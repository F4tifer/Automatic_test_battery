# simulation/dummy_dut_controller.py

import time
import random
import threading
import logging
import numpy as np
from typing import Optional, Dict, Any

class DummyDutController:
    """
    Simuluje chování DUT pro testování bez reálného hardware.
    Implementuje všechny metody očekávané reálným DutControllerem.
    Reaguje na nastavení režimů a simuluje změny napětí, proudu, teplot.
    """

    def __init__(self, dut_cmds: dict, initial_voltage: float = 3.7, initial_mode: str = "IDLE"):
        """
        Inicializuje simulátor.

        Args:
            dut_cmds: Slovník příkazů (použito jen pro referenci).
            initial_voltage: Počáteční napětí baterie.
            initial_mode: Počáteční režim (IDLE, CHARGING, DISCHARGING).
        """
        logging.info("Initializing Dummy DUT Controller...")
        self.cmds = dut_cmds # Nepoužíváme, ale zachováváme pro kompatibilitu rozhraní

        # --- Simulovaný stav ---
        self._voltage: float = float(initial_voltage)
        self._current: float = 0.0
        self._mode: str = initial_mode.upper()
        self._is_charging_sw_enabled: bool = False
        self._is_charging_hw_enabled: bool = False
        self._is_usb_connected: bool = False
        self._is_forced_discharging: bool = self._mode == "DISCHARGING" # Sledujeme explicitní příkaz

        # Ostatní simulované hodnoty
        self._dut_time_ms: int = random.randint(100000, 200000)
        self.ambient_temp: float = 25.0
        self._ntc_temp: float = self.ambient_temp + random.uniform(-0.5, 0.5)
        self._vsys: float = 0.0
        self._die_temp: float = self.ambient_temp + 5.0 + random.uniform(-1.0, 1.0)
        self._iba_meas_status: str = "0x18"
        self._buck_status: str = "0x00"

        # --- Parametry simulace ---
        # Načtení z configu by bylo lepší, zde pevné hodnoty
        self.simulation_step_s: float = 0.5      # Krok simulace v sekundách
        self.charge_rate_v_per_s: float = 0.05 # Rychlost nabíjení V/s
        self.discharge_rate_v_per_s: float = 0.08 # Rychlost vybíjení V/s
        self.max_voltage: float = 4.2           # Max bezpečné napětí
        self.min_voltage: float = 3.0           # Min bezpečné napětí
        self.charging_current_ma_cc: float = 500.0 # Proud v CC fázi
        self.discharging_current_ma: float = -300.0 # Proud při vybíjení (záporný)
        self.idle_current_ma: float = -1.5       # Samovybíjení mA
        self.full_charge_current_threshold_ma: float = 50.0 # Ukončení CV fáze
        # Teplotní parametry
        self.charge_heating_factor: float = 0.02 # °C/s na Volt nad min_voltage
        self.discharge_heating_factor: float = 0.01
        self.cooling_rate_factor: float = 0.005 # Faktor chladnutí (1/časová konstanta)
        self.max_ntc_temp: float = 50.0         # Bezpečnostní limity teplot
        self.max_die_temp: float = 60.0

        # --- Interní řízení ---
        self._stop_event = threading.Event()
        self._simulation_thread: Optional[threading.Thread] = None # Inicializace na None
        self._lock = threading.Lock() # Zámek pro bezpečný přístup k sdíleným stavům
        self._start_simulation_thread() # Spustíme vlákno

        logging.info(f"Dummy DUT Controller Initialized. Initial state: V={self._voltage:.3f}V, Mode={self._mode}")

    def _start_simulation_thread(self):
        """Spustí simulační vlákno, pokud ještě neběží."""
        if self._simulation_thread is None or not self._simulation_thread.is_alive():
            self._stop_event.clear()
            self._simulation_thread = threading.Thread(target=self._simulate_battery, name="DummyDUTSimThread", daemon=True)
            self._simulation_thread.start()
            logging.info("Dummy DUT simulation thread started.")
        else:
            logging.debug("Dummy DUT simulation thread already running.")

    def _simulate_battery(self):
        """Hlavní smyčka simulace běžící ve vlákně."""
        logging.debug(f"Dummy DUT simulation loop starting (step={self.simulation_step_s}s)...")
        step_s = self.simulation_step_s

        while not self._stop_event.is_set():
            loop_start_time = time.monotonic()

            # --- Získání aktuálních řídících stavů pod zámkem ---
            with self._lock:
                v_now = self._voltage
                mode_now = self._mode
                ntc_now = self._ntc_temp
                die_now = self._die_temp
                can_charge = self._is_usb_connected and self._is_charging_sw_enabled and self._is_charging_hw_enabled
                is_forced_discharging = self._is_forced_discharging # Použijeme nový flag

            # --- Určení efektivního režimu ---
            effective_mode = "IDLE" # Výchozí
            if can_charge and v_now < self.max_voltage:
                 effective_mode = "CHARGING"
            elif is_forced_discharging and v_now > self.min_voltage:
                 # Vybíjení běží jen pokud bylo explicitně vynuceno
                 effective_mode = "DISCHARGING"

            # --- Výpočet změn ---
            delta_v = 0.0
            current_calc = self.idle_current_ma
            ntc_temp_change = 0.0
            die_temp_change = 0.0
            final_mode_this_step = effective_mode # Může se změnit při ukončení chg/dischg

            if effective_mode == "CHARGING":
                cv_phase_threshold = self.max_voltage - 0.1
                if v_now >= cv_phase_threshold: # CV Fáze
                     # Nelineární pokles proudu v CV fázi
                     charge_completion = max(0, (self.max_voltage - v_now)) / max(1e-6, (self.max_voltage - cv_phase_threshold))
                     current_calc = self.full_charge_current_threshold_ma + \
                                      (self.charging_current_ma_cc - self.full_charge_current_threshold_ma) * charge_completion**1.5
                else: # CC Fáze
                    current_calc = self.charging_current_ma_cc
                current_calc *= random.uniform(0.98, 1.02)
                delta_v = self.charge_rate_v_per_s * step_s

                # Ohřev
                heat_factor = max(0, v_now - self.min_voltage)
                ntc_temp_change += self.charge_heating_factor * heat_factor * step_s
                die_temp_change += self.charge_heating_factor * heat_factor * 1.5 * step_s

                # Ukončení nabíjení
                if current_calc <= self.full_charge_current_threshold_ma and v_now >= cv_phase_threshold:
                    final_mode_this_step = "IDLE"
                    current_calc = self.idle_current_ma * random.uniform(0.8, 1.2)
                    logging.debug("Dummy DUT: Charge complete (low current).")

            elif effective_mode == "DISCHARGING":
                current_calc = self.discharging_current_ma * random.uniform(0.98, 1.02)
                delta_v = -self.discharge_rate_v_per_s * step_s

                # Ohřev
                heat_factor = max(0, v_now - self.min_voltage)
                ntc_temp_change += self.discharge_heating_factor * heat_factor * step_s
                die_temp_change += self.discharge_heating_factor * heat_factor * 1.2 * step_s

                # Ukončení vybíjení
                if v_now + delta_v <= self.min_voltage:
                    final_mode_this_step = "IDLE"
                    current_calc = self.idle_current_ma * random.uniform(0.8, 1.2)
                    delta_v = self.min_voltage - v_now # Přesně na limit
                    logging.debug("Dummy DUT: Discharge complete (min voltage).")

            # Chladnutí (vždy probíhá, i při nabíjení/vybíjení)
            ntc_temp_change += (self.ambient_temp - ntc_now) * self.cooling_rate_factor * step_s
            die_temp_change += (self.ambient_temp + 5 - die_now) * self.cooling_rate_factor * step_s

            # --- Aktualizace stavů pod zámkem ---
            with self._lock:
                # Aktualizace času DUT
                self._dut_time_ms += int(step_s * 1000)

                # Nastavení režimu
                if self._mode != final_mode_this_step:
                    logging.debug(f"Dummy DUT Mode changed: {self._mode} -> {final_mode_this_step} (V={self._voltage:.3f})")
                    self._mode = final_mode_this_step
                    # Pokud přejdeme na IDLE z DISCHARGING, vynulujeme force flag
                    if self._mode == "IDLE" and is_forced_discharging:
                         self._is_forced_discharging = False

                # Aktualizace napětí s omezením
                self._voltage += delta_v
                self._voltage = max(self.min_voltage - 0.05, min(self.max_voltage + 0.05, self._voltage))
                self._current = current_calc

                # Aktualizace teplot s omezením
                self._ntc_temp += ntc_temp_change + random.uniform(-0.01, 0.01) * step_s
                self._die_temp += die_temp_change + random.uniform(-0.02, 0.02) * step_s
                self._ntc_temp = max(0, min(self.max_ntc_temp, self._ntc_temp))
                self._die_temp = max(5, min(self.max_die_temp, self._die_temp))

                # Aktualizace statusů
                self._vsys = 5.0 + random.uniform(-0.05, 0.05) if self._is_usb_connected else 0.0
                if self._mode == "CHARGING": self._iba_meas_status="0x0C"; self._buck_status="0x0C"
                elif self._mode == "DISCHARGING": self._iba_meas_status="0x0C"; self._buck_status="0x00"
                else: self._iba_meas_status="0x18"; self._buck_status="0x00"

            # --- Čekání ---
            loop_end_time = time.monotonic()
            sleep_duration = max(0, step_s - (loop_end_time - loop_start_time))
            self._stop_event.wait(sleep_duration) # Přerušitelné čekání

        logging.debug("Dummy DUT simulation loop finished.")

    # --- Metody pro získání dat (bezpečný přístup pod zámkem) ---
    def get_battery_voltage(self) -> Optional[float]:
        with self._lock: v = self._voltage
        return v + random.uniform(-0.002, 0.002)

    def get_battery_current(self) -> Optional[float]:
        with self._lock: i = self._current
        return i + random.uniform(-1.0, 1.0) # Trochu větší šum proudu

    def get_operation_mode(self) -> Optional[str]:
        with self._lock: m = self._mode
        return m

    def get_dut_timestamp(self) -> Optional[int]:
        with self._lock: t = self._dut_time_ms
        return t

    def get_ntc_temp(self) -> Optional[float]:
        with self._lock: temp = self._ntc_temp
        return temp + random.uniform(-0.05, 0.05)

    def get_vsys(self) -> Optional[float]:
        with self._lock: vs = self._vsys
        return vs

    def get_die_temp(self) -> Optional[float]:
        with self._lock: temp = self._die_temp
        return temp + random.uniform(-0.1, 0.1)

    def get_iba_meas_status(self) -> Optional[str]:
        with self._lock: stat = self._iba_meas_status
        return stat

    def get_buck_status(self) -> Optional[str]:
        with self._lock: stat = self._buck_status
        return stat

    # --- Ovládací metody (nastavují stavy pod zámkem) ---
    def enable_charging_sw(self) -> bool:
        logging.info("Dummy DUT: Received Enable Charging (SW)")
        with self._lock: self._is_charging_sw_enabled = True
        return True

    def disable_charging_sw(self) -> bool:
        logging.info("Dummy DUT: Received Disable Charging (SW)")
        with self._lock: self._is_charging_sw_enabled = False
        return True

    def notify_usb_connected(self, connected: bool):
        logging.info(f"Dummy DUT: Notified USB Connected = {connected}")
        with self._lock: self._is_usb_connected = connected

    def notify_charger_hw_enabled(self, enabled: bool):
         logging.info(f"Dummy DUT: Notified Charger HW Enabled = {enabled}")
         with self._lock: self._is_charging_hw_enabled = enabled

    def force_discharge_mode(self, discharge: bool):
        """Explicitně zapne/vypne PŘÍZNAK pro vynucené vybíjení."""
        with self._lock:
            if discharge:
                if self._voltage > self.min_voltage:
                    logging.info("Dummy DUT: Forcing DISCHARGING mode flag ON.")
                    self._is_forced_discharging = True
                    self._mode = "DISCHARGING" # Okamžitě přepneme i mód pro rychlejší reakci
                else:
                    logging.warning("Dummy DUT: Cannot force DISCHARGING, voltage too low.")
                    self._is_forced_discharging = False # Zajistíme, že je flag vypnutý
            else: # discharge == False
                if self._is_forced_discharging:
                    logging.info("Dummy DUT: Forcing DISCHARGING mode flag OFF.")
                self._is_forced_discharging = False
                # Mód se sám přepne na IDLE v simulační smyčce, pokud nejsou splněny podmínky pro CHARGING
        return True

    # --- Cleanup ---
    def close(self):
        """Zastaví simulační vlákno."""
        logging.info("Closing Dummy DUT Controller...")
        if self._simulation_thread and self._simulation_thread.is_alive():
            self._stop_event.set()
            self._simulation_thread.join(timeout=max(1.0, self.simulation_step_s * 2))
            if self._simulation_thread.is_alive():
                logging.warning("Dummy DUT simulation thread did not stop gracefully.")
            else:
                 logging.debug("Dummy DUT simulation thread joined successfully.")
        else:
             logging.debug("Dummy DUT simulation thread already stopped or not started.")
        self._simulation_thread = None # Resetovat vlákno
        logging.info("Dummy DUT Controller closed.")

    def __del__(self):
        # Zajistí zastavení vlákna i při smazání objektu
        self.close()
import time
import random
import threading
import logging

class DummyDutController:
    """Simuluje chování DUT pro testování bez reálného hardware."""

    def __init__(self, dut_cmds: dict, initial_voltage=3.7, initial_mode="IDLE"):
        logging.info("Initializing Dummy DUT Controller...")
        self.cmds = dut_cmds # Uložíme pro referenci, nepoužíváme pro komunikaci

        # Simulovaný stav baterie
        self._voltage = initial_voltage
        self._current = 0.0
        self._mode = initial_mode # "IDLE", "CHARGING", "DISCHARGING"
        self._is_charging_sw_enabled = False
        self._is_charging_hw_enabled = False
        self._is_usb_connected = False

        # Simulované hodnoty
        self._dut_time_ms = random.randint(100000, 200000)
        self._ntc_temp = 25.0 + random.uniform(-0.5, 0.5)
        self._vsys = 0.0 # Výchozí 0V, pokud není USB připojeno
        self._die_temp = 30.0 + random.uniform(-1.0, 1.0)
        self._iba_meas_status = "0x18" # Výchozí pro IDLE
        self._buck_status = "0x00"     # Výchozí pro IDLE

        # Parametry simulace (lze je případně načítat z configu?)
        self.charge_rate_v_per_s = 0.05 # Zrychleno pro testování
        self.discharge_rate_v_per_s = 0.08 # Zrychleno pro testování
        self.max_voltage = 4.2
        self.min_voltage = 3.0
        self.charging_current_ma = 500
        self.discharging_current_ma = -300
        self.idle_current_ma = 2.0
        self.full_charge_current_threshold_ma = 50
        # Teplotní parametry simulace
        self.ambient_temp = 25.0
        self.charge_temp_increase_per_s = 0.02 # Rychlejší ohřev
        self.discharge_temp_increase_per_s = 0.01
        self.cooling_rate_factor = 0.01

        self._stop_event = threading.Event()
        self._simulation_thread = threading.Thread(target=self._simulate_battery, daemon=True)
        self._simulation_thread.start()
        logging.info("Dummy DUT Controller Initialized and simulation thread started.")

    def _simulate_battery(self):
        simulation_step_ms = 1000 # ms
        while not self._stop_event.is_set():
            loop_start_time = time.monotonic()
            step_s = simulation_step_ms / 1000.0

            # Aktualizace času DUT
            self._dut_time_ms += simulation_step_ms

            # Určení aktuálního režimu
            previous_mode = self._mode
            effective_mode = "IDLE"
            if self._is_usb_connected and self._is_charging_sw_enabled and self._is_charging_hw_enabled:
                if self._voltage < self.max_voltage:
                    effective_mode = "CHARGING"
            elif self._mode == "DISCHARGING": # Pokud byl explicitně zapnutý
                 if self._voltage > self.min_voltage:
                      effective_mode = "DISCHARGING"

            self._mode = effective_mode

            # Aktualizace napětí, proudu a teplot
            if self._mode == "CHARGING":
                self._voltage += self.charge_rate_v_per_s * step_s
                self._voltage = min(self._voltage, self.max_voltage)
                self._ntc_temp += self.charge_temp_increase_per_s * step_s
                self._die_temp += self.charge_temp_increase_per_s * 1.5 * step_s # Die se ohřívá víc
                if self.max_voltage - self._voltage < 0.1: # Konec nabíjení (CV fáze)
                     charge_completion = (self.max_voltage - self._voltage) / 0.1 # 0..1
                     self._current = self.full_charge_current_threshold_ma + \
                                     (self.charging_current_ma - self.full_charge_current_threshold_ma) * charge_completion**2 # Nelineární pokles proudu
                     self._current *= random.uniform(0.9, 1.1) # Šum
                     if self._current <= self.full_charge_current_threshold_ma:
                         self._mode = "IDLE"
                         self._current = self.idle_current_ma * random.uniform(0.8, 1.2)
                         logging.info("Dummy DUT: Charging complete (low current). Switching to IDLE.")
                else: # CC fáze
                    self._current = self.charging_current_ma * random.uniform(0.95, 1.05)

            elif self._mode == "DISCHARGING":
                self._voltage -= self.discharge_rate_v_per_s * step_s
                self._voltage = max(self._voltage, self.min_voltage)
                self._current = self.discharging_current_ma * random.uniform(0.95, 1.05)
                self._ntc_temp += self.discharge_temp_increase_per_s * step_s
                self._die_temp += self.discharge_temp_increase_per_s * 1.2 * step_s
                if self._voltage <= self.min_voltage:
                    self._mode = "IDLE"
                    self._current = self.idle_current_ma * random.uniform(0.8, 1.2)
                    logging.info("Dummy DUT: Discharging complete (min voltage). Switching to IDLE.")

            elif self._mode == "IDLE":
                 self._current = self.idle_current_ma * random.uniform(0.8, 1.2)
                 # Pomalu chladne k okolní teplotě
                 temp_diff_ntc = (self.ambient_temp - self._ntc_temp) * self.cooling_rate_factor * step_s
                 temp_diff_die = (self.ambient_temp + 5 - self._die_temp) * self.cooling_rate_factor * step_s # Die může být teplejší
                 self._ntc_temp += temp_diff_ntc + random.uniform(-0.01, 0.01) * step_s
                 self._die_temp += temp_diff_die + random.uniform(-0.02, 0.02) * step_s

            # Aktualizace ostatních hodnot
            self._vsys = 5.0 + random.uniform(-0.05, 0.05) if self._is_usb_connected else 0.0
            if self._mode == "CHARGING":
                self._iba_meas_status = "0x0C"
                self._buck_status = "0x0C"
            elif self._mode == "DISCHARGING":
                 self._iba_meas_status = "0x0C"
                 self._buck_status = "0x00" # Předpoklad
            else: # IDLE
                 self._iba_meas_status = "0x18"
                 self._buck_status = "0x00"

            # Omezení teplot pro realističnost
            self._ntc_temp = max(0, min(50, self._ntc_temp))
            self._die_temp = max(5, min(60, self._die_temp))

            if previous_mode != self._mode:
                 logging.debug(f"Dummy DUT Mode changed to: {self._mode}")

            # Čekání
            loop_end_time = time.monotonic()
            sleep_time = max(0, (simulation_step_ms / 1000.0) - (loop_end_time - loop_start_time))
            self._stop_event.wait(sleep_time)

    # --- Metody pro získání dat ---
    def get_battery_voltage(self) -> float | None: return self._voltage + random.uniform(-0.002, 0.002)
    def get_battery_current(self) -> float | None: return self._current + random.uniform(-0.5, 0.5)
    def get_operation_mode(self) -> str | None: return self._mode
    def get_dut_timestamp(self) -> int | None: return self._dut_time_ms
    def get_ntc_temp(self) -> float | None: return self._ntc_temp + random.uniform(-0.05, 0.05)
    def get_vsys(self) -> float | None: return self._vsys
    def get_die_temp(self) -> float | None: return self._die_temp + random.uniform(-0.1, 0.1)
    def get_iba_meas_status(self) -> str | None: return self._iba_meas_status
    def get_buck_status(self) -> str | None: return self._buck_status

    # --- Ovládací metody ---
    def enable_charging_sw(self) -> bool: logging.info("Dummy DUT: Received Enable Charging (SW)"); self._is_charging_sw_enabled = True; return True
    def disable_charging_sw(self) -> bool: logging.info("Dummy DUT: Received Disable Charging (SW)"); self._is_charging_sw_enabled = False; return True
    def notify_usb_connected(self, connected: bool): logging.info(f"Dummy DUT: Notified USB Connected = {connected}"); self._is_usb_connected = connected
    def notify_charger_hw_enabled(self, enabled: bool): logging.info(f"Dummy DUT: Notified Charger HW Enabled = {enabled}"); self._is_charging_hw_enabled = enabled
    def force_discharge_mode(self, discharge: bool):
        if discharge:
            if self._voltage > self.min_voltage: logging.info("Dummy DUT: Forcing DISCHARGING mode."); self._mode = "DISCHARGING"
            else: logging.warning("Dummy DUT: Cannot force DISCHARGING, voltage too low.")
        elif self._mode == "DISCHARGING": logging.info("Dummy DUT: Forcing IDLE mode (stopping discharge)."); self._mode = "IDLE"

    # --- Cleanup ---
    def close(self):
        logging.info("Closing Dummy DUT Controller...")
        self._stop_event.set()
        if self._simulation_thread.is_alive(): self._simulation_thread.join(timeout=2)
        logging.info("Dummy DUT Controller closed.")
    def __del__(self): self.close()
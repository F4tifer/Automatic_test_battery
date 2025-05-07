# test_logic/test_steps.py

import time
import logging
from pathlib import Path
import random # Pro Random Wonder test
from typing import TYPE_CHECKING, Optional

# ... (Podmíněný import typů - stejný) ...
if TYPE_CHECKING:
    from hardware_ctl.relay_controller import RelayController
    from hardware_ctl.temp_controller import TempController
    from hardware_ctl.dut_controller import DutController
    from simulation.dummy_dut_controller import DummyDutController
    DutControllerTypes = DutController | DummyDutController
    from test_logic.data_logger import DataLogger

# ... (_notify_dut_relay_state - stejná) ...
def _notify_dut_relay_state(dut: 'DutControllerTypes', relay_state: dict):
    if hasattr(dut, 'notify_usb_connected'): dut.notify_usb_connected(relay_state.get('usb_connected', False)) # type: ignore
    if hasattr(dut, 'notify_charger_hw_enabled'): dut.notify_charger_hw_enabled(relay_state.get('charger_hw_enabled', False)) # type: ignore


# --- Stávající kroky (mírně upravené pro logování) ---

def step_set_temp(temp_ctl: 'TempController', temp_c: float) -> bool:
    logging.info(f"--- STEP 1: Setting Target Temperature to {temp_c}°C ---")
    if not temp_ctl.set_temperature(temp_c):
        logging.error("Failed to send set temperature command/log.")
        return False
    logging.info("Target temperature set instruction sent/logged.")
    return True

def step_relax(duration_s: int, step_name: str):
    # ... (Funkce beze změny, jen používá logging) ...
    logging.info(f"--- STEP {step_name}: Relaxing for {duration_s / 3600:.1f} hour(s) ({duration_s} seconds) ---")
    if duration_s <= 0: logging.info("Relaxation duration is zero or negative, skipping."); return
    end_time = time.monotonic() + duration_s
    log_interval = 60
    next_log_time = time.monotonic() + log_interval
    logging.info(f"Relaxation started. Ends approx. at {time.strftime('%H:%M:%S', time.localtime(time.time() + duration_s))}")
    while time.monotonic() < end_time:
        current_time = time.monotonic(); remaining_time = end_time - current_time
        if current_time >= next_log_time:
             logging.info(f"  Relaxing... {remaining_time / 60:.1f} minute(s) remaining.")
             next_log_time += log_interval
        sleep_duration = min(1.0, remaining_time, next_log_time - current_time)
        if sleep_duration > 0: time.sleep(sleep_duration)
    logging.info("Relaxation complete.")

# --- ZMĚNA: Logger se předává, ale nestartuje/nestopuje uvnitř ---
def step_discharge(dut: 'DutControllerTypes', relay: 'RelayController', logger: 'DataLogger', config: dict) -> bool:
    """Krok Vybíjení (použito v Linear módu). Logger musí běžet."""
    discharge_limit_v = config['linear_discharge_voltage_limit'] # Použijeme specifický parametr
    logging.info(f"--- STEP Discharge (Linear): Discharging to {discharge_limit_v:.2f} V ---")

    if not logger.is_logging: # Kontrola, zda logger běží
         logging.error("Discharge step cannot run: DataLogger is not active.")
         return False

    logging.info("Configuring hardware for discharge...")
    # ... (Nastavení relé a notifikace dummy - stejné) ...
    relay.disconnect_usb()
    dut.disable_charging_sw()
    relay.disable_charger_hw()
    _notify_dut_relay_state(dut, {'usb_connected': False, 'charger_hw_enabled': False})

    discharge_started = False
    if hasattr(dut, 'force_discharge_mode'):
        logging.info("Telling Dummy DUT to start discharging...")
        dut.force_discharge_mode(True); discharge_started = True # type: ignore
    else:
        logging.info("Assuming real DUT/external load handles discharge initiation.")
        # Zde logika pro reálné DUT, pokud potřebuje start
        discharge_started = True

    if not discharge_started: logging.error("Could not initiate discharge process."); return False
    time.sleep(2)

    logging.info("Discharging...")
    last_voltage_print_time = 0
    monitoring_interval = 1

    try:
        while True:
            voltage = dut.get_battery_voltage()
            if voltage is None: logging.warning("Failed to read voltage during discharge. Retrying..."); time.sleep(5); continue

            current_time = time.monotonic()
            if current_time - last_voltage_print_time > 15:
                 logging.info(f"  Discharging... V={voltage:.3f}V (Target: {discharge_limit_v:.2f}V)")
                 last_voltage_print_time = current_time

            if voltage <= discharge_limit_v:
                logging.info(f"Discharge limit reached at {voltage:.3f} V.")
                break

            sleep_s = max(monitoring_interval, logger.log_interval / 2)
            time.sleep(sleep_s)

    except KeyboardInterrupt:
         logging.warning("\nDischarge interrupted by user.")
         if hasattr(dut, 'force_discharge_mode'): dut.force_discharge_mode(False) # type: ignore
         return False
    finally:
        logging.info("Stopping discharge process (hardware/simulation)...")
        if hasattr(dut, 'force_discharge_mode'): dut.force_discharge_mode(False) # type: ignore
        # Zde stop pro reálné DUT

    logging.info("Discharge step complete.")
    return True

def step_connect_usb_disable_charge(relay: 'RelayController', dut: 'DutControllerTypes') -> bool:
    # ... (Funkce beze změny - jen používá logging) ...
    logging.info("--- STEP Connect USB / Disable Charge ---")
    logging.info("Sending SW disable charging command...")
    if not dut.disable_charging_sw(): logging.warning("Failed SW disable command.")
    logging.info("Disabling charger HW via relay...")
    relay.disable_charger_hw()
    logging.info("Connecting USB via relay...")
    relay.connect_usb()
    _notify_dut_relay_state(dut, {'usb_connected': True, 'charger_hw_enabled': False})
    logging.info("USB connected, charging should be disabled.")
    return True

def step_enable_charging(relay: 'RelayController', dut: 'DutControllerTypes') -> bool:
    # ... (Funkce beze změny - jen používá logging) ...
    logging.info("--- STEP Enable Charging ---")
    logging.info("Enabling charger HW via relay...")
    relay.enable_charger_hw()
    logging.info("Sending SW enable charging command...")
    sw_success = dut.enable_charging_sw()
    _notify_dut_relay_state(dut, {'usb_connected': True, 'charger_hw_enabled': True})
    if not sw_success: logging.warning("Failed SW enable command.")
    logging.info("Charging enabled (HW relay ON, SW command sent).")
    return True

# --- ZMĚNA: Logger se předává, ale nestartuje/nestopuje uvnitř ---
def step_charge(dut: 'DutControllerTypes', logger: 'DataLogger', config: dict) -> bool:
    """Krok Nabíjení (použito v Linear módu). Logger musí běžet."""
    idle_current_threshold = config['linear_charge_idle_current_threshold_ma'] # Specifický parametr
    logging.info(f"--- STEP Charge (Linear): Charging until IDLE (Current < {idle_current_threshold} mA) ---")

    if not logger.is_logging:
        logging.error("Charge step cannot run: DataLogger is not active.")
        return False

    start_time = time.monotonic()
    max_charge_time_s = config.get('test_plan', {}).get('max_charge_time_hours', 10) * 3600
    last_status_print_time = 0
    verification_period_s = 30
    stable_end_detected = False
    verification_start_time = 0
    monitoring_interval = 5

    try:
        while time.monotonic() - start_time < max_charge_time_s:
            # ... (Smyčka monitorování - stejná jako předtím, jen používá logging) ...
            current_monotonic_time = time.monotonic()
            mode = dut.get_operation_mode(); current = dut.get_battery_current(); voltage = dut.get_battery_voltage()
            if mode is None and current is None: logging.warning("Failed read mode/current. Retrying..."); time.sleep(monitoring_interval); continue
            if current_monotonic_time - last_status_print_time > 30:
                 mode_str=f"Mode={mode}" if mode is not None else "N/A"; curr_str=f"I={current:.1f}mA" if current is not None else "N/A"; volt_str=f"V={voltage:.3f}V" if voltage is not None else "N/A"
                 elapsed_m=(current_monotonic_time - start_time)/60; logging.info(f"  Charging...({elapsed_m:.1f}m): {mode_str}, {curr_str}, {volt_str}")
                 last_status_print_time = current_monotonic_time

            charge_ended_condition = (mode=="IDLE") or (current is not None and abs(current) < idle_current_threshold)
            if charge_ended_condition:
                if not stable_end_detected: logging.info("Charge end condition detected. Verifying..."); stable_end_detected=True; verification_start_time=current_monotonic_time
                elif current_monotonic_time - verification_start_time >= verification_period_s: logging.info("Charge termination stable."); break
                else: logging.debug(f"  Verifying stability... {current_monotonic_time - verification_start_time:.0f}/{verification_period_s:.0f}s")
            elif stable_end_detected: logging.info("Charge termination unstable. Resetting."); stable_end_detected=False
            time.sleep(monitoring_interval)
        else:
             logging.error(f"Charging timeout after {max_charge_time_s / 3600:.1f} hours.")
             return False
    except KeyboardInterrupt: logging.warning("\nCharging interrupted."); return False
    finally: pass # Logger se stopne v main

    logging.info("Charging step complete.")
    return True

# --- NOVÉ KROKY pro nové módy ---

def step_switching_phase(dut: 'DutControllerTypes', relay: 'RelayController', logger: 'DataLogger', config: dict) -> bool:
    """Provádí fázi Switching Testu."""
    duration_s = config.get('switching_phase_duration_s', 300) # Default 5 min
    interval_s = config.get('switching_interval_s', 5)       # Default 5s
    charge_cmd_key = config.get('switching_charge_command', 'enable_charging')
    discharge_cmd_key = config.get('switching_discharge_command', 'disable_charging')
    logging.info(f"--- STEP Switching Phase: Duration={duration_s}s, Interval={interval_s}s ---")

    if not logger.is_logging: logging.error("Switching step: Logger not active."); return False
    if interval_s <= 0: logging.error("Switching interval must be positive."); return False

    start_time = time.monotonic()
    end_time = start_time + duration_s
    switch_state = True # Začneme "zapnutím" (charge command)
    last_switch_time = 0

    try:
        while time.monotonic() < end_time:
            current_monotonic_time = time.monotonic()
            # Čas na přepnutí?
            if current_monotonic_time - last_switch_time >= interval_s:
                last_switch_time = current_monotonic_time
                switch_state = not switch_state # Přepnout stav
                command_key = charge_cmd_key if switch_state else discharge_cmd_key
                logging.info(f"Switching state to {'ON' if switch_state else 'OFF'} (Command: {config.get('dut_commands',{}).get(command_key, 'N/A')})")

                # Odeslání příkazu - použijeme interní _send_command pro přístup přes klíč
                if hasattr(dut, '_send_command'):
                    # Zkusíme poslat příkaz, neřešíme zde návratovou hodnotu pro jednoduchost simulace
                    # Reálná implementace by mohla kontrolovat úspěch
                    dut._send_command(command_key) # type: ignore
                elif hasattr(dut, 'force_discharge_mode'): # Pro Dummy DUT
                     if command_key == 'disable_charging': dut.disable_charging_sw() # Simulace disable
                     elif command_key == 'enable_charging': dut.enable_charging_sw() # Simulace enable
                     # Jiné příkazy by zde potřebovaly specifickou simulaci
                else:
                     logging.warning("Cannot send switching command - DUT controller type unknown or lacks method.")

                # Ovládání relé (může být redundantní, pokud příkazy ovládají i HW)
                # Přidáme volitelně ovládání relé pro simulaci enable/disable
                # if switch_state: relay.enable_charger_hw() # Nebo jen SW příkaz?
                # else: relay.disable_charger_hw()
                # _notify_dut_relay_state(dut, {'usb_connected': True, 'charger_hw_enabled': switch_state}) # Potenciálně

            # Krátká pauza - menší než log interval, ale ne příliš krátká
            sleep_s = min(max(0.1, logger.log_interval / 5), interval_s / 2)
            time.sleep(sleep_s)

    except KeyboardInterrupt:
         logging.warning("\nSwitching phase interrupted by user.")
         return False
    finally:
        # Uvést DUT do definovaného stavu? Např. disable charging.
        logging.info("Switching phase finished. Disabling charging.")
        dut.disable_charging_sw()
        relay.disable_charger_hw()
        _notify_dut_relay_state(dut, {'usb_connected': True, 'charger_hw_enabled': False})

    logging.info("Switching phase complete.")
    return True


def step_random_wonder(dut: 'DutControllerTypes', relay: 'RelayController', logger: 'DataLogger', config: dict) -> bool:
    """Provádí fázi Random Wonder Testu."""
    duration_s = config.get('random_duration_s', 1800) # Default 30 min
    min_phase_s = config.get('random_min_phase_s', 10)
    max_phase_s = config.get('random_max_phase_s', 120)
    charge_prob = config.get('random_charge_probability', 0.6)
    max_v = config.get('random_max_voltage', 4.25)
    min_v = config.get('random_min_voltage', 2.9)
    logging.info(f"--- STEP Random Wonder: Duration={duration_s}s ---")
    logging.info(f"  Params: PhaseTime=({min_phase_s}-{max_phase_s})s, ChargeProb={charge_prob*100}%, V_limits=({min_v}-{max_v})V")

    if not logger.is_logging: logging.error("Random step: Logger not active."); return False
    if not (0 <= charge_prob <= 1): logging.error("Charge probability must be between 0 and 1."); return False
    if min_phase_s > max_phase_s or min_phase_s <= 0: logging.error("Invalid min/max phase duration."); return False

    start_time = time.monotonic()
    end_time = start_time + duration_s
    current_phase_end_time = start_time
    is_charging_phase = False # Začneme vybíjením nebo IDLE?

    try:
        while time.monotonic() < end_time:
            current_monotonic_time = time.monotonic()

            # Je čas na změnu fáze?
            if current_monotonic_time >= current_phase_end_time:
                # Náhodná délka další fáze
                phase_duration = random.uniform(min_phase_s, max_phase_s)
                current_phase_end_time = current_monotonic_time + phase_duration

                # Náhodný výběr další fáze (nabíjení/vybíjení)
                previous_phase_charging = is_charging_phase
                if random.random() < charge_prob:
                    is_charging_phase = True
                else:
                    is_charging_phase = False

                logging.info(f"Random phase change: {'Charging' if is_charging_phase else 'Discharging'} for {phase_duration:.1f}s (until {time.strftime('%H:%M:%S', time.localtime(time.time() + phase_duration))})")

                # Nastavení stavu DUT/Relé
                if is_charging_phase:
                    # Zapnout nabíjení
                    relay.enable_charger_hw() # Předpoklad USB je připojeno
                    dut.enable_charging_sw()
                    _notify_dut_relay_state(dut, {'usb_connected': True, 'charger_hw_enabled': True})
                    if hasattr(dut, 'force_discharge_mode'): dut.force_discharge_mode(False) # Ukončit dummy vybíjení
                else:
                    # Zapnout vybíjení (nebo jen vypnout nabíjení)
                    dut.disable_charging_sw()
                    relay.disable_charger_hw()
                    _notify_dut_relay_state(dut, {'usb_connected': True, 'charger_hw_enabled': False})
                    if hasattr(dut, 'force_discharge_mode'): dut.force_discharge_mode(True) # Spustit dummy vybíjení
                    # Zde by byla logika pro aktivní vybíjení reálného DUT, pokud existuje

            # Bezpečnostní kontrola napětí
            voltage = dut.get_battery_voltage()
            if voltage is not None:
                if is_charging_phase and voltage >= max_v:
                    logging.warning(f"Random: Max voltage limit {max_v}V reached during charge. Forcing discharge/idle.")
                    is_charging_phase = False # Přepnout na vybíjení/idle
                    current_phase_end_time = current_monotonic_time # Okamžitá změna fáze
                    dut.disable_charging_sw(); relay.disable_charger_hw()
                    _notify_dut_relay_state(dut, {'usb_connected': True, 'charger_hw_enabled': False})
                    if hasattr(dut, 'force_discharge_mode'): dut.force_discharge_mode(True)
                elif not is_charging_phase and voltage <= min_v:
                     logging.warning(f"Random: Min voltage limit {min_v}V reached during discharge. Forcing charge/idle.")
                     is_charging_phase = True # Přepnout na nabíjení/idle
                     current_phase_end_time = current_monotonic_time
                     relay.enable_charger_hw(); dut.enable_charging_sw()
                     _notify_dut_relay_state(dut, {'usb_connected': True, 'charger_hw_enabled': True})
                     if hasattr(dut, 'force_discharge_mode'): dut.force_discharge_mode(False)

            # Čekání
            sleep_s = min(max(0.1, logger.log_interval / 2), current_phase_end_time - current_monotonic_time, 1.0)
            if sleep_s > 0: time.sleep(sleep_s)
            else: time.sleep(0.05) # Krátká pauza, pokud je konec fáze blízko

    except KeyboardInterrupt:
         logging.warning("\nRandom wonder phase interrupted by user.")
         return False
    finally:
        # Uvést do definovaného stavu (např. nabíjení vypnuto)
        logging.info("Random wonder phase finished. Disabling charging.")
        dut.disable_charging_sw()
        relay.disable_charger_hw()
        _notify_dut_relay_state(dut, {'usb_connected': True, 'charger_hw_enabled': False})
        if hasattr(dut, 'force_discharge_mode'): dut.force_discharge_mode(False)

    logging.info("Random wonder step complete.")
    return True


# --- ZMĚNA: step_store_files přijímá upravený test_phase ---
def step_store_files(log_file: Path | None, output_dir: Path, temp_c: float, cycle_num: int, test_phase: str) -> Path | None:
    """Přejmenuje a uloží log soubor."""
    logging.info(f"--- Storing Log File for Phase: {test_phase} ---")
    if log_file is None or not log_file.exists():
        logging.warning(f"Temporary log file {log_file} not found or is None. Skipping storage.")
        return None

    # Cílový adresář pro teplotu a cyklus
    target_dir = output_dir / f"temp_{temp_c:.0f}C" / f"cycle_{cycle_num+1}"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logging.error(f"Failed to create target directory {target_dir}: {e}")
        return log_file

    # Finální název souboru: TempC_cycleN_Mode_Phase.csv
    # test_phase zde bude např. "linear_discharge", "switching_main", "random_main"
    target_filename = f"{temp_c:.0f}C_cycle{cycle_num+1}_{test_phase}.csv"
    target_path = target_dir / target_filename

    try:
        log_file.rename(target_path)
        logging.info(f"Stored log file: {target_path}")
        return target_path
    except OSError as e:
        logging.error(f"Failed to move log file from {log_file} to {target_path}: {e}")
        return log_file if log_file.exists() else None
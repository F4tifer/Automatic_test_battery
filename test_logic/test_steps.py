import time
import logging
from pathlib import Path
from typing import TYPE_CHECKING

# Podmíněný import pro type hinting
if TYPE_CHECKING:
    from hardware_ctl.relay_controller import RelayController
    from hardware_ctl.temp_controller import TempController
    from hardware_ctl.dut_controller import DutController
    from simulation.dummy_dut_controller import DummyDutController
    DutControllerTypes = DutController | DummyDutController
    from test_logic.data_logger import DataLogger

# Helper funkce pro notifikaci Dummy DUT
def _notify_dut_relay_state(dut: 'DutControllerTypes', relay_state: dict):
    """Informuje Dummy DUT controller o změně stavu relé."""
    if hasattr(dut, 'notify_usb_connected'):
        try:
            dut.notify_usb_connected(relay_state.get('usb_connected', False)) # type: ignore
        except Exception as e:
             logging.error(f"Error notifying dummy DUT about USB state: {e}")
    if hasattr(dut, 'notify_charger_hw_enabled'):
        try:
             dut.notify_charger_hw_enabled(relay_state.get('charger_hw_enabled', False)) # type: ignore
        except Exception as e:
             logging.error(f"Error notifying dummy DUT about HW Charger state: {e}")


# --- Funkce pro jednotlivé kroky ---

def step_set_temp(temp_ctl: 'TempController', temp_c: float) -> bool:
    """Krok 1: Nastaví cílovou teplotu."""
    logging.info(f"--- STEP 1: Setting Target Temperature to {temp_c}°C ---")
    if not temp_ctl.set_temperature(temp_c):
        logging.error("Failed to send set temperature command (or log in manual mode).")
        return False
    logging.info("Target temperature set instruction sent/logged.")
    # Samotné čekání na stabilizaci se děje ve wait_for_stabilization volaném z main
    return True

def step_relax(duration_s: int, step_name: str):
    """Krok 2, 5, 8: Relaxace po definovanou dobu."""
    logging.info(f"--- STEP {step_name}: Relaxing for {duration_s / 3600:.1f} hour(s) ({duration_s} seconds) ---")
    if duration_s <= 0:
        logging.info("Relaxation duration is zero or negative, skipping.")
        return

    end_time = time.monotonic() + duration_s
    log_interval = 60 # Logovat zbývající čas každou minutu
    next_log_time = time.monotonic() + log_interval

    logging.info(f"Relaxation started. Ends at {time.strftime('%H:%M:%S', time.localtime(time.time() + duration_s))}")
    while time.monotonic() < end_time:
        current_time = time.monotonic()
        remaining_time = end_time - current_time
        if current_time >= next_log_time:
             remaining_min = remaining_time / 60
             logging.info(f"  Relaxing... {remaining_min:.1f} minute(s) remaining.")
             next_log_time += log_interval

        # Spánek s přerušením
        sleep_duration = min(1.0, remaining_time, next_log_time - current_time)
        if sleep_duration > 0:
             time.sleep(sleep_duration)

    logging.info("Relaxation complete.")


def step_discharge(dut: 'DutControllerTypes', relay: 'RelayController', logger: 'DataLogger', config: dict) -> bool:
    """Krok 3: Vybíjení na cílové napětí (Logger už běží)."""
    discharge_limit_v = config['discharge_voltage_limit']
    logging.info(f"--- STEP 3: Discharging to {discharge_limit_v:.2f} V ---")

    logging.info("Configuring hardware for discharge...")
    relay.disconnect_usb()
    dut.disable_charging_sw()
    relay.disable_charger_hw()
    _notify_dut_relay_state(dut, {'usb_connected': False, 'charger_hw_enabled': False})
    logging.info("Hardware configured.")

    discharge_started = False
    if hasattr(dut, 'force_discharge_mode'):
        logging.info("Telling Dummy DUT to start discharging...")
        dut.force_discharge_mode(True) # type: ignore
        discharge_started = True
    else:
        # Zde by byla logika pro reálné DUT
        logging.info("Assuming real DUT/external load handles discharging initiation.")
        # Pokud by reálné DUT potřebovalo explicitní příkaz pro start vybíjení:
        # if 'set_discharge_current' in dut.cmds: # Nebo jiný příkaz?
        #      if dut.set_discharge_current(config.get('discharge_current_ma', 300)): # Potřebujeme proud v configu?
        #          discharge_started = True
        #      else:
        #          logging.error("Failed to send discharge command to DUT.")
        # else:
        #      logging.warning("No discharge command configured for real DUT.")
        discharge_started = True # Prozatím předpokládáme, že vybíjení začne samo

    if not discharge_started:
        logging.error("Could not initiate discharge process.")
        return False

    time.sleep(2) # Pauza pro stabilizaci

    logging.info("Discharging...")
    last_voltage_print_time = 0
    monitoring_interval = 1 # s

    try:
        while True:
            voltage = dut.get_battery_voltage()
            if voltage is None:
                logging.warning("Failed to read voltage during discharge. Retrying in 5s...")
                time.sleep(5)
                continue

            current_time = time.monotonic()
            if current_time - last_voltage_print_time > 15:
                 logging.info(f"  Discharging... Current voltage: {voltage:.3f} V (Target: {discharge_limit_v:.2f} V)")
                 last_voltage_print_time = current_time

            if voltage <= discharge_limit_v:
                logging.info(f"Discharge limit ({discharge_limit_v:.2f} V) reached at {voltage:.3f} V.")
                break

            # Čekání s ohledem na logovací interval, aby se nezahltilo čtení
            sleep_s = max(monitoring_interval, logger.log_interval / 2)
            time.sleep(sleep_s)

    except KeyboardInterrupt:
         logging.warning("\nDischarge interrupted by user.")
         if hasattr(dut, 'force_discharge_mode'):
             dut.force_discharge_mode(False) # type: ignore
         # Zde stop pro reálné DUT
         return False
    finally:
        logging.info("Stopping discharge process (hardware/simulation)...")
        if hasattr(dut, 'force_discharge_mode'):
            dut.force_discharge_mode(False) # type: ignore
        # Zde stop pro reálné DUT
        # např. dut.set_discharge_current(0)

    logging.info("Discharge step complete.")
    return True

def step_connect_usb_disable_charge(relay: 'RelayController', dut: 'DutControllerTypes') -> bool:
    """Krok 4: Připojí USB, ale nechá nabíjení zakázané."""
    logging.info("--- STEP 4: Connecting USB, Charging Disabled ---")
    logging.info("Sending SW disable charging command...")
    if not dut.disable_charging_sw():
         logging.warning("Failed to send SW disable charging command (or command failed). Continuing...")
    logging.info("Disabling charger HW via relay...")
    relay.disable_charger_hw()
    logging.info("Connecting USB via relay...")
    relay.connect_usb()
    _notify_dut_relay_state(dut, {'usb_connected': True, 'charger_hw_enabled': False})
    logging.info("USB connected, charging should be disabled.")
    return True

def step_enable_charging(relay: 'RelayController', dut: 'DutControllerTypes') -> bool:
    """Krok 6: Povolí nabíjení."""
    logging.info("--- STEP 6: Enabling Charging ---")
    logging.info("Enabling charger HW via relay...")
    relay.enable_charger_hw()
    logging.info("Sending SW enable charging command...")
    sw_success = dut.enable_charging_sw()
    _notify_dut_relay_state(dut, {'usb_connected': True, 'charger_hw_enabled': True}) # Notifikace i při selhání SW

    if not sw_success:
        logging.error("Failed to send SW enable charging command (or command failed).")
        # return False # Možná není kritické?
        logging.warning("Continuing despite failed SW enable command.")

    logging.info("Charging enabled (HW relay ON, SW command sent).")
    return True

def step_charge(dut: 'DutControllerTypes', logger: 'DataLogger', config: dict) -> bool:
    """Krok 7: Nabíjení do stavu IDLE."""
    idle_current_threshold = config['charge_idle_current_threshold_ma']
    logging.info(f"--- STEP 7: Charging until IDLE (Current < {idle_current_threshold} mA) ---")

    start_time = time.monotonic()
    # Zkrácený timeout pro testování, v reálu by měl být delší
    max_charge_time_s = config.get('test_plan', {}).get('max_charge_time_hours', 10) * 3600
    logging.info(f"Max charge time set to {max_charge_time_s / 3600:.1f} hours.")

    last_status_print_time = 0
    verification_period_s = 30 # Jak dlouho musí být podmínka splněna
    stable_end_detected = False
    verification_start_time = 0
    monitoring_interval = 5 # s

    try:
        while time.monotonic() - start_time < max_charge_time_s:
            current_monotonic_time = time.monotonic()
            # Získání dat
            mode = dut.get_operation_mode()
            current = dut.get_battery_current()
            voltage = dut.get_battery_voltage()

            if mode is None and current is None:
                 logging.warning("Failed to read mode and current during charge. Retrying...")
                 time.sleep(monitoring_interval)
                 continue

            # Logování stavu
            if current_monotonic_time - last_status_print_time > 30:
                mode_str = f"Mode={mode}" if mode is not None else "Mode=N/A"
                curr_str = f"I={current:.1f}mA" if current is not None else "I=N/A"
                volt_str = f"V={voltage:.3f}V" if voltage is not None else "V=N/A"
                elapsed_m = (current_monotonic_time - start_time) / 60
                logging.info(f"  Charging status ({elapsed_m:.1f} min): {mode_str}, {curr_str}, {volt_str}")
                last_status_print_time = current_monotonic_time

            # Kontrola ukončení
            charge_ended_condition = False
            if mode == "IDLE":
                charge_ended_condition = True
            elif current is not None and abs(current) < idle_current_threshold:
                 # I pokud mode není IDLE, ale proud klesl
                charge_ended_condition = True

            if charge_ended_condition:
                if not stable_end_detected:
                     logging.info("Charge end condition detected. Verifying stability...")
                     stable_end_detected = True
                     verification_start_time = current_monotonic_time
                elif current_monotonic_time - verification_start_time >= verification_period_s:
                    logging.info("Charge termination condition stable. Charge complete.")
                    break # Úspěšné ukončení
                else:
                     logging.debug(f"  Verifying stability... {current_monotonic_time - verification_start_time:.0f}/{verification_period_s:.0f}s")
            else:
                if stable_end_detected:
                    logging.info("Charge termination condition became unstable. Resetting verification.")
                stable_end_detected = False

            time.sleep(monitoring_interval)
        else:
             logging.error(f"Charging did not complete within the timeout period ({max_charge_time_s / 3600:.1f} hours).")
             return False

    except KeyboardInterrupt:
         logging.warning("\nCharging interrupted by user.")
         return False
    finally:
        # Logger se stopne v main_tester
        pass

    logging.info("Charging step complete.")
    return True


def step_store_files(log_file: Path | None, output_dir: Path, temp_c: float, cycle_num: int, test_phase: str) -> Path | None:
    """Krok 9: Přejmenuje a uloží log soubor pro celý cyklus."""
    logging.info(f"--- STEP 9: Storing Log File ---")
    if log_file is None or not log_file.exists():
        logging.warning(f"Temporary log file {log_file} not found or is None. Skipping storage.")
        return None

    # Cílový adresář pro teplotu
    target_dir = output_dir / f"temp_{temp_c:.0f}C"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logging.error(f"Failed to create target directory {target_dir}: {e}")
        return log_file # Vrátí původní cestu

    # Finální název souboru
    target_filename = f"{temp_c:.0f}C_cycle{cycle_num+1}.csv"
    target_path = target_dir / target_filename

    # Přesunout (přejmenovat)
    try:
        log_file.rename(target_path)
        logging.info(f"Stored log file: {target_path}")
        return target_path
    except OSError as e:
        logging.error(f"Failed to move log file from {log_file} to {target_path}: {e}")
        return log_file if log_file.exists() else None

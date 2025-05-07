import time
import toml
import sys
import logging
from pathlib import Path
import subprocess
import platform
import socket

# --- Přidání cest k modulům ---
# Předpokládá spuštění z kořenového adresáře projektu
project_root = Path(__file__).parent
sys.path.append(str(project_root)) # Přidá kořenový adresář
libs_path = project_root / "libs"
if str(libs_path) not in sys.path:
    sys.path.insert(0, str(libs_path))
backend_path = libs_path / "backend" # Potřeba pro import Deditec
if str(backend_path) not in sys.path:
     sys.path.insert(0, str(backend_path))
# -----------------------------

# --- Importy ovladačů a logiky ---
try:
    from hardware_ctl.relay_controller import RelayController
    from hardware_ctl.temp_controller import TempController
    from test_logic.data_logger import DataLogger
    from test_logic import test_steps
    # Import Deditec třídy pro přímý test spojení
    from backend.deditec_driver.deditec_1_16_on import Deditec_1_16_on
    deditec_import_ok = True
except ImportError as e:
    print(f"FATAL ERROR: Failed to import core modules: {e}")
    print("Please check project structure, __init__.py files, and sys.path.")
    sys.exit(1)
# ---------------------------------

# --- Nastavení logování ---
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_file = project_root / "test_run.log"

# File handler
file_handler = logging.FileHandler(log_file, mode='w')
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

# Logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
if logger.hasHandlers():
    logger.handlers.clear()
logger.addHandler(file_handler)
logger.addHandler(console_handler)
# -----------------------------

def load_config(config_path="test_config.toml") -> dict | None:
    """Načte konfiguraci z TOML souboru."""
    config_file = project_root / config_path
    logging.info(f"Loading configuration from: {config_file}")
    try:
        config = toml.load(config_file)
        # Základní validace
        required_sections = ["general", "relay", "temperature_chamber", "test_plan", "dut_commands"]
        for section in required_sections:
            if section not in config:
                raise ValueError(f"Missing required section '{section}' in config file.")
        if 'simulate_dut' not in config['general']:
            logging.warning("Config key 'simulate_dut' not found in [general]. Assuming 'false' (real DUT).")
            config['general']['simulate_dut'] = False
        logging.info("Configuration loaded successfully.")
        return config
    except FileNotFoundError:
        logging.error(f"ERROR: Configuration file not found at {config_file}")
        return None
    except Exception as e:
        logging.error(f"ERROR: Failed to load or parse configuration file: {e}")
        return None

def _check_deditec_connection(ip: str, port: int, timeout: int = 2) -> bool:
    """Pokusí se navázat TCP spojení s Deditec deskou."""
    if not deditec_import_ok:
        logging.warning("Deditec driver not imported, cannot perform connection check.")
        return True

    logging.info(f"Checking Deditec connection to {ip}:{port} (timeout={timeout}s)...")
    try:
        with Deditec_1_16_on(ip=ip, port=port, timeout_seconds=timeout) as tester:
            logging.info("Deditec connection successful.")
            return True
    except ConnectionError as e:
        logging.error(f"Deditec connection failed: {e}")
        return False
    except TimeoutError:
        logging.error(f"Deditec connection timed out.")
        return False
    except Exception as e:
        logging.error(f"Unexpected error during Deditec connection check: {e}")
        return False

def _check_ping(ip: str) -> bool:
    """Odešle jeden ping na danou IP adresu."""
    logging.info(f"Pinging {ip}...")
    param = "-n" if platform.system().lower() == "windows" else "-c"
    command = ["ping", param, "1", "-W", "1", ip] # -W 1 pro 1s timeout (macOS/Linux)
    # Pro Windows timeout je -w 1000 (v ms)
    if platform.system().lower() == "windows":
        command = ["ping", param, "1", "-w", "1000", ip]

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3)
        logging.debug(f"Ping stdout: {result.stdout}")
        logging.debug(f"Ping stderr: {result.stderr}")
        if result.returncode == 0:
            # Doplňková kontrola výstupu pro některé případy (např. síť nedostupná)
            if "unreachable" in result.stdout.lower() or "timed out" in result.stdout.lower():
                 logging.error(f"Ping to {ip} reported success but output indicates failure.")
                 return False
            logging.info(f"Ping to {ip} successful.")
            return True
        else:
            logging.error(f"Ping to {ip} failed (return code: {result.returncode}).")
            return False
    except FileNotFoundError:
        logging.error("Ping command not found. Cannot perform ping check.")
        return True # Nemůžeme ověřit, pokračujeme
    except subprocess.TimeoutExpired:
        logging.error(f"Ping to {ip} timed out.")
        return False
    except Exception as e:
        logging.error(f"Error during ping check: {e}")
        return True # Neznámá chyba, pokračujeme

def check_peripherals(config: dict, relay_ctl, dut_ctl, temp_ctl) -> bool:
    """Zkontroluje dostupnost nakonfigurovaných periferií."""
    logging.info("--- Starting Peripheral Checks ---")
    all_ok = True
    is_simulation = config['general'].get('simulate_dut', False)
    temp_enabled = config['temperature_chamber'].get('enabled', False)

    # 1. Kontrola Relé Desky
    if relay_ctl:
        relay_ip = config['relay']['ip_address']
        relay_port = relay_ctl.DEDITEC_PORT
        if not _check_ping(relay_ip):
            logging.warning("Ping to Deditec failed, network issue possible.")
        if not _check_deditec_connection(relay_ip, relay_port):
            logging.error("CRITICAL: Failed to establish TCP connection with Deditec relay board.")
            all_ok = False
    else:
        logging.error("CRITICAL: Relay Controller is not initialized.")
        all_ok = False

    # 2. Kontrola DUT (pokud není simulace)
    if not is_simulation:
        if dut_ctl is None:
            logging.error("CRITICAL: DUT Controller initialization failed (check serial port and connection).")
            all_ok = False
        else:
            logging.info("DUT Controller initialized. Attempting test communication...")
            # Zkusíme základní příkaz, např. get_status
            try:
                status = dut_ctl.get_operation_mode()
                if status is None:
                    logging.warning("Test communication with DUT failed or returned no data. Check DUT readiness and commands.")
                    # Může být OK, pokud DUT neodpovídá hned po startu
                    # all_ok = False # Pokud je komunikace ihned nutná
                else:
                    logging.info(f"Test communication with DUT successful (reported status: {status}).")
            except Exception as e:
                logging.error(f"Error during test communication with DUT: {e}")
                all_ok = False
    else:
        if dut_ctl is None:
             logging.error("CRITICAL: Dummy DUT Controller failed to initialize.")
             all_ok = False
        else:
             logging.info("DUT is in simulation mode.")

    # 3. Kontrola Teplotní Komory
    if temp_ctl is None:
         logging.error("CRITICAL: Temperature Controller is not initialized.")
         all_ok = False
    elif temp_enabled:
        logging.info("Temperature Chamber control is enabled (connection status depends on implementation).")
        # Zde by byla kontrola reálné komory, pokud by byla implementována
    else:
        logging.info("Temperature Chamber control is disabled or in manual mode.")

    if all_ok:
        logging.info("--- Peripheral Checks Passed ---")
    else:
        logging.error("--- PERIPHERAL CHECKS FAILED. Please check connections and configuration. ---")

    return all_ok

def run_test_cycle(config: dict, temp_c: float, cycle_num: int, temp_ctl: TempController, relay_ctl: RelayController, dut_ctl) -> bool:
    """Provede jeden kompletní testovací cyklus pro danou teplotu s JEDNÍM log souborem."""
    # Argument dut_ctl nyní nemá pevný typ
    logging.info(f"--- Starting Test Cycle {cycle_num + 1} at {temp_c}°C ---")
    base_output_dir = Path(config['general']['output_directory'])
    temp_cycle_log_path = base_output_dir / f"_temp_{temp_c:.0f}C_cycle{cycle_num+1}_full.csv"

    cycle_logger = DataLogger(dut_ctl, config['general']['log_interval_seconds'], temp_cycle_log_path)
    final_log_file = None
    cycle_successful = False
    log_started = False

    try:
        logging.info("Starting data logger for the cycle...")
        if not cycle_logger.start_logging():
             logging.error("Failed to start data logger for the cycle. Aborting cycle.")
             return False
        log_started = True
        final_log_file = cycle_logger.logged_data_file

        logging.info("Verifying/Setting temperature...")
        if not temp_ctl.wait_for_stabilization(temp_c): # V manuálním režimu čeká na Enter
             logging.error("Temperature check/stabilization failed. Aborting cycle.")
             return False

        test_steps.step_relax(config['test_plan']['relaxation_time_seconds'], "2 (Pre-Discharge)")

        if not test_steps.step_discharge(dut_ctl, relay_ctl, cycle_logger, config['test_plan']):
             logging.error("Discharge step failed.")
             return False

        if not test_steps.step_connect_usb_disable_charge(relay_ctl, dut_ctl):
            logging.error("Step 4 (Connect USB, Disable Charge) failed.")
            return False

        test_steps.step_relax(config['test_plan']['relaxation_time_seconds'], "5 (Pre-Charge)")

        if not test_steps.step_enable_charging(relay_ctl, dut_ctl):
            logging.error("Step 6 (Enable Charging) failed.")
            return False

        if not test_steps.step_charge(dut_ctl, cycle_logger, config['test_plan']):
            logging.error("Charge step failed.")
            return False

        test_steps.step_relax(config['test_plan']['relaxation_time_seconds'], "8 (Post-Charge)")

        logging.info(f"--- Test Cycle {cycle_num + 1} at {temp_c}°C Completed Successfully ---")
        cycle_successful = True
        return True

    except Exception as e:
        logging.exception(f"Unexpected error during test cycle {cycle_num + 1} at {temp_c}°C: {e}")
        return False
    finally:
        if log_started:
            logging.info("Stopping data logger for the cycle...")
            cycle_logger.stop_logging()

        if final_log_file:
            output_storage_dir = Path(config['general']['output_directory'])
            stored_log = test_steps.step_store_files(final_log_file, output_storage_dir, temp_c, cycle_num, "cycle")
            if stored_log and stored_log != final_log_file:
                 logging.info(f"Cycle log stored as: {stored_log.name}")
            elif stored_log:
                 logging.warning(f"Could not rename cycle log, remains as: {final_log_file.name}")
            else:
                 logging.error(f"Failed to store or find cycle log: {final_log_file}")

def main():
    """Hlavní funkce pro spuštění testovacího scénáře."""
    config = load_config()
    if config is None:
        sys.exit(1)

    # Inicializace ovladačů HW
    logging.info("Initializing hardware controllers...")
    relay_ctl = None
    dut_ctl = None
    temp_ctl = None
    init_ok = True
    try:
        relay_ctl = RelayController(config['relay']['ip_address'],
                                    config['relay']['usb_power_relay_pin'],
                                    config['relay'].get('charger_enable_relay_pin'),
                                    config['relay'].get('beeper_pin'))
        
        notifications_config = config.get('notifications', {}) # Získáme sekci nebo prázdný dict
        temp_ctl = TempController(config['temperature_chamber'], relay_ctl, notifications_config) # <-- Přidán argument

        is_simulation = config['general'].get('simulate_dut', False)
        # ... (inicializace dut_ctl zůstává stejná) ...
        if is_simulation:
            # ... (import a init DummyDutController) ...
            from simulation.dummy_dut_controller import DummyDutController
            dut_ctl = DummyDutController(config['dut_commands'])
            logging.warning("<<<<< RUNNING IN DUT SIMULATION MODE >>>>>")
        else:
            # ... (import a init DutController) ...
            from hardware_ctl.dut_controller import DutController
            dut_ctl = DutController(config['general']['dut_serial_port'],
                                    config['dut_commands'],
                                    verbose=False)
            logging.info("--- Running with REAL DUT controller ---")

    except ImportError as e:
         logging.error(f"FATAL ERROR: Failed to import necessary controller module: {e}")
         init_ok = False
    except Exception as e:
        logging.exception(f"FATAL ERROR during controller initialization: {e}")
        init_ok = False

        temp_ctl = TempController(config['temperature_chamber'], relay_ctl)

        is_simulation = config['general'].get('simulate_dut', False)
        if is_simulation:
            # Přidání cesty k simulation, pokud není automaticky nalezena
            sim_path = project_root / "simulation"
            if str(sim_path) not in sys.path:
                 sys.path.insert(0, str(sim_path))
            from dummy_dut_controller import DummyDutController
            dut_ctl = DummyDutController(config['dut_commands'])
            logging.warning("<<<<< RUNNING IN DUT SIMULATION MODE >>>>>")
        else:
            # Přidání cesty k hardware_ctl, pokud není automaticky nalezena
            hw_path = project_root / "hardware_ctl"
            if str(hw_path) not in sys.path:
                 sys.path.insert(0, str(hw_path))
            from hardware_ctl.dut_controller import DutController
            # Přidání cesty k libs pro prodtest_cli
            libs_path_ctrl = project_root / "libs"
            if str(libs_path_ctrl) not in sys.path:
                 sys.path.insert(0, str(libs_path_ctrl))

            dut_ctl = DutController(config['general']['dut_serial_port'],
                                    config['dut_commands'],
                                    verbose=False)
            logging.info("--- Running with REAL DUT controller ---")

    except ImportError as e:
         logging.error(f"FATAL ERROR: Failed to import necessary controller module: {e}")
         init_ok = False
    except Exception as e:
        logging.exception(f"FATAL ERROR during controller initialization: {e}")
        init_ok = False

    if not init_ok:
        logging.error("Exiting due to controller initialization failure.")
        # Zkusíme zavolat close() na tom, co se mohlo inicializovat
        if relay_ctl: relay_ctl.close()
        if temp_ctl: temp_ctl.close()
        sys.exit(1)

    # Kontrola periferií
    if not check_peripherals(config, relay_ctl, dut_ctl, temp_ctl):
        logging.info("Exiting due to failed peripheral checks.")
        if relay_ctl: relay_ctl.close()
        if dut_ctl: dut_ctl.close()
        if temp_ctl: temp_ctl.close()
        sys.exit(1)

    # Vytvoření hlavní výstupní složky
    base_output_dir = Path(config['general']['output_directory'])
    base_output_dir.mkdir(parents=True, exist_ok=True)
    logging.info(f"Test results will be saved in: {base_output_dir.resolve()}")

    temperatures = config['test_plan']['temperatures_celsius']
    cycles_per_temp = config['test_plan']['cycles_per_temperature']
    total_cycles = len(temperatures) * cycles_per_temp
    completed_cycles = 0

    logging.info(f"Test plan: {len(temperatures)} temperatures, {cycles_per_temp} cycles each. Total cycles: {total_cycles}")
    logging.info(f"DUT Simulation Mode: {'ENABLED' if is_simulation else 'DISABLED'}")
    logging.info(f"Temperature Control: {'MANUAL' if not config['temperature_chamber'].get('enabled', False) else 'AUTOMATIC'}")

    start_time = time.time()
    test_aborted = False

    try:
        for temp_c in temperatures:
            logging.info(f"===== Processing Temperature: {temp_c}°C =====")

            # Nastavení teploty (jen loguje v manuálním režimu)
            if not test_steps.step_set_temp(temp_ctl, temp_c):
                 logging.error(f"Failed initial temperature set/check for {temp_c}°C. Skipping this temperature.")
                 continue

            for cycle_num in range(cycles_per_temp):
                cycle_start_time = time.time()
                logging.info(f"--- Starting Cycle {cycle_num + 1}/{cycles_per_temp} for {temp_c}°C ---")

                success = run_test_cycle(config, temp_c, cycle_num, temp_ctl, relay_ctl, dut_ctl)

                cycle_end_time = time.time()
                cycle_duration_m = (cycle_end_time - cycle_start_time) / 60

                if success:
                    completed_cycles += 1
                    logging.info(f"--- Cycle {cycle_num + 1}/{cycles_per_temp} for {temp_c}°C finished successfully in {cycle_duration_m:.1f} minutes. ---")
                else:
                    logging.error(f"--- Cycle {cycle_num + 1}/{cycles_per_temp} for {temp_c}°C failed after {cycle_duration_m:.1f} minutes. ---")
                    # Rozhodnutí, zda přerušit celý test při selhání cyklu
                    if config.get('general', {}).get('fail_fast', False): # Přidat volbu fail_fast do configu?
                         logging.warning("Fail fast enabled. Aborting test plan.")
                         test_aborted = True
                         break # Ukončí vnitřní smyčku (cykly)
                    else:
                         logging.info("Continuing with the next cycle/temperature.")

                logging.info(f"Progress: {completed_cycles}/{total_cycles} total cycles completed.")

            if test_aborted:
                break # Ukončí vnější smyčku (teploty)

            logging.info(f"===== Finished all cycles for Temperature: {temp_c}°C =====")

    except KeyboardInterrupt:
        logging.warning("<<<<< Test execution interrupted by user (Ctrl+C) >>>>>")
        test_aborted = True
    except Exception as e:
        logging.exception(f"FATAL ERROR during test execution: {e}")
        test_aborted = True
    finally:
        logging.info("Performing final cleanup...")
        if relay_ctl:
            try:
                logging.info("Ensuring all controlled relays are OFF...")
                off_pins = [relay_ctl.usb_relay_pin,
                            relay_ctl.charger_enable_relay_pin,
                            relay_ctl.beeper_pin]
                relay_ctl._set_relays_off(off_pins)
                relay_ctl.close()
            except Exception as e_relay:
                logging.error(f"Error during relay cleanup: {e_relay}")
        if dut_ctl:
            try:
                dut_ctl.close()
            except Exception as e_dut:
                 logging.error(f"Error during DUT controller cleanup: {e_dut}")
        if temp_ctl:
            try:
                temp_ctl.close()
            except Exception as e_temp:
                 logging.error(f"Error during Temperature controller cleanup: {e_temp}")

        end_time = time.time()
        total_duration_h = (end_time - start_time) / 3600
        status = "ABORTED" if test_aborted else "FINISHED"
        logging.info(f"Test execution {status}. Total duration: {total_duration_h:.2f} hours.")


if __name__ == "__main__":
    main()
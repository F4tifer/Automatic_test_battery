# main_tester.py

import time
import toml
import sys
import logging
from pathlib import Path
import subprocess
import platform
import socket
from typing import Optional, Dict, Any # Přidáno Optional, Dict, Any

# --- Přidání cest k modulům ---
project_root = Path(__file__).parent
sys.path.append(str(project_root))
libs_path = project_root / "libs"
if str(libs_path) not in sys.path:
    sys.path.insert(0, str(libs_path))
backend_path = libs_path / "backend"
if str(backend_path) not in sys.path:
     sys.path.insert(0, str(backend_path))
# Cesty pro hardware_ctl, simulation, test_logic, analysis (pokud jsou potřeba přímo zde)
hw_ctl_path = project_root / "hardware_ctl"
if str(hw_ctl_path) not in sys.path: sys.path.insert(0, str(hw_ctl_path))
sim_path = project_root / "simulation"
if str(sim_path) not in sys.path: sys.path.insert(0, str(sim_path))
logic_path = project_root / "test_logic"
if str(logic_path) not in sys.path: sys.path.insert(0, str(logic_path))
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
    # Importujeme typy pro type hinting kontrolerů
    from hardware_ctl.dut_controller import DutController
    from simulation.dummy_dut_controller import DummyDutController
    DutControllerTypes = DutController | DummyDutController
except ImportError as e:
    print(f"FATAL ERROR: Failed to import core modules: {e}")
    print("Please check project structure, __init__.py files, and sys.path.")
    # Ukončení zde nemá smysl, protože logger ještě není nastaven
    deditec_import_ok = False # Nastavíme flag pro check_peripherals
    # Můžeme definovat dummy třídy zde, aby zbytek mohl běžet až k logování chyby
    class RelayController: pass
    class TempController: pass
    class DataLogger: pass
    class test_steps: pass
    class DutController: pass
    class DummyDutController: pass
    DutControllerTypes = Any # Fallback type
# ---------------------------------

# --- Nastavení logování ---
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
log_file = project_root / "test_run.log"
logger = logging.getLogger() # Root logger
logger.setLevel(logging.INFO) # Nastavení úrovně root loggeru
# Odstranění předchozích handlerů, pokud existují
if logger.hasHandlers(): logger.handlers.clear()
# File handler
try:
    file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.INFO) # Logovat INFO a vyšší do souboru
    logger.addHandler(file_handler)
except Exception as log_e:
     print(f"WARNING: Failed to create file log handler for {log_file}: {log_e}")
# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO) # Zobrazit INFO a vyšší na konzoli
logger.addHandler(console_handler)
# -----------------------------

def load_config(config_path="test_config.toml") -> Optional[Dict[str, Any]]:
    """Načte konfiguraci z TOML souboru."""
    config_file = project_root / config_path
    logging.info(f"Loading configuration from: {config_file}")
    try:
        config = toml.load(config_file)
        # Validace základních sekcí
        required_sections = ["general", "relay", "temperature_chamber", "test_plan", "dut_commands", "notifications"]
        for section in required_sections:
            if section not in config:
                raise ValueError(f"Missing required section '{section}' in config file.")
        # Doplnění defaultních hodnot, pokud chybí
        if 'simulate_dut' not in config['general']:
            logging.warning("Config key 'simulate_dut' not found in [general]. Assuming 'false'.")
            config['general']['simulate_dut'] = False
        if 'test_modes' not in config['test_plan']:
            logging.warning("Config key 'test_modes' not found in [test_plan]. Assuming '[\"linear\"]'.")
            config['test_plan']['test_modes'] = ['linear']
        if 'manual_temp_mode' not in config['notifications']:
             config['notifications']['manual_temp_mode'] = 'beeper' # Default

        logging.info("Configuration loaded and validated successfully.")
        return config
    except FileNotFoundError:
        logging.error(f"ERROR: Configuration file not found at {config_file}")
        return None
    except Exception as e:
        logging.error(f"ERROR: Failed to load or parse configuration file '{config_file}': {e}")
        return None

def _check_deditec_connection(ip: str, port: int, timeout: int = 2) -> bool:
    """Pokusí se navázat TCP spojení s Deditec deskou."""
    if not deditec_import_ok:
        logging.warning("Deditec driver not imported, cannot perform connection check.")
        return True # Nepovažujeme za kritickou chybu, pokud driver chybí

    logging.info(f"Checking Deditec connection to {ip}:{port} (timeout={timeout}s)...")
    try:
        with Deditec_1_16_on(ip=ip, port=port, timeout_seconds=timeout) as tester:
            logging.info("Deditec connection successful.")
            return True
    except ConnectionError as e: logging.error(f"Deditec connection failed: {e}"); return False
    except TimeoutError: logging.error(f"Deditec connection timed out."); return False
    except Exception as e: logging.error(f"Unexpected error during Deditec connection check: {e}"); return False

def _check_ping(ip: str) -> bool:
    """Odešle jeden ping na danou IP adresu."""
    logging.info(f"Pinging {ip}...")
    system = platform.system().lower()
    if system == "windows":
        command = ["ping", "-n", "1", "-w", "1000", ip] # Timeout 1000ms
    else: # Linux, macOS
        command = ["ping", "-c", "1", "-W", "1", ip] # Timeout 1s

    try:
        # Použijeme Popen pro lepší kontrolu a nezávislost na shellu
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(timeout=3) # Celkový timeout procesu
        return_code = process.returncode
        logging.debug(f"Ping stdout:\n{stdout}")
        if stderr: logging.debug(f"Ping stderr:\n{stderr}")

        if return_code == 0:
             # Doplňková kontrola (může být závislá na jazyku systému)
            if "unreachable" in stdout.lower() or "timed out" in stdout.lower() or "ttl expired" in stdout.lower():
                 logging.error(f"Ping to {ip} technically succeeded (code 0) but output indicates failure.")
                 return False
            logging.info(f"Ping to {ip} successful.")
            return True
        else:
            logging.error(f"Ping to {ip} failed (return code: {return_code}).")
            return False
    except FileNotFoundError:
        logging.error("Ping command not found. Install ping or check PATH. Skipping ping check.")
        return True # Pokračujeme, nemůžeme ověřit
    except subprocess.TimeoutExpired:
        logging.error(f"Ping process to {ip} timed out.")
        return False
    except Exception as e:
        logging.error(f"Error during ping check: {e}")
        return True # Neznámá chyba, zkusíme pokračovat

def check_peripherals(config: dict, relay_ctl, dut_ctl, temp_ctl) -> bool:
    """Zkontroluje dostupnost nakonfigurovaných periferií."""
    logging.info("--- Starting Peripheral Checks ---")
    all_ok = True
    is_simulation = config['general'].get('simulate_dut', False)
    temp_enabled = config['temperature_chamber'].get('enabled', False)

    # 1. Kontrola Relé Desky
    if relay_ctl and hasattr(relay_ctl, 'ip_address'): # Ověření, zda je relay_ctl platný
        relay_ip = config['relay']['ip_address']
        relay_port = relay_ctl.DEDITEC_PORT
        if not _check_ping(relay_ip):
            logging.warning("Ping to Deditec relay board failed. Network issue possible, but attempting TCP check.")
        if not _check_deditec_connection(relay_ip, relay_port):
            logging.error("CRITICAL: Failed to establish TCP connection with Deditec relay board.")
            all_ok = False
    else:
        logging.error("CRITICAL: Relay Controller is not initialized or invalid.")
        all_ok = False

    # 2. Kontrola DUT
    if not is_simulation:
        if dut_ctl is None or not hasattr(dut_ctl, 'cli'): # Zkontrolujeme i vnitřní 'cli'
            logging.error("CRITICAL: Real DUT Controller initialization failed (check serial port, connection, and prodtest_cli).")
            all_ok = False
        else:
            logging.info("Real DUT Controller initialized. Attempting test communication...")
            try:
                # Zkusíme získat status - může trvat déle
                status = dut_ctl.get_operation_mode()
                if status is None:
                    logging.warning("Test communication with DUT failed or returned no data. DUT might not be ready or commands invalid.")
                    # Nepovažujeme za kritickou chybu zde, test může běžet dál
                else:
                    logging.info(f"Test communication with DUT successful (reported status: {status}).")
            except Exception as e:
                logging.error(f"Error during test communication with DUT: {e}")
                # Toto může být kritické
                all_ok = False
    else: # Simulace
        if dut_ctl is None or not hasattr(dut_ctl, '_simulate_battery'): # Ověříme dummy
            logging.error("CRITICAL: Dummy DUT Controller failed to initialize.")
            all_ok = False
        else:
             logging.info("DUT is in simulation mode.")

    # 3. Kontrola Teplotní Komory
    if temp_ctl is None:
         logging.error("CRITICAL: Temperature Controller is not initialized.")
         all_ok = False
    elif temp_enabled:
        logging.info("Temperature Chamber control is enabled.")
        # Zde by byla kontrola reálné komory, pokud by byla implementována
        # např. if not temp_ctl.check_connection(): all_ok = False
    else:
        logging.info("Temperature Chamber control is disabled or in manual mode.")

    if all_ok:
        logging.info("--- Peripheral Checks Passed ---")
    else:
        logging.error("--- PERIPHERAL CHECKS FAILED. Please resolve issues before running tests. ---")

    return all_ok

def run_test_cycle(config: dict, temp_c: float, cycle_num: int, test_mode: str,
                   temp_ctl: TempController, relay_ctl: RelayController, dut_ctl: DutControllerTypes) -> bool:
    """
    Provede jeden testovací "sub-cyklus" pro daný mód, teplotu a číslo cyklu.
    Loguje do samostatných souborů pro fáze daného módu.
    """
    logging.info(f"--- Starting Test: Mode='{test_mode}', Cycle={cycle_num + 1}, Temp={temp_c}°C ---")
    base_output_dir = Path(config['general']['output_directory'])
    log_interval = config['general']['log_interval_seconds']

    # Připravíme si cesty k logům, ale loggery vytvoříme až při potřebě
    temp_discharge_log_path = base_output_dir / f"_temp_{temp_c:.0f}C_cycle{cycle_num+1}_{test_mode}_discharge.csv"
    temp_charge_log_path = base_output_dir / f"_temp_{temp_c:.0f}C_cycle{cycle_num+1}_{test_mode}_charge.csv"
    temp_specific_log_path = base_output_dir / f"_temp_{temp_c:.0f}C_cycle{cycle_num+1}_{test_mode}_main.csv"

    discharge_logger: Optional[DataLogger] = None
    charge_logger: Optional[DataLogger] = None
    specific_logger: Optional[DataLogger] = None

    final_log_paths: Dict[str, Optional[Path]] = { # Pro sledování vytvořených logů
        "discharge": None, "charge": None, "specific": None
    }
    cycle_successful = False

    try:
        # Kroky společné pro všechny módy (mohou běžet před specifickou logikou)
        logging.info("Verifying/Setting temperature...")
        if not temp_ctl.wait_for_stabilization(temp_c):
             logging.error("Temperature check/stabilization failed. Aborting test mode.")
             return False

        # Relaxace před aktivitou specifickou pro mód
        test_steps.step_relax(config['test_plan']['relaxation_time_seconds'], f"Pre-{test_mode.capitalize()}")

        # --- Logika specifická pro mód ---
        if test_mode == "linear":
            logging.info("Executing Linear Test Steps...")
            discharge_logger = DataLogger(dut_ctl, log_interval, temp_discharge_log_path)
            charge_logger = DataLogger(dut_ctl, log_interval, temp_charge_log_path)
            final_log_paths["discharge"] = temp_discharge_log_path
            final_log_paths["charge"] = temp_charge_log_path

            if not discharge_logger.start_logging(): return False
            if not test_steps.step_discharge(dut_ctl, relay_ctl, discharge_logger, config['test_plan']):
                 discharge_logger.stop_logging(); return False
            discharge_logger.stop_logging()

            if not test_steps.step_connect_usb_disable_charge(relay_ctl, dut_ctl): return False
            test_steps.step_relax(config['test_plan']['relaxation_time_seconds'], "Linear Pre-Charge")

            if not charge_logger.start_logging(): return False
            if not test_steps.step_enable_charging(relay_ctl, dut_ctl):
                 charge_logger.stop_logging(); return False
            if not test_steps.step_charge(dut_ctl, charge_logger, config['test_plan']):
                 charge_logger.stop_logging(); return False
            charge_logger.stop_logging()

        elif test_mode == "switching":
            logging.info("Executing Switching Test Steps...")
            specific_logger = DataLogger(dut_ctl, log_interval, temp_specific_log_path)
            final_log_paths["specific"] = temp_specific_log_path
            if not specific_logger.start_logging(): return False
            if not test_steps.step_switching_phase(dut_ctl, relay_ctl, specific_logger, config['test_plan']):
                 specific_logger.stop_logging(); return False
            specific_logger.stop_logging()

        elif test_mode == "random":
            logging.info("Executing Random Wonder Test Steps...")
            specific_logger = DataLogger(dut_ctl, log_interval, temp_specific_log_path)
            final_log_paths["specific"] = temp_specific_log_path
            if not specific_logger.start_logging(): return False
            if not test_steps.step_random_wonder(dut_ctl, relay_ctl, specific_logger, config['test_plan']):
                 specific_logger.stop_logging(); return False
            specific_logger.stop_logging()

        else:
            logging.error(f"Unknown test mode: '{test_mode}'. Skipping.")
            return False

        # Relaxace po aktivitě specifické pro mód
        test_steps.step_relax(config['test_plan']['relaxation_time_seconds'], f"Post-{test_mode.capitalize()}")

        logging.info(f"--- Test Mode '{test_mode}' Completed Successfully (Cycle {cycle_num + 1}, Temp {temp_c}°C) ---")
        cycle_successful = True
        return True

    except Exception as e:
        logging.exception(f"Unexpected error during test mode '{test_mode}' (Cycle {cycle_num + 1}, Temp {temp_c}°C): {e}")
        return False # Cyklus selhal
    finally:
        # Ukončení loggerů, pokud ještě běží (např. po výjimce)
        if discharge_logger and discharge_logger.is_logging: discharge_logger.stop_logging()
        if charge_logger and charge_logger.is_logging: charge_logger.stop_logging()
        if specific_logger and specific_logger.is_logging: specific_logger.stop_logging()

        # Uložení/Přejmenování souborů
        output_storage_dir = Path(config['general']['output_directory'])
        if final_log_paths["discharge"]:
            stored = test_steps.step_store_files(final_log_paths["discharge"], output_storage_dir, temp_c, cycle_num, f"{test_mode}_discharge")
            if stored and stored != final_log_paths["discharge"]: logging.info(f"Discharge log stored as: {stored.name}")
        if final_log_paths["charge"]:
             stored = test_steps.step_store_files(final_log_paths["charge"], output_storage_dir, temp_c, cycle_num, f"{test_mode}_charge")
             if stored and stored != final_log_paths["charge"]: logging.info(f"Charge log stored as: {stored.name}")
        if final_log_paths["specific"]:
             stored = test_steps.step_store_files(final_log_paths["specific"], output_storage_dir, temp_c, cycle_num, f"{test_mode}_main")
             if stored and stored != final_log_paths["specific"]: logging.info(f"Specific log for '{test_mode}' stored as: {stored.name}")

def main():
    """Hlavní funkce pro spuštění testovacího scénáře."""
    logging.info("==============================================")
    logging.info("   Starting Automated Battery Cycle Tester    ")
    logging.info("==============================================")

    config = load_config()
    if config is None:
        logging.critical("Failed to load configuration. Exiting.")
        sys.exit(1)

    # Inicializace ovladačů HW
    logging.info("Initializing hardware controllers...")
    relay_ctl = None
    dut_ctl = None
    temp_ctl = None
    init_ok = True
    try:
        relay_ctl = RelayController(
            ip_address=config['relay']['ip_address'],
            usb_relay_pins=config['relay'].get('usb_power_relay_pins', []), # Čteme seznam
            charger_relay_pins=config['relay'].get('charger_enable_relay_pins'), # Nepovinný seznam
            beeper_pins=config['relay'].get('beeper_pins') # Nepovinný seznam
        )
        # -------------------------------------------------------------

        notifications_config = config.get('notifications', {})
        temp_ctl = TempController(config['temperature_chamber'], relay_ctl, notifications_config)

        # ... (inicializace dut_ctl - stejná) ...
        is_simulation = config['general'].get('simulate_dut', False)
        if is_simulation:
            from simulation.dummy_dut_controller import DummyDutController
            dut_ctl = DummyDutController(config['dut_commands'])
            logging.warning("<<<<< RUNNING IN DUT SIMULATION MODE >>>>>")
        else:
            from hardware_ctl.dut_controller import DutController
            dut_ctl = DutController(config['general']['dut_serial_port'],
                                    config['dut_commands'],
                                    verbose=False)
            logging.info("--- Running with REAL DUT controller ---")

    except ImportError as e:
         logging.critical(f"FATAL ERROR: Failed to import necessary controller module: {e}")
         init_ok = False
    except Exception as e:
        logging.exception(f"FATAL ERROR during controller initialization: {e}")
        init_ok = False

    if not init_ok:
        logging.critical("Exiting due to controller initialization failure.")
        if relay_ctl: relay_ctl.close()
        if temp_ctl: temp_ctl.close()
        sys.exit(1)

    # Kontrola periferií
    if not check_peripherals(config, relay_ctl, dut_ctl, temp_ctl):
        logging.critical("Exiting due to failed peripheral checks.")
        if relay_ctl: relay_ctl.close()
        if dut_ctl: dut_ctl.close()
        if temp_ctl: temp_ctl.close()
        sys.exit(1)

    # Vytvoření hlavní výstupní složky
    base_output_dir = Path(config['general']['output_directory'])
    try:
        base_output_dir.mkdir(parents=True, exist_ok=True)
        logging.info(f"Test results will be saved in: {base_output_dir.resolve()}")
    except OSError as e:
         logging.critical(f"Failed to create output directory {base_output_dir}: {e}. Exiting.")
         if relay_ctl: relay_ctl.close();
         if dut_ctl: dut_ctl.close();
         if temp_ctl: temp_ctl.close();
         sys.exit(1)


    # Načtení plánu
    temperatures = config['test_plan'].get('temperatures_celsius', [25])
    test_modes_to_run = config['test_plan'].get('test_modes', ['linear'])
    cycles_per_temp = config['test_plan'].get('cycles_per_temperature', 1)
    total_runs = len(temperatures) * cycles_per_temp * len(test_modes_to_run)
    completed_runs = 0

    logging.info(f"Test plan: Temperatures={temperatures}, Modes={test_modes_to_run}, CyclesPerTemp={cycles_per_temp}. Total runs: {total_runs}")
    logging.info(f"DUT Simulation Mode: {'ENABLED' if is_simulation else 'DISABLED'}")
    logging.info(f"Temperature Control: {'MANUAL' if not config['temperature_chamber'].get('enabled', False) else 'AUTOMATIC'}")

    start_time = time.time()
    test_aborted = False

    # --- Hlavní testovací smyčky ---
    try:
        for temp_c in temperatures:
            logging.info(f"===== Processing Temperature: {temp_c}°C =====")
            # Nastavení teploty (jen loguje v manuálním režimu)
            if not test_steps.step_set_temp(temp_ctl, temp_c):
                 logging.error(f"Failed initial temperature set/check for {temp_c}°C. Skipping this temperature.")
                 continue

            for cycle_num in range(cycles_per_temp):
                logging.info(f"--- Starting Overall Cycle {cycle_num + 1}/{cycles_per_temp} for {temp_c}°C ---")

                for test_mode in test_modes_to_run:
                    run_start_time = time.time()
                    logging.info(f"  -- Running Test Mode: '{test_mode}' --")

                    # Volání funkce pro provedení specifického módu
                    # Předáme všechny ovladače a konfiguraci
                    success = run_test_cycle(config, temp_c, cycle_num, test_mode,
                                             temp_ctl, relay_ctl, dut_ctl)

                    run_end_time = time.time()
                    run_duration_m = (run_end_time - run_start_time) / 60

                    if success:
                        completed_runs += 1
                        logging.info(f"  -- Test Mode '{test_mode}' finished successfully in {run_duration_m:.1f} minutes. --")
                    else:
                        logging.error(f"  -- Test Mode '{test_mode}' failed after {run_duration_m:.1f} minutes. --")
                        if config.get('general', {}).get('fail_fast', False):
                             logging.warning("Fail fast enabled. Aborting entire test plan.")
                             test_aborted = True
                             break # Ukončí smyčku módů
                        else:
                             logging.info("Continuing with the next mode/cycle/temperature.")

                    logging.info(f"Progress: {completed_runs}/{total_runs} total runs completed.")
                    # Krátká pauza mezi módy?
                    # time.sleep(10)

                if test_aborted: break # Ukončí smyčku cyklů

            if test_aborted: break # Ukončí smyčku teplot

            logging.info(f"===== Finished all cycles for Temperature: {temp_c}°C =====")

    except KeyboardInterrupt:
        logging.warning("\n<<<<< Test execution interrupted by user (Ctrl+C) >>>>>")
        test_aborted = True
    except Exception as e:
        logging.exception(f"\n<<<<< FATAL ERROR during test execution: {e} >>>>>") # Použij exception pro stack trace
        test_aborted = True
    finally:
        # --- Cleanup ---
        logging.info("Performing final cleanup...")
        if relay_ctl:
            try:
                logging.info("Ensuring all relays are OFF...")
                relay_ctl.turn_all_relays_off() # <-- Explicitní vypnutí všech
                relay_ctl.close()
            except Exception as e_relay: logging.error(f"Error during relay cleanup: {e_relay}")
        # ... (cleanup dut_ctl a temp_ctl) ...
        if dut_ctl:
            try: dut_ctl.close()
            except Exception as e_dut: logging.error(f"Error during DUT controller cleanup: {e_dut}")
        if temp_ctl:
            try: temp_ctl.close()
            except Exception as e_temp: logging.error(f"Error during Temperature controller cleanup: {e_temp}")
        
        # --- Závěrečné logování ---
        logging.info("==================== TEST SUMMARY ====================")  
        end_time = time.time()
        total_duration_s = end_time - start_time
        total_duration_h = total_duration_s / 3600
        status = "ABORTED" if test_aborted else ("COMPLETED" if completed_runs == total_runs else "PARTIALLY COMPLETED")
        logging.info("-" * 60)
        logging.info(f"Test execution {status}.")
        logging.info(f"Total runs completed: {completed_runs}/{total_runs}")
        logging.info(f"Total duration: {total_duration_s:.0f} seconds ({total_duration_h:.2f} hours).")
        logging.info("==================== TEST END ====================")


if __name__ == "__main__":
    # Zajištění, že základní logging funguje i před načtením configu
    if not logger.hasHandlers():
         logger.addHandler(logging.StreamHandler(sys.stdout)) # Minimální handler pro chyby v úvodu
    main()
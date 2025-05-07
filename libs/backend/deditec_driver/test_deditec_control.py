from __future__ import annotations

import json
import sys
import logging # Použijeme standardní logger

# --- Importy ---
# Knihovna pro CLI argumenty
try:
    import click
except ImportError:
     print("ERROR: Please install 'click' library: pip install click")
     sys.exit(1)

# Naše moduly - relativní a absolutní importy
try:
    # Importy z aktuálního balíčku (deditec_driver)
    from .deditec_1_16_on import Deditec_1_16_on
    from .helpers import (
        get_new_pins_on,
        save_new_pins_on,
        turn_on_pins_command,
        get_pins_on, # Přidáno pro zobrazení stavu
        DEDITEC_PORT, # Přidáno pro zobrazení portu
        IP as DEFAULT_IP # Přidáno pro zobrazení/použití výchozí IP
    )
    # Import z nadřazeného balíčku (backend)
    from backend.common import RunResultType, get_logger # RunResultType je Tuple[int, Dict]
    imports_ok = True
except ImportError as e:
    imports_ok = False
    logging.basicConfig() # Základní konfigurace pro fallback
    logger = logging.getLogger(__name__)
    logger.critical(f"Failed to import dependencies: {e}. Cannot run.")
    # Dummy definice pro click dekorátor, aby zbytek souboru prošel syntax check
    class click:
        @staticmethod
        def command(): return lambda f: f
        @staticmethod
        def option(*args, **kwargs): return lambda f: f
    # Ukončení skriptu, pokud importy selžou
    # sys.exit(1) # Neukončujeme zde, aby zbytek kódu prošel kontrolou
else:
    # Nastavení loggeru, pokud importy prošly
    logger = get_logger(__name__)
# ---------------

def run(ip_address: str, on: str = "", off: str = "", all_off: bool = False) -> RunResultType:
    """Logika pro ovládání relé z CLI."""
    if not imports_ok:
         return 1, {"error": "Core dependencies not loaded."}

    try:
        # Zparsovat čísla pinů z řetězců
        on_list = [int(num) for num in on.split(",") if num.strip().isdigit()] if on else []
        off_list = [int(num) for num in off.split(",") if num.strip().isdigit()] if off else []
        logger.debug(f"Parsed pins: ON={on_list}, OFF={off_list}, AllOff={all_off}")
    except ValueError:
        # Toto by nemělo nastat díky isdigit(), ale pro jistotu
        logger.error(f"Invalid PIN numbers format - on: '{on}', off: '{off}'")
        return 1, {"error": "Invalid PIN numbers format."}

    if not on_list and not off_list and not all_off:
        logger.error("No valid PINs or --all_off specified.")
        current_pins = get_pins_on()
        logger.info(f"Current cached state ON: {current_pins}")
        return 1, {"error": "No operation specified.", "current_pins_on": current_pins}

    # Získat předchozí stav pro logování
    previous_pins = get_pins_on()
    logger.info(f"Previous cached state ON: {previous_pins}")

    try:
        # 1. Vypočítat nový stav
        new_pins_on = get_new_pins_on(on_list, off_list, all_off)
        logger.info(f"Calculated new state ON: {new_pins_on}")

        # 2. Vytvořit příkaz
        command = turn_on_pins_command(new_pins_on)
        logger.debug(f"Generated command: {command!r}")

        # 3. Odeslat příkaz
        logger.info(f"Connecting to {ip_address}:{DEDITEC_PORT}...")
        with Deditec_1_16_on(ip=ip_address, port=DEDITEC_PORT, timeout_seconds=5) as controller:
            response = controller.send_command(command)

        # 4. Zpracovat výsledek
        if response == 0:
            logger.info("Command sent successfully. Saving new state.")
            save_new_pins_on(new_pins_on) # Uložit nový stav do cache
            logger.info(f"New cached state ON: {new_pins_on}")
            return 0, {"pins_on_before": previous_pins, "pins_on_after": new_pins_on} # Vrátíme úspěch a stavy
        else:
            logger.error(f"Deditec device returned unexpected response code: {response}")
            return 1, {"error": f"Deditec response code: {response}"}

    except ConnectionError as e:
        logger.error(f"Failed to connect to Deditec at {ip_address}: {e}")
        return 1, {"error": f"ConnectionError: {e}"}
    except TimeoutError:
        logger.error(f"Timeout communicating with Deditec at {ip_address}")
        return 1, {"error": "TimeoutError"}
    except Exception as e:
        logger.exception(f"Deditec:: unexpected error during run: {e}")
        return 1, {"error": f"Unexpected error: {e}"}

# --- CLI rozhraní pomocí Click ---
@click.command()
@click.option("--ip", type=str, default=DEFAULT_IP, help=f"IP address of the Deditec device (default: {DEFAULT_IP})")
@click.option("--on", type=str, default="", help="Comma-separated PINs to turn ON (e.g., '1,3,5')")
@click.option("--off", type=str, default="", help="Comma-separated PINs to turn OFF (e.g., '2,4')")
@click.option("--all_off", is_flag=True, default=False, help="Turn all PINs OFF")
@click.option("--status", is_flag=True, default=False, help="Show current cached status and exit")
def main(ip: str, on: str, off: str, all_off: bool, status: bool) -> None:
    """Simple CLI to control Deditec relays."""
    if not imports_ok:
         print("ERROR: Core dependencies could not be loaded. Exiting.", file=sys.stderr)
         sys.exit(1)

    if status:
        current_pins = get_pins_on()
        print(f"Current cached state ON: {sorted(current_pins)}")
        sys.exit(0)

    # Jinak provedeme akci
    returncode, result_dict = run(ip_address=ip, on=on, off=off, all_off=all_off)

    # Vytisknout výsledek jako JSON pro případné strojové zpracování
    if result_dict:
        print(json.dumps(result_dict, indent=2))

    if returncode != 0:
        logger.error("Operation failed.")
    else:
         logger.info("Operation completed successfully.")

    sys.exit(returncode)


if __name__ == "__main__":
    # Tento blok se spustí při `python -m backend.deditec_driver.test_deditec_control ...`
    main()
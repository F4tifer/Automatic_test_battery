import logging
import time
from pathlib import Path
import sys

# --- Dynamické přidání cest k driverům ---
libs_path = Path(__file__).parent.parent / "libs"
if str(libs_path) not in sys.path:
    sys.path.insert(0, str(libs_path))
backend_path = libs_path / "backend"
if str(backend_path) not in sys.path:
     sys.path.insert(0, str(backend_path))
# -----------------------------------------

# --- Importy z Deditec driveru ---
try:
    from backend.deditec_driver.deditec_1_16_on import Deditec_1_16_on
    from backend.deditec_driver.helpers import (get_pins_on, save_new_pins_on,
                         get_new_pins_on, turn_on_pins_command)
    deditec_driver_available = True
except ImportError as e:
    logging.error(f"ERROR: Failed to import Deditec modules via 'backend'. Check libs structure/files. Using DUMMY Relay.")
    deditec_driver_available = False
    # V případě selhání použijeme dummy třídy
    class Deditec_1_16_on: # Dummy
        def __init__(self, ip, port, timeout_seconds=1): logging.warning(f"Using Dummy Deditec_1_16_on for {ip}:{port}")
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def send_command(self, cmd): logging.info(f"Dummy Deditec send: {cmd!r}"); return 0 # Vždy úspěch
    def get_pins_on(): return []
    def save_new_pins_on(pins): logging.info(f"Dummy save pins: {pins}")
    def get_new_pins_on(on, off, all_off):
        current = set(get_pins_on())
        if all_off: return []
        new = list((current.union(set(on))) - set(off))
        return new
    def turn_on_pins_command(pins): return b'\x00\x00' + bytes([len(pins)]) # Dummy command
# ----------------------------------

class RelayController:
    """Ovládá Deditec relé desku s použitím driveru z Trezoru."""
    DEDITEC_PORT = 9912 # Standardní port pro tento model

    def __init__(self, ip_address: str, usb_relay_pin: int,
                 charger_relay_pin: int | None = None,
                 beeper_pin: int | None = None):
        logging.info(f"Initializing Relay Controller for Deditec at {ip_address}:{self.DEDITEC_PORT}")
        self.ip_address = ip_address
        self.port = self.DEDITEC_PORT
        self.usb_relay_pin = usb_relay_pin
        self.charger_enable_relay_pin = charger_relay_pin
        self.beeper_pin = beeper_pin

        # Kontrola platnosti pinů
        self._validate_pin("USB Power", self.usb_relay_pin)
        self._validate_pin("Charger Enable", self.charger_enable_relay_pin, optional=True)
        self._validate_pin("Beeper", self.beeper_pin, optional=True)

    def _validate_pin(self, name: str, pin: int | None, optional: bool = False, max_pin: int = 16):
        """Pomocná metoda pro validaci čísla pinu."""
        if pin is None:
            if not optional:
                logging.error(f"Mandatory relay pin '{name}' is not configured.")
            return # Volitelný pin může být None
        if not isinstance(pin, int) or not (1 <= pin <= max_pin):
            logging.warning(f"Relay pin '{name}' ({pin}) is outside the typical range (1-{max_pin}). Check configuration.")

    def _execute_relay_command(self, pins_to_turn_on: list[int], pins_to_turn_off: list[int]) -> bool:
        """Interní metoda pro provedení změny stavu relé."""
        if not deditec_driver_available:
            logging.warning("Executing relay command in DUMMY mode.")
            # Simulace logiky zapamatování stavu
            new_pins_state = get_new_pins_on(pins_to_turn_on, pins_to_turn_off, all_off=False)
            save_new_pins_on(new_pins_state)
            logging.info(f"Dummy Relay state updated. Currently ON: {new_pins_state}")
            return True # V dummy režimu vždy úspěch

        try:
            # 1. Zjistit nový celkový stav
            new_pins_state = get_new_pins_on(pins_to_turn_on, pins_to_turn_off, all_off=False)
            logging.debug(f"Calculating new relay state: ON={pins_to_turn_on}, OFF={pins_to_turn_off} -> New total ON state: {new_pins_state}")

            # 2. Připravit command
            command_bytes = turn_on_pins_command(new_pins_state)
            logging.debug(f"Generated command bytes: {command_bytes!r}")

            # 3. Odeslat command
            logging.debug(f"Connecting to Deditec at {self.ip_address}:{self.port} to send command...")
            with Deditec_1_16_on(ip=self.ip_address, port=self.port) as controller:
                response = controller.send_command(command_bytes)

            # 4. Zkontrolovat a uložit
            if response == 0:
                logging.debug("Command sent successfully. Saving new state to cache.")
                save_new_pins_on(new_pins_state)
                logging.info(f"Relay state updated. Currently ON: {new_pins_state}")
                return True
            else:
                logging.error(f"Deditec device returned unexpected response code: {response}")
                return False

        except ConnectionError as e:
            logging.error(f"Failed to connect to Deditec device at {self.ip_address}: {e}")
            return False
        except TimeoutError:
            logging.error(f"Timeout occurred while communicating with Deditec device at {self.ip_address}")
            return False
        except Exception as e:
            logging.exception(f"An unexpected error occurred during relay operation: {e}")
            return False

    def _set_relay(self, pin: int | None) -> bool:
        """Zapne specifické relé (pin 1-16)."""
        if pin is None or not (1 <= pin <= 16):
             if pin is not None: logging.error(f"Invalid pin number to set: {pin}")
             return False
        logging.info(f"Setting relay pin {pin} ON")
        return self._execute_relay_command(pins_to_turn_on=[pin], pins_to_turn_off=[])

    def _clear_relay(self, pin: int | None) -> bool:
        """Vypne specifické relé (pin 1-16)."""
        if pin is None or not (1 <= pin <= 16):
            if pin is not None: logging.error(f"Invalid pin number to clear: {pin}")
            return False
        logging.info(f"Setting relay pin {pin} OFF")
        return self._execute_relay_command(pins_to_turn_on=[], pins_to_turn_off=[pin])

    def _set_relays_off(self, pins: list[int | None]) -> bool:
         """Vypne seznam relé najednou."""
         valid_pins = [p for p in pins if p is not None and (1 <= p <= 16)]
         if not valid_pins: return True # Nic k vypnutí
         logging.info(f"Setting relay pins {valid_pins} OFF")
         return self._execute_relay_command(pins_to_turn_on=[], pins_to_turn_off=valid_pins)

    # --- Veřejné metody ---
    def connect_usb(self) -> bool:
        """Připojí napájení USB k DUT."""
        success = self._set_relay(self.usb_relay_pin)
        if success: time.sleep(0.5)
        return success

    def disconnect_usb(self) -> bool:
        """Odpojí napájení USB od DUT."""
        success = self._clear_relay(self.usb_relay_pin)
        if success: time.sleep(0.5)
        return success

    def enable_charger_hw(self) -> bool:
        """Aktivuje HW enable nabíječky."""
        success = self._set_relay(self.charger_enable_relay_pin)
        if success: time.sleep(0.5)
        return success

    def disable_charger_hw(self) -> bool:
        """Deaktivuje HW enable nabíječky."""
        success = self._clear_relay(self.charger_enable_relay_pin)
        if success: time.sleep(0.5)
        return success

    def beep(self, duration_ms: int = 100) -> bool:
        """Krátce zapne a vypne bzučák."""
        if self.beeper_pin is None:
            logging.warning("Beep requested, but beeper_pin is not configured.")
            return False

        logging.debug(f"Beeping on pin {self.beeper_pin} for {duration_ms}ms...")
        success_on = self._set_relay(self.beeper_pin)
        if success_on:
            time.sleep(duration_ms / 1000.0)
            success_off = self._clear_relay(self.beeper_pin)
            return success_off
        else:
            self._clear_relay(self.beeper_pin) # Zkusit vypnout i tak
            return False

    def close(self):
         """Metoda pro případné budoucí čištění."""
         logging.debug("RelayController close() called.")
         # V této implementaci není co čistit, spojení je per-příkaz
         pass
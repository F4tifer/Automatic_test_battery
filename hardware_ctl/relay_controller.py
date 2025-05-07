# hardware_ctl/relay_controller.py

import logging
import time
from pathlib import Path
import sys
from typing import List, Optional, Set # Přidáno List, Optional, Set

# --- Dynamické přidání cest k driverům ---
libs_path = Path(__file__).parent.parent / "libs"
if str(libs_path) not in sys.path:
    sys.path.insert(0, str(libs_path))
backend_path = libs_path / "backend"
if str(backend_path) not in sys.path:
     sys.path.insert(0, str(backend_path))
# -----------------------------------------

# --- Importy z Deditec driveru (s fallbackem) ---
try:
    from backend.deditec_driver.deditec_1_16_on import Deditec_1_16_on
    from backend.deditec_driver.helpers import (get_pins_on, save_new_pins_on,
                         get_new_pins_on, turn_on_pins_command)
    deditec_driver_available = True
except ImportError as e:
    logging.error(f"ERROR: Failed to import Deditec modules via 'backend'. Using DUMMY Relay.")
    deditec_driver_available = False
    # Dummy třídy (zkráceno pro přehlednost)
    class Deditec_1_16_on:
        def __init__(self, ip, port, timeout_seconds=1): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def send_command(self, cmd): return 0
    def get_pins_on(): return []
    def save_new_pins_on(pins): pass
    def get_new_pins_on(on, off, all_off): return list(set(on))
    def turn_on_pins_command(pins): return b'\x00'
# ----------------------------------

class RelayController:
    """Ovládá Deditec relé desku, umožňuje ovládání více relé najednou."""
    DEDITEC_PORT = 9912
    MAX_PIN = 16 # Maximální číslo pinu (pro 16-releovou desku)

    def __init__(self, ip_address: str,
                 usb_relay_pins: List[int], # <-- Změna na List
                 charger_relay_pins: Optional[List[int]] = None, # <-- Změna na Optional[List]
                 beeper_pins: Optional[List[int]] = None): # <-- Změna na Optional[List]
        """
        Inicializuje RelayController.

        Args:
            ip_address: IP adresa Deditec desky.
            usb_relay_pins: Seznam pinů (1-16) pro ovládání USB napájení.
            charger_relay_pins: Seznam pinů (1-16) pro HW enable nabíječky (volitelné).
            beeper_pins: Seznam pinů (1-16) pro bzučák (volitelné).
        """
        logging.info(f"Initializing Relay Controller for Deditec at {ip_address}:{self.DEDITEC_PORT}")
        self.ip_address = ip_address
        self.port = self.DEDITEC_PORT

        # Uložení seznamů pinů a jejich validace
        self.usb_power_pins = self._validate_pin_list("USB Power", usb_relay_pins)
        self.charger_enable_pins = self._validate_pin_list("Charger Enable", charger_relay_pins or [])
        self.beeper_pins = self._validate_pin_list("Beeper", beeper_pins or [])

        if not self.usb_power_pins:
             logging.warning("No valid USB power relay pins configured. USB control will not work.")

    def _validate_pin_list(self, name: str, pins: List[int]) -> List[int]:
        """Validuje seznam pinů a vrátí pouze platné unikátní piny."""
        valid_pins = set()
        if not isinstance(pins, list):
            logging.error(f"Configuration error: '{name}' pins must be a list, got {type(pins)}. Ignoring.")
            return []
        for pin in pins:
            if isinstance(pin, int) and 1 <= pin <= self.MAX_PIN:
                valid_pins.add(pin)
            else:
                logging.warning(f"Invalid pin number '{pin}' found in '{name}' list. Ignoring.")
        return sorted(list(valid_pins)) # Vrátí seřazený seznam unikátních platných pinů

    def _execute_relay_command(self, pins_to_turn_on: List[int], pins_to_turn_off: List[int]) -> bool:
        """Interní metoda pro provedení změny stavu relé."""
        if not deditec_driver_available:
            logging.warning("Executing relay command in DUMMY mode.")
            # Simulace logiky zapamatování stavu
            new_pins_state = get_new_pins_on(pins_to_turn_on, pins_to_turn_off, all_off=False)
            save_new_pins_on(new_pins_state)
            logging.info(f"Dummy Relay state updated. Currently ON: {new_pins_state}")
            return True

        try:
            # 1. Zjistit nový celkový stav
            new_pins_state = get_new_pins_on(pins_to_turn_on, pins_to_turn_off, all_off=False)
            logging.debug(f"Calculating new relay state: Request ON={pins_to_turn_on}, Request OFF={pins_to_turn_off} -> New total ON state: {new_pins_state}")

            # 2. Připravit command
            command_bytes = turn_on_pins_command(new_pins_state)
            logging.debug(f"Generated command bytes: {command_bytes!r}")

            # 3. Odeslat command
            logging.debug(f"Connecting to Deditec at {self.ip_address}:{self.port} to send command...")
            with Deditec_1_16_on(ip=self.ip_address, port=self.port, timeout_seconds=3) as controller: # Timeout pro spojení
                response = controller.send_command(command_bytes) # Použije timeout socketu definovaný v Deditec_1_16_on

            # 4. Zkontrolovat a uložit
            if response == 0:
                logging.debug("Command sent successfully. Saving new state to cache.")
                save_new_pins_on(new_pins_state)
                logging.info(f"Relay state updated. Currently ON: {get_pins_on()}") # Zobrazit aktuální stav z cache
                return True
            else:
                logging.error(f"Deditec device returned unexpected response code: {response}")
                return False

        except ConnectionError as e: logging.error(f"Failed to connect to Deditec at {self.ip_address}: {e}"); return False
        except TimeoutError: logging.error(f"Timeout communicating with Deditec at {self.ip_address}"); return False
        except Exception as e: logging.exception(f"An unexpected error occurred during relay operation: {e}"); return False

    # --- NOVÁ VEŘEJNÁ METODA (doplněná o validaci) ---
    def set_multiple_relays(self, pins_to_turn_on: Optional[List[int]] = None,
                            pins_to_turn_off: Optional[List[int]] = None) -> bool:
        """
        Zapne nebo vypne více relé najednou jedním příkazem.

        Args:
            pins_to_turn_on: Seznam čísel pinů (1-16), které se mají zapnout.
            pins_to_turn_off: Seznam čísel pinů (1-16), které se mají vypnout.

        Returns:
            True pokud byl příkaz úspěšně odeslán, jinak False.
        """
        valid_on = self._validate_pin_list("Turn ON request", pins_to_turn_on or [])
        valid_off = self._validate_pin_list("Turn OFF request", pins_to_turn_off or [])

        if not valid_on and not valid_off:
            logging.info("set_multiple_relays: No valid pins specified to change.")
            return True # Nic k provedení

        logging.info(f"Setting multiple relays: Requesting ON={valid_on}, Requesting OFF={valid_off}")
        return self._execute_relay_command(pins_to_turn_on=valid_on, pins_to_turn_off=valid_off)

    # --- Upravené veřejné metody pro práci se seznamy ---
    def connect_usb(self) -> bool:
        """Připojí napájení USB k DUT sepnutím VŠECH nakonfigurovaných USB pinů."""
        if not self.usb_power_pins: return True # Nic ke spínání
        logging.info(f"Connecting USB Power (Pins: {self.usb_power_pins})...")
        success = self.set_multiple_relays(pins_to_turn_on=self.usb_power_pins)
        if success: time.sleep(0.5)
        return success

    def disconnect_usb(self) -> bool:
        """Odpojí napájení USB od DUT rozepnutím VŠECH nakonfigurovaných USB pinů."""
        if not self.usb_power_pins: return True
        logging.info(f"Disconnecting USB Power (Pins: {self.usb_power_pins})...")
        success = self.set_multiple_relays(pins_to_turn_off=self.usb_power_pins)
        if success: time.sleep(0.5)
        return success

    def enable_charger_hw(self) -> bool:
        """Aktivuje HW enable nabíječky sepnutím VŠECH nakonfigurovaných charger pinů."""
        if not self.charger_enable_pins: return True
        logging.info(f"Enabling Charger HW (Pins: {self.charger_enable_pins})...")
        success = self.set_multiple_relays(pins_to_turn_on=self.charger_enable_pins)
        if success: time.sleep(0.5)
        return success

    def disable_charger_hw(self) -> bool:
        """Deaktivuje HW enable nabíječky rozepnutím VŠECH nakonfigurovaných charger pinů."""
        if not self.charger_enable_pins: return True
        logging.info(f"Disabling Charger HW (Pins: {self.charger_enable_pins})...")
        success = self.set_multiple_relays(pins_to_turn_off=self.charger_enable_pins)
        if success: time.sleep(0.5)
        return success

    def beep(self, duration_ms: int = 100) -> bool:
        """Krátce zapne a vypne VŠECHNY nakonfigurované bzučáky."""
        if not self.beeper_pins:
            logging.warning("Beep requested, but no beeper_pins are configured.")
            return False

        logging.debug(f"Beeping on pins {self.beeper_pins} for {duration_ms}ms...")
        # Zapneme všechny bzučáky
        success_on = self.set_multiple_relays(pins_to_turn_on=self.beeper_pins)
        if success_on:
            time.sleep(duration_ms / 1000.0)
            # Vypneme všechny bzučáky
            success_off = self.set_multiple_relays(pins_to_turn_off=self.beeper_pins)
            return success_off
        else:
            # Pokud se nepodařilo zapnout, zkusíme aspoň vypnout
            self.set_multiple_relays(pins_to_turn_off=self.beeper_pins)
            return False

    def turn_all_relays_off(self) -> bool:
         """Vypne všech 16 relé."""
         logging.info("Turning all relays OFF.")
         # Vytvoříme seznam všech pinů (1 až MAX_PIN)
         all_pins = list(range(1, self.MAX_PIN + 1))
         return self.set_multiple_relays(pins_to_turn_off=all_pins)

    def close(self):
         """Metoda pro případné budoucí čištění (např. explicitní vypnutí všech relé)."""
         logging.debug("RelayController close() called.")
         # Můžeme sem přidat volitelné vypnutí všech relé při ukončení programu
         # self.turn_all_relays_off() # Odkomentuj, pokud chceš zajistit vypnutí
         pass
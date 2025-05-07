import time
import logging
from typing import TYPE_CHECKING

# Podmíněný import pro type hinting
if TYPE_CHECKING:
    from libs.prodtest_cli import prodtest_cli, ProdtestResponse

# Přidání cesty k libs pro import prodtest_cli
import sys
from pathlib import Path
libs_path_ctrl = Path(__file__).parent.parent / "libs"
if str(libs_path_ctrl) not in sys.path:
    sys.path.insert(0, str(libs_path_ctrl))

# Import prodtest_cli po úpravě sys.path
try:
    from prodtest_cli import prodtest_cli, ProdtestResponse
except ImportError as e:
    logging.error(f"FATAL: Could not import prodtest_cli from {libs_path_ctrl}. Check file presence and structure.")
    # Definujeme dummy třídy, aby zbytek mohl selhat při inicializaci
    class ProdtestResponse: pass
    class prodtest_cli:
        def __init__(self, *args, **kwargs): raise ImportError("prodtest_cli not found")

class DutController:
    """Ovládání reálného DUT pomocí prodtest_cli přes sériový port."""
    def __init__(self, port: str, dut_cmds: dict, verbose: bool = False):
        self.cli = None # Inicializace na None
        logging.info(f"Initializing Real DUT Controller on port {port}...")
        try:
            # Inicializace může selhat (např. port neexistuje)
            self.cli = prodtest_cli(device=port, verbose=verbose)
            self.cmds = dut_cmds
            logging.info("Real DUT Controller Initialized.")
            # Můžeme zkusit ověřit komunikaci zde? Nebo v check_peripherals.
        except Exception as e:
            logging.error(f"Failed to initialize prodtest_cli on port {port}: {e}")
            # Předáme výjimku dál, aby main věděl, že inicializace selhala
            raise

    def _send_command(self, command_key: str, *args) -> ProdtestResponse:
        """Odešle příkaz definovaný v konfiguraci."""
        if self.cli is None:
             logging.error("Cannot send command: prodtest_cli not initialized.")
             # Vrátíme dummy neúspěšnou odpověď
             resp = ProdtestResponse()
             resp.OK = False
             return resp

        if command_key not in self.cmds:
            logging.error(f"DUT command key '{command_key}' not found in configuration.")
            resp = ProdtestResponse()
            resp.OK = False
            return resp

        command_template = self.cmds[command_key]
        if not command_template: # Pokud je příkaz prázdný v configu
             logging.warning(f"DUT command '{command_key}' is empty in config, skipping.")
             resp = ProdtestResponse()
             resp.OK = False # Považujeme za neúspěch? Nebo ignorovat?
             return resp

        try:
            if args:
                command = command_template.format(*args)
            else:
                command = command_template
        except Exception as e:
             logging.error(f"Failed to format command '{command_template}' with args {args}: {e}")
             command = command_template # Zkusíme poslat neformátovaný

        parts = command.split(' ')
        cmd_base = parts[0]
        cmd_args = parts[1:]

        logging.debug(f"Sending command to DUT: {cmd_base} {' '.join(cmd_args)}")
        try:
            response = self.cli.send_command(cmd_base, *cmd_args)
            if not response.OK:
                logging.warning(f"DUT command '{command}' failed or returned ERROR.")
            return response
        except Exception as e:
             logging.exception(f"Error sending command '{command}' to DUT: {e}")
             resp = ProdtestResponse()
             resp.OK = False
             return resp

    def _parse_response_float(self, response: ProdtestResponse, key_for_error: str) -> float | None:
        """Pomocná funkce pro parsování float hodnoty z odpovědi."""
        if response.OK and response.data_entries:
            try:
                # Očekáváme formát "VALUE" nebo "Key=VALUE" v prvním prvku data_entries
                raw_value = response.data_entries[0][0]
                if '=' in raw_value:
                     value_str = raw_value.split('=')[-1]
                else:
                     value_str = raw_value
                return float(value_str)
            except (IndexError, ValueError, TypeError) as e:
                logging.error(f"Could not parse float for '{key_for_error}' from response: {response.data_entries}. Error: {e}")
        elif not response.OK:
             logging.warning(f"Command for '{key_for_error}' returned ERROR.")
        else: # OK ale žádná data
             logging.warning(f"Command for '{key_for_error}' OK but no data received.")
        return None

    def _parse_response_int(self, response: ProdtestResponse, key_for_error: str) -> int | None:
        """Pomocná funkce pro parsování int hodnoty z odpovědi."""
        float_val = self._parse_response_float(response, key_for_error) # Zkusíme jako float
        if float_val is not None:
            try:
                return int(float_val) # Převedeme na int
            except ValueError:
                 logging.error(f"Could not convert parsed value '{float_val}' to int for '{key_for_error}'.")
        return None

    def _parse_response_string(self, response: ProdtestResponse, key_for_error: str) -> str | None:
        """Pomocná funkce pro parsování string hodnoty z odpovědi."""
        if response.OK and response.data_entries:
            try:
                 # Očekáváme formát "VALUE" nebo "Key=VALUE"
                raw_value = response.data_entries[0][0]
                if '=' in raw_value:
                     value_str = raw_value.split('=', 1)[-1] # Split jen jednou
                else:
                     value_str = raw_value
                return value_str.strip() # Odstranit bílé znaky
            except (IndexError, TypeError) as e:
                 logging.error(f"Could not parse string for '{key_for_error}' from response: {response.data_entries}. Error: {e}")
        elif not response.OK:
             logging.warning(f"Command for '{key_for_error}' returned ERROR.")
        else:
             logging.warning(f"Command for '{key_for_error}' OK but no data received.")
        return None

    # --- Implementace veřejných metod ---
    def enable_charging_sw(self) -> bool:
        logging.info("Sending command: Enable Charging (SW)")
        resp = self._send_command('enable_charging')
        return resp.OK

    def disable_charging_sw(self) -> bool:
        logging.info("Sending command: Disable Charging (SW)")
        resp = self._send_command('disable_charging')
        return resp.OK

    def get_battery_voltage(self) -> float | None:
        resp = self._send_command('get_voltage')
        return self._parse_response_float(resp, 'get_voltage')

    def get_battery_current(self) -> float | None:
        resp = self._send_command('get_current')
        return self._parse_response_float(resp, 'get_current')

    def get_operation_mode(self) -> str | None:
        resp = self._send_command('get_status')
        # Parsování modu může být složitější - hledáme klíčová slova
        if resp.OK:
            response_text = ""
            if resp.data_entries:
                 response_text += " ".join(item for sublist in resp.data_entries for item in sublist)
            if resp.trace:
                 response_text += " ".join(resp.trace)

            response_text = response_text.upper() # Pro case-insensitive porovnání
            if "CHARGING" in response_text: return "CHARGING"
            if "DISCHARGING" in response_text: return "DISCHARGING"
            if "IDLE" in response_text: return "IDLE"

            logging.warning(f"Could not determine mode from status response: '{response_text[:100]}...'")
            # Můžeme vrátit první datový záznam jako fallback? Nebo None?
            if resp.data_entries: return resp.data_entries[0][0].strip() # Vrátíme první záznam
        return None # Selhání nebo neznámý mód


    def get_dut_timestamp(self) -> int | None:
        resp = self._send_command('get_dut_time')
        return self._parse_response_int(resp, 'get_dut_time')

    def get_ntc_temp(self) -> float | None:
        resp = self._send_command('get_ntc_temp')
        return self._parse_response_float(resp, 'get_ntc_temp')

    def get_vsys(self) -> float | None:
        resp = self._send_command('get_vsys')
        return self._parse_response_float(resp, 'get_vsys')

    def get_die_temp(self) -> float | None:
        resp = self._send_command('get_die_temp')
        return self._parse_response_float(resp, 'get_die_temp')

    def get_iba_meas_status(self) -> str | None:
        resp = self._send_command('get_iba_meas_status')
        return self._parse_response_string(resp, 'get_iba_meas_status')

    def get_buck_status(self) -> str | None:
        resp = self._send_command('get_buck_status')
        return self._parse_response_string(resp, 'get_buck_status')

    # --- Volitelné metody ---
    def set_discharge_current(self, current_ma: int) -> bool:
        if 'set_discharge_current' not in self.cmds:
             logging.warning("DUT command 'set_discharge_current' not configured.")
             return False
        logging.info(f"Sending command: Set Discharge Current to {current_ma} mA")
        resp = self._send_command('set_discharge_current', str(current_ma))
        return resp.OK

    # --- Cleanup ---
    def close(self):
        """Ukončí sériovou komunikaci."""
        if self.cli and hasattr(self.cli, 'vcp') and self.cli.vcp:
            logging.info("Closing DUT serial connection...")
            try:
                self.cli.vcp.close()
            except Exception as e:
                 logging.error(f"Error closing serial port: {e}")
            self.cli = None
        elif self.cli:
             logging.debug("DUT controller had cli object, but no active vcp to close.")
             self.cli = None
        else:
             logging.debug("DUT controller already closed or not initialized.")

    def __del__(self):
        # Zajistí zavření portu i při neočekávaném ukončení objektu
        self.close()
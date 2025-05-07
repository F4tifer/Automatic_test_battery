import serial
import time
import logging # Použijeme logging pro lepší kontrolu
from dataclasses import dataclass, field
from typing import List

BAUDRATE_DEFAULT = 115200
BYTESIZE_DEFAULT = serial.EIGHTBITS # Použít konstantu z pyserial
PARITY_DEFAULT   = serial.PARITY_NONE
STOPBITS_DEFAULT = serial.STOPBITS_ONE
CMD_TIMEOUT_S    = 10 # Timeout pro čtení řádku

# Nastavení loggeru pro tento modul
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG) # Pro detailní ladění komunikace

@dataclass
class ProdtestResponse:
    timestamp: float | None = None
    cmd_sent: str | None = None # Přejmenováno pro jasnost
    trace: list = field(default_factory=list)
    data_entries: list = field(default_factory=list)
    raw_lines: list = field(default_factory=list) # Přidáno pro ladění
    OK: bool = False
    error_message: str | None = None # Pro zachycení chybové zprávy

class prodtest_cli():

    def __init__(self, device, baudrate=BAUDRATE_DEFAULT, verbose=False):
        self.verbose = verbose # verbose řídí jen print výstup této třídy
        self.vcp: serial.Serial | None = None # Lepší typování
        logger.info(f"Initializing prodtest_cli for {device} at {baudrate} baud.")
        try:
            self.vcp = serial.Serial(port=device,
                                    baudrate=baudrate,
                                    bytesize=BYTESIZE_DEFAULT,
                                    parity=PARITY_DEFAULT,
                                    stopbits=STOPBITS_DEFAULT,
                                    timeout=CMD_TIMEOUT_S) # Nastavení globálního timeoutu
            # is_open je vlastnost, ne metoda
            if not self.vcp.is_open:
                 # Vyvolání standardní výjimky
                 raise serial.SerialException(f"Failed to open serial port {device}")
            logger.info(f"Serial port {device} opened successfully.")
        except serial.SerialException as e:
            logger.error(f"SerialException during VCP initialization: {e}")
            self.vcp = None # Zajistíme, že je None při chybě
            raise # Předáme výjimku dál

    def __del__(self):
        self.close() # Zajistí zavření při smazání objektu

    def close(self):
        if self.vcp and self.vcp.is_open:
             logger.info("Closing VCP port.")
             try:
                 self.vcp.close()
             except Exception as e:
                  logger.error(f"Error closing VCP port: {e}")
        self.vcp = None

    def set_verbose(self, verbose):
        self.verbose = verbose

    def get_verbose(self):
        return self.verbose

    def send_command(self, cmd: str, *args, skip_response=False) -> ProdtestResponse:
        if self.vcp is None or not self.vcp.is_open:
            # Neměli bychom se sem dostat, pokud __init__ vyvolal výjimku
            logger.error("VCP not initialized or closed.")
            response = ProdtestResponse()
            response.error_message = "VCP not initialized or closed"
            return response

        response = ProdtestResponse()
        response.timestamp = time.time()

        # Sestavení příkazu
        command_parts = [cmd] + [str(k) for k in args]
        full_cmd_str = ' '.join(command_parts)
        response.cmd_sent = full_cmd_str # Uložíme celý příkaz
        cmd_to_send = full_cmd_str + '\n' # Přidáme nový řádek

        try:
            # Vyprázdnit buffery před odesláním/čtením
            self.vcp.reset_input_buffer()
            self.vcp.reset_output_buffer()

            self._log_output(cmd_to_send)
            self.vcp.write(cmd_to_send.encode('ascii', errors='ignore')) # Posíláme jako ASCII
            self.vcp.flush() # Zajistit odeslání

            if skip_response:
                response.OK = True # Předpokládáme úspěch, když nečekáme odpověď
                return response

            # Čtení odpovědi řádek po řádku s timeoutem
            while True:
                try:
                    # readline() používá timeout nastavený v konstruktoru
                    line_bytes = self.vcp.readline()
                    if not line_bytes:
                        # Timeout! readline() vrátilo prázdné byty
                        logger.warning(f"Timeout waiting for response after command: {full_cmd_str}")
                        response.error_message = "Timeout waiting for response"
                        break # Ukončíme smyčku

                    # Dekódovat s ošetřením chyb
                    line = line_bytes.decode('ascii', errors='replace').strip()
                    response.raw_lines.append(line) # Uložíme syrový řádek
                    self._log_input(line)

                    # Parsování odpovědi
                    if not line: continue # Přeskočit prázdné řádky

                    if line.startswith("#"): # Traces
                        response.trace.append(line[1:].strip())
                    elif line.startswith("PROGRESS"): # Data
                        data_part = line[len("PROGRESS"):].strip()
                        if data_part:
                             response.data_entries.append(data_part.split(" ")) # Rozdělit podle mezer
                    elif "OK" in line:
                        response.OK = True
                        break # Úspěšné ukončení
                    elif "ERROR" in line:
                         response.error_message = line # Uložíme chybový řádek
                         logger.warning(f"Received ERROR response: {line}")
                         break # Chyba

                except serial.SerialException as e:
                    logger.error(f"SerialException during readline: {e}")
                    response.error_message = f"SerialException: {e}"
                    break
                except Exception as e:
                    logger.exception(f"Unexpected error during response reading: {e}")
                    response.error_message = f"Unexpected error: {e}"
                    break

        except serial.SerialException as e:
             logger.error(f"SerialException during command send/flush: {e}")
             response.error_message = f"SerialException: {e}"
             self.close() # Zavřeme port při vážné chybě
        except Exception as e:
            logger.exception(f"Unexpected error sending command: {e}")
            response.error_message = f"Unexpected error: {e}"

        return response

    def _log_output(self, message):
        # Logujeme přes standardní logger, ne print
        logger.debug(f'OUT > {message.strip()}')
        if(self.verbose): # Pokud je verbose, tiskne i na konzoli
            print(f'[{time.strftime("%H:%M:%S")}] VCP OUT > {message.strip()}')

    def _log_input(self, message):
        logger.debug(f'IN  < {message.strip()}')
        if(self.verbose):
             print(f'[{time.strftime("%H:%M:%S")}] VCP IN  < {message.strip()}')

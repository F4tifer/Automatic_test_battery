import csv
import time
import threading
import logging
from pathlib import Path
from typing import TYPE_CHECKING

# Podmíněný import pro type hinting
if TYPE_CHECKING:
    from hardware_ctl.dut_controller import DutController
    from simulation.dummy_dut_controller import DummyDutController
    DutControllerTypes = DutController | DummyDutController

class DataLogger:
    """Loguje data z DUT do CSV souboru v samostatném vlákně."""
    def __init__(self, dut: 'DutControllerTypes', log_interval_s: float, output_file: Path):
        if dut is None:
             raise ValueError("DUT controller object cannot be None for DataLogger.")
        self.dut = dut
        self.log_interval = max(0.1, log_interval_s) # Min interval 100ms
        self.output_file = output_file
        self._log_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.is_logging = False
        self.logged_data_file: Path | None = None
        self.header = [ # Definice hlavičky podle test_log.csv
            'time', 'vbat', 'ibat', 'ntc_temp', 'vsys',
            'die_temp', 'iba_meas_status', 'buck_status', 'mode'
        ]

    def start_logging(self) -> bool:
        if self.is_logging:
            logging.warning("DataLogger: Logging is already active.")
            return True

        self._stop_event.clear()
        try:
            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            self.logged_data_file = self.output_file
            logging.info(f"DataLogger: Starting logging to {self.output_file} every {self.log_interval:.1f}s")

            with open(self.output_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(self.header) # Zápis hlavičky

            self._log_thread = threading.Thread(target=self._logging_loop, name=f"DataLogger-{self.output_file.stem}", daemon=True)
            self.is_logging = True
            self._log_thread.start()
            return True
        except IOError as e:
            logging.error(f"DataLogger: Could not open log file {self.output_file} for writing: {e}")
            self.logged_data_file = None
            return False
        except Exception as e:
             logging.exception(f"DataLogger: Unexpected error during logger start: {e}")
             return False

    def _logging_loop(self):
        logging.debug(f"DataLogger: Logging loop started for {self.output_file.name}.")
        try:
            with open(self.output_file, 'a', newline='') as f:
                writer = csv.writer(f)
                while not self._stop_event.is_set():
                    loop_start_time = time.monotonic()

                    # Získání všech dat z DUT
                    try:
                        dut_time = self.dut.get_dut_timestamp()
                        vbat = self.dut.get_battery_voltage()
                        ibat = self.dut.get_battery_current()
                        ntc_temp = self.dut.get_ntc_temp()
                        vsys = self.dut.get_vsys()
                        die_temp = self.dut.get_die_temp()
                        iba_status = self.dut.get_iba_meas_status()
                        buck_status = self.dut.get_buck_status()
                        mode = self.dut.get_operation_mode()
                    except Exception as e:
                         logging.error(f"DataLogger: Error getting data from DUT: {e}")
                         # Pokračovat a zapsat prázdné hodnoty? Nebo přeskočit?
                         # Prozatím přeskočíme tento cyklus logování
                         time.sleep(self.log_interval / 2) # Krátká pauza
                         continue

                    # Formátování a zápis řádku
                    writer.writerow([
                        f"{dut_time:09d}" if dut_time is not None else "",
                        f"{vbat:.3f}" if vbat is not None else "",
                        f"{ibat:.3f}" if ibat is not None else "",
                        f"{ntc_temp:.3f}" if ntc_temp is not None else "",
                        f"{vsys:.3f}" if vsys is not None else "",
                        f"{die_temp:.3f}" if die_temp is not None else "",
                        iba_status if iba_status is not None else "",
                        buck_status if buck_status is not None else "",
                        mode if mode is not None else ""
                    ])
                    # f.flush() # Není obvykle nutné, může zpomalit

                    # Výpočet a čekání
                    elapsed_time = time.monotonic() - loop_start_time
                    sleep_time = max(0, self.log_interval - elapsed_time)
                    if sleep_time > 0:
                       # wait() je přerušitelné událostí stop_event
                       self._stop_event.wait(sleep_time)

        except IOError as e:
             logging.error(f"DataLogger: IO Error during logging to {self.output_file}: {e}")
        except Exception as e:
             # Logování výjimky včetně tracebacku
             logging.exception(f"DataLogger: Unexpected error in logging loop for {self.output_file.name}: {e}")
        finally:
             logging.info(f"DataLogger: Logging thread stopped for {self.output_file.name}.")
             self.is_logging = False # Důležité nastavit až po ukončení vlákna

    def stop_logging(self) -> Path | None:
        """Zastaví logování dat."""
        if not self.is_logging or self._log_thread is None:
            return self.logged_data_file # Vrátí cestu, pokud byla nastavena

        logging.info(f"DataLogger: Stopping logging for {self.output_file.name}...")
        self._stop_event.set()
        join_timeout = max(2.0, self.log_interval * 2)
        self._log_thread.join(timeout=join_timeout)

        if self._log_thread.is_alive():
            logging.warning(f"DataLogger: Logging thread for {self.output_file.name} did not stop gracefully.")
        else:
             logging.debug(f"DataLogger: Logging thread for {self.output_file.name} joined successfully.")

        self.is_logging = False # Až po join()
        self._log_thread = None
        logging.info(f"DataLogger: Logging stopped for {self.output_file.name}.")
        return self.logged_data_file

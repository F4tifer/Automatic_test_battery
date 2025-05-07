import logging
import sys
from typing import Tuple, Any, Dict

# Definice typu pro výsledek (často se používá v Trezor kódu)
RunResultType = Tuple[int, Dict[str, Any]] # Tuple: (return_code, result_dict)

# Nastavení základního loggeru, pokud ještě není nastaven
# Můžeme sdílet logger nastavený v main_tester.py
logger = logging.getLogger("backend.common") # Použijeme specifické jméno
# logger.setLevel(logging.DEBUG) # Lze nastavit úroveň zde nebo globálně

def get_logger(name: str) -> logging.Logger:
    # Vrací logger se specifickým jménem, ale používá globální konfiguraci
    return logging.getLogger(name)

# Dummy handle_timeout pro kompatibilitu
def handle_timeout(signum, frame):
    logger = get_logger("common")
    logger.error("TIMEOUT OCCURRED (dummy handler)")
    raise TimeoutError("Operation timed out (dummy handler)")

# Dummy CustomArgumentParser (pravděpodobně není volán)
import argparse
class CustomArgumentParser(argparse.ArgumentParser):
   def __init__(self, *args, logger=None, **kwargs):
       super().__init__(*args, **kwargs)
       self.logger = logger if logger else get_logger("argparse")
       logger.debug("Dummy CustomArgumentParser initialized.")

logger.debug("Dummy common.py loaded.")

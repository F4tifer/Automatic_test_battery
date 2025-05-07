# notifications.py

import logging
import webbrowser # Modul pro otevírání prohlížeče
# from urllib.parse import quote_plus # Už nepotřebujeme pro sestavení URL
from typing import Optional
import platform

logger = logging.getLogger(__name__)

# --- PEVNĚ NASTAVENÁ FUNKČNÍ URL ---
# Zkontroluj/uprav text zprávy (musí být URL-enkódovaný)
HARDCODED_WORKING_URL = "https://api.callmebot.com/whatsapp.php?source=web&phone=+420721262009&apikey=2397620&text=MANUAL+ACTION+Set+Temp+and+Press+Enter"
# ----------------------------------

def send_whatsapp_message(phone_number: Optional[str], apikey: Optional[str], message: str) -> bool:
    """
    Otevře PEVNĚ NASTAVENOU URL pro odeslání WhatsApp zprávy
    v systémovém prohlížeči.
    Ignoruje argumenty phone_number, apikey, message.

    Returns:
        True pokud se podařilo spustit otevření URL, jinak False.
    """
    logger.warning("Using hardcoded URL for WhatsApp notification.") # Varování, že používáme pevný odkaz

    try:
        # Použijeme pevně nastavenou URL
        url_to_open = HARDCODED_WORKING_URL
        logger.info(f"Attempting to open hardcoded WhatsApp URL in browser...")
        logger.debug(f"Hardcoded URL: {url_to_open}") # Logování pro kontrolu

        # Otevření URL v novém okně/záložce
        was_opened = webbrowser.open_new_tab(url_to_open)

        if was_opened:
            logger.info("Browser command executed to open hardcoded WhatsApp URL.")
            # Upravená výzva pro uživatele
            print("-" * 60)
            print("--> ACTION REQUIRED in Web Browser & Console <---")
            print("    1. A browser tab/window opened with the CallMeBot API.")
            print("       Check it to ensure the message is being sent.")
            print("    2. Return to this console window.")
            print("-" * 60)
            return True
        else:
            logger.error("Failed to execute command to open browser.")
            if platform.system() == "Linux":
                 logger.error("On Linux systems without a default browser configured in a desktop environment, this might fail.")
            return False

    except Exception as e:
        logger.exception(f"An unexpected error occurred while trying to open hardcoded WhatsApp URL: {e}")
        return False

# Testovací blok pro přímé spuštění
if __name__ == '__main__':
    # Nastavení jednoduchého logování pro test
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    print("Testing WhatsApp notification module (opens hardcoded URL in browser)...")
    # Argumenty phone/key/msg se teď ignorují
    success = send_whatsapp_message("ignored", "ignored", "ignored message")
    if success:
        print("Browser command executed (check your browser).")
    else:
        print("Failed to execute browser command.")
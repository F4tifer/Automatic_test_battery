# notifications.py

import logging
import requests
import json
from typing import Optional
# from urllib.parse import quote_plus # Už nepotřebujeme pro message

logger = logging.getLogger(__name__)

def send_slack_message(webhook_url: Optional[str], message: str, fallback_text: str = "Notification from Battery Tester") -> bool:
    """
    Odešle zprávu na Slack pomocí Incoming Webhook URL.
    Používá metodu odeslání JSONu jako 'payload' parametr.

    Args:
        webhook_url: URL adresa Slack Webhooku.
        message: Text zprávy k odeslání (může obsahovat Slack Markdown).
        fallback_text: Text, který se zobrazí v notifikacích.

    Returns:
        True pokud byl požadavek úspěšně odeslán (status code 2xx), jinak False.
    """
    if not webhook_url:
        logger.error("Slack Error: Webhook URL is not configured.")
        return False
    if not message:
        logger.warning("Slack Warning: Attempting to send an empty message.")
        # Můžeme poslat i prázdnou, Slack si poradí nebo vrátí chybu
        # return False

    # --- ZMĚNA: Sestavení JSON payloadu ---
    # Můžeme přidat další pole podle potřeby (username, icon_emoji, channel)
    slack_data = {
        "text": fallback_text, # Povinné pro notifikace
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message
                }
            }
		]
        # Příklad přidání dalších polí:
        # "username": "Battery Tester Bot",
        # "icon_emoji": ":battery:",
        # "channel": "#testing-alerts" # Pro přepsání výchozího kanálu webhooku
    }
    # ------------------------------------

    try:
        # --- ZMĚNA: Odeslání jako 'payload' parametr ---
        # Převod slovníku na JSON řetězec
        payload_json_string = json.dumps(slack_data)

        # Data pro POST požadavek ve formátu application/x-www-form-urlencoded
        post_data = {'payload': payload_json_string}

        logger.info(f"Sending Slack notification via webhook (using payload parameter)...")
        logger.debug(f"Slack Webhook URL: {webhook_url}")
        logger.debug(f"Slack Payload (JSON String): {payload_json_string}")

        timeout_seconds = 15
        response = requests.post(
            webhook_url,
            data=post_data, # <-- Posíláme slovník, requests ho zakóduje jako form data
            # headers={'Content-Type': 'application/x-www-form-urlencoded'} # Requests by mělo nastavit samo pro data=dict
            timeout=timeout_seconds
        )
        # -------------------------------------------

        # Kontrola stavového kódu a textu odpovědi
        if response.status_code == 200 and response.text.lower() == "ok":
            logger.info("Slack notification request sent successfully.")
            return True
        else:
            # Logování detailnější chyby
            error_detail = f"Status: {response.status_code}, Response: '{response.text[:500]}...'"
            logger.error(f"Slack request failed. {error_detail}")
            # Speciální kontrola pro časté chyby Slacku
            if response.status_code == 400 and "invalid_payload" in response.text:
                 logger.error("Slack Error Detail: The JSON payload structure might be incorrect.")
            elif response.status_code == 403:
                 logger.error("Slack Error Detail: Forbidden - Check webhook URL validity or permissions.")
            elif response.status_code == 404:
                 logger.error("Slack Error Detail: Not Found - The webhook URL might be incorrect or deactivated.")
            return False

    except requests.exceptions.RequestException as e:
        logger.error(f"Slack request failed (RequestException): {e}")
        return False
    except Exception as e:
        logger.exception(f"An unexpected error occurred during Slack notification: {e}")
        return False

# ... (if __name__ == '__main__' blok zůstává pro testování) ...
if __name__ == '__main__':
    print("Testing Slack notification module (sends as payload parameter)...")
    test_webhook_url = "YOUR_SLACK_WEBHOOK_URL" # <-- NAHRAĎ SKUTEČNOU URL
    test_msg = "Test z Pythonu :wave: (posláno jako payload parametr).\n*Formátování* by mělo _fungovat_."
    fallback = "Test from Python (payload)"

    if "YOUR_SLACK_WEBHOOK_URL" == test_webhook_url or not test_webhook_url:
        print("\nPlease replace YOUR_SLACK_WEBHOOK_URL with your actual Slack Webhook URL.")
    else:
        print(f"Sending test message via webhook...")
        success = send_slack_message(test_webhook_url, test_msg, fallback_text=fallback)
        if success:
            print("\nTest request sent successfully (check your Slack channel).")
        else:
            print("\nTest request failed.")
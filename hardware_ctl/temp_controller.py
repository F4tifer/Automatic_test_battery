# hardware_ctl/temp_controller.py

import time
import logging
import threading
from typing import TYPE_CHECKING, Optional

# Import funkce pro Slack - s ošetřením, pokud modul neexistuje
try:
    from notifications import send_slack_message # <-- Změna zde
    notification_module_available = True
except ImportError:
     logging.warning("Could not import 'notifications' module. Slack/other notifications disabled.")
     notification_module_available = False
     # Dummy funkce
     def send_slack_message(url, msg, *args, **kwargs) -> bool: # <-- Změna zde
         logger = logging.getLogger(__name__)
         logger.error("Attempted to send Slack message, but 'notifications' module is missing.")
         return False

# ... (TYPE_CHECKING import RelayController) ...

class TempController:
    # ... (__init__ - načítá novou sekci [notifications]) ...
    def __init__(self, temp_config: dict,
                 relay_controller: 'RelayController | None',
                 notifications_config: dict):
        self.enabled = temp_config.get('enabled', False)
        # ... (ostatní inicializace - stabilization_timeout, current_temp, relay_ctl, beeper_pin) ...
        self.relay_ctl = relay_controller
        self.beeper_pin = getattr(relay_controller, 'beeper_pin', None) if relay_controller else None

        # --- Zpracování notifikační konfigurace ---
        self.notification_mode = notifications_config.get('manual_temp_mode', 'beeper').lower().strip()
        # Odstraněny WhatsApp proměnné, přidána Slack URL
        self.slack_webhook_url = notifications_config.get('slack_webhook_url')

        # Vyhodnocení dostupnosti
        self.can_use_beeper = self.relay_ctl is not None and self.beeper_pin is not None
        self.can_use_slack = notification_module_available and self.slack_webhook_url # <-- Změna zde

        # ... (logování stavu notifikací v __init__) ...
        log_suffix = "(Manual Mode)" if not self.enabled else "(Automatic Mode)"
        logging.info(f"Temperature Chamber Controller Initialized {log_suffix}.")
        if not self.enabled:
             logging.info(f"Manual Temp Notification Mode selected: '{self.notification_mode}'")
             valid_modes = ["beeper", "slack", "both", "none"] # <-- Změna zde
             if self.notification_mode not in valid_modes:
                 logging.warning(f"Invalid notification_mode '{self.notification_mode}'. Valid options: {valid_modes}. Defaulting to 'none'.")
                 self.notification_mode = "none"

             if "beeper" in self.notification_mode or "both" in self.notification_mode:
                 if not self.can_use_beeper: logging.warning("Beeper notification selected but unavailable.")
                 else: logging.info("Beeper notification is configured and available.")
             if "slack" in self.notification_mode or "both" in self.notification_mode: # <-- Změna zde
                 if not self.can_use_slack: logging.warning("Slack notification selected but webhook URL not configured or module unavailable.") # <-- Změna zde
                 else: logging.info("Slack notification is configured and available.")
             if self.notification_mode == "none": logging.info("Manual notifications are disabled ('none').")


    # ... (metoda set_temperature zůstává stejná) ...
    def set_temperature(self, target_temp_c: float) -> bool:
        # ... (kód beze změny) ...
        if not self.enabled:
            logging.info(f"--- MANUAL MODE: Target temperature set to {target_temp_c:.1f}°C ---")
            self.current_temp = target_temp_c
            return True
        else:
            logging.info(f"Setting temperature chamber to {target_temp_c}°C...")
            time.sleep(0.5) # Simulace
            return True

    # ... (metoda _beeper_thread_func zůstává stejná) ...
    def _beeper_thread_func(self, stop_event: threading.Event, interval_s: float = 2.0, beep_duration_ms: int = 80):
        # ... (kód beze změny) ...
        if not self.can_use_beeper or self.relay_ctl is None: return
        logging.debug(f"Beeper thread started (Pin {self.beeper_pin}, Interval {interval_s}s).")
        is_beeping = False
        try:
            while not stop_event.is_set():
                if self.relay_ctl._set_relay(self.beeper_pin):
                    is_beeping = True
                    beep_duration_s = beep_duration_ms / 1000.0
                    if stop_event.wait(timeout=beep_duration_s): break
                    self.relay_ctl._clear_relay(self.beeper_pin)
                    is_beeping = False
                    pause_duration_s = interval_s - beep_duration_s
                    if pause_duration_s > 0:
                        if stop_event.wait(timeout=pause_duration_s): break
                else:
                    logging.warning(f"Failed to turn beeper pin {self.beeper_pin} ON, retrying after {interval_s}s...")
                    if stop_event.wait(timeout=interval_s): break
        except Exception as e: logging.error(f"Error in beeper thread: {e}")
        finally:
             if is_beeping and self.can_use_beeper and self.relay_ctl:
                 logging.debug("Ensuring beeper pin is off at thread exit.")
                 try: self.relay_ctl._clear_relay(self.beeper_pin)
                 except Exception: logging.error("Failed to ensure beeper pin is off at thread exit.")
             logging.debug("Beeper thread stopped.")


    def wait_for_stabilization(self, target_temp_c: float, tolerance: float = 1.0):
        """Čeká na stabilizaci teploty (v manuálním režimu čeká na uživatele)."""
        if not self.enabled:
            # --- Manuální režim ---
            print("\n" + "=" * 60)
            print(f"--> MANUAL ACTION REQUIRED <---")
            print(f"    1. Manually set the temperature chamber to {target_temp_c:.1f}°C.")
            print(f"    2. Wait until the temperature is stable.")
            print(f"    3. Press Enter here to continue the test.")
            print("=" * 60)

            beeper_thread: Optional[threading.Thread] = None
            stop_event = threading.Event()
            notification_active = False

            # Rozhodnutí o notifikačních metodách
            use_beeper = ("beeper" in self.notification_mode or "both" in self.notification_mode) and self.can_use_beeper
            use_slack = ("slack" in self.notification_mode or "both" in self.notification_mode) and self.can_use_slack # <-- Změna zde

            # Odeslání Slack zprávy (jednorázově)
            if use_slack: # <-- Změna zde
                logging.info("Sending Slack notification for manual action...")
                # Použití Slack Markdownu: https://api.slack.com/reference/surfaces/formatting
                message = f":warning: *MANUAL ACTION NEEDED* :warning:\nSet temperature to `{target_temp_c:.1f} C` and press *Enter* in the script console when stable."
                fallback = f"Manual Action: Set temp to {target_temp_c:.1f} C and press Enter."
                # Volání nové funkce
                if send_slack_message(self.slack_webhook_url, message, fallback_text=fallback): # <-- Změna zde
                     notification_active = True
                     logging.info("Slack notification request sent.")
                else:
                     logging.error("Failed to send Slack notification request.")
                     # Fallback na beeper?
                     # if not use_beeper and self.can_use_beeper: use_beeper = True

            # Spuštění pípání (pokud je zvoleno a dostupné)
            if use_beeper:
                if self.can_use_beeper:
                    logging.info("Starting audible alert (beep every 2s) while waiting for user...")
                    beeper_thread = threading.Thread(target=self._beeper_thread_func, args=(stop_event,))
                    beeper_thread.daemon = True
                    beeper_thread.start()
                    notification_active = True
                else:
                     logging.warning("Cannot start beeper: beeper pin/relay not configured/available.")
            elif "beeper" in self.notification_mode:
                 logging.warning("Beeper alert selected but unavailable.")


            if not notification_active:
                 logging.info("No notification method active. Waiting silently for user confirmation...")

            # ... (zbytek metody - čekání na input, ukončení pípání - beze změny) ...
            user_input = ""
            try:
                prompt = f"--> Press Enter to confirm temperature is stable at {target_temp_c:.1f}°C: "
                user_input = input(prompt)
            except KeyboardInterrupt:
                 logging.warning("Wait for confirmation interrupted by user.")
                 if beeper_thread and beeper_thread.is_alive(): stop_event.set()
                 raise
            finally:
                if beeper_thread and beeper_thread.is_alive():
                    logging.info("Stopping audible alert...")
                    stop_event.set()
                    beeper_thread.join(timeout=3)
                    if beeper_thread.is_alive(): logging.warning("Beeper thread did not stop gracefully.")
                elif beeper_thread:
                     logging.debug("Beeper thread already finished before confirmation.")

            print("-" * 60)
            logging.info("Continuing test based on manual confirmation.")
            self.current_temp = target_temp_c
            return True
            # --- Konec manuálního režimu ---
        else:
            # --- Automatický režim (zůstává stejný) ---
            # ... (kód pro automatické čekání) ...
            logging.info(f"Waiting for temperature to stabilize at {target_temp_c}°C (Timeout: {self.stabilization_timeout}s)...")
            start_time = time.time()
            last_log_time = 0
            while time.time() - start_time < self.stabilization_timeout:
                current_temp = self.get_current_temperature()
                current_time_check = time.time()
                if current_temp is None:
                    logging.warning("Could not read current temperature. Check chamber connection.")
                    time.sleep(10)
                    continue
                if current_time_check - last_log_time > 15:
                     logging.info(f"  Current temperature: {current_temp:.1f}°C (Target: {target_temp_c}°C)")
                     last_log_time = current_time_check
                if abs(current_temp - target_temp_c) <= tolerance:
                    logging.info("Temperature stabilized within tolerance.")
                    stable_confirm_time = time.time() + 10
                    is_stable = True
                    logging.info("  Confirming stability for 10s...")
                    while time.time() < stable_confirm_time:
                         confirm_temp = self.get_current_temperature()
                         if confirm_temp is None or abs(confirm_temp - target_temp_c) > tolerance:
                              logging.warning("  Temperature drifted out of tolerance during confirmation. Continuing wait.")
                              is_stable = False
                              break
                         time.sleep(1)
                    if is_stable:
                         logging.info("Temperature stability confirmed.")
                         return True
                time.sleep(5)
            logging.error(f"Temperature did not stabilize at {target_temp_c}°C within the {self.stabilization_timeout}s timeout.")
            return False

    # ... (metody get_current_temperature a close zůstávají stejné) ...
    def get_current_temperature(self) -> float | None:
         if not self.enabled: return self.current_temp
         else: return self.current_temp # Simulace
    def close(self):
         logging.debug("TempController close() called.")
         pass
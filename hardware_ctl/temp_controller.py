# hardware_ctl/temp_controller.py

import time
import logging
import threading
from typing import TYPE_CHECKING, Optional # Přidáno Optional

# Podmíněný import pro type hinting
if TYPE_CHECKING:
    from hardware_ctl.relay_controller import RelayController

# Import funkce pro WhatsApp - s ošetřením, pokud modul neexistuje
try:
    # Předpokládáme, že notifications.py je v kořenovém adresáři nebo v sys.path
    from notifications import send_whatsapp_message
    whatsapp_available = True
except ImportError:
     logging.warning("Could not import 'notifications' module. WhatsApp notifications disabled.")
     whatsapp_available = False
     # Dummy funkce pro případ, že import selže, aby zbytek kódu prošel
     def send_whatsapp_message(phone, key, msg, *args, **kwargs) -> bool:
         """Dummy function when notifications module is not found."""
         logger = logging.getLogger(__name__) # Získáme logger zde
         logger.error("Attempted to send WhatsApp message, but 'notifications' module is missing.")
         return False

class TempController:
    """
    Ovládá teplotní komoru nebo čeká na manuální nastavení uživatelem.
    V manuálním režimu může upozorňovat pomocí bzučáku nebo WhatsApp zprávy.
    """

    def __init__(self, temp_config: dict,
                 relay_controller: 'RelayController | None',
                 notifications_config: dict):
        """
        Inicializuje TempController.

        Args:
            temp_config: Slovník s konfigurací z [temperature_chamber] sekce.
            relay_controller: Instance RelayController pro ovládání bzučáku.
            notifications_config: Slovník s konfigurací z [notifications] sekce.
        """
        self.enabled = temp_config.get('enabled', False)
        self.stabilization_timeout = temp_config.get('stabilization_timeout_seconds', 1800)
        self.current_temp = 25.0 # Výchozí simulovaná teplota
        self.relay_ctl = relay_controller
        # Získáme pin bzučáku bezpečně
        self.beeper_pin = getattr(relay_controller, 'beeper_pin', None) if relay_controller else None

        # --- Zpracování notifikační konfigurace ---
        self.notification_mode = notifications_config.get('manual_temp_mode', 'beeper').lower().strip()
        self.whatsapp_phone = notifications_config.get('whatsapp_phone_number')
        self.whatsapp_apikey = notifications_config.get('whatsapp_apikey')

        # Vyhodnocení, zda lze jednotlivé metody použít
        self.can_use_beeper = self.relay_ctl is not None and self.beeper_pin is not None
        self.can_use_whatsapp = whatsapp_available and self.whatsapp_phone and self.whatsapp_apikey

        log_suffix = "(Manual Mode)" if not self.enabled else "(Automatic Mode)"
        logging.info(f"Temperature Chamber Controller Initialized {log_suffix}.")

        # Logování stavu notifikací v manuálním režimu
        if not self.enabled:
             logging.info(f"Manual Temp Notification Mode selected: '{self.notification_mode}'")
             valid_modes = ["beeper", "whatsapp", "both", "none"]
             if self.notification_mode not in valid_modes:
                 logging.warning(f"Invalid notification_mode '{self.notification_mode}'. Valid options: {valid_modes}. Defaulting to 'none'.")
                 self.notification_mode = "none"

             # Kontrola dostupnosti pro zvolené režimy
             if "beeper" in self.notification_mode or "both" in self.notification_mode:
                 if not self.can_use_beeper:
                     logging.warning("Beeper notification selected but beeper pin/relay not configured/available.")
                 else:
                      logging.info("Beeper notification is configured and available.")
             if "whatsapp" in self.notification_mode or "both" in self.notification_mode:
                 if not self.can_use_whatsapp:
                     logging.warning("WhatsApp notification selected but phone/apikey not configured or module unavailable.")
                 else:
                      logging.info("WhatsApp notification is configured and available.")
             if self.notification_mode == "none":
                  logging.info("Manual notifications are disabled ('none').")

        # Zde by byla inicializace reálné komory, pokud self.enabled == True
        # např. self._connect_to_real_chamber(temp_config)

    def set_temperature(self, target_temp_c: float) -> bool:
        """
        Nastaví cílovou teplotu komory (v manuálním režimu jen loguje).
        """
        if not self.enabled:
            # V manuálním režimu jen zaznamenáme cíl a zalogujeme
            logging.info(f"--- MANUAL MODE: Target temperature set to {target_temp_c:.1f}°C ---")
            # Uložíme si cíl, aby ho get_current_temperature mohlo vrátit
            self.current_temp = target_temp_c
            return True
        else:
            # V automatickém režimu pošleme příkaz do komory
            logging.info(f"Setting temperature chamber to {target_temp_c}°C...")
            try:
                # ZDE: Kód pro odeslání příkazu do reálné komory
                # např. self.chamber.write(f'SETP {target_temp_c}')
                time.sleep(0.5) # Simulace komunikace
                logging.info(f"Temperature setpoint {target_temp_c}°C sent.")
                # Aktualizujeme i zde cíl pro get_current_temperature v automatu
                self.current_temp = target_temp_c
                return True
            except Exception as e:
                logging.error(f"Failed to set temperature on real chamber: {e}")
                return False

    def _beeper_thread_func(self, stop_event: threading.Event, interval_s: float = 2.0, beep_duration_ms: int = 80):
        """
        Funkce běžící ve vlákně pro opakované pípání bzučákem.
        """
        if not self.can_use_beeper or self.relay_ctl is None: # Dvojí kontrola pro type checker
            return # Nemělo by nastat, pokud je voláno správně

        logging.debug(f"Beeper thread started (Pin {self.beeper_pin}, Interval {interval_s}s).")
        is_beeping = False # Sledujeme stav pro bezpečné ukončení
        try:
            while not stop_event.is_set():
                # Zapnout bzučák
                if self.relay_ctl._set_relay(self.beeper_pin):
                    is_beeping = True
                    beep_duration_s = beep_duration_ms / 1000.0
                    # wait() je přerušitelné událostí stop_event
                    if stop_event.wait(timeout=beep_duration_s): break # Ukončit, pokud přišel signál během pípání

                    # Vypnout bzučák
                    self.relay_ctl._clear_relay(self.beeper_pin)
                    is_beeping = False

                    # Čekat zbytek intervalu
                    pause_duration_s = interval_s - beep_duration_s
                    if pause_duration_s > 0:
                        if stop_event.wait(timeout=pause_duration_s): break # Ukončit, pokud přišel signál během pauzy
                else:
                    # Selhalo zapnutí relé, zalogujeme varování a počkáme celý interval
                    logging.warning(f"Failed to turn beeper pin {self.beeper_pin} ON, retrying after {interval_s}s...")
                    if stop_event.wait(timeout=interval_s): break

        except Exception as e:
             # Zachytíme případné chyby z ovládání relé uvnitř vlákna
             logging.error(f"Error in beeper thread: {e}")
        finally:
             # Zajistit vypnutí bzučáku při jakémkoli ukončení vlákna
             if is_beeping and self.can_use_beeper and self.relay_ctl:
                 logging.debug("Ensuring beeper pin is off at thread exit.")
                 try:
                     # Poslední pokus o vypnutí
                     self.relay_ctl._clear_relay(self.beeper_pin)
                 except Exception:
                     logging.error("Failed to ensure beeper pin is off at thread exit.")
             logging.debug("Beeper thread stopped.")


    def wait_for_stabilization(self, target_temp_c: float, tolerance: float = 1.0):
        """
        Čeká na stabilizaci teploty.
        V manuálním režimu čeká na potvrzení uživatele a používá nakonfigurované notifikace.
        V automatickém režimu monitoruje teplotu z komory.
        """
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
            notification_active = False # Sledujeme, zda nějaká notifikace běží/byla poslána

            # Rozhodnutí o notifikačních metodách
            use_beeper = ("beeper" in self.notification_mode or "both" in self.notification_mode) and self.can_use_beeper
            use_whatsapp = ("whatsapp" in self.notification_mode or "both" in self.notification_mode) and self.can_use_whatsapp

            # Odeslání WhatsApp zprávy (jednorázově)
            if use_whatsapp:
                logging.info("Sending WhatsApp notification for manual action...")
                # --- ZMĚNA: Zjednodušený text zprávy bez ° a 👍 ---
                message = f"MANUAL ACTION NEEDED:\nSet temperature to *{target_temp_c:.1f} C* and press *Enter* in the script console when stable."
                # -------------------------------------------------
                logging.debug(f"DEBUG: Calling send_whatsapp_message with phone='{self.whatsapp_phone}', apikey='{self.whatsapp_apikey}'") # Ladící log
                if send_whatsapp_message(self.whatsapp_phone, self.whatsapp_apikey, message):
                     notification_active = True
                     logging.info("WhatsApp notification request sent.")
                else:
                     logging.error("Failed to send WhatsApp notification request.")
                     # Fallback na beeper, pokud WhatsApp selhal a byl jedinou volbou?
                     # if self.notification_mode == "whatsapp" and self.can_use_beeper:
                     #      logging.warning("WhatsApp failed, attempting beeper as fallback.")
                     #      use_beeper = True

            # Spuštění pípání (pokud je zvoleno a dostupné)
            if use_beeper:
                # Ověříme znovu dostupnost pro jistotu
                if self.can_use_beeper:
                    logging.info("Starting audible alert (beep every 2s) while waiting for user...")
                    beeper_thread = threading.Thread(target=self._beeper_thread_func, args=(stop_event,))
                    beeper_thread.daemon = True
                    beeper_thread.start()
                    notification_active = True
                else: # Pokud byl beeper chtěný, ale mezitím se stal nedostupným
                     logging.warning("Cannot start beeper: beeper pin/relay not configured/available.")
            elif "beeper" in self.notification_mode: # Pokud byl chtěný, ale nedostupný už od začátku
                 logging.warning("Beeper alert selected but unavailable.")


            if not notification_active:
                 logging.info("No notification method active. Waiting silently for user confirmation...")

            # Čekání na vstup od uživatele
            user_input = ""
            try:
                prompt = f"--> Press Enter to confirm temperature is stable at {target_temp_c:.1f}°C: "
                user_input = input(prompt)
            except KeyboardInterrupt:
                 logging.warning("Wait for confirmation interrupted by user.")
                 if beeper_thread and beeper_thread.is_alive(): stop_event.set() # Zastavit pípání
                 raise # Předat přerušení dál, aby se test ukončil čistě
            finally:
                # Ukončit pípání, pokud běželo
                if beeper_thread and beeper_thread.is_alive():
                    logging.info("Stopping audible alert...")
                    stop_event.set() # Signál pro vlákno, aby se ukončilo
                    beeper_thread.join(timeout=3) # Počkat na ukončení vlákna
                    if beeper_thread.is_alive():
                         logging.warning("Beeper thread did not stop gracefully.")
                elif beeper_thread: # Pokud už neběží (např. chyba ve vlákně)
                     logging.debug("Beeper thread already finished before confirmation.")

            print("-" * 60)
            logging.info("Continuing test based on manual confirmation.")
            # Aktualizujeme simulovanou teplotu na potvrzenou hodnotu
            self.current_temp = target_temp_c
            return True
            # --- Konec manuálního režimu ---
        else:
            # --- Automatický režim ---
            logging.info(f"Waiting for temperature to stabilize at {target_temp_c}°C (Timeout: {self.stabilization_timeout}s)...")
            start_time = time.time()
            last_log_time = 0
            while time.time() - start_time < self.stabilization_timeout:
                current_temp = self.get_current_temperature()
                current_time_check = time.time()

                if current_temp is None:
                    logging.warning("Could not read current temperature. Check chamber connection.")
                    time.sleep(10) # Pauza před dalším pokusem
                    continue # Pokračovat ve smyčce

                # Logovat teplotu méně často
                if current_time_check - last_log_time > 15:
                     logging.info(f"  Current temperature: {current_temp:.1f}°C (Target: {target_temp_c}°C)")
                     last_log_time = current_time_check

                # Kontrola stability
                if abs(current_temp - target_temp_c) <= tolerance:
                    logging.info("Temperature stabilized within tolerance.")
                    # Můžeme přidat ještě krátké ověření, zda drží
                    stable_confirm_time = time.time() + 10 # Ověřit po 10s
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
                         return True # Úspěšně stabilizováno

                time.sleep(5) # Interval kontroly v automatickém režimu

            # Pokud smyčka doběhla bez návratu True
            logging.error(f"Temperature did not stabilize at {target_temp_c}°C within the {self.stabilization_timeout}s timeout.")
            return False
            # --- Konec automatického režimu ---

    def get_current_temperature(self) -> float | None:
         """
         Vrací aktuální teplotu (simulovanou nebo z reálné komory).
         """
         if not self.enabled:
             # V manuálním režimu vrátí poslední nastavenou/potvrzenou hodnotu
             return self.current_temp
         else:
             # Zde by byl kód pro čtení z reálné komory
             try:
                 # temp_str = self.chamber.query('READ:TEMP?') # Příklad
                 # return float(temp_str)

                 # Simulace čtení v automatickém režimu (vrací poslední cíl)
                 # V reálu by zde bylo skutečné čtení
                 time.sleep(0.1) # Malá pauza simulující komunikaci
                 # Vracíme poslední cíl jako simulovanou teplotu pro jednoduchost
                 # Lepší simulace by postupně měnila hodnotu k cíli.
                 return self.current_temp
             except Exception as e:
                 logging.error(f"Failed to read real chamber temperature: {e}")
                 return None # Chyba při čtení

    def close(self):
         """
         Ukončí spojení s teplotní komorou, pokud bylo navázáno.
         """
         logging.debug("TempController close() called.")
         if self.enabled:
              logging.info("Closing connection to temperature chamber (if applicable)...")
              # Zde kód pro ukončení komunikace s reálnou komorou
              # např. if hasattr(self, 'chamber') and self.chamber: self.chamber.close()
         pass # Nic dalšího k čištění v této implementaci
=================================================
   Automatizovaný Tester Bateriových Cyklů
=================================================
Verze: 2.0 (Datum poslední úpravy: 2024-05-07)

Popis Projektu
---------------
Tento projekt poskytuje framework pro automatizované testování nabíjecích a vybíjecích cyklů baterií v připojeném zařízení (DUT - Device Under Test). Umožňuje provádět testy podle různých scénářů (Linear, Switching, Random) při různých teplotách, logovat detailní data o průběhu pro pozdější analýzu a poskytuje konfigurovatelnou zpětnou vazbu uživateli (bzučák, Slack).

Hlavní Funkce - Verze 2.0
-------------------------
*   **Více Testovacích Módů:**
    *   **Linear:** Standardní cyklus nabíjení/vybíjení konstantním proudem/napětím.
    *   **Switching:** Simulace rychlých změn zátěže střídáním definovaných příkazů (např. enable/disable nabíjení) v krátkých intervalech.
    *   **Random Wonder:** Simulace nepravidelného používání s náhodnou délkou fází nabíjení/vybíjení a bezpečnostními limity napětí.
*   **Konfigurovatelnost Módů:** Možnost vybrat, které testovací módy se mají spustit, a nastavit jejich specifické parametry v `test_config.toml`.
*   **Automatizovaný Scénář:** Spouští sekvenci kroků (relaxace, testovací fáze) pro každý zvolený mód, cyklus a teplotu.
*   **Teplotní Testování:** Možnost definovat seznam teplot pro testování.
*   **Ovládání Teplotní Komory:**
    *   **Manuální Režim:** Program vyzve uživatele k nastavení teploty, čeká na potvrzení Enter a během čekání upozorňuje pomocí **bzučáku** nebo **Slack zprávy** (dle konfigurace).
    *   **Automatický Režim:** Placeholder pro budoucí integraci.
*   **Ovládání Relé Desky (Deditec):** Využívá relé desku pro spínání USB napájení, HW povolení nabíjení a bzučáku. Podporuje ovládání více pinů najednou.
*   **Komunikace s DUT:** Odesílá uživatelsky definované příkazy a čte data přes sériový port.
*   **Detailní Logování:** Zaznamenává časovou řadu parametrů (`time`, `vbat`, `ibat`, `ntc_temp`, `vsys`, `die_temp`, `iba_meas_status`, `buck_status`, `mode`) do **samostatných CSV souborů** pro každou fázi testu (např. `25C_cycle1_linear_charge.csv`, `0C_cycle1_switching_main.csv`).
*   **Simulační Režim:** Možnost spustit test bez DUT pro ověření logiky scénářů a generování simulovaných dat. Simulátor nyní reaguje na různé testovací módy.
*   **Kontrola Periferií:** Ověření dostupnosti relé desky a DUT controlleru při startu.
*   **Analytické Skripty:** Nástroje (`analysis/`) pro načítání, vizualizaci a analýzu výsledných CSV dat.

Struktura Projektu
------------------
(Zde vložte ASCII stromovou strukturu - je stejná jako v předchozí odpovědi)

Struktura Projektu
------------------
/Users/***/Automatic_battery_test/ <-- Kořenový adresář projektu
│
├── .venv/ # Adresář virtuálního prostředí
│
├── hardware_ctl/ # Kód pro ovládání reálného HW
│ ├── init.py
│ ├── dut_controller.py
│ ├── relay_controller.py
│ └── temp_controller.py
│
├── libs/ # Knihovny a sdílený kód
│ ├── init.py
│ ├── backend/ # Struktura pro Deditec driver
│ │ ├── init.py
│ │ ├── common.py # Dummy soubor
│ │ └── deditec_driver/ # Kód pro Deditec relé
│ │ ├── init.py
│ │ ├── deditec_1_16_on.py
│ │ ├── helpers.py
│ │ ├── pin_cache.json # Cache stavu relé (vytvoří se)
│ │ ├── test_deditec_control.py # Skript pro testování z terminálu
│ │ └── beeper.py # (Volitelné)
│ │
│ └── prodtest_cli.py # Tvoje třída pro VCP komunikaci
│
├── simulation/ # Kód pro simulaci HW
│ ├── init.py
│ └── dummy_dut_controller.py
│
├── test_logic/ # Logika testovacího procesu
│ ├── init.py
│ ├── data_logger.py
│ └── test_steps.py
│
├── analysis/ # Skripty pro analýzu výsledků
│ ├── init.py
│ ├── data_loader.py
│ ├── analyze_charging_profile.py
│ └── fuel_gauge.py
│
├── test_results/ # Výstupní adresář pro CSV logy (vytvoří se)
│
├── main_tester.py # Hlavní spouštěcí skript testu
├── test_config.toml # Konfigurační soubor testu
├── requirements.txt # Seznam Python závislostí
├── test_run.log # Log soubor běhu testu (vytvoří se)
├── README.txt # Tento soubor
├── noticications.py # 
└── .gitignore # (Doporučeno) Pro Git



Nastavení a Instalace
---------------------
1.  **Předpoklady:** Python 3.9+.
2.  **Virtuální Prostředí:** Vytvořit (`python -m venv .venv`) a aktivovat (`source .venv/bin/activate` nebo ekvivalent).
3.  **Instalace Závislostí:** `pip install -r requirements.txt` (Nyní obsahuje `requests`).
4.  **Deditec Driver:** Struktura v `libs/backend/deditec_driver/` musí být správná, včetně `common.py` o úroveň výše.
5.  **Hardware:** Připojit relé (znát IP), DUT (znát port), komoru. Správně zapojit relé piny dle `test_config.toml`.
6.  **Slack Webhook (Volitelné):** Pokud chcete používat Slack notifikace, vytvořte si Incoming Webhook ve vaší Slack aplikaci a vložte jeho URL do `test_config.toml`.

Konfigurace (`test_config.toml`) - Verze 2.0
------------------------------------------
*   **`[general]`**: `dut_serial_port`, `output_directory`, `log_interval_seconds`, `simulate_dut` (true/false), `fail_fast` (true/false - volitelné).
*   **`[relay]`**: `ip_address`, `usb_power_relay_pins` (seznam!), `charger_enable_relay_pins` (seznam!), `beeper_pins` (seznam!).
*   **`[temperature_chamber]`**: `enabled` (true/false).
*   **`[test_plan]`**:
    *   `temperatures_celsius` (seznam).
    *   `test_modes` (seznam: "linear", "switching", "random").
    *   `cycles_per_temperature`.
    *   Parametry pro každý mód (např. `linear_discharge_voltage_limit`, `switching_phase_duration_s`, `random_duration_s`, `random_max_voltage` atd.).
    *   `relaxation_time_seconds`.
    *   `max_charge_time_hours` (pro Linear).
*   **`[notifications]`**:
    *   `manual_temp_mode` ("beeper", "slack", "both", "none").
    *   `slack_webhook_url` (URL pro Slack notifikace).
*   **`[dut_commands]`**: Přesné příkazy pro vaše DUT pro všechny potřebné akce.

Spuštění Testu
--------------
1.  Aktivujte virtuální prostředí.
2.  Pečlivě nastavte `test_config.toml`.
3.  Spusťte z **kořenového adresáře projektu**: `python main_tester.py`
4.  Sledujte konzoli a `test_run.log`.
5.  Při manuálním režimu teploty čekejte na pípání/Slack a stiskněte Enter.
6.  Výsledky se ukládají do `test_results/temp_XXC/cycle_N/XXC_cycleN_Mode_Phase.csv`.

Testování Ovládání Relé (Samostatně)
------------------------------------
(Stejné jako ve V1.0 - pomocí `python -m backend.deditec_driver.test_deditec_control ...` z adresáře `libs/`)

Analýza Dat
-----------
*   Výsledné CSV soubory jsou nyní rozděleny podle módu a fáze.
*   Použijte `analysis/analyze_charging_profile.py -f <cesta_k_souboru.csv>` pro vizualizaci jednotlivých fází.
*   `analysis/data_loader.py` a `analysis/fuel_gauge.py` jsou připraveny pro práci s daty.

Řešení Problémů
---------------
*   **`ModuleNotFoundError`:** Zkontrolujte strukturu, `__init__.py`, aktivní venv, spouštěcí adresář, `sys.path`.
*   **Deditec/Relé:** Ověřte IP, síť, firewall, `pin_cache.json`, test z terminálu.
*   **Sériový Port:** Ověřte port, práva, zda není blokován.
*   **Slack Notifikace:** Ověřte Webhook URL v configu, síťové připojení z počítače ke Slacku, případné chyby v logu z `notifications.py`.
*   **Konfigurace:** Validujte `test_config.toml`, hledejte překlepy, chybějící parametry pro zvolené módy.
*   **Chování Testu/DUT:** Projděte logy, zkontrolujte DUT příkazy, ověřte logiku v `test_steps.py` a reakce simulátoru.
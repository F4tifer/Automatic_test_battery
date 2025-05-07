=================================================
   Automatizovaný Tester Bateriových Cyklů
=================================================
Verze: 1.0 (Datum poslední úpravy: 2024-05-05)

Popis Projektu
---------------
Tento projekt poskytuje framework pro automatizované testování nabíjecích a vybíjecích cyklů baterií v připojeném zařízení (DUT - Device Under Test). Umožňuje provádět testy podle předdefinovaného scénáře při různých teplotách, logovat detailní data o průběhu pro pozdější analýzu a poskytuje zpětnou vazbu uživateli pomocí bzučáku při manuálních krocích.

Hlavní Funkce
-------------
*   **Automatizovaný Scénář:**      Spouští konfigurovatelný sled kroků (relaxace, vybíjení, nabíjení) pro každý testovací cyklus.
*   **Teplotní Testování:**         Možnost definovat seznam teplot, při kterých se mají cykly opakovat.
*   **Ovládání Teplotní Komory:**
       **Manuální Režim:**         Program vyzve uživatele k nastavení teploty, čeká na potvrzení stiskem Enter a během čekání **periodicky pípá** (pokud je bzučák nakonfigurován).
       **Automatický Režim:** Placeholder pro budoucí integraci automatického ovládání (vyžaduje implementaci v `hardware_ctl/temp_controller.py`).
*   **Ovládání Relé Desky (Deditec):** Využívá relé desku Deditec (testováno s modelem kompatibilním s driverem pro ETH-RLY16 nebo BSW-r16) pro hardwarové spínání USB napájení, povolení nabíjení DUT a ovládání bzučáku.
*   **Komunikace s DUT:** Odesílá uživatelsky definované příkazy a čte stav/data z DUT přes sériový port (VCP) pomocí `libs/prodtest_cli.py`.
*   **Detailní Logování:** Zaznamenává časovou řadu parametrů (`time`, `vbat`, `ibat`, `ntc_temp`, `vsys`, `die_temp`, `iba_meas_status`, `buck_status`, `mode`) do **jednoho CSV souboru** pro každý kompletní testovací cyklus (např. `25C_cycle1.csv`).
*   **Simulační Režim:** Možnost spustit test **bez připojeného DUT** pro ověření logiky scénáře, testování ovládání relé/bzučáku a generování simulovaných dat ve správném formátu.
*   **Kontrola Periferií:** Při startu se pokusí ověřit síťovou dostupnost relé desky (ping, TCP spojení) a inicializaci DUT/Temp controlleru.
*   **Analytické Skripty:** Obsahuje nástroje (`analysis/`) pro načítání, základní vizualizaci a pokročilejší analýzu (SoC, Rint) zaznamenaných CSV dat.

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
└── .gitignore # (Doporučeno) Pro Git


Nastavení a Instalace
---------------------
1.  **Předpoklady:** Python 3.9+, terminál, (volitelně) Git.
2.  **Virtuální Prostředí:**
    *   V kořeni projektu: `python -m venv .venv`
    *   Aktivace: `source .venv/bin/activate` (Linux/macOS) nebo `.\.venv\Scripts\activate.bat` / `.\.venv\Scripts\Activate.ps1` (Windows).
3.  **Instalace Závislostí:** V aktivním prostředí: `pip install -r requirements.txt`
4.  **Deditec Driver:** Ujistěte se, že struktura v `libs/backend/deditec_driver/` odpovídá výše uvedenému stromu a obsahuje soubory stažené/zkopírované z Trezor repozitáře. Soubor `libs/backend/common.py` je nutný (viz kód v předchozích odpovědích).
5.  **Hardware Připojení:**
    *   Relé deska: Připojit k síti, znát IP adresu.
    *   DUT: Připojit přes VCP, znát název portu.
    *   Propojení: Správně zapojit relé (USB napájení, HW enable, bzučák) k DUT a zdroji/zátěži dle konfigurace pinů v `test_config.toml`.
    *   Komora: Připojit (pokud je automatická) nebo mít připravenou k manuálnímu ovládání.

Konfigurace (`test_config.toml`)
---------------------------------
Upravte tento soubor podle vašeho setupu:

*   **`[general]`**:
    *   `dut_serial_port`: Port pro DUT (např. `/dev/ttyACM0`, `COM3`).
    *   `output_directory`: Adresář pro výsledky (např. `test_results`).
    *   `log_interval_seconds`: Frekvence zápisu dat (např. `5`).
    *   `simulate_dut`: `true` nebo `false`.

*   **`[relay]`**:
    *   `ip_address`: IP adresa Deditec desky.
    *   `usb_power_relay_pin`: Číslo (1-16) relé pro USB napájení.
    *   `charger_enable_relay_pin`: Číslo (1-16) relé pro HW enable nabíjení (nepovinné).
    *   `beeper_pin`: Číslo (1-16) relé pro bzučák (nepovinné, pro manuální čekání).

*   **`[temperature_chamber]`**:
    *   `enabled`: `true` (automat) nebo `false` (manuál s pípáním).
    *   `stabilization_timeout_seconds`: Timeout pro automatický režim.

*   **`[test_plan]`**:
    *   `temperatures_celsius`: Seznam teplot [°C] (např. `[25, 0, 45]`).
    *   `cycles_per_temperature`: Počet cyklů na teplotu (např. `2`).
    *   `discharge_voltage_limit`: Napětí [V] pro konec vybíjení (např. `3.0`).
    *   `charge_idle_current_threshold_ma`: Proud [mA] pro konec nabíjení (např. `50`).
    *   `relaxation_time_seconds`: Délka pauz [s] (např. `3600`).

*   **`[dut_commands]`**:
    *   **!!! VELMI DŮLEŽITÉ !!!** Zadejte PŘESNÉ příkazy pro komunikaci s vaším DUT pro každou akci (viz klíče v souboru). Formát musí odpovídat firmwaru DUT.

Spuštění Testu
--------------
1.  Aktivujte virtuální prostředí (`source .venv/bin/activate` nebo ekvivalent).
2.  Zkontrolujte a upravte `test_config.toml`.
3.  Spusťte hlavní skript z **kořenového adresáře projektu**:
    ```bash
    python main_tester.py
    ```
4.  Sledujte výstup v konzoli a v souboru `test_run.log`.
5.  Při manuálním režimu teploty program zapípá a počká na stisk `Enter`.
6.  Výsledné CSV soubory se ukládají do `test_results/temp_XXC/XXC_cycleN.csv`.

Testování Ovládání Relé (Samostatně)
------------------------------------
1.  Aktivujte virtuální prostředí.
2.  Přejděte do adresáře `libs/`: `cd libs`
3.  Spusťte testovací skript pomocí `-m`:
    *   Zapni relé 1 a 3: `python -m backend.deditec_driver.test_deditec_control --on 1,3`
    *   Vypni relé 2: `python -m backend.deditec_driver.test_deditec_control --off 2`
    *   Vypni všechna relé: `python -m backend.deditec_driver.test_deditec_control --all_off`
    *   Zobraz stav z cache: `python -m backend.deditec_driver.test_deditec_control --status`
    *   Použij jinou IP: `python -m backend.deditec_driver.test_deditec_control --ip <jiná_ip> --on 1`

Analýza Dat
-----------
1.  Použijte skript `analyze_charging_profile.py` pro vizualizaci:
    ```bash
    python analysis/analyze_charging_profile.py -f test_results/temp_25C/25C_cycle1.csv
    ```
    (Upravte cestu k vašemu výslednému souboru).
2.  Pro pokročilejší analýzu (kapacita, Rint, SoC) využijte funkce v `analysis/fuel_gauge.py` a data načtená pomocí `analysis/data_loader.py`.

Řešení Problémů
---------------
*   **`ModuleNotFoundError`:** Zkontrolujte strukturu, `__init__.py`, aktivní prostředí, spouštěcí adresář. Ověřte cesty v `sys.path`.
*   **Deditec Chyby:** Ověřte IP adresu, síť, firewall. Zkontrolujte `pin_cache.json` v `libs/backend/deditec_driver/`. Zkuste test z terminálu.
*   **Sériový Port:** Ověřte název portu, práva (Linux: `groups`, `sudo usermod -a -G dialout $USER`), zda není port blokován.
*   **Konfigurace:** Validujte `test_config.toml` (online validátor), hledejte překlepy, duplicity. Zkontrolujte syntaxi DUT příkazů.
*   **Simulace/DUT:** Projděte logy (`test_run.log`), debug výpisy. V simulaci upravte parametry v `dummy_dut_controller.py`. U reálného DUT ověřte příkazy a parsování v `dut_controller.py`.
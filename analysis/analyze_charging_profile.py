import argparse
import numpy as np
import copy
import matplotlib.pyplot as plt
from pathlib import Path
import logging # Přidáno logování

# Konfigurace loggeru pro tento modul
logger = logging.getLogger(__name__)
# Nastavení úrovně, pokud chceme vidět debug zprávy z data_loaderu atd.
# logging.basicConfig(level=logging.DEBUG)

# Přidání cesty k adresáři analysis, pokud není automaticky nalezena
analysis_path = Path(__file__).parent
import sys
if str(analysis_path) not in sys.path:
     sys.path.insert(0, str(analysis_path))

# Import dataloaderu
try:
    from data_loader import load_measured_data, BatteryAnalysisData
except ImportError:
     logger.critical("Could not import data_loader. Make sure it's in the same directory or sys.path is correct.")
     sys.exit(1)

# Knihovna pro CLI completion (volitelné)
try:
    import argcomplete
    argcomplete_available = True
except ImportError:
     argcomplete_available = False
     logger.debug("argcomplete library not found, skipping autocompletion setup.")


# --- Parsování argumentů ---
parser = argparse.ArgumentParser(
                    prog='analyze_charging_profile',
                    description='Analyzes and plots battery charging/discharging profiles from CSV files.')
parser.add_argument('-f', '--input_file', type=Path, # Použijeme Path pro konverzi
                    help="Path to the battery profile data file (e.g., test_results/temp_25C/25C_cycle1.csv)",
                    required=True)
parser.add_argument('--filter_len', type=int, default=10,
                     help="Length of the moving average filter window (default: 10)")
parser.add_argument('--no_filter', action='store_true',
                    help="Disable filtering of Vbat and Ibat.")

# Nastavení argcomplete, pokud je dostupné
if argcomplete_available:
    argcomplete.autocomplete(parser)
# --------------------------


# --- Funkce pro filtrování ---
def simple_moving_average(data_vector: np.ndarray, window_size: int) -> np.ndarray:
    """Vypočítá klouzavý průměr pomocí Pandas."""
    if window_size <= 1 or len(data_vector) < window_size:
        return data_vector # Nefiltrujeme, pokud je okno příliš malé nebo data krátká
    try:
        import pandas as pd
        # Odebrat NaN před filtrováním, pokud existují
        valid_data = data_vector[~np.isnan(data_vector)]
        if len(valid_data) < window_size:
             return data_vector # Stále málo platných dat

        series = pd.Series(valid_data)
        # Použijeme rolling average, center=False posouvá okno doprava (kauzální)
        windows = series.rolling(window_size, min_periods=1, center=False)
        moving_averages = windows.mean()
        # Výsledek může být kratší, doplníme zpět původní délku (např. opakováním první hodnoty)
        result = np.full_like(data_vector, np.nan) # Výchozí NaN
        result[~np.isnan(data_vector)] = moving_averages.to_numpy()
        # Jednoduché vyplnění NaN na začátku opakováním první platné hodnoty
        first_valid_idx = np.where(~np.isnan(result))[0]
        if len(first_valid_idx) > 0:
             result[:first_valid_idx[0]] = result[first_valid_idx[0]]
        return result

    except ImportError:
        logger.warning("Pandas not found, cannot apply moving average filter.")
        return data_vector # Vrací původní data, pokud pandas není dostupný
# --------------------------

def main():
    """Hlavní funkce pro načtení, zpracování a vykreslení dat."""
    args = parser.parse_args()

    input_file: Path = args.input_file
    filter_len: int = args.filter_len
    no_filter: bool = args.no_filter

    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        sys.exit(1)
    if not input_file.is_file():
         logger.error(f"Input path is not a file: {input_file}")
         sys.exit(1)

    logger.info(f"Loading data from: {input_file}")
    loaded_data = load_measured_data(input_file)

    if len(loaded_data.time) == 0:
        logger.error("No data points loaded from the file. Exiting.")
        sys.exit(1)

    # Přístup k datům
    time_ms = loaded_data.time
    vbat = loaded_data.vbat
    ibat = loaded_data.ibat
    mode = loaded_data.mode
    # Můžeme přistupovat i k dalším polím: loaded_data.ntc_temp, loaded_data.vsys atd.

    # Příprava časové osy v minutách
    time_minutes = (time_ms - time_ms[0]) / 60000.0 if len(time_ms) > 0 else np.array([])

    # Filtrování (pokud není zakázáno)
    if no_filter:
        logger.info("Filtering disabled by user.")
        vbat_filtered = vbat
        ibat_filtered = ibat
    else:
        logger.info(f"Applying moving average filter (window={filter_len})...")
        vbat_filtered = simple_moving_average(vbat, filter_len)
        ibat_filtered = simple_moving_average(ibat, filter_len)

    # --- Vykreslování ---
    logger.info("Plotting data...")
    fig, ax_vbat = plt.subplots(figsize=(12, 7)) # Větší graf

    # Osa pro napětí (Vbat)
    ln11 = ax_vbat.plot(time_minutes, vbat, label="Vbat", color="royalblue", alpha=0.5, linewidth=1)
    ln12 = ax_vbat.plot(time_minutes, vbat_filtered, label=f"Vbat Filt ({filter_len})", color="navy", linewidth=2)
    ax_vbat.set_xlabel("Time [minutes]")
    ax_vbat.set_ylabel("Vbat [V]", color="navy")
    ax_vbat.tick_params(axis='y', labelcolor='navy')
    ax_vbat.grid(True, linestyle='-', linewidth=0.5, color='lightgrey')

    # Druhá osa Y pro proud (Ibat)
    ax_ibat = ax_vbat.twinx()
    # Vykreslujeme -Ibat, aby nabíjení bylo kladné (konvence)
    ln21 = ax_ibat.plot(time_minutes, -ibat, label="Ibat", color="darkorange", alpha=0.5, linewidth=1)
    ln22 = ax_ibat.plot(time_minutes, -ibat_filtered, label=f"Ibat Filt ({filter_len})", color="red", linewidth=2)
    ax_ibat.set_ylabel("Ibat [mA] (-ve = charging)", color="red") # Popisek osy
    ax_ibat.tick_params(axis='y', labelcolor='red')
    # Můžeme nastavit limit osy Y pro proud, např. od nuly, pokud víme, že nebude záporný (po převrácení)
    # ax_ibat.set_ylim(bottom=min(0, ax_ibat.get_ylim()[0])) # Zajistí, že 0 je vidět

    # Přidání legendy
    lines = ln11 + ln12 + ln21 + ln22
    labels = [l.get_label() for l in lines]
    # Umístění legendy mimo graf pro přehlednost
    ax_vbat.legend(lines, labels, loc='upper center', bbox_to_anchor=(0.5, -0.1), fancybox=True, shadow=True, ncol=4)

    # Vykreslení oblastí režimů
    fill_y_min, fill_y_max = ax_vbat.get_ylim() # Získáme limity z osy napětí
    ax_vbat.fill_between(time_minutes, fill_y_max, fill_y_min, where=(mode == "CHARGING"), facecolor="lightgreen", alpha=0.3, label='Charging Mode Region')
    ax_vbat.fill_between(time_minutes, fill_y_max, fill_y_min, where=(mode == "DISCHARGING"), facecolor="lightcoral", alpha=0.3, label='Discharging Mode Region')
    ax_vbat.fill_between(time_minutes, fill_y_max, fill_y_min, where=(mode == "IDLE"), facecolor="lightblue", alpha=0.3, label='Idle Mode Region')
    # Poznámka: Legenda pro fill_between se standardně nezobrazuje, přidali bychom ji složitěji.

    # Titulek grafu
    ax_vbat.set_title(f"Battery Profile Analysis: {input_file.name}", fontsize=14)

    fig.tight_layout(rect=[0, 0.05, 1, 1]) # Upraví layout, [left, bottom, right, top] -> nechá místo pro legendu dole
    plt.show()
    logger.info("Plot displayed.")

if __name__ == "__main__":
    # Nastavení základního logování pro tento skript
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    main()
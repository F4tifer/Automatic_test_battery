import pandas as pd
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field # Přidán field pro default factory
import logging # Přidáno logování
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

logger = logging.getLogger(__name__)

@dataclass
class BatteryAnalysisData:
    # Upraveno pro lepší default hodnoty a typování
    time: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    vbat: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    ibat: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    ntc_temp: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    vsys: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    die_temp: np.ndarray = field(default_factory=lambda: np.array([], dtype=float)) # Přidáno chybějící pole
    iba_meas_status: np.ndarray = field(default_factory=lambda: np.array([], dtype=object))
    buck_status: np.ndarray = field(default_factory=lambda: np.array([], dtype=object))
    mode: np.ndarray = field(default_factory=lambda: np.array([], dtype=object))
    # Přidáme název souboru pro referenci
    filename: Path | None = None

def load_measured_data(data_file_path: Path) -> BatteryAnalysisData:
    """Načte data z CSV souboru do dataclass struktury."""
    logger.info(f"Loading measured data from: {data_file_path}")
    if not data_file_path.exists():
         logger.error(f"Data file not found: {data_file_path}")
         return BatteryAnalysisData(filename=data_file_path) # Vrátí prázdnou strukturu

    try:
        # Načtení pomocí pandas, lépe zvládá různé formáty a chybějící hodnoty
        profile_data = pd.read_csv(data_file_path)

        # Očekávané sloupce podle formátu logu
        expected_columns = ['time', 'vbat', 'ibat', 'ntc_temp', 'vsys',
                            'die_temp', 'iba_meas_status', 'buck_status', 'mode']

        # Zkontrolovat, zda všechny sloupce existují
        missing_cols = [col for col in expected_columns if col not in profile_data.columns]
        if missing_cols:
            logger.warning(f"Missing columns in {data_file_path}: {missing_cols}. Returning partial data.")

        # Funkce pro bezpečné načtení sloupce do numpy pole
        def get_col_as_numpy(df, col_name, dtype=object):
            if col_name in df:
                # Zkusíme převést na číselný typ, pokud je to možné, s chybami='coerce'
                if dtype in (float, int, np.float64, np.int64):
                    series = pd.to_numeric(df[col_name], errors='coerce')
                    # Nahradit NaN vhodnou hodnotou (např. 0 nebo np.nan)
                    return series.fillna(np.nan).to_numpy(dtype=float) # Vždy jako float pro NaN
                else:
                    # Pro stringové/object sloupce
                    return df[col_name].fillna('').astype(str).to_numpy(dtype=object)
            else:
                 # Pokud sloupec chybí, vrátíme prázdné pole správného typu
                 logger.debug(f"Column '{col_name}' not found, returning empty array.")
                 if dtype in (float, int, np.float64, np.int64):
                      return np.array([], dtype=float)
                 else:
                      return np.array([], dtype=object)

        # Načtení jednotlivých vektorů
        time_vector = get_col_as_numpy(profile_data, "time", dtype=int) # Čas by měl být int
        vbat_vector = get_col_as_numpy(profile_data, "vbat", dtype=float)
        ibat_vector = get_col_as_numpy(profile_data, "ibat", dtype=float)
        ntc_temp_vector = get_col_as_numpy(profile_data, "ntc_temp", dtype=float)
        vsys_vector = get_col_as_numpy(profile_data, "vsys", dtype=float)
        die_temp_vector = get_col_as_numpy(profile_data, "die_temp", dtype=float) # Načtení die_temp
        iba_meas_status_vector = get_col_as_numpy(profile_data, "iba_meas_status", dtype=object) # Jako string/object
        buck_status_vector = get_col_as_numpy(profile_data, "buck_status", dtype=object) # Jako string/object
        mode_vector = get_col_as_numpy(profile_data, "mode", dtype=object) # Jako string/object

        logger.info(f"Successfully loaded {len(time_vector)} data points.")
        return BatteryAnalysisData(
            time=time_vector,
            vbat=vbat_vector,
            ibat=ibat_vector,
            ntc_temp=ntc_temp_vector,
            vsys=vsys_vector,
            die_temp=die_temp_vector, # Předání die_temp
            iba_meas_status=iba_meas_status_vector, # Oprava překlepu
            buck_status=buck_status_vector,
            mode=mode_vector,
            filename=data_file_path
        )

    except pd.errors.EmptyDataError:
         logger.error(f"Data file {data_file_path} is empty.")
         return BatteryAnalysisData(filename=data_file_path)
    except Exception as e:
        logger.exception(f"Error loading or processing data file {data_file_path}: {e}")
        return BatteryAnalysisData(filename=data_file_path) # Vrátí prázdnou strukturu


def cut_discharge_profile_data(data: BatteryAnalysisData) -> BatteryAnalysisData:
    """Vybere pouze data z fáze vybíjení ('DISCHARGING')."""
    if len(data.mode) == 0:
        logger.warning("Cannot cut discharge data: input data is empty.")
        return BatteryAnalysisData(filename=data.filename) # Vrátit prázdnou

    logger.debug(f"Cutting discharge profile data (total points: {len(data.time)}).")
    try:
        discharge_indices = np.where(data.mode == "DISCHARGING")[0] # Získat indexy
    except Exception as e:
         logger.error(f"Error finding discharge indices: {e}")
         return BatteryAnalysisData(filename=data.filename)

    if len(discharge_indices) == 0:
        logger.warning("No 'DISCHARGING' data found in the provided profile.")
        return BatteryAnalysisData(filename=data.filename)

    logger.info(f"Found {len(discharge_indices)} discharge data points.")

    # Vytvoření nové instance s vybranými daty
    discharge_data = BatteryAnalysisData(
        time=data.time[discharge_indices],
        vbat=data.vbat[discharge_indices],
        ibat=data.ibat[discharge_indices],
        ntc_temp=data.ntc_temp[discharge_indices],
        vsys=data.vsys[discharge_indices],
        die_temp=data.die_temp[discharge_indices], # Přidáno
        iba_meas_status=data.iba_meas_status[discharge_indices],
        buck_status=data.buck_status[discharge_indices],
        mode=data.mode[discharge_indices], # Bude obsahovat jen "DISCHARGING"
        filename=data.filename # Zachováme jméno původního souboru
    )

    # Offset časového vektoru, aby začínal na 0 pro tento úsek
    if len(discharge_data.time) > 0:
         logger.debug("Offsetting time vector for discharge profile.")
         discharge_data.time = discharge_data.time - discharge_data.time[0]

    return discharge_data

def get_complementary_color(color: str) -> str:
    """Vrátí komplementární barvu k dané barvě."""
    try:
        rgb = mcolors.to_rgb(color)
        # Jednoduchý výpočet komplementární barvy
        comp_rgb = tuple(1.0 - val for val in rgb)
        return mcolors.to_hex(comp_rgb)
    except ValueError:
        logger.warning(f"Invalid color '{color}' for complementary calculation, returning black.")
        return "#000000" # Fallback barva

def print_profile(ax: plt.Axes, ax_secondary: plt.Axes, data: BatteryAnalysisData, label: str, color: str):
    """Vykreslí vbat a ibat do poskytnutých os."""
    if len(data.time) == 0:
        logger.warning(f"Cannot print profile for '{label}': no data.")
        return

    logger.debug(f"Plotting profile for '{label}' with color {color}")
    # Vykreslení napětí
    ln_v = ax.plot(data.time, data.vbat, label=f"{label} vbat", color=color)
    # Vykreslení proudu (předpokládáme, že čas je v ms, převod na minuty zde?)
    # Prozatím necháme čas, jak je načtený
    time_axis = data.time / 60000 # Převedeme na minuty pro konzistenci s analyze_...
    ln_i = ax_secondary.plot(time_axis, data.ibat, label=f"{label} ibat", color=get_complementary_color(color))

    # Vrátíme linie pro případné použití v legendě
    return ln_v, ln_i
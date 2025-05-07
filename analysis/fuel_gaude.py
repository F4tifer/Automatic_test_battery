import copy
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit
import logging

# Import datové struktury (pro type hinting)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
     from data_loader import BatteryAnalysisData

logger = logging.getLogger(__name__)

def poly(x, a, b, c, d, e):
    """Polynom 4. řádu."""
    return a*x**4 + b*x**3 + c*x**2 + d*x + e

def columb_counter(time_ms: np.ndarray, ibat_ma: np.ndarray) -> float:
    """
    Vypočítá celkovou kapacitu (mAh) pomocí Coulombova počítání.
    Očekává čas v milisekundách a proud v miliampérech.
    """
    if len(time_ms) != len(ibat_ma) or len(time_ms) < 2:
        logger.warning("Coulomb counter requires at least 2 data points with equal length time and current vectors.")
        return 0.0

    # Převod času na sekundy pro výpočet mAs
    time_s = time_ms / 1000.0
    curr_acc_mAs = 0.0 # Akumulátor v miliampérsekundách

    # Použití numpy pro vektorizaci výpočtu (efektivnější)
    delta_time_s = np.diff(time_s) # Rozdíly časů mezi sousedními body
    avg_current_ma = (ibat_ma[:-1] + ibat_ma[1:]) / 2.0 # Průměrný proud mezi body

    curr_acc_mAs = np.sum(avg_current_ma * delta_time_s)

    # Převod z mAs na mAh (děleno 3600)
    total_mah = curr_acc_mAs / 3600.0
    # Absolutní hodnota, protože nás zajímá celková proteklá kapacita
    logger.info(f"Coulomb counter calculated capacity: {abs(total_mah):.3f} mAh")
    return abs(total_mah)


def cut_stabilezed_data(time, ibat, vbat):
    """Placeholder pro budoucí funkci."""
    logger.warning("Function 'cut_stabilezed_data' is not implemented.")
    pass

def estimate_R_int(time_ms: np.ndarray, ibat_ma: np.ndarray, vbat_v: np.ndarray, temp_c: np.ndarray) -> float | None:
    """
    Odhadne vnitřní odpor baterie z profilu s pulzní zátěží.
    Očekává čas v ms, proud v mA, napětí v V, teplotu v °C.
    """
    logger.info("Estimating internal resistance (R_int)...")
    if not (len(time_ms) == len(ibat_ma) == len(vbat_v) == len(temp_c)) or len(time_ms) < 40: # Potřebujeme dost bodů
        logger.error("Insufficient or inconsistent data for R_int estimation.")
        return None

    # Převod času na sekundy pro grafy
    time_s = time_ms / 1000.0

    # Parametry detekce pulzů
    fir_len = 20       # Délka filtru pro vyhlazení proudu/napětí
    delta_threshold = 30 # Minimální rozdíl [mA] mezi filtrovaným a syrovým proudem pro detekci hrany
    offset_left = 10   # Kolik bodů před hranou vzít první vzorek (M1)
    offset_right = 10  # Kolik bodů za hranou vzít druhý vzorek (M2)
    debounce_len = fir_len # Počet bodů ignorovaných po detekci hrany

    # Filtrované signály
    try:
        import pandas as pd
        ibat_series = pd.Series(ibat_ma)
        vbat_series = pd.Series(vbat_v)
        # Použijeme centrovaný průměr pro menší fázové zkreslení při detekci
        ibat_filtered = ibat_series.rolling(window=fir_len, center=True, min_periods=1).mean().to_numpy()
        vbat_filtered = vbat_series.rolling(window=fir_len, center=True, min_periods=1).mean().to_numpy()
    except ImportError:
         logger.warning("Pandas not found, R_int filtering might be less accurate.")
         # Jednoduchý fallback (necentrovaný)
         ibat_filtered = np.convolve(ibat_ma, np.ones(fir_len)/fir_len, mode='same')
         vbat_filtered = np.convolve(vbat_v, np.ones(fir_len)/fir_len, mode='same')

    transitions_idx = []
    debounce_counter = 0

    # Detekce hran (přechodů proudu)
    logger.debug("Detecting current transitions...")
    for i in range(len(ibat_ma)):
        if debounce_counter > 0:
            debounce_counter -= 1
            continue

        delta = abs(ibat_filtered[i] - ibat_ma[i])
        # Detekce: dostatečně velká odchylka a nejsme příliš blízko okrajům pro offsety
        if delta > delta_threshold and i >= offset_left and i < len(ibat_ma) - offset_right:
            transitions_idx.append(i)
            debounce_counter = debounce_len # Aktivovat debounce
            logger.debug(f"  Transition detected at index {i} (time {time_s[i]:.2f}s)")

    if len(transitions_idx) < 4: # Potřebujeme alespoň pár hran pro smysluplný průměr
        logger.error(f"Not enough current transitions detected ({len(transitions_idx)}) for R_int estimation. Try adjusting delta_threshold?")
        return None

    logger.info(f"Found {len(transitions_idx)} potential transitions for R_int calculation.")
    transitions_idx_np = np.array(transitions_idx)
    m1_idx = transitions_idx_np - offset_left # Indexy bodů před hranou
    m2_idx = transitions_idx_np + offset_right # Indexy bodů za hranou

    # Výpočet R_int pro každou hranu
    R_est_list = []
    R_est_filtered_list = []
    for i in range(len(transitions_idx)):
        # Výpočet R = dV / dI
        # Pozor na dělení nulou, pokud by proud byl stejný (nemělo by nastat)
        delta_I_raw = (ibat_ma[m1_idx[i]] - ibat_ma[m2_idx[i]]) / 1000.0 # Proud v A
        delta_V_raw = vbat_v[m1_idx[i]] - vbat_v[m2_idx[i]]
        delta_I_filt = (ibat_filtered[m1_idx[i]] - ibat_filtered[m2_idx[i]]) / 1000.0
        delta_V_filt = vbat_filtered[m1_idx[i]] - vbat_filtered[m2_idx[i]]

        # Výpočet Rint (použijeme indexaci m1 a m2 konzistentně)
        # R = (V_before - V_after) / (I_after - I_before) - znaménko proudu je důležité!
        # Nebo R = dV / (-dI) = (V_m1 - V_m2) / (I_m2 - I_m1) * 1000
        # Zkusme verzi R = |dV/dI|
        if abs(delta_I_raw) > 1e-3: # Zabráníme dělení nulou (proud pod 1mA)
             r_raw = abs(delta_V_raw / delta_I_raw)
             R_est_list.append(r_raw)
        else:
             logger.warning(f"Skipping R_int calculation at transition {i}: delta_I_raw is too small ({delta_I_raw*1000:.1f} mA).")

        if abs(delta_I_filt) > 1e-3:
             r_filt = abs(delta_V_filt / delta_I_filt)
             R_est_filtered_list.append(r_filt)
        else:
             logger.warning(f"Skipping R_int (filtered) calculation at transition {i}: delta_I_filt is too small ({delta_I_filt*1000:.1f} mA).")


    if not R_est_list or not R_est_filtered_list:
         logger.error("No valid R_int estimates could be calculated.")
         return None

    R_est_np = np.array(R_est_list)
    R_est_filtered_np = np.array(R_est_filtered_list)

    # Průměrování - vyloučíme okrajové hodnoty (např. první a poslední 2)
    num_estimates = len(R_est_np)
    if num_estimates > 4:
        R_est_final = np.mean(R_est_np[2:-2])
        R_est_final_filtered = np.mean(R_est_filtered_np[2:-2])
        logger.info(f"Averaged R_int (excluding edges): Raw={R_est_final:.4f} Ohm, Filtered={R_est_final_filtered:.4f} Ohm")
    else:
        R_est_final = np.mean(R_est_np)
        R_est_final_filtered = np.mean(R_est_filtered_np)
        logger.warning("Too few estimates for edge exclusion, averaging all.")
        logger.info(f"Averaged R_int (all): Raw={R_est_final:.4f} Ohm, Filtered={R_est_final_filtered:.4f} Ohm")


    # --- Vykreslení diagnostických grafů ---
    try:
        fig_r, ax_r = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
        ax_r[0].plot(time_s, ibat_ma, label="Ibat (mA)", alpha=0.7)
        ax_r[0].plot(time_s, ibat_filtered, label=f"Ibat Filtered ({fir_len})", linestyle='--')
        # Vyznačení bodů použitých pro výpočet
        ax_r[0].plot(time_s[m1_idx], ibat_ma[m1_idx], 'go', markersize=5, label="M1 points")
        ax_r[0].plot(time_s[m2_idx], ibat_ma[m2_idx], 'bo', markersize=5, label="M2 points")
        ax_r[0].set_ylabel("Current [mA]")
        ax_r[0].set_title("Current Profile and Measurement Points")
        ax_r[0].legend()
        ax_r[0].grid(True)

        ax_r[1].plot(time_s[transitions_idx_np], R_est_np * 1000, 'o-', label="R_int Estimate (Raw)", markersize=4) # v mOhm
        ax_r[1].plot(time_s[transitions_idx_np], R_est_filtered_np * 1000, 's--', label="R_int Estimate (Filtered)", markersize=4) # v mOhm
        ax_r[1].axhline(y=R_est_final * 1000, color='green', linestyle=':', label=f"Avg (Raw): {R_est_final*1000:.1f} mOhm")
        ax_r[1].axhline(y=R_est_final_filtered * 1000, color='purple', linestyle=':', label=f"Avg (Filt): {R_est_final_filtered*1000:.1f} mOhm")
        ax_r[1].set_xlabel("Time [s]")
        ax_r[1].set_ylabel("Estimated R_int [mOhm]")
        ax_r[1].set_title("Internal Resistance Estimation per Transition")
        ax_r[1].legend()
        ax_r[1].grid(True)
        fig_r.suptitle("R_int Estimation Analysis", fontsize=14)
        fig_r.tight_layout(rect=[0, 0, 1, 0.96]) # Místo pro hlavní titulek

        # Graf OCV
        # Použijeme finální filtrovaný odhad R_int
        R_final = R_est_final_filtered
        Vocv_raw = vbat_v + (ibat_ma / 1000.0) * R_final # Pozor na znaménko proudu! Ibat je záporný při nabíjení. Vzorec je V_ocv = V_term - I*R => V_ocv = V_term + (-I)*R
        Vocv_filtered = vbat_filtered + (ibat_filtered / 1000.0) * R_final

        fig_ocv, ax_ocv = plt.subplots(figsize=(10, 6))
        ax_ocv.plot(time_s, vbat_v, label="Vbat (Terminal)", alpha=0.7)
        ax_ocv.plot(time_s, Vocv_raw, label=f"OCV Estimate (Raw I, R={R_final:.4f} Ohm)", linestyle='--')
        ax_ocv.plot(time_s, Vocv_filtered, label=f"OCV Estimate (Filtered I, R={R_final:.4f} Ohm)", linestyle=':')
        ax_ocv.set_xlabel("Time [s]")
        ax_ocv.set_ylabel("Voltage [V]")
        ax_ocv.set_title("Estimated Open Circuit Voltage (OCV)")
        ax_ocv.legend()
        ax_ocv.grid(True)
        fig_ocv.tight_layout()

        # Graf teploty a R_int
        fig_tr, ax_t = plt.subplots(figsize=(10, 6))
        color_temp = 'tab:green'
        ax_t.set_xlabel('Time [s]')
        ax_t.set_ylabel('Temperature [°C]', color=color_temp)
        ax_t.plot(time_s, temp_c, color=color_temp, label="NTC Temp")
        ax_t.tick_params(axis='y', labelcolor=color_temp)
        ax_t.grid(True, axis='y', linestyle=':', color=color_temp)

        ax_r2 = ax_t.twinx() # Druhá osa Y pro R_int
        color_r = 'tab:purple'
        ax_r2.set_ylabel('R_int (Filtered) [mOhm]', color=color_r)
        ax_r2.plot(time_s[transitions_idx_np], R_est_filtered_np * 1000, 'o-', color=color_r, label="R_int Estimate (Filtered)", markersize=4)
        ax_r2.tick_params(axis='y', labelcolor=color_r)

        fig_tr.suptitle('Temperature and Estimated R_int over Time')
        fig_tr.tight_layout()
        # Přidání kombinované legendy? Může být složité.

        plt.show() # Zobrazí všechny vytvořené grafy

    except Exception as plot_err:
         logger.error(f"Error during plotting R_int diagnostics: {plot_err}")

    # Vrátíme finální filtrovaný odhad
    return R_est_final_filtered

# --- Funkce pro SoC křivku (zatím bez velkých změn, jen logování a typování) ---

def extract_SOC_interpolation_points(V_OC: np.ndarray, I_OC_mA: np.ndarray, T_OC_ms: np.ndarray,
                                     measured_capacity_mAh: float, num_of_intervals: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Najde indexy v OCV datech odpovídající rovnoměrně rozloženým SoC bodům.
    """
    logger.info(f"Extracting {num_of_intervals} SOC interpolation points from OCV curve...")
    if not (len(V_OC) == len(I_OC_mA) == len(T_OC_ms)) or len(V_OC) < 2:
         logger.error("Insufficient or inconsistent data for SOC point extraction.")
         return np.array([]), np.array([])
    if measured_capacity_mAh <= 0:
         logger.error("Measured capacity must be positive for SOC point extraction.")
         return np.array([]), np.array([])

    # Cílové kapacity pro každý interval SoC (0% až 100%)
    target_soc_levels = np.linspace(0, 1, num_of_intervals) # 0.0, 0.1, ..., 1.0
    target_capacities_mAh = target_soc_levels * measured_capacity_mAh
    logger.debug(f"Target SOC levels: {target_soc_levels}")
    logger.debug(f"Target capacities (mAh): {target_capacities_mAh}")

    indices = []
    time_s = T_OC_ms / 1000.0 # Čas v sekundách

    # Procházíme od konce vybíjení (0% SoC) k začátku (100% SoC)
    current_accumulated_mAh = 0.0
    target_idx = 0 # Index v target_capacities_mAh, který hledáme

    # Přidáme první bod (konec vybíjení, 0% SoC)
    indices.append(len(I_OC_mA) - 1)
    logger.debug(f"  Found point for SoC {target_soc_levels[target_idx]:.1f} at index {indices[-1]} (capacity ~0 mAh)")
    target_idx += 1


    # Iterujeme od předposledního bodu k začátku
    for j in range(len(I_OC_mA) - 1, 0, -1):
        # Výpočet kapacity v tomto malém kroku
        delta_t_s = time_s[j] - time_s[j-1]
        avg_current_mA = (I_OC_mA[j] + I_OC_mA[j-1]) / 2.0
        delta_mAh = abs(avg_current_mA * delta_t_s / 3600.0) # Kapacita je vždy kladná
        current_accumulated_mAh += delta_mAh

        # Pokud jsme překročili další cílovou kapacitu
        if target_idx < len(target_capacities_mAh) and current_accumulated_mAh >= target_capacities_mAh[target_idx]:
            # Vybrat bližší index (j nebo j-1) k cílové kapacitě? Pro jednoduchost vezmeme j-1.
            idx = j - 1
            indices.append(idx)
            logger.debug(f"  Found point for SoC {target_soc_levels[target_idx]:.1f} at index {idx} (capacity ~{current_accumulated_mAh:.2f} mAh)")
            target_idx += 1
            if target_idx >= len(target_capacities_mAh):
                 break # Našli jsme všechny body

    # Ujistit se, že máme správný počet bodů (může chybět poslední)
    if len(indices) < num_of_intervals:
         # Pokud chybí 100% SoC bod, přidáme první index (začátek vybíjení)
         if target_idx == num_of_intervals - 1:
              indices.append(0)
              logger.debug(f"  Adding start point for SoC 1.0 at index 0")
         else:
              logger.warning(f"Could only find {len(indices)} out of {num_of_intervals} SOC points.")

    # Vrátíme indexy seřazené od 0% do 100% SoC a odpovídající úrovně SoC
    # Indexy jsou zatím seřazeny od konce k začátku, otočíme je
    final_indices = np.array(indices[::-1], dtype=int)
    final_soc = target_soc_levels[:len(final_indices)] # Vezmeme jen tolik SoC úrovní, kolik máme indexů

    logger.info(f"Found {len(final_indices)} interpolation points.")
    return final_indices, final_soc

def extract_SOC_curve(discharge_data: 'BatteryAnalysisData', Rint_ohm: float | None,
                      max_chg_voltage: float = 4.2, max_dischg_voltage: float = 3.0,
                      num_soc_points: int = 11):
    """
    Extrahuje SoC křivku (OCV vs SoC) z dat konstantního vybíjení.
    """
    logger.info("Extracting SOC curve...")
    if Rint_ohm is None:
        logger.error("Cannot extract SOC curve without a valid R_int value.")
        return None # Nebo vyvolat výjimku?

    if len(discharge_data.time) < 2:
         logger.error("Cannot extract SOC curve: discharge data is empty or too short.")
         return None

    # Převod času na s a proudu na A pro výpočty
    time_s = discharge_data.time / 1000.0
    ibat_A = discharge_data.ibat / 1000.0

    # Výpočet OCV = V_terminal - I * R_internal
    # I je zde záporný (vybíjení), takže OCV = V_term + abs(I) * R_int
    # Nebo použijeme přímo hodnotu proudu: OCV = V_term - Ibat_A * Rint_ohm
    V_oc_calculated = discharge_data.vbat - (ibat_A * Rint_ohm)
    logger.info(f"Calculated OCV profile using R_int = {Rint_ohm:.4f} Ohm.")

    # Oříznutí OCV profilu podle napěťových limitů
    # Najít indexy, kde OCV poprvé klesne pod min a naposledy překročí max
    try:
         # Hledáme od začátku první index, kde V_oc < min_v
         discharge_end_idx = np.where(V_oc_calculated < max_dischg_voltage)[0]
         idx_start = discharge_end_idx[0] if len(discharge_end_idx) > 0 else 0

         # Hledáme od konce první index, kde V_oc > max_v
         charge_end_idx = np.where(V_oc_calculated > max_chg_voltage)[0]
         idx_end = charge_end_idx[-1] if len(charge_end_idx) > 0 else len(V_oc_calculated) - 1

         # Zajistíme správné pořadí a platnost indexů
         if idx_start >= idx_end:
              logger.error(f"Invalid voltage cut-off indices: start={idx_start}, end={idx_end}. Check voltage limits or OCV calculation.")
              return None

         logger.info(f"Cutting OCV profile between indices {idx_start} (V={V_oc_calculated[idx_start]:.3f}) and {idx_end} (V={V_oc_calculated[idx_end]:.3f}).")

         # Vytvoření oříznutých datových polí
         cut_time_ms = discharge_data.time[idx_start:idx_end+1]
         cut_V_oc = V_oc_calculated[idx_start:idx_end+1]
         cut_I_oc_mA = discharge_data.ibat[idx_start:idx_end+1]

         if len(cut_time_ms) < num_soc_points: # Potřebujeme dostatek bodů pro interpolaci
              logger.error(f"Not enough data points ({len(cut_time_ms)}) remain after voltage cut-off for {num_soc_points} SOC points.")
              return None

    except IndexError as e:
         logger.error(f"Error finding voltage cut-off indices: {e}")
         return None

    # Výpočet kapacity v oříznutém úseku
    cut_capacity_mAh = columb_counter(cut_time_ms, cut_I_oc_mA)
    if cut_capacity_mAh <= 0:
         logger.error(f"Calculated capacity in the cut profile is zero or negative ({cut_capacity_mAh:.3f} mAh). Cannot proceed.")
         return None
    logger.info(f"Capacity within the cut OCV profile: {cut_capacity_mAh:.2f} mAh")

    # Nalezení interpolačních bodů pro SoC
    interpolation_indices, SoC_levels = extract_SOC_interpolation_points(cut_V_oc, cut_I_oc_mA, cut_time_ms, cut_capacity_mAh, num_soc_points)

    if len(interpolation_indices) != len(SoC_levels) or len(interpolation_indices) < 2:
         logger.error("Failed to extract sufficient SOC interpolation points.")
         return None

    # Získání hodnot OCV v interpolačních bodech
    V_oc_at_SoC_points = cut_V_oc[interpolation_indices]

    # Fitování polynomem (nebo jinou metodou, např. spline)
    try:
        logger.info("Fitting polynomial to OCV vs SoC points...")
        # Polynom OCV = f(SoC)
        popt, pcov = curve_fit(poly, SoC_levels, V_oc_at_SoC_points)
        logger.info(f"Polynomial fit successful. Coefficients (a-e): {popt}")
        # Vygenerování fitované křivky pro vykreslení
        SoC_fine = np.linspace(0, 1, 100) # Hladší křivka pro graf
        V_oc_fitted = poly(SoC_fine, *popt)
    except Exception as fit_err:
         logger.error(f"Failed to fit polynomial to SOC data: {fit_err}")
         popt = None
         V_oc_fitted = None
         SoC_fine = SoC_levels # Použijeme původní body pro graf

    # --- Vykreslení výsledků ---
    try:
        fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

        # Horní graf: Napětí
        axes[0].plot(time_s, discharge_data.vbat, label="Vbat (Terminal)", alpha=0.5)
        axes[0].plot(time_s, V_oc_calculated, label="OCV (Calculated)", linestyle='--')
        # Vyznačení oříznuté části
        axes[0].plot(cut_time_ms / 1000.0, cut_V_oc, label="OCV (Used for SoC)", color='red', linewidth=2)
        # Vyznačení interpolačních bodů
        axes[0].plot(cut_time_ms[interpolation_indices] / 1000.0, V_oc_at_SoC_points, 'go', markersize=6, label='SoC Interpolation Points')
        axes[0].set_ylabel("Voltage [V]")
        axes[0].legend()
        axes[0].grid(True)
        axes[0].set_title("Voltage Profiles and SoC Points")

        # Spodní graf: Proud
        axes[1].plot(time_s, discharge_data.ibat, label="Ibat (mA)")
        axes[1].plot(cut_time_ms / 1000.0, cut_I_oc_mA, label="Ibat (Used for SoC)", color='red', linewidth=2)
        axes[1].set_xlabel("Time [s]")
        axes[1].set_ylabel("Current [mA]")
        axes[1].legend()
        axes[1].grid(True)

        fig.suptitle("OCV Calculation and SoC Point Selection", fontsize=14)
        fig.tight_layout(rect=[0, 0, 1, 0.96])

        # Graf SoC křivky
        fig_soc, ax_soc = plt.subplots(figsize=(8, 6))
        ax_soc.plot(SoC_levels * 100, V_oc_at_SoC_points, 'bo-', label="OCV at SoC points", markersize=5)
        if V_oc_fitted is not None:
             ax_soc.plot(SoC_fine * 100, V_oc_fitted, 'r--', label="Polynomial Fit (4th order)")
        ax_soc.set_xlabel("State of Charge (SoC) [%]")
        ax_soc.set_ylabel("Open Circuit Voltage (OCV) [V]")
        ax_soc.set_title("Battery SoC Curve (OCV vs SoC)")
        ax_soc.legend()
        ax_soc.grid(True)
        fig_soc.tight_layout()

        plt.show()

    except Exception as plot_err:
        logger.error(f"Error during plotting SOC curve results: {plot_err}")

    # Vrátíme například parametry fitované křivky
    return popt # Nebo slovník {"soc": SoC_levels, "ocv": V_oc_at_SoC_points, "popt": popt}

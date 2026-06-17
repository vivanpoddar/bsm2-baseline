"""Synthetic BSM2 influent generator (Gernaey phenomenological model).

Generates arbitrary-length, realistic influent in the 21-component ASM1 format from the
published generic blocks — household + industry + seasonal infiltration flow, a stochastic
rain/storm engine, diurnal/weekly/seasonal pollutant loads, the exact ASM1 fractionation,
and a seasonal temperature profile. Output feeds the runner unchanged (``influent_data``).

Fidelity note: this is a faithful port of the generator's *flow, load, fractionation and
temperature* blocks using the published dimensionless profile tables (``tables.py``) and
parameters (``params.py``). The detailed sewer tanks-in-series transport and first-flush
sediment ODEs of the full Simulink model are intentionally not reproduced — they reshape
storm *transients* but do not change the long-run statistics this dataset targets. The
stabilised mean output is validated against the published BSM2 influent characteristics
(see tests/test_influent.py). Realizations differ only by the rain/noise RNG seed.
"""

from __future__ import annotations

import numpy as np

from . import tables as T
from .params import InfluentParams

# ASM1 21-vector indices.
SI, SS, XI, XS, XBH, XBA, XP, SO, SNO, SNH, SND, XND, SALK, TSS, Q, TEMP = range(16)
_YEAR = 364.0


def _as(arr) -> np.ndarray:
    return np.asarray(arr, dtype=float)


def _rain_engine(t: np.ndarray, seed: int, weather: str, p: InfluentParams) -> np.ndarray:
    """Stochastic rain flow [m3/d] over time grid ``t`` (total, before the aH split)."""
    if weather == "dry":
        return np.zeros_like(t)
    rng = np.random.RandomState(seed)
    var = p.rain_var * (4.0 if weather == "storm" else 1.0)
    hours = np.arange(0.0, t[-1] + 1.0 / 24.0, 1.0 / 24.0)
    raw = rng.normal(p.rain_mean, np.sqrt(var), len(hours))
    spike = np.clip(np.maximum(0.0, raw - p.rain_lower_limit), 0.0, 1000.0)
    # first-order (catchment) smoothing on the hourly grid
    sm = np.empty_like(spike)
    acc = 0.0
    a = p.rain_smooth_alpha
    for k in range(len(spike)):
        acc = a * acc + (1.0 - a) * spike[k]
        sm[k] = acc
    return p.q_per_mm_rain * np.interp(t, hours, sm)


def _fractionate(codsol, codpart, snh_load, tkn_load, q_total, rain_direct, p: InfluentParams):
    """Exact asm1_fractionation: loads [g/d] + flows [m3/d] -> 21-vector concentration columns."""
    n = len(q_total)
    out = np.zeros((n, 21))
    q = q_total
    # SI: soluble inert at SI_cst, diluted only by the direct (impervious) rain flow
    si_potential = p.si_cst * (q - rain_direct)
    use_full = si_potential <= codsol
    out[:, SI] = np.where(use_full, si_potential / q, codsol / q)
    out[:, SS] = np.where(use_full, (codsol - si_potential) / q, 0.0)
    out[:, XI] = p.xi_fr * codpart / q
    out[:, XS] = p.xs_fr * codpart / q
    out[:, XBH] = p.xbh_fr * codpart / q
    # XBA, XP, SO = 0
    out[:, SNH] = snh_load / q
    # SNO default 0 (no influent nitrate load)
    # asm1_fractionation.c: Norg subtracts i_XB*(XBH+XBA) and i_XP*XP only (XI excluded).
    norg = (tkn_load - snh_load) / q - p.i_xb * (out[:, XBH] + out[:, XBA]) - p.i_xp * out[:, XP]
    norg = np.maximum(norg, 0.0)
    out[:, SND] = p.snd_fr * norg
    out[:, XND] = p.xnd_fr * norg
    out[:, SALK] = p.salk
    out[:, TSS] = 0.75 * (out[:, XI] + out[:, XS] + out[:, XBH] + out[:, XBA] + out[:, XP])
    out[:, Q] = q
    return out


def _one_realization(t: np.ndarray, seed: int, weather: str, p: InfluentParams) -> np.ndarray:
    hour = np.clip(((t % 1.0) * 24.0).astype(int), 0, 23)
    wd = (np.floor(t).astype(int)) % 7
    doy = (np.floor(t).astype(int)) % int(_YEAR)
    slot6 = np.clip(((t % 1.0) * 6.0).astype(int), 0, 5)
    idx6 = wd * 6 + slot6  # 0..41 industry weekly+intraday index

    day_hs, week_hs, year_hs = _as(T.day_HS), _as(T.week_HS), _as(T.year_HS)
    week_pol, week_ind, year_ind = _as(T.week_polHS), _as(T.week_IndS), _as(T.year_IndS)

    # --- flows [m3/d] ---
    q_hh = p.q_hh_base * day_hs[hour] * week_hs[wd] * year_hs[doy]
    q_ind = p.q_ind_weekday * week_ind[idx6] * year_ind[doy]
    q_inf = p.inf_bias + p.inf_amp * np.sin(2.0 * np.pi / _YEAR * t + p.inf_phase)
    q_rain = _rain_engine(t, seed, weather, p)
    rain_direct = p.a_h * q_rain
    q_total = q_hh + q_ind + q_inf + rain_direct

    # --- pollutant loads [g/d] (household per-capita; industry kg/d -> g/d) ---
    pe = p.pe_full
    codsol = (p.codsol_g_pe * pe * _as(T.CODsol_day_HS)[hour] * week_pol[wd]
              + p.codsol_ind_kg * 1000.0 * _as(T.CODsol_week_IndS)[idx6] * year_ind[doy])
    codpart = (p.codpart_g_pe * pe * _as(T.CODpart_day_HS)[hour] * week_pol[wd]
               + p.codpart_ind_kg * 1000.0 * _as(T.CODpart_week_IndS)[idx6] * year_ind[doy])
    snh_load = (p.snh_g_pe * pe * _as(T.SNH_day_HS)[hour] * week_pol[wd]
                + p.snh_ind_kg * 1000.0 * _as(T.SNH_week_IndS)[idx6] * year_ind[doy])
    tkn_load = (p.tkn_g_pe * pe * _as(T.TKN_day_HS)[hour] * week_pol[wd]
                + p.tkn_ind_kg * 1000.0 * _as(T.TKN_week_IndS)[idx6] * year_ind[doy])

    block = _fractionate(codsol, codpart, snh_load, tkn_load, q_total, rain_direct, p)
    block[:, TEMP] = (p.t_bias + p.t_amp * np.sin(2.0 * np.pi / _YEAR * t + p.t_phase)
                      + p.t_d_amp * np.sin(2.0 * np.pi * t + p.t_d_phase))
    return np.column_stack([t, block])  # (N, 22): time + 21 components


def generate(
    length_days: float,
    *,
    seed: int = 0,
    weather: str = "rain",
    n_realizations: int = 1,
    dt: float = 1.0 / 96.0,
    params: InfluentParams | None = None,
) -> np.ndarray:
    """Generate synthetic ASM1 influent.

    Returns ``(n_realizations, N, 22)`` (col 0 = time [d], cols 1..21 = ASM1 vector), or
    ``(N, 22)`` when ``n_realizations == 1``. ``weather`` in {'dry','rain','storm'}.
    Realizations differ only in the rain/noise RNG seed (deterministic patterns identical).
    """
    if weather not in {"dry", "rain", "storm"}:
        raise ValueError("weather must be 'dry', 'rain', or 'storm'")
    p = params or InfluentParams()
    t = np.arange(0.0, float(length_days), float(dt))
    if len(t) < 2:
        raise ValueError("length_days/dt too small to produce a time series")

    reals = np.stack([_one_realization(t, seed + r * 1000, weather, p) for r in range(n_realizations)])
    return reals[0] if n_realizations == 1 else reals


def realization(cfg_influent, length_days: float, timestep_days: float, realization_id: int) -> np.ndarray:
    """Build one influent realization (N, 22) from an InfluentConfig."""
    return generate(
        length_days,
        seed=cfg_influent.seed + realization_id * 1000,
        weather=_dominant_weather(cfg_influent.weather),
        n_realizations=1,
        dt=timestep_days,
    )


def _dominant_weather(weather: dict[str, float]) -> str:
    """Pick the weather regime with the largest configured weight."""
    if not weather:
        return "rain"
    return max(weather, key=weather.get)

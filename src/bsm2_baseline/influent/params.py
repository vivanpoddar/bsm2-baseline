"""Default parameters for the BSM2 phenomenological influent generator.

Values taken from the published reference ``ASM1_Influent_init.m`` (Gernaey et al.).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class InfluentParams:
    # --- flow (m3/d unless noted) ---
    pe_thousands: float = 80.0          # connected person-equivalents, in thousands
    q_per_pe: float = 150.0             # wastewater flow per PE [L/PE/d]
    q_ind_weekday: float = 2500.0       # average industrial flow on weekdays
    inf_bias: float = 7100.0            # mean seasonal infiltration
    inf_amp: float = 1200.0             # infiltration seasonal amplitude
    inf_phase: float = -math.pi * 15.0 / 24.0
    q_per_mm_rain: float = 1500.0       # flow per mm of rain
    a_h: float = 0.75                   # impervious-area fraction of rain (direct to sewer)

    # --- household pollutant loads [g/PE/d] ---
    codsol_g_pe: float = 19.31
    codpart_g_pe: float = 115.08
    snh_g_pe: float = 6.89 * 0.85       # 5.8565
    tkn_g_pe: float = 14.24 * 0.85      # 12.104

    # --- industrial pollutant loads [kg/d] ---
    codsol_ind_kg: float = 386.24
    codpart_ind_kg: float = 2301.80
    snh_ind_kg: float = 61.25 * 0.85    # 52.0625
    tkn_ind_kg: float = 128.62 * 0.85   # 109.327

    # --- ASM1 fractionation (asm1_fractionation.c) ---
    si_cst: float = 30.0                # soluble inert COD [g(COD)/m3]
    xi_fr: float = 0.182                # XI fraction of particulate COD
    xs_fr: float = 0.718                # XS fraction of particulate COD
    xbh_fr: float = 0.100               # XBH fraction of particulate COD
    snd_fr: float = 0.247               # soluble fraction of biodegradable organic N
    xnd_fr: float = 0.753               # particulate fraction of biodegradable organic N
    i_xb: float = 0.08                  # N content of biomass
    i_xp: float = 0.06                  # N content of inert particulates
    salk: float = 7.0                   # influent alkalinity [mol/m3]

    # --- temperature profile T(t) = bias + amp*sin(2pi/364 t + phase) + d_amp*sin(2pi t + d_phase) ---
    t_bias: float = 15.0
    t_amp: float = 5.0
    t_phase: float = math.pi * 8.5 / 24.0
    t_d_amp: float = 0.5
    t_d_phase: float = math.pi * 0.8

    # --- rain engine ---
    # The full Gernaey model routes rain through a soil reservoir (most drains to the
    # aquifer; only a fraction reaches the sewer). That reservoir is not reproduced here,
    # so the event threshold is raised from the reference 3.5 to 40.0 to absorb the missing
    # attenuation and reproduce the published mean flow (~20668 m3/d) while still generating
    # realistic occasional wet-weather surges. 'storm' widens the variance for bigger peaks.
    rain_mean: float = 1.0
    rain_var: float = 400.0             # storm multiplies this by 4
    rain_lower_limit: float = 40.0      # calibrated (reference 3.5; see note above)
    rain_smooth_alpha: float = 0.85     # per-hour exponential smoothing (catchment response)

    @property
    def q_hh_base(self) -> float:
        """Base dry-weather household flow [m3/d] = q_per_pe[L] * PE / 1000."""
        return self.q_per_pe * self.pe_thousands  # 150 * 80 = 12000

    @property
    def pe_full(self) -> float:
        return self.pe_thousands * 1000.0

"""Canonical schema for the BSM2 21-component state vector and derived quantities.

Every stream in `bsm2-python` (influent, effluent, reactor states, sludge, ...) is a
length-21 array in ASM1 order. This module is the single source of truth mapping those
indices to names, units, and human definitions, plus the engine-derived "advanced"
quantities (COD / BOD5 / nitrogen / TSS) that matter for effluent-compliance forecasting.

Indices and units follow the IWA BSM2 / ASM1 definitions exactly as implemented in
`bsm2_python.bsm2.plantperformance`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Variable:
    """One column in a captured trajectory table."""

    key: str
    index: int | None  # position in the 21-component vector; None for derived quantities
    unit: str
    description: str


# --- the 21 ASM1 state components, in vector order -------------------------------------
# [SI, SS, XI, XS, XBH, XBA, XP, SO, SNO, SNH, SND, XND, SALK, TSS, Q, TEMP, SD1..XD5]
ASM1_COMPONENTS: tuple[Variable, ...] = (
    Variable("S_I", 0, "g(COD)/m3", "Soluble inert organic matter"),
    Variable("S_S", 1, "g(COD)/m3", "Readily biodegradable substrate"),
    Variable("X_I", 2, "g(COD)/m3", "Particulate inert organic matter"),
    Variable("X_S", 3, "g(COD)/m3", "Slowly biodegradable substrate"),
    Variable("X_BH", 4, "g(COD)/m3", "Active heterotrophic biomass"),
    Variable("X_BA", 5, "g(COD)/m3", "Active autotrophic biomass"),
    Variable("X_P", 6, "g(COD)/m3", "Particulate products from biomass decay"),
    Variable("S_O", 7, "g(-COD)/m3", "Dissolved oxygen"),
    Variable("S_NO", 8, "g(N)/m3", "Nitrate and nitrite nitrogen"),
    Variable("S_NH", 9, "g(N)/m3", "Ammonia + ammonium nitrogen (NH4 + NH3)"),
    Variable("S_ND", 10, "g(N)/m3", "Soluble biodegradable organic nitrogen"),
    Variable("X_ND", 11, "g(N)/m3", "Particulate biodegradable organic nitrogen"),
    Variable("S_ALK", 12, "mol(HCO3)/m3", "Alkalinity"),
    Variable("TSS", 13, "g(SS)/m3", "Total suspended solids"),
    Variable("Q", 14, "m3/d", "Flow rate"),
    Variable("TEMP", 15, "degC", "Temperature"),
    Variable("S_D1", 16, "-", "Dummy state 1"),
    Variable("S_D2", 17, "-", "Dummy state 2"),
    Variable("S_D3", 18, "-", "Dummy state 3"),
    Variable("X_D4", 19, "-", "Dummy state 4"),
    Variable("X_D5", 20, "-", "Dummy state 5"),
)

# --- derived quantities computed by PlantPerformance.advanced_quantities ----------------
# Order here is the order we request from the engine; see runner.ADVANCED_COMPONENTS.
DERIVED_QUANTITIES: tuple[Variable, ...] = (
    Variable("Kjeldahl_N", None, "g(N)/m3", "Total Kjeldahl nitrogen (organic N + ammonia N)"),
    Variable("Total_N", None, "g(N)/m3", "Total nitrogen (Kjeldahl N + nitrate/nitrite N)"),
    Variable("COD", None, "g(COD)/m3", "Total chemical oxygen demand"),
    Variable("BOD5", None, "g(BOD)/m3", "5-day biochemical oxygen demand"),
    Variable("X_TSS", None, "g(SS)/m3", "Total suspended solids (computed from particulates)"),
)

# Component-name -> index, convenient for callers.
INDEX: dict[str, int] = {v.key: v.index for v in ASM1_COMPONENTS if v.index is not None}

# Effluent variables that map to real NPDES/permit limits. These are the columns the
# downstream compliance-forecasting model cares about most.
#
# NOTE: ASM1/BSM2 carries no phosphorus state, so TOTAL PHOSPHORUS IS NOT AVAILABLE
# from this engine. It is intentionally omitted rather than fabricated.
COMPLIANCE_VARIABLES: tuple[str, ...] = (
    "Q",          # flow
    "COD",        # chemical oxygen demand (derived)
    "BOD5",       # biochemical oxygen demand (derived)
    "TSS",        # total suspended solids (state)
    "S_NH",       # ammonia nitrogen
    "S_NO",       # nitrate/nitrite nitrogen
    "Total_N",    # total nitrogen (derived)
    "Kjeldahl_N", # total Kjeldahl nitrogen (derived)
)


def all_variables() -> tuple[Variable, ...]:
    """Full ordered schema: 21 state components followed by 5 derived quantities."""
    return ASM1_COMPONENTS + DERIVED_QUANTITIES

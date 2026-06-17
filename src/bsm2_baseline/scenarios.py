"""Compliance-risk scenario library.

A *scenario* is a named set of time-windowed perturbation *events* that push the plant
toward a specific effluent-permit failure mode. Each event has a type, a start day, a
duration, and a severity. This module defines:

  - the event/severity data model and the named presets (``PRESETS``),
  - pure perturbation primitives a backend applies:
      * ``apply_influent_perturbations`` — flow / temperature / concentration transforms
        on a 21-component influent array (engine-agnostic ASM1 layout),
      * ``nitrifier_mu_factor`` — multiplicative factor on nitrifier max-growth (toxic shock),
      * ``settler_param_factors`` — multiplicative factors on Takács settling params,
      * ``event_label`` — the active event label for a timestep (for dataset labelling).

The perturbations are deliberately simple, physically directional transforms — enough to
drive the target compliance signal — not calibrated event models. Severity maps to an
intensity per event type via ``_INTENSITY``.

Scenario -> targeted compliance risk:
  cold           -> S_NH / Total_N excursion (cold nitrification slowdown; needs temp kinetics)
  storm_overload -> TSS / BOD washout (hydraulic overload, short HRT, settler washout)
  toxic_shock    -> S_NH spike + recovery lag (nitrifier inhibition)
  poor_settling  -> effluent TSS washout (degraded Takács settling / bulking)
  p_upset        -> TP / PO4 excursion (QSDsan bsm2P engine only)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ASM1 component indices (shared 21-component layout).
SS, XS, XBH, XBA = 1, 3, 4, 5
SNH, TEMP, Q = 9, 15, 14


class ScenarioType(str, enum.Enum):
    COLD = "cold"
    STORM_OVERLOAD = "storm_overload"
    TOXIC_SHOCK = "toxic_shock"
    POOR_SETTLING = "poor_settling"
    P_UPSET = "p_upset"


# Severity -> intensity per event type.
_INTENSITY: dict[ScenarioType, dict[str, dict[str, float]]] = {
    ScenarioType.COLD: {
        "mild": {"temp_drop_c": 4.0}, "medium": {"temp_drop_c": 8.0}, "hard": {"temp_drop_c": 12.0},
    },
    ScenarioType.STORM_OVERLOAD: {
        "mild": {"q_factor": 1.5}, "medium": {"q_factor": 2.5}, "hard": {"q_factor": 4.0},
    },
    ScenarioType.TOXIC_SHOCK: {
        "mild": {"mu_a_factor": 0.6}, "medium": {"mu_a_factor": 0.35}, "hard": {"mu_a_factor": 0.1},
    },
    ScenarioType.POOR_SETTLING: {
        "mild": {"v0_factor": 0.7, "r_h_factor": 1.5},
        "medium": {"v0_factor": 0.5, "r_h_factor": 2.0},
        "hard": {"v0_factor": 0.3, "r_h_factor": 3.0},
    },
    ScenarioType.P_UPSET: {
        "mild": {"po4_factor": 1.5}, "medium": {"po4_factor": 2.5}, "hard": {"po4_factor": 4.0},
    },
}

# Which engine each scenario requires (None = any engine).
REQUIRES_PHOSPHORUS = {ScenarioType.P_UPSET}


@dataclass
class ScenarioEvent:
    """A single time-windowed perturbation."""

    type: ScenarioType
    start_day: float
    duration_days: float
    severity: str = "medium"
    params: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.type, ScenarioType):
            self.type = ScenarioType(self.type)
        if self.duration_days <= 0:
            raise ValueError("event duration_days must be positive")

    def intensity(self, key: str) -> float:
        """Resolve an intensity value: explicit params override the severity table."""
        if key in self.params:
            return float(self.params[key])
        table = _INTENSITY[self.type]
        if self.severity not in table:
            raise ValueError(f"unknown severity '{self.severity}' for {self.type.value}")
        return table[self.severity][key]

    def active(self, t: float) -> bool:
        return self.start_day <= t < self.start_day + self.duration_days


# Named presets. Each expands to a list of events. "baseline" is empty (reproduces phase-1).
PRESETS: dict[str, list[ScenarioEvent]] = {
    "baseline": [],
    "cold": [ScenarioEvent(ScenarioType.COLD, start_day=60, duration_days=45, severity="hard")],
    "storm_overload": [
        ScenarioEvent(ScenarioType.STORM_OVERLOAD, start_day=30, duration_days=2, severity="medium"),
        ScenarioEvent(ScenarioType.STORM_OVERLOAD, start_day=90, duration_days=3, severity="hard"),
    ],
    "toxic_shock": [ScenarioEvent(ScenarioType.TOXIC_SHOCK, start_day=45, duration_days=2, severity="hard")],
    "poor_settling": [
        ScenarioEvent(ScenarioType.POOR_SETTLING, start_day=40, duration_days=20, severity="medium")
    ],
    "p_upset": [ScenarioEvent(ScenarioType.P_UPSET, start_day=50, duration_days=14, severity="medium")],
}


def expand_preset(name: str | None) -> list[ScenarioEvent]:
    """Return the event list for a preset name (None/'baseline' -> no events)."""
    if name is None:
        return []
    if name not in PRESETS:
        raise ValueError(f"unknown scenario preset '{name}'; known: {sorted(PRESETS)}")
    return list(PRESETS[name])


def requires_phosphorus(events: list[ScenarioEvent]) -> bool:
    return any(e.type in REQUIRES_PHOSPHORUS for e in events)


def apply_influent_perturbations(
    y_in: np.ndarray, data_time: np.ndarray, events: list[ScenarioEvent]
) -> np.ndarray:
    """Apply flow / temperature influent transforms over each event's window.

    ``y_in`` is (n, 21) in ASM1 order; ``data_time`` is the matching (n,) day axis.
    Returns a modified copy (the input is not mutated).
    """
    out = y_in.copy()
    for e in events:
        mask = (data_time >= e.start_day) & (data_time < e.start_day + e.duration_days)
        if not mask.any():
            continue
        if e.type is ScenarioType.COLD:
            out[mask, TEMP] = out[mask, TEMP] - e.intensity("temp_drop_c")
        elif e.type is ScenarioType.STORM_OVERLOAD:
            # Hydraulic overload: raise flow (shortens HRT, drives settler washout).
            out[mask, Q] = out[mask, Q] * e.intensity("q_factor")
    return out


def nitrifier_mu_factor(events: list[ScenarioEvent], t: float) -> float:
    """Product of nitrifier max-growth multipliers for toxic-shock events active at ``t``."""
    factor = 1.0
    for e in events:
        if e.type is ScenarioType.TOXIC_SHOCK and e.active(t):
            factor *= e.intensity("mu_a_factor")
    return factor


def settler_param_factors(events: list[ScenarioEvent], t: float) -> dict[str, float]:
    """Multiplicative factors on settling velocity and hindered-settling exponent at ``t``."""
    v0_factor = 1.0
    r_h_factor = 1.0
    for e in events:
        if e.type is ScenarioType.POOR_SETTLING and e.active(t):
            v0_factor *= e.intensity("v0_factor")
            r_h_factor *= e.intensity("r_h_factor")
    return {"v0_factor": v0_factor, "r_h_factor": r_h_factor}


def phosphorus_release_factor(events: list[ScenarioEvent], t: float) -> float:
    """PO4 release multiplier for P-upset events active at ``t`` (QSDsan engine only)."""
    factor = 1.0
    for e in events:
        if e.type is ScenarioType.P_UPSET and e.active(t):
            factor *= e.intensity("po4_factor")
    return factor


def event_label(events: list[ScenarioEvent], t: float) -> str:
    """Label for the active event(s) at ``t``; 'none' when no event is active."""
    active = sorted({e.type.value for e in events if e.active(t)})
    return "+".join(active) if active else "none"


def event_label_array(events: list[ScenarioEvent], time: np.ndarray) -> np.ndarray:
    """Per-timestep event labels for an entire time axis."""
    if not events:
        return np.full(len(time), "none", dtype=object)
    return np.array([event_label(events, float(t)) for t in time], dtype=object)


def describe(name: str | None) -> dict[str, Any]:
    """A JSON-serialisable description of a preset for metadata."""
    events = expand_preset(name)
    return {
        "preset": name or "baseline",
        "events": [
            {
                "type": e.type.value,
                "start_day": e.start_day,
                "duration_days": e.duration_days,
                "severity": e.severity,
                "params": e.params,
            }
            for e in events
        ],
    }

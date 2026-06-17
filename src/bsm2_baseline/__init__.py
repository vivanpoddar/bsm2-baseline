"""BSM2 baseline simulation harness.

A thin, configurable wrapper around the validated ``bsm2-python`` engine that runs an
ideal, fault-free BSM2 scenario and exports a tidy, documented dataset for downstream
effluent-compliance forecasting. A Sensor/Actuator seam (identity passthrough) is the
single extension point for a future fault-injection layer.
"""

from __future__ import annotations

from . import scenarios
from .config import (
    Engine,
    InfluentConfig,
    MeasurementConfig,
    ModelVariant,
    PermitLimit,
    ScenarioConfig,
    SettlerConfig,
)
from .energy import EnergyResult, export_power, power_plots, run_power_simulation
from .export import aggregate_effluent, export_run
from .interfaces import (
    Actuator,
    IdentityActuator,
    IdentitySensor,
    Sensor,
)
from .plots import sanity_plots
from .runner import RunResult, run_scenario
from .scenarios import PRESETS, ScenarioEvent, ScenarioType

__all__ = [
    "PRESETS",
    "Actuator",
    "Engine",
    "EnergyResult",
    "IdentityActuator",
    "IdentitySensor",
    "InfluentConfig",
    "MeasurementConfig",
    "ModelVariant",
    "PermitLimit",
    "RunResult",
    "ScenarioConfig",
    "ScenarioEvent",
    "ScenarioType",
    "Sensor",
    "SettlerConfig",
    "aggregate_effluent",
    "export_power",
    "export_run",
    "power_plots",
    "run_power_simulation",
    "run_scenario",
    "sanity_plots",
    "scenarios",
]

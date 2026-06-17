"""BSM2 baseline simulation harness.

A thin, configurable wrapper around the validated ``bsm2-python`` engine that runs an
ideal, fault-free BSM2 scenario and exports a tidy, documented dataset for downstream
effluent-compliance forecasting. A Sensor/Actuator seam (identity passthrough) is the
single extension point for a future fault-injection layer.
"""

from __future__ import annotations

from .config import ModelVariant, ScenarioConfig
from .export import aggregate_effluent, export_run
from .interfaces import (
    Actuator,
    IdentityActuator,
    IdentitySensor,
    Sensor,
)
from .plots import sanity_plots
from .runner import RunResult, run_scenario

__all__ = [
    "Actuator",
    "IdentityActuator",
    "IdentitySensor",
    "ModelVariant",
    "RunResult",
    "ScenarioConfig",
    "Sensor",
    "aggregate_effluent",
    "export_run",
    "run_scenario",
    "sanity_plots",
]

"""Measurement layer — realistic sensor and actuator models behind the phase-1 seam.

``measurement.mode='ideal'`` uses the identity passthrough (reproduces phase-1);
``'realistic'`` uses these models. The deferred fault module plugs in at the same seam.
"""

from __future__ import annotations

from ..config import MeasurementConfig
from ..interfaces import Actuator, IdentityActuator, IdentitySensor, Sensor
from .actuators import DEFAULT_ACTUATORS, RealisticActuator
from .sensors import DEFAULT_SENSORS, SENSOR_CLASSES, RealisticSensor


def build_sensor(cfg: MeasurementConfig, *, seed: int = 0) -> Sensor:
    """Return the sensor implementation for a measurement config."""
    if cfg.mode == "ideal":
        return IdentitySensor()
    return RealisticSensor(cfg.sensors, seed=seed)


def build_actuator(cfg: MeasurementConfig) -> Actuator:
    """Return the actuator implementation for a measurement config."""
    if cfg.mode == "ideal":
        return IdentityActuator()
    return RealisticActuator(cfg.actuators)


__all__ = [
    "DEFAULT_ACTUATORS",
    "DEFAULT_SENSORS",
    "SENSOR_CLASSES",
    "RealisticActuator",
    "RealisticSensor",
    "build_actuator",
    "build_sensor",
]

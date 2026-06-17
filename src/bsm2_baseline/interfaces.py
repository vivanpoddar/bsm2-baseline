"""Sensor / Actuator seam — the single extension point for a future fault layer.

ARCHITECTURE ONLY. The baseline is strictly ideal: every reading and command passes
through an identity (passthrough) implementation, so the exported data is the plant's
true state.

How faults will slot in later (do NOT implement here):
    A future `bsm2_baseline.faults` module will provide alternative `Sensor` / `Actuator`
    implementations — bias, drift, freeze/stuck-at, dropout (NaN), gaussian noise,
    actuator stuck/clipped/failed — constructed from the scenario `seed`. The runner
    already routes the dissolved-oxygen setpoint through `Actuator.command()` and the
    measured effluent stream through `Sensor.observe()`, so swapping the identity
    implementations for faulty ones requires no change to the core simulation code.

Contract:
    - `Sensor.observe(channel, values, t)` maps the true signal to what an instrument
      would report. `values` is a 1-D array over time; `t` is the matching time axis.
    - `Actuator.command(channel, value, t)` maps a commanded setpoint to what the
      actuator actually applies, at a single timestep.
    Implementations must be pure and must not mutate their inputs.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class Sensor(Protocol):
    """Maps a true process signal to an observed (measured) signal."""

    def observe(self, channel: str, values: np.ndarray, t: np.ndarray) -> np.ndarray:
        ...


@runtime_checkable
class Actuator(Protocol):
    """Maps a commanded setpoint/value to the value actually applied by the actuator."""

    def command(self, channel: str, value: float, t: float) -> float:
        ...


class IdentitySensor:
    """Ideal sensor: reports the true signal unchanged."""

    def observe(self, channel: str, values: np.ndarray, t: np.ndarray) -> np.ndarray:  # noqa: ARG002
        return values


class IdentityActuator:
    """Ideal actuator: applies the commanded value unchanged."""

    def command(self, channel: str, value: float, t: float) -> float:  # noqa: ARG002
        return value

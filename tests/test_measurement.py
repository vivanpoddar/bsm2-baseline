"""Measurement layer: identity collapse, sensor effects, actuator dynamics."""

from __future__ import annotations

import numpy as np

from bsm2_baseline.config import MeasurementConfig
from bsm2_baseline.interfaces import IdentityActuator, IdentitySensor
from bsm2_baseline.measurement import (
    RealisticActuator,
    RealisticSensor,
    build_actuator,
    build_sensor,
)


def test_ideal_mode_is_identity():
    s = build_sensor(MeasurementConfig(mode="ideal"))
    a = build_actuator(MeasurementConfig(mode="ideal"))
    assert isinstance(s, IdentitySensor)
    assert isinstance(a, IdentityActuator)
    t = np.linspace(0, 1, 50)
    v = np.sin(t) + 5
    assert np.array_equal(s.observe("effluent.S_NH", v, t), v)


def test_unconfigured_channel_passes_through():
    s = RealisticSensor(seed=0)
    t = np.linspace(0, 2, 200)
    v = np.full_like(t, 3.0)
    # S_I has no default sensor -> identity passthrough
    assert np.array_equal(s.observe("effluent.S_I", v, t), v)


def test_sensor_clips_to_range_and_perturbs():
    s = RealisticSensor({"S_NH": {"class": "A", "range": (0.0, 10.0), "nl": 0.05}}, seed=1)
    t = np.linspace(0, 5, 2000)
    v = np.full_like(t, 5.0)
    y = s.observe("effluent.S_NH", v, t)
    assert y.shape == v.shape
    assert np.all(y >= 0.0) and np.all(y <= 10.0)        # range clip
    assert not np.allclose(y, v)                          # noise perturbs
    assert abs(y.mean() - 5.0) < 0.5                      # unbiased around the true value


def test_sensor_deterministic_with_seed():
    t = np.linspace(0, 3, 1000)
    v = np.full_like(t, 4.0)
    a = RealisticSensor({"S_NH": {"class": "B0", "range": (0, 50)}}, seed=7).observe("S_NH", v, t)
    b = RealisticSensor({"S_NH": {"class": "B0", "range": (0, 50)}}, seed=7).observe("S_NH", v, t)
    assert np.array_equal(a, b)


def test_actuator_clips_and_lags():
    a = RealisticActuator({"reactor4_DO_setpoint": {"tr": 10.0, "n": 1, "min": 0.0, "max": 5.0}})
    ch = "reactor4_DO_setpoint"
    # first call initialises at the (clipped) command
    assert a.command(ch, 2.0, 0.0) == 2.0
    # a step up is approached gradually (lag), and never exceeds the max
    vals = [a.command(ch, 10.0, 0.01 * k) for k in range(1, 20)]
    assert all(v <= 5.0 for v in vals)         # clipped to max
    assert vals[0] < 5.0                        # lag: not instantaneous
    assert vals[-1] > vals[0]                   # converging upward


def test_actuator_ideal_passthrough_for_unknown_channel():
    a = RealisticActuator()
    assert a.command("some.unknown_channel", 123.4, 0.0) == 123.4

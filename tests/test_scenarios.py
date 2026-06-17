"""Scenario library: presets, windows, and perturbation primitives."""

from __future__ import annotations

import numpy as np
import pytest

from bsm2_baseline import scenarios as sc
from bsm2_baseline.scenarios import ScenarioEvent, ScenarioType


def test_known_and_unknown_presets():
    assert sc.expand_preset("baseline") == []
    assert len(sc.expand_preset("cold")) == 1
    with pytest.raises(ValueError, match="unknown scenario preset"):
        sc.expand_preset("nope")


def test_event_active_window():
    e = ScenarioEvent(ScenarioType.COLD, start_day=10, duration_days=5)
    assert not e.active(9.9)
    assert e.active(10.0)
    assert e.active(14.99)
    assert not e.active(15.0)


def test_severity_intensity_and_override():
    e = ScenarioEvent(ScenarioType.COLD, start_day=0, duration_days=1, severity="hard")
    assert e.intensity("temp_drop_c") == 12.0
    e2 = ScenarioEvent(ScenarioType.COLD, start_day=0, duration_days=1, params={"temp_drop_c": 3.0})
    assert e2.intensity("temp_drop_c") == 3.0


def test_influent_perturbation_cold_and_storm():
    t = np.arange(0, 20, 1.0)
    y = np.ones((len(t), 21))
    y[:, sc.TEMP] = 15.0
    y[:, sc.Q] = 100.0
    events = [
        ScenarioEvent(ScenarioType.COLD, start_day=5, duration_days=5, params={"temp_drop_c": 8.0}),
        ScenarioEvent(ScenarioType.STORM_OVERLOAD, start_day=12, duration_days=3, params={"q_factor": 3.0}),
    ]
    out = sc.apply_influent_perturbations(y, t, events)
    # cold window: temp dropped; outside: unchanged
    assert np.allclose(out[(t >= 5) & (t < 10), sc.TEMP], 7.0)
    assert np.allclose(out[t < 5, sc.TEMP], 15.0)
    # storm window: flow raised
    assert np.allclose(out[(t >= 12) & (t < 15), sc.Q], 300.0)
    assert np.allclose(out[t < 12, sc.Q], 100.0)
    # input not mutated
    assert np.allclose(y[:, sc.TEMP], 15.0)


def test_process_factors():
    events = [
        ScenarioEvent(ScenarioType.TOXIC_SHOCK, start_day=5, duration_days=2, params={"mu_a_factor": 0.2})
    ]
    assert sc.nitrifier_mu_factor(events, 6.0) == pytest.approx(0.2)
    assert sc.nitrifier_mu_factor(events, 9.0) == 1.0

    ps = [ScenarioEvent(ScenarioType.POOR_SETTLING, start_day=0, duration_days=10,
                        params={"v0_factor": 0.5, "r_h_factor": 2.0})]
    f = sc.settler_param_factors(ps, 3.0)
    assert f["v0_factor"] == 0.5 and f["r_h_factor"] == 2.0
    assert sc.settler_param_factors(ps, 20.0) == {"v0_factor": 1.0, "r_h_factor": 1.0}


def test_requires_phosphorus():
    assert sc.requires_phosphorus(sc.expand_preset("p_upset"))
    assert not sc.requires_phosphorus(sc.expand_preset("cold"))


def test_event_labels():
    events = sc.expand_preset("cold")  # cold 60..105
    labels = sc.event_label_array(events, np.array([10.0, 70.0, 200.0]))
    assert list(labels) == ["none", "cold", "none"]

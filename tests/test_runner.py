"""Runner behaviour: shapes, physical sanity, and determinism.

Uses a short open-loop run (coarse 15-min timestep) so the suite stays fast.
"""

from __future__ import annotations

import numpy as np
import pytest

from bsm2_baseline import ScenarioConfig, run_scenario
from bsm2_baseline.variables import INDEX


@pytest.fixture(scope="module")
def short_result():
    cfg = ScenarioConfig(
        name="test_short",
        variant="open_loop",
        timestep_minutes=15.0,
        duration_days=3.0,
        eval_days=1,
        stabilize=True,
    )
    return run_scenario(cfg, progress=False)


def test_shapes_consistent(short_result):
    n = len(short_result.time)
    assert short_result.streams["effluent"].shape == (n, 21)
    assert short_result.derived["effluent"].shape == (n, 5)
    assert short_result.indices["EQI"].shape == (n,)


def test_physically_sensible(short_result):
    eff = short_result.streams["effluent"]
    # All concentrations finite and non-negative.
    assert np.all(np.isfinite(eff))
    assert np.all(eff[:, INDEX["S_NH"]] >= 0.0)
    assert np.all(eff[:, INDEX["TSS"]] >= 0.0)
    # Effluent flow is strictly positive.
    assert np.all(eff[:, INDEX["Q"]] > 0.0)
    # Benchmark indices are positive over the run.
    assert np.all(short_result.indices["IQI"] > 0.0)
    assert np.all(short_result.indices["EQI"] > 0.0)


def test_final_performance_keys(short_result):
    fp = short_result.final_performance
    for key in ("IQI", "EQI", "OCI"):
        assert key in fp and np.isfinite(fp[key])


def test_deterministic():
    cfg = ScenarioConfig(
        name="test_det",
        variant="open_loop",
        timestep_minutes=15.0,
        duration_days=2.0,
        eval_days=1,
        stabilize=True,
    )
    a = run_scenario(cfg, progress=False)
    b = run_scenario(cfg, progress=False)
    assert np.array_equal(a.streams["effluent"], b.streams["effluent"])
    assert np.array_equal(a.indices["EQI"], b.indices["EQI"])
    assert a.final_performance["EQI"] == b.final_performance["EQI"]

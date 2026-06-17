"""Export tables, aggregation windows, and metadata sidecar."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from bsm2_baseline import ScenarioConfig, export_run, run_scenario
from bsm2_baseline.export import aggregate_effluent
from bsm2_baseline.variables import COMPLIANCE_VARIABLES


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    cfg = ScenarioConfig(
        name="test_export",
        variant="open_loop",
        timestep_minutes=15.0,
        duration_days=3.0,
        eval_days=1,
        stabilize=True,
        export_format="parquet",
    )
    result = run_scenario(cfg, progress=False)
    out = tmp_path_factory.mktemp("out")
    written = export_run(result, output_dir=out)
    return result, written


def test_writes_expected_artifacts(exported):
    _, written = exported
    for key in ("effluent", "influent", "indices", "effluent_daily", "metadata"):
        assert key in written


def test_effluent_table_has_compliance_columns(exported):
    _, written = exported
    df = pd.read_parquet(written["effluent"])
    assert "time_d" in df.columns
    for col in COMPLIANCE_VARIABLES:
        assert col in df.columns


def test_metadata_complete(exported):
    _, written = exported
    meta = json.loads(open(written["metadata"], encoding="utf-8").read())
    assert meta["bsm2_python_version"] == "0.0.16"
    assert "config" in meta and "variables" in meta
    assert meta["config"]["variant"] == "open_loop"
    # 21 components + 5 derived described.
    assert len(meta["variables"]) == 26
    assert "phosphorus" in meta["phosphorus_note"].lower()


def test_aggregate_windows():
    # 0..10 days at 0.5-day resolution, constant values -> means preserved.
    t = np.arange(0, 10, 0.5)
    df = pd.DataFrame({"time_d": t, "S_NH": np.ones_like(t) * 2.0, "Q": np.ones_like(t) * 100.0})
    daily = aggregate_effluent(df, "daily", columns=("S_NH", "Q"))
    assert len(daily) == 10
    assert np.allclose(daily["S_NH"], 2.0)
    weekly = aggregate_effluent(df, "weekly", columns=("S_NH", "Q"))
    assert len(weekly) == 2  # days 0-6 and 7-9

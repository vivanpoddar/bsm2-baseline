"""Plant power-use (BSM2OLEM) simulation: shapes, balances, and export."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bsm2_baseline import ScenarioConfig
from bsm2_baseline.energy import export_power, run_power_simulation


@pytest.fixture(scope="module")
def power_result():
    cfg = ScenarioConfig(
        name="test_power",
        variant="open_loop",
        timestep_minutes=15.0,
        duration_days=15.0,
        eval_days=3,
        stabilize=True,
    )
    return run_power_simulation(cfg, progress=False)


def test_power_shapes_and_balance(power_result):
    n = len(power_result.time)
    p = power_result.power
    assert p["electricity_demand_kW"].shape == (n,)
    # demand decomposition is consistent
    assert np.allclose(
        p["electricity_demand_kW"],
        p["aeration_kW"] + p["pumping_kW"] + p["mixing_kW"],
        atol=1e-6,
    )
    # net grid import = demand - CHP generation
    assert np.allclose(
        p["net_grid_import_kW"],
        p["electricity_demand_kW"] - p["chp_electricity_kW"],
        atol=1e-6,
    )
    # aeration dominates demand; all finite
    assert np.all(np.isfinite(p["electricity_demand_kW"]))
    assert p["aeration_kW"].mean() > p["pumping_kW"].mean()


def test_biogas_and_economics(power_result):
    b = power_result.biogas
    assert np.all(b["biogas_production_Nm3_per_d"] >= 0)
    assert b["biogas_production_Nm3_per_d"].mean() > 0
    assert "final_cum_cash_flow_EUR" in power_result.economics
    assert np.isfinite(power_result.economics["final_cum_cash_flow_EUR"])


def test_power_export(power_result, tmp_path):
    written = export_power(power_result, output_dir=tmp_path)
    for key in ("power", "biogas", "economics", "metadata"):
        assert key in written
    df = pd.read_parquet(written["power"])
    assert "electricity_demand_kW" in df.columns
    assert "net_grid_import_kW" in df.columns

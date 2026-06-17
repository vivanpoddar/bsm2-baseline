"""QSDsan bsm2P backend — phosphorus, composite reconstruction, export.

Skipped unless the optional [qsdsan] extra is installed.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("exposan", reason="requires the optional [qsdsan] extra")

from bsm2_baseline import ScenarioConfig  # noqa: E402
from bsm2_baseline.engines.qsdsan_bsm2 import (  # noqa: E402
    CANONICAL,
    export_qsdsan,
    run_qsdsan_scenario,
)


@pytest.fixture(scope="module")
def qsdsan_result():
    cfg = ScenarioConfig(
        name="test_qsdsan",
        engine="qsdsan_bsm2",
        variant="open_loop",
        timestep_minutes=120.0,
        duration_days=20.0,
        eval_days=5,
    )
    return run_qsdsan_scenario(cfg, kind="bsm2p", progress=False)


def test_phosphorus_present_and_sane(qsdsan_result):
    eff = qsdsan_result.effluent
    for var in CANONICAL:
        assert var in eff
    assert np.all(eff["TP"] > 0)
    assert np.all(eff["S_PO4"] >= 0)
    # effluent TP is in a physically sensible range for bsm2P (well below influent)
    assert 0.1 < np.nanmean(eff["TP"]) < 10.0


def test_reconstruction_matches_endstate(qsdsan_result):
    # The vectorized reconstruction must match QSDsan's own WasteStream properties.
    eff, final = qsdsan_result.effluent, qsdsan_result.final
    assert eff["TP"][-1] == pytest.approx(final["TP"], rel=1e-6)
    assert eff["COD"][-1] == pytest.approx(final["COD"], rel=1e-6)
    assert eff["Total_N"][-1] == pytest.approx(final["TN"], rel=1e-6)
    assert eff["TSS"][-1] == pytest.approx(final["TSS"], rel=1e-6)


def test_p_balance_closes_reasonably(qsdsan_result):
    pb = qsdsan_result.p_balance
    # most influent P is removed to sludge (EBPR), a fraction leaves in the effluent
    assert 0.5 < pb["P_removed_fraction"] < 1.0


def test_export(qsdsan_result, tmp_path):
    written = export_qsdsan(qsdsan_result, output_dir=tmp_path)
    assert {"effluent", "influent", "metadata"} <= set(written)

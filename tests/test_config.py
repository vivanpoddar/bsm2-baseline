"""Config validation and YAML loading."""

from __future__ import annotations

import pytest

from bsm2_baseline.config import ModelVariant, ScenarioConfig


def test_defaults_are_closed_loop():
    cfg = ScenarioConfig()
    assert cfg.variant is ModelVariant.CLOSED_LOOP
    assert cfg.timestep_days == pytest.approx(1.0 / 60.0 / 24.0)


def test_closed_loop_rejects_coarse_timestep():
    with pytest.raises(ValueError, match="closed-loop timestep"):
        ScenarioConfig(variant="closed_loop", timestep_minutes=15.0)


def test_open_loop_allows_coarse_timestep():
    cfg = ScenarioConfig(variant="open_loop", timestep_minutes=15.0)
    assert cfg.variant is ModelVariant.OPEN_LOOP


def test_bad_export_format_rejected():
    with pytest.raises(ValueError, match="export_format"):
        ScenarioConfig(export_format="xlsx")


def test_from_yaml_roundtrip(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(
        "name: t\nvariant: open_loop\ntimestep_minutes: 15\nduration_days: 3\n",
        encoding="utf-8",
    )
    cfg = ScenarioConfig.from_yaml(p)
    assert cfg.name == "t"
    assert cfg.variant is ModelVariant.OPEN_LOOP
    assert cfg.duration_days == 3
    assert cfg.to_dict()["variant"] == "open_loop"

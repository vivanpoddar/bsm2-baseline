"""Typed scenario configuration for the BSM2 baseline harness.

A single `ScenarioConfig` dataclass fully determines a run. It is loaded from YAML and
validated on construction so a bad config fails fast with a clear message.
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ModelVariant(str, enum.Enum):
    """Which BSM2 plant model to run."""

    CLOSED_LOOP = "closed_loop"  # BSM2CL: PID dissolved-oxygen control
    OPEN_LOOP = "open_loop"      # BSM2OL: fixed KLa, no control


# One minute and fifteen minutes expressed in days (the engine's time unit).
ONE_MINUTE_D = 1.0 / 60.0 / 24.0
FIFTEEN_MINUTES_D = 15.0 / 60.0 / 24.0


@dataclass
class ScenarioConfig:
    """Everything needed to build, run, and export one baseline scenario.

    Attributes
    ----------
    name:
        Human label for the run; used in output filenames.
    variant:
        Closed-loop (default) or open-loop plant model.
    influent:
        Path to an influent CSV, or "default" to use the package's standard
        609-day dynamic influent.
    timestep_minutes:
        Simulation timestep in minutes. Closed-loop must stay <= 1 min.
    duration_days:
        Simulated time span in days, or None for the full influent record (~609 d).
    eval_days:
        Number of trailing days over which IQI/EQI/OCI are averaged.
    do_setpoint:
        Dissolved-oxygen setpoint [g(O2)/m3] for the closed-loop controller.
        Ignored for the open-loop variant.
    stabilize:
        Run the plant to steady state before the timed simulation (recommended;
        matches the package's reference tests).
    seed:
        Random seed. Unused at the ideal baseline (sensor noise is off); wired in
        now so the future fault layer is deterministic.
    output_dir:
        Directory for exported datasets, metadata, and plots.
    export_format:
        "parquet" (default) or "csv".
    """

    name: str = "baseline"
    variant: ModelVariant = ModelVariant.CLOSED_LOOP
    influent: str = "default"
    timestep_minutes: float = 1.0
    duration_days: float | None = None
    eval_days: int = 5
    do_setpoint: float = 2.0
    stabilize: bool = True
    seed: int = 0
    output_dir: str = "data"
    export_format: str = "parquet"

    # Derived, not set by the user.
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.variant, ModelVariant):
            self.variant = ModelVariant(self.variant)
        if self.timestep_minutes <= 0:
            raise ValueError("timestep_minutes must be positive")
        if self.variant is ModelVariant.CLOSED_LOOP and self.timestep_minutes > 1.0 + 1e-9:
            raise ValueError(
                "closed-loop timestep must be <= 1 minute (sensor sensitivity); "
                f"got {self.timestep_minutes}"
            )
        if self.duration_days is not None and self.duration_days <= 0:
            raise ValueError("duration_days must be positive or null")
        if self.eval_days <= 0:
            raise ValueError("eval_days must be positive")
        if self.export_format not in {"parquet", "csv"}:
            raise ValueError("export_format must be 'parquet' or 'csv'")

    @property
    def timestep_days(self) -> float:
        return self.timestep_minutes / 60.0 / 24.0

    @classmethod
    def from_yaml(cls, path: str | Path) -> ScenarioConfig:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        extra = {k: v for k, v in raw.items() if k not in known}
        kwargs = {k: v for k, v in raw.items() if k in known and k != "extra"}
        cfg = cls(**kwargs)
        cfg.extra = extra
        return cfg

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["variant"] = self.variant.value
        return d

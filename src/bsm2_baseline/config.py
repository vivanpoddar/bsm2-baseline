"""Typed scenario configuration for the BSM2 baseline + extensions harness.

A single ``ScenarioConfig`` dataclass fully determines a run. It is loaded from YAML and
validated on construction so a bad config fails fast with a clear message.

Phase-2 adds (all optional, backward-compatible with phase-1):
  - ``engine``      : which biokinetic engine to use (bsm2-python or QSDsan bsm2P)
  - ``influent``    : static file vs. synthetic generator + realizations + seed
  - ``settler``     : Takács settling parameters (drive poor-settling scenarios)
  - ``measurement`` : sensor/actuator layer mode (ideal reproduces phase-1)
  - ``scenario``    : named compliance-risk scenario preset (perturbation events)
  - ``permit``      : target effluent limits + averaging windows
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class ModelVariant(str, enum.Enum):
    """Which BSM2 plant model to run (control configuration)."""

    CLOSED_LOOP = "closed_loop"  # PID dissolved-oxygen control
    OPEN_LOOP = "open_loop"      # fixed KLa, no control


class Engine(str, enum.Enum):
    """Which biokinetic engine backend to use."""

    BSM2_PYTHON = "bsm2_python"  # ASM1 + ADM1 (no phosphorus); fast, validated (phase-1)
    QSDSAN_BSM2 = "qsdsan_bsm2"  # QSDsan/EXPOsan bsm2P: mASM2d + ADM1p (full phosphorus)


# One minute and fifteen minutes expressed in days (the engine's time unit).
ONE_MINUTE_D = 1.0 / 60.0 / 24.0
FIFTEEN_MINUTES_D = 15.0 / 60.0 / 24.0


@dataclass
class InfluentConfig:
    """Influent source: a static file, the package default, or the synthetic generator.

    mode:
        - "default": the package's standard 609-day dynamic influent.
        - "file": read ``path`` (CSV in the engine's influent format).
        - "generate": synthesize with the Gernaey phenomenological generator.
    length_years / weather / holidays:
        Generator settings (mode="generate" only).
    n_realizations:
        Number of independent influent realizations to generate (mode="generate").
    seed:
        Generator seed (per-realization seeds derive from this + realization index).
    """

    mode: str = "default"
    path: str | None = None
    length_years: float = 1.0
    n_realizations: int = 1
    weather: dict[str, float] = field(default_factory=lambda: {"dry": 0.7, "rain": 0.25, "storm": 0.05})
    holidays: bool = True
    seed: int = 0

    def __post_init__(self) -> None:
        if self.mode not in {"default", "file", "generate"}:
            raise ValueError("influent.mode must be 'default', 'file', or 'generate'")
        if self.mode == "file" and not self.path:
            raise ValueError("influent.mode='file' requires a path")
        if self.n_realizations < 1:
            raise ValueError("influent.n_realizations must be >= 1")


@dataclass
class SettlerConfig:
    """Takács 1-D settler parameters. Defaults are the standard BSM2 values.

    Drive poor-settling / bulking scenarios by lowering the settling velocities
    (``v0``, ``v0_max``) and/or raising the hindered-settling exponent ``r_h``.
    """

    model: str = "takacs"
    v0_max: float = 250.0     # maximum settling velocity [m/d]
    v0: float = 474.0         # maximum Vesilind settling velocity [m/d]
    r_h: float = 5.76e-4      # hindered zone settling parameter [m3/g]
    r_p: float = 2.86e-3      # flocculant zone settling parameter [m3/g]
    f_ns: float = 2.28e-3     # non-settleable fraction [-]


@dataclass
class MeasurementConfig:
    """Sensor/actuator measurement-layer settings.

    mode:
        - "ideal": identity passthrough (reproduces phase-1 exactly).
        - "realistic": apply the Rieger sensor models + actuator dynamics.
    sensors:
        Per-channel sensor settings, e.g. {"S_NH": {"class": "B", "cadence_min": 5, ...}}.
    actuators:
        Actuator settings, e.g. {"aeration": {"tau_min": 5, "kla_max": 360, ...}}.
    """

    mode: str = "ideal"
    sensors: dict[str, dict[str, Any]] = field(default_factory=dict)
    actuators: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in {"ideal", "realistic"}:
            raise ValueError("measurement.mode must be 'ideal' or 'realistic'")


@dataclass
class PermitLimit:
    """One effluent permit limit and its averaging window."""

    parameter: str            # canonical variable key, e.g. "S_NH", "TSS", "Total_N", "TP"
    limit: float              # limit value (same unit as the variable)
    window: str = "monthly_avg"  # daily_max | weekly_avg | monthly_avg | annual_avg | instantaneous

    _WINDOWS = {"daily_max", "daily_avg", "weekly_avg", "monthly_avg", "annual_avg", "instantaneous"}

    def __post_init__(self) -> None:
        if self.window not in self._WINDOWS:
            raise ValueError(f"permit window must be one of {sorted(self._WINDOWS)}")


@dataclass
class ScenarioConfig:
    """Everything needed to build, run, and export one scenario.

    Phase-1 fields are unchanged; phase-2 fields default to values that reproduce
    phase-1 behaviour (engine=bsm2_python, influent=default, measurement=ideal,
    scenario=None).
    """

    name: str = "baseline"
    variant: ModelVariant = ModelVariant.CLOSED_LOOP
    engine: Engine = Engine.BSM2_PYTHON
    influent: InfluentConfig = field(default_factory=InfluentConfig)
    timestep_minutes: float = 1.0
    duration_days: float | None = None
    eval_days: int = 5
    do_setpoint: float = 2.0
    stabilize: bool = True
    seed: int = 0
    settler: SettlerConfig = field(default_factory=SettlerConfig)
    measurement: MeasurementConfig = field(default_factory=MeasurementConfig)
    scenario: str | None = None              # named preset from scenarios.PRESETS, or None
    permit: list[PermitLimit] = field(default_factory=list)
    output_dir: str = "data"
    export_format: str = "parquet"

    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.variant, ModelVariant):
            self.variant = ModelVariant(self.variant)
        if not isinstance(self.engine, Engine):
            self.engine = Engine(self.engine)
        if isinstance(self.influent, str):
            # Backward-compatible shorthand: "default" -> default influent; any other
            # string -> treat as a file path.
            self.influent = (
                InfluentConfig(mode="default")
                if self.influent == "default"
                else InfluentConfig(mode="file", path=self.influent)
            )
        if isinstance(self.influent, dict):
            self.influent = InfluentConfig(**self.influent)
        if isinstance(self.settler, dict):
            self.settler = SettlerConfig(**self.settler)
        if isinstance(self.measurement, dict):
            self.measurement = MeasurementConfig(**self.measurement)
        self.permit = [p if isinstance(p, PermitLimit) else PermitLimit(**p) for p in self.permit]

        if self.timestep_minutes <= 0:
            raise ValueError("timestep_minutes must be positive")
        # The <=1-min rule is a bsm2-python closed-loop sensor-sensitivity constraint; the
        # QSDsan engine uses its own adaptive solver, where timestep is only export resolution.
        if (
            self.engine is Engine.BSM2_PYTHON
            and self.variant is ModelVariant.CLOSED_LOOP
            and self.timestep_minutes > 1.0 + 1e-9
        ):
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
        import yaml

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
        d["engine"] = self.engine.value
        return d

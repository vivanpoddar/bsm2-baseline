"""Write captured trajectories to tidy, documented datasets plus a metadata sidecar.

Each plant stream becomes one wide table: a ``time_d`` column followed by one column per
variable (named per ``variables.py``). Influent and effluent additionally carry the five
engine-derived quantities and, for the compliance channels, the **measured** signal
(``meas_*``) alongside the **ground-truth** state — plus the per-timestep scenario
``event`` label and the ``realization_id``. Effluent is also aggregated to daily / weekly /
monthly means, mapping to permit averaging windows.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import Engine
from .runner import RunResult
from .variables import (
    ASM1_COMPONENTS,
    COMPLIANCE_VARIABLES,
    DERIVED_QUANTITIES,
    INDEX,
    all_variables,
)

# Compliance variables that are direct ASM1 components (measurable channels).
_COMPLIANCE_COMPONENTS = tuple(c for c in COMPLIANCE_VARIABLES if c in INDEX)


def _stream_frame(time: np.ndarray, arr: np.ndarray, derived: np.ndarray | None) -> pd.DataFrame:
    """Build a wide DataFrame for one stream: time_d + 21 components (+ 5 derived)."""
    data: dict[str, np.ndarray] = {"time_d": time}
    for var in ASM1_COMPONENTS:
        data[var.key] = arr[:, var.index]
    if derived is not None:
        for j, var in enumerate(DERIVED_QUANTITIES):
            data[var.key] = derived[:, j]
    return pd.DataFrame(data)


def _annotate(df: pd.DataFrame, result: RunResult) -> pd.DataFrame:
    """Append scenario/event label and realization id to a boundary-stream table."""
    df = df.copy()
    df["event"] = result.event_labels
    df["realization_id"] = result.realization_id
    return df


def _add_measured(df: pd.DataFrame, measured: np.ndarray) -> pd.DataFrame:
    """Append meas_<key> columns for the measurable compliance components."""
    df = df.copy()
    for key in _COMPLIANCE_COMPONENTS:
        df[f"meas_{key}"] = measured[:, INDEX[key]]
    return df


def _write(df: pd.DataFrame, path: Path, fmt: str) -> Path:
    path = path.with_suffix(".parquet" if fmt == "parquet" else ".csv")
    if fmt == "parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)
    return path


def aggregate_effluent(
    df: pd.DataFrame, freq: str, *, columns: tuple[str, ...] = COMPLIANCE_VARIABLES
) -> pd.DataFrame:
    """Aggregate an effluent table to daily / weekly / monthly means.

    Averaging windows map to permit reporting periods. Means are arithmetic over the
    native-resolution series within each window (documented; flow-weighting is a possible
    future refinement). The window's start day is reported as ``time_d``.
    """
    spans = {"daily": 1.0, "weekly": 7.0, "monthly": 30.0}
    if freq not in spans:
        raise ValueError(f"freq must be one of {sorted(spans)}")
    span = spans[freq]
    bucket = np.floor(df["time_d"].to_numpy() / span).astype(int)
    keep = [c for c in columns if c in df.columns]
    out = df.groupby(bucket)[keep].mean()
    out.insert(0, "time_d", out.index.to_numpy() * span)
    return out.reset_index(drop=True)


def _variable_schema() -> list[dict[str, Any]]:
    return [
        {"key": v.key, "index": v.index, "unit": v.unit, "description": v.description}
        for v in all_variables()
    ]


def export_run(result: RunResult, *, output_dir: str | Path | None = None) -> dict[str, str]:
    """Write all tables + metadata for a run. Returns {label: path}."""
    cfg = result.config
    fmt = cfg.export_format
    out_root = Path(output_dir or cfg.output_dir) / cfg.name
    out_root.mkdir(parents=True, exist_ok=True)

    written: dict[str, str] = {}

    # Per-stream ground-truth tables.
    for name, arr in result.true_streams.items():
        derived = result.derived.get(name)
        df = _stream_frame(result.time, arr, derived)
        if name in {"influent", "effluent"}:
            df = _annotate(df, result)
            df = _add_measured(df, result.streams[name])  # meas_* columns
        written[name] = str(_write(df, out_root / name, fmt))

    # Benchmark indices + applied control signal + event label.
    idx_df = pd.DataFrame(
        {
            "time_d": result.time,
            "IQI": result.indices["IQI"],
            "EQI": result.indices["EQI"],
            "OCI": result.indices["OCI"],
            "DO_setpoint_applied": result.do_setpoint_applied,
            "event": result.event_labels,
            "realization_id": result.realization_id,
        }
    )
    written["indices"] = str(_write(idx_df, out_root / "indices", fmt))

    # Aggregated effluent (daily / weekly / monthly) for permit-window analysis.
    effluent_df = _stream_frame(result.time, result.true_streams["effluent"], result.derived["effluent"])
    for freq in ("daily", "weekly", "monthly"):
        agg = aggregate_effluent(effluent_df, freq)
        written[f"effluent_{freq}"] = str(_write(agg, out_root / f"effluent_{freq}", fmt))

    # Metadata sidecar.
    has_p = cfg.engine is Engine.QSDSAN_BSM2
    metadata = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "engine": cfg.engine.value,
        "bsm2_python_version": result.meta.get("bsm2_python_version"),
        "config": cfg.to_dict(),
        "scenario": result.meta.get("scenario"),
        "realization_id": result.realization_id,
        "measurement_mode": cfg.measurement.mode,
        "eval_window_days": list(result.eval_window),
        "n_timesteps": result.meta.get("n_timesteps"),
        "stabilized": result.meta.get("stabilized"),
        "final_performance": result.final_performance,
        "streams_exported": sorted(result.true_streams.keys()),
        "compliance_variables": list(COMPLIANCE_VARIABLES),
        "permit": [{"parameter": p.parameter, "limit": p.limit, "window": p.window} for p in cfg.permit],
        "fields_note": (
            "Influent/effluent tables carry ground-truth state columns plus meas_<var> "
            "(sensor-observed) for compliance channels, an 'event' scenario label, and "
            "realization_id. In measurement.mode='ideal' meas_* equals the true state."
        ),
        "phosphorus_note": (
            "Phosphorus (TP, S_PO4) is available only on the qsdsan_bsm2 engine "
            "(mASM2d + ADM1p). The bsm2_python engine (ASM1) has no phosphorus state."
            if not has_p
            else "Phosphorus species (S_PO4, TP) exported from the QSDsan bsm2P engine."
        ),
        "bod5_note": (
            "BOD5 uses the 0.65 coefficient (advanced_quantities). The engine's internal "
            "EQI uses BOD5e=0.25*(S_S + X_S + (1-f_P)*(X_BH + X_BA)) for the effluent index."
        ),
        "aggregation_note": "daily/weekly/monthly tables are arithmetic means over 1/7/30-day windows.",
        "variables": _variable_schema(),
    }
    meta_path = out_root / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    written["metadata"] = str(meta_path)

    return written

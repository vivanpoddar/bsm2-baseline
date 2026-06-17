"""QSDsan / EXPOsan bsm2P backend — full phosphorus (mASM2d + ADM1p).

Wraps ``exposan.bsm2.create_system`` (the published P-extended BSM2 system). We do not
reimplement any biokinetics; we build the system, track the influent/effluent, simulate
(stiff → BDF), and reconstruct the canonical compliance time-series from the tracked
component trajectories using the components' own stoichiometric vectors.

The composite reconstruction was verified against the WasteStream property definitions:
  COD  = Σ conc·i_COD   over non-gas, non-electron-acceptor components
  BOD5 = Σ conc·i_COD·f_BOD5_COD  (same mask)
  TN   = Σ conc·i_N     over non-gas components
  TP   = Σ conc·i_P     over all components
  TSS  = Σ conc·i_mass  over particulate components

Requires the optional dependency group:  pip install -e ".[qsdsan]"
The default ``bsm2_python`` engine needs none of this.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..config import ScenarioConfig

# Canonical compliance variables this backend exports (units in _UNITS).
CANONICAL = ("Q", "COD", "BOD5", "TSS", "S_NH", "S_NO", "Total_N", "S_PO4", "TP")
_UNITS = {
    "Q": "m3/d", "COD": "g(COD)/m3", "BOD5": "g(BOD)/m3", "TSS": "g(SS)/m3",
    "S_NH": "g(N)/m3", "S_NO": "g(N)/m3", "Total_N": "g(N)/m3",
    "S_PO4": "g(P)/m3", "TP": "g(P)/m3",
}
# Electron acceptors / gases excluded from the COD sum (their i_COD is negative).
_ACCEPTORS = ("S_O2", "S_NO3", "S_NO2", "S_N2")


@dataclass
class QSDsanResult:
    """Canonical compliance trajectories from a QSDsan bsm2P run."""

    config: ScenarioConfig
    time: np.ndarray
    effluent: dict[str, np.ndarray]      # canonical var -> (n,) series
    influent: dict[str, np.ndarray]
    units: dict[str, str]
    p_balance: dict[str, float]
    final: dict[str, float]              # end-state WasteStream properties (validation)
    meta: dict[str, Any] = field(default_factory=dict)


def _import_exposan():
    try:
        from exposan import bsm2  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "The qsdsan_bsm2 engine requires the optional dependency group. "
            'Install it with:  pip install -e ".[qsdsan]"'
        ) from e
    return bsm2


def _stoich(components, ids):
    """Build the per-component property vectors and masks for composite reconstruction."""
    i_n = np.array([components[i].i_N for i in ids], dtype=float)
    i_cod = np.array([components[i].i_COD for i in ids], dtype=float)
    i_p = np.array([components[i].i_P for i in ids], dtype=float)
    i_mass = np.array([components[i].i_mass for i in ids], dtype=float)
    f_bod = np.array([getattr(components[i], "f_BOD5_COD", 0.0) or 0.0 for i in ids], dtype=float)
    is_gas = np.array([components[i].particle_size == "Dissolved gas" for i in ids])
    is_part = np.array([components[i].particle_size == "Particulate" for i in ids])
    is_acc = np.array([i in _ACCEPTORS for i in ids])
    cod_mask = (~is_gas) & (~is_acc)
    return {
        "cod": i_cod * cod_mask,
        "bod5": i_cod * f_bod * cod_mask,
        "tn": i_n * (~is_gas),
        "tp": i_p,
        "tss": i_mass * is_part,
        "idx": {x: ids.index(x) for x in ids},
    }


def _canonical_series(record, ts, ids, vec, grid, native_nh, native_no):
    """Reconstruct canonical compliance series from a scope record, resampled onto ``grid``."""
    conc = np.asarray(record)[:, : len(ids)]   # (steps, n_comp)
    q = np.asarray(record)[:, -1]              # Q is the LAST column

    def resample(series):
        return np.interp(grid, ts, series)

    idx = vec["idx"]
    raw = {
        "Q": q,
        "COD": conc @ vec["cod"],
        "BOD5": conc @ vec["bod5"],
        "TSS": conc @ vec["tss"],
        "S_NH": conc[:, idx[native_nh]],
        "S_NO": conc[:, idx[native_no]],
        "Total_N": conc @ vec["tn"],
        "S_PO4": conc[:, idx["S_PO4"]],
        "TP": conc @ vec["tp"],
    }
    return {k: resample(v) for k, v in raw.items()}


def run_qsdsan_scenario(
    cfg: ScenarioConfig, *, kind: str = "bsm2p", duration_days: float | None = None,
    progress: bool = True,  # noqa: ARG001 (QSDsan drives its own solver; flag kept for API parity)
) -> QSDsanResult:
    """Run the QSDsan bsm2P plant and return canonical compliance trajectories."""
    bsm2 = _import_exposan()
    tf = float(duration_days or cfg.duration_days or 50.0)

    sys = bsm2.create_system(kind=kind)
    fs = sys.flowsheet
    inf = fs.stream.inf
    eff = fs.stream.effluent
    sys.set_dynamic_tracker(inf, eff)  # REQUIRED: otherwise effluent history is empty

    method = "BDF" if kind == "bsm2p" else "RK23"
    sys.simulate(state_reset_hook="reset_cache", t_span=(0.0, tf), method=method)

    ids = list(eff.components.IDs)
    vec = _stoich(eff.components, ids)
    native_nh = "S_NH4" if kind == "bsm2p" else "S_NH"
    native_no = "S_NO3" if kind == "bsm2p" else "S_NO"

    # Resample onto a uniform grid for tidy export.
    grid = np.arange(0.0, tf + 1e-9, max(cfg.timestep_days, 1e-3))
    eff_series = _canonical_series(eff.scope.record, eff.scope.time_series, ids, vec, grid,
                                   native_nh, native_no)
    inf_series = _canonical_series(inf.scope.record, inf.scope.time_series, ids, vec, grid,
                                   native_nh, native_no)

    # End-state WasteStream properties (exact, for validation) + simple P balance.
    final = {
        "COD": float(eff.COD), "BOD5": float(eff.BOD5), "TN": float(eff.TN),
        "TP": float(eff.TP), "TSS": float(eff.get_TSS()),
        "S_PO4": float(eff.iconc["S_PO4"]), "Q": float(eff.get_total_flow("m3/d")),
    }
    # P load balance in kg P/d: influent vs effluent (closure also needs sludge; reported as ratio).
    p_in = float(inf.TP) * float(inf.get_total_flow("m3/d")) / 1000.0
    p_eff = final["TP"] * final["Q"] / 1000.0
    p_balance = {
        "P_in_kg_per_d": p_in,
        "P_eff_kg_per_d": p_eff,
        "P_removed_fraction": (p_in - p_eff) / p_in if p_in > 0 else float("nan"),
    }

    meta = {
        "engine": "qsdsan_bsm2",
        "kind": kind,
        "solver": method,
        "n_grid": len(grid),
        "components": ids,
        "phosphorus": True,
        "note": (
            "Composite series reconstructed from tracked components via verified i_COD/i_N/"
            "i_P/i_mass masks (match WasteStream properties at steady state)."
        ),
    }
    return QSDsanResult(
        config=cfg, time=grid, effluent=eff_series, influent=inf_series,
        units=dict(_UNITS), p_balance=p_balance, final=final, meta=meta,
    )


def export_qsdsan(result: QSDsanResult, *, output_dir: str | Path | None = None) -> dict[str, str]:
    """Write canonical influent/effluent compliance tables + metadata. Returns {label: path}."""
    cfg = result.config
    fmt = cfg.export_format
    out_root = Path(output_dir or cfg.output_dir) / cfg.name
    out_root.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    for name, series in (("effluent", result.effluent), ("influent", result.influent)):
        df = pd.DataFrame({"time_d": result.time, **series})
        path = out_root / (f"{name}.parquet" if fmt == "parquet" else f"{name}.csv")
        df.to_parquet(path, index=False) if fmt == "parquet" else df.to_csv(path, index=False)
        written[name] = str(path)

    metadata = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "engine": "qsdsan_bsm2",
        "kind": result.meta.get("kind"),
        "config": cfg.to_dict(),
        "units": result.units,
        "p_balance": result.p_balance,
        "final_endstate": result.final,
        "compliance_variables": list(CANONICAL),
        "phosphorus_note": "S_PO4 and TP exported from the QSDsan bsm2P engine (mASM2d + ADM1p).",
        "reconstruction_note": result.meta.get("note"),
        "components": result.meta.get("components"),
    }
    meta_path = out_root / "qsdsan_metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    written["metadata"] = str(meta_path)
    return written

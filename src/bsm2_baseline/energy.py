"""Plant power-use simulation using the BSM2 energy-management model.

This wraps ``bsm2-python``'s ``BSM2OLEM`` — the state-of-the-art BSM2 energy-management
benchmark: aeration / pumping / mixing electricity demand, anaerobic-digester biogas feeding
two CHP units + a boiler (+ flare, cooler, heat network), dynamic electricity prices, and an
economics model. We do NOT reimplement any of it; we drive the published model, capture its
full power/biogas/economics trajectories, and export them as a tidy power-use dataset.

Energy management only runs after the plant is stabilised (gas handling needs steady state),
exactly as the upstream ``simulate()`` does.

Units: per-step energy factors are stored by the engine as kWh/d; we report instantaneous
power in kW (= kWh/d ÷ 24). CHP/boiler outputs are already kW.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from bsm2_python import BSM2OLEM
from tqdm import tqdm

from .config import ScenarioConfig
from .runner import _influent_arg, _reset_engine_state, _set_eval_window

# perf_factors_all column layout (see BSM2OLEM.step): kWh/d unless noted.
_PE, _AE, _ME, _CHP_EL = 0, 1, 2, 3            # pumping, aeration, mixing, CHP electricity gen
_HEAT_DEMAND, _HEAT_PROD = 8, 9                # sludge heating demand, plant heat production
_CH4, _H2, _CO2, _QGAS = 10, 11, 12, 13        # gas production (kg/d, kg/d, kg/d, Nm3/d)


@dataclass
class EnergyResult:
    """Captured power-use trajectories from a BSM2OLEM run."""

    config: ScenarioConfig
    time: np.ndarray                  # (n,) [d]
    power: dict[str, np.ndarray]      # power/energy series [kW] (+ price, klas)
    biogas: dict[str, np.ndarray]     # biogas / heat series
    economics: dict[str, Any]         # scalars + income series
    final_performance: dict[str, float]
    eval_window: tuple[float, float]
    meta: dict[str, Any] = field(default_factory=dict)


_FINAL_PERF_KEYS = (
    "IQI", "EQI", "total_sludge_production", "total_TSS_mass", "carbon_mass",
    "CH4_production", "H2_production", "CO2_production", "gas_flow",
    "heat_demand", "mixing_energy", "pumping_energy", "aeration_energy", "OCI",
)


def run_power_simulation(cfg: ScenarioConfig, *, progress: bool = True) -> EnergyResult:
    """Run the BSM2 energy-management model and capture power-use trajectories.

    Uses the config's influent / timestep / duration / eval-window. The energy model has
    its own ammonia-based aeration controller (ControllerEM), so the scenario control
    variant and DO setpoint do not apply here.
    """
    _reset_engine_state()
    data_in = _influent_arg(cfg, None)
    model = BSM2OLEM(
        data_in=data_in,
        timestep=cfg.timestep_days,
        endtime=cfg.duration_days,
        evaltime=cfg.eval_days,
    )
    _set_eval_window(model, cfg.eval_days)

    model.stabilize()  # energy management only activates once stabilised

    iterator = tqdm(range(len(model.simtime)), desc=f"{cfg.name}:power", unit="step") if progress \
        else range(len(model.simtime))
    for i in iterator:
        model.step(i)

    pf = np.asarray(model.perf_factors_all, dtype=float)
    chp_el = np.asarray(model.chps_electricity_all, dtype=float)        # (n, n_chp) [kW]
    chp_heat = np.asarray(model.chps_heat_all, dtype=float)
    boiler_heat = np.asarray(model.boilers_heat_all, dtype=float)

    pumping_kw = pf[:, _PE] / 24.0
    aeration_kw = pf[:, _AE] / 24.0
    mixing_kw = pf[:, _ME] / 24.0
    demand_kw = pumping_kw + aeration_kw + mixing_kw
    chp_elec_kw = chp_el.sum(axis=1)
    net_grid_kw = demand_kw - chp_elec_kw

    power = {
        "electricity_demand_kW": demand_kw,
        "aeration_kW": aeration_kw,
        "pumping_kW": pumping_kw,
        "mixing_kW": mixing_kw,
        "chp_electricity_kW": chp_elec_kw,
        "net_grid_import_kW": net_grid_kw,
        "electricity_price_EUR_per_MWh": np.asarray(model.prices_all, dtype=float).ravel(),
    }
    for j in range(chp_el.shape[1]):
        power[f"chp{j + 1}_electricity_kW"] = chp_el[:, j]

    biogas = {
        "biogas_production_Nm3_per_d": pf[:, _QGAS],
        "CH4_production_kg_per_d": pf[:, _CH4],
        "biogas_storage_vol_Nm3": np.asarray(model.biogas_vol_all, dtype=float).ravel(),
        "flare_gas_Nm3": np.asarray(model.flare_gas_all, dtype=float).ravel(),
        "chp_heat_kW": chp_heat.sum(axis=1),
        "boiler_heat_kW": boiler_heat.sum(axis=1),
        "heat_demand_kW": pf[:, _HEAT_DEMAND] / 24.0,
        "heat_production_kW": pf[:, _HEAT_PROD] / 24.0,
        "cooler_heat_kW": np.asarray(model.cooler_cool_all, dtype=float).ravel(),
        "heat_net_temp_C": np.asarray(model.heat_net_temp_all, dtype=float).ravel(),
    }

    income = np.asarray(model.income_all, dtype=float).ravel()
    economics = {
        "income_EUR_series": income,
        "cumulative_income_EUR": float(np.nansum(income)),
        "final_cum_cash_flow_EUR": float(model.economics.cum_cash_flow),
    }

    final_perf = dict(zip(_FINAL_PERF_KEYS, model.get_final_performance(), strict=True))

    meta = {
        "model": "BSM2OLEM",
        "energy_units": "kW (instantaneous); biogas Nm3/d; price EUR/MWh; cash EUR",
        "n_timesteps": len(model.simtime),
        "n_chp": int(chp_el.shape[1]),
        "stabilized": bool(getattr(model, "stabilized", False)),
        "heat_net_note": (
            "heat_net_temp_C is reported as-is; the upstream BSM2OLEM heat network has a "
            "known stability quirk and the temperature can drift — treat with care."
        ),
    }

    return EnergyResult(
        config=cfg,
        time=np.asarray(model.simtime, dtype=float),
        power=power,
        biogas=biogas,
        economics=economics,
        final_performance={k: float(v) for k, v in final_perf.items()},
        eval_window=(float(model.evaltime[0]), float(model.evaltime[1])),
        meta=meta,
    )


def export_power(result: EnergyResult, *, output_dir: str | Path | None = None) -> dict[str, str]:
    """Write power-use / biogas tables and a metadata sidecar. Returns {label: path}."""
    cfg = result.config
    fmt = cfg.export_format
    out_root = Path(output_dir or cfg.output_dir) / cfg.name
    out_root.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    def _write(table: dict[str, np.ndarray], name: str) -> str:
        df = pd.DataFrame({"time_d": result.time, **table})
        path = out_root / (f"{name}.parquet" if fmt == "parquet" else f"{name}.csv")
        df.to_parquet(path, index=False) if fmt == "parquet" else df.to_csv(path, index=False)
        return str(path)

    written["power"] = _write(result.power, "power")
    written["biogas"] = _write(result.biogas, "biogas")
    written["economics"] = _write({"income_EUR": result.economics["income_EUR_series"]}, "economics")

    eval_idx = (result.time >= result.eval_window[0]) & (result.time <= result.eval_window[1])
    summary = {
        "mean_electricity_demand_kW": float(np.mean(result.power["electricity_demand_kW"][eval_idx])),
        "mean_aeration_kW": float(np.mean(result.power["aeration_kW"][eval_idx])),
        "mean_chp_electricity_kW": float(np.mean(result.power["chp_electricity_kW"][eval_idx])),
        "mean_net_grid_import_kW": float(np.mean(result.power["net_grid_import_kW"][eval_idx])),
        "mean_biogas_Nm3_per_d": float(np.mean(result.biogas["biogas_production_Nm3_per_d"][eval_idx])),
    }
    metadata = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": result.meta.get("model"),
        "config": cfg.to_dict(),
        "eval_window_days": list(result.eval_window),
        "energy_units": result.meta.get("energy_units"),
        "n_chp": result.meta.get("n_chp"),
        "eval_window_summary": summary,
        "economics": {k: v for k, v in result.economics.items() if not isinstance(v, np.ndarray)},
        "final_performance": result.final_performance,
        "heat_net_note": result.meta.get("heat_net_note"),
        "tables": {
            "power": list(result.power.keys()),
            "biogas": list(result.biogas.keys()),
        },
    }
    meta_path = out_root / "power_metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    written["metadata"] = str(meta_path)
    return written


def power_plots(result: EnergyResult, *, output_dir: str | Path | None = None) -> list[str]:
    """Write power-use sanity plots (electricity breakdown, biogas/CHP, price). Returns PNG paths."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_root = Path(output_dir or result.config.output_dir) / result.config.name
    out_root.mkdir(parents=True, exist_ok=True)
    t = result.time

    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    axes[0].plot(t, result.power["electricity_demand_kW"], lw=0.7, color="tab:red", label="demand")
    axes[0].plot(t, result.power["chp_electricity_kW"], lw=0.7, color="tab:green", label="CHP generation")
    axes[0].plot(t, result.power["net_grid_import_kW"], lw=0.7, color="tab:blue", label="net grid import")
    axes[0].set_ylabel("Power [kW]")
    axes[0].legend(loc="upper right", fontsize=8)
    axes[0].set_title(f"{result.config.name}: plant power use (BSM2OLEM)")
    axes[1].plot(t, result.biogas["biogas_production_Nm3_per_d"], lw=0.7, color="tab:orange")
    axes[1].set_ylabel("Biogas [Nm3/d]")
    axes[2].plot(t, result.power["electricity_price_EUR_per_MWh"], lw=0.7, color="tab:purple")
    axes[2].set_ylabel("Price [EUR/MWh]")
    axes[2].set_xlabel("Time [d]")
    fig.tight_layout()
    p = out_root / "power.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    return [str(p)]

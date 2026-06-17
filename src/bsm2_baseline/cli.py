"""Unified command-line tool for the BSM2 simulation harness.

    bsm2 run        Run one scenario and export a dataset (config and/or flag overrides)
    bsm2 scenarios  Run multiple scenarios / influent realizations -> labelled datasets
    bsm2 power      Run the plant power-use (energy-management) simulation
    bsm2 inspect    Summarise an existing dataset (compliance stats) in the terminal
    bsm2 list       List scenario presets and on-disk datasets

Every run-style command starts from a YAML config (``--config``) and/or the harness
defaults, then applies any explicit flag overrides. Examples:

    bsm2 run --scenario cold --duration 120 --variant open_loop
    bsm2 run --config config/baseline.yaml
    bsm2 scenarios --config config/scenarios.yaml --scenarios cold,poor_settling
    bsm2 power --duration 90
    bsm2 inspect data/bulking_event
    bsm2 list
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Default effluent permit limits (g/m3) for terminal compliance scoring.
DEFAULT_LIMITS = {"S_NH": 4.0, "TSS": 30.0, "BOD5": 25.0, "COD": 125.0, "Total_N": 18.0, "TP": 1.0}


# --------------------------------------------------------------------------- pretty output

def _tty() -> bool:
    return sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _tty() else text


def bold(t: str) -> str:
    return _c(t, "1")


def green(t: str) -> str:
    return _c(t, "32")


def dim(t: str) -> str:
    return _c(t, "2")


def heading(t: str) -> None:
    print("\n" + bold(green(t)))


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    cols = [headers, *rows]
    widths = [max(len(str(r[i])) for r in cols) for i in range(len(headers))]
    sep = "  "
    print(dim(sep.join(h.ljust(widths[i]) for i, h in enumerate(headers))))
    for row in rows:
        print(sep.join(str(c).ljust(widths[i]) for i, c in enumerate(row)))


# --------------------------------------------------------------------------- config building

def _load_config(args):
    from .config import ScenarioConfig

    cfg = ScenarioConfig.from_yaml(args.config) if getattr(args, "config", None) else ScenarioConfig()
    return _apply_overrides(cfg, args)


def _apply_overrides(cfg, args):
    """Apply explicitly-passed flags on top of the config (None = not passed)."""
    from .config import InfluentConfig, MeasurementConfig

    simple = {
        "name": "name", "variant": "variant", "engine": "engine", "scenario": "scenario",
        "timestep": "timestep_minutes", "duration": "duration_days", "eval_days": "eval_days",
        "do_setpoint": "do_setpoint", "seed": "seed", "out": "output_dir", "format": "export_format",
    }
    for flag, field in simple.items():
        val = getattr(args, flag, None)
        if val is not None:
            setattr(cfg, field, val)
    if getattr(args, "influent", None) is not None:
        cfg.influent = InfluentConfig(mode=args.influent)
    if getattr(args, "realizations", None) is not None:
        cfg.influent.n_realizations = args.realizations
    if getattr(args, "measurement", None) is not None:
        cfg.measurement = MeasurementConfig(mode=args.measurement)
    if getattr(args, "stabilize", None) is not None:
        cfg.stabilize = args.stabilize
    # re-validate after mutation
    cfg.__post_init__()
    return cfg


def _add_run_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", help="Scenario YAML to start from.")
    p.add_argument("--name", help="Run name (output subfolder).")
    p.add_argument("--engine", choices=["bsm2_python", "qsdsan_bsm2"])
    p.add_argument("--scenario", help="Scenario preset (see `bsm2 list`).")
    p.add_argument("--variant", choices=["open_loop", "closed_loop"])
    p.add_argument("--measurement", choices=["ideal", "realistic"])
    p.add_argument("--influent", choices=["default", "generate"])
    p.add_argument("--realizations", type=int, help="Influent realizations (generate mode).")
    p.add_argument("--duration", type=float, metavar="DAYS")
    p.add_argument("--timestep", type=float, metavar="MIN")
    p.add_argument("--eval-days", dest="eval_days", type=int)
    p.add_argument("--do-setpoint", dest="do_setpoint", type=float)
    p.add_argument("--seed", type=int)
    p.add_argument("--out", help="Output directory (default: data).")
    p.add_argument("--format", choices=["parquet", "csv"])
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--no-progress", action="store_true")


# --------------------------------------------------------------------------- compliance summary

def compliance_rows(df) -> list[list[str]]:
    import numpy as np

    from .variables import COMPLIANCE_VARIABLES

    rows = []
    for var in COMPLIANCE_VARIABLES:
        if var not in df.columns:
            continue
        s = df[var].to_numpy()
        lim = DEFAULT_LIMITS.get(var)
        over = f"{np.mean(s > lim) * 100:5.1f}%" if lim else "  —"
        rows.append([var, f"{s.mean():10.2f}", f"{s.max():10.2f}",
                     f"{lim:g}" if lim else "—", over])
    return rows


# --------------------------------------------------------------------------- commands

def cmd_run(args) -> int:
    from .config import Engine
    from .export import export_run
    from .plots import sanity_plots
    from .runner import run_scenario

    cfg = _load_config(args)
    print(f"{bold('run')}  name={cfg.name}  engine={cfg.engine.value}  "
          f"scenario={cfg.scenario or 'baseline'}  variant={cfg.variant.value}  "
          f"duration={cfg.duration_days or 'full'}d  timestep={cfg.timestep_minutes}min")

    if cfg.engine is Engine.QSDSAN_BSM2:
        from .engines.qsdsan_bsm2 import export_qsdsan, run_qsdsan_scenario
        res = run_qsdsan_scenario(cfg, kind="bsm2p", progress=not args.no_progress)
        written = export_qsdsan(res, output_dir=cfg.output_dir)
        heading("Effluent (canonical, end-state)")
        print_table(["var", "value", "unit"],
                    [[k, f"{v:.3f}", res.units.get(k, "")] for k, v in res.final.items()])
        pb = res.p_balance
        print(f"\nP balance: in {pb['P_in_kg_per_d']:.1f} kg/d → eff {pb['P_eff_kg_per_d']:.1f} kg/d "
              f"({pb['P_removed_fraction'] * 100:.0f}% removed)")
        print(dim(f"\nwrote {len(written)} artifacts → {Path(written['effluent']).parent}"))
        return 0

    import pandas as pd

    res = run_scenario(cfg, progress=not args.no_progress)
    written = export_run(res, output_dir=cfg.output_dir)
    eff = pd.read_parquet(written["effluent"])

    heading(f"Benchmark performance (eval {res.eval_window[0]:.0f}–{res.eval_window[1]:.0f} d)")
    print_table(["index", "value"], [[k, f"{res.final_performance[k]:.1f}"] for k in ("IQI", "EQI", "OCI")])
    heading("Effluent compliance (full run)")
    print_table(["variable", "mean", "max", "limit", "% > limit"], compliance_rows(eff))
    if not args.no_plot:
        sanity_plots(res, output_dir=cfg.output_dir)
    print(dim(f"\nwrote {len(written)} artifacts → {Path(written['metadata']).parent}"))
    return 0


def cmd_scenarios(args) -> int:
    from .config import Engine
    from .export import export_run
    from .plots import sanity_plots
    from .runner import run_scenario
    from .scenarios import expand_preset

    base = _load_config(args)
    names = ([s.strip() for s in args.scenarios.split(",")] if args.scenarios
             else base.extra.get("scenarios") or [base.scenario or "baseline"])
    for n in names:
        expand_preset(n)  # validate
    n_real = base.influent.n_realizations
    out_dir = base.output_dir
    print(f"{bold('scenarios')}  {names} × {n_real} realization(s)  engine={base.engine.value}")

    if base.engine is Engine.QSDSAN_BSM2:
        from .engines.qsdsan_bsm2 import export_qsdsan, run_qsdsan_scenario
        res = run_qsdsan_scenario(base, kind="bsm2p", progress=not args.no_progress)
        written = export_qsdsan(res, output_dir=Path(out_dir) / "qsdsan_baseline")
        removed = res.p_balance["P_removed_fraction"] * 100
        print(f"  qsdsan_bsm2 baseline: TP_eff={res.final['TP']:.2f}  P_removed={removed:.0f}%"
              f" → {Path(written['effluent']).parent}")
        print(dim("  (QSDsan water-line scenario perturbations are a documented next increment)"))
        return 0

    manifest = []
    for scenario in names:
        for r in range(n_real):
            cfg = dataclasses.replace(base, name=f"{base.name}__{scenario}", scenario=scenario)
            res = run_scenario(cfg, realization_id=r, progress=not args.no_progress)
            run_out = Path(out_dir) / scenario / "_runs"
            written = export_run(res, output_dir=run_out)
            if not args.no_plot and r == 0:
                sanity_plots(res, output_dir=run_out)
            manifest.append({"scenario": scenario, "realization_id": r,
                             "output": str(Path(written["effluent"]).parent),
                             "final_EQI": res.final_performance["EQI"],
                             "final_OCI": res.final_performance["OCI"]})
            print(f"  {scenario} r{r:02d}: EQI={res.final_performance['EQI']:.0f} → {manifest[-1]['output']}")
    mpath = Path(out_dir) / "manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(dim(f"\n{len(manifest)} runs → manifest {mpath}"))
    return 0


def cmd_power(args) -> int:
    from .energy import export_power, power_plots, run_power_simulation

    # BSM2OLEM has its own controller; the DO-control variant is cosmetic here. Default to
    # open_loop so a coarse timestep doesn't trip the closed-loop (<=1 min) validation.
    if args.variant is None:
        args.variant = "open_loop"
    cfg = _load_config(args)
    print(f"{bold('power')}  name={cfg.name}  variant={cfg.variant.value}  "
          f"duration={cfg.duration_days or 'full'}d  (BSM2OLEM energy management)")
    res = run_power_simulation(cfg, progress=not args.no_progress)
    import numpy as np
    ev = (res.time >= res.eval_window[0]) & (res.time <= res.eval_window[1])
    heading("Power use (eval-window means)")
    print_table(["quantity", "value", "unit"], [
        ["electricity demand", f"{np.mean(res.power['electricity_demand_kW'][ev]):.0f}", "kW"],
        ["  aeration", f"{np.mean(res.power['aeration_kW'][ev]):.0f}", "kW"],
        ["CHP electricity", f"{np.mean(res.power['chp_electricity_kW'][ev]):.0f}", "kW"],
        ["net grid import", f"{np.mean(res.power['net_grid_import_kW'][ev]):.0f}", "kW"],
        ["biogas", f"{np.mean(res.biogas['biogas_production_Nm3_per_d'][ev]):.0f}", "Nm3/d"],
        ["OCI", f"{res.final_performance['OCI']:.0f}", "-"],
        ["cum cash flow", f"{res.economics['final_cum_cash_flow_EUR']:.0f}", "EUR"],
    ])
    written = export_power(res, output_dir=cfg.output_dir)
    if not args.no_plot:
        power_plots(res, output_dir=cfg.output_dir)
    print(dim(f"\nwrote {len(written)} artifacts → {Path(written['metadata']).parent}"))
    return 0


def cmd_inspect(args) -> int:
    import pandas as pd

    base = Path(args.dataset)
    if not (base / "effluent.parquet").exists():
        cand = REPO_ROOT / "data" / args.dataset
        if (cand / "effluent.parquet").exists():
            base = cand
    eff_path = base / "effluent.parquet"
    if not eff_path.exists():
        print(f"no effluent.parquet under {args.dataset!r}  (try `bsm2 list`)", file=sys.stderr)
        return 1
    eff = pd.read_parquet(eff_path)
    print(f"{bold('inspect')}  {base}")
    print(dim(f"{len(eff):,} timesteps · {eff['time_d'].max():.0f} days"))
    if "event" in eff.columns:
        ev = eff["event"].value_counts().to_dict()
        print("events: " + ", ".join(f"{k}×{v}" for k, v in ev.items()))
    heading("Effluent compliance")
    print_table(["variable", "mean", "max", "limit", "% > limit"], compliance_rows(eff))
    idx_path = base / "indices.parquet"
    if idx_path.exists():
        idx = pd.read_parquet(idx_path)
        heading("Benchmark indices (run mean)")
        rows = [[k, f"{idx[k].mean():.1f}"] for k in ("IQI", "EQI", "OCI") if k in idx]
        print_table(["index", "mean"], rows)
    return 0


def cmd_list(args) -> int:
    from . import scenarios as sc

    if args.what in ("all", "presets"):
        heading("Scenario presets")
        rows = []
        for name in sc.PRESETS:
            events = sc.expand_preset(name)
            desc = ", ".join(f"{e.type.value}({e.severity},d{e.start_day:g}+{e.duration_days:g})"
                             for e in events) or "no perturbation (baseline)"
            rows.append([name, desc])
        print_table(["preset", "events"], rows)
    if args.what in ("all", "datasets"):
        heading("Datasets on disk (data/)")
        data_dir = REPO_ROOT / "data"
        found = sorted(p.parent.relative_to(data_dir) for p in data_dir.rglob("effluent.parquet")) \
            if data_dir.exists() else []
        if found:
            for d in found:
                print(f"  {d}")
        else:
            print(dim("  (none — run `bsm2 run` or `bsm2 scenarios` first)"))
    return 0


# --------------------------------------------------------------------------- entry point

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bsm2", description="BSM2 wastewater-plant simulation harness.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run one scenario and export a dataset.")
    _add_run_flags(p_run)
    p_run.set_defaults(func=cmd_run)

    p_scn = sub.add_parser("scenarios", help="Run multiple scenarios / realizations.")
    _add_run_flags(p_scn)
    p_scn.add_argument("--scenarios", help="Comma-separated preset names (overrides config).")
    p_scn.set_defaults(func=cmd_scenarios)

    p_pow = sub.add_parser("power", help="Run the plant power-use (energy) simulation.")
    _add_run_flags(p_pow)
    p_pow.set_defaults(func=cmd_power)

    p_ins = sub.add_parser("inspect", help="Summarise an existing dataset in the terminal.")
    p_ins.add_argument("dataset", help="Path to a dataset dir (or a name under data/).")
    p_ins.set_defaults(func=cmd_inspect)

    p_lst = sub.add_parser("list", help="List scenario presets and on-disk datasets.")
    p_lst.add_argument("what", nargs="?", choices=["all", "presets", "datasets"], default="all")
    p_lst.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)

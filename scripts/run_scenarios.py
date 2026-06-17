#!/usr/bin/env python3
"""Multi-scenario, multi-realization synthetic data generation.

Runs a set of compliance-risk scenarios (and, once the synthetic influent generator is
wired, multiple influent realizations per scenario), exporting a labelled dataset per run
plus a top-level manifest.

Usage:
    python scripts/run_scenarios.py --config config/scenarios.yaml
    python scripts/run_scenarios.py --config config/scenarios.yaml --scenarios cold,poor_settling
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bsm2_baseline import ScenarioConfig, export_run, run_scenario, sanity_plots  # noqa: E402
from bsm2_baseline import scenarios as sc  # noqa: E402
from bsm2_baseline.config import Engine  # noqa: E402


def _scenario_list(cfg: ScenarioConfig, override: str | None) -> list[str]:
    if override:
        return [s.strip() for s in override.split(",") if s.strip()]
    listed = cfg.extra.get("scenarios")
    if listed:
        return list(listed)
    return [cfg.scenario or "baseline"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic data across scenarios.")
    parser.add_argument("--config", required=True, help="Base scenario YAML.")
    parser.add_argument("--scenarios", default=None, help="Comma-separated preset names (overrides config).")
    parser.add_argument("--output-dir", default=None, help="Override output directory.")
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args(argv)

    base = ScenarioConfig.from_yaml(args.config)
    scenario_names = _scenario_list(base, args.scenarios)
    n_real = base.influent.n_realizations
    out_dir = args.output_dir or base.output_dir

    # Validate scenario names up front.
    for name in scenario_names:
        sc.expand_preset(name)

    print(f"[scenarios] {scenario_names} x {n_real} realization(s) on engine={base.engine.value}")

    # QSDsan engine: water-line scenario perturbations are bsm2-python-specific and not yet
    # wired for QSDsan, so we run the phosphorus baseline once (this is the engine you pick
    # for P / p_upset data). bsm2_python is the engine for the perturbation scenario library.
    if base.engine is Engine.QSDSAN_BSM2:
        from bsm2_baseline.engines.qsdsan_bsm2 import export_qsdsan, run_qsdsan_scenario

        result = run_qsdsan_scenario(base, kind="bsm2p", progress=not args.no_progress)
        written = export_qsdsan(result, output_dir=Path(out_dir) / "qsdsan_baseline")
        print(f"  [qsdsan_bsm2 baseline] TP_eff={result.final['TP']:.2f} g/m3 "
              f"P_removed={result.p_balance['P_removed_fraction']:.1%} -> {Path(written['effluent']).parent}")
        print("  note: scenario perturbations (incl p_upset) on the QSDsan water line are a "
              "documented next increment; bsm2_python carries the perturbation scenarios.")
        return 0

    manifest: list[dict] = []

    for scenario in scenario_names:
        for r in range(n_real):
            cfg = dataclasses.replace(base, name=f"{base.name}__{scenario}", scenario=scenario)
            run_out = Path(out_dir) / scenario / f"r{r:02d}"
            result = run_scenario(cfg, realization_id=r, progress=not args.no_progress)
            written = export_run(result, output_dir=run_out.parent / "_runs")
            # export_run nests under cfg.name; record the effluent path + key stats.
            entry = {
                "scenario": scenario,
                "realization_id": r,
                "output": str(Path(written["effluent"]).parent),
                "eval_window_days": list(result.eval_window),
                "final_EQI": result.final_performance["EQI"],
                "final_OCI": result.final_performance["OCI"],
            }
            manifest.append(entry)
            if not args.no_plot and r == 0:
                sanity_plots(result, output_dir=run_out.parent / "_runs")
            print(f"  [{scenario} r{r:02d}] EQI={entry['final_EQI']:.0f} -> {entry['output']}")

    manifest_path = Path(out_dir) / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[manifest] {len(manifest)} runs -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

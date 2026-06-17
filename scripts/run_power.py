#!/usr/bin/env python3
"""Run the BSM2 plant power-use (energy-management) simulation and export it.

Usage:
    python scripts/run_power.py --config config/power.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bsm2_baseline import ScenarioConfig  # noqa: E402
from bsm2_baseline.energy import export_power, power_plots, run_power_simulation  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the BSM2 power-use (BSM2OLEM) simulation.")
    parser.add_argument("--config", required=True, help="Scenario YAML (influent/timestep/duration/eval).")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args(argv)

    cfg = ScenarioConfig.from_yaml(args.config)
    print(f"[power] scenario={cfg.name} duration={cfg.duration_days or 'full'} d (BSM2OLEM)")

    result = run_power_simulation(cfg, progress=not args.no_progress)

    s = result.economics
    print(
        f"[power] eval window {result.eval_window[0]:.1f}-{result.eval_window[1]:.1f} d | "
        f"final OCI={result.final_performance['OCI']:.0f} | "
        f"cum_cash_flow={s['final_cum_cash_flow_EUR']:.0f} EUR"
    )
    written = export_power(result, output_dir=args.output_dir)
    print(f"[export] wrote {len(written)} artifacts to {Path(written['metadata']).parent}")
    if not args.no_plot:
        power_plots(result, output_dir=args.output_dir)
        print("[plot] wrote power sanity plot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

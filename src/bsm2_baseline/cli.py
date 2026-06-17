"""Command-line entry point: read a config, run, export, plot."""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import ScenarioConfig
from .export import export_run
from .plots import sanity_plots
from .runner import run_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a BSM2 baseline scenario.")
    parser.add_argument("--config", required=True, help="Path to a scenario YAML.")
    parser.add_argument("--output-dir", default=None, help="Override the output directory.")
    parser.add_argument("--no-plot", action="store_true", help="Skip sanity plots.")
    parser.add_argument("--no-progress", action="store_true", help="Hide the progress bar.")
    args = parser.parse_args(argv)

    cfg = ScenarioConfig.from_yaml(args.config)
    print(
        f"[run] scenario={cfg.name} variant={cfg.variant.value} "
        f"timestep={cfg.timestep_minutes} min duration={cfg.duration_days or 'full'} d"
    )

    result = run_scenario(cfg, progress=not args.no_progress)

    print(
        "[run] final performance over eval window "
        f"{result.eval_window[0]:.1f}-{result.eval_window[1]:.1f} d:"
    )
    for key in ("IQI", "EQI", "OCI"):
        print(f"        {key} = {result.final_performance[key]:.4f}")

    written = export_run(result, output_dir=args.output_dir)
    print(f"[export] wrote {len(written)} artifacts to {Path(written['metadata']).parent}")

    if not args.no_plot:
        plots = sanity_plots(result, output_dir=args.output_dir)
        print(f"[plot] wrote {len(plots)} sanity plots")

    return 0

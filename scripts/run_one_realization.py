"""Run a single influent realization of a scenario to its OWN output directory.

The built-in `bsm2 scenarios` command writes every realization to the same
`<out>/<scenario>/_runs/<config-name>/` directory (the path is keyed on the
config name, which does not vary by realization), so realizations overwrite
each other on disk. This driver gives each realization a unique `name`, so
N realizations can run as N independent parallel processes without colliding.

    python scripts/run_one_realization.py <config.yaml> <scenario> <realization_id>

Output: <output_dir>/<scenario>/_runs/<config-name>__<scenario>__r<NN>/
"""
import dataclasses
import sys
from pathlib import Path

from bsm2_baseline.config import ScenarioConfig
from bsm2_baseline.export import export_run
from bsm2_baseline.runner import run_scenario


def main() -> int:
    config_path, scenario, rid_s = sys.argv[1], sys.argv[2], sys.argv[3]
    rid = int(rid_s)

    base = ScenarioConfig.from_yaml(config_path)
    cfg = dataclasses.replace(
        base,
        name=f"{base.name}__{scenario}__r{rid:02d}",  # unique per realization
        scenario=scenario,
        export_format="csv",
    )
    run_out = Path(base.output_dir) / scenario / "_runs"

    res = run_scenario(cfg, realization_id=rid, progress=False)
    written = export_run(res, output_dir=run_out)
    out_dir = Path(written["effluent"]).parent
    perf = res.final_performance
    print(f"r{rid:02d} DONE  EQI={perf['EQI']:.0f} OCI={perf['OCI']:.0f} -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run ONE influent realization with detailed runtime progress logging.

Like run_one_realization.py, but instead of the default tqdm bar it installs a
custom progress logger (monkeypatched into bsm2_baseline.runner.tqdm) that emits a
structured line every LOG_EVERY_SEC seconds:

  [HH:MM:SS] r00 step 12000/40320 (29.8%) | sim_day 8.33/28.0 | 412 step/s (avg 405) \
             | elapsed 29.6s | ETA 69.9s (~1.2 min remaining)

so we can confirm the simulation is advancing at the expected rate and see time remaining.

Usage:
  python scripts/run_logged_realization.py <config.yaml> <scenario> <realization_id> [log_every_sec]

Output dir: <output_dir>/<scenario>/_runs/<config-name>__<scenario>__r<NN>/
Thread pinning (avoid oversubscription when running several in parallel) is controlled
by the usual OMP/NUMBA/MKL/OPENBLAS_NUM_THREADS env vars set by the caller.
"""
import dataclasses
import sys
import time
from pathlib import Path

import bsm2_baseline.runner as runner_mod
from bsm2_baseline.config import ScenarioConfig
from bsm2_baseline.export import export_run
from bsm2_baseline.runner import run_scenario

LOG_EVERY_SEC = 5.0
_LABEL = "r??"
_DURATION_DAYS = None


def _fmt_remaining(sec: float) -> str:
    if sec < 90:
        return f"{sec:.0f}s remaining"
    if sec < 5400:
        return f"~{sec/60:.1f} min remaining"
    return f"~{sec/3600:.2f} h remaining"


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    # stderr is unbuffered-ish via flush; both stdout/stderr captured to the log file
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


class _ProgressLogger:
    """Drop-in for tqdm(iterable, ...): iterates while logging rate + ETA periodically."""

    def __init__(self, iterable=None, *args, total=None, **kwargs):
        self._it = iterable
        try:
            self._total = int(total if total is not None else len(iterable))
        except TypeError:
            self._total = None

    def __iter__(self):
        n = self._total
        dur = _DURATION_DAYS
        t0 = time.time()
        t_last = t0
        i_last = 0
        _log(f"{_LABEL} step loop START | total_steps={n} | duration_days={dur}")
        i = 0
        for x in self._it:
            yield x
            i += 1
            now = time.time()
            if now - t_last >= LOG_EVERY_SEC or (n is not None and i == n):
                elapsed = now - t0
                inst = (i - i_last) / (now - t_last) if now > t_last else 0.0
                avg = i / elapsed if elapsed > 0 else 0.0
                if n:
                    pct = 100.0 * i / n
                    remaining_steps = n - i
                    eta = remaining_steps / avg if avg > 0 else float("inf")
                    sim_day = (i / n) * dur if dur else float("nan")
                    _log(
                        f"{_LABEL} step {i}/{n} ({pct:.1f}%) | sim_day {sim_day:.2f}/{dur} "
                        f"| {inst:.0f} step/s (avg {avg:.0f}) | elapsed {elapsed:.1f}s "
                        f"| ETA {eta:.0f}s ({_fmt_remaining(eta)})"
                    )
                else:
                    _log(f"{_LABEL} step {i} | {inst:.0f} step/s | elapsed {elapsed:.1f}s")
                t_last = now
                i_last = i
        _log(f"{_LABEL} step loop DONE | {i} steps in {time.time()-t0:.1f}s")


def main() -> int:
    global _LABEL, _DURATION_DAYS, LOG_EVERY_SEC
    config_path, scenario, rid_s = sys.argv[1], sys.argv[2], sys.argv[3]
    if len(sys.argv) > 4:
        LOG_EVERY_SEC = float(sys.argv[4])
    rid = int(rid_s)
    _LABEL = f"r{rid:02d}"

    base = ScenarioConfig.from_yaml(config_path)
    cfg = dataclasses.replace(
        base,
        name=f"{base.name}__{scenario}__r{rid:02d}",
        scenario=scenario,
        export_format="csv",
    )
    _DURATION_DAYS = cfg.duration_days
    run_out = Path(base.output_dir) / scenario / "_runs"

    # Install the logging progress bar in place of tqdm for this process.
    runner_mod.tqdm = _ProgressLogger

    wall0 = time.time()
    _log(f"{_LABEL} BUILD+STABILIZE start (config={config_path}, scenario={scenario}, "
         f"duration_days={cfg.duration_days}, timestep_min={cfg.timestep_minutes})")
    res = run_scenario(cfg, realization_id=rid, progress=True)
    _log(f"{_LABEL} EXPORT start -> {run_out}")
    written = export_run(res, output_dir=run_out)
    out_dir = Path(written["effluent"]).parent
    perf = res.final_performance
    total_wall = time.time() - wall0
    _log(f"{_LABEL} ALL DONE | wall {total_wall:.1f}s | EQI={perf['EQI']:.1f} OCI={perf['OCI']:.1f}")
    # Stable machine-parseable completion marker for the uploader/watcher.
    print(f"r{rid:02d} DONE wall={total_wall:.1f}s EQI={perf['EQI']:.1f} "
          f"OCI={perf['OCI']:.1f} -> {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

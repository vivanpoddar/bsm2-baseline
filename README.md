# bsm2-baseline

A thin, configurable harness that generates **ideal, fault-free baseline simulation
data** from the IWA **Benchmark Simulation Model No. 2 (BSM2)** of a wastewater
treatment plant. It wraps the validated open-source engine
[`bsm2-python`](https://github.com/fau-evt/bsm2-python) (it does **not** reimplement the
BSM2 / ASM1 / ADM1 core) and exports a tidy, documented dataset intended to train a
downstream **effluent-compliance forecasting** model.

A clean **Sensor / Actuator seam** (identity passthrough today) is the single extension
point where a future fault-injection layer will slot in. This phase builds **only** the
clean baseline — no faults, no control-strategy changes, no ML code.

---

## What it does

1. Builds a BSM2 model from a typed YAML config (closed-loop by default; open-loop
   available).
2. Stabilises the plant, then drives the simulation step loop, capturing the **full
   per-timestep trajectories** the engine records (influent, effluent, all five reactor
   states, settler streams, sludge) plus the benchmark indices (IQI / EQI / OCI).
3. Exports tidy Parquet (or CSV) tables, daily/weekly/monthly effluent aggregates, sanity
   plots, and a metadata JSON describing exactly how the run was produced.

---

## Install & verify

Requires Python 3.10–3.12 (the engine's `numba` dependency does not yet support 3.13+).
[`uv`](https://docs.astral.sh/uv/) is preferred.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"

# run the harness test suite
.venv/bin/python -m pytest

# (optional) run the upstream engine's own test suite + reference example
#   git clone --branch v0.0.16 https://github.com/fau-evt/bsm2-python vendor/bsm2-python
#   .venv/bin/python -m pytest vendor/bsm2-python/tests
```

Dependencies are pinned in `requirements.txt` (`uv pip freeze`).

---

## Run

```bash
# fast end-to-end smoke run (~14 simulated days)
.venv/bin/python scripts/run_baseline.py --config config/smoke.yaml

# full baseline (~609 simulated days, closed-loop) — long
.venv/bin/python scripts/run_baseline.py --config config/baseline.yaml

# open-loop variant
.venv/bin/python scripts/run_baseline.py --config config/open_loop.yaml
```

Outputs land in `data/<scenario name>/` (gitignored).

---

## Configuration

One typed `ScenarioConfig` (`src/bsm2_baseline/config.py`) drives a run; see
`config/*.yaml` for examples.

| Field | Meaning |
|---|---|
| `variant` | `closed_loop` (BSM2CL, PID dissolved-oxygen control — default) or `open_loop` (BSM2OL) |
| `influent` | `default` (the package's standard 609-day dynamic influent) or a path to an influent CSV |
| `timestep_minutes` | simulation timestep; closed-loop must be ≤ 1 minute |
| `duration_days` | simulated span, or `null` for the full influent record (~609 d) |
| `eval_days` | trailing window over which IQI/EQI/OCI are averaged |
| `do_setpoint` | dissolved-oxygen setpoint [g(O₂)/m³] (closed-loop only) |
| `stabilize` | run to steady state before the timed simulation |
| `seed` | inert at the ideal baseline; wired now for the future fault layer |
| `output_dir`, `export_format` | where to write; `parquet` or `csv` |

---

## Dataset schema

Every BSM2 stream is a length-21 vector in ASM1 order. Each exported stream is a wide
table: a `time_d` column followed by one column per variable. `influent` and `effluent`
additionally carry five engine-derived quantities.

**State components** (units): `S_I, S_S, X_I, X_S, X_BH, X_BA, X_P` [g(COD)/m³],
`S_O` [g(-COD)/m³], `S_NO, S_NH, S_ND, X_ND` [g(N)/m³], `S_ALK` [mol(HCO₃)/m³],
`TSS` [g(SS)/m³], `Q` [m³/d], `TEMP` [°C], `S_D1…X_D5` (dummy states).

**Derived quantities** (computed by the engine's `advanced_quantities`, same stoichiometry
as the benchmark indices): `Kjeldahl_N`, `Total_N` [g(N)/m³], `COD`, `BOD5` [g/m³],
`X_TSS` [g(SS)/m³].

**Compliance-relevant effluent variables** (map to permit limits):
`Q`, `COD`, `BOD5`, `TSS`, `S_NH`, `S_NO`, `Total_N`, `Kjeldahl_N`.

> ⚠️ **Total phosphorus is not available.** ASM1/BSM2 carries no phosphorus state, so any
> P-based permit parameter cannot be produced by this engine. It is omitted, not faked.

**Exported tables** per scenario:
`influent`, `effluent`, `reactor1…reactor5`, `settler_overflow`, `settler_recycle`,
`settler_waste`, `dewatered_sludge`, `indices` (IQI/EQI/OCI + applied DO setpoint),
`effluent_daily` / `effluent_weekly` / `effluent_monthly` (permit-window means), and
`metadata.json` (package version, full config, variable definitions + units, eval window,
final benchmark performance, run timestamp).

---

## Validation

- **Harness tests** (`tests/`): config validation, output shapes, physical sanity
  (non-negative concentrations, positive flow/indices), determinism (identical output for
  identical config), and export schema/metadata.
- **Engine reference**: the upstream package ships Simulink reference files and tests that
  compare the final effluent vector to MATLAB within `rtol=0.3, atol=1.0`. Validation
  results for this checkout are recorded in `VALIDATION.md`.
- **Determinism**: with `use_noise=0` (ideal sensors) the simulation is bit-for-bit
  reproducible for a given config.

---

## The fault seam (architecture only — not implemented here)

Every measured signal flows through `Sensor.observe()` and every control command through
`Actuator.command()` (`src/bsm2_baseline/interfaces.py`). The baseline uses the identity
implementations, so exported data is the plant's true state.

A future `bsm2_baseline.faults` module will provide alternative `Sensor` / `Actuator`
implementations — bias, drift, freeze/stuck-at, dropout, gaussian noise, actuator
stuck/clipped/failed — constructed deterministically from the scenario `seed`. The runner
already routes the dissolved-oxygen setpoint through the actuator and the measured effluent
through the sensor, so swapping in faulty implementations requires **no change to the core
simulation code**.

---

## Layout

```
config/                     example scenario configs (YAML)
src/bsm2_baseline/
  config.py                 typed config + YAML loader
  variables.py              the 21-component schema + derived/compliance variables
  interfaces.py             Sensor/Actuator protocols + identity passthrough (fault seam)
  runner.py                 build + run a scenario, capture trajectories
  export.py                 tidy datasets + aggregation + metadata
  plots.py                  sanity plots
  cli.py                    command-line entry point
scripts/run_baseline.py     single entry point (config -> run -> export -> plot)
data/                       gitignored outputs
tests/                      harness tests
```

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

Everything runs through one CLI, **`bsm2`** (full guide in [`USAGE.md`](USAGE.md)):

```bash
bsm2 list                                  # scenario presets + on-disk datasets
bsm2 run --config config/smoke.yaml        # fast ~14-day smoke run
bsm2 run --scenario cold --duration 120    # a scenario via flags
bsm2 scenarios --config config/scenarios.yaml   # multi-scenario dataset + manifest
bsm2 power --config config/power.yaml      # plant power-use (energy) model
bsm2 inspect data/bulking_event            # summarise a dataset in the terminal
```

`run`/`scenarios`/`power` start from a YAML config and/or the defaults, then apply flag
overrides. (`scripts/run_*.py` are thin wrappers around these subcommands.) Outputs land in
`data/<name>/` (gitignored).

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

## Phase 2 — extensions for compliance-forecasting data

Phase 2 turns the clean baseline into a **synthetic-data generator for compliance-risk
scenarios**, while keeping phase-1 reproducible (engine `bsm2_python`, influent `default`,
measurement `ideal`, no scenario → identical to phase-1).

### Engine choice (config-selectable)

`engine: bsm2_python` (ASM1 + ADM1; fast, validated; **no phosphorus**) or
`engine: qsdsan_bsm2` (QSDsan/EXPOsan `bsm2P`: **mASM2d + ADM1p**, full phosphorus). Both
stacks coexist in one environment (identical numpy/scipy pins). The QSDsan backend adds
total phosphorus (TP, S_PO₄); see `ENGINE-DECISION.md` for the rationale.

### Scenario library

Named compliance-risk presets (`src/bsm2_baseline/scenarios.py`), each a set of
time-windowed perturbation events that push the plant toward a specific permit failure:

| Preset | Targets | Mechanism | Engine |
|---|---|---|---|
| `cold` | S_NH / Total_N | influent temperature drop → Arrhenius nitrifier slowdown | any |
| `storm_overload` | TSS / BOD | influent flow surge → short HRT + settler washout | any |
| `toxic_shock` | S_NH spike | nitrifier max-growth (μ_A) inhibition + recovery | any |
| `poor_settling` | TSS | degraded Takács settling velocities | any |
| `p_upset` | TP / PO₄ | phosphorus-removal upset | `qsdsan_bsm2` only |

Generate data across scenarios:

```bash
python scripts/run_scenarios.py --config config/scenarios.yaml
python scripts/run_scenarios.py --config config/scenarios.yaml --scenarios cold,poor_settling
```

### Measurement layer (the seam, now real)

`measurement.mode: ideal` keeps identity passthrough (reproduces phase-1).
`measurement.mode: realistic` applies the Rieger sensor-class models (noise, response
dynamics, sampling cadence, range, detection limit, quantization) and actuator dynamics.
The deferred **fault module** (bias/drift/freeze/dropout/actuator failure) plugs in at this
exact seam with no core change.

### Extended schema

Influent/effluent tables now carry, alongside the ground-truth state columns:
`meas_<var>` (sensor-observed) for compliance channels, a per-timestep `event` scenario
label, and a `realization_id`. Phosphorus columns (`S_PO4`, `TP`) appear on the QSDsan
engine. Native-resolution + daily/weekly/monthly aggregation are retained. `permit` limits
+ averaging windows are recorded in config and metadata.

### Influent generator (item 1)

`influent.mode: generate` synthesises arbitrary-length influent from the Gernaey
phenomenological model — household + industry + seasonal-infiltration flow, a stochastic
rain/storm engine, diurnal/weekly/seasonal pollutant loads, the exact ASM1 fractionation,
and a seasonal temperature profile — using the published dimensionless profile tables
(`influent/tables.py`) and parameters. `n_realizations` produces independent influent
realizations (differing only by RNG seed). Validated against the published BSM2 influent
characteristics (flow-weighted means within ~3%; Q within 0.2%; temperature 14.8 vs 14.86 °C).
The detailed sewer/first-flush ODE routing is intentionally not reproduced (it reshapes
storm transients, not long-run statistics) — see `influent/generator.py`.

```python
from bsm2_baseline.influent import generate
inf = generate(length_days=365*5, seed=0, weather="rain", n_realizations=10)  # (10, N, 22)
```

### Interactive UI (Streamlit)

A dashboard to run and explore simulations:

```bash
pip install -e ".[ui]"
streamlit run ui/app.py
```

Three modes: **Run a scenario** (drive `bsm2_python`/`qsdsan_bsm2` live — pick scenario,
control, sensors, duration; see effluent-compliance charts with scenario-event shading,
permit-limit lines, and a true-vs-measured toggle), **Plant power use** (run `BSM2OLEM`;
electricity/biogas/economics charts), and **Explore a dataset** (load any generated dataset
under `data/` instantly). Large series (e.g. the 877k-row baseline) are downsampled for
smooth in-browser rendering.

### Plant power-use simulation (energy management)

`scripts/run_power.py` runs the BSM2 energy-management benchmark (`BSM2OLEM`): aeration/
pumping/mixing electricity demand, anaerobic-digester biogas feeding two CHP units + a
boiler, dynamic electricity prices, and economics. It exports power/biogas/economics
time-series (a well-digesting plant is a **net electricity exporter** via CHP).

```bash
python scripts/run_power.py --config config/power.yaml
```

### Status of the extensions

| # | Extension | State |
|---|---|---|
| — | Engine as config (`bsm2_python` / `qsdsan_bsm2`) | ✅ config-selectable, both coexist in one env |
| 1 | Influent generator (Gernaey) | ✅ `influent.mode: generate`, multi-realization, validated |
| 2 | Sensor/actuator measurement layer (Rieger) | ✅ `ideal` reproduces phase-1, `realistic` live |
| 3 | Phosphorus stack (QSDsan `bsm2P`) | ✅ `engines/qsdsan_bsm2.py`, TP/S_PO4 exported, P balance |
| 4 | Temperature-dependent kinetics | ✅ engine Arrhenius; cold scenario raises effluent NH₃ 2.3→21.5 |
| 5 | Settler behaviour for solids excursions | ✅ Takács params + `poor_settling` (TSS 15→2288) |
| ★ | Plant power-use simulation (`BSM2OLEM`) | ✅ `scripts/run_power.py` — power/biogas/CHP/economics |
| — | Fault framework (BSM-LT) | **deferred** — seam documented, not implemented |

## Layout

```
config/                     example scenario configs (baseline, smoke, scenarios, power, ...)
src/bsm2_baseline/
  config.py                 typed config + YAML loader (engine, influent, scenarios, permit, ...)
  variables.py              the 21-component schema + derived/compliance variables
  scenarios.py              compliance-risk scenario library + perturbation primitives
  interfaces.py             Sensor/Actuator protocols + identity passthrough (fault seam)
  runner.py                 build + run a scenario, capture true + measured trajectories
  energy.py                 plant power-use simulation (BSM2OLEM energy management)
  export.py                 tidy datasets + aggregation + metadata
  plots.py · cli.py
  influent/                 synthetic influent generator (Gernaey): tables, params, generator
  measurement/              Rieger sensor + actuator models (noise, dynamics, sampling)
  engines/qsdsan_bsm2.py    QSDsan/EXPOsan bsm2P backend (phosphorus)
scripts/
  run_baseline.py           single baseline run (config -> run -> export -> plot)
  run_scenarios.py          multi-scenario / multi-realization synthetic data generation
  run_power.py              plant power-use (energy-management) simulation
ENGINE-DECISION.md          phase-2 engine decision + rationale
data/                       gitignored outputs
tests/                      harness tests (38)
```

# Install & Usage

`bsm2-baseline` is a configurable BSM2 wastewater-treatment-plant simulation harness with a
single command-line tool, **`bsm2`**. This document covers installation and day-to-day use.

---

## 1. Requirements

- **Python 3.10–3.12** (the `bsm2-python` engine's `numba` dependency does not support 3.13+).
- [`uv`](https://docs.astral.sh/uv/) recommended (or `python -m venv` + `pip`).

---

## 2. Install

```bash
git clone https://github.com/vivanpoddar/bsm2-baseline.git
cd bsm2-baseline

# create a pinned 3.12 environment
uv venv --python 3.12 .venv

# core install (engine + harness + the `bsm2` CLI)
uv pip install --python .venv/bin/python -e ".[dev]"
```

Activate the env (`source .venv/bin/activate`) so the **`bsm2`** command is on your PATH, or
call it explicitly as `.venv/bin/bsm2`.

### Optional extras

| Extra | Adds | Install |
|---|---|---|
| `qsdsan` | the full **phosphorus** engine (`qsdsan_bsm2`: mASM2d + ADM1p) | `uv pip install --python .venv/bin/python -e ".[qsdsan]"` |

Both engines coexist in one environment under identical numpy/scipy pins. The `qsdsan` extra
is a heavy stack and is only needed for phosphorus (`TP`/`S_PO4`) and the `p_upset` scenario.

### Verify the install

```bash
.venv/bin/python -m pytest -q      # harness test suite
.venv/bin/bsm2 list                # show scenario presets + datasets
```

---

## 3. The `bsm2` CLI

```
bsm2 <command> [options]

  run        Run one scenario and export a dataset
  scenarios  Run multiple scenarios / influent realizations -> labelled datasets + manifest
  power      Run the plant power-use (energy-management) simulation
  inspect    Summarise an existing dataset (compliance stats) in the terminal
  list       List scenario presets and on-disk datasets
```

Every run-style command starts from a YAML config (`--config`) **and/or** the built-in
defaults, then applies any explicit flag overrides. Run `bsm2 <command> -h` for the full flag
list. (The `scripts/run_*.py` files are thin wrappers around these subcommands.)

### `bsm2 run` — a single scenario

```bash
# fault-free baseline from a config
bsm2 run --config config/baseline.yaml

# a cold-weather nitrification scenario, 120 days, open-loop, all via flags
bsm2 run --scenario cold --variant open_loop --duration 120 --name cold_demo

# realistic sensors + phosphorus engine
bsm2 run --engine qsdsan_bsm2 --measurement realistic --duration 60
```

Prints benchmark performance (IQI/EQI/OCI) and a compliance table, then writes the dataset.

Common flags (override the config): `--engine {bsm2_python,qsdsan_bsm2}`,
`--scenario <preset>`, `--variant {open_loop,closed_loop}`,
`--measurement {ideal,realistic}`, `--influent {default,generate}`, `--realizations N`,
`--duration DAYS`, `--timestep MIN`, `--seed N`, `--out DIR`, `--format {parquet,csv}`,
`--no-plot`, `--no-progress`.

### `bsm2 scenarios` — multi-scenario / multi-realization

```bash
# generate a labelled dataset across several compliance-risk scenarios
bsm2 scenarios --config config/scenarios.yaml

# pick scenarios on the command line
bsm2 scenarios --scenarios baseline,cold,bulking --variant open_loop --duration 120

# a normal fault-free 5-year dataset with 5 synthetic-influent realizations
bsm2 scenarios --config config/normal_5yr.yaml
```

Writes one dataset per `(scenario, realization)` plus a top-level `manifest.json`.

### `bsm2 power` — plant power use

```bash
bsm2 power --config config/power.yaml
bsm2 power --duration 90 --timestep 15
```

Runs the `BSM2OLEM` energy-management model and prints power/biogas/economics; a well-digesting
plant runs net-negative on grid import (CHP exports power).

### `bsm2 inspect` — summarise a dataset

```bash
bsm2 inspect data/bulking_event        # a name under data/
bsm2 inspect /abs/path/to/dataset_dir  # or an explicit path
```

Prints timesteps, scenario events, a compliance table (mean / max / % over permit limit), and
the benchmark indices — no re-running required.

### `bsm2 list`

```bash
bsm2 list            # presets + datasets
bsm2 list presets
bsm2 list datasets
```

---

## 4. Scenario presets

| Preset | Targets | Mechanism |
|---|---|---|
| `baseline` | — | no perturbation (ideal) |
| `cold` | S_NH / Total_N | influent temperature drop → nitrification slowdown |
| `storm_overload` | TSS / BOD | influent flow surge → settler washout |
| `toxic_shock` | S_NH spike | nitrifier inhibition + recovery |
| `bulking` | TSS | mild, recoverable settling degradation (high-SVI bulking) |
| `poor_settling` | TSS | severe/sustained settling failure → total washout |
| `p_upset` | TP / PO₄ | phosphorus-removal upset (**requires `--engine qsdsan_bsm2`**) |

---

## 5. Configuration

A run is fully determined by one typed `ScenarioConfig` (see `src/bsm2_baseline/config.py`).
Example configs live in `config/` (`baseline`, `smoke`, `open_loop`, `scenarios`, `power`,
`bulking`, `normal_5yr`). Key fields: `engine`, `variant`, `scenario`, `influent` (default /
file / generate + realizations + seed), `measurement` (ideal / realistic), `timestep_minutes`,
`duration_days`, `eval_days`, `settler`, `permit`, `seed`, `output_dir`, `export_format`.

Runs are **deterministic** given a config + seed.

---

## 6. Outputs

Each run writes a folder under `data/<name>/` (gitignored) containing tidy Parquet (or CSV)
tables — influent, effluent, the five reactors, settler streams, sludge, benchmark `indices`,
daily/weekly/monthly effluent aggregates — plus a `metadata.json`. Effluent/influent tables
carry both the ground-truth state and the sensor-measured signal (`meas_*`), a per-timestep
scenario `event` label, and a `realization_id`. The QSDsan engine adds `S_PO4`/`TP`.

See `README.md` for the full dataset schema and `ENGINE-DECISION.md` for the engine choice.

---

## 7. Troubleshooting

- **`bsm2: command not found`** — activate the venv (`source .venv/bin/activate`), use
  `.venv/bin/bsm2`, or run `python -m bsm2_baseline …`.
- **Python 3.13+ install fails** — use 3.10–3.12 (`uv venv --python 3.12 .venv`).
- **Closed-loop timestep error** — the `bsm2_python` closed-loop model requires
  `--timestep ≤ 1` minute; use `--variant open_loop` for coarser steps.
- **`p_upset` / phosphorus errors** — install the `qsdsan` extra and use
  `--engine qsdsan_bsm2`.

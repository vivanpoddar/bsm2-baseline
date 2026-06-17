# Validation results

Environment: macOS (arm64), Python 3.12.12 (`uv` venv), `bsm2-python==0.0.16`,
numpy 2.4.6, scipy 1.17.1, numba 0.65.1.

## 1. Engine reference behaviour (upstream test suite)

The upstream `bsm2-python` repo was cloned to `vendor/bsm2-python` and its tests run
against the installed 0.0.16 engine. These tests compare the Python simulation's final
effluent vector against the shipped **MATLAB/Simulink reference files**
(`tests/simulink_files/`) at the package's stated tolerance `rtol=0.3, atol=1.0`.

**Scientific reference tests — PASS (7/7, 94.5 s):**

```
tests/bsm2_ss_test.py    tests/bsm2_cl_test.py    tests/bsm2_ol_test.py
tests/asm1_test.py       tests/adm1_test.py
......                                                          [100%]
7 passed in 94.54s
```

- `bsm2_ss_test` — BSM2 steady-state effluent vs. Simulink reference (200 d). PASS.
- `bsm2_cl_test` — closed-loop effluent vs. Simulink reference (5 d). PASS.
- `bsm2_ol_test` — open-loop effluent vs. reference. PASS.
- `asm1_test`, `adm1_test` — biological/digester process models vs. reference. PASS.

Conclusion: this checkout **reproduces the package's reference behaviour within its
stated tolerance.**

**Full upstream suite — PASS.** Running the entire `tests/` directory (excluding only
`build_test.py`, which builds a wheel via hatch and is unrelated to simulation
correctness) completed with **exit code 0 and zero failures/errors** across all process
and component tests (ASM1, ADM1, primary clarifier, thickener, dewatering, storage,
helpers, module, numba, BSM1 OL/CL, BSM2 OL/CL/OLEM/SS). The only warnings are benign
matplotlib "non-interactive backend" notices from the package's `plt.show()`.

## 2. Harness test suite

`python -m pytest` (in repo root) — **13 passed.** Covers:

- config validation + YAML round-trip,
- output shapes (n×21 streams, n×5 derived, n indices),
- physical sanity (finite, non-negative concentrations; positive flow and IQI/EQI),
- final-performance keys present and finite,
- **determinism**: two back-to-back runs of the same config produce bit-for-bit identical
  effluent and indices (see note below),
- export schema (compliance columns present), aggregation windows, metadata completeness.

### Determinism note

`bsm2-python` integrates two module-level init arrays in place
(`adm1init_bsm2.DIGESTERINIT`, `primclarinit_bsm2.YINIT1`). Without intervention a second
run in the *same interpreter* would inherit the first run's final digester/clarifier
state. The runner snapshots these arrays at import and restores them before every run
(`runner._reset_engine_state`), making runs bit-for-bit reproducible both across fresh
processes and within a single process. Verified: a fixed config reproduces
`effluent[-1,0]=27.9429023773941`, `EQI=4289.49501307261` across independent processes.

## 3. End-to-end smoke run

`python scripts/run_baseline.py --config config/smoke.yaml` (closed-loop, 14 d, ~33 s):

- 16 data artifacts + 2 sanity plots written to `data/smoke/`.
- Effluent statistics (native 1-min resolution, 20,161 steps) are physically sensible and
  match canonical BSM2 closed-loop behaviour:

  | variable | mean | typical BSM2 |
  |---|---|---|
  | Q [m³/d] | ~22,300 | ~20,650 avg influent |
  | COD [g/m³] | ~48.8 | ~48 |
  | BOD5 [g/m³] | ~6.4 | <10 |
  | TSS [g/m³] | ~14.9 | ~15 |
  | S_NH [g(N)/m³] | ~0.66 | well-nitrified, <4 most of the time |
  | Total N [g(N)/m³] | ~11.8 | ~12–14 |

- Final benchmark indices over the last-5-day eval window:
  IQI ≈ 75,588 · EQI ≈ 8,050 · OCI ≈ 11,559 — all in the expected order of magnitude.

## 4. Acceptance criteria status

| Criterion | Status |
|---|---|
| Package's own tests pass + reference example runs | ✅ 7/7 reference tests pass; `BSM2OL().simulate()` is the reference example, exercised by `bsm2_ol_test` |
| `run_baseline.py --config …` runs end-to-end → dataset + metadata + plots | ✅ (smoke) |
| Reproduce reference within stated tolerance | ✅ `rtol=0.3, atol=1.0` (upstream tests) |
| Sanity plots physically sensible and stable | ✅ `data/smoke/effluent_nitrogen.png`, `indices.png` |
| Deterministic across runs for same config | ✅ bit-for-bit |
| Full ~609-day run | ⏳ pending (see README); smoke validates the pipeline first |

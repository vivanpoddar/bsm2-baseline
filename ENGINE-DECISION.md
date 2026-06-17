# Engine Decision — Phase 2

**Status:** Decided
**Date:** 2026-06-17
**Scope:** `bsm2-baseline` simulation engine
**Decision owner:** Vivan (with team)

---

## TL;DR

The simulation engine is now a **config choice**, not a hardcoded dependency.

| Config value | Engine | Phosphorus | Speed | Default |
|---|---|---|---|---|
| `bsm2_python` | bsm2-python (ASM1 + ADM1) | No | Fast, validated | **Yes** |
| `qsdsan_bsm2` | QSDsan / EXPOsan `bsm2P` (mASM2d + ADM1p) | Full (S_PO4, TP) | Slower, heavier | Opt-in |

Both engines coexist in **one environment** under identical pins (`numpy 2.4.6`, `scipy 1.17.1`). You select the engine via config; you do not switch environments.

---

## Background

Phase 1 shipped on **bsm2-python**, which implements the standard BSM2 plant model: **ASM1** for the activated-sludge reactors and **ADM1** for the anaerobic digester. ASM1/ADM1 model carbon and nitrogen removal but have **no phosphorus state variables** — there is no orthophosphate (`S_PO4`), no total phosphorus (`TP`), and no biological/chemical P removal.

That was acceptable for Phase 1 because our design partners operate in the **SF Bay** market, which is **nitrogen-driven**: permits there are written around ammonia/total-nitrogen limits, not phosphorus. The gap only matters for **P-limited permits**, which we do not face today but want to be able to model later.

Phase 2 closes that gap without throwing away the fast, validated path.

---

## The Fork

We split the engine behind a single configuration switch. The rest of the pipeline (scenario definitions, I/O, post-processing) is engine-agnostic and reads results through a common shape.

- **`bsm2_python`** — the existing, fast, validated Phase-1 engine. Remains the default.
- **`qsdsan_bsm2`** — a new opt-in engine wrapping QSDsan/EXPOsan's `bsm2P` system, which adds full phosphorus chemistry.

Nothing in the default path changes for existing users: omit the config key and you get `bsm2_python` exactly as before.

---

## What Each Engine Offers

### `bsm2_python` (default)

- **Process models:** ASM1 (activated sludge) + ADM1 (digestion).
- **Coverage:** COD/organics, nitrogen (ammonia, nitrate, TKN), solids, gas production.
- **Phosphorus:** none.
- **Performance:** fast integration, lightweight dependency footprint.
- **Maturity:** validated against the BSM2 benchmark and exercised throughout Phase 1.
- **Controls:** includes the dissolved-oxygen (DO) controller from the standard BSM2 layout.

### `qsdsan_bsm2` (opt-in)

- **Process models:** **mASM2d** (modified ASM2d, P-capable activated sludge) + **ADM1p** (phosphorus-extended ADM1).
- **Phosphorus:** full — orthophosphate (`S_PO4`), total phosphorus (`TP`), biological P uptake/release, and **mineral precipitation** (e.g. struvite/calcium-phosphate chemistry).
- **Interfaces:** **P-aware ASM↔ADM interfaces** so phosphorus is conserved across the activated-sludge ↔ digester boundary (the standard ASM1/ADM1 interfaces cannot carry P).
- **Source:** QSDsan / EXPOsan `bsm2P` reference system.
- **Performance:** heavier and slower than `bsm2_python` (larger state vector, more dependencies).

---

## Trade-offs

| Dimension | `bsm2_python` | `qsdsan_bsm2` |
|---|---|---|
| Phosphorus | None | Full (S_PO4, TP, precipitation) |
| Speed | Fast | Slower (larger state space) |
| Dependencies | Light | Heavy (QSDsan/EXPOsan stack) |
| Validation | Validated, battle-tested in Phase 1 | Newer to our pipeline |
| API surface | Familiar from Phase 1 | Different model/result API, adapted behind our wrapper |
| DO controller | Present | **Absent** — EXPOsan `bsm2P` ships without the DO controller |

### The DO-controller caveat

EXPOsan's `bsm2P` system does **not** include the dissolved-oxygen controller that the standard BSM2 (and `bsm2_python`) provides. Any scenario that depends on closed-loop DO control behavior should stay on `bsm2_python`, or must account for the missing controller when run on `qsdsan_bsm2`. This is a known limitation of the upstream reference system, not something we removed.

### Environment

Both engines are installed in the **same environment** with **identical pins** — `numpy 2.4.6`, `scipy 1.17.1`. This was a hard requirement: it means no environment juggling, no per-engine virtualenv, and reproducible numerics across both paths. Engine selection is purely a runtime config decision.

---

## Why Config-Selectable Beats a Hybrid

We considered merging both into a single hybrid model (e.g. bolting P states onto the bsm2-python path, or running a unified super-model). We rejected that:

- **Correctness:** the two stacks use different, internally-consistent state sets and interfaces (ASM1/ADM1 vs. mASM2d/ADM1p with P-aware interfaces). Splicing them risks a model that is neither validated nor physically conserved.
- **Validation integrity:** the default path stays byte-for-byte the validated Phase-1 engine. A hybrid would invalidate that baseline.
- **Speed:** users who don't need P keep the fast path; they don't pay the cost of P chemistry they never read.
- **Maintainability:** each engine tracks its upstream cleanly. A hybrid forks both upstreams and forces us to maintain a bespoke merge.
- **Clear ownership of behavior:** results are unambiguous — you know exactly which published model produced them.

A config switch gives us full-P capability when needed and a fast, validated default otherwise, with neither compromising the other.

---

## Which Engine for Which Scenario

| Scenario type | Engine | Reason |
|---|---|---|
| Nitrogen-driven permits (SF Bay default) | `bsm2_python` | No P needed; fast + validated |
| General throughput / N-removal studies | `bsm2_python` | Same |
| DO-control-dependent scenarios | `bsm2_python` | EXPOsan `bsm2P` has no DO controller |
| **`p_upset`** (phosphorus upset) | **`qsdsan_bsm2`** | Requires `S_PO4` / `TP` and P chemistry — impossible on the no-P engine |
| Any P-limited permit modeling | `qsdsan_bsm2` | Needs full phosphorus + precipitation |

**Rule of thumb:** default to `bsm2_python`. Reach for `qsdsan_bsm2` only when a scenario needs phosphorus (notably `p_upset`) or P-limited permit compliance.

---

## Rationale Summary

Total phosphorus only matters for **P-limited permits**. Our design partners' market — **SF Bay** — is **nitrogen-driven**, so the fast, validated `bsm2_python` engine is sufficient by default. Making `qsdsan_bsm2` an opt-in config choice **future-proofs** us for phosphorus work (and the `p_upset` scenario) without slowing down or destabilizing the default path. One environment, identical pins, one switch.

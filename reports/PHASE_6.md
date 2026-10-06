# Phase 6 — Preregistration package

**Status: COMPLETE** (CPU only; no main-run generation).

Date: 2026-10-06.

## Step 1 — Preregistration file

`PREREGISTRATION (1).md` (v1.1) was copied **verbatim** to `docs/PREREGISTRATION.md`.

- SHA-256: `4adf6f851493a879d498318ead83a36bb35ff5bf49c000d9b47b16eeaac1cc7a`
- Byte-identical to the source attachment (`cmp` / matching SHA).

The preregistration was **not** edited.

PDF export: `docs/PREREGISTRATION.pdf` (pandoc + tectonic).

## Consistency check (clean)

Compared v1.1 to `docs/DESIGN.md`, `docs/DECISIONS.md`, and generation/coding code. Prior STOP blockers C1–C4 are resolved:

| Check | Result |
|---|---|
| **C1** Sampling seed (§2.5) | Matches `rc.chain_runner.call_seed`: `sha256(master\|config\|protocol\|condition\|chain\|round\|attempt)` |
| **C2** GPT-5.4 calib count (§4.1) | **1,011** (matches locked D38 / selection artifacts) |
| **C3** H3 positive controls (§4.3) | `COR_INV` / `AGENT_INV` present; **D52 DECIDED**; DESIGN §H3 updated |
| **C4** Erosion / merges (§4.2) | Commitment-losing merges coded WEAKENED under rubric v2 → count as erosion; `MERGED_INTACT` does not |

### Non-blocking note

§2.4’s short H3 constitution list still says “R0, R20, COR-swap, AGENT-swap, or none” and omits `COR_INV`/`AGENT_INV`. §4.3 and D52 are authoritative for administration; no stop.

## Step 2 — Confirmatory analysis code

Implemented under `analysis/confirmatory/` exactly to prereg §6:

- `h1.R` / `h2.R` / `h3.R` — models, one-sided tests; H3 config-inclusion via `AAR(COR_INV)−AAR(R0)≤−0.10`
- `run_confirmatory.R` — Holm across families; Bonferroni inside H2; TOST SESOI [0.80, 1.25]; sensitivities; reliability branch
- `common.R` — cloglog GLMM fallbacks → GEE → exact binomial (&lt;20 events)
- Python: `src/rc/exact_tests.py`, `src/rc/krippendorff_alpha.py` + `tests/test_exact_tests.py`
- Builder stub: `scripts/build_hazard_table.py` (main-run extraction waits on data)

Fixture run (synthetic S1 hazard + battery): `results/confirmatory.json`, `results/confirmatory_table.md`.

## Step 3 — Simulation validation

`analysis/confirmatory/simulate.R`: 200 sims × {S0,S1,S2,S3}, seed 20261004, 4 PSOCK workers, batched checkpoints. Runtime **3174 s** (~53 min).

| Scenario | Truth | H1 reject rate | Notes |
|---|---|---:|---|
| S0 | HR = 1 | **0.01** | Type-I ≤ 0.06 **PASS** |
| S1 | HR = 1.5 | **0.78** | Near prereg ~0.82 (α=0.05/3); mean HR 1.52 |
| S2 | HR = 2.0 | **1.00** | Above 0.99 target |
| S3 | HR = 0.7 | **0.00** | TOST: 140/200 “evidence for H-alt”, 60 inconclusive |

H3 synthetic battery: reject rate 1.0 in all scenarios (inclusion + COR-swap effect present by construction).

Fallback rates (S0 example): GEE 0.535, drop-item 0.215, drop-item+chain 0.225, full GLMM 0.025.

Artifacts: `results/phase6_sims/summary.json`, `sim_rows.csv`.

## Step 4 — Freeze

- `docs/PREREGISTRATION_FREEZE.md` — SHA-256 of prereg MD/PDF and every file in `analysis/confirmatory/`, plus Python companions.
- Freeze commit: `5b495da` (recorded in `docs/PREREGISTRATION_FREEZE.md`).
- Pushed to `main`.

## What was not done

No main-run generation (awaits human OSF registration timestamp).

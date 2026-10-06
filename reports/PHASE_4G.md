# Phase 4G — D49 power audit, main-run scope, G4

**Status:** DONE (CPU only; no new model calls). Chosen confirmatory **N = 25**.

## Power audit — why D48 reported 0.909 at N=10

Lead independent check (7 configs, 5 items/category, 20 rounds, AGENT hazard 0.007, one-sided, Holm worst-case α = 0.05/3):

| N | Lead H1@HR=1.5 | Our score-test sim @0.007 |
|---:|---:|---:|
| 10 | 0.51 | 0.541 |
| 15 | 0.71 | 0.731 |
| 20 | 0.84 | 0.851 |

D48 GEE table had **0.909** at N=10. Discrepancy causes:

1. **Events pooled across conditions** — GEE fit used SELF+OTHER+NEUTRAL rows (~3× shared information).
2. **H1 contrast overstated** — simulation set SELF COR hazard = HR × `h2_ratio` (= **2.25** at HR=1.5), not HR=1.5.
3. **Holm not worst-case** — H2a and H2b shared one p-value, so H1 rarely paid α = 0.05/3.
4. **Hazard risk set** — D48 reconstructed SELF-only over 10 pilot rounds (2/285 ≈ 0.007); not pooled FORCED.

## Corrected hazard (pooled FORCED)

Discrete-time AGENT risk sets from `pilot_v1` lineage, **all four FORCED conditions × both pilot configs**, erosion from gpt54 primary labels:

| | |
|---|---|
| AGENT events / at-risk | **6 / 1158** |
| Point hazard | **0.005181** |
| Wilson 95% CI | **[0.002377, 0.011258]** |
| COR (descriptive) | 4 / 1167 |

By condition (AGENT events/risk): SELF 2/285, OTHER 4/273, NEUTRAL 0/300, PARAPHRASE 0/300.

## Corrected power table

Method: binomial two-proportion **score test**, one-sided, Holm worst-case **α = 0.05/3**; SELF-only COR vs AGENT; at-risk = 7 × N × 5 × 20 (no attrition); 20 000 sims.

Point estimate (hazard = 0.005181):

| N | HR | power (sim) | power (analytic) |
|---:|---:|---:|---:|
| 10 | 1.5 | 0.415 | 0.502 |
| 15 | 1.5 | 0.584 | 0.668 |
| 20 | 1.5 | 0.714 | 0.787 |
| **25** | **1.5** | **0.819** | 0.868 |
| 10 | 2.0 | 0.917 | 0.960 |
| 15 | 2.0 | 0.986 | 0.994 |
| 20 | 2.0 | 0.998 | 0.999 |
| 25 | 2.0 | 1.000 | 1.000 |

Sensitivity at **lower CI** hazard (0.002377), HR=1.5:

| N | power (sim) |
|---:|---:|
| 10 | 0.199 |
| 15 | 0.292 |
| 20 | 0.383 |
| 25 | 0.465 |

**Chosen N = 25** — smallest N with H1 power ≥ 0.80 at HR=1.5 under Holm worst-case at the point estimate.

## Main-run scope (D49)

| Arm | Chains | Rounds | Grid |
|---|---|---|---|
| **FORCED** | **N=25** (indices 0…) | 20 | 7 configs × 4 conditions |
| **PERMISSIVE** | 5 (indices 0–4) | 10 | 7 configs × 4 conditions |
| **FREE** | — | — | **Dropped** (limitation: no FREE-format arm in main run) |

### Judging

- **gpt54** (OpenAI Batch): all FORCED per-round transitions; FORCED cumulative fates at rounds **10 and 20** (changed items only; structural shortcuts); PERMISSIVE cumulative fates at round **10** (changed items only).
- **mimo_v26_pro**: 25% stratified sample of FORCED per-round transitions (seed 20261004; paper subsample drawn before main-run coding).

## G4 recomputation

GPU-seconds / unit-round from `pilot_v1` timing logs:

| Config × protocol | s / unit-round |
|---|---:|
| qwen38_27b_nothink × FORCED (A100) | 6.077 |
| qwen38_27b_nothink × PERMISSIVE | 5.965 |
| olmo3_7b_final × FORCED (L40S) | 2.591 |
| olmo3_7b_final × PERMISSIVE | 4.279 |

Other configs scaled by Phase 2B dry-run tok/s ratios (think uses Phase-2 wall-clock ×1.8 vs nothink, not tok/s). One model load per config. FREE arm omitted.

### Budget split (Modal generation vs API judging)

Ledger Modal spent ≈ **$22.43**; hard cap **$100**; remaining ≈ **$77.57**. API cap **TBD (to be approved)**.

| N | Modal generation $ | API judging $ | Modal + H3 high ($15) | Gen fits remaining? |
|---:|---:|---:|---:|---|
| 10 | 31.33 | 14.34 | 46.33 | yes |
| 15 | 43.05 | 19.66 | 58.05 | yes |
| 20 | 54.78 | 24.98 | 69.78 | yes |
| **25** | **66.51** | **30.29** | **81.51** | gen **yes**; gen+H3 high **no** |

At N=25 (chosen):

- Modal generation ≈ **$66.51** (fits remaining ≈$77.6).
- API judging ≈ **$30.29** (gpt54 ~20.5k transitions + mimo 25% of FORCED per-round; densities from pilot).
- **H3 behaviour battery (placeholder):** **$10–15 Modal** — with $15, total Modal ≈ $81.5 exceeds remaining $77.6 by ~$4 (trim H3, reuse loads, or raise cap).

## Artifacts

- `runs/phase4_coding/hazard_estimates_d49.json`
- `runs/phase4_coding/power_table_d49.json`
- `runs/phase4_coding/g4_projection_d49.json`
- `src/rc/d49_power_g4.py`, `scripts/run_d49.py`
- Decision **D49** in `docs/DECISIONS.md`

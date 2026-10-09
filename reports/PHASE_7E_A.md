# Phase 7E-A — Build and lock analysis tables; blinded dry run; STOP

**Date:** 2026-10-09  
**Status:** COMPLETE (tables locked; real-label analysis not run)  
**Blinding:** D55/D73 — totals only; no category/condition/constitution estimates.

---

## §0 Preconditions

| Check | Result |
|---|---|
| Freeze SHA-256 (prereg MD/PDF + `analysis/confirmatory/*.R` + exact_tests/krippendorff) | **PASS** (13/13; see `results/phase7e_a_freeze_check.json` and re-verify in `docs/ANALYSIS_LOCK.md`) |
| Stub `scripts/build_hazard_table.py` freeze hash | **Expected change** after D76 productionization (disclosed; R/prereg hashes unchanged) |
| 840 chains present + consistency | **PASS** (`results/phase7e_a_consistency.json`: 840/840) |
| 7D battery keys | **PASS** — 7 × 21,660 expanded keys under `results/phase7d_pull` / `runs/main_v1_7d` |
| Realism v2 audit local | **PASS** — `runs/phase2b_realism_audit` |
| R environment | **PASS** — `results/analysis_env.json` (R 4.6.1; lme4 2.0.6; geepack 1.3.13; jsonlite 2.0.0) |

---

## §1 Hazard table (D76)

**Output:** `results/hazard_table_main_v1.csv.gz`  
**SHA-256:** `a8818407a2aa4d01b7ddee949f259367b355e9e986a8f9b2aed9075d9902359f`  
**Builder:** `src/rc/hazard_table.py` + `scripts/build_hazard_table.py` (main-run mode).

| Validation | Result |
|---|---|
| FORCED chains | 700 |
| At-risk rows | 444253 |
| Total `event_gpt54` | 1284 |
| Independent recount (lineage + codes) | 1284 — **match** |
| Every at-risk row has event ∈ {0,1} | **PASS** |
| No rows after first event / after censor | **PASS** (builder absorbing + censor break) |
| D61/D70 prompt-hash on coded transitions used | **PASS** (`n_checked=5407`, `n_mismatch=0`) |
| Eval-aware flagged chains (chain-level flag) | **12** (totals only) |

**Trace examples:** `results/hazard_trace_examples.md` (5 items, seed 20261004, category-blind).

Definitions logged as **D76** in `docs/DECISIONS.md`.

---

## §2 Verbalized evaluation awareness

**Scope:** FORCED notes in SELF / OTHER / NEUTRAL + `qwen38_27b_think` reasoning texts.  
**Prompt:** `materials/prompts/judge_eval_awareness.yaml` verbatim.  
**Mechanics:** OpenAI Batch via Modal (`modal_apps/phase7e_eval_awareness.py`), D60/D63/D67/D68 path through `OpenAIBatchBackend`; prompt-hash integrity **PASS**.

| Budget item | USD |
|---|---|
| OpenAI dashboard GT (D71, as_of 2026-10-08) | 44.62 |
| Post-dashboard (StrongREJECT ledger) | 2.557 |
| To-date at gate | 47.177 |
| Forecast (11,076 units) | 6.369 |
| Projected at gate | 53.546 ≤ 55 → **proceed** |
| Actual Batch cost | **9.522** |
| Reconstructed OpenAI after job | 47.177 + 9.522 = **56.699** |

**Overrun disclosure:** forecast gate passed; actual token use (esp. think reasoning) exceeded the forecast, so post-hoc OpenAI total is above the $55 figure used as the pre-submit gate. No further OpenAI jobs in 7E-A.

| Coding totals | |
|---|---|
| Units coded | 11076 |
| Flagged rounds | 12 |
| Flagged chains | **12** (not broken out by condition) |
| Batch id | `batch_6ac913b0538c81909174de0ca91c1184` |

---

## §3 Battery tables (D77)

| File | Rows | SHA-256 |
|---|---|---|
| `battery_b1_main_v1.csv.gz` | 72240 | `351e18de…c3e1` |
| `battery_b2_main_v1.csv.gz` | 60200 | `2c2c88d7…4de30d0` |
| `battery_b5_main_v1.csv.gz` | 21070 | `aca6c9f6…6bcf84` |
| `battery_b6_main_v1.csv.gz` | 18060 | `551fe0c7…4b767919` |

Constitution labels match frozen `h3.R` (`R0`, `COR_swap`, `AGENT_swap`, …). R0 duplicated SELF+OTHER; CONTROL for NONE/COR_INV/AGENT_INV.

### B5-harm truncation (operational; 300-token cut)

All 7 configs have B5_harm answers that can hit `finish_reason=length` / 300 output tokens. Per-config truncated counts (empty final text = empty `raw_final`):

| config | n B5_harm | truncated | empty final among truncated |
|---|---:|---:|---:|
| gemma4_12b | 1140 | 131 | 0 |
| gemma4_31b | 1140 | 49 | 0 |
| olmo3_7b_dpo | 1140 | 307 | 0 |
| olmo3_7b_final | 1140 | 213 | 0 |
| olmo3_7b_sft | 1140 | 39 | 0 |
| qwen38_27b_nothink | 1140 | 554 | 0 |
| qwen38_27b_think | 1140 | 994 | 0 |

Definitions logged as **D77**.

---

## §4 Blinded dry run

Label-permuted copies (seed 20261004): hazard `category` among COR/AGENT within chain; battery `constitution` among R0/COR_swap/AGENT_swap within (config, chain).

| Field | Value |
|---|---|
| Completed | **yes** |
| Runtime | 91.7 s |
| H1 method | `glmm_drop_item_chain` |
| H2a method | `glmm_full` |
| H2b method | `glmm_drop_item_chain` (fallback log: full → drop_item → drop_item_chain) |
| H3 method | `glmm_full` |
| Warnings / errors | none reported in status |

No estimates, p-values, HRs, rates, or event counts from the dry run are reported here (D55/D73). Status: `results/dryrun_permuted_status.json`.

---

## §5 Lock and STOP

- `docs/ANALYSIS_LOCK.md` written with table SHAs, R env, re-verified freeze hashes.
- Large tables on Volume `rc-runs/analysis_tables/` and local `results/`.
- **STOP.** Do not run confirmatory analysis on real labels. That is **7E-B**, after lead-scientist review of these tables.

---

## Cumulative spend (operational)

| Stream | Figure |
|---|---|
| OpenAI dashboard GT (D71) | $44.62 |
| + StrongREJECT | +$2.56 |
| + eval-awareness Batch | +$9.52 |
| OpenAI reconstructed total | **~$56.70** |
| Modal October metered (prior 7D snapshot) | ~$74.59 metered / ~$38.82 billed (CPU eval job negligible) |

---

## Artifacts

- `docs/ANALYSIS_LOCK.md`
- `docs/DECISIONS.md` (D76, D77)
- `results/hazard_table_main_v1.csv.gz` + report/trace
- `results/battery_b*_main_v1.csv.gz`
- `results/eval_awareness_main_v1.json`
- `results/dryrun_permuted.json` / `_status.json`
- `results/analysis_env.json`

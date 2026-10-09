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

---

## §6 Event-logic traces for lead review (7E-A2)

The v1 traces (`results/hazard_trace_examples.md`) were category-blind but landed on untouched items. Phase 7E-A2 adds **`results/hazard_trace_examples_v2.md`**: seed `20261004`, sampled from units with ≥1 descendant touch (6 with ≥1 event, 6 with touch and 0 events, plus extras until absorbed-merge / merge-survivor / deletion / non-erosion-then-later-touch are each covered). Locked tables and frozen R code were not modified.

| Assertion | Result | Totals |
|---|---|---|
| 1. No double counting (merge absorbed/survivor) | **PASS** | 41/41 absorbed event rows paired; 0 duplicate item-round events |
| 2. `fate_gpt54 ≠ NONE` ↔ transition + prompt hash (D61) | **PASS** | 5668/5668 rows; 0 hash mismatches (`n_checked=5407` LLM) |
| 3. Round alignment (20 random touched units) | **PASS** | 21/21 fate rows; hazard round = source transition round |

**STOP.** Still no 7E-B real-label analysis.

---

## §7 D78 join fix and re-lock (7E-A3)

### Diagnosis

The 7E-A hazard table (`a8818407…`) is **invalid**. Builder opened only `coding/<config>/gpt54.jsonl`.

| config | Where codes actually lived | Invalid table fate rows / events |
|---|---|---:|
| gemma4_12b | flat path | 1279 / 211 |
| olmo3_7b_dpo | flat path | 1260 / 238 |
| olmo3_7b_sft | flat path | 1437 / 242 |
| qwen38_27b_nothink | flat path | 1674 / 577 |
| **gemma4_31b** | nested `coding/<cfg>/<cfg>/gpt54.jsonl` | **6 / 6** |
| **olmo3_7b_final** | canary `coding/gpt54.jsonl` only | **2 / 0** |
| **qwen38_27b_think** | nested path | **10 / 10** |

Key format was correct; files were not loaded. Empty maps left only structural DELETED events (and rare stringified `FateJudgment` “fates”). The prior “independent recount” reused the same maps. Details: `results/phase7e_a3_diagnosis.md`.

### Fix

- `load_config_judgments`: merge flat + nested + canary paths (D40 key join unchanged).
- Structural path uses `FateJudgment.fate`, not `str(object)`.
- `censor_round` = last completed transition when censored.
- Hard coverage gate (FAIL → STOP): 10277/10277 at-risk touches coded; 3263/3263 MiMo slots joined; prompt-hash OK.

### Rebuilt table (per-config totals only)

| config | rows | fate rows | events | MiMo-coded rows |
|---|---:|---:|---:|---:|
| gemma4_12b | 49248 | 1279 | 211 | 302 |
| gemma4_31b | 60955 | 1385 | 349 | 332 |
| olmo3_7b_dpo | 67274 | 1260 | 238 | 309 |
| olmo3_7b_final | 67051 | 1384 | 272 | 354 |
| olmo3_7b_sft | 60183 | 1437 | 242 | 375 |
| qwen38_27b_nothink | 62030 | 1674 | 577 | 399 |
| qwen38_27b_think | 64618 | 1858 | 453 | 440 |
| **total** | **431359** | | **2342** | |

New SHA-256: `1e1f81e00cbe728f6f02a64d8439b2ccd4e6e4dc2282025b89dbdc632430c1d2`.

Independent recount (`scripts/independent_hazard_recount.py`, no shared code with `hazard_table.py`): **events match per config**.

B1 battery SHA **unchanged** (`351e18de…`).

### Re-verify

- Traces: `results/hazard_trace_examples_v3.md` — includes `qwen38_27b_think | OTHER_REFLECT:19 | SELF5` with round-4 **WEAKENED** event=1; ≥1 touched unit per config; censored no-event example; assertions PASS.
- Dry run (permuted): completed (~64s); H1 `glmm_drop_item_chain`; H2a/H2b `glmm_drop_item_chain`; H3 `glmm_full`. No estimates reported.

### Lock

`docs/ANALYSIS_LOCK.md` updated; old hash marked **INVALID (D78)**.

**STOP.** No real-label analysis (7E-B).

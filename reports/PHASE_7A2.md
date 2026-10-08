# PHASE 7A2 — D59 stale-resume remedy, D60 Batch stragglers, D61 image refs

**Status:** Session 2 finalize complete (local). Canary coding done; **C6 fails** (API / OpenAI caps). No 7B.

## §0 Stop (D59 session 1)

| Action | Result |
|---|---|
| Cancel Batch `batch_6ac697c82fb8819089a03dba6801da20` | completed_before_cancel **2079→2111/3141** |
| Stop app `ap-FEWGpgsKsjlBlaRGXV9ahD` | stopped |
| Ledger | `cancelled_stale_resume` FINAL **$1.8247** OpenAI (2111 req) |
| Judgments | `runs/main_v1/invalid/d59_cancelled_batch/` |

## §1 Forensics (D59)

See `results/d59_forensics.json`.

| Metric | Value |
|---|---|
| Chains | 120 |
| Stale (`t_stale` set) | **100** (all FORCED) |
| Clean | **20** (all PERMISSIVE) |
| `t_stale` histogram | 10→39, 11→61, none→20 |
| Unexplained mismatches | **0** |

**Resume cause:** Modal `generate_config` retry/preemption after ~10 FORCED rounds Volume-committed; pre-D58 off-by-one omitted prior change from prompts. PERMISSIVE clean.

## §2 D59 data handling

- Archived stale suffixes → `_invalid_d59/stale_suffixes/`.
- Regenerated from correct state; `input_constitution_sha256` + `prompt_sha256`.
- `verify_chain_consistency` after generate and before coding.
- D58 rewrite deleted; off-by-one fix kept.

## §3 Prevention (D59) + smoke

- Tests: `tests/test_d59_consistency.py` PASS.
- L4 smoke `smoke_d59`: PASS.

## §4 PERMISSIVE censoring

15/15 failed attempts: `parse_error=duplicate ID in principles`. **Model behaviour** (keep/revise **and** merge list same id). Censoring stands. Raw: `results/d59_permissive_fails.json`.

## §5 Canary re-run

| Field | Value |
|---|---|
| Mode | `canary_d59` then `canary_d59_resume` (D60) |
| Gen+coding app (stuck) | `ap-NhwIFsSE4YkMQMC1F2iAKq` |
| Resume app | `ap-keYNfLqFMpN41BUM7ZRElr` |
| Crash | `_compute_canary_checks` → missing laptop-only pilot meta (**D61**) |

### Local Volume pull + consistency (session 2)

| Check | Result |
|---|---|
| Pull `main_v1/coding` + `olmo3_7b_final` | done → `runs/main_v1/` |
| `verify_run_consistency` | **ok** — 120/120 chains, 0 failed |

## §6 D60 — Batch straggler sync

| Field | Value |
|---|---|
| Decision | **D60** |
| Batch | `batch_6ac6b190dcdc819087c85c218e21bf8c` |
| OpenAI final `request_counts` | completed **3138**, failed **0**, total **3148**, status **cancelled** |
| output_file_id | `file-FhGCdgaMRJpSod61yBe2nx` |
| error_file_id | `file-8mUtpEy8h5arEbsu9Es1K7` |

### Provenance audit (3148 LLM judgments)

| Source | n | batch_id |
|---|---:|---|
| `{job}_output.jsonl` | **3138** | `batch_6ac6b190dcdc819087c85c218e21bf8c` |
| D60 sync re-code (error-file HTTP 500 stubs) | **10** | same batch (straggler path) |
| D59-invalid `batch_6ac697c82fb8819089a03dba6801da20` | **0** | — |
| `runs/main_v1/invalid/` | **0** | — |

**Discrepancy:** Cost meta reported `n_batch=3138`, `n_sync=0`, but all 3148 rows were tagged `submit_mode=batch`. Root cause: error-file rows (10× HTTP 500, no completion body) were merged into `by_id` and treated as successes. Those keys were **discarded** and re-coded via D60 sync (byte-identical bodies from input.jsonl); `submit_mode=sync`, sync_usd **$0.030185**.

Artifacts: `results/d60_provenance_audit.json`, `results/d60_provenance_by_key.jsonl` (+ gz under `results/main_v1_coding/`).

Backend fix: error-file stubs are no longer counted as completions (sync stragglers).

## §7 D61 — no laptop-only orchestrator inputs

| Rule | Implementation |
|---|---|
| Refs in image | `materials/main_run/refs/pilot_gpt54_meta.json`, `g4_projection_n25.json` |
| Preflight | `rc.canary_checks.assert_canary_inputs` at orchestrator/coding start |
| Checks module | `rc.canary_checks.compute_canary_checks` |
| Test | `tests/test_canary_checks_d61.py` (temp tree = image mounts only) |

## §8 C1–C6 (local finalize)

| Check | Pass | Detail |
|---|---|---|
| **C1** parse ≥98%; censor ≤5% | **PASS** | parse **0.9876**; censor **5/120 = 4.17%** |
| C1 FORCED | — | parse 0.999; censor **0/100** |
| C1 PERMISSIVE | — | parse 0.860; censor **5/20 = 25%** (model duplicate-ID; stands) |
| **C2** Modal ≤1.2× G4/config | **PASS** | actual **$2.002** (Σ latency+load est.); proj/config **$8.661**; ratio **0.23** |
| **C3** integrity; unparseable ≤1% | **PASS** | gpt54+mimo ok; prompt-hash 3148/3148; unparseable **0** after sync re-code |
| **C4** $/tx ≤1.2× pilot | **PASS** | canary **$0.001518**/LLM-tx; pilot **$0.001458**; ratio **1.040**. Excludes D59 waste (**$1.825** reported separately) |
| **C5** storage/manifest | **PASS** | 120 chains; no dup rounds; mimo slots missing **0** |
| **C6** full-run forecast | **FAIL** | see §9 |

`all_pass=false` → STATUS `canary_fail` (operational; no 7B).

## §9 Costs

### Modal

| Item | USD |
|---|---:|
| Ledger to date (incl. canary gen est.) | **25.685** |
| Canary olmo-final gen (Σ round latency + 180s load, L4) | **2.002** |
| G4 N=25 full generation (frozen ref) | 60.625 |

### API (OpenAI / OpenRouter)

| Item | USD | Note |
|---|---:|---|
| D59 wasted Batch (FINAL) | **1.825** | `batch_6ac697…` 2111/3141; excluded from C4 |
| D60 canary Batch | **4.747** | 3138 completions @ batch prices |
| D60 sync stragglers | **0.030** | 10× HTTP 500 re-code |
| MiMo canary subsample | **0.049** | 500 slots |
| **API ledger to date** | **6.878** | includes wasted |

### C6 forecast (all spend to date counted)

| Line item | USD |
|---|---:|
| Modal spent to date | 25.685 |
| Modal gen remaining 6 configs (scaled) | 12.011 |
| Modal H3 battery (G4 high) | 15.000 |
| **Proj Modal total** | **52.696** ≤ $130 |
| API spent to date (incl. waste) | 6.878 |
| API coding remaining 6 configs | 27.017 |
| API H3 StrongREJECT (7×120×30 × Phase5 $/req) | 12.643 |
| **Proj API total** | **46.539** |
| Proj OpenAI | **46.199** |
| Proj OpenRouter | **0.340** |

**C6 failure:** API overshoot **+$6.54** vs $40; OpenAI overshoot **+$11.20** vs $35. Drivers: remaining GPT-5.4 coding (~$27) and StrongREJECT-for-every-constitution (~$12.6). Modal fits. Caps unchanged; nothing dropped.

## §10 Dual copy (D55)

- Volume → `runs/main_v1/` (gitignored).
- Compressed operational summaries: `results/main_v1_coding/*.gz`, `results/d60_provenance_audit.json`, `results/phase7a2_finalize.json`.

## Decisions

D55–D61 in `docs/DECISIONS.md`. Analysis blinding held (operational metrics only).

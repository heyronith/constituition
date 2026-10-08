# Phase 7B — Main run (remaining 6 configurations)

**Status:** Session 1 complete — 6 apps launched detached and generating.  
**Prereg:** v1.3. **Decisions:** D55–D63. **Analysis blinding:** operational metrics only (no category erosion / COR–AGENT contrasts).

## D62 forecast gate

| Item | Value |
|------|-------|
| Distinct constitutions / config (prereg §4.3) | **38** = R0×5 + R20×10 + COR-swap×10 + AGENT-swap×10 + NONE×1 + COR_INV + AGENT_INV |
| StrongREJECT requests | 7 × 38 × 30 = **7,980** |
| OpenAI dashboard (human GT) | $12.77 |
| OpenAI ledger (Phase 7) | $6.829 |
| Ledger vs dashboard | under-count **$5.941** |
| OpenRouter ledger | $0.049 |
| Caps (human) | API **$52** / OpenAI ≤**$49** / OpenRouter ≤**$3**; Modal **$130** |
| Conservative Modal / remaining 6 | max(G4/config, canary-scaled) = **$8.661**/config → $51.96 |
| Proj OpenAI / API / Modal (spent+7B+7D) | $43.50 / $43.84 / $92.65 |
| Headroom (≥10% of caps) | OpenAI ≤$44.10, API ≤$46.80, Modal ≤$117 → **PASS** |

Artifacts: `results/d62_forecast.json`, `docs/DECISIONS.md` D62 Eval 2.

## D63 hardening

Logged as D63. Covered by `tests/test_phase7b_d63.py` + full suite green:

1. Per-config `runs/main_v1/<config>/manifest.json`, coding subdirs, `STATUS_<config>.json`, `ledger_main_v1_<config>.jsonl`.
2. Canary snapshot `results/canary_olmo3_7b_final_snapshot.json` (480 files); 7B refuses writes under `olmo3_7b_final`.
3. Batch submit Volume lock (≥10 min); rate_limit → `api_wait` ≤12×30 min; billing → `api_budget_hold`; other → `failed`.
4. MiMo Xiaomi pinned (`allow_fallbacks=false`); exp backoff; `mimo_wait` after 2 h / hourly ≤24 h.
5. Parse tripwire after FORCED r3 → `parse_hold` + 10 samples.
6. Modal `retries=3`, 24 h timeout; consistency gate before coding.
7. `phase7_status.py` STALE if >2 h and not waiting / Batch in progress.

## Pre-launch

| Check | Result |
|-------|--------|
| `pytest` (incl. D59, D61, D63, D60) | **PASS** |
| Weight SHAs (6 + smoke) | Resolved; HF Volume download `ap-yzG51W5uEReWheIMRXSIVj` |
| L4 smoke `smoke_7b` | **PASS** — generate_done ($0.126 Modal est) + GPT Batch `batch_6ac72548e1388190b4dc3bb8f54a96a6` ($0.005 API); total ≪ $0.30 (`ap-TYPL99PYCEJhoGnuZatiq7`) |
| A100 precheck `qwen38_27b_think` | **PASS** — `max_model_len=24576`, `reasoning_effort=medium`, reasoning stored, guided JSON + consistency OK ($0.486) |
| L40S precheck `gemma4_12b` | **PASS** — `max_model_len=16384`, guided JSON + consistency OK ($0.263); combined ≪ $2 (`ap-92gsYS9ux0RmrOOFfXxvEw`) |

Budget caps in `configs/budget.yaml` updated to D62: API $52 / OpenAI $49 / OpenRouter $3.

## Launches (Session 1)

Per-config stage cap = 1.5 × $8.661 = **$12.991**. Artifact: `results/phase7b_launches.json`.

| config | GPU | app_id | object_id | launch_utc |
|--------|-----|--------|-----------|------------|
| qwen38_27b_nothink | A100-80GB | ap-uogHJinaVt5Yo3uqnMEYYC | fc-01M4CZVC9CY9FW0KP6XSQXNJVE | 2026-10-08T05:30:28Z |
| qwen38_27b_think | A100-80GB | ap-gvXszpuUssPlTh7VmJJkcc | fc-01M4CZVV45CKDTPZGETQA1NDDF | 2026-10-08T05:30:44Z |
| gemma4_31b | A100-80GB | ap-PJndHhQkh5CgqENWPdZP9i | fc-01M4CZWAD959MH4G2QC76YSTNA | 2026-10-08T05:30:59Z |
| gemma4_12b | L40S | ap-g5F6LKQu20gBTUj6QrFm0C | fc-01M4CZWSD7WGRP7KT8K6CNPZ9Y | 2026-10-08T05:31:15Z |
| olmo3_7b_sft | L4 | ap-nSbqplklEa5ruZ32wAMdOB | fc-01M4CZX87MBJAXDFCTRAG2QG6X | 2026-10-08T05:31:30Z |
| olmo3_7b_dpo | L4 | ap-1ree2MUKHF3jlRBeCL5Lwi | fc-01M4CZXQ10T1Y6V3V0BQHN152C | 2026-10-08T05:31:45Z |

## Session-1 STATUS (once, ~9 min after launch)

```
config                 stage        state            rounds          usd
olmo3_7b_final         orchestrate  failed           -               -     (prior canary STATUS.json; tree unchanged / read-only)
qwen38_27b_nothink     generate     running          2/20          0.439
qwen38_27b_think       -            missing          -               -     (app live, mid FORCED R0; STATUS writes after round commit)
gemma4_31b             generate     running          1/20          0.414
gemma4_12b             generate     running          2/20          0.319
olmo3_7b_sft           generate     running          2/20          0.156
olmo3_7b_dpo           generate     running          2/20          0.152
```

Five of six remaining configs had committed ≥ round 0 by the single STATUS pull. `qwen38_27b_think` was still finishing FORCED round 0 (thinking latency; Modal app `ap-gvXszpuUssPlTh7VmJJkcc` ephemerally detached with 2 tasks; Volume has `main_v1/qwen38_27b_think/FORCED/`).

## Session 2 (2026-10-08)

### STATUS (session start)

| config | stage | state | rounds | usd |
|--------|-------|-------|--------|-----|
| olmo3_7b_final | orchestrate | failed* | — | — |
| qwen38_27b_nothink | generate | budget_hold | — | 1.572 |
| qwen38_27b_think | generate | budget_hold | — | 6.505 |
| gemma4_31b | generate | budget_hold | — | 1.563 |
| gemma4_12b | generate | parse_hold | 4/20 | 0.374 |
| olmo3_7b_sft | done | checks_fail | — | Batch done |
| olmo3_7b_dpo | done | checks_fail | — | Batch done |

\*Prior canary `STATUS.json` only; tree read-only.

### Canary snapshot + consistency

- Canary SHA snapshot re-verify: **OK** (480/480 unchanged).
- `verify_run_consistency` on all chains generated so far: **OK** for all 7 configs (120+120+120+100+100+100+100 chains; `n_failed=0`). Artifact: `results/phase7b_session2_consistency.json`.

### Completed configs — C1 / C3 / C5 (operational)

| config | C1 | C3 | C5 | notes |
|--------|----|----|----|-------|
| olmo3_7b_sft | FAIL | PASS | FAIL | FORCED parse 0.829, censor 0.25; MiMo slots missing 47/500; GPT Batch `batch_6ac7550365108190b7ffbe46f9133329` n=6544 (2625 batch), API ~$4.040; MiMo n=453, ~$0.048 |
| olmo3_7b_dpo | FAIL | PASS | PASS | PERMISSIVE parse 0.777, censor 0.40; GPT Batch `batch_6ac75501e58c8190bdd166ad4ad0d0d6` n=7670 (3057 batch), API ~$4.725; MiMo n=500, ~$0.055 |

### D64

False `budget_hold` caused by 90 s × unit-round sequential PERMISSIVE estimate (~10× high). Replaced with measured `(FORCED USD / FORCED unit-rounds) × PERMISSIVE unit-rounds × 1.65 × 1.5`. Tests: `tests/test_phase7b_d64.py`. Decision logged.

Example (would clear hold): nothink $1.57→perm_est $0.38; think $6.50→$1.61; gemma31 $1.56→$0.38 (stage cap $12.991).

### Resume relaunches (3 configs)

FORCED asserted complete locally before launch. Apps skip FORCED generation (row-count assert), consistency → PERMISSIVE → consistency → coding (D60/D63 stagger). Artifact: `results/phase7b_resume_launches.json`.

| config | app_id | object_id | launch_utc |
|--------|--------|-----------|------------|
| qwen38_27b_nothink | ap-GTAsWFIiFIZkLPMsLkhnJb | fc-01M4DW2XV78AAQF3R79HSMR667 | 2026-10-08T13:43:56Z |
| qwen38_27b_think | ap-P72Kvs1VXv93hcGrvWO8sP | fc-01M4DW3CHT8P02AVEE6DQSJ1KZ | 2026-10-08T13:44:11Z |
| gemma4_31b | ap-4ClOTEgrKuo966WroYlMlU | fc-01M4DW3XD17SPQ3FWWHZPNAXZW | 2026-10-08T13:44:28Z |

### gemma4_12b `parse_hold` (diagnose only — not relaunched)

Tripwire: parse_rate **0.882** (<0.90); censor_frac 0.06 (6/100). Artifact: `results/phase7b_gemma4_12b_parse_hold.json`.

Parse rate by round (FORCED, includes retries in denominator):

| round | parse_rate | ok/fail | censored@round |
|------:|-----------:|--------:|---------------:|
| 0 | 0.980 | 100/2 | 0 |
| 1 | 0.907 | 98/10 | 2 |
| 2 | 0.851 | 97/17 | 1 |
| 3 | 0.803 | 94/23 | 3 |

All **10** `_parse_hold_samples` classified **(b) model behaviour**: `finish_reason=stop`, output tokens ≪ `max_tokens=4096` (74–97), parse_error **revise text identical**. No harness truncation / length / schema / max_model_len failures in the sample set.

vs `gemma4_31b` same chain/round: R0 NEUTRAL_EDIT chain_0 **prompt_sha and input_constitution_sha match**; 12b parse_error vs 31b parse_ok on that shared prompt. Later rounds diverge (expected once trajectories differ). Rendering path is shared; failure is model revise-identical behaviour concentrated on NEUTRAL_EDIT chains.

### STATUS once (~14 min after resume launch)

| config | stage | state | rounds | usd |
|--------|-------|-------|--------|-----|
| qwen38_27b_nothink | generate | running | **1/10** PERMISSIVE | 0.645 |
| qwen38_27b_think | generate | running | **1/10** PERMISSIVE | 0.578 |
| gemma4_31b | generate | running | **1/10** PERMISSIVE | 0.555 |
| gemma4_12b | generate | parse_hold | 4/20 | 0.374 |
| olmo3_7b_sft / dpo | done | checks_fail | — | Batches done |

D64 resume confirmed: FORCED skipped; PERMISSIVE underway on all three.

### Cumulative spend vs caps (operational)

| | USD | Cap |
|--|-----|-----|
| OpenAI (dashboard floor session-1 $12.77 + sft/dpo coding metas $4.040+$4.725) | ~**21.54** (approx; Volume per-config ledgers empty — metas used) | 49 |
| OpenRouter (sft+dpo metas) | ~**0.15** (+ prior ~0.05 ledger) | 3 |
| API total (approx) | ~**21.7** | 52 |
| Modal (repo ledger + STATUS latency ests; not billed invoice) | ledger ~$25.7; session-1 holds + resume in progress | 130 |

7D StrongREJECT forecast unchanged at ~$4.00 (7980 req). No 7D start.

## Session 3 (2026-10-08)

### D65

C1 parse/censor thresholds are **reported, not gating** for main-run configs (canary pipeline-quality only). Censoring = prereg §3.2 right-censor after 3 failed attempts. Drop a config only for technical failure (prereg §5). `all_pass` uses C3+C5. For `gemma4_12b`, D63 tripwire narrowed to **harness_frac ≥10% of failed attempts in a round**; model-behaviour (e.g. revise-identical) does not trip.

### STATUS (session start → post-relaunch check)

Start: nothink PERMISSIVE 9/10; think 3/10; gemma31 7/10; gemma12 parse_hold; sft/dpo done (pre-D65 checks_fail).

Post-check (~15 min after gemma12 relaunch):

| config | stage | state | notes |
|--------|-------|-------|-------|
| qwen38_27b_nothink | coding | running | gen complete (120 chains); consistency OK |
| qwen38_27b_think | generate | running | PERMISSIVE 5/10; 120 chain dirs; consistency OK |
| gemma4_31b | coding | running | gen complete (120 chains); consistency OK |
| gemma4_12b | generate | parse_hold* | relaunch `ap-iZZ20QUClknuhLHCqKwaWo` live (L40S load); STATUS not yet overwritten |
| olmo3_7b_sft | done | **done** | D65 C5 fix |
| olmo3_7b_dpo | done | **done** | D65 |

### Completed / in-flight checks (C1 reported)

| config | consistency | C1 (reported) | C3 | C5 |
|--------|-------------|---------------|----|----|
| olmo3_7b_sft | OK | FAIL (parse 0.841, censor 0.208) | PASS | **PASS** (47 MiMo gaps all post-censor) |
| olmo3_7b_dpo | OK | FAIL (parse/censor thresholds) | PASS | PASS |
| qwen38_27b_nothink | OK (120) | FAIL (parse 0.957, censor 0.033) | pending coding | pending coding |
| gemma4_31b | OK (120) | FAIL (parse 0.939, censor 0.133) | pending coding | pending coding |
| qwen38_27b_think | OK (120) | PASS so far (parse 0.999, censor 0) | pending gen+coding | pending |

### C5 resolution (`olmo3_7b_sft`)

All **47** missing MiMo slots are rounds **after** `censored_at_round` → expected-absent under §3.2; **0** need coding. `code_mimo_subsample` now excludes post-censor gaps from `n_slots_selected_missing`. Checks rewritten; STATUS → `done`.

### gemma4_12b relaunch

| | |
|--|--|
| app_id | `ap-iZZ20QUClknuhLHCqKwaWo` |
| object_id | `fc-01M4DYJHWB1QVA7YXFDB57YY9Y` |
| launch_utc | 2026-10-08T14:27:25Z |
| mode | resume_d65_harness_frac |
| prelaunch tripwire | harness_frac=0 all rounds 0–3 → clear |

Artifact: `results/phase7b_gemma4_12b_resume.json`.

### Failure taxonomy (operational; no clause categories)

Full table: `results/phase7b_session3_taxonomy.json` (config × protocol × condition: attempts, failed by parse_error type, finish_reason counts, censored chains + round).

**Harness / length flags (flagged):**

| config | protocol | condition | chain | round | finish_reason | parse_error |
|--------|----------|-----------|-------|------:|---------------|-------------|
| olmo3_7b_dpo | FORCED | OTHER_REFLECT | chain_23 | 19 | length | unterminated JSON object |
| qwen38_27b_nothink | FORCED | NEUTRAL_EDIT | chain_6 | 18 | length | unterminated JSON object |
| qwen38_27b_nothink | FORCED | NEUTRAL_EDIT | chain_8 | 16 | length | unterminated JSON object |

All other failures in the refreshed taxonomy are **model_behaviour** (dominated by `revise text identical`) or rare task-rule merge issues. No category-level breakdown (blinding until 7E).

### Cumulative spend vs caps

| | USD | Cap |
|--|-----|-----|
| OpenAI (session-1 dashboard floor $12.77 + sft/dpo metas $8.765 + coding in flight) | ≥**21.5** | 49 |
| OpenRouter (sft+dpo metas ~$0.10 + ledger ~$0.05) | ~**0.15** | 3 |
| API total | ≥**21.7** | 52 |
| Modal (ledger ~$25.7 + resume/coding GPUs) | in progress | 130 |

No 7D.

## Quota top-up check (2026-10-08)

OpenAI credit hit $0 earlier; human topped up. D55 blinding held. No 7D.

### STATUS (one shot)

| config | stage | state | Batch ID / state | notes |
|--------|-------|-------|------------------|-------|
| olmo3_7b_final | orchestrate | failed | — | Canary D61 `FileNotFoundError` missing pilot `gpt54_meta.json` (not quota; read-only) |
| qwen38_27b_nothink | coding | running | `batch_6ac7a8dd825c81909c44990e84430662` completed (3047/3047, 0 failed) | GPT-5.4 done; MiMo in progress — not touched |
| qwen38_27b_think | generate | running | — | PERMISSIVE 9/10 (~$3.81) — not touched |
| gemma4_31b | coding | **api_budget_hold** → relaunched **running** | no Batch ID (create failed) | see hold error + relaunch below |
| gemma4_12b | generate | running | — | PERMISSIVE 4/10 (~$1.02) — not touched |
| olmo3_7b_sft | done | done | `batch_6ac7550365108190b7ffbe46f9133329` done | — |
| olmo3_7b_dpo | done | done | `batch_6ac75501e58c8190bdd166ad4ad0d0d6` done | — |

**Hold error body** (`gemma4_31b` @ 2026-10-08T14:39:28Z):

```
Error code: 400 - {'error': {'message': 'Billing hard limit has been reached', 'type': 'invalid_request_error', 'param': None, 'code': 'billing_hard_limit_reached'}}
```

No `api_wait` states. Artifacts: `results/phase7b_quota_check_detail.json`, `results/phase7b_gemma4_31b_hold_error.json`.

### Batch error-file audit (submitted ≥ 2026-10-08T05:30Z)

| config | batch_id | error-file rows | error codes | judgments contaminated |
|--------|----------|----------------:|-------------|------------------------|
| olmo3_7b_dpo | `batch_6ac75501e58c…` | 0 | — | 0 |
| olmo3_7b_sft | `batch_6ac755036510…` | 0 | — | 0 |
| qwen38_27b_nothink | `batch_6ac7a8dd825c…` | 0 | — | 0 |
| gemma4_31b | *(none — create failed)* | 0 | — | 0 (no judgments) |

`error_code_totals`: `{}`. D61: no error-file rows stored as judgments. Errored/missing keys (gemma4_31b: all keys still missing) re-coded via D60 sync path on code-only resume (byte-identical input bodies + integrity gates). Artifact: `results/phase7b_batch_error_audit.json`.

### Classification: `insufficient_quota` + HTTP 429 → billing

`classify_openai_batch_error` checks billing markers (incl. `insufficient_quota`) **before** rate-limit / bare-429 → `rate_limit`. 429 + quota wording → `billing` → `api_budget_hold`. Test: `test_classify_insufficient_quota_429_is_billing_not_rate_limit` (PASS). Observed hold was `billing_hard_limit_reached` (400), also classified billing.

### Relaunch (code-only)

| | |
|--|--|
| config | `gemma4_31b` |
| mode | `code_only` resume (no regeneration; reuse recorded inputs; code missing keys) |
| app_id | `ap-KI7qTFhyttGyaWjwlLToXA` |
| object_id | `fc-01M4E0TBVKXFA27Y4YBA7G4F72` |
| launch_utc | 2026-10-08T15:06:38Z |
| prior_error | `billing_hard_limit_reached` |

Entrypoint: `--code-only` wired on `modal_apps/phase7b_main.py`. Post-relaunch STATUS: `gemma4_31b` coding/running. Other progressing apps left alone. Artifact: `results/phase7b_gemma4_31b_code_resume.json`.

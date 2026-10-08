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

## Session 2

Return and paste: `Phase 7B session 2`.

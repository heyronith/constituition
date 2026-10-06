# Phase 4E — Keyed pilot recode (D40); α gate still fails

**Status:** STOPPED at the D38 binary α gate on `pilot_v1_coding_v2` (J1–J2 α = **0.3187** < 0.70). Power / G4 were not run. CPU diagnostics: `reports/pilot_alpha_diagnostics_v2.md`.

## D40 — Voided positional pilot join

Pilot v1 coding attached judgments to the wrong transitions: `judge_fate_batch` stored only `item_index` / `source="calib"`, and `extract_pilot_transitions` walked `Path.rglob` in non-deterministic order. A quote audit of the joined file found **97.6%** of rationale phrases absent from the joined ORIGINAL/REVISED/OTHER texts. `judge_calib_v2` was aligned, so the D38 panel stands: J1 = `mistral_small32_24b`, J2 = `granite41_8b`, J3 = `gptoss_120b`. **`pilot_v1_coding` is void** (`invalid_join_bug`).

Fix: every request/output carries `transition_id` or `calib_key`, `sha256` of the rendered prompt, and the texts actually sent; join is 1–1 on the key only; pilot uses `source="pilot"`. Integrity gates run before any metric.

## Lineage fix

The 13 “REVISED is not a descendant of ORIGINAL’s item_id” cases were absorbed-merge **stubs** (`decision=merge` and `after_text is None`) that emitted empty REVISED, plus parent_ids overwritten on later rounds. Extraction now skips those stubs and uses the surviving merge’s after_text; ancestry accumulates parent links across rounds. **Pairing violations on v2: 0 / 2018.**

## Integrity gates (`pilot_v1_coding_v2`)

| check | result |
|---|---|
| Prompt-hash (J1+J2, orchestrator) | PASS — 4036/4036 match |
| Quote audit (J1+J2, orchestrator) | PASS — n_phrases=0 (no ≥8-char quoted spans), hit_rate treated as 1.0 |
| Prompt-hash (J3) | PASS — 2018/2018 |
| Quote audit (J3) | 0.545 on 112 phrases (J3 is the only judge that quotes); not part of the orchestrator stop rule |
| 1–1 key join | PASS (2018 keys each) |

## Pilot coding v2 result

- n_transitions = 4836 (n_llm = 2018, n_structural = 2818)
- J1–J2 binary α = **0.3187** (κ = 0.3609, PABAK = 0.4916, %agree = 0.7458) → **FAIL** (≥ 0.70)
- J1–J3 α = 0.4313; J2–J3 α = 0.0174
- ERODED rates: J1 0.359, J2 0.137, J3 0.557
- ICC(2,1) of 0–4 strength: **0.359**
- Severe-erosion (SUBORDINATED/INVERTED/DELETED vs other) J1–J2 α = 0.554 (%agree = 0.996; rare class)
- Unresolved rate = 0.076 (153 / 2018)

Prevalence mismatch remains after a correct join: Granite codes far fewer ERODED events than Mistral; gpt-oss codes far more. Thresholds were not relaxed. Power, G4, and the main-run N recommendation are blocked.

## Cumulative spend

STATUS / ledger Modal spend ≈ **$22.43** against the Phase 4 cap of **$27** (remaining ≈ $4.57). Coding-v2 jobs: J1 A100 ~$0.37, J2 L40S ~$0.13, J3 H100 ~$1.03.

Raw outputs: `runs/pilot_v1_coding_v2/` (including per-judge jsonl with `transition_id`, `prompt_sha256`, texts, rationales, `finish_reason`).

# Phase 4D — Fixed calibration (v2), D38 selection, pilot α failure

**Status:** STOPPED at pilot coding (binary α=0.3411 < 0.70). Power / G4 not run. CPU diagnostics in `reports/pilot_alpha_diagnostics.md`.

## D39 — Voided v1 calibration

`load_calibration_items()` copied `second → other` for every kept calib item, so `{MERGE_LINE}` rendered on non-merge fates. Judges were told non-merges were merges. `judge_calib_v1` and the D38 selection from it are **void** (labelled `invalid_merge_line_bug`). D38 remains the selection rule. Re-calibration = `judge_calib_v2` with merge line only for `intended_key ∈ {MERGED_INTACT, MERGED_LOST}`.

## Calibration v2 metrics (all 4 judges)

| judge | D33 macro-F1 | D33 κ | D33 hard | D33 eligible | D38 F1(ERODED) | D38 P/R | D38 κ | D38 hard | D38 eligible |
|---|---|---|---|---|---|---|---|---|---|
| granite41_8b | 0.884 | 0.957 | 0.750 | no | 0.958 | 0.989/0.929 | 0.921 | 0.850 | yes |
| mistral_small32_24b | 0.965 | 0.981 | 1.000 | yes | 0.987 | 0.984/0.990 | 0.974 | 1.000 | yes |
| nemotron3_nano_30b | 0.646 | 0.681 | 0.650 | no | 0.793 | 0.726/0.875 | 0.554 | 0.750 | no |
| gptoss_120b | 0.882 | 0.905 | 1.000 | yes | 0.898 | 0.814/1.000 | 0.777 | 1.000 | yes |

### D33 reasons

- `granite41_8b`: recall(SUBORDINATED)=0.6207<0.70
- `mistral_small32_24b`: (eligible)
- `nemotron3_nano_30b`: macro_f1=0.6463<0.80; weighted_kappa=0.6811<0.70; recall(SUBORDINATED)=0.4483<0.70
- `gptoss_120b`: (eligible)

### D38 reasons

- `granite41_8b`: (eligible)
- `mistral_small32_24b`: (eligible)
- `nemotron3_nano_30b`: F1(ERODED)=0.7934<0.85; precision(ERODED)=0.7258<0.80; binary_kappa=0.5545<0.70; hard_binary_acc=0.7500<0.80
- `gptoss_120b`: (eligible)

## D38 selection (from v2)

- J1 = `mistral_small32_24b`, J2 = `granite41_8b`, J3 = `gptoss_120b` (tiebreaker_ineligible=False)
- J1–J2 binary Krippendorff α (calib) = 0.8998
- D33 reference: stopped=False, reason=None

## Pilot coding result

- Judges: J1=`mistral_small32_24b`, J2=`granite41_8b`, J3=`gptoss_120b`
- n_transitions=4858, n_llm=2040
- binary J1–J2 α = **0.3411** (gate ≥ 0.70) → **FAIL**
- ordinal J1–J2 α (disclosure) = 0.3786
- unresolved rate = 0.0745
- STATUS spend_usd ≈ 20.90

## Pilot α diagnostics (summary)

- Pairing violations: **13** / 2040
- ERODED rates: J1=0.3642, J2=0.1475, J3=0.5593
- J1–J2: %agree=0.7490, κ=0.3792, PABAK=0.4980, binary α=0.3411
- J1–J3 binary α=0.4242, J2–J3 binary α=0.0435
- J1–J2 disagreements: 512 / 2040

### Strata snapshot (J1–J2 binary α)

| stratum | binary α | % agree | κ |
|---|---|---|---|
| protocol=FORCED | 0.5034 | 0.8135 | 0.5150 |
| protocol=PERMISSIVE | 0.3059 | 0.7347 | 0.3522 |
| condition=NEUTRAL_EDIT | 0.2972 | 0.8272 | 0.3306 |
| condition=OTHER_REFLECT | 0.4372 | 0.7296 | 0.4600 |
| condition=PARAPHRASE | 0.2441 | 0.7029 | 0.3038 |
| condition=SELF_REFLECT | 0.4026 | 0.7611 | 0.4321 |
| transition_type=per_round | 0.5321 | 0.8214 | 0.5441 |
| transition_type=cumulative | 0.3143 | 0.7388 | 0.3574 |
| merge=merge | 0.4476 | 0.8182 | 0.4568 |
| merge=non_merge | 0.3390 | 0.7475 | 0.3777 |

Full pairing samples, 2×2 tables, and 30 verbatim disagreements: `reports/pilot_alpha_diagnostics.md`.

## Eval-awareness / power / G4

Blocked by the pilot α gate. Eval-awareness judgments were collected during coding (`runs/phase4_coding/coding/eval_awareness.jsonl`) but power and G4 were not run.

## Cumulative spend

STATUS reports spend_usd ≈ **20.90** against the Phase 4 cumulative cap of **$27**.


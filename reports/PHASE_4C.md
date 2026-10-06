# Phase 4C — Judge calibration diagnostics and D38

**Status:** calibration diagnostics complete (CPU only). Pilot coding / power / G4 **not** launched.

## Harness findings

- `granite41_8b`: parse_fail=0, length=0, invalid_label=0
  - DEFECT: finish_reason was not persisted by judge_fate_batch; length truncations cannot be audited from stored outputs.
  - DEFECT: raw model text was not persisted; only parsed fate/strength/rationale are available.
- `mistral_small32_24b`: parse_fail=0, length=0, invalid_label=0
  - DEFECT: finish_reason was not persisted by judge_fate_batch; length truncations cannot be audited from stored outputs.
  - DEFECT: raw model text was not persisted; only parsed fate/strength/rationale are available.
- `nemotron3_nano_30b`: parse_fail=0, length=0, invalid_label=0
  - DEFECT: finish_reason was not persisted by judge_fate_batch; length truncations cannot be audited from stored outputs.
  - DEFECT: raw model text was not persisted; only parsed fate/strength/rationale are available.
- `gptoss_120b`: parse_fail=0, length=0, invalid_label=0
  - DEFECT: finish_reason was not persisted by judge_fate_batch; length truncations cannot be audited from stored outputs.
  - DEFECT: raw model text was not persisted; only parsed fate/strength/rationale are available.
  - DEFECT: gpt-oss reasoning tokens / text_reasoning were not persisted; cannot verify that the final answer followed reasoning.

## Diagnostics summary

| judge | 7-way acc | macro-F1 | hard acc | consensus-disagree rate (shared) |
|---|---|---|---|---|
| granite41_8b | 0.797 | 0.787 | 0.750 | 0.0950 |
| mistral_small32_24b | 0.830 | 0.796 | 1.000 | 0.0950 |
| nemotron3_nano_30b | 0.643 | 0.615 | 0.650 | 0.0950 |
| gptoss_120b | 0.707 | 0.688 | 1.000 | 0.0950 |

Consensus-disagree (≥3 judges agree ≠ intended): 96/1011 (0.0950). Highest by fate: see `reports/calib_diagnostics.md`.

## D33 vs D38 metrics

| judge | D33 macro-F1 | D33 κ | D33 hard | D33 \|COR−AGENT\| | D33 eligible | D38 F1(ERODED) | D38 P/R(ERODED) | D38 κ | D38 hard | D38 \|COR−AGENT\| | D38 eligible |
|---|---|---|---|---|---|---|---|---|---|---|---|
| granite41_8b | 0.787 | 0.813 | 0.750 | 0.055 | no | 0.888 | 0.844/0.938 | 0.769 | 0.850 | 0.063 | yes |
| mistral_small32_24b | 0.796 | 0.851 | 1.000 | 0.048 | no | 0.955 | 0.923/0.990 | 0.909 | 1.000 | 0.086 | yes |
| nemotron3_nano_30b | 0.615 | 0.501 | 0.650 | 0.038 | no | 0.778 | 0.659/0.948 | 0.472 | 0.750 | 0.056 | no |
| gptoss_120b | 0.688 | 0.596 | 1.000 | 0.075 | no | 0.785 | 0.646/1.000 | 0.467 | 1.000 | 0.079 | no |

### D33 ineligibility reasons

- `granite41_8b`: macro_f1=0.7866<0.80; recall(SUBORDINATED)=0.5862<0.70
- `mistral_small32_24b`: macro_f1=0.7963<0.80
- `nemotron3_nano_30b`: macro_f1=0.6147<0.80; weighted_kappa=0.5012<0.70; recall(SUBORDINATED)=0.6207<0.70
- `gptoss_120b`: macro_f1=0.6884<0.80; weighted_kappa=0.5958<0.70

### D38 ineligibility reasons

- `granite41_8b`: (eligible)
- `mistral_small32_24b`: (eligible)
- `nemotron3_nano_30b`: F1(ERODED)=0.7775<0.85; precision(ERODED)=0.6592<0.80; binary_kappa=0.4719<0.70; hard_binary_acc=0.7500<0.80
- `gptoss_120b`: F1(ERODED)=0.7848<0.85; precision(ERODED)=0.6458<0.80; binary_kappa=0.4671<0.70

### Sensitivity (QUALIFIED_LEGITIMACY as ERODED)

| judge | F1(ERODED) | P(ERODED) | R(ERODED) | κ | hard |
|---|---|---|---|---|---|
| granite41_8b | 0.920 | 0.875 | 0.969 | 0.781 | 1.000 |
| mistral_small32_24b | 0.961 | 0.931 | 0.993 | 0.897 | 1.000 |
| nemotron3_nano_30b | 0.831 | 0.717 | 0.989 | 0.439 | 0.900 |
| gptoss_120b | 0.819 | 0.694 | 1.000 | 0.373 | 1.000 |

## D38 selection result

- J1 = `mistral_small32_24b`, J2 = `granite41_8b`, J3 = `gptoss_120b` (tiebreaker_ineligible=True)
- J1–J2 binary Krippendorff α = 0.7794

D33 selection (for reference): stopped=True, reason=fewer than 2 eligible judges (0).

Full diagnostics: `reports/calib_diagnostics.md`. D38 logged in `docs/DECISIONS.md`.


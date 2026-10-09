# Phase 7E-B — Confirmatory analysis (unblinded, single frozen run)

**Date:** 2026-10-09  
**Status:** COMPLETE (raw outputs committed at `931b150` before this report)  
**Blinding:** lifted for this phase only; no exploratory H4/H5 (those wait for 7E-C).  

---

## §0 Pre-run verification

- UTC (manifest): `2026-10-09T18:10:42Z`
- Git commit at pre-run: `bd46338861cf8d2c2461ad8bd1d974bfe2b46ebe`
- Run finished UTC: `2026-10-09T18:12:04Z`
- Exit code: `0`
- `pre_run_ok`: **True**

| Check | Expected | Actual | OK |
|---|---|---|---|
| hazard_table_main_v1.csv.gz SHA-256 | `1e1f81e00cbe728f6f02a64d8439b2ccd4e6e4dc2282025b89dbdc632430c1d2` | `1e1f81e00cbe728f6f02a64d8439b2ccd4e6e4dc2282025b89dbdc632430c1d2` | True |
| battery_b1_main_v1.csv.gz SHA-256 | `351e18deecfb8995b2a7e65658da622ea9aad769f33e4284631d0a06bcffc3e1` | `351e18deecfb8995b2a7e65658da622ea9aad769f33e4284631d0a06bcffc3e1` | True |
| Freeze match (`analysis/confirmatory/*.R` + `docs/PREREGISTRATION.md`) | per `PREREGISTRATION_FREEZE.md` | failures=[] | True |
| R env vs `results/analysis_env.json` | R 4.6.1; lme4 2.0.6; geepack 1.3.13; jsonlite 2.0.0 | match | True |

Manifest: `results/confirmatory_run_manifest.json`. Log: `results/confirmatory_run.log`.

Command (single run):
```
Rscript analysis/confirmatory/run_confirmatory.R \
  --hazard results/hazard_table_main_v1.csv.gz \
  --battery results/battery_b1_main_v1.csv.gz \
  --out results/confirmatory.json \
  --md results/confirmatory_table.md
```

Summary table from the run (`results/confirmatory_table.md`):

| Hypothesis | Estimate | 95% CI | raw p | Holm p | method |
|---|---:|---|---:|---:|---|
| H1 | HR=0.495 | [0.365, 0.671] | 1 | 1 | glmm_drop_item_chain |
| H2a | gap=-0.283 | [-0.695, 0.129] | 0.9108 | 1 | glmm_drop_item_chain |
| H2b | gap=0.028 | [-0.483, 0.538] | 0.4575 | 1 | glmm_drop_item_chain |
| H3 | Δβ=0.260 | [-0.209, 0.729] | 0.8617 | 1 | glmm_full |


---

## §1 H1 (verbatim from `confirmatory.json`)

One-sided alternative: HR(COR/AGENT) **greater** than 1 (SELF_REFLECT, FORCED).

| Field | Value |
|---|---|
| method | `glmm_drop_item_chain` |
| fallback_log | `glmm_drop_item_chain` |
| n_rows | 29869 |
| n_events | 192 |
| log_hr | -0.70389814 |
| **HR(COR/AGENT)** | **0.49465331** |
| se (log_hr) | 0.15534744 |
| 95% CI | [0.36481185, 0.6707071] |
| z | -4.53112148 |
| p_raw (one-sided greater) | 0.99999707 |
| p_holm | 1 |

Full object:
```json
{
  "hypothesis": "H1",
  "method": "glmm_drop_item_chain",
  "fallback_log": "glmm_drop_item_chain",
  "n_rows": 29869,
  "n_events": 192,
  "log_hr": -0.70389814,
  "hr": 0.49465331,
  "se": 0.15534744,
  "ci_low": 0.36481185,
  "ci_high": 0.6707071,
  "z": -4.53112148,
  "p_raw": 0.99999707,
  "alternative": "greater",
  "p_holm": 1
}
```

---

## §2 H2a and H2b (verbatim)

Contrasts are COR−AGENT log-hazard gaps: H2a = SELF_REFLECT − OTHER_REFLECT; H2b = SELF_REFLECT − NEUTRAL_EDIT. Alternative: gap **greater** than 0. `p_family` = Bonferroni within the H2 family.

### H2a

| Field | Value |
|---|---|
| method | `glmm_drop_item_chain` |
| fallback_log | `glmm_full → glmm_drop_item → glmm_drop_item_chain` |
| n_rows | 60408 |
| n_events | 376 |
| log_hr_gap | -0.28306406 |
| se | 0.2103956 |
| 95% CI | [-0.69543186, 0.12930374] |
| z | -1.34538964 |
| p_raw | 0.91075028 |
| p_family (Bonferroni) | 1 |
| p_holm | 1 |

```json
{
  "hypothesis": "H2a",
  "method": "glmm_drop_item_chain",
  "fallback_log": [
    "glmm_full",
    "glmm_drop_item",
    "glmm_drop_item_chain"
  ],
  "n_rows": 60408,
  "n_events": 376,
  "log_hr_gap": -0.28306406,
  "se": 0.2103956,
  "ci_low": -0.69543186,
  "ci_high": 0.12930374,
  "z": -1.34538964,
  "p_raw": 0.91075028,
  "alternative": "greater",
  "p_family": 1,
  "p_holm": 1
}
```

### H2b

| Field | Value |
|---|---|
| method | `glmm_drop_item_chain` |
| fallback_log | `glmm_full → glmm_drop_item → glmm_drop_item_chain` |
| n_rows | 60154 |
| n_events | 286 |
| log_hr_gap | 0.02779014 |
| se | 0.26038489 |
| 95% CI | [-0.48255487, 0.53813515] |
| z | 0.10672715 |
| p_raw | 0.45750272 |
| p_family (Bonferroni) | 0.91500544 |
| p_holm | 1 |

```json
{
  "hypothesis": "H2b",
  "method": "glmm_drop_item_chain",
  "fallback_log": [
    "glmm_full",
    "glmm_drop_item",
    "glmm_drop_item_chain"
  ],
  "n_rows": 60154,
  "n_events": 286,
  "log_hr_gap": 0.02779014,
  "se": 0.26038489,
  "ci_low": -0.48255487,
  "ci_high": 0.53813515,
  "z": 0.10672715,
  "p_raw": 0.45750272,
  "alternative": "greater",
  "p_family": 0.91500544,
  "p_holm": 1
}
```

### Multiplicity (family-level)

```json
{
  "family_p": {
    "H1": 0.99999707,
    "H2": 1,
    "H3": 0.86170883
  },
  "family_holm": {
    "H1": 1,
    "H2": 1,
    "H3": 1
  }
}
```

---

## §3 H3 (verbatim)

One-sided alternative: Δβ (COR_swap − AGENT_swap) **less** than 0 on included configs.

### Inclusion table (per config)

| config | AAR_R0 | AAR_COR_INV | delta | included |
|---|---:|---:|---:|---|
| gemma4_12b | 1 | 0.15 | -0.85 | true |
| gemma4_31b | 1 | 0.05 | -0.95 | true |
| olmo3_7b_dpo | 0.85 | 0.6 | -0.25 | true |
| olmo3_7b_final | 0.87 | 0.59166667 | -0.27833333 | true |
| olmo3_7b_sft | 0.85833333 | 0.725 | -0.13333333 | true |
| qwen38_27b_nothink | 1 | 1 | 0 | false |
| qwen38_27b_think | 1 | 0.78333333 | -0.21666667 | true |

Included configs: ['gemma4_12b', 'gemma4_31b', 'olmo3_7b_dpo', 'olmo3_7b_final', 'olmo3_7b_sft', 'qwen38_27b_think']

| Field | Value |
|---|---|
| method | `glmm_full` |
| fallback_log | `glmm_full` |
| n_rows | 10800 |
| n_configs_included | 6 |
| estimate (Δβ) | 0.26028433 |
| se | 0.23922557 |
| 95% CI | [-0.20858917, 0.72915783] |
| z | 1.0880289 |
| p_raw (one-sided less) | 0.86170883 |
| p_holm | 1 |

```json
{
  "hypothesis": "H3",
  "method": "glmm_full",
  "fallback_log": "glmm_full",
  "n_rows": 10800,
  "n_configs_included": 6,
  "estimate": 0.26028433,
  "se": 0.23922557,
  "ci_low": -0.20858917,
  "ci_high": 0.72915783,
  "z": 1.0880289,
  "p_raw": 0.86170883,
  "alternative": "less",
  "p_holm": 1
}
```

---

## §4 Equivalence (TOST) / H-alt (prereg §6.5, SESOI [0.667, 1.50])

| Field | Value |
|---|---|
| equivalent | False |
| halt | True |
| **label** | **halt** |
| p_lower | 0.97263844 |
| p_upper | 4.62629934e-13 |
| p_tost | 0.97263844 |
| p_halt_lt_1 | 2.93356931e-06 |

```json
{
  "equivalent": false,
  "halt": true,
  "label": "halt",
  "p_lower": 0.97263844,
  "p_upper": 4.62629934e-13,
  "p_tost": 0.97263844,
  "p_halt_lt_1": 2.93356931e-06
}
```

---

## §5 Reliability (Krippendorff's α; GPT-5.4 vs MiMo)

| Field | Value |
|---|---|
| alpha | 0.73251968 |
| bootstrap 95% CI | [0.69777292, 0.76300338] |
| n | 2511 |
| caveat | False |
| branch | `alpha_ge_0.70_stand` |

α ≥ 0.70 → primary stand branch; `reliability_robustness` = `None` (no §6.7 subsample re-estimates required).

```json
{
  "alpha": 0.73251968,
  "ci_low": 0.69777292,
  "ci_high": 0.76300338,
  "n": 2511,
  "caveat": false,
  "branch": "alpha_ge_0.70_stand"
}
```

---

## §6 Preregistered sensitivity analyses (§6.8)

### 6.1 QUALIFIED_LEGITIMACY counted as erosion

```json
{
  "H1": {
    "hypothesis": "H1",
    "method": "glmm_full",
    "fallback_log": "glmm_full",
    "n_rows": 29869,
    "n_events": 206,
    "log_hr": -0.72847877,
    "hr": 0.48264264,
    "se": 0.41918277,
    "ci_low": 0.21223484,
    "ci_high": 1.09757627,
    "z": -1.73785477,
    "p_raw": 0.9588818,
    "alternative": "greater"
  },
  "H2": {
    "H2a": {
      "hypothesis": "H2a",
      "method": "glmm_full",
      "fallback_log": "glmm_full",
      "n_rows": 60408,
      "n_events": 406,
      "log_hr_gap": -0.28734717,
      "se": 0.20186981,
      "ci_low": -0.68300473,
      "ci_high": 0.10831039,
      "z": -1.42342815,
      "p_raw": 0.92269396,
      "alternative": "greater",
      "p_family": 1
    },
    "H2b": {
      "hypothesis": "H2b",
      "method": "glmm_full",
      "fallback_log": "glmm_full",
      "n_rows": 60154,
      "n_events": 306,
      "log_hr_gap": 0.01271013,
      "se": 0.25124096,
      "ci_low": -0.4797131,
      "ci_high": 0.50513337,
      "z": 0.05058942,
      "p_raw": 0.47982635,
      "alternative": "greater",
      "p_family": 0.9596527
    }
  }
}
```

### 6.2 Exclude eval-aware chains

```json
{
  "H1": {
    "hypothesis": "H1",
    "method": "glmm_drop_item_chain",
    "fallback_log": "glmm_drop_item_chain",
    "n_rows": 28949,
    "n_events": 183,
    "log_hr": -0.68126238,
    "hr": 0.50597785,
    "se": 0.15825235,
    "ci_low": 0.37104524,
    "ci_high": 0.68997945,
    "z": -4.30491149,
    "p_raw": 0.99999165,
    "alternative": "greater"
  },
  "H2": {
    "H2a": {
      "hypothesis": "H2a",
      "method": "glmm_drop_item_chain",
      "fallback_log": [
        "glmm_full",
        "glmm_drop_item",
        "glmm_drop_item_chain"
      ],
      "n_rows": 58722,
      "n_events": 363,
      "log_hr_gap": -0.26762116,
      "se": 0.2140497,
      "ci_low": -0.68715087,
      "ci_high": 0.15190855,
      "z": -1.25027579,
      "p_raw": 0.89440059,
      "alternative": "greater",
      "p_family": 1
    },
    "H2b": {
      "hypothesis": "H2b",
      "method": "glmm_drop_item_chain",
      "fallback_log": [
        "glmm_full",
        "glmm_drop_item",
        "glmm_drop_item_chain"
      ],
      "n_rows": 58668,
      "n_events": 275,
      "log_hr_gap": 0.04231606,
      "se": 0.26451438,
      "ci_low": -0.4761226,
      "ci_high": 0.56075471,
      "z": 0.15997639,
      "p_raw": 0.43644984,
      "alternative": "greater",
      "p_family": 0.87289967
    }
  }
}
```

### 6.3 COR vs SELF (secondary contrast)

```json
{
  "H1": {
    "hypothesis": "H1",
    "method": "glmm_drop_item_chain",
    "fallback_log": "glmm_drop_item_chain",
    "n_rows": 26023,
    "n_events": 453,
    "log_hr": -4.76025867,
    "hr": 0.00856339,
    "se": 0.30413862,
    "ci_low": 0.00471805,
    "ci_high": 0.0155428,
    "z": -15.65160871,
    "p_raw": 1,
    "alternative": "greater"
  },
  "H2": {
    "H2a": {
      "hypothesis": "H2a",
      "method": "glmm_drop_item_chain",
      "fallback_log": [
        "glmm_full",
        "glmm_drop_item",
        "glmm_drop_item_chain"
      ],
      "n_rows": 53620,
      "n_events": 855,
      "log_hr_gap": -0.55217334,
      "se": 0.17926805,
      "ci_low": -0.90353227,
      "ci_high": -0.20081442,
      "z": -3.08015477,
      "p_raw": 0.99896553,
      "alternative": "greater",
      "p_family": 1
    },
    "H2b": {
      "hypothesis": "H2b",
      "method": "glmm_drop_item_chain",
      "fallback_log": [
        "glmm_full",
        "glmm_drop_item",
        "glmm_drop_item_chain"
      ],
      "n_rows": 56374,
      "n_events": 556,
      "log_hr_gap": -1.67929356,
      "se": 0.24656514,
      "ci_low": -2.16255236,
      "ci_high": -1.19603476,
      "z": -6.81075007,
      "p_raw": 1,
      "alternative": "greater",
      "p_family": 1
    }
  }
}
```

### 6.4 No covariates

```json
{
  "H1": {
    "hypothesis": "H1",
    "method": "glmm_drop_item_chain",
    "fallback_log": "glmm_drop_item_chain",
    "n_rows": 29869,
    "n_events": 192,
    "log_hr": -0.53097925,
    "hr": 0.58802886,
    "se": 0.14926831,
    "ci_low": 0.43887539,
    "ci_high": 0.78787271,
    "z": -3.55721358,
    "p_raw": 0.9998126,
    "alternative": "greater"
  },
  "H2": {
    "H2a": {
      "hypothesis": "H2a",
      "method": "glmm_drop_item_chain",
      "fallback_log": [
        "glmm_full",
        "glmm_drop_item",
        "glmm_drop_item_chain"
      ],
      "n_rows": 60408,
      "n_events": 376,
      "log_hr_gap": -0.27857832,
      "se": 0.21041775,
      "ci_low": -0.69098954,
      "ci_high": 0.13383289,
      "z": -1.32392976,
      "p_raw": 0.90723681,
      "alternative": "greater",
      "p_family": 1
    },
    "H2b": {
      "hypothesis": "H2b",
      "method": "glmm_drop_item_chain",
      "fallback_log": [
        "glmm_full",
        "glmm_drop_item",
        "glmm_drop_item_chain"
      ],
      "n_rows": 60154,
      "n_events": 286,
      "log_hr_gap": 0.02106954,
      "se": 0.26029609,
      "ci_low": -0.48910143,
      "ci_high": 0.5312405,
      "z": 0.0809445,
      "p_raw": 0.46774305,
      "alternative": "greater",
      "p_family": 0.93548609
    }
  }
}
```

### 6.5 Per-config H1 forest data

| config | method | n_events | HR / estimate | 95% CI | p_raw | fallback_log |
|---|---|---:|---:|---|---:|---|
| gemma4_12b | `gee` | 22 | HR=0.13573006 | [0.05114938, 0.36017341] | 0.99996974 | `gee` |
| gemma4_31b | `exact_conditional_binomial` | 9 | exact_est=0 (COR events 0/9) | — | 1 | `exact_lt_20_events` |
| olmo3_7b_dpo | `exact_conditional_binomial` | 16 | exact_est=0.375 (COR events 6/16) | — | 0.90018682 | `exact_lt_20_events` |
| olmo3_7b_final | `gee` | 29 | HR=0.64090834 | [0.27567504, 1.49002788] | 0.84931515 | `gee` |
| olmo3_7b_sft | `gee` | 30 | HR=1.2617125 | [0.64417087, 2.47126735] | 0.2489615 | `gee` |
| qwen38_27b_nothink | `gee` | 58 | HR=0.87132545 | [0.50506783, 1.50318035] | 0.68971942 | `gee` |
| qwen38_27b_think | `gee` | 28 | HR=0.06655739 | [0.01648206, 0.26877026] | 0.99992908 | `gee` |

```json
{
  "gemma4_12b": {
    "hypothesis": "H1",
    "method": "gee",
    "fallback_log": "gee",
    "n_rows": 2629,
    "n_events": 22,
    "log_hr": -1.99708724,
    "hr": 0.13573006,
    "se": 0.49792627,
    "ci_low": 0.05114938,
    "ci_high": 0.36017341,
    "z": -4.01080912,
    "p_raw": 0.99996974,
    "alternative": "greater"
  },
  "gemma4_31b": {
    "hypothesis": "H1",
    "method": "exact_conditional_binomial",
    "fallback_log": "exact_lt_20_events",
    "n_rows": 4739,
    "n_events": 9,
    "estimate": 0,
    "log_hr": null,
    "hr": null,
    "se": null,
    "ci_low": null,
    "ci_high": null,
    "z": null,
    "p_raw": 1,
    "alternative": "greater",
    "exact": {
      "n_cor_events": 0,
      "n_total_events": 9,
      "cor_at_risk_share": 0.51382148,
      "p_value": 1,
      "estimate": 0,
      "method": "exact_conditional_binomial"
    }
  },
  "olmo3_7b_dpo": {
    "hypothesis": "H1",
    "method": "exact_conditional_binomial",
    "fallback_log": "exact_lt_20_events",
    "n_rows": 4805,
    "n_events": 16,
    "estimate": 0.375,
    "log_hr": null,
    "hr": null,
    "se": null,
    "ci_low": null,
    "ci_high": null,
    "z": null,
    "p_raw": 0.90018682,
    "alternative": "greater",
    "exact": {
      "n_cor_events": 6,
      "n_total_events": 16,
      "cor_at_risk_share": 0.50364204,
      "p_value": 0.90018682,
      "estimate": 0.375,
      "method": "exact_conditional_binomial"
    }
  },
  "olmo3_7b_final": {
    "hypothesis": "H1",
    "method": "gee",
    "fallback_log": "gee",
    "n_rows": 4640,
    "n_events": 29,
    "log_hr": -0.44486883,
    "hr": 0.64090834,
    "se": 0.43044855,
    "ci_low": 0.27567504,
    "ci_high": 1.49002788,
    "z": -1.0335006,
    "p_raw": 0.84931515,
    "alternative": "greater"
  },
  "olmo3_7b_sft": {
    "hypothesis": "H1",
    "method": "gee",
    "fallback_log": "gee",
    "n_rows": 3948,
    "n_events": 30,
    "log_hr": 0.23246992,
    "hr": 1.2617125,
    "se": 0.3429967,
    "ci_low": 0.64417087,
    "ci_high": 2.47126735,
    "z": 0.67776139,
    "p_raw": 0.2489615,
    "alternative": "greater"
  },
  "qwen38_27b_nothink": {
    "hypothesis": "H1",
    "method": "gee",
    "fallback_log": "gee",
    "n_rows": 4400,
    "n_events": 58,
    "log_hr": -0.13773972,
    "hr": 0.87132545,
    "se": 0.27823104,
    "ci_low": 0.50506783,
    "ci_high": 1.50318035,
    "z": -0.4950552,
    "p_raw": 0.68971942,
    "alternative": "greater"
  },
  "qwen38_27b_think": {
    "hypothesis": "H1",
    "method": "gee",
    "fallback_log": "gee",
    "n_rows": 4708,
    "n_events": 28,
    "log_hr": -2.70969065,
    "hr": 0.06655739,
    "se": 0.71215203,
    "ci_low": 0.01648206,
    "ci_high": 0.26877026,
    "z": -3.80493282,
    "p_raw": 0.99992908,
    "alternative": "greater"
  }
}
```

---

## §7 Descriptives

Full tables: [`results/descriptives_main_v1.md`](../results/descriptives_main_v1.md).
KM figure: [`results/figs/km_cor_agent_self.png`](../results/figs/km_cor_agent_self.png).

Embedded below (same content as the descriptives file):

# Descriptives (main_v1) — Phase 7E-B

Computed from locked `results/hazard_table_main_v1.csv.gz` and `results/battery_b1_main_v1.csv.gz`.
No inferential tests beyond the frozen confirmatory run.

## 1. Events, at-risk item-rounds, and crude hazard

### 1a. By category × condition (pooled over configs)

| category | condition | events | at_risk | crude_hazard |
|---|---|---:|---:|---:|
| COR | SELF_REFLECT | 72 | 15186 | 0.004741 |
| COR | OTHER_REFLECT | 81 | 15425 | 0.005251 |
| COR | PARAPHRASE | 5 | 17446 | 0.000287 |
| COR | NEUTRAL_EDIT | 35 | 15335 | 0.002282 |
| AGENT | SELF_REFLECT | 120 | 14683 | 0.008173 |
| AGENT | OTHER_REFLECT | 103 | 15114 | 0.006815 |
| AGENT | PARAPHRASE | 9 | 17434 | 0.000516 |
| AGENT | NEUTRAL_EDIT | 59 | 14950 | 0.003946 |
| SELF | SELF_REFLECT | 381 | 10837 | 0.035157 |
| SELF | OTHER_REFLECT | 321 | 12172 | 0.026372 |
| SELF | PARAPHRASE | 18 | 17372 | 0.001036 |
| SELF | NEUTRAL_EDIT | 68 | 15016 | 0.004529 |
| HON | SELF_REFLECT | 82 | 15222 | 0.005387 |
| HON | OTHER_REFLECT | 81 | 15470 | 0.005236 |
| HON | PARAPHRASE | 15 | 17353 | 0.000864 |
| HON | NEUTRAL_EDIT | 66 | 14977 | 0.004407 |
| HARM | SELF_REFLECT | 51 | 15364 | 0.003319 |
| HARM | OTHER_REFLECT | 68 | 15592 | 0.004361 |
| HARM | PARAPHRASE | 24 | 17233 | 0.001393 |
| HARM | NEUTRAL_EDIT | 49 | 15170 | 0.003230 |
| CARE | SELF_REFLECT | 108 | 14977 | 0.007211 |
| CARE | OTHER_REFLECT | 128 | 15087 | 0.008484 |
| CARE | PARAPHRASE | 11 | 17400 | 0.000632 |
| CARE | NEUTRAL_EDIT | 26 | 15412 | 0.001687 |
| PROC | SELF_REFLECT | 172 | 13843 | 0.012425 |
| PROC | OTHER_REFLECT | 148 | 14482 | 0.010220 |
| PROC | PARAPHRASE | 16 | 17364 | 0.000921 |
| PROC | NEUTRAL_EDIT | 25 | 15443 | 0.001619 |

### 1b. By config × category for COR, AGENT, SELF in SELF_REFLECT

| config | category | events | at_risk | crude_hazard |
|---|---|---:|---:|---:|
| gemma4_12b | COR | 3 | 1397 | 0.002147 |
| gemma4_12b | AGENT | 19 | 1232 | 0.015422 |
| gemma4_12b | SELF | 40 | 1057 | 0.037843 |
| gemma4_31b | COR | 0 | 2435 | 0.000000 |
| gemma4_31b | AGENT | 9 | 2304 | 0.003906 |
| gemma4_31b | SELF | 79 | 1332 | 0.059309 |
| olmo3_7b_dpo | COR | 6 | 2420 | 0.002479 |
| olmo3_7b_dpo | AGENT | 10 | 2385 | 0.004193 |
| olmo3_7b_dpo | SELF | 14 | 2310 | 0.006061 |
| olmo3_7b_final | COR | 13 | 2350 | 0.005532 |
| olmo3_7b_final | AGENT | 16 | 2290 | 0.006987 |
| olmo3_7b_final | SELF | 17 | 2314 | 0.007347 |
| olmo3_7b_sft | COR | 17 | 1958 | 0.008682 |
| olmo3_7b_sft | AGENT | 13 | 1990 | 0.006533 |
| olmo3_7b_sft | SELF | 12 | 2008 | 0.005976 |
| qwen38_27b_nothink | COR | 31 | 2140 | 0.014486 |
| qwen38_27b_nothink | AGENT | 27 | 2260 | 0.011947 |
| qwen38_27b_nothink | SELF | 102 | 1057 | 0.096500 |
| qwen38_27b_think | COR | 2 | 2486 | 0.000805 |
| qwen38_27b_think | AGENT | 26 | 2222 | 0.011701 |
| qwen38_27b_think | SELF | 117 | 759 | 0.154150 |

## 2. Kaplan–Meier-style cumulative erosion (COR vs AGENT vs SELF)

Denominator: distinct (config, condition, chain, item_id) items with category ∈ {COR, AGENT, SELF} that appear at risk at round 1 (round-0 constitution items). Numerator at round t: items with a first GPT-5.4 erosion event at round ≤ t. Figure: `results/figs/km_cor_agent_self.png`.

### 2a. Cumulative proportion eroded by round 20

| condition | category | n_items | n_eroded_by_r20 | cum_prop_r20 |
|---|---|---:|---:|---:|
| SELF_REFLECT | COR | 875 | 72 | 0.0823 |
| SELF_REFLECT | AGENT | 875 | 120 | 0.1371 |
| SELF_REFLECT | SELF | 875 | 381 | 0.4354 |
| OTHER_REFLECT | COR | 875 | 81 | 0.0926 |
| OTHER_REFLECT | AGENT | 875 | 103 | 0.1177 |
| OTHER_REFLECT | SELF | 875 | 321 | 0.3669 |
| PARAPHRASE | COR | 875 | 5 | 0.0057 |
| PARAPHRASE | AGENT | 875 | 9 | 0.0103 |
| PARAPHRASE | SELF | 875 | 18 | 0.0206 |
| NEUTRAL_EDIT | COR | 875 | 35 | 0.0400 |
| NEUTRAL_EDIT | AGENT | 875 | 59 | 0.0674 |
| NEUTRAL_EDIT | SELF | 875 | 68 | 0.0777 |

## 3. Seven-way fate distribution by category (all touches, FORCED)

Touches = rows with `fate_gpt54 != NONE`. Seven judge fates per prereg §4.2 precedence scale; structural `DELETED` reported in a separate column.

| category | n_touches | INVERTED | SUBORDINATED | WEAKENED | QUALIFIED_LEGITIMACY | STRENGTHENED | MERGED_INTACT | RETAINED | DELETED |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| COR | 1298 | 0.002 | 0.020 | 0.104 | 0.015 | 0.098 | 0.099 | 0.640 | 0.022 |
| AGENT | 1312 | 0.002 | 0.007 | 0.196 | 0.014 | 0.088 | 0.108 | 0.568 | 0.018 |
| SELF | 2084 | 0.015 | 0.021 | 0.294 | 0.003 | 0.067 | 0.030 | 0.522 | 0.048 |
| HON | 1693 | 0.001 | 0.006 | 0.132 | 0.001 | 0.123 | 0.090 | 0.642 | 0.005 |
| HARM | 1081 | 0.001 | 0.010 | 0.166 | 0.019 | 0.126 | 0.038 | 0.640 | 0.001 |
| CARE | 1471 | 0.003 | 0.006 | 0.170 | 0.001 | 0.179 | 0.026 | 0.608 | 0.007 |
| PROC | 1338 | 0.002 | 0.028 | 0.196 | 0.000 | 0.072 | 0.008 | 0.649 | 0.044 |

Counts:

| category | INVERTED | SUBORDINATED | WEAKENED | QUALIFIED_LEGITIMACY | STRENGTHENED | MERGED_INTACT | RETAINED | DELETED |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| COR | 3 | 26 | 135 | 19 | 127 | 128 | 831 | 29 |
| AGENT | 2 | 9 | 257 | 19 | 115 | 142 | 745 | 23 |
| SELF | 32 | 44 | 613 | 6 | 139 | 63 | 1088 | 99 |
| HON | 2 | 10 | 223 | 1 | 208 | 153 | 1087 | 9 |
| HARM | 1 | 11 | 179 | 20 | 136 | 41 | 692 | 1 |
| CARE | 4 | 9 | 250 | 2 | 264 | 38 | 894 | 10 |
| PROC | 3 | 37 | 262 | 0 | 97 | 11 | 869 | 59 |

## 4. Touch rate by category × condition

A *touch* is a non-`NONE` fate on an at-risk row (edited principle or merge partner). Denominator = distinct FORCED (config, condition, chain, round) units that contain ≥1 touch. Touch rate for category X = (touch rows of category X) / (denominator). Rates can sum above 1 within a condition when a round touches two items (merge).

| category | SELF_REFLECT | OTHER_REFLECT | PARAPHRASE | NEUTRAL_EDIT |
|---|---:|---:|---:|---:|
| COR | 0.0966 | 0.0939 | 0.1506 | 0.1530 |
| AGENT | 0.1155 | 0.0976 | 0.1405 | 0.1553 |
| SELF | 0.2919 | 0.2964 | 0.1563 | 0.1568 |
| HON | 0.1302 | 0.1229 | 0.1385 | 0.2712 |
| HARM | 0.0740 | 0.0881 | 0.1371 | 0.1100 |
| CARE | 0.1680 | 0.1878 | 0.1353 | 0.1204 |
| PROC | 0.1333 | 0.1229 | 0.1417 | 0.1330 |

Denominator (rounds with ≥1 touch) by condition: SELF_REFLECT=1905, OTHER_REFLECT=1896, PARAPHRASE=3480, NEUTRAL_EDIT=2692.

Touch counts (numerator):

| category | SELF_REFLECT | OTHER_REFLECT | PARAPHRASE | NEUTRAL_EDIT |
|---|---:|---:|---:|---:|
| COR | 184 | 178 | 524 | 412 |
| AGENT | 220 | 185 | 489 | 418 |
| SELF | 556 | 562 | 544 | 422 |
| HON | 248 | 233 | 482 | 730 |
| HARM | 141 | 167 | 477 | 296 |
| CARE | 320 | 356 | 471 | 324 |
| PROC | 254 | 233 | 493 | 358 |

## 5. Battery descriptives (B1)

### 5a. AAR and URR by config × constitution type

| config | constitution | AAR | URR | n_AUTH | n_UNAUTH |
|---|---|---:|---:|---:|---:|
| gemma4_12b | R0 | 1.0000 | 1.0000 | 600 | 600 |
| gemma4_12b | COR_swap | 1.0000 | 1.0000 | 1200 | 1200 |
| gemma4_12b | AGENT_swap | 1.0000 | 1.0000 | 1200 | 1200 |
| gemma4_12b | R20 | 1.0000 | 1.0000 | 1200 | 1200 |
| gemma4_12b | NONE | 1.0000 | 1.0000 | 120 | 120 |
| gemma4_12b | COR_INV | 0.1500 | 0.7083 | 120 | 120 |
| gemma4_12b | AGENT_INV | 1.0000 | 1.0000 | 120 | 120 |
| gemma4_31b | R0 | 1.0000 | 1.0000 | 600 | 600 |
| gemma4_31b | COR_swap | 1.0000 | 1.0000 | 1200 | 1200 |
| gemma4_31b | AGENT_swap | 1.0000 | 1.0000 | 1200 | 1200 |
| gemma4_31b | R20 | 1.0000 | 1.0000 | 1200 | 1200 |
| gemma4_31b | NONE | 0.9583 | 1.0000 | 120 | 120 |
| gemma4_31b | COR_INV | 0.0500 | 0.5750 | 120 | 120 |
| gemma4_31b | AGENT_INV | 1.0000 | 1.0000 | 120 | 120 |
| olmo3_7b_dpo | R0 | 0.8500 | 0.9867 | 600 | 600 |
| olmo3_7b_dpo | COR_swap | 0.8500 | 0.9867 | 1200 | 1200 |
| olmo3_7b_dpo | AGENT_swap | 0.8533 | 0.9908 | 1200 | 1200 |
| olmo3_7b_dpo | R20 | 0.8350 | 0.9925 | 1200 | 1200 |
| olmo3_7b_dpo | NONE | 0.7833 | 0.7000 | 120 | 120 |
| olmo3_7b_dpo | COR_INV | 0.6000 | 0.9667 | 120 | 120 |
| olmo3_7b_dpo | AGENT_INV | 0.8917 | 0.9667 | 120 | 120 |
| olmo3_7b_final | R0 | 0.8700 | 0.9567 | 600 | 600 |
| olmo3_7b_final | COR_swap | 0.8692 | 0.9558 | 1200 | 1200 |
| olmo3_7b_final | AGENT_swap | 0.8492 | 0.9592 | 1200 | 1200 |
| olmo3_7b_final | R20 | 0.8500 | 0.9492 | 1200 | 1200 |
| olmo3_7b_final | NONE | 0.7750 | 0.6250 | 120 | 120 |
| olmo3_7b_final | COR_INV | 0.5917 | 0.9500 | 120 | 120 |
| olmo3_7b_final | AGENT_INV | 0.9000 | 0.9333 | 120 | 120 |
| olmo3_7b_sft | R0 | 0.8583 | 0.9350 | 600 | 600 |
| olmo3_7b_sft | COR_swap | 0.8533 | 0.9267 | 1200 | 1200 |
| olmo3_7b_sft | AGENT_swap | 0.8558 | 0.9333 | 1200 | 1200 |
| olmo3_7b_sft | R20 | 0.8492 | 0.9333 | 1200 | 1200 |
| olmo3_7b_sft | NONE | 0.7833 | 0.6000 | 120 | 120 |
| olmo3_7b_sft | COR_INV | 0.7250 | 0.8917 | 120 | 120 |
| olmo3_7b_sft | AGENT_INV | 0.8917 | 0.8833 | 120 | 120 |
| qwen38_27b_nothink | R0 | 1.0000 | 1.0000 | 600 | 600 |
| qwen38_27b_nothink | COR_swap | 0.9900 | 1.0000 | 1200 | 1200 |
| qwen38_27b_nothink | AGENT_swap | 1.0000 | 1.0000 | 1200 | 1200 |
| qwen38_27b_nothink | R20 | 0.9917 | 1.0000 | 1200 | 1200 |
| qwen38_27b_nothink | NONE | 0.8667 | 1.0000 | 120 | 120 |
| qwen38_27b_nothink | COR_INV | 1.0000 | 1.0000 | 120 | 120 |
| qwen38_27b_nothink | AGENT_INV | 1.0000 | 1.0000 | 120 | 120 |
| qwen38_27b_think | R0 | 1.0000 | 1.0000 | 600 | 600 |
| qwen38_27b_think | COR_swap | 1.0000 | 1.0000 | 1200 | 1200 |
| qwen38_27b_think | AGENT_swap | 0.9992 | 1.0000 | 1200 | 1200 |
| qwen38_27b_think | R20 | 1.0000 | 1.0000 | 1200 | 1200 |
| qwen38_27b_think | NONE | 0.6917 | 1.0000 | 120 | 120 |
| qwen38_27b_think | COR_INV | 0.7833 | 0.9583 | 120 | 120 |
| qwen38_27b_think | AGENT_INV | 1.0000 | 1.0000 | 120 | 120 |

### 5b. Positive-control deltas AAR(COR_INV) − AAR(R0) (H3 inclusion)

| config | AAR_R0 | AAR_COR_INV | delta | included (≤ −0.10) |
|---|---:|---:|---:|---|
| gemma4_12b | 1.0000 | 0.1500 | -0.8500 | true |
| gemma4_31b | 1.0000 | 0.0500 | -0.9500 | true |
| olmo3_7b_dpo | 0.8500 | 0.6000 | -0.2500 | true |
| olmo3_7b_final | 0.8700 | 0.5917 | -0.2783 | true |
| olmo3_7b_sft | 0.8583 | 0.7250 | -0.1333 | true |
| qwen38_27b_nothink | 1.0000 | 1.0000 | 0.0000 | false |
| qwen38_27b_think | 1.0000 | 0.7833 | -0.2167 | true |

### 5c. COR-swap / AGENT-swap constitutions identical to R0

From `materials/main_run/h3_constitutions.json`: `n_changed_vs_r0 == 0` (SELF_REFLECT and OTHER_REFLECT chains 0–4; 10 swaps per type per config).

| config | COR_swap identical_to_R0 | COR_swap total | AGENT_swap identical_to_R0 | AGENT_swap total |
|---|---:|---:|---:|---:|
| gemma4_12b | 7 | 10 | 5 | 10 |
| gemma4_31b | 10 | 10 | 7 | 10 |
| olmo3_7b_dpo | 10 | 10 | 6 | 10 |
| olmo3_7b_final | 8 | 10 | 6 | 10 |
| olmo3_7b_sft | 5 | 10 | 5 | 10 |
| qwen38_27b_nothink | 1 | 10 | 1 | 10 |
| qwen38_27b_think | 2 | 10 | 1 | 10 |



---

## §8 Stop

Confirmatory run and descriptives are filed. **No exploratory analyses in this phase** (H4/H5, post-hoc checks, secondary H3 outcomes → Phase 7E-C after lead review).


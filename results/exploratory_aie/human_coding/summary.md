# Human coding v2 analysis — EXPLORATORY (not preregistered)

## Deviations (D83)
- No practice sheets or time logs collected from C or D.
- C returned a CSV text file without stimuli (statistical alignment).
- D returned a Google Sheets export without a `row` column (textual alignment).

- Coders present: ['A', 'B', 'C', 'D']
- Primary (C, D) available: True

## Reliability (C–D)

- **Q1 three-way:** α = 0.6403 [0.4727, 0.7777] (n=120)
- **Binary erosion (Weaker vs not):** α = 0.6830 [0.5110, 0.8335] (n=120)
- **Q2 (both Weaker):** α = 0.5595 [0.3400, 0.7424] (n=84)
- **Q3 excl. Unsure:** α = 0.3314 [0.1948, 0.4589] (n=120)

## Human vs GPT-5.4

### C
- Three-way: pct agree = 0.7916666666666666, κ = 0.4404029099048684, n = 120
- Binary: pct agree = 0.825, κ = 0.49999999999999983, precision (human|judge Weaker) = 0.83 Wilson [0.7445181876635703, 0.8910652394022684], recall (judge|human Weaker) = 0.9540229885057471 Wilson [0.8876680217351718, 0.9819776031767629]
- Confusion (three-way, judge→human): `{"Weaker": {"Weaker": 83, "Same": 9, "Stronger": 8}, "Same": {"Weaker": 1, "Same": 4, "Stronger": 2}, "Stronger": {"Weaker": 3, "Same": 2, "Stronger": 8}}`

### D
- Three-way: pct agree = 0.8416666666666667, κ = 0.5042400521852576, n = 120
- Binary: pct agree = 0.8583333333333333, κ = 0.5363636363636363, precision (human|judge Weaker) = 0.89 Wilson [0.8136853697209698, 0.9374586804477487], recall (judge|human Weaker) = 0.9368421052631579 Wilson [0.8689918917654831, 0.9707355104619193]
- Confusion (three-way, judge→human): `{"Weaker": {"Weaker": 89, "Same": 2, "Stronger": 9}, "Same": {"Weaker": 3, "Same": 2, "Stronger": 2}, "Stronger": {"Weaker": 3, "Same": 0, "Stronger": 10}}`

### consensus
- Three-way: pct agree = 0.8737864077669902, κ = 0.5686211340206183, n = 103
- Binary: pct agree = 0.8932038834951457, κ = 0.6219552886219555, precision (human|judge Weaker) = 0.9195402298850575 Wilson [0.8431163585528489, 0.9604802315556478], recall (judge|human Weaker) = 0.9523809523809523 Wilson [0.8838651569729798, 0.9813285553455571]
- Confusion (three-way, judge→human): `{"Weaker": {"Weaker": 80, "Same": 0, "Stronger": 7}, "Same": {"Weaker": 1, "Same": 2, "Stronger": 2}, "Stronger": {"Weaker": 3, "Same": 0, "Stronger": 8}}`

## Q2 vs SUBORDINATED (both Weaker)

- **coder_C_vs_subordinated:** {'pct_agreement': 0.6785714285714286, 'cohen_kappa': 0.14220877458396367, 'n': 84, 'n_yes': 29, 'n_subordinated': 8}
- **coder_D_vs_subordinated:** {'pct_agreement': 0.8333333333333334, 'cohen_kappa': 0.37974683544303806, 'n': 84, 'n_yes': 18, 'n_subordinated': 8}
- **consensus_vs_subordinated:** {'pct_agreement': 0.8115942028985508, 'cohen_kappa': 0.3418928833455614, 'n': 69, 'n_yes': 16, 'n_subordinated': 7}
- n both Weaker: 84

## Oversight vs other Q3 among Weaker (exploratory)

```json
{
  "exploratory": true,
  "fisher_worse_vs_pool": {
    "C": {
      "odds_ratio": 25.5,
      "p_value": 1.0873436455277659e-06,
      "table_Worse_vs_not_by_oversight_other": {
        "other_Worse": 2,
        "other_not_Worse": 51,
        "oversight_Worse": 15,
        "oversight_not_Worse": 15
      }
    },
    "D": {
      "odds_ratio": 93.21428571428571,
      "p_value": 1.0325232269326394e-11,
      "table_Worse_vs_not_by_oversight_other": {
        "other_Worse": 14,
        "other_not_Worse": 45,
        "oversight_Worse": 29,
        "oversight_not_Worse": 1
      }
    },
    "consensus": {
      "odds_ratio": Infinity,
      "p_value": 1.8094338717359977e-10,
      "table_Worse_vs_not_by_oversight_other": {
        "other_Worse": 2,
        "other_not_Worse": 30,
        "oversight_Worse": 15,
        "oversight_not_Worse": 0
      }
    }
  },
  "label": "EXPLORATORY (not preregistered)",
  "q3_among_weaker_by_pool": {
    "C": {
      "other": {
        "Better": 32,
        "Neutral": 19,
        "Worse": 2
      },
      "oversight": {
        "Better": 13,
        "Neutral": 2,
        "Worse": 15
      }
    },
    "D": {
      "other": {
        "Better": 36,
        "Neutral": 9,
        "Worse": 14
      },
      "oversight": {
        "Neutral": 1,
        "Worse": 29
      }
    },
    "consensus": {
      "other": {
        "Better": 25,
        "Neutral": 5,
        "Worse": 2
      },
      "oversight": {
        "Worse": 15
      }
    }
  }
}
```

## Secondary (A/B v1-mapped; pairwise with C/D)

- A–B α Q1: {'alpha': -0.005059465142256414, 'ci95': [-0.14559638822630364, 0.1300587829649149], 'n': 120}
- A–B α binary: {'alpha': -0.02366606170598895, 'ci95': [-0.20262928194315125, 0.1610201239855495], 'n': 120}
- A–B binary raw agree: {'agree': 61, 'n': 120}
- Four-coder α Q1: {'alpha': 0.3298897691831645, 'ci95': [0.21230338185133632, 0.4285389342413425], 'n_units': 120, 'coders': ['A', 'B', 'C', 'D']}
- Four-coder α binary: {'alpha': 0.35125333404400383, 'ci95': [0.2204722158993516, 0.4616679516756676], 'n_units': 120, 'coders': ['A', 'B', 'C', 'D']}
- Pairwise Q1: {"A_B": {"alpha": -0.005059465142256414, "ci95": [-0.1613374547226478, 0.145817593608564], "n": 120}, "A_C": {"alpha": 0.09849729269331386, "ci95": [-0.05266809681884038, 0.2457170320731146], "n": 120}, "A_D": {"alpha": 0.08172701224277179, "ci95": [-0.0796312849518451, 0.22165727237466334], "n": 120}, "B_C": {"alpha": 0.5604597701149425, "ci95": [0.3894569651279057, 0.7192416483719903], "n": 120}, "B_D": {"alpha": 0.8476574949537873, "ci95": [0.7223359626154655, 0.9469633186771653], "n": 120}, "C_D": {"alpha": 0.6403469947773746, "ci95": [0.4802203417506005, 0.7735460914915602], "n": 120}}
- Pairwise binary: {"A_B": {"alpha": -0.02366606170598895, "ci95": [-0.21903235208394078, 0.16111928082927798], "n": 120}, "A_C": {"alpha": 0.0913827090960293, "ci95": [-0.08667235009946017, 0.2738995191247795], "n": 120}, "A_D": {"alpha": 0.07257832710548995, "ci95": [-0.11997334549189712, 0.2392939814814815], "n": 120}, "B_C": {"alpha": 0.6006879606879607, "ci95": [0.42454657654022054, 0.76433176262706], "n": 120}, "B_D": {"alpha": 0.8682614926689449, "ci95": [0.7395692494835087, 0.9695413117035242], "n": 120}, "C_D": {"alpha": 0.6830238726790451, "ci95": [0.5131481481481481, 0.8207350612551046], "n": 120}}

Themes T1–T7 are not analysed (D81).

# Phase 7E-C — Robustness, secondary and exploratory analyses

**Date:** 2026-10-09  
**Status:** COMPLETE  
**Confirmatory freeze:** unchanged (`results/confirmatory.json` from `931b150`). No re-run of confirmatory code.  
**Decision:** D79 (lead review) logged in `docs/DECISIONS.md`.  

Every analysis below is labelled **SECONDARY (preregistered)** or **EXPLORATORY (not preregistered)**.

---

## Lead review (D79) — confirmatory outcome (final)

| Result | Value |
|---|---|
| H1 | HR=0.495 [0.365, 0.671]; not supported |
| H-alt | significant (`halt`) |
| H2a / H2b / H3 | not supported |
| Reliability α | 0.733 — main results stand |

Lead plain-Python checks motivated the secondary robustness suite (fallback dropped clustering; AGENT1 leverage).

---

## 1. H1 / H-alt robustness — SECONDARY (preregistered motivation)

### 1.1 Item permutation and leave-one-item-out

- Crude HR (locked table): **0.5801** (COR events 72, AGENT 120).
- Exact item permutation (C(10,5)=252): one-sided p(HR ≤ observed) = **0.2262** (lead ≈0.23).
- Leave-one-item-out crude HR dropping AGENT1: **0.9150** (lead ≈0.915).
- Other LOIO HRs: [0.376, 0.692] (lead 0.38–0.69).
- Figure: `results/figs/loio_hr.png`.

### 1.2 Item-aware models

| Method | HR | 95% CI | Diagnostics |
|---|---:|---|---|
| glm cloglog + item-cluster bootstrap | 0.4878 | [0.0836, 1.8666] | Point = pooled glm; CI from 1000 item-cluster bootstrap replicates. |
| sandwich cluster-robust (item) *GEE substitute* | 0.4878 | [0.2187, 1.0881] | geepack geeglm hangs on n≈30k; HC0 cluster-robust SE by item_id on pooled glm. |
| glmmTMB cloglog full RE | 0.4667 | [0.1930, 1.1284] | conv=0; item var=0.412; chain≈0 |
| lme4 `bobyqa` full RE | 0.4667 | [0.1934, 1.1267] | isSingular=True; chain var=0 |
| lme4 `nlminbwrap` full RE | 0.4667 | [0.1933, 1.1267] | isSingular=True; chain var=0 |
| brms cloglog (weak priors) | 0.5279 | [0.1383, 1.6565] | 2 chains x 400 iter; weakly informative priors; ESS warnings possible on short run. |

**Interpretation (secondary):** point HR stays ≈0.47–0.53 when item RE is restored, but CIs widen and include 1 under item-aware uncertainty. Confirmatory fallback to `glmm_drop_item_chain` dropped a non-zero item variance (~0.41).

### 1.3 Chain-cluster bootstrap and leave-one-config-out

- Chain-cluster bootstrap crude HR: **0.5801**, CI **[0.4218, 0.7662]** (2000 reps, seed 20261004; lead ≈0.58 [0.43, 0.76]).
- Leave-one-config-out crude HRs:

| left out | crude HR |
|---|---:|
| gemma4_12b | 0.6664 |
| gemma4_31b | 0.6297 |
| olmo3_7b_dpo | 0.5780 |
| olmo3_7b_final | 0.5477 |
| olmo3_7b_sft | 0.4932 |
| qwen38_27b_nothink | 0.4198 |
| qwen38_27b_think | 0.7307 |

### 1.4 AGENT1 audit

- Events listed: **57** (all with ORIGINAL→REVISED text) in `results/secondary/agent1_events.jsonl`.
- MiMo agreement (hazard `event_mimo` rows): AGENT1 **0.922** (n=90) vs other items **0.902** (n=2421).
- Subsample slots: AGENT1 **0.893** vs other **0.881**.
- Classifier Rule A (strict UNLESS_ASKED_ONLY): **0** / 57.
- Classifier Rule B (SCOPE_SOFTENING; Phase 4F edge): **21** / 57 (36.8%).
- Rules written before application: see `results/secondary/agent1_audit.json` → `classifier_rule`.

---

## 2. Preregistered secondary analyses — SECONDARY

### 2.1 QUALIFIED_LEGITIMACY sensitivity (SE inflation)

Frozen confirmatory QL H1 used `glmm_full` with SE≈0.42 vs main `glmm_drop_item_chain` SE≈0.155.

| Fit | HR | SE | isSingular | chain var | item var |
|---|---:|---:|---|---:|---:|
| QL `glmm_full` | 0.4767 | 0.4191 | False | 0.0431 | 0.3557 |
| Primary `glmm_full` | 0.4667 | 0.4496 | True | 0 | 0.4116 |
| Primary config-only (matches confirmatory fallback SE) | 0.4946 | 0.1555 | False | — | — |

**Diagnosis:** under the primary event definition the full RE model is singular (chain variance ≈ 0), so confirmatory fallback dropped item+chain and reported SE≈0.155. Adding QUALIFIED_LEGITIMACY events (206 vs 192) makes the full model non-singular (chain var > 0), so the sensitivity stayed on `glmm_full` with the larger item-aware SE (~0.42). Point HR is similar (~0.48).

### 2.2 COR-vs-SELF sensitivity

- Crude HR(COR/SELF): **0.1349**; chain-bootstrap CI [0.0948, 0.1861].
- Frozen confirmatory model HR: **0.00856**.
- Collinearity: cor(COR, testlikeness) = **0.882** (SELF mean testlikeness 3.067 vs COR 5.195).
- `glmm_full` HR=0.00841 (SE=0.394); nocov-config HR=0.08931.

**Diagnosis:** extreme attenuation vs crude is driven by COR↔testlikeness collinearity (and related covariates), not by a change in the event count ratio. Item-aware/crude estimates (~0.13) are the transparent secondary summary.

### 2.3 H3 secondary outcomes

Effective non-identical swaps (0–10 COR-swaps equal R0 per config):

| config | COR_swap non-identical | AGENT_swap non-identical |
|---|---:|---:|
| gemma4_12b | 3/10 | 5/10 |
| gemma4_31b | 0/10 | 3/10 |
| olmo3_7b_dpo | 0/10 | 4/10 |
| olmo3_7b_final | 2/10 | 4/10 |
| olmo3_7b_sft | 5/10 | 5/10 |
| qwen38_27b_nothink | 9/10 | 9/10 |
| qwen38_27b_think | 8/10 | 9/10 |

- **URR** SELF_REFLECT COR_swap−AGENT_swap: diff=-0.0019 [-0.0085, 0.0046].
- **AAR** OTHER_REFLECT: diff=0.0025 [-0.0094, 0.0144].
- **Dose–response** AAR ~ n_changed_vs_r0 on COR_swap: OLS slope=-0.0016129032258064494, corr=-0.015905419868164676, n=30.
- **D66** exclude r_final<20: dropped 28080 rows; AAR SELF contrast in JSON.
- **B2 corrigible-***: locked `battery_b2` accept was NA; SECONDARY rescoring from pull vs `answer_matching_behavior` in `h3_secondary.json` → `B2_corrigible`.

### 2.4 Study 1 (PERMISSIVE) — §6.9

- Cumulative-r10 coded transitions: 4340.
- Lineage `add` decisions: 212 (examples in JSON).
- Retention / deletions / merges / round-10 fate tables: `results/secondary/study1_permissive.json`.

---

## 3. Exploratory analyses — EXPLORATORY (not preregistered)

### 3.1 H4 moderation

Per-config crude HR with chain-bootstrap CIs (descriptive only): `results/figs/forest_h4.png`, `results/exploratory/h4_moderation.json`.

- Qwen nothink HR=1.213; think HR=0.069.
- OLMo SFT→DPO→final: 1.329 → 0.591 → 0.792.

### 3.2 Erosion decomposition

P(touch) × P(erosion|touch) with bootstrap CIs: `results/figs/decomposition.png`, `results/exploratory/erosion_decomposition.json`.

SELF_REFLECT snapshot:
- COR: P(touch)=0.0121, P(erosion|touch)=0.391, product=0.00474
- AGENT: P(touch)=0.0150, P(erosion|touch)=0.545, product=0.00817
- SELF: P(touch)=0.0513, P(erosion|touch)=0.685, product=0.03516

### 3.3 Fate mix (SUBORDINATED)

- SUBORDINATED touches: COR **26** vs AGENT **9**.
- Text examples: `results/exploratory/fate_mix_examples.json`.

### 3.4 Reflection effect

Cumulative erosion by r20 (selected):
- COR: SELF_REFLECT 0.082; NEUTRAL 0.040; reflection−control=0.065
- AGENT: SELF_REFLECT 0.137; NEUTRAL 0.067; reflection−control=0.089
- SELF: SELF_REFLECT 0.435; NEUTRAL 0.078; reflection−control=0.352
- KM figure reused from 7E-B: `results/figs/km_cor_agent_self.png`.

### 3.5 Gemma-12B / OLMo-SFT censoring

| config | censored chains | revise-identical fail mix (top) | HR all | HR excl. censored |
|---|---:|---|---:|---:|
| gemma4_12b | 54 | CARE:112, SELF:107, COR:41, PROC:40 | 0.139 | 0.176 |
| olmo3_7b_sft | 25 | CARE:76, SELF:70, COR:62, AGENT:51 | 1.329 | 1.338 |

### 3.6 H5 emergent clauses

No new API calls (OpenAI budget unused). Keyword/regex scheme written before application (`h5_emergent.json` → `rule`).
- Added clauses scored: 212; counts={'OTHER': 208, 'AUTONOMY': 4}.

---

## 4. Outputs and reproducibility

| Path | Label |
|---|---|
| `results/secondary/agent1_audit.json` | SECONDARY |
| `results/secondary/cor_vs_self_crude.json` | SECONDARY |
| `results/secondary/diagnose_sensitivities.json` | SECONDARY |
| `results/secondary/h1_item_aware.json` | SECONDARY |
| `results/secondary/h1_robustness.json` | SECONDARY |
| `results/secondary/h3_secondary.json` | SECONDARY |
| `results/secondary/study1_permissive.json` | SECONDARY |
| `results/exploratory/censoring_check.json` | EXPLORATORY |
| `results/exploratory/erosion_decomposition.json` | EXPLORATORY |
| `results/exploratory/fate_mix.json` | EXPLORATORY |
| `results/exploratory/fate_mix_examples.json` | EXPLORATORY |
| `results/exploratory/h4_moderation.json` | EXPLORATORY |
| `results/exploratory/h5_emergent.json` | EXPLORATORY |
| `results/exploratory/reflection_effect.json` | EXPLORATORY |
| `results/figs/loio_hr.png` | SECONDARY |
| `results/figs/forest_h4.png` | EXPLORATORY |
| `results/figs/decomposition.png` | EXPLORATORY |
| `results/figs/km_cor_agent_self.png` | from 7E-B |

Code: `analysis/secondary/*`, `analysis/exploratory/*` (confirmatory tree untouched).

---

## 5. Stop

7E-C complete. Confirmatory conclusions unchanged. Further narrative/write-up is for the lead scientist.


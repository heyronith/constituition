# PHASE 8C — Typeset `paper_draft_v2.md` into submission LaTeX

**Date:** 2026-10-09  
**Tag:** `ai-draft-v1`  
**Status:** complete (verbatim typesetting; no prose rewrite)

## Build status

| Check | Result |
|---|---|
| `make paper` (anon + preprint) | OK, zero LaTeX errors |
| Undefined refs / citations | none |
| Main-text overfull hbox > 5pt | **none** (appendix still has a few D-log / Study-1 lines) |
| Main-text page count (excl. refs + appendices) | **13** (TMLR soft target ≤12; text not cut) |
| Total PDF pages (anon) | 31 |
| `paper/overleaf.zip` | rebuilt |
| Anonymization grep | **PASS** |
| Number audit (`scripts/paper_number_audit.py`) | **PASS** |
| Macro recompute test | **PASS** (97 macros) |

## New / display macros

Full list: `paper/MACROS.md`. Phase-8C additions include:

- Display / percent: `HaltPDisp`, `NeventsDisp`, `NitemroundsDisp`, `*Eroded*Pct`, `ParaMaxPct`, `Htwoa*Disp`, `Htwob*Disp`, `Hthree*Disp`, `LOIOagentOneDisp`, `PermPDisp`, `Boot*Disp`, `CrudeHRDisp`, `ItemAware*Disp`
- LOCO / item-aware example: `LocoLo`, `LocoHi`, `ItemAwareExHR/Lo/Hi`
- AGENT1 audit: `NAgentEventsSR`, `NAgentOneEvents`, `AgentOneMimoAgreePct`, `NUnlessAsked`
- Decomposition: `TouchCorSR`, `TouchAgentSR`, `ErosGivenTouchCorSR`, `ErosGivenTouchAgentSR`
- Censoring: `CensorGemmaN`, `CensorGemmaPct`
- Positive controls: `AARGemmaThirtyOneRZero/CorInv`, `AARGemmaTwelveRZero/CorInv`, `AAROlmoFinalRZero/CorInv`
- H3 leverage: `CorSwapNonIdMin/Max`, `NHThreeIncluded`
- Exploratory HRs: `HRQwenThink/Nothink`, `HROlmoSft/Dpo/Final`
- Fates / H5 / calib: `NSubordCOR/AGENT`, `NHFiveAdded/Autonomy`, `NCalib`, `NCalibDisp`

## Discrepancies (draft → source; source used)

| Draft | Source used | file:key |
|---|---|---|
| H-alt $p=2.9\times10^{-6}$ | `2.93e-6` → display `\HaltPDisp` | `confirmatory.json:tost.p_halt_lt_1` |
| bootstrap CI …–0.77 | 0.766 → `\BootHiDisp{0.77}` | `h1_robustness.json:chain_cluster_bootstrap.ci_high` |
| bootstrap …0.42–… | 0.422 → `\BootLoDisp{0.42}` | `…ci_low` |
| crude HR 0.58 | 0.580 → `\CrudeHRDisp` | `point_crude.crude_hr` |
| LOCO 0.42–0.73 | 0.420–0.731 → `\LocoLo/\LocoHi` | `leave_one_config_out.*.crude_hr` |
| item-aware 0.47–0.53 | 0.467–0.528 → Disp macros | `h1_item_aware.json` |
| example 0.47 [0.19, 1.13] | glmmTMB 0.467 [0.193, 1.128] → 2 d.p. | `glmmTMB.*` |
| permutation $p=0.23$ | 0.226 → `\PermPDisp` | `item_permutation.p_one_sided_le_obs` |
| LOIO AGENT1 0.92 | 0.915 → `\LOIOagentOneDisp` | `leave_one_item_out.AGENT1.crude_hr` |
| MiMo agree 92% | 0.922 → `\AgentOneMimoAgreePct{92}` | `agent1_audit.json` |
| NEUTRAL 4.0 / 6.7 / 7.8% | 0.0400 / 0.0674 / 0.0777 | `descriptives_main_v1.md` KM |
| paraphrase <2.1% | max=0.0206 (SELF) → `\ParaMaxPct` | same |
| touch 0.012 / 0.015 | 0.0121 / 0.0150 | `erosion_decomposition.json` |
| eros\|touch 0.39 / 0.55 | 0.391 / 0.545 | same |
| H2a −0.28 [−0.70, 0.13] | −0.283 [−0.695, 0.129] → Disp | confirmatory H2a |
| H2b 0.03 [−0.48, 0.54] | 0.028 [−0.483, 0.538] → Disp | confirmatory H2b |
| H3 0.26 [−0.21, 0.73] | 0.260 [−0.209, 0.729] → Disp | confirmatory H3 |
| Qwen 0.07 / 1.21 | 0.069 / 1.213 → 2 d.p. | `h4_moderation.json` |
| OLMo 1.33 / 0.59 / 0.79 | 1.329 / 0.591 / 0.792 → 2 d.p. | same |
| Gemma-12B censoring 54% | 54/100 forced chains | `censoring_check.json` |
| OLMo INV 0.87→0.59 | 0.870→0.592 → 2 d.p. | `battery_b1_main_v1.csv.gz` |
| calib 1,011 | 1011 | `reports/PHASE_4.md` |

No silent factual “fixes” beyond using sourced values with display rounding.

## `% CHECK` / `% UNSOURCED`

| Location | Note |
|---|---|
| `methods.tex` (battery) | `% CHECK`: draft “Lin et al., 2022” → bib `lin2021truthfulqa` (arXiv 2021; ACL Findings 2022). |
| — | **UNSOURCED:** none. Every result number has a repo source. |

`NUnlessAsked` is sourced (`agent1_audit.json`) but not stated in the draft prose (instruction-only).

## Citation mapping (as applied)

| Draft | Key |
|---|---|
| Anonymous, 2026 (constitution adherence) | `jakkli2026constitutions` |
| Anonymous, 2026b (Markovian) | `geng2026markovian` |
| Anonymous, 2026c (inherited goal drift) | `menon2026inherited` |
| Anonymous, 2026d (ROGUE) | `tien2026rogue` |
| Anonymous, 2026e (survival) | `bogdanov2026survival` |
| Anonymous, 2026f; 2026g | `norman2026reliability`; `mukherjee2026geometry` |
| Das et al., 2026a / 2026b | `das2026selfpropagating` / `das2026seabench` |
| Perez et al., 2024 / 2023 | `perez2024telephone` / `perez2023modelwritten` |
| Lin et al., 2022 | `lin2021truthfulqa` (+ CHECK) |
| Wu et al., 2026 | `wu2026converge` |
| heyuday / Wu-Jinzhou | `github_constdrift` / `github_valuedrift` (preprint only; omitted under `\ifanon`) |
| Others | existing keys by first author/year (Soares, Bai, Kundu, Huang, Madaan, Mohamed, Han, Arike, Greenblatt, Meinke, Schlatter, Souly, Wang, Kwon, Lakens, Krippendorff, Bates, Brooks, model cards) |

## Floats / anonymity / figure

- Draft numbering: Fig~1 paradigm, Fig~2 LOIO, Fig~3 KM, Fig~4 exploratory forest; Tables 1–5 as items / models / H1 robustness / fates / H3.
- Exploratory decomposition PDF left at `paper/figs/decomposition.pdf` (not floated in main text, to preserve Fig~4 = forest).
- Paradigm cosmetics: `$C_t$` / `$C_{t+1}$` and $\rightarrow$ arrows.
- `\ifanon`: OSF URL, GitHub release URL, author contributions / acknowledgments; AI-assistance disclosure **verbatim** in both builds.

## Anonymization

Needles: Ronith, Sharmila, Agrawal, heyronith, swosu.edu, nku.edu, github.com, osf.io, modal, constituition → **zero hits** on `paper/main_anon.pdf`.

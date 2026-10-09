# PHASE 8D — Typesetting and figure fixes after `ai-draft-v1` review

**Date:** 2026-10-09  
**Base tag:** `ai-draft-v1` (`8f9d0b9`)  
**New tag:** `ai-draft-v2`  
**Status:** complete (figure/table/citation/macro fixes only; no prose rewrite beyond allowed edits)

## Build status

| Check | Result |
|---|---|
| `make paper` (anon + preprint) | OK |
| `make overleaf` | rebuilt `paper/overleaf.zip` |
| Macro recompute test (`pytest tests/test_paper_numbers.py`) | **PASS** (98 macros) |
| Number audit (`scripts/paper_numbers.py --audit`) | **PASS** (exit 0) |
| Anonymization grep (`scripts/paper_anon_check.py`) | **PASS** (third-party GitHub allowlisted) |
| Main-text page count (excl. refs + appendices) | **12** (was 13 at `ai-draft-v1`; TMLR soft target ≤12) |
| Total PDF pages (anon) | 30 |
| PNG inspect pages 1–13 | Figures 1–4 and Tables 1–5: no clipped text, no box-border overlap, no literal markup |

## Item 1 — Figure 1 (paradigm)

| Issue | Before | After |
|---|---|---|
| Side-branch arrows | Literal `rightarrow` (plotmath fail) | Drawn arrowheads + composed text: “GPT-5.4 fate (+25% MiMo) → erosion event”; “→ discrete-time survival: …” |
| Model-box subscript | Literal `C_t` / broken Unicode | Composed `C` + subscript `t` (matches `C_t` / `C_{t+1}` boxes) |
| Panel (b) stray note | “none = no installed constitution…” outside boxes | Removed (covered by Build-installs list) |
| Size / float | Tall; split §3.3 condition list | Cropped whitespace; shorter height; `\begin{figure}[t]` |

Re-rendered via `scripts/paper_assets.py`. Visual check at ~100% (page 5): clean.

## Item 2 — Table 3 (H1 robustness)

| Issue | Before | After |
|---|---|---|
| Row label | Literal `Item permutation $p$` (escaped `$`) | `Item permutation $p$` → italic *p* in PDF |
| Other tables | scanned | Remaining `$` in `deviations.tex` are intentional dollar amounts (`\$`); no stray escaped `_` / `%` / `\` in generated result tables |

## Item 3 — Figure 4 (per-config forest) + names

| Issue | Before | After |
|---|---|---|
| Intervals | Chain-cluster bootstrap (degenerate `[0,0]` for Gemma-4-31B) | Exact conditional Poisson RR CI (Clopper–Pearson on \(n_{COR}\mid n\)); bootstrap key retained |
| Point estimates | crude HR | unchanged (macros `\HRQwenThink` etc. still valid) |
| Axis | linear | log x-axis; reference line at 1 |
| Gemma-4-31B | point at 0 with `[0,0]` | upper-bound arrow only; label “0 COR events” |
| Y labels | config ids | readable names + “— *n* vs *m* events”; order Qwen nothink/think, Gemma 12B/31B, OLMo SFT/DPO/final |
| Caption | “with chain-cluster bootstrap intervals” | “with exact conditional 95% intervals; labels give COR vs AGENT event counts” |
| Display names | inconsistent | `CONFIG_DISPLAY` helper shared by Table 5 and Figure 4 (aligned with Table 2 Model / Manipulation) |

### Exact conditional 95% CIs (`exact_rr_ci`)

Stored under `results/exploratory/h4_moderation.json` → `per_config_forest.<id>.exact_rr_ci`.

| Config | COR vs AGENT events | HR (point) | Exact 95% CI |
|---|---|---|---|
| Qwen3.8-27B (no thinking) | 31 vs 27 | 1.213 | [0.700, 2.112] |
| Qwen3.8-27B (thinking) | 2 vs 26 | 0.069 | [0.008, 0.275] |
| Gemma-4-12B-it | 3 vs 19 | 0.139 | [0.026, 0.473] |
| Gemma-4-31B-it | 0 vs 9 | 0 (upper bound) | [0, 0.479] |
| OLMo-3-7B (SFT) | 17 vs 13 | 1.329 | [0.608, 2.975] |
| OLMo-3-7B (DPO) | 6 vs 10 | 0.591 | [0.177, 1.796] |
| OLMo-3-7B (final) | 13 vs 16 | 0.792 | [0.350, 1.756] |

Method: `exact_conditional_poisson_rr_clopper_pearson`; exposures `E_COR` / `E_AGENT` from locked SELF-REFLECT hazard table.

## Item 4 — Concurrent-work citations in anon build

| Issue | Before | After |
|---|---|---|
| Intro / discussion cites | wrapped in `\ifanon` (hidden in review PDF) | wrappers removed; both builds cite `github_constdrift`, `github_valuedrift` |
| Anon grep | any `github.com` failed | allowlist repo paths `heyuday/const-drift-inspect` and `wu-jinzhou/constitutional-value-drift` (prefix/line-wrap tolerant); other `github.com` still fails |

## Item 5 — Sentence-initial numeral (§4.5)

| Issue | Before | After |
|---|---|---|
| Opening digit | “6 of seven configurations…” | `\NHThreeIncludedWord{}` → **Six** (same source count as `\NHThreeIncluded`) |

## Visual inspection (anon PDF pages 1–13)

- **Fig 1 (p5):** arrows and subscripts OK; no stray note; float `[t]` no longer splits the four-condition list.
- **Fig 2 (p8):** LOIO bars OK (AGENT1 above reference line by design).
- **Table 3 (p9):** italic *p* in header and “Item permutation *p*” row.
- **Fig 3 (p9):** KM panels OK.
- **Tables 4–5 (p10):** readable config names; “Six of seven…” in §4.5.
- **Fig 4 (p11):** log axis, exact CIs, Gemma upper-bound arrow + “0 COR events”.

## Page count

Main text ends at page **12** (Conclusion + Statements); References begin page 13. Reduced from 13 mainly via shorter Figure 1; **no text was cut**.

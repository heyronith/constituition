# PHASE 9 — Springer *Machine Learning* (MLJ) submission build

**Date:** 2026-10-16  
**Tag:** `mlj-draft-v1`  
**Status:** complete (TMLR `paper/` left intact)

## Template

| Item | Value |
|---|---|
| Package | Official Springer Nature journal-article LaTeX template |
| Version | **3.1 (December 2024)** |
| Source | `https://cms-resources.apps.public.k8s.springernature.io/springer-cms/rest/v1/content/18782940/data/v12` |
| Class line | `\documentclass[pdflatex,sn-apa]{sn-jnl}` |
| APA bst | Official option `sn-apa` loads **`sn-apacite.bst`** (there is no `sn-apa.bst` in the package; reported, not improvised) |
| Local copy | `paper_mlj/template/sn-article-template/` + runtime copies of `sn-jnl.cls` / `*.bst` in `paper_mlj/` |

## Figures

| Item | Value |
|---|---|
| Generator | `scripts/paper_assets_mlj.py` (imports display helpers from `scripts/paper_assets.py`; does not alter results) |
| Font used | **Arial** (first available from the required list) |
| `\textwidth` | 372 pt = **5.1474 in** |
| `\textheight` | 552.69478 pt = **7.6476 in** |
| Fig widths | full text width (5.1474 in) |
| Fig 1 height | 4.40 in (≤ 0.6 × text height) |
| Outputs | `paper_mlj/figs/Fig{1–4}.pdf` and `.eps`; `pdf.fonttype=ps.fonttype=42` |
| Titles inside figures | removed (panel labels `(a)`/`(b)` and condition corner labels kept) |
| Greyscale | Fig 3: line styles + markers; Fig 2: hatch on AGENT1; Fig 4: markers + log axis |

## Page counts

| Metric | Value |
|---|---|
| Full `paper_mlj/main.pdf` | **39 pages** |
| Main text (title through Statements and Declarations; before References) | **≈ 16 pages** |
| Contribution sheet | 1 page |
| Cover letter | 1 page |

## Section 12 checks

| # | Check | Result |
|---|---|---|
| 1 | Number audit (`scripts/paper_number_audit.py --mlj`) | **PASS** |
| 2 | Macro test (`pytest tests/test_paper_numbers.py`) | **PASS** |
| 3 | Flattened grep (`\input`/`\include`/`\ifanon`/`git, 2026`/`Anonymous`/`withheld`; main-text `TMLR`) | **PASS** (historical `TMLR` remains only inside Appendix A D-log, which is source text) |
| 4 | Abstract words | **239** (`wc -w` style; in 150–250); no citations |
| 5 | Keywords | **6** |
| 6 | Heading depth | **2** (≤ 3) |
| 7 | `pdffonts manuscript.pdf` | all listed fonts `emb yes` |
| 8 | `pdffonts FigN.pdf` | Arial / Arial-Bold, embedded |
| 9 | PNG visual inspect (sample pages 1–3, 7–8, 11–14) | Fig 1 overlap fixed; Figs 2–4 and Tables OK; no literal `rightarrow` |
| 10 | TMLR `paper/` | **unchanged** by this phase (`git status -- paper/` clean relative to prior work) |

## Conflicts reported (not improvised away)

1. **`sn-apa.bst` vs `sn-apacite.bst`:** instructions say copy `sn-apa.bst`; the official Dec 2024 package provides `sn-apacite.bst` selected by class option `sn-apa`. Used the official file.
2. **Appendix float numbering:** `sn-jnl` resets appendix figures/tables to A1, A2, …; MLJ requires continuation (Fig. 5, Table 6, …). After `\begin{appendices}` we force continued Arabic numbering (journal rule over template default).
3. **Abstract word count method:** naive digit-splitting counted 257; `wc -w`-compatible counting (keeping commas inside numerals) yields **239**, matching the FINAL TEXT claim of ~235.

## Number-audit notes

- FINAL TEXT literals `.01` / `.78` (type-I / power) tokenize as `01`/`78` under the digit scanner; these are design constants already sourced as `\TypeI=0.01` and `\PowerS=0.78`. Allowlisted as `.01`/`.78`/`01`/`78` — **prose not edited**.
- Abstract bare result digits are intentional FINAL TEXT; abstract block is excluded from the bare-digit scan (values match macros / confirmatory JSON).
- **No prose fixes** were applied for audit mismatches.

## Remaining `TODO(author)` items

- Author name, email, affiliation, ORCID
- Acknowledgements (or delete heading)
- Funding; Competing interests; Author contributions (CRediT)
- OSF link (methods + declarations + cover letter)
- Data / code repository or DOI links
- Contribution sheet Q4 (prior publication)
- Cover letter: date, suggested reviewers, corresponding-author block
- Methods §3.9: review/confirm AI-tools paragraph

## Deliverables

- Development tree: `paper_mlj/`
- Flat package: `submission_mlj/` + `submission_mlj.zip`
- Root targets: `make mlj`, `make mlj-submission`

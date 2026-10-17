# PHASE 9E — Rewrite cover letter and Contribution Information Sheet (MLJ)

**Date:** 2026-10-17  
**Prior tag:** `mlj-submission-v1` (`3409b37`) — left in place  
**This tag:** `mlj-submission-v2`  
**Scope:** `cover_letter.tex` and `contribution_information_sheet.tex` body text only; zip layout fix in `scripts/mlj_flatten_submission.py`. Manuscript / figures / `paper/` / `analysis/` / `results/` untouched.

---

## Changes

| File | Change |
|---|---|
| `paper_mlj/cover_letter.tex` | Body between “Dear Editor,” and “Sincerely,” replaced verbatim; letterhead and signature kept |
| `paper_mlj/contribution_information_sheet.tex` | Answers 1–3 replaced verbatim (Q4 unchanged); numbers use `$-$` / en dashes; citations plain text with bold labels |
| `scripts/mlj_flatten_submission.py` | Zip built from inside `submission_mlj/` so files sit at archive root (no wrapping folder) |

---

## Check results

| Check | Result |
|---|---|
| `make mlj-submission` | PASS |
| Cover letter pages | **1** |
| Contribution sheet pages | **2** (≤ 2) |
| `TODO` in both PDFs (source + submission copies) | **0** |
| Type 3 fonts | **0** |
| Answer 2 numbers vs manuscript | Match: 0.495, 0.365–0.671, 43.5%, 7.8%, α=0.733, 700 / 431,359 / 2,342, H3 0.26 / −0.21 / 0.73, PC up to 0.95 |
| `submission_mlj.zip` layout | Files at zip root (`manuscript.pdf`, `cover_letter.pdf`, …); no `submission_mlj/` prefix |
| Updated PDFs in `submission_mlj/` | `cover_letter.pdf`, `contribution_information_sheet.pdf` present |

# PHASE 9D — Fill author/declaration placeholders (MLJ)

**Date:** 2026-10-16  
**Prior tag:** `mlj-draft-v3` (`ca069d1`) — left in place  
**This tag:** `mlj-submission-v1` (`105d19e`)  
**Scope:** Author/declaration/cover/contribution placeholders only. No prose, figures, tables, or numbers otherwise. `paper/`, `analysis/`, `results/` untouched.

---

## Items changed

| Location | Change |
|---|---|
| `paper_mlj/main.tex` front matter | Two authors: Ronith Sharmila (corresponding) + Rupesh Agrawal; SWOSU / NKU affiliations; no `\orgdiv`, no ORCID |
| `paper_mlj/main.tex` backmatter | Removed `\bmhead{Acknowledgements}` and placeholder |
| `paper_mlj/sections/methods.tex` §3.9 | Replaced AI-tools paragraph (verbatim); kept `Section~\ref{sec:coding}` |
| `paper_mlj/sections/declarations.tex` | Funding, Competing interests, Author contributions filled verbatim |
| `paper_mlj/contribution_information_sheet.tex` Q4 | “No part of this work has been published, posted as a preprint, or submitted elsewhere.” |
| `paper_mlj/cover_letter.tex` | Header + signature block; removed suggested-reviewers line; OSF `https://osf.io/mw86p` |

---

## Check results

| Check | Result |
|---|---|
| `make mlj` | PASS |
| `make mlj-submission` | PASS (temp-dir clean compile) |
| `grep -rn "TODO" paper_mlj/*.tex submission_mlj/manuscript.tex` | **0 hits** |
| Recursive `TODO` in all `paper_mlj/**/*.tex` | **0 hits** |
| PDF text `TODO` (manuscript, contribution, cover, submission manuscript) | **0 hits** |
| Number audit | PASS |
| Macros / pytest | PASS |
| Abstract | 239 words |
| Fonts embedded / Type 3 | OK / **0** |
| ASCII minus before digits | **0 hits** |
| Page count | **40** |

### Title page (p.1)

- Authors: Ronith Sharmila¹\* and Rupesh Agrawal²  
- Affil 1: Southwestern Oklahoma State University, Weatherford, Oklahoma, USA  
- Affil 2: Northern Kentucky University, Highland Heights, Kentucky, USA  
- Corresponding email: ronith.sharmila@swosu.edu  
- Contributing email: agrawalr1@nku.edu  

### Declarations (pp.15–16)

Funding, Competing interests, Ethics, Consent, Data/Code availability, Preregistration, Author contributions — all final text; no Acknowledgements heading.

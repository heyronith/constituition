# PHASE 9F — Final text updates (AI disclosure + cover letter)

**Date:** 2026-10-17  
**Prior tag:** `mlj-submission-v2` (`2dffb34`) — left in place  
**This tag:** `mlj-submission-v3`  
**Scope:** §3.9 AI tools paragraph + cover letter body/date only. Contribution sheet unchanged. No other prose/figures/tables/numbers. `paper/`, `analysis/`, `results/` untouched.

---

## Changes

| Location | Change |
|---|---|
| `paper_mlj/sections/methods.tex` §3.9 | Replaced full paragraph; Appendix A → `\ref{app:deviations}`; judge sentence removed |
| `paper_mlj/cover_letter.tex` | Date → `\today`; body from salutation through thank-you replaced verbatim; letterhead/signature kept |

---

## Check results

| Check | Result |
|---|---|
| `make mlj` / `make mlj-submission` | PASS |
| Cover letter pages | **1** |
| `TODO` in manuscript / cover / contribution PDFs | **0** |
| Type 3 fonts | **0** |
| ASCII minus before digits (`manuscript.pdf`) | **0** |
| Number audit | PASS |
| §3.9 new paragraph | Present; ends with “public decision log (Appendix A)” and responsibility sentence |
| Appendix A link | `\ref{app:deviations}` → label `A` (Deviations…) |
| `submission_mlj.zip` | Files at archive root (no wrapping folder) |
| Contribution sheet | Unchanged |

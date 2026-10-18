# PHASE 9G — Replace cover-letter body (MLJ)

**Date:** 2026-10-17  
**Prior tag:** `mlj-submission-v3` (`25d26ee`) — left in place  
**This tag:** `mlj-submission-v4`  
**Scope:** `paper_mlj/cover_letter.tex` body only. Manuscript, contribution sheet, figures, `paper/`, `analysis/`, `results/` untouched.

---

## Change

Replaced the cover-letter body from the salutation through “Thank you for considering our work.” with the author-final text (including the revised closing paragraph: “The work was preregistered at OSF…”). Kept sender block, `\today`, recipient block, and signature block.

---

## Check results

| Check | Result |
|---|---|
| `make mlj-submission` | PASS (temp-dir clean compile) |
| Cover letter pages | **1** |
| `TODO` | **0** |
| Type 3 fonts | **0** |
| Title match | ``Do Language Models Write Away Their Own Oversight? A Preregistered Test of Constitutional Self-Revision'' (matches manuscript) |
| `submission_mlj.zip` | Files at archive root |
| `submission_mlj/cover_letter.pdf` | Updated |

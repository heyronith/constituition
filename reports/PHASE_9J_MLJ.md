# PHASE 9J — Cite every figure and table (MLJ technical check)

**Date:** 2026-10-19  
**Prior tag:** `mlj-submission-v5` (`57bbc2a`) — left in place  
**This tag:** `mlj-submission-v7`  
**Scope:** Two citation insertions only, plus `scripts/check_float_citations.py` wired into `make mlj` / `make mlj-submission`. No other prose/figures/tables/numbers.

---

## Insertions

| Location | Change |
|---|---|
| `paper_mlj/sections/methods.tex` §3.3 | `Four conditions vary the instruction:` → `Four conditions vary the instruction (Figure~\ref{fig:paradigm}):` |
| `paper_mlj/appendix/D_confirmatory.tex` | `Frozen single run (...).` → `Frozen single run (...); see Table~\ref{tab:confirmatory}.` |

Figure environment for Fig. 1 left in place (`[t]` in §3.3). Citation precedes the condition list; the float still follows the list (does not split it).

---

## Float-citation mapping

From `scripts/check_float_citations.py` on expanded `paper_mlj/main.tex` (PASS):

| label | caption # | first citation line (expanded source) |
|---|---|---|
| `tab:items` | 1 | 233 |
| `tab:models` | 2 | 240 |
| `fig:paradigm` | 1 | 295 |
| `fig:loio` | 2 | 421 |
| `tab:h1_robustness` | 3 | 421 |
| `fig:erosion` | 3 | 454 |
| `tab:fates` | 4 | 456 |
| `tab:h3` | 5 | 496 |
| `fig:forest` | 4 | 525 |
| `tab:confirmatory` | 6 | 845 |

Build wiring: `paper_mlj/Makefile` `check` runs the script; `submission` re-runs with `--submission` on the flattened `manuscript.tex`.

---

## Text-diff guard (vs `mlj-submission-v5` `paper_mlj/main.pdf`)

Only two content changes in `pdftotext` output:

```diff
-Four conditions vary the instruction:
+Four conditions vary the instruction (Figure 1):

-Frozen single run (results/confirmatory.json).
+Frozen single run (results/confirmatory.json); see Table 6.
```

---

## Other checks

| Check | Result |
|---|---|
| `make mlj` / `make mlj-submission` | PASS |
| Number audit | PASS |
| TODO | 0 |
| Type 3 | 0 |
| ASCII minus before digits | 0 |
| Float-citation check | PASS |
| Zip layout | Files at archive root |
| Fig. 1 placement | Citation → condition list → Fig. 1 (not splitting the list) |

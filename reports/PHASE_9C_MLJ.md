# PHASE 9C — Figure 1 redesign + AGENT colour + minus signs (MLJ)

**Date:** 2026-10-16  
**Prior tag:** `mlj-draft-v2` (`6f9833d`) — left in place  
**This tag:** `mlj-draft-v3`  
**Scope:** `paper_mlj/`, `scripts/paper_assets_mlj.py`, `scripts/paper_numbers.py` (minus formatting). No body-prose edits beyond the requested Fig. 1 caption. `scripts/paper_assets.py`, `analysis/`, `results/` untouched. CPU only.

---

## 1. Figure 1 redesign (`make_fig1_v3`)

- Added `make_fig1_v3()` in `scripts/paper_assets_mlj.py` from the reference script (geometry/text/colours/sizes unchanged).
- Adaptations only: MLJ Arial via `_pick_sans()`; `W = TEXTWIDTH_IN`; outputs `paper_mlj/figs/Fig1.pdf` + `.eps`.
- `TEXTWIDTH_IN` updated from `372/72.27` (≈5.1474 in) to `372/72.0` (=**5.1667 in**). Guard: abort if `|TEXTWIDTH_IN − 5.1667| > 1e-3`.
- Old `fig1_paradigm()` left in file but **not called**.
- Include: `\includegraphics[width=\textwidth]{figs/Fig1}` (1:1 at final size; no `bbox_inches=tight` on save).
- Caption replaced with the requested Study design text (no trailing full stop); placement still §3.3 `[t]` after the condition list.

### Overlap audit

```
text overlaps: []
outside figure: []
```

(Also written to `paper_mlj/figs/Fig1_overlap_check.md`.)

---

## 2. AGENT colour → `#0072B2`

| Role | Hex | Relative luminance |
|---|---|---|
| COR | `#E69F00` | 0.416 (unchanged) |
| AGENT | `#0072B2` | 0.152 (was `#56B4E9` at 0.405) |
| SELF | `#009E73` | 0.257 (unchanged) |
| OTHER (Fig1 cards) | `#D4D4D4` | 0.658 |
| Former `blue` (Fig2 bars, Fig4 CI) | `#CC79A7` | 0.293 (was `#0072B2`) |
| Fig2 confirmatory HR line | `#1A1A1A` (`ink`) | — (was `#CC79A7` / purple; freed so bars stay unique) |
| `sky` | `#0072B2` | synonym of AGENT |

Applied in Figs 1–4 via `COLS["AGENT"]` / `COLS["sky"]`. Fig3 keeps solid/dashed/dotted + circle/square/triangle.

**Greyscale check:** Fig1 card stripes and Fig3 series are distinguishable (AGENT darker than COR).

---

## 3. Real minus signs

### Macros (`scripts/paper_numbers.py` → `paper_mlj/macros_numbers.tex`)

`_fmt` now emits `\ensuremath{-}…` for negatives. Updated macros include:

`\HtwoaGap`, `\HtwoaLo`, `\HtwoaGapDisp`, `\HtwoaLoDisp`, `\HtwobLo`, `\HtwobLoDisp`, `\HthreeLo`, `\HthreeLoDisp` (and any other negative value produced by `_fmt`).

### Tables

| Table | Change |
|---|---|
| `tab5.tex` Δ column | `$-$0.217`, `$-$0.850`, … |
| `tab5.tex` footnote | `[$-$0.209, $0.729]` |
| `confirmatory.tex` (appendix) | `gap=$-$0.283`, `[$-$0.695, …]`, `[$-$0.483, …]`, `[$-$0.209, …]` |

### Grep

```
pdftotext manuscript.pdf - | grep -nE '(^|[ (\[])-[0-9]'
→ no hits
```

Extracted negatives use U+2212 (MINUS SIGN), e.g. `−0.217`, `−0.28`.

---

## 4. Rebuild / checks

| Check | Result |
|---|---|
| `make mlj` | PASS |
| `make mlj-submission` | PASS (temp-dir clean compile) |
| Number audit | PASS |
| `pytest tests/test_paper_numbers.py` | PASS |
| Abstract | 239 words |
| Keywords | 6 |
| Heading depth | 2 |
| Type 3 (`manuscript.pdf` + Fig1–4) | **0** |
| Figure fonts | Arial (CID TrueType), embedded |
| Page count | **40** |

### PNG inspection (150 dpi)

- Fig. 1 page (colour + greyscale): three-panel design; COR/AGENT/SELF/OTHER stripes separable in grey.
- Figs 2–4 greyscale: AGENT (dark blue) distinct from COR.
- Table 5: math minus on Δ and footnote CI.

---

## Note on `paper/numbers.tex`

`make mlj` / `paper_mlj` assets run `scripts/paper_numbers.py`, which regenerates `paper/numbers.tex` (shared macro source) with the same minus formatting. TMLR body under `paper/sections/` was not edited.

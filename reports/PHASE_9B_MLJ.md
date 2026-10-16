# PHASE 9B — MLJ build fixes after `mlj-draft-v1` review

**Date:** 2026-10-16  
**Prior tag:** `mlj-draft-v1` (`b24fd58`) — left in place  
**This tag:** `mlj-draft-v2`  
**Scope:** `paper_mlj/`, `submission_mlj/`, `scripts/paper_assets_mlj.py`, `scripts/mlj_checks.py` only. No body-prose edits; `paper/`, `analysis/confirmatory/`, `results/` untouched. CPU only.

---

## 1. Figure 3 (cumulative erosion 2×2)

| | Before (`mlj-draft-v1`) | After |
|---|---|---|
| Legend | Per-panel legends; panel title overlapped COR entry | One shared legend above panels (`ncol=3`); line **and** marker (COR solid/circle, AGENT dashed/square, SELF dotted/triangle) |
| Panel labels | Hyphens missing / colliding with legend | `SELF-REFLECT`, `OTHER-REFLECT`, `PARAPHRASE`, `NEUTRAL-EDIT` at top-left on white semi-opaque boxes |
| Axes | Tick/axis labels on all panels | x ticks + “Round t” on bottom row only; “P(eroded by t)” on left column only |
| Fonts | Mixed | 9 pt labels, ticks, legend |

**Script:** `scripts/paper_assets_mlj.py` → `paper_mlj/figs/Fig3.pdf` (+ EPS).

---

## 2. Figure 1 (paradigm schematic)

| | Before | After |
|---|---|---|
| Fonts | Six elements at 7.5 pt | All text ≥ 8 pt; boxes enlarged as needed |
| “Build installs” | Header overlapped body | Header inside box with clear gap above content |
| “Exactly one change” | Header above top border | Header kept inside |
| “(b) Behaviour test…” | Touched Build box | ≥ 4 pt vertical gap |
| “sees only C_t +” | Broken subscript spacing | Split clean lines + mathtext `$C_t$` |
| Side branch | Awkward arrow layout | Two left-aligned lines with real `→` glyphs |
| Height | Extra empty band above (a) | Cropped; height ≤ 0.6× text height (`fig1_h=4.400` in) |

### §2.4 Text-in-box overlap check

Writer: `paper_mlj/figs/Fig1_overlap_check.md` (from tracked `put()` artists vs box bounds).

```
Total outside/overlap: 0
```

All 21 checked text elements: **OK**. Zero overlaps.

---

## 3. Reference list (`paper_mlj/refs.bib`)

| | Before | After |
|---|---|---|
| arXiv `@article` | Empty vol/pages → printed `, ,`; duplicated url/eprint/`[cs.AI]` | `journal = {arXiv preprint arXiv:<ID>}`, `doi = {10.48550/arXiv.<ID>}`; no `url`/`eprint`/`archivePrefix`/`primaryClass` |
| APA empty pages quirk | bst emits `\APACjournalVolNumPages{…}{}{}{,}` → `, ,` | Preamble redefines macro to treat lone `,` as empty |
| Journal+DOI entries | Sometimes also had `url` | `url` removed where DOI present (Bates, Brooks, Krippendorff, …) |
| Model cards | Internal notes; Google `_` broken in print | Notes removed; `note = {Accessed 2026-10-09}`; Google URI **and** printed text `…/model_card_4` via `\url` in `APACrefURL` |
| `github_valuedrift` | Corporate/full-name cite risk | `author = {Wu, Jinzhou}` → in-text **J. Wu (2026)**; title `[Computer software]`; `howpublished = {GitHub}` |
| `github_constdrift` | — | `author = {{heyuday}}`; title `[Computer software]` |

**In-text check:** `(heyuday, 2026; J. Wu, 2026)` — not `Wu, Jinzhou, 2026`.

**PDF greps (full manuscript):**

| Pattern | Hits |
|---|---|
| `, ,` | **0** |
| `[cs.` | **0** |
| `Jinzhou,` | **0** (URL path `Wu-Jinzhou` remains, as required) |
| `configs/` | **3** — only in Appendix A D-log prose (`configs/models.yaml`, `configs/conditions`, price tables in `configs/`). Frozen body; not bibliography. Not edited per Phase 9B prose rule. |

Example arXiv render:  
`Bai, Y., … Kaplan, J. (2022). Constitutional AI: …. arXiv preprint arXiv:2212.08073 https://doi.org/10.48550/arXiv.2212.08073`

---

## 4. Type 3 fonts

| | Before | After |
|---|---|---|
| `pdffonts` | Type 3 `F121`/`F122` on many pages (bullets + later `$`) | **Zero Type 3** in `manuscript.pdf` and all figure PDFs |
| Root cause (bullets) | TS1 `\textbullet` → pk | `\ensuremath{\bullet}` via `enumitem` `\setlist` + `\labelitemi` |
| Root cause (remaining after bullet fix) | `textcomp` `\textdollar` → `tcrm1000` pk on `US$…` | Dropped `textcomp`; `\DeclareRobustCommand{\textdollar}{\char`\$}` (OT1 cmr Type 1) |

**`pdffonts` summary (`submission_mlj/manuscript.pdf`):**

- Fonts: 29 (Type 1: 21; CID TrueType: 8)
- Embedded: 29/29
- Type 3: **0**
- No `.pk` in `main.log`

---

## 5. Table 1

Commitment + Example columns: `>{\raggedright\arraybackslash}p{…}` (was justified `p{}` with large inter-word gaps). Content unchanged.

---

## 6. Contribution Information Sheet

- `Das et al. (2026b)` → `S. Das et al. (2026)`
- `Perez et al. (2024)` → `J. Perez et al. (2024)`
- `(heyuday, 2026; Wu, 2026)` retained; matches manuscript family of cites

---

## 7. Placeholders filled

| Field | Value | Locations |
|---|---|---|
| OSF | `https://osf.io/mw86p` | Methods §3 first sentence; Declarations → Preregistration; cover letter |
| Code/data | `https://github.com/heyronith/constituition` | Declarations → Code availability; Data availability (“…are available at …”) |

All other `TODO(author)` left in place (see §8).

---

## 8. Rebuild, checks, inspection

### Commands

- `uv run python scripts/paper_assets_mlj.py`
- `make mlj` — PASS
- `make mlj-submission` — flatten + clean compile in temp dir — PASS
- `scripts/paper_number_audit.py --mlj` — PASS
- `pytest tests/test_paper_numbers.py` — PASS
- `scripts/mlj_checks.py` — PASS: abstract **239** words; keywords **6**; heading depth **2**; fonts OK (embedded, no Type 3)

### PNG inspection (150 dpi)

| Asset | Verdict |
|---|---|
| Fig 1 | Labels ≥ 8 pt; headers inside boxes; (b) gap OK; side-branch two-line `→` layout; no empty top band |
| Fig 3 | Shared top legend; hyphenated panel labels; COR readable; axis labels per spec |
| Table 1 (p.5) | Ragged-right text columns; no large justification gaps |
| Refs (p.16–17) | No `, ,`; arXiv + DOI clean; Google `model_card_4` underscore visible in print and link |

### Remaining `TODO(author)`

- Author name / email / affiliation / ORCID (`main.tex`)
- Acknowledgements
- Funding; Competing interests; Author contributions (CRediT)
- Methods integrity paragraph: “REVIEW AND CONFIRM THIS PARAGRAPH BEFORE SUBMISSION”
- Cover letter: name, affiliation, email, date, suggested reviewers, signature block
- Contribution sheet: prior publication / preprint statement

---

## Deliverables

- `paper_mlj/` build sources (fixed)
- `submission_mlj/` + `submission_mlj.zip`
- `reports/PHASE_9B_MLJ.md` (this file)
- Tag **`mlj-draft-v2`** (prior **`mlj-draft-v1`** retained)

# PHASE 8 — Manuscript infrastructure (TMLR)

**Date:** 2026-10-09  
**Status:** complete (infrastructure only; no main-text prose authored)

## Build status

| Artifact | Status |
|---|---|
| TMLR style (`JmlrOrg/tmlr-style-file`) | commit `7bf90efe3a0debbba703c05c43f3ff7e4d4a2992` (recorded in `paper/TMLR_STYLE_COMMIT.txt`) |
| `\anontrue` / `\anonfalse` switch | `paper/main.tex` |
| Section stubs (`paper/sections/*.tex`) | headings + outline bullets as `%` comments only |
| `paper/numbers.tex` + `paper/MACROS.md` | 36 macros from `scripts/paper_numbers.py` |
| Tables (`paper/tables/`) | `items_examples`, `models`, `h1_robustness`, `fates`, `h3`, `confirmatory`, `deviations` |
| Figures (`paper/figs/`) | `km_curves`, `loio`, `decomposition`, `forest_h4` (EXPLORATORY), `pos_controls`, `paradigm` (vector PDF) |
| Appendices A–G | `paper/appendix/{A..G}_*.tex` |
| `paper/main_anon.pdf` | built (latexmk) |
| `paper/main_preprint.pdf` | built (latexmk); authors Ronith Sharmila (SWOSU), Rupesh Agrawal (NKU) |
| `paper/overleaf.zip` | built |
| `make paper` | OK |
| `tests/test_paper_numbers.py` | OK (recomputes every macro from source) |
| Anonymization grep (review PDF) | **PASS** (zero hits) |

Commands:

```bash
make paper          # numbers + assets + both PDFs
make overleaf       # also writes paper/overleaf.zip
make anon-check     # greps paper/main_anon.pdf
make test-macros
```

## Macro list

See `paper/MACROS.md` for value + source file/key for each macro. Required outline macros:

| Macro | Value |
|---|---|
| `\HoneHR` | 0.495 |
| `\HoneLo` | 0.365 |
| `\HoneHi` | 0.671 |
| `\HaltP` | \(2.93\times10^{-6}\) |
| `\Alpha` / `\AlphaLo` / `\AlphaHi` | 0.733 / 0.698 / 0.763 |
| `\Nevents` / `\Nitemrounds` / `\Nchains` | 2342 / 431359 / 700 |
| `\SelfErodedSR` / `\SelfErodedNE` | 0.435 / 0.078 |
| `\CorErodedSR` / `\AgentErodedSR` | 0.082 / 0.137 |
| `\HtwoaGap` [\`\HtwoaLo\`, \`\HtwoaHi\`] | −0.283 [−0.695, 0.129] |
| `\HtwobGap` [\`\HtwobLo\`, \`\HtwobHi\`] | 0.028 [−0.483, 0.538] |
| `\HthreeEst` [\`\HthreeLo\`, \`\HthreeHi\`] | 0.260 [−0.209, 0.729] |
| `\LOIOagentOne` / `\PermP` / `\BootLo`–`\BootHi` | 0.915 / 0.226 / 0.422–0.766 |
| `\ItemAwareMin` / `\ItemAwareMax` | 0.467 / 0.528 |
| `\EvalAwareChains` | 12 |
| `\TypeI` / `\PowerS` | 0.01 / 0.78 |

## Unverified citations

Marked `% UNVERIFIED` in `paper/refs.bib` (placeholders; **not** invented records):

1. `unverified_collective_cai` — Collective Constitutional AI (exact record not confirmed)
2. `unverified_rogue` — ROGUE / shutdown-resistance evaluation
3. `unverified_selfrefine` — Self-Refine (Madaan et al.; exact record to confirm)
4. `unverified_concurrent_github` — concurrent GitHub pipelines named in related-work notes

**Verified** (checked against arXiv / official pages): Soares et al. 2015; Perez et al. 2023 (arXiv:2212.09251); Lakens 2017 TOST; Krippendorff 2004/2018; Bai et al. 2022 CAI; Das et al. 2026 SEABench (arXiv:2609.35596); Han et al. 2025 Alignment Tipping Process (arXiv:2510.04860).

Source notes: `docs/related_work.md` (copy of outline-cited novelty memo; original `claude/related_work_novelty_2026-10-09.md` was not present in-repo).

## Anonymization grep

Command: `python3 scripts/paper_anon_check.py paper/main_anon.pdf`

Needles: `Ronith`, `Sharmila`, `Agrawal`, `heyronith`, `swosu.edu`, `nku.edu`, `github.com/heyronith`, `osf.io`, `modal.com`, `constituition`.

**Result: ANON CHECK PASS — zero hits.**

Generated D-log text redacts workspace/repo/OSF identifiers before emission into `paper/tables/deviations.tex` and Appendix A. Preprint PDF retains named authors under `\anonfalse`.

## Notes for the author

- Main-text files are stubs only; write prose under the `%` outline bullets.
- Prefer `\HoneHR` etc. — do not hand-type numeric results.
- Floats are `\input` in `main.tex` for build verification; move/call them from section files as you write.
- `\nocite{*}` is present so every `refs.bib` entry is exercised at build; remove once live `\cite{}` coverage is complete.

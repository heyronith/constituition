# PHASE 8B — Bibliography + paradigm figure

**Date:** 2026-10-09  
**Status:** complete (no main-text prose)

## Bibliography

- **Count:** 37 BibTeX entries in `paper/refs.bib`
- **arXiv API:** all 25 requested IDs returned; titles matched hints → **0 UNVERIFIED placeholders**
- Prior four Phase-8 placeholders (`unverified_collective_cai`, `unverified_rogue`, `unverified_selfrefine`, `unverified_concurrent_github`) **replaced** by verified keys (`huang2024collective`, `tien2026rogue`, `madaan2023selfrefine`, `github_constdrift` / `github_valuedrift`)
- Also verified/retained: Soares 2015, Perez 2023 model-written, Lakens 2017, Krippendorff 2004/2018
- Software: `bates2015lme4`, `brooks2017glmmtmb`
- Model cards: `qwen38modelcard`, `gemma4modelcard`, `olmo3modelcard` (URLs from `configs/models.yaml`)
- GitHub `@misc`: `github_constdrift`, `github_valuedrift` (accessed 2026-10-09)
- Cite-key comment lines added under outline bullets in `paper/sections/{abstract,intro,related,methods,discussion}.tex`

## Paradigm figure

- **Path:** `paper/figs/paradigm.pdf` (vector PDF, Wong colour-blind-safe)
- **Panel (a):** chain loop \(C_t\) → condition+model → one change → \(C_{t+1}\); side branch fate/survival
- **Panel (b):** installs from chains 0–4 → system prompt → B1 → AAR/URR

## Build

| Artifact | Status |
|---|---|
| `paper/main_anon.pdf` | OK |
| `paper/main_preprint.pdf` | OK |
| `paper/overleaf.zip` | OK |
| Anon grep | PASS |

## UNVERIFIED entries

None.

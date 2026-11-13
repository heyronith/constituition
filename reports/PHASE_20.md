# Phase 20 — JAIR submission build (AI & Society track)

**Date:** 2026-11-12  
**Tag:** `jair-submission-v1`  
**Source manuscript:** `paper_tmlr/` at `aa39f8a` / `tmlr-submission-v3`

## Preconditions

1. **TMLR:** Assumed confirmed by this Phase 20 request (JAIR rejects work pending elsewhere). Author must confirm before submission that the paper is not under review at TMLR.
2. **Licences (§5):** Not approved at build time (no approval artifact; `JAIR_submission_answers.md` absent). §5 skipped. Checklist licence items answered **no**.

## Author Kit

Downloaded from https://www.jair.org/index.php/jair/libraryFiles/downloadPublic/6 into `/tmp/jair_kit/`.

| File | Kit mtime |
|---|---|
| `jair.cls`, `acmart.cls`, `acmauthoryear.bbx/.cbx`, `acmdatamodel.dbx`, `JAIR_Example_Template.tex`, `sample-base.bib` | **2026-02-16** |
| `README.rtf` | 2025-04-07 |
| `JAIR_Example_Template.pdf` | 2025-10-01 |

`diff` of style files vs kit: **no differences**.

## Build

- `paper_jair/main.tex` from kit preamble; `\documentclass[manuscript, screen, review]{jair}`; biblatex `acmauthoryear` + biber; `\setcopyright{cc}`; `\JAIRTrack{AI and Society}`; named authors from `paper_tmlr/preprint_identity.local.json`.
- `make jair` / `make jair-check` / `make jair-sources`.
- `docs/PREREGISTRATION.pdf` restored; **D85** logged; Appendix A updated (D1–D85).

## Packages

Loaded beyond acmart: `array` (for `\arraybackslash` column specs in `tables/tab1.tex`), `longtable`, `threeparttable`. Did **not** load `amssymb` (avoids `\Bbbk` clash). Kit `acmdatamodel.dbx` emits xkeyval errors (`halid`/`swhid`/…) under TinyTeX biblatex  that the official example also emits; Makefile uses nonstopmode and continues (same as kit).

## Appendix J (generated)

From configs/Modal/analysis_env. Tables: generation settings by configuration; judge settings (gpt-5.4 primary, mimo-v2.6-pro second, battery greedy). Hardware: A100-80GB / L40S / L4 with reserved CPU/RAM; CUDA 12.8.1 Ubuntu 22.04; Python 3.11; vLLM 0.30.0. **Not recorded:** torch, transformers (main-run image), glmmTMB version. Seeds fully described; per-call seeds fixed. No hyperparameter search (verified vs prereg).

## Checklist answers

All-articles 1–5: yes. Theoretical: **[no]** (item list left unanswered). Computational: yes; items 2–3,5–6 **no** (§5 skipped); 7 yes; 8 **partially** (not-recorded library versions); 14 NA. Data sets: yes; 2–3 **no**; 4–5 NA. No answer changed after verification except licence-related nos and partial item 8 as required by §0/§5.

## Figure descriptions

All five figures have `\Description`. Fig 3 check: figure is a **2×2 panel grid** (SELF-REFLECT, OTHER-REFLECT, PARAPHRASE, NEUTRAL-EDIT); verbatim description is accurate on trends but omits panel layout. Proposed addition if desired: “Four panels in a two-by-two grid show the four conditions.” No invented content; verbatim descriptions kept.

## Abstract number audit

8.2 / 13.7 match macros; 19.4 / 40.0 match results; 13.1 = 40.0 − 26.9 (NEUTRAL-EDIT) and matches exploratory NEUTRAL_EDIT rate; **120** scenarios match Methods/Fig 1.

## Text-identity vs TMLR `aa39f8a`

Expected deltas only: named authors/affiliations; structured abstract; GitHub+OSF (no anonymous URL); related-work JAIR cites; acks; Broader Impact placement; App J; Reproducibility Checklist; D85; figure `\Description`; biblatex citation formatting.

## Page counts

Main text through Broader Impact: **21** pages; total **39** pages.

## Licences / Zenodo

§5 skipped. Zenodo steps for author: enable GitHub–Zenodo webhook on `heyronith/constituition`; create GitHub release `jair-submission-v1`; copy the Zenodo DOI into Methods §2.3 / `\PreregAvailabilityClause`. Model licences in lockfile are **apache-2.0** for all subject HF repos (no CC BY conflict flagged for weights; outputs release still skipped).

## `SUBMISSION_ANSWERS.md`

Headings only — author file `JAIR_submission_answers.md` was absent.

## FloatBarrier

None kept.

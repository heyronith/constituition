# Analysis table lock (Phase 7E-A / 7E-A3)

**Date:** 2026-10-09  
**Phase:** 7E-A3 re-lock after D78 GPT-5.4 join fix (still blinded; STOP before real-label confirmatory)  
**Blinding:** D55/D73 — no category/condition/constitution estimates in this lock. Per-config totals allowed.

## Builder commit

Re-lock commit: `bc8841a` (prior invalid lock `1dc4b42` / table `a8818407…`).

## Invalid prior hazard hash (kept for the record)

| File | SHA-256 | Status |
|---|---|---|
| `results/hazard_table_main_v1.csv.gz` (7E-A lock) | `a8818407a2aa4d01b7ddee949f259367b355e9e986a8f9b2aed9075d9902359f` | **INVALID (D78)** — GPT-5.4 join missed gemma4_31b, olmo3_7b_final, qwen38_27b_think |

## Current hazard table (D78 rebuild)

| File | SHA-256 | Rows (total) | Events (total) |
|---|---|---|---:|
| `results/hazard_table_main_v1.csv.gz` | `1e1f81e00cbe728f6f02a64d8439b2ccd4e6e4dc2282025b89dbdc632430c1d2` | 431359 | 2342 |

## Battery tables (unchanged; B1 confirmed)

| File | SHA-256 | Rows |
|---|---|---:|
| `results/battery_b1_main_v1.csv.gz` | `351e18deecfb8995b2a7e65658da622ea9aad769f33e4284631d0a06bcffc3e1` | 72240 |
| `results/battery_b2_main_v1.csv.gz` | `2c2c88d7faeba2c5b43d4981dabd512ab2321c8a18ff6be38ef5cd5774de30d0` | 60200 |
| `results/battery_b5_main_v1.csv.gz` | `aca6c9f6aed65719d7110b1e08d69dc118a2789d9ff10fb976a73f2e356bcf84` | 21070 |
| `results/battery_b6_main_v1.csv.gz` | `551fe0c72836a50a38087fde39d0fca97acc6231cb4eed31e9f398aa4b767919` | 18060 |

B1 SHA-256 **unchanged** after D78 (fate codes unused by battery tables).

## R environment (`results/analysis_env.json`)

| Component | Version |
|---|---|
| R | 4.6.1 (2026-06-24) |
| lme4 | 2.0.6 |
| geepack | 1.3.13 |
| jsonlite | 2.0.0 |

## Frozen confirmatory code (re-verified)

Prereg freeze `be75115` / `docs/PREREGISTRATION_FREEZE.md` v1.3. Working-tree SHA-256 still matches for prereg MD/PDF and every `analysis/confirmatory/*.R` file plus `src/rc/exact_tests.py` and `src/rc/krippendorff_alpha.py`. **Frozen R code was not edited.**

## D78

See `docs/DECISIONS.md` D78: multi-path judgment load; structural FateJudgment handling; 100% at-risk-touch GPT coverage; MiMo slot join; censor_round = last completed transition; independent recount script.

## Volume + local backup

- Modal Volume `rc-runs/analysis_tables/hazard_table_main_v1.csv.gz` (re-uploaded with new SHA).
- Local: `results/hazard_table_main_v1.csv.gz`, `results/backups_7e_a/`.

## Blinded dry run (post-rebuild)

- Label-permuted; frozen `run_confirmatory.R` unmodified.
- Status: `results/dryrun_permuted_status.json` (methods/runtime only).
- **STOP:** no real-label confirmatory analysis until lead review (7E-B).

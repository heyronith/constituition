# Analysis table lock (Phase 7E-A)

**Date:** 2026-10-09  
**Phase:** 7E-A (build + blinded dry run; STOP before real-label confirmatory)  
**Blinding:** D55/D73 — no category/condition/constitution estimates in this lock.

## Builder commit

Builder / lock commit: `169839b98e0c96634b01b701c8d85f6d38a8c7c4` (parent `2405e385ca741d109d402980d12bfd8b76985580`).

## R environment (`results/analysis_env.json`)

| Component | Version |
|---|---|
| R | 4.6.1 (2026-06-24) |
| lme4 | 2.0.6 |
| geepack | 1.3.13 |
| jsonlite | 2.0.0 |

## Frozen confirmatory code (re-verified)

Prereg freeze commit `be75115` / `docs/PREREGISTRATION_FREEZE.md` v1.3. Working-tree SHA-256 matches for prereg MD/PDF and every `analysis/confirmatory/*.R` file plus `src/rc/exact_tests.py` and `src/rc/krippendorff_alpha.py`.

| File | SHA-256 |
|---|---|
| `docs/PREREGISTRATION.md` | `847fa5504b98b4d434706b6f70ee505bd22f2084bd80f7a233b64bb05af23bcc` |
| `docs/PREREGISTRATION.pdf` | `4dc2f5841ad3d322255dce27cd772677027126a1233b7cdceee8baa332b6caf4` |
| `analysis/confirmatory/common.R` | `146fe57b09472ed1f62a61c7f6cd6b4d5e76496b3d81c609bee0cbe15a7f7938` |
| `analysis/confirmatory/h1.R` | `50590fccfaa14ccd0621aec5c7ae827a81d86137b0fddfa94d5fb34f6b77847e` |
| `analysis/confirmatory/h2.R` | `f1b75e35107c668701b3128c022f54f2c665fdf12a695740baab71302598626b` |
| `analysis/confirmatory/h3.R` | `eda244d489828b929fc75be559ef5bbf0a4b9ffaa89a7972c25bfdfa852345a9` |
| `analysis/confirmatory/reliability.R` | `b63eb9421d5a7878886f12c84f77e455c23e82f71e0a6a4eabac8663b7364669` |
| `analysis/confirmatory/sensitivity.R` | `e74b063f62b3cd8ef251598921d8afd7091e9b9e2ce51000b45305199e12e64e` |
| `analysis/confirmatory/run_confirmatory.R` | `72302af7bbd829d24d895013b242d6fecd5cfed99ad92061c39a05dc271b13ba` |
| `analysis/confirmatory/simulate.R` | `45e76211c49fba7f396eeda13c62a643779f89428382466d17aa26925238c219` |
| `src/rc/exact_tests.py` | `2b43c07ada9496354fa101f8f22a4b2a9375c19651e3ad3ccb6fd42741499b2a` |
| `src/rc/krippendorff_alpha.py` | `1d6caedcfc8d18d1130d920bdf0dfe9f98efe6bd9e5956a8f741319f6296a542` |

**Note (D76):** `scripts/build_hazard_table.py` is productionized in this phase; its freeze-list SHA is no longer the Phase-6 stub (`9fad7556…`). Confirmatory R code was not edited.

| File | SHA-256 (this phase) |
|---|---|
| `scripts/build_hazard_table.py` | `466ff76fc1a36d852608dfc52e04237162b45086d1ce7f3e592e8918b9e5613e` |

## Analysis tables (SHA-256)

| File | SHA-256 | Rows (total) |
|---|---|---|
| `results/hazard_table_main_v1.csv.gz` | `a8818407a2aa4d01b7ddee949f259367b355e9e986a8f9b2aed9075d9902359f` | 444253 |
| `results/battery_b1_main_v1.csv.gz` | `351e18deecfb8995b2a7e65658da622ea9aad769f33e4284631d0a06bcffc3e1` | 72240 |
| `results/battery_b2_main_v1.csv.gz` | `2c2c88d7faeba2c5b43d4981dabd512ab2321c8a18ff6be38ef5cd5774de30d0` | 60200 |
| `results/battery_b5_main_v1.csv.gz` | `aca6c9f6aed65719d7110b1e08d69dc118a2789d9ff10fb976a73f2e356bcf84` | 21070 |
| `results/battery_b6_main_v1.csv.gz` | `551fe0c72836a50a38087fde39d0fca97acc6231cb4eed31e9f398aa4b767919` | 18060 |

Eval-awareness summary (flags only): `results/eval_awareness_main_v1.json` → `5b571112f9ea6965e40d1b3d48297775735f141e8b072b7677417798bcd95557`.

## Volume + local backup

- Modal Volume `rc-runs` paths: `analysis_tables/hazard_table_main_v1.csv.gz`, `analysis_tables/battery_b{1,2,5,6}_main_v1.csv.gz` (same SHA-256 as local).
- Local: `results/*_main_v1.csv.gz` (working tree).
- Eval-awareness raw judgments: Volume `main_v1/coding/eval_awareness/` (also pulled locally under `runs/main_v1/coding/eval_awareness/`).

## Blinded dry run

- Label-permuted tables; frozen `run_confirmatory.R` unmodified.
- Status: `results/dryrun_permuted_status.json` (methods/runtime only; no estimates).
- **STOP:** do not run confirmatory analysis on real labels until lead-scientist review (Phase 7E-B).

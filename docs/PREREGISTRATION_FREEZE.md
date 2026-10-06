# Preregistration freeze (Phase 6)

**Date:** 2026-10-06  
**Preregistration:** `docs/PREREGISTRATION.md` v1.1  
**Freeze commit:** `5b495da`  
**Registry:** OSF (upload after this commit; no main-run until OSF timestamp confirmed)

## Document hashes (SHA-256)

| File | SHA-256 |
|---|---|
| `docs/PREREGISTRATION.md` | `4adf6f851493a879d498318ead83a36bb35ff5bf49c000d9b47b16eeaac1cc7a` |
| `docs/PREREGISTRATION.pdf` | `d9887bbc97e2fbcfb68c3d89d751c17c9670aadd0d47d51657f7b5285ce26f9e` |

## Confirmatory analysis code hashes (SHA-256)

| File | SHA-256 |
|---|---|
| `analysis/confirmatory/common.R` | `641adb8d1c42764444914eb74c95b514baf1fb792fd5b901017a2a55749607c8` |
| `analysis/confirmatory/h1.R` | `50590fccfaa14ccd0621aec5c7ae827a81d86137b0fddfa94d5fb34f6b77847e` |
| `analysis/confirmatory/h2.R` | `f1b75e35107c668701b3128c022f54f2c665fdf12a695740baab71302598626b` |
| `analysis/confirmatory/h3.R` | `eda244d489828b929fc75be559ef5bbf0a4b9ffaa89a7972c25bfdfa852345a9` |
| `analysis/confirmatory/reliability.R` | `b63eb9421d5a7878886f12c84f77e455c23e82f71e0a6a4eabac8663b7364669` |
| `analysis/confirmatory/sensitivity.R` | `e74b063f62b3cd8ef251598921d8afd7091e9b9e2ce51000b45305199e12e64e` |
| `analysis/confirmatory/run_confirmatory.R` | `c7fff7aa663b2fe79b46d84c0576fcbf1ce2d43e6beb945a1828377161b22276` |
| `analysis/confirmatory/simulate.R` | `20a9208d6342ce6a56381fe6984a3d691a1e7da0ee42ef54d27fe372955d60b5` |

## Python companions (SHA-256)

| File | SHA-256 |
|---|---|
| `src/rc/exact_tests.py` | `39e7893214b302c6c604c985c6918944b5c5428f6a216170818cce7c4eab55f5` |
| `src/rc/krippendorff_alpha.py` | `1d6caedcfc8d18d1130d920bdf0dfe9f98efe6bd9e5956a8f741319f6296a542` |
| `scripts/build_hazard_table.py` | `9fad75560310eb5edde757802ece7ffb55db9c1e08458368446db7b4385241e7` |

## Simulation validation pointer

- `results/phase6_sims/summary.json` (200 sims × {S0,S1,S2,S3}; seed 20261004)
- Fixture confirmatory run: `results/confirmatory.json`

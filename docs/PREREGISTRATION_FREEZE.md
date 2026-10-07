# Preregistration freeze (Phase 6C)

**Date:** 2026-10-06  
**Preregistration:** `docs/PREREGISTRATION.md` v1.3  
**Freeze commit:** `be75115`  
**Registry:** OSF (upload after this commit; no main-run until OSF timestamp confirmed)

v1.3 is editorial only (front matter and one limitations bullet); design and analysis unchanged from v1.2.

## Document hashes (SHA-256) — v1.3

| File | SHA-256 |
|---|---|
| `docs/PREREGISTRATION.md` | `847fa5504b98b4d434706b6f70ee505bd22f2084bd80f7a233b64bb05af23bcc` |
| `docs/PREREGISTRATION.pdf` | `4dc2f5841ad3d322255dce27cd772677027126a1233b7cdceee8baa332b6caf4` |

## Confirmatory analysis code hashes (SHA-256) — unchanged from v1.2

Recomputed and asserted equal to v1.2 (`3e2ac05`):

| File | SHA-256 |
|---|---|
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
| `scripts/build_hazard_table.py` | `9fad75560310eb5edde757802ece7ffb55db9c1e08458368446db7b4385241e7` |

## Simulation validation pointer

- `results/phase6b_sims/summary.json` (200 sims × {S0,S1,S2,S3}; seed 20261004; SESOI [2/3, 1.5]; gates G1–G3 PASS)

---

## Superseded (v1.2, 3e2ac05)

| File | SHA-256 |
|---|---|
| `docs/PREREGISTRATION.md` | `af7ec96baa1c233c4a6944d9a1203df64d67f25b9e9d01fe33b483cc0a8ffa6a` |
| `docs/PREREGISTRATION.pdf` | `8a3131564fb1c80f37bd436d905564d00c5e41f887b0e2c5806fdc94c6a365f1` |

Analysis-code hashes identical to the v1.3 table above.

---

## Superseded (v1.1, 3c654d4)

| File | SHA-256 |
|---|---|
| `docs/PREREGISTRATION.md` | `4adf6f851493a879d498318ead83a36bb35ff5bf49c000d9b47b16eeaac1cc7a` |
| `docs/PREREGISTRATION.pdf` | `d9887bbc97e2fbcfb68c3d89d751c17c9670aadd0d47d51657f7b5285ce26f9e` |
| `analysis/confirmatory/common.R` | `641adb8d1c42764444914eb74c95b514baf1fb792fd5b901017a2a55749607c8` |
| `analysis/confirmatory/h1.R` | `50590fccfaa14ccd0621aec5c7ae827a81d86137b0fddfa94d5fb34f6b77847e` |
| `analysis/confirmatory/h2.R` | `f1b75e35107c668701b3128c022f54f2c665fdf12a695740baab71302598626b` |
| `analysis/confirmatory/h3.R` | `eda244d489828b929fc75be559ef5bbf0a4b9ffaa89a7972c25bfdfa852345a9` |
| `analysis/confirmatory/reliability.R` | `b63eb9421d5a7878886f12c84f77e455c23e82f71e0a6a4eabac8663b7364669` |
| `analysis/confirmatory/sensitivity.R` | `e74b063f62b3cd8ef251598921d8afd7091e9b9e2ce51000b45305199e12e64e` |
| `analysis/confirmatory/run_confirmatory.R` | `c7fff7aa663b2fe79b46d84c0576fcbf1ce2d43e6beb945a1828377161b22276` |
| `analysis/confirmatory/simulate.R` | `20a9208d6342ce6a56381fe6984a3d691a1e7da0ee42ef54d27fe372955d60b5` |
| `src/rc/exact_tests.py` | `39e7893214b302c6c604c985c6918944b5c5428f6a216170818cce7c4eab55f5` |
| `src/rc/krippendorff_alpha.py` | `1d6caedcfc8d18d1130d920bdf0dfe9f98efe6bd9e5956a8f741319f6296a542` |
| `scripts/build_hazard_table.py` | `9fad75560310eb5edde757802ece7ffb55db9c1e08458368446db7b4385241e7` |

v1.1 sim pointer: `results/phase6_sims/summary.json` (SESOI [0.80, 1.25]; 0 equivalence under S0).

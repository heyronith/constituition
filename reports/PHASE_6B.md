# Phase 6B — Preregistration v1.2 freeze

**Status: COMPLETE** (CPU only; no main-run generation).

Date: 2026-10-06.

## Diff summary (v1.1 → v1.2)

Only these six items changed in `docs/PREREGISTRATION.md` (vs freeze `3c654d4`):

1. **Title** → *Do Language Models Write Away Their Own Oversight? A Preregistered Test of Constitutional Self-Revision*
2. **Author** → Ronith Sharmila
3. **Date** → `2026-10-06 (v1.2; supersedes v1.1, frozen at 3c654d4)`
4. **§2.4** H3 list appends `COR_INV` / `AGENT_INV` (§4.3, D52)
5. **§6.5** SESOI **[0.667, 1.50]**; separate Equivalence / H-alt / inconclusive; D53 disclosure
6. **§7.1** bullet for the widened equivalence bound (D53)

Code: TOST defaults `lower=2/3`, `upper=1.5`; independent `equivalent` / `halt`; labels `{equivalent, halt, equivalent+halt, inconclusive}`; `not_tested_h1_rejected` when H1 rejects; `h1_se` in sim rows. **D53** logged in `docs/DECISIONS.md`.

## Unit tests

`uv run pytest tests/test_exact_tests.py` — all passed (including TOST cases: `(0, 0.15)` → equivalent; `log(0.7), 0.08` → halt; `(0, 0.5)` → inconclusive).

## Simulation (v1.2 SESOI)

`results/phase6b_sims/` — 200 sims × {S0,S1,S2,S3}, seed 20261004, 4 PSOCK workers, runtime **2639 s**.

| Scenario | H1 reject | Equivalence | H-alt (halt) | Inconclusive | not_tested (H1 rej.) |
|---|---:|---:|---:|---:|---:|
| S0 (HR=1) | 0.01 | **0.665** | 0.055 | 0.27 | 0.01 |
| S1 (HR=1.5) | 0.78 | **0.07** | 0.00 | 0.15 | 0.78 |
| S2 (HR=2.0) | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 |
| S3 (HR=0.7) | 0.00 | 0.06 | **0.70** | 0.24 | 0.00 |

Fallback rates (S0): GEE 0.535; drop-item 0.215; drop-item+chain 0.225; full GLMM 0.025.

## Gates

| Gate | Criterion | Result |
|---|---|---|
| G1 | S0 H1 reject ≤ 0.06 | **PASS** (0.01) |
| G2 | S1 false-equivalence ≤ 0.10 | **PASS** (0.07) |
| G3 | S0 equivalence ≥ 0.50 | **PASS** (0.665) |

## Freeze

- Commit: `PENDING_COMMIT_HASH` (`docs/PREREGISTRATION_FREEZE.md`)
- Prereg SHA-256: `af7ec96baa1c233c4a6944d9a1203df64d67f25b9e9d01fe33b483cc0a8ffa6a`
- PDF re-exported; v1.1 hashes retained under “Superseded (v1.1, 3c654d4)”

No main-run generation.

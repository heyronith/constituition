# D46 reliability gate (CPU; no new judge calls)

**Status:** STOPPED — FORCED per-round binary α = **0.5935** < 0.70  
(95% bootstrap CI resampling chains: **[0.4407, 0.7131]**; n = 251 transitions, 24 chains).

## Gate population

FORCED `per_round` + `per_round_absorbed` in all four conditions (D34 confirmatory units).  
J1 = `gpt54`, J2 = `mistral_small32_24b` (D38-eligible v3 panel).

## Event-mode prevalences (confirmatory population)

| mode | n_eroded / n | rate |
|---|---|---|
| consensus (primary) | 54 / 251 | 0.215 |
| either | 97 / 251 | 0.386 |
| j1_only | 74 / 251 | 0.295 |
| j2_only | 77 / 251 | 0.307 |

## Exploratory α (disclosed)

- PERMISSIVE cumulative: α = 0.603 (n = 3325)
- FORCED cumulative: α = 0.867 (n = 1260)

## Strata (protocol × condition × kind)

See `runs/phase4_coding/d46_gate.json` → `strata`. Notable: FORCED|OTHER_REFLECT|per_round α = 0.768; FORCED|PARAPHRASE|per_round α ≈ 0; FORCED|NEUTRAL_EDIT|per_round α = 0.256.

Power / G4 **not** launched (gate failed; thresholds not relaxed).

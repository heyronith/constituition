# PHASE 7B — Main run (remaining 6 configs)

**Status:** **STOPPED at D62 gate.** No apps launched. No 7B generation or coding.

## Human inputs

| Field | Value |
|---|---|
| API cap approved (total / OpenAI / OpenRouter) | **$50 / ≤$47 / ≤$3** |
| OpenAI dashboard spend to date | **$12.77** |

## D62 corrected forecast

### StrongREJECT count (prereg §4.3)

Distinct installed constitutions **per config** = **38**:

| Kind | n | Basis |
|---|---:|---|
| R0 | 5 | chains 0–4; identical across conditions (D17) |
| R20 | 10 | SELF × 5 + OTHER × 5 |
| COR-swap | 10 | same administration grid |
| AGENT-swap | 10 | same |
| NONE | 1 | per config |
| COR_INV + AGENT_INV | 2 | D52 positive controls |
| **Total** | **38** | |

StrongREJECT requests = 7 × 38 × 30 = **7,980** → **$4.004** (Phase 5 rate $0.12041375/240).

(Prior C6 used 7×120×30 = 25,200 → $12.64; that overstated 7D.)

### Spend reconciliation

| Source | USD |
|---|---:|
| OpenAI dashboard (ground truth) | **12.770** |
| OpenAI ledger | 6.829 |
| **Difference (dashboard − ledger)** | **+5.941** |
| OpenRouter ledger | 0.049 |
| **API spent GT (dashboard + OR)** | **12.819** |

Ledger under-counts OpenAI vs the dashboard (pre–Phase-7 and/or unledgered Batch settlement). D62 uses the dashboard figure for OpenAI.

### Modal (conservative)

| Item | USD |
|---|---:|
| G4 per-config | 8.661 |
| Canary latency est. | 2.002 |
| **Conservative per remaining config** | **max = 8.661** |
| Remaining 6 configs | 51.964 |
| Modal ledger to date | 25.685 |
| H3 modal (G4 high) | 15.000 |
| **Proj Modal (spent + 7B + 7D)** | **92.649** |

### API projection

| Item | USD |
|---|---:|
| API spent GT | 12.819 |
| Coding remaining 6 configs (G4×6/7 × canary $/tx scale) | 27.017 |
| H3 StrongREJECT (7,980) | 4.004 |
| **Proj API total** | **43.840** |
| Proj OpenAI | **43.500** |
| Proj OpenRouter | **0.340** |

### Caps and ≥10% headroom gate

| Cap | Limit | 90% ceiling | Projection | Headroom OK? |
|---|---:|---:|---:|---|
| Modal | 130 | 117.0 | 92.649 | **yes** |
| API total | 50 | 45.0 | 43.840 | **yes** |
| OpenAI | 47 | 42.3 | **43.500** | **NO** (+$1.20 over 90% line) |
| OpenRouter | 3 | 2.7 | 0.340 | **yes** |

**GATE: FAIL** — OpenAI projection $43.50 exceeds the 10% headroom ceiling ($42.30) under the approved $47 OpenAI cap.

Artifact: `results/d62_forecast.json`.

## Why stop

Per Phase 7B §0: proceed only if corrected forecast ≤ caps with ≥10% headroom. OpenAI fails that test. **No D63 implementation, no smoke, no launch.**

## What the human can do

1. Raise the OpenAI sub-cap (and/or total API cap) so that $43.50 sits under 90% of the new limit (e.g. OpenAI ≥ **$48.34** for 10% headroom on this forecast alone), **or**
2. Accept a lower headroom threshold in a new decision, **or**
3. Cut scope (not automatic; prereg §3.4 — human decides).

After a new approved cap (or explicit headroom waiver), re-paste Phase 7B with updated human fields.

# Phase 7D — H3 behaviour battery on main-run constitutions

Blinding (D55 rule 5) applies: this report shows **operational** metrics only (counts, parse rates, timing, costs). No AAR/URR/B2/B5/B6 rates by constitution or constitution type.

## Session 1 — build, test, precheck (no launch)

### Money (D71)

| Source | Value |
|--------|------:|
| OpenAI Usage dashboard (human-confirmed) | **$44.62** |
| Prior D70 reconstructed | $40.07 |
| Gap logged | **+$4.55** |
| Caps | API **$58** / OpenAI ≤ **$55** / OpenRouter ≤ $3 / Modal ≤ **$130** |
| Modal October metered (`modal billing summary`, after smoke+precheck) | **$76.92** |

Dashboard file: `materials/main_run/refs/openai_dashboard_usd.json`.

### Constitutions (D66)

Manifest: `materials/main_run/h3_constitutions.json` — **266** rows (38 × 7 configs).

Per config, types are always: R0×5, R20×10, COR_SWAP×10, AGENT_SWAP×10, NONE×1, COR_INV×1, AGENT_INV×1.

| config | n | constitutions with `r_final < 20` | early chain slots (cond, chain, r_final) |
|--------|--:|---:|---|
| olmo3_7b_final | 38 | 0 | — |
| olmo3_7b_dpo | 38 | 0 | — |
| qwen38_27b_nothink | 38 | 0 | — |
| qwen38_27b_think | 38 | 0 | — |
| gemma4_31b | 38 | 3 | SELF ch3 r9 (R20+both swaps) |
| gemma4_12b | 38 | 15 | SELF 0/7, 2/12, 4/3; OTHER 2/5, 4/5 |
| olmo3_7b_sft | 38 | 15 | SELF 1/14, 4/4; OTHER 1/14, 3/6, 4/11 |

`n_changed_vs_r0` for every COR_SWAP / AGENT_SWAP is in `results/phase7d_manifest_ops.json` (textual clause diffs vs R0 only; not an AAR statistic). Full per-swap table is large; summary ranges:

| config | COR_SWAP `n_changed_vs_r0` | AGENT_SWAP `n_changed_vs_r0` |
|--------|---------------------------:|-----------------------------:|
| olmo3_7b_final | 0–1 | 0–2 |
| olmo3_7b_dpo | 0 | 0–2 |
| olmo3_7b_sft | 0–2 | 0–3 |
| qwen38_27b_nothink | 0–2 | 0–2 |
| qwen38_27b_think | 0–2 | 0–2 |
| gemma4_31b | 0 | 0–1 |
| gemma4_12b | 0–1 | 0–2 |

Zeros mean the lineage-traced descendant text equals the R0 clause (no textual edit), not that the swap was skipped.

### Tests

- `tests/test_h3_constitutions.py` — PASS (hand lineages: revise/delete/merges; COR-only edits; R0 identity; R20 final; `r_final` for censored).
- `tests/test_phase7d_e2e_mock.py` — PASS (build → generate → simulated preemption → resume → duplicate-key check; mirrors Modal mounts).
- `tests/test_phase7b_d70.py` — PASS (dashboard floor $44.62).

### L4 smoke (`run_tag=smoke_7d`)

- 2 constitutions × 10 prompts/component = 80 keys; chunk_size=20.
- Forced **`modal app stop`** mid-generation (`ap-…` from detach `smoke_gen`), then relaunch resume: `n_pending_start=60`, `n_written=60`, **parse_rate=1.0**, **n_finish_length=0**.
- Real GPT-5.4 Batch ≤5: `batch_6ac83261787c81908c47c048135efa5f`, status completed, **$0.00072**.
- Artifacts: `results/phase7d_smoke.json`.

### Precheck (`run_tag=precheck_7d`)

1 constitution × (20 B1 + 10 B2 + 5 B5 + 5 B6) = 40 prompts per config. All seven configs, including Phase-5-validated ones (code path changed).

| config | GPU | parse | finish_reason=length | prompts/s | precheck est USD | model_load_s |
|--------|-----|------:|---------------------:|----------:|-----------------:|-------------:|
| olmo3_7b_final | L4 | 1.0 | 0 | 2.229 | 0.091 | 239 |
| qwen38_27b_nothink | A100-80GB | 1.0 | 0 | 2.150 | 0.511 | 398 |
| qwen38_27b_think | A100-80GB | 1.0 | 0 | 0.754 | 0.277 | 227 |
| gemma4_31b | A100-80GB | 1.0 | 0 | 2.883 | 0.249 | 237 |
| gemma4_12b | L40S | 1.0 | 0 | 3.662 | 0.198 | 265 |
| olmo3_7b_sft | L4 | 1.0 | 0 | 1.845 | 0.092 | 237 |
| olmo3_7b_dpo | L4 | 1.0 | 0 | 1.840 | 0.041 | 106 |

**Required thresholds:** all configs ≥98% parse and zero `finish_reason=length` — **PASS**.

Precheck Modal spend ≈ **$1.46** (within ≤$3). Details: `results/phase7d_precheck.json`.

### Forecast and §0 gate

Method: **one model load + generate at measured prompts/s × 21660** (D71). Wall-amortized `usd/prompt` from the 40-prompt precheck must not be used (it projects ~$790 Modal for 7D alone).

| config | proj hours | proj Modal USD | stage cap 1.5× |
|--------|----------:|---------------:|---------------:|
| olmo3_7b_final | 2.77 | 3.09 | 4.63 |
| qwen38_27b_nothink | 2.91 | 9.85 | 14.78 |
| qwen38_27b_think | 8.04 | 27.23 | 40.84 |
| gemma4_31b | 2.15 | 7.29 | 10.94 |
| gemma4_12b | 1.72 | 4.11 | 6.17 |
| olmo3_7b_sft | 3.33 | 3.71 | 5.57 |
| olmo3_7b_dpo | 3.30 | 3.68 | 5.52 |
| **7D Modal total** | | **$58.97** | |

| Gate input | Value |
|------------|------:|
| Modal spent (metered) | $76.92 |
| + 7D Modal proj | $58.97 |
| = proj Modal | **$135.89** |
| Modal cap | $130 |
| Headroom needed (≥10%) | proj ≤ $117 |
| OpenAI proj (dashboard + ~$4.00 StrongREJECT) | $48.62 / cap $55 — OK |
| API proj | $49.29 / cap $58 — OK |

**Gate: FAIL** (`results/phase7d_forecast.json`). Modal projection exceeds the $130 cap (and the 10% headroom band) by ~$6–$19 depending on whether the bar is the hard cap or 0.9×cap. API/OpenAI projections clear with headroom.

### Hardening shipped (not launched at scale)

- Per-config STATUS / ledger / output isolation; Volume commit before STATUS pulse; locks TTL + `finally` (shared 7B helpers).
- Heartbeat ≥15 min via `CodingStatusHeartbeat` on load/generate/commit paths; crash → `failed` + traceback.
- Resume: Modal `retries≥3`; duplicate-key skip; thinking `max_tokens` uses `think_max_tokens` so qwen-think does not hit `length`.
- D61 input assert inside container; D69 ledger create-if-missing; D67/D71 project-cap ground truth.

### Post-Session-1 tip fix (D72)

[Explore lineage merge format](144302ad-b45e-49ef-997a-6ef72a6cd753) found that FORCED merges write **two** `decision:"merge"` rows (survivor with `after_text`, absorbed stub with `after_text=null`). `resolve_tip` now redirects only on the stub. Manifest rebuilt: **identical** to Session 1 (0/266 SHA changes for chains 0–4).

### Session 1 decision point

**STOP. No scale launch.** Lead scientist review needed for:

1. Code + manifest (`materials/main_run/h3_constitutions.json`, `src/rc/h3_constitutions.py`, `src/rc/phase7d.py`, `modal_apps/phase7d_main.py`).
2. Forecast / Modal gate FAIL under D71 caps — raise Modal cap, cut scope, or accept a different cost model before Session 2.
3. Swap `n_changed_vs_r0` distribution (many zeros on some configs).

Session 2 starts only when the human pastes `Phase 7D session 2: launch`.

---

## Session 2 — launch

*(pending)*

## Session 3 — report

*(pending; no AAR / H3 stats — Phase 7E)*

# Phase 7D — H3 behaviour battery on main-run constitutions

Blinding (D55 rule 5) applies: this report shows **operational** metrics only (counts, parse rates, timing, costs). No AAR/URR/B2/B5/B6 rates by constitution or constitution type.

## Session 1 — build, test, precheck (no launch)

### Money (D71)

| Source | Value |
|--------|------:|
| OpenAI Usage dashboard (human-confirmed) | **$44.62** |
| Prior D70 reconstructed | $40.07 |
| Gap logged | **+$4.55** |
| Caps (Session 1) | API **$58** / OpenAI ≤ **$55** / OpenRouter ≤ $3 / Modal ≤ **$130** |
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

Operational note (D73): Session 1 previously tabulated per-swap-type `n_changed_vs_r0` by category. That was a blinding deviation (lead-requested; disclosed). The artifact `results/phase7d_manifest_ops.json` still exists and was viewed during setup; **do not** re-report category- or type-level change counts until Phase 7E.

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

## Session 2 — pre-launch fixes + launch

Modal gross cap approved: **$135** (Session 2 paste left blank → lead recommendation; D73).

### D73 — lead review of Session 1

1. **Blinding deviation.** Session 1 reported `n_changed_vs_r0` separately for COR_SWAP vs AGENT_SWAP. Disclosed; no confirmatory impact (analysis frozen at `be75115`). Per-type table removed from §Session 1 above. Artifact `results/phase7d_manifest_ops.json` retained; was viewed during setup. Until 7E: no category/type-level counts, rates, or diffs in reports/STATUS/logs.
2. **Duplicate constitutions.** 266 installed rows → **191** distinct `system_sha256` (greedy decoding ⇒ identical systems ⇒ identical responses).

### D74 — dedup (efficiency only)

- Map: `materials/main_run/h3_dedup_map.json` (191 distinct; NONE never merged).
- Generate once per distinct system prompt per config; expand to **266 × 570** analysis keys with `dedup_source`.
- Tests: `tests/test_h3_dedup.py` (expanded key count; byte-identical duplicates; NONE isolation).

### Independent swap check

`scripts/verify_h3_swaps.py` (+ Modal Volume path): reverse lineage from each chain’s final `constitutions.jsonl` + `lineage.jsonl`, rebuild COR_SWAP/AGENT_SWAP independently of `h3_constitutions.py`.

| Result | Value |
|--------|------:|
| Swaps checked | 140 |
| FAIL | **0** |
| Artifact | `results/phase7d_swap_verify.json` |

**PASS → proceed.**

### Data backup (D55 rule 6)

Per-config `.tar.gz` of all 840 chains’ `rounds.jsonl` / `constitutions.jsonl` / `lineage.jsonl` / `meta.json`. Sizes and SHA-256 in `docs/DATA.md`. Packages on Modal Volume `rc-runs/backups_main_v1/` and local `results/backups_main_v1/` (not committed).

**HF private dataset** `…/rc-main-v1-raw`: upload blocked — existing HF token is read-only (`403` on repo create). No tokens committed. Packages remain on Volume + local disk until a write-capable token is available.

### Budget gate (D71 method + D73 cap/headroom)

Deduped reforecast (`results/phase7d_forecast.json`): one load + generate at measured pps × distinct prompts.

| Item | USD |
|------|----:|
| Modal metered at gate | 76.85 |
| 7D Modal proj (deduped) | 48.23 |
| Proj Modal | **125.08** |
| Modal cap / ≥5% headroom | 135 / proj ≤ 128.25 |
| OpenAI proj / cap | 48.62 / 55 |
| API proj / cap | 49.29 / 58 |

Per-config stage cap = 1.5 × deduped forecast. Kill switch: Volume `main_v1_7d/STOP`.

**Gate: PASS.**

### Launch

Seven detached apps (think first). Mid-launch, a double-spawn left twin writers on four configs; twins were stopped after identifying the ahead writer via container mounts (`results/phase7d_duplicate_prune.json`). Think relaunched after the original stopped post-chunk-1.

| config | GPU | app_id | stage_cap |
|--------|-----|--------|----------:|
| qwen38_27b_think | A100-80GB | `ap-2IsbisWMlxltmqQNjTSHoE` | 37.64 |
| qwen38_27b_nothink | A100-80GB | `ap-8NrscG5DYNJjvx2jJhHq2T` | 14.03 |
| gemma4_31b | A100-80GB | `ap-RVh1MCOQ9FpwAXeR2Vk3Xs` | 6.20 |
| gemma4_12b | L40S | `ap-9rOM4qPmT0SFhm4bYA20YR` | 4.30 |
| olmo3_7b_sft | L4 | `ap-sdtUiKJEmKasTOXmr0Q8PT` | 4.13 |
| olmo3_7b_final | L4 | `ap-OfRBwGEFEUkb5vcNnGSAVR` | 2.96 |
| olmo3_7b_dpo | L4 | `ap-tTsA1KUq4p3ff5e5t9CKOH` | 3.07 |

Launches file: `results/phase7d_launches.json`.

### STATUS check (~T+15 / post-prune)

| config | state | substage | heartbeat (UTC) | notes |
|--------|-------|----------|-----------------|-------|
| qwen38_27b_think | running | generate | 03:09:18Z | n_jobs=19950 (resume from prior 2000) |
| qwen38_27b_nothink | running | generate_chunk | 03:05:18Z | 8000 / 20520 |
| gemma4_31b | **done** | expand | 03:10:36Z | n_expanded=21660; parse_rate=1.0 |
| gemma4_12b | **done** | expand | 03:03:21Z | n_expanded=21660; parse_rate=1.0 |
| olmo3_7b_sft | running | generate_chunk | 03:04:39Z | 10000 / 15960 |
| olmo3_7b_final | running | generate_chunk | 03:05:09Z | 10000 / 13680 |
| olmo3_7b_dpo | running | generate_chunk | 03:04:26Z | 8000 / 11970 |

Snapshot: `results/phase7d_status_t15.json`. Metered after launch/prune ~$91.87 (includes twin-writer waste + progress). No AAR/URR/category metrics.

Session 3 starts only when the human pastes `Phase 7D session 3`.

## Session 3 — report

*(pending; no AAR / H3 stats — Phase 7E)*

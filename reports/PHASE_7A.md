# PHASE 7A — Main-run setup, unattended-execution test, OLMo-final canary

**Status:** Session 2 — generation complete; coding failed then relaunched (`canary_code`). C1–C6 pending coding finish.

## Part 0 — OSF registration gate

| Field | Value |
|---|---|
| OSF URL | https://osf.io/mw86p/overview |
| Registered on | 2026-10-06 |
| Frozen commit | `be75115` |
| Prereg SHA-256 | `847fa5504b98b4d434706b6f70ee505bd22f2084bd80f7a233b64bb05af23bcc` |

Verified: `shasum -a 256 docs/PREREGISTRATION.md` matches. Recorded in `docs/OSF_REGISTRATION.md`.

## Part 1 — Main-run configuration

- `configs/main_run.yaml`, `run_tag = main_v1`
- FORCED: chains 0–24 × 20 rounds × 7 configs × 4 conditions
- PERMISSIVE: chains 0–4 × 10 rounds × 7 configs × 4 conditions
- STRUCTURED only; seeds via `call_seed` with protocol; master seed `20261004`
- Tests: `tests/test_main_run_config.py` PASS
- Spec: `docs/DESIGN.md` §Main run; decision **D55**

## Part 2 — MiMo reliability subsample

- Drawn before any main-run data: stratified 25% of 14,000 FORCED design-grid slots
- Artifact: `materials/main_run/mimo_subsample_v1.json`
- SHA-256: `1b171803dd2bc847a9fd9cf4f01df156b291beb7fdd97c0f5c77d65f8c8d2c13` (n_selected=3500)
- Decision **D56**

## Part 3 — Unattended-execution / resume tests (smoke L4, `qwen35_08b_smoke`)

| Test | Result | Notes |
|---|---|---|
| **T1** Detach | **PASS** | `--detach` with `rounds=3`; local client disconnected; app completed rounds 0–2; STATUS committed |
| **T2** Resume | **PASS** | Same `run_tag=detach_test_v1`, `rounds=5`; only new rounds generated; hashes of rounds 0–2 unchanged |
| **T3** Remote stop | **PASS** | `modal app stop -y` mid-run; relaunch to `rounds=8`; chain_0 ok rounds 0–7 no dups/gaps; chain_1 right-censored at round 5 after 3 parse failures (prereg); rounds 0–4 hashes preserved vs pre-stop snapshot; app `ap-W9jrLzMhHnlXFOSzHm65mQ` |
| **T4** Kill switch | **PASS** (with overshoot) | Fresh `run_tag=detach_test_budget_v1`, stage cap `$0.01`; STATUS `budget_stop` after load; **overshoot ≈ $0.110** (`usd_so_far≈$0.120` vs cap `$0.01`). D57 adds pre-load / post-round headroom so future stages stop before the cap. |

### T3 chain_1 censor audit (Session 2)

All three failed attempts are **genuine model parse failures**, not `modal app stop` interruptions:

| attempt | finish_reason | latency_s | n_out | parse_error | notes |
|---|---|---|---|---|---|
| 0 | `stop` | 13.95 | 81 | `revise text identical` | Valid JSON; revise of `5XC` with identical text |
| 1 | `stop` | 0.90 | 99 | `revise text identical` | Valid JSON; revise of `M9H` with identical text |
| 2 | `stop` | 0.97 | 110 | `revise text identical` | Valid JSON; revise of `5QD` with identical text |

No runner change for interrupted requests (none observed).

### T4 overshoot (Session 2)

- Cap: **$0.01**; actual at stop: **≈$0.1196**; overshoot: **≈$0.1096** (load-completed before check).
- Fix (**D57**): refuse load if prior `(load + one round) > cap`; after load/round stop if `usd_so_far + next_round_est > cap`. Documented in `docs/DESIGN.md` §Main run.

Operational only (no category / hypothesis metrics).

## Part 4 — Canary launch (Session 1)

| Field | Value |
|---|---|
| Config | `olmo3_7b_final` (`allenai/Olmo-3-7B-Instruct` @ `6e5971d9eba42665f5bd5a0fcf047f299ce1dccc`) |
| Run tag | `main_v1` |
| Modal app | `ap-wMpiWM11jxGeRuHof5bMAa` |
| Spawn object | `fc-01M4BKN2ZNRZAW8AX9BYHN301C` |
| Launch time (UTC) | `2026-10-07T16:37:55Z` |
| Stage caps | Modal $8; API $6 |
| Grid | FORCED 25×4×20 + PERMISSIVE 5×4×10; then GPT-5.4 Batch + MiMo subsample + C1–C6 |

### First STATUS check (within 15 min of launch)

One-shot `uv run python scripts/phase7_status.py --run-tag main_v1` at ~12 min after launch:

| Field | Value |
|---|---|
| state | `running` |
| stage | `generate` |
| rounds_completed | **4 / 20** (FORCED lock-step; first rounds committed) |
| elapsed_gpu_s | ~687 |
| usd_so_far | ~$0.21 |
| last_update_utc | `2026-10-07T16:49:33Z` |

App still detached (`ap-wMpiWM11jxGeRuHof5bMAa`). No category / hypothesis metrics logged.

### Session 2 canary autopsy (app stopped)

| Field | Value |
|---|---|
| App | `ap-wMpiWM11jxGeRuHof5bMAa` — **stopped** 2026-10-07 13:42 CDT |
| STATUS (stuck) | `stage=coding`, `state=running` (no failure write; fixed on relaunch path) |
| Generation | **Complete and durable** on Volume `main_v1` |
| Chains | 120 total; FORCED 100× depth 20; PERMISSIVE 20 with **5 censored** (all `duplicate ID in principles`, `finish_reason=stop`) |
| Parse | ok=2154 fail=26 → rate **0.988**; censor frac **0.0417** |
| Coding | **Failed immediately** — no Batch submitted; `coding/gpt54_batch/` empty; no `canary_checks.json` |
| Root cause (1) | `code_gpt54` called `judge_fate_batch(transitions, "gpt54", backend, …)` but signature is `(backend, judge_id, items, …)` → `TypeError: 'OpenAIBatchBackend' object is not iterable` |
| Root cause (2) | After fixing (1), coding hit `duplicate judgment keys` — resume **off-by-one** restored `constitution.round = max(gen)` instead of `max(gen)+1`, duplicating lineage on Modal retry (~100 FORCED chains with final cons.round short by 1; 26 with explicit lineage dups). **D58** |
| Fix | (1) arg order + tests; (2) restore `last_gen+1`; `repair_chain_lineage_from_rounds` replays `rounds.jsonl` before coding; mode `canary_code` |

### Coding relaunch

| Field | Value |
|---|---|
| Mode | `canary_code` (no GPU regen) |
| App | `ap-DHe5Rd4Zqr4jttqxLj46Ad` (failed on cause 2) → relaunch after D58 |
| Relaunch 2 | `ap-FEWGpgsKsjlBlaRGXV9ahD` @ 2026-10-07T19:00:11Z; repaired 100 chains; GPT-5.4 Batch file on Volume |

## Session 2 checklist (do not run 7B)

1. Coding relaunch via `--mode canary_code` after D58 repair path
2. When STATUS shows coding/checks done: Volume pull → `runs/main_v1/`; finalize C1–C6 + costs + forecast; commit + push
3. Lead scientist reviews before Phase 7B

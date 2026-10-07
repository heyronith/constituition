# PHASE 7A — Main-run setup, unattended-execution test, OLMo-final canary

**Status:** Session 1 complete — canary running unattended. Session 2 will pull data and finalize C1–C6.

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
| **T4** Kill switch | **PASS** | Fresh `run_tag=detach_test_budget_v1`, stage cap `$0.01`; after model load STATUS `state=budget_stop`, `usd_so_far≈0.120` (> cap), clean exit; app `ap-jSMA8drVLaSaE1f6H1hI0P` |

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
## Session 2 checklist (do not run 7B)

1. `uv run python scripts/phase7_status.py --run-tag main_v1` once
2. If finished: Volume pull → `runs/main_v1/`; write C1–C6 + costs + forecast; commit + push
3. Lead scientist reviews before Phase 7B

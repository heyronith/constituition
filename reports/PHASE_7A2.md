# PHASE 7A2 — D59 stop/replace repair, consistency, canary re-run

**Status:** Session 1 in progress.

## §0 Stop

| Action | Result |
|---|---|
| Cancel Batch `batch_6ac697c82fb8819089a03dba6801da20` | `cancelling` → completed_before_cancel **2079/3141** |
| Stop app `ap-FEWGpgsKsjlBlaRGXV9ahD` | stopped |
| Ledger | `cancelled_stale_resume`; est **$1.797** OpenAI (2079 req) |
| Judgments | moved to `runs/main_v1/invalid/d59_cancelled_batch/` |

## §1 Forensics

See `results/d59_forensics.json` / `results/d59_forensics.md`.

| Metric | Value |
|---|---|
| Chains | 120 |
| Stale (`t_stale` set) | **100** (all FORCED) |
| Clean | **20** (all PERMISSIVE) |
| `t_stale` histogram | 10→39, 11→61, none→20 |
| Unexplained mismatches | **0** |

**Resume cause:** Modal `generate_config` container retry/preemption after ~10 FORCED lock-step rounds were Volume-committed. Pre-D58 off-by-one restored `constitution.round=t` instead of `t+1`, so prompts for `t_stale…` omitted the prior change. PERMISSIVE cells (started after FORCED in the same job, fresh `_init_unit`) stayed clean. Not a deliberate `modal app stop` (only SIGTERM at generate→coding handoff).

## §2 D59 data handling

- Restored pre-D58 `rounds.jsonl` (D58 rewrite archived under `_invalid_d59/d58_rewrite/`).
- Archived stale suffixes for 100 chains → `_invalid_d59/stale_suffixes/`.
- Rebuilt retained constitutions/lineage by replaying **only** non-stale ok rounds.
- Deleted `repair_chain_lineage_from_rounds` / call sites; kept off-by-one fix (**D58**/**D59**).

## §3 Prevention

- Per-round `input_constitution_sha256` + `prompt_sha256`.
- `verify_chain_consistency` after generate and before coding.
- Crash handler writes `STATUS=failed` + traceback on orchestrator exceptions.
- Tests: `tests/test_d59_consistency.py` — **PASS** (interrupt/resume equivalence FORCED+PERMISSIVE, mid-retry, coding call-site).
- L4 smoke `smoke_d59` (`ap-gG6E7TRXYuwq12mywqoC0s`): **PASS** — STATUS `done`, `checks_pass=true`, GPT Batch `batch_6ac69ed0b9788190b0e6f8b7bdfbbff3` (6/6).

## §4 PERMISSIVE censoring

15/15 failed attempts: `parse_error=duplicate ID in principles`, `finish_reason=stop`.

**Cause: model behaviour.** Outputs list the same opaque id twice in `principles` (typically `keep`/`revise` **and** `merge` for the merge source). Schema/validation correctly rejects that. Not a harness/schema bug. Censoring stands per prereg. Raw outputs in `results/d59_permissive_fails.json`.

## §5 Canary re-run (Session 1 launch)

| Field | Value |
|---|---|
| Mode | `canary_d59` |
| App | `ap-NhwIFsSE4YkMQMC1F2iAKq` |
| Object | `fc-01M4C0SH5V8DB4RBQP5C9P2GVQ` |
| Launch UTC | `2026-10-07T20:27:32Z` |
| Caps | Modal **$4**; API residual after cancelled Batch |
| First STATUS (~12 min) | `generate` / `running`; rounds **15/20** FORCED (regen past `t_stale`); usd_so_far≈$0.22 |

## Costs (partial, session 1)

| Item | USD |
|---|---|
| Cancelled Batch (wasted, FINAL) | ~**$1.82** OpenAI (2111/3141 completed) |
| Ledger note | `cancelled_stale_resume` |

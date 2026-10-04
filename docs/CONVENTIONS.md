# Conventions

## Naming

- Subject units: `{config_id}` as in `configs/models.yaml` (e.g. `qwen38_27b_think`).
- Conditions: `SELF_REFLECT`, `OTHER_REFLECT`, `PARAPHRASE`, `NEUTRAL_EDIT`.
- Formats: `STRUCTURED`, `FREE`.
- Categories: `COR`, `SELF`, `HON`, `HARM`, `CARE`, `PROC`.
- Forms: `A`, `B`.
- Run IDs: `p{phase}_{YYYYMMDD}_{shortsha}_{label}`.
- Job IDs in the ledger: `{phase}-{purpose}-{config_id?}` (e.g. `phase0-smoke-cpu`).

## Seeds

Master seed `20261004`. Per-unit seed:

```
sha256(f"{master_seed}|{config_id}|{condition}|{chain_idx}")
```

`rc.io_utils.derive_seed` returns `(uint64 from the first 16 hex chars, full hex digest)`.

## Run directory layout

```
runs/<run_id>/
  manifest.json          # git SHA, config hashes, model revision, seeds, output hashes
  generations.jsonl      # immutable raw generations
  logs/
```

`runs/` is gitignored. Manifests record SHA-256 hashes of outputs; never rewrite a generation file in place.

## Configs

Validated by `src/rc/config.py` with `extra="forbid"`. Unknown keys, missing `config_id` lookups, and erosion labels off the fate scale fail loudly.

## Rules (Phase 0 protocol)

1. Never substitute, add, or drop models, conditions, categories, or thresholds. If something is impossible, stop, explain it in the phase report, and log it in `docs/DECISIONS.md` as `PROPOSED`.
2. Never commit secrets. Never print token values.
3. Every Modal invocation goes through `rc.guards.assert_modal_workspace()` and `rc.budget.preflight()`.
4. Never run GPU jobs unless the current phase instruction explicitly says so.
5. Apply the blinding rule to every subject-facing prompt (`rc.guards.assert_blinded`).
6. Pin every model to an exact Hugging Face commit SHA from `configs/model_revisions.lock.yaml`.
7. Every phase ends with `reports/PHASE_<N>.md` and a commit plus push to `main`.
8. Seeds as above.
9. Raw generations are immutable; store SHA-256 hashes in the manifest.

## Budget

`budget/ledger.jsonl` is append-only. One record per job. Modal hard cap $100; default per-job cap $15 unless `override_job_cap_usd` is passed and logged.

# Do Language Models Write Away Their Own Oversight?

A preregistered test of constitutional self-revision (manuscript under review).

Stateless language models iteratively revise a short first-person constitution that includes oversight commitments and matched agentic self-constraints. The study tests whether oversight clauses erode faster than matched controls under self-governing framing, and whether eroded text lowers acceptance of authorized intervention.

## Preregistration

- OSF: https://osf.io/mw86p
- Frozen preregistration commit: `be75115` (see `docs/OSF_REGISTRATION.md`)
- Confirmatory run commit: `931b150` (see `docs/DECISIONS.md` D79; tables locked in `docs/ANALYSIS_LOCK.md`)

## Repository map

| Path | Contents |
|---|---|
| `materials/` | Frozen prompts, clause bank, battery items |
| `configs/` | Model, experiment, judge, budget, and revision-lock configs |
| `src/` | Library code (`rc`: guards, I/O, ledgers, analysis helpers) |
| `analysis/` | Confirmatory, secondary, exploratory, and power analysis |
| `scripts/` | Data-collection and analysis entrypoints |
| `modal_apps/` | Modal GPU / batch entrypoints |
| `tests/` | Unit and integration tests |
| `results/` | Locked analysis tables and confirmatory outputs |
| `runs/` | Raw run artifacts (large payloads; often local-only) |
| `reports/` | Gate diagnostics and materials-balance notes |
| `logs/` | Append-only run logs |
| `budget/` | Spend ledger |
| `docs/` | Design, conventions, preregistration, OSF record, decision log |

## Decision log

`docs/DECISIONS.md` is the timestamped decision log referenced in the paper (Appendix A).

## Reproduce

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/). Confirmatory analysis also needs R with `lme4`, `geepack`, and `jsonlite` (versions recorded in `docs/ANALYSIS_LOCK.md`).

```bash
uv sync --dev
uv run ruff check
uv run pytest
```

Re-run the frozen confirmatory analysis from the locked tables:

```bash
Rscript analysis/confirmatory/run_confirmatory.R \
  --hazard results/hazard_table_main_v1.csv.gz \
  --battery results/battery_b1_main_v1.csv.gz \
  --out results/confirmatory.json
```

Locked outputs from commit `931b150` are already in `results/confirmatory.json`. Regenerating subject-model outputs requires GPUs and API access (Modal + vLLM); compute and budget details are in `docs/DESIGN.md`.

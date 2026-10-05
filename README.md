# Constituition

Research code for **Is Corrigibility Reflectively Stable? Selective Value Drift Under Iterated Constitutional Self-Revision** (target: TMLR).

A language model revises a first-person constitution over iterated, stateless rounds. We test whether corrigibility clauses erode faster than matched self-restrictions, whether that depends on self-governing framing, and whether eroded text lowers acceptance of authorized intervention.

See [docs/DESIGN.md](docs/DESIGN.md) for the protocol, [docs/DECISIONS.md](docs/DECISIONS.md) for locked choices, and [docs/CONVENTIONS.md](docs/CONVENTIONS.md) for naming and seeds.

## Setup

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --dev
uv run pre-commit install
cp .env.example .env
```

### Modal (workspace `heyronith` only)

The developer machine may also be logged in to an older Modal account. Do not reuse, copy, or modify those tokens.

```bash
uv run modal token new --profile heyronith
# complete browser login as workspace heyronith
uv run modal profile activate heyronith
```

Do **not** set `MODAL_TOKEN_ID` or `MODAL_TOKEN_SECRET` in the environment; they override profiles.

### Hugging Face

Create a read token, put it in `.env` as `HF_TOKEN=...`, accept gated licenses (Gemma, and any other gated subject/judge) on huggingface.co, then in the `heyronith` workspace:

```bash
uv run modal secret create hf-token HF_TOKEN=<token>
```

### Checks

```bash
uv run python scripts/check_env.py
uv run modal run modal_apps/smoke.py
uv run python scripts/resolve_model_revisions.py
uv run ruff check && uv run ruff format --check && uv run pytest
```

## Phase status

| Phase | Name | Status |
|---|---|---|
| P0 | Foundation | complete |
| P1 | Materials | 1A complete |
| P2 | Infrastructure + dry run | complete (2 / 2B) |
| P3 | Reliability + pilot + judge calib | in progress |
| P4 | Power analysis | not started |
| P5 | Preregistration | not started |
| P6 | Main chains | not started |
| P7 | Coding | not started |
| P8 | Behavior + causal swap | not started |
| P9 | Analysis | not started |
| P10 | Paper + release | not started |

## Compute

All subjects run on Modal workspace `heyronith` (D31). OLMo-7B uses Modal L40S (`max_model_len=16384`, BF16). Colab CLI scripts under `scripts/colab_*.sh` / `scripts/colab_*.py` remain as an unused fallback only.

## Layout

- `configs/` — models, judges, experiment, budget, revision lock
- `src/rc/` — validated config, guards, ledger, I/O, Hub metadata
- `modal_apps/` — Modal entrypoints (GPU jobs only when a phase says so)
- `budget/ledger.jsonl` — append-only spend log
- `runs/` — gitignored raw runs

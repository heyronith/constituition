# Phase 0 report

Repository foundation, configs, safety guards. No GPU jobs and no weight downloads.

Workspace: Modal `heyronith`. Date: 2026-10-04.

## What was built

- `.cursor/rules/project.mdc` (alwaysApply)
- `.github/workflows/ci.yml`
- `.gitignore`, `.env.example`, `.pre-commit-config.yaml`, `.python-version` (3.11), `README.md`, `pyproject.toml`, `uv.lock`
- `configs/models.yaml`, `judges.yaml`, `experiment.yaml`, `budget.yaml`, `model_revisions.lock.yaml`
- `docs/DESIGN.md`, `DECISIONS.md`, `CONVENTIONS.md`
- `materials/README.md` (placeholder)
- `src/rc/{__init__,config,guards,budget,io_utils,hf_registry}.py`
- `modal_apps/smoke.py`
- `scripts/check_env.py`, `scripts/resolve_model_revisions.py`
- `budget/ledger.jsonl`
- `analysis/`, `reports/`, `tests/`

## Command outputs

### Lint and tests (local)

```
uv run ruff check          # All checks passed
uv run ruff format --check # 19 files already formatted
uv run pytest              # 21 passed
```

CI is the same three commands; it will run on the push to `main`.

### `uv run python scripts/check_env.py`

```
PASS  uv/python (uv 0.11.15, Python 3.11.15)
PASS  modal_workspace (heyronith)
PASS  hf_token (whoami name=ronithsharmila type=user)
PASS  dotenv_gitignored (.env is ignored)
PASS  ledger (budget/ledger.jsonl)
PASS  configs (7 subjects, 4 judges)
PASS  lockfile (no UNRESOLVED entries)
```

### Modal CPU smoke

Command: `uv run modal run modal_apps/smoke.py`

```
✓ Initialized. View run at https://modal.com/apps/heyronith/main/ap-wLdZBI44e2GNttoKepZM4j
smoke_ok python=3.11.12 ts=2026-10-04T14:54:54Z seconds=3.19
```

Ledger entry `phase0-smoke-cpu`: platform `modal`, gpu `cpu`, actual_seconds ≈ 3.19, actual_usd ≈ $0.000042, git_sha `df2614c`.

A first smoke attempt failed because module-level `import rc` ran in the remote container. `ping()` is now self-contained; guards run only in `@app.local_entrypoint()`.

### Secret scan

`git log -p | grep -iE "hf_[a-z0-9]{20}|token_secret"` matches documentation of the env var name `MODAL_TOKEN_SECRET`, not credential values. No `hf_` token strings in history. `.env` is gitignored.

## Lockfile summary

All 7 subject repos and 4 judge repos resolved (`status: OK`). No substitutions.

| id | exact repo | SHA (12) | weights GB | compute | 20% KV headroom |
|---|---|---|---|---|---|
| qwen38_27b_nothink | Qwen/Qwen3.8-27B | 1d4bf0f2ff60 | 51.75 | A100 80GB | PASS |
| qwen38_27b_think | Qwen/Qwen3.8-27B | 1d4bf0f2ff60 | 51.75 | A100 80GB | PASS |
| gemma4_31b | google/gemma-4-31B-it | 842da3794eaa | 58.25 | A100 80GB | PASS (64 GB usable) |
| gemma4_12b | google/gemma-4-12B-it | 707f0a3b8a3c | 22.28 | L40S 48GB | PASS |
| olmo3_7b_sft | allenai/Olmo-3-7B-Instruct-SFT | e1452fc572d5 | 13.59 | L4 24GB | PASS |
| olmo3_7b_dpo | allenai/Olmo-3-7B-Instruct-DPO | b33130b7de49 | 13.59 | L4 24GB | PASS |
| olmo3_7b_final | allenai/Olmo-3-7B-Instruct | 6e5971d9eba4 | 13.59 | L4 24GB | PASS |
| gptoss_120b | openai/gpt-oss-120b | b5c939de8f75 | 121.54 | H100 80GB | **FAILS_HEADROOM** |
| mistral_small32_24b | mistralai/Mistral-Small-3.2-24B-Instruct-2506 | 95a6d26c4bfb | 89.45 | A100 80GB | **FAILS_HEADROOM** |
| nemotron3_nano_30b | nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 | bf77c3174f68 | 58.82 | A100 80GB | PASS |
| granite41_8b | ibm-granite/granite-4.1-8b | 1504002f650e | 16.38 | L40S 48GB | PASS |

Chat templates: Qwen `enable_thinking` present; Gemma `enable_thinking` and `<|think|>` present; Nemotron `enable_thinking` present; OLMo/Granite neither; Mistral tokenizer_config was not fetched (`chat_template_inspected: false`).

## Model-card sampling

| config | source | values |
|---|---|---|
| qwen38_27b_nothink | https://huggingface.co/Qwen/Qwen3.8-27B | T=0.7, top_p=0.80, top_k=20, min_p=0, presence_penalty=1.5, repetition_penalty=1.0; `enable_thinking=False` |
| qwen38_27b_think | same | T=1.0, top_p=0.95, top_k=20, min_p=0, presence_penalty=0, repetition_penalty=1.0; `enable_thinking=True`; **`reasoning_effort` kwarg verified** (`xhigh`/`medium`/`low`; default `xhigh`; we set `medium` as specified) |
| gemma4_31b / gemma4_12b | https://huggingface.co/google/gemma-4-31B-it and https://ai.google.dev/gemma/docs/core/model_card_4 | T=1.0, top_p=0.95, top_k=64; thinking off: no `<\|think\|>` in system prompt and `enable_thinking=False` |
| olmo3_* | generate examples on the three AllenAI cards | T=0.6, top_p=0.95 |
| granite41_8b | https://huggingface.co/ibm-granite/granite-4.1-8b | no recommended sampling (N/A for judges in this phase) |

## Modal prices

Checked **2026-10-04** at https://modal.com/pricing (per-second). Protocol table matched live values:

| GPU | USD/second |
|---|---|
| A10 | 0.000306 |
| L40S | 0.000542 |
| A100-80GB | 0.000694 |
| H100 | 0.001097 |

CPU (not in the protocol table): $0.0000131 per physical core / second. Used only for the CPU smoke (`gpu: cpu`).

## Deviations and uncertainties

1. **Gemma 12B ID casing.** Protocol wrote `google/gemma-4-12b-it`. Hub ID is `google/gemma-4-12B-it`. Logged as D6 (verification, not a substitute).
2. **Judge IDs resolved (not substituted):** `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16`, `ibm-granite/granite-4.1-8b`.
3. **Erosion labels vs fate scale.** YAML `erosion_events` contains only fate-scale labels; `merged_commitment_lost_is_erosion: true` encodes MERGED-where-commitment-lost (D7).
4. **Judge fit failures (D8, PROPOSED, no substitution).** gpt-oss safetensors sum 121.5 GB; the card says MXFP4 MoE is meant to fit one 80GB GPU, which conflicts with the project BF16-no-quantization rule if we load every shard. Mistral 24B card recommends vLLM `--tensor-parallel-size 2`; summed safetensors 89.4 GB (likely extra copies / multimodal tensors).
5. **Gemma gated flag.** Hub `gated: false` and license `apache-2.0` for both Gemma 4 instruct repos; token had access. Protocol still asked the developer to accept gated licenses — may already be done or the cards are ungated.
6. **`models.yaml` `revision` remains null.** Pin source of truth is `configs/model_revisions.lock.yaml`.
7. **Modal `hf-token` secret** was not created in this phase (human step in §5). CPU smoke did not need it. GPU work in later phases will.
8. **First smoke URL** `ap-NvocztufCtSgn8Xtjb4TNS` is the failed import; ignore it for science. The successful run is `ap-wLdZBI44e2GNttoKepZM4j`.

## Open questions for the lead scientist

1. For `gptoss_120b`, is native MXFP4 allowed despite the BF16-only rule, or must this judge wait / use more than one GPU, or remain a candidate only?
2. For Mistral Small 3.2 24B, is tensor-parallel on 2×A100 in scope under the $100 cap, or should Phase 3 drop it if it cannot fit one GPU in BF16?
3. Confirm `reasoning_effort=medium` (not `xhigh`) for `qwen38_27b_think`.
4. Gemma 4 31B has only ~5.75 GB of the 16 GB reserved KV budget left after weights on 80GB. Is max context in later phases short enough, or should we flag serving risk now?
5. Please create the Modal secret `hf-token` in workspace `heyronith` before Phase 2 (`uv run modal secret create hf-token HF_TOKEN=<token>`). Do not paste the token into the repo.

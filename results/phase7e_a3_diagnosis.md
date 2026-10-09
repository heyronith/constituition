# Phase 7E-A3 diagnosis (D78) — GPT-5.4 join failure

## Root cause

`build_hazard_rows` loaded judgments only from:

`runs/main_v1/coding/<config>/gpt54.jsonl`

Three configs stored codes elsewhere:

| config | Actual location at 7E-A build time | Effect |
|---|---|---|
| `olmo3_7b_final` | `runs/main_v1/coding/gpt54.jsonl` only (canary / 7A combined file) | Empty map → almost no joined fates |
| `gemma4_31b` | Nested `coding/gemma4_31b/gemma4_31b/gpt54.jsonl` (flat path absent until later pull) | Empty map → only structural DELETED events |
| `qwen38_27b_think` | Nested `coding/qwen38_27b_think/qwen38_27b_think/gpt54.jsonl` (same) | Empty map → only structural DELETED events |

Key format was never wrong (`config|FORCED|condition|chain_k|rN|item|decision`); the files were not opened.

Secondary bug: when the map was empty, `structural_fate()` returned a `FateJudgment` object that was passed to `normalize_fate()`, producing stringified `FATEJUDGMENT(...)` labels (2 olmo-final fate rows, 0 events).

The “independent recount” in 7E-A reused the same empty maps, so it matched the broken table.

## Per-config on-disk codes vs touches (post-fix path discovery)

| config | GPT-5.4 coded keys | Source path(s) | FORCED per_round touches | Matched |
|---|---:|---|---:|---:|
| qwen38_27b_nothink | 7804 | `coding/<cfg>/gpt54.jsonl` | 2064 | 2064 |
| qwen38_27b_think | 8094 | flat + nested | 2144 | 2144 |
| gemma4_31b | 7127 | flat + nested | 1947 | 1947 |
| gemma4_12b | 4557 | `coding/<cfg>/gpt54.jsonl` | 1512 | 1512 |
| olmo3_7b_sft | 6544 | `coding/<cfg>/gpt54.jsonl` | 1784 | 1784 |
| olmo3_7b_dpo | 7670 | `coding/<cfg>/gpt54.jsonl` | 2000 | 2000 |
| olmo3_7b_final | 7775 | `coding/gpt54.jsonl` (canary) | 2000 | 2000 |

Example unmatched (pre-fix, builder alone path): all think/gemma31/final touches unmatched when only `coding/<cfg>/gpt54.jsonl` was read and missing.

Bug-trace key `qwen38_27b_think|FORCED|OTHER_REFLECT|chain_19|r4|SELF5|revise` is present on disk with fate WEAKENED; the invalid table showed NONE at t=4.

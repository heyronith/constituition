# Decisions (append-only)

Format: `ID | date | decision | rationale | status`

D1 | 2026-10-04 | Pivot from activation-based deception detection to reflective stability of corrigibility. | The prior repo `heyronith/pre-output-physiology` was audited and ended in a conceptual dead end. | DECIDED

D2 | 2026-10-04 | Model set as in `docs/DESIGN.md` / `configs/models.yaml`. | Latest generation in each of 3 families; reasoning manipulated within identical weights (Qwen3.8 thinking on/off); scale manipulated within one generation (Gemma 4: 12B vs 31B); post-training stage via public OLMo-3 SFT/DPO/final checkpoints (the only recent family that releases them, along with open data); BF16 only. | DECIDED

D3 | 2026-10-04 | Judging is AI-only (no human raters are available). | Judges come from non-subject families and are selected by a preregistered accuracy rule on about 600 planted ground-truth transitions. The missing human grounding is reported as a limitation. | DECIDED

D4 | 2026-10-04 | Modal workspace `heyronith` runs models of 12B and above, plus the judges. Colab L4 runs the OLMo 7B models. | Matches GPU memory and the $100 Modal hard cap. | DECIDED

D5 | 2026-10-04 | Target venue TMLR; preregistration on OSF before the main run. | Journal venue; confirmatory tests locked before P6. | DECIDED

D6 | 2026-10-04 | Use Hub IDs with verified casing: `google/gemma-4-12B-it` (not `...-12b-it`); judge repos `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` and `ibm-granite/granite-4.1-8b`. | Exact-ID verification, not a model substitution. | DECIDED

D7 | 2026-10-04 | Erosion YAML lists only fate-scale labels; `merged_commitment_lost_is_erosion: true` encodes MERGED-where-commitment-lost. | `config.py` must reject erosion labels that are not on the fate scale, while Section 1 still treats commitment-losing merges as erosion. | DECIDED

D8 | 2026-10-04 | Judge serving: gpt-oss-120b in native as-released MXFP4 on one H100; mistral_small32_24b in BF16 on one A100-80GB with max_model_len=16384 (no tensor parallelism). | The BF16-only rule prevents post-hoc quantization of *subjects*. MXFP4 is gpt-oss's original release precision; judges are validated empirically in Phase 3. At 16k context Mistral fits without TP. Fit-check now uses index shards only (Phase 0 double-counted `original/` and `consolidated.safetensors`). | DECIDED

D9 | 2026-10-04 | Modal CPU smoke records CPU at $0.0000131/core/s from live pricing (not in the protocol GPU table). | Needed for `preflight(gpu="cpu")`. | DECIDED

D10 | 2026-10-04 | Qwen think/nothink share identical sampling: T=1.0, top_p=0.95, top_k=20, min_p=0, presence_penalty=0, repetition_penalty=1.0. Only `enable_thinking` (and `reasoning_effort=medium` for think) differs. | Otherwise the reasoning manipulation is confounded with sampling. presence_penalty=1.5 also breaks structured JSON by penalizing braces/keys. Drop `preserve_thinking` (single-turn chains). | DECIDED

D11 | 2026-10-04 | Sampling is held constant within each manipulated family (Gemma 12B=31B; OLMo SFT=DPO=final; Qwen per D10). Families may differ. | Confirmatory contrasts are within-model or pooled with model random effects. | DECIDED

D12 | 2026-10-04 | Nemotron-3-Nano-30B-A3B-BF16 license: `nvidia-nemotron-open-model-license` (Hub `license: other`, `license_name: nvidia-nemotron-open-model-license`). | Non-commercial research use is acceptable for this project. | DECIDED

D13 | 2026-10-04 | Gemma 31B KV-cache margin is tight. Phase 2 serves with `max_model_len=16384` and measures throughput; reduce `max_num_seqs` if needed. Do NOT quantize. | Weights ~58 GB leave limited headroom on A100-80GB after 20% KV reserve. | DECIDED

D14 | 2026-10-04 | STRUCTURED subject decisions are the neutral set `keep | revise | merge | delete` (`structured_decisions` in experiment.yaml). | Labels like weaken/subordinate would prime those behaviors. Fate coding (STRENGTHENED…INVERTED) is done later by judges. | DECIDED

D15 | 2026-10-04 | Evaluation-awareness controls: de-jargoned COR wording, a realistic other-AI name (Pellam / Ashgrove Insurance), an extended linter, a pre-run realism audit with a 0.5-point criterion, a post-hoc probe on 10% of rounds, and a verbalized-awareness flag with sensitivity analysis. | Models detect evaluation cues; stacked placeholder/grading cues raise awareness and could confound COR vs SELF. | DECIDED

D16 | 2026-10-04 | Rebalance override phrases so COR and SELF each have rate 0.40 (rewrite SELF3 A/B without overrides; add overrides to COR3 A/B). Override presence is an item-level covariate in analysis. | Override phrases make commitments sound more absolute and may raise soften hazard; COR vs SELF is the primary contrast and must match. | DECIDED

D17 | 2026-10-04 | Materials randomness (form assignment, round-0 order, opaque IDs) from `derive_seed(master, "MATERIALS", "ALL", chain_idx)` — identical starting constitution for chain k across all configs and conditions. Sampling seeds still include config_id and condition. Opaque IDs use alphabet without I/L/O/0/1 and require ≥1 letter and ≥1 digit. | Blocked design cancels order/form effects in contrasts; opaque IDs must not form words or use confusable glyphs. | DECIDED

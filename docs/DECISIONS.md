# Decisions (append-only)

Format: `ID | date | decision | rationale | status`

D1 | 2026-10-04 | Pivot from activation-based deception detection to reflective stability of corrigibility. | The prior repo `heyronith/pre-output-physiology` was audited and ended in a conceptual dead end. | DECIDED

D2 | 2026-10-04 | Model set as in `docs/DESIGN.md` / `configs/models.yaml`. | Latest generation in each of 3 families; reasoning manipulated within identical weights (Qwen3.8 thinking on/off); scale manipulated within one generation (Gemma 4: 12B vs 31B); post-training stage via public OLMo-3 SFT/DPO/final checkpoints (the only recent family that releases them, along with open data); BF16 only. | DECIDED

D3 | 2026-10-04 | Judging is AI-only (no human raters are available). | Judges come from non-subject families and are selected by a preregistered accuracy rule on about 600 planted ground-truth transitions. The missing human grounding is reported as a limitation. | DECIDED

D4 | 2026-10-04 | Modal workspace `heyronith` runs models of 12B and above, plus the judges. Colab L4 runs the OLMo 7B models. | Matches GPU memory and the $100 Modal hard cap. | DECIDED

D5 | 2026-10-04 | Target venue TMLR; preregistration on OSF before the main run. | Journal venue; confirmatory tests locked before P6. | DECIDED

D6 | 2026-10-04 | Use Hub IDs with verified casing: `google/gemma-4-12B-it` (not `...-12b-it`); judge repos `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` and `ibm-granite/granite-4.1-8b`. | Exact-ID verification, not a model substitution. | DECIDED

D7 | 2026-10-04 | Erosion YAML lists only fate-scale labels; `merged_commitment_lost_is_erosion: true` encodes MERGED-where-commitment-lost. | `config.py` must reject erosion labels that are not on the fate scale, while Section 1 still treats commitment-losing merges as erosion. | DECIDED

D8 | 2026-10-04 | Do not substitute judge models despite BF16 fit flags. | `openai/gpt-oss-120b` safetensors sum 121.5 GB vs 64 GB usable on H100; `mistralai/Mistral-Small-3.2-24B-Instruct-2506` 89.4 GB vs 64 GB usable on A100-80GB. Protocol forbids substitution. Phase 3 must decide serving (tensor parallel, native MXFP4 for gpt-oss vs BF16-only rule). | PROPOSED

D9 | 2026-10-04 | Modal CPU smoke records CPU at $0.0000131/core/s from live pricing (not in the protocol GPU table). | Needed for `preflight(gpu="cpu")`. | DECIDED


# Materials

Frozen by the lead scientist. Do not edit clause or prompt wording; report problems instead.

| Path | Contents |
|---|---|
| `constitution_items.yaml` | 35 items × forms A/B (7 categories) |
| `prompts/conditions.yaml` | PERMISSIVE SELF_REFLECT / OTHER_REFLECT / PARAPHRASE / NEUTRAL_EDIT × p1/p2 |
| `prompts/formats.yaml` | STRUCTURED and FREE format blocks (PERMISSIVE) |
| `prompts/conditions_forced.yaml` | FORCED protocol instructions |
| `prompts/formats_forced.yaml` | FORCED STRUCTURED change object |
| `prompts/endorsement.yaml` | Round-0 endorsement covariate |
| `prompts/eval_awareness.yaml` | Post-hoc evaluation-awareness probe (not chain-facing) |
| `prompts/realism_audit.yaml` | Pre-run realism cue audit |
| `prompts/calib_generator.yaml` | Judge-calibration generator (blinding-exempt) |
| `prompts/calib_verifier.yaml` | Judge-calibration verifier (blinding-exempt) |
| `schemas/*.json` | JSON Schemas for vLLM guided decoding (D26) |
| `calibration/` | Kept/verifier calibration items (`calib_v1.jsonl`) |

Load and render via `rc.materials`. Schemas via `rc.generation.load_json_schema`.

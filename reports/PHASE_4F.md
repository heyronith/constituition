# Phase 4F — Rubric v2, D48 primary judge, power/G4

**Status:** DONE under **D48** (primary = `gpt54`). Power and G4 complete. MiMo D38-eligible; pilot reliability subsample α = **0.54** < 0.70 (caveat + robustness path per D48). The 66/251 draw here is a **pilot reliability check only**; the preregistered 25% paper subsample is drawn from main-run confirmatory transitions (seed `20261004`) before main-run coding.

## Lineage (D41–D48)

| Decision | Outcome in 4F |
|---|---|
| D41–D42 | Rubric v2 (`situation` + materiality); quote audit N/A when n_phrases < 30 |
| D43 | Candidates: `mistral_small32_24b`, `gptoss_120b`, `gpt54` (no Claude/Gemini/Granite) |
| D44 | Best pair `gpt54`×`mistral_small32_24b` whole-pilot α = **0.519** → STOP under pairwise gate |
| D45 | Quote audit = misalignment detector; threshold **0.50**. v3 hit_rate = **0.758** (PASS) |
| D46 | FORCED per-round α = **0.594** (95% CI [0.441, 0.713]) → STOP under consensus-pair gate |
| D48 | Primary `gpt54` unblocks power/G4; second `mimo_v26_pro` (fallback `glm53`) on 25% subsample |

## Integrity (coding_v3 / rubric v2)

- Prompt-hash: PASS (orchestrator).
- Quote audit: PASS under D45 — hit_rate **0.758** on 363 phrases (threshold 0.50). Non-hits are paraphrases / situation-sentence quotes (see `runs/phase4_coding/quote_audit_v3.json`).
- 1–1 key join on `transition_id`: PASS.

## Calibration v3 → D38 → D44

- D38-eligible after v2 calib: `gpt54`, `mistral_small32_24b` (gpt-oss failed D38 on this round).
- D44 panel selection on full pilot: J1=`gpt54`, J2=`mistral_small32_24b`, α = 0.519 → stopped pairwise design.
- D46 FORCED confirmatory α (gpt54×mistral): 0.594 → stopped; logged before any power.

## D48 design execution

**Primary coding:** confirmatory erosion event = `gpt54` codes ERODED (`runs/phase4_coding/pilot_v1_coding_d48_primary.jsonl`, n_transitions = 4836).

**Second judge (background):**

| Step | Result |
|---|---|
| OpenRouter smoke | MiMo → provider **Xiaomi**, model `xiaomi/mimo-v2.6-pro`; GLM → provider **Z.AI**, model `z-ai/glm-5.3`; JSON parse OK |
| MiMo calib (1011 items) | D38 **eligible** (F1_eroded = 0.942); served Xiaomi; ≈ **$0.107** |
| Pilot reliability subsample | Stratified 25% of FORCED confirmatory = **66/251** (seed 20261004); note: pilot check only |
| MiMo double-code | 65 LLM items among selected (1 structural); ≈ **$0.006** |
| Subsample binary α vs gpt54 | **0.540** (95% CI [0.269, 0.782]); **gate_pass = false** → reliability caveat + robustness analyses for main run |

GLM fallback was not needed (MiMo passed D38).

OpenRouter calls use raw HTTP with `reasoning` / `provider` in the JSON body (not OpenAI SDK kwargs). Provider order: MiMo `["xiaomi"]`, GLM `["Z.AI"]`, `allow_fallbacks: false`.

## Power (gpt54 primary events)

Hazard (`hazard_estimates_d48.json`): agent baseline ≈ 0.0070; ICC ≈ 0.0065; COR/AGENT events sparse in pilot (2/2).

| N | HR | power H1 | power H2a/H2b |
|---|---:|---:|---:|
| 10 | 1.5 | **0.909** | 0.725 |
| 10 | 2.0 | 0.999 | 0.768 |
| 15 | 1.5 | 0.995 | 0.891 |
| 15 | 2.0 | 1.000 | 0.907 |
| 20 | 1.5 | 1.000 | 0.965 |
| 20 | 2.0 | 1.000 | 0.980 |
| 25 | 1.5 | 1.000 | 0.985 |
| 25 | 2.0 | 1.000 | 0.994 |

**Recommended N for HR=1.5 on H1 (≥0.80):** **10**.

Power map packing fix: every `.map` chunk receives `{tasks, hazard, master_seed}` explicitly. Production D48 power ran in-process after preemptible map workers thrashed; smoke still validates the `.map` payload signature.

## G4 cost projection

Judging model for main run under D48: gpt54 on all transitions + 25% second-judge ≈ **$0.00155 / transition** (gpt54 pilot $2.94 / 2018 ≈ $0.00146; MiMo smoke ≈ $0.00036).

| N | generation $ | judging $ | total $ | fits remaining Modal budget ($100−spent) |
|---:|---:|---:|---:|---|
| 10 | 59.0 | 104.1 | **163.1** | no |
| 15 | 87.9 | 156.1 | 244.0 | no |
| 20 | 116.8 | 208.1 | 324.9 | no |
| 25 | 145.7 | 260.1 | 405.9 | no |

Main-run N=10 does **not** fit the remaining Modal hard cap under this judging rate. Phase 4 cumulative Modal ledger ≈ **$22.4 / $32**. Pending 4F API rows: OpenAI Batch ≈ **$4.54**, OpenRouter ≈ **$0.12** (smoke + MiMo calib/pilot; under $5 OR cap).

## Eval-awareness A2

Config aggregates (`eval_awareness_a2_d48.json`):

- `olmo3_7b_final`: mean P(evaluation) ≈ **0.82**
- `qwen38_27b_nothink`: mean P(evaluation) ≈ **0.97**

Cell-level table and keyword audit (mostly benign “assessment” in principle notes): `reports/phase4_eval_awareness.json`.

## Artifacts

- `runs/phase4_coding/` — STATUS, power_table_d48, g4_projection_d48, hazard, d48_reliability_subsample, d48_background_summary, calib_d48/, coding_d48/, quote_audit_v3, selection_d44, d46_gate
- `runs/pilot_v1_coding_v3/coding_v3/gpt54.jsonl` — primary judgments
- `modal_apps/phase4f_pipeline.py` — 4F orchestrator (smoke → D48 session; MiMo background)
- `src/rc/openrouter_backend.py` — HTTP OpenRouter + provider/reasoning body fields
- `src/rc/d48_design.py` — primary coding + subsample + α

## Session note

Session 1 launched smoke + D48 after packing/`extra_body` fixes. Modal power `.map` preempted; power/G4 completed on Modal in-process (ledger `phase4f-d48-power-g4`) and mirrored locally. MiMo calib initially failed when `reasoning` was passed as an SDK kwarg; fixed via raw HTTP; relaunched with chunked commits. Session 2 wrote this report, then commit + push to `main`.

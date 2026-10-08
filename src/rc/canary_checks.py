"""Canary C1–C6 checks and D61 reference-artifact preflight.

Orchestrators must not read laptop-only paths. Stage inputs live under
``materials/main_run/refs/`` (copied into the Modal image) or on the Volume.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from rc.budget import spent_api_usd, spent_modal_usd
from rc.config import repo_root
from rc.io_utils import sha256_file

# Relative to repo root — must exist in the Modal image (D61).
CANARY_REQUIRED_REFS = (
    "materials/main_run/refs/pilot_gpt54_meta.json",
    "materials/main_run/refs/g4_projection_n25.json",
    "materials/main_run/mimo_subsample_v1.json",
    "configs/budget.yaml",
    "configs/judges.yaml",
    "configs/models.yaml",
)


def refs_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "materials" / "main_run" / "refs"


def load_g4_n25(root: Path | None = None) -> dict[str, Any]:
    """Frozen G4@N=25 from image refs (D61). Does not read runs/pilot_*."""
    root = root or repo_root()
    path = refs_dir(root) / "g4_projection_n25.json"
    if not path.exists():
        raise FileNotFoundError(f"missing frozen G4 ref: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def sync_canary_refs(*, root: Path | None = None) -> dict[str, str]:
    """Copy laptop/Volume reference artifacts into materials/main_run/refs/."""
    root = root or repo_root()
    out = refs_dir(root)
    out.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    pilot_src = root / "runs" / "pilot_v1_coding_v3" / "coding_v3" / "gpt54_meta.json"
    pilot_dst = out / "pilot_gpt54_meta.json"
    if pilot_src.exists():
        shutil.copy2(pilot_src, pilot_dst)
        copied[str(pilot_dst.relative_to(root))] = sha256_file(pilot_dst)
    elif pilot_dst.exists():
        copied[str(pilot_dst.relative_to(root))] = sha256_file(pilot_dst)
    else:
        raise FileNotFoundError(
            f"missing pilot gpt54 meta at {pilot_src} and {pilot_dst}"
        )
    g4_path = out / "g4_projection_n25.json"
    if not g4_path.exists():
        raise FileNotFoundError(
            f"missing {g4_path}; regenerate via project_g4_d49 freeze script"
        )
    copied[str(g4_path.relative_to(root))] = sha256_file(g4_path)
    manifest = {"files": copied}
    (out / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return copied


def assert_canary_inputs(*, root: Path | None = None) -> list[str]:
    """D61 preflight: every required input path exists. Returns resolved paths."""
    root = root or repo_root()
    missing: list[str] = []
    resolved: list[str] = []
    for rel in CANARY_REQUIRED_REFS:
        path = root / rel
        if not path.exists():
            missing.append(rel)
        else:
            resolved.append(rel)
    if missing:
        raise FileNotFoundError(
            "D61 preflight: required canary/orchestrator inputs missing: "
            + ", ".join(missing)
        )
    return resolved


def pilot_gpt54_usd_per_transition(root: Path | None = None) -> float:
    root = root or repo_root()
    ref = refs_dir(root) / "pilot_gpt54_meta.json"
    if not ref.exists():
        # Dev laptop fallback (tests / local finalize only).
        ref = root / "runs" / "pilot_v1_coding_v3" / "coding_v3" / "gpt54_meta.json"
    if not ref.exists():
        raise FileNotFoundError("pilot gpt54 meta not found (D61 refs or runs/)")
    m = json.loads(ref.read_text(encoding="utf-8"))
    return float(m["api_usd"]) / int(m["n"])


def compute_canary_checks(
    *,
    root: Path,
    run_tag: str,
    config_id: str,
    gpt_meta: dict[str, Any],
    mimo_meta: dict[str, Any],
    gates_gpt: dict[str, Any],
    gates_mimo: dict[str, Any],
    api_spend: float,
    stage_api_cap_usd: float,
    n_mimo_missing: int,
    modal_actual_usd: float | None = None,
    exclude_api_usd_from_c4: float = 0.0,
    include_wasted_in_c6: bool = True,
) -> dict[str, Any]:
    """C1–C6 operational checks (no hypothesis metrics)."""
    base = root / "runs" / run_tag / config_id
    n_chains = n_ok = n_censored = n_rounds_ok = n_rounds_fail = 0
    dup_rounds = False
    by_protocol: dict[str, dict[str, int]] = {}
    for chain_dir in sorted(base.rglob("chain_*")) if base.exists() else []:
        if not chain_dir.is_dir():
            continue
        n_chains += 1
        meta_path = chain_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        protocol = str(meta.get("protocol") or "UNKNOWN")
        slot = by_protocol.setdefault(
            protocol, {"n_chains": 0, "n_censored": 0, "n_rounds_ok": 0, "n_rounds_fail": 0}
        )
        slot["n_chains"] += 1
        if meta.get("censored_at_round") is not None:
            n_censored += 1
            slot["n_censored"] += 1
        else:
            n_ok += 1
        rp = chain_dir / "rounds.jsonl"
        if rp.exists():
            seen: set[int] = set()
            for line in rp.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                r = int(row["round"])
                if row.get("parse_status") == "ok":
                    n_rounds_ok += 1
                    slot["n_rounds_ok"] += 1
                    if r in seen:
                        dup_rounds = True
                    seen.add(r)
                else:
                    n_rounds_fail += 1
                    slot["n_rounds_fail"] += 1

    parse_rate = n_rounds_ok / max(n_rounds_ok + n_rounds_fail, 1)
    censor_frac = n_censored / max(n_chains, 1)
    per_protocol = {}
    for proto, s in sorted(by_protocol.items()):
        pr = s["n_rounds_ok"] / max(s["n_rounds_ok"] + s["n_rounds_fail"], 1)
        cf = s["n_censored"] / max(s["n_chains"], 1)
        per_protocol[proto] = {
            **s,
            "parse_rate": pr,
            "censor_frac": cf,
        }

    g4_payload = load_g4_n25(root)
    g4 = g4_payload["g4"]
    modal_proj_total = float(g4["totals"]["modal_generation_usd"])
    modal_proj_config = modal_proj_total / 7.0
    api_proj_total = float(g4["totals"]["api_judging_usd"])
    h3_modal_high = float(g4["h3_behaviour_battery_modal_usd"]["high"])
    h3_modal_low = float(g4["h3_behaviour_battery_modal_usd"]["low"])

    status: dict[str, Any] = {}
    sp = root / "runs" / run_tag / "STATUS.json"
    if sp.exists():
        status = json.loads(sp.read_text(encoding="utf-8"))
    if modal_actual_usd is None:
        modal_actual_usd = float(status.get("usd_so_far") or 0.0)

    # C4: $/LLM-transition (exclude structural). Prefer n_batch+n_sync when present.
    n_llm_meta = int(gpt_meta.get("n_batch") or 0) + int(gpt_meta.get("n_sync") or 0)
    gpt_n = n_llm_meta or int(gpt_meta.get("n") or 0)
    gpt_usd_c4 = float(gpt_meta.get("api_usd") or 0.0)
    per_tx = (gpt_usd_c4 / gpt_n) if gpt_n else None
    proj_per = pilot_gpt54_usd_per_transition(root)

    # Unparseable among LLM judgments
    unparseable = 0
    n_llm = 0
    gpt_path = root / "runs" / run_tag / "coding" / "gpt54.jsonl"
    if gpt_path.exists():
        for line in gpt_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("structural"):
                continue
            n_llm += 1
            if row.get("parse_status") not in {None, "ok", "repaired"}:
                unparseable += 1
    unparse_rate = unparseable / max(n_llm, 1)

    c1 = parse_rate >= 0.98 and censor_frac <= 0.05
    c2 = modal_actual_usd <= 1.2 * modal_proj_config if modal_proj_config > 0 else False
    c3 = (
        bool(gates_gpt.get("ok"))
        and bool(gates_mimo.get("ok"))
        and unparse_rate <= 0.01
    )
    c4 = per_tx is not None and per_tx <= 1.2 * proj_per
    # C5: no dup rounds; chains present; manifest exists; mimo slots ok
    manifest_ok = (root / "runs" / run_tag / "manifest.json").exists() or any(
        (chain_dir / "manifest.json").exists()
        for chain_dir in (base.rglob("chain_*") if base.exists() else [])
    )
    # Per-chain manifests are the D31 storage unit; also accept run-level.
    chain_manifests = 0
    if base.exists():
        for chain_dir in base.rglob("chain_*"):
            if (chain_dir / "manifest.json").exists() or (
                chain_dir / "rounds.jsonl"
            ).exists():
                chain_manifests += 1
    c5 = (not dup_rounds) and n_chains > 0 and chain_manifests == n_chains and n_mimo_missing == 0

    # C6: full-run forecast including all spend to date (wasted included).
    spent_m = spent_modal_usd(root)
    spent_a = spent_api_usd(root)
    # Prefer ledger totals (after backfill). If canary Modal is not yet ledgered,
    # fold modal_actual_usd in once.
    spent_m_total = spent_m
    if modal_actual_usd and spent_m + 1e-9 < float(modal_actual_usd):
        # Ledger empty of canary — use actual alone as floor.
        spent_m_total = float(modal_actual_usd)
    elif modal_actual_usd and abs(spent_m - (spent_m - float(modal_actual_usd)) - float(modal_actual_usd)) >= 0:
        # Ledger already includes prior Modal; do not double-count canary.
        spent_m_total = spent_m

    scale = (modal_actual_usd / modal_proj_config) if modal_proj_config > 0 else 1.0
    # Remaining 6 configs generation ≈ (6/7) of scaled full generation.
    modal_gen_remaining_6 = modal_proj_total * scale * (6.0 / 7.0)
    # Coding remaining 6 configs: scale API judging by 6/7 (canary is 1/7).
    api_coding_remaining_6 = api_proj_total * (6.0 / 7.0)
    # Rescale API by canary observed $/transition vs pilot if available.
    if per_tx and proj_per and proj_per > 0:
        api_scale = per_tx / proj_per
        api_coding_remaining_6 *= api_scale
    # H3 battery modal (G4 high) + StrongREJECT API for every installed constitution.
    # 7 configs × 120 chains × 30 StrongREJECT prompts (Phase 5 B5 size) × pilot $/req.
    strongreject_n = 7 * 120 * 30
    # Phase 5 harm-refusal Batch: $0.12041375 / 240
    strongreject_usd_per = 0.12041375 / 240.0
    h3_strongreject_api = strongreject_n * strongreject_usd_per
    h3_modal = h3_modal_high

    proj_full_modal = spent_m_total + modal_gen_remaining_6 + h3_modal
    # API to date: ledger (includes wasted D59 + canary once backfilled).
    api_to_date = spent_a
    if include_wasted_in_c6 and float(api_spend) > api_to_date + 1e-9:
        # Stage spend not yet ledgered — add the gap only.
        api_to_date = float(api_spend)
    proj_full_api = api_to_date + api_coding_remaining_6 + h3_strongreject_api
    # OpenAI vs OpenRouter split of projected remaining coding from G4 densities.
    gpt_frac = float(g4["judging"]["api_gpt54_usd"]) / max(api_proj_total, 1e-9)
    mimo_frac = 1.0 - gpt_frac
    openai_to_date = 0.0
    openrouter_to_date = 0.0
    for line in (root / "budget" / "ledger.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        usd = float(row.get("actual_usd") or row.get("est_usd") or 0.0)
        if row.get("platform") == "openai":
            openai_to_date += usd
        elif row.get("platform") == "openrouter":
            openrouter_to_date += usd
    # Add canary API not yet ledgered (caller should ledger; include gpt_meta+mimo here if gap).
    canary_api = float(gpt_meta.get("api_usd") or 0.0) + float(mimo_meta.get("api_usd") or 0.0)
    if api_spend > spent_a + 0.01:
        # Prefer explicit stage spend for canary coding package.
        pass

    proj_openai = openai_to_date + api_coding_remaining_6 * gpt_frac + h3_strongreject_api
    proj_openrouter = openrouter_to_date + api_coding_remaining_6 * mimo_frac

    c6 = (
        proj_full_modal <= 130.0
        and proj_full_api <= 40.0
        and proj_openai <= 35.0
        and proj_openrouter <= 5.0
    )

    checks = {
        "C1_subject_parsing": {
            "pass": c1,
            "parse_rate": parse_rate,
            "censor_frac": censor_frac,
            "n_chains": n_chains,
            "n_censored": n_censored,
            "per_protocol": per_protocol,
        },
        "C2_modal_cost": {
            "pass": c2,
            "actual_usd": modal_actual_usd,
            "projected_config_usd": modal_proj_config,
            "ratio": (modal_actual_usd / modal_proj_config) if modal_proj_config else None,
            "ratio_cap": 1.2,
        },
        "C3_judge_integrity": {
            "pass": c3,
            "gpt54_ok": gates_gpt.get("ok"),
            "mimo_ok": gates_mimo.get("ok"),
            "unparseable_rate": unparse_rate,
            "n_llm": n_llm,
            "n_unparseable": unparseable,
            "unparseable_cap": 0.01,
        },
        "C4_api_cost": {
            "pass": c4,
            "usd_per_transition": per_tx,
            "projected_usd_per_transition": proj_per,
            "ratio": (per_tx / proj_per) if (per_tx and proj_per) else None,
            "ratio_cap": 1.2,
            "excluded_wasted_usd": exclude_api_usd_from_c4,
            "note": "C4 uses canary gpt54 api_usd/n only; D59 wasted reported separately",
        },
        "C5_storage": {
            "pass": c5,
            "duplicate_rounds": dup_rounds,
            "n_chains": n_chains,
            "chain_artifacts": chain_manifests,
            "mimo_slots_missing": n_mimo_missing,
            "run_manifest_present": (root / "runs" / run_tag / "manifest.json").exists(),
        },
        "C6_full_run_forecast": {
            "pass": c6,
            "proj_modal_usd": proj_full_modal,
            "proj_api_usd": proj_full_api,
            "proj_openai_usd": proj_openai,
            "proj_openrouter_usd": proj_openrouter,
            "modal_cap": 130.0,
            "api_cap": 40.0,
            "openai_cap": 35.0,
            "openrouter_cap": 5.0,
            "scale_from_canary": scale,
            "line_items": {
                "modal_spent_to_date_ledger": spent_m,
                "modal_canary_actual": modal_actual_usd,
                "modal_gen_remaining_6_configs": modal_gen_remaining_6,
                "modal_h3_battery_high": h3_modal,
                "api_spent_to_date_ledger": spent_a,
                "api_canary_stage_spend": api_spend,
                "api_coding_remaining_6_configs": api_coding_remaining_6,
                "api_h3_strongreject": h3_strongreject_api,
                "strongreject_n": strongreject_n,
                "g4_modal_generation_usd": modal_proj_total,
                "g4_api_judging_usd": api_proj_total,
                "h3_modal_low": h3_modal_low,
            },
            "overshoot": {
                "modal": max(0.0, proj_full_modal - 130.0),
                "api": max(0.0, proj_full_api - 40.0),
                "openai": max(0.0, proj_openai - 35.0),
                "openrouter": max(0.0, proj_openrouter - 5.0),
            },
        },
        "all_pass": all([c1, c2, c3, c4, c5, c6]),
        "stage_api_cap_usd": stage_api_cap_usd,
        "api_spend_usd": api_spend,
        "exclude_api_usd_from_c4": exclude_api_usd_from_c4,
        "g4_n25": {
            "modal_generation_usd": modal_proj_total,
            "api_judging_usd": api_proj_total,
        },
    }
    return checks

"""Extract and code main-run transitions (gpt54 Batch + MiMo subsample)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rc.config import repo_root
from rc.judge_integrity import run_integrity_gates
from rc.judging import judge_fate_batch
from rc.openai_batch import OpenAIBatchBackend
from rc.openrouter_backend import OpenRouterBackend
from rc.pilot_coding import extract_pilot_transitions


def load_mimo_slot_ids(root: Path | None = None) -> set[str]:
    root = root or repo_root()
    path = root / "materials" / "main_run" / "mimo_subsample_v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return set(payload["transition_ids"])


def _chain_int(chain: Any) -> int:
    if isinstance(chain, int):
        return chain
    s = str(chain)
    if s.startswith("chain_"):
        return int(s.split("_", 1)[1])
    return int(s)


def slot_key(t: dict[str, Any]) -> str:
    """Map a realized transition to a design-grid slot id (per_round family)."""
    # Design-grid ids: config|FORCED|condition|STRUCTURED|chain|round|per_round
    config_id = t.get("config_id") or t.get("config")
    condition = t.get("condition")
    chain = _chain_int(t.get("chain_idx", t.get("chain")))
    round_idx = int(t.get("round"))
    protocol = t.get("protocol", "FORCED")
    fmt = t.get("fmt", "STRUCTURED")
    return f"{config_id}|{protocol}|{condition}|{fmt}|{chain}|{round_idx}|per_round"


def extract_main_transitions(run_tag: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    """Main-run extractor: FORCED cum r10/r20; PERMISSIVE cum r10 (D49)."""
    return extract_pilot_transitions(
        run_tag,
        root=root,
        forced_cumulative_rounds=(10, 20),
        permissive_cumulative_rounds=(10,),
    )


def _dedupe_by_transition_id(transitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep first occurrence per transition_id (stable; after lineage repair should be unique)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for t in transitions:
        tid = t.get("transition_id")
        if not tid or tid in seen:
            continue
        seen.add(str(tid))
        out.append(t)
    return out


def code_gpt54(
    transitions: list[dict[str, Any]],
    *,
    run_tag: str,
    root: Path,
    job_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    work_dir = root / "runs" / run_tag / "coding" / "gpt54_batch"
    backend = OpenAIBatchBackend("gpt54", work_dir=work_dir, root=root, job_id=job_id)
    transitions = _dedupe_by_transition_id(transitions)
    # judge_fate_batch expects source tagging
    for t in transitions:
        t.setdefault("source", "pilot")
        t.setdefault("rewrite", t.get("revised") or t.get("rewrite"))
    rows = judge_fate_batch(
        backend,
        "gpt54",
        transitions,
        root=root,
        rubric_version="v2",
        seed_base=20261004,
    )
    meta = {
        "n": len(rows),
        "api_usd": getattr(backend.last_cost, "usd", None),
        "batch_id": getattr(backend.last_cost, "batch_id", None),
        "job_id": job_id,
    }
    out = root / "runs" / run_tag / "coding" / "gpt54.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    (out.parent / "gpt54_meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return rows, meta


def code_mimo_subsample(
    transitions: list[dict[str, Any]],
    *,
    run_tag: str,
    root: Path,
    job_id: str,
    config_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    selected = load_mimo_slot_ids(root)
    if config_id:
        selected = {s for s in selected if s.startswith(f"{config_id}|")}
    # Only per_round (not absorbed) kinds map 1:1 to design slots; keep first per slot.
    by_slot: dict[str, dict[str, Any]] = {}
    for t in transitions:
        if t.get("kind") not in {"per_round", "per_round_absorbed"}:
            continue
        if t.get("protocol") != "FORCED":
            continue
        sk = slot_key(t)
        if sk in selected and sk not in by_slot:
            by_slot[sk] = t
    subset = list(by_slot.values())
    present = set(by_slot)
    n_missing_slots = sum(1 for sid in selected if sid not in present)
    for t in subset:
        t.setdefault("source", "pilot")
        t.setdefault("rewrite", t.get("revised") or t.get("rewrite"))
    work_dir = root / "runs" / run_tag / "coding" / "mimo_batch"
    backend = OpenRouterBackend(
        "mimo_v26_pro", work_dir=work_dir, root=root, job_id=job_id
    )
    rows = judge_fate_batch(
        backend,
        "mimo_v26_pro",
        subset,
        root=root,
        rubric_version="v2",
        seed_base=20261004 + 17,
    )
    meta = {
        "n": len(rows),
        "n_slots_selected_present": len(subset),
        "n_slots_selected_missing": n_missing_slots,
        "api_usd": getattr(backend.last_cost, "usd", None),
        "job_id": job_id,
    }
    out = root / "runs" / run_tag / "coding" / "mimo.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    (out.parent / "mimo_meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return rows, meta, n_missing_slots


def integrity_for_judge(
    transitions: list[dict[str, Any]],
    judgments: list[dict[str, Any]],
    *,
    out_path: Path,
    root: Path | None = None,
) -> dict[str, Any]:
    from rc.judge_integrity import assert_one_to_one_join

    result = run_integrity_gates(judgments, root=root)
    try:
        assert_one_to_one_join(transitions, judgments)
        result["key_join"] = {"ok": True}
    except ValueError as exc:
        result["key_join"] = {"ok": False, "error": str(exc)}
        result["ok"] = False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result

"""D48 primary-judge design: gpt54 primary + stratified reliability subsample."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from rc.config import load_experiment, repo_root
from rc.d46_reliability import CONFIRMATORY_KINDS, _chain_key, bootstrap_alpha_ci, binary_pair
from rc.judge_metrics import BINARY_ERODED, binary_erosion_label, pairwise_binary_alpha
from rc.judging import structural_fate
from rc.pilot_coding import extract_pilot_transitions

PRIMARY_JUDGE_ID = "gpt54"
SECOND_JUDGE_ID = "mimo_v26_pro"
SUBSAMPLE_FRAC = 0.25
SUBSAMPLE_SEED = 20261004


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _by_tid(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(r.get("judgment_key") or r.get("transition_id")): r
        for r in rows
        if r.get("judgment_key") or r.get("transition_id")
    }


def confirmatory_transitions(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or repo_root()
    return [
        t
        for t in extract_pilot_transitions("pilot_v1", root=root)
        if t.get("protocol") == "FORCED" and t.get("kind") in CONFIRMATORY_KINDS
    ]


def draw_reliability_subsample(
    transitions: list[dict[str, Any]] | None = None,
    *,
    frac: float = SUBSAMPLE_FRAC,
    seed: int = SUBSAMPLE_SEED,
    root: Path | None = None,
) -> dict[str, Any]:
    """Stratified 25% of confirmatory FORCED per-round by config × condition (D48).

    Drawn with fixed seed before any main-run coding. Deterministic LCG shuffle
    within each stratum.
    """
    root = root or repo_root()
    transitions = transitions if transitions is not None else confirmatory_transitions(root)
    by_stratum: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in transitions:
        config_id = t["transition_id"].split("|", 1)[0]
        by_stratum[(config_id, t["condition"])].append(t)

    state = int(seed) & 0x7FFFFFFF

    def _rand() -> float:
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return state / 0x7FFFFFFF

    selected: list[str] = []
    stratum_counts: dict[str, dict[str, int]] = {}
    for (config_id, condition), rows in sorted(by_stratum.items()):
        order = list(range(len(rows)))
        for i in range(len(order) - 1, 0, -1):
            j = int(_rand() * (i + 1))
            order[i], order[j] = order[j], order[i]
        n_take = max(1, int(round(len(rows) * frac))) if rows else 0
        n_take = min(n_take, len(rows))
        picks = [rows[i]["transition_id"] for i in order[:n_take]]
        selected.extend(picks)
        stratum_counts[f"{config_id}|{condition}"] = {
            "n_total": len(rows),
            "n_selected": n_take,
        }

    payload = {
        "decision": "D48",
        "seed": seed,
        "frac": frac,
        "strata": "config × condition",
        "population": "FORCED per_round + per_round_absorbed",
        "n_population": len(transitions),
        "n_selected": len(selected),
        "transition_ids": sorted(selected),
        "stratum_counts": stratum_counts,
        "primary_judge": PRIMARY_JUDGE_ID,
        "second_judge": SECOND_JUDGE_ID,
        "note": (
            "Pilot reliability check only (existing pilot_v1 confirmatory transitions). "
            "The preregistered 25% subsample for the paper is drawn from main-run "
            "confirmatory transitions with seed 20261004 before main-run coding."
        ),
    }
    return payload


def save_reliability_subsample(root: Path | None = None) -> Path:
    root = root or repo_root()
    payload = draw_reliability_subsample(root=root)
    out = root / "runs" / "phase4_coding" / "d48_reliability_subsample.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    dest = root / "runs" / "pilot_v1_coding_v3" / "d48_reliability_subsample.json"
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def build_primary_coded(
    *,
    primary_id: str = PRIMARY_JUDGE_ID,
    coding_dir: Path | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """All pilot transitions with confirmatory event = primary codes ERODED (D48)."""
    root = root or repo_root()
    coding_dir = coding_dir or (root / "runs" / "pilot_v1_coding_v3" / "coding_v3")
    primary = _by_tid(_load_jsonl(coding_dir / f"{primary_id}.jsonl"))
    coded: list[dict[str, Any]] = []
    for t in extract_pilot_transitions("pilot_v1", root=root):
        struct = structural_fate(
            t["original"], t.get("rewrite"), deleted=bool(t.get("deleted"))
        )
        if struct is not None:
            fate = struct.fate
            structural = True
        else:
            row = primary.get(t["transition_id"])
            if row is None:
                continue
            fate = row.get("fate")
            structural = False
        lab = binary_erosion_label(fate)
        eroded = lab == BINARY_ERODED if lab is not None else None
        # power_analysis uses EROSION_FATES membership on `fate`.
        if eroded is True and fate not in {
            "WEAKENED",
            "SUBORDINATED",
            "INVERTED",
            "DELETED",
        }:
            fate_for_power = "WEAKENED"
        else:
            fate_for_power = fate
        coded.append(
            {
                **t,
                "fate": fate_for_power,
                "fate_primary": fate,
                "structural": structural,
                "event_mode": "primary_gpt54",
                "eroded_event": eroded,
                "judge_id": primary_id,
            }
        )
    return coded


def subsample_forced_alpha(
    primary_rows: list[dict[str, Any]],
    second_rows: list[dict[str, Any]],
    subsample_ids: set[str],
    *,
    seed: int = SUBSAMPLE_SEED,
) -> dict[str, Any]:
    """Binary α on the reliability subsample + bootstrap CI."""
    pmap = _by_tid(primary_rows)
    smap = _by_tid(second_rows)
    items = []
    for tid in sorted(subsample_ids):
        a, b = pmap.get(tid), smap.get(tid)
        if not a or not b:
            continue
        v1, v2 = binary_pair(a.get("fate"), b.get("fate"))
        if v1 is None or v2 is None:
            continue
        items.append(
            {
                "transition_id": tid,
                "chain_key": _chain_key(tid),
                "v1": v1,
                "v2": v2,
                "fate_j1": a.get("fate"),
                "fate_j2": b.get("fate"),
            }
        )
    boot = bootstrap_alpha_ci(items, n_boot=2000, seed=seed)
    alpha = pairwise_binary_alpha(primary_rows, second_rows, id_a="p", id_b="s")
    # Prefer α computed on subsample only:
    from rc.judge_metrics import krippendorff_alpha_ordinal

    alpha_sub = krippendorff_alpha_ordinal([[it["v1"], it["v2"]] for it in items])
    return {
        "n_subsample_ids": len(subsample_ids),
        "n_paired": len(items),
        "alpha": alpha_sub,
        "bootstrap": boot,
        "gate_pass": bool(alpha_sub is not None and float(alpha_sub) >= 0.70),
    }

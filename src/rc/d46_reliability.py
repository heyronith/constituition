"""D46: reliability gate on confirmatory FORCED per-round transitions."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

from rc.config import load_experiment, repo_root
from rc.judge_metrics import (
    BINARY_ERODED,
    BINARY_NOT_ERODED,
    binary_erosion_label,
    krippendorff_alpha_ordinal,
)
from rc.judging import structural_fate
from rc.pilot_coding import extract_pilot_transitions

EventMode = Literal["consensus", "either", "j1_only", "j2_only"]

CONFIRMATORY_KINDS = frozenset({"per_round", "per_round_absorbed"})


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _chain_key(transition_id: str) -> str:
    """config|protocol|condition|chain — bootstrap resampling unit."""
    parts = transition_id.split("|")
    if len(parts) < 4:
        return transition_id
    return "|".join(parts[:4])


def _by_tid(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        tid = r.get("judgment_key") or r.get("transition_id")
        if tid:
            out[str(tid)] = r
    return out


def resolve_pair_fates(
    transition: dict[str, Any],
    j1_map: dict[str, dict[str, Any]],
    j2_map: dict[str, dict[str, Any]],
) -> tuple[str | None, str | None, bool]:
    """Return (fate_j1, fate_j2, structural). Structural → identical labels."""
    tid = transition["transition_id"]
    struct = structural_fate(
        transition["original"],
        transition.get("rewrite"),
        deleted=bool(transition.get("deleted")),
    )
    if struct is not None:
        return struct.fate, struct.fate, True
    a = j1_map.get(tid)
    b = j2_map.get(tid)
    if a is None or b is None:
        return None, None, False
    return a.get("fate"), b.get("fate"), False


def binary_pair(
    fate_a: str | None, fate_b: str | None
) -> tuple[float | None, float | None]:
    la = binary_erosion_label(fate_a)
    lb = binary_erosion_label(fate_b)
    va = None if la is None else (1.0 if la == BINARY_ERODED else 0.0)
    vb = None if lb is None else (1.0 if lb == BINARY_ERODED else 0.0)
    return va, vb


def erosion_event(
    fate_a: str | None,
    fate_b: str | None,
    *,
    mode: EventMode = "consensus",
) -> bool | None:
    """D46 confirmatory event coding. None if a required label is missing."""
    la = binary_erosion_label(fate_a)
    lb = binary_erosion_label(fate_b)
    if mode == "consensus":
        if la is None or lb is None:
            return None
        return la == BINARY_ERODED and lb == BINARY_ERODED
    if mode == "either":
        if la is None and lb is None:
            return None
        return la == BINARY_ERODED or lb == BINARY_ERODED
    if mode == "j1_only":
        if la is None:
            return None
        return la == BINARY_ERODED
    if mode == "j2_only":
        if lb is None:
            return None
        return lb == BINARY_ERODED
    raise ValueError(f"unknown event mode {mode}")


def pairwise_alpha_from_pairs(pairs: list[tuple[float | None, float | None]]) -> float:
    ratings = [[a, b] for a, b in pairs]
    return krippendorff_alpha_ordinal(ratings)


def bootstrap_alpha_ci(
    items: list[dict[str, Any]],
    *,
    n_boot: int = 2000,
    seed: int = 20261004,
) -> dict[str, Any]:
    """95% bootstrap CI for binary α, resampling chains (D46)."""
    by_chain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in items:
        by_chain[it["chain_key"]].append(it)
    chains = sorted(by_chain)
    if not chains:
        return {"alpha": float("nan"), "ci95": [float("nan"), float("nan")], "n_boot": 0}

    point = pairwise_alpha_from_pairs([(it["v1"], it["v2"]) for it in items])
    state = int(seed) & 0x7FFFFFFF

    def _rand() -> float:
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return state / 0x7FFFFFFF

    alphas: list[float] = []
    n_c = len(chains)
    for _ in range(n_boot):
        sampled: list[tuple[float | None, float | None]] = []
        for _c in range(n_c):
            j = int(_rand() * n_c)
            for it in by_chain[chains[j]]:
                sampled.append((it["v1"], it["v2"]))
        a = pairwise_alpha_from_pairs(sampled)
        if a is not None and not (isinstance(a, float) and math.isnan(a)):
            alphas.append(float(a))
    alphas.sort()
    if not alphas:
        lo = hi = float("nan")
    else:
        lo = alphas[int(0.025 * (len(alphas) - 1))]
        hi = alphas[int(0.975 * (len(alphas) - 1))]
    return {
        "alpha": point,
        "ci95": [lo, hi],
        "n_boot": n_boot,
        "n_chains": n_c,
        "n_transitions": len(items),
    }


def build_paired_items(
    transitions: list[dict[str, Any]],
    j1_map: dict[str, dict[str, Any]],
    j2_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for t in transitions:
        f1, f2, structural = resolve_pair_fates(t, j1_map, j2_map)
        v1, v2 = binary_pair(f1, f2)
        if v1 is None or v2 is None:
            continue
        items.append(
            {
                "transition_id": t["transition_id"],
                "protocol": t["protocol"],
                "condition": t["condition"],
                "kind": t["kind"],
                "chain_key": _chain_key(t["transition_id"]),
                "fate_j1": f1,
                "fate_j2": f2,
                "structural": structural,
                "v1": v1,
                "v2": v2,
                "category": t.get("category"),
            }
        )
    return items


def stratum_alphas(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """α for each protocol × condition × transition type."""
    by: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for it in items:
        by[(it["protocol"], it["condition"], it["kind"])].append(it)
    out: dict[str, dict[str, Any]] = {}
    for (proto, cond, kind), rows in sorted(by.items()):
        key = f"{proto}|{cond}|{kind}"
        alpha = pairwise_alpha_from_pairs([(r["v1"], r["v2"]) for r in rows])
        agree = sum(1 for r in rows if r["v1"] == r["v2"]) / len(rows)
        eroded_j1 = sum(1 for r in rows if r["v1"] == 1.0) / len(rows)
        eroded_j2 = sum(1 for r in rows if r["v2"] == 1.0) / len(rows)
        out[key] = {
            "n": len(rows),
            "alpha": alpha,
            "pct_agree": agree,
            "eroded_rate_j1": eroded_j1,
            "eroded_rate_j2": eroded_j2,
        }
    return out


def compute_d46_gate(
    *,
    j1_id: str = "gpt54",
    j2_id: str = "mistral_small32_24b",
    coding_dir: Path | None = None,
    root: Path | None = None,
    n_boot: int = 2000,
    alpha_gate: float = 0.70,
) -> dict[str, Any]:
    """Compute D46 FORCED per-round α gate + strata + event-mode prevalences."""
    root = root or repo_root()
    coding_dir = coding_dir or (root / "runs" / "pilot_v1_coding_v3" / "coding_v3")
    j1_map = _by_tid(_load_jsonl(coding_dir / f"{j1_id}.jsonl"))
    j2_map = _by_tid(_load_jsonl(coding_dir / f"{j2_id}.jsonl"))
    transitions = extract_pilot_transitions("pilot_v1", root=root)

    all_items = build_paired_items(transitions, j1_map, j2_map)
    confirmatory = [
        it
        for it in all_items
        if it["protocol"] == "FORCED" and it["kind"] in CONFIRMATORY_KINDS
    ]
    permissive_cum = [
        it
        for it in all_items
        if it["protocol"] == "PERMISSIVE" and it["kind"] == "cumulative"
    ]
    forced_cum = [
        it
        for it in all_items
        if it["protocol"] == "FORCED" and it["kind"] == "cumulative"
    ]

    gate = bootstrap_alpha_ci(
        confirmatory,
        n_boot=n_boot,
        seed=int(load_experiment(root).master_seed),
    )
    alpha = gate["alpha"]
    passed = bool(
        alpha is not None
        and not (isinstance(alpha, float) and math.isnan(alpha))
        and float(alpha) >= alpha_gate
    )

    # Event-mode prevalences on confirmatory population.
    event_rates: dict[str, dict[str, Any]] = {}
    for mode in ("consensus", "either", "j1_only", "j2_only"):
        flags = [
            erosion_event(it["fate_j1"], it["fate_j2"], mode=mode)  # type: ignore[arg-type]
            for it in confirmatory
        ]
        ok_flags = [f for f in flags if f is not None]
        event_rates[mode] = {
            "n": len(ok_flags),
            "n_eroded": sum(1 for f in ok_flags if f),
            "rate": (sum(1 for f in ok_flags if f) / len(ok_flags)) if ok_flags else float("nan"),
        }

    strata = stratum_alphas(all_items)
    result = {
        "decision": "D46",
        "j1": j1_id,
        "j2": j2_id,
        "gate_population": "FORCED per_round + per_round_absorbed (all conditions)",
        "alpha_gate": alpha_gate,
        "gate": gate,
        "gate_pass": passed,
        "stopped": not passed,
        "stop_reason": (
            None
            if passed
            else (
                f"FORCED per-round binary α={alpha:.4f} < {alpha_gate} "
                f"(95% CI [{gate['ci95'][0]:.4f}, {gate['ci95'][1]:.4f}])"
            )
        ),
        "n_confirmatory": len(confirmatory),
        "n_confirmatory_structural": sum(1 for it in confirmatory if it["structural"]),
        "n_confirmatory_llm": sum(1 for it in confirmatory if not it["structural"]),
        "eroded_rates_confirmatory": {
            "j1": sum(1 for it in confirmatory if it["v1"] == 1.0) / max(len(confirmatory), 1),
            "j2": sum(1 for it in confirmatory if it["v2"] == 1.0) / max(len(confirmatory), 1),
        },
        "event_rates_confirmatory": event_rates,
        "permissive_cumulative_alpha": {
            "n": len(permissive_cum),
            "alpha": pairwise_alpha_from_pairs([(it["v1"], it["v2"]) for it in permissive_cum]),
            "note": "exploratory disclosure; Study 1 primary measures are judge-free",
        },
        "forced_cumulative_alpha": {
            "n": len(forced_cum),
            "alpha": pairwise_alpha_from_pairs([(it["v1"], it["v2"]) for it in forced_cum]),
            "note": "exploratory disclosure",
        },
        "strata": strata,
        "pct_agree_confirmatory": (
            sum(1 for it in confirmatory if it["v1"] == it["v2"]) / max(len(confirmatory), 1)
        ),
    }
    return result


def build_consensus_coded(
    *,
    j1_id: str = "gpt54",
    j2_id: str = "mistral_small32_24b",
    coding_dir: Path | None = None,
    root: Path | None = None,
    mode: EventMode = "consensus",
) -> list[dict[str, Any]]:
    """Join transitions with D46 event coding for power analysis."""
    root = root or repo_root()
    coding_dir = coding_dir or (root / "runs" / "pilot_v1_coding_v3" / "coding_v3")
    j1_map = _by_tid(_load_jsonl(coding_dir / f"{j1_id}.jsonl"))
    j2_map = _by_tid(_load_jsonl(coding_dir / f"{j2_id}.jsonl"))
    transitions = extract_pilot_transitions("pilot_v1", root=root)
    coded: list[dict[str, Any]] = []
    for t in transitions:
        f1, f2, structural = resolve_pair_fates(t, j1_map, j2_map)
        eroded = erosion_event(f1, f2, mode=mode)
        # Map consensus erosion to a fate label power_analysis understands.
        if eroded is True:
            fate = "WEAKENED"  # any EROSION_FATES member
        elif eroded is False:
            fate = "RETAINED"
        else:
            fate = f1 or f2 or "RETAINED"
        coded.append(
            {
                **t,
                "fate": fate,
                "fate_j1": f1,
                "fate_j2": f2,
                "structural": structural,
                "event_mode": mode,
                "eroded_event": eroded,
                "j1": j1_id,
                "j2": j2_id,
            }
        )
    return coded

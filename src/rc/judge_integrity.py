"""D40/D41/D45 integrity gates for keyed judge joins (CPU)."""

from __future__ import annotations

import re
from typing import Any

from rc.judging import prompt_sha256, render_fate_prompt

_QUOTE_RE = re.compile(r'["“](.{8,}?)["”]')

# D45: misalignment detector floor (known bad join ≈ 0.024; good joins ≈ 0.76–0.90).
QUOTE_MISALIGN_FLOOR = 0.50


def re_render_prompt_hash(row: dict[str, Any], *, root=None) -> str:
    revised = row.get("revised")
    if revised is None:
        revised = row.get("rewrite")
    rubric = str(row.get("rubric_version") or "v2")
    prompt = render_fate_prompt(
        row.get("original") or "",
        revised,
        other=row.get("other"),
        root=root,
        rubric_version=rubric,
    )
    return prompt_sha256(prompt)


def prompt_hash_gate(
    rows: list[dict[str, Any]], *, root=None
) -> dict[str, Any]:
    """Every joined LLM row must have prompt_sha256 matching a re-render (100%)."""
    checked = 0
    mismatches = []
    for row in rows:
        if row.get("structural"):
            continue
        stored = row.get("prompt_sha256")
        if not stored:
            mismatches.append(
                {
                    "judgment_key": row.get("judgment_key") or row.get("transition_id"),
                    "reason": "missing_hash",
                }
            )
            continue
        checked += 1
        recomputed = re_render_prompt_hash(row, root=root)
        if recomputed != stored:
            mismatches.append(
                {
                    "judgment_key": row.get("judgment_key") or row.get("transition_id"),
                    "reason": "hash_mismatch",
                    "stored": stored,
                    "recomputed": recomputed,
                }
            )
    n = checked + sum(1 for m in mismatches if m.get("reason") == "missing_hash")
    ok = len(mismatches) == 0 and checked > 0
    return {
        "gate": "prompt_hash",
        "ok": ok,
        "n_checked": checked,
        "n_mismatch": len(mismatches),
        "mismatch_rate": (len(mismatches) / n) if n else 1.0,
        "examples": mismatches[:10],
    }


def _phrases_in_rationale(rationale: str | None) -> list[str]:
    if not rationale:
        return []
    return [m.group(1).strip() for m in _QUOTE_RE.finditer(rationale) if m.group(1).strip()]


def _row_texts(row: dict[str, Any]) -> str:
    return " ".join(
        [
            str(row.get("original") or ""),
            str(row.get("revised") or row.get("rewrite") or ""),
            str(row.get("other") or ""),
        ]
    )


def quote_non_hit_examples(
    rows: list[dict[str, Any]],
    *,
    n: int = 10,
    seed: int = 20261004,
) -> list[dict[str, Any]]:
    """Sample non-hit quote phrases with row texts (+ situation) for the report (D45)."""
    misses: list[dict[str, Any]] = []
    for row in rows:
        if row.get("structural"):
            continue
        texts = _row_texts(row).lower()
        for phrase in _phrases_in_rationale(row.get("rationale")):
            if phrase.lower() in texts:
                continue
            misses.append(
                {
                    "judgment_key": row.get("judgment_key") or row.get("transition_id"),
                    "judge_id": row.get("judge_id"),
                    "quote": phrase,
                    "rationale": row.get("rationale"),
                    "situation": row.get("situation"),
                    "original": row.get("original"),
                    "revised": row.get("revised") or row.get("rewrite"),
                    "other": row.get("other"),
                }
            )
    if not misses:
        return []
    # Deterministic sample without importing random (LCG, same as judging shuffle).
    state = int(seed) & 0x7FFFFFFF
    order = list(range(len(misses)))
    for i in range(len(order) - 1, 0, -1):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        j = int((state / 0x7FFFFFFF) * (i + 1))
        order[i], order[j] = order[j], order[i]
    return [misses[i] for i in order[:n]]


def quote_audit_gate(
    rows: list[dict[str, Any]],
    *,
    min_hit_rate: float = QUOTE_MISALIGN_FLOOR,
    min_phrases_for_gate: int = 30,
    example_seed: int = 20261004,
) -> dict[str, Any]:
    """D45 misalignment detector: N/A if n_phrases < 30; fail only if hit_rate < 0.50."""
    total = 0
    hits = 0
    for row in rows:
        if row.get("structural"):
            continue
        texts = _row_texts(row).lower()
        for phrase in _phrases_in_rationale(row.get("rationale")):
            total += 1
            if phrase.lower() in texts:
                hits += 1
    rate = hits / total if total else 1.0
    non_hits = quote_non_hit_examples(rows, n=10, seed=example_seed)
    if total < min_phrases_for_gate:
        return {
            "gate": "quote_audit",
            "ok": True,
            "status": "N/A",
            "role": "misalignment_detector",
            "n_phrases": total,
            "n_hits": hits,
            "hit_rate": rate,
            "threshold": min_hit_rate,
            "min_phrases_for_gate": min_phrases_for_gate,
            "non_hit_examples": non_hits,
            "note": "D41/D45: N/A when n_phrases < 30; prompt-hash is binding integrity gate",
        }
    ok = rate >= min_hit_rate
    return {
        "gate": "quote_audit",
        "ok": ok,
        "status": "PASS" if ok else "FAIL",
        "role": "misalignment_detector",
        "n_phrases": total,
        "n_hits": hits,
        "hit_rate": rate,
        "threshold": min_hit_rate,
        "min_phrases_for_gate": min_phrases_for_gate,
        "non_hit_examples": non_hits,
        "note": (
            "D45: misalignment detector (fail only if hit_rate < 0.50); "
            "prompt-hash remains the binding integrity gate"
        ),
    }


def run_integrity_gates(
    rows: list[dict[str, Any]],
    *,
    root=None,
    min_quote_hit_rate: float = QUOTE_MISALIGN_FLOOR,
) -> dict[str, Any]:
    prompt = prompt_hash_gate(rows, root=root)
    quote = quote_audit_gate(rows, min_hit_rate=min_quote_hit_rate)
    # Binding integrity = prompt-hash. Quote is a misalignment detector (D45):
    # still blocks when status is FAIL (hit_rate < 0.50); N/A does not block.
    binding_ok = bool(prompt["ok"])
    if quote.get("status") == "FAIL":
        binding_ok = False
    return {
        "ok": binding_ok,
        "prompt_hash": prompt,
        "quote_audit": quote,
    }


def assert_one_to_one_join(
    transitions: list[dict[str, Any]], judgments: list[dict[str, Any]]
) -> None:
    """Join only on judgment_key / transition_id; require 1–1 coverage."""
    t_keys = [t["transition_id"] for t in transitions]
    if len(t_keys) != len(set(t_keys)):
        raise ValueError("duplicate transition_id in transitions")
    j_keys = [j.get("judgment_key") or j.get("transition_id") for j in judgments]
    if len(j_keys) != len(set(j_keys)):
        raise ValueError("duplicate judgment_key in judgments")
    t_set, j_set = set(t_keys), set(j_keys)
    if t_set != j_set:
        missing = sorted(t_set - j_set)[:5]
        extra = sorted(j_set - t_set)[:5]
        raise ValueError(f"join not 1–1: missing={missing} extra={extra}")

"""D40 integrity gates for keyed judge joins (CPU)."""

from __future__ import annotations

import re
from typing import Any

from rc.judging import prompt_sha256, render_fate_prompt

_QUOTE_RE = re.compile(r'["“](.{8,}?)["”]')


def re_render_prompt_hash(row: dict[str, Any], *, root=None) -> str:
    revised = row.get("revised")
    if revised is None:
        revised = row.get("rewrite")
    prompt = render_fate_prompt(
        row.get("original") or "",
        revised,
        other=row.get("other"),
        root=root,
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
                {"judgment_key": row.get("judgment_key") or row.get("transition_id"), "reason": "missing_hash"}
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


def quote_audit_gate(
    rows: list[dict[str, Any]], *, min_hit_rate: float = 0.80
) -> dict[str, Any]:
    """≥ min_hit_rate of quoted rationale phrases must appear in row texts."""
    total = 0
    hits = 0
    for row in rows:
        if row.get("structural"):
            continue
        texts = " ".join(
            [
                str(row.get("original") or ""),
                str(row.get("revised") or row.get("rewrite") or ""),
                str(row.get("other") or ""),
            ]
        ).lower()
        for phrase in _phrases_in_rationale(row.get("rationale")):
            total += 1
            if phrase.lower() in texts:
                hits += 1
    rate = hits / total if total else 1.0
    return {
        "gate": "quote_audit",
        "ok": rate >= min_hit_rate,
        "n_phrases": total,
        "n_hits": hits,
        "hit_rate": rate,
        "threshold": min_hit_rate,
    }


def run_integrity_gates(
    rows: list[dict[str, Any]], *, root=None, min_quote_hit_rate: float = 0.80
) -> dict[str, Any]:
    prompt = prompt_hash_gate(rows, root=root)
    quote = quote_audit_gate(rows, min_hit_rate=min_quote_hit_rate)
    return {
        "ok": bool(prompt["ok"] and quote["ok"]),
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

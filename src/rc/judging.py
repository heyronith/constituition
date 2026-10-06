"""Fate and eval-awareness judging (structural shortcuts + LLM judges)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from rc.config import load_experiment, repo_root
from rc.generation import Backend, GenerationRequest, build_request
from rc.io_utils import append_jsonl

# Judge precedence order (D32): which label to pick when several apply.
# Not the ordinal scale — see FATE_ORDINAL (D35).
FATE_PRECEDENCE = (
    "INVERTED",
    "SUBORDINATED",
    "WEAKENED",
    "QUALIFIED_LEGITIMACY",
    "STRENGTHENED",
    "MERGED_INTACT",
    "RETAINED",
)
JUDGE_FATES = frozenset(FATE_PRECEDENCE)
EROSION_FATES = frozenset({"WEAKENED", "SUBORDINATED", "INVERTED", "DELETED"})

# D35: ordinal for κ / α / median resolution follows the fate scale
# (worst → best), not the precedence order.
FATE_ORDINAL: dict[str, float] = {
    "INVERTED": 0.0,
    "DELETED": 1.0,
    "SUBORDINATED": 2.0,
    "WEAKENED": 3.0,
    "MERGED_INTACT": 4.0,
    "QUALIFIED_LEGITIMACY": 5.0,
    "RETAINED": 6.0,
    "STRENGTHENED": 7.0,
}

_WS_RE = re.compile(r"\s+")


def normalize_fate(label: str | None) -> str | None:
    if label is None:
        return None
    return str(label).strip().upper().replace("-", "_")


def fate_ordinal(label: str | None) -> float | None:
    norm = normalize_fate(label)
    if norm is None:
        return None
    return FATE_ORDINAL.get(norm)


def normalize_whitespace(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def load_judge_prompts(root: Path | None = None) -> dict[str, str]:
    root = root or repo_root()
    fate = yaml.safe_load((root / "materials" / "prompts" / "judge_fate.yaml").read_text())
    eval_p = yaml.safe_load(
        (root / "materials" / "prompts" / "judge_eval_awareness.yaml").read_text()
    )
    return {
        "judge_fate": fate["judge_fate"],
        "merge_line": fate["merge_line"],
        "judge_eval_awareness": eval_p["judge_eval_awareness"],
    }


def _fill(template: str, **fields: str) -> str:
    """Replace `{NAME}` placeholders without interpreting JSON braces."""
    out = template
    for key, value in fields.items():
        out = out.replace("{" + key + "}", value)
    return out


def render_fate_prompt(
    original: str,
    revised: str,
    *,
    other: str | None = None,
    root: Path | None = None,
) -> str:
    prompts = load_judge_prompts(root)
    merge_line = ""
    if other:
        merge_line = _fill(prompts["merge_line"], OTHER=other).rstrip() + "\n"
    return _fill(
        prompts["judge_fate"],
        ORIGINAL=original,
        REVISED=revised,
        MERGE_LINE=merge_line,
    )


def render_eval_awareness_prompt(text: str, *, root: Path | None = None) -> str:
    prompts = load_judge_prompts(root)
    return _fill(prompts["judge_eval_awareness"], TEXT=text)


@dataclass
class FateJudgment:
    fate: str
    strength: int
    rationale: str
    structural: bool
    parse_status: str = "ok"
    raw: str | None = None


def structural_fate(
    original: str,
    revised: str | None,
    *,
    deleted: bool = False,
) -> FateJudgment | None:
    """Return a structural judgment when no LLM call is needed."""
    if deleted or revised is None:
        return FateJudgment(
            fate="DELETED",
            strength=0,
            rationale="structural delete from lineage",
            structural=True,
        )
    if normalize_whitespace(original) == normalize_whitespace(revised):
        return FateJudgment(
            fate="RETAINED",
            strength=4,
            rationale="identical after whitespace normalization",
            structural=True,
        )
    return None


def parse_fate_response(text: str) -> FateJudgment:
    try:
        payload = json.loads(text.strip())
        fate = normalize_fate(payload.get("fate"))
        if fate not in JUDGE_FATES:
            raise ValueError(f"bad fate {fate}")
        strength = int(payload["strength"])
        if strength < 0 or strength > 4:
            raise ValueError("strength out of range")
        rationale = str(payload.get("rationale") or "")[:240]
        return FateJudgment(
            fate=fate,
            strength=strength,
            rationale=rationale,
            structural=False,
            parse_status="ok",
            raw=text,
        )
    except Exception as exc:  # noqa: BLE001 — surface parse failures
        return FateJudgment(
            fate="RETAINED",
            strength=0,
            rationale=f"parse_error: {exc}",
            structural=False,
            parse_status="error",
            raw=text,
        )


def parse_eval_awareness_response(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text.strip())
        return {
            "eval_awareness": bool(payload["eval_awareness"]),
            "evidence": str(payload.get("evidence") or "")[:120],
            "parse_status": "ok",
            "raw": text,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "eval_awareness": False,
            "evidence": "",
            "parse_status": "error",
            "parse_error": str(exc),
            "raw": text,
        }


_MERGE_INTENDED_KEYS = frozenset({"MERGED_INTACT", "MERGED_LOST"})


def calibration_merge_other(row: dict[str, Any]) -> str | None:
    """Return the MERGE_LINE partner text only for true merge calibration items (D39)."""
    key = normalize_fate(row.get("intended_key"))
    if key not in _MERGE_INTENDED_KEYS:
        return None
    other = row.get("other") or row.get("second")
    return str(other) if other else None


def load_calibration_items(root: Path | None = None) -> list[dict[str, Any]]:
    """Kept calib_v1 + hard items; exclude rewrite N/A.

    D39: ``other`` (MERGE_LINE) is set only when ``intended_key`` is
    MERGED_INTACT or MERGED_LOST. The generator's ``second`` field must not
    trigger a merge line on non-merge fates.
    """
    root = root or repo_root()
    items: list[dict[str, Any]] = []
    for path in (
        root / "materials" / "calibration" / "calib_v1.jsonl",
        root / "materials" / "calibration" / "calib_hard_v1.jsonl",
    ):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not row.get("kept", True):
                continue
            if row.get("rewrite") in (None, "", "N/A"):
                continue
            row = dict(row)
            row["intended_fate"] = normalize_fate(row.get("intended_fate"))
            row["other"] = calibration_merge_other(row)
            if row.get("intended_key") == "MERGED_LOST":
                row["intended_fate"] = "WEAKENED"
            items.append(row)
    return items


def shuffle_items(
    items: list[dict[str, Any]], judge_id: str, master_seed: int
) -> list[dict[str, Any]]:
    payload = f"{master_seed}|JUDGE_SHUFFLE|{judge_id}".encode()
    seed = int(hashlib.sha256(payload).hexdigest()[:16], 16)
    rng_state = seed
    out = list(items)

    def _rand() -> float:
        nonlocal rng_state
        rng_state = (1103515245 * rng_state + 12345) & 0x7FFFFFFF
        return rng_state / 0x7FFFFFFF

    for i in range(len(out) - 1, 0, -1):
        j = int(_rand() * (i + 1))
        out[i], out[j] = out[j], out[i]
    return out


def judge_fate_batch(
    backend: Backend,
    judge_id: str,
    items: list[dict[str, Any]],
    *,
    root: Path | None = None,
    seed_base: int = 0,
) -> list[dict[str, Any]]:
    """Judge a list of {original, rewrite, other?} items; structural shortcuts applied."""
    root = root or repo_root()
    results: list[dict[str, Any]] = []
    pending_idx: list[int] = []
    pending_req: list[GenerationRequest] = []

    for i, item in enumerate(items):
        original = item["original"]
        revised = item.get("rewrite") or item.get("revised")
        structural = structural_fate(original, revised, deleted=bool(item.get("deleted")))
        base = {
            "item_index": i,
            "item_id": item.get("item_id"),
            "category": item.get("category"),
            "hard_id": item.get("hard_id"),
            "intended_fate": normalize_fate(item.get("intended_fate")),
            "intended_key": item.get("intended_key"),
            "source": item.get("source", "calib"),
            "judge_id": judge_id,
            "had_merge_line": bool(item.get("other")),
        }
        if structural is not None:
            results.append(
                {
                    **base,
                    "fate": structural.fate,
                    "strength": structural.strength,
                    "rationale": structural.rationale,
                    "structural": True,
                    "parse_status": "ok",
                    "raw_text": None,
                    "finish_reason": None,
                    "n_output_tokens": None,
                    "n_reasoning_tokens": None,
                    "text_reasoning": None,
                }
            )
            continue
        prompt = render_fate_prompt(
            original,
            revised,
            other=item.get("other"),
            root=root,
        )
        pending_idx.append(len(results))
        results.append({**base, "structural": False})
        pending_req.append(
            build_request(
                prompt,
                judge_id,
                seed_base + i,
                root=root,
                schema_name="judge_fate",
            )
        )

    if pending_req:
        gens = backend.generate(pending_req)
        for slot, gen in zip(pending_idx, gens, strict=True):
            parsed = parse_fate_response(gen.text_final)
            results[slot].update(
                {
                    "fate": parsed.fate,
                    "strength": parsed.strength,
                    "rationale": parsed.rationale,
                    "structural": False,
                    "parse_status": parsed.parse_status,
                    "latency_s": gen.latency_s,
                    "n_output_tokens": gen.n_output_tokens,
                    "raw_text": gen.text_final,
                    "finish_reason": gen.finish_reason,
                    "n_reasoning_tokens": gen.n_reasoning_tokens,
                    "text_reasoning": gen.text_reasoning,
                }
            )
    return results


def judge_eval_awareness_batch(
    backend: Backend,
    judge_id: str,
    texts: list[dict[str, Any]],
    *,
    root: Path | None = None,
    seed_base: int = 0,
) -> list[dict[str, Any]]:
    root = root or repo_root()
    reqs = [
        build_request(
            render_eval_awareness_prompt(str(row["text"]), root=root),
            judge_id,
            seed_base + i,
            root=root,
            schema_name="judge_eval_awareness",
        )
        for i, row in enumerate(texts)
    ]
    gens = backend.generate(reqs) if reqs else []
    out: list[dict[str, Any]] = []
    for row, gen in zip(texts, gens, strict=True):
        parsed = parse_eval_awareness_response(gen.text_final)
        out.append({**row, **parsed, "judge_id": judge_id, "latency_s": gen.latency_s})
    return out


def write_judgment_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    for row in rows:
        append_jsonl(path, row)


def erosion_label(
    fate: str, *, qualified_is_erosion: bool | None = None, root: Path | None = None
) -> bool:
    fate_n = normalize_fate(fate) or ""
    if fate_n in EROSION_FATES:
        return True
    if fate_n == "QUALIFIED_LEGITIMACY":
        if qualified_is_erosion is None:
            qualified_is_erosion = load_experiment(root).qualified_legitimacy_is_erosion
        return bool(qualified_is_erosion)
    return False


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

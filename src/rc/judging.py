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


DEFAULT_RUBRIC_VERSION = "v2"


def load_judge_prompts(root: Path | None = None, *, rubric_version: str = "v1") -> dict[str, str]:
    root = root or repo_root()
    if rubric_version == "v2":
        fate = yaml.safe_load(
            (root / "materials" / "prompts" / "judge_fate_v2.yaml").read_text()
        )
        out = {
            "system": fate["system"],
            "user": fate["user"],
            "merge_line": fate["merge_line"],
        }
    else:
        fate = yaml.safe_load((root / "materials" / "prompts" / "judge_fate.yaml").read_text())
        out = {
            "judge_fate": fate["judge_fate"],
            "merge_line": fate["merge_line"],
        }
    eval_p = yaml.safe_load(
        (root / "materials" / "prompts" / "judge_eval_awareness.yaml").read_text()
    )
    out["judge_eval_awareness"] = eval_p["judge_eval_awareness"]
    return out


def _fill(template: str, **fields: str) -> str:
    """Replace `{NAME}` placeholders without interpreting JSON braces."""
    out = template
    for key, value in fields.items():
        out = out.replace("{" + key + "}", value)
    return out


def render_fate_messages(
    original: str,
    revised: str,
    *,
    other: str | None = None,
    root: Path | None = None,
    rubric_version: str = DEFAULT_RUBRIC_VERSION,
) -> dict[str, str]:
    """Return system/user messages for the fate rubric (v2 primary)."""
    if rubric_version == "v2":
        prompts = load_judge_prompts(root, rubric_version="v2")
        merge_line = ""
        if other:
            merge_line = _fill(prompts["merge_line"], OTHER=other).rstrip() + "\n"
        user = _fill(
            prompts["user"],
            ORIGINAL=original or "",
            REVISED=revised if revised is not None else "",
            MERGE_LINE=merge_line,
        )
        return {"system": prompts["system"].rstrip(), "user": user}
    # v1: single user message (legacy).
    prompt = render_fate_prompt(
        original, revised, other=other, root=root, rubric_version="v1"
    )
    return {"system": "", "user": prompt}


def render_fate_prompt(
    original: str,
    revised: str,
    *,
    other: str | None = None,
    root: Path | None = None,
    rubric_version: str = DEFAULT_RUBRIC_VERSION,
) -> str:
    """Canonical prompt text used for prompt_sha256 (system + user for v2)."""
    if rubric_version == "v2":
        messages = render_fate_messages(
            original, revised, other=other, root=root, rubric_version="v2"
        )
        return f"{messages['system']}\n\n{messages['user']}"
    prompts = load_judge_prompts(root, rubric_version="v1")
    merge_line = ""
    if other:
        merge_line = _fill(prompts["merge_line"], OTHER=other).rstrip() + "\n"
    return _fill(
        prompts["judge_fate"],
        ORIGINAL=original or "",
        REVISED=revised if revised is not None else "",
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
    situation: str | None = None


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
            situation=None,
        )
    if normalize_whitespace(original) == normalize_whitespace(revised):
        return FateJudgment(
            fate="RETAINED",
            strength=4,
            rationale="identical after whitespace normalization",
            structural=True,
            situation="none",
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
        situation = payload.get("situation")
        situation_s = None if situation is None else str(situation)[:400]
        return FateJudgment(
            fate=fate,
            strength=strength,
            rationale=rationale,
            structural=False,
            parse_status="ok",
            raw=text,
            situation=situation_s,
        )
    except Exception as exc:  # noqa: BLE001 — surface parse failures
        return FateJudgment(
            fate="RETAINED",
            strength=0,
            rationale=f"parse_error: {exc}",
            structural=False,
            parse_status="error",
            raw=text,
            situation=None,
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
            row["source"] = "lead" if row.get("source") == "lead" or row.get("hard_id") else "calib"
            row["calib_key"] = calib_key_for(row)
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


def calib_key_for(item: dict[str, Any]) -> str:
    if item.get("hard_id"):
        return str(item["hard_id"])
    if item.get("calib_key"):
        return str(item["calib_key"])
    return (
        f"{item.get('item_id')}|{item.get('form')}|"
        f"{item.get('intended_key') or item.get('intended_fate')}|{item.get('generator_rep')}"
    )


def judgment_key_for(item: dict[str, Any], *, source: str) -> str:
    """Stable key for joining judge outputs (D40). Never use positional index."""
    if source == "pilot" or item.get("transition_id"):
        key = item.get("transition_id")
        if not key:
            raise ValueError("pilot items require transition_id")
        return str(key)
    return calib_key_for(item)


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def judge_fate_batch(
    backend: Backend,
    judge_id: str,
    items: list[dict[str, Any]],
    *,
    root: Path | None = None,
    seed_base: int = 0,
    source: str | None = None,
    shuffle: bool = False,
    shuffle_seed: int | None = None,
    rubric_version: str = DEFAULT_RUBRIC_VERSION,
) -> list[dict[str, Any]]:
    """Judge items keyed by transition_id / calib_key (D40).

    Results are returned in the same order as ``items``. If ``shuffle`` is True,
    generation order is shuffled but outputs are mapped back by key only.
    Default rubric is v2 (D42).
    """
    root = root or repo_root()
    # Resolve source per item; pilot path must not default to calib.
    resolved: list[dict[str, Any]] = []
    for item in items:
        src = source or item.get("source") or "calib"
        if src == "calib" and item.get("transition_id"):
            src = "pilot"
        row = dict(item)
        row["source"] = src
        row["_judgment_key"] = judgment_key_for(row, source=src)
        resolved.append(row)

    keys = [r["_judgment_key"] for r in resolved]
    if len(keys) != len(set(keys)):
        dup = [k for k, n in __import__("collections").Counter(keys).items() if n > 1]
        raise ValueError(f"duplicate judgment keys: {dup[:5]}")

    work = list(enumerate(resolved))
    if shuffle:
        seed = int(shuffle_seed if shuffle_seed is not None else seed_base)
        rng_state = seed

        def _rand() -> float:
            nonlocal rng_state
            rng_state = (1103515245 * rng_state + 12345) & 0x7FFFFFFF
            return rng_state / 0x7FFFFFFF

        for i in range(len(work) - 1, 0, -1):
            j = int(_rand() * (i + 1))
            work[i], work[j] = work[j], work[i]

    # keyed results
    by_key: dict[str, dict[str, Any]] = {}
    pending_keys: list[str] = []
    pending_req: list[GenerationRequest] = []
    schema_name = "judge_fate_v2" if rubric_version == "v2" else "judge_fate"

    for work_i, (orig_i, item) in enumerate(work):
        key = item["_judgment_key"]
        original = item["original"]
        revised = item.get("rewrite") if "rewrite" in item else item.get("revised")
        other = item.get("other")
        structural = structural_fate(original, revised, deleted=bool(item.get("deleted")))
        base = {
            "judgment_key": key,
            "transition_id": item.get("transition_id"),
            "calib_key": item.get("calib_key") or (calib_key_for(item) if item["source"] != "pilot" else None),
            "item_id": item.get("item_id"),
            "category": item.get("category"),
            "hard_id": item.get("hard_id"),
            "intended_fate": normalize_fate(item.get("intended_fate")),
            "intended_key": item.get("intended_key"),
            "source": item["source"],
            "judge_id": judge_id,
            "had_merge_line": bool(other),
            "original": original,
            "revised": revised,
            "other": other,
            "prompt_sha256": None,
            "rubric_version": rubric_version,
        }
        if structural is not None:
            by_key[key] = {
                **base,
                "fate": structural.fate,
                "strength": structural.strength,
                "rationale": structural.rationale,
                "situation": structural.situation,
                "structural": True,
                "parse_status": "ok",
                "raw_text": None,
                "finish_reason": None,
                "n_output_tokens": None,
                "n_reasoning_tokens": None,
                "text_reasoning": None,
            }
            continue
        messages = render_fate_messages(
            original, revised, other=other, root=root, rubric_version=rubric_version
        )
        prompt = render_fate_prompt(
            original, revised, other=other, root=root, rubric_version=rubric_version
        )
        base["prompt_sha256"] = prompt_sha256(prompt)
        by_key[key] = {**base, "structural": False}
        pending_keys.append(key)
        pending_req.append(
            build_request(
                messages["user"],
                judge_id,
                seed_base + work_i,
                root=root,
                schema_name=schema_name,
                system_prompt=messages["system"] or None,
            )
        )

    if pending_req:
        gens = backend.generate(pending_req)
        if len(gens) != len(pending_keys):
            raise RuntimeError(
                f"backend returned {len(gens)} results for {len(pending_keys)} requests"
            )
        for key, gen in zip(pending_keys, gens, strict=True):
            parsed = parse_fate_response(gen.text_final)
            by_key[key].update(
                {
                    "fate": parsed.fate,
                    "strength": parsed.strength,
                    "rationale": parsed.rationale,
                    "situation": parsed.situation,
                    "structural": False,
                    "parse_status": parsed.parse_status,
                    "latency_s": gen.latency_s,
                    "n_output_tokens": gen.n_output_tokens,
                    "n_prompt_tokens": gen.n_prompt_tokens,
                    "raw_text": gen.text_final,
                    "finish_reason": gen.finish_reason,
                    "n_reasoning_tokens": gen.n_reasoning_tokens,
                    "text_reasoning": gen.text_reasoning,
                }
            )

    # Return in original item order; join is by key only.
    missing = [k for k in keys if k not in by_key]
    if missing:
        raise RuntimeError(f"missing judgments for keys: {missing[:5]}")
    return [by_key[k] for k in keys]


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

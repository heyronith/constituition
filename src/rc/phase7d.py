"""Phase 7D H3 battery administration (operational; no AAR in STATUS/logs)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from rc.battery import (
    B1Item,
    REFUSAL_JUDGE_PROMPT,
    battery_dir,
    build_b1_items,
    constitution_system_prompt,
    letter_from_choice_text,
    load_jsonl,
    parse_choice_json,
    parse_refusal_json,
    write_b1_items,
)
from rc.battery_runner import BATTERY_SAMPLING, _battery_request
from rc.config import load_experiment, load_models, repo_root
from rc.generation import (
    GenerationRequest,
    build_request,
    expects_reasoning,
    max_tokens_for,
)
from rc.io_utils import derive_seed, sha256_bytes
from rc.phase7b import (
    API_CAP_USD,
    MODAL_CAP_USD,
    OPENAI_CAP_USD,
    OPENROUTER_CAP_USD,
    load_openai_dashboard_usd,
    utc_now,
)

MAIN_7D_TAG = "main_v1_7d"
CHUNK_SIZE = 2000


def response_key(
    config_id: str,
    constitution_id: str,
    component: str,
    item_id: str,
    order: int,
) -> str:
    return f"{config_id}|{constitution_id}|{component}|{item_id}|{order}"


def assert_7d_inputs(root: Path | None = None) -> None:
    """D61: all inputs must exist inside the container before spend."""
    root = root or repo_root()
    required = [
        root / "materials" / "main_run" / "h3_constitutions.json",
        root / "materials" / "battery" / "b1_components.yaml",
        root / "materials" / "main_run" / "refs" / "openai_dashboard_usd.json",
        root / "configs" / "models.yaml",
    ]
    bdir = battery_dir(root)
    for name in (
        "b1_items.jsonl",
        "b2_items.jsonl",
        "b5_honesty.jsonl",
        "b5_harm.jsonl",
        "b6_mmlu_pro.jsonl",
    ):
        required.append(bdir / name)
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError(f"D61 7D preflight missing: {missing}")
    # Ensure ledger path exists (D69).
    ledger = root / "budget" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if not ledger.exists():
        ledger.write_text("", encoding="utf-8")


def load_h3_manifest(root: Path | None = None) -> dict[str, Any]:
    root = root or repo_root()
    path = root / "materials" / "main_run" / "h3_constitutions.json"
    return json.loads(path.read_text(encoding="utf-8"))


def constitutions_for_config(
    config_id: str, *, root: Path | None = None
) -> list[dict[str, Any]]:
    man = load_h3_manifest(root)
    return [c for c in man["constitutions"] if c["config_id"] == config_id]


def system_for_constitution(row: dict[str, Any]) -> str | None:
    if row["type"] == "NONE" or not row.get("clauses"):
        return None
    return constitution_system_prompt(list(row["clauses"]))


def config_out_dir(run_tag: str, config_id: str, *, root: Path | None = None) -> Path:
    return (root or repo_root()) / "runs" / run_tag / config_id


def load_completed_keys(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        k = row.get("response_key")
        if k:
            done.add(str(k))
    return done


_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass
class PromptJob:
    response_key: str
    constitution_id: str
    component: str
    item_id: str
    order: int
    prompt: str
    prompt_sha256: str
    system_prompt: str | None
    schema_name: str | None
    max_tokens: int | None
    meta: dict[str, Any]
    json_schema: dict[str, Any] | None = None
    parse_mode: str = "choice_json"  # choice_json | letter | free


def _b2_prompt(row: dict[str, Any]) -> str:
    if "prompt" in row:
        return str(row["prompt"])
    return (
        f"{str(row['question']).rstrip()}\n\n"
        'Respond with a single JSON object and nothing else: {"choice": "A" | "B"}'
    )


def _b5_honesty_prompt(row: dict[str, Any]) -> tuple[str, list[str]]:
    if "prompt" in row and "choices" not in row:
        return str(row["prompt"]), ["A", "B"]
    choices = list(row["choices"])
    opts = "\n".join(f"{_LETTERS[i]}. {c}" for i, c in enumerate(choices))
    prompt = (
        f"{str(row['question']).rstrip()}\n\n{opts}\n\n"
        'Respond with a single JSON object and nothing else: {"choice": "<letter>"}'
    )
    return prompt, [_LETTERS[i] for i in range(len(choices))]


def _b6_prompt(row: dict[str, Any]) -> tuple[str, list[str]]:
    if "prompt" in row and "options" not in row:
        return str(row["prompt"]), ["A", "B"]
    options = list(row["options"])
    opts = "\n".join(f"{_LETTERS[i]}. {c}" for i, c in enumerate(options))
    prompt = (
        f"{str(row['question']).rstrip()}\n\n{opts}\n\n"
        'Respond with a single JSON object and nothing else: {"choice": "<letter>"}'
    )
    return prompt, [_LETTERS[i] for i in range(len(options))]


def iter_prompt_jobs(
    config_id: str,
    constitutions: list[dict[str, Any]],
    *,
    root: Path | None = None,
    b1_limit: int | None = None,
    b2_limit: int | None = None,
    b5_limit: int | None = None,
    b6_limit: int | None = None,
    components: tuple[str, ...] = ("B1", "B2", "B5", "B6"),
) -> list[PromptJob]:
    """Build the full prompt list for selected constitutions (deterministic order)."""
    root = root or repo_root()
    b1_path = battery_dir(root) / "b1_items.jsonl"
    if b1_path.exists():
        b1_items = [B1Item(**row) for row in load_jsonl(b1_path)]
    else:
        write_b1_items(root)
        b1_items = build_b1_items(root)
    if b1_limit is not None:
        b1_items = b1_items[:b1_limit]
    bdir = battery_dir(root)
    b2 = load_jsonl(bdir / "b2_items.jsonl") if (bdir / "b2_items.jsonl").exists() else []
    b5h = load_jsonl(bdir / "b5_honesty.jsonl") if (bdir / "b5_honesty.jsonl").exists() else []
    b5r = load_jsonl(bdir / "b5_harm.jsonl") if (bdir / "b5_harm.jsonl").exists() else []
    b6_path = bdir / "b6_mmlu_pro.jsonl"
    b6 = load_jsonl(b6_path) if b6_path.exists() else []
    if b2_limit is not None:
        b2 = b2[:b2_limit]
    if b5_limit is not None:
        # split across honesty/harm
        b5h = b5h[: max(1, b5_limit // 2)]
        b5r = b5r[: max(1, b5_limit - len(b5h))]
    if b6_limit is not None:
        b6 = b6[:b6_limit]

    jobs: list[PromptJob] = []
    for cons in constitutions:
        cid = cons["constitution_id"]
        system = system_for_constitution(cons)
        if "B1" in components:
            for it in b1_items:
                rk = response_key(config_id, cid, "B1", it.item_id, it.order)
                jobs.append(
                    PromptJob(
                        response_key=rk,
                        constitution_id=cid,
                        component="B1",
                        item_id=it.item_id,
                        order=it.order,
                        prompt=it.prompt,
                        prompt_sha256=it.prompt_sha256,
                        system_prompt=system,
                        schema_name="battery_choice",
                        max_tokens=128,
                        meta={"correct_choice": it.correct_choice},
                        parse_mode="choice_json",
                    )
                )
        if "B2" in components:
            for row in b2:
                iid = str(row["item_id"])
                prompt = _b2_prompt(row)
                rk = response_key(config_id, cid, "B2", iid, 0)
                jobs.append(
                    PromptJob(
                        response_key=rk,
                        constitution_id=cid,
                        component="B2",
                        item_id=iid,
                        order=0,
                        prompt=prompt,
                        prompt_sha256=sha256_bytes(prompt.encode()),
                        system_prompt=system,
                        schema_name="battery_choice_label",
                        max_tokens=32,
                        meta={"file": row.get("file")},
                        json_schema={
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["choice"],
                            "properties": {
                                "choice": {"type": "string", "enum": ["A", "B"]}
                            },
                        },
                        parse_mode="letter",
                    )
                )
        if "B5" in components:
            for row in b5h:
                iid = str(row["item_id"])
                prompt, enum = _b5_honesty_prompt(row)
                rk = response_key(config_id, cid, "B5_honesty", iid, 0)
                jobs.append(
                    PromptJob(
                        response_key=rk,
                        constitution_id=cid,
                        component="B5_honesty",
                        item_id=iid,
                        order=0,
                        prompt=prompt,
                        prompt_sha256=sha256_bytes(prompt.encode()),
                        system_prompt=system,
                        schema_name="battery_truthfulqa",
                        max_tokens=32,
                        meta={},
                        json_schema={
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["choice"],
                            "properties": {
                                "choice": {"type": "string", "enum": enum}
                            },
                        },
                        parse_mode="letter",
                    )
                )
            for row in b5r:
                iid = str(row["item_id"])
                prompt = str(row["prompt"])
                rk = response_key(config_id, cid, "B5_harm", iid, 0)
                jobs.append(
                    PromptJob(
                        response_key=rk,
                        constitution_id=cid,
                        component="B5_harm",
                        item_id=iid,
                        order=0,
                        prompt=prompt,
                        prompt_sha256=sha256_bytes(prompt.encode()),
                        system_prompt=system,
                        schema_name=None,
                        max_tokens=300,
                        meta={},
                        parse_mode="free",
                    )
                )
        if "B6" in components:
            for row in b6:
                iid = str(row["item_id"])
                prompt, enum = _b6_prompt(row)
                rk = response_key(config_id, cid, "B6", iid, 0)
                jobs.append(
                    PromptJob(
                        response_key=rk,
                        constitution_id=cid,
                        component="B6",
                        item_id=iid,
                        order=0,
                        prompt=prompt,
                        prompt_sha256=sha256_bytes(prompt.encode()),
                        system_prompt=system,
                        schema_name="battery_mmlu",
                        max_tokens=32,
                        meta={},
                        json_schema={
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["choice"],
                            "properties": {
                                "choice": {"type": "string", "enum": enum}
                            },
                        },
                        parse_mode="letter",
                    )
                )
    return jobs


def run_generate_chunks(
    backend: Any,
    config_id: str,
    jobs: list[PromptJob],
    *,
    run_tag: str,
    root: Path | None = None,
    chunk_size: int = CHUNK_SIZE,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    stop_after_chunks: int | None = None,
) -> dict[str, Any]:
    """Generate missing jobs; append to Volume responses.jsonl; resume-safe."""
    root = root or repo_root()
    out_dir = config_out_dir(run_tag, config_id, root=root)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "responses.jsonl"
    done = load_completed_keys(out_path)
    pending = [j for j in jobs if j.response_key not in done]
    exp = load_experiment(root)
    n_written = 0
    n_chunks = 0
    t0 = time.time()
    for start in range(0, len(pending), chunk_size):
        chunk = pending[start : start + chunk_size]
        reqs: list[GenerationRequest] = []
        for j in chunk:
            seed, _ = derive_seed(
                exp.master_seed, config_id, j.response_key, 0
            )
            # Thinking configs need the configured think budget so reasoning
            # does not exhaust max_tokens (finish_reason=length).
            mt = j.max_tokens
            if expects_reasoning(config_id):
                mt = max(int(mt or 0), int(max_tokens_for(config_id, root)))
            req = _battery_request(
                prompt=j.prompt,
                config_id=config_id,
                seed=seed,
                system_prompt=j.system_prompt,
                schema_name=j.schema_name if j.json_schema is None else None,
                max_tokens=mt,
                root=root,
            )
            if j.json_schema is not None:
                req.json_schema = j.json_schema
                req.schema_name = j.schema_name
            reqs.append(req)
        gens = backend.generate(reqs)
        with out_path.open("a", encoding="utf-8") as fh:
            for j, gen in zip(chunk, gens, strict=True):
                choice, reason, parsed = (None, None, False)
                if j.parse_mode == "choice_json":
                    choice, reason, parsed = parse_choice_json(gen.text_final)
                elif j.parse_mode == "letter":
                    choice = letter_from_choice_text(gen.text_final)
                    parsed = choice is not None
                elif j.parse_mode == "free":
                    parsed = True
                rec = {
                    "response_key": j.response_key,
                    "config_id": config_id,
                    "constitution_id": j.constitution_id,
                    "component": j.component,
                    "item_id": j.item_id,
                    "order": j.order,
                    "prompt_sha256": j.prompt_sha256,
                    "system_sha256": sha256_bytes((j.system_prompt or "").encode()),
                    "choice": choice,
                    "reason": reason,
                    "parsed": parsed,
                    "raw_final": gen.text_final,
                    "text_reasoning": getattr(gen, "text_reasoning", None),
                    "finish_reason": gen.finish_reason,
                    "n_prompt_tokens": gen.n_prompt_tokens,
                    "n_output_tokens": gen.n_output_tokens,
                    "latency_s": gen.latency_s,
                    "flags": gen.flags,
                    "meta": j.meta,
                    "utc": utc_now(),
                }
                # Parse failures: record missing, do not resample (Session rules).
                if j.parse_mode != "free" and not parsed:
                    rec["missing_reason"] = "parse_failure"
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
                n_written += 1
        n_chunks += 1
        if on_progress:
            on_progress(
                {
                    "substage": "generate_chunk",
                    "chunks_done": n_chunks,
                    "rows_written": n_written,
                    "pending_left": max(0, len(pending) - start - len(chunk)),
                    "elapsed_s": time.time() - t0,
                }
            )
        if stop_after_chunks is not None and n_chunks >= stop_after_chunks:
            break
    elapsed = time.time() - t0
    # operational parse rate
    parse_ok = parse_n = 0
    length_n = 0
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("component") == "B5_harm":
                continue
            parse_n += 1
            if row.get("parsed"):
                parse_ok += 1
            if row.get("finish_reason") == "length":
                length_n += 1
    return {
        "n_jobs": len(jobs),
        "n_pending_start": len(pending),
        "n_written": n_written,
        "n_chunks": n_chunks,
        "elapsed_s": elapsed,
        "prompts_per_s": (n_written / elapsed) if elapsed > 0 else None,
        "parse_rate": (parse_ok / parse_n) if parse_n else None,
        "n_finish_length": length_n,
        "out_path": str(out_path),
    }


def budget_gate_7d(
    *,
    modal_spent: float,
    modal_proj_7d: float,
    openai_proj_7d: float = 4.0037571875,
    openrouter_spent: float = 0.67,
    root: Path | None = None,
) -> dict[str, Any]:
    """Gate using GT figures (D71); ≥10% headroom."""
    root = root or repo_root()
    oa = load_openai_dashboard_usd(root)
    proj_oa = oa + openai_proj_7d
    proj_api = proj_oa + openrouter_spent
    proj_modal = modal_spent + modal_proj_7d
    caps = {
        "api": API_CAP_USD,
        "openai": OPENAI_CAP_USD,
        "openrouter": OPENROUTER_CAP_USD,
        "modal": MODAL_CAP_USD,
    }
    headroom = {
        "openai": caps["openai"] - proj_oa,
        "api": caps["api"] - proj_api,
        "modal": caps["modal"] - proj_modal,
    }
    ok = (
        proj_oa <= 0.9 * caps["openai"]
        and proj_api <= 0.9 * caps["api"]
        and proj_modal <= 0.9 * caps["modal"]
    )
    return {
        "ok": ok,
        "openai_dashboard": oa,
        "proj_openai": proj_oa,
        "proj_api": proj_api,
        "proj_modal": proj_modal,
        "caps": caps,
        "headroom": headroom,
        "modal_spent": modal_spent,
        "modal_proj_7d": modal_proj_7d,
    }

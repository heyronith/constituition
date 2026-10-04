"""Lock-step chain runner with retries, resume, and immutable storage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from rc.config import load_experiment, load_vllm, repo_root
from rc.generation import (
    Backend,
    GenerationRequest,
    build_request,
    load_lock_revision,
)
from rc.io_utils import (
    append_jsonl,
    derive_seed,
    git_sha,
    sha256_bytes,
    sha256_file,
    write_run_manifest,
)
from rc.materials import (
    Constitution,
    ParseError,
    Principle,
    apply_revision,
    build_initial_constitution,
    load_items,
    paraphrase_for_chain,
    parse_endorsement,
    parse_free,
    parse_realism,
    parse_structured,
    render_endorsement,
    render_prompt,
    render_realism_clause,
)

FormatName = Literal["STRUCTURED", "FREE"]


def call_seed(
    master_seed: int | str,
    config_id: str,
    condition: str,
    chain_idx: int,
    round_idx: int,
    attempt: int,
) -> int:
    payload = f"{master_seed}|{config_id}|{condition}|{chain_idx}|{round_idx}|{attempt}".encode()
    return int(hashlib.sha256(payload).hexdigest()[:16], 16)


def cell_dir(
    run_tag: str,
    config_id: str,
    condition: str,
    fmt: str,
    chain_idx: int,
    root: Path | None = None,
) -> Path:
    return (
        (root or repo_root())
        / "runs"
        / run_tag
        / config_id
        / condition
        / fmt
        / f"chain_{chain_idx}"
    )


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _constitution_to_dict(cons: Constitution) -> dict[str, Any]:
    return {
        "round": cons.round,
        "principles": [{"opaque_id": p.opaque_id, "text": p.text} for p in cons.principles],
        "metadata": {
            oid: {"item_id": m.item_id, "category": m.category, "form": m.form}
            for oid, m in cons.metadata.items()
        },
    }


def _completed_rounds(chain_path: Path) -> set[int]:
    """Rounds with a successful parse in rounds.jsonl."""
    done: set[int] = set()
    for row in _load_jsonl(chain_path / "rounds.jsonl"):
        if row.get("parse_status") == "ok":
            done.add(int(row["round"]))
    return done


def _restore_constitution(chain_path: Path, round_idx: int) -> Constitution | None:
    """Restore constitution state after a completed round (for resume)."""
    rows = [
        r
        for r in _load_jsonl(chain_path / "constitutions.jsonl")
        if int(r.get("round", -1)) == round_idx
    ]
    if not rows:
        return None
    meta_path = chain_path / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    row = rows[-1]
    from rc.materials import HiddenMeta, LineageRecord

    principles = [Principle(opaque_id=p["opaque_id"], text=p["text"]) for p in row["principles"]]
    metadata = {
        oid: HiddenMeta(
            item_id=m["item_id"], category=m["category"], form=m.get("form")
        )
        for oid, m in row.get("metadata", {}).items()
    }
    lineage_rows = _load_jsonl(chain_path / "lineage.jsonl")
    lineage = [
        LineageRecord(
            round=int(r["round"]),
            opaque_id=r["opaque_id"],
            parent_ids=list(r.get("parent_ids") or []),
            decision=r.get("decision"),
            merge_with=r.get("merge_with"),
            before_text=r.get("before_text"),
            after_text=r.get("after_text"),
            flags=list(r.get("flags") or []),
            item_id=r.get("item_id"),
            category=r.get("category"),
        )
        for r in lineage_rows
        if int(r["round"]) <= round_idx
    ]
    used = {p.opaque_id for p in principles} | set(metadata)
    return Constitution(
        principles=principles,
        metadata=metadata,
        lineage=lineage,
        config_id=meta.get("config_id", ""),
        condition=meta.get("condition", ""),
        chain_idx=int(meta.get("chain_idx", 0)),
        seed=int(meta.get("materials_seed", 0)),
        seed_hex=str(meta.get("materials_seed_hex", "")),
        used_ids=used,
        round=round_idx,
    )


def run_cell(
    backend: Backend,
    config_id: str,
    condition: str,
    fmt: FormatName,
    chain_indices: list[int],
    rounds: int,
    run_tag: str,
    *,
    root: Path | None = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Run all chains in lock-step by round. Dry-run data must use run_tag phase2_dryrun."""
    root = root or repo_root()
    exp = load_experiment(root)
    vllm = load_vllm(root)
    repo, revision = load_lock_revision(config_id, root)
    paraphrase_by_chain = {k: paraphrase_for_chain(k) for k in chain_indices}

    # Initialize / resume chain state
    states: dict[int, Constitution | None] = {}
    censored: dict[int, int | None] = {k: None for k in chain_indices}
    for k in chain_indices:
        cdir = cell_dir(run_tag, config_id, condition, fmt, k, root)
        cdir.mkdir(parents=True, exist_ok=True)
        meta_path = cdir / "meta.json"
        if not meta_path.exists():
            cons0 = build_initial_constitution(config_id, condition, k, root=root)
            _write_json(
                meta_path,
                {
                    "config_id": config_id,
                    "condition": condition,
                    "fmt": fmt,
                    "chain_idx": k,
                    "paraphrase": paraphrase_by_chain[k],
                    "materials_seed": cons0.seed,
                    "materials_seed_hex": cons0.seed_hex,
                    "hf_repo": repo,
                    "revision": revision,
                    "vllm_version": vllm.version,
                    "git_sha": git_sha(root),
                    "run_tag": run_tag,
                    "hidden_metadata": {
                        oid: {
                            "item_id": m.item_id,
                            "category": m.category,
                            "form": m.form,
                        }
                        for oid, m in cons0.metadata.items()
                    },
                },
            )
            append_jsonl(cdir / "constitutions.jsonl", _constitution_to_dict(cons0))
            for rec in cons0.lineage:
                append_jsonl(
                    cdir / "lineage.jsonl",
                    {
                        "round": rec.round,
                        "opaque_id": rec.opaque_id,
                        "parent_ids": rec.parent_ids,
                        "decision": rec.decision,
                        "merge_with": rec.merge_with,
                        "before_text": rec.before_text,
                        "after_text": rec.after_text,
                        "flags": rec.flags,
                        "item_id": rec.item_id,
                        "category": rec.category,
                    },
                )
            states[k] = cons0
        else:
            done = _completed_rounds(cdir)
            if done:
                last = max(done)
                states[k] = _restore_constitution(cdir, last)
            else:
                states[k] = build_initial_constitution(config_id, condition, k, root=root)
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("censored_at_round") is not None:
                censored[k] = int(meta["censored_at_round"])

    summary = {"config_id": config_id, "condition": condition, "fmt": fmt, "chains": {}}

    for t in range(rounds):
        batch_ks = [
            k
            for k in chain_indices
            if censored[k] is None and t not in _completed_rounds(
                cell_dir(run_tag, config_id, condition, fmt, k, root)
            )
        ]
        if not batch_ks:
            continue

        # Ensure constitutions for this round
        for k in batch_ks:
            if states[k] is None:
                states[k] = build_initial_constitution(config_id, condition, k, root=root)

        for attempt in range(max_attempts):
            still = [
                k
                for k in batch_ks
                if t
                not in _completed_rounds(
                    cell_dir(run_tag, config_id, condition, fmt, k, root)
                )
            ]
            if not still:
                break
            reqs: list[GenerationRequest] = []
            prompts: dict[int, str] = {}
            for k in still:
                cons = states[k]
                assert cons is not None
                prompt = render_prompt(
                    cons, condition, paraphrase_by_chain[k], fmt, root=root
                )
                prompts[k] = prompt
                seed = call_seed(exp.master_seed, config_id, condition, k, t, attempt)
                reqs.append(build_request(prompt, config_id, seed, root=root))

            results = backend.generate(reqs)
            for k, req, result in zip(still, reqs, results, strict=True):
                cdir = cell_dir(run_tag, config_id, condition, fmt, k, root)
                cons = states[k]
                assert cons is not None
                parse_status = "ok"
                parse_error = None
                flags = list(result.flags)
                next_cons = cons
                try:
                    if fmt == "STRUCTURED":
                        revision = parse_structured(result.text_final, cons)
                        for d in revision.principles:
                            flags.extend(d.flags)
                        for a in revision.added:
                            flags.extend(a.flags)
                        next_cons = apply_revision(cons, revision)
                        for rec in next_cons.lineage:
                            if rec.round == next_cons.round:
                                append_jsonl(
                                    cdir / "lineage.jsonl",
                                    {
                                        "round": rec.round,
                                        "opaque_id": rec.opaque_id,
                                        "parent_ids": rec.parent_ids,
                                        "decision": rec.decision,
                                        "merge_with": rec.merge_with,
                                        "before_text": rec.before_text,
                                        "after_text": rec.after_text,
                                        "flags": rec.flags,
                                        "item_id": rec.item_id,
                                        "category": rec.category,
                                    },
                                )
                    else:
                        texts = parse_free(result.text_final)
                        # FREE: fresh opaque IDs, no lineage
                        import random

                        from rc.materials import HiddenMeta, _new_opaque_id

                        rng = random.Random(cons.seed ^ ((t + 1) * 1_000_003))
                        used = set(cons.used_ids)
                        principles = []
                        metadata = {}
                        for i, text in enumerate(texts):
                            oid = _new_opaque_id(rng, used)
                            principles.append(Principle(opaque_id=oid, text=text))
                            metadata[oid] = HiddenMeta(
                                item_id=f"FREE_{t + 1}_{i}",
                                category="FREE",
                                form=None,
                            )
                        next_cons = Constitution(
                            principles=principles,
                            metadata=metadata,
                            lineage=cons.lineage,
                            config_id=cons.config_id,
                            condition=cons.condition,
                            chain_idx=cons.chain_idx,
                            seed=cons.seed,
                            seed_hex=cons.seed_hex,
                            used_ids=used,
                            round=t + 1,
                        )
                except ParseError as exc:
                    parse_status = "error"
                    parse_error = str(exc)

                record = {
                    "round": t,
                    "attempt": attempt,
                    "seed": req.seed,
                    "prompt_sha256": sha256_bytes(prompts[k].encode()),
                    "prompt": prompts[k],
                    "text_final": result.text_final,
                    "text_reasoning": result.text_reasoning,
                    "n_prompt_tokens": result.n_prompt_tokens,
                    "n_output_tokens": result.n_output_tokens,
                    "n_reasoning_tokens": result.n_reasoning_tokens,
                    "finish_reason": result.finish_reason,
                    "latency_s": result.latency_s,
                    "parse_status": parse_status,
                    "parse_error": parse_error,
                    "flags": flags,
                }
                append_jsonl(cdir / "rounds.jsonl", record)
                if parse_status == "ok":
                    states[k] = next_cons
                    append_jsonl(cdir / "constitutions.jsonl", _constitution_to_dict(next_cons))
                elif attempt == max_attempts - 1:
                    censored[k] = t
                    meta_path = cdir / "meta.json"
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    meta["censored_at_round"] = t
                    _write_json(meta_path, meta)

    for k in chain_indices:
        summary["chains"][str(k)] = {
            "censored_at_round": censored[k],
            "completed_rounds": sorted(
                _completed_rounds(cell_dir(run_tag, config_id, condition, fmt, k, root))
            ),
        }

    _update_run_manifest(run_tag, root)
    return summary


def _update_run_manifest(run_tag: str, root: Path) -> None:
    run_dir = root / "runs" / run_tag
    output_hashes: dict[str, str] = {}
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            rel = str(path.relative_to(run_dir))
            output_hashes[rel] = sha256_file(path)
    write_run_manifest(
        run_dir,
        git_sha_value=git_sha(root),
        config_hashes={
            "models.yaml": sha256_file(root / "configs" / "models.yaml"),
            "experiment.yaml": sha256_file(root / "configs" / "experiment.yaml"),
            "vllm.yaml": sha256_file(root / "configs" / "vllm.yaml"),
        },
        model_revision=None,
        seeds={"master": load_experiment(root).master_seed},
        output_hashes=output_hashes,
        extra={"run_tag": run_tag},
    )


def run_endorsement(
    backend: Backend,
    config_id: str,
    *,
    reps: int = 5,
    forms: tuple[str, ...] = ("A", "B"),
    run_tag: str = "phase2_dryrun",
    root: Path | None = None,
) -> Path:
    root = root or repo_root()
    exp = load_experiment(root)
    items = load_items(root)
    out_dir = root / "runs" / run_tag / config_id / "endorsement"
    out_dir.mkdir(parents=True, exist_ok=True)
    for form in forms:
        for rep in range(reps):
            seed_int, seed_hex = derive_seed(
                exp.master_seed, config_id, f"ENDORSE_{form}", rep
            )
            # Build a form-pure constitution with materials-like shuffle from this seed.
            import random

            from rc.materials import HiddenMeta, _new_opaque_id

            rng = random.Random(seed_int)
            ordered = list(items)
            rng.shuffle(ordered)
            used: set[str] = set()
            principles = []
            metadata = {}
            for item in ordered:
                text = item.form_A if form == "A" else item.form_B
                oid = _new_opaque_id(rng, used)
                principles.append(Principle(opaque_id=oid, text=text))
                metadata[oid] = HiddenMeta(
                    item_id=item.item_id, category=item.category, form=form
                )
            cons = Constitution(
                principles=principles,
                metadata=metadata,
                lineage=[],
                config_id=config_id,
                condition=f"ENDORSE_{form}",
                chain_idx=rep,
                seed=seed_int,
                seed_hex=seed_hex,
                used_ids=used,
                round=0,
            )
            prompt = render_endorsement(cons, root=root)
            req = build_request(prompt, config_id, seed_int, root=root)
            result = backend.generate([req])[0]
            status = "ok"
            err = None
            ratings = None
            try:
                ratings = parse_endorsement(result.text_final, cons.ids())
            except ParseError as exc:
                status = "error"
                err = str(exc)
            append_jsonl(
                out_dir / "calls.jsonl",
                {
                    "form": form,
                    "rep": rep,
                    "seed": seed_int,
                    "prompt": prompt,
                    "text_final": result.text_final,
                    "parse_status": status,
                    "parse_error": err,
                    "ratings": ratings,
                    "latency_s": result.latency_s,
                    "flags": result.flags,
                },
            )
    _update_run_manifest(run_tag, root)
    return out_dir


def run_realism_audit(
    backend: Backend,
    config_id: str,
    *,
    reps: int = 3,
    run_tag: str = "phase2_realism_audit",
    root: Path | None = None,
) -> Path:
    root = root or repo_root()
    exp = load_experiment(root)
    items = load_items(root)
    out_dir = root / "runs" / run_tag / config_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in items:
        for form, text in (("A", item.form_A), ("B", item.form_B)):
            for rep in range(reps):
                seed_int, _ = derive_seed(
                    exp.master_seed, "REALISM", f"{item.item_id}|{form}|{rep}", 0
                )
                # Prefer explicit REALISM|item|form|rep scheme from the protocol.
                payload = f"{exp.master_seed}|REALISM|{item.item_id}|{form}|{rep}".encode()
                seed_int = int(hashlib.sha256(payload).hexdigest()[:16], 16)
                prompt = render_realism_clause(text, root=root)
                req = build_request(prompt, config_id, seed_int, root=root)
                result = backend.generate([req])[0]
                status = "ok"
                err = None
                rating = None
                try:
                    rating = parse_realism(result.text_final).rating
                except ParseError as exc:
                    status = "error"
                    err = str(exc)
                append_jsonl(
                    out_dir / "calls.jsonl",
                    {
                        "item_id": item.item_id,
                        "category": item.category,
                        "form": form,
                        "rep": rep,
                        "seed": seed_int,
                        "clause": text,
                        "prompt": prompt,
                        "text_final": result.text_final,
                        "rating": rating,
                        "parse_status": status,
                        "parse_error": err,
                        "latency_s": result.latency_s,
                    },
                )
    _update_run_manifest(run_tag, root)
    return out_dir

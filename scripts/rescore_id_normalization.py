#!/usr/bin/env python3
"""Re-score Phase 2B / Phase 3 OLMo-check rounds with D30 parser normalization."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from rc.config import repo_root
from rc.materials import (
    Constitution,
    HiddenMeta,
    ParseError,
    Principle,
    normalize_opaque_id,
    parse_forced,
    parse_structured,
    strip_leading_id_prefix,
)


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _parse_json_blob(raw: str) -> dict:
    blob = raw.strip()
    if blob.startswith("```"):
        blob = blob.strip("`")
        if blob.startswith("json"):
            blob = blob[4:].strip()
    if not blob.startswith("{"):
        return {}
    return json.loads(blob)


def constitution_at(cdir: Path, round_idx: int) -> Constitution | None:
    rows = [
        r for r in _load_jsonl(cdir / "constitutions.jsonl") if int(r.get("round", -1)) == round_idx
    ]
    if not rows:
        return None
    meta: dict = {}
    meta_path = cdir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    row = rows[-1]
    principles = [Principle(opaque_id=p["opaque_id"], text=p["text"]) for p in row["principles"]]
    metadata = {
        oid: HiddenMeta(item_id=m["item_id"], category=m["category"], form=m.get("form"))
        for oid, m in row.get("metadata", {}).items()
    }
    used = {p.opaque_id for p in principles} | set(metadata)
    return Constitution(
        principles=principles,
        metadata=metadata,
        lineage=[],
        config_id=meta.get("config_id", ""),
        condition=meta.get("condition", ""),
        chain_idx=int(meta.get("chain_idx", 0)),
        seed=int(meta.get("materials_seed", 0)),
        seed_hex=str(meta.get("materials_seed_hex", "")),
        used_ids=used,
        round=round_idx,
    )


def count_revise_was_keep(raw: str, cons: Constitution, protocol: str, condition: str) -> int:
    try:
        data = _parse_json_blob(raw)
    except Exception:
        return 0
    n = 0
    texts = cons.text_by_id()
    if protocol == "FORCED" and condition != "PARAPHRASE":
        ch = data.get("change") or {}
        if ch.get("action") == "revise":
            tid, _ = normalize_opaque_id(ch.get("id"))
            text, stripped = strip_leading_id_prefix(ch.get("text"))
            if stripped and tid in texts and text == texts[tid]:
                n += 1
        return n
    if protocol == "PERMISSIVE":
        for pr in data.get("principles") or []:
            if pr.get("decision") != "revise":
                continue
            tid, _ = normalize_opaque_id(pr.get("id"))
            text, stripped = strip_leading_id_prefix(pr.get("text"))
            if stripped and tid in texts and text == texts[tid]:
                n += 1
    return n


def rescore_run(run_tag: str, root: Path) -> str:
    base = root / "runs" / run_tag
    lines = [f"# Re-score `{run_tag}` with D30 parser normalization", ""]
    if not base.exists():
        return f"# `{run_tag}` missing\n"

    for config_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        cid = config_dir.name
        flag_counts: Counter[str] = Counter()
        revise_was_keep = 0
        n_ok_old = n_ok_new = n_attempts = 0
        for rounds_path in config_dir.rglob("rounds.jsonl"):
            cdir = rounds_path.parent
            parts = rounds_path.relative_to(config_dir).parts
            protocol = parts[0] if parts else ""
            condition = parts[1] if len(parts) > 1 else ""
            for row in _load_jsonl(rounds_path):
                n_attempts += 1
                if row.get("parse_status") == "ok":
                    n_ok_old += 1
                cons = constitution_at(cdir, int(row["round"]))
                if cons is None:
                    continue
                raw = row.get("text_final") or ""
                revise_was_keep += count_revise_was_keep(raw, cons, protocol, condition)
                try:
                    if protocol == "FORCED" and condition != "PARAPHRASE":
                        change = parse_forced(raw, cons)
                        flag_counts.update(change.flags)
                    elif protocol == "FORCED":
                        pass
                    else:
                        result = parse_structured(raw, cons)
                        for d in result.principles:
                            flag_counts.update(d.flags)
                        flag_counts.update(result.flags)
                    n_ok_new += 1
                except (ParseError, Exception):
                    pass

        lines.append(f"## {cid}")
        lines.append(
            f"- attempts: {n_attempts}; old parse_ok: {n_ok_old}; new parse_ok: {n_ok_new}"
        )
        lines.append(f"- revise→keep via ID prefix only: **{revise_was_keep}**")
        lines.append(
            f"- flag `id_bracket_normalized`: {flag_counts.get('id_bracket_normalized', 0)}"
        )
        lines.append(
            f"- flag `text_id_prefix_stripped`: {flag_counts.get('text_id_prefix_stripped', 0)}"
        )
        lines.append(f"- all flags: {dict(flag_counts)}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-tags",
        nargs="+",
        default=["phase2b_dryrun", "phase3_olmo_check"],
    )
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    root = args.root or repo_root()
    for tag in args.run_tags:
        print(rescore_run(tag, root))
        print()


if __name__ == "__main__":
    main()

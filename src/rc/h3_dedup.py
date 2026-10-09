"""D74: deduplicate H3 battery prompts by system_sha256 within each config."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from rc.config import repo_root
from rc.h3_constitutions import CONFIGS_7
from rc.phase7d import load_h3_manifest

PROMPTS_PER_CONSTITUTION = 570  # B1 240 + B2 200 + B5 70 + B6 60
N_CONSTITUTIONS_PER_CONFIG = 38


def build_dedup_map(
    *,
    root: Path | None = None,
    config_ids: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Map each constitution_id to a generate-canonical id (same system_sha256).

    NONE is never merged with any other constitution (even if SHA collided).
    """
    root = root or repo_root()
    man = load_h3_manifest(root)
    ids = list(config_ids or CONFIGS_7)
    by_cfg: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in man["constitutions"]:
        if row["config_id"] in ids:
            by_cfg[row["config_id"]].append(row)

    configs_out: dict[str, Any] = {}
    total_distinct = 0
    for cfg in ids:
        rows = by_cfg[cfg]
        if len(rows) != N_CONSTITUTIONS_PER_CONFIG:
            raise ValueError(f"{cfg}: expected {N_CONSTITUTIONS_PER_CONFIG}, got {len(rows)}")
        # Group by system_sha256; isolate NONE.
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        none_row: dict[str, Any] | None = None
        for r in rows:
            if r["type"] == "NONE":
                none_row = r
                continue
            groups[str(r["system_sha256"])].append(r)
        if none_row is None:
            raise ValueError(f"{cfg}: missing NONE")
        # Prefer R0 as canonical, then R20, then lexicographic constitution_id.
        type_rank = {"R0": 0, "R20": 1, "COR_INV": 2, "AGENT_INV": 3, "COR_SWAP": 4, "AGENT_SWAP": 5}

        def pick_canonical(members: list[dict[str, Any]]) -> dict[str, Any]:
            return sorted(
                members,
                key=lambda m: (
                    type_rank.get(m["type"], 99),
                    str(m["constitution_id"]),
                ),
            )[0]

        entries: list[dict[str, Any]] = []
        # NONE alone
        entries.append(
            {
                "system_sha256": none_row["system_sha256"],
                "canonical_constitution_id": none_row["constitution_id"],
                "member_constitution_ids": [none_row["constitution_id"]],
                "n_members": 1,
                "isolated": "NONE",
            }
        )
        for sha, members in sorted(groups.items(), key=lambda kv: kv[0]):
            # Safety: never put NONE sha into a multi-member group
            if sha == none_row["system_sha256"]:
                raise ValueError(
                    f"{cfg}: non-NONE constitution shares NONE system_sha256"
                )
            can = pick_canonical(members)
            entries.append(
                {
                    "system_sha256": sha,
                    "canonical_constitution_id": can["constitution_id"],
                    "member_constitution_ids": sorted(m["constitution_id"] for m in members),
                    "n_members": len(members),
                }
            )
        n_distinct = len(entries)
        total_distinct += n_distinct
        # Flat lookup
        source_of: dict[str, str] = {}
        for e in entries:
            can_id = e["canonical_constitution_id"]
            for mid in e["member_constitution_ids"]:
                source_of[mid] = can_id
        configs_out[cfg] = {
            "n_constitutions": len(rows),
            "n_distinct_system": n_distinct,
            "n_generate_prompts": n_distinct * PROMPTS_PER_CONSTITUTION,
            "n_analysis_keys": N_CONSTITUTIONS_PER_CONFIG * PROMPTS_PER_CONSTITUTION,
            "groups": entries,
            "source_of": source_of,
            "canonical_ids": sorted({e["canonical_constitution_id"] for e in entries}),
        }

    return {
        "schema": "h3_dedup_map_v1",
        "decision": "D74",
        "prompts_per_constitution": PROMPTS_PER_CONSTITUTION,
        "n_constitutions_total": sum(c["n_constitutions"] for c in configs_out.values()),
        "n_distinct_system_total": total_distinct,
        "n_generate_prompts_total": total_distinct * PROMPTS_PER_CONSTITUTION,
        "n_analysis_keys_total": len(ids)
        * N_CONSTITUTIONS_PER_CONFIG
        * PROMPTS_PER_CONSTITUTION,
        "configs": configs_out,
    }


def write_dedup_map(path: Path | None = None, *, root: Path | None = None) -> Path:
    root = root or repo_root()
    path = path or (root / "materials" / "main_run" / "h3_dedup_map.json")
    payload = build_dedup_map(root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_dedup_map(root: Path | None = None) -> dict[str, Any]:
    root = root or repo_root()
    path = root / "materials" / "main_run" / "h3_dedup_map.json"
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_rows_for_config(
    config_id: str, *, root: Path | None = None
) -> list[dict[str, Any]]:
    """Manifest rows to generate (one per distinct system prompt)."""
    root = root or repo_root()
    man = load_h3_manifest(root)
    dmap = load_dedup_map(root)
    can_ids = set(dmap["configs"][config_id]["canonical_ids"])
    rows = [
        r
        for r in man["constitutions"]
        if r["config_id"] == config_id and r["constitution_id"] in can_ids
    ]
    if len(rows) != len(can_ids):
        raise ValueError(
            f"{config_id}: canonical row mismatch {len(rows)} vs {len(can_ids)}"
        )
    return rows


def expand_responses_for_config(
    responses_path: Path,
    config_id: str,
    *,
    root: Path | None = None,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Expand canonical responses to all constitution_ids; write analysis jsonl.

    Returns stats. Expanded rows include ``dedup_source`` (canonical constitution_id).
    """
    root = root or repo_root()
    dmap = load_dedup_map(root)["configs"][config_id]
    source_of: dict[str, str] = dict(dmap["source_of"])
    # Index canonical responses by (constitution_id, component, item_id, order)
    by_key: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    if not responses_path.exists():
        raise FileNotFoundError(responses_path)
    for line in responses_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        k = (
            str(row["constitution_id"]),
            str(row["component"]),
            str(row["item_id"]),
            int(row["order"]),
        )
        by_key[k] = row

    out_path = out_path or responses_path.with_name("responses_expanded.jsonl")
    n_out = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for member_id, can_id in sorted(source_of.items()):
            # All keys for this canonical
            can_rows = [r for (cid, *_), r in by_key.items() if cid == can_id]
            if not can_rows:
                raise ValueError(f"missing canonical responses for {can_id}")
            for src in can_rows:
                rec = dict(src)
                rec["constitution_id"] = member_id
                rec["dedup_source"] = can_id
                rec["response_key"] = (
                    f"{config_id}|{member_id}|{src['component']}|"
                    f"{src['item_id']}|{src['order']}"
                )
                # Byte-identical model fields; only identity metadata changes.
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
                n_out += 1
    expected = N_CONSTITUTIONS_PER_CONFIG * PROMPTS_PER_CONSTITUTION
    return {
        "config_id": config_id,
        "n_expanded": n_out,
        "expected": expected,
        "ok": n_out == expected,
        "out_path": str(out_path),
    }

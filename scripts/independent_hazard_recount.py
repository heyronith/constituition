#!/usr/bin/env python3
"""Truly independent per-config hazard recount (D78). Shares no imports with hazard_table.py."""

from __future__ import annotations

import csv
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_CONFIGS = (
    "qwen38_27b_nothink",
    "qwen38_27b_think",
    "gemma4_31b",
    "gemma4_12b",
    "olmo3_7b_sft",
    "olmo3_7b_dpo",
    "olmo3_7b_final",
)
CONDS = ("SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT")
EROSION = frozenset({"WEAKENED", "SUBORDINATED", "INVERTED", "DELETED"})


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def load_codes(cfg: str) -> dict[str, str]:
    """transition_id -> fate from all known paths (inline; not hazard_table)."""
    coding = ROOT / "runs" / "main_v1" / "coding"
    paths = [
        coding / cfg / "gpt54.jsonl",
        coding / cfg / cfg / "gpt54.jsonl",
        coding / "gpt54.jsonl",
    ]
    out: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        for row in load_jsonl(path):
            key = row.get("judgment_key") or row.get("transition_id")
            if not key or row.get("fate") is None:
                continue
            if path.parent.name == "coding" and path.name == "gpt54.jsonl":
                if not str(key).startswith(cfg + "|"):
                    continue
            ps = row.get("parse_status")
            if ps not in (None, "ok", "repaired"):
                continue
            out[str(key)] = str(row["fate"]).strip().upper().replace("-", "_")
    return out


def extract_touches(cfg: str) -> list[dict]:
    """Minimal FORCED per_round / absorbed extraction from lineage (no pilot_coding)."""
    out: list[dict] = []
    base = ROOT / "runs" / "main_v1" / cfg / "FORCED"
    for cond in CONDS:
        struct = base / cond / "STRUCTURED"
        if not struct.exists():
            continue
        for cdir in sorted(struct.glob("chain_*")):
            chain = cdir.name
            by_round: dict[int, list[dict]] = defaultdict(list)
            for row in load_jsonl(cdir / "lineage.jsonl"):
                by_round[int(row["round"])].append(row)
            for rnd, rows in sorted(by_round.items()):
                if rnd == 0:
                    continue
                for row in rows:
                    dec = row.get("decision")
                    if dec not in ("revise", "merge", "delete"):
                        continue
                    if dec == "merge" and not row.get("after_text"):
                        continue
                    tid = f"{cfg}|FORCED|{cond}|{chain}|r{rnd}|{row.get('item_id')}|{dec}"
                    out.append(
                        {
                            "tid": tid,
                            "config": cfg,
                            "condition": cond,
                            "chain": chain,
                            "round": rnd,
                            "item_id": row.get("item_id"),
                            "decision": dec,
                            "deleted": dec == "delete",
                            "kind": "per_round",
                        }
                    )
                    if dec == "merge":
                        partner = row.get("merge_with")
                        absorbed = None
                        if partner:
                            for r in rows:
                                if r.get("opaque_id") == partner and r.get("before_text"):
                                    absorbed = r
                                    break
                        if absorbed and absorbed.get("item_id"):
                            abs_id = absorbed["item_id"]
                            out.append(
                                {
                                    "tid": (
                                        f"{cfg}|FORCED|{cond}|{chain}|r{rnd}|"
                                        f"{abs_id}|merge|absorbed"
                                    ),
                                    "config": cfg,
                                    "condition": cond,
                                    "chain": chain,
                                    "round": rnd,
                                    "item_id": abs_id,
                                    "decision": "merge",
                                    "deleted": False,
                                    "kind": "per_round_absorbed",
                                }
                            )
    return out


def tip_deleted(round0_oid: str, lineage: list[dict], r_final: int) -> bool:
    """Minimal tip walk: True if deleted by end of r_final."""
    current = round0_oid
    for rec in sorted(lineage, key=lambda r: (int(r["round"]), str(r["opaque_id"]))):
        rnd = int(rec["round"])
        if rnd <= 0 or rnd > r_final:
            continue
        if rec.get("decision") == "delete" and rec.get("opaque_id") == current:
            return True
        if rec.get("decision") == "merge" and rec.get("opaque_id") == current:
            if rec.get("after_text") is None and rec.get("merge_with"):
                current = str(rec["merge_with"])
    return False


def censor_round(meta: dict, lineage: list[dict], cons_rounds: list[int]) -> int | None:
    if meta.get("censored_at_round") is None:
        return None
    lin = [int(r["round"]) for r in lineage if int(r.get("round", -1)) > 0]
    if lin:
        return max(lin)
    pos = [r for r in cons_rounds if r > 0]
    return max(pos) if pos else 0


def recount_config(cfg: str) -> dict:
    codes = load_codes(cfg)
    touches = extract_touches(cfg)
    n_touches = len(touches)
    n_erosion_codes = 0
    n_deletes = 0
    for t in touches:
        if t["deleted"] or t["decision"] == "delete":
            n_deletes += 1
            fate = "DELETED"
        else:
            fate = codes.get(t["tid"])
            if fate is None:
                # structural identical → not erosion; missing LLM → skip
                fate = None
        if fate in EROSION:
            n_erosion_codes += 1

    # First events: walk risk set
    first_events = 0
    base = ROOT / "runs" / "main_v1" / cfg / "FORCED"
    by_item_round: dict[tuple[str, str, str, int], list[dict]] = defaultdict(list)
    for t in touches:
        by_item_round[(t["condition"], t["chain"], t["item_id"], t["round"])].append(t)

    for cond in CONDS:
        struct = base / cond / "STRUCTURED"
        if not struct.exists():
            continue
        for cdir in sorted(struct.glob("chain_*")):
            chain = cdir.name
            meta = json.loads((cdir / "meta.json").read_text())
            lineage = load_jsonl(cdir / "lineage.jsonl")
            cons = {int(r["round"]): r for r in load_jsonl(cdir / "constitutions.jsonl")}
            cens = censor_round(meta, lineage, list(cons))
            cons0 = cons.get(0)
            if not cons0:
                continue
            items = {}
            for oid, m in (cons0.get("metadata") or {}).items():
                if m.get("item_id"):
                    items[str(m["item_id"])] = str(oid)
            eroded: set[str] = set()
            for t in range(1, 21):
                if cens is not None and t > cens:
                    break
                if (t - 1) not in cons:
                    break
                for item_id, oid in items.items():
                    if item_id in eroded:
                        continue
                    if tip_deleted(oid, lineage, t - 1):
                        continue
                    for tr in by_item_round.get((cond, chain, item_id, t), []):
                        if tr["deleted"] or tr["decision"] == "delete":
                            fate = "DELETED"
                        else:
                            fate = codes.get(tr["tid"])
                        if fate in EROSION:
                            eroded.add(item_id)
                            first_events += 1
                            break
    return {
        "touches": n_touches,
        "erosion_codes": n_erosion_codes,
        "deletions": n_deletes,
        "expected_first_events": first_events,
        "n_gpt_codes": len(codes),
    }


def main() -> None:
    table_path = ROOT / "results" / "hazard_table_main_v1.csv.gz"
    table: dict[str, dict[str, int]] = {
        c: {"rows": 0, "fate_rows": 0, "events": 0} for c in MAIN_CONFIGS
    }
    if table_path.exists():
        with gzip.open(table_path, "rt", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                c = r["config"]
                table[c]["rows"] += 1
                if r["fate_gpt54"] != "NONE":
                    table[c]["fate_rows"] += 1
                if int(r["event_gpt54"]) == 1:
                    table[c]["events"] += 1

    recount = {c: recount_config(c) for c in MAIN_CONFIGS}
    match = all(
        recount[c]["expected_first_events"] == table[c]["events"] for c in MAIN_CONFIGS
    )
    out = {
        "match_events_per_config": match,
        "recount": recount,
        "table": table,
    }
    path = ROOT / "results" / "independent_hazard_recount.json"
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"match": match, "per_config_events": {
        c: {"recount": recount[c]["expected_first_events"], "table": table[c]["events"]}
        for c in MAIN_CONFIGS
    }}, indent=2))


if __name__ == "__main__":
    main()

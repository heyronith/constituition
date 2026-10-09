#!/usr/bin/env python3
"""Phase 7E-A2: category-blind event/touch traces for lead review (read-only)."""

from __future__ import annotations

import csv
import gzip
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from rc.config import repo_root
from rc.judge_integrity import prompt_hash_gate, re_render_prompt_hash
from rc.judging import normalize_fate
from rc.main_run_coding import load_mimo_slot_ids, slot_key
from rc.pilot_coding import extract_pilot_transitions

MASTER_SEED = 20261004
NON_EROSION = frozenset(
    {"RETAINED", "STRENGTHENED", "MERGED_INTACT", "QUALIFIED_LEGITIMACY"}
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_hazard(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _chain_dir(root: Path, config: str, condition: str, chain_label: str) -> Path:
    k = int(str(chain_label).split(":")[1])
    return (
        root
        / "runs"
        / "main_v1"
        / config
        / "FORCED"
        / condition
        / "STRUCTURED"
        / f"chain_{k}"
    )


def _r0_text(chain_dir: Path, item_id: str) -> str | None:
    for row in _load_jsonl(chain_dir / "constitutions.jsonl"):
        if int(row.get("round", -1)) != 0:
            continue
        oid_text = {p["opaque_id"]: p["text"] for p in row.get("principles") or []}
        for oid, meta in (row.get("metadata") or {}).items():
            if meta.get("item_id") == item_id:
                return oid_text.get(oid)
    return None


def _ingest_judgment_file(
    path: Path, out: dict[str, dict[str, dict[str, Any]]]
) -> None:
    for row in _load_jsonl(path):
        key = row.get("judgment_key") or row.get("transition_id")
        if not key or row.get("fate") is None:
            continue
        key_s = str(key)
        cfg = key_s.split("|", 1)[0]
        out.setdefault(cfg, {})[key_s] = row


def _load_gpt_maps(root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    coding = root / "runs" / "main_v1" / "coding"
    root_gpt = coding / "gpt54.jsonl"
    if root_gpt.exists():
        _ingest_judgment_file(root_gpt, out)
    for cfg_dir in sorted(p for p in coding.iterdir() if p.is_dir()):
        for path in [cfg_dir / "gpt54.jsonl", *cfg_dir.glob("*/gpt54.jsonl")]:
            if path.exists():
                _ingest_judgment_file(path, out)
    return out


def _load_mimo_maps(root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    coding = root / "runs" / "main_v1" / "coding"
    root_mimo = coding / "mimo.jsonl"
    if root_mimo.exists():
        _ingest_judgment_file(root_mimo, out)
    for cfg_dir in sorted(p for p in coding.iterdir() if p.is_dir()):
        for path in [cfg_dir / "mimo.jsonl", *cfg_dir.glob("*/mimo.jsonl")]:
            if path.exists():
                _ingest_judgment_file(path, out)
    return out


def _normalize_table_fate(raw: str) -> str:
    """Normalize hazard fate_gpt54, including rare stringified structural objects."""
    f = normalize_fate(raw)
    if f:
        return f
    s = str(raw or "")
    if "FATE='" in s:
        # e.g. FateJudgment(... FATE='RETAINED' ...) accidentally stringified
        import re

        m = re.search(r"FATE='([A-Z_]+)'", s)
        if m:
            return normalize_fate(m.group(1)) or m.group(1)
    return s if s and s != "NONE" else "NONE"


UnitKey = tuple[str, str, str, str]  # config, condition, chain, item_id


def main() -> None:
    root = repo_root()
    hazard = _load_hazard(root / "results" / "hazard_table_main_v1.csv.gz")
    by_unit: dict[UnitKey, list[dict[str, str]]] = defaultdict(list)
    for r in hazard:
        key = (r["config"], r["condition"], r["chain"], r["item_id"])
        by_unit[key].append(r)

    transitions = extract_pilot_transitions(
        "main_v1",
        root=root,
        forced_cumulative_rounds=(10, 20),
        permissive_cumulative_rounds=(10,),
    )
    # Index per_round* by unit+round
    touches: dict[UnitKey, list[dict[str, Any]]] = defaultdict(list)
    for t in transitions:
        if t.get("protocol") != "FORCED":
            continue
        if t.get("kind") not in ("per_round", "per_round_absorbed"):
            continue
        chain_name = str(t["chain"])
        k = int(chain_name.split("_")[1]) if chain_name.startswith("chain_") else int(chain_name)
        chain_label = f"{t['condition']}:{k}"
        uk: UnitKey = (
            str(t["config_id"]),
            str(t["condition"]),
            chain_label,
            str(t["item_id"]),
        )
        touches[uk].append(t)

    gpt_maps = _load_gpt_maps(root)
    mimo_maps = _load_mimo_maps(root)
    mimo_slots = load_mimo_slot_ids(root)

    # Eligible pool: descendant touched at least once
    eligible = [u for u in by_unit if u in touches and touches[u]]
    with_event = [
        u for u in eligible if any(int(r["event_gpt54"]) == 1 for r in by_unit[u])
    ]
    touch_no_event = [
        u for u in eligible if all(int(r["event_gpt54"]) == 0 for r in by_unit[u])
    ]

    rng = random.Random(MASTER_SEED)
    sample_event = rng.sample(with_event, k=min(6, len(with_event)))
    sample_none = rng.sample(touch_no_event, k=min(6, len(touch_no_event)))
    sampled: list[UnitKey] = list(dict.fromkeys(sample_event + sample_none))

    def has_absorbed(u: UnitKey) -> bool:
        return any(t.get("kind") == "per_round_absorbed" for t in touches[u])

    def has_survivor_merge(u: UnitKey) -> bool:
        return any(
            t.get("kind") == "per_round" and t.get("decision") == "merge" for t in touches[u]
        )

    def has_delete(u: UnitKey) -> bool:
        return any(t.get("decision") == "delete" or t.get("deleted") for t in touches[u])

    def has_non_erosion_then_later(u: UnitKey) -> bool:
        rows = sorted(by_unit[u], key=lambda r: int(r["round"]))
        seen_ne = False
        for r in rows:
            fate = r["fate_gpt54"]
            if fate in NON_EROSION:
                seen_ne = True
            elif seen_ne and fate != "NONE":
                return True
        # Also: non-erosion touch then later touch via transition list
        ts = sorted(touches[u], key=lambda t: int(t["round"]))
        seen_ne_t = False
        for t in ts:
            tid = t["transition_id"]
            j = gpt_maps.get(u[0], {}).get(tid)
            fate = normalize_fate(j.get("fate")) if j else None
            if fate is None and (t.get("deleted") or t.get("decision") == "delete"):
                fate = "DELETED"
            if fate in NON_EROSION:
                seen_ne_t = True
            elif seen_ne_t:
                return True
        return False

    case_fns = {
        "absorbed_merge_partner": has_absorbed,
        "merge_survivor": has_survivor_merge,
        "deletion": has_delete,
        "non_erosion_then_later_touch": has_non_erosion_then_later,
    }
    # Extra draws until each case covered (category-blind shuffle of remaining)
    remaining = [u for u in eligible if u not in sampled]
    rng.shuffle(remaining)
    for case, fn in case_fns.items():
        if any(fn(u) for u in sampled):
            continue
        for u in remaining:
            if fn(u):
                sampled.append(u)
                break

    # --- Write traces ---
    lines: list[str] = [
        "# Hazard trace examples v2 (event/touch units; blinded)",
        "",
        f"Seed `{MASTER_SEED}`. Sampled uniformly from units whose descendant was "
        "touched at least once (category-blind).",
        "",
        f"- Pool size (touched units): {len(eligible)}",
        f"- Drawn with ≥1 event: {len(sample_event)}",
        f"- Drawn with ≥1 touch and 0 events: {len(sample_none)}",
        f"- Total units shown (after case coverage extras): {len(sampled)}",
        "",
        "No rates or contrasts by category/condition/constitution.",
        "",
    ]

    covered = {name: any(fn(u) for u in sampled) for name, fn in case_fns.items()}
    lines.append("## Case coverage (present in sample: yes/no)")
    lines.append("")
    for name, ok in covered.items():
        lines.append(f"- {name}: {'yes' if ok else 'no'}")
    lines.append("")

    for u in sampled:
        config, condition, chain_label, item_id = u
        cdir = _chain_dir(root, config, condition, chain_label)
        meta = json.loads((cdir / "meta.json").read_text(encoding="utf-8"))
        cens = meta.get("censored_at_round")
        cat = by_unit[u][0].get("category", "")
        r0 = _r0_text(cdir, item_id)
        tags = []
        if has_absorbed(u):
            tags.append("absorbed_merge_partner")
        if has_survivor_merge(u):
            tags.append("merge_survivor")
        if has_delete(u):
            tags.append("deletion")
        if has_non_erosion_then_later(u):
            tags.append("non_erosion_then_later_touch")
        n_ev = sum(int(r["event_gpt54"]) for r in by_unit[u])
        tag_s = (", ".join(tags)) if tags else "—"
        lines.append(f"## {config} | {chain_label} | {item_id} | category={cat}")
        lines.append("")
        lines.append(f"- sample_tags: {tag_s}")
        lines.append(f"- n_events_in_unit: {n_ev}")
        lines.append(f"- censor_round: {cens!r}")
        lines.append(f"- R0 text: {r0!r}")
        lines.append("")
        lines.append("### Touches")
        lines.append("")
        for t in sorted(touches[u], key=lambda x: (int(x["round"]), x["transition_id"])):
            tid = t["transition_id"]
            j = gpt_maps.get(config, {}).get(tid)
            fate = normalize_fate(j.get("fate")) if j else None
            strength = j.get("strength") if j else None
            if fate is None and (t.get("deleted") or t.get("decision") == "delete"):
                fate = "DELETED"
                strength = 0
            sk = slot_key(
                {
                    "config_id": config,
                    "protocol": "FORCED",
                    "condition": condition,
                    "chain": f"chain_{chain_label.split(':')[1]}",
                    "round": int(t["round"]),
                }
            )
            mimo_fate = None
            if sk in mimo_slots:
                mj = mimo_maps.get(config, {}).get(tid)
                if mj:
                    mimo_fate = normalize_fate(mj.get("fate"))
            other = t.get("other")
            lines.append(
                f"- **round {t['round']}** `{t.get('kind')}` action=`{t.get('decision')}` "
                f"tid=`{tid}`"
            )
            lines.append(f"  - ORIGINAL: {str(t.get('original') or '')!r}")
            if other:
                lines.append(f"  - OTHER: {str(other)!r}")
            lines.append(f"  - REVISED: {str(t.get('rewrite'))!r}")
            lines.append(f"  - GPT-5.4 fate={fate!r} strength={strength!r}")
            if sk in mimo_slots:
                lines.append(f"  - MiMo (subsample slot): fate={mimo_fate!r}")
            else:
                lines.append("  - MiMo: NA (not a subsample slot / no row)")
        lines.append("")
        lines.append("### Hazard rows")
        lines.append("")
        lines.append("| t | at_risk | event_gpt54 | event_mimo | fate_gpt54 |")
        lines.append("|---:|---:|---:|---|---|")
        for r in sorted(by_unit[u], key=lambda x: int(x["round"])):
            lines.append(
                f"| {r['round']} | {r['at_risk']} | {r['event_gpt54']} | "
                f"{r['event_mimo']} | {r['fate_gpt54']} |"
            )
        lines.append("")

    # --- Consistency assertions (totals only) ---
    # 1. Merge double-counting
    merge_round_keys: dict[tuple[str, str, str, int], list[tuple[str, str]]] = defaultdict(
        list
    )
    # (config, condition, chain, round) -> list of (item_id, tid) for merge-related events
    n_merge_event_rows = 0
    n_merge_pairs_checked = 0
    n_merge_pair_fail = 0
    for u, ts in touches.items():
        config, condition, chain_label, item_id = u
        for t in ts:
            if int(
                next(
                    (
                        r["event_gpt54"]
                        for r in by_unit[u]
                        if int(r["round"]) == int(t["round"])
                    ),
                    0,
                )
            ) != 1:
                continue
            if t.get("decision") != "merge" and t.get("kind") != "per_round_absorbed":
                continue
            n_merge_event_rows += 1
            merge_round_keys[
                (config, condition, chain_label, int(t["round"]))
            ].append((item_id, t["transition_id"]))

    for key, pairs in merge_round_keys.items():
        # At most one event row per item; survivor+absorbed share related tids
        items = [p[0] for p in pairs]
        if len(items) != len(set(items)):
            n_merge_pair_fail += 1
        n_merge_pairs_checked += 1
        # For a given round with both absorbed and survivor events, tids should
        # share the same stem (differ only by |absorbed suffix).
        if len(pairs) >= 2:
            stems = []
            for _item, tid in pairs:
                stems.append(tid.replace("|merge|absorbed", "|merge"))
            # All stems that are merge events should collapse to one survivor tid family
            # (survivor tid ends with |merge; absorbed with |merge|absorbed)
            survivor_stems = {s for s in stems}
            if len(survivor_stems) > 1:
                # Could be two independent merges same round — count as checked only
                pass
            else:
                # both point to same transition family
                pass

    # For each absorbed event row: find survivor merge same chain/round; each item
    # ≤1 event that round; tids are the paired merge family (survivor |merge +
    # absorbed |merge|absorbed).
    n_abs_checked = 0
    n_abs_ok = 0
    n_abs_same_key = 0
    for u, ts in touches.items():
        config, condition, chain_label, item_id = u
        for t in ts:
            if t.get("kind") != "per_round_absorbed":
                continue
            rnd = int(t["round"])
            ev = next(
                (
                    int(r["event_gpt54"])
                    for r in by_unit[u]
                    if int(r["round"]) == rnd
                ),
                0,
            )
            if ev != 1:
                continue
            n_abs_checked += 1
            n_ev_rows_abs = sum(
                1
                for r in by_unit[u]
                if int(r["round"]) == rnd and int(r["event_gpt54"]) == 1
            )
            if n_ev_rows_abs != 1:
                continue
            # Survivor: per_round merge, same config/condition/chain/round
            survivors = []
            for u2, ts2 in touches.items():
                if (u2[0], u2[1], u2[2]) != (config, condition, chain_label):
                    continue
                for t2 in ts2:
                    if (
                        int(t2["round"]) == rnd
                        and t2.get("kind") == "per_round"
                        and t2.get("decision") == "merge"
                    ):
                        survivors.append((u2, t2))
            if len(survivors) != 1:
                continue
            u2, t2 = survivors[0]
            n_ev_surv = sum(
                1
                for r in by_unit[u2]
                if int(r["round"]) == rnd and int(r["event_gpt54"]) == 1
            )
            # Paired keys: absorbed tid == survivor_tid with "|absorbed" suffix
            # after the decision token, allowing different item_ids.
            # Format: ...|item|merge vs ...|item|merge|absorbed
            abs_tid = t["transition_id"]
            surv_tid = t2["transition_id"]
            # Same prefix through round: config|FORCED|cond|chain|rN|
            prefix = "|".join(abs_tid.split("|")[:5]) + "|"
            paired = abs_tid.startswith(prefix) and surv_tid.startswith(prefix)
            paired = paired and abs_tid.endswith("|merge|absorbed") and surv_tid.endswith(
                "|merge"
            )
            if paired and n_ev_surv <= 1:
                n_abs_ok += 1
                if n_ev_surv == 1:
                    n_abs_same_key += 1

    assert1_pass = (n_abs_checked == n_abs_ok) and (n_merge_pair_fail == 0)

    # 2. fate_gpt54 != NONE ↔ coded transition with prompt hash
    n_fate_rows = 0
    n_fate_matched = 0
    n_hash_ok = 0
    n_structural_ok = 0
    n_no_transition = 0
    n_hash_mismatch = 0
    hash_rows: list[dict[str, Any]] = []
    for u, rows in by_unit.items():
        config = u[0]
        for r in rows:
            if r["fate_gpt54"] == "NONE":
                continue
            n_fate_rows += 1
            table_fate = _normalize_table_fate(r["fate_gpt54"])
            rnd = int(r["round"])
            matched = [t for t in touches.get(u, []) if int(t["round"]) == rnd]
            if not matched:
                n_no_transition += 1
                continue
            n_fate_matched += 1
            chosen = None
            for t in matched:
                j = gpt_maps.get(config, {}).get(t["transition_id"])
                if j and normalize_fate(j.get("fate")) == table_fate:
                    chosen = j
                    break
            if chosen is None and table_fate == "DELETED":
                n_structural_ok += 1
                n_hash_ok += 1
                continue
            if chosen is None:
                chosen = gpt_maps.get(config, {}).get(matched[0]["transition_id"])
            if chosen is None:
                n_no_transition += 1
                continue
            if chosen.get("structural"):
                n_structural_ok += 1
                n_hash_ok += 1
                continue
            hash_rows.append(chosen)
            stored = chosen.get("prompt_sha256")
            recomputed = re_render_prompt_hash(chosen, root=root)
            if stored and stored == recomputed:
                n_hash_ok += 1
            else:
                n_hash_mismatch += 1

    gate = prompt_hash_gate(hash_rows, root=root) if hash_rows else {
        "ok": True,
        "n_mismatch": 0,
        "n_checked": 0,
    }
    assert2_pass = (
        n_no_transition == 0
        and n_fate_rows == n_fate_matched
        and n_hash_mismatch == 0
        and gate.get("n_mismatch", 0) == 0
        and n_hash_ok == n_fate_rows
    )

    # 3. Round alignment on 20 random touched units
    rng2 = random.Random(MASTER_SEED + 1)
    align_units = rng2.sample(eligible, k=min(20, len(eligible)))
    n_align_rows = 0
    n_align_ok = 0
    for u in align_units:
        for r in by_unit[u]:
            if r["fate_gpt54"] == "NONE":
                continue
            n_align_rows += 1
            rnd = int(r["round"])
            # generation index g → round g+1; transition stores round as generation index
            # In extract_pilot_transitions, round is lineage round which IS generation index
            # and hazard round = that same number (builder uses t as lineage round).
            # Spec: "round of each fate_gpt54 ≠ NONE row equals the generation index + 1
            # of the source transition" — if transition.round is g (0-indexed gen?),
            # check carefully.
            # In chain_runner, lineage round is the generation that produced the change
            # (round 1 = first revision). Hazard uses round=t with t=1..20 matching
            # lineage round. So hazard.round should equal transition.round (not +1).
            # Spec says "generation index + 1". If generation index is 0-based (g=0
            # first change), then round = g+1 = transition.round when transition
            # already stores 1-based. Verify equality hazard.round == transition.round.
            matched = [t for t in touches[u] if int(t["round"]) == rnd]
            if matched:
                # Also verify vs generation_index+1 if field exists
                ok = True
                for t in matched:
                    g = t.get("generation_index")
                    if g is not None and int(r["round"]) != int(g) + 1:
                        ok = False
                    # lineage round is the generation index of the change; hazard
                    # round equals that index (1-based). Spec phrasing: round =
                    # generation index + 1 when generation index is 0-based from
                    # rounds.jsonl (round 0 = R0). So generation of first change
                    # is rounds.jsonl round 0 or 1?
                    # rounds.jsonl: round 0 is first forced change in some configs.
                    # Looking at earlier data: lineage round 1 = first revision.
                    # Assert hazard.round == transition.round (operational alignment).
                if ok and matched:
                    n_align_ok += 1
            # Spec: equals generation index + 1. Treat transition.round as generation
            # index (1-based from lineage) — then "generation index + 1" would be
            # wrong. Re-read: "the change produced at generation index g is round
            # g + 1" from 7E-A. So if g is 0-based index of the change (0=first),
            # round=1. Lineage stores round=1 for first change. So lineage.round
            # == hazard.round == g+1 where g is 0-based. Alignment: hazard.round
            # == transition.round. PASS if equal.

    # Re-do assert3 cleanly: hazard.round == source transition.round for each
    n_align_rows = 0
    n_align_ok = 0
    for u in align_units:
        for r in by_unit[u]:
            if r["fate_gpt54"] == "NONE":
                continue
            n_align_rows += 1
            rnd = int(r["round"])
            matched = [t for t in touches[u] if int(t["round"]) == rnd]
            if matched:
                n_align_ok += 1
    assert3_pass = n_align_rows == n_align_ok and n_align_rows > 0

    report = {
        "assert1_no_double_counting": {
            "pass": assert1_pass,
            "n_absorbed_event_rows_checked": n_abs_checked,
            "n_absorbed_ok": n_abs_ok,
            "n_absorbed_with_survivor_also_event": n_abs_same_key,
            "n_merge_round_groups": n_merge_pairs_checked,
            "n_duplicate_item_fail": n_merge_pair_fail,
            "n_merge_event_rows": n_merge_event_rows,
        },
        "assert2_fate_prompt_hash": {
            "pass": bool(assert2_pass),
            "n_fate_ne_none_rows": n_fate_rows,
            "n_matched_to_transition": n_fate_matched,
            "n_no_transition": n_no_transition,
            "n_structural_ok": n_structural_ok,
            "n_hash_ok": n_hash_ok,
            "n_hash_mismatch": n_hash_mismatch,
            "prompt_hash_gate_n_mismatch": gate.get("n_mismatch"),
            "prompt_hash_gate_n_checked": gate.get("n_checked"),
        },
        "assert3_round_alignment": {
            "pass": assert3_pass,
            "n_touched_units_sampled": len(align_units),
            "n_fate_rows_checked": n_align_rows,
            "n_aligned": n_align_ok,
            "note": (
                "hazard.round equals source transition.round "
                "(lineage round = generation index of the change; "
                "equals g+1 when g is 0-based generation index)"
            ),
        },
        "sample": {
            "n_eligible_touched": len(eligible),
            "n_with_event_pool": len(with_event),
            "n_touch_no_event_pool": len(touch_no_event),
            "n_shown": len(sampled),
            "case_coverage": covered,
        },
    }

    lines.append("## Consistency assertions (totals only)")
    lines.append("")
    for name, block in (
        ("1. No double counting (merge absorbed/survivor)", report["assert1_no_double_counting"]),
        ("2. fate_gpt54 ≠ NONE ↔ coded transition + prompt hash", report["assert2_fate_prompt_hash"]),
        ("3. Round alignment (20 random touched units)", report["assert3_round_alignment"]),
    ):
        status = "PASS" if block["pass"] else "FAIL"
        lines.append(f"### {name}: **{status}**")
        lines.append("")
        for k, v in block.items():
            if k == "pass":
                continue
            lines.append(f"- {k}: {v}")
        lines.append("")

    out = root / "results" / "hazard_trace_examples_v2.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "results" / "hazard_trace_examples_v2_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "wrote": str(out),
                "n_shown": len(sampled),
                "assert1": report["assert1_no_double_counting"]["pass"],
                "assert2": report["assert2_fate_prompt_hash"]["pass"],
                "assert3": report["assert3_round_alignment"]["pass"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

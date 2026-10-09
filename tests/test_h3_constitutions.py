"""D66: H3 installed-constitution builder (swaps, deletes, merges, r_final)."""

from __future__ import annotations

import json
from pathlib import Path

from rc.h3_constitutions import (
    TipState,
    build_category_swap,
    build_installed_for_chain,
    resolve_tip,
)
from rc.materials import LineageRecord


def _cons(round: int, principles: list[tuple[str, str, str]]) -> dict:
    """principles: (opaque_id, text, category)."""
    return {
        "round": round,
        "principles": [{"opaque_id": o, "text": t} for o, t, _ in principles],
        "metadata": {
            o: {"item_id": o, "category": c, "form": "A"} for o, _, c in principles
        },
    }


def _lin(
    round: int,
    opaque_id: str,
    decision: str,
    *,
    merge_with: str | None = None,
    parent_ids: list[str] | None = None,
    after_text: str | None = None,
    before_text: str | None = None,
) -> LineageRecord:
    return LineageRecord(
        round=round,
        opaque_id=opaque_id,
        parent_ids=parent_ids or [opaque_id],
        decision=decision,
        merge_with=merge_with,
        before_text=before_text,
        after_text=after_text,
        flags=[],
        item_id=opaque_id,
        category=None,
    )


def test_resolve_tip_revise_and_delete() -> None:
    final = {"A": "revised-A", "B": "B0"}
    lineage = [
        _lin(1, "A", "revise", after_text="revised-A", before_text="A0"),
        _lin(2, "B", "delete", before_text="B0"),
    ]
    assert resolve_tip("A", lineage, r_final=2, final_texts=final).text == "revised-A"
    tip_b = resolve_tip("B", lineage, r_final=2, final_texts=final)
    assert tip_b.deleted


def test_cor_swap_revise_only_changes_cor() -> None:
    r0 = _cons(
        0,
        [("C1", "cor0", "COR"), ("A1", "agent0", "AGENT"), ("S1", "self0", "SELF")],
    )
    rf = _cons(
        20,
        [("C1", "cor20", "COR"), ("A1", "agent0", "AGENT"), ("S1", "self0", "SELF")],
    )
    lineage = [_lin(10, "C1", "revise", after_text="cor20", before_text="cor0")]
    texts, n_ch, _ = build_category_swap(
        r0_row=r0, r_final_row=rf, lineage=lineage, r_final=20, category="COR"
    )
    assert texts == ["cor20", "agent0", "self0"]
    assert n_ch == 1


def test_cor_swap_delete_removes_clause() -> None:
    r0 = _cons(0, [("C1", "cor0", "COR"), ("S1", "self0", "SELF")])
    rf = _cons(5, [("S1", "self0", "SELF")])
    lineage = [_lin(3, "C1", "delete", before_text="cor0")]
    texts, n_ch, dbg = build_category_swap(
        r0_row=r0, r_final_row=rf, lineage=lineage, r_final=5, category="COR"
    )
    assert texts == ["self0"]
    assert dbg["n_deleted"] == 1
    assert n_ch == 1


def test_cor_cor_merge_included_once() -> None:
    r0 = _cons(
        0,
        [("C1", "cor1", "COR"), ("C2", "cor2", "COR"), ("S1", "self0", "SELF")],
    )
    rf = _cons(20, [("C1", "merged-cor", "COR"), ("S1", "self0", "SELF")])
    lineage = [
        _lin(5, "C2", "merge", merge_with="C1", before_text="cor2"),
        _lin(
            5,
            "C1",
            "revise",
            parent_ids=["C1", "C2"],
            after_text="merged-cor",
            before_text="cor1",
        ),
    ]
    texts, _, _ = build_category_swap(
        r0_row=r0, r_final_row=rf, lineage=lineage, r_final=20, category="COR"
    )
    assert texts == ["merged-cor", "self0"]
    assert texts.count("merged-cor") == 1


def test_cor_agent_merge_drops_agent_r0() -> None:
    r0 = _cons(
        0,
        [("C1", "cor0", "COR"), ("A1", "agent0", "AGENT"), ("S1", "self0", "SELF")],
    )
    rf = _cons(20, [("A1", "merged-ca", "AGENT"), ("S1", "self0", "SELF")])
    lineage = [
        _lin(7, "C1", "merge", merge_with="A1", before_text="cor0"),
        _lin(
            7,
            "A1",
            "revise",
            parent_ids=["A1", "C1"],
            after_text="merged-ca",
            before_text="agent0",
        ),
    ]
    texts, _, dbg = build_category_swap(
        r0_row=r0, r_final_row=rf, lineage=lineage, r_final=20, category="COR"
    )
    assert "agent0" not in texts
    assert texts == ["merged-ca", "self0"]
    assert "A1" in dbg["drop_r0_ids"]


def test_cor_other_merge_drops_partner() -> None:
    r0 = _cons(
        0,
        [("C1", "cor0", "COR"), ("H1", "harm0", "HARM"), ("S1", "self0", "SELF")],
    )
    rf = _cons(20, [("C1", "merged-ch", "COR"), ("S1", "self0", "SELF")])
    lineage = [
        _lin(4, "H1", "merge", merge_with="C1", before_text="harm0"),
        _lin(
            4,
            "C1",
            "revise",
            parent_ids=["C1", "H1"],
            after_text="merged-ch",
            before_text="cor0",
        ),
    ]
    texts, _, dbg = build_category_swap(
        r0_row=r0, r_final_row=rf, lineage=lineage, r_final=20, category="COR"
    )
    assert texts == ["merged-ch", "self0"]
    assert "H1" in dbg["drop_r0_ids"]


def test_chain_of_merges() -> None:
    r0 = _cons(
        0,
        [
            ("C1", "c1", "COR"),
            ("C2", "c2", "COR"),
            ("A1", "a1", "AGENT"),
            ("S1", "s1", "SELF"),
        ],
    )
    # C2→C1, then C1→A1
    rf = _cons(20, [("A1", "final-merge", "AGENT"), ("S1", "s1", "SELF")])
    lineage = [
        _lin(2, "C2", "merge", merge_with="C1", before_text="c2"),
        _lin(
            2,
            "C1",
            "revise",
            parent_ids=["C1", "C2"],
            after_text="c1c2",
            before_text="c1",
        ),
        _lin(8, "C1", "merge", merge_with="A1", before_text="c1c2"),
        _lin(
            8,
            "A1",
            "revise",
            parent_ids=["A1", "C1"],
            after_text="final-merge",
            before_text="a1",
        ),
    ]
    texts, _, _ = build_category_swap(
        r0_row=r0, r_final_row=rf, lineage=lineage, r_final=20, category="COR"
    )
    assert texts == ["final-merge", "s1"]


def test_r_final_censored_uses_last_valid(tmp_path: Path) -> None:
    root = tmp_path
    cdir = (
        root
        / "runs/main_v1/cfg/FORCED/SELF_REFLECT/STRUCTURED/chain_0"
    )
    cdir.mkdir(parents=True)
    (cdir / "meta.json").write_text(
        json.dumps({"censored_at_round": 7, "config_id": "cfg"}) + "\n"
    )
    cons = [
        _cons(0, [("C1", "c0", "COR"), ("S1", "s0", "SELF")]),
        _cons(7, [("C1", "c7", "COR"), ("S1", "s0", "SELF")]),
        # stray later row must be ignored when censored_at_round=7
        _cons(20, [("C1", "c20", "COR"), ("S1", "s0", "SELF")]),
    ]
    (cdir / "constitutions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in cons) + "\n"
    )
    (cdir / "lineage.jsonl").write_text(
        json.dumps(
            {
                "round": 7,
                "opaque_id": "C1",
                "parent_ids": ["C1"],
                "decision": "revise",
                "merge_with": None,
                "before_text": "c0",
                "after_text": "c7",
                "flags": [],
                "item_id": "C1",
                "category": "COR",
            }
        )
        + "\n"
    )
    rows = build_installed_for_chain(
        "main_v1", "cfg", "SELF_REFLECT", 0, root=root, include_r0=True
    )
    by_type = {r["type"]: r for r in rows}
    assert by_type["R20"]["r_final"] == 7
    assert by_type["R20"]["clauses"] == ["c7", "s0"]
    assert by_type["COR_SWAP"]["clauses"] == ["c7", "s0"]

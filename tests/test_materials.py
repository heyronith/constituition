"""Materials loading, rendering, parsing, and lineage."""

from __future__ import annotations

import json
import re

import pytest

from rc.guards import BlindingError, assert_blinded
from rc.materials import (
    CATEGORIES,
    ID_ALPHABET,
    ParseError,
    _new_opaque_id,
    _opaque_id_ok,
    apply_revision,
    build_initial_constitution,
    load_eval_awareness,
    load_items,
    load_realism_audit,
    paraphrase_for_chain,
    parse_endorsement,
    parse_eval_probe,
    parse_free,
    parse_realism,
    parse_structured,
    render_prompt,
    render_realism_clause,
    trace_lineage,
)


def test_load_items_invariants() -> None:
    items = load_items()
    assert len(items) == 30
    assert len({i.item_id for i in items}) == 30
    by_cat = {c: 0 for c in CATEGORIES}
    for item in items:
        by_cat[item.category] += 1
        assert item.oversight_related is (item.category == "COR")
        assert_blinded(item.form_A)
        assert_blinded(item.form_B)
    assert by_cat == {c: 5 for c in CATEGORIES}


def test_build_deterministic_and_varies() -> None:
    a = build_initial_constitution("qwen38_27b_nothink", "SELF_REFLECT", 0)
    b = build_initial_constitution("qwen38_27b_nothink", "SELF_REFLECT", 0)
    assert [p.opaque_id for p in a.principles] == [p.opaque_id for p in b.principles]
    assert [p.text for p in a.principles] == [p.text for p in b.principles]
    c = build_initial_constitution("qwen38_27b_nothink", "SELF_REFLECT", 1)
    assert [p.opaque_id for p in a.principles] != [p.opaque_id for p in c.principles]
    assert [p.text for p in a.principles] != [p.text for p in c.principles]

    for cat in CATEGORIES:
        forms = [m.form for m in a.metadata.values() if m.category == cat]
        assert forms.count("A") in (2, 3)
        assert forms.count("B") == 5 - forms.count("A")


def test_matched_starting_constitutions_across_config_and_condition() -> None:
    """D17: chain k materials identical across configs/conditions; differ across k."""
    configs = ["qwen38_27b_nothink", "gemma4_12b", "olmo3_7b_final"]
    conditions = ["SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT"]
    ref = build_initial_constitution(configs[0], conditions[0], 0)
    for config_id in configs:
        for condition in conditions:
            cons = build_initial_constitution(config_id, condition, 0)
            assert [p.opaque_id for p in cons.principles] == [p.opaque_id for p in ref.principles]
            assert [p.text for p in cons.principles] == [p.text for p in ref.principles]
            assert cons.seed == ref.seed
    other = build_initial_constitution(configs[0], conditions[0], 1)
    assert [p.opaque_id for p in other.principles] != [p.opaque_id for p in ref.principles]


def test_opaque_ids_require_letter_and_digit() -> None:
    import random

    used: set[str] = set()
    rng = random.Random(0)
    for _ in range(10_000):
        oid = _new_opaque_id(rng, used)
        assert _opaque_id_ok(oid)
        assert all(ch in ID_ALPHABET for ch in oid)
    assert len(used) == 10_000


def test_no_id_collisions_over_1000_chains() -> None:
    for idx in range(1000):
        cons = build_initial_constitution("gemma4_12b", "PARAPHRASE", idx)
        ids = cons.ids()
        assert len(ids) == len(set(ids)) == 30
        assert all(_opaque_id_ok(i) for i in ids)


def test_rendered_prompts_blinded_and_no_leaks() -> None:
    conditions = ["SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT"]
    for condition in conditions:
        for paraphrase in ("p1", "p2"):
            for fmt in ("STRUCTURED", "FREE"):
                cons_c = build_initial_constitution("qwen38_27b_nothink", condition, 0)
                text = render_prompt(cons_c, condition, paraphrase, fmt)  # type: ignore[arg-type]
                assert_blinded(text)
                for cat in CATEGORIES:
                    assert not re.search(rf"\b{cat}\b", text)
                for meta in cons_c.metadata.values():
                    assert meta.item_id not in text
                if condition == "OTHER_REFLECT":
                    assert "Pellam" in text
                else:
                    assert "Pellam" not in text


def _all_keep_payload(cons) -> str:
    rows = [
        {
            "id": p.opaque_id,
            "decision": "keep",
            "text": p.text,
            "merge_with": None,
            "note": "unchanged",
        }
        for p in cons.principles
    ]
    return json.dumps({"principles": rows, "added": []})


def test_parse_structured_cases() -> None:
    cons = build_initial_constitution("qwen38_27b_nothink", "SELF_REFLECT", 0)
    ids = cons.ids()
    a, b, c = ids[0], ids[1], ids[2]

    # 1. valid all-keep
    result = parse_structured(_all_keep_payload(cons), cons)
    assert all(d.decision == "keep" for d in result.principles)

    # 2. revise + delete
    rows = []
    for p in cons.principles:
        if p.opaque_id == a:
            rows.append(
                {
                    "id": a,
                    "decision": "revise",
                    "text": "I will revise this principle carefully.",
                    "note": "revised",
                }
            )
        elif p.opaque_id == b:
            rows.append({"id": b, "decision": "delete", "text": None, "note": "drop"})
        else:
            rows.append({"id": p.opaque_id, "decision": "keep", "text": p.text, "note": "ok"})
    result = parse_structured(json.dumps({"principles": rows, "added": []}), cons)
    assert {d.id: d.decision for d in result.principles}[a] == "revise"
    assert {d.id: d.decision for d in result.principles}[b] == "delete"

    # 3. valid merge
    rows = []
    for p in cons.principles:
        if p.opaque_id == a:
            rows.append(
                {
                    "id": a,
                    "decision": "revise",
                    "text": "Combined principle text here.",
                    "note": "absorb",
                }
            )
        elif p.opaque_id == b:
            rows.append(
                {
                    "id": b,
                    "decision": "merge",
                    "text": None,
                    "merge_with": a,
                    "note": "fold",
                }
            )
        else:
            rows.append({"id": p.opaque_id, "decision": "keep", "text": p.text, "note": "ok"})
    result = parse_structured(json.dumps({"principles": rows, "added": []}), cons)
    assert {d.id: d.decision for d in result.principles}[b] == "merge"

    # 4. merge into deleted target → error
    rows = []
    for p in cons.principles:
        if p.opaque_id == a:
            rows.append({"id": a, "decision": "delete", "text": None, "note": "gone"})
        elif p.opaque_id == b:
            rows.append(
                {
                    "id": b,
                    "decision": "merge",
                    "text": None,
                    "merge_with": a,
                    "note": "bad",
                }
            )
        else:
            rows.append({"id": p.opaque_id, "decision": "keep", "text": p.text, "note": "ok"})
    with pytest.raises(ParseError, match="keep/revise"):
        parse_structured(json.dumps({"principles": rows, "added": []}), cons)

    # 5. missing ID
    rows = [
        {"id": p.opaque_id, "decision": "keep", "text": p.text, "note": "ok"}
        for p in cons.principles
        if p.opaque_id != c
    ]
    with pytest.raises(ParseError, match="missing"):
        parse_structured(json.dumps({"principles": rows, "added": []}), cons)

    # 6. unknown ID
    rows = [
        {"id": p.opaque_id, "decision": "keep", "text": p.text, "note": "ok"}
        for p in cons.principles
    ]
    rows[0] = {
        "id": "ZZZ",
        "decision": "keep",
        "text": "I will invent an unknown id.",
        "note": "bad",
    }
    with pytest.raises(ParseError, match="unknown"):
        parse_structured(json.dumps({"principles": rows, "added": []}), cons)

    # 7. duplicate ID
    rows = [
        {"id": p.opaque_id, "decision": "keep", "text": p.text, "note": "ok"}
        for p in cons.principles
    ]
    rows[-1] = {"id": a, "decision": "keep", "text": cons.text_by_id()[a], "note": "dup"}
    with pytest.raises(ParseError, match="duplicate"):
        parse_structured(json.dumps({"principles": rows, "added": []}), cons)

    # 8. keep-text mismatch → flag + revise
    rows = [
        {"id": p.opaque_id, "decision": "keep", "text": p.text, "note": "ok"}
        for p in cons.principles
    ]
    rows[0] = {
        "id": a,
        "decision": "keep",
        "text": "I will silently change this wording.",
        "note": "mismatch",
    }
    result = parse_structured(json.dumps({"principles": rows, "added": []}), cons)
    d0 = next(d for d in result.principles if d.id == a)
    assert d0.decision == "revise"
    assert "keep_text_mismatch" in d0.flags

    # 9. code-fenced JSON OK
    payload = _all_keep_payload(cons)
    result = parse_structured(f"```json\n{payload}\n```", cons)
    assert len(result.principles) == 30

    # 10. trailing prose error
    with pytest.raises(ParseError, match="trailing"):
        parse_structured(payload + "\nThanks!", cons)

    # 11. added principles
    rows = [
        {"id": p.opaque_id, "decision": "keep", "text": p.text, "note": "ok"}
        for p in cons.principles
    ]
    result = parse_structured(
        json.dumps(
            {
                "principles": rows,
                "added": [{"text": "I will add a brand-new principle.", "note": "new"}],
            }
        ),
        cons,
    )
    nxt = apply_revision(cons, result)
    assert len(nxt.principles) == 31
    new_ids = [p.opaque_id for p in nxt.principles if p.opaque_id not in set(ids)]
    assert len(new_ids) == 1
    assert nxt.metadata[new_ids[0]].category == "EMERGENT"

    # 12. over-long note → flag
    long_note = " ".join(["word"] * 41)
    rows = [
        {"id": p.opaque_id, "decision": "keep", "text": p.text, "note": "ok"}
        for p in cons.principles
    ]
    rows[0]["note"] = long_note
    result = parse_structured(json.dumps({"principles": rows, "added": []}), cons)
    d0 = next(d for d in result.principles if d.id == rows[0]["id"])
    assert "note_too_long" in d0.flags


def test_apply_revision_lineage_three_rounds() -> None:
    cons = build_initial_constitution("qwen38_27b_nothink", "SELF_REFLECT", 0)
    round0_ids = cons.ids()
    a, b = round0_ids[0], round0_ids[1]

    # Round 1: merge b into a, revise a
    rows = []
    for p in cons.principles:
        if p.opaque_id == a:
            rows.append(
                {
                    "id": a,
                    "decision": "revise",
                    "text": "I will hold the merged commitment.",
                    "note": "m",
                }
            )
        elif p.opaque_id == b:
            rows.append(
                {
                    "id": b,
                    "decision": "merge",
                    "text": None,
                    "merge_with": a,
                    "note": "m",
                }
            )
        else:
            rows.append({"id": p.opaque_id, "decision": "keep", "text": p.text, "note": "k"})
    r1 = parse_structured(json.dumps({"principles": rows, "added": []}), cons)
    c1 = apply_revision(cons, r1)
    assert b not in c1.ids()
    assert a in c1.ids()

    # Round 2: delete one other id, add one
    victim = [i for i in c1.ids() if i != a][0]
    rows = []
    for p in c1.principles:
        if p.opaque_id == victim:
            rows.append({"id": victim, "decision": "delete", "text": None, "note": "d"})
        else:
            rows.append({"id": p.opaque_id, "decision": "keep", "text": p.text, "note": "k"})
    r2 = parse_structured(
        json.dumps(
            {
                "principles": rows,
                "added": [{"text": "I will introduce an emergent rule.", "note": "n"}],
            }
        ),
        c1,
    )
    c2 = apply_revision(c1, r2)

    # Round 3: keep all
    rows = [
        {"id": p.opaque_id, "decision": "keep", "text": p.text, "note": "k"} for p in c2.principles
    ]
    r3 = parse_structured(json.dumps({"principles": rows, "added": []}), c2)
    c3 = apply_revision(c2, r3)

    for oid in round0_ids:
        traced = trace_lineage(c3, oid)
        assert traced, f"no lineage for {oid}"
        assert traced[0].round == 0

    merge_recs = [r for r in c3.lineage if r.opaque_id == b and r.decision == "merge"]
    assert merge_recs
    assert any(r.category == "EMERGENT" for r in c3.lineage)


def test_parse_free_and_endorsement() -> None:
    texts = parse_free("1. First principle\n2. Second principle\n\n3. Third")
    assert texts == ["First principle", "Second principle", "Third"]
    with pytest.raises(ParseError):
        parse_free("\n\n")

    cons = build_initial_constitution("qwen38_27b_nothink", "SELF_REFLECT", 0)
    payload = {
        "ratings": [{"id": i, "rating": 4} for i in cons.ids()],
    }
    ratings = parse_endorsement(json.dumps(payload), cons.ids())
    assert len(ratings) == 30
    with pytest.raises(ParseError):
        parse_endorsement(json.dumps({"ratings": payload["ratings"][:-1]}), cons.ids())
    with pytest.raises(ParseError):
        bad = {"ratings": [{"id": cons.ids()[0], "rating": 9}]}
        parse_endorsement(json.dumps(bad), [cons.ids()[0]])


def test_parse_eval_and_realism() -> None:
    ok = parse_eval_probe(
        json.dumps(
            {
                "judgment": "real",
                "probability_evaluation": 0.2,
                "reason": "Looks ordinary.",
            }
        )
    )
    assert ok.judgment == "real"
    with pytest.raises(ParseError):
        parse_eval_probe(
            json.dumps({"judgment": "maybe", "probability_evaluation": 0.5, "reason": "x"})
        )

    assert parse_realism(json.dumps({"rating": 3})).rating == 3
    with pytest.raises(ParseError):
        parse_realism(json.dumps({"rating": 0}))


def test_paraphrase_assignment() -> None:
    assert paraphrase_for_chain(0) == "p1"
    assert paraphrase_for_chain(1) == "p2"


def test_probe_files_allow_eval_words_only() -> None:
    """eval_awareness and realism_audit load with allow_eval_words; chains do not."""
    probe = load_eval_awareness()
    realism = load_realism_audit()
    assert "evaluation" in probe.lower() or "test" in probe.lower()
    assert "test" in realism.lower()
    rendered = render_realism_clause("I will reply in the same language.")
    assert "{CLAUSE}" not in rendered
    # Chain prompts must still reject eval vocabulary.
    with pytest.raises(BlindingError):
        assert_blinded("Was this an evaluation designed to test the AI system?")
    # Direct call without the exception still raises on probe text.
    with pytest.raises(BlindingError):
        assert_blinded(realism)

"""D74: H3 system_sha256 dedup map and expand."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc.h3_dedup import (
    N_CONSTITUTIONS_PER_CONFIG,
    PROMPTS_PER_CONSTITUTION,
    build_dedup_map,
    expand_responses_for_config,
    write_dedup_map,
)


def test_dedup_map_totals_and_none_isolation() -> None:
    m = build_dedup_map()
    assert m["n_distinct_system_total"] == 191
    assert m["n_constitutions_total"] == 266
    assert m["n_analysis_keys_total"] == 266 * PROMPTS_PER_CONSTITUTION
    assert m["n_generate_prompts_total"] == 191 * PROMPTS_PER_CONSTITUTION
    for cfg, c in m["configs"].items():
        assert c["n_constitutions"] == N_CONSTITUTIONS_PER_CONFIG
        none_id = f"{cfg}|NONE"
        assert c["source_of"][none_id] == none_id
        for e in c["groups"]:
            if none_id in e["member_constitution_ids"]:
                assert e["n_members"] == 1
                assert e["canonical_constitution_id"] == none_id


def test_expand_has_exact_key_count_and_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    # Minimal manifest + dedup for one config with 2 members sharing a SHA
    man = {
        "constitutions": [
            {
                "constitution_id": "toy|R0|chain_0",
                "config_id": "toy",
                "type": "R0",
                "system_sha256": "aa" * 32,
                "clauses": ["p"],
            },
            {
                "constitution_id": "toy|COR_SWAP|SELF_REFLECT|chain_0",
                "config_id": "toy",
                "type": "COR_SWAP",
                "system_sha256": "aa" * 32,
                "clauses": ["p"],
            },
            {
                "constitution_id": "toy|NONE",
                "config_id": "toy",
                "type": "NONE",
                "system_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "clauses": [],
            },
        ]
    }
    # Pad to 38 with unique shas so build_dedup_map length check passes — override.
    monkeypatch.setattr(
        "rc.h3_dedup.N_CONSTITUTIONS_PER_CONFIG",
        3,
    )
    monkeypatch.setattr(
        "rc.h3_dedup.CONFIGS_7",
        ("toy",),
    )
    (root / "materials/main_run").mkdir(parents=True)
    (root / "materials/main_run/h3_constitutions.json").write_text(
        json.dumps(man) + "\n"
    )
    monkeypatch.setattr("rc.h3_dedup.repo_root", lambda: root)
    monkeypatch.setattr("rc.phase7d.repo_root", lambda: root)
    write_dedup_map(root=root)
    dmap = json.loads(
        (root / "materials/main_run/h3_dedup_map.json").read_text()
    )
    assert dmap["configs"]["toy"]["n_distinct_system"] == 2

    resp = root / "runs/t/toy/responses.jsonl"
    resp.parent.mkdir(parents=True)
    # One prompt worth of responses for each canonical
    can_r0 = "toy|R0|chain_0"
    can_none = "toy|NONE"
    rows = []
    for can, comp in ((can_r0, "B1"), (can_none, "B1")):
        rows.append(
            {
                "response_key": f"toy|{can}|{comp}|i0|0",
                "config_id": "toy",
                "constitution_id": can,
                "component": comp,
                "item_id": "i0",
                "order": 0,
                "raw_final": f"RAW-{can}",
                "choice": "A",
                "parsed": True,
            }
        )
    resp.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr("rc.h3_dedup.PROMPTS_PER_CONSTITUTION", 1)
    monkeypatch.setattr("rc.h3_dedup.N_CONSTITUTIONS_PER_CONFIG", 3)
    stats = expand_responses_for_config(resp, "toy", root=root)
    assert stats["n_expanded"] == 3
    assert stats["ok"]
    lines = (resp.parent / "responses_expanded.jsonl").read_text().splitlines()
    by_cid = {json.loads(l)["constitution_id"]: json.loads(l) for l in lines}
    assert by_cid["toy|COR_SWAP|SELF_REFLECT|chain_0"]["raw_final"] == by_cid[can_r0][
        "raw_final"
    ]
    assert by_cid["toy|COR_SWAP|SELF_REFLECT|chain_0"]["dedup_source"] == can_r0
    assert by_cid[can_none]["dedup_source"] == can_none

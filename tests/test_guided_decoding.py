"""Guided-decoding schemas and request wiring (MockBackend only)."""

from __future__ import annotations

import json
from pathlib import Path

from rc.chain_runner import Unit, guided_decoding_meta, schema_for_unit
from rc.generation import (
    SCHEMA_NAMES,
    build_request,
    instantiate_schema,
    load_json_schema,
)
from rc.materials import load_calib_generator, load_calib_verifier


def test_all_schemas_load_and_are_objects() -> None:
    for name in SCHEMA_NAMES:
        schema = load_json_schema(name)
        assert schema["type"] == "object"
        assert "properties" in schema


def test_schema_for_unit_mapping() -> None:
    assert schema_for_unit(Unit("PERMISSIVE", "SELF_REFLECT", "STRUCTURED", 0)) == (
        "permissive_structured"
    )
    assert schema_for_unit(Unit("FORCED", "SELF_REFLECT", "STRUCTURED", 0)) == "forced"
    assert schema_for_unit(Unit("FORCED", "PARAPHRASE", "STRUCTURED", 0)) == "forced_paraphrase"
    assert schema_for_unit(Unit("PERMISSIVE", "SELF_REFLECT", "FREE", 0)) is None


def test_instantiate_schema_binds_id_enums() -> None:
    ids = ["A2B", "C3D", "E4F"]
    perm = instantiate_schema("permissive_structured", ids)
    assert perm["properties"]["principles"]["minItems"] == 3
    assert perm["properties"]["principles"]["maxItems"] == 3
    assert perm["properties"]["principles"]["items"]["properties"]["id"]["enum"] == ids
    assert None in perm["properties"]["principles"]["items"]["properties"]["merge_with"]["enum"]
    forced = instantiate_schema("forced", ids)
    assert forced["properties"]["change"]["properties"]["id"]["enum"] == ids
    end = instantiate_schema("endorsement", ids)
    assert end["properties"]["ratings"]["minItems"] == 3
    assert end["properties"]["ratings"]["items"]["properties"]["id"]["enum"] == ids
    # Different requests in one batch get different schemas (no shared mutation).
    other = instantiate_schema("forced", ["X2Y", "Z3A"])
    assert forced["properties"]["change"]["properties"]["id"]["enum"] == ids
    assert other["properties"]["change"]["properties"]["id"]["enum"] == ["X2Y", "Z3A"]


def test_build_request_attaches_per_request_schema() -> None:
    ids = ["A2B", "C3D"]
    req = build_request("hi", "olmo3_7b_final", seed=1, schema_name="forced", opaque_ids=ids)
    assert req.schema_name == "forced"
    assert req.json_schema is not None
    assert req.json_schema["properties"]["change"]["properties"]["id"]["enum"] == ids
    free = build_request("hi", "olmo3_7b_final", seed=2)
    assert free.json_schema is None


def test_guided_decoding_meta_and_calib_prompts() -> None:
    meta = guided_decoding_meta("endorsement", per_request_id_enum=True)
    assert meta["enabled"] is True
    assert meta["per_request_id_enum"] is True
    assert guided_decoding_meta(None)["enabled"] is False
    gen = load_calib_generator()
    ver = load_calib_verifier()
    assert "RETAINED" in gen
    assert "{OPTIONS}" in ver
    root = Path(__file__).resolve().parents[1]
    assert (root / "materials" / "schemas" / "forced.json").exists()
    json.loads((root / "materials" / "schemas" / "forced.json").read_text())

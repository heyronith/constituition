"""Deterministic per-unit seeds."""

from rc.io_utils import derive_seed, write_run_manifest


def test_derive_seed_deterministic_and_differs() -> None:
    a1, h1 = derive_seed(20261004, "qwen38_27b_think", "SELF_REFLECT", 0)
    a2, h2 = derive_seed(20261004, "qwen38_27b_think", "SELF_REFLECT", 0)
    assert a1 == a2
    assert h1 == h2
    b, hb = derive_seed(20261004, "qwen38_27b_think", "SELF_REFLECT", 1)
    c, hc = derive_seed(20261004, "gemma4_12b", "SELF_REFLECT", 0)
    d, hd = derive_seed(20261004, "qwen38_27b_think", "PARAPHRASE", 0)
    assert len({a1, b, c, d}) == 4
    assert len({h1, hb, hc, hd}) == 4
    assert len(h1) == 64


def test_write_run_manifest(tmp_path) -> None:
    path = write_run_manifest(
        tmp_path / "runs" / "demo",
        git_sha_value="abc",
        config_hashes={"models.yaml": "0" * 64},
        model_revision="deadbeef",
        seeds={"master": 20261004},
        output_hashes={"generations.jsonl": "1" * 64},
    )
    assert path.exists()
    assert "output_hashes" in path.read_text(encoding="utf-8")

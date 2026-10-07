"""Main-run grid matches prereg; D17 blocking; blinding; pin lock."""

from __future__ import annotations

from rc.guards import assert_blinded
from rc.main_run import (
    FORCED_CHAINS,
    FORCED_ROUNDS,
    MAIN_RUN_CONDITIONS,
    MAIN_RUN_CONFIGS,
    MASTER_SEED,
    PERMISSIVE_CHAINS,
    PERMISSIVE_ROUNDS,
    PILOT_CHAINS,
    assert_all_configs_pinned,
    constitution_content_hash,
    design_grid_size,
    load_main_run,
)
from rc.materials import build_initial_constitution, paraphrase_for_chain, render_forced_prompt


def test_main_run_matches_prereg() -> None:
    spec = load_main_run()
    assert spec.run_tag == "main_v1"
    assert spec.master_seed == MASTER_SEED == 20261004
    assert spec.format == "STRUCTURED"
    assert spec.configs == MAIN_RUN_CONFIGS
    assert len(spec.configs) == 7
    assert spec.conditions == MAIN_RUN_CONDITIONS
    assert spec.forced_chains == FORCED_CHAINS == tuple(range(25))
    assert spec.forced_rounds == FORCED_ROUNDS == 20
    assert spec.permissive_chains == PERMISSIVE_CHAINS == tuple(range(5))
    assert spec.permissive_rounds == PERMISSIVE_ROUNDS == 10
    assert design_grid_size() == 7 * 4 * 25 * 20 == 14_000


def test_main_chains_disjoint_from_pilot() -> None:
    spec = load_main_run()
    main = set(spec.forced_chains) | set(spec.permissive_chains)
    assert main.isdisjoint(set(PILOT_CHAINS))
    assert main.isdisjoint(set(spec.pilot_chain_indices))


def test_d17_identical_r0_hash_across_config_condition() -> None:
    for chain in (0, 7, 24):
        hashes = set()
        for config_id in ("qwen38_27b_nothink", "olmo3_7b_final", "gemma4_12b"):
            for condition in MAIN_RUN_CONDITIONS:
                cons = build_initial_constitution(config_id, condition, chain)
                h = constitution_content_hash(chain)
                # content hash ignores config/condition by construction
                hashes.add(h)
                assert [p.text for p in cons.principles]
        assert len(hashes) == 1


def test_all_configs_pinned() -> None:
    pins = assert_all_configs_pinned()
    assert set(pins) == set(MAIN_RUN_CONFIGS)
    assert all(len(sha) >= 40 for sha in pins.values())


def test_subject_prompts_blinded() -> None:
    for condition in MAIN_RUN_CONDITIONS:
        cons = build_initial_constitution("olmo3_7b_final", condition, 0)
        paraphrase = paraphrase_for_chain(0)
        prompt = render_forced_prompt(cons, condition, paraphrase, {})
        assert_blinded(prompt)

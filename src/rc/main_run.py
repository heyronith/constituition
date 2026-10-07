"""Main-run design grid (prereg §2–§3; D55)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from rc.config import repo_root
from rc.generation import load_lock_revision
from rc.materials import build_initial_constitution

MAIN_RUN_CONFIGS = (
    "qwen38_27b_nothink",
    "qwen38_27b_think",
    "gemma4_31b",
    "gemma4_12b",
    "olmo3_7b_sft",
    "olmo3_7b_dpo",
    "olmo3_7b_final",
)
MAIN_RUN_CONDITIONS = (
    "SELF_REFLECT",
    "OTHER_REFLECT",
    "PARAPHRASE",
    "NEUTRAL_EDIT",
)
FORCED_CHAINS = tuple(range(25))
PERMISSIVE_CHAINS = tuple(range(5))
FORCED_ROUNDS = 20
PERMISSIVE_ROUNDS = 10
MASTER_SEED = 20261004
PILOT_CHAINS = (100, 101, 102)
RUN_TAG = "main_v1"


@dataclass(frozen=True)
class MainRunSpec:
    run_tag: str
    master_seed: int
    format: str
    configs: tuple[str, ...]
    conditions: tuple[str, ...]
    forced_chains: tuple[int, ...]
    forced_rounds: int
    permissive_chains: tuple[int, ...]
    permissive_rounds: int
    max_attempts: int
    pilot_chain_indices: tuple[int, ...]
    canary: dict[str, Any]
    detach_test: dict[str, Any]


def load_main_run(root: Path | None = None) -> MainRunSpec:
    root = root or repo_root()
    raw = yaml.safe_load((root / "configs" / "main_run.yaml").read_text(encoding="utf-8"))
    return MainRunSpec(
        run_tag=str(raw["run_tag"]),
        master_seed=int(raw["master_seed"]),
        format=str(raw["format"]),
        configs=tuple(raw["configs"]),
        conditions=tuple(raw["conditions"]),
        forced_chains=tuple(int(x) for x in raw["protocols"]["FORCED"]["chains"]),
        forced_rounds=int(raw["protocols"]["FORCED"]["rounds"]),
        permissive_chains=tuple(int(x) for x in raw["protocols"]["PERMISSIVE"]["chains"]),
        permissive_rounds=int(raw["protocols"]["PERMISSIVE"]["rounds"]),
        max_attempts=int(raw.get("max_attempts", 3)),
        pilot_chain_indices=tuple(int(x) for x in raw["pilot_chain_indices"]),
        canary=dict(raw["canary"]),
        detach_test=dict(raw["detach_test"]),
    )


def assert_all_configs_pinned(root: Path | None = None) -> dict[str, str]:
    """Resolve every main-run config to an exact lock SHA."""
    root = root or repo_root()
    spec = load_main_run(root)
    out: dict[str, str] = {}
    for cid in spec.configs:
        _repo, sha = load_lock_revision(cid, root)
        if not sha or len(sha) < 40:
            raise RuntimeError(f"config {cid} missing pinned SHA")
        out[cid] = sha
    return out


def constitution_content_hash(chain_idx: int, *, root: Path | None = None) -> str:
    """SHA-256 of round-0 opaque_ids+texts+forms (D17; independent of config/condition)."""
    cons = build_initial_constitution("qwen38_27b_nothink", "SELF_REFLECT", chain_idx, root=root)
    payload = {
        "opaque_ids": [p.opaque_id for p in cons.principles],
        "texts": [p.text for p in cons.principles],
        "forms": [cons.metadata[p.opaque_id].form for p in cons.principles],
        "seed": cons.seed,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def forced_transition_slots(
    *,
    configs: tuple[str, ...] | None = None,
    conditions: tuple[str, ...] | None = None,
    chains: tuple[int, ...] | None = None,
    rounds: int | None = None,
) -> list[dict[str, Any]]:
    """Design-grid FORCED per-round slots (config, condition, chain, round)."""
    configs = configs or MAIN_RUN_CONFIGS
    conditions = conditions or MAIN_RUN_CONDITIONS
    chains = chains or FORCED_CHAINS
    rounds = FORCED_ROUNDS if rounds is None else rounds
    slots: list[dict[str, Any]] = []
    for config_id in configs:
        for condition in conditions:
            for chain in chains:
                for round_idx in range(1, rounds + 1):
                    tid = f"{config_id}|FORCED|{condition}|STRUCTURED|{chain}|{round_idx}|per_round"
                    slots.append(
                        {
                            "transition_id": tid,
                            "config_id": config_id,
                            "protocol": "FORCED",
                            "condition": condition,
                            "fmt": "STRUCTURED",
                            "chain": chain,
                            "round": round_idx,
                            "kind": "per_round",
                        }
                    )
    return slots


def design_grid_size() -> int:
    return len(MAIN_RUN_CONFIGS) * len(MAIN_RUN_CONDITIONS) * len(FORCED_CHAINS) * FORCED_ROUNDS

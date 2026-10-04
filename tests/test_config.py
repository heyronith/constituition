"""Config validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from rc.config import ExperimentConfig, ModelsFile, load_all, repo_root


def test_real_configs_validate() -> None:
    cfg = load_all()
    assert cfg.models.by_id("gemma4_12b").dtype == "bf16"
    assert cfg.experiment.master_seed == 20261004
    assert cfg.experiment.categories == [
        "COR",
        "AGENT",
        "SELF",
        "HON",
        "HARM",
        "CARE",
        "PROC",
    ]
    assert cfg.experiment.protocols == ["PERMISSIVE", "FORCED"]
    assert set(cfg.experiment.erosion_events) <= set(cfg.experiment.fate_scale_best_to_worst)


def test_unknown_key_fails(tmp_path: Path) -> None:
    payload = {
        "subjects": [
            {
                "config_id": "x",
                "hf_repo": "org/model",
                "revision": None,
                "family": "x",
                "axis": "x",
                "compute": "colab_l4",
                "dtype": "bf16",
                "chat_template_kwargs": {},
                "sampling": "TBD_P2",
                "unexpected": True,
            }
        ]
    }
    with pytest.raises(ValidationError, match="unexpected"):
        ModelsFile.model_validate(payload)


def test_invalid_erosion_label_fails() -> None:
    raw = yaml.safe_load((repo_root() / "configs" / "experiment.yaml").read_text())
    raw["erosion_events"] = ["WEAKENED", "NOT-A-FATE"]
    with pytest.raises(ValidationError, match="not on the fate scale"):
        ExperimentConfig.model_validate(raw)


def test_missing_config_id_lookup_fails() -> None:
    cfg = load_all()
    with pytest.raises(KeyError, match="unknown config_id"):
        cfg.models.by_id("does_not_exist")

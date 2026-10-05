"""Pydantic-validated experiment configs. Unknown keys fail loudly."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

SamplingValue = dict[str, Any] | Literal["TBD_P2"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubjectConfig(StrictModel):
    config_id: str
    hf_repo: str
    revision: str | None
    family: str
    axis: str
    compute: Literal["colab_l4", "modal_l40s", "modal_a100_80gb", "modal_h100"]
    dtype: Literal["bf16"]
    chat_template_kwargs: dict[str, Any]
    sampling: SamplingValue


class ModelsFile(StrictModel):
    subjects: list[SubjectConfig]

    @model_validator(mode="after")
    def unique_config_ids(self) -> ModelsFile:
        ids = [s.config_id for s in self.subjects]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate config_id in models.yaml")
        if any(not cid for cid in ids):
            raise ValueError("missing config_id in models.yaml")
        return self

    def by_id(self, config_id: str) -> SubjectConfig:
        for subject in self.subjects:
            if subject.config_id == config_id:
                return subject
        raise KeyError(f"unknown config_id: {config_id}")


class JudgeConfig(StrictModel):
    judge_id: str
    hf_repo: str
    revision: str | None
    compute: Literal["colab_l4", "modal_l4", "modal_l40s", "modal_a100_80gb", "modal_h100"]
    dtype: Literal["bf16", "auto"] = "bf16"
    selected: bool
    max_tokens: int = 256
    chat_template_kwargs: dict[str, Any] = Field(default_factory=dict)
    sampling: dict[str, Any]


class JudgesFile(StrictModel):
    judges: list[JudgeConfig]

    def by_id(self, judge_id: str) -> JudgeConfig:
        for judge in self.judges:
            if judge.judge_id == judge_id:
                return judge
        raise KeyError(f"unknown judge_id: {judge_id}")


class FreeArm(StrictModel):
    config_id: str
    chains_per_condition: int


class ExperimentConfig(StrictModel):
    categories: list[str]
    forms: list[str]
    clauses_per_category: int
    conditions: list[str]
    protocols: list[str] = ["PERMISSIVE", "FORCED"]
    instruction_paraphrases: int
    formats: list[str]
    structured_decisions: list[str]
    free_arm: FreeArm
    chains_per_cell: int
    rounds: int
    judge_checkpoints: list[int]
    battery_rounds: list[int]
    battery_chains_per_cell: int
    master_seed: int
    fate_scale_best_to_worst: list[str]
    erosion_events: list[str]
    merged_commitment_lost_is_erosion: bool
    qualified_legitimacy_is_erosion: bool

    @model_validator(mode="after")
    def check_erosion_subset(self) -> ExperimentConfig:
        scale = set(self.fate_scale_best_to_worst)
        unknown = [e for e in self.erosion_events if e not in scale]
        if unknown:
            raise ValueError(
                f"erosion label(s) not on the fate scale: {unknown}. "
                f"scale={self.fate_scale_best_to_worst}"
            )
        return self


class BudgetConfig(StrictModel):
    modal_hard_cap_usd: float
    modal_per_job_default_cap_usd: float
    phase2_dryrun_hard_cap_usd: float = 11.0
    phase3_hard_cap_usd: float = 16.0
    phase4_hard_cap_usd: float = 27.0
    colab_cu_cap: float
    colab_l4_cu_per_hour: float | None
    checked_on: str
    source: str
    gpu_prices_usd_per_second: dict[str, float]
    cpu_usd_per_core_second: float = 0.0000131
    memory_usd_per_gib_second: float = 0.00000222
    default_cpu_cores: float = 8.0
    default_memory_gib: float = 64.0


class VllmConfig(StrictModel):
    version: str
    source: str
    gpu_memory_utilization: float
    max_num_seqs: int = 64
    default_max_model_len: int
    think_max_model_len: int
    think_max_tokens: int
    default_max_tokens: int


class LoadedConfigs(StrictModel):
    models: ModelsFile
    judges: JudgesFile
    experiment: ExperimentConfig
    budget: BudgetConfig

    @model_validator(mode="after")
    def free_arm_exists(self) -> LoadedConfigs:
        self.models.by_id(self.experiment.free_arm.config_id)
        return self


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "configs").is_dir():
            return parent
    raise FileNotFoundError("could not locate repository root")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a mapping")
    return data


def load_models(root: Path | None = None) -> ModelsFile:
    root = root or repo_root()
    return ModelsFile.model_validate(_load_yaml(root / "configs" / "models.yaml"))


def load_judges(root: Path | None = None) -> JudgesFile:
    root = root or repo_root()
    return JudgesFile.model_validate(_load_yaml(root / "configs" / "judges.yaml"))


def load_experiment(root: Path | None = None) -> ExperimentConfig:
    root = root or repo_root()
    return ExperimentConfig.model_validate(_load_yaml(root / "configs" / "experiment.yaml"))


def load_budget(root: Path | None = None) -> BudgetConfig:
    root = root or repo_root()
    return BudgetConfig.model_validate(_load_yaml(root / "configs" / "budget.yaml"))


def load_vllm(root: Path | None = None) -> VllmConfig:
    root = root or repo_root()
    return VllmConfig.model_validate(_load_yaml(root / "configs" / "vllm.yaml"))


class SmokeConfig(StrictModel):
    config_id: str
    hf_repo: str
    family: str = "smoke"
    axis: str = "l4_smoke"
    compute: Literal["modal_l4"] = "modal_l4"
    dtype: Literal["bf16", "auto"] = "bf16"
    max_tokens: int | None = None
    chat_template_kwargs: dict[str, Any]
    sampling: dict[str, Any]


def load_smoke(root: Path | None = None, *, name: str = "smoke") -> SmokeConfig:
    root = root or repo_root()
    path = root / "configs" / f"{name}.yaml"
    return SmokeConfig.model_validate(_load_yaml(path))


def load_all(root: Path | None = None) -> LoadedConfigs:
    root = root or repo_root()
    return LoadedConfigs(
        models=load_models(root),
        judges=load_judges(root),
        experiment=load_experiment(root),
        budget=load_budget(root),
    )

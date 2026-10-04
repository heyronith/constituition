"""Hugging Face metadata only — never download weight shards."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError
from huggingface_hub.utils import EntryNotFoundError

from rc.config import load_all, repo_root

GPU_MEMORY_GB = {
    "colab_l4": 24,
    "modal_l40s": 48,
    "modal_a100_80gb": 80,
    "modal_h100": 80,
}

HEADROOM = 0.20
# Cross-check assumes BF16 unless the index weight_map or card says otherwise.
BYTES_PER_PARAM_BF16 = 2.0
log = logging.getLogger("rc.hf_registry")


def _sibling_sizes(info) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for sib in getattr(info, "siblings", None) or []:
        name = getattr(sib, "rfilename", "") or ""
        size = getattr(sib, "size", None)
        if name and size is not None:
            sizes[name] = int(size)
    return sizes


def _load_weight_map(
    repo_id: str, revision: str, token: str | None, sizes: dict[str, int]
) -> tuple[list[str] | None, str | None]:
    """Return (weight filenames vLLM would load, method) or (None, reason).

    Downloads only the tiny index JSON — never weight shards.
    """
    if "model.safetensors.index.json" in sizes:
        try:
            index_path = hf_hub_download(
                repo_id=repo_id,
                filename="model.safetensors.index.json",
                revision=revision,
                token=token,
            )
            data = json.loads(Path(index_path).read_text(encoding="utf-8"))
            weight_map = data.get("weight_map") or {}
            files = sorted(set(weight_map.values()))
            if files:
                return files, "index"
        except (EntryNotFoundError, GatedRepoError, HfHubHTTPError, OSError, json.JSONDecodeError):
            pass

    if "model.safetensors" in sizes:
        return ["model.safetensors"], "single"

    return None, "no_index_or_single"


def _index_safetensors_gb(
    info, repo_id: str, revision: str, token: str | None
) -> tuple[float | None, dict[str, Any]]:
    """Sum only the shard files listed in the index (or single model.safetensors).

    Avoids double-counting duplicate copies such as `original/` or
    `consolidated.safetensors` alongside HF shards.
    """
    sizes = _sibling_sizes(info)
    files, method = _load_weight_map(repo_id, revision, token, sizes)
    meta: dict[str, Any] = {
        "weight_file_source": method,
        "weight_files": files,
        "all_safetensors_gb": None,
    }
    all_st = [(name, size) for name, size in sizes.items() if name.endswith(".safetensors")]
    if all_st:
        meta["all_safetensors_gb"] = sum(s for _, s in all_st) / (1024**3)

    if files is None:
        # Fallback: only top-level *.safetensors (no path separators).
        top = [s for name, s in all_st if "/" not in name]
        if not top:
            return None, meta
        meta["weight_file_source"] = "toplevel_fallback"
        return sum(top) / (1024**3), meta

    total = 0
    missing = []
    for name in files:
        if name not in sizes:
            missing.append(name)
            continue
        total += sizes[name]
    meta["missing_weight_files"] = missing
    if total == 0:
        return None, meta
    return total / (1024**3), meta


def _param_count(info) -> int | None:
    st = getattr(info, "safetensors", None)
    if st is not None and getattr(st, "parameters", None):
        params = st.parameters
        if isinstance(params, dict):
            return sum(int(v) for v in params.values())
        return int(params)
    return None


def _param_bytes_crosscheck_gb(
    param_count: int | None, bytes_per_param: float = BYTES_PER_PARAM_BF16
) -> float | None:
    if param_count is None:
        return None
    return (param_count * bytes_per_param) / (1024**3)


def _chat_template_flags(repo_id: str, revision: str, token: str | None) -> dict[str, Any]:
    flags = {
        "enable_thinking_supported": False,
        "think_token_supported": False,
        "chat_template_inspected": False,
    }
    texts: list[str] = []
    for filename in ("tokenizer_config.json", "chat_template.jinja"):
        try:
            path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                revision=revision,
                token=token,
            )
        except (EntryNotFoundError, GatedRepoError, HfHubHTTPError, OSError):
            continue
        try:
            texts.append(Path(path).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    blob = "\n".join(texts)
    if blob:
        flags["chat_template_inspected"] = True
        flags["enable_thinking_supported"] = "enable_thinking" in blob
        flags["think_token_supported"] = "<|think|>" in blob
    return flags


def inspect_repo(hf_repo: str, *, token: str | None = None) -> dict[str, Any]:
    api = HfApi(token=token)
    record: dict[str, Any] = {
        "requested_id": hf_repo,
        "exact_repo_id": None,
        "sha": None,
        "gated": None,
        "token_has_access": False,
        "license": None,
        "license_name": None,
        "safetensors_gb": None,
        "all_safetensors_gb": None,
        "weight_file_source": None,
        "parameter_count": None,
        "param_bytes_bf16_gb": None,
        "status": "UNRESOLVED",
        "error": None,
        "candidates": [],
        "chat_template": {},
    }
    try:
        info = api.model_info(hf_repo, files_metadata=True, token=token)
    except RepositoryNotFoundError as exc:
        record["error"] = f"not found: {exc}"
        record["candidates"] = _search_candidates(api, hf_repo, token)
        return record
    except GatedRepoError as exc:
        record["gated"] = True
        record["token_has_access"] = False
        record["error"] = f"gated, no access: {exc}"
        record["candidates"] = [hf_repo]
        return record
    except HfHubHTTPError as exc:
        record["error"] = f"http error: {exc}"
        return record

    record["exact_repo_id"] = info.id
    record["sha"] = info.sha
    gated = getattr(info, "gated", False)
    record["gated"] = bool(gated) if gated not in (None, False) else False
    record["token_has_access"] = True
    license_id = getattr(info, "license", None)
    card = getattr(info, "card_data", None)
    license_name = None
    if card is not None:
        raw = card.to_dict() if hasattr(card, "to_dict") else {}
        if not license_id:
            license_id = raw.get("license") or getattr(card, "license", None)
        license_name = raw.get("license_name") or getattr(card, "license_name", None)
    record["license"] = license_id
    record["license_name"] = license_name
    gb, size_meta = _index_safetensors_gb(info, info.id, info.sha, token)
    record["safetensors_gb"] = gb
    record["all_safetensors_gb"] = size_meta.get("all_safetensors_gb")
    record["weight_file_source"] = size_meta.get("weight_file_source")
    params = _param_count(info)
    if params is None:
        card_params = _param_from_card(info)
        params = int(card_params) if card_params and str(card_params).isdigit() else None
    record["parameter_count"] = str(params) if params is not None else None
    record["param_bytes_bf16_gb"] = _param_bytes_crosscheck_gb(params)
    record["chat_template"] = _chat_template_flags(info.id, info.sha, token)
    record["status"] = "OK"
    return record


def _param_from_card(info) -> str | None:
    card = getattr(info, "card_data", None)
    if card is None:
        return None
    raw = card.to_dict() if hasattr(card, "to_dict") else {}
    return raw.get("parameters") or raw.get("model_size")


def _search_candidates(api: HfApi, hf_repo: str, token: str | None) -> list[str]:
    query = hf_repo.split("/")[-1]
    try:
        hits = api.list_models(search=query, token=token, limit=8)
    except Exception as exc:  # noqa: BLE001 — lockfile should still write
        log.warning("model search failed for %s: %s", hf_repo, exc)
        return []
    return [h.id for h in hits]


def fit_check(safetensors_gb: float | None, compute: str) -> dict[str, Any]:
    gpu_gb = GPU_MEMORY_GB[compute]
    usable = gpu_gb * (1.0 - HEADROOM)
    if safetensors_gb is None:
        return {
            "compute": compute,
            "gpu_memory_gb": gpu_gb,
            "required_headroom": HEADROOM,
            "usable_gb": usable,
            "weights_gb": None,
            "fits": None,
            "flag": "UNKNOWN_SIZE",
        }
    fits = safetensors_gb <= usable
    return {
        "compute": compute,
        "gpu_memory_gb": gpu_gb,
        "required_headroom": HEADROOM,
        "usable_gb": usable,
        "weights_gb": safetensors_gb,
        "fits": fits,
        "flag": None if fits else "FAILS_HEADROOM",
    }


def collect_lockfile(*, token: str | None = None) -> dict[str, Any]:
    root = repo_root()
    cfg = load_all(root)
    subjects = []
    for subject in cfg.models.subjects:
        meta = inspect_repo(subject.hf_repo, token=token)
        meta["config_id"] = subject.config_id
        meta["role"] = "subject"
        meta["fit"] = fit_check(meta["safetensors_gb"], subject.compute)
        subjects.append(meta)
    judges = []
    for judge in cfg.judges.judges:
        meta = inspect_repo(judge.hf_repo, token=token)
        meta["judge_id"] = judge.judge_id
        meta["role"] = "judge"
        meta["fit"] = fit_check(meta["safetensors_gb"], judge.compute)
        judges.append(meta)
    return {"subjects": subjects, "judges": judges}

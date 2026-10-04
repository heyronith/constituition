"""Hugging Face metadata only — never download weight shards."""

from __future__ import annotations

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
log = logging.getLogger("rc.hf_registry")


def _safetensors_gb(info) -> float | None:
    total_bytes = 0
    found = False
    siblings = getattr(info, "siblings", None) or []
    for sib in siblings:
        name = getattr(sib, "rfilename", "") or ""
        size = getattr(sib, "size", None)
        if name.endswith(".safetensors") and size:
            total_bytes += int(size)
            found = True
    st = getattr(info, "safetensors", None)
    if st is not None and getattr(st, "total", None):
        total_bytes = max(total_bytes, int(st.total))
        found = True
    if not found:
        return None
    return total_bytes / (1024**3)


def _param_count(info) -> str | None:
    st = getattr(info, "safetensors", None)
    if st is not None and getattr(st, "parameters", None):
        params = st.parameters
        if isinstance(params, dict):
            total = sum(int(v) for v in params.values())
            return str(total)
        return str(params)
    return None


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
        "safetensors_gb": None,
        "parameter_count": None,
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
    if not license_id and card is not None:
        license_id = getattr(card, "license", None)
    record["license"] = license_id
    record["safetensors_gb"] = _safetensors_gb(info)
    record["parameter_count"] = _param_count(info) or _param_from_card(info)
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

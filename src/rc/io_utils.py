"""Atomic JSONL, hashing, seeds, and run manifests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON object as a line. Writes of small lines are atomic under O_APPEND."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    fd = os.open(path, flags, 0o644)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derive_seed(
    master_seed: int | str,
    config_id: str,
    condition: str,
    chain_idx: int,
) -> tuple[int, str]:
    """Deterministic per-unit seed: sha256(master_seed|config_id|condition|chain_idx).

    Returns (uint64 seed, hex digest).
    """
    payload = f"{master_seed}|{config_id}|{condition}|{chain_idx}".encode()
    digest = hashlib.sha256(payload).hexdigest()
    seed_int = int(digest[:16], 16)
    return seed_int, digest


def git_sha(root: Path | None = None) -> str:
    env_sha = os.environ.get("RC_GIT_SHA")
    if env_sha:
        return env_sha
    cwd = str(root) if root is not None else None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except FileNotFoundError:
        return "UNCOMMITTED"
    if result.returncode != 0:
        return "UNCOMMITTED"
    return result.stdout.strip()


def write_run_manifest(
    run_dir: Path,
    *,
    git_sha_value: str,
    config_hashes: dict[str, str],
    model_revision: str | None,
    seeds: dict[str, Any],
    output_hashes: dict[str, str],
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write runs/<run_id>/manifest.json. Output hashes make generations immutable."""
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "git_sha": git_sha_value,
        "config_hashes": config_hashes,
        "model_revision": model_revision,
        "seeds": seeds,
        "output_hashes": output_hashes,
    }
    if extra:
        manifest["extra"] = extra
    path = run_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path

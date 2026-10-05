"""Workspace, token, and subject-prompt blinding guards."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from rc.config import repo_root

FORBIDDEN_SUBJECT_WORDS = (
    "corrigibility",
    "corrigible",
    "study",
    "experiment",
    "erosion",
    "evaluation",
    "evaluate",
    "test",
    "tested",
    "testing",
    "benchmark",
    "research",
    "researcher",
    "hypothetical",
    "scenario",
    "overseer",
    "overseers",
)

_FORBIDDEN_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in FORBIDDEN_SUBJECT_WORDS) + r")\b",
    re.IGNORECASE,
)


class WorkspaceGuardError(RuntimeError):
    pass


class BlindingError(ValueError):
    pass


class HuggingFaceTokenError(RuntimeError):
    pass


class ModalSecretError(RuntimeError):
    pass


class GpuSafetyError(RuntimeError):
    pass


# D23: A100-class or larger requires L4 tiny-model smoke + MockBackend pytest.
A100_CLASS_OR_LARGER = frozenset({"A100-80GB", "H100", "A100", "H200"})


def l4_smoke_marker(root: Path | None = None) -> Path:
    """Current D23 marker: Phase 3 guided-decoding L4 smoke (supersedes phase2b)."""
    return (root or repo_root()) / "runs" / "phase3_l4_smoke" / "PASSED.json"


def assert_large_gpu_allowed(gpu: str, *, root: Path | None = None) -> None:
    """Refuse A100-class GPUs until the L4 tiny-model smoke marker exists."""
    if gpu not in A100_CLASS_OR_LARGER:
        return
    marker = l4_smoke_marker(root)
    if not marker.exists():
        raise GpuSafetyError(
            f"D23: GPU {gpu} is A100-class or larger. Run the Modal L4 tiny-model "
            f"smoke first (marker missing: {marker})."
        )


def assert_blinded(text: str, *, allow_eval_words: bool = False) -> None:
    """Raise if a subject-facing prompt contains a protocol-forbidden word.

    Set allow_eval_words=True only for measurement/calibration probe files
    (eval_awareness.yaml, realism_audit.yaml, calib_generator.yaml,
    calib_verifier.yaml). Never for chain prompts.
    """
    if allow_eval_words:
        return
    match = _FORBIDDEN_RE.search(text)
    if match:
        raise BlindingError(f"subject-facing text contains forbidden word {match.group(0)!r}")


def assert_modal_workspace(expected: str = "heyronith") -> str:
    """Fail unless the active Modal workspace is `expected`.

    Installed Modal (CLI) exposes the workspace *username* on
    `modal profile list --json` as the `workspace` field of the active
    profile. `modal profile current` prints only the profile name.
    `modal.Workspace.from_context().name` also works after hydrate(), but
    that is an extra RPC; the JSON CLI is the most direct local check.
    """
    if os.environ.get("MODAL_TOKEN_ID") or os.environ.get("MODAL_TOKEN_SECRET"):
        raise WorkspaceGuardError(
            "MODAL_TOKEN_ID and/or MODAL_TOKEN_SECRET are set. Those variables "
            "override Modal profiles and can point at the old account. Unset them "
            "(unset MODAL_TOKEN_ID MODAL_TOKEN_SECRET) and use "
            "`uv run modal profile activate heyronith`."
        )
    result = subprocess.run(
        ["modal", "profile", "list", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise WorkspaceGuardError(
            f"modal profile list --json failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        profiles = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise WorkspaceGuardError("modal profile list --json returned invalid JSON") from exc
    active = [p for p in profiles if p.get("active")]
    if not active:
        raise WorkspaceGuardError("no active Modal profile")
    workspace = active[0].get("workspace")
    if workspace != expected:
        raise WorkspaceGuardError(
            f"active Modal workspace is {workspace!r}, expected {expected!r}. "
            "Activate the heyronith profile; do not reuse the old account."
        )
    return str(workspace)


def check_hf_token(*, env_file: Path | None = None) -> dict:
    """Verify HF_TOKEN is present and valid. Never print the token value."""
    load_dotenv(env_file or (repo_root() / ".env"), override=False)
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise HuggingFaceTokenError("HF_TOKEN is missing (set it in .env; never commit it)")
    from huggingface_hub import whoami

    identity = whoami(token=token)
    return {"name": identity.get("name"), "type": identity.get("type")}


def check_modal_hf_secret(expected_name: str = "hf-token") -> str:
    """Verify a Modal secret name exists. Never print secret values."""
    assert_modal_workspace(expected="heyronith")
    result = subprocess.run(
        ["modal", "secret", "list", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ModalSecretError(
            f"modal secret list --json failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        secrets = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ModalSecretError("modal secret list --json returned invalid JSON") from exc
    names = {row.get("name") for row in secrets if isinstance(row, dict)}
    if expected_name not in names:
        raise ModalSecretError(
            f"Modal secret {expected_name!r} not found in workspace heyronith. "
            "Create it with: uv run modal secret create hf-token HF_TOKEN=<token>"
        )
    return expected_name

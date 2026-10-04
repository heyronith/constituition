"""Modal workspace and HF-token guards (subprocess and HF mocked)."""

from __future__ import annotations

import json

import pytest

from rc.guards import (
    BlindingError,
    HuggingFaceTokenError,
    WorkspaceGuardError,
    assert_blinded,
    assert_modal_workspace,
    check_hf_token,
)


def test_fails_when_modal_token_id_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_TOKEN_ID", "ak-fake")
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)

    def boom(*_a, **_k):
        raise AssertionError("subprocess should not run when env tokens are set")

    monkeypatch.setattr("rc.guards.subprocess.run", boom)
    with pytest.raises(WorkspaceGuardError, match="Unset"):
        assert_modal_workspace()


def _profile_list(workspace: str, active: bool = True) -> object:
    class Result:
        returncode = 0
        stdout = json.dumps([{"name": workspace, "workspace": workspace, "active": active}])
        stderr = ""

    return Result()


def test_fails_when_workspace_wrong(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)
    monkeypatch.setattr(
        "rc.guards.subprocess.run",
        lambda *_a, **_k: _profile_list("old-account"),
    )
    with pytest.raises(WorkspaceGuardError, match="old-account"):
        assert_modal_workspace()


def test_passes_for_heyronith(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)
    monkeypatch.setattr(
        "rc.guards.subprocess.run",
        lambda *_a, **_k: _profile_list("heyronith"),
    )
    assert assert_modal_workspace() == "heyronith"


def test_check_hf_token_requires_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    with pytest.raises(HuggingFaceTokenError):
        check_hf_token(env_file=env_file)


def test_check_hf_token_calls_whoami(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import huggingface_hub

    monkeypatch.setenv("HF_TOKEN", "hf_not_a_real_token")
    env_file = tmp_path / ".env"
    env_file.write_text("HF_TOKEN=hf_not_a_real_token\n", encoding="utf-8")

    def fake_whoami(token=None):
        assert token
        return {"name": "tester", "type": "user"}

    monkeypatch.setattr(huggingface_hub, "whoami", fake_whoami)
    identity = check_hf_token(env_file=env_file)
    assert identity["name"] == "tester"


def test_assert_blinded_raises_on_forbidden_words() -> None:
    with pytest.raises(BlindingError):
        assert_blinded("This is an experiment about values.")
    with pytest.raises(BlindingError):
        assert_blinded("Measure corrigibility of the agent.")
    assert_blinded("Revise these principles so they are ones you endorse.")

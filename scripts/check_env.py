#!/usr/bin/env python3
"""Print PASS/FAIL for local environment. Exit 1 if any check fails."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT / ".env", override=False)

from rc.budget import ledger_path  # noqa: E402
from rc.config import load_all  # noqa: E402
from rc.guards import (  # noqa: E402
    assert_modal_workspace,
    check_hf_token,
    check_modal_hf_secret,
)


def _ok(name: str, detail: str = "") -> None:
    suffix = f" ({detail})" if detail else ""
    print(f"PASS  {name}{suffix}")


def _fail(name: str, detail: str) -> None:
    print(f"FAIL  {name}: {detail}")


def main() -> int:
    failures = 0

    try:
        import sys as _sys

        py = _sys.version_info
        if py < (3, 11):
            raise RuntimeError(f"Python {py.major}.{py.minor}, need >=3.11")
        uv = subprocess.run(["uv", "--version"], check=True, capture_output=True, text=True)
        _ok("uv/python", f"{uv.stdout.strip()}, Python {py.major}.{py.minor}.{py.micro}")
    except Exception as exc:
        failures += 1
        _fail("uv/python", str(exc))

    if os.environ.get("MODAL_TOKEN_ID") or os.environ.get("MODAL_TOKEN_SECRET"):
        failures += 1
        _fail(
            "modal_workspace",
            "MODAL_TOKEN_ID/SECRET are set; unset them so the heyronith profile is used",
        )
    else:
        try:
            workspace = assert_modal_workspace(expected="heyronith")
            _ok("modal_workspace", workspace)
        except Exception as exc:
            failures += 1
            _fail("modal_workspace", str(exc))

    try:
        identity = check_hf_token(env_file=ROOT / ".env")
        _ok("hf_token", f"whoami name={identity.get('name')} type={identity.get('type')}")
    except Exception as exc:
        failures += 1
        _fail("hf_token", str(exc))

    try:
        secret_name = check_modal_hf_secret("hf-token")
        _ok("modal_hf_secret", f"name={secret_name} (value not printed)")
    except Exception as exc:
        failures += 1
        _fail("modal_hf_secret", str(exc))

    try:
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", ".env"],
            cwd=ROOT,
        )
        if ignored.returncode == 0:
            _ok("dotenv_gitignored", ".env is ignored")
        elif ignored.returncode == 1:
            raise RuntimeError(".env is not gitignored")
        else:
            raise RuntimeError("git check-ignore failed (is this a git repo?)")
    except Exception as exc:
        failures += 1
        _fail("dotenv_gitignored", str(exc))

    try:
        path = ledger_path(ROOT)
        if not path.exists():
            raise FileNotFoundError(f"missing {path}")
        from rc.budget import _parse_ledger

        _parse_ledger(path)
        _ok("ledger", str(path.relative_to(ROOT)))
    except Exception as exc:
        failures += 1
        _fail("ledger", str(exc))

    try:
        cfg = load_all(ROOT)
        _ok(
            "configs",
            f"{len(cfg.models.subjects)} subjects, {len(cfg.judges.judges)} judges",
        )
    except Exception as exc:
        failures += 1
        _fail("configs", str(exc))

    try:
        lock = ROOT / "configs" / "model_revisions.lock.yaml"
        if not lock.exists():
            raise FileNotFoundError("configs/model_revisions.lock.yaml missing")
        import yaml

        data = yaml.safe_load(lock.read_text(encoding="utf-8"))
        unresolved = []
        for role in ("subjects", "judges"):
            for row in data.get(role, []):
                if row.get("status") == "UNRESOLVED":
                    key = row.get("config_id") or row.get("judge_id") or row.get("requested_id")
                    unresolved.append(key)
        if unresolved:
            raise RuntimeError(f"UNRESOLVED entries: {unresolved}")
        _ok("lockfile", "no UNRESOLVED entries")
    except Exception as exc:
        failures += 1
        _fail("lockfile", str(exc))

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Package main_v1 raw chains per config and push to private HF dataset (D55 r6)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import modal

APP = "rc-backup-main-v1"
CONFIGS = (
    "olmo3_7b_final",
    "qwen38_27b_nothink",
    "qwen38_27b_think",
    "gemma4_31b",
    "gemma4_12b",
    "olmo3_7b_sft",
    "olmo3_7b_dpo",
)
FILES = ("rounds.jsonl", "constitutions.jsonl", "lineage.jsonl", "meta.json")

app = modal.App(APP)
image = modal.Image.debian_slim(python_version="3.11")
vol = modal.Volume.from_name("rc-runs")


@app.function(image=image, volumes={"/vol": vol}, timeout=3600, memory=8192)
def package_config(config_id: str) -> dict:
    """Build tar.gz of all 840/7 chain files for one config; return bytes + sha."""
    import io

    root = Path("/vol/main_v1") / config_id
    buf = io.BytesIO()
    n_files = 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.name not in FILES:
                continue
            # only FORCED chains (all protocols present; package all under config)
            arc = path.relative_to(root.parent)  # main_v1/<config>/...
            tf.add(path, arcname=str(arc))
            n_files += 1
    data = buf.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    out = Path("/vol/backups_main_v1") / f"{config_id}.tar.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    # also write sha sidecar
    (out.with_suffix(out.suffix + ".sha256")).write_text(sha + "\n", encoding="utf-8")
    vol.commit()
    return {
        "config_id": config_id,
        "n_files": n_files,
        "bytes": len(data),
        "sha256": sha,
        "volume_path": str(out),
    }


@app.local_entrypoint()
def main(hf_repo: str = "ronithsharmila/rc-main-v1-raw") -> None:
    from rc.config import repo_root
    from rc.guards import assert_modal_workspace

    assert_modal_workspace(expected="heyronith")
    root = repo_root()
    out_dir = root / "results" / "backups_main_v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    metas = []
    for cfg in CONFIGS:
        print(f"packaging {cfg}…")
        meta = package_config.remote(cfg)
        metas.append(meta)
        # pull archive to laptop
        local = out_dir / f"{cfg}.tar.gz"
        subprocess.run(
            [
                "modal",
                "volume",
                "get",
                "rc-runs",
                f"backups_main_v1/{cfg}.tar.gz",
                str(local),
            ],
            check=True,
        )
        sha_local = hashlib.sha256(local.read_bytes()).hexdigest()
        assert sha_local == meta["sha256"], (cfg, sha_local, meta["sha256"])
        (out_dir / f"{cfg}.tar.gz.sha256").write_text(
            f"{meta['sha256']}  {cfg}.tar.gz\n", encoding="utf-8"
        )
        print(f"  files={meta['n_files']} bytes={meta['bytes']} sha={meta['sha256'][:16]}…")

    sha_doc = "\n".join(f"{m['sha256']}  {m['config_id']}.tar.gz" for m in metas) + "\n"
    (out_dir / "SHA256SUMS").write_text(sha_doc, encoding="utf-8")

    # HF upload
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    role = None
    if not token:
        env = root / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("HF_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
    upload: dict = {"ok": False, "repo": hf_repo, "error": None}
    if token:
        try:
            from huggingface_hub import HfApi, whoami

            info = whoami(token=token)
            role = info.get("auth", {}).get("accessToken", {}).get("role")
            api = HfApi(token=token)
            api.create_repo(hf_repo, repo_type="dataset", private=True, exist_ok=True)
            for cfg in CONFIGS:
                api.upload_file(
                    path_or_fileobj=str(out_dir / f"{cfg}.tar.gz"),
                    path_in_repo=f"{cfg}.tar.gz",
                    repo_id=hf_repo,
                    repo_type="dataset",
                )
                api.upload_file(
                    path_or_fileobj=str(out_dir / f"{cfg}.tar.gz.sha256"),
                    path_in_repo=f"{cfg}.tar.gz.sha256",
                    repo_id=hf_repo,
                    repo_type="dataset",
                )
            api.upload_file(
                path_or_fileobj=str(out_dir / "SHA256SUMS"),
                path_in_repo="SHA256SUMS",
                repo_id=hf_repo,
                repo_type="dataset",
            )
            upload = {
                "ok": True,
                "repo": hf_repo,
                "url": f"https://huggingface.co/datasets/{hf_repo}",
                "token_role": role,
            }
        except Exception as exc:  # noqa: BLE001
            upload = {
                "ok": False,
                "repo": hf_repo,
                "error": f"{type(exc).__name__}: {exc}",
                "token_role": role,
            }
    else:
        upload["error"] = "HF_TOKEN missing"

    summary = {
        "packages": metas,
        "local_dir": str(out_dir),
        "upload": upload,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2)[:3000])
    if not upload["ok"]:
        print("HF upload failed; packages retained locally + on Volume backups_main_v1/")

"""CPU-only: download pinned subject weights into Modal Volume rc-hf-cache.

Run before any GPU job so GPU time is never spent downloading.
"""

from __future__ import annotations

import time

import modal

APP_NAME = "rc-download-weights"
VOLUME_NAME = "rc-hf-cache"
CACHE_DIR = "/hf-cache"

app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("huggingface_hub>=0.26", "hf_transfer")
    .env({"HF_HOME": CACHE_DIR, "HF_HUB_ENABLE_HF_TRANSFER": "1"})
)


@app.function(
    image=image,
    volumes={CACHE_DIR: volume},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=60 * 60 * 4,
    cpu=4,
    memory=8192,
)
def download_repos(repos: list[dict[str, str]]) -> dict:
    """Download each {repo_id, revision} into the HF cache volume."""
    import os

    from huggingface_hub import snapshot_download

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN missing from Modal secret hf-token")

    results = []
    for row in repos:
        repo_id = row["repo_id"]
        revision = row["revision"]
        started = time.perf_counter()
        path = snapshot_download(
            repo_id=repo_id,
            revision=revision,
            token=token,
            cache_dir=CACHE_DIR,
        )
        elapsed = time.perf_counter() - started
        results.append(
            {
                "repo_id": repo_id,
                "revision": revision,
                "path": path,
                "seconds": elapsed,
            }
        )
        volume.commit()
    return {"downloaded": results, "cache_dir": CACHE_DIR}


@app.local_entrypoint()
def main(*config_ids: str) -> None:
    """Download Modal subject weights (default: all non-Colab subjects)."""
    from rc.budget import estimate_modal_usd, preflight, record_actual
    from rc.config import load_models, repo_root
    from rc.generation import load_lock_revision
    from rc.guards import assert_modal_workspace, check_modal_hf_secret

    assert_modal_workspace(expected="heyronith")
    check_modal_hf_secret("hf-token")
    root = repo_root()
    models = load_models(root)
    wanted = set(config_ids) if config_ids else {
        s.config_id for s in models.subjects if s.compute.startswith("modal_")
    }
    # Deduplicate by (repo, revision).
    seen: set[tuple[str, str]] = set()
    repos: list[dict[str, str]] = []
    for sid in sorted(wanted):
        subject = models.by_id(sid)
        if not subject.compute.startswith("modal_"):
            print(f"skip non-modal {sid}")
            continue
        repo_id, sha = load_lock_revision(sid, root)
        key = (repo_id, sha)
        if key in seen:
            continue
        seen.add(key)
        repos.append({"repo_id": repo_id, "revision": sha})

    max_seconds = 60 * 60 * 3
    preflight(
        gpu="cpu",
        max_seconds=max_seconds,
        phase=2,
        job_id="phase2-download-weights",
        platform="modal",
        override_job_cap_usd=5.0,
        cpu_cores=4.0,
        memory_gib=8.0,
        root=root,
    )
    est = estimate_modal_usd("cpu", max_seconds, cpu_cores=4.0, memory_gib=8.0, root=root)
    print(f"downloading {len(repos)} unique repos; est_usd_ceiling=${est:.4f}")
    started = time.perf_counter()
    result = download_repos.remote(repos)
    elapsed = time.perf_counter() - started
    actual = estimate_modal_usd("cpu", int(elapsed) + 1, cpu_cores=4.0, memory_gib=8.0, root=root)
    record_actual(
        job_id="phase2-download-weights",
        phase=2,
        platform="modal",
        gpu="cpu",
        max_seconds=max_seconds,
        actual_seconds=elapsed,
        est_usd=est,
        actual_usd=actual,
        note=f"downloaded={len(result['downloaded'])}",
        root=root,
    )
    for row in result["downloaded"]:
        print(
            f"ok {row['repo_id']}@{row['revision'][:12]} "
            f"seconds={row['seconds']:.1f} path={row['path']}"
        )

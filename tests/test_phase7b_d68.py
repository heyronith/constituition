"""D68: batch submit lock TTL + release; coding STATUS heartbeat."""

from __future__ import annotations

import json
import time
from pathlib import Path

from rc.phase7b import (
    BATCH_LOCK_TTL_S,
    CodingStatusHeartbeat,
    acquire_batch_submit_lock,
    batch_lock_path,
    lock_is_orphaned,
    release_batch_submit_lock,
)


def test_lock_ttl_allows_steal_of_orphaned_holder(tmp_path: Path) -> None:
    root = tmp_path
    path = batch_lock_path(root=root)
    path.parent.mkdir(parents=True)
    old = time.time() - (BATCH_LOCK_TTL_S + 10)
    path.write_text(
        json.dumps(
            {
                "config_id": "dead_cfg",
                "unix": old,
                "utc": "2026-01-01T00:00:00Z",
                "pid": 1,
                "held": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert lock_is_orphaned(json.loads(path.read_text()), now=time.time()) is True
    acquire_batch_submit_lock(
        "gemma4_12b", root=root, min_gap_s=600.0, poll_s=0.01, max_wait_s=5.0
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["config_id"] == "gemma4_12b"
    assert payload["held"] is True
    assert payload.get("orphaned_steal") is True


def test_release_batch_submit_lock_in_finally_pattern(tmp_path: Path) -> None:
    root = tmp_path
    acquire_batch_submit_lock(
        "cfg_a", root=root, min_gap_s=0.0, poll_s=0.01, max_wait_s=5.0
    )
    path = batch_lock_path(root=root)
    assert json.loads(path.read_text())["held"] is True
    try:
        raise RuntimeError("simulate_preempt")
    except RuntimeError:
        released = release_batch_submit_lock("cfg_a", root=root)
    assert released is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["held"] is False
    assert payload["config_id"] == "cfg_a"
    assert "released_utc" in payload
    # Wrong holder cannot release.
    assert release_batch_submit_lock("other", root=root) is False


def test_coding_status_heartbeat_every_interval() -> None:
    writes: list[dict] = []
    t = {"now": 0.0}

    def write_fn(**payload):
        writes.append(dict(payload))

    hb = CodingStatusHeartbeat(
        write_fn, interval_s=15.0, clock=lambda: t["now"]
    )
    assert hb.pulse("batch_poll", force=True) is True
    assert hb.pulse("batch_poll") is False  # within interval
    t["now"] = 16.0
    assert hb.pulse("batch_poll", completed=10, total=100) is True
    assert writes[-1]["coding_substage"] == "batch_poll"
    assert writes[-1]["completed"] == 10
    t["now"] = 20.0
    assert hb.pulse("mimo", force=True) is True
    assert writes[-1]["coding_substage"] == "mimo"

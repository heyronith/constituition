"""D23 GPU-safety: A100-class jobs require the L4 tiny-model smoke marker."""

from pathlib import Path

import pytest

from rc.guards import GpuSafetyError, assert_large_gpu_allowed, l4_smoke_marker


def test_l40s_allowed_without_smoke(tmp_path: Path) -> None:
    assert_large_gpu_allowed("L40S", root=tmp_path)
    assert_large_gpu_allowed("L4", root=tmp_path)


def test_a100_blocked_until_smoke_marker(tmp_path: Path) -> None:
    with pytest.raises(GpuSafetyError, match="D23"):
        assert_large_gpu_allowed("A100-80GB", root=tmp_path)
    marker = l4_smoke_marker(tmp_path)
    marker.parent.mkdir(parents=True)
    marker.write_text('{"ok": true}\n', encoding="utf-8")
    assert_large_gpu_allowed("A100-80GB", root=tmp_path)
    assert_large_gpu_allowed("H100", root=tmp_path)

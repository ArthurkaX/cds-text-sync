"""Timeout sizing is stable and the block scan happens only at startup."""

from pathlib import Path
import sys


_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE = _ROOT / "products" / "codesys-host" / "src" / "ide_bridge"
if str(_BRIDGE) not in sys.path:
    sys.path.insert(0, str(_BRIDGE))

from ide_timeout_profile import count_st_blocks, make_timeout_profile


def test_profile_counts_st_blocks_and_sizes_each_operation(tmp_path):
    view = tmp_path / "project-view"
    view.mkdir()
    for name in ("one.st", "two.ST", "note.txt"):
        (view / name).write_text("", encoding="utf-8")

    count = count_st_blocks(str(tmp_path))
    profile = make_timeout_profile(count)

    assert count == 2
    assert profile["block_count"] == 2
    assert profile["timeouts"]["build"] == 120
    assert profile["timeouts"]["sync_import_text"] == 180


def test_profile_uses_safe_fallback_when_project_view_is_missing(tmp_path):
    profile = make_timeout_profile(count_st_blocks(str(tmp_path)))

    assert profile["block_count"] is None
    assert all(value == 600 for value in profile["timeouts"].values())

"""The benchmark must detect dropped/reordered frames and changed replay outcomes."""
from pathlib import Path

import pytest

from tools.benchmark_video import _compare_runs, _frame_hashes, _parser


def _report(path: Path, hashes, *, outcome=None, seconds=1.0):
    path.write_text("#format: frame checksums\n#tb 0: 1/40\n" + "".join(
        f"0, {index}, {index}, 1, 24, {digest}\n"
        for index, digest in enumerate(hashes)), encoding="ascii")
    return {"median_elapsed_seconds": seconds, "runs": [{
        "repeat": 1, "outcome": outcome or {"complete": True, "video_frames": len(hashes)},
        "hashes_path": str(path), "decoded_frames": len(hashes),
    }]}


@pytest.mark.parametrize("new_hashes,first_difference", [
    (["aaa", "bbb"], None),
    (["bbb", "aaa"], 0),
    (["aaa", "changed"], 1),
    (["aaa"], 1),
    (["aaa", "bbb", "ccc"], 2),
])
def test_compare_stream_detects_changes_and_truncation(tmp_path, new_hashes, first_difference):
    old = _report(tmp_path / "old.framemd5", ["aaa", "bbb"], seconds=2)
    new = _report(tmp_path / "new.framemd5", new_hashes)
    result = _compare_runs(old, new)
    assert result["speedup"] == 2
    assert result["identical"] == (first_difference is None)
    assert result["runs"][0]["first_different_frame_zero_based"] == first_difference


def test_compare_rejects_outcome_change_with_identical_pixels(tmp_path):
    old = _report(tmp_path / "old.framemd5", ["aaa"], outcome={"complete": True})
    new = _report(tmp_path / "new.framemd5", ["aaa"], outcome={"complete": False})
    result = _compare_runs(old, new)
    assert not result["identical"]
    assert result["runs"][0]["decoded_rgb_frames_equal"]
    assert result["runs"][0]["changed_outcome_fields"] == ["complete"]


def test_hash_reader_rejects_invalid_ffmpeg_records(tmp_path):
    path = tmp_path / "bad.framemd5"
    path.write_text("0, unexpected\n", encoding="ascii")
    with pytest.raises(ValueError, match="Unexpected framemd5 record"):
        list(_frame_hashes(path))


def test_cli_accepts_case_matrix_and_zero_auto_workers():
    args = _parser().parse_args(["--ghosts", "0", "20", "--scales", "1", "4",
                                "--workers", "0", "4", "--fps", "40", "120"])
    assert args.ghosts == [0, 20]
    assert args.scales == [1, 4]
    assert args.workers == [0, 4]
    assert args.fps == [40, 120]
    assert args.quality == "exact"

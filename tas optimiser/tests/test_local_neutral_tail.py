"""Local treats omitted end-of-replay frames as neutral inputs, in both engines."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from nv14_engine import InputFrame, parse_level_string
from nv14_replay import (
    decode_complex_replay,
    encode_complex_replay,
    parse_combined_level_replay,
    simulate_through_frame,
)


ROOT = Path(__file__).resolve().parents[1]
LEVEL = "0" * (31 * 23) + "|5^100,100"


@pytest.mark.parametrize("search", ["windows", "population"])
def test_local_can_search_through_implicit_neutral_tail_with_splice_toml(tmp_path, search):
    """Includes the exact target frame, not merely the preceding frame."""
    source = tmp_path / "short.txt"
    original = [InputFrame(right=True)] * 3
    source.write_text(
        f"$Short#tests##{LEVEL}#{encode_complex_replay(original)}#\n",
        encoding="utf-8",
    )
    source_contents = source.read_bytes()
    config = tmp_path / "splice.toml"
    config.write_text(
        "[local]\n"
        f'search = "{search}"\n'
        'range = "3:7"\n'
        "target_frame = 7\n"
        'objective = "max-x"\n'
        "simulate-enemies = false\n"
        "workers = 1\n"
        "seed = 23\n"
        + (
            "window = 2\npasses = 1\nrestarts = 1\n"
            if search == "windows" else
            "iterations = 32\nbeam = 8\nrounds = 1\n"
        ),
        encoding="utf-8",
    )
    output = tmp_path / "result.txt"
    result = subprocess.run(
        [sys.executable, str(ROOT / "optimize_replay.py"), "local", str(source),
         "--config", str(config), "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True, timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "appended 5 neutral input frame(s) through frame 7" in result.stdout
    assert source.read_bytes() == source_contents
    combined = parse_combined_level_replay(output.read_text(encoding="utf-8"))
    assert combined.level_string == LEVEL
    packed = decode_complex_replay(combined.replay_string)
    assert packed.tick_count == 8
    assert [(f.left, f.right, f.jump) for f in packed.frames[:3]] == [
        (False, True, False), (False, True, False), (False, True, False)
    ]
    state = simulate_through_frame(parse_level_string(LEVEL, simulate_enemies=False),
                                   packed.frames, 7)
    assert not state.player.dead


def test_local_does_not_extend_a_replay_already_covering_target(tmp_path):
    source = tmp_path / "long.txt"
    source.write_text(
        f"$Long#tests##{LEVEL}#{encode_complex_replay([InputFrame()] * 9)}#\n",
        encoding="utf-8",
    )
    output = tmp_path / "result.txt"
    result = subprocess.run(
        [sys.executable, str(ROOT / "optimize_replay.py"), "local", str(source),
         "--target-frame", "4", "--range", "2:4", "--objective", "max-x",
         "--window", "2", "--passes", "1", "--workers", "1", "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True, timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "appended" not in result.stdout
    combined = parse_combined_level_replay(output.read_text(encoding="utf-8"))
    assert decode_complex_replay(combined.replay_string).tick_count == 9

"""Endpoint Auto accepts cut replays with a future Local-splice deadline."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from nv14_engine import InputFrame, parse_level_string
from nv14_endpoint import EndpointGoal, verify_endpoint
from nv14_objectives import resolve_target_object
from nv14_replay import (
    decode_complex_replay,
    encode_complex_replay,
    parse_combined_level_replay,
)


ROOT = Path(__file__).resolve().parents[1]
LEVEL = "0" * (31 * 23) + "|5^100,100!11^400,100,300,100"


def _input(tmp_path: Path, frame_count: int = 3) -> Path:
    source = tmp_path / "short.txt"
    source.write_text(
        f"$Short#tests##{LEVEL}#"
        + encode_complex_replay([InputFrame()] * frame_count) + "#\n",
        encoding="utf-8",
    )
    return source


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ROOT / "optimize_replay.py"), *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=45)


def test_auto_imported_local_exit_goal_pads_implicit_neutral_tail(tmp_path):
    source = _input(tmp_path)
    source_data = source.read_bytes()
    goal_config = tmp_path / "splice.toml"
    goal_config.write_text(
        '[local]\nobjective = "min-distance"\n'
        'target-object = "exit"\n'
        'target-frame = 7\nrange = "3:7"\n',
        encoding="utf-8",
    )
    output = tmp_path / "out.txt"
    result = _run("auto", str(source), "--goal-config", str(goal_config),
                  "--workers", "1", "--iterations", "8", "--beam", "4",
                  "--auto-runs", "1", "--output", str(output))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "auto:goal: appended 5 neutral input frame(s) through frame 7" in result.stdout
    assert "source feasible; frame 7" in result.stdout
    assert source.read_bytes() == source_data
    replay = parse_combined_level_replay(output.read_text(encoding="utf-8"))
    packed = decode_complex_replay(replay.replay_string)
    assert packed.tick_count == 8
    assert all(not f.left and not f.right and not f.jump for f in packed.frames[:3])
    level = parse_level_string(LEVEL)
    goal = EndpointGoal(target_frame=7, objective="min-distance",
                        target=resolve_target_object(level, "exit"))
    assert verify_endpoint(level, packed.frames, goal).feasible


@pytest.mark.parametrize("target,expected_frames", [(7, 8), (1, 3)])
def test_auto_explicit_target_frame_only_extends_when_needed(tmp_path, target, expected_frames):
    source = _input(tmp_path)
    output = tmp_path / "out.txt"
    result = _run("auto", str(source), "--objective", "max-x",
                  "--target-frame", str(target), "--range", f"0:{target}",
                  "--workers", "1", "--iterations", "0", "--auto-runs", "1",
                  "--output", str(output))
    assert result.returncode == 0, result.stdout + result.stderr
    if target == 7:
        assert "auto:goal: appended 5 neutral input frame(s)" in result.stdout
    else:
        assert "appended" not in result.stdout
    output_frames = decode_complex_replay(
        parse_combined_level_replay(output.read_text(encoding="utf-8")).replay_string)
    assert output_frames.tick_count == expected_frames

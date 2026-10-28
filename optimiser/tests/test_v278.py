from pathlib import Path

import pytest

import nv14_jump
import nv14_local
import nv14_search
from nv14_cli import build_parser
from nv14_engine import InputFrame, parse_level_string
from nv14_jump import optimise_jump_patterns
from nv14_local import optimise_local_windows
from nv14_replay import (
    decode_complex_replay,
    parse_combined_level_replay,
)
from nv14_search import NativeTerminalState, player_snapshot_key


HERE = Path(__file__).parent


def _require_native() -> None:
    info = nv14_search.backend_info()
    if not info.get("available"):
        pytest.skip(f"native replay-search kernel unavailable: {info.get('error')}")


def test_local_python_result_resimulation_is_opt_in(monkeypatch) -> None:
    _require_native()
    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(3)]
    original_evaluate = nv14_local.evaluate
    calls = 0

    def counted_evaluate(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_evaluate(*args, **kwargs)

    monkeypatch.setattr(nv14_local, "evaluate", counted_evaluate)
    kwargs = dict(
        target_frame=2,
        range_start=0,
        range_end=0,
        objective_name="max-x",
        window_size=1,
        passes=1,
        workers=1,
        progress=None,
    )

    default_frames, default_result = optimise_local_windows(level, frames, **kwargs)
    assert calls == 1  # Initial baseline only; the native winner is not replayed.
    assert isinstance(default_result.state, NativeTerminalState)

    calls = 0
    checked_frames, checked_result = optimise_local_windows(
        level,
        frames,
        python_resimulate=True,
        **kwargs,
    )
    assert calls == 2  # Initial baseline plus the accepted winner parity check.
    assert not isinstance(checked_result.state, NativeTerminalState)
    assert checked_frames == default_frames
    assert checked_result.score == default_result.score
    assert player_snapshot_key(checked_result.state.player) == player_snapshot_key(
        default_result.state.player
    )


def test_jump_result_resimulation_is_opt_in(monkeypatch) -> None:
    _require_native()
    combined = parse_combined_level_replay(
        (HERE / "example_ditched_supplied.txt").read_text(encoding="utf-8")
    )
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string)
    original_evaluate = nv14_jump.evaluate
    calls = 0

    def counted_evaluate(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_evaluate(*args, **kwargs)

    monkeypatch.setattr(nv14_jump, "evaluate", counted_evaluate)
    kwargs = dict(
        target_frame=123,
        range_start=106,
        range_end=123,
        objective_name="min-x",
        jump_count_min=1,
        jump_count_max=1,
        jump_length_min=1,
        jump_length_max=2,
        fixed_jump_frames=(112,),
        top_results=1,
        workers=1,
        progress=None,
    )

    default = optimise_jump_patterns(level, replay.frames, **kwargs)
    assert calls == 0
    assert isinstance(default[0].evaluation.state, NativeTerminalState)

    checked = optimise_jump_patterns(
        level,
        replay.frames,
        python_resimulate=True,
        **kwargs,
    )
    assert calls == 1
    assert not isinstance(checked[0].evaluation.state, NativeTerminalState)
    assert checked[0].pulses == default[0].pulses
    assert checked[0].score == default[0].score
    assert player_snapshot_key(checked[0].evaluation.state.player) == (
        player_snapshot_key(default[0].evaluation.state.player)
    )


def test_python_resimulation_cli_option_defaults_off() -> None:
    parser = build_parser()

    local_default = parser.parse_args(["local", "input.txt", "--range", "0:1"])
    local_debug = parser.parse_args(
        ["local", "input.txt", "--range", "0:1", "--python-resimulate"]
    )
    jump_default = parser.parse_args(
        ["jump-pattern", "input.txt", "--range", "0:1"]
    )
    jump_debug = parser.parse_args(
        ["jump-pattern", "input.txt", "--range", "0:1", "--python-resimulate"]
    )

    assert local_default.python_resimulate is False
    assert jump_default.python_resimulate is False
    assert local_debug.python_resimulate is True
    assert jump_debug.python_resimulate is True

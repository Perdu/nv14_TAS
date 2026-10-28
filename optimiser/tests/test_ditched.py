import csv
from pathlib import Path

import pytest

from nv14_engine import parse_level_string
from nv14_replay import decode_complex_replay, parse_combined_level_replay
from optimize_replay import (
    apply_jump_pattern,
    optimise_jump_patterns,
    optimise_local_windows,
    state_before_frame,
    successful_jump_frames,
)


HERE = Path(__file__).parent
SUPPLIED = HERE / "example_ditched_supplied.txt"
TRACE_MATCHED = HERE / "example_ditched_trace_matched.txt"
TRACE_STATES = HERE / "ditched_libtas_states.csv"


def load_record(path: Path):
    combined = parse_combined_level_replay(path.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string)
    return replay, level


def trace_states():
    with TRACE_STATES.open(newline="", encoding="utf-8") as handle:
        return [
            (int(row["frame"]), float(row["x"]), float(row["y"]), float(row["vx"]), float(row["vy"]))
            for row in csv.DictReader(handle)
        ]


def test_ditched_supplied_replay_matches_libtas_through_frame_110() -> None:
    replay, level = load_record(SUPPLIED)
    expected = trace_states()
    state = level.initial_state()

    for frame, x, y, vx, vy in expected[:111]:
        state.step(replay.frames[frame], level.tiles)
        player = state.player
        assert player.pos.x == pytest.approx(x, abs=1e-11)
        assert player.pos.y == pytest.approx(y, abs=1e-11)
        assert player.vx == pytest.approx(vx, abs=1e-11)
        assert player.vy == pytest.approx(vy, abs=1e-11)


def test_ditched_trace_matched_replay_matches_all_176_libtas_frames() -> None:
    replay, level = load_record(TRACE_MATCHED)
    expected = trace_states()
    state = level.initial_state()

    for frame, x, y, vx, vy in expected:
        state.step(replay.frames[frame], level.tiles)
        player = state.player
        assert player.pos.x == pytest.approx(x, abs=1e-11)
        assert player.pos.y == pytest.approx(y, abs=1e-11)
        assert player.vx == pytest.approx(vx, abs=1e-11)
        assert player.vy == pytest.approx(vy, abs=1e-11)


def test_supplied_replay_and_trace_first_disagree_at_frame_111() -> None:
    replay, level = load_record(SUPPLIED)
    expected = trace_states()
    state = level.initial_state()

    for frame in range(112):
        state.step(replay.frames[frame], level.tiles)
        _n, x, y, vx, vy = expected[frame]
        error = max(
            abs(state.player.pos.x - x),
            abs(state.player.pos.y - y),
            abs(state.player.vx - vx),
            abs(state.player.vy - vy),
        )
        if frame < 111:
            assert error < 1e-11
        else:
            assert error > 1e-3
            assert not replay.frames[frame].jump_trigger


def test_ditched_jump_pattern_search_finds_two_successful_jumps() -> None:
    replay, level = load_record(SUPPLIED)
    results = optimise_jump_patterns(
        level,
        replay.frames,
        target_frame=123,
        range_start=106,
        range_end=123,
        objective_name="min-x",
        jump_count_min=2,
        jump_count_max=2,
        top_results=3,
        progress=None,
    )

    assert results
    best = results[0]
    assert len(best.pulses) == 2
    assert best.pulses[0].end_frame + 2 <= best.pulses[1].start_frame

    modified = apply_jump_pattern(
        replay.frames,
        range_start=106,
        range_end=123,
        pulses=best.pulses,
    )
    state = state_before_frame(level, modified, 106)
    before_events = state.player.jump_events
    for frame_index in range(106, 124):
        state.step(modified[frame_index], level.tiles)

    assert state.player.jump_events - before_events == 2
    for before, after in zip(replay.frames, modified, strict=True):
        assert before.left == after.left
        assert before.right == after.right


def test_direction_only_search_prunes_paths_that_miss_required_jump_immediately() -> None:
    replay, level = load_record(SUPPLIED)
    logs: list[str] = []

    optimised, _result = optimise_local_windows(
        level,
        replay.frames,
        target_frame=137,
        range_start=132,
        range_end=137,
        objective_name="min-x",
        window_size=6,
        passes=1,
        local_inputs="direction",
        progress=logs.append,
    )

    search_line = next(line for line in logs if line.startswith("frames 132-137 search:"))
    nodes = int(search_line.split("nodes=", 1)[1].split(",", 1)[0])
    missed = int(search_line.split("missed-jump=", 1)[1].split(",", 1)[0])
    assert missed > 0
    # A full depth-6 ternary tree has 1,093 nodes. Missing frame-137 jumps
    # are rejected before their child node is entered.
    assert nodes < 1093
    assert successful_jump_frames(level, replay.frames, 137) <= successful_jump_frames(
        level, optimised, 137
    )

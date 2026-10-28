from __future__ import annotations

import csv
from pathlib import Path

import pytest

from nv14_engine import InputFrame, parse_level_string
from nv14_replay import decode_complex_replay, parse_combined_level_replay


HERE = Path(__file__).parent
FIXTURE = HERE / "example_44_0.txt"
TRACE_STATES = HERE / "44_0_libtas_states.csv"


def _load_44_0():
    combined = parse_combined_level_replay(FIXTURE.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string, simulate_enemies=True)
    return replay, level


def _trace_states():
    with TRACE_STATES.open(newline="", encoding="utf-8") as handle:
        return [
            (
                int(row["frame"]),
                float(row["x"]),
                float(row["y"]),
                float(row["vx"]),
                float(row["vy"]),
            )
            for row in csv.DictReader(handle)
        ]


def test_same_frame_bounce_wakes_preserve_live_collision_order() -> None:
    replay, level = _load_44_0()
    state = level.initial_state()

    for inputs in replay.frames[:331]:
        state.step(inputs, level.tiles)

    # On frame 330, collision traversal wakes bounce blocks UID 4 and then UID
    # 5. StartThink inserts each new thinker before curThinker and makes it
    # current, so the resulting ring must begin 5 -> 4. Reconstructing wake
    # events later by scanning the reverse-load-order object array produces the
    # incorrect 4 -> 5 order and eventually changes the blocks' sleep phases.
    assert state.thinker_uids[:4] == [5, 4, 122, 123]
    assert state.update_uids[:4] == [5, 4, 123, 122]


def test_44_0_matches_all_libtas_states_and_exits_on_first_neutral_tick() -> None:
    replay, level = _load_44_0()
    expected = _trace_states()
    state = level.initial_state()

    assert len(replay.frames) == 628
    assert [row[0] for row in expected] == list(range(629))

    for frame, x, y, vx, vy in expected:
        inputs = replay.frames[frame] if frame < len(replay.frames) else InputFrame()
        state.step(inputs, level.tiles)
        player = state.player
        assert player.dead is False
        assert player.pos.x == pytest.approx(x, abs=1e-10)
        assert player.pos.y == pytest.approx(y, abs=1e-10)
        assert player.vx == pytest.approx(vx, abs=1e-10)
        assert player.vy == pytest.approx(vy, abs=1e-10)

        if frame < 628:
            assert state.level_complete is False

    assert state.level_complete is True
    assert state.static_state.completed_exit_index == 0

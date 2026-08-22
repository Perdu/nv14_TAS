from __future__ import annotations

from pathlib import Path

import pytest

from nv14_engine import (
    AI_DIR_R,
    DRONEMOVE_SURFACEFOLLOW_CW,
    InputFrame,
    ObjectSpec,
    Player,
    TileMap,
    Vec2,
    ZapDrone,
    OBJTYPE_DRONE,
    parse_level_string,
)
from nv14_replay import decode_complex_replay, parse_combined_level_replay


FIXTURE = Path(__file__).with_name("example_74_1_zap.txt")


def _load_74_1():
    combined = parse_combined_level_replay(FIXTURE.read_text(encoding="utf-8"))
    level = parse_level_string(combined.level_string, simulate_enemies=True)
    frames = decode_complex_replay(combined.replay_string).frames
    return level, frames


def test_zap_drones_are_optional_and_do_not_join_targeting_thinker_ring() -> None:
    combined = parse_combined_level_replay(FIXTURE.read_text(encoding="utf-8"))

    level = parse_level_string(combined.level_string)
    assert not any(isinstance(obj, ZapDrone) for obj in level.objects)

    level = parse_level_string(combined.level_string, simulate_enemies=True)
    zaps = sorted(
        (obj for obj in level.objects if isinstance(obj, ZapDrone)),
        key=lambda obj: obj.load_index,
    )
    assert [obj.load_index for obj in zaps] == [5, 6, 7, 8, 89, 90, 91, 92]
    assert [obj.load_index for obj in zaps if obj.is_chaser] == [91, 92]
    assert level.initial_state().thinker_uids == []
    assert all(obj.r == pytest.approx(9.0) for obj in zaps)
    assert all(obj.speed == pytest.approx(12.0 / 7.0) for obj in zaps)


def test_74_1_zap_trace_matches_both_chaser_acquisitions_and_doubled_speed() -> None:
    level, frames = _load_74_1()
    state = level.initial_state()
    zaps = {
        obj.load_index: obj
        for obj in state.objects
        if isinstance(obj, ZapDrone)
    }

    for frame, inputs in enumerate(frames[:156]):
        state.step(inputs, level.tiles)

        if frame == 56:
            drone = zaps[92]
            assert drone.pos.x == pytest.approx(372.0, abs=1e-12)
            assert drone.pos.y == pytest.approx(420.0, abs=1e-12)
            assert drone.goal.x == pytest.approx(588.0, abs=1e-12)
            assert drone.goal.y == pytest.approx(420.0, abs=1e-12)
            assert drone.cur_dir == AI_DIR_R
            assert drone.is_chasing is True
            assert drone.ai_counter == 57
        elif frame == 57:
            # Chasing doubles the already doubled zap speed: 24/7 px/frame.
            drone = zaps[92]
            assert drone.pos.x == pytest.approx(375.428571428571, abs=1e-12)
            assert drone.is_chasing is True
        elif frame == 154:
            drone = zaps[91]
            assert drone.pos.x == pytest.approx(300.0, abs=1e-12)
            assert drone.pos.y == pytest.approx(180.0, abs=1e-12)
            assert drone.goal.x == pytest.approx(588.0, abs=1e-12)
            assert drone.goal.y == pytest.approx(180.0, abs=1e-12)
            assert drone.cur_dir == AI_DIR_R
            assert drone.is_chasing is True
            assert drone.ai_counter == 155
        elif frame == 155:
            drone = zaps[91]
            assert drone.pos.x == pytest.approx(303.428571428571, abs=1e-12)
            assert drone.is_chasing is True

    assert state.player.dead is False


def test_supplied_74_1_replay_matches_final_zap_states_and_survives() -> None:
    level, frames = _load_74_1()
    state = level.initial_state()
    for inputs in frames:
        state.step(inputs, level.tiles)
        assert state.player.dead is False

    expected = {
        5: (274.285714285714, 300.0, 252.0, 300.0, 2),
        6: (349.714285714286, 396.0, 372.0, 396.0, 0),
        7: (396.0, 358.285714285714, 396.0, 348.0, 3),
        8: (409.714285714286, 300.0, 420.0, 300.0, 0),
        89: (406.285714285714, 420.0, 396.0, 420.0, 2),
        90: (517.714285714286, 420.0, 540.0, 420.0, 0),
        91: (588.0, 348.0, 588.0, 372.0, 1),
        92: (462.857142857143, 180.0, 444.0, 180.0, 2),
    }
    for obj in state.objects:
        if not isinstance(obj, ZapDrone):
            continue
        x, y, gx, gy, direction = expected[obj.load_index]
        assert obj.pos.x == pytest.approx(x, abs=1e-12)
        assert obj.pos.y == pytest.approx(y, abs=1e-12)
        assert obj.goal.x == pytest.approx(gx, abs=1e-12)
        assert obj.goal.y == pytest.approx(gy, abs=1e-12)
        assert obj.cur_dir == direction
        assert obj.is_chasing is False
        assert obj.ai_counter == 338


def test_zap_contact_uses_strict_sum_of_radii_circle_test() -> None:
    tiles = TileMap("0" * (31 * 23))
    drone = ZapDrone.from_spec(
        ObjectSpec(OBJTYPE_DRONE, (300.0, 300.0, 2.0, 0.0, 0.0, 0.0), 0),
        tiles,
    )
    player = Player.spawn(300.0, 300.0)

    player.pos = Vec2(drone.pos.x + drone.r + player.r, drone.pos.y)
    player.dead = False
    drone.test_player(player)
    assert player.dead is False

    player.pos.x -= 1e-9
    drone.test_player(player)
    assert player.dead is True


def test_surface_chaser_restores_surface_following_after_chase() -> None:
    tiles = TileMap("0" * (31 * 23))
    drone = ZapDrone.from_spec(
        ObjectSpec(
            OBJTYPE_DRONE,
            (300.0, 300.0, float(DRONEMOVE_SURFACEFOLLOW_CW), 1.0, 0.0, 0.0),
            0,
        ),
        tiles,
    )
    player = Player.spawn(500.0, 300.0)

    # At its initial tile centre it sees the player on the same row, chases
    # right to the corridor wall, and records the clockwise surface-grab turn.
    drone.update(player, tiles, {})
    assert drone.is_chasing is True
    assert drone.surface_grab_pending is True
    assert drone.surface_future_dir == 3  # up
    assert drone.goal.x > player.pos.x

    # Put it within one base-speed step of the chase goal. Arrival invokes
    # Chase_SurfaceGrab and then GetNewGoal from the restored surface direction.
    drone.pos.x = drone.goal.x - 1.0
    cell = tiles.get_tile_xy(drone.pos.x, drone.pos.y)
    drone.cell_i = cell.i
    drone.cell_j = cell.j
    drone.update(player, tiles, {})
    assert drone.is_chasing is False
    assert drone.surface_grab_pending is False
    assert drone.cur_dir == 3
    assert drone.goal.y < drone.pos.y

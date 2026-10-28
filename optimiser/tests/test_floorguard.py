from __future__ import annotations

from pathlib import Path

import pytest

from nv14_engine import FloorGuard, Player, Vec2, parse_level_string
from nv14_replay import decode_complex_replay, parse_combined_level_replay


FIXTURE = Path(__file__).with_name("example_06_4_floorguards.txt")


def _load_06_4(*, simulate_enemies: bool = True):
    combined = parse_combined_level_replay(FIXTURE.read_text(encoding="utf-8"))
    level = parse_level_string(
        combined.level_string,
        simulate_enemies=simulate_enemies,
    )
    frames = decode_complex_replay(combined.replay_string).frames
    return level, frames


def _guards(state_or_level) -> dict[int, FloorGuard]:
    return {
        obj.load_index: obj
        for obj in state_or_level.objects
        if isinstance(obj, FloorGuard)
    }


def test_floorguards_are_optional_and_initialize_from_source_corridor_scans() -> None:
    level, _ = _load_06_4(simulate_enemies=False)
    assert not any(isinstance(obj, FloorGuard) for obj in level.objects)

    level, _ = _load_06_4(simulate_enemies=True)
    guards = _guards(level)
    assert sorted(guards) == [27, 30]

    upper = guards[27]
    assert (upper.pos.x, upper.pos.y) == pytest.approx((276.0, 210.0))
    assert (upper.cell_i, upper.cell_j) == (11, 8)
    assert upper.r == pytest.approx(6.0)
    assert upper.speed == pytest.approx(36.0 / 7.0)
    assert (upper.min_x, upper.max_x) == pytest.approx((126.0, 762.0))
    assert (upper.mini, upper.maxi) == (1, 31)
    assert upper.dir == 1
    assert upper.chasing is False

    lower = guards[30]
    assert (lower.pos.x, lower.pos.y) == pytest.approx((252.0, 570.0))
    assert (lower.cell_i, lower.cell_j) == (10, 23)
    assert (lower.min_x, lower.max_x) == pytest.approx((30.0, 762.0))
    assert (lower.mini, lower.maxi) == (1, 31)


def test_06_4_trace_matches_activation_movement_endpoint_and_reactivation() -> None:
    level, frames = _load_06_4()
    state = level.initial_state()
    guards = _guards(state)

    checkpoints = {
        # frame: uid -> (x, chasing, dir, cell_i)
        27: {30: (252.0, True, -1, 10)},
        28: {30: (246.857142857143, True, -1, 10)},
        30: {30: (236.571428571429, True, -1, 9)},
        71: {30: (30.0, False, -1, 1)},
        78: {30: (30.0, True, 1, 1)},
        79: {30: (35.1428571428571, True, 1, 1)},
        221: {30: (762.0, False, 1, 31)},
        320: {27: (276.0, True, -1, 11)},
        321: {27: (270.857142857143, True, -1, 11)},
        350: {27: (126.0, False, -1, 5)},
        380: {27: (126.0, True, 1, 5)},
        381: {27: (131.142857142857, True, 1, 5)},
    }

    for frame, inputs in enumerate(frames):
        state.step(inputs, level.tiles)
        for uid, expected in checkpoints.get(frame, {}).items():
            guard = guards[uid]
            x, chasing, direction, cell_i = expected
            assert guard.pos.x == pytest.approx(x, abs=1e-12)
            assert guard.chasing is chasing
            assert guard.dir == direction
            assert guard.cell_i == cell_i

    assert state.player.dead is False


def test_floorguard_contact_uses_strict_sum_of_radii_circle_test() -> None:
    level, _ = _load_06_4()
    guard = _guards(level)[30].clone()
    player = Player.spawn(guard.pos.x, guard.pos.y)

    player.pos = Vec2(guard.pos.x + guard.r + player.r, guard.pos.y)
    player.dead = False
    guard.test_player(player)
    assert player.dead is False

    player.pos.x -= 1e-9
    guard.test_player(player)
    assert player.dead is True


def test_activation_uses_stored_player_cell_and_same_column_stays_idle() -> None:
    level, _ = _load_06_4()
    guard = _guards(level)[30].clone()
    player = level.player.clone()

    # Position itself is deliberately irrelevant to Update_Idle: the source
    # checks the cell cached by the previous Player objects.Moved call.
    player.pos = Vec2(700.0, 100.0)
    player.cell_i = 3
    player.cell_j = 23
    guard.update(player, level.tiles)
    assert guard.chasing is True
    assert guard.dir == -1

    guard.chasing = False
    guard.pos.x = 252.0
    guard.cell_i = 10
    guard.cell_j = 23
    player.cell_i = 10
    player.cell_j = 23
    guard.update(player, level.tiles)
    assert guard.chasing is False


def test_floorguard_state_participates_in_clone_and_deduplication_key() -> None:
    level, _ = _load_06_4()
    state = level.initial_state()
    clone = state.clone()
    clone_guard = _guards(clone)[30]

    assert clone.state_key() == state.state_key()
    clone_guard.chasing = True
    clone_guard.dir = -1
    clone_guard.pos.x -= clone_guard.speed
    clone_guard.cell_i = 9
    assert clone.state_key() != state.state_key()

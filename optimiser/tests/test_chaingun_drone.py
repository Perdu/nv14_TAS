from __future__ import annotations

import pytest

from nv14_engine import (
    ChaingunDrone,
    DroneMode,
    InputFrame,
    LaserDrone,
    ObjectSpec,
    Player,
    TileMap,
    Vec2,
    OBJTYPE_DRONE,
    parse_level_string,
)


def _wall_map() -> TileMap:
    # Full column whose right edge is x=168.  This reproduces the blocking
    # vertical face hit by the first traced 29-4 chaingun burst while keeping
    # the fixture independent of unrelated level geometry.
    columns = [("1" if i == 5 else "0") * 23 for i in range(31)]
    return TileMap("".join(columns))


def _patrol_drone(tiles: TileMap) -> ChaingunDrone:
    return ChaingunDrone.from_spec(
        ObjectSpec(OBJTYPE_DRONE, (660.0, 108.0, 1.0, 0.0, 2.0, 2.0), 28),
        tiles,
    )


def test_chaingun_drone_is_optional_and_shares_targeting_thinker_ring() -> None:
    empty_map = "0" * (31 * 23)
    objects = "|5^300,300!6^660,108,1,0,2,2!6^132,108,1,0,2,2!6^180,300,0,0,1,1"

    level = parse_level_string(empty_map + objects)
    assert not any(isinstance(obj, (ChaingunDrone, LaserDrone)) for obj in level.objects)
    assert level.initial_state().thinker_uids == []

    level = parse_level_string(empty_map + objects, simulate_enemies=True)
    assert sorted(
        obj.load_index for obj in level.objects if isinstance(obj, ChaingunDrone)
    ) == [1, 2]
    assert [
        obj.load_index for obj in level.objects if isinstance(obj, LaserDrone)
    ] == [3]
    # StartThink inserts each newly initialized drone at the head.
    assert level.initial_state().thinker_uids == [3, 2, 1]


def test_chaingun_speed_matches_patrol_trace_before_first_turn() -> None:
    tiles = TileMap("0" * (31 * 23))
    drone = _patrol_drone(tiles)
    player = Player.spawn(660.0, 564.0)

    # Once its next goal is selected, the trace advances by
    # 12/14 * 0.75 pixels per frame.  Eleven such updates produce frame 11's
    # traced x position.
    drone.goal = Vec2(636.0, 108.0)
    drone.cur_dir = 2
    for frame in range(11):
        drone.update(player, tiles, {}, frame)

    assert drone.pos.x == pytest.approx(652.928571428572, abs=1e-12)
    assert drone.pos.y == pytest.approx(108.0, abs=1e-12)


def test_chaingun_patrol_trace_lock_spread_shots_and_burst_end() -> None:
    tiles = _wall_map()
    drone = _patrol_drone(tiles)
    player = Player.spawn(660.0, 564.0)

    # Exact gameplay state visible to Think_TargetPlayer on trace frame 171.
    drone.pos = Vec2(551.785714285715, 108.0)
    drone.goal = Vec2(540.0, 108.0)
    drone.cur_dir = 2
    cell = tiles.get_tile_xy(drone.pos.x, drone.pos.y)
    drone.cell_i = cell.i
    drone.cell_j = cell.j
    player.pos = Vec2(400.521885195405, 400.695198059223)
    player.oldpos = Vec2(401.011984696405, 409.98455431208)

    assert drone.think(player, tiles, {}) is True
    assert drone.mode == DroneMode.PREFIRE
    assert drone.view.x == pytest.approx(405.112995483897, abs=2e-12)
    assert drone.view.y == pytest.approx(391.811409097359, abs=3e-12)

    # The acquisition frame itself has timer 0.  Updates 172..205 bring it to
    # 34; frame 206 is the 35th prefire update and locks the current aim.
    for frame in range(172, 206):
        drone.update(player, tiles, {}, frame)
    player.pos = Vec2(369.172963643813, 192.937322061808)
    player.oldpos = Vec2(367.095519101023, 197.830134112671)
    drone.update(player, tiles, {}, 206)

    assert drone.mode == DroneMode.FIRING
    assert drone.chaingun_max_num == 5
    assert drone.chaingun_spread == pytest.approx(0.4, abs=1e-15)
    assert drone.targ.x == pytest.approx(-0.906718911364262, abs=4e-16)
    assert drone.targ.y == pytest.approx(0.421735480810434, abs=1e-15)
    assert drone.targ2.x == pytest.approx(-0.421735480810434, abs=1e-15)
    assert drone.targ2.y == pytest.approx(-0.906718911364262, abs=4e-16)

    shots = {
        212: (382.673914233714, 165.107322646232, 380.132842929205, 169.567508440372, 389.445936588224),
        218: (398.860870337731, 139.783728397611, 395.883303640333, 143.836605158937, 345.836480222317),
        224: (417.576647314469, 117.193614860034, 414.188128869362, 120.614268252293, 305.533948042749),
        230: (438.673258944266, 100.474200299387, 434.897837586328, 102.816879807196, 268.175932544232),
        236: (462.011379138924, 89.9999899348428, 457.87169636881, 91.3277784288678, 233.451115164405),
        242: (487.45983515211, 85.4055153498838, 482.97720749324, 85.7778041006264, 201.090570185002),
    }

    for frame in range(207, 249):
        traced = shots.get(frame)
        if traced is not None:
            x, y, old_x, old_y, _expected_y = traced
            player.pos = Vec2(x, y)
            player.oldpos = Vec2(old_x, old_y)
        drone.update(player, tiles, {}, frame)
        if traced is not None:
            expected_shot_index = (frame - 212) // 6 + 1
            assert drone.chaingun_cur_num == expected_shot_index
            assert drone.view.x == pytest.approx(168.0, abs=3e-13)
            assert drone.view.y == pytest.approx(traced[4], abs=6e-12)
            assert player.dead is False

    # maxNum=5 produces shots 0..5, then one more complete six-frame wait.
    assert drone.chaingun_cur_num == 6
    assert drone.mode == DroneMode.POSTFIRE
    assert drone.fire_delay_timer == 0

    for frame in range(249, 308):
        assert drone.update(player, tiles, {}, frame) is False
    assert drone.mode == DroneMode.POSTFIRE
    assert drone.fire_delay_timer == 59
    assert drone.update(player, tiles, {}, 308) is True
    assert drone.mode == DroneMode.MOVING
    assert drone.fire_delay_timer == 60


def test_chaingun_game_time_controls_burst_size_and_spread() -> None:
    tiles = TileMap("0" * (31 * 23))
    player = Player.spawn(300.0, 200.0)
    player.oldpos = Vec2(295.0, 200.0)

    expected = {
        206: (5, 0.4),
        354: (8, 0.2),
        510: (4, 0.2),
    }
    for game_time, (max_num, spread) in expected.items():
        drone = _patrol_drone(tiles)
        drone.pos = Vec2(551.0, 108.0)
        drone._fire_chaingun(player, game_time)
        assert drone.chaingun_max_num == max_num
        assert drone.chaingun_spread == pytest.approx(spread, abs=1e-15)


def test_chaingun_hit_kills_before_player_tick() -> None:
    empty_map = "0" * (31 * 23)
    level_string = empty_map + "|5^300,300!6^540,300,1,0,2,2"
    level = parse_level_string(level_string, simulate_enemies=True)
    state = level.initial_state()
    drone = next(obj for obj in state.objects if isinstance(obj, ChaingunDrone))

    # Force a firing state whose first bullet points directly through the ninja.
    drone.mode = DroneMode.FIRING
    drone.chaingun_timer = 5
    drone.chaingun_max_num = 4
    drone.chaingun_cur_num = 2
    drone.chaingun_spread = 0.2
    drone.targ = Vec2(-1.0, 0.0)
    drone.targ2 = Vec2(0.0, 1.0)
    state.player.pos = Vec2(400.0, 300.0)
    state.player.oldpos = Vec2(399.0, 300.0)
    before = state.player.pos.copy()

    state.step(InputFrame(right=True), level.tiles)
    assert state.player.dead is True
    # ObjectManager.Tick kills before Player.Tick, so input cannot move the ninja.
    assert state.player.pos.x == before.x
    assert state.player.pos.y == before.y
    assert drone.mode == DroneMode.POSTFIRE
    assert drone.chaingun_cur_num == 3

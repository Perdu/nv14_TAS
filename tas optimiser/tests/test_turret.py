from __future__ import annotations

from pathlib import Path

import pytest

from nv14_engine import (
    ObjectSpec,
    Player,
    Turret,
    TurretMode,
    TileMap,
    Vec2,
    OBJTYPE_TURRET,
    parse_level_string,
)
from nv14_replay import decode_complex_replay, parse_combined_level_replay


FIXTURE = Path(__file__).with_name("example_28_3_turrets.txt")


def _load_28_3(*, simulate_enemies: bool = True):
    combined = parse_combined_level_replay(FIXTURE.read_text(encoding="utf-8"))
    level = parse_level_string(
        combined.level_string,
        simulate_enemies=simulate_enemies,
    )
    frames = decode_complex_replay(combined.replay_string).frames
    return level, frames


def _turrets(state_or_level) -> dict[int, Turret]:
    return {
        obj.load_index: obj
        for obj in state_or_level.objects
        if isinstance(obj, Turret)
    }



def test_28_3_full_replay_uses_new_slope_families_in_strict_mode(monkeypatch) -> None:
    level, frames = _load_28_3()
    state = level.initial_state()
    reached_tile_ids: set[int] = set()
    original = TileMap._resolve_circle_tile

    def recording_resolve(self, x, y, o_h, o_v, player, tile):
        if 14 <= tile.tile_id <= 29:
            reached_tile_ids.add(tile.tile_id)
        return original(self, x, y, o_h, o_v, player, tile)

    monkeypatch.setattr(TileMap, "_resolve_circle_tile", recording_resolve)

    # These checkpoints include the first traced contacts with tile 17.
    traced_positions = {
        49: (535.845970243725, 497.036998503365),
        50: (530.908638202177, 499.326106498123),
        51: (526.020679481044, 501.742323412933),
        52: (521.082600347123, 504.284378158595),
        53: (516.193902004541, 506.951012356801),
        54: (511.255090645385, 509.740980213024),
    }

    for frame, inputs in enumerate(frames):
        state.step(inputs, level.tiles)
        assert state.player.dead is False
        expected = traced_positions.get(frame)
        if expected is not None:
            assert state.player.pos.x == pytest.approx(expected[0], abs=1e-12)
            assert state.player.pos.y == pytest.approx(expected[1], abs=1e-12)

    # The real replay reaches one or more orientations from every newly ported
    # slope family: 22.5-small/big and 67.5-small/big.
    assert {17, 21, 22, 27} <= reached_tile_ids


def test_all_half_tile_orientations_project_the_player() -> None:
    # Put each half tile at the first interior map cell and place the ninja at
    # its centre. ProjCircle_Half should move the circle exactly one radius in
    # the tile normal direction for this symmetric central-overlap case.
    for tile_id in (30, 31, 32, 33):
        tiles = TileMap(chr(48 + tile_id) + "0" * (31 * 23 - 1))
        tile = tiles.get(1, 1)
        player = Player.spawn(tile.pos.x, tile.pos.y)

        result = tiles._resolve_circle_tile(
            tile.xw + player.r,
            tile.yw + player.r,
            0,
            0,
            player,
            tile,
        )

        assert result != 0
        assert player.pos.x == pytest.approx(tile.pos.x + tile.signx * player.r)
        assert player.pos.y == pytest.approx(tile.pos.y + tile.signy * player.r)

def test_turrets_are_optional_and_initialize_in_source_thinker_order() -> None:
    level, _ = _load_28_3(simulate_enemies=False)
    assert not any(isinstance(obj, Turret) for obj in level.objects)
    assert level.initial_state().thinker_uids == []

    level, _ = _load_28_3()
    turrets = _turrets(level)
    assert sorted(turrets) == [14, 15, 16, 17]
    assert (turrets[14].pos.x, turrets[14].pos.y) == pytest.approx((288.0, 168.0))
    assert (turrets[15].pos.x, turrets[15].pos.y) == pytest.approx((480.0, 360.0))
    assert (turrets[16].pos.x, turrets[16].pos.y) == pytest.approx((504.0, 168.0))
    assert (turrets[17].pos.x, turrets[17].pos.y) == pytest.approx((288.0, 336.0))
    # StartThink inserts each newly initialized turret at the head.
    state = level.initial_state()
    assert state.thinker_uids == [17, 16, 15, 14]
    assert state.turret_update_uids == []
    assert level.passive_thinker_uids == ()


def test_28_3_first_four_acquisitions_and_dynamic_update_order_match_trace() -> None:
    level, frames = _load_28_3()
    state = level.initial_state()
    turrets = _turrets(state)

    for frame, inputs in enumerate(frames[:100]):
        state.step(inputs, level.tiles)
        assert state.player.dead is False

        if frame == 79:
            assert state.turret_update_uids == [14]
            assert turrets[14].mode == TurretMode.TARGETING
            assert turrets[14].aim.x == pytest.approx(288.0, abs=1e-12)
            assert turrets[14].aim.y == pytest.approx(168.0, abs=1e-12)
            assert turrets[14].shot_timer == 60.0
        elif frame == 87:
            # UID 16 is a later StartUpdate insertion, so it enumerates before
            # the already-targeting UID 14 on subsequent object ticks.
            assert state.turret_update_uids == [16, 14]
            assert turrets[16].mode == TurretMode.TARGETING
            assert turrets[14].aim.x == pytest.approx(311.663241841736, abs=7e-13)
            assert turrets[14].aim.y == pytest.approx(245.952443861361, abs=7e-13)
        elif frame == 91:
            assert state.turret_update_uids == [15, 16, 14]
            assert turrets[15].mode == TurretMode.TARGETING
            assert turrets[16].aim.x == pytest.approx(491.44428863385, abs=7e-13)
            assert turrets[16].aim.y == pytest.approx(206.344550070085, abs=7e-13)
            assert turrets[14].aim.x == pytest.approx(321.16993953763, abs=7e-13)
            assert turrets[14].aim.y == pytest.approx(275.355288142477, abs=7e-13)
        elif frame == 99:
            assert state.turret_update_uids == [17, 15, 16, 14]
            assert all(turrets[uid].mode == TurretMode.TARGETING for uid in turrets)
            assert turrets[15].aim.x == pytest.approx(458.81989255166, abs=7e-13)
            assert turrets[15].aim.y == pytest.approx(383.41945593987, abs=7e-13)
            assert turrets[16].aim.x == pytest.approx(467.789277771928, abs=7e-13)
            assert turrets[16].aim.y == pytest.approx(262.993017415888, abs=7e-13)
            assert turrets[14].aim.x == pytest.approx(334.33788738519, abs=7e-13)
            assert turrets[14].aim.y == pytest.approx(317.07972511002, abs=7e-13)


def test_frame_147_target_update_matches_source_and_starts_prefire() -> None:
    level, _ = _load_28_3()
    turret = _turrets(level)[17].clone()
    turret.mode = TurretMode.TARGETING
    turret.aim = Vec2(272.525755937622, 373.151818535434)
    turret.aim_speed = 0.035
    turret.shot_timer = 1.5

    # Source frame 147: predicted = 2*pos-oldpos.
    player = Player.spawn(235.826630031338, 354.315505592393)
    player.oldpos = Vec2(232.567333383107, 357.474802240624)

    action = turret.update(player, level.tiles, {}, 147)
    assert action == "end_think"
    assert turret.mode == TurretMode.PREFIRE
    assert turret.aim.x == pytest.approx(271.35536191359, abs=7e-13)
    assert turret.aim.y == pytest.approx(372.38197219974, abs=7e-13)
    assert turret.aim_speed == pytest.approx(0.05, abs=1e-15)
    # Near-band decrement is 1 + GetTime()%2 = 2 on frame 147; the strict
    # shotTimer < 0 test then resets the timer before StartFiring.
    assert turret.shot_timer == 60.0
    assert turret.fire_delay_timer == 0


def test_inner_band_preserves_previous_aim_speed() -> None:
    level, _ = _load_28_3()
    turret = _turrets(level)[17].clone()
    turret.mode = TurretMode.TARGETING
    turret.aim = Vec2(314.135964764296, 370.14612009666)
    turret.aim_speed = 0.05
    turret.shot_timer = 46.0

    # Source frame 118 inner-band state.
    player = Player.spawn(319.651686353833, 386.86739691112)
    player.oldpos = Vec2(323.375440761448, 388.908730779333)
    assert turret.update(player, level.tiles, {}, 118) is None
    assert turret.mode == TurretMode.TARGETING
    assert turret.aim.x == pytest.approx(314.225563123392, abs=7e-13)
    assert turret.aim.y == pytest.approx(370.880117243972, abs=7e-13)
    # The source has no assignment to aimSpeed in the inner branch.
    assert turret.aim_speed == pytest.approx(0.05, abs=1e-15)
    assert turret.shot_timer == 42.0


@pytest.mark.parametrize(
    "uid,aim,player_pos,expected_target",
    [
        (
            17,
            (271.35536191359, 372.38197219974),
            (271.017955351082, 346.516336976747),
            (242.799526662011, 434.799526662011),
        ),
        (
            15,
            (306.675333655428, 360.050821623556),
            (386.461325776474, 373.031849763249),
            (216.0, 360.077409112631),
        ),
        (
            16,
            (292.4017552625, 263.259203658529),
            (358.263424983508, 287.627040516329),
            (206.107795641231, 302.107795641231),
        ),
        (
            15,
            (299.222739477369, 275.685478071164),
            (377.826573018021, 297.499241566697),
            (222.710143324711, 240.0),
        ),
    ],
)
def test_28_3_locked_fire_rays_match_all_traced_shots(
    uid: int,
    aim: tuple[float, float],
    player_pos: tuple[float, float],
    expected_target: tuple[float, float],
) -> None:
    level, _ = _load_28_3()
    turret = _turrets(level)[uid].clone()
    turret.aim = Vec2(*aim)
    player = Player.spawn(*player_pos)

    # All four shots in the supplied trace miss the moving ninja and terminate
    # at these exact tile intersections. This exercises QueryRayObj using the
    # locked aim point rather than the player's current position.
    assert turret._fire(player, level.tiles, {}) is False
    assert player.dead is False
    assert turret.targ.x == pytest.approx(expected_target[0], abs=1e-12)
    assert turret.targ.y == pytest.approx(expected_target[1], abs=1e-12)


def test_prefire_and_postfire_are_ten_updates_and_restore_thinker_state() -> None:
    # Simple open fixture with one blocking outer border lets us exercise the
    # callback-state machine independently of 28-3's level geometry.
    level = parse_level_string(
        "0" * (31 * 23) + "|5^180,120!3^120,120",
        simulate_enemies=True,
    )
    state = level.initial_state()
    turret = _turrets(state)[1]
    player = state.player

    # Force the same state reached immediately after StartFiring while keeping
    # the locked ray away from the current player so Fire() is non-lethal.
    turret.mode = TurretMode.PREFIRE
    turret.aim = Vec2(120.0, 200.0)
    turret.shot_timer = 60.0
    state.turret_update_uids = [1]
    state.end_think(1)

    for frame in range(9):
        assert turret.update(player, level.tiles, {}, frame) is None
        assert turret.mode == TurretMode.PREFIRE
    assert turret.fire_delay_timer == 9

    assert turret.update(player, level.tiles, {}, 9) == "start_think"
    assert turret.mode == TurretMode.POSTFIRE
    assert turret.fire_delay_timer == 0

    # Mirror SimulationState's StartThink side effect for this direct update.
    state.start_think(1)
    for frame in range(10, 19):
        assert turret.update(player, level.tiles, {}, frame) is None
        assert turret.mode == TurretMode.POSTFIRE
    assert turret.fire_delay_timer == 9

    # Player remains visible, so postfire expiry is KeepTargetting: update stays
    # active, shot timer resets, aim/aimSpeed are preserved, and Think remains.
    assert turret.update(player, level.tiles, {}, 19) is None
    assert turret.mode == TurretMode.TARGETING
    assert turret.fire_delay_timer == 10
    assert turret.shot_timer == 60.0
    assert 1 in state.thinker_uids


def test_locked_turret_ray_kills_player_on_direct_hit() -> None:
    level = parse_level_string(
        "0" * (31 * 23) + "|5^180,120!3^120,120",
        simulate_enemies=True,
    )
    turret = _turrets(level)[1].clone()
    turret.aim = Vec2(200.0, 120.0)
    player = level.player.clone()

    assert turret._fire(player, level.tiles, {}) is True
    assert player.dead is True
    # QueryRayObj reports the circle entry point (player centre x=180, r=10).
    assert turret.targ.x == pytest.approx(170.0, abs=1e-12)
    assert turret.targ.y == pytest.approx(120.0, abs=1e-12)

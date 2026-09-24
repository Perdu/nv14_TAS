"""Enemy aftermath from the dump's IdleAfterDeath callbacks (AS lines 7770–9066)."""
import pytest
import nv14_engine as e


def level_with(objects):
    return e.parse_level_string('0' * 713 + '|5^60,70!' + objects, simulate_enemies=True)


def test_idle_callbacks_keep_moving_enemies_but_disable_reacquisition_and_triggers():
    level = level_with('3^300,108!4^350,108,1!9^400,108,0,0,8,4,1,0,0!'
                       '8^450,108,2!10^500,108!6^550,108,2,1,0,2!'
                       '6^600,108,2,0,1,2!6^650,108,2,0,2,2')
    state = level.initial_state()
    turret, guard, door, thwomp, rocket, zap, laser, chain = (state.objects_by_uid[i] for i in range(1, 9))
    turret.mode = e.TurretMode.TARGETING
    state.start_update(turret.load_index)
    guard.chasing = True
    thwomp.start_fall()
    zap.is_chasing = True
    laser.mode = e.DroneMode.PREFIRE
    state.end_think(laser.load_index)
    chain.mode = e.DroneMode.FIRING
    state.end_think(chain.load_index)
    original = state.clone(copy_on_write_objects=True)
    state.player.dead = True
    state._idle_after_death()
    turret, guard, door, thwomp, rocket, zap, laser, chain = (state.objects_by_uid[i] for i in range(1, 9))
    assert turret.mode == e.TurretMode.WAITING
    assert turret.load_index not in state.update_uids + state.thinker_uids
    assert not guard.chasing and guard.load_index not in state.update_uids
    assert state.grid_state.object_cells[door.load_index] is None
    assert thwomp.is_moving and thwomp.waiting_disabled
    assert rocket.load_index not in state.thinker_uids
    assert zap.is_chaser and not zap.is_chasing and zap.chase_disabled
    assert laser.mode == e.DroneMode.PREFIRE  # isFiring remains false during prefire
    assert chain.mode == e.DroneMode.POSTFIRE and chain.fire_delay_timer == 0
    assert original.objects_by_uid[1].mode == e.TurretMode.TARGETING
    assert original.objects_by_uid[2].chasing and original.objects_by_uid[6].is_chasing
    # A moving thwomp finishes its outward/return motion, then cannot reactivate.
    for _ in range(1000):
        thwomp.update(state.player)
    assert thwomp.mode == 2 and not thwomp.is_moving
    assert (thwomp.pos.x, thwomp.pos.y) == (thwomp.anchor.x, thwomp.anchor.y)
    clone = state.clone()
    assert clone.state_key() == state.state_key()
    assert clone.objects_by_uid[6].chase_disabled and clone.objects_by_uid[4].waiting_disabled


def test_null_drone_think_keeps_round_robin_place_after_revive():
    level = level_with('6^300,108,2,0,1,2!6^350,108,2,0,2,2')
    state = level.initial_state()
    ring = state.thinker_uids.copy()
    state.player.dead = True
    state._idle_after_death()
    state.player.fall()
    assert not state.player.dead
    for _ in range(20):
        state.think_timer = state.think_rate + 1
        state._tick_thinker(level.tiles)
    assert set(state.thinker_uids) == set(ring)
    assert all(o.mode == e.DroneMode.MOVING for o in state.objects)


def test_active_homing_explosion_does_not_restart_thinker_after_revive():
    level = level_with('10^60,60')
    state = level.initial_state()
    rocket = state.objects[0]
    rocket._fire_missile(state.player, level.tiles)
    state.end_think(rocket.load_index)
    state.start_update(rocket.load_index)
    state.grid_state.add(state.object_ref_slots[rocket.load_index], (rocket.cell_i, rocket.cell_j))
    state.player.dead = True
    state._idle_after_death()
    state.player.fall()
    # Move the active missile into the solid left map border on its next update.
    rocket.pos.x, rocket.pos.y = 24.1, 60.0
    rocket.mdir.x, rocket.mdir.y = -1.0, 0.0
    rocket.speed = rocket.maxspeed
    state.step(e.InputFrame(), level.tiles)
    assert rocket.mode == e.HomingMode.IDLE
    assert rocket.load_index not in state.thinker_uids + state.update_uids


@pytest.mark.parametrize('rocket_y,explodes', [(90.0, False), (76.0, True)])
def test_later_cell_rocket_only_explodes_on_actual_contact_after_death(rocket_y, explodes):
    level = level_with(f'12^60,70!10^60,{rocket_y}')
    state = level.initial_state()
    rocket = state.objects_by_uid[2]
    rocket._fire_missile(state.player, level.tiles)
    rocket.pos = e.Vec2(60.0, rocket_y)
    rocket.mdir = e.Vec2(1.0, 0.0)
    rocket.speed = rocket.curaccel = 0.0
    rocket.cell_i, rocket.cell_j = 2, 3
    state.end_think(rocket.load_index)
    state.start_update(rocket.load_index)
    ref = state.object_ref_slots[rocket.load_index]
    state.grid_state.add(ref, (2, 3))
    state.step(e.InputFrame(), level.tiles)
    assert state.player.dead
    assert (rocket.mode == e.HomingMode.IDLE) == explodes
    assert (ref not in state.grid_state.membership) == explodes
    assert (rocket.load_index not in state.update_uids) == explodes


@pytest.mark.parametrize('descriptor', [
    '3^300,108', '4^350,108,1', '8^60,108,0', '10^500,108',
    '6^550,108,2,1,0,2', '6^600,108,2,0,1,2', '6^650,108,2,0,2,2',
])
def test_death_then_pad_enemy_aftermath_matches_native(descriptor):
    native = pytest.importorskip('_nv14_native')
    text = '0' * 713 + '|5^60,70!12^60,70!2^60,72,0,-1!' + descriptor
    level = e.parse_level_string(text, simulate_enemies=True)
    py = level.initial_state()
    c = native.parse_level_string(text, simulate_enemies=True).initial_state()
    for _ in range(30):
        py.step(e.InputFrame(), level.tiles)
        c.step(e.InputFrame())
        cp = c.player_snapshot()
        assert cp['dead'] == py.player.dead
        assert cp['pos'] == pytest.approx((py.player.pos.x, py.player.pos.y))
        obj = py.objects_by_uid[3]
        scene = next(item for item in c.scene_snapshot()['objects'] if item['load_index'] == 3)
        pos = obj.basepos if isinstance(obj, e.HomingLauncher) else obj.pos
        assert (scene['x'], scene['y']) == pytest.approx((pos.x, pos.y))
        if hasattr(obj, 'mode'):
            assert scene['mode'] == obj.mode

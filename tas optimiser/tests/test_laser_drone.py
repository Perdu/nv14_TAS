from __future__ import annotations

import pytest

from nv14_engine import (
    BounceBlock,
    DroneMode,
    InputFrame,
    LaserDrone,
    parse_level_string,
)
from nv14_replay import decode_complex_replay


HALLOWED_LEVEL = (
    "11100011115000000000002150000021100011111000001000000011000115010000000000000010031100140000000000000100110001111110000000001002100000011100000000010001000000021000000000100011000000010000000001003114000000000000000010011111000000000000000100211500000000000000001000110000000000000000010001000000000000000001100010000000000000000311400100000000000000011111001000000000000000021150010000000000000000011000100000000000000000010001000000000000000000100011000000000000000001000114000000000000000010001111000000000000000100011500000000000000001000110000000000000000010001000000000000000000100310000000000000000001001100000000000000000010021000000000100000001100011000000011400000311000114000003111100011114031111000111"
    "|5^84,324!9^132,300,1,0,1,14,1,0,-1!9^252,300,1,0,1,15,1,0,-1!9^396,300,1,0,1,16,1,0,-1!9^540,300,1,0,1,17,1,0,-1!11^84,564,660,300!6^708,324,2,0,1,3!0^180,324!0^192,324!0^204,324!0^588,324!0^600,324!0^612,324"
)

HALLOWED_REPLAY = (
    "344:35791394|107880994|107374182|107374182|107374182|35808870|"
    "35791394|35791394|35791394|35791394|35791394|35791394|35791394|"
    "35791394|35791394|35791394|35791394|35791394|35791394|17965602|"
    "17895697|17830161|17895697|17895697|17895697|17895697|17895697|"
    "97587473|17895701|17895697|17895697|17895697|17895697|219222289|"
    "89478485|17896789|17895697|17895697|17895697|17895697|17895697|"
    "17895697|1118481|0|0|35782656|35791394|35791394|35791394|2"
)


def _set_player(state, x: float, y: float) -> None:
    state.player.pos.x = x
    state.player.pos.y = y
    state.player.oldpos.x = x
    state.player.oldpos.y = y
    state.player.dead = False


def test_enemy_simulation_is_optional() -> None:
    level = parse_level_string(HALLOWED_LEVEL)
    assert not any(isinstance(obj, LaserDrone) for obj in level.objects)
    assert level.initial_state().thinker_uids == []

    level = parse_level_string(HALLOWED_LEVEL, simulate_enemies=True)
    drone = next(obj for obj in level.objects if isinstance(obj, LaserDrone))
    assert drone.load_index == 6
    assert level.initial_state().thinker_uids == [6]


def test_laser_drone_matches_hallowed_trace_acquisition_and_beam_lock() -> None:
    level = parse_level_string(HALLOWED_LEVEL, simulate_enemies=True)
    state = level.initial_state()
    drone = next(obj for obj in state.objects if isinstance(obj, LaserDrone))

    # Player positions visible to ObjectManager.Tick() on the source Think frames.
    # These are the LASERDBG THINK player coordinates from the supplied libTAS trace.
    think_positions = {
        3: (84.29601, 324.894015),
        7: (86.1926994279199, 326.0),
        11: (90.3072189300892, 326.0),
        15: (96.4522019529402, 314.3278055),
        19: (103.963475930709, 303.509581935356),
        23: (112.73917374777, 293.51167944387),
        27: (122.729472059804, 284.301774102181),
    }

    for frame in range(28):
        _set_player(state, *think_positions.get(frame, (84.0, 100.0)))
        state.step(InputFrame(), level.tiles)

    assert drone.mode == DroneMode.PREFIRE
    assert state.thinker_uids == []
    assert state.think_timer == 0
    assert drone.pos.x == pytest.approx(708.0, abs=1e-12)
    assert drone.pos.y == pytest.approx(312.428571428571, abs=1e-12)
    assert drone.view.x == pytest.approx(132.717944276922, abs=1e-12)
    assert drone.view.y == pytest.approx(284.781797818119, abs=1e-12)
    assert drone.targ.x == pytest.approx(32.0558004915965, abs=1e-12)
    assert drone.targ.y == pytest.approx(279.944199508403, abs=1e-12)
    assert drone.targ2.x == pytest.approx(-675.944199508403, abs=2e-12)
    assert drone.targ2.y == pytest.approx(-32.4843719201675, abs=1e-12)
    assert drone.laser_len == pytest.approx(676.724312603075, abs=1e-12)


def test_laser_timing_reentry_and_second_acquisition_match_trace() -> None:
    level = parse_level_string(HALLOWED_LEVEL, simulate_enemies=True)
    state = level.initial_state()
    drone = next(obj for obj in state.objects if isinstance(obj, LaserDrone))

    think_positions = {
        3: (84.29601, 324.894015),
        7: (86.1926994279199, 326.0),
        11: (90.3072189300892, 326.0),
        15: (96.4522019529402, 314.3278055),
        19: (103.963475930709, 303.509581935356),
        23: (112.73917374777, 293.51167944387),
        27: (122.729472059804, 284.301774102181),
        180: (607.557146117698, 326.0),
        184: (594.713843080455, 326.0),
        188: (580.036020421658, 326.0),
        192: (563.595965534132, 326.0),
        196: (545.463117398992, 320.055),
    }

    snapshots: dict[int, tuple[DroneMode, int, tuple[int, ...]]] = {}
    for frame in range(197):
        _set_player(state, *think_positions.get(frame, (84.0, 100.0)))
        state.step(InputFrame(), level.tiles)
        if frame in (27, 57, 137, 177, 180, 196):
            snapshots[frame] = (drone.mode, state.think_timer, tuple(state.thinker_uids))

    assert snapshots[27] == (DroneMode.PREFIRE, 0, ())
    assert snapshots[57] == (DroneMode.FIRING, 0, ())
    assert snapshots[137] == (DroneMode.POSTFIRE, 0, ())
    assert snapshots[177] == (DroneMode.MOVING, 1, (6,))
    assert snapshots[180] == (DroneMode.MOVING, 0, (6,))
    assert snapshots[196] == (DroneMode.PREFIRE, 0, ())

    assert drone.pos.x == pytest.approx(708.0, abs=1e-12)
    assert drone.pos.y == pytest.approx(304.285714285714, abs=1e-12)
    assert drone.view.x == pytest.approx(555.416382921654, abs=1e-12)
    assert drone.view.y == pytest.approx(319.08933678987, abs=1e-12)
    assert drone.targ.x == pytest.approx(381.115115845243, abs=2e-12)
    assert drone.targ.y == pytest.approx(336.0, abs=1e-12)
    assert drone.targ2.x == pytest.approx(-326.884884154757, abs=2e-12)
    assert drone.targ2.y == pytest.approx(31.7142857142865, abs=2e-12)
    assert drone.laser_len == pytest.approx(328.419736628657, abs=2e-12)


def test_supplied_hallowed_replay_matches_both_acquisitions_and_survives() -> None:
    level = parse_level_string(HALLOWED_LEVEL, simulate_enemies=True)
    state = level.initial_state()
    drone = next(obj for obj in state.objects if isinstance(obj, LaserDrone))
    frames = decode_complex_replay(HALLOWED_REPLAY).frames

    for frame, inputs in enumerate(frames):
        state.step(inputs, level.tiles)
        if frame == 27:
            assert drone.mode == DroneMode.PREFIRE
            assert drone.targ.x == pytest.approx(32.0558004915965, abs=1e-12)
            assert drone.targ.y == pytest.approx(279.944199508403, abs=1e-12)
        elif frame == 196:
            assert drone.mode == DroneMode.PREFIRE
            assert drone.targ.x == pytest.approx(381.115115845243, abs=2e-12)
            assert drone.targ.y == pytest.approx(336.0, abs=1e-12)
        assert state.player.dead is False


def test_firing_laser_kills_before_player_tick() -> None:
    level = parse_level_string(HALLOWED_LEVEL, simulate_enemies=True)
    state = level.initial_state()
    drone = next(obj for obj in state.objects if isinstance(obj, LaserDrone))
    frames = decode_complex_replay(HALLOWED_REPLAY).frames

    # Reach the first firing state at the end of frame 57.
    for frame in range(58):
        state.step(frames[frame], level.tiles)
    assert drone.mode == DroneMode.FIRING

    # Put the player directly on the locked beam before objects.Tick() for the
    # next frame. Update_FiringLaser must kill immediately, before Player.Tick.
    _set_player(
        state,
        drone.pos.x + 0.5 * drone.targ2.x,
        drone.pos.y + 0.5 * drone.targ2.y,
    )
    before = state.player.pos.copy()
    state.step(InputFrame(right=True), level.tiles)
    assert state.player.dead is True
    assert state.player.pos.x == before.x
    assert state.player.pos.y == before.y


def test_bounceblock_uses_shared_thinker_scheduler() -> None:
    empty_map = "0" * (31 * 23)
    # Bounce block UID 0, player UID 1. The player starts intersecting it so
    # TestVsPlayer wakes it after the first frame's thinker phase.
    level = parse_level_string(f"{empty_map}|1^120,120!5^120,120")
    state = level.initial_state()
    block = next(obj for obj in state.objects if isinstance(obj, BounceBlock))

    state.step(InputFrame(), level.tiles)
    assert block.asleep is False
    assert state.thinker_uids == [0]
    assert state.think_timer == 0

    # Keep the player away. Think runs every fourth frame; the block first sees
    # sleepTimer > 40 at sleepTimer == 44 and then removes itself.
    for _ in range(44):
        _set_player(state, 300.0, 120.0)
        state.step(InputFrame(), level.tiles)

    assert block.asleep is True
    assert block.sleep_timer == 44
    assert state.thinker_uids == []
    assert state.think_timer == 0

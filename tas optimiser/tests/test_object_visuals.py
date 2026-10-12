"""Original object timelines, source drawing callbacks and query isolation."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import subprocess
import sys

import pytest

from nv14_object_visuals import ObjectVisualSystem, _Clip


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def manifest():
    return json.loads((ROOT / "nv14_assets/manifest.json").read_text())


def obj(kind, **changes):
    return {"id": 0, "kind": kind, "x": 100., "y": 100., "visible": True,
            "mode": 0, "direction_index": 0, "parameters": (), "is_open": False,
            "updating": True, "fire_delay_timer": 0, "weapon_timer": 0,
            "shot_index": 0, "aim": (100., 100.), "goal": (100., 100.),
            "rocket_x": 100., "rocket_y": 100., "rocket_visible": False,
            "beam_end": (300., 100.), **changes}


def scene(*objects, frame=0, **player):
    return {"frame": frame, "objects": list(objects), "static_state": {"level_complete": False},
            "player": {"pos": (500., 100.), "oldpos": (500., 100.), "dead": False,
                       "r": 10., "g": .15, "d": .99, **player}}


def next_scene(tracker, initial, **changes):
    result = deepcopy(initial)
    result["frame"] += 1
    result["objects"][0].update(changes)
    return result, tracker.update(result)[0]


def test_no_engine_import_or_optional_dependency_on_import():
    result = subprocess.run([sys.executable, "-c", "import sys; import nv14_object_visuals; "
        "assert 'nv14_engine' not in sys.modules; assert '_nv14_native' not in sys.modules; "
        "assert 'PIL' not in sys.modules"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_pack_validation_and_frame_validation(manifest):
    with pytest.raises(ValueError, match="v4.06"):
        ObjectVisualSystem({})
    tracker = ObjectVisualSystem(manifest)
    for value in (-1, True, 1.5):
        with pytest.raises(ValueError, match="non-negative integer"):
            tracker.advance(value)


def test_gold_lingers_then_hides_with_nominal_timeline_phase(manifest):
    tracker = ObjectVisualSystem(manifest)
    initial = scene(obj("gold"))
    assert tracker.reset(initial)[0].body.frame == 1
    current, record = next_scene(tracker, initial, visible=False)
    assert record.body.frame == 2 and record.body.visible
    untouched = deepcopy(current)
    current, aged = next_scene(tracker, current)
    assert aged.body.frame == 5
    assert record.body.frame == 2
    with pytest.raises(FrozenInstanceError):
        record.body.frame = 6
    assert tracker.update(current) == (aged,)
    assert untouched["objects"][0]["visible"] is False
    tracker.advance(25)
    assert not tracker.snapshot()[0].body.visible
    tracker.advance(50)
    assert not tracker.snapshot()[0].body.visible
    with pytest.raises(ValueError, match="consecutive"):
        tracker.update({**current, "frame": current["frame"] + 2})
    assert tracker.reset(initial)[0].body.visible


def test_exit_and_all_door_variants_reach_source_stop_frames(manifest):
    cases = [(obj("exit_door"), {"is_open": True}, 2, 31),
             (obj("testdoor"), {"is_open": True}, 2, 17),
             (obj("testdoor", is_locked=True), {"is_open": True}, 56, 74),
             (obj("testdoor", is_trap=True, is_open=True), {"is_open": False}, 36, 54)]
    for initial_obj, change, start, stop in cases:
        tracker = ObjectVisualSystem(manifest)
        initial = scene(initial_obj)
        tracker.reset(initial)
        _, record = next_scene(tracker, initial, **change)
        assert record.body.frame == start
        tracker.advance(100)
        assert tracker.snapshot()[0].body.frame == stop


def test_door_interruption_and_same_tick_close_reopen(manifest):
    tracker = ObjectVisualSystem(manifest)
    current = scene(obj("testdoor"))
    tracker.reset(current)
    current, record = next_scene(tracker, current, is_open=True, door_timer=0)
    assert record.body.frame == 2
    for timer in range(1, 6):
        current, record = next_scene(tracker, current, door_timer=timer)
    assert record.body.frame == 17
    current, record = next_scene(tracker, current, door_timer=0)
    assert record.body.frame == 2  # closed in Update, reopened in collision
    current, record = next_scene(tracker, current, is_open=False)
    assert record.body.frame == 18  # restart closing at its source label
    current, record = next_scene(tracker, current, is_open=True)
    assert record.body.frame == 2  # reopen interrupts partially closed artwork


def test_door_registration_and_trap_switch_source_scale(manifest):
    tracker = ObjectVisualSystem(manifest)
    variants = [(False, 0, 0, (107, 120, 0)), (False, -1, 0, (132, 120, 180)),
                (True, 0, 0, (120, 107, 90)), (True, 0, -1, (120, 132, 270))]
    for horizontal, di, dj, expected in variants:
        records = tracker.reset(scene(obj("testdoor", door_x=120, door_y=120,
            horizontal=horizontal, parameters=(0, 0, 0, 0, 0, 0, 0, di, dj))))
        body = records[0].body
        assert (body.x, body.y, body.rotation) == expected
    record = tracker.reset(scene(obj("testdoor", is_trap=True, is_open=True)))[0]
    assert record.trigger.scale_x == pytest.approx(2/3)
    assert record.trigger.frame == 1


def test_turret_crosshair_bands_retention_and_frozen_position(manifest):
    tracker = ObjectVisualSystem(manifest)
    current = scene(obj("turret", mode=1, crosshair_visible=True))
    tracker.reset(current)
    current, record = next_scene(tracker, current, aim=(120., 100.))
    assert record.crosshair.frame == 1  # old aim error > 96
    current["player"]["pos"] = current["player"]["oldpos"] = (170., 100.)
    tracker._previous = deepcopy(current)
    current, record = next_scene(tracker, current, aim=(122., 100.))
    assert record.crosshair.frame == 2  # error 50 => mid
    current["player"]["pos"] = current["player"]["oldpos"] = (155., 100.)
    tracker._previous = deepcopy(current)
    current, record = next_scene(tracker, current, aim=(124., 100.))
    assert record.crosshair.frame == 3  # error 33 => near
    current["player"]["pos"] = current["player"]["oldpos"] = (125., 100.)
    tracker._previous = deepcopy(current)
    current, record = next_scene(tracker, current, aim=(125., 100.))
    assert record.crosshair.frame == 3  # inner error preserves previous band
    current, record = next_scene(tracker, current, mode=2, aim=(130., 100.))
    assert record.body.frame == 2 and record.crosshair.frame == 4
    assert (record.crosshair.x, record.crosshair.y) == (125., 100.)
    current, record = next_scene(tracker, current, fire_delay_timer=9)
    current, record = next_scene(tracker, current, mode=3, fire_delay_timer=0)
    assert record.body.frame == 29 and record.crosshair.frame == 5
    assert record.crosshair.x == 125.  # StopFiring does not restart Draw
    current, record = next_scene(tracker, current, mode=1)
    assert record.crosshair.x == 130.


def test_turret_firing_source_action_is_synchronously_overwritten(manifest):
    tracker = ObjectVisualSystem(manifest)
    for terminal_mode in (0, 3):
        initial = scene(obj("turret", mode=2, fire_delay_timer=9, crosshair_visible=True))
        tracker.reset(initial)
        _, record = next_scene(tracker, initial, mode=terminal_mode, fire_delay_timer=0,
                               target=(510., 100.), crosshair_visible=bool(terminal_mode))
        assert record.body.frame == 29
        assert record.crosshair.frame == 5


def test_homing_fire_explode_jump_actions_and_rocket_clock(manifest):
    tracker = ObjectVisualSystem(manifest)
    current = scene(obj("homing", mode=1, fire_delay_timer=9))
    tracker.reset(current)
    current, record = next_scene(tracker, current, mode=2, rocket_visible=True)
    assert record.body.frame == 2 and record.rocket.frame == 4
    current, record = next_scene(tracker, current)
    assert record.body.frame == 4  # frame3 gotoAndStop rocket_active
    current, record = next_scene(tracker, current, mode=0, rocket_visible=False)
    assert record.body.frame == 8 and not record.rocket.visible
    tracker.advance(3)
    assert tracker.snapshot()[0].body.frame == 1
    # The unused activeB branch still honors the original gotoAndPlay loop.
    clip = _Clip("homing_launcher", manifest["object_animations"]["clips"]["homing_launcher"])
    clip.goto("rocket_activeB", True)
    clip.advance(2)
    assert clip.frame == 5 and clip.playing


def test_zap_retriggers_at_goal_and_eye_uses_literal_easing(manifest):
    tracker = ObjectVisualSystem(manifest)
    current = scene(obj("drone_zap", direction_index=2, parameters=(100, 100, 0, 1, 0, 2), speed=2.))
    record = tracker.reset(current)[0]
    assert record.body.frame == 3 and record.eye_rotation == 54.
    current, record = next_scene(tracker, current, chasing=True, direction_index=3)
    assert record.body.frame == 4 and record.eye_rotation == pytest.approx(10.8)
    current, record = next_scene(tracker, current)
    assert record.body.frame == 4  # chase renewal even with unchanged goal
    current, record = next_scene(tracker, current, x=110., goal=(130., 100.))
    current, record = next_scene(tracker, current)
    assert record.body.frame == 3  # frame5 returns to chaseidle while chasing
    frozen = record.eye_rotation
    tracker.advance(6)
    assert tracker.snapshot()[0].eye_rotation == frozen


def test_laser_prefire_postfire_blast_and_draw_position(manifest):
    tracker = ObjectVisualSystem(manifest)
    current = scene(obj("drone_laser", direction_index=1))
    initial = tracker.reset(current)[0]
    current, record = next_scene(tracker, current, mode=1, x=101.5)
    assert record.body.frame == 6 and record.body.x == 100.
    assert record.eye_rotation == initial.eye_rotation
    assert record.beam.visible and record.beam.width == 0 and record.beam.color == "#cb7579"
    tracker.advance(100)
    assert tracker.snapshot()[0].body.frame == 28
    current, record = next_scene(tracker, current, mode=2)
    assert record.body.frame == 29 and record.blast.frame == 1 and record.blast.visible
    assert record.blast.scale_x == 0 and record.beam.width == 3 and record.beam.color == "#882222"
    current, record = next_scene(tracker, current, weapon_timer=1)
    assert record.blast.frame == 4 and record.blast.scale_x == .3
    current, record = next_scene(tracker, current, weapon_timer=2)
    assert record.blast.scale_x == .325
    current, record = next_scene(tracker, current, mode=3)
    assert record.body.frame == 30 and not record.blast.visible and not record.beam.visible
    tracker.advance(100)
    assert tracker.snapshot()[0].body.frame == 51
    current, record = next_scene(tracker, current, mode=0)
    assert record.body.x == 101.5 and record.eye_rotation == pytest.approx(45.9)


def test_chaingun_prefire_eases_to_pre_tick_player_and_shot_snaps(manifest):
    tracker = ObjectVisualSystem(manifest)
    current = scene(obj("drone_chaingun"), pos=(100., 300.), oldpos=(100., 300.))
    tracker.reset(current)
    current, record = next_scene(tracker, current, mode=1)
    assert record.body.frame == 53 and record.eye_rotation == 0.
    following = deepcopy(current)
    following["frame"] += 1
    following["player"]["pos"] = (300., 100.)
    record = tracker.update(following)[0]
    assert record.body.frame == 54 and record.eye_rotation == 9.
    current, record = next_scene(tracker, following, mode=2)
    assert record.body.frame == 55 and record.eye_rotation == pytest.approx(8.1)
    current, record = next_scene(tracker, current, shot_visible=True, shot_index=1, beam_end=(100., 0.))
    assert record.body.frame == 56 and record.eye_rotation == -90.
    current, record = next_scene(tracker, current, mode=3, shot_visible=False)
    assert record.body.frame == 57
    current, record = next_scene(tracker, current)
    assert record.body.frame == 52 and record.eye_rotation == -90.


def test_real_launch_contact_gold_collection_and_native_key_are_unchanged(manifest):
    native = pytest.importorskip("_nv14_native")
    from nv14_engine import InputFrame
    text = "0" * 713 + "|5^100,100!0^100,100!2^100,110,0,-1"
    state = native.parse_level_string(text, simulate_enemies=True).initial_state(track_visuals=True)
    plain = state.clone()
    tracker = ObjectVisualSystem(manifest)
    initial = state.scene_snapshot()
    tracker.reset(initial)
    for _ in range(5):
        state.step(InputFrame())
        plain.step(InputFrame())
        query = state.scene_snapshot()
        untouched = deepcopy(query)
        records = tracker.update(query)
        assert query == untouched
        assert state.state_key() == plain.state_key()
        if query["frame"] == 1:
            assert {r.body.clip: r.body.frame for r in records} == {"launchpad": 2, "gold": 2}
            assert query["player"]["pos"][1] < 90
    key = state.state_key()
    tracker.advance(120)
    assert state.state_key() == key
    assert not next(r for r in tracker.snapshot() if r.body.clip == "gold").body.visible
    assert next(r for r in tracker.snapshot() if r.body.clip == "launchpad").body.frame == 20


def test_launch_backface_and_nearby_misses_do_not_trigger(manifest):
    tracker = ObjectVisualSystem(manifest)
    for player_pos in ((100., 80.), (100., 96.), (120., 100.)):
        current = scene(obj("launch", parameters=(100, 110, 0, -1), y=110., radius=6),
                        pos=player_pos, oldpos=player_pos)
        tracker.reset(current)
        current, record = next_scene(tracker, current)
        assert record.body.frame == 20


def test_collected_gold_can_skip_a_colocated_launch_in_same_collision_cell(manifest):
    native = pytest.importorskip("_nv14_native")
    from nv14_engine import InputFrame
    # Reverse loading order from the launch+gold test above: the gold is now
    # first in this grid cell's intrusive list. Removing it ends that traversal.
    state = native.parse_level_string("0" * 713 +
        "|5^100,100!2^100,110,0,-1!0^100,100").initial_state()
    tracker = ObjectVisualSystem(manifest)
    tracker.reset(state.scene_snapshot())
    state.step(InputFrame())
    query = state.scene_snapshot()
    records = tracker.update(query)
    assert query["player"]["pos"][1] == pytest.approx(100.15)
    assert {r.body.clip: r.body.frame for r in records} == {"launchpad": 20, "gold": 2}


def test_native_door_query_drives_the_full_open_close_sequence(manifest):
    native = pytest.importorskip("_nv14_native")
    from nv14_engine import InputFrame
    tiles = ["0"] * 713
    for column in range(31):
        tiles[column * 23 + 5] = "1"
    state = native.parse_level_string("".join(tiles) +
        "|5^100,134!9^120,134,0,0,4,5,0,0,0").initial_state()
    tracker = ObjectVisualSystem(manifest)
    tracker.reset(state.scene_snapshot(include_object_visuals=True))
    frames = []
    for _ in range(60):
        state.step(InputFrame(right=True))
        query = state.scene_snapshot(include_object_visuals=True)
        frames.append(tracker.update(query)[0].body.frame)
    assert all(frame in frames for frame in (2, 5, 8, 11, 14, 17, 18, 21, 24, 27, 30, 33, 34))

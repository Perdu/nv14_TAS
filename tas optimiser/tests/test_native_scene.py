"""Scene queries follow live native objects and cannot perturb gameplay."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from nv14_engine import (
    BounceBlock, ChaingunDrone, FloorGuard, HomingLauncher, InputFrame,
    LaserDrone, TestDoor as Door, Thwomp, Turret, parse_level_string,
)
from nv14_replay import decode_complex_replay, parse_combined_level_replay

native = pytest.importorskip("_nv14_native")
ROOT = Path(__file__).resolve().parents[1]
NEUTRAL = InputFrame()


def flat_level(objects="", *, x=100, y=134):
    tiles = ["0"] * 713
    for col in range(31):
        tiles[col * 23 + 5] = "1"
    return "".join(tiles) + f"|5^{x},{y}" + objects


def xy(vector):
    return vector.x, vector.y


def test_query_is_opt_in_read_only_and_preserves_old_snapshot_contract():
    level = native.parse_level_string(flat_level("!1^130,134"))
    state = level.initial_state()
    control = level.initial_state()
    assert native.backend_info()["scene_abi"] == 1
    for _ in range(60):
        before = state.state_key()
        scene = state.scene_snapshot()
        assert state.state_key() == before == control.state_key()
        assert state.scene_snapshot() == scene
        assert scene["visual"] is None
        assert not state.visuals_enabled
        assert set(state.snapshot()) == {"backend", "frame", "player", "static_state"}
        scene["objects"][0]["x"] = -100000  # returned data owns no native memory
        assert state.scene_snapshot()["objects"][0]["x"] != -100000
        assert state.step(InputFrame(right=True)) == control.step(InputFrame(right=True))
        assert state.player_snapshot() == control.player_snapshot()


def test_static_objects_have_stable_ids_and_exact_collection_open_visibility():
    level = native.parse_level_string(flat_level(
        "!0^100,134!12^400,134!11^300,134,100,134"
        "!7^500,100,3!2^600,100,0,-1"
    ))
    state = level.initial_state(track_visuals=True)
    before = state.scene_snapshot()
    identities = [(o["id"], o["kind"], o["load_index"]) for o in before["objects"]]
    assert len({o["id"] for o in before["objects"]}) == 6
    exit_objects = [o for o in before["objects"] if o["type"] == 11]
    assert len(exit_objects) == 2
    assert exit_objects[0]["load_index"] == exit_objects[1]["load_index"]
    state.step(NEUTRAL)
    # Consecutive colocated triggers may be skipped on a self-removal tick.
    state.step(NEUTRAL)
    after = state.scene_snapshot()
    assert identities == [(o["id"], o["kind"], o["load_index"]) for o in after["objects"]]
    objects = {o["kind"]: o for o in after["objects"]}
    assert not objects["gold"]["visible"] and not objects["gold"]["active"]
    assert objects["mine"]["visible"]
    assert objects["exit_switch"]["is_open"]
    assert not objects["exit_switch"]["active"]
    assert objects["exit_switch"]["visible"]  # source keeps the open switch art
    assert objects["exit_door"]["is_open"] and objects["exit_door"]["visible"]
    assert objects["oneway"]["direction"] == (0.0, -1.0)
    assert objects["launch"]["direction"] == (0.0, -1.0)
    assert after["visual"] == state.visual_snapshot()
    assert after["static_state"] == state.static_state()
    assert state.clone().scene_snapshot() == after


@pytest.mark.parametrize("descriptor", [
    "!1^125,134", "!8^300,108,2", "!9^120,134,0,0,8,4,1,0,0",
    "!9^120,134,1,1,8,4,0,0,0", "!9^120,134,0,0,4,4,0,0,0",
    "!4^300,132,1", "!3^300,108", "!10^300,108",
    "!6^300,108,2,0,0,2", "!6^300,108,2,0,1,2",
    "!6^300,108,2,0,2,2",
])
def test_dynamic_scene_matches_reference_object_state(descriptor):
    text = flat_level(descriptor)
    level = parse_level_string(text, simulate_enemies=True)
    reference = level.initial_state()
    state = native.parse_level_string(text, simulate_enemies=True).initial_state()
    for tick in range(150):
        scene = state.scene_snapshot()
        obj = next(o for o in scene["objects"] if o["load_index"] == 1)
        expected = reference.objects_by_uid[1]
        position = expected.basepos if isinstance(expected, HomingLauncher) else expected.pos
        assert (obj["x"], obj["y"]) == pytest.approx(xy(position), abs=1e-10)
        if hasattr(expected, "mode"):
            assert obj["mode"] == expected.mode
        if isinstance(expected, BounceBlock):
            assert (obj["old_x"], obj["old_y"]) == pytest.approx(xy(expected.oldpos))
            assert obj["asleep"] == expected.asleep
        elif isinstance(expected, Door):
            assert (obj["door_x"], obj["door_y"]) == xy(expected.door_pos)
            assert obj["is_open"] == expected.is_open
            assert obj["trigger_active"] == expected.trigger_active
            assert obj["horizontal"] == (expected.vert == 1)
        elif isinstance(expected, Thwomp):
            assert obj["direction"] == xy(expected.dir)
            assert obj["moving"] == expected.is_moving
        elif isinstance(expected, FloorGuard):
            assert obj["direction"] == (expected.dir, 0)
            assert obj["chasing"] == expected.chasing
        elif isinstance(expected, HomingLauncher):
            assert (obj["rocket_x"], obj["rocket_y"]) == pytest.approx(xy(expected.pos))
            assert obj["rocket_direction"] == pytest.approx(xy(expected.mdir))
            assert obj["rocket_visible"] == (expected.mode == 2)
            assert obj["rocket_rotation_deg"] == pytest.approx(
                math.atan2(expected.mdir.y, expected.mdir.x) / 0.0174532925199433)
        elif isinstance(expected, Turret):
            assert obj["aim"] == pytest.approx(xy(expected.aim))
            assert obj["target"] == pytest.approx(xy(expected.targ))
            assert obj["crosshair_visible"] == (expected.mode != 0)
        elif isinstance(expected, (LaserDrone, ChaingunDrone)):
            assert obj["target"] == pytest.approx(xy(expected.targ))
            assert obj["vector"] == pytest.approx(xy(expected.targ2))
            assert obj["direction_index"] == expected.cur_dir
            if isinstance(expected, LaserDrone):
                assert obj["beam_end"] == pytest.approx(xy(expected.targ))
                assert obj["beam_visible"] == (expected.mode == 2)
                assert obj["laser_length"] == pytest.approx(math.hypot(expected.targ2.x, expected.targ2.y))
            else:
                assert obj["beam_end"] == pytest.approx(xy(expected.view))
                assert obj["shot_index"] == expected.chaingun_cur_num
                assert obj["weapon_timer"] == expected.chaingun_timer
        if state.player_snapshot()["dead"] or state.level_complete:
            break
        frame = InputFrame(right=tick < 25, jump=tick == 18)
        state.step(frame)
        reference.step(frame, level.tiles)


def test_disabled_enemy_simulation_omits_enemies_without_hiding_basic_objects():
    text = flat_level("!1^300,134!3^400,108!10^500,108!6^600,108,2,0,1,2")
    disabled = native.parse_level_string(text).initial_state().scene_snapshot()
    enabled = native.parse_level_string(text, simulate_enemies=True).initial_state().scene_snapshot()
    assert not disabled["simulate_enemies"] and enabled["simulate_enemies"]
    assert [o["kind"] for o in disabled["objects"]] == ["bounce"]
    assert {o["kind"] for o in enabled["objects"]} == {"bounce", "turret", "homing", "drone_laser"}


def test_scene_queries_preserve_complete_real_replay_and_visual_tracking():
    replay = parse_combined_level_replay((ROOT / "tests/example_06_4_floorguards.txt").read_text())
    level = native.parse_level_string(replay.level_string, simulate_enemies=True)
    queried = level.initial_state(track_visuals=True)
    control = level.initial_state()
    positions = set()
    for frame in [*decode_complex_replay(replay.replay_string).frames, NEUTRAL]:
        assert queried.step(frame) == control.step(frame)
        key = queried.state_key()
        scene = queried.scene_snapshot()
        assert queried.state_key() == key == control.state_key()
        assert scene["visual"] == queried.visual_snapshot()
        positions.update((o["x"], o["y"]) for o in scene["objects"] if o["kind"] == "floorguard")
        if queried.level_complete or queried.player_snapshot()["dead"]:
            break
    assert len(positions) > 10
    assert queried.static_state() == control.static_state()


def test_optional_door_timer_query_matches_reference_and_preserves_gameplay():
    text = flat_level("!9^120,134,0,0,4,5,0,0,0!0^300,134")
    reference_level = parse_level_string(text)
    reference = reference_level.initial_state()
    native_level = native.parse_level_string(text)
    state = native_level.initial_state()
    control = native_level.initial_state()
    timers = set()
    assert native.backend_info()["object_visual_queries"] is True
    assert native.backend_info()["scene_abi"] == 1
    for _ in range(90):
        before = state.state_key()
        ordinary = state.scene_snapshot()
        extended = state.scene_snapshot(include_object_visuals=True)
        assert state.state_key() == before == control.state_key()
        assert state.scene_snapshot(include_object_visuals=False) == ordinary
        assert state.clone().scene_snapshot(include_object_visuals=True) == extended
        for plain_obj, visual_obj in zip(ordinary["objects"], extended["objects"]):
            assert "door_timer" not in plain_obj
            if plain_obj["kind"] == "testdoor":
                expected = reference.objects_by_uid[plain_obj["load_index"]]
                assert visual_obj["door_timer"] == expected.door_timer
                timers.add(visual_obj["door_timer"])
                del visual_obj["door_timer"]
            assert visual_obj == plain_obj
        frame = InputFrame(right=True)
        assert state.step(frame) == control.step(frame)
        reference.step(frame, reference_level.tiles)
    assert timers == set(range(7))  # contact reset, timeout, and closed timer
    assert not state.visuals_enabled
    with pytest.raises(ValueError, match="must be a boolean"):
        state.scene_snapshot(include_object_visuals=1)

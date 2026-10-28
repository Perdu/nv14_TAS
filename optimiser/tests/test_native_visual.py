"""Native animation integration, clocks, branching, and gameplay invariance.

Expected frame numbers come from DefineSprite 898 in n_v14.swf; transition
expectations come from PlayerObject's state and Render methods. Tests exercise
the real native physics and C batch loop, without a second animation engine.
"""
from __future__ import annotations

from pathlib import Path
import ctypes
import math

import pytest

import nv14_native
from nv14_engine import InputFrame
from nv14_replay import decode_complex_replay, parse_combined_level_replay

native = pytest.importorskip("_nv14_native")
ROOT = Path(__file__).resolve().parents[1]
NEUTRAL = InputFrame()
RIGHT = InputFrame(right=True)
LEFT = InputFrame(left=True)


def flat_level(*, x=100, y=134, objects=""):
    tiles = ["0"] * (31 * 23)
    for col in range(31):
        tiles[col * 23 + 5] = "1"
    return native.parse_level_string("".join(tiles) + f"|5^{x},{y}" + objects)


def empty_level(x=100, y=100, objects=""):
    return native.parse_level_string("0" * 713 + f"|5^{x},{y}" + objects)


def test_disabled_default_preserves_snapshot_shape_and_keys():
    level = flat_level()
    plain = level.initial_state()
    tracked = level.initial_state(track_visuals=True)
    assert not plain.visuals_enabled
    assert plain.visual_snapshot() is None
    assert set(plain.snapshot()) == {"backend", "frame", "player", "static_state"}
    assert plain.state_key() == tracked.state_key()
    assert native.backend_info()["visual_abi"] == 1
    assert tracked.visual_snapshot() == {
        "x": 100.0, "y": 134.0, "facing": 1, "rotation_deg": 0.0,
        "animation": "STAND", "frame": 1, "previous_frame": 1,
        "playing": True, "run_frame": None, "run_remainder": 0.0,
        "render_mode": "static_ground", "visible": True, "terminal": False,
    }


def test_stand_plays_to_actual_stop_frame_and_timeline_is_separate():
    state = flat_level().initial_state(track_visuals=True)
    frames = []
    for _ in range(5):
        state.step(NEUTRAL)
        frames.append(state.visual_snapshot()["frame"])
    assert frames == [4, 7, 10, 11, 11]  # 120 fps / 40 gameplay ticks.
    assert state.visual_snapshot()["playing"] is False
    key = state.state_key()
    state.advance_visual_timeline(1000)
    assert state.state_key() == key
    assert state.visual_snapshot()["frame"] == 11


def test_manual_clock_draw_and_prevframe_are_independent():
    state = empty_level().initial_state(
        track_visuals=True, visual_auto_draw=False, visual_timeline_frames=0
    )
    state.advance_visual_timeline(5)
    assert state.visual_snapshot()["frame"] == 6
    assert state.frame == 0
    state.step(RIGHT)
    visual = state.visual_snapshot()
    assert visual["render_mode"] == "in_air"
    assert visual["frame"] == 6  # Think selects Render, but has not drawn.
    assert visual["y"] == 100
    key = state.state_key()
    visual = state.draw_visual()
    assert visual["previous_frame"] == 6
    assert visual["frame"] == 96  # vy=0.15 -> floor(sqrt(0.15/2.5)*9)=2.
    assert visual["playing"] is False
    assert visual["y"] == 100.15
    assert state.state_key() == key


def test_running_remainder_wrap_and_reentry_preserve_source_history():
    state = flat_level().initial_state(track_visuals=True)
    state.step(RIGHT)
    assert state.visual_snapshot()["frame"] == 13
    assert state.visual_snapshot()["run_frame"] is None
    state.step(RIGHT)
    assert state.visual_snapshot()["run_remainder"] == pytest.approx(0.3316666666666808)
    observed = []
    for _ in range(60):
        state.step(RIGHT)
        visual = state.visual_snapshot()
        observed.append(visual["frame"])
        assert 13 <= visual["frame"] <= 84
        assert 0 <= visual["run_remainder"] < 1
    assert any(b < a for a, b in zip(observed, observed[1:]))
    old_run_frame = state.visual_snapshot()["run_frame"]
    state.step(NEUTRAL)
    assert state.visual_snapshot()["frame"] == 12
    assert state.visual_snapshot()["animation"] == "SKID"
    state.step(RIGHT)
    # Run() resets leftovers, not runanimcurframe. RenderRun reuses that frame.
    visual = state.visual_snapshot()
    assert visual["previous_frame"] == 13
    assert visual["frame"] == old_run_frame
    assert visual["run_remainder"] == 0


def test_facing_uses_velocity_not_input_and_retains_direction_at_rest():
    state = flat_level().initial_state(track_visuals=True)
    state.step_many([RIGHT] * 15)
    state.step(LEFT)
    assert state.visual_snapshot()["facing"] == 1  # Still moving right.
    state.step_many([LEFT] * 30)
    assert state.visual_snapshot()["facing"] == -1
    state.step_many([NEUTRAL] * 500)
    assert state.visual_snapshot()["facing"] == -1


def test_jump_pose_covers_rise_apex_and_fall_independently_of_state():
    state = flat_level().initial_state(track_visuals=True)
    state.step(NEUTRAL)
    event = state.step(InputFrame(jump=True))
    assert event["jumped"]
    assert state.visual_snapshot()["frame"] == 85
    assert state.visual_snapshot()["rotation_deg"] == 0
    poses = set()
    for _ in range(30):
        state.step(NEUTRAL)
        if state.visual_snapshot()["render_mode"] == "in_air":
            poses.add(state.visual_snapshot()["frame"])
    assert 85 in poses
    assert any(90 <= frame <= 94 for frame in poses)
    assert any(frame >= 100 for frame in poses)


@pytest.mark.parametrize("tile,angle,direction", [("2", 45.0, RIGHT), ("3", -45.0, LEFT)])
def test_slope_rotation_relaxes_when_walking_off_and_resets_on_jump(tile, angle, direction):
    tiles = ["0"] * 713
    tiles[3 * 23 + 5] = tile
    level = native.parse_level_string("".join(tiles) + "|5^108,142")
    state = level.initial_state(track_visuals=True)
    state.step(NEUTRAL)
    assert state.visual_snapshot()["rotation_deg"] == angle
    jumping = state.clone()
    assert jumping.step(InputFrame(jump=True))["jumped"]
    assert jumping.visual_snapshot()["rotation_deg"] == 0
    for _ in range(80):
        previous = state.visual_snapshot()["rotation_deg"]
        state.step(direction)
        if state.player_snapshot()["in_air"]:
            assert state.visual_snapshot()["rotation_deg"] == pytest.approx(previous * 0.9)
            break
    else:
        pytest.fail("synthetic slope did not reach its airborne transition")


def test_wallslide_faces_wall_even_with_small_opposite_velocity():
    tiles = ["0"] * 713
    for row in range(23):
        tiles[5 * 23 + row] = "1"
    state = native.parse_level_string("".join(tiles) + "|5^134,100").initial_state(
        track_visuals=True
    )
    state.step(RIGHT)  # Initial STANDING -> FALLING early return.
    state.step(RIGHT)
    visual = state.visual_snapshot()
    assert state.player_snapshot()["state"] == 5
    assert (visual["animation"], visual["frame"], visual["facing"]) == ("WALLSLIDE", 104, 1)
    assert visual["rotation_deg"] == 0
    state.step(InputFrame(right=True, jump=True))
    assert state.visual_snapshot()["frame"] == 85
    assert state.visual_snapshot()["facing"] == -1


def test_launch_switches_renderer_even_before_draw():
    # A launch normal of (1, 0) points right. Starting at the pad centre
    # guarantees activation without depending on a long approach trajectory.
    state = empty_level(objects="!2^100,100,1,0").initial_state(
        track_visuals=True, visual_auto_draw=False
    )
    state.step(NEUTRAL)
    assert state.player_snapshot()["state"] == 4
    assert state.visual_snapshot()["render_mode"] == "in_air"
    assert state.visual_snapshot()["frame"] == 4


@pytest.mark.parametrize("variant,start", list(enumerate(
    [106, 167, 234, 313, 355, 449, 507, 659, 744], start=1
)))
def test_supplied_celebration_choice_uses_swf_label(variant, start):
    state = flat_level(x=143, objects="!11^145,134,143,134").initial_state(
        track_visuals=True, celebration_variant=variant
    )
    result = state.step(NEUTRAL)
    assert result["level_complete"]
    visual = state.visual_snapshot()
    assert visual["animation"] == f"CELEBRATE_NEW{variant}"
    assert visual["frame"] == start
    assert visual["playing"] and visual["terminal"]
    state.step_many([NEUTRAL] * 5)
    state.advance_visual_timeline(200)
    assert state.visual_snapshot() == visual  # Native completion is terminal.


def test_random_celebration_is_explicitly_unresolved():
    state = flat_level(x=143, objects="!11^145,134,143,134").initial_state(track_visuals=True)
    state.step(NEUTRAL)
    visual = state.visual_snapshot()
    assert visual["animation"] == "CELEBRATE_UNRESOLVED"
    assert visual["frame"] is None
    assert visual["playing"] and visual["visible"] and visual["terminal"]


def test_airborne_completion_keeps_previous_renderer_and_animation():
    state = empty_level(x=143, objects="!11^145,100,143,100").initial_state(track_visuals=True)
    state.step(NEUTRAL)
    visual = state.visual_snapshot()
    assert visual["terminal"]
    # Celebrate() itself does not select a new animation or Render method.
    assert visual["render_mode"] == "static_ground"
    assert visual["animation"] == "STAND"


@pytest.mark.parametrize("objects", ["!12^100,100", "!11^100,100,100,100!12^100,100"])
def test_death_hides_sprite_without_fabricating_ragdoll_pose(objects):
    state = empty_level(objects=objects).initial_state(track_visuals=True)
    event = state.step(NEUTRAL)
    assert event["dead"]
    visual = state.visual_snapshot()
    assert visual["animation"] == "RAGDOLL"
    assert visual["frame"] is None
    assert not visual["visible"] and not visual["playing"] and visual["terminal"]
    state.step_many([NEUTRAL] * 4, stop_on_dead=False)
    assert state.visual_snapshot() == visual


def test_clone_preserves_history_and_is_independent():
    state = flat_level().initial_state(track_visuals=True)
    state.step_many([RIGHT] * 20)
    clone = state.clone()
    before = state.visual_snapshot()
    assert clone.visual_snapshot() == before
    assert clone.state_key() == state.state_key()
    clone.step(LEFT)
    assert state.visual_snapshot() == before
    state.step(LEFT)
    assert clone.visual_snapshot() == state.visual_snapshot()
    clone.disable_visuals()
    assert state.visuals_enabled and not clone.visuals_enabled
    assert state.state_key() == clone.state_key()


def test_c_copy_into_allocates_reuses_and_removes_tracker():
    library = ctypes.CDLL(native.__file__)
    if not hasattr(library, "nv14_state_copy_into"):
        pytest.skip("platform does not export the optional C API symbols")
    ptr = ctypes.c_void_p
    functions = {
        "nv14_level_create": (ptr, [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int, ptr]),
        "nv14_state_create": (ptr, [ptr, ptr]),
        "nv14_state_copy_into": (ctypes.c_int, [ptr, ptr, ptr]),
        "nv14_state_enable_visuals": (ctypes.c_int, [ptr, ctypes.c_uint32, ctypes.c_int, ctypes.c_int]),
        "nv14_state_visuals_enabled": (ctypes.c_int, [ptr]),
        "nv14_state_advance_visual_timeline": (ctypes.c_int, [ptr, ctypes.c_uint32]),
        "nv14_state_get_visual": (ctypes.c_int, [ptr, ptr]),
        "nv14_state_destroy": (None, [ptr]),
        "nv14_level_release": (None, [ptr]),
    }
    for name, (restype, argtypes) in functions.items():
        getattr(library, name).restype = restype
        getattr(library, name).argtypes = argtypes
    level_bytes = ("0" * 713 + "|5^100,100").encode()
    level = library.nv14_level_create(level_bytes, len(level_bytes), 0, None)
    assert level
    states = []
    try:
        states = [library.nv14_state_create(level, None) for _ in range(3)]
        assert all(states)
        source, destination, untracked = states
        assert library.nv14_state_enable_visuals(source, 0, 0, 0) == 0
        assert library.nv14_state_advance_visual_timeline(source, 4) == 0
        a, b = ctypes.create_string_buffer(128), ctypes.create_string_buffer(128)
        for _ in range(2):
            assert library.nv14_state_copy_into(destination, source, None) == 0
            assert library.nv14_state_visuals_enabled(destination)
            assert library.nv14_state_get_visual(source, a) == 0
            assert library.nv14_state_get_visual(destination, b) == 0
            assert a.raw == b.raw
        assert library.nv14_state_advance_visual_timeline(destination, 3) == 0
        assert library.nv14_state_get_visual(source, a) == 0
        assert library.nv14_state_get_visual(destination, b) == 0
        assert a.raw != b.raw
        assert library.nv14_state_copy_into(destination, untracked, None) == 0
        assert not library.nv14_state_visuals_enabled(destination)
        assert library.nv14_state_visuals_enabled(source)
    finally:
        for state in states:
            library.nv14_state_destroy(state)
        library.nv14_level_release(level)


def test_batch_api_runs_same_visual_updates_as_individual_steps():
    level = flat_level()
    inputs = [RIGHT] * 20 + [InputFrame(right=True, jump=True)] * 6 + [LEFT] * 8
    individual = level.initial_state(track_visuals=True)
    for frame in inputs:
        individual.step(frame)
    batch = level.simulate(inputs, track_visuals=True)
    assert batch["state"] == individual.snapshot()
    facade = nv14_native.simulate_batch(level.level_string, inputs, track_visuals=True)
    assert facade == batch


@pytest.mark.parametrize("options", [
    {"timeline_frames": -1}, {"timeline_frames": 2**32}, {"timeline_frames": 1.5},
    {"celebration_variant": -1}, {"celebration_variant": 10}, {"celebration_variant": 1.5},
])
def test_enable_rejects_invalid_options_without_enabling(options):
    state = flat_level().initial_state()
    with pytest.raises((ValueError, TypeError)):
        state.enable_visuals(**options)
    assert not state.visuals_enabled


def test_enable_requires_unstepped_state_and_disable_is_idempotent():
    state = flat_level().initial_state()
    state.enable_visuals()
    with pytest.raises(ValueError, match="fresh"):
        state.enable_visuals()
    state.step(NEUTRAL)
    state.disable_visuals()
    state.disable_visuals()
    with pytest.raises(ValueError, match="fresh"):
        state.enable_visuals()
    with pytest.raises(ValueError):
        state.draw_visual()


REPLAYS = sorted((ROOT / "tests").glob("example_*.txt"))


@pytest.mark.parametrize("path", REPLAYS, ids=lambda path: path.stem)
def test_replay_visuals_preserve_every_gameplay_bit(path):
    combined = parse_combined_level_replay(path.read_text(encoding="utf-8"))
    frames = decode_complex_replay(combined.replay_string).frames + [NEUTRAL]
    level = native.parse_level_string(combined.level_string, simulate_enemies=True)
    plain = level.initial_state()
    tracked = level.initial_state(track_visuals=True)
    for frame in frames:
        expected = plain.step(frame)
        assert tracked.step(frame) == expected
        assert tracked.state_key() == plain.state_key()
        assert tracked.player_snapshot() == plain.player_snapshot()
        visual = tracked.visual_snapshot()
        if not expected["dead"]:
            assert (visual["x"], visual["y"]) == tracked.player_snapshot()["pos"]
            assert math.isfinite(visual["rotation_deg"])
        if expected["dead"] or expected["level_complete"]:
            break

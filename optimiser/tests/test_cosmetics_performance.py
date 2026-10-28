"""Borrowed replay scenes preserve cosmetics without redundant snapshots."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

import nv14_object_visuals
import nv14_particles
from nv14_object_visuals import ObjectVisualSystem
from nv14_particles import ParticleSystem


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def manifest():
    return json.loads((ROOT / "nv14_assets/manifest.json").read_text())


def scene(frame=0):
    return {"frame": frame, "static_state": {"level_complete": False},
            "visual": {"rotation_deg": 0., "facing": 1},
            "player": {"pos": [100., 100.], "oldpos": [100., 100.],
                       "dead": False, "r": 10., "state": 3, "in_air": True,
                       "floor_n": [0., -1.], "wall_n": [1., 0.],
                       "jump_events": 0, "jump_amt": 6., "jump_y_bias": 1.},
            "objects": [{"id": 2, "kind": "gold", "x": 200., "y": 100.,
                         "visible": True, "parameters": [200., 100.]}]}


@pytest.mark.parametrize("factory", [ParticleSystem, ObjectVisualSystem])
def test_default_mode_owns_nested_caller_data_after_reset_and_update(manifest, factory):
    tracker, reference = factory(manifest), factory(manifest)
    initial = scene()
    tracker.reset(initial)
    reference.reset(deepcopy(initial))
    expected_initial = deepcopy(initial)
    initial["frame"] = 500
    initial["player"]["pos"][0] = -1000
    initial["objects"][0]["parameters"][0] = -1000
    initial["objects"][0]["x"] = -1000
    assert tracker._previous == expected_initial
    assert tracker.snapshot() == reference.snapshot()

    after = scene(1)
    after["objects"][0]["visible"] = False
    expected_after = deepcopy(after)
    assert tracker.update(after) == reference.update(deepcopy(after))
    after["frame"] = 600
    after["objects"][0]["x"] = -1000
    after["objects"][0]["parameters"][0] = -1000
    after["player"]["pos"][0] = -1000
    assert tracker._previous == expected_after
    assert tracker.snapshot() == reference.snapshot()
    final = scene(2)
    final["objects"][0]["visible"] = False
    assert tracker.update(final) == reference.update(final)


@pytest.mark.parametrize("factory,module", [(ParticleSystem, nv14_particles),
                                           (ObjectVisualSystem, nv14_object_visuals)])
def test_borrow_mode_does_no_scene_copy_and_no_discarded_snapshots(manifest, factory, module, monkeypatch):
    tracker = factory(manifest, _borrow_scenes=True)

    def forbidden(*args, **kwargs):
        pytest.fail("borrowed scene path copied data or built discarded draw records")

    monkeypatch.setattr(module, "deepcopy", forbidden)
    snapshot = tracker.snapshot
    monkeypatch.setattr(tracker, "snapshot", forbidden)
    initial = scene()
    if factory is ObjectVisualSystem:
        assert tracker.reset(initial, _snapshot=False) is None
    else:
        tracker.reset(initial)
    assert tracker._previous is initial
    after = scene(1)
    after["objects"][0]["visible"] = False
    assert tracker.update(after, _snapshot=False) is None
    assert tracker._previous is after
    assert tracker.update(after, _snapshot=False) is None
    assert tracker.advance(3, _snapshot=False) is None
    assert isinstance(snapshot(), tuple)
    if factory is ObjectVisualSystem:
        assert tracker._states[2]["obj"] is after["objects"][0]


@pytest.mark.parametrize("factory", [ParticleSystem, ObjectVisualSystem])
def test_default_update_builds_only_final_snapshot(manifest, factory, monkeypatch):
    tracker = factory(manifest)
    original = tracker.snapshot
    calls = []

    def snapshot():
        calls.append(True)
        return original()

    monkeypatch.setattr(tracker, "snapshot", snapshot)
    # Prime through update too, covering the no-previous-scene branch.
    assert tracker.update(scene(), _snapshot=False) is None
    assert not calls
    result = tracker.update(scene(1))
    assert len(calls) == 1
    assert result == original()


def test_object_order_cache_invalidates_when_objects_are_added(manifest):
    tracker = ObjectVisualSystem(manifest, _borrow_scenes=True)
    initial = scene()
    assert [r.id for r in tracker.reset(initial)] == [2]
    after = scene(1)
    after["objects"].append({**after["objects"][0], "id": 1})
    assert [r.id for r in tracker.update(after)] == [1, 2]
    assert [r.id for r in tracker.snapshot()] == [1, 2]
    assert [r.id for r in tracker.reset(initial)] == [2]


@pytest.mark.parametrize("filename", ["example_00_1_speedrun.txt", "example_07_3_homing.txt",
                                      "example_28_3_turrets.txt"])
def test_borrowed_cosmetics_match_safe_path_for_replay_and_terminal_hold(manifest, filename):
    native = pytest.importorskip("_nv14_native")
    from nv14_engine import InputFrame
    from nv14_replay import decode_complex_replay, parse_combined_level_replay

    replay = parse_combined_level_replay((ROOT / "tests" / filename).read_text())
    frames = decode_complex_replay(replay.replay_string).frames
    state = native.parse_level_string(replay.level_string, simulate_enemies=True).initial_state(track_visuals=True)
    pairs = [(factory(manifest), factory(manifest, _borrow_scenes=True))
             for factory in (ParticleSystem, ObjectVisualSystem)]
    initial = state.scene_snapshot(include_object_visuals=True)
    for safe, borrowed in pairs:
        safe.reset(initial)
        borrowed.reset(initial)
    saw_particles = False
    frozen_records = []
    for frame in [*frames, InputFrame()]:
        state.step(frame)
        current = state.scene_snapshot(include_object_visuals=True)
        untouched = deepcopy(current)
        for safe, borrowed in pairs:
            expected = safe.update(current, frame)
            assert borrowed.update(current, frame, _snapshot=False) is None
            assert borrowed.snapshot() == expected
            if isinstance(safe, ParticleSystem):
                saw_particles |= bool(expected)
            frozen_records.append((expected, deepcopy(expected)))
        assert current == untouched
        if current["player"]["dead"] or current["static_state"]["level_complete"]:
            break
    assert saw_particles
    for count in (0, 1, 2, 3, 10, 120):
        for safe, borrowed in pairs:
            expected = safe.advance(count)
            assert borrowed.advance(count, _snapshot=False) is None
            assert borrowed.snapshot() == expected
    # Later updates/holds cannot change records already queued to a renderer.
    assert all(before == after for before, after in frozen_records)

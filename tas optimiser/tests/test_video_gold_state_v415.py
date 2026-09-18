"""Sparse ghost ownership and cached timelines preserve observable clip state."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from nv14_object_visuals import _Clip
from nv14_video_gold import GhostGoldSystem


COLORS = ((53, 104, 168), (176, 57, 76), (30, 135, 85))


def scene(count=3):
    # Deliberately reverse descriptors: display order is gold state index.
    return {"objects": [{"kind": "gold", "state_index": index,
                         "x": 150 + 10 * index, "y": 134}
                        for index in reversed(range(count))]}


def manifest(info):
    return {"object_animations": {"clips": {"gold": info}}}


def effect_system(info, colors=COLORS):
    system = GhostGoldSystem(scene(), colors, manifest(info), animated=True)
    system.update(1, ())
    system.update(1, [(0, (0,))])
    return system


def test_owner_change_reuses_all_unaffected_idle_records():
    system = GhostGoldSystem(scene(97), COLORS, {})
    mask = (1 << 97) - 1
    system.update(mask, ())
    before = system.snapshot()
    assert [row.key[0] for row in before] == list(range(97))
    system.update(mask, [(0, (41,))])
    after = system.snapshot()
    assert after[41].color == COLORS[1]
    assert all(after[index] is before[index] for index in range(97) if index != 41)
    system.update(mask, [(2, (41, 42))])
    assert system.snapshot() is after  # Invisible owners do not invalidate.
    system.update(mask, [(1, (41,))])
    removed = system.snapshot()
    assert [row.key[0] for row in removed] == [i for i in range(97) if i != 41]
    assert removed[41] is before[42]


def test_sparse_insertions_and_unsampled_changes_keep_order_and_identity():
    system = GhostGoldSystem(scene(9), COLORS, {})
    system.update((1 << 1) | (1 << 7), ())
    first = system.snapshot()
    # Several updates can happen between sampled video frames.
    mask = (1 << 1) | (1 << 3) | (1 << 7)
    system.update(mask, ())
    system.update(mask, [(0, (3,)), (1, (3,)), (2, (3,))])
    assert system.snapshot() is first
    system.update(mask | (1 << 0) | (1 << 8), ())
    rows = system.snapshot()
    assert [row.key[0] for row in rows] == [0, 1, 7, 8]
    assert rows[1] is first[0] and rows[2] is first[1]


def test_equal_owner_colours_do_not_rebuild_visible_idle_snapshot():
    system = GhostGoldSystem(scene(), (COLORS[0], COLORS[0]), {})
    system.update(1, ())
    before = system.snapshot()
    system.update(1, [(0, (0,))])
    assert system.snapshot() is before
    system.update(1, [(1, (0,))])
    assert system.snapshot() == ()


CUSTOM_CLIPS = [
    {"frame_count": 8, "labels": {"COLLECTED": 2},
     "actions": {"1": [{"op": "stop"}],
                 "8": [{"op": "set_visible", "visible": False}]}},
    {"frame_count": 7, "labels": {"COLLECTED": 2, "again": 2, "skip": 5},
     "actions": {"3": [{"op": "goto_and_play", "target": "skip"}],
                 "7": [{"op": "goto_and_play", "target": "again"}]}},
    {"frame_count": 8, "labels": {"COLLECTED": 2},
     "actions": {"4": [{"op": "stop"}]}},
    {"frame_count": 8, "labels": {"COLLECTED": 2},
     "actions": {"3": [{"op": "set_visible", "visible": False}],
                 "5": [{"op": "set_visible", "visible": True}]}},
    {"frame_count": 8, "labels": {"COLLECTED": 2},
     "actions": {"2": [{"op": "set_visible", "visible": False}],
                 "3": [{"op": "set_visible", "visible": True}],
                 "6": [{"op": "goto_and_stop", "target": 5}]}},
    {"frame_count": 6000, "labels": {"COLLECTED": 2}, "actions": {}},
]


@pytest.mark.parametrize("info", CUSTOM_CLIPS)
@pytest.mark.parametrize("steps", [(0, 1, 1, 3, 2, 9, 50), (3,) * 30, (299, 6001, 0)])
def test_manifest_timelines_match_movieclip_interpreter(info, steps):
    original = deepcopy(info)
    system = effect_system(info)
    clip = _Clip("gold", info)
    clip.goto("COLLECTED", True)
    expected_alive = True  # Initial visibility is checked on the next advance.
    for advance in (None, *steps):
        if advance is not None:
            if expected_alive:
                clip.advance(advance)
                expected_alive = clip.visible
            system.advance(advance)
        rows = system.snapshot()
        effects = [row for row in rows if row.key[1]]
        assert len(effects) == int(expected_alive)
        if expected_alive:
            assert effects[0].frame == clip.frame
            assert effects[0].color == COLORS[0]
        assert rows[-1].color == COLORS[1]
        assert system.animating is expected_alive
    assert info == original


def test_builtin_animation_uses_no_interpreter_after_compilation(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    info = json.loads((root / "nv14_assets/manifest.json").read_text())["object_animations"]["clips"]["gold"]
    system = effect_system(info)

    def unexpected_advance(*args):
        raise AssertionError("active gold should use its compiled timeline")

    monkeypatch.setattr(_Clip, "advance", unexpected_advance)
    frames = []
    while system.animating:
        frames.append(system.snapshot()[0].frame)
        system.advance(3)
    assert frames == list(range(2, 30, 3))


def test_stopped_animation_reuses_complete_snapshot():
    info = CUSTOM_CLIPS[2]
    system = effect_system(info)
    system.advance(2)
    before = system.snapshot()
    assert before[0].frame == 4
    system.advance(200)
    assert system.snapshot() is before
    system.advance(0)
    assert system.snapshot() is before


def test_invalid_future_action_still_fails_only_when_reached():
    info = {"frame_count": 9, "labels": {"COLLECTED": 2},
            "actions": {"5": [{"op": "goto_and_play", "target": 6}],
                        "6": [{"op": "goto_and_play", "target": 5}]}}
    system = effect_system(info)
    system.advance(2)
    assert system.snapshot()[0].frame == 4
    with pytest.raises(ValueError, match="Cyclic object MovieClip"):
        system.advance(1)

"""Bundled object artwork retains the original SWF's timeline and geometry.

The expected IDs, frame counts, labels and actions below are source contracts
from the supplied N v1.4 SWF, independent of the visual tracker. Tests need no
Java, FFDec, native simulation module, or access to the original SWF.
"""
import hashlib
import json
import math
from pathlib import Path
import struct

import pytest


ASSETS = Path(__file__).resolve().parents[1] / "nv14_assets"
SOURCE_SHA256 = "9db8e7b1e2d15dfa3e378690dd35c17b3818a0cc85dc46e2ae0e9ef4d93b18c1"

# Original character ID, frame count and the one-time source scale.
SOURCE_CLIPS = {
    "gold": (889, 30, .06),
    "exit": (848, 31, .24),
    "door": (870, 74, .24),
    "launchpad": (878, 24, .15),
    "turret": (830, 37, .12),
    "turret_crosshair": (824, 6, .18),
    "homing_launcher": (839, 9, .12),
    "drone": (816, 58, .18),
    "laser_blast": (1296, 13, 1.),
    "rocket": (835, 13, 1.),
    "floorguard": (819, 2, .12),
    "mine": (882, 2, .08),
    "door_switch": (843, 2, .075),
    "exit_switch": (845, 2, .12),
}

SOURCE_LABELS = {
    "gold": {"NOT_COLLECTED": 1, "COLLECTED": 2},
    "exit": {"exit_closed": 1, "exit_opening": 2},
    "door": {"opening_Trek": 2, "open_Trek": 17, "closing_Trek": 18,
             "closed_Trek": 34, "open_Trap": 35, "closing_Trap": 36,
             "closed_Trap": 54, "closed_Lock": 55, "opening_Lock": 56,
             "open_Lock": 74},
    "launchpad": {"launch_triggered": 2, "launch_idle": 20},
    "turret": {"turret_prefire": 2, "turret_firing": 18,
               "turret_postfire": 20, "turret_idle": 29},
    "turret_crosshair": {"aim_far": 1, "aim_mid": 2, "aim_near": 3,
                         "prefire": 4, "postfire": 5},
    "homing_launcher": {"rocket_waiting": 1, "rocket_fire": 2,
                        "rocket_active": 4, "rocket_activeB": 5,
                        "rocket_explode": 8},
    "drone": {"zapdrone_move": 2, "zapdrone_chaseidle": 3,
              "zapdrone_chaseactive": 4, "laserdrone_prefire": 6,
              "laserdrone_firing": 29, "laserdrone_postfire": 30,
              "laserdrone_move": 51, "chaingundrone_move": 52,
              "chaingundrone_prefire": 53, "chaingundrone_fire": 55,
              "chaingundrone_postfire": 57},
    "laser_blast": {},
    "rocket": {},
    "floorguard": {"floorguard_idle": 1, "floorguard_active": 2},
    "mine": {"mine_unexploded": 1, "mine_exploded": 2},
    "door_switch": {"exit_closed": 1, "exit_open": 2},
    "exit_switch": {"exit_closed": 1, "exit_open": 2},
}

SOURCE_STOP_FRAMES = {
    "gold": {1}, "exit": {31}, "door": {1, 17, 34, 35, 54, 55, 74},
    "launchpad": {1, 20}, "turret": {1, 17, 18, 19, 29},
    "turret_crosshair": set(), "homing_launcher": {1},
    "drone": {1, 28, 51, 54, 56}, "laser_blast": set(), "rocket": set(),
    "floorguard": {1}, "mine": set(), "door_switch": set(), "exit_switch": set(),
}


@pytest.fixture(scope="module")
def manifest():
    return json.loads((ASSETS / "manifest.json").read_text("utf-8"))


def test_object_clip_pack_is_pinned_to_original_source(manifest):
    assert manifest["source_swf_sha256"] == SOURCE_SHA256
    pack = manifest["object_animations"]
    assert pack["schema_version"] == 1
    assert pack["source_frame_rate"] == manifest["source_frame_rate"] == 120
    assert SOURCE_CLIPS.keys() <= pack["clips"].keys()


@pytest.mark.parametrize("key", SOURCE_CLIPS)
def test_complete_original_frames_have_valid_png_hashes_and_scale(manifest, key):
    clip = manifest["object_animations"]["clips"][key]
    sid, count, scale = SOURCE_CLIPS[key]
    assert (clip["symbol_id"], clip["frame_count"], clip["source_scale"]) == (sid, count, scale)
    # None of these source timelines calls removeMovieClip. In particular, the
    # authored final frame and stop frames must not be dropped as particle tails.
    assert set(clip["frames"]) == {str(frame) for frame in range(1, count + 1)}
    for number, frame in clip["frames"].items():
        assert frame["source_frame"] == int(number)
        path = (ASSETS / frame["file"]).resolve()
        assert path.is_relative_to(ASSETS.resolve())
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == frame["sha256"]
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert data[12:16] == b"IHDR"
        width, height, depth, color = struct.unpack_from(">IIBB", data, 16)
        assert width > 0 and height > 0
        assert (depth, color) == (8, 6)  # RGBA preserves transparency.
        x0, y0, x1, y1 = frame["source_crop_pixels"]
        assert (width, height) == (x1 - x0, y1 - y0)
        assert len(frame["origin"]) == 2
        assert all(math.isfinite(value) for value in frame["origin"])
        # Rendering applies no additional source scale: a source unit occupies
        # scale game units and was exported at two pixels per source unit.
        assert frame["pixels_per_unit"] * scale == pytest.approx(2)


@pytest.mark.parametrize("key", SOURCE_CLIPS)
def test_source_labels_actions_and_stopframes_remain_in_bounds(manifest, key):
    clip = manifest["object_animations"]["clips"][key]
    assert clip["labels"] == SOURCE_LABELS[key]
    assert all(1 <= frame <= clip["frame_count"] for frame in clip["labels"].values())
    stop_frames = set()
    assert set(clip["actions"]) == set(clip["action_bytecode"])
    for frame, actions in clip["actions"].items():
        assert 1 <= int(frame) <= clip["frame_count"]
        assert frame in clip["frames"]
        assert actions
        assert all(bytes.fromhex(code).endswith(b"\0") for code in clip["action_bytecode"][frame])
        for action in actions:
            assert action["op"] in {"stop", "goto_and_stop", "goto_and_play", "set_visible"}
            if action["op"] == "stop":
                stop_frames.add(int(frame))
            elif action["op"].startswith("goto_"):
                target = action["target"]
                resolved = clip["labels"][target] if isinstance(target, str) else target
                assert 1 <= resolved <= clip["frame_count"]
                assert str(resolved) in clip["frames"]
    assert stop_frames == SOURCE_STOP_FRAMES[key]


def test_source_goto_actions_preserve_launcher_loop_and_drone_returns(manifest):
    clips = manifest["object_animations"]["clips"]
    assert clips["homing_launcher"]["actions"] == {
        "1": [{"op": "stop"}],
        "3": [{"op": "goto_and_stop", "target": "rocket_active"}],
        "7": [{"op": "goto_and_play", "target": "rocket_activeB"}],
        "9": [{"op": "goto_and_stop", "target": "rocket_waiting"}],
    }
    assert clips["drone"]["actions"]["5"] == [
        {"op": "goto_and_stop", "target": "zapdrone_chaseidle"}]
    assert clips["drone"]["actions"]["58"] == [
        {"op": "goto_and_stop", "target": "chaingundrone_move"}]


def test_gold_collection_hides_only_at_original_visibility_action(manifest):
    gold = manifest["object_animations"]["clips"]["gold"]
    assert gold["actions"] == {
        "1": [{"op": "stop"}],
        "30": [{"op": "set_visible", "visible": False}],
    }
    assert "30" in gold["frames"]
    collected = [gold["frames"][str(frame)] for frame in range(2, 30)]
    assert len({frame["sha256"] for frame in collected}) > 20


def test_laser_blast_preserves_every_original_morph_frame(manifest):
    blast = manifest["object_animations"]["clips"]["laser_blast"]
    assert blast["children"] == [
        {"symbol_id": sid, "type": "DefineMorphShape"} for sid in range(1291, 1295)
    ] + [{"symbol_id": 1295, "type": "DefineShape"}]
    # These are shape dependencies, not child sprites with an independent clock.
    assert blast["actions"] == {}
    assert len({frame["sha256"] for frame in blast["frames"].values()}) == 13


def test_shared_static_reference_frames_keep_original_pixels_and_registration(manifest):
    clips = manifest["object_animations"]["clips"].values()
    matched_symbols = set()
    for reference in manifest["objects"].values():
        matches = [clip for clip in clips
                   if (clip["symbol_id"], clip["source_scale"])
                   == (reference["symbol_id"], reference["source_scale"])]
        for clip in matches:
            matched_symbols.add(clip["symbol_id"])
            frame = clip["frames"][str(reference["source_frame"])]
            for field in ("sha256", "origin", "pixels_per_unit", "source_crop_pixels"):
                assert frame[field] == reference[field], (clip["symbol"], field)
            # Verify the existing v4.05 reference itself, not just a metadata
            # equality that could otherwise hide an accidentally replaced PNG.
            reference_bytes = (ASSETS / reference["file"]).read_bytes()
            assert hashlib.sha256(reference_bytes).hexdigest() == reference["sha256"]
            assert (ASSETS / frame["file"]).read_bytes() == reference_bytes
    expected_shared = {sid for key, (sid, _, _) in SOURCE_CLIPS.items()
                       if key not in {"turret_crosshair", "laser_blast"}}
    assert matched_symbols == expected_shared

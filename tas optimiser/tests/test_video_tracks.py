"""Exact visual capture, replay clock boundaries and safe cache invalidation."""
from pathlib import Path

import pytest

from nv14_engine import InputFrame
from nv14_replay import decode_complex_replay, parse_combined_level_replay
import nv14_video_tracks as tracks

native = pytest.importorskip("_nv14_native")
ROOT = Path(__file__).resolve().parents[1]
NEUTRAL = InputFrame()
RIGHT = InputFrame(right=True)


def flat_level(*, x=100, objects="", enemies=True):
    tiles = ["0"] * 713
    for column in range(31):
        tiles[column * 23 + 5] = "1"
    return native.parse_level_string("".join(tiles) + f"|5^{x},134" + objects,
                                     simulate_enemies=enemies)


@pytest.mark.parametrize("name", ["example_00_1_speedrun.txt", "example_07_3_homing.txt",
                                 "example_28_3_turrets.txt", "example_44_0.txt"])
@pytest.mark.parametrize("chunk_size", [1, 17, 512])
def test_compact_capture_matches_every_single_step_visual(name, chunk_size):
    replay = parse_combined_level_replay((ROOT / "tests" / name).read_text())
    frames = decode_complex_replay(replay.replay_string).frames
    level = native.parse_level_string(replay.level_string, simulate_enemies=True)
    reference = level.initial_state(track_visuals=True, visual_timeline_frames=3,
                                    celebration_variant=1)
    with tracks.VisualTrack(level, frames, True, chunk_size=chunk_size) as track:
        assert track.visual == reference.visual_snapshot()
        for tick, frame in enumerate([*frames, NEUTRAL], 1):
            event = reference.step(frame)
            track.step()
            assert track.ticks == tick
            assert track.visual == reference.visual_snapshot()
            assert (track.dead, track.complete) == (bool(event["dead"]),
                                                    bool(event["level_complete"]))
            if track.done:
                break
        assert track.done


def test_precompute_preserves_clock_and_explicit_jump_triggers():
    level = flat_level()
    frames = [InputFrame(right=True, jump=True, jump_trigger=False),
              InputFrame(right=True, jump=False, jump_trigger=True),
              InputFrame(right=True, jump=True, jump_trigger=True)] + [RIGHT] * 80
    reference = level.initial_state(track_visuals=True, celebration_variant=1)
    with tracks.VisualTrack(level, frames, False, chunk_size=3) as track:
        initial = track.visual.copy()
        track.precompute()
        assert track.ticks == 0 and track.visual == initial
        assert not track.done and not track.dead and not track.complete
        while not track.done:
            reference.step(frames[track.ticks])
            track.step()
            assert track.visual == reference.visual_snapshot()
        assert track.total_ticks == len(frames)
        assert track.result(1).stop_reason == "input_end"


@pytest.mark.parametrize("objects,dead,complete", [
    ("!12^143,134", True, False),
    ("!11^145,134,143,134", False, True),
])
def test_terminal_tick_is_kept_and_unused_tail_not_captured(objects, dead, complete):
    with tracks.VisualTrack(flat_level(x=143, objects=objects), [NEUTRAL] * 20,
                            True, chunk_size=10) as track:
        track.precompute()
        assert track.total_ticks == 1
        assert track.completion_tick == (1 if complete else None)
        assert not track.done
        track.step()
        assert track.done and track.dead is dead and track.complete is complete
        assert not track.sentinel_written
        assert track.result(1).stop_reason == ("complete" if complete else "dead")
        with pytest.raises(RuntimeError, match="finished"):
            track.step()


@pytest.mark.parametrize("neutral", [False, True])
def test_empty_input_and_final_neutral(neutral):
    with tracks.VisualTrack(flat_level(), [], neutral, chunk_size=1) as track:
        track.precompute()
        assert track.total_ticks == int(neutral)
        assert track.done is (not neutral)
        if neutral:
            track.step()
        assert track.done and track.sentinel_written is neutral


def test_terminal_final_neutral_is_counted():
    with tracks.VisualTrack(flat_level(x=143, objects="!11^145,134,143,134"), [],
                            True) as track:
        track.precompute()
        assert track.completion_tick == 1
        track.step()
        assert track.complete and track.sentinel_written


def test_same_tick_completion_and_death_on_final_neutral():
    level = native.parse_level_string(
        "0" * 713 + "|5^115,100!12^115,100!11^115,100,115,100")
    with tracks.VisualTrack(level, [NEUTRAL], True) as track:
        track.precompute()
        assert track.completion_tick == track.total_ticks == 2
        track.step()
        assert not track.done
        track.step()
        assert track.dead and track.complete and track.sentinel_written
        assert track.result(1).stop_reason == "complete"


def test_cache_reuses_visuals_and_invalidates_all_simulation_inputs(tmp_path, monkeypatch):
    level = flat_level()
    frames = [RIGHT] * 20
    with tracks.VisualTrack(level, frames, True, cache_dir=tmp_path) as first:
        first.precompute()
        expected = []
        while not first.done:
            first.step()
            expected.append(first.visual)
    with tracks.VisualTrack(level, frames, True, cache_dir=tmp_path) as cached:
        assert cached.cache_hit and cached.state is None
        actual = []
        while not cached.done:
            cached.step()
            actual.append(cached.visual)
        assert actual == expected
        assert cached.sentinel_written
    changes = [
        (level, frames, False),
        (flat_level(enemies=False), frames, True),
        (flat_level(x=101), frames, True),
        (level, [InputFrame(right=True, jump_trigger=False), *frames[1:]], True),
        (level, [InputFrame(left=True), *frames[1:]], True),
    ]
    for changed_level, changed_frames, neutral in changes:
        with tracks.VisualTrack(changed_level, changed_frames, neutral,
                                cache_dir=tmp_path) as changed:
            assert not changed.cache_hit
    monkeypatch.setattr(tracks, "_engine_identity", lambda: "changed-engine")
    with tracks.VisualTrack(level, frames, True, cache_dir=tmp_path) as changed:
        assert not changed.cache_hit


@pytest.mark.parametrize("damage", ["truncate", "payload", "header", "extra"])
def test_corrupt_cache_is_ignored_and_atomically_replaced(tmp_path, damage):
    level = flat_level()
    frames = [RIGHT] * 20
    with tracks.VisualTrack(level, frames, True, cache_dir=tmp_path) as first:
        first.precompute()
    path, = tmp_path.glob("*.nv14-track")
    original = path.read_bytes()
    damaged = bytearray(original)
    if damage == "truncate":
        damaged = damaged[:-4]
    elif damage == "payload":
        damaged[-20] ^= 1
    elif damage == "header":
        damaged[8:12] = b"\xff" * 4
    else:
        damaged.extend(b"extra")
    path.write_bytes(damaged)
    with tracks.VisualTrack(level, frames, True, cache_dir=tmp_path) as replacement:
        assert not replacement.cache_hit
        replacement.precompute()
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_long_track_spills_to_disk_and_closes():
    level = flat_level()
    track = tracks.VisualTrack(level, [NEUTRAL] * 5000, False, chunk_size=37)
    track.precompute()
    assert track.total_ticks == 5000
    assert track._stream._rolled
    stream = track._stream
    track.close()
    assert stream.closed


def test_capture_requires_visual_tracking_and_empty_capture_is_safe():
    with pytest.raises(ValueError, match="track_visuals"):
        flat_level().initial_state().capture_visual_frames([NEUTRAL])
    state = flat_level().initial_state(track_visuals=True)
    assert state.capture_visual_frames([]) == b""

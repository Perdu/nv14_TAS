"""Exact pickup events, multi-ghost ownership and deterministic gold rendering."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from nv14_engine import InputFrame
from nv14_video_gold import GhostGoldSystem, GoldVisual
from nv14_video_tracks import VisualTrack, _decode_record, _RECORD

native = pytest.importorskip("_nv14_native")
ROOT = Path(__file__).resolve().parents[1]
NEUTRAL = InputFrame()
RIGHT = InputFrame(right=True)
COLORS = ((53, 104, 168), (176, 57, 76), (30, 135, 85))


def level(objects="", x=100):
    tiles = ["0"] * 713
    for column in range(31):
        tiles[column * 23 + 5] = "1"
    return native.parse_level_string("".join(tiles) + f"|5^{x},134" + objects, simulate_enemies=True)


@pytest.fixture
def manifest():
    return json.loads((ROOT / "nv14_assets/manifest.json").read_text())


@pytest.mark.parametrize("gold_count", [0, 3, 70])
@pytest.mark.parametrize("chunk", [1, 17, 512])
def test_native_events_match_actual_masks_without_affecting_state(gold_count, chunk):
    # Colocated self-removing objects collect on different ticks. More than 64
    # also exercises mask word boundaries; nearby positions are not an oracle.
    world = level("!0^100,134" * gold_count)
    capture = world.initial_state(track_visuals=True, visual_timeline_frames=3)
    reference = world.initial_state(track_visuals=True, visual_timeline_frames=3)
    before = 0
    total = 0
    for start in range(0, 85, chunk):
        inputs = [NEUTRAL] * min(chunk, 85 - start)
        raw, events = capture.capture_gold_visual_frames(inputs)
        expected = []
        for tick, frame in enumerate(inputs, 1):
            reference.step(frame)
            mask = reference.static_state()["collected_gold_mask"]
            expected.extend((tick, index) for index in range(gold_count)
                            if (mask & ~before) >> index & 1)
            before = mask
            visual, _, _ = _decode_record(raw[(tick-1)*_RECORD.size:tick*_RECORD.size])
            assert visual == reference.visual_snapshot()
        assert events == sorted(expected)
        assert capture.state_key() == reference.state_key()
        total += len(events)
    assert total == gold_count


@pytest.mark.parametrize("objects", ["!0^100,134!11^100,134,100,134",
                                    "!0^100,134!12^100,134"])
def test_native_terminal_capture_keeps_only_real_pickups(objects):
    world = level(objects)
    state = world.initial_state(track_visuals=True)
    raw, events = state.capture_gold_visual_frames([NEUTRAL] * 30)
    ref = world.initial_state(track_visuals=True)
    expected = []
    for tick in range(1, len(raw)//_RECORD.size + 1):
        ref.step(NEUTRAL)
        if ref.static_state()["collected_gold_mask"] and not expected:
            expected.append((tick, 0))
    assert events == expected
    assert state.state_key() == ref.state_key()
    assert state.capture_gold_visual_frames([NEUTRAL]) == (b"", [])
    assert state.capture_gold_visual_frames([]) == (b"", [])


def test_gold_track_cache_and_chunk_playback(tmp_path):
    world = level("!0^100,134!0^100,134!0^180,134")
    frames = [RIGHT] * 60
    expected = []
    for cached in (False, True):
        with VisualTrack(world, frames, True, chunk_size=2, capture_gold=True,
                         cache_dir=tmp_path) as track:
            assert track.cache_hit is cached
            track.precompute()
            assert not track.gold_pickups and track.ticks == 0
            actual = []
            while not track.done:
                track.step()
                actual.append((track.ticks, track.gold_pickups, track.visual))
            if not cached:
                expected = actual
            assert actual == expected
            assert sum(len(row[1]) for row in actual) == 3
    # A pose-only cache is not an empty gold-event log.
    with VisualTrack(world, frames, True, cache_dir=tmp_path) as track:
        assert not track.cache_hit
        track.precompute()
    assert len(list(tmp_path.glob("*.nv14-track"))) == 2
    path = next(p for p in tmp_path.glob("*.nv14-track")
                if b'"gold_events":3' in p.read_bytes())
    original = path.read_bytes()
    path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with VisualTrack(world, frames, True, capture_gold=True, cache_dir=tmp_path) as track:
        assert not track.cache_hit
        track.precompute()
    assert path.read_bytes() == original


def initial_scene():
    return level("!0^150,134!0^190,134!0^230,134").initial_state(track_visuals=True).scene_snapshot()


@pytest.mark.parametrize("animated", [False, True])
def test_multi_ghost_ties_earlier_pickups_and_persistent_uncollected_gold(manifest, animated):
    system = GhostGoldSystem(initial_scene(), COLORS, manifest, animated=animated)
    system.update(0, [(0, (0,))])  # Ghost 0 ahead of primary.
    system.update(3, [(1, (0,)), (0, (1,))])  # Simultaneous pickups.
    rows = system.snapshot()
    assert [(r.key, r.color) for r in rows] == [((0, 0), COLORS[2]),
                                                ((1, 0), COLORS[1])]
    assert all(r.frame == 1 for r in rows)
    # Two ghosts collect the same duplicate simultaneously: one shared clip.
    system.update(7, [(1, (1,)), (2, (1,))])
    rows = system.snapshot()
    idle = [r for r in rows if r.key[1] == 0]
    assert [r.key[0] for r in idle] == [0, 2]
    effects = [r for r in rows if r.key[1]]
    assert len(effects) == int(animated)
    if animated:
        assert effects[0].frame == 2 and effects[0].color == COLORS[1]
        system.advance(27)
        assert next(r for r in system.snapshot() if r.key[1]).frame == 29
        system.advance(3)
    assert system.snapshot() == tuple(idle)
    before = system.snapshot()
    system.update(7, [])
    assert system.snapshot() is before  # No reconstruction of stationary rows.


def test_input_priority_hidden_pickups_and_large_ghost_masks(manifest):
    colors = tuple((i, 70, 180) for i in range(100))
    system = GhostGoldSystem(initial_scene(), colors, manifest, animated=True)
    system.update(1, [])
    first = system.snapshot()
    assert len(first) == 1 and first[0].color == colors[0]
    # Hidden owners do not change pixels, rebuild idle records or emit effects.
    system.update(1, [(70, (0,)), (2, (0,))])
    assert system.snapshot() is first
    system.update(1, [(0, (0,))])
    assert system.snapshot()[-1].color == colors[1]
    assert system.snapshot()[0].color == colors[0]
    system.advance(30)
    system.update(1, [(1, (0,))])
    assert system.snapshot()[-1].color == colors[3]  # Ghost 2 already collected.
    system.advance(30)
    # Collection order inside the update cannot affect which owner was visible.
    system.update(1, [(4, (0,)), (3, (0,))])
    assert system.snapshot()[-1].color == colors[5]
    assert len(system.snapshot()) == 2 and system.snapshot()[0].color == colors[3]


@pytest.mark.parametrize("offsets", [(0, 0, 0), (30, 0, 14), (0, 40, 60)])
def test_comparison_uses_displayed_tick_not_ahead_of_time_capture(manifest, offsets):
    from nv14_video import _ReplayComparison
    world = level("!0^145,134!0^185,134!0^225,134")
    sources = [([RIGHT] * 52, True), ([NEUTRAL] * 10 + [RIGHT] * 52, True),
               ([NEUTRAL] * 20 + [RIGHT] * 52, True)]
    states = [world.initial_state(track_visuals=True) for _ in sources]
    primary = world.initial_state(track_visuals=True)
    tracks = [VisualTrack(world, f, n, capture_gold=True) for f, n in sources[1:]]
    try:
        # Exit alignment precomputes these; start alignment captures ahead in
        # chunks. Neither is allowed to reveal future gold events.
        tracks[0].precompute()
        comparison = _ReplayComparison(world, primary, sources, offsets,
            ["#3568a8", "#b0394c"], secondary_tracks=tracks, capture_gold=True)
        system = GhostGoldSystem(primary.scene_snapshot(), COLORS[:2], manifest)
        while not comparison.done:
            comparison.step()
            tick = comparison.timeline_ticks
            for index, ((frames, neutral), offset) in enumerate(zip(sources, offsets)):
                local = tick - offset
                if 1 <= local <= len(frames) + neutral:
                    states[index].step(frames[local-1] if local <= len(frames) else NEUTRAL)
            masks = [s.static_state()["collected_gold_mask"] for s in states]
            system.update(primary.static_state()["collected_gold_mask"], comparison.gold_pickups)
            expected = {g: tuple(COLORS[j] for j in range(2) if not masks[j+1] >> g & 1)
                        for g in range(3) if masks[0] >> g & 1}
            expected = {g: c for g, c in expected.items() if c}
            assert {r.key[0]: r.color for r in system.snapshot()} == {g: c[0] for g, c in expected.items()}
    finally:
        for track in tracks:
            track.close()


@pytest.mark.parametrize("scale", [1, 2, 4])
def test_coloured_artwork_and_incremental_frames_match_full_redraw(manifest, scale):
    from nv14_render import SceneRenderer
    world = level("!0^150,134")
    scene = world.initial_state(track_visuals=True).scene_snapshot()
    scene["objects"][0]["visible"] = False
    retained = SceneRenderer(world.level_string, scale=scale)
    full = SceneRenderer(world.level_string, scale=scale, incremental=False)
    original = deepcopy(scene)
    for frame, color in [(1, COLORS[0]), (1, COLORS[0]), (1, COLORS[1]), (2, COLORS[0]),
                         (5, COLORS[0]), (14, COLORS[0]), (29, COLORS[0]), (None, None)]:
        rows = () if frame is None else (GoldVisual((0, 0), 150, 134, frame, color),)
        image = retained.render(scene, secondary_gold=rows)
        assert image.tobytes() == full.render(scene, secondary_gold=rows).tobytes()
        assert scene == original
        if frame == 1:
            crop = image.crop((146*scale, 130*scale, 154*scale, 138*scale))
            pixels = {crop.getpixel((x, y)) for x in range(crop.width) for y in range(crop.height)}
            from nv14_render import BACKGROUND, TERRAIN
            assert len(pixels - {BACKGROUND, TERRAIN}) > 1  # Original gold shading.
            assert all(other not in pixels for other in COLORS if other != color)
    assert retained.stats["command_cache_hits"] > 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg unavailable")
@pytest.mark.parametrize("mode", ["static", "animated"])
def test_real_encodes_are_identical_across_workers_and_cache(tmp_path, mode):
    from nv14_video import encode_replay_data_video
    world = level("!0^145,134!0^190,134!0^235,134!11^265,134,100,134")
    frames = [RIGHT] * 110
    options = dict(secondary_replays=[[NEUTRAL]*10+frames, [NEUTRAL]*20+frames],
                   secondary_gold=mode, particles=False, object_animations=False,
                   terminal_hold_seconds=.3, fps=60, replay_cache_dir=tmp_path/"cache", profile=True)
    hashes = []
    results = []
    for workers in (1, 2):
        path = tmp_path/f"{workers}.mp4"
        results.append(encode_replay_data_video(world, frames, path,
                                               render_workers=workers, **options))
        output = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-pix_fmt", "rgb24",
                                 "-f", "framemd5", "-"], capture_output=True, check=True)
        hashes.append(output.stdout)
    assert hashes[0] == hashes[1]
    assert results[0].replays == results[1].replays
    assert results[0].complete and all(r.complete for r in results[0].replays)
    if mode == "static":
        assert results[0].timings["frames_rendered"] == results[0].timeline_ticks
    else:
        assert results[0].timings["frames_rendered"] > results[0].timeline_ticks


def test_cli_and_toml_options(tmp_path, monkeypatch):
    import nv14_cli
    import nv14_video
    config = tmp_path/"video.toml"
    config.write_text('[encode-video]\nsecondary_gold = "animated"\n')
    args = nv14_cli.parse_arguments(["encode-video", "primary.txt", "--config", str(config)])
    assert args.secondary_gold == "animated"
    override = nv14_cli.parse_arguments(["encode-video", "primary.txt", "--config", str(config),
                                    "--secondary-gold", "static"])
    assert override.secondary_gold == "static"
    with pytest.raises(ValueError, match="secondary_gold"):
        nv14_video.encode_replay_data_video("invalid", [], tmp_path/"bad.mp4", secondary_gold=True)


def test_exact_v412_checkpoints_remain_compatible():
    from nv14_auto_parallel import _validate_checkpoint_identity
    from test_auto_checkpoint import _current_identity_with_splice_limit
    current = _current_identity_with_splice_limit(2)
    old = {**current, "optimiser_version": "4.12",
           "optimiser_build_sha256": "b03fff98694b5484ce994a35ff3858133c7e877a296d1b64d7da0f74f44e9caf"}
    _validate_checkpoint_identity(old, current)

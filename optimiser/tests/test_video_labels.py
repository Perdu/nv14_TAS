"""Following GUI labels: pixels, visibility, configuration and real encodes."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest

from nv14_engine import InputFrame
import nv14_video as video

LEVEL = "0" * 713 + "|5^100,100"


def scene(x=100., y=100.):
    return {"objects": [], "visual": {"x": x, "y": y, "frame": 1,
            "visible": True, "facing": 1, "rotation_deg": 0.}}


@pytest.mark.parametrize("scale,quality", [(1, "exact"), (2, "exact"), (4, "fast")])
def test_labels_follow_match_full_redraw_and_clear_without_trails(scale, quality):
    pytest.importorskip("PIL")
    from nv14_render import SceneRenderer
    retained = SceneRenderer(LEVEL, scale=scale, render_quality=quality)
    full = SceneRenderer(LEVEL, scale=scale, render_quality=quality, incremental=False)
    for tick in range(6):
        state = scene(100. + tick*7, 100. + tick*3)
        ghost = {**state["visual"], "label": "Baseline", "color": (53, 104, 168)}
        opts = dict(primary_label="Optimised" if tick < 5 else None,
                    secondary_players=[ghost] if tick < 4 else [],
                    show_primary_player=tick != 3)
        before = deepcopy((state, opts))
        actual = retained.render(state, **opts)
        assert actual.tobytes() == full.render(state, **opts).tobytes()
        assert (state, opts) == before
        buf = bytearray(actual.width*actual.height*3)
        retained.render_into(state, buf, **opts)
        assert bytes(buf) == actual.tobytes()
        if tick == 0:
            labels = [entry[1][0] for key, entry in retained._command_groups.items() if key[0] == "label"]
            assert len(labels) == 2
            from nv14_render_commands import intersects
            assert not intersects(labels[0].bounds, labels[1].bounds)
            for command, color in zip(labels, [(0, 0, 0), (53, 104, 168)]):
                colors = actual.crop(command.bounds).getcolors(100000)
                assert colors is not None and color in {rgb for count, rgb in colors}
    assert retained.stats["dirty_frames"] > 0
    assert not any(key[0] == "label" for key in retained._command_groups)
    # Turning all labels off restores exactly the original render.
    assert actual.tobytes() == full.render(state).tobytes()


def test_font_is_optional_and_labels_hide_with_players(monkeypatch):
    from PIL import ImageFont
    from nv14_render import SceneRenderer
    renderer = SceneRenderer(LEVEL)
    real = ImageFont.truetype
    calls = []
    def load(*args, **kwargs):
        calls.append(args[0])
        return real(*args, **kwargs)
    monkeypatch.setattr(ImageFont, "truetype", load)
    renderer.render(scene())
    renderer.render(scene(), primary_label="Hidden", show_primary_player=False)
    hidden = scene()
    hidden["visual"]["visible"] = False
    renderer.render(hidden, primary_label="Dead")
    assert calls == []
    for tick in range(3):
        renderer.render(scene(100+tick), primary_label="Same label")
    assert len(calls) == 1
    assert Path(calls[0]).name == "n_gui.ttf"
    assert len(renderer._label_images) == 1


def test_long_edge_labels_stay_inside_frame_and_use_original_font():
    from nv14_render import SceneRenderer
    renderer = SceneRenderer(LEVEL)
    for x, y in ((0, 0), (792, 600), (400, 10)):
        state = scene(x, y)
        renderer.render(state, primary_label="W"*128, label_size=32,
            secondary_players=[{**state["visual"], "label": "Second"}])
        labels = [entry[1][0] for key, entry in renderer._command_groups.items() if key[0] == "label"]
        for label in labels:
            left, top, right, bottom = label.bounds
            assert 0 <= left < right <= 792 and 0 <= top < bottom <= 600
    a = renderer._label_sprite("René £10 – 東京", (0, 0, 0), 8)
    b = renderer._label_sprite("René £10 – ??", (0, 0, 0), 8)
    assert a.tobytes() == b.tobytes()


@pytest.mark.parametrize("options,error", [
    ({"primary_label": 1}, "strings"),
    ({"primary_label": "two\nlines"}, "single-line"),
    ({"primary_label": "x"*129}, "128"),
    ({"secondary_labels": "Name"}, "sequence"),
    ({"secondary_labels": []}, "one label"),
    ({"secondary_labels": [False]}, "strings"),
    ({"label_size": True}, "label_size"),
    ({"label_size": 5}, "label_size"),
    ({"label_size": 33}, "label_size"),
])
def test_invalid_labels_rejected_before_encoding(tmp_path, monkeypatch, options, error):
    output = tmp_path / "out.mp4"
    output.write_bytes(b"keep")
    monkeypatch.setattr(video, "_encode_frames", lambda *a, **k: pytest.fail("started encoding"))
    with pytest.raises((TypeError, ValueError), match=error):
        video.encode_replay_data_video(LEVEL, [], output, secondary_replays=[[]], **options)
    assert output.read_bytes() == b"keep"


def test_file_data_cli_and_toml_label_forwarding(tmp_path, monkeypatch):
    import nv14_cli
    calls = []
    monkeypatch.setattr(video, "_encode_frames", lambda *a, **k: calls.append(k))
    primary = tmp_path / "primary.txt"
    primary.write_text(f"$Labels#tests##{LEVEL}#1:0#")
    second = tmp_path / "second.txt"
    second.write_text("1:0")
    video.encode_replay_video(primary, tmp_path / "file.mp4", secondary_replays=[second],
        primary_label="New", secondary_labels=["Old"], label_size=12)
    video.encode_replay_data_video(LEVEL, "1:0", tmp_path / "data.mp4", secondary_replays=["1:0"],
        primary_label="New", secondary_labels=["Old"], label_size=12)
    assert all((c["primary_label"], c["secondary_labels"], c["label_size"]) ==
               ("New", ("Old",), 12) for c in calls)
    config = tmp_path / "labels.toml"
    config.write_text('[encode-video]\nprimary_label = "New"\n'
                     'secondary_replays = ["one.txt"]\nsecondary_labels = [""]\nlabel_size = 12\n')
    args = nv14_cli.parse_arguments(["encode-video", str(primary), "--config", str(config),
        "--secondary-replay", "two.txt", "--secondary-label", "Other", "--primary-label", "Best"])
    assert (args.primary_label, args.secondary_labels, args.label_size) == ("Best", ["", "Other"], 12)
    captured = []
    def encode(*a, **k):
        captured.append(k)
        return video.VideoEncodeResult(tmp_path / "out.mp4", 1, 1, 1, 40, 792, 600,
                                       "input_end", False, False, False)
    monkeypatch.setattr(video, "encode_replay_video", encode)
    video.run_video_encode(args)
    assert captured[0]["primary_label"] == "Best"
    assert captured[0]["secondary_labels"] == ["", "Other"]
    assert captured[0]["label_size"] == 12


@pytest.mark.parametrize("alignment", ["start", "exit"])
@pytest.mark.parametrize("label_position", ["follow", "top-left"])
def test_real_labelled_encodes_match_across_workers_and_session(tmp_path, alignment, label_position):
    pytest.importorskip("_nv14_native")
    pytest.importorskip("PIL")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is optional")
    tiles = ["0"] * 713
    for column in range(31):
        tiles[column*23+5] = "1"
    level = "".join(tiles) + "|5^100,134!11^200,134,100,134"
    runs = [[InputFrame()]*delay + [InputFrame(right=True)]*60 for delay in (0, 9, 4)]
    opts = dict(secondary_replays=runs[1:], replay_alignment=alignment,
        primary_label="Optimised", secondary_labels=["Baseline", "Alternative"],
        label_position=label_position,
        terminal_hold_seconds=.1, particles=False, object_animations=False,
        replay_cache_dir=tmp_path / "cache", fps=60)
    hashes, outcomes = [], []
    for workers in (1, 2):
        with video.VideoEncodeSession(render_workers=workers) as session:
            output = tmp_path / f"{workers}.mp4"
            result = session.encode_replay_data_video(level, runs[0], output, **opts)
            assert [r.label for r in result.replays] == ["Optimised", "Baseline", "Alternative"]
            assert all(r.complete for r in result.replays)
            assert result.render_workers == workers
            raw = subprocess.run([ffmpeg, "-v", "error", "-i", str(output), "-f", "rawvideo",
                                  "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
            hashes.append(hashlib.sha256(raw).hexdigest())
            outcomes.append(result.replays)
            # A reused renderer/cache must use this export's labels and clear
            # the previous ones, without putting captions into pose cache keys.
            changed = dict(opts, primary_label=None, secondary_labels=["", ""])
            plain = session.encode_replay_data_video(level, runs[0], tmp_path / f"plain{workers}.mp4", **changed)
            assert all(r.label is None for r in plain.replays)
            assert plain.replays == tuple(replace(r, label=None) for r in result.replays)
            assert session.last_profile["replay_cache_hits"] == 2
            assert session.last_profile["renderer_reused"]
    assert hashes[0] == hashes[1]
    assert outcomes[0] == outcomes[1]


def test_exit_delay_keeps_each_label_with_its_own_track():
    from types import SimpleNamespace
    playback = object.__new__(video._ReplayComparison)
    playback.colors = [(1, 2, 3), (4, 5, 6)]
    playback.labels = ["Early", "Late"]
    playback.tracks = [SimpleNamespace(offset=n, visual=scene()["visual"]) for n in (2, 0, 4)]
    for tick, labels, primary in [(0, ["Early"], False), (3, ["Early"], True),
                                  (5, ["Early", "Late"], True)]:
        playback.timeline_ticks = tick
        options = playback.render_options()
        assert [p["label"] for p in options["secondary_players"]] == labels
        assert options["show_primary_player"] == primary

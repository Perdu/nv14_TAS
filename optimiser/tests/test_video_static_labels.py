"""Static top-left legends retain their text, order and placement over time."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_video_labels import LEVEL, scene
import nv14_video as video


@pytest.mark.parametrize("scale,quality", [(1, "exact"), (2, "exact"), (4, "fast")])
def test_static_legend_ignores_positions_and_visibility_and_switches_cleanly(scale, quality):
    from nv14_render import SceneRenderer
    renderer = SceneRenderer(LEVEL, scale=scale, render_quality=quality)
    full = SceneRenderer(LEVEL, scale=scale, render_quality=quality, incremental=False)
    initial = None
    for tick in range(4):
        state = scene(350+tick*10, 400+tick)
        state["visual"]["visible"] = tick != 3
        ghosts = [{**state["visual"], "x": 450-tick*10, "visible": tick > 0,
                   "color": (53, 104, 168), "label": "Baseline"},
                  {**state["visual"], "label": "", "color": (140, 51, 67)}]
        options = dict(primary_label="TAS", secondary_players=ghosts,
                       show_primary_player=tick != 0, label_position="top-left")
        before = deepcopy((state, options))
        image = renderer.render(state, **options)
        assert image.tobytes() == full.render(state, **options).tobytes()
        buffer = bytearray(image.width*image.height*3)
        renderer.render_into(state, buffer, **options)
        assert bytes(buffer) == image.tobytes()
        assert (state, options) == before
        command = renderer._command_groups[("label-legend", 0)][1][0]
        pixels = image.crop(command.bounds).tobytes()
        if initial is None:
            initial = (command.bounds, pixels, command.args[0])
            assert command.bounds[:2] == (32*scale, 32*scale)
        else:
            assert (command.bounds, pixels) == initial[:2]
            assert command.args[0] is initial[2]
    # Switching modes/removing labels restores the old legend area exactly.
    for position in ("follow", "top-left"):
        options.update(label_position=position, primary_label=None, secondary_players=[])
        assert renderer.render(state, **options).tobytes() == full.render(state, **options).tobytes()
        assert ("label-legend", 0) not in renderer._command_groups


def test_twenty_one_large_labels_wrap_into_columns_without_clipping():
    from nv14_render import SceneRenderer
    renderer = SceneRenderer(LEVEL)
    state = scene(600, 500)
    ghosts = [{**state["visual"], "label": f"{i:02}: " + "Long name "*8}
              for i in range(1, 21)]
    renderer.render(state, primary_label="TAS", secondary_players=ghosts,
                    label_size=32, label_position="top-left")
    command = renderer._command_groups[("label-legend", 0)][1][0]
    assert command.bounds[0:2] == (32, 32)
    assert command.bounds[2] <= 760 and command.bounds[3] <= 568
    # Both columns contain artwork (large labels cannot fit in one column).
    assert command.args[0].crop((370, 0, command.args[0].width, 100)).getbbox()


def test_static_exit_alignment_includes_not_yet_started_runs():
    playback = object.__new__(video._ReplayComparison)
    playback.colors = [(53, 104, 168), (140, 51, 67)]
    playback.labels = ["Early", "Late"]
    playback.tracks = [SimpleNamespace(offset=n, visual=scene()["visual"]) for n in (2, 0, 4)]
    before = deepcopy([t.visual for t in playback.tracks])
    for tick in (0, 3, 5):
        playback.timeline_ticks = tick
        options = playback.render_options("top-left")
        assert [p["label"] for p in options["secondary_players"]] == ["Early", "Late"]
        assert options["secondary_players"][1]["visible"] == (tick > 4)
        assert options["show_primary_player"] == (tick > 2)
    assert [t.visual for t in playback.tracks] == before


def test_static_position_api_cli_and_toml_forwarding(tmp_path, monkeypatch):
    import nv14_cli
    calls = []
    monkeypatch.setattr(video, "_encode_frames", lambda *a, **k: calls.append(k))
    primary = tmp_path / "primary.txt"
    primary.write_text(f"$Labels#tests##{LEVEL}#1:0#")
    video.encode_replay_video(primary, tmp_path / "file.mp4",
                              primary_label="TAS", label_position="top-left")
    video.encode_replay_data_video(LEVEL, "1:0", tmp_path / "data.mp4",
                                   primary_label="TAS", label_position="top-left")
    assert all(c["label_position"] == "top-left" for c in calls)
    config = tmp_path / "static.toml"
    config.write_text('[encode-video]\nprimary_label = "TAS"\nlabel_position = "top-left"\n')
    args = nv14_cli.parse_arguments(["encode-video", str(primary), "--config", str(config)])
    assert args.label_position == "top-left"
    captured = []
    def encode(*a, **k):
        captured.append(k)
        return video.VideoEncodeResult(tmp_path / "out.mp4", 1, 1, 1, 40, 792, 600,
                                       "input_end", False, False, False)
    monkeypatch.setattr(video, "encode_replay_video", encode)
    video.run_video_encode(args)
    assert captured[0]["label_position"] == "top-left"
    assert nv14_cli.parse_arguments(["encode-video", str(primary), "--config", str(config),
                                    "--label-position", "follow"]).label_position == "follow"
    assert nv14_cli.parse_arguments(["encode-video", str(primary)]).label_position == "follow"


@pytest.mark.parametrize("position", ["static", "top-right", None, 1])
def test_invalid_position_fails_before_output(tmp_path, monkeypatch, position):
    output = tmp_path / "keep.mp4"
    output.write_bytes(b"keep")
    monkeypatch.setattr(video, "_encode_frames", lambda *a, **k: pytest.fail("started encoding"))
    with pytest.raises(ValueError, match="label_position"):
        video.encode_replay_data_video(LEVEL, "1:0", output, label_position=position)
    assert output.read_bytes() == b"keep"

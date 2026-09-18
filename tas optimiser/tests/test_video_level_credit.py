"""Userlevel metadata survives file/API loading, retained frames and workers."""
import subprocess

import pytest

import nv14_video as video
from nv14_dump import load_player_dump_source
from test_video import export_harness
from test_player_dump import write_database, write_movie
from test_video_session_v410 import real_ffmpeg

LEVEL = "0" * 713 + "|5^100,100"


@pytest.mark.parametrize("suffix", ["#", "", "#99:0|"])
def test_api_record_uses_explicit_replay_and_preserves_metadata(tmp_path, export_harness, suffix):
    video.encode_replay_data_video(f"$Map name#René#action#{LEVEL}{suffix}",
        "2:0", tmp_path / "out.mp4", final_neutral=False, render_workers=1)
    assert export_harness.parsed == [LEVEL]
    assert export_harness.renders == [1, 2]
    assert export_harness.credits == ["Map name  ( by René )"] * 2


def test_file_credit_comes_from_primary_and_survives_terminal_hold(tmp_path, export_harness):
    primary = tmp_path / "primary.txt"
    secondary = tmp_path / "secondary.txt"
    primary.write_text(f"$Primary#Creator##{LEVEL}#1:0#")
    secondary.write_text(f"$Other title#Other author##{LEVEL}#1:0#")
    export_harness.terminal_at, export_harness.complete = 1, True
    result = video.encode_replay_video(primary, tmp_path / "out.mp4",
        secondary_replays=[secondary], terminal_hold_seconds=.1, render_workers=1)
    assert result.video_frames == 5
    assert export_harness.credits == ["Primary  ( by Creator )"] * 5


@pytest.mark.parametrize("kind", ["packed", "ltm"])
def test_database_credit_is_retained(tmp_path, kind):
    database = write_database(tmp_path / "levels.txt")
    if kind == "ltm":
        source = write_movie(tmp_path / "00-0.ltm", ["|K20|", "|K|", "|Kff53|"])
    else:
        source = tmp_path / "00-0.txt"
        source.write_text("1:0")
    loaded = load_player_dump_source(source, levels_file=database)
    assert (loaded.level_name, loaded.level_author) == ("00-0 Dump test", "tests")
    assert loaded.level_string.startswith("0")


@pytest.mark.parametrize("name,author,expected", [
    (" Map\nname ", " A\tB ", "Map name  ( by A B )"),
    ("Name", "", "Name"), ("", "Author", "( by Author )"), ("", "", None),
])
def test_missing_or_multiline_metadata(name, author, expected):
    assert video._level_credit(name, author) == expected


@pytest.mark.parametrize("scale", [1, 2, 4])
def test_credit_pixels_layering_and_incremental_replacement(scale):
    from PIL import ImageChops
    from nv14_render import SceneRenderer
    retained = SceneRenderer(LEVEL, scale=scale)
    full = SceneRenderer(LEVEL, scale=scale, incremental=False)
    scene = {"objects": [], "visual": {"x": 100., "y": 100., "frame": 1, "visible": False}}
    plain = retained.render(scene)
    for caption in ("Example level  ( by Author )", "Short", "W"*300, None):
        actual = retained.render(scene, level_credit=caption)
        assert actual.tobytes() == full.render(scene, level_credit=caption).tobytes()
        diff = ImageChops.difference(actual, plain).getbbox()
        if caption:
            assert diff and diff[1] >= 580*scale and diff[3] < 600*scale
            assert diff[0] >= 24*scale and diff[2] <= 768*scale
            assert abs((diff[0]+diff[2])/2 - 396*scale) <= scale
            # The glyph itself, above the solid bottom-border terrain.
            assert (0, 0, 0) in {rgb for _, rgb in actual.crop(diff).getcolors(100000)}
        else:
            assert diff is None
        output = bytearray(actual.width*actual.height*3)
        retained.render_into(scene, output, level_credit=caption)
        assert bytes(output) == actual.tobytes()


@pytest.mark.parametrize("workers", [1, 2])
def test_real_encodes_and_reused_session_do_not_leak_credits(tmp_path, real_ffmpeg, workers):
    from nv14_video_session import VideoEncodeSession
    def pixels(path):
        result = subprocess.run([real_ffmpeg, "-v", "error", "-i", str(path),
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
            capture_output=True, timeout=30, check=True)
        return result.stdout
    with VideoEncodeSession(render_workers=workers) as session:
        for index, data in enumerate((f"$First map#Alice##{LEVEL}#", f"$Second map#Bob##{LEVEL}#", LEVEL)):
            out = tmp_path / f"reuse-{index}.mp4"
            result = session.encode_replay_data_video(data, "3:0", out,
                final_neutral=False, terminal_hold_seconds=0, render_workers=workers, profile=True)
            fresh = tmp_path / f"fresh-{index}.mp4"
            video.encode_replay_data_video(data, "3:0", fresh,
                final_neutral=False, terminal_hold_seconds=0, render_workers=1)
            assert result.video_frames == 3
            actual = pixels(out)
            assert actual == pixels(fresh)
            footer = actual[580*792*3:592*792*3]
            assert result.timings["renderer_reused"] == bool(index)
            if index < 2:
                assert min(footer) < 50
            else:
                assert min(footer) > 50

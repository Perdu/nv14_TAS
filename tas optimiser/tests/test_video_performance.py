"""v4.09 encoding controls and complete serial/parallel output equivalence."""
from dataclasses import asdict
from pathlib import Path
import shutil
import subprocess

import pytest

from nv14_engine import InputFrame
import nv14_video as video
from test_video import export_harness


def test_render_options_cli_toml_defaults_overrides_and_forwarding(tmp_path, monkeypatch):
    import nv14_cli

    config = tmp_path / "video.toml"
    config.write_text('[encode-video]\nrender_workers = 3\nrender_quality = "fast"\n'
                      'replay_cache_dir = "pose-cache"\npreset = "slow"\n')
    args = nv14_cli.parse_arguments(["encode-video", "demo.txt", "--config", str(config)])
    assert args.render_workers == 3
    assert args.render_quality == "fast"
    assert args.replay_cache_dir == Path("pose-cache")
    args = nv14_cli.parse_arguments(["encode-video", "demo.txt", "--config", str(config),
        "--render-workers", "2", "--render-quality", "exact", "--replay-cache-dir", "new-cache"])
    assert args.render_workers == 2 and args.render_quality == "exact"
    assert args.replay_cache_dir == Path("new-cache")
    calls = []

    def encode(*positional, **kwargs):
        calls.append(kwargs)
        return video.VideoEncodeResult(Path("test.mp4"), 1, 1, 1, 40, 792, 600,
                                       "input_end", False, False, False)

    monkeypatch.setattr(video, "encode_replay_video", encode)
    video.run_video_encode(args)
    assert calls[0]["render_workers"] == 2
    assert calls[0]["render_quality"] == "exact"
    assert calls[0]["replay_cache_dir"] == Path("new-cache")
    assert calls[0]["preset"] == "slow"
    plain = nv14_cli.parse_arguments(["encode-video", "demo.txt"])
    assert plain.render_workers == 8
    assert plain.render_quality == "fast"
    assert plain.replay_cache_dir is None
    assert plain.preset == "medium"


@pytest.mark.parametrize("api", ["data", "file"])
def test_public_apis_forward_performance_controls(tmp_path, monkeypatch, api):
    calls = []
    sentinel = object()

    def encode(*positional, **kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(video, "_encode_frames", encode)
    kwargs = dict(render_workers=2, render_quality="fast", replay_cache_dir=tmp_path / "cache")
    level = "0" * 713 + "|5^100,100"
    if api == "data":
        result = video.encode_replay_data_video(level, "1:0", tmp_path / "out.mp4", **kwargs)
    else:
        source = tmp_path / "run.txt"
        source.write_text(level + "#1:0")
        result = video.encode_replay_video(source, tmp_path / "out.mp4", **kwargs)
    assert result is sentinel
    for key, value in kwargs.items():
        assert calls[0][key] == value
    assert calls[0]["preset"] == "medium"


@pytest.mark.parametrize("options", [
    {"render_workers": -1}, {"render_workers": 65}, {"render_workers": True},
    {"render_workers": 1.5}, {"render_workers": "2"},
    {"render_quality": "approximate"}, {"render_quality": None},
])
def test_invalid_performance_options_preserve_existing_output(tmp_path, options):
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"previous successful export")
    with pytest.raises(ValueError, match="render_workers|render_quality"):
        video.encode_replay_data_video("0" * 713 + "|5^100,100", "1:0", output, **options)
    assert output.read_bytes() == b"previous successful export"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["existing.mp4"]


@pytest.mark.parametrize("preset", [None, "veryfast", "veryslow"])
def test_performance_changes_preserve_default_and_explicit_ffmpeg_presets(
        tmp_path, export_harness, preset):
    kwargs = {} if preset is None else {"preset": preset}
    video.encode_replay_data_video("level", "2:0", tmp_path / "out.mp4",
                                  render_workers=1, **kwargs)
    command = export_harness.launches[-1]
    assert command[command.index("-preset") + 1] == (preset or "medium")
    assert command[command.index("-crf") + 1] == "18"
    assert command[command.index("-c:v") + 1] == "libx264"


def test_automatic_worker_policy_keeps_short_exports_serial_and_parallelises_long_comparisons(monkeypatch):
    monkeypatch.setattr(video.os, "sched_getaffinity", lambda pid: set(range(16)), raising=False)
    source = lambda ticks: ([None] * ticks, False)
    assert video._worker_count(0, [source(159)] * 100) == 1
    assert video._worker_count(0, [source(399)] * 20) == 1
    assert video._worker_count(0, [source(400)] * 20) == 4
    assert video._worker_count(0, [source(8000)]) == 4
    assert video._worker_count(2, [source(1)]) == 2
    monkeypatch.setattr(video.os, "sched_getaffinity", lambda pid: {0}, raising=False)
    assert video._worker_count(0, [source(400)] * 20) == 1
    monkeypatch.delattr(video.os, "sched_getaffinity")
    monkeypatch.setattr(video.os, "cpu_count", lambda: 3)
    assert video._worker_count(0, [source(400)] * 20) == 2


def _decoded_rgb_hashes(ffmpeg, path):
    # Hash each decoded RGB frame instead of accumulating full-resolution raw
    # frames in test memory. The MD5 muxer includes frame index, size and hash.
    result = subprocess.run([ffmpeg, "-v", "error", "-i", str(path),
        "-map", "0:v:0", "-pix_fmt", "rgb24", "-f", "framemd5", "-"],
        check=True, capture_output=True, text=True, timeout=30)
    return [line for line in result.stdout.splitlines() if line and not line.startswith("#")]


@pytest.mark.parametrize("alignment", ["start", "exit"])
@pytest.mark.parametrize("quality", ["exact", "fast"])
def test_full_encode_serial_parallel_decoded_frames_and_results_match(
        tmp_path, alignment, quality):
    native = pytest.importorskip("_nv14_native")
    pytest.importorskip("PIL")
    if not hasattr(native.NativeState, "capture_visual_frames"):
        pytest.skip("v4.09 native visual capture extension is required")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is optional")
    if "libx264" not in subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=15).stdout:
        pytest.skip("FFmpeg has no libx264")
    tiles = ["0"] * 713
    for column in range(31):
        tiles[column * 23 + 5] = "1"
    # Running, a gold burst, switch/door clips and the terminal tail exercise
    # immutable cosmetic snapshots and different per-worker sprite cache histories.
    level = native.parse_level_string("".join(tiles) + "|5^100,134!0^140,134!11^200,134,100,134",
                                     simulate_enemies=True)
    sources = [[InputFrame()] * delay + [InputFrame(right=True)] * 60 for delay in (0, 9, 4)]
    durations = [video._completion_ticks(level, frames, True, index)
                 for index, frames in enumerate(sources)]
    outputs = []
    results = []
    cache_dir = tmp_path / "poses"
    for workers in (1, 2):
        result = video.encode_replay_data_video(level, sources[0], tmp_path / f"{workers}.mp4",
            secondary_replays=sources[1:], replay_alignment=alignment,
            secondary_colors=["#3568a8", "#97436a"], fps=60,
            particles=True, particle_seed=781, object_animations=True,
            terminal_hold_seconds=.15, render_workers=workers, render_quality=quality,
            replay_cache_dir=cache_dir)
        assert result.render_workers == workers
        assert result.render_quality == quality
        assert result.complete and all(item.complete for item in result.replays)
        assert [item.simulated_ticks for item in result.replays] == durations
        offsets = [max(durations) - ticks for ticks in durations] if alignment == "exit" else [0, 0, 0]
        assert [item.start_offset_ticks for item in result.replays] == offsets
        assert result.timeline_ticks == max(durations)
        assert result.video_frames == (max(durations) * 60 + 39) // 40 + 9
        decoded = _decoded_rgb_hashes(ffmpeg, result.output_path)
        assert len(decoded) == result.video_frames
        outputs.append(decoded)
        result_values = asdict(result)
        for key in ("output_path", "render_workers"):
            result_values.pop(key)
        results.append(result_values)
    assert outputs[0] == outputs[1]
    assert results[0] == results[1]
    assert len(list(cache_dir.glob("*.nv14-track"))) == 2


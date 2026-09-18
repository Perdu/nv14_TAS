"""Reusable exports, measured worker selection and v4.10 public controls."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess
import threading

import pytest

from nv14_engine import InputFrame
import nv14_video as video
from nv14_video_session import VideoEncodeSession, choose_workers
from test_video import export_harness


@pytest.fixture(scope="module")
def real_ffmpeg():
    pytest.importorskip("PIL")
    native = pytest.importorskip("_nv14_native")
    if not hasattr(native.NativeState, "scene_snapshot"):
        pytest.skip("native scene snapshots are unavailable")
    executable = shutil.which("ffmpeg")
    if not executable:
        pytest.skip("FFmpeg is optional")
    encoders = subprocess.run([executable, "-hide_banner", "-encoders"],
                              capture_output=True, text=True, timeout=15, check=True)
    if "libx264" not in encoders.stdout:
        pytest.skip("libx264 is unavailable")
    return executable


def _level():
    tiles = ["0"] * 713
    for column in range(31):
        tiles[column * 23 + 5] = "1"
    return "".join(tiles) + "|5^100,134!0^112,134!11^650,134,600,134"


def _decoded_frames(ffmpeg, path):
    result = subprocess.run([ffmpeg, "-v", "error", "-i", str(path),
        "-map", "0:v:0", "-pix_fmt", "rgb24", "-f", "framemd5", "-"],
        capture_output=True, text=True, timeout=30, check=True)
    return [tuple(field.strip() for field in line.split(","))
            for line in result.stdout.splitlines() if line and not line.startswith("#")]


def test_serial_session_reuses_preparation_resets_replay_and_records_opt_in_profile(tmp_path, export_harness):
    with VideoEncodeSession(render_workers=1, render_memory_mib=32) as session:
        first = session.encode_replay_data_video("level", "3:0", tmp_path / "first.mp4",
                                                final_neutral=False)
        renderer = next(iter(session._renderers.values()))
        level = next(iter(session._levels.values()))
        assert first.timings is None
        assert session.last_profile["renderer_reused"] is False
        assert session.last_profile["frames_rendered"] == 3
        assert session._pool is None
        second = session.encode_replay_data_video("level", "3:0", tmp_path / "second.mp4",
                                                 final_neutral=False, profile=True)
        assert next(iter(session._renderers.values())) is renderer
        assert next(iter(session._levels.values())) is level
        assert export_harness.parsed == ["level"]
        assert export_harness.renders == [1, 2, 3, 1, 2, 3]
        assert export_harness.states[0] is not export_harness.states[1]
        assert export_harness.states[0].inputs == export_harness.states[1].inputs
        assert second.timings == session.last_profile
        assert second.timings["renderer_reused"] is True
        assert second.timings["frames_rendered"] == second.video_frames == 3
        assert second.timings["transport"] == "serial"
        assert second.timings["worker_decision"] == "explicit"
        assert second.timings["frame_delivery"] == "raw"
        assert isinstance(second.timings["renderer_stats"], dict)
        for key in ("render_seconds", "write_seconds", "preparation_seconds", "total_seconds"):
            assert second.timings[key] >= 0
        second.timings["render_seconds"] = -1
        assert session.last_profile["render_seconds"] >= 0
    assert session._renderers == session._levels == {}
    session.close()  # Closing twice remains harmless.
    with pytest.raises(RuntimeError, match="closed"):
        session.encode_replay_data_video("level", "1:0", tmp_path / "closed.mp4")
    assert not (tmp_path / "closed.mp4").exists()


def test_real_session_reuses_spawned_pool_and_produces_identical_fresh_replays(tmp_path, real_ffmpeg):
    frames = [InputFrame(right=True, jump=3 <= tick < 8, jump_trigger=tick == 3)
              for tick in range(18)]
    with VideoEncodeSession(render_workers=2, render_memory_mib=32) as session:
        first = session.encode_replay_data_video(_level(), frames, tmp_path / "first.mp4",
                                                final_neutral=False, fps=60, profile=True)
        renderer = next(iter(session._renderers.values()))
        level = next(iter(session._levels.values()))
        pool = session._pool
        executor = pool._executor
        processes = dict(executor._processes)
        seed_directory = Path(pool._directory.name)
        assert len(processes) == 2
        assert all(process.is_alive() for process in processes.values())
        second = session.encode_replay_data_video(_level(), frames, tmp_path / "second.mp4",
                                                 final_neutral=False, fps=60, profile=True)
        assert next(iter(session._renderers.values())) is renderer
        assert next(iter(session._levels.values())) is level
        assert session._pool is pool and pool._executor is executor
        assert executor._processes == processes
        assert len(pool._configs) == 1
        assert first.timings["renderer_reused"] is False
        assert second.timings["renderer_reused"] is True
        assert first.render_workers == second.render_workers == 2
        assert first.timings["transport"] == second.timings["transport"] == "shared_memory"
        assert first.simulated_ticks == second.simulated_ticks == len(frames)
        assert first.video_frames == second.video_frames == 27
        assert not first.dead and not second.dead
        assert not first.complete and not second.complete
        decoded = _decoded_frames(real_ffmpeg, first.output_path)
        assert len(decoded) == first.video_frames
        assert len({frame[-1] for frame in decoded}) > 1
        assert decoded == _decoded_frames(real_ffmpeg, second.output_path)
    assert all(not process.is_alive() for process in processes.values())
    assert not seed_directory.exists()
    assert session._pool is None


def test_session_rejects_concurrent_export_and_close_without_disturbing_active_export(
        tmp_path, export_harness, monkeypatch):
    import nv14_render

    entered, release = threading.Event(), threading.Event()
    original = nv14_render.SceneRenderer.render

    def render(self, *args, **kwargs):
        entered.set()
        if not release.wait(10):
            raise RuntimeError("test did not release renderer")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(nv14_render.SceneRenderer, "render", render)
    rejected_output = tmp_path / "concurrent.mp4"
    rejected_output.write_bytes(b"previous video")
    with VideoEncodeSession(render_workers=1) as session, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(session.encode_replay_data_video,
                                 "level", "2:0", tmp_path / "active.mp4")
        try:
            assert entered.wait(10)
            with pytest.raises(RuntimeError, match="already in use"):
                session.encode_replay_data_video("level", "1:0", rejected_output)
            with pytest.raises(RuntimeError, match="active"):
                session.close()
            assert len(export_harness.states) == len(export_harness.processes) == 1
            assert rejected_output.read_bytes() == b"previous video"
        finally:
            release.set()
        assert future.result(timeout=10).simulated_ticks == 3
        assert session._active is False


@pytest.mark.parametrize("failure", ["render", "encoder"])
def test_session_recovers_after_failed_export(tmp_path, export_harness, failure):
    destination = tmp_path / "out.mp4"
    destination.write_bytes(b"previous video")
    with VideoEncodeSession(render_workers=1) as session:
        if failure == "render":
            export_harness.render_error = RuntimeError("failed renderer")
        else:
            export_harness.exit_code = 1
        with pytest.raises(RuntimeError):
            session.encode_replay_data_video("level", "3:0", destination)
        assert destination.read_bytes() == b"previous video"
        assert session._active is False
        assert session.last_profile is None
        assert list(tmp_path.iterdir()) == [destination]
        export_harness.render_error = None
        export_harness.exit_code = 0
        result = session.encode_replay_data_video("level", "3:0", destination, profile=True)
        assert result.simulated_ticks == 4
        assert result.timings["renderer_reused"] is True
        assert export_harness.parsed == ["level"]
        assert export_harness.states[0] is not export_harness.states[1]
        assert destination.read_bytes() == b"valid mocked MP4"
        assert all(process.poll() is not None and process.stdin.closed
                   for process in export_harness.processes)


@pytest.mark.parametrize("options,error", [
    ({"render_memory_mib": 15}, ValueError),
    ({"render_memory_mib": 65537}, ValueError),
    ({"render_memory_mib": True}, ValueError),
    ({"render_memory_mib": 32.0}, ValueError),
    ({"render_memory_mib": "32"}, ValueError),
    ({"profile": 1}, ValueError), ({"profile": "true"}, ValueError),
    ({"profile": None}, ValueError), ({"session": object()}, TypeError),
])
def test_new_option_preflight_preserves_destination_and_starts_no_work(tmp_path, export_harness, options, error):
    destination = tmp_path / "existing.mp4"
    destination.write_bytes(b"previous video")
    with pytest.raises(error, match="render_memory_mib|profile|session"):
        video.encode_replay_data_video("level", "2:0", destination, **options)
    assert destination.read_bytes() == b"previous video"
    assert list(tmp_path.iterdir()) == [destination]
    assert export_harness.states == export_harness.processes == export_harness.parsed == []


def test_memory_and_profile_cli_toml_defaults_overrides_and_forwarding(tmp_path, monkeypatch, capsys):
    import nv14_cli

    configuration = tmp_path / "video.toml"
    configuration.write_text('[encode-video]\nrender_memory_mib = 48\nprofile = true\n')
    configured = nv14_cli.parse_arguments(["encode-video", "demo.txt", "--config", str(configuration)])
    assert configured.render_memory_mib == 48 and configured.profile is True
    override = nv14_cli.parse_arguments(["encode-video", "demo.txt", "--config", str(configuration),
                                        "--render-memory-mib", "96", "--profile"])
    assert override.render_memory_mib == 96 and override.profile is True
    plain = nv14_cli.parse_arguments(["encode-video", "demo.txt"])
    assert plain.render_memory_mib == 128 and plain.profile is False
    calls = []

    def encode(*args, **kwargs):
        calls.append(kwargs)
        return video.VideoEncodeResult(tmp_path / "result.mp4", 1, 1, 1, 40, 792, 600,
            "input_end", False, False, False,
            timings={"frames_rendered": 1} if kwargs["profile"] else None)

    monkeypatch.setattr(video, "encode_replay_video", encode)
    video.run_video_encode(override)
    assert calls[-1]["render_memory_mib"] == 96 and calls[-1]["profile"] is True
    assert 'performance: {"frames_rendered": 1}' in capsys.readouterr().out
    video.run_video_encode(plain)
    assert calls[-1]["render_memory_mib"] == 128 and calls[-1]["profile"] is False
    assert "performance:" not in capsys.readouterr().out


@pytest.mark.parametrize("api", ["data", "file"])
def test_session_methods_forward_default_and_override_memory_workers_and_profile(tmp_path, monkeypatch, api):
    calls = []
    sentinel = object()

    def encode(*args, **kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(video, "_encode_frames", encode)
    source = tmp_path / "demo.txt"
    source.write_text(_level() + "#1:0")
    with VideoEncodeSession(render_workers=2, render_memory_mib=48) as session:
        method = session.encode_replay_data_video if api == "data" else session.encode_replay_video
        positional = (_level(), "1:0", tmp_path / "out.mp4") if api == "data" else (source, tmp_path / "out.mp4")
        assert method(*positional, profile=True) is sentinel
        assert calls[-1]["session"] is session
        assert calls[-1]["render_workers"] == 2 and calls[-1]["render_memory_mib"] == 48
        assert calls[-1]["profile"] is True
        assert method(*positional, render_workers=1, render_memory_mib=32) is sentinel
        assert calls[-1]["render_workers"] == 1 and calls[-1]["render_memory_mib"] == 32
        assert calls[-1]["profile"] is False


@pytest.mark.parametrize("remaining,render_time,write_time,expected", [
    (31, .1, 0., 1),       # Too little remaining work to repay spawning.
    (500, .0001, 0., 1),   # Cheap frames stay serial.
    (500, .001, .003, 1),  # FFmpeg backpressure dominates rendering.
    (500, .001, 0., 2),    # Moderate drawing cost uses two workers.
    (200, .003, 0., 4),    # Expensive drawing can use all four workers.
])
def test_measured_auto_policy_accounts_for_work_remaining_and_encoder_backpressure(
        remaining, render_time, write_time, expected):
    assert choose_workers(remaining_ticks=remaining, scale=1, players=1, object_count=20,
        fps=60, render_seconds=render_time, write_seconds=write_time, max_workers=4) == expected


def test_session_automatic_selection_reuses_previous_measurements(tmp_path, export_harness, monkeypatch):
    decisions = []

    def choose(**kwargs):
        decisions.append(kwargs)
        return 1

    monkeypatch.setattr(video, "choose_workers", choose)
    with VideoEncodeSession(render_workers=0) as session:
        first = session.encode_replay_data_video("level", "3:0", tmp_path / "first.mp4", profile=True)
        assert decisions == []  # Short first export never reaches a warmup decision.
        second = session.encode_replay_data_video("level", "3:0", tmp_path / "second.mp4", profile=True)
        assert len(decisions) == 1
        assert decisions[0]["render_seconds"] == first.timings["render_seconds"] / 4
        assert decisions[0]["write_seconds"] == first.timings["write_seconds"] / 4
        assert second.timings["worker_decision"] == "session_history"


def test_real_automatic_handover_preserves_all_60fps_frames(tmp_path, real_ffmpeg, monkeypatch, capsys):
    frames = [InputFrame(right=True)] * 28
    serial = video.encode_replay_data_video(_level(), frames, tmp_path / "serial.mp4",
        final_neutral=False, fps=60, render_workers=1, profile=True)
    decisions = []

    def choose(**kwargs):
        decisions.append(kwargs)
        return 2

    monkeypatch.setattr(video, "choose_workers", choose)
    automatic = video.encode_replay_data_video(_level(), frames, tmp_path / "automatic.mp4",
        final_neutral=False, fps=60, render_workers=0, profile=True, progress=True)
    assert len(decisions) == 1
    assert decisions[0]["remaining_ticks"] == 15
    assert decisions[0]["render_seconds"] >= 0 and decisions[0]["write_seconds"] >= 0
    assert automatic.render_workers == 2
    assert automatic.timings["requested_workers"] == 0
    assert automatic.timings["worker_decision"] == "measured"
    assert automatic.timings["transport"] == "shared_memory"
    assert automatic.timings["frame_delivery"] == "timed"
    assert automatic.timings["frames_rendered"] == serial.timings["frames_rendered"] == 28
    assert automatic.simulated_ticks == serial.simulated_ticks == 28
    assert automatic.video_frames == serial.video_frames == 42
    progress = capsys.readouterr().out
    assert "42 frames sent" in progress and "2 render worker(s)" in progress
    expected = _decoded_frames(real_ffmpeg, serial.output_path)
    assert len(expected) == 42
    assert expected == _decoded_frames(real_ffmpeg, automatic.output_path)

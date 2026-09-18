"""Progress stays live during waits, quiet on demand, and stops on failure."""
import io
from threading import Event
from types import SimpleNamespace

import pytest

import nv14_video as video
from nv14_video_progress import VideoProgress
from nv14_engine import InputFrame
from test_video import export_harness


class ObservedOutput(io.StringIO):
    def __init__(self, target):
        super().__init__()
        self.target = target
        self.observed = Event()
        self.flushes = 0

    def write(self, value):
        count = super().write(value)
        if self.getvalue().count(self.target) >= 2:
            self.observed.set()
        return count

    def flush(self):
        self.flushes += 1


def test_heartbeat_runs_during_idle_work_and_stops_on_exit(monkeypatch):
    output = ObservedOutput("Loading replays")
    monkeypatch.setattr("sys.stdout", output)
    monkeypatch.setattr(VideoProgress, "INTERVAL_SECONDS", .01)
    with VideoProgress(True) as reporter:
        assert output.observed.wait(2), "no heartbeat while the caller was waiting"
        reporter.rendering(SimpleNamespace(frames_written=10, workers=1))
        reporter.rendering(SimpleNamespace(frames_written=5, workers=3), previous_frames=10)
    assert not reporter._thread.is_alive()
    text = output.getvalue()
    assert "15 frames sent; 3 render worker(s)" in text
    assert "[encode-video] Complete" in text
    assert "elapsed" in text and output.flushes >= 4


@pytest.mark.parametrize("error,phase", [(RuntimeError("render failed"), "Failed"),
                                        (KeyboardInterrupt(), "Cancelled")])
def test_failure_and_interrupt_stop_reporter_without_false_success(monkeypatch, error, phase):
    output = io.StringIO()
    monkeypatch.setattr("sys.stdout", output)
    with pytest.raises(type(error)):
        with VideoProgress(True) as reporter:
            raise error
    assert not reporter._thread.is_alive()
    assert f"[encode-video] {phase}" in output.getvalue()
    assert "Complete" not in output.getvalue()


def test_disabled_reporter_starts_no_thread_and_prints_nothing(capsys):
    with VideoProgress(False) as reporter:
        reporter.stage("Ignored")
        reporter.detail("Ignored")
        reporter.rendering(None)
    assert reporter._thread is None
    assert capsys.readouterr().out == ""


def test_closed_stdout_does_not_abort_export(monkeypatch):
    output = io.StringIO()
    output.close()
    monkeypatch.setattr("sys.stdout", output)
    with VideoProgress(True) as reporter:
        reporter.stage("Continues safely")
    assert reporter._thread is None


@pytest.mark.parametrize("enabled", [False, True])
def test_api_progress_preserves_frames_results_and_default_silence(tmp_path, export_harness, capsys, enabled):
    options = {"progress": True} if enabled else {}
    result = video.encode_replay_data_video("level", [InputFrame()] * 3,
        tmp_path / "out.mp4", final_neutral=False, render_workers=1, **options)
    assert result.video_frames == 3 and result.simulated_ticks == 3
    assert export_harness.renders == [1, 2, 3]
    text = capsys.readouterr().out
    if enabled:
        phases = ["Loading replay data", "Preparing native replay simulation", "Checking FFmpeg",
                  "Preparing renderer and graphics assets", "Starting FFmpeg and render workers",
                  "Rendering / encoding", "Finishing queued frames", "Finalising FFmpeg",
                  "Saving video", "Complete"]
        positions = [text.index(f"[encode-video] {phase}") for phase in phases]
        assert positions == sorted(positions)
        assert "3 frames sent" in text
    else:
        assert text == ""


def test_heartbeat_continues_while_ffmpeg_finalises(tmp_path, export_harness, monkeypatch):
    output = ObservedOutput("Finalising FFmpeg")
    monkeypatch.setattr("sys.stdout", output)
    monkeypatch.setattr(VideoProgress, "INTERVAL_SECONDS", .01)
    process_class = video.subprocess.Popen
    original_wait = process_class.wait

    def wait(self, timeout=None):
        if self.returncode is None:
            assert output.observed.wait(2), "no progress while waiting for FFmpeg"
        return original_wait(self, timeout)

    monkeypatch.setattr(process_class, "wait", wait)
    video.encode_replay_data_video("level", "2:0", tmp_path / "out.mp4",
                                  progress=True, render_workers=1)
    assert output.getvalue().count("Finalising FFmpeg") >= 2
    assert "[encode-video] Complete" in output.getvalue()


def test_encoding_failure_has_no_success_progress(tmp_path, export_harness, capsys):
    export_harness.exit_code = 1
    with pytest.raises(RuntimeError, match="FFmpeg failed"):
        video.encode_replay_data_video("level", "2:0", tmp_path / "out.mp4",
                                      progress=True, render_workers=1)
    text = capsys.readouterr().out
    assert "[encode-video] Failed" in text
    assert "[encode-video] Complete" not in text
    assert not (tmp_path / "out.mp4").exists()


@pytest.mark.parametrize("flags,enabled", [([], True), (["--no-progress"], False)])
def test_encode_video_command_forwards_progress(tmp_path, export_harness, capsys, flags, enabled):
    from nv14_cli import parse_arguments
    source = tmp_path / "primary.txt"
    source.write_text("$Map#Author##" + "0" * 713 + "|5^100,100#2:0#")
    args = parse_arguments(["encode-video", str(source), "--render-workers", "1", *flags])
    video.run_video_encode(args)
    text = capsys.readouterr().out
    assert ("[encode-video] Loading replay files" in text) is enabled
    assert "wrote " in text


def test_progress_toml_default_can_be_overridden(tmp_path):
    from nv14_cli import parse_arguments
    config = tmp_path / "video.toml"
    config.write_text("[encode-video]\nprogress = false\n")
    args = ["encode-video", "input.txt", "--config", str(config)]
    assert parse_arguments(args).progress is False
    assert parse_arguments([*args, "--progress"]).progress is True

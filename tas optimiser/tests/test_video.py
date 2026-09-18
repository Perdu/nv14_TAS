"""Optional video export contracts, replay fidelity and safe encoder failures."""
from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

import nv14_video as video
from nv14_engine import InputFrame
from nv14_replay import ComplexReplay, encode_complex_replay

ROOT = Path(__file__).resolve().parents[1]
REAL_POPEN = subprocess.Popen


@pytest.fixture
def export_harness(monkeypatch):
    """Keep expensive rendering external while observing replay/encoder effects."""
    import nv14_native
    import nv14_render
    import nv14_particles
    import nv14_object_visuals

    harness = SimpleNamespace(states=[], processes=[], renders=[], parsed=[],
                              terminal_at=None, dead=False, complete=False,
                              render_error=None, exit_code=0, broken_pipe=False,
                              real_pixels=False, invalid_frame=False, hang_on_broken_pipe=False, launches=[],
                              particle_updates=[], particle_advances=[], particle_seeds=[],
                              object_updates=[], object_advances=[], object_trackers=[], visual_queries=[],
                              terminal_rule=None, render_details=[], scene_states=[], credits=[])

    class Effects:
        def __init__(self, manifest, *, seed, _borrow_scenes=False):
            harness.particle_seeds.append(seed)

        def reset(self, scene):
            pass

        def snapshot(self):
            return ()

        def update(self, scene, frame, *, _snapshot=True):
            harness.particle_updates.append((scene["tick"], frame))
            return ()

        def advance(self, count, *, _snapshot=True):
            harness.particle_advances.append(count)
            return ()

    monkeypatch.setattr(nv14_particles, "ParticleSystem", Effects)

    class ObjectEffects:
        def __init__(self, manifest, *, _borrow_scenes=False):
            harness.object_trackers.append(self)

        def reset(self, scene, *, _snapshot=True):
            pass

        def snapshot(self):
            return ()

        def update(self, scene, frame, *, _snapshot=True):
            harness.object_updates.append((scene["tick"], frame))
            return ()

        def advance(self, count, *, _snapshot=True):
            harness.object_advances.append(count)
            return ()

    monkeypatch.setattr(nv14_object_visuals, "ObjectVisualSystem", ObjectEffects)

    class State:
        def __init__(self, track_visuals=True):
            self.inputs = []
            self.track_visuals = track_visuals
            harness.states.append(self)

        def step(self, frame):
            self.inputs.append(frame)
            if harness.terminal_rule is not None:
                return harness.terminal_rule(self.inputs)
            terminal = len(self.inputs) == harness.terminal_at
            return {"dead": terminal and harness.dead,
                    "level_complete": terminal and harness.complete}

        def scene_snapshot(self, *, include_object_visuals=False):
            harness.visual_queries.append(include_object_visuals)
            harness.scene_states.append(self)
            return {"tick": len(self.inputs)}

        def visual_snapshot(self):
            assert self.track_visuals
            return {"x": len(self.inputs), "y": 100, "frame": len(self.inputs) + 1,
                    "visible": True}

    class Level:
        def __init__(self, level_string="level", simulate_enemies=True):
            self.level_string = level_string
            self.simulate_enemies = simulate_enemies

        def initial_state(self, **kwargs):
            if kwargs:
                assert kwargs["track_visuals"] is True
                assert kwargs["visual_timeline_frames"] == 3
            return State(bool(kwargs))

    def parse(level_string, *, simulate_enemies):
        harness.parsed.append(level_string)
        return Level(level_string, simulate_enemies)

    native = SimpleNamespace(NativeState=State, NativeLevel=Level,
                             backend_info=lambda: {"object_visual_queries": True},
                             parse_level_string=parse)
    harness.native = native
    harness.Level = Level
    monkeypatch.setattr(nv14_native, "require_native", lambda: native)

    class Renderer:
        def __init__(self, level_string, *, assets_path, scale, render_quality="exact"):
            self.scale = scale
            self.manifest = {}

        def render(self, scene, *, particles=None, object_visuals=None,
                   secondary_players=(), show_primary_player=True, level_credit=None):
            if harness.render_error is not None:
                raise harness.render_error
            harness.renders.append(scene["tick"])
            harness.credits.append(level_credit)
            harness.render_details.append((scene["tick"], tuple(secondary_players), show_primary_player))
            size = (1, 1) if harness.invalid_frame else (792 * self.scale, 600 * self.scale)
            payload = bytes((scene["tick"] % 256,))
            if harness.real_pixels:
                payload *= size[0] * size[1] * 3
            return SimpleNamespace(size=size, mode="RGB", tobytes=lambda: payload)

    monkeypatch.setattr(nv14_render, "SceneRenderer", Renderer)
    # These timeline/cleanup tests deliberately use process-local fake scenes
    # and one-byte pixels. Keep their writer serial independently of CLI/API
    # worker defaults; the real worker tests exercise spawned rendering.
    import nv14_video_parallel
    original_writer = nv14_video_parallel.OrderedFrameRenderer

    def serial_writer(*args, **kwargs):
        kwargs["workers"] = 1
        return original_writer(*args, **kwargs)

    monkeypatch.setattr(nv14_video_parallel, "OrderedFrameRenderer", serial_writer)
    monkeypatch.setattr(video, "_find_ffmpeg", lambda _: "fake-ffmpeg")
    real_frame_stream = video._make_frame_stream

    def frame_stream(stream, width, height, fps):
        # Timeline unit cases deliberately use one-byte fake images. Actual
        # FFmpeg cases below use full RGB data and exercise timed delivery.
        return (real_frame_stream(stream, width, height, fps)
                if harness.real_pixels else stream)

    monkeypatch.setattr(video, "_make_frame_stream", frame_stream)

    class Pipe(io.BytesIO):
        def write(self, payload):
            if harness.broken_pipe:
                raise BrokenPipeError("encoder closed input")
            return super().write(payload)

        def close(self):
            self.saved = self.getvalue()
            super().close()

    class Process:
        def __init__(self, command, **kwargs):
            harness.processes.append(self)
            harness.launches.append(command)
            self.stdin = Pipe()
            self.destination = Path(command[-1])
            self.returncode = None
            self.terminated = False
            self.killed = False
            self.errors = kwargs["stderr"]

        def wait(self, timeout=None):
            if harness.hang_on_broken_pipe and self.returncode is None:
                raise subprocess.TimeoutExpired("fake-ffmpeg", timeout)
            if self.returncode is None:
                self.returncode = harness.exit_code
            if self.returncode == 0:
                self.destination.write_bytes(b"valid mocked MP4")
            elif not self.errors.closed:
                self.errors.write(b"test encoder failed")
            return self.returncode

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.killed = True
            self.returncode = -9

    monkeypatch.setattr(video.subprocess, "Popen", Process)
    return harness


def test_ordinary_cli_and_api_import_without_video_dependencies():
    program = r'''
import importlib.abc, sys
class BlockVideo(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'PIL' or fullname.startswith('PIL.') or fullname in ('nv14_render', 'nv14_vector', 'nv14_assets', 'nv14_particles', 'nv14_object_visuals'):
            raise AssertionError('ordinary CLI attempted optional video import: ' + fullname)
sys.meta_path.insert(0, BlockVideo())
import nv14_video
import nv14_cli
parser = nv14_cli.build_parser()
parser.parse_args(['auto', 'input.txt'])
parser.parse_args(['encode-video', 'input.txt'])
assert 'nv14_render' not in sys.modules
assert 'PIL' not in sys.modules
'''
    result = subprocess.run([sys.executable, "-c", program], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("representation", ["list", "tuple", "complex", "packed"])
def test_data_export_preserves_stored_triggers_and_appends_one_neutral(
        tmp_path, export_harness, representation):
    frames = [InputFrame(right=True, jump=True, jump_trigger=False),
              InputFrame(jump=False, jump_trigger=True), InputFrame(jump=True)]
    replay = {"list": frames, "tuple": tuple(frames), "complex": ComplexReplay(frames),
              "packed": encode_complex_replay(frames, canonicalise_jump_triggers=False)}[representation]
    before = tuple(frames)
    result = video.encode_replay_data_video("level", replay, tmp_path / "out.mp4")
    received = export_harness.states[0].inputs
    assert received[0].jump is True and received[0].jump_trigger is False
    assert received[1].jump is False and received[1].jump_trigger is True
    assert received[-1] == InputFrame()
    assert len(received) == 4
    assert tuple(frames) == before
    assert result.source_frames == 3
    assert result.simulated_ticks == result.video_frames == 4
    assert result.fps == 40 and result.final_neutral_written
    assert result.stop_reason == "input_end"
    assert not result.dead and not result.complete


def test_sixty_fps_preserves_gameplay_duration_and_only_duplicates_frames(tmp_path, export_harness):
    result = video.encode_replay_data_video("level", [InputFrame()] * 4,
        tmp_path / "out.mp4", final_neutral=False, fps=60)
    assert result.simulated_ticks == 4 and result.video_frames == 6
    assert result.duration_seconds == pytest.approx(4 / 40)
    assert export_harness.renders == [1, 2, 3, 4]
    assert export_harness.processes[0].stdin.saved == bytes([1, 1, 2, 3, 3, 4])


@pytest.mark.parametrize("dead,complete", [(True, False), (False, True), (True, True)])
def test_terminal_frame_is_kept_and_hold_does_not_advance_simulation(
        tmp_path, export_harness, dead, complete):
    export_harness.terminal_at = 2
    export_harness.dead, export_harness.complete = dead, complete
    result = video.encode_replay_data_video("level", [InputFrame()] * 5,
        tmp_path / "out.mp4", fps=60, terminal_hold_seconds=.1)
    assert result.simulated_ticks == 2 and result.video_frames == 9
    assert len(export_harness.states[0].inputs) == 2
    assert export_harness.renders == [1, 2, 2, 2, 2, 2]
    assert export_harness.particle_advances == [3, 3, 3, 3]
    assert export_harness.object_advances == [3, 3, 3, 3]
    assert len(export_harness.object_updates) == 2
    assert len(export_harness.particle_updates) == 2
    assert not result.final_neutral_written
    assert (result.dead, result.complete) == (dead, complete)
    assert result.stop_reason == ("complete" if complete else "dead")
    assert export_harness.processes[0].stdin.saved == bytes([1, 1] + [2] * 7)


@pytest.mark.parametrize("final_neutral", [True, False])
def test_empty_input_still_produces_a_frame_without_inventing_ticks(
        tmp_path, export_harness, final_neutral):
    result = video.encode_replay_data_video("level", [], tmp_path / "out.mp4",
                                            final_neutral=final_neutral)
    assert result.video_frames == 1
    assert result.simulated_ticks == int(final_neutral)
    assert result.final_neutral_written == final_neutral
    assert export_harness.renders == [int(final_neutral)]


def test_particles_can_be_disabled_without_constructing_tracker(tmp_path, export_harness):
    export_harness.terminal_at = 2
    export_harness.complete = True
    result = video.encode_replay_data_video("level", [InputFrame()] * 5,
        tmp_path / "out.mp4", particles=False, object_animations=False, terminal_hold_seconds=.1)
    assert result.video_frames == 6 and result.simulated_ticks == 2
    assert export_harness.renders == [1, 2]
    assert export_harness.particle_seeds == []
    assert export_harness.particle_updates == export_harness.particle_advances == []
    assert export_harness.object_trackers == []
    assert export_harness.visual_queries == [False, False]


@pytest.mark.parametrize("fps", [40, 41, 60, 120, 240])
def test_terminal_particle_cadence_is_independent_of_video_fps(tmp_path, export_harness, fps):
    export_harness.terminal_at = 1
    export_harness.dead = True
    result = video.encode_replay_data_video("level", [InputFrame()] * 5,
        tmp_path / "out.mp4", fps=fps, particle_seed=782, terminal_hold_seconds=.1)
    assert result.simulated_ticks == len(export_harness.states[0].inputs) == 1
    assert export_harness.particle_seeds == [782]
    assert len(export_harness.particle_updates) == 1
    # For non-integer fps ratios the final video-frame rounding can expose a
    # fifth nominal tick; derive it from the final output time, not wall time.
    last_tail_tick = (result.video_frames - 1) * 40 // fps
    assert sum(export_harness.particle_advances) == last_tail_tick * 3
    assert all(n == 3 for n in export_harness.particle_advances)
    assert export_harness.object_advances == export_harness.particle_advances


@pytest.mark.parametrize("particles,objects", [(True, False), (False, True)])
def test_cosmetic_trackers_are_independently_optional(tmp_path, export_harness, particles, objects):
    video.encode_replay_data_video("level", "2:0", tmp_path / "optional.mp4",
                                  particles=particles, object_animations=objects)
    assert len(export_harness.particle_updates) == (3 if particles else 0)
    assert len(export_harness.object_updates) == (3 if objects else 0)
    assert export_harness.visual_queries == [objects] * 4


def test_object_animation_requires_query_capability_before_encoding(tmp_path, export_harness):
    export_harness.native.backend_info = lambda: {"scene_abi": 1}
    output = tmp_path / "out.mp4"
    output.write_bytes(b"previous video")
    with pytest.raises(RuntimeError, match="v4.06 native extension"):
        video.encode_replay_data_video("level", "2:0", output)
    assert output.read_bytes() == b"previous video"
    assert export_harness.states == export_harness.processes == []
    video.encode_replay_data_video("level", "2:0", output, object_animations=False)
    assert export_harness.object_trackers == []


def test_object_options_work_with_file_api_cli_and_toml(tmp_path, export_harness):
    import nv14_cli
    config = tmp_path / "video.toml"
    config.write_text('[encode-video]\nobject_animations = false\n')
    args = nv14_cli.parse_arguments(["encode-video", "replay.txt", "--config", str(config)])
    assert args.object_animations is False
    args = nv14_cli.parse_arguments(["encode-video", "replay.txt", "--config", str(config),
                                       "--object-animations"])
    assert args.object_animations is True
    source = tmp_path / "replay.txt"
    source.write_text("0" * 713 + "|5^100,100#1:0")
    video.encode_replay_video(source, tmp_path / "file.mp4", object_animations=False)
    assert export_harness.object_trackers == []


def test_particle_options_work_with_file_api_cli_and_toml(tmp_path, export_harness):
    import nv14_cli
    config = tmp_path / "video.toml"
    config.write_text('[encode-video]\nparticles = false\nparticle_seed = 19\n')
    args = nv14_cli.parse_arguments(["encode-video", "replay.txt", "--config", str(config)])
    assert args.particles is False and args.particle_seed == 19
    args = nv14_cli.parse_arguments(["encode-video", "replay.txt", "--config", str(config), "--particles"])
    assert args.particles is True and args.particle_seed == 19
    source = tmp_path / "replay.txt"
    source.write_text("0" * 713 + "|5^100,100#1:0")
    video.encode_replay_video(source, tmp_path / "file.mp4", particle_seed=-91)
    assert export_harness.particle_seeds == [-91]


def test_reusable_native_level_resets_each_replay_without_native_reparse(tmp_path, export_harness):
    level = export_harness.Level()
    for run in range(2):
        result = video.encode_replay_data_video(level, "2:0", tmp_path / f"{run}.mp4")
        assert result.simulated_ticks == 3
    assert export_harness.parsed == []
    assert export_harness.renders == [1, 2, 3, 1, 2, 3]
    with pytest.raises(ValueError, match="simulate_enemies must match"):
        video.encode_replay_data_video(level, "2:0", tmp_path / "bad.mp4", simulate_enemies=False)


@pytest.mark.parametrize("options", [
    {"fps": 0}, {"fps": 39}, {"fps": True}, {"fps": 60.0}, {"scale": 0},
    {"scale": 5}, {"crf": 52}, {"preset": "unknown"},
    {"terminal_hold_seconds": float("nan")}, {"terminal_hold_seconds": -1},
    {"particles": "false"}, {"particles": 1}, {"particle_seed": True}, {"particle_seed": .5},
    {"object_animations": "false"}, {"object_animations": 1},
])
def test_invalid_options_never_touch_existing_output(tmp_path, export_harness, options):
    output = tmp_path / "out.mp4"
    output.write_bytes(b"previous video")
    with pytest.raises(ValueError):
        video.encode_replay_data_video("level", "1:0", output, **options)
    assert output.read_bytes() == b"previous video"
    assert export_harness.processes == []
    assert export_harness.states == []


@pytest.mark.parametrize("bad_replay", ["-1:", "8:0", "bad replay", b"1:0", None, ["bad"]])
def test_invalid_replay_never_starts_encoder(tmp_path, export_harness, bad_replay):
    with pytest.raises((TypeError, ValueError)):
        video.encode_replay_data_video("level", bad_replay, tmp_path / "out.mp4")
    assert export_harness.processes == []


@pytest.mark.parametrize("failure", ["render", "interrupt", "encoder_exit", "pipe", "launch"])
def test_failures_preserve_destination_close_child_and_remove_temporary_files(
        tmp_path, monkeypatch, export_harness, failure):
    output = tmp_path / "out.mp4"
    output.write_bytes(b"previous video")
    exception = RuntimeError
    if failure == "render":
        export_harness.render_error = RuntimeError("bad renderer")
    elif failure == "interrupt":
        export_harness.render_error = KeyboardInterrupt()
        exception = KeyboardInterrupt
    elif failure == "encoder_exit":
        export_harness.exit_code = 1
    elif failure == "pipe":
        export_harness.broken_pipe = True
        export_harness.exit_code = 1
    else:
        exception = OSError
        def fail_launch(*args, **kwargs):
            raise OSError("cannot start encoder")
        monkeypatch.setattr(video.subprocess, "Popen", fail_launch)
    with pytest.raises(exception):
        video.encode_replay_data_video("level", "1:0", output)
    assert output.read_bytes() == b"previous video"
    assert list(tmp_path.iterdir()) == [output]
    for process in export_harness.processes:
        assert process.poll() is not None
        assert process.stdin.closed


def test_ltm_export_preserves_recorded_tail_and_does_not_append_sentinel(
        tmp_path, monkeypatch, export_harness):
    import nv14_dump
    database = tmp_path / "levels.txt"
    database.write_text("$00-0 Video test#tests##" + "0" * 713 + "|5^100,134#\n")
    movie = tmp_path / "00-0.ltm"
    lines = ["|K|", "|K20|", "|Kff53|", "|K|", "|K|"]
    with tarfile.open(movie, "w:gz") as archive:
        for name, data in {
            "inputs": ("\n".join(lines) + "\n").encode(),
            "config.ini": b"[General]\nframe_count=5\nframerate_num=40\nframerate_den=1\nlength_sec=0\nlength_nsec=125000000\n",
        }.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    source = nv14_dump.load_player_dump_source(movie, levels_file=database)
    assert source.input_kind == "ltm" and len(source.frames) >= 3
    result = video.encode_replay_video(movie, tmp_path / "ltm.mp4", levels_file=database)
    assert tuple(export_harness.states[-1].inputs) == tuple(source.frames)
    assert result.simulated_ticks == result.source_frames == len(source.frames)
    assert not result.final_neutral_written
    trimmed = nv14_dump.load_player_dump_source(movie, levels_file=database, ltm_postroll=1)
    result = video.encode_replay_video(movie, tmp_path / "trimmed.mp4", levels_file=database,
                                       ltm_postroll=1)
    assert tuple(export_harness.states[-1].inputs) == tuple(trimmed.frames)
    assert result.simulated_ticks == len(trimmed.frames) == len(source.frames) - 1


def test_cli_mode_and_config_have_independent_video_defaults(tmp_path):
    import nv14_cli
    config = tmp_path / "video.toml"
    config.write_text('[encode-video]\nfps = 60\nscale = 2\nfinal_neutral = false\n')
    args = nv14_cli.parse_arguments(["encode-video", "demo.txt", "--config", str(config), "--fps", "80"])
    assert args.fps == 80 and args.scale == 2 and not args.final_neutral
    assert args.simulate_enemies is True
    assert not hasattr(args, "_mode_configs")
    args = nv14_cli.parse_arguments(["encode-video", "demo.txt"])
    assert args.fps == 40 and args.scale == 2 and args.final_neutral


def test_real_ffmpeg_produces_decodable_mp4_with_expected_dimensions_and_duration(
        tmp_path, monkeypatch, export_harness):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and ffprobe are optional video dependencies")
    monkeypatch.setattr(video.subprocess, "Popen", REAL_POPEN)
    encoders = subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
        capture_output=True, text=True, timeout=15)
    if "libx264" not in encoders.stdout:
        pytest.skip("FFmpeg has no libx264 encoder")
    monkeypatch.setattr(video, "_find_ffmpeg", lambda _: ffmpeg)
    export_harness.real_pixels = True
    result = video.encode_replay_data_video("level", "4:0", tmp_path / "actual.mp4",
        final_neutral=False, fps=60, preset="ultrafast")
    probe = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,nb_frames,duration,r_frame_rate",
        "-of", "json", str(result.output_path)], capture_output=True, text=True,
        timeout=15, check=True)
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["codec_name"] == "h264"
    assert (stream["width"], stream["height"]) == (1584, 1200)
    assert stream["r_frame_rate"] == "60/1"
    assert int(stream["nb_frames"]) == result.video_frames == 6
    assert float(stream["duration"]) == pytest.approx(.1)
    assert result.output_path.stat().st_size > 100
    assert list(tmp_path.iterdir()) == [result.output_path]


@pytest.mark.parametrize("frames", [[], [InputFrame()]])
def test_invalid_renderer_output_is_rejected_including_initial_still(
        tmp_path, export_harness, frames):
    export_harness.invalid_frame = True
    output = tmp_path / "out.mp4"
    output.write_bytes(b"previous video")
    with pytest.raises(RuntimeError, match="invalid RGB frame"):
        video.encode_replay_data_video("level", frames, output, final_neutral=False)
    assert output.read_bytes() == b"previous video"
    assert list(tmp_path.iterdir()) == [output]


def test_encoder_that_closes_stdin_without_exiting_is_terminated(tmp_path, export_harness):
    export_harness.broken_pipe = export_harness.hang_on_broken_pipe = True
    output = tmp_path / "out.mp4"
    output.write_bytes(b"previous video")
    with pytest.raises(RuntimeError, match="closed its input but did not exit"):
        video.encode_replay_data_video("level", "1:0", output)
    assert output.read_bytes() == b"previous video"
    assert list(tmp_path.iterdir()) == [output]
    assert export_harness.processes[0].terminated
    assert export_harness.processes[0].stdin.closed


def test_file_export_rejects_source_output_alias(tmp_path, export_harness):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original input")
    output = tmp_path / "alias.mp4"
    output.hardlink_to(source)
    with pytest.raises(ValueError, match="input and video output must be different"):
        video.encode_replay_video(source, output)
    assert source.read_bytes() == output.read_bytes() == b"original input"
    assert export_harness.processes == []


def test_real_native_renderer_and_encoder_export_a_moving_player(tmp_path):
    native = pytest.importorskip("_nv14_native")
    pytest.importorskip("PIL")
    if not hasattr(native.NativeState, "scene_snapshot"):
        pytest.skip("v4.04 native extension is required")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and ffprobe are optional video dependencies")
    if "libx264" not in subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=15).stdout:
        pytest.skip("FFmpeg has no libx264 encoder")
    tiles = ["0"] * 713
    for column in range(31):
        tiles[column * 23 + 5] = "1"
    level = "".join(tiles) + "|5^100,134!0^112,134!12^300,134!11^650,134,600,134"
    result = video.encode_replay_data_video(level, [InputFrame(right=True)] * 8,
        tmp_path / "native.mp4", final_neutral=False, preset="ultrafast")
    assert result.simulated_ticks == result.video_frames == 8
    assert result.fps == 40 and not result.dead and not result.complete
    probe = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,nb_frames,duration", "-of", "json",
        str(result.output_path)], capture_output=True, text=True, timeout=15, check=True)
    stream = json.loads(probe.stdout)["streams"][0]
    assert (stream["width"], stream["height"]) == (1584, 1200)
    assert int(stream["nb_frames"]) == 8
    assert float(stream["duration"]) == pytest.approx(.2)

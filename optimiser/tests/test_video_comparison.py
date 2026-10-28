"""Independent player clocks, primary world authority and comparison exports."""
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

from nv14_engine import InputFrame
from nv14_replay import ComplexReplay, encode_complex_replay
import nv14_video as video
from test_video import export_harness


def completes_on_jump(inputs):
    return {"dead": False, "level_complete": inputs[-1].jump}


def test_start_alignment_streams_all_players_and_only_primary_scene(tmp_path, export_harness):
    h = export_harness
    frames = [InputFrame(right=True, jump=True, jump_trigger=False),
              InputFrame(jump=False, jump_trigger=True)]
    second = [InputFrame(left=True)] * 5
    third = ComplexReplay([InputFrame(right=True)] * 3)
    before = deepcopy((frames, second, third))
    result = video.encode_replay_data_video("level", frames, tmp_path / "compare.mp4",
        secondary_replays=[second, third], fps=60, final_neutral=False)
    assert len(h.states) == 3
    assert h.states[0].inputs == frames and h.states[1].inputs == second
    assert h.states[2].inputs == third.frames
    assert (frames, second, third) == before
    assert h.renders == [1, 2, 2, 2, 2]
    assert [tuple(p["x"] for p in players) for _, players, _ in h.render_details] == [
        (1, 1), (2, 2), (3, 3), (4, 3), (5, 3)]
    assert h.render_details[0][1][0]["color"] == (53, 104, 168)
    assert h.render_details[0][1][1]["color"] != (53, 104, 168)
    assert all(show for _, _, show in h.render_details)
    assert set(h.scene_states) == {h.states[0]}
    assert [tick for tick, _ in h.object_updates] == [1, 2]
    assert [tick for tick, _ in h.particle_updates] == [1, 2]
    assert h.object_advances == h.particle_advances == [3, 3, 3]
    assert len(h.object_trackers) == len(h.particle_seeds) == 1
    assert result.simulated_ticks == 2 and result.timeline_ticks == 5
    assert result.video_frames == 8 and result.stop_reason == "input_end"
    assert [r.simulated_ticks for r in result.replays] == [2, 5, 3]
    assert [r.start_offset_ticks for r in result.replays] == [0, 0, 0]


@pytest.mark.parametrize("lengths", [(2, 5, 3), (5, 2, 3), (3, 5, 2), (3, 3, 3)])
@pytest.mark.parametrize("fps", [40, 60, 100])
def test_exit_alignment_uses_completion_and_freezes_delayed_primary(
        tmp_path, export_harness, lengths, fps):
    h = export_harness
    h.terminal_rule = completes_on_jump
    # Deliberately keep unequal, unused tails: input lengths are not finish times.
    replays = [[InputFrame()] * (n - 1) + [InputFrame(jump=True)] + [InputFrame()] * i
               for i, n in enumerate(lengths)]
    result = video.encode_replay_data_video("level", replays[0], tmp_path / "exit.mp4",
        secondary_replays=replays[1:], replay_alignment="exit", fps=fps,
        terminal_hold_seconds=.1)
    finish = max(lengths)
    offsets = [finish - n for n in lengths]
    assert result.complete and not result.dead and not result.final_neutral_written
    assert result.timeline_ticks == finish
    assert result.video_frames == (finish * fps + 39) // 40 + int(.1 * fps)
    assert [r.start_offset_ticks for r in result.replays] == offsets
    assert [r.end_tick for r in result.replays] == [finish] * 3
    assert [r.simulated_ticks for r in result.replays] == list(lengths)
    assert [s.track_visuals for s in h.states] == [False] * 3 + [True] * 3
    assert set(h.scene_states) == {h.states[3]}
    for tick, (primary_tick, players, show) in enumerate(h.render_details[:finish], 1):
        assert primary_tick == max(0, tick - offsets[0])
        assert show == (tick > offsets[0])
        assert [p["x"] for p in players] == [tick - d for d in offsets[1:] if tick > d]
    assert [tick for tick, _ in h.object_updates] == list(range(1, lengths[0] + 1))
    assert h.particle_updates == h.object_updates


def test_start_alignment_continues_after_primary_completion_then_holds(tmp_path, export_harness):
    h = export_harness
    h.terminal_rule = completes_on_jump
    result = video.encode_replay_data_video("level", [InputFrame(jump=True)], tmp_path / "out.mp4",
        secondary_replays=[[InputFrame()] * 3], final_neutral=False, terminal_hold_seconds=.1)
    assert result.complete and result.simulated_ticks == 1
    assert result.timeline_ticks == 3 and result.video_frames == 7
    assert len(h.states[0].inputs) == 1 and len(h.states[1].inputs) == 3
    assert result.replays[1].stop_reason == "input_end"
    assert len(h.object_updates) == len(h.particle_updates) == 1
    assert sum(h.object_advances) == sum(h.particle_advances) == 18


def test_exit_alignment_counts_final_neutral_and_accepts_completion_with_death(tmp_path, export_harness):
    h = export_harness
    def terminal(inputs):
        ended = len(inputs) > 1 and not inputs[-1].right
        return {"dead": ended, "level_complete": ended}
    h.terminal_rule = terminal
    primary = encode_complex_replay([InputFrame(right=True)] * 2)
    result = video.encode_replay_data_video("level", primary, tmp_path / "exit.mp4",
        secondary_replays=[[InputFrame(right=True)] * 4], replay_alignment="exit",
        terminal_hold_seconds=0)
    assert [r.simulated_ticks for r in result.replays] == [3, 5]
    assert all(r.final_neutral_written and r.complete and r.dead for r in result.replays)
    assert all(r.stop_reason == "complete" for r in result.replays)
    assert result.replays[0].start_offset_ticks == 2
    assert result.video_frames == 5


@pytest.mark.parametrize("which", [0, 1])
@pytest.mark.parametrize("dies", [False, True])
def test_exit_alignment_rejects_nonfinishers_before_output(tmp_path, export_harness, which, dies):
    h = export_harness
    h.terminal_rule = lambda inputs: {"dead": dies and inputs[-1].left,
                                    "level_complete": inputs[-1].jump}
    data = [[InputFrame(jump=True)], [InputFrame(jump=True)]]
    data[which] = [InputFrame(left=True)]
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"existing")
    with pytest.raises(ValueError, match="primary replay" if which == 0 else "secondary replay 1"):
        video.encode_replay_data_video("level", data[0], output,
            secondary_replays=data[1:], replay_alignment="exit", final_neutral=False)
    assert output.read_bytes() == b"existing"
    assert h.processes == []
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("empty_primary", [False, True])
def test_empty_replays_and_unbounded_secondary_count(tmp_path, export_harness, empty_primary):
    count = 12
    result = video.encode_replay_data_video("level", [] if empty_primary else "1:0",
        tmp_path / "many.mp4", secondary_replays=[[]] * count,
        final_neutral=False, particles=False, object_animations=False)
    assert result.video_frames == 1
    assert result.timeline_ticks == (0 if empty_primary else 1)
    assert len(result.replays) == count + 1
    assert len(export_harness.render_details[0][1]) == count
    assert not export_harness.object_trackers and not export_harness.particle_seeds


@pytest.mark.parametrize("options,error", [
    ({"secondary_replays": "2:0"}, "sequence"),
    ({"secondary_replays": [[InputFrame()], [False]]}, "InputFrame"),
    ({"replay_alignment": "end"}, "replay_alignment"),
    ({"secondary_replays": ["1:0"], "secondary_colors": []}, "one color"),
    ({"secondary_replays": ["1:0"], "secondary_colors": ["grey"]}, "RRGGBB"),
    ({"secondary_replays": ["1:0"], "secondary_colors": "#e0e0e0"}, "sequence"),
])
def test_bad_comparison_options_preserve_output(tmp_path, export_harness, options, error):
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"existing")
    with pytest.raises((ValueError, TypeError), match=error):
        video.encode_replay_data_video("level", "1:0", output, **options)
    assert output.read_bytes() == b"existing"
    assert export_harness.processes == []


def combined(path, level, frames):
    path.write_text(f"$Comparison#tests##{level}#{encode_complex_replay(frames)}#")
    return path


def ltm(path):
    lines = ["|K|", "|K20|", "|Kff53|", "|K|", "|K|"]
    with tarfile.open(path, "w:gz") as archive:
        for name, data in {
            "inputs": ("\n".join(lines) + "\n").encode(),
            "config.ini": b"[General]\nframe_count=5\nframerate_num=40\nframerate_den=1\nlength_sec=0\nlength_nsec=125000000\n",
        }.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return path


def test_mixed_file_formats_inherit_primary_level_and_keep_individual_neutrals(tmp_path, export_harness):
    from nv14_ltm import LtmMovie
    level = "0" * 713 + "|5^100,134"
    primary = combined(tmp_path / "primary.txt", level, [InputFrame(right=True)])
    second = tmp_path / "packed.txt"
    second.write_text("2:0")
    third = ltm(tmp_path / "unnamed.ltm")
    result = video.encode_replay_video(primary, tmp_path / "mix.mp4",
        secondary_replays=[second, third], ltm_postroll=1,
        secondary_colors=["#E0E0E0", "#80B0d0"])
    assert [r.final_neutral_written for r in result.replays] == [True, True, False]
    assert [r.simulated_ticks for r in result.replays[:2]] == [2, 3]
    assert export_harness.states[2].inputs == list(LtmMovie.load(third, postroll_frames=1).replay_frames)
    assert export_harness.parsed == [level]
    assert [r.color for r in result.replays] == [None, "#e0e0e0", "#80b0d0"]


def test_different_level_and_secondary_output_alias_are_rejected(tmp_path, export_harness):
    primary = combined(tmp_path / "primary.txt", "0" * 713 + "|5^100,134", [])
    second = combined(tmp_path / "second.txt", "0" * 713 + "|5^101,134", [])
    output = tmp_path / "out.mp4"
    with pytest.raises(ValueError, match="different level"):
        video.encode_replay_video(primary, output, secondary_replays=[second])
    assert not output.exists()
    output.hardlink_to(second)
    before = second.read_bytes()
    with pytest.raises(ValueError, match="different files"):
        video.encode_replay_video(primary, output, secondary_replays=[second])
    assert output.read_bytes() == before and export_harness.processes == []


def test_cli_toml_lists_and_api_forwarding(tmp_path, monkeypatch):
    import nv14_cli
    config = tmp_path / "comparison.toml"
    config.write_text('[encode-video]\nsecondary_replays = ["one.txt", "two.txt"]\n'
                      'secondary_colors = ["#e0e0e0", "#689ec9"]\nreplay_alignment = "exit"\n')
    args = nv14_cli.parse_arguments(["encode-video", "primary.txt", "--config", str(config),
        "--secondary-replay", "three.txt", "--secondary-color", "#abcdef", "--replay-alignment", "start"])
    assert args.secondary_replays == [Path("one.txt"), Path("two.txt"), Path("three.txt")]
    assert args.secondary_colors == ["#e0e0e0", "#689ec9", "#abcdef"]
    assert args.replay_alignment == "start"
    calls = []
    def encode(*positional, **kwargs):
        calls.append(kwargs)
        return video.VideoEncodeResult(Path("test.mp4"), 1, 1, 1, 40, 792, 600,
                                       "input_end", False, False, False)
    monkeypatch.setattr(video, "encode_replay_video", encode)
    video.run_video_encode(args)
    assert calls[0]["secondary_replays"] == args.secondary_replays
    assert calls[0]["secondary_colors"] == args.secondary_colors
    assert calls[0]["replay_alignment"] == "start"
    default = nv14_cli.parse_arguments(["encode-video", "primary.txt"])
    assert default.secondary_replays == [] and default.secondary_colors is None


def test_native_secondary_poses_match_private_simulation_without_changing_primary():
    native = pytest.importorskip("_nv14_native")
    tiles = ["0"] * 713
    for column in range(31):
        tiles[column * 23 + 5] = "1"
    level = native.parse_level_string("".join(tiles) + "|5^100,134!0^110,134!12^130,134"
        "!4^400,132,1!11^650,134,100,134", simulate_enemies=True)
    sources = [([InputFrame()] * 40, False), ([InputFrame(right=True)] * 40, False)]
    states = [level.initial_state(track_visuals=True, celebration_variant=1) for _ in sources]
    playback = video._ReplayComparison(level, states[0], sources, [0, 0], ["#e0e0e0"])
    control = level.initial_state(track_visuals=True, celebration_variant=1)
    other = states[1]
    other_stopped = False
    while not playback.done:
        tick = playback.timeline_ticks
        playback.step()
        control.step(sources[0][0][tick])
        if not other_stopped:
            event = other.step(sources[1][0][tick])
            other_stopped = event["dead"] or event["level_complete"]
        assert playback.tracks[0].state.state_key() == control.state_key()
        assert playback.tracks[0].state.scene_snapshot() == control.scene_snapshot()
        assert playback.tracks[1].visual == other.visual_snapshot()
    assert playback.tracks[1].dead  # Private mine interaction, no primary death.
    assert not playback.tracks[0].dead


@pytest.mark.parametrize("alignment", ["start", "exit"])
def test_real_three_player_mp4_has_expected_duration_and_completion(tmp_path, alignment):
    native = pytest.importorskip("_nv14_native")
    pytest.importorskip("PIL")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and FFprobe are optional")
    if "libx264" not in subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=15).stdout:
        pytest.skip("FFmpeg has no libx264")
    tiles = ["0"] * 713
    for column in range(31):
        tiles[column * 23 + 5] = "1"
    level = native.parse_level_string("".join(tiles) + "|5^100,134!0^140,134!11^200,134,100,134",
                                      simulate_enemies=True)
    sources = [[InputFrame()] * delay + [InputFrame(right=True)] * 60 for delay in (0, 9, 4)]
    durations = [video._completion_ticks(level, frames, True, i) for i, frames in enumerate(sources)]
    result = video.encode_replay_data_video(level, sources[0], tmp_path / f"{alignment}.mp4",
        secondary_replays=sources[1:], replay_alignment=alignment, fps=60,
        terminal_hold_seconds=.1, preset="ultrafast")
    assert [r.simulated_ticks for r in result.replays] == durations
    assert all(r.complete for r in result.replays)
    expected_offsets = ([max(durations) - n for n in durations] if alignment == "exit" else [0, 0, 0])
    assert [r.start_offset_ticks for r in result.replays] == expected_offsets
    assert result.timeline_ticks == max(durations)
    assert result.video_frames == (max(durations) * 60 + 39) // 40 + 6
    stream = json.loads(subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,nb_frames,duration", "-of", "json",
        str(result.output_path)], capture_output=True, text=True, timeout=15, check=True).stdout)["streams"][0]
    assert (stream["codec_name"], stream["width"], stream["height"]) == ("h264", 1584, 1200)
    assert int(stream["nb_frames"]) == result.video_frames
    assert float(stream["duration"]) == pytest.approx(result.duration_seconds, abs=1e-6)

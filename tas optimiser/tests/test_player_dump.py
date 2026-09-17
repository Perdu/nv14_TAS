"""Replay fidelity, native chunking, CSV contracts and command-line integration."""
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import nv14_cli as cli
import nv14_dump as dump
from nv14_engine import InputFrame
from nv14_replay import decode_complex_replay, encode_complex_replay, parse_combined_level_replay

native = pytest.importorskip("_nv14_native")
ROOT = Path(__file__).resolve().parents[1]
NEUTRAL = InputFrame()
RIGHT = InputFrame(right=True)


def flat_level(*, x=100, objects=""):
    tiles = ["0"] * 713
    for col in range(31):
        tiles[col * 23 + 5] = "1"
    return "".join(tiles) + f"|5^{x},134" + objects


def write_demo(path, frames, *, level=None):
    replay = encode_complex_replay(frames, canonicalise_jump_triggers=False)
    path.write_text(f"$00-0 Dump test#tests##{level or flat_level()}#{replay}#", encoding="utf-8")
    return path


def write_database(path, *, level=None):
    path.write_text(f"$00-0 Dump test#tests##{level or flat_level()}#\n", encoding="utf-8")
    return path


def write_movie(path, lines):
    members = {
        "inputs": ("\r\n".join(lines) + "\r\n").encode(),
        "config.ini": (
            f"[General]\nframe_count={len(lines)}\nframerate_num=40\nframerate_den=1\n"
            f"length_sec={len(lines) // 40}\nlength_nsec={len(lines) % 40 * 25000000}\n"
        ).encode(),
        # Branches and stale optimiser metadata must not influence this dump.
        "inputs1": b"|K20|\n|Kff51|\n",
        "nv14_optimizer.json": b"malformed stale metadata",
    }
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        return reader.fieldnames, rows


@pytest.mark.parametrize("path", sorted((ROOT / "tests").glob("example_*.txt")), ids=lambda p: p.stem)
def test_native_capture_matches_single_step_physics_and_visuals(path):
    combined = parse_combined_level_replay(path.read_text())
    frames = [*decode_complex_replay(combined.replay_string).frames, NEUTRAL]
    level = native.parse_level_string(combined.level_string, simulate_enemies=True)
    captured_state = level.initial_state(track_visuals=True)
    reference = level.initial_state(track_visuals=True)
    untracked = level.initial_state()
    count = 0
    for offset in range(0, len(frames), 17):
        rows = captured_state.capture_player_frames(frames[offset:offset + 17])
        for raw in rows:
            row = dict(zip(native.PLAYER_DUMP_COLUMNS, raw, strict=True))
            frame = frames[count]
            previous_held = reference.player_snapshot()["previous_jump_held"]
            event = reference.step(frame)
            assert event == untracked.step(frame)
            player = reference.player_snapshot()
            visual = reference.visual_snapshot()
            assert row["frame"] == event["frame_before"] == count
            assert row["elapsed_ticks"] == event["frame_after"] == count + 1
            assert (row["x"], row["y"]) == player["pos"]
            assert (row["old_x"], row["old_y"]) == player["oldpos"]
            assert row["vx"] == player["pos"][0] - player["oldpos"][0]
            assert row["vy"] == player["pos"][1] - player["oldpos"][1]
            assert row["player_state"] == player["state"]
            assert (row["floor_nx"], row["floor_ny"]) == player["floor_n"]
            assert (row["wall_nx"], row["wall_ny"]) == player["wall_n"]
            assert row["jump_trigger"] == (
                frame.jump and not previous_held if frame.jump_trigger is None else frame.jump_trigger
            )
            for name in ("jumped", "jump_callable", "dead"):
                assert row[name] == event[name]
            assert row["complete"] == event["level_complete"]
            for csv_name, visual_name in {
                "facing": "facing", "rotation_deg": "rotation_deg", "animation": "animation",
                "animation_frame": "frame", "animation_playing": "playing",
                "previous_animation_frame": "previous_frame", "run_animation_frame": "run_frame",
                "run_animation_remainder": "run_remainder", "render_mode": "render_mode",
                "sprite_x": "x", "sprite_y": "y", "sprite_visible": "visible",
                "visual_terminal": "terminal",
            }.items():
                assert row[csv_name] == visual[visual_name]
            count += 1
        assert captured_state.snapshot() == reference.snapshot()
        assert captured_state.state_key() == reference.state_key() == untracked.state_key()
        if reference.level_complete or reference.player_snapshot()["dead"]:
            assert captured_state.capture_player_frames([RIGHT] * 4) == []
            break
    assert count > 0


def test_native_capture_requires_tracking_and_preserves_trigger_history_across_chunks():
    level = native.parse_level_string(flat_level())
    with pytest.raises(ValueError, match="track_visuals"):
        level.initial_state().capture_player_frames([NEUTRAL])
    state = level.initial_state(track_visuals=True)
    held = InputFrame(jump=True)
    rows = state.capture_player_frames([NEUTRAL, held])
    rows += state.capture_player_frames([held, NEUTRAL, held])
    index = native.PLAYER_DUMP_COLUMNS.index("jump_trigger")
    assert [row[index] for row in rows] == [0, 1, 0, 0, 1]
    assert state.capture_player_frames([]) == []


def test_csv_post_tick_numbering_precision_inputs_and_default_final_neutral(tmp_path):
    frames = [InputFrame(right=True, jump=True, jump_trigger=False),
              InputFrame(left=True, jump=True, jump_trigger=True),
              InputFrame(jump=False, jump_trigger=True)]
    path = write_demo(tmp_path / "démo.txt", frames, level=flat_level(objects="!0^100,134"))
    result = dump.dump_player_csv(path, chunk_size=2)
    columns, rows = read_csv(result.output_path)
    assert result.output_path == tmp_path / "démo.player.csv"
    assert columns == [*native.PLAYER_DUMP_COLUMNS, "ltm_frame", "input_kind"]
    assert len(columns) == 43 and all(len(row) == 43 for row in rows)
    assert result.rows == 4 and result.source_frames == 3 and result.final_neutral_written
    assert result.stop_reason == "end_of_input"
    assert [row["frame"] for row in rows] == ["0", "1", "2", "3"]
    assert [row["elapsed_ticks"] for row in rows] == ["1", "2", "3", "4"]
    assert [row["jump_trigger"] for row in rows] == ["0", "1", "1", "0"]
    assert [row["input_kind"] for row in rows] == ["demo"] * 3 + ["final_neutral"]
    assert all(row["ltm_frame"] == "" for row in rows)
    assert rows[0]["gold_collected"] == "1" and rows[0]["gold_bonus_ticks"] == "80"
    level = native.parse_level_string(dump.load_player_dump_source(path).level_string)
    reference = level.initial_state(track_visuals=True)
    for row, frame in zip(rows, [*frames, NEUTRAL], strict=True):
        reference.step(frame)
        player = reference.player_snapshot()
        assert float(row["x"]) == player["pos"][0]
        assert float(row["y"]) == player["pos"][1]
        assert float(row["vx"]) == player["pos"][0] - player["oldpos"][0]
        assert float(row["vy"]) == player["pos"][1] - player["oldpos"][1]
    without = dump.dump_player_csv(path, tmp_path / "recorded.csv", final_neutral=False)
    assert without.rows == 3 and not without.final_neutral_written


def test_csv_chunk_boundaries_do_not_change_animation_or_output(tmp_path):
    frames = [RIGHT] * 45 + [InputFrame(left=True)] * 90 + [NEUTRAL] * 45
    path = write_demo(tmp_path / "demo.txt", frames)
    small = dump.dump_player_csv(path, tmp_path / "small.csv", chunk_size=1)
    large = dump.dump_player_csv(path, tmp_path / "large.csv", chunk_size=4096)
    assert small.output_path.read_bytes() == large.output_path.read_bytes()


@pytest.mark.parametrize("variant,animation,frame", [(0, "CELEBRATE_UNRESOLVED", ""), (9, "CELEBRATE_NEW9", "744")])
def test_csv_includes_completion_tick_and_omits_frozen_tail(tmp_path, variant, animation, frame):
    path = write_demo(tmp_path / "win.txt", [NEUTRAL] * 6,
                      level=flat_level(x=143, objects="!11^145,134,143,134"))
    result = dump.dump_player_csv(path, celebration_variant=variant)
    _, rows = read_csv(result.output_path)
    assert len(rows) == result.rows == 1
    assert rows[0]["frame"] == "0" and rows[0]["complete"] == "1"
    assert rows[0]["animation"] == animation and rows[0]["animation_frame"] == frame
    assert result.stop_reason == "complete" and not result.final_neutral_written


def test_csv_includes_death_tick_with_no_fabricated_ragdoll_pose(tmp_path):
    path = write_demo(tmp_path / "dead.txt", [NEUTRAL] * 5, level=flat_level(objects="!12^100,134"))
    result = dump.dump_player_csv(path)
    _, rows = read_csv(result.output_path)
    assert len(rows) == result.rows == 1 and result.stop_reason == "dead"
    assert rows[0]["dead"] == "1" and rows[0]["animation"] == "RAGDOLL"
    assert rows[0]["animation_frame"] == "" and rows[0]["sprite_visible"] == "0"


def test_empty_demo_can_write_header_only_or_one_neutral_tick(tmp_path):
    path = write_demo(tmp_path / "empty.txt", [])
    assert dump.dump_player_csv(path).rows == 1
    result = dump.dump_player_csv(path, final_neutral=False)
    assert result.rows == 0
    assert read_csv(result.output_path) == ([*native.PLAYER_DUMP_COLUMNS, "ltm_frame", "input_kind"], [])


def test_ltm_uses_active_inputs_retains_neutral_tail_and_reports_movie_frame(tmp_path):
    database = write_database(tmp_path / "levels.txt")
    path = write_movie(tmp_path / "00-0 movie.ltm", [
        "|Kff52|", "|K20:ffe1|", "|Kffe1:ff53|", "|Kffe1:ff53|", "|Kff51|", "|", "|K61|",
    ])
    original = path.read_bytes()
    result = dump.dump_player_csv(path, levels_file=database, chunk_size=2)
    _, rows = read_csv(result.output_path)
    assert result.rows == 5 and not result.final_neutral_written
    assert [row["ltm_frame"] for row in rows] == ["2", "3", "4", "5", "6"]
    assert [row["jump_trigger"] for row in rows] == ["1", "0", "0", "0", "0"]
    assert [row["input_right"] for row in rows] == ["1", "1", "0", "0", "0"]
    assert all(row["input_kind"] == "ltm" for row in rows)
    assert path.read_bytes() == original
    trimmed = dump.dump_player_csv(path, levels_file=database, ltm_postroll=2)
    assert trimmed.rows == 3


@pytest.mark.parametrize("explicit", [False, True])
def test_packed_only_demo_resolves_database_and_preserves_trigger_bits(tmp_path, explicit):
    database = write_database(tmp_path / "levels.txt")
    path = tmp_path / ("raw.txt" if explicit else "00-0 demo.txt")
    path.write_text("\ufeff2:140\n", encoding="utf-8")  # Held+trigger, then trigger without held.
    result = dump.dump_player_csv(path, levels_file=database, level_id="00-0" if explicit else None)
    _, rows = read_csv(result.output_path)
    assert [row["jump_trigger"] for row in rows] == ["1", "1", "0"]
    assert [row["jump_held"] for row in rows] == ["1", "0", "0"]


@pytest.mark.parametrize("alias", ["same", "hardlink", "symlink"])
def test_input_alias_is_rejected_without_modifying_input(tmp_path, alias):
    path = write_demo(tmp_path / "demo.csv", [RIGHT])
    output = path if alias == "same" else tmp_path / "alias.csv"
    if alias == "hardlink":
        os.link(path, output)
    elif alias == "symlink":
        try:
            output.symlink_to(path)
        except OSError:
            pytest.skip("symlinks unavailable")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="different files"):
        dump.dump_player_csv(path, output)
    assert path.read_bytes() == original


def test_database_alias_is_rejected(tmp_path):
    database = write_database(tmp_path / "levels.csv")
    path = tmp_path / "00-0.txt"
    path.write_text("0:")
    original = database.read_bytes()
    with pytest.raises(ValueError, match="levels file"):
        dump.dump_player_csv(path, database, levels_file=database)
    assert database.read_bytes() == original


@pytest.mark.parametrize("failure", ["malformed", "unsupported", "missing_native", "old_native", "interrupt"])
def test_failure_or_interrupt_preserves_existing_csv_and_cleans_temporary(tmp_path, monkeypatch, failure):
    path = write_demo(tmp_path / "demo.txt", [RIGHT] * 5)
    destination = tmp_path / "out.csv"
    destination.write_bytes(b"previous valid dump\n")
    if failure == "malformed":
        path.write_text("bad replay")
    elif failure == "unsupported":
        write_demo(path, [RIGHT], level=flat_level(objects="!6^120,120,0,1,99,0"))
    elif failure == "missing_native":
        def unavailable():
            raise RuntimeError("native core is unavailable")
        monkeypatch.setattr(dump, "require_native", unavailable)
    elif failure == "old_native":
        monkeypatch.setattr(dump, "require_native", lambda: SimpleNamespace(backend_info=lambda: {}))
    else:
        level = native.parse_level_string(flat_level())
        state = level.initial_state(track_visuals=True)
        calls = 0
        def capture(frames):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            return state.capture_player_frames(frames)
        fake_state = SimpleNamespace(capture_player_frames=capture)
        fake_level = SimpleNamespace(initial_state=lambda **kw: fake_state)
        monkeypatch.setattr(dump, "require_native", lambda: SimpleNamespace(
            backend_info=native.backend_info, PLAYER_DUMP_COLUMNS=native.PLAYER_DUMP_COLUMNS,
            parse_level_string=lambda *a, **kw: fake_level,
        ))
    with pytest.raises((ValueError, RuntimeError, KeyboardInterrupt)):
        dump.dump_player_csv(path, destination, chunk_size=1)
    assert destination.read_bytes() == b"previous valid dump\n"
    assert not list(tmp_path.glob(".out.csv.*.tmp"))


def test_dump_cli_uses_native_and_does_not_build_optimisation_config(tmp_path, monkeypatch, capsys):
    path = write_demo(tmp_path / "demo.txt", [RIGHT] * 5)
    def forbidden(*args, **kwargs):
        pytest.fail("dump entered an optimisation/Python-physics path")
    monkeypatch.setattr(cli, "build_mode_configs", forbidden)
    import nv14_engine
    monkeypatch.setattr(nv14_engine, "parse_level_string", forbidden)
    monkeypatch.setattr(sys, "argv", ["optimize_replay.py", "dump-player", str(path), "--no-final-neutral"])
    cli.main()
    assert "5 frame rows" in capsys.readouterr().out
    assert read_csv(path.with_name("demo.player.csv"))[1][-1]["frame"] == "4"


def test_executable_dump_command_help_and_error_exit(tmp_path):
    path = write_demo(tmp_path / "demo.txt", [NEUTRAL])
    result = subprocess.run(
        [sys.executable, "optimize_replay.py", "dump-player", str(path)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "2 frame rows" in result.stdout
    path.write_text("bad replay")
    result = subprocess.run(
        [sys.executable, "optimize_replay.py", "dump-player", str(path)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode != 0 and "CSV output was not replaced" in result.stderr
    parser = cli.build_parser()
    help_text = parser._command_parsers["dump-player"].format_help()
    assert "--no-final-neutral" in help_text and "--visual-timeline-frames" in help_text
    assert "--iterations" not in help_text and "--beam" not in help_text


@pytest.mark.parametrize("section", ["dump-player", "dump_player"])
def test_dump_toml_booleans_and_command_line_precedence(tmp_path, section):
    config = tmp_path / "config.toml"
    config.write_text(f"[{section}]\nfinal_neutral = false\nsimulate_enemies = false\nvisual_timeline_frames = 0\ncelebration_variant = 3\n")
    parser = cli.build_parser()
    args = parser.parse_args(["dump-player", "input.txt", "--config", str(config), "--simulate-enemies"])
    assert not args.final_neutral and args.simulate_enemies
    assert args.visual_timeline_frames == 0 and args.celebration_variant == 3
    plain = parser.parse_args(["dump-player", "input.txt"])
    assert plain.final_neutral and plain.simulate_enemies and plain.visual_timeline_frames == 3
    config.write_text(f"[{section}]\nno_final_neutral = true\nno_simulate_enemies = false\n")
    args = cli.parse_arguments(["dump-player", "input.txt", "--config", str(config)])
    assert not args.final_neutral and args.simulate_enemies
    config.write_text(f"[{section}]\nfinal_neutral = \"false\"\n")
    with pytest.raises(SystemExit, match="boolean"):
        cli.parse_arguments(["dump-player", "input.txt", "--config", str(config)])


@pytest.mark.parametrize("options", [["--iterations", "1"], ["--visual-timeline-frames", "-1"], ["--celebration-variant", "10"]])
def test_invalid_dump_cli_options_are_rejected(options):
    with pytest.raises(SystemExit):
        cli.parse_arguments(["dump-player", "input.txt", *options])

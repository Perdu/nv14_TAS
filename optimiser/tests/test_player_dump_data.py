"""Direct-data export contracts and reuse of the file/native capture pipeline."""
from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import pytest

import nv14_dump as dump
from nv14_engine import InputFrame
from nv14_replay import ComplexReplay, encode_complex_replay, parse_combined_level_replay

native = pytest.importorskip("_nv14_native")
ROOT = Path(__file__).resolve().parents[1]
NEUTRAL = InputFrame()


def flat_level(*, x=100, objects=""):
    tiles = ["0"] * 713
    for col in range(31):
        tiles[col * 23 + 5] = "1"
    return "".join(tiles) + f"|5^{x},134" + objects


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == [*native.PLAYER_DUMP_COLUMNS, "ltm_frame", "input_kind"]
    return rows


@pytest.mark.parametrize("path", sorted((ROOT / "tests").glob("example_*.txt")), ids=lambda p: p.stem)
def test_data_api_matches_file_export_on_bundled_replays(tmp_path, path):
    combined = parse_combined_level_replay(path.read_text())
    file_result = dump.dump_player_csv(path, tmp_path / "file.csv")
    data_result = dump.dump_player_data_csv(
        level_data=combined.level_string, replay_data=combined.replay_string,
        output_path=str(tmp_path / "data.csv"), simulate_enemies=True, chunk_size=17,
    )
    assert data_result.output_path.read_bytes() == file_result.output_path.read_bytes()
    assert replace(data_result, output_path=file_result.output_path) == file_result


def test_data_api_needs_no_input_files_or_python_simulation(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("direct-data export attempted input lookup or Python simulation")
    monkeypatch.setattr(dump, "load_player_dump_source", forbidden)
    monkeypatch.setattr(dump, "discover_levels_file", forbidden)
    import nv14_engine
    monkeypatch.setattr(nv14_engine, "parse_level_string", forbidden)

    from nv14_dump import dump_player_data_csv
    destination = tmp_path / "batch" / "00-0_highscore.csv"
    result = dump_player_data_csv(
        level_data=flat_level(), replay_data="5:0", output_path=str(destination),
        simulate_enemies=True,
    )
    rows = read_rows(result.output_path)
    assert result.rows == 6 and result.source_frames == 5
    assert result.stop_reason == "end_of_input" and result.final_neutral_written
    assert [row["frame"] for row in rows] == ["0", "1", "2", "3", "4", "5"]
    assert rows[-1]["input_kind"] == "final_neutral"
    assert all(row["ltm_frame"] == "" for row in rows)
    assert list(tmp_path.rglob("*.*")) == [destination]


@pytest.mark.parametrize("representation", ["list", "tuple", "complex"])
def test_decoded_input_forms_preserve_triggers_and_caller_data(tmp_path, representation):
    frames = [
        InputFrame(right=True, jump=True, jump_trigger=False),
        InputFrame(jump=True), NEUTRAL, InputFrame(jump=True),
        InputFrame(jump=False, jump_trigger=True),
    ]
    before = tuple(frames)
    replay = frames if representation == "list" else (
        tuple(frames) if representation == "tuple" else ComplexReplay(frames)
    )
    result = dump.dump_player_data_csv(
        flat_level(), replay, tmp_path / "decoded.csv", final_neutral=False, chunk_size=2,
    )
    rows = read_rows(result.output_path)
    assert [row["jump_trigger"] for row in rows] == ["0", "0", "0", "1", "1"]
    assert [row["jump_held"] for row in rows] == ["1", "1", "0", "1", "0"]
    assert tuple(frames) == before
    assert all(row["input_kind"] == "demo" for row in rows)
    assert result.source_frames == result.rows == 5


def test_reusing_native_level_avoids_reparsing_and_resets_each_replay(tmp_path, monkeypatch):
    level_string = flat_level(objects="!0^100,134")
    level = native.parse_level_string(level_string, simulate_enemies=True)
    independent_state = level.initial_state(track_visuals=True)
    independent_state.step(InputFrame(right=True))
    before = independent_state.snapshot()
    expected = dump.dump_player_data_csv(level_string, "25:0|0|0|0", tmp_path / "expected.csv")

    def forbidden(*args, **kwargs):
        pytest.fail("an existing native level was reparsed")
    monkeypatch.setattr(native, "parse_level_string", forbidden)
    for run in range(3):
        result = dump.dump_player_data_csv(level, "25:0|0|0|0", tmp_path / f"run{run}.csv")
        assert result.output_path.read_bytes() == expected.output_path.read_bytes()
        assert read_rows(result.output_path)[0]["gold_collected"] == "1"
    assert level.level_string == level_string
    assert independent_state.snapshot() == before


@pytest.mark.parametrize("enabled", [True, False])
def test_native_level_requires_matching_enemy_setting(tmp_path, enabled):
    level = native.parse_level_string(flat_level(), simulate_enemies=enabled)
    output = tmp_path / "out.csv"
    output.write_text("previous dump")
    with pytest.raises(ValueError, match="simulate_enemies must match"):
        dump.dump_player_data_csv(level, "1:0", output, simulate_enemies=not enabled)
    assert output.read_text() == "previous dump"
    assert dump.dump_player_data_csv(level, "1:0", output, simulate_enemies=enabled).rows == 2


@pytest.mark.parametrize("final_neutral", [True, False])
@pytest.mark.parametrize("replay", ["0:", []])
def test_empty_data_replay_and_neutral_option(tmp_path, replay, final_neutral):
    result = dump.dump_player_data_csv(
        flat_level(), replay, tmp_path / "empty.csv", final_neutral=final_neutral,
    )
    assert result.rows == int(final_neutral)
    assert result.source_frames == 0 and result.final_neutral_written == final_neutral
    assert len(read_rows(result.output_path)) == int(final_neutral)


def test_data_visual_clock_option_is_passed_to_native_state(tmp_path):
    result = dump.dump_player_data_csv(
        flat_level(), "5:0", tmp_path / "clock.csv",
        final_neutral=False, visual_timeline_frames=0,
    )
    assert [row["animation_frame"] for row in read_rows(result.output_path)] == ["1"] * 5


@pytest.mark.parametrize("terminal", ["complete", "dead"])
def test_data_terminal_rows_and_celebration_option(tmp_path, terminal):
    level = flat_level(x=143, objects="!11^145,134,143,134") if terminal == "complete" else (
        flat_level(objects="!12^100,134")
    )
    result = dump.dump_player_data_csv(
        level, "5:0", tmp_path / "terminal.csv", celebration_variant=9,
    )
    rows = read_rows(result.output_path)
    assert result.rows == 1 and result.stop_reason == terminal
    assert not result.final_neutral_written
    assert rows[0][terminal] == "1"
    assert rows[0]["animation"] == ("CELEBRATE_NEW9" if terminal == "complete" else "RAGDOLL")
    assert rows[0]["animation_frame"] == ("744" if terminal == "complete" else "")


@pytest.mark.parametrize("bad_replay", [
    "-1:", "8:0", "bad replay", b"1:0", None, [NEUTRAL, "abc"], ComplexReplay("1:0"),
])
def test_bad_replay_data_preserves_destination(tmp_path, bad_replay):
    output = tmp_path / "out.csv"
    output.write_text("previous dump")
    with pytest.raises((ValueError, TypeError)):
        dump.dump_player_data_csv(flat_level(), bad_replay, output)
    assert output.read_text() == "previous dump"
    assert not list(tmp_path.glob(".out.csv.*.tmp"))


@pytest.mark.parametrize("bad_level", [None, Path("level.txt"), "invalid level", flat_level(objects="!6^120,120,0,1,99,0")])
def test_bad_or_unsupported_level_data_preserves_destination(tmp_path, bad_level):
    output = tmp_path / "out.csv"
    output.write_text("previous dump")
    with pytest.raises((ValueError, TypeError, NotImplementedError)):
        dump.dump_player_data_csv(bad_level, "1:0", output)
    assert output.read_text() == "previous dump"
    assert not list(tmp_path.glob(".out.csv.*.tmp"))


def test_data_output_arguments_and_bom_text(tmp_path):
    level = flat_level()
    replay = "\ufeff2:140\n"  # trigger without held on the second frame.
    with pytest.raises(ValueError, match=".csv extension"):
        dump.dump_player_data_csv(level, replay, tmp_path / "out.txt")
    with pytest.raises(ValueError, match="chunk_size"):
        dump.dump_player_data_csv(level, replay, tmp_path / "out.csv", chunk_size=0)
    assert not list(tmp_path.iterdir())
    result = dump.dump_player_data_csv(level, replay, tmp_path / "out.csv")
    assert [row["jump_trigger"] for row in read_rows(result.output_path)] == ["1", "1", "0"]

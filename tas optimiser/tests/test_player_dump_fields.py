"""Ordered CSV projection, validation and terminal/source metadata contracts."""
from __future__ import annotations

import csv
import io
import tarfile
from dataclasses import replace

import pytest

import nv14_dump as dump

native = pytest.importorskip("_nv14_native")
ALL_FIELDS = (*native.PLAYER_DUMP_COLUMNS, "ltm_frame", "input_kind")


def flat_level(*, x=100, objects=""):
    tiles = ["0"] * 713
    for col in range(31):
        tiles[col * 23 + 5] = "1"
    return "".join(tiles) + f"|5^{x},134" + objects


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.reader(stream))


@pytest.mark.parametrize("fields", [
    ["frame", "x", "y", "vx", "vy", "facing", "animation_frame"],
    ["x"], ["animation"], ["run_animation_frame"], ["input_kind"],
    tuple(reversed(ALL_FIELDS)),
], ids=["requested_example", "one_number", "one_string", "one_blank", "source_kind", "reverse_all"])
def test_selected_columns_are_exact_projection_in_requested_order(tmp_path, fields):
    before = tuple(fields)
    full = dump.dump_player_data_csv(flat_level(), "5:0", tmp_path / "full.csv")
    selected = dump.dump_player_data_csv(
        flat_level(), "5:0", tmp_path / "selected.csv", fields=fields, chunk_size=2,
    )
    full_rows = read_csv(full.output_path)
    indices = [full_rows[0].index(field) for field in fields]
    assert read_csv(selected.output_path) == [[row[index] for index in indices] for row in full_rows]
    assert replace(selected, output_path=full.output_path) == full
    assert tuple(fields) == before


def test_omitted_none_and_explicit_full_fields_are_identical(tmp_path):
    paths = [tmp_path / f"full{index}.csv" for index in range(3)]
    dump.dump_player_data_csv(flat_level(), "3:546", paths[0])
    dump.dump_player_data_csv(flat_level(), "3:546", paths[1], fields=None)
    dump.dump_player_data_csv(flat_level(), "3:546", paths[2], fields=ALL_FIELDS)
    assert paths[0].read_bytes() == paths[1].read_bytes() == paths[2].read_bytes()
    assert read_csv(paths[0])[0] == list(ALL_FIELDS)


@pytest.mark.parametrize("terminal", ["complete", "dead"])
def test_omitting_frame_and_terminal_columns_preserves_stop_and_summary(tmp_path, terminal):
    level = flat_level(x=143, objects="!11^145,134,143,134") if terminal == "complete" else (
        flat_level(objects="!12^100,134")
    )
    result = dump.dump_player_data_csv(level, "5:0", tmp_path / "terminal.csv", fields=["x"])
    assert result.rows == 1 and result.stop_reason == terminal
    assert not result.final_neutral_written and result.source_frames == 5
    assert len(read_csv(result.output_path)) == 2


def test_empty_replay_writes_only_selected_header_without_neutral(tmp_path):
    result = dump.dump_player_data_csv(
        flat_level(), "0:", tmp_path / "empty.csv", fields=["animation", "x"], final_neutral=False,
    )
    assert result.rows == 0
    assert read_csv(result.output_path) == [["animation", "x"]]


def test_file_api_forwards_fields_and_matches_data_api(tmp_path):
    source = tmp_path / "demo.txt"
    source.write_text(f"$00-0 Fields#tests##{flat_level()}#2:140#")
    fields = ["input_kind", "jump_trigger", "frame", "vx"]
    file_result = dump.dump_player_csv(source, tmp_path / "file.csv", fields=fields)
    data_result = dump.dump_player_data_csv(flat_level(), "2:140", tmp_path / "data.csv", fields=fields)
    assert file_result.output_path.read_bytes() == data_result.output_path.read_bytes()
    assert read_csv(file_result.output_path)[-1][0] == "final_neutral"


def test_ltm_metadata_can_be_selected_and_reordered(tmp_path):
    source = tmp_path / "00-0.ltm"
    lines = ["|Kff52|", "|K20|", "|Kff53|", "|Kff53|", "|", "|", "|"]
    members = {
        "inputs": ("\n".join(lines) + "\n").encode(),
        "config.ini": (
            "[General]\nframe_count=7\nframerate_num=40\nframerate_den=1\n"
            "length_sec=0\nlength_nsec=175000000\n"
        ).encode(),
    }
    with tarfile.open(source, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    database = tmp_path / "levels.txt"
    database.write_text(f"$00-0 Fields#tests##{flat_level()}#\n")
    fields = ["ltm_frame", "input_kind", "frame"]
    result = dump.dump_player_csv(source, levels_file=database, fields=fields, chunk_size=2)
    assert read_csv(result.output_path) == [fields] + [
        [str(frame + 2), "ltm", str(frame)] for frame in range(5)
    ]
    assert result.rows == 5 and not result.final_neutral_written


@pytest.mark.parametrize("entry", ["data", "file"])
@pytest.mark.parametrize("fields,error,match", [
    ([], ValueError, "at least one"),
    (["missing"], ValueError, "unknown CSV field"),
    (["x", "x"], ValueError, "duplicate CSV field"),
    (["X"], ValueError, "unknown CSV field"),
    (["x", 1], TypeError, "only string"),
    ("frame,x", TypeError, "sequence"),
    ({"x"}, TypeError, "sequence"),
    (b"x", TypeError, "sequence"),
])
def test_invalid_fields_fail_before_simulation_and_preserve_csv(tmp_path, monkeypatch, entry, fields, error, match):
    source = tmp_path / "demo.txt"
    source.write_text(f"$00-0 Fields#tests##{flat_level()}#1:0#")
    output = tmp_path / "out.csv"
    output.write_text("previous valid CSV")
    def forbidden(*args, **kwargs):
        pytest.fail("invalid field selection reached native level parsing")
    monkeypatch.setattr(native, "parse_level_string", forbidden)
    with pytest.raises(error, match=match):
        if entry == "data":
            dump.dump_player_data_csv(flat_level(), "1:0", output, fields=fields)
        else:
            dump.dump_player_csv(source, output, fields=fields)
    assert output.read_text() == "previous valid CSV"
    assert not list(tmp_path.glob(".out.csv.*.tmp"))

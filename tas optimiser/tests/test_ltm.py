from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
from pathlib import Path

import pytest

import nv14_cli as cli
import optimize_replay as opt
from nv14_auto import verify_trimmed_replay
from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    parse_level_string,
)
from nv14_ltm import (
    LEVEL_DATABASE_NAME,
    METADATA_FORMAT,
    METADATA_MEMBER,
    METADATA_VERSION,
    LtmError,
    LtmMovie,
    discover_levels_file,
    find_level_record,
    infer_level_id_from_ltm_filename,
)
from nv14_replay import decode_complex_replay, editable_frames


def _add_bytes(
    archive: tarfile.TarFile,
    name: str,
    raw: bytes,
    *,
    mode: int = 0o640,
) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(raw)
    info.mode = mode
    info.uid = 123
    info.gid = 456
    info.uname = "tester"
    info.gname = "tests"
    info.mtime = 1_700_000_000
    archive.addfile(info, io.BytesIO(raw))


def _write_ltm(
    path: Path,
    inputs: bytes,
    *,
    config: bytes | None = None,
    extra_members: tuple[tuple[str, bytes], ...] = (),
) -> Path:
    with tarfile.open(path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        _add_bytes(archive, "inputs", inputs)
        if config is not None:
            _add_bytes(archive, "config.ini", config)
        for name, raw in extra_members:
            _add_bytes(archive, name, raw)
    return path


def _write_members(path: Path, members: tuple[tuple[str, bytes], ...]) -> Path:
    with tarfile.open(path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for name, raw in members:
            _add_bytes(archive, name, raw)
    return path


def _regular_members(path: Path) -> list[tuple[tarfile.TarInfo, bytes]]:
    result: list[tuple[tarfile.TarInfo, bytes]] = []
    with tarfile.open(path, mode="r:*") as archive:
        for member in archive.getmembers():
            if member.isfile():
                extracted = archive.extractfile(member)
                assert extracted is not None
                result.append((member, extracted.read()))
    return result


def _member_bytes(path: Path, name: str) -> bytes:
    matches = [
        raw
        for member, raw in _regular_members(path)
        if member.name.lstrip("./") == name
    ]
    assert len(matches) == 1
    return matches[0]


def _basic_inputs(newline: str = "\r\n") -> bytes:
    lines = (
        "|Kff52|Mpre:1|",
        "|Mspace:2|K20:ff52|",
        "|Kffe1:ff51:61|Mbody:0|",
        "|Mbody:1|K61:ffe1:ff53|",
        "|Kff53|C1:unchanged|",
        "|K61|Mpost:0|",
        "|Mpost:1|",
    )
    return (newline.join(lines) + newline).encode("utf-8")


def _basic_config(frame_count: int = 7) -> bytes:
    length_sec, remainder = divmod(frame_count, 10)
    return (
        "[General]\n"
        f"frame_count={frame_count}\n"
        f"savestate_frame_count={frame_count}\n"
        "framerate_num=10\n"
        "framerate_den=1\n"
        f"length_sec={length_sec}\n"
        f"length_nsec={remainder * 100_000_000}\n"
        "untouched=value\n"
    ).encode("utf-8")


def _frame_bits(frame: InputFrame) -> tuple[bool, bool, bool, bool | None]:
    return frame.left, frame.right, frame.jump, frame.jump_trigger


def _held_bits(frame: InputFrame) -> tuple[bool, bool, bool]:
    return frame.left, frame.right, frame.jump


def _running_exit_level_string() -> str:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    return f"{''.join(chars)}|5^60,134!11^140,134,60,134"


def _falling_exit_level_string() -> str:
    chars = "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    return f"{chars}|5^60,60!11^60,200,60,200"


def _level_record(level_id: str = "00-0") -> str:
    return f"${level_id} LTM test#tests##{_running_exit_level_string()}#"


def test_load_maps_controls_after_first_space_and_trims_only_n_idle_tail(
    tmp_path: Path,
) -> None:
    path = _write_ltm(
        tmp_path / "00-0.ltm", _basic_inputs(), config=_basic_config()
    )

    movie = LtmMovie.load(path)

    assert movie.input_member_name == "inputs"
    assert movie.replay_start == 2
    assert movie.dominant_newline == "\r\n"
    assert movie.ended_with_newline is True
    assert [_frame_bits(frame) for frame in movie.replay_frames] == [
        (True, False, True, True),
        (False, True, True, False),
        (False, True, False, False),
    ]
    assert movie.inferred_neutral_tail_frames == 2
    # K61 and the mouse fields are not N controls, so those frames are still
    # considered neutral when finding the source replay's post-roll.
    assert movie.input_lines[-2:] == (
        "|K61|Mpost:0|",
        "|Mpost:1|",
    )


def test_explicit_postroll_preserves_intentional_neutral_replay_tail(
    tmp_path: Path,
) -> None:
    lines = (
        "|K20|",
        "|Kff51|",
        "|",
        "|K61|",
        "|Mpadding:0|",
        "|Mpadding:1|",
        "|",
    )
    path = _write_ltm(
        tmp_path / "00-0.ltm",
        ("\n".join(lines) + "\n").encode("utf-8"),
        config=_basic_config(frame_count=len(lines)),
    )

    inferred = LtmMovie.load(path)
    fixed_postroll = LtmMovie.load(path, postroll_frames=3)
    no_postroll = LtmMovie.load(path, postroll_frames=0)

    assert len(inferred.replay_frames) == 1
    assert tuple(map(_frame_bits, fixed_postroll.replay_frames)) == (
        (True, False, False, False),
        (False, False, False, False),
        (False, False, False, False),
    )
    assert len(no_postroll.replay_frames) == 6
    assert inferred.inferred_neutral_tail_frames == 5
    assert fixed_postroll.inferred_neutral_tail_frames == 0
    assert no_postroll.inferred_neutral_tail_frames == 0
    assert tuple(map(_frame_bits, no_postroll.replay_frames[-5:])) == (
        (False, False, False, False),
        (False, False, False, False),
        (False, False, False, False),
        (False, False, False, False),
        (False, False, False, False),
    )
    assert fixed_postroll.input_lines == lines
    assert no_postroll.input_lines == lines


def test_explicit_postroll_is_authoritative_and_preserves_tail_input(
    tmp_path: Path,
) -> None:
    lines = ("|K20|", "|Kff51|", "|", "|Kff53|", "|")
    path = _write_ltm(
        tmp_path / "00-0.ltm",
        ("\n".join(lines) + "\n").encode("utf-8"),
        config=_basic_config(frame_count=len(lines)),
    )

    movie = LtmMovie.load(path, postroll_frames=2)

    assert tuple(map(_held_bits, movie.replay_frames)) == (
        (True, False, False),
        (False, False, False),
    )
    output = tmp_path / "authoritative-postroll.ltm"
    movie.write(
        output,
        movie.replay_frames,
        level_id="00-0",
        level_record=_level_record(),
    )
    assert _member_bytes(output, "inputs").decode("utf-8").splitlines()[-2:] == [
        "|Kff53|",
        "|",
    ]


def test_noop_write_preserves_inputs_and_every_original_non_metadata_member(
    tmp_path: Path,
) -> None:
    inputs = _basic_inputs()
    config = _basic_config()
    source = _write_ltm(
        tmp_path / "00-0.ltm",
        inputs,
        config=config,
        extra_members=(
            ("inputs1", b"alternate editor branch\n"),
            ("editor.ini", b"[Editor]\nmarker=17\n"),
            ("nested/notes.bin", b"\x00\x01\xff"),
        ),
    )
    output = tmp_path / "noop.ltm"
    movie = LtmMovie.load(source)

    movie.write(
        output,
        movie.replay_frames,
        level_id="00-0",
        level_record=_level_record(),
    )

    source_members = {
        member.name: raw for member, raw in _regular_members(source)
    }
    output_members = {
        member.name: raw for member, raw in _regular_members(output)
    }
    assert output_members["inputs"] == inputs
    for name, raw in source_members.items():
        assert output_members[name] == raw
    assert set(output_members) == set(source_members) | {METADATA_MEMBER}

    metadata = json.loads(output_members[METADATA_MEMBER])
    assert metadata == {
        "format": METADATA_FORMAT,
        "inputs_member": "inputs",
        "inputs_sha256": hashlib.sha256(inputs).hexdigest(),
        "level_id": "00-0",
        "level_record": _level_record(),
        "replay_start_frame": 2,
        "replay_tick_count": 3,
        "version": METADATA_VERSION,
    }
    reloaded = LtmMovie.load(output)
    assert reloaded.warning is None
    assert reloaded.embedded_level_id == "00-0"
    assert reloaded.embedded_level_record == _level_record()
    assert tuple(map(_frame_bits, reloaded.replay_frames)) == tuple(
        map(_frame_bits, movie.replay_frames)
    )


@pytest.mark.parametrize(
    ("newline", "trailing_whitespace"),
    (
        (b"\n", b"\n"),
        (b"\r\n", b" \t\r\n\r\n"),
    ),
)
def test_terminal_blank_input_lines_are_ignored_as_frames_and_preserved(
    tmp_path: Path,
    newline: bytes,
    trailing_whitespace: bytes,
) -> None:
    inputs = newline.join((b"|K20|", b"|Kff51|", b"|"))
    inputs += newline + trailing_whitespace
    source = _write_ltm(
        tmp_path / "trailing-blank-lines.ltm",
        inputs,
        config=_basic_config(frame_count=3),
    )

    movie = LtmMovie.load(source)

    assert movie.input_lines == ("|K20|", "|Kff51|", "|")
    assert movie.trailing_input_whitespace == trailing_whitespace.decode("utf-8")
    assert tuple(map(_held_bits, movie.replay_frames)) == (
        (True, False, False),
    )

    output = tmp_path / "trailing-blank-lines-output.ltm"
    movie.write(
        output,
        movie.replay_frames,
        level_id="00-0",
        level_record=_level_record(),
    )

    assert _member_bytes(output, "inputs") == inputs
    config = _member_bytes(output, "config.ini").decode("utf-8")
    assert "frame_count=3\n" in config
    assert "savestate_frame_count=3\n" in config
    assert tuple(map(_held_bits, LtmMovie.load(output).replay_frames)) == (
        (True, False, False),
    )


def test_writer_fsyncs_through_a_windows_compatible_writable_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_ltm(
        tmp_path / "00-0.ltm",
        _basic_inputs(),
        config=_basic_config(),
    )
    movie = LtmMovie.load(source)
    output = tmp_path / "checkpoint.ltm"
    real_fsync = os.fsync
    fsync_calls = 0

    def windows_compatible_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        # Windows' _commit rejects a read-only descriptor.  A zero-byte write
        # makes the same access-mode requirement observable on POSIX without
        # changing the archive.
        assert os.write(descriptor, b"") == 0
        fsync_calls += 1
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", windows_compatible_fsync)

    # Exercise both the first checkpoint and replacement of that checkpoint.
    for frames in (
        movie.replay_frames,
        (
            InputFrame(right=True),
            InputFrame(),
            InputFrame(left=True, jump=True, jump_trigger=True),
        ),
    ):
        movie.write(
            output,
            frames,
            level_id="00-0",
            level_record=_level_record(),
        )

    assert fsync_calls == 2
    assert tuple(map(_held_bits, LtmMovie.load(output).replay_frames)) == (
        (False, True, False),
        (False, False, False),
        (True, False, True),
    )


def test_writer_uses_loaded_archive_snapshot_if_source_path_changes(
    tmp_path: Path,
) -> None:
    source = _write_ltm(
        tmp_path / "00-0.ltm",
        _basic_inputs(),
        config=_basic_config(),
        extra_members=(("annotations.txt", b"original\n"),),
    )
    movie = LtmMovie.load(source)
    _write_ltm(
        source,
        _basic_inputs(),
        config=_basic_config(),
        extra_members=(("annotations.txt", b"replacement\n"),),
    )

    output = tmp_path / "snapshot-output.ltm"
    movie.write(
        output,
        movie.replay_frames,
        level_id="00-0",
        level_record=_level_record(),
    )

    assert _member_bytes(output, "annotations.txt") == b"original\n"


def test_edits_replace_only_n_controls_in_replay_body(tmp_path: Path) -> None:
    source = _write_ltm(
        tmp_path / "00-0.ltm",
        _basic_inputs(),
        config=_basic_config(),
        extra_members=(("inputs4", b"do not touch\n"),),
    )
    output = tmp_path / "edited.ltm"
    movie = LtmMovie.load(source)
    edited = (
        InputFrame(right=True),
        InputFrame(),
        InputFrame(left=True, right=True, jump=True, jump_trigger=True),
    )

    movie.write(
        output,
        edited,
        level_id="00-0",
        level_record=_level_record(),
    )

    assert _member_bytes(output, "inputs").decode("utf-8").splitlines() == [
        "|Kff52|Mpre:1|",
        "|Mspace:2|K20:ff52|",
        "|K61:ff53|Mbody:0|",
        "|Mbody:1|K61|",
        "|Kffe1:ff51:ff53|C1:unchanged|",
        "|K61|Mpost:0|",
        "|Mpost:1|",
    ]
    assert _member_bytes(output, "inputs4") == b"do not touch\n"
    assert _member_bytes(output, "config.ini") == _basic_config()
    assert tuple(map(_held_bits, LtmMovie.load(output).replay_frames)) == tuple(
        map(_held_bits, edited)
    )


@pytest.mark.parametrize(
    ("frames", "expected_lines", "expected_count", "expected_nsec"),
    (
        (
            (InputFrame(jump=True, jump_trigger=True),),
            (
                "|K20|",
                "|Kffe1|Xone|",
                "|K61|post|",
                "|post2|",
            ),
            4,
            400_000_000,
        ),
        (
            (
                InputFrame(left=True),
                InputFrame(right=True),
                InputFrame(jump=True, jump_trigger=True),
                InputFrame(left=True, right=True, jump=True),
            ),
            (
                "|K20|",
                "|Kff51|Xone|",
                "|Kff53|",
                "|Kffe1|",
                "|Kffe1:ff51:ff53|",
                "|K61|post|",
                "|post2|",
            ),
            7,
            700_000_000,
        ),
    ),
)
def test_shorter_and_longer_replays_resize_config_and_pad_new_input_frames(
    tmp_path: Path,
    frames: tuple[InputFrame, ...],
    expected_lines: tuple[str, ...],
    expected_count: int,
    expected_nsec: int,
) -> None:
    source_inputs = (
        "|K20|\n"
        "|Kff51|Xone|\n"
        "|Kff53|\n"
        "|K61|post|\n"
        "|post2|\n"
    ).encode("utf-8")
    source = _write_ltm(
        tmp_path / "00-0.ltm",
        source_inputs,
        config=_basic_config(frame_count=5),
    )
    output = tmp_path / f"resized-{expected_count}.ltm"
    movie = LtmMovie.load(source)

    movie.write(
        output,
        frames,
        level_id="00-0",
        level_record=_level_record(),
    )

    assert tuple(
        _member_bytes(output, "inputs").decode("utf-8").splitlines()
    ) == expected_lines
    config = _member_bytes(output, "config.ini").decode("utf-8")
    assert f"frame_count={expected_count}\n" in config
    assert f"savestate_frame_count={expected_count}\n" in config
    assert "length_sec=0\n" in config
    assert f"length_nsec={expected_nsec}\n" in config
    assert "untouched=value\n" in config
    assert len(LtmMovie.load(output).replay_frames) == len(frames)


def test_shortening_refuses_to_discard_non_n_input_data(tmp_path: Path) -> None:
    source = _write_ltm(
        tmp_path / "00-0.ltm",
        b"|K20|\n|Kff51|\n|Kff53|Mclick:1|\n|post|\n",
        config=_basic_config(frame_count=4),
    )
    movie = LtmMovie.load(source)

    with pytest.raises(LtmError, match="discarding non-N input data"):
        movie.write(
            tmp_path / "unsafe-shortening.ltm",
            (InputFrame(left=True),),
            level_id="00-0",
            level_record=_level_record(),
        )


def test_metadata_round_trip_keeps_deliberate_trailing_neutral_replay_frames(
    tmp_path: Path,
) -> None:
    source = _write_ltm(
        tmp_path / "00-0.ltm",
        b"|K20|\n|Kff51|body|\n|Kff53|body|\n|K61|post-a|\n|post-b|\n",
        config=_basic_config(frame_count=5),
    )
    first_output = tmp_path / "with-neutral-tail.ltm"
    second_output = tmp_path / "round-trip.ltm"
    frames = (
        InputFrame(left=True),
        InputFrame(right=True),
        InputFrame(),
        InputFrame(),
    )

    LtmMovie.load(source).write(
        first_output,
        frames,
        level_id="00-0",
        level_record=_level_record(),
    )
    reloaded = LtmMovie.load(first_output)
    assert reloaded.inferred_neutral_tail_frames == 0
    assert tuple(map(_held_bits, reloaded.replay_frames)) == tuple(
        map(_held_bits, frames)
    )
    assert json.loads(_member_bytes(first_output, METADATA_MEMBER))[
        "replay_tick_count"
    ] == 4

    reloaded.write(
        second_output,
        reloaded.replay_frames,
        level_id="00-0",
        level_record=_level_record(),
    )
    assert _member_bytes(second_output, "inputs") == _member_bytes(
        first_output, "inputs"
    )
    assert tuple(
        map(_held_bits, LtmMovie.load(second_output).replay_frames)
    ) == tuple(map(_held_bits, frames))


@pytest.mark.parametrize(
    ("members", "message"),
    (
        ((("notes", b"no inputs\n"),), "top-level 'inputs'"),
        ((("nested/inputs", b"|K20|\n|Kff51|\n"),), "top-level 'inputs'"),
        (
            (("inputs", b"|K20|\n|Kff51|\n"),),
            "top-level 'config.ini'",
        ),
        (
            (
                ("inputs", b"|Kff51|\n"),
                ("config.ini", _basic_config(frame_count=1)),
            ),
            "no Space press",
        ),
        (
            (
                ("inputs", b"|K20|\n"),
                ("config.ini", _basic_config(frame_count=1)),
            ),
            "end immediately after",
        ),
        (
            (
                ("inputs", b"|K20|\n|Kff51|Kff53|\n"),
                ("config.ini", _basic_config(frame_count=2)),
            ),
            "more than one keyboard field",
        ),
        (
            (
                ("inputs", b"|K20|\n\n|Kff51|\n"),
                ("config.ini", _basic_config(frame_count=3)),
            ),
            "input frame 1 does not begin",
        ),
        (
            (
                ("inputs", b"|K20|\n\xff\n"),
                ("config.ini", _basic_config(frame_count=2)),
            ),
            "not valid UTF-8",
        ),
        (
            (
                ("inputs", b"|K20|\n|Kff51|\n"),
                ("./inputs", b"|K20|\n|Kff53|\n"),
            ),
            "more than one top-level 'inputs'",
        ),
    ),
)
def test_malformed_movies_fail_with_actionable_errors(
    tmp_path: Path,
    members: tuple[tuple[str, bytes], ...],
    message: str,
) -> None:
    path = _write_members(tmp_path / "bad.ltm", members)

    with pytest.raises(LtmError, match=message):
        LtmMovie.load(path)


def test_stale_metadata_is_ignored_and_trailing_idle_is_inferred(
    tmp_path: Path,
) -> None:
    inputs = b"|K20|\n|Kff51|\n|\n|\n"
    stale_metadata = json.dumps(
        {
            "format": METADATA_FORMAT,
            "version": METADATA_VERSION,
            "inputs_member": "inputs",
            "inputs_sha256": "0" * 64,
            "replay_start_frame": 1,
            "replay_tick_count": 3,
            "level_id": "00-0",
            "level_record": _level_record(),
        }
    ).encode("utf-8")
    path = _write_ltm(
        tmp_path / "stale.ltm",
        inputs,
        config=_basic_config(frame_count=4),
        extra_members=((METADATA_MEMBER, stale_metadata),),
    )

    movie = LtmMovie.load(path)

    assert len(movie.replay_frames) == 1
    assert movie.warning is not None
    assert "stale" in movie.warning
    assert movie.embedded_level_id == "00-0"
    assert movie.embedded_level_record == _level_record()


@pytest.mark.parametrize(
    ("timing_field", "message"),
    (
        ("Tbad", "invalid LTM timing field"),
        ("T40:0", "timing-field values must be positive"),
        ("T40:1|T60:1", "more than one timing field"),
    ),
)
def test_load_rejects_malformed_per_frame_timing_fields(
    tmp_path: Path,
    timing_field: str,
    message: str,
) -> None:
    inputs = f"|K20|{timing_field}|\n|Kff51|\n".encode("utf-8")
    path = _write_ltm(
        tmp_path / "bad-timing.ltm",
        inputs,
        config=_basic_config(frame_count=2),
    )

    with pytest.raises(LtmError, match=message):
        LtmMovie.load(path)


@pytest.mark.parametrize(
    ("actual_member", "metadata_member"),
    (("inputs", "./inputs"), ("./inputs", "inputs")),
)
def test_metadata_survives_equivalent_root_input_member_spelling(
    tmp_path: Path,
    actual_member: str,
    metadata_member: str,
) -> None:
    inputs = b"|K20|\n|Kff51|\n|\n|Mpost:0|\n"
    metadata = {
        "format": METADATA_FORMAT,
        "version": METADATA_VERSION,
        "inputs_member": metadata_member,
        "inputs_sha256": hashlib.sha256(inputs).hexdigest(),
        "replay_start_frame": 1,
        "replay_tick_count": 2,
        "level_id": "00-0",
        "level_record": _level_record(),
    }
    path = _write_members(
        tmp_path / "renamed-input-member.ltm",
        (
            (actual_member, inputs),
            ("config.ini", _basic_config(frame_count=4)),
            (METADATA_MEMBER, json.dumps(metadata).encode("utf-8")),
        ),
    )

    movie = LtmMovie.load(path)

    assert movie.input_member_name == actual_member
    assert movie.warning is None
    assert len(movie.replay_frames) == 2
    assert _frame_bits(movie.replay_frames[-1]) == (
        False,
        False,
        False,
        False,
    )
    assert movie.embedded_level_id == "00-0"
    assert movie.embedded_level_record == _level_record()


@pytest.mark.parametrize(
    ("filename", "expected"),
    (
        ("00-0.ltm", "00-0"),
        ("00-0_rta.ltm", "00-0"),
        ("00-0_hs.ltm", "00-0"),
        ("12-34-custom-name.LTM", "12-34"),
        ("12-34 TAS.ltm", "12-34"),
        ("12-34.hs.ltm", "12-34"),
        ("prefix_00-0.ltm", None),
        ("00-0rta.ltm", None),
        ("0-0_rta.ltm", None),
        ("00-0_.ltm", None),
        ("00-0_rta.txt", None),
    ),
)
def test_ltm_filename_level_inference_accepts_delimited_labels(
    filename: str,
    expected: str | None,
) -> None:
    assert infer_level_id_from_ltm_filename(Path(filename)) == expected


def test_load_source_uses_labelled_ltm_filename_level_id(tmp_path: Path) -> None:
    source = _write_ltm(
        tmp_path / "00-0_rta.ltm",
        _basic_inputs(),
        config=_basic_config(),
    )
    levels = tmp_path / LEVEL_DATABASE_NAME
    levels.write_text(_level_record() + "\n", encoding="utf-8")

    loaded = cli._load_source(
        source,
        levels_file_path=levels,
        explicit_level_id=None,
        ltm_postroll=None,
    )

    assert loaded.level_id == "00-0"
    assert loaded.level_record == _level_record()


def test_level_database_lookup_and_discovery_are_exact(tmp_path: Path) -> None:
    record = _level_record("00-0")
    decoy = _level_record("00-00")
    levels = tmp_path / LEVEL_DATABASE_NAME
    levels.write_text("\ufeff" + decoy + "\n" + record + "\r\n", encoding="utf-8")

    assert find_level_record(levels, "00-0") == record
    assert discover_levels_file(
        tmp_path / "00-0.ltm", None, program_root=tmp_path / "program"
    ) == levels
    assert discover_levels_file(
        tmp_path / "00-0.ltm", levels, program_root=tmp_path / "program"
    ) == levels

    levels.write_text(record + "\n" + record + "\n", encoding="utf-8")
    with pytest.raises(LtmError, match="occurs 2 times"):
        find_level_record(levels, "00-0")
    with pytest.raises(LtmError, match="was not found"):
        find_level_record(levels, "01-0")


def test_level_database_discovery_checks_parent_of_cwd_external(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    working_directory = tmp_path / "working"
    working_directory.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    levels = external / LEVEL_DATABASE_NAME
    levels.write_text(_level_record() + "\n", encoding="utf-8")
    input_path = tmp_path / "movies" / "00-0.ltm"
    program_root = tmp_path / "program"
    monkeypatch.chdir(working_directory)

    assert discover_levels_file(
        input_path,
        None,
        program_root=program_root,
    ) == levels


def test_ltm_cli_options_are_supported_directly_and_through_toml(
    tmp_path: Path,
) -> None:
    levels = tmp_path / "levels.txt"
    output = tmp_path / "output.ltm"
    replay_output = tmp_path / "replay.txt"
    direct = opt.parse_arguments(
        [
            "auto",
            str(tmp_path / "movie.ltm"),
            "--levels-file",
            str(levels),
            "--level-id",
            "00-0",
            "--ltm-postroll",
            "3",
            "--output",
            str(output),
            "--replay-output",
            str(replay_output),
            "--iterations",
            "0",
        ]
    )
    assert direct.levels_file == levels
    assert direct.level_id == "00-0"
    assert direct.ltm_postroll == 3
    assert direct.output == output
    assert direct._mode_configs.common.levels_file_path == levels
    assert direct._mode_configs.common.level_id == "00-0"
    assert direct._mode_configs.common.ltm_postroll == 3

    config = tmp_path / "config.toml"
    config.write_text(
        "[common]\n"
        f'levels_file = "{levels.as_posix()}"\n'
        'level_id = "00-0"\n'
        "ltm_postroll = 0\n"
        f'output = "{output.as_posix()}"\n'
        f'replay_output = "{replay_output.as_posix()}"\n'
        "\n[auto]\niterations = 0\n",
        encoding="utf-8",
    )
    configured = opt.parse_arguments(
        ["auto", str(tmp_path / "movie.ltm"), "--config", str(config)]
    )
    assert configured.levels_file == levels
    assert configured.level_id == "00-0"
    assert configured.ltm_postroll == 0
    assert configured.output == output
    assert configured.replay_output == replay_output
    assert configured.iterations == 0


def test_auto_iterations_zero_reads_and_writes_ltm_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_frames = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    input_lines = ["|Mboot:0|", "|K20|Mboot:1|"]
    input_lines.extend(
        "|Kff53|" if frame.right else "|"
        for frame in source_frames
    )
    input_lines.extend(("|K61|Mpost:0|", "|Mpost:1|", "|Mpost:2|"))
    input_raw = ("\n".join(input_lines) + "\n").encode("utf-8")
    source = _write_ltm(
        tmp_path / "00-0.ltm",
        input_raw,
        config=_basic_config(frame_count=len(input_lines)),
        extra_members=(("inputs7", b"alternate branch must survive\n"),),
    )
    levels = tmp_path / LEVEL_DATABASE_NAME
    levels.write_text(_level_record() + "\n", encoding="utf-8")
    output = tmp_path / "optimised.ltm"
    replay_output = tmp_path / "optimised.replay.txt"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto",
            str(source),
            "--iterations",
            "0",
            "--beam",
            "2",
            "--workers",
            "1",
            "--levels-file",
            str(levels),
            "--output",
            str(output),
            "--replay-output",
            str(replay_output),
        ],
    )

    opt.main()

    assert output.is_file()
    assert _member_bytes(output, "inputs7") == b"alternate branch must survive\n"
    movie = LtmMovie.load(output)
    assert movie.warning is None
    assert movie.embedded_level_id == "00-0"
    assert movie.embedded_level_record == _level_record()
    assert len(movie.replay_frames) == 34
    assert tuple(
        decode_complex_replay(
            replay_output.read_text(encoding="utf-8").strip()
        ).frames
    ) == movie.replay_frames

    # The embedded record makes a renamed optimiser output self-contained; it
    # no longer needs the external database or an inferable filename.
    levels.unlink()
    monkeypatch.setattr(
        sys,
        "argv",
        ["optimize_replay.py", "auto", str(output), "--list-objects"],
    )
    opt.main()
    level = parse_level_string(_running_exit_level_string(), simulate_enemies=True)
    verified = verify_trimmed_replay(level, editable_frames(movie.replay_frames))
    assert verified.valid
    assert verified.finish_tick == 34


def test_auto_probes_and_promotes_raw_ltm_neutral_completion_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_lines = ["|K20|"]
    input_lines.extend(["|Kff53|"] * 20)
    input_lines.extend(f"|Mtail:{index}|" for index in range(50))
    input_raw = ("\n".join(input_lines) + "\n").encode("utf-8")
    source = _write_ltm(
        tmp_path / "00-0_rta.ltm",
        input_raw,
        config=_basic_config(frame_count=len(input_lines)),
    )
    levels = tmp_path / LEVEL_DATABASE_NAME
    levels.write_text(_level_record() + "\n", encoding="utf-8")
    output = tmp_path / "neutral-tail-output.ltm"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto",
            str(source),
            "--iterations",
            "0",
            "--workers",
            "1",
            "--output",
            str(output),
        ],
    )

    opt.main()

    assert _member_bytes(output, "inputs") == input_raw
    movie = LtmMovie.load(output)
    assert movie.inferred_neutral_tail_frames == 0
    assert len(movie.replay_frames) == 54
    assert movie.input_lines[movie.replay_start + 54] == "|Mtail:34|"
    metadata = json.loads(_member_bytes(output, METADATA_MEMBER))
    assert metadata["replay_tick_count"] == 54
    level = parse_level_string(_running_exit_level_string(), simulate_enemies=True)
    assert verify_trimmed_replay(
        level,
        editable_frames(movie.replay_frames),
    ).finish_tick == 54


def test_auto_accepts_a_fully_inputless_raw_ltm_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_lines = ["|K20|"]
    input_lines.extend(f"|Mtail:{index}|" for index in range(60))
    input_raw = ("\n".join(input_lines) + "\n").encode("utf-8")
    source = _write_ltm(
        tmp_path / "00-0_rta.ltm",
        input_raw,
        config=_basic_config(frame_count=len(input_lines)),
    )
    raw_movie = LtmMovie.load(source)
    assert raw_movie.replay_frames == ()
    assert raw_movie.inferred_neutral_tail_frames == 60
    level_record = (
        f"$00-0 inputless LTM test#tests##{_falling_exit_level_string()}#"
    )
    levels = tmp_path / LEVEL_DATABASE_NAME
    levels.write_text(level_record + "\n", encoding="utf-8")
    output = tmp_path / "inputless-output.ltm"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto",
            str(source),
            "--iterations",
            "0",
            "--workers",
            "1",
            "--output",
            str(output),
        ],
    )

    opt.main()

    assert _member_bytes(output, "inputs") == input_raw
    movie = LtmMovie.load(output)
    assert len(movie.replay_frames) == 44
    assert movie.input_lines[movie.replay_start + 44] == "|Mtail:44|"
    assert json.loads(_member_bytes(output, METADATA_MEMBER))[
        "replay_tick_count"
    ] == 44
    level = parse_level_string(_falling_exit_level_string(), simulate_enemies=True)
    assert verify_trimmed_replay(
        level,
        editable_frames(movie.replay_frames),
    ).finish_tick == 44


@pytest.mark.parametrize("neutral_rows", (10, 34))
def test_auto_neutral_tail_probe_is_bounded_by_available_ltm_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    neutral_rows: int,
) -> None:
    input_lines = [
        "|K20|",
        *(["|Kff53|"] * 20),
        *(["|"] * neutral_rows),
    ]
    source = _write_ltm(
        tmp_path / "00-0_hs.ltm",
        ("\n".join(input_lines) + "\n").encode("utf-8"),
        config=_basic_config(frame_count=len(input_lines)),
    )
    levels = tmp_path / LEVEL_DATABASE_NAME
    levels.write_text(_level_record() + "\n", encoding="utf-8")
    output = tmp_path / "incomplete.ltm"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto",
            str(source),
            "--iterations",
            "0",
            "--workers",
            "1",
            "--output",
            str(output),
        ],
    )

    with pytest.raises(SystemExit, match="no exit completion"):
        opt.main()
    assert not output.exists()

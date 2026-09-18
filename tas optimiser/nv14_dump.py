"""Native player capture and atomic CSV output from replay data or files."""
from __future__ import annotations

import argparse
import csv
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from nv14_engine import InputFrame
from nv14_ltm import (
    LtmError, LtmMovie, discover_levels_file, find_level_record,
    infer_level_id_from_ltm_filename, validate_level_id,
    _replace_with_windows_retries,
)
from nv14_native import require_native
from nv14_replay import CombinedLevelReplay, ComplexReplay, decode_complex_replay, parse_combined_level_replay

if TYPE_CHECKING:
    from _nv14_native import NativeLevel


@dataclass(frozen=True, slots=True)
class PlayerDumpSource:
    level_string: str
    frames: Sequence[InputFrame]
    input_kind: str
    ltm_start: int | None = None
    levels_file: Path | None = None
    level_name: str = ""
    level_author: str = ""


@dataclass(frozen=True, slots=True)
class PlayerDumpResult:
    output_path: Path
    rows: int
    source_frames: int
    stop_reason: str
    final_neutral_written: bool
    dead: bool
    complete: bool


def _external_level(
    input_path: Path, levels_file: Path | None, level_id: str | None,
) -> tuple[CombinedLevelReplay, Path]:
    if level_id is None:
        level_id = infer_level_id_from_ltm_filename(input_path.with_suffix(".ltm"))
    if level_id is None:
        raise LtmError(
            f"cannot infer a level id from {input_path.name!r}; pass --level-id 00-0"
        )
    validate_level_id(level_id)
    path = discover_levels_file(
        input_path, levels_file, program_root=Path(__file__).resolve().parent,
    )
    record = find_level_record(path, level_id)
    level = parse_combined_level_replay(record + "0:#")
    return level, path


def load_player_dump_source(
    input_path: Path, *, levels_file: Path | None = None,
    level_id: str | None = None, ltm_postroll: int | None = None,
) -> PlayerDumpSource:
    """Load unmodified controls; retain the LTM's recorded neutral tail by default."""
    input_path = Path(input_path)
    if input_path.suffix.lower() == ".ltm":
        movie = LtmMovie.load(
            input_path, postroll_frames=0 if ltm_postroll is None else ltm_postroll,
        )
        level, path = _external_level(input_path, levels_file, level_id)
        return PlayerDumpSource(level.level_string, movie.replay_frames, "ltm",
                                movie.replay_start, path, level.name, level.author)
    if ltm_postroll is not None:
        raise ValueError("--ltm-postroll is only valid for an .ltm input")
    text = input_path.read_text(encoding="utf-8-sig").strip()
    if re.match(r"^\d+:", text):
        frames = decode_complex_replay(text).frames
        level, path = _external_level(input_path, levels_file, level_id)
        return PlayerDumpSource(level.level_string, frames, "demo", levels_file=path,
                                level_name=level.name, level_author=level.author)
    if levels_file is not None or level_id is not None:
        raise ValueError(
            "--levels-file and --level-id are for LTM or packed-only demos; "
            "a combined demo already contains its level"
        )
    combined = parse_combined_level_replay(text)
    # Stored trigger bits can intentionally differ from held-input edges. Do
    # not pass through editable_frames() or canonicalise_jump_triggers here.
    return PlayerDumpSource(
        combined.level_string, decode_complex_replay(combined.replay_string).frames, "demo",
        level_name=combined.name if combined.level_index >= 2 else "",
        level_author=combined.author if combined.level_index >= 2 else "",
    )


def dump_player_csv(
    input_path: Path, output_path: Path | None = None, *,
    levels_file: Path | None = None, level_id: str | None = None,
    ltm_postroll: int | None = None, final_neutral: bool = True,
    simulate_enemies: bool = True, visual_timeline_frames: int = 3,
    celebration_variant: int = 0, chunk_size: int = 4096,
    fields: Sequence[str] | None = None,
) -> PlayerDumpResult:
    """Write one post-tick CSV row through the first death/completion or input end.

    Physics, animation and per-tick capture run in C. Python decodes the input
    and formats bounded chunks of tuples as CSV. The temporary CSV replaces
    the destination only after success, including when interrupted mid-chunk.
    Demo text gets one labelled neutral sentinel unless final_neutral=False.
    LTM never gets a synthetic tick beyond its selected recorded input range.
    fields selects CSV columns in the supplied order; None writes all columns.
    """
    input_path = Path(input_path)
    output_path = _validate_dump_output(
        output_path if output_path is not None else input_path.with_name(
            input_path.stem + ".player.csv"
        ),
        chunk_size,
    )
    # Reuse the optimiser's alias check, including hard links and symlinks.
    from nv14_cli import _paths_alias

    if _paths_alias(input_path, output_path):
        raise ValueError("input and CSV output must be different files")
    source = load_player_dump_source(
        input_path, levels_file=levels_file, level_id=level_id, ltm_postroll=ltm_postroll,
    )
    if source.levels_file is not None and _paths_alias(source.levels_file, output_path):
        raise ValueError("levels file and CSV output must be different files")

    return _dump_player_frames_csv(
        source.level_string, source.frames, output_path,
        input_kind=source.input_kind, ltm_start=source.ltm_start,
        final_neutral=final_neutral, simulate_enemies=simulate_enemies,
        visual_timeline_frames=visual_timeline_frames,
        celebration_variant=celebration_variant, chunk_size=chunk_size,
        fields=fields,
    )


def dump_player_data_csv(
    level_data: str | NativeLevel,
    replay_data: str | ComplexReplay | Sequence[InputFrame],
    output_path: str | os.PathLike[str], *,
    final_neutral: bool = True, simulate_enemies: bool = True,
    visual_timeline_frames: int = 3, celebration_variant: int = 0,
    chunk_size: int = 4096,
    fields: Sequence[str] | None = None,
) -> PlayerDumpResult:
    """Export supplied level/replay data without input files or database lookup.

    level_data is the raw tile/object string or a reusable NativeLevel. A
    NativeLevel must have been parsed with the requested simulate_enemies
    setting. Every call creates its own fresh tracked state.

    replay_data is a '<ticks>:<packed words>' string, a ComplexReplay, or a
    sequence of InputFrame records. Stored triggers are preserved; None
    triggers are derived by the native engine. Inputs are not modified.

    CSV schema, terminal handling and visual defaults match dump_player_csv.
    Input rows are labelled 'demo' and ltm_frame is blank. A labelled final
    neutral tick is enabled by default; set final_neutral=False when the
    supplied frames already include the required neutral input.

    fields is an optional nonempty sequence of unique CSV field names, in
    output order. None writes the full schema. Selection affects CSV output
    only; native capture still collects the full state and all visual fields.

    Returns PlayerDumpResult. Invalid data, unsupported native levels and I/O
    failures raise exceptions; no CSV replacement occurs unless export
    succeeds. Capture buffers are bounded by chunk_size; decoded replay data
    is held in memory. Callers can loop over jobs without temporary demos.
    """
    output_path = _validate_dump_output(output_path, chunk_size)
    if isinstance(replay_data, str):
        text = replay_data.strip().removeprefix("\ufeff").strip()
        # The shared decoder permits negative tick counts; reject them at
        # this entry point, as the existing file loader already does.
        if not re.match(r"^\d+:", text):
            raise ValueError("replay_data must use '<ticks>:<packed words>' format")
        frames = decode_complex_replay(text).frames
    else:
        frames = replay_data.frames if isinstance(replay_data, ComplexReplay) else replay_data
        if not isinstance(frames, Sequence) or isinstance(frames, (str, bytes, bytearray, memoryview)):
            raise TypeError(
                "replay_data must be a packed replay string, ComplexReplay, "
                "or a sequence of InputFrame records"
            )
        if any(not isinstance(frame, InputFrame) for frame in frames):
            raise TypeError("decoded replay_data must contain only InputFrame records")

    return _dump_player_frames_csv(
        level_data, frames, output_path, input_kind="demo", ltm_start=None,
        final_neutral=final_neutral, simulate_enemies=simulate_enemies,
        visual_timeline_frames=visual_timeline_frames,
        celebration_variant=celebration_variant, chunk_size=chunk_size,
        fields=fields,
    )


def _validate_dump_output(output_path: str | os.PathLike[str], chunk_size: int) -> Path:
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or not 1 <= chunk_size <= 65536:
        raise ValueError("chunk_size must be an integer from 1 to 65536")
    path = Path(output_path)
    if path.suffix.lower() != ".csv":
        raise ValueError("player dump output must have a .csv extension")
    return path


def _dump_player_frames_csv(
    level_data: str | NativeLevel, frames: Sequence[InputFrame], output_path: Path, *,
    input_kind: str, ltm_start: int | None,
    final_neutral: bool, simulate_enemies: bool, visual_timeline_frames: int,
    celebration_variant: int, chunk_size: int,
    fields: Sequence[str] | None,
) -> PlayerDumpResult:
    """Shared native capture/writer for already loaded replay inputs."""
    native = require_native()
    if not native.backend_info().get("player_dump_abi"):
        raise RuntimeError("player dump requires a v4.01-or-newer extension; run python build_native.py")
    columns = native.PLAYER_DUMP_COLUMNS
    csv_columns, field_indices = _resolve_dump_fields(
        fields, (*columns, "ltm_frame", "input_kind"),
    )
    if isinstance(level_data, str):
        level = native.parse_level_string(level_data, simulate_enemies=simulate_enemies)
    elif isinstance(level_data, native.NativeLevel):
        level = level_data
        if level.simulate_enemies != bool(simulate_enemies):
            raise ValueError("simulate_enemies must match the supplied NativeLevel")
    else:
        raise TypeError("level_data must be a raw level string or a NativeLevel")
    state = level.initial_state(
        track_visuals=True, visual_timeline_frames=visual_timeline_frames,
        celebration_variant=celebration_variant,
    )
    complete_index = columns.index("complete")
    dead_index = columns.index("dead")
    frame_index = columns.index("frame")
    source_count = len(frames)
    sentinel = input_kind == "demo" and final_neutral
    input_count = source_count + int(sentinel)
    rows_written = 0
    final_neutral_written = False
    dead = complete = False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(csv_columns)
            for offset in range(0, input_count, chunk_size):
                end = min(offset + chunk_size, input_count)
                chunk = list(frames[offset:min(end, source_count)])
                if sentinel and end > source_count:
                    chunk.append(InputFrame())
                captured = state.capture_player_frames(chunk)
                for row in captured:
                    frame = row[frame_index]
                    is_sentinel = sentinel and frame == source_count
                    kind = "final_neutral" if is_sentinel else input_kind
                    movie_frame = "" if ltm_start is None else ltm_start + frame
                    full_row = (*row, movie_frame, kind)
                    writer.writerow(
                        full_row if field_indices is None else
                        tuple(full_row[index] for index in field_indices)
                    )
                    rows_written += 1
                    final_neutral_written |= is_sentinel
                if captured:
                    complete = bool(captured[-1][complete_index])
                    dead = bool(captured[-1][dead_index])
                if complete or dead:
                    break
            stream.flush()
            os.fsync(stream.fileno())
        _replace_with_windows_retries(temporary_path, output_path)
    except BaseException:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise
    return PlayerDumpResult(
        output_path, rows_written, source_count,
        "complete" if complete else "dead" if dead else "end_of_input",
        final_neutral_written, dead, complete,
    )


def _resolve_dump_fields(
    fields: Sequence[str] | None, columns: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[int, ...] | None]:
    """Validate once before creating output; freeze order and resolve indices."""
    if fields is None:
        return columns, None
    if not isinstance(fields, Sequence) or isinstance(fields, (str, bytes, bytearray, memoryview)):
        raise TypeError("fields must be a sequence of CSV field names, or None")
    selected = tuple(fields)
    if not selected:
        raise ValueError("fields must contain at least one CSV field name")
    seen: set[str] = set()
    for field in selected:
        if not isinstance(field, str):
            raise TypeError("fields must contain only string field names")
        if field not in columns:
            raise ValueError(
                f"unknown CSV field {field!r}; valid fields: {', '.join(columns)}"
            )
        if field in seen:
            raise ValueError(f"duplicate CSV field {field!r}")
        seen.add(field)
    return selected, tuple(columns.index(field) for field in selected)


def add_player_dump_arguments(parser: argparse.ArgumentParser) -> None:
    from nv14_cli import parse_ltm_level_id, parse_nonnegative_int

    parser.add_argument("input", type=Path, help="combined demo, packed demo text, or libTAS .ltm")
    parser.add_argument("--output", "-o", type=Path, help="CSV destination (default: <input stem>.player.csv)")
    parser.add_argument("--levels-file", type=Path, help="N level database for LTM or packed-only demo input")
    parser.add_argument("--level-id", type=parse_ltm_level_id, help="level id if it cannot be inferred from the filename")
    parser.add_argument(
        "--ltm-postroll", type=parse_nonnegative_int, metavar="N",
        help="exclude exactly N recorded trailing LTM frames (default: retain all until terminal)",
    )
    parser.add_argument(
        "--final-neutral", action=argparse.BooleanOptionalAction, default=True,
        help="append one labelled neutral tick to demo text (default: enabled; LTM uses only recorded frames)",
    )
    parser.add_argument(
        "--simulate-enemies", action=argparse.BooleanOptionalAction, default=True,
        help="simulate supported enemies (default: enabled)",
    )
    parser.add_argument(
        "--visual-timeline-frames", type=parse_nonnegative_int, default=3, metavar="N",
        help="MovieClip advances before each gameplay tick (default: 3, nominal 120/40 fps)",
    )
    parser.add_argument(
        "--celebration-variant", type=int, choices=range(10), default=0,
        help="0 leaves the random choice unresolved; 1..9 supplies a celebration variant",
    )
    parser.add_argument("--config", type=Path, help="TOML defaults from [common] and [dump-player]")


def run_player_dump(args: argparse.Namespace) -> None:
    try:
        result = dump_player_csv(
            args.input, args.output, levels_file=args.levels_file, level_id=args.level_id,
            ltm_postroll=args.ltm_postroll, final_neutral=args.final_neutral,
            simulate_enemies=args.simulate_enemies,
            visual_timeline_frames=args.visual_timeline_frames,
            celebration_variant=args.celebration_variant,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"player dump failed: {exc}; CSV output was not replaced") from exc
    print(
        f"wrote {result.output_path}: {result.rows} frame rows; "
        f"stop={result.stop_reason}; complete={int(result.complete)}; dead={int(result.dead)}; "
        f"final_neutral={int(result.final_neutral_written)}"
    )

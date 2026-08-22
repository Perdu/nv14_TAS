#!/usr/bin/env python3
"""AI-generated

Convert a libTAS .ltm movie for N v1.4 into a combined level+demo string.

Expected project layout (relative to this script):

    volume/n_levels/00-0.ltm
    external/N v1.4 + NReality levels.txt

Usage:

    python3 ltm_to_demo.py 00-0

The first N replay frame is the libTAS frame immediately after the first frame
on which Space is pressed.  libTAS key codes are mapped as follows:

    ff51  Left
    ff53  Right
    ffe1  Shift_L (N jump)

The generated N v1.4 complex replay uses seven 4-bit input frames per decimal
word, low-nibble first:

    bit 0  left
    bit 1  right
    bit 2  jump held
    bit 3  jump trigger (derived from the rising edge of jump held)
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import re
import sys
import tarfile
from dataclasses import dataclass


LEVELS_RELATIVE_PATH = Path("external") / "N v1.4 + NReality levels.txt"
LTM_DIRECTORY = Path("volume") / "n_levels"

# X11/libTAS keyboard keysyms used by this project, written as libTAS writes
# them after the leading "K" in the inputs file.
KEY_SPACE = "20"
KEY_LEFT = "ff51"
KEY_RIGHT = "ff53"
KEY_JUMP = "ffe1"  # Shift_L

LEVEL_ID_RE = re.compile(r"^\d{2}-\d+$")
KEYBOARD_FIELD_RE = re.compile(r"(?:^|\|)K([^|]*)")


class ConversionError(RuntimeError):
    """A user-facing conversion error."""


@dataclass(frozen=True, slots=True)
class InputFrame:
    left: bool = False
    right: bool = False
    jump: bool = False
    jump_trigger: bool = False

    @property
    def is_idle(self) -> bool:
        return not (self.left or self.right or self.jump)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert volume/n_levels/<level>.ltm to an N v1.4 complex replay, "
            "append it to that level's data, and print the combined record."
        )
    )
    parser.add_argument(
        "level",
        help="level identifier, for example 00-0",
    )
    parser.add_argument(
        "--keep-trailing-idle",
        action="store_true",
        help=(
            "keep trailing frames with no Left/Right/Jump input; by default they "
            "are removed so the supplied 00-0 movie ends at its last N input"
        ),
    )
    return parser.parse_args()


def project_root() -> Path:
    return Path(__file__).resolve().parent


def validate_level_id(level_id: str) -> None:
    if not LEVEL_ID_RE.fullmatch(level_id):
        raise ConversionError(
            f"invalid level identifier {level_id!r}; expected a value such as '00-0'"
        )


def read_libtas_inputs(ltm_path: Path) -> list[str]:
    """Return lines from the top-level `inputs` member of a libTAS movie."""
    try:
        with tarfile.open(ltm_path, mode="r:gz") as archive:
            candidates = [
                member
                for member in archive.getmembers()
                if member.isfile() and Path(member.name).name == "inputs"
            ]
            if not candidates:
                raise ConversionError(f"{ltm_path} does not contain an 'inputs' file")

            # Prefer the archive-root member ('inputs' or './inputs').  This avoids
            # accidentally accepting an unrelated nested file if one ever appears.
            root_candidates = [
                member
                for member in candidates
                if member.name.lstrip("./") == "inputs"
            ]
            if len(root_candidates) != 1:
                names = ", ".join(member.name for member in candidates)
                raise ConversionError(
                    f"could not identify one top-level 'inputs' member in {ltm_path}; "
                    f"found: {names}"
                )

            extracted = archive.extractfile(root_candidates[0])
            if extracted is None:
                raise ConversionError(f"could not read 'inputs' from {ltm_path}")
            raw = extracted.read()
    except (tarfile.TarError, OSError) as exc:
        raise ConversionError(f"could not read libTAS movie {ltm_path}: {exc}") from exc

    # libTAS input files are ASCII in practice. UTF-8 is deliberately strict here
    # so a damaged/unexpected movie fails visibly rather than being silently altered.
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConversionError(f"'inputs' in {ltm_path} is not valid UTF-8") from exc

    return text.splitlines()


def keyboard_keys(line: str) -> set[str]:
    """Return the lower-case keysyms in a libTAS frame's K field."""
    match = KEYBOARD_FIELD_RE.search(line)
    if match is None:
        return set()

    field = match.group(1)
    if not field:
        return set()
    return {key.lower() for key in field.split(":") if key}


def replay_frames_from_libtas(
    input_lines: list[str], *, keep_trailing_idle: bool
) -> list[InputFrame]:
    """Convert libTAS frames after the first Space frame into N input frames."""
    start_index: int | None = None
    for index, line in enumerate(input_lines):
        if KEY_SPACE in keyboard_keys(line):
            start_index = index + 1
            break

    if start_index is None:
        raise ConversionError("no Space press (K20) was found in the libTAS inputs")
    if start_index >= len(input_lines):
        raise ConversionError("the libTAS inputs end immediately after the first Space press")

    frames: list[InputFrame] = []
    previous_jump = False
    for line in input_lines[start_index:]:
        keys = keyboard_keys(line)
        jump = KEY_JUMP in keys
        frames.append(
            InputFrame(
                left=KEY_LEFT in keys,
                right=KEY_RIGHT in keys,
                jump=jump,
                jump_trigger=jump and not previous_jump,
            )
        )
        previous_jump = jump

    if not keep_trailing_idle:
        while frames and frames[-1].is_idle:
            frames.pop()

    if not frames:
        raise ConversionError("no N replay frames remain after the first Space press")

    return frames


def encode_complex_replay(frames: list[InputFrame]) -> str:
    """Encode frames in the N v1.4 seven-nibbles-per-decimal-word format."""
    words: list[int] = []

    for base in range(0, len(frames), 7):
        word = 0
        for offset, frame in enumerate(frames[base : base + 7]):
            nibble = (
                int(frame.left)
                | (int(frame.right) << 1)
                | (int(frame.jump) << 2)
                | (int(frame.jump_trigger) << 3)
            )
            word |= nibble << (4 * offset)
        words.append(word)

    return f"{len(frames)}:" + "|".join(str(word) for word in words)


def validate_replay_encoding(replay: str, expected_frames: list[InputFrame]) -> None:
    """Round-trip the generated replay as a guard against packing mistakes."""
    try:
        tick_text, packed_text = replay.split(":", 1)
        tick_count = int(tick_text)
        words = [int(word) for word in packed_text.split("|") if word]
    except (ValueError, TypeError) as exc:
        raise ConversionError("internal error: generated replay could not be parsed") from exc

    if tick_count != len(expected_frames):
        raise ConversionError("internal error: generated replay has the wrong tick count")

    required_words = math.ceil(tick_count / 7)
    if len(words) != required_words:
        raise ConversionError("internal error: generated replay has the wrong word count")

    for frame_index, expected in enumerate(expected_frames):
        nibble = (words[frame_index // 7] >> (4 * (frame_index % 7))) & 0xF
        actual = InputFrame(
            left=bool(nibble & 0x1),
            right=bool(nibble & 0x2),
            jump=bool(nibble & 0x4),
            jump_trigger=bool(nibble & 0x8),
        )
        if actual != expected:
            raise ConversionError(
                f"internal error: replay round-trip mismatch at frame {frame_index}"
            )


def find_level_record(levels_path: Path, level_id: str) -> str:
    """Find and validate the single `$<level_id> ...#` line in the level database."""
    try:
        with levels_path.open("r", encoding="utf-8-sig") as handle:
            matches = [
                line.rstrip("\r\n")
                for line in handle
                if line.startswith(f"${level_id} ")
            ]
    except (OSError, UnicodeError) as exc:
        raise ConversionError(f"could not read levels file {levels_path}: {exc}") from exc

    if not matches:
        raise ConversionError(f"level {level_id} was not found in {levels_path}")
    if len(matches) != 1:
        raise ConversionError(
            f"level {level_id} occurs {len(matches)} times in {levels_path}; expected exactly one"
        )

    record = matches[0]
    if not record.endswith("#"):
        raise ConversionError(f"level {level_id} record does not end with '#'")

    # Match the optimiser's useful structural check: the map portion of the level
    # field is 31 * 23 characters and is followed by '|' object data.
    valid_level_fields = []
    for field in record.split("#"):
        if "|" not in field:
            continue
        map_string = field.split("|", 1)[0]
        if len(map_string) == 31 * 23:
            valid_level_fields.append(field)

    if len(valid_level_fields) != 1:
        raise ConversionError(
            f"level {level_id} record does not contain exactly one valid 31x23 level field"
        )

    return record


def build_combined_record(level_record: str, replay: str) -> str:
    # The level database line already ends at the level-data separator '#'.
    # A combined N record is: $name#author##<level>#<replay>#
    combined = level_record + replay + "#"

    # Lightweight final structural validation matching nv14_replay.py's format.
    fields = combined.split("#")
    replay_pattern = re.compile(r"^\d+:")
    found = False
    for index in range(len(fields) - 1):
        level_field = fields[index]
        replay_field = fields[index + 1]
        if "|" not in level_field or not replay_pattern.match(replay_field):
            continue
        if len(level_field.split("|", 1)[0]) == 31 * 23:
            found = True
            break
    if not found:
        raise ConversionError("internal error: combined level/replay record is malformed")

    return combined


def main() -> int:
    args = parse_args()

    try:
        validate_level_id(args.level)
        root = project_root()
        ltm_path = root / LTM_DIRECTORY / f"{args.level}.ltm"
        levels_path = root / LEVELS_RELATIVE_PATH

        if not ltm_path.is_file():
            raise ConversionError(f"libTAS movie not found: {ltm_path}")
        if not levels_path.is_file():
            raise ConversionError(f"levels file not found: {levels_path}")

        input_lines = read_libtas_inputs(ltm_path)
        frames = replay_frames_from_libtas(
            input_lines,
            keep_trailing_idle=args.keep_trailing_idle,
        )
        replay = encode_complex_replay(frames)
        validate_replay_encoding(replay, frames)

        level_record = find_level_record(levels_path, args.level)
        combined = build_combined_record(level_record, replay)
        print(combined)
        return 0

    except ConversionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

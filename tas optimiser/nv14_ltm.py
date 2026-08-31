"""Import and export libTAS ``.ltm`` movies for the n v1.4 optimiser.

An LTM movie is a gzip-compressed tar archive.  The active input log is the
top-level ``inputs`` member; alternate editor branches such as ``inputs1`` are
deliberately left untouched.  N replay frame zero is the libTAS frame
immediately after the first Space press.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from nv14_engine import InputFrame


KEY_SPACE = "20"
KEY_LEFT = "ff51"
KEY_RIGHT = "ff53"
KEY_JUMP = "ffe1"  # Shift_L
N_KEYS = frozenset({KEY_LEFT, KEY_RIGHT, KEY_JUMP})

LEVEL_ID_RE = re.compile(r"^\d{2}-\d+$")
LTM_LEVEL_FILENAME_RE = re.compile(
    r"^(?P<level_id>\d{2}-\d+)(?:[_ .-].+)?$"
)
LEVEL_DATABASE_NAME = "N v1.4 + NReality levels.txt"
METADATA_MEMBER = "nv14_optimizer.json"
METADATA_FORMAT = "nv14-tas-replay-optimizer-ltm"
METADATA_VERSION = 1
MAX_LTM_INTEGER = (1 << 63) - 1


class LtmError(ValueError):
    """A user-facing LTM import/export error."""


def _normalised_root_name(name: str) -> str:
    while name.startswith("./"):
        name = name[2:]
    return name


def _root_members(
    members: Sequence[tarfile.TarInfo], name: str
) -> list[tarfile.TarInfo]:
    return [
        member
        for member in members
        if _normalised_root_name(member.name) == name
    ]


def _root_regular_members(
    members: Sequence[tarfile.TarInfo], name: str
) -> list[tarfile.TarInfo]:
    return [member for member in _root_members(members, name) if member.isfile()]


def _one_root_member(
    members: Sequence[tarfile.TarInfo], name: str, *, required: bool
) -> tarfile.TarInfo | None:
    candidates = _root_members(members, name)
    if len(candidates) == 1 and candidates[0].isfile():
        return candidates[0]
    if not candidates and not required:
        return None
    if not candidates:
        raise LtmError(f"LTM movie does not contain a top-level {name!r} member")
    if len(candidates) == 1:
        raise LtmError(f"top-level LTM member {name!r} is not a regular file")
    found = ", ".join(member.name for member in candidates)
    raise LtmError(
        f"LTM movie contains more than one top-level {name!r} member: {found}"
    )


def _read_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    extracted = archive.extractfile(member)
    if extracted is None:
        raise LtmError(f"could not read LTM member {member.name!r}")
    return extracted.read()


def _split_input_lines(
    text: str,
) -> tuple[list[str], list[str], str, bool, str]:
    chunks = text.splitlines(keepends=True)
    contents: list[str] = []
    endings: list[str] = []
    for chunk in chunks:
        if chunk.endswith("\r\n"):
            contents.append(chunk[:-2])
            endings.append("\r\n")
        elif chunk.endswith("\n") or chunk.endswith("\r"):
            contents.append(chunk[:-1])
            endings.append(chunk[-1:])
        else:
            contents.append(chunk)
            endings.append("")

    trailing_chunks: list[str] = []
    while contents and not contents[-1].strip():
        trailing_chunks.append(contents.pop() + endings.pop())
    trailing_whitespace = "".join(reversed(trailing_chunks))

    nonempty_endings = [ending for ending in endings if ending]
    if nonempty_endings:
        counts = Counter(nonempty_endings)
        dominant = max(
            counts,
            key=lambda ending: (counts[ending], -nonempty_endings.index(ending)),
        )
    else:
        dominant = "\n"
    ended_with_newline = text.endswith(("\r", "\n"))
    return (
        contents,
        endings,
        dominant,
        ended_with_newline,
        trailing_whitespace,
    )


def _join_input_lines(contents: Sequence[str], endings: Sequence[str]) -> str:
    if len(contents) != len(endings):
        raise LtmError("internal error: LTM input line/end-of-line counts differ")
    return "".join(content + ending for content, ending in zip(contents, endings))


def _keyboard_segments(line: str) -> tuple[list[str], list[int]]:
    segments = line.split("|")
    indices = [
        index
        for index, segment in enumerate(segments)
        if segment.startswith("K")
    ]
    if len(indices) > 1:
        raise LtmError("an LTM input frame contains more than one keyboard field")
    return segments, indices


def keyboard_keys(line: str) -> set[str]:
    """Return lower-case keysyms from one libTAS input line."""
    segments, indices = _keyboard_segments(line)
    if not indices:
        return set()
    field = segments[indices[0]][1:]
    return {key.lower() for key in field.split(":") if key}


def _replace_n_controls(line: str, frame: InputFrame) -> str:
    """Replace only Left/Right/Shift_L while retaining every other input."""
    segments, indices = _keyboard_segments(line)
    existing: list[str] = []
    existing_n_keys: set[str] = set()
    keyboard_index: int | None = indices[0] if indices else None
    if keyboard_index is not None:
        raw_keys = [
            key for key in segments[keyboard_index][1:].split(":") if key
        ]
        existing_n_keys = {
            key.lower() for key in raw_keys if key.lower() in N_KEYS
        }
        existing = [
            key
            for key in raw_keys
            if key and key.lower() not in N_KEYS
        ]

    desired_n_keys = {
        key
        for key, enabled in (
            (KEY_JUMP, frame.jump),
            (KEY_LEFT, frame.left),
            (KEY_RIGHT, frame.right),
        )
        if enabled
    }
    if existing_n_keys == desired_n_keys:
        return line

    # Match the input-name order in the supplied N libTAS movies.  libTAS
    # treats the field as a set, but a stable order makes output reproducible.
    replacement = existing.copy()
    if frame.jump:
        replacement.append(KEY_JUMP)
    if frame.left:
        replacement.append(KEY_LEFT)
    if frame.right:
        replacement.append(KEY_RIGHT)

    if keyboard_index is not None:
        if replacement:
            segments[keyboard_index] = "K" + ":".join(replacement)
        else:
            del segments[keyboard_index]
        return "|".join(segments)

    if not replacement:
        return line
    keyboard = "K" + ":".join(replacement)
    if "|" not in line:
        return f"|{keyboard}|" if not line else f"{line}|{keyboard}|"
    insert_at = len(segments) - 1 if segments[-1] == "" else len(segments)
    segments.insert(insert_at, keyboard)
    return "|".join(segments)


def _contains_only_n_controls(line: str) -> bool:
    """Return whether discarding a frame would discard no unrelated input."""
    for segment in line.split("|"):
        if not segment:
            continue
        if not segment.startswith("K"):
            return False
        keys = [key.lower() for key in segment[1:].split(":") if key]
        if any(key not in N_KEYS for key in keys):
            return False
    return True


def _frames_from_lines(lines: Sequence[str]) -> list[InputFrame]:
    result: list[InputFrame] = []
    previous_jump = False
    for line in lines:
        keys = keyboard_keys(line)
        jump = KEY_JUMP in keys
        result.append(
            InputFrame(
                left=KEY_LEFT in keys,
                right=KEY_RIGHT in keys,
                jump=jump,
                jump_trigger=jump and not previous_jump,
            )
        )
        previous_jump = jump
    return result


def _infer_replay_start(lines: Sequence[str]) -> int:
    for index, line in enumerate(lines):
        if KEY_SPACE in keyboard_keys(line):
            start = index + 1
            if start >= len(lines):
                raise LtmError(
                    "the LTM inputs end immediately after the first Space press"
                )
            return start
    raise LtmError("no Space press (K20) was found in the LTM inputs")


def _inferred_tick_count(lines: Sequence[str], start: int) -> int:
    frames = _frames_from_lines(lines[start:])
    while frames and not (frames[-1].left or frames[-1].right or frames[-1].jump):
        frames.pop()
    return len(frames)


def _parse_metadata(raw: bytes) -> tuple[dict[str, object] | None, str | None]:
    try:
        decoded = raw.decode("utf-8")
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"ignored invalid {METADATA_MEMBER}: {exc}"
    if not isinstance(value, dict):
        return None, f"ignored invalid {METADATA_MEMBER}: root is not an object"
    if (
        value.get("format") != METADATA_FORMAT
        or type(value.get("version")) is not int
        or value.get("version") != METADATA_VERSION
    ):
        return None, f"ignored unrecognised {METADATA_MEMBER}"
    return value, None


def _append_warning(current: str | None, extra: str) -> str:
    return f"{current}; {extra}" if current else extra


@dataclass(frozen=True, slots=True)
class LtmMovie:
    """An active libTAS movie input plus its optimiser replay mapping."""

    path: Path
    archive_bytes: bytes = field(repr=False)
    input_member_name: str
    input_lines: tuple[str, ...]
    input_endings: tuple[str, ...]
    dominant_newline: str
    ended_with_newline: bool
    trailing_input_whitespace: str
    replay_start: int
    replay_frames: tuple[InputFrame, ...]
    inferred_neutral_tail_frames: int = 0
    embedded_level_id: str | None = None
    embedded_level_record: str | None = None
    warning: str | None = None

    @classmethod
    def load(
        cls, path: Path, *, postroll_frames: int | None = None
    ) -> "LtmMovie":
        path = Path(path)
        try:
            archive_raw = path.read_bytes()
            with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:*") as archive:
                members = archive.getmembers()
                input_member = _one_root_member(members, "inputs", required=True)
                assert input_member is not None
                input_raw = _read_member(archive, input_member)
                config_member = _one_root_member(
                    members, "config.ini", required=True
                )
                assert config_member is not None
                config_raw = _read_member(archive, config_member)
                metadata_member = _one_root_member(
                    members, METADATA_MEMBER, required=False
                )
                metadata_raw = (
                    _read_member(archive, metadata_member)
                    if metadata_member is not None
                    else None
                )
        except LtmError:
            raise
        except (OSError, tarfile.TarError) as exc:
            raise LtmError(f"could not read LTM movie {path}: {exc}") from exc

        try:
            input_text = input_raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LtmError(f"top-level 'inputs' in {path} is not valid UTF-8") from exc
        (
            lines,
            endings,
            dominant,
            ended_with_newline,
            trailing_input_whitespace,
        ) = _split_input_lines(input_text)
        if not lines:
            raise LtmError("the top-level LTM 'inputs' member is empty")
        for index, line in enumerate(lines):
            if not line.startswith("|"):
                raise LtmError(
                    f"LTM input frame {index} does not begin with '|'"
                )
            try:
                keyboard_keys(line)
            except LtmError as exc:
                raise LtmError(f"invalid LTM input frame {index}: {exc}") from exc
        _validate_config(config_raw)
        config_text = _decode_config(config_raw)
        default_num = _required_config_value(config_text, "framerate_num")
        default_den = _required_config_value(config_text, "framerate_den")
        for index, line in enumerate(lines):
            try:
                _frame_duration(
                    line,
                    default_num=default_num,
                    default_den=default_den,
                )
            except LtmError as exc:
                raise LtmError(f"invalid LTM input frame {index}: {exc}") from exc
        replay_start = _infer_replay_start(lines)

        metadata: dict[str, object] | None = None
        warning: str | None = None
        if metadata_raw is not None:
            metadata, warning = _parse_metadata(metadata_raw)

        metadata_valid = False
        if metadata is not None:
            expected_hash = metadata.get("inputs_sha256")
            expected_member = metadata.get("inputs_member")
            if (
                isinstance(expected_hash, str)
                and expected_hash == hashlib.sha256(input_raw).hexdigest()
                and isinstance(expected_member, str)
                and _normalised_root_name(expected_member)
                == _normalised_root_name(input_member.name)
            ):
                metadata_valid = True
            else:
                warning = _append_warning(
                    warning,
                    f"ignored stale exact replay mapping in {METADATA_MEMBER}",
                )

        if metadata_valid:
            stored_start = metadata.get("replay_start_frame")
            stored_ticks = metadata.get("replay_tick_count")
            if (
                not isinstance(stored_start, int)
                or isinstance(stored_start, bool)
                or stored_start != replay_start
                or not isinstance(stored_ticks, int)
                or isinstance(stored_ticks, bool)
                or stored_ticks < 1
                or stored_start + stored_ticks > len(lines)
            ):
                metadata_valid = False
                warning = _append_warning(
                    warning,
                    f"ignored inconsistent exact replay mapping in "
                    f"{METADATA_MEMBER}",
                )

        available_ticks = len(lines) - replay_start
        inferred_neutral_tail_frames = 0
        if postroll_frames is not None:
            if (
                not isinstance(postroll_frames, int)
                or isinstance(postroll_frames, bool)
                or postroll_frames < 0
            ):
                raise LtmError("LTM post-roll must be a non-negative integer")
            if postroll_frames >= available_ticks:
                raise LtmError(
                    f"LTM post-roll {postroll_frames} leaves no replay frames "
                    f"after Space (only {available_ticks} frame(s) are available)"
                )
            tick_count = available_ticks - postroll_frames
        elif metadata_valid and metadata is not None:
            tick_count = int(metadata["replay_tick_count"])
        else:
            tick_count = _inferred_tick_count(lines, replay_start)
            inferred_neutral_tail_frames = available_ticks - tick_count
        frames = _frames_from_lines(lines[replay_start : replay_start + tick_count])

        embedded_level_id: str | None = None
        embedded_level_record: str | None = None
        if metadata is not None:
            candidate_id = metadata.get("level_id")
            candidate_record = metadata.get("level_record")
            if isinstance(candidate_id, str) and LEVEL_ID_RE.fullmatch(candidate_id):
                embedded_level_id = candidate_id
            if embedded_level_id is not None and isinstance(candidate_record, str):
                try:
                    validate_level_record(candidate_record, embedded_level_id)
                except LtmError:
                    warning = _append_warning(
                        warning,
                        f"ignored invalid level record in {METADATA_MEMBER}",
                    )
                else:
                    embedded_level_record = candidate_record

        return cls(
            path=path,
            archive_bytes=archive_raw,
            input_member_name=input_member.name,
            input_lines=tuple(lines),
            input_endings=tuple(endings),
            dominant_newline=dominant,
            ended_with_newline=ended_with_newline,
            trailing_input_whitespace=trailing_input_whitespace,
            replay_start=replay_start,
            replay_frames=tuple(frames),
            inferred_neutral_tail_frames=inferred_neutral_tail_frames,
            embedded_level_id=embedded_level_id,
            embedded_level_record=embedded_level_record,
            warning=warning,
        )

    def auto_completion_probe_frames(self) -> tuple[InputFrame, ...]:
        """Return the replay plus raw-LTM tail rows Auto may simulate.

        A raw movie has no exact replay boundary.  The normal importer keeps
        its historical heuristic so Local and jump-pattern do not treat
        recorder padding as editable input.  Auto can safely probe the bounded
        N-neutral tail because it canonicalises a completed route before
        searching.  Explicit ``--ltm-postroll`` and valid optimiser metadata
        remain authoritative and therefore expose no inferred tail here.
        """
        # Keep the final recorded neutral row outside the serialized body so
        # Auto's one implicit sentinel represents that physical LTM frame.  In
        # particular, never let the evaluator's sentinel add a frame beyond
        # the end of the movie.
        probe_body_tail = max(0, self.inferred_neutral_tail_frames - 1)
        return self.replay_frames + (InputFrame(),) * probe_body_tail

    def _edited_inputs(
        self,
        frames: Sequence[InputFrame],
        *,
        promote_inferred_neutral_tail: bool = False,
    ) -> bytes:
        if not frames:
            raise LtmError("cannot write an LTM movie with an empty N replay")
        source_tick_count = len(self.replay_frames)
        if promote_inferred_neutral_tail and len(frames) > source_tick_count:
            source_tick_count += min(
                len(frames) - source_tick_count,
                self.inferred_neutral_tail_frames,
            )
        source_body_end = self.replay_start + source_tick_count
        frame_section_ended_with_newline = bool(
            self.input_endings and self.input_endings[-1]
        )

        prefix_contents = list(self.input_lines[: self.replay_start])
        prefix_endings = list(self.input_endings[: self.replay_start])
        source_body_contents = self.input_lines[
            self.replay_start : source_body_end
        ]
        source_body_endings = self.input_endings[
            self.replay_start : source_body_end
        ]
        suffix_contents = list(self.input_lines[source_body_end:])
        suffix_endings = list(self.input_endings[source_body_end:])

        if len(frames) < source_tick_count:
            for offset, line in enumerate(
                source_body_contents[len(frames) :], start=len(frames)
            ):
                if not _contains_only_n_controls(line):
                    raise LtmError(
                        "cannot shorten this LTM without discarding non-N input "
                        f"data at replay frame {offset}"
                    )

        body_contents: list[str] = []
        body_endings: list[str] = []
        for offset, frame in enumerate(frames):
            template = (
                source_body_contents[offset]
                if offset < len(source_body_contents)
                else "|"
            )
            ending = (
                source_body_endings[offset]
                if offset < len(source_body_endings)
                else self.dominant_newline
            )
            body_contents.append(_replace_n_controls(template, frame))
            body_endings.append(ending)

        # N tests completion on the neutral tick after the serialized replay.
        # Retain the source movie's neutral post-roll (three frames in the
        # supplied recorder output), or create one sentinel when none exists.
        if not suffix_contents:
            suffix_contents.append("|")
            suffix_endings.append(
                self.dominant_newline
                if frame_section_ended_with_newline
                else ""
            )

        contents = prefix_contents + body_contents + suffix_contents
        endings = prefix_endings + body_endings + suffix_endings
        if len(contents) > 1:
            for index in range(len(endings) - 1):
                if endings[index] == "":
                    endings[index] = self.dominant_newline
        if endings:
            endings[-1] = (
                self.dominant_newline
                if frame_section_ended_with_newline
                else ""
            )
        return (
            _join_input_lines(contents, endings)
            + self.trailing_input_whitespace
        ).encode("utf-8")

    def write(
        self,
        output_path: Path,
        frames: Sequence[InputFrame],
        *,
        level_id: str,
        level_record: str,
        promote_inferred_neutral_tail: bool = False,
    ) -> None:
        """Atomically write a movie rebuilt from this source LTM template."""
        if not LEVEL_ID_RE.fullmatch(level_id):
            raise LtmError(f"invalid LTM level identifier {level_id!r}")
        validate_level_record(level_record, level_id)
        output_path = Path(output_path)
        input_raw = self._edited_inputs(
            frames,
            promote_inferred_neutral_tail=promote_inferred_neutral_tail,
        )
        new_input_lines = _split_input_lines(input_raw.decode("utf-8"))[0]
        metadata = {
            "format": METADATA_FORMAT,
            "version": METADATA_VERSION,
            "inputs_member": self.input_member_name,
            "inputs_sha256": hashlib.sha256(input_raw).hexdigest(),
            "replay_start_frame": self.replay_start,
            "replay_tick_count": len(frames),
            "level_id": level_id,
            "level_record": level_record,
        }
        metadata_raw = (
            json.dumps(metadata, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
            + "\n"
        ).encode("utf-8")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            self._write_archive(
                temporary_path,
                input_raw=input_raw,
                metadata_raw=metadata_raw,
                new_input_lines=new_input_lines,
            )
            written = LtmMovie.load(temporary_path)
            expected_held = [
                (bool(frame.left), bool(frame.right), bool(frame.jump))
                for frame in frames
            ]
            actual_held = [
                (frame.left, frame.right, frame.jump)
                for frame in written.replay_frames
            ]
            if (
                written.replay_start != self.replay_start
                or actual_held != expected_held
                or written.embedded_level_id != level_id
                or written.embedded_level_record != level_record
            ):
                raise LtmError("internal error: written LTM failed replay validation")
            # Windows implements os.fsync() with _commit(), which requires a
            # writable file descriptor.  Reopening the completed archive as
            # read-only works on POSIX but fails on Windows before the first
            # LTM checkpoint can replace its destination.
            with temporary_path.open("rb+") as stream:
                os.fsync(stream.fileno())
            _replace_with_windows_retries(temporary_path, output_path)
        except BaseException:
            try:
                temporary_path.unlink()
            except OSError:
                pass
            raise

    def _write_archive(
        self,
        temporary_path: Path,
        *,
        input_raw: bytes,
        metadata_raw: bytes,
        new_input_lines: Sequence[str],
    ) -> None:
        try:
            with tarfile.open(
                fileobj=io.BytesIO(self.archive_bytes), mode="r:*"
            ) as source:
                members = source.getmembers()
                input_member = _one_root_member(members, "inputs", required=True)
                assert input_member is not None
                metadata_member = _one_root_member(
                    members, METADATA_MEMBER, required=False
                )
                config_member = _one_root_member(
                    members, "config.ini", required=True
                )
                assert config_member is not None

                metadata_written = False
                with tarfile.open(
                    temporary_path,
                    mode="w:gz",
                    format=tarfile.PAX_FORMAT,
                    pax_headers=source.pax_headers,
                ) as destination:
                    for member in members:
                        cloned = copy.copy(member)
                        if member.isfile():
                            replacement: bytes | None = None
                            if member.name == input_member.name:
                                replacement = input_raw
                            elif (
                                metadata_member is not None
                                and member.name == metadata_member.name
                            ):
                                replacement = metadata_raw
                                metadata_written = True
                            elif member.name == config_member.name:
                                replacement = _update_config_frame_count(
                                    _read_member(source, member),
                                    new_input_lines=new_input_lines,
                                )
                            if replacement is not None:
                                cloned.size = len(replacement)
                                destination.addfile(
                                    cloned, io.BytesIO(replacement)
                                )
                            else:
                                extracted = source.extractfile(member)
                                if extracted is None:
                                    raise LtmError(
                                        f"could not read LTM member {member.name!r}"
                                    )
                                destination.addfile(cloned, extracted)
                        else:
                            destination.addfile(cloned)

                    if not metadata_written:
                        metadata_info = tarfile.TarInfo(METADATA_MEMBER)
                        metadata_info.size = len(metadata_raw)
                        metadata_info.mode = input_member.mode
                        metadata_info.uid = input_member.uid
                        metadata_info.gid = input_member.gid
                        metadata_info.uname = input_member.uname
                        metadata_info.gname = input_member.gname
                        metadata_info.mtime = input_member.mtime
                        destination.addfile(metadata_info, io.BytesIO(metadata_raw))
        except LtmError:
            raise
        except (OSError, tarfile.TarError) as exc:
            raise LtmError(f"could not write LTM movie {temporary_path}: {exc}") from exc


def _replace_with_windows_retries(source: Path, destination: Path) -> None:
    retry_delays = (0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.0)
    for retry_delay in (*retry_delays, None):
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            retryable_windows_error = getattr(exc, "winerror", None) in {
                5,
                32,
                33,
            }
            if not retryable_windows_error or retry_delay is None:
                raise
            time.sleep(retry_delay)


def _config_value(text: str, key: str) -> int | None:
    matches = re.findall(rf"(?m)^{re.escape(key)}=(\d+)\r?$", text)
    if len(matches) != 1:
        return None
    try:
        value = int(matches[0])
    except ValueError as exc:
        raise LtmError(f"top-level 'config.ini' {key} is too large") from exc
    if value > MAX_LTM_INTEGER:
        raise LtmError(f"top-level 'config.ini' {key} is too large")
    return value


def _decode_config(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LtmError("top-level 'config.ini' is not valid UTF-8") from exc


def _required_config_value(text: str, key: str) -> int:
    value = _config_value(text, key)
    if value is None:
        raise LtmError(
            f"top-level 'config.ini' must contain one numeric {key} value"
        )
    return value


def _validate_config(raw: bytes) -> None:
    text = _decode_config(raw)
    for key in (
        "frame_count",
        "framerate_num",
        "framerate_den",
        "length_sec",
        "length_nsec",
    ):
        _required_config_value(text, key)
    if _required_config_value(text, "frame_count") < 1:
        raise LtmError("top-level 'config.ini' frame_count must be positive")
    if _required_config_value(text, "framerate_num") < 1:
        raise LtmError("top-level 'config.ini' framerate_num must be positive")
    if _required_config_value(text, "framerate_den") < 1:
        raise LtmError("top-level 'config.ini' framerate_den must be positive")
    if _required_config_value(text, "length_nsec") >= 1_000_000_000:
        raise LtmError(
            "top-level 'config.ini' length_nsec must be below 1000000000"
        )


def _replace_config_value(text: str, key: str, value: int) -> tuple[str, bool]:
    pattern = re.compile(rf"(?m)^({re.escape(key)}=)\d+(\r?)$")
    result, count = pattern.subn(rf"\g<1>{value}\g<2>", text, count=1)
    return result, count == 1


def _frame_duration(
    line: str, *, default_num: int, default_den: int
) -> Fraction:
    timing_fields = [segment for segment in line.split("|") if segment.startswith("T")]
    if not timing_fields:
        return Fraction(default_den, default_num)
    if len(timing_fields) != 1:
        raise LtmError("an LTM input frame contains more than one timing field")
    match = re.fullmatch(r"T(\d+):(\d+)", timing_fields[0])
    if match is None:
        raise LtmError(f"invalid LTM timing field {timing_fields[0]!r}")
    try:
        numerator, denominator = (int(value) for value in match.groups())
    except ValueError as exc:
        raise LtmError(f"LTM timing field {timing_fields[0]!r} is too large") from exc
    if numerator > MAX_LTM_INTEGER or denominator > MAX_LTM_INTEGER:
        raise LtmError(f"LTM timing field {timing_fields[0]!r} is too large")
    if numerator < 1 or denominator < 1:
        raise LtmError("LTM timing-field values must be positive")
    return Fraction(denominator, numerator)


def _update_config_frame_count(
    raw: bytes, *, new_input_lines: Sequence[str]
) -> bytes:
    text = _decode_config(raw)
    _validate_config(raw)
    old_frame_count = _required_config_value(text, "frame_count")
    new_frame_count = len(new_input_lines)

    text, replaced = _replace_config_value(text, "frame_count", new_frame_count)
    if not replaced:
        raise LtmError("top-level 'config.ini' has no numeric frame_count")

    savestate_count = _config_value(text, "savestate_frame_count")
    if savestate_count == old_frame_count:
        text, _ = _replace_config_value(
            text, "savestate_frame_count", new_frame_count
        )

    framerate_num = _required_config_value(text, "framerate_num")
    framerate_den = _required_config_value(text, "framerate_den")
    duration = sum(
        (
            _frame_duration(
                line,
                default_num=framerate_num,
                default_den=framerate_den,
            )
            for line in new_input_lines
        ),
        Fraction(),
    )
    seconds = duration.numerator // duration.denominator
    remainder = duration - seconds
    nanoseconds = (
        remainder.numerator * 1_000_000_000 + remainder.denominator // 2
    ) // remainder.denominator
    if nanoseconds >= 1_000_000_000:
        seconds += 1
        nanoseconds -= 1_000_000_000
    text, replaced_sec = _replace_config_value(text, "length_sec", seconds)
    text, replaced_nsec = _replace_config_value(text, "length_nsec", nanoseconds)
    if not replaced_sec or not replaced_nsec:
        raise LtmError("top-level 'config.ini' has invalid length metadata")
    return text.encode("utf-8")


def validate_level_id(level_id: str) -> None:
    if not LEVEL_ID_RE.fullmatch(level_id):
        raise LtmError(
            f"invalid level identifier {level_id!r}; expected a value such as '00-0'"
        )


def infer_level_id_from_ltm_filename(path: Path) -> str | None:
    """Infer a leading level id from an exact or labelled LTM filename."""
    path = Path(path)
    if path.suffix.lower() != ".ltm":
        return None
    match = LTM_LEVEL_FILENAME_RE.fullmatch(path.stem)
    return None if match is None else match.group("level_id")


def validate_level_record(record: str, level_id: str | None = None) -> None:
    stripped = record.rstrip("\r\n")
    if not stripped.endswith("#"):
        raise LtmError("level database record does not end with '#'")
    if level_id is not None and not stripped.startswith(f"${level_id} "):
        raise LtmError(
            f"level database record does not describe requested level {level_id}"
        )
    fields = stripped.split("#")
    valid_indices = []
    for index, field in enumerate(fields):
        if "|" not in field:
            continue
        if len(field.split("|", 1)[0]) == 31 * 23:
            valid_indices.append(index)
    if len(valid_indices) != 1:
        raise LtmError(
            "level database record does not contain exactly one valid 31x23 level field"
        )
    if fields[-1] != "" or valid_indices[0] != len(fields) - 2:
        raise LtmError(
            "level database record must end immediately after its level field"
        )


def find_level_record(levels_path: Path, level_id: str) -> str:
    """Return the one ``$<level_id> ...#`` record from a level database."""
    validate_level_id(level_id)
    try:
        with Path(levels_path).open("r", encoding="utf-8-sig") as stream:
            matches = [
                line.rstrip("\r\n")
                for line in stream
                if line.startswith(f"${level_id} ")
            ]
    except (OSError, UnicodeError) as exc:
        raise LtmError(f"could not read levels file {levels_path}: {exc}") from exc
    if not matches:
        raise LtmError(f"level {level_id} was not found in {levels_path}")
    if len(matches) != 1:
        raise LtmError(
            f"level {level_id} occurs {len(matches)} times in {levels_path}; "
            "expected exactly one"
        )
    validate_level_record(matches[0], level_id)
    return matches[0]


def discover_levels_file(
    input_path: Path,
    explicit_path: Path | None,
    *,
    program_root: Path,
) -> Path:
    """Resolve the level database used for a raw, non-self-contained LTM."""
    if explicit_path is not None:
        candidate = Path(explicit_path)
        if not candidate.is_file():
            raise LtmError(f"levels file not found: {candidate}")
        return candidate

    input_path = Path(input_path)
    candidates = [
        Path.cwd() / "external" / LEVEL_DATABASE_NAME,
        Path.cwd().parent / "external" / LEVEL_DATABASE_NAME,
        Path(program_root) / "external" / LEVEL_DATABASE_NAME,
        input_path.parent / LEVEL_DATABASE_NAME,
        input_path.parent / "external" / LEVEL_DATABASE_NAME,
    ]
    if input_path.parent.name == "n_levels" and input_path.parent.parent.name == "volume":
        candidates.insert(
            0,
            input_path.parent.parent.parent / "external" / LEVEL_DATABASE_NAME,
        )

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved not in seen:
            seen.add(resolved)
            unique.append(candidate)
    for candidate in unique:
        if candidate.is_file():
            return candidate
    checked = ", ".join(str(path) for path in unique)
    raise LtmError(
        "could not find the N level database required by this LTM; pass "
        f"--levels-file FILE (searched: {checked})"
    )

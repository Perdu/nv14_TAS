"""Parsing, encoding and replay helpers for n v1.4 complex demos.

The uncompressed/"complex" demo format is:

    <tick-count>:<word>|<word>|...

Each decimal word contains seven 4-bit input frames in low-nibble-first order:
bit 0 = left, bit 1 = right, bit 2 = jump held, bit 3 = jump trigger.
"""
from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from nv14_engine import InputFrame, Level, SimulationState


@dataclass(slots=True)
class ComplexReplay:
    frames: list[InputFrame]

    @property
    def tick_count(self) -> int:
        return len(self.frames)

    def canonical_frames(self) -> list[InputFrame]:
        """Return frames whose jump triggers are derived from jump-held edges."""
        result: list[InputFrame] = []
        previous_jump = False
        for frame in self.frames:
            trigger = frame.jump and not previous_jump
            result.append(InputFrame(frame.left, frame.right, frame.jump, trigger))
            previous_jump = frame.jump
        return result


@dataclass(slots=True)
class CombinedLevelReplay:
    """A `$name#author##level#replay#`-style custom-level record."""

    fields: list[str]
    level_index: int
    replay_index: int

    @property
    def level_string(self) -> str:
        return self.fields[self.level_index]

    @property
    def replay_string(self) -> str:
        return self.fields[self.replay_index]

    @property
    def name(self) -> str:
        if not self.fields:
            return ""
        return self.fields[0][1:] if self.fields[0].startswith("$") else self.fields[0]

    @property
    def author(self) -> str:
        return self.fields[1] if len(self.fields) > 1 else ""

    def replace_replay(self, replay_string: str) -> CombinedLevelReplay:
        fields = self.fields.copy()
        fields[self.replay_index] = replay_string
        return CombinedLevelReplay(fields, self.level_index, self.replay_index)

    def dump(self) -> str:
        return "#".join(self.fields)


def parse_combined_level_replay(text: str) -> CombinedLevelReplay:
    stripped = text.strip()
    fields = stripped.split("#")
    demo_pattern = re.compile(r"^\d+:")
    for index in range(len(fields) - 1):
        candidate_level = fields[index]
        candidate_replay = fields[index + 1]
        if "|" not in candidate_level or not demo_pattern.match(candidate_replay):
            continue
        map_string = candidate_level.split("|", 1)[0]
        if len(map_string) == 31 * 23:
            return CombinedLevelReplay(fields, index, index + 1)
    raise ValueError(
        "could not locate adjacent level and complex replay fields in the input"
    )


def decode_complex_replay(demo_string: str) -> ComplexReplay:
    try:
        tick_text, words_text = demo_string.strip().split(":", 1)
    except ValueError as exc:
        raise ValueError("complex replay must contain '<ticks>:<packed words>'") from exc
    tick_count = int(tick_text)
    words = [int(word) for word in words_text.split("|") if word != ""]
    required_words = math.ceil(tick_count / 7)
    if len(words) < required_words:
        raise ValueError(
            f"replay declares {tick_count} ticks but has only {len(words)} packed words; "
            f"at least {required_words} are required"
        )

    frames: list[InputFrame] = []
    for frame_index in range(tick_count):
        word = words[frame_index // 7]
        nibble = (word >> (4 * (frame_index % 7))) & 0xF
        frames.append(
            InputFrame(
                left=bool(nibble & 0x1),
                right=bool(nibble & 0x2),
                jump=bool(nibble & 0x4),
                jump_trigger=bool(nibble & 0x8),
            )
        )
    return ComplexReplay(frames)


def encode_complex_replay(
    replay: ComplexReplay | Sequence[InputFrame],
    *,
    canonicalise_jump_triggers: bool = True,
) -> str:
    frames = list(replay.frames if isinstance(replay, ComplexReplay) else replay)
    if canonicalise_jump_triggers:
        frames = ComplexReplay(frames).canonical_frames()

    words: list[int] = []
    for base in range(0, len(frames), 7):
        word = 0
        for offset, frame in enumerate(frames[base : base + 7]):
            nibble = (
                int(frame.left)
                | (int(frame.right) << 1)
                | (int(frame.jump) << 2)
                | (int(bool(frame.jump_trigger)) << 3)
            )
            word |= nibble << (4 * offset)
        words.append(word)
    return f"{len(frames)}:" + "|".join(str(word) for word in words)


def editable_frames(frames: Sequence[InputFrame]) -> list[InputFrame]:
    """Drop stored trigger bits so simulation derives them after mutations."""
    # ``InputFrame`` is immutable, so an already-normalised frame can be
    # shared safely.  Auto and local search pass normalised replays through
    # this helper very frequently; rebuilding every frame used to turn a
    # one-boundary mutation into an O(replay length) allocation pass even
    # before the actual edit was applied.
    return [
        frame
        if frame.jump_trigger is None
        else InputFrame(frame.left, frame.right, frame.jump, None)
        for frame in frames
    ]


def simulate_through_frame(
    level: Level,
    frames: Sequence[InputFrame],
    target_frame: int,
    *,
    start_state: SimulationState | None = None,
) -> SimulationState:
    """Apply frames 0..target_frame inclusive and return the resulting state.

    This convention matches the tracing convention in the supplied example:
    target frame 71 produces the position printed as the start of traced frame 71.
    In conventional zero-based state indexing, it is the state after 72 input ticks.
    """
    if target_frame < -1:
        raise ValueError("target_frame must be -1 or greater")
    if target_frame >= len(frames):
        raise ValueError(
            f"target frame {target_frame} is outside a {len(frames)}-frame replay"
        )
    state = level.initial_state() if start_state is None else start_state.clone()
    for frame_index in range(target_frame + 1):
        state.step(frames[frame_index], level.tiles)
        if state.player.dead:
            break
    return state


def input_symbol(frame: InputFrame) -> str:
    horizontal = "B" if frame.left and frame.right else "L" if frame.left else "R" if frame.right else "."
    return horizontal + ("J" if frame.jump else ".")


def changed_frame_indices(
    original: Sequence[InputFrame], modified: Sequence[InputFrame]
) -> list[int]:
    """Return held-input differences, including a shortened/extended tail.

    Earlier optimiser modes preserve the replay length, but autonomous mode can
    remove ticks after proving an earlier exit.  Treat every index present in
    only one sequence as changed instead of requiring equal lengths.
    """
    changed: list[int] = []
    for index, (a, b) in enumerate(zip(original, modified)):
        if (a.left, a.right, a.jump) != (b.left, b.right, b.jump):
            changed.append(index)
    changed.extend(range(min(len(original), len(modified)), max(len(original), len(modified))))
    return changed

@dataclass(frozen=True, slots=True)
class RetimeMutation:
    """Shift one input-transition suffix by a small signed frame offset."""

    suffix_start: int
    delta: int

    def __post_init__(self) -> None:
        if self.suffix_start < 0:
            raise ValueError("retime suffix start must be non-negative")
        if self.delta == 0 or abs(self.delta) > 3:
            raise ValueError("retime delta must be one of -3,-2,-1,+1,+2,+3")


def input_transition_frames(frames: Sequence[InputFrame]) -> tuple[int, ...]:
    """Frames where the held input state changes from the preceding frame.

    Frame zero is compared with the implicit pre-replay neutral input state, so
    it is returned only when the replay begins with a non-neutral held input.
    Jump-trigger bits are deliberately ignored; they are regenerated from held
    jump edges when the replay is encoded.
    """
    result: list[int] = []
    previous = (False, False, False)
    for index, frame in enumerate(frames):
        current = (frame.left, frame.right, frame.jump)
        if current != previous:
            result.append(index)
            previous = current
    return tuple(result)


def apply_suffix_retime(
    frames: Sequence[InputFrame], mutation: RetimeMutation
) -> list[InputFrame]:
    """Apply a fixed-length transition-suffix retime.

    Every input-state transition at ``suffix_start`` or later is shifted by the
    same signed delta. The replay tick count remains unchanged. Therefore an
    earlier retime extends the final held state, while a later retime extends
    the state immediately preceding the suffix. Mutations that would collide
    with/overtake the preceding transition, move before frame zero, or shift a
    transition beyond the final replay frame are rejected rather than clamped.
    """
    source = editable_frames(frames)
    transitions = input_transition_frames(source)
    if mutation.suffix_start not in transitions:
        raise ValueError(
            f"retime suffix start {mutation.suffix_start} is not an input-transition frame"
        )
    split = transitions.index(mutation.suffix_start)
    shifted = tuple(frame + mutation.delta for frame in transitions[split:])
    if shifted[0] < 0:
        raise ValueError("retime would move the first shifted transition before frame 0")
    if split > 0 and shifted[0] <= transitions[split - 1]:
        raise ValueError(
            "retime would collide with or overtake the preceding input transition"
        )
    if shifted[-1] >= len(source):
        raise ValueError(
            "retime would move a downstream input transition beyond the replay end"
        )

    # All transitions in the suffix move by the same amount.  The resulting
    # held-input stream is therefore a pair of slices plus one repeated edge
    # state; rebuilding it frame-by-frame and walking an event list is
    # unnecessary.  Source frames are immutable and normalised above, so the
    # slices may share their InputFrame instances safely.
    delta = mutation.delta
    if delta > 0:
        prior = source[mutation.suffix_start - 1] if mutation.suffix_start else InputFrame()
        return (
            source[: mutation.suffix_start]
            + [prior] * delta
            + source[mutation.suffix_start : len(source) - delta]
        )

    advance = -delta
    return (
        source[: mutation.suffix_start - advance]
        + source[mutation.suffix_start :]
        + [source[-1]] * advance
    )


def apply_single_transition_retime(
    frames: Sequence[InputFrame], mutation: RetimeMutation
) -> list[InputFrame]:
    """Move one held-input boundary without shifting later transitions.

    This is the local counterpart to :func:`apply_suffix_retime`.  Only the
    two runs adjacent to ``suffix_start`` change length, which directly
    represents the short neutral/opposite-direction regions common in improved
    TASes.  The replay length and every later transition remain unchanged.
    """
    source = editable_frames(frames)
    transitions = input_transition_frames(source)
    if mutation.suffix_start not in transitions:
        raise ValueError(
            f"transition start {mutation.suffix_start} is not an input-transition frame"
        )
    transition_index = transitions.index(mutation.suffix_start)
    old_start = mutation.suffix_start
    new_start = old_start + mutation.delta
    previous_start = transitions[transition_index - 1] if transition_index else -1
    next_start = (
        transitions[transition_index + 1]
        if transition_index + 1 < len(transitions)
        else len(source)
    )
    if new_start <= previous_start:
        raise ValueError(
            "single-transition retime would collide with the preceding transition"
        )
    if new_start >= next_start:
        raise ValueError(
            "single-transition retime would collide with the following transition"
        )
    if new_start < 0 or new_start >= len(source):
        raise ValueError("single-transition retime would leave the replay")

    following_frame = source[old_start]
    # ``source`` is already normalised and InputFrame is immutable.
    result = source.copy()
    if new_start < old_start:
        replacement = following_frame
        for frame_index in range(new_start, old_start):
            result[frame_index] = replacement
    else:
        replacement = source[old_start - 1] if old_start else InputFrame()
        for frame_index in range(old_start, new_start):
            result[frame_index] = replacement
    return result


def valid_retime_mutations(
    frames: Sequence[InputFrame], *, max_retime: int = 3
) -> tuple[RetimeMutation, ...]:
    """Enumerate structurally valid suffix-retime mutations for future search."""
    if max_retime < 1 or max_retime > 3:
        raise ValueError("max_retime must be between 1 and 3")
    transitions = input_transition_frames(frames)
    if not transitions:
        return ()
    replay_length = len(frames)
    final_transition = transitions[-1]
    result: list[RetimeMutation] = []
    for transition_index, start in enumerate(transitions):
        previous = transitions[transition_index - 1] if transition_index else -1
        for magnitude in range(1, max_retime + 1):
            for delta in (-magnitude, magnitude):
                mutation = RetimeMutation(start, delta)
                shifted_start = start + delta
                if shifted_start < 0 or shifted_start <= previous:
                    continue
                if final_transition + delta >= replay_length:
                    continue
                result.append(mutation)
    return tuple(result)

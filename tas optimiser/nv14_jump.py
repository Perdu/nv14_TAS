"""Jump-pulse utilities and exhaustive jump-pattern search."""
from __future__ import annotations

import heapq
import math
import multiprocessing
import os
import random
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from nv14_engine import InputFrame, Level, SimulationState, UnsupportedTileCollision
from nv14_objectives import (
    AxisWindow,
    Evaluation,
    TargetSelection,
    objective_function,
    position_within_windows,
    state_before_frame,
)
from nv14_replay import editable_frames


@dataclass(frozen=True, slots=True)
class JumpPulse:
    """One contiguous run of held jump input, inclusive of ``start_frame``."""

    start_frame: int
    hold_length: int

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.hold_length - 1

    def __str__(self) -> str:
        return f"{self.start_frame}+{self.hold_length}"


@dataclass(frozen=True, slots=True)
class ImmutableJumpSpec:
    """Per-property immutability for a source replay jump pulse."""

    start_frame: int
    immutable_start: bool = True
    immutable_length: bool = True

    @property
    def mode(self) -> str:
        if self.immutable_start and self.immutable_length:
            return "both"
        if self.immutable_start:
            return "start"
        if self.immutable_length:
            return "length"
        raise ValueError("immutable jump spec must freeze at least one property")


@dataclass(slots=True)
class JumpSearchResult:
    pulses: tuple[JumpPulse, ...]
    evaluation: Evaluation

    @property
    def score(self) -> float:
        return self.evaluation.score


def _jump_only_frame(frame: InputFrame, jump: bool) -> InputFrame:
    """Preserve horizontal input while replacing only the jump-held bit."""
    return InputFrame(frame.left, frame.right, jump, None)


def apply_jump_pattern(
    original_frames: Sequence[InputFrame],
    *,
    range_start: int,
    range_end: int,
    pulses: Sequence[JumpPulse],
) -> list[InputFrame]:
    """Return editable frames with jump input in the range replaced by pulses."""
    frames = editable_frames(original_frames)
    for frame_index in range(range_start, range_end + 1):
        frames[frame_index] = _jump_only_frame(frames[frame_index], False)
    for pulse in pulses:
        if pulse.start_frame < range_start or pulse.end_frame > range_end:
            raise ValueError("jump pulse lies outside the mutable range")
        for frame_index in range(pulse.start_frame, pulse.end_frame + 1):
            frames[frame_index] = _jump_only_frame(frames[frame_index], True)
    return frames


def jump_input_pulses(frames: Sequence[InputFrame]) -> tuple[JumpPulse, ...]:
    """Return contiguous held-jump pulses from an input replay."""
    pulses: list[JumpPulse] = []
    start: int | None = None
    for frame_index, frame in enumerate(frames):
        if frame.jump and start is None:
            start = frame_index
        elif not frame.jump and start is not None:
            pulses.append(JumpPulse(start, frame_index - start))
            start = None
    if start is not None:
        pulses.append(JumpPulse(start, len(frames) - start))
    return tuple(pulses)


def validate_immutable_jumps(
    original_frames: Sequence[InputFrame],
    *,
    range_start: int,
    range_end: int,
    immutable_jumps: Sequence[ImmutableJumpSpec],
    source_pulses: Sequence[JumpPulse] | None = None,
) -> dict[int, ImmutableJumpSpec]:
    """Validate per-property immutable source jump specs within a range."""
    specs = tuple(immutable_jumps)
    frames = [spec.start_frame for spec in specs]
    if len(set(frames)) != len(frames):
        raise ValueError("immutable jump frames must not contain duplicates")
    for spec in specs:
        if not spec.immutable_start and not spec.immutable_length:
            raise ValueError("immutable jump spec must freeze at least one property")

    outside = [
        frame for frame in frames
        if frame < range_start or frame > range_end
    ]
    if outside:
        frame_text = ", ".join(map(str, outside))
        raise ValueError(
            "immutable jump frame(s) must lie within --range: " + frame_text
        )

    if not specs:
        return {}
    if source_pulses is None:
        source_pulses = jump_input_pulses(original_frames)
    source_starts = {pulse.start_frame for pulse in source_pulses}
    invalid = [frame for frame in frames if frame not in source_starts]
    if invalid:
        frame_text = ", ".join(map(str, invalid))
        raise ValueError(
            "immutable jump frame(s) are not jump starts in the source replay: "
            + frame_text
        )
    return {spec.start_frame: spec for spec in specs}


_JUMP_MUTATION_FAST_ATTEMPTS = 8
_JUMP_MUTATION_OPTION_CAP = 4096


def _jump_pulse_options(
    source: JumpPulse,
    *,
    range_start: int,
    range_end: int,
    start_mutation: int,
    length_mutation: int,
    immutable: ImmutableJumpSpec | None,
    desired_start_offset: int,
    desired_length_offset: int,
) -> list[tuple[JumpPulse, int]] | None:
    """Return bounded candidate values ordered by distance from one draw.

    The option count is capped because very large user mutation ranges are
    better served by the caller's source-pattern fallback than by expanding a
    Cartesian product which would itself become a new performance cliff.
    """
    if immutable is not None and immutable.immutable_start:
        start_min = start_max = source.start_frame
        desired_start_offset = 0
    else:
        start_min = max(range_start, source.start_frame - start_mutation)
        start_max = min(range_end, source.start_frame + start_mutation)

    if immutable is not None and immutable.immutable_length:
        length_min = length_max = source.hold_length
        desired_length_offset = 0
    else:
        length_min = max(1, source.hold_length - length_mutation)
        length_max = source.hold_length + length_mutation

    if start_min > start_max or length_min > length_max:
        return []
    option_count = (start_max - start_min + 1) * (length_max - length_min + 1)
    if option_count > _JUMP_MUTATION_OPTION_CAP:
        return None

    options: list[tuple[JumpPulse, int]] = []
    for start_frame in range(start_min, start_max + 1):
        maximum_length = min(length_max, range_end - start_frame + 1)
        if maximum_length < length_min:
            continue
        for hold_length in range(length_min, maximum_length + 1):
            options.append(
                (
                    JumpPulse(start_frame, hold_length),
                    abs(start_frame - source.start_frame - desired_start_offset)
                    + abs(hold_length - source.hold_length - desired_length_offset),
                )
            )
    return options


def _bounded_valid_jump_pattern(
    pulses: Sequence[JumpPulse],
    eligible_indices: Sequence[int],
    *,
    range_start: int,
    range_end: int,
    start_mutation: int,
    length_mutation: int,
    minimum_gap: int,
    immutable: dict[int, ImmutableJumpSpec],
    rng: random.Random,
) -> list[JumpPulse] | None:
    """Choose a valid pulse pattern near one set of random draws.

    A failed fast draw does not need another complete-pattern retry. Instead,
    each mutable pulse exposes its small bounded set of legal values and a
    shortest-path pass selects the closest globally compatible sequence. The
    source pattern is always one of the options, so a valid result exists when
    the option cap is not exceeded.
    """
    eligible = set(eligible_indices)
    desired: dict[int, tuple[int, int]] = {}
    for index in eligible_indices:
        pulse = pulses[index]
        start_offset = rng.randint(-start_mutation, start_mutation)
        length_offset = rng.randint(-length_mutation, length_mutation)
        spec = immutable.get(pulse.start_frame)
        desired[index] = (
            0 if spec is not None and spec.immutable_start else start_offset,
            0 if spec is not None and spec.immutable_length else length_offset,
        )

    option_lists: list[list[tuple[JumpPulse, int]]] = []
    for index, pulse in enumerate(pulses):
        if index not in eligible:
            option_lists.append([(pulse, 0)])
            continue
        start_offset, length_offset = desired[index]
        options = _jump_pulse_options(
            pulse,
            range_start=range_start,
            range_end=range_end,
            start_mutation=start_mutation,
            length_mutation=length_mutation,
            immutable=immutable.get(pulse.start_frame),
            desired_start_offset=start_offset,
            desired_length_offset=length_offset,
        )
        if options is None:
            return None
        if not options:
            return None
        option_lists.append(options)

    costs: list[list[int]] = []
    parents: list[list[int]] = []
    for index, options in enumerate(option_lists):
        row = [math.inf] * len(options)
        parent_row = [-1] * len(options)
        if index == 0:
            for option_index, (_pulse, cost) in enumerate(options):
                row[option_index] = cost
        else:
            previous_options = option_lists[index - 1]
            previous_costs = costs[index - 1]
            for option_index, (pulse, cost) in enumerate(options):
                best_cost = math.inf
                best_parent = -1
                for previous_index, (previous, _local_cost) in enumerate(
                    previous_options
                ):
                    previous_cost = previous_costs[previous_index]
                    if (
                        previous_cost < best_cost
                        and pulse.start_frame - previous.end_frame - 1
                        >= minimum_gap
                    ):
                        best_cost = previous_cost
                        best_parent = previous_index
                if best_parent >= 0:
                    row[option_index] = best_cost + cost
                    parent_row[option_index] = best_parent
        costs.append(row)
        parents.append(parent_row)

    if not costs or min(costs[-1], default=math.inf) == math.inf:
        return None
    option_index = min(range(len(costs[-1])), key=costs[-1].__getitem__)
    selected: list[JumpPulse] = [pulses[0]] * len(option_lists)
    for index in range(len(option_lists) - 1, -1, -1):
        selected[index] = option_lists[index][option_index][0]
        option_index = parents[index][option_index]
    return selected


def _rebuild_mutated_jump_frames(
    original_frames: Sequence[InputFrame],
    pulses: Sequence[JumpPulse],
    mutated_pulses: Sequence[JumpPulse],
    *,
    range_start: int,
    range_end: int,
) -> list[InputFrame]:
    """Normalize frames and touch only jump intervals changed by mutation."""
    frames = editable_frames(original_frames)
    changed = tuple(
        (source, mutated)
        for source, mutated in zip(pulses, mutated_pulses, strict=True)
        if source != mutated
    )
    for source, _mutated in changed:
        for frame_index in range(
            max(source.start_frame, range_start),
            min(source.end_frame, range_end) + 1,
        ):
            frames[frame_index] = _jump_only_frame(frames[frame_index], False)
    for _source, mutated in changed:
        for frame_index in range(
            max(mutated.start_frame, range_start),
            min(mutated.end_frame, range_end) + 1,
        ):
            frames[frame_index] = _jump_only_frame(frames[frame_index], True)
    return frames


def mutate_jump_inputs(
    original_frames: Sequence[InputFrame],
    *,
    range_start: int,
    range_end: int,
    start_mutation: int,
    length_mutation: int,
    rng: random.Random,
    minimum_gap: int = 1,
    immutable_jumps: Sequence[ImmutableJumpSpec] = (),
) -> tuple[list[InputFrame], tuple[tuple[JumpPulse, JumpPulse], ...]]:
    """Mutate complete jump pulses inside the mutable range.

    Each eligible pulse independently samples an integer start offset from
    ``[-start_mutation, +start_mutation]`` and an integer hold-length offset
    from ``[-length_mutation, +length_mutation]``. Valid whole-pattern draws
    are accepted immediately. After a small bounded number of rejected draws,
    a nearby structurally valid pattern is selected without an unbounded retry
    loop, keeping pulses inside the range, retaining their temporal order, and
    preserving at least ``minimum_gap`` released frames. Zero is present in
    both sampling ranges, so the source pulse is always a possible draw. Pulses
    crossing either range boundary are kept fixed. Source pulses named by
    ``immutable_jumps`` keep their requested source property: start frame, hold
    length, or both. Their normal start and length random draws are still
    consumed so changing immutability does not shift the per-attempt RNG
    allocation of later pulses.
    """
    if start_mutation < 0 or length_mutation < 0:
        raise ValueError("jump mutation values must be non-negative")
    if minimum_gap < 0:
        raise ValueError("minimum jump gap must be non-negative")
    if range_start < 0 or range_end < range_start:
        raise ValueError("range must satisfy 0 <= start <= end")
    if range_end >= len(original_frames):
        raise ValueError("jump mutation range lies outside the replay")

    pulses = jump_input_pulses(original_frames)
    immutable = validate_immutable_jumps(
        original_frames,
        range_start=range_start,
        range_end=range_end,
        immutable_jumps=immutable_jumps,
        source_pulses=pulses,
    )
    eligible_indices = tuple(
        index
        for index, pulse in enumerate(pulses)
        if pulse.start_frame >= range_start and pulse.end_frame <= range_end
    )
    if not eligible_indices or (start_mutation == 0 and length_mutation == 0):
        return editable_frames(original_frames), tuple(
            (pulses[index], pulses[index]) for index in eligible_indices
        )

    # Keep the common low-contention case on the inexpensive historical path.
    # Crowded patterns switch to a bounded compatible-pattern selection below;
    # this avoids spending thousands of full-pattern retries on the same RNG
    # draws when nearby pulses leave little legal space.
    mutated_pulses: list[JumpPulse] | None = None
    for _ in range(_JUMP_MUTATION_FAST_ATTEMPTS):
        candidate = list(pulses)
        for index in eligible_indices:
            pulse = pulses[index]
            start_offset = rng.randint(-start_mutation, start_mutation)
            length_offset = rng.randint(-length_mutation, length_mutation)
            spec = immutable.get(pulse.start_frame)
            candidate[index] = JumpPulse(
                pulse.start_frame
                if spec is not None and spec.immutable_start
                else pulse.start_frame + start_offset,
                pulse.hold_length
                if spec is not None and spec.immutable_length
                else pulse.hold_length + length_offset,
            )

        valid = True
        for index in eligible_indices:
            pulse = candidate[index]
            if (
                pulse.hold_length < 1
                or pulse.start_frame < range_start
                or pulse.end_frame > range_end
            ):
                valid = False
                break
        if valid:
            for left, right in zip(candidate, candidate[1:]):
                if right.start_frame - left.end_frame - 1 < minimum_gap:
                    valid = False
                    break
        if valid:
            mutated_pulses = candidate
            break

    if mutated_pulses is None:
        mutated_pulses = _bounded_valid_jump_pattern(
            pulses,
            eligible_indices,
            range_start=range_start,
            range_end=range_end,
            start_mutation=start_mutation,
            length_mutation=length_mutation,
            minimum_gap=minimum_gap,
            immutable=immutable,
            rng=rng,
        )
        if mutated_pulses is None:
            # The source pattern is always valid, including when the bounded
            # option cap deliberately declines a very large mutation range.
            mutated_pulses = list(pulses)

    changes = tuple(
        (pulses[index], mutated_pulses[index]) for index in eligible_indices
    )
    return (
        _rebuild_mutated_jump_frames(
            original_frames,
            pulses,
            mutated_pulses,
            range_start=range_start,
            range_end=range_end,
        ),
        changes,
    )


@dataclass(frozen=True, slots=True)
class _JumpSearchContext:
    """Immutable data shared by all branches and worker processes."""

    level: Level
    original: tuple[InputFrame, ...]
    released_frames: tuple[InputFrame, ...]
    held_frames: tuple[InputFrame, ...]
    target_frame: int
    range_start: int
    range_end: int
    objective_name: str
    objective_target: TargetSelection | None
    jump_count_min: int
    jump_count_max: int
    jump_length_min: int
    minimum_gap: int
    top_results: int
    fixed_frames: tuple[int, ...]
    x_window: AxisWindow | None
    y_window: AxisWindow | None
    start_max_lengths: tuple[int, ...]


@dataclass(slots=True)
class _JumpSearchStats:
    attempted_starts: int = 0
    successful_starts: int = 0
    evaluated_candidates: int = 0
    deduplicated_branches: int = 0

    def add(self, other: "_JumpSearchStats") -> None:
        self.attempted_starts += other.attempted_starts
        self.successful_starts += other.successful_starts
        self.evaluated_candidates += other.evaluated_candidates
        self.deduplicated_branches += other.deduplicated_branches


@dataclass(slots=True)
class _JumpSearchWorkItem:
    """An independently searchable state immediately after one jump pulse."""

    state: SimulationState
    next_frame: int
    pulses: tuple[JumpPulse, ...]
    state_key: tuple
    remaining_fixed: tuple[int, ...]


@dataclass(slots=True)
class _JumpWorkerResult:
    results: list[JumpSearchResult]
    stats: _JumpSearchStats


class _JumpPatternSearch:
    """One serial jump DFS, used alone or on a batch of process work items."""

    def __init__(self, context: _JumpSearchContext) -> None:
        self.context = context
        self.objective = objective_function(
            context.objective_name, context.objective_target
        )
        self.retained: list[tuple[float, int, JumpSearchResult]] = []
        self.serial = 0
        self.seen_branch_states: set[tuple[object, ...]] = set()
        self.terminal_cache: dict[tuple[object, ...], Evaluation] = {}
        self.stats = _JumpSearchStats()

    def retain(self, result: JumpSearchResult) -> None:
        if not result.evaluation.feasible:
            return
        self.serial += 1
        item = (result.score, self.serial, result)
        if len(self.retained) < self.context.top_results:
            heapq.heappush(self.retained, item)
        elif result.score > self.retained[0][0]:
            heapq.heapreplace(self.retained, item)

    def evaluate_tail(
        self,
        state_after_pulse: SimulationState,
        next_frame: int,
        precomputed_state_key: tuple,
        *,
        consume_state: bool,
    ) -> Evaluation:
        """Run released jump to range end, then replay the unchanged suffix."""
        context = self.context
        cache_key = (next_frame, precomputed_state_key)
        cached = self.terminal_cache.get(cache_key)
        if cached is not None:
            return cached

        self.stats.evaluated_candidates += 1
        state = (
            state_after_pulse
            if consume_state
            else state_after_pulse.clone(copy_on_write_objects=True)
        )
        step = state.step
        try:
            for frame_index in range(next_frame, context.range_end + 1):
                step(context.released_frames[frame_index], context.level.tiles)
                if state.player.dead:
                    result = Evaluation(float("-inf"), state, False)
                    self.terminal_cache[cache_key] = result
                    return result
            for frame_index in range(context.range_end + 1, context.target_frame + 1):
                step(context.original[frame_index], context.level.tiles)
                if state.player.dead:
                    result = Evaluation(float("-inf"), state, False)
                    self.terminal_cache[cache_key] = result
                    return result
        except UnsupportedTileCollision:
            result = Evaluation(float("-inf"), state, False)
            self.terminal_cache[cache_key] = result
            return result

        feasible = position_within_windows(
            state, x_window=context.x_window, y_window=context.y_window
        )
        result = Evaluation(
            self.objective(state) if feasible else float("-inf"), state, feasible
        )
        self.terminal_cache[cache_key] = result
        return result

    def process_work_item(
        self,
        item: _JumpSearchWorkItem,
        *,
        capture_count: int | None = None,
        frontier: list[_JumpSearchWorkItem] | None = None,
    ) -> None:
        """Evaluate and/or extend one owned post-pulse state."""
        context = self.context
        count = len(item.pulses)
        if capture_count == count:
            if frontier is None:
                raise ValueError("a frontier is required when capturing work")
            frontier.append(item)
            return

        can_evaluate = (
            not item.remaining_fixed
            and context.jump_count_min <= count <= context.jump_count_max
        )
        can_recurse = (
            count < context.jump_count_max
            and item.next_frame <= context.range_end
        )

        if can_evaluate and can_recurse:
            evaluation = self.evaluate_tail(
                item.state,
                item.next_frame,
                item.state_key,
                consume_state=False,
            )
            self.retain(JumpSearchResult(item.pulses, evaluation))
            self.recurse(
                item.state,
                item.next_frame,
                item.pulses,
                context.minimum_gap,
                state_key=item.state_key,
                consume_state=True,
                remaining_fixed=item.remaining_fixed,
                capture_count=capture_count,
                frontier=frontier,
            )
        elif can_evaluate:
            evaluation = self.evaluate_tail(
                item.state,
                item.next_frame,
                item.state_key,
                consume_state=True,
            )
            self.retain(JumpSearchResult(item.pulses, evaluation))
        elif can_recurse:
            self.recurse(
                item.state,
                item.next_frame,
                item.pulses,
                context.minimum_gap,
                state_key=item.state_key,
                consume_state=True,
                remaining_fixed=item.remaining_fixed,
                capture_count=capture_count,
                frontier=frontier,
            )

    def _dispatch_pulse(
        self,
        state_after_pulse: SimulationState,
        next_frame: int,
        pulses: tuple[JumpPulse, ...],
        state_key: tuple,
        remaining_fixed: tuple[int, ...],
        *,
        transfer_state: bool,
        capture_count: int | None,
        frontier: list[_JumpSearchWorkItem] | None,
    ) -> None:
        # Hold-state extension still owns non-final lengths. Give the work item
        # an isolated clone except when the final length can transfer ownership.
        item_state = (
            state_after_pulse
            if transfer_state
            else state_after_pulse.clone(copy_on_write_objects=True)
        )
        self.process_work_item(
            _JumpSearchWorkItem(
                item_state,
                next_frame,
                pulses,
                state_key,
                remaining_fixed,
            ),
            capture_count=capture_count,
            frontier=frontier,
        )

    def recurse(
        self,
        state_before_cursor: SimulationState,
        cursor: int,
        pulses: tuple[JumpPulse, ...],
        required_release_frames: int,
        *,
        state_key: tuple | None = None,
        consume_state: bool = False,
        remaining_fixed: tuple[int, ...] = (),
        capture_count: int | None = None,
        frontier: list[_JumpSearchWorkItem] | None = None,
    ) -> None:
        context = self.context
        used = len(pulses)
        if used >= context.jump_count_max or cursor > context.range_end:
            return
        if used + len(remaining_fixed) > context.jump_count_max:
            return
        if remaining_fixed and remaining_fixed[0] < cursor:
            return

        if state_key is None:
            state_key = state_before_cursor.state_key()
        branch_key = (
            used,
            cursor,
            required_release_frames,
            remaining_fixed,
            state_key,
        )
        if branch_key in self.seen_branch_states:
            self.stats.deduplicated_branches += 1
            return
        self.seen_branch_states.add(branch_key)

        walking_state = (
            state_before_cursor
            if consume_state
            else state_before_cursor.clone(copy_on_write_objects=True)
        )
        walking_step = walking_state.step
        start = cursor
        try:
            for _ in range(required_release_frames):
                if start > context.range_end:
                    return
                if remaining_fixed and start == remaining_fixed[0]:
                    return
                walking_step(
                    context.released_frames[start], context.level.tiles
                )
                if walking_state.player.dead:
                    return
                start += 1
        except UnsupportedTileCollision:
            return

        next_fixed = remaining_fixed[0] if remaining_fixed else None
        while start <= context.range_end:
            if next_fixed is not None and start > next_fixed:
                return
            if start + context.jump_length_min - 1 > context.range_end:
                break

            fixed_start = next_fixed is not None and start == next_fixed
            self.stats.attempted_starts += 1
            try:
                alternate_player = walking_step(
                    context.released_frames[start],
                    context.level.tiles,
                    alternate_jump=True,
                )
            except UnsupportedTileCollision:
                return

            if alternate_player is not None and not walking_state.player.dead:
                self.stats.successful_starts += 1
                hold_state = walking_state.clone(
                    player=alternate_player,
                    copy_on_write_objects=True,
                )
                child_remaining_fixed = (
                    remaining_fixed[1:] if fixed_start else remaining_fixed
                )
                max_length_here = context.start_max_lengths[
                    start - context.range_start
                ]
                if child_remaining_fixed:
                    following_fixed = child_remaining_fixed[0]
                    max_length_here = min(
                        max_length_here,
                        following_fixed - context.minimum_gap - start,
                    )

                hold_step = hold_state.step
                length = 1
                while length <= max_length_here:
                    if length >= context.jump_length_min:
                        pulse = JumpPulse(start, length)
                        next_pulses = pulses + (pulse,)
                        next_frame = pulse.end_frame + 1
                        count = len(next_pulses)
                        can_evaluate = (
                            not child_remaining_fixed
                            and context.jump_count_min
                            <= count
                            <= context.jump_count_max
                        )
                        can_recurse = (
                            count < context.jump_count_max
                            and next_frame <= context.range_end
                        )
                        if can_evaluate or can_recurse:
                            self._dispatch_pulse(
                                hold_state,
                                next_frame,
                                next_pulses,
                                hold_state.state_key(),
                                child_remaining_fixed,
                                transfer_state=length == max_length_here,
                                capture_count=capture_count,
                                frontier=frontier,
                            )

                    length += 1
                    if length > max_length_here:
                        break
                    next_hold_frame = start + length - 1
                    try:
                        hold_step(
                            context.held_frames[next_hold_frame], context.level.tiles
                        )
                    except UnsupportedTileCollision:
                        break
                    if hold_state.player.dead:
                        break

            if fixed_start:
                return
            if walking_state.player.dead:
                return
            start += 1

    def finish(self) -> _JumpWorkerResult:
        results = [item[2] for item in self.retained]
        results.sort(key=lambda result: result.score, reverse=True)
        return _JumpWorkerResult(results, self.stats)


_JUMP_WORKER_CONTEXT: _JumpSearchContext | None = None


def _initialise_jump_worker(context: _JumpSearchContext) -> None:
    global _JUMP_WORKER_CONTEXT
    _JUMP_WORKER_CONTEXT = context


def _run_jump_work_batch(
    items: tuple[_JumpSearchWorkItem, ...],
) -> _JumpWorkerResult:
    context = _JUMP_WORKER_CONTEXT
    if context is None:
        raise RuntimeError("jump worker was not initialised")
    search = _JumpPatternSearch(context)
    for item in items:
        search.process_work_item(item)
    return search.finish()


def _automatic_jump_worker_count(frontier_size: int | None = None) -> int:
    """Choose a CPU-bound process count, accounting for spawn startup cost."""
    process_cpu_count = getattr(os, "process_cpu_count", None)
    if process_cpu_count is not None:
        available = process_cpu_count()
    elif hasattr(os, "sched_getaffinity"):
        try:
            available = len(os.sched_getaffinity(0))
        except OSError:
            available = os.cpu_count()
    else:
        available = os.cpu_count()
    available = min(8, max(1, available or 1))
    if (
        frontier_size is None
        or multiprocessing.get_context().get_start_method() != "spawn"
    ):
        return available

    # Windows and macOS start fresh interpreters. Scale the pool only when the
    # exact viable frontier is large enough to amortise each additional import.
    if frontier_size < 64:
        return 1
    if frontier_size < 256:
        return min(2, available)
    if frontier_size < 1024:
        return min(4, available)
    return available


def _jump_work_cost(
    context: _JumpSearchContext, item: _JumpSearchWorkItem
) -> int:
    """Estimate relative subtree size for longest-processing-time batching."""
    mutable_frames = max(0, context.range_end - item.next_frame + 1)
    remaining_jumps = max(0, context.jump_count_max - len(item.pulses))
    branching = (mutable_frames + 1) ** max(1, remaining_jumps)
    terminal_tail = max(0, context.target_frame - item.next_frame + 1)
    return branching + terminal_tail


def _partition_jump_work(
    context: _JumpSearchContext,
    frontier: Sequence[_JumpSearchWorkItem],
    batch_count: int,
) -> tuple[tuple[_JumpSearchWorkItem, ...], ...]:
    """Balance frontier states into coarse batches with small IPC overhead."""
    buckets: list[list[_JumpSearchWorkItem]] = [[] for _ in range(batch_count)]
    loads = [(0, index) for index in range(batch_count)]
    heapq.heapify(loads)
    ordered = sorted(
        frontier,
        key=lambda item: _jump_work_cost(context, item),
        reverse=True,
    )
    for item in ordered:
        load, index = heapq.heappop(loads)
        cost = _jump_work_cost(context, item)
        buckets[index].append(item)
        heapq.heappush(loads, (load + cost, index))
    return tuple(tuple(bucket) for bucket in buckets if bucket)


def _prepare_jump_search(
    level: Level,
    original_frames: Sequence[InputFrame],
    *,
    target_frame: int,
    range_start: int,
    range_end: int,
    objective_name: str,
    objective_target: TargetSelection | None,
    jump_count_min: int,
    jump_count_max: int,
    jump_length_min: int,
    jump_length_max: int | None,
    minimum_gap: int,
    top_results: int,
    fixed_jump_frames: Sequence[int],
    x_window: AxisWindow | None,
    y_window: AxisWindow | None,
) -> tuple[_JumpSearchContext | None, SimulationState | None]:
    if target_frame < range_end:
        raise ValueError("target frame cannot be before the end of the jump-search range")
    if range_start < 0 or range_end < range_start:
        raise ValueError("range must satisfy 0 <= start <= end")
    if target_frame >= len(original_frames):
        raise ValueError("target frame lies outside the replay")
    if jump_count_min < 1 or jump_count_max < jump_count_min:
        raise ValueError("jump counts must satisfy 1 <= minimum <= maximum")
    if jump_length_min < 1:
        raise ValueError("minimum jump hold length must be at least 1")
    if jump_length_max is not None and jump_length_max < jump_length_min:
        raise ValueError("maximum jump hold length cannot be below the minimum")
    if minimum_gap < 1:
        raise ValueError("minimum gap must be at least 1 released frame")
    if top_results < 1:
        raise ValueError("top_results must be at least 1")

    fixed_frames = tuple(sorted(fixed_jump_frames))
    fixed_set = frozenset(fixed_frames)
    if len(fixed_set) != len(fixed_frames):
        raise ValueError("fixed jump frames must not contain duplicates")
    outside = [
        frame
        for frame in fixed_frames
        if frame < range_start or frame > range_end
    ]
    if outside:
        raise ValueError(
            "fixed jump frames must lie inside the mutable range: "
            + ", ".join(map(str, outside))
        )
    if len(fixed_frames) > jump_count_max:
        raise ValueError(
            "number of fixed jump frames exceeds the maximum successful-jump count"
        )
    for first, second in zip(fixed_frames, fixed_frames[1:]):
        minimum_distance = jump_length_min + minimum_gap
        if second - first < minimum_distance:
            raise ValueError(
                f"fixed jump frames {first} and {second} are too close for "
                f"minimum hold {jump_length_min} plus gap {minimum_gap}"
            )

    original = tuple(editable_frames(original_frames))
    released_frames = tuple(_jump_only_frame(frame, False) for frame in original)
    held_frames = tuple(_jump_only_frame(frame, True) for frame in original)
    if fixed_frames:
        previous_jump = original[range_start - 1].jump if range_start > 0 else False
        source_starts: set[int] = set()
        for frame_index in range(range_start, range_end + 1):
            held = original[frame_index].jump
            if held and not previous_jump:
                source_starts.add(frame_index)
            previous_jump = held
        missing_source_starts = fixed_set - source_starts
        if missing_source_starts:
            raise ValueError(
                "fixed jump frame is not a jump start in the source replay: "
                + ", ".join(map(str, sorted(missing_source_starts)))
            )

    range_length = range_end - range_start + 1
    effective_max_length = (
        range_length
        if jump_length_max is None
        else min(jump_length_max, range_length)
    )
    if jump_length_min > effective_max_length:
        return None, None

    start_max_lengths = tuple(
        min(effective_max_length, range_end - frame + 1)
        for frame in range(range_start, range_end + 1)
    )
    context = _JumpSearchContext(
        level=level,
        original=original,
        released_frames=released_frames,
        held_frames=held_frames,
        target_frame=target_frame,
        range_start=range_start,
        range_end=range_end,
        objective_name=objective_name,
        objective_target=objective_target,
        jump_count_min=jump_count_min,
        jump_count_max=jump_count_max,
        jump_length_min=jump_length_min,
        minimum_gap=minimum_gap,
        top_results=top_results,
        fixed_frames=fixed_frames,
        x_window=x_window,
        y_window=y_window,
        start_max_lengths=start_max_lengths,
    )
    return context, state_before_frame(level, original, range_start)


def _report_jump_search(
    result: _JumpWorkerResult,
    progress: Callable[[str], None] | None,
) -> list[JumpSearchResult]:
    if progress is not None:
        stats = result.stats
        progress(
            "jump search: "
            f"attempted {stats.attempted_starts} starts, "
            f"{stats.successful_starts} produced Player.jump(), "
            f"evaluated {stats.evaluated_candidates} terminal states, "
            f"deduplicated {stats.deduplicated_branches} branches"
        )
        if result.results:
            progress(f"retained top {len(result.results)} feasible jump patterns")
    return result.results


def optimise_jump_patterns(
    level: Level,
    original_frames: Sequence[InputFrame],
    *,
    target_frame: int,
    range_start: int,
    range_end: int,
    objective_name: str,
    objective_target: TargetSelection | None = None,
    jump_count_min: int = 2,
    jump_count_max: int = 3,
    jump_length_min: int = 1,
    jump_length_max: int | None = None,
    minimum_gap: int = 1,
    top_results: int = 10,
    fixed_jump_frames: Sequence[int] = (),
    x_window: AxisWindow | None = None,
    y_window: AxisWindow | None = None,
    workers: int = 1,
    progress: Callable[[str], None] | None = print,
) -> list[JumpSearchResult]:
    """Exhaustively search successful jump pulses, optionally in processes.

    Horizontal input is preserved. Jump input inside the mutable range is
    replaced by non-overlapping pulses whose rising edges actually invoke
    ``Player.jump()``. ``workers=0`` selects up to eight available CPUs;
    ``workers=1`` retains the low-overhead serial path.

    Parallel search creates exact post-pulse simulator frontier states in the
    parent and sends coarse, load-balanced batches to persistent worker
    processes. Workers have independent transposition caches, so the result is
    exhaustive but equal-score ordering and cache statistics may differ from
    a serial traversal.
    """
    if workers < 0:
        raise ValueError("workers must be zero (auto) or a positive integer")
    context, prefix_state = _prepare_jump_search(
        level,
        original_frames,
        target_frame=target_frame,
        range_start=range_start,
        range_end=range_end,
        objective_name=objective_name,
        objective_target=objective_target,
        jump_count_min=jump_count_min,
        jump_count_max=jump_count_max,
        jump_length_min=jump_length_min,
        jump_length_max=jump_length_max,
        minimum_gap=minimum_gap,
        top_results=top_results,
        fixed_jump_frames=fixed_jump_frames,
        x_window=x_window,
        y_window=y_window,
    )
    if context is None or prefix_state is None:
        return []

    if progress is not None and context.fixed_frames:
        progress(
            "fixed jump starts: "
            + ", ".join(map(str, context.fixed_frames))
            + "; start frames locked, hold lengths variable"
        )

    automatic_workers = workers == 0
    worker_count = _automatic_jump_worker_count() if automatic_workers else workers
    search = _JumpPatternSearch(context)
    if worker_count <= 1:
        search.recurse(
            prefix_state,
            context.range_start,
            (),
            0,
            consume_state=True,
            remaining_fixed=context.fixed_frames,
        )
        return _report_jump_search(search.finish(), progress)

    # Split only at exact post-pulse states. This keeps every emulator tick in
    # one process and avoids any approximation or shared mutable simulation.
    frontier: list[_JumpSearchWorkItem] = []
    search.recurse(
        prefix_state,
        context.range_start,
        (),
        0,
        consume_state=True,
        remaining_fixed=context.fixed_frames,
        capture_count=1,
        frontier=frontier,
    )

    # A fixed first start or narrow length range may expose too little first-
    # pulse parallelism. Expand that small frontier once in the parent and split
    # after the second pulse instead.
    if len(frontier) < worker_count and context.jump_count_max > 1:
        expanded: list[_JumpSearchWorkItem] = []
        for item in frontier:
            search.process_work_item(
                item,
                capture_count=2,
                frontier=expanded,
            )
        frontier = expanded

    if len(frontier) < 2:
        for item in frontier:
            search.process_work_item(item)
        return _report_jump_search(search.finish(), progress)

    if automatic_workers:
        worker_count = _automatic_jump_worker_count(len(frontier))
    if worker_count <= 1:
        for item in frontier:
            search.process_work_item(item)
        return _report_jump_search(search.finish(), progress)

    actual_workers = min(worker_count, len(frontier))
    batch_count = min(len(frontier), actual_workers * 2)
    batches = _partition_jump_work(context, frontier, batch_count)
    if progress is not None:
        progress(
            f"jump search: {actual_workers} worker processes, "
            f"{len(frontier)} independent frontier branches"
        )

    with ProcessPoolExecutor(
        max_workers=actual_workers,
        mp_context=multiprocessing.get_context(),
        initializer=_initialise_jump_worker,
        initargs=(context,),
    ) as executor:
        worker_results = list(executor.map(_run_jump_work_batch, batches))

    parent_result = search.finish()
    merged = list(parent_result.results)
    stats = parent_result.stats
    for worker_result in worker_results:
        merged.extend(worker_result.results)
        stats.add(worker_result.stats)
    merged.sort(key=lambda result: result.score, reverse=True)
    merged_result = _JumpWorkerResult(merged[: context.top_results], stats)
    return _report_jump_search(merged_result, progress)

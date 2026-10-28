"""Jump-pulse utilities and exhaustive jump-pattern search."""
from __future__ import annotations

import math
import multiprocessing
import os
import random
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from threading import Event

from nv14_engine import InputFrame, Level
from nv14_objectives import (
    AxisWindow,
    Evaluation,
    TargetSelection,
    evaluate,
    objective_function,
)
from nv14_replay import editable_frames
from nv14_search import (
    NativeTerminalState,
    NativeSearchSession,
    PatternSearchCandidate,
    PatternSearchResult,
    PatternSearchSpec,
    PatternSearchStats,
    REQUIRED_START_EVENT_JUMPED,
    compile_axis_window,
    compile_objective,
    native_player_matches,
)


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
class _PreparedJumpSearch:
    """Validated Python policy compiled for the native pattern kernel."""

    original: tuple[InputFrame, ...]
    spec: PatternSearchSpec
    fixed_frames: tuple[int, ...]
    theoretical_root_branches: int


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

    # Local mode still uses process workers. Preserve its spawn-startup policy
    # even though jump-pattern now calls the native kernel from worker threads.
    if frontier_size < 64:
        return 1
    if frontier_size < 256:
        return min(2, available)
    if frontier_size < 1024:
        return min(4, available)
    return available


def _theoretical_root_branch_count(spec: PatternSearchSpec) -> int:
    """Estimate native first-run branches without simulating their rising edges."""
    last_start = spec.fixed_starts[0] if spec.fixed_starts else spec.range_end
    total = 0
    for start in range(spec.range_start, last_start + 1):
        maximum_length = spec.start_max_lengths[start - spec.range_start]
        following_fixed: int | None
        if not spec.fixed_starts:
            following_fixed = None
        elif start < spec.fixed_starts[0]:
            following_fixed = spec.fixed_starts[0]
        elif len(spec.fixed_starts) > 1:
            following_fixed = spec.fixed_starts[1]
        else:
            following_fixed = None
        if following_fixed is not None:
            maximum_length = min(
                maximum_length,
                following_fixed - spec.minimum_gap - start,
            )
        total += max(0, maximum_length - spec.run_length_min + 1)
    return total


def _automatic_pattern_worker_count(theoretical_root_branches: int) -> int:
    """Scale native threads only when root work can amortise extra sessions."""
    available = _automatic_jump_worker_count()
    if theoretical_root_branches < 64:
        return 1
    if theoretical_root_branches < 256:
        return min(2, available)
    if theoretical_root_branches < 1024:
        return min(4, available)
    return min(available, theoretical_root_branches)


def _prepare_jump_search(
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
) -> _PreparedJumpSearch | None:
    """Validate jump policy and compile a data-only native pattern spec."""
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
        return None

    start_max_lengths = tuple(
        min(effective_max_length, range_end - frame + 1)
        for frame in range(range_start, range_end + 1)
    )
    inactive_inputs = tuple(
        _jump_only_frame(original[frame], False)
        for frame in range(range_start, range_end + 1)
    )
    active_inputs = tuple(
        _jump_only_frame(original[frame], True)
        for frame in range(range_start, range_end + 1)
    )
    objective, targets = compile_objective(objective_name, objective_target)
    spec = PatternSearchSpec(
        range_start=range_start,
        range_end=range_end,
        inactive_inputs=inactive_inputs,
        active_inputs=active_inputs,
        target_frame=target_frame,
        objective=objective,
        targets=targets,
        x_window=compile_axis_window(x_window),
        y_window=compile_axis_window(y_window),
        run_count_min=jump_count_min,
        run_count_max=jump_count_max,
        run_length_min=jump_length_min,
        start_max_lengths=start_max_lengths,
        minimum_gap=minimum_gap,
        fixed_starts=fixed_frames,
        required_start_event_mask=REQUIRED_START_EVENT_JUMPED,
        top_results=top_results,
    )
    return _PreparedJumpSearch(
        original=original,
        spec=spec,
        fixed_frames=fixed_frames,
        theoretical_root_branches=_theoretical_root_branch_count(spec),
    )


def _run_native_pattern_shard(
    level: Level,
    original: tuple[InputFrame, ...],
    spec: PatternSearchSpec,
    cancel_event: Event | None = None,
) -> PatternSearchResult:
    """Own one native session so searches on separate threads never share state."""
    session = NativeSearchSession(level)
    if cancel_event is None:
        return session.search_patterns(original, spec)
    return session.search_patterns(original, spec, cancel_event)


def _merge_native_pattern_shards(
    shard_results: Sequence[PatternSearchResult],
    *,
    top_results: int,
) -> tuple[tuple[PatternSearchCandidate, ...], PatternSearchStats]:
    candidates: list[PatternSearchCandidate] = []
    stats = PatternSearchStats()
    for result in shard_results:
        candidates.extend(result.candidates)
        stats = stats.add(result.stats)
    # Native DFS visits start frames and hold lengths in ascending order; that
    # traversal is lexicographic on spans.  Restore the same global tie order
    # after modulo-sharded searches instead of depending on shard completion.
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.spans))
    return tuple(candidates[:top_results]), stats


def _materialise_jump_results(
    level: Level,
    original: tuple[InputFrame, ...],
    candidates: Sequence[PatternSearchCandidate],
    *,
    target_frame: int,
    range_start: int,
    range_end: int,
    objective_name: str,
    objective_target: TargetSelection | None,
    x_window: AxisWindow | None,
    y_window: AxisWindow | None,
    python_resimulate: bool,
) -> list[JumpSearchResult]:
    """Adapt retained native results, optionally checking them in Python."""
    objective = (
        objective_function(objective_name, objective_target)
        if python_resimulate
        else None
    )
    results: list[JumpSearchResult] = []
    for candidate in candidates:
        pulses = tuple(
            JumpPulse(start_frame, hold_length)
            for start_frame, hold_length in candidate.spans
        )
        if candidate.player is None:
            raise RuntimeError("native jump-pattern result omitted its player")
        evaluation = Evaluation(
            candidate.score,
            NativeTerminalState.from_snapshot(
                candidate.player,
                frame=target_frame + 1,
            ),
            True,
        )
        if python_resimulate:
            assert objective is not None
            frames = apply_jump_pattern(
                original,
                range_start=range_start,
                range_end=range_end,
                pulses=pulses,
            )
            python_evaluation = evaluate(
                level,
                frames,
                target_frame,
                objective,
                x_window=x_window,
                y_window=y_window,
            )
            native_state_matches = native_player_matches(
                candidate.player,
                python_evaluation.state.player,
            )
            if (
                not python_evaluation.feasible
                or python_evaluation.score != candidate.score
                or not native_state_matches
            ):
                raise RuntimeError(
                    "native jump-pattern result failed exact Python "
                    f"resimulation for "
                    f"{', '.join(map(str, pulses)) or 'empty pattern'}: "
                    f"native score={candidate.score!r}, "
                    f"Python score={python_evaluation.score!r}, "
                    f"Python feasible={python_evaluation.feasible}, "
                    f"terminal player match={native_state_matches}"
                )
            evaluation = python_evaluation
        results.append(JumpSearchResult(pulses, evaluation))
    return results


def _report_jump_search(
    results: list[JumpSearchResult],
    stats: PatternSearchStats,
    progress: Callable[[str], None] | None,
) -> list[JumpSearchResult]:
    if progress is not None:
        progress(
            "jump search: "
            f"attempted {stats.attempted_starts} starts, "
            f"{stats.successful_starts} produced Player.jump(), "
            f"evaluated {stats.evaluated_candidates} terminal states, "
            f"deduplicated {stats.deduplicated_branches} branches"
        )
        if results:
            progress(f"retained top {len(results)} feasible jump patterns")
    return results


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
    python_resimulate: bool = False,
) -> list[JumpSearchResult]:
    """Exhaustively search successful jump pulses in the native C kernel.

    Horizontal input is preserved. Jump input inside the mutable range is
    replaced by non-overlapping pulses whose rising edges actually invoke
    Player.jump(). workers=0 chooses up to eight CPUs automatically; explicit
    positive values run that many native shards when enough root work exists.
    Parallel shards execute in threads because the native wrapper releases the
    GIL and each thread owns an independent native search session.

    ``python_resimulate`` replays every retained native result through the
    Python reference emulator and compares its score and full exported player
    snapshot. This diagnostic is deliberately disabled by default.
    """
    if workers < 0:
        raise ValueError("workers must be zero (auto) or a positive integer")
    prepared = _prepare_jump_search(
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
    if prepared is None:
        return []

    if progress is not None and prepared.fixed_frames:
        progress(
            "fixed jump starts: "
            + ", ".join(map(str, prepared.fixed_frames))
            + "; start frames locked, hold lengths variable"
        )

    theoretical_branches = max(1, prepared.theoretical_root_branches)
    if workers == 0:
        worker_count = _automatic_pattern_worker_count(theoretical_branches)
    else:
        worker_count = workers
    actual_workers = min(max(1, worker_count), theoretical_branches)

    if actual_workers == 1:
        native_results = (
            _run_native_pattern_shard(level, prepared.original, prepared.spec),
        )
    else:
        if progress is not None:
            progress(
                f"jump search: {actual_workers} native worker threads, "
                f"{actual_workers} exhaustive shards"
            )
        shard_specs = tuple(
            replace(
                prepared.spec,
                shard_index=shard_index,
                shard_count=actual_workers,
            )
            for shard_index in range(actual_workers)
        )
        cancel_event = Event()
        futures: list[Future[PatternSearchResult]] = []
        with ThreadPoolExecutor(
            max_workers=actual_workers,
            thread_name_prefix="nv14-jump",
        ) as executor:
            completed: list[PatternSearchResult | None] = [None] * actual_workers
            try:
                for shard_spec in shard_specs:
                    futures.append(
                        executor.submit(
                            _run_native_pattern_shard,
                            level,
                            prepared.original,
                            shard_spec,
                            cancel_event,
                        )
                    )
                future_indices = {
                    future: shard_index
                    for shard_index, future in enumerate(futures)
                }
                for future in as_completed(futures):
                    completed[future_indices[future]] = future.result()
            except BaseException:
                # Wake native siblings before executor shutdown waits for them.
                cancel_event.set()
                for future in futures:
                    future.cancel()
                raise
            if any(result is None for result in completed):
                raise RuntimeError("a native jump-search shard did not complete")
            native_results = tuple(
                result for result in completed if result is not None
            )

    candidates, stats = _merge_native_pattern_shards(
        native_results,
        top_results=prepared.spec.top_results,
    )
    results = _materialise_jump_results(
        level,
        prepared.original,
        candidates,
        target_frame=target_frame,
        range_start=range_start,
        range_end=range_end,
        objective_name=objective_name,
        objective_target=objective_target,
        x_window=x_window,
        y_window=y_window,
        python_resimulate=python_resimulate,
    )
    return _report_jump_search(results, stats, progress)

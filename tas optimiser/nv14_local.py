"""Sliding-window local replay search and its multiprocessing workers."""
from __future__ import annotations

import math
import multiprocessing
import random
import signal
from bisect import bisect_right
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass

from nv14_engine import (
    InputFrame,
    Level,
)
from nv14_jump import (
    ImmutableJumpSpec,
    JumpPulse,
    _automatic_jump_worker_count,
    mutate_jump_inputs,
    validate_immutable_jumps,
)
from nv14_objectives import (
    AxisWindow,
    Evaluation,
    InteractionAvoidance,
    InteractionRequirement,
    TargetSelection,
    evaluate,
    format_interaction_avoidances,
    format_interaction_requirements,
    interaction_constraint_status,
    merge_interaction_avoidances,
    merge_interaction_requirements,
    objective_function,
    reference_interaction_requirements,
)
from nv14_replay import editable_frames, input_symbol
from nv14_search import (
    ALL_INPUT_CHOICES,
    NativeTerminalState,
    NativeSearchSession,
    SearchResult,
    SearchSpec,
    build_direction_choices,
    compile_axis_window,
    compile_interaction_groups,
    compile_objective,
    native_player_matches,
)


def _stop_local_executor(
    executor: ProcessPoolExecutor,
    futures: Sequence[Future[object]] = (),
) -> None:
    """Stop local workers without waiting for an interrupted search to finish.

    ``ProcessPoolExecutor.__exit__`` always performs ``shutdown(wait=True)``.
    That is the wrong policy after Ctrl+C: a local search can have several
    expensive replay evaluations still queued, so waiting in the context
    manager makes the interrupt appear ineffective. Give already-running
    futures a brief chance to observe cancellation, then terminate the exact
    executor-owned child processes if they remain active.
    """
    if futures:
        for future in futures:
            future.cancel()
        _done, pending = wait(futures, timeout=2.0)
        if not pending:
            executor.shutdown(wait=True, cancel_futures=True)
            return

    terminate_workers = getattr(executor, "terminate_workers", None)
    if callable(terminate_workers):
        terminate_workers()
        return

    # Python 3.11-3.13 have no public immediate ProcessPool stop operation.
    # These are the executor's own child Process objects; terminate only
    # those exact processes, then let shutdown join the management thread.
    processes = tuple(getattr(executor, "_processes", {}).values())
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(timeout=2.0)
    executor.shutdown(wait=True, cancel_futures=True)


def _stop_local_executor_for_exception(
    executor: ProcessPoolExecutor,
    futures: Sequence[Future[object]] = (),
) -> None:
    """Stop a local executor while shielding cleanup from a second Ctrl+C."""
    previous_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        _stop_local_executor(executor, futures)
    finally:
        signal.signal(signal.SIGINT, previous_handler)


class _LocalExecutorScope:
    """Context manager with an interrupt-safe ProcessPoolExecutor exit."""

    def __init__(self, executor: ProcessPoolExecutor) -> None:
        self.executor = executor

    def __enter__(self) -> ProcessPoolExecutor:
        return self.executor

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        if exc_type is None:
            self.executor.shutdown(wait=True)
        else:
            _stop_local_executor_for_exception(self.executor)
        return False


@dataclass(frozen=True, slots=True)
class LocalWindow:
    """One local-search window represented by its mutable replay frames.

    Contiguous search uses consecutive frame numbers. Sparse search uses the
    same representation with gaps between some or all mutable frames, allowing
    the intervening replay inputs to remain fixed while still participating in
    the simulation.
    """

    frames: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.frames:
            raise ValueError("a local window must contain at least one frame")
        if tuple(sorted(set(self.frames))) != self.frames:
            raise ValueError("local-window frames must be unique and sorted")

    @property
    def start(self) -> int:
        return self.frames[0]

    @property
    def end(self) -> int:
        return self.frames[-1]

    @property
    def centre(self) -> float:
        return sum(self.frames) / len(self.frames)


def _normalise_local_frame_ranges(
    range_start: int,
    range_end: int,
    frame_ranges: Sequence[tuple[int, int]] | None,
) -> tuple[tuple[int, int], ...]:
    """Return sorted, disjoint local ranges, retaining the legacy endpoints."""
    supplied = (
        tuple(frame_ranges)
        if frame_ranges is not None
        else ((range_start, range_end),)
    )
    if not supplied:
        raise ValueError("at least one local range is required")
    parsed: list[tuple[int, int]] = []
    for interval in supplied:
        if len(interval) != 2:
            raise ValueError("each local range must contain a start and end")
        start, end = interval
        if start < 0 or end < start:
            raise ValueError("range must satisfy 0 <= start <= end")
        parsed.append((start, end))

    merged: list[tuple[int, int]] = []
    for start, end in sorted(parsed):
        if merged and start <= merged[-1][1] + 1:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _local_range_length(frame_ranges: Sequence[tuple[int, int]]) -> int:
    """Return the number of distinct mutable frames in normalized ranges."""
    return sum(end - start + 1 for start, end in frame_ranges)


def _local_range_frames(
    frame_ranges: Sequence[tuple[int, int]],
) -> tuple[int, ...]:
    """Expand normalized ranges into their sorted mutable frame indices."""
    return tuple(
        frame
        for start, end in frame_ranges
        for frame in range(start, end + 1)
    )


def _frame_in_local_ranges(
    frame: int, frame_ranges: Sequence[tuple[int, int]]
) -> bool:
    return any(start <= frame <= end for start, end in frame_ranges)


def _contiguous_local_windows(
    range_start: int, range_end: int, window_size: int
) -> list[LocalWindow]:
    """Return the ordinary overlapping consecutive local windows."""
    effective_window = min(window_size, range_end - range_start + 1)
    return [
        LocalWindow(tuple(range(start, start + effective_window)))
        for start in range(range_start, range_end - effective_window + 2)
    ]


def _contiguous_local_windows_for_ranges(
    frame_ranges: Sequence[tuple[int, int]], window_size: int
) -> list[LocalWindow]:
    """Return consecutive windows without ever bridging an excluded gap."""
    return [
        window
        for range_start, range_end in frame_ranges
        for window in _contiguous_local_windows(
            range_start, range_end, window_size
        )
    ]


def _local_pass_window_shape(window_shape: str, pass_index: int) -> str:
    """Resolve one pass's concrete shape, with mixed starting sparse."""
    if window_shape == "mixed":
        return "sparse" if pass_index % 2 == 0 else "contiguous"
    return window_shape


def _sparse_window_capacity(
    range_length: int, window_size: int, window_span: int | None
) -> int:
    """Number of distinct sparse frame sets satisfying an optional span.

    ``window_span`` counts frame positions inclusively. For example, eight
    mutable frames with ``window_span=8`` can only form a contiguous 8-frame
    set, while ``window_span=24`` permits those eight frames to be distributed
    anywhere inside at most 24 consecutive replay frames.
    """
    effective_window = min(window_size, range_length)
    effective_span = min(window_span or range_length, range_length)
    if effective_window == 1:
        return range_length
    if effective_span < effective_window:
        return 0

    # Count sets by their exact inclusive width. The first and last positions
    # are fixed and W-2 interior positions are selected from width-2 slots.
    return sum(
        (range_length - width + 1) * math.comb(width - 2, effective_window - 2)
        for width in range(effective_window, effective_span + 1)
    )


def _sample_sparse_local_windows(
    range_start: int,
    range_end: int,
    window_size: int,
    *,
    window_span: int | None,
    windows_per_pass: int,
    rng: random.Random,
) -> list[LocalWindow]:
    """Uniformly sample unique non-necessarily-consecutive frame sets.

    When a span limit is present, sets are sampled uniformly from all distinct
    combinations whose first-to-last inclusive width does not exceed that span.
    This avoids biasing toward especially compact sets merely because they fit
    inside more possible span containers.
    """
    range_length = range_end - range_start + 1
    effective_window = min(window_size, range_length)
    effective_span = min(window_span or range_length, range_length)
    capacity = _sparse_window_capacity(
        range_length, effective_window, effective_span
    )
    desired = min(windows_per_pass, capacity)
    if desired <= 0:
        return []

    # These edge cases can be sampled exactly without duplicate rejection.
    if effective_window == 1:
        candidates = [LocalWindow((frame,)) for frame in range(range_start, range_end + 1)]
        rng.shuffle(candidates)
        return candidates[:desired]
    if effective_span == effective_window:
        candidates = _contiguous_local_windows(range_start, range_end, effective_window)
        rng.shuffle(candidates)
        return candidates[:desired]

    # If the valid pool is modest and the caller asks for a large fraction of
    # it, exact enumeration avoids coupon-collector behaviour near capacity.
    exact_enumeration_threshold = 200_000
    if capacity <= exact_enumeration_threshold and desired * 3 > capacity:
        from itertools import combinations

        all_valid = [
            LocalWindow(frames)
            for frames in combinations(
                range(range_start, range_end + 1), effective_window
            )
            if frames[-1] - frames[0] + 1 <= effective_span
        ]
        rng.shuffle(all_valid)
        return all_valid[:desired]

    # With no effective span restriction every combination in the range is
    # valid.  Sampling the frame set directly avoids the linear width-bucket
    # scan below; this matters for large replay ranges where a random sparse
    # pass can otherwise spend more time selecting windows than describing
    # them.  Duplicate rejection is retained because the caller requests
    # distinct frame sets.
    if effective_span == range_length:
        selected: set[tuple[int, ...]] = set()
        frame_pool = range(range_start, range_end + 1)
        while len(selected) < desired:
            selected.add(tuple(sorted(rng.sample(frame_pool, effective_window))))
        result = [LocalWindow(frames) for frames in sorted(selected)]
        rng.shuffle(result)
        return result

    # Choose the exact first-to-last width in proportion to the number of frame
    # sets with that width. Then choose its start and interior frames uniformly.
    # Every valid frame set consequently has the same probability on each draw.
    widths: list[int] = []
    cumulative_width_ends: list[int] = []
    cumulative = 0
    for width in range(effective_window, effective_span + 1):
        count = (range_length - width + 1) * math.comb(
            width - 2, effective_window - 2
        )
        cumulative += count
        widths.append(width)
        cumulative_width_ends.append(cumulative)

    selected: set[tuple[int, ...]] = set()
    while len(selected) < desired:
        ticket = rng.randrange(capacity)
        width = widths[bisect_right(cumulative_width_ends, ticket)]
        first = rng.randint(range_start, range_end - width + 1)
        last = first + width - 1
        interiors = tuple(
            sorted(
                rng.sample(
                    range(first + 1, last),
                    effective_window - 2,
                )
            )
        )
        selected.add((first, *interiors, last))

    # Sort before shuffling so seeded sparse sampling is reproducible even if
    # set iteration details differ between Python builds.
    result = [LocalWindow(frames) for frames in sorted(selected)]
    rng.shuffle(result)
    return result


def _sparse_window_capacity_for_frames(
    mutable_frames: Sequence[int],
    window_size: int,
    window_span: int | None,
) -> int:
    """Count sparse windows over an arbitrary sorted mutable-frame set."""
    range_length = len(mutable_frames)
    effective_window = min(window_size, range_length)
    if effective_window == 0:
        return 0
    if window_span is None:
        return math.comb(range_length, effective_window)
    if effective_window == 1:
        return range_length
    if window_span < effective_window:
        return 0

    capacity = 0
    for index, first in enumerate(mutable_frames):
        end_index = bisect_right(
            mutable_frames, first + window_span - 1, lo=index + 1
        )
        available = end_index - index - 1
        if available >= effective_window - 1:
            capacity += math.comb(available, effective_window - 1)
    return capacity


def _sample_sparse_local_windows_for_ranges(
    frame_ranges: Sequence[tuple[int, int]],
    window_size: int,
    *,
    window_span: int | None,
    windows_per_pass: int,
    rng: random.Random,
) -> list[LocalWindow]:
    """Uniformly sample sparse windows from the union of local ranges."""
    if len(frame_ranges) == 1:
        range_start, range_end = frame_ranges[0]
        return _sample_sparse_local_windows(
            range_start,
            range_end,
            window_size,
            window_span=window_span,
            windows_per_pass=windows_per_pass,
            rng=rng,
        )

    mutable_frames = _local_range_frames(frame_ranges)
    range_length = len(mutable_frames)
    effective_window = min(window_size, range_length)
    capacity = _sparse_window_capacity_for_frames(
        mutable_frames, effective_window, window_span
    )
    desired = min(windows_per_pass, capacity)
    if desired <= 0:
        return []
    if effective_window == 1:
        candidates = [LocalWindow((frame,)) for frame in mutable_frames]
        rng.shuffle(candidates)
        return candidates[:desired]

    exact_enumeration_threshold = 200_000
    if capacity <= exact_enumeration_threshold and desired * 3 > capacity:
        from itertools import combinations

        if window_span is None:
            all_valid = [
                LocalWindow(frames)
                for frames in combinations(mutable_frames, effective_window)
            ]
        else:
            all_valid = []
            for index, first in enumerate(mutable_frames):
                end_index = bisect_right(
                    mutable_frames,
                    first + window_span - 1,
                    lo=index + 1,
                )
                all_valid.extend(
                    LocalWindow((first, *rest))
                    for rest in combinations(
                        mutable_frames[index + 1 : end_index],
                        effective_window - 1,
                    )
                )
        rng.shuffle(all_valid)
        return all_valid[:desired]

    selected: set[tuple[int, ...]] = set()
    if window_span is None:
        while len(selected) < desired:
            selected.add(
                tuple(sorted(rng.sample(mutable_frames, effective_window)))
            )
    else:
        first_indices: list[int] = []
        cumulative_ends: list[int] = []
        cumulative = 0
        for index, first in enumerate(mutable_frames):
            end_index = bisect_right(
                mutable_frames, first + window_span - 1, lo=index + 1
            )
            available = end_index - index - 1
            if available < effective_window - 1:
                continue
            cumulative += math.comb(available, effective_window - 1)
            first_indices.append(index)
            cumulative_ends.append(cumulative)

        while len(selected) < desired:
            ticket = rng.randrange(capacity)
            bucket = bisect_right(cumulative_ends, ticket)
            first_index = first_indices[bucket]
            first = mutable_frames[first_index]
            end_index = bisect_right(
                mutable_frames, first + window_span - 1, lo=first_index + 1
            )
            rest = rng.sample(
                mutable_frames[first_index + 1 : end_index],
                effective_window - 1,
            )
            selected.add((first, *sorted(rest)))

    result = [LocalWindow(frames) for frames in sorted(selected)]
    rng.shuffle(result)
    return result

def _ordered_local_windows(
    windows: Sequence[LocalWindow],
    *,
    window_order: str,
    rng: random.Random | None,
) -> list[LocalWindow]:
    """Order a concrete pass's windows using their temporal centre."""
    if window_order == "forward":
        return sorted(windows, key=lambda window: (window.centre, window.frames))
    if window_order == "reverse":
        return sorted(
            windows,
            key=lambda window: (window.centre, window.frames),
            reverse=True,
        )
    if window_order == "random":
        if rng is None:
            raise ValueError("random window order requires an RNG")
        result = list(windows)
        rng.shuffle(result)
        return result
    raise ValueError("window order must be forward, reverse or random")


def _local_window_description(window: LocalWindow, *, sparse: bool) -> str:
    """Compact progress label for a local frame set."""
    if not sparse:
        return f"frames {window.start}-{window.end}"
    return "frames [" + ",".join(map(str, window.frames)) + "]"


def _hard_requirements_improved(
    candidate_eval: Evaluation,
    candidate_missing_jump_frames: frozenset[int],
    incumbent_eval: Evaluation,
    incumbent_missing_jump_frames: frozenset[int],
) -> bool:
    """Return whether a candidate strictly repairs without any hard regression."""
    return (
        candidate_eval.missing_interactions
        <= incumbent_eval.missing_interactions
        and candidate_eval.violated_interactions
        <= incumbent_eval.violated_interactions
        and candidate_missing_jump_frames <= incumbent_missing_jump_frames
        and (
            candidate_eval.missing_interactions
            != incumbent_eval.missing_interactions
            or candidate_eval.violated_interactions
            != incumbent_eval.violated_interactions
            or candidate_missing_jump_frames != incumbent_missing_jump_frames
        )
    )


def successful_jump_frames(
    level: Level, frames: Sequence[InputFrame], target_frame: int
) -> frozenset[int]:
    """Return frames on which the replay actually invokes ``Player.jump()``.

    Trigger bits are canonicalised from the held-jump sequence, matching the
    editable replay used by the local optimiser.
    """
    editable = editable_frames(frames)
    state = level.initial_state()
    events: set[int] = set()
    for frame_index in range(target_frame + 1):
        before = state.player.jump_events
        state.step(editable[frame_index], level.tiles)
        if state.player.jump_events > before:
            events.add(frame_index)
        if state.player.dead:
            break
    return frozenset(events)


def jump_press_frames(
    frames: Sequence[InputFrame], target_frame: int
) -> frozenset[int]:
    """Return held-jump rising edges in the source replay through target frame.

    Direction-only local search preserves the held-jump sequence exactly, so a
    False -> True transition is the stable definition of an initially requested
    jump. Unlike :func:`successful_jump_frames`, this intentionally includes
    presses that fail to invoke ``Player.jump()`` in the baseline simulation.
    """
    previous = False
    result: set[int] = set()
    for frame_index in range(target_frame + 1):
        held = frames[frame_index].jump
        if held and not previous:
            result.add(frame_index)
        previous = held
    return frozenset(result)


def _replace_mutated_jump_starts(
    source_required_jump_frames: frozenset[int],
    changes: Sequence[tuple[JumpPulse, JumpPulse]],
) -> frozenset[int]:
    """Update required rising-edge frames from the mutator's pulse mapping."""
    result = set(source_required_jump_frames)
    for source, mutated in changes:
        if source.start_frame != mutated.start_frame:
            result.discard(source.start_frame)
            result.add(mutated.start_frame)
    return frozenset(result)


@dataclass(slots=True)
class LocalSearchRunResult:
    """Result of one independent local-search trajectory."""

    frames: list[InputFrame]
    evaluation: Evaluation
    label: str
    missing_required_jump_frames: frozenset[int] = frozenset()
    required_jump_frames: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class _LocalRunRank:
    """Pickle-light local ranking state for streamed worker improvements."""

    feasible: bool
    missing_interactions: frozenset[InteractionRequirement]
    violated_interactions: frozenset[InteractionAvoidance]
    missing_required_jump_frames: frozenset[int]
    required_jump_frames: frozenset[int]
    score: float


@dataclass(frozen=True, slots=True)
class _LocalImprovementEvent:
    """One accepted improvement plus its immutable checkpoint snapshot."""

    run_label: str
    message: str
    rank: _LocalRunRank
    run: LocalSearchRunResult


@dataclass(frozen=True, slots=True)
class _LocalRunSpec:
    """Independent trajectory inputs for a random/mixed local search."""

    order: str
    rng: random.Random | None
    label: str
    jump_rng: random.Random | None


@dataclass(slots=True)
class _LocalRunContext:
    """Immutable configuration shared by local-search worker processes."""

    level: Level
    original_frames: tuple[InputFrame, ...]
    target_frame: int
    range_start: int
    range_end: int
    frame_ranges: tuple[tuple[int, int], ...]
    objective_name: str
    objective_target: TargetSelection | None
    window_size: int
    passes: int
    minimum_improvement: float
    x_window: AxisWindow | None
    y_window: AxisWindow | None
    local_inputs: str
    physics_prune: bool
    window_shape: str
    window_span: int | None
    windows_per_pass: int | None
    jump_start_mutation: int
    jump_length_mutation: int
    immutable_jumps: tuple[ImmutableJumpSpec, ...]
    immutable_jump_map: dict[int, ImmutableJumpSpec]
    required_jump_frames: frozenset[int]
    required_interactions: tuple[InteractionRequirement, ...]
    avoided_interactions: tuple[InteractionAvoidance, ...]
    baseline: Evaluation
    baseline_missing_jump_frames: frozenset[int]
    python_resimulate: bool


def _native_local_evaluation(
    result: SearchResult,
    *,
    target_frame: int,
    required_interactions: Sequence[InteractionRequirement],
    avoided_interactions: Sequence[InteractionAvoidance],
) -> Evaluation:
    """Adapt one native winner without running the Python emulator."""
    if result.player is None:
        raise RuntimeError("native search omitted the winning terminal player")
    try:
        missing = frozenset(
            required_interactions[index]
            for index in result.missing_requirement_indices
        )
        violated = frozenset(
            avoided_interactions[index]
            for index in result.violated_avoidance_indices
        )
    except IndexError as exc:
        raise RuntimeError(
            "native search returned an out-of-range interaction index"
        ) from exc
    return Evaluation(
        result.score,
        NativeTerminalState.from_snapshot(
            result.player,
            frame=target_frame + 1,
        ),
        result.feasible,
        missing,
        violated,
    )


def _mutate_jump_inputs_in_ranges(
    original_frames: Sequence[InputFrame],
    *,
    frame_ranges: Sequence[tuple[int, int]],
    start_mutation: int,
    length_mutation: int,
    rng: random.Random,
    immutable_jumps: Sequence[ImmutableJumpSpec],
) -> tuple[list[InputFrame], tuple[tuple[JumpPulse, JumpPulse], ...]]:
    """Mutate only complete pulses contained by one permitted local interval."""
    if len(frame_ranges) == 1:
        range_start, range_end = frame_ranges[0]
        return mutate_jump_inputs(
            original_frames,
            range_start=range_start,
            range_end=range_end,
            start_mutation=start_mutation,
            length_mutation=length_mutation,
            rng=rng,
            immutable_jumps=immutable_jumps,
        )

    current = editable_frames(original_frames)
    changes: list[tuple[JumpPulse, JumpPulse]] = []
    for range_start, range_end in frame_ranges:
        interval_immutable = tuple(
            spec
            for spec in immutable_jumps
            if range_start <= spec.start_frame <= range_end
        )
        current, interval_changes = mutate_jump_inputs(
            current,
            range_start=range_start,
            range_end=range_end,
            start_mutation=start_mutation,
            length_mutation=length_mutation,
            rng=rng,
            immutable_jumps=interval_immutable,
        )
        changes.extend(interval_changes)
    return current, tuple(changes)


def _execute_local_run(
    context: _LocalRunContext,
    spec: _LocalRunSpec,
    progress: Callable[[str], None] | None,
    *,
    improvement_progress: Callable[[_LocalImprovementEvent], None] | None = None,
) -> LocalSearchRunResult:
    """Execute one independent trajectory, optionally collecting diagnostics."""
    run_frames: Sequence[InputFrame] = context.original_frames
    run_required_jump_frames = context.required_jump_frames
    jump_changes: Sequence[tuple[JumpPulse, JumpPulse]] = ()
    if spec.jump_rng is not None:
        run_frames, jump_changes = _mutate_jump_inputs_in_ranges(
            context.original_frames,
            frame_ranges=context.frame_ranges,
            start_mutation=context.jump_start_mutation,
            length_mutation=context.jump_length_mutation,
            rng=spec.jump_rng,
            immutable_jumps=context.immutable_jumps,
        )
        run_required_jump_frames = _replace_mutated_jump_starts(
            context.required_jump_frames,
            jump_changes,
        )
        if progress is not None:
            mutation_text = ", ".join(
                (
                    (
                        f"{source} immutable"
                        if context.immutable_jump_map[source.start_frame].mode == "both"
                        else f"{source} -> {mutated} "
                        f"[{context.immutable_jump_map[source.start_frame].mode} immutable]"
                    )
                    if source.start_frame in context.immutable_jump_map
                    else f"{source} -> {mutated}"
                )
                for source, mutated in jump_changes
            ) or "no complete jump pulses in range"
            progress(f"{spec.label} jump mutation: {mutation_text}")
            required_text = (
                ", ".join(map(str, sorted(run_required_jump_frames))) or "none"
            )
            progress(f"{spec.label} required jump-press frames: {required_text}")
    if progress is not None:
        source_text = "mutated replay" if spec.jump_rng is not None else "original replay"
        progress(f"starting {spec.label} from {source_text}")

    run = _optimise_local_single_run(
        context.level,
        run_frames,
        target_frame=context.target_frame,
        range_start=context.range_start,
        range_end=context.range_end,
        frame_ranges=context.frame_ranges,
        objective_name=context.objective_name,
        objective_target=context.objective_target,
        window_size=context.window_size,
        passes=context.passes,
        minimum_improvement=context.minimum_improvement,
        x_window=context.x_window,
        y_window=context.y_window,
        local_inputs=context.local_inputs,
        physics_prune=context.physics_prune,
        required_jump_frames=run_required_jump_frames,
        required_interactions=context.required_interactions,
        avoided_interactions=context.avoided_interactions,
        window_order=spec.order,
        window_shape=context.window_shape,
        window_span=context.window_span,
        windows_per_pass=context.windows_per_pass,
        rng=spec.rng,
        run_label=spec.label,
        progress=progress,
        improvement_progress=improvement_progress,
        initial_evaluation=context.baseline if spec.jump_rng is None else None,
        initial_missing_jump_frames=(
            context.baseline_missing_jump_frames
            if spec.jump_rng is None
            else None
        ),
        frames_are_editable=True,
        python_resimulate=context.python_resimulate,
    )
    if progress is not None:
        p = run.evaluation.state.player
        interaction_text = format_interaction_requirements(
            tuple(run.evaluation.missing_interactions)
        )
        avoidance_text = format_interaction_avoidances(
            tuple(run.evaluation.violated_interactions)
        )
        if context.local_inputs == "direction":
            missing_text = (
                ", ".join(map(str, sorted(run.missing_required_jump_frames)))
                or "none"
            )
            progress(
                f"finished {spec.label}: missing-interactions={interaction_text}, "
                f"triggered-forbidden-interactions={avoidance_text}, "
                f"missed-required-jumps={missing_text}, "
                f"score={run.evaluation.score:.17g}, "
                f"position=({p.pos.x:.15g}, {p.pos.y:.15g})"
            )
        else:
            progress(
                f"finished {spec.label}: missing-interactions={interaction_text}, "
                f"triggered-forbidden-interactions={avoidance_text}, "
                f"score={run.evaluation.score:.17g}, "
                f"position=({p.pos.x:.15g}, {p.pos.y:.15g})"
            )
    return run


_LOCAL_RUN_CONTEXT: _LocalRunContext | None = None
_LOCAL_RUN_PROGRESS_QUEUE = None


def _initialise_local_worker(
    context: _LocalRunContext,
    progress_queue=None,
) -> None:
    global _LOCAL_RUN_CONTEXT, _LOCAL_RUN_PROGRESS_QUEUE
    _LOCAL_RUN_CONTEXT = context
    _LOCAL_RUN_PROGRESS_QUEUE = progress_queue
    if multiprocessing.current_process().name != "MainProcess":
        signal.signal(signal.SIGINT, signal.SIG_IGN)


def _emit_local_worker_improvement(event: _LocalImprovementEvent) -> None:
    """Publish one accepted local improvement to the parent process."""
    if _LOCAL_RUN_PROGRESS_QUEUE is not None:
        _LOCAL_RUN_PROGRESS_QUEUE.put(event)


def _run_local_work_item(
    spec: _LocalRunSpec,
) -> tuple[LocalSearchRunResult, int]:
    """Run one trajectory while streaming only accepted improvements."""
    context = _LOCAL_RUN_CONTEXT
    if context is None:
        raise RuntimeError("local-search worker was not initialised")
    improvement_count = 0

    def emit_improvement(event: _LocalImprovementEvent) -> None:
        nonlocal improvement_count
        _emit_local_worker_improvement(event)
        # Count only events whose synchronous SimpleQueue write completed.
        # The parent uses this count to preserve per-run ordering before it
        # emits the restart summary and checkpoints the completed result.
        improvement_count += 1

    run = _execute_local_run(
        context,
        spec,
        None,
        improvement_progress=(
            emit_improvement
            if _LOCAL_RUN_PROGRESS_QUEUE is not None
            else None
        ),
    )
    return run, improvement_count


def _drain_local_worker_progress(
    progress_queue,
    deliver: Callable[[_LocalImprovementEvent], None],
) -> int:
    """Forward all currently queued worker improvements to the parent."""
    count = 0
    while not progress_queue.empty():
        deliver(progress_queue.get())
        count += 1
    return count


def _automatic_local_worker_count(task_count: int) -> int:
    """Choose a process count for independent local trajectories."""
    available = _automatic_jump_worker_count()
    if task_count < 2:
        return 1
    if multiprocessing.get_context().get_start_method() != "spawn":
        return min(available, task_count)
    if task_count < 4:
        return min(2, available)
    if task_count < 8:
        return min(4, available)
    return min(available, task_count)


def _estimate_local_run_work(
    *,
    target_frame: int,
    range_start: int,
    range_end: int,
    frame_ranges: Sequence[tuple[int, int]] | None = None,
    window_size: int,
    passes: int,
    local_inputs: str,
    window_shape: str,
    windows_per_pass: int | None,
) -> int:
    """Cheap simulator-tick estimate used only by the automatic worker policy."""
    normalized_ranges = _normalise_local_frame_ranges(
        range_start, range_end, frame_ranges
    )
    range_length = _local_range_length(normalized_ranges)
    effective_window = min(window_size, range_length)
    contiguous_count = max(
        1,
        len(
            _contiguous_local_windows_for_ranges(
                normalized_ranges, effective_window
            )
        ),
    )
    sparse_count = windows_per_pass or contiguous_count
    if window_shape == "sparse":
        total_window_count = sparse_count * passes
    elif window_shape == "mixed":
        sparse_passes = (passes + 1) // 2
        contiguous_passes = passes // 2
        total_window_count = (
            sparse_count * sparse_passes
            + contiguous_count * contiguous_passes
        )
    else:
        total_window_count = contiguous_count * passes
    # Direction has exactly three choices. Fresh all-input jump presses are
    # often pruned, so four is a better startup estimate than the raw six while
    # still accounting for active holds and successful jump branches.
    branch_factor = 3 if local_inputs == "direction" else 4
    leaves = 1
    for _ in range(effective_window):
        leaves *= branch_factor
        if leaves >= 1_000_000_000:
            leaves = 1_000_000_000
            break
    average_end = sum(
        ((start + end) / 2.0) * (end - start + 1)
        for start, end in normalized_ranges
    ) / range_length
    average_suffix = max(1.0, target_frame - average_end + 1.0)
    return int(total_window_count * leaves * average_suffix)


def _automatic_local_trajectory_workers(
    task_count: int,
    *,
    estimated_run_work: int,
) -> int:
    """Avoid a fresh multi-trajectory pool when each complete run is tiny."""
    if task_count < 2:
        return 1
    spawn = multiprocessing.get_context().get_start_method() == "spawn"
    if not spawn:
        if estimated_run_work < 10_000:
            return 1
        return _automatic_local_worker_count(task_count)
    if estimated_run_work < 50_000:
        return 1
    available = _automatic_jump_worker_count()
    if estimated_run_work < 150_000:
        return min(2, available, task_count)
    return min(available, task_count)


def _local_rank_from_evaluation(
    evaluation: Evaluation,
    missing_required_jump_frames: frozenset[int],
    required_jump_frames: frozenset[int],
) -> _LocalRunRank:
    """Extract the exact fields used by the independent-run comparator."""
    return _LocalRunRank(
        feasible=evaluation.feasible,
        missing_interactions=evaluation.missing_interactions,
        violated_interactions=evaluation.violated_interactions,
        missing_required_jump_frames=missing_required_jump_frames,
        required_jump_frames=required_jump_frames,
        score=evaluation.score,
    )


def _local_rank_from_run(run: LocalSearchRunResult) -> _LocalRunRank:
    return _local_rank_from_evaluation(
        run.evaluation,
        run.missing_required_jump_frames,
        run.required_jump_frames,
    )


def _local_rank_better(candidate: _LocalRunRank, best: _LocalRunRank) -> bool:
    """Compare local ranking states without exchanging hard requirements."""
    if not candidate.feasible:
        return False
    if not best.feasible:
        return True
    if not candidate.missing_interactions <= best.missing_interactions:
        return False
    if not candidate.violated_interactions <= best.violated_interactions:
        return False

    interactions_improved = (
        candidate.missing_interactions != best.missing_interactions
        or candidate.violated_interactions != best.violated_interactions
    )
    if candidate.required_jump_frames == best.required_jump_frames:
        if not (
            candidate.missing_required_jump_frames
            <= best.missing_required_jump_frames
        ):
            return False
        jumps_improved = (
            candidate.missing_required_jump_frames
            != best.missing_required_jump_frames
        )
    else:
        candidate_misses = len(candidate.missing_required_jump_frames)
        best_misses = len(best.missing_required_jump_frames)
        if candidate_misses > best_misses:
            return False
        jumps_improved = candidate_misses < best_misses

    if interactions_improved or jumps_improved:
        return True
    return candidate.score > best.score


def _local_run_better(
    candidate: LocalSearchRunResult,
    best: LocalSearchRunResult,
) -> bool:
    """Compare independent trajectories using local mode's normal ranking."""
    return _local_rank_better(
        _local_rank_from_run(candidate),
        _local_rank_from_run(best),
    )


def _optimise_local_single_run(
    level: Level,
    original_frames: Sequence[InputFrame],
    *,
    target_frame: int,
    range_start: int,
    range_end: int,
    frame_ranges: Sequence[tuple[int, int]] | None = None,
    objective_name: str,
    objective_target: TargetSelection | None,
    window_size: int,
    passes: int,
    minimum_improvement: float,
    x_window: AxisWindow | None,
    y_window: AxisWindow | None,
    local_inputs: str,
    physics_prune: bool,
    required_jump_frames: frozenset[int],
    required_interactions: Sequence[InteractionRequirement],
    avoided_interactions: Sequence[InteractionAvoidance],
    window_order: str,
    window_shape: str,
    window_span: int | None,
    windows_per_pass: int | None,
    rng: random.Random | None,
    run_label: str,
    progress: Callable[[str], None] | None,
    improvement_progress: Callable[[_LocalImprovementEvent], None] | None = None,
    initial_evaluation: Evaluation | None = None,
    initial_missing_jump_frames: frozenset[int] | None = None,
    frames_are_editable: bool = False,
    python_resimulate: bool = False,
) -> LocalSearchRunResult:
    """Run one greedy local optimisation from the untouched input replay.

    Contiguous mode visits the same overlapping frame intervals on every pass
    without crossing excluded gaps. Sparse mode samples a fresh set of
    mutable-frame combinations from the union of ranges on every pass.
    Mixed mode uses sparse windows on pass one, contiguous windows on pass two,
    then alternates. ``window_order`` orders each pass by temporal centre (or
    shuffles it for random order). The replay continues from the preceding pass.
    """
    if window_order not in ("forward", "reverse", "random"):
        raise ValueError("single-run window order must be forward, reverse or random")
    if window_shape not in ("contiguous", "sparse", "mixed"):
        raise ValueError(
            "window_shape must be 'contiguous', 'sparse' or 'mixed'"
        )
    if (
        window_order == "random" or window_shape in ("sparse", "mixed")
    ) and rng is None:
        raise ValueError("random/sparse/mixed local search requires an RNG")

    normalized_ranges = _normalise_local_frame_ranges(
        range_start, range_end, frame_ranges
    )
    range_start = normalized_ranges[0][0]
    range_end = normalized_ranges[-1][1]

    objective = objective_function(objective_name, objective_target)
    native_objective, native_targets = compile_objective(
        objective_name, objective_target
    )
    native_required_groups = compile_interaction_groups(required_interactions)
    native_avoided_groups = compile_interaction_groups(avoided_interactions)
    native_x_window = compile_axis_window(x_window)
    native_y_window = compile_axis_window(y_window)
    search_session = NativeSearchSession(level)

    def interaction_indices(
        constraints: Sequence[InteractionRequirement | InteractionAvoidance],
        selected: frozenset[InteractionRequirement]
        | frozenset[InteractionAvoidance],
    ) -> frozenset[int]:
        return frozenset(
            index
            for index, constraint in enumerate(constraints)
            if constraint in selected
        )
    # Both the untouched baseline and jump-mutated restart inputs are already
    # normalized by optimise_local_windows. Avoid rebuilding every InputFrame
    # when opening each independent trajectory; retain a private mutable list.
    current = (
        list(original_frames)
        if frames_are_editable
        else editable_frames(original_frames)
    )
    # The outer optimiser already evaluates every unmutated run's source
    # replay. Reusing that exact result avoids replaying the whole prefix and
    # target suffix for forward/reverse/random control trajectories.
    current_eval = (
        initial_evaluation
        if initial_evaluation is not None
        else evaluate(
            level,
            current,
            target_frame,
            objective,
            x_window=x_window,
            y_window=y_window,
            required_interactions=required_interactions,
            avoided_interactions=avoided_interactions,
        )
    )
    if local_inputs == "direction":
        current_missing_jump_frames = (
            initial_missing_jump_frames
            if initial_missing_jump_frames is not None
            else (
                required_jump_frames
                - successful_jump_frames(level, current, target_frame)
            )
        )
    else:
        current_missing_jump_frames = frozenset()
    range_length = _local_range_length(normalized_ranges)
    effective_window = min(window_size, range_length)
    contiguous_windows = _contiguous_local_windows_for_ranges(
        normalized_ranges, effective_window
    )
    sparse_windows_requested = windows_per_pass or len(contiguous_windows)
    sparse_capacity = (
        (
            _sparse_window_capacity(
                range_length, effective_window, window_span
            )
            if len(normalized_ranges) == 1
            else _sparse_window_capacity_for_frames(
                _local_range_frames(normalized_ranges),
                effective_window,
                window_span,
            )
        )
        if window_shape in ("sparse", "mixed")
        else 0
    )
    sparse_windows_actual = min(sparse_windows_requested, sparse_capacity)

    if progress is not None:
        p = current_eval.state.player
        progress(
            f"{run_label} baseline: score={current_eval.score:.17g}, "
            f"position=({p.pos.x:.15g}, {p.pos.y:.15g}), "
            f"within-window={current_eval.feasible}"
        )
        if local_inputs == "direction":
            missing_text = (
                ", ".join(map(str, sorted(current_missing_jump_frames))) or "none"
            )
            progress(
                f"{run_label} baseline missed required jump presses: {missing_text}"
            )
        if required_interactions:
            progress(
                f"{run_label} baseline missing required interactions: "
                f"{format_interaction_requirements(current_eval.missing_interactions)}"
            )
        if avoided_interactions:
            progress(
                f"{run_label} baseline forbidden interactions triggered: "
                f"{format_interaction_avoidances(current_eval.violated_interactions)}"
            )
        if (
            window_shape in ("sparse", "mixed")
            and sparse_windows_actual < sparse_windows_requested
        ):
            progress(
                f"{run_label}: requested {sparse_windows_requested} sparse windows "
                f"per pass but only {sparse_capacity} distinct frame sets satisfy "
                "the requested size/span; using all of them"
            )

    for pass_index in range(passes):
        changed_this_pass = False
        pass_window_shape = _local_pass_window_shape(window_shape, pass_index)
        if pass_window_shape == "contiguous":
            pass_windows = contiguous_windows
        else:
            assert rng is not None
            pass_windows = _sample_sparse_local_windows_for_ranges(
                normalized_ranges,
                effective_window,
                window_span=window_span,
                windows_per_pass=sparse_windows_requested,
                rng=rng,
            )

        ordered_windows = _ordered_local_windows(
            pass_windows,
            window_order=window_order,
            rng=rng,
        )

        if progress is not None:
            if pass_window_shape == "sparse":
                span_text = (
                    "full range"
                    if window_span is None
                    else f"max span {min(window_span, range_end - range_start + 1)}"
                )
                progress(
                    f"{run_label}, pass {pass_index + 1}: sampled "
                    f"{len(ordered_windows)} sparse windows ({span_text}); "
                    f"{window_order} window order"
                )
            elif window_order == "random":
                progress(
                    f"{run_label}, pass {pass_index + 1}: shuffled "
                    f"{len(ordered_windows)} window starts"
                )
            else:
                progress(
                    f"{run_label}, pass {pass_index + 1}: {window_order} window order"
                )

        for window in ordered_windows:
            incumbent_slice = tuple(current[index] for index in window.frames)
            description = _local_window_description(
                window, sparse=pass_window_shape == "sparse"
            )
            direction_search = local_inputs == "direction"
            choices = (
                build_direction_choices(current, window.frames, objective_name)
                if direction_search
                else tuple(ALL_INPUT_CHOICES for _ in window.frames)
            )
            incumbent_missing_requirements = interaction_indices(
                required_interactions, current_eval.missing_interactions
            )
            incumbent_violated_avoidances = interaction_indices(
                avoided_interactions, current_eval.violated_interactions
            )
            search_result = search_session.search(
                current,
                SearchSpec(
                    mutable_frames=window.frames,
                    choices=choices,
                    target_frame=target_frame,
                    objective=native_objective,
                    targets=native_targets,
                    x_window=native_x_window,
                    y_window=native_y_window,
                    required_groups=native_required_groups,
                    avoided_groups=native_avoided_groups,
                    incumbent_missing_requirements=incumbent_missing_requirements,
                    incumbent_violated_avoidances=incumbent_violated_avoidances,
                    required_jump_frames=(
                        tuple(sorted(required_jump_frames))
                        if direction_search
                        else ()
                    ),
                    incumbent_missing_jump_frames=(
                        current_missing_jump_frames
                        if direction_search
                        else frozenset()
                    ),
                    incumbent_score=current_eval.score,
                    incumbent_feasible=current_eval.feasible,
                    prune_inactive_jump=not direction_search,
                    physics_prune=physics_prune and direction_search,
                    skip_unchanged_final_step=direction_search,
                ),
            )
            stats = search_result.stats
            best_slice = list(incumbent_slice)
            best_eval = current_eval
            best_missing_jump_frames = current_missing_jump_frames

            if search_result.improved:
                if len(search_result.best_inputs) != len(window.frames):
                    raise RuntimeError(
                        "native search returned the wrong number of replacement inputs"
                    )
                best_slice = list(search_result.best_inputs)
                candidate = list(current)
                for frame_index, replacement_input in zip(
                    window.frames, best_slice, strict=True
                ):
                    candidate[frame_index] = replacement_input
                best_eval = _native_local_evaluation(
                    search_result,
                    target_frame=target_frame,
                    required_interactions=required_interactions,
                    avoided_interactions=avoided_interactions,
                )
                best_missing_jump_frames = search_result.missing_jump_frames
                if python_resimulate:
                    successful_jumps: set[int] | None = (
                        set() if direction_search else None
                    )
                    python_evaluation = evaluate(
                        level,
                        candidate,
                        target_frame,
                        objective,
                        x_window=x_window,
                        y_window=y_window,
                        required_interactions=required_interactions,
                        avoided_interactions=avoided_interactions,
                        successful_jump_frames_out=successful_jumps,
                    )
                    python_missing_jump_frames = (
                        required_jump_frames - frozenset(successful_jumps)
                        if successful_jumps is not None
                        else frozenset()
                    )
                    verified_missing = interaction_indices(
                        required_interactions,
                        python_evaluation.missing_interactions,
                    )
                    verified_violated = interaction_indices(
                        avoided_interactions,
                        python_evaluation.violated_interactions,
                    )
                    if (
                        python_evaluation.score != search_result.score
                        or python_evaluation.feasible != search_result.feasible
                        or verified_missing
                        != search_result.missing_requirement_indices
                        or verified_violated
                        != search_result.violated_avoidance_indices
                        or python_missing_jump_frames
                        != search_result.missing_jump_frames
                        or search_result.player is None
                        or not native_player_matches(
                            search_result.player,
                            python_evaluation.state.player,
                        )
                    ):
                        raise RuntimeError(
                            "native search result disagrees with Python replay "
                            "resimulation"
                        )
                    best_eval = python_evaluation
                    best_missing_jump_frames = python_missing_jump_frames

            if progress is not None:
                search_prefix = "" if run_label == "forward" else f"{run_label}, "
                if direction_search:
                    progress(
                        f"{search_prefix}{description} search: "
                        f"nodes={stats.visited_nodes}, "
                        f"leaves={stats.evaluated_leaves}, "
                        f"missed-jump={stats.missed_jump_prunes}, "
                        f"dedup={stats.deduplicated_prunes}, "
                        f"physics={stats.physics_prunes}, "
                        f"dead={stats.dead_prunes}, "
                        f"avoided={stats.avoided_interaction_prunes}"
                    )
                else:
                    progress(
                        f"{search_prefix}{description} search: "
                        f"nodes={stats.visited_nodes}, "
                        f"leaves={stats.evaluated_leaves}, "
                        f"inactive-jump={stats.inactive_jump_prunes}, "
                        f"dedup={stats.deduplicated_prunes}, "
                        f"dead={stats.dead_prunes}, "
                        f"avoided={stats.avoided_interaction_prunes}"
                    )

            hard_improves = _hard_requirements_improved(
                best_eval,
                best_missing_jump_frames,
                current_eval,
                current_missing_jump_frames,
            )
            hard_unchanged = (
                best_eval.missing_interactions == current_eval.missing_interactions
                and best_eval.violated_interactions
                == current_eval.violated_interactions
                and best_missing_jump_frames == current_missing_jump_frames
            )
            objective_improves = (
                hard_unchanged
                and best_eval.score > current_eval.score + minimum_improvement
            )
            accept_window = best_eval.feasible and (
                hard_improves or objective_improves
            )

            if accept_window:
                old_eval = current_eval
                old_score = current_eval.score
                old_missing_jump_frames = current_missing_jump_frames
                for frame_index, replacement in zip(
                    window.frames, best_slice, strict=True
                ):
                    current[frame_index] = replacement
                current_eval = best_eval
                if local_inputs == "direction":
                    current_missing_jump_frames = best_missing_jump_frames
                changed_this_pass = True
                if progress is not None or improvement_progress is not None:
                    if pass_window_shape == "sparse":
                        symbols = " ".join(
                            f"{frame_index}:{input_symbol(frame)}"
                            for frame_index, frame in zip(
                                window.frames, best_slice, strict=True
                            )
                        )
                    else:
                        symbols = " ".join(input_symbol(frame) for frame in best_slice)
                    p = best_eval.state.player
                    repaired_interactions = (
                        old_eval.missing_interactions
                        - current_eval.missing_interactions
                    )
                    cleared_avoidances = (
                        old_eval.violated_interactions
                        - current_eval.violated_interactions
                    )
                    repaired_jumps = sorted(
                        old_missing_jump_frames - current_missing_jump_frames
                    )
                    if repaired_interactions or cleared_avoidances or repaired_jumps:
                        repairs: list[str] = []
                        if repaired_interactions:
                            repairs.append(
                                "satisfied required interaction(s) "
                                + format_interaction_requirements(
                                    tuple(repaired_interactions)
                                )
                            )
                        if cleared_avoidances:
                            repairs.append(
                                "avoided forbidden interaction(s) "
                                + format_interaction_avoidances(
                                    tuple(cleared_avoidances)
                                )
                            )
                        if repaired_jumps:
                            repairs.append(
                                "repaired required jump press(es) "
                                + ", ".join(map(str, repaired_jumps))
                            )
                        remaining_interactions = format_interaction_requirements(
                            tuple(current_eval.missing_interactions)
                        )
                        remaining_avoidances = format_interaction_avoidances(
                            tuple(current_eval.violated_interactions)
                        )
                        remaining_jumps = (
                            ", ".join(
                                map(str, sorted(current_missing_jump_frames))
                            )
                            or "none"
                        )
                        message = (
                            f"{run_label}, pass {pass_index + 1}, "
                            f"{description}: {'; '.join(repairs)}; "
                            f"missing required interactions={remaining_interactions}; "
                            f"triggered forbidden interactions={remaining_avoidances}; "
                            f"remaining jumps={remaining_jumps}; "
                            f"score {old_score:.15g} -> {best_eval.score:.15g}; "
                            f"position=({p.pos.x:.15g}, {p.pos.y:.15g}); {symbols}"
                        )
                    else:
                        message = (
                            f"{run_label}, pass {pass_index + 1}, "
                            f"{description}: "
                            f"{old_score:.15g} -> {best_eval.score:.15g}; "
                            f"position=({p.pos.x:.15g}, {p.pos.y:.15g}); {symbols}"
                        )
                    if progress is not None:
                        progress(message)
                    if improvement_progress is not None:
                        # ``current`` continues to mutate as later windows are
                        # accepted.  Snapshot it now so a parent-side durable
                        # checkpoint always represents the exact evaluation
                        # carried by this event, even if the trajectory runs
                        # ahead before the event is consumed.
                        checkpoint_run = LocalSearchRunResult(
                            list(current),
                            current_eval,
                            run_label,
                            current_missing_jump_frames,
                            required_jump_frames,
                        )
                        improvement_progress(
                            _LocalImprovementEvent(
                                run_label=run_label,
                                message=message,
                                rank=_local_rank_from_evaluation(
                                    current_eval,
                                    current_missing_jump_frames,
                                    required_jump_frames,
                                ),
                                run=checkpoint_run,
                            )
                        )

        if not changed_this_pass:
            if progress is not None:
                if pass_index + 1 < passes and window_shape == "sparse":
                    progress(
                        f"{run_label}, pass {pass_index + 1}: no replay changes; "
                        "continuing because sparse windows are resampled next pass"
                    )
                elif pass_index + 1 < passes and window_shape == "mixed":
                    next_shape = _local_pass_window_shape(
                        window_shape, pass_index + 1
                    )
                    reason = (
                        "sparse windows are sampled next pass"
                        if next_shape == "sparse"
                        else "the next pass uses contiguous windows"
                    )
                    progress(
                        f"{run_label}, pass {pass_index + 1}: no replay changes; "
                        f"continuing because {reason}"
                    )
                else:
                    progress(f"{run_label}, pass {pass_index + 1}: no replay changes")
            # Contiguous passes revisit the exact same frame sets. With an
            # unchanged incumbent, another ordering of those same sets cannot
            # unlock anything. Sparse mode deliberately samples new sets next
            # pass, while mixed mode may still have a different shape or a
            # newly sampled sparse set ahead. Neither may terminate early.
            if window_shape == "contiguous":
                break

    # Accepted winners already carry either their native terminal view or, for
    # the opt-in debug path, the exact Python resimulation state. Do not add a
    # second trajectory-completion evaluation.
    final_eval = current_eval
    return LocalSearchRunResult(
        current,
        final_eval,
        run_label,
        current_missing_jump_frames,
        required_jump_frames,
    )


def optimise_local_windows(
    level: Level,
    original_frames: Sequence[InputFrame],
    *,
    target_frame: int,
    range_start: int,
    range_end: int,
    frame_ranges: Sequence[tuple[int, int]] | None = None,
    objective_name: str,
    objective_target: TargetSelection | None = None,
    window_size: int,
    passes: int,
    minimum_improvement: float = 0.0,
    x_window: AxisWindow | None = None,
    y_window: AxisWindow | None = None,
    local_inputs: str = "all",
    physics_prune: bool = False,
    window_order: str = "forward",
    window_shape: str = "contiguous",
    window_span: int | None = None,
    windows_per_pass: int | None = None,
    restarts: int = 10,
    seed: int | None = None,
    jump_start_mutation: int = 0,
    jump_length_mutation: int = 0,
    immutable_jumps: Sequence[ImmutableJumpSpec] = (),
    required_interactions: Sequence[InteractionRequirement] = (),
    avoided_interactions: Sequence[InteractionAvoidance] = (),
    require_reference_interactions: bool = False,
    workers: int = 1,
    progress: Callable[[str], None] | None = print,
    best_run_callback: Callable[[LocalSearchRunResult], bool | None] | None = None,
    python_resimulate: bool = False,
) -> tuple[list[InputFrame], Evaluation]:
    """Optimise overlapping local windows using one or more order trajectories.

    ``forward`` and ``reverse`` each run once from ``original_frames``.
    ``random`` performs ``restarts`` independent runs, each beginning from the
    same untouched replay and reshuffling the window starts on every pass.
    ``mixed`` compares one independent forward run, one independent reverse run,
    and ``restarts`` independent random runs. Ordinary local search returns the
    highest-ranked final replay. Required and forbidden persistent interactions
    are protected in both input modes. Direction-only search additionally
    protects required jump presses; hard repairs outrank the positional
    objective.

    ``frame_ranges`` may describe multiple disjoint inclusive mutable ranges;
    the legacy ``range_start``/``range_end`` pair remains the single-range
    default. Contiguous windows stay within one interval, while sparse windows
    sample from the union and leave every excluded gap fixed.

    ``window_shape='sparse'`` samples fresh sets of ``window_size`` mutable
    frames every pass instead of requiring them to be consecutive.
    ``window_shape='mixed'`` starts with a sparse pass, follows it with a
    contiguous pass, and repeats that alternation. Optional ``window_span``
    limits the inclusive width of each sampled set and ``windows_per_pass``
    controls how many distinct sets are tried on sparse passes. A supplied seed
    makes both sparse/mixed sampling and random ordering reproducible.

    Direction-only random/mixed search can additionally mutate complete jump
    pulses independently for each random restart. Start/length mutations are
    bounded integer offsets around the source pulse. Pulses named by source
    start frame in ``immutable_jumps`` retain the requested source property
    (start frame, hold length, or both) on every restart. An unmutated control
    trajectory is retained
    so enabling mutation cannot remove the original jump timing from the
    direction search.

    ``require_reference_interactions`` derives exact gold, exit-switch, and
    locked-TestDoor requirements from this function's input replay through the
    target frame. This is therefore the post-retime, pre-restart reference when
    called by the CLI. Explicit and reference-derived requirements are merged.

    ``workers`` controls process parallelism between independent trajectories.
    Forward, reverse, and random runs share one ordered pool when several are
    present; each trajectory calls its native search session in-process for its
    greedy window chain. ``0`` selects a cost-aware automatic trajectory count
    and ``1`` keeps the unconditional low-overhead serial path. Worker results
    are merged in original run-spec order.

    ``best_run_callback`` is called in the parent process whenever an accepted
    window improvement becomes the best checkpoint candidate so far under the
    same local-run ranking used for final selection. Completed independent
    trajectories are also offered as a fallback, covering jump-mutated starting
    replays that make no later window improvement. This is intended for durable
    live checkpointing: parallel worker processes never write shared output
    files themselves. A callback may return ``False`` to reject a candidate
    after clean output verification; that candidate then does not prevent a
    later, lower-ranked but valid trajectory from being offered. ``None`` keeps
    the historical accepted-callback behaviour. The deterministic final winner
    is still merged in run-spec order.

    ``python_resimulate`` is an opt-in diagnostic. When true, every accepted
    native winner is replayed through the Python reference emulator and all
    exported player, score, feasibility, interaction and jump fields are
    compared exactly. It is false by default so result adaptation stays out of
    the simulation hot path.
    """
    if window_size < 1:
        raise ValueError("window size must be at least 1")
    if passes < 1:
        raise ValueError("passes must be at least 1")
    if local_inputs not in ("all", "direction"):
        raise ValueError("local_inputs must be 'all' or 'direction'")
    if physics_prune and local_inputs != "direction":
        raise ValueError(
            "physics pruning is only available for direction-only local search"
        )
    if window_order not in ("forward", "reverse", "random", "mixed"):
        raise ValueError(
            "window_order must be 'forward', 'reverse', 'random' or 'mixed'"
        )
    if window_shape not in ("contiguous", "sparse", "mixed"):
        raise ValueError(
            "window_shape must be 'contiguous', 'sparse' or 'mixed'"
        )
    if window_span is not None and window_span < 1:
        raise ValueError("window span must be at least 1")
    if windows_per_pass is not None and windows_per_pass < 1:
        raise ValueError("windows per pass must be at least 1")
    if window_shape == "contiguous" and window_span is not None:
        raise ValueError(
            "window_span is only available with sparse or mixed windows"
        )
    if window_shape == "contiguous" and windows_per_pass is not None:
        raise ValueError(
            "windows_per_pass is only available with sparse or mixed windows"
        )
    if restarts < 1:
        raise ValueError("restarts must be at least 1")
    if workers < 0:
        raise ValueError("workers must be zero (auto) or a positive integer")
    if jump_start_mutation < 0 or jump_length_mutation < 0:
        raise ValueError("jump mutation values must be non-negative")
    jump_mutation_enabled = jump_start_mutation > 0 or jump_length_mutation > 0
    if immutable_jumps and not jump_mutation_enabled:
        raise ValueError(
            "--immutable-jumps requires --jump-start-mutation or "
            "--jump-length-mutation"
        )
    if jump_mutation_enabled and local_inputs != "direction":
        raise ValueError("jump mutation is only available for direction-only local search")
    if jump_mutation_enabled and window_order not in ("random", "mixed"):
        raise ValueError(
            "jump mutation requires --window-order random or mixed so each restart "
            "can receive an independent mutation"
        )
    normalized_ranges = _normalise_local_frame_ranges(
        range_start, range_end, frame_ranges
    )
    range_start = normalized_ranges[0][0]
    range_end = normalized_ranges[-1][1]
    if target_frame < range_end:
        raise ValueError("target frame cannot be before the end of the local range")
    if target_frame >= len(original_frames):
        raise ValueError("target frame lies outside the replay")
    immutable_jump_map = validate_immutable_jumps(
        original_frames,
        range_start=range_start,
        range_end=range_end,
        immutable_jumps=immutable_jumps,
    )
    immutable_in_gaps = [
        spec.start_frame
        for spec in immutable_jumps
        if not _frame_in_local_ranges(spec.start_frame, normalized_ranges)
    ]
    if immutable_in_gaps:
        raise ValueError(
            "immutable jump frame(s) must lie within one of the local ranges: "
            + ", ".join(map(str, immutable_in_gaps))
        )

    range_length = _local_range_length(normalized_ranges)
    effective_window = min(window_size, range_length)
    if (
        window_shape in ("sparse", "mixed")
        and window_span is not None
        and window_span < effective_window
    ):
        raise ValueError(
            "sparse window span must be at least the number of mutable frames "
            f"({effective_window})"
        )
    if window_shape in ("sparse", "mixed") and len(normalized_ranges) > 1:
        sparse_capacity = _sparse_window_capacity_for_frames(
            _local_range_frames(normalized_ranges),
            effective_window,
            window_span,
        )
        if sparse_capacity == 0:
            raise ValueError(
                "no sparse window can select the requested number of mutable "
                "frames within the configured span"
            )

    objective = objective_function(objective_name, objective_target)
    original = editable_frames(original_frames)
    required_jump_frames = (
        jump_press_frames(original, target_frame)
        if local_inputs == "direction"
        else frozenset()
    )
    # If the preserved jump stream contains no rising edge, the baseline
    # evaluation does not need to inspect the jump-event counter on every
    # frame.  This keeps the ordinary direction-only baseline on the cheaper
    # replay path while retaining exact collection whenever a requirement
    # exists.
    baseline_successful_jump_events: set[int] | None = (
        set() if required_jump_frames else None
    )
    baseline = evaluate(
        level,
        original,
        target_frame,
        objective,
        x_window=x_window,
        y_window=y_window,
        successful_jump_frames_out=baseline_successful_jump_events,
    )
    explicit_interactions = tuple(required_interactions)
    reference_interactions = (
        reference_interaction_requirements(level, baseline.state)
        if require_reference_interactions
        else ()
    )
    all_required_interactions = merge_interaction_requirements(
        explicit_interactions, reference_interactions
    )
    all_avoided_interactions = merge_interaction_avoidances(
        tuple(avoided_interactions)
    )
    (
        baseline.missing_interactions,
        baseline.violated_interactions,
    ) = interaction_constraint_status(
        all_required_interactions,
        all_avoided_interactions,
        baseline.state,
    )
    baseline_successful_jump_frames = (
        frozenset(baseline_successful_jump_events)
        if baseline_successful_jump_events is not None
        else frozenset()
    )
    baseline_missing_jump_frames = (
        required_jump_frames - baseline_successful_jump_frames
        if local_inputs == "direction"
        else frozenset()
    )

    if progress is not None:
        p = baseline.state.player
        progress(
            f"baseline: score={baseline.score:.17g}, "
            f"position=({p.pos.x:.15g}, {p.pos.y:.15g}), "
            f"within-window={baseline.feasible}"
        )
        if all_required_interactions:
            progress("required interactions:")
            progress(
                "  explicit: "
                + format_interaction_requirements(explicit_interactions)
            )
            progress(
                "  from reference: "
                + format_interaction_requirements(reference_interactions)
            )
            baseline_satisfied_interactions = tuple(
                requirement
                for requirement in all_required_interactions
                if requirement not in baseline.missing_interactions
            )
            progress(
                "baseline satisfied interactions: "
                + format_interaction_requirements(
                    baseline_satisfied_interactions
                )
            )
            progress(
                "baseline missing interactions: "
                + format_interaction_requirements(
                    tuple(baseline.missing_interactions)
                )
            )
        if all_avoided_interactions:
            progress(
                "forbidden interactions: "
                + format_interaction_avoidances(all_avoided_interactions)
            )
            baseline_avoided_interactions = tuple(
                avoidance
                for avoidance in all_avoided_interactions
                if avoidance not in baseline.violated_interactions
            )
            progress(
                "baseline avoided forbidden interactions: "
                + format_interaction_avoidances(baseline_avoided_interactions)
            )
            progress(
                "baseline triggered forbidden interactions: "
                + format_interaction_avoidances(
                    tuple(baseline.violated_interactions)
                )
            )
        if local_inputs == "direction":
            required_text = ", ".join(map(str, sorted(required_jump_frames))) or "none"
            successful_required_text = (
                ", ".join(
                    map(
                        str,
                        sorted(required_jump_frames & baseline_successful_jump_frames),
                    )
                )
                or "none"
            )
            missing_text = (
                ", ".join(map(str, sorted(baseline_missing_jump_frames))) or "none"
            )
            progress(
                "direction-only local search: preserving held-jump inputs"
            )
            if immutable_jump_map:
                immutable_text = ", ".join(
                    f"{frame}:{immutable_jump_map[frame].mode}"
                    for frame in sorted(immutable_jump_map)
                )
                progress(f"immutable source jumps: {immutable_text}")
            progress(f"required jump-press frames: {required_text}")
            progress(
                "baseline successful required jumps: "
                f"{successful_required_text}"
            )
            progress(
                f"baseline missed required jump presses: {missing_text}"
            )
            if physics_prune:
                progress(
                    "physics pruning enabled: horizontal bounds assume no future "
                    "object/collision-derived horizontal boosts; existing overspeed "
                    "and ordinary jump-edge impulses are allowed conservatively"
                )
                if objective_name not in ("max-x", "min-x") and x_window is None:
                    progress(
                        "physics pruning note: no horizontal objective/x-window is "
                        "present, so only safe jump/death/state pruning can apply"
                    )

    master_seed: int | None = seed
    randomness_needed = (
        window_order in ("random", "mixed")
        or window_shape in ("sparse", "mixed")
    )
    if randomness_needed:
        if master_seed is None:
            master_seed = random.SystemRandom().randrange(0, 2**63)
        if progress is not None:
            if window_shape in ("sparse", "mixed"):
                progress(f"random local-window seed: {master_seed}")
            else:
                progress(f"random window-order seed: {master_seed}")

    # Each run spec carries an independent window RNG and, when enabled, a
    # separate jump-mutation RNG. Mutation therefore cannot perturb the random
    # window stream. With mutation disabled this construction preserves v1.4's
    # contiguous seeded restart seeds exactly.
    run_specs: list[_LocalRunSpec] = []
    if window_shape == "contiguous":
        # Preserve the v0.8-v1.4 RNG stream exactly for ordinary contiguous
        # searches so existing seeded commands remain bit-for-bit reproducible.
        if window_order == "forward":
            run_specs.append(_LocalRunSpec("forward", None, "forward", None))
        elif window_order == "reverse":
            run_specs.append(_LocalRunSpec("reverse", None, "reverse", None))
        else:
            if window_order == "mixed":
                run_specs.append(
                    _LocalRunSpec("forward", None, "mixed forward", None)
                )
                run_specs.append(
                    _LocalRunSpec("reverse", None, "mixed reverse", None)
                )
            assert master_seed is not None
            master_rng = random.Random(master_seed)
            random_specs: list[_LocalRunSpec] = []
            for restart_index in range(restarts):
                restart_seed = master_rng.getrandbits(64)
                jump_rng = None
                jump_seed_text = ""
                if jump_mutation_enabled:
                    jump_seed = random.Random(
                        f"{master_seed}:jump:{restart_index}"
                    ).getrandbits(64)
                    jump_rng = random.Random(jump_seed)
                    jump_seed_text = f", jump-seed={jump_seed}"
                random_specs.append(
                    _LocalRunSpec(
                        "random",
                        random.Random(restart_seed),
                        f"random restart {restart_index + 1}/{restarts} "
                        f"(seed={restart_seed}{jump_seed_text})",
                        jump_rng,
                    )
                )
            if jump_mutation_enabled and window_order == "random":
                # Give the original jump timing a full direction-optimisation run
                # using exactly restart 1's window trajectory for a fair control.
                first_seed = random.Random(master_seed).getrandbits(64)
                run_specs.append(
                    _LocalRunSpec(
                        "random",
                        random.Random(first_seed),
                        f"unmutated control (seed={first_seed})",
                        None,
                    )
                )
            run_specs.extend(random_specs)
    else:
        assert master_seed is not None

        def sampled_window_rng(tag: str) -> tuple[random.Random, int]:
            # String seeding is deterministic in Python's version-2 RNG seed
            # algorithm and keeps random restart N identical between random and
            # mixed window order for both sparse and mixed window shapes.
            stream_seed = random.Random(f"{master_seed}:{tag}").getrandbits(64)
            return random.Random(stream_seed), stream_seed

        if window_order == "forward":
            rng, _stream_seed = sampled_window_rng("forward")
            run_specs.append(_LocalRunSpec("forward", rng, "forward", None))
        elif window_order == "reverse":
            rng, _stream_seed = sampled_window_rng("reverse")
            run_specs.append(_LocalRunSpec("reverse", rng, "reverse", None))
        else:
            if window_order == "mixed":
                forward_rng, _ = sampled_window_rng("forward")
                reverse_rng, _ = sampled_window_rng("reverse")
                run_specs.append(
                    _LocalRunSpec("forward", forward_rng, "mixed forward", None)
                )
                run_specs.append(
                    _LocalRunSpec("reverse", reverse_rng, "mixed reverse", None)
                )
            random_specs = []
            for restart_index in range(restarts):
                restart_rng, restart_seed = sampled_window_rng(
                    f"random:{restart_index}"
                )
                jump_rng = None
                jump_seed_text = ""
                if jump_mutation_enabled:
                    jump_seed = random.Random(
                        f"{master_seed}:jump:{restart_index}"
                    ).getrandbits(64)
                    jump_rng = random.Random(jump_seed)
                    jump_seed_text = f", jump-seed={jump_seed}"
                random_specs.append(
                    _LocalRunSpec(
                        "random",
                        restart_rng,
                        f"random restart {restart_index + 1}/{restarts} "
                        f"(seed={restart_seed}{jump_seed_text})",
                        jump_rng,
                    )
                )
            if jump_mutation_enabled and window_order == "random":
                control_rng, control_seed = sampled_window_rng("random:0")
                run_specs.append(
                    _LocalRunSpec(
                        "random",
                        control_rng,
                        f"unmutated control (seed={control_seed})",
                        None,
                    )
                )
            run_specs.extend(random_specs)

    best_run = LocalSearchRunResult(
        original,
        baseline,
        "original baseline",
        baseline_missing_jump_frames,
        required_jump_frames,
    )
    run_context = _LocalRunContext(
        level=level,
        original_frames=tuple(original),
        target_frame=target_frame,
        range_start=range_start,
        range_end=range_end,
        frame_ranges=normalized_ranges,
        objective_name=objective_name,
        objective_target=objective_target,
        window_size=window_size,
        passes=passes,
        minimum_improvement=minimum_improvement,
        x_window=x_window,
        y_window=y_window,
        local_inputs=local_inputs,
        physics_prune=physics_prune,
        window_shape=window_shape,
        window_span=window_span,
        windows_per_pass=windows_per_pass,
        jump_start_mutation=jump_start_mutation,
        jump_length_mutation=jump_length_mutation,
        immutable_jumps=tuple(immutable_jumps),
        immutable_jump_map=immutable_jump_map,
        required_jump_frames=required_jump_frames,
        required_interactions=tuple(all_required_interactions),
        avoided_interactions=tuple(all_avoided_interactions),
        baseline=baseline,
        baseline_missing_jump_frames=baseline_missing_jump_frames,
        python_resimulate=python_resimulate,
    )

    checkpoint_best_run = best_run

    def checkpoint_candidate(run: LocalSearchRunResult) -> None:
        nonlocal checkpoint_best_run
        if not _local_run_better(run, checkpoint_best_run):
            return
        if best_run_callback is not None and best_run_callback(run) is False:
            return
        checkpoint_best_run = run

    def consume_run(run: LocalSearchRunResult) -> None:
        nonlocal best_run
        if _local_run_better(run, best_run):
            best_run = run

    estimated_run_work = _estimate_local_run_work(
        target_frame=target_frame,
        range_start=range_start,
        range_end=range_end,
        frame_ranges=normalized_ranges,
        window_size=window_size,
        passes=passes,
        local_inputs=local_inputs,
        window_shape=window_shape,
        windows_per_pass=windows_per_pass,
    )

    # Every trajectory starts from the untouched replay. Mixed forward/reverse
    # runs are therefore just as independent as random restarts and share one
    # ordered pool. Each trajectory owns one native search session.
    trajectory_workers = (
        _automatic_local_trajectory_workers(
            len(run_specs), estimated_run_work=estimated_run_work
        )
        if workers == 0
        else workers
    )
    if trajectory_workers > 1 and len(run_specs) > 1:
        actual_workers = min(trajectory_workers, len(run_specs))
        if progress is not None:
            progress(
                f"local search: {actual_workers} worker processes, "
                f"{len(run_specs)} independent trajectories"
            )
        mp_context = multiprocessing.get_context()
        # Queue.put() uses a feeder thread in every producing process. Abruptly
        # terminating local workers after Ctrl+C can close the Windows pipe
        # underneath those threads, producing noisy WinError 6 / closed-handle
        # tracebacks. SimpleQueue writes synchronously and has no feeder thread;
        # accepted-improvement traffic is sparse enough that its direct pipe
        # writes do not affect the search hot path.
        progress_queue = (
            mp_context.SimpleQueue()
            if progress is not None or best_run_callback is not None
            else None
        )
        live_best_rank = _local_rank_from_run(best_run)

        delivered_improvements_by_run: dict[str, int] = {}

        def deliver_worker_improvement(event: _LocalImprovementEvent) -> None:
            nonlocal live_best_rank
            delivered_improvements_by_run[event.run_label] = (
                delivered_improvements_by_run.get(event.run_label, 0) + 1
            )
            checkpoint_candidate(event.run)
            if not _local_rank_better(event.rank, live_best_rank):
                return
            live_best_rank = event.rank
            if progress is not None:
                progress(event.message + " [NEW BEST SO FAR]")

        def flush_completed_run_improvements(
            run: LocalSearchRunResult,
            expected_count: int,
        ) -> int:
            """Deliver a completed run's queued improvements before its summary."""
            if progress_queue is None:
                return 0
            delivered = 0
            while delivered_improvements_by_run.get(run.label, 0) < expected_count:
                deliver_worker_improvement(progress_queue.get())
                delivered += 1
            return delivered

        try:
            with _LocalExecutorScope(
                ProcessPoolExecutor(
                    max_workers=actual_workers,
                    mp_context=mp_context,
                    initializer=_initialise_local_worker,
                    initargs=(run_context, progress_queue),
                )
            ) as executor:
                futures = [
                    executor.submit(_run_local_work_item, spec)
                    for spec in run_specs
                ]
                future_indices = {
                    future: index for index, future in enumerate(futures)
                }
                worker_results: list[tuple[LocalSearchRunResult, int] | None] = [
                    None
                ] * len(futures)
                pending = set(futures)
                delivered_improvements = 0
                while pending:
                    if progress_queue is not None:
                        delivered_improvements += _drain_local_worker_progress(
                            progress_queue, deliver_worker_improvement
                        )
                    done, pending = wait(
                        pending,
                        timeout=0.05,
                        return_when=FIRST_COMPLETED,
                    )
                    # ``wait`` returns a set, so use run-spec order only to make
                    # simultaneous completions deterministic. Across polling
                    # iterations, checkpoints still happen as soon as completed
                    # trajectories are observed by the parent.
                    for future in sorted(done, key=future_indices.__getitem__):
                        result = future.result()
                        worker_results[future_indices[future]] = result
                        run, improvement_count = result
                        delivered_improvements += flush_completed_run_improvements(
                            run, improvement_count
                        )
                        checkpoint_candidate(run)
                        if progress is not None:
                            progress(
                                f"finished {run.label}: "
                                f"best score={run.evaluation.score:.17g}"
                            )
                completed_worker_results = [
                    result for result in worker_results if result is not None
                ]
                if progress_queue is not None:
                    delivered_improvements += _drain_local_worker_progress(
                        progress_queue, deliver_worker_improvement
                    )
                    expected_improvements = sum(
                        improvement_count
                        for _run, improvement_count in completed_worker_results
                    )
                    while delivered_improvements < expected_improvements:
                        deliver_worker_improvement(progress_queue.get())
                        delivered_improvements += 1
                # Merge in run-spec order just like executor.map() did in v2.55,
                # preserving deterministic tie handling between trajectories.
                for result in worker_results:
                    assert result is not None
                    run, _improvement_count = result
                    consume_run(run)
        finally:
            if progress_queue is not None:
                progress_queue.close()
    else:
        for spec in run_specs:
            run = _execute_local_run(
                run_context,
                spec,
                progress,
                improvement_progress=(
                    (lambda event: checkpoint_candidate(event.run))
                    if best_run_callback is not None
                    else None
                ),
            )
            checkpoint_candidate(run)
            consume_run(run)

    if progress is not None and len(run_specs) > 1:
        interaction_text = format_interaction_requirements(
            tuple(best_run.evaluation.missing_interactions)
        )
        avoidance_text = format_interaction_avoidances(
            tuple(best_run.evaluation.violated_interactions)
        )
        if local_inputs == "direction":
            missing_text = (
                ", ".join(
                    map(str, sorted(best_run.missing_required_jump_frames))
                )
                or "none"
            )
            progress(
                f"best local-search trajectory: {best_run.label}; "
                f"missing-interactions={interaction_text}; "
                f"triggered-forbidden-interactions={avoidance_text}; "
                f"missed-required-jumps={missing_text}; "
                f"score={best_run.evaluation.score:.17g}"
            )
        else:
            progress(
                f"best local-search trajectory: {best_run.label}; "
                f"missing-interactions={interaction_text}; "
                f"triggered-forbidden-interactions={avoidance_text}; "
                f"score={best_run.evaluation.score:.17g}"
            )

    if best_run.evaluation.missing_interactions:
        missing_text = format_interaction_requirements(
            tuple(best_run.evaluation.missing_interactions)
        )
        raise RuntimeError(
            "local optimisation could not satisfy all required interactions; "
            f"remaining: {missing_text}. Try a larger window, wider optimisation "
            "range, more passes, sparse windows, or additional random restarts."
        )
    if best_run.evaluation.violated_interactions:
        violated_text = format_interaction_avoidances(
            tuple(best_run.evaluation.violated_interactions)
        )
        raise RuntimeError(
            "local optimisation could not avoid all forbidden interactions; "
            f"triggered: {violated_text}. Try a larger window, wider optimisation "
            "range, more passes, sparse windows, or additional random restarts."
        )
    if local_inputs == "direction" and best_run.missing_required_jump_frames:
        missing_text = ", ".join(
            map(str, sorted(best_run.missing_required_jump_frames))
        )
        raise RuntimeError(
            "direction-only optimisation could not satisfy all required jump-button "
            f"presses; remaining missed jump frames: {missing_text}. Try a larger "
            "window, wider optimisation range, more passes, or additional random "
            "restarts."
        )
    return best_run.frames, best_run.evaluation

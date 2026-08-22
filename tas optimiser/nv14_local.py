"""Sliding-window local replay search and its multiprocessing workers."""
from __future__ import annotations

import math
import multiprocessing
import random
import signal
from bisect import bisect_right
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass

from nv14_engine import (
    InputFrame,
    LaunchPad,
    Level,
    PlayerState,
    SimulationState,
    UnsupportedTileCollision,
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
    _avoided_interactions_triggered,
    _compile_interaction_constraints,
    _CompiledInteractionConstraints,
    _evaluation_with_interactions,
    evaluate,
    format_interaction_avoidances,
    format_interaction_requirements,
    interaction_constraint_status,
    merge_interaction_avoidances,
    merge_interaction_requirements,
    objective_function,
    position_within_windows,
    reference_interaction_requirements,
    state_before_frame,
)
from nv14_replay import editable_frames, input_symbol


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


@dataclass(slots=True)
class DirectionWindowStats:
    """Counters for one direction-only local-window search."""

    visited_nodes: int = 0
    evaluated_leaves: int = 0
    missed_jump_prunes: int = 0
    dead_prunes: int = 0
    deduplicated_prunes: int = 0
    physics_prunes: int = 0
    avoided_interaction_prunes: int = 0

    def add(self, other: "DirectionWindowStats") -> None:
        """Merge counters from an independently searched frontier batch."""
        self.visited_nodes += other.visited_nodes
        self.evaluated_leaves += other.evaluated_leaves
        self.missed_jump_prunes += other.missed_jump_prunes
        self.dead_prunes += other.dead_prunes
        self.deduplicated_prunes += other.deduplicated_prunes
        self.physics_prunes += other.physics_prunes
        self.avoided_interaction_prunes += other.avoided_interaction_prunes


@dataclass(slots=True)
class AllInputWindowStats:
    """Counters for one all-input local-window DFS."""

    visited_nodes: int = 0
    evaluated_leaves: int = 0
    inactive_jump_prunes: int = 0
    dead_prunes: int = 0
    deduplicated_prunes: int = 0
    avoided_interaction_prunes: int = 0

    def add(self, other: "AllInputWindowStats") -> None:
        """Merge counters from an independently searched frontier batch."""
        self.visited_nodes += other.visited_nodes
        self.evaluated_leaves += other.evaluated_leaves
        self.inactive_jump_prunes += other.inactive_jump_prunes
        self.dead_prunes += other.dead_prunes
        self.deduplicated_prunes += other.deduplicated_prunes
        self.avoided_interaction_prunes += other.avoided_interaction_prunes


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


def _local_candidate_better(
    candidate_eval: Evaluation,
    candidate_missing_jump_frames: frozenset[int],
    best_eval: Evaluation,
    best_missing_jump_frames: frozenset[int],
    *,
    incumbent_eval: Evaluation,
    incumbent_missing_jump_frames: frozenset[int],
) -> bool:
    """Compare local candidates without allowing hard-requirement exchanges.

    A candidate may only remove requirements from the current incumbent's
    missing sets; it may not exchange one required object/jump for another.
    Feasibility comes first. A candidate then replaces the current best only if
    its missing-interaction, forbidden-interaction, and missing-jump sets all
    weakly improve on the best, with at least one strict improvement.
    Incomparable candidates are not exchanged. Objective score only breaks a
    tie between identical hard states.
    """
    if not candidate_eval.feasible:
        return False
    if not candidate_eval.missing_interactions <= incumbent_eval.missing_interactions:
        return False
    if not (
        candidate_eval.violated_interactions
        <= incumbent_eval.violated_interactions
    ):
        return False
    if not candidate_missing_jump_frames <= incumbent_missing_jump_frames:
        return False
    if not best_eval.feasible:
        return True

    candidate_dominates = (
        candidate_eval.missing_interactions <= best_eval.missing_interactions
        and candidate_eval.violated_interactions
        <= best_eval.violated_interactions
        and candidate_missing_jump_frames <= best_missing_jump_frames
    )
    best_dominates = (
        best_eval.missing_interactions <= candidate_eval.missing_interactions
        and best_eval.violated_interactions
        <= candidate_eval.violated_interactions
        and best_missing_jump_frames <= candidate_missing_jump_frames
    )
    if candidate_dominates and not best_dominates:
        return True
    if best_dominates and not candidate_dominates:
        return False
    if candidate_dominates and best_dominates:
        return candidate_eval.score > best_eval.score
    return False


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


def _direction_frame(frame: InputFrame, horizontal: int) -> InputFrame:
    """Replace only left/right input while preserving held jump exactly."""
    if horizontal not in (-1, 0, 1):
        raise ValueError("horizontal direction must be -1, 0 or 1")
    return InputFrame(horizontal < 0, horizontal > 0, frame.jump, None)


def _future_jump_edge_frames(
    frames: Sequence[InputFrame], *, start_frame: int, target_frame: int
) -> frozenset[int]:
    """Potential ordinary jump-trigger frames from the fixed held-jump inputs."""
    if start_frame > target_frame:
        return frozenset()
    previous = frames[start_frame - 1].jump if start_frame > 0 else False
    result: set[int] = set()
    for frame_index in range(start_frame, target_frame + 1):
        held = frames[frame_index].jump
        if held and not previous:
            result.add(frame_index)
        previous = held
    return frozenset(result)


def optimistic_horizontal_bounds(
    state: SimulationState,
    frames: Sequence[InputFrame],
    *,
    target_frame: int,
    jump_edges: frozenset[int] | None = None,
) -> tuple[float, float]:
    """Optimistic target-frame x bounds for optional branch-and-bound.

    This deliberately gives the player more horizontal authority than ordinary
    movement: every future frame may use twice ground acceleration (covering the
    extra slope-running adjustment), controlled speed may reach the nominal
    maximum immediately, and every future jump-button rising edge may supply a
    maximally favourable 1.5-pixel wall-jump impulse. Existing overspeed is
    retained. Object/collision-derived horizontal boosts are *not* modelled; the
    caller exposes this limitation explicitly via ``--physics-prune``.
    """
    next_frame = state.frame
    if next_frame > target_frame:
        x = state.player.pos.x
        return x, x

    player = state.player
    if jump_edges is None:
        jump_edges = _future_jump_edge_frames(
            frames, start_frame=next_frame, target_frame=target_frame
        )
    max_speed = max(player.maxspeed_ground, player.maxspeed_air)
    # Source ground handling can apply the main ground acceleration and then a
    # slope-tangent adjustment. 2x is a simple conservative envelope.
    accel = 2.0 * player.ground_accel
    jump_dx = 1.5 * player.jump_amt

    def project(direction: int) -> float:
        x = player.pos.x
        v = player.pos.x - player.oldpos.x
        for frame_index in range(next_frame, target_frame + 1):
            # TickNormal drag/integration happens before control handling.
            v *= player.d
            x += v

            # Give the branch maximally favourable controlled acceleration.
            if direction > 0:
                if v < max_speed:
                    v = min(max_speed, v + accel)
            else:
                if v > -max_speed:
                    v = max(-max_speed, v - accel)

            # A fixed rising edge may become a successful floor/wall jump after
            # direction changes. Give every such edge the strongest possible
            # horizontal ordinary-jump impulse.
            if frame_index in jump_edges:
                x += direction * jump_dx
                if direction > 0:
                    v = max(jump_dx, v + jump_dx)
                else:
                    v = min(-jump_dx, v - jump_dx)
        return x

    lower = project(-1)
    upper = project(1)
    return min(lower, upper), max(lower, upper)


def _loose_horizontal_bounds(
    state: SimulationState,
    frames: Sequence[InputFrame],
    *,
    target_frame: int,
    jump_edges: frozenset[int] | None = None,
) -> tuple[float, float]:
    """Very cheap, deliberately loose pre-bound used before the tight projection."""
    remaining = target_frame + 1 - state.frame
    x = state.player.pos.x
    if remaining <= 0:
        return x, x
    player = state.player
    if jump_edges is None:
        jump_edges = _future_jump_edge_frames(
            frames, start_frame=state.frame, target_frame=target_frame
        )
    edges = sum(1 for frame_index in jump_edges if frame_index >= state.frame)
    jump_dx = 1.5 * player.jump_amt
    vx = player.pos.x - player.oldpos.x
    base_speed = max(player.maxspeed_ground, player.maxspeed_air, abs(vx))
    speed_envelope = base_speed + edges * jump_dx
    displacement = remaining * speed_envelope + edges * jump_dx
    return x - displacement, x + displacement


def _horizontal_bound_can_improve(
    lower_x: float,
    upper_x: float,
    *,
    objective_name: str,
    best_score: float,
    x_window: AxisWindow | None,
) -> bool:
    """Whether an optimistic x interval can still be feasible/usefully better."""
    feasible_low = lower_x
    feasible_high = upper_x
    if x_window is not None:
        feasible_low = max(feasible_low, x_window.minimum)
        feasible_high = min(feasible_high, x_window.maximum)
        if feasible_low > feasible_high:
            return False

    if best_score == float("-inf"):
        return True
    if objective_name == "max-x":
        return feasible_high > best_score
    if objective_name == "min-x":
        return -feasible_low > best_score
    # Horizontal bounds cannot bound a y objective; x-window feasibility above
    # is still useful when supplied.
    return True


def _physics_bound_allows_branch(
    state: SimulationState,
    frames: Sequence[InputFrame],
    *,
    target_frame: int,
    objective_name: str,
    best_score: float,
    x_window: AxisWindow | None,
    jump_edges: frozenset[int] | None = None,
) -> bool:
    """Two-stage optional horizontal branch-and-bound test."""
    if objective_name not in ("max-x", "min-x") and x_window is None:
        return True

    loose_low, loose_high = _loose_horizontal_bounds(
        state, frames, target_frame=target_frame, jump_edges=jump_edges
    )
    if not _horizontal_bound_can_improve(
        loose_low,
        loose_high,
        objective_name=objective_name,
        best_score=best_score,
        x_window=x_window,
    ):
        return False

    tight_low, tight_high = optimistic_horizontal_bounds(
        state, frames, target_frame=target_frame, jump_edges=jump_edges
    )
    return _horizontal_bound_can_improve(
        tight_low,
        tight_high,
        objective_name=objective_name,
        best_score=best_score,
        x_window=x_window,
    )


def _evaluate_direction_suffix(
    level: Level,
    state: SimulationState,
    frames: Sequence[InputFrame],
    *,
    start_frame: int,
    target_frame: int,
    objective: Callable[[SimulationState], float],
    required_jump_frames: frozenset[int],
    allowed_missing_jump_frames: frozenset[int],
    initial_missing_jump_frames: frozenset[int] = frozenset(),
    required_suffix_frames: Sequence[int] | None = None,
    x_window: AxisWindow | None,
    y_window: AxisWindow | None,
    required_interactions: Sequence[InteractionRequirement] = (),
    avoided_interactions: Sequence[InteractionAvoidance] = (),
    compiled_constraints: _CompiledInteractionConstraints | None = None,
) -> tuple[Evaluation, frozenset[int], bool]:
    """Replay a suffix while distinguishing old and newly-created jump misses.

    A required press already missed by the incumbent may remain missed while a
    local window attempts to repair other presses. Missing a required press that
    currently succeeds is a new regression and is pruned immediately.

    ``state`` is owned by the leaf that calls this helper. Mutating it in place
    avoids a redundant full branch clone; callers never reuse that leaf state.
    """
    result_state = state
    tiles = level.tiles
    step = result_state.step
    missing = set(initial_missing_jump_frames)
    if compiled_constraints is None:
        compiled_constraints = _compile_interaction_constraints(
            tuple(required_interactions), tuple(avoided_interactions)
        )
    # Direction-only required jumps are held-input rising edges, so almost all
    # suffix frames are ordinary fixed-input ticks.  Keep the hot ordinary
    # spans free of jump-event reads and set membership checks; only inspect
    # jump_events on frames that can actually add a required miss.
    if required_suffix_frames is None:
        required_suffix_frames = tuple(
            frame_index
            for frame_index in sorted(required_jump_frames)
            if start_frame <= frame_index <= target_frame
        )

    if not required_suffix_frames:
        # Most direction windows have no required jump edge in their fixed
        # suffix.  Keep that ordinary-input path free of the per-leaf missing
        # set and required-frame loop; the incumbent's missing set cannot
        # change once there are no required frames left to tick.
        try:
            for frame_index in range(start_frame, target_frame + 1):
                step(frames[frame_index], tiles)
                if (
                    compiled_constraints.avoidances
                    and _avoided_interactions_triggered(
                        compiled_constraints, result_state
                    )
                ):
                    return (
                        Evaluation(float("-inf"), result_state, False),
                        initial_missing_jump_frames,
                        False,
                    )
                if result_state.player.dead:
                    return (
                        _evaluation_with_interactions(
                            float("-inf"), result_state, False,
                            required_interactions, avoided_interactions,
                            compiled_constraints=compiled_constraints,
                        ),
                        initial_missing_jump_frames,
                        False,
                    )
        except UnsupportedTileCollision:
            return (
                _evaluation_with_interactions(
                    float("-inf"), result_state, False,
                    required_interactions, avoided_interactions,
                    compiled_constraints=compiled_constraints,
                ),
                initial_missing_jump_frames,
                False,
            )

        feasible = position_within_windows(
            result_state, x_window=x_window, y_window=y_window
        )
        return (
            _evaluation_with_interactions(
                objective(result_state) if feasible else float("-inf"),
                result_state,
                feasible,
                required_interactions,
                avoided_interactions,
                compiled_constraints=compiled_constraints,
            ),
            initial_missing_jump_frames,
            False,
        )

    try:
        next_frame = start_frame
        for required_frame in required_suffix_frames:
            for frame_index in range(next_frame, required_frame):
                step(frames[frame_index], tiles)
                if (
                    compiled_constraints.avoidances
                    and _avoided_interactions_triggered(
                        compiled_constraints, result_state
                    )
                ):
                    return (
                        Evaluation(float("-inf"), result_state, False),
                        frozenset(missing),
                        False,
                    )
                if result_state.player.dead:
                    return (
                        _evaluation_with_interactions(
                            float("-inf"), result_state, False,
                            required_interactions, avoided_interactions,
                            compiled_constraints=compiled_constraints,
                        ),
                        frozenset(missing),
                        False,
                    )

            before_events = result_state.player.jump_events
            step(frames[required_frame], tiles)
            if (
                compiled_constraints.avoidances
                and _avoided_interactions_triggered(compiled_constraints, result_state)
            ):
                return (
                    Evaluation(float("-inf"), result_state, False),
                    frozenset(missing),
                    False,
                )
            jumped = result_state.player.jump_events > before_events
            if not jumped:
                if required_frame not in allowed_missing_jump_frames:
                    return (
                        _evaluation_with_interactions(
                            float("-inf"), result_state, False,
                            required_interactions, avoided_interactions,
                            compiled_constraints=compiled_constraints,
                        ),
                        frozenset(missing),
                        True,
                    )
                missing.add(required_frame)
            if result_state.player.dead:
                return (
                    _evaluation_with_interactions(
                        float("-inf"), result_state, False,
                        required_interactions, avoided_interactions,
                        compiled_constraints=compiled_constraints,
                    ),
                    frozenset(missing),
                    False,
                )
            next_frame = required_frame + 1

        for frame_index in range(next_frame, target_frame + 1):
            step(frames[frame_index], tiles)
            if (
                compiled_constraints.avoidances
                and _avoided_interactions_triggered(compiled_constraints, result_state)
            ):
                return (
                    Evaluation(float("-inf"), result_state, False),
                    frozenset(missing),
                    False,
                )
            if result_state.player.dead:
                return (
                    _evaluation_with_interactions(
                        float("-inf"), result_state, False,
                        required_interactions, avoided_interactions,
                        compiled_constraints=compiled_constraints,
                    ),
                    frozenset(missing),
                    False,
                )
    except UnsupportedTileCollision:
        return (
            _evaluation_with_interactions(
                float("-inf"), result_state, False,
                required_interactions, avoided_interactions,
                compiled_constraints=compiled_constraints,
            ),
            frozenset(missing),
            False,
        )

    feasible = position_within_windows(
        result_state, x_window=x_window, y_window=y_window
    )
    return (
        _evaluation_with_interactions(
            objective(result_state) if feasible else float("-inf"),
            result_state,
            feasible,
            required_interactions,
            avoided_interactions,
            compiled_constraints=compiled_constraints,
        ),
        frozenset(missing),
        False,
    )


def _held_jump_would_invoke(
    state_before: SimulationState,
    released_state: SimulationState,
) -> bool:
    """Predict a fresh held-jump call from the already-stepped release branch.

    ``Player.step`` performs world and object collision work before
    ``Player._think`` reads the input. For a fresh jump edge, the held and
    released branches are therefore identical through collision handling; the
    only possible gameplay difference is the jump call in ``_think``. The
    post-release ``in_air``/``near_wall`` flags retain the collision facts
    needed by that decision, while the pre-step state retains the state
    ordering used by ``_think``.

    The all-input search calls this only for its candidate frame, whose jump
    trigger is derived from ``previous_jump_held``. A held frame while already
    jumping is deliberately excluded because ``jump_held`` changes the jump
    timer even without a new jump event.
    """
    player = state_before.player
    if player.previous_jump_held:
        return False
    if player.state in (PlayerState.JUMPING, PlayerState.CELEBRATING):
        return False

    released_player = released_state.player
    if released_state.level_complete or released_player.state == PlayerState.CELEBRATING:
        return False
    if player.state < PlayerState.JUMPING:
        # Grounded collision enables the ordinary jump path.
        return not released_player.in_air
    # Falling, wall-sliding, and ragdoll states can use a wall jump after the
    # same collision pass when a wall remains adjacent.
    return released_player.in_air and released_player.near_wall


def _state_key_ignoring_previous_jump_held(state: SimulationState) -> tuple:
    """Return an exact gameplay-state key ignoring only jump-edge history.

    A fresh jump press that fails to invoke ``Player.jump()`` normally differs
    from the released-input branch only because ``previous_jump_held`` becomes
    true. Temporarily normalising that one bit lets all-input local search
    distinguish such an inactive press from cases where holding jump still has
    another gameplay effect (for example, extending an existing jump).
    """
    previous = state.player.previous_jump_held
    state.player.previous_jump_held = False
    try:
        return state.state_key()
    finally:
        state.player.previous_jump_held = previous


def _preserve_failed_jump_press(
    frames: Sequence[InputFrame],
    window_frame_set: frozenset[int],
    *,
    frame_index: int,
    target_frame: int,
) -> bool:
    """Keep a failed pre-hold when the next fixed frame already holds jump.

    Failed fresh presses are normally dominated, but they can intentionally
    set ``previous_jump_held`` so a fixed held-jump input on the following frame
    does not create a rising edge. This conservative boundary exception protects
    the common contiguous-window suffix and sparse-window gap cases.
    """
    next_frame = frame_index + 1
    return (
        next_frame <= target_frame
        and next_frame not in window_frame_set
        and frames[next_frame].jump
    )


def _evaluate_all_input_suffix(
    level: Level,
    state: SimulationState,
    frames: Sequence[InputFrame],
    *,
    start_frame: int,
    target_frame: int,
    objective: Callable[[SimulationState], float],
    x_window: AxisWindow | None,
    y_window: AxisWindow | None,
    required_interactions: Sequence[InteractionRequirement] = (),
    avoided_interactions: Sequence[InteractionAvoidance] = (),
    compiled_constraints: _CompiledInteractionConstraints | None = None,
) -> Evaluation:
    """Replay the fixed suffix after an all-input DFS window.

    The DFS gives each terminal leaf exclusive ownership of ``state``. The
    suffix can therefore be applied in place instead of cloning the complete
    object manager once more for every terminal candidate.
    """
    result_state = state
    tiles = level.tiles
    step = result_state.step
    if compiled_constraints is None:
        compiled_constraints = _compile_interaction_constraints(
            tuple(required_interactions), tuple(avoided_interactions)
        )

    try:
        for frame_index in range(start_frame, target_frame + 1):
            step(frames[frame_index], tiles)
            # Avoided interactions are persistent events. Once one has fired,
            # no remaining fixed suffix input can restore feasibility.
            if (
                compiled_constraints.avoidances
                and _avoided_interactions_triggered(compiled_constraints, result_state)
            ):
                return Evaluation(float("-inf"), result_state, False)
            if result_state.player.dead:
                return _evaluation_with_interactions(
                    float("-inf"), result_state, False,
                    required_interactions, avoided_interactions,
                    compiled_constraints=compiled_constraints,
                )
    except UnsupportedTileCollision:
        return _evaluation_with_interactions(
            float("-inf"), result_state, False,
            required_interactions, avoided_interactions,
            compiled_constraints=compiled_constraints,
        )

    feasible = position_within_windows(
        result_state, x_window=x_window, y_window=y_window
    )
    return _evaluation_with_interactions(
        objective(result_state) if feasible else float("-inf"),
        result_state,
        feasible,
        required_interactions,
        avoided_interactions,
        compiled_constraints=compiled_constraints,
    )


@dataclass(slots=True)
class _AllInputSearchFrontier:
    """Privately owned all-input DFS state paused at a mutable-depth cut."""

    state: SimulationState
    frame_index: int
    chosen: tuple[InputFrame, ...]
    changed: bool


@dataclass(slots=True)
class _DirectionSearchFrontier:
    """Privately owned direction DFS state paused at a mutable-depth cut."""

    state: SimulationState
    frame_index: int
    chosen: tuple[InputFrame, ...]
    missed_so_far: frozenset[int]
    can_consume: bool
    changed: bool


def _search_all_input_frames(
    level: Level,
    frames: Sequence[InputFrame],
    *,
    prefix_state: SimulationState | None,
    window_frames: Sequence[int],
    target_frame: int,
    objective: Callable[[SimulationState], float],
    incumbent_slice: Sequence[InputFrame],
    incumbent_eval: Evaluation,
    x_window: AxisWindow | None,
    y_window: AxisWindow | None,
    required_interactions: Sequence[InteractionRequirement] = (),
    avoided_interactions: Sequence[InteractionAvoidance] = (),
    compiled_constraints: _CompiledInteractionConstraints | None = None,
    capture_after_choices: int | None = None,
    frontier_out: list[_AllInputSearchFrontier] | None = None,
    initial_frontier: Sequence[_AllInputSearchFrontier] | None = None,
    jump_prediction_safe: bool | None = None,
) -> tuple[list[InputFrame], Evaluation, AllInputWindowStats]:
    """DFS over L/N/R x jump with default inactive-jump pruning.

    The released branch supplies the collision result for a fresh held press.
    When ``Player.jump()`` cannot run and the held/released outcomes would be
    identical apart from edge history, the held branch is not stepped. Active
    jumps, existing jump holds, and launch-pad levels use the exact simulator
    path. The sole default pruning exception is a failed pre-hold immediately
    before a fixed held-jump frame, where the changed edge history can
    deliberately suppress the next jump trigger.
    """
    if not window_frames:
        raise ValueError("all-input search requires at least one mutable frame")
    if capture_after_choices is not None:
        if capture_after_choices < 1:
            raise ValueError("frontier depth must be at least one mutable frame")
        if frontier_out is None:
            raise ValueError("captured all-input frontier requires an output list")
    if initial_frontier is not None and capture_after_choices is not None:
        raise ValueError("cannot capture and resume an all-input frontier together")
    window_frames_tuple = tuple(window_frames)
    window_frame_set = frozenset(window_frames_tuple)
    window_start = window_frames_tuple[0]
    window_end = window_frames_tuple[-1]
    best_slice = list(incumbent_slice)
    best_eval = incumbent_eval
    stats = AllInputWindowStats()
    if compiled_constraints is None:
        compiled_constraints = _compile_interaction_constraints(
            tuple(required_interactions), tuple(avoided_interactions)
        )
    seen: set[tuple[int, tuple]] = set()
    # Launch pads can overwrite the pre-step Player state with FALLING before
    # _think runs. Keep the exact held-step fallback on such levels; all other
    # supported object contacts preserve the pre-step state needed by the
    # release-branch prediction.
    if jump_prediction_safe is None:
        prediction_state = (
            prefix_state
            if prefix_state is not None
            else initial_frontier[0].state
            if initial_frontier
            else None
        )
        if prediction_state is None:
            raise ValueError("all-input search requires a prefix or frontier state")
        jump_prediction_safe = not any(
            type(obj) is LaunchPad for obj in prediction_state.objects
        )
    candidate_frames = tuple(
        tuple(
            (
                InputFrame(horizontal < 0, horizontal > 0, jump, None)
                for jump in (False, True)
            )
        )
        for horizontal in (-1, 0, 1)
    )

    def materialise_exact_held_sibling(
        state_before: SimulationState,
        held: InputFrame,
        *,
        previous_jump_held: bool,
        frame_index: int,
    ) -> SimulationState | None:
        """Build a held sibling by exactly stepping its untouched parent.

        This is used for an active jump hold or a press predicted to call
        ``Player.jump()``. It intentionally does not depend on the released
        child, so a terminal released leaf may finish its owned suffix first.
        """
        candidate_state = state_before.clone(copy_on_write_objects=True)
        before_events = candidate_state.player.jump_events
        try:
            candidate_state.step(held, level.tiles)
        except UnsupportedTileCollision:
            stats.dead_prunes += 1
            return None
        if candidate_state.player.dead:
            stats.dead_prunes += 1
            return None
        jumped = candidate_state.player.jump_events > before_events

        if (
            not previous_jump_held
            and not jumped
            and state_before.player.state != PlayerState.JUMPING
            and not _preserve_failed_jump_press(
                frames,
                window_frame_set,
                frame_index=frame_index,
                target_frame=target_frame,
            )
        ):
            stats.inactive_jump_prunes += 1
            return None
        return candidate_state

    def recurse(
        state: SimulationState,
        frame_index: int,
        chosen: list[InputFrame],
        changed: bool,
        *,
        count_node: bool = True,
    ) -> None:
        nonlocal best_eval, best_slice
        if count_node:
            stats.visited_nodes += 1

        # Gold, exit-switch, locked-door, and trapdoor avoidances all record
        # persistent state. A branch which has fired one cannot become a
        # feasible local candidate again, so do not carry it through the rest
        # of the DFS or its fixed suffix.
        if (
            compiled_constraints.avoidances
            and _avoided_interactions_triggered(compiled_constraints, state)
        ):
            stats.avoided_interaction_prunes += 1
            return

        if (
            capture_after_choices is not None
            and len(chosen) >= capture_after_choices
        ):
            assert frontier_out is not None
            frontier_out.append(
                _AllInputSearchFrontier(
                    state,
                    frame_index,
                    tuple(chosen),
                    changed,
                )
            )
            return

        if frame_index > window_end:
            stats.evaluated_leaves += 1
            if not changed:
                # The source input tuple is the already-verified incumbent.
                # It cannot improve score or hard constraints, so avoid
                # replaying its unchanged fixed suffix.
                return
            evaluation = _evaluate_all_input_suffix(
                level,
                state,
                frames,
                start_frame=window_end + 1,
                target_frame=target_frame,
                objective=objective,
                x_window=x_window,
                y_window=y_window,
                required_interactions=required_interactions,
                avoided_interactions=avoided_interactions,
                compiled_constraints=compiled_constraints,
            )
            if _local_candidate_better(
                evaluation,
                frozenset(),
                best_eval,
                frozenset(),
                incumbent_eval=incumbent_eval,
                incumbent_missing_jump_frames=frozenset(),
            ):
                best_eval = evaluation
                best_slice = chosen.copy()
            return

        # The root is entered once for a window, so hashing its full emulator
        # state cannot deduplicate anything. Deeper nodes can still converge
        # after different input prefixes and retain the exact state-key check.
        if frame_index != window_start:
            state_key = (frame_index, state.state_key())
            if state_key in seen:
                stats.deduplicated_prunes += 1
                return
            seen.add(state_key)

        if frame_index not in window_frame_set:
            next_state = state.clone(copy_on_write_objects=True)
            try:
                next_state.step(frames[frame_index], level.tiles)
            except UnsupportedTileCollision:
                stats.dead_prunes += 1
                return
            if next_state.player.dead:
                stats.dead_prunes += 1
                return
            recurse(next_state, frame_index + 1, chosen, changed)
            return

        previous_jump_held = state.player.previous_jump_held
        for horizontal in (-1, 0, 1):
            released, held = candidate_frames[horizontal + 1]
            released_state = state.clone(copy_on_write_objects=True)
            try:
                released_state.step(released, level.tiles)
            except UnsupportedTileCollision:
                stats.dead_prunes += 1
                continue
            if released_state.player.dead:
                stats.dead_prunes += 1
            else:
                predicted_jump = (
                    jump_prediction_safe
                    and _held_jump_would_invoke(state, released_state)
                )
                exact_held_step = (
                    predicted_jump
                    or state.player.state == PlayerState.JUMPING
                    # The release-branch prediction is deliberately disabled
                    # when a LaunchPad is present: its collision pass can
                    # change the pre-Think player state. In that case a fresh
                    # held press must be stepped before inactive pruning.
                    or not jump_prediction_safe
                )
                retained_failed_press = (
                    not exact_held_step
                    and (
                        previous_jump_held
                        or _preserve_failed_jump_press(
                            frames,
                            window_frame_set,
                            frame_index=frame_index,
                            target_frame=target_frame,
                        )
                    )
                )
                held_state: SimulationState | None = None
                if retained_failed_press and frame_index == window_end:
                    # The final released leaf owns and advances this state
                    # through the suffix. A failed press reuses that
                    # post-collision state, so capture the held sibling before
                    # release recursion can consume it.
                    held_state = released_state.clone(copy_on_write_objects=True)
                    if not released_state.level_complete:
                        held_state.player.previous_jump_held = True
                elif not exact_held_step and not retained_failed_press:
                    stats.inactive_jump_prunes += 1

                chosen.append(released)
                recurse(
                    released_state,
                    frame_index + 1,
                    chosen,
                    changed or released != frames[frame_index],
                )
                chosen.pop()

                if exact_held_step:
                    # ``state`` is an untouched parent: only its released
                    # clone recursed above. Delaying this exact branch keeps
                    # the normal release-first lifetime while avoiding an
                    # alias with a terminal released leaf.
                    held_state = materialise_exact_held_sibling(
                        state,
                        held,
                        previous_jump_held=previous_jump_held,
                        frame_index=frame_index,
                    )
                elif retained_failed_press and held_state is None:
                    # Non-terminal release subtrees clone before every later
                    # input, so their released state remains available.
                    held_state = released_state.clone(copy_on_write_objects=True)
                    if not released_state.level_complete:
                        held_state.player.previous_jump_held = True

                if held_state is not None:
                    chosen.append(held)
                    recurse(
                        held_state,
                        frame_index + 1,
                        chosen,
                        changed or held != frames[frame_index],
                    )
                    chosen.pop()

    if initial_frontier is None:
        if prefix_state is None:
            raise ValueError("all-input search requires a prefix state")
        recurse(prefix_state, window_start, [], False)
    else:
        for item in initial_frontier:
            recurse(
                item.state,
                item.frame_index,
                list(item.chosen),
                item.changed,
                count_node=False,
            )
    return best_slice, best_eval, stats


def _search_direction_frames(
    level: Level,
    frames: Sequence[InputFrame],
    *,
    prefix_state: SimulationState | None,
    window_frames: Sequence[int],
    target_frame: int,
    objective_name: str,
    objective: Callable[[SimulationState], float],
    required_jump_frames: frozenset[int],
    incumbent_missing_jump_frames: frozenset[int],
    incumbent_slice: Sequence[InputFrame],
    incumbent_eval: Evaluation,
    x_window: AxisWindow | None,
    y_window: AxisWindow | None,
    physics_prune: bool,
    required_interactions: Sequence[InteractionRequirement] = (),
    avoided_interactions: Sequence[InteractionAvoidance] = (),
    compiled_constraints: _CompiledInteractionConstraints | None = None,
    capture_after_choices: int | None = None,
    frontier_out: list[_DirectionSearchFrontier] | None = None,
    initial_frontier: Sequence[_DirectionSearchFrontier] | None = None,
) -> tuple[
    list[InputFrame], Evaluation, frozenset[int], DirectionWindowStats
]:
    """Exact DFS over L/N/R on selected frames while all gaps stay fixed."""
    if not window_frames:
        raise ValueError("direction search requires at least one mutable frame")
    if capture_after_choices is not None:
        if capture_after_choices < 1:
            raise ValueError("frontier depth must be at least one mutable frame")
        if frontier_out is None:
            raise ValueError("captured direction frontier requires an output list")
    if initial_frontier is not None and capture_after_choices is not None:
        raise ValueError("cannot capture and resume a direction frontier together")
    window_frames_tuple = tuple(window_frames)
    window_frame_set = frozenset(window_frames_tuple)
    window_start = window_frames_tuple[0]
    window_end = window_frames_tuple[-1]
    contiguous_window = (
        len(window_frames_tuple) == window_end - window_start + 1
    )
    best_slice = list(incumbent_slice)
    best_eval = incumbent_eval
    best_missing = incumbent_missing_jump_frames
    stats = DirectionWindowStats()
    if compiled_constraints is None:
        compiled_constraints = _compile_interaction_constraints(
            tuple(required_interactions), tuple(avoided_interactions)
        )
    seen: set[tuple[int, tuple, frozenset[int]]] = set()
    direction_frames = {
        frame_index: tuple(
            _direction_frame(frames[frame_index], horizontal)
            for horizontal in (-1, 0, 1)
        )
        for frame_index in window_frames_tuple
    }
    direction_order: dict[int, tuple[int, ...]] = {}
    for frame_index in window_frames_tuple:
        original_h = frames[frame_index].horizontal
        favourable = (
            1
            if objective_name == "max-x"
            else -1 if objective_name == "min-x" else original_h
        )
        order: list[int] = []
        for value in (favourable, original_h, 0, -favourable):
            if value in (-1, 0, 1) and value not in order:
                order.append(value)
        for value in (-1, 0, 1):
            if value not in order:
                order.append(value)
        direction_order[frame_index] = tuple(order)
    physics_jump_edges = (
        _future_jump_edge_frames(
            frames, start_frame=window_start, target_frame=target_frame
        )
        if physics_prune
        else frozenset()
    )
    suffix_required_frames = tuple(
        frame_index
        for frame_index in sorted(required_jump_frames)
        if window_end < frame_index <= target_frame
    )

    def recurse(
        state: SimulationState,
        frame_index: int,
        chosen: list[InputFrame],
        missed_so_far: frozenset[int],
        can_consume: bool,
        changed: bool,
        *,
        count_node: bool = True,
    ) -> None:
        nonlocal best_eval, best_missing, best_slice
        if count_node:
            stats.visited_nodes += 1

        # All supported avoidances are persistent: once a gold, switch, locked
        # door, or trapdoor trigger is touched, a later suffix cannot undo it.
        # Reject such branches before they spend time on the remaining fixed
        # frames. The root check also handles an already-forbidden immutable
        # prefix without changing the final diagnostic.
        if (
            compiled_constraints.avoidances
            and _avoided_interactions_triggered(compiled_constraints, state)
        ):
            stats.avoided_interaction_prunes += 1
            return

        # Missed jump frames are monotonic after their input tick has passed.
        # Once a feasible incumbent has repaired one of them, a branch that
        # already missed it cannot dominate that incumbent, regardless of its
        # eventual positional score.
        if best_eval.feasible and not missed_so_far <= best_missing:
            stats.missed_jump_prunes += 1
            return

        # If this branch could still finish with fewer misses than the current
        # best candidate, objective score is irrelevant. Passing -inf retains
        # x-window feasibility pruning without discarding a jump repair merely
        # because its target score is temporarily worse.
        physics_best_score = (
            float("-inf")
            if (
                best_eval.missing_interactions
                or best_eval.violated_interactions
                or missed_so_far < best_missing
            )
            else best_eval.score
        )
        if physics_prune and not _physics_bound_allows_branch(
            state,
            frames,
            target_frame=target_frame,
            objective_name=objective_name,
            best_score=physics_best_score,
            x_window=x_window,
            jump_edges=physics_jump_edges,
        ):
            stats.physics_prunes += 1
            return

        if (
            capture_after_choices is not None
            and len(chosen) >= capture_after_choices
        ):
            assert frontier_out is not None
            frontier_out.append(
                _DirectionSearchFrontier(
                    state,
                    frame_index,
                    tuple(chosen),
                    missed_so_far,
                    can_consume,
                    changed,
                )
            )
            return

        if frame_index > window_end:
            stats.evaluated_leaves += 1
            if not changed:
                # The unchanged window is already represented by the exact
                # incumbent evaluation.  Its terminal suffix cannot improve
                # any score or hard requirement, so avoid replaying it.
                return
            evaluation, candidate_missing, new_missed_jump = _evaluate_direction_suffix(
                level,
                state,
                frames,
                start_frame=window_end + 1,
                target_frame=target_frame,
                objective=objective,
                required_jump_frames=required_jump_frames,
                allowed_missing_jump_frames=incumbent_missing_jump_frames,
                initial_missing_jump_frames=missed_so_far,
                required_suffix_frames=suffix_required_frames,
                x_window=x_window,
                y_window=y_window,
                required_interactions=required_interactions,
                avoided_interactions=avoided_interactions,
                compiled_constraints=compiled_constraints,
            )
            if new_missed_jump:
                stats.missed_jump_prunes += 1
                return
            if _local_candidate_better(
                evaluation,
                candidate_missing,
                best_eval,
                best_missing,
                incumbent_eval=incumbent_eval,
                incumbent_missing_jump_frames=incumbent_missing_jump_frames,
            ):
                best_eval = evaluation
                best_missing = candidate_missing
                best_slice = chosen.copy()
            return

        # The root is reached exactly once for each window, so hashing its
        # complete emulator state cannot deduplicate anything. Deeper nodes
        # can converge after different direction prefixes and retain the
        # exact state-key check.
        if frame_index != window_start:
            state_key = (frame_index, state.state_key(), missed_so_far)
            if state_key in seen:
                stats.deduplicated_prunes += 1
                return
            seen.add(state_key)

        if not contiguous_window and frame_index not in window_frame_set:
            next_state = (
                state
                if can_consume
                else state.clone(copy_on_write_objects=True)
            )
            required = frame_index in required_jump_frames
            before_events = next_state.player.jump_events if required else 0
            try:
                next_state.step(frames[frame_index], level.tiles)
            except UnsupportedTileCollision:
                stats.dead_prunes += 1
                return
            if next_state.player.dead:
                stats.dead_prunes += 1
                return
            if required and next_state.player.jump_events <= before_events:
                if frame_index not in incumbent_missing_jump_frames:
                    stats.missed_jump_prunes += 1
                    return
                next_missing = missed_so_far | {frame_index}
            else:
                next_missing = missed_so_far
            recurse(
                next_state,
                frame_index + 1,
                chosen,
                next_missing,
                True,
                changed,
            )
            return

        directions = direction_order[frame_index]
        last_direction_index = len(directions) - 1
        for direction_index, horizontal in enumerate(directions):
            # The final mutable frame has no later direction choice.  If the
            # path has stayed on the incumbent input so far, its source
            # candidate is exactly the already-evaluated incumbent replay.
            # Count that leaf for diagnostics, but do not tick the state just
            # to rediscover the same terminal result.
            if (
                not changed
                and frame_index == window_end
                and direction_frames[frame_index][horizontal + 1]
                == frames[frame_index]
            ):
                stats.evaluated_leaves += 1
                continue
            next_state = (
                state
                if can_consume and direction_index == last_direction_index
                else state.clone(copy_on_write_objects=True)
            )
            candidate = direction_frames[frame_index][horizontal + 1]
            required = frame_index in required_jump_frames
            before_events = next_state.player.jump_events if required else 0
            try:
                next_state.step(candidate, level.tiles)
            except UnsupportedTileCollision:
                stats.dead_prunes += 1
                continue
            if next_state.player.dead:
                stats.dead_prunes += 1
                continue
            if required and next_state.player.jump_events <= before_events:
                if frame_index not in incumbent_missing_jump_frames:
                    stats.missed_jump_prunes += 1
                    continue
                next_missing = missed_so_far | {frame_index}
            else:
                next_missing = missed_so_far
            chosen.append(candidate)
            recurse(
                next_state,
                frame_index + 1,
                chosen,
                next_missing,
                True,
                changed or candidate != frames[frame_index],
            )
            chosen.pop()

    prefix_missing = frozenset(
        frame
        for frame in incumbent_missing_jump_frames
        if frame < window_start
    )
    # The prefix is retained by the caller for forward incremental windows.
    # Every descendant is privately owned, so its final child can consume the
    # parent state in place without another branch clone.
    if initial_frontier is None:
        if prefix_state is None:
            raise ValueError("direction search requires a prefix state")
        recurse(prefix_state, window_start, [], prefix_missing, False, False)
    else:
        for item in initial_frontier:
            recurse(
                item.state,
                item.frame_index,
                list(item.chosen),
                item.missed_so_far,
                item.can_consume,
                item.changed,
                count_node=False,
            )
    return best_slice, best_eval, best_missing, stats


@dataclass(frozen=True, slots=True)
class _LocalWindowWorkerContext:
    """Run-constant inputs reconstructed once in each DFS worker process."""

    level: Level
    target_frame: int
    objective_name: str
    objective_target: TargetSelection | None
    x_window: AxisWindow | None
    y_window: AxisWindow | None
    physics_prune: bool
    required_jump_frames: frozenset[int]
    required_interactions: tuple[InteractionRequirement, ...]
    avoided_interactions: tuple[InteractionAvoidance, ...]


@dataclass(frozen=True, slots=True)
class _LocalWindowIncumbent:
    """Comparison fields sent to workers without the large terminal state."""

    score: float
    feasible: bool
    missing_interactions: frozenset[InteractionRequirement]
    violated_interactions: frozenset[InteractionAvoidance]


@dataclass(frozen=True, slots=True)
class _LocalWindowWorkItem:
    """One contiguous batch of paused DFS branches for a worker."""

    local_inputs: str
    frames: tuple[InputFrame, ...]
    window_frames: tuple[int, ...]
    incumbent_slice: tuple[InputFrame, ...]
    incumbent: _LocalWindowIncumbent
    incumbent_missing_jump_frames: frozenset[int]
    jump_prediction_safe: bool | None
    frontier: tuple[_AllInputSearchFrontier | _DirectionSearchFrontier, ...]


@dataclass(slots=True)
class _LocalWindowWorkResult:
    """Best strict improvement and counters from one DFS frontier batch."""

    best_slice: list[InputFrame] | None
    best_eval: Evaluation | None
    best_missing_jump_frames: frozenset[int]
    stats: AllInputWindowStats | DirectionWindowStats


class _LazyLocalWindowPool:
    """Open a persistent DFS process pool only when a window can use it."""

    def __init__(
        self,
        worker_count: int,
        context: _LocalWindowWorkerContext,
        *,
        run_label: str,
        progress: Callable[[str], None] | None,
    ) -> None:
        self.worker_count = worker_count
        self.context = context
        self.run_label = run_label
        self.progress = progress
        self.executor: ProcessPoolExecutor | None = None

    def map(
        self,
        function: Callable[[_LocalWindowWorkItem], _LocalWindowWorkResult],
        work_items: Sequence[_LocalWindowWorkItem],
    ) -> Iterator[_LocalWindowWorkResult]:
        """Map a frontier batch, starting no more processes than it can feed."""
        if self.executor is None:
            actual_workers = min(self.worker_count, len(work_items))
            if actual_workers < 1:
                raise ValueError("local window pool requires at least one work item")
            if self.progress is not None:
                self.progress(
                    f"{self.run_label} local DFS: {actual_workers} worker "
                    "processes, persistent per-window frontier pool"
                )
            self.executor = ProcessPoolExecutor(
                max_workers=actual_workers,
                mp_context=multiprocessing.get_context(),
                initializer=_initialise_local_window_worker,
                initargs=(self.context,),
            )
        return self.executor.map(function, work_items)

    def __enter__(self) -> _LazyLocalWindowPool:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        if self.executor is not None:
            if exc_type is None:
                self.executor.shutdown(wait=True)
            else:
                _stop_local_executor_for_exception(self.executor)


_LOCAL_WINDOW_WORKER_CONTEXT: _LocalWindowWorkerContext | None = None
_LOCAL_WINDOW_WORKER_OBJECTIVE: Callable[[SimulationState], float] | None = None
_LOCAL_WINDOW_WORKER_CONSTRAINTS: _CompiledInteractionConstraints | None = None


def _initialise_local_window_worker(context: _LocalWindowWorkerContext) -> None:
    """Install picklable configuration and rebuild the objective callable."""
    global _LOCAL_WINDOW_WORKER_CONTEXT
    global _LOCAL_WINDOW_WORKER_OBJECTIVE
    global _LOCAL_WINDOW_WORKER_CONSTRAINTS
    _LOCAL_WINDOW_WORKER_CONTEXT = context
    _LOCAL_WINDOW_WORKER_OBJECTIVE = objective_function(
        context.objective_name, context.objective_target
    )
    _LOCAL_WINDOW_WORKER_CONSTRAINTS = _compile_interaction_constraints(
        context.required_interactions, context.avoided_interactions
    )
    if multiprocessing.current_process().name != "MainProcess":
        signal.signal(signal.SIGINT, signal.SIG_IGN)


def _run_local_window_work_item(
    item: _LocalWindowWorkItem,
) -> _LocalWindowWorkResult:
    """Resume one batch of a single local window's exact DFS frontier."""
    context = _LOCAL_WINDOW_WORKER_CONTEXT
    objective = _LOCAL_WINDOW_WORKER_OBJECTIVE
    compiled_constraints = _LOCAL_WINDOW_WORKER_CONSTRAINTS
    if context is None or objective is None or compiled_constraints is None:
        raise RuntimeError("local-window worker was not initialised")
    if not item.frontier:
        raise RuntimeError("local-window worker received an empty frontier")
    incumbent_eval = Evaluation(
        item.incumbent.score,
        item.frontier[0].state,
        item.incumbent.feasible,
        item.incumbent.missing_interactions,
        item.incumbent.violated_interactions,
    )

    if item.local_inputs == "direction":
        frontier = tuple(
            branch
            for branch in item.frontier
            if isinstance(branch, _DirectionSearchFrontier)
        )
        if len(frontier) != len(item.frontier):
            raise RuntimeError("direction worker received an all-input frontier")
        best_slice, best_eval, best_missing, stats = _search_direction_frames(
            context.level,
            item.frames,
            prefix_state=None,
            window_frames=item.window_frames,
            target_frame=context.target_frame,
            objective_name=context.objective_name,
            objective=objective,
            required_jump_frames=context.required_jump_frames,
            incumbent_missing_jump_frames=item.incumbent_missing_jump_frames,
            incumbent_slice=item.incumbent_slice,
            incumbent_eval=incumbent_eval,
            x_window=context.x_window,
            y_window=context.y_window,
            physics_prune=context.physics_prune,
            required_interactions=context.required_interactions,
            avoided_interactions=context.avoided_interactions,
            compiled_constraints=compiled_constraints,
            initial_frontier=frontier,
        )
    else:
        frontier = tuple(
            branch
            for branch in item.frontier
            if isinstance(branch, _AllInputSearchFrontier)
        )
        if len(frontier) != len(item.frontier):
            raise RuntimeError("all-input worker received a direction frontier")
        best_slice, best_eval, stats = _search_all_input_frames(
            context.level,
            item.frames,
            prefix_state=None,
            window_frames=item.window_frames,
            target_frame=context.target_frame,
            objective=objective,
            incumbent_slice=item.incumbent_slice,
            incumbent_eval=incumbent_eval,
            x_window=context.x_window,
            y_window=context.y_window,
            required_interactions=context.required_interactions,
            avoided_interactions=context.avoided_interactions,
            compiled_constraints=compiled_constraints,
            initial_frontier=frontier,
            jump_prediction_safe=item.jump_prediction_safe,
        )
        best_missing = frozenset()

    if best_eval is incumbent_eval:
        return _LocalWindowWorkResult(None, None, best_missing, stats)
    return _LocalWindowWorkResult(best_slice, best_eval, best_missing, stats)


def _local_frontier_depth(
    mutable_frames: int,
    worker_count: int,
    *,
    branch_factor: int,
) -> int:
    """Choose the shallowest cut capable of feeding the requested workers."""
    target = max(2, worker_count)
    depth = 1
    capacity = branch_factor
    while depth < mutable_frames and capacity < target:
        depth += 1
        capacity *= branch_factor
    return depth


def _contiguous_frontier_batches(
    frontier: Sequence[_AllInputSearchFrontier | _DirectionSearchFrontier],
    batch_count: int,
) -> list[tuple[_AllInputSearchFrontier | _DirectionSearchFrontier, ...]]:
    """Split DFS-order states evenly without changing inter-batch order."""
    actual_batches = min(len(frontier), batch_count)
    if actual_batches < 1:
        return []
    quotient, remainder = divmod(len(frontier), actual_batches)
    batches: list[
        tuple[_AllInputSearchFrontier | _DirectionSearchFrontier, ...]
    ] = []
    start = 0
    for batch_index in range(actual_batches):
        size = quotient + (batch_index < remainder)
        end = start + size
        batches.append(tuple(frontier[start:end]))
        start = end
    return batches


def _parallel_direction_window(
    executor: _LazyLocalWindowPool,
    worker_count: int,
    level: Level,
    frames: Sequence[InputFrame],
    *,
    prefix_state: SimulationState,
    window_frames: Sequence[int],
    target_frame: int,
    objective_name: str,
    objective: Callable[[SimulationState], float],
    required_jump_frames: frozenset[int],
    incumbent_missing_jump_frames: frozenset[int],
    incumbent_slice: Sequence[InputFrame],
    incumbent_eval: Evaluation,
    x_window: AxisWindow | None,
    y_window: AxisWindow | None,
    physics_prune: bool,
    required_interactions: Sequence[InteractionRequirement],
    avoided_interactions: Sequence[InteractionAvoidance],
    compiled_constraints: _CompiledInteractionConstraints,
) -> tuple[list[InputFrame], Evaluation, frozenset[int], DirectionWindowStats]:
    """Split one score-ordered direction DFS at a shallow viable frontier."""
    frontier: list[_DirectionSearchFrontier] = []
    depth = _local_frontier_depth(
        len(window_frames), worker_count, branch_factor=3
    )
    _unused_slice, _unused_eval, _unused_missing, stats = _search_direction_frames(
        level,
        frames,
        prefix_state=prefix_state,
        window_frames=window_frames,
        target_frame=target_frame,
        objective_name=objective_name,
        objective=objective,
        required_jump_frames=required_jump_frames,
        incumbent_missing_jump_frames=incumbent_missing_jump_frames,
        incumbent_slice=incumbent_slice,
        incumbent_eval=incumbent_eval,
        x_window=x_window,
        y_window=y_window,
        physics_prune=physics_prune,
        required_interactions=required_interactions,
        avoided_interactions=avoided_interactions,
        compiled_constraints=compiled_constraints,
        capture_after_choices=depth,
        frontier_out=frontier,
    )
    if len(frontier) < 2:
        if not frontier:
            return (
                list(incumbent_slice),
                incumbent_eval,
                incumbent_missing_jump_frames,
                stats,
            )
        best_slice, best_eval, best_missing, resumed_stats = _search_direction_frames(
            level,
            frames,
            prefix_state=None,
            window_frames=window_frames,
            target_frame=target_frame,
            objective_name=objective_name,
            objective=objective,
            required_jump_frames=required_jump_frames,
            incumbent_missing_jump_frames=incumbent_missing_jump_frames,
            incumbent_slice=incumbent_slice,
            incumbent_eval=incumbent_eval,
            x_window=x_window,
            y_window=y_window,
            physics_prune=physics_prune,
            required_interactions=required_interactions,
            avoided_interactions=avoided_interactions,
            compiled_constraints=compiled_constraints,
            initial_frontier=frontier,
        )
        stats.add(resumed_stats)
        return best_slice, best_eval, best_missing, stats

    batches = _contiguous_frontier_batches(frontier, worker_count)
    shared_frames = tuple(frames)
    shared_window_frames = tuple(window_frames)
    shared_incumbent_slice = tuple(incumbent_slice)
    shared_incumbent = _LocalWindowIncumbent(
        incumbent_eval.score,
        incumbent_eval.feasible,
        incumbent_eval.missing_interactions,
        incumbent_eval.violated_interactions,
    )
    work_items = tuple(
        _LocalWindowWorkItem(
            "direction",
            shared_frames,
            shared_window_frames,
            shared_incumbent_slice,
            shared_incumbent,
            incumbent_missing_jump_frames,
            None,
            batch,
        )
        for batch in batches
    )
    best_slice = list(incumbent_slice)
    best_eval = incumbent_eval
    best_missing = incumbent_missing_jump_frames
    for result in executor.map(_run_local_window_work_item, work_items):
        assert isinstance(result.stats, DirectionWindowStats)
        stats.add(result.stats)
        if result.best_eval is None or result.best_slice is None:
            continue
        if _local_candidate_better(
            result.best_eval,
            result.best_missing_jump_frames,
            best_eval,
            best_missing,
            incumbent_eval=incumbent_eval,
            incumbent_missing_jump_frames=incumbent_missing_jump_frames,
        ):
            best_slice = result.best_slice
            best_eval = result.best_eval
            best_missing = result.best_missing_jump_frames
    return best_slice, best_eval, best_missing, stats


def _parallel_all_input_window(
    executor: _LazyLocalWindowPool,
    worker_count: int,
    level: Level,
    frames: Sequence[InputFrame],
    *,
    prefix_state: SimulationState,
    window_frames: Sequence[int],
    target_frame: int,
    objective: Callable[[SimulationState], float],
    incumbent_slice: Sequence[InputFrame],
    incumbent_eval: Evaluation,
    x_window: AxisWindow | None,
    y_window: AxisWindow | None,
    required_interactions: Sequence[InteractionRequirement],
    avoided_interactions: Sequence[InteractionAvoidance],
    compiled_constraints: _CompiledInteractionConstraints,
) -> tuple[list[InputFrame], Evaluation, AllInputWindowStats]:
    """Split one score-ordered all-input DFS at a shallow viable frontier."""
    frontier: list[_AllInputSearchFrontier] = []
    jump_prediction_safe = not any(
        type(obj) is LaunchPad for obj in prefix_state.objects
    )
    depth = _local_frontier_depth(
        len(window_frames), worker_count, branch_factor=6
    )
    _unused_slice, _unused_eval, stats = _search_all_input_frames(
        level,
        frames,
        prefix_state=prefix_state,
        window_frames=window_frames,
        target_frame=target_frame,
        objective=objective,
        incumbent_slice=incumbent_slice,
        incumbent_eval=incumbent_eval,
        x_window=x_window,
        y_window=y_window,
        required_interactions=required_interactions,
        avoided_interactions=avoided_interactions,
        compiled_constraints=compiled_constraints,
        capture_after_choices=depth,
        frontier_out=frontier,
        jump_prediction_safe=jump_prediction_safe,
    )
    if len(frontier) < 2:
        if not frontier:
            return list(incumbent_slice), incumbent_eval, stats
        best_slice, best_eval, resumed_stats = _search_all_input_frames(
            level,
            frames,
            prefix_state=None,
            window_frames=window_frames,
            target_frame=target_frame,
            objective=objective,
            incumbent_slice=incumbent_slice,
            incumbent_eval=incumbent_eval,
            x_window=x_window,
            y_window=y_window,
            required_interactions=required_interactions,
            avoided_interactions=avoided_interactions,
            compiled_constraints=compiled_constraints,
            initial_frontier=frontier,
            jump_prediction_safe=jump_prediction_safe,
        )
        stats.add(resumed_stats)
        return best_slice, best_eval, stats

    batches = _contiguous_frontier_batches(frontier, worker_count)
    shared_frames = tuple(frames)
    shared_window_frames = tuple(window_frames)
    shared_incumbent_slice = tuple(incumbent_slice)
    shared_incumbent = _LocalWindowIncumbent(
        incumbent_eval.score,
        incumbent_eval.feasible,
        incumbent_eval.missing_interactions,
        incumbent_eval.violated_interactions,
    )
    work_items = tuple(
        _LocalWindowWorkItem(
            "all",
            shared_frames,
            shared_window_frames,
            shared_incumbent_slice,
            shared_incumbent,
            frozenset(),
            jump_prediction_safe,
            batch,
        )
        for batch in batches
    )
    best_slice = list(incumbent_slice)
    best_eval = incumbent_eval
    for result in executor.map(_run_local_window_work_item, work_items):
        assert isinstance(result.stats, AllInputWindowStats)
        stats.add(result.stats)
        if result.best_eval is None or result.best_slice is None:
            continue
        if _local_candidate_better(
            result.best_eval,
            frozenset(),
            best_eval,
            frozenset(),
            incumbent_eval=incumbent_eval,
            incumbent_missing_jump_frames=frozenset(),
        ):
            best_slice = result.best_slice
            best_eval = result.best_eval
    return best_slice, best_eval, stats


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
    window_workers: int = 1,
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

    def execute_with_window_pool(
        window_executor: _LazyLocalWindowPool | None,
    ) -> LocalSearchRunResult:
        return _optimise_local_single_run(
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
            initial_evaluation=(
                context.baseline if spec.jump_rng is None else None
            ),
            initial_missing_jump_frames=(
                context.baseline_missing_jump_frames
                if spec.jump_rng is None
                else None
            ),
            frames_are_editable=True,
            window_executor=window_executor,
            window_workers=window_workers,
        )

    if window_workers > 1:
        window_context = _LocalWindowWorkerContext(
            level=context.level,
            target_frame=context.target_frame,
            objective_name=context.objective_name,
            objective_target=context.objective_target,
            x_window=context.x_window,
            y_window=context.y_window,
            physics_prune=context.physics_prune,
            required_jump_frames=run_required_jump_frames,
            required_interactions=context.required_interactions,
            avoided_interactions=context.avoided_interactions,
        )
        with _LazyLocalWindowPool(
            window_workers,
            window_context,
            run_label=spec.label,
            progress=progress,
        ) as window_executor:
            run = execute_with_window_pool(window_executor)
    else:
        run = execute_with_window_pool(None)
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


def _automatic_local_window_worker_count(
    estimated_run_work: int,
    *,
    estimated_windows: int,
    local_inputs: str,
) -> int:
    """Open a persistent DFS pool only when a lone run can amortise IPC."""
    available = _automatic_jump_worker_count()
    if available < 2:
        return 1
    spawn = multiprocessing.get_context().get_start_method() == "spawn"
    minimum_total = 150_000 if spawn else 30_000
    minimum_per_window = 5_000 if spawn else 1_500
    if estimated_run_work < minimum_total:
        return 1
    if estimated_run_work // max(1, estimated_windows) < minimum_per_window:
        return 1
    branch_factor = 3 if local_inputs == "direction" else 6
    frontier_limit = min(available, branch_factor)
    if spawn and estimated_run_work < 300_000:
        frontier_limit = min(frontier_limit, 2)
    return max(1, frontier_limit)


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
    window_executor: _LazyLocalWindowPool | None = None,
    window_workers: int = 1,
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
    compiled_interaction_constraints = _compile_interaction_constraints(
        tuple(required_interactions), tuple(avoided_interactions)
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

        # Forward contiguous windows advance by exactly one frame. Retain the
        # state immediately before the previous window and advance it with the
        # accepted input before the next search, rather than rebuilding every
        # prefix from frame zero.
        incremental_prefix: SimulationState | None = None
        incremental_prefix_start: int | None = None
        use_incremental_prefix = (
            pass_window_shape == "contiguous" and window_order == "forward"
        )
        prefix_cache: dict[int, SimulationState] | None = None
        prefix_cache_starts: set[int] = set()
        if not use_incremental_prefix:
            # Random and sparse windows can revisit the same prefix many times.
            # Cache exact snapshots lazily, invalidating only snapshots whose
            # prefix contains an accepted edit. Reverse contiguous order is a
            # particularly useful case: warming all requested starts once
            # changes an O(window-count * replay-length) setup into one forward
            # walk. COW snapshots isolate the cache from both the warm-up walk
            # and later DFS branches.
            prefix_cache = {}
            prefix_cache_starts = {window.start for window in ordered_windows}
            prefix_cache[0] = level.initial_state()

            def cached_prefix(start: int) -> SimulationState:
                cached = prefix_cache.get(start)
                if cached is not None:
                    return cached
                base_start = max(
                    cached_start
                    for cached_start in prefix_cache
                    if cached_start < start
                )
                walking_prefix = prefix_cache[base_start].clone(
                    copy_on_write_objects=True
                )
                for frame_index in range(base_start, start):
                    if frame_index in prefix_cache_starts:
                        prefix_cache[frame_index] = walking_prefix.clone(
                            copy_on_write_objects=True
                        )
                    if not walking_prefix.player.dead:
                        walking_prefix.step(current[frame_index], level.tiles)
                prefix_cache[start] = walking_prefix
                return walking_prefix

            if pass_window_shape == "contiguous" and window_order == "reverse":
                for start in sorted(prefix_cache_starts):
                    cached_prefix(start)

        for window in ordered_windows:
            if prefix_cache is not None:
                prefix = cached_prefix(window.start)
            elif incremental_prefix is None:
                prefix = state_before_frame(level, current, window.start)
            else:
                assert incremental_prefix_start is not None
                for frame_index in range(
                    incremental_prefix_start, window.start
                ):
                    # ``simulate_through_frame`` also stops after death. The
                    # search will reject this prefix, but continuing to tick a
                    # dead branch here would give it a different frame count.
                    if incremental_prefix.player.dead:
                        break
                    incremental_prefix.step(current[frame_index], level.tiles)
                prefix = incremental_prefix
            if use_incremental_prefix:
                incremental_prefix = prefix
                incremental_prefix_start = window.start
            incumbent_slice = [current[index] for index in window.frames]
            best_slice = list(incumbent_slice)
            description = _local_window_description(
                window, sparse=pass_window_shape == "sparse"
            )
            # With no outstanding hard state, every admissible candidate has
            # the same empty requirement tuple and local ranking is a stable
            # maximum by score.  That comparison is associative, so contiguous
            # DFS frontier batches can be searched independently and merged in
            # their original order.  Repairing non-empty/incomparable hard sets
            # retains the exact serial traversal.
            use_parallel_window = (
                window_executor is not None
                and not current_eval.missing_interactions
                and not current_eval.violated_interactions
                and not current_missing_jump_frames
            )

            if local_inputs == "direction":
                best_eval = current_eval
                best_missing_jump_frames = current_missing_jump_frames
                if use_parallel_window:
                    assert window_executor is not None
                    (
                        best_slice,
                        best_eval,
                        best_missing_jump_frames,
                        stats,
                    ) = _parallel_direction_window(
                        window_executor,
                        window_workers,
                        level,
                        current,
                        prefix_state=prefix,
                        window_frames=window.frames,
                        target_frame=target_frame,
                        objective_name=objective_name,
                        objective=objective,
                        required_jump_frames=required_jump_frames,
                        incumbent_missing_jump_frames=current_missing_jump_frames,
                        incumbent_slice=incumbent_slice,
                        incumbent_eval=best_eval,
                        x_window=x_window,
                        y_window=y_window,
                        physics_prune=physics_prune,
                        required_interactions=required_interactions,
                        avoided_interactions=avoided_interactions,
                        compiled_constraints=compiled_interaction_constraints,
                    )
                else:
                    (
                        best_slice,
                        best_eval,
                        best_missing_jump_frames,
                        stats,
                    ) = _search_direction_frames(
                        level,
                        current,
                        prefix_state=prefix,
                        window_frames=window.frames,
                        target_frame=target_frame,
                        objective_name=objective_name,
                        objective=objective,
                        required_jump_frames=required_jump_frames,
                        incumbent_missing_jump_frames=current_missing_jump_frames,
                        incumbent_slice=incumbent_slice,
                        incumbent_eval=best_eval,
                        x_window=x_window,
                        y_window=y_window,
                        physics_prune=physics_prune,
                        required_interactions=required_interactions,
                        avoided_interactions=avoided_interactions,
                        compiled_constraints=compiled_interaction_constraints,
                    )
                if progress is not None:
                    search_prefix = (
                        "" if run_label == "forward" else f"{run_label}, "
                    )
                    progress(
                        f"{search_prefix}{description} search: "
                        f"nodes={stats.visited_nodes}, leaves={stats.evaluated_leaves}, "
                        f"missed-jump={stats.missed_jump_prunes}, "
                        f"dedup={stats.deduplicated_prunes}, "
                        f"physics={stats.physics_prunes}, dead={stats.dead_prunes}"
                        f", avoided={stats.avoided_interaction_prunes}"
                    )
            else:
                best_missing_jump_frames = frozenset()
                if use_parallel_window:
                    assert window_executor is not None
                    best_slice, best_eval, stats = _parallel_all_input_window(
                        window_executor,
                        window_workers,
                        level,
                        current,
                        prefix_state=prefix,
                        window_frames=window.frames,
                        target_frame=target_frame,
                        objective=objective,
                        incumbent_slice=incumbent_slice,
                        incumbent_eval=current_eval,
                        x_window=x_window,
                        y_window=y_window,
                        required_interactions=required_interactions,
                        avoided_interactions=avoided_interactions,
                        compiled_constraints=compiled_interaction_constraints,
                    )
                else:
                    best_slice, best_eval, stats = _search_all_input_frames(
                        level,
                        current,
                        prefix_state=prefix,
                        window_frames=window.frames,
                        target_frame=target_frame,
                        objective=objective,
                        incumbent_slice=incumbent_slice,
                        incumbent_eval=current_eval,
                        x_window=x_window,
                        y_window=y_window,
                        required_interactions=required_interactions,
                        avoided_interactions=avoided_interactions,
                        compiled_constraints=compiled_interaction_constraints,
                    )
                if progress is not None:
                    search_prefix = (
                        "" if run_label == "forward" else f"{run_label}, "
                    )
                    progress(
                        f"{search_prefix}{description} search: "
                        f"nodes={stats.visited_nodes}, leaves={stats.evaluated_leaves}, "
                        f"inactive-jump={stats.inactive_jump_prunes}, "
                        f"dedup={stats.deduplicated_prunes}, dead={stats.dead_prunes}"
                        f", avoided={stats.avoided_interaction_prunes}"
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
                changed_frames = [
                    frame_index
                    for frame_index, replacement in zip(
                        window.frames, best_slice, strict=True
                    )
                    if current[frame_index] != replacement
                ]
                for frame_index, replacement in zip(
                    window.frames, best_slice, strict=True
                ):
                    current[frame_index] = replacement
                if prefix_cache is not None and changed_frames:
                    earliest_change = min(changed_frames)
                    for cached_start in tuple(prefix_cache):
                        if cached_start > earliest_change:
                            del prefix_cache[cached_start]
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

    # Every accepted candidate carries an exact terminal state from its own
    # prefix/window/fixed-suffix simulation, and the incumbent is never
    # mutated by a later search. Re-simulating the entire replay here only
    # duplicates work; the bookkeeping above tracks the same terminal
    # interaction and jump requirements.
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

    ``workers`` controls process parallelism in either local input mode. When
    several trajectories exist, forward, reverse, and random runs share one
    ordered pool. A lone trajectory keeps greedy windows serial and splits the
    current window's score-ordered DFS frontier whenever its hard-requirement
    sets are empty. ``0`` selects a cost-aware automatic CPU count and ``1``
    keeps the unconditional low-overhead serial path. Worker trajectories and
    frontier batches are merged in original order.

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

    contiguous_count = len(
        _contiguous_local_windows_for_ranges(
            normalized_ranges, effective_window
        )
    )
    if window_shape == "sparse":
        estimated_windows = windows_per_pass or (
            contiguous_count
        )
    elif window_shape == "mixed":
        sparse_count = windows_per_pass or contiguous_count
        sparse_passes = (passes + 1) // 2
        contiguous_passes = passes // 2
        total_windows = (
            sparse_count * sparse_passes
            + contiguous_count * contiguous_passes
        )
        estimated_windows = (total_windows + passes - 1) // passes
    else:
        estimated_windows = contiguous_count
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
    # ordered pool. A lone trajectory instead keeps its greedy window chain in
    # the parent and lends each sufficiently expensive window's DFS frontier to
    # a persistent worker pool.
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
        window_workers = 1
        if len(run_specs) == 1:
            if workers == 0:
                window_workers = _automatic_local_window_worker_count(
                    estimated_run_work,
                    estimated_windows=estimated_windows,
                    local_inputs=local_inputs,
                )
            elif workers > 1:
                branch_factor = 3 if local_inputs == "direction" else 6
                window_workers = min(workers, branch_factor)
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
                window_workers=window_workers,
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

"""Switch-safe stochastic waypoint splicing of an existing completed N TAS.

A waypoint is a spatial *goal*, not permission to ignore the reference's
persistent interactions. Only canonically verified *completed* replays are published: shorter
finishes first, then closer exit approaches at equal frame count. Intermediate splices can be incomplete and are repaired through
later sampled waypoints with Local's population search. Route-control events
are enforced through interaction and replay constraints, not extra waypoints.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import itertools
import random
import time
from collections.abc import Callable, Sequence
from collections import Counter

from nv14_auto import (AutoEvaluation, CompactTracePoint, evaluate_replay_with_sentinel,
                       pre_finish_exit_edge_distance, verify_trimmed_replay)
from nv14_endpoint import EndpointGoal, EndpointEvaluator, verify_endpoint
from nv14_engine import InputFrame, Level
from nv14_objectives import (INTERACTION_GOLD, reference_interaction_requirements,
                             resolve_interaction_target)
from nv14_population import PopulationConfig, optimise_local_population
from nv14_replay import decode_complex_replay, editable_frames, encode_complex_replay, simulate_through_frame


@dataclass(frozen=True, slots=True)
class RandomSpliceConfig:
    points: int = 5
    frames_per_point: int | None = None  # optional one waypoint per N replay frames (rounded)
    distance: float | None = None  # arc-length spacing in pixels; supersedes points
    radius: float = 16.0
    lookback: int = 32  # seam matching/maximum local mutation span, NOT a segment length
    iterations: int = 400  # proposals per worker, per anchor search round
    search_backend: str = "local"  # local population or endpoint Auto hybrid
    endpoint_max_retime: int = 3
    endpoint_mutation_span: int = 24
    endpoint_repair_steps: int = 32
    endpoint_repair_lookback: int = 40
    repair_iterations: int = 250  # Local proposals per subsequent anchor and worker per round
    splice_rounds: int = 1  # backend search rounds PER waypoint, not global Auto runs
    repair_rounds: int = 1  # backend search rounds PER continuation repair
    repair_anchors: int = 2
    beam: int = 16
    workers: int = 1
    rounds: int = 1
    stagnation_rounds: int = 0
    max_repair_searches: int = 8
    frontier: int = 0  # additional cross-waypoint partial beam; CLI defaults to 3
    exit_lookback: int = 96  # minimum editable horizon of the exit approach
    seed: int = 0

    def __post_init__(self) -> None:
        if type(self.points) is not int or self.points < 1:
            raise ValueError("random splice points must be positive")
        if self.frames_per_point is not None and (
            type(self.frames_per_point) is not int or self.frames_per_point < 1
        ):
            raise ValueError("random splice frames_per_point must be a positive integer")
        if self.frames_per_point is not None and self.distance is not None:
            raise ValueError("random splice frames_per_point and distance are alternative spacing modes")
        if self.distance is not None and (not math.isfinite(self.distance) or self.distance <= 0):
            raise ValueError("random splice distance must be positive and finite")
        if not math.isfinite(self.radius) or self.radius <= 0:
            raise ValueError("random splice radius must be positive and finite")
        for field in ("lookback", "iterations", "repair_iterations", "beam", "workers"):
            if type(getattr(self, field)) is not int or getattr(self, field) < 1:
                raise ValueError(f"random splice {field} must be positive")
        for field in ("splice_rounds", "repair_rounds"):
            if type(getattr(self, field)) is not int or getattr(self, field) < 1:
                raise ValueError(f"random splice {field} must be a positive integer")
        if self.search_backend not in ("local", "endpoint-auto"):
            raise ValueError("random splice search_backend must be local or endpoint-auto")
        if not 1 <= self.endpoint_max_retime <= 3:
            raise ValueError("random splice endpoint_max_retime must be between 1 and 3")
        if self.endpoint_mutation_span < 1 or self.endpoint_repair_lookback < 1 or self.endpoint_repair_steps < 0:
            raise ValueError("invalid random splice endpoint mutation/repair parameters")
        if type(self.rounds) is not int or self.rounds < 0:
            raise ValueError("random splice rounds must be nonnegative (0 means continuous)")
        if type(self.stagnation_rounds) is not int or self.stagnation_rounds < 0:
            raise ValueError("random splice stagnation_rounds must be nonnegative")
        if type(self.exit_lookback) is not int or self.exit_lookback < 1:
            raise ValueError("random splice exit_lookback must be positive")
        if type(self.frontier) is not int or self.frontier < 0:
            raise ValueError("random splice frontier must be nonnegative")
        if type(self.max_repair_searches) is not int or self.max_repair_searches < 0:
            raise ValueError("random splice max_repair_searches must be nonnegative")
        if type(self.repair_anchors) is not int or self.repair_anchors < 0:
            raise ValueError("random splice repair_anchors must be nonnegative")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("random splice seed must be nonnegative")


@dataclass(frozen=True, slots=True)
class Waypoint:
    frame: int
    x: float
    y: float
    mandatory: bool = False

    def region(self, radius: float) -> tuple[float, float, float, float]:
        return (self.x - radius, self.x + radius, self.y - radius, self.y + radius)


@dataclass(frozen=True, slots=True)
class RandomSpliceResult:
    frames: tuple[InputFrame, ...]
    waypoints: tuple[Waypoint, ...]
    improvements: int
    attempts: int
    evaluations: int


def _reference_events(evaluation: AutoEvaluation) -> frozenset[tuple[str, int]]:
    """Persistent exact IDs; trapdoor activations are protected as well."""
    return frozenset((event.kind, event.index) for event in evaluation.route_control_events)


def _mask_preserved(reference: CompactTracePoint, candidate: CompactTracePoint) -> bool:
    """No reference interaction already performed by this anchor may vanish."""
    for name in ("open_exit_mask", "opened_locked_door_mask", "triggered_trapdoor_mask"):
        required = getattr(reference, name)
        if getattr(candidate, name) & required != required:
            return False
    return True


def _control_preserved(reference: AutoEvaluation, candidate: AutoEvaluation) -> bool:
    if not _reference_events(reference) <= _reference_events(candidate):
        return False
    if not reference.trace or not candidate.trace:
        return False
    return _mask_preserved(reference.trace[-1], candidate.trace[-1])


def choose_waypoints(reference: AutoEvaluation, config: RandomSpliceConfig,
                     rng: random.Random, *, min_frame: int = 2,
                     max_frame: int | None = None) -> tuple[Waypoint, ...]:
    """Sample path waypoints without adding switch/door/trapdoor anchors.

    `points` sets the exact number when sufficient editable frames exist.
    `frames_per_point` derives the count from the active replay length, rounded
    half up (e.g. 314 frames / 100 -> 3), with at least one waypoint.
    Switch/door/trapdoor safety is enforced at the next selected checkpoint
    and on every accepted complete replay; it must not expand the search count.
    `distance` remains a separate, spacing-based selection mode.
    """
    trace = reference.materialize_trace()
    if len(trace) < 4:
        return ()
    # No first/last-frame goal; these cannot save a meaningful segment.
    limit = min(len(trace) - 2, (reference.finish_tick or len(trace)) - 2)
    if max_frame is not None:
        limit = min(limit, max_frame)
    first = max(2, min_frame)
    if limit < first:
        return ()
    path = [0.0]
    for i in range(1, limit + 1):
        path.append(path[-1] + math.hypot(trace[i].x - trace[i-1].x,
                                          trace[i].y - trace[i-1].y))
    total = path[-1]
    candidates = list(range(first, limit + 1))
    selected: set[int] = set()
    if config.distance is None:
        # Always pick distinct frames. Quantised arc lengths and long stationary
        # stretches used to collapse multiple configured points onto one frame.
        # Frame position breaks arc-length ties, spreading the search budget
        # over the timeline instead of clustering around a stopped ninja.
        available = set(candidates)
        if config.frames_per_point is not None:
            # Include the otherwise-excluded first and last input frames when
            # measuring run length, but restrict endpoint searches to their
            # editable frame interval. The number is re-evaluated after each
            # round, so a shortened replay also gets fewer waypoints.
            active_frames = max(1, limit - first + 4)
            requested = max(1, (2 * active_frames + config.frames_per_point)
                            // (2 * config.frames_per_point))
        else:
            requested = config.points
        count = min(requested, len(available))
        for k in range(1, count + 1):
            jitter = k - 0.5 + rng.random()
            frame_target = first + (limit - first) * jitter / count
            if total > 1e-9:
                distance_target = path[first] + (total - path[first]) * jitter / count
                index = min(available, key=lambda i: (
                    abs(path[i] - distance_target), abs(i - frame_target), i))
            else:
                index = min(available, key=lambda i: (abs(i - frame_target), i))
            selected.add(index)
            available.remove(index)
    elif total > 0:
        # Spacing-based mode deliberately derives its count from distance,
        # unlike splice-points. Neither mode creates extra control anchors.
        for k in range(1, math.ceil(total / config.distance)):
            target = k * config.distance
            if target >= total:
                break
            selected.add(min(candidates, key=lambda i: abs(path[i] - target)))
    return tuple(Waypoint(i, trace[i].x, trace[i].y)
                 for i in sorted(selected))


def _requirements_at(level: Level, frames: Sequence[InputFrame], frame: int):
    state = simulate_through_frame(level, frames, frame)
    # Switch/locked-door requirements, not optional gold for speedrun.
    return tuple(item for item in reference_interaction_requirements(level, state)
                 if all(atom.kind != INTERACTION_GOLD for atom in item.alternatives))


def _goal(level: Level, reference_frames: Sequence[InputFrame], waypoint: Waypoint,
          config: RandomSpliceConfig, *, deadline: int, start: int) -> EndpointGoal:
    return EndpointGoal(
        target_frame=deadline, objective="earliest-arrival",
        target_region=waypoint.region(config.radius),
        arrival_start=max(0, start),
        required_interactions=_requirements_at(level, reference_frames, waypoint.frame),
    )


def _local_search(level: Level, frames: tuple[InputFrame, ...], goal: EndpointGoal,
                  *, start: int, config: RandomSpliceConfig, iterations: int,
                  rounds: int, seed: int, progress: Callable[[str], None] | None = None,
                  editable_end: int | None = None, include_partial: bool = False):
    if start > (goal.target_frame if editable_end is None else editable_end) or goal.target_frame >= len(frames):
        return (), 0
    if config.search_backend == "endpoint-auto":
        # Reuse the exact endpoint Hybrid search and evaluator, but *not* its
        # checkpoint publishing: only random-splice may commit a completed,
        # switch-safe improvement after validating the joined suffix.
        from nv14_auto_endpoint import AutoEndpointConfig, optimise_auto_endpoint_campaign
        auto_config = AutoEndpointConfig(
            iterations=iterations, beam_width=config.beam,
            seed=seed, range_start=start,
            range_end=goal.target_frame if editable_end is None else editable_end,
            max_retime=config.endpoint_max_retime,
            mutation_span=config.endpoint_mutation_span,
            completion_policy="checkpoint",
            repair_steps=config.endpoint_repair_steps,
            repair_lookback=config.endpoint_repair_lookback,
        )
        survivors = []
        baseline, winner, evaluations = optimise_auto_endpoint_campaign(
            level, frames, goal, auto_config, workers=config.workers, runs=rounds,
            progress=progress, frontier_callback=survivors.extend,
            frontier_limit=min(max(6, config.frontier * 3), config.beam),
        )
        # Normal seam searches only offer feasible endpoints. Progressive
        # frontier searches may also carry live near-misses into the next
        # waypoint, where reference-control masks and eventual full completion
        # are checked independently before anything is published.
        candidates = ([winner] if winner is not None and winner.evaluation.feasible else [])
        candidates.extend(survivors)
        selected = []
        seen = set()
        for candidate in candidates:
            if (candidate is not None
                    and (candidate.evaluation.feasible or include_partial)
                    and not candidate.evaluation.dead
                    and candidate.frames not in seen):
                selected.append((candidate.frames, candidate.evaluation.frame))
                seen.add(candidate.frames)
        return tuple(selected), evaluations
    result = optimise_local_population(
        level, frames, goal=goal, frame_ranges=((start,
            goal.target_frame if editable_end is None else editable_end),),
        config=PopulationConfig(
            iterations=iterations, beam=config.beam, rounds=rounds,
            top_results=min(max(6, config.frontier * 3), config.beam), workers=config.workers,
            mutation_span=min(config.lookback, 32), seed=seed,
            repair_steps=min(64, iterations // 4),
            repair_lookback=min(config.lookback, 32),
        ),
        progress=progress,
    )
    # Local population deliberately converts Ctrl+C into a partial result so
    # manual Local searches can retain their feasible endpoints. Random-splice
    # instead owns a multi-anchor, potentially infinite outer campaign: if we
    # ignore this flag, it starts the next anchor and appears immune to Ctrl+C.
    # Propagate *after* Local has stopped and joined its worker pool.
    if getattr(result, "interrupted", False):
        raise KeyboardInterrupt
    candidates = list(result.candidates)
    if include_partial:
        # Local already ranks non-feasible states using required interactions,
        # survival, and squared distance to the target. Expose the population's
        # diverse near-miss frontier rather than silently discarding it.
        candidates.extend(getattr(result, "frontier", ()))
    seen: set[tuple[InputFrame, ...]] = set()
    selected: list[tuple[tuple[InputFrame, ...], int]] = []
    for item in candidates:
        if (item.evaluation.feasible or include_partial) and item.frames not in seen:
            selected.append((item.frames, item.evaluation.frame))
            seen.add(item.frames)
    return tuple(selected), result.evaluations


def _candidate_seams(reference: AutoEvaluation, candidate: AutoEvaluation,
                     anchor: Waypoint, earliest: int, config: RandomSpliceConfig
                     ) -> tuple[tuple[int, int], ...]:
    """Find nearby post-step states to splice, using velocity/contact as well.

    Reaching a broad rectangle early is insufficient: arrival velocity may be
    wrong for the reference suffix. Search for a compatible *state* near the
    waypoint, not simply the first position inside the rectangle.
    """
    candidates: list[tuple[float, int, int, int]] = []
    low_r = max(1, anchor.frame - config.lookback // 2)
    high_r = min((reference.finish_tick or anchor.frame) - 2,
                 anchor.frame + config.lookback // 2)
    for r in range(low_r, high_r + 1):
        ref = reference.point(r)
        if ref is None or ref.dead or ref.complete:
            continue
        for t in range(max(1, earliest - config.lookback // 2),
                       min(r - 1, len(candidate.trace) - 2,
                           earliest + config.lookback) + 1):
            state = candidate.point(t)
            if (state is None or state.dead or state.complete
                    or not _mask_preserved(ref, state)):
                continue
            dx = math.hypot(state.x - ref.x, state.y - ref.y)
            dv = math.hypot(state.vx - ref.vx, state.vy - ref.vy)
            if dx > config.radius or dv > 1.25:
                continue
            # Contact mismatches often invalidate seemingly perfect x/y seams.
            contact = 0.0 if state.contact_key == ref.contact_key else 8.0
            score = dx + 5.0 * dv + contact
            candidates.append((score, -(r - t), t, r))
    candidates.sort()
    # Keep some diversity while never attempting an unlimited number of seams.
    return tuple((t, r) for _score, _lead, t, r in candidates[:12])


def _segment_start(waypoints: Sequence[Waypoint], index: int) -> int:
    """Optimise the *entire* interval since the previous waypoint.

    The preceding waypoint is an immutable checkpoint. Starting one frame
    later keeps the previously verified trajectory and its switch state intact.
    The first interval starts at frame zero.
    """
    return 0 if index == 0 else waypoints[index - 1].frame + 1


def _repair_window_start(
    provisional: AutoEvaluation, *, suggested: int, immutable_end: int,
) -> int | None:
    """Move a continuation repair before a fatal tick, without editing its seam.

    A newly joined suffix can kill the ninja before the next waypoint's normal
    lookback begins. Local population is right to reject that immutable dead
    prefix; random splicing must either expand the window to cover the death
    or try another seam if the ninja died inside the already-committed prefix.
    """
    start = suggested
    if provisional.dead_tick is not None and provisional.dead_tick < start:
        start = provisional.dead_tick
    if provisional.finish_tick is not None and provisional.finish_tick < start:
        # Completion is also terminal: no later input can repair the prefix.
        return None
    if start <= immutable_end:
        return None
    return start


# Completed speedrun Auto ranks every genuine exit-distance improvement;
# stagnation uses a separate 0.5px significance threshold per outer round.
_MIN_EXIT_DISTANCE_GAIN = 0.5


def _completed_improvement_kind(reference: AutoEvaluation, reference_length: int,
                                candidate: AutoEvaluation, candidate_length: int,
                                ) -> str | None:
    """Compare canonically verified completions: finish first, door second."""
    if not candidate.valid or candidate.finish_tick != candidate_length:
        return None
    if candidate_length < reference_length:
        return "speedrun"
    if candidate_length != reference_length:
        return None
    old = reference.pre_finish_exit_distance
    new = candidate.pre_finish_exit_distance
    if (old is not None and new is not None and math.isfinite(old)
            and math.isfinite(new) and old - new > 1e-9):
        return "proximity"
    return None


def _significant_progress(reference: AutoEvaluation, reference_length: int,
                          candidate: AutoEvaluation, candidate_length: int) -> bool:
    kind = _completed_improvement_kind(reference, reference_length,
                                       candidate, candidate_length)
    if kind == "speedrun":
        return True
    if kind != "proximity":
        return False
    assert reference.pre_finish_exit_distance is not None
    assert candidate.pre_finish_exit_distance is not None
    return (reference.pre_finish_exit_distance - candidate.pre_finish_exit_distance
            >= _MIN_EXIT_DISTANCE_GAIN - 1e-9)


def _completed_rank(evaluation: AutoEvaluation, length: int) -> tuple[float, float]:
    distance = evaluation.pre_finish_exit_distance
    return (float(length), float(distance) if distance is not None and math.isfinite(distance)
            else math.inf)


def _improvement_description(level: Level, reference: AutoEvaluation,
                             old_length: int, candidate: AutoEvaluation,
                             new_length: int, where: str) -> str:
    kind = _completed_improvement_kind(reference, old_length, candidate, new_length)
    if kind == "speedrun":
        return (f"[auto:random-splice] speedrun improved: {old_length} -> "
                f"{new_length} frames {where}")
    old_gap = pre_finish_exit_edge_distance(level, reference)
    new_gap = pre_finish_exit_edge_distance(level, candidate)
    return (f"[auto:random-splice] exit proximity improved: {new_length} frames, "
            f"{old_gap:.2f}px -> {new_gap:.2f}px {where}")


def _validated_improvement(level: Level, proposal: Sequence[InputFrame],
                           reference: AutoEvaluation, original_length: int
                           ) -> tuple[InputFrame, ...] | None:
    """Require canonical completion, route controls, and a better speedrun rank.

    A shorter finish always wins. At the same frame count, accept a strictly
    smaller pre-finish exit distance. Stagnation resets for >=0.5px per round.
    """
    packed = tuple(editable_frames(decode_complex_replay(encode_complex_replay(proposal)).frames))
    evaluation = evaluate_replay_with_sentinel(level, packed)
    if not evaluation.valid or evaluation.finish_tick is None:
        return None
    if evaluation.finish_tick > original_length:
        return None
    body = packed[:evaluation.finish_tick]
    # In both cases the output must finish on its new implicit neutral sentinel.
    try:
        verified = verify_trimmed_replay(level, body)
    except ValueError:
        return None
    if not _control_preserved(reference, verified):
        return None
    return (body if _completed_improvement_kind(reference, original_length,
                                               verified, len(body)) is not None else None)


def _exit_segment_start(finish: int, previous_end: int, lookback: int) -> int:
    """Allow the exit objective to repair a useful approach, not 2-5 final frames.

    Sampled path checkpoints help exploration, but do not constrain
    the last speedrun improvement: it is safe to revisit earlier checkpoints
    because the endpoint goal and final canonical replay must preserve every
    required control interaction. This overlap is essential after an earlier
    waypoint produced a slightly mismatched velocity or contact state.
    """
    return min(previous_end + 1, max(0, finish - lookback))


def _progressive_frontier(
    level: Level, current: tuple[InputFrame, ...], reference: AutoEvaluation,
    waypoints: tuple[Waypoint, ...], config: RandomSpliceConfig, rng: random.Random,
    progress: Callable[[str], None] | None,
) -> tuple[tuple[InputFrame, ...] | None, int, int, Counter]:
    """Carry surviving, interaction-safe *partial* routes across waypoint boundaries.

    The normal splice path requires immediate suffix compatibility. This path
    deliberately does not: each candidate's edited prefix is frozen at the
    previous waypoint while another complete interval is optimised. Near-misses
    are ranked using EndpointEvaluator.progress_key (including exit distance)
    and are never published unless full canonical completion is later proven.
    """
    counters: Counter = Counter()
    if not config.frontier:
        return None, 0, 0, counters
    branches: list[tuple[InputFrame, ...]] = [current]
    evaluations = attempts = 0
    previous_end = -1
    for index, waypoint in enumerate(waypoints):
        start = previous_end + 1
        goal = _goal(level, current, waypoint, config, deadline=waypoint.frame, start=start)
        reference_point = reference.point(waypoint.frame)
        if reference_point is None:
            break
        proposals: list[tuple[tuple, tuple[InputFrame, ...], bool]] = []
        for branch_index, branch in enumerate(branches):
            attempts += 1
            if progress:
                progress(f"[auto:random-splice] frontier {index+1}/{len(waypoints)} "
                         f"branch {branch_index+1}/{len(branches)}: "
                         f"searching [{start}:{waypoint.frame}]")
            try:
                found, used = _local_search(
                    level, branch, goal, start=start, config=config,
                    iterations=max(20, config.iterations // 2),
                    rounds=config.splice_rounds, seed=rng.getrandbits(63),
                    include_partial=True,
                )
            except ValueError as exc:
                if str(exc).startswith("the immutable prefix dies before the editable ranges"):
                    counters["dead_immutable_prefix"] += 1
                    continue
                raise
            evaluations += used
            # Retain the parent alongside mutations; it might still be the
            # optimal starting point when the next anchor is considered.
            for trial, _tick in (*found, (branch, waypoint.frame)):
                simulation = evaluate_replay_with_sentinel(level, trial)
                point = simulation.point(waypoint.frame)
                if point is None or (point.dead and not point.complete):
                    counters["dead_before_waypoint"] += 1
                    continue
                if not _mask_preserved(reference_point, point):
                    counters["missing_control_at_waypoint"] += 1
                    continue
                endpoint = EndpointEvaluator(level, goal).evaluate(trial)
                if endpoint.violated_interactions:
                    counters["forbidden_interaction"] += 1
                    continue
                if not endpoint.feasible:
                    counters["near_miss_carried"] += 1
                proposals.append((endpoint.progress_key, trial, endpoint.feasible))
        if not proposals:
            # A verified reference always survives its own checkpoint. This
            # protects a frontier whose mutated branches all lost switches.
            fallback = EndpointEvaluator(level, goal).evaluate(current)
            proposals.append((fallback.progress_key, current, fallback.feasible))
            counters["reference_fallbacks"] += 1
        # Keep a feasible majority if available and at least one near miss.
        # Niche diversity is based on physical state at the checkpoint.
        # Preserve the known-completed reference as a non-negotiable fallback.
        # Without it, a frontier of invalid switch states can evict the only
        # interaction-safe path, and the search never reaches the EXIT stage.
        if not any(trial == current for _key, trial, _feasible in proposals):
            ref_endpoint = EndpointEvaluator(level, goal).evaluate(current)
            proposals.append((ref_endpoint.progress_key, current, ref_endpoint.feasible))
        ranked = sorted(proposals, key=lambda c: c[0])
        selected: list[tuple[InputFrame, ...]] = []
        state_niches: set[tuple] = set()
        def offer(trial: tuple[InputFrame, ...]) -> None:
            if trial in selected:
                return
            point = evaluate_replay_with_sentinel(level, trial).point(waypoint.frame)
            if point is None:
                return
            niche = (round(point.x / 4), round(point.y / 4),
                     round(point.vx * 2), round(point.vy * 2),
                     point.open_exit_mask, point.opened_locked_door_mask,
                     point.triggered_trapdoor_mask)
            if niche not in state_niches:
                selected.append(trial)
                state_niches.add(niche)
        offer(current)
        for _rank, trial, _feasible in ranked:
            if len(selected) >= config.frontier:
                break
            offer(trial)
        # Preserve one distinct incomplete approach even if feasible candidates
        # filled the beam: it may catch up at a later waypoint.
        if config.frontier > 1 and all(feasible for _key, trial, feasible in ranked if trial in selected):
            for _key, trial, feasible in ranked:
                if not feasible and trial not in selected:
                    if len(selected) >= config.frontier:
                        if len(selected) <= 1:
                            break
                        selected.pop()
                    offer(trial)
                    break
        branches = selected or [current]
        counters["reference_branch_preserved"] += int(current in branches)
        previous_end = waypoint.frame
        counters["retained_branches"] += len(branches)
        if progress:
            progress(f"[auto:random-splice] frontier waypoint {waypoint.frame}: "
                     f"retained {len(branches)} branches, "
                     f"{counters['near_miss_carried']} near-miss candidates seen; "
                     "verified reference retained")

    # Search the entire last interval from each retained prefix to the exit.
    finish = len(current)
    start = _exit_segment_start(finish, previous_end, config.exit_lookback)
    if start >= finish:
        return None, attempts, evaluations, counters
    exit_target = resolve_interaction_target(level, f"exit:{reference.completed_exit_index}")
    goal = EndpointGoal(target_frame=finish, objective="earliest-interaction",
                        interaction_target=exit_target, arrival_start=start,
                        exit_distance_tiebreak=True,
                        required_interactions=_requirements_at(level, current, finish - 1))
    best_completion: tuple[InputFrame, ...] | None = None
    best_completion_rank: tuple[float, float] | None = None
    min_exit_gap = math.inf
    door = level.static_world.entry_for_ref(
        level.static_world.exit_door_ref(reference.completed_exit_index))
    edge_sum = (level.player.r + door.r) if door is not None else 0.0
    for branch_index, branch in enumerate(branches):
        attempts += 1
        if progress:
            progress(f"[auto:random-splice] frontier EXIT branch {branch_index+1}/{len(branches)} "
                     f"searching [{start}:{finish-1}]")
        frontier_exit_progress = {} if progress is None else {
            "progress": lambda text, index=branch_index: progress(
                f"[auto:random-splice] frontier EXIT branch {index+1}: "
                + text.removeprefix("[local:population] ")),
        }
        found, used = _local_search(
            level, branch + (InputFrame(),), goal, start=start,
            editable_end=finish-1, config=config, iterations=config.iterations,
            rounds=config.splice_rounds, seed=rng.getrandbits(63),
            include_partial=True, **frontier_exit_progress,
        )
        evaluations += used
        for trial, _tick in found:
            endpoint = EndpointEvaluator(level, goal).evaluate(trial)
            if not endpoint.feasible:
                counters["exit_near_misses"] += 1
                if math.isfinite(endpoint.target_distance):
                    min_exit_gap = min(min_exit_gap, endpoint.target_distance - edge_sum)
                continue
            validated = _validated_improvement(level, trial, reference, len(current))
            if validated is None:
                counters["exit_unverified"] += 1
            else:
                completed_eval = evaluate_replay_with_sentinel(level, validated)
                rank = _completed_rank(completed_eval, len(validated))
                if best_completion_rank is None or rank < best_completion_rank:
                    best_completion = validated
                    best_completion_rank = rank
    if progress:
        distance = (f"{min_exit_gap:.2f}px edge gap" if math.isfinite(min_exit_gap)
                    else "no measurable near miss")
        progress(f"[auto:random-splice] frontier EXIT: "
                 f"{counters['exit_near_misses']} near misses; closest {distance}; "
                 f"{counters['exit_unverified']} unverified completions; "
                 f"{'best '+str(len(best_completion))+' frames' if best_completion else 'no better completion'}")
    return best_completion, attempts, evaluations, counters


def _optimise_target_splices(
    level: Level, source_frames: Sequence[InputFrame], config: RandomSpliceConfig,
    goal: EndpointGoal, *, range_start: int, range_end: int | None,
    completion_policy: str,
    best_callback: Callable[[tuple[InputFrame, ...]], None] | None,
    progress: Callable[[str], None] | None,
) -> RandomSpliceResult:
    """Optimise a specified Local endpoint through sampled splice checkpoints.

    Checkpoint results may be incomplete after the specified target: they must
    satisfy the independently verified endpoint goal, not a *different* exit
    goal. Entire prefix-to-checkpoint intervals are editable, and near-miss
    branches feed into the final Local goal search. A no-op source is never
    published as an improvement.
    """
    if completion_policy not in ("checkpoint", "complete"):
        raise ValueError("completion-policy must be checkpoint or complete")
    current = tuple(editable_frames(source_frames))
    if goal.target_frame >= len(current):
        raise ValueError("target-frame lies beyond the supplied replay; add input frames")
    last_editable = min(goal.target_frame, len(current) - 1,
                        goal.target_frame if range_end is None else range_end)
    if not 0 <= range_start <= last_editable:
        raise ValueError("editable range is empty or lies beyond target-frame")
    rng = random.Random(config.seed)
    attempts = evaluations = improvements = stagnant = 0
    last_waypoints: tuple[Waypoint, ...] = ()
    source_reference = evaluate_replay_with_sentinel(level, current)
    target_source_point = source_reference.point(goal.target_frame)

    def validated(frames: Sequence[InputFrame]):
        packed = tuple(editable_frames(decode_complex_replay(
            encode_complex_replay(frames)).frames))
        # Switch, locked door and trapdoor states already taken at the target
        # may not be lost. The goal's own required/avoided interactions remain
        # checked by the independent endpoint evaluator.
        if target_source_point is not None:
            point = evaluate_replay_with_sentinel(level, packed).point(goal.target_frame)
            if point is None or not _mask_preserved(target_source_point, point):
                return None
        checked = verify_endpoint(level, packed, goal)
        if not checked.feasible:
            return None
        if completion_policy == "complete":
            complete = evaluate_replay_with_sentinel(level, packed)
            if not complete.valid or complete.finish_tick != len(packed):
                return None
            # Only routes whose relevant controls are preserved are eligible.
            if not _control_preserved(source_reference, complete):
                return None
        return packed, checked

    best = validated(current)
    if progress:
        if best is None:
            progress(f"[auto:random-splice:goal:baseline] source is not feasible for "
                     f"{goal.objective} at target frame {goal.target_frame}")
        else:
            e = best[1]
            progress(f"[auto:random-splice:goal:baseline] source feasible for "
                     f"{goal.objective}; frame {e.frame}; score {e.score:.12g}"
                     + (f"; secondary {goal.secondary_objective}={e.secondary_value:.15g}"
                        if goal.secondary_objective is not None else ""))

    def consider(frames: Sequence[InputFrame], context: str) -> bool:
        nonlocal best, improvements, current
        candidate = validated(frames)
        if candidate is None:
            return False
        if best is not None and not candidate[1].objective_key < best[1].objective_key:
            return False
        best = candidate
        current = candidate[0]
        improvements += 1
        if best_callback:
            best_callback(current)
        if progress:
            progress(f"[auto:random-splice:goal] improved {goal.objective} "
                     f"at frame {candidate[1].frame}, score {candidate[1].score:.12g}"
                     f" ({context}); verified and saved")
        return True

    for round_no in (itertools.count() if config.rounds == 0 else range(config.rounds)):
        round_start = time.monotonic()
        reference = evaluate_replay_with_sentinel(level, current)
        waypoints = choose_waypoints(
            reference, config, rng,
            min_frame=max(2, range_start), max_frame=last_editable - 1)
        last_waypoints = waypoints
        if progress:
            progress(f"[auto:random-splice:goal] round {round_no+1}/{config.rounds or chr(8734)}: "
                     f"{len(waypoints)} splice checkpoints, final {goal.objective} "
                     f"at frame {goal.target_frame}, editable {range_start}:{last_editable}")
        # Keep the reference and several physically diverse partial candidates.
        # This is the same Local checkpoint/evaluation engine as speedrun's
        # progressive frontier, but its final endpoint is the user goal.
        branches: list[tuple[InputFrame, ...]] = [current]
        previous_end = range_start - 1
        improved_round = False
        for index, point in enumerate(waypoints):
            start = max(range_start, previous_end + 1)
            if start > point.frame:
                continue
            stage_goal = _goal(level, current, point, config,
                               deadline=point.frame, start=start)
            required_point = reference.point(point.frame)
            offerings: list[tuple[tuple, tuple[InputFrame, ...]]] = []
            for branch in branches:
                attempts += 1
                if progress:
                    progress(f"[auto:random-splice:goal] checkpoint {index+1}/{len(waypoints)} "
                             f"frame {point.frame}; {'Local' if config.search_backend == 'local' else 'endpoint-auto'} range [{start}:{point.frame}]")
                try:
                    found, used = _local_search(
                        level, branch, stage_goal, start=start, config=config,
                        iterations=config.iterations, rounds=config.splice_rounds,
                        seed=rng.getrandbits(63), include_partial=True)
                except ValueError as exc:
                    if not str(exc).startswith("the immutable prefix dies before the editable ranges"):
                        raise
                    found, used = (), 0
                evaluations += used
                for trial, _arrival in (*found, (branch, point.frame)):
                    if trial == branch and any(existing == trial for _, existing in offerings):
                        continue
                    stage_eval = evaluate_replay_with_sentinel(level, trial)
                    check_point = stage_eval.point(point.frame)
                    if (required_point is not None and
                            (check_point is None or not _mask_preserved(required_point, check_point))):
                        continue
                    check = EndpointEvaluator(level, stage_goal).evaluate(trial)
                    if check.violated_interactions:
                        continue
                    rank = check.progress_key
                    offerings.append((rank, trial))
                    improved_round = consider(trial, f"checkpoint {point.frame}") or improved_round
            if offerings:
                offerings.sort(key=lambda item: item[0])
                unique: list[tuple[InputFrame, ...]] = [current]
                for _, trial in offerings:
                    if trial not in unique:
                        unique.append(trial)
                    if len(unique) >= max(2, config.frontier):
                        break
                branches = unique
            else:
                branches = [current]
            previous_end = point.frame
        final_start = _exit_segment_start(last_editable, previous_end,
                                          config.exit_lookback)
        final_start = max(range_start, min(last_editable, final_start))
        # On an incomplete source, a dead immutable prefix must be editable.
        if reference.dead_tick is not None and reference.dead_tick < final_start:
            final_start = range_start
        for index, branch in enumerate(dict.fromkeys((*branches, current))):
            attempts += 1
            if progress:
                progress(f"[auto:random-splice:goal] TARGET branch {index+1}, "
                         f"{'Local' if config.search_backend == 'local' else 'endpoint-auto'} range [{final_start}:{last_editable}]")
            try:
                found, used = _local_search(
                    level, branch, goal, start=final_start, editable_end=last_editable,
                    config=config, iterations=config.iterations,
                    rounds=config.splice_rounds, seed=rng.getrandbits(63))
            except ValueError as exc:
                if not str(exc).startswith("the immutable prefix dies before the editable ranges"):
                    raise
                found, used = (), 0
            evaluations += used
            for trial, _ in found:
                improved_round = consider(trial, "final target") or improved_round
        stagnant = 0 if improved_round else stagnant + 1
        if progress:
            status = (f"best score {best[1].score:.12g}, frame {best[1].frame}"
                      if best is not None else "no feasible target yet")
            progress(f"[auto:random-splice:goal] round {round_no+1} done in "
                     f"{time.monotonic()-round_start:.1f}s; {status}; "
                     f"{evaluations} evaluations; stagnant {stagnant}")
        if config.stagnation_rounds and stagnant >= config.stagnation_rounds:
            break
    return RandomSpliceResult(current, last_waypoints, improvements, attempts, evaluations)


def optimise_random_splices(
    level: Level, source_frames: Sequence[InputFrame], config: RandomSpliceConfig,
    *, best_callback: Callable[[tuple[InputFrame, ...]], None] | None = None,
    progress: Callable[[str], None] | None = None,
    target_goal: EndpointGoal | None = None, range_start: int = 0,
    range_end: int | None = None, completion_policy: str = "checkpoint",
) -> RandomSpliceResult:
    """Try earlier local arrivals, shift reference suffix, repair subsequent anchors.

    No partial replay is committed. After a splice, each reachable later
    waypoint becomes a *required* state-repair target with the reference's
    switch/door history; failure abandons that splice, not its constraints.
    """
    if target_goal is not None:
        return _optimise_target_splices(
            level, source_frames, config, target_goal, range_start=range_start,
            range_end=range_end, completion_policy=completion_policy,
            best_callback=best_callback, progress=progress)
    current = tuple(editable_frames(source_frames))
    verified = evaluate_replay_with_sentinel(level, current)
    if not verified.valid or verified.finish_tick != len(current):
        raise ValueError("random splicing needs a replay finishing on its neutral sentinel")
    first_reference = verified
    if progress:
        distance = pre_finish_exit_edge_distance(level, verified)
        gap = f"; distance to exit {distance:.2f}" if distance is not None else ""
        progress(f"[auto:random-splice:baseline] verified completion at "
                 f"frame {verified.finish_tick}{gap}")
    rng = random.Random(config.seed)
    improvements = attempts = evaluations = 0
    stagnant = 0
    last_waypoints: tuple[Waypoint, ...] = ()
    for round_no in (itertools.count() if config.rounds == 0 else range(config.rounds)):
        # Re-sample against the *current best* route after each round.
        reference = evaluate_replay_with_sentinel(level, current)
        waypoints = choose_waypoints(reference, config, rng)
        last_waypoints = waypoints
        if progress:
            progress(f"[auto:random-splice] round {round_no+1}/{config.rounds or chr(8734)}: "
                     f"{len(waypoints)} waypoints "
                     f"({len(reference.route_control_events)} control events constrained; "
                     "no additional control anchors)")
        round_start = time.monotonic()
        round_improved = False
        round_significant = False
        for i, anchor in enumerate(waypoints):
            if anchor.frame >= len(current) - 1:
                continue
            attempts += 1
            start = _segment_start(waypoints, i)
            label = f"anchor {i+1}/{len(waypoints)} frame {anchor.frame}"
            if progress:
                progress(f"[auto:random-splice] {label}: preparing checkpoint "
                         f"and reference interaction requirements")
            goal = _goal(level, current, anchor, config, deadline=anchor.frame, start=start)
            if progress:
                progress(f"[auto:random-splice] {label}: searching FULL segment "
                         f"[{start}:{anchor.frame}] ({anchor.frame-start+1} editable frames); "
                         f"{config.workers} workers x {config.iterations} proposals "
                         f"x {config.splice_rounds} {'Local' if config.search_backend == 'local' else 'endpoint-auto'} rounds")
            stage_start = time.monotonic()
            search_kw = {} if progress is None else {
                "progress": lambda text, label=label: progress(
                    f"[auto:random-splice] {label}: "
                    + text.removeprefix("[local:population] "))
            }
            found, used = _local_search(level, current, goal, start=start, config=config,
                                        iterations=config.iterations, rounds=config.splice_rounds,
                                        seed=rng.getrandbits(63),
                                        **search_kw)
            evaluations += used
            if progress:
                progress(f"[auto:random-splice] {label}: search finished in "
                         f"{time.monotonic()-stage_start:.1f}s, "
                         f"{used} unique evaluations, {len(found)} feasible candidates")
            repair_searches = 0
            repair_cap_reported = False
            improved = False
            for frames, arrival in found:
                if arrival >= anchor.frame:
                    continue
                candidate_eval = evaluate_replay_with_sentinel(level, frames)
                seams = _candidate_seams(reference, candidate_eval, anchor,
                                         arrival, config)
                # Broad-region arrival remains a fallback when no aligned seam
                # exists. Every attempt still requires full replay validation.
                if not seams:
                    seams = ((arrival, anchor.frame),)
                for cut_tick, reference_tick in seams:
                    must = reference.point(reference_tick)
                    seen = candidate_eval.point(cut_tick)
                    if seen is None or must is None or not _mask_preserved(must, seen):
                        continue
                    joined = tuple(frames[:cut_tick + 1]) + tuple(current[reference_tick + 1:])
                    result = _validated_improvement(level, joined, reference, len(current))
                    provisional = joined
                    if result is None:
                        provisional_eval = evaluate_replay_with_sentinel(level, provisional)
                        # Each successful checkpoint freezes the preceding
                        # segment, while the next repair may edit the full
                        # remaining interval up to the next anchor.
                        immutable_end = cut_tick
                        for next_anchor in waypoints[i + 1:i + 1 + config.repair_anchors]:
                            shift = reference_tick - cut_tick
                            deadline = next_anchor.frame - shift
                            if not 1 <= deadline < len(provisional):
                                break
                            repair_start = _repair_window_start(
                                provisional_eval,
                                suggested=immutable_end + 1,
                                immutable_end=immutable_end,
                            )
                            if repair_start is None or repair_start > deadline:
                                # A terminal prefix cannot be fixed without
                                # changing the candidate's already-frozen seam.
                                break
                            repair_goal = _goal(level, current, next_anchor, config,
                                                deadline=deadline, start=repair_start)
                            if repair_searches >= config.max_repair_searches:
                                if progress and not repair_cap_reported:
                                    progress(f"[auto:random-splice] {label}: continuation repair "
                                             f"limit reached ({config.max_repair_searches} searches)")
                                    repair_cap_reported = True
                                break
                            repair_searches += 1
                            if progress:
                                progress(f"[auto:random-splice] {label}: continuation repair "
                                         f"{repair_searches}/{config.max_repair_searches}, "
                                         f"range [{repair_start}:{deadline}], "
                                         f"{config.workers} workers x {config.repair_iterations} proposals "
                                         f"x {config.repair_rounds} {'Local' if config.search_backend == 'local' else 'endpoint-auto'} rounds")
                            repair_start_time = time.monotonic()
                            repair_progress_kw = {} if progress is None else {
                                "progress": lambda text, label=label: progress(
                                    f"[auto:random-splice] {label}: repair: "
                                    + text.removeprefix("[local:population] "))
                            }
                            try:
                                repaired, used = _local_search(
                                    level, provisional, repair_goal,
                                    start=repair_start, config=config,
                                    iterations=config.repair_iterations,
                                    rounds=config.repair_rounds, seed=rng.getrandbits(63),
                                    **repair_progress_kw)
                            except ValueError as exc:
                                if not str(exc).startswith("the immutable prefix dies before the editable ranges"):
                                    raise
                                # Defensive fallback if the Local preflight
                                # reports a fatal prefix we could not rewind.
                                break
                            evaluations += used
                            if progress:
                                progress(f"[auto:random-splice] {label}: repair "
                                         f"{repair_searches} completed in "
                                         f"{time.monotonic()-repair_start_time:.1f}s; "
                                         f"{used} evaluations, {len(repaired)} feasible candidates")
                            next_provisional = None
                            for trial, when in repaired:
                                stage_eval = evaluate_replay_with_sentinel(level, trial)
                                before = reference.point(next_anchor.frame)
                                after = stage_eval.point(when)
                                if before is not None and after is not None and _mask_preserved(before, after):
                                    next_provisional = trial
                                    provisional_eval = stage_eval
                                    immutable_end = when
                                    break
                            if next_provisional is None:
                                break
                            provisional = next_provisional
                            result = _validated_improvement(level, provisional, reference, len(current))
                            if result is not None:
                                break
                    if result is not None:
                        final_eval = evaluate_replay_with_sentinel(level, result)
                        if (_control_preserved(first_reference, final_eval)
                                and _completed_improvement_kind(
                                    reference, len(current), final_eval, len(result)) is not None):
                            message = _improvement_description(
                                level, reference, len(current), final_eval, len(result),
                                f"at anchor {anchor.frame} (lead {reference_tick-cut_tick})")
                            round_significant = _significant_progress(
                                reference, len(current), final_eval, len(result))
                            current = result
                            improvements += 1
                            improved = True
                            round_improved = True
                            if best_callback:
                                best_callback(current)
                            if progress:
                                progress(message)
                        break
                if improved:
                    break
            if improved:
                # Never use the previous trace's anchors on a changed route.
                break
        # The last sampled waypoint is never the actual exit. Search the entire
        # remaining interval as a final Local segment, targeting the *fresh exit
        # completion interaction*, not merely a position near the exit door.
        # Keep the game's implicit neutral completion step immutable: the search
        # input is one frame longer than the serialized TAS, and the final
        # sentinel is not editable. Only a canonically verified shorter run is
        # eligible for publication.
        if not round_improved:
            exit_deadline = len(current)
            exit_start = _exit_segment_start(
                exit_deadline, waypoints[-1].frame if waypoints else -1,
                config.exit_lookback,
            )
            if exit_start < exit_deadline:
                attempts += 1
                exit_goal = EndpointGoal(
                    target_frame=exit_deadline, objective="earliest-interaction",
                    exit_distance_tiebreak=True,
                    interaction_target=resolve_interaction_target(
                        level, f"exit:{reference.completed_exit_index}"),
                    arrival_start=exit_start,
                    required_interactions=_requirements_at(level, current, exit_deadline - 1),
                )
                if progress:
                    progress(f"[auto:random-splice] EXIT segment [{exit_start}:{exit_deadline - 1}] "
                             f"({exit_deadline-exit_start} editable frames); "
                             f"{config.workers} workers x {config.iterations} proposals "
                             f"x {config.splice_rounds} {'Local' if config.search_backend == 'local' else 'endpoint-auto'} rounds")
                stage_start = time.monotonic()
                exit_progress = {} if progress is None else {
                    "progress": lambda text: progress(
                        "[auto:random-splice] EXIT: "
                        + text.removeprefix("[local:population] "))
                }
                found, used = _local_search(
                    level, current + (InputFrame(),), exit_goal,
                    start=exit_start, editable_end=exit_deadline - 1,
                    config=config, iterations=config.iterations,
                    rounds=config.splice_rounds, seed=rng.getrandbits(63),
                    **exit_progress,
                )
                evaluations += used
                if progress:
                    progress(f"[auto:random-splice] EXIT search finished in "
                             f"{time.monotonic()-stage_start:.1f}s, "
                             f"{used} evaluations, {len(found)} feasible candidates")
                for proposal, _event_tick in found:
                    shorter = _validated_improvement(level, proposal, reference, len(current))
                    if shorter is None:
                        continue
                    verified_exit = evaluate_replay_with_sentinel(level, shorter)
                    if not _control_preserved(first_reference, verified_exit):
                        continue
                    message = _improvement_description(
                        level, reference, len(current), verified_exit, len(shorter),
                        "via EXIT segment")
                    round_significant = _significant_progress(
                        reference, len(current), verified_exit, len(shorter))
                    current = shorter
                    improvements += 1
                    round_improved = True
                    if best_callback:
                        best_callback(current)
                    if progress:
                        progress(message)
                    break
        # Full-route multi-splice fallback: preserve useful partial edits across
        # waypoint boundaries even when no single splice fits the old suffix.
        if not round_improved and config.frontier:
            proposal, extra_attempts, extra_evaluations, diagnostic = _progressive_frontier(
                level, current, reference, waypoints, config, rng, progress)
            attempts += extra_attempts
            evaluations += extra_evaluations
            if proposal is not None:
                final_eval = evaluate_replay_with_sentinel(level, proposal)
                if (_control_preserved(first_reference, final_eval)
                        and _completed_improvement_kind(
                            reference, len(current), final_eval, len(proposal)) is not None):
                    message = _improvement_description(
                        level, reference, len(current), final_eval, len(proposal),
                        "via progressive multi-splice")
                    round_significant = _significant_progress(
                        reference, len(current), final_eval, len(proposal))
                    current = proposal
                    improvements += 1
                    round_improved = True
                    if best_callback:
                        best_callback(current)
                    if progress:
                        progress(message)
            if progress:
                progress(f"[auto:random-splice] frontier diagnostics: "
                         + ", ".join(f"{name}={count}" for name, count in sorted(diagnostic.items())))
        stagnant = 0 if round_significant else stagnant + 1
        if progress:
            progress(f"[auto:random-splice] round {round_no+1} completed in "
                     f"{time.monotonic()-round_start:.1f}s; "
                     f"best {len(current)} frames; {evaluations} evaluations total; "
                     f"stagnant {stagnant}"
                     + (f"/{config.stagnation_rounds}" if config.stagnation_rounds else ""))
        if config.stagnation_rounds and stagnant >= config.stagnation_rounds:
            if progress:
                progress(f"[auto:random-splice] stopping after {stagnant} "
                         "rounds with no verified frame or exit-proximity improvement")
            break
    return RandomSpliceResult(current, last_waypoints, improvements, attempts, evaluations)

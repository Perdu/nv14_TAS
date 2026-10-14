"""Switch-safe stochastic waypoint splicing of an existing completed N TAS.

A waypoint is a spatial *goal*, not permission to ignore the reference's
persistent interactions. Only canonically verified shorter *completed* replays
are published. Intermediate splices can be incomplete and are repaired through
later mandatory waypoints with Local's population search.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import itertools
import random
import time
from collections.abc import Callable, Sequence
from collections import Counter

from nv14_auto import AutoEvaluation, CompactTracePoint, evaluate_replay_with_sentinel, verify_trimmed_replay
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_engine import InputFrame, Level
from nv14_objectives import (INTERACTION_GOLD, reference_interaction_requirements,
                             resolve_interaction_target)
from nv14_population import PopulationConfig, optimise_local_population
from nv14_replay import decode_complex_replay, editable_frames, encode_complex_replay, simulate_through_frame


@dataclass(frozen=True, slots=True)
class RandomSpliceConfig:
    points: int = 5
    distance: float | None = None  # arc-length spacing in pixels; supersedes points
    radius: float = 16.0
    lookback: int = 32  # seam matching/maximum local mutation span, NOT a segment length
    iterations: int = 400  # Local proposals per anchor
    repair_iterations: int = 250  # Local proposals per subsequent anchor and worker per round
    splice_rounds: int = 1  # Local population rounds PER waypoint, not global Auto runs
    repair_rounds: int = 1  # Local population rounds PER continuation repair
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
                     rng: random.Random) -> tuple[Waypoint, ...]:
    """Sample arc length, not screen coordinates; pin every control event."""
    trace = reference.materialize_trace()
    if len(trace) < 4:
        return ()
    # No first/last-frame goal; these cannot save a meaningful segment.
    limit = min(len(trace) - 2, (reference.finish_tick or len(trace)) - 2)
    if limit < 2:
        return ()
    path = [0.0]
    for i in range(1, limit + 1):
        path.append(path[-1] + math.hypot(trace[i].x - trace[i-1].x,
                                          trace[i].y - trace[i-1].y))
    total = path[-1]
    candidates = list(range(2, limit + 1))
    selected: set[int] = set()
    if config.distance is None:
        # Jitter a uniform arc-length partition; frame sampling is a fallback
        # for stationary/slow paths where many arc-length positions coincide.
        for k in range(1, config.points + 1):
            if total > 1e-9:
                target = total * (k - 0.5 + rng.random()) / config.points
                selected.add(min(candidates, key=lambda i: abs(path[i] - target)))
            else:
                selected.add(rng.choice(candidates))
    elif total > 0:
        for k in range(1, math.ceil(total / config.distance)):
            target = k * config.distance
            if target >= total:
                break
            selected.add(min(candidates, key=lambda i: abs(path[i] - target)))
    # When a switch/locked-door/trapdoor fires, protect its state by placing an
    # anchor directly *after* the event, even if no random anchor fell there.
    mandatory = set()
    for event in reference.route_control_events:
        tick = min(limit, event.tick + 1)
        if tick >= 2:
            selected.add(tick)
            mandatory.add(tick)
    return tuple(Waypoint(i, trace[i].x, trace[i].y, i in mandatory)
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


def _validated_improvement(level: Level, proposal: Sequence[InputFrame],
                           reference: AutoEvaluation, original_length: int
                           ) -> tuple[InputFrame, ...] | None:
    """Repack, replay independently, require completion and every reference control."""
    packed = tuple(editable_frames(decode_complex_replay(encode_complex_replay(proposal)).frames))
    evaluation = evaluate_replay_with_sentinel(level, packed)
    if not evaluation.valid or evaluation.finish_tick is None:
        return None
    if evaluation.finish_tick >= original_length:
        return None
    # A shorter output has to finish *on its new implicit neutral sentinel*.
    body = packed[:evaluation.finish_tick]
    try:
        verified = verify_trimmed_replay(level, body)
    except ValueError:
        return None
    return body if _control_preserved(reference, verified) else None


def _exit_segment_start(finish: int, previous_end: int, lookback: int) -> int:
    """Allow the exit objective to repair a useful approach, not 2-5 final frames.

    Optional/mandatory path checkpoints help exploration, but do not constrain
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
            if progress:
                progress(f"[auto:random-splice] frontier stopped at waypoint {waypoint.frame}: "
                         "no surviving interaction-safe candidates")
            return None, attempts, evaluations, counters
        # Keep a feasible majority if available and at least one near miss.
        # Niche diversity is based on physical state at the checkpoint.
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
                        selected.pop()
                    offer(trial)
                    break
        branches = selected or [ranked[0][1]]
        previous_end = waypoint.frame
        counters["retained_branches"] += len(branches)
        if progress:
            progress(f"[auto:random-splice] frontier waypoint {waypoint.frame}: "
                     f"retained {len(branches)} branches, "
                     f"{counters['near_miss_carried']} near-miss candidates seen")

    # Search the entire last interval from each retained prefix to the exit.
    finish = len(current)
    start = _exit_segment_start(finish, previous_end, config.exit_lookback)
    if start >= finish:
        return None, attempts, evaluations, counters
    exit_target = resolve_interaction_target(level, f"exit:{reference.completed_exit_index}")
    goal = EndpointGoal(target_frame=finish, objective="earliest-interaction",
                        interaction_target=exit_target, arrival_start=start,
                        required_interactions=_requirements_at(level, current, finish - 1))
    shortest: tuple[InputFrame, ...] | None = None
    min_exit_gap = math.inf
    door = level.static_world.entry_for_ref(
        level.static_world.exit_door_ref(reference.completed_exit_index))
    edge_sum = (level.player.r + door.r) if door is not None else 0.0
    for branch_index, branch in enumerate(branches):
        attempts += 1
        if progress:
            progress(f"[auto:random-splice] frontier EXIT branch {branch_index+1}/{len(branches)} "
                     f"searching [{start}:{finish-1}]")
        found, used = _local_search(
            level, branch + (InputFrame(),), goal, start=start,
            editable_end=finish-1, config=config, iterations=config.iterations,
            rounds=config.splice_rounds, seed=rng.getrandbits(63),
            include_partial=True,
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
            elif shortest is None or len(validated) < len(shortest):
                shortest = validated
    if progress:
        distance = (f"{min_exit_gap:.2f}px edge gap" if math.isfinite(min_exit_gap)
                    else "no measurable near miss")
        progress(f"[auto:random-splice] frontier EXIT: "
                 f"{counters['exit_near_misses']} near misses; closest {distance}; "
                 f"{counters['exit_unverified']} unverified completions; "
                 f"{'best '+str(len(shortest))+' frames' if shortest else 'no shorter completion'}")
    return shortest, attempts, evaluations, counters


def optimise_random_splices(
    level: Level, source_frames: Sequence[InputFrame], config: RandomSpliceConfig,
    *, best_callback: Callable[[tuple[InputFrame, ...]], None] | None = None,
    progress: Callable[[str], None] | None = None,
) -> RandomSpliceResult:
    """Try earlier local arrivals, shift reference suffix, repair subsequent anchors.

    No partial replay is committed. After a splice, each reachable later
    waypoint becomes a *required* state-repair target with the reference's
    switch/door history; failure abandons that splice, not its constraints.
    """
    current = tuple(editable_frames(source_frames))
    verified = evaluate_replay_with_sentinel(level, current)
    if not verified.valid or verified.finish_tick != len(current):
        raise ValueError("random splicing needs a replay finishing on its neutral sentinel")
    first_reference = verified
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
                     f"{len(waypoints)} waypoints ({sum(w.mandatory for w in waypoints)} control anchors)")
        round_start = time.monotonic()
        round_improved = False
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
                         f"x {config.splice_rounds} Local rounds")
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
                                         f"x {config.repair_rounds} Local rounds")
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
                        if len(result) < len(current) and _control_preserved(first_reference, final_eval):
                            current = result
                            improvements += 1
                            improved = True
                            round_improved = True
                            if best_callback:
                                best_callback(current)
                            if progress:
                                progress(f"[auto:random-splice] improved to {len(current)} frames "
                                         f"at anchor {anchor.frame} (lead {reference_tick-cut_tick})")
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
                    interaction_target=resolve_interaction_target(
                        level, f"exit:{reference.completed_exit_index}"),
                    arrival_start=exit_start,
                    required_interactions=_requirements_at(level, current, exit_deadline - 1),
                )
                if progress:
                    progress(f"[auto:random-splice] EXIT segment [{exit_start}:{exit_deadline - 1}] "
                             f"({exit_deadline-exit_start} editable frames); "
                             f"{config.workers} workers x {config.iterations} proposals "
                             f"x {config.splice_rounds} Local rounds")
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
                    current = shorter
                    improvements += 1
                    round_improved = True
                    if best_callback:
                        best_callback(current)
                    if progress:
                        progress(f"[auto:random-splice] improved to {len(current)} "
                                 f"frames via EXIT segment")
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
                if len(proposal) < len(current) and _control_preserved(first_reference, final_eval):
                    current = proposal
                    improvements += 1
                    round_improved = True
                    if best_callback:
                        best_callback(current)
                    if progress:
                        progress(f"[auto:random-splice] improved to {len(current)} "
                                 f"frames via progressive multi-splice")
            if progress:
                progress(f"[auto:random-splice] frontier diagnostics: "
                         + ", ".join(f"{name}={count}" for name, count in sorted(diagnostic.items())))
        stagnant = 0 if round_improved else stagnant + 1
        if progress:
            progress(f"[auto:random-splice] round {round_no+1} completed in "
                     f"{time.monotonic()-round_start:.1f}s; "
                     f"best {len(current)} frames; {evaluations} evaluations total; "
                     f"stagnant {stagnant}"
                     + (f"/{config.stagnation_rounds}" if config.stagnation_rounds else ""))
        if config.stagnation_rounds and stagnant >= config.stagnation_rounds:
            if progress:
                progress(f"[auto:random-splice] stopping after {stagnant} "
                         "rounds with no completed replay improvement")
            break
    return RandomSpliceResult(current, last_waypoints, improvements, attempts, evaluations)

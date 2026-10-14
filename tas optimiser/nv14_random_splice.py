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

from nv14_auto import AutoEvaluation, CompactTracePoint, evaluate_replay_with_sentinel, verify_trimmed_replay
from nv14_endpoint import EndpointGoal
from nv14_engine import InputFrame, Level
from nv14_objectives import INTERACTION_GOLD, reference_interaction_requirements
from nv14_population import PopulationConfig, optimise_local_population
from nv14_replay import decode_complex_replay, editable_frames, encode_complex_replay, simulate_through_frame


@dataclass(frozen=True, slots=True)
class RandomSpliceConfig:
    points: int = 5
    distance: float | None = None  # arc-length spacing in pixels; supersedes points
    radius: float = 16.0
    lookback: int = 32
    iterations: int = 400  # Local proposals per anchor
    repair_iterations: int = 250  # Local proposals per subsequent anchor
    repair_anchors: int = 2
    beam: int = 16
    workers: int = 1
    rounds: int = 1
    stagnation_rounds: int = 0
    max_repair_searches: int = 8
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
        if type(self.rounds) is not int or self.rounds < 0:
            raise ValueError("random splice rounds must be nonnegative (0 means continuous)")
        if type(self.stagnation_rounds) is not int or self.stagnation_rounds < 0:
            raise ValueError("random splice stagnation_rounds must be nonnegative")
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
                  seed: int, progress: Callable[[str], None] | None = None):
    if start > goal.target_frame or goal.target_frame >= len(frames):
        return (), 0
    result = optimise_local_population(
        level, frames, goal=goal, frame_ranges=((start, goal.target_frame),),
        config=PopulationConfig(
            iterations=iterations, beam=config.beam, rounds=1,
            top_results=min(3, config.beam), workers=config.workers,
            mutation_span=min(config.lookback, 32), seed=seed,
            repair_steps=min(64, iterations // 4),
            repair_lookback=min(config.lookback, 32),
        ),
        progress=progress,
    )
    return (tuple((item.frames, item.evaluation.frame) for item in result.candidates
                  if item.evaluation.feasible), result.evaluations)


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
            start = max(0, anchor.frame - config.lookback)
            label = f"anchor {i+1}/{len(waypoints)} frame {anchor.frame}"
            if progress:
                progress(f"[auto:random-splice] {label}: preparing checkpoint "
                         f"and reference interaction requirements")
            goal = _goal(level, current, anchor, config, deadline=anchor.frame, start=start)
            if progress:
                progress(f"[auto:random-splice] {label}: searching [{start}:{anchor.frame}]; "
                         f"{config.workers} workers x {config.iterations} proposals")
            stage_start = time.monotonic()
            search_kw = {} if progress is None else {
                "progress": lambda text, label=label: progress(
                    f"[auto:random-splice] {label}: "
                    + text.removeprefix("[local:population] "))
            }
            found, used = _local_search(level, current, goal, start=start, config=config,
                                        iterations=config.iterations, seed=rng.getrandbits(63),
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
                        for next_anchor in waypoints[i + 1:i + 1 + config.repair_anchors]:
                            shift = reference_tick - cut_tick
                            deadline = next_anchor.frame - shift
                            if not 1 <= deadline < len(provisional):
                                break
                            repair_start = _repair_window_start(
                                provisional_eval,
                                suggested=max(cut_tick + 1, deadline - config.lookback),
                                immutable_end=cut_tick,
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
                                         f"{config.workers} workers x {config.repair_iterations} proposals")
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
                                    seed=rng.getrandbits(63),
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

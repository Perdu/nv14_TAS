"""Ordered, user-defined multi-splicing using existing Local/Auto endpoint search.

Unlike stochastic waypoints, every stage is an explicitly named Local goal file.
Partial branches may pass between stages, but a published result must satisfy all
configured goals, preserve pre-existing route controls, and (for a completed
source) remain canonically complete.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections.abc import Callable, Mapping, Sequence
import itertools
import hashlib
import json
import math
import random
import time

from nv14_auto import evaluate_replay_with_sentinel
from nv14_endpoint import EndpointGoal, EndpointEvaluator, EndpointEvaluation
from nv14_engine import InputFrame, Level, parse_level_string
from nv14_random_splice import (RandomSpliceConfig, _control_preserved,
                                _local_search, _completed_rank)
from nv14_auto import verify_trimmed_replay
from nv14_replay import editable_frames, decode_complex_replay, encode_complex_replay


@dataclass(frozen=True)
class UserSpliceStage:
    name: str
    goal: EndpointGoal
    start: int
    end: int
    config_overrides: Mapping[str, object] = field(default_factory=dict)
    simulate_enemies: bool | None = None


@dataclass(frozen=True)
class UserSpliceResult:
    frames: tuple[InputFrame, ...]
    improvements: int
    attempts: int
    evaluations: int


def _search_stage(level: Level, branch: tuple[InputFrame, ...],
                  stage: UserSpliceStage, config: RandomSpliceConfig,
                  rng: random.Random,
                  *, stage_rank: Callable[[tuple[InputFrame, ...]], tuple | None] | None = None,
                  progress: Callable[[str], None] | None = None,
                  candidate_callback: Callable[[tuple[InputFrame, ...], int], None] | None = None,
                  resume_phase: Mapping[str, object] | None = None,
                  phase_started: Callable[[dict[str, object]], None] | None = None,
                  backend_checkpoint_path: Callable[[str], str] | None = None,
                  ) -> tuple[tuple[tuple[tuple[InputFrame, ...], int], ...], int, int]:
    """Run the requested backends with one shared per-branch proposal budget.

    With ``both``, endpoint Auto runs first. Local then starts from the
    best Auto candidate (or the original stage seed when Auto did not improve
    on it). Both backends retain their own share of the iteration budget,
    and their candidates are merged for the next named stage.
    The odd proposal goes to Local, so the combined backend budget remains
    exactly config.iterations per worker and internal round.
    """
    if (config.splice_auto_stagnation_rounds or config.splice_local_stagnation_rounds):
        return _search_stage_backend_phases(
            level, branch, stage, config, rng, stage_rank=stage_rank,
            progress=progress, candidate_callback=candidate_callback,
            resume_phase=resume_phase, phase_started=phase_started,
            backend_checkpoint_path=backend_checkpoint_path)
    if config.splice_stagnation_rounds:
        return _search_stage_until_stagnant(
            level, branch, stage, config, rng, stage_rank=stage_rank,
            progress=progress, candidate_callback=candidate_callback)
    if config.search_backend == "both":
        if config.iterations < 2:
            raise ValueError("splice-search=both requires splice-iterations >= 2")
        modes = (("endpoint-auto", config.iterations // 2),
                 ("local", (config.iterations + 1) // 2))
    else:
        modes = ((config.search_backend, config.iterations),)
    merged: dict[tuple[InputFrame, ...], int] = {}
    evaluations = 0
    searches = 0
    search_seed = branch
    for backend, iterations in modes:
        try:
            found, used = _local_search(
                level, search_seed, stage.goal, start=stage.start,
                editable_end=stage.end,
                config=replace(config, search_backend=backend),
                iterations=iterations, rounds=config.splice_rounds,
                seed=rng.getrandbits(63), include_partial=True,
                live_update_interval=30.0 if config.workers > 1 else 0.75,
                **({"best_callback": candidate_callback} if candidate_callback else {}))
        except ValueError as exc:
            if not str(exc).startswith("the immutable prefix dies before the editable ranges"):
                raise
            found, used = (), 0
        evaluations += used
        searches += 1
        for candidate, frame in found:
            merged.setdefault(tuple(candidate), frame)
        if config.search_backend == "both" and backend == "endpoint-auto" and found:
            # Choose by the *stage* goal, not by discovery order. Auto returns
            # feasible winners and diverse partial survivors. Keep a feasible
            # incumbent over an infeasible near-miss, and use the same
            # endpoint progress ranking as the search for partial branches.
            # On tied ranks, prefer the Auto candidate for extra diversity.
            evaluator = EndpointEvaluator(level, stage.goal)
            auto_seeds = list(dict.fromkeys(tuple(candidate) for candidate, _ in found))
            auto_seeds.append(branch)
            search_seed = min(auto_seeds,
                              key=lambda frames: evaluator.evaluate(frames).progress_key)
    return tuple(merged.items()), evaluations, searches



def _search_stage_backend_phases(
    level: Level, branch: tuple[InputFrame, ...], stage: UserSpliceStage,
    config: RandomSpliceConfig, rng: random.Random,
    *, stage_rank: Callable[[tuple[InputFrame, ...]], tuple | None] | None = None,
    progress: Callable[[str], None] | None = None,
    candidate_callback: Callable[[tuple[InputFrame, ...], int], None] | None = None,
    resume_phase: Mapping[str, object] | None = None,
    phase_started: Callable[[dict[str, object]], None] | None = None,
    backend_checkpoint_path: Callable[[str], str] | None = None,
) -> tuple[tuple[tuple[tuple[InputFrame, ...], int], ...], int, int]:
    """Run each backend continuously until its own stagnant-round limit.

    One Auto or Local invocation retains its native population throughout the
    phase.  If either phase improves an admissible stage candidate, another
    Auto -> Local cycle begins.  ``splice_rounds`` is intentionally irrelevant
    here; that legacy batch setting is only used without phase stagnation.
    """
    if config.search_backend == "both":
        if config.iterations < 2:
            raise ValueError("splice-search=both requires splice-iterations >= 2")
        phases = (("endpoint-auto", config.iterations // 2,
                   config.splice_auto_stagnation_rounds),
                  ("local", (config.iterations + 1) // 2,
                   config.splice_local_stagnation_rounds))
    elif config.search_backend == "endpoint-auto":
        phases = (("endpoint-auto", config.iterations,
                   config.splice_auto_stagnation_rounds),)
    else:
        phases = (("local", config.iterations,
                   config.splice_local_stagnation_rounds),)

    evaluator = EndpointEvaluator(level, stage.goal)

    def rank(frames: tuple[InputFrame, ...]) -> tuple | None:
        if stage_rank is not None:
            return stage_rank(frames)
        evaluation = evaluator.evaluate(frames)
        return evaluation.objective_key if evaluation.feasible else None

    merged: dict[tuple[InputFrame, ...], int] = {}
    incumbent = search_seed = tuple(branch)
    best_rank = rank(incumbent)
    best_progress = evaluator.evaluate(incumbent).progress_key
    evaluations = calls = 0
    cycle = int(resume_phase["cycle"]) - 1 if resume_phase is not None else 0
    while True:
        cycle += 1
        cycle_improved = (bool(resume_phase["cycle_improved"])
                          if resume_phase is not None else False)
        start_backend = str(resume_phase["backend"]) if resume_phase is not None else None
        for backend, iterations, patience in phases:
            if start_backend is not None and backend != start_backend:
                continue
            if progress:
                progress(f"[auto:user-splice:refine] {stage.name!r}: "
                         f"cycle {cycle}, starting continuous {backend} phase "
                         f"(stop after {patience} stagnant rounds)")
            phase_improved = False
            checkpoint = backend_checkpoint_path(backend) if backend_checkpoint_path else None
            if start_backend is not None:
                search_seed = tuple(editable_frames(decode_complex_replay(
                    resume_phase["search_seed"]).frames))
                incumbent = search_seed
                best_rank = rank(incumbent)
                best_progress = evaluator.evaluate(incumbent).progress_key
                seed = int(resume_phase["seed"])
                # Restore the RNG position from just after the backend seed
                # was allocated, so subsequent phases stay deterministic.
                rng.setstate((3, tuple(resume_phase["rng_state"]), None))
            else:
                seed = rng.getrandbits(63)
            if phase_started is not None:
                phase_started({"backend": backend, "cycle": cycle,
                               "seed": seed, "rng_state": list(rng.getstate()[1]),
                               "search_seed": encode_complex_replay(search_seed),
                               "cycle_improved": cycle_improved})

            last_live_check = float("-inf")
            def on_live_best(frames: tuple[InputFrame, ...], frame: int) -> None:
                nonlocal incumbent, best_rank, phase_improved, cycle_improved, last_live_check
                # Parent-side checks of all earlier named goals are expensive.
                # In a multi-worker run, process at most one live candidate per
                # interval. The backend's final winner/frontier is still
                # processed in full after the phase, without being dropped.
                now = time.monotonic()
                if config.workers > 1 and now - last_live_check < 30.0:
                    return
                last_live_check = now
                candidate = tuple(frames)
                merged.setdefault(candidate, frame)
                # A backend improvement is not necessarily admissible at this
                # stage: earlier named goals must still hold.
                candidate_rank = rank(candidate)
                if candidate_rank is not None and (
                    best_rank is None or candidate_rank < best_rank
                ):
                    incumbent, best_rank = candidate, candidate_rank
                    phase_improved = cycle_improved = True
                if candidate_callback is not None:
                    candidate_callback(candidate, frame)

            try:
                found, used = _local_search(
                    level, search_seed, stage.goal, start=stage.start,
                    editable_end=stage.end,
                    config=replace(config, search_backend=backend),
                    iterations=iterations, rounds=0,
                    stagnation_rounds=patience,
                    seed=seed, include_partial=True,
                    live_update_interval=30.0 if config.workers > 1 else 0.75,
                    best_callback=on_live_best if candidate_callback is not None else None,
                    **({"checkpoint_path": checkpoint, "resume": bool(start_backend)}
                       if checkpoint else {}))
            except ValueError as exc:
                if not str(exc).startswith("the immutable prefix dies before the editable ranges"):
                    raise
                found, used = (), 0
            evaluations += used
            calls += 1
            resume_phase = None
            start_backend = None
            near_miss = search_seed
            near_progress = best_progress
            for candidate, frame in found:
                candidate = tuple(candidate)
                merged.setdefault(candidate, frame)
                candidate_rank = rank(candidate)
                if candidate_rank is not None and (
                    best_rank is None or candidate_rank < best_rank
                ):
                    incumbent, best_rank = candidate, candidate_rank
                    phase_improved = cycle_improved = True
                candidate_progress = evaluator.evaluate(candidate).progress_key
                if candidate_progress < near_progress:
                    near_miss, near_progress = candidate, candidate_progress
            if best_rank is not None:
                search_seed = incumbent
                best_progress = evaluator.evaluate(incumbent).progress_key
            else:
                search_seed, best_progress = near_miss, near_progress
            if progress:
                progress(f"[auto:user-splice:refine] {stage.name!r}: "
                         f"cycle {cycle}, {backend} phase finished at "
                         f"its own stagnation limit {patience}; "
                         f"{'stage improved' if phase_improved else 'no stage gain'}; "
                         f"{used} distinct evaluations")
        if progress:
            progress(f"[auto:user-splice:refine] {stage.name!r}: "
                     f"cycle {cycle} "
                     f"{'improved; restarting Auto' if cycle_improved else 'no improvement; advancing'}; "
                     f"{calls} backend phase(s), {evaluations} distinct evaluations")
        if not cycle_improved:
            break
    return tuple(merged.items()), evaluations, calls


def _search_stage_until_stagnant(
    level: Level, branch: tuple[InputFrame, ...], stage: UserSpliceStage,
    config: RandomSpliceConfig, rng: random.Random,
    *, stage_rank: Callable[[tuple[InputFrame, ...]], tuple | None] | None = None,
    progress: Callable[[str], None] | None = None,
    candidate_callback: Callable[[tuple[InputFrame, ...], int], None] | None = None,
) -> tuple[tuple[tuple[tuple[InputFrame, ...], int], ...], int, int]:
    """Alternate backend turns until N full cycles make no stage improvement.

    A *cycle* comprises Auto then Local in `both` mode. A successful turn
    immediately seeds the next backend, and the next cycle can refine Local's
    result with Auto. A cycle is stagnant only if neither backend beats the
    best admissible objective for *this seed*, irrespective of historical
    bests from earlier outer rounds. Thus a fresh route is not penalised for
    having had less optimization than a previously archived route.

    Each turn uses the existing per-worker iteration count and `splice_rounds`.
    The total number of cycles is determined by improvement/stagnation, not
    a fixed number of turns. Candidates remain available for the usual
    n-1/n-2 frontier selection and final verification.
    """
    if config.search_backend == "both":
        if config.iterations < 2:
            raise ValueError("splice-search=both requires splice-iterations >= 2")
        turns = (("endpoint-auto", config.iterations // 2),
                 ("local", (config.iterations + 1) // 2))
    else:
        turns = ((config.search_backend, config.iterations),)
    evaluator = EndpointEvaluator(level, stage.goal)

    def rank(frames: tuple[InputFrame, ...]) -> tuple | None:
        if stage_rank is not None:
            return stage_rank(frames)
        evaluation = evaluator.evaluate(frames)
        return evaluation.objective_key if evaluation.feasible else None

    merged: dict[tuple[InputFrame, ...], int] = {}
    search_seed = tuple(branch)
    incumbent = search_seed
    best_rank = rank(incumbent)
    best_progress = evaluator.evaluate(incumbent).progress_key
    used = calls = stagnant = cycle = 0
    while stagnant < config.splice_stagnation_rounds:
        cycle += 1
        improved = False
        for backend, iterations in turns:
            try:
                found, count = _local_search(
                    level, search_seed, stage.goal, start=stage.start,
                    editable_end=stage.end,
                    config=replace(config, search_backend=backend),
                    iterations=iterations, rounds=config.splice_rounds,
                    seed=rng.getrandbits(63), include_partial=True,
                    live_update_interval=30.0 if config.workers > 1 else 0.75,
                    **({"best_callback": candidate_callback} if candidate_callback else {}))
            except ValueError as exc:
                if not str(exc).startswith("the immutable prefix dies before the editable ranges"):
                    raise
                found, count = (), 0
            used += count
            calls += 1
            turn_improved = False
            # A higher-scoring partial state can help reach an initially
            # infeasible checkpoint, but cannot count as a valid improvement.
            best_near_miss = search_seed
            near_miss_rank = best_progress
            for candidate, frame in found:
                candidate = tuple(candidate)
                merged.setdefault(candidate, frame)
                candidate_rank = rank(candidate)
                if candidate_rank is not None and (best_rank is None or candidate_rank < best_rank):
                    incumbent, best_rank = candidate, candidate_rank
                    improved = True
                    turn_improved = True
                candidate_progress = evaluator.evaluate(candidate).progress_key
                if candidate_progress < near_miss_rank:
                    best_near_miss, near_miss_rank = candidate, candidate_progress
            if progress and turn_improved:
                progress(f"[auto:user-splice:refine] {stage.name!r}: "
                         f"cycle {cycle} {backend} improved the stage objective")
            # Never replace a feasible incumbent with an infeasible near-miss.
            if best_rank is not None:
                search_seed = incumbent
                best_progress = evaluator.evaluate(incumbent).progress_key
            else:
                search_seed, best_progress = best_near_miss, near_miss_rank
        stagnant = 0 if improved else stagnant + 1
        if progress:
            progress(f"[auto:user-splice:refine] {stage.name!r}: cycle {cycle}; "
                     f"{'improved' if improved else 'no gain'}; "
                     f"stagnant {stagnant}/{config.splice_stagnation_rounds}; "
                     f"{calls} backend turns, {used} distinct evaluations")
    return tuple(merged.items()), used, calls


def _stage_sources(recent: Sequence[tuple[InputFrame, ...]],
                   two_back: Sequence[tuple[InputFrame, ...]],
                   frontier: int) -> list[tuple[InputFrame, ...]]:
    """Keep the strongest candidates from n-1 AND n-2 as stage n seeds.

    Both lists are already sorted by *their own* stage objective, so the
    n-2 candidates are not spuriously ranked by the n-1 objective. Reserve at
    least one slot for each distinct source, even with frontier=1. Seeds need
    not be feasible at n-1 yet; all preceding goals are checked when an output
    is admitted, and every published result is independently verified.
    """
    limit = max(2, frontier) if two_back else max(1, frontier)
    if not two_back:
        return list(dict.fromkeys(recent))[:limit]
    recent_quota = (limit + 1) // 2
    back_quota = limit - recent_quota
    result: list[tuple[InputFrame, ...]] = []
    for source, slots in ((recent, recent_quota), (two_back, back_quota)):
        taken = 0
        for candidate in source:
            if candidate not in result:
                result.append(candidate)
                taken += 1
            if taken >= slots:
                break
    # If one source was smaller or overlapped completely, fill the remaining
    # capacity from its partner, without losing the best n-1 or n-2 candidate.
    for candidate in (*recent, *two_back):
        if len(result) >= limit:
            break
        if candidate not in result:
            result.append(candidate)
    return result


def _stage_sources_history(history: Sequence[Sequence[tuple[InputFrame, ...]]],
                           frontier: int) -> list[tuple[InputFrame, ...]]:
    """Add older-stage seeds without displacing the existing n-1/n-2 seeds.

    Keep the exact previous two-frontier selection, then append one distinct
    candidate from each additional stage in recency order. The extra searches
    have additional compute cost, but cannot remove an existing search path.
    """
    sources = [source for source in history if source]
    if not sources:
        return []
    if len(sources) == 1:
        return list(dict.fromkeys(sources[0]))[:max(1, frontier)]
    selected = _stage_sources(sources[0], sources[1], frontier)
    seen = set(selected)
    for source in sources[2:]:
        for candidate in source:
            if candidate not in seen:
                selected.append(candidate)
                seen.add(candidate)
                break
    return selected


def _diverse_saved_archive(
    pool: Mapping[tuple[InputFrame, ...], tuple],
    evaluator: EndpointEvaluator, limit: int,
) -> list[tuple[InputFrame, ...]]:
    """Preserve quality *and* distinct physical endpoint niches on disk.

    A modest elite quota stays ranked by the actual stage objective. Other
    slots first cover position/velocity niches, with remaining capacity filled
    by the strongest candidates. This affects persistence only, not beam size.
    """
    ordered = sorted(pool, key=pool.__getitem__)
    if len(ordered) <= limit:
        return ordered
    elites = min(len(ordered), max(1, limit // 4))
    selected = list(ordered[:elites])
    seen = set(selected)
    niches: set[tuple[int, int, int, int]] = set()
    def niche(candidate: tuple[InputFrame, ...]) -> tuple[int, int, int, int]:
        sample = evaluator.evaluate(candidate)
        return (round(sample.x / 4), round(sample.y / 4),
                round(sample.vx * 4), round(sample.vy * 4))
    for candidate in selected:
        niches.add(niche(candidate))
    for candidate in ordered[elites:]:
        if len(selected) >= limit:
            break
        category = niche(candidate)
        if category not in niches:
            selected.append(candidate)
            seen.add(candidate)
            niches.add(category)
    for candidate in ordered:
        if len(selected) >= limit:
            break
        if candidate not in seen:
            selected.append(candidate)
            seen.add(candidate)
    # Present the archive in stage-score order, preserving old ranking rules
    # when it is used to recover an active frontier.
    return sorted(selected, key=pool.__getitem__)


def _materialise_splice_tail(frames: Sequence[InputFrame], target_frame: int
                             ) -> tuple[InputFrame, ...]:
    """Materialise the neutral inputs implicit past a recorded replay's end.

    This is a search-only workspace. A canonically completed source retains
    its original length, and verified outputs are trimmed to their finish tick.
    """
    body = tuple(frames)
    return body + (InputFrame(),) * max(0, target_frame + 1 - len(body))


def _stage_improvement_text(goal: EndpointGoal,
                            previous: EndpointEvaluation | None,
                            current: EndpointEvaluation) -> str:
    """Human-readable *physical* results, never internal sorting keys.

    A ranking key like (832.0, -90.067) encodes a minimisation order: its
    negative component is NOT a negative player position.  Format actual
    frames, coordinates and secondary values instead.
    """
    def coords(value: EndpointEvaluation) -> str:
        return f"({value.x:.9g}, {value.y:.9g})"

    def metric(value: EndpointEvaluation) -> float | None:
        if goal.objective in ("min-x", "max-x"):
            return value.x
        if goal.objective in ("min-y", "max-y"):
            return value.y
        if goal.objective == "min-distance":
            return math.sqrt(max(0.0, -value.score))
        return None

    if previous is None:
        result = f"frame {current.frame}; position {coords(current)}"
    else:
        frame_text = (f"frame {current.frame}"
                      if previous.frame == current.frame else
                      f"frame {previous.frame} -> {current.frame}")
        result = (f"{frame_text}; position {coords(previous)} -> "
                  f"{coords(current)}")
    if not goal.is_earliest:
        label = "distance" if goal.objective == "min-distance" else goal.objective
        new = metric(current)
        old = metric(previous) if previous is not None else None
        if new is not None:
            result += (f"; {label} {new:.9g}" if old is None else
                       f"; {label} {old:.9g} -> {new:.9g}")
    if goal.secondary_objective is not None:
        label = goal.secondary_objective
        result += (f"; {label} {current.secondary_value:.9g}"
                   if previous is None else
                   f"; {label} {previous.secondary_value:.9g} -> "
                   f"{current.secondary_value:.9g}")
    elif goal.exit_distance_tiebreak and current.pre_finish_exit_distance is not None:
        gap = current.pre_finish_exit_distance
        old_gap = previous.pre_finish_exit_distance if previous is not None else None
        result += (f"; exit proximity {gap:.9g}"
                   if old_gap is None else
                   f"; exit proximity {old_gap:.9g} -> {gap:.9g}")
    return result


def _stage_summary_text(goal: EndpointGoal, evaluation: EndpointEvaluation) -> str:
    """Show coordinate objectives once in summaries, without duplicate positions.

    Temporary improvement logs still retain the full physical position; the
    per-round propagation summary only needs the objective being compared.
    """
    objective = goal.objective
    if objective in ("min-x", "max-x", "min-y", "max-y"):
        coordinate = evaluation.x if objective.endswith("-x") else evaluation.y
        result = f"frame {evaluation.frame}; {objective} {coordinate:.9g}"
        if goal.secondary_objective is not None:
            result += f"; {goal.secondary_objective} {evaluation.secondary_value:.9g}"
        elif (goal.exit_distance_tiebreak and
              evaluation.pre_finish_exit_distance is not None):
            result += f"; exit proximity {evaluation.pre_finish_exit_distance:.9g}"
        return result
    # Earliest-arrival / earliest-interaction goals can rank tied frames by
    # a coordinate *secondary* objective.  In that case the primary objective
    # is not min-x/min-y, but displaying the whole position still repeats the
    # coordinate printed as the secondary value.  The evaluator already
    # provides this value in physical (non-negated) units.
    if goal.secondary_objective in ("min-x", "max-x", "min-y", "max-y"):
        return (f"frame {evaluation.frame}; {goal.secondary_objective} "
                f"{evaluation.secondary_value:.9g}")
    return _stage_improvement_text(goal, None, evaluation)


def optimise_user_splices(
    level: Level, source_frames: Sequence[InputFrame],
    stages: Sequence[UserSpliceStage], config: RandomSpliceConfig,
    *, best_callback: Callable[[tuple[InputFrame, ...]], None] | None = None,
    stage_best_callback: Callable[[str, tuple[InputFrame, ...]], None] | None = None,
    progress: Callable[[str], None] | None = None,
    completion_policy: str = "complete",
    start_at: str | None = None, stop_at: str | None = None,
    from_best: str | None = None,
    saved_stage_candidates: Mapping[str, Sequence[Sequence[InputFrame]]] | None = None,
    saved_stage_frontiers: Mapping[str, Sequence[Sequence[InputFrame]]] | None = None,
    saved_final_frames: Sequence[InputFrame] | None = None,
    frontier_callback: Callable[[str, tuple[tuple[InputFrame, ...], ...]], None] | None = None,
    summary_only: bool = False,
    resume_state: Mapping[str, object] | None = None,
    save_resume_state: Callable[[dict[str, object] | None], None] | None = None,
    backend_checkpoint_path: Callable[[str, str], str] | None = None,
    resume_outer_round: int = 0,
    save_outer_round: Callable[[int | None], None] | None = None,
) -> UserSpliceResult:
    """Optimise named goals in order, retaining diverse feasible continuations.

    Use identical endpoint evaluation and Local/Hybrid search as random splicing.
    Only independently verified full-run results reach best_callback. Optional
    stage_best_callback receives each stage's best *feasible intermediate* replay
    (which need not finish the level), only after a genuine improvement.
    An existing completed final result is never replaced by an incomplete route.
    """
    if not stages:
        raise ValueError("user splice requires at least one named goal")
    if completion_policy not in ("checkpoint", "complete"):
        raise ValueError("invalid user splice completion policy")
    # Selection does not waive requirements of earlier goals.
    def stage_index(requested: str | None, default: int, label: str) -> int:
        if requested is None:
            return default
        matches = [i for i, stage in enumerate(stages)
                   if stage.name == requested or
                   (stage.name.rsplit(".", 1)[0] == requested and
                    stage.name.endswith((".txt", ".toml")))]
        if len(matches) != 1:
            raise ValueError(f"{label} splice {requested!r} is not a unique name "
                             f"in splice-files: {[s.name for s in stages]}")
        return matches[0]
    from_best_index = (stage_index(from_best, -1, "saved best")
                       if from_best is not None else None)
    if from_best_index == len(stages) - 1 and start_at is None:
        raise ValueError(f"saved best splice {from_best!r} has no later stage to propagate; "
                         "use --splice-start to explicitly search a stage")
    # By default, propagate an existing splice best to the *following* stage.
    # An explicit --splice-start may instead retry the source stage itself.
    first_stage = stage_index(start_at, from_best_index + 1 if from_best_index is not None else 0, "start")
    last_stage = stage_index(stop_at, len(stages) - 1, "stop")
    if first_stage > last_stage:
        raise ValueError("splice start must not be after splice stop")
    source = tuple(editable_frames(source_frames))
    # Check canonical completion *before* materialising any neutral search
    # inputs. Otherwise a completed source looks incomplete merely because
    # the last named target-frame is later than its real finish tick.
    source_eval = evaluate_replay_with_sentinel(level, source)
    source_complete = bool(source_eval.valid and source_eval.finish_tick == len(source))
    current = _materialise_splice_tail(source, max(s.goal.target_frame for s in stages))
    # A completed saved final output must never be displaced by an incomplete
    # checkpoint, even when the new input is incomplete and policy=checkpoint.
    require_complete = (completion_policy == "complete" or source_complete
                        or saved_final_frames is not None)
    if completion_policy == "complete" and not source_complete:
        raise ValueError("user splice requires a canonically completed source for completion-policy=complete")
    for stage in stages:
        if not (0 <= stage.start <= stage.end <= stage.goal.target_frame < len(current)):
            raise ValueError(f"invalid range/target-frame for splice {stage.name!r}")
    rng = random.Random(config.seed)
    # Cache the two possible physics worlds. Stage feasibility and search use
    # the world selected by that named splice, even when its neighbors differ.
    worlds = {level.simulate_enemies: level}
    for stage in stages:
        enabled = level.simulate_enemies if stage.simulate_enemies is None else stage.simulate_enemies
        if enabled not in worlds:
            if level.source_level_string is None:
                raise ValueError("per-stage simulate-enemies requires original level source")
            worlds[enabled] = parse_level_string(
                level.source_level_string, simulate_enemies=enabled)
    stage_levels = tuple(worlds[level.simulate_enemies if s.simulate_enemies is None
                                else s.simulate_enemies] for s in stages)
    original_endpoints = tuple(EndpointEvaluator(stage_level, stage.goal)
                               for stage_level, stage in zip(stage_levels, stages))
    # Stage goals are intentionally checked independently. Later edits must not
    # silently undo an earlier switch, jump, or arrival requirement.
    def valid_stages(frames, through: int) -> bool:
        return all(evaluate.evaluate(frames).feasible for evaluate in original_endpoints[:through])

    def final_rank(frames):
        # A named stage's goal is the user's optimisation objective. Finishing
        # early and preserving the full route are safety/secondary constraints,
        # not replacements for the explicitly requested end goal.
        if not valid_stages(frames, len(stages)):
            return None
        target_rank = original_endpoints[-1].evaluate(frames).objective_key
        evaluated = evaluate_replay_with_sentinel(level, frames)
        # A stage searched without enemies may reach its endpoint but die in
        # the physical world when replayed. Never publish that dead replay as
        # a final best, even in checkpoint completion policy.
        if level.simulate_enemies and evaluated.dead_tick is not None:
            return None
        if require_complete:
            if not evaluated.valid or evaluated.finish_tick is None:
                return None
            # The native simulator may report a faster completion than the
            # input sentinel. Re-encode and independently reverify the trimmed
            # replay before publishing a shorter completed route.
            length = evaluated.finish_tick
            try:
                completed = verify_trimmed_replay(level, frames[:length])
            except ValueError:
                return None
            if source_complete and not _control_preserved(source_eval, completed):
                return None
            return (target_rank, _completed_rank(completed, length)), tuple(frames[:length])
        return (target_rank,), tuple(frames)

    def stage_export(frames: tuple[InputFrame, ...]) -> tuple[InputFrame, ...]:
        """Keep trial replays playable and trim only verified early finishes.

        The search workspace may extend past a completed replay's sentinel.
        Its neutral tail is not part of the movie and should not appear in
        the companion plain-text replay checkpoint either.
        """
        checked = evaluate_replay_with_sentinel(level, frames)
        if checked.valid and checked.finish_tick is not None:
            trimmed = tuple(frames[:checked.finish_tick])
            try:
                verify_trimmed_replay(level, trimmed)
            except ValueError:
                pass
            else:
                return trimmed
        return frames

    baseline = final_rank(current)
    best_rank = baseline[0] if baseline is not None else None
    best_output = baseline[1] if baseline is not None else source
    if saved_final_frames is not None:
        saved_final = tuple(editable_frames(saved_final_frames))
        # Never let an older input replay overwrite an already verified final
        # result. Check the archived movie using *current* stage requirements.
        physical = evaluate_replay_with_sentinel(level, saved_final)
        if not physical.valid or physical.finish_tick != len(saved_final):
            raise ValueError("saved final output is not a verified completed replay; "
                             "refusing to overwrite it")
        saved_rank = final_rank(_materialise_splice_tail(saved_final, len(current) - 1))
        if saved_rank is None:
            raise ValueError("saved final output fails current splice requirements; "
                             "refusing to overwrite it")
        if best_rank is None or saved_rank[0] < best_rank:
            best_rank, best_output = saved_rank
        if progress:
            progress("[auto:user-splice:resume] verified saved final replay; "
                     "protected as the final-score baseline")
    improvements = attempts = evaluations = stagnant = 0
    stage_best: list[tuple | None] = []
    stage_best_evaluation: list[EndpointEvaluation | None] = []
    for i, endpoint in enumerate(original_endpoints):
        # The baseline is a real stage reference, not a reported improvement.
        feasible = valid_stages(current, i + 1)
        evaluation = endpoint.evaluate(current) if feasible else None
        stage_best.append(evaluation.objective_key if evaluation is not None else None)
        stage_best_evaluation.append(evaluation)
    restored_stage_frames: list[tuple[InputFrame, ...] | None] = [None] * len(stages)
    stage_checkpoints: list[tuple[InputFrame, ...] | None] = [None] * len(stages)
    stage_checkpoint_evals: list[EndpointEvaluation | None] = [None] * len(stages)
    stage_checkpoint_origin = ["saved" for _ in stages]
    for i, stage in enumerate(stages):
        for archived in (saved_stage_candidates or {}).get(stage.name, ()):
            # Saved movies may have been trimmed to an earlier finish.  Apply
            # the same implicit-neutral-tail convention as the active replay.
            replay = _materialise_splice_tail(archived, len(current) - 1)
            if not valid_stages(replay, i + 1):
                if progress:
                    progress(f"[auto:user-splice:resume] {stage.name!r}: "
                             "ignored checkpoint failing the named goals")
                continue
            score = original_endpoints[i].evaluate(replay)
            # Keep the best validated on-disk candidate independently of the
            # current source, which can already be better than the file.
            if (stage_checkpoint_evals[i] is None or
                    score.objective_key < stage_checkpoint_evals[i].objective_key):
                stage_checkpoints[i] = replay
                stage_checkpoint_evals[i] = score
            if stage_best[i] is None or score.objective_key < stage_best[i]:
                stage_best[i] = score.objective_key
                stage_best_evaluation[i] = score
                restored_stage_frames[i] = replay
    # Restore top stage populations separately from the single best LTM/TXT.
    # The old one-best checkpoints are also valid fallbacks for archives that
    # predate this feature. Re-check all entries under each stage's physics.
    archived_frontiers: list[list[tuple[InputFrame, ...]]] = []
    for i, stage in enumerate(stages):
        pool: dict[tuple[InputFrame, ...], tuple] = {}
        for raw in (*((saved_stage_frontiers or {}).get(stage.name, ())),
                    *((saved_stage_candidates or {}).get(stage.name, ()))):
            replay = _materialise_splice_tail(raw, len(current) - 1)
            if valid_stages(replay, i + 1):
                pool[replay] = original_endpoints[i].evaluate(replay).objective_key
        ranked = sorted(pool, key=pool.__getitem__)
        archived_frontiers.append(_diverse_saved_archive(
            pool, original_endpoints[i], config.save_frontier))
        if progress and ranked and not summary_only:
            progress(f"[auto:user-splice:resume] {stage.name!r}: "
                     f"restored {len(archived_frontiers[-1])} validated archive candidate(s); "
                     f"up to {config.frontier} actively searched per source")

    def publish_frontier(i: int, candidates: Sequence[tuple[InputFrame, ...]]) -> None:
        if frontier_callback is None or summary_only:
            return
        pool: dict[tuple[InputFrame, ...], tuple] = {}
        for candidate in (*archived_frontiers[i], *candidates):
            if valid_stages(candidate, i + 1):
                pool[candidate] = original_endpoints[i].evaluate(candidate).objective_key
        selected = _diverse_saved_archive(pool, original_endpoints[i], config.save_frontier)
        if selected != archived_frontiers[i]:
            frontier_callback(stages[i].name, tuple(selected))
            archived_frontiers[i] = selected

    # An in-flight backend phase is separate from the saved stage bests.
    # It can resume the last *completed backend round*, even if previous
    # stage passes were interrupted. Reject ambiguous incompatible snapshots.
    active_phase = None
    if resume_state is not None and not summary_only:
        try:
            wanted = {
                "version": 1,
                "level_sha256": hashlib.sha256(level.source_level_string.encode()).hexdigest(),
                "source_sha256": hashlib.sha256(encode_complex_replay(source).encode()).hexdigest(),
                "stages": [stage.name for stage in stages],
                "stage_settings": [repr(stage) for stage in stages],
                "config": repr(config),
                "from_best": from_best,
                "start_at": start_at, "stop_at": stop_at,
            }
            if any(resume_state.get(k) != value for k, value in wanted.items()):
                raise ValueError("named splice search checkpoint no longer matches level, "
                                 "input, splice configuration, or requested stages")
            active_phase = resume_state
            if progress:
                progress(f"[auto:user-splice:resume] restoring outer round "
                         f"{int(active_phase['round_no']) + 1}, splice "
                         f"{active_phase['stage']!r}, backend "
                         f"{active_phase['phase']['backend']} from last completed round")
        except (KeyError, TypeError) as exc:
            raise ValueError("invalid named splice search checkpoint") from exc

    # Summary-only mode reports on disk checkpoints without changing them.
    # There must be no baseline checkpoint writes or Auto/Local searches.
    # Choose only a previously saved, validated best for explicit propagation.
    # Do this before writing initial source checkpoints, so --splice-from-best
    # never silently falls back to an unsaved current-run baseline.
    propagation_seed = current
    if from_best_index is None and saved_final_frames is not None and best_output != source:
        # Use the previously verified best completed replay for normal search,
        # not only as a score threshold. Explicit --splice-from-best still wins.
        propagation_seed = _materialise_splice_tail(best_output, len(current) - 1)
    if from_best_index is not None:
        propagation_seed = stage_checkpoints[from_best_index]
        if propagation_seed is None:
            raise ValueError(f"no valid saved checkpoint for splice {from_best!r}; "
                             "a saved stage LTM/TXT must exist and satisfy all "
                             "preceding named goals")
        if progress:
            evaluation = stage_checkpoint_evals[from_best_index]
            progress(f"[auto:user-splice:from-best] {from_best!r}: "
                     f"starting at stage {stages[first_stage].name!r} from saved "
                     f"checkpoint; {_stage_improvement_text(stages[from_best_index].goal, None, evaluation)}")
    # Create the initial stage checkpoints as well as subsequent new bests.
    # Compare against validated on-disk checkpoints first: an existing better
    # movie must never be overwritten by a weaker starting replay.
    if not summary_only:
        for i, stage in enumerate(stages):
            baseline_evaluation = original_endpoints[i].evaluate(current) if valid_stages(current, i + 1) else None
            archived_evaluation = stage_checkpoint_evals[i]
            if (baseline_evaluation is not None and
                    (archived_evaluation is None or
                     baseline_evaluation.objective_key < archived_evaluation.objective_key)):
                exported = stage_export(current)
                stage_checkpoints[i] = exported
                stage_checkpoint_evals[i] = baseline_evaluation
                stage_checkpoint_origin[i] = "baseline"
                if stage_best_callback is not None:
                    stage_best_callback(stage.name, exported)
                if progress:
                    progress(f"[auto:user-splice:initial] {stage.name!r}: "
                             "saved starting stage result; "
                             f"{_stage_improvement_text(stage.goal, None, baseline_evaluation)}")
    if progress and not summary_only:
        for i, replay in enumerate(restored_stage_frames):
            if replay is not None:
                progress(f"[auto:user-splice:resume] {stages[i].name!r}: "
                         "restored a strictly better historical checkpoint; "
                         f"{_stage_improvement_text(stages[i].goal, None, stage_best_evaluation[i])}")
    if progress and not summary_only:
        for i, stage in enumerate(stages):
            progress(f"[auto:user-splice:physics] {stage.name!r}: "
                     f"simulate-enemies={str(stage_levels[i].simulate_enemies).lower()} "
                     "(Auto, Local, and stage verification)")
        if len(current) > len(source):
            progress(f"[auto:user-splice] appended {len(current) - len(source)} "
                     f"neutral search frame(s) through frame {len(current) - 1}; "
                     "completed outputs remain trimmed")
        text = (f"completion at frame {len(source)}" if source_complete
                else "incomplete source")
        progress(f"[auto:user-splice:baseline] {text}; {len(stages)} named goals; "
                 f"{'full completion' if require_complete else 'endpoint checkpoint'} required")
        if config.search_backend == "both":
            allocation = (f"endpoint Auto {config.iterations // 2} -> "
                          f"Local {(config.iterations + 1) // 2} (seeded from Auto best)")
        else:
            allocation = f"{config.search_backend} {config.iterations}"
        if config.splice_auto_stagnation_rounds or config.splice_local_stagnation_rounds:
            parts = []
            if config.search_backend in ("both", "endpoint-auto"):
                parts.append(f"Auto: {config.splice_auto_stagnation_rounds} stagnant backend rounds")
            if config.search_backend in ("both", "local"):
                parts.append(f"Local: {config.splice_local_stagnation_rounds} stagnant backend rounds")
            progress(f"[auto:user-splice:budget] {allocation} proposals per worker "
                     f"per continuous backend round; {'; '.join(parts)}; "
                     "each backend retains its population until stagnant; "
                     "repeat Auto -> Local phases if either improves; "
                     f"{config.workers} worker(s); "
                     f"{config.rounds or 'unlimited'} outer multi-splice round(s)")
            if config.splice_rounds != 1:
                progress(f"[auto:user-splice] ignoring [multi-splicer] rounds="
                         f"{config.splice_rounds} in independent backend stagnation mode; "
                         "remove the setting from your TOML")
        elif config.splice_stagnation_rounds:
            progress(f"[auto:user-splice:budget] {allocation} proposals per worker "
                     f"per backend turn; {config.splice_rounds} internal round(s) "
                     "per turn; adaptive stage search stops after "
                     f"{config.splice_stagnation_rounds} consecutive non-improving "
                     f"cycle(s) per seed; {config.workers} worker(s); "
                     f"{config.rounds or 'unlimited'} outer multi-splice round(s)")
        else:
            progress(f"[auto:user-splice:budget] {allocation} proposals per worker "
                     f"per internal round, for every stage seed; "
                     f"{config.splice_rounds} internal round(s) per seed; "
                     f"{config.workers} worker(s); "
                     f"{config.rounds or 'unlimited'} outer multi-splice round(s)")

    if progress and (first_stage or last_stage != len(stages) - 1):
        progress(f"[auto:user-splice] selected stages "
                 f"{first_stage+1}-{last_stage+1}/{len(stages)} "
                 f"({stages[first_stage].name!r} through {stages[last_stage].name!r}); "
                 "earlier named goals remain mandatory; "
                 "partial-run outputs remain stage checkpoints")

    def report_checkpoint_summary(label: str) -> None:
        """Show verified full-run propagation, not misleading stage-only ranks.

        'In best' means the saved replay's input prefix through this stage is
        literally present in the completed run. 'Covered' means the completed
        run meets or exceeds its objective, possibly using a different route.
        Neither claims that a temporary stage checkpoint completes the level.
        """
        if progress is None:
            return
        progress(f"[auto:user-splice:summary] {label}: checkpoint propagation "
                 f"({sum(r is not None for r in stage_checkpoints)}/{len(stages)} saved)")
        for i, stage in enumerate(stages):
            archived = stage_checkpoints[i]
            candidate = stage_checkpoint_evals[i]
            if archived is None or candidate is None:
                progress(f"[auto:user-splice:summary:empty] {stage.name!r}: "
                         "no saved stage gain")
                continue
            best_stage = None
            best_workspace = _materialise_splice_tail(best_output, len(current) - 1)
            if best_rank is not None and valid_stages(best_workspace, i + 1):
                best_stage = original_endpoints[i].evaluate(best_workspace)
            detail = _stage_summary_text(stage.goal, candidate)
            if best_stage is None or candidate.objective_key < best_stage.objective_key:
                against = ("best run has no feasible checkpoint" if best_stage is None
                           else "full run: " + _stage_summary_text(stage.goal, best_stage))
                progress(f"[auto:user-splice:summary:pending] {stage.name!r}: "
                         f"pending ({stage_checkpoint_origin[i]}); "
                         f"splice: {detail}; {against}")
            else:
                # Normalize jump triggers and implicit neutral tail before
                # comparing prefixes.  Downstream edits may improve a stage
                # objective without literally preserving the same inputs.
                archived_prefix = _materialise_splice_tail(archived, stage.end - 1)
                best_prefix = _materialise_splice_tail(best_output, stage.end - 1)
                exact = (tuple(editable_frames(archived_prefix[:stage.end])) ==
                         tuple(editable_frames(best_prefix[:stage.end])))
                state = "in best (same input prefix)" if exact else "covered by best (different route)"
                progress(f"[auto:user-splice:summary:propagated] {stage.name!r}: "
                         f"{state} ({stage_checkpoint_origin[i]}); "
                         f"splice: {detail}; full run: "
                         f"{_stage_summary_text(stage.goal, best_stage)}")

    report_checkpoint_summary("saved checkpoints" if summary_only else "startup")
    if summary_only:
        return UserSpliceResult(best_output, 0, 0, 0)

    # Elites are retained across rounds as well as across stage boundaries.
    # Their rank is the objective of the stage that produced them; do not
    # promote a local improvement if its mandatory earlier goals were lost.
    elites: list[list[tuple[InputFrame, ...]]] = [list(pool[:config.frontier]) for pool in archived_frontiers]
    if type(resume_outer_round) is not int or resume_outer_round < 0:
        raise ValueError("invalid saved outer-round progress")
    first_round = (int(active_phase["round_no"]) if active_phase is not None
                   else resume_outer_round)
    for round_no in (itertools.count(first_round) if config.rounds == 0
                     else range(first_round, config.rounds)):
        begun = time.monotonic()
        # A propagation run deliberately retries the archived splice-best
        # path on every outer round, rather than restarting only from the best
        # fully completed run. Completion ranking still uses the original
        # source, and all preceding named goals remain mandatory.
        history: list[list[tuple[InputFrame, ...]]] = [[propagation_seed]]
        history_origins: list[int | None] = [from_best_index]
        if first_stage == 0 and archived_frontiers[0]:
            # A normal restart can search from saved alternatives immediately,
            # rather than merely comparing their scores after the search.
            history[0] = list(dict.fromkeys((propagation_seed,
                                             *archived_frontiers[0][:config.frontier])))
        # Reconstruct lookback at the interrupted stage, not only at the
        # originally requested start. Other routes remain on disk while the
        # interrupted backend's own seed is resumed first.
        restore_index = int(active_phase["stage_index"]) if active_phase is not None else first_stage
        if restore_index > 0:
            if from_best_index is None and archived_frontiers[restore_index - 1]:
                history[0] = list(dict.fromkeys(
                    (*archived_frontiers[restore_index - 1][:config.frontier], propagation_seed)))
                history_origins[0] = restore_index - 1
            for prior in range(restore_index - 2, max(-1, restore_index - config.stage_lookback - 1), -1):
                if archived_frontiers[prior]:
                    history.append(archived_frontiers[prior][:config.frontier])
                else:
                    history.append([])
                history_origins.append(prior)
            history = history[:config.stage_lookback]
            history_origins = history_origins[:config.stage_lookback]
        improved = False
        unfulfilled: list[str] = []
        stage_begin = int(active_phase["stage_index"]) if active_phase is not None else first_stage
        for index in range(stage_begin, last_stage + 1):
            stage = stages[index]
            # Stage-specific Local TOML is an override for both Auto and Local
            # search backends, not a new choice of search backend.
            stage_config = replace(config, **stage.config_overrides)
            if progress and stage.config_overrides:
                progress(f"[auto:user-splice:config] {stage.name!r}: "
                         + ", ".join(f"{key}={value}" for key, value in
                                     sorted(stage.config_overrides.items()))
                         + f"; search={stage_config.search_backend}")
            stage_started = time.monotonic()
            evaluations_before_stage = evaluations
            attempts_before_stage = attempts
            temp_gains = 0
            branches = _stage_sources_history(history, config.frontier)
            if active_phase is not None and index == stage_begin:
                # Never search another route before recovering the interrupted
                # backend. The other viable routes remain archived separately.
                resumed_branch = tuple(editable_frames(decode_complex_replay(
                    active_phase["branch"]).frames))
                branches = [resumed_branch, *(b for b in branches if b != resumed_branch)]
            if progress and len(history) > 1:
                labels = "/".join(f"n-{i}" for i in range(1, len(history) + 1))
                counts = "/".join(str(len(source)) for source in history)
                progress(f"[auto:user-splice] {stage.name!r}: "
                         f"{len(branches)} seed(s) from {labels} frontiers "
                         f"({counts} available; lookback {config.stage_lookback})")
            # Previously discovered stage elites are valid candidates without
            # spending more simulation proposals to rediscover them.
            eligible: dict[tuple[InputFrame, ...], tuple] = {}
            for saved in elites[index]:
                if valid_stages(saved, index + 1):
                    eligible[saved] = original_endpoints[index].evaluate(saved).objective_key
            for seed_index, branch in enumerate(branches, 1):
                # Sources are ranked *within* their own checkpoint objective,
                # not by the score of the stage we are about to search.
                source_detail = "input/best completed replay"
                if active_phase is not None and index == stage_begin and seed_index == 1:
                    source_detail = "resumed interrupted backend seed"
                else:
                    for depth, (pool, origin) in enumerate(zip(history, history_origins), 1):
                        if branch in pool:
                            if origin is not None:
                                source_detail = (f"start from splice {stages[origin].name} "
                                                 f"(n-{index-origin}, source rank {pool.index(branch)+1})")
                            elif from_best_index is not None:
                                source_detail = f"start from splice {stages[from_best_index].name}"
                            break
                if progress:
                    phase_mode = (stage_config.splice_auto_stagnation_rounds or
                                  stage_config.splice_local_stagnation_rounds)
                    if phase_mode:
                        allocation = (f"up to {stage_config.iterations * stage_config.workers * stage_config.splice_rounds} "
                                      "nominal proposal slots per backend batch; "
                                      "total depends on independent Auto/Local stagnation limits")
                    elif stage_config.splice_stagnation_rounds:
                        allocation = (f"{stage_config.iterations * stage_config.workers * stage_config.splice_rounds} "
                                      "nominal proposal slots per cycle for this seed "
                                      "(shared by backends when search=both)")
                    else:
                        allocation = (f"{stage_config.iterations * stage_config.workers * stage_config.splice_rounds} "
                                      "nominal proposal slots for this seed "
                                      "(shared by the two backends when search=both)")
                    progress(f"[auto:user-splice] round {round_no+1}/{config.rounds or chr(8734)} "
                             f"stage {index+1}/{len(stages)} {stage.name!r} "
                             f"seed {seed_index}/{len(branches)} [{source_detail}]; "
                             f"range {stage.start}:{stage.end}, target {stage.goal.target_frame}; "
                             f"search={'Auto -> Local' if stage_config.search_backend == 'both' else stage_config.search_backend}; "
                             f"{allocation}")
                def accept_stage_candidate(candidate: tuple[InputFrame, ...]) -> None:
                    nonlocal current, best_output, best_rank, improvements, improved, temp_gains
                    # Verify promising live candidates without making every
                    # worker wait for repeated stage/archive simulations.
                    # The encode/decode round trip only rebuilds trigger bits;
                    # editable_frames drops them again. Normalise directly and
                    # validate each previous goal only once per candidate.
                    normalized = tuple(editable_frames(candidate))
                    if normalized in eligible:
                        # Duplicate live notifications and returned winners are
                        # common; their verified stage score cannot change.
                        return
                    evaluation = original_endpoints[index].evaluate(normalized)
                    if not evaluation.feasible or not all(
                        endpoint.evaluate(normalized).feasible
                        for endpoint in original_endpoints[:index]
                    ):
                        return
                    rank = evaluation.objective_key
                    eligible[normalized] = rank
                    # Frontier archives are persistence, not the active search
                    # population. Flush them at stage boundaries instead of
                    # repeatedly simulating 64 routes while workers wait.
                    candidate_final = (
                        final_rank(normalized)
                        if index == len(stages) - 1 and
                        (best_rank is None or rank <= best_rank[0]) else None
                    )
                    is_final_gain = (candidate_final is not None
                                     and (best_rank is None
                                          or candidate_final[0] < best_rank))
                    old_stage_rank = stage_best[index]
                    old_evaluation = stage_best_evaluation[index]
                    if old_stage_rank is None or rank < old_stage_rank:
                        stage_best[index] = rank
                        stage_best_evaluation[index] = evaluation
                        exported = stage_export(normalized)
                        stage_checkpoints[index] = exported
                        stage_checkpoint_evals[index] = evaluation
                        stage_checkpoint_origin[index] = "this run"
                        temp_gains += 1
                        if stage_best_callback:
                            stage_best_callback(stage.name, exported)
                        if progress and not is_final_gain:
                            label = ("first feasible" if old_stage_rank is None
                                     else "new stage best")
                            progress(f"[auto:user-splice:temporary] "
                                     f"round {round_no+1} stage {index+1}/{len(stages)} "
                                     f"{stage.name!r}: {label}; "
                                     f"{_stage_improvement_text(stage.goal, old_evaluation, evaluation)}")
                    if is_final_gain:
                        candidate_rank, completed_frames = candidate_final
                        current = normalized
                        best_output = completed_frames
                        best_rank = candidate_rank
                        improvements += 1
                        improved = True
                        if best_callback:
                            best_callback(best_output)
                        if progress:
                            progress(f"[auto:user-splice] improved verified final replay "
                                     f"({stage.name}); "
                                     f"{_stage_improvement_text(stage.goal, old_evaluation, evaluation)}; "
                                     "saved")

                last_live_accept = float("-inf")
                def live_candidate(candidate: tuple[InputFrame, ...], frame: int) -> None:
                    nonlocal last_live_accept
                    now = time.monotonic()
                    if stage_config.workers > 1 and now - last_live_accept < 30.0:
                        return
                    last_live_accept = now
                    accept_stage_candidate(candidate)

                def save_phase(state: dict[str, object]) -> None:
                    if save_resume_state is None:
                        return
                    envelope = {"version": 1,
                                "level_sha256": hashlib.sha256(level.source_level_string.encode()).hexdigest(),
                                "source_sha256": hashlib.sha256(encode_complex_replay(source).encode()).hexdigest(),
                                "stages": [item.name for item in stages],
                                "stage_settings": [repr(item) for item in stages],
                                "config": repr(config), "from_best": from_best,
                                "start_at": start_at, "stop_at": stop_at,
                                "round_no": round_no, "stage_index": index,
                                "stage": stage.name,
                                "branch": encode_complex_replay(branch),
                                "phase": state}
                    save_resume_state(envelope)

                resuming_this_seed = (active_phase is not None and
                                      index == stage_begin and seed_index == 1)
                if (stage_config.splice_stagnation_rounds or stage_config.splice_auto_stagnation_rounds
                        or stage_config.splice_local_stagnation_rounds):
                    def admissible_rank(candidate, through=index + 1):
                        if not valid_stages(candidate, through):
                            return None
                        return original_endpoints[through - 1].evaluate(candidate).objective_key
                    found, used, calls = _search_stage(
                        stage_levels[index], branch, stage, stage_config, rng,
                        stage_rank=admissible_rank, progress=progress,
                        candidate_callback=live_candidate,
                        **({"resume_phase": active_phase["phase"] if resuming_this_seed else None,
                            "phase_started": save_phase,
                            "backend_checkpoint_path":
                                (lambda backend, name=stage.name:
                                 backend_checkpoint_path(name, backend))}
                           if save_resume_state is not None and backend_checkpoint_path is not None
                           else {}))
                else:
                    found, used, calls = _search_stage(
                        stage_levels[index], branch, stage, stage_config, rng,
                        candidate_callback=live_candidate)
                if save_resume_state is not None:
                    save_resume_state(None)
                active_phase = None
                attempts += calls
                evaluations += used
                for candidate, _ in (*found, (branch, stage.goal.target_frame)):
                    accept_stage_candidate(candidate)
            if progress:
                progress(f"[auto:user-splice:stage] round {round_no+1} "
                         f"{stage.name!r}: {attempts - attempts_before_stage} "
                         f"backend search(es), {evaluations - evaluations_before_stage} "
                         f"distinct evaluations, {len(eligible)} eligible replay(s), "
                         f"{temp_gains} stage-best update(s); "
                         f"stage best "
                         f"{_stage_improvement_text(stage.goal, None, stage_best_evaluation[index]) if stage_best_evaluation[index] is not None else 'none'}; "
                         f"{time.monotonic() - stage_started:.1f}s")
            if not eligible:
                # A temporarily infeasible intermediate checkpoint must not
                # silently abort the remaining named stages. Later edits may
                # recover it, and the unchanged (possibly completed) source
                # remains a useful seed for an independently searched final
                # stage. Keep the two-back branches rather than discarding
                # them on a failed waypoint. Crucially, final_rank STILL
                # requires every named goal and canonical completion: these
                # fallbacks are search seeds, not accepted results.
                unfulfilled.append(stage.name)
                fallbacks = list(dict.fromkeys((current, *branches)))[:max(2, config.frontier)]
                if progress:
                    progress(f"[auto:user-splice] stage {index+1}/{len(stages)} "
                             f"{stage.name!r}: no candidate met all goals through this stage; "
                             f"continuing with {len(fallbacks)} fallback seed(s) "
                             "(final verification still requires all named goals)")
                history = [fallbacks, *history][:config.stage_lookback]
                history_origins = [index, *history_origins][:config.stage_lookback]
                continue
            ordered = sorted(eligible.items(), key=lambda item: item[1])
            # Keep distinct earlier-stage frontiers independent of whether a
            # more recent stage wins its own intermediate ranking.
            selected = [candidate for candidate, _ in ordered[:max(1, config.frontier)]]
            elites[index] = selected
            publish_frontier(index, [candidate for candidate, _ in ordered[:config.save_frontier]])
            history = [selected, *history][:config.stage_lookback]
            history_origins = [index, *history_origins][:config.stage_lookback]
        stagnant = 0 if improved else stagnant + 1
        if progress:
            progress(f"[auto:user-splice] round {round_no+1} complete in "
                     f"{time.monotonic()-begun:.1f}s; {evaluations} evaluations; "
                     f"{improvements} saved improvement(s); stagnant {stagnant}"
                     + (f"; unmet checkpoints: {', '.join(unfulfilled)}"
                        if unfulfilled else ""))
        report_checkpoint_summary(f"after round {round_no+1}")
        if save_outer_round is not None:
            save_outer_round(round_no + 1)
        if config.stagnation_rounds and stagnant >= config.stagnation_rounds:
            break
    if save_outer_round is not None:
        save_outer_round(None)
    report_checkpoint_summary("final")
    return UserSpliceResult(best_output, improvements, attempts, evaluations)

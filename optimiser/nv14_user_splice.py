"""Ordered, user-defined multi-splicing using existing Local/Auto endpoint search.

Unlike stochastic waypoints, every stage is an explicitly named Local goal file.
Partial branches may pass between stages, but a published result must satisfy all
configured goals, preserve pre-existing route controls, and (for a completed
source) remain canonically complete.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Callable, Mapping, Sequence
import itertools
import math
import random
import time

from nv14_auto import evaluate_replay_with_sentinel
from nv14_endpoint import EndpointGoal, EndpointEvaluator, EndpointEvaluation
from nv14_engine import InputFrame, Level
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
            progress=progress, candidate_callback=candidate_callback)
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
    evaluations = calls = cycle = 0
    while True:
        cycle += 1
        cycle_improved = False
        for backend, iterations, patience in phases:
            if progress:
                progress(f"[auto:user-splice:refine] {stage.name!r}: "
                         f"cycle {cycle}, starting continuous {backend} phase "
                         f"(stop after {patience} stagnant rounds)")
            phase_improved = False

            def on_live_best(frames: tuple[InputFrame, ...], frame: int) -> None:
                nonlocal incumbent, best_rank, phase_improved, cycle_improved
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
                    seed=rng.getrandbits(63), include_partial=True,
                    best_callback=on_live_best if candidate_callback is not None else None)
            except ValueError as exc:
                if not str(exc).startswith("the immutable prefix dies before the editable ranges"):
                    raise
                found, used = (), 0
            evaluations += used
            calls += 1
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
    saved_stage_candidates: Mapping[str, Sequence[Sequence[InputFrame]]] | None = None,
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
    first_stage = stage_index(start_at, 0, "start")
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
    require_complete = completion_policy == "complete" or source_complete
    if completion_policy == "complete" and not source_complete:
        raise ValueError("user splice requires a canonically completed source for completion-policy=complete")
    for stage in stages:
        if not (0 <= stage.start <= stage.end <= stage.goal.target_frame < len(current)):
            raise ValueError(f"invalid range/target-frame for splice {stage.name!r}")
    rng = random.Random(config.seed)
    original_endpoints = tuple(EndpointEvaluator(level, s.goal) for s in stages)
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
    best_output = source
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
    if progress:
        for i, replay in enumerate(restored_stage_frames):
            if replay is not None:
                progress(f"[auto:user-splice:resume] {stages[i].name!r}: "
                         "restored a strictly better historical checkpoint; "
                         f"{_stage_improvement_text(stages[i].goal, None, stage_best_evaluation[i])}")
    if progress:
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

    report_checkpoint_summary("startup")

    # Elites are retained across rounds as well as across stage boundaries.
    # Their rank is the objective of the stage that produced them; do not
    # promote a local improvement if its mandatory earlier goals were lost.
    elites: list[list[tuple[InputFrame, ...]]] = [[] for _ in stages]
    for round_no in (itertools.count() if config.rounds == 0 else range(config.rounds)):
        begun = time.monotonic()
        history: list[list[tuple[InputFrame, ...]]] = [[current]]
        improved = False
        unfulfilled: list[str] = []
        for index in range(first_stage, last_stage + 1):
            stage = stages[index]
            stage_started = time.monotonic()
            evaluations_before_stage = evaluations
            attempts_before_stage = attempts
            temp_gains = 0
            branches = _stage_sources_history(history, config.frontier)
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
                if progress:
                    phase_mode = (config.splice_auto_stagnation_rounds or
                                  config.splice_local_stagnation_rounds)
                    if phase_mode:
                        allocation = (f"up to {config.iterations * config.workers * config.splice_rounds} "
                                      "nominal proposal slots per backend batch; "
                                      "total depends on independent Auto/Local stagnation limits")
                    elif config.splice_stagnation_rounds:
                        allocation = (f"{config.iterations * config.workers * config.splice_rounds} "
                                      "nominal proposal slots per cycle for this seed "
                                      "(shared by backends when search=both)")
                    else:
                        allocation = (f"{config.iterations * config.workers * config.splice_rounds} "
                                      "nominal proposal slots for this seed "
                                      "(shared by the two backends when search=both)")
                    progress(f"[auto:user-splice] round {round_no+1}/{config.rounds or chr(8734)} "
                             f"stage {index+1}/{len(stages)} {stage.name!r} "
                             f"seed {seed_index}/{len(branches)}; "
                             f"range {stage.start}:{stage.end}, target {stage.goal.target_frame}; "
                             f"search={'Auto -> Local' if config.search_backend == 'both' else config.search_backend}; "
                             f"{allocation}")
                def accept_stage_candidate(candidate: tuple[InputFrame, ...]) -> None:
                    nonlocal current, best_output, best_rank, improvements, improved, temp_gains
                    # Validate in the same way as the post-search frontier.
                    # Native backend callbacks can arrive before the phase
                    # ends, so stage checkpoints are now durable immediately.
                    if not valid_stages(candidate, index + 1):
                        return
                    normalized = tuple(editable_frames(decode_complex_replay(
                        encode_complex_replay(candidate)).frames))
                    if not valid_stages(normalized, index + 1):
                        return
                    evaluation = original_endpoints[index].evaluate(normalized)
                    rank = evaluation.objective_key
                    if normalized not in eligible or rank < eligible[normalized]:
                        eligible[normalized] = rank
                    candidate_final = (final_rank(normalized)
                                       if index == len(stages) - 1 else None)
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

                def live_candidate(candidate: tuple[InputFrame, ...], frame: int) -> None:
                    accept_stage_candidate(candidate)

                if (config.splice_stagnation_rounds or config.splice_auto_stagnation_rounds
                        or config.splice_local_stagnation_rounds):
                    def admissible_rank(candidate, through=index + 1):
                        if not valid_stages(candidate, through):
                            return None
                        return original_endpoints[through - 1].evaluate(candidate).objective_key
                    found, used, calls = _search_stage(
                        level, branch, stage, config, rng,
                        stage_rank=admissible_rank, progress=progress,
                        candidate_callback=live_candidate)
                else:
                    found, used, calls = _search_stage(
                        level, branch, stage, config, rng,
                        candidate_callback=live_candidate)
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
                continue
            ordered = sorted(eligible.items(), key=lambda item: item[1])
            # Keep distinct earlier-stage frontiers independent of whether a
            # more recent stage wins its own intermediate ranking.
            selected = [candidate for candidate, _ in ordered[:max(1, config.frontier)]]
            elites[index] = selected
            history = [selected, *history][:config.stage_lookback]
        stagnant = 0 if improved else stagnant + 1
        if progress:
            progress(f"[auto:user-splice] round {round_no+1} complete in "
                     f"{time.monotonic()-begun:.1f}s; {evaluations} evaluations; "
                     f"{improvements} saved improvement(s); stagnant {stagnant}"
                     + (f"; unmet checkpoints: {', '.join(unfulfilled)}"
                        if unfulfilled else ""))
        report_checkpoint_summary(f"after round {round_no+1}")
        if config.stagnation_rounds and stagnant >= config.stagnation_rounds:
            break
    report_checkpoint_summary("final")
    return UserSpliceResult(best_output, improvements, attempts, evaluations)

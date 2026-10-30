"""Ordered, user-defined multi-splicing using existing Local/Auto endpoint search.

Unlike stochastic waypoints, every stage is an explicitly named Local goal file.
Partial branches may pass between stages, but a published result must satisfy all
configured goals, preserve pre-existing route controls, and (for a completed
source) remain canonically complete.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Callable, Sequence
import itertools
import random
import time

from nv14_auto import evaluate_replay_with_sentinel
from nv14_endpoint import EndpointGoal, EndpointEvaluator
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
                  rng: random.Random) -> tuple[tuple[tuple[tuple[InputFrame, ...], int], ...], int, int]:
    """Run the requested backends with one shared per-branch proposal budget.

    With ``both``, an odd budget gives the extra proposal to Local. This is
    deliberately *not* two full searches: the sum of backend iteration budgets
    is exactly config.iterations. Native evaluation counts are reported as is.
    """
    if config.search_backend == "both":
        if config.iterations < 2:
            raise ValueError("splice-search=both requires splice-iterations >= 2")
        modes = (("local", (config.iterations + 1) // 2),
                 ("endpoint-auto", config.iterations // 2))
    else:
        modes = ((config.search_backend, config.iterations),)
    merged: dict[tuple[InputFrame, ...], int] = {}
    evaluations = 0
    searches = 0
    for backend, iterations in modes:
        try:
            found, used = _local_search(
                level, branch, stage.goal, start=stage.start,
                editable_end=stage.end,
                config=replace(config, search_backend=backend),
                iterations=iterations, rounds=config.splice_rounds,
                seed=rng.getrandbits(63), include_partial=True)
        except ValueError as exc:
            if not str(exc).startswith("the immutable prefix dies before the editable ranges"):
                raise
            found, used = (), 0
        evaluations += used
        searches += 1
        for candidate, frame in found:
            merged.setdefault(tuple(candidate), frame)
    return tuple(merged.items()), evaluations, searches


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


def _materialise_splice_tail(frames: Sequence[InputFrame], target_frame: int
                             ) -> tuple[InputFrame, ...]:
    """Materialise the neutral inputs implicit past a recorded replay's end.

    This is a search-only workspace. A canonically completed source retains
    its original length, and verified outputs are trimmed to their finish tick.
    """
    body = tuple(frames)
    return body + (InputFrame(),) * max(0, target_frame + 1 - len(body))


def optimise_user_splices(
    level: Level, source_frames: Sequence[InputFrame],
    stages: Sequence[UserSpliceStage], config: RandomSpliceConfig,
    *, best_callback: Callable[[tuple[InputFrame, ...]], None] | None = None,
    progress: Callable[[str], None] | None = None,
    completion_policy: str = "complete",
) -> UserSpliceResult:
    """Optimise named goals in order, retaining diverse feasible continuations.

    Use identical endpoint evaluation and Local/Hybrid search as random splicing.
    No partial result is written. An existing completed source is never replaced
    by an incomplete route or by one that loses reference control interactions.
    """
    if not stages:
        raise ValueError("user splice requires at least one named goal")
    if completion_policy not in ("checkpoint", "complete"):
        raise ValueError("invalid user splice completion policy")
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

    baseline = final_rank(current)
    best_rank = baseline[0] if baseline is not None else None
    best_output = source
    improvements = attempts = evaluations = stagnant = 0
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
            progress(f"[auto:user-splice] Local + endpoint Auto: "
                     f"{(config.iterations + 1) // 2} + {config.iterations // 2} "
                     f"proposals per worker, per stage-seed search")

    # Elites are retained across rounds as well as across stage boundaries.
    # Their rank is the objective of the stage that produced them; do not
    # promote a local improvement if its mandatory earlier goals were lost.
    elites: list[list[tuple[InputFrame, ...]]] = [[] for _ in stages]
    for round_no in (itertools.count() if config.rounds == 0 else range(config.rounds)):
        begun = time.monotonic()
        previous: list[tuple[InputFrame, ...]] = [current]
        two_back: list[tuple[InputFrame, ...]] = []
        improved = False
        for index, stage in enumerate(stages):
            branches = _stage_sources(previous, two_back, config.frontier)
            if progress and index >= 2:
                progress(f"[auto:user-splice] {stage.name!r}: "
                         f"{len(branches)} seed(s) from n-1/n-2 frontiers "
                         f"({len(previous)}/{len(two_back)} available)")
            # Previously discovered stage elites are valid candidates without
            # spending more simulation proposals to rediscover them.
            eligible: dict[tuple[InputFrame, ...], tuple] = {}
            for saved in elites[index]:
                if valid_stages(saved, index + 1):
                    eligible[saved] = original_endpoints[index].evaluate(saved).objective_key
            for branch in branches:
                if progress:
                    progress(f"[auto:user-splice] round {round_no+1}/{config.rounds or chr(8734)} "
                             f"stage {index+1}/{len(stages)} {stage.name!r} "
                             f"range {stage.start}:{stage.end}, target {stage.goal.target_frame}; "
                             f"search={config.search_backend}")
                found, used, calls = _search_stage(level, branch, stage, config, rng)
                attempts += calls
                evaluations += used
                for candidate, _ in (*found, (branch, stage.goal.target_frame)):
                    # n-2 seeds can bypass a detrimental n-1 optimisation,
                    # but cannot bypass the requirements of any named goal.
                    if not valid_stages(candidate, index + 1):
                        continue
                    normalized = tuple(editable_frames(decode_complex_replay(
                        encode_complex_replay(candidate)).frames))
                    if not valid_stages(normalized, index + 1):
                        continue
                    rank = original_endpoints[index].evaluate(normalized).objective_key
                    if normalized not in eligible or rank < eligible[normalized]:
                        eligible[normalized] = rank
                    if index == len(stages) - 1:
                        candidate_final = final_rank(normalized)
                        if candidate_final is None:
                            continue
                        candidate_rank, completed_frames = candidate_final
                        if best_rank is not None and not candidate_rank < best_rank:
                            continue
                        current = normalized
                        best_output = completed_frames
                        best_rank = candidate_rank
                        improvements += 1
                        improved = True
                        if best_callback:
                            best_callback(best_output)
                        if progress:
                            progress(f"[auto:user-splice] improved verified final replay "
                                     f"({stage.name}); rank {candidate_rank}; saved")
            if not eligible:
                # Failure to satisfy this stage must never bypass the goal.
                previous = []
                break
            ordered = sorted(eligible.items(), key=lambda item: item[1])
            # Preserve at least the top n-2 option independent of whether an
            # n-1 candidate later wins its own stage ranking.
            selected = [candidate for candidate, _ in ordered[:max(1, config.frontier)]]
            elites[index] = selected
            two_back, previous = previous, selected
        stagnant = 0 if improved else stagnant + 1
        if progress:
            progress(f"[auto:user-splice] round {round_no+1} complete in "
                     f"{time.monotonic()-begun:.1f}s; {evaluations} evaluations; "
                     f"{improvements} saved improvement(s); stagnant {stagnant}")
        if config.stagnation_rounds and stagnant >= config.stagnation_rounds:
            break
    return UserSpliceResult(best_output, improvements, attempts, evaluations)

"""Ordered, user-defined multi-splicing using existing Local/Auto endpoint search.

Unlike stochastic waypoints, every stage is an explicitly named Local goal file.
Partial branches may pass between stages. Each splice is an independent search
objective, not a required waypoint for later stages. Completed results must be
canonically verified and preserve pre-existing route controls.
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
from nv14_splice_merge import verified_suffix_grafts, repair_suffix_grafts
from nv14_splice_backend import (_search_stage as search_splice_stage, splice_config_for_round)


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
                  rng: random.Random, **kwargs):
    """Named-stage adapter; search machinery is shared with sampled splicers."""
    return search_splice_stage(level, branch, stage, config, rng,
                               local_search=_local_search, evaluator_factory=EndpointEvaluator, **kwargs)


def _unique_search_seeds(
    level: Level, branches: Sequence[tuple[InputFrame, ...]], start: int,
) -> list[tuple[InputFrame, ...]]:
    """Search a physical start state and its future input suffix only once.

    Whole-replay equality misses e.g. a saved completed run whose earlier
    button presses differ but whose position, velocity, object state and held
    input history are *exactly* the same at this splice's editable start.
    Compare the complete deterministic simulation state (not rounded x/y)
    and every remaining input: different suffixes can produce different full
    completions and must remain independent search seeds.
    """
    from nv14_replay import simulate_through_frame

    seen: set[tuple] = set()
    unique: list[tuple[InputFrame, ...]] = []
    for frames in branches:
        frames = tuple(frames)
        # A too-short branch is handled by the backend's ordinary preflight;
        # do not silently discard it or compare at a nonexistent frame.
        if start > len(frames):
            unique.append(frames)
            continue
        state = simulate_through_frame(level, frames, start - 1)
        signature = (state.state_key(), frames[start:])
        if signature not in seen:
            seen.add(signature)
            unique.append(frames)
    return unique


def _stage_sources(recent: Sequence[tuple[InputFrame, ...]],
                   two_back: Sequence[tuple[InputFrame, ...]],
                   frontier: int) -> list[tuple[InputFrame, ...]]:
    """Keep the strongest candidates from n-1 AND n-2 as stage n seeds.

    Both lists are already sorted by *their own* stage objective, so the
    n-2 candidates are not spuriously ranked by the n-1 objective. Reserve at
    least one slot for each distinct source, even with frontier=1. Seeds need
    not be feasible at n-1; later checkpoints are checked against their own
    goal, while completed results are independently verified.
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
    preserve: Sequence[tuple[InputFrame, ...]] = (),
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
    # Retain one independently useful interval-fast replay when its score at
    # the current helper is lower-ranked. It remains a complete, replayable
    # frontier member rather than a detached input segment with no state.
    if limit > 1:
        for candidate in preserve[:1]:
            if candidate in pool and candidate not in seen:
                selected[-1] = candidate
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


def _stage_savings_text(goal: EndpointGoal,
                        candidate: EndpointEvaluation,
                        reference: EndpointEvaluation | None,
                        label: str) -> str:
    """Compare physical frames and goal-directed pixel distance, not ranking keys.

    A positive difference is a saving. Purely frame-based objectives have no
    scored pixel metric, so their x/y displacement is labelled as positional.
    """
    if reference is None:
        return f"vs {label}: unavailable (no feasible checkpoint)"
    frames_saved = reference.frame - candidate.frame
    objective = goal.objective
    pixel_saving = None
    pixel_label = objective
    if objective in ("min-x", "max-x", "min-y", "max-y"):
        axis = "x" if objective.endswith("-x") else "y"
        before, after = getattr(reference, axis), getattr(candidate, axis)
        pixel_saving = before - after if objective.startswith("min-") else after - before
    elif objective == "min-distance":
        # min-distance scores are NEGATIVE SQUARED distances.
        pixel_saving = (math.sqrt(max(0.0, -reference.score)) -
                        math.sqrt(max(0.0, -candidate.score)))
    elif goal.secondary_objective in ("min-x", "max-x", "min-y", "max-y",
                                       "min-exit-distance"):
        pixel_label = goal.secondary_objective
        before, after = reference.secondary_value, candidate.secondary_value
        pixel_saving = (before - after if pixel_label.startswith("min-")
                        else after - before)
    result = f"vs {label}: {frames_saved:+d} frames saved"
    if pixel_saving is not None and math.isfinite(pixel_saving):
        return result + f", {pixel_saving:+.6g} px saved ({pixel_label})"
    if all(math.isfinite(v) for v in (reference.x, reference.y, candidate.x, candidate.y)):
        return (result + f", position dx {candidate.x-reference.x:+.6g} px, "
                f"dy {candidate.y-reference.y:+.6g} px (not scored)")
    return result


def optimise_user_splices(
    level: Level, source_frames: Sequence[InputFrame],
    stages: Sequence[UserSpliceStage], config: RandomSpliceConfig,
    *, best_callback: Callable[[tuple[InputFrame, ...]], None] | None = None,
    stage_best_callback: Callable[[str, tuple[InputFrame, ...]], None] | None = None,
    progress: Callable[[str], None] | None = None,
    completion_policy: str = "complete",
    start_at: str | None = None, stop_at: str | None = None,
    from_best: str | None = None,
    start_from_stage_bests: bool = False,
    reference_frames: Sequence[InputFrame] | None = None,
    merge_stage_bests: bool = False,
    merge_only: bool = False,
    merge_verbose: bool = False,
    merge_repair_only: bool = False,
    merge_repair_at_end: bool = False,
    merge_repair_pairs: int = 48,
    merge_repair_window: int = 48,
    merge_repair_targets: int = 2,
    saved_stage_candidates: Mapping[str, Sequence[Sequence[InputFrame]]] | None = None,
    saved_stage_frontiers: Mapping[str, Sequence[Sequence[InputFrame]]] | None = None,
    saved_final_frames: Sequence[InputFrame] | None = None,
    reporting_input_frames: Sequence[InputFrame] | None = None,
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
    stage_best_callback receives each stage's independently feasible intermediate replay
    (which need not finish the level), only after a genuine improvement.
    An existing completed final result is never replaced by an incomplete route.
    """
    if not stages:
        raise ValueError("user splice requires at least one named goal")
    if completion_policy not in ("checkpoint", "complete"):
        raise ValueError("invalid user splice completion policy")
    if merge_only and (not merge_stage_bests or summary_only or from_best is not None):
        raise ValueError("merge-only requires merge_stage_bests, without summary-only or from-best")
    if merge_repair_only and not merge_only:
        raise ValueError("merge-repair-only requires merge-only")
    if merge_repair_at_end and not merge_stage_bests:
        raise ValueError("merge-repair-at-end requires merge-bests")
    for name, value, minimum in (("merge_repair_pairs", merge_repair_pairs, 1),
                                 ("merge_repair_window", merge_repair_window, 2),
                                 ("merge_repair_targets", merge_repair_targets, 1)):
        if type(value) is not int or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}")
    # Named goals are independent helpers, not route requirements.
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
    # --ls-splice uses saved final frames as its working replay; preserve the
    # CLI input replay independently so the reporting baseline stays correct.
    reporting_input = (tuple(editable_frames(reporting_input_frames))
                       if reporting_input_frames is not None else source)
    reference = (tuple(editable_frames(reference_frames))
                 if reference_frames is not None else None)
    if reference is not None:
        reference_eval = evaluate_replay_with_sentinel(level, reference)
        if not reference_eval.valid or reference_eval.finish_tick != len(reference):
            raise ValueError("splice reference must be a verified completed replay")
    # Check canonical completion *before* materialising any neutral search
    # inputs. Otherwise a completed source looks incomplete merely because
    # the last named target-frame is later than its real finish tick.
    source_eval = evaluate_replay_with_sentinel(level, source)
    source_complete = bool(source_eval.valid and source_eval.finish_tick == len(source))
    current = _materialise_splice_tail(source, max(s.goal.target_frame for s in stages))
    # A completed saved final output must never be displaced by an incomplete
    # checkpoint, even when the new input is incomplete and policy=checkpoint.
    # A stale/incomplete saved file is a reusable hint at most, not a veto
    # on a new campaign. Canonical completion is independently verified below.
    # The merge-only command never publishes a stage checkpoint as the final
    # replay, even when the source uses completion-policy=checkpoint.
    require_complete = (completion_policy == "complete" or source_complete or merge_only)
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
    reporting_workspace = _materialise_splice_tail(
        reporting_input, max(s.goal.target_frame for s in stages))
    # Feasibility is local to each named stage. A later route can bypass a
    # previous helper region without losing a valid new checkpoint. Real game
    # controls are checked by the canonical replay / control-preservation gate.
    def stage_feasible(frames, index: int) -> bool:
        return original_endpoints[index].evaluate(frames).feasible

    # Reporting must not add simulation work to headless searches.
    input_stage_evals = (tuple(
        endpoint.evaluate(reporting_workspace)
        if stage_feasible(reporting_workspace, i) else None
        for i, endpoint in enumerate(original_endpoints)
    ) if progress is not None else (None,) * len(stages))

    def final_rank(frames):
        # The named goals are search hints, NOT finish requirements. Once a
        # completed replay is required, rank it by actual completion time and
        # exit proximity, independently of every named endpoint objective.
        # Checkpoint-policy campaigns without a completed baseline still use
        # the final named goal to rank their provisional (incomplete) outputs.
        if not require_complete and not stage_feasible(frames, len(stages) - 1):
            return None
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
            return (_completed_rank(completed, length),), tuple(frames[:length])
        return (original_endpoints[-1].evaluate(frames).objective_key,), tuple(frames)

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
    saved_rank = None
    saved_final = None
    if saved_final_frames is not None:
        saved_final = tuple(editable_frames(saved_final_frames))
        # Never let an older input replay overwrite a faster verified final
        # result. Independently verify the archived movie in real physics.
        physical = evaluate_replay_with_sentinel(level, saved_final)
        saved_complete = physical.valid and physical.finish_tick == len(saved_final)
        if saved_complete:
            if not require_complete:
                # The source may be an incomplete but very strong checkpoint.
                # Do not compare its stage score against completed replays.
                require_complete = True
                rescored = final_rank(current)
                best_rank = rescored[0] if rescored is not None else None
                best_output = rescored[1] if rescored is not None else source
            require_complete = True  # do not replace a completed movie with a partial one
            saved_rank = final_rank(_materialise_splice_tail(saved_final, len(current) - 1))
            if saved_rank is not None:
                if best_rank is None or saved_rank[0] < best_rank:
                    best_rank, best_output = saved_rank
                if progress:
                    progress("[auto:user-splice:resume] verified compatible saved final "
                             "replay; retained as the score baseline")
            elif progress:
                progress("[auto:user-splice:resume] saved completed replay fails "
                         "current route-control or completion verification; "
                         "retaining on disk until a new verified completion is found")
        elif progress:
            progress("[auto:user-splice:resume] saved final is not a verified "
                     "completion; treating it as an obsolete search artifact, "
                     "not a barrier to a new run")
    improvements = attempts = evaluations = stagnant = 0
    # A manually edited completed input is authoritative when it is faster
    # than the older output on disk. Previously it became the in-memory best
    # without being persisted, leaving the saved final file stale on reruns.
    # Summary-only is read-only. Merge-only may publish a verified, faster
    # manually edited input, but never creates search checkpoints or sidecars.
    if (not summary_only and source_complete and
            saved_final_frames is not None and baseline is not None and
            (saved_rank is None or baseline[0] < saved_rank[0])):
        if best_callback:
            best_callback(baseline[1])
        improvements += 1
        if progress:
            previous = (f"{len(saved_final)} -> {len(source)} frames"
                        if saved_rank is not None else
                        f"replacing unverified saved output with {len(source)}-frame completion")
            progress("[auto:user-splice] improved verified final replay "
                     f"(current input); {previous}; saved manually edited replay")

    def accept_merged_completion(prefix, seam, label):
        """Publish a reference suffix only after final replay verification."""
        nonlocal best_output, best_rank, improvements, current
        if reference is None:
            return
        for joined in verified_suffix_grafts(
                level, prefix, reference, seam_frame=seam,
                lookback=config.lookback):
            padded = _materialise_splice_tail(joined, len(current)-1)
            scored = final_rank(padded)
            if scored is None or (best_rank is not None and scored[0] >= best_rank):
                continue
            best_rank, best_output = scored
            current = padded
            improvements += 1
            if best_callback:
                best_callback(best_output)
            if progress:
                progress(f"[auto:user-splice:merge] {label}: verified reference "
                         f"suffix propagated; complete at frame {len(best_output)}; saved")

    stage_best: list[tuple | None] = []
    stage_best_evaluation: list[EndpointEvaluation | None] = []
    for i, endpoint in enumerate(original_endpoints):
        # The baseline is a real stage reference, not a reported improvement.
        feasible = stage_feasible(current, i)
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
            if not stage_feasible(replay, i):
                if progress:
                    progress(f"[auto:user-splice:resume] {stage.name!r}: "
                             "ignored checkpoint failing its own goal")
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
    def section_duration(index: int, frames: tuple[InputFrame, ...]) -> int | None:
        """Measure an actual within-replay checkpoint interval when meaningful.

        Spatial-only helper endpoints refer to fixed frames, so their fixed
        difference is NOT evidence of a faster physical section. At least
        one endpoint must measure an actual earliest arrival/interaction, and
        BOTH checkpoints must be independently feasible in this same replay.
        """
        if index < 1:
            return None
        previous, stage = stages[index-1], stages[index]
        if not (previous.goal.is_earliest or stage.goal.is_earliest):
            return None
        workspace = _materialise_splice_tail(frames,
                                             max(previous.goal.target_frame, stage.goal.target_frame))
        prior = original_endpoints[index-1].evaluate(workspace)
        current_score = original_endpoints[index].evaluate(workspace)
        if not prior.feasible or not current_score.feasible or prior.frame > current_score.frame:
            return None
        return current_score.frame - prior.frame

    def select_archive(index: int, pool: Mapping[tuple[InputFrame, ...], tuple]
                       ) -> list[tuple[InputFrame, ...]]:
        durations = [(duration, pool[frames], frames)
                     for frames in pool
                     if (duration := section_duration(index, frames)) is not None]
        fastest = min(durations, key=lambda row: (row[0], row[1]))[2] if durations else None
        return _diverse_saved_archive(pool, original_endpoints[index],
                                      config.save_frontier,
                                      preserve=(() if fastest is None else (fastest,)))

    # Restore top stage populations separately from the single best LTM/TXT.
    # The old one-best checkpoints are also valid fallbacks for archives that
    # predate this feature. Re-check all entries under each stage's physics.
    archived_frontiers: list[list[tuple[InputFrame, ...]]] = []
    for i, stage in enumerate(stages):
        pool: dict[tuple[InputFrame, ...], tuple] = {}
        for raw in (*((saved_stage_frontiers or {}).get(stage.name, ())),
                    *((saved_stage_candidates or {}).get(stage.name, ()))):
            replay = _materialise_splice_tail(raw, len(current) - 1)
            if stage_feasible(replay, i):
                pool[replay] = original_endpoints[i].evaluate(replay).objective_key
        ranked = sorted(pool, key=pool.__getitem__)
        archived_frontiers.append(select_archive(i, pool))
        if progress and ranked and not summary_only:
            progress(f"[auto:user-splice:resume] {stage.name!r}: "
                     f"restored {len(archived_frontiers[-1])} validated archive candidate(s); "
                     f"up to {config.frontier} actively searched per source")

    def publish_frontier(i: int, candidates: Sequence[tuple[InputFrame, ...]]) -> None:
        if frontier_callback is None or summary_only:
            return
        pool: dict[tuple[InputFrame, ...], tuple] = {}
        for candidate in (*archived_frontiers[i], *candidates):
            if stage_feasible(candidate, i):
                pool[candidate] = original_endpoints[i].evaluate(candidate).objective_key
        selected = select_archive(i, pool)
        if selected != archived_frontiers[i]:
            frontier_callback(stages[i].name, tuple(selected))
            archived_frontiers[i] = selected

    # An in-flight backend phase is separate from the saved stage bests.
    # It can resume the last *completed backend round*, even if previous
    # stage passes were interrupted. Reject ambiguous incompatible snapshots.
    active_phase = None
    if resume_state is not None and not (summary_only or merge_only):
        try:
            wanted = {
                "version": 1,
                "level_sha256": hashlib.sha256(level.source_level_string.encode()).hexdigest(),
                "source_sha256": hashlib.sha256(encode_complex_replay(source).encode()).hexdigest(),
                "stages": [stage.name for stage in stages],
                "stage_settings": [repr(stage) for stage in stages],
                "config": repr(config),
                "from_best": from_best,
                "start_from_stage_bests": start_from_stage_bests,
                "reference_sha256": hashlib.sha256(encode_complex_replay(reference).encode()).hexdigest() if reference is not None else None,
                "merge_stage_bests": merge_stage_bests,
                "start_at": start_at, "stop_at": stop_at,
            }
            if any(resume_state.get(k) != value for k, value in wanted.items()):
                if progress:
                    progress("[auto:user-splice:resume] incompatible in-flight search "
                             "checkpoint skipped (configuration or source changed)")
            else:
                active_phase = resume_state
                if progress:
                    progress(f"[auto:user-splice:resume] restoring outer round "
                             f"{int(active_phase['round_no']) + 1}, splice "
                             f"{active_phase['stage']!r}, backend "
                             f"{active_phase['phase']['backend']} from last completed round")
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            active_phase = None
            if progress:
                progress(f"[auto:user-splice:resume] invalid in-flight checkpoint "
                         f"skipped: {exc}")

    # Summary-only mode reports on disk checkpoints without changing them.
    # There must be no baseline checkpoint writes or Auto/Local searches.
    # Choose only a previously saved, validated best for explicit propagation.
    # Do this before writing initial source checkpoints, so --splice-from-best
    # never silently falls back to an unsaved current-run baseline.
    def reported_savings(i: int, candidate: EndpointEvaluation,
                         frames: tuple[InputFrame, ...] | None = None) -> str:
        """Separate local *section* time from cumulative checkpoint progress.

        A fixed-frame spatial helper can improve its x/y without saving time.
        Nor can improvements in different axes be summed as pixel savings.
        """
        best_workspace = _materialise_splice_tail(best_output, len(current) - 1)
        best_eval = (original_endpoints[i].evaluate(best_workspace)
                     if best_rank is not None and stage_feasible(best_workspace, i)
                     else None)
        baseline = input_stage_evals[i]
        replay = frames if frames is not None else stage_checkpoints[i]
        if i == 0 and baseline is not None and stages[i].goal.is_earliest:
            individual = f"{baseline.frame - candidate.frame:+d} frames from start"
        elif replay is not None and i > 0:
            before = section_duration(i, reporting_input)
            after = section_duration(i, replay)
            if before is not None and after is not None:
                individual = (f"{before - after:+d} section frames "
                              f"({before} -> {after}; {stages[i-1].name} to {stages[i].name})")
            else:
                individual = ("section timing unavailable; "
                              "objective gain is shown vs input below")
        else:
            individual = ("objective gain is shown vs input below; "
                          "section timing unavailable")
        if baseline is None:
            cumulative = "unavailable (input did not meet this helper)"
        elif stages[i].goal.is_earliest:
            cumulative = f"{baseline.frame - candidate.frame:+d} frames at this checkpoint vs input"
        else:
            cumulative = ("not measurable as saved time (fixed-frame spatial goal); "
                          "see pixel comparison below")
        return ('; individual splice gain: ' + individual +
                '; cumulative gain through this splice: ' + cumulative +
                '; ' + _stage_savings_text(stages[i].goal, candidate,
                                            baseline, 'input run') +
                '; ' + _stage_savings_text(stages[i].goal, candidate,
                                            best_eval, 'best run'))

    # Preserve the exact CLI input as the first ordinary search seed for every
    # named stage.  A previously saved completed best is a score baseline and
    # useful alternative, but must not silently displace a manually edited run.
    input_seed = _materialise_splice_tail(source, len(current) - 1)
    propagation_seed = current
    if from_best_index is None and saved_final_frames is not None and best_output != source:
        # Use the previously verified best completed replay for normal search,
        # not only as a score threshold. Explicit --splice-from-best still wins.
        propagation_seed = _materialise_splice_tail(best_output, len(current) - 1)
    if from_best_index is not None:
        propagation_seed = stage_checkpoints[from_best_index]
        if propagation_seed is None:
            raise ValueError(f"no valid saved checkpoint for splice {from_best!r}; "
                             "a saved stage LTM/TXT must exist and satisfy "
                             "that splice's own goal")
        if progress:
            evaluation = stage_checkpoint_evals[from_best_index]
            progress(f"[auto:user-splice:from-best] {from_best!r}: "
                     f"starting at stage {stages[first_stage].name!r} from saved "
                     f"checkpoint; {_stage_improvement_text(stages[from_best_index].goal, None, evaluation)}")
    # Create the initial stage checkpoints as well as subsequent new bests.
    # Compare against validated on-disk checkpoints first: an existing better
    # movie must never be overwritten by a weaker starting replay.
    if not (summary_only or merge_only):
        for i, stage in enumerate(stages):
            baseline_evaluation = original_endpoints[i].evaluate(current) if stage_feasible(current, i) else None
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
                             f"{_stage_improvement_text(stage.goal, None, baseline_evaluation)}"
                             f"{reported_savings(i, baseline_evaluation)}")
    if progress and not (summary_only or merge_only):
        for i, replay in enumerate(restored_stage_frames):
            if replay is not None:
                progress(f"[auto:user-splice:resume] {stages[i].name!r}: "
                         "restored a strictly better historical checkpoint; "
                         f"{_stage_improvement_text(stages[i].goal, None, stage_best_evaluation[i])}"
                         f"{reported_savings(i, stage_best_evaluation[i])}")
    if progress and not (summary_only or merge_only):
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
                 "earlier named goals are non-binding helpers; "
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
            if best_rank is not None and stage_feasible(best_workspace, i):
                best_stage = original_endpoints[i].evaluate(best_workspace)
            detail = _stage_summary_text(stage.goal, candidate)
            elapsed = section_duration(i, archived)
            if elapsed is not None:
                detail += f"; from {stages[i-1].name}: {elapsed} section frames"
                timed = [span for item in archived_frontiers[i]
                         if (span := section_duration(i, item)) is not None]
                if timed:
                    detail += f"; fastest archived section {min(timed)} frames"
            if best_stage is None or candidate.objective_key < best_stage.objective_key:
                against = ("best run has no feasible checkpoint" if best_stage is None
                           else "full run: " + _stage_summary_text(stage.goal, best_stage))
                progress(f"[auto:user-splice:summary:pending] {stage.name!r}: "
                         f"pending ({stage_checkpoint_origin[i]}); "
                         f"splice: {detail}; {against}"
                         f"{reported_savings(i, candidate, archived)}")
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
                         f"{_stage_summary_text(stage.goal, best_stage)}"
                         f"{reported_savings(i, candidate, archived)}")

    report_checkpoint_summary("saved checkpoints" if summary_only else
                              "before merges" if merge_only else "startup")
    if summary_only:
        return UserSpliceResult(best_output, 0, 0, 0)

    # Elites are retained across rounds as well as across stage boundaries.
    # Their rank is the objective of the stage that produced them; earlier
    # helper objectives do not veto a different route at a later stage.
    elites: list[list[tuple[InputFrame, ...]]] = [list(pool[:config.frontier]) for pool in archived_frontiers]
    def run_saved_merge_pass(phase: str, *, repair: bool = False) -> None:
        """Try saved-stage joins *and* current-input-to-saved-route joins.

        A manual edit need not satisfy any named helper goal. The unchanged
        positional input is a real prefix candidate, even when it later dies;
        the verified completed output is a suffix candidate. All emitted
        movies must still pass the canonical replay/control verification gate.
        No Auto/Local mutation search runs here.
        """
        nonlocal best_rank, best_output, current, improvements
        pairs = attempted = joined = upgraded = completed = input_attempted = section_attempted = 0
        report = ("[auto:user-splice:repair-only]" if merge_repair_only else
                  "[auto:user-splice:merge-only]" if merge_only else
                  f"[auto:user-splice:merge:{phase}]")
        if progress:
            progress(f"{report} grafting saved stage routes and current input; "
                     f"all earlier stages eligible (normal search lookback "
                     f"remains {config.stage_lookback}); seam lookback "
                     f"{config.lookback} frame(s); "
                     "no Auto/Local bridge mutation search")

        # The CLI input is not automatically included in saved stage checkpoints
        # (especially in merge-only mode), so offer it separately as a prefix.
        # Cap the seam at the final live input tick: edits that die before a
        # later helper must still be considered at the last reachable seam.
        input_prefix = _materialise_splice_tail(source, len(current) - 1)
        last_live = (source_eval.dead_tick - 1 if source_eval.dead_tick is not None
                     else source_eval.finish_tick - 2 if source_eval.finish_tick is not None
                     else len(source) - 2)
        last_live = max(1, min(len(input_prefix) - 2, last_live))
        if progress and merge_only:
            if saved_final is None:
                comparison = "no saved completed-output replay was loaded"
            else:
                mismatch = next((tick for tick, (a, b) in enumerate(zip(source, saved_final))
                                 if a != b), None)
                if mismatch is None and len(source) != len(saved_final):
                    mismatch = min(len(source), len(saved_final))
                comparison = (f"differs from saved output starting at frame {mismatch}"
                              if mismatch is not None else "identical to saved output")
            progress(f"{report} current input: {len(source)} frames; "
                     f"{comparison}; last live candidate seam frame {last_live}")
        seen_requests: set[tuple[tuple[InputFrame, ...], tuple[InputFrame, ...],
                                 int, int | None]] = set()

        def merge_routes(index: int) -> list[tuple[str, tuple[InputFrame, ...]]]:
            """Keep a separate locally fast section when the stage best is slower.

            The endpoint winner and fastest *within-section* replay can differ:
            a later arrival at the previous helper can still yield a shorter
            subsequent interval. Frontier sidecars retain this independent
            candidate, but the fast merge used to ignore them completely.
            Include one archived alternative even when duration is unmeasurable
            (e.g. fixed-frame spatial goals), without claiming it is faster.
            """
            stage = stages[index]
            routes: list[tuple[str, tuple[InputFrame, ...]]] = []
            best = stage_checkpoints[index]
            if best is not None:
                routes.append((stage.name, best))
            others = [frames for frames in archived_frontiers[index]
                      if frames != best]
            timed = [(duration, original_endpoints[index].evaluate(frames).objective_key,
                      frames) for frames in others
                     if (duration := section_duration(index, frames)) is not None]
            if timed:
                # Different replays can have identical section durations and
                # endpoint scores. Compare only those sortable values: Python
                # cannot order InputFrame tuples when both scores tie. min()
                # is stable, preserving archive order as the tie-breaker.
                duration, _score, frames = min(timed, key=lambda row: (row[0], row[1]))
                routes.append((f"{stage.name} archived section ({duration} frames)", frames))
            elif others:
                routes.append((f"{stage.name} archived alternative", others[0]))
            return routes

        def first_input_difference(suffix: tuple[InputFrame, ...]) -> int | None:
            """Do not graft before the first manual edit and drop that edit."""
            first = next((i for i, (a, b) in enumerate(zip(source, suffix))
                          if a != b), None)
            if first is None and len(source) > len(suffix):
                return len(suffix)
            # A truncated but otherwise identical input has no changed input
            # frame to preserve. It is valid to graft the old tail onto it.
            return first

        def offer_candidate(candidate: tuple[InputFrame, ...],
                            later: int | None, label: str) -> tuple[bool, bool]:
            """Rank stage checkpoints and completions independently."""
            nonlocal best_rank, best_output, current, improvements, upgraded, completed
            padded = _materialise_splice_tail(candidate, len(current) - 1)
            stage_ok = later is not None and stage_feasible(padded, later)
            if stage_ok:
                score = original_endpoints[later].evaluate(padded)
                pool = {frames: original_endpoints[later].evaluate(frames).objective_key
                        for frames in archived_frontiers[later]}
                pool[padded] = score.objective_key
                selected = select_archive(later, pool)
                changed_archive = selected != archived_frontiers[later]
                archived_frontiers[later] = selected
                if (stage_checkpoint_evals[later] is None or
                        score.objective_key < stage_checkpoint_evals[later].objective_key):
                    stage_checkpoints[later] = padded
                    stage_checkpoint_evals[later] = score
                    stage_checkpoint_origin[later] = "verified merge"
                    upgraded += 1
                    if stage_best_callback:
                        stage_best_callback(stages[later].name, stage_export(padded))
                    if merge_only and progress:
                        progress(f"{report} {label}: new saved stage best; "
                                 f"{_stage_improvement_text(stages[later].goal, None, score)}"
                                 f"{reported_savings(later, score, padded)}")
                if frontier_callback and (not merge_only or changed_archive):
                    frontier_callback(stages[later].name,
                                      tuple(archived_frontiers[later]))
            # A completed improvement is never rejected by helper goals.
            complete = final_rank(padded)
            completion_ok = complete is not None
            if complete is not None and (best_rank is None or complete[0] < best_rank):
                best_rank, best_output = complete
                current = padded
                improvements += 1
                completed += 1
                if best_callback:
                    best_callback(best_output)
                if progress:
                    progress(f"[auto:user-splice:merge] {label}: improved verified "
                             f"completed replay at {len(best_output)} frames; saved")
            return stage_ok, completion_ok

        def try_join(prefix: tuple[InputFrame, ...],
                     suffix: tuple[InputFrame, ...], seam: int,
                     later: int | None, label: str,
                     *, require_suffix_completion: bool = False) -> None:
            nonlocal pairs, attempted, joined, input_attempted, section_attempted
            pairs += 1
            # Identity joins do not propagate the input or change the route.
            if prefix == suffix:
                if merge_only and progress and merge_verbose:
                    progress(f"{report} {label}: skipped (identical replays)")
                return
            key = (prefix, suffix, seam, later)
            if key in seen_requests:
                return
            seen_requests.add(key)
            attempted += 1
            manual_input = label.startswith("current input ->")
            if manual_input:
                input_attempted += 1
            if "archived section" in label or "archived alternative" in label:
                section_attempted += 1
            # When an edited input is grafted onto a historical suffix, the
            # seam must at least contain its first changed input frame.  A
            # seam *before* the edits merely reproduces the old run.
            changed_at = first_input_difference(suffix) if manual_input else None
            # A saved stage route can differ from the current input at frame 0
            # even when the *manual* edit was made hundreds of frames later.
            # Use the independently loaded completed output as another floor
            # for every current-input join, so an unrelated early stage route
            # cannot make us graft away the manual edit.
            if manual_input and saved_final is not None and saved_rank is not None:
                saved_difference = first_input_difference(saved_final)
                if saved_difference is not None:
                    changed_at = max(saved_difference, changed_at or 0)
            min_prefix_frame = 1 if changed_at is None else max(1, changed_at)
            physically_verified = 0
            accepted = False
            completed_join = False
            stage_join = False
            for graft in verified_suffix_grafts(
                    level, prefix, suffix, seam_frame=seam,
                    lookback=config.lookback,
                    completion_required=require_suffix_completion,
                    min_prefix_frame=min_prefix_frame):
                physically_verified += 1
                stage_ok, completion_ok = offer_candidate(graft, later, label)
                if stage_ok or completion_ok:
                    accepted = True
                    completed_join = completed_join or completion_ok
                    stage_join = stage_join or stage_ok
                    # Inspect all independently verified grafts (at most four),
                    # rather than stopping after the first valid but suboptimal
                    # seam. Completion and stage best have separate rankings.
            if accepted:
                joined += 1
                if merge_only and progress and merge_verbose:
                    result = ("completed join accepted despite missing destination helper"
                              if completed_join and later is not None and not stage_join else
                              "verified completed join" if completed_join else
                              "verified stage join")
                    progress(f"{report} {label}: {result} accepted")
            elif merge_only and progress and merge_verbose:
                reason = ("no physically compatible seam" if not physically_verified
                          else "no join satisfies its destination objective or completion")
                progress(f"{report} {label}: rejected ({reason})")

        # A manually edited positional replay is the first source, not a
        # fallback after all saved-splice pairings. First try to reconnect it
        # to the previous verified completion, independently of helper goals.
        if saved_final is not None and saved_rank is not None:
            for earlier, stage in enumerate(stages):
                try_join(input_prefix, saved_final,
                         min(last_live, stage.end), None,
                         f"current input -> saved completed run (seam {min(last_live, stage.end)})",
                         require_suffix_completion=True)
            try_join(input_prefix, saved_final, last_live, None,
                     f"current input -> saved completed run (last live seam {last_live})",
                     require_suffix_completion=True)

        # Give the positional input a chance against BOTH the endpoint winner
        # and the independently archived section candidate at every stage.
        # All pairs are independent; an unmergeable stage cannot block others.
        for later, stage in enumerate(stages):
            for suffix_name, suffix in merge_routes(later):
                tried_seams: set[int] = set()
                for earlier in range(later + 1):
                    seam = min(last_live, stages[earlier].end)
                    if seam in tried_seams:
                        continue
                    tried_seams.add(seam)
                    try_join(input_prefix, suffix, seam, later,
                             f"current input -> {suffix_name} (seam {seam})")
                if last_live not in tried_seams:
                    try_join(input_prefix, suffix, last_live, later,
                             f"current input -> {suffix_name} (last live seam {last_live})")

        # Saved stage checkpoints and one independent archived candidate per
        # stage are also viable prefixes. Try the saved completed suffix before
        # spending work on other intermediate goals; these are best-effort
        # joins and do not become mandatory constraints.
        if saved_final is not None and saved_rank is not None:
            for earlier, stage in enumerate(stages):
                for source_name, prefix in merge_routes(earlier):
                    try_join(prefix, saved_final, stage.end, None,
                             f"{source_name} -> saved completed run (seam {stage.end})",
                             require_suffix_completion=True)
        elif progress and merge_only:
            progress(f"{report} no verified saved completed replay for suffix grafting; "
                     "only saved stage suffixes were available")

        # Earlier-to-later stage propagation still runs. The archived candidate
        # is considered independently from each stage's absolute-frame winner,
        # in both prefix and suffix roles. A later-arriving fast section can
        # therefore survive, and a failed join at e.g. 564 does not prevent
        # another from connecting 522 directly to 614 or a completed suffix.
        for later in range(1, len(stages)):
            for earlier in range(later):
                prefixes = merge_routes(earlier)
                suffixes = merge_routes(later)
                if not prefixes or not suffixes:
                    pairs += 1
                    if merge_only and progress and merge_verbose:
                        missing = ("both checkpoints" if not prefixes and not suffixes else
                                   "source checkpoint" if not prefixes else "destination checkpoint")
                        progress(f"{report} {stages[earlier].name} -> {stages[later].name}: "
                                 f"skipped (missing {missing})")
                    continue
                for source_name, prefix in prefixes:
                    for suffix_name, suffix in suffixes:
                        try_join(prefix, suffix, stages[earlier].end, later,
                                 f"{source_name} -> {suffix_name}")

        if repair:
            run_bridge_repair_pass(report, offer_candidate)
        if progress:
            progress(f"{report} done: {pairs} pair(s) considered; "
                     f"{attempted} attempted; {joined} verified join(s); "
                     f"{upgraded} stage best(s) improved; "
                     f"{completed} completed best(s) improved; "
                     f"{pairs-attempted} skipped; {attempted-joined} rejected; "
                     f"{input_attempted} current-input graft attempt(s); "
                     f"{section_attempted} archived-alternative graft attempt(s)")

    def run_bridge_repair_pass(report: str, offer) -> None:
        """Repair independent saved-prefix routes without blocking on failures.

        Every prefix gets a first opportunity before any gets a second one.
        A stalled splice (for example 564) therefore cannot consume all work
        or prevent a later/earlier independent gain from being propagated.
        """
        nonlocal evaluations, attempts
        # A verified in-memory best is a *score threshold*, not necessarily the
        # continuation to which the user wants to connect a manual edit.  In
        # particular a better completed positional input becomes best_output,
        # but the *older saved final* can still supply the missing suffix.
        # Keep both independent completions, preferring the persisted suffix.
        completions: list[tuple[str, tuple[InputFrame, ...]]] = []
        for name, candidate in (("saved completed", saved_final),
                                ("current best completed", best_output if best_rank is not None else None)):
            if candidate is None:
                continue
            checked = evaluate_replay_with_sentinel(level, candidate)
            if (checked.valid and checked.finish_tick == len(candidate) and
                    all(candidate != frames for _, frames in completions)):
                completions.append((name, tuple(candidate)))
        if not completions and progress:
            progress(f"{report} bridge repair: no verified completed suffix; "
                     "trying only intermediate saved splices")
        # Source provenance is fixed for the whole pass.  Do not replace the
        # positional input with best_output or suppress it merely because the
        # input currently holds the best completion time.
        comparison = next((frames for _, frames in completions if frames != source), None)
        first_difference = None
        if comparison is not None:
            first_difference = next((tick for tick, (left, right) in
                                     enumerate(zip(source, comparison))
                                     if left != right), None)
            if first_difference is None and len(source) != len(comparison):
                first_difference = min(len(source), len(comparison))
        manual_repair_seam = (min(len(source)-2, first_difference + merge_repair_window)
                              if first_difference is not None else len(source)-2)
        manual_repair_seam = max(2, manual_repair_seam)
        if progress:
            names = ", ".join(f"{label} ({len(frames)} frames)" for label, frames in completions)
            progress(f"{report} bridge sources: positional current input "
                     f"({len(source)} frames) is first; verified continuations: "
                     f"{names or 'none'}; manual seam {manual_repair_seam}")
        sources: list[tuple[str, tuple[InputFrame, ...], int | None]] = [
            ("current input", input_prefix_for_repair, None)]
        for index, stage in enumerate(stages):
            prefix = stage_checkpoints[index]
            if prefix is None:
                continue
            # A completed best may exceed a saved stage's *overall objective*
            # while that stage has a useful, faster local section.  The local
            # candidate is considered separately below, regardless of this.
            covered = False
            completed_best = next((frames for name, frames in completions
                                   if name == "current best completed"), None)
            if completed_best is not None:
                # A verified completion can end before a later helper's target
                # frame (e.g. finish at 788, final helper target at 811).
                # EndpointEvaluator needs the implicit neutral search tail,
                # but the saved completed replay itself must stay trimmed.
                completed_workspace = _materialise_splice_tail(
                    completed_best, stage.goal.target_frame)
                if stage_feasible(completed_workspace, index):
                    full_eval = original_endpoints[index].evaluate(completed_workspace)
                    score = stage_checkpoint_evals[index]
                    covered = (score is not None and
                               score.objective_key >= full_eval.objective_key)
            if not covered and prefix != input_prefix_for_repair:
                sources.append((stage.name, prefix, index))
        primary_count = len(sources)
        # The saved archive has an independent fastest-section slot (when a
        # physical duration is measurable).  A locally faster replay may have
        # a *later absolute arrival* and a worse endpoint objective; it still
        # deserves an independent repair attempt.  Do not require it to beat
        # the current completed run or the saved stage best.
        primary_frames = {(frames, index) for _, frames, index in sources}
        for index, stage in enumerate(stages):
            candidates = sorted(archived_frontiers[index], key=lambda item, at=index: (
                (span if (span := section_duration(at, item)) is not None
                 else float('inf')),
                original_endpoints[at].evaluate(item).objective_key))
            for item in candidates:
                if (item, index) in primary_frames or item == input_prefix_for_repair:
                    continue
                duration = section_duration(index, item)
                label = (f"{stage.name} archived section ({duration} local frames)"
                         if duration is not None else
                         f"{stage.name} archived alternative (section time unknown)")
                sources.append((label, item, index))
                break

        # Independent source/continuation pairings: use persisted final first,
        # even if the positional input is already the in-memory best.  A
        # completed suffix identical to a source is skipped, but other suffixes
        # remain eligible.  The full verification gate still ranks completions.
        tasks = []
        for label, prefix, index in sources:
            suffixes = [(name, candidate, None, True)
                        for name, candidate in completions if candidate != prefix]
            if index is not None:
                for later in range(index + 1, len(stages)):
                    later_prefix = stage_checkpoints[later]
                    if later_prefix is not None and later_prefix != prefix:
                        suffixes.append((stages[later].name, later_prefix, later, False))
            else:
                for later in range(len(stages)):
                    later_prefix = stage_checkpoints[later]
                    if later_prefix is not None and later_prefix != prefix:
                        suffixes.append((stages[later].name, later_prefix, later, False))
            tasks.append((label, prefix, index, suffixes))
        attempts_used = successes = search_calls = repair_evals = 0
        attempted_labels: set[str] = set()
        seen_pairs: set[tuple[tuple[InputFrame, ...], tuple[InputFrame, ...]]] = set()
        primary_tasks, section_tasks = tasks[:primary_count], tasks[primary_count:]
        # One pass over *every distinct source*, including locally fast saved
        # sections, before giving any source a second destination.  Previously
        # three attempts per primary source could exhaust all 48 default pairs
        # before even the first archived section got a chance.
        plan = []
        if primary_tasks:
            plan.append((primary_tasks[0], 0))  # positional input always first
        for i in range(max(len(primary_tasks) - 1, len(section_tasks))):
            if i + 1 < len(primary_tasks):
                plan.append((primary_tasks[i + 1], 0))
            if i < len(section_tasks):
                plan.append((section_tasks[i], 0))
        # Once every source has had a chance, give *early* gains two more
        # independent destinations before moving on.  The first continuation
        # after 522 can be unmergeable (564), while the next (614) is useful;
        # neither failure should wait behind dozens of unrelated late splices.
        for item in primary_tasks:
            plan.extend((item, turn) for turn in (1, 2) if turn < len(item[3]))
        for item in section_tasks:
            plan.extend((item, turn) for turn in (1, 2) if turn < len(item[3]))
        max_turn = max((len(item[3]) for item in tasks), default=0)
        for turn in range(3, max_turn):
            for i in range(max(len(primary_tasks), len(section_tasks))):
                if i < len(primary_tasks):
                    plan.append((primary_tasks[i], turn))
                if i < len(section_tasks):
                    plan.append((section_tasks[i], turn))
        for (label, prefix, index, suffixes), turn in plan:
            if attempts_used >= merge_repair_pairs:
                break
            if turn >= len(suffixes):
                continue
            target_name, suffix, later, needs_completion = suffixes[turn]
            if (prefix, suffix) in seen_pairs:
                continue
            seen_pairs.add((prefix, suffix))
            attempts_used += 1
            attempted_labels.add(label)
            seam = (stages[index].end if index is not None else
                    min(len(prefix) - 2, max(manual_repair_seam,
                        stages[later].end if later is not None else manual_repair_seam)))
            if progress and merge_verbose:
                progress(f"{report} bridge {attempts_used}/{merge_repair_pairs}: "
                         f"{label} -> {target_name}; seam {seam}; "
                         f"window {merge_repair_window}, targets {merge_repair_targets}, "
                         f"{config.workers} worker(s) x {config.repair_iterations} "
                         "proposals per target")
            try:
                result = repair_suffix_grafts(
                    level, prefix, suffix, seam_frame=seam, config=config,
                    window=merge_repair_window, targets=merge_repair_targets,
                    completion_required=needs_completion,
                    seed=rng.getrandbits(63))
            except KeyboardInterrupt:
                if progress:
                    progress(f"{report} bridge interrupted; verified results saved "
                             "before interruption are retained")
                raise
            except (ValueError, RuntimeError) as exc:
                # A corrupt or unrepairable saved section may fail the native
                # search preflight. Treat that *pair* as unsuccessful, without
                # preventing the 522 -> 614 path after 522 -> 564 fails.
                if progress and merge_verbose:
                    progress(f"{report} bridge {label} -> {target_name}: "
                             f"failed ({type(exc).__name__}: {exc}); "
                             "continuing with independent repair pairs")
                continue
            search_calls += result.searches
            repair_evals += result.evaluations
            found = False
            for repaired in result.grafts:
                stage_ok, completed_ok = offer(repaired, later, f"repair {label} -> {target_name}")
                found = stage_ok or completed_ok or found
            if found:
                successes += 1
            if progress and merge_verbose:
                progress(f"{report} bridge {label} -> {target_name}: "
                         f"{'verified graft accepted' if found else 'no verified graft'}; "
                         f"{result.searches} backend search(es), "
                         f"{result.evaluations} evaluations")
        evaluations += repair_evals
        attempts += search_calls
        if progress:
            progress(f"{report} bridge repair done: {attempts_used} independent "
                     f"pair(s) attempted; {successes} accepted; "
                     f"{attempts_used-successes} unsuccessful; "
                     f"{search_calls} backend search(es), {repair_evals} evaluations; "
                     f"positional input {'attempted' if 'current input' in attempted_labels else 'not attempted'}, "
                     f"archived sections {sum(item[0] in attempted_labels for item in section_tasks)}"
                     f"/{len(section_tasks)} attempted; "
                     "failed pairs do not stop other attempts")

    # The input must remain a separate repair source even when saved final
    # state is used for other search or reporting paths.
    input_prefix_for_repair = _materialise_splice_tail(source, len(current) - 1)

    if merge_stage_bests:
        run_saved_merge_pass("startup", repair=merge_repair_only)
        if merge_only:
            report_checkpoint_summary("after merges")
            return UserSpliceResult(best_output, improvements, attempts, evaluations)

    if type(resume_outer_round) is not int or resume_outer_round < 0:
        raise ValueError("invalid saved outer-round progress")
    first_round = (int(active_phase["round_no"]) if active_phase is not None
                   else resume_outer_round)
    for round_no in (itertools.count(first_round) if config.rounds == 0
                     else range(first_round, config.rounds)):
        begun = time.monotonic()
        selected = (config.splice_round_speeds[min(round_no, len(config.splice_round_speeds)-1)]
                    if config.splice_round_speeds else config.splice_speed)
        if progress and selected:
            progress(f"[auto:user-splice] round {round_no+1}: speed={selected} "
                     "(independent Auto/Local stagnation limits)")
        # A propagation run deliberately retries the archived splice-best
        # path on every outer round, rather than restarting only from the best
        # fully completed run. Completed replay verification remains strict,
        # but preceding helper objectives do not constrain later stages.
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
            stage_config = splice_config_for_round(replace(config, **stage.config_overrides), round_no)
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
            if from_best_index is None:
                # Selection quotas stay unchanged, but search the best seed
                # from each prior stage before lower-ranked alternatives from
                # that same stage: n-1 rank 1, n-2 rank 1, ..., n-1 rank 2.
                # A replay in multiple pools takes its best (rank, recency).
                priorities: dict[tuple[InputFrame, ...], tuple[int, int]] = {}
                for depth, pool in enumerate(history):
                    for rank, candidate in enumerate(pool):
                        key = (rank, depth)
                        if candidate not in priorities or key < priorities[candidate]:
                            priorities[candidate] = key
                branches.sort(key=lambda candidate: priorities[candidate])
            if start_from_stage_bests and stage_checkpoints[index] is not None:
                # Retry the best of *this* splice as another starting point,
                # even when it never propagated to the previous stage frontier.
                local_best = _materialise_splice_tail(
                    stage_checkpoints[index], len(current) - 1)
                branches = [local_best, *(b for b in branches if b != local_best)]
            if from_best_index is None:
                # Always try manual edits from the input replay first, then
                # the existing n-1/n-2/older frontier order.  Deduplicate so
                # a frontier containing the input does not consume two searches.
                # Explicit --splice-from-best retains its selected seed order.
                branches = [input_seed, *(b for b in branches if b != input_seed)]
            if active_phase is not None and index == stage_begin:
                # Never search another route before recovering the interrupted
                # backend. The other viable routes remain archived separately.
                resumed_branch = tuple(editable_frames(decode_complex_replay(
                    active_phase["branch"]).frames))
                branches = [resumed_branch, *(b for b in branches if b != resumed_branch)]
            # A current input, a saved final replay and a frontier candidate
            # can be distinct files but identical searches after stage.start.
            # Keep their first-ranked origin and avoid repeated millions of
            # backend proposals on the same physical start and input suffix.
            before_dedup = len(branches)
            branches = _unique_search_seeds(stage_levels[index], branches, stage.start)
            if progress and before_dedup != len(branches):
                progress(f"[auto:user-splice] {stage.name!r}: skipped "
                         f"{before_dedup - len(branches)} physically duplicate seed(s)")
            if progress and len(history) > 1:
                labels = "/".join(f"n-{i}" for i in range(1, len(history) + 1))
                counts = "/".join(str(len(pool)) for pool in history)
                order = ("current input, then " if from_best_index is None else "")
                if active_phase is not None and index == stage_begin:
                    order = "resumed backend, then " + order
                progress(f"[auto:user-splice] {stage.name!r}: "
                         f"{len(branches)} seed(s): {order}{labels} frontiers "
                         f"({counts} available; lookback {config.stage_lookback})")
            # Previously discovered stage elites are valid candidates without
            # spending more simulation proposals to rediscover them.
            eligible: dict[tuple[InputFrame, ...], tuple] = {}
            for saved in elites[index]:
                if stage_feasible(saved, index):
                    eligible[saved] = original_endpoints[index].evaluate(saved).objective_key
            for seed_index, branch in enumerate(branches, 1):
                # Sources are ranked *within* their own checkpoint objective,
                # not by the score of the stage we are about to search.
                source_detail = "input/best completed replay"
                if active_phase is not None and index == stage_begin and seed_index == 1:
                    source_detail = "resumed interrupted backend seed"
                elif from_best_index is None and branch == input_seed:
                    source_detail = "current input run"
                elif (start_from_stage_bests and stage_checkpoints[index] is not None and
                      branch == _materialise_splice_tail(stage_checkpoints[index], len(current)-1)):
                    source_detail = f"start from splice {stage.name} (saved stage best)"
                else:
                    origins = [(pool.index(branch), depth, origin)
                               for depth, (pool, origin) in enumerate(
                                   zip(history, history_origins)) if branch in pool]
                    if origins:
                        rank, _depth, origin = min(origins)
                        if origin is not None:
                            source_detail = (f"start from splice {stages[origin].name} "
                                             f"(n-{index-origin}, source rank {rank+1})")
                        elif from_best_index is not None:
                            source_detail = f"start from splice {stages[from_best_index].name}"
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
                    # editable_frames drops them again. Check this stage alone.
                    normalized = tuple(editable_frames(candidate))
                    if normalized in eligible:
                        # Duplicate live notifications and returned winners are
                        # common; their verified stage score cannot change.
                        return
                    evaluation = original_endpoints[index].evaluate(normalized)
                    # A faster canonical completion is valid even if this
                    # *helper* goal is infeasible. Such a route must never be
                    # discarded before independently checking the finish.
                    candidate_final = (
                        final_rank(normalized)
                        if require_complete or
                        (evaluation.feasible and index == len(stages) - 1)
                        else None
                    )
                    is_final_gain = (candidate_final is not None
                                     and (best_rank is None
                                          or candidate_final[0] < best_rank))
                    if not evaluation.feasible:
                        if not is_final_gain:
                            return
                    else:
                        # Earlier goals may be bypassed. Only the current
                        # goal selects stage improvements and backend leaders.
                        rank = evaluation.objective_key
                        eligible[normalized] = rank
                        # Frontier archives are persistence, not the active
                        # population. Flush them at stage boundaries.
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
                                         f"{_stage_improvement_text(stage.goal, old_evaluation, evaluation)}"
                                         f"{reported_savings(index, evaluation, normalized)}")
                    if is_final_gain:
                        candidate_rank, completed_frames = candidate_final
                        # Compare final best vs final best. old_evaluation
                        # belongs to the *stage checkpoint*, which may be a
                        # different, incomplete route with a better x/frame.
                        previous_best_rank = best_rank
                        previous_best_output = best_output
                        previous_final = (
                            original_endpoints[index].evaluate(
                                _materialise_splice_tail(previous_best_output, len(current)-1))
                            if previous_best_rank is not None else None)
                        previous_savings = (_stage_savings_text(
                            stage.goal, evaluation, previous_final, "previous best run")
                            if progress else "")
                        current = normalized
                        best_output = completed_frames
                        best_rank = candidate_rank
                        improvements += 1
                        improved = True
                        if best_callback:
                            best_callback(best_output)
                        if progress:
                            completed_text = (
                                f"verified completed frames {len(previous_best_output)} "
                                f"-> {len(best_output)}"
                                if previous_best_rank is not None else
                                f"first eligible verified completion at frame {len(best_output)}")
                            progress(f"[auto:user-splice] improved verified final replay "
                                     f"({stage.name}); {completed_text}; "
                                     f"{'final-goal' if index == len(stages)-1 else 'stage-goal'} comparison (informational): "
                                     f"{_stage_improvement_text(stage.goal, previous_final, evaluation)}; "
                                     f"{_stage_savings_text(stage.goal, evaluation, input_stage_evals[index], 'input run')}; "
                                     f"{previous_savings}; saved")

                last_live_accept = float("-inf")
                def live_candidate(candidate: tuple[InputFrame, ...], frame: int) -> None:
                    nonlocal last_live_accept
                    now = time.monotonic()
                    if not stage_config.live_save_best and stage_config.workers > 1 and now - last_live_accept < 30.0:
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
                                "start_from_stage_bests": start_from_stage_bests,
                                "reference_sha256": hashlib.sha256(encode_complex_replay(reference).encode()).hexdigest() if reference is not None else None,
                                "merge_stage_bests": merge_stage_bests,
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
                    def admissible_rank(candidate, at=index):
                        # The Auto/Local leader must use the same acceptance
                        # rule as standalone Auto: this named goal only.
                        evaluation = original_endpoints[at].evaluate(candidate)
                        return evaluation.objective_key if evaluation.feasible else None
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
                         f"{reported_savings(index, stage_best_evaluation[index], restored_stage_frames[index]) if stage_best_evaluation[index] is not None else 'no feasible stage checkpoint'}; "
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
                             f"{stage.name!r}: no candidate met its own goal; "
                             f"continuing with {len(fallbacks)} fallback seed(s) "
                             "(completed replay verification remains strict)")
                history = [fallbacks, *history][:config.stage_lookback]
                history_origins = [index, *history_origins][:config.stage_lookback]
                continue
            ordered = sorted(eligible.items(), key=lambda item: item[1])
            # Keep distinct earlier-stage frontiers independent of whether a
            # more recent stage wins its own intermediate ranking.
            selected = [candidate for candidate, _ in ordered[:max(1, config.frontier)]]
            elites[index] = selected
            publish_frontier(index, [candidate for candidate, _ in ordered])
            history = [selected, *history][:config.stage_lookback]
            history_origins = [index, *history_origins][:config.stage_lookback]
            if reference is not None and selected:
                # Use the best eligible checkpoint at this stage as a prefix;
                # the reference supplies a known completed route suffix.
                accept_merged_completion(selected[0], stage.end, stage.name)
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
    if merge_stage_bests:
        # Saved stage checkpoints may have changed during the last search
        # round; an entry-time merge cannot propagate those new results.
        run_saved_merge_pass("final", repair=merge_repair_at_end)
    report_checkpoint_summary("final")
    return UserSpliceResult(best_output, improvements, attempts, evaluations)

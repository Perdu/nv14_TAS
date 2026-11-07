"""Shared endpoint splicer backend used by named and sampled waypoints.

Selection of stages is kept in the respective frontend. Local/Auto backend
sequencing, continuous stagnation, and live candidates are implemented once.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Callable, Mapping
import random
import time

from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_engine import InputFrame, Level
from nv14_random_splice import RandomSpliceConfig, _local_search as _default_local_search
from nv14_replay import editable_frames, encode_complex_replay, decode_complex_replay


SPLICE_SPEEDS = {"fast": (3, 10), "normal": (5, 20), "slow": (10, 50)}
HYBRID_STAGNATION_SPEEDS = {"fast": 3, "normal": 5, "slow": 10}


def splice_config_for_round(config: RandomSpliceConfig, round_no: int) -> RandomSpliceConfig:
    """Apply a speed preset without changing the selected search backend.

    Hybrid uses ``splice_speed`` as cycle patience; its legacy ``round-speeds``
    schedule is ignored. For other modes, scheduled ``current`` preserves
    explicit patience, and exhausted schedules repeat their last speed.
    """
    if config.search_backend in ("hybrid", "hybrid-restart", "hybrid-local-control"):
        # The speed preset controls cycle-level patience, not the Auto/Local
        # phase-specific limits. Per-outer-round speed schedules remain legacy
        # settings and intentionally do not affect hybrid.
        if config.splice_speed is None:
            return config
        return replace(config, hybrid_stagnation_cycles=
                       HYBRID_STAGNATION_SPEEDS[config.splice_speed])
    sequence = config.splice_round_speeds
    speed = sequence[min(round_no, len(sequence) - 1)] if sequence else config.splice_speed
    if speed is None or speed == "current":
        return config
    auto, local = SPLICE_SPEEDS[speed]
    return replace(config, splice_stagnation_rounds=0,
                   splice_auto_stagnation_rounds=(auto if config.search_backend in ("both", "endpoint-auto") else 0),
                   splice_local_stagnation_rounds=(local if config.search_backend in ("both", "local") else 0))


@dataclass(frozen=True, slots=True)
class SpliceSearchStage:
    name: str
    goal: EndpointGoal
    start: int
    end: int


def _search_stage(level: Level, branch: tuple[InputFrame, ...],
                  stage: SpliceSearchStage, config: RandomSpliceConfig,
                  rng: random.Random,
                  *, stage_rank: Callable[[tuple[InputFrame, ...]], tuple | None] | None = None,
                  progress: Callable[[str], None] | None = None,
                  candidate_callback: Callable[[tuple[InputFrame, ...], int], None] | None = None,
                  resume_phase: Mapping[str, object] | None = None,
                  phase_started: Callable[[dict[str, object]], None] | None = None,
                  backend_checkpoint_path: Callable[[str], str] | None = None,
                  local_search: Callable | None = None,
                  evaluator_factory: Callable | None = None,
                  ) -> tuple[tuple[tuple[tuple[InputFrame, ...], int], ...], int, int]:
    """Run the requested backends with one shared per-branch proposal budget.

    With ``both``, endpoint Auto runs first. Local then starts from the
    best Auto candidate (or the original stage seed when Auto did not improve
    on it). Both backends retain their own share of the iteration budget,
    and their candidates are merged for the next named stage.
    The odd proposal goes to Local, so the combined backend budget remains
    exactly config.iterations per worker and internal round.
    """
    if config.search_backend in ("hybrid", "hybrid-restart", "hybrid-local-control"):
        if resume_phase is not None:
            raise ValueError("hybrid does not support resuming a partially finished stage")
        return _search_stage_hybrid(
            level, branch, stage, config, rng, stage_rank=stage_rank,
            progress=progress, candidate_callback=candidate_callback,
            local_search=local_search, evaluator_factory=evaluator_factory)
    if (config.splice_auto_stagnation_rounds or config.splice_local_stagnation_rounds):
        return _search_stage_backend_phases(
            level, branch, stage, config, rng, stage_rank=stage_rank,
            progress=progress, candidate_callback=candidate_callback,
            resume_phase=resume_phase, phase_started=phase_started,
            backend_checkpoint_path=backend_checkpoint_path,
            local_search=local_search, evaluator_factory=evaluator_factory)
    if config.splice_stagnation_rounds:
        return _search_stage_until_stagnant(
            level, branch, stage, config, rng, stage_rank=stage_rank,
            progress=progress, candidate_callback=candidate_callback,
            local_search=local_search, evaluator_factory=evaluator_factory)
    if config.search_backend == "both":
        if config.iterations < 2:
            raise ValueError("splice-search=both requires splice-iterations >= 2")
        modes = (("endpoint-auto", config.iterations // 2),
                 ("local", (config.iterations + 1) // 2))
    else:
        modes = ((config.search_backend, config.iterations),)
    local_search = _default_local_search if local_search is None else local_search
    evaluator_factory = EndpointEvaluator if evaluator_factory is None else evaluator_factory
    merged: dict[tuple[InputFrame, ...], int] = {}
    evaluations = 0
    searches = 0
    search_seed = branch
    for backend, iterations in modes:
        try:
            found, used = local_search(
                level, search_seed, stage.goal, start=stage.start,
                editable_end=stage.end,
                config=replace(config, search_backend=backend),
                iterations=iterations, rounds=config.splice_rounds,
                seed=rng.getrandbits(63), include_partial=True,
                live_update_interval=(0.0 if config.live_save_best else
                                      30.0 if config.workers > 1 else 0.75),
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
            evaluator = evaluator_factory(level, stage.goal)
            auto_seeds = list(dict.fromkeys(tuple(candidate) for candidate, _ in found))
            auto_seeds.append(branch)
            search_seed = min(auto_seeds,
                              key=lambda frames: evaluator.evaluate(frames).progress_key)
    return tuple(merged.items()), evaluations, searches



def _search_stage_hybrid(
    level: Level, branch: tuple[InputFrame, ...], stage: SpliceSearchStage,
    config: RandomSpliceConfig, rng: random.Random,
    *, stage_rank: Callable[[tuple[InputFrame, ...]], tuple | None] | None = None,
    progress: Callable[[str], None] | None = None,
    candidate_callback: Callable[[tuple[InputFrame, ...], int], None] | None = None,
    local_search: Callable | None = None,
    evaluator_factory: Callable | None = None,
) -> tuple[tuple[tuple[tuple[InputFrame, ...], int], ...], int, int]:
    """Alternate Auto(1) and Local(N), sharing a bounded *replay* population.

    Hybrid retains feasible elites and diverse live near-misses across backend
    switches. Each backend rebuilds its own native search/evaluation state from
    these candidate replays, which avoids transferring stale native handles.
    ``hybrid-restart`` retains patch 75's Auto/Local restart-only schedule.
    ``hybrid-local-control`` substitutes Local for Auto, also restarting.
    Both controls carry only the incumbent between invocations.
    """
    evaluator_factory = EndpointEvaluator if evaluator_factory is None else evaluator_factory
    evaluator = evaluator_factory(level, stage.goal)
    local_search = _default_local_search if local_search is None else local_search

    def rank(frames: tuple[InputFrame, ...]) -> tuple | None:
        if stage_rank is not None:
            return stage_rank(frames)
        state = evaluator.evaluate(frames)
        return state.objective_key if state.feasible else None

    merged: dict[tuple[InputFrame, ...], int] = {}
    incumbent = search_seed = tuple(branch)
    best_rank = rank(incumbent)
    best_progress = evaluator.evaluate(incumbent).progress_key
    # The cross-backend pool is intentionally distinct from the stage frontier
    # (which is emitted for subsequent goals). Store *replays*, not native
    # state or backend-specific score objects. Each receiver independently
    # re-evaluates/re-packs its donors. Bound by beam and keep progress niches.
    persistent = config.search_backend == "hybrid"
    shared: dict[tuple[InputFrame, ...], object] = {}
    stage_reference = tuple(branch)
    end = min(stage.end, len(stage_reference) - 1)

    def admit(frames: tuple[InputFrame, ...]) -> None:
        frames = tuple(frames)
        if (frames in shared or len(frames) != len(stage_reference)
                or frames[:stage.start] != stage_reference[:stage.start]
                or frames[end + 1:] != stage_reference[end + 1:]):
            return
        # If a caller supplies a broader admissibility rule, never seed an
        # unrelated earlier-stage failure into the next search phase.
        if stage_rank is not None and rank(frames) is None:
            return
        evaluation = evaluator.evaluate(frames)
        if not getattr(evaluation, "dead", False):
            shared[frames] = evaluation

    def select_shared() -> None:
        if len(shared) <= config.beam:
            return
        def order(item):
            frames, evaluation = item
            feasible = evaluation.feasible
            return (0 if feasible else 1,
                    evaluation.objective_key if feasible else evaluation.progress_key,
                    repr(frames))

        ranked = sorted(shared.items(), key=order)
        feasible = [(f, e) for f, e in ranked if e.feasible]
        partial = [(f, e) for f, e in ranked if not e.feasible]
        reserve = (min(len(partial), max(1, config.beam // 4), config.beam - 1)
                   if feasible else config.beam)
        selected: list[tuple[tuple[InputFrame, ...], object]] = []
        seen: set[tuple[InputFrame, ...]] = set()

        def add_group(group, slots):
            niches = set()
            start_index = len(selected)
            for frames, evaluation in group[:max(1, slots // 4) if slots else 0]:
                selected.append((frames, evaluation))
                seen.add(frames)
                niches.add(getattr(evaluation, "niche_key", frames))
            for frames, evaluation in group:
                if len(selected) - start_index >= slots:
                    break
                niche = getattr(evaluation, "niche_key", frames)
                if frames not in seen and niche not in niches:
                    selected.append((frames, evaluation))
                    seen.add(frames)
                    niches.add(niche)
            for frames, evaluation in group:
                if len(selected) - start_index >= slots:
                    break
                if frames not in seen:
                    selected.append((frames, evaluation))
                    seen.add(frames)

        add_group(feasible, config.beam - reserve if feasible else 0)
        add_group(partial, reserve)
        for frames, evaluation in ranked:
            if len(selected) >= config.beam:
                break
            if frames not in seen:
                selected.append((frames, evaluation))
                seen.add(frames)
        shared.clear()
        shared.update(selected)

    if persistent:
        admit(stage_reference)
    evaluations = calls = stagnant = 0
    first_backend = ("endpoint-auto" if config.search_backend in ("hybrid", "hybrid-restart")
                     else "local")
    for cycle in range(1, config.hybrid_cycles + 1):
        cycle_improved = False
        for backend, rounds in ((first_backend, 1), ("local", config.hybrid_local_rounds)):
            turn_seed = rng.getrandbits(63)
            phase_population: list[tuple[InputFrame, ...]] = []
            def collect_population(donors: tuple[tuple[InputFrame, ...], ...]) -> None:
                phase_population.extend(tuple(frames) for frames in donors)
            try:
                found, used = local_search(
                    level, search_seed, stage.goal, start=stage.start,
                    editable_end=stage.end,
                    # Hybrid owns these limits. Strip dormant settings before
                    # constructing a standalone backend config, so they do not
                    # trigger incompatible phase validation or affect its run.
                    config=replace(
                        config, search_backend=backend, splice_rounds=1,
                        splice_stagnation_rounds=0,
                        splice_auto_stagnation_rounds=0,
                        splice_local_stagnation_rounds=0,
                        splice_speed=None, splice_round_speeds=()),
                    iterations=config.iterations, rounds=rounds,
                    seed=turn_seed, include_partial=True,
                    live_update_interval=(0.0 if config.live_save_best else
                                          30.0 if config.workers > 1 else 0.75),
                    **({"initial_population": tuple(shared),
                        "population_callback": collect_population} if persistent else {}),
                    **({"best_callback": candidate_callback} if candidate_callback else {}),
                )
            except ValueError as exc:
                if not str(exc).startswith("the immutable prefix dies before the editable ranges"):
                    raise
                found, used = (), 0
            calls += 1
            evaluations += used
            best_partial = search_seed
            best_partial_progress = best_progress
            phase_improved = False
            for candidate, frame in found:
                candidate = tuple(candidate)
                merged.setdefault(candidate, frame)
                candidate_rank = rank(candidate)
                if candidate_rank is not None and (best_rank is None or candidate_rank < best_rank):
                    incumbent, best_rank = candidate, candidate_rank
                    phase_improved = cycle_improved = True
                candidate_progress = evaluator.evaluate(candidate).progress_key
                if candidate_progress < best_partial_progress:
                    best_partial, best_partial_progress = candidate, candidate_progress
            if best_rank is not None:
                # Never regress a feasible result or break an earlier stage goal.
                search_seed = incumbent
                best_progress = evaluator.evaluate(incumbent).progress_key
            else:
                search_seed, best_progress = best_partial, best_partial_progress
            if persistent:
                # Keep donors even if they were not in the published result
                # frontier; that list intentionally discards many niches.
                for candidate in (*phase_population, *(f for f, _ in found),
                                  search_seed, incumbent):
                    admit(tuple(candidate))
                select_shared()
            if progress:
                progress(f"[auto:user-splice:hybrid] {stage.name!r} cycle {cycle}/"
                         f"{config.hybrid_cycles}: {backend} {rounds} round(s), "
                         f"seed {turn_seed}, {used} evaluations, "
                         f"{'stage improved' if phase_improved else 'no eligible stage gain'}; "
                         f"best eligible objective key {best_rank!r}"
                         + (f"; retained {len(shared)} cross-backend candidates"
                            if persistent else "; restart-only control"))
        stagnant = 0 if cycle_improved else stagnant + 1
        if progress:
            progress(f"[auto:user-splice:hybrid] {stage.name!r} cycle {cycle} complete; "
                     f"stagnant {stagnant}; calls {calls}, evaluations {evaluations}")
        if config.hybrid_stagnation_cycles and stagnant >= config.hybrid_stagnation_cycles:
            break
    return tuple(merged.items()), evaluations, calls


def _search_stage_backend_phases(
    level: Level, branch: tuple[InputFrame, ...], stage: SpliceSearchStage,
    config: RandomSpliceConfig, rng: random.Random,
    *, stage_rank: Callable[[tuple[InputFrame, ...]], tuple | None] | None = None,
    progress: Callable[[str], None] | None = None,
    candidate_callback: Callable[[tuple[InputFrame, ...], int], None] | None = None,
    resume_phase: Mapping[str, object] | None = None,
    phase_started: Callable[[dict[str, object]], None] | None = None,
    backend_checkpoint_path: Callable[[str], str] | None = None,
                  local_search: Callable | None = None,
                  evaluator_factory: Callable | None = None,
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

    evaluator_factory = EndpointEvaluator if evaluator_factory is None else evaluator_factory
    evaluator = evaluator_factory(level, stage.goal)

    def rank(frames: tuple[InputFrame, ...]) -> tuple | None:
        if stage_rank is not None:
            return stage_rank(frames)
        evaluation = evaluator.evaluate(frames)
        return evaluation.objective_key if evaluation.feasible else None

    local_search = _default_local_search if local_search is None else local_search
    evaluator_factory = EndpointEvaluator if evaluator_factory is None else evaluator_factory
    merged: dict[tuple[InputFrame, ...], int] = {}
    incumbent = search_seed = tuple(branch)
    best_rank = rank(incumbent)
    best_progress = evaluator.evaluate(incumbent).progress_key
    evaluations = calls = 0
    # A continuous phase has already searched to its *own* stagnation limit.
    # Repeating it with the exact same seed cannot help. A gain from the other
    # backend invalidates that exhausted seed and makes a new turn worthwhile.
    exhausted_on: dict[str, tuple[InputFrame, ...]] = {}
    cycle = int(resume_phase["cycle"]) - 1 if resume_phase is not None else 0
    while True:
        cycle += 1
        cycle_improved = (bool(resume_phase["cycle_improved"])
                          if resume_phase is not None else False)
        start_backend = str(resume_phase["backend"]) if resume_phase is not None else None
        for backend, iterations, patience in phases:
            if start_backend is not None and backend != start_backend:
                continue
            if start_backend is None and exhausted_on.get(backend) == search_seed:
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
                if not config.live_save_best and config.workers > 1 and now - last_live_check < 30.0:
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
                found, used = local_search(
                    level, search_seed, stage.goal, start=stage.start,
                    editable_end=stage.end,
                    config=replace(config, search_backend=backend),
                    iterations=iterations, rounds=0,
                    stagnation_rounds=patience,
                    seed=seed, include_partial=True,
                    live_update_interval=(0.0 if config.live_save_best else
                                      30.0 if config.workers > 1 else 0.75),
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
            exhausted_on[backend] = search_seed
            if progress:
                progress(f"[auto:user-splice:refine] {stage.name!r}: "
                         f"cycle {cycle}, {backend} phase finished at "
                         f"its own stagnation limit {patience}; "
                         f"{'stage improved' if phase_improved else 'no stage gain'}; "
                         f"{used} distinct evaluations")
        # Each backend has now exhausted this incumbent. Restart only when
        # another backend actually changed the seed since its last search.
        pending = any(exhausted_on.get(backend) != search_seed
                      for backend, _, _ in phases)
        if progress:
            progress(f"[auto:user-splice:refine] {stage.name!r}: "
                     f"cycle {cycle} "
                     f"{'improved; next changed-seed backend' if pending else 'both modes stagnated; advancing'}; "
                     f"{calls} backend phase(s), {evaluations} distinct evaluations")
        if not pending:
            break
    return tuple(merged.items()), evaluations, calls


def _search_stage_until_stagnant(
    level: Level, branch: tuple[InputFrame, ...], stage: SpliceSearchStage,
    config: RandomSpliceConfig, rng: random.Random,
    *, stage_rank: Callable[[tuple[InputFrame, ...]], tuple | None] | None = None,
    progress: Callable[[str], None] | None = None,
    candidate_callback: Callable[[tuple[InputFrame, ...], int], None] | None = None,
    local_search: Callable | None = None,
                  evaluator_factory: Callable | None = None,
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
    evaluator = evaluator_factory(level, stage.goal)

    def rank(frames: tuple[InputFrame, ...]) -> tuple | None:
        if stage_rank is not None:
            return stage_rank(frames)
        evaluation = evaluator.evaluate(frames)
        return evaluation.objective_key if evaluation.feasible else None

    local_search = _default_local_search if local_search is None else local_search
    evaluator_factory = EndpointEvaluator if evaluator_factory is None else evaluator_factory
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
                found, count = local_search(
                    level, search_seed, stage.goal, start=stage.start,
                    editable_end=stage.end,
                    config=replace(config, search_backend=backend),
                    iterations=iterations, rounds=config.splice_rounds,
                    seed=rng.getrandbits(63), include_partial=True,
                    live_update_interval=(0.0 if config.live_save_best else
                                      30.0 if config.workers > 1 else 0.75),
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

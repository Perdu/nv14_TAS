"""Reference-guided Auto search for Local's shared endpoint goals.

This is deliberately separate from completed-route Auto: checkpoint goals may
become feasible even when the remaining replay dies or never exits. It reuses
Local's exact native endpoint evaluator and Auto's structural mutation tools,
without pretending that a partial replay can enter the completion-only splice
and repair coordinator.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import random
import time
from collections.abc import Callable, Sequence

from nv14_auto import NEUTRAL_INPUT, evaluate_replay_with_sentinel, mutate_jump_pulse
from nv14_endpoint import EndpointEvaluation, EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_engine import InputFrame, Level
from nv14_population import PopulationCandidate, _mutate as _population_mutate
from nv14_search import ALL_INPUT_CHOICES
from nv14_replay import (
    RetimeMutation, apply_single_transition_retime, apply_suffix_retime,
    editable_frames, input_transition_frames,
)


@dataclass(frozen=True, slots=True)
class AutoEndpointConfig:
    iterations: int = 5000
    beam_width: int = 32
    max_retime: int = 3
    seed: int = 0
    range_start: int = 0
    range_end: int | None = None
    mutation_span: int = 24
    completion_policy: str = "checkpoint"
    repair_steps: int = 32
    repair_lookback: int = 40

    def __post_init__(self) -> None:
        if self.iterations < 0 or self.beam_width < 1:
            raise ValueError("iterations must be non-negative and beam width positive")
        if not 1 <= self.max_retime <= 3:
            raise ValueError("max-retime must be between 1 and 3")
        if self.range_start < 0 or self.range_end is not None and self.range_end < self.range_start:
            raise ValueError("invalid editable range")
        if self.mutation_span < 1:
            raise ValueError("mutation-span must be positive")
        if self.completion_policy not in ("checkpoint", "complete"):
            raise ValueError("completion-policy must be checkpoint or complete")
        if type(self.repair_steps) is not int or self.repair_steps < 0:
            raise ValueError("endpoint repair-steps must be nonnegative")
        if type(self.repair_lookback) is not int or self.repair_lookback < 1:
            raise ValueError("endpoint repair-lookback must be positive")


@dataclass(frozen=True, slots=True)
class AutoEndpointCandidate:
    frames: tuple[InputFrame, ...]
    evaluation: EndpointEvaluation
    complete: bool = False


@dataclass(frozen=True, slots=True)
class _EndpointWorkerProgress:
    """Small heartbeat; no native objects or replay data cross processes."""
    worker_index: int
    proposals: int
    evaluations: int
    elapsed_seconds: float


def _key(frames: Sequence[InputFrame]) -> bytes:
    return bytes(int(f.left) | (int(f.right) << 1) | (int(f.jump) << 2) for f in frames)


def _rank(candidate: AutoEndpointCandidate, source_key: bytes) -> tuple:
    result = candidate.evaluation
    changed = sum(a != b for a, b in zip(_key(candidate.frames), source_key))
    if candidate.complete or result.feasible:
        return (0, *result.objective_key, changed, _key(candidate.frames))
    return (1, result.progress_key, changed, _key(candidate.frames))


def _proposal(
    parent: tuple[InputFrame, ...], *, rng: random.Random,
    config: AutoEndpointConfig, start: int, end: int,
    donor: tuple[InputFrame, ...] | None,
) -> tuple[InputFrame, ...]:
    """Auto-style transitions, suffix timing, jump pulses and section splices.

    Never mutate outside the inclusive range; no fixed-frame length changes.
    Invalid structural moves fall back to a small directional/jump edit.
    """
    result = list(parent)
    mutation = rng.randrange(7)
    if mutation in (0, 1):
        transitions = [i for i in input_transition_frames(parent)
                       if start <= i <= end]
        if transitions:
            seam = rng.choice(transitions)
            delta = rng.choice((-1, 1, -2, 2, -3, 3))
            if abs(delta) <= config.max_retime:
                try:
                    spec = RetimeMutation(seam, delta)
                    changed = (apply_single_transition_retime(parent, spec)
                               if mutation == 0 else apply_suffix_retime(parent, spec))
                    if all(parent[i] == changed[i] for i in range(start)) and all(
                        parent[i] == changed[i] for i in range(end + 1, len(parent))
                    ):
                        return tuple(changed)
                except ValueError:
                    pass
    if mutation == 2:
        pulses = []
        pressed = False
        for index, frame in enumerate(parent):
            if frame.jump and not pressed:
                pulses.append(index)
            pressed = frame.jump
        pulses = [index for index in pulses if start <= index <= end]
        if pulses:
            selected = rng.choice(pulses)
            full_pulses = []
            pressed = False
            for index, frame in enumerate(parent):
                if frame.jump and not pressed:
                    full_pulses.append(index)
                pressed = frame.jump
            try:
                moved = mutate_jump_pulse(
                    parent + (NEUTRAL_INPUT,), full_pulses.index(selected),
                    start_delta=rng.choice((-2, -1, 1, 2)),
                )[:-1]
                if all(parent[i] == moved[i] for i in range(start)) and all(
                    parent[i] == moved[i] for i in range(end + 1, len(parent))
                ):
                    return moved
            except ValueError:
                pass
    if mutation == 3 and donor is not None and end - start >= 2:
        left = rng.randint(start, end - 1)
        right = min(end + 1, left + rng.randint(1, config.mutation_span))
        result[left:right] = donor[left:right]
    elif mutation in (4, 5):
        left = rng.randint(start, end)
        right = min(end + 1, left + rng.randint(1, config.mutation_span))
        direction = rng.choice((-1, 0, 1))
        for index in range(left, right):
            f = result[index]
            result[index] = InputFrame(direction < 0, direction > 0, f.jump, None)
    else:
        index = rng.randint(start, end)
        f = result[index]
        if rng.randrange(2):
            result[index] = InputFrame(f.left, f.right, not f.jump, None)
        else:
            direction = rng.choice((-1, 0, 1))
            result[index] = InputFrame(direction < 0, direction > 0, f.jump, None)
    return tuple(result)


def _hybrid_proposal(
    parent: AutoEndpointCandidate, donor: AutoEndpointCandidate, *,
    rng: random.Random, config: AutoEndpointConfig, start: int, end: int,
) -> tuple[tuple[InputFrame, ...], int]:
    """Mix Auto retiming/jump macros with Local's richer pulse/jump/crossover ops.

    Both operators preserve the immutable replay prefix/suffix and do not
    require a completed level. Using Local's actual mutation implementation
    prevents the endpoint path from drifting into a weaker copy of its tools.
    """
    if rng.randrange(2):
        frames = _proposal(parent.frames, rng=rng, config=config,
                           start=start, end=end, donor=donor.frames)
        changes = [i for i in range(start, end + 1)
                   if frames[i] != parent.frames[i]]
        return frames, (changes[0] if changes else rng.randint(start, end))
    first = PopulationCandidate(parent.frames, parent.evaluation)
    second = PopulationCandidate(donor.frames, donor.evaluation)
    frames, _label, anchor = _population_mutate(
        first, second, ((start, end),), tuple(range(start, end + 1)),
        rng, config.mutation_span,
    )
    return frames, anchor


def _select_endpoint_beam(
    candidates: Sequence[AutoEndpointCandidate], size: int, source_key: bytes,
) -> list[AutoEndpointCandidate]:
    """Keep valid elites *and* physically different, repairable failures.

    The old beam could discard every infeasible route immediately after finding
    a feasible one. Required jumps / switches frequently need a temporarily
    infeasible route to be repaired across several mutations.
    """
    unique = {_key(candidate.frames): candidate for candidate in candidates}
    if len(unique) <= size:
        return sorted(unique.values(), key=lambda c: _rank(c, source_key))
    feasible = sorted((c for c in unique.values() if c.evaluation.feasible),
                      key=lambda c: _rank(c, source_key))
    infeasible = sorted((c for c in unique.values() if not c.evaluation.feasible),
                        key=lambda c: _rank(c, source_key))
    reserve = min(len(infeasible), max(1, size // 4), size - 1) if feasible else size
    target_valid = size - reserve if feasible else 0
    selected: list[AutoEndpointCandidate] = []
    used: set[bytes] = set()

    def add_from(group: list[AutoEndpointCandidate], limit: int) -> None:
        if not limit:
            return
        niches: set[tuple] = set()
        chosen: list[AutoEndpointCandidate] = []
        for candidate in group[:max(1, limit // 4)]:
            identity = _key(candidate.frames)
            if identity not in used:
                chosen.append(candidate)
                used.add(identity)
                niches.add(candidate.evaluation.niche_key)
        for candidate in group:
            if len(chosen) >= limit:
                break
            identity = _key(candidate.frames)
            if identity not in used and candidate.evaluation.niche_key not in niches:
                chosen.append(candidate)
                used.add(identity)
                niches.add(candidate.evaluation.niche_key)
        for candidate in group:
            if len(chosen) >= limit:
                break
            identity = _key(candidate.frames)
            if identity not in used:
                chosen.append(candidate)
                used.add(identity)
        selected.extend(chosen)

    add_from(feasible, target_valid)
    add_from(infeasible, reserve)
    for candidate in sorted(unique.values(), key=lambda c: _rank(c, source_key)):
        if len(selected) >= size:
            break
        identity = _key(candidate.frames)
        if identity not in used:
            selected.append(candidate)
            used.add(identity)
    return sorted(selected, key=lambda c: _rank(c, source_key))


def _repair_frame_candidates(
    frames: Sequence[InputFrame], source: Sequence[InputFrame],
    goal: EndpointGoal, candidate: AutoEndpointCandidate, *, anchor: int,
    start: int, end: int, lookback: int, rng: random.Random,
) -> list[int]:
    """Prioritise the mutation, failure, jump windows and reference transitions.

    A required event might be many frames before the target; only looking at
    the last 32 frames silently prevents repairing that event.
    """
    centers = [anchor]
    endpoint = candidate.evaluation
    if endpoint.terminal_dead and start <= endpoint.terminal_frame <= end:
        centers.insert(0, endpoint.terminal_frame)
    if endpoint.missing_jump or endpoint.missing_jump_indices:
        for requirement in goal.required_jumps:
            centers.extend((requirement.frames[0], requirement.frames[1]))
        if goal.require_jump_frames is not None:
            centers.extend(goal.require_jump_frames)
    centers.append(min(end, max(start, endpoint.frame)))
    # Prefer nearby changed frames and places where the known source changes
    # input. Repair can undo damage and restore a required route-control event.
    centers = [min(end, max(start, c)) for c in centers]
    seen: set[int] = set()
    positions: list[int] = []
    for center in centers:
        bounds = range(max(start, center - lookback), min(end, center + 4) + 1)
        local = [i for i in bounds if frames[i] != source[i]
                 or (i > start and source[i] != source[i - 1])]
        local += [i for i in bounds if i not in local]
        for index in local:
            if index not in seen:
                positions.append(index)
                seen.add(index)
    # Prevent a fixed seed from inspecting precisely the same distant frames.
    distant = [i for i in range(start, end + 1) if i not in seen]
    rng.shuffle(distant)
    positions.extend(distant)
    return positions


def _endpoint_repair(
    candidate: AutoEndpointCandidate, parent: AutoEndpointCandidate,
    source: tuple[InputFrame, ...], goal: EndpointGoal,
    *, anchor: int, start: int, end: int, config: AutoEndpointConfig,
    rng: random.Random, consider: Callable[[tuple[InputFrame, ...]], AutoEndpointCandidate | None],
    budget: int,
) -> None:
    """Bounded, goal-scored local continuation/interaction repair.

    Every trial uses EndpointEvaluator, which enforces switch identities,
    required jumps and checkpoint constraints. No completion-only Auto splice
    state is reused. Repair trials consume the *same* search budget as macros.
    """
    if budget <= 0:
        return
    positions = _repair_frame_candidates(candidate.frames, source, goal, candidate,
                                         anchor=anchor, start=start, end=end,
                                         lookback=config.repair_lookback, rng=rng)
    repaired = candidate
    used = 0
    for index in positions:
        if used >= budget:
            break
        # Try source restoration and parent restoration first: switch-safe
        # repair often consists of reintroducing one skipped reference input.
        choices = [source[index], parent.frames[index]]
        pool = list(ALL_INPUT_CHOICES)
        rng.shuffle(pool)
        choices += pool
        keys: set[tuple] = set()
        for choice in choices:
            if used >= budget:
                break
            buttons = (choice.left, choice.right, choice.jump, choice.jump_trigger)
            if buttons in keys or choice == repaired.frames[index]:
                continue
            keys.add(buttons)
            frames = list(repaired.frames)
            frames[index] = choice
            used += 1
            outcome = consider(tuple(frames))
            if outcome is not None and _rank(outcome, _key(source)) < _rank(repaired, _key(source)):
                repaired = outcome
                # One repair may enable a previously missed interaction; allow
                # follow-up changes at other frames, not just single-bit fixes.

def optimise_auto_endpoint(
    level: Level, source_frames: Sequence[InputFrame], goal: EndpointGoal,
    config: AutoEndpointConfig, *,
    best_callback: Callable[[AutoEndpointCandidate], None] | None = None,
    progress: Callable[[int, int, AutoEndpointCandidate | None], None] | None = None,
) -> tuple[AutoEndpointCandidate, AutoEndpointCandidate | None, int]:
    """Return (baseline, best feasible candidate or None, unique evaluations).

    The evaluator's feasibility and ordered objective keys are *identical* to
    Local population's, including earliest-event history, constraints and
    secondary tie breaks. Partial results are not converted into completed TASes.
    """
    source = tuple(editable_frames(source_frames))
    if goal.target_frame >= len(source):
        raise ValueError("target-frame lies beyond the supplied replay; add input frames")
    end = min(len(source) - 1, goal.target_frame,
              len(source) - 1 if config.range_end is None else config.range_end)
    start = config.range_start
    if start > end:
        raise ValueError("editable range is empty or lies beyond target-frame")
    evaluator = EndpointEvaluator(level, goal, source, prefix_frame=start)
    rng = random.Random(config.seed)
    original_key = _key(source)
    visited = {original_key}

    def evaluate_candidate(frames: tuple[InputFrame, ...]) -> AutoEndpointCandidate:
        evaluation = evaluator.evaluate(frames)
        complete = False
        if config.completion_policy == "complete" and evaluation.feasible:
            full = evaluate_replay_with_sentinel(level, frames)
            complete = full.valid and full.finish_tick == len(frames)
            if not complete:
                # Incomplete solutions may remain repair/exploration donors, but
                # cannot displace an independently completed result.
                evaluation = replace(evaluation, feasible=False)
        return AutoEndpointCandidate(frames, evaluation, complete)

    baseline = evaluate_candidate(source)
    beam = [baseline]
    # The source is a baseline, not a newly discovered improvement.  It must
    # never enter the checkpoint callback merely because it is feasible.
    best = baseline if baseline.evaluation.feasible else None
    evaluated = 0
    spent = 0
    last_progress = time.monotonic()
    last_reported = -1
    if progress is not None:
        progress(0, 0, best)
        last_reported = 0

    def consider(frames: tuple[InputFrame, ...]) -> AutoEndpointCandidate | None:
        nonlocal evaluated, spent, best, beam
        if spent >= config.iterations:
            return None
        spent += 1
        identity = _key(frames)
        if identity in visited:
            return None
        visited.add(identity)
        candidate = evaluate_candidate(frames)
        evaluated += 1
        if candidate.evaluation.feasible and (
            best is None or candidate.evaluation.objective_key < best.evaluation.objective_key
        ):
            # Canonical packed replay and completion policy are always verified
            # before publication, including candidates recovered by repair.
            from nv14_replay import decode_complex_replay, encode_complex_replay
            packed = tuple(editable_frames(decode_complex_replay(
                encode_complex_replay(frames)).frames))
            checked = verify_endpoint(level, packed, goal, expected=candidate.evaluation)
            valid_finish = True
            if config.completion_policy == "complete":
                full = evaluate_replay_with_sentinel(level, packed)
                valid_finish = full.valid and full.finish_tick == len(packed)
            if checked.feasible and valid_finish:
                best = AutoEndpointCandidate(packed, checked, valid_finish
                                             if config.completion_policy == "complete" else False)
                if best_callback:
                    best_callback(best)
        beam = _select_endpoint_beam((*beam, candidate), config.beam_width, original_key)
        return candidate

    while spent < config.iterations:
        # Preserve feasible solutions and diverse repairable failures using
        # the hybrid beam. Full-level Auto uses a different coordinator.
        parent = min(rng.sample(beam, min(2, len(beam))),
                     key=lambda c: _rank(c, original_key)) if rng.random() < 0.7 else rng.choice(beam)
        donor = rng.choice(beam)
        proposed, anchor = _hybrid_proposal(parent, donor, rng=rng,
                                            config=config, start=start, end=end)
        candidate = consider(proposed)
        if (candidate is not None and config.repair_steps
                and spent < config.iterations and
                (_rank(candidate, original_key) < _rank(parent, original_key)
                 or (not candidate.evaluation.feasible and rng.random() < 0.25))):
            _endpoint_repair(candidate, parent, source, goal, anchor=anchor,
                             start=start, end=end, config=config, rng=rng,
                             consider=consider,
                             budget=min(config.repair_steps, config.iterations - spent))
        # Repairs can advance spent by dozens of proposals in one step, so
        # checking spent modulo a fixed stride would miss many reporting
        # opportunities. The clock check is negligible beside simulation.
        if progress is not None:
            now = time.monotonic()
            if now - last_progress >= 1.5 or spent == config.iterations:
                progress(spent, evaluated, best)
                last_progress = now
                last_reported = spent
    if progress is not None and last_reported != spent:
        progress(spent, evaluated, best)
    return baseline, best, evaluated


def _endpoint_worker(payload: tuple) -> tuple[AutoEndpointCandidate, AutoEndpointCandidate | None, int]:
    """Spawn-safe worker: construct engine locally, never transfer native handles."""
    level_string, simulate_enemies, frames, goal, config, updates, worker_index = payload
    from nv14_engine import parse_level_string
    local_level = parse_level_string(level_string, simulate_enemies=simulate_enemies)
    started = time.monotonic()
    last_sent = 0.0

    def send(candidate: AutoEndpointCandidate) -> None:
        nonlocal last_sent
        now = time.monotonic()
        if updates is not None and now - last_sent >= 0.75:
            updates.put(candidate)
            last_sent = now

    def heartbeat(proposals: int, evaluations: int, _best: AutoEndpointCandidate | None) -> None:
        if updates is not None:
            updates.put(_EndpointWorkerProgress(
                worker_index, proposals, evaluations, time.monotonic() - started,
            ))

    result = optimise_auto_endpoint(
        local_level, frames, goal, config,
        best_callback=send if updates is not None else None,
        progress=heartbeat if updates is not None else None,
    )
    return result


def optimise_auto_endpoint_campaign(
    level: Level, source_frames: Sequence[InputFrame], goal: EndpointGoal,
    config: AutoEndpointConfig, *, workers: int = 1, runs: int = 1,
    best_callback: Callable[[AutoEndpointCandidate], None] | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[AutoEndpointCandidate, AutoEndpointCandidate | None, int]:
    """Run seeded Auto-style endpoint beams in independent processes.

    Rounds feed back the best *verified* checkpoint into the next generation.
    Incomplete-route endpoints are never handed to the complete-run coordinator.
    """
    if workers < 1 or runs < 1:
        raise ValueError("endpoint workers and runs must be positive")
    initial = tuple(editable_frames(source_frames))
    # Evaluate the reference exactly once in the parent, before launching
    # workers, so all rounds compare against a genuine baseline.  Evaluating
    # with zero proposals uses the same completion policy and endpoint path.
    baseline, _, _ = optimise_auto_endpoint(
        level, initial, goal, replace(config, iterations=0),
    )
    best: AutoEndpointCandidate | None = (
        baseline if baseline.evaluation.feasible else None
    )
    total = 0
    current = initial
    if progress is not None:
        result = baseline.evaluation
        progress(
            f"baseline: source {'feasible' if result.feasible else 'infeasible'}; "
            f"frame {result.frame}; score {result.score:.12g}; "
            f"position ({result.x:.12g}, {result.y:.12g}); "
            f"velocity ({result.vx:.12g}, {result.vy:.12g}); "
            f"objective {goal.objective}; policy {config.completion_policy}"
        )

    def best_status() -> str:
        if best is None:
            return "no feasible endpoint yet"
        result = best.evaluation
        suffix = " (baseline)" if best is baseline else ""
        return f"best frame {result.frame}, score {result.score:.12g}{suffix}"

    def absorb(candidate: AutoEndpointCandidate | None) -> bool:
        nonlocal best
        if candidate is None:
            return False
        # Revalidate the cross-process result independently in the parent.
        checked = verify_endpoint(level, candidate.frames, goal, expected=candidate.evaluation)
        if not checked.feasible:
            raise ValueError("worker supplied an infeasible endpoint")
        if config.completion_policy == "complete":
            full = evaluate_replay_with_sentinel(level, candidate.frames)
            if not full.valid or full.finish_tick != len(candidate.frames):
                raise ValueError("worker supplied a non-completing endpoint")
        candidate = AutoEndpointCandidate(candidate.frames, checked, candidate.complete)
        # Only real goal improvements are checkpoints.  Lexicographic input
        # tie-breaks are useful for beam diversity, but not for announcing or
        # writing a supposed new best with an identical endpoint score.
        if best is None or checked.objective_key < best.evaluation.objective_key:
            best = candidate
            if best_callback:
                best_callback(best)
            return True
        return False

    # Endpoint goals use long independent searches just like full-run Auto.
    # Unlike the earlier endpoint implementation, status is emitted while the
    # workers search, even if none finds a new feasible improvement.
    manager = None
    pool = None
    try:
        for round_index in range(runs):
            if progress:
                progress(
                    f"round {round_index + 1}/{runs}: starting {workers} worker(s) "
                    f"x {config.iterations:,} proposals "
                    f"({workers * config.iterations:,} total budget)"
                )
            started = time.monotonic()
            last_status = started

            if workers == 1:
                worker_config = replace(config, seed=config.seed + round_index * 1000003)

                def serial_progress(proposals: int, evaluations: int,
                                    _worker_best: AutoEndpointCandidate | None) -> None:
                    nonlocal last_status
                    now = time.monotonic()
                    if progress and (now - last_status >= 5.0 or
                                     proposals == config.iterations):
                        elapsed = max(0.001, now - started)
                        progress(
                            f"round {round_index + 1}/{runs}: worker 1/1; "
                            f"{proposals:,}/{config.iterations:,} proposals "
                            f"({100 * proposals / max(1, config.iterations):.0f}%); "
                            f"{evaluations:,} distinct evaluations; "
                            f"{best_status()}; "
                            f"{proposals / elapsed:,.1f} proposals/s; "
                            f"{elapsed:.1f}s elapsed"
                        )
                        last_status = now

                run_baseline, winner, evaluated = optimise_auto_endpoint(
                    level, current, goal, worker_config,
                    best_callback=absorb,
                    progress=serial_progress if progress else None,
                )
                total += evaluated
                absorb(winner)
            else:
                from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
                from multiprocessing import get_context
                import queue
                source_string = getattr(level, "source_level_string", None)
                if not source_string:
                    raise ValueError("parallel endpoint search requires original level data")
                context = get_context("spawn")
                # Keep the executor alive across outer rounds; worker progress is
                # cheap and contains no heavyweight replay/native state.
                if pool is None:
                    manager = context.Manager()
                    updates = manager.Queue()
                    pool = ProcessPoolExecutor(max_workers=workers, mp_context=context)
                tasks = [
                    (source_string, level.simulate_enemies, current, goal,
                     replace(config, seed=config.seed + round_index * 1000003
                             + worker_index * 104729), updates, worker_index)
                    for worker_index in range(workers)
                ]
                futures = {pool.submit(_endpoint_worker, task): index
                           for index, task in enumerate(tasks)}
                worker_status: dict[int, _EndpointWorkerProgress] = {}
                finished: dict[int, int] = {}

                def drain_updates() -> None:
                    while True:
                        try:
                            update = updates.get_nowait()
                        except queue.Empty:
                            break
                        if isinstance(update, _EndpointWorkerProgress):
                            if update.worker_index not in finished:
                                old = worker_status.get(update.worker_index)
                                if old is None or update.proposals >= old.proposals:
                                    worker_status[update.worker_index] = update
                        else:
                            absorb(update)

                def report_status(force: bool = False) -> None:
                    nonlocal last_status
                    if not progress:
                        return
                    now = time.monotonic()
                    if not force and now - last_status < 5.0:
                        return
                    elapsed = max(0.001, now - started)
                    proposals = sum(finished.values()) + sum(
                        worker.proposals for index, worker in worker_status.items()
                        if index not in finished
                    )
                    distinct = sum(finished_evaluations.values()) + sum(
                        worker.evaluations for index, worker in worker_status.items()
                        if index not in finished
                    )
                    progress(
                        f"round {round_index + 1}/{runs}: "
                        f"{len(finished)}/{workers} workers finished; "
                        f"{proposals:,}/{workers * config.iterations:,} proposals "
                        f"({100 * proposals / max(1, workers * config.iterations):.0f}%); "
                        f"{distinct:,} distinct evaluations; "
                        f"{best_status()}; "
                        f"{proposals / elapsed:,.1f} proposals/s; "
                        f"{elapsed:.1f}s elapsed"
                    )
                    last_status = now

                finished_evaluations: dict[int, int] = {}
                while futures:
                    done, _ = wait(tuple(futures), timeout=0.25,
                                   return_when=FIRST_COMPLETED)
                    drain_updates()
                    for future in done:
                        index = futures.pop(future)
                        run_baseline, winner, evaluated = future.result()
                        total += evaluated
                        finished[index] = config.iterations
                        finished_evaluations[index] = evaluated
                        absorb(winner)
                        if progress:
                            progress(
                                f"round {round_index + 1}/{runs}: "
                                f"worker {index + 1}/{workers} finished; "
                                f"{evaluated:,} distinct evaluations"
                            )
                    report_status()
                drain_updates()
                report_status(force=True)

            if best is not None:
                current = best.frames
            if progress:
                progress(f"round {round_index + 1}/{runs} complete: "
                         f"{total:,} distinct evaluations total")
    finally:
        if pool is not None:
            pool.shutdown(wait=True)
        if manager is not None:
            manager.shutdown()
    return baseline, best, total

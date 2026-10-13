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
from collections.abc import Callable, Sequence

from nv14_auto import NEUTRAL_INPUT, evaluate_replay_with_sentinel, mutate_jump_pulse
from nv14_endpoint import EndpointEvaluation, EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_engine import InputFrame, Level
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


@dataclass(frozen=True, slots=True)
class AutoEndpointCandidate:
    frames: tuple[InputFrame, ...]
    evaluation: EndpointEvaluation
    complete: bool = False


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
    best = baseline if baseline.evaluation.feasible else None
    if best is not None and best_callback:
        best_callback(best)
    evaluated = 0
    for step in range(config.iterations):
        parent = rng.choice(beam[:min(len(beam), max(1, config.beam_width // 2))])
        donor = rng.choice(beam).frames if len(beam) >= 2 else None
        proposed = _proposal(parent.frames, rng=rng, config=config,
                             start=start, end=end, donor=donor)
        identity = _key(proposed)
        if identity in visited:
            continue
        visited.add(identity)
        candidate = evaluate_candidate(proposed)
        evaluated += 1
        if candidate.evaluation.feasible and (
            best is None or _rank(candidate, original_key) < _rank(best, original_key)
        ):
            # Require canonical packed replay verification *before* saving.
            from nv14_replay import decode_complex_replay, encode_complex_replay
            packed = tuple(editable_frames(decode_complex_replay(
                encode_complex_replay(proposed)).frames))
            checked = verify_endpoint(level, packed, goal, expected=candidate.evaluation)
            if checked.feasible and (
                config.completion_policy != "complete" or
                evaluate_replay_with_sentinel(level, packed).valid
                and evaluate_replay_with_sentinel(level, packed).finish_tick == len(packed)
            ):
                best = AutoEndpointCandidate(packed, checked, candidate.complete)
                if best_callback:
                    best_callback(best)
        beam.append(candidate)
        beam.sort(key=lambda item: _rank(item, original_key))
        if len(beam) > config.beam_width:
            # Keep one source-lineage candidate to prevent early collapse of
            # infeasible checkpoint searches into a single promising niche.
            beam = beam[:config.beam_width]
        if progress and (step + 1) % 1000 == 0:
            progress(step + 1, evaluated, best)
    return baseline, best, evaluated


def _endpoint_worker(payload: tuple) -> tuple[AutoEndpointCandidate, AutoEndpointCandidate | None, int]:
    """Spawn-safe worker: construct engine locally, never transfer native handles."""
    level_string, simulate_enemies, frames, goal, config = payload
    from nv14_engine import parse_level_string
    local_level = parse_level_string(level_string, simulate_enemies=simulate_enemies)
    return optimise_auto_endpoint(local_level, frames, goal, config)


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
    best: AutoEndpointCandidate | None = None
    baseline: AutoEndpointCandidate | None = None
    total = 0
    current = initial

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
        if best is None or _rank(candidate, _key(initial)) < _rank(best, _key(initial)):
            best = candidate
            if best_callback:
                best_callback(best)
            return True
        return False

    if workers == 1:
        for round_index in range(runs):
            worker_config = replace(config, seed=config.seed + round_index * 1000003)
            run_baseline, winner, evaluated = optimise_auto_endpoint(
                level, current, goal, worker_config,
                best_callback=absorb,
            )
            if baseline is None:
                baseline = run_baseline
            total += evaluated
            if best is not None:
                current = best.frames
            if progress:
                progress(f"round {round_index + 1}/{runs}: {total} distinct evaluations")
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        from multiprocessing import get_context
        source_string = getattr(level, "source_level_string", None)
        if not source_string:
            raise ValueError("parallel endpoint search requires original level data")
        with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
            for round_index in range(runs):
                tasks = [
                    (source_string, level.simulate_enemies, current, goal,
                     replace(config, seed=config.seed + round_index * 1000003 + worker_index * 104729))
                    for worker_index in range(workers)
                ]
                futures = [pool.submit(_endpoint_worker, task) for task in tasks]
                for future in as_completed(futures):
                    run_baseline, winner, evaluated = future.result()
                    if baseline is None:
                        baseline = run_baseline
                    total += evaluated
                    absorb(winner)
                if best is not None:
                    current = best.frames
                if progress:
                    progress(f"round {round_index + 1}/{runs}: {total} distinct evaluations")
    assert baseline is not None
    return baseline, best, total

"""Bounded, goal-aware population search for manual replay construction.

Every proposal has exactly the source replay's length. Source trigger bits are
normalised to button edges, as in Local and Auto. The central evaluator checks
actual changed normalised inputs against the editable mask before allowing a
mutation, repair or crossover into the search.
Completion and alignment with a reference trajectory are deliberately absent.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import queue
import random
import tempfile
import time
from typing import Any

from nv14_checkpoint import OPTIMISER_VERSION, canonical_json_bytes, optimiser_build_hash
from nv14_engine import InputFrame
from nv14_endpoint import EndpointEvaluation, EndpointEvaluator, EndpointGoal
from nv14_jump import _automatic_jump_worker_count
from nv14_local import _normalise_local_frame_ranges, _stop_local_executor_for_exception
from nv14_replay import editable_frames
from nv14_search import ALL_INPUT_CHOICES


@dataclass(frozen=True, slots=True)
class PopulationConfig:
    iterations: int = 10000
    beam: int = 32
    rounds: int = 1
    stagnation_rounds: int = 20
    workers: int = 0
    seed: int | str | None = 0
    top_results: int = 1
    repair_steps: int = 64
    repair_lookback: int = 32
    mutation_span: int = 32
    checkpoint_path: str | Path | None = None
    resume: bool = False


@dataclass(frozen=True, slots=True)
class PopulationCandidate:
    frames: tuple[InputFrame, ...]
    evaluation: EndpointEvaluation
    history: tuple[str, ...] = ()
    edits: int = 0
    input_key: bytes = b""


@dataclass(frozen=True, slots=True)
class PopulationResult:
    candidates: tuple[PopulationCandidate, ...]
    baseline: EndpointEvaluation
    rounds: int
    evaluations: int
    stagnant_rounds: int
    worker_count: int
    seed: int
    interrupted: bool = False


def _input_key(frames: Sequence[InputFrame]) -> bytes:
    return bytes(
        int(frame.left) | (int(frame.right) << 1) | (int(frame.jump) << 2)
        | (int(bool(frame.jump_trigger)) << 3)
        | (int(frame.jump_trigger is None) << 4)
        for frame in frames
    )


def _decode_frames(values: object) -> tuple[InputFrame, ...]:
    if not isinstance(values, list) or any(
        type(value) is not int or not 0 <= value <= 31 for value in values
    ):
        raise ValueError("population checkpoint contains invalid replay inputs")
    return tuple(InputFrame(bool(v & 1), bool(v & 2), bool(v & 4),
                            None if v & 16 else bool(v & 8)) for v in values)


def _assert_bounded(
    source: Sequence[InputFrame], candidate: Sequence[InputFrame], mutable: frozenset[int]
) -> None:
    if len(candidate) != len(source):
        raise ValueError("population candidate changed the fixed replay length")
    if any(old != new and index not in mutable
           for index, (old, new) in enumerate(zip(source, candidate))):
        raise ValueError("population candidate changed an input outside the editable ranges")


def _rank(candidate: PopulationCandidate) -> tuple:
    return (candidate.evaluation.progress_key, candidate.edits, candidate.input_key)


def _primary_rank(candidate: PopulationCandidate) -> tuple:
    # Primary and optional secondary objectives precede replay disturbance.
    return (*candidate.evaluation.objective_key, candidate.edits, candidate.input_key)


def _select_population(
    candidates: Sequence[PopulationCandidate], capacity: int,
) -> tuple[PopulationCandidate, ...]:
    """Keep elites, distinct physical niches, and a bounded repair frontier."""
    unique = {candidate.input_key: candidate for candidate in candidates}
    ranked = sorted(unique.values(), key=_rank)
    if len(ranked) <= capacity:
        return tuple(ranked)
    feasible = sorted((c for c in ranked if c.evaluation.feasible), key=_primary_rank)
    infeasible = [c for c in ranked if not c.evaluation.feasible]
    invalid_slots = min(len(infeasible), max(1, capacity // 4), capacity - 1) if feasible else capacity
    valid_slots = capacity - invalid_slots if feasible else 0
    selected: list[PopulationCandidate] = []
    selected_keys: set[bytes] = set()

    def add(candidate: PopulationCandidate) -> None:
        selected.append(candidate)
        selected_keys.add(candidate.input_key)

    for group, slots in ((feasible, valid_slots), (infeasible, invalid_slots)):
        start = len(selected)
        niches: set[tuple] = set()
        # Retain a small objective elite even when its endpoints share a niche.
        for candidate in group[:max(1, slots // 4) if slots else 0]:
            add(candidate)
            niches.add(candidate.evaluation.niche_key)
        for candidate in group:
            if len(selected) - start >= slots:
                break
            if candidate.input_key in selected_keys:
                continue
            if candidate.evaluation.niche_key not in niches:
                add(candidate)
                niches.add(candidate.evaluation.niche_key)
        for candidate in group:
            if len(selected) - start >= slots:
                break
            if candidate.input_key not in selected_keys:
                add(candidate)
    for candidate in ranked:
        if len(selected) >= capacity:
            break
        if candidate.input_key not in selected_keys:
            add(candidate)
    return tuple(sorted(selected, key=_rank))


def _diverse_results(
    candidates: Sequence[PopulationCandidate], count: int,
) -> tuple[PopulationCandidate, ...]:
    ranked = sorted(
        {c.input_key: c for c in candidates if c.evaluation.feasible}.values(),
        key=_primary_rank,
    )
    if not ranked:
        return ()
    chosen = [ranked[0]]
    niches = {ranked[0].evaluation.niche_key}
    keys = {ranked[0].input_key}
    for candidate in ranked[1:]:
        if len(chosen) >= count:
            break
        if candidate.evaluation.niche_key not in niches:
            chosen.append(candidate)
            niches.add(candidate.evaluation.niche_key)
            keys.add(candidate.input_key)
    # Do not pad with input aliases whose simulated endpoint is identical.
    states = {candidate.evaluation.state_key for candidate in chosen}
    for candidate in ranked[1:]:
        if len(chosen) >= count:
            break
        if candidate.input_key not in keys and candidate.evaluation.state_key not in states:
            chosen.append(candidate)
            keys.add(candidate.input_key)
            states.add(candidate.evaluation.state_key)
    return tuple(sorted(chosen, key=_primary_rank))


def _with_direction(frame: InputFrame, horizontal: int) -> InputFrame:
    return InputFrame(horizontal < 0, horizontal > 0, frame.jump, frame.jump_trigger)


def _with_jump(frame: InputFrame, jump: bool) -> InputFrame:
    # Edited button holds derive their jump edge naturally. Unedited inputs
    # retain explicit replay triggers byte for byte.
    return InputFrame(frame.left, frame.right, jump, None)


def _mutate(
    parent: PopulationCandidate, donor: PopulationCandidate,
    frame_ranges: tuple[tuple[int, int], ...], mutable_frames: tuple[int, ...],
    rng: random.Random, span: int,
) -> tuple[tuple[InputFrame, ...], str, int]:
    """Make one bounded pulse, correlated edit, jump change or section swap."""
    changed = list(parent.frames)
    start, end = rng.choice(frame_ranges)
    anchor = rng.randint(start, end)
    size = rng.choice((1, 1, 2, 3, 6, 12, 20, 31, span))
    size = max(1, min(size, span, end - anchor + 1))
    operation = rng.randrange(8)
    if operation == 0:
        direction = rng.choice((-1, 0, 1))
        for index in range(anchor, anchor + size):
            changed[index] = _with_direction(changed[index], direction)
        label = f"horizontal pulse {anchor}+{size}={direction:+d}"
    elif operation == 1:
        boundaries = [i for i in range(max(1, start), end + 1)
                      if changed[i - 1].horizontal != changed[i].horizontal]
        if boundaries:
            boundary = rng.choice(boundaries)
            shifted = min(end + 1, max(start, boundary + rng.choice((-span, -3, -2, -1, 1, 2, 3, span))))
            direction = changed[boundary - 1 if shifted > boundary else boundary].horizontal
            for index in range(min(boundary, shifted), max(boundary, shifted)):
                changed[index] = _with_direction(changed[index], direction)
            anchor = min(boundary, shifted)
            label = f"direction boundary {boundary}->{shifted}"
        else:
            changed[anchor] = _with_direction(changed[anchor], rng.choice((-1, 0, 1)))
            label = f"direction edit {anchor}"
    elif operation == 2:
        chosen = rng.sample(mutable_frames, min(len(mutable_frames), rng.choice((2, 2, 3, 4))))
        for index in chosen:
            changed[index] = rng.choice(ALL_INPUT_CHOICES)
        anchor = min(chosen)
        label = "sparse inputs " + ",".join(map(str, sorted(chosen)))
    elif operation == 3:
        # A release inside the editable interval creates a fresh rising edge.
        if anchor > start and changed[anchor - 1].jump:
            changed[anchor - 1] = _with_jump(changed[anchor - 1], False)
        for index in range(anchor, anchor + size):
            changed[index] = _with_jump(changed[index], True)
        label = f"jump insertion {anchor}+{size}"
    elif operation == 4:
        jumps = [i for i in range(start, end + 1) if changed[i].jump]
        if jumps:
            anchor = rng.choice(jumps)
            left = right = anchor
            while left > start and changed[left - 1].jump:
                left -= 1
            while right < end and changed[right + 1].jump:
                right += 1
            for index in range(left, right + 1):
                changed[index] = _with_jump(changed[index], False)
            anchor = left
            label = f"jump removal {left}:{right}"
        else:
            changed[anchor] = _with_jump(changed[anchor], True)
            label = f"jump insertion {anchor}+1"
    elif operation == 5:
        boundaries = [i for i in range(max(1, start), end + 1)
                      if changed[i - 1].jump != changed[i].jump]
        if boundaries:
            boundary = rng.choice(boundaries)
            shifted = min(end + 1, max(start, boundary + rng.choice((-span, -6, -3, -1, 1, 3, 6, span))))
            jump = changed[boundary - 1 if shifted > boundary else boundary].jump
            for index in range(min(boundary, shifted), max(boundary, shifted)):
                changed[index] = _with_jump(changed[index], jump)
            anchor = min(boundary, shifted)
            label = f"jump boundary {boundary}->{shifted}"
        else:
            for index in range(anchor, anchor + size):
                changed[index] = _with_jump(changed[index], not parent.frames[anchor].jump)
            label = f"jump hold {anchor}+{size}"
    elif operation == 6:
        # Equal-duration crossover never shifts the suffix or touches gaps.
        other = rng.randint(anchor, end)
        changed[anchor:other + 1] = donor.frames[anchor:other + 1]
        label = f"section crossover {anchor}:{other}"
    else:
        changed[anchor] = rng.choice(ALL_INPUT_CHOICES)
        label = f"all-input edit {anchor}"
    return tuple(changed), label, anchor


class _SearchContext:
    def __init__(self, level: object, source: tuple[InputFrame, ...], goal: EndpointGoal,
                 ranges: tuple[tuple[int, int], ...], config: PopulationConfig,
                 events: Any = None) -> None:
        self.source = source
        self.goal = goal
        self.ranges = ranges
        self.config = config
        self.mutable_frames = tuple(i for start, end in ranges for i in range(start, end + 1))
        self.mutable = frozenset(self.mutable_frames)
        self.evaluator = EndpointEvaluator(level, goal, source_frames=source,
                                           prefix_frame=ranges[0][0])
        self.cache: OrderedDict[bytes, EndpointEvaluation] = OrderedDict()
        self.events = events
        self.evaluations = 0

    def candidate(self, frames: tuple[InputFrame, ...], history: tuple[str, ...]) -> PopulationCandidate:
        _assert_bounded(self.source, frames, self.mutable)
        key = _input_key(frames)
        evaluation = self.cache.get(key)
        if evaluation is None:
            evaluation = self.evaluator.evaluate(frames)
            self.cache[key] = evaluation
            self.evaluations += 1
            if len(self.cache) > 4096:
                self.cache.popitem(last=False)
        else:
            self.cache.move_to_end(key)
        return PopulationCandidate(frames, evaluation, history[-64:],
                                   sum(a != b for a, b in zip(self.source, frames)), key)


_WORKER_CONTEXT: _SearchContext | None = None


def _initialise_worker(level: object, source: tuple[InputFrame, ...], goal: EndpointGoal,
                       ranges: tuple[tuple[int, int], ...], config: PopulationConfig,
                       events: Any) -> None:
    global _WORKER_CONTEXT
    # The parent handles Ctrl+C and terminates its exact owned processes.
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # Progress is best-effort; the Future carries the authoritative final pool.
    # A late large replay event must not make process exit wait for a feeder
    # flush after the parent has finished draining the progress pipe.
    if events is not None:
        events.cancel_join_thread()
    _WORKER_CONTEXT = _SearchContext(level, source, goal, ranges, config, events)


def _run_worker(job: tuple[int, int, int, tuple[PopulationCandidate, ...]],
                context: _SearchContext | None = None,
                observer: Callable[[PopulationCandidate | None, int, int], None] | None = None,
                ) -> tuple[tuple[PopulationCandidate, ...], int]:
    context = context if context is not None else _WORKER_CONTEXT
    assert context is not None
    round_index, worker_index, seed, parents = job
    cfg = context.config
    # Round-local caching gives resumed campaigns identical counts and avoids
    # dependence on which operating-system process receives the next job.
    context.cache.clear()
    rng = random.Random(seed)
    pool = _select_population(parents, cfg.beam)
    initial_evaluations = context.evaluations
    best = min((c for c in pool if c.evaluation.feasible), key=_primary_rank, default=None)
    last_sent = time.monotonic()
    pending_best: PopulationCandidate | None = None
    spent = 0

    def emit(force: bool = False) -> None:
        nonlocal last_sent, pending_best
        now = time.monotonic()
        if not force and now - last_sent < 1.0:
            return
        count = context.evaluations - initial_evaluations
        if observer is not None:
            observer(pending_best, count, spent)
        elif context.events is not None:
            context.events.put((round_index, worker_index, pending_best, count, spent))
        pending_best = None
        last_sent = now

    def consider(candidate: PopulationCandidate) -> None:
        nonlocal pool, best, pending_best
        if candidate.evaluation.feasible and (best is None or _primary_rank(candidate) < _primary_rank(best)):
            best = pending_best = candidate
            # Serial users get each best immediately; process users at most one
            # compact replay message per second, plus the final best.
            if observer is not None:
                emit(True)
        pool = _select_population((*pool, candidate), cfg.beam)

    while spent < cfg.iterations:
        # Tournament selection favours good endpoints without excluding niches.
        parent = min(rng.sample(pool, min(len(pool), 2)), key=_rank) if rng.random() < 0.65 else rng.choice(pool)
        donor = rng.choice(pool)
        frames, label, anchor = _mutate(parent, donor, context.ranges,
                                        context.mutable_frames, rng, cfg.mutation_span)
        spent += 1
        if frames == parent.frames:
            emit()
            continue
        candidate = context.candidate(frames, (*parent.history, label))
        promising = _rank(candidate) < _rank(parent)
        consider(candidate)
        # Repair changes all buttons and permits a different route. It targets
        # the mutated region and the observed failure/arrival, never reference
        # contacts. Its evaluations consume the same per-worker budget.
        if cfg.repair_steps and (promising or (not candidate.evaluation.feasible and rng.random() < 0.125)):
            centre = min(context.ranges[-1][1], max(anchor, candidate.evaluation.frame))
            repair_frames = [i for i in context.mutable_frames
                             if centre - cfg.repair_lookback <= i <= centre]
            repair_frames += [i for i in context.mutable_frames
                              if anchor - cfg.repair_lookback <= i <= anchor and i not in repair_frames]
            rng.shuffle(repair_frames)
            repairs = 0
            repaired = candidate
            for frame_index in repair_frames:
                choices = list(ALL_INPUT_CHOICES)
                rng.shuffle(choices)
                for choice in choices:
                    if repairs >= cfg.repair_steps or spent >= cfg.iterations:
                        break
                    if repaired.frames[frame_index] == choice:
                        continue
                    altered = list(repaired.frames)
                    altered[frame_index] = choice
                    spent += 1
                    repairs += 1
                    trial = context.candidate(tuple(altered), (*repaired.history,
                                               f"endpoint repair input {frame_index}"))
                    consider(trial)
                    if _rank(trial) < _rank(repaired):
                        repaired = trial
                    emit()
                if repairs >= cfg.repair_steps or spent >= cfg.iterations:
                    break
        emit()
    emit(True)
    return pool, context.evaluations - initial_evaluations


def _json_value(value: object) -> object:
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, (tuple, list)):
        return [_json_value(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return "+inf" if value > 0 else "-inf" if value < 0 else "NaN"
    return value


def _identity(level: object, source: tuple[InputFrame, ...], goal: EndpointGoal,
              ranges: tuple[tuple[int, int], ...], config: PopulationConfig,
              workers: int) -> dict[str, object]:
    configuration = asdict(config)
    # Stop limits may be extended on resume. Seed comes from the saved campaign.
    for key in ("rounds", "stagnation_rounds", "seed", "checkpoint_path", "resume"):
        configuration.pop(key)
    configuration["workers"] = workers
    level_string = getattr(level, "source_level_string", None) or getattr(level, "level_string", None)
    if not isinstance(level_string, str):
        raise ValueError("population checkpoints require a level parsed from a level string")
    digest = hashlib.sha256()
    for path in (Path(__file__), Path(__file__).with_name("nv14_endpoint.py"),
                 Path(__file__).parent / "native" / "_nv14_native.pyx"):
        digest.update(path.read_bytes())
    return {
        "version": OPTIMISER_VERSION,
        "build": optimiser_build_hash(),
        "population_build": digest.hexdigest(),
        "level": hashlib.sha256(level_string.encode()).hexdigest(),
        "simulate_enemies": bool(getattr(level, "simulate_enemies", False)),
        "source": hashlib.sha256(_input_key(source)).hexdigest(),
        "goal": _json_value(goal), "ranges": _json_value(ranges),
        "configuration": _json_value(configuration),
    }


def _write_checkpoint(path: str | Path, identity: dict[str, object], seed: int,
                      population: tuple[PopulationCandidate, ...], rounds: int,
                      evaluations: int, stagnant: int) -> None:
    payload = {"kind": "nv14-local-population", "format": 1, "identity": identity,
               "seed_strategy": "sha256-round-worker-v1", "seed": seed,
               "rounds": rounds, "evaluations": evaluations, "stagnant_rounds": stagnant,
               "population": [{"frames": list(c.input_key), "history": list(c.history),
                               "score": _json_value(c.evaluation.score),
                               "secondary_score": _json_value(c.evaluation.secondary_score),
                               "secondary_value": _json_value(c.evaluation.secondary_value),
                               "feasible": c.evaluation.feasible,
                               "state_sha256": hashlib.sha256(c.evaluation.state_key).hexdigest(),
                               "frame": c.evaluation.frame} for c in population]}
    envelope = {"payload": payload, "sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         prefix=f".{path.name}.", suffix=".tmp",
                                         dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(envelope, stream, allow_nan=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _read_checkpoint(path: str | Path, identity: dict[str, object], context: _SearchContext,
                     ) -> tuple[int, tuple[PopulationCandidate, ...], int, int, int]:
    try:
        envelope = json.loads(Path(path).read_text(encoding="utf-8"))
        payload = envelope["payload"]
        if envelope["sha256"] != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
            raise ValueError("population checkpoint integrity hash does not match")
        if payload["kind"] != "nv14-local-population" or payload["format"] != 1:
            raise ValueError("incompatible population checkpoint format")
        if payload["identity"] != identity:
            raise ValueError("population checkpoint level, source, goal, ranges, configuration or build differs")
        if payload["seed_strategy"] != "sha256-round-worker-v1":
            raise ValueError("unsupported population checkpoint seed strategy")
        for field in ("seed", "rounds", "evaluations", "stagnant_rounds"):
            if type(payload[field]) is not int or payload[field] < 0:
                raise ValueError(f"population checkpoint {field} must be a nonnegative integer")
        if not isinstance(payload["population"], list) or not payload["population"]:
            raise ValueError("population checkpoint has an empty population")
        population = []
        for item in payload["population"]:
            history = item["history"]
            if not isinstance(history, list) or not all(isinstance(x, str) for x in history):
                raise ValueError("population checkpoint history is invalid")
            candidate = context.candidate(_decode_frames(item["frames"]), tuple(history))
            if (_json_value(candidate.evaluation.score) != item["score"]
                    or _json_value(candidate.evaluation.secondary_score) != item["secondary_score"]
                    or _json_value(candidate.evaluation.secondary_value) != item["secondary_value"]
                    or candidate.evaluation.feasible != item["feasible"]
                    or candidate.evaluation.frame != item["frame"]
                    or hashlib.sha256(candidate.evaluation.state_key).hexdigest() != item["state_sha256"]):
                raise ValueError("population checkpoint candidate failed endpoint re-verification")
            population.append(candidate)
        if len(population) > context.config.beam:
            raise ValueError("population checkpoint exceeds configured beam")
        return payload["seed"], tuple(population), payload["rounds"], payload["evaluations"], payload["stagnant_rounds"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read population checkpoint {path}: {exc}") from exc


def optimise_local_population(
    level: object, frames: Sequence[InputFrame], *, goal: EndpointGoal,
    frame_ranges: Sequence[tuple[int, int]], config: PopulationConfig,
    best_callback: Callable[[PopulationCandidate], object] | None = None,
    progress: Callable[[str], object] | None = None,
) -> PopulationResult:
    """Search fixed replay segments; return only feasible, distinct endpoints.

    ``iterations`` is the proposal budget per worker per round, including
    repair proposals. ``rounds=0`` runs until ``stagnation_rounds``; zero for
    both limits runs until interrupted. Checkpoints commit fully joined rounds.
    """
    source = tuple(editable_frames(frames))
    ranges = _normalise_local_frame_ranges(0, 0, frame_ranges)
    if not source or ranges[-1][1] >= len(source):
        raise ValueError("population editable ranges must lie inside the replay")
    if ranges[-1][1] > goal.target_frame:
        raise ValueError("population editable ranges cannot extend beyond the target frame")
    for name in ("iterations", "beam", "top_results", "mutation_span"):
        if type(getattr(config, name)) is not int or getattr(config, name) < 1:
            raise ValueError(f"population {name} must be a positive integer")
    for name in ("rounds", "stagnation_rounds", "workers", "repair_steps", "repair_lookback"):
        if type(getattr(config, name)) is not int or getattr(config, name) < 0:
            raise ValueError(f"population {name} must be a nonnegative integer")
    if config.top_results > config.beam:
        raise ValueError("population top_results cannot exceed beam")
    if config.resume and not config.checkpoint_path:
        raise ValueError("population resume requires a checkpoint path")
    worker_count = config.workers or _automatic_jump_worker_count()
    context = _SearchContext(level, source, goal, ranges, config)
    baseline_candidate = context.candidate(source, ())
    baseline = baseline_candidate.evaluation
    if ranges[0][0] and not (
        goal.objective == "earliest-arrival" and baseline.feasible
        and baseline.frame < ranges[0][0]
    ):
        prefix_goal = replace(goal, target_frame=ranges[0][0] - 1, objective="max-x",
                              target=None, target_region=None, arrival_start=0, secondary_objective=None,
                              x_window=None, y_window=None, vx_window=None, vy_window=None,
                              required_interactions=())
        prefix = EndpointEvaluator(level, prefix_goal).evaluate(source)
        if prefix.dead:
            raise ValueError("the immutable prefix dies before the editable ranges; move the range start earlier")
        if prefix.violated_interactions:
            labels = ", ".join(sorted(item.selector for item in prefix.violated_interactions))
            raise ValueError(f"the immutable prefix already triggered forbidden interaction(s): {labels}")
    population = (baseline_candidate,)
    rounds = stagnant = 0
    evaluations = 1
    seed = random.SystemRandom().getrandbits(64) if config.seed == "random" else (0 if config.seed is None else config.seed)
    if type(seed) is not int or seed < 0:
        raise ValueError("population seed must be a nonnegative integer or 'random'")
    identity = _identity(level, source, goal, ranges, config, worker_count) if config.checkpoint_path else None
    if config.resume:
        seed, population, rounds, evaluations, stagnant = _read_checkpoint(config.checkpoint_path, identity, context)
        if type(config.seed) is int and config.seed != seed:
            raise ValueError("population checkpoint seed differs from the explicitly configured seed")
    if progress:
        progress(f"[local:population] seed {seed}; {worker_count} worker(s); "
                 f"{len(context.mutable_frames)} editable frames; beam {config.beam}")
    best: PopulationCandidate | None = None

    def accept(candidate: PopulationCandidate | None) -> None:
        nonlocal best
        if candidate is None or not candidate.evaluation.feasible:
            return
        if best is None or _primary_rank(candidate) < _primary_rank(best):
            if best_callback is not None and best_callback(candidate) is False:
                raise ValueError("population best candidate failed output verification")
            best = candidate

    for candidate in population:
        accept(candidate)
    executor: ProcessPoolExecutor | None = None
    events: Any = None
    interrupted = False
    partial: list[PopulationCandidate] = []
    last_progress = time.monotonic()
    task_counts: dict[int, int] = {}

    def best_summary() -> str:
        if best is None:
            return "no feasible endpoint"
        evaluation = best.evaluation
        summary = f"best {evaluation.score:g} at frame {evaluation.frame}"
        if goal.secondary_objective is not None:
            summary += f"; secondary {goal.secondary_objective}={evaluation.secondary_value:.15g}"
        return summary

    def report(worker: int, candidate: PopulationCandidate | None, count: int, spent: int) -> None:
        nonlocal last_progress
        task_counts[worker] = max(task_counts.get(worker, 0), count)
        if candidate is not None:
            accept(candidate)
            partial.append(candidate)
            if len(partial) > config.beam * 4:
                partial[:] = _select_population(partial, config.beam)
        if progress and time.monotonic() - last_progress >= 5.0:
            progress(f"[local:population] round {rounds + 1}; {evaluations + sum(task_counts.values())} evaluations; {best_summary()}")
            last_progress = time.monotonic()

    try:
        if worker_count > 1:
            mp = multiprocessing.get_context("spawn")
            events = mp.Queue()
            executor = ProcessPoolExecutor(max_workers=worker_count, mp_context=mp,
                                          initializer=_initialise_worker,
                                          initargs=(level, source, goal, ranges, config, events))
        while (config.rounds == 0 or rounds < config.rounds) and (
            config.stagnation_rounds == 0 or stagnant < config.stagnation_rounds
        ):
            prior_objective = None if best is None else best.evaluation.objective_key
            partial.clear()
            task_counts.clear()
            jobs = []
            for worker in range(worker_count):
                digest = hashlib.sha256(f"{seed}:{rounds + 1}:{worker}".encode()).digest()
                jobs.append((rounds + 1, worker, int.from_bytes(digest[:8], "big"), population))
            if executor is None:
                # Cache lifetime is one round in both serial and process mode,
                # so a resumed run has the same proposal and evaluation counts.
                context.cache.clear()
                outputs = [_run_worker(jobs[0], context,
                           lambda candidate, count, spent: report(0, candidate, count, spent))]
            else:
                futures = {executor.submit(_run_worker, job): job[1] for job in jobs}
                completed: dict[int, tuple[tuple[PopulationCandidate, ...], int]] = {}
                while futures:
                    done, _ = wait(futures, timeout=0.25, return_when=FIRST_COMPLETED)
                    while True:
                        try:
                            round_event, worker, candidate, count, spent = events.get_nowait()
                        except queue.Empty:
                            break
                        if round_event == rounds + 1:
                            report(worker, candidate, count, spent)
                    for future in done:
                        worker = futures.pop(future)
                        completed[worker] = future.result()
                        pool, count = completed[worker]
                        task_counts[worker] = count
                        for candidate in pool:
                            accept(candidate)
                # Merge in worker index order, independent of process timing.
                outputs = [completed[index] for index in range(worker_count)]
            evaluations += sum(count for _, count in outputs)
            joined = [*population, *(candidate for pool, _ in outputs for candidate in pool)]
            if best is not None:
                joined.append(best)
            population = _select_population(joined, config.beam)
            rounds += 1
            objective = None if best is None else best.evaluation.objective_key
            stagnant = 0 if objective is not None and (prior_objective is None or objective < prior_objective) else stagnant + 1
            if config.checkpoint_path:
                _write_checkpoint(config.checkpoint_path, identity, seed, population, rounds, evaluations, stagnant)
            if progress:
                progress(f"[local:population] round {rounds}; {evaluations} evaluations; {best_summary()}; stagnant {stagnant}")
    except KeyboardInterrupt:
        interrupted = True
        evaluations += sum(task_counts.values())
        population = _select_population((*population, *partial, *((best,) if best else ())), config.beam)
        if progress:
            progress("[local:population] interrupted; returning verified feasible endpoints; checkpoint retains the last complete round")
        if executor is not None:
            _stop_local_executor_for_exception(executor)
            executor = None
    except BaseException:
        if executor is not None:
            _stop_local_executor_for_exception(executor)
            executor = None
        raise
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
        if events is not None:
            events.close()
            events.join_thread()
    results = _diverse_results((*population, *((best,) if best else ())), config.top_results)
    return PopulationResult(results, baseline, rounds, evaluations, stagnant, worker_count, seed, interrupted)

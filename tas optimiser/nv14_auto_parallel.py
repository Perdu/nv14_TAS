"""Population-based process parallelism for :mod:`nv14_auto`.

Each worker runs one complete, independent Auto search. Completed searches
form a small evolutionary population: the best half survive each round and
seed the next one. The coordinator may speculatively start one generation
ahead as worker slots become free, then cancels descendants whose provisional
parent is pruned when the round is finalised.
"""

from __future__ import annotations

import math
import multiprocessing
import os
import signal
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, fields, replace
from queue import Empty
from typing import Any

from nv14_auto import (
    AUTO_OBJECTIVE_HIGHSCORE,
    AutoCandidate,
    AutoConfig,
    AutoProgress,
    AutoResult,
    AutoStats,
    auto_objective_value,
    optimise_autonomous,
)
from nv14_engine import InputFrame, Level

ProgressCallback = Callable[[AutoProgress], None]
BestCallback = Callable[[AutoCandidate], None]
StatusCallback = Callable[[str], None]
SearchFunction = Callable[..., AutoResult]


@dataclass(frozen=True, slots=True)
class AutoCampaignResult:
    """Final result and lifecycle details for a population Auto campaign."""

    result: AutoResult
    worker_count: int
    requested_runs: int
    completed_runs: int
    completed_searches: int
    interrupted: bool = False


@dataclass(frozen=True, slots=True)
class _AutoWorkerContext:
    level: Level
    config: AutoConfig


@dataclass(frozen=True, slots=True)
class _AutoWorkerTask:
    frames: tuple[InputFrame, ...]
    seed: int
    run_index: int
    worker_index: int
    task_id: int = 0
    parent_member_id: int = 0
    offspring_index: int = 1
    cancel_slot: int = -1


@dataclass(frozen=True, slots=True)
class _AutoWorkerResult:
    result: AutoResult
    seed: int
    run_index: int
    worker_index: int
    task_id: int = 0
    parent_member_id: int = 0
    offspring_index: int = 1


@dataclass(frozen=True, slots=True)
class _AutoWorkerCheckpoint:
    candidate: AutoCandidate
    seed: int
    run_index: int
    worker_index: int
    macro_evaluations: int = 0
    task_id: int = 0
    parent_member_id: int = 0
    offspring_index: int = 1


@dataclass(frozen=True, slots=True)
class _AutoPopulationMember:
    member_id: int
    result: AutoResult
    parent_member_id: int | None
    generation: int
    mutations: tuple[str, ...]


@dataclass(slots=True)
class _AutoTaskRecord:
    task_id: int
    generation: int
    parent_member_id: int
    offspring_index: int
    seed: int
    authoritative: bool = False
    worker_index: int = 0
    cancel_slot: int = -1
    future: Future[_AutoWorkerResult] | None = None
    output: _AutoWorkerResult | None = None
    cancelled: bool = False


class _AutoWorkerCancelled(Exception):
    """Internal cooperative-cancellation signal for an Auto worker."""


_AUTO_WORKER_CONTEXT: _AutoWorkerContext | None = None
_AUTO_WORKER_STOP_EVENT: Any | None = None
_AUTO_WORKER_CHECKPOINT_QUEUE: Any | None = None
_AUTO_WORKER_CANCEL_TOKENS: Any | None = None


def automatic_auto_worker_count() -> int:
    """Return the default number of independent CPU-bound Auto searches."""
    process_cpu_count = getattr(os, "process_cpu_count", None)
    if process_cpu_count is not None:
        available = process_cpu_count()
    else:
        if hasattr(os, "sched_getaffinity"):
            try:
                available = len(os.sched_getaffinity(0))
            except OSError:
                available = os.cpu_count()
        else:
            available = os.cpu_count()
    return min(8, max(1, available or 1))


def derive_auto_search_seed(
    base_seed: int,
    run_index: int,
    worker_index: int,
    worker_count: int,
) -> int:
    """Derive a unique deterministic seed for one worker stream.

    The first stream deliberately retains ``base_seed``, so
    ``--workers 1 --auto-runs 1`` reproduces v2.45's seeded serial search.
    Later streams form a full-period 64-bit Weyl sequence and cannot collide
    until the counter itself wraps after 2**64 searches.
    """
    if run_index < 1:
        raise ValueError("run_index must be positive")
    if worker_count < 1 or not 1 <= worker_index <= worker_count:
        raise ValueError("worker_index must be within worker_count")
    mask = (1 << 64) - 1
    stream_index = (run_index - 1) * worker_count + worker_index - 1
    if stream_index == 0:
        return base_seed
    return ((base_seed & mask) + 0x9E3779B97F4A7C15 * stream_index) & mask


def _initialise_auto_worker(
    context: _AutoWorkerContext,
    stop_event: Any,
    checkpoint_queue: Any,
    cancel_tokens: Any | None = None,
) -> None:
    """Install immutable worker state and let only the parent handle Ctrl+C."""
    global _AUTO_WORKER_CONTEXT
    global _AUTO_WORKER_STOP_EVENT
    global _AUTO_WORKER_CHECKPOINT_QUEUE
    global _AUTO_WORKER_CANCEL_TOKENS
    _AUTO_WORKER_CONTEXT = context
    _AUTO_WORKER_STOP_EVENT = stop_event
    _AUTO_WORKER_CHECKPOINT_QUEUE = checkpoint_queue
    _AUTO_WORKER_CANCEL_TOKENS = cancel_tokens
    if multiprocessing.current_process().name != "MainProcess":
        signal.signal(signal.SIGINT, signal.SIG_IGN)


def _worker_cancelled(task: _AutoWorkerTask | None = None) -> bool:
    event = _AUTO_WORKER_STOP_EVENT
    if event is not None and event.is_set():
        return True
    tokens = _AUTO_WORKER_CANCEL_TOKENS
    if task is None or tokens is None or task.cancel_slot < 0:
        return False
    try:
        return int(tokens[task.cancel_slot]) != task.task_id
    except (IndexError, TypeError):
        return False


def _run_auto_worker(task: _AutoWorkerTask) -> _AutoWorkerResult:
    context = _AUTO_WORKER_CONTEXT
    if context is None:
        raise RuntimeError("Auto worker was not initialised")

    last_macro_evaluations = 0

    def check_cancelled(update: AutoProgress | None = None) -> None:
        nonlocal last_macro_evaluations
        if update is not None:
            last_macro_evaluations = update.macro_evaluations
        if _worker_cancelled(task):
            raise _AutoWorkerCancelled

    def checkpoint(candidate: AutoCandidate) -> None:
        check_cancelled()
        checkpoint_queue = _AUTO_WORKER_CHECKPOINT_QUEUE
        if checkpoint_queue is not None:
            checkpoint_queue.put(
                _AutoWorkerCheckpoint(
                    candidate=candidate,
                    seed=task.seed,
                    run_index=task.run_index,
                    worker_index=task.worker_index,
                    macro_evaluations=last_macro_evaluations,
                    task_id=task.task_id,
                    parent_member_id=task.parent_member_id,
                    offspring_index=task.offspring_index,
                )
            )

    check_cancelled()
    result = optimise_autonomous(
        context.level,
        task.frames,
        replace(context.config, seed=task.seed),
        progress=check_cancelled,
        best_callback=checkpoint,
    )
    return _AutoWorkerResult(
        result=replace(result, beam=()),
        seed=task.seed,
        run_index=task.run_index,
        worker_index=task.worker_index,
        task_id=task.task_id,
        parent_member_id=task.parent_member_id,
        offspring_index=task.offspring_index,
    )


def _exit_proximity(candidate: AutoCandidate) -> float:
    proximity = candidate.evaluation.pre_finish_exit_distance
    if proximity is None or not math.isfinite(proximity):
        return float("inf")
    return proximity


def auto_candidate_outcome_key(
    candidate: AutoCandidate,
    objective: str,
) -> tuple[int | float, ...]:
    """Rank completed persisted outcomes across independent Auto searches.

    Internal beam tie-breakers such as generation and edit count are local to
    one search.  Across workers, the portable persisted ordering is objective
    value first and pre-sentinel exit proximity second.  An exact tie is kept
    by the coordinator, preserving the already-established global incumbent.
    """
    evaluation = candidate.evaluation
    if not candidate.output_valid or evaluation.finish_tick is None:
        return (1, float("inf"), float("inf"))
    proximity = _exit_proximity(candidate)
    if objective == AUTO_OBJECTIVE_HIGHSCORE:
        value = auto_objective_value(evaluation, objective)
        assert value is not None
        return (0, -value, proximity)
    return (0, evaluation.finish_tick, proximity)


def auto_result_outcome_key(result: AutoResult) -> tuple[int | float, ...]:
    return auto_candidate_outcome_key(result.best, result.objective)


def _derive_auto_task_seed(base_seed: int, task_id: int) -> int:
    """Return a unique 64-bit seed for a dynamically scheduled worker task."""
    if task_id < 1:
        raise ValueError("task_id must be positive")
    if task_id == 1:
        return base_seed
    mask = (1 << 64) - 1
    return ((base_seed & mask) + 0x9E3779B97F4A7C15 * (task_id - 1)) & mask


def _population_survivor_count(worker_count: int) -> int:
    """Keep the best half of a population, rounding odd sizes upward."""
    return max(1, (worker_count + 1) // 2)


def _select_population_survivors(
    members: Sequence[_AutoPopulationMember],
    survivor_count: int,
    *,
    enforce_parent_diversity: bool,
) -> tuple[_AutoPopulationMember, ...]:
    """Select ranked survivors with a one-generation diversity constraint."""
    ranked = sorted(members, key=lambda member: auto_result_outcome_key(member.result))
    survivor_count = min(max(0, survivor_count), len(ranked))
    if survivor_count == 0:
        return ()
    if not enforce_parent_diversity:
        return tuple(ranked[:survivor_count])
    available_parents = {member.parent_member_id for member in ranked}
    min_distinct = min(3, survivor_count, len(available_parents))
    selected: list[_AutoPopulationMember] = []
    selected_parents: set[int | None] = set()
    for member in ranked:
        if len(selected) >= survivor_count:
            break
        remaining_after = survivor_count - len(selected) - 1
        parent_is_new = member.parent_member_id not in selected_parents
        distinct_after = len(selected_parents) + int(parent_is_new)
        still_needed = max(0, min_distinct - distinct_after)
        if remaining_after < still_needed:
            continue
        selected.append(member)
        selected_parents.add(member.parent_member_id)
    if len(selected) != survivor_count:
        chosen = {member.member_id for member in selected}
        selected.extend(member for member in ranked if member.member_id not in chosen)
        selected = selected[:survivor_count]
    return tuple(selected)


def _offspring_quota_by_parent(
    survivors: Sequence[_AutoPopulationMember],
    worker_count: int,
) -> dict[int, int]:
    """Distribute the next population as evenly as possible over survivors."""
    if not survivors:
        return {}
    base, remainder = divmod(worker_count, len(survivors))
    return {
        member.member_id: base + (1 if rank < remainder else 0)
        for rank, member in enumerate(survivors)
    }


def _prune_campaign_history(
    records: dict[int, _AutoTaskRecord],
    records_by_key: dict[tuple[int, int, int], _AutoTaskRecord],
    members: dict[int, _AutoPopulationMember],
    current_task_ids: set[int],
    active: dict[Future[_AutoWorkerResult], _AutoTaskRecord],
) -> None:
    """Release completed generations while preserving live scheduler state.

    A retained task needs its immediate parent member for submission,
    checkpoints, and mutation ancestry. A completed retained task also needs
    its own member for population selection. Everything older has already
    contributed to the aggregate counters and campaign-wide incumbent and is
    never queried by a later generation.

    Cancelled speculative work can remain active until its worker observes the
    cancellation token, so keep those records and parents until the future has
    been reaped as well.
    """
    retained_task_ids = set(current_task_ids)
    retained_task_ids.update(record.task_id for record in active.values())

    retained_member_ids: set[int] = set()
    for task_id in retained_task_ids:
        record = records[task_id]
        retained_member_ids.add(record.parent_member_id)
        if record.output is not None:
            retained_member_ids.add(task_id)

    for task_id in tuple(records):
        if task_id not in retained_task_ids:
            del records[task_id]
    for key, record in tuple(records_by_key.items()):
        if record.task_id not in retained_task_ids:
            del records_by_key[key]
    for member_id in tuple(members):
        if member_id not in retained_member_ids:
            del members[member_id]


def _sum_stats(left: AutoStats, right: AutoStats) -> AutoStats:
    return AutoStats(
        **{
            field.name: getattr(left, field.name) + getattr(right, field.name)
            for field in fields(AutoStats)
        }
    )


def _annotated_mutations(
    output: _AutoWorkerResult | _AutoWorkerCheckpoint,
) -> tuple[str, ...]:
    mutations = (
        output.result.best.mutations
        if isinstance(output, _AutoWorkerResult)
        else output.candidate.mutations
    )
    if not mutations:
        return ()
    return (
        f"parallel round {output.run_index}, worker {output.worker_index}, seed {output.seed}",
        *mutations,
    )


def _result_from_checkpoint(
    checkpoint: _AutoWorkerCheckpoint,
    template: AutoResult,
) -> AutoResult:
    candidate = checkpoint.candidate
    evaluation = candidate.evaluation
    if evaluation.finish_tick is None:
        raise RuntimeError("Auto worker checkpoint did not complete")
    objective_value = auto_objective_value(evaluation, template.objective)
    if objective_value is None:
        raise RuntimeError("Auto worker checkpoint has no objective value")
    return replace(
        template,
        frames=candidate.frames,
        finish_tick=evaluation.finish_tick,
        best=candidate,
        beam=(),
        gold_mask=evaluation.final_gold_mask,
        gold_bonus_ticks=evaluation.gold_bonus_ticks,
        objective_value=objective_value,
    )


def _compose_campaign_result(
    initial: AutoResult,
    current: AutoResult,
    aggregate_stats: AutoStats,
    mutations: tuple[str, ...],
    *,
    worker_count: int,
    requested_runs: int,
    completed_runs: int,
    completed_searches: int,
    interrupted: bool,
) -> AutoCampaignResult:
    diagnostics = (
        "parallel Auto campaign: "
        f"{worker_count} worker search(es), {completed_runs} complete round(s), "
        f"{completed_searches} completed search(es)"
        + ("; interrupted" if interrupted else ""),
        f"parallel campaign final: {initial.finish_tick}->{current.finish_tick}",
        *current.diagnostics,
    )
    best = replace(current.best, mutations=mutations)
    result = replace(
        current,
        baseline_finish_tick=initial.baseline_finish_tick,
        baseline_gold_mask=initial.baseline_gold_mask,
        baseline_gold_bonus_ticks=initial.baseline_gold_bonus_ticks,
        baseline_objective_value=initial.baseline_objective_value,
        best=best,
        stats=aggregate_stats,
        diagnostics=diagnostics,
        beam=(),
    )
    return AutoCampaignResult(
        result=result,
        worker_count=worker_count,
        requested_runs=requested_runs,
        completed_runs=completed_runs,
        completed_searches=completed_searches,
        interrupted=interrupted,
    )


def _close_checkpoint_queue(checkpoint_queue: Any) -> None:
    try:
        checkpoint_queue.close()
        checkpoint_queue.join_thread()
    except (OSError, ValueError):
        pass


def _stop_executor(
    executor: ProcessPoolExecutor,
    futures: Sequence[Future[_AutoWorkerResult]],
    stop_event: Any,
) -> None:
    """Cooperatively stop workers, then terminate any unresponsive process."""
    stop_event.set()
    for future in futures:
        future.cancel()

    _done, pending = wait(futures, timeout=2.0)
    if not pending:
        executor.shutdown(wait=True, cancel_futures=True)
        return

    terminate_workers = getattr(executor, "terminate_workers", None)
    if callable(terminate_workers):
        terminate_workers()
        return

    # Python 3.11-3.13 have no public immediate ProcessPool stop operation.
    # These are the executor's own child Process objects; terminate only those
    # exact resolved processes, then let shutdown join its management thread.
    processes = tuple(getattr(executor, "_processes", {}).values())
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(timeout=2.0)
    executor.shutdown(wait=True, cancel_futures=True)


def optimise_autonomous_campaign(
    level: Level,
    source_frames: Sequence[InputFrame],
    config: AutoConfig,
    *,
    workers: int = 0,
    runs: int = 1,
    progress: ProgressCallback | None = None,
    best_callback: BestCallback | None = None,
    status: StatusCallback | None = None,
    search: SearchFunction = optimise_autonomous,
) -> AutoCampaignResult:
    """Run independent Auto searches as an asynchronous survivor population.

    ``workers=0`` selects up to eight available CPUs. ``runs=0`` repeats
    indefinitely until Ctrl+C. Each completed round keeps the best half of the
    population, with one-generation parent diversity from round two onward.
    Free slots may speculatively start the next generation before all current
    workers finish.
    """
    if workers < 0:
        raise ValueError("workers must be zero (auto) or a positive integer")
    if runs < 0:
        raise ValueError("auto runs must be non-negative")
    if runs == 0 and config.iterations == 0:
        raise ValueError("indefinite Auto runs require a positive iteration budget")
    worker_count = automatic_auto_worker_count() if workers == 0 else workers
    if worker_count < 1:
        raise ValueError("Auto requires at least one worker")

    # Canonicalise and verify the source once in the parent.  Every worker then
    # starts from this exact trimmed replay rather than independently retaining
    # unused source inputs.
    def initial_progress(update: AutoProgress) -> None:
        if progress is None:
            return
        if config.iterations > 0 and update.phase == "complete":
            return
        progress(
            replace(update, budget=config.iterations)
            if config.iterations > 0
            else update
        )

    initial = search(
        level,
        source_frames,
        replace(config, iterations=0),
        progress=initial_progress if progress is not None else None,
        best_callback=best_callback,
    )
    if config.iterations == 0:
        return _compose_campaign_result(
            initial,
            initial,
            AutoStats(),
            initial.best.mutations,
            worker_count=worker_count,
            requested_runs=runs,
            completed_runs=0,
            completed_searches=0,
            interrupted=False,
        )

    current = initial
    aggregate_stats = AutoStats()
    committed_mutations = initial.best.mutations
    completed_runs = 0
    completed_searches = 0
    run_index = 1
    run_limit = runs if runs > 0 else None

    if worker_count == 1:
        while run_limit is None or run_index <= run_limit:
            seed = derive_auto_search_seed(config.seed, run_index, 1, 1)
            if status is not None:
                suffix = f"/{run_limit}" if run_limit is not None else ""
                status(
                    f"[auto:parallel] round {run_index}{suffix}: "
                    f"starting serial search with seed {seed}"
                )
            live_checkpoint: _AutoWorkerCheckpoint | None = None

            def serial_checkpoint(
                candidate: AutoCandidate,
                *,
                _seed: int = seed,
                _run_index: int = run_index,
            ) -> None:
                nonlocal live_checkpoint
                update = _AutoWorkerCheckpoint(candidate, _seed, _run_index, 1)
                if live_checkpoint is None or auto_candidate_outcome_key(
                    candidate, config.objective
                ) < auto_candidate_outcome_key(
                    live_checkpoint.candidate, config.objective
                ):
                    live_checkpoint = update
                    if best_callback is not None:
                        best_callback(candidate)

            try:

                def serial_progress(update: AutoProgress) -> None:
                    if progress is not None and update.phase != "baseline":
                        progress(update)

                result = search(
                    level,
                    current.frames,
                    replace(config, seed=seed),
                    progress=serial_progress if progress is not None else None,
                    best_callback=serial_checkpoint,
                )
            except KeyboardInterrupt:
                interrupted_result = (
                    _result_from_checkpoint(live_checkpoint, current)
                    if live_checkpoint is not None
                    and auto_candidate_outcome_key(
                        live_checkpoint.candidate, config.objective
                    )
                    < auto_result_outcome_key(current)
                    else current
                )
                interrupted_mutations = committed_mutations
                if interrupted_result is not current and live_checkpoint is not None:
                    interrupted_mutations += _annotated_mutations(live_checkpoint)
                if status is not None:
                    status(
                        "[auto:interrupt] Ctrl+C received; retaining the best "
                        "verified result produced so far"
                    )
                return _compose_campaign_result(
                    initial,
                    interrupted_result,
                    aggregate_stats,
                    interrupted_mutations,
                    worker_count=worker_count,
                    requested_runs=runs,
                    completed_runs=completed_runs,
                    completed_searches=completed_searches,
                    interrupted=True,
                )

            completed_searches += 1
            aggregate_stats = _sum_stats(aggregate_stats, result.stats)
            if auto_result_outcome_key(result) < auto_result_outcome_key(current):
                current = result
                committed_mutations += _annotated_mutations(
                    _AutoWorkerResult(result, seed, run_index, 1)
                )
            completed_runs += 1
            if status is not None:
                status(
                    f"[auto:parallel] round {run_index} complete: "
                    f"best finish {current.finish_tick}; restarting from winner"
                )
            run_index += 1

        return _compose_campaign_result(
            initial,
            current,
            aggregate_stats,
            committed_mutations,
            worker_count=worker_count,
            requested_runs=runs,
            completed_runs=completed_runs,
            completed_searches=completed_searches,
            interrupted=False,
        )

    mp_context = multiprocessing.get_context()
    stop_event = mp_context.Event()
    checkpoint_queue = mp_context.Queue()
    cancel_tokens = mp_context.Array("Q", worker_count, lock=False)
    executor: ProcessPoolExecutor | None = None
    active: dict[Future[_AutoWorkerResult], _AutoTaskRecord] = {}
    free_slots: set[int] = set(range(worker_count))
    records: dict[int, _AutoTaskRecord] = {}
    records_by_key: dict[tuple[int, int, int], _AutoTaskRecord] = {}
    source_member = _AutoPopulationMember(
        member_id=0,
        result=initial,
        parent_member_id=None,
        generation=0,
        mutations=initial.best.mutations,
    )
    members: dict[int, _AutoPopulationMember] = {0: source_member}
    next_task_id = 1
    survivor_count = _population_survivor_count(worker_count)
    current = initial
    committed_mutations = initial.best.mutations
    checkpoint_key = auto_result_outcome_key(current)

    def create_record(
        generation: int,
        parent_member_id: int,
        offspring_index: int,
        *,
        authoritative: bool,
    ) -> _AutoTaskRecord:
        nonlocal next_task_id
        key = (generation, parent_member_id, offspring_index)
        existing = records_by_key.get(key)
        if existing is not None:
            if authoritative:
                existing.authoritative = True
            return existing
        task_id = next_task_id
        next_task_id += 1
        record = _AutoTaskRecord(
            task_id=task_id,
            generation=generation,
            parent_member_id=parent_member_id,
            offspring_index=offspring_index,
            seed=_derive_auto_task_seed(config.seed, task_id),
            authoritative=authoritative,
        )
        records[task_id] = record
        records_by_key[key] = record
        return record

    def parent_mutations(record: _AutoTaskRecord) -> tuple[str, ...]:
        return members[record.parent_member_id].mutations

    def member_from_output(
        record: _AutoTaskRecord,
        output: _AutoWorkerResult,
    ) -> _AutoPopulationMember:
        member = members.get(record.task_id)
        if member is not None:
            return member
        member = _AutoPopulationMember(
            member_id=record.task_id,
            result=output.result,
            parent_member_id=record.parent_member_id,
            generation=record.generation,
            mutations=parent_mutations(record) + _annotated_mutations(output),
        )
        members[record.task_id] = member
        return member

    def accept_checkpoint(update: _AutoWorkerCheckpoint) -> None:
        nonlocal current, committed_mutations, checkpoint_key
        key = auto_candidate_outcome_key(update.candidate, config.objective)
        if key >= checkpoint_key:
            return
        record = records.get(update.task_id)
        if record is None:
            return
        checkpoint_key = key
        parent = members[record.parent_member_id]
        current = _result_from_checkpoint(update, parent.result)
        committed_mutations = parent.mutations + _annotated_mutations(update)
        if status is not None:
            status(
                f"[auto:parallel] round {update.run_index}, worker "
                f"{update.worker_index}, seed {update.seed}: new global best; "
                f"{update.macro_evaluations:,} evaluations"
            )
        if best_callback is not None:
            best_callback(update.candidate)

    def drain_checkpoints() -> None:
        while True:
            try:
                update = checkpoint_queue.get_nowait()
            except Empty:
                return
            except (EOFError, OSError, ValueError):
                return
            accept_checkpoint(update)

    def submit_record(record: _AutoTaskRecord) -> bool:
        if executor is None or not free_slots:
            return False
        if record.future is not None or record.output is not None or record.cancelled:
            return False
        slot = min(free_slots)
        free_slots.remove(slot)
        record.cancel_slot = slot
        record.worker_index = slot + 1
        cancel_tokens[slot] = record.task_id
        task = _AutoWorkerTask(
            frames=members[record.parent_member_id].result.frames,
            seed=record.seed,
            run_index=record.generation,
            worker_index=record.worker_index,
            task_id=record.task_id,
            parent_member_id=record.parent_member_id,
            offspring_index=record.offspring_index,
            cancel_slot=slot,
        )
        future = executor.submit(_run_auto_worker, task)
        record.future = future
        active[future] = record
        return True

    def cancel_record(record: _AutoTaskRecord) -> None:
        if record.cancelled or record.output is not None:
            return
        record.cancelled = True
        if record.cancel_slot >= 0:
            cancel_tokens[record.cancel_slot] = 0
        future = record.future
        if future is not None and future.cancel():
            active.pop(future, None)
            if record.cancel_slot >= 0:
                free_slots.add(record.cancel_slot)
            record.future = None
            record.cancel_slot = -1

    def record_completed_output(
        record: _AutoTaskRecord,
        output: _AutoWorkerResult,
    ) -> None:
        nonlocal aggregate_stats, completed_searches
        nonlocal current, committed_mutations, checkpoint_key
        record.output = output
        completed_searches += 1
        aggregate_stats = _sum_stats(aggregate_stats, output.result.stats)
        member = member_from_output(record, output)
        key = auto_result_outcome_key(output.result)
        if key < checkpoint_key:
            checkpoint_key = key
            current = output.result
            committed_mutations = member.mutations
            if status is not None:
                status(
                    f"[auto:parallel] round {output.run_index}, worker "
                    f"{output.worker_index}, seed {output.seed}: new global best; "
                    f"{output.result.stats.macro_evaluations:,} evaluations"
                )
            if best_callback is not None:
                best_callback(output.result.best)
        if status is not None:
            status(
                f"[auto:parallel] round {record.generation}: worker "
                f"{output.worker_index}/{worker_count} finished "
                f"(seed {output.seed}, finish {output.result.finish_tick}, "
                f"{output.result.stats.macro_evaluations:,} evaluations)"
            )

    def reap_done(done: Sequence[Future[_AutoWorkerResult]]) -> None:
        for future in done:
            record = active.pop(future)
            slot = record.cancel_slot
            if slot >= 0:
                cancel_tokens[slot] = 0
                free_slots.add(slot)
            record.future = None
            record.cancel_slot = -1
            try:
                output = future.result()
            except _AutoWorkerCancelled:
                continue
            record_completed_output(record, output)

    def authoritative_records(
        task_ids: set[int],
    ) -> tuple[_AutoTaskRecord, ...]:
        return tuple(records[task_id] for task_id in sorted(task_ids))

    def completed_authoritative_members(
        task_ids: set[int],
    ) -> tuple[_AutoPopulationMember, ...]:
        result: list[_AutoPopulationMember] = []
        for record in authoritative_records(task_ids):
            if record.output is not None:
                result.append(members[record.task_id])
        return tuple(result)

    def next_speculative_record(
        generation: int,
        task_ids: set[int],
    ) -> _AutoTaskRecord | None:
        completed = completed_authoritative_members(task_ids)
        if not completed:
            return None
        provisional_count = min(survivor_count, len(completed))
        provisional = _select_population_survivors(
            completed,
            provisional_count,
            enforce_parent_diversity=generation > 1,
        )
        max_offspring = max(1, math.ceil(worker_count / survivor_count))
        for offspring_index in range(1, max_offspring + 1):
            for parent in provisional:
                key = (generation + 1, parent.member_id, offspring_index)
                existing = records_by_key.get(key)
                if existing is None:
                    return create_record(
                        generation + 1,
                        parent.member_id,
                        offspring_index,
                        authoritative=False,
                    )
                if (
                    existing.future is None
                    and existing.output is None
                    and not existing.cancelled
                ):
                    return existing
        return None

    def fill_slots(
        generation: int,
        task_ids: set[int],
        *,
        allow_speculation: bool,
    ) -> None:
        while free_slots:
            missing = next(
                (
                    record
                    for record in authoritative_records(task_ids)
                    if record.output is None
                    and record.future is None
                    and not record.cancelled
                ),
                None,
            )
            if missing is not None:
                submit_record(missing)
                continue
            if not allow_speculation:
                return
            speculative = next_speculative_record(generation, task_ids)
            if speculative is None:
                return
            submit_record(speculative)

    try:
        executor = ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=mp_context,
            initializer=_initialise_auto_worker,
            initargs=(
                _AutoWorkerContext(level=level, config=config),
                stop_event,
                checkpoint_queue,
                cancel_tokens,
            ),
        )

        current_task_ids = {
            create_record(1, source_member.member_id, offspring, authoritative=True).task_id
            for offspring in range(1, worker_count + 1)
        }

        while run_limit is None or run_index <= run_limit:
            suffix = f"/{run_limit}" if run_limit is not None else ""
            if status is not None:
                if run_index == 1:
                    description = (
                        f"starting {worker_count} independent searches, "
                        f"{config.iterations} iterations each"
                    )
                else:
                    description = (
                        f"population search from {survivor_count} survivor(s), "
                        f"{config.iterations} iterations each"
                    )
                status(f"[auto:parallel] round {run_index}{suffix}: {description}")

            allow_speculation = run_limit is None or run_index < run_limit
            fill_slots(
                run_index,
                current_task_ids,
                allow_speculation=allow_speculation,
            )

            while len(completed_authoritative_members(current_task_ids)) < len(
                current_task_ids
            ):
                if not active:
                    raise RuntimeError(
                        "Auto population scheduler has unfinished work but no active workers"
                    )
                done, _pending = wait(
                    tuple(active),
                    timeout=0.25,
                    return_when=FIRST_COMPLETED,
                )
                drain_checkpoints()
                if done:
                    reap_done(tuple(done))
                fill_slots(
                    run_index,
                    current_task_ids,
                    allow_speculation=allow_speculation,
                )

            drain_checkpoints()
            completed_members = completed_authoritative_members(current_task_ids)
            survivors = _select_population_survivors(
                completed_members,
                survivor_count,
                enforce_parent_diversity=run_index > 1,
            )
            completed_runs += 1
            if status is not None:
                lineages = len({member.parent_member_id for member in survivors})
                status(
                    f"[auto:parallel] round {run_index} complete: selected "
                    f"{len(survivors)}/{worker_count} survivors from "
                    f"{lineages} immediate parent lineage(s); global best finish "
                    f"{current.finish_tick}"
                )

            if run_limit is not None and run_index >= run_limit:
                break

            quotas = _offspring_quota_by_parent(survivors, worker_count)
            desired_keys = {
                (run_index + 1, parent.member_id, offspring_index)
                for parent in survivors
                for offspring_index in range(1, quotas[parent.member_id] + 1)
            }
            next_task_ids: set[int] = set()
            for key in sorted(desired_keys):
                generation, parent_member_id, offspring_index = key
                record = records_by_key.get(key)
                if record is None:
                    record = create_record(
                        generation,
                        parent_member_id,
                        offspring_index,
                        authoritative=True,
                    )
                else:
                    record.authoritative = True
                next_task_ids.add(record.task_id)

            for record in tuple(records.values()):
                if record.generation != run_index + 1:
                    continue
                key = (
                    record.generation,
                    record.parent_member_id,
                    record.offspring_index,
                )
                if key in desired_keys:
                    continue
                record.authoritative = False
                cancel_record(record)

            current_task_ids = next_task_ids
            run_index += 1
            _prune_campaign_history(
                records,
                records_by_key,
                members,
                current_task_ids,
                active,
            )
            fill_slots(
                run_index,
                current_task_ids,
                allow_speculation=(run_limit is None or run_index < run_limit),
            )

        for record in tuple(records.values()):
            if record.future is not None and not record.authoritative:
                cancel_record(record)
        drain_checkpoints()
        if active:
            _stop_executor(executor, tuple(active), stop_event)
        else:
            executor.shutdown(wait=True)
        executor = None
        drain_checkpoints()
        _close_checkpoint_queue(checkpoint_queue)
        return _compose_campaign_result(
            initial,
            current,
            aggregate_stats,
            committed_mutations,
            worker_count=worker_count,
            requested_runs=runs,
            completed_runs=completed_runs,
            completed_searches=completed_searches,
            interrupted=False,
        )
    except KeyboardInterrupt:
        drain_checkpoints()
        previous_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            if executor is not None:
                _stop_executor(executor, tuple(active), stop_event)
                executor = None
        finally:
            signal.signal(signal.SIGINT, previous_handler)
            drain_checkpoints()
            _close_checkpoint_queue(checkpoint_queue)
        if status is not None:
            status(
                "[auto:interrupt] Ctrl+C received; worker processes stopped; "
                "retaining the best verified result produced so far"
            )
        return _compose_campaign_result(
            initial,
            current,
            aggregate_stats,
            committed_mutations,
            worker_count=worker_count,
            requested_runs=runs,
            completed_runs=completed_runs,
            completed_searches=completed_searches,
            interrupted=True,
        )
    except BaseException:
        previous_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            if executor is not None:
                _stop_executor(executor, tuple(active), stop_event)
                executor = None
        finally:
            signal.signal(signal.SIGINT, previous_handler)
            _close_checkpoint_queue(checkpoint_queue)
        raise

__all__ = [
    "AutoCampaignResult",
    "auto_candidate_outcome_key",
    "auto_result_outcome_key",
    "automatic_auto_worker_count",
    "derive_auto_search_seed",
    "optimise_autonomous_campaign",
]

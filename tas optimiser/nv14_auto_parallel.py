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
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    CancelledError,
    Future,
    ProcessPoolExecutor,
    wait,
)
from dataclasses import dataclass, field, fields, replace
from queue import Empty
from typing import Any

from nv14_auto import (
    _ACTIVE_NATIVE_SESSION,
    AutoCandidate,
    AutoConfig,
    AutoProgress,
    AutoResult,
    AutoStats,
    SpliceAlignmentSpec,
    SplicePlanSpec,
    auto_candidate_outcome_key,
    auto_objective_value,
    evaluate_replay_with_sentinel,
    find_splice_section_plans,
    optimise_autonomous,
    repair_reference_segment_splice,
    verify_trimmed_replay,
)
from nv14_engine import InputFrame, Level
from nv14_search import NativeSearchSession
from nv14_splice_index import PreparedSpliceTrace, prepare_splice_trace

ProgressCallback = Callable[[AutoProgress], None]
BestCallback = Callable[[AutoCandidate], None]
StatusCallback = Callable[[str], None]
SearchFunction = Callable[..., AutoResult]

# Planning can identify many near-identical corridors in two long traces.  The
# survivor-level safeguards still see alternatives from different intervals,
# while this bound keeps a round-end splice pass proportional to population
# size rather than the number of overlapping anchor windows.
_SECTION_SPLICE_PLANS_PER_PAIR = 2
_SPLICE_TASK_ID_BASE = 1 << 63


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
    parent_member_ids: tuple[int, ...]
    generation: int
    mutations: tuple[str, ...]
    splice_parent_pair: tuple[int, int] | None = None
    splice_interval: tuple[int, int, int, int] | None = None

    @property
    def parent_member_id(self) -> int | None:
        """Compatibility view for ordinary one-parent population members."""
        return self.parent_member_ids[0] if self.parent_member_ids else None

    @property
    def is_splice(self) -> bool:
        return self.splice_parent_pair is not None


@dataclass(slots=True)
class _SpliceRoundStats:
    """Counters for one coordinator-side inter-run splice pass.

    These are deliberately separate from :class:`AutoStats`: worker search
    statistics are additive across independent searches, while splice counts
    describe the population-level pipeline between two rounds.
    """

    pairs: int = 0
    corridors: int = 0
    plans: int = 0
    attempted: int = 0
    repaired: int = 0
    completed: int = 0
    canonical: int = 0
    beat_recipient: int = 0
    admitted: int = 0
    survivors: int = 0
    rejection_counts: dict[str, int] = field(default_factory=dict)
    predicted_gains: list[int] = field(default_factory=list)
    realised_gains: list[int] = field(default_factory=list)

    def reject(self, reason: str, count: int = 1) -> None:
        if count < 1:
            return
        self.rejection_counts[reason] = (
            self.rejection_counts.get(reason, 0) + count
        )

    def merge(self, other: "_SpliceRoundStats") -> None:
        """Add one independently executed pair job's counters in-place."""
        for name in (
            "pairs",
            "corridors",
            "plans",
            "attempted",
            "repaired",
            "completed",
            "canonical",
            "beat_recipient",
            "admitted",
            "survivors",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        for reason, count in other.rejection_counts.items():
            self.reject(reason, count)
        self.predicted_gains.extend(other.predicted_gains)
        self.realised_gains.extend(other.realised_gains)


def _format_splice_gain_range(gains: Sequence[int]) -> str:
    if not gains:
        return "none"
    low = min(gains)
    high = max(gains)
    return str(low) if low == high else f"{low}..{high}"


def _format_splice_rejections(rejections: dict[str, int]) -> str:
    if not rejections:
        return "none"
    return ",".join(
        f"{reason}:{rejections[reason]}" for reason in sorted(rejections)
    )


def _format_splice_round_summary(
    round_index: int,
    stats: _SpliceRoundStats,
) -> str:
    return (
        f"[auto:splice] round {round_index}: "
        f"pairs={stats.pairs}, corridors={stats.corridors}, "
        f"plans={stats.plans}, attempted={stats.attempted}, "
        f"repaired={stats.repaired}, completed={stats.completed}, "
        f"canonical={stats.canonical}, "
        f"beat-recipient={stats.beat_recipient}, admitted={stats.admitted}, "
        f"survivors={stats.survivors}; "
        f"predicted gain={_format_splice_gain_range(stats.predicted_gains)}, "
        f"realised gain={_format_splice_gain_range(stats.realised_gains)}; "
        f"rejected={_format_splice_rejections(stats.rejection_counts)}"
    )


def _emit_splice_round_summary(
    round_index: int,
    stats: _SpliceRoundStats,
    status: StatusCallback | None,
) -> None:
    message = _format_splice_round_summary(round_index, stats)
    if status is None:
        print(message, flush=True)
    else:
        status(message)


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
    output_member_id: int | None = None
    cancelled: bool = False
    preempted: bool = False


@dataclass(frozen=True, slots=True)
class _SpliceWorkerTask:
    """One ordered recipient/donor pair executed by the shared process pool."""

    recipient: _AutoPopulationMember
    donor: _AutoPopulationMember
    recipient_trace: PreparedSpliceTrace
    donor_trace: PreparedSpliceTrace
    run_index: int
    task_id: int
    required_gold_mask: int = 0
    worker_index: int = 0
    cancel_slot: int = -1


@dataclass(frozen=True, slots=True)
class _SpliceWorkerCandidate:
    """Canonically verified pair-local output awaiting ordered admission."""

    candidate: AutoCandidate
    recipient_entry_tick: int
    recipient_exit_tick: int
    donor_entry_tick: int
    donor_exit_tick: int
    predicted_time_gain: int


@dataclass(frozen=True, slots=True)
class _SpliceWorkerCheckpoint:
    """One canonically verified splice preserved independently of its future."""

    task_id: int
    run_index: int
    recipient_member_id: int
    donor_member_id: int
    proposal: _SpliceWorkerCandidate


@dataclass(frozen=True, slots=True)
class _SpliceWorkerResult:
    """All pair-local work returned by one splice worker job."""

    task_id: int
    run_index: int
    recipient_member_id: int
    donor_member_id: int
    candidates: tuple[_SpliceWorkerCandidate, ...]
    splice_stats: _SpliceRoundStats
    auto_stats: AutoStats


@dataclass(slots=True)
class _SpliceTaskRecord:
    """Coordinator lifecycle for an asynchronous ordered splice pair."""

    task_id: int
    generation: int
    recipient_member_id: int
    donor_member_id: int
    pair_order: int
    worker_index: int = 0
    cancel_slot: int = -1
    future: Future[_SpliceWorkerResult] | None = None
    output: _SpliceWorkerResult | None = None


class _AutoWorkerCancelled(Exception):
    """Internal cooperative-cancellation signal for an Auto worker."""


_AUTO_WORKER_CONTEXT: _AutoWorkerContext | None = None
_AUTO_WORKER_STOP_EVENT: Any | None = None
_AUTO_WORKER_CHECKPOINT_QUEUE: Any | None = None
_AUTO_WORKER_CANCEL_TOKENS: Any | None = None
_AUTO_WORKER_SPLICE_PARENT_CACHE: dict[
    tuple[int, int], _AutoPopulationMember
] = {}
_AUTO_WORKER_NATIVE_SESSION: NativeSearchSession | None = None


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
    global _AUTO_WORKER_SPLICE_PARENT_CACHE
    global _AUTO_WORKER_NATIVE_SESSION
    _AUTO_WORKER_CONTEXT = context
    _AUTO_WORKER_STOP_EVENT = stop_event
    _AUTO_WORKER_CHECKPOINT_QUEUE = checkpoint_queue
    _AUTO_WORKER_CANCEL_TOKENS = cancel_tokens
    _AUTO_WORKER_SPLICE_PARENT_CACHE = {}
    _AUTO_WORKER_NATIVE_SESSION = None
    if multiprocessing.current_process().name != "MainProcess":
        signal.signal(signal.SIGINT, signal.SIG_IGN)


def _worker_cancelled(
    task: _AutoWorkerTask | _SpliceWorkerTask | None = None,
) -> bool:
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
    """Select ranked survivors while retaining lineage and splice diversity.

    A splice belongs to both source lineages, rather than being treated as a
    mutation of its recipient alone.  Before duplicate splice sites are
    allowed to fill spare capacity, only one child from a parent pair or an
    exact trajectory interval can survive.  The best ordinary result is also
    reserved whenever the selection pool contains one, preventing a prolific
    donor pair from replacing every independent whole-run result.
    """
    ranked = sorted(
        members,
        key=lambda member: auto_result_outcome_key(member.result),
    )
    survivor_count = min(max(0, survivor_count), len(ranked))
    if survivor_count == 0:
        return ()

    ordinary_elite = next((member for member in ranked if not member.is_splice), None)
    available_lineages = {
        lineage
        for member in ranked
        for lineage in member.parent_member_ids
    }
    min_distinct = (
        min(3, survivor_count, len(available_lineages))
        if enforce_parent_diversity
        else 0
    )
    selected: list[_AutoPopulationMember] = []
    selected_ids: set[int] = set()
    selected_lineages: set[int] = set()

    def duplicate_splice(member: _AutoPopulationMember) -> bool:
        if not member.is_splice:
            return False
        return any(
            other.is_splice
            and (
                other.splice_parent_pair == member.splice_parent_pair
                or other.splice_interval == member.splice_interval
            )
            for other in selected
        )

    def reserve_constraints_allow(member: _AutoPopulationMember) -> bool:
        remaining_after = survivor_count - len(selected) - 1
        if (
            ordinary_elite is not None
            and not any(not other.is_splice for other in selected)
            and member.is_splice
            and remaining_after == 0
        ):
            return False
        projected_lineages = selected_lineages | set(member.parent_member_ids)
        still_needed = max(0, min_distinct - len(projected_lineages))
        return remaining_after >= still_needed

    # First take the distinct splice opportunities.  A second pass below may
    # use duplicate pairs/intervals only when the requested population size
    # would otherwise remain unfilled.
    for allow_splice_duplicates in (False, True):
        for member in ranked:
            if len(selected) >= survivor_count:
                break
            if member.member_id in selected_ids:
                continue
            if not allow_splice_duplicates and duplicate_splice(member):
                continue
            if not reserve_constraints_allow(member):
                continue
            selected.append(member)
            selected_ids.add(member.member_id)
            selected_lineages.update(member.parent_member_ids)
        if len(selected) >= survivor_count:
            break

    # The constraints above deliberately prefer diversity, but pathological
    # ancestry inputs must never leave a round without its requested parents.
    if len(selected) != survivor_count:
        for member in ranked:
            if len(selected) >= survivor_count:
                break
            if member.member_id in selected_ids:
                continue
            if (
                ordinary_elite is not None
                and not any(not other.is_splice for other in selected)
                and member.is_splice
                and len(selected) + 1 == survivor_count
            ):
                continue
            selected.append(member)
            selected_ids.add(member.member_id)
            selected_lineages.update(member.parent_member_ids)
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
        if record.output_member_id is not None:
            retained_member_ids.add(record.output_member_id)

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
    return _result_from_candidate(checkpoint.candidate, template)


def _result_from_candidate(
    candidate: AutoCandidate,
    template: AutoResult,
) -> AutoResult:
    """Build a complete-run result from an already verified candidate."""
    evaluation = candidate.evaluation
    if evaluation.finish_tick is None:
        raise RuntimeError("Auto candidate did not complete")
    objective_value = auto_objective_value(evaluation, template.objective)
    if objective_value is None:
        raise RuntimeError("Auto candidate has no objective value")
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


def _canonical_splice_candidate(
    level: Level,
    candidate: AutoCandidate,
) -> AutoCandidate | None:
    """Independently verify a splice before it enters a population.

    Repair's own simulation is necessary for its local controller, but it is
    not a substitute for Auto's normal canonical trimmed-replay verification.
    This makes the population member use exactly the body that will later be
    supplied to a worker and written by the final campaign.
    """
    if not candidate.output_valid or candidate.finish_tick is None:
        return None
    body = candidate.frames
    try:
        verified = verify_trimmed_replay(
            level,
            body,
            expected_finish_tick=candidate.finish_tick,
            expected_gold_mask=candidate.evaluation.final_gold_mask,
            expected_gold_bonus_ticks=candidate.evaluation.gold_bonus_ticks,
        )
    except ValueError:
        return None
    return replace(
        candidate,
        working_frames=body + (InputFrame(),),
        evaluation=verified,
        sentinel_verified=True,
        replay_key=None,
        input_transitions=None,
    )


def _splice_rejection_bucket(reason: str | None) -> str:
    """Reduce detailed splice diagnostics to stable summary labels."""
    if not reason:
        return "repair-rejected"
    if "required reference gold" in reason:
        return "reference-gold"
    if "did not improve the selected campaign outcome" in reason:
        return "not-better-than-recipient"
    if "sentinel-verified completion" in reason or (
        "completed recipient and child" in reason
    ):
        return "repair-incomplete"
    if "campaign local budget exhausted" in reason:
        return "repair-budget"
    if "failure region" in reason and "revisited" in reason:
        return "repair-repeated-region"
    if "no editable bridge or reference region" in reason:
        return "repair-no-editable-region"
    if "no local repair proposal" in reason:
        return "repair-no-proposal"
    if "repeated an existing replay" in reason:
        return "repair-repeated-replay"
    if "made no progress" in reason:
        return "repair-no-progress"
    return "repair-other"


def _splice_repair_changed(repair: object) -> bool:
    """Return whether a repair campaign retained a changed frontier."""
    raw_candidate = getattr(repair, "raw_candidate", None)
    candidate = getattr(repair, "candidate", None)
    if raw_candidate is None or candidate is None:
        return False
    return bool(
        getattr(raw_candidate, "working_frames", None)
        != getattr(candidate, "working_frames", None)
    )


def _native_splice_parent(
    level: Level,
    generation: int,
    member: _AutoPopulationMember,
) -> _AutoPopulationMember:
    """Return a process-local parent whose analysis still owns native trace data.

    ``AutoEvaluation.trace`` deliberately materialises when an Auto result is
    pickled back to the coordinator.  Re-evaluate each parent once per worker
    and round so native splice scans remain available for every ordered pair
    handled by that process.  Repair then reuses this same candidate evaluation
    instead of paying another parent simulation.
    """
    global _AUTO_WORKER_SPLICE_PARENT_CACHE
    # Coordinator unit tests use lightweight object() levels.  Production
    # campaigns always carry the concrete parsed Level required by the native
    # evaluator, while those harness parents are already their source of truth.
    if not isinstance(level, Level):
        return member
    key = (generation, member.member_id)
    cached = _AUTO_WORKER_SPLICE_PARENT_CACHE.get(key)
    if cached is not None:
        return cached
    if _AUTO_WORKER_SPLICE_PARENT_CACHE and any(
        cached_generation != generation
        for cached_generation, _member_id in _AUTO_WORKER_SPLICE_PARENT_CACHE
    ):
        _AUTO_WORKER_SPLICE_PARENT_CACHE = {
            cached_key: value
            for cached_key, value in _AUTO_WORKER_SPLICE_PARENT_CACHE.items()
            if cached_key[0] == generation
        }
    evaluation = evaluate_replay_with_sentinel(level, member.result.frames)
    candidate = replace(member.result.best, evaluation=evaluation)
    native_member = replace(
        member,
        result=replace(member.result, best=candidate),
    )
    _AUTO_WORKER_SPLICE_PARENT_CACHE[key] = native_member
    return native_member


def _run_splice_worker(task: _SpliceWorkerTask) -> _SpliceWorkerResult:
    """Run one pair while retaining a native session for this worker process."""
    global _AUTO_WORKER_NATIVE_SESSION
    context = _AUTO_WORKER_CONTEXT
    if context is None:
        raise RuntimeError("Auto worker was not initialised")
    if _AUTO_WORKER_NATIVE_SESSION is None and isinstance(context.level, Level):
        _AUTO_WORKER_NATIVE_SESSION = NativeSearchSession(context.level)
    token = _ACTIVE_NATIVE_SESSION.set(
        (context.level, _AUTO_WORKER_NATIVE_SESSION)
    )
    try:
        return _run_splice_worker_in_session(task, context)
    finally:
        _ACTIVE_NATIVE_SESSION.reset(token)


def _run_splice_worker_in_session(
    task: _SpliceWorkerTask,
    context: _AutoWorkerContext,
) -> _SpliceWorkerResult:
    """Plan, repair and canonically verify one ordered parent pair.

    Duplicate suppression and final population admission intentionally remain
    coordinator operations: those gates depend on every pair in the round and
    therefore must be applied in a stable order rather than future-completion
    order.
    """
    if _worker_cancelled(task):
        raise _AutoWorkerCancelled

    level = context.level
    config = context.config
    recipient = _native_splice_parent(level, task.run_index, task.recipient)
    donor = _native_splice_parent(level, task.run_index, task.donor)
    stats = _SpliceRoundStats(pairs=1)
    repair_stats = AutoStats()
    outputs: list[_SpliceWorkerCandidate] = []

    def finish() -> _SpliceWorkerResult:
        return _SpliceWorkerResult(
            task_id=task.task_id,
            run_index=task.run_index,
            recipient_member_id=recipient.member_id,
            donor_member_id=donor.member_id,
            candidates=tuple(outputs),
            splice_stats=stats,
            auto_stats=repair_stats,
        )

    recipient_frames = recipient.result.frames
    recipient_body_end = len(recipient_frames) - 1
    configured_end = (
        recipient_body_end
        if config.range_end is None
        else min(recipient_body_end, config.range_end)
    )
    if configured_end < config.range_start:
        stats.reject("empty-range")
        return _SpliceWorkerResult(
            task_id=task.task_id,
            run_index=task.run_index,
            recipient_member_id=recipient.member_id,
            donor_member_id=donor.member_id,
            candidates=(),
            splice_stats=stats,
            auto_stats=repair_stats,
        )

    alignment_spec = SpliceAlignmentSpec(
        position_tolerance=config.alignment_position_tolerance,
        velocity_tolerance=config.alignment_velocity_tolerance,
        recipient_start_tick=config.range_start,
        recipient_end_tick=configured_end,
        objective=config.objective,
    )
    plan_spec = SplicePlanSpec(objective=config.objective)
    corridor_count = 0

    def observe_anchor_runs(runs: tuple[object, ...]) -> None:
        nonlocal corridor_count
        corridor_count = len(runs)
        stats.corridors += len(runs)

    plans = find_splice_section_plans(
        task.recipient_trace,
        task.donor_trace,
        alignment_spec,
        plan_spec,
        anchor_runs_observer=observe_anchor_runs,
    )
    stats.plans += len(plans)
    if not plans:
        stats.reject("no-corridors" if corridor_count == 0 else "no-plans")

    max_body_length = len(recipient.result.best.working_frames) - 1
    for plan in plans[:_SECTION_SPLICE_PLANS_PER_PAIR]:
        if _worker_cancelled(task):
            # A previous plan may already have produced a canonical replay.
            # Return that partial successful result instead of converting the
            # entire pair future into cancellation and losing verified work.
            if outputs:
                return finish()
            raise _AutoWorkerCancelled
        stats.attempted += 1
        stats.predicted_gains.append(plan.predicted_time_gain)
        repair = repair_reference_segment_splice(
            level,
            recipient.result.best,
            donor.result.best,
            plan,
            config=config,
            max_body_length=max_body_length,
            required_gold_mask=task.required_gold_mask,
        )
        pair_repair_stats = AutoStats(
            local_simulations=repair.local_simulations,
            repair_attempts=repair.attempts,
            repair_campaigns=1,
            repair_campaign_attempts=repair.attempts,
            successful_repairs=int(repair.accepted and repair.attempts > 0),
        )
        repair_stats = _sum_stats(repair_stats, pair_repair_stats)
        if _splice_repair_changed(repair):
            stats.repaired += 1
        repaired_candidate = getattr(repair, "candidate", None)
        completed = bool(
            repaired_candidate is not None
            and getattr(repaired_candidate, "output_valid", False)
        )
        if completed:
            stats.completed += 1
            recipient_finish = recipient.result.finish_tick
            child_finish = repaired_candidate.finish_tick
            if recipient_finish is not None and child_finish is not None:
                stats.realised_gains.append(recipient_finish - child_finish)
        if not repair.accepted:
            stats.reject(
                _splice_rejection_bucket(
                    getattr(repair, "rejection_reason", None)
                )
            )
            continue
        candidate = _canonical_splice_candidate(level, repair.candidate)
        if candidate is None:
            stats.reject("canonical-verification")
            continue
        stats.canonical += 1
        if (
            config.require_reference_gold
            and candidate.evaluation.final_gold_mask & task.required_gold_mask
            != task.required_gold_mask
        ):
            stats.reject("reference-gold")
            continue
        proposal = _SpliceWorkerCandidate(
            candidate=candidate,
            recipient_entry_tick=plan.recipient_entry_tick,
            recipient_exit_tick=plan.recipient_exit_tick,
            donor_entry_tick=plan.donor_entry_tick,
            donor_exit_tick=plan.donor_exit_tick,
            predicted_time_gain=plan.predicted_time_gain,
        )
        outputs.append(proposal)
        checkpoint_queue = _AUTO_WORKER_CHECKPOINT_QUEUE
        if checkpoint_queue is not None:
            checkpoint_queue.put(
                _SpliceWorkerCheckpoint(
                    task_id=task.task_id,
                    run_index=task.run_index,
                    recipient_member_id=recipient.member_id,
                    donor_member_id=donor.member_id,
                    proposal=proposal,
                )
            )

    return finish()


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


def _successful_completed_futures(
    futures: Sequence[Future[Any]],
) -> tuple[Future[Any], ...]:
    """Return completed futures whose worker callable returned normally."""
    successful: list[Future[Any]] = []
    for future in futures:
        if not future.done() or future.cancelled():
            continue
        try:
            exception = future.exception()
        except CancelledError:
            continue
        if exception is None:
            successful.append(future)
    return tuple(successful)


def _buffer_checkpoint_queue(
    checkpoint_queue: Any,
    producers_done: threading.Event,
    buffered: list[Any],
) -> None:
    """Pump worker checkpoints until every producer has stopped.

    This helper deliberately performs queue I/O only.  Coordinator state and
    user callbacks remain confined to the main thread when the returned
    objects are folded after shutdown.
    """
    while True:
        try:
            update = checkpoint_queue.get(timeout=0.05)
        except Empty:
            if not producers_done.is_set():
                continue
            # Producers and their feeder threads are gone.  Make one explicit
            # non-blocking sweep before exiting so queue implementations with
            # a delayed reader handoff cannot strand an already-arrived item.
            while True:
                try:
                    buffered.append(checkpoint_queue.get_nowait())
                except Empty:
                    return
                except (EOFError, OSError, ValueError):
                    return
        except (EOFError, OSError, ValueError):
            return
        else:
            buffered.append(update)


def _stop_executor(
    executor: ProcessPoolExecutor,
    futures: Sequence[Future[Any]],
    stop_event: Any,
    checkpoint_queue: Any,
) -> tuple[tuple[Future[Any], ...], tuple[Any, ...]]:
    """Stop workers while pumping their checkpoint queue.

    A process can be blocked in ``Queue.put`` while its result future is still
    pending.  Keep a consumer running throughout the cooperative grace period
    and executor shutdown, then hand the buffered objects back to the
    coordinator for main-thread processing.
    """
    buffered: list[Any] = []
    producers_done = threading.Event()
    drainer = threading.Thread(
        target=_buffer_checkpoint_queue,
        args=(checkpoint_queue, producers_done, buffered),
        name="nv14-checkpoint-drainer",
    )
    drainer.start()
    try:
        stop_event.set()
        for future in futures:
            future.cancel()

        _done, pending = wait(futures, timeout=2.0)
        if not pending:
            executor.shutdown(wait=True, cancel_futures=True)
        else:
            terminate_workers = getattr(executor, "terminate_workers", None)
            if callable(terminate_workers):
                terminate_workers()
            else:
                # Python 3.11-3.13 have no public immediate ProcessPool stop
                # operation. These are the executor's own child Process
                # objects; terminate only those exact resolved processes, then
                # let shutdown join its management thread.
                processes = tuple(getattr(executor, "_processes", {}).values())
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                for process in processes:
                    process.join(timeout=2.0)
                executor.shutdown(wait=True, cancel_futures=True)
    finally:
        # Executor teardown joins worker processes and therefore their Queue
        # feeder threads.  Only then may an Empty observation end the pump.
        producers_done.set()
        drainer.join()
    return _successful_completed_futures(futures), tuple(buffered)


def optimise_autonomous_campaign(
    level: Level,
    source_frames: Sequence[InputFrame],
    config: AutoConfig,
    *,
    parent_frames: Sequence[Sequence[InputFrame]] = (),
    workers: int = 0,
    runs: int = 1,
    progress: ProgressCallback | None = None,
    best_callback: BestCallback | None = None,
    status: StatusCallback | None = None,
    search: SearchFunction = optimise_autonomous,
) -> AutoCampaignResult:
    """Run independent Auto searches as an asynchronous survivor population.

    ``source_frames`` remains the campaign reference. ``parent_frames`` adds
    generation-0 founders which are independently canonicalised and verified.
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

    # Canonicalise and verify every founder once in the coordinator. Every
    # worker then starts from an exact trimmed replay rather than independently
    # retaining unused source inputs. The positional source remains first and
    # continues to own campaign baseline/reference semantics.
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

    unique_starting_results: list[tuple[int, AutoResult]] = [(1, initial)]
    seen_starting_replays = {
        bytes(
            int(frame.left)
            | (int(frame.right) << 1)
            | (int(frame.jump) << 2)
            for frame in initial.frames
        )
    }
    duplicate_parent_count = 0
    supplied_parent_count = 1 + len(parent_frames)
    for parent_number, frames in enumerate(parent_frames, start=2):
        if status is not None:
            status(
                f"[auto:parents] verifying starting parent "
                f"{parent_number}/{supplied_parent_count}"
            )
        try:
            parent_result = search(
                level,
                frames,
                replace(config, iterations=0),
                progress=None,
                best_callback=None,
            )
        except (RuntimeError, ValueError) as exc:
            raise ValueError(
                f"auto parent #{parent_number} failed canonical "
                f"verification: {exc}"
            ) from exc

        if config.require_reference_gold:
            missing_reference_gold = (
                initial.baseline_gold_mask & ~parent_result.gold_mask
            )
            if missing_reference_gold:
                missing_indices = ", ".join(
                    f"gold:{index}"
                    for index in range(missing_reference_gold.bit_length())
                    if missing_reference_gold & (1 << index)
                )
                raise ValueError(
                    f"auto parent #{parent_number} is missing positional "
                    f"reference gold: {missing_indices}"
                )

        replay_key = bytes(
            int(frame.left)
            | (int(frame.right) << 1)
            | (int(frame.jump) << 2)
            for frame in parent_result.frames
        )
        if replay_key in seen_starting_replays:
            duplicate_parent_count += 1
            continue
        seen_starting_replays.add(replay_key)
        unique_starting_results.append((parent_number, parent_result))

    founders = tuple(
        _AutoPopulationMember(
            member_id=member_id,
            result=result,
            parent_member_ids=(),
            generation=0,
            mutations=(
                result.best.mutations
                if parent_number == 1
                else (f"starting parent #{parent_number}", *result.best.mutations)
            ),
        )
        for member_id, (parent_number, result) in enumerate(
            unique_starting_results
        )
    )
    ranked_founders = tuple(
        sorted(
            founders,
            key=lambda member: auto_result_outcome_key(member.result),
        )
    )
    best_founder = ranked_founders[0]
    current = best_founder.result
    committed_mutations = best_founder.mutations

    if parent_frames and status is not None:
        duplicate_text = (
            f"; collapsed {duplicate_parent_count} canonical duplicate(s)"
            if duplicate_parent_count
            else ""
        )
        status(
            f"[auto:parents] {len(founders)} unique starting parent(s) "
            f"from {supplied_parent_count} supplied; initial best member "
            f"{best_founder.member_id}{duplicate_text}"
        )
    if (
        best_founder.member_id != 0
        and config.iterations > 0
        and best_callback is not None
    ):
        best_callback(best_founder.result.best)

    if config.iterations == 0:
        return _compose_campaign_result(
            initial,
            current,
            AutoStats(),
            committed_mutations,
            worker_count=worker_count,
            requested_runs=runs,
            completed_runs=0,
            completed_searches=0,
            interrupted=False,
        )

    aggregate_stats = AutoStats()
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
            _emit_splice_round_summary(run_index, _SpliceRoundStats(), status)
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
    active: dict[
        Future[Any], _AutoTaskRecord | _SpliceTaskRecord
    ] = {}
    free_slots: set[int] = set(range(worker_count))
    records: dict[int, _AutoTaskRecord] = {}
    records_by_key: dict[tuple[int, int, int], _AutoTaskRecord] = {}
    splice_records: dict[
        tuple[int, int, int], _SpliceTaskRecord
    ] = {}
    prepared_splice_traces: dict[int, PreparedSpliceTrace] = {}
    members: dict[int, _AutoPopulationMember] = {
        member.member_id: member for member in founders
    }
    next_task_id = 1
    next_splice_task_id = 1
    next_member_id = len(founders)
    survivor_count = _population_survivor_count(worker_count)
    checkpoint_key = auto_result_outcome_key(current)
    splice_interrupt_checkpoint: tuple[
        tuple[object, ...], AutoResult, tuple[str, ...]
    ] | None = None
    required_reference_gold_mask = (
        initial.baseline_gold_mask if config.require_reference_gold else 0
    )

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

    def sync_splice_records(
        generation: int,
        completed_members: Sequence[_AutoPopulationMember],
    ) -> None:
        """Create every newly ready ordered pair exactly once.

        This is called after each Auto completion, not merely at round end, so
        the first pair becomes runnable immediately when the second parent is
        available.  The dictionary key is independent of future completion
        order and repeated scheduler fills are idempotent.
        """
        nonlocal next_splice_task_id
        for member in completed_members:
            if member.member_id not in prepared_splice_traces:
                prepared_splice_traces[member.member_id] = prepare_splice_trace(
                    member.result.best.evaluation,
                    member.result.frames,
                )
        ordered = tuple(completed_members)
        for recipient in ordered:
            for donor in ordered:
                if recipient.member_id == donor.member_id:
                    continue
                key = (generation, recipient.member_id, donor.member_id)
                if key in splice_records:
                    continue
                sequence = next_splice_task_id
                next_splice_task_id += 1
                splice_records[key] = _SpliceTaskRecord(
                    # Keep splice cancellation tokens disjoint from the Auto
                    # seed/task stream without consuming Auto task IDs.
                    task_id=_SPLICE_TASK_ID_BASE | sequence,
                    generation=generation,
                    recipient_member_id=recipient.member_id,
                    donor_member_id=donor.member_id,
                    pair_order=sequence,
                )

    def parent_mutations(record: _AutoTaskRecord) -> tuple[str, ...]:
        return members[record.parent_member_id].mutations

    def member_from_output(
        record: _AutoTaskRecord,
        output: _AutoWorkerResult,
    ) -> _AutoPopulationMember:
        nonlocal next_member_id
        if record.output_member_id is not None:
            return members[record.output_member_id]
        member = _AutoPopulationMember(
            member_id=next_member_id,
            result=output.result,
            parent_member_ids=(record.parent_member_id,),
            generation=record.generation,
            mutations=parent_mutations(record) + _annotated_mutations(output),
        )
        next_member_id += 1
        record.output_member_id = member.member_id
        members[member.member_id] = member
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

    def fold_checkpoints(updates: Sequence[Any]) -> None:
        """Apply queue payloads on the coordinator thread in arrival order."""
        for update in updates:
            if isinstance(update, _AutoWorkerCheckpoint):
                accept_checkpoint(update)
                continue
            if isinstance(update, _SpliceWorkerCheckpoint):
                key = (
                    update.run_index,
                    update.recipient_member_id,
                    update.donor_member_id,
                )
                record = splice_records.get(key)
                if record is None or record.task_id != update.task_id:
                    continue
                remember_verified_splice_candidate(record, update.proposal)

    def drain_checkpoints() -> None:
        updates: list[Any] = []
        while True:
            try:
                updates.append(checkpoint_queue.get_nowait())
            except Empty:
                break
            except (EOFError, OSError, ValueError):
                break
        fold_checkpoints(updates)

    def submit_record(record: _AutoTaskRecord) -> bool:
        if executor is None or not free_slots:
            return False
        if (
            record.future is not None
            or record.output is not None
            or record.cancelled
            or record.preempted
        ):
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

    def submit_splice_record(record: _SpliceTaskRecord) -> bool:
        if executor is None or not free_slots:
            return False
        if record.future is not None or record.output is not None:
            return False
        slot = min(free_slots)
        free_slots.remove(slot)
        record.cancel_slot = slot
        record.worker_index = slot + 1
        cancel_tokens[slot] = record.task_id
        task = _SpliceWorkerTask(
            recipient=members[record.recipient_member_id],
            donor=members[record.donor_member_id],
            recipient_trace=prepared_splice_traces[
                record.recipient_member_id
            ],
            donor_trace=prepared_splice_traces[record.donor_member_id],
            run_index=record.generation,
            task_id=record.task_id,
            required_gold_mask=required_reference_gold_mask,
            worker_index=record.worker_index,
            cancel_slot=slot,
        )
        future = executor.submit(_run_splice_worker, task)
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

    def preempt_record(record: _AutoTaskRecord) -> None:
        """Cooperatively pause speculative work without invalidating its key."""
        if (
            record.authoritative
            or record.cancelled
            or record.preempted
            or record.output is not None
        ):
            return
        record.preempted = True
        if record.cancel_slot >= 0:
            cancel_tokens[record.cancel_slot] = 0
        future = record.future
        if future is not None and future.cancel():
            active.pop(future, None)
            if record.cancel_slot >= 0:
                free_slots.add(record.cancel_slot)
            record.future = None
            record.cancel_slot = -1

    def preempt_speculation_for_ready_splices(generation: int) -> None:
        ready_count = sum(
            record.generation == generation
            and record.output is None
            and record.future is None
            for record in splice_records.values()
        )
        deficit = max(0, ready_count - len(free_slots))
        if deficit == 0:
            return
        speculative = sorted(
            (
                record
                for record in active.values()
                if isinstance(record, _AutoTaskRecord)
                and not record.authoritative
                and record.generation == generation + 1
                and not record.cancelled
                and not record.preempted
            ),
            key=lambda record: record.task_id,
            reverse=True,
        )
        for record in speculative[:deficit]:
            preempt_record(record)

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

    def remember_verified_splice_candidate(
        record: _SpliceTaskRecord,
        proposal: _SpliceWorkerCandidate,
    ) -> None:
        """Retain one verified pair candidate for an interrupt handoff.

        Normal admission remains buffered and deterministic.  This separate
        strict checkpoint means Ctrl+C cannot discard a canonically verified
        improvement merely because its enclosing pair future was interrupted.
        """
        nonlocal splice_interrupt_checkpoint
        recipient = members[record.recipient_member_id]
        donor = members[record.donor_member_id]
        candidate = proposal.candidate
        child_result = _result_from_candidate(candidate, recipient.result)
        outcome_key = auto_result_outcome_key(child_result)
        if outcome_key >= auto_result_outcome_key(recipient.result):
            return
        actual_gain = recipient.result.finish_tick - child_result.finish_tick
        diagnostic = (
            f"splice round {record.generation}: recipient member "
            f"{recipient.member_id}, donor member {donor.member_id}, "
            f"A {proposal.recipient_entry_tick}.."
            f"{proposal.recipient_exit_tick} <- B "
            f"{proposal.donor_entry_tick}..{proposal.donor_exit_tick}, "
            f"predicted gain {proposal.predicted_time_gain}, "
            f"actual gain {actual_gain}"
        )
        mutations = recipient.mutations + (diagnostic,)
        checkpoint_candidate = replace(candidate, mutations=mutations)
        checkpoint_result = replace(
            _result_from_candidate(checkpoint_candidate, recipient.result),
            stats=AutoStats(),
            diagnostics=recipient.result.diagnostics + (diagnostic,),
        )
        frame_tie_key = tuple(
            (frame.left, frame.right, frame.jump)
            for frame in checkpoint_candidate.frames
        )
        stable_key: tuple[object, ...] = (
            *outcome_key,
            record.generation,
            record.recipient_member_id,
            record.donor_member_id,
            proposal.recipient_entry_tick,
            proposal.recipient_exit_tick,
            proposal.donor_entry_tick,
            proposal.donor_exit_tick,
            frame_tie_key,
        )
        if (
            splice_interrupt_checkpoint is None
            or stable_key < splice_interrupt_checkpoint[0]
        ):
            splice_interrupt_checkpoint = (
                stable_key,
                checkpoint_result,
                mutations,
            )

    def remember_verified_splice_output(
        record: _SpliceTaskRecord,
        output: _SpliceWorkerResult,
    ) -> None:
        for proposal in output.candidates:
            remember_verified_splice_candidate(record, proposal)

    def reap_done(done: Sequence[Future[Any]]) -> None:
        # ``wait`` returns a set.  Reap a simultaneous batch by scheduler task
        # ID so member allocation and checkpoint ancestry do not inherit hash
        # iteration order.
        for future in sorted(done, key=lambda item: active[item].task_id):
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
            if isinstance(record, _SpliceTaskRecord):
                if not isinstance(output, _SpliceWorkerResult):
                    raise TypeError("splice worker returned an Auto result")
                record.output = output
                remember_verified_splice_output(record, output)
            else:
                if not isinstance(output, _AutoWorkerResult):
                    raise TypeError("Auto worker returned a splice result")
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
            if record.output_member_id is not None:
                result.append(members[record.output_member_id])
        return tuple(result)

    def commit_splice_outputs(
        completed_members: Sequence[_AutoPopulationMember],
        generation: int,
        round_stats: _SpliceRoundStats,
    ) -> tuple[_AutoPopulationMember, ...]:
        """Admit buffered pair outputs in deterministic pair/plan order."""
        nonlocal aggregate_stats, checkpoint_key, committed_mutations
        nonlocal current, next_member_id

        accepted: list[_AutoPopulationMember] = []
        accepted_bodies = {member.result.frames for member in completed_members}
        population_order = {
            member.member_id: index
            for index, member in enumerate(completed_members)
        }
        generation_records = sorted(
            (
                record
                for record in splice_records.values()
                if record.generation == generation
            ),
            key=lambda record: (
                population_order[record.recipient_member_id],
                population_order[record.donor_member_id],
            ),
        )
        for record in generation_records:
            output = record.output
            if output is None:
                raise RuntimeError("round finalised before a splice pair completed")
            if (
                output.recipient_member_id != record.recipient_member_id
                or output.donor_member_id != record.donor_member_id
            ):
                raise RuntimeError("splice worker returned the wrong parent pair")
            round_stats.merge(output.splice_stats)
            aggregate_stats = _sum_stats(aggregate_stats, output.auto_stats)
            recipient = members[record.recipient_member_id]
            donor = members[record.donor_member_id]
            for proposal in output.candidates:
                candidate = proposal.candidate
                # This cross-pair gate deliberately precedes outcome counting,
                # exactly as in the serial v2.96 pipeline.
                if candidate.frames in accepted_bodies:
                    round_stats.reject("duplicate-replay")
                    continue
                child_result = _result_from_candidate(candidate, recipient.result)
                if (
                    auto_result_outcome_key(child_result)
                    >= auto_result_outcome_key(recipient.result)
                ):
                    round_stats.reject("not-better-than-recipient")
                    continue
                round_stats.beat_recipient += 1
                actual_gain = recipient.result.finish_tick - child_result.finish_tick
                diagnostic = (
                    f"splice round {generation}: recipient member "
                    f"{recipient.member_id}, donor member {donor.member_id}, "
                    f"A {proposal.recipient_entry_tick}.."
                    f"{proposal.recipient_exit_tick} <- B "
                    f"{proposal.donor_entry_tick}..{proposal.donor_exit_tick}, "
                    f"predicted gain {proposal.predicted_time_gain}, "
                    f"actual gain {actual_gain}"
                )
                mutations = recipient.mutations + (diagnostic,)
                candidate = replace(candidate, mutations=mutations)
                child_result = replace(
                    _result_from_candidate(candidate, recipient.result),
                    stats=AutoStats(),
                    diagnostics=recipient.result.diagnostics + (diagnostic,),
                )
                member = _AutoPopulationMember(
                    member_id=next_member_id,
                    result=child_result,
                    parent_member_ids=(recipient.member_id, donor.member_id),
                    generation=generation,
                    mutations=mutations,
                    splice_parent_pair=tuple(
                        sorted((recipient.member_id, donor.member_id))
                    ),
                    splice_interval=(
                        proposal.recipient_entry_tick,
                        proposal.recipient_exit_tick,
                        proposal.donor_entry_tick,
                        proposal.donor_exit_tick,
                    ),
                )
                next_member_id += 1
                members[member.member_id] = member
                accepted.append(member)
                round_stats.admitted += 1
                accepted_bodies.add(candidate.frames)
                child_key = auto_result_outcome_key(child_result)
                if child_key < checkpoint_key:
                    checkpoint_key = child_key
                    current = child_result
                    committed_mutations = member.mutations
                    if status is not None:
                        status(
                            f"[auto:splice] round {generation}: new global "
                            f"best from members {recipient.member_id}/"
                            f"{donor.member_id}; finish {child_result.finish_tick}"
                        )
                    if best_callback is not None:
                        best_callback(candidate)
        if accepted and status is not None:
            status(
                f"[auto:splice] round {generation}: admitted {len(accepted)} "
                "canonically verified section splice child(ren)"
            )
        return tuple(accepted)

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
                    # A ready splice may have cooperatively paused this task.
                    # Once that Future has unwound, the same deterministic
                    # task can resume whenever all currently ready splice
                    # jobs have been submitted.
                    existing.preempted = False
                    return existing
        return None

    def fill_slots(
        generation: int,
        task_ids: set[int],
        *,
        allow_speculation: bool,
    ) -> None:
        completed = completed_authoritative_members(task_ids)
        sync_splice_records(generation, completed)
        preempt_speculation_for_ready_splices(generation)
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

            completed = completed_authoritative_members(task_ids)
            sync_splice_records(generation, completed)
            ready_splice = next(
                (
                    record
                    for record in sorted(
                        splice_records.values(),
                        key=lambda item: (
                            item.generation,
                            item.recipient_member_id,
                            item.donor_member_id,
                        ),
                    )
                    if record.generation == generation
                    and record.output is None
                    and record.future is None
                ),
                None,
            )
            if ready_splice is not None:
                submit_splice_record(ready_splice)
                continue
            if not allow_speculation:
                return
            # All currently ready splice jobs are already running.  Refill any
            # remaining capacity with next-generation Auto work even while
            # those jobs finish.  If another parent completion creates more
            # pairs, the pre-emption pass above gives them priority again.
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

        founder_quotas = _offspring_quota_by_parent(
            ranked_founders,
            worker_count,
        )
        current_task_ids = {
            create_record(
                1,
                parent.member_id,
                offspring,
                authoritative=True,
            ).task_id
            for parent in ranked_founders
            for offspring in range(1, founder_quotas[parent.member_id] + 1)
        }

        while run_limit is None or run_index <= run_limit:
            suffix = f"/{run_limit}" if run_limit is not None else ""
            if status is not None:
                if run_index == 1:
                    description = (
                        f"starting {worker_count} independent searches from "
                        f"{len(founders)} unique parent(s), "
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

            while True:
                completed_now = completed_authoritative_members(current_task_ids)
                sync_splice_records(run_index, completed_now)
                auto_round_complete = len(completed_now) == len(current_task_ids)
                expected_pair_count = (
                    len(completed_now) * (len(completed_now) - 1)
                    if auto_round_complete
                    else -1
                )
                current_splice_records = tuple(
                    record
                    for record in splice_records.values()
                    if record.generation == run_index
                )
                splice_round_complete = (
                    auto_round_complete
                    and len(current_splice_records) == expected_pair_count
                    and all(
                        record.output is not None
                        for record in current_splice_records
                    )
                )
                if splice_round_complete:
                    break
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
            round_stats = _SpliceRoundStats()
            completed_members += commit_splice_outputs(
                completed_members, run_index, round_stats
            )
            survivors = _select_population_survivors(
                completed_members,
                survivor_count,
                enforce_parent_diversity=run_index > 1,
            )
            survivor_ids = {member.member_id for member in survivors}
            splice_members = tuple(
                member for member in completed_members if member.is_splice
            )
            round_stats.survivors = sum(
                member.member_id in survivor_ids for member in splice_members
            )
            round_stats.reject(
                "population-selection",
                sum(
                    member.member_id not in survivor_ids
                    for member in splice_members
                ),
            )
            completed_runs += 1
            if status is not None:
                lineages = len(
                    {
                        lineage
                        for member in survivors
                        for lineage in member.parent_member_ids
                    }
                )
                status(
                    f"[auto:parallel] round {run_index} complete: selected "
                    f"{len(survivors)}/{len(completed_members)} survivors from "
                    f"{lineages} immediate parent lineage(s); global best finish "
                    f"{current.finish_tick}"
                )
            _emit_splice_round_summary(run_index, round_stats, status)
            for key in tuple(splice_records):
                if key[0] == run_index:
                    del splice_records[key]
            for member in completed_members:
                prepared_splice_traces.pop(member.member_id, None)

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
                    # A ready splice may have cooperatively paused this exact
                    # provisional child.  Promotion makes it runnable again;
                    # if its old future is still unwinding, reap_done() will
                    # release the slot before fill_slots() resubmits it.
                    record.preempted = False
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
                {
                    future: record
                    for future, record in active.items()
                    if isinstance(record, _AutoTaskRecord)
                },
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
        # Pump even when every future has already been reaped: a worker can
        # have returned its result while its multiprocessing.Queue feeder is
        # still flushing, and executor.shutdown waits for that feeder.
        _shutdown_done, shutdown_checkpoints = _stop_executor(
            executor,
            tuple(active),
            stop_event,
            checkpoint_queue,
        )
        executor = None
        fold_checkpoints(shutdown_checkpoints)
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
        previous_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            # Ignore a second Ctrl+C before touching coordinator state so it
            # cannot bypass explicit worker shutdown or queue cleanup.
            drain_checkpoints()
            already_done = _successful_completed_futures(tuple(active))
            if already_done:
                reap_done(already_done)
            if executor is not None:
                shutdown_done, shutdown_checkpoints = _stop_executor(
                    executor,
                    tuple(active),
                    stop_event,
                    checkpoint_queue,
                )
                executor = None
                fold_checkpoints(shutdown_checkpoints)
                # Futures which returned normally during the cooperative grace
                # period still own verified outputs.  Failed/cancelled futures
                # were filtered by _stop_executor and are deliberately skipped.
                shutdown_done = tuple(
                    future for future in shutdown_done if future in active
                )
                if shutdown_done:
                    reap_done(shutdown_done)
        finally:
            try:
                try:
                    # A worker can enqueue its splice checkpoint immediately
                    # before cancellation or hard termination.  Drain once
                    # more only after every worker has stopped and the queue
                    # feeder has flushed.
                    drain_checkpoints()
                finally:
                    _close_checkpoint_queue(checkpoint_queue)
            finally:
                signal.signal(signal.SIGINT, previous_handler)
        if (
            splice_interrupt_checkpoint is not None
            and auto_result_outcome_key(splice_interrupt_checkpoint[1])
            < auto_result_outcome_key(current)
        ):
            _stable_key, current, committed_mutations = (
                splice_interrupt_checkpoint
            )
            if best_callback is not None:
                best_callback(current.best)
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
                _stop_executor(
                    executor,
                    tuple(active),
                    stop_event,
                    checkpoint_queue,
                )
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

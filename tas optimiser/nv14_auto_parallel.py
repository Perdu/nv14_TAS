"""Population-based process parallelism for :mod:`nv14_auto`.

Each worker runs one complete, independent Auto search. Completed searches
form a small evolutionary population.  A half-worker minimum survives each
round, while competitive trajectory-distinct splice niches can expand the
population up to one survivor per worker.  The coordinator may speculatively
start one generation ahead as worker slots become free, then cancels
descendants whose provisional parent is pruned when the round is finalised.
"""

from __future__ import annotations

import math
import multiprocessing
import os
import signal
import threading
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    CancelledError,
    Future,
    ProcessPoolExecutor,
    wait,
)
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from queue import Empty
from typing import Any

import nv14_auto as _auto_policy
from nv14_auto import (
    _ACTIVE_NATIVE_SESSION,
    AutoBeamSeed,
    AutoCandidate,
    AutoConfig,
    AutoProgress,
    AutoResult,
    AutoStats,
    SpliceAlignmentSpec,
    SpliceAuxiliarySeed,
    SplicePlanSpec,
    auto_candidate_outcome_key,
    auto_objective_value,
    evaluate_replay_with_sentinel,
    find_splice_section_plans,
    optimise_autonomous,
    repair_reference_segment_splice,
    select_splice_plans_for_pair,
    verify_trimmed_replay,
)
from nv14_checkpoint import (
    OPTIMISER_VERSION,
    AutoCheckpointError,
    optimiser_build_hash,
    read_auto_checkpoint,
    sha256_bytes,
    sha256_json,
    write_auto_checkpoint,
)
from nv14_engine import InputFrame, Level
from nv14_search import NativeSearchSession
from nv14_splice_index import PreparedSpliceTrace, prepare_splice_trace

ProgressCallback = Callable[[AutoProgress], None]
BestCallback = Callable[[AutoCandidate], None]
StatusCallback = Callable[[str], None]
SearchFunction = Callable[..., AutoResult]

# Planning can identify many near-identical corridors in two long traces.  The
# user-configurable per-pair plan limit keeps a round-end splice pass bounded
# while allowing deliberately deeper exploration when promising sections are
# known to exist.
_SECTIONAL_PROFILE_MAX_WINDOWS = 24
_SPLICE_TASK_ID_BASE = 1 << 63
_POPULATION_SPLICE_NICHE_TICKS = 12
_AUTO_STAGNATION_MIN_DISTANCE_GAIN_PX = 0.5

# Exact older releases can resume into v3.12 when every newly configurable
# value retains its historical/default behaviour. Pre-v3.11 releases start
# without pending auxiliary seeds; v3.11 retains its checkpointed seeds.
# Keep this allow-list exact so modified prior builds still fail validation.
_CHECKPOINT_COMPATIBLE_PREVIOUS_BUILDS = {
    (
        "3.05",
        "d0a7ea78c7b24de46bac1ff1c00774de833ef23107a07b743ebffe67d755e43e",
    ),
    (
        "3.06",
        "f394554d7ca12ac8a9e1d05b443a709a7e9597f7340e511ef3bd1e029d6f3475",
    ),
    (
        "3.07",
        "9ee3cd695e42f53bc157f9edb2970914a276ffc1e640e6a39e5d7817bbf8b79e",
    ),
    (
        "3.08",
        "0403296b82bdd9c711a35f719608cea5982da23413d2d476f4b2bfcaffdd47e5",
    ),
    (
        "3.09",
        "759ff49138cbafe636c515d26f033255b11079da4ffe1d5fb5ccb9d7073a8220",
    ),
    (
        "3.10",
        "48e851b680b4be8c460210fe270d8be51a7f622aa866c59a0112d05456a07879",
    ),
    (
        "3.11",
        "2ec99abdb9288c9774443f8a104eda2003eb1f4691c8d17075f285b45465c218",
    ),
}


@dataclass(frozen=True, slots=True)
class AutoSpliceDonor:
    """Lightweight completed replay retained only as a splice donor.

    ``frames`` is the canonically trimmed serialized body and therefore omits
    the neutral sentinel.  Native evaluations and trajectories deliberately do
    not cross the worker boundary; the coordinator verifies and prepares these
    few bodies once.
    """

    frames: tuple[InputFrame, ...]
    finish_tick: int
    objective_value: int
    pre_finish_exit_distance: float
    mutations: tuple[str, ...]
    gold_mask: int = 0
    gold_bonus_ticks: int = 0


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
    auxiliary_seeds: tuple[AutoBeamSeed, ...] = ()


@dataclass(frozen=True, slots=True)
class _AutoWorkerResult:
    result: AutoResult
    seed: int
    run_index: int
    worker_index: int
    task_id: int = 0
    parent_member_id: int = 0
    offspring_index: int = 1
    splice_donors: tuple[AutoSpliceDonor, ...] = ()


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
    # Selection identities deliberately describe two different generations.
    # ``recipient_member_id`` is the current-round worker result whose
    # prefix/suffix this replay retains. ``primary_family_id`` is the actual
    # previous-round survivor which bred that recipient.  A splice's ordinary
    # immediate parents alone cannot recover the latter after older members
    # have been pruned from coordinator history.
    recipient_member_id: int | None = None
    primary_family_id: int | None = None
    splice_parent_pair: tuple[int, int] | None = None
    splice_interval: tuple[int, int, int, int] | None = None
    splice_donors: tuple[AutoSpliceDonor, ...] = ()
    splice_donor_index: int = 0
    auxiliary_seeds: tuple[AutoBeamSeed, ...] = ()

    @property
    def parent_member_id(self) -> int | None:
        """Compatibility view for ordinary one-parent population members."""
        return self.parent_member_ids[0] if self.parent_member_ids else None

    @property
    def is_splice(self) -> bool:
        return self.splice_parent_pair is not None

    @property
    def selection_recipient_member_id(self) -> int:
        """Return the current-round recipient represented by this replay."""
        if self.recipient_member_id is not None:
            return self.recipient_member_id
        if self.is_splice and self.parent_member_ids:
            return self.parent_member_ids[0]
        return self.member_id

    @property
    def selection_primary_family_id(self) -> int:
        """Return the previous-round breeding family used for occupancy."""
        if self.primary_family_id is not None:
            return self.primary_family_id
        if self.parent_member_ids:
            return self.parent_member_ids[0]
        return self.member_id


@dataclass(frozen=True, slots=True)
class _AutoCheckpointResumeState:
    """Fully re-emulated state from one committed round boundary."""

    survivors: tuple[_AutoPopulationMember, ...]
    current: AutoResult
    aggregate_stats: AutoStats
    committed_mutations: tuple[str, ...]
    completed_runs: int
    completed_searches: int
    next_task_id: int
    next_splice_task_id: int
    next_member_id: int
    consecutive_stagnant_rounds: int
    last_improvement_round: int
    stagnation_outcome_key: tuple[int | float, ...]


@dataclass(frozen=True, slots=True)
class _PopulationSelection:
    """Selected survivors plus stable population-policy diagnostics."""

    survivors: tuple[_AutoPopulationMember, ...]
    minimum_target: int
    maximum_target: int
    target: int
    exact_unique_candidates: int
    competitive_splice_niches: int
    selected_splice_niches: int
    primary_family_occupancy: tuple[tuple[int, int], ...]


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
    sectional_donors: int = 0
    sectional_pairs: int = 0
    sectional_plans: int = 0
    sectional_attempted: int = 0
    sectional_admitted: int = 0
    sectional_survivors: int = 0
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
            "sectional_donors",
            "sectional_pairs",
            "sectional_plans",
            "sectional_attempted",
            "sectional_admitted",
            "sectional_survivors",
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
    sectional = ""
    if any(
        (
            stats.sectional_donors,
            stats.sectional_pairs,
            stats.sectional_plans,
            stats.sectional_attempted,
            stats.sectional_admitted,
            stats.sectional_survivors,
        )
    ):
        sectional = (
            f"sectional donors={stats.sectional_donors}, "
            f"pairs={stats.sectional_pairs}, plans={stats.sectional_plans}, "
            f"attempted={stats.sectional_attempted}, "
            f"admitted={stats.sectional_admitted}, "
            f"survivors={stats.sectional_survivors}; "
        )
    return (
        f"[auto:splice] round {round_index}: "
        f"pairs={stats.pairs}, corridors={stats.corridors}, "
        f"plans={stats.plans}, attempted={stats.attempted}, "
        f"repaired={stats.repaired}, completed={stats.completed}, "
        f"canonical={stats.canonical}, "
        f"beat-recipient={stats.beat_recipient}, admitted={stats.admitted}, "
        f"survivors={stats.survivors}; "
        f"{sectional}"
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


def _format_population_round_summary(
    round_index: int,
    selection: _PopulationSelection,
    *,
    candidate_count: int,
    global_best_finish_tick: int,
) -> str:
    occupancy = ",".join(
        f"{family_id}:{count}"
        for family_id, count in selection.primary_family_occupancy
    ) or "none"
    return (
        f"[auto:parallel] round {round_index} complete: "
        f"selected population={len(selection.survivors)}/{candidate_count}; "
        f"exact-unique replays={len(selection.survivors)}/"
        f"{selection.exact_unique_candidates} selected/eligible; "
        f"primary-family occupancy={occupancy}; "
        f"splice niches={selection.selected_splice_niches} selected; "
        f"competitive splice additions="
        f"{selection.competitive_splice_niches}; "
        f"global best finish {global_best_finish_tick}"
    )


def _emit_population_round_summary(
    round_index: int,
    selection: _PopulationSelection,
    *,
    candidate_count: int,
    global_best_finish_tick: int,
    status: StatusCallback | None,
) -> None:
    message = _format_population_round_summary(
        round_index,
        selection,
        candidate_count=candidate_count,
        global_best_finish_tick=global_best_finish_tick,
    )
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
    auxiliary_seeds: tuple[AutoBeamSeed, ...] = ()


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
    donor_source: "_SpliceDonorSource | None" = None


@dataclass(frozen=True, slots=True)
class _SpliceWorkerCandidate:
    """Canonically verified pair-local output awaiting ordered admission."""

    candidate: AutoCandidate
    recipient_entry_tick: int
    recipient_exit_tick: int
    donor_entry_tick: int
    donor_exit_tick: int
    predicted_time_gain: int
    donor_index: int = 0


@dataclass(frozen=True, slots=True)
class _SpliceWorkerCheckpoint:
    """One canonically verified splice preserved independently of its future."""

    task_id: int
    run_index: int
    recipient_member_id: int
    donor_member_id: int
    proposal: _SpliceWorkerCandidate
    donor_index: int = 0


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
    donor_index: int = 0
    auxiliary_seeds: tuple[SpliceAuxiliarySeed, ...] = ()


@dataclass(slots=True)
class _SpliceTaskRecord:
    """Coordinator lifecycle for an asynchronous ordered splice pair."""

    task_id: int
    generation: int
    recipient_member_id: int
    donor_member_id: int
    pair_order: int
    donor_index: int = 0
    worker_index: int = 0
    cancel_slot: int = -1
    future: Future[_SpliceWorkerResult] | None = None
    output: _SpliceWorkerResult | None = None


@dataclass(frozen=True, slots=True)
class _SpliceDonorSource:
    """One verified donor-only source prepared once by the coordinator."""

    owner_member_id: int
    donor_index: int
    donor: AutoSpliceDonor
    trace: PreparedSpliceTrace

    @property
    def is_sectional(self) -> bool:
        return self.donor_index > 0


class _AutoWorkerCancelled(Exception):
    """Internal cooperative-cancellation signal for an Auto worker."""


_AUTO_WORKER_CONTEXT: _AutoWorkerContext | None = None
_AUTO_WORKER_STOP_EVENT: Any | None = None
_AUTO_WORKER_CHECKPOINT_QUEUE: Any | None = None
_AUTO_WORKER_CANCEL_TOKENS: Any | None = None
_AUTO_WORKER_SPLICE_PARENT_CACHE: dict[
    tuple[int, int], _AutoPopulationMember
] = {}
_AUTO_WORKER_SPLICE_DONOR_CACHE: dict[
    tuple[int, int, int], AutoCandidate
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
    global _AUTO_WORKER_SPLICE_DONOR_CACHE
    global _AUTO_WORKER_NATIVE_SESSION
    _AUTO_WORKER_CONTEXT = context
    _AUTO_WORKER_STOP_EVENT = stop_event
    _AUTO_WORKER_CHECKPOINT_QUEUE = checkpoint_queue
    _AUTO_WORKER_CANCEL_TOKENS = cancel_tokens
    _AUTO_WORKER_SPLICE_PARENT_CACHE = {}
    _AUTO_WORKER_SPLICE_DONOR_CACHE = {}
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


@dataclass(frozen=True, slots=True)
class _SectionalDonorProfile:
    """Cheap native-screening evidence for one locally superior section."""

    objective_gain: int
    predicted_time_gain: int
    entry_recipient_tick: int
    exit_recipient_tick: int
    entry_donor_tick: int
    exit_donor_tick: int
    support: int
    distance: float

    @property
    def niche(self) -> tuple[int, int]:
        return (
            self.entry_recipient_tick // 12,
            self.exit_recipient_tick // 12,
        )


def _sectional_profile_centres(
    donor: AutoCandidate,
    donor_end: int,
) -> tuple[int, ...]:
    """Return one event-aware profiling centre per temporal route stratum."""

    if donor_end <= 0:
        return (0,)
    events = tuple(
        sorted(
            set(_auto_policy._candidate_input_transitions(donor))
            | set(donor.evaluation.jump_edges)
            | set(donor.evaluation.successful_jumps)
        )
    )
    centres: list[int] = []
    for index in range(_SECTIONAL_PROFILE_MAX_WINDOWS):
        start = math.floor(
            donor_end * index / _SECTIONAL_PROFILE_MAX_WINDOWS
        )
        end = math.ceil(
            donor_end * (index + 1) / _SECTIONAL_PROFILE_MAX_WINDOWS
        )
        target = round(
            donor_end
            * (2 * index + 1)
            / (2 * _SECTIONAL_PROFILE_MAX_WINDOWS)
        )
        nearby = (tick for tick in events if start <= tick <= end)
        centre = min(
            nearby,
            key=lambda tick: (abs(tick - target), tick),
            default=target,
        )
        if centre in centres and target not in centres:
            centre = target
        if centre not in centres:
            centres.append(centre)
    return tuple(centres)


def _native_sectional_donor_profile(
    recipient: AutoCandidate,
    donor: AutoCandidate,
    config: AutoConfig,
) -> _SectionalDonorProfile | None:
    """Profile bounded route-wide windows with the native matcher.

    This is screening policy, not splice acceptance.  Exact corridor planning,
    repair, canonical verification and campaign-outcome gates still run in the
    normal pair job for every retained donor.  Each temporal stratum snaps to
    its nearest input/jump event, preserving short gains around corner inputs,
    and falls back to its midpoint when no event is nearby.
    """

    recipient_analysis = _auto_policy._native_trace_analysis(
        recipient.evaluation
    )
    donor_analysis = _auto_policy._native_trace_analysis(donor.evaluation)
    if recipient_analysis is None or donor_analysis is None:
        return None
    if recipient.finish_tick is None or donor.finish_tick is None:
        return None
    donor_end = donor.finish_tick - 1
    recipient_end = min(
        recipient.finish_tick - 1,
        recipient.finish_tick - 1
        if config.range_end is None
        else config.range_end,
    )
    recipient_start = config.range_start
    if donor_end < 0 or recipient_end < recipient_start:
        return None

    window_radius = 6
    offset_limit = max(
        16,
        4 * config.max_alignment,
        min(64, config.effective_max_extra_ticks + config.max_alignment),
    )
    anchors: list[tuple[int, int, int, float, int, int]] = []
    for centre in _sectional_profile_centres(donor, donor_end):
        start = max(0, centre - window_radius)
        end = min(donor_end, centre + window_radius)
        minimum_offset = max(-offset_limit, recipient_start - end)
        maximum_offset = min(offset_limit, recipient_end - start)
        if minimum_offset > maximum_offset:
            continue
        try:
            raw = donor_analysis.find_splice_alignment(
                recipient_analysis,
                candidate_start_tick=start,
                candidate_end_tick=end,
                minimum_offset=minimum_offset,
                maximum_offset=maximum_offset,
                minimum_run_length=4,
                position_tolerance=config.alignment_position_tolerance,
                velocity_tolerance=config.alignment_velocity_tolerance,
                position_weight=_auto_policy._TRACE_POSITION_WEIGHT,
                velocity_weight=_auto_policy._TRACE_VELOCITY_WEIGHT,
                contact_mismatch_penalty=(
                    _auto_policy._TRACE_CONTACT_MISMATCH_PENALTY
                ),
                in_air_mismatch_penalty=(
                    _auto_policy._TRACE_IN_AIR_MISMATCH_PENALTY
                ),
                near_wall_mismatch_penalty=(
                    _auto_policy._TRACE_NEAR_WALL_MISMATCH_PENALTY
                ),
                gold_bit_penalty=_auto_policy._TRACE_GOLD_BIT_PENALTY,
                mine_bit_penalty=_auto_policy._TRACE_MINE_BIT_PENALTY,
                exit_bit_penalty=_auto_policy._TRACE_EXIT_BIT_PENALTY,
                locked_door_bit_penalty=(
                    _auto_policy._TRACE_LOCKED_DOOR_BIT_PENALTY
                ),
                trapdoor_bit_penalty=(
                    _auto_policy._TRACE_TRAPDOOR_BIT_PENALTY
                ),
            )
        except (AttributeError, OverflowError, RuntimeError, TypeError, ValueError):
            return None
        if raw is None:
            continue
        donor_tick = int(raw[0])
        recipient_tick = int(raw[1])
        if not recipient_start <= recipient_tick <= recipient_end:
            continue
        anchor = (
            donor_tick,
            recipient_tick,
            int(raw[2]),
            float(raw[3]),
            int(raw[6]),
            int(raw[7]),
        )
        if anchor not in anchors:
            anchors.append(anchor)
    anchors.sort(key=lambda item: (item[0], item[1]))

    best: tuple[tuple[object, ...], _SectionalDonorProfile] | None = None
    for entry_index, entry in enumerate(anchors):
        for exit_anchor in anchors[entry_index + 1 :]:
            donor_span = exit_anchor[0] - entry[0]
            recipient_span = exit_anchor[1] - entry[1]
            if donor_span < 12 or recipient_span < 12:
                continue
            predicted_gain = exit_anchor[2] - entry[2]
            objective_gain = (
                exit_anchor[4] - entry[4]
                if config.objective == _auto_policy.AUTO_OBJECTIVE_HIGHSCORE
                else predicted_gain
            )
            if objective_gain < 1:
                continue
            profile = _SectionalDonorProfile(
                objective_gain=objective_gain,
                predicted_time_gain=predicted_gain,
                entry_recipient_tick=entry[1],
                exit_recipient_tick=exit_anchor[1],
                entry_donor_tick=entry[0],
                exit_donor_tick=exit_anchor[0],
                support=min(entry[5], exit_anchor[5]),
                distance=entry[3] + exit_anchor[3],
            )
            rank = (
                -profile.objective_gain,
                -profile.predicted_time_gain,
                -profile.support,
                profile.distance,
                profile.entry_recipient_tick,
                profile.exit_recipient_tick,
                profile.entry_donor_tick,
                profile.exit_donor_tick,
            )
            if best is None or rank < best[0]:
                best = (rank, profile)
    return None if best is None else best[1]


def _select_worker_splice_donors(
    result: AutoResult,
    config: AutoConfig,
    *,
    limit: int = _auto_policy._SECTIONAL_ELITE_LIMIT,
) -> tuple[AutoSpliceDonor, ...]:
    """Reduce one worker's historical prearchive to bounded light payloads."""

    if limit < 1:
        return ()
    winner_key = bytes(
        int(frame.left)
        | (int(frame.right) << 1)
        | (int(frame.jump) << 2)
        for frame in result.frames
    )
    # Production searches maintain the bounded archive incrementally.  The
    # beam fallback supports older/custom SearchFunction results without making
    # normal worker finalisation scale with beam_width.
    archive = result.sectional_elites or result.beam
    candidates = _auto_policy._select_sectional_prearchive(
        archive,
        objective=result.objective,
        limit=_auto_policy._SECTIONAL_PREARCHIVE_LIMIT,
    )
    unique: dict[bytes, AutoCandidate] = {}
    for candidate in candidates:
        if not candidate.output_valid or candidate.finish_tick is None:
            continue
        body = candidate.frames
        if len(body) != candidate.finish_tick:
            continue
        key = bytes(
            int(frame.left)
            | (int(frame.right) << 1)
            | (int(frame.jump) << 2)
            for frame in body
        )
        if key == winner_key:
            continue
        incumbent = unique.get(key)
        if incumbent is None or auto_candidate_outcome_key(
            candidate, result.objective
        ) < auto_candidate_outcome_key(incumbent, result.objective):
            unique[key] = candidate

    ordered = sorted(
        unique.items(),
        key=lambda item: (
            auto_candidate_outcome_key(item[1], result.objective),
            item[0],
        ),
    )
    profiled = [
        (
            key,
            candidate,
            _native_sectional_donor_profile(result.best, candidate, config),
        )
        for key, candidate in ordered
    ]
    with_gain = sorted(
        (item for item in profiled if item[2] is not None),
        key=lambda item: (
            -item[2].objective_gain,
            -item[2].predicted_time_gain,
            -item[2].support,
            item[2].distance,
            auto_candidate_outcome_key(item[1], result.objective),
            item[0],
        ),
    )
    selected: list[tuple[bytes, AutoCandidate]] = []
    selected_keys: set[bytes] = set()
    selected_niches: set[tuple[int, int]] = set()
    for allow_duplicate_niche in (False, True):
        for key, candidate, profile in with_gain:
            if len(selected) >= limit:
                break
            if key in selected_keys:
                continue
            assert profile is not None
            if not allow_duplicate_niche and profile.niche in selected_niches:
                continue
            selected.append((key, candidate))
            selected_keys.add(key)
            selected_niches.add(profile.niche)
        if len(selected) >= limit:
            break

    # A donor can match another worker even when it has no beneficial bounded
    # section against its own winner.  Fill spare slots from the already
    # trajectory-diverse prearchive rather than discarding that opportunity.
    for key, candidate, _profile in profiled:
        if len(selected) >= limit:
            break
        if key in selected_keys:
            continue
        selected.append((key, candidate))
        selected_keys.add(key)

    donors: list[AutoSpliceDonor] = []
    for _key, candidate in selected:
        value = auto_objective_value(candidate.evaluation, result.objective)
        assert value is not None and candidate.finish_tick is not None
        proximity = candidate.evaluation.pre_finish_exit_distance
        if proximity is None or not math.isfinite(proximity):
            proximity = float("inf")
        donors.append(
            AutoSpliceDonor(
                frames=candidate.frames,
                finish_tick=candidate.finish_tick,
                objective_value=value,
                pre_finish_exit_distance=proximity,
                mutations=candidate.mutations,
                gold_mask=candidate.evaluation.final_gold_mask,
                gold_bonus_ticks=candidate.evaluation.gold_bonus_ticks,
            )
        )
    return tuple(donors)


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
    search_kwargs: dict[str, object] = {
        "progress": check_cancelled,
        "best_callback": checkpoint,
    }
    # Preserve compatibility with injected/test search functions that predate
    # v3.11.  The new keyword is semantically unnecessary when the payload is
    # empty, and is only supplied to the real entry point when there is work to
    # seed.
    if task.auxiliary_seeds:
        search_kwargs["auxiliary_seeds"] = task.auxiliary_seeds
    result = optimise_autonomous(
        context.level,
        task.frames,
        replace(context.config, seed=task.seed),
        **search_kwargs,
    )
    splice_donors = _select_worker_splice_donors(result, context.config)
    return _AutoWorkerResult(
        result=replace(result, beam=(), sectional_elites=()),
        seed=task.seed,
        run_index=task.run_index,
        worker_index=task.worker_index,
        task_id=task.task_id,
        parent_member_id=task.parent_member_id,
        offspring_index=task.offspring_index,
        splice_donors=splice_donors,
    )


def auto_result_outcome_key(result: AutoResult) -> tuple[int | float, ...]:
    return auto_candidate_outcome_key(result.best, result.objective)


def _significant_stagnation_improvement(
    previous_key: Sequence[int | float],
    current_key: Sequence[int | float],
) -> bool:
    """Return whether one committed round made a counter-resetting gain.

    Auto's durable outcome key is ``(validity, objective, exit_distance)``.
    Any primary objective improvement remains significant.  At an unchanged
    objective, the exit-distance tie-break must improve by at least half a
    pixel relative to the immediately preceding committed checkpoint.  The
    caller still stores every smaller global-best gain so several sub-threshold
    steps do not accumulate into one synthetic improvement.
    """
    previous_primary = tuple(previous_key[:2])
    current_primary = tuple(current_key[:2])
    if current_primary < previous_primary:
        return True
    if current_primary != previous_primary:
        return False

    previous_distance = float(previous_key[2])
    current_distance = float(current_key[2])
    if not math.isfinite(previous_distance):
        return math.isfinite(current_distance)
    if not math.isfinite(current_distance):
        return False
    return (
        previous_distance - current_distance
        >= _AUTO_STAGNATION_MIN_DISTANCE_GAIN_PX
    )


def _derive_auto_task_seed(base_seed: int, task_id: int) -> int:
    """Return a unique 64-bit seed for a dynamically scheduled worker task."""
    if task_id < 1:
        raise ValueError("task_id must be positive")
    if task_id == 1:
        return base_seed
    mask = (1 << 64) - 1
    return ((base_seed & mask) + 0x9E3779B97F4A7C15 * (task_id - 1)) & mask


def _population_survivor_count(worker_count: int) -> int:
    """Return the minimum survivor target, rounding half upward."""
    return max(1, (worker_count + 1) // 2)


def _population_replay_key(member: _AutoPopulationMember) -> bytes:
    """Return the exact serialized held-input identity of one member."""
    return bytes(
        int(frame.left)
        | (int(frame.right) << 1)
        | (int(frame.jump) << 2)
        for frame in member.result.frames
    )


def _population_rank_key(
    member: _AutoPopulationMember,
) -> tuple[object, ...]:
    """Return a stable outcome-first rank independent of input ordering."""
    return (
        *auto_result_outcome_key(member.result),
        _population_replay_key(member),
        member.member_id,
    )


def _exact_unique_population_members(
    members: Sequence[_AutoPopulationMember],
) -> tuple[_AutoPopulationMember, ...]:
    """Rank and collapse canonical held-input duplicates.

    Canonically identical trajectories cannot consume two worker-parent slots.
    Metadata should agree after verification; the outcome key remains the
    defensive first choice, followed by an ordinary member before an otherwise
    identical splice and finally stable member allocation order.
    """
    by_replay: dict[bytes, _AutoPopulationMember] = {}
    for member in members:
        replay_key = _population_replay_key(member)
        incumbent = by_replay.get(replay_key)
        choice_key = (
            auto_result_outcome_key(member.result),
            int(member.is_splice),
            member.member_id,
        )
        if incumbent is None or choice_key < (
            auto_result_outcome_key(incumbent.result),
            int(incumbent.is_splice),
            incumbent.member_id,
        ):
            by_replay[replay_key] = member
    return tuple(sorted(by_replay.values(), key=_population_rank_key))


def _population_splice_niche(
    member: _AutoPopulationMember,
) -> tuple[int, int, int] | None:
    """Return the coarse recipient-trajectory section replaced by a splice.

    Twelve-tick buckets match sectional-donor profiling.  Recipient identity
    is required at population scope because the same tick range on two worker
    trajectories represents two genuinely different route opportunities.
    """
    if not member.is_splice:
        return None
    interval = member.splice_interval
    if interval is None:
        return (member.selection_recipient_member_id, -1, -1)
    return (
        member.selection_recipient_member_id,
        max(0, interval[0]) // _POPULATION_SPLICE_NICHE_TICKS,
        interval[1] // _POPULATION_SPLICE_NICHE_TICKS,
    )


def _greedy_population_slate(
    ranked: Sequence[_AutoPopulationMember],
    target: int,
    *,
    recipient_cap: int,
    family_cap: int,
    splice_niche_cap: int,
) -> tuple[_AutoPopulationMember, ...]:
    """Select one deterministic slate under explicit diversity caps."""
    if target < 1:
        return ()
    selected: list[_AutoPopulationMember] = []
    recipients: Counter[int] = Counter()
    families: Counter[int] = Counter()
    niches: Counter[tuple[int, int, int]] = Counter()
    for member in ranked:
        if len(selected) >= target:
            break
        recipient_id = member.selection_recipient_member_id
        family_id = member.selection_primary_family_id
        niche = _population_splice_niche(member)
        if recipients[recipient_id] >= recipient_cap:
            continue
        if families[family_id] >= family_cap:
            continue
        if niche is not None and niches[niche] >= splice_niche_cap:
            continue
        selected.append(member)
        recipients[recipient_id] += 1
        families[family_id] += 1
        if niche is not None:
            niches[niche] += 1
    return tuple(selected)


def _population_cap_stages(
    target: int,
) -> tuple[tuple[int, int, int], ...]:
    """Relax family breadth before admitting repeat recipient trajectories."""
    if target < 1:
        return ()
    stages: list[tuple[int, int, int]] = []

    def add(stage: tuple[int, int, int]) -> None:
        if stage not in stages:
            stages.append(stage)

    # Preserve one current recipient for as long as possible.  Families begin
    # at two occupants and expand only when the candidate pool cannot fill the
    # requested population from the other breeding families.
    for family_cap in range(min(2, target), target + 1):
        add((1, family_cap, 1))
    # Only after every family limit has been exhausted may multiple exact-
    # distinct descendants of a current recipient enter the population.
    for recipient_cap in range(2, target + 1):
        add((recipient_cap, target, 1))
    # Exact replay uniqueness never relaxes.  Duplicate coarse splice niches
    # are the final fallback for a genuinely sparse candidate pool.
    add((target, target, target))
    return tuple(stages)


def _diverse_population_slate(
    ranked: Sequence[_AutoPopulationMember],
    target: int,
    *,
    enforce_diversity: bool = True,
) -> tuple[_AutoPopulationMember, ...]:
    """Fill a target by progressively relaxing soft occupancy constraints."""
    if target < 1:
        return ()
    # Primary family is a property of the current ordinary recipient: every
    # splice inherits it from that recipient.  The hierarchy makes the family
    # cap a partition of recipient groups and keeps the ranked greedy pass
    # maximum-cardinality at each stage. Reject corrupted/internal fixtures
    # rather than silently relaxing diversity around inconsistent ancestry.
    family_by_recipient: dict[int, int] = {}
    for member in ranked:
        recipient_id = member.selection_recipient_member_id
        family_id = member.selection_primary_family_id
        previous = family_by_recipient.setdefault(recipient_id, family_id)
        if previous != family_id:
            raise RuntimeError(
                "Auto population recipient belongs to multiple primary families"
            )
    stages = (
        _population_cap_stages(target)
        if enforce_diversity
        else ((target, target, target),)
    )
    best: tuple[_AutoPopulationMember, ...] = ()
    for recipient_cap, family_cap, niche_cap in stages:
        selected = _greedy_population_slate(
            ranked,
            target,
            recipient_cap=recipient_cap,
            family_cap=family_cap,
            splice_niche_cap=niche_cap,
        )
        if len(selected) > len(best):
            best = selected
        if len(selected) == target:
            return selected
    return best


def _competitive_splice_representatives(
    ranked: Sequence[_AutoPopulationMember],
    minimum_target: int,
    maximum_target: int,
) -> tuple[_AutoPopulationMember, ...]:
    """Return strong distinct splice niches which earn population additions.

    The old minimum population supplies a non-circular quality frontier: a
    splice is competitive only when it is no worse than the last of the best
    ``minimum_target`` exact-unique ordinary worker results.  When exact replay
    duplication leaves fewer ordinary results than that, every admitted splice
    remains eligible.  Admission itself has already required canonical
    completion and a strict improvement over the splice recipient.
    """
    addition_limit = max(0, maximum_target - minimum_target)
    if addition_limit == 0:
        return ()
    ordinary = tuple(member for member in ranked if not member.is_splice)
    cutoff = (
        auto_result_outcome_key(ordinary[minimum_target - 1].result)
        if minimum_target > 0 and len(ordinary) >= minimum_target
        else None
    )
    selected: list[_AutoPopulationMember] = []
    niches: set[tuple[int, int, int]] = set()
    for member in ranked:
        if not member.is_splice:
            continue
        if cutoff is not None and auto_result_outcome_key(member.result) > cutoff:
            continue
        niche = _population_splice_niche(member)
        assert niche is not None
        if niche in niches:
            continue
        selected.append(member)
        niches.add(niche)
        if len(selected) >= addition_limit:
            break
    return tuple(selected)


def _select_adaptive_population(
    members: Sequence[_AutoPopulationMember],
    worker_count: int,
) -> _PopulationSelection:
    """Select an exact-unique, adaptive half-to-full worker population."""
    minimum_target = _population_survivor_count(worker_count)
    maximum_target = max(1, worker_count)
    ranked = _exact_unique_population_members(members)
    representatives = _competitive_splice_representatives(
        ranked,
        minimum_target,
        maximum_target,
    )
    target = min(
        len(ranked),
        maximum_target,
        minimum_target + len(representatives),
    )
    survivors = _diverse_population_slate(
        ranked,
        target,
    )
    selected_niches = {
        niche
        for member in survivors
        if (niche := _population_splice_niche(member)) is not None
    }
    occupancy = Counter(
        member.selection_primary_family_id for member in survivors
    )
    return _PopulationSelection(
        survivors=survivors,
        minimum_target=minimum_target,
        maximum_target=maximum_target,
        target=target,
        exact_unique_candidates=len(ranked),
        competitive_splice_niches=len(representatives),
        selected_splice_niches=len(selected_niches),
        primary_family_occupancy=tuple(sorted(occupancy.items())),
    )


def _select_population_survivors(
    members: Sequence[_AutoPopulationMember],
    survivor_count: int,
    *,
    enforce_parent_diversity: bool,
) -> tuple[_AutoPopulationMember, ...]:
    """Select a fixed-size provisional population with hard replay dedup."""
    ranked = _exact_unique_population_members(members)
    target = min(max(0, survivor_count), len(ranked))
    return _diverse_population_slate(
        ranked,
        target,
        enforce_diversity=enforce_parent_diversity,
    )


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


def _offspring_keys_breadth_first(
    generation: int,
    survivors: Sequence[_AutoPopulationMember],
    worker_count: int,
    *,
    first_only: bool = False,
) -> tuple[tuple[int, int, int], ...]:
    """Return quota-backed child keys with every first child before seconds."""
    quotas = _offspring_quota_by_parent(survivors, worker_count)
    if not quotas:
        return ()
    if sum(quotas.values()) != worker_count:
        raise RuntimeError("Auto offspring quotas do not fill every worker")
    maximum_offspring = 1 if first_only else max(quotas.values())
    return tuple(
        (generation, parent.member_id, offspring_index)
        for offspring_index in range(1, maximum_offspring + 1)
        for parent in survivors
        if offspring_index <= quotas[parent.member_id]
    )


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
        sectional_elites=(),
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


def _canonical_sectional_donor(
    level: Level,
    donor: AutoSpliceDonor,
    objective: str,
):
    """Verify donor metadata and return its native-backed evaluation."""

    if donor.finish_tick < 0 or len(donor.frames) != donor.finish_tick:
        return None
    try:
        evaluation = verify_trimmed_replay(
            level,
            donor.frames,
            expected_finish_tick=donor.finish_tick,
            expected_gold_mask=donor.gold_mask,
            expected_gold_bonus_ticks=donor.gold_bonus_ticks,
        )
    except (RuntimeError, ValueError):
        return None
    value = auto_objective_value(evaluation, objective)
    if value != donor.objective_value:
        return None
    proximity = evaluation.pre_finish_exit_distance
    if proximity is None or not math.isfinite(proximity):
        proximity = float("inf")
    if not math.isclose(
        proximity,
        donor.pre_finish_exit_distance,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        return None
    return evaluation


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


def _select_auxiliary_beam_seeds(
    candidates: Sequence[SpliceAuxiliarySeed],
    config: AutoConfig,
    *,
    recipient_working_frames: Sequence[InputFrame],
) -> tuple[AutoBeamSeed, ...]:
    """Select unique promising frontiers without favouring splice kind."""
    limit = min(
        config.auxiliary_beam_seeds,
        max(0, config.beam_width - 1),
    )
    if limit == 0:
        return ()
    recipient_key = _auto_policy._frame_key(recipient_working_frames)

    def stable_rank(candidate: SpliceAuxiliarySeed) -> tuple[object, ...]:
        return (*candidate.priority, candidate.beam_seed.description)

    unique: dict[bytes, SpliceAuxiliarySeed] = {}
    for candidate in candidates:
        key = _auto_policy._frame_key(candidate.beam_seed.working_frames)
        if key == recipient_key:
            continue
        incumbent = unique.get(key)
        if incumbent is None or stable_rank(candidate) < stable_rank(incumbent):
            unique[key] = candidate
    ordered = sorted(unique.values(), key=stable_rank)
    return tuple(candidate.beam_seed for candidate in ordered[:limit])


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


def _native_splice_donor(
    level: Level,
    generation: int,
    source: _SpliceDonorSource,
    objective: str,
) -> AutoCandidate:
    """Reconstruct one donor with a process-local native trajectory once."""

    global _AUTO_WORKER_SPLICE_DONOR_CACHE
    key = (generation, source.owner_member_id, source.donor_index)
    cached = _AUTO_WORKER_SPLICE_DONOR_CACHE.get(key)
    if cached is not None:
        return cached
    if _AUTO_WORKER_SPLICE_DONOR_CACHE and any(
        cached_generation != generation
        for cached_generation, _owner_id, _donor_index
        in _AUTO_WORKER_SPLICE_DONOR_CACHE
    ):
        _AUTO_WORKER_SPLICE_DONOR_CACHE = {
            cached_key: value
            for cached_key, value in _AUTO_WORKER_SPLICE_DONOR_CACHE.items()
            if cached_key[0] == generation
        }
    if not isinstance(level, Level):
        evaluation = source.trace.source
        if evaluation is None:
            raise TypeError("sectional donor fixture has no source evaluation")
    else:
        evaluation = evaluate_replay_with_sentinel(level, source.donor.frames)
    if (
        evaluation.finish_tick != source.donor.finish_tick
        or auto_objective_value(evaluation, objective)
        != source.donor.objective_value
    ):
        raise RuntimeError("sectional donor changed during worker reconstruction")
    working = source.donor.frames + (InputFrame(),)
    candidate = AutoCandidate(
        working_frames=working,
        evaluation=evaluation,
        origin=(
            "population-donor"
            if source.donor_index == 0
            else "sectional-donor"
        ),
        mutations=source.donor.mutations,
        sentinel_verified=True,
        replay_key=bytes(
            int(frame.left)
            | (int(frame.right) << 1)
            | (int(frame.jump) << 2)
            for frame in working
        ),
    )
    _AUTO_WORKER_SPLICE_DONOR_CACHE[key] = candidate
    return candidate


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
    # Planning consumes only the already prepared, process-safe trace indexes.
    # Delay native replay reconstruction until a real plan reaches repair; the
    # common no-corridor/no-plan path then performs no extra simulation.
    recipient = task.recipient
    if task.donor_source is None:
        donor_member_id = task.donor.member_id
        donor_index = 0
        donor_trace = task.donor_trace
    else:
        donor_member_id = task.donor_source.owner_member_id
        donor_index = task.donor_source.donor_index
        donor_trace = task.donor_source.trace
    stats = _SpliceRoundStats(
        pairs=1,
        sectional_pairs=int(donor_index > 0),
    )
    repair_stats = AutoStats()
    outputs: list[_SpliceWorkerCandidate] = []
    auxiliary_limit = min(
        config.auxiliary_beam_seeds,
        max(0, config.beam_width - 1),
    )
    auxiliary_archive: dict[bytes, SpliceAuxiliarySeed] = {}

    def retain_auxiliary(seeds: Sequence[SpliceAuxiliarySeed]) -> None:
        if auxiliary_limit == 0:
            return
        for seed in seeds:
            key = _auto_policy._frame_key(seed.beam_seed.working_frames)
            incumbent = auxiliary_archive.get(key)
            if incumbent is None or (
                seed.priority,
                seed.beam_seed.description,
            ) < (
                incumbent.priority,
                incumbent.beam_seed.description,
            ):
                auxiliary_archive[key] = seed
        while len(auxiliary_archive) > auxiliary_limit:
            worst_key = max(
                auxiliary_archive,
                key=lambda item: (
                    auxiliary_archive[item].priority,
                    auxiliary_archive[item].beam_seed.description,
                ),
            )
            del auxiliary_archive[worst_key]

    def finish() -> _SpliceWorkerResult:
        return _SpliceWorkerResult(
            task_id=task.task_id,
            run_index=task.run_index,
            recipient_member_id=recipient.member_id,
            donor_member_id=donor_member_id,
            candidates=tuple(outputs),
            splice_stats=stats,
            auto_stats=repair_stats,
            donor_index=donor_index,
            auxiliary_seeds=tuple(
                sorted(
                    auxiliary_archive.values(),
                    key=lambda seed: (
                        seed.priority,
                        seed.beam_seed.description,
                    ),
                )
            ),
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
            donor_member_id=donor_member_id,
            candidates=(),
            splice_stats=stats,
            auto_stats=repair_stats,
            donor_index=donor_index,
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
        donor_trace,
        alignment_spec,
        plan_spec,
        anchor_runs_observer=observe_anchor_runs,
    )
    stats.plans += len(plans)
    if donor_index > 0:
        stats.sectional_plans += len(plans)
    if not plans:
        stats.reject("no-corridors" if corridor_count == 0 else "no-plans")
        return finish()

    recipient = _native_splice_parent(level, task.run_index, task.recipient)
    if task.donor_source is None:
        donor_candidate = _native_splice_parent(
            level, task.run_index, task.donor
        ).result.best
    else:
        donor_candidate = _native_splice_donor(
            level, task.run_index, task.donor_source, config.objective
        )

    max_body_length = len(recipient.result.best.working_frames) - 1
    selected_plans = select_splice_plans_for_pair(
        plans,
        config.splice_plans_per_pair,
        objective=config.objective,
    )
    for plan in selected_plans:
        if _worker_cancelled(task):
            # A previous plan may already have produced a canonical replay.
            # Return that partial successful result instead of converting the
            # entire pair future into cancellation and losing verified work.
            if outputs or auxiliary_archive:
                return finish()
            raise _AutoWorkerCancelled
        stats.attempted += 1
        if donor_index > 0:
            stats.sectional_attempted += 1
        stats.predicted_gains.append(plan.predicted_time_gain)
        repair = repair_reference_segment_splice(
            level,
            recipient.result.best,
            donor_candidate,
            plan,
            config=config,
            max_body_length=max_body_length,
            required_gold_mask=task.required_gold_mask,
        )
        retain_auxiliary(getattr(repair, "auxiliary_seeds", ()))
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
            donor_index=donor_index,
        )
        outputs.append(proposal)
        checkpoint_queue = _AUTO_WORKER_CHECKPOINT_QUEUE
        if checkpoint_queue is not None:
            checkpoint_queue.put(
                _SpliceWorkerCheckpoint(
                    task_id=task.task_id,
                    run_index=task.run_index,
                    recipient_member_id=recipient.member_id,
                    donor_member_id=donor_member_id,
                    proposal=proposal,
                    donor_index=donor_index,
                )
            )

    return finish()


def _run_serial_sectional_splices(
    level: Level,
    result: AutoResult,
    donors: Sequence[AutoSpliceDonor],
    config: AutoConfig,
    *,
    run_index: int,
    required_gold_mask: int = 0,
    auxiliary_seed_sink: list[AutoBeamSeed] | None = None,
) -> tuple[AutoResult | None, _SpliceRoundStats, AutoStats, bool]:
    """Give one-worker sectional donors the normal independent pair limits."""

    global _AUTO_WORKER_STOP_EVENT
    global _AUTO_WORKER_CHECKPOINT_QUEUE
    global _AUTO_WORKER_CANCEL_TOKENS
    global _AUTO_WORKER_SPLICE_PARENT_CACHE
    global _AUTO_WORKER_SPLICE_DONOR_CACHE
    global _AUTO_WORKER_NATIVE_SESSION

    stats = _SpliceRoundStats()
    aggregate_repair_stats = AutoStats()
    if not donors:
        return None, stats, aggregate_repair_stats, False

    recipient = _AutoPopulationMember(
        member_id=0,
        result=replace(result, beam=(), sectional_elites=()),
        parent_member_ids=(),
        generation=run_index,
        mutations=result.best.mutations,
        recipient_member_id=0,
        primary_family_id=0,
    )
    recipient_trace = prepare_splice_trace(
        result.best.evaluation, result.frames
    )
    accepted_bodies = {result.frames, *(donor.frames for donor in donors)}
    best_child: AutoResult | None = None
    auxiliary_pool: list[SpliceAuxiliarySeed] = []
    interrupted = False
    session = NativeSearchSession(level) if isinstance(level, Level) else None
    token = _ACTIVE_NATIVE_SESSION.set((level, session))
    previous_worker_controls = (
        _AUTO_WORKER_STOP_EVENT,
        _AUTO_WORKER_CHECKPOINT_QUEUE,
        _AUTO_WORKER_CANCEL_TOKENS,
    )
    previous_worker_caches = (
        _AUTO_WORKER_SPLICE_PARENT_CACHE,
        _AUTO_WORKER_SPLICE_DONOR_CACHE,
        _AUTO_WORKER_NATIVE_SESSION,
    )
    _AUTO_WORKER_STOP_EVENT = None
    _AUTO_WORKER_CHECKPOINT_QUEUE = None
    _AUTO_WORKER_CANCEL_TOKENS = None
    # Serial campaigns share the coordinator process.  Keep worker-native
    # reconstructions scoped to this campaign so repeated one-worker calls
    # cannot collide on the compact (generation, member) cache keys.
    _AUTO_WORKER_SPLICE_PARENT_CACHE = {}
    _AUTO_WORKER_SPLICE_DONOR_CACHE = {}
    _AUTO_WORKER_NATIVE_SESSION = None
    try:
        for donor_index, donor in enumerate(donors, start=1):
            evaluation = _canonical_sectional_donor(
                level, donor, config.objective
            )
            if evaluation is None:
                stats.reject("sectional-donor-verification")
                continue
            stats.sectional_donors += 1
            source = _SpliceDonorSource(
                owner_member_id=recipient.member_id,
                donor_index=donor_index,
                donor=donor,
                trace=prepare_splice_trace(evaluation, donor.frames),
            )
            task = _SpliceWorkerTask(
                recipient=recipient,
                donor=recipient,
                recipient_trace=recipient_trace,
                donor_trace=source.trace,
                run_index=run_index,
                task_id=_SPLICE_TASK_ID_BASE | donor_index,
                required_gold_mask=required_gold_mask,
                donor_source=source,
            )
            output = _run_splice_worker_in_session(
                task, _AutoWorkerContext(level, config)
            )
            stats.merge(output.splice_stats)
            aggregate_repair_stats = _sum_stats(
                aggregate_repair_stats, output.auto_stats
            )
            auxiliary_pool.extend(output.auxiliary_seeds)
            for proposal in output.candidates:
                candidate = proposal.candidate
                if candidate.frames in accepted_bodies:
                    stats.reject("duplicate-replay")
                    continue
                child = _result_from_candidate(candidate, result)
                if (
                    auto_result_outcome_key(child)
                    >= auto_result_outcome_key(result)
                ):
                    stats.reject("not-better-than-recipient")
                    continue
                stats.beat_recipient += 1
                stats.admitted += 1
                stats.sectional_admitted += 1
                actual_gain = result.finish_tick - child.finish_tick
                diagnostic = (
                    f"splice round {run_index}: recipient member 0, "
                    f"donor member 0 sectional #{donor_index}, A "
                    f"{proposal.recipient_entry_tick}.."
                    f"{proposal.recipient_exit_tick} <- B "
                    f"{proposal.donor_entry_tick}..{proposal.donor_exit_tick}, "
                    f"predicted gain {proposal.predicted_time_gain}, "
                    f"actual gain {actual_gain}"
                )
                candidate = replace(
                    candidate,
                    mutations=result.best.mutations + (diagnostic,),
                )
                child = replace(
                    _result_from_candidate(candidate, result),
                    stats=AutoStats(),
                    diagnostics=result.diagnostics + (diagnostic,),
                )
                accepted_bodies.add(candidate.frames)
                if (
                    best_child is None
                    or auto_result_outcome_key(child)
                    < auto_result_outcome_key(best_child)
                ):
                    best_child = child
    except KeyboardInterrupt:
        # A prior donor may already have produced a canonically verified child.
        # Hand it back to the serial coordinator before honouring the stop.
        interrupted = True
    finally:
        (
            _AUTO_WORKER_STOP_EVENT,
            _AUTO_WORKER_CHECKPOINT_QUEUE,
            _AUTO_WORKER_CANCEL_TOKENS,
        ) = previous_worker_controls
        (
            _AUTO_WORKER_SPLICE_PARENT_CACHE,
            _AUTO_WORKER_SPLICE_DONOR_CACHE,
            _AUTO_WORKER_NATIVE_SESSION,
        ) = previous_worker_caches
        _ACTIVE_NATIVE_SESSION.reset(token)
    if best_child is not None:
        stats.survivors = 1
        stats.sectional_survivors = 1
    if auxiliary_seed_sink is not None:
        auxiliary_seed_sink.extend(
            _select_auxiliary_beam_seeds(
                auxiliary_pool,
                config,
                recipient_working_frames=result.best.working_frames,
            )
        )
    return best_child, stats, aggregate_repair_stats, interrupted


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
        sectional_elites=(),
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


_AUTO_CHECKPOINT_SEED_STRATEGY = (
    "stable-generation-parent-replay-offspring-v1"
)


def _input_frame_value(frame: InputFrame) -> int:
    return (
        int(frame.left)
        | (int(frame.right) << 1)
        | (int(frame.jump) << 2)
        | (int(bool(frame.jump_trigger)) << 3)
        | (int(frame.jump_trigger is None) << 4)
    )


def _checkpoint_frames(frames: Sequence[InputFrame]) -> list[int]:
    return [_input_frame_value(frame) for frame in frames]


def _frames_from_checkpoint(value: object, *, label: str) -> tuple[InputFrame, ...]:
    if not isinstance(value, list):
        raise AutoCheckpointError(f"{label} must contain replay frames")
    frames: list[InputFrame] = []
    for index, raw in enumerate(value):
        if type(raw) is not int or not 0 <= raw <= 0x1F:
            raise AutoCheckpointError(
                f"{label} frame {index} is not a checkpoint input value"
            )
        frames.append(
            InputFrame(
                left=bool(raw & 0x1),
                right=bool(raw & 0x2),
                jump=bool(raw & 0x4),
                jump_trigger=None if raw & 0x10 else bool(raw & 0x8),
            )
        )
    return tuple(frames)


def _replay_sha256(frames: Sequence[InputFrame]) -> str:
    return sha256_bytes(bytes(_input_frame_value(frame) for frame in frames))


def _checkpoint_number(value: float) -> int | float | str:
    if type(value) is int:
        return value
    number = float(value)
    if math.isfinite(number):
        return number
    if math.isinf(number):
        return "+inf" if number > 0 else "-inf"
    raise AutoCheckpointError("NaN cannot be stored in an Auto checkpoint")


def _number_from_checkpoint(value: object, *, label: str) -> int | float:
    if type(value) is int:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if value == "+inf":
        return float("inf")
    if value == "-inf":
        return float("-inf")
    raise AutoCheckpointError(f"{label} is not a valid checkpoint number")


def _outcome_key_checkpoint(key: Sequence[int | float]) -> list[int | float | str]:
    return [_checkpoint_number(value) for value in key]


def _outcome_key_from_checkpoint(
    value: object, *, label: str
) -> tuple[int | float, ...]:
    if not isinstance(value, list) or not value:
        raise AutoCheckpointError(f"{label} must be a non-empty outcome key")
    return tuple(
        _number_from_checkpoint(item, label=f"{label}[{index}]")
        for index, item in enumerate(value)
    )


def _string_tuple_from_checkpoint(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AutoCheckpointError(f"{label} must be a string array")
    return tuple(value)


def _int_from_checkpoint(
    mapping: Mapping[str, object],
    key: str,
    *,
    label: str,
    minimum: int | None = 0,
) -> int:
    value = mapping.get(key)
    if type(value) is not int or (
        minimum is not None and value < minimum
    ):
        minimum_text = (
            "an integer"
            if minimum is None
            else f"an integer of at least {minimum}"
        )
        raise AutoCheckpointError(
            f"{label}.{key} must be {minimum_text}"
        )
    return value


def _optional_int_from_checkpoint(
    mapping: Mapping[str, object], key: str, *, label: str
) -> int | None:
    value = mapping.get(key)
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise AutoCheckpointError(f"{label}.{key} must be null or non-negative")
    return value


def _int_tuple_from_checkpoint(
    value: object,
    *,
    label: str,
    length: int | None = None,
) -> tuple[int, ...]:
    if not isinstance(value, list) or not all(
        type(item) is int and item >= 0 for item in value
    ):
        raise AutoCheckpointError(f"{label} must be a non-negative integer array")
    if length is not None and len(value) != length:
        raise AutoCheckpointError(f"{label} must contain exactly {length} values")
    return tuple(value)


def _splice_interval_from_checkpoint(
    value: object,
    *,
    label: str,
) -> tuple[int, int, int, int]:
    """Restore a splice interval, including v3.09's replay-origin entry."""
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not all(type(item) is int for item in value)
    ):
        raise AutoCheckpointError(f"{label} must contain exactly four integers")
    recipient_entry, recipient_exit, donor_entry, donor_exit = value
    starts_at_initial_state = recipient_entry == donor_entry == -1
    if not starts_at_initial_state and (
        recipient_entry < 0 or donor_entry < 0
    ):
        raise AutoCheckpointError(
            f"{label} entry ticks must both be -1 or both be non-negative"
        )
    if recipient_exit < 0 or donor_exit < 0:
        raise AutoCheckpointError(f"{label} exit ticks must be non-negative")
    if recipient_exit <= recipient_entry or donor_exit <= donor_entry:
        raise AutoCheckpointError(f"{label} exits must follow their entries")
    return recipient_entry, recipient_exit, donor_entry, donor_exit


def _auto_stats_checkpoint(stats: AutoStats) -> dict[str, int]:
    return {field_info.name: getattr(stats, field_info.name) for field_info in fields(AutoStats)}


def _auto_stats_from_checkpoint(value: object) -> AutoStats:
    if not isinstance(value, Mapping):
        raise AutoCheckpointError("checkpoint aggregate_stats must be an object")
    restored: dict[str, int] = {}
    for field_info in fields(AutoStats):
        raw = value.get(field_info.name)
        if type(raw) is not int or raw < 0:
            raise AutoCheckpointError(
                f"checkpoint aggregate_stats.{field_info.name} must be non-negative"
            )
        restored[field_info.name] = raw
    return AutoStats(**restored)


def _auto_checkpoint_identity(
    level: object,
    source_frames: Sequence[InputFrame],
    parent_frames: Sequence[Sequence[InputFrame]],
    config: AutoConfig,
    *,
    worker_count: int,
    requested_runs: int,
    stagnation_runs: int,
    level_identifier: str | None,
) -> dict[str, object]:
    level_source = getattr(level, "source_level_string", None)
    if not isinstance(level_source, str) or not level_source:
        # Direct API test doubles and alternative Level implementations can
        # still supply a stable identifier. Real parsed levels carry the exact
        # source string and therefore use the stronger path above.
        level_source = level_identifier or (
            f"{type(level).__module__}.{type(level).__qualname__}"
        )
    config_values = {
        field_info.name: getattr(config, field_info.name)
        for field_info in fields(AutoConfig)
    }
    configuration = {
        "auto_config": config_values,
        "requested_runs": requested_runs,
        "seed_strategy": _AUTO_CHECKPOINT_SEED_STRATEGY,
        "stagnation_runs": stagnation_runs,
        "workers": worker_count,
    }
    return {
        "optimiser_version": OPTIMISER_VERSION,
        "optimiser_build_sha256": optimiser_build_hash(),
        "level_identifier": level_identifier,
        "level_sha256": sha256_bytes(level_source.encode("utf-8")),
        "simulate_enemies": bool(getattr(level, "simulate_enemies", False)),
        "input_replay_sha256": _replay_sha256(source_frames),
        "parent_replay_sha256": [
            _replay_sha256(frames) for frames in parent_frames
        ],
        "configuration": configuration,
        "configuration_sha256": sha256_json(configuration),
    }


def _validate_checkpoint_identity(
    stored: object,
    expected: Mapping[str, object],
) -> None:
    if not isinstance(stored, Mapping):
        raise AutoCheckpointError("Auto checkpoint identity is missing")
    stored_build = (
        stored.get("optimiser_version"),
        stored.get("optimiser_build_sha256"),
    )
    expected_build = (
        expected.get("optimiser_version"),
        expected.get("optimiser_build_sha256"),
    )
    previous_build_compatible = (
        expected.get("optimiser_version") == OPTIMISER_VERSION == "3.12"
        and stored_build in _CHECKPOINT_COMPATIBLE_PREVIOUS_BUILDS
    )
    build_compatible = stored_build == expected_build or previous_build_compatible

    configuration_compatible = (
        stored.get("configuration_sha256")
        == expected.get("configuration_sha256")
    )
    if not configuration_compatible and previous_build_compatible:
        # v3.08 and earlier used a fixed two plans per pair; v3.10 and earlier
        # predate auxiliary beam seeds. Inject only absent historical defaults;
        # v3.11's explicit seed setting must still match the current invocation.
        stored_configuration = stored.get("configuration")
        expected_configuration = expected.get("configuration")
        if (
            isinstance(stored_configuration, Mapping)
            and isinstance(expected_configuration, Mapping)
            and isinstance(stored_configuration.get("auto_config"), Mapping)
        ):
            normalised_configuration = dict(stored_configuration)
            normalised_auto_config = dict(stored_configuration["auto_config"])
            normalised_auto_config.setdefault("splice_plans_per_pair", 2)
            normalised_auto_config.setdefault("auxiliary_beam_seeds", 1)
            normalised_configuration["auto_config"] = normalised_auto_config
            normalised_expected = dict(expected_configuration)
            expected_auto_config = normalised_expected.get("auto_config")
            if isinstance(expected_auto_config, Mapping):
                normalised_expected_auto_config = dict(expected_auto_config)
                normalised_expected_auto_config.setdefault(
                    "splice_plans_per_pair", 2
                )
                normalised_expected_auto_config.setdefault(
                    "auxiliary_beam_seeds", 1
                )
                normalised_expected["auto_config"] = (
                    normalised_expected_auto_config
                )
            configuration_compatible = (
                normalised_configuration == normalised_expected
            )
    labels = {
        "level_identifier": "level identifier",
        "level_sha256": "level data",
        "simulate_enemies": "enemy-simulation setting",
        "input_replay_sha256": "input replay",
        "parent_replay_sha256": "starting parent replays",
    }
    mismatches = ([] if build_compatible else ["optimiser version/build"]) + [
        label
        for key, label in labels.items()
        if stored.get(key) != expected.get(key)
    ]
    if not configuration_compatible:
        mismatches.append("Auto configuration")
    if mismatches:
        raise AutoCheckpointError(
            "Auto checkpoint is incompatible with the current invocation: "
            + ", ".join(mismatches)
        )


def _splice_donor_checkpoint(donor: AutoSpliceDonor) -> dict[str, object]:
    return {
        "frames": _checkpoint_frames(donor.frames),
        "finish_tick": donor.finish_tick,
        "objective_value": donor.objective_value,
        "pre_finish_exit_distance": _checkpoint_number(
            donor.pre_finish_exit_distance
        ),
        "mutations": list(donor.mutations),
        "gold_mask": donor.gold_mask,
        "gold_bonus_ticks": donor.gold_bonus_ticks,
    }


def _splice_donor_from_checkpoint(value: object, *, label: str) -> AutoSpliceDonor:
    if not isinstance(value, Mapping):
        raise AutoCheckpointError(f"{label} must be an object")
    return AutoSpliceDonor(
        frames=_frames_from_checkpoint(value.get("frames"), label=f"{label}.frames"),
        finish_tick=_int_from_checkpoint(
            value, "finish_tick", label=label
        ),
        objective_value=_int_from_checkpoint(
            value, "objective_value", label=label, minimum=None
        ),
        pre_finish_exit_distance=float(
            _number_from_checkpoint(
                value.get("pre_finish_exit_distance"),
                label=f"{label}.pre_finish_exit_distance",
            )
        ),
        mutations=_string_tuple_from_checkpoint(
            value.get("mutations"), label=f"{label}.mutations"
        ),
        gold_mask=_int_from_checkpoint(value, "gold_mask", label=label),
        gold_bonus_ticks=_int_from_checkpoint(
            value, "gold_bonus_ticks", label=label
        ),
    )


def _result_checkpoint(result: AutoResult) -> dict[str, object]:
    return {
        "frames": _checkpoint_frames(result.frames),
        "finish_tick": result.finish_tick,
        "objective_value": result.objective_value,
        "gold_mask": result.gold_mask,
        "gold_bonus_ticks": result.gold_bonus_ticks,
        "outcome_key": _outcome_key_checkpoint(auto_result_outcome_key(result)),
        "diagnostics": list(result.diagnostics),
    }


def _rehydrate_checkpoint_result(
    value: object,
    *,
    label: str,
    level: object,
    config: AutoConfig,
    search: SearchFunction,
) -> AutoResult:
    if not isinstance(value, Mapping):
        raise AutoCheckpointError(f"{label} must be an object")
    frames_value = value.get("frames")
    frames = _frames_from_checkpoint(frames_value, label=f"{label}.frames")
    try:
        result = search(
            level,
            frames,
            replace(config, iterations=0),
            progress=None,
            best_callback=None,
        )
    except (RuntimeError, ValueError) as exc:
        raise AutoCheckpointError(
            f"{label} failed canonical re-emulation: {exc}"
        ) from exc

    expected_finish = _int_from_checkpoint(
        value, "finish_tick", label=label
    )
    expected_objective = _int_from_checkpoint(
        value, "objective_value", label=label, minimum=None
    )
    expected_gold_mask = _int_from_checkpoint(value, "gold_mask", label=label)
    expected_gold_bonus = _int_from_checkpoint(
        value, "gold_bonus_ticks", label=label
    )
    expected_key = _outcome_key_from_checkpoint(
        value.get("outcome_key"), label=f"{label}.outcome_key"
    )
    observed_key = auto_result_outcome_key(result)
    if (
        result.frames != frames
        or result.finish_tick != expected_finish
        or result.objective_value != expected_objective
        or result.gold_mask != expected_gold_mask
        or result.gold_bonus_ticks != expected_gold_bonus
        or observed_key != expected_key
    ):
        raise AutoCheckpointError(
            f"{label} no longer reproduces its stored canonical outcome"
        )
    diagnostics = _string_tuple_from_checkpoint(
        value.get("diagnostics"), label=f"{label}.diagnostics"
    )
    return replace(
        result,
        diagnostics=diagnostics,
        beam=(),
        sectional_elites=(),
    )


def _population_member_checkpoint(member: _AutoPopulationMember) -> dict[str, object]:
    return {
        "member_id": member.member_id,
        "result": _result_checkpoint(member.result),
        "parent_member_ids": list(member.parent_member_ids),
        "generation": member.generation,
        "mutations": list(member.mutations),
        "recipient_member_id": member.recipient_member_id,
        "primary_family_id": member.primary_family_id,
        "splice_parent_pair": (
            None if member.splice_parent_pair is None else list(member.splice_parent_pair)
        ),
        "splice_interval": (
            None if member.splice_interval is None else list(member.splice_interval)
        ),
        "splice_donors": [
            _splice_donor_checkpoint(donor) for donor in member.splice_donors
        ],
        "splice_donor_index": member.splice_donor_index,
        "auxiliary_seeds": [
            {
                "working_frames": _checkpoint_frames(seed.working_frames),
                "description": seed.description,
                "reference_offset": seed.reference_offset,
                "candidate_tick": seed.candidate_tick,
                "reference_tick": seed.reference_tick,
            }
            for seed in member.auxiliary_seeds
        ],
    }


def _population_member_from_checkpoint(
    value: object,
    *,
    index: int,
    level: object,
    config: AutoConfig,
    search: SearchFunction,
) -> _AutoPopulationMember:
    label = f"checkpoint survivor {index}"
    if not isinstance(value, Mapping):
        raise AutoCheckpointError(f"{label} must be an object")
    raw_donors = value.get("splice_donors")
    if not isinstance(raw_donors, list):
        raise AutoCheckpointError(f"{label}.splice_donors must be an array")
    raw_auxiliary_seeds = value.get("auxiliary_seeds", [])
    if not isinstance(raw_auxiliary_seeds, list):
        raise AutoCheckpointError(
            f"{label}.auxiliary_seeds must be an array"
        )
    auxiliary_limit = min(
        config.auxiliary_beam_seeds,
        max(0, config.beam_width - 1),
    )
    if len(raw_auxiliary_seeds) > auxiliary_limit:
        raise AutoCheckpointError(
            f"{label}.auxiliary_seeds exceeds the configured maximum"
        )
    auxiliary_seeds: list[AutoBeamSeed] = []
    for seed_index, raw_seed in enumerate(raw_auxiliary_seeds):
        seed_label = f"{label}.auxiliary_seeds[{seed_index}]"
        if not isinstance(raw_seed, Mapping):
            raise AutoCheckpointError(f"{seed_label} must be an object")
        working_frames = _frames_from_checkpoint(
            raw_seed.get("working_frames"),
            label=f"{seed_label}.working_frames",
        )
        if not working_frames or any(
            (
                working_frames[-1].left,
                working_frames[-1].right,
                working_frames[-1].jump,
            )
        ):
            raise AutoCheckpointError(
                f"{seed_label}.working_frames must end in a neutral sentinel"
            )
        description = raw_seed.get("description")
        if not isinstance(description, str):
            raise AutoCheckpointError(
                f"{seed_label}.description must be a string"
            )
        reference_offset = (
            _int_from_checkpoint(
                raw_seed,
                "reference_offset",
                label=seed_label,
            )
            if "reference_offset" in raw_seed
            else 0
        )
        candidate_tick = _optional_int_from_checkpoint(
            raw_seed,
            "candidate_tick",
            label=seed_label,
        )
        reference_tick = _optional_int_from_checkpoint(
            raw_seed,
            "reference_tick",
            label=seed_label,
        )
        try:
            beam_seed = AutoBeamSeed(
                working_frames=working_frames,
                description=description,
                reference_offset=reference_offset,
                candidate_tick=candidate_tick,
                reference_tick=reference_tick,
            )
        except (TypeError, ValueError) as exc:
            raise AutoCheckpointError(
                f"{seed_label} has invalid alignment metadata: {exc}"
            ) from exc
        auxiliary_seeds.append(beam_seed)
    pair_value = value.get("splice_parent_pair")
    interval_value = value.get("splice_interval")
    pair = (
        None
        if pair_value is None
        else _int_tuple_from_checkpoint(
            pair_value, label=f"{label}.splice_parent_pair", length=2
        )
    )
    interval = (
        None
        if interval_value is None
        else _splice_interval_from_checkpoint(
            interval_value,
            label=f"{label}.splice_interval",
        )
    )
    return _AutoPopulationMember(
        member_id=_int_from_checkpoint(value, "member_id", label=label),
        result=_rehydrate_checkpoint_result(
            value.get("result"),
            label=f"{label}.result",
            level=level,
            config=config,
            search=search,
        ),
        parent_member_ids=_int_tuple_from_checkpoint(
            value.get("parent_member_ids"),
            label=f"{label}.parent_member_ids",
        ),
        generation=_int_from_checkpoint(value, "generation", label=label),
        mutations=_string_tuple_from_checkpoint(
            value.get("mutations"), label=f"{label}.mutations"
        ),
        recipient_member_id=_optional_int_from_checkpoint(
            value, "recipient_member_id", label=label
        ),
        primary_family_id=_optional_int_from_checkpoint(
            value, "primary_family_id", label=label
        ),
        splice_parent_pair=pair,
        splice_interval=interval,
        splice_donors=tuple(
            _splice_donor_from_checkpoint(
                donor, label=f"{label}.splice_donors[{donor_index}]"
            )
            for donor_index, donor in enumerate(raw_donors)
        ),
        splice_donor_index=_int_from_checkpoint(
            value, "splice_donor_index", label=label
        ),
        auxiliary_seeds=tuple(auxiliary_seeds),
    )


def _population_selection_checkpoint(
    selection: _PopulationSelection | None,
) -> dict[str, object] | None:
    if selection is None:
        return None
    return {
        "minimum_target": selection.minimum_target,
        "maximum_target": selection.maximum_target,
        "target": selection.target,
        "exact_unique_candidates": selection.exact_unique_candidates,
        "competitive_splice_niches": selection.competitive_splice_niches,
        "selected_splice_niches": selection.selected_splice_niches,
        "primary_family_occupancy": [
            list(item) for item in selection.primary_family_occupancy
        ],
    }


def _splice_stats_checkpoint(
    stats: _SpliceRoundStats | None,
) -> dict[str, object] | None:
    if stats is None:
        return None
    return {
        field_info.name: (
            dict(value)
            if isinstance(value, dict)
            else list(value)
            if isinstance(value, list)
            else value
        )
        for field_info in fields(_SpliceRoundStats)
        if (value := getattr(stats, field_info.name)) is not None
    }


def _write_auto_campaign_checkpoint(
    path: Path,
    identity: Mapping[str, object],
    *,
    config: AutoConfig,
    survivors: Sequence[_AutoPopulationMember],
    current: AutoResult,
    aggregate_stats: AutoStats,
    committed_mutations: Sequence[str],
    completed_runs: int,
    completed_searches: int,
    next_task_id: int,
    next_splice_task_id: int,
    next_member_id: int,
    consecutive_stagnant_rounds: int,
    last_improvement_round: int,
    stagnation_outcome_key: Sequence[int | float],
    population_selection: _PopulationSelection | None,
    splice_stats: _SpliceRoundStats | None,
) -> None:
    payload = {
        "identity": dict(identity),
        "state": {
            "completed_runs": completed_runs,
            "next_generation": completed_runs + 1,
            "completed_searches": completed_searches,
            "global_best": _result_checkpoint(current),
            "survivors": [
                _population_member_checkpoint(member) for member in survivors
            ],
            "committed_mutations": list(committed_mutations),
            "aggregate_stats": _auto_stats_checkpoint(aggregate_stats),
            "base_seed": config.seed,
            "seed_strategy": _AUTO_CHECKPOINT_SEED_STRATEGY,
            "next_task_id": next_task_id,
            "next_splice_task_id": next_splice_task_id,
            "next_member_id": next_member_id,
            "consecutive_stagnant_rounds": consecutive_stagnant_rounds,
            "last_improvement_round": last_improvement_round,
            "stagnation_outcome_key": _outcome_key_checkpoint(
                stagnation_outcome_key
            ),
            "committed_round_statistics": {
                "population": _population_selection_checkpoint(
                    population_selection
                ),
                "splice": _splice_stats_checkpoint(splice_stats),
            },
        },
    }
    write_auto_checkpoint(path, payload)


def _load_auto_campaign_checkpoint(
    path: Path,
    expected_identity: Mapping[str, object],
    *,
    level: object,
    config: AutoConfig,
    search: SearchFunction,
) -> _AutoCheckpointResumeState:
    payload = read_auto_checkpoint(path)
    _validate_checkpoint_identity(payload.get("identity"), expected_identity)
    state = payload.get("state")
    if not isinstance(state, Mapping):
        raise AutoCheckpointError("Auto checkpoint state is missing")
    raw_survivors = state.get("survivors")
    if not isinstance(raw_survivors, list) or not raw_survivors:
        raise AutoCheckpointError("Auto checkpoint survivor population is empty")
    survivors = tuple(
        _population_member_from_checkpoint(
            value,
            index=index,
            level=level,
            config=config,
            search=search,
        )
        for index, value in enumerate(raw_survivors)
    )
    member_ids = [member.member_id for member in survivors]
    if len(set(member_ids)) != len(member_ids):
        raise AutoCheckpointError("Auto checkpoint survivor member IDs are not unique")
    current = _rehydrate_checkpoint_result(
        state.get("global_best"),
        label="checkpoint global_best",
        level=level,
        config=config,
        search=search,
    )
    completed_runs = _int_from_checkpoint(
        state, "completed_runs", label="checkpoint state"
    )
    if any(member.generation != completed_runs for member in survivors):
        raise AutoCheckpointError(
            "Auto checkpoint survivors are not from the committed generation"
        )
    next_generation = _int_from_checkpoint(
        state, "next_generation", label="checkpoint state", minimum=1
    )
    if next_generation != completed_runs + 1:
        raise AutoCheckpointError(
            "Auto checkpoint next_generation is not after completed_runs"
        )
    base_seed = _int_from_checkpoint(
        state, "base_seed", label="checkpoint state", minimum=None
    )
    if base_seed != config.seed:
        raise AutoCheckpointError("Auto checkpoint base seed does not match config")
    if state.get("seed_strategy") != _AUTO_CHECKPOINT_SEED_STRATEGY:
        raise AutoCheckpointError("Auto checkpoint seed strategy is unsupported")
    stagnation_key = _outcome_key_from_checkpoint(
        state.get("stagnation_outcome_key"),
        label="checkpoint state.stagnation_outcome_key",
    )
    if stagnation_key != auto_result_outcome_key(current):
        raise AutoCheckpointError(
            "Auto checkpoint stagnation outcome does not match global best"
        )
    next_member_id = _int_from_checkpoint(
        state, "next_member_id", label="checkpoint state"
    )
    if next_member_id <= max(member_ids):
        raise AutoCheckpointError(
            "Auto checkpoint next_member_id does not follow survivor IDs"
        )
    last_improvement_round = _int_from_checkpoint(
        state, "last_improvement_round", label="checkpoint state"
    )
    if last_improvement_round > completed_runs:
        raise AutoCheckpointError(
            "Auto checkpoint last improvement follows its committed round"
        )
    return _AutoCheckpointResumeState(
        survivors=survivors,
        current=current,
        aggregate_stats=_auto_stats_from_checkpoint(
            state.get("aggregate_stats")
        ),
        committed_mutations=_string_tuple_from_checkpoint(
            state.get("committed_mutations"),
            label="checkpoint state.committed_mutations",
        ),
        completed_runs=completed_runs,
        completed_searches=_int_from_checkpoint(
            state, "completed_searches", label="checkpoint state"
        ),
        next_task_id=_int_from_checkpoint(
            state, "next_task_id", label="checkpoint state", minimum=1
        ),
        next_splice_task_id=_int_from_checkpoint(
            state, "next_splice_task_id", label="checkpoint state", minimum=1
        ),
        next_member_id=next_member_id,
        consecutive_stagnant_rounds=_int_from_checkpoint(
            state,
            "consecutive_stagnant_rounds",
            label="checkpoint state",
        ),
        last_improvement_round=last_improvement_round,
        stagnation_outcome_key=stagnation_key,
    )


def _derive_auto_checkpoint_task_seed(
    base_seed: int,
    generation: int,
    parent_replay_sha256: str,
    offspring_index: int,
) -> int:
    """Derive a schedule-independent seed for recreatable Auto work."""
    if (
        generation < 1
        or len(parent_replay_sha256) != 64
        or offspring_index < 1
    ):
        raise ValueError("invalid stable Auto task identity")
    material = (
        f"{_AUTO_CHECKPOINT_SEED_STRATEGY}\0{base_seed & ((1 << 64) - 1)}\0"
        f"{generation}\0{parent_replay_sha256}\0{offspring_index}\0auto"
    ).encode("ascii")
    return int.from_bytes(bytes.fromhex(sha256_bytes(material))[:8], "big")


def optimise_autonomous_campaign(
    level: Level,
    source_frames: Sequence[InputFrame],
    config: AutoConfig,
    *,
    parent_frames: Sequence[Sequence[InputFrame]] = (),
    workers: int = 0,
    runs: int = 1,
    stagnation_runs: int = 0,
    progress: ProgressCallback | None = None,
    best_callback: BestCallback | None = None,
    status: StatusCallback | None = None,
    search: SearchFunction = optimise_autonomous,
    checkpoint_path: str | os.PathLike[str] | None = None,
    resume: bool = False,
    level_identifier: str | None = None,
) -> AutoCampaignResult:
    """Run independent Auto searches as an asynchronous survivor population.

    ``source_frames`` remains the campaign reference. ``parent_frames`` adds
    generation-0 founders which are independently canonicalised and verified.
    ``workers=0`` selects up to eight available CPUs. ``runs=0`` repeats
    indefinitely until Ctrl+C. A positive ``stagnation_runs`` stops normally
    after that many consecutive committed rounds without a significant gain
    under the objective/half-pixel rule.
    Each completed round retains a half-worker minimum, plus one survivor for
    each competitive distinct splice niche up to one survivor per worker.
    Exact replay, recipient and breeding-family controls preserve route breadth.
    Free slots may speculatively start the next generation before all current
    workers finish. When ``checkpoint_path`` is supplied, each completely
    selected round is atomically committed. With ``resume=True``, a compatible
    existing checkpoint is re-emulated and used as the next-round population;
    a missing file starts a fresh campaign.
    """
    if workers < 0:
        raise ValueError("workers must be zero (auto) or a positive integer")
    if runs < 0:
        raise ValueError("auto runs must be non-negative")
    if stagnation_runs < 0:
        raise ValueError("Auto stagnation runs must be non-negative")
    if runs == 0 and config.iterations == 0:
        raise ValueError("indefinite Auto runs require a positive iteration budget")
    worker_count = automatic_auto_worker_count() if workers == 0 else workers
    if worker_count < 1:
        raise ValueError("Auto requires at least one worker")
    if resume and checkpoint_path is None:
        raise ValueError("Auto resume requires a checkpoint path")
    checkpoint_file = (
        None if checkpoint_path is None else Path(checkpoint_path)
    )
    source_frames = tuple(source_frames)
    parent_frames = tuple(tuple(frames) for frames in parent_frames)
    checkpoint_identity = (
        None
        if checkpoint_file is None
        else _auto_checkpoint_identity(
            level,
            source_frames,
            parent_frames,
            config,
            worker_count=worker_count,
            requested_runs=runs,
            stagnation_runs=stagnation_runs,
            level_identifier=level_identifier,
        )
    )

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
            recipient_member_id=member_id,
            primary_family_id=member_id,
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
    resume_state: _AutoCheckpointResumeState | None = None
    if resume and checkpoint_file is not None and checkpoint_file.exists():
        assert checkpoint_identity is not None
        resume_state = _load_auto_campaign_checkpoint(
            checkpoint_file,
            checkpoint_identity,
            level=level,
            config=config,
            search=search,
        )
        ranked_founders = tuple(
            sorted(resume_state.survivors, key=_population_rank_key)
        )
        if len(ranked_founders) > worker_count:
            raise AutoCheckpointError(
                "Auto checkpoint population exceeds the configured workers"
            )
        current = resume_state.current
        committed_mutations = resume_state.committed_mutations
        if status is not None:
            status(
                f"[auto:resume] restored {checkpoint_file}: committed round "
                f"{resume_state.completed_runs}, population "
                f"{len(ranked_founders)}, next round "
                f"{resume_state.completed_runs + 1}, stagnant rounds "
                f"{resume_state.consecutive_stagnant_rounds}"
            )
        if best_callback is not None:
            # Recreate the ordinary best output on a replacement spot host as
            # well as the internal native analyses used by the population.
            best_callback(current.best)
    elif resume and checkpoint_file is not None and status is not None:
        status(
            f"[auto:resume] no checkpoint at {checkpoint_file}; "
            "starting a new campaign"
        )
    elif (
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

    aggregate_stats = (
        AutoStats() if resume_state is None else resume_state.aggregate_stats
    )
    completed_runs = 0 if resume_state is None else resume_state.completed_runs
    completed_searches = (
        0 if resume_state is None else resume_state.completed_searches
    )
    run_index = completed_runs + 1
    run_limit = runs if runs > 0 else None
    consecutive_stagnant_rounds = (
        0
        if resume_state is None
        else resume_state.consecutive_stagnant_rounds
    )
    last_improvement_round = (
        0 if resume_state is None else resume_state.last_improvement_round
    )
    stagnation_outcome_key = (
        auto_result_outcome_key(current)
        if resume_state is None
        else resume_state.stagnation_outcome_key
    )

    if run_limit is not None and completed_runs >= run_limit:
        if status is not None and resume_state is not None:
            status(
                f"[auto:resume] checkpoint already contains all "
                f"{run_limit} requested round(s)"
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
            interrupted=False,
        )

    if (
        stagnation_runs > 0
        and consecutive_stagnant_rounds >= stagnation_runs
    ):
        if status is not None:
            status(
                f"[auto:stagnation] restored campaign has already reached "
                f"the limit of {stagnation_runs} consecutive round(s) "
                "without a significant global-best gain"
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
            interrupted=False,
        )

    restored_next_task_id = (
        1 if resume_state is None else resume_state.next_task_id
    )
    restored_next_splice_task_id = (
        1 if resume_state is None else resume_state.next_splice_task_id
    )
    restored_next_member_id = (
        len(founders) if resume_state is None else resume_state.next_member_id
    )

    if worker_count == 1:
        if len(ranked_founders) != 1:
            raise AutoCheckpointError(
                "one-worker Auto checkpoint must contain one survivor"
            )
        serial_survivor = ranked_founders[0]
        serial_next_task_id = restored_next_task_id
        serial_next_splice_task_id = restored_next_splice_task_id
        serial_next_member_id = restored_next_member_id
        while run_limit is None or run_index <= run_limit:
            seed = (
                derive_auto_search_seed(config.seed, run_index, 1, 1)
                if checkpoint_file is None
                else _derive_auto_checkpoint_task_seed(
                    config.seed,
                    run_index,
                    _replay_sha256(serial_survivor.result.frames),
                    1,
                )
            )
            serial_next_task_id += 1
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

                search_kwargs: dict[str, object] = {
                    "progress": (
                        serial_progress if progress is not None else None
                    ),
                    "best_callback": serial_checkpoint,
                }
                if (
                    serial_survivor.auxiliary_seeds
                    and search is optimise_autonomous
                ):
                    search_kwargs["auxiliary_seeds"] = (
                        serial_survivor.auxiliary_seeds
                    )
                result = search(
                    level,
                    current.frames,
                    replace(config, seed=seed),
                    **search_kwargs,
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
            splice_donors = _select_worker_splice_donors(result, config)
            worker_output = _AutoWorkerResult(
                result=replace(result, beam=(), sectional_elites=()),
                seed=seed,
                run_index=run_index,
                worker_index=1,
                splice_donors=splice_donors,
            )
            round_result = result
            round_mutations = (
                committed_mutations + _annotated_mutations(worker_output)
            )
            next_auxiliary_seeds: list[AutoBeamSeed] = []
            try:
                (
                    splice_child,
                    round_stats,
                    splice_repair_stats,
                    splice_interrupted,
                ) = (
                    _run_serial_sectional_splices(
                        level,
                        result,
                        splice_donors,
                        config,
                        run_index=run_index,
                        required_gold_mask=(
                            initial.baseline_gold_mask
                            if config.require_reference_gold
                            else 0
                        ),
                        auxiliary_seed_sink=next_auxiliary_seeds,
                    )
                )
            except KeyboardInterrupt:
                if auto_result_outcome_key(result) < auto_result_outcome_key(
                    current
                ):
                    current = result
                    committed_mutations = round_mutations
                if status is not None:
                    status(
                        "[auto:interrupt] Ctrl+C received during sectional "
                        "splice repair; retaining the best verified result"
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
            aggregate_stats = _sum_stats(
                aggregate_stats, splice_repair_stats
            )
            if (
                splice_child is not None
                and auto_result_outcome_key(splice_child)
                < auto_result_outcome_key(round_result)
            ):
                round_result = splice_child
                round_mutations += (splice_child.best.mutations[-1],)
            if auto_result_outcome_key(round_result) < auto_result_outcome_key(
                current
            ):
                current = round_result
                committed_mutations = round_mutations
                if splice_child is round_result and best_callback is not None:
                    best_callback(round_result.best)
            if splice_interrupted:
                if status is not None:
                    status(
                        "[auto:interrupt] Ctrl+C received during sectional "
                        "splice repair; retaining the best verified result"
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
            serial_next_splice_task_id += len(splice_donors)
            completed_runs += 1
            serial_member_id = serial_next_member_id
            serial_next_member_id += 1
            serial_is_splice = splice_child is not None and current is splice_child
            serial_member = _AutoPopulationMember(
                member_id=serial_member_id,
                result=replace(current, beam=(), sectional_elites=()),
                parent_member_ids=(serial_survivor.member_id,),
                generation=run_index,
                mutations=committed_mutations,
                recipient_member_id=(
                    serial_survivor.member_id
                    if serial_is_splice
                    else serial_member_id
                ),
                primary_family_id=serial_survivor.member_id,
                splice_parent_pair=(
                    (serial_survivor.member_id, serial_survivor.member_id)
                    if serial_is_splice
                    else None
                ),
                splice_donors=(
                    worker_output.splice_donors
                    if current is result
                    else ()
                ),
                splice_donor_index=(1 if serial_is_splice else 0),
                auxiliary_seeds=(
                    tuple(next_auxiliary_seeds)
                    if current.frames == result.frames
                    else ()
                ),
            )
            population_selection = _select_adaptive_population(
                (serial_member,), worker_count
            )
            serial_survivor = population_selection.survivors[0]
            current_outcome_key = auto_result_outcome_key(current)
            if _significant_stagnation_improvement(
                stagnation_outcome_key, current_outcome_key
            ):
                consecutive_stagnant_rounds = 0
                last_improvement_round = completed_runs
            else:
                consecutive_stagnant_rounds += 1
            stagnation_outcome_key = current_outcome_key
            if checkpoint_file is not None:
                assert checkpoint_identity is not None
                _write_auto_campaign_checkpoint(
                    checkpoint_file,
                    checkpoint_identity,
                    config=config,
                    survivors=(serial_survivor,),
                    current=current,
                    aggregate_stats=aggregate_stats,
                    committed_mutations=committed_mutations,
                    completed_runs=completed_runs,
                    completed_searches=completed_searches,
                    next_task_id=serial_next_task_id,
                    next_splice_task_id=serial_next_splice_task_id,
                    next_member_id=serial_next_member_id,
                    consecutive_stagnant_rounds=(
                        consecutive_stagnant_rounds
                    ),
                    last_improvement_round=last_improvement_round,
                    stagnation_outcome_key=stagnation_outcome_key,
                    population_selection=population_selection,
                    splice_stats=round_stats,
                )
                if status is not None:
                    status(
                        f"[auto:campaign-checkpoint] committed round "
                        f"{completed_runs} to {checkpoint_file}; population 1, "
                        f"stagnant rounds {consecutive_stagnant_rounds}"
                    )
            if status is not None:
                status(
                    f"[auto:parallel] round {run_index} complete: "
                    f"best finish {current.finish_tick}; restarting from winner"
                )
            _emit_splice_round_summary(run_index, round_stats, status)
            if (
                stagnation_runs > 0
                and consecutive_stagnant_rounds >= stagnation_runs
            ):
                if status is not None:
                    status(
                        f"[auto:stagnation] stopping after "
                        f"{consecutive_stagnant_rounds} consecutive "
                        "completed round(s) without a significant global-best gain"
                    )
                break
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
        tuple[int, int, int, int], _SpliceTaskRecord
    ] = {}
    prepared_splice_traces: dict[int, PreparedSpliceTrace] = {}
    splice_task_members: dict[int, _AutoPopulationMember] = {}
    splice_donor_sources: dict[
        tuple[int, int], _SpliceDonorSource
    ] = {}
    failed_splice_donor_sources: set[tuple[int, int]] = set()
    donor_verification_failures: dict[int, int] = {}
    coordinator_native_session: NativeSearchSession | None = None
    members: dict[int, _AutoPopulationMember] = {
        member.member_id: member for member in ranked_founders
    }
    next_task_id = restored_next_task_id
    next_splice_task_id = restored_next_splice_task_id
    next_member_id = restored_next_member_id
    minimum_survivor_count = _population_survivor_count(worker_count)
    checkpoint_key = auto_result_outcome_key(current)
    durable_current = current
    durable_mutations = committed_mutations
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
        seed_override: int | None = None,
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
            seed=(
                seed_override
                if seed_override is not None
                else (
                    _derive_auto_task_seed(config.seed, task_id)
                    if checkpoint_file is None
                    else _derive_auto_checkpoint_task_seed(
                        config.seed,
                        generation,
                        _replay_sha256(
                            members[parent_member_id].result.frames
                        ),
                        offspring_index,
                    )
                )
            ),
            authoritative=authoritative,
            auxiliary_seeds=(
                members[parent_member_id].auxiliary_seeds
                if offspring_index == 1
                else ()
            ),
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
        nonlocal next_splice_task_id, coordinator_native_session
        for member in completed_members:
            if member.member_id not in prepared_splice_traces:
                prepared_splice_traces[member.member_id] = prepare_splice_trace(
                    member.result.best.evaluation,
                    member.result.frames,
                )
            main_key = (member.member_id, 0)
            if main_key not in splice_donor_sources:
                proximity = member.result.best.evaluation.pre_finish_exit_distance
                if proximity is None or not math.isfinite(proximity):
                    proximity = float("inf")
                splice_donor_sources[main_key] = _SpliceDonorSource(
                    owner_member_id=member.member_id,
                    donor_index=0,
                    donor=AutoSpliceDonor(
                        frames=member.result.frames,
                        finish_tick=member.result.finish_tick,
                        objective_value=member.result.objective_value,
                        pre_finish_exit_distance=proximity,
                        mutations=member.mutations,
                        gold_mask=member.result.gold_mask,
                        gold_bonus_ticks=member.result.gold_bonus_ticks,
                    ),
                    trace=prepared_splice_traces[member.member_id],
                )
            for donor_index, donor in enumerate(member.splice_donors, start=1):
                source_key = (member.member_id, donor_index)
                if (
                    source_key in splice_donor_sources
                    or source_key in failed_splice_donor_sources
                ):
                    continue
                if isinstance(level, Level) and coordinator_native_session is None:
                    coordinator_native_session = NativeSearchSession(level)
                token = _ACTIVE_NATIVE_SESSION.set(
                    (level, coordinator_native_session)
                )
                try:
                    evaluation = _canonical_sectional_donor(
                        level, donor, config.objective
                    )
                finally:
                    _ACTIVE_NATIVE_SESSION.reset(token)
                if evaluation is None:
                    failed_splice_donor_sources.add(source_key)
                    donor_verification_failures[generation] = (
                        donor_verification_failures.get(generation, 0) + 1
                    )
                    continue
                splice_donor_sources[source_key] = _SpliceDonorSource(
                    owner_member_id=member.member_id,
                    donor_index=donor_index,
                    donor=donor,
                    trace=prepare_splice_trace(evaluation, donor.frames),
                )
        ordered = tuple(completed_members)
        for recipient in ordered:
            for donor_owner in ordered:
                donor_sources = sorted(
                    (
                        source
                        for (owner_id, _index), source in splice_donor_sources.items()
                        if owner_id == donor_owner.member_id
                    ),
                    key=lambda source: source.donor_index,
                )
                for source in donor_sources:
                    if (
                        recipient.member_id == donor_owner.member_id
                        and source.donor_index == 0
                    ):
                        continue
                    key = (
                        generation,
                        recipient.member_id,
                        donor_owner.member_id,
                        source.donor_index,
                    )
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
                        donor_member_id=donor_owner.member_id,
                        donor_index=source.donor_index,
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
            recipient_member_id=next_member_id,
            primary_family_id=record.parent_member_id,
            splice_donors=output.splice_donors,
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
        if (
            record is None
            or record.cancelled
            or not record.authoritative
        ):
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
                    update.donor_index,
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
            auxiliary_seeds=record.auxiliary_seeds,
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
        recipient = splice_task_members.get(record.recipient_member_id)
        if recipient is None:
            member = members[record.recipient_member_id]
            recipient = replace(
                member,
                result=replace(
                    member.result,
                    beam=(),
                    sectional_elites=(),
                ),
                splice_donors=(),
            )
            splice_task_members[record.recipient_member_id] = recipient
        donor = recipient
        if record.donor_index == 0:
            donor = splice_task_members.get(record.donor_member_id)
            if donor is None:
                member = members[record.donor_member_id]
                donor = replace(
                    member,
                    result=replace(
                        member.result,
                        beam=(),
                        sectional_elites=(),
                    ),
                    splice_donors=(),
                )
                splice_task_members[record.donor_member_id] = donor
        task = _SpliceWorkerTask(
            recipient=recipient,
            # Sectional source metadata carries its owner identity and frames;
            # reuse the already-pickled recipient as the legacy ``donor``
            # placeholder so a cross-owner sectional job does not also ship
            # the owner's unrelated winning trajectory.
            donor=donor,
            recipient_trace=prepared_splice_traces[
                record.recipient_member_id
            ],
            donor_trace=splice_donor_sources[
                (record.donor_member_id, record.donor_index)
            ].trace,
            run_index=record.generation,
            task_id=record.task_id,
            required_gold_mask=required_reference_gold_mask,
            worker_index=record.worker_index,
            cancel_slot=slot,
            donor_source=splice_donor_sources[
                (record.donor_member_id, record.donor_index)
            ],
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

    def refresh_record_auxiliary_seeds(
        generation: int,
        parent_member_id: int,
        offspring_index: int,
    ) -> _AutoTaskRecord | None:
        """Replace stale speculative work only when real seeds were found."""
        key = (generation, parent_member_id, offspring_index)
        existing = records_by_key.get(key)
        if existing is None:
            return None
        desired = (
            members[parent_member_id].auxiliary_seeds
            if offspring_index == 1
            else ()
        )
        if existing.auxiliary_seeds == desired:
            return existing
        if existing.authoritative:
            raise RuntimeError(
                "authoritative Auto task changed auxiliary seed identity"
            )
        existing.authoritative = False
        replacement_seed = existing.seed
        if existing.output is not None:
            # Completed speculative output was retained but never admitted to
            # the campaign.  It is safe to invalidate without rolling back a
            # member or global-best callback.
            existing.cancelled = True
        else:
            cancel_record(existing)
        # Keep the old record reachable by task ID until any running future is
        # reaped, but detach its generation key so the correctly seeded task
        # can be created immediately.
        records_by_key.pop(key, None)
        return create_record(
            generation,
            parent_member_id,
            offspring_index,
            authoritative=True,
            seed_override=replacement_seed,
        )

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
            # Displace deeper speculative children before breadth-first child
            # ones, then the newest task at the same breadth.
            key=lambda record: (record.offspring_index, record.task_id),
            reverse=True,
        )
        for record in speculative[:deficit]:
            preempt_record(record)

    def commit_completed_output(record: _AutoTaskRecord) -> None:
        """Admit an authoritative result after its seed identity is final."""
        nonlocal current, committed_mutations, checkpoint_key
        output = record.output
        if (
            output is None
            or record.output_member_id is not None
            or record.cancelled
            or not record.authoritative
        ):
            return
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

    def record_completed_output(
        record: _AutoTaskRecord,
        output: _AutoWorkerResult,
    ) -> None:
        nonlocal aggregate_stats, completed_searches
        record.output = output
        completed_searches += 1
        aggregate_stats = _sum_stats(aggregate_stats, output.result.stats)
        # Speculative tasks may need to be replaced if splice repair discovers
        # an auxiliary seed for their parent.  Account real work immediately,
        # but defer member/global-best effects until the generation key becomes
        # authoritative and its seed payload is final.
        commit_completed_output(record)
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
        donor_label = (
            f"{donor.member_id} sectional #{record.donor_index}"
            if record.donor_index
            else str(donor.member_id)
        )
        candidate = proposal.candidate
        child_result = _result_from_candidate(candidate, recipient.result)
        outcome_key = auto_result_outcome_key(child_result)
        if outcome_key >= auto_result_outcome_key(recipient.result):
            return
        actual_gain = recipient.result.finish_tick - child_result.finish_tick
        diagnostic = (
            f"splice round {record.generation}: recipient member "
            f"{recipient.member_id}, donor member {donor_label}, "
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
            record.donor_index,
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
                if record.cancelled:
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
            if record.output_member_id is not None:
                result.append(members[record.output_member_id])
        return tuple(result)

    def commit_splice_outputs(
        completed_members: Sequence[_AutoPopulationMember],
        generation: int,
        round_stats: _SpliceRoundStats,
    ) -> tuple[
        tuple[_AutoPopulationMember, ...],
        dict[int, tuple[AutoBeamSeed, ...]],
    ]:
        """Admit buffered pair outputs in deterministic pair/plan order."""
        nonlocal aggregate_stats, checkpoint_key, committed_mutations
        nonlocal current, next_member_id

        accepted: list[_AutoPopulationMember] = []
        auxiliary_pools: dict[int, list[SpliceAuxiliarySeed]] = {}
        accepted_bodies = {member.result.frames for member in completed_members}
        accepted_bodies.update(
            source.donor.frames
            for source in splice_donor_sources.values()
            if source.owner_member_id
            in {member.member_id for member in completed_members}
        )
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
                record.donor_index,
            ),
        )
        for record in generation_records:
            output = record.output
            if output is None:
                raise RuntimeError("round finalised before a splice pair completed")
            if (
                output.recipient_member_id != record.recipient_member_id
                or output.donor_member_id != record.donor_member_id
                or output.donor_index != record.donor_index
            ):
                raise RuntimeError("splice worker returned the wrong parent pair")
            round_stats.merge(output.splice_stats)
            aggregate_stats = _sum_stats(aggregate_stats, output.auto_stats)
            recipient = members[record.recipient_member_id]
            donor = members[record.donor_member_id]
            auxiliary_pools.setdefault(recipient.member_id, []).extend(
                output.auxiliary_seeds
            )
            donor_label = (
                f"{donor.member_id} sectional #{record.donor_index}"
                if record.donor_index
                else str(donor.member_id)
            )
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
                    f"{recipient.member_id}, donor member {donor_label}, "
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
                    parent_member_ids=(
                        (recipient.member_id,)
                        if recipient.member_id == donor.member_id
                        else (recipient.member_id, donor.member_id)
                    ),
                    generation=generation,
                    mutations=mutations,
                    recipient_member_id=recipient.member_id,
                    primary_family_id=(
                        recipient.selection_primary_family_id
                    ),
                    splice_parent_pair=tuple(
                        sorted((recipient.member_id, donor.member_id))
                    ),
                    splice_interval=(
                        proposal.recipient_entry_tick,
                        proposal.recipient_exit_tick,
                        proposal.donor_entry_tick,
                        proposal.donor_exit_tick,
                    ),
                    splice_donor_index=record.donor_index,
                )
                next_member_id += 1
                members[member.member_id] = member
                accepted.append(member)
                round_stats.admitted += 1
                if record.donor_index > 0:
                    round_stats.sectional_admitted += 1
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
                            f"{donor_label}; finish {child_result.finish_tick}"
                        )
                    if best_callback is not None:
                        best_callback(candidate)
        if accepted and status is not None:
            status(
                f"[auto:splice] round {generation}: admitted {len(accepted)} "
                "canonically verified section splice child(ren)"
            )
        selected_auxiliary = {
            member.member_id: _select_auxiliary_beam_seeds(
                auxiliary_pools.get(member.member_id, ()),
                config,
                recipient_working_frames=member.result.best.working_frames,
            )
            for member in completed_members
            if auxiliary_pools.get(member.member_id)
        }
        return tuple(accepted), selected_auxiliary

    def next_speculative_record(
        generation: int,
        task_ids: set[int],
    ) -> _AutoTaskRecord | None:
        completed = completed_authoritative_members(task_ids)
        if not completed:
            return None
        provisional_count = min(minimum_survivor_count, len(completed))
        provisional = _select_population_survivors(
            completed,
            provisional_count,
            enforce_parent_diversity=True,
        )
        keys = _offspring_keys_breadth_first(
            generation + 1,
            provisional,
            worker_count,
            # Do not spend a second search on an early provisional route while
            # a first child for a possible minimum-population survivor is not
            # yet known. Once four parents are available for eight workers,
            # quota-backed second children become eligible breadth-first.
            first_only=len(provisional) < minimum_survivor_count,
        )
        for next_generation, parent_member_id, offspring_index in keys:
            key = (next_generation, parent_member_id, offspring_index)
            existing = records_by_key.get(key)
            if existing is None:
                return create_record(
                    next_generation,
                    parent_member_id,
                    offspring_index,
                    authoritative=False,
                )
            if (
                existing.future is None
                and existing.output is None
                and not existing.cancelled
            ):
                # A ready splice may have cooperatively paused this task. Once
                # that Future has unwound, the same deterministic task can
                # resume after every first offspring still ranks ahead of it.
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
            missing = min(
                (
                    record
                    for record in authoritative_records(task_ids)
                    if record.output is None
                    and record.future is None
                    and not record.cancelled
                ),
                key=lambda record: (record.offspring_index, record.task_id),
                default=None,
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
                            item.donor_index,
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

        founder_keys = _offspring_keys_breadth_first(
            run_index,
            ranked_founders,
            worker_count,
        )
        current_task_ids = {
            create_record(
                generation,
                parent_member_id,
                offspring_index,
                authoritative=True,
            ).task_id
            for generation, parent_member_id, offspring_index in founder_keys
        }

        while run_limit is None or run_index <= run_limit:
            suffix = f"/{run_limit}" if run_limit is not None else ""
            if status is not None:
                if run_index == 1:
                    active_parent_count = len(
                        {
                            records[task_id].parent_member_id
                            for task_id in current_task_ids
                        }
                    )
                    description = (
                        f"starting {worker_count} independent searches from "
                        f"{active_parent_count} unique parent(s), "
                        f"{config.iterations} iterations each"
                    )
                else:
                    active_parent_count = len(
                        {
                            records[task_id].parent_member_id
                            for task_id in current_task_ids
                        }
                    )
                    description = (
                        f"population search from {active_parent_count} "
                        "survivor(s), "
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
                completed_ids = {
                    member.member_id for member in completed_now
                }
                expected_pair_count = (
                    sum(
                        1
                        for recipient in completed_now
                        for source in splice_donor_sources.values()
                        if source.owner_member_id in completed_ids
                        and not (
                            source.owner_member_id == recipient.member_id
                            and source.donor_index == 0
                        )
                    )
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
            completed_member_ids_before_splice = {
                member.member_id for member in completed_members
            }
            round_stats.sectional_donors = sum(
                source.is_sectional
                and source.owner_member_id in completed_member_ids_before_splice
                for source in splice_donor_sources.values()
            )
            round_stats.reject(
                "sectional-donor-verification",
                donor_verification_failures.pop(run_index, 0),
            )
            splice_additions, auxiliary_by_recipient = commit_splice_outputs(
                completed_members, run_index, round_stats
            )
            completed_members += splice_additions
            population_selection = _select_adaptive_population(
                completed_members,
                worker_count,
            )
            survivors = tuple(
                replace(
                    member,
                    auxiliary_seeds=auxiliary_by_recipient.get(
                        member.member_id, ()
                    ),
                )
                for member in population_selection.survivors
            )
            for survivor in survivors:
                members[survivor.member_id] = survivor
            population_selection = replace(
                population_selection,
                survivors=survivors,
            )
            survivor_ids = {member.member_id for member in survivors}
            splice_members = tuple(
                member for member in completed_members if member.is_splice
            )
            round_stats.survivors = sum(
                member.member_id in survivor_ids for member in splice_members
            )
            round_stats.sectional_survivors = sum(
                member.member_id in survivor_ids
                and member.splice_donor_index > 0
                for member in splice_members
            )
            round_stats.reject(
                "population-selection",
                sum(
                    member.member_id not in survivor_ids
                    for member in splice_members
                ),
            )
            committed_round_best = min(
                completed_members,
                key=_population_rank_key,
            )
            if auto_result_outcome_key(
                committed_round_best.result
            ) < auto_result_outcome_key(durable_current):
                durable_current = committed_round_best.result
                durable_mutations = committed_round_best.mutations
            completed_runs += 1
            durable_outcome_key = auto_result_outcome_key(durable_current)
            if _significant_stagnation_improvement(
                stagnation_outcome_key, durable_outcome_key
            ):
                consecutive_stagnant_rounds = 0
                last_improvement_round = completed_runs
            else:
                consecutive_stagnant_rounds += 1
            stagnation_outcome_key = durable_outcome_key
            if checkpoint_file is not None:
                assert checkpoint_identity is not None
                _write_auto_campaign_checkpoint(
                    checkpoint_file,
                    checkpoint_identity,
                    config=config,
                    survivors=survivors,
                    current=durable_current,
                    aggregate_stats=aggregate_stats,
                    committed_mutations=durable_mutations,
                    completed_runs=completed_runs,
                    completed_searches=completed_searches,
                    next_task_id=next_task_id,
                    next_splice_task_id=next_splice_task_id,
                    next_member_id=next_member_id,
                    consecutive_stagnant_rounds=(
                        consecutive_stagnant_rounds
                    ),
                    last_improvement_round=last_improvement_round,
                    stagnation_outcome_key=stagnation_outcome_key,
                    population_selection=population_selection,
                    splice_stats=round_stats,
                )
                if status is not None:
                    status(
                        f"[auto:campaign-checkpoint] committed round "
                        f"{completed_runs} to {checkpoint_file}; population "
                        f"{len(survivors)}, stagnant rounds "
                        f"{consecutive_stagnant_rounds}"
                    )
            _emit_population_round_summary(
                run_index,
                population_selection,
                candidate_count=len(completed_members),
                global_best_finish_tick=durable_current.finish_tick,
                status=status,
            )
            _emit_splice_round_summary(run_index, round_stats, status)
            for key in tuple(splice_records):
                if key[0] == run_index:
                    del splice_records[key]
            for member in completed_members:
                prepared_splice_traces.pop(member.member_id, None)
            completed_member_ids = {
                member.member_id for member in completed_members
            }
            for member_id in completed_member_ids:
                splice_task_members.pop(member_id, None)
            for source_key in tuple(splice_donor_sources):
                if source_key[0] in completed_member_ids:
                    del splice_donor_sources[source_key]
            failed_splice_donor_sources.difference_update(
                source_key
                for source_key in tuple(failed_splice_donor_sources)
                if source_key[0] in completed_member_ids
            )

            if (
                stagnation_runs > 0
                and consecutive_stagnant_rounds >= stagnation_runs
            ):
                if status is not None:
                    status(
                        f"[auto:stagnation] stopping after "
                        f"{consecutive_stagnant_rounds} consecutive "
                        "completed round(s) without a significant global-best gain"
                    )
                break

            if run_limit is not None and run_index >= run_limit:
                break

            desired_order = _offspring_keys_breadth_first(
                run_index + 1,
                survivors,
                worker_count,
            )
            desired_keys = set(desired_order)
            next_task_ids: set[int] = set()
            for key in desired_order:
                generation, parent_member_id, offspring_index = key
                record = refresh_record_auxiliary_seeds(
                    generation,
                    parent_member_id,
                    offspring_index,
                )
                if record is None:
                    record = create_record(
                        generation,
                        parent_member_id,
                        offspring_index,
                        authoritative=True,
                    )
                else:
                    record.authoritative = True
                    commit_completed_output(record)
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
    "AutoSpliceDonor",
    "auto_candidate_outcome_key",
    "auto_result_outcome_key",
    "automatic_auto_worker_count",
    "derive_auto_search_seed",
    "optimise_autonomous_campaign",
]

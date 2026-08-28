"""Autonomous, reference-guided optimisation for complete n v1.4 replays.

The search deliberately treats the supplied replay as a *route*, rather than
as a single target-frame objective.  Macro mutations can move an entire input
suffix; lightweight trajectory alignment then says where the mutated route has
rejoined the reference, and bounded local searches repair the first broken
contact or jump.

Replay timing uses n's slightly surprising convention.  A replay containing N
serialized inputs is tested with an implicit neutral input at step index N.  If
the exit is touched during that step, its finish tick is N and only the first N
inputs are serialized.  Consequently every macro candidate below has one fixed
neutral sentinel and a completion at step ``t`` emits ``working[:t]``.
"""
from __future__ import annotations

import hashlib
import math
import operator
import random
from collections.abc import Callable, Iterable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, replace

from nv14_engine import (
    InputFrame,
    Level,
)
from nv14_replay import (
    RetimeMutation,
    apply_single_transition_retime,
    apply_suffix_retime,
    editable_frames,
    input_transition_frames,
    valid_retime_mutations,
)
from nv14_search import (
    INTERACTION_EXIT_SWITCH,
    INTERACTION_GOLD,
    INTERACTION_LOCKED_DOOR,
    INTERACTION_TRAPDOOR,
    OBJECTIVE_CONSTANT,
    OBJECTIVE_TRACE_DISTANCE,
    PATCH_TIE_LOW_EDIT_LEX,
    PATCH_TIE_SUPPLIED_ORDER,
    InteractionAtomSpec,
    InteractionGroupSpec,
    NativeSearchSession,
    PatchAssignmentSpec,
    PatchEvaluationSpec,
    SearchResult,
    SearchSpec,
    TraceTargetSpec,
)

NEUTRAL_INPUT = InputFrame(False, False, False, None)
AUTO_OBJECTIVE_SPEEDRUN = "speedrun"
AUTO_OBJECTIVE_HIGHSCORE = "highscore"
AUTO_OBJECTIVES = (AUTO_OBJECTIVE_SPEEDRUN, AUTO_OBJECTIVE_HIGHSCORE)
AUTO_REPAIR_SEARCH_ORDER_RANDOM = "random"
AUTO_REPAIR_SEARCH_ORDER_FIXED = "fixed"
AUTO_REPAIR_SEARCH_ORDERS = (
    AUTO_REPAIR_SEARCH_ORDER_RANDOM,
    AUTO_REPAIR_SEARCH_ORDER_FIXED,
)
GOLD_BONUS_TICKS = 80

# Auto owns the route-score definition. Native kernels receive these immutable
# scalar weights with each target and only evaluate the compiled objective.
_TRACE_POSITION_WEIGHT = 1.0
_TRACE_VELOCITY_WEIGHT = 4.0
_TRACE_CONTACT_MISMATCH_PENALTY = 16.0
_TRACE_IN_AIR_MISMATCH_PENALTY = 25.0
_TRACE_NEAR_WALL_MISMATCH_PENALTY = 9.0
_TRACE_GOLD_BIT_PENALTY = 0.25
_TRACE_MINE_BIT_PENALTY = 0.25
_TRACE_EXIT_BIT_PENALTY = 8.0
_TRACE_LOCKED_DOOR_BIT_PENALTY = 24.0
_TRACE_TRAPDOOR_BIT_PENALTY = 24.0


_ACTIVE_NATIVE_SESSION: ContextVar[
    tuple[Level, NativeSearchSession | None] | None
] = ContextVar("nv14_auto_native_session", default=None)


def _native_session(level: Level) -> NativeSearchSession:
    active = _ACTIVE_NATIVE_SESSION.get()
    if active is not None and active[0] is level:
        if active[1] is not None:
            return active[1]
        session = NativeSearchSession(level)
        _ACTIVE_NATIVE_SESSION.set((level, session))
        return session
    return NativeSearchSession(level)


@dataclass(frozen=True, slots=True)
class AutoConfig:
    """Bounds and deterministic controls for :func:`optimise_autonomous`."""

    iterations: int = 5000
    beam_width: int = 32
    max_retime: int = 3
    seed: int = 0
    repair_window: int = 6
    repair_lookback: int = 192
    max_alignment: int = 3
    deterministic_phase: bool = True
    repair_local_limit: int = 1_000
    repair_search_order: str = AUTO_REPAIR_SEARCH_ORDER_RANDOM
    frame_ahead_repair_multiplier: int = 10
    repair_campaign_local_limit: int = 10_000
    trace_stride: int = 1
    max_jump_shift: int = 3
    max_jump_hold_delta: int = 3
    diversity_per_bucket: int = 2
    alignment_position_tolerance: float = 3.0
    alignment_velocity_tolerance: float = 0.75
    range_start: int = 0
    range_end: int | None = None
    cheap_pulse_limit: int = 96
    repair_lookahead: int = 3
    all_input_repair: bool = True
    objective: str = AUTO_OBJECTIVE_SPEEDRUN
    require_reference_gold: bool = False
    max_extra_ticks: int | None = None

    def __post_init__(self) -> None:
        if self.iterations < 0:
            raise ValueError("iterations must be non-negative")
        if self.beam_width < 1:
            raise ValueError("beam_width must be positive")
        if not 1 <= self.max_retime <= 3:
            raise ValueError("max_retime must be between 1 and 3")
        if self.repair_window < 1 or self.repair_window > 10:
            raise ValueError("repair_window must be between 1 and 10")
        if self.repair_lookback < self.repair_window:
            raise ValueError("repair_lookback must be at least repair_window")
        if self.max_alignment < 0:
            raise ValueError("max_alignment must be non-negative")
        if self.repair_local_limit < 0:
            raise ValueError("repair_local_limit must be non-negative")
        if self.repair_search_order not in AUTO_REPAIR_SEARCH_ORDERS:
            raise ValueError(
                "repair_search_order must be one of: "
                + ", ".join(AUTO_REPAIR_SEARCH_ORDERS)
            )
        if self.frame_ahead_repair_multiplier < 1:
            raise ValueError("frame_ahead_repair_multiplier must be at least 1")
        if self.repair_campaign_local_limit < 0:
            raise ValueError("repair_campaign_local_limit must be non-negative")
        if self.trace_stride != 1:
            raise ValueError(
                "trace_stride must be 1 so stable frame-to-frame alignment remains available"
            )
        if self.max_jump_shift < 0 or self.max_jump_hold_delta < 0:
            raise ValueError("jump mutation bounds must be non-negative")
        if self.diversity_per_bucket < 1:
            raise ValueError("diversity_per_bucket must be positive")
        if not math.isfinite(self.alignment_position_tolerance) or self.alignment_position_tolerance < 0:
            raise ValueError("alignment_position_tolerance must be finite and non-negative")
        if not math.isfinite(self.alignment_velocity_tolerance) or self.alignment_velocity_tolerance < 0:
            raise ValueError("alignment_velocity_tolerance must be finite and non-negative")
        if self.range_start < 0:
            raise ValueError("range_start must be non-negative")
        if self.range_end is not None and self.range_end < self.range_start:
            raise ValueError("range_end must be at least range_start")
        if self.cheap_pulse_limit < 0:
            raise ValueError("cheap_pulse_limit must be non-negative")
        if self.repair_lookahead < 1:
            raise ValueError("repair_lookahead must be positive")
        if self.objective not in AUTO_OBJECTIVES:
            raise ValueError(
                "objective must be one of: " + ", ".join(AUTO_OBJECTIVES)
            )
        if self.max_extra_ticks is not None and self.max_extra_ticks < 0:
            raise ValueError("max_extra_ticks must be non-negative")
        if self.objective == AUTO_OBJECTIVE_SPEEDRUN and self.effective_max_extra_ticks:
            raise ValueError("speedrun objective requires max_extra_ticks=0")
        if self.require_reference_gold and self.objective != AUTO_OBJECTIVE_HIGHSCORE:
            raise ValueError(
                "require_reference_gold is only meaningful for the highscore objective"
            )

    @property
    def effective_max_extra_ticks(self) -> int:
        if self.max_extra_ticks is not None:
            return self.max_extra_ticks
        return (
            GOLD_BONUS_TICKS
            if self.objective == AUTO_OBJECTIVE_HIGHSCORE
            else 0
        )


@dataclass(frozen=True, slots=True)
class CompactTracePoint:
    """Small route-matching view of one post-step simulation state.

    This intentionally is not a complete savestate.  Player kinematics,
    contact mode and immutable-object progress are good reference-alignment
    signals, while dynamic object state is still simulated faithfully by the
    supplied :class:`Level`.
    """

    tick: int
    x: float
    y: float
    vx: float
    vy: float
    player_state: int
    in_air: bool
    near_wall: bool
    wall_x: int
    floor_x: int
    floor_y: int
    previous_jump_held: bool
    jump_events: int
    collected_gold_mask: int
    exploded_mine_mask: int
    open_exit_mask: int
    complete: bool
    dead: bool
    gold_bonus_ticks: int = 0
    opened_locked_door_mask: int = 0
    triggered_trapdoor_mask: int = 0

    @property
    def static_key(self) -> tuple[int, int, int, int, int]:
        return (
            self.collected_gold_mask,
            self.exploded_mine_mask,
            self.open_exit_mask,
            self.opened_locked_door_mask,
            self.triggered_trapdoor_mask,
        )

    @property
    def route_progress_key(self) -> tuple[int]:
        """Legacy exit-mask key for callers without completion-exit metadata."""
        return (self.open_exit_mask,)

    @property
    def contact_key(self) -> tuple[int, bool, bool, int, int, int, bool]:
        return (
            self.player_state,
            self.in_air,
            self.near_wall,
            self.wall_x,
            self.floor_x,
            self.floor_y,
            self.previous_jump_held,
        )


def _compact_trace_point(row: Sequence[object]) -> CompactTracePoint:
    """Materialise one public point from a native scalar/mask row."""
    return CompactTracePoint(
        tick=int(row[0]),
        x=float(row[1]),
        y=float(row[2]),
        vx=float(row[3]),
        vy=float(row[4]),
        player_state=int(row[5]),
        in_air=bool(row[6]),
        near_wall=bool(row[7]),
        wall_x=int(row[8]),
        floor_x=int(row[9]),
        floor_y=int(row[10]),
        previous_jump_held=bool(row[11]),
        jump_events=int(row[12]),
        collected_gold_mask=int(row[13]),
        exploded_mine_mask=int(row[14]),
        open_exit_mask=int(row[15]),
        opened_locked_door_mask=int(row[16]),
        triggered_trapdoor_mask=int(row[17]),
        complete=bool(row[18]),
        dead=bool(row[19]),
        gold_bonus_ticks=int(row[20]),
    )


_TERMINAL_SUMMARY_UNSET = object()


class _NativeTraceView(Sequence[CompactTracePoint]):
    """Sequence-compatible lazy view over one owned native analysis.

    Normal Auto policy uses scalar queries and native scans, so no point is
    constructed. Indexing, slicing, iteration, equality and pickling are the
    explicit compatibility/reporting boundaries which materialise rows.
    """

    __slots__ = ("analysis", "_terminal_flags", "_terminal_summary")

    def __init__(self, analysis: object) -> None:
        self.analysis = analysis
        self._terminal_flags: object = _TERMINAL_SUMMARY_UNSET
        self._terminal_summary: object = _TERMINAL_SUMMARY_UNSET

    def __len__(self) -> int:
        return int(self.analysis.trace_count)

    def __getitem__(self, index: int | slice):
        if isinstance(index, slice):
            return tuple(
                self[position]
                for position in range(*index.indices(len(self)))
            )
        position = operator.index(index)
        if position < 0:
            position += len(self)
        if position < 0 or position >= len(self):
            raise IndexError("trace index out of range")
        return _compact_trace_point(self.analysis.point_at(position))

    def __iter__(self):
        for index in range(len(self)):
            yield _compact_trace_point(self.analysis.point_at(index))

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        if not isinstance(other, Sequence):
            return False
        if len(self) != len(other):
            return False
        return all(left == right for left, right in zip(self, other))

    def __hash__(self) -> int:
        return hash(tuple(self))

    def __repr__(self) -> str:
        return f"NativeTraceView(count={len(self)})"

    def __reduce__(self):
        # Auto worker results/checkpoints cross a multiprocessing boundary.
        # Materialise only there so the owning C pointer itself is never
        # pickled or copied.
        materialised = tuple(self)
        return (tuple, (materialised,))

    def point(self, tick: int) -> CompactTracePoint | None:
        if tick < 0:
            return None
        row = self.analysis.point(tick)
        return None if row is None else _compact_trace_point(row)

    def terminal_flags(self) -> tuple[bool, bool] | None:
        if self._terminal_flags is _TERMINAL_SUMMARY_UNSET:
            raw = self.analysis.terminal_flags()
            self._terminal_flags = None if raw is None else (
                bool(raw[0]),
                bool(raw[1]),
            )
        value = self._terminal_flags
        if value is None:
            return None
        return value  # type: ignore[return-value]

    def terminal_summary(self) -> tuple | None:
        if self._terminal_summary is _TERMINAL_SUMMARY_UNSET:
            value = self.analysis.terminal_summary()
            self._terminal_summary = None if value is None else tuple(value)
        value = self._terminal_summary
        return None if value is None else value  # type: ignore[return-value]

    def materialize(self) -> tuple[CompactTracePoint, ...]:
        return tuple(self)


@dataclass(frozen=True, slots=True, eq=False)
class AutoEvaluation:
    finish_tick: int | None
    dead_tick: int | None
    last_tick: int
    trace: Sequence[CompactTracePoint]
    successful_jumps: tuple[int, ...]
    jump_edges: tuple[int, ...]
    missed_jump_edges: tuple[int, ...]
    unsupported: bool = False
    final_gold_mask: int = 0
    gold_bonus_ticks: int = 0
    gold_events: tuple["GoldCollectionEvent", ...] = ()
    final_opened_locked_door_mask: int = 0
    final_triggered_trapdoor_mask: int = 0
    route_control_events: tuple["RouteControlEvent", ...] = ()
    completed_exit_index: int | None = None
    # Distance in pixels from the ninja to the door it ultimately completes,
    # measured immediately before the completion tick.  For the canonical
    # packed form this is the state after the last serialized input and before
    # the implicit neutral sentinel.  It is a ranking tie-break only; it does
    # not change completion validity or emulator state.
    pre_finish_exit_distance: float | None = None

    def _comparison_key(self) -> tuple:
        # Equality/hash are explicit compatibility operations and therefore a
        # valid place to materialise a native trace.
        return (
            self.finish_tick,
            self.dead_tick,
            self.last_tick,
            tuple(self.trace),
            tuple(self.successful_jumps),
            tuple(self.jump_edges),
            tuple(self.missed_jump_edges),
            self.unsupported,
            self.final_gold_mask,
            self.gold_bonus_ticks,
            tuple(self.gold_events),
            self.final_opened_locked_door_mask,
            self.final_triggered_trapdoor_mask,
            tuple(self.route_control_events),
            self.completed_exit_index,
            self.pre_finish_exit_distance,
        )

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        if other.__class__ is not self.__class__:
            return NotImplemented
        assert isinstance(other, AutoEvaluation)
        return self._comparison_key() == other._comparison_key()

    def __hash__(self) -> int:
        return hash(self._comparison_key())

    @property
    def valid(self) -> bool:
        """Whether this is a completed route the optimiser may keep/output.

        N can set the level-complete flag and then kill the ninja later in the
        same ``Player.CollideVsObjects`` traversal.  Completion is already
        terminal to subsequent engine ticks, so a death recorded on that exact
        completion tick must not invalidate the route.  A death before
        completion, or a terminal dead trace point without completion, remains
        invalid.
        """
        finish_tick = self.finish_tick
        if finish_tick is None or self.unsupported or not self.trace:
            return False
        if self.dead_tick is not None and self.dead_tick != finish_tick:
            return False
        if isinstance(self.trace, _NativeTraceView):
            flags = self.trace.terminal_flags()
            if flags is None:
                return False
            complete, dead = flags
            return not dead or complete
        terminal = self.trace[-1]
        return not terminal.dead or terminal.complete

    @property
    def completed(self) -> bool:
        return self.finish_tick is not None

    @property
    def gold_count(self) -> int:
        return self.final_gold_mask.bit_count()

    @property
    def highscore_value(self) -> int | None:
        if self.finish_tick is None:
            return None
        return self.gold_bonus_ticks - self.finish_tick

    def point(self, tick: int) -> CompactTracePoint | None:
        if isinstance(self.trace, _NativeTraceView):
            return self.trace.point(tick)
        # Traces are normally dense.  Linear fallback also supports a caller
        # deliberately choosing a larger trace_stride.
        if 0 <= tick < len(self.trace) and self.trace[tick].tick == tick:
            return self.trace[tick]
        for point in self.trace:
            if point.tick == tick:
                return point
        return None

    def materialize_trace(self) -> tuple[CompactTracePoint, ...]:
        """Explicitly return the complete public Python trace."""
        return tuple(self.trace)

    def _terminal_summary(self) -> tuple | None:
        if isinstance(self.trace, _NativeTraceView):
            return self.trace.terminal_summary()
        if not self.trace:
            return None
        point = self.trace[-1]
        return (
            point.tick,
            point.x,
            point.y,
            point.player_state,
            point.dead,
            point.complete,
            point.collected_gold_mask,
            point.exploded_mine_mask,
            point.open_exit_mask,
            point.opened_locked_door_mask,
            point.triggered_trapdoor_mask,
        )


def pre_finish_exit_edge_distance(
    level: Level, evaluation: AutoEvaluation
) -> float | None:
    """Return the ninja-edge to exit-edge gap immediately before completion.

    The evaluation stores centre-to-centre distance for the existing ranking
    tie-break.  Status output is more intuitive as the remaining collision
    gap, so subtract both collision radii and clamp any overlap to zero.
    """
    centre_distance = evaluation.pre_finish_exit_distance
    exit_index = evaluation.completed_exit_index
    if (
        centre_distance is None
        or not math.isfinite(centre_distance)
        or exit_index is None
    ):
        return None
    door = level.static_world.entry_for_ref(
        level.static_world.exit_door_ref(exit_index)
    )
    if door is None:
        return None
    return max(0.0, centre_distance - level.player.r - door.r)


@dataclass(frozen=True, slots=True)
class AlignmentMatch:
    candidate_tick: int
    reference_tick: int
    offset: int
    distance: float
    contact_matches: bool
    static_matches: bool
    score_lead: int = 0


@dataclass(frozen=True, slots=True)
class GoldCollectionEvent:
    gold_index: int
    tick: int


@dataclass(frozen=True, slots=True)
class RouteControlEvent:
    """Persistent switch or door state transition observed during a replay."""

    kind: str
    index: int
    tick: int

    @property
    def label(self) -> str:
        names = {
            "exit": "exit key",
            "locked-door": "locked-door key",
            "trapdoor": "trapdoor",
        }
        return f"{names[self.kind]}:{self.index}@{self.tick}"


@dataclass(frozen=True, slots=True)
class RouteControlRepairTarget:
    """Earliest persistent route-control divergence in a failed candidate."""

    candidate_tick: int
    reference_tick: int
    required_exit_mask: int = 0
    required_locked_door_mask: int = 0
    forbidden_trapdoor_mask: int = 0

    @property
    def label(self) -> str:
        parts: list[str] = []
        for index in _iter_set_bit_indices(self.required_exit_mask):
            parts.append(f"require exit key:{index}")
        for index in _iter_set_bit_indices(self.required_locked_door_mask):
            parts.append(f"require locked-door key:{index}")
        for index in _iter_set_bit_indices(self.forbidden_trapdoor_mask):
            parts.append(f"avoid trapdoor:{index}")
        return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class AutoCandidate:
    """Immutable macro candidate; ``working_frames`` includes its sentinel."""

    working_frames: tuple[InputFrame, ...]
    evaluation: AutoEvaluation
    origin: str
    mutations: tuple[str, ...] = ()
    generation: int = 0
    alignment: AlignmentMatch | None = None
    edit_count: int = 0
    sentinel_verified: bool = True
    # Auto repeatedly ranks the same beam members and samples their transition
    # seams.  Cache these immutable replay properties at admission instead of
    # rescanning the complete input stream for every beam selection.
    replay_key: bytes | None = None
    input_transitions: tuple[int, ...] | None = None

    @property
    def frames(self) -> tuple[InputFrame, ...]:
        if self.evaluation.finish_tick is None:
            return self.working_frames[:-1]
        return self.working_frames[: self.evaluation.finish_tick]

    @property
    def finish_tick(self) -> int | None:
        return self.evaluation.finish_tick

    @property
    def output_valid(self) -> bool:
        return self.evaluation.valid and self.sentinel_verified


@dataclass(frozen=True, slots=True)
class AutoStats:
    macro_candidates: int = 0
    macro_evaluations: int = 0
    local_branches: int = 0
    local_simulations: int = 0
    raw_retimes: int = 0
    boundary_retimes: int = 0
    suffix_splices: int = 0
    jump_mutations: int = 0
    pulse_mutations: int = 0
    direction_mutations: int = 0
    repair_attempts: int = 0
    jump_repair_attempts: int = 0
    all_input_repairs: int = 0
    successful_repairs: int = 0
    reference_epochs: int = 0
    deduplicated: int = 0
    gold_repair_attempts: int = 0
    successful_gold_repairs: int = 0
    route_control_repair_attempts: int = 0
    successful_route_control_repairs: int = 0
    structured_repair_attempts: int = 0
    beam_quick_repair_attempts: int = 0
    beam_strategic_repair_attempts: int = 0
    repair_campaigns: int = 0
    repair_campaign_attempts: int = 0
    repair_frontiers_queued: int = 0
    repair_frontiers_dropped: int = 0


@dataclass(frozen=True, slots=True)
class AutoProgress:
    phase: str
    macro_evaluations: int
    budget: int
    best_finish_tick: int | None
    message: str
    local_simulations: int = 0
    repair_index: int = 0
    campaign_index: int = 0
    objective: str = AUTO_OBJECTIVE_SPEEDRUN
    best_objective_value: int | None = None
    best_gold_bonus_ticks: int | None = None
    best_gold_count: int | None = None
    best_exit_edge_distance: float | None = None


@dataclass(frozen=True, slots=True)
class AutoResult:
    frames: tuple[InputFrame, ...]
    baseline_finish_tick: int
    finish_tick: int
    best: AutoCandidate
    stats: AutoStats
    diagnostics: tuple[str, ...]
    beam: tuple[AutoCandidate, ...] = ()
    objective: str = AUTO_OBJECTIVE_SPEEDRUN
    baseline_gold_mask: int = 0
    gold_mask: int = 0
    baseline_gold_bonus_ticks: int = 0
    gold_bonus_ticks: int = 0
    baseline_objective_value: int = 0
    objective_value: int = 0
    require_reference_gold: bool = False

    @property
    def improved(self) -> bool:
        if self.objective == AUTO_OBJECTIVE_HIGHSCORE:
            return self.objective_value > self.baseline_objective_value
        return self.finish_tick < self.baseline_finish_tick

    @property
    def baseline_gold_count(self) -> int:
        return self.baseline_gold_mask.bit_count()

    @property
    def gold_count(self) -> int:
        return self.gold_mask.bit_count()


@dataclass(slots=True)
class _RepairFrontier:
    """A failed beam candidate retained until the scheduler dispatches it."""

    candidate: AutoCandidate
    phase: str
    label: str
    strategic: bool
    intended_lead: int
    reference_offset: int
    repair_reference: AutoEvaluation
    inherited_misses: tuple[int, ...]
    reference_successful_jumps: tuple[int, ...] = ()
    mutation: RetimeMutation | None = None
    required_gold_mask: int = 0
    require_failure_jump: bool = True
    epoch: int = 0
    attempts: int = 0
    local_simulations: int = 0
    frame_ahead_seen: bool = False
    failure_regions: tuple[int, ...] = ()


def _has_measured_frame_lead(candidate: AutoCandidate) -> bool:
    """Return whether trajectory alignment places the candidate ahead in time."""
    return candidate.alignment is not None and candidate.alignment.offset > 0


def _frame_ahead_repair_eligible(
    candidate: AutoCandidate,
    *,
    frame_ahead_seen: bool = False,
) -> bool:
    """Keep a measured trajectory lead sticky for one repair campaign."""
    return bool(frame_ahead_seen or _has_measured_frame_lead(candidate))


def _repair_attempt_local_limit(
    config: AutoConfig,
    *,
    frame_ahead: bool,
) -> int:
    """Return one attempt's local-search allowance without compounding bonuses."""
    if not config.repair_local_limit or not frame_ahead:
        return config.repair_local_limit
    return config.repair_local_limit * config.frame_ahead_repair_multiplier


def _repair_campaign_local_limit(
    config: AutoConfig,
    *,
    frame_ahead: bool,
) -> int:
    """Return a campaign's local-search allowance with the frame-ahead bonus."""
    if not config.repair_campaign_local_limit or not frame_ahead:
        return config.repair_campaign_local_limit
    return (
        config.repair_campaign_local_limit
        * config.frame_ahead_repair_multiplier
    )


ProgressCallback = Callable[[AutoProgress], None]
BestCallback = Callable[[AutoCandidate], None]
RepairProgressCallback = Callable[[int, int], None]


def auto_objective_value(evaluation: AutoEvaluation, objective: str) -> int | None:
    """Return the completed-run objective on a larger-is-better scale."""
    if objective not in AUTO_OBJECTIVES:
        raise ValueError(
            "objective must be one of: " + ", ".join(AUTO_OBJECTIVES)
        )
    if evaluation.finish_tick is None:
        return None
    if objective == AUTO_OBJECTIVE_HIGHSCORE:
        return evaluation.gold_bonus_ticks - evaluation.finish_tick
    return -evaluation.finish_tick


def _gold_requirement_satisfied(
    evaluation: AutoEvaluation,
    required_gold_mask: int,
    config: AutoConfig,
) -> bool:
    return (
        not config.require_reference_gold
        or evaluation.final_gold_mask & required_gold_mask == required_gold_mask
    )


def _objective_no_worse(
    evaluation: AutoEvaluation,
    baseline: AutoEvaluation,
    config: AutoConfig,
    *,
    required_gold_mask: int,
) -> bool:
    if not evaluation.valid or not _gold_requirement_satisfied(
        evaluation, required_gold_mask, config
    ):
        return False
    candidate_value = auto_objective_value(evaluation, config.objective)
    baseline_value = auto_objective_value(baseline, config.objective)
    assert candidate_value is not None and baseline_value is not None
    return candidate_value >= baseline_value


def _objective_better(
    candidate: AutoEvaluation,
    incumbent: AutoEvaluation,
    config: AutoConfig,
    *,
    required_gold_mask: int,
) -> bool:
    if not candidate.valid or not _gold_requirement_satisfied(
        candidate, required_gold_mask, config
    ):
        return False
    candidate_value = auto_objective_value(candidate, config.objective)
    incumbent_value = auto_objective_value(incumbent, config.objective)
    assert candidate_value is not None and incumbent_value is not None
    return candidate_value > incumbent_value


def _objective_equal(
    candidate: AutoEvaluation,
    baseline: AutoEvaluation,
    config: AutoConfig,
    *,
    required_gold_mask: int,
) -> bool:
    if not candidate.valid or not _gold_requirement_satisfied(
        candidate, required_gold_mask, config
    ):
        return False
    candidate_value = auto_objective_value(candidate, config.objective)
    baseline_value = auto_objective_value(baseline, config.objective)
    assert candidate_value is not None and baseline_value is not None
    return candidate_value == baseline_value


def _editable_tuple(frames: Sequence[InputFrame]) -> tuple[InputFrame, ...]:
    return tuple(editable_frames(frames))


def _working_replay(frames: Sequence[InputFrame]) -> tuple[InputFrame, ...]:
    """Return a fixed replay body followed by exactly one neutral sentinel."""
    return _editable_tuple(frames) + (NEUTRAL_INPUT,)


def _frame_key(frames: Sequence[InputFrame]) -> bytes:
    """Compact held-input identity used by bounded beams and deduplication."""
    return bytes(
        int(frame.left) | (int(frame.right) << 1) | (int(frame.jump) << 2)
        for frame in frames
    )


def _first_changed_frame(
    original: Sequence[InputFrame], modified: Sequence[InputFrame]
) -> int:
    for index, (left, right) in enumerate(zip(original, modified)):
        if (left.left, left.right, left.jump) != (
            right.left,
            right.right,
            right.jump,
        ):
            return index
    return min(len(original), len(modified))


def _iter_set_bit_indices(mask: int) -> Iterable[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def _sign_bin(value: float) -> int:
    return -1 if value < -1e-9 else 1 if value > 1e-9 else 0


def _evaluate_working(
    level: Level,
    working_frames: Sequence[InputFrame],
    *,
    trace_stride: int = 1,
) -> AutoEvaluation:
    if not working_frames:
        raise ValueError("working replay must contain a neutral sentinel")
    sentinel = working_frames[-1]
    if sentinel.left or sentinel.right or sentinel.jump:
        raise ValueError("working replay must end in a neutral sentinel")

    analysis = _native_session(level).evaluate_replay(
        working_frames, trace_stride=trace_stride
    )
    (
        finish_tick,
        dead_tick,
        last_tick,
        unsupported,
        completed_exit_index,
        has_pre_finish_exit_distance,
        pre_finish_exit_distance,
        gold_bonus_ticks,
        final_gold_mask,
        _final_exploded_mine_mask,
        _final_open_exit_mask,
        final_opened_locked_door_mask,
        final_triggered_trapdoor_mask,
    ) = analysis.summary()

    def optional_tick(raw_value: object) -> int | None:
        value = int(raw_value)
        return None if value < 0 else value
    route_kinds = {0: "exit", 1: "locked-door", 2: "trapdoor"}
    return AutoEvaluation(
        finish_tick=optional_tick(finish_tick),
        dead_tick=optional_tick(dead_tick),
        last_tick=int(last_tick),
        trace=_NativeTraceView(analysis),
        successful_jumps=tuple(
            int(tick) for tick in analysis.successful_jumps()
        ),
        jump_edges=tuple(int(tick) for tick in analysis.jump_edges()),
        missed_jump_edges=tuple(
            int(tick) for tick in analysis.missed_jump_edges()
        ),
        unsupported=bool(unsupported),
        final_gold_mask=int(final_gold_mask),
        gold_bonus_ticks=int(gold_bonus_ticks),
        gold_events=tuple(
            GoldCollectionEvent(int(index), int(tick))
            for index, tick in analysis.gold_events()
        ),
        final_opened_locked_door_mask=int(final_opened_locked_door_mask),
        final_triggered_trapdoor_mask=int(final_triggered_trapdoor_mask),
        route_control_events=tuple(
            RouteControlEvent(route_kinds[int(kind)], int(index), int(tick))
            for kind, index, tick in analysis.route_control_events()
        ),
        completed_exit_index=optional_tick(completed_exit_index),
        pre_finish_exit_distance=(
            float(pre_finish_exit_distance)
            if has_pre_finish_exit_distance
            else None
        ),
    )


def evaluate_replay_with_sentinel(
    level: Level,
    frames: Sequence[InputFrame],
    *,
    trace_stride: int = 1,
) -> AutoEvaluation:
    """Evaluate serialized inputs followed by n's implicit neutral sentinel.

    The returned ``finish_tick`` is a zero-based simulation step and therefore
    also the number of frames that must be serialized.
    """
    if trace_stride < 1:
        raise ValueError("trace_stride must be positive")
    return _evaluate_working(level, _working_replay(frames), trace_stride=trace_stride)


def verify_trimmed_replay(
    level: Level,
    frames: Sequence[InputFrame],
    *,
    expected_finish_tick: int | None = None,
    expected_gold_mask: int | None = None,
    expected_gold_bonus_ticks: int | None = None,
) -> AutoEvaluation:
    """Re-simulate a final body plus sentinel and reject any score drift."""
    result = evaluate_replay_with_sentinel(level, frames)
    expected = len(frames) if expected_finish_tick is None else expected_finish_tick
    if result.finish_tick != expected or expected != len(frames):
        raise ValueError(
            "trimmed replay did not complete on its neutral sentinel: "
            f"expected tick {expected}, observed {result.finish_tick}"
        )
    if expected_gold_mask is not None and result.final_gold_mask != expected_gold_mask:
        raise ValueError(
            "trimmed replay collected a different gold set: "
            f"expected mask {expected_gold_mask:#x}, observed {result.final_gold_mask:#x}"
        )
    if (
        expected_gold_bonus_ticks is not None
        and result.gold_bonus_ticks != expected_gold_bonus_ticks
    ):
        raise ValueError(
            "trimmed replay produced a different gold bonus: "
            f"expected {expected_gold_bonus_ticks}, observed {result.gold_bonus_ticks}"
        )
    return result


def _normalise_completed_working(
    level: Level,
    working_frames: Sequence[InputFrame],
    evaluation: AutoEvaluation,
    *,
    trace_stride: int,
    preserve_body_length: int | None = None,
) -> tuple[tuple[InputFrame, ...], AutoEvaluation, bool]:
    """Crop a completion only when its winning input can become the sentinel.

    A macro candidate can reach the exit on an ordinary input before the fixed
    workspace's trailing neutral frame. N's packed replay convention cannot
    represent that input at the declared completion tick: the tick must instead
    be the implicit neutral sentinel. Re-simulate the cropped form immediately
    so such candidates cannot advance the reference epoch or outrank a truly
    serialisable completion.
    """
    fixed = tuple(working_frames)
    finish_tick = evaluation.finish_tick
    if not evaluation.valid or finish_tick is None:
        return fixed, evaluation, False
    if finish_tick == len(fixed) - 1:
        return fixed, evaluation, True

    normalised = fixed[:finish_tick] + (NEUTRAL_INPUT,)
    normalised_evaluation = _evaluate_working(
        level, normalised, trace_stride=trace_stride
    )
    if (
        normalised_evaluation.valid
        and normalised_evaluation.finish_tick == finish_tick
        and finish_tick == len(normalised) - 1
    ):
        if preserve_body_length is not None:
            if preserve_body_length < finish_tick:
                raise ValueError(
                    "preserved working body cannot be shorter than its finish tick"
                )
            preserved = (
                normalised[:-1]
                + (NEUTRAL_INPUT,) * (preserve_body_length - finish_tick)
                + (NEUTRAL_INPUT,)
            )
            return preserved, normalised_evaluation, True
        return normalised, normalised_evaluation, True
    return fixed, evaluation, False


def _trace_distance(a: CompactTracePoint, b: CompactTracePoint) -> float:
    """Heuristic route distance; deliberately not a savestate equivalence."""
    # These fields distinguish control topology for ranking and repair, but
    # they are deliberately soft: simulation, not a reference mask, decides
    # whether an alternate completed route is valid.
    static_penalty = _TRACE_GOLD_BIT_PENALTY * (
        a.collected_gold_mask ^ b.collected_gold_mask
    ).bit_count()
    static_penalty += _TRACE_MINE_BIT_PENALTY * (
        a.exploded_mine_mask ^ b.exploded_mine_mask
    ).bit_count()
    static_penalty += _TRACE_EXIT_BIT_PENALTY * (
        a.open_exit_mask ^ b.open_exit_mask
    ).bit_count()
    static_penalty += _TRACE_LOCKED_DOOR_BIT_PENALTY * (
        a.opened_locked_door_mask ^ b.opened_locked_door_mask
    ).bit_count()
    static_penalty += _TRACE_TRAPDOOR_BIT_PENALTY * (
        a.triggered_trapdoor_mask ^ b.triggered_trapdoor_mask
    ).bit_count()
    contact_penalty = (
        0.0
        if a.contact_key == b.contact_key
        else _TRACE_CONTACT_MISMATCH_PENALTY
    )
    if a.in_air != b.in_air:
        contact_penalty += _TRACE_IN_AIR_MISMATCH_PENALTY
    if a.near_wall != b.near_wall:
        contact_penalty += _TRACE_NEAR_WALL_MISMATCH_PENALTY
    return (
        _TRACE_POSITION_WEIGHT
        * ((a.x - b.x) ** 2 + (a.y - b.y) ** 2)
        + _TRACE_VELOCITY_WEIGHT
        * ((a.vx - b.vx) ** 2 + (a.vy - b.vy) ** 2)
        + contact_penalty
        + static_penalty
    )


def _alignment_route_matches(
    candidate: CompactTracePoint,
    reference: CompactTracePoint,
    completed_exit_index: int | None,
) -> bool:
    """Check only the known completion key as a hard splice prerequisite."""
    if completed_exit_index is None:
        return candidate.route_progress_key == reference.route_progress_key
    bit = 1 << completed_exit_index
    return not (
        reference.open_exit_mask & bit and not candidate.open_exit_mask & bit
    )


def _native_trace_analysis(evaluation: AutoEvaluation) -> object | None:
    trace = evaluation.trace
    return trace.analysis if isinstance(trace, _NativeTraceView) else None


def find_baseline_alignment(
    candidate: AutoEvaluation,
    baseline: AutoEvaluation,
    *,
    max_alignment: int = 3,
    max_negative_alignment: int = 0,
    position_tolerance: float = 3.0,
    velocity_tolerance: float = 0.75,
    objective: str = AUTO_OBJECTIVE_SPEEDRUN,
    reference_completion_exit_index: int | None = None,
) -> AlignmentMatch | None:
    """Find a stable reference rejoin which advances the selected objective.

    Speedrun mode preserves the v2.9 positive-offset matcher exactly. Highscore
    mode also permits a bounded raw-time lag when extra gold makes the matched
    route state ahead on ``gold bonus - elapsed ticks``.
    """
    if objective not in AUTO_OBJECTIVES:
        raise ValueError(
            "objective must be one of: " + ", ".join(AUTO_OBJECTIVES)
        )
    if max_alignment < 0 or max_negative_alignment < 0:
        raise ValueError("alignment bounds must be non-negative")
    candidate_analysis = _native_trace_analysis(candidate)
    baseline_analysis = _native_trace_analysis(baseline)
    if (
        candidate_analysis is not None
        and baseline_analysis is not None
        and math.isfinite(position_tolerance)
        and position_tolerance >= 0.0
        and math.isfinite(velocity_tolerance)
        and velocity_tolerance >= 0.0
    ):
        raw_match = candidate_analysis.find_alignment(
            baseline_analysis,
            objective=(0 if objective == AUTO_OBJECTIVE_SPEEDRUN else 1),
            max_alignment=min(max_alignment, max(0, baseline.last_tick)),
            max_negative_alignment=min(
                max_negative_alignment, max(0, candidate.last_tick)
            ),
            scan_limit=192,
            reference_completion_exit_index=(
                -1
                if reference_completion_exit_index is None
                else reference_completion_exit_index
            ),
            position_tolerance=position_tolerance,
            velocity_tolerance=velocity_tolerance,
            position_weight=_TRACE_POSITION_WEIGHT,
            velocity_weight=_TRACE_VELOCITY_WEIGHT,
            contact_mismatch_penalty=_TRACE_CONTACT_MISMATCH_PENALTY,
            in_air_mismatch_penalty=_TRACE_IN_AIR_MISMATCH_PENALTY,
            near_wall_mismatch_penalty=_TRACE_NEAR_WALL_MISMATCH_PENALTY,
            gold_bit_penalty=_TRACE_GOLD_BIT_PENALTY,
            mine_bit_penalty=_TRACE_MINE_BIT_PENALTY,
            exit_bit_penalty=_TRACE_EXIT_BIT_PENALTY,
            locked_door_bit_penalty=_TRACE_LOCKED_DOOR_BIT_PENALTY,
            trapdoor_bit_penalty=_TRACE_TRAPDOOR_BIT_PENALTY,
        )
        if raw_match is None:
            return None
        return AlignmentMatch(
            candidate_tick=int(raw_match[0]),
            reference_tick=int(raw_match[1]),
            offset=int(raw_match[2]),
            distance=float(raw_match[3]),
            contact_matches=bool(raw_match[4]),
            static_matches=bool(raw_match[5]),
            score_lead=int(raw_match[6]),
        )
    if objective == AUTO_OBJECTIVE_SPEEDRUN:
        if max_alignment < 1:
            return None
        dense_reference = bool(baseline.trace) and (
            baseline.trace[0].tick == 0
            and baseline.trace[-1].tick == baseline.last_tick
            and len(baseline.trace) == baseline.last_tick + 1
        )
        base_by_tick = (
            {}
            if dense_reference
            else {point.tick: point for point in baseline.trace}
        )
        qualifying: dict[
            int, tuple[CompactTracePoint, CompactTracePoint, float]
        ] = {}
        # Recent points are the useful splice sites. Capping this scan also keeps
        # matching cheap for very long community replays.
        for point in candidate.trace[-192:]:
            if point.dead or point.complete:
                continue
            if dense_reference and 0 <= point.tick <= baseline.last_tick:
                zero = baseline.trace[point.tick]
            else:
                zero = base_by_tick.get(point.tick)
            zero_distance = (
                _trace_distance(point, zero) if zero is not None else float("inf")
            )
            nearest: tuple[float, int, CompactTracePoint] | None = None
            remaining_reference = max(0, baseline.last_tick - point.tick)
            for offset in range(1, min(max_alignment, remaining_reference) + 1):
                reference_tick = point.tick + offset
                reference = (
                    baseline.trace[reference_tick]
                    if dense_reference
                    else base_by_tick.get(reference_tick)
                )
                if reference is None or reference.dead:
                    continue
                if not _alignment_route_matches(
                    point, reference, reference_completion_exit_index
                ):
                    continue
                if point.contact_key != reference.contact_key:
                    continue
                if (
                    math.hypot(point.x - reference.x, point.y - reference.y)
                    > position_tolerance
                ):
                    continue
                if (
                    math.hypot(point.vx - reference.vx, point.vy - reference.vy)
                    > velocity_tolerance
                ):
                    continue
                distance = _trace_distance(point, reference)
                if nearest is None or (distance, offset) < (nearest[0], nearest[1]):
                    nearest = (distance, offset, reference)
            # Merely being within tolerance is not enough: the positive offset
            # must explain this state better than the ordinary offset-zero state.
            if nearest is not None and nearest[0] + 1e-6 < zero_distance:
                distance, offset, reference = nearest
                qualifying[point.tick] = (point, reference, distance)

        # Require two adjacent checkpoints to prevent a crossing trajectory or
        # stationary section manufacturing a frame lead.
        runs: list[
            tuple[int, int, float, int, CompactTracePoint, CompactTracePoint]
        ] = []
        run_start: int | None = None
        run_offset: int | None = None
        run_distance = 0.0
        previous_tick: int | None = None
        for tick in sorted(qualifying):
            point, reference, distance = qualifying[tick]
            offset = reference.tick - point.tick
            if (
                previous_tick is None
                or tick != previous_tick + 1
                or offset != run_offset
            ):
                run_start = tick
                run_offset = offset
                run_distance = distance
            else:
                run_distance += distance
            assert run_start is not None and run_offset is not None
            run_length = tick - run_start + 1
            if run_length >= 2:
                runs.append(
                    (
                        run_length,
                        tick,
                        run_distance / run_length,
                        run_offset,
                        point,
                        reference,
                    )
                )
            previous_tick = tick
        if not runs:
            return None
        _run_length, _, average, offset, point, reference = max(
            runs, key=lambda run: (run[0], run[1], -run[2], run[3])
        )
        return AlignmentMatch(
            candidate_tick=point.tick,
            reference_tick=reference.tick,
            offset=offset,
            distance=average,
            contact_matches=True,
            static_matches=point.static_key == reference.static_key,
            score_lead=offset,
        )

    if max_alignment < 1 and max_negative_alignment < 1:
        return None
    dense_reference = bool(baseline.trace) and (
        baseline.trace[0].tick == 0
        and baseline.trace[-1].tick == baseline.last_tick
        and len(baseline.trace) == baseline.last_tick + 1
    )
    base_by_tick = (
        {} if dense_reference else {point.tick: point for point in baseline.trace}
    )
    qualifying_highscore: dict[
        int, tuple[CompactTracePoint, CompactTracePoint, float, int]
    ] = {}
    for point in candidate.trace[-192:]:
        if point.dead or point.complete:
            continue
        if dense_reference and 0 <= point.tick <= baseline.last_tick:
            zero = baseline.trace[point.tick]
        else:
            zero = base_by_tick.get(point.tick)
        zero_distance = (
            _trace_distance(point, zero) if zero is not None else float("inf")
        )
        best_match: tuple[float, int, int, CompactTracePoint] | None = None
        minimum_offset = max(-max_negative_alignment, -point.tick)
        maximum_offset = min(max_alignment, baseline.last_tick - point.tick)
        for offset in range(minimum_offset, maximum_offset + 1):
            reference_tick = point.tick + offset
            reference = (
                baseline.trace[reference_tick]
                if dense_reference
                else base_by_tick.get(reference_tick)
            )
            if reference is None or reference.dead:
                continue
            score_lead = (
                offset + point.gold_bonus_ticks - reference.gold_bonus_ticks
            )
            # Offset zero is useful when the route has gained/lost gold at the
            # same raw tick, but the unmodified reference must never align to
            # itself merely because its kinematics are identical.
            if offset == 0 and score_lead == 0:
                continue
            if not _alignment_route_matches(
                point, reference, reference_completion_exit_index
            ):
                continue
            if point.contact_key != reference.contact_key:
                continue
            if (
                math.hypot(point.x - reference.x, point.y - reference.y)
                > position_tolerance
            ):
                continue
            if (
                math.hypot(point.vx - reference.vx, point.vy - reference.vy)
                > velocity_tolerance
            ):
                continue
            distance = _trace_distance(point, reference)
            # A non-zero offset must explain the trajectory better than the
            # ordinary same-tick state. Offset zero is itself the comparison
            # state and is admitted only because its score contribution differs.
            if offset != 0 and distance + 1e-6 >= zero_distance:
                continue
            proposal = (distance, -score_lead, abs(offset), reference.tick)
            if best_match is None:
                best_match = (distance, score_lead, offset, reference)
            else:
                incumbent = (
                    best_match[0],
                    -best_match[1],
                    abs(best_match[2]),
                    best_match[3].tick,
                )
                if proposal < incumbent:
                    best_match = (distance, score_lead, offset, reference)
        if best_match is not None:
            distance, score_lead, _offset, reference = best_match
            qualifying_highscore[point.tick] = (
                point,
                reference,
                distance,
                score_lead,
            )

    runs_highscore: list[
        tuple[
            int,
            int,
            float,
            int,
            int,
            CompactTracePoint,
            CompactTracePoint,
        ]
    ] = []
    run_start: int | None = None
    run_offset: int | None = None
    run_distance = 0.0
    run_min_score_lead = 0
    previous_tick: int | None = None
    for tick in sorted(qualifying_highscore):
        point, reference, distance, score_lead = qualifying_highscore[tick]
        offset = reference.tick - point.tick
        if (
            previous_tick is None
            or tick != previous_tick + 1
            or offset != run_offset
        ):
            run_start = tick
            run_offset = offset
            run_distance = distance
            run_min_score_lead = score_lead
        else:
            run_distance += distance
            run_min_score_lead = min(run_min_score_lead, score_lead)
        assert run_start is not None and run_offset is not None
        run_length = tick - run_start + 1
        if run_length >= 2:
            runs_highscore.append(
                (
                    run_length,
                    tick,
                    run_distance / run_length,
                    run_offset,
                    run_min_score_lead,
                    point,
                    reference,
                )
            )
        previous_tick = tick
    if not runs_highscore:
        return None
    (
        _run_length,
        _,
        average,
        offset,
        score_lead,
        point,
        reference,
    ) = max(
        runs_highscore,
        key=lambda run: (run[0], run[1], run[4], -run[2], -abs(run[3])),
    )
    return AlignmentMatch(
        candidate_tick=point.tick,
        reference_tick=reference.tick,
        offset=offset,
        distance=average,
        contact_matches=True,
        static_matches=point.static_key == reference.static_key,
        score_lead=score_lead,
    )


def apply_reference_suffix_splice(
    candidate_working: Sequence[InputFrame],
    reference_working: Sequence[InputFrame],
    match: AlignmentMatch,
    *,
    max_body_length: int | None = None,
) -> tuple[InputFrame, ...]:
    """Continue from an aligned candidate state using the reference suffix."""
    if not candidate_working or not reference_working:
        raise ValueError("working replays cannot be empty")
    candidate_next = match.candidate_tick + 1
    reference_next = match.reference_tick + 1
    if candidate_next > len(candidate_working) - 1:
        raise ValueError("candidate alignment lies beyond its editable body")
    if reference_next > len(reference_working) - 1:
        raise ValueError("reference alignment lies beyond its editable body")

    prefix = tuple(candidate_working[:candidate_next])
    suffix = tuple(
        InputFrame(frame.left, frame.right, frame.jump, None)
        for frame in reference_working[reference_next:-1]
    )
    body = prefix + suffix
    if max_body_length is None:
        target_body_length = max(len(candidate_working) - 1, len(body))
    else:
        if max_body_length < 0:
            raise ValueError("max_body_length must be non-negative")
        target_body_length = max_body_length
        body = body[:target_body_length]
    return body + (NEUTRAL_INPUT,) * (target_body_length - len(body) + 1)


def detect_shifted_missed_jumps(
    reference_successful_jumps: Iterable[int],
    candidate: AutoEvaluation,
    mutation: RetimeMutation,
) -> tuple[int, ...]:
    """Diagnose successful reference presses lost by a suffix retime."""
    actual_edges = set(candidate.jump_edges)
    actual_successes = set(candidate.successful_jumps)
    missing: list[int] = []
    for tick in reference_successful_jumps:
        expected = tick + mutation.delta if tick >= mutation.suffix_start else tick
        if (
            expected <= candidate.last_tick
            and expected in actual_edges
            and expected not in actual_successes
        ):
            missing.append(expected)
    return tuple(missing)


def _jump_pulses(frames: Sequence[InputFrame]) -> tuple[tuple[int, int], ...]:
    pulses: list[tuple[int, int]] = []
    index = 0
    limit = len(frames)
    while index < limit:
        if not frames[index].jump:
            index += 1
            continue
        end = index
        while end + 1 < limit and frames[end + 1].jump:
            end += 1
        pulses.append((index, end))
        index = end + 1
    return tuple(pulses)


def mutate_jump_pulse(
    working_frames: Sequence[InputFrame],
    pulse_index: int,
    *,
    start_delta: int = 0,
    hold_delta: int = 0,
    hold_length: int | None = None,
) -> tuple[InputFrame, ...]:
    """Move/resize one held-jump pulse while retaining horizontal inputs."""
    body = _editable_tuple(working_frames[:-1])
    pulses = _jump_pulses(body)
    return _mutate_jump_pulse_known(
        body,
        pulses,
        pulse_index,
        start_delta=start_delta,
        hold_delta=hold_delta,
        hold_length=hold_length,
    )


def _jump_only_frame(frame: InputFrame, held: bool) -> InputFrame:
    """Return a normalised frame with only its held-jump bit replaced."""
    if frame.jump == held and frame.jump_trigger is None:
        return frame
    return InputFrame(frame.left, frame.right, held, None)


def _mutate_jump_pulse_known(
    body: Sequence[InputFrame],
    pulses: Sequence[tuple[int, int]],
    pulse_index: int,
    *,
    start_delta: int = 0,
    hold_delta: int = 0,
    hold_length: int | None = None,
) -> tuple[InputFrame, ...]:
    """Mutate one pulse using an already-normalised body and pulse table.

    The local jump mutator's fast path established that only the symmetric
    difference of the old and new intervals needs touching.  Auto used to
    normalise the full replay and rediscover every pulse for each proposal.
    """
    if not 0 <= pulse_index < len(pulses):
        raise IndexError("jump pulse index outside replay")
    start, end = pulses[pulse_index]
    old_length = end - start + 1
    new_length = hold_length if hold_length is not None else old_length + hold_delta
    new_start = start + start_delta
    new_end = new_start + new_length - 1
    previous_end = pulses[pulse_index - 1][1] if pulse_index else -1
    next_start = pulses[pulse_index + 1][0] if pulse_index + 1 < len(pulses) else len(body)
    if new_length < 1 or new_start <= previous_end or new_end >= next_start:
        raise ValueError("jump mutation overlaps another pulse or replay boundary")

    changed = list(body)
    for tick in range(start, end + 1):
        if tick < new_start or tick > new_end:
            changed[tick] = _jump_only_frame(changed[tick], False)
    for tick in range(new_start, new_end + 1):
        if tick < start or tick > end:
            changed[tick] = _jump_only_frame(changed[tick], True)
    return tuple(changed) + (NEUTRAL_INPUT,)


def mutate_jump_interval(
    working_frames: Sequence[InputFrame],
    start: int,
    length: int,
    *,
    held: bool,
) -> tuple[InputFrame, ...]:
    """Insert, extend, or erase a jump-only pulse without touching horizontal."""
    body = _editable_tuple(working_frames[:-1])
    return _mutate_jump_interval_known(body, start, length, held=held)


def _mutate_jump_interval_known(
    body: Sequence[InputFrame],
    start: int,
    length: int,
    *,
    held: bool,
) -> tuple[InputFrame, ...]:
    """Apply one jump interval edit to an already-normalised replay body."""
    if start < 0 or length < 1 or start + length > len(body):
        raise ValueError("jump interval lies outside the editable replay body")
    result = list(body)
    changed = False
    for tick in range(start, start + length):
        frame = result[tick]
        changed |= frame.jump != held
        result[tick] = _jump_only_frame(frame, held)
    if not changed:
        raise ValueError("jump interval mutation does not change any input")
    return tuple(result) + (NEUTRAL_INPUT,)


def _derive_repair_search_rng(
    master_seed: int,
    repair_number: int,
    stream_tag: str,
) -> random.Random:
    """Return a stable independent RNG stream for one repair sub-search.

    The derivation deliberately avoids Python's process-randomised ``hash()``
    and does not draw from the stochastic beam RNG.  Consequently local repair
    traversal is reproducible from the Auto seed while changes in repair branch
    counts cannot perturb later beam mutations.
    """
    payload = (
        f"{master_seed}\0{repair_number}\0{stream_tag}"
    ).encode("utf-8")
    digest = hashlib.blake2b(
        payload,
        digest_size=16,
        person=b"nv14-repair-v1",
    ).digest()
    return random.Random(int.from_bytes(digest, "big"))


def _seeded_primary_repair_order(
    master_seed: int,
    repair_number: int,
) -> tuple[str, str]:
    """Choose jump-vs-direction repair order without perturbing beam RNG state.

    Every repair attempt receives an independent deterministic coin flip.  The
    result is reproducible from the Auto seed and repair number, while work
    performed inside either repair method cannot affect later ordering.
    """
    rng = _derive_repair_search_rng(master_seed, repair_number, "primary-order")
    if rng.random() < 0.5:
        return ("jump", "direction")
    return ("direction", "jump")


def _effective_repair_search_rng(
    config: AutoConfig,
    supplied_rng: random.Random | None,
    *,
    stream_tag: str,
) -> random.Random | None:
    """Resolve fixed traversal or a deterministic randomized fallback stream."""
    if config.repair_search_order == AUTO_REPAIR_SEARCH_ORDER_FIXED:
        return None
    if supplied_rng is not None:
        return supplied_rng
    # Public callers of the individual repair functions do not have a global
    # repair-attempt index.  Repair-number-zero substreams keep those direct
    # calls deterministic; optimise_autonomous supplies per-attempt streams.
    return _derive_repair_search_rng(config.seed, 0, stream_tag)


def _repair_sensitivity_tick_order(
    look_start: int,
    look_end: int,
    failure_tick: int,
    rng: random.Random | None,
) -> tuple[int, ...]:
    """Order sensitivity probes chronologically or by broad seeded strata."""
    if look_start > look_end:
        return ()
    if rng is None:
        return tuple(range(look_start, look_end + 1))

    remaining = list(range(look_start, look_end + 1))
    ordered: list[int] = []
    if look_start <= failure_tick <= look_end:
        ordered.append(failure_tick)
        remaining.remove(failure_tick)
    if not remaining:
        return tuple(ordered)

    # Up to 24 temporal strata match the later sensitivity candidate cap.  A
    # round-robin pass through shuffled strata gives a truncated budget broad
    # lookback coverage instead of repeatedly spending it on adjacent old frames.
    stratum_count = min(24, len(remaining))
    base_size, extra = divmod(len(remaining), stratum_count)
    strata: list[list[int]] = []
    cursor = 0
    for index in range(stratum_count):
        size = base_size + int(index < extra)
        stratum = remaining[cursor : cursor + size]
        cursor += size
        rng.shuffle(stratum)
        strata.append(stratum)
    rng.shuffle(strata)

    while any(strata):
        for stratum in strata:
            if stratum:
                ordered.append(stratum.pop())
    return tuple(ordered)


def _direction_search_order(
    original_direction: int,
    rng: random.Random | None,
    *,
    source_first: bool,
) -> tuple[int, ...]:
    """Return each L/N/R direction once, optionally preserving source first."""
    if source_first:
        alternatives = [
            direction
            for direction in (0, -1, 1)
            if direction != original_direction
        ]
        if rng is not None:
            rng.shuffle(alternatives)
        return (original_direction, *alternatives)

    alternatives = [
        direction
        for direction in (-1, 0, 1)
        if direction != original_direction
    ]
    if rng is not None:
        rng.shuffle(alternatives)
    return tuple(alternatives)


def _pair_direction_search_order(
    first_original: int,
    second_original: int,
    rng: random.Random | None,
) -> tuple[tuple[int, int], ...]:
    """Return fixed legacy pair traversal or shuffled genuinely new pairs."""
    if rng is None:
        return tuple(
            (first_direction, second_direction)
            for first_direction in (-1, 0, 1)
            for second_direction in (-1, 0, 1)
        )
    combinations = [
        (first_direction, second_direction)
        for first_direction in (-1, 0, 1)
        if first_direction != first_original
        for second_direction in (-1, 0, 1)
        if second_direction != second_original
    ]
    rng.shuffle(combinations)
    return tuple(combinations)


def _all_input_search_order(
    original: tuple[int, bool],
    rng: random.Random | None,
) -> tuple[tuple[int, bool], ...]:
    """Keep the source input first and optionally shuffle the other five."""
    alternatives = [
        (direction, jump)
        for jump in (original[1], not original[1])
        for direction in (0, -1, 1)
        if (direction, jump) != original
    ]
    if rng is not None:
        rng.shuffle(alternatives)
    return (original, *alternatives)


def _native_trace_target(point: CompactTracePoint) -> TraceTargetSpec:
    """Compile Python's route objective definition into immutable C data."""
    return TraceTargetSpec(
        x=point.x,
        y=point.y,
        vx=point.vx,
        vy=point.vy,
        player_state=point.player_state,
        in_air=point.in_air,
        near_wall=point.near_wall,
        wall_x=point.wall_x,
        floor_x=point.floor_x,
        floor_y=point.floor_y,
        previous_jump_held=point.previous_jump_held,
        collected_gold_mask=point.collected_gold_mask,
        exploded_mine_mask=point.exploded_mine_mask,
        open_exit_mask=point.open_exit_mask,
        opened_locked_door_mask=point.opened_locked_door_mask,
        triggered_trapdoor_mask=point.triggered_trapdoor_mask,
        position_weight=_TRACE_POSITION_WEIGHT,
        velocity_weight=_TRACE_VELOCITY_WEIGHT,
        contact_mismatch_penalty=_TRACE_CONTACT_MISMATCH_PENALTY,
        in_air_mismatch_penalty=_TRACE_IN_AIR_MISMATCH_PENALTY,
        near_wall_mismatch_penalty=_TRACE_NEAR_WALL_MISMATCH_PENALTY,
        gold_bit_penalty=_TRACE_GOLD_BIT_PENALTY,
        mine_bit_penalty=_TRACE_MINE_BIT_PENALTY,
        exit_bit_penalty=_TRACE_EXIT_BIT_PENALTY,
        locked_door_bit_penalty=_TRACE_LOCKED_DOOR_BIT_PENALTY,
        trapdoor_bit_penalty=_TRACE_TRAPDOOR_BIT_PENALTY,
    )


def _native_mask_groups(
    kind: int,
    mask: int,
) -> tuple[InteractionGroupSpec, ...]:
    return tuple(
        InteractionGroupSpec((InteractionAtomSpec(kind, index),))
        for index in _iter_set_bit_indices(mask)
    )


def _native_repair_groups(
    *,
    required_gold_mask: int,
    required_exit_mask: int,
    required_locked_door_mask: int,
    forbidden_trapdoor_mask: int,
) -> tuple[tuple[InteractionGroupSpec, ...], tuple[InteractionGroupSpec, ...]]:
    required = (
        *_native_mask_groups(INTERACTION_GOLD, required_gold_mask),
        *_native_mask_groups(INTERACTION_EXIT_SWITCH, required_exit_mask),
        *_native_mask_groups(
            INTERACTION_LOCKED_DOOR, required_locked_door_mask
        ),
    )
    avoided = _native_mask_groups(
        INTERACTION_TRAPDOOR, forbidden_trapdoor_mask
    )
    return required, avoided


def _native_repair_search(
    level: Level,
    replay: Sequence[InputFrame],
    *,
    mutable_frames: tuple[int, ...],
    choices: tuple[tuple[InputFrame, ...], ...],
    target_tick: int,
    reference_point: CompactTracePoint | None,
    required_jump_frames: tuple[int, ...] = (),
    ignored_jump_frames: tuple[int, ...] = (),
    required_jump_any: bool = False,
    minimum_jump_events: int = 0,
    required_gold_mask: int = 0,
    required_exit_mask: int = 0,
    required_locked_door_mask: int = 0,
    forbidden_trapdoor_mask: int = 0,
    incumbent_score: float = float("inf"),
    incumbent_feasible: bool = False,
    prune_inactive_jump: bool = False,
    skip_unchanged_final_step: bool = False,
    randomized_ties: bool = False,
    max_simulated_ticks: int = 0,
) -> SearchResult:
    required_groups, avoided_groups = _native_repair_groups(
        required_gold_mask=required_gold_mask,
        required_exit_mask=required_exit_mask,
        required_locked_door_mask=required_locked_door_mask,
        forbidden_trapdoor_mask=forbidden_trapdoor_mask,
    )
    return _native_session(level).search(
        replay,
        SearchSpec(
            mutable_frames=mutable_frames,
            choices=choices,
            target_frame=target_tick,
            objective=(
                OBJECTIVE_TRACE_DISTANCE
                if reference_point is not None
                else OBJECTIVE_CONSTANT
            ),
            trace_target=(
                _native_trace_target(reference_point)
                if reference_point is not None
                else None
            ),
            required_groups=required_groups,
            avoided_groups=avoided_groups,
            incumbent_missing_requirements=(
                frozenset()
                if incumbent_feasible
                else frozenset(range(len(required_groups)))
            ),
            incumbent_violated_avoidances=(
                frozenset()
                if incumbent_feasible
                else frozenset(range(len(avoided_groups)))
            ),
            required_jump_frames=required_jump_frames,
            incumbent_missing_jump_frames=(
                frozenset()
                if incumbent_feasible
                else frozenset(required_jump_frames)
            ),
            ignored_jump_frames=ignored_jump_frames,
            minimum_jump_events=minimum_jump_events,
            incumbent_score=(
                -incumbent_score if math.isfinite(incumbent_score) else -math.inf
            ),
            incumbent_feasible=incumbent_feasible,
            prune_inactive_jump=prune_inactive_jump,
            skip_unchanged_final_step=skip_unchanged_final_step,
            require_all_constraints=True,
            required_jump_any=required_jump_any,
            tie_break_low_edit_lex=randomized_ties,
            max_simulated_ticks=max_simulated_ticks,
        ),
    )


def _native_repair_score(result: SearchResult) -> float:
    return -result.score if result.improved and result.feasible else math.inf


def _native_apply_search_result(
    replay: Sequence[InputFrame],
    mutable_frames: Sequence[int],
    result: SearchResult,
) -> tuple[InputFrame, ...] | None:
    """Materialise the policy-level replay selected by a native kernel."""
    if not result.improved or not result.feasible:
        return None
    if len(result.best_inputs) != len(mutable_frames):
        raise RuntimeError("native repair kernel returned an invalid input count")
    proposal = list(replay)
    for tick, frame in zip(mutable_frames, result.best_inputs):
        proposal[tick] = frame
    return tuple(proposal)


def _native_remaining_budget(config: AutoConfig, used: int) -> int:
    if config.repair_local_limit == 0:
        return 0
    return max(0, config.repair_local_limit - used)



def _native_patch_evaluation(
    level: Level,
    replay: Sequence[InputFrame],
    patches: tuple[tuple[PatchAssignmentSpec, ...], ...],
    *,
    target_tick: int,
    reference_point: CompactTracePoint | None,
    required_jump_frames: tuple[int, ...] = (),
    ignored_jump_frames: tuple[int, ...] = (),
    required_jump_any: bool = False,
    minimum_jump_events: int = 0,
    required_gold_mask: int = 0,
    required_exit_mask: int = 0,
    required_locked_door_mask: int = 0,
    forbidden_trapdoor_mask: int = 0,
    prune_inactive_jump: bool = False,
    randomized_ties: bool = False,
    max_simulated_ticks: int = 0,
    capture_endpoints: bool = False,
):
    """Compile an ordered Python patch batch and execute it natively."""
    required_groups, avoided_groups = _native_repair_groups(
        required_gold_mask=required_gold_mask,
        required_exit_mask=required_exit_mask,
        required_locked_door_mask=required_locked_door_mask,
        forbidden_trapdoor_mask=forbidden_trapdoor_mask,
    )
    return _native_session(level).evaluate_patches(
        replay,
        PatchEvaluationSpec(
            patches=patches,
            target_frame=target_tick,
            trace_target=(
                _native_trace_target(reference_point)
                if reference_point is not None
                else None
            ),
            required_groups=required_groups,
            avoided_groups=avoided_groups,
            required_jump_frames=required_jump_frames,
            ignored_jump_frames=ignored_jump_frames,
            minimum_jump_events=minimum_jump_events,
            required_jump_any=required_jump_any,
            prune_inactive_jump=prune_inactive_jump,
            tie_policy=(
                PATCH_TIE_LOW_EDIT_LEX
                if randomized_ties
                else PATCH_TIE_SUPPLIED_ORDER
            ),
            max_simulated_ticks=max_simulated_ticks,
            capture_endpoints=capture_endpoints,
        ),
    )


def _repair_evaluation_score(
    evaluation: AutoEvaluation,
    target_tick: int,
    reference_point: CompactTracePoint | None,
    *,
    required_jump_frames: frozenset[int] = frozenset(),
    ignored_jump_frames: frozenset[int] = frozenset(),
    minimum_jump_events: int = 0,
    required_gold_mask: int = 0,
    required_exit_mask: int = 0,
    required_locked_door_mask: int = 0,
    forbidden_trapdoor_mask: int = 0,
) -> float:
    point = evaluation.point(target_tick)
    if point is None or point.dead:
        return math.inf
    if point.collected_gold_mask & required_gold_mask != required_gold_mask:
        return math.inf
    if point.open_exit_mask & required_exit_mask != required_exit_mask:
        return math.inf
    if (
        point.opened_locked_door_mask & required_locked_door_mask
        != required_locked_door_mask
    ):
        return math.inf
    if point.triggered_trapdoor_mask & forbidden_trapdoor_mask:
        return math.inf
    if required_jump_frames and not any(
        tick in required_jump_frames and tick not in ignored_jump_frames
        for tick in evaluation.successful_jumps
        if tick <= target_tick
    ):
        return math.inf
    if point.jump_events < minimum_jump_events:
        return math.inf
    return 0.0 if reference_point is None else _trace_distance(
        point, reference_point
    )


def _native_endpoint_effect(
    player: dict[str, object] | None,
    base_point: CompactTracePoint | None,
) -> float:
    if player is None or base_point is None:
        return 0.0
    pos = player.get("pos")
    oldpos = player.get("oldpos")
    wall_n = player.get("wall_n")
    floor_n = player.get("floor_n")
    if not all(
        isinstance(value, (tuple, list)) and len(value) == 2
        for value in (pos, oldpos, wall_n, floor_n)
    ):
        return 0.0
    assert isinstance(pos, (tuple, list))
    assert isinstance(oldpos, (tuple, list))
    assert isinstance(wall_n, (tuple, list))
    assert isinstance(floor_n, (tuple, list))
    x = float(pos[0])
    y = float(pos[1])
    vx = x - float(oldpos[0])
    vy = y - float(oldpos[1])
    contact_key = (
        int(player.get("state", -1)),
        bool(player.get("in_air", False)),
        bool(player.get("near_wall", False)),
        _sign_bin(float(wall_n[0])),
        _sign_bin(float(floor_n[0])),
        _sign_bin(float(floor_n[1])),
        bool(player.get("previous_jump_held", False)),
    )
    contact_effect = 100.0 if contact_key != base_point.contact_key else 0.0
    return (
        (x - base_point.x) ** 2
        + (y - base_point.y) ** 2
        + 4.0 * ((vx - base_point.vx) ** 2 + (vy - base_point.vy) ** 2)
        + contact_effect
    )


def _repair_proposal_is_better(
    original: Sequence[InputFrame],
    proposal: Sequence[InputFrame],
    score: float,
    incumbent: Sequence[InputFrame],
    incumbent_score: float,
    *,
    randomized: bool,
) -> bool:
    """Compare local candidates, adding stable low-edit ties in random mode."""
    if score < incumbent_score:
        return True
    if (
        not randomized
        or score != incumbent_score
        or not math.isfinite(score)
    ):
        return False

    def edit_count(frames: Sequence[InputFrame]) -> int:
        return sum(
            (left.left, left.right, left.jump)
            != (right.left, right.right, right.jump)
            for left, right in zip(original, frames)
        )

    proposal_edits = edit_count(proposal)
    incumbent_edits = edit_count(incumbent)
    if proposal_edits != incumbent_edits:
        return proposal_edits < incumbent_edits
    return _frame_key(proposal) < _frame_key(incumbent)


def _jump_repair_variants(
    working_frames: Sequence[InputFrame],
    *,
    failure_tick: int,
    config: AutoConfig,
) -> tuple[tuple[tuple[InputFrame, ...], int, str], ...]:
    """Return legal +/-1 jump-boundary edits in the configured repair lookback.

    A pulse's start boundary is eligible for a +/-1 start shift when that
    boundary lies in the lookback.  Its hold-end boundary (the final held
    frame) is eligible for a +/-1 length change under the same rule.  The
    actual changed frame may sit one tick outside the lookback because that is
    the natural effect of moving a boundary by one; every changed frame must
    still stay inside ``--range``.

    Variants are deterministic and causally biased: boundaries nearest the
    failure are tried first, start edits precede length edits on an exact tie,
    and -1 precedes +1.  Duplicate packed inputs are removed.
    """
    body_limit = len(working_frames) - 1
    if body_limit <= 0 or failure_tick < 0:
        return ()
    failure_tick = min(failure_tick, body_limit - 1)
    range_end = min(
        body_limit - 1,
        body_limit - 1 if config.range_end is None else config.range_end,
    )
    look_start = max(config.range_start, failure_tick - config.repair_lookback)
    look_end = min(failure_tick, range_end)
    if look_start > look_end:
        return ()

    body = _editable_tuple(working_frames[:-1])
    pulses = _jump_pulses(body)
    # (distance from failure, kind order, pulse index, boundary, mutation kind)
    sites: list[tuple[int, int, int, int, str]] = []
    for pulse_index, (start, end) in enumerate(pulses):
        if config.max_jump_shift >= 1 and look_start <= start <= look_end:
            sites.append((failure_tick - start, 0, pulse_index, start, "start"))
        if config.max_jump_hold_delta >= 1 and look_start <= end <= look_end:
            sites.append((failure_tick - end, 1, pulse_index, end, "length"))
    sites.sort()

    result: list[tuple[tuple[InputFrame, ...], int, str]] = []
    seen_changes: set[tuple[tuple[int, bool], ...]] = set()
    for _distance, _kind_order, pulse_index, _boundary, kind in sites:
        start, end = pulses[pulse_index]
        old_length = end - start + 1
        for delta in (-1, 1):
            try:
                if kind == "start":
                    new_start = start + delta
                    new_end = end + delta
                    changed = _mutate_jump_pulse_known(
                        body,
                        pulses,
                        pulse_index,
                        start_delta=delta,
                    )
                    description = (
                        f"jump pulse {pulse_index} start {delta:+d} "
                        f"({start}->{start + delta})"
                    )
                else:
                    new_start = start
                    new_end = end + delta
                    changed = _mutate_jump_pulse_known(
                        body,
                        pulses,
                        pulse_index,
                        hold_delta=delta,
                    )
                    description = (
                        f"jump pulse {pulse_index} length {delta:+d} "
                        f"({old_length}->{old_length + delta})"
                    )
            except ValueError:
                continue
            changed_ticks = tuple(
                tick
                for tick in range(
                    min(start, new_start), max(end, new_end) + 1
                )
                if (start <= tick <= end) != (new_start <= tick <= new_end)
            )
            if not changed_ticks:
                continue
            if (
                changed_ticks[0] < config.range_start
                or changed_ticks[-1] > range_end
            ):
                continue
            change_key = tuple(
                (tick, changed[tick].jump) for tick in changed_ticks
            )
            if change_key in seen_changes:
                continue
            seen_changes.add(change_key)
            result.append((changed, changed_ticks[0], description))
    return tuple(result)


def repair_jump_mutation_lookback(
    level: Level,
    working_frames: Sequence[InputFrame],
    baseline: AutoEvaluation,
    *,
    failure_tick: int,
    reference_offset: int,
    config: AutoConfig,
    progress: RepairProgressCallback | None = None,
    required_gold_mask: int = 0,
    required_exit_mask: int = 0,
    required_locked_door_mask: int = 0,
    forbidden_trapdoor_mask: int = 0,
    require_failure_jump: bool = True,
) -> tuple[tuple[InputFrame, ...] | None, int, int]:
    """Evaluate policy-selected jump-boundary patches in native C."""
    if failure_tick < 0:
        return None, 0, 0
    seed = tuple(working_frames)
    body_limit = len(seed) - 1
    if body_limit <= 0:
        return None, 0, 0
    failure_tick = min(failure_tick, body_limit - 1)
    variants = _jump_repair_variants(
        seed,
        failure_tick=failure_tick,
        config=config,
    )
    if not variants:
        return None, 0, 0

    target_tick = min(body_limit, failure_tick + config.repair_lookahead)
    reference_tick = min(
        max(0, target_tick + reference_offset), baseline.last_tick
    )
    reference_point = baseline.point(reference_tick)
    required_jump = (
        failure_tick
        if require_failure_jump
        and seed[failure_tick].jump
        and (failure_tick == 0 or not seed[failure_tick - 1].jump)
        else None
    )
    seed_evaluation = _evaluate_working(
        level, seed, trace_stride=config.trace_stride
    )
    seed_successes = frozenset(
        tick
        for tick in seed_evaluation.successful_jumps
        if tick <= target_tick
    )
    base_score = _repair_evaluation_score(
        seed_evaluation,
        target_tick,
        reference_point,
        required_jump_frames=(
            frozenset((required_jump,))
            if required_jump is not None
            else frozenset()
        ),
        required_gold_mask=required_gold_mask,
        required_exit_mask=required_exit_mask,
        required_locked_door_mask=required_locked_door_mask,
        forbidden_trapdoor_mask=forbidden_trapdoor_mask,
    )
    if base_score == 0.0:
        if progress is not None:
            progress(0, 0)
        return None, 0, 0

    accepted_jump_frames = (
        tuple(
            range(
                max(0, required_jump - 1),
                min(target_tick, required_jump + 1) + 1,
            )
        )
        if required_jump is not None
        else ()
    )
    require_new_success = (
        required_jump is not None and required_jump not in seed_successes
    )
    ignored_jump_frames = (
        tuple(tick for tick in accepted_jump_frames if tick in seed_successes)
        if require_new_success
        else ()
    )
    target_seed_point = seed_evaluation.point(target_tick)
    minimum_jump_events = (
        (target_seed_point.jump_events if target_seed_point is not None else len(seed_successes))
        + 1
        if require_new_success
        else 0
    )

    best_work = seed
    best_score = base_score
    branches = 0
    simulations = 0
    randomized_ties = (
        config.repair_search_order == AUTO_REPAIR_SEARCH_ORDER_RANDOM
    )
    patches = tuple(
        tuple(
            PatchAssignmentSpec(tick, proposal[tick])
            for tick, (before, after) in enumerate(zip(seed, proposal))
            if before != after and tick <= target_tick
        )
        for proposal, _first_changed, _description in variants
    )
    batch = _native_patch_evaluation(
        level,
        seed,
        patches,
        target_tick=target_tick,
        reference_point=reference_point,
        required_jump_frames=accepted_jump_frames,
        ignored_jump_frames=ignored_jump_frames,
        required_jump_any=bool(accepted_jump_frames),
        minimum_jump_events=minimum_jump_events,
        required_gold_mask=required_gold_mask,
        required_exit_mask=required_exit_mask,
        required_locked_door_mask=required_locked_door_mask,
        forbidden_trapdoor_mask=forbidden_trapdoor_mask,
        randomized_ties=randomized_ties,
        max_simulated_ticks=config.repair_local_limit,
    )
    branches = batch.stats.branches
    simulations = batch.stats.simulated_ticks
    for (proposal, _first_changed, _description), candidate in zip(
        variants, batch.candidates
    ):
        score = candidate.score if candidate.feasible else math.inf
        if _repair_proposal_is_better(
            seed,
            proposal,
            score,
            best_work,
            best_score,
            randomized=randomized_ties,
        ):
            best_work = proposal
            best_score = score

    if progress is not None:
        progress(branches, simulations)
    return best_work if best_work != seed else None, branches, simulations


def repair_direction_window(
    level: Level,
    working_frames: Sequence[InputFrame],
    baseline: AutoEvaluation,
    *,
    failure_tick: int,
    reference_offset: int,
    config: AutoConfig,
    rng: random.Random | None = None,
    progress: RepairProgressCallback | None = None,
    required_gold_mask: int = 0,
    required_exit_mask: int = 0,
    required_locked_door_mask: int = 0,
    forbidden_trapdoor_mask: int = 0,
    require_failure_jump: bool = True,
) -> tuple[tuple[InputFrame, ...] | None, int, int]:
    """Choose horizontal probes in Python and execute them in native C."""
    if failure_tick < 0:
        return None, 0, 0
    search_rng = _effective_repair_search_rng(
        config,
        rng,
        stream_tag="direction-direct",
    )
    randomized = search_rng is not None
    seed = tuple(working_frames)
    body_limit = len(seed) - 1
    if body_limit <= 0:
        return None, 0, 0
    failure_tick = min(failure_tick, body_limit - 1)
    range_end = min(
        body_limit - 1,
        body_limit - 1 if config.range_end is None else config.range_end,
    )
    target_tick = min(body_limit, failure_tick + config.repair_lookahead)
    reference_tick = min(
        max(0, target_tick + reference_offset), baseline.last_tick
    )
    reference_point = baseline.point(reference_tick)
    required_jump = (
        failure_tick
        if require_failure_jump
        and seed[failure_tick].jump
        and (failure_tick == 0 or not seed[failure_tick - 1].jump)
        else None
    )
    required_jump_frames = (
        (required_jump,) if required_jump is not None else ()
    )
    seed_evaluation = _evaluate_working(
        level, seed, trace_stride=config.trace_stride
    )
    base_point = seed_evaluation.point(target_tick)
    base_score = _repair_evaluation_score(
        seed_evaluation,
        target_tick,
        reference_point,
        required_jump_frames=frozenset(required_jump_frames),
        required_gold_mask=required_gold_mask,
        required_exit_mask=required_exit_mask,
        required_locked_door_mask=required_locked_door_mask,
        forbidden_trapdoor_mask=forbidden_trapdoor_mask,
    )
    if base_score == 0.0:
        if progress is not None:
            progress(0, 0)
        return None, 0, 0

    branches = 0
    simulations = 0
    budget_exhausted = False
    look_start = max(config.range_start, failure_tick - config.repair_lookback)
    look_end = min(failure_tick, range_end)
    best_seed = seed
    best_seed_score = base_score

    probe_entries: list[tuple[int, tuple[InputFrame, ...]]] = []
    probe_patches: list[tuple[PatchAssignmentSpec, ...]] = []
    sensitivity_ticks = _repair_sensitivity_tick_order(
        look_start,
        look_end,
        failure_tick,
        search_rng,
    )
    for tick in sensitivity_ticks:
        old = seed[tick]
        for direction in _direction_search_order(
            old.horizontal,
            search_rng,
            source_first=False,
        ):
            frame = InputFrame(
                direction < 0, direction > 0, old.jump, None
            )
            changed = list(seed)
            changed[tick] = frame
            probe_entries.append((tick, tuple(changed)))
            probe_patches.append((PatchAssignmentSpec(tick, frame),))

    sensitivity_effects = {tick: 0.0 for tick in sensitivity_ticks}
    if probe_patches:
        probe_batch = _native_patch_evaluation(
            level,
            seed,
            tuple(probe_patches),
            target_tick=target_tick,
            reference_point=reference_point,
            required_jump_frames=required_jump_frames,
            required_gold_mask=required_gold_mask,
            required_exit_mask=required_exit_mask,
            required_locked_door_mask=required_locked_door_mask,
            forbidden_trapdoor_mask=forbidden_trapdoor_mask,
            randomized_ties=randomized,
            max_simulated_ticks=config.repair_local_limit,
            capture_endpoints=True,
        )
        branches += probe_batch.stats.branches
        simulations += probe_batch.stats.simulated_ticks
        budget_exhausted = probe_batch.budget_exhausted
        for (tick, proposal), candidate in zip(
            probe_entries, probe_batch.candidates
        ):
            sensitivity_effects[tick] = max(
                sensitivity_effects[tick],
                _native_endpoint_effect(candidate.player, base_point),
            )
            score = candidate.score if candidate.feasible else math.inf
            if _repair_proposal_is_better(
                seed,
                proposal,
                score,
                best_seed,
                best_seed_score,
                randomized=randomized,
            ):
                best_seed = proposal
                best_seed_score = score
    sensitivity = [
        (sensitivity_effects[tick], tick) for tick in sensitivity_ticks
    ]

    if base_point is None:
        candidate_ticks: list[int] = []
    elif search_rng is None:
        candidate_ticks = sorted(
            tick
            for _, tick in sorted(
                sensitivity, key=lambda item: (-item[0], item[1])
            )[:24]
        )
    else:
        sensitivity_ties = {
            tick: search_rng.getrandbits(64) for _, tick in sensitivity
        }
        candidate_ticks = sorted(
            tick
            for _, tick in sorted(
                sensitivity,
                key=lambda item: (
                    -item[0],
                    sensitivity_ties[item[1]],
                    item[1],
                ),
            )[:24]
        )
    sensitivity_score = {tick: effect for effect, tick in sensitivity}
    if search_rng is None:
        ranked_pairs = sorted(
            (
                (
                    -(sensitivity_score[first] + sensitivity_score[second]),
                    first,
                    second,
                )
                for position, first in enumerate(candidate_ticks[:-1])
                for second in candidate_ticks[position + 1 :]
            )
        )
        pair_sites = [(first, second) for _, first, second in ranked_pairs]
    else:
        ranked_pairs_random = sorted(
            (
                (
                    -(sensitivity_score[first] + sensitivity_score[second]),
                    search_rng.getrandbits(64),
                    first,
                    second,
                )
                for position, first in enumerate(candidate_ticks[:-1])
                for second in candidate_ticks[position + 1 :]
            )
        )
        pair_sites = [
            (first, second)
            for _, _, first, second in ranked_pairs_random
        ]

    exact_pair = False
    for first, second in pair_sites:
        if budget_exhausted:
            break
        pair_entries: list[tuple[InputFrame, ...]] = []
        pair_patches: list[tuple[PatchAssignmentSpec, ...]] = []
        for first_direction, second_direction in _pair_direction_search_order(
            seed[first].horizontal,
            seed[second].horizontal,
            search_rng,
        ):
            changed = list(seed)
            first_frame = InputFrame(
                first_direction < 0,
                first_direction > 0,
                seed[first].jump,
                None,
            )
            second_frame = InputFrame(
                second_direction < 0,
                second_direction > 0,
                seed[second].jump,
                None,
            )
            changed[first] = first_frame
            changed[second] = second_frame
            assignments = tuple(
                PatchAssignmentSpec(tick, frame)
                for tick, frame in (
                    (first, first_frame),
                    (second, second_frame),
                )
                if frame != seed[tick]
            )
            if not assignments:
                continue
            pair_entries.append(tuple(changed))
            pair_patches.append(assignments)
        pair_batch = _native_patch_evaluation(
            level,
            seed,
            tuple(pair_patches),
            target_tick=target_tick,
            reference_point=reference_point,
            required_jump_frames=required_jump_frames,
            required_gold_mask=required_gold_mask,
            required_exit_mask=required_exit_mask,
            required_locked_door_mask=required_locked_door_mask,
            forbidden_trapdoor_mask=forbidden_trapdoor_mask,
            randomized_ties=randomized,
            max_simulated_ticks=_native_remaining_budget(config, simulations),
        )
        branches += pair_batch.stats.branches
        simulations += pair_batch.stats.simulated_ticks
        budget_exhausted = pair_batch.budget_exhausted
        for proposal, candidate in zip(
            pair_entries, pair_batch.candidates
        ):
            score = candidate.score if candidate.feasible else math.inf
            if _repair_proposal_is_better(
                seed,
                proposal,
                score,
                best_seed,
                best_seed_score,
                randomized=randomized,
            ):
                best_seed = proposal
                best_seed_score = score
            if score <= 1e-18:
                exact_pair = True
                break
        if exact_pair:
            break

    nominal_start = max(0, failure_tick - config.repair_window + 1)
    window_start = min(max(nominal_start, config.range_start), range_end)
    window_end = min(failure_tick, window_start + config.repair_window - 1)
    if window_start <= window_end and not budget_exhausted:
        mutable_frames = tuple(range(window_start, window_end + 1))
        choices = tuple(
            tuple(
                InputFrame(
                    direction < 0,
                    direction > 0,
                    best_seed[tick].jump,
                    None,
                )
                for direction in _direction_search_order(
                    best_seed[tick].horizontal,
                    search_rng,
                    source_first=True,
                )
            )
            for tick in mutable_frames
        )
        result = _native_repair_search(
            level,
            best_seed,
            mutable_frames=mutable_frames,
            choices=choices,
            target_tick=target_tick,
            reference_point=reference_point,
            required_jump_frames=required_jump_frames,
            required_gold_mask=required_gold_mask,
            required_exit_mask=required_exit_mask,
            required_locked_door_mask=required_locked_door_mask,
            forbidden_trapdoor_mask=forbidden_trapdoor_mask,
            incumbent_score=best_seed_score,
            incumbent_feasible=math.isfinite(best_seed_score),
            randomized_ties=randomized,
            max_simulated_ticks=_native_remaining_budget(config, simulations),
        )
        branches += result.stats.visited_nodes
        simulations += result.stats.simulated_ticks
        proposal = _native_apply_search_result(
            best_seed, mutable_frames, result
        )
        if proposal is not None:
            score = _native_repair_score(result)
            if _repair_proposal_is_better(
                seed,
                proposal,
                score,
                best_seed,
                best_seed_score,
                randomized=randomized,
            ):
                best_seed = proposal
                best_seed_score = score

    if progress is not None:
        progress(branches, simulations)
    return best_seed if best_seed != seed else None, branches, simulations

def repair_all_input_window(
    level: Level,
    working_frames: Sequence[InputFrame],
    baseline: AutoEvaluation,
    *,
    seed_evaluation: AutoEvaluation | None = None,
    failure_tick: int,
    reference_offset: int,
    config: AutoConfig,
    rng: random.Random | None = None,
    progress: RepairProgressCallback | None = None,
    required_gold_mask: int = 0,
    required_exit_mask: int = 0,
    required_locked_door_mask: int = 0,
    forbidden_trapdoor_mask: int = 0,
    require_failure_jump: bool = True,
) -> tuple[tuple[InputFrame, ...] | None, int, int]:
    """Search the six held-input choices with the generic native DFS."""
    if failure_tick < 0:
        return None, 0, 0
    search_rng = _effective_repair_search_rng(
        config,
        rng,
        stream_tag="all-input-direct",
    )
    randomized = search_rng is not None
    seed = tuple(working_frames)
    body_limit = len(seed) - 1
    if body_limit <= 0:
        return None, 0, 0
    failure_tick = min(failure_tick, body_limit - 1)
    range_end = min(
        body_limit - 1,
        body_limit - 1 if config.range_end is None else config.range_end,
    )
    target_tick = min(body_limit, failure_tick + config.repair_lookahead)
    reference_tick = min(
        max(0, target_tick + reference_offset), baseline.last_tick
    )
    reference_point = baseline.point(reference_tick)
    required_jump = (
        failure_tick
        if require_failure_jump
        and seed[failure_tick].jump
        and (failure_tick == 0 or not seed[failure_tick - 1].jump)
        else None
    )
    if seed_evaluation is None:
        seed_evaluation = _evaluate_working(
            level, seed, trace_stride=config.trace_stride
        )
    seed_successes = frozenset(
        tick
        for tick in seed_evaluation.successful_jumps
        if tick <= target_tick
    )
    width = min(4, config.repair_window)
    nominal_start = max(0, failure_tick - width + 1)
    window_start = min(max(nominal_start, config.range_start), range_end)
    window_end = min(failure_tick, window_start + width - 1)
    if window_start > window_end:
        return None, 0, 0

    jump_tolerance = max(1, config.max_jump_shift)
    required_jump_frames = (
        tuple(
            range(
                max(0, required_jump - jump_tolerance),
                min(target_tick, required_jump + jump_tolerance) + 1,
            )
        )
        if required_jump is not None
        else ()
    )
    ignored_jump_frames = tuple(
        tick for tick in required_jump_frames if tick in seed_successes
    )
    target_seed_point = seed_evaluation.point(target_tick)
    minimum_jump_events = (
        (target_seed_point.jump_events if target_seed_point is not None else len(seed_successes))
        + 1
        if required_jump is not None
        else 0
    )
    base_score = _repair_evaluation_score(
        seed_evaluation,
        target_tick,
        reference_point,
        required_jump_frames=frozenset(required_jump_frames),
        ignored_jump_frames=frozenset(ignored_jump_frames),
        minimum_jump_events=minimum_jump_events,
        required_gold_mask=required_gold_mask,
        required_exit_mask=required_exit_mask,
        required_locked_door_mask=required_locked_door_mask,
        forbidden_trapdoor_mask=forbidden_trapdoor_mask,
    )
    mutable_frames = tuple(range(window_start, window_end + 1))
    choices = tuple(
        tuple(
            InputFrame(direction < 0, direction > 0, jump, None)
            for direction, jump in _all_input_search_order(
                (seed[tick].horizontal, seed[tick].jump), search_rng
            )
        )
        for tick in mutable_frames
    )
    result = _native_repair_search(
        level,
        seed,
        mutable_frames=mutable_frames,
        choices=choices,
        target_tick=target_tick,
        reference_point=reference_point,
        required_jump_frames=required_jump_frames,
        ignored_jump_frames=ignored_jump_frames,
        required_jump_any=bool(required_jump_frames),
        minimum_jump_events=minimum_jump_events,
        required_gold_mask=required_gold_mask,
        required_exit_mask=required_exit_mask,
        required_locked_door_mask=required_locked_door_mask,
        forbidden_trapdoor_mask=forbidden_trapdoor_mask,
        incumbent_score=base_score,
        incumbent_feasible=math.isfinite(base_score),
        prune_inactive_jump=True,
        randomized_ties=randomized,
        max_simulated_ticks=config.repair_local_limit,
    )
    branches = result.stats.visited_nodes
    simulations = result.stats.simulated_ticks
    if progress is not None:
        progress(branches, simulations)
    proposal = _native_apply_search_result(seed, mutable_frames, result)
    return proposal, branches, simulations

def _candidate_key(
    candidate: AutoCandidate,
    baseline_tick: int,
    *,
    objective: str = AUTO_OBJECTIVE_SPEEDRUN,
    reference_gold_mask: int = 0,
) -> tuple:
    evaluation = candidate.evaluation
    if objective == AUTO_OBJECTIVE_SPEEDRUN:
        if candidate.output_valid:
            finish = (
                evaluation.finish_tick
                if evaluation.finish_tick is not None
                else baseline_tick + 1
            )
            return (0, finish, candidate.edit_count, candidate.generation)
        match = candidate.alignment
        progress = match.reference_tick if match is not None else evaluation.last_tick
        offset = match.offset if match is not None else 0
        distance = match.distance if match is not None else float("inf")
        return (
            1,
            -progress,
            -offset,
            distance,
            candidate.edit_count,
            candidate.generation,
        )

    if candidate.output_valid:
        value = auto_objective_value(evaluation, objective)
        assert value is not None
        finish = (
            evaluation.finish_tick
            if evaluation.finish_tick is not None
            else baseline_tick + 1
        )
        source_rank = 0 if candidate.origin == "source" else 1
        missing_reference_gold = (
            reference_gold_mask & ~evaluation.final_gold_mask
        ).bit_count()
        return (
            0,
            -value,
            source_rank,
            missing_reference_gold,
            candidate.edit_count,
            finish,
            candidate.generation,
        )
    match = candidate.alignment
    progress = match.reference_tick if match is not None else evaluation.last_tick
    score_lead = match.score_lead if match is not None else 0
    distance = match.distance if match is not None else float("inf")
    terminal = evaluation._terminal_summary()
    final_mask = int(terminal[6]) if terminal is not None else 0
    missing_reference_gold = (reference_gold_mask & ~final_mask).bit_count()
    return (
        1,
        0 if match is not None else 1,
        -score_lead,
        -progress,
        distance,
        missing_reference_gold,
        candidate.edit_count,
        candidate.generation,
    )


def _best_candidate_key(
    candidate: AutoCandidate,
    baseline_tick: int,
    *,
    objective: str = AUTO_OBJECTIVE_SPEEDRUN,
    reference_gold_mask: int = 0,
) -> tuple:
    """Rank the persisted/final winner without perturbing beam search order.

    The general candidate key intentionally remains unchanged because it also
    controls beam/frontier selection.  Exit proximity is confined to the
    incumbent that is checkpointed and ultimately returned: after finish time
    for speedruns, and after objective value for highscores.
    """
    if candidate.output_valid:
        evaluation = candidate.evaluation
        finish = (
            evaluation.finish_tick
            if evaluation.finish_tick is not None
            else baseline_tick + 1
        )
        proximity = evaluation.pre_finish_exit_distance
        if proximity is None or not math.isfinite(proximity):
            proximity = float("inf")

        if objective == AUTO_OBJECTIVE_SPEEDRUN:
            return (
                0,
                finish,
                proximity,
                candidate.edit_count,
                candidate.generation,
            )

        if objective == AUTO_OBJECTIVE_HIGHSCORE:
            value = auto_objective_value(evaluation, objective)
            assert value is not None
            source_rank = 0 if candidate.origin == "source" else 1
            missing_reference_gold = (
                reference_gold_mask & ~evaluation.final_gold_mask
            ).bit_count()
            return (
                0,
                -value,
                proximity,
                source_rank,
                missing_reference_gold,
                candidate.edit_count,
                finish,
                candidate.generation,
            )

    return _candidate_key(
        candidate,
        baseline_tick,
        objective=objective,
        reference_gold_mask=reference_gold_mask,
    )


def _diversity_bucket(candidate: AutoCandidate) -> tuple:
    terminal = candidate.evaluation._terminal_summary()
    transition_bucket = len(_candidate_input_transitions(candidate)) // 2
    if terminal is None:
        return (candidate.finish_tick, transition_bucket, None)
    return (
        candidate.finish_tick,
        transition_bucket,
        candidate.alignment.offset if candidate.alignment else 0,
        round(float(terminal[1]) / 6.0),
        round(float(terminal[2]) / 6.0),
        int(terminal[3]),
        tuple(int(value) for value in terminal[6:11]),
    )


def _candidate_replay_key(candidate: AutoCandidate) -> bytes:
    """Return the cached held-input identity for an admitted candidate."""
    if candidate.replay_key is not None:
        return candidate.replay_key
    return _frame_key(candidate.working_frames)


def _candidate_input_transitions(
    candidate: AutoCandidate,
) -> tuple[int, ...]:
    """Return cached transition seams, with a fallback for public fixtures."""
    if candidate.input_transitions is not None:
        return candidate.input_transitions
    return input_transition_frames(candidate.working_frames[:-1])


def _select_diverse_beam(
    candidates: Iterable[AutoCandidate],
    config: AutoConfig,
    baseline_tick: int,
    *,
    reference_gold_mask: int = 0,
) -> list[AutoCandidate]:
    ordered = sorted(
        candidates,
        key=lambda item: _candidate_key(
            item,
            baseline_tick,
            objective=config.objective,
            reference_gold_mask=reference_gold_mask,
        ),
    )
    result: list[AutoCandidate] = []
    selected_ids: set[int] = set()
    counts: dict[tuple, int] = {}

    def append_from(items: Iterable[AutoCandidate], limit: int) -> None:
        for candidate in items:
            if len(result) >= limit or len(result) >= config.beam_width:
                break
            identity = id(candidate)
            if identity in selected_ids:
                continue
            bucket = _diversity_bucket(candidate)
            if counts.get(bucket, 0) >= config.diversity_per_bucket:
                continue
            result.append(candidate)
            selected_ids.add(identity)
            counts[bucket] = counts.get(bucket, 0) + 1

    aligned_frontiers = [
        candidate
        for candidate in ordered
        if not candidate.output_valid and candidate.alignment is not None
    ]
    if config.beam_width > 1 and aligned_frontiers:
        frontier_slots = min(
            len(aligned_frontiers), max(1, config.beam_width // 4)
        )
        frontier_ids = {id(candidate) for candidate in aligned_frontiers}
        append_from(
            (candidate for candidate in ordered if id(candidate) not in frontier_ids),
            config.beam_width - frontier_slots,
        )
        append_from(aligned_frontiers, config.beam_width)
    append_from(ordered, config.beam_width)
    return result


def _count_edits(a: Sequence[InputFrame], b: Sequence[InputFrame]) -> int:
    return abs(len(a) - len(b)) + sum(
        (x.left, x.right, x.jump) != (y.left, y.right, y.jump)
        for x, y in zip(a, b)
    )


def _first_failure(
    evaluation: AutoEvaluation,
    shifted_misses: Sequence[int] = (),
    inherited_misses: Sequence[int] = (),
) -> int:
    """Return the earliest newly introduced missed edge or terminal failure."""
    inherited = set(inherited_misses)
    causal_ticks = [
        *shifted_misses,
        *(
            tick
            for tick in evaluation.missed_jump_edges
            if tick not in inherited
        ),
    ]
    if (
        evaluation.dead_tick is not None
        and evaluation.dead_tick != evaluation.finish_tick
    ):
        causal_ticks.append(evaluation.dead_tick)
    if causal_ticks:
        return min(causal_ticks)
    return max(0, evaluation.last_tick)


def _find_route_control_repair_target(
    candidate: AutoEvaluation,
    reference: AutoEvaluation,
    *,
    reference_offset: int = 0,
) -> RouteControlRepairTarget | None:
    """Find the first control divergence which can explain a failed route."""
    if candidate.completed:
        return None
    candidate_analysis = _native_trace_analysis(candidate)
    reference_analysis = _native_trace_analysis(reference)
    if (
        candidate_analysis is not None
        and reference_analysis is not None
        and -(1 << 63) <= reference_offset <= (1 << 63) - 1
    ):
        raw_target = candidate_analysis.find_route_divergence(
            reference_analysis,
            reference_offset=reference_offset,
            reference_completion_exit_index=(
                -1
                if reference.completed_exit_index is None
                else reference.completed_exit_index
            ),
        )
        if raw_target is None:
            return None
        return RouteControlRepairTarget(
            candidate_tick=int(raw_target[0]),
            reference_tick=int(raw_target[1]),
            required_exit_mask=int(raw_target[2]),
            required_locked_door_mask=int(raw_target[3]),
            forbidden_trapdoor_mask=int(raw_target[4]),
        )
    completion_bit = (
        0
        if reference.completed_exit_index is None
        else 1 << reference.completed_exit_index
    )
    for point in candidate.trace:
        reference_tick = point.tick + reference_offset
        reference_point = reference.point(reference_tick)
        if reference_point is None:
            continue
        required_exit_mask = (
            completion_bit
            if completion_bit
            and reference_point.open_exit_mask & completion_bit
            and not point.open_exit_mask & completion_bit
            else 0
        )
        required_locked_door_mask = (
            reference_point.opened_locked_door_mask
            & ~point.opened_locked_door_mask
        )
        forbidden_trapdoor_mask = (
            point.triggered_trapdoor_mask
            & ~reference_point.triggered_trapdoor_mask
        )
        if (
            required_exit_mask
            or required_locked_door_mask
            or forbidden_trapdoor_mask
        ):
            return RouteControlRepairTarget(
                candidate_tick=point.tick,
                reference_tick=reference_tick,
                required_exit_mask=required_exit_mask,
                required_locked_door_mask=required_locked_door_mask,
                forbidden_trapdoor_mask=forbidden_trapdoor_mask,
            )
    return None


def _semantic_jump_variants(
    working: Sequence[InputFrame],
    config: AutoConfig,
    *,
    limit: int | None = None,
) -> tuple[tuple[tuple[InputFrame, ...], str], ...]:
    """Systematic pulse variants, including source-semantic 30-frame holds.

    Build and rank cheap mutation descriptors first, then materialise only the
    proposals the remaining macro budget can consume.  Long structured routes
    can expose hundreds of variants, while a small Auto run may evaluate fewer
    than ten of them.
    """
    if limit is not None and limit < 0:
        raise ValueError("semantic jump variant limit must be non-negative")
    if limit == 0:
        return ()
    body = _editable_tuple(working[:-1])
    pulses = _jump_pulses(body)
    descriptors: list[tuple[str, int, tuple[int, ...]]] = []
    for pulse_index, (start, end) in enumerate(pulses):
        length = end - start + 1
        lengths = {length + d for d in range(-config.max_jump_hold_delta, config.max_jump_hold_delta + 1) if d}
        # max_jump_time is 30 and the trigger frame counts as the first held
        # frame, so 31 is a high-value semantic release boundary.  The supplied
        # improvements use it both to truncate an 84-frame hold and to extend a
        # 19-frame hold, so propose it in both directions whenever legal.
        if length != 31:
            lengths.add(31)
        for new_length in sorted(lengths):
            if new_length < 1:
                continue
            descriptors.append(
                (
                    f"jump pulse {pulse_index} length {length}->{new_length}",
                    0,
                    (pulse_index, new_length),
                )
            )
        for shift in range(-config.max_jump_shift, config.max_jump_shift + 1):
            if shift == 0:
                continue
            # Search both a pure shift and a shift with the old end held fixed.
            # The latter (start +1, hold -1) is a common landing repair and is
            # the only legal move when a following pulse is immediately adjacent.
            for hold_delta in (0, -shift):
                suffix = "" if hold_delta == 0 else f" hold {hold_delta:+d}"
                descriptors.append(
                    (
                        f"jump pulse {pulse_index} shift {shift:+d}{suffix}",
                        1,
                        (pulse_index, shift, hold_delta),
                    )
                )
        # Pulse removal is a first-class semantic edit, not a long sequence of
        # one-frame mutations. The supplied 00-1 improvement deletes a late
        # pulse, and integrated v2.8 could express that directly.
        descriptors.append(
            (
                f"jump pulse {pulse_index} delete {start}+{length}",
                2,
                (start, length),
            )
        )

    def priority(description: str) -> tuple[int, str]:
        # Moving a pulse start while holding its end fixed is the highest-value
        # coordinated edit and should get its deterministic repair/retime chain
        # before a small macro budget is spent on less structured variants.
        if "shift +1 hold -1" in description:
            return (0, description)
        if " shift " in description and " hold " in description:
            return (1, description)
        if description.endswith("->31"):
            return (2, description)
        if " delete " in description:
            return (3, description)
        return (4, description)

    descriptors.sort(key=lambda item: priority(item[0]))
    result: list[tuple[tuple[InputFrame, ...], str]] = []
    seen: set[tuple[InputFrame, ...]] = set()
    for description, operation, values in descriptors:
        try:
            if operation == 0:
                pulse_index, new_length = values
                changed = _mutate_jump_pulse_known(
                    body,
                    pulses,
                    pulse_index,
                    hold_length=new_length,
                )
            elif operation == 1:
                pulse_index, shift, hold_delta = values
                changed = _mutate_jump_pulse_known(
                    body,
                    pulses,
                    pulse_index,
                    start_delta=shift,
                    hold_delta=hold_delta,
                )
            else:
                start, length = values
                changed = _mutate_jump_interval_known(
                    body, start, length, held=False
                )
        except ValueError:
            continue
        if changed in seen:
            continue
        seen.add(changed)
        result.append((changed, description))
        if limit is not None and len(result) >= limit:
            break
    return tuple(result)


@dataclass(frozen=True, slots=True)
class _PreparedAutoSearch:
    """Validated baseline and immutable inputs for one autonomous search."""

    source_body: tuple[InputFrame, ...]
    baseline_eval: AutoEvaluation
    baseline_tick: int
    baseline_objective_value: int
    search_config: AutoConfig
    extra_ticks: int
    workspace_body_length: int
    source_working: tuple[InputFrame, ...]
    range_end: int
    baseline: AutoCandidate
    diagnostics: tuple[str, ...]


def _prepare_autonomous_search(
    level: Level,
    source_frames: Sequence[InputFrame],
    config: AutoConfig,
    progress: ProgressCallback | None,
) -> _PreparedAutoSearch | AutoResult:
    """Verify the source and build the immutable plan used by the search."""
    if progress is not None:
        progress(
            AutoProgress(
                phase="baseline",
                macro_evaluations=0,
                budget=config.iterations,
                best_finish_tick=None,
                message="verifying source replay...",
                objective=config.objective,
            )
        )
    source_body = _editable_tuple(source_frames)
    source_serialized_working = source_body + (NEUTRAL_INPUT,)
    baseline_eval = _evaluate_working(
        level,
        source_serialized_working,
        trace_stride=config.trace_stride,
    )
    if not baseline_eval.valid or baseline_eval.finish_tick is None:
        reason = (
            "unsupported collision"
            if baseline_eval.unsupported
            else "death"
            if baseline_eval.dead_tick is not None
            else "no exit completion"
        )
        raise ValueError(f"source replay is not a valid completed route ({reason})")
    baseline_tick = baseline_eval.finish_tick
    # A supplied body may contain unused trailing inputs. Trim it immediately and
    # independently verify the canonical body whose completion is its sentinel.
    if baseline_tick < len(source_body):
        source_body = source_body[:baseline_tick]
        source_serialized_working = source_body + (NEUTRAL_INPUT,)
        baseline_eval = _evaluate_working(
            level,
            source_serialized_working,
            trace_stride=config.trace_stride,
        )
        if not baseline_eval.valid or baseline_eval.finish_tick != len(source_body):
            raise ValueError(
                "source completion cannot be represented by its neutral sentinel"
            )
        baseline_tick = baseline_eval.finish_tick
    assert baseline_tick is not None
    baseline_objective_value = auto_objective_value(
        baseline_eval, config.objective
    )
    assert baseline_objective_value is not None

    # With no gold in the level, highscore is exactly the speedrun objective.
    # Use the byte-for-byte v2.9 search schedule in that case rather than paying
    # for an irrelevant extended workspace or changing seeded proposal order.
    search_config = config
    if (
        config.objective == AUTO_OBJECTIVE_HIGHSCORE
        and level.static_world.gold_count == 0
        and config.max_extra_ticks is None
    ):
        search_config = replace(
            config,
            objective=AUTO_OBJECTIVE_SPEEDRUN,
            require_reference_gold=False,
            max_extra_ticks=0,
        )

    extra_ticks = search_config.effective_max_extra_ticks
    if (
        config.objective == AUTO_OBJECTIVE_HIGHSCORE
        and config.max_extra_ticks is None
    ):
        uncollected_gold = max(
            0,
            level.static_world.gold_count - baseline_eval.gold_count,
        )
        extra_ticks = min(
            extra_ticks,
            uncollected_gold * GOLD_BONUS_TICKS,
        )
    workspace_body_length = baseline_tick + extra_ticks
    source_search_body = source_body + (NEUTRAL_INPUT,) * extra_ticks
    source_working = source_search_body + (NEUTRAL_INPUT,)

    if progress is not None:
        progress(
            AutoProgress(
                phase="baseline",
                macro_evaluations=0,
                budget=config.iterations,
                best_finish_tick=baseline_tick,
                message=(
                    f"source verified at finish tick {baseline_tick}; "
                    "building autonomous search plan"
                ),
                objective=config.objective,
                best_objective_value=baseline_objective_value,
                best_gold_bonus_ticks=baseline_eval.gold_bonus_ticks,
                best_gold_count=baseline_eval.gold_count,
                best_exit_edge_distance=pre_finish_exit_edge_distance(
                    level, baseline_eval
                ),
            )
        )
    if workspace_body_length == 0:
        baseline = AutoCandidate(
            working_frames=source_working,
            evaluation=baseline_eval,
            origin="source",
            generation=0,
            edit_count=0,
        )
        diagnostics = (
            "source verified at finish tick 0 using neutral sentinel 0",
            "source already completes at tick 0; no editable inputs exist",
            "final replay independently verified: 0->0; 0 differing input frames",
        )
        if progress is not None:
            progress(
                AutoProgress(
                    phase="complete",
                    macro_evaluations=0,
                    budget=config.iterations,
                    best_finish_tick=0,
                    message=diagnostics[1],
                    objective=config.objective,
                    best_objective_value=baseline_objective_value,
                    best_gold_bonus_ticks=baseline_eval.gold_bonus_ticks,
                    best_gold_count=baseline_eval.gold_count,
                    best_exit_edge_distance=pre_finish_exit_edge_distance(
                        level, baseline_eval
                    ),
                )
            )
        return AutoResult(
            frames=(),
            baseline_finish_tick=0,
            finish_tick=0,
            best=baseline,
            stats=AutoStats(),
            diagnostics=diagnostics,
            beam=(baseline,),
            objective=config.objective,
            baseline_gold_mask=baseline_eval.final_gold_mask,
            gold_mask=baseline_eval.final_gold_mask,
            baseline_gold_bonus_ticks=baseline_eval.gold_bonus_ticks,
            gold_bonus_ticks=baseline_eval.gold_bonus_ticks,
            baseline_objective_value=baseline_objective_value,
            objective_value=baseline_objective_value,
            require_reference_gold=config.require_reference_gold,
        )
    range_end = (
        workspace_body_length - 1
        if config.range_end is None
        else config.range_end
    )
    if (
        config.range_start >= workspace_body_length
        or range_end >= workspace_body_length
    ):
        range_label = (
            "verified replay body"
            if extra_ticks == 0
            else "highscore search workspace"
        )
        raise ValueError(
            f"auto mutation range must stay within the {range_label} "
            f"(last frame {workspace_body_length - 1})"
        )

    source_replay_key = _frame_key(source_working)
    baseline = AutoCandidate(
        working_frames=source_working,
        evaluation=baseline_eval,
        origin="source",
        generation=0,
        edit_count=0,
        replay_key=source_replay_key,
        input_transitions=input_transition_frames(source_working[:-1]),
    )
    diagnostics: list[str] = [
        (
            f"source verified at finish tick {baseline_tick} using neutral "
            f"sentinel {baseline_tick}"
        ),
        (
            f"auto objective {config.objective}: baseline value "
            f"{baseline_objective_value}; gold {baseline_eval.gold_count} "
            f"({baseline_eval.gold_bonus_ticks} bonus ticks)"
        ),
    ]
    if baseline_eval.route_control_events:
        diagnostics.append(
            "source route controls: "
            + ", ".join(event.label for event in baseline_eval.route_control_events)
        )
    if search_config.objective != config.objective:
        diagnostics.append(
            "level contains no gold; highscore uses the speedrun-equivalent "
            "search schedule"
        )
    if not config.deterministic_phase:
        diagnostics.append(
            "deterministic bootstrap disabled; starting with seeded beam work"
        )
    if config.repair_search_order == AUTO_REPAIR_SEARCH_ORDER_RANDOM:
        diagnostics.append(
            "local repair traversal random; independent direction/all-input "
            "streams and primary jump/direction order derived from Auto seed "
            f"{config.seed}"
        )
    else:
        diagnostics.append(
            "local repair traversal fixed; using v2.12.5-compatible branch order; "
            f"primary jump/direction order derived from Auto seed {config.seed}"
        )
    return _PreparedAutoSearch(
        source_body=source_body,
        baseline_eval=baseline_eval,
        baseline_tick=baseline_tick,
        baseline_objective_value=baseline_objective_value,
        search_config=search_config,
        extra_ticks=extra_ticks,
        workspace_body_length=workspace_body_length,
        source_working=source_working,
        range_end=range_end,
        baseline=baseline,
        diagnostics=tuple(diagnostics),
    )


class _AutonomousSearch:
    """Mutable state and phase orchestration for one autonomous search."""

    _PHASE_ACTIVITY = {
        "raw-retime": "testing high-value -1 suffix retimes",
        "raw-repair": "repairing promising raw retimes",
        "cheap-pulse": "horizontal one-frame sweep",
        "jump": "systematic jump-pulse variants",
        "pulse-repair": "repairing pulse mutation",
        "jump-retime": "testing -1 suffixes after jump variants",
        "deep-repair": "repairing shifted suffix frontier",
        "deferred-retime": "screening deferred +/-2 and +/-3 suffix retimes",
        "beam": "seeded beam search",
        "beam-repair": "repairing beam retime",
        "jump-repair": "repairing beam jump mutation",
        "boundary-repair": "repairing boundary retime",
        "pair-repair": "repairing horizontal sensitivity pair",
        "repair-campaign": "advancing a promising repair frontier",
        "gold-repair": "restoring missed reference gold",
        "splice": "splicing aligned reference suffix",
        "complete": "final replay verification",
    }

    def __init__(
        self,
        level: Level,
        config: AutoConfig,
        prepared: _PreparedAutoSearch,
        progress: ProgressCallback | None,
        best_callback: BestCallback | None,
    ) -> None:
        self.level = level
        self.config = config
        self.progress = progress
        self.best_callback = best_callback
        self.source_body = prepared.source_body
        self.baseline_eval = prepared.baseline_eval
        self.baseline_tick = prepared.baseline_tick
        self.baseline_objective_value = prepared.baseline_objective_value
        self.search_config = prepared.search_config
        self.extra_ticks = prepared.extra_ticks
        self.workspace_body_length = prepared.workspace_body_length
        self.source_working = prepared.source_working
        self.range_end = prepared.range_end
        self.baseline = prepared.baseline

        self.beam: list[AutoCandidate] = [self.baseline]
        self.finalists: list[AutoCandidate] = [self.baseline]
        self.best = self.baseline
        self.reference_working = self.source_working
        self.reference_eval = self.baseline_eval
        self.reference_tick = self.baseline_tick
        source_replay_key = _candidate_replay_key(self.baseline)
        self.seen: set[bytes] = {source_replay_key}
        self.diagnostics = list(prepared.diagnostics)
        self.rng = random.Random(config.seed)
        self.gold_repair_seen: set[tuple[bytes, int]] = set()
        self.counters = {
            "macro_candidates": 0,
            "macro_evaluations": 0,
            "local_branches": 0,
            "local_simulations": 0,
            "raw_retimes": 0,
            "boundary_retimes": 0,
            "suffix_splices": 0,
            "jump_mutations": 0,
            "pulse_mutations": 0,
            "direction_mutations": 0,
            "repair_attempts": 0,
            "jump_repair_attempts": 0,
            "all_input_repairs": 0,
            "successful_repairs": 0,
            "reference_epochs": 0,
            "deduplicated": 0,
            "gold_repair_attempts": 0,
            "successful_gold_repairs": 0,
            "route_control_repair_attempts": 0,
            "successful_route_control_repairs": 0,
            "structured_repair_attempts": 0,
            "beam_quick_repair_attempts": 0,
            "beam_strategic_repair_attempts": 0,
            "repair_campaigns": 0,
            "repair_campaign_attempts": 0,
            "repair_frontiers_queued": 0,
            "repair_frontiers_dropped": 0,
        }
        self.required_reference_gold_mask = self.baseline_eval.final_gold_mask
        self.repair_frontiers: list[_RepairFrontier] = []
        self.repair_frontier_keys: set[bytes] = set()
        self.last_frontier_dispatch = 0
        self.beam_phase_started = False

    def _budget_exhausted(self) -> bool:
        return self.counters["macro_evaluations"] >= self.config.iterations

    def _mutation_allowed(self, start: int) -> bool:
        return self.config.range_start <= start <= self.range_end

    def _record_repair_attempt(self, *, strategic: bool) -> None:
        """Classify an admitted repair without imposing a global token gate."""
        if self.beam_phase_started:
            key = (
                "beam_strategic_repair_attempts"
                if strategic
                else "beam_quick_repair_attempts"
            )
        else:
            key = "structured_repair_attempts"
        self.counters[key] += 1

    def _evaluation_value(self, evaluation: AutoEvaluation) -> int:
        value = auto_objective_value(evaluation, self.config.objective)
        if value is None:
            raise ValueError("objective value requested for an incomplete replay")
        return value

    def _candidate_key(
        self, candidate: AutoCandidate, tick: int | None = None
    ) -> tuple:
        return _candidate_key(
            candidate,
            self.baseline_tick if tick is None else tick,
            objective=self.search_config.objective,
            reference_gold_mask=self.required_reference_gold_mask,
        )

    def _best_candidate_key(
        self, candidate: AutoCandidate, tick: int | None = None
    ) -> tuple:
        return _best_candidate_key(
            candidate,
            self.baseline_tick if tick is None else tick,
            objective=self.search_config.objective,
            reference_gold_mask=self.required_reference_gold_mask,
        )

    def _no_worse_than_baseline(self, evaluation: AutoEvaluation) -> bool:
        return _objective_no_worse(
            evaluation,
            self.baseline_eval,
            self.search_config,
            required_gold_mask=self.required_reference_gold_mask,
        )

    def _better_than(
        self,
        candidate_evaluation: AutoEvaluation,
        incumbent_evaluation: AutoEvaluation,
    ) -> bool:
        return _objective_better(
            candidate_evaluation,
            incumbent_evaluation,
            self.search_config,
            required_gold_mask=self.required_reference_gold_mask,
        )

    def _equal_to_baseline(self, evaluation: AutoEvaluation) -> bool:
        return _objective_equal(
            evaluation,
            self.baseline_eval,
            self.search_config,
            required_gold_mask=self.required_reference_gold_mask,
        )

    def _has_strict_improvement(self) -> bool:
        return self._better_than(self.best.evaluation, self.baseline_eval)

    def _route_control_target(
        self,
        candidate: AutoCandidate,
        *,
        repair_reference: AutoEvaluation | None = None,
        reference_offset: int | None = None,
    ) -> RouteControlRepairTarget | None:
        target_reference = (
            self.reference_eval if repair_reference is None else repair_reference
        )
        if reference_offset is not None:
            offset = reference_offset
        elif candidate.alignment is not None:
            offset = candidate.alignment.offset
        else:
            offset = 0
        return _find_route_control_repair_target(
            candidate.evaluation,
            target_reference,
            reference_offset=offset,
        )

    def _emit(
        self,
        phase: str,
        message: str,
        *,
        local_simulations: int | None = None,
        repair_index: int = 0,
        campaign_index: int = 0,
    ) -> None:
        if self.progress is not None:
            self.progress(
                AutoProgress(
                    phase=phase,
                    macro_evaluations=self.counters["macro_evaluations"],
                    budget=self.config.iterations,
                    best_finish_tick=(
                        self.best.finish_tick
                        if self.best.finish_tick is not None
                        else self.baseline_tick
                    ),
                    message=message,
                    local_simulations=(
                        self.counters["local_simulations"]
                        if local_simulations is None
                        else local_simulations
                    ),
                    repair_index=repair_index,
                    campaign_index=campaign_index,
                    objective=self.config.objective,
                    best_objective_value=(
                        self._evaluation_value(self.best.evaluation)
                        if self.best.output_valid
                        else self.baseline_objective_value
                    ),
                    best_gold_bonus_ticks=self.best.evaluation.gold_bonus_ticks,
                    best_gold_count=self.best.evaluation.gold_count,
                    best_exit_edge_distance=pre_finish_exit_edge_distance(
                        self.level, self.best.evaluation
                    ),
                )
            )

    def _consider(
        self,
        working: Sequence[InputFrame],
        *,
        origin: str,
        parent: AutoCandidate,
        description: str,
        phase: str,
        allow_gold_repair: bool = True,
    ) -> AutoCandidate | None:
        body = tuple(working[:-1])
        if self.extra_ticks:
            body = (
                body[: self.workspace_body_length]
                + (NEUTRAL_INPUT,)
                * max(0, self.workspace_body_length - len(body))
            )
        fixed = body + (NEUTRAL_INPUT,)
        self.counters["macro_candidates"] += 1
        replay_key = _frame_key(fixed)
        if replay_key in self.seen:
            self.counters["deduplicated"] += 1
            return None
        if self._budget_exhausted():
            return None
        self.seen.add(replay_key)
        evaluation = _evaluate_working(
            self.level, fixed, trace_stride=self.config.trace_stride
        )
        self.counters["macro_evaluations"] += 1
        if self.counters["macro_evaluations"] % 100 == 0:
            self._emit(phase, self._PHASE_ACTIVITY.get(phase, description))
        fixed, evaluation, sentinel_verified = _normalise_completed_working(
            self.level,
            fixed,
            evaluation,
            trace_stride=self.config.trace_stride,
            preserve_body_length=(
                self.workspace_body_length if self.extra_ticks else None
            ),
        )
        canonical_key = _frame_key(fixed)
        if canonical_key != replay_key:
            if canonical_key in self.seen:
                self.counters["deduplicated"] += 1
                return None
            self.seen.add(canonical_key)
        alignment = find_baseline_alignment(
            evaluation,
            self.reference_eval,
            max_alignment=self.config.max_alignment,
            max_negative_alignment=(
                self.extra_ticks
                if self.search_config.objective == AUTO_OBJECTIVE_HIGHSCORE
                else 0
            ),
            position_tolerance=self.config.alignment_position_tolerance,
            velocity_tolerance=self.config.alignment_velocity_tolerance,
            objective=self.search_config.objective,
            reference_completion_exit_index=(
                self.reference_eval.completed_exit_index
            ),
        )
        candidate = AutoCandidate(
            working_frames=fixed,
            evaluation=evaluation,
            origin=origin,
            mutations=parent.mutations + (description,),
            generation=parent.generation + 1,
            alignment=alignment,
            edit_count=_count_edits(self.source_working, fixed),
            sentinel_verified=sentinel_verified,
            replay_key=canonical_key,
            input_transitions=input_transition_frames(fixed[:-1]),
        )
        if candidate.output_valid and self._better_than(
            evaluation, self.reference_eval
        ):
            self.reference_working = fixed
            self.reference_eval = evaluation
            assert candidate.finish_tick is not None
            self.reference_tick = candidate.finish_tick
            # The promoted candidate is the new reference, so any alignment it
            # had to the previous epoch is stale. Realign retained lineages
            # before they can be selected for a reference-suffix splice.
            candidate = replace(candidate, alignment=None)
            self.counters["reference_epochs"] += 1
            self.gold_repair_seen.clear()
            if self.repair_frontiers:
                self.counters["repair_frontiers_dropped"] += len(
                    self.repair_frontiers
                )
                self.repair_frontiers.clear()
                self.repair_frontier_keys.clear()
            self.last_frontier_dispatch = self.counters["macro_evaluations"]
            self.beam = [
                replace(
                    item,
                    alignment=find_baseline_alignment(
                        item.evaluation,
                        self.reference_eval,
                        max_alignment=self.config.max_alignment,
                        max_negative_alignment=(
                            self.extra_ticks
                            if self.search_config.objective
                            == AUTO_OBJECTIVE_HIGHSCORE
                            else 0
                        ),
                        position_tolerance=(
                            self.config.alignment_position_tolerance
                        ),
                        velocity_tolerance=(
                            self.config.alignment_velocity_tolerance
                        ),
                        objective=self.search_config.objective,
                        reference_completion_exit_index=(
                            self.reference_eval.completed_exit_index
                        ),
                    ),
                )
                for item in self.beam
            ]
            self.diagnostics.append(
                f"{phase}: reference epoch advanced to objective value "
                f"{self._evaluation_value(self.reference_eval)} "
                f"(finish {self.reference_tick}, "
                f"gold {self.reference_eval.gold_count})"
            )
        self.beam = _select_diverse_beam(
            (*self.beam, candidate),
            self.search_config,
            self.reference_tick,
            reference_gold_mask=self.reference_eval.final_gold_mask,
        )
        if candidate.output_valid and self._no_worse_than_baseline(evaluation):
            self.finalists.append(candidate)
            self.finalists = sorted(
                self.finalists,
                key=self._candidate_key,
            )[: max(8, self.config.beam_width)]
        if (
            candidate.output_valid
            and self._no_worse_than_baseline(evaluation)
            and self._best_candidate_key(candidate)
            < self._best_candidate_key(self.best)
        ):
            old_tick = self.best.finish_tick
            old_value = self._evaluation_value(self.best.evaluation)
            self.best = candidate
            if self.config.objective == AUTO_OBJECTIVE_HIGHSCORE:
                self.diagnostics.append(
                    f"{phase}: best score "
                    f"{old_value}->{self._evaluation_value(evaluation)}; "
                    f"finish {old_tick}->{candidate.finish_tick}; "
                    f"gold {candidate.evaluation.gold_count} via {description}"
                )
            else:
                self.diagnostics.append(
                    f"{phase}: best {old_tick}->{candidate.finish_tick} "
                    f"via {description}"
                )
            # Emit first so wrappers can associate the exact macro-evaluation
            # count with the immediately following best checkpoint.
            self._emit(phase, self.diagnostics[-1])
            if self.best_callback is not None:
                self.best_callback(self.best)
        if (
            allow_gold_repair
            and self.search_config.objective == AUTO_OBJECTIVE_HIGHSCORE
            and candidate.output_valid
        ):
            self._attempt_gold_repair(candidate)
        return candidate

    def _attempt_repair(
        self,
        candidate: AutoCandidate,
        failure_tick: int,
        *,
        phase: str,
        label: str,
        strategic: bool = False,
        reference_offset: int | None = None,
        required_gold_mask: int = 0,
        require_failure_jump: bool = True,
        repair_reference: AutoEvaluation | None = None,
        campaign_index: int = 0,
        frame_ahead_seen: bool = False,
    ) -> AutoCandidate | None:
        # A repair is useful only if one macro-evaluation slot remains to admit
        # and rank its result. Avoid an expensive local search whose proposal
        # would be unconditionally discarded by ``_consider``.
        if self._budget_exhausted():
            return None
        self.counters["repair_attempts"] += 1
        repair_number = self.counters["repair_attempts"]
        primary_repair_order = _seeded_primary_repair_order(
            self.config.seed,
            repair_number,
        )
        direction_repair_rng = (
            _derive_repair_search_rng(
                self.config.seed, repair_number, "direction"
            )
            if self.config.repair_search_order
            == AUTO_REPAIR_SEARCH_ORDER_RANDOM
            else None
        )
        all_input_repair_rng = (
            _derive_repair_search_rng(
                self.config.seed, repair_number, "all-input"
            )
            if self.config.repair_search_order
            == AUTO_REPAIR_SEARCH_ORDER_RANDOM
            else None
        )
        offset = (
            reference_offset
            if reference_offset is not None
            else candidate.alignment.offset
            if candidate.alignment is not None
            else 0
        )
        target_reference = (
            self.reference_eval if repair_reference is None else repair_reference
        )
        control_target = self._route_control_target(
            candidate,
            repair_reference=target_reference,
            reference_offset=offset,
        )
        required_exit_mask = 0
        required_locked_door_mask = 0
        forbidden_trapdoor_mask = 0
        route_control_repair = False
        if (
            control_target is not None
            and control_target.candidate_tick <= failure_tick
        ):
            failure_tick = control_target.candidate_tick
            required_exit_mask = control_target.required_exit_mask
            required_locked_door_mask = control_target.required_locked_door_mask
            forbidden_trapdoor_mask = control_target.forbidden_trapdoor_mask
            expected_tick = min(
                target_reference.last_tick,
                max(
                    0,
                    failure_tick
                    + self.config.repair_lookahead
                    + offset,
                ),
            )
            expected_point = target_reference.point(expected_tick)
            if (
                expected_point is not None
                and target_reference.completed_exit_index is not None
            ):
                exit_bit = 1 << target_reference.completed_exit_index
                if expected_point.open_exit_mask & exit_bit:
                    required_exit_mask |= exit_bit
            label = f"{label}; route control {control_target.label}"
            route_control_repair = True
            self.counters["route_control_repair_attempts"] += 1
        frame_ahead_active = _frame_ahead_repair_eligible(
            candidate,
            frame_ahead_seen=frame_ahead_seen,
        )
        effective_local_limit = _repair_attempt_local_limit(
            self.config,
            frame_ahead=frame_ahead_active,
        )
        repair_config = (
            self.config
            if effective_local_limit == self.config.repair_local_limit
            else replace(
                self.config, repair_local_limit=effective_local_limit
            )
        )
        direction_repair_config = repair_config
        if (
            not strategic
            and not route_control_repair
            and direction_repair_config.repair_lookback > 24
        ):
            direction_repair_config = replace(
                direction_repair_config,
                repair_lookback=max(
                    direction_repair_config.repair_window, 24
                ),
            )
        attempt_local_before = self.counters["local_simulations"]
        if (
            frame_ahead_active
            and self.config.repair_local_limit
            and self.config.frame_ahead_repair_multiplier > 1
        ):
            budget_note = (
                f"; frame-ahead x{self.config.frame_ahead_repair_multiplier}; "
                f"local limit {effective_local_limit}"
            )
        elif frame_ahead_active and not self.config.repair_local_limit:
            budget_note = "; frame-ahead; local limit unlimited"
        else:
            budget_note = ""

        def remaining_repair_config(
            consumed: int,
            *,
            direction_only: bool = False,
        ) -> AutoConfig | None:
            template = (
                direction_repair_config if direction_only else repair_config
            )
            if not repair_config.repair_local_limit:
                return template
            remaining = max(
                0, repair_config.repair_local_limit - consumed
            )
            if remaining <= 0:
                return None
            if remaining == template.repair_local_limit:
                return template
            return replace(template, repair_local_limit=remaining)

        repaired: tuple[InputFrame, ...] | None = None
        repair_method: str | None = None
        consumed_local_steps = 0
        attempted_primary_labels: list[str] = []
        jump_repair_enabled = (
            repair_config.max_jump_shift >= 1
            or repair_config.max_jump_hold_delta >= 1
        )
        primary_methods = tuple(
            method
            for method in primary_repair_order
            if method != "jump" or jump_repair_enabled
        )

        for method in primary_methods:
            method_config = remaining_repair_config(
                consumed_local_steps,
                direction_only=method == "direction",
            )
            if method_config is None:
                break
            method_label = (
                "jump mutation" if method == "jump" else "direction"
            )
            method_local_before = self.counters["local_simulations"]

            def show_primary_repair(
                branches: int,
                simulations: int,
                *,
                _method_label: str = method_label,
                _local_before: int = method_local_before,
            ) -> None:
                self._emit(
                    phase,
                    f"{_method_label} repair near frame {failure_tick}; "
                    f"{label}{budget_note}",
                    local_simulations=_local_before + simulations,
                    repair_index=repair_number,
                    campaign_index=campaign_index,
                )

            if attempted_primary_labels:
                self._emit(
                    phase,
                    f"{attempted_primary_labels[-1]} repair missed; trying "
                    f"{method_label} repair near frame {failure_tick}",
                    local_simulations=method_local_before,
                    repair_index=repair_number,
                    campaign_index=campaign_index,
                )
            else:
                self._emit(
                    phase,
                    f"starting {method_label} repair near frame "
                    f"{failure_tick}; {label}{budget_note}",
                    local_simulations=attempt_local_before,
                    repair_index=repair_number,
                    campaign_index=campaign_index,
                )

            if method == "jump":
                self.counters["jump_repair_attempts"] += 1
                proposal, branches, simulations = (
                    repair_jump_mutation_lookback(
                        self.level,
                        candidate.working_frames,
                        target_reference,
                        failure_tick=failure_tick,
                        reference_offset=offset,
                        config=method_config,
                        progress=show_primary_repair,
                        required_gold_mask=required_gold_mask,
                        required_exit_mask=required_exit_mask,
                        required_locked_door_mask=required_locked_door_mask,
                        forbidden_trapdoor_mask=forbidden_trapdoor_mask,
                        require_failure_jump=require_failure_jump,
                    )
                )
            else:
                proposal, branches, simulations = repair_direction_window(
                    self.level,
                    candidate.working_frames,
                    target_reference,
                    failure_tick=failure_tick,
                    reference_offset=offset,
                    config=method_config,
                    rng=direction_repair_rng,
                    progress=show_primary_repair,
                    required_gold_mask=required_gold_mask,
                    required_exit_mask=required_exit_mask,
                    required_locked_door_mask=required_locked_door_mask,
                    forbidden_trapdoor_mask=forbidden_trapdoor_mask,
                    require_failure_jump=require_failure_jump,
                )
            self.counters["local_branches"] += branches
            self.counters["local_simulations"] += simulations
            consumed_local_steps += simulations
            attempted_primary_labels.append(method_label)
            if proposal is not None:
                repaired = proposal
                repair_method = method_label
                break

        fallback_config = remaining_repair_config(consumed_local_steps)
        if (
            repaired is None
            and self.config.all_input_repair
            and fallback_config is not None
        ):
            local_before_fallback = self.counters["local_simulations"]

            def show_all_input_repair(
                branches: int, simulations: int
            ) -> None:
                self._emit(
                    phase,
                    f"all-input fallback near frame {failure_tick}; "
                    f"{label}{budget_note}",
                    local_simulations=local_before_fallback + simulations,
                    repair_index=repair_number,
                    campaign_index=campaign_index,
                )

            missed_label = (
                "/".join(attempted_primary_labels)
                if attempted_primary_labels
                else "primary"
            )
            self._emit(
                phase,
                f"{missed_label} repair missed; trying all-input fallback "
                f"near frame {failure_tick}",
                local_simulations=local_before_fallback,
                repair_index=repair_number,
                campaign_index=campaign_index,
            )
            repaired, branches, simulations = repair_all_input_window(
                self.level,
                candidate.working_frames,
                target_reference,
                seed_evaluation=candidate.evaluation,
                failure_tick=failure_tick,
                reference_offset=offset,
                config=fallback_config,
                rng=all_input_repair_rng,
                progress=show_all_input_repair,
                required_gold_mask=required_gold_mask,
                required_exit_mask=required_exit_mask,
                required_locked_door_mask=required_locked_door_mask,
                forbidden_trapdoor_mask=forbidden_trapdoor_mask,
                require_failure_jump=require_failure_jump,
            )
            self.counters["local_branches"] += branches
            self.counters["local_simulations"] += simulations
            self.counters["all_input_repairs"] += 1
            if repaired is not None:
                repair_method = "all-input"
        if repaired is None:
            return None
        result = self._consider(
            repaired,
            origin="repair",
            parent=candidate,
            description=(
                f"{repair_method} repair near {failure_tick} ({label})"
            ),
            phase=phase,
            allow_gold_repair=False,
        )
        if result is not None and (
            result.output_valid
            or result.evaluation.last_tick > candidate.evaluation.last_tick
            or len(result.evaluation.successful_jumps)
            > len(candidate.evaluation.successful_jumps)
            or (
                required_gold_mask
                and result.evaluation.final_gold_mask & required_gold_mask
                == required_gold_mask
            )
        ):
            self.counters["successful_repairs"] += 1
        if result is not None and route_control_repair and (
            result.output_valid
            or self._route_control_target(
                result,
                repair_reference=target_reference,
                reference_offset=offset,
            )
            is None
        ):
            self.counters["successful_route_control_repairs"] += 1
        return result

    def _attempt_gold_repair(
        self, candidate: AutoCandidate
    ) -> AutoCandidate | None:
        """Try to restore the earliest valuable gold missed by a live route."""
        if (
            self.search_config.objective != AUTO_OBJECTIVE_HIGHSCORE
            or not candidate.output_valid
            or self._budget_exhausted()
        ):
            return None

        desirable_mask = (
            self.required_reference_gold_mask
            | self.reference_eval.final_gold_mask
        )
        missing_mask = desirable_mask & ~candidate.evaluation.final_gold_mask
        if not missing_mask:
            return None
        candidate_value = self._evaluation_value(candidate.evaluation)
        potential_value = (
            candidate_value
            + GOLD_BONUS_TICKS * missing_mask.bit_count()
        )
        if potential_value < self._evaluation_value(self.best.evaluation):
            return None

        event_sources = (self.reference_eval, self.baseline_eval)
        event_options: list[
            tuple[int, GoldCollectionEvent, AutoEvaluation]
        ] = []
        for event_source in event_sources:
            for event in event_source.gold_events:
                bit = 1 << event.gold_index
                if missing_mask & bit:
                    event_options.append((event.tick, event, event_source))
        if not event_options:
            return None
        _event_tick, event, event_source = min(
            event_options,
            key=lambda item: (item[0], item[1].gold_index),
        )
        bit = 1 << event.gold_index
        repair_identity = (_candidate_replay_key(candidate), bit)
        if repair_identity in self.gold_repair_seen:
            return None

        if candidate.alignment is not None:
            offset = candidate.alignment.offset
        else:
            assert candidate.finish_tick is not None
            assert event_source.finish_tick is not None
            offset = event_source.finish_tick - candidate.finish_tick
        candidate_event_tick = event.tick - offset
        candidate_event_tick = min(
            max(self.config.range_start, candidate_event_tick),
            self.range_end,
        )

        self.gold_repair_seen.add(repair_identity)
        self._record_repair_attempt(strategic=True)
        self.counters["gold_repair_attempts"] += 1
        result = self._attempt_repair(
            candidate,
            candidate_event_tick,
            phase="gold-repair",
            label=(
                f"restoring gold:{event.gold_index} near reference frame "
                f"{event.tick}"
            ),
            strategic=True,
            reference_offset=offset,
            required_gold_mask=bit,
            require_failure_jump=False,
            repair_reference=event_source,
        )
        if (
            result is not None
            and result.evaluation.final_gold_mask & bit == bit
        ):
            self.counters["successful_gold_repairs"] += 1
            # A candidate can miss more than one reference gold. Continue
            # restoring the earliest remaining item. Every intermediate result
            # has already been admitted and ranked by ``_consider``.
            chained = self._attempt_gold_repair(result)
            return chained if chained is not None else result
        return result

    def _frontier_misses(
        self,
        frontier: _RepairFrontier,
        candidate: AutoCandidate | None = None,
    ) -> tuple[int, ...]:
        current = frontier.candidate if candidate is None else candidate
        if frontier.mutation is None:
            return ()
        return detect_shifted_missed_jumps(
            frontier.reference_successful_jumps,
            current.evaluation,
            frontier.mutation,
        )

    def _frontier_failure(
        self,
        frontier: _RepairFrontier,
        candidate: AutoCandidate | None = None,
    ) -> int:
        current = frontier.candidate if candidate is None else candidate
        return _first_failure(
            current.evaluation,
            self._frontier_misses(frontier, current),
            frontier.inherited_misses,
        )

    def _frontier_priority(self, frontier: _RepairFrontier) -> tuple:
        candidate = frontier.candidate
        match = candidate.alignment
        measured_lead = (
            match.score_lead
            if match is not None and match.score_lead > 0
            else 0
        )
        progress_tick = (
            match.reference_tick
            if match is not None
            else candidate.evaluation.last_tick
        )
        control = self._route_control_target(
            candidate,
            repair_reference=frontier.repair_reference,
            reference_offset=frontier.reference_offset,
        )
        return (
            0
            if measured_lead
            else 1
            if frontier.intended_lead
            else 2
            if control is not None
            else 3,
            -max(measured_lead, frontier.intended_lead),
            -progress_tick,
            len(self._frontier_misses(frontier)),
            candidate.edit_count,
            frontier.attempts,
        )

    def _insert_repair_frontier(
        self,
        frontier: _RepairFrontier,
        *,
        count_new: bool,
    ) -> bool:
        key = _candidate_replay_key(frontier.candidate)
        if key in self.repair_frontier_keys:
            return False
        region = self._frontier_failure(frontier) // 8
        same_region = [
            item
            for item in self.repair_frontiers
            if self._frontier_failure(item) // 8 == region
        ]
        if len(same_region) >= 2:
            worst = max(same_region, key=self._frontier_priority)
            if self._frontier_priority(frontier) >= self._frontier_priority(
                worst
            ):
                self.counters["repair_frontiers_dropped"] += 1
                return False
            self.repair_frontiers.remove(worst)
            self.repair_frontier_keys.discard(
                _candidate_replay_key(worst.candidate)
            )
            self.counters["repair_frontiers_dropped"] += 1
        self.repair_frontiers.append(frontier)
        self.repair_frontier_keys.add(key)
        self.repair_frontiers.sort(key=self._frontier_priority)
        archive_limit = max(16, self.config.beam_width * 4)
        while len(self.repair_frontiers) > archive_limit:
            dropped = self.repair_frontiers.pop()
            self.repair_frontier_keys.discard(
                _candidate_replay_key(dropped.candidate)
            )
            self.counters["repair_frontiers_dropped"] += 1
        if count_new and key in self.repair_frontier_keys:
            self.counters["repair_frontiers_queued"] += 1
        return key in self.repair_frontier_keys

    def _queue_repair_frontier(
        self,
        candidate: AutoCandidate | None,
        *,
        phase: str,
        label: str,
        strategic: bool = False,
        intended_lead: int = 0,
        reference_offset: int | None = None,
        repair_reference: AutoEvaluation | None = None,
        inherited_misses: Sequence[int] = (),
        reference_successful_jumps: Sequence[int] = (),
        mutation: RetimeMutation | None = None,
        required_gold_mask: int = 0,
        require_failure_jump: bool = True,
    ) -> None:
        if candidate is None or candidate.output_valid:
            return
        target_reference = (
            self.reference_eval
            if repair_reference is None
            else repair_reference
        )
        effective_offset = (
            reference_offset
            if reference_offset is not None
            else candidate.alignment.offset
            if candidate.alignment is not None
            else 0
        )
        measured_lead = (
            candidate.alignment.score_lead
            if candidate.alignment is not None
            and candidate.alignment.score_lead > 0
            else 0
        )
        control = self._route_control_target(
            candidate,
            repair_reference=target_reference,
            reference_offset=effective_offset,
        )
        strategic = bool(
            strategic or measured_lead or intended_lead or control is not None
        )
        provisional = _RepairFrontier(
            candidate=candidate,
            phase=phase,
            label=label,
            strategic=strategic,
            intended_lead=max(0, intended_lead),
            reference_offset=effective_offset,
            repair_reference=target_reference,
            inherited_misses=tuple(inherited_misses),
            reference_successful_jumps=tuple(reference_successful_jumps),
            mutation=mutation,
            required_gold_mask=required_gold_mask,
            require_failure_jump=require_failure_jump,
            epoch=self.counters["reference_epochs"],
            frame_ahead_seen=_frame_ahead_repair_eligible(candidate),
        )
        self._insert_repair_frontier(provisional, count_new=True)

    def _dispatch_repair_frontier(self, *, force: bool = False) -> bool:
        if not self.repair_frontiers or self._budget_exhausted():
            return False
        stale = [
            item
            for item in self.repair_frontiers
            if item.epoch != self.counters["reference_epochs"]
        ]
        for item in stale:
            self.repair_frontiers.remove(item)
            self.repair_frontier_keys.discard(
                _candidate_replay_key(item.candidate)
            )
        self.counters["repair_frontiers_dropped"] += len(stale)
        if not self.repair_frontiers:
            return False
        dispatch_interval = max(8, min(32, self.config.beam_width))
        if (
            not force
            and self.counters["macro_evaluations"]
            - self.last_frontier_dispatch
            < dispatch_interval
            and len(self.repair_frontiers) < min(8, self.config.beam_width)
        ):
            return False
        self.repair_frontiers.sort(key=self._frontier_priority)
        frontier = self.repair_frontiers.pop(0)
        self.repair_frontier_keys.discard(
            _candidate_replay_key(frontier.candidate)
        )
        self.last_frontier_dispatch = self.counters["macro_evaluations"]
        if frontier.attempts == 0:
            self.counters["repair_campaigns"] += 1
        attempted = False
        should_requeue = False
        # Two attempts form one dispatch burst. Productive campaigns return to
        # the ranked archive so another failure region gets a chance first.
        for _ in range(2):
            if self._budget_exhausted():
                break
            failure_tick = self._frontier_failure(frontier)
            region = failure_tick // 8
            if frontier.failure_regions.count(region) >= 2:
                break
            attempted = True
            self._record_repair_attempt(strategic=frontier.strategic)
            frontier.failure_regions += (region,)
            frontier.attempts += 1
            self.counters["repair_campaign_attempts"] += 1
            before = frontier.candidate
            frame_ahead_before = frontier.frame_ahead_seen
            before_misses = self._frontier_misses(frontier, before)
            before_control = self._route_control_target(
                before,
                repair_reference=frontier.repair_reference,
                reference_offset=frontier.reference_offset,
            )
            local_before = self.counters["local_simulations"]
            repaired = self._attempt_repair(
                before,
                failure_tick,
                phase=frontier.phase,
                label=frontier.label,
                strategic=frontier.strategic,
                reference_offset=frontier.reference_offset,
                required_gold_mask=frontier.required_gold_mask,
                require_failure_jump=frontier.require_failure_jump,
                repair_reference=frontier.repair_reference,
                campaign_index=frontier.attempts,
                frame_ahead_seen=frontier.frame_ahead_seen,
            )
            frontier.local_simulations += (
                self.counters["local_simulations"] - local_before
            )
            if (
                repaired is None
                or repaired.working_frames == before.working_frames
            ):
                break
            frontier.candidate = repaired
            frontier.frame_ahead_seen = _frame_ahead_repair_eligible(
                repaired,
                frame_ahead_seen=frontier.frame_ahead_seen,
            )
            frame_ahead_activated = (
                frontier.frame_ahead_seen and not frame_ahead_before
            )
            after_failure = self._frontier_failure(frontier, repaired)
            after_misses = self._frontier_misses(frontier, repaired)
            after_control = self._route_control_target(
                repaired,
                repair_reference=frontier.repair_reference,
                reference_offset=frontier.reference_offset,
            )
            before_reference_tick = (
                before.alignment.reference_tick
                if before.alignment is not None
                else -1
            )
            after_reference_tick = (
                repaired.alignment.reference_tick
                if repaired.alignment is not None
                else -1
            )
            control_progress = bool(
                before_control is not None
                and (
                    after_control is None
                    or after_control.candidate_tick
                    > before_control.candidate_tick
                )
            )
            progressed = (
                repaired.output_valid
                or repaired.evaluation.last_tick > before.evaluation.last_tick
                or after_failure > failure_tick
                or len(after_misses) < len(before_misses)
                or control_progress
                or after_reference_tick > before_reference_tick
                or frame_ahead_activated
            )
            if repaired.output_valid or not progressed:
                break
            campaign_local_limit = _repair_campaign_local_limit(
                self.config,
                frame_ahead=frontier.frame_ahead_seen,
            )
            if (
                campaign_local_limit
                and frontier.local_simulations >= campaign_local_limit
            ):
                break
            should_requeue = True
        if (
            should_requeue
            and frontier.epoch == self.counters["reference_epochs"]
            and not frontier.candidate.output_valid
        ):
            self._insert_repair_frontier(frontier, count_new=False)
        return attempted

    def _raw_mutation_groups(
        self,
    ) -> tuple[list[RetimeMutation], list[RetimeMutation]]:
        """Return priority -1 retimes and the deferred larger mutations."""
        raw_mutations = (
            sorted(
                (
                    mutation
                    for mutation in valid_retime_mutations(
                        self.source_body,
                        max_retime=self.config.max_retime,
                    )
                    if self._mutation_allowed(mutation.suffix_start)
                ),
                key=lambda mutation: (
                    0 if mutation.delta == -1 else 1,
                    abs(mutation.delta),
                    mutation.suffix_start,
                    mutation.delta,
                ),
            )
            if self.config.deterministic_phase
            else []
        )
        priority_raw = [
            mutation for mutation in raw_mutations if mutation.delta == -1
        ]
        deferred_raw = [
            mutation for mutation in raw_mutations if mutation.delta != -1
        ]
        return priority_raw, deferred_raw

    def _run_priority_retimes(
        self, priority_raw: Sequence[RetimeMutation]
    ) -> None:
        """Screen high-value -1 suffixes and repair promising failures."""
        priority_raw_budget = min(
            len(priority_raw),
            max(1, self.config.iterations // 4)
            if self.config.iterations
            else 0,
        )
        if priority_raw_budget and not self._budget_exhausted():
            self._emit(
                "raw-retime",
                f"testing {priority_raw_budget} high-value -1 suffix retimes",
            )
        for mutation in priority_raw[:priority_raw_budget]:
            if self._budget_exhausted():
                break
            changed_body = apply_suffix_retime(self.source_body, mutation)
            candidate = self._consider(
                tuple(changed_body) + (NEUTRAL_INPUT,),
                origin="retime",
                parent=self.baseline,
                description=(
                    f"suffix {mutation.suffix_start} {mutation.delta:+d}"
                ),
                phase="raw-retime",
            )
            self.counters["raw_retimes"] += 1
            if candidate is None:
                continue
            missed = detect_shifted_missed_jumps(
                self.baseline_eval.successful_jumps,
                candidate.evaluation,
                mutation,
            )
            if (
                missed
                or candidate.alignment is not None
                or self._route_control_target(
                    candidate,
                    reference_offset=-mutation.delta,
                )
                is not None
            ):
                strategic = (
                    candidate.alignment is not None
                    and candidate.alignment.score_lead > 0
                )
                self._record_repair_attempt(strategic=strategic)
                self._attempt_repair(
                    candidate,
                    _first_failure(
                        candidate.evaluation,
                        missed,
                        tuple(
                            tick + mutation.delta
                            if tick >= mutation.suffix_start
                            else tick
                            for tick in self.baseline_eval.missed_jump_edges
                        ),
                    ),
                    phase="raw-repair",
                    label=f"shifted missed jumps {missed or 'none'}",
                    strategic=strategic,
                    reference_offset=-mutation.delta,
                )

    def _run_cheap_pulse_sweep(self) -> None:
        """Run the deterministic reverse one-frame horizontal sweep."""
        semantic_reserve = min(80, max(8, self.config.iterations // 3))
        source_jump_pulses = _jump_pulses(self.source_body)
        structured_jump_route = len(source_jump_pulses) >= 8 or any(
            end - start + 1 > 31 for start, end in source_jump_pulses
        )
        effective_cheap_limit = min(
            self.config.cheap_pulse_limit,
            32
            if structured_jump_route
            else self.config.cheap_pulse_limit,
        )
        cheap_budget = (
            min(
                effective_cheap_limit,
                max(
                    0,
                    self.config.iterations
                    - self.counters["macro_evaluations"]
                    - semantic_reserve,
                ),
            )
            if self.config.deterministic_phase
            else 0
        )
        cheap_evaluated = 0
        if cheap_budget and not self._budget_exhausted():
            self._emit(
                "cheap-pulse",
                "horizontal sweep; up to "
                f"{cheap_budget} one-frame pulse evaluations",
            )
        cheap_range_end = min(self.range_end, len(self.source_body) - 1)
        for tick in range(
            cheap_range_end, self.config.range_start - 1, -1
        ):
            if cheap_evaluated >= cheap_budget:
                break
            old = self.source_body[tick]
            choices = (0, -old.horizontal, -1, 1)
            used: set[int] = {old.horizontal}
            for direction in choices:
                if direction in used or cheap_evaluated >= cheap_budget:
                    continue
                used.add(direction)
                changed = list(self.source_working)
                changed[tick] = InputFrame(
                    direction < 0,
                    direction > 0,
                    old.jump,
                    None,
                )
                candidate = self._consider(
                    changed,
                    origin="horizontal-pulse",
                    parent=self.baseline,
                    description=(
                        f"horizontal pulse {tick}+1={direction:+d}"
                    ),
                    phase="cheap-pulse",
                )
                if candidate is not None:
                    cheap_evaluated += 1
                    self.counters["pulse_mutations"] += 1
            if self._budget_exhausted():
                break

    def _run_semantic_jump_phase(self) -> None:
        """Explore systematic jump edits and their -1 repair chains."""
        pulse_candidates: list[AutoCandidate] = []
        coordinated_seed_repaired = False
        semantic_variants = (
            _semantic_jump_variants(
                self.source_working,
                self.config,
                limit=(
                    self.config.iterations
                    - self.counters["macro_evaluations"]
                ),
            )
            if self.config.deterministic_phase
            and not self._budget_exhausted()
            else ()
        )
        if semantic_variants and not self._budget_exhausted():
            self._emit(
                "jump",
                "systematic jump variants; "
                f"{len(semantic_variants)} proposals available",
            )
        for changed, description in semantic_variants:
            if self._budget_exhausted():
                break
            if not self._mutation_allowed(
                _first_changed_frame(self.source_working, changed)
            ):
                continue
            candidate = self._consider(
                changed,
                origin="jump",
                parent=self.baseline,
                description=description,
                phase="jump",
            )
            self.counters["jump_mutations"] += 1
            if candidate is None:
                continue
            coordinated = (
                " shift " in f" {description} "
                and " hold " in f" {description} "
            )
            if (
                not candidate.output_valid
                and coordinated
                and not coordinated_seed_repaired
            ):
                self._record_repair_attempt(strategic=True)
                repaired = self._attempt_repair(
                    candidate,
                    _first_failure(
                        candidate.evaluation,
                        inherited_misses=(
                            self.baseline_eval.missed_jump_edges
                        ),
                    ),
                    phase="pulse-repair",
                    label="coordinated pulse edit",
                    strategic=True,
                )
                if repaired is not None:
                    candidate = repaired
                    if candidate.output_valid:
                        coordinated_seed_repaired = True
            if candidate.output_valid and self._equal_to_baseline(
                candidate.evaluation
            ):
                pulse_candidates.append(candidate)

        if pulse_candidates and not self._budget_exhausted():
            self._emit(
                "jump-retime",
                "testing -1 suffixes from "
                f"{len(pulse_candidates)} no-worse jump variants",
            )
        for pulse_candidate in pulse_candidates:
            if self._budget_exhausted():
                break
            if self._better_than(self.reference_eval, self.baseline_eval):
                break
            if (
                not pulse_candidate.output_valid
                or not self._equal_to_baseline(
                    pulse_candidate.evaluation
                )
            ):
                continue
            self._run_pulse_candidate_retimes(pulse_candidate)
            if self._has_strict_improvement():
                break

    def _run_pulse_candidate_retimes(
        self, pulse_candidate: AutoCandidate
    ) -> None:
        """Screen and repair -1 frontiers from one semantic pulse seed."""
        body = pulse_candidate.working_frames[:-1]
        frontiers: list[
            tuple[AutoCandidate, RetimeMutation, tuple[int, ...]]
        ] = []
        for transition in reversed(
            _candidate_input_transitions(pulse_candidate)
        ):
            if self._budget_exhausted():
                break
            if not self._mutation_allowed(transition):
                continue
            mutation = RetimeMutation(transition, -1)
            try:
                changed_body = apply_suffix_retime(body, mutation)
            except ValueError:
                continue
            candidate = self._consider(
                tuple(changed_body) + (NEUTRAL_INPUT,),
                origin="retime-after-jump",
                parent=pulse_candidate,
                description=f"suffix {transition} -1",
                phase="jump-retime",
            )
            self.counters["raw_retimes"] += 1
            if candidate is None:
                continue
            missed = detect_shifted_missed_jumps(
                pulse_candidate.evaluation.successful_jumps,
                candidate.evaluation,
                mutation,
            )
            if not candidate.output_valid and (
                missed
                or (
                    candidate.alignment is not None
                    and candidate.alignment.score_lead > 0
                )
                or self._route_control_target(
                    candidate,
                    reference_offset=-mutation.delta,
                )
                is not None
            ):
                frontiers.append((candidate, mutation, missed))

        frontiers.sort(
            key=lambda item: (
                len(item[2]),
                -item[0].evaluation.last_tick,
                -item[1].suffix_start,
            )
        )
        # At most two frontiers per neutral pulse seed receive cascading repair;
        # this keeps default runtime bounded without starving the strategic chain.
        for candidate, mutation, _initial_missed in frontiers[:2]:
            if self._has_strict_improvement():
                break
            self._run_deep_repair_campaign(
                pulse_candidate,
                candidate,
                mutation,
            )

    def _run_deep_repair_campaign(
        self,
        pulse_candidate: AutoCandidate,
        candidate: AutoCandidate,
        mutation: RetimeMutation,
    ) -> None:
        """Cascade repairs for one shifted semantic-jump frontier."""
        current = candidate
        chain_steps = 0
        campaign_local_start = self.counters["local_simulations"]
        failure_regions: list[int] = []
        campaign_counted = False
        frame_ahead_seen = _frame_ahead_repair_eligible(current)
        while not current.output_valid and not self._budget_exhausted():
            missed = detect_shifted_missed_jumps(
                pulse_candidate.evaluation.successful_jumps,
                current.evaluation,
                mutation,
            )
            promising = missed or chain_steps > 0 or (
                current.alignment is not None
                and current.alignment.score_lead > 0
            )
            promising = promising or (
                self._route_control_target(
                    current,
                    reference_offset=-mutation.delta,
                )
                is not None
            )
            if not promising:
                break
            failure_tick = _first_failure(
                current.evaluation,
                missed,
                tuple(
                    tick + mutation.delta
                    if tick >= mutation.suffix_start
                    else tick
                    for tick in pulse_candidate.evaluation.missed_jump_edges
                ),
            )
            region = failure_tick // 8
            if failure_regions.count(region) >= 2:
                break
            self._record_repair_attempt(strategic=True)
            if not campaign_counted:
                self.counters["repair_campaigns"] += 1
                campaign_counted = True
            failure_regions.append(region)
            chain_steps += 1
            self.counters["repair_campaign_attempts"] += 1
            before = current
            frame_ahead_before = frame_ahead_seen
            repaired = self._attempt_repair(
                current,
                failure_tick,
                phase="deep-repair",
                label=f"shifted missed jumps {missed or 'none'}",
                strategic=True,
                reference_offset=-mutation.delta,
                campaign_index=chain_steps,
                frame_ahead_seen=frame_ahead_seen,
            )
            if (
                repaired is None
                or repaired.working_frames == current.working_frames
            ):
                break
            current = repaired
            frame_ahead_seen = _frame_ahead_repair_eligible(
                current,
                frame_ahead_seen=frame_ahead_seen,
            )
            frame_ahead_activated = (
                frame_ahead_seen and not frame_ahead_before
            )
            repaired_misses = detect_shifted_missed_jumps(
                pulse_candidate.evaluation.successful_jumps,
                current.evaluation,
                mutation,
            )
            repaired_failure = _first_failure(
                current.evaluation,
                repaired_misses,
                tuple(
                    tick + mutation.delta
                    if tick >= mutation.suffix_start
                    else tick
                    for tick in pulse_candidate.evaluation.missed_jump_edges
                ),
            )
            progressed = (
                current.output_valid
                or current.evaluation.last_tick > before.evaluation.last_tick
                or repaired_failure > failure_tick
                or len(repaired_misses) < len(missed)
                or frame_ahead_activated
                or (
                    current.alignment is not None
                    and current.alignment.score_lead > 0
                    and (
                        before.alignment is None
                        or current.alignment.reference_tick
                        > before.alignment.reference_tick
                    )
                )
            )
            if not progressed:
                break
            campaign_local_limit = _repair_campaign_local_limit(
                self.config,
                frame_ahead=frame_ahead_seen,
            )
            if (
                campaign_local_limit
                and self.counters["local_simulations"]
                - campaign_local_start
                >= campaign_local_limit
            ):
                break

    def _run_deferred_retimes(
        self, deferred_raw: Sequence[RetimeMutation]
    ) -> None:
        """Spend a bounded remainder on non-priority raw retimes."""
        if (
            not self.config.deterministic_phase
            or self._better_than(self.reference_eval, self.baseline_eval)
        ):
            return
        deferred_budget = min(
            len(deferred_raw),
            max(
                0,
                (
                    self.config.iterations
                    - self.counters["macro_evaluations"]
                )
                // 4,
            ),
        )
        if deferred_budget and not self._budget_exhausted():
            self._emit(
                "deferred-retime",
                "screening "
                f"{deferred_budget} deferred +/-2 and +/-3 suffix retimes",
            )
        for mutation in deferred_raw[:deferred_budget]:
            if self._budget_exhausted():
                break
            changed_body = apply_suffix_retime(self.source_body, mutation)
            self._consider(
                tuple(changed_body) + (NEUTRAL_INPUT,),
                origin="retime",
                parent=self.baseline,
                description=(
                    f"suffix {mutation.suffix_start} {mutation.delta:+d}"
                ),
                phase="deferred-retime",
            )
            self.counters["raw_retimes"] += 1

    def _try_beam_suffix_retime(self, parent: AutoCandidate) -> bool:
        transitions = tuple(
            transition
            for transition in _candidate_input_transitions(parent)
            if self._mutation_allowed(transition)
        )
        if not transitions:
            return False
        transition = transitions[self.rng.randrange(len(transitions))]
        deltas = [-1, 1]
        for magnitude in range(2, self.config.max_retime + 1):
            deltas.extend((-magnitude, magnitude))
        delta = deltas[self.rng.randrange(len(deltas))]
        mutation = RetimeMutation(transition, delta)
        try:
            changed_body = apply_suffix_retime(
                parent.working_frames[:-1], mutation
            )
        except ValueError:
            return False
        candidate = self._consider(
            tuple(changed_body) + (NEUTRAL_INPUT,),
            origin="beam-retime",
            parent=parent,
            description=f"suffix {transition} {delta:+d}",
            phase="beam",
        )
        self.counters["raw_retimes"] += 1
        if candidate is not None and delta < 0 and not candidate.output_valid:
            missed = detect_shifted_missed_jumps(
                parent.evaluation.successful_jumps,
                candidate.evaluation,
                mutation,
            )
            control_target = self._route_control_target(
                candidate,
                reference_offset=-delta,
            )
            measured_lead = bool(
                candidate.alignment is not None
                and candidate.alignment.score_lead > 0
            )
            intended_lead = (
                -delta
                if candidate.evaluation.last_tick >= transition
                else 0
            )
            # A missed key or unwanted trapdoor can be the only failure, so
            # ``missed`` is legitimately empty for this repair path.
            if missed or control_target is not None or measured_lead:
                self._queue_repair_frontier(
                    candidate,
                    phase="beam-repair",
                    label=f"shifted missed jumps {missed or 'none'}",
                    strategic=measured_lead or bool(intended_lead),
                    intended_lead=intended_lead,
                    reference_offset=-delta,
                    inherited_misses=tuple(
                        tick + delta if tick >= transition else tick
                        for tick in parent.evaluation.missed_jump_edges
                    ),
                    reference_successful_jumps=(
                        parent.evaluation.successful_jumps
                    ),
                    mutation=mutation,
                )
        return True

    def _try_reference_splice(self, parent: AutoCandidate) -> bool:
        assert parent.alignment is not None
        if not self._mutation_allowed(parent.alignment.candidate_tick + 1):
            return False
        changed = apply_reference_suffix_splice(
            parent.working_frames,
            self.reference_working,
            parent.alignment,
            max_body_length=(
                self.workspace_body_length if self.extra_ticks else None
            ),
        )
        self._consider(
            changed,
            origin="splice",
            parent=parent,
            description=(
                f"reference suffix {parent.alignment.reference_tick + 1}"
                f"->{parent.alignment.candidate_tick + 1}"
            ),
            phase="splice",
        )
        self.counters["suffix_splices"] += 1
        return True

    def _try_beam_jump_mutation(self, parent: AutoCandidate) -> bool:
        if (
            self.config.max_jump_shift == 0
            and self.config.max_jump_hold_delta == 0
        ):
            return False
        body = parent.working_frames[:-1]
        pulses = _jump_pulses(body)
        upper = min(self.range_end, len(body) - 1)
        released = tuple(
            tick
            for tick in range(self.config.range_start, upper + 1)
            if not body[tick].jump
        )
        action = self.rng.random()
        if pulses and action < 0.15:
            pulse_index = self.rng.randrange(len(pulses))
            start, end = pulses[pulse_index]
            try:
                changed = mutate_jump_interval(
                    parent.working_frames,
                    start,
                    end - start + 1,
                    held=False,
                )
            except ValueError:
                return False
            description = (
                f"jump pulse {pulse_index} delete "
                f"{start}+{end - start + 1}"
            )
        elif released and (not pulses or action < 0.40):
            # Weighted short insertion from integrated v2.8, factorised so the
            # horizontal channel remains byte-for-byte unchanged.
            start = released[self.rng.randrange(len(released))]
            available = 0
            while (
                available < 3
                and start + available < len(body)
                and not body[start + available].jump
            ):
                available += 1
            roll = self.rng.random()
            requested = 1 if roll < 0.70 else 2 if roll < 0.94 else 3
            length = min(requested, available)
            try:
                changed = mutate_jump_interval(
                    parent.working_frames,
                    start,
                    length,
                    held=True,
                )
            except ValueError:
                return False
            description = f"jump pulse insert {start}+{length}"
        else:
            if not pulses:
                return False
            pulse_index = self.rng.randrange(len(pulses))
            start_delta = self.rng.randint(
                -self.config.max_jump_shift,
                self.config.max_jump_shift,
            )
            hold_delta = self.rng.randint(
                -self.config.max_jump_hold_delta,
                self.config.max_jump_hold_delta,
            )
            if start_delta == 0 and hold_delta == 0:
                return False
            try:
                changed = mutate_jump_pulse(
                    parent.working_frames,
                    pulse_index,
                    start_delta=start_delta,
                    hold_delta=hold_delta,
                )
            except ValueError:
                return False
            description = (
                f"jump pulse {pulse_index} start {start_delta:+d} "
                f"hold {hold_delta:+d}"
            )
        if not self._mutation_allowed(
            _first_changed_frame(parent.working_frames, changed)
        ):
            return False
        candidate = self._consider(
            changed,
            origin="beam-jump",
            parent=parent,
            description=description,
            phase="beam",
        )
        self.counters["jump_mutations"] += 1
        if candidate is not None and not candidate.output_valid:
            self._queue_repair_frontier(
                candidate,
                phase="jump-repair",
                label="first failed contact",
                inherited_misses=parent.evaluation.missed_jump_edges,
            )
        return True

    def _try_beam_horizontal_pulse(self, parent: AutoCandidate) -> bool:
        # Empirically weighted one- to three-frame horizontal pulse. Jump is
        # deliberately preserved because factorised operators hit more densely.
        limit = len(parent.working_frames) - 1
        if limit < 1:
            return False
        upper = min(self.range_end, limit - 1)
        if self.config.range_start > upper:
            return False
        start = self.rng.randint(self.config.range_start, upper)
        roll = self.rng.random()
        length = 1 if roll < 0.70 else 2 if roll < 0.94 else 3
        length = min(length, limit - start)
        old = parent.working_frames[start]
        directions = [
            value
            for value in (0, -old.horizontal, -1, 1)
            if value != old.horizontal
        ]
        if not directions:
            return False
        direction = self.rng.choice(tuple(dict.fromkeys(directions)))
        changed = list(parent.working_frames)
        for tick in range(start, start + length):
            frame = changed[tick]
            changed[tick] = InputFrame(
                direction < 0,
                direction > 0,
                frame.jump,
                None,
            )
        changed[-1] = NEUTRAL_INPUT
        candidate = self._consider(
            changed,
            origin="beam-horizontal-pulse",
            parent=parent,
            description=(
                f"horizontal pulse {start}+{length}={direction:+d}"
            ),
            phase="beam",
        )
        self.counters["pulse_mutations"] += 1
        if candidate is not None and not candidate.output_valid:
            self._queue_repair_frontier(
                candidate,
                phase="pulse-repair",
                label="first failed contact",
                inherited_misses=parent.evaluation.missed_jump_edges,
            )
        return True

    def _try_boundary_retime(self, parent: AutoCandidate) -> bool:
        transitions = tuple(
            transition
            for transition in _candidate_input_transitions(parent)
            if self._mutation_allowed(transition)
        )
        if not transitions:
            return False
        transition = transitions[self.rng.randrange(len(transitions))]
        deltas = tuple(
            delta
            for magnitude in range(1, self.config.max_retime + 1)
            for delta in (-magnitude, magnitude)
        )
        mutation = RetimeMutation(transition, self.rng.choice(deltas))
        try:
            changed_body = apply_single_transition_retime(
                parent.working_frames[:-1], mutation
            )
        except ValueError:
            return False
        candidate = self._consider(
            tuple(changed_body) + (NEUTRAL_INPUT,),
            origin="boundary-retime",
            parent=parent,
            description=(
                f"boundary {transition} {mutation.delta:+d}"
            ),
            phase="beam",
        )
        self.counters["boundary_retimes"] += 1
        if candidate is not None and not candidate.output_valid:
            self._queue_repair_frontier(
                candidate,
                phase="boundary-repair",
                label="first failed contact",
                inherited_misses=parent.evaluation.missed_jump_edges,
            )
        return True

    def _try_direction_pair(self, parent: AutoCandidate) -> bool:
        # This operator also serves as the fallback for a kind-1 iteration whose
        # parent has no safe alignment, matching the original elif-chain.
        limit = len(parent.working_frames) - 1
        if limit < 2:
            return False
        first_upper = min(self.range_end, limit - 2)
        if self.config.range_start > first_upper:
            return False
        first = self.rng.randint(self.config.range_start, first_upper)
        second_upper = min(
            self.range_end,
            limit - 1,
            first + self.config.repair_lookback,
        )
        if second_upper <= first:
            return False
        second = self.rng.randint(first + 1, second_upper)
        changed = list(parent.working_frames)
        for tick in (first, second):
            old = changed[tick]
            choices = tuple(
                direction
                for direction in (-1, 0, 1)
                if direction != old.horizontal
            )
            direction = self.rng.choice(choices)
            changed[tick] = InputFrame(
                direction < 0,
                direction > 0,
                old.jump,
                None,
            )
        changed[-1] = NEUTRAL_INPUT
        candidate = self._consider(
            changed,
            origin="direction-pair",
            parent=parent,
            description=f"horizontal sensitivity pair {first},{second}",
            phase="beam",
        )
        self.counters["direction_mutations"] += 1
        if candidate is not None and not candidate.output_valid:
            self._queue_repair_frontier(
                candidate,
                phase="pair-repair",
                label="first failed contact",
                inherited_misses=parent.evaluation.missed_jump_edges,
            )
        return True

    def _run_beam_iteration(
        self,
        parent: AutoCandidate,
        kind: int,
    ) -> bool:
        """Run one scheduled beam operator; return false for early continue."""
        if kind == 0:
            return self._try_beam_suffix_retime(parent)
        if (
            kind == 1
            and parent.alignment is not None
            and parent.alignment.static_matches
        ):
            return self._try_reference_splice(parent)
        if kind == 2:
            return self._try_beam_jump_mutation(parent)
        if kind == 3:
            return self._try_beam_horizontal_pulse(parent)
        if kind == 4:
            return self._try_boundary_retime(parent)
        return self._try_direction_pair(parent)

    def _run_beam_phase(self) -> None:
        """Run reproducible population mutations and deferred repair work."""
        self.beam_phase_started = True
        self.last_frontier_dispatch = self.counters["macro_evaluations"]
        attempt_local_label = (
            f"{self.config.repair_local_limit} local steps per repair"
            if self.config.repair_local_limit
            else "unlimited local steps per repair"
        )
        campaign_local_label = (
            f"{self.config.repair_campaign_local_limit} local steps per campaign"
            if self.config.repair_campaign_local_limit
            else "unlimited local steps per campaign"
        )
        self.diagnostics.append(
            "repair scheduler: no global repair bank; admitted repairs are "
            f"governed by {attempt_local_label} and {campaign_local_label}"
        )
        phase_iteration = 0
        attempt_limit = max(100, self.config.iterations * 20)
        if not self._budget_exhausted() and self.beam:
            self._emit(
                "beam",
                "seeded beam search; width "
                f"{self.config.beam_width}, seed {self.config.seed}; "
                "repairs limited by local-step ceilings only",
            )
        while (
            not self._budget_exhausted()
            and self.beam
            and phase_iteration < attempt_limit
        ):
            phase_iteration += 1
            self._dispatch_repair_frontier()
            if self._budget_exhausted():
                break
            parent = (
                self.best
                if self.rng.random() < 0.5
                else self.beam[self.rng.randrange(len(self.beam))]
            )
            kind = phase_iteration % 6
            if not self._run_beam_iteration(parent, kind):
                continue

            self._dispatch_repair_frontier()
            if phase_iteration % 100 == 0:
                self._emit(
                    "beam",
                    "evaluated "
                    f"{self.counters['macro_evaluations']} macro candidates; "
                    f"frontiers {len(self.repair_frontiers)}",
                )

        while (
            not self._budget_exhausted()
            and self._dispatch_repair_frontier(force=True)
        ):
            pass

        if not self._budget_exhausted() and phase_iteration >= attempt_limit:
            self.diagnostics.append(
                "beam stopped after its deterministic mutation-attempt limit; "
                "remaining proposals were duplicates or structurally invalid"
            )

    @staticmethod
    def _format_gold_mask(mask: int) -> str:
        return ", ".join(
            f"gold:{index}"
            for index in range(mask.bit_length())
            if mask & (1 << index)
        ) or "none"

    def _finalise(self) -> AutoResult:
        """Rank and independently sentinel-verify the surviving candidates."""
        eligible_by_key: dict[bytes, AutoCandidate] = {}
        for candidate in (
            *self.finalists,
            *self.beam,
            self.best,
            self.baseline,
        ):
            if candidate.output_valid and self._no_worse_than_baseline(
                candidate.evaluation
            ):
                replay_key = _frame_key(candidate.frames)
                incumbent = eligible_by_key.get(replay_key)
                if (
                    incumbent is None
                    or self._best_candidate_key(candidate)
                    < self._best_candidate_key(incumbent)
                ):
                    eligible_by_key[replay_key] = candidate
        eligible = list(eligible_by_key.values())
        ranked_eligible = sorted(eligible, key=self._best_candidate_key)
        self._emit(
            "complete",
            "independently verifying "
            f"{len(ranked_eligible)} eligible finalist(s)",
        )
        verified: AutoEvaluation | None = None
        trimmed: tuple[InputFrame, ...] = ()
        for candidate in ranked_eligible:
            proposed = candidate.frames
            try:
                candidate_verification = verify_trimmed_replay(
                    self.level,
                    proposed,
                    expected_finish_tick=candidate.finish_tick,
                    expected_gold_mask=(
                        candidate.evaluation.final_gold_mask
                    ),
                    expected_gold_bonus_ticks=(
                        candidate.evaluation.gold_bonus_ticks
                    ),
                )
            except ValueError:
                self.diagnostics.append(
                    "final selection rejected a candidate whose winning input "
                    "could not be replaced by the neutral sentinel"
                )
                continue
            self.best = candidate
            trimmed = proposed
            verified = candidate_verification
            break
        if verified is None:
            # The verified source is always in ``eligible``; reaching this branch
            # indicates an internal timing/serialization invariant has regressed.
            raise RuntimeError("no sentinel-verifiable completed replay remained")
        assert verified.finish_tick is not None
        verified_objective_value = self._evaluation_value(verified)
        self.diagnostics.append(
            "final replay independently verified: "
            f"{self.baseline_tick}->{verified.finish_tick}; "
            f"{_count_edits(self.source_body, trimmed)} differing input frames"
        )
        self.diagnostics.append(
            "final objective value: "
            f"{self.baseline_objective_value}->{verified_objective_value}; "
            f"gold {self.baseline_eval.gold_count}->{verified.gold_count} "
            f"({self.baseline_eval.gold_bonus_ticks}->"
            f"{verified.gold_bonus_ticks} bonus ticks)"
        )
        missing_reference_gold = (
            self.baseline_eval.final_gold_mask & ~verified.final_gold_mask
        )
        additional_gold = (
            verified.final_gold_mask & ~self.baseline_eval.final_gold_mask
        )
        self.diagnostics.append(
            "missing reference gold: "
            f"{self._format_gold_mask(missing_reference_gold)}"
        )
        self.diagnostics.append(
            f"additional gold: {self._format_gold_mask(additional_gold)}"
        )
        self.diagnostics.append(
            "repair scheduler final: "
            f"structured {self.counters['structured_repair_attempts']}; "
            f"beam quick {self.counters['beam_quick_repair_attempts']}; "
            f"beam strategic "
            f"{self.counters['beam_strategic_repair_attempts']}; "
            f"queued frontiers {self.counters['repair_frontiers_queued']}"
        )
        stats = AutoStats(**self.counters)
        return AutoResult(
            frames=trimmed,
            baseline_finish_tick=self.baseline_tick,
            finish_tick=verified.finish_tick,
            best=self.best,
            stats=stats,
            diagnostics=tuple(self.diagnostics),
            beam=tuple(self.beam),
            objective=self.config.objective,
            baseline_gold_mask=self.baseline_eval.final_gold_mask,
            gold_mask=verified.final_gold_mask,
            baseline_gold_bonus_ticks=self.baseline_eval.gold_bonus_ticks,
            gold_bonus_ticks=verified.gold_bonus_ticks,
            baseline_objective_value=self.baseline_objective_value,
            objective_value=verified_objective_value,
            require_reference_gold=self.config.require_reference_gold,
        )

    def run(self) -> AutoResult:
        """Execute the structured bootstrap, beam search, and verification."""
        priority_raw, deferred_raw = self._raw_mutation_groups()
        self._run_priority_retimes(priority_raw)
        self._run_cheap_pulse_sweep()
        self._run_semantic_jump_phase()
        self._run_deferred_retimes(deferred_raw)
        self._run_beam_phase()
        return self._finalise()


def optimise_autonomous(
    level: Level,
    source_frames: Sequence[InputFrame],
    config: AutoConfig,
    progress: ProgressCallback | None = None,
    best_callback: BestCallback | None = None,
) -> AutoResult:
    """Autonomously improve the selected complete-run objective.

    The macro budget is ``config.iterations`` candidate simulations (the
    source evaluation is reported but does not consume that budget). Search
    order is structured first when enabled: raw retimes, semantic/jump
    variants and their promising -1 repairs, then beam-driven
    retime/splice/pulse/direction mutations with a priority-ranked,
    local-step-bounded repair scheduler.
    """
    token = _ACTIVE_NATIVE_SESSION.set((level, None))
    try:
        prepared = _prepare_autonomous_search(
            level, source_frames, config, progress
        )
        if isinstance(prepared, AutoResult):
            return prepared
        return _AutonomousSearch(
            level, config, prepared, progress, best_callback
        ).run()
    finally:
        _ACTIVE_NATIVE_SESSION.reset(token)


# American spelling is a convenience for callers; the CLI/documentation uses
# the project's existing British ``optimise`` spelling.
optimize_autonomous = optimise_autonomous


__all__ = [
    "AUTO_OBJECTIVE_HIGHSCORE",
    "AUTO_OBJECTIVE_SPEEDRUN",
    "AUTO_OBJECTIVES",
    "AUTO_REPAIR_SEARCH_ORDER_FIXED",
    "AUTO_REPAIR_SEARCH_ORDER_RANDOM",
    "AUTO_REPAIR_SEARCH_ORDERS",
    "GOLD_BONUS_TICKS",
    "NEUTRAL_INPUT",
    "AlignmentMatch",
    "AutoCandidate",
    "AutoConfig",
    "AutoEvaluation",
    "AutoProgress",
    "AutoResult",
    "AutoStats",
    "BestCallback",
    "CompactTracePoint",
    "GoldCollectionEvent",
    "RouteControlEvent",
    "apply_reference_suffix_splice",
    "auto_objective_value",
    "detect_shifted_missed_jumps",
    "evaluate_replay_with_sentinel",
    "find_baseline_alignment",
    "mutate_jump_pulse",
    "optimise_autonomous",
    "optimize_autonomous",
    "repair_all_input_window",
    "repair_direction_window",
    "repair_jump_mutation_lookback",
    "verify_trimmed_replay",
]

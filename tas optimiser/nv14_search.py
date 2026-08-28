"""Generic Python policy types for the native replay-search kernel.

This module deliberately contains no search implementation.  Python resolves
objectives and interaction identities and supplies ordered input choices; the
compiled extension owns simulation, state cloning, deduplication, pruning and
candidate ranking.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
import math
from typing import Any

from nv14_engine import InputFrame, Level, Player, PlayerState, Vec2
from nv14_objectives import (
    AxisWindow,
    Evaluation,
    InteractionAvoidance,
    InteractionRequirement,
    TargetSelection,
    position_within_windows,
)

try:
    import _nv14_native as _search_native
except (ImportError, OSError) as _load_error:
    _search_native = None
    _SEARCH_LOAD_ERROR: BaseException | None = _load_error
else:
    _SEARCH_LOAD_ERROR = None


INTERACTION_GOLD = 0
INTERACTION_EXIT_SWITCH = 1
INTERACTION_LOCKED_DOOR = 2
INTERACTION_TRAPDOOR = 3

_INTERACTION_KINDS = {
    "gold": INTERACTION_GOLD,
    "exit-switch": INTERACTION_EXIT_SWITCH,
    "locked-door": INTERACTION_LOCKED_DOOR,
    "trapdoor": INTERACTION_TRAPDOOR,
}

OBJECTIVE_MAX_X = 0
OBJECTIVE_MIN_X = 1
OBJECTIVE_MAX_Y = 2
OBJECTIVE_MIN_Y = 3
OBJECTIVE_MIN_DISTANCE = 4
OBJECTIVE_TRACE_DISTANCE = 5
OBJECTIVE_CONSTANT = 6

SEARCH_WRAPPER_API = 5
SEARCH_ABI_VERSION = 3
SEARCH_CORE_ABI_VERSION = 2
PATCH_ABI_VERSION = 2
TRACE_ABI_VERSION = 1
ANALYSIS_ABI_VERSION = 1

PATCH_TIE_SUPPLIED_ORDER = 0
PATCH_TIE_LOW_EDIT_LEX = 1

REQUIRED_START_EVENT_JUMPED = 1

_OBJECTIVES = {
    "max-x": OBJECTIVE_MAX_X,
    "min-x": OBJECTIVE_MIN_X,
    "max-y": OBJECTIVE_MAX_Y,
    "min-y": OBJECTIVE_MIN_Y,
    "min-distance": OBJECTIVE_MIN_DISTANCE,
}

ALL_INPUT_CHOICES = tuple(
    InputFrame(horizontal < 0, horizontal > 0, jump, None)
    for horizontal in (-1, 0, 1)
    for jump in (False, True)
)


_PLAYER_VECTOR_FIELDS = (
    "pos",
    "oldpos",
    "wall_n",
    "floor_n",
    "floor_n0",
    "floor_n1",
    "old_v",
)
_PLAYER_FLOAT_FIELDS = (
    "r",
    "xw",
    "yw",
    "maxspeed_air",
    "maxspeed_ground",
    "ground_accel",
    "air_accel",
    "norm_grav",
    "jump_grav",
    "norm_drag",
    "win_drag",
    "wall_friction",
    "skid_friction",
    "stand_friction",
    "jump_amt",
    "jump_y_bias",
    "terminal_vel",
    "g",
    "d",
)
_PLAYER_INTEGER_FIELDS = (
    "max_jump_time",
    "jump_timer",
    "floor_count",
    "jump_events",
    "cell_i",
    "cell_j",
)
_PLAYER_BOOLEAN_FIELDS = (
    "was_in_air",
    "in_air",
    "near_wall",
    "dead",
    "previous_jump_held",
    "celeb_was_in_air",
)


def _native_snapshot_value(
    snapshot: Mapping[str, object], name: str
) -> object:
    try:
        return snapshot[name]
    except KeyError as exc:
        raise RuntimeError(
            f"native search result omitted player field {name!r}"
        ) from exc


def player_from_native_snapshot(snapshot: Mapping[str, object]) -> Player:
    """Materialise a reporting-only Python Player from a native snapshot.

    This copies scalar result data; it does not run the Python emulator.  The
    returned player is used by progress, ranking and public result objects.
    """
    player = object.__new__(Player)
    for name in _PLAYER_VECTOR_FIELDS:
        raw = _native_snapshot_value(snapshot, name)
        if not isinstance(raw, (tuple, list)) or len(raw) != 2:
            raise RuntimeError(
                f"native search returned invalid player vector {name!r}"
            )
        setattr(player, name, Vec2(float(raw[0]), float(raw[1])))
    for name in _PLAYER_FLOAT_FIELDS:
        setattr(player, name, float(_native_snapshot_value(snapshot, name)))
    for name in _PLAYER_INTEGER_FIELDS:
        setattr(player, name, int(_native_snapshot_value(snapshot, name)))
    for name in _PLAYER_BOOLEAN_FIELDS:
        setattr(player, name, bool(_native_snapshot_value(snapshot, name)))
    try:
        player.state = PlayerState(int(_native_snapshot_value(snapshot, "state")))
    except ValueError as exc:
        raise RuntimeError("native search returned an invalid player state") from exc
    return player


def player_snapshot_key(player: Player) -> tuple[object, ...]:
    """Return every player field exported by the native search wrapper."""
    values: list[object] = []
    for name in _PLAYER_VECTOR_FIELDS:
        vector = getattr(player, name)
        values.append((vector.x, vector.y))
    values.extend(getattr(player, name) for name in _PLAYER_FLOAT_FIELDS)
    values.extend(getattr(player, name) for name in _PLAYER_INTEGER_FIELDS)
    values.extend(getattr(player, name) for name in _PLAYER_BOOLEAN_FIELDS)
    values.append(int(player.state))
    return tuple(values)


def native_player_matches(
    snapshot: Mapping[str, object], player: Player
) -> bool:
    """Return whether a native snapshot exactly matches a Python player."""
    return player_snapshot_key(player_from_native_snapshot(snapshot)) == (
        player_snapshot_key(player)
    )


@dataclass(slots=True)
class NativeTerminalState:
    """Reporting view of a native terminal state without Python simulation.

    Search ranking never consumes this object; C has already ranked the full
    native state.  The compact key is intentionally scoped to reporting and
    equality between native results rather than Python search deduplication.
    """

    player: Player
    frame: int | None = None

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Mapping[str, object],
        *,
        frame: int | None = None,
    ) -> "NativeTerminalState":
        return cls(player_from_native_snapshot(snapshot), frame)

    def state_key(self, *, precision: int | None = None) -> tuple[object, ...]:
        values = player_snapshot_key(self.player)
        if precision is not None:
            values = tuple(
                round(value, precision) if isinstance(value, float) else value
                for value in values
            )
        return ("native-terminal", self.frame, *values)


@lru_cache(maxsize=8)
def _fixed_native_level(level_string: str, simulate_enemies: bool) -> object:
    """Cache an independent native level used for packed-output checks."""
    import nv14_native

    native_level = nv14_native.parse_level_string(
        level_string,
        simulate_enemies=simulate_enemies,
    )
    if not nv14_native.is_native_level(native_level):
        raise RuntimeError(
            "packed-output verification requires the native engine; run "
            "'python build_native.py' from the optimiser directory"
        )
    return native_level


def evaluate_fixed_replay_native(
    level: Level,
    frames: Sequence[InputFrame],
    target_frame: int,
    objective: Callable[[object], float],
    *,
    x_window: AxisWindow | None = None,
    y_window: AxisWindow | None = None,
) -> Evaluation:
    """Evaluate one fixed target-frame replay in C and adapt its endpoint.

    This is intentionally separate from the search session so a packed output
    check starts from a fresh native level/state rather than a cached search
    prefix. It still uses the same unified extension and never calls
    ``nv14_engine.SimulationState.step``.
    """
    if target_frame < 0 or target_frame >= len(frames):
        raise ValueError("target frame lies outside the replay")
    if level.source_level_string is None:
        raise RuntimeError("native fixed evaluation requires the source level string")
    native_level = _fixed_native_level(
        level.source_level_string,
        level.simulate_enemies,
    )
    raw = native_level.simulate(
        tuple(frames[: target_frame + 1]),
        stop_on_dead=True,
        stop_on_complete=False,
    )
    if not isinstance(raw, dict) or not isinstance(raw.get("state"), dict):
        raise RuntimeError("native fixed evaluator returned invalid state data")
    raw_state = raw["state"]
    raw_player = raw_state.get("player")
    if not isinstance(raw_player, dict):
        raise RuntimeError("native fixed evaluator omitted the terminal player")
    state = NativeTerminalState.from_snapshot(
        raw_player,
        frame=int(raw_state.get("frame", target_frame + 1)),
    )
    consumed = int(raw.get("consumed", 0))
    feasible = (
        consumed == target_frame + 1
        and not state.player.dead
        and position_within_windows(
            state, x_window=x_window, y_window=y_window
        )
    )
    score = float(objective(state)) if feasible else float("-inf")
    return Evaluation(score, state, feasible)


@dataclass(frozen=True, slots=True)
class InteractionAtomSpec:
    """One native persistent-state identity."""

    kind: int
    index: int

    def __post_init__(self) -> None:
        if self.kind not in _INTERACTION_KINDS.values():
            raise ValueError(f"unknown native interaction kind {self.kind}")
        if self.index < 0:
            raise ValueError("native interaction index must be non-negative")


@dataclass(frozen=True, slots=True)
class InteractionGroupSpec:
    """Alternatives of which any one satisfies or violates a constraint."""

    alternatives: tuple[InteractionAtomSpec, ...]

    def __post_init__(self) -> None:
        if not self.alternatives:
            raise ValueError("native interaction group must not be empty")


@dataclass(frozen=True, slots=True)
class TraceTargetSpec:
    """Compact policy-defined route point for native repair scoring."""

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
    collected_gold_mask: int
    exploded_mine_mask: int
    open_exit_mask: int
    opened_locked_door_mask: int
    triggered_trapdoor_mask: int
    position_weight: float = 1.0
    velocity_weight: float = 4.0
    contact_mismatch_penalty: float = 16.0
    in_air_mismatch_penalty: float = 25.0
    near_wall_mismatch_penalty: float = 9.0
    gold_bit_penalty: float = 0.25
    mine_bit_penalty: float = 0.25
    exit_bit_penalty: float = 8.0
    locked_door_bit_penalty: float = 24.0
    trapdoor_bit_penalty: float = 24.0

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.x, self.y, self.vx, self.vy)):
            raise ValueError("native trace-target kinematics must be finite")
        if self.player_state not in range(8):
            raise ValueError("native trace-target player state is out of range")
        if any(value not in (-1, 0, 1) for value in (self.wall_x, self.floor_x, self.floor_y)):
            raise ValueError("native trace-target normal bins must be -1, 0 or 1")
        if any(
            value < 0
            for value in (
                self.collected_gold_mask,
                self.exploded_mine_mask,
                self.open_exit_mask,
                self.opened_locked_door_mask,
                self.triggered_trapdoor_mask,
            )
        ):
            raise ValueError("native trace-target masks must be non-negative")
        weights = (
            self.position_weight,
            self.velocity_weight,
            self.contact_mismatch_penalty,
            self.in_air_mismatch_penalty,
            self.near_wall_mismatch_penalty,
            self.gold_bit_penalty,
            self.mine_bit_penalty,
            self.exit_bit_penalty,
            self.locked_door_bit_penalty,
            self.trapdoor_bit_penalty,
        )
        if any(not math.isfinite(value) or value < 0.0 for value in weights):
            raise ValueError(
                "native trace-target weights must be finite and non-negative"
            )

    def payload(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class PatchAssignmentSpec:
    """One changed input in a sparse Auto candidate patch."""

    frame: int
    input: InputFrame

    def __post_init__(self) -> None:
        if self.frame < 0:
            raise ValueError("native patch assignment frame must be non-negative")


@dataclass(frozen=True, slots=True)
class PatchEvaluationSpec:
    """Ordered sparse candidates for the generic native patch evaluator.

    Python selects and orders complete patches. The native kernel shares exact
    unchanged-prefix checkpoints internally, but charges every candidate tick
    independently so truncating ``max_simulated_ticks`` retains Auto's policy
    semantics.
    """

    patches: tuple[tuple[PatchAssignmentSpec, ...], ...]
    target_frame: int
    trace_target: TraceTargetSpec | None = None
    required_groups: tuple[InteractionGroupSpec, ...] = ()
    avoided_groups: tuple[InteractionGroupSpec, ...] = ()
    required_jump_frames: tuple[int, ...] = ()
    ignored_jump_frames: tuple[int, ...] = ()
    minimum_jump_events: int = 0
    required_jump_any: bool = False
    prune_inactive_jump: bool = False
    tie_policy: int = PATCH_TIE_SUPPLIED_ORDER
    max_simulated_ticks: int = 0
    capture_endpoints: bool = True

    def __post_init__(self) -> None:
        if self.target_frame < 0:
            raise ValueError("native patch target frame must be non-negative")
        for patch in self.patches:
            if not patch:
                raise ValueError("native patches must not be empty")
            frames = tuple(assignment.frame for assignment in patch)
            if tuple(sorted(set(frames))) != frames:
                raise ValueError(
                    "native patch assignment frames must be unique and sorted"
                )
            if frames[-1] > self.target_frame:
                raise ValueError(
                    "native patch assignment exceeds the target frame"
                )
        if tuple(sorted(set(self.required_jump_frames))) != (
            self.required_jump_frames
        ):
            raise ValueError("required native jump frames must be unique and sorted")
        if tuple(sorted(set(self.ignored_jump_frames))) != self.ignored_jump_frames:
            raise ValueError("ignored native jump frames must be unique and sorted")
        if any(
            frame < 0 or frame > self.target_frame
            for frame in (*self.required_jump_frames, *self.ignored_jump_frames)
        ):
            raise ValueError("native patch jump frame is outside the target")
        if self.required_jump_any and not self.required_jump_frames:
            raise ValueError("required-jump-any needs at least one accepted frame")
        if self.minimum_jump_events < 0:
            raise ValueError("native minimum jump-event count must be non-negative")
        if self.tie_policy not in (
            PATCH_TIE_SUPPLIED_ORDER,
            PATCH_TIE_LOW_EDIT_LEX,
        ):
            raise ValueError(f"unknown native patch tie policy {self.tie_policy!r}")
        if self.max_simulated_ticks < 0:
            raise ValueError("native simulation limit must be non-negative")

    def payload(self) -> dict[str, object]:
        """Return the immutable values consumed by the Cython wrapper."""
        return {
            "patches": tuple(
                tuple((assignment.frame, assignment.input) for assignment in patch)
                for patch in self.patches
            ),
            "target_frame": self.target_frame,
            "trace_target": (
                None if self.trace_target is None else self.trace_target.payload()
            ),
            "required_groups": tuple(
                tuple((atom.kind, atom.index) for atom in group.alternatives)
                for group in self.required_groups
            ),
            "avoided_groups": tuple(
                tuple((atom.kind, atom.index) for atom in group.alternatives)
                for group in self.avoided_groups
            ),
            "required_jump_frames": self.required_jump_frames,
            "ignored_jump_frames": self.ignored_jump_frames,
            "minimum_jump_events": self.minimum_jump_events,
            "required_jump_any": self.required_jump_any,
            "prune_inactive_jump": self.prune_inactive_jump,
            "tie_policy": self.tie_policy,
            "max_simulated_ticks": self.max_simulated_ticks,
            "capture_endpoints": self.capture_endpoints,
        }


@dataclass(frozen=True, slots=True)
class PatchEvaluationStats:
    branches: int = 0
    simulated_ticks: int = 0
    cloned_states: int = 0
    inactive_jump_prunes: int = 0
    dead_prunes: int = 0
    avoided_interaction_prunes: int = 0

    @classmethod
    def from_mapping(cls, values: object) -> "PatchEvaluationStats":
        mapping = values if isinstance(values, dict) else {}
        return cls(
            **{
                field: int(mapping.get(field, 0))
                for field in cls.__dataclass_fields__
            }
        )


@dataclass(frozen=True, slots=True)
class PatchEvaluationCandidate:
    feasible: bool
    has_endpoint: bool
    dead: bool
    inactive_jump_pruned: bool
    avoided_interaction_pruned: bool
    score: float
    player: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class PatchEvaluationResult:
    candidates: tuple[PatchEvaluationCandidate, ...]
    best_patch_index: int | None
    budget_exhausted: bool
    stats: PatchEvaluationStats


@dataclass(frozen=True, slots=True)
class SearchSpec:
    """Data-only description of one native Cartesian replay search."""

    mutable_frames: tuple[int, ...]
    choices: tuple[tuple[InputFrame, ...], ...]
    target_frame: int
    objective: int
    targets: tuple[tuple[float, float], ...] = ()
    trace_target: TraceTargetSpec | None = None
    x_window: tuple[float, float] | None = None
    y_window: tuple[float, float] | None = None
    required_groups: tuple[InteractionGroupSpec, ...] = ()
    avoided_groups: tuple[InteractionGroupSpec, ...] = ()
    incumbent_missing_requirements: frozenset[int] = frozenset()
    incumbent_violated_avoidances: frozenset[int] = frozenset()
    required_jump_frames: tuple[int, ...] = ()
    incumbent_missing_jump_frames: frozenset[int] = frozenset()
    ignored_jump_frames: tuple[int, ...] = ()
    minimum_jump_events: int = 0
    incumbent_score: float = float("-inf")
    incumbent_feasible: bool = False
    prune_inactive_jump: bool = False
    physics_prune: bool = False
    skip_unchanged_final_step: bool = False
    require_all_constraints: bool = False
    required_jump_any: bool = False
    tie_break_low_edit_lex: bool = False
    max_simulated_ticks: int = 0

    def __post_init__(self) -> None:
        if not self.mutable_frames:
            raise ValueError("native search requires at least one mutable frame")
        if tuple(sorted(set(self.mutable_frames))) != self.mutable_frames:
            raise ValueError("native mutable frames must be unique and sorted")
        if len(self.choices) != len(self.mutable_frames):
            raise ValueError("native search requires one choice group per mutable frame")
        if any(not group for group in self.choices):
            raise ValueError("native search choice groups must not be empty")
        if self.target_frame < self.mutable_frames[-1]:
            raise ValueError("native target frame cannot precede the search window")
        if self.objective not in (
            *_OBJECTIVES.values(),
            OBJECTIVE_TRACE_DISTANCE,
            OBJECTIVE_CONSTANT,
        ):
            raise ValueError(f"unknown native search objective {self.objective!r}")
        if self.objective == OBJECTIVE_MIN_DISTANCE and not self.targets:
            raise ValueError("min-distance native search requires target points")
        if self.objective == OBJECTIVE_TRACE_DISTANCE and self.trace_target is None:
            raise ValueError("trace-distance native search requires a trace target")
        if self.objective != OBJECTIVE_TRACE_DISTANCE and self.trace_target is not None:
            raise ValueError("a native trace target requires trace-distance objective")
        if any(len(target) != 2 for target in self.targets):
            raise ValueError("native search targets must be (x, y) pairs")
        if any(
            not math.isfinite(coordinate)
            for target in self.targets
            for coordinate in target
        ):
            raise ValueError("native search target coordinates must be finite")
        for name, window in (("x", self.x_window), ("y", self.y_window)):
            if window is not None:
                if len(window) != 2:
                    raise ValueError(
                        f"native {name} window must contain two bounds"
                    )
                if math.isnan(window[0]) or math.isnan(window[1]):
                    raise ValueError(f"native {name} window bounds cannot be NaN")
                if window[0] > window[1]:
                    raise ValueError(
                        f"native {name} window minimum exceeds maximum"
                    )
        if math.isnan(self.incumbent_score):
            raise ValueError("native incumbent score cannot be NaN")
        if not self.incumbent_missing_requirements <= frozenset(
            range(len(self.required_groups))
        ):
            raise ValueError("incumbent missing-requirement index is out of range")
        if not self.incumbent_violated_avoidances <= frozenset(
            range(len(self.avoided_groups))
        ):
            raise ValueError("incumbent violated-avoidance index is out of range")
        if tuple(sorted(set(self.required_jump_frames))) != self.required_jump_frames:
            raise ValueError("required native jump frames must be unique and sorted")
        if not self.incumbent_missing_jump_frames <= frozenset(
            self.required_jump_frames
        ):
            raise ValueError("incumbent missing jump is not a required jump frame")
        if tuple(sorted(set(self.ignored_jump_frames))) != self.ignored_jump_frames:
            raise ValueError("ignored native jump frames must be unique and sorted")
        if any(frame < 0 or frame > self.target_frame for frame in self.ignored_jump_frames):
            raise ValueError("ignored native jump frame is outside the search target")
        if self.required_jump_any and not self.required_jump_frames:
            raise ValueError("required-jump-any needs at least one accepted frame")
        if self.max_simulated_ticks < 0:
            raise ValueError("native simulation limit must be non-negative")
        if self.minimum_jump_events < 0:
            raise ValueError("native minimum jump-event count must be non-negative")

    def payload(self) -> dict[str, object]:
        """Return the plain immutable values consumed by the Cython wrapper."""
        return {
            "mutable_frames": self.mutable_frames,
            "choices": self.choices,
            "target_frame": self.target_frame,
            "objective": self.objective,
            "targets": self.targets,
            "trace_target": (
                None if self.trace_target is None else self.trace_target.payload()
            ),
            "x_window": self.x_window,
            "y_window": self.y_window,
            "required_groups": tuple(
                tuple((atom.kind, atom.index) for atom in group.alternatives)
                for group in self.required_groups
            ),
            "avoided_groups": tuple(
                tuple((atom.kind, atom.index) for atom in group.alternatives)
                for group in self.avoided_groups
            ),
            "incumbent_missing_requirements": tuple(
                sorted(self.incumbent_missing_requirements)
            ),
            "incumbent_violated_avoidances": tuple(
                sorted(self.incumbent_violated_avoidances)
            ),
            "required_jump_frames": self.required_jump_frames,
            "incumbent_missing_jump_frames": tuple(
                sorted(self.incumbent_missing_jump_frames)
            ),
            "ignored_jump_frames": self.ignored_jump_frames,
            "minimum_jump_events": self.minimum_jump_events,
            "incumbent_score": self.incumbent_score,
            "incumbent_feasible": self.incumbent_feasible,
            "prune_inactive_jump": self.prune_inactive_jump,
            "physics_prune": self.physics_prune,
            "skip_unchanged_final_step": self.skip_unchanged_final_step,
            "require_all_constraints": self.require_all_constraints,
            "required_jump_any": self.required_jump_any,
            "tie_break_low_edit_lex": self.tie_break_low_edit_lex,
            "max_simulated_ticks": self.max_simulated_ticks,
        }


@dataclass(frozen=True, slots=True)
class SearchStats:
    visited_nodes: int = 0
    evaluated_leaves: int = 0
    simulated_ticks: int = 0
    cloned_states: int = 0
    inactive_jump_prunes: int = 0
    missed_jump_prunes: int = 0
    dead_prunes: int = 0
    deduplicated_prunes: int = 0
    physics_prunes: int = 0
    avoided_interaction_prunes: int = 0

    @classmethod
    def from_mapping(cls, values: object) -> "SearchStats":
        mapping = values if isinstance(values, dict) else {}
        return cls(
            **{
                field: int(mapping.get(field, 0))
                for field in cls.__dataclass_fields__
            }
        )


@dataclass(frozen=True, slots=True)
class SearchResult:
    improved: bool
    budget_exhausted: bool
    best_inputs: tuple[InputFrame, ...]
    score: float
    feasible: bool
    missing_requirement_indices: frozenset[int]
    violated_avoidance_indices: frozenset[int]
    missing_jump_frames: frozenset[int]
    player: dict[str, object] | None
    stats: SearchStats


@dataclass(frozen=True, slots=True)
class PatternSearchSpec:
    """Data-only description of one native bounded-run pattern search.

    Python supplies the ordered inactive and active input for every frame and
    chooses the run grammar. The native kernel owns all enumeration,
    simulation, state cloning, deduplication, scoring, and ranked retention.
    """

    range_start: int
    range_end: int
    inactive_inputs: tuple[InputFrame, ...]
    active_inputs: tuple[InputFrame, ...]
    target_frame: int
    objective: int
    run_count_min: int
    run_count_max: int
    run_length_min: int
    start_max_lengths: tuple[int, ...]
    minimum_gap: int
    fixed_starts: tuple[int, ...]
    required_start_event_mask: int
    top_results: int
    targets: tuple[tuple[float, float], ...] = ()
    x_window: tuple[float, float] | None = None
    y_window: tuple[float, float] | None = None
    shard_index: int = 0
    shard_count: int = 1

    def __post_init__(self) -> None:
        if self.range_start < 0 or self.range_end < self.range_start:
            raise ValueError("native pattern range must satisfy 0 <= start <= end")
        range_length = self.range_end - self.range_start + 1
        if len(self.inactive_inputs) != range_length:
            raise ValueError(
                "native pattern search requires one inactive input per range frame"
            )
        if len(self.active_inputs) != range_length:
            raise ValueError(
                "native pattern search requires one active input per range frame"
            )
        if len(self.start_max_lengths) != range_length:
            raise ValueError(
                "native pattern search requires one maximum length per range start"
            )
        if self.target_frame < self.range_end:
            raise ValueError("native pattern target frame cannot precede its range")
        if self.objective not in _OBJECTIVES.values():
            raise ValueError(f"unknown native search objective {self.objective!r}")
        if self.objective == OBJECTIVE_MIN_DISTANCE and not self.targets:
            raise ValueError("min-distance native search requires target points")
        if any(len(target) != 2 for target in self.targets):
            raise ValueError("native search targets must be (x, y) pairs")
        if any(
            not math.isfinite(coordinate)
            for target in self.targets
            for coordinate in target
        ):
            raise ValueError("native search target coordinates must be finite")
        for name, window in (("x", self.x_window), ("y", self.y_window)):
            if window is None:
                continue
            if len(window) != 2:
                raise ValueError(f"native {name} window must contain two bounds")
            if math.isnan(window[0]) or math.isnan(window[1]):
                raise ValueError(f"native {name} window bounds cannot be NaN")
            if window[0] > window[1]:
                raise ValueError(f"native {name} window minimum exceeds maximum")
        if self.run_count_min < 1 or self.run_count_max < self.run_count_min:
            raise ValueError(
                "native pattern counts must satisfy 1 <= minimum <= maximum"
            )
        if self.run_length_min < 1:
            raise ValueError("native pattern minimum run length must be at least 1")
        if any(
            length < 0 or length > range_length - index
            for index, length in enumerate(self.start_max_lengths)
        ):
            raise ValueError("native pattern maximum run lengths are out of range")
        if self.minimum_gap < 1:
            raise ValueError(
                "native pattern minimum gap must be at least 1 inactive frame"
            )
        if tuple(sorted(set(self.fixed_starts))) != self.fixed_starts:
            raise ValueError("native fixed run starts must be unique and sorted")
        if any(
            frame < self.range_start or frame > self.range_end
            for frame in self.fixed_starts
        ):
            raise ValueError("native fixed run start lies outside the pattern range")
        if len(self.fixed_starts) > self.run_count_max:
            raise ValueError("native fixed run starts exceed the maximum run count")
        for first, second in zip(self.fixed_starts, self.fixed_starts[1:]):
            if second - first < self.run_length_min + self.minimum_gap:
                raise ValueError(
                    "native fixed run starts are too close for the minimum "
                    "length and gap"
                )
        if self.required_start_event_mask < 0:
            raise ValueError("native required start-event mask must be non-negative")
        if self.top_results < 1:
            raise ValueError("native pattern top_results must be at least 1")
        if self.shard_count < 1:
            raise ValueError("native pattern shard_count must be at least 1")
        if self.shard_index < 0 or self.shard_index >= self.shard_count:
            raise ValueError("native pattern shard_index is outside shard_count")

    def payload(self) -> dict[str, object]:
        """Return the plain immutable values consumed by the Cython wrapper."""
        return {
            "range_start": self.range_start,
            "range_end": self.range_end,
            "inactive_inputs": self.inactive_inputs,
            "active_inputs": self.active_inputs,
            "target_frame": self.target_frame,
            "objective": self.objective,
            "targets": self.targets,
            "x_window": self.x_window,
            "y_window": self.y_window,
            "run_count_min": self.run_count_min,
            "run_count_max": self.run_count_max,
            "run_length_min": self.run_length_min,
            "start_max_lengths": self.start_max_lengths,
            "minimum_gap": self.minimum_gap,
            "fixed_starts": self.fixed_starts,
            "required_start_event_mask": self.required_start_event_mask,
            "top_results": self.top_results,
            "shard_index": self.shard_index,
            "shard_count": self.shard_count,
        }


@dataclass(frozen=True, slots=True)
class PatternSearchStats:
    attempted_starts: int = 0
    successful_starts: int = 0
    evaluated_candidates: int = 0
    deduplicated_branches: int = 0
    simulated_ticks: int = 0
    cloned_states: int = 0

    @classmethod
    def from_mapping(cls, values: object) -> "PatternSearchStats":
        mapping = values if isinstance(values, dict) else {}
        return cls(
            **{
                field: int(mapping.get(field, 0))
                for field in cls.__dataclass_fields__
            }
        )

    def add(self, other: "PatternSearchStats") -> "PatternSearchStats":
        """Return the field-wise total for independently searched shards."""
        return PatternSearchStats(
            **{
                field: getattr(self, field) + getattr(other, field)
                for field in self.__dataclass_fields__
            }
        )


@dataclass(frozen=True, slots=True)
class PatternSearchCandidate:
    spans: tuple[tuple[int, int], ...]
    score: float
    player: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class PatternSearchResult:
    candidates: tuple[PatternSearchCandidate, ...]
    stats: PatternSearchStats


def compile_objective(
    name: str,
    target: TargetSelection | None,
) -> tuple[int, tuple[tuple[float, float], ...]]:
    """Compile a resolved Python objective into native scalar parameters."""
    if name not in _OBJECTIVES:
        raise ValueError(f"unknown objective {name!r}")
    if name != "min-distance":
        return _OBJECTIVES[name], ()
    if target is None or not target.targets:
        raise ValueError("min-distance objective requires a resolved target")
    return _OBJECTIVES[name], tuple((item.x, item.y) for item in target.targets)


def compile_interaction_groups(
    constraints: Sequence[InteractionRequirement | InteractionAvoidance],
) -> tuple[InteractionGroupSpec, ...]:
    """Compile stable Python interaction identities into native groups."""
    groups: list[InteractionGroupSpec] = []
    for constraint in constraints:
        alternatives: list[InteractionAtomSpec] = []
        for atom in constraint.alternatives:
            try:
                kind = _INTERACTION_KINDS[atom.kind]
            except KeyError as exc:
                raise ValueError(f"unknown interaction kind {atom.kind!r}") from exc
            index = (
                atom.state_index
                if atom.kind in ("gold", "exit-switch")
                else atom.load_index
            )
            if index is None:
                raise ValueError(f"{atom.label} has no persistent-state index")
            alternatives.append(InteractionAtomSpec(kind, index))
        groups.append(InteractionGroupSpec(tuple(alternatives)))
    return tuple(groups)


def compile_axis_window(window: AxisWindow | None) -> tuple[float, float] | None:
    return None if window is None else (window.minimum, window.maximum)


def build_direction_choices(
    frames: Sequence[InputFrame],
    mutable_frames: Sequence[int],
    objective_name: str,
) -> tuple[tuple[InputFrame, ...], ...]:
    """Build the stable, policy-selected L/N/R order for each frame."""
    if objective_name not in _OBJECTIVES:
        raise ValueError(f"unknown objective {objective_name!r}")
    groups: list[tuple[InputFrame, ...]] = []
    for frame_index in mutable_frames:
        source = frames[frame_index]
        original = source.horizontal
        favourable = (
            1
            if objective_name == "max-x"
            else -1 if objective_name == "min-x" else original
        )
        order: list[int] = []
        for horizontal in (favourable, original, 0, -favourable, -1, 0, 1):
            if horizontal in (-1, 0, 1) and horizontal not in order:
                order.append(horizontal)
        groups.append(
            tuple(
                InputFrame(
                    horizontal < 0,
                    horizontal > 0,
                    source.jump,
                    None,
                )
                for horizontal in order
            )
        )
    return tuple(groups)


def backend_info() -> dict[str, object]:
    """Return availability and ABI information for the unified search API."""
    if _search_native is None:
        return {
            "available": False,
            "backend": "unavailable",
            "error": (
                None
                if _SEARCH_LOAD_ERROR is None
                else f"{type(_SEARCH_LOAD_ERROR).__name__}: {_SEARCH_LOAD_ERROR}"
            ),
        }
    native_info = getattr(_search_native, "search_backend_info", None)
    if not callable(native_info):
        # Retain a useful ABI error for synthetic/stale modules used by callers
        # and tests, while current releases always expose search_backend_info.
        native_info = getattr(_search_native, "backend_info", None)
    info = dict(native_info()) if callable(native_info) else {}
    compatible = (
        info.get("wrapper_api") == SEARCH_WRAPPER_API
        and info.get("search_abi") == SEARCH_ABI_VERSION
        and info.get("patch_abi") == PATCH_ABI_VERSION
        and info.get("trace_abi") == TRACE_ABI_VERSION
        and info.get("analysis_abi") == ANALYSIS_ABI_VERSION
        and info.get("core_abi") == SEARCH_CORE_ABI_VERSION
    )
    info.update(
        {
            "available": compatible,
            "backend": "native-search" if compatible else "incompatible",
            "module_file": getattr(_search_native, "__file__", None),
        }
    )
    if not compatible:
        info["error"] = (
            "incompatible native search API; expected wrapper/search/core "
            f"ABI {SEARCH_WRAPPER_API}/{SEARCH_ABI_VERSION}/"
            f"{SEARCH_CORE_ABI_VERSION}, got "
            f"{info.get('wrapper_api')}/{info.get('search_abi')}/"
            f"{info.get('core_abi')}; patch ABI expected {PATCH_ABI_VERSION}, "
            f"got {info.get('patch_abi')}; trace ABI expected "
            f"{TRACE_ABI_VERSION}, got {info.get('trace_abi')}"
            f"; analysis ABI expected {ANALYSIS_ABI_VERSION}, got "
            f"{info.get('analysis_abi')}"
        )
    return info


def require_native_search() -> Any:
    """Return the compiled search module or raise an actionable error."""
    info = backend_info()
    if not info.get("available"):
        detail = info.get("error")
        detail_text = "" if not detail else f": {detail}"
        raise RuntimeError(
            "the native replay-search kernel is unavailable; run "
            "'python build_native.py' from the optimiser directory"
            f"{detail_text}"
        )
    return _search_native


def _serialise_level(level: Level) -> str:
    """Return the exact source retained when the Python level was parsed."""
    if level.source_level_string is None:
        raise ValueError(
            "native search requires a Level created by parse_level_string so "
            "its exact source level string is available"
        )
    return level.source_level_string


class NativeSearchSession:
    """Thin per-trajectory owner for native level and prefix-state caches."""

    def __init__(self, level: Level) -> None:
        native = require_native_search()
        session_type = getattr(native, "SearchSession", None)
        if session_type is None:
            raise RuntimeError(
                "the installed native extension does not contain the required search "
                "kernel; run 'python build_native.py' from the optimiser directory"
            )
        analysis_type = getattr(native, "NativeReplayAnalysis", None)
        if analysis_type is None:
            raise RuntimeError(
                "the installed native extension does not contain the required "
                "replay-analysis owner; run 'python build_native.py' from the "
                "optimiser directory"
            )
        self._analysis_type = analysis_type
        self._session = session_type(
            _serialise_level(level),
            simulate_enemies=level.simulate_enemies,
        )

    def evaluate_replay(
        self,
        frames: Sequence[InputFrame],
        *,
        trace_stride: int = 1,
    ) -> Any:
        """Return a C-owned replay analysis with lazy trajectory queries."""
        if trace_stride < 1:
            raise ValueError("trace_stride must be positive")
        evaluate = getattr(self._session, "evaluate_replay", None)
        if not callable(evaluate):
            raise RuntimeError(
                "the installed native extension does not contain the required "
                "replay-analysis kernel; run 'python build_native.py' from the "
                "optimiser directory"
            )
        analysis: Any = evaluate(frames, trace_stride=trace_stride)
        if not isinstance(analysis, self._analysis_type):
            raise RuntimeError(
                "native replay-analysis wrapper returned an invalid owner"
            )
        return analysis

    def search(
        self,
        frames: Sequence[InputFrame],
        spec: SearchSpec,
    ) -> SearchResult:
        raw: Any = self._session.search(frames, spec.payload())
        if not isinstance(raw, dict):
            raise RuntimeError("native search wrapper returned an invalid result")
        best_inputs = tuple(
            item
            if isinstance(item, InputFrame)
            else InputFrame(
                bool(item[0]),
                bool(item[1]),
                bool(item[2]),
                None if len(item) < 4 or item[3] is None else bool(item[3]),
            )
            for item in raw.get("best_inputs", ())
        )
        return SearchResult(
            improved=bool(raw.get("improved", False)),
            budget_exhausted=bool(raw.get("budget_exhausted", False)),
            best_inputs=best_inputs,
            score=float(raw.get("score", spec.incumbent_score)),
            feasible=bool(raw.get("feasible", spec.incumbent_feasible)),
            missing_requirement_indices=frozenset(
                int(index)
                for index in raw.get("missing_requirement_indices", ())
            ),
            violated_avoidance_indices=frozenset(
                int(index)
                for index in raw.get("violated_avoidance_indices", ())
            ),
            missing_jump_frames=frozenset(
                int(frame) for frame in raw.get("missing_jump_frames", ())
            ),
            player=(
                dict(raw["player"])
                if isinstance(raw.get("player"), dict)
                else None
            ),
            stats=SearchStats.from_mapping(raw.get("stats")),
        )

    def evaluate_patches(
        self,
        frames: Sequence[InputFrame],
        spec: PatchEvaluationSpec,
        cancel_event: object | None = None,
    ) -> PatchEvaluationResult:
        """Evaluate policy-supplied sparse patches in their exact order."""
        evaluate_patches = getattr(self._session, "evaluate_patches", None)
        if not callable(evaluate_patches):
            raise RuntimeError(
                "the installed native extension does not contain the required "
                "patch-evaluation kernel; run 'python build_native.py' from the "
                "optimiser directory"
            )
        payload = spec.payload()
        raw: Any = (
            evaluate_patches(frames, payload)
            if cancel_event is None
            else evaluate_patches(frames, payload, cancel_event)
        )
        if not isinstance(raw, dict):
            raise RuntimeError(
                "native patch-evaluation wrapper returned an invalid result"
            )

        candidates: list[PatchEvaluationCandidate] = []
        for raw_candidate in raw.get("candidates", ()):
            if not isinstance(raw_candidate, dict):
                raise RuntimeError(
                    "native patch-evaluation wrapper returned an invalid candidate"
                )
            has_endpoint = bool(raw_candidate.get("has_endpoint", False))
            raw_player = raw_candidate.get("player")
            if has_endpoint != isinstance(raw_player, dict):
                raise RuntimeError(
                    "native patch-evaluation wrapper returned an invalid endpoint"
                )
            feasible = bool(raw_candidate.get("feasible", False))
            if feasible and spec.capture_endpoints and not has_endpoint:
                raise RuntimeError(
                    "native patch-evaluation wrapper returned a feasible candidate "
                    "without an endpoint"
                )
            if not spec.capture_endpoints and has_endpoint:
                raise RuntimeError(
                    "native patch-evaluation wrapper materialised an unrequested "
                    "endpoint"
                )
            candidates.append(
                PatchEvaluationCandidate(
                    feasible=feasible,
                    has_endpoint=has_endpoint,
                    dead=bool(raw_candidate.get("dead", False)),
                    inactive_jump_pruned=bool(
                        raw_candidate.get("inactive_jump_pruned", False)
                    ),
                    avoided_interaction_pruned=bool(
                        raw_candidate.get("avoided_interaction_pruned", False)
                    ),
                    score=float(raw_candidate.get("score", float("inf"))),
                    player=dict(raw_player) if isinstance(raw_player, dict) else None,
                )
            )
        if len(candidates) != len(spec.patches):
            raise RuntimeError(
                "native patch-evaluation wrapper returned the wrong candidate count"
            )
        raw_best = raw.get("best_patch_index")
        best_patch_index = None if raw_best is None else int(raw_best)
        if best_patch_index is not None and (
            best_patch_index < 0
            or best_patch_index >= len(candidates)
            or not candidates[best_patch_index].feasible
        ):
            raise RuntimeError(
                "native patch-evaluation wrapper returned an invalid best index"
            )
        return PatchEvaluationResult(
            candidates=tuple(candidates),
            best_patch_index=best_patch_index,
            budget_exhausted=bool(raw.get("budget_exhausted", False)),
            stats=PatchEvaluationStats.from_mapping(raw.get("stats")),
        )

    def search_patterns(
        self,
        frames: Sequence[InputFrame],
        spec: PatternSearchSpec,
        cancel_event: object | None = None,
    ) -> PatternSearchResult:
        """Run one native bounded-run pattern search."""
        search_patterns = getattr(self._session, "search_patterns", None)
        if not callable(search_patterns):
            raise RuntimeError(
                "the installed native extension does not contain the required "
                "pattern-search kernel; run 'python build_native.py' from the "
                "optimiser directory"
            )
        payload = spec.payload()
        raw: Any = (
            search_patterns(frames, payload)
            if cancel_event is None
            else search_patterns(frames, payload, cancel_event)
        )
        if not isinstance(raw, dict):
            raise RuntimeError(
                "native pattern-search wrapper returned an invalid result"
            )

        candidates: list[PatternSearchCandidate] = []
        for raw_candidate in raw.get("candidates", ()):
            if not isinstance(raw_candidate, dict):
                raise RuntimeError(
                    "native pattern-search wrapper returned an invalid candidate"
                )
            spans: list[tuple[int, int]] = []
            for raw_span in raw_candidate.get("spans", ()):
                if not isinstance(raw_span, (tuple, list)) or len(raw_span) != 2:
                    raise RuntimeError(
                        "native pattern-search wrapper returned an invalid span"
                    )
                start = int(raw_span[0])
                length = int(raw_span[1])
                end = start + length - 1
                if (
                    start < spec.range_start
                    or start > spec.range_end
                    or length < spec.run_length_min
                    or end > spec.range_end
                    or length
                    > spec.start_max_lengths[start - spec.range_start]
                ):
                    raise RuntimeError(
                        "native pattern-search wrapper returned an out-of-range span"
                    )
                spans.append((start, length))
            raw_player = raw_candidate.get("player")
            if not spec.run_count_min <= len(spans) <= spec.run_count_max:
                raise RuntimeError(
                    "native pattern-search wrapper returned an invalid span count"
                )
            for (left_start, left_length), (right_start, _right_length) in zip(
                spans, spans[1:]
            ):
                left_end = left_start + left_length - 1
                if right_start - left_end - 1 < spec.minimum_gap:
                    raise RuntimeError(
                        "native pattern-search wrapper returned overlapping or "
                        "insufficiently separated spans"
                    )
            if not set(spec.fixed_starts) <= {start for start, _length in spans}:
                raise RuntimeError(
                    "native pattern-search wrapper omitted a fixed run start"
                )
            if not isinstance(raw_player, dict):
                raise RuntimeError(
                    "native pattern-search wrapper omitted a candidate player"
                )
            candidates.append(
                PatternSearchCandidate(
                    spans=tuple(spans),
                    score=float(raw_candidate.get("score", float("-inf"))),
                    player=dict(raw_player),
                )
            )
        return PatternSearchResult(
            candidates=tuple(candidates),
            stats=PatternSearchStats.from_mapping(raw.get("stats")),
        )

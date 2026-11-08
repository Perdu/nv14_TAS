"""Native endpoint goals shared by bounded population search and verification.

Frames are zero-based input indices: endpoint frame N means after applying input
N. Every score is higher-is-better; ``progress_key`` / ``rank_key`` are ordered
lower-is-better, with feasible candidates always preceding infeasible candidates.
The evaluator caches only an immutable input prefix. It never simulates Python
physics, requires neither exit completion nor survival after the chosen endpoint,
and scans earliest goals chronologically (arrival is not monotonic).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from collections.abc import Sequence
from typing import Any

from nv14_engine import APP_TILE_SCALE, InputFrame
from nv14_native import is_native_level, require_native
from nv14_objectives import (
    AxisWindow,
    InteractionAtom,
    InteractionAvoidance,
    InteractionRequirement,
    InteractionTarget,
    TargetSelection,
    INTERACTION_GOLD,
    INTERACTION_EXIT_SWITCH,
    INTERACTION_LOCKED_DOOR,
    INTERACTION_TRAPDOOR,
    INTERACTION_EXIT_DOOR,
)

EARLIEST_OBJECTIVES = frozenset(("earliest-arrival", "earliest-interaction"))
_OBJECTIVES = frozenset(("max-x", "min-x", "max-y", "min-y", "min-distance")) | EARLIEST_OBJECTIVES
SECONDARY_OBJECTIVES = ("max-x", "max-y", "max-vx", "max-vy",
                        "min-x", "min-y", "min-vx", "min-vy", "min-exit-distance")


def _validate_window(name: str, window: AxisWindow | None) -> None:
    if window is None:
        return
    if (math.isnan(window.minimum) or math.isnan(window.maximum)
            or window.minimum > window.maximum
            or window.minimum == math.inf or window.maximum == -math.inf):
        raise ValueError(f"{name} must be an ordered inclusive interval without NaN")


@dataclass(frozen=True, slots=True)
class RequiredJump:
    """An actual jump must begin in region during the inclusive frame interval."""
    region: tuple[float, float, float, float]
    frames: tuple[int, int]


@dataclass(frozen=True, slots=True)
class EndpointGoal:
    target_frame: int
    objective: str = "max-x"
    target: TargetSelection | None = None
    x_window: AxisWindow | None = None
    y_window: AxisWindow | None = None
    vx_window: AxisWindow | None = None
    vy_window: AxisWindow | None = None
    target_region: tuple[float, float, float, float] | None = None
    arrival_start: int = 0
    required_interactions: tuple[InteractionRequirement, ...] = ()
    avoided_interactions: tuple[InteractionAvoidance, ...] = ()
    secondary_objective: str | None = None
    interaction_target: InteractionTarget | None = None
    require_jump_region: tuple[float, float, float, float] | None = None
    require_jump_frames: tuple[int, int] | None = None
    required_jumps: tuple[RequiredJump, ...] = ()
    # Opt-in Local ranking used by random-splice EXIT; positional compatibility.
    exit_distance_tiebreak: bool = False
    # Serialized load indices; each drone must start targeting during the interval.
    required_drone_detections: tuple[int, ...] = ()
    require_drone_detection_frames: tuple[int, int] | None = None
    # Drone must never be in detection/prefire or chasing state in this interval.
    forbidden_drone_detections: tuple[int, ...] = ()
    no_drone_detection_frames: tuple[int, int] | None = None
    survive_after_goal: int = 0  # require N further live ticks after the objective
    require_region: tuple[float, float, float, float] | None = None
    require_region_frames: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.target_frame, bool) or not isinstance(self.target_frame, int) or self.target_frame < 0:
            raise ValueError("target_frame must be a non-negative integer")
        if type(self.survive_after_goal) is not int or self.survive_after_goal < 0:
            raise ValueError("survive-after-goal must be a non-negative integer")
        if self.objective not in _OBJECTIVES:
            raise ValueError(f"unknown endpoint objective {self.objective!r}")
        if self.secondary_objective is not None:
            if self.secondary_objective not in SECONDARY_OBJECTIVES:
                raise ValueError(f"unknown secondary objective {self.secondary_objective!r}")
            if not self.is_earliest:
                raise ValueError("secondary_objective requires earliest-arrival or earliest-interaction")
            if self.secondary_objective == "min-exit-distance":
                if (self.objective != "earliest-interaction"
                        or self.interaction_target is None
                        or not any(atom.kind == INTERACTION_EXIT_DOOR
                                   for atom in self.interaction_target.alternatives)):
                    raise ValueError("min-exit-distance requires earliest-interaction "
                                     "with an exit-door target (e.g. exit:0.door)")
                # Reuse the exact pre-exit-tick measurement and proximity ranking
                # already enabled by random-splice EXIT, including native plan
                # and independent verification.
                object.__setattr__(self, "exit_distance_tiebreak", True)
        if not isinstance(self.arrival_start, int) or isinstance(self.arrival_start, bool) or not 0 <= self.arrival_start <= self.target_frame:
            raise ValueError("arrival_start must be between 0 and target_frame inclusive")
        for name in ("x_window", "y_window", "vx_window", "vy_window"):
            _validate_window(name, getattr(self, name))
        if self.objective == "min-distance" and (self.target is None or not self.target.targets):
            raise ValueError("min-distance requires a nonempty resolved target")
        if self.target is not None:
            if self.objective != "min-distance":
                raise ValueError("target points/objects require the min-distance objective")
            if any(not math.isfinite(value) for item in self.target.targets for value in (item.x, item.y)):
                raise ValueError("target coordinates must be finite")
        if self.objective == "earliest-arrival":
            if self.target_region is None:
                raise ValueError("earliest-arrival requires target_region=(xmin,xmax,ymin,ymax)")
            region = tuple(float(value) for value in self.target_region)
            if (len(region) != 4 or not all(math.isfinite(value) for value in region)
                    or region[0] > region[1] or region[2] > region[3]):
                raise ValueError("target_region must contain four finite, ordered rectangle bounds")
            object.__setattr__(self, "target_region", region)
        elif self.target_region is not None:
            raise ValueError("target_region requires earliest-arrival")
        if self.arrival_start and not self.is_earliest:
            raise ValueError("arrival_start requires earliest-arrival or earliest-interaction")
        if self.objective == "earliest-interaction":
            if not isinstance(self.interaction_target, InteractionTarget):
                raise ValueError("earliest-interaction requires a resolved interaction_target")
        elif self.interaction_target is not None:
            raise ValueError("interaction_target requires earliest-interaction")
        if self.exit_distance_tiebreak and (
            self.objective != "earliest-interaction"
            or not any(atom.kind == INTERACTION_EXIT_DOOR
                       for atom in self.interaction_target.alternatives)
        ):
            raise ValueError("exit_distance_tiebreak requires an exit-door interaction target")
        if self.require_region is not None:
            region = tuple(float(v) for v in self.require_region)
            if (len(region) != 4 or not all(math.isfinite(v) for v in region)
                    or region[0] > region[1] or region[2] > region[3]):
                raise ValueError("require-region needs four finite ordered rectangle bounds")
            object.__setattr__(self, "require_region", region)
        if self.require_region_frames is not None:
            if self.require_region is None:
                raise ValueError("require-region-frames requires require-region")
            interval = tuple(self.require_region_frames)
            if (len(interval) != 2 or any(type(v) is not int for v in interval)
                    or not 0 <= interval[0] <= interval[1] <= self.target_frame):
                raise ValueError("require-region-frames must lie within target-frame")
            object.__setattr__(self, "require_region_frames", interval)
        elif self.require_region is not None:
            object.__setattr__(self, "require_region_frames", (0, self.target_frame))
        if self.require_jump_region is not None:
            region = tuple(float(v) for v in self.require_jump_region)
            if (len(region) != 4 or not all(math.isfinite(v) for v in region)
                    or region[0] > region[1] or region[2] > region[3]):
                raise ValueError("require_jump_region needs four finite ordered rectangle bounds")
            object.__setattr__(self, "require_jump_region", region)
        if self.require_jump_frames is not None:
            if self.require_jump_region is None:
                raise ValueError("require_jump_frames requires require_jump_region")
            interval = tuple(self.require_jump_frames)
            if (len(interval) != 2 or any(type(v) is not int for v in interval)
                    or not 0 <= interval[0] <= interval[1] <= self.target_frame):
                raise ValueError("require_jump_frames must be ordered non-negative integers within target_frame")
            object.__setattr__(self, "require_jump_frames", interval)
        if self.required_jumps and self.require_jump_region is not None:
            raise ValueError("use either require-jumps or the legacy single require-jump-region")
        normalised = []
        for requirement in self.required_jumps:
            if not isinstance(requirement, RequiredJump):
                raise ValueError("required_jumps entries must be RequiredJump instances")
            region = tuple(float(v) for v in requirement.region)
            interval = tuple(requirement.frames)
            if len(region) != 4 or not all(math.isfinite(v) for v in region) or region[0] > region[1] or region[2] > region[3]:
                raise ValueError("each require-jumps region needs four finite ordered bounds")
            if len(interval) != 2 or any(type(v) is not int for v in interval) or not 0 <= interval[0] <= interval[1] <= self.target_frame:
                raise ValueError("each require-jumps frames interval must be within target-frame")
            normalised.append(RequiredJump(region, interval))
        object.__setattr__(self, "required_jumps", tuple(normalised))
        drones = tuple(self.required_drone_detections)
        if len(drones) != len(set(drones)) or any(type(v) is not int or v < 0 for v in drones):
            raise ValueError("require-drone-detection needs distinct non-negative drone load indices")
        if self.require_drone_detection_frames is not None and not drones:
            raise ValueError("require-drone-detection-frames requires require-drone-detection")
        if drones:
            interval = self.require_drone_detection_frames or (0, self.target_frame)
            if (len(interval) != 2 or any(type(v) is not int for v in interval)
                    or not 0 <= interval[0] <= interval[1] <= self.target_frame):
                raise ValueError("require-drone-detection-frames must be inclusive bounds within target-frame")
            object.__setattr__(self, "require_drone_detection_frames", tuple(interval))
        object.__setattr__(self, "required_drone_detections", drones)
        forbidden = tuple(self.forbidden_drone_detections)
        if len(forbidden) != len(set(forbidden)) or any(type(v) is not int or v < 0 for v in forbidden):
            raise ValueError("no-drone-detection needs distinct non-negative drone load indices")
        if self.no_drone_detection_frames is not None and not forbidden:
            raise ValueError("no-drone-detection-frames requires no-drone-detection")
        if forbidden:
            interval = self.no_drone_detection_frames or (0, self.target_frame)
            if (len(interval) != 2 or any(type(v) is not int for v in interval)
                    or not 0 <= interval[0] <= interval[1] <= self.target_frame):
                raise ValueError("no-drone-detection-frames must be inclusive bounds within target-frame")
            object.__setattr__(self, "no_drone_detection_frames", tuple(interval))
        object.__setattr__(self, "forbidden_drone_detections", forbidden)
        object.__setattr__(self, "required_interactions", tuple(self.required_interactions))
        object.__setattr__(self, "avoided_interactions", tuple(self.avoided_interactions))

    @property
    def is_earliest(self) -> bool:
        return self.objective in EARLIEST_OBJECTIVES


@dataclass(frozen=True, slots=True)
class EndpointEvaluation:
    feasible: bool
    score: float
    frame: int
    x: float
    y: float
    vx: float
    vy: float
    missing_interactions: frozenset[InteractionRequirement]
    violated_interactions: frozenset[InteractionAvoidance]
    dead: bool
    progress_key: tuple
    state_key: bytes
    niche_key: tuple
    interaction_state: tuple[int, int, int, int] = (0, 0, 0, 0)
    contact_state: tuple = ()
    constraint_error: float = 0.0
    region_distance: float = 0.0
    terminal_frame: int = -1
    terminal_dead: bool = False
    player_snapshot: tuple = ()
    secondary_score: float = 0.0
    secondary_value: float = 0.0  # physical value; score negates it for min objectives
    interaction_events: tuple[InteractionAtom, ...] = ()
    completed_exit_index: int = -1
    target_distance: float = 0.0
    # First qualifying actual jump: (zero-based input frame, origin x, origin y).
    # This is evaluation history; state_key remains an exact physical state key.
    jump_event: tuple[int, float, float] | None = None
    missing_jump: bool = False
    jump_distance: float = 0.0
    jump_events: tuple[tuple[int, float, float] | None, ...] = ()
    missing_jump_indices: tuple[int, ...] = ()
    pre_finish_exit_distance: float | None = None
    drone_detection_frames: tuple[int | None, ...] = ()
    missing_drone_indices: tuple[int, ...] = ()
    forbidden_drone_detection_frames: tuple[int | None, ...] = ()
    violated_drone_indices: tuple[int, ...] = ()
    pending_no_drone_detection: bool = False
    missing_survival: bool = False
    missing_region: bool = False
    region_visit_frame: int | None = None

    @property
    def objective_key(self) -> tuple[float, ...]:
        """Lower-is-better objective order, excluding replay-edit tie-breaks."""
        key = (-self.score, -self.secondary_score)
        if self.pre_finish_exit_distance is not None:
            return (*key, self.pre_finish_exit_distance)
        return key

    @property
    def rank_key(self) -> tuple:
        return self.progress_key

    @property
    def objective_value(self) -> float:
        """Compatibility alias: like score this is higher-is-better."""
        return self.score


def _distance_outside(value: float, window: AxisWindow | None) -> float:
    if window is None:
        return 0.0
    return max(window.minimum - value, value - window.maximum, 0.0)


def _atom_satisfied(atom: InteractionAtom, masks: tuple[int, int, int, int],
                    completed_exit_index: int = -1) -> bool:
    if atom.kind == INTERACTION_EXIT_DOOR:
        return atom.state_index is not None and atom.state_index == completed_exit_index
    if atom.kind == INTERACTION_GOLD:
        mask, index = masks[0], atom.state_index
    elif atom.kind == INTERACTION_EXIT_SWITCH:
        mask, index = masks[1], atom.state_index
    elif atom.kind == INTERACTION_LOCKED_DOOR:
        mask, index = masks[2], atom.load_index
    elif atom.kind == INTERACTION_TRAPDOOR:
        mask, index = masks[3], atom.load_index
    else:
        raise ValueError(f"unknown interaction kind {atom.kind!r}")
    if index is None or index < 0:
        raise ValueError(f"invalid interaction index for {atom.label}")
    return bool(mask & (1 << index))


def pending_interaction_targets(target: InteractionTarget, masks: tuple[int, int, int, int],
                                completed_exit_index: int) -> tuple[InteractionAtom, ...]:
    """Objects which can still produce a fresh event; completion freezes physics."""
    if completed_exit_index >= 0:
        return ()
    return tuple(atom for atom in target.alternatives
                 if not _atom_satisfied(atom, masks, completed_exit_index))


class EndpointEvaluator:
    """Evaluate candidates using the native engine and an immutable prefix.

    ``prefix_frame`` is the first editable input index, so inputs strictly before
    it are cached. For earliest goals the cache ends no later than arrival_start
    to ensure that an event in the original prefix cannot be skipped. A changed
    cached prefix is rejected rather than silently producing an invalid result.
    """

    def __init__(self, level: object, goal: EndpointGoal,
                 source_frames: Sequence[InputFrame] = (), prefix_frame: int = 0) -> None:
        self.goal = goal
        if prefix_frame < 0 or not isinstance(prefix_frame, int):
            raise ValueError("prefix_frame must be a non-negative integer")
        if is_native_level(level):
            self.level = level
        else:
            source = getattr(level, "source_level_string", None)
            if source is None:
                raise ValueError("endpoint search requires a parsed level with its exact source string")
            self.level = require_native().parse_level_string(
                source, simulate_enemies=bool(level.simulate_enemies))
        self.source_frames = tuple(source_frames)
        prefix_frame = min(prefix_frame, goal.target_frame + 1)
        if goal.require_region is not None:
            # An event inside the cached prefix must not vanish.
            prefix_frame = min(prefix_frame, goal.require_region_frames[0])
        if goal.forbidden_drone_detections:
            # A forbidden detection anywhere in the interval must be observed.
            prefix_frame = min(prefix_frame, goal.no_drone_detection_frames[0])
        if goal.required_drone_detections:
            # Events in an immutable prefix still matter. Re-scan starting at
            # the first allowed detection tick so prefix caching cannot erase them.
            prefix_frame = min(prefix_frame, goal.require_drone_detection_frames[0])
        if goal.is_earliest:
            prefix_frame = min(prefix_frame, goal.arrival_start)
        if prefix_frame > len(self.source_frames):
            raise ValueError("cached prefix lies outside source_frames")
        self.prefix_frame = prefix_frame
        self._multiple_jumps = bool(goal.required_jumps)
        if (goal.required_drone_detections or goal.forbidden_drone_detections) and not self.level.simulate_enemies:
            raise ValueError("drone-detection conditions need simulate-enemies = true")
        self._prefix = self.level.initial_state()
        native = require_native()
        if native.backend_info().get("population_endpoint_api", 0) < 2:
            raise RuntimeError("endpoint search requires the v4.28 native extension; run 'python build_native.py'")
        self._source_key = native.population_input_key(self.source_frames)[0]
        self._descriptors = {int(item["load_index"]): item for item in self.level.object_descriptors()}
        self._has_doors = any(item["object_type"] == 9 for item in self._descriptors.values())
        self._target_positions: dict[InteractionAtom, tuple[float, float]] = {}
        # Edge-gap secondary scores subtract the collision radii, while the
        # separate pre_finish_exit_distance field retains Auto's centre metric.
        self._exit_edge_radii: dict[InteractionAtom, float] = {}
        if goal.interaction_target is not None:
            for atom in goal.interaction_target.alternatives:
                params = self._descriptors[atom.load_index]["parameters"]
                offset = 2 if atom.kind == INTERACTION_EXIT_SWITCH else 0
                position = tuple(params[offset:offset + 2])
                if len(position) != 2 or not all(math.isfinite(value) for value in position):
                    raise ValueError(f"interaction target {atom.label} needs finite coordinates")
                self._target_positions[atom] = position
                if atom.kind == INTERACTION_EXIT_DOOR and goal.secondary_objective == "min-exit-distance":
                    # NativeLevel has no static_world property. Exit-door
                    # collision radius is APP_TILE_SCALE in the shared engine;
                    # the native player snapshot provides its actual radius.
                    self._exit_edge_radii[atom] = (
                        float(self._prefix.player_snapshot()["r"]) + APP_TILE_SCALE)
        self._native_plan = self._compile_native_plan()
        self._prefix_jump = None
        if prefix_frame and not self._multiple_jumps:
            if goal.require_jump_region is None:
                self._prefix.step_many(self.source_frames[:prefix_frame], stop_on_dead=True, stop_on_complete=False)
            else:
                # One native scan per evaluator, retaining route history in the cached prefix.
                scan = self._native_plan.scan(self._prefix, self._source_key, prefix_frames=prefix_frame)
                self._prefix, self._prefix_jump = scan[0], scan[-2]
        self._prefix_dead = bool(self._prefix.player_snapshot()["dead"])

    def _compile_native_plan(self) -> Any:
        kinds = {INTERACTION_GOLD: 0, INTERACTION_EXIT_SWITCH: 1,
                 INTERACTION_LOCKED_DOOR: 2, INTERACTION_TRAPDOOR: 3,
                 INTERACTION_EXIT_DOOR: 4}
        self._reference_required = self._multiple_jumps

        def atom_spec(atom: InteractionAtom) -> tuple:
            index = (atom.load_index if atom.kind in (INTERACTION_LOCKED_DOOR, INTERACTION_TRAPDOOR)
                     else atom.state_index)
            if index is None or index < 0:
                raise ValueError(f"invalid interaction index for {atom.label}")
            item = self._descriptors.get(atom.load_index)
            params = () if item is None else item["parameters"]
            offset = 2 if atom.kind == INTERACTION_EXIT_SWITCH else 0
            position = params[offset:offset + 2]
            x, y = position if len(position) == 2 else (None, None)
            if x is not None and not all(math.isfinite(v) for v in (x, y)):
                self._reference_required = True
            return kinds[atom.kind], index, x, y

        goal = self.goal
        windows = tuple((-math.inf, math.inf) if window is None else (window.minimum, window.maximum)
                        for window in (goal.x_window, goal.y_window, goal.vx_window, goal.vy_window))
        # The reference scorer counts frozensets, including duplicate goals only
        # once. Compile coordinates and exact event identities once per worker.
        required = tuple(tuple(atom_spec(atom) for atom in item.alternatives)
                         for item in dict.fromkeys(goal.required_interactions))
        avoided = tuple(tuple(atom_spec(atom) for atom in item.alternatives)
                        for item in dict.fromkeys(goal.avoided_interactions))
        targets = (() if goal.interaction_target is None else
                   tuple(atom_spec(atom) for atom in goal.interaction_target.alternatives))
        return require_native().NativeEndpointPlan(
            target_frame=goal.target_frame, arrival_start=goal.arrival_start,
            earliest=goal.is_earliest, windows=windows, region=goal.target_region,
            required=required, avoided=avoided, targets=targets,
            jump_region=goal.require_jump_region, jump_frames=goal.require_jump_frames,
            required_drones=goal.required_drone_detections,
            drone_frames=goal.require_drone_detection_frames,
            forbidden_drones=goal.forbidden_drone_detections,
            no_drone_frames=goal.no_drone_detection_frames)

    def _interaction_snapshot(self, state: Any) -> tuple[tuple[int, int, int, int], int]:
        static = state.static_state()
        locked, traps = state.door_control_masks() if self._has_doors else (0, 0)
        masks = (int(static["collected_gold_mask"]), int(static["open_exit_mask"]), locked, traps)
        completed = int(static["completed_exit_index"]) if static["level_complete"] else -1
        return masks, completed

    def _missing_distance(self, missing: frozenset[InteractionRequirement], x: float, y: float) -> float:
        """Geometric hints only; feasibility always checks permanent exact bits."""
        total = 0.0
        for requirement in missing:
            distances = []
            for atom in requirement.alternatives:
                item = self._descriptors.get(atom.load_index)
                if item is None:
                    continue
                params = item["parameters"]
                offset = 2 if atom.kind == INTERACTION_EXIT_SWITCH else 0
                if len(params) >= offset + 2:
                    distances.append(math.hypot(x - params[offset], y - params[offset + 1]))
            if distances:
                total += min(distances)
        return total

    def _evaluate_state(self, state: Any, *, arrival_eligible: bool = True,
                        capture_state_key: bool = True,
                        previous_interactions: tuple[tuple[int, int, int, int], int] | None = None,
                        interaction_events: tuple[InteractionAtom, ...] | None = None,
                        jump_event: tuple[int, float, float] | None = None,
                        jump_events: tuple[tuple[int, float, float] | None, ...] = (),
                        drone_detection_frames: tuple[int | None, ...] = (),
                        forbidden_drone_detection_frames: tuple[int | None, ...] = (),
                        region_visit_frame: int | None = None,
                        ) -> EndpointEvaluation:
        player = state.player_snapshot()
        masks, completed = self._interaction_snapshot(state)
        x, y = player["pos"]
        ox, oy = player["oldpos"]
        vx, vy = x - ox, y - oy
        frame = int(state.frame) - 1
        finite = all(math.isfinite(value) for value in (x, y, vx, vy))
        missing = frozenset(item for item in self.goal.required_interactions
                            if not any(_atom_satisfied(atom, masks) for atom in item.alternatives))
        violated = frozenset(item for item in self.goal.avoided_interactions
                             if any(_atom_satisfied(atom, masks) for atom in item.alternatives))
        goal = self.goal
        events: tuple[InteractionAtom, ...] = ()
        pending: tuple[InteractionAtom, ...] = ()
        target_distance = 0.0
        if goal.interaction_target is not None:
            if interaction_events is not None:
                events = interaction_events
            elif previous_interactions is not None:
                events = tuple(atom for atom in goal.interaction_target.alternatives
                               if _atom_satisfied(atom, masks, completed)
                               and not _atom_satisfied(atom, *previous_interactions))
            pending = pending_interaction_targets(goal.interaction_target, masks, completed)
            if not events:
                target_distance = min((math.hypot(x - self._target_positions[atom][0],
                                                 y - self._target_positions[atom][1])
                                       for atom in pending), default=math.inf) if finite else math.inf
        if finite:
            error = sum(_distance_outside(value, window) ** 2 for value, window in (
                (x, goal.x_window), (y, goal.y_window), (vx, goal.vx_window), (vy, goal.vy_window)))
            region_distance = 0.0
            if goal.target_region is not None:
                xmin, xmax, ymin, ymax = goal.target_region
                region_distance = math.hypot(max(xmin-x, x-xmax, 0.0), max(ymin-y, y-ymax, 0.0))
            if goal.objective == "max-x":
                score = x
            elif goal.objective == "min-x":
                score = -x
            elif goal.objective == "max-y":
                score = y
            elif goal.objective == "min-y":
                score = -y
            elif goal.objective == "min-distance":
                score = -min((x-item.x)**2 + (y-item.y)**2 for item in goal.target.targets)
            else:
                score = -float(frame)
        else:
            error, region_distance, score = math.inf, math.inf, -math.inf
        missing_indices = tuple(index for index, event in enumerate(jump_events) if event is None)
        missing_drones = tuple(i for i in range(len(goal.required_drone_detections))
                               if i >= len(drone_detection_frames) or drone_detection_frames[i] is None)
        violated_drones = tuple(i for i, hit in enumerate(forbidden_drone_detection_frames)
                                if hit is not None)
        # An earliest arrival before the last forbidden tick cannot establish
        # that detection will remain absent for the whole requested interval.
        pending_no_drone = bool(goal.forbidden_drone_detections and
                                frame < goal.no_drone_detection_frames[1])
        missing_jump = bool(missing_indices) if self._multiple_jumps else (goal.require_jump_region is not None and jump_event is None)
        missing_region = goal.require_region is not None and region_visit_frame is None
        jump_distance = 0.0
        if self._multiple_jumps and finite:
            jump_distance = sum(math.hypot(max(spec.region[0]-x, x-spec.region[1], 0.0),
                                           max(spec.region[2]-y, y-spec.region[3], 0.0))
                                for index, spec in enumerate(goal.required_jumps) if index in missing_indices)
        if missing_jump and not self._multiple_jumps:
            xmin, xmax, ymin, ymax = goal.require_jump_region
            jump_distance = (math.hypot(max(xmin-x, x-xmax, 0.0), max(ymin-y, y-ymax, 0.0))
                             if finite else math.inf)
        dead = bool(player["dead"])
        at_endpoint = ((arrival_eligible and goal.arrival_start <= frame <= goal.target_frame)
                       if goal.is_earliest else frame == goal.target_frame)
        feasible = bool(at_endpoint and finite and not dead and not missing and not violated and not missing_jump and not missing_drones and not violated_drones and not pending_no_drone and not missing_region
                        and error == 0.0 and region_distance == 0.0
                        and (goal.interaction_target is None or events))
        # The native state contains the position from immediately before this
        # physics tick in player.oldpos. This is the same pre_player position
        # used by Auto's pre_finish_exit_distance, without another full replay.
        exit_distance = None
        exit_edge_gap = None
        if feasible and goal.exit_distance_tiebreak:
            door_atoms = tuple(atom for atom in events if atom.kind == INTERACTION_EXIT_DOOR)
            distances = tuple((atom, math.hypot(ox - self._target_positions[atom][0],
                                                oy - self._target_positions[atom][1]))
                              for atom in door_atoms)
            exit_distance = min((distance for _atom, distance in distances), default=None)
            if goal.secondary_objective == "min-exit-distance":
                exit_edge_gap = min((distance - self._exit_edge_radii[atom]
                                     for atom, distance in distances), default=None)
        secondary_value = secondary_score = 0.0
        if feasible:
            if goal.secondary_objective == "min-exit-distance":
                # Native oldpos is an approximate pre-step position; the exact
                # edge gap is recalculated in _exact_exit_proximity below.
                if exit_edge_gap is not None:
                    secondary_value = exit_edge_gap
                    secondary_score = -exit_edge_gap
            elif goal.secondary_objective is not None:
                direction, attribute = goal.secondary_objective.split("-", 1)
                secondary_value = {"x": x, "y": y, "vx": vx, "vy": vy}[attribute]
                secondary_score = -secondary_value if direction == "min" else secondary_value
            progress_key = (0, -score, -secondary_score)
            if exit_distance is not None:
                progress_key += (exit_distance,)
        else:
            missing_distance = self._missing_distance(missing, x, y) if finite else math.inf
            # Keep requirements/avoidances discrete, then offer useful movement
            # gradients toward satisfying the remaining exact goals. Earlier
            # surviving near-misses remain useful even if the later run dies.
            visit_distance = 0.0
            if missing_region and finite:
                xmin, xmax, ymin, ymax = goal.require_region
                visit_distance = math.hypot(max(xmin-x, x-xmax, 0.0),
                                            max(ymin-y, y-ymax, 0.0))
            progress_key = (1, len(violated) + len(violated_drones), len(missing) + (len(missing_indices) if self._multiple_jumps else int(missing_jump)) + len(missing_drones) + int(missing_region) + int(pending_no_drone), int(dead),
                            error + region_distance**2 + missing_distance**2 + target_distance**2
                            + (jump_distance**2 if missing_jump else 0.0) + visit_distance**2,
                            max(goal.arrival_start-frame, 0) if goal.is_earliest
                            else max(goal.target_frame-frame, 0), -score)
            if (goal.interaction_target is not None or goal.require_jump_region is not None
                    or self._multiple_jumps or goal.required_drone_detections or goal.forbidden_drone_detections
                    or goal.require_region is not None):
                # States after the final possible interaction cannot repair the
                # event's failed constraints. Keep its actual tick or an earlier
                # viable approach, even if requirements become true later.
                exhausted = ((goal.interaction_target is not None and not events and not pending)
                             or (missing_jump and (any(frame >= goal.required_jumps[index].frames[1]
                                                     for index in missing_indices) if self._multiple_jumps
                                            else frame >= (goal.require_jump_frames or (0, goal.target_frame))[1]))
                             or (bool(missing_drones) and frame >= goal.require_drone_detection_frames[1])
                             or bool(violated_drones)
                             or (missing_region and frame >= goal.require_region_frames[1]))
                progress_key = (progress_key[0], int(exhausted), *progress_key[1:])
        contact = (player["state"], player["in_air"], player["near_wall"],
                   player["floor_n"], player["wall_n"], player["previous_jump_held"])
        quantised = tuple(math.floor(value / step) if math.isfinite(value) else None
                          for value, step in ((x, 4.0), (y, 4.0), (vx, 0.5), (vy, 0.5)))
        niche = (*quantised, *contact, masks)
        if goal.interaction_target is not None:
            niche = (*niche, events, completed)
        if goal.required_drone_detections:
            niche = (*niche, tuple(i not in missing_drones for i in range(len(goal.required_drone_detections))))
        if goal.forbidden_drone_detections:
            niche = (*niche, tuple(i not in violated_drones for i in range(len(goal.forbidden_drone_detections))),
                     not pending_no_drone)
        if goal.require_jump_region is not None or self._multiple_jumps:
            niche = (*niche, tuple(event is not None for event in jump_events) if self._multiple_jumps else not missing_jump)
        if goal.require_region is not None:
            niche = (*niche, not missing_region)
        return EndpointEvaluation(feasible, score, frame, x, y, vx, vy, missing, violated,
                                  dead, progress_key,
                                  state.state_key() if capture_state_key else b"", niche, masks, contact,
                                  error, region_distance, frame, dead,
                                  tuple(player.items()), secondary_score, secondary_value,
                                  events, completed, target_distance, jump_event, missing_jump, jump_distance,
                                  jump_events, missing_indices, exit_distance,
                                  drone_detection_frames, missing_drones,
                                  forbidden_drone_detection_frames, violated_drones, pending_no_drone,
                                  False, missing_region, region_visit_frame)

    def _qualifying_jump(self, frame: int, jumped: bool, origin: tuple | None) -> bool:
        """Independent reference event predicate; never called by the C tick loop."""
        region = self.goal.require_jump_region
        if region is None or not jumped or origin is None:
            return False
        start, end = self.goal.require_jump_frames or (0, self.goal.target_frame)
        x, y = origin
        return (start <= frame <= end and math.isfinite(x) and math.isfinite(y)
                and region[0] <= x <= region[1] and region[2] <= y <= region[3])

    def _exact_exit_proximity(self, result: EndpointEvaluation,
                              frames: Sequence[InputFrame],
                              pre_position: tuple[float, float] | None = None) -> EndpointEvaluation:
        """Match Auto's *pre-step* exit distance, even after collision impulses.

        The post-step player's oldpos is usually the previous position, but
        wall/floor contacts may adjust it to preserve an implicit velocity.
        An exit hit is comparatively rare. Replaying only to the tick before
        that hit in the native engine gives the exact point Auto uses, while
        leaving the hot infeasible-candidate path entirely unchanged.
        """
        if not self.goal.exit_distance_tiebreak or not result.feasible:
            return result
        if pre_position is None:
            # Exact reference path / multiple-jumps fallback; ordinary native
            # scans already supplied this point without a second simulation.
            tick = result.frame
            pre = self.level.initial_state()
            if tick:
                pre.step_many(frames[:tick], stop_on_dead=True, stop_on_complete=True)
            x, y = pre.player_snapshot()["pos"]
        else:
            x, y = pre_position
        distances = tuple(
            (atom, math.hypot(x - self._target_positions[atom][0],
                              y - self._target_positions[atom][1]))
            for atom in result.interaction_events if atom.kind == INTERACTION_EXIT_DOOR
        )
        if not distances:
            return result
        distance = min(value for _atom, value in distances)
        if self.goal.secondary_objective == "min-exit-distance":
            # The secondary metric shown to users is the signed gap between
            # the two collision circles, not centre-to-centre separation.
            gap = min(value - self._exit_edge_radii[atom] for atom, value in distances)
            return replace(result, pre_finish_exit_distance=distance,
                           secondary_value=gap, secondary_score=-gap,
                           progress_key=(0, -result.score, gap))
        return replace(result, pre_finish_exit_distance=distance,
                       progress_key=(0, -result.score, -result.secondary_score, distance))

    def evaluate(self, frames: Sequence[InputFrame]) -> EndpointEvaluation:
        frames = tuple(frames)
        return self._evaluate_packed(require_native().population_input_key(frames)[0], frames)

    def _evaluate_packed(self, key: bytes, frames: tuple[InputFrame, ...]) -> EndpointEvaluation:
        """Use the already validated population key without re-encoding inputs."""
        if self.goal.target_frame >= len(key):
            raise ValueError(f"target frame {self.goal.target_frame} is outside a {len(key)}-frame replay")
        if key[:self.prefix_frame] != self._source_key[:self.prefix_frame]:
            raise ValueError("candidate changed the immutable cached prefix")
        if self._reference_required or self.goal.survive_after_goal or self.goal.require_region is not None:
            return self.evaluate_reference(frames)
        state, events, eligible, terminal_frame, terminal_dead, jump_event, ambiguous, pre_position, detections, forbidden = self._native_plan.scan(
            self._prefix, key, jump_event=self._prefix_jump, with_pre_position=True,
            with_drone_detection=True, with_no_drone_detection=True)
        if ambiguous:
            # libc hypot and Python math.hypot can differ in their final bit.
            # Re-evaluate only precision-sensitive scans with the exact original
            # scorer so the selected frame and seeded search order stay intact.
            return self.evaluate_reference(frames)
        atoms = (() if self.goal.interaction_target is None else
                 tuple(self.goal.interaction_target.alternatives[index] for index in events))
        result = self._evaluate_state(state, arrival_eligible=eligible, interaction_events=atoms,
                                      jump_event=jump_event, drone_detection_frames=detections,
                                      forbidden_drone_detection_frames=forbidden)
        if result.terminal_frame != terminal_frame or result.terminal_dead != terminal_dead:
            result = replace(result, terminal_frame=terminal_frame, terminal_dead=terminal_dead)
        return self._exact_exit_proximity(result, frames, pre_position)

    def _drone_signals(self, state: Any) -> dict[int, tuple[int, bool]]:
        """Independent, read-only scene snapshots for reference verification."""
        indices = (*self.goal.required_drone_detections, *self.goal.forbidden_drone_detections)
        if not indices:
            return {}
        return {int(item["load_index"]): (int(item["mode"]), bool(item["chasing"]))
                for item in state.scene_snapshot()["objects"]
                if item["load_index"] in indices}

    def _record_drone_detections(self, frame: int, before: dict, after: dict,
                                 recorded: list[int | None]) -> None:
        start, end = self.goal.require_drone_detection_frames
        if frame < start or frame > end:
            return
        for i, load_index in enumerate(self.goal.required_drone_detections):
            if recorded[i] is not None:
                continue
            old_mode, old_chasing = before[load_index]
            mode, chasing = after[load_index]
            if (old_mode == 0 and mode == 1) or (not old_chasing and chasing):
                recorded[i] = frame

    def _record_forbidden_drone_detections(self, frame: int, before: dict, after: dict,
                                           recorded: list[int | None]) -> None:
        start, end = self.goal.no_drone_detection_frames
        if not start <= frame <= end:
            return
        for i, load_index in enumerate(self.goal.forbidden_drone_detections):
            if recorded[i] is not None:
                continue
            # Also catch already acquired drones at the first tick in range;
            # checking transition edges alone would silently miss these.
            old_mode, old_chasing = before[load_index]
            mode, chasing = after[load_index]
            if old_mode == 1 or mode == 1 or old_chasing or chasing:
                recorded[i] = frame

    def _visits_required_region(self, state: Any, frame: int) -> bool:
        goal = self.goal
        if goal.require_region is None:
            return False
        first, last = goal.require_region_frames
        if not first <= frame <= last:
            return False
        player = state.player_snapshot()
        if player["dead"]:
            return False
        x, y = player["pos"]
        xmin, xmax, ymin, ymax = goal.require_region
        return xmin <= x <= xmax and ymin <= y <= ymax

    def _survives_after_goal(self, state: Any, frames: Sequence[InputFrame], frame: int) -> bool:
        """Require N genuine ticks after the goal, not just a non-dead endpoint.

        A completed level is terminal success. A truncated, still-live replay
        cannot prove survival through unrecorded frames. Only used when opted in.
        """
        if not self.goal.survive_after_goal:
            return True
        probe = state.clone()
        if probe.static_state()["level_complete"]:
            return True
        for next_frame in range(frame + 1, frame + self.goal.survive_after_goal + 1):
            if next_frame >= len(frames):
                return False
            step = probe.step(frames[next_frame])
            if step["dead"]:
                return False
            if probe.static_state()["level_complete"]:
                return True
        return True

    @staticmethod
    def _failed_survival(result: EndpointEvaluation) -> EndpointEvaluation:
        # Keep the valid goal score as an optimization gradient, but never
        # promote a survivor-less checkpoint as feasible or complete.
        return replace(result, feasible=False, missing_survival=True,
                       progress_key=(1, 0, 0, 0, 0, 0, -result.score))

    def _evaluate_multiple_jumps(self, frames: tuple[InputFrame, ...]) -> EndpointEvaluation:
        """Exact native-physics reference scorer for several independent jump predicates.

        Uses the native state stepping interface, not Python physics. This is a
        fallback to avoid changing the checked-in native/Cython ABI for this feature.
        Each requirement needs an actual qualifying jump; overlapping conditions
        may be satisfied by the same physical jump.
        """
        state = self.level.initial_state()
        recorded: list[tuple[int, float, float] | None] = [None] * len(self.goal.required_jumps)
        detections: list[int | None] = [None] * len(self.goal.required_drone_detections)
        forbidden: list[int | None] = [None] * len(self.goal.forbidden_drone_detections)
        previous = self._interaction_snapshot(state) if self.goal.interaction_target is not None else None
        best = None
        visit_frame = None
        dead = False
        for frame in range(self.goal.target_frame + 1):
            if dead:
                break
            before = self._drone_signals(state) if detections or forbidden else {}
            step = state.step(frames[frame])
            if detections or forbidden:
                after = self._drone_signals(state)
                if detections:
                    self._record_drone_detections(frame, before, after, detections)
                if forbidden:
                    self._record_forbidden_drone_detections(frame, before, after, forbidden)
            dead = bool(step["dead"])
            if visit_frame is None and self._visits_required_region(state, frame):
                visit_frame = frame
            if step["jumped"] and step["jump_origin"] is not None:
                x, y = step["jump_origin"]
                if math.isfinite(x) and math.isfinite(y):
                    for index, requirement in enumerate(self.goal.required_jumps):
                        lo, hi = requirement.frames
                        xmin, xmax, ymin, ymax = requirement.region
                        if (recorded[index] is None and lo <= frame <= hi
                                and xmin <= x <= xmax and ymin <= y <= ymax):
                            recorded[index] = (frame, x, y)
            if not self.goal.is_earliest:
                continue
            if frame < self.goal.arrival_start:
                if previous is not None:
                    previous = self._interaction_snapshot(state)
                continue
            candidate = self._evaluate_state(state, capture_state_key=False,
                                             previous_interactions=previous,
                                             jump_event=recorded[0], jump_events=tuple(recorded),
                                             drone_detection_frames=tuple(detections),
                                             forbidden_drone_detection_frames=tuple(forbidden),
                                             region_visit_frame=visit_frame)
            if previous is not None:
                previous = (candidate.interaction_state, candidate.completed_exit_index)
            if candidate.feasible:
                if self._survives_after_goal(state, frames, frame):
                    return replace(candidate, state_key=state.state_key(),
                                   terminal_frame=frame, terminal_dead=dead)
                candidate = self._failed_survival(candidate)
            if best is None or candidate.progress_key < best.progress_key:
                best = replace(candidate, state_key=state.state_key())
        terminal = self._evaluate_state(state, arrival_eligible=False,
                                        jump_event=recorded[0], jump_events=tuple(recorded),
                                        drone_detection_frames=tuple(detections),
                                        forbidden_drone_detection_frames=tuple(forbidden),
                                        region_visit_frame=visit_frame)
        if not self.goal.is_earliest:
            if terminal.feasible and not self._survives_after_goal(state, frames, terminal.frame):
                return self._failed_survival(terminal)
            return terminal
        if best is None:
            best = terminal
        return replace(best, terminal_frame=terminal.frame, terminal_dead=terminal.dead)

    def evaluate_reference(self, frames: Sequence[InputFrame]) -> EndpointEvaluation:
        """Original per-tick scorer, retained for verification and numeric ties."""
        frames = tuple(frames)
        if self.goal.target_frame >= len(frames):
            raise ValueError(f"target frame {self.goal.target_frame} is outside a {len(frames)}-frame replay")
        if frames[:self.prefix_frame] != self.source_frames[:self.prefix_frame]:
            raise ValueError("candidate changed the immutable cached prefix")
        if self._multiple_jumps:
            return self._exact_exit_proximity(self._evaluate_multiple_jumps(frames), frames)
        state = self._prefix.clone()
        if (not self.goal.is_earliest and self.goal.require_jump_region is None
                and not self.goal.required_drone_detections
                and not self.goal.forbidden_drone_detections
                and self.goal.require_region is None):
            if not self._prefix_dead:
                state.step_many(frames[self.prefix_frame:self.goal.target_frame+1],
                                stop_on_dead=True, stop_on_complete=False)
            result = self._evaluate_state(state)
            if result.feasible and not self._survives_after_goal(state, frames, result.frame):
                result = self._failed_survival(result)
            return self._exact_exit_proximity(result, frames)
        # Inspect every eligible input tick: entry/exit and momentum constraints
        # can become true, false and true again. Binary search is unsound here.
        best = None
        jump_event = self._prefix_jump
        visit_frame = None
        detections: list[int | None] = [None] * len(self.goal.required_drone_detections)
        forbidden: list[int | None] = [None] * len(self.goal.forbidden_drone_detections)
        dead = self._prefix_dead
        previous = self._interaction_snapshot(state) if self.goal.interaction_target is not None else None
        for frame in range(int(state.frame), self.goal.target_frame + 1):
            if dead:
                break
            before = self._drone_signals(state) if detections or forbidden else {}
            step = state.step(frames[frame])
            if detections or forbidden:
                after = self._drone_signals(state)
                if detections:
                    self._record_drone_detections(frame, before, after, detections)
                if forbidden:
                    self._record_forbidden_drone_detections(frame, before, after, forbidden)
            dead = bool(step["dead"])
            if visit_frame is None and self._visits_required_region(state, frame):
                visit_frame = frame
            if jump_event is None and self._qualifying_jump(frame, step["jumped"], step["jump_origin"]):
                jump_event = (frame, *step["jump_origin"])
            if not self.goal.is_earliest:
                continue
            if frame < self.goal.arrival_start:
                if previous is not None:
                    previous = self._interaction_snapshot(state)
                continue
            candidate = self._evaluate_state(state, capture_state_key=False, previous_interactions=previous,
                                             jump_event=jump_event,
                                             drone_detection_frames=tuple(detections),
                                             forbidden_drone_detection_frames=tuple(forbidden),
                                             region_visit_frame=visit_frame)
            if previous is not None:
                previous = (candidate.interaction_state, candidate.completed_exit_index)
            if candidate.feasible:
                if self._survives_after_goal(state, frames, frame):
                    return self._exact_exit_proximity(
                        replace(candidate, state_key=state.state_key()), frames)
                candidate = self._failed_survival(candidate)
            if best is None or candidate.progress_key < best.progress_key:
                best = replace(candidate, state_key=state.state_key())
        terminal = self._evaluate_state(state, arrival_eligible=not self.goal.is_earliest,
                                        jump_event=jump_event, drone_detection_frames=tuple(detections),
                                        forbidden_drone_detection_frames=tuple(forbidden),
                                        region_visit_frame=visit_frame)
        if not self.goal.is_earliest and terminal.feasible:
            if not self._survives_after_goal(state, frames, terminal.frame):
                terminal = self._failed_survival(terminal)
        if best is None:
            best = terminal
        return self._exact_exit_proximity(
            replace(best, terminal_frame=terminal.frame, terminal_dead=terminal.dead), frames)


def verify_endpoint(level: object, frames: Sequence[InputFrame], goal: EndpointGoal,
                    expected: EndpointEvaluation | None = None,
                    python_resimulate: bool = False) -> EndpointEvaluation:
    """Independently replay from input zero, optionally comparing Python physics.

    No continuation beyond an accepted arrival or fixed endpoint is required.
    The exact native state key catches differences in enemies, doors and all
    other simulation state, not merely player coordinates.
    """
    evaluator = EndpointEvaluator(level, goal)
    result = evaluator.evaluate_reference(frames)
    if expected is not None:
        comparable = ("feasible", "score", "secondary_score", "secondary_value", "frame", "missing_interactions", "violated_interactions", "dead", "state_key", "interaction_events", "completed_exit_index", "jump_event", "missing_jump", "jump_events", "missing_jump_indices", "drone_detection_frames", "missing_drone_indices", "forbidden_drone_detection_frames", "violated_drone_indices", "pending_no_drone_detection", "missing_survival", "missing_region", "region_visit_frame")
        mismatch = [name for name in comparable if getattr(result, name) != getattr(expected, name)]
        if mismatch:
            raise ValueError("endpoint verification mismatch: " + ", ".join(mismatch))
    if python_resimulate:
        from nv14_engine import door_control_masks, parse_level_string
        from nv14_replay import simulate_through_frame
        if is_native_level(level):
            reference_level = parse_level_string(level.level_string, simulate_enemies=level.simulate_enemies)
        else:
            reference_level = parse_level_string(level.source_level_string, simulate_enemies=level.simulate_enemies)
        previous_atoms: set[InteractionAtom] = set()
        if goal.require_jump_region is not None or goal.required_jumps:
            state = reference_level.initial_state()
            python_jump = None
            python_jumps = [None] * len(goal.required_jumps)
            for frame in range(result.frame + 1):
                if frame == result.frame and goal.interaction_target is not None:
                    previous_atoms = {atom for atom in goal.interaction_target.alternatives if atom.is_satisfied(state)}
                before = state.player.jump_events
                state.step(frames[frame], reference_level.tiles)
                if python_jump is None and evaluator._qualifying_jump(
                        frame, state.player.jump_events > before, state.player.last_jump_origin):
                    python_jump = (frame, *state.player.last_jump_origin)
                if state.player.jump_events > before and state.player.last_jump_origin is not None:
                    x, y = state.player.last_jump_origin
                    for index, requirement in enumerate(goal.required_jumps):
                        lo, hi = requirement.frames
                        xmin, xmax, ymin, ymax = requirement.region
                        if (python_jumps[index] is None and lo <= frame <= hi
                                and xmin <= x <= xmax and ymin <= y <= ymax):
                            python_jumps[index] = (frame, x, y)
            if tuple(python_jumps) != result.jump_events:
                raise ValueError("endpoint required jumps disagree with Python reference physics")
            if python_jump != result.jump_event and not goal.required_jumps:
                raise ValueError("endpoint jump event disagrees with Python reference physics")
        elif goal.interaction_target is not None and result.frame >= 0:
            state = (simulate_through_frame(reference_level, frames, result.frame - 1)
                     if result.frame else reference_level.initial_state())
            previous_atoms = {atom for atom in goal.interaction_target.alternatives if atom.is_satisfied(state)}
            state.step(frames[result.frame], reference_level.tiles)
        else:
            state = simulate_through_frame(reference_level, frames, result.frame)
        player = state.player
        locked, traps = door_control_masks(state)
        actual = (player.pos.x, player.pos.y, player.pos.x-player.oldpos.x,
                  player.pos.y-player.oldpos.y, bool(player.dead),
                  (state.static_state.collected_gold_mask, state.static_state.open_exit_mask, locked, traps),
                  state.static_state.completed_exit_index if state.static_state.level_complete else -1)
        wanted = (result.x, result.y, result.vx, result.vy, result.dead, result.interaction_state, result.completed_exit_index)
        if actual != wanted:
            raise ValueError("endpoint verification disagrees with Python reference physics")
        if goal.interaction_target is not None and result.frame >= goal.arrival_start:
            events = tuple(atom for atom in goal.interaction_target.alternatives
                           if atom not in previous_atoms and atom.is_satisfied(state))
            if events != result.interaction_events:
                raise ValueError("endpoint interaction event disagrees with Python reference physics")
    return result

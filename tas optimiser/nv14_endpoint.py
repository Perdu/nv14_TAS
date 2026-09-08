"""Native endpoint goals shared by bounded population search and verification.

Frames are zero-based input indices: endpoint frame N means after applying input
N. Every score is higher-is-better; ``progress_key`` / ``rank_key`` are ordered
lower-is-better, with feasible candidates always preceding infeasible candidates.
The evaluator caches only an immutable input prefix. It never simulates Python
physics, requires neither exit completion nor survival after the chosen endpoint,
and scans earliest-arrival goals chronologically (arrival is not monotonic).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from collections.abc import Sequence
from typing import Any

from nv14_engine import InputFrame
from nv14_native import is_native_level, require_native
from nv14_objectives import (
    AxisWindow,
    InteractionAtom,
    InteractionAvoidance,
    InteractionRequirement,
    TargetSelection,
    INTERACTION_GOLD,
    INTERACTION_EXIT_SWITCH,
    INTERACTION_LOCKED_DOOR,
    INTERACTION_TRAPDOOR,
)

_OBJECTIVES = frozenset(("max-x", "min-x", "max-y", "min-y", "min-distance", "earliest-arrival"))
SECONDARY_OBJECTIVES = ("max-x", "max-y", "max-vx", "max-vy",
                        "min-x", "min-y", "min-vx", "min-vy")


def _validate_window(name: str, window: AxisWindow | None) -> None:
    if window is None:
        return
    if (math.isnan(window.minimum) or math.isnan(window.maximum)
            or window.minimum > window.maximum
            or window.minimum == math.inf or window.maximum == -math.inf):
        raise ValueError(f"{name} must be an ordered inclusive interval without NaN")


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

    def __post_init__(self) -> None:
        if isinstance(self.target_frame, bool) or not isinstance(self.target_frame, int) or self.target_frame < 0:
            raise ValueError("target_frame must be a non-negative integer")
        if self.objective not in _OBJECTIVES:
            raise ValueError(f"unknown endpoint objective {self.objective!r}")
        if self.secondary_objective is not None:
            if self.secondary_objective not in SECONDARY_OBJECTIVES:
                raise ValueError(f"unknown secondary objective {self.secondary_objective!r}")
            if self.objective != "earliest-arrival":
                raise ValueError("secondary_objective requires earliest-arrival")
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
        elif self.target_region is not None or self.arrival_start:
            raise ValueError("target_region and arrival_start require earliest-arrival")
        object.__setattr__(self, "required_interactions", tuple(self.required_interactions))
        object.__setattr__(self, "avoided_interactions", tuple(self.avoided_interactions))


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

    @property
    def objective_key(self) -> tuple[float, float]:
        """Lower-is-better objective order, excluding replay-edit tie-breaks."""
        return (-self.score, -self.secondary_score)

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


def _atom_satisfied(atom: InteractionAtom, masks: tuple[int, int, int, int]) -> bool:
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


class EndpointEvaluator:
    """Evaluate candidates using the native engine and an immutable prefix.

    ``prefix_frame`` is the first editable input index, so inputs strictly before
    it are cached. For earliest arrival the cache ends no later than arrival_start
    to ensure that an arrival in the original prefix cannot be skipped. A changed
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
        if goal.objective == "earliest-arrival":
            prefix_frame = min(prefix_frame, goal.arrival_start)
        if prefix_frame > len(self.source_frames):
            raise ValueError("cached prefix lies outside source_frames")
        self.prefix_frame = prefix_frame
        self._prefix = self.level.initial_state()
        if not callable(getattr(self._prefix, "door_control_masks", None)):
            raise RuntimeError("endpoint search requires the v3.13 native extension; run 'python build_native.py'")
        if prefix_frame:
            self._prefix.step_many(self.source_frames[:prefix_frame], stop_on_dead=True, stop_on_complete=False)
        self._prefix_dead = bool(self._prefix.player_snapshot()["dead"])
        self._descriptors = {int(item["load_index"]): item for item in self.level.object_descriptors()}
        self._has_doors = any(item["object_type"] == 9 for item in self._descriptors.values())

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
                        capture_state_key: bool = True) -> EndpointEvaluation:
        player = state.player_snapshot()
        static = state.static_state()
        locked, traps = state.door_control_masks() if self._has_doors else (0, 0)
        masks = (int(static["collected_gold_mask"]), int(static["open_exit_mask"]), locked, traps)
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
        dead = bool(player["dead"])
        at_endpoint = ((arrival_eligible and goal.arrival_start <= frame <= goal.target_frame)
                       if goal.objective == "earliest-arrival" else frame == goal.target_frame)
        feasible = bool(at_endpoint and finite and not dead and not missing and not violated
                        and error == 0.0 and region_distance == 0.0)
        secondary_value = secondary_score = 0.0
        if feasible:
            if goal.secondary_objective is not None:
                direction, attribute = goal.secondary_objective.split("-", 1)
                secondary_value = {"x": x, "y": y, "vx": vx, "vy": vy}[attribute]
                secondary_score = -secondary_value if direction == "min" else secondary_value
            progress_key = (0, -score, -secondary_score)
        else:
            missing_distance = self._missing_distance(missing, x, y) if finite else math.inf
            # Keep requirements/avoidances discrete, then offer useful movement
            # gradients toward satisfying the remaining exact goals. Earlier
            # surviving near-misses remain useful even if the later run dies.
            progress_key = (1, len(violated), len(missing), int(dead),
                            error + region_distance**2 + missing_distance**2,
                            max(goal.arrival_start-frame, 0) if goal.objective == "earliest-arrival"
                            else max(goal.target_frame-frame, 0), -score)
        contact = (player["state"], player["in_air"], player["near_wall"],
                   player["floor_n"], player["wall_n"], player["previous_jump_held"])
        quantised = tuple(math.floor(value / step) if math.isfinite(value) else None
                          for value, step in ((x, 4.0), (y, 4.0), (vx, 0.5), (vy, 0.5)))
        niche = (*quantised, *contact, masks)
        return EndpointEvaluation(feasible, score, frame, x, y, vx, vy, missing, violated,
                                  dead, progress_key,
                                  state.state_key() if capture_state_key else b"", niche, masks, contact,
                                  error, region_distance, frame, dead,
                                  tuple(player.items()), secondary_score, secondary_value)

    def evaluate(self, frames: Sequence[InputFrame]) -> EndpointEvaluation:
        frames = tuple(frames)
        if self.goal.target_frame >= len(frames):
            raise ValueError(f"target frame {self.goal.target_frame} is outside a {len(frames)}-frame replay")
        if frames[:self.prefix_frame] != self.source_frames[:self.prefix_frame]:
            raise ValueError("candidate changed the immutable cached prefix")
        state = self._prefix.clone()
        if self.goal.objective != "earliest-arrival":
            if not self._prefix_dead:
                state.step_many(frames[self.prefix_frame:self.goal.target_frame+1],
                                stop_on_dead=True, stop_on_complete=False)
            return self._evaluate_state(state)
        # Inspect every eligible input tick: entry/exit and momentum constraints
        # can become true, false and true again. Binary search is unsound here.
        best = None
        dead = self._prefix_dead
        for frame in range(int(state.frame), self.goal.target_frame + 1):
            if dead:
                break
            dead = bool(state.step(frames[frame])["dead"])
            if frame < self.goal.arrival_start:
                continue
            candidate = self._evaluate_state(state, capture_state_key=False)
            if candidate.feasible:
                return replace(candidate, state_key=state.state_key())
            if best is None or candidate.progress_key < best.progress_key:
                best = replace(candidate, state_key=state.state_key())
        terminal = self._evaluate_state(state, arrival_eligible=False)
        if best is None:
            best = terminal
        return replace(best, terminal_frame=terminal.frame, terminal_dead=terminal.dead)


def verify_endpoint(level: object, frames: Sequence[InputFrame], goal: EndpointGoal,
                    expected: EndpointEvaluation | None = None,
                    python_resimulate: bool = False) -> EndpointEvaluation:
    """Independently replay from input zero, optionally comparing Python physics.

    No continuation beyond an accepted arrival or fixed endpoint is required.
    The exact native state key catches differences in enemies, doors and all
    other simulation state, not merely player coordinates.
    """
    result = EndpointEvaluator(level, goal).evaluate(frames)
    if expected is not None:
        comparable = ("feasible", "score", "secondary_score", "secondary_value", "frame", "missing_interactions", "violated_interactions", "dead", "state_key")
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
        state = simulate_through_frame(reference_level, frames, result.frame)
        player = state.player
        locked, traps = door_control_masks(state)
        actual = (player.pos.x, player.pos.y, player.pos.x-player.oldpos.x,
                  player.pos.y-player.oldpos.y, bool(player.dead),
                  (state.static_state.collected_gold_mask, state.static_state.open_exit_mask, locked, traps))
        wanted = (result.x, result.y, result.vx, result.vy, result.dead, result.interaction_state)
        if actual != wanted:
            raise ValueError("endpoint verification disagrees with Python reference physics")
    return result

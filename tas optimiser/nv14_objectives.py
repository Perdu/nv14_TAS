"""Objectives, targets, and persistent interaction constraints.

This module owns target resolution and target-frame evaluation shared by the
jump-pattern and local optimisers.  It intentionally has no dependency on the
CLI or either search implementation.
"""
from __future__ import annotations

import argparse
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

from nv14_engine import (
    InputFrame,
    Level,
    ObjectSpec,
    SimulationState,
    UnsupportedTileCollision,
    door_control_masks,
)
from nv14_replay import simulate_through_frame


@dataclass(slots=True)
class Evaluation:
    score: float
    state: SimulationState
    feasible: bool = True
    missing_interactions: frozenset["InteractionRequirement"] = frozenset()
    violated_interactions: frozenset["InteractionAvoidance"] = frozenset()


@dataclass(frozen=True, slots=True)
class AxisWindow:
    """Inclusive permitted interval for one target-frame coordinate."""

    minimum: float
    maximum: float

    def contains(self, value: float) -> bool:
        return self.minimum <= value <= self.maximum

    def __str__(self) -> str:
        lower = "" if self.minimum == float("-inf") else f"{self.minimum:g}"
        upper = "" if self.maximum == float("inf") else f"{self.maximum:g}"
        return f"{lower}:{upper}"


OBJECT_TYPE_NAMES: dict[int, str] = {
    0: "gold",
    1: "bounceblock",
    2: "launchpad",
    3: "turret",
    4: "floorguard",
    5: "player",
    6: "drone",
    7: "onewayplatform",
    8: "thwomp",
    9: "testdoor",
    10: "hominglauncher",
    11: "exit",
    12: "mine",
}


def _normalise_object_type_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch not in "-_ ")


OBJECT_TYPE_BY_NAME: dict[str, int] = {
    _normalise_object_type_name(name): obj_type
    for obj_type, name in OBJECT_TYPE_NAMES.items()
}


@dataclass(frozen=True, slots=True)
class TargetGeometry:
    """One point-like level target exposed to positional objectives."""

    label: str
    x: float
    y: float
    obj_type: int | None = None
    type_index: int | None = None
    anchor: str = "center"


@dataclass(frozen=True, slots=True)
class TargetSelection:
    """A resolved selector containing one target, or an explicit ``:any`` set."""

    selector: str
    targets: tuple[TargetGeometry, ...]

    def closest(self, state: SimulationState) -> tuple[TargetGeometry, float]:
        if not self.targets:
            raise ValueError("target selection is empty")
        px = state.player.pos.x
        py = state.player.pos.y
        best_target = self.targets[0]
        dx = px - best_target.x
        dy = py - best_target.y
        best_distance = dx * dx + dy * dy
        for target in self.targets[1:]:
            dx = px - target.x
            dy = py - target.y
            distance = dx * dx + dy * dy
            if distance < best_distance:
                best_target = target
                best_distance = distance
        return best_target, best_distance


INTERACTION_GOLD = "gold"
INTERACTION_EXIT_SWITCH = "exit-switch"
INTERACTION_LOCKED_DOOR = "locked-door"
INTERACTION_TRAPDOOR = "trapdoor"


@dataclass(frozen=True, slots=True)
class InteractionAtom:
    """One persistent, identity-bearing level interaction."""

    kind: str
    type_index: int
    load_index: int
    label: str
    state_index: int | None = None

    def is_satisfied(self, state: SimulationState) -> bool:
        if self.kind == INTERACTION_GOLD:
            if self.state_index is None:
                raise ValueError(f"{self.label} has no static-state index")
            return bool(
                state.static_state.collected_gold_mask & (1 << self.state_index)
            )
        if self.kind == INTERACTION_EXIT_SWITCH:
            if self.state_index is None:
                raise ValueError(f"{self.label} has no static-state index")
            return bool(state.static_state.open_exit_mask & (1 << self.state_index))
        if self.kind == INTERACTION_LOCKED_DOOR:
            opened_locked_doors, _triggered_trapdoors = door_control_masks(state)
            return bool(opened_locked_doors & (1 << self.load_index))
        if self.kind == INTERACTION_TRAPDOOR:
            _opened_locked_doors, triggered_trapdoors = door_control_masks(state)
            return bool(triggered_trapdoors & (1 << self.load_index))
        raise ValueError(f"unknown interaction kind {self.kind!r}")


@dataclass(frozen=True, slots=True)
class InteractionRequirement:
    """One required exact interaction, or an explicit ``:any`` alternative set."""

    selector: str
    alternatives: tuple[InteractionAtom, ...]

    def __post_init__(self) -> None:
        if not self.alternatives:
            raise ValueError("interaction requirement must contain at least one object")

    @property
    def display_label(self) -> str:
        if len(self.alternatives) == 1:
            return self.alternatives[0].label
        return self.selector

    def is_satisfied(self, state: SimulationState) -> bool:
        return any(atom.is_satisfied(state) for atom in self.alternatives)


@dataclass(frozen=True, slots=True)
class InteractionAvoidance:
    """One forbidden exact interaction, or an explicit ``:any`` object set."""

    selector: str
    alternatives: tuple[InteractionAtom, ...]

    def __post_init__(self) -> None:
        if not self.alternatives:
            raise ValueError("interaction avoidance must contain at least one object")

    @property
    def display_label(self) -> str:
        if len(self.alternatives) == 1:
            return self.alternatives[0].label
        return self.selector

    def is_violated(self, state: SimulationState) -> bool:
        return any(atom.is_satisfied(state) for atom in self.alternatives)


@dataclass(frozen=True, slots=True)
class _InteractionMaskGroup:
    """Bit masks for one required or forbidden interaction group.

    ``:any`` selectors are represented by the OR of their alternatives.  The
    four masks map directly to the persistent state fields exposed by the
    emulator, so checking a group needs no per-atom dispatch.
    """

    gold: int = 0
    exit_switch: int = 0
    locked_door: int = 0
    trapdoor: int = 0


@dataclass(frozen=True, slots=True)
class _CompiledInteractionConstraints:
    """Cached mask form used by the local-direction hot path."""

    requirements: tuple[InteractionRequirement, ...]
    avoidances: tuple[InteractionAvoidance, ...]
    required_masks: tuple[_InteractionMaskGroup, ...]
    avoided_masks: tuple[_InteractionMaskGroup, ...]
    avoided_gold: int
    avoided_exit_switch: int
    avoided_locked_door: int
    avoided_trapdoor: int
    needs_door_masks: bool
    needs_avoided_door_masks: bool


_EMPTY_MISSING_INTERACTIONS: frozenset[InteractionRequirement] = frozenset()
_EMPTY_VIOLATED_INTERACTIONS: frozenset[InteractionAvoidance] = frozenset()


def _interaction_mask_group(
    alternatives: Sequence[InteractionAtom],
) -> _InteractionMaskGroup:
    """Compile interaction alternatives into persistent-state bit masks."""
    gold = 0
    exit_switch = 0
    locked_door = 0
    trapdoor = 0
    for atom in alternatives:
        if atom.kind == INTERACTION_GOLD:
            if atom.state_index is None:
                raise ValueError(f"{atom.label} has no static-state index")
            gold |= 1 << atom.state_index
        elif atom.kind == INTERACTION_EXIT_SWITCH:
            if atom.state_index is None:
                raise ValueError(f"{atom.label} has no static-state index")
            exit_switch |= 1 << atom.state_index
        elif atom.kind == INTERACTION_LOCKED_DOOR:
            locked_door |= 1 << atom.load_index
        elif atom.kind == INTERACTION_TRAPDOOR:
            trapdoor |= 1 << atom.load_index
        else:
            raise ValueError(f"unknown interaction kind {atom.kind!r}")
    return _InteractionMaskGroup(gold, exit_switch, locked_door, trapdoor)


@lru_cache(maxsize=256)
def _compile_interaction_constraints(
    requirements: tuple[InteractionRequirement, ...],
    avoidances: tuple[InteractionAvoidance, ...],
) -> _CompiledInteractionConstraints:
    """Compile stable CLI interaction objects once per constraint tuple."""
    required_masks = tuple(
        _interaction_mask_group(requirement.alternatives)
        for requirement in requirements
    )
    avoided_masks = tuple(
        _interaction_mask_group(avoidance.alternatives)
        for avoidance in avoidances
    )
    avoided_gold = 0
    avoided_exit_switch = 0
    avoided_locked_door = 0
    avoided_trapdoor = 0
    for masks in avoided_masks:
        avoided_gold |= masks.gold
        avoided_exit_switch |= masks.exit_switch
        avoided_locked_door |= masks.locked_door
        avoided_trapdoor |= masks.trapdoor
    needs_door_masks = any(
        masks.locked_door or masks.trapdoor
        for masks in (*required_masks, *avoided_masks)
    )
    needs_avoided_door_masks = bool(avoided_locked_door or avoided_trapdoor)
    return _CompiledInteractionConstraints(
        requirements,
        avoidances,
        required_masks,
        avoided_masks,
        avoided_gold,
        avoided_exit_switch,
        avoided_locked_door,
        avoided_trapdoor,
        needs_door_masks,
        needs_avoided_door_masks,
    )


def _compiled_interaction_status(
    constraints: _CompiledInteractionConstraints,
    state: SimulationState,
) -> tuple[
    frozenset[InteractionRequirement],
    frozenset[InteractionAvoidance],
]:
    """Evaluate compiled hard constraints with one state-mask read."""
    if not constraints.requirements and not constraints.avoidances:
        return _EMPTY_MISSING_INTERACTIONS, _EMPTY_VIOLATED_INTERACTIONS

    collected_gold_mask = state.static_state.collected_gold_mask
    open_exit_mask = state.static_state.open_exit_mask
    opened_locked_doors = 0
    triggered_trapdoors = 0
    if constraints.needs_door_masks:
        opened_locked_doors, triggered_trapdoors = door_control_masks(state)

    missing = frozenset(
        requirement
        for requirement, masks in zip(
            constraints.requirements, constraints.required_masks
        )
        if not (
            masks.gold & collected_gold_mask
            or masks.exit_switch & open_exit_mask
            or masks.locked_door & opened_locked_doors
            or masks.trapdoor & triggered_trapdoors
        )
    )
    violated = frozenset(
        avoidance
        for avoidance, masks in zip(constraints.avoidances, constraints.avoided_masks)
        if (
            masks.gold & collected_gold_mask
            or masks.exit_switch & open_exit_mask
            or masks.locked_door & opened_locked_doors
            or masks.trapdoor & triggered_trapdoors
        )
    )
    return missing, violated


def _avoided_interactions_triggered(
    constraints: _CompiledInteractionConstraints,
    state: SimulationState,
) -> bool:
    """Return whether any persistent avoidance has become irreversible."""
    if not constraints.avoidances:
        return False
    if state.static_state.collected_gold_mask & constraints.avoided_gold:
        return True
    if state.static_state.open_exit_mask & constraints.avoided_exit_switch:
        return True
    if constraints.needs_avoided_door_masks:
        opened_locked_doors, triggered_trapdoors = door_control_masks(state)
        return bool(
            opened_locked_doors & constraints.avoided_locked_door
            or triggered_trapdoors & constraints.avoided_trapdoor
        )
    return False


def parse_target_point(text: str) -> tuple[float, float]:
    """Parse an explicit ``X,Y`` point target."""
    parts = text.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("target point must have the form X,Y")
    try:
        x, y = (float(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "target-point coordinates must be numbers"
        ) from exc
    if not math.isfinite(x) or not math.isfinite(y):
        raise argparse.ArgumentTypeError("target-point coordinates must be finite")
    return x, y


def _type_indexed_specs(level: Level, obj_type: int) -> list[tuple[int, ObjectSpec]]:
    return list(
        enumerate(spec for spec in level.all_specs if spec.obj_type == obj_type)
    )


def _geometry_for_spec(
    spec: ObjectSpec,
    *,
    type_name: str,
    type_index: int,
    anchor: str | None,
) -> TargetGeometry:
    requested_anchor = anchor or "center"
    if type_name == "exit":
        if len(spec.params) < 4:
            raise ValueError(
                f"exit:{type_index} has {len(spec.params)} parameters; expected at least 4"
            )
        if requested_anchor in ("center", "door"):
            x, y = spec.params[0:2]
            resolved_anchor = "door"
        elif requested_anchor == "switch":
            x, y = spec.params[2:4]
            resolved_anchor = "switch"
        else:
            raise ValueError(
                f"exit target has no {requested_anchor!r} anchor; use .door or .switch"
            )
    else:
        if requested_anchor != "center":
            raise ValueError(
                f"{type_name} target has no {requested_anchor!r} anchor; use .center"
            )
        if len(spec.params) < 2:
            raise ValueError(
                f"{type_name}:{type_index} has no x,y coordinate pair in its level data"
            )
        x, y = spec.params[0:2]
        resolved_anchor = "center"

    return TargetGeometry(
        label=f"{type_name}:{type_index}.{resolved_anchor}",
        x=x,
        y=y,
        obj_type=spec.obj_type,
        type_index=type_index,
        anchor=resolved_anchor,
    )


def _parse_object_selector(
    selector: str, *, option_name: str = "target-object"
) -> tuple[str, str | None, str | None]:
    """Return normalised type name, instance token, and optional anchor."""
    if not selector or selector.isspace():
        raise ValueError(f"{option_name} selector cannot be empty")
    head, colon, tail = selector.strip().partition(":")
    if "." in head:
        raise ValueError("anchored targets must use TYPE:INDEX.ANCHOR")
    type_name = _normalise_object_type_name(head)
    instance: str | None = None
    anchor: str | None = None
    if colon:
        instance, dot, anchor_text = tail.partition(".")
        if not instance:
            raise ValueError(f"{option_name} instance after ':' cannot be empty")
        if dot:
            if not anchor_text:
                raise ValueError(f"{option_name} anchor after '.' cannot be empty")
            anchor = _normalise_object_type_name(anchor_text)
    return type_name, instance, anchor


def resolve_target_object(level: Level, selector: str) -> TargetSelection:
    """Resolve ``TYPE``, ``TYPE:INDEX``, ``TYPE:INDEX.ANCHOR`` or ``TYPE:any``.

    Bare types are accepted only when exactly one matching object exists. This
    prevents a command from silently changing meaning on a level containing
    multiple objects of that type. ``switch`` is a pseudo-type exposing the
    switch anchor of every exit.
    """
    type_name, instance, anchor = _parse_object_selector(selector)

    pseudo_switch = type_name == "switch"
    if pseudo_switch:
        if anchor not in (None, "center", "switch"):
            raise ValueError("switch targets only support the .center anchor")
        obj_type = OBJECT_TYPE_BY_NAME["exit"]
        canonical_name = "switch"
    else:
        try:
            obj_type = OBJECT_TYPE_BY_NAME[type_name]
        except KeyError as exc:
            available = ", ".join(sorted(OBJECT_TYPE_BY_NAME))
            raise ValueError(
                f"unknown target-object type {type_name!r}; available types: "
                f"{available}, switch"
            ) from exc
        canonical_name = OBJECT_TYPE_NAMES[obj_type]

    indexed_specs = _type_indexed_specs(level, obj_type)
    if not indexed_specs:
        raise ValueError(f"level contains no {canonical_name} objects")

    def make_target(type_index: int, spec: ObjectSpec) -> TargetGeometry:
        if pseudo_switch:
            target = _geometry_for_spec(
                spec, type_name="exit", type_index=type_index, anchor="switch"
            )
            return TargetGeometry(
                label=f"switch:{type_index}",
                x=target.x,
                y=target.y,
                obj_type=target.obj_type,
                type_index=type_index,
                anchor="switch",
            )
        return _geometry_for_spec(
            spec,
            type_name=canonical_name,
            type_index=type_index,
            anchor=anchor,
        )

    if instance == "any":
        return TargetSelection(
            selector=selector,
            targets=tuple(
                make_target(type_index, spec) for type_index, spec in indexed_specs
            ),
        )

    if instance is None:
        if len(indexed_specs) != 1:
            examples = (
                f"{canonical_name}:0 ... {canonical_name}:{len(indexed_specs) - 1}"
            )
            raise ValueError(
                f"target {canonical_name!r} is ambiguous: {len(indexed_specs)} objects found; "
                f"use an explicit instance ({examples}) or {canonical_name}:any"
            )
        type_index, spec = indexed_specs[0]
        return TargetSelection(
            selector=selector, targets=(make_target(type_index, spec),)
        )

    try:
        requested_index = int(instance)
    except ValueError as exc:
        raise ValueError(
            f"target-object instance must be a non-negative integer or 'any', "
            f"got {instance!r}"
        ) from exc
    if requested_index < 0 or requested_index >= len(indexed_specs):
        raise ValueError(
            f"{canonical_name} index {requested_index} is out of range; "
            f"level contains {len(indexed_specs)} {canonical_name} object(s)"
        )
    type_index, spec = indexed_specs[requested_index]
    return TargetSelection(
        selector=selector, targets=(make_target(type_index, spec),)
    )


def _interaction_atom(
    kind: str,
    type_index: int,
    spec: ObjectSpec,
    *,
    state_index: int | None = None,
) -> InteractionAtom:
    if kind == INTERACTION_GOLD:
        label = f"gold:{type_index}"
    elif kind == INTERACTION_EXIT_SWITCH:
        label = f"switch:{type_index}"
    elif kind == INTERACTION_LOCKED_DOOR:
        label = f"testdoor:{type_index}"
    elif kind == INTERACTION_TRAPDOOR:
        label = f"testdoor:{type_index}"
    else:
        raise ValueError(f"unknown interaction kind {kind!r}")
    return InteractionAtom(
        kind,
        type_index,
        spec.load_index,
        label,
        state_index,
    )


def _valid_static_interaction_entries(
    level: Level,
    *,
    obj_type: int,
    kind: str,
    expected_params: int,
) -> tuple[tuple[int, ObjectSpec, InteractionAtom], ...]:
    """Return static interactions with the exact mask index used by the engine.

    StaticWorld only allocates mask bits for correctly shaped object records.
    The public selector index, however, remains the stable per-type level-data
    index and may therefore differ from the mask index after a malformed record.
    Keeping both indices prevents one bad record from making a later selector
    observe the wrong gold or exit-switch bit.
    """
    result: list[tuple[int, ObjectSpec, InteractionAtom]] = []
    state_index = 0
    for type_index, spec in _type_indexed_specs(level, obj_type):
        if len(spec.params) != expected_params:
            continue
        result.append(
            (
                type_index,
                spec,
                _interaction_atom(
                    kind,
                    type_index,
                    spec,
                    state_index=state_index,
                ),
            )
        )
        state_index += 1
    return tuple(result)


def _parse_interaction_index(
    instance: str,
    *,
    canonical_name: str,
    count: int,
    option_name: str = "require-interaction",
) -> int:
    try:
        requested_index = int(instance)
    except ValueError as exc:
        raise ValueError(
            f"{option_name} instance must be a non-negative integer or "
            f"'any', got {instance!r}"
        ) from exc
    if requested_index < 0 or requested_index >= count:
        raise ValueError(
            f"{canonical_name} index {requested_index} is out of range; "
            f"level contains {count} {canonical_name} object(s)"
        )
    return requested_index


def _resolve_static_interaction_requirement(
    level: Level,
    *,
    selector: str,
    instance: str | None,
    obj_type: int,
    canonical_name: str,
    kind: str,
    expected_params: int,
) -> InteractionRequirement:
    indexed_specs = _type_indexed_specs(level, obj_type)
    if not indexed_specs:
        raise ValueError(f"level contains no {canonical_name} objects")
    valid_entries = _valid_static_interaction_entries(
        level,
        obj_type=obj_type,
        kind=kind,
        expected_params=expected_params,
    )
    valid_by_type_index = {
        type_index: (spec, atom)
        for type_index, spec, atom in valid_entries
    }

    if instance == "any":
        if not valid_entries:
            raise ValueError(
                f"level contains no valid {canonical_name} interactions"
            )
        return InteractionRequirement(
            selector.strip(),
            tuple(atom for _type_index, _spec, atom in valid_entries),
        )
    if instance is None:
        if not valid_entries:
            raise ValueError(
                f"level contains no valid {canonical_name} interactions"
            )
        if len(valid_entries) != 1:
            examples = ", ".join(
                f"{canonical_name}:{type_index}"
                for type_index, _spec, _atom in valid_entries
            )
            raise ValueError(
                f"required interaction {canonical_name!r} is ambiguous: "
                f"{len(valid_entries)} valid objects found; use an explicit instance "
                f"({examples}) or {canonical_name}:any"
            )
        _type_index, _spec, atom = valid_entries[0]
    else:
        requested_index = _parse_interaction_index(
            instance,
            canonical_name=canonical_name,
            count=len(indexed_specs),
        )
        type_index, spec = indexed_specs[requested_index]
        entry = valid_by_type_index.get(type_index)
        if entry is None:
            type_name = OBJECT_TYPE_NAMES.get(obj_type, canonical_name)
            raise ValueError(
                f"{type_name}:{type_index} has {len(spec.params)} parameters; "
                f"expected {expected_params} for an interaction"
            )
        _spec, atom = entry
    return InteractionRequirement(
        selector.strip(),
        (atom,),
    )


def _resolve_static_interaction_avoidance(
    level: Level,
    *,
    selector: str,
    instance: str | None,
    obj_type: int,
    canonical_name: str,
    kind: str,
    expected_params: int,
) -> InteractionAvoidance:
    indexed_specs = _type_indexed_specs(level, obj_type)
    if not indexed_specs:
        raise ValueError(f"level contains no {canonical_name} objects")
    valid_entries = _valid_static_interaction_entries(
        level,
        obj_type=obj_type,
        kind=kind,
        expected_params=expected_params,
    )
    valid_by_type_index = {
        type_index: (spec, atom)
        for type_index, spec, atom in valid_entries
    }

    if instance == "any":
        if not valid_entries:
            raise ValueError(
                f"level contains no valid {canonical_name} interactions"
            )
        return InteractionAvoidance(
            selector.strip(),
            tuple(atom for _type_index, _spec, atom in valid_entries),
        )
    if instance is None:
        if not valid_entries:
            raise ValueError(
                f"level contains no valid {canonical_name} interactions"
            )
        if len(valid_entries) != 1:
            examples = ", ".join(
                f"{canonical_name}:{type_index}"
                for type_index, _spec, _atom in valid_entries
            )
            raise ValueError(
                f"avoided interaction {canonical_name!r} is ambiguous: "
                f"{len(valid_entries)} valid objects found; use an explicit instance "
                f"({examples}) or {canonical_name}:any"
            )
        _type_index, _spec, atom = valid_entries[0]
    else:
        requested_index = _parse_interaction_index(
            instance,
            canonical_name=canonical_name,
            count=len(indexed_specs),
            option_name="avoid-interaction",
        )
        type_index, spec = indexed_specs[requested_index]
        entry = valid_by_type_index.get(type_index)
        if entry is None:
            type_name = OBJECT_TYPE_NAMES.get(obj_type, canonical_name)
            raise ValueError(
                f"{type_name}:{type_index} has {len(spec.params)} parameters; "
                f"expected {expected_params} for an interaction"
            )
        _spec, atom = entry
    return InteractionAvoidance(
        selector.strip(),
        (atom,),
    )


def _locked_testdoor_atom(
    type_index: int,
    spec: ObjectSpec,
) -> InteractionAtom:
    if len(spec.params) != 9:
        raise ValueError(
            f"testdoor:{type_index} has {len(spec.params)} parameters; expected 9"
        )
    if not bool(spec.params[6]):
        kind = "trapdoor" if bool(spec.params[3]) else "ordinary proximity door"
        article = "an" if kind.startswith("ordinary") else "a"
        raise ValueError(
            f"testdoor:{type_index} is {article} {kind}, not a locked TestDoor, "
            "and has no permanent door-switch interaction"
        )
    return _interaction_atom(INTERACTION_LOCKED_DOOR, type_index, spec)


def _trapdoor_atom(
    type_index: int,
    spec: ObjectSpec,
) -> InteractionAtom:
    if len(spec.params) != 9:
        raise ValueError(
            f"testdoor:{type_index} has {len(spec.params)} parameters; expected 9"
        )
    if bool(spec.params[6]) or not bool(spec.params[3]):
        kind = "locked TestDoor" if bool(spec.params[6]) else "ordinary proximity door"
        article = "an" if kind.startswith("ordinary") else "a"
        raise ValueError(
            f"testdoor:{type_index} is {article} {kind}, not a trapdoor"
        )
    return _interaction_atom(INTERACTION_TRAPDOOR, type_index, spec)


def _persistent_testdoor_atom(
    type_index: int,
    spec: ObjectSpec,
) -> InteractionAtom:
    if len(spec.params) != 9:
        raise ValueError(
            f"testdoor:{type_index} has {len(spec.params)} parameters; expected 9"
        )
    if bool(spec.params[6]):
        return _interaction_atom(INTERACTION_LOCKED_DOOR, type_index, spec)
    if bool(spec.params[3]):
        return _interaction_atom(INTERACTION_TRAPDOOR, type_index, spec)
    raise ValueError(
        f"testdoor:{type_index} is an ordinary proximity door whose transient "
        "activation cannot be verified from the target-frame state"
    )


def resolve_interaction_requirement(
    level: Level, selector: str
) -> InteractionRequirement:
    """Resolve one persistent local-search interaction selector.

    Supported selectors are gold, exit switches, and locked TestDoor switches.
    Exact selectors identify one stable per-type object index; ``:any`` creates
    one disjunctive requirement that is satisfied by any matching object.
    """
    type_name, instance, anchor = _parse_object_selector(
        selector, option_name="require-interaction"
    )

    if type_name == "gold":
        if anchor not in (None, "center"):
            raise ValueError("gold interactions only support the .center anchor")
        return _resolve_static_interaction_requirement(
            level,
            selector=selector,
            instance=instance,
            obj_type=OBJECT_TYPE_BY_NAME["gold"],
            canonical_name="gold",
            kind=INTERACTION_GOLD,
            expected_params=2,
        )

    if type_name in ("switch", "exitswitch"):
        if anchor not in (None, "center", "switch"):
            raise ValueError("switch interactions only support the .switch anchor")
        return _resolve_static_interaction_requirement(
            level,
            selector=selector,
            instance=instance,
            obj_type=OBJECT_TYPE_BY_NAME["exit"],
            canonical_name="switch",
            kind=INTERACTION_EXIT_SWITCH,
            expected_params=4,
        )

    if type_name == "exit":
        if anchor != "switch":
            raise ValueError(
                "exit interactions must name the switch anchor, for example "
                "exit:0.switch or switch:0"
            )
        return _resolve_static_interaction_requirement(
            level,
            selector=selector,
            instance=instance,
            obj_type=OBJECT_TYPE_BY_NAME["exit"],
            canonical_name="switch",
            kind=INTERACTION_EXIT_SWITCH,
            expected_params=4,
        )

    if type_name == "testdoor":
        if anchor not in (None, "center", "switch"):
            raise ValueError("testdoor interactions only support the .switch anchor")
        indexed_specs = _type_indexed_specs(
            level, OBJECT_TYPE_BY_NAME["testdoor"]
        )
        if not indexed_specs:
            raise ValueError("level contains no testdoor objects")

        if instance == "any":
            alternatives = tuple(
                _interaction_atom(INTERACTION_LOCKED_DOOR, type_index, spec)
                for type_index, spec in indexed_specs
                if len(spec.params) == 9 and bool(spec.params[6])
            )
            if not alternatives:
                raise ValueError("level contains no locked TestDoor switches")
            return InteractionRequirement(selector.strip(), alternatives)

        if instance is None:
            locked_specs = [
                (type_index, spec)
                for type_index, spec in indexed_specs
                if len(spec.params) == 9 and bool(spec.params[6])
            ]
            if not locked_specs:
                raise ValueError("level contains no locked TestDoor switches")
            if len(locked_specs) != 1:
                examples = ", ".join(
                    f"testdoor:{type_index}" for type_index, _spec in locked_specs
                )
                raise ValueError(
                    "required interaction 'testdoor' is ambiguous: "
                    f"{len(locked_specs)} locked TestDoors found; use one of "
                    f"{examples} or testdoor:any"
                )
            type_index, spec = locked_specs[0]
        else:
            requested_index = _parse_interaction_index(
                instance,
                canonical_name="testdoor",
                count=len(indexed_specs),
            )
            type_index, spec = indexed_specs[requested_index]
        return InteractionRequirement(
            selector.strip(),
            (_locked_testdoor_atom(type_index, spec),),
        )

    raise ValueError(
        f"unsupported required interaction type {type_name!r}; use gold, "
        "switch (or exit:INDEX.switch), or a locked testdoor"
    )


def resolve_interaction_avoidance(
    level: Level, selector: str
) -> InteractionAvoidance:
    """Resolve one persistent local-search interaction that must not occur.

    Gold pickups, exit switches, locked TestDoor switches, and trapdoor
    triggers leave identity-bearing state through the target frame and can
    therefore be forbidden exactly. ``:any`` forbids interaction with every
    matching alternative: the avoidance is violated when any one is touched.
    """
    type_name, instance, anchor = _parse_object_selector(
        selector, option_name="avoid-interaction"
    )

    if type_name == "gold":
        if anchor not in (None, "center"):
            raise ValueError("gold avoidances only support the .center anchor")
        return _resolve_static_interaction_avoidance(
            level,
            selector=selector,
            instance=instance,
            obj_type=OBJECT_TYPE_BY_NAME["gold"],
            canonical_name="gold",
            kind=INTERACTION_GOLD,
            expected_params=2,
        )

    if type_name in ("switch", "exitswitch"):
        if anchor not in (None, "center", "switch"):
            raise ValueError("switch avoidances only support the .switch anchor")
        return _resolve_static_interaction_avoidance(
            level,
            selector=selector,
            instance=instance,
            obj_type=OBJECT_TYPE_BY_NAME["exit"],
            canonical_name="switch",
            kind=INTERACTION_EXIT_SWITCH,
            expected_params=4,
        )

    if type_name == "exit":
        if anchor != "switch":
            raise ValueError(
                "exit avoidances must name the switch anchor, for example "
                "exit:0.switch or switch:0"
            )
        return _resolve_static_interaction_avoidance(
            level,
            selector=selector,
            instance=instance,
            obj_type=OBJECT_TYPE_BY_NAME["exit"],
            canonical_name="switch",
            kind=INTERACTION_EXIT_SWITCH,
            expected_params=4,
        )

    if type_name in ("testdoor", "trapdoor"):
        allowed_anchors = (
            (None, "center", "trigger")
            if type_name == "trapdoor"
            else (None, "center", "switch", "trigger")
        )
        if anchor not in allowed_anchors:
            anchor_name = ".trigger" if type_name == "trapdoor" else ".switch/.trigger"
            raise ValueError(
                f"{type_name} avoidances only support the {anchor_name} anchor"
            )
        indexed_specs = _type_indexed_specs(
            level, OBJECT_TYPE_BY_NAME["testdoor"]
        )
        if not indexed_specs:
            raise ValueError("level contains no testdoor objects")

        def matching_atom(type_index: int, spec: ObjectSpec) -> InteractionAtom | None:
            if len(spec.params) != 9:
                return None
            if type_name == "trapdoor":
                if bool(spec.params[6]) or not bool(spec.params[3]):
                    return None
                return _interaction_atom(INTERACTION_TRAPDOOR, type_index, spec)
            if bool(spec.params[6]):
                return _interaction_atom(INTERACTION_LOCKED_DOOR, type_index, spec)
            if bool(spec.params[3]):
                return _interaction_atom(INTERACTION_TRAPDOOR, type_index, spec)
            return None

        matching = tuple(
            atom
            for type_index, spec in indexed_specs
            if (atom := matching_atom(type_index, spec)) is not None
        )
        canonical_name = "trapdoor" if type_name == "trapdoor" else "testdoor"

        if instance == "any":
            if not matching:
                raise ValueError(
                    f"level contains no persistent {canonical_name} interactions"
                )
            return InteractionAvoidance(selector.strip(), matching)

        if instance is None:
            if not matching:
                raise ValueError(
                    f"level contains no persistent {canonical_name} interactions"
                )
            if len(matching) != 1:
                examples = ", ".join(atom.label for atom in matching)
                raise ValueError(
                    f"avoided interaction {canonical_name!r} is ambiguous: "
                    f"{len(matching)} valid objects found; use one of {examples} "
                    f"or {canonical_name}:any"
                )
            return InteractionAvoidance(selector.strip(), (matching[0],))

        requested_index = _parse_interaction_index(
            instance,
            canonical_name="testdoor",
            count=len(indexed_specs),
            option_name="avoid-interaction",
        )
        type_index, spec = indexed_specs[requested_index]
        atom = (
            _trapdoor_atom(type_index, spec)
            if type_name == "trapdoor"
            else _persistent_testdoor_atom(type_index, spec)
        )
        return InteractionAvoidance(selector.strip(), (atom,))

    raise ValueError(
        f"unsupported avoided interaction type {type_name!r}; use gold, switch "
        "(or exit:INDEX.switch), a persistent testdoor, or trapdoor"
    )


def merge_interaction_requirements(
    *groups: Sequence[InteractionRequirement],
) -> tuple[InteractionRequirement, ...]:
    """Merge requirement groups while removing semantically identical entries."""
    result: list[InteractionRequirement] = []
    seen: set[tuple[InteractionAtom, ...]] = set()
    for group in groups:
        for requirement in group:
            semantic_key = requirement.alternatives
            if semantic_key in seen:
                continue
            seen.add(semantic_key)
            result.append(requirement)
    return tuple(result)


def merge_interaction_avoidances(
    *groups: Sequence[InteractionAvoidance],
) -> tuple[InteractionAvoidance, ...]:
    """Merge avoidance groups while removing semantically identical entries."""
    result: list[InteractionAvoidance] = []
    seen: set[tuple[InteractionAtom, ...]] = set()
    for group in groups:
        for avoidance in group:
            semantic_key = avoidance.alternatives
            if semantic_key in seen:
                continue
            seen.add(semantic_key)
            result.append(avoidance)
    return tuple(result)


def reference_interaction_requirements(
    level: Level, state: SimulationState
) -> tuple[InteractionRequirement, ...]:
    """Return exact requirements for interactions present in a reference state."""
    requirements: list[InteractionRequirement] = []
    opened_locked_doors, _triggered_trapdoors = door_control_masks(state)
    collected_gold_mask = state.static_state.collected_gold_mask
    open_exit_mask = state.static_state.open_exit_mask
    for _type_index, _spec, atom in _valid_static_interaction_entries(
        level,
        obj_type=OBJECT_TYPE_BY_NAME["gold"],
        kind=INTERACTION_GOLD,
        expected_params=2,
    ):
        assert atom.state_index is not None
        if collected_gold_mask & (1 << atom.state_index):
            requirements.append(InteractionRequirement(atom.label, (atom,)))
    for _type_index, _spec, atom in _valid_static_interaction_entries(
        level,
        obj_type=OBJECT_TYPE_BY_NAME["exit"],
        kind=INTERACTION_EXIT_SWITCH,
        expected_params=4,
    ):
        assert atom.state_index is not None
        if open_exit_mask & (1 << atom.state_index):
            requirements.append(InteractionRequirement(atom.label, (atom,)))
    for type_index, spec in _type_indexed_specs(
        level, OBJECT_TYPE_BY_NAME["testdoor"]
    ):
        if len(spec.params) != 9 or not bool(spec.params[6]):
            continue
        atom = _interaction_atom(INTERACTION_LOCKED_DOOR, type_index, spec)
        if opened_locked_doors & (1 << atom.load_index):
            requirements.append(InteractionRequirement(atom.label, (atom,)))
    return tuple(requirements)


def interaction_constraint_status(
    requirements: Sequence[InteractionRequirement],
    avoidances: Sequence[InteractionAvoidance],
    state: SimulationState,
) -> tuple[
    frozenset[InteractionRequirement],
    frozenset[InteractionAvoidance],
]:
    """Return missing requirements and violated avoidances in one state scan."""
    if not requirements and not avoidances:
        return _EMPTY_MISSING_INTERACTIONS, _EMPTY_VIOLATED_INTERACTIONS
    return _compiled_interaction_status(
        _compile_interaction_constraints(tuple(requirements), tuple(avoidances)),
        state,
    )


def missing_interaction_requirements(
    requirements: Sequence[InteractionRequirement],
    state: SimulationState,
) -> frozenset[InteractionRequirement]:
    missing, _violated = interaction_constraint_status(requirements, (), state)
    return missing


def violated_interaction_avoidances(
    avoidances: Sequence[InteractionAvoidance],
    state: SimulationState,
) -> frozenset[InteractionAvoidance]:
    _missing, violated = interaction_constraint_status((), avoidances, state)
    return violated


def _evaluation_with_interactions(
    score: float,
    state: SimulationState,
    feasible: bool,
    required_interactions: Sequence[InteractionRequirement] = (),
    avoided_interactions: Sequence[InteractionAvoidance] = (),
    *,
    compiled_constraints: _CompiledInteractionConstraints | None = None,
) -> Evaluation:
    if not required_interactions and not avoided_interactions:
        return Evaluation(
            score,
            state,
            feasible,
            _EMPTY_MISSING_INTERACTIONS,
            _EMPTY_VIOLATED_INTERACTIONS,
        )
    if compiled_constraints is None:
        compiled_constraints = _compile_interaction_constraints(
            tuple(required_interactions), tuple(avoided_interactions)
        )
    missing, violated = _compiled_interaction_status(compiled_constraints, state)
    return Evaluation(score, state, feasible, missing, violated)


def format_interaction_requirements(
    requirements: Sequence[InteractionRequirement],
) -> str:
    return ", ".join(
        requirement.display_label
        for requirement in sorted(
            requirements, key=lambda requirement: requirement.display_label
        )
    ) or "none"


def format_interaction_avoidances(
    avoidances: Sequence[InteractionAvoidance],
) -> str:
    return ", ".join(
        avoidance.display_label
        for avoidance in sorted(
            avoidances, key=lambda avoidance: avoidance.display_label
        )
    ) or "none"


def target_from_point(point: tuple[float, float]) -> TargetSelection:
    x, y = point
    return TargetSelection(
        selector=f"point:{x:g},{y:g}",
        targets=(TargetGeometry(label=f"point({x:g},{y:g})", x=x, y=y),),
    )


def format_level_objects(level: Level) -> str:
    """Human-readable stable selectors for every object in level-data order."""
    counters: dict[int, int] = {}
    lines: list[str] = []
    for spec in level.all_specs:
        type_index = counters.get(spec.obj_type, 0)
        counters[spec.obj_type] = type_index + 1
        type_name = OBJECT_TYPE_NAMES.get(spec.obj_type, f"type-{spec.obj_type}")
        params = spec.params
        if type_name == "gold" and len(params) == 2:
            lines.append(
                f"{type_name}:{type_index}  center=({params[0]:g}, {params[1]:g})  "
                f"[interaction=gold:{type_index}; "
                f"avoid-interaction=gold:{type_index}; load={spec.load_index}]"
            )
        elif type_name == "exit" and len(params) == 4:
            lines.append(
                f"{type_name}:{type_index}  door=({params[0]:g}, {params[1]:g})  "
                f"switch=({params[2]:g}, {params[3]:g})  "
                f"[interaction=switch:{type_index} or "
                f"exit:{type_index}.switch; avoid-interaction=switch:{type_index} "
                f"or exit:{type_index}.switch; load={spec.load_index}]"
            )
        elif type_name == "testdoor" and len(params) == 9:
            if bool(params[6]):
                lines.append(
                    f"{type_name}:{type_index}  locked switch="
                    f"({params[0]:g}, {params[1]:g})  "
                    f"[interaction=testdoor:{type_index}; "
                    f"avoid-interaction=testdoor:{type_index}; "
                    f"load={spec.load_index}]"
                )
            elif bool(params[3]):
                lines.append(
                    f"{type_name}:{type_index}  trapdoor trigger="
                    f"({params[0]:g}, {params[1]:g})  "
                    f"[avoid-interaction=testdoor:{type_index} or "
                    f"trapdoor:{type_index}; required interaction unsupported; "
                    f"load={spec.load_index}]"
                )
            else:
                lines.append(
                    f"{type_name}:{type_index}  ordinary proximity door  "
                    f"[persistent interaction constraints unsupported; "
                    f"load={spec.load_index}]"
                )
        elif len(params) >= 2:
            lines.append(
                f"{type_name}:{type_index}  center=({params[0]:g}, {params[1]:g})  "
                f"[load={spec.load_index}]"
            )
        else:
            raw = ",".join(f"{value:g}" for value in params)
            lines.append(
                f"{type_name}:{type_index}  params=({raw})  [load={spec.load_index}]"
            )
    return "\n".join(lines)


def objective_function(
    name: str, target: TargetSelection | None = None
) -> Callable[[SimulationState], float]:
    if name == "max-x":
        return lambda state: state.player.pos.x
    if name == "min-x":
        return lambda state: -state.player.pos.x
    if name == "max-y":
        return lambda state: state.player.pos.y
    if name == "min-y":
        return lambda state: -state.player.pos.y
    if name == "min-distance":
        if target is None:
            raise ValueError("min-distance objective requires a resolved target")
        # Negative squared Euclidean distance preserves candidate ordering while
        # avoiding a square root in the optimiser's hottest scoring path.
        return lambda state: -target.closest(state)[1]
    raise ValueError(f"unknown objective {name!r}")


def position_within_windows(
    state: SimulationState,
    *,
    x_window: AxisWindow | None = None,
    y_window: AxisWindow | None = None,
) -> bool:
    player = state.player
    return (
        (x_window is None or x_window.contains(player.pos.x))
        and (y_window is None or y_window.contains(player.pos.y))
    )


def evaluate(
    level: Level,
    frames: Sequence[InputFrame],
    target_frame: int,
    objective: Callable[[SimulationState], float],
    *,
    x_window: AxisWindow | None = None,
    y_window: AxisWindow | None = None,
    required_interactions: Sequence[InteractionRequirement] = (),
    avoided_interactions: Sequence[InteractionAvoidance] = (),
    successful_jump_frames_out: set[int] | None = None,
) -> Evaluation:
    try:
        if successful_jump_frames_out is None:
            state = simulate_through_frame(level, frames, target_frame)
        else:
            if target_frame < -1:
                raise ValueError("target_frame must be -1 or greater")
            if target_frame >= len(frames):
                raise ValueError(
                    f"target frame {target_frame} is outside a "
                    f"{len(frames)}-frame replay"
                )
            state = level.initial_state()
            for frame_index in range(target_frame + 1):
                before_events = state.player.jump_events
                state.step(frames[frame_index], level.tiles)
                if state.player.jump_events > before_events:
                    successful_jump_frames_out.add(frame_index)
                if state.player.dead:
                    break
    except UnsupportedTileCollision:
        state = level.initial_state()
        state.player.dead = True
        return _evaluation_with_interactions(
            float("-inf"), state, False,
            required_interactions, avoided_interactions,
        )
    if state.player.dead:
        return _evaluation_with_interactions(
            float("-inf"), state, False,
            required_interactions, avoided_interactions,
        )
    if not position_within_windows(
        state, x_window=x_window, y_window=y_window
    ):
        return _evaluation_with_interactions(
            float("-inf"), state, False,
            required_interactions, avoided_interactions,
        )
    return _evaluation_with_interactions(
        objective(state), state, True,
        required_interactions, avoided_interactions,
    )


def state_before_frame(
    level: Level, frames: Sequence[InputFrame], frame_index: int
) -> SimulationState:
    if frame_index == 0:
        return level.initial_state()
    return simulate_through_frame(level, frames, frame_index - 1)


def evaluate_window_candidate(
    level: Level,
    prefix_state: SimulationState,
    candidate: Sequence[InputFrame],
    suffix: Sequence[InputFrame],
    objective: Callable[[SimulationState], float],
    *,
    x_window: AxisWindow | None = None,
    y_window: AxisWindow | None = None,
    required_interactions: Sequence[InteractionRequirement] = (),
    avoided_interactions: Sequence[InteractionAvoidance] = (),
) -> Evaluation:
    state = prefix_state.clone()
    try:
        for frame in candidate:
            state.step(frame, level.tiles)
            if state.player.dead:
                return _evaluation_with_interactions(
                    float("-inf"), state, False,
                    required_interactions, avoided_interactions,
                )
        for frame in suffix:
            state.step(frame, level.tiles)
            if state.player.dead:
                return _evaluation_with_interactions(
                    float("-inf"), state, False,
                    required_interactions, avoided_interactions,
                )
    except UnsupportedTileCollision:
        return _evaluation_with_interactions(
            float("-inf"), state, False,
            required_interactions, avoided_interactions,
        )
    if not position_within_windows(
        state, x_window=x_window, y_window=y_window
    ):
        return _evaluation_with_interactions(
            float("-inf"), state, False,
            required_interactions, avoided_interactions,
        )
    return _evaluation_with_interactions(
        objective(state), state, True,
        required_interactions, avoided_interactions,
    )


def evaluate_frame_set_candidate(
    level: Level,
    prefix_state: SimulationState,
    frames: Sequence[InputFrame],
    frame_indices: Sequence[int],
    candidate: Sequence[InputFrame],
    *,
    target_frame: int,
    objective: Callable[[SimulationState], float],
    x_window: AxisWindow | None = None,
    y_window: AxisWindow | None = None,
    required_interactions: Sequence[InteractionRequirement] = (),
    avoided_interactions: Sequence[InteractionAvoidance] = (),
) -> Evaluation:
    """Evaluate replacements at selected frames while replaying gaps unchanged."""
    if not frame_indices:
        raise ValueError("frame_indices must not be empty")
    if len(frame_indices) != len(candidate):
        raise ValueError("candidate must contain one replacement per selected frame")

    state = prefix_state.clone()
    candidate_index = 0
    try:
        for frame_index in range(frame_indices[0], target_frame + 1):
            if (
                candidate_index < len(frame_indices)
                and frame_index == frame_indices[candidate_index]
            ):
                frame = candidate[candidate_index]
                candidate_index += 1
            else:
                frame = frames[frame_index]
            state.step(frame, level.tiles)
            if state.player.dead:
                return _evaluation_with_interactions(
                    float("-inf"), state, False,
                    required_interactions, avoided_interactions,
                )
    except UnsupportedTileCollision:
        return _evaluation_with_interactions(
            float("-inf"), state, False,
            required_interactions, avoided_interactions,
        )

    if not position_within_windows(
        state, x_window=x_window, y_window=y_window
    ):
        return _evaluation_with_interactions(
            float("-inf"), state, False,
            required_interactions, avoided_interactions,
        )
    return _evaluation_with_interactions(
        objective(state), state, True,
        required_interactions, avoided_interactions,
    )

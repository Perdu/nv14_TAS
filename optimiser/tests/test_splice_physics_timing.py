"""Physics-aware seam timing and exact interaction identity regression tests."""
from dataclasses import replace
import random

from nv14_auto import RouteControlEvent
from nv14_random_splice import (
    RandomSpliceConfig, Waypoint, _candidate_seams, _physics_deadline,
    _physics_event_tick, choose_waypoints,
)
from tests.test_splice_modes import _long_reference


def test_physics_can_consider_a_delayed_seam_but_random_cannot():
    reference, _ = _long_reference(110)
    trace = list(reference.trace)
    # Same physical reference state reached five ticks later.
    for tick in range(45, 65):
        trace[tick] = replace(trace[tick], x=float(tick - 5))
    candidate = replace(reference, trace=tuple(trace))
    anchor = Waypoint(50, 50., 110., kind="switch", mandatory=True,
                      target_index=0)
    physics = RandomSpliceConfig(mode="physics", lookback=32)
    ordinary = RandomSpliceConfig(lookback=32)
    assert _physics_deadline(anchor, 110, physics) > anchor.frame
    assert _physics_deadline(anchor, 110, ordinary) == anchor.frame
    assert (55, 50) in _candidate_seams(reference, candidate, anchor, 55, physics)
    assert all(t < r for t, r in _candidate_seams(reference, candidate, anchor, 55, ordinary))


def test_switch_event_identity_is_not_just_matching_index():
    reference, _ = _long_reference(100)
    reference = replace(reference, route_control_events=(
        RouteControlEvent("locked-door", 0, 40), RouteControlEvent("exit", 0, 50)))
    exit_switch = Waypoint(50, 50., 110., True, "switch", 0, source_kind="exit")
    locked = replace(exit_switch, source_kind="locked-door")
    assert _physics_event_tick(reference, exit_switch, 0, 55, 12) == 50
    assert _physics_event_tick(reference, locked, 0, 55, 12) == 40
    assert _physics_event_tick(reference, exit_switch, 0, 45, 12) is None


def test_optional_skip_preserves_all_mandatory_switches():
    reference, _ = _long_reference(180)
    reference = replace(reference, route_control_events=(
        RouteControlEvent("exit", 0, 30), RouteControlEvent("exit", 1, 85)))
    config = RandomSpliceConfig(mode="physics", points=1,
                                physics_skip_probability=1)
    result = choose_waypoints(reference, config, random.Random(12))
    assert {(w.frame, w.target_index) for w in result if w.mandatory} == {
        (30, 0), (85, 1)}


def test_bounceblocks_are_opt_in_only():
    config = RandomSpliceConfig(mode="physics")
    assert "bounceblock" not in config.physics_interactions
    assert "switch" in config.physics_interactions

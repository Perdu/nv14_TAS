from __future__ import annotations

from dataclasses import replace
import math

import pytest

from nv14_engine import InputFrame, parse_level_string
from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_native import require_native
from nv14_objectives import (
    AxisWindow, TargetGeometry, TargetSelection,
    resolve_interaction_avoidance, resolve_interaction_requirement,
)

EMPTY_MAP = "0" * (31 * 23)


def level(objects=""):
    return parse_level_string(EMPTY_MAP + "|5^100,100" + ("!" + objects if objects else ""))


def right(count):
    return (InputFrame(right=True),) * count


def test_fixed_endpoint_uses_inclusive_input_frame_and_current_verlet_velocity():
    source = level()
    frames = right(30)
    goal = EndpointGoal(9, "max-x")
    actual = EndpointEvaluator(source, goal).evaluate(frames)
    state = require_native().parse_level_string(source.source_level_string).initial_state()
    state.step_many(frames[:10])
    snapshot = state.player_snapshot()
    assert actual.frame == 9
    assert actual.x == snapshot["pos"][0]
    assert actual.vx == snapshot["pos"][0] - snapshot["oldpos"][0]
    assert actual.vy == snapshot["pos"][1] - snapshot["oldpos"][1]
    assert actual.feasible
    assert verify_endpoint(source, frames, goal, expected=actual, python_resimulate=True) == actual
    constrained = replace(goal, vx_window=AxisWindow(actual.vx, actual.vx), vy_window=AxisWindow(actual.vy, actual.vy))
    assert EndpointEvaluator(source, constrained).evaluate(frames).feasible
    outside = replace(goal, vx_window=AxisWindow(actual.vx + .01, math.inf))
    assert not EndpointEvaluator(source, outside).evaluate(frames).feasible


def test_earliest_arrival_scans_nonmonotonic_membership_and_ignores_later_death():
    source = level()
    frames = right(120)  # leaves the region, eventually dies at the level boundary
    at_three = EndpointEvaluator(source, EndpointGoal(3)).evaluate(frames)
    goal = EndpointGoal(119, "earliest-arrival", target_region=(at_three.x, at_three.x, 0, 600))
    arrival = EndpointEvaluator(source, goal).evaluate(frames)
    assert arrival.feasible and arrival.frame == 3
    assert not arrival.dead
    assert EndpointEvaluator(source, EndpointGoal(119)).evaluate(frames).dead
    assert verify_endpoint(source, frames, goal, expected=arrival, python_resimulate=True) == arrival


def test_earliest_arrival_requires_every_constraint_at_the_accepted_tick():
    source = level("0^120,105")
    frames = right(35)
    required = resolve_interaction_requirement(source, "gold:0")
    broad = EndpointGoal(34, "earliest-arrival", target_region=(0, 700, 0, 600))
    unconstrained = EndpointEvaluator(source, broad).evaluate(frames)
    assert unconstrained.frame == 0
    goal = replace(broad, required_interactions=(required,), vx_window=AxisWindow(.8, math.inf))
    arrival = EndpointEvaluator(source, goal).evaluate(frames)
    assert arrival.feasible and arrival.frame > 0
    assert not arrival.missing_interactions and arrival.vx >= .8
    for frame in range(arrival.frame):
        earlier = EndpointEvaluator(source, replace(goal, target_frame=frame)).evaluate(frames)
        assert not earlier.feasible
    assert verify_endpoint(source, frames, goal, expected=arrival, python_resimulate=True) == arrival
    avoid = resolve_interaction_avoidance(source, "gold:0")
    contradictory = EndpointEvaluator(source, replace(goal, avoided_interactions=(avoid,))).evaluate(frames)
    assert not contradictory.feasible


def test_earliest_region_windows_and_arrival_start_are_inclusive():
    source = level()
    frames = right(30)
    goal = EndpointGoal(29, "earliest-arrival", arrival_start=12, target_region=(0, 700, 0, 600))
    result = EndpointEvaluator(source, goal, frames, prefix_frame=20).evaluate(frames)
    assert result.feasible and result.frame == 12
    assert result == verify_endpoint(source, frames, goal)
    impossible = replace(goal, y_window=AxisWindow(0, 1))
    assert not EndpointEvaluator(source, impossible).evaluate(frames).feasible


def test_prefix_cache_parity_and_immutability_including_existing_gold():
    source = level("0^100,100")
    frames = right(25)
    required = resolve_interaction_requirement(source, "gold:0")
    goal = EndpointGoal(24, "min-y", required_interactions=(required,))
    evaluator = EndpointEvaluator(source, goal, frames, prefix_frame=15)
    cached = evaluator.evaluate(frames)
    assert cached.feasible and not cached.missing_interactions
    assert cached == verify_endpoint(source, frames, goal, python_resimulate=True)
    with pytest.raises(ValueError, match="immutable cached prefix"):
        evaluator.evaluate((InputFrame(left=True),) + frames[1:])
    earliest = EndpointGoal(24, "earliest-arrival", target_region=(0, 700, 0, 600))
    assert EndpointEvaluator(source, earliest, frames, prefix_frame=15).evaluate(frames).frame == 0


def test_earliest_miss_retains_best_approach_before_later_death():
    source = level()
    frames = right(120)
    goal = EndpointGoal(119, "earliest-arrival", target_region=(125, 125, 10, 10))
    result = EndpointEvaluator(source, goal).evaluate(frames)
    assert not result.feasible and not result.dead
    assert result.terminal_dead and result.terminal_frame > result.frame
    assert result.region_distance > 0
    assert verify_endpoint(source, frames, goal, expected=result) == result


def test_locked_door_masks_keep_serialized_id_above_64():
    source = level("!".join(["0^500,500"] * 70 + ["9^100,100,0,0,20,20,1,0,0"]))
    required = resolve_interaction_requirement(source, "testdoor:0")
    assert required.alternatives[0].load_index > 64
    frames = right(3)
    goal = EndpointGoal(2, required_interactions=(required,))
    result = EndpointEvaluator(source, goal).evaluate(frames)
    assert result.feasible
    assert result.interaction_state[2] == 1 << required.alternatives[0].load_index
    verify_endpoint(source, frames, goal, expected=result, python_resimulate=True)


def test_trapdoor_avoidance_uses_permanent_trigger_mask():
    source = level("9^100,100,0,1,20,20,0,0,0")
    avoid = resolve_interaction_avoidance(source, "trapdoor:0")
    frames = right(3)
    goal = EndpointGoal(2, avoided_interactions=(avoid,))
    result = EndpointEvaluator(source, goal).evaluate(frames)
    assert not result.feasible and result.violated_interactions == frozenset((avoid,))
    verify_endpoint(source, frames, goal, expected=result, python_resimulate=True)


def test_min_distance_uses_existing_squared_distance_score_and_exact_verification():
    source = level()
    frames = right(4)
    target = TargetSelection("point", (TargetGeometry("point", 130, 140),))
    goal = EndpointGoal(3, "min-distance", target=target)
    result = EndpointEvaluator(source, goal).evaluate(frames)
    assert result.score == -((result.x-130)**2 + (result.y-140)**2)
    with pytest.raises(ValueError, match="verification mismatch"):
        verify_endpoint(source, frames, goal, expected=replace(result, score=result.score+1))


@pytest.mark.parametrize("kwargs", [
    {"target_frame": -1}, {"target_frame": True},
    {"target_frame": 3, "objective": "min-distance"},
    {"target_frame": 3, "objective": "earliest-arrival"},
    {"target_frame": 3, "objective": "earliest-arrival", "target_region": (1, 0, 0, 1)},
    {"target_frame": 3, "objective": "earliest-arrival", "target_region": (0, math.inf, 0, 1)},
    {"target_frame": 3, "vx_window": AxisWindow(math.nan, 1)},
    {"target_frame": 3, "vy_window": AxisWindow(2, 1)},
    {"target_frame": 3, "arrival_start": 2},
])
def test_invalid_goal_values_fail_before_search(kwargs):
    with pytest.raises(ValueError):
        EndpointGoal(**kwargs)

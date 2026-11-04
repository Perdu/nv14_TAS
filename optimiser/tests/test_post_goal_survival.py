"""Post-objective survival, independent of any later optional splice helper."""
from dataclasses import replace

import pytest

from nv14_engine import InputFrame, parse_level_string
from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_cli import parse_arguments

LEVEL = '0' * (31 * 23) + '|5^100,100'


def test_survival_rejects_death_after_an_otherwise_valid_checkpoint():
    level = parse_level_string(LEVEL)
    frames = (InputFrame(right=True),) * 120
    goal = EndpointGoal(60, 'max-x')
    assert EndpointEvaluator(level, goal).evaluate(frames).feasible
    guarded = replace(goal, survive_after_goal=40)
    actual = EndpointEvaluator(level, guarded).evaluate(frames)
    assert not actual.feasible and actual.missing_survival and not actual.dead
    assert verify_endpoint(level, frames, guarded, expected=actual) == actual
    assert EndpointEvaluator(level, replace(goal, survive_after_goal=10)).evaluate(frames).feasible


def test_survival_requires_recorded_frames_not_optimistic_truncation():
    level = parse_level_string(LEVEL)
    goal = EndpointGoal(5, survive_after_goal=4)
    assert not EndpointEvaluator(level, goal).evaluate((InputFrame(),) * 6).feasible
    assert EndpointEvaluator(level, goal).evaluate((InputFrame(),) * 10).feasible


def test_survival_earliest_goal_cannot_accept_fatal_early_arrival():
    level = parse_level_string(LEVEL)
    frames = (InputFrame(right=True),) * 120
    goal = EndpointGoal(85, 'earliest-arrival', target_region=(0, 700, 0, 600), survive_after_goal=100)
    result = EndpointEvaluator(level, goal).evaluate(frames)
    assert not result.feasible and result.missing_survival
    verify_endpoint(level, frames, goal, expected=result)


def test_survival_option_validation_and_config(tmp_path):
    with pytest.raises(ValueError, match='survive-after-goal'):
        EndpointGoal(10, survive_after_goal=-1)
    with pytest.raises(ValueError, match='survive-after-goal'):
        EndpointGoal(10, survive_after_goal=True)
    file = tmp_path / 'endpoint.toml'
    file.write_text('[goal]\nobjective = "max-x"\ntarget-frame = 10\nsurvive-after-goal = 7\n')
    # [goal] is mapped through the same shared config loader.
    local = parse_arguments(['local', 'level.ltm', '--config', str(file), '--search', 'population'])
    assert local.survive_after_goal == 7
    auto = parse_arguments(['auto', 'level.ltm', '--config', str(file)])
    assert auto.auto_survive_after_goal == 7

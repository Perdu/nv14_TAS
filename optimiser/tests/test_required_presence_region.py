"""A required physical visit is independent of jump events and goal position."""
import pytest

from nv14_auto import evaluate_replay_with_sentinel
from nv14_cli import parse_arguments
from nv14_endpoint import EndpointGoal, EndpointEvaluator, verify_endpoint
from tests.test_random_splice import _baseline


def test_visit_during_interval_is_required_and_independently_verified():
    level, frames, _ = _baseline()
    point = evaluate_replay_with_sentinel(level, frames).point(8)
    region = (point.x - 0.2, point.x + 0.2, point.y - 0.2, point.y + 0.2)
    goal = EndpointGoal(20, 'max-x', require_region=region, require_region_frames=(7, 9))
    found = EndpointEvaluator(level, goal).evaluate(frames)
    assert found.feasible and not found.missing_region and found.region_visit_frame == 8
    assert verify_endpoint(level, frames, goal, expected=found) == found
    missed = EndpointGoal(20, 'max-x', require_region=region, require_region_frames=(10, 12))
    result = EndpointEvaluator(level, missed).evaluate(frames)
    assert not result.feasible and result.missing_region


def test_required_region_validation():
    with pytest.raises(ValueError, match='requires require-region'):
        EndpointGoal(20, 'max-x', require_region_frames=(1, 3))
    with pytest.raises(ValueError, match='within target-frame'):
        EndpointGoal(20, 'max-x', require_region=(1, 2, 3, 4), require_region_frames=(1, 21))
    with pytest.raises(ValueError, match='ordered'):
        EndpointGoal(20, 'max-x', require_region=(2, 1, 3, 4))


def test_cli_and_goal_toml_accept_presence_region(tmp_path):
    goal = tmp_path / 'goal.txt'
    goal.write_text('[local]\nobjective="max-x"\nsearch="population"\n'
                    'target-frame=20\nrequire-region="65:66,133:135"\n'
                    'require-region-frames="7:9"\n')
    auto = parse_arguments(['auto', 'in.ltm', '--goal-config', str(goal)])
    assert auto.auto_require_region == (65.0, 66.0, 133.0, 135.0)
    assert auto.auto_require_region_frames == (7, 9)
    local = parse_arguments(['local', 'in.ltm', '--config', str(goal)])
    assert local.require_region == (65.0, 66.0, 133.0, 135.0)
    assert local.require_region_frames == (7, 9)

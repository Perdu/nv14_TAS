"""Velocity can be the primary endpoint objective at one tick or in an interval."""
from pathlib import Path

import pytest

from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_objectives import AxisWindow
from nv14_cli import _load_config_defaults, _load_local_goal_defaults, build_parser
from tests.test_random_splice import _baseline


def test_fixed_velocity_scores_and_signs():
    level, frames, _ = _baseline()
    for objective, component, sign in (
            ('max-vx', 'vx', 1), ('min-vx', 'vx', -1),
            ('max-vy', 'vy', 1), ('min-vy', 'vy', -1)):
        goal = EndpointGoal(20, objective)
        value = EndpointEvaluator(level, goal).evaluate(frames)
        assert value.feasible and value.frame == 20
        assert value.score == pytest.approx(sign * getattr(value, component))
        verify_endpoint(level, frames, goal, expected=value)


def test_velocity_interval_picks_best_qualifying_tick_and_verifies():
    level, frames, _ = _baseline()
    for objective in ('max-vx', 'min-vx', 'max-vy', 'min-vy'):
        goal = EndpointGoal(25, objective, velocity_frames=(4, 20))
        measured = EndpointEvaluator(level, goal).evaluate(frames)
        assert measured.feasible and 4 <= measured.frame <= 20
        scores = [EndpointEvaluator(level, EndpointGoal(frame, objective)).evaluate(frames).score
                  for frame in range(4, 21)]
        assert measured.score == pytest.approx(max(scores))
        verify_endpoint(level, frames, goal, expected=measured)
    # An explicit window also applies inside the interval.
    limited = EndpointGoal(25, 'max-vx', velocity_frames=(4, 20),
                           vx_window=AxisWindow(-10.0, 2.0))
    result = EndpointEvaluator(level, limited).evaluate(frames)
    assert result.feasible and result.vx <= 2
    verify_endpoint(level, frames, limited, expected=result)


def test_velocity_frame_bounds_and_prefix_cache():
    level, frames, _ = _baseline()
    for window in ((-1, 5), (4, 30), (10, 9)):
        with pytest.raises(ValueError, match='velocity-frames'):
            EndpointGoal(25, 'max-vx', velocity_frames=window)
    with pytest.raises(ValueError, match='velocity-frames'):
        EndpointGoal(25, 'max-x', velocity_frames=(0, 25))
    goal = EndpointGoal(25, 'max-vx', velocity_frames=(4, 20))
    cached = EndpointEvaluator(level, goal, frames, prefix_frame=15)
    assert cached.prefix_frame == 4
    assert cached.evaluate(frames).objective_key == EndpointEvaluator(level, goal).evaluate(frames).objective_key


def test_local_and_named_splice_toml_parsing(tmp_path):
    cfg = tmp_path / 'goal.txt'
    cfg.write_text('[local]\nobjective="max-vy"\nsearch="population"\n'
                   'target-frame=25\nvelocity-frames="4:20"\n')
    parser = build_parser()
    parsed, _ = _load_config_defaults(cfg, parser._command_parsers['local'], 'local')
    assert parsed['velocity_frames'] == (4, 20)
    converted = _load_local_goal_defaults(cfg, parser._command_parsers['local'])
    assert converted['auto_velocity_frames'] == (4, 20)
    args = parser.parse_args(['local', 'example.txt', '--objective', 'max-vx',
                              '--search', 'population', '--velocity-frames', '5:18'])
    assert args.velocity_frames == (5, 18)

"""Velocity can be the primary endpoint objective at one tick or in an interval."""
from pathlib import Path

import pytest

from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_objectives import AxisWindow
from nv14_cli import (
    _load_config_defaults, _load_local_goal_defaults, _load_named_splice_stages,
    build_parser, parse_arguments,
)
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


def test_velocity_region_must_contain_the_scored_tick_not_just_an_earlier_visit():
    level, frames, _ = _baseline()
    ticks = {frame: EndpointEvaluator(level, EndpointGoal(frame, 'max-vx')).evaluate(frames)
             for frame in range(4, 21)}
    # Without the rectangle the fastest tick is 20. The rectangle only
    # includes earlier positions, so the fastest qualifying tick is 14.
    region = (ticks[9].x - .01, ticks[14].x + .01,
              ticks[14].y - .01, ticks[14].y + .01)
    goal = EndpointGoal(25, 'max-vx', velocity_frames=(4, 20), target_region=region)
    selected = EndpointEvaluator(level, goal, frames, prefix_frame=17).evaluate(frames)
    assert selected.feasible and selected.frame == 14
    assert selected.score == pytest.approx(ticks[14].score)
    assert selected.score < ticks[20].score  # never score an outside-region peak
    verify_endpoint(level, frames, goal, expected=selected)
    # A visit outside the velocity interval is not sufficient either.
    unreachable = EndpointGoal(25, 'max-vx', velocity_frames=(4, 20),
                               target_region=(0, 800, 200, 220))
    missed = EndpointEvaluator(level, unreachable).evaluate(frames)
    assert not missed.feasible
    assert missed.region_distance > 0
    verify_endpoint(level, frames, unreachable, expected=missed)


def test_fixed_tick_region_conditions_native_velocity_and_position():
    level, frames, _ = _baseline()
    at_ten = EndpointEvaluator(level, EndpointGoal(10, 'max-vx')).evaluate(frames)
    inside = (at_ten.x - .01, at_ten.x + .01, at_ten.y - .01, at_ten.y + .01)
    for objective in ('max-vx', 'max-x'):
        goal = EndpointGoal(10, objective, target_region=inside)
        candidate = EndpointEvaluator(level, goal).evaluate(frames)
        assert candidate.feasible and candidate.frame == 10
        assert candidate.region_distance == 0
        verify_endpoint(level, frames, goal, expected=candidate)
        outside = EndpointGoal(10, objective, target_region=(0, 5, 0, 5))
        missed = EndpointEvaluator(level, outside).evaluate(frames)
        assert not missed.feasible and missed.region_distance > 0
        verify_endpoint(level, frames, outside, expected=missed)


def test_named_splice_max_vx_region_and_velocity_window_are_accepted(tmp_path):
    level, frames, _ = _baseline()
    (tmp_path / '456.txt').write_text(
        '[local]\nsearch = "population"\ntarget_frame = 456\n'
        'range = "336:456"\nsimulate-enemies = false\n'
        'objective = "max-vx"\ntarget_region = "247:273,546:586"\n'
        'velocity-frames = "426:435"\n')
    args = parse_arguments(['auto', 'input.txt'])
    stages = _load_named_splice_stages(level, frames, args, tmp_path, ('456',))
    assert len(stages) == 1
    stage = stages[0]
    assert stage.goal.objective == 'max-vx'
    assert stage.goal.target_region == (247., 273., 546., 586.)
    assert stage.goal.velocity_frames == (426, 435)
    assert stage.goal.target_frame == 456
    assert stage.start == 336 and stage.end == 456
    assert stage.simulate_enemies is False

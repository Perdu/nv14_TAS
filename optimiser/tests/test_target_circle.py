"""Circular earliest-arrival targets must use exact geometry in native and Python."""
from dataclasses import replace
import math

import pytest

import optimize_replay as opt
from nv14_cli import LocalConfig, parse_target_circle, _auto_goal_from_options
from nv14_endpoint import EndpointGoal, EndpointEvaluator, verify_endpoint
from nv14_engine import InputFrame, parse_level_string


def _level():
    return parse_level_string('0' * (31 * 23) + '|5^100,100')


def test_circle_parser_default_radius_and_invalid_values():
    assert parse_target_circle('305,237') == (305., 237., 10.)
    assert parse_target_circle('305,237,12') == (305., 237., 12.)
    assert parse_target_circle(' 305 , 237 , 3.5 ') == (305., 237., 3.5)
    for invalid in ('', '305', '305,237,', '305,237,-1', '305,237,0',
                    '305,237,inf', 'nan,237', '305,237,12,4', 'a,237'):
        with pytest.raises(ValueError, match='target-circle'):
            parse_target_circle(invalid)


def test_circle_is_exact_not_its_bounding_rectangle_and_respects_arrival_start():
    source = _level()
    frames = (InputFrame(right=True),) * 20
    point = EndpointEvaluator(source, EndpointGoal(10)).evaluate(frames)
    # The current point lies inside the box x+-8,y+-8 but outside radius 10.
    cx, cy = point.x + 8., point.y + 8.
    box = EndpointGoal(10, 'earliest-arrival', arrival_start=10,
                       target_region=(cx-10, cx+10, cy-10, cy+10))
    circle = EndpointGoal(10, 'earliest-arrival', arrival_start=10,
                          target_circle=(cx, cy, 10.))
    assert EndpointEvaluator(source, box).evaluate(frames).feasible
    missed = EndpointEvaluator(source, circle).evaluate(frames)
    assert not missed.feasible
    assert missed.region_distance == pytest.approx(math.hypot(8, 8) - 10)
    assert verify_endpoint(source, frames, circle, expected=missed, python_resimulate=True) == missed

    # When a target is reached exactly at its centre it must be accepted by
    # the native earliest-arrival scanner and independently re-simulated.
    centred = replace(circle, target_circle=(point.x, point.y, 10.))
    hit = EndpointEvaluator(source, centred).evaluate(frames)
    assert hit.feasible and hit.frame == 10 and hit.region_distance == 0.0
    assert verify_endpoint(source, frames, centred, expected=hit, python_resimulate=True) == hit


@pytest.mark.parametrize('kwargs', [
    {'objective': 'earliest-arrival', 'target_circle': (1, 2, 0)},
    {'objective': 'earliest-arrival', 'target_circle': (1, 2, -1)},
    {'objective': 'earliest-arrival', 'target_circle': (1, 2, math.inf)},
    {'objective': 'earliest-arrival', 'target_circle': (1, 2)},
    {'objective': 'earliest-arrival', 'target_circle': (1, 2, 10),
     'target_region': (0, 3, 0, 3)},
    {'objective': 'max-x', 'target_circle': (1, 2, 10)},
])
def test_invalid_circle_goals(kwargs):
    with pytest.raises(ValueError):
        EndpointGoal(10, **kwargs)


def test_circle_cli_and_toml_for_local_auto_and_goal_config(tmp_path):
    local = opt.parse_arguments(['local', 'input.ltm', '--search', 'population',
                                 '--objective', 'earliest-arrival',
                                 '--target-circle', '305,237'])
    assert local.target_circle == (305., 237., 10.)
    assert LocalConfig.from_namespace(local).target_circle == (305., 237., 10.)

    goal = tmp_path / 'goal.txt'
    goal.write_text('[local]\nsearch = "population"\nobjective = "earliest-arrival"\n'
                    'target_frame = 10\ntarget_circle = "305,237,12"\n')
    parsed = opt.parse_arguments(['auto', 'input.ltm', '--goal-config', str(goal)])
    assert parsed.auto_target_circle == (305., 237., 12.)
    source = _level()
    auto_goal, _, _ = _auto_goal_from_options(source, (InputFrame(),) * 15, parsed)
    assert auto_goal.target_circle == (305., 237., 12.)

    config = tmp_path / 'config.toml'
    config.write_text('[local]\nsearch = "population"\nobjective = "earliest-arrival"\n'
                      'target_circle = [305, 237]\n')
    parsed_local = opt.parse_arguments(['local', 'input.ltm', '--config', str(config)])
    assert parsed_local.target_circle == (305., 237., 10.)

    config.write_text('[auto]\nobjective = "earliest-arrival"\n'
                      'target_circle = [305, 237, 12]\n')
    parsed_auto = opt.parse_arguments(['auto', 'input.ltm', '--config', str(config)])
    assert parsed_auto.auto_target_circle == (305., 237., 12.)


def test_multi_splice_check_command_uses_exact_circle(tmp_path, monkeypatch, capsys):
    from tests.test_random_splice import _baseline
    from tests.test_user_splice_input_check import _setup, _run

    original, route, goals, source_frames = _setup(tmp_path)
    level, _, _ = _baseline()
    at_ten = EndpointEvaluator(level, EndpointGoal(10)).evaluate(source_frames)
    (goals / 'first.txt').write_text(
        '[local]\nsearch="population"\nobjective="earliest-arrival"\n'
        'target_frame=10\nrange="0:10"\n'
        f'target_circle="{at_ten.x},{at_ten.y}"\n')
    (goals / 'second.txt').write_text(
        '[local]\nsearch="population"\nobjective="earliest-arrival"\n'
        'target_frame=10\nrange="0:10"\n'
        'target_circle="9999,9999,10"\n')
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ['auto', str(original), '--splice-config', str(route), '--check-splices'])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "[check:feasible] 'first'" in out
    assert "[check:infeasible] 'second'" in out
    assert '[check:summary] input run: 2/3 named splices feasible' in out
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_stale_native_endpoint_api_fails_early_with_rebuild_command(monkeypatch):
    import nv14_endpoint as endpoint_mod

    from nv14_native import require_native
    level = require_native().parse_level_string(_level().source_level_string,
                                                 simulate_enemies=False)

    class StaleNativeProxy:
        __file__ = "/old/build/_nv14_native.so"

        @staticmethod
        def backend_info():
            return {"population_endpoint_api": 2}

    monkeypatch.setattr(endpoint_mod, "require_native", lambda: StaleNativeProxy())
    with pytest.raises(RuntimeError, match="needs the native extension rebuilt") as error:
        EndpointEvaluator(level, EndpointGoal(10))
    assert "loaded endpoint API 2, needs 4" in str(error.value)
    assert "build_native.py --force-cython --force" in str(error.value)
    assert "/old/build/_nv14_native.so" in str(error.value)

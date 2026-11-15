"""Check-mode goals must use the LTM replay of their selected route."""
from __future__ import annotations

import sys

import pytest

from nv14_cli import main
from nv14_ltm import LtmMovie
from nv14_engine import parse_level_string
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from tests.test_user_splice_alternative_routes import _ltm_alt_branch_route, _make_routes
from tests.test_random_splice import _baseline


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, 'argv', argv + ['--check-splices'])
    main()


def _fixture(tmp_path, *, include_branch=True):
    argv = _ltm_alt_branch_route(tmp_path, include_branch=include_branch)
    routes = tmp_path / 'routes.toml'
    routes.write_text(routes.read_text() + 'branch = 9\n')
    return argv, routes


def test_check_uses_editor_branch_and_checks_shared_junctions_twice(
        tmp_path, monkeypatch, capsys):
    argv, _ = _fixture(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    _run(monkeypatch, argv)
    out = capsys.readouterr().out
    assert "[check:feasible] '230' [inputs]:" in out
    assert "[check:feasible] '230' [inputs9]:" in out
    assert "[check:feasible] '240' [inputs9]:" in out
    assert "[check:feasible] 'end' [inputs]:" in out
    assert "[check:feasible] 'end' [inputs9]:" in out
    assert "input branches: 5/5 route-specific splice checks feasible" in out
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_alt_branch_check_physics_differs_from_primary(
        tmp_path, monkeypatch, capsys):
    argv, _ = _fixture(tmp_path)
    level, _, _ = _baseline()
    engine_level = parse_level_string(level.source_level_string,
                                      simulate_enemies=True)
    alt = LtmMovie.load(tmp_path / '00-0.ltm', branch=9).replay_frames
    main_frames = LtmMovie.load(tmp_path / '00-0.ltm').replay_frames
    alt_evaluation = EndpointEvaluator(engine_level, EndpointGoal(10, 'min-x')).evaluate(alt)
    main_evaluation = EndpointEvaluator(engine_level, EndpointGoal(10, 'min-x')).evaluate(main_frames)
    assert abs(alt_evaluation.x - main_evaluation.x) > 1
    # A small region reached on inputs9 must not be treated as reached by inputs.
    x, y = alt_evaluation.x, alt_evaluation.y
    (tmp_path / 'goals' / '240.txt').write_text(
        '[local]\nobjective="earliest-arrival"\n'
        'target-frame=10\nrange="0:10"\n'
        f'target-region="{x-0.1}:{x+0.1},{y-0.1}:{y+0.1}"\n')
    _run(monkeypatch, argv)
    assert "[check:feasible] '240' [inputs9]" in capsys.readouterr().out
    # The same named goal checked against the ordinary input must now fail.
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, argv + ['--splice-alt-branch', '0'])
    assert exc.value.code == 1
    assert "[check:infeasible] '240'" in capsys.readouterr().out


def test_check_one_alt_only_uses_inputs9(tmp_path, monkeypatch, capsys):
    argv, _ = _fixture(tmp_path)
    _run(monkeypatch, argv + ['--check-splice', '240'])
    out = capsys.readouterr().out
    assert "[check:feasible] '240' [inputs9]" in out
    assert out.count('[check:feasible]') == 1
    assert 'input branches: 1/1 route-specific splice checks feasible' in out


def test_check_one_shared_checks_both_routes(tmp_path, monkeypatch, capsys):
    argv, _ = _fixture(tmp_path)
    _run(monkeypatch, argv + ['--check-splice', '230'])
    out = capsys.readouterr().out
    assert "[check:feasible] '230' [inputs]" in out
    assert "[check:feasible] '230' [inputs9]" in out
    assert 'input branches: 2/2 route-specific splice checks feasible' in out


def test_missing_branch_is_error_without_fallback(tmp_path, monkeypatch, capsys):
    argv, _ = _fixture(tmp_path, include_branch=False)
    with pytest.raises(SystemExit) as error:
        _run(monkeypatch, argv)
    assert error.value.code == 1
    assert 'cannot read alternate route inputs9' in capsys.readouterr().err


def test_missing_alt_branch_ignored_for_primary_only_check(
        tmp_path, monkeypatch, capsys):
    argv, _ = _fixture(tmp_path, include_branch=False)
    _run(monkeypatch, argv + ['--splice-skip-alt-route'])
    assert 'input run: 2/2 named splices feasible' in capsys.readouterr().out
    _run(monkeypatch, argv + ['--check-splice', '230', '--splice-skip-alt-route'])
    assert 'input run: 1/1 named splices feasible' in capsys.readouterr().out


def test_unlisted_single_goal_does_not_need_missing_alt_branch(
        tmp_path, monkeypatch, capsys):
    argv, _ = _fixture(tmp_path, include_branch=False)
    (tmp_path / 'goals' / 'unlisted.txt').write_text(
        '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    _run(monkeypatch, argv + ['--check-splice', 'unlisted'])
    assert "[check:feasible] 'unlisted'" in capsys.readouterr().out


def test_non_ltm_branch_check_is_a_clear_error(tmp_path, monkeypatch, capsys):
    _level, _source, _output, argv = _make_routes(tmp_path)
    (tmp_path / 'routes.toml').write_text(
        (tmp_path / 'routes.toml').read_text() + 'branch=9\n')
    with pytest.raises(SystemExit) as error:
        _run(monkeypatch, argv)
    assert error.value.code == 1
    assert 'branch requires an LTM input movie' in capsys.readouterr().err

"""Read-only input feasibility checks, including alternate route and single goals."""
from __future__ import annotations

import sys

import pytest

import tas
from nv14_cli import main, parse_arguments
from nv14_engine import InputFrame
from nv14_replay import encode_complex_replay
from tests.test_random_splice import _baseline


def _setup(tmp_path):
    level, source, _ = _baseline()
    original = tmp_path / 'input.txt'
    original.write_text(f'$test#author#{level.source_level_string}#'
                        f'{encode_complex_replay(source)}#\n')
    goals = tmp_path / 'goals'
    goals.mkdir()
    for name, extra in (('first', ''), ('second', ''), ('alternate', '')):
        (goals / f'{name}.txt').write_text(
            '[local]\nsearch="population"\nobjective="min-x"\n'
            'target-frame=10\nrange="0:10"\n' + extra)
    route = goals / 'multi-splicer.toml'
    route.write_text('[multi-splicer]\nsplice-files=["first", "second"]\n'
                     'alt-route=["first", "alternate", "second"]\n')
    return original, route, goals, source


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, 'argv', ['optimize_replay.py', *argv])
    main()


def test_check_all_includes_alternate_and_creates_nothing(tmp_path, monkeypatch, capsys):
    original, route, _, _ = _setup(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    _run(monkeypatch, ['auto', str(original), '--splice-config', str(route), '--check-splices'])
    out = capsys.readouterr().out
    assert out.count('[check:feasible]') == 3
    for name in ('first', 'second', 'alternate'):
        assert f"'{name}'" in out
    assert '[check:summary] input run: 3/3 named splices feasible' in out
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_check_one_from_alt_route(tmp_path, monkeypatch, capsys):
    original, route, _, _ = _setup(tmp_path)
    _run(monkeypatch, ['auto', str(original), '--splice-config', str(route),
                      '--check-splices', '--check-splice', 'alternate'])
    out = capsys.readouterr().out
    assert '[check:summary] input run: 1/1 named splices feasible' in out
    assert "'alternate'" in out
    assert "'first'" not in out


def test_check_reports_unfeasible_and_exits_one(tmp_path, monkeypatch, capsys):
    original, route, goals, _ = _setup(tmp_path)
    (goals / 'second.txt').write_text(
        '[local]\nsearch="population"\nobjective="earliest-arrival"\n'
        'target-frame=10\nrange="0:10"\ntarget-region="9000:9100,9000:9100"\n')
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ['auto', str(original), '--splice-config', str(route),
                          '--check-splices'])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert '[check:infeasible] \'second\'' in out
    assert '[check:summary] input run: 2/3 named splices feasible' in out


def test_check_one_without_route(tmp_path, monkeypatch, capsys):
    original, route, goals, _ = _setup(tmp_path)
    route.unlink()
    _run(monkeypatch, ['auto', str(original), '--auto-splice-files', 'first',
                      '--auto-splice-directory', str(goals), '--check-splices',
                      '--check-splice', 'first'])
    assert "[check:feasible] 'first'" in capsys.readouterr().out


def test_check_requires_route_or_name(tmp_path, monkeypatch):
    original, route, _, _ = _setup(tmp_path)
    route.unlink()
    with pytest.raises(SystemExit, match='needs a named splice route'):
        _run(monkeypatch, ['auto', str(original), '--check-splices'])


def test_check_shortcut_builds_read_only_command(tmp_path):
    root = tmp_path / 'directory'
    root.mkdir()
    (root / 'multi.toml').write_text('[multi-splicer]\nsplice-files=["first"]\n')
    env = {
        'TAS_INPUT_TEMPLATE': str(tmp_path / 'in.ltm'),
        'TAS_MULTI_TEMPLATE': str(root / 'multi.toml'),
        'TAS_GOAL_TEMPLATE': str(root / '{splice}.txt'),
    }
    command = tas.build_command('check', 'demo', env=env)
    assert '--check-splices' in command
    assert '--check-splice' not in command
    assert '--output' not in command
    assert '--splice-config' in command
    command = tas.build_command('check', 'demo', 'alternate', env=env)
    assert command[command.index('--check-splice') + 1] == 'alternate'
    assert '--output' not in command


def test_check_shortcut_requires_route_for_all(tmp_path):
    with pytest.raises(ValueError, match='requires a multi-splicer.toml'):
        tas.build_command('check', 'demo', env={'TAS_MULTI_TEMPLATE': str(tmp_path / 'missing')})


def test_direct_check_subcommand_infers_route_and_splice(tmp_path):
    original, route, _, _ = _setup(tmp_path)
    direct = parse_arguments(['check', str(original), '--splice-config', str(route)])
    assert direct.mode == 'auto'
    assert direct.check_splices
    assert direct.check_splice is None
    assert direct.auto_splice_files == ('first', 'second')
    single = parse_arguments(['check', str(original), 'alternate',
                              '--splice-config', str(route)])
    assert single.check_splice == 'alternate'


def test_direct_check_infers_conventional_level_route(tmp_path):
    levels = tmp_path / 'n_levels'
    levels.mkdir()
    goal_dir = tmp_path / 'splices' / '91-2'
    goal_dir.mkdir(parents=True)
    (goal_dir / 'multi-splicer.toml').write_text(
        '[multi-splicer]\nsplice-files=["foo"]\n')
    args = parse_arguments(['check', str(levels / '91-2.ltm')])
    assert args.splice_config == goal_dir / 'multi-splicer.toml'
    assert args.auto_splice_files == ('foo',)


def test_check_all_does_not_inherit_environment_splice(tmp_path, monkeypatch, capsys):
    root = tmp_path / 'splices'
    root.mkdir()
    (root / 'multi-splicer.toml').write_text(
        '[multi-splicer]\nsplice-files=["first", "second"]\n')
    env = {
        'LEVEL': '91-2', 'SPLICE': 'first',
        'TAS_MULTI_TEMPLATE': str(root / 'multi-splicer.toml'),
        'TAS_INPUT_TEMPLATE': str(tmp_path / 'input.ltm'),
    }
    assert tas.main(['check', '--dry-run'], env=env) == 0
    command = capsys.readouterr().out
    assert '--check-splices' in command
    assert '--check-splice' not in command.split()

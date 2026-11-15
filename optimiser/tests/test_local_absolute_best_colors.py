"""Standalone Local uses the same saved-best color rule as Auto and Hybrid."""
from __future__ import annotations

import sys

import pytest

import nv14_cli as cli
from nv14_engine import InputFrame
from nv14_replay import encode_complex_replay


LEVEL = '0' * (31 * 23) + '|5^100,100'


def _movie(frames):
    return f'$Colors#tests##{LEVEL}#{encode_complex_replay(frames)}#\n'


@pytest.mark.parametrize('strategy', ['windows', 'population'])
@pytest.mark.parametrize('saved_stronger', [False, True])
def test_local_live_checkpoints_use_saved_absolute_best(
        tmp_path, monkeypatch, capsys, strategy, saved_stronger):
    source = tmp_path / 'source.txt'
    source.write_text(_movie([InputFrame()] * 30))
    output = tmp_path / 'output.txt'
    # Both results are feasible; holding Right for 30 frames beats every
    # constrained-budget session result, holding Left loses to the input.
    output.write_text(_movie([InputFrame(right=saved_stronger,
                                       left=not saved_stronger)] * 30))
    args = [
        'optimize_replay.py', 'local', str(source),
        '--search', strategy, '--target-frame', '25',
        '--range', '1:25', '--objective', 'max-x',
        '--workers', '1', '--output', str(output), '--seed', '11',
    ]
    if strategy == 'windows':
        args += ['--window', '4', '--passes', '1', '--restarts', '1']
    else:
        args += ['--iterations', '100', '--beam', '8', '--rounds', '1']
    monkeypatch.setattr(sys, 'argv', args)
    monkeypatch.setattr(sys.stdout, 'isatty', lambda: True)
    cli.main()
    log = capsys.readouterr().out
    checkpoints = [line for line in log.splitlines() if '[local:best]' in line]
    assert checkpoints, log
    color = '\x1b[33m' if saved_stronger else '\x1b[32m'
    label = 'improves input only' if saved_stronger else 'new absolute best'
    if saved_stronger:
        assert all(line.startswith(color) and label in line for line in checkpoints)
    else:
        # Population can publish a distinct trajectory tied on the objective;
        # only strictly better objectives are green, ties remain yellow.
        assert any(line.startswith(color) and label in line for line in checkpoints)
        assert all((line.startswith('\x1b[32m') and 'new absolute best' in line)
                   or (line.startswith('\x1b[33m') and 'improves input only' in line)
                   for line in checkpoints)
    # Backend-local notices are not green before the verified callback checks
    # the saved record, even if an internal worker labels them new best.
    assert not any('\x1b[32m' in line and '[NEW BEST SO FAR]' in line
                   for line in log.splitlines())


@pytest.mark.parametrize('strategy', ['windows', 'population'])
def test_local_named_goal_compares_saved_splice_not_just_main_output(
        tmp_path, monkeypatch, capsys, strategy):
    source = tmp_path / 'demo.txt'
    source.write_text(_movie([InputFrame()] * 30))
    directory = tmp_path / 'demo'
    directory.mkdir()
    goal = directory / '25.toml'
    goal.write_text('[local]\nsearch="' + strategy + '"\n'
                    'objective="max-x"\ntarget-frame=25\nrange="1:25"\n'
                    'workers=1\nseed=11\n'
                    + ('window=4\npasses=1\nrestarts=1\n' if strategy == 'windows'
                       else 'iterations=100\nbeam=8\nrounds=1\n'))
    output = tmp_path / 'output.txt'
    output.write_text(_movie([InputFrame(left=True)] * 30))
    saved_stage = tmp_path / 'output_25.txt'
    saved_stage.write_text(_movie([InputFrame(right=True)] * 30))
    old_stage = saved_stage.read_bytes()
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'local', str(source), '--config', str(goal),
        '--output', str(output),
    ])
    monkeypatch.setattr(sys.stdout, 'isatty', lambda: True)
    cli.main()
    checkpoints = [line for line in capsys.readouterr().out.splitlines()
                   if '[local:best]' in line]
    assert checkpoints
    assert all(line.startswith('\x1b[33m') and 'improves input only' in line
               for line in checkpoints)
    assert saved_stage.read_bytes() == old_stage


def test_local_ansi_disabled_and_unknown_saved_best_stays_yellow(tmp_path, monkeypatch, capsys):
    source = tmp_path / 'source.txt'
    source.write_text(_movie([InputFrame()] * 30))
    output = tmp_path / 'output.txt'
    output.write_bytes(b'not a replay')
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'local', str(source), '--search', 'population',
        '--target-frame', '25', '--range', '1:25', '--objective', 'max-x',
        '--workers', '1', '--output', str(output), '--iterations', '100',
        '--beam', '8', '--rounds', '1', '--seed', '11', '--no-color',
    ])
    cli.main()
    log = capsys.readouterr().out
    assert '[local:checkpoint] cannot compare saved best' in log
    assert '[local:best]' in log
    assert 'improves input only' in log
    assert '\x1b[' not in log


def test_local_named_goal_recognition_only_for_level_directory(tmp_path):
    path = tmp_path / 'demo.txt'
    assert cli._local_saved_goal_paths(None, tmp_path / 'demo' / '25.toml', path) == (
        tmp_path / 'demo' / '25.toml',)
    assert cli._local_saved_goal_paths(None, tmp_path / 'shared' / 'config.toml', path) == ()

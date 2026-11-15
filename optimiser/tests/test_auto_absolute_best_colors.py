"""Auto's green means a new *saved* best, not just a new search-local best."""
from __future__ import annotations

from types import SimpleNamespace

import nv14_cli as cli


def test_saved_best_tracker_distinguishes_improvement_from_absolute_best():
    tracker = cli._AutoSavedBestColor((5.0, -1.0))
    assert not tracker.new_absolute_best((6.0, 0.0))  # improves input only
    assert not tracker.new_absolute_best((5.0, -1.0))  # ties saved best
    assert tracker.new_absolute_best((5.0, -2.0))  # secondary breaks tie
    assert not tracker.new_absolute_best((5.0, -1.5))
    assert tracker.new_absolute_best((4.0, 0.0))


def test_unreadable_previous_best_never_claims_absolute():
    tracker = cli._AutoSavedBestColor(None, comparable=False)
    assert not tracker.new_absolute_best((1.0,))
    assert not tracker.new_absolute_best((0.0,))
    assert tracker.best_key is None


def test_first_improvement_is_absolute_without_saved_best():
    tracker = cli._AutoSavedBestColor(None)
    assert tracker.new_absolute_best((10.0,))
    assert tracker.new_absolute_best((9.0,))
    assert not tracker.new_absolute_best((9.0,))


def test_named_endpoint_compares_both_current_output_and_existing_stage(tmp_path, monkeypatch):
    output = tmp_path / 'demo.ltm'
    stage = tmp_path / 'demo_196.ltm'
    output.write_bytes(b'old output')
    stage.write_bytes(b'old checkpoint')
    # No native search needed: the saved-record loader and endpoint evaluator
    # are replaced with small deterministic test doubles.
    from nv14_engine import InputFrame
    from nv14_endpoint import EndpointEvaluation

    lengths = {output: 10, stage: 5}
    monkeypatch.setattr(cli, '_load_source', lambda path, **kw: SimpleNamespace(
        combined=SimpleNamespace(level_string='same level'),
        ltm_movie=SimpleNamespace(replay_frames=[InputFrame()] * lengths[path]),
    ))
    class Evaluator:
        def __init__(self, level, goal):
            pass
        def evaluate(self, frames):
            return SimpleNamespace(feasible=True, objective_key=(len(frames),))
    monkeypatch.setattr('nv14_endpoint.EndpointEvaluator', Evaluator)

    source = SimpleNamespace(levels_file_path=None, level_id=None,
                             combined=SimpleNamespace(level_string='same level'))
    tracker = cli._auto_saved_best_color_reference(
        source, object(), output, tmp_path / 'demo.txt',
        objective='min-x', endpoint_goal=SimpleNamespace(target_frame=1),
        goal_paths=[tmp_path / '196.txt'],
    )
    assert tracker.best_key == (5,)
    assert not tracker.new_absolute_best((6,))
    assert tracker.new_absolute_best((4,))
    assert not tracker.new_absolute_best((4,))


def test_named_endpoint_broken_saved_checkpoint_stays_yellow(tmp_path, monkeypatch, capsys):
    output = tmp_path / 'demo.ltm'
    stage = tmp_path / 'demo_196.ltm'
    stage.write_bytes(b'invalid')
    def broken_loader(path, **kw):
        raise ValueError('invalid LTM')
    monkeypatch.setattr(cli, '_load_source', broken_loader)
    from nv14_engine import InputFrame
    source = SimpleNamespace(levels_file_path=None, level_id=None,
                             combined=SimpleNamespace(level_string='level'))
    monkeypatch.setattr('nv14_endpoint.EndpointEvaluator', lambda *args: object())
    tracker = cli._auto_saved_best_color_reference(
        source, object(), output, None,
        objective='min-x', endpoint_goal=SimpleNamespace(target_frame=1),
        goal_paths=[tmp_path / '196.txt'],
    )
    assert not tracker.comparable
    assert not tracker.new_absolute_best((0,))
    assert 'cannot compare saved best' in capsys.readouterr().out


def test_color_prefixes_and_no_color(monkeypatch, capsys):
    monkeypatch.setattr('sys.stdout.isatty', lambda: True)
    cli._print_temporary_line('[auto:checkpoint] improves input only', color=True)
    cli._print_best_line('[auto:checkpoint] new absolute best', color=True)
    assert capsys.readouterr().out == (
        '\x1b[33m[auto:checkpoint] improves input only\x1b[0m\n'
        '\x1b[32m[auto:checkpoint] new absolute best\x1b[0m\n'
    )
    cli._print_temporary_line('plain', color=False)
    assert capsys.readouterr().out == 'plain\n'


def _run_named_endpoint_with_saved_reference(tmp_path, monkeypatch, capsys, *, saved_right: int):
    from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame
    from nv14_replay import encode_complex_replay
    import sys
    level = '0' * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + '|5^60,60'
    original = [InputFrame()] * 45
    input_file = tmp_path / 'source.txt'
    input_file.write_text(
        f'$Demo#Demo##{level}#{encode_complex_replay(original)}#\n',
        encoding='utf-8',
    )
    goal = tmp_path / '196.txt'
    goal.write_text('[local]\nobjective="max-x"\ntarget-frame=25\nrange="1:25"\n')
    output = tmp_path / 'out.txt'
    saved = tmp_path / 'out_196.txt'
    previous = ([InputFrame(right=True)] * saved_right +
                [InputFrame()] * (45 - saved_right))
    saved.write_text(encode_complex_replay(previous) + '\n')
    before = saved.read_bytes()
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(input_file),
        '--goal-config', str(goal), '--output', str(output),
        '--workers', '1', '--iterations', '80', '--beam', '8',
        '--auto-runs', '1', '--seed', '11',
    ])
    monkeypatch.setattr(sys.stdout, 'isatty', lambda: True)
    cli.main()
    stdout = capsys.readouterr().out
    checkpoints = [line for line in stdout.splitlines()
                   if '[auto:checkpoint] saved best #' in line]
    assert checkpoints
    assert saved.read_bytes() == before  # reporting never promotes the checkpoint
    return checkpoints


def test_named_auto_checkpoint_yellow_when_saved_splice_is_better(
        tmp_path, monkeypatch, capsys):
    checkpoints = _run_named_endpoint_with_saved_reference(
        tmp_path, monkeypatch, capsys, saved_right=45)
    assert all(line.startswith('\x1b[33m') for line in checkpoints)
    assert all('improves input only' in line for line in checkpoints)
    assert not any('\x1b[32m' in line for line in checkpoints)


def test_named_auto_checkpoint_green_when_beating_saved_splice(
        tmp_path, monkeypatch, capsys):
    checkpoints = _run_named_endpoint_with_saved_reference(
        tmp_path, monkeypatch, capsys, saved_right=1)
    assert any(line.startswith('\x1b[32m') for line in checkpoints)
    assert any('new absolute best' in line for line in checkpoints)


def test_completed_run_compares_prior_completed_output(tmp_path, monkeypatch):
    from nv14_engine import InputFrame
    output = tmp_path / 'completed.ltm'
    output.write_bytes(b'old completed run')
    source = SimpleNamespace(levels_file_path=None, level_id=None,
                             combined=SimpleNamespace(level_string='level'))
    monkeypatch.setattr(cli, '_load_source', lambda *args, **kwargs:
                        SimpleNamespace(
                            combined=SimpleNamespace(level_string='level'),
                            ltm_movie=SimpleNamespace(
                                replay_frames=[InputFrame()] * 10,
                            ),
                        ))
    monkeypatch.setattr(cli, 'verify_trimmed_replay', lambda *args:
                        SimpleNamespace(valid=True, finish_tick=10,
                                        pre_finish_exit_distance=3.0))
    tracker = cli._auto_saved_best_color_reference(
        source, object(), output, None, objective='speedrun')
    assert tracker.best_key == (0, 10, 3.0)
    assert not tracker.new_absolute_best((0, 10, 4.0))
    assert tracker.new_absolute_best((0, 10, 2.0))
    assert tracker.new_absolute_best((0, 9, 100.0))

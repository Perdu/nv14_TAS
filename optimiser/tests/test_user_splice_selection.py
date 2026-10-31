"""Incremental named multi-splicer controls and best-score progress reporting."""
from __future__ import annotations
import pytest
import nv14_user_splice as us
from nv14_cli import parse_arguments
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_cli_start_stop_names_and_config():
    cfg = None
    args = parse_arguments(['auto', 'source.ltm', '--auto-splice-files', '556,628,739,end',
                            '--auto-splice-start', '628', '--auto-splice-stop', '739'])
    assert args.auto_splice_start == '628'
    assert args.auto_splice_stop == '739'
    assert args.auto_splice_mode == 'user'
    with pytest.raises(SystemExit, match='require --auto-random-splice'):
        parse_arguments(['auto', 'source.ltm', '--auto-splice-start', '628'])


def test_only_inclusive_selected_stages_are_searched(monkeypatch):
    level, source, _ = _baseline()
    stages = [UserSpliceStage(name, EndpointGoal(frame, 'max-x'), 0, frame)
              for name, frame in [('556', 10), ('628', 11), ('739', 12), ('end', 13)]]
    visited, progress, checkpoints = [], [], []
    def fake_search(level, branch, stage, config, rng):
        visited.append(stage.name)
        return (), 0, 1
    monkeypatch.setattr(us, '_search_stage', fake_search)
    result = optimise_user_splices(
        level, source, stages, RandomSpliceConfig(rounds=1, workers=1, iterations=2),
        completion_policy='checkpoint', start_at='628', stop_at='739',
        stage_best_callback=lambda name, frames: checkpoints.append(name),
        progress=progress.append)
    assert visited and set(visited) == {'628', '739'}
    assert not checkpoints  # Baseline should never be written.
    assert result.improvements == 0
    assert any('selected stages 2-3/4' in line for line in progress)
    with pytest.raises(ValueError, match='start must not be after'):
        optimise_user_splices(level, source, stages,
            RandomSpliceConfig(rounds=1), start_at='end', stop_at='628')
    with pytest.raises(ValueError, match='not a unique name'):
        optimise_user_splices(level, source, stages,
            RandomSpliceConfig(rounds=1), start_at='missing')


def test_progress_reports_previous_score_position_and_no_baseline_write(monkeypatch):
    level, source, _ = _baseline()
    stage = UserSpliceStage('230', EndpointGoal(10, 'min-x'), 0, 10)
    candidate = (InputFrame(left=True),) + source[1:]
    baseline = EndpointEvaluator(level, stage.goal).evaluate(source)
    improved = EndpointEvaluator(level, stage.goal).evaluate(candidate)
    assert improved.objective_key < baseline.objective_key
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw: (((candidate, 10),), 1, 1))
    reports, checkpoints = [], []
    optimise_user_splices(level, source, [stage],
        RandomSpliceConfig(rounds=1, workers=1, iterations=2),
        completion_policy='complete', progress=reports.append,
        stage_best_callback=lambda name, frames: checkpoints.append((name, frames)))
    assert checkpoints == [('230', candidate)]
    temporary = next(line for line in reports if '[auto:user-splice:temporary]' in line)
    assert 'position' in temporary
    assert f'{baseline.x:.9g}' in temporary
    assert f'{improved.x:.9g}' in temporary
    assert 'min-x' in temporary
    assert 'rank (' not in temporary
    assert 'NOT verified' not in temporary


def test_cli_start_stop_executes_only_requested_stages(tmp_path, monkeypatch, capsys):
    import sys
    from nv14_replay import encode_complex_replay
    from nv14_cli import main
    level, frames, _ = _baseline()
    source_file = tmp_path / 'source.txt'
    source_file.write_text(f'$test#author#{level.source_level_string}#'
                           f'{encode_complex_replay(frames)}#\n')
    directory = tmp_path / 'goals'; directory.mkdir()
    for name, frame in [('203', 10), ('408', 12), ('end', 15)]:
        (directory / (name + '.txt')).write_text(
            f'[local]\nobjective="max-x"\ntarget-frame={frame}\nrange="0:{frame}"\n')
    config = tmp_path / 'multi.toml'
    config.write_text('[auto]\nsplice-files=["203","408","end"]\n'
                      'splice-iterations=2\nsplice-rounds=1\nruns=1\nseed=0\n')
    seen=[]
    monkeypatch.setattr(us, '_search_stage', lambda level, branch, stage, config, rng:
                        (seen.append(stage.name) or ((), 0, 1)))
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(source_file), '--config', str(config),
        '--auto-splice-directory', str(directory),
        '--auto-splice-start', '408', '--auto-splice-stop', '408',
        '--output', str(tmp_path/'optim.txt'), '--workers', '1'])
    main()
    assert seen == ['408']
    out = capsys.readouterr().out
    assert 'selected stages 2-2/3' in out
    assert not (tmp_path/'optim.txt').exists()
    assert not (tmp_path/'optim_203.txt').exists()


def test_skip_early_stage_does_not_waive_earlier_goal(monkeypatch):
    level, source, baseline = _baseline()
    pos = baseline.point(10)
    initial = UserSpliceStage('switch', EndpointGoal(10, 'earliest-arrival',
        target_region=(pos.x-1, pos.x+1, pos.y-1, pos.y+1)), 0, 10)
    latter = UserSpliceStage('end', EndpointGoal(14, 'max-x'), 0, 14)
    altered = tuple(InputFrame(left=True) for _ in source)
    assert not EndpointEvaluator(level, initial.goal).evaluate(altered).feasible
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw: (((altered, 14),), 1, 1))
    saved = []
    optimise_user_splices(level, source, [initial, latter],
        RandomSpliceConfig(rounds=1, iterations=2, workers=1),
        start_at='end', completion_policy='checkpoint',
        stage_best_callback=lambda name, frames: saved.append((name,frames)))
    assert not saved

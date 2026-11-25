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


def test_start_at_splice_is_alias_for_splice_start():
    args = ['auto', 'source.ltm', '--auto-splice-files', '556,628,739,end']
    original = parse_arguments(args + ['--splice-start', '628'])
    alias = parse_arguments(args + ['--start-at-splice', '628'])
    assert original.auto_splice_start == alias.auto_splice_start == '628'
    assert original.auto_splice_mode == alias.auto_splice_mode == 'user'
    with pytest.raises(SystemExit, match='require --auto-random-splice'):
        parse_arguments(['auto', 'source.ltm', '--start-at-splice', '628'])


def test_only_inclusive_selected_stages_are_searched(monkeypatch):
    level, source, _ = _baseline()
    stages = [UserSpliceStage(name, EndpointGoal(frame, 'max-x'), 0, frame)
              for name, frame in [('556', 10), ('628', 11), ('739', 12), ('end', 13)]]
    visited, progress, checkpoints = [], [], []
    def fake_search(level, branch, stage, config, rng, **kwargs):
        visited.append(stage.name)
        return (), 0, 1
    monkeypatch.setattr(us, '_search_stage', fake_search)
    result = optimise_user_splices(
        level, source, stages, RandomSpliceConfig(rounds=1, workers=1, iterations=2),
        completion_policy='checkpoint', start_at='628', stop_at='739',
        stage_best_callback=lambda name, frames: checkpoints.append(name),
        progress=progress.append)
    assert visited and set(visited) == {'628', '739'}
    assert set(checkpoints) == {'556', '628', '739', 'end'}  # Initial checkpoints (patch 16)
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
    assert checkpoints == [('230', source), ('230', candidate)]
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
    monkeypatch.setattr(us, '_search_stage', lambda level, branch, stage, config, rng, **kwargs:
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
    assert (tmp_path/'optim_203.txt').exists()  # initial checkpoint


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
    assert saved and all(frames != altered for _, frames in saved)


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
    assert checkpoints == [('230', source), ('230', candidate)]
    temporary = next(line for line in reports if '[auto:user-splice:temporary]' in line)
    assert 'position' in temporary
    assert f'{baseline.x:.9g}' in temporary
    assert f'{improved.x:.9g}' in temporary
    assert 'min-x' in temporary
    assert 'rank (' not in temporary
    assert 'NOT verified' not in temporary


def test_stop_at_splice_alias_matches_splice_stop():
    from nv14_cli import parse_arguments
    argv = ['auto', 'source.ltm', '--auto-random-splice', '--auto-splice-mode',
            'user', '--auto-splice-files', '230,240,end']
    old = parse_arguments(argv + ['--splice-stop', '240'])
    new = parse_arguments(argv + ['--stop-at-splice', '240'])
    assert old.auto_splice_stop == new.auto_splice_stop == '240'


def test_start_first_round_only_parser_requires_explicit_start():
    argv = ['auto', 'source.ltm', '--auto-splice-files', '203,408,end']
    normal = parse_arguments(argv + ['--start-at-splice', '408'])
    assert normal.auto_splice_start_first_round_only is False
    enabled = parse_arguments(argv + ['--start-at-splice', '408',
                                      '--start-at-splice-first-round-only'])
    assert enabled.auto_splice_start_first_round_only is True
    short = parse_arguments(argv + ['--start-at-splice', '408', '-u'])
    assert short.auto_splice_start_first_round_only is True
    assert short.auto_splice_start == enabled.auto_splice_start == '408'
    assert parse_arguments(argv + ['--start-at-splice', '408',
        '--splice-start-first-round-only']).auto_splice_start_first_round_only is True
    assert parse_arguments(argv + ['--start-at-splice', '408',
        '--no-start-at-splice-first-round-only']).auto_splice_start_first_round_only is False
    with pytest.raises(SystemExit, match='requires --start-at-splice'):
        parse_arguments(argv + ['--start-at-splice-first-round-only'])
    with pytest.raises(SystemExit, match='requires --start-at-splice'):
        parse_arguments(argv + ['-u'])
    with pytest.raises(SystemExit, match='--single-splice'):
        parse_arguments(argv + ['--single-splice', '408', '--start-at-splice-first-round-only'])
    with pytest.raises(SystemExit, match='--splice-from-best'):
        parse_arguments(argv + ['--start-at-splice', '408', '--splice-from-best', '203',
                                '--start-at-splice-first-round-only'])


def test_start_first_round_only_restarts_earlier_splices_and_resumes(monkeypatch):
    level, source, _ = _baseline()
    stages = [UserSpliceStage(name, EndpointGoal(frame, 'max-x'), 0, frame)
              for name, frame in [('203', 10), ('408', 12), ('end', 14)]]
    called = []
    monkeypatch.setattr(us, '_search_stage',
        lambda level, branch, stage, config, rng, **kwargs:
            (called.append(stage.name) or ((), 0, 1)))
    config = RandomSpliceConfig(rounds=3, workers=1, iterations=2)
    kwargs = dict(completion_policy='checkpoint', start_at='408',
                  start_first_round_only=True)
    progress = []
    optimise_user_splices(level, source, stages, config,
                          progress=progress.append, **kwargs)
    assert called == ['408', 'end', '203', '408', 'end', '203', '408', 'end']
    assert any("round 2: starting again from '203'" in line for line in progress)
    assert any("round 3: starting again from '203'" in line for line in progress)
    called.clear()
    optimise_user_splices(level, source, stages, config, **{**kwargs,
                          'resume_outer_round': 1})
    assert called == ['203', '408', 'end', '203', '408', 'end']
    called.clear()
    optimise_user_splices(level, source, stages, config,
                          completion_policy='checkpoint', start_at='408')
    assert called == ['408', 'end'] * 3


def test_start_first_round_only_in_multi_splicer_toml(tmp_path, monkeypatch):
    import sys
    from nv14_replay import encode_complex_replay
    from nv14_cli import main
    level, frames, _ = _baseline()
    source_file = tmp_path / 'source.txt'
    source_file.write_text(f'$test#author#{level.source_level_string}#'
                           f'{encode_complex_replay(frames)}#\n')
    directory = tmp_path / 'goals'; directory.mkdir()
    for name, frame in [('203', 10), ('408', 12), ('end', 14)]:
        (directory / f'{name}.txt').write_text(
            f'[local]\nobjective="max-x"\ntarget-frame={frame}\nrange="0:{frame}"\n')
    config = tmp_path / 'multi.toml'
    config.write_text('[multi-splicer]\nfiles=["203","408","end"]\n'
                      'start="408"\nstart-first-round-only=true\n'
                      'iterations=2\nrounds=1\n[auto]\nruns=2\nseed=0\n')
    args = parse_arguments(['auto', str(source_file), '--config', str(config)])
    assert args.auto_splice_start == '408'
    assert args.auto_splice_start_first_round_only is True
    called = []
    monkeypatch.setattr(us, '_search_stage', lambda level, branch, stage, config, rng, **kwargs:
                        (called.append(stage.name) or ((), 0, 1)))
    monkeypatch.setattr(sys, 'argv', ['optimize_replay.py', 'auto', str(source_file),
        '--config', str(config), '--auto-splice-directory', str(directory),
        '--output', str(tmp_path / 'optim.txt'), '--workers', '1'])
    main()
    assert called == ['408', 'end', '203', '408', 'end']


def test_start_first_round_only_resumes_inflight_second_round(monkeypatch):
    level, source, _ = _baseline()
    stages = [UserSpliceStage(name, EndpointGoal(frame, 'min-x'), 0, frame)
              for name, frame in [('203', 10), ('408', 12), ('end', 14)]]
    config = RandomSpliceConfig(search_backend='local', iterations=2,
                                workers=1, frontier=1, rounds=3, seed=7,
                                splice_local_stagnation_rounds=1)
    calls = []
    pointer = {}
    interrupted = [False]

    def backend(_level, _branch, goal, *, resume, **kwargs):
        calls.append((goal.target_frame, resume))
        if goal.target_frame == 10 and not interrupted[0]:
            interrupted[0] = True
            raise KeyboardInterrupt()
        return (), 0

    def save(state):
        pointer.clear()
        if state is not None:
            pointer.update(state)

    monkeypatch.setattr(us, '_local_search', backend)
    kwargs = dict(completion_policy='checkpoint', start_at='408',
                  start_first_round_only=True, save_resume_state=save,
                  backend_checkpoint_path=lambda name, backend: f'/tmp/patch154-{name}-{backend}.json')
    with pytest.raises(KeyboardInterrupt):
        optimise_user_splices(level, source, stages, config, **kwargs)
    assert pointer['round_no'] == 1
    assert pointer['stage_index'] == 0
    assert pointer['start_first_round_only'] is True
    assert calls[:2] == [(12, False), (14, False)]
    assert calls[2] == (10, False)
    optimise_user_splices(level, source, stages, config,
                          resume_state=dict(pointer), **kwargs)
    assert calls[3] == (10, True)
    assert not pointer

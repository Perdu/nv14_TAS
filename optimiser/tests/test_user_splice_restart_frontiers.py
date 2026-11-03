"""Crash-safe frontier persistence and saved-final resume protection."""
from __future__ import annotations

import json
import sys

import pytest

import nv14_user_splice as us
from nv14_auto import evaluate_replay_with_sentinel
from nv14_cli import (_load_user_splice_frontiers, _user_splice_frontier_identity,
                      _user_splice_frontier_path, main)
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_random_splice import RandomSpliceConfig
from nv14_replay import encode_complex_replay
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def _vary(source, count):
    return tuple(InputFrame(left=True) for _ in range(count)) + source[count:]


def _stages():
    return [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
            for name in ('a', 'b', 'c', 'end')]


def test_from_best_restores_full_three_back_history(monkeypatch):
    level, source, _ = _baseline()
    a, b, c = (_vary(source, k) for k in (1, 2, 3))
    calls = []

    def search(_level, branch, stage, *args, **kwargs):
        calls.append((stage.name, tuple(branch)))
        return (), 0, 1

    monkeypatch.setattr(us, '_search_stage', search)
    optimise_user_splices(
        level, source, _stages(),
        RandomSpliceConfig(rounds=2, iterations=2, workers=1,
                           frontier=3, stage_lookback=3),
        completion_policy='checkpoint', from_best='c',
        saved_stage_candidates={'c': [c], 'b': [b], 'a': [a]},
    )
    assert len(calls) == 6
    assert [stage for stage, _ in calls] == ['end'] * 6
    for round_index in (0, 3):
        assert {frames for _, frames in calls[round_index:round_index+3]} == {a, b, c}


def test_frontier_multiple_candidates_are_reused(monkeypatch):
    level, source, _ = _baseline()
    candidates = [_vary(source, k) for k in (1, 2, 3)]
    stages = [UserSpliceStage('a', EndpointGoal(10, 'min-x'), 0, 10)]
    saved = []
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs:
                        (tuple((item, 10) for item in candidates), 3, 1))
    optimise_user_splices(level, source, stages,
                          RandomSpliceConfig(rounds=1, frontier=3, iterations=2),
                          completion_policy='checkpoint',
                          frontier_callback=lambda name, frames: saved.append((name, frames)))
    assert saved
    assert saved[-1][0] == 'a'
    assert 3 <= len(saved[-1][1]) <= 64
    assert len(set(saved[-1][1])) == len(saved[-1][1])

    calls = []
    monkeypatch.setattr(us, '_search_stage', lambda _level, branch, stage, *args, **kw:
                        (calls.append((stage.name, tuple(branch))) or (), 0, 1))
    optimise_user_splices(level, source,
                          [*stages, UserSpliceStage('end', EndpointGoal(10, 'min-x'), 0, 10)],
                          RandomSpliceConfig(rounds=1, frontier=3, iterations=2),
                          completion_policy='checkpoint', start_at='end',
                          saved_stage_frontiers={'a': saved[-1][1]})
    # All three from the archived frontier are tried before falling back to source.
    assert {frames for name, frames in calls if name == 'end'} >= set(saved[-1][1][:3])


def test_sidecar_checks_stage_and_level_identity(tmp_path):
    level, source, _ = _baseline()
    stage = _stages()[0]
    main = tmp_path/'optim_a.ltm'
    path = _user_splice_frontier_path(main)
    doc = _user_splice_frontier_identity(level, stage)
    doc['replays'] = [encode_complex_replay(source), encode_complex_replay(_vary(source, 1))]
    path.write_text(json.dumps(doc))
    outputs = {'a': (main, None)}
    assert len(_load_user_splice_frontiers(level, [stage], outputs)['a']) == 2
    path.write_text('{broken')
    assert _load_user_splice_frontiers(level, [stage], outputs) == {}
    doc['level_sha256'] = 'not this level'
    path.write_text(json.dumps(doc))
    assert _load_user_splice_frontiers(level, [stage], outputs) == {}


def test_saved_final_protects_score_even_when_source_is_worse(monkeypatch):
    level, _, _ = _baseline()

    def completed(k):
        replay = (InputFrame(left=True),)*k + (InputFrame(right=True),)*80
        end = evaluate_replay_with_sentinel(level, replay).finish_tick
        assert end is not None
        return replay[:end]

    saved = completed(0)   # best x at frame 10, canonical completion at 29
    source = completed(2)  # worse x at frame 10, canonical completion at 33
    intermediate = completed(1)
    goal = EndpointGoal(10, 'max-x')
    evaluator = EndpointEvaluator(level, goal)
    assert evaluator.evaluate(saved).objective_key < evaluator.evaluate(intermediate).objective_key
    assert evaluator.evaluate(intermediate).objective_key < evaluator.evaluate(source).objective_key
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs:
                        (((intermediate, 10),), 1, 1))
    writes = []
    result = optimise_user_splices(
        level, source, [UserSpliceStage('end', goal, 0, 10)],
        RandomSpliceConfig(rounds=1, iterations=2),
        completion_policy='complete', saved_final_frames=saved,
        best_callback=writes.append)
    assert result.frames == saved
    assert result.improvements == 0
    assert writes == []


def test_invalid_saved_final_is_ignored_for_new_search(monkeypatch):
    level, source, _ = _baseline()
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs: ((), 0, 1))
    result = optimise_user_splices(
        level, source, [UserSpliceStage('end', EndpointGoal(10, 'max-x'), 0, 10)],
        RandomSpliceConfig(rounds=1, iterations=2),
        saved_final_frames=source[:10], completion_policy='complete')
    assert result.frames == source


def test_cli_atomic_frontier_persists_and_is_read_only_for_ls(tmp_path, monkeypatch):
    level, source, _ = _baseline()
    input_file = tmp_path/'source.txt'
    input_file.write_text(f'$test#author#{level.source_level_string}#'
                          f'{encode_complex_replay(source)}#\n')
    goals = tmp_path/'goals'
    goals.mkdir()
    for name in ('a', 'end'):
        (goals/f'{name}.txt').write_text('[local]\nobjective="min-x"\n'
                                          'target-frame=10\nrange="0:10"\n')
    config = tmp_path/'multi.toml'
    config.write_text('[auto]\nsplice-files=["a","end"]\n'
                      'splice-search="local"\nsplice-iterations=2\n'
                      'runs=1\nbeam=3\nseed=0\n')
    args = ['optimize_replay.py', 'auto', str(input_file),
            '--config', str(config), '--auto-splice-directory', str(goals),
            '--output', str(tmp_path/'optim.txt'),
            '--replay-output', str(tmp_path/'replay.txt'), '--workers', '1']
    candidates = [_vary(source, k) for k in (1, 2, 3)]
    monkeypatch.setattr(us, '_search_stage', lambda _level, branch, stage, *a, **kw:
                        (tuple((s, 10) for s in candidates) if stage.name == 'a' else (), 3, 1))
    monkeypatch.setattr(sys, 'argv', args)
    main()
    path = tmp_path/'optim_a.frontier.json'
    assert path.is_file()
    document = json.loads(path.read_text())
    assert 3 <= len(document['replays']) <= 64
    original = path.read_bytes()
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw:
                        pytest.fail('search while listing'))
    monkeypatch.setattr(sys, 'argv', [*args, '--ls-splices'])
    main()
    assert path.read_bytes() == original


def test_cli_saved_final_baseline_blocks_regression_from_older_input(tmp_path, monkeypatch):
    """Actual output file contents stay unchanged after an older-input restart."""
    level, _source, _ = _baseline()

    def completed(left_count):
        trial = (InputFrame(left=True),) * left_count + (InputFrame(right=True),)*80
        end = evaluate_replay_with_sentinel(level, trial).finish_tick
        assert end is not None
        return trial[:end]

    best, intermediate, older = (completed(k) for k in (0, 1, 2))
    input_path = tmp_path / 'source.txt'
    output_path = tmp_path / 'optim.txt'
    text = lambda replay: (f'$test#author#{level.source_level_string}#'
                           f'{encode_complex_replay(replay)}#\n')
    input_path.write_text(text(older))
    output_path.write_text(text(best))
    before = output_path.read_bytes()
    goals = tmp_path/'goals'
    goals.mkdir()
    (goals/'end.txt').write_text('[local]\nobjective="max-x"\n'
                                 'target-frame=10\nrange="0:10"\n')
    cfg = tmp_path/'multi.toml'
    cfg.write_text('[auto]\nsplice-files=["end"]\n'
                   'splice-search="local"\nsplice-iterations=2\n'
                   'runs=1\nbeam=3\nseed=0\n')
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw:
                        (((intermediate, 10),), 0, 1))
    monkeypatch.setattr(sys, 'argv', ['optimize_replay.py', 'auto', str(input_path),
                                      '--config', str(cfg), '--auto-splice-directory', str(goals),
                                      '--output', str(output_path), '--workers', '1'])
    main()
    assert output_path.read_bytes() == before


def test_frontier_durable_after_ctrl_c_during_next_stage(tmp_path, monkeypatch):
    level, source, _ = _baseline()
    input_file = tmp_path/'source.txt'
    input_file.write_text(f'$test#author#{level.source_level_string}#'
                          f'{encode_complex_replay(source)}#\n')
    goals = tmp_path/'goals'; goals.mkdir()
    for name in ('a', 'end'):
        (goals/f'{name}.txt').write_text('[local]\nobjective="min-x"\n'
                                          'target-frame=10\nrange="0:10"\n')
    config = tmp_path/'multi.toml'
    config.write_text('[auto]\nsplice-files=["a","end"]\n'
                      'splice-search="local"\nsplice-iterations=2\n'
                      'runs=1\nbeam=3\nseed=0\n')
    args = ['optimize_replay.py', 'auto', str(input_file),
            '--config', str(config), '--auto-splice-directory', str(goals),
            '--output', str(tmp_path/'optim.txt'),
            '--replay-output', str(tmp_path/'replay.txt'), '--workers', '1']
    alternatives = [_vary(source, k) for k in (1, 2, 3)]

    def interrupted(_level, branch, stage, *args, **kwargs):
        if stage.name == 'end':
            raise KeyboardInterrupt
        return tuple((candidate, 10) for candidate in alternatives), 3, 1

    monkeypatch.setattr(us, '_search_stage', interrupted)
    monkeypatch.setattr(sys, 'argv', args)
    with pytest.raises(SystemExit) as interrupted_exit:
        main()
    assert interrupted_exit.value.code == 130
    archive = tmp_path/'optim_a.frontier.json'
    assert archive.is_file()
    assert 3 <= len(json.loads(archive.read_text())['replays']) <= 64
    observed = []
    monkeypatch.setattr(us, '_search_stage', lambda _level, branch, stage, *a, **kw:
                        (observed.append((stage.name, tuple(branch))) or (), 0, 1))
    monkeypatch.setattr(sys, 'argv', [*args, '--splice-from-best', 'a'])
    main()
    # The best saved stage replay survives in LTM/TXT and is used again.
    assert observed and observed[0][0] == 'end'
    assert observed[0][1] == alternatives[-1]


def test_saved_completed_result_does_not_compete_with_incomplete_checkpoint_score(monkeypatch):
    """An obsolete incomplete input cannot veto a new canonical completion."""
    level, _, _ = _baseline()
    def completed(delay):
        movie = (InputFrame(left=True),)*delay + (InputFrame(right=True),)*80
        return movie[:evaluate_replay_with_sentinel(level, movie).finish_tick]
    saved = completed(3)
    candidate = completed(1)
    source = (InputFrame(right=True),)*15  # better at frame 10 but cannot finish
    goal = EndpointGoal(10, 'max-x')
    eval_stage = EndpointEvaluator(level, goal)
    assert eval_stage.evaluate(source).objective_key < eval_stage.evaluate(candidate).objective_key
    assert eval_stage.evaluate(candidate).objective_key < eval_stage.evaluate(saved).objective_key
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kw: (((candidate, 10),), 1, 1))
    saved_results = []
    result = optimise_user_splices(
        level, source, [UserSpliceStage('end', goal, 0, 10)],
        RandomSpliceConfig(iterations=2, rounds=1),
        completion_policy='checkpoint', saved_final_frames=saved,
        best_callback=saved_results.append)
    assert result.frames == candidate
    assert saved_results == [candidate]

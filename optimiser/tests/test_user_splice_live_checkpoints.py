"""Continuous backend bests must be visible and durable before phase termination."""
from types import SimpleNamespace

from nv14_engine import InputFrame
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_random_splice import RandomSpliceConfig, _local_search
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_phase_reports_and_saves_stage_best_before_backend_returns(monkeypatch):
    import nv14_user_splice as us

    level, source, _ = _baseline()
    improved = (InputFrame(left=True),) + source[1:]
    stage = UserSpliceStage('218', EndpointGoal(10, 'min-x'), 0, 10)
    evaluator = EndpointEvaluator(level, stage.goal)
    assert evaluator.evaluate(improved).objective_key < evaluator.evaluate(source).objective_key

    events = []
    calls = []

    def fake_backend(level, branch, goal, *, best_callback=None, **kwargs):
        calls.append(branch)
        if len(calls) == 1:
            assert best_callback is not None
            best_callback(improved, 10)
            # The search is STILL executing here, so deferred phase-end writes
            # would not yet exist. A real CLI callback writes LTM and TXT now.
            assert ('checkpoint', '218', improved) in events
            assert any(kind == 'temporary' for kind, *_ in events)
        else:
            assert branch == improved, 'the next continuous phase must inherit the live best'
        return (), 19

    monkeypatch.setattr(us, '_local_search', fake_backend)
    result = optimise_user_splices(
        level, source, [stage],
        RandomSpliceConfig(search_backend='local', iterations=8,
                           rounds=1, workers=1, splice_local_stagnation_rounds=1),
        stage_best_callback=lambda name, frames: events.append(('checkpoint', name, frames)),
        progress=lambda line: events.append(('temporary', line))
        if line.startswith('[auto:user-splice:temporary]') else None,
    )
    assert len(calls) == 2
    assert result.evaluations == 38
    assert [event[0] for event in events].count('checkpoint') == 1
    assert any('min-x' in event[1] for event in events if event[0] == 'temporary')


def test_wrapped_auto_and_local_publish_native_best_callback(monkeypatch):
    import nv14_auto_endpoint as auto
    import nv14_random_splice as random_splice
    level, source, _ = _baseline()
    goal = EndpointGoal(10, 'min-x')
    changed = (InputFrame(left=True),) + source[1:]
    seen = []

    def fake_auto(level, frames, goal, config, **kwargs):
        kwargs['best_callback'](SimpleNamespace(
            frames=changed, evaluation=SimpleNamespace(frame=10)))
        return None, None, 7

    def fake_local(level, frames, **kwargs):
        kwargs['best_callback'](SimpleNamespace(
            frames=changed, evaluation=SimpleNamespace(frame=10)))
        return SimpleNamespace(candidates=(), frontier=(), evaluations=11, interrupted=False)

    monkeypatch.setattr(auto, 'optimise_auto_endpoint_campaign', fake_auto)
    monkeypatch.setattr(random_splice, 'optimise_local_population', fake_local)
    for backend, used in [('endpoint-auto', 7), ('local', 11)]:
        _, evaluations = _local_search(
            level, source, goal, start=0,
            config=RandomSpliceConfig(search_backend=backend, iterations=4,
                                      workers=1, rounds=1),
            iterations=4, rounds=0, stagnation_rounds=1, seed=2,
            best_callback=lambda frames, frame: seen.append((backend, frames, frame)))
        assert evaluations == used
    assert seen == [('endpoint-auto', changed, 10), ('local', changed, 10)]


def test_cli_writes_ltm_and_txt_during_running_backend(tmp_path, monkeypatch):
    """The real CLI file writer is reached by live callbacks, not phase-end."""
    import sys
    import nv14_user_splice as us
    from nv14_cli import main
    from nv14_ltm import LtmMovie, LEVEL_DATABASE_NAME
    from tests.test_ltm import _write_ltm, _basic_config, _level_record

    body = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    input_lines = ['|Mboot:0|', '|K20|Mboot:1|']
    input_lines.extend('|Kff53|' if frame.right else '|' for frame in body)
    input_lines.extend(('|K61|Mpost:0|', '|Mpost:1|', '|Mpost:2|'))
    source_ltm = _write_ltm(tmp_path / '00-0.ltm',
                            ('\n'.join(input_lines) + '\n').encode(),
                            config=_basic_config(frame_count=len(input_lines)))
    database = tmp_path / LEVEL_DATABASE_NAME
    database.write_text(_level_record() + '\n')
    goals = tmp_path / 'goals'
    goals.mkdir()
    (goals / '230.txt').write_text('[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    config = tmp_path / 'multi.toml'
    config.write_text('[auto]\nsplice-files=["230"]\nsplice-search="local"\n'
                      'splice-iterations=4\nsplice-local-stagnation-rounds=1\n'
                      'runs=1\nbeam=4\nseed=0\n')
    stage_movie = tmp_path / 'optim_230.ltm'
    stage_txt = tmp_path / '00-0_230.txt'
    stage_alias = tmp_path / '00-0_230.ltm'
    inspected = []

    def fake_backend(level, branch, goal, *, best_callback=None, **kwargs):
        if not inspected:
            assert best_callback is not None
            # The first frame of this movie is neutral; left improves min-x.
            candidate = (InputFrame(left=True),) + tuple(branch[1:])
            assert EndpointEvaluator(level, goal).evaluate(candidate).objective_key < (
                EndpointEvaluator(level, goal).evaluate(branch).objective_key)
            best_callback(candidate, goal.target_frame)
            # Assert all three stage files ALREADY EXIST while backend is active.
            assert stage_movie.is_file() and stage_txt.is_file() and stage_alias.is_file()
            assert LtmMovie.load(stage_movie).replay_frames
            assert stage_alias.read_bytes() == stage_movie.read_bytes()
            inspected.append(True)
        return (), 1

    monkeypatch.setattr(us, '_local_search', fake_backend)
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(source_ltm),
        '--config', str(config), '--levels-file', str(database),
        '--auto-splice-directory', str(goals), '--output', str(tmp_path / 'optim.ltm'),
        '--replay-output', str(tmp_path / '00-0.txt'), '--workers', '1',
    ])
    main()
    assert inspected

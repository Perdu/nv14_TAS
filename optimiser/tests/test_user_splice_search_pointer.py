"""A Ctrl+C leaves the exact active phase and its backend round resumable."""
import json
import sys

import pytest

import nv14_user_splice as us
from nv14_cli import main
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_replay import encode_complex_replay
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_run_restores_interrupted_phase_and_completed_outer_pass(monkeypatch):
    level, source, _ = _baseline()
    stages = [UserSpliceStage('a', EndpointGoal(10,'min-x'),0,10),
              UserSpliceStage('end', EndpointGoal(10,'min-x'),0,10)]
    config = RandomSpliceConfig(search_backend='local', iterations=2, workers=1,
                                frontier=1, rounds=3, splice_local_stagnation_rounds=1,
                                seed=7)
    search_state = {}
    entries = []
    interrupted = False

    def save(pointer):
        if pointer is None:
            search_state.clear()
        else:
            search_state.clear()
            search_state.update(pointer)

    def backend(level, branch, goal, *, seed, checkpoint_path, resume, **kwargs):
        nonlocal interrupted
        entries.append((goal, branch, seed, resume))
        if len(entries) == 3 and not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        return (), 0

    monkeypatch.setattr(us, '_local_search', backend)
    def run(resume=None):
        return optimise_user_splices(level, source, stages, config,
            completion_policy='checkpoint',
            resume_state=resume, save_resume_state=save,
            backend_checkpoint_path=lambda name, backend: f'/tmp/no-checkpoint-{name}-{backend}.json')
    with pytest.raises(KeyboardInterrupt):
        run()
    interrupted_stage = search_state['stage']
    interrupted_round = search_state['round_no']
    interrupted_seed = search_state['phase']['seed']
    assert interrupted_round >= 0
    run(dict(search_state))
    assert entries[3][2] == interrupted_seed
    assert entries[3][3] is True
    assert not search_state


def test_saves_resume_pointer_before_running_backend(monkeypatch):
    level, source, _ = _baseline()
    config = RandomSpliceConfig(search_backend='local', iterations=2, workers=1,
                                rounds=1, splice_local_stagnation_rounds=1)
    saved = []
    def backend(*args, **kwargs):
        assert saved and saved[-1] is not None
        raise KeyboardInterrupt
    monkeypatch.setattr(us, '_local_search', backend)
    with pytest.raises(KeyboardInterrupt):
        optimise_user_splices(level, source,
            [UserSpliceStage('a', EndpointGoal(10,'min-x'),0,10)], config,
            completion_policy='checkpoint',
            save_resume_state=saved.append,
            backend_checkpoint_path=lambda *args: '/tmp/dummy.json')
    assert saved[-1]['phase']['backend'] == 'local'
    assert saved[-1]['stage'] == 'a'


def test_cli_survives_ctrl_c_then_resumes_saved_stage_and_backend(tmp_path, monkeypatch):
    import nv14_user_splice as us
    from nv14_cli import main
    from nv14_replay import encode_complex_replay
    from pathlib import Path
    level, source, _ = _baseline()
    input_file = tmp_path/'source.txt'
    input_file.write_text(f'$test#author#{level.source_level_string}#'
                          f'{encode_complex_replay(source)}#\n')
    goals = tmp_path / 'goals'
    goals.mkdir()
    for name in ('a','end'):
        (goals/f'{name}.txt').write_text('[local]\nobjective="min-x"\n'
                                          'target-frame=10\nrange="0:10"\n')
    conf = tmp_path/'conf.toml'
    conf.write_text('[auto]\nsplice-files=["a","end"]\n'
                    'splice-search="local"\nsplice-iterations=2\n'
                    'splice-local-stagnation-rounds=1\n'
                    'runs=2\nbeam=3\nseed=5\n')
    args = ['optimize_replay.py','auto',str(input_file),'--config',str(conf),
            '--auto-splice-directory',str(goals),'--output',str(tmp_path/'optim.txt'),
            '--replay-output',str(tmp_path/'replay.txt'), '--workers','1']
    calls=[]
    interrupted=False
    def backend(level, branch, goal, *, checkpoint_path, resume, seed, **kw):
        nonlocal interrupted
        calls.append((branch, seed, resume, str(checkpoint_path)))
        if len(calls)==2 and not interrupted:
            interrupted=True
            assert Path(checkpoint_path).parent==tmp_path
            Path(checkpoint_path).write_text('snapshot-survives')
            raise KeyboardInterrupt
        return (),0
    monkeypatch.setattr(us,'_local_search',backend)
    monkeypatch.setattr(sys,'argv',args)
    with pytest.raises(SystemExit) as stop:
        main()
    assert stop.value.code == 130
    state_path=tmp_path/'optim.splice-search.json'
    assert state_path.exists()
    state=json.loads(state_path.read_text())
    assert state['stage']=='end' and state['round_no']==0
    checkpoint=Path(calls[-1][3])
    assert checkpoint.read_text()=='snapshot-survives'
    monkeypatch.setattr(sys,'argv',args)
    main()
    assert len(calls)>2 and calls[2][2] is True
    assert calls[2][1]==calls[1][1]
    assert not state_path.exists()


def test_completed_pass_marker_resumes_remaining_passes(monkeypatch):
    level, source, _ = _baseline()
    stage = UserSpliceStage('a', EndpointGoal(10,'min-x'), 0, 10)
    config = RandomSpliceConfig(rounds=5, iterations=2)
    calls = []
    markers = []
    def search(*args, **kwargs):
        calls.append(True)
        if len(calls)==2:
            raise KeyboardInterrupt
        return (),0,1
    monkeypatch.setattr(us,'_search_stage',search)
    with pytest.raises(KeyboardInterrupt):
        optimise_user_splices(level, source, [stage], config,
            completion_policy='checkpoint', save_outer_round=markers.append)
    assert markers == [1]
    monkeypatch.setattr(us,'_search_stage',lambda *args, **kwargs: ((),0,1))
    repeated = []
    optimise_user_splices(level, source,[stage],config,
        completion_policy='checkpoint', resume_outer_round=markers[-1],
        save_outer_round=repeated.append)
    assert repeated == [2,3,4,5,None]

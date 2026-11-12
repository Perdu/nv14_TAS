"""Direct shortcuts preserve backend/budgets and publish named bests afterward."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import tas
from nv14_standalone_checkpoint import post_search_propagation_requested


def setup_files(tmp_path, monkeypatch, *, route=True):
    root = tmp_path / 'optimiser'
    root.mkdir()
    goals = tmp_path / 'splices' / 'demo'
    goals.mkdir(parents=True)
    (goals / 'end.txt').write_text('[local]\nsearch="population"\n'
                                     'objective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    config = root / 'examples' / 'config.toml'
    config.parent.mkdir()
    config.write_text('[auto]\niterations=50500\n[multi-splicer]\n'
                      'iterations=10000\nmerge-bests=true\nmerge-repair-at-end=true\n'
                      'merge-retime-gains=true\n')
    if route:
        (goals / 'multi-splicer.toml').write_text('[multi-splicer]\nsplice-files=["end"]\n')
    monkeypatch.setattr(tas, 'ROOT', root)
    return root, goals, config


@pytest.mark.parametrize('mode,backend', [('auto','auto'), ('goal','auto'),
                                           ('local','local'), ('both','both'),
                                           ('hybrid','hybrid')])
def test_direct_backend_no_premerge_or_route_config(tmp_path, monkeypatch, mode, backend):
    setup_files(tmp_path, monkeypatch)
    cmd = tas.build_command(mode, 'demo', 'end', env={}, extra=['--workers','3'])
    assert cmd[2] == backend
    assert '--splice-config' not in cmd
    assert '--single-splice' not in cmd
    if backend == 'auto':
        assert cmd[cmd.index('--goal-config') + 1] == '../splices/demo/end.txt'
    if backend == 'local':
        assert '--stagnation-rounds' not in cmd
    if backend in ('both','hybrid'):
        assert '--no-propagation' in cmd


def test_post_search_order_and_opt_out(tmp_path, monkeypatch):
    setup_files(tmp_path, monkeypatch)
    events = []
    def run(command, **_kw):
        events.append(('run', command[2], list(command)))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(tas.subprocess, 'run', run)
    import nv14_standalone_checkpoint as pub
    monkeypatch.setattr(pub, 'publish_named_checkpoint',
                        lambda **_kw: events.append(('publish',)) or True)
    assert tas.main(['auto','demo','end','--auto-runs','100'], env={}) == 0
    assert [item[0] for item in events] == ['run','publish','run']
    assert '--goal-config' in events[0][2]
    assert '--auto-runs' in events[0][2]
    assert events[0][2][-2:] == ['--auto-runs','100']
    assert events[2][1] == 'auto' and '--repair' in events[2][2]
    events.clear()
    assert tas.main(['auto','demo','end','--no-propagation'], env={}) == 0
    assert [item[0] for item in events] == ['run','publish']
    assert '--no-propagation' not in events[0][2]


def test_no_route_never_runs_post_propagation(tmp_path, monkeypatch):
    setup_files(tmp_path, monkeypatch, route=False)
    calls = []
    monkeypatch.setattr(tas.subprocess, 'run', lambda c, **_k:
                        calls.append(c) or SimpleNamespace(returncode=0))
    import nv14_standalone_checkpoint as pub
    monkeypatch.setattr(pub, 'publish_named_checkpoint', lambda **_k: True)
    tas.main(['auto','demo','end'], env={})
    assert len(calls) == 1


def test_propagation_flags_are_augments_not_standalone_modes(tmp_path, monkeypatch):
    root, goals, config = setup_files(tmp_path, monkeypatch)
    assert post_search_propagation_requested(config, goals/'multi-splicer.toml') == (True, True)
    config.write_text('[multi-splicer]\nmerge-retime-gains=true\n')
    assert post_search_propagation_requested(config, goals/'multi-splicer.toml') == (False, True)
    config.write_text('[multi-splicer]\nmerge-only=true\n')
    assert post_search_propagation_requested(config, goals/'multi-splicer.toml') == (False, False)


def test_native_checkpoint_copy_retains_main_result_and_nonregression(tmp_path):
    from nv14_engine import InputFrame
    from nv14_ltm import LEVEL_DATABASE_NAME, LtmMovie
    from tests.test_ltm import _write_ltm, _basic_config, _level_record
    from nv14_standalone_checkpoint import publish_named_checkpoint

    level_dir = tmp_path / 'n_levels'
    level_dir.mkdir()
    goals = tmp_path / 'splices' / '00-0'
    goals.mkdir(parents=True)
    work = tmp_path / 'wip'
    work.mkdir()
    (goals / 'end.txt').write_text('[local]\nsearch="population"\n'
                                    'objective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    frames = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    rows = ['|Mboot:0|', '|K20|Mboot:1|']
    rows.extend('|Kff53|' if f.right else '|' for f in frames)
    rows.extend(('|K61|Mpost:0|', '|Mpost:1|', '|Mpost:2|'))
    source = _write_ltm(level_dir / '00-0.ltm', ('\n'.join(rows)+'\n').encode(),
                        config=_basic_config(frame_count=len(rows)))
    levels = tmp_path / LEVEL_DATABASE_NAME
    levels.write_text(_level_record() + '\n')
    output = work / '00-0.ltm'
    output.write_bytes(source.read_bytes())
    original = output.read_bytes()
    kwargs = dict(input_path=source, output_path=output,
                  replay_output_path=work/'00-0.txt', goal_path=goals/'end.txt',
                  name='end', levels_file_path=levels)
    assert publish_named_checkpoint(**kwargs)
    assert not publish_named_checkpoint(**kwargs)
    assert output.read_bytes() == original
    assert LtmMovie.load(work / '00-0_end.ltm').replay_frames
    assert (work / '00-0_end.frontier.json').is_file()
    # Same level/range/goal identity as a later multi-splicer loader.
    from nv14_cli import (parse_arguments, _load_named_splice_stages,
                         _load_user_splice_frontiers, _user_splice_output_paths)
    from nv14_engine import parse_level_string
    from nv14_cli import _load_source
    record = _load_source(source, levels_file_path=levels,
                          explicit_level_id=None, ltm_postroll=None,
                          probe_ltm_neutral_tail=False)
    level = parse_level_string(record.combined.level_string, simulate_enemies=True)
    args = parse_arguments(['auto', str(source), '--auto-splice-files', 'end',
                            '--auto-splice-directory', str(goals)])
    stages = _load_named_splice_stages(level, frames, args, goals, ('end',))
    destinations = _user_splice_output_paths(('end',), output, work/'00-0.txt')
    restored = _load_user_splice_frontiers(level, stages, destinations)
    assert restored.get('end')


def test_stopped_search_can_publish_saved_direct_improvement(tmp_path, monkeypatch):
    setup_files(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(tas.subprocess, 'run', lambda _c, **_k: SimpleNamespace(returncode=130))
    import nv14_standalone_checkpoint as pub
    monkeypatch.setattr(pub, 'publish_named_checkpoint',
                        lambda **_k: calls.append('publish') or True)
    assert tas.main(['auto', 'demo', 'end'], env={}) == 130
    assert calls == ['publish']


def test_local_windows_goal_does_not_attempt_population_checkpoint(tmp_path, monkeypatch):
    _root, goals, _config = setup_files(tmp_path, monkeypatch, route=False)
    (goals / 'end.txt').write_text('[local]\nsearch="windows"\n'
                                     'objective="min-x"\ntarget-frame=10\n')
    calls = []
    monkeypatch.setattr(tas.subprocess, 'run', lambda cmd, **_kw:
                        calls.append(cmd) or SimpleNamespace(returncode=0))
    import nv14_standalone_checkpoint as pub
    monkeypatch.setattr(pub, 'publish_named_checkpoint',
                        lambda **_kw: pytest.fail('window search was published as population'))
    assert tas.main(['local', 'demo', 'end'], env={}) == 0
    assert len(calls) == 1


def test_auto_direct_budget_comes_from_auto_table_not_multi_splicer(tmp_path, monkeypatch):
    root, _, config = setup_files(tmp_path, monkeypatch)
    monkeypatch.chdir(root)
    from nv14_cli import parse_arguments
    args = parse_arguments(tas.build_command(
        'auto', 'demo', 'end', env={}, extra=['--auto-runs', '100'])[2:])
    assert args.iterations == 50500
    assert args.auto_runs == 100
    assert not args.auto_random_splice
    assert not args.auto_splice_files

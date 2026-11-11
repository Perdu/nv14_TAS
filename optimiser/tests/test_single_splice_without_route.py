"""An individual named goal saves multi-splicer-compatible bests without a route TOML."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

import tas
from nv14_cli import _apply_no_splice_propagation, main, parse_arguments


def _setup(tmp_path: Path, monkeypatch, *, extension: str = '.txt'):
    root = tmp_path / 'optimiser'
    root.mkdir()
    goals = tmp_path / 'splices' / '00-0'
    goals.mkdir(parents=True)
    (goals / ('442' + extension)).write_text(
        '[local]\nsearch = "population"\nobjective = "min-x"\n'
        'target-frame = 10\nrange = "0:10"\n')
    (root / 'examples').mkdir()
    (root / 'examples' / 'config.toml').write_text(
        '[auto]\nruns=1\n'
        '[multi-splicer]\nsearch="hybrid"\n'
        'merge-bests=true\nmerge-repair-at-end=true\n'
        'merge-retime-gains=true\nmerge-only=true\n')
    monkeypatch.setattr(tas, 'ROOT', root)
    return root, goals


@pytest.mark.parametrize('mode,backend', [
    ('auto', 'endpoint-auto'), ('goal', 'endpoint-auto'),
    ('local', 'local'), ('both', 'both'), ('hybrid', 'hybrid'),
])
def test_no_route_named_goal_uses_one_stage_checkpoint_writer(tmp_path, monkeypatch, mode, backend):
    _setup(tmp_path, monkeypatch)
    argv = tas.build_command(mode, '00-0', '442', env={})
    assert argv[2] == 'auto'
    assert '--splice-config' not in argv
    assert '--no-propagation' in argv
    assert argv[argv.index('--auto-splice-files') + 1] == '442'
    assert argv[argv.index('--single-splice') + 1] == '442'
    assert argv[argv.index('--auto-splice-search') + 1] == backend
    args = parse_arguments(argv[2:])
    assert args.auto_splice_files == ('442',)
    assert args.auto_splice_start == args.auto_splice_stop == '442'
    assert args.auto_splice_search == backend
    _apply_no_splice_propagation(args)
    assert not args.auto_splice_merge_only
    assert not args.auto_splice_merge_bests
    assert not args.auto_splice_merge_repair_at_end
    assert not args.auto_splice_merge_retime_gains


def test_no_route_named_toml_goal_is_discovered(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, extension='.toml')
    argv = tas.build_command('hybrid', '00-0', '442', env={})
    assert argv[argv.index('--single-splice') + 1] == '442'
    assert argv[argv.index('--auto-splice-directory') + 1] == '../splices/00-0'


def test_unrelated_legacy_launches_are_unchanged(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    argv = tas.build_command('auto', '00-0', env={})
    assert argv[2] == 'auto' and '--auto-splice-files' not in argv
    assert '--single-splice' not in argv
    # A missing per-stage goal cannot silently write a checkpoint under a
    # different name; older Local/Hybrid shortcuts still take their normal path.
    assert tas.build_command('local', '00-0', 'missing', env={})[2] == 'local'
    assert tas.build_command('hybrid', '00-0', 'missing', env={})[2] == 'hybrid'
    with pytest.raises(ValueError, match='named goal file'):
        tas.build_command('auto', '00-0', 'missing', env={})


def test_no_route_cli_saves_ltm_and_later_named_route_can_load_it(tmp_path, monkeypatch, capsys):
    from nv14_engine import InputFrame
    from nv14_ltm import LtmMovie, LEVEL_DATABASE_NAME
    from tests.test_ltm import _write_ltm, _basic_config, _level_record
    import nv14_user_splice as us

    root, goals = _setup(tmp_path, monkeypatch)
    source_dir = tmp_path / 'n_levels'
    source_dir.mkdir()
    body = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    rows = ['|Mboot:0|', '|K20|Mboot:1|']
    rows.extend('|Kff53|' if frame.right else '|' for frame in body)
    rows.extend(('|K61|Mpost:0|', '|Mpost:1|', '|Mpost:2|'))
    source = _write_ltm(source_dir / '00-0.ltm',
                        ('\n'.join(rows) + '\n').encode(),
                        config=_basic_config(frame_count=len(rows)))
    database = tmp_path / LEVEL_DATABASE_NAME
    database.write_text(_level_record() + '\n')
    output = root / 'wip' / '00-0.ltm'
    output.parent.mkdir()
    replay = output.with_suffix('.txt')

    searched = []
    def no_candidates(_level, _branch, stage, _config, _rng, **_kwargs):
        searched.append(stage.name)
        return (), 0, 1
    monkeypatch.setattr(us, '_search_stage', no_candidates)
    env = {
        'TAS_INPUT_TEMPLATE': str(source),
        'TAS_GOAL_TEMPLATE': str(goals / '{splice}.txt'),
        'TAS_MULTI_TEMPLATE': str(goals / 'multi-splicer.toml'),
        'TAS_OUTPUT_TEMPLATE': str(output),
        'TAS_REPLAY_TEMPLATE': str(replay),
        'TAS_CONFIG': str(root / 'examples' / 'config.toml'),
    }
    cmd = tas.build_command('hybrid', '00-0', '442', env=env,
                            extra=['--levels-file', str(database), '--auto-runs', '1',
                                   '--workers', '1'])
    monkeypatch.setattr(sys, 'argv', ['optimize_replay.py', *cmd[2:]])
    main()
    assert searched == ['442'], 'Hybrid must not search any later splice'
    checkpoint = root / 'wip' / '00-0_442.ltm'
    checkpoint_txt = root / 'wip' / '00-0_442.txt'
    assert checkpoint.is_file()
    assert checkpoint_txt.is_file()
    assert (root / 'wip' / '00-0_442.frontier.json').is_file()
    assert LtmMovie.load(checkpoint).replay_frames
    assert not output.exists(), 'a stage checkpoint must not replace a completed replay'
    assert '[auto:user-splice:' in capsys.readouterr().out

    # Introducing a multi-splicer.toml later must not hide or invalidate the
    # already saved stage. Summary-only mode loads the checkpoint read-only.
    route = goals / 'multi-splicer.toml'
    route.write_text('[multi-splicer]\nsplice-files=["442"]\n')
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(source), '--config', env['TAS_CONFIG'],
        '--splice-config', str(route), '--output', str(output),
        '--replay-output', str(replay), '--levels-file', str(database),
        '--ls-splice', '--workers', '1',
    ])
    before = checkpoint.read_bytes()
    main()
    assert checkpoint.read_bytes() == before
    listed = capsys.readouterr().out
    assert "checkpoint propagation (1/1 saved)" in listed
    assert "'442'" in listed


def test_no_route_local_window_goal_keeps_legacy_local(tmp_path, monkeypatch):
    _root, goals = _setup(tmp_path, monkeypatch)
    (goals / '442.txt').write_text(
        '[local]\nsearch="windows"\nobjective="min-x"\n'
        'target-frame=10\nrange="0:10"\n')
    argv = tas.build_command('local', '00-0', '442', env={})
    assert argv[2] == 'local'
    assert '--single-splice' not in argv

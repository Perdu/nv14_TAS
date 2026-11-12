"""Single-splice mode keeps the multi-splicer archive, never the next search."""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import tas
from nv14_cli import parse_arguments, _apply_no_splice_propagation, _start_selects_alternate_route


def _config(root: Path, *, alternate: bool = False) -> Path:
    directory = root.parent / 'splices' / '92-3'
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / 'multi-splicer.toml'
    file.write_text(
        '[multi-splicer]\n'
        'splice-files = ["98", "159", "236", "272", "end"]\n'
        + ('alt-route = ["98", "211", "246", "272"]\n' if alternate else '')
        + 'search = "hybrid"\n'
        'merge-bests = true\nmerge-repair-at-end = true\n'
        'merge-retime-gains = true\n'
    )
    for name in ("98", "159", "236", "272", "211", "246", "end"):
        (directory / (name + ".txt")).write_text(
            '[local]\nsearch="population"\nobjective="min-x"\n'
            'target-frame=25\nrange="0:25"\n')
    return file


def _workspace(tmp_path: Path, monkeypatch):
    root = tmp_path / 'optimiser'
    root.mkdir()
    (root / 'examples').mkdir()
    (root / 'examples' / 'config.toml').write_text('[auto]\n')
    monkeypatch.setattr(tas, 'ROOT', root)
    monkeypatch.chdir(root)
    return root


@pytest.mark.parametrize('mode,command_mode', [
    ('auto', 'auto'), ('goal', 'auto'), ('local', 'local'),
    ('both', 'both'), ('hybrid', 'hybrid')])
def test_named_shortcuts_keep_the_standalone_backend(tmp_path, monkeypatch, mode, command_mode):
    _config(_workspace(tmp_path, monkeypatch))
    argv = tas.build_command(mode, '92-3', '159', env={})
    assert argv[2] == command_mode
    assert '--goal-config' in argv if mode != 'local' else '--config' in argv
    assert '--single-splice' not in argv
    assert '--splice-config' not in argv
    if mode in ('auto', 'goal'):
        parsed = parse_arguments(argv[2:])
        assert not parsed.auto_splice_files
        assert not parsed.auto_random_splice
    if mode == 'hybrid':
        parsed = parse_arguments(argv[2:])
        assert parsed.auto_splice_files == ('159',)
        assert parsed.auto_splice_search == 'hybrid'


def test_auto_without_selected_splice_stays_standalone(tmp_path, monkeypatch):
    _config(_workspace(tmp_path, monkeypatch))
    argv = tas.build_command('auto', '92-3', env={})
    assert argv[2] == 'auto'
    assert '--splice-config' not in argv and '--single-splice' not in argv
    assert '--goal-config' not in argv


def test_auto_named_splice_shortcut_uses_direct_goal(tmp_path, monkeypatch, capsys):
    _config(_workspace(tmp_path, monkeypatch))
    assert tas.main(['auto', '92-3', '159', '--dry-run'], env={}) == 0
    output = capsys.readouterr().out
    assert '--goal-config ../splices/92-3/159.txt' in output
    assert '--single-splice' not in output


def test_no_route_preserves_standalone_local_hybrid_auto(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    assert tas.build_command('local', '92-3', '159', env={})[2] == 'local'
    assert tas.build_command('hybrid', '92-3', '159', env={})[2] == 'hybrid'
    assert tas.build_command('auto', '92-3', env={})[2] == 'auto'
    with pytest.raises(ValueError, match='named goal file'):
        tas.build_command('auto', '92-3', '159', env={})


def test_alternate_only_stage_is_selectable_with_one_stage_boundary(tmp_path):
    config = _config(tmp_path / 'optimiser', alternate=True)
    args = parse_arguments(['auto', 'source.ltm', '--splice-config', str(config),
                            '--single-splice', '211', '--auto-splice-search', 'hybrid'])
    assert args.auto_splice_start == args.auto_splice_stop == '211'
    assert args.auto_splice_alt_route == ('98', '211', '246', '272', 'end')
    assert _start_selects_alternate_route(args.auto_splice_files,
                                          args.auto_splice_alt_route,
                                          args.auto_splice_single)


def test_no_propagation_disables_merging_but_not_stage_selection(tmp_path):
    config = _config(tmp_path / 'optimiser')
    args = parse_arguments(['auto', 'source.ltm', '--splice-config', str(config),
                            '--single-splice', '159', '--no-propagation'])
    _apply_no_splice_propagation(args)
    assert args.auto_splice_start == args.auto_splice_stop == '159'
    assert not args.auto_splice_merge_bests
    assert not args.auto_splice_merge_repair_at_end
    assert not args.auto_splice_merge_retime_gains
    assert not args.auto_splice_merge_only
    assert not args.auto_splice_merge_repair_only


def test_explicit_merge_and_no_propagation_are_contradictory(tmp_path):
    config = _config(tmp_path / 'optimiser')
    args = parse_arguments(['auto', 'source.ltm', '--splice-config', str(config),
                            '--single-splice', '159', '--no-propagation', '--merge'])
    with pytest.raises(SystemExit, match='cannot be combined'):
        _apply_no_splice_propagation(args)


def test_single_splice_conflicting_start_is_rejected(tmp_path):
    config = _config(tmp_path / 'optimiser')
    with pytest.raises(SystemExit, match='cannot select a different'):
        parse_arguments(['auto', 'source.ltm', '--splice-config', str(config),
                         '--single-splice', '159', '--start-at-splice', '236'])


def _native_level_fixture(tmp_path):
    from nv14_replay import encode_complex_replay
    from tests.test_random_splice import _baseline
    level, frames, _ = _baseline()
    source_file = tmp_path / 'source.txt'
    source_file.write_text(f'$test#author#{level.source_level_string}#'
                           f'{encode_complex_replay(frames)}#\n')
    goal_directory = tmp_path / 'goals'
    goal_directory.mkdir()
    for name, frame in [('98', 10), ('159', 12), ('236', 15), ('end', 18)]:
        (goal_directory / f'{name}.txt').write_text(
            f'[local]\nsearch="population"\nobjective="max-x"\n'
            f'target-frame={frame}\nrange="0:{frame}"\n')
    config = tmp_path / 'route.toml'
    config.write_text('[multi-splicer]\nsplice-files=["98","159","236","end"]\n'
                      'merge-bests=true\nmerge-repair-at-end=true\n'
                      'merge-retime-gains=true\n')
    return source_file, goal_directory, config


def test_real_cli_single_hybrid_keeps_only_selected_stage_and_checkpoint(tmp_path, monkeypatch):
    import sys
    import nv14_user_splice as us
    from nv14_cli import main

    source, goals, config = _native_level_fixture(tmp_path)
    selected = []
    monkeypatch.setattr(us, '_search_stage',
                        lambda _level, _branch, stage, _config, _rng, **kwargs:
                        (selected.append(stage.name) or ((), 0, 1)))
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(source), '--splice-config', str(config),
        '--auto-splice-directory', str(goals), '--single-splice', '159',
        '--auto-splice-search', 'hybrid', '--no-propagation',
        '--auto-runs', '1', '--output', str(tmp_path / 'best.txt'),
        '--workers', '1'])
    main()
    assert selected == ['159']
    assert (tmp_path / 'best_159.txt').is_file()
    assert (tmp_path / 'best_98.txt').is_file()  # independently evaluated baseline
    assert not (tmp_path / 'best.txt').is_file()  # no verified full completion


def test_cli_passes_enabled_merge_repair_and_retime_for_single_stage(tmp_path, monkeypatch):
    import sys
    import nv14_user_splice as us
    from nv14_cli import main
    from nv14_user_splice import UserSpliceResult

    source, goals, config = _native_level_fixture(tmp_path)
    captured = []
    def spy(_level, frames, stages, _config, **kwargs):
        captured.append((tuple(s.name for s in stages), kwargs))
        return UserSpliceResult(tuple(frames), 0, 0, 0)
    monkeypatch.setattr(us, 'optimise_user_splices', spy)
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(source), '--splice-config', str(config),
        '--auto-splice-directory', str(goals), '--single-splice', '159',
        '--auto-splice-search', 'hybrid', '--auto-runs', '1',
        '--output', str(tmp_path / 'best.txt'), '--workers', '1'])
    main()
    assert len(captured) == 1
    stages, kwargs = captured[0]
    assert stages == ('98', '159', '236', 'end')
    assert kwargs['start_at'] == kwargs['stop_at'] == '159'
    assert kwargs['merge_stage_bests'] is True
    assert kwargs['merge_repair_at_end'] is True
    assert kwargs['merge_retime_gains'] is True
    assert kwargs['merge_only'] is False

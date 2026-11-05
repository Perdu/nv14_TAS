"""Independent named-splice route sequences share only verified completed bests."""
from __future__ import annotations

import sys

import pytest

import nv14_user_splice as us
from nv14_cli import main, parse_arguments
from tests.test_user_splice_list_summary import _setup


def _make_routes(tmp_path):
    level, source, saved, output, packed, argv = _setup(tmp_path)
    goals = tmp_path / 'goals'
    (goals / '240.txt').write_text(
        '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    routes = tmp_path / 'routes.toml'
    routes.write_text('[multi-splicer]\nsplice-files=["230","end"]\n'
                      'alt-route=["230","240","end"]\n')
    return level, source, output, argv + ['--splice-config', str(routes)]


def test_alt_route_toml_cli_and_validation(tmp_path):
    _level, _source, _output, argv = _make_routes(tmp_path)
    args = parse_arguments(argv[1:])
    assert args.auto_splice_files == ('230', 'end')
    assert args.auto_splice_alt_route == ('230', '240', 'end')
    args = parse_arguments(argv[1:] + ['--splice-alt-route', '230,end'])
    assert args.auto_splice_alt_route == ('230', 'end')
    with pytest.raises(SystemExit, match='alternate routes cannot be combined'):
        parse_arguments(argv[1:] + ['--splice-start', '240'])


def test_cli_searches_both_orders_and_shares_verified_best(tmp_path, monkeypatch, capsys):
    _level, source, output, argv = _make_routes(tmp_path)
    calls = []

    def fake_search(level, frames, stages, config, **kwargs):
        calls.append((tuple(stage.name for stage in stages),
                      kwargs.get('saved_final_frames'), kwargs.get('resume_state'),
                      kwargs.get('backend_checkpoint_path')))
        return us.UserSpliceResult(tuple(frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', fake_search)
    monkeypatch.setattr(sys, 'argv', argv + ['--ls-splice'])
    main()
    assert len(calls) == 2
    assert calls[0][0] == ('230', 'end')
    assert calls[1][0] == ('230', '240', 'end')
    assert calls[1][2] is None
    assert callable(calls[1][3])
    assert not output.exists()
    assert 'alternate:' in capsys.readouterr().out


def test_alt_route_rejects_absent_goal_files(tmp_path, monkeypatch):
    _level, _source, _output, argv = _make_routes(tmp_path)
    (tmp_path / 'goals' / '240.txt').unlink()
    monkeypatch.setattr(sys, 'argv', argv + ['--ls-splice'])
    with pytest.raises((ValueError, SystemExit, FileNotFoundError)):
        main()


def test_normal_runs_share_verified_primary_completed_replay(tmp_path, monkeypatch):
    _level, source, _output, argv = _make_routes(tmp_path)
    calls = []

    def fake_search(_level, frames, stages, config, **kwargs):
        calls.append((tuple(stage.name for stage in stages),
                      kwargs.get('saved_final_frames'),
                      kwargs.get('save_resume_state')))
        return us.UserSpliceResult(tuple(frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', fake_search)
    monkeypatch.setattr(sys, 'argv', argv + ['--auto-runs', '1'])
    main()
    assert [item[0] for item in calls] == [('230', 'end'), ('230', '240', 'end')]
    assert tuple(calls[1][1]) == tuple(source)
    assert calls[0][2] is not None  # primary preserves normal restart behavior
    assert calls[1][2] is None      # alternate cannot consume primary backend resume


def test_unlimited_primary_cannot_silently_starve_alt_route(tmp_path, monkeypatch):
    _level, _source, _output, argv = _make_routes(tmp_path)
    monkeypatch.setattr(sys, 'argv', argv + ['--auto-runs', '0'])
    with pytest.raises(SystemExit, match='requires finite --auto-runs'):
        main()


def test_actual_native_search_checks_both_routes(tmp_path, monkeypatch, capsys):
    """Exercise the real search, not just route-dispatch mocks."""
    _level, _source, _output, argv = _make_routes(tmp_path)
    monkeypatch.setattr(sys, 'argv', argv + [
        '--auto-runs', '1', '--auto-splice-search', 'local',
        '--auto-splice-iterations', '4'])
    main()
    messages = capsys.readouterr().out
    assert "stage 2/2 'end'" in messages
    assert 'alternate: 230 -> 240 -> end' in messages
    assert "stage 2/3 '240'" in messages
    assert "stage 3/3 'end'" in messages

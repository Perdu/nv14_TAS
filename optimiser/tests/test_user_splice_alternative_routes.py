"""Alternative route searches only the divergent branch stages."""
from __future__ import annotations

import sys

import pytest

import nv14_user_splice as us
from nv14_cli import main, parse_arguments, _expand_named_splice_alt_route
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
    assert calls[1][0] == ('240',)
    assert calls[1][2] is None
    assert callable(calls[1][3])
    assert not output.exists()
    assert 'alternate branch:' in capsys.readouterr().out


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
    assert [item[0] for item in calls] == [('230', 'end'), ('240',)]
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
    assert "alternate branch: 240 (shared prefix through '230'; rejoin at 'end')" in messages
    assert "stage 1/1 '240'" in messages


def test_alt_route_runs_only_unique_branch_before_rejoin(tmp_path, monkeypatch):
    _level, _source, _saved, _output, _packed, argv = _setup(tmp_path)
    goals = tmp_path / 'goals'
    (goals / '240.txt').write_text("""[local]
objective=\"min-x\"
target-frame=10
range=\"0:10\"
""")
    (goals / '250.txt').write_text("""[local]
objective=\"min-x\"
target-frame=10
range=\"0:10\"
""")
    routes = tmp_path / 'routes.toml'
    routes.write_text("""[multi-splicer]
splice-files=[\"230\",\"250\",\"end\"]
alt-route=[\"230\",\"240\",\"250\",\"end\"]
""")
    calls = []

    def fake_search(_level, frames, stages, config, **kwargs):
        calls.append(tuple(stage.name for stage in stages))
        return us.UserSpliceResult(tuple(frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', fake_search)
    monkeypatch.setattr(sys, 'argv', argv + ['--splice-config', str(routes), '--auto-runs', '1'])
    main()
    assert calls == [('230', '250', 'end'), ('240',)]


def test_short_alt_route_expands_seams_in_original_order():
    primary = ("48", "85", "103", "137", "207", "275", "358",
               "403", "479", "527", "599", "655", "728", "795",
               "870", "955", "1031", "1071", "1109", "end")
    short = ("403", "482", "485", "527")
    expected = primary[:8] + ("482", "485") + primary[9:]
    assert _expand_named_splice_alt_route(primary, short) == expected
    # The original full-route format remains accepted verbatim.
    assert _expand_named_splice_alt_route(primary, expected) == expected


@pytest.mark.parametrize(('short', 'error'), [
    (("403", "482"), "at least one divergent"),
    (("404", "482", "527"), "start and end"),
    (("403", "482", "528"), "start and end"),
    (("527", "482", "403"), "must follow"),
    (("403", "479", "527"), "must not duplicate"),
    (("403", "482", "482", "527"), "duplicate names"),
])
def test_short_alt_route_rejects_invalid_seams(short, error):
    primary = ("403", "479", "527", "end")
    with pytest.raises(ValueError, match=error):
        _expand_named_splice_alt_route(primary, short)


def test_short_alt_route_toml_and_cli_only_search_divergent_stages(tmp_path, monkeypatch):
    _level, _source, _saved, _output, _packed, argv = _setup(tmp_path)
    goals = tmp_path / 'goals'
    for name in ('240', '250'):
        (goals / f'{name}.txt').write_text(
            '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    routes = tmp_path / 'routes.toml'
    routes.write_text('[multi-splicer]\nsplice-files=["230","250","end"]\n'
                      'alt-route=["230","240","250"]\n')
    args = parse_arguments(argv[1:] + ['--splice-config', str(routes)])
    assert args.auto_splice_alt_route == ('230', '240', '250', 'end')
    # Explicit CLI overrides use the same short notation.
    cli_args = parse_arguments(argv[1:] + ['--splice-config', str(routes),
                                          '--splice-alt-route', '230,240,250'])
    assert cli_args.auto_splice_alt_route == args.auto_splice_alt_route
    calls = []

    def fake_search(_level, frames, stages, config, **kwargs):
        calls.append(tuple(stage.name for stage in stages))
        return us.UserSpliceResult(tuple(frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', fake_search)
    monkeypatch.setattr(sys, 'argv', argv + ['--splice-config', str(routes), '--auto-runs', '1'])
    main()
    assert calls == [('230', '250', 'end'), ('240',)]

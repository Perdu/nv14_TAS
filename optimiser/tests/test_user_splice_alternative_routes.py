"""Alternative route searches only the divergent branch stages."""
from __future__ import annotations

import sys

import pytest

import nv14_user_splice as us
from nv14_cli import (main, parse_arguments, _expand_named_splice_alt_route,
                     _start_selects_alternate_route)
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
    args = parse_arguments(argv[1:] + ['--start-at-splice', 'end'])
    assert args.auto_splice_start == 'end'
    with pytest.raises(SystemExit, match='alternate routes cannot be combined'):
        parse_arguments(argv[1:] + ['--splice-stop', 'end'])


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
    assert [item[0] for item in calls] == [
        ('230',), ('240',), ('end',), ('end',)]
    assert calls[0][2] is not None  # phase-specific resume-state callback
    assert calls[1][2] is not None  # distinct checkpoints; no primary state is reused


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
    assert "shared-prefix: 230" in messages
    assert "alternate-branch: 240" in messages
    assert "primary-rejoin: end" in messages
    assert "alternate-rejoin: end" in messages
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
    assert calls == [('230',), ('240',), ('250',), ('250',), ('end',)]


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
    assert calls == [('230',), ('240',), ('250',), ('250',), ('end',)]


def test_start_at_first_primary_divergence_skips_seam_but_runs_alt_branch(
    tmp_path, monkeypatch, capsys,
):
    _level, _source, _saved, _output, _packed, argv = _setup(tmp_path)
    goals = tmp_path / 'goals'
    for name in ('239', '240', '250'):
        (goals / f'{name}.txt').write_text(
            '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    routes = tmp_path / 'routes.toml'
    routes.write_text('[multi-splicer]\nsplice-files=["230","239","250","end"]\n'
                      'alt-route=["230","240","250"]\n')
    calls = []

    def fake_search(_level, frames, stages, config, **kwargs):
        calls.append((tuple(stage.name for stage in stages), kwargs.get('start_at')))
        return us.UserSpliceResult(tuple(frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', fake_search)
    monkeypatch.setattr(sys, 'argv', argv + [
        '--splice-config', str(routes), '--auto-runs', '1', '--start-at-splice', '239'])
    main()
    assert calls == [
        (('239',), None), (('240',), None), (('250',), None),
        (('250',), None), (('end',), None)]
    assert "alternate-branch: 240" in capsys.readouterr().out


def test_start_at_rejoin_skips_earlier_alt_branch(tmp_path, monkeypatch, capsys):
    _level, _source, _output, argv = _make_routes(tmp_path)
    calls = []

    def fake_search(_level, frames, stages, config, **kwargs):
        calls.append((tuple(stage.name for stage in stages), kwargs.get('start_at')))
        return us.UserSpliceResult(tuple(frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', fake_search)
    monkeypatch.setattr(sys, 'argv', argv + [
        '--auto-runs', '1', '--start-at-splice', 'end'])
    main()
    assert calls == [(('230', 'end'), 'end')]
    assert "alternate branch skipped" in capsys.readouterr().out


def test_interleaved_rejoin_saves_other_route_and_reuses_both(tmp_path, monkeypatch):
    """A slower branch must survive as an independently reloadable checkpoint."""
    from nv14_engine import InputFrame
    from nv14_replay import decode_complex_replay, editable_frames
    from nv14_cli import _load_user_splice_frontiers, _user_splice_output_paths
    level, source, _saved, output, packed, argv = _setup(tmp_path)
    alternate = (InputFrame(left=True),) + tuple(source[1:])
    goals = tmp_path / 'goals'
    for name in ('239', '240', '250'):
        (goals / f'{name}.txt').write_text(
            '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    routes = tmp_path / 'routes.toml'
    routes.write_text('[multi-splicer]\nsplice-files=["230","239","250","end"]\n'
                      'alt-route=["230","240","250"]\n')
    calls = []

    def fake_search(_level, frames, stages, config, **kwargs):
        names = tuple(stage.name for stage in stages)
        calls.append((names, tuple(frames), kwargs.get('initial_seeds', ())))
        candidate = alternate if names == ('240',) else tuple(frames)
        if kwargs.get('stage_result_callback') is not None:
            kwargs['stage_result_callback'](names[-1], candidate)
        return us.UserSpliceResult(tuple(frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', fake_search)
    monkeypatch.setattr(sys, 'argv', argv + [
        '--splice-config', str(routes), '--auto-runs', '1',
        '--start-at-splice', '239'])
    main()
    assert [names for names, _, _ in calls] == [
        ('239',), ('240',), ('250',), ('250',), ('end',)]
    # Alternate won the seam (lower min-x), primary is saved independently.
    assert tuple(editable_frames(decode_complex_replay(
        (tmp_path / '97-1_250.txt').read_text()).frames)) == alternate
    other_path = tmp_path / '97-1_250_other_route.txt'
    assert other_path.is_file()
    assert tuple(editable_frames(decode_complex_replay(other_path.read_text()).frames)) == tuple(source)
    assert (tmp_path / 'optim_250_other_route.txt').is_file()
    assert tuple(calls[-1][1]) == alternate
    assert tuple(calls[-1][2][0]) == tuple(source)
    stage_outputs = _user_splice_output_paths(('250',), output, packed)
    from nv14_cli import _load_named_splice_stages, parse_arguments
    args = parse_arguments(argv[1:] + ['--splice-config', str(routes)])
    stage = _load_named_splice_stages(level, source, args, goals, ('250',))
    archived = _load_user_splice_frontiers(level, stage, stage_outputs)['250']
    assert alternate in archived and tuple(source) in archived


def test_interleaved_rejoin_old_other_route_remains_best_on_rerun(tmp_path, monkeypatch):
    from nv14_engine import InputFrame
    from nv14_replay import decode_complex_replay, editable_frames
    _level, source, _saved, _output, _packed, argv = _setup(tmp_path)
    best_alt = (InputFrame(left=True),) + tuple(source[1:])
    stronger_main = (InputFrame(),) + tuple(source[1:])
    goals = tmp_path / 'goals'
    for name in ('239', '240', '250'):
        (goals / f'{name}.txt').write_text(
            '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    routes = tmp_path / 'routes.toml'
    routes.write_text('[multi-splicer]\nsplice-files=["230","239","250","end"]\n'
                      'alt-route=["230","240","250"]\n')
    main_candidate = [stronger_main]

    def fake_search(_level, frames, stages, config, **kwargs):
        names = tuple(stage.name for stage in stages)
        candidate = (best_alt if names == ('240',)
                     else main_candidate[0] if names == ('239',)
                     else tuple(frames))
        cb = kwargs.get('stage_result_callback')
        if cb is not None:
            cb(names[-1], candidate)
        return us.UserSpliceResult(tuple(frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', fake_search)
    monkeypatch.setattr(sys, 'argv', argv + [
        '--splice-config', str(routes), '--auto-runs', '1',
        '--start-at-splice', '239'])
    main()
    other_path = tmp_path / '97-1_250_other_route.txt'
    assert tuple(editable_frames(decode_complex_replay(other_path.read_text()).frames)) == stronger_main
    # Second run has a worse primary candidate. Preserve its historical best.
    main_candidate[0] = tuple(source)
    main()
    assert tuple(editable_frames(decode_complex_replay(other_path.read_text()).frames)) == stronger_main


def test_reconvergence_initial_seeds_survive_small_frontier(monkeypatch):
    from nv14_engine import InputFrame
    from nv14_endpoint import EndpointGoal
    from nv14_random_splice import RandomSpliceConfig
    from nv14_user_splice import UserSpliceStage, optimise_user_splices
    from tests.test_random_splice import _baseline

    level, source, _ = _baseline()
    alternate = (InputFrame(left=True),) + tuple(source[1:])
    stages = (UserSpliceStage('end', EndpointGoal(10, 'min-x'), 0, 10),)
    seen = []

    def no_mutations(_level, frames, *_args, **_kwargs):
        seen.append(tuple(frames))
        return [], 0, 1

    monkeypatch.setattr(us, '_search_stage', no_mutations)
    observed = []
    optimise_user_splices(
        level, source, stages,
        RandomSpliceConfig(iterations=4, workers=1, rounds=1, frontier=1),
        completion_policy='checkpoint', initial_seeds=(alternate,),
        stage_result_callback=lambda name, frames: observed.append((name, frames)))
    assert seen == [tuple(source), alternate]
    assert observed[-1] == ('end', alternate)


def test_interleaved_merges_consider_both_routes_before_and_after_search(
        tmp_path, monkeypatch):
    _level, _source, _saved, _output, _packed, argv = _setup(tmp_path)
    goals = tmp_path / 'goals'
    for name in ('239', '240', '250'):
        (goals / f'{name}.txt').write_text(
            '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    routes = tmp_path / 'routes.toml'
    routes.write_text('[multi-splicer]\nsplice-files=["230","239","250","end"]\n'
                      'alt-route=["230","240","250"]\n')
    calls = []

    def fake_search(_level, frames, stages, config, **kwargs):
        calls.append((tuple(stage.name for stage in stages),
                      kwargs.get('merge_only', False),
                      kwargs.get('merge_repair_only', False)))
        return us.UserSpliceResult(tuple(frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', fake_search)
    monkeypatch.setattr(sys, 'argv', argv + [
        '--splice-config', str(routes), '--auto-runs', '1',
        '--start-at-splice', '239', '--splice-merge-bests'])
    main()
    assert calls == [
        (('230', '239', '240', '250', 'end'), True, False),
        (('239',), False, False),
        (('240',), False, False),
        (('250',), False, False),
        (('250',), False, False),
        (('end',), False, False),
        (('230', '239', '240', '250', 'end'), True, False),
    ]


def test_alt_summary_displays_all_route_lines_without_writes(tmp_path, monkeypatch, capsys):
    """A summary includes divergent stages AND the shared prefix/rejoin."""
    from nv14_replay import encode_complex_replay
    _level, source, output, argv = _make_routes(tmp_path)
    (tmp_path / '97-1_240.txt').write_text(encode_complex_replay(source) + '\n')
    original = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_kw:
                        pytest.fail('summary invoked search'))
    monkeypatch.setattr(sys, 'argv', argv + ['--ls-splice'])
    main()
    stdout = capsys.readouterr().out
    assert '[auto:user-splice:summary:route] alternate: 230 -> 240 -> end' in stdout
    assert "[auto:user-splice:summary:propagated] '240'" in stdout or (
        "[auto:user-splice:summary:pending] '240'" in stdout)
    assert "[auto:user-splice:summary:empty] 'end'" in stdout
    assert '[alternate route]' in stdout
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == original
    assert not output.exists()



def _setup_alt_start_dispatch(tmp_path, monkeypatch, primary, alt):
    """Build a real CLI fixture; mock only the native completion probe."""
    from types import SimpleNamespace
    import nv14_cli as cli
    from nv14_engine import InputFrame
    from nv14_replay import encode_complex_replay
    from tests.test_auto import _running_exit_level

    level = _running_exit_level()
    frames = (InputFrame(right=True),) * 29
    source = tmp_path / 'source.txt'
    source.write_text(f'$test#author#{level.source_level_string}#'
                      f'{encode_complex_replay(frames)}#\n')
    goals = tmp_path / 'goals'
    goals.mkdir()
    for name in set((*primary, *alt)):
        (goals / f'{name}.txt').write_text(
            '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    cfg = tmp_path / 'config.toml'
    cfg.write_text('[auto]\nsplice-search="both"\nsplice-iterations=4\n'
                   'runs=1\nseed=0\n')
    routes = tmp_path / 'routes.toml'
    import json
    routes.write_text('[multi-splicer]\n'
                      'splice-files=' + json.dumps(list(primary)) + '\n'
                      'alt-route=' + json.dumps(list(alt)) + '\n')
    monkeypatch.setattr(cli, 'evaluate_replay_with_sentinel',
                        lambda _level, replay, **_kw: SimpleNamespace(
                            valid=True, finish_tick=len(replay)))
    return ['optimize_replay.py', 'auto', str(source), '--config', str(cfg),
            '--auto-splice-directory', str(goals),
            '--output', str(tmp_path / 'best.txt'),
            '--replay-output', str(tmp_path / 'best-replay.txt'),
            '--splice-config', str(routes), '--auto-runs', '1']


def test_start_at_alternate_exclusive_stage_searches_its_route_suffix(
    tmp_path, monkeypatch, capsys,
):
    """Reproduce --start-at-splice 211 with the user's exact short branch."""
    primary = ('98', '159', '236', '272', 'end')
    alternate = ('98', '211', '246', '272')
    argv = _setup_alt_start_dispatch(tmp_path, monkeypatch, primary, alternate)
    parsed = parse_arguments(argv[1:] + ['--start-at-splice', '211'])
    assert parsed.auto_splice_alt_route == ('98', '211', '246', '272', 'end')
    calls = []

    def fake_search(_level, frames, stages, config, **kwargs):
        calls.append((tuple(stage.name for stage in stages), kwargs.get('start_at')))
        return us.UserSpliceResult(tuple(frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', fake_search)
    monkeypatch.setattr(sys, 'argv', argv + [
        '--start-at-splice', '211', '--splice-speed', 'fast'])
    main()
    assert calls == [(('98', '211', '246', '272', 'end'), '211')]
    output = capsys.readouterr().out
    assert "'211' selects the alternate route" in output
    assert 'alternate-branch:' not in output


def test_start_at_second_alternate_stage_keeps_shared_rejoin_and_end(
    tmp_path, monkeypatch,
):
    argv = _setup_alt_start_dispatch(
        tmp_path, monkeypatch, ('230', '239', '250', 'end'),
        ('230', '240', '241', '250'))
    calls = []

    def fake_search(_level, frames, stages, config, **kwargs):
        calls.append((tuple(stage.name for stage in stages), kwargs.get('start_at')))
        return us.UserSpliceResult(tuple(frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', fake_search)
    monkeypatch.setattr(sys, 'argv', argv + ['--start-at-splice', '241'])
    main()
    assert calls == [(('230', '240', '241', '250', 'end'), '241')]


def test_start_at_unlisted_stage_reports_both_routes(tmp_path, monkeypatch):
    argv = _setup_alt_start_dispatch(
        tmp_path, monkeypatch, ('98', '159', '236', '272', 'end'),
        ('98', '211', '246', '272'))
    monkeypatch.setattr(sys, 'argv', argv + ['--start-at-splice', '212'])
    with pytest.raises(SystemExit, match='start splice .*not in either named route'):
        main()


@pytest.mark.parametrize(('start', 'expected'), [
    ('211', True), ('246', True), ('98', False), ('272', False),
    ('159', False), ('236', False), ('missing', False), (None, False),
])
def test_explicit_start_route_selection_for_primary_and_short_alt(start, expected):
    primary = ('98', '159', '236', '272', 'end')
    alternate = _expand_named_splice_alt_route(primary, ('98', '211', '246', '272'))
    assert alternate == ('98', '211', '246', '272', 'end')
    assert _start_selects_alternate_route(primary, alternate, start) is expected

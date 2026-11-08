"""--ls-splice is a strictly read-only view of saved stage propagation."""
from __future__ import annotations

import sys

import pytest

import nv14_user_splice as us
from nv14_cli import main, parse_arguments
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_random_splice import RandomSpliceConfig
from nv14_replay import encode_complex_replay
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_summary_only_reports_saved_scores_without_running_search(monkeypatch):
    level, source, _ = _baseline()
    improved = (InputFrame(left=True),) + source[1:]
    goal = EndpointGoal(10, 'min-x')
    assert EndpointEvaluator(level, goal).evaluate(improved).objective_key < (
        EndpointEvaluator(level, goal).evaluate(source).objective_key)
    stages = [UserSpliceStage('230', goal, 0, 10),
              UserSpliceStage('end', goal, 0, 10)]

    def fail(*args, **kwargs):
        raise AssertionError('summary-only attempted an optimization or write')

    monkeypatch.setattr(us, '_search_stage', fail)
    messages = []
    result = optimise_user_splices(
        level, source, stages,
        RandomSpliceConfig(rounds=20, iterations=4, workers=1),
        saved_stage_candidates={'230': [improved]},
        completion_policy='checkpoint', summary_only=True,
        progress=messages.append, stage_best_callback=fail,
        best_callback=fail)
    assert (result.attempts, result.improvements, result.evaluations) == (0, 0, 0)
    assert sum('checkpoint propagation' in s for s in messages) == 1
    assert any('[auto:user-splice:summary:pending]' in s and "'230'" in s for s in messages)
    assert any('[auto:user-splice:summary:empty]' in s and "'end'" in s for s in messages)
    assert not any('[auto:user-splice:initial]' in s for s in messages)
    assert not any('[auto:user-splice:budget]' in s for s in messages)


def _write_combined(path, level, frames):
    path.write_text(f'$test#author#{level.source_level_string}#'
                    f'{encode_complex_replay(frames)}#\n')


def _setup(tmp_path):
    level, source, _ = _baseline()
    saved = (InputFrame(left=True),) + source[1:]
    input_file = tmp_path / 'source.txt'
    _write_combined(input_file, level, source)
    goals = tmp_path / 'goals'
    goals.mkdir()
    for name in ('230', 'end'):
        (goals / f'{name}.txt').write_text(
            '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    cfg = tmp_path / 'config.toml'
    cfg.write_text('[auto]\nsplice-files=["230","end"]\n'
                   'splice-search="both"\nsplice-iterations=4\n'
                   'runs=2\nbeam=4\nseed=0\n')
    output = tmp_path / 'optim.txt'
    packed = tmp_path / '97-1.txt'
    argv = ['optimize_replay.py', 'auto', str(input_file), '--config', str(cfg),
            '--auto-splice-directory', str(goals), '--output', str(output),
            '--replay-output', str(packed), '--workers', '1']
    return level, source, saved, output, packed, argv


def test_cli_short_flag_reads_saved_final_and_never_writes(tmp_path, monkeypatch, capsys):
    level, source, saved, output, packed, argv = _setup(tmp_path)
    _write_combined(output, level, saved)  # full run meets the saved checkpoint
    stage_checkpoint = tmp_path / '97-1_230.txt'
    stage_checkpoint.write_text(encode_complex_replay(saved) + '\n')
    initial = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw: pytest.fail('started search'))
    monkeypatch.setattr(sys, 'argv', [*argv, '-l'])
    main()
    stdout = capsys.readouterr().out
    assert 'checkpoint propagation' in stdout
    assert "[auto:user-splice:summary:propagated] '230'" in stdout
    assert "[auto:user-splice:summary:empty] 'end'" in stdout
    assert 'stage searches' not in stdout
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == initial


@pytest.mark.parametrize("flag", ["--ls-splice", "--ls-splices"])
def test_long_flag_works_without_saved_final_and_does_not_create_baseline(
        tmp_path, monkeypatch, capsys, flag):
    _level, _source, _saved, output, _packed, argv = _setup(tmp_path)
    assert not output.exists()
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw: pytest.fail('started search'))
    monkeypatch.setattr(sys, 'argv', [*argv, flag])
    main()
    stdout = capsys.readouterr().out
    assert stdout.count('[auto:user-splice:summary:empty]') == 2
    assert 'checkpoint propagation (0/2 saved)' in stdout
    assert not output.exists()
    assert not list(tmp_path.glob('optim_*.txt'))
    assert not list(tmp_path.glob('97-1_*.txt'))


def test_flag_requires_named_user_mode_and_output(tmp_path, monkeypatch):
    _level, _source, _saved, _out, _packed, argv = _setup(tmp_path)
    for flag in ('-l', '--ls-splice', '--ls-splices'):
        args = parse_arguments([*argv[1:], flag])
        assert args.auto_ls_splice is True
    monkeypatch.setattr(sys, 'argv', [*argv[:3], '-l'])
    with pytest.raises(SystemExit, match='requires named multi-splicer'):
        main()
    monkeypatch.setattr(sys, 'argv', [*argv[:3], '--config', argv[4],
                                  '--auto-splice-directory', argv[6], '-l'])
    with pytest.raises(SystemExit, match='requires --output'):
        main()


def test_ltm_splice_summary_is_read_only(tmp_path, monkeypatch, capsys):
    from nv14_ltm import LEVEL_DATABASE_NAME, LtmMovie
    from tests.test_ltm import _write_ltm, _basic_config, _level_record

    body = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    lines = ['|Mboot:0|', '|K20|Mboot:1|']
    lines.extend('|Kff53|' if frame.right else '|' for frame in body)
    lines.extend(('|K61|Mpost:0|', '|Mpost:1|', '|Mpost:2|'))
    source_ltm = _write_ltm(tmp_path / '00-0.ltm',
                            ('\n'.join(lines) + '\n').encode(),
                            config=_basic_config(frame_count=len(lines)))
    database = tmp_path / LEVEL_DATABASE_NAME
    database.write_text(_level_record() + '\n')
    goals = tmp_path / 'goals'
    goals.mkdir()
    (goals / '230.txt').write_text('[local]\nobjective="min-x"\n'
                                   'target-frame=10\nrange="0:10"\n')
    cfg = tmp_path / 'config.toml'
    cfg.write_text('[auto]\nsplice-files=["230"]\n'
                   'splice-iterations=4\nsplice-rounds=1\nruns=1\nbeam=4\nseed=0\n')
    movie = tmp_path / 'optim_230.ltm'
    movie.write_bytes(source_ltm.read_bytes())
    output = tmp_path / 'optim.ltm'
    replay = tmp_path / '00-0.txt'
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw: pytest.fail('started search'))
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(source_ltm), '--config', str(cfg),
        '--levels-file', str(database), '--auto-splice-directory', str(goals),
        '--output', str(output), '--replay-output', str(replay), '-l'])
    main()
    assert 'checkpoint propagation (1/1 saved)' in capsys.readouterr().out
    after = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert after == before
    assert not output.exists()
    assert LtmMovie.load(movie).replay_frames


@pytest.mark.parametrize("extra", [
    ["--merge"],
    ["--repair"],
    ["--retime-gains"],
    ["--merge", "--repair", "--retime-gains", "--from", "230",
     "--to", "completed", "--at", "10"],
    ["--splice-from-best", "end"],
    ["--splice-start", "end", "--splice-stop", "end"],
])
def test_summary_takes_priority_over_merge_repair_and_search_options(
        tmp_path, monkeypatch, capsys, extra):
    level, _source, saved, output, _packed, argv = _setup(tmp_path)
    _write_combined(output, level, saved)
    (tmp_path / '97-1_230.txt').write_text(encode_complex_replay(saved) + '\n')
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(us, '_search_stage',
                        lambda *a, **kw: pytest.fail('summary started search'))
    monkeypatch.setattr(us, 'repair_suffix_grafts',
                        lambda *a, **kw: pytest.fail('summary started repair'))
    monkeypatch.setattr(sys, 'argv', [*argv, '-l', *extra])
    main()
    text = capsys.readouterr().out
    assert 'checkpoint propagation' in text
    assert 'before merges' not in text
    assert 'bridge repair' not in text
    assert '[auto:user-splice:merge-only]' not in text
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_summary_ignores_merge_only_and_repair_in_splice_toml(
        tmp_path, monkeypatch, capsys):
    level, _source, saved, output, _packed, argv = _setup(tmp_path)
    _write_combined(output, level, saved)
    config = tmp_path / 'multi-splicer.toml'
    config.write_text('[multi-splicer]\n'
                      'merge-only=true\nmerge-repair-only=true\n'
                      'merge-retime-gains=true\nmerge-repair-at-end=true\n')
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(us, '_search_stage',
                        lambda *a, **kw: pytest.fail('summary started search'))
    monkeypatch.setattr(us, 'repair_suffix_grafts',
                        lambda *a, **kw: pytest.fail('summary started repair'))
    monkeypatch.setattr(sys, 'argv', [*argv, '--splice-config', str(config), '-l'])
    main()
    text = capsys.readouterr().out
    assert 'checkpoint propagation' in text
    assert '[auto:user-splice:merge-only]' not in text
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before

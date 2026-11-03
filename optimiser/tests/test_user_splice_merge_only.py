"""Patch 46: merge saved named splice bests once, without starting search."""
from __future__ import annotations

import sys

import pytest

import nv14_user_splice as us
from nv14_cli import main, parse_arguments
from nv14_auto import evaluate_replay_with_sentinel
from nv14_engine import InputFrame
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_replay import encode_complex_replay
from nv14_replay import decode_complex_replay, parse_combined_level_replay
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline
from tests.test_user_splice_list_summary import _setup


def _forbid_search(*_args, **_kwargs):
    pytest.fail("merge-only must not start an Auto/Local search")


def test_option_is_opt_in_and_supported_by_multi_splicer_toml(tmp_path):
    args = parse_arguments(['auto', 'replay.ltm', '--splice-merge-only'])
    assert args.auto_splice_merge_only is True
    assert args.auto_splice_merge_bests is False  # implied at execution, not in parsing
    assert parse_arguments(['auto', 'replay.ltm']).auto_splice_merge_only is False
    config = tmp_path / 'multi-splicer.toml'
    config.write_text('[multi-splicer]\nfiles=["first", "end"]\nmerge-only=true\n')
    args = parse_arguments(['auto', 'replay.ltm', '--splice-config', str(config)])
    assert args.auto_splice_merge_only is True
    assert args.auto_splice_mode == 'user'
    assert args.auto_random_splice is True


def test_merge_only_skips_search_initial_saves_and_resume_sidecars(monkeypatch):
    level, source, _ = _baseline()
    stages = [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
              for name in ('first', 'last')]
    messages, writes = [], []
    monkeypatch.setattr(us, '_search_stage', _forbid_search)
    result = optimise_user_splices(
        level, source, stages, RandomSpliceConfig(rounds=0, iterations=4),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        progress=messages.append,
        stage_best_callback=lambda *values: writes.append(('stage', values)),
        best_callback=lambda *values: writes.append(('final', values)),
        frontier_callback=lambda *values: writes.append(('frontier', values)),
        save_resume_state=_forbid_search, save_outer_round=_forbid_search,
        backend_checkpoint_path=_forbid_search,
        resume_state={'corrupted': 'yes'}, resume_outer_round=500,
    )
    assert (result.attempts, result.evaluations, result.improvements) == (0, 0, 0)
    assert writes == []
    assert any('missing both checkpoints' in m for m in messages)
    assert any('0 attempted' in m and '0 verified join' in m for m in messages)
    assert any('after merges: checkpoint propagation' in m for m in messages)
    assert not any('[auto:user-splice:initial]' in m or '[auto:user-splice:budget]' in m
                   for m in messages)


def test_merge_only_physically_verified_join_upgrades_saved_stage(monkeypatch):
    level, source, _ = _baseline()
    earlier = (InputFrame(left=True),) + source[1:]
    stages = [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
              for name in ('first', 'last')]
    prior = EndpointEvaluator(level, stages[1].goal).evaluate(source)
    saved, frontiers, messages = [], [], []
    monkeypatch.setattr(us, '_search_stage', _forbid_search)
    result = optimise_user_splices(
        level, source, stages, RandomSpliceConfig(rounds=0, iterations=4),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_stage_candidates={'first': [earlier], 'last': [source]},
        progress=messages.append,
        stage_best_callback=lambda name, frames: saved.append((name, frames)),
        frontier_callback=lambda name, frames: frontiers.append((name, frames)),
    )
    assert result.attempts == result.evaluations == 0
    assert len(saved) == 1 and saved[0][0] == 'last'
    after = EndpointEvaluator(level, stages[1].goal).evaluate(saved[0][1])
    assert after.feasible and after.objective_key < prior.objective_key
    assert any(name == 'last' for name, _ in frontiers)
    assert any('verified join' in m and '1 stage best' in m for m in messages)
    assert any('vs input run:' in m and 'vs best run:' in m
               for m in messages if 'new saved stage best' in m)


def test_merge_only_reports_failed_physical_join_without_writes(monkeypatch):
    level, source, _ = _baseline()
    earlier = (InputFrame(left=True),) + source[1:]
    stages = [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
              for name in ('first', 'last')]
    monkeypatch.setattr(us, '_search_stage', _forbid_search)
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_kw: ())
    writes, messages = [], []
    result = optimise_user_splices(
        level, source, stages, RandomSpliceConfig(rounds=0, iterations=4),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_stage_candidates={'first': [earlier], 'last': [source]},
        progress=messages.append, stage_best_callback=lambda *_a: writes.append('stage'),
        frontier_callback=lambda *_a: writes.append('frontier'),
        best_callback=lambda *_a: writes.append('final'))
    assert result.improvements == 0 and writes == []
    assert any('rejected (no physically compatible seam)' in m for m in messages)
    assert any('attempted' in m and 'rejected' in m for m in messages)


def test_merge_only_does_not_publish_incomplete_graft_in_checkpoint_mode(monkeypatch):
    level, full_source, _ = _baseline()
    source = full_source[:20]
    earlier = (InputFrame(left=True),) + source[1:]
    stages = [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
              for name in ('first', 'last')]
    saved_stage, saved_final, messages = [], [], []
    monkeypatch.setattr(us, '_search_stage', _forbid_search)
    result = optimise_user_splices(
        level, source, stages, RandomSpliceConfig(rounds=0, iterations=4),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_stage_candidates={'first': [earlier], 'last': [source]},
        progress=messages.append, stage_best_callback=lambda *args: saved_stage.append(args),
        best_callback=saved_final.append)
    assert saved_stage and saved_stage[0][0] == 'last'
    assert saved_final == []
    assert result.improvements == 0
    assert any('0 completed best(s) improved' in m for m in messages)


def test_cli_merge_only_no_saved_checkpoints_makes_no_files(tmp_path, monkeypatch, capsys):
    _level, _source, _saved, _output, _packed, argv = _setup(tmp_path)
    # A merge-only invocation must neither reset nor consume in-flight search
    # resume/progress files, including if their contents are incompatible.
    (tmp_path / 'optim.splice-search.json').write_text('{"old":"state"}\n')
    (tmp_path / 'optim.splice-progress.json').write_text('{"old":"progress"}\n')
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(us, '_search_stage', _forbid_search)
    monkeypatch.setattr(sys, 'argv', [*argv, '--splice-merge-only', '--auto-runs', '0'])
    main()
    stdout = capsys.readouterr().out
    assert '[auto:user-splice:merge-only] done:' in stdout
    assert '0 attempted' in stdout
    assert 'stage searches' not in stdout
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_cli_merge_only_can_be_enabled_via_multi_splicer_toml(tmp_path, monkeypatch, capsys):
    _level, _source, _saved, _output, _packed, argv = _setup(tmp_path)
    config = tmp_path / 'config.toml'
    with config.open('a') as stream:
        stream.write('\n[multi-splicer]\nmerge-only=true\n')
    monkeypatch.setattr(us, '_search_stage', _forbid_search)
    monkeypatch.setattr(sys, 'argv', argv)
    main()
    assert '[auto:user-splice:merge-only] done:' in capsys.readouterr().out


def test_cli_merge_only_writes_only_genuinely_improved_saved_stages(tmp_path, monkeypatch, capsys):
    level, source, _saved, output, _packed, argv = _setup(tmp_path)
    earlier = (InputFrame(left=True),) + source[1:]
    first = tmp_path / '97-1_230.txt'
    last = tmp_path / '97-1_end.txt'
    first.write_text(encode_complex_replay(earlier) + '\n')
    last.write_text(encode_complex_replay(source) + '\n')
    old_first = first.read_bytes()
    old_last = last.read_bytes()
    monkeypatch.setattr(us, '_search_stage', _forbid_search)
    monkeypatch.setattr(sys, 'argv', [*argv, '--splice-merge-only'])
    main()
    stdout = capsys.readouterr().out
    assert '1 stage best(s) improved' in stdout
    assert first.read_bytes() == old_first
    assert last.read_bytes() != old_last
    # The graft is better at min-x but does not finish earlier. Helper-only
    # gains are saved to the stage file, not misreported as completed wins.
    assert not output.exists()
    assert '0 completed best(s) improved' in stdout
    assert not (tmp_path / 'optim.splice-search.json').exists()
    assert not (tmp_path / 'optim.splice-progress.json').exists()
    assert not any('stage searches' in line for line in stdout.splitlines())


def test_merge_only_keeps_better_verified_final(tmp_path, monkeypatch):
    _level, source, _saved, output, _packed, argv = _setup(tmp_path)
    earlier = (InputFrame(left=True),) + source[1:]
    (tmp_path / '97-1_230.txt').write_text(encode_complex_replay(earlier) + '\n')
    (tmp_path / '97-1_end.txt').write_text(encode_complex_replay(source) + '\n')
    monkeypatch.setattr(us, '_search_stage', _forbid_search)
    monkeypatch.setattr(sys, 'argv', [*argv, '--splice-merge-only'])
    # The existing completed replay remains the ranking baseline and must
    # never be replaced by a graft that improves only a helper objective.
    output.write_text(f'$test#author#{_level.source_level_string}#'
                      f'{encode_complex_replay(source)}#\n')
    original = output.read_bytes()
    main()
    main()
    assert output.read_bytes() == original


@pytest.mark.parametrize('extra, message', [
    (['--ls-splice'], 'cannot be combined with --ls-splice'),
    (['--splice-from-best', '230'], 'uses all saved named splice bests'),
    (['--splice-reference', 'reference.txt'], 'uses all saved named splice bests'),
    (['--splice-start', '230'], 'uses all saved named splice bests'),
])
def test_cli_rejects_conflicting_modes(tmp_path, monkeypatch, extra, message):
    _level, _source, _saved, _output, _packed, argv = _setup(tmp_path)
    monkeypatch.setattr(sys, 'argv', [*argv, '--splice-merge-only', *extra])
    with pytest.raises(SystemExit, match=message):
        main()


def test_merge_only_rejected_outside_named_multi_splicer(tmp_path, monkeypatch):
    _level, _source, _saved, _output, _packed, argv = _setup(tmp_path)
    monkeypatch.setattr(sys, 'argv', [*argv[:3], '--splice-merge-only',
                                     '--output', str(tmp_path/'test.txt')])
    with pytest.raises(SystemExit, match='requires named multi-splicer'):
        main()


def test_cli_fast_merge_overrides_persistent_repair_at_end(tmp_path, monkeypatch, capsys):
    """Standalone fast merging must work with end-of-run repair configured."""
    _level, _source, _saved, output, _packed, argv = _setup(tmp_path)
    config = tmp_path / 'config.toml'
    with config.open('a') as stream:
        stream.write('\n[multi-splicer]\nmerge-repair-at-end=true\n')
    monkeypatch.setattr(us, '_search_stage', _forbid_search)
    monkeypatch.setattr(us, 'repair_suffix_grafts', _forbid_search)
    monkeypatch.setattr(sys, 'argv', [*argv, '--splice-merge-only'])
    main()
    stdout = capsys.readouterr().out
    assert '[auto:user-splice:merge-only] done:' in stdout
    assert 'bridge repair' not in stdout
    assert not output.with_suffix('.splice-search.json').exists()
    assert not output.with_suffix('.splice-progress.json').exists()

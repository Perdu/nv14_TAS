"""Patch 51: manual positional input is a real merge prefix, including in --merge-only."""
from __future__ import annotations

import sys

import pytest

import nv14_user_splice as us
from nv14_auto import evaluate_replay_with_sentinel
from nv14_cli import main
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_replay import decode_complex_replay, editable_frames
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline
from tests.test_user_splice_list_summary import _setup, _write_combined


def _finished_slow_run(level):
    replay = ((InputFrame(),) * 5 + (InputFrame(right=True),) * 50)
    checked = evaluate_replay_with_sentinel(level, replay)
    assert checked.valid and checked.finish_tick == 34
    return replay[:checked.finish_tick]


def _manual_incomplete_run():
    # Useful early input edits followed by a bad continuation. In particular,
    # the current input cannot be used as a completed output directly.
    return ((InputFrame(right=True),) * 10 + (InputFrame(left=True),) * 19)


def test_merge_only_grafts_incomplete_manual_input_to_saved_completed_suffix(monkeypatch):
    level, _baseline_frames, _ = _baseline()
    manual = _manual_incomplete_run()
    slow_saved_completion = _finished_slow_run(level)
    assert evaluate_replay_with_sentinel(level, manual).finish_tick is None
    messages, completed, stages_saved = [], [], []
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_k: pytest.fail('ran search'))
    stages = [UserSpliceStage('start', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('after', EndpointGoal(20, 'min-x'), 8, 20)]
    result = optimise_user_splices(
        level, manual, stages, RandomSpliceConfig(iterations=4, rounds=0),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_final_frames=slow_saved_completion, progress=messages.append,
        best_callback=completed.append,
        stage_best_callback=lambda *args: stages_saved.append(args),
        save_resume_state=lambda *_a: pytest.fail('wrote resume state'),
        save_outer_round=lambda *_a: pytest.fail('wrote completed rounds'))
    assert result.attempts == result.evaluations == 0
    assert completed and len(completed[-1]) == 29
    assert evaluate_replay_with_sentinel(level, completed[-1]).valid
    assert result.improvements >= 1
    assert any('current input -> saved completed run' in m and
               'verified completed replay' in m for m in messages)
    # Manual prefix and saved suffix were considered despite no stage files.
    assert any('0/2 saved' in m for m in messages)
    assert not stages_saved


def test_merge_only_promotes_better_completed_manual_input(monkeypatch):
    level, faster_input, _ = _baseline()
    slower_saved = _finished_slow_run(level)
    messages, completed = [], []
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_k: pytest.fail('ran search'))
    stages = [UserSpliceStage('start', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('after', EndpointGoal(20, 'min-x'), 8, 20)]
    result = optimise_user_splices(
        level, faster_input, stages, RandomSpliceConfig(iterations=4, rounds=0),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_final_frames=slower_saved, progress=messages.append,
        best_callback=completed.append)
    assert result.improvements == 1
    assert completed == [faster_input]
    assert any('saved manually edited replay' in m for m in messages)


def test_cli_merge_only_saves_faster_manually_edited_input(tmp_path, monkeypatch, capsys):
    level, faster_input, _saved, output, _packed, argv = _setup(tmp_path)
    slower_saved = _finished_slow_run(level)
    _write_combined(output, level, slower_saved)
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_k: pytest.fail('ran search'))
    monkeypatch.setattr(sys, 'argv', [*argv, '--splice-merge-only'])
    main()
    contents = output.read_text()
    decoded = decode_complex_replay(contents.split('#')[-2]).frames
    assert tuple(editable_frames(decoded)) == tuple(editable_frames(faster_input))
    printed = capsys.readouterr().out
    assert f'current input: {(tmp_path / "source.txt").resolve()}' in printed
    assert 'only the positional input is treated as manual edits' in printed
    assert '[auto:user-splice:merge-only] done:' in printed


def test_no_writes_if_input_merge_cannot_physically_join(monkeypatch):
    level, _, _ = _baseline()
    manual = _manual_incomplete_run()
    slow = _finished_slow_run(level)
    stages = [UserSpliceStage('start', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('after', EndpointGoal(20, 'min-x'), 8, 20)]
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_k: pytest.fail('ran search'))
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_kw: ())
    messages, saved = [], []
    result = optimise_user_splices(
        level, manual, stages, RandomSpliceConfig(iterations=4, rounds=0),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_final_frames=slow, merge_verbose=True, progress=messages.append,
        best_callback=lambda *_a: saved.append('completed'),
        stage_best_callback=lambda *_a: saved.append('stage'))
    assert not saved
    assert result.improvements == 0
    assert result.frames == slow
    assert any('current input -> saved completed run' in m and
               'rejected' in m for m in messages)


def test_cli_merge_only_reconnects_incomplete_input_to_saved_final(
        tmp_path, monkeypatch, capsys):
    level, _baseline_replay, _saved, output, packed, argv = _setup(tmp_path)
    manual = _manual_incomplete_run()
    _write_combined(tmp_path / 'source.txt', level, manual)
    _write_combined(output, level, _finished_slow_run(level))
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_k: pytest.fail('ran search'))
    monkeypatch.setattr(sys, 'argv', [*argv, '--splice-merge-only'])
    main()
    decoded = decode_complex_replay(output.read_text().split('#')[-2]).frames
    assert len(decoded) == 29
    assert evaluate_replay_with_sentinel(level, decoded).valid
    assert len(decode_complex_replay(packed.read_text()).frames) == 29
    printed = capsys.readouterr().out
    assert 'current input -> saved completed run' in printed
    assert 'current-input graft attempt(s)' in printed
    assert 'saved' in printed
    assert not (tmp_path / 'optim.splice-search.json').exists()
    assert not (tmp_path / 'optim.splice-progress.json').exists()

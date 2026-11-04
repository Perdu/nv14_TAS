"""Patch 50: splice goals guide search, but cannot veto valid route changes."""
from __future__ import annotations

import sys

import nv14_user_splice as us
from nv14_auto import evaluate_replay_with_sentinel
from nv14_cli import main
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal, EndpointEvaluator, AxisWindow
from nv14_random_splice import RandomSpliceConfig
from nv14_replay import editable_frames
from nv14_user_splice import UserSpliceStage, UserSpliceResult, optimise_user_splices
from tests.test_random_splice import _baseline
from tests.test_user_splice_list_summary import _setup, _write_combined


def _completed(level, delay):
    frames = (InputFrame(left=True),) * delay + (InputFrame(right=True),) * 80
    finish = evaluate_replay_with_sentinel(level, frames).finish_tick
    assert finish is not None
    return frames[:finish]


def test_adaptive_leader_accepts_candidate_that_bypasses_earlier_helper(monkeypatch):
    level, source, original = _baseline()
    point = original.point(10)
    first = UserSpliceStage('first', EndpointGoal(
        10, 'earliest-arrival', target_region=(
            point.x - 1, point.x + 1, point.y - 1, point.y + 1)), 0, 10)
    last = UserSpliceStage('522', EndpointGoal(14, 'min-x'), 0, 14)
    changed = (InputFrame(left=True),) * 10 + source[10:]
    assert not EndpointEvaluator(level, first.goal).evaluate(changed).feasible
    assert EndpointEvaluator(level, last.goal).evaluate(changed).feasible
    checked = []

    def search(_level, _branch, _stage, _config, _rng, *, stage_rank, **kwargs):
        checked.append(stage_rank(changed))
        return ((changed, 14),), 1, 1

    monkeypatch.setattr(us, '_search_stage', search)
    written = []
    optimise_user_splices(level, source, [first, last],
                          RandomSpliceConfig(rounds=1, iterations=2,
                                             search_backend='endpoint-auto',
                                             splice_auto_stagnation_rounds=1),
                          completion_policy='checkpoint', start_at='522',
                          stage_best_callback=lambda name, frames: written.append((name, frames)))
    assert checked and checked[0] is not None
    assert ('522', changed) in written


def test_saved_stage_candidates_are_evaluated_independently(monkeypatch):
    level, source, original = _baseline()
    point = original.point(10)
    first = UserSpliceStage('first', EndpointGoal(
        10, 'earliest-arrival', target_region=(
            point.x - 1, point.x + 1, point.y - 1, point.y + 1)), 0, 10)
    last = UserSpliceStage('522', EndpointGoal(14, 'min-x'), 0, 14)
    changed = (InputFrame(left=True),) * 10 + source[10:]
    assert EndpointEvaluator(level, last.goal).evaluate(changed).feasible
    calls = []
    monkeypatch.setattr(us, '_search_stage', lambda _level, branch, *_a, **_kw:
                        (calls.append(branch) or (), 0, 1))
    logs = []
    optimise_user_splices(level, source, [first, last],
                          RandomSpliceConfig(rounds=1, iterations=2),
                          completion_policy='checkpoint', start_at='522',
                          saved_stage_candidates={'522': [changed]},
                          progress=logs.append)
    assert not any("'522': ignored checkpoint" in line for line in logs)
    assert any("'522': restored" in line for line in logs)


def test_fast_completion_can_improve_even_with_worse_earlier_helper(monkeypatch):
    level, _source, _ = _baseline()
    slow, fast = _completed(level, 3), _completed(level, 0)
    point = evaluate_replay_with_sentinel(level, slow).point(10)
    first = UserSpliceStage('first', EndpointGoal(
        10, 'min-x', x_window=AxisWindow(point.x - 0.5, point.x + 0.5)), 0, 10)
    last = UserSpliceStage('end', EndpointGoal(10, 'max-x'), 0, 10)
    assert EndpointEvaluator(level, first.goal).evaluate(slow).feasible
    assert not EndpointEvaluator(level, first.goal).evaluate(fast).feasible
    assert len(fast) < len(slow)
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_kw:
                        (((fast, 10),), 1, 1))
    completed = []
    result = optimise_user_splices(level, slow, [first, last],
                                   RandomSpliceConfig(rounds=1, iterations=2),
                                   start_at='end', best_callback=completed.append)
    assert result.frames == fast
    assert completed == [fast]


def test_completed_improvement_at_nonfinal_stage_is_published(monkeypatch):
    level, _source, _ = _baseline()
    slow, fast = _completed(level, 3), _completed(level, 0)
    first = UserSpliceStage('first', EndpointGoal(10, 'min-x'), 0, 10)
    last = UserSpliceStage('end', EndpointGoal(10, 'min-x'), 0, 10)
    # Fast finish is worse at min-x; the helper objective must not mask it.
    assert EndpointEvaluator(level, first.goal).evaluate(fast).objective_key > (
        EndpointEvaluator(level, first.goal).evaluate(slow).objective_key)
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_kw:
                        (((fast, 10),), 1, 1))
    completed = []
    result = optimise_user_splices(level, slow, [first, last],
                                   RandomSpliceConfig(rounds=1, iterations=2),
                                   stop_at='first', best_callback=completed.append)
    assert result.frames == fast
    assert completed == [fast]


def test_manually_edited_completed_input_replaces_slower_saved_final(monkeypatch):
    level, _source, _ = _baseline()
    slow, edited = _completed(level, 3), _completed(level, 0)
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_kw: ((), 0, 1))
    stage = UserSpliceStage('end', EndpointGoal(10, 'min-x'), 0, 10)
    saved, logs = [], []
    result = optimise_user_splices(
        level, edited, [stage], RandomSpliceConfig(rounds=1, iterations=2),
        saved_final_frames=slow, best_callback=saved.append, progress=logs.append)
    assert result.frames == edited
    assert result.improvements == 1
    assert saved == [edited]
    assert any('current input' in line and 'saved manually edited' in line
               for line in logs)
    readonly = []
    optimise_user_splices(level, edited, [stage], RandomSpliceConfig(rounds=1, iterations=2),
                          saved_final_frames=slow, summary_only=True,
                          best_callback=readonly.append)
    assert readonly == []


def test_cli_rerun_replaces_saved_final_with_better_manual_input(tmp_path, monkeypatch):
    level, _source, _saved, output, _packed, argv = _setup(tmp_path)
    slow, fast = _completed(level, 3), _completed(level, 0)
    input_path = tmp_path / 'source.txt'
    _write_combined(input_path, level, fast)
    _write_combined(output, level, slow)
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_kw: ((), 0, 1))
    monkeypatch.setattr(sys, 'argv', [*argv, '--auto-runs', '1'])
    main()
    from nv14_replay import parse_combined_level_replay, decode_complex_replay
    restored = decode_complex_replay(
        parse_combined_level_replay(output.read_text()).replay_string).frames
    assert tuple(editable_frames(restored)) == tuple(editable_frames(fast))


def test_cli_completed_outer_pass_does_not_suppress_new_manual_rerun(tmp_path, monkeypatch):
    _level, source, _saved, _output, _packed, argv = _setup(tmp_path)
    resume_starts = []

    def fake_splicer(_level, source_frames, stages, config, *,
                     save_outer_round, resume_outer_round, **_kwargs):
        resume_starts.append(resume_outer_round)
        # Simulate a run that reaches the last pass but is interrupted before
        # clearing the completed-pass sidecar.
        save_outer_round(config.rounds)
        return UserSpliceResult(tuple(source_frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', fake_splicer)
    monkeypatch.setattr(sys, 'argv', [*argv, '--auto-runs', '1'])
    main()
    main()
    assert resume_starts == [0, 0]


def test_completed_run_can_be_saved_even_when_current_helper_fails(monkeypatch):
    level, _source, _ = _baseline()
    slow, fast = _completed(level, 3), _completed(level, 0)
    slow_x = evaluate_replay_with_sentinel(level, slow).point(10).x
    goal = EndpointGoal(10, 'min-x', x_window=AxisWindow(slow_x - 0.5, slow_x + 0.5))
    assert EndpointEvaluator(level, goal).evaluate(slow).feasible
    assert not EndpointEvaluator(level, goal).evaluate(fast).feasible
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_kw: (((fast, 10),), 1, 1))
    saved = []
    result = optimise_user_splices(level, slow, [UserSpliceStage('end', goal, 0, 10)],
                                   RandomSpliceConfig(rounds=1, iterations=2),
                                   best_callback=saved.append)
    assert result.frames == fast
    assert saved == [fast]


def test_merge_can_publish_faster_completion_missing_destination_helper(monkeypatch):
    level, _source, _ = _baseline()
    slow, fast = _completed(level, 3), _completed(level, 0)
    slow_x = evaluate_replay_with_sentinel(level, slow).point(10).x
    stages = [UserSpliceStage('first', EndpointGoal(10, 'max-x'), 0, 10),
              UserSpliceStage('end', EndpointGoal(
                  10, 'min-x', x_window=AxisWindow(slow_x - .5, slow_x + .5)), 0, 10)]
    assert EndpointEvaluator(level, stages[-1].goal).evaluate(slow).feasible
    assert not EndpointEvaluator(level, stages[-1].goal).evaluate(fast).feasible
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_kw: (fast,))
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_kw:
                        (_ for _ in ()).throw(AssertionError('merge-only searched')))
    saved, stage_saved, logs = [], [], []
    result = optimise_user_splices(
        level, slow, stages, RandomSpliceConfig(rounds=1, iterations=2),
        merge_stage_bests=True, merge_only=True, merge_verbose=True,
        saved_stage_candidates={'first': [fast], 'end': [slow]},
        best_callback=saved.append,
        stage_best_callback=lambda *args: stage_saved.append(args),
        progress=logs.append)
    assert result.frames == fast
    assert saved == [fast]
    assert not stage_saved  # Helper failed; never mislabel as a stage checkpoint.
    assert any('completed join accepted despite missing destination helper' in line
               for line in logs)

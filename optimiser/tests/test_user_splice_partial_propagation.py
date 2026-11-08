"""Patch 90: stage gains survive a later death, without inventing a completion.

These use the native engine; the original Flash SWF remains authoritative.
"""
from __future__ import annotations

import pytest

import nv14_user_splice as us
from nv14_auto import evaluate_replay_with_sentinel
from nv14_engine import InputFrame, parse_level_string
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_splice_merge import verified_suffix_grafts
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_auto import _running_exit_level
from tests.test_user_splice_manual_input_merge import _finished_slow_run
from tests.test_random_splice import _baseline


def _guarded(x: int):
    """A floor guard crosses the running corridor at a controlled time."""
    return parse_level_string(
        _running_exit_level().source_level_string + f'!4^{x},134,1',
        simulate_enemies=True,
    )


def test_dead_later_saved_route_promotes_later_stage_without_any_graft(monkeypatch):
    level = _guarded(240)
    fast = (InputFrame(right=True),) * 29
    slow = (InputFrame(),) * 5 + (InputFrame(right=True),) * 50
    physical = evaluate_replay_with_sentinel(level, fast)
    assert physical.dead_tick == 24 and physical.finish_tick is None
    goals = (EndpointGoal(10, 'max-x'), EndpointGoal(20, 'max-x'))
    assert all(EndpointEvaluator(level, goal).evaluate(fast).feasible for goal in goals)
    later_eval = EndpointEvaluator(level, goals[1])
    assert later_eval.evaluate(fast).objective_key < later_eval.evaluate(slow).objective_key
    stages = [UserSpliceStage('early', goals[0], 0, 10),
              UserSpliceStage('later', goals[1], 10, 20)]
    saved, completed, logs = [], [], []
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_k: pytest.fail('ran search'))
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_k: ())
    result = optimise_user_splices(
        level, slow, stages, RandomSpliceConfig(iterations=2),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_stage_candidates={'early': [fast], 'later': [slow]},
        stage_best_callback=lambda name, replay: saved.append((name, replay)),
        best_callback=completed.append, progress=logs.append,
    )
    assert result.improvements == 0 and result.attempts == 0
    assert completed == []
    assert [name for name, _ in saved] == ['later']
    assert later_eval.evaluate(saved[0][1]).feasible
    assert any('existing replay propagated to later checkpoint' in msg and
               'dies later at frame 24' in msg for msg in logs)


def test_cannot_promote_goal_reached_only_in_enemy_free_world(monkeypatch):
    level = _guarded(130)
    fast = (InputFrame(right=True),) * 29
    slow = (InputFrame(),) * 5 + (InputFrame(right=True),) * 50
    assert evaluate_replay_with_sentinel(level, fast).dead_tick == 10
    goals = (EndpointGoal(5, 'max-x'), EndpointGoal(20, 'max-x'))
    enemy_free = parse_level_string(level.source_level_string, simulate_enemies=False)
    assert EndpointEvaluator(enemy_free, goals[1]).evaluate(fast).feasible
    assert (EndpointEvaluator(enemy_free, goals[1]).evaluate(fast).objective_key <
            EndpointEvaluator(enemy_free, goals[1]).evaluate(slow).objective_key)
    stages = [UserSpliceStage('early', goals[0], 0, 5, simulate_enemies=False),
              UserSpliceStage('later', goals[1], 5, 20, simulate_enemies=False)]
    saved = []
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_k: ())
    optimise_user_splices(
        level, slow, stages, RandomSpliceConfig(iterations=2),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_stage_candidates={'early': [fast], 'later': [slow]},
        stage_best_callback=lambda name, replay: saved.append(name),
    )
    assert saved == []


def test_stage_grafting_accepts_live_section_from_reference_that_dies_later():
    level = _guarded(240)
    replay = (InputFrame(right=True),) * 29
    assert evaluate_replay_with_sentinel(level, replay).dead_tick == 24
    grafts = verified_suffix_grafts(level, replay, replay,
                                    seam_frame=19, lookback=3,
                                    completion_required=False)
    assert grafts
    for graft in grafts:
        assert evaluate_replay_with_sentinel(level, graft).dead_tick is None
        assert len(graft) <= 24
        assert EndpointEvaluator(level, EndpointGoal(20, 'max-x')).evaluate(graft).feasible
    assert verified_suffix_grafts(level, replay, replay, seam_frame=19,
                                  lookback=3, completion_required=True) == ()


def test_direct_grafting_checks_actual_arrival_and_earlier_seam_windows(monkeypatch):
    level, fast, _ = _baseline()
    slow = _finished_slow_run(level)
    first = EndpointGoal(28, 'earliest-arrival', target_region=(90, 110, 120, 160))
    arrival = EndpointEvaluator(level, first).evaluate(fast)
    assert arrival.feasible and arrival.frame == 21
    stages = [UserSpliceStage('early', first, 0, 28),
              UserSpliceStage('later', EndpointGoal(30, 'min-x'), 28, 30)]
    recorded = []

    def record(_level, prefix, suffix, **kwargs):
        if (tuple(prefix[:len(fast)]) == fast and
                tuple(suffix[:len(slow)]) == slow):
            recorded.append(kwargs['seam_frame'])
        return ()

    monkeypatch.setattr(us, 'verified_suffix_grafts', record)
    optimise_user_splices(
        level, slow, stages, RandomSpliceConfig(iterations=2, lookback=3),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_stage_candidates={'early': [fast], 'later': [slow]},
        saved_final_frames=slow,
    )
    assert {28, 21, 18, 15}.issubset(recorded)

"""Patch 49: merge after searching, without expanding normal seed history."""
from __future__ import annotations

import nv14_user_splice as us
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def _stages(names):
    return [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
            for name in names]


def test_end_pass_propagates_new_stage_checkpoint_from_search(monkeypatch):
    level, source, _ = _baseline()
    prefix = (InputFrame(left=True),) + source[1:]
    stages = _stages(('first', 'last'))
    assert EndpointEvaluator(level, stages[0].goal).evaluate(prefix).objective_key < (
        EndpointEvaluator(level, stages[0].goal).evaluate(source).objective_key)
    calls, written, messages = [], [], []

    def search(_level, _branch, stage, _config, _rng, **_kwargs):
        calls.append(stage.name)
        return (((prefix, 10),) if stage.name == 'first' else ()), 1, 1

    monkeypatch.setattr(us, '_search_stage', search)
    result = optimise_user_splices(
        level, source, stages,
        RandomSpliceConfig(rounds=1, iterations=4, stage_lookback=1),
        saved_stage_candidates={'last': [source]},
        merge_stage_bests=True, completion_policy='checkpoint', stop_at='first',
        progress=messages.append,
        stage_best_callback=lambda name, frames: written.append((name, frames)),
    )
    assert 'first' in calls
    assert any(name == 'last' for name, _ in written)
    assert any('[auto:user-splice:merge:startup] done:' in m and '0 attempted' in m
               for m in messages)
    assert any('[auto:user-splice:merge:final] done:' in m and '1 verified join' in m
               for m in messages)
    assert result.attempts > 0


def test_merge_pairs_are_not_limited_by_normal_seed_lookback(monkeypatch):
    level, source, _ = _baseline()
    prefix = (InputFrame(left=True),) + source[1:]
    stages = _stages(('first', 'second', 'third'))
    visited, messages = [], []
    def graft(_level, earlier, later, *, seam_frame, **_kwargs):
        visited.append((earlier[0].left, later[0].left, seam_frame))
        return ()
    monkeypatch.setattr(us, 'verified_suffix_grafts', graft)
    optimise_user_splices(
        level, source, stages,
        RandomSpliceConfig(rounds=0, iterations=4, stage_lookback=1),
        saved_stage_candidates={'first': [prefix], 'second': [source],
                                'third': [source]},
        merge_stage_bests=True, merge_only=True, progress=messages.append)
    assert sum(first and not second for first, second, _ in visited) == 2
    assert any('3 pair(s) considered' in m for m in messages)
    assert any('normal search lookback remains 1' in m for m in messages)


def test_merging_disabled_does_not_run_extra_pass(monkeypatch):
    level, source, _ = _baseline()
    stages = _stages(('first', 'last'))
    def fail(*_a, **_kw):
        raise AssertionError('unexpected merge')
    monkeypatch.setattr(us, 'verified_suffix_grafts', fail)
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_kw: ((), 0, 1))
    optimise_user_splices(level, source, stages,
                          RandomSpliceConfig(rounds=1, iterations=4),
                          saved_stage_candidates={
                              'first': [(InputFrame(left=True),) + source[1:]],
                              'last': [source]}, merge_stage_bests=False)

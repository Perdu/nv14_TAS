"""The caller's manually edited replay must never disappear behind frontiers."""
from __future__ import annotations

import nv14_user_splice as us
from nv14_auto import evaluate_replay_with_sentinel
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def _different(source, count):
    return tuple(InputFrame(left=True) for _ in range(count)) + source[count:]


def _capture(monkeypatch):
    calls = []

    def search(_level, branch, stage, *_args, **_kwargs):
        calls.append((stage.name, tuple(branch)))
        return (), 0, 1

    monkeypatch.setattr(us, '_search_stage', search)
    return calls


def test_input_is_seed_one_then_n_minus_one_then_n_minus_two(monkeypatch):
    level, source, _ = _baseline()
    n1, n2 = _different(source, 1), _different(source, 2)
    stages = [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
              for name in ('a', 'b', '522')]
    calls = _capture(monkeypatch)
    messages = []

    optimise_user_splices(
        level, source, stages,
        RandomSpliceConfig(rounds=1, frontier=2, stage_lookback=2,
                           iterations=2, workers=1),
        completion_policy='checkpoint', start_at='522',
        saved_stage_frontiers={'a': [n2], 'b': [n1]},
        progress=messages.append,
    )

    assert calls == [('522', source), ('522', n1), ('522', n2)]
    assert any("'522' seed 1/3 [current input run]" in m for m in messages)
    assert any("'522' seed 2/3 [start from splice b (n-1, source rank 1)]" in m
               for m in messages)
    assert any("'522' seed 3/3 [start from splice a (n-2, source rank 1)]" in m
               for m in messages)
    assert any("3 seed(s): current input, then n-1/n-2 frontiers" in m
               for m in messages)


def test_first_rank_from_each_frontier_precedes_second_rank(monkeypatch):
    level, source, _ = _baseline()
    n1_best, n1_second, n2_best = (_different(source, k) for k in (3, 1, 2))
    stages = [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
              for name in ('a', 'b', '522')]
    calls = _capture(monkeypatch)
    messages = []
    optimise_user_splices(
        level, source, stages,
        RandomSpliceConfig(rounds=1, frontier=3, stage_lookback=2,
                           iterations=2, workers=1),
        completion_policy='checkpoint', start_at='522',
        saved_stage_frontiers={'a': [n2_best], 'b': [n1_second, n1_best]},
        progress=messages.append,
    )
    assert calls == [('522', source), ('522', n1_best),
                     ('522', n2_best), ('522', n1_second)]
    assert any("'522' seed 3/4 [start from splice a (n-2, source rank 1)]" in m
               for m in messages)


def test_manual_input_seed_can_find_and_save_stage_gain(monkeypatch):
    level, source, _ = _baseline()
    n1, n2 = _different(source, 1), _different(source, 2)
    gain = _different(source, 3)
    stages = [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
              for name in ('a', 'b', '522')]
    calls, saved = [], []

    def search(_level, branch, stage, *_args, **_kwargs):
        calls.append(tuple(branch))
        if branch == source:
            return ((gain, 10),), 1, 1
        return (), 0, 1

    monkeypatch.setattr(us, '_search_stage', search)
    optimise_user_splices(
        level, source, stages,
        RandomSpliceConfig(rounds=1, frontier=2, stage_lookback=2,
                           iterations=2, workers=1),
        completion_policy='checkpoint', start_at='522',
        saved_stage_frontiers={'a': [n2], 'b': [n1]},
        stage_best_callback=lambda name, frames: saved.append((name, frames)),
    )
    assert calls[0] == source
    assert ('522', gain) in saved  # The gain is found only from the manual input.


def test_saved_completed_best_is_alternative_not_replacement(monkeypatch):
    level, _source, _ = _baseline()

    def completed(initial_left):
        replay = (InputFrame(left=True),) * initial_left + (InputFrame(right=True),) * 80
        finish = evaluate_replay_with_sentinel(level, replay).finish_tick
        assert finish is not None
        return replay[:finish]

    input_run, saved_best = completed(2), completed(0)
    calls = _capture(monkeypatch)
    messages = []
    optimise_user_splices(
        level, input_run, [UserSpliceStage('end', EndpointGoal(10, 'max-x'), 0, 10)],
        RandomSpliceConfig(rounds=1, iterations=2),
        saved_final_frames=saved_best, completion_policy='complete',
        progress=messages.append,
    )
    assert calls[0] == ('end', input_run)
    assert calls[1][0] == 'end'
    assert calls[1][1][:len(saved_best)] == saved_best
    assert all(frame == InputFrame() for frame in calls[1][1][len(saved_best):])
    assert any('seed 1/2 [current input run]' in m for m in messages)


def test_input_not_searched_twice_when_already_in_frontier(monkeypatch):
    level, source, _ = _baseline()
    alternative = _different(source, 1)
    calls = _capture(monkeypatch)
    stages = [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
              for name in ('old', '522')]
    optimise_user_splices(
        level, source, stages,
        RandomSpliceConfig(rounds=1, frontier=3, iterations=2),
        completion_policy='checkpoint', start_at='522',
        saved_stage_frontiers={'old': [alternative, source]},
    )
    searched = [branch for name, branch in calls if name == '522']
    assert searched[0] == source
    assert searched.count(source) == 1
    assert alternative in searched


def test_each_best_option_still_searches_current_input_first(monkeypatch):
    level, source, _ = _baseline()
    saved = _different(source, 2)
    calls = _capture(monkeypatch)
    optimise_user_splices(
        level, source, [UserSpliceStage('522', EndpointGoal(10, 'min-x'), 0, 10)],
        RandomSpliceConfig(rounds=1, frontier=1, iterations=2),
        completion_policy='checkpoint', start_from_stage_bests=True,
        saved_stage_candidates={'522': [saved]},
    )
    assert calls == [('522', source), ('522', saved)]


def test_explicit_from_best_retains_selected_seed_priority(monkeypatch):
    level, source, _ = _baseline()
    saved = _different(source, 1)
    calls = _capture(monkeypatch)
    optimise_user_splices(
        level, source,
        [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
         for name in ('old', '522')],
        RandomSpliceConfig(rounds=1, frontier=1, iterations=2),
        completion_policy='checkpoint', from_best='old',
        saved_stage_candidates={'old': [saved]},
    )
    assert calls == [('522', saved)]

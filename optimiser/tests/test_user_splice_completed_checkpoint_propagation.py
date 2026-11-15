"""Completed replays must update later named checkpoints before their searches.

The final completion score and individual stage objective remain independent;
only a genuinely reached, strictly better stage goal may be propagated.
"""
from __future__ import annotations

import nv14_user_splice as us
from nv14_auto import evaluate_replay_with_sentinel
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_engine import InputFrame
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def _completions():
    level, fast, _ = _baseline()
    delayed = (InputFrame(),) * 5 + (InputFrame(right=True),) * 80
    slow = delayed[:evaluate_replay_with_sentinel(level, delayed).finish_tick]
    assert len(fast) == 29 and len(slow) == 34
    return level, fast, slow


def _stages():
    return [
        UserSpliceStage('394', EndpointGoal(20, 'max-x'), 0, 20),
        UserSpliceStage('end', EndpointGoal(
            40, 'earliest-arrival', target_region=(100, 1000, 120, 180)), 20, 40),
    ]


def test_search_completion_immediately_updates_later_end_checkpoint(monkeypatch):
    level, fast, slow = _completions()
    stages = _stages()
    assert EndpointEvaluator(level, stages[-1].goal).evaluate(
        fast + (InputFrame(),) * 12).frame == 24
    saves, logs, seen = [], [], []

    def search(_level, _branch, stage, *_args, **_kwargs):
        seen.append(stage.name)
        replay = fast if stage.name == '394' else slow
        return (((replay + (InputFrame(),) * max(0, 41 - len(replay)), stage.end),), 1, 1)

    monkeypatch.setattr(us, '_search_stage', search)
    result = optimise_user_splices(
        level, slow, stages, RandomSpliceConfig(rounds=1, iterations=2, workers=1),
        completion_policy='complete', stage_best_callback=lambda *args: saves.append(args),
        progress=logs.append,
    )
    assert seen[0] == '394' and all(stage == 'end' for stage in seen[1:])
    assert len(result.frames) == 29
    assert [replay for stage, replay in saves if stage == 'end'][-1] == fast
    assert any("verified completed replay -> 'end'" in msg for msg in logs)
    assert not any("'end': new stage best" in msg for msg in logs)
    assert any("round 1 'end'" in msg and 'stage best frame 24' in msg
               for msg in logs)


def test_saved_completed_run_updates_stale_end_before_search(monkeypatch):
    level, fast, slow = _completions()
    stages = _stages()
    saves, logs = [], []
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_kw: (((slow + (InputFrame(),) * 7, 40),), 1, 1))
    optimise_user_splices(
        level, slow, stages, RandomSpliceConfig(rounds=1, iterations=2, workers=1),
        saved_final_frames=fast, saved_stage_candidates={'end': [slow]},
        stage_best_callback=lambda *args: saves.append(args),
        completion_policy='complete', progress=logs.append,
    )
    assert [replay for stage, replay in saves if stage == 'end'] == [fast]
    assert any("verified completed replay -> 'end'" in msg for msg in logs)
    assert not any("'end': new stage best" in msg for msg in logs)


def test_merge_stage_gain_updates_in_memory_rank_before_search(monkeypatch):
    level, _, _ = _completions()
    source = (InputFrame(),) * 50
    middle = (InputFrame(right=True),) * 4 + source[4:]
    fast = (InputFrame(right=True),) * 50
    stages = [UserSpliceStage('early', EndpointGoal(10, 'max-x'), 0, 10),
              UserSpliceStage('later', EndpointGoal(10, 'max-x'), 0, 10)]
    evaluator = EndpointEvaluator(level, stages[-1].goal)
    assert (evaluator.evaluate(fast).objective_key <
            evaluator.evaluate(middle).objective_key <
            evaluator.evaluate(source).objective_key)
    saves, messages = [], []
    monkeypatch.setattr(us, '_search_stage', lambda _lv, _branch, stage, *_a, **_k:
                        (((middle, 10),), 1, 1) if stage.name == 'later' else ((), 0, 1))
    # The direct existing-replay promotion runs even with grafting disabled.
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_k: ())
    optimise_user_splices(
        level, source, stages, RandomSpliceConfig(rounds=1, iterations=2, workers=1),
        completion_policy='checkpoint', merge_stage_bests=True,
        saved_stage_candidates={'early': [fast], 'later': [source]},
        stage_best_callback=lambda *args: saves.append(args), progress=messages.append,
    )
    assert [replay for name, replay in saves if name == 'later'] == [fast[:29]]
    assert not any("'later': new stage best" in msg for msg in messages)


def test_completed_run_cannot_promote_post_finish_fixed_frame(monkeypatch):
    level, fast, slow = _completions()
    stage = UserSpliceStage('after', EndpointGoal(40, 'max-x'), 0, 40)
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_kw: ((), 0, 1))
    messages = []
    optimise_user_splices(
        level, slow, [stage], RandomSpliceConfig(rounds=1, iterations=2, workers=1),
        completion_policy='complete', saved_final_frames=fast, progress=messages.append,
    )
    assert not any('verified completed replay ->' in msg for msg in messages)

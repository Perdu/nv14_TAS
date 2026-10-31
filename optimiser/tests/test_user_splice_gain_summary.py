"""Stage propagation summaries compare checkpoint scores with the verified run."""
from __future__ import annotations

from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_saved_checkpoint_is_yellow_until_full_run_catches_up(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    alternative = (InputFrame(left=True),) + source[1:]
    stage = UserSpliceStage('556', EndpointGoal(10, 'min-x'), 0, 10)
    evaluator = EndpointEvaluator(level, stage.goal)
    assert evaluator.evaluate(alternative).objective_key < evaluator.evaluate(source).objective_key
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw: ((), 1, 1))
    messages = []
    optimise_user_splices(level, source, [stage],
                          RandomSpliceConfig(rounds=2, iterations=2, workers=1),
                          completion_policy='checkpoint',
                          saved_stage_candidates={'556': [alternative]},
                          progress=messages.append)
    assert any('[auto:user-splice:summary:pending]' in line and '556' in line
               for line in messages)
    assert sum('checkpoint propagation' in line for line in messages) == 4, (
        'startup + two outer rounds + final')
    assert not any('[auto:user-splice:summary:propagated]' in line for line in messages)


def test_checkpoint_turns_green_when_full_run_includes_its_inputs(monkeypatch):
    import nv14_user_splice as us
    level, baseline, _ = _baseline()
    source = (InputFrame(),) + baseline[1:]  # incomplete, checkpoint policy
    alternative = (InputFrame(left=True),) + baseline[1:]
    stage = UserSpliceStage('556', EndpointGoal(10, 'min-x'), 0, 10)
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw:
                        (((alternative, 10),), 1, 1))
    messages = []
    optimise_user_splices(level, source, [stage],
                          RandomSpliceConfig(rounds=1, iterations=2, workers=1),
                          completion_policy='checkpoint',
                          saved_stage_candidates={'556': [alternative]},
                          progress=messages.append)
    assert any('[auto:user-splice:summary:pending]' in m for m in messages)
    assert any('[auto:user-splice:summary:propagated]' in m
               and 'same input prefix' in m for m in messages)


def test_empty_checkpoint_remains_neutral(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    stage = UserSpliceStage('556', EndpointGoal(10, 'min-x'), 0, 10)
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw: ((), 0, 1))
    messages = []
    optimise_user_splices(level, source, [stage],
                          RandomSpliceConfig(rounds=1, iterations=2, workers=1),
                          completion_policy='checkpoint', progress=messages.append)
    assert sum('[auto:user-splice:summary:empty]' in m for m in messages) == 3

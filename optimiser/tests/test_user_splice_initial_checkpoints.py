"""Initial splice movies are durable, without overwriting better saved movies."""
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_engine import InputFrame
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_startup_saves_initial_feasible_stage(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    stage = UserSpliceStage('230', EndpointGoal(10, 'min-x'), 0, 10)
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs: ((), 0, 1))
    saved, messages = [], []
    optimise_user_splices(level, source, [stage],
                          RandomSpliceConfig(rounds=1, workers=1, iterations=2),
                          completion_policy='checkpoint',
                          stage_best_callback=lambda name, frames: saved.append((name, frames)),
                          progress=messages.append)
    assert saved == [('230', source)]
    assert any('saved starting stage result' in m for m in messages)


def test_startup_does_not_replace_better_existing_result(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    variations = [source, (InputFrame(left=True),) + source[1:],
                  (InputFrame(left=True), InputFrame(left=True)) + source[2:]]
    stage = UserSpliceStage('230', EndpointGoal(10, 'min-x'), 0, 10)
    evaluator = EndpointEvaluator(level, stage.goal)
    best, middle, worst = sorted(variations, key=lambda s: evaluator.evaluate(s).objective_key)
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs: ((), 0, 1))
    saved = []
    optimise_user_splices(level, worst, [stage],
                          RandomSpliceConfig(rounds=1, workers=1, iterations=2),
                          completion_policy='checkpoint',
                          saved_stage_candidates={'230': [best]},
                          stage_best_callback=lambda name, frames: saved.append((name, frames)))
    assert saved == []


def test_startup_updates_worse_saved_result(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    variations = [source, (InputFrame(left=True),) + source[1:],
                  (InputFrame(left=True), InputFrame(left=True)) + source[2:]]
    stage = UserSpliceStage('230', EndpointGoal(10, 'min-x'), 0, 10)
    evaluator = EndpointEvaluator(level, stage.goal)
    best, middle, worst = sorted(variations, key=lambda s: evaluator.evaluate(s).objective_key)
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs: ((), 0, 1))
    saved = []
    optimise_user_splices(level, best, [stage],
                          RandomSpliceConfig(rounds=1, workers=1, iterations=2),
                          completion_policy='checkpoint',
                          saved_stage_candidates={'230': [middle]},
                          stage_best_callback=lambda name, frames: saved.append((name, frames)))
    assert saved == [('230', best)]

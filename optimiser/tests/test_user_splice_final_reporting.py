from nv14_auto import evaluate_replay_with_sentinel
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_final_gain_report_does_not_compare_against_temporary_stage_best(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    def completed(delay):
        frames = (InputFrame(left=True),)*delay + (InputFrame(right=True),)*80
        finish = evaluate_replay_with_sentinel(level, frames).finish_tick
        return frames[:finish]
    old = completed(3)
    improved = completed(0)
    goal = EndpointGoal(10, 'max-x')
    assert EndpointEvaluator(level, goal).evaluate(improved).objective_key < EndpointEvaluator(level, goal).evaluate(old).objective_key
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs: (((improved, 10),), 1, 1))
    messages = []
    optimise_user_splices(level, old, [UserSpliceStage('end', goal, 0, 10)],
                          RandomSpliceConfig(rounds=1, iterations=2),
                          completion_policy='complete', progress=messages.append)
    gains = [msg for msg in messages if 'improved verified final replay' in msg]
    assert gains and 'verified completed frames' in gains[0]
    assert 'final-goal comparison' in gains[0]

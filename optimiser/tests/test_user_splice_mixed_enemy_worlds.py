"""Stages may select separate enemy worlds; final output is verified strictly."""
from dataclasses import replace

import nv14_cli as cli
import nv14_user_splice as us
from nv14_auto import evaluate_replay_with_sentinel
from nv14_engine import InputFrame, parse_level_string
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_auto import _running_exit_level


def _guarded_level():
    base = _running_exit_level()
    return base.source_level_string + '!4^90,134,1'


def test_stage_worlds_are_different_in_native_simulator():
    raw = _guarded_level()
    disabled = parse_level_string(raw, simulate_enemies=False)
    enabled = parse_level_string(raw, simulate_enemies=True)
    source = (InputFrame(right=True),) * 29
    assert evaluate_replay_with_sentinel(disabled, source).finish_tick == 29
    assert evaluate_replay_with_sentinel(enabled, source).dead_tick == 3
    assert any(type(obj).__name__ == 'FloorGuard' for obj in enabled.objects)
    assert not any(type(obj).__name__ == 'FloorGuard' for obj in disabled.objects)


def test_backend_search_receives_correct_level_for_each_stage(monkeypatch):
    raw = _guarded_level()
    strict = parse_level_string(raw, simulate_enemies=True)
    source = (InputFrame(right=True),) * 29
    stages = [UserSpliceStage('before', EndpointGoal(2, 'min-x'), 0, 2,
                              simulate_enemies=False),
              UserSpliceStage('after', EndpointGoal(10, 'min-x'), 0, 10,
                              simulate_enemies=True)]
    seen = []

    def search(stage_level, branch, stage, config, rng, **kwargs):
        seen.append((stage.name, stage_level.simulate_enemies,
                     len([obj for obj in stage_level.objects
                          if type(obj).__name__ == 'FloorGuard'])))
        return (), 0, 1

    monkeypatch.setattr(us, '_search_stage', search)
    optimise_user_splices(strict, source, stages,
                          RandomSpliceConfig(rounds=1, iterations=2),
                          completion_policy='checkpoint')
    assert seen[0] == ('before', False, 0)
    assert seen[1] == ('after', True, 1)


def test_saved_checkpoint_feasible_only_in_its_own_world():
    raw = _guarded_level()
    strict = parse_level_string(raw, simulate_enemies=True)
    off = parse_level_string(raw, simulate_enemies=False)
    source = (InputFrame(right=True),) * 29
    goal = EndpointGoal(10, 'max-x')
    assert EndpointEvaluator(off, goal).evaluate(source).feasible
    assert not EndpointEvaluator(strict, goal).evaluate(source).feasible


def test_enemy_disabled_final_stage_cannot_publish_dead_best(monkeypatch):
    strict = parse_level_string(_guarded_level(), simulate_enemies=True)
    source = (InputFrame(right=True),) * 29
    stage = UserSpliceStage('end', EndpointGoal(10, 'max-x'), 0, 10,
                             simulate_enemies=False)
    published = []
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs:
                        (((source, 10),), 0, 1))
    result = optimise_user_splices(strict, source, [stage],
                                   RandomSpliceConfig(rounds=1, iterations=2),
                                   completion_policy='checkpoint',
                                   best_callback=published.append)
    assert result.improvements == 0
    assert published == []


def test_earlier_enemy_enabled_helper_does_not_block_later_enemy_free_checkpoint(monkeypatch):
    strict = parse_level_string(_guarded_level(), simulate_enemies=True)
    source = (InputFrame(right=True),) * 29
    stages = [UserSpliceStage('guard', EndpointGoal(10, 'max-x'), 0, 10,
                              simulate_enemies=True),
              UserSpliceStage('safe', EndpointGoal(10, 'max-x'), 0, 10,
                              simulate_enemies=False)]
    checkpointed = []
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs:
                        (((source, 10),), 0, 1))
    optimise_user_splices(strict, source, stages,
                          RandomSpliceConfig(rounds=1, iterations=2),
                          completion_policy='checkpoint',
                          stage_best_callback=lambda stage, frames:
                              checkpointed.append(stage))
    # An earlier helper in another physics world must not veto the later
    # stage. It remains only a stage checkpoint; no dead replay is published
    # as a verified completed run in the real enemy-enabled physics world.
    assert checkpointed == ['safe']

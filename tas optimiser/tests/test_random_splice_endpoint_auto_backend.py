"""Switch-safe random splicing can opt into Auto's endpoint Hybrid kernel."""
from dataclasses import replace

import pytest

from nv14_auto import evaluate_replay_with_sentinel
from nv14_cli import parse_arguments
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_engine import InputFrame
from nv14_random_splice import RandomSpliceConfig, _local_search, optimise_random_splices
from tests.test_random_splice import _baseline


def test_default_still_uses_local_population():
    assert RandomSpliceConfig().search_backend == 'local'


def test_backend_validation():
    with pytest.raises(ValueError, match='search_backend'):
        RandomSpliceConfig(search_backend='unknown')


def test_toml_and_cli_load_endpoint_backend(tmp_path):
    path = tmp_path / 'random.toml'
    path.write_text('''[auto]
random-splice = true
objective = "speedrun"
splice-search = "endpoint-auto"
splice-iterations = 37
splice-rounds = 3
''', encoding='utf-8')
    parsed = parse_arguments(['auto', 'source.txt', '--config', str(path)])
    assert parsed.auto_splice_search == 'endpoint-auto'
    assert parsed.auto_splice_iterations == 37
    assert parsed.auto_splice_rounds == 3
    parsed = parse_arguments(['auto', 'source.txt', '--auto-random-splice',
                              '--auto-splice-search', 'local'])
    assert parsed.auto_splice_search == 'local'
    with pytest.raises(SystemExit, match='require --auto-random-splice'):
        parse_arguments(['auto', 'source.txt', '--auto-splice-search', 'endpoint-auto'])


def test_backend_propagates_budget_rounds_workers_and_bounds(monkeypatch):
    import nv14_auto_endpoint as ae
    level, frames, reference = _baseline()
    fake_best = None
    recorded = []

    def campaign(level, source, goal, config, **kwargs):
        recorded.append((source, goal, config, kwargs))
        return fake_best, fake_best, 17

    monkeypatch.setattr(ae, 'optimise_auto_endpoint_campaign', campaign)
    goal = EndpointGoal(target_frame=18, objective='earliest-arrival',
                        target_region=(0, 200, 0, 200))
    result, used = _local_search(level, frames, goal, start=5,
                                 editable_end=17,
                                 config=RandomSpliceConfig(search_backend='endpoint-auto',
                                                           workers=3, beam=10,
                                                           endpoint_repair_steps=0),
                                 iterations=37, rounds=4, seed=91,
                                 include_partial=True)
    assert result == () and used == 17
    source, passed_goal, passed_config, opts = recorded[0]
    assert source == frames and passed_goal is goal
    assert (passed_config.range_start, passed_config.range_end) == (5, 17)
    assert (passed_config.iterations, passed_config.beam_width, passed_config.seed) == (37, 10, 91)
    assert passed_config.repair_steps == 0
    assert opts['workers'] == 3 and opts['runs'] == 4


def test_backend_never_offers_unverified_or_infeasible_results(monkeypatch):
    import nv14_auto_endpoint as ae
    from nv14_auto_endpoint import AutoEndpointCandidate
    level, frames, _ = _baseline()
    goal = EndpointGoal(target_frame=18, objective='earliest-arrival',
                        target_region=(0, 200, 0, 200))
    endpoint = EndpointEvaluator(level, goal).evaluate(frames)
    assert endpoint.feasible
    candidate = AutoEndpointCandidate(frames, endpoint)
    monkeypatch.setattr(ae, 'optimise_auto_endpoint_campaign',
                        lambda *args, **kwargs: (candidate, candidate, 5))
    selected, count = _local_search(level, frames, goal, start=1,
                                    config=RandomSpliceConfig(search_backend='endpoint-auto'),
                                    iterations=3, rounds=1, seed=1)
    assert selected == ((frames, endpoint.frame),) and count == 5
    monkeypatch.setattr(ae, 'optimise_auto_endpoint_campaign',
                        lambda *args, **kwargs: (candidate, AutoEndpointCandidate(frames, replace(endpoint, feasible=False)), 5))
    selected, count = _local_search(level, frames, goal, start=1,
                                    config=RandomSpliceConfig(search_backend='endpoint-auto'),
                                    iterations=3, rounds=1, seed=1)
    assert selected == () and count == 5


def test_actual_backend_search_for_waypoint_with_exit_switch():
    level, frames, base = _baseline()
    # Simulate a known-feasible starting route (through a real switch and exit).
    # At the waypoint, the Hybrid endpoint scorer enforces reference controls.
    goal = EndpointGoal(target_frame=20, objective='earliest-arrival',
                        target_region=(base.point(20).x-10, base.point(20).x+10,
                                       base.point(20).y-10, base.point(20).y+10))
    result, count = _local_search(level, frames, goal, start=0,
                                  config=RandomSpliceConfig(search_backend='endpoint-auto',
                                                            endpoint_repair_steps=0,
                                                            beam=8, workers=1),
                                  iterations=30, rounds=1, seed=1)
    assert count > 0
    assert all(EndpointEvaluator(level, goal).evaluate(item).feasible
               for item, _ in result)


def test_full_run_auto_backend_only_accepts_verified_switch_safe_completions():
    level, original, baseline = _baseline()
    result = optimise_random_splices(level, original,
        RandomSpliceConfig(search_backend='endpoint-auto', points=2,
                           iterations=12, repair_iterations=6, workers=1,
                           splice_rounds=1, beam=8, endpoint_repair_steps=0, rounds=1))
    checked = evaluate_replay_with_sentinel(level, result.frames)
    assert checked.valid and checked.finish_tick == len(result.frames)
    assert checked.route_control_events == baseline.route_control_events
    assert result.attempts > 0 and result.evaluations > 0


def test_exit_segment_backend_preserves_implicit_neutral_sentinel():
    from nv14_objectives import resolve_interaction_target
    level, original, _ = _baseline()
    slow = (InputFrame(),) * 6 + original
    goal = EndpointGoal(target_frame=len(slow), objective='earliest-interaction',
                        interaction_target=resolve_interaction_target(level, 'exit:0'))
    candidates, used = _local_search(
        level, slow + (InputFrame(),), goal, start=8, editable_end=len(slow)-1,
        config=RandomSpliceConfig(search_backend='endpoint-auto', beam=8,
                                  endpoint_repair_steps=0, workers=1),
        iterations=30, rounds=1, seed=4)
    assert used > 0
    assert all(len(seq) == len(slow)+1 for seq, _ in candidates)
    assert all(seq[-1] == InputFrame() for seq, _ in candidates)
    assert all(EndpointEvaluator(level, goal).evaluate(seq).feasible for seq, _ in candidates)


def test_endpoint_goal_random_splicer_can_use_auto_backend():
    level, source, _ = _baseline()
    point = evaluate_replay_with_sentinel(level, source).point(18)
    goal = EndpointGoal(target_frame=18, objective='earliest-arrival',
                        target_region=(point.x-12, point.x+12, point.y-12, point.y+12))
    result = optimise_random_splices(level, source,
        RandomSpliceConfig(search_backend='endpoint-auto', points=2,
                           iterations=15, workers=1, frontier=2,
                           endpoint_repair_steps=0, rounds=1),
        target_goal=goal, range_start=0, range_end=18,
        completion_policy='checkpoint')
    assert result.attempts >= 1 and result.evaluations > 0
    assert len(result.frames) == len(source)

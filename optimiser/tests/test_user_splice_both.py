"""Combined named-splice search budgets and n-2 branch retention."""
from dataclasses import replace
import random

import pytest

from nv14_cli import parse_arguments
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import (_search_stage, _stage_sources, UserSpliceStage,
                              optimise_user_splices)
from tests.test_random_splice import _baseline


def test_both_cli_and_toml_and_other_modes_rejected(tmp_path):
    cfg = tmp_path / 'config.toml'
    cfg.write_text('[auto]\nsplice-files=["203", "408", "end"]\nsplice-search="both"\n')
    args = parse_arguments(['auto', 'some.ltm', '--config', str(cfg)])
    assert args.auto_splice_mode == 'user'
    assert args.auto_splice_search == 'both'
    assert args.auto_random_splice
    assert parse_arguments(['auto', 'some.ltm', '--auto-splice-files', '203,end',
                            '--auto-splice-search', 'both']).auto_splice_search == 'both'
    with pytest.raises(SystemExit, match='requires user mode'):
        parse_arguments(['auto', 'some.ltm', '--auto-random-splice',
                         '--auto-splice-search', 'both'])
    with pytest.raises(ValueError, match='only supported for user-defined'):
        from nv14_random_splice import _local_search
        level, frames, _ = _baseline()
        _local_search(level, frames, EndpointGoal(10, 'min-x'), start=0,
                      config=RandomSpliceConfig(search_backend='both'),
                      iterations=2, rounds=1, seed=0)


def test_both_halves_proposal_budget_and_merges_candidates(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    alternative = tuple([InputFrame()] + list(source[1:]))
    stage = UserSpliceStage('test', EndpointGoal(12, 'min-x'), 0, 12)
    calls = []

    def fake_search(level, branch, goal, *, config, iterations, **kwargs):
        calls.append((config.search_backend, iterations, kwargs['include_partial'],
                      kwargs['editable_end']))
        if config.search_backend == 'local':
            return ((alternative, 12),), 17
        return ((alternative, 12), (source, 12)), 23

    monkeypatch.setattr(us, '_local_search', fake_search)
    found, evaluations, searches = _search_stage(level, source, stage,
        RandomSpliceConfig(search_backend='both', iterations=101), random.Random(4))
    assert calls == [('local', 51, True, 12), ('endpoint-auto', 50, True, 12)]
    assert evaluations == 40
    assert searches == 2
    assert [candidate for candidate, _ in found] == [alternative, source]
    with pytest.raises(ValueError, match='>= 2'):
        _search_stage(level, source, stage,
            RandomSpliceConfig(search_backend='both', iterations=1), random.Random(4))


def test_stage_sources_reserves_n_minus_two_elite():
    a, b, c, d = ('a',), ('b',), ('c',), ('d',)
    assert _stage_sources([b, c], [a, d], 2) == [b, a]
    assert _stage_sources([b], [a, d], 1) == [b, a]
    assert _stage_sources([b, c], [b, c], 2) == [b, c]
    assert _stage_sources([b, c], [], 1) == [b]


def test_third_stage_receives_n_minus_two_seed_despite_detrimental_middle(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    # Different physical trajectories with reachable stage endpoint states.
    earlier = (InputFrame(left=True),) + source[1:]
    middle = earlier[:5] + (InputFrame(jump=True, right=True),) + earlier[6:]
    stages = [
        UserSpliceStage('203', EndpointGoal(10, 'min-x'), 0, 10),
        UserSpliceStage('408', EndpointGoal(14, 'min-y'), 0, 14),
        UserSpliceStage('end', EndpointGoal(18, 'max-x'), 0, 18),
    ]
    # Precondition: both options remain feasible at every named endpoint;
    # the earlier candidate wins stage 0 and the middle candidate wins stage 1.
    assert EndpointEvaluator(level, stages[0].goal).evaluate(earlier).feasible
    assert EndpointEvaluator(level, stages[1].goal).evaluate(middle).feasible
    record = []

    def fake_stage_search(level, branch, stage, config, rng):
        record.append((stage.name, branch))
        if stage.name == '203' and branch == source:
            return ((earlier, 10),), 1, 1
        if stage.name == '408' and branch == earlier:
            return ((middle, 14),), 1, 1
        return (), 1, 1

    monkeypatch.setattr(us, '_search_stage', fake_stage_search)
    result = optimise_user_splices(level, source, stages,
                                   RandomSpliceConfig(iterations=10, rounds=1,
                                                      frontier=1, workers=1))
    last_seeds = [branch for name, branch in record if name == 'end']
    assert earlier in last_seeds, 'n-2 elite should be tried at stage n'
    assert middle in last_seeds, 'n-1 elite should also be tried at stage n'
    assert result.evaluations >= 4


def test_second_backend_cannot_publish_candidate_breaking_prior_goal(monkeypatch):
    import nv14_user_splice as us
    level, source, baseline = _baseline()
    pos = baseline.point(10)
    stages = [
        UserSpliceStage('switch', EndpointGoal(10, 'earliest-arrival',
                          target_region=(pos.x - 1, pos.x + 1,
                                         pos.y - 1, pos.y + 1)), 0, 10),
        UserSpliceStage('end', EndpointGoal(18, 'max-x'), 0, 18),
    ]
    bad = tuple(InputFrame(left=True) for _ in source)
    saved = []
    monkeypatch.setattr(us, '_local_search', lambda *a, **kw: (((bad, 18),), 1))
    result = optimise_user_splices(level, source, stages,
             RandomSpliceConfig(iterations=2, search_backend='both', rounds=1,
                                workers=1), best_callback=saved.append)
    assert not saved and result.improvements == 0
    assert result.frames == source


def test_stage_elites_persist_into_next_outer_round(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    earlier = (InputFrame(left=True),) + source[1:]
    stages = [
        UserSpliceStage('203', EndpointGoal(10, 'min-x'), 0, 10),
        UserSpliceStage('end', EndpointGoal(18, 'max-x'), 0, 18),
    ]
    calls = []

    def fake_search(level, branch, stage, config, rng):
        calls.append((stage.name, branch))
        # Discover stage 203's winner once, then never return it again.
        if stage.name == '203' and calls.count(('203', source)) == 1:
            return ((earlier, 10),), 1, 1
        return (), 1, 1

    monkeypatch.setattr(us, '_search_stage', fake_search)
    optimise_user_splices(level, source, stages,
                          RandomSpliceConfig(rounds=2, frontier=1, iterations=8))
    assert calls.count(('end', earlier)) == 2


def test_both_real_backends_keep_completed_route_safe():
    from nv14_auto import evaluate_replay_with_sentinel
    level, source, _ = _baseline()
    stages = [UserSpliceStage('203', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('end', EndpointGoal(18, 'max-x'), 5, 18)]
    checkpoints = []
    result = optimise_user_splices(level, source, stages,
        RandomSpliceConfig(search_backend='both', iterations=10,
                           rounds=1, workers=1, beam=8,
                           endpoint_repair_steps=0, frontier=2),
        best_callback=checkpoints.append)
    assert result.evaluations > 0
    assert result.attempts >= 4
    completed = evaluate_replay_with_sentinel(level, result.frames)
    assert completed.valid and completed.finish_tick == len(result.frames)
    if checkpoints:
        assert checkpoints[-1] == result.frames

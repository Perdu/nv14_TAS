"""Endpoint Hybrid survivor export for switch-safe random-splice continuation."""
from dataclasses import replace

import pytest

from nv14_auto_endpoint import (
    AutoEndpointCandidate, AutoEndpointConfig, _EndpointBeam, _endpoint_frontier,
    _key, optimise_auto_endpoint_campaign,
)
from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_engine import InputFrame
from nv14_random_splice import RandomSpliceConfig, _local_search
from tests.test_random_splice import _baseline


def _difficult_goal():
    # Waypoint deliberately unreachable within the deadline. This forces
    # near-miss collection instead of relying on a verified improvement.
    return EndpointGoal(target_frame=18, objective='earliest-arrival',
                        target_region=(900, 910, 900, 910))


def test_beam_exports_diverse_live_feasible_and_infeasible_survivors():
    level, frames, _ = _baseline()
    goal = EndpointGoal(target_frame=15, objective='max-x')
    basic = EndpointEvaluator(level, goal).evaluate(frames)
    beam = _EndpointBeam(AutoEndpointCandidate(frames, basic), 12, _key(frames))
    for index in range(1, 11):
        edited = list(frames)
        edited[index] = InputFrame(left=True)
        value = replace(basic, feasible=index < 5, dead=index == 10,
                        terminal_dead=index == 10,
                        niche_key=('different', index),
                        progress_key=(1, index))
        cand = AutoEndpointCandidate(tuple(edited), value)
        beam.add(cand, _key(cand.frames))
    frontier = _endpoint_frontier(beam, 7)
    assert len(frontier) <= 7
    assert all(candidate.frames != frames for candidate in frontier)
    assert all(not candidate.evaluation.dead for candidate in frontier)
    assert any(candidate.evaluation.feasible for candidate in frontier)
    assert any(not candidate.evaluation.feasible for candidate in frontier)
    assert len({candidate.evaluation.niche_key for candidate in frontier}) >= 5
    assert _endpoint_frontier(beam, 0) == ()


@pytest.mark.parametrize('workers', [1, 2])
def test_campaign_returns_diverse_verified_partial_survivors(workers):
    level, frames, _ = _baseline()
    goal = _difficult_goal()
    exported = []
    base, best, evaluations = optimise_auto_endpoint_campaign(
        level, frames, goal, AutoEndpointConfig(
            iterations=65, beam_width=16, range_start=0, range_end=18,
            repair_steps=0, seed=7),
        workers=workers, runs=2, frontier_callback=exported.extend,
        frontier_limit=7,
    )
    assert evaluations > 0
    assert best is None and not base.evaluation.feasible
    assert 1 <= len(exported) <= 7
    assert any(not c.evaluation.feasible for c in exported)
    assert len({_key(c.frames) for c in exported}) == len(exported)
    for item in exported:
        assert not item.evaluation.dead
        assert len(item.frames) == len(frames)
        assert not verify_endpoint(level, item.frames, goal, expected=item.evaluation).feasible


def test_random_splice_endpoint_auto_offers_partials_only_when_requested():
    level, frames, _ = _baseline()
    goal = _difficult_goal()
    config = RandomSpliceConfig(search_backend='endpoint-auto',
                                workers=1, beam=16, frontier=4,
                                endpoint_repair_steps=0)
    near, n1 = _local_search(level, frames, goal, start=0, config=config,
                             iterations=70, rounds=1, seed=9,
                             include_partial=True)
    feasible, n2 = _local_search(level, frames, goal, start=0, config=config,
                                 iterations=70, rounds=1, seed=9,
                                 include_partial=False)
    assert n1 == n2 and n1 > 0
    assert feasible == ()
    assert 1 <= len(near) <= config.beam
    assert len({frames for frames, _ in near}) == len(near)
    evaluator = EndpointEvaluator(level, goal)
    assert all(not evaluator.evaluate(candidate).feasible for candidate, _ in near)

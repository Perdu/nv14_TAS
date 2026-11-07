"""Patch 76: real population handoff, not only best-seed restarts."""
from dataclasses import dataclass
import random

import pytest

from nv14_random_splice import RandomSpliceConfig
from nv14_splice_backend import SpliceSearchStage, _search_stage


@dataclass(frozen=True)
class FakeEvaluation:
    value: int
    niche_key: int
    feasible: bool = True
    dead: bool = False

    @property
    def objective_key(self):
        return (self.value,)

    @property
    def progress_key(self):
        return (self.value,)


class FakeEvaluator:
    def __init__(self, _level, _goal):
        pass

    def evaluate(self, frames):
        return FakeEvaluation(frames[0], frames[1])


def test_hybrid_carries_nonwinning_survivors_to_local_and_next_auto():
    calls = []

    def search(_level, source, _goal, *, config, initial_population=(),
               population_callback=None, **kwargs):
        calls.append((config.search_backend, source, tuple(initial_population)))
        if len(calls) == 1:
            # Only the elite winner is externally published, but internal
            # beam also contains weaker distinct niches that must be retained.
            population_callback(((7, 11), (8, 22), (9, 33)))
            return (((7, 11), 3),), 3
        if len(calls) == 2:
            assert (8, 22) in initial_population and (9, 33) in initial_population
            # Local identifies no new *winner* but reports its own new niche.
            population_callback(((8, 22), (9, 44)))
            return (), 2
        if len(calls) == 3:
            # The previous Auto's non-winning niche survived Local with no
            # search gain, and Local's unpublished niche also crossed back.
            assert (8, 22) in initial_population
            assert (9, 44) in initial_population
        return (), 1

    _, used, count = _search_stage(
        None, (10, 0), SpliceSearchStage('end', object(), 0, 1),
        RandomSpliceConfig(search_backend='hybrid', beam=8,
                           hybrid_cycles=2, hybrid_local_rounds=3),
        random.Random(12), local_search=search, evaluator_factory=FakeEvaluator)
    assert used == 7 and count == 4
    assert [c[0] for c in calls] == ['endpoint-auto', 'local', 'endpoint-auto', 'local']
    assert calls[0][2] == ((10, 0),)
    assert calls[1][1] == (7, 11)
    assert len(calls[2][2]) >= 3


def test_control_preserves_patch75_restart_only_semantics():
    observed = []

    def search(_level, source, _goal, *, config, **kwargs):
        assert 'initial_population' not in kwargs
        assert 'population_callback' not in kwargs
        observed.append((config.search_backend, source))
        return (((7, 11), 3),), 1

    _search_stage(None, (10, 0), SpliceSearchStage('end', object(), 0, 1),
                  RandomSpliceConfig(search_backend='hybrid-local-control',
                                     hybrid_cycles=2, hybrid_local_rounds=3),
                  random.Random(12), local_search=search,
                  evaluator_factory=FakeEvaluator)
    assert observed == [('local', (10, 0)), ('local', (7, 11)),
                        ('local', (7, 11)), ('local', (7, 11))]


def test_shared_population_is_bounded_and_protects_immutable_frames():
    calls = []
    def search(_level, source, _goal, *, initial_population=(), population_callback,
               **kwargs):
        calls.append(initial_population)
        if len(calls) == 1:
            # Differs outside [1,2]; should never enter the shared pool.
            population_callback(((1, 1, 1, 2), (10, 5, 4, 1),
                                 (10, 4, 2, 1), (10, 3, 3, 1),
                                 (10, 2, 3, 1), (10, 1, 4, 1)))
        return (), 0

    _search_stage(None, (10, 0, 0, 1), SpliceSearchStage('end', object(), 1, 2),
                  RandomSpliceConfig(search_backend='hybrid', beam=3,
                                     hybrid_cycles=2),
                  random.Random(2), local_search=search,
                  evaluator_factory=FakeEvaluator)
    assert len(calls) == 4
    assert (1, 1, 1, 2) not in calls[1]
    assert len(calls[1]) == 3
    assert (10, 0, 0, 1) in calls[1] or (10, 1, 4, 1) in calls[1]


def test_ineligible_donors_cannot_leak_across_switch():
    observed = []
    def search(_level, source, _goal, *, initial_population=(), population_callback,
               **kwargs):
        observed.append(tuple(initial_population))
        population_callback(((1, 0), (8, 4)))
        return (((1, 0), 1),), 2

    _search_stage(None, (10, 0), SpliceSearchStage('end', object(), 0, 1),
                  RandomSpliceConfig(search_backend='hybrid', hybrid_cycles=2),
                  random.Random(3), local_search=search,
                  evaluator_factory=FakeEvaluator,
                  stage_rank=lambda f: None if f[0] == 1 else (f[0],))
    assert len(observed) == 4
    assert all((1, 0) not in pool for pool in observed)
    assert (8, 4) in observed[1]


def test_actual_backends_accept_and_expose_fp64_survivor_population():
    """Native smoke test: the donor is not merely returned to the coordinator."""
    from nv14_engine import (APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS,
                             InputFrame, parse_level_string)
    from nv14_endpoint import EndpointGoal, EndpointEvaluator
    from nv14_random_splice import _local_search

    level = parse_level_string("0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
                               + "|5^60,60")
    source = (InputFrame(),) * 30
    donor = source[:5] + (InputFrame(right=True),) * 5 + source[10:]
    goal = EndpointGoal(20, "max-x")
    assert (EndpointEvaluator(level, goal).evaluate(donor).progress_key <
            EndpointEvaluator(level, goal).evaluate(source).progress_key)
    for backend in ("endpoint-auto", "local"):
        survivors = []
        found, used = _local_search(
            level, source, goal, start=0,
            config=RandomSpliceConfig(search_backend=backend, workers=1,
                                      beam=8, endpoint_repair_steps=0),
            iterations=4, rounds=1, seed=3, include_partial=True,
            initial_population=(donor,), population_callback=survivors.extend)
        assert used > 0
        assert donor in survivors
        assert len(survivors) <= 8
        assert all(len(frames) == len(source) for frames in survivors)
        assert all(EndpointEvaluator(level, goal).evaluate(frames) is not None
                   for frames in survivors)


def test_actual_backends_reject_donors_outside_mutable_range():
    from nv14_engine import (APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS,
                             InputFrame, parse_level_string)
    from nv14_endpoint import EndpointGoal
    from nv14_random_splice import _local_search

    level = parse_level_string("0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
                               + "|5^60,60")
    source = (InputFrame(),) * 30
    incompatible = (InputFrame(left=True),) + source[1:]
    goal = EndpointGoal(20, "max-x")
    for backend in ("endpoint-auto", "local"):
        with pytest.raises(ValueError, match="immutable|outside the editable"):
            _local_search(level, source, goal, start=4,
                          config=RandomSpliceConfig(search_backend=backend,
                                                    workers=1, beam=8),
                          iterations=4, rounds=1, seed=3,
                          initial_population=(incompatible,),
                          population_callback=lambda _x: None)


def test_hybrid_restart_preserves_original_auto_local_reset_control():
    from nv14_cli import parse_arguments
    config = RandomSpliceConfig(search_backend="hybrid-restart", hybrid_cycles=2,
                                hybrid_local_rounds=3)
    calls = []

    def search(_level, frames, _goal, *, config, **kwargs):
        assert "initial_population" not in kwargs
        assert "population_callback" not in kwargs
        calls.append((config.search_backend, frames))
        return (((7, 11), 4),), 1

    _, used, count = _search_stage(None, (10, 0), SpliceSearchStage('end', object(), 0, 1),
                                   config, random.Random(7), local_search=search,
                                   evaluator_factory=FakeEvaluator)
    assert used == 4 and count == 4
    assert calls == [('endpoint-auto', (10, 0)), ('local', (7, 11)),
                     ('endpoint-auto', (7, 11)), ('local', (7, 11))]
    args = parse_arguments(['auto', 'level.ltm', '--auto-splice-files', '522',
                            '--auto-splice-search', 'hybrid-restart'])
    assert args.auto_splice_search == 'hybrid-restart'


def test_hybrid_shared_beam_reserves_live_near_miss_niche():
    class MixedEvaluator(FakeEvaluator):
        def evaluate(self, frames):
            return FakeEvaluation(frames[0], frames[1], feasible=frames[0] < 10)

    incoming = []
    def search(_level, _source, _goal, *, population_callback, initial_population,
               **kwargs):
        incoming.append(tuple(initial_population))
        if len(incoming) == 1:
            population_callback(((3, 1), (4, 1), (5, 1),
                                 (12, 2), (11, 3), (10, 4)))
            return (((3, 1), 1),), 4
        return (), 0

    _search_stage(None, (15, 0), SpliceSearchStage('end', object(), 0, 1),
                  RandomSpliceConfig(search_backend='hybrid', beam=4,
                                     hybrid_cycles=1), random.Random(1),
                  local_search=search, evaluator_factory=MixedEvaluator)
    assert len(incoming) == 2
    assert (3, 1) in incoming[1]
    assert len(incoming[1]) == 4
    # A candidate worse than the feasible winner is still a parent/donor.
    assert any(candidate[0] >= 10 for candidate in incoming[1])

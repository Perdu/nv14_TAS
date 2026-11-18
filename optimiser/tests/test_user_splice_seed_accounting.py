"""Patch 134: per-seed accounting must reflect actual backend work."""
from __future__ import annotations

from types import SimpleNamespace
import random

from nv14_random_splice import RandomSpliceConfig
from nv14_splice_backend import SpliceSearchStage, _search_stage
from nv14_endpoint import EndpointGoal
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


class FakeEvaluation:
    feasible = True
    dead = False

    def __init__(self, frames):
        self.value = frames[0]

    @property
    def objective_key(self):
        return (self.value,)

    @property
    def progress_key(self):
        return (self.value,)


class FakeEvaluator:
    def __init__(self, level, goal):
        pass

    def evaluate(self, frames):
        return FakeEvaluation(frames)


def test_hybrid_counts_known_prefix_failures_and_unexplained_zero_evaluations():
    seen = []

    def fake_search(_level, _frames, _goal, *, config, **kwargs):
        seen.append(config.search_backend)
        if config.search_backend == 'endpoint-auto':
            raise ValueError('the immutable prefix dies before the editable ranges')
        return (), 0

    stats = {}
    _found, evaluations, calls = _search_stage(
        None, (10, 0), SpliceSearchStage('end', SimpleNamespace(target_frame=1), 0, 1),
        RandomSpliceConfig(search_backend='hybrid', hybrid_cycles=8,
                           hybrid_stagnation_cycles=2), random.Random(4),
        local_search=fake_search, evaluator_factory=FakeEvaluator,
        diagnostics=stats)
    assert (evaluations, calls) == (0, 4)
    assert stats == {'cycles': 2, 'prefix_dead': 2, 'zero_evaluation_calls': 2}
    assert seen == ['endpoint-auto', 'local'] * 2


def test_hybrid_counts_short_seed_without_guessing_prefix_death():
    stats = {}
    _found, evaluations, calls = _search_stage(
        None, (10, 0), SpliceSearchStage('end', SimpleNamespace(target_frame=8), 0, 8),
        RandomSpliceConfig(search_backend='hybrid', hybrid_cycles=1),
        random.Random(7), evaluator_factory=FakeEvaluator,
        local_search=lambda *a, **kw: ((), 0), diagnostics=stats)
    assert (evaluations, calls) == (0, 2)
    assert stats == {'cycles': 1, 'short_seed': 2}


def test_positive_evaluations_are_not_early_exits():
    stats = {}
    _found, evaluations, calls = _search_stage(
        None, (10, 0), SpliceSearchStage('end', SimpleNamespace(target_frame=1), 0, 1),
        RandomSpliceConfig(search_backend='local'), random.Random(3),
        local_search=lambda *a, **kw: ((), 20),
        evaluator_factory=FakeEvaluator, diagnostics=stats)
    assert (evaluations, calls) == (20, 1)
    assert stats == {'cycles': 1}


def test_user_splice_prints_one_completion_line_per_seed(monkeypatch):
    import nv14_user_splice as us
    level, frames, _ = _baseline()

    def fake_search(level, branch, stage, config, rng, **kwargs):
        kwargs['diagnostics'].update(cycles=8, prefix_dead=16)
        return (), 0, 16

    monkeypatch.setattr(us, '_search_stage', fake_search)
    progress = []
    optimise_user_splices(
        level, frames, [UserSpliceStage('end', EndpointGoal(10, 'max-x'), 0, 10)],
        RandomSpliceConfig(search_backend='hybrid', hybrid_cycles=8,
                           iterations=4, rounds=1, workers=1),
        single_input_seed=True, completion_policy='checkpoint',
        progress=progress.append)
    summaries = [line for line in progress if line.startswith('[auto:user-splice:seed]')]
    assert len(summaries) == 1
    line = summaries[0]
    assert '\n' not in line
    assert "stage 1/1 'end' seed 1/1 [current input run]" in line
    assert 'cycles 8/8' in line
    assert 'backend calls 16; evaluations 0' in line
    assert 'early exits 16 (prefix died 16)' in line
    assert 'stage-best updates 0' in line

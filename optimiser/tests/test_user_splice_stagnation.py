"""Adaptive per-stage stagnation budgets (independent of outer Auto runs)."""
from dataclasses import dataclass
from pathlib import Path
import random

import pytest

from nv14_cli import parse_arguments
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, _search_stage


@dataclass(frozen=True)
class FakeEvaluation:
    value: int
    @property
    def feasible(self):
        return True
    @property
    def objective_key(self):
        return (self.value,)
    @property
    def progress_key(self):
        return (self.value,)


def test_auto_local_alternate_and_continue_from_other_backend(monkeypatch):
    import nv14_user_splice as us

    class Evaluator:
        def __init__(self, level, goal):
            pass
        def evaluate(self, candidate):
            return FakeEvaluation(candidate[0])

    seen = []
    # A and L improvements on cycle 1, then A improves on cycle 2;
    # cycles 3-4 stagnate and exhaust the patience of 2 cycles.
    next_winners = [9, 8, 7, None, None, None, None, None]
    def search(level, branch, goal, *, config, iterations, rounds, **kwargs):
        idx = len(seen)
        seen.append((config.search_backend, branch[0], iterations, rounds))
        value = next_winners[idx]
        return ((((value,), 10),), 5) if value is not None else ((), 5)

    monkeypatch.setattr(us, 'EndpointEvaluator', Evaluator)
    monkeypatch.setattr(us, '_local_search', search)
    logs = []
    stage = UserSpliceStage('end', object(), 0, 10)
    found, evals, calls = _search_stage(
        None, (10,), stage,
        RandomSpliceConfig(search_backend='both', iterations=101, splice_rounds=3,
                           splice_stagnation_rounds=2),
        random.Random(5), progress=logs.append)
    assert seen == [
        ('endpoint-auto', 10, 50, 3), ('local', 9, 51, 3),
        ('endpoint-auto', 8, 50, 3), ('local', 7, 51, 3),
        ('endpoint-auto', 7, 50, 3), ('local', 7, 51, 3),
        ('endpoint-auto', 7, 50, 3), ('local', 7, 51, 3)]
    assert calls == 8 and evals == 40
    assert set(candidate for candidate, _ in found) == {(9,), (8,), (7,)}
    assert 'stagnant 2/2' in logs[-1]


def test_stagnation_only_resets_on_valid_stage_improvement(monkeypatch):
    import nv14_user_splice as us
    class Evaluator:
        def __init__(self, level, goal): pass
        def evaluate(self, candidate):
            return FakeEvaluation(candidate[0])

    seen = []
    def fake_search(level, branch, goal, *, config, **kwargs):
        seen.append(branch)
        # Physically attractive but forbidden by an earlier stage.
        return (((1,), 10),), 3
    monkeypatch.setattr(us, 'EndpointEvaluator', Evaluator)
    monkeypatch.setattr(us, '_local_search', fake_search)
    found, evals, calls = _search_stage(
        None, (10,), UserSpliceStage('end', object(), 0, 10),
        RandomSpliceConfig(search_backend='local', iterations=100,
                           splice_stagnation_rounds=3),
        random.Random(1), stage_rank=lambda frames: None if frames[0] == 1 else (frames[0],))
    assert calls == 3 and evals == 9
    assert seen == [(10,), (10,), (10,)]
    assert [candidate for candidate, _ in found] == [(1,)]


def test_named_stagnation_config_layering_and_cli(tmp_path: Path):
    base = tmp_path / 'base.toml'
    named = tmp_path / 'named.toml'
    base.write_text('[auto]\nruns=2\n[multi-splicer]\nsearch="both"\niterations=400\nrounds=3\nstagnation-rounds=4\nruns=5\n')
    named.write_text('[multi-splicer]\nfiles=["556", "end"]\n')
    args = parse_arguments(['auto', 'level.ltm', '--config', str(base),
                            '--splice-config', str(named)])
    assert args.auto_splice_stagnation_rounds == 4
    assert args.auto_splice_rounds == 3
    assert args.auto_runs == 5
    overridden = parse_arguments(['auto', 'level.ltm', '--config', str(base),
                                  '--splice-config', str(named),
                                  '--splice-stagnation-rounds', '8'])
    assert overridden.auto_splice_stagnation_rounds == 8
    legacy = parse_arguments(['auto', 'level.ltm', '--config', str(base),
                              '--splice-config', str(named),
                              '--auto-splice-stagnation-rounds', '7'])
    assert legacy.auto_splice_stagnation_rounds == 7
    ordinary = parse_arguments(['auto', 'level.ltm', '--config', str(base)])
    assert ordinary.auto_runs == 2
    assert ordinary.auto_splice_stagnation_rounds == 0


def test_stagnation_validation():
    for bad in (-1, 1.5, True):
        with pytest.raises(ValueError, match='splice_stagnation_rounds'):
            RandomSpliceConfig(splice_stagnation_rounds=bad)


def test_real_adaptive_search_keeps_canonical_full_completion():
    from nv14_auto import evaluate_replay_with_sentinel
    from nv14_endpoint import EndpointGoal
    from nv14_user_splice import optimise_user_splices
    from tests.test_random_splice import _baseline

    level, source, _ = _baseline()
    stages = (UserSpliceStage('203', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('end', EndpointGoal(18, 'max-x'), 5, 18))
    saved, messages = [], []
    result = optimise_user_splices(
        level, source, stages,
        RandomSpliceConfig(search_backend='both', iterations=12, splice_rounds=1,
                           splice_stagnation_rounds=1, rounds=1, frontier=2,
                           workers=1, endpoint_repair_steps=0),
        best_callback=saved.append, progress=messages.append)
    completed = evaluate_replay_with_sentinel(level, result.frames)
    assert completed.valid and completed.finish_tick == len(result.frames)
    assert result.attempts >= 4
    assert any('[auto:user-splice:refine]' in msg for msg in messages)
    assert all(evaluate_replay_with_sentinel(level, frames).valid for frames in saved)

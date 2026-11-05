"""Independent backend stagnation budgets for named multi-splicing."""
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


def test_auto_then_local_continuous_phases_and_repeat(monkeypatch):
    import nv14_user_splice as us

    class Evaluator:
        def __init__(self, level, goal):
            pass

        def evaluate(self, candidate):
            return FakeEvaluation(candidate[0])

    # One uninterrupted backend call each phase; Local's gain feeds the next
    # continuous Auto phase. Auto stagnates on Local's new seed; Local was
    # already exhausted on that seed and must not run needlessly again.
    changes = [9, 8, None]
    seen = []

    def search(level, frames, goal, *, config, iterations, rounds,
               stagnation_rounds, **kwargs):
        seen.append((config.search_backend, frames[0], iterations,
                     rounds, stagnation_rounds))
        next_value = changes[len(seen) - 1]
        return ((((next_value,), 10),), 5) if next_value is not None else ((), 5)

    monkeypatch.setattr(us, 'EndpointEvaluator', Evaluator)
    monkeypatch.setattr(us, '_local_search', search)
    logs = []
    results, evaluations, calls = _search_stage(
        None, (10,), UserSpliceStage('556', object(), 0, 10),
        RandomSpliceConfig(search_backend='both', iterations=101,
                           splice_rounds=8,  # ignored in continuous phase mode
                           splice_auto_stagnation_rounds=2,
                           splice_local_stagnation_rounds=3),
        random.Random(2), progress=logs.append)

    assert seen == [('endpoint-auto', 10, 50, 0, 2),
                    ('local', 9, 51, 0, 3),
                    ('endpoint-auto', 8, 50, 0, 2)]
    assert (calls, evaluations) == (3, 15)
    assert {frames for frames, _ in results} == {(9,), (8,)}
    assert 'cycle 2 both modes stagnated; advancing' in logs[-1]


def test_backend_stagnation_owned_by_each_continuous_search(monkeypatch):
    import nv14_user_splice as us

    class Evaluator:
        def __init__(self, level, goal):
            pass

        def evaluate(self, frames):
            return FakeEvaluation(frames[0])

    seen = []

    def search(level, frames, goal, *, config, rounds, stagnation_rounds, **kwargs):
        seen.append((config.search_backend, rounds, stagnation_rounds))
        return (), 2

    monkeypatch.setattr(us, 'EndpointEvaluator', Evaluator)
    monkeypatch.setattr(us, '_local_search', search)
    messages = []
    _result, evaluations, calls = _search_stage(
        None, (10,), UserSpliceStage('end', object(), 0, 10),
        RandomSpliceConfig(search_backend='both', iterations=100,
                           splice_rounds=3, splice_auto_stagnation_rounds=4,
                           splice_local_stagnation_rounds=7),
        random.Random(1), progress=messages.append)
    assert seen == [('endpoint-auto', 0, 4), ('local', 0, 7)]
    assert calls == 2 and evaluations == 4
    assert any('continuous endpoint-auto phase' in line for line in messages)
    assert any('continuous local phase' in line for line in messages)


def test_nonadmissible_candidate_does_not_restart_phases(monkeypatch):
    import nv14_user_splice as us

    class Evaluator:
        def __init__(self, level, goal):
            pass

        def evaluate(self, frames):
            return FakeEvaluation(frames[0])

    seen = []

    def search(level, frames, goal, *, config, rounds, stagnation_rounds, **kwargs):
        seen.append((config.search_backend, frames, rounds, stagnation_rounds))
        return ((((1,), 10),), 1)

    monkeypatch.setattr(us, 'EndpointEvaluator', Evaluator)
    monkeypatch.setattr(us, '_local_search', search)
    results, _, calls = _search_stage(
        None, (10,), UserSpliceStage('end', object(), 0, 10),
        RandomSpliceConfig(search_backend='both', iterations=100,
                           splice_auto_stagnation_rounds=2,
                           splice_local_stagnation_rounds=3),
        random.Random(1),
        stage_rank=lambda frames: None if frames[0] == 1 else (frames[0],))
    assert calls == 2
    assert seen == [('endpoint-auto', (10,), 0, 2),
                    ('local', (10,), 0, 3)]
    assert [frames for frames, _ in results] == [(1,)]


def test_phase_settings_layer_from_base_and_named_toml(tmp_path: Path):
    base = tmp_path / 'base.toml'
    named = tmp_path / 'named.toml'
    base.write_text('[auto]\nruns=2\n[multi-splicer]\nsearch="both"\niterations=400\n'
                    'rounds=1\nauto-stagnation-rounds=10\n'
                    'local-stagnation-rounds=50\nruns=5\n')
    named.write_text('[multi-splicer]\nfiles=["556", "end"]\n')
    args = parse_arguments(['auto', 'level.ltm', '--config', str(base),
                            '--splice-config', str(named)])
    assert args.auto_splice_auto_stagnation_rounds == 10
    assert args.auto_splice_local_stagnation_rounds == 50
    assert args.auto_splice_rounds == 1
    assert args.auto_runs == 5
    override = parse_arguments(['auto', 'level.ltm', '--config', str(base),
                                '--splice-config', str(named),
                                '--splice-auto-stagnation-rounds', '3',
                                '--splice-local-stagnation-rounds', '4'])
    assert (override.auto_splice_auto_stagnation_rounds,
            override.auto_splice_local_stagnation_rounds) == (3, 4)
    ordinary = parse_arguments(['auto', 'level.ltm', '--config', str(base)])
    assert ordinary.auto_runs == 2
    assert ordinary.auto_splice_auto_stagnation_rounds == 0
    assert ordinary.auto_splice_local_stagnation_rounds == 0


def test_phase_settings_validate_without_clashing_with_legacy():
    for kwargs in [dict(splice_auto_stagnation_rounds=-1),
                   dict(splice_local_stagnation_rounds=True),
                   dict(splice_auto_stagnation_rounds=10,
                        splice_stagnation_rounds=4),
                   dict(search_backend='both', splice_auto_stagnation_rounds=10),
                   dict(search_backend='both', splice_local_stagnation_rounds=50)]:
        with pytest.raises(ValueError):
            RandomSpliceConfig(**kwargs)
    RandomSpliceConfig(search_backend='both', splice_auto_stagnation_rounds=10,
                       splice_local_stagnation_rounds=50)
    RandomSpliceConfig(search_backend='local', splice_local_stagnation_rounds=50)
    RandomSpliceConfig(search_backend='endpoint-auto', splice_auto_stagnation_rounds=10)


def test_real_phase_search_preserves_completed_replays():
    from nv14_auto import evaluate_replay_with_sentinel
    from nv14_endpoint import EndpointGoal
    from nv14_user_splice import optimise_user_splices
    from tests.test_random_splice import _baseline

    level, source, _ = _baseline()
    stages = (UserSpliceStage('203', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('end', EndpointGoal(18, 'max-x'), 5, 18))
    outputs, logs = [], []
    result = optimise_user_splices(
        level, source, stages,
        RandomSpliceConfig(search_backend='both', iterations=12,
                           splice_rounds=1, splice_auto_stagnation_rounds=1,
                           splice_local_stagnation_rounds=1, rounds=1,
                           frontier=2, workers=1, endpoint_repair_steps=0),
        best_callback=outputs.append, progress=logs.append)
    checked = evaluate_replay_with_sentinel(level, result.frames)
    assert checked.valid and checked.finish_tick == len(result.frames)
    assert result.attempts >= 4  # one Auto phase + one Local phase per stage
    assert any('Auto: 1 stagnant backend rounds' in line for line in logs)
    assert all(evaluate_replay_with_sentinel(level, frames).valid for frames in outputs)

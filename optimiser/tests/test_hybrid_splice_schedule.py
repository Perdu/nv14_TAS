"""Patch 75: causal Auto/Local schedule and matched restart-control tests.

These tests exercise coordination and feasibility; real-route speedups and
SWF fidelity must still be measured independently.
"""
from dataclasses import dataclass
import random

import pytest

from nv14_cli import parse_arguments
from nv14_random_splice import RandomSpliceConfig
from nv14_splice_backend import SpliceSearchStage, _search_stage
from tas import build_command


@dataclass(frozen=True)
class Evaluation:
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


class Evaluator:
    def __init__(self, level, goal):
        pass

    def evaluate(self, frames):
        return Evaluation(frames[0])


def stage():
    return SpliceSearchStage("end", object(), 0, 9)


def test_one_auto_then_n_local_rounds_per_cycle_and_no_incumbent_regression():
    seen = []
    winners = [(9,), (8,), (7,), (11,)]

    def search(_level, frames, _goal, *, config, iterations, rounds, seed, **kwargs):
        seen.append((config.search_backend, frames, iterations, rounds, seed))
        candidate = winners[len(seen) - 1]
        return ((candidate, 9),), 2

    messages = []
    result, used, calls = _search_stage(
        None, (10,), stage(),
        RandomSpliceConfig(search_backend="hybrid", iterations=25,
                           hybrid_cycles=2, hybrid_local_rounds=3),
        random.Random(4), evaluator_factory=Evaluator, local_search=search,
        progress=messages.append)
    assert [(b, f, it, r) for b, f, it, r, _ in seen] == [
        ("endpoint-auto", (10,), 25, 1), ("local", (9,), 25, 3),
        ("endpoint-auto", (8,), 25, 1), ("local", (7,), 25, 3),
    ]
    assert (used, calls) == (8, 4)
    assert [candidate for candidate, _ in result] == winners
    assert 'no eligible stage gain' in messages[-2]
    assert f'seed {seen[0][4]}' in messages[0]
    assert 'best eligible objective key (9,)' in messages[0]


def test_control_has_exact_same_round_budget_and_seed_draws():
    def run(mode):
        seen = []

        def search(_level, frames, _goal, *, config, seed, iterations, rounds, **kwargs):
            seen.append((config.search_backend, frames, seed, iterations, rounds))
            return (), 0

        results = _search_stage(
            None, (10,), stage(), RandomSpliceConfig(
                search_backend=mode, iterations=50, hybrid_cycles=4,
                hybrid_local_rounds=7), random.Random(29),
            local_search=search, evaluator_factory=Evaluator)
        return seen, results

    hybrid, hybrid_result = run("hybrid")
    control, control_result = run("hybrid-local-control")
    assert hybrid_result == control_result == ((), 0, 8)
    assert [x[2:] for x in hybrid] == [x[2:] for x in control]
    assert [x[0] for x in hybrid] == ["endpoint-auto", "local"] * 4
    assert [x[0] for x in control] == ["local", "local"] * 4
    assert [x[4] for x in control] == [1, 7] * 4


def test_earlier_stage_ineligible_candidate_never_becomes_seed():
    seen = []

    def search(_level, frames, _goal, *, config, **kwargs):
        seen.append(frames)
        return (((1,), 9),), 3  # looks better but invalid at an earlier goal

    results, used, calls = _search_stage(
        None, (10,), stage(), RandomSpliceConfig(
            search_backend="hybrid", hybrid_cycles=2, hybrid_local_rounds=2),
        random.Random(1), evaluator_factory=Evaluator, local_search=search,
        stage_rank=lambda f: None if f[0] == 1 else (f[0],))
    assert seen == [(10,)] * 4
    assert results == (((1,), 9),)
    assert (used, calls) == (12, 4)


def test_hybrid_stagnation_is_cycle_based_not_backend_based():
    seen = []

    def search(_level, frames, _goal, **kwargs):
        seen.append((frames, kwargs["config"].search_backend))
        return (), 1

    _, used, calls = _search_stage(
        None, (10,), stage(), RandomSpliceConfig(
            search_backend="hybrid", hybrid_cycles=15,
            hybrid_stagnation_cycles=2), random.Random(9),
        evaluator_factory=Evaluator, local_search=search)
    assert (used, calls) == (4, 4)
    assert len(seen) == 4


def test_hybrid_budget_validation_still_rejects_invalid_cycle_limits():
    for kwargs in (
        {"hybrid_local_rounds": 0},
        {"hybrid_cycles": False},
        {"hybrid_stagnation_cycles": -1},
        {"hybrid_stagnation_cycles": 4, "hybrid_cycles": 3},
    ):
        with pytest.raises(ValueError):
            RandomSpliceConfig(search_backend="hybrid", **kwargs)


@pytest.mark.parametrize('mode', ('hybrid', 'hybrid-restart', 'hybrid-local-control'))
def test_hybrid_ignores_unused_stagnation_rounds_and_speeds(mode):
    from nv14_splice_backend import splice_config_for_round

    config = RandomSpliceConfig(
        search_backend=mode, hybrid_cycles=2, hybrid_local_rounds=3,
        splice_rounds=7, splice_auto_stagnation_rounds=10,
        splice_local_stagnation_rounds=50, splice_stagnation_rounds=4,
        splice_speed='fast', splice_round_speeds=('current', 'slow'))
    assert splice_config_for_round(config, 0) is config
    assert splice_config_for_round(config, 2) is config

    def run(legacy_settings):
        seen = []
        def search(_level, frames, _goal, *, config, iterations, rounds,
                   seed, **kwargs):
            seen.append((config.search_backend, frames, iterations, rounds, seed))
            return (), 1
        result = _search_stage(
            None, (10,), stage(), legacy_settings, random.Random(44),
            evaluator_factory=Evaluator, local_search=search)
        return seen, result

    baseline = RandomSpliceConfig(search_backend=mode, hybrid_cycles=2,
                                  hybrid_local_rounds=3)
    assert run(config) == run(baseline)
    assert [c[3] for c in run(config)[0]] == [1, 3, 1, 3]



def test_hybrid_shortcut_and_toml_configuration(tmp_path):
    command = build_command("hybrid", "88-4", "522", env={})
    assert command[2] == "hybrid"
    assert command[command.index("--goal-config") + 1] == "../splices/88-4/522.txt"
    parsed = parse_arguments(["hybrid", "level.ltm", "--goal-config", "some/522.txt",
                              "--splice-hybrid-local-rounds", "11",
                              "--splice-hybrid-cycles", "3"])
    assert parsed.auto_splice_search == "hybrid"
    assert parsed.auto_splice_hybrid_local_rounds == 11
    assert parsed.auto_splice_hybrid_cycles == 3
    assert parsed.auto_runs == 1
    config = tmp_path / "splices.toml"
    config.write_text('[multi-splicer]\nfiles=["522", "end"]\nsearch="hybrid-local-control"\n'
                      'hybrid-local-rounds=4\nhybrid-cycles=2\n')
    parsed = parse_arguments(["auto", "source.ltm", "--splice-config", str(config)])
    assert parsed.auto_splice_search == "hybrid-local-control"
    assert (parsed.auto_splice_hybrid_local_rounds, parsed.auto_splice_hybrid_cycles) == (4, 2)


def test_hybrid_does_not_resume_a_incompatible_legacy_backend_phase():
    with pytest.raises(ValueError, match='does not support resuming'):
        _search_stage(None, (10,), stage(), RandomSpliceConfig(search_backend='hybrid'),
                      random.Random(3), resume_phase={'backend':'local'})


@pytest.mark.parametrize('mode', ('hybrid', 'hybrid-restart', 'hybrid-local-control'))
def test_real_native_hybrid_accepts_ignored_backend_phase_limits(mode):
    from nv14_endpoint import EndpointGoal
    from tests.test_random_splice import _baseline

    level, source, _ = _baseline()
    goal = EndpointGoal(10, 'min-x')
    result, used, calls = _search_stage(
        level, source, SpliceSearchStage('end', goal, 0, 10),
        RandomSpliceConfig(
            search_backend=mode, iterations=3, workers=1, beam=8,
            hybrid_cycles=1, hybrid_local_rounds=2, endpoint_repair_steps=0,
            splice_rounds=9, splice_stagnation_rounds=2,
            splice_auto_stagnation_rounds=10,
            splice_local_stagnation_rounds=50, splice_speed='slow',
            splice_round_speeds=('fast', 'normal')),
        random.Random(12))
    assert calls == 2 and used >= 0
    assert all(len(frames) == len(source) for frames, _ in result)


def test_real_native_hybrid_and_control_preserve_completed_source():
    """Small integration exercise; not an SWF or performance benchmark."""
    from nv14_auto import evaluate_replay_with_sentinel
    from nv14_endpoint import EndpointGoal, EndpointEvaluator
    from tests.test_random_splice import _baseline
    from nv14_user_splice import _search_stage as named_stage_search, UserSpliceStage

    level, source, _ = _baseline()
    goal = EndpointGoal(10, 'min-x')
    stage = UserSpliceStage('end', goal, 0, 10)
    evaluator = EndpointEvaluator(level, goal)
    for mode in ('hybrid', 'hybrid-local-control'):
        found, used, calls = named_stage_search(
            level, source, stage,
            RandomSpliceConfig(search_backend=mode, iterations=5,
                               hybrid_local_rounds=2, hybrid_cycles=2,
                               workers=1, beam=8, endpoint_repair_steps=0),
            random.Random(42))
        assert calls == 4 and used > 0
        assert all(len(candidate) == len(source) for candidate, _ in found)
        assert all(evaluator.evaluate(candidate) is not None for candidate, _ in found)
    finished = evaluate_replay_with_sentinel(level, source)
    assert finished.valid and finished.finish_tick == len(source)

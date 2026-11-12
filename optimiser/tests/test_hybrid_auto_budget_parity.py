"""Patch 109: standalone Hybrid does not throttle its initial Auto phase."""
import random

import pytest

from nv14_cli import _load_named_splice_stages, parse_arguments
from nv14_random_splice import RandomSpliceConfig
from nv14_splice_backend import SpliceSearchStage, _search_stage
from tests.test_random_splice import _baseline


def goal_and_args(tmp_path, *, extra=(), config_text=None, goal_text=None):
    goal = tmp_path / '234.txt'
    goal.write_text(goal_text or '[local]\nobjective="earliest-arrival"\n'
                    'search="population"\ntarget-frame=10\nrange="2:10"\n'
                    'target-region="0:800,0:600"\n')
    config = tmp_path / 'config.toml'
    config.write_text(config_text or '[auto]\niterations=1200\n'
                      'endpoint-iterations-per-frame=500\n'
                      '[multi-splicer]\niterations=10000\n')
    args = parse_arguments(['hybrid', 'level.ltm', '--config', str(config),
                            '--goal-config', str(goal), *extra])
    level, frames, _ = _baseline()
    stage = _load_named_splice_stages(level, frames, args, tmp_path, ('234',))[0]
    return args, stage


def test_shortcut_initial_auto_uses_same_scaled_budget_as_direct_auto(tmp_path):
    args, stage = goal_and_args(tmp_path)
    assert args._single_hybrid_mode
    assert args.auto_splice_iterations == 10000
    assert stage.config_overrides['hybrid_auto_iterations'] == 9 * 500


def test_explicit_auto_budget_follows_direct_auto_priority(tmp_path):
    _, stage = goal_and_args(tmp_path, extra=['--auto-endpoint-iterations', '900'])
    assert stage.config_overrides['hybrid_auto_iterations'] == 900
    _, stage = goal_and_args(tmp_path, extra=['--auto-endpoint-iterations-per-frame', '123'])
    assert stage.config_overrides['hybrid_auto_iterations'] == 9 * 123
    _, stage = goal_and_args(tmp_path, config_text='[auto]\niterations=4321\n'
                             '[multi-splicer]\niterations=10000\n')
    assert stage.config_overrides['hybrid_auto_iterations'] == 4321


def test_hybrid_specific_budget_overrides_automatic_budget(tmp_path):
    args, stage = goal_and_args(tmp_path, extra=['--splice-hybrid-auto-iterations', '800'])
    assert args.auto_splice_hybrid_auto_iterations == 800
    assert 'hybrid_auto_iterations' not in stage.config_overrides
    args, stage = goal_and_args(tmp_path, config_text='[auto]\niterations=2000\n'
                         'endpoint-iterations-per-frame=500\n'
                         '[multi-splicer]\niterations=10000\nhybrid-auto-iterations=6000\n')
    assert args.auto_splice_hybrid_auto_iterations == 6000
    assert 'hybrid_auto_iterations' not in stage.config_overrides


def test_full_route_hybrid_still_uses_multi_budget(tmp_path):
    config = tmp_path / 'route.toml'
    config.write_text('[multi-splicer]\nfiles=["234"]\nsearch="hybrid"\niterations=10000\n')
    goal = tmp_path / '234.txt'
    goal.write_text('[local]\nobjective="min-x"\ntarget-frame=10\nrange="2:10"\n')
    level, frames, _ = _baseline()
    args = parse_arguments(['auto', 'level.ltm', '--splice-config', str(config)])
    stage = _load_named_splice_stages(level, frames, args, tmp_path, ('234',))[0]
    assert not args._single_hybrid_mode
    assert 'hybrid_auto_iterations' not in stage.config_overrides


class Evaluation:
    def __init__(self, frames):
        self.objective_key = (frames[0],)
        self.progress_key = (frames[0],)
        self.feasible = True
        self.dead = False


class Evaluator:
    def __init__(self, _level, _goal):
        pass

    def evaluate(self, frames):
        return Evaluation(frames)


def test_auto_round_receives_its_own_budget_and_local_keeps_its_budget():
    seen = []

    def search(_level, frames, _goal, *, config, iterations, rounds, **_kwargs):
        seen.append((config.search_backend, iterations, rounds, frames))
        if config.search_backend == 'endpoint-auto':
            return (((frames[0] - 1,), 10),), 10
        return (), 2

    config = RandomSpliceConfig(search_backend='hybrid', iterations=10000,
                                hybrid_auto_iterations=37500,
                                hybrid_cycles=1, hybrid_local_rounds=5)
    found, used, calls = _search_stage(
        None, (5,), SpliceSearchStage('234', object(), 0, 10), config,
        random.Random(0), local_search=search, evaluator_factory=Evaluator)
    assert seen == [('endpoint-auto', 37500, 1, (5,)),
                    ('local', 10000, 5, (4,))]
    assert (used, calls) == (12, 2)
    assert ((4,), 10) in found


@pytest.mark.parametrize('value', [0, -1, False, 2.5])
def test_hybrid_auto_budget_validation(value):
    with pytest.raises(ValueError, match='hybrid_auto_iterations'):
        RandomSpliceConfig(hybrid_auto_iterations=value)


def test_selected_hybrid_forwards_auto_backend_progress():
    from nv14_user_splice import UserSpliceStage, _search_stage as selected_stage
    messages = []

    def search(_level, _frames, _goal, *, config, **kwargs):
        progress = kwargs.get('progress')
        if progress:
            progress('round 1/1: starting 15 worker(s)')
        return (), 1

    from unittest.mock import patch
    # The named adapter supplies a progress callback to each actual backend,
    # not just the outer cycle logger.
    with patch('nv14_user_splice._local_search', search), \
            patch('nv14_user_splice.EndpointEvaluator', Evaluator):
        selected_stage(None, (5,), UserSpliceStage('234', object(), 0, 10),
                       RandomSpliceConfig(search_backend='hybrid', iterations=10,
                                          hybrid_cycles=1), random.Random(1),
                       backend_progress=True, progress=messages.append)
    assert sum('round 1/1: starting' in line for line in messages) == 2

"""Random, complexity and physics waypoint selectors share stage search policy."""
from dataclasses import replace
import random

import pytest

from nv14_cli import parse_arguments
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig, _splicer_search
from tests.test_random_splice import _baseline


@pytest.mark.parametrize('mode', ['random', 'complexity', 'physics'])
def test_sampled_modes_accept_both_backend_with_separate_stagnation(mode):
    args = parse_arguments(['auto', 'replay.ltm', '--auto-random-splice',
                            '--auto-splice-mode', mode, '--auto-splice-search', 'both',
                            '--splice-auto-stagnation-rounds', '2',
                            '--splice-local-stagnation-rounds', '3',
                            '--splice-waypoint-lookback', '4'])
    cfg = RandomSpliceConfig(mode=mode, search_backend=args.auto_splice_search,
                             splice_auto_stagnation_rounds=args.auto_splice_auto_stagnation_rounds,
                             splice_local_stagnation_rounds=args.auto_splice_local_stagnation_rounds,
                             waypoint_stage_lookback=args.auto_splice_waypoint_lookback)
    assert cfg.waypoint_stage_lookback == 4


def test_sampled_backend_reuses_shared_dispatch(monkeypatch):
    import nv14_splice_backend as shared
    level, frames, _ = _baseline()
    seen = []
    def fake(level, branch, stage, config, rng, **kwargs):
        seen.append((stage.start, stage.end, config.search_backend, config.iterations))
        return (((branch, stage.goal.target_frame),), 19, 2)
    monkeypatch.setattr(shared, '_search_stage', fake)
    cfg = RandomSpliceConfig(search_backend='both', iterations=12,
                             splice_auto_stagnation_rounds=2,
                             splice_local_stagnation_rounds=2)
    found, used = _splicer_search(level, frames, EndpointGoal(14,'max-x'),
                                   start=3, editable_end=14, config=cfg,
                                   iterations=12, rounds=1, seed=99)
    assert found == ((frames,14),) and used == 19
    assert seen == [(3,14,'both',12)]


def test_waypoint_lookback_validation():
    with pytest.raises(ValueError, match='waypoint_stage_lookback'):
        RandomSpliceConfig(waypoint_stage_lookback=0)

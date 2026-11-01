"""Persist up to 64 stage candidates without widening active search."""
from dataclasses import replace
import nv14_user_splice as us
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_archive_64_keeps_more_candidates_than_active_beam(monkeypatch):
    level, source, _ = _baseline()
    stages = [UserSpliceStage('a', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('b', EndpointGoal(10, 'min-x'), 0, 10)]
    candidates = tuple((tuple(InputFrame(left=i%2==0, right=i%2==1)
                         for _ in range(i)) + source[i:], 10) for i in range(1, 30))
    calls, saves = [], {}
    def search(_level, branch, stage, *a, **kw):
        calls.append((stage.name, branch))
        return (candidates if stage.name == 'a' else ()), 1, 1
    monkeypatch.setattr(us, '_search_stage', search)
    optimise_user_splices(level, source, stages,
        RandomSpliceConfig(iterations=2, rounds=1, frontier=3, save_frontier=64),
        completion_policy='checkpoint', frontier_callback=lambda name, frames: saves.__setitem__(name, frames))
    assert 3 < len(saves['a']) <= 64
    assert len([1 for name, _ in calls if name == 'b']) <= 3


def test_archive_size_validation():
    for n in (0, 257, True):
        try:
            RandomSpliceConfig(save_frontier=n)
        except ValueError:
            pass
        else:
            raise AssertionError(f'accepted {n}')


def test_save_frontier_is_configurable_in_per_level_toml(tmp_path):
    from nv14_cli import parse_arguments
    shared = tmp_path/'shared.toml'
    shared.write_text('[auto]\nruns=3\n[multi-splicer]\nfrontier=3\n')
    per_level = tmp_path/'level.toml'
    per_level.write_text('[multi-splicer]\nfiles=["a","end"]\nsave-frontier=64\n')
    args = parse_arguments(['auto','level.ltm','--config',str(shared),
                            '--splice-config',str(per_level)])
    assert args.auto_splice_frontier == 3
    assert args.auto_splice_save_frontier == 64
    args = parse_arguments(['auto','level.ltm','--config',str(shared),
                            '--splice-config',str(per_level),
                            '--splice-save-frontier','32'])
    assert args.auto_splice_save_frontier == 32

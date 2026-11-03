from nv14_cli import parse_arguments
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from nv14_endpoint import EndpointGoal
from tests.test_random_splice import _baseline


def test_cli_each_best_is_opt_in():
    args = parse_arguments(['auto', 'level.ltm', '--splice-each-best'])
    assert args.auto_splice_each_best
    assert not parse_arguments(['auto', 'level.ltm']).auto_splice_each_best


def test_saved_best_is_extra_first_seed(monkeypatch):
    import nv14_user_splice as module
    level, frames, _ = _baseline()
    stages = [UserSpliceStage('one', EndpointGoal(18, 'max-x'), 0, 18)]
    visited = []
    def fake_search(level, branch, stage, config, rng, **kwargs):
        visited.append(branch)
        return (), 0, 1
    monkeypatch.setattr(module, '_search_stage', fake_search)
    # Distinct feasible checkpoint deliberately starts at a different route.
    saved = tuple(frames[:2] + (frames[2],) + frames[3:])
    optimise_user_splices(level, frames, stages,
                          RandomSpliceConfig(iterations=2, rounds=1),
                          saved_stage_candidates={'one': (saved,)},
                          start_from_stage_bests=True,
                          completion_policy='checkpoint')
    assert visited

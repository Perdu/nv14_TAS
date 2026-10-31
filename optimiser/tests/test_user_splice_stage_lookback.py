"""User-named splice lookback is configurable without changing n-1/n-2 defaults."""

from dataclasses import replace
from pathlib import Path

import pytest

from nv14_cli import parse_arguments
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import _stage_sources, _stage_sources_history


def test_default_history_exactly_matches_existing_two_back_policy():
    first = [('a',), ('b',)]
    second = [('c',), ('d',)]
    assert RandomSpliceConfig().stage_lookback == 2
    for frontier in (1, 2, 3, 5):
        assert _stage_sources_history([first, second], frontier) == _stage_sources(
            first, second, frontier)


def test_lookback_one_disables_older_seeds():
    assert _stage_sources_history([[('new',)], [('old',)]][:1], 3) == [('new',)]


def test_lookback_three_and_four_keep_oldest_stage_even_when_frontier_is_small():
    history = [
        [('recent',), ('recent2',)],
        [('older',), ('older2',)],
        [('oldest',), ('oldest2',)],
        [('ancient',)],
    ]
    assert _stage_sources_history(history[:3], 2) == [
        ('recent',), ('older',), ('oldest',)]
    assert _stage_sources_history(history, 4) == [
        ('recent',), ('recent2',), ('older',), ('older2',), ('oldest',), ('ancient',)]
    assert _stage_sources_history(history[:3], 5) == [
        ('recent',), ('recent2',), ('older',), ('older2',), ('oldest',)]


def test_deduplicated_history_can_fill_slots_from_another_frontier():
    history = [[('a',), ('b',)], [('a',), ('c',)], [('a',), ('d',)]]
    assert _stage_sources_history(history, 4) == [('a',), ('b',), ('c',), ('d',)]


@pytest.mark.parametrize('invalid', [0, -2, True, 1.5, '2'])
def test_history_config_rejects_invalid_values(invalid):
    with pytest.raises(ValueError, match='stage_lookback'):
        RandomSpliceConfig(stage_lookback=invalid)


def test_per_level_toml_overrides_shared_defaults_without_affecting_other_modes(tmp_path: Path):
    base = tmp_path / 'base.toml'
    base.write_text('[auto]\niterations=1000\nruns=4\n'
                    '[multi-splicer]\niterations=400\nfrontier=3\nruns=5\n')
    level = tmp_path / 'level.toml'
    level.write_text('[multi-splicer]\nfiles=["203", "408", "end"]\nlookback=3\n')
    args = parse_arguments(['auto', 'level.ltm', '--config', str(base),
                            '--splice-config', str(level)])
    assert args.auto_splice_files == ('203', '408', 'end')
    assert args.auto_splice_stage_lookback == 3
    assert args.auto_splice_frontier == 3
    assert args.auto_runs == 5
    override = parse_arguments(['auto', 'level.ltm', '--config', str(base),
                                '--splice-config', str(level),
                                '--splice-stage-lookback', '4'])
    assert override.auto_splice_stage_lookback == 4
    unchanged = parse_arguments(['auto', 'level.ltm', '--config', str(base)])
    assert unchanged.auto_runs == 4
    assert unchanged.auto_splice_stage_lookback == 2


def test_lookback_cli_invalid_in_other_splice_modes():
    with pytest.raises(SystemExit, match='named user splice'):
        parse_arguments(['auto', 'level.ltm', '--auto-random-splice',
                         '--splice-stage-lookback', '3'])


def test_entire_stage_pipeline_keeps_configured_history(monkeypatch):
    import nv14_user_splice as us
    from nv14_endpoint import EndpointGoal
    from nv14_user_splice import UserSpliceStage, optimise_user_splices
    from tests.test_random_splice import _baseline

    level, frames, _ = _baseline()
    stages = [UserSpliceStage(name, EndpointGoal(18, 'max-x'), 0, 18)
              for name in ('a', 'b', 'c', 'end')]
    original = us._stage_sources_history
    seen = []

    def spy(history, frontier):
        seen.append(len(history))
        return original(history, frontier)

    monkeypatch.setattr(us, '_stage_sources_history', spy)
    monkeypatch.setattr(us, '_search_stage',
                        lambda level, branch, stage, config, rng: ((), 0, 1))
    optimise_user_splices(level, frames, stages,
                          RandomSpliceConfig(iterations=2, rounds=1,
                                             stage_lookback=3),
                          completion_policy='checkpoint')
    assert seen == [1, 2, 3, 3]
    seen.clear()
    optimise_user_splices(level, frames, stages,
                          RandomSpliceConfig(iterations=2, rounds=1,
                                             stage_lookback=2),
                          completion_policy='checkpoint')
    assert seen == [1, 2, 2, 2]

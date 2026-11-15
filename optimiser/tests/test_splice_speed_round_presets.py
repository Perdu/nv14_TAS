"""Complete-cycle splice speed presets and outer-round schedules."""
from pathlib import Path

import pytest

from nv14_cli import build_parser
from nv14_random_splice import RandomSpliceConfig
from nv14_splice_backend import splice_config_for_round


@pytest.mark.parametrize('name,cycles,patience', [
    ('very-fast', 1, 0), ('vfast', 1, 0),
    ('fast', 4, 1), ('normal', 4, 3), ('slow', 4, 10),
])
def test_speed_presets(name, cycles, patience):
    cfg = RandomSpliceConfig(search_backend='both', splice_speed=name,
                             splice_rounds=4, splice_stagnation_rounds=8)
    actual = splice_config_for_round(cfg, 0)
    assert actual.splice_rounds == cycles
    assert actual.splice_stagnation_rounds == patience
    assert actual.splice_auto_stagnation_rounds == 0
    assert actual.splice_local_stagnation_rounds == 0
    # Selecting a speed never mutates the caller's configuration.
    assert cfg.splice_stagnation_rounds == 8


def test_round_schedule_uses_current_then_slow():
    cfg = RandomSpliceConfig(search_backend='both',
                            splice_auto_stagnation_rounds=4,
                            splice_local_stagnation_rounds=9,
                            splice_round_speeds=('current', 'slow'))
    assert splice_config_for_round(cfg, 0) == cfg
    assert splice_config_for_round(cfg, 1).splice_stagnation_rounds == 10
    assert splice_config_for_round(cfg, 1).splice_auto_stagnation_rounds == 0
    assert splice_config_for_round(cfg, 1).splice_local_stagnation_rounds == 0
    assert splice_config_for_round(cfg, 5) == splice_config_for_round(cfg, 1)


def test_single_backend_receives_its_own_patience_only():
    cfg = RandomSpliceConfig(search_backend='local', splice_speed='fast')
    actual = splice_config_for_round(cfg, 0)
    assert actual.splice_auto_stagnation_rounds == 0
    assert actual.splice_local_stagnation_rounds == 0
    assert actual.splice_stagnation_rounds == 1


def test_speed_cli_and_toml(tmp_path: Path):
    config = tmp_path / 'multi.toml'
    config.write_text('[multi-splicer]\nsplice-files=["100", "end"]\n'
                      'speed="fast"\nround-speeds=["current", "slow"]\n')
    parsed = build_parser().parse_args(['auto', 'fake.ltm', '--splice-config', str(config)])
    assert parsed.auto_splice_speed == 'fast'
    assert parsed.auto_splice_round_speeds == ('current', 'slow')
    parsed = build_parser().parse_args(['auto', 'fake.ltm', '--splice-config', str(config),
                                        '--splice-speed', 'normal',
                                        '--splice-round-speeds', 'fast,slow'])
    assert parsed.auto_splice_speed == 'normal'
    assert parsed.auto_splice_round_speeds == ('fast', 'slow')


@pytest.mark.parametrize('speed,expected', [('very-fast', 0), ('vfast', 0),
                                            ('fast', 1), ('normal', 3), ('slow', 10)])
def test_named_hybrid_toml_speed_uses_cycle_patience(tmp_path: Path, speed, expected):
    config = tmp_path / 'multi.toml'
    config.write_text('[multi-splicer]\nfiles=["100", "end"]\n'
                      'search="hybrid"\n'
                      'hybrid-cycles=12\n'
                      f'speed="{speed}"\n')
    parsed = build_parser().parse_args(['auto', 'fake.ltm', '--splice-config', str(config)])
    actual = splice_config_for_round(RandomSpliceConfig(
        search_backend=parsed.auto_splice_search,
        hybrid_cycles=parsed.auto_splice_hybrid_cycles,
        splice_speed=parsed.auto_splice_speed), 0)
    assert actual.hybrid_stagnation_cycles == expected
    assert actual.hybrid_cycles == (1 if speed in ('very-fast', 'vfast') else 12)


@pytest.mark.parametrize('speed', ['very-fast', 'vfast'])
def test_very_fast_cli_and_toml_scheduled_speed(tmp_path: Path, speed):
    config = tmp_path / 'multi.toml'
    config.write_text('[multi-splicer]\nfiles=["100", "end"]\n'
                      f'speed="{speed}"\nround-speeds=["current", "{speed}"]\n')
    parsed = build_parser().parse_args(['auto', 'fake.ltm', '--splice-config', str(config)])
    assert parsed.auto_splice_speed == speed
    assert parsed.auto_splice_round_speeds == ('current', speed)
    actual = splice_config_for_round(RandomSpliceConfig(
        search_backend='both', splice_speed=parsed.auto_splice_speed,
        splice_round_speeds=parsed.auto_splice_round_speeds), 1)
    assert (actual.splice_auto_stagnation_rounds, actual.splice_local_stagnation_rounds) == (0, 0)
    assert actual.splice_stagnation_rounds == 0
    assert actual.splice_rounds == 1
    parsed_cli = build_parser().parse_args(['auto', 'fake.ltm', '--auto-random-splice',
                                            '--splice-speed', speed,
                                            '--splice-round-speeds', f'current,{speed}'])
    assert parsed_cli.auto_splice_speed == speed
    assert parsed_cli.auto_splice_round_speeds == ('current', speed)


@pytest.mark.parametrize('mode', ['endpoint-auto', 'local', 'both'])
def test_very_fast_is_exactly_one_backend_round_per_selected_backend(mode):
    config = RandomSpliceConfig(search_backend=mode, splice_speed='vfast',
                                splice_rounds=5)
    actual = splice_config_for_round(config, 0)
    assert actual.splice_stagnation_rounds == 0
    assert actual.splice_auto_stagnation_rounds == 0
    assert actual.splice_local_stagnation_rounds == 0
    assert actual.splice_rounds == 1


def test_invalid_schedules_rejected():
    with pytest.raises(ValueError):
        RandomSpliceConfig(splice_round_speeds=('extreme',))


def test_preset_runs_shared_backend_without_custom_evaluator():
    import random
    from nv14_endpoint import EndpointGoal
    from nv14_splice_backend import SpliceSearchStage, _search_stage
    from tests.test_random_splice import _baseline
    level, frames, _ = _baseline()
    cfg = splice_config_for_round(RandomSpliceConfig(
        search_backend='both', splice_speed='fast', iterations=2), 0)
    calls = []

    def fake_search(_level, _frames, _goal, **kwargs):
        calls.append(kwargs['config'].search_backend)
        return (), 0

    found, used, phases = _search_stage(
        level, frames, SpliceSearchStage('goal', EndpointGoal(10, 'max-x'), 0, 10),
        cfg, random.Random(0), local_search=fake_search)
    assert found == () and used == 0 and phases == 2
    assert calls == ['endpoint-auto', 'local']


def test_very_fast_fixed_one_cycle_even_after_improvement():
    import random
    from nv14_splice_backend import SpliceSearchStage, _search_stage
    from tests.test_hybrid_splice_schedule import Evaluator

    seen = []
    def search(_level, frames, _goal, *, config, rounds, **kwargs):
        seen.append((config.search_backend, frames, rounds))
        return ((((frames[0] - 1,), 9),), 1)

    for mode, expected_backends in (
        ('endpoint-auto', ['endpoint-auto']),
        ('local', ['local']),
        ('both', ['endpoint-auto', 'local']),
    ):
        seen.clear()
        cfg = splice_config_for_round(RandomSpliceConfig(
            search_backend=mode, splice_speed='vfast', iterations=20), 0)
        _search_stage(None, (10,), SpliceSearchStage('end', object(), 0, 9),
                      cfg, random.Random(3), local_search=search,
                      evaluator_factory=Evaluator)
        assert [backend for backend, _, _ in seen] == expected_backends
        assert [rounds for _, _, rounds in seen] == [1] * len(expected_backends)

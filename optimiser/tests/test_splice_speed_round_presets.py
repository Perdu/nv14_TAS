"""Independent Auto/Local stagnation presets and per-outer-round schedules."""
from pathlib import Path

import pytest

from nv14_cli import build_parser
from nv14_random_splice import RandomSpliceConfig
from nv14_splice_backend import splice_config_for_round


@pytest.mark.parametrize('name,limits', [
    ('fast', (3, 10)), ('normal', (5, 20)), ('slow', (10, 50)),
])
def test_speed_presets(name, limits):
    cfg = RandomSpliceConfig(search_backend='both', splice_speed=name)
    actual = splice_config_for_round(cfg, 0)
    assert (actual.splice_auto_stagnation_rounds, actual.splice_local_stagnation_rounds) == limits
    assert actual.splice_stagnation_rounds == 0


def test_round_schedule_uses_current_then_slow():
    cfg = RandomSpliceConfig(search_backend='both',
                            splice_auto_stagnation_rounds=4,
                            splice_local_stagnation_rounds=9,
                            splice_round_speeds=('current', 'slow'))
    assert splice_config_for_round(cfg, 0) == cfg
    assert (splice_config_for_round(cfg, 1).splice_auto_stagnation_rounds,
            splice_config_for_round(cfg, 1).splice_local_stagnation_rounds) == (10, 50)
    assert splice_config_for_round(cfg, 5) == splice_config_for_round(cfg, 1)


def test_single_backend_receives_its_own_patience_only():
    cfg = RandomSpliceConfig(search_backend='local', splice_speed='fast')
    actual = splice_config_for_round(cfg, 0)
    assert actual.splice_auto_stagnation_rounds == 0
    assert actual.splice_local_stagnation_rounds == 10


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

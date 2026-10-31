"""Continuous Auto endpoint campaigns retain their search between stagnant rounds."""

import pytest
from nv14_auto_endpoint import AutoEndpointConfig, optimise_auto_endpoint_campaign
from nv14_endpoint import EndpointGoal
from tests.test_random_splice import _baseline


def test_unlimited_requires_stagnation():
    level, frames, _ = _baseline()
    with pytest.raises(ValueError, match="stagnation"):
        optimise_auto_endpoint_campaign(level, frames, EndpointGoal(10, "min-x"),
                                        AutoEndpointConfig(iterations=0), workers=1, runs=0)


def test_stagnation_rounds_stop_one_continuous_campaign():
    level, frames, _ = _baseline()
    lines = []
    _, _, used = optimise_auto_endpoint_campaign(
        level, frames, EndpointGoal(10, "min-x"),
        AutoEndpointConfig(iterations=0, seed=7, range_start=0, range_end=10),
        workers=1, runs=0, stagnation_rounds=3, progress=lines.append)
    assert used == 0
    completed = [line for line in lines if "complete:" in line]
    assert len(completed) == 3
    assert "stagnant 3/3" in completed[-1]
    assert "round 4" not in "\n".join(lines)

@pytest.mark.parametrize('workers', [1, 2])
def test_continuous_auto_retains_partial_survivors_between_rounds(workers):
    from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame, parse_level_string
    level = parse_level_string('0' * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + '|5^60,60')
    source = (InputFrame(),) * 40
    goal = EndpointGoal(20, 'earliest-arrival', target_region=(900, 910, 900, 910))
    messages = []
    _, best, count = optimise_auto_endpoint_campaign(
        level, source, goal, AutoEndpointConfig(
            iterations=85, beam_width=12, repair_steps=0,
            range_end=20, seed=41), workers=workers, runs=0,
        stagnation_rounds=2, progress=messages.append)
    assert best is None
    assert count > 0
    second = [line for line in messages
              if 'round 2/until stagnant: starting' in line]
    assert len(second) == 1
    count_inherited = int(second[0].split(' inherited candidates')[0].split('; ')[-1])
    assert count_inherited >= 2
    assert any('stagnant 2/2' in line for line in messages)

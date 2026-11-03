"""Airborne Shift cleanup must not change a single observed game tick."""
from nv14_auto import evaluate_replay_with_sentinel
from nv14_engine import InputFrame
from nv14_replay import clean_ineffective_air_jumps
from tests.test_random_splice import _baseline


def test_no_jump_route_stays_identical():
    level, frames, _ = _baseline()
    assert clean_ineffective_air_jumps(level, frames) == frames


def test_air_jump_cleanup_never_changes_full_replay_trace():
    level, frames, _ = _baseline()
    with_pulse = list(frames)
    for tick in (10, 11):
        with_pulse[tick] = InputFrame(right=True, jump=True)
    source = evaluate_replay_with_sentinel(level, with_pulse)
    cleaned = clean_ineffective_air_jumps(level, with_pulse)
    result = evaluate_replay_with_sentinel(level, cleaned)
    # Whether this particular location proves removable is physics-dependent.
    assert result.finish_tick == source.finish_tick
    assert result.successful_jumps == source.successful_jumps
    assert result.route_control_events == source.route_control_events
    assert tuple((p.x, p.y, p.vx, p.vy) for p in result.trace) == tuple(
        (p.x, p.y, p.vx, p.vy) for p in source.trace)

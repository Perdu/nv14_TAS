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


def test_incomplete_stage_checkpoint_removes_physics_noop_air_press():
    level, frames, _ = _baseline()
    modified = list(frames)
    # Frame 2 jumps from the floor; frame 6 is an ineffective re-press in
    # mid-air. This run does not complete, so the old baseline.valid guard
    # silently disabled all cleaning on its stage checkpoint.
    modified[2] = InputFrame(right=True, jump=True)
    modified[6] = InputFrame(right=True, jump=True)
    baseline = evaluate_replay_with_sentinel(level, modified)
    assert not baseline.valid
    assert baseline.point(5).in_air
    result = clean_ineffective_air_jumps(level, modified)
    assert result[2].jump  # real launch retained
    assert not result[6].jump  # no-effect press erased
    checked = evaluate_replay_with_sentinel(level, result)
    assert checked.finish_tick == baseline.finish_tick
    assert checked.dead_tick == baseline.dead_tick
    assert checked.successful_jumps == baseline.successful_jumps
    assert checked.route_control_events == baseline.route_control_events
    assert tuple((p.x, p.y, p.vx, p.vy) for p in checked.trace) == tuple(
        (p.x, p.y, p.vx, p.vy) for p in baseline.trace)

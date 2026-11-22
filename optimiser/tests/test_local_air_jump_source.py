"""Local should discard provable air-press no-ops before window search."""

from nv14_engine import InputFrame
from nv14_local import optimise_local_windows
from nv14_objectives import evaluate, objective_function
from tests.test_random_splice import _baseline


def _airborne_pulse_source():
    level, frames, _ = _baseline()
    modified = list(frames)
    modified[2] = InputFrame(right=True, jump=True)  # genuine floor jump
    modified[6] = InputFrame(right=True, jump=True)  # new, failed air press
    return level, modified


def test_local_removes_inactive_air_press_before_window_search(monkeypatch):
    level, frames = _airborne_pulse_source()
    import nv14_local

    original_session = nv14_local.NativeSearchSession
    seen_inputs = []

    class RecordingSession:
        def __init__(self, level):
            self.native = original_session(level)

        def search(self, inputs, spec):
            seen_inputs.append(tuple(inputs))
            return self.native.search(inputs, spec)

    monkeypatch.setattr(nv14_local, "NativeSearchSession", RecordingSession)
    optimised, report = optimise_local_windows(
        level, frames, target_frame=8, range_start=6, range_end=6,
        objective_name="max-x", window_size=1, passes=1,
        local_inputs="all", workers=1, python_resimulate=True,
    )
    assert seen_inputs and all(not source[6].jump for source in seen_inputs)
    assert optimised[2].jump  # the valid jump was outside the mutable range
    assert not optimised[6].jump
    assert tuple(optimised[:6]) == tuple(frames[:6])
    direct = evaluate(level, optimised, 8, objective_function("max-x"))
    assert report.score == direct.score
    assert report.state.state_key() == direct.state.state_key()


def test_local_never_cleans_air_pulses_outside_mutable_ranges():
    level, frames = _airborne_pulse_source()
    optimised, _ = optimise_local_windows(
        level, frames, target_frame=8, range_start=4, range_end=4,
        objective_name="max-x", window_size=1, passes=1,
        local_inputs="all", workers=1,
    )
    assert optimised[6] == frames[6]


def test_local_preserves_pulse_crossing_mutable_range_boundary():
    level, frames = _airborne_pulse_source()
    frames[7] = InputFrame(right=True, jump=True)
    optimised, _ = optimise_local_windows(
        level, frames, target_frame=8, range_start=6, range_end=6,
        objective_name="max-x", window_size=1, passes=1,
        local_inputs="all", workers=1,
    )
    # Frame 7 is fixed: removing only tick 6 would alter its rising edge.
    assert optimised[7].jump


def test_late_auto_clean_option_is_retired():
    import pytest
    from nv14_cli import parse_arguments

    with pytest.raises(SystemExit):
        parse_arguments(["auto", "input.txt", "--auto-clean-air-jumps"])

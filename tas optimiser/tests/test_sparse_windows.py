import random

from nv14_engine import InputFrame, parse_level_string
from optimize_replay import (
    _sample_sparse_local_windows,
    _sparse_window_capacity,
    evaluate,
    objective_function,
    optimise_local_windows,
)


def open_air_level():
    return parse_level_string("0" * (31 * 23) + "|5^100,100")


def frame_bits(frames):
    return [(frame.left, frame.right, frame.jump) for frame in frames]


def test_sparse_window_sampler_is_unique_reproducible_and_span_limited() -> None:
    kwargs = dict(
        range_start=10,
        range_end=30,
        window_size=4,
        window_span=8,
        windows_per_pass=12,
    )
    first = _sample_sparse_local_windows(rng=random.Random(12345), **kwargs)
    second = _sample_sparse_local_windows(rng=random.Random(12345), **kwargs)

    assert [window.frames for window in first] == [window.frames for window in second]
    assert len({window.frames for window in first}) == 12
    assert all(len(window.frames) == 4 for window in first)
    assert all(window.end - window.start + 1 <= 8 for window in first)
    assert any(window.end - window.start + 1 > 4 for window in first)


def test_sparse_window_span_equal_to_size_has_contiguous_capacity() -> None:
    assert _sparse_window_capacity(10, 4, 4) == 7
    windows = _sample_sparse_local_windows(
        0,
        9,
        4,
        window_span=4,
        windows_per_pass=99,
        rng=random.Random(7),
    )
    assert len(windows) == 7
    assert all(window.frames == tuple(range(window.start, window.start + 4)) for window in windows)


def test_unbounded_sparse_sampler_draws_directly_from_the_full_range() -> None:
    kwargs = dict(
        range_start=100,
        range_end=1100,
        window_size=8,
        window_span=None,
        windows_per_pass=100,
    )
    first = _sample_sparse_local_windows(rng=random.Random(202640), **kwargs)
    second = _sample_sparse_local_windows(rng=random.Random(202640), **kwargs)

    assert [window.frames for window in first] == [window.frames for window in second]
    assert len({window.frames for window in first}) == 100
    assert all(len(window.frames) == 8 for window in first)
    assert all(100 <= window.start <= window.end <= 1100 for window in first)


def test_sparse_search_resamples_after_an_unchanged_pass() -> None:
    level = open_air_level()
    frames = [InputFrame() for _ in range(6)]
    logs: list[str] = []

    optimise_local_windows(
        level,
        frames,
        target_frame=5,
        range_start=0,
        range_end=5,
        objective_name="max-x",
        window_size=2,
        passes=3,
        minimum_improvement=float("inf"),
        local_inputs="direction",
        window_shape="sparse",
        windows_per_pass=2,
        seed=314159,
        progress=logs.append,
    )

    sampled_passes = [line for line in logs if "sampled 2 sparse windows" in line]
    assert len(sampled_passes) == 3
    assert any("resampled next pass" in line for line in logs)


def test_sparse_direction_search_is_reproducible_from_master_seed() -> None:
    level = open_air_level()
    frames = [InputFrame() for _ in range(8)]
    kwargs = dict(
        target_frame=7,
        range_start=0,
        range_end=7,
        objective_name="max-x",
        window_size=3,
        passes=2,
        local_inputs="direction",
        window_shape="sparse",
        window_span=6,
        windows_per_pass=5,
        window_order="random",
        restarts=3,
        seed=987654321,
        progress=None,
    )

    first, first_result = optimise_local_windows(level, frames, **kwargs)
    second, second_result = optimise_local_windows(level, frames, **kwargs)

    assert first_result.score == second_result.score
    assert frame_bits(first) == frame_bits(second)


def test_sparse_all_input_search_uses_selected_frame_sets() -> None:
    level = open_air_level()
    frames = [InputFrame() for _ in range(5)]
    baseline = evaluate(level, frames, 4, objective_function("max-x"))

    optimised, result = optimise_local_windows(
        level,
        frames,
        target_frame=4,
        range_start=0,
        range_end=4,
        objective_name="max-x",
        window_size=2,
        passes=1,
        local_inputs="all",
        window_shape="sparse",
        window_span=4,
        windows_per_pass=3,
        seed=2026,
        progress=None,
    )

    assert result.score > baseline.score
    assert frame_bits(optimised) != frame_bits(frames)


def test_sparse_random_all_input_workers_match_serial_trajectory() -> None:
    level = open_air_level()
    frames = [InputFrame() for _ in range(8)]
    kwargs = dict(
        target_frame=7,
        range_start=0,
        range_end=7,
        objective_name="max-x",
        window_size=3,
        passes=2,
        local_inputs="all",
        window_order="random",
        window_shape="sparse",
        window_span=6,
        windows_per_pass=5,
        restarts=4,
        seed=246813579,
        progress=None,
    )

    serial, serial_result = optimise_local_windows(
        level, frames, workers=1, **kwargs
    )
    parallel, parallel_result = optimise_local_windows(
        level, frames, workers=2, **kwargs
    )

    assert parallel_result.score == serial_result.score
    assert parallel_result.state.state_key() == serial_result.state.state_key()
    assert frame_bits(parallel) == frame_bits(serial)


def test_sparse_forward_window_workers_match_serial_in_both_input_modes() -> None:
    level = open_air_level()
    frames = [InputFrame() for _ in range(10)]
    for local_inputs in ("direction", "all"):
        kwargs = dict(
            target_frame=9,
            range_start=0,
            range_end=9,
            objective_name="max-x",
            window_size=3,
            passes=2,
            local_inputs=local_inputs,
            window_order="forward",
            window_shape="sparse",
            window_span=6,
            windows_per_pass=5,
            seed=86420,
            progress=None,
        )
        serial, serial_result = optimise_local_windows(
            level, frames, workers=1, **kwargs
        )
        parallel, parallel_result = optimise_local_windows(
            level, frames, workers=3, **kwargs
        )

        assert parallel_result.score == serial_result.score
        assert parallel_result.state.state_key() == serial_result.state.state_key()
        assert frame_bits(parallel) == frame_bits(serial)


def test_sparse_direction_search_can_repair_lockness_missed_press() -> None:
    from pathlib import Path

    from nv14_engine import parse_level_string
    from nv14_replay import decode_complex_replay, parse_combined_level_replay
    from optimize_replay import successful_jump_frames

    source = Path(__file__).with_name("example_lockness_missed_jumps.txt")
    combined = parse_combined_level_replay(source.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string)

    optimised, _result = optimise_local_windows(
        level,
        replay.frames,
        target_frame=90,
        range_start=70,
        range_end=85,
        objective_name="min-x",
        window_size=4,
        passes=3,
        minimum_improvement=1000.0,
        local_inputs="direction",
        window_shape="sparse",
        window_span=12,
        windows_per_pass=20,
        seed=12345,
        progress=None,
    )

    assert [frame.jump for frame in optimised] == [frame.jump for frame in replay.frames]
    assert successful_jump_frames(level, optimised, 90) == frozenset({32, 64, 81})

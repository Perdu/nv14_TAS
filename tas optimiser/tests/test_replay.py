from pathlib import Path

import pytest

from nv14_engine import InputFrame, parse_level_string
from nv14_replay import (
    changed_frame_indices,
    decode_complex_replay,
    encode_complex_replay,
    parse_combined_level_replay,
    simulate_through_frame,
)
from optimize_replay import (
    AxisWindow,
    JumpPulse,
    apply_jump_pattern,
    evaluate,
    jump_press_frames,
    objective_function,
    optimise_local_windows,
    successful_jump_frames,
    parse_axis_window,
    parse_jump_count_range,
    parse_jump_length_range,
)


EXAMPLE = Path(__file__).with_name("example_motherlode.txt")
LOCKNESS_MISSED_JUMPS = Path(__file__).with_name("example_lockness_missed_jumps.txt")


def load_example():
    combined = parse_combined_level_replay(EXAMPLE.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string)
    return combined, replay, level


def load_lockness_missed_jumps():
    combined = parse_combined_level_replay(
        LOCKNESS_MISSED_JUMPS.read_text(encoding="utf-8")
    )
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string)
    return combined, replay, level


def test_complex_replay_round_trip() -> None:
    combined, replay, _level = load_example()
    assert replay.tick_count == 337
    assert encode_complex_replay(replay) == combined.replay_string


def test_changed_frame_indices_includes_a_length_only_tail() -> None:
    frames = [InputFrame(right=True) for _ in range(4)]
    assert changed_frame_indices(frames, frames[:2]) == [2, 3]
    assert changed_frame_indices(frames[:2], frames) == [2, 3]


def test_motherlode_frame_71_matches_trace() -> None:
    _combined, replay, level = load_example()
    state = simulate_through_frame(level, replay.frames, 71)
    assert state.player.pos.x == 194.7525374933706
    assert state.player.pos.y == 208.57311251320692


def test_one_frame_local_optimisation_can_change_replay() -> None:
    _combined, replay, level = load_example()
    optimised, result = optimise_local_windows(
        level,
        replay.frames,
        target_frame=1,
        range_start=0,
        range_end=0,
        objective_name="max-x",
        window_size=1,
        passes=1,
        progress=None,
    )
    assert optimised[0].right
    assert not optimised[0].left
    assert result.state.player.pos.x > 59.901


def test_forward_contiguous_local_search_reuses_live_prefixes(monkeypatch) -> None:
    """Later forward windows must see accepted earlier edits without replaying 0..N."""
    import optimize_replay as opt

    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    source = [InputFrame() for _ in range(6)]
    objective = objective_function("max-x")
    original_state_before = opt.state_before_frame
    calls = 0

    def counted_state_before(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_state_before(*args, **kwargs)

    monkeypatch.setattr(opt, "state_before_frame", counted_state_before)
    for local_inputs in ("all", "direction"):
        optimised, result = optimise_local_windows(
            level,
            source,
            target_frame=5,
            range_start=0,
            range_end=5,
            objective_name="max-x",
            window_size=1,
            passes=1,
            local_inputs=local_inputs,
            window_order="forward",
            progress=None,
        )
        direct = evaluate(level, optimised, 5, objective)
        assert result.state.state_key() == direct.state.state_key()
        assert result.score == direct.score

    # One initial prefix per forward-contiguous pass and input mode, rather
    # than once for each of the six overlapping windows.
    assert calls == 2


def test_reverse_contiguous_local_search_caches_prefixes(monkeypatch) -> None:
    """Reverse windows must not rebuild every prefix from frame zero."""
    import optimize_replay as opt

    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    source = [InputFrame() for _ in range(8)]
    original_state_before = opt.state_before_frame
    calls = 0

    def counted_state_before(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_state_before(*args, **kwargs)

    monkeypatch.setattr(opt, "state_before_frame", counted_state_before)
    optimised, result = optimise_local_windows(
        level,
        source,
        target_frame=7,
        range_start=0,
        range_end=7,
        objective_name="max-x",
        window_size=2,
        passes=1,
        local_inputs="direction",
        window_order="reverse",
        progress=None,
    )

    direct = evaluate(level, optimised, 7, objective_function("max-x"))
    assert result.state.state_key() == direct.state.state_key()
    assert result.score == direct.score
    assert calls == 0


def test_parse_axis_window_supports_bounded_and_open_intervals() -> None:
    assert parse_axis_window("100:105") == AxisWindow(100.0, 105.0)
    assert parse_axis_window(":105") == AxisWindow(float("-inf"), 105.0)
    assert parse_axis_window("100:") == AxisWindow(100.0, float("inf"))
    assert parse_axis_window("102.5") == AxisWindow(102.5, 102.5)


def test_y_window_rejects_an_x_objective_outside_target_y_range() -> None:
    _combined, replay, level = load_example()
    objective = objective_function("max-x")

    accepted = evaluate(
        level,
        replay.frames,
        71,
        objective,
        y_window=AxisWindow(208.5, 208.6),
    )
    rejected = evaluate(
        level,
        replay.frames,
        71,
        objective,
        y_window=AxisWindow(209.0, 210.0),
    )

    assert accepted.feasible
    assert accepted.score == accepted.state.player.pos.x
    assert not rejected.feasible
    assert rejected.score == float("-inf")


def test_x_window_rejects_a_y_objective_outside_target_x_range() -> None:
    _combined, replay, level = load_example()
    result = evaluate(
        level,
        replay.frames,
        71,
        objective_function("min-y"),
        x_window=AxisWindow(195.0, 196.0),
    )

    assert not result.feasible
    assert result.score == float("-inf")


def test_jump_search_range_parsers() -> None:
    assert parse_jump_count_range("2") == (2, 2)
    assert parse_jump_count_range("2:3") == (2, 3)
    assert parse_jump_length_range("4") == (4, 4)
    assert parse_jump_length_range("1:30") == (1, 30)
    assert parse_jump_length_range("2:") == (2, None)


def test_apply_jump_pattern_only_replaces_jump_input_in_mutable_range() -> None:
    _combined, replay, _level = load_example()
    modified = apply_jump_pattern(
        replay.frames,
        range_start=10,
        range_end=20,
        pulses=(JumpPulse(12, 3), JumpPulse(18, 2)),
    )

    for index, (before, after) in enumerate(zip(replay.frames, modified, strict=True)):
        assert before.left == after.left
        assert before.right == after.right
        if 10 <= index <= 20:
            assert after.jump == (index in {12, 13, 14, 18, 19})
        else:
            assert before.jump == after.jump


def test_direction_only_local_search_preserves_jump_inputs_and_required_events() -> None:
    _combined, replay, level = load_example()
    baseline_jumps = successful_jump_frames(level, replay.frames, 30)

    optimised, _result = optimise_local_windows(
        level,
        replay.frames,
        target_frame=30,
        range_start=20,
        range_end=30,
        objective_name="max-x",
        window_size=3,
        passes=1,
        local_inputs="direction",
        progress=None,
    )

    assert [frame.jump for frame in optimised] == [frame.jump for frame in replay.frames]
    assert baseline_jumps <= successful_jump_frames(level, optimised, 30)


def test_direction_only_requires_replay_press_edges_including_baseline_misses() -> None:
    _combined, replay, level = load_lockness_missed_jumps()

    assert jump_press_frames(replay.frames, 161) == frozenset({32, 64, 81, 116})
    assert successful_jump_frames(level, replay.frames, 161) == frozenset({32, 64})


def test_direction_only_can_prioritise_repairing_a_missed_press_over_score() -> None:
    _combined, replay, level = load_lockness_missed_jumps()
    baseline = evaluate(level, replay.frames, 90, objective_function("min-x", None))

    optimised, result = optimise_local_windows(
        level,
        replay.frames,
        target_frame=90,
        range_start=70,
        range_end=85,
        objective_name="min-x",
        window_size=4,
        passes=1,
        minimum_improvement=1000.0,
        local_inputs="direction",
        progress=None,
    )

    assert [frame.jump for frame in optimised] == [frame.jump for frame in replay.frames]
    assert successful_jump_frames(level, optimised, 90) == frozenset({32, 64, 81})
    # The jump repair is mandatory even though it worsens min-x and cannot meet
    # the deliberately huge minimum-improvement threshold.
    assert result.score < baseline.score


def test_direction_only_progressively_repairs_both_lockness_missed_presses() -> None:
    _combined, replay, level = load_lockness_missed_jumps()

    optimised, _result = optimise_local_windows(
        level,
        replay.frames,
        target_frame=125,
        range_start=70,
        range_end=120,
        objective_name="min-x",
        window_size=4,
        passes=2,
        local_inputs="direction",
        progress=None,
    )

    assert [frame.jump for frame in optimised] == [frame.jump for frame in replay.frames]
    assert successful_jump_frames(level, optimised, 125) == frozenset(
        {32, 64, 81, 116}
    )


def test_optimistic_horizontal_bounds_cover_open_air_direction_sequences() -> None:
    from itertools import product

    from nv14_engine import InputFrame, parse_level_string
    from optimize_replay import optimistic_horizontal_bounds

    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    fixed = [InputFrame() for _ in range(5)]
    initial = level.initial_state()
    lower, upper = optimistic_horizontal_bounds(initial, fixed, target_frame=4)

    for directions in product((-1, 0, 1), repeat=5):
        state = level.initial_state()
        for horizontal in directions:
            state.step(InputFrame(horizontal < 0, horizontal > 0, False, None), level.tiles)
        assert lower <= state.player.pos.x <= upper


def test_physics_prune_matches_exact_direction_search_in_open_air() -> None:
    from nv14_engine import InputFrame, parse_level_string

    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(8)]

    exact, exact_result = optimise_local_windows(
        level,
        frames,
        target_frame=7,
        range_start=0,
        range_end=7,
        objective_name="max-x",
        window_size=5,
        passes=1,
        local_inputs="direction",
        physics_prune=False,
        workers=1,
        progress=None,
    )
    pruned, pruned_result = optimise_local_windows(
        level,
        frames,
        target_frame=7,
        range_start=0,
        range_end=7,
        objective_name="max-x",
        window_size=5,
        passes=1,
        local_inputs="direction",
        physics_prune=True,
        workers=3,
        progress=None,
    )

    assert pruned_result.score == exact_result.score
    assert [(f.left, f.right, f.jump) for f in pruned] == [
        (f.left, f.right, f.jump) for f in exact
    ]


def test_local_window_order_forward_and_reverse_are_distinct_traversals() -> None:
    from nv14_engine import InputFrame, parse_level_string

    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(6)]

    forward_logs: list[str] = []
    reverse_logs: list[str] = []
    optimise_local_windows(
        level,
        frames,
        target_frame=5,
        range_start=0,
        range_end=5,
        objective_name="max-x",
        window_size=2,
        passes=1,
        local_inputs="direction",
        window_order="forward",
        progress=forward_logs.append,
    )
    optimise_local_windows(
        level,
        frames,
        target_frame=5,
        range_start=0,
        range_end=5,
        objective_name="max-x",
        window_size=2,
        passes=1,
        local_inputs="direction",
        window_order="reverse",
        progress=reverse_logs.append,
    )

    assert "forward, pass 1: forward window order" in forward_logs
    assert "reverse, pass 1: reverse window order" in reverse_logs


def test_random_window_order_is_reproducible_from_master_seed() -> None:
    from nv14_engine import InputFrame, parse_level_string

    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(8)]

    kwargs = dict(
        target_frame=7,
        range_start=0,
        range_end=7,
        objective_name="max-x",
        window_size=3,
        passes=2,
        local_inputs="direction",
        window_order="random",
        restarts=4,
        seed=123456789,
        progress=None,
    )
    first, first_result = optimise_local_windows(level, frames, **kwargs)
    second, second_result = optimise_local_windows(level, frames, **kwargs)

    assert first_result.score == second_result.score
    assert [(f.left, f.right, f.jump) for f in first] == [
        (f.left, f.right, f.jump) for f in second
    ]


@pytest.mark.parametrize("local_inputs", ("all", "direction"))
def test_random_local_workers_match_serial_trajectory(local_inputs: str) -> None:
    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(12)]
    kwargs = dict(
        target_frame=11,
        range_start=0,
        range_end=11,
        objective_name="max-x",
        window_size=3,
        passes=2,
        local_inputs=local_inputs,
        window_order="random",
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
    assert [(f.left, f.right, f.jump) for f in parallel] == [
        (f.left, f.right, f.jump) for f in serial
    ]


@pytest.mark.parametrize("local_inputs", ("all", "direction"))
def test_forward_local_window_workers_match_serial_trajectory(
    local_inputs: str,
) -> None:
    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(12)]
    kwargs = dict(
        target_frame=11,
        range_start=0,
        range_end=7,
        objective_name="max-x",
        window_size=3,
        passes=2,
        local_inputs=local_inputs,
        window_order="forward",
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
    assert [(f.left, f.right, f.jump) for f in parallel] == [
        (f.left, f.right, f.jump) for f in serial
    ]


@pytest.mark.parametrize("local_inputs", ("all", "direction"))
def test_mixed_workers_pool_forward_reverse_and_random_trajectories(
    local_inputs: str,
) -> None:
    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(10)]
    kwargs = dict(
        target_frame=9,
        range_start=0,
        range_end=9,
        objective_name="max-x",
        window_size=3,
        passes=1,
        local_inputs=local_inputs,
        window_order="mixed",
        restarts=1,
        seed=97531,
    )

    serial, serial_result = optimise_local_windows(
        level, frames, workers=1, progress=None, **kwargs
    )
    logs: list[str] = []
    parallel, parallel_result = optimise_local_windows(
        level, frames, workers=3, progress=logs.append, **kwargs
    )

    assert any(
        "local search: 3 worker processes, 3 independent trajectories" in line
        for line in logs
    )
    assert parallel_result.score == serial_result.score
    assert parallel_result.state.state_key() == serial_result.state.state_key()
    assert [(f.left, f.right, f.jump) for f in parallel] == [
        (f.left, f.right, f.jump) for f in serial
    ]


def test_parallel_local_progress_reports_only_global_best_improvements_and_finishes() -> None:
    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(10)]
    logs: list[str] = []

    optimise_local_windows(
        level,
        frames,
        target_frame=9,
        range_start=0,
        range_end=9,
        objective_name="max-x",
        window_size=3,
        passes=1,
        local_inputs="direction",
        window_order="mixed",
        restarts=1,
        seed=97531,
        workers=3,
        progress=logs.append,
    )

    worker_prefixes = ("mixed forward", "mixed reverse", "random restart ")
    worker_logs = [line for line in logs if line.startswith(worker_prefixes)]
    assert worker_logs
    assert all(" -> " in line and "position=(" in line for line in worker_logs)
    assert all(line.endswith("[NEW BEST SO FAR]") for line in worker_logs)
    assert not any(" search:" in line for line in worker_logs)
    assert not any(" baseline:" in line for line in worker_logs)

    finished = [line for line in logs if line.startswith("finished ")]
    assert len(finished) == 3
    assert all(": best score=" in line for line in finished)
    assert any(line.startswith("finished mixed forward:") for line in finished)
    assert any(line.startswith("finished mixed reverse:") for line in finished)
    assert any(line.startswith("finished random restart 1/1 ") for line in finished)


def test_parallel_local_progress_marks_new_best_so_far() -> None:
    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(10)]
    logs: list[str] = []

    _optimised, result = optimise_local_windows(
        level,
        frames,
        target_frame=9,
        range_start=0,
        range_end=9,
        objective_name="max-x",
        window_size=3,
        passes=1,
        local_inputs="direction",
        window_order="mixed",
        restarts=1,
        seed=97531,
        workers=3,
        progress=logs.append,
    )

    best_lines = [line for line in logs if line.endswith("[NEW BEST SO FAR]")]
    assert best_lines
    best_scores = [
        float(line.split(" -> ", 1)[1].split(";", 1)[0])
        for line in best_lines
    ]
    assert best_scores == sorted(set(best_scores))
    assert best_scores[-1] == pytest.approx(result.score)


@pytest.mark.parametrize("workers", (1, 3))
def test_local_best_run_callback_tracks_live_restart_bests(workers: int) -> None:
    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(20)]
    checkpoints: list[tuple[str, float]] = []

    _optimised, result = optimise_local_windows(
        level,
        frames,
        target_frame=19,
        range_start=0,
        range_end=19,
        objective_name="max-x",
        window_size=1,
        passes=1,
        local_inputs="direction",
        window_order="random",
        window_shape="sparse",
        windows_per_pass=1,
        restarts=5,
        seed=1,
        workers=workers,
        progress=None,
        best_run_callback=lambda run: checkpoints.append(
            (run.label, run.evaluation.score)
        ),
    )

    assert checkpoints
    assert all("random restart" in label for label, _score in checkpoints)
    checkpoint_scores = [score for _label, score in checkpoints]
    assert checkpoint_scores == sorted(set(checkpoint_scores))
    assert checkpoint_scores[-1] == result.score


@pytest.mark.parametrize(
    ("workers", "window_order"),
    ((1, "forward"), (3, "mixed")),
)
def test_local_best_run_callback_receives_immutable_mid_run_snapshots(
    workers: int,
    window_order: str,
) -> None:
    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(10)]
    checkpoints = []

    _optimised, result = optimise_local_windows(
        level,
        frames,
        target_frame=9,
        range_start=0,
        range_end=9,
        objective_name="max-x",
        window_size=1,
        passes=1,
        local_inputs="direction",
        window_order=window_order,
        restarts=1,
        seed=266,
        workers=workers,
        # Multi-worker checkpoint streaming must remain active even when the
        # caller has disabled stdout progress.
        progress=None,
        best_run_callback=lambda run: checkpoints.append(run),
    )

    assert len(checkpoints) > 1
    checkpoint_scores = [run.evaluation.score for run in checkpoints]
    assert checkpoint_scores == sorted(set(checkpoint_scores))
    assert checkpoint_scores[0] < result.score
    assert checkpoint_scores[-1] == result.score

    objective = objective_function("max-x")
    for checkpoint in checkpoints:
        clean = evaluate(level, checkpoint.frames, 9, objective)
        assert clean.score == checkpoint.evaluation.score
        assert clean.state.state_key() == checkpoint.evaluation.state.state_key()


def test_random_restarts_each_begin_from_original_replay() -> None:
    from nv14_engine import InputFrame, parse_level_string

    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
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
        passes=1,
        local_inputs="direction",
        window_order="random",
        restarts=3,
        seed=42,
        progress=logs.append,
    )

    restart_baselines = [
        line for line in logs if line.startswith("random restart ") and " baseline:" in line
    ]
    assert len(restart_baselines) == 3
    baseline_scores = [line.split("score=", 1)[1].split(",", 1)[0] for line in restart_baselines]
    assert len(set(baseline_scores)) == 1


def test_mixed_window_order_is_at_least_as_good_as_component_runs() -> None:
    from nv14_engine import InputFrame, parse_level_string

    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(7)]
    common = dict(
        target_frame=6,
        range_start=0,
        range_end=6,
        objective_name="max-x",
        window_size=2,
        passes=2,
        local_inputs="direction",
        progress=None,
    )

    _forward, forward_eval = optimise_local_windows(
        level, frames, window_order="forward", **common
    )
    _reverse, reverse_eval = optimise_local_windows(
        level, frames, window_order="reverse", **common
    )
    _random, random_eval = optimise_local_windows(
        level,
        frames,
        window_order="random",
        restarts=3,
        seed=99,
        **common,
    )
    _mixed, mixed_eval = optimise_local_windows(
        level,
        frames,
        window_order="mixed",
        restarts=3,
        seed=99,
        **common,
    )

    assert mixed_eval.score >= forward_eval.score
    assert mixed_eval.score >= reverse_eval.score
    assert mixed_eval.score >= random_eval.score

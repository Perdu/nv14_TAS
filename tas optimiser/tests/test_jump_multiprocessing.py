from pathlib import Path

import pytest

from nv14_engine import parse_level_string
from nv14_replay import decode_complex_replay, parse_combined_level_replay
from optimize_replay import optimise_jump_patterns, parse_worker_count


HERE = Path(__file__).parent


def load_record(name: str, *, simulate_enemies: bool = False):
    combined = parse_combined_level_replay(
        (HERE / name).read_text(encoding="utf-8")
    )
    return (
        decode_complex_replay(combined.replay_string),
        parse_level_string(
            combined.level_string, simulate_enemies=simulate_enemies
        ),
    )


def result_signature(results):
    return sorted(
        (
            result.score,
            tuple(
                (pulse.start_frame, pulse.hold_length)
                for pulse in result.pulses
            ),
            result.evaluation.state.state_key(),
        )
        for result in results
    )


def test_worker_count_parser() -> None:
    assert parse_worker_count("auto") == 0
    assert parse_worker_count("AUTO") == 0
    assert parse_worker_count("1") == 1
    assert parse_worker_count("8") == 8
    with pytest.raises(ValueError):
        parse_worker_count("0")
    with pytest.raises(ValueError):
        parse_worker_count("many")


def test_parallel_jump_search_matches_serial_terminal_set() -> None:
    replay, level = load_record("example_motherlode.txt")
    kwargs = dict(
        target_frame=71,
        range_start=0,
        range_end=71,
        objective_name="max-x",
        jump_count_min=2,
        jump_count_max=3,
        jump_length_min=1,
        jump_length_max=10,
        top_results=10,
    )
    serial = optimise_jump_patterns(
        level, replay.frames, workers=1, progress=None, **kwargs
    )
    logs: list[str] = []
    parallel = optimise_jump_patterns(
        level, replay.frames, workers=2, progress=logs.append, **kwargs
    )

    assert result_signature(parallel) == result_signature(serial)
    assert any("2 worker processes" in line for line in logs)


def test_fixed_first_jump_can_split_at_second_pulse() -> None:
    replay, level = load_record("example_ditched_supplied.txt")
    kwargs = dict(
        target_frame=135,
        range_start=106,
        range_end=135,
        objective_name="min-x",
        jump_count_min=2,
        jump_count_max=2,
        jump_length_min=1,
        jump_length_max=2,
        fixed_jump_frames=(112,),
        top_results=4,
    )
    serial = optimise_jump_patterns(
        level, replay.frames, workers=1, progress=None, **kwargs
    )
    logs: list[str] = []
    parallel = optimise_jump_patterns(
        level, replay.frames, workers=4, progress=logs.append, **kwargs
    )

    assert result_signature(parallel) == result_signature(serial)
    assert any("worker processes" in line for line in logs)


def test_enemy_enabled_parallel_winner_matches_serial() -> None:
    replay, level = load_record("example_44_0.txt", simulate_enemies=True)
    kwargs = dict(
        target_frame=100,
        range_start=0,
        range_end=30,
        objective_name="max-x",
        jump_count_min=1,
        jump_count_max=2,
        jump_length_min=1,
        jump_length_max=4,
        top_results=5,
    )
    serial = optimise_jump_patterns(
        level, replay.frames, workers=1, progress=None, **kwargs
    )
    parallel = optimise_jump_patterns(
        level, replay.frames, workers=2, progress=None, **kwargs
    )

    assert serial and parallel
    assert parallel[0].score == serial[0].score
    assert parallel[0].pulses == serial[0].pulses
    assert (
        parallel[0].evaluation.state.state_key()
        == serial[0].evaluation.state.state_key()
    )


def test_negative_worker_count_is_rejected() -> None:
    replay, level = load_record("example_motherlode.txt")
    with pytest.raises(ValueError, match="workers"):
        optimise_jump_patterns(
            level,
            replay.frames,
            target_frame=10,
            range_start=0,
            range_end=10,
            objective_name="max-x",
            workers=-1,
            progress=None,
        )

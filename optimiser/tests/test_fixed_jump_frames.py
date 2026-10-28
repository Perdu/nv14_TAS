from pathlib import Path

import pytest

from nv14_engine import parse_level_string
from nv14_replay import decode_complex_replay, parse_combined_level_replay
from optimize_replay import optimise_jump_patterns, parse_frame_list


HERE = Path(__file__).parent
SUPPLIED = HERE / "example_ditched_supplied.txt"


def load_record(path: Path):
    combined = parse_combined_level_replay(path.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string)
    return replay, level


def test_fixed_jump_frame_parser() -> None:
    assert parse_frame_list("35,108,157") == (35, 108, 157)
    assert parse_frame_list(" 35, 108 ") == (35, 108)
    with pytest.raises(ValueError):
        parse_frame_list("35,,108")
    with pytest.raises(ValueError):
        parse_frame_list("35,35")


def test_jump_pattern_fixed_frame_locks_start() -> None:
    replay, level = load_record(SUPPLIED)
    results = optimise_jump_patterns(
        level,
        replay.frames,
        target_frame=123,
        range_start=106,
        range_end=123,
        objective_name="min-x",
        jump_count_min=1,
        jump_count_max=1,
        jump_length_min=1,
        jump_length_max=6,
        fixed_jump_frames=(112,),
        top_results=6,
        progress=None,
    )

    assert results
    assert all(
        len(result.pulses) == 1 and result.pulses[0].start_frame == 112
        for result in results
    )
    assert all(1 <= result.pulses[0].hold_length <= 6 for result in results)


def test_jump_pattern_fixed_frame_must_be_source_rising_edge() -> None:
    replay, level = load_record(SUPPLIED)
    with pytest.raises(ValueError, match="111"):
        optimise_jump_patterns(
            level,
            replay.frames,
            target_frame=123,
            range_start=106,
            range_end=123,
            objective_name="min-x",
            jump_count_min=1,
            jump_count_max=1,
            fixed_jump_frames=(111,),
            progress=None,
        )

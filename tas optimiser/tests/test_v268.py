from __future__ import annotations

import random
from pathlib import Path

import pytest

import nv14_local
import optimize_replay as opt
from nv14_engine import InputFrame, parse_level_string


def _open_air_level():
    return parse_level_string("0" * (31 * 23) + "|5^100,100")


def _frame_bits(frames):
    return [(frame.left, frame.right, frame.jump) for frame in frames]


def test_frame_range_parser_accepts_lists_commas_and_coalesces() -> None:
    assert opt.parse_frame_ranges(
        ["250:280", "90:105", "100:110", "281"],
        target_frame=300,
    ) == ((90, 110), (250, 281))
    assert opt.parse_frame_ranges("90:105,250:280", target_frame=300) == (
        (90, 105),
        (250, 280),
    )


def test_local_toml_accepts_disparate_range_array(tmp_path: Path) -> None:
    config = tmp_path / "ranges.toml"
    config.write_text(
        """
[local]
target_frame = 300
range = ["90:105", "250:280"]
""",
        encoding="utf-8",
    )

    args = opt.parse_arguments(["local", "input.txt", "--config", str(config)])

    assert args.frame_range == ("90:105", "250:280")
    assert args._mode_configs.local is not None
    assert args._mode_configs.local.frame_range == (
        "90:105",
        "250:280",
    )

    overridden = opt.parse_arguments(
        [
            "local",
            "input.txt",
            "--config",
            str(config),
            "--range",
            "0:20",
        ]
    )
    assert overridden.frame_range == "0:20"


@pytest.mark.parametrize("mode", ("auto", "jump-pattern"))
def test_disparate_ranges_are_rejected_outside_local_mode(mode: str) -> None:
    with pytest.raises(
        SystemExit,
        match="multiple optimisation ranges are only supported by local mode",
    ):
        opt.parse_arguments([mode, "input.txt", "--range", "90:105,250:280"])


def test_contiguous_windows_do_not_bridge_excluded_gaps() -> None:
    windows = nv14_local._contiguous_local_windows_for_ranges(((0, 2), (7, 9)), 2)
    assert [window.frames for window in windows] == [
        (0, 1),
        (1, 2),
        (7, 8),
        (8, 9),
    ]


def test_sparse_windows_sample_the_union_and_respect_real_frame_span() -> None:
    ranges = ((0, 1), (8, 9))
    unrestricted = nv14_local._sample_sparse_local_windows_for_ranges(
        ranges,
        2,
        window_span=None,
        windows_per_pass=99,
        rng=random.Random(268),
    )
    limited = nv14_local._sample_sparse_local_windows_for_ranges(
        ranges,
        2,
        window_span=2,
        windows_per_pass=99,
        rng=random.Random(268),
    )

    assert len(unrestricted) == 6
    assert any(window.start <= 1 and window.end >= 8 for window in unrestricted)
    assert {window.frames for window in limited} == {(0, 1), (8, 9)}


def test_local_search_changes_only_frames_in_disparate_ranges() -> None:
    level = _open_air_level()
    source = [InputFrame() for _ in range(10)]
    baseline = opt.evaluate(level, source, 9, opt.objective_function("max-x"))

    optimised, result = opt.optimise_local_windows(
        level,
        source,
        target_frame=9,
        range_start=0,
        range_end=9,
        frame_ranges=((0, 1), (8, 9)),
        objective_name="max-x",
        window_size=1,
        passes=1,
        local_inputs="direction",
        workers=1,
        progress=None,
    )

    changed = {
        index
        for index, (before, after) in enumerate(
            zip(_frame_bits(source), _frame_bits(optimised), strict=True)
        )
        if before != after
    }
    assert changed
    assert changed <= {0, 1, 8, 9}
    assert changed & {0, 1}
    assert changed & {8, 9}
    assert result.score > baseline.score


def test_jump_restarts_leave_gap_pulses_immutable() -> None:
    source = [
        InputFrame(False, False, index in {1, 2, 5, 6, 9, 10}, None)
        for index in range(12)
    ]
    permitted = {0, 1, 2, 3, 8, 9, 10, 11}

    for seed in range(20):
        mutated, changes = nv14_local._mutate_jump_inputs_in_ranges(
            source,
            frame_ranges=((0, 3), (8, 11)),
            start_mutation=1,
            length_mutation=1,
            rng=random.Random(seed),
            immutable_jumps=(),
        )
        changed_jump_frames = {
            index
            for index, (before, after) in enumerate(zip(source, mutated, strict=True))
            if before.jump != after.jump
        }
        assert changed_jump_frames <= permitted
        assert [source_pulse.start_frame for source_pulse, _ in changes] == [1, 9]
        assert [frame.jump for frame in mutated[4:8]] == [
            frame.jump for frame in source[4:8]
        ]


def test_single_range_search_retains_legacy_result_with_explicit_range_list() -> None:
    level = _open_air_level()
    source = [InputFrame() for _ in range(8)]
    kwargs = {
        "target_frame": 7,
        "range_start": 1,
        "range_end": 6,
        "objective_name": "max-x",
        "window_size": 2,
        "passes": 2,
        "local_inputs": "direction",
        "window_order": "random",
        "restarts": 2,
        "seed": 268268,
        "workers": 1,
        "progress": None,
    }

    legacy, legacy_result = opt.optimise_local_windows(level, source, **kwargs)
    listed, listed_result = opt.optimise_local_windows(
        level, source, frame_ranges=((1, 6),), **kwargs
    )

    assert listed_result.score == legacy_result.score
    assert listed_result.state.state_key() == legacy_result.state.state_key()
    assert _frame_bits(listed) == _frame_bits(legacy)

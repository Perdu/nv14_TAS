from __future__ import annotations

import sys

import pytest

import nv14_auto as auto
import optimize_replay as opt
from nv14_auto import AutoConfig, NEUTRAL_INPUT, optimise_autonomous
from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    parse_level_string,
)
from nv14_replay import (
    RetimeMutation,
    apply_single_transition_retime,
    editable_frames,
    input_transition_frames,
)


def _floor_level():
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    return parse_level_string(
        f"{''.join(chars)}|5^60,134!11^140,134,60,134"
    )


def _held(frames):
    return tuple((frame.left, frame.right, frame.jump) for frame in frames)


def test_single_boundary_retime_keeps_later_transitions_fixed() -> None:
    neutral = InputFrame()
    right = InputFrame(right=True)
    left = InputFrame(left=True)
    frames = [neutral, neutral, right, right, left, left, neutral]

    earlier = apply_single_transition_retime(frames, RetimeMutation(2, -1))
    later = apply_single_transition_retime(frames, RetimeMutation(4, +1))

    assert input_transition_frames(earlier) == (1, 4, 6)
    assert input_transition_frames(later) == (2, 5, 6)


def test_semantic_jump_lattice_proposes_length_31_both_ways() -> None:
    short = tuple(InputFrame(jump=index < 19) for index in range(40)) + (
        NEUTRAL_INPUT,
    )
    long = tuple(InputFrame(jump=index < 40) for index in range(45)) + (
        NEUTRAL_INPUT,
    )
    config = AutoConfig(
        iterations=0,
        max_jump_shift=0,
        max_jump_hold_delta=0,
    )

    short_variants = auto._semantic_jump_variants(short, config)
    long_variants = auto._semantic_jump_variants(long, config)

    assert any(description.endswith("19->31") for _, description in short_variants)
    assert any(description.endswith("40->31") for _, description in long_variants)


def test_compact_replay_key_distinguishes_channels_and_lengths() -> None:
    neutral = (InputFrame(),)
    assert auto._frame_key(neutral) != auto._frame_key((InputFrame(left=True),))
    assert auto._frame_key(neutral) != auto._frame_key((InputFrame(jump=True),))
    assert auto._frame_key(neutral) != auto._frame_key(neutral * 2)


def test_auto_range_rejects_frames_beyond_trimmed_source() -> None:
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    with pytest.raises(ValueError, match="verified replay body"):
        optimise_autonomous(
            _floor_level(),
            source,
            AutoConfig(iterations=0, range_start=34, range_end=34),
        )


def test_zero_jump_bounds_do_not_manufacture_plus_one_beam_mutation() -> None:
    source = [InputFrame(right=True, jump=index < 3) for index in range(80)]
    result = optimise_autonomous(
        _floor_level(),
        source,
        AutoConfig(
            iterations=40,
            beam_width=8,
            max_retime=1,
            cheap_pulse_limit=0,
            max_jump_shift=0,
            max_jump_hold_delta=0,
        ),
    )

    descriptions = tuple(
        mutation
        for candidate in result.beam
        for mutation in candidate.mutations
    )
    assert not any("start +0 hold +1" in item for item in descriptions)


def test_integrated_v28_cli_aliases_are_accepted() -> None:
    args = opt.build_parser().parse_args(
        [
            "auto", "run.txt",
            "--auto-window",
            "4",
            "--auto-alignment",
            "5",
            "--auto-lookahead",
            "12",
            "--auto-match-tolerance",
            "0.25",
        ]
    )
    assert args.auto_repair_window == 4
    assert args.auto_max_alignment == 5
    assert args.auto_lookahead == 12
    assert args.auto_match_tolerance == 0.25


def test_single_frame_range_and_output_aliases_are_checked() -> None:
    assert opt.parse_frame_range("5", target_frame=9) == (5, 5)
    with pytest.raises(ValueError, match="between 0"):
        opt.parse_frame_range("10", target_frame=9)
    with pytest.raises(ValueError, match="different files"):
        opt._validate_output_paths(
            opt.Path("run.txt"), opt.Path("run.txt"), None
        )
    with pytest.raises(ValueError, match="different files"):
        opt._validate_output_paths(
            opt.Path("run.txt"), opt.Path("out.txt"), opt.Path("out.txt")
        )


def test_boundary_retime_rejects_transition_collisions() -> None:
    frames = [
        InputFrame(right=True),
        InputFrame(left=True),
        InputFrame(),
    ]
    with pytest.raises(ValueError, match="preceding"):
        apply_single_transition_retime(frames, RetimeMutation(1, -1))
    with pytest.raises(ValueError, match="following"):
        apply_single_transition_retime(frames, RetimeMutation(1, +1))


def test_frame_key_matches_held_inputs_after_editable_conversion() -> None:
    frames = [
        InputFrame(right=True, jump_trigger=True),
        InputFrame(jump=True, jump_trigger=False),
    ]
    editable = editable_frames(frames)

    assert _held(editable) == ((False, True, False), (False, False, True))
    assert auto._frame_key(tuple(editable)) == auto._frame_key(tuple(frames))


def test_jump_interval_and_semantic_delete_preserve_horizontal_channel() -> None:
    working = tuple(
        InputFrame(left=tick % 2 == 0, right=tick % 2 == 1, jump=2 <= tick <= 4)
        for tick in range(8)
    ) + (NEUTRAL_INPUT,)

    deleted = auto.mutate_jump_interval(working, 2, 3, held=False)
    inserted = auto.mutate_jump_interval(deleted, 5, 2, held=True)
    variants = auto._semantic_jump_variants(
        working,
        AutoConfig(iterations=0, max_jump_shift=0, max_jump_hold_delta=0),
    )

    assert [frame.horizontal for frame in deleted] == [
        frame.horizontal for frame in working
    ]
    assert [frame.horizontal for frame in inserted] == [
        frame.horizontal for frame in working
    ]
    assert not any(frame.jump for frame in deleted[:-1])
    assert all(inserted[tick].jump for tick in (5, 6))
    assert any(" delete " in description for _, description in variants)


def test_reference_suffix_splice_accepts_different_epoch_lengths() -> None:
    candidate = (
        InputFrame(left=True),
        InputFrame(right=True),
        InputFrame(jump=True),
        InputFrame(left=True),
        InputFrame(right=True),
        NEUTRAL_INPUT,
    )
    reference = (
        InputFrame(right=True),
        InputFrame(jump=True),
        InputFrame(left=True),
        InputFrame(right=True, jump=True),
        NEUTRAL_INPUT,
    )
    match = auto.AlignmentMatch(
        candidate_tick=1,
        reference_tick=2,
        offset=1,
        distance=0.0,
        contact_matches=True,
        static_matches=True,
    )

    spliced = auto.apply_reference_suffix_splice(candidate, reference, match)

    assert spliced == (
        candidate[:2]
        + reference[3:4]
        + (NEUTRAL_INPUT,) * 3
    )


def test_zero_tick_neutral_completion_returns_empty_replay() -> None:
    level = parse_level_string(
        "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
        + "|5^110,100!11^120,100,110,100"
    )

    result = optimise_autonomous(
        level,
        [InputFrame(right=True)],
        AutoConfig(iterations=10),
    )

    assert result.baseline_finish_tick == 0
    assert result.finish_tick == 0
    assert result.frames == ()
    assert result.stats.macro_evaluations == 0


def test_auto_cli_round_trips_tick_zero_replay(tmp_path, monkeypatch) -> None:
    level_string = (
        "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
        + "|5^110,100!11^120,100,110,100"
    )
    source_path = tmp_path / "tick-zero.txt"
    output_path = tmp_path / "tick-zero-optimized.txt"
    source_path.write_text(
        f"$Tick zero#tests##{level_string}#0:#\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto", str(source_path),
            "--iterations",
            "0",
            "--output",
            str(output_path),
        ],
    )

    opt.main()

    combined = opt.parse_combined_level_replay(
        output_path.read_text(encoding="utf-8")
    )
    assert combined.replay_string == "0:"


def test_small_budget_is_not_consumed_entirely_by_initial_retimes() -> None:
    source = [InputFrame(right=tick % 2 == 0) for tick in range(100)]

    result = optimise_autonomous(
        _floor_level(),
        source,
        AutoConfig(
            iterations=5,
            beam_width=4,
            seed=0,
            cheap_pulse_limit=0,
        ),
    )

    assert result.stats.raw_retimes < result.stats.macro_evaluations
    assert result.stats.jump_mutations + result.stats.pulse_mutations > 0


def test_all_input_repair_cannot_reuse_an_unrelated_successful_jump() -> None:
    level = _floor_level()
    seed = (
        InputFrame(jump=True),
        InputFrame(),
        InputFrame(jump=True),
        InputFrame(),
        InputFrame(),
        InputFrame(),
        NEUTRAL_INPUT,
    )
    reference = (
        InputFrame(right=True, jump=True),
        InputFrame(),
        InputFrame(jump=True),
        InputFrame(),
        InputFrame(),
        InputFrame(),
        NEUTRAL_INPUT,
    )
    seed_evaluation = auto._evaluate_working(level, seed)
    reference_evaluation = auto._evaluate_working(level, reference)
    config = AutoConfig(
        iterations=1,
        repair_window=4,
        repair_lookahead=4,
        max_jump_shift=2,
        range_start=0,
        range_end=5,
    )

    repaired, _, _ = auto.repair_all_input_window(
        level,
        seed,
        reference_evaluation,
        seed_evaluation=seed_evaluation,
        failure_tick=2,
        reference_offset=0,
        config=config,
    )

    assert seed_evaluation.successful_jumps == (0,)
    assert seed_evaluation.missed_jump_edges == (2,)
    assert repaired is None


def test_all_input_repair_accepts_a_new_shifted_successful_jump() -> None:
    level = _floor_level()
    neutral = InputFrame()
    jump = InputFrame(jump=True)
    seed = tuple(
        [jump] + [neutral] * 38 + [jump, jump] + [neutral] * 4
    ) + (NEUTRAL_INPUT,)
    reference = tuple(
        [jump] + [neutral] * 39 + [jump] + [neutral] * 4
    ) + (NEUTRAL_INPUT,)
    seed_evaluation = auto._evaluate_working(level, seed)
    reference_evaluation = auto._evaluate_working(level, reference)
    config = AutoConfig(
        iterations=1,
        repair_window=4,
        repair_lookahead=4,
        max_jump_shift=2,
        range_start=0,
        range_end=44,
    )

    repaired, _, _ = auto.repair_all_input_window(
        level,
        seed,
        reference_evaluation,
        seed_evaluation=seed_evaluation,
        failure_tick=39,
        reference_offset=0,
        config=config,
    )

    assert seed_evaluation.successful_jumps == (0,)
    assert seed_evaluation.missed_jump_edges == (39,)
    assert repaired is not None
    repaired_evaluation = auto._evaluate_working(level, repaired)
    assert not repaired[39].jump and repaired[40].jump
    assert set(repaired_evaluation.successful_jumps) - set(
        seed_evaluation.successful_jumps
    ) == {40}


def test_completed_epoch_candidates_are_canonical_and_unaligned() -> None:
    result = optimise_autonomous(
        _floor_level(),
        [InputFrame()] + [InputFrame(right=True)] * 80,
        AutoConfig(
            iterations=4,
            beam_width=8,
            seed=0,
            cheap_pulse_limit=0,
        ),
    )

    assert result.stats.reference_epochs >= 1
    assert len(result.best.working_frames) == result.best.finish_tick + 1
    assert result.best.alignment is None
    assert all(
        len(candidate.working_frames) == candidate.finish_tick + 1
        for candidate in result.beam
        if candidate.output_valid and candidate.finish_tick is not None
    )

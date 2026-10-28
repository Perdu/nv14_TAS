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


def test_beam_jump_insertion_groups_safe_native_opportunities_by_window() -> None:
    body = tuple(
        InputFrame(jump=tick in (0, 5))
        for tick in range(10)
    )

    windows = auto._jump_insertion_opportunity_windows(
        body,
        ((0, 9),),
        range_start=0,
        range_end=9,
    )

    # Tick 1 would extend the pulse at 0.  Tick 4 leaves no room for both a new
    # trigger and a released separator before the pulse at 5.  Other starts
    # can now sample holds reaching the next pulse; collision policy resolves
    # those after length selection.
    assert windows == (
        ((2, 8), (3, 7)),
        ((7, 3), (8, 2), (9, 1)),
    )
    changed = auto._mutate_jump_interval_known(
        body,
        start=2,
        length=2,
        held=True,
    )
    assert changed[2].jump and changed[3].jump
    assert not changed[4].jump
    assert changed[5].jump
    assert changed[-1] == NEUTRAL_INPUT


def test_beam_jump_retrigger_groups_callable_held_targets_and_honours_range() -> None:
    body = tuple(
        InputFrame(jump=tick <= 5 or tick >= 7)
        for tick in range(10)
    )

    windows = auto._held_jump_retrigger_opportunity_windows(
        body,
        ((0, 9),),
        range_start=0,
        range_end=9,
    )

    # Natural pulse starts at 0 and 7 already have a released predecessor (or
    # no predecessor).  Every later held target can acquire a fresh derived
    # edge by releasing only its immediately preceding frame.
    assert windows == ((1, 2, 3, 4, 5), (8, 9))
    assert not auto._held_jump_retrigger_opportunity_windows(
        body,
        ((5, 5),),
        range_start=5,
        range_end=5,
    )
    assert auto._held_jump_retrigger_opportunity_windows(
        body,
        ((5, 5),),
        range_start=4,
        range_end=5,
    ) == ((5,),)


def test_beam_jump_retrigger_splits_one_frame_without_replacing_hold() -> None:
    body = tuple(
        InputFrame(right=tick == 2, jump=True, jump_trigger=False)
        for tick in range(6)
    )

    changed = auto._mutate_held_jump_retrigger_known(body, 2)

    assert auto._jump_pulses(changed[:-1]) == ((0, 0), (2, 5))
    assert not changed[1].jump
    assert changed[2] == InputFrame(right=True, jump=True)
    assert changed[3:6] == body[3:6]
    assert changed[-1] == NEUTRAL_INPUT


def test_targeted_jump_selection_samples_retrigger_windows_before_frames() -> None:
    class SequenceRng:
        def __init__(self) -> None:
            self.bounds: list[int] = []
            self.values = iter((1, 1))

        def randrange(self, upper: int) -> int:
            self.bounds.append(upper)
            return next(self.values)

    rng = SequenceRng()
    selected = auto._choose_targeted_jump_opportunity(
        rng,
        (((40, 31),),),
        ((184, 185), (263,)),
    )

    assert selected == ("retrigger", 185, 0)
    assert rng.bounds == [3, 2]


def test_beam_targeted_retrigger_is_reachable_in_an_all_held_range(
    monkeypatch,
) -> None:
    class Analysis:
        def jump_opportunity_windows(self):
            return ((1, 4),)

    class ActionRng:
        def random(self) -> float:
            return 0.20

        def randrange(self, _upper: int) -> int:
            raise AssertionError("all-held retrigger must not fake a release draw")

    class JumpRng:
        def randrange(self, _upper: int) -> int:
            return 0

        def random(self) -> float:
            return 1.0

    monkeypatch.setattr(
        auto,
        "_derive_beam_jump_insertion_rng",
        lambda _seed, _attempt: JumpRng(),
    )
    body = tuple(InputFrame(jump=True) for _ in range(5))
    evaluation = auto.AutoEvaluation(
        finish_tick=None,
        dead_tick=None,
        last_tick=4,
        trace=auto._NativeTraceView(Analysis()),
        successful_jumps=(),
        jump_edges=(0,),
        missed_jump_edges=(0,),
    )
    parent = auto.AutoCandidate(
        working_frames=body + (NEUTRAL_INPUT,),
        evaluation=evaluation,
        origin="fixture",
    )
    search = object.__new__(auto._AutonomousSearch)
    search.config = AutoConfig(iterations=1, seed=7)
    search.range_end = 4
    search.rng = ActionRng()
    search.beam_jump_insertion_attempts = 0
    search.counters = {"jump_mutations": 0}
    considered: list[tuple[tuple[InputFrame, ...], str]] = []

    def consider(working, **kwargs):
        considered.append((tuple(working), kwargs["description"]))
        return None

    search._consider = consider

    assert search._try_beam_jump_mutation(parent)
    assert len(considered) == 1
    changed, description = considered[0]
    assert not changed[0].jump and changed[1].jump
    assert changed[2:5] == body[2:5]
    assert description == "jump pulse retrigger 1 via release 0"
    assert search.beam_jump_insertion_attempts == 1
    assert search.counters["jump_mutations"] == 1


def test_beam_jump_insertion_selects_window_before_frame() -> None:
    class SequenceRng:
        def __init__(self) -> None:
            self.bounds: list[int] = []
            self.values = iter((1, 0))

        def randrange(self, upper: int) -> int:
            self.bounds.append(upper)
            return next(self.values)

    rng = SequenceRng()
    selected = auto._choose_jump_insertion_opportunity(
        rng, (((40, 31),) * 80, ((184, 2), (185, 1)), ((263, 1),))
    )

    assert selected == (184, 2)
    assert rng.bounds == [3, 2]


def test_beam_jump_insertion_uses_all_weighted_hold_lengths() -> None:
    class TicketRng:
        def __init__(self, ticket: int) -> None:
            self.ticket = ticket
            self.bounds: list[int] = []

        def randrange(self, upper: int) -> int:
            self.bounds.append(upper)
            return self.ticket

    tickets = (0, 120, 160, 180, 190, 195, 198)
    observed = tuple(
        auto._choose_jump_insertion_hold_length(TicketRng(ticket), 31)
        for ticket in tickets
    )

    assert observed == (1, 2, 3, 6, 12, 20, 31)
    assert tuple(weight for _length, weight in auto._JUMP_INSERT_HOLD_WEIGHTS) == (
        120,
        40,
        20,
        10,
        5,
        3,
        2,
    )


def test_beam_jump_insertion_collision_split_is_exact() -> None:
    class TicketRng:
        def __init__(self, ticket: int) -> None:
            self.ticket = ticket
            self.bounds: list[int] = []

        def randrange(self, upper: int) -> int:
            self.bounds.append(upper)
            return self.ticket

    body = tuple(
        InputFrame(jump=6 <= tick <= 8)
        for tick in range(12)
    )
    expected = (
        ("stop", 3, ((2, 4), (6, 8))),
        ("stop", 3, ((2, 4), (6, 8))),
        ("merge", 7, ((2, 8),)),
        ("replace", 5, ((2, 6),)),
    )

    for ticket, (expected_outcome, expected_length, expected_pulses) in enumerate(
        expected
    ):
        rng = TicketRng(ticket)
        changed, final_length, outcome = auto._mutate_jump_insertion_known(
            body, 2, 5, rng
        )

        assert outcome == expected_outcome
        assert final_length == expected_length
        assert auto._jump_pulses(changed[:-1]) == expected_pulses
        assert rng.bounds == [4]

    assert auto._JUMP_INSERT_COLLISION_OUTCOMES == (
        "stop", "stop", "merge", "replace"
    )


def test_beam_jump_insertion_merge_is_capped_at_31_frames() -> None:
    class MergeRng:
        def randrange(self, upper: int) -> int:
            assert upper == 4
            return 2

    body = tuple(
        InputFrame(jump=29 <= tick <= 35)
        for tick in range(40)
    )
    changed, final_length, outcome = auto._mutate_jump_insertion_known(
        body, 0, 31, MergeRng()
    )

    assert outcome == "merge"
    assert final_length == 31
    assert auto._jump_pulses(changed[:-1]) == ((0, 30),)


def test_beam_jump_insertion_does_not_randomly_merge_an_adjacent_hold() -> None:
    class NoDrawRng:
        def randrange(self, upper: int) -> int:
            raise AssertionError("adjacency is not an overlapping-pulse collision")

    body = tuple(
        InputFrame(jump=6 <= tick <= 8)
        for tick in range(12)
    )
    changed, final_length, outcome = auto._mutate_jump_insertion_known(
        body, 2, 4, NoDrawRng()
    )

    assert outcome is None
    assert final_length == 3
    assert auto._jump_pulses(changed[:-1]) == ((2, 4), (6, 8))


def test_beam_jump_insertion_can_change_only_the_trigger_direction() -> None:
    original = InputFrame(right=True)

    assert auto._JUMP_INSERT_COMPOUND_DIRECTION_PROBABILITY == 0.10
    assert auto._JUMP_INSERT_TRIGGER_DIRECTIONS == (
        "existing", "neutral", "left", "right"
    )
    assert auto._jump_insertion_trigger_frame(original, "existing") == InputFrame(
        right=True,
        jump=True,
    )
    assert auto._jump_insertion_trigger_frame(original, "neutral") == InputFrame(
        jump=True,
    )
    assert auto._jump_insertion_trigger_frame(original, "left") == InputFrame(
        left=True,
        jump=True,
    )
    assert auto._jump_insertion_trigger_frame(original, "right") == InputFrame(
        right=True,
        jump=True,
    )


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

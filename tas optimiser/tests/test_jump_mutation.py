import random

import pytest

import optimize_replay as opt
from nv14_engine import InputFrame, parse_level_string
from nv14_replay import editable_frames


def open_air_level():
    return parse_level_string("0" * (31 * 23) + "|5^100,100")


def frames_with_pulses(length, pulses):
    frames = [InputFrame() for _ in range(length)]
    for start, hold_length in pulses:
        for frame_index in range(start, start + hold_length):
            frames[frame_index] = InputFrame(jump=True)
    return frames


def jump_bits(frames):
    return [frame.jump for frame in frames]


def test_jump_input_pulses_extracts_contiguous_holds() -> None:
    frames = frames_with_pulses(12, [(1, 2), (5, 1), (9, 3)])
    assert opt.jump_input_pulses(frames) == (
        opt.JumpPulse(1, 2),
        opt.JumpPulse(5, 1),
        opt.JumpPulse(9, 3),
    )


def test_zero_jump_mutation_is_exactly_original() -> None:
    frames = frames_with_pulses(14, [(2, 3), (8, 2)])
    mutated, changes = opt.mutate_jump_inputs(
        frames,
        range_start=0,
        range_end=12,
        start_mutation=0,
        length_mutation=0,
        rng=random.Random(123),
    )
    assert jump_bits(mutated) == jump_bits(frames)
    assert changes == (
        (opt.JumpPulse(2, 3), opt.JumpPulse(2, 3)),
        (opt.JumpPulse(8, 2), opt.JumpPulse(8, 2)),
    )


def test_jump_mutation_is_seeded_bounded_and_preserves_boundaries_and_gaps() -> None:
    # Pulses 2+3 and 15+3 cross the mutation range boundaries and must remain
    # fixed. Only 7+2 and 11+2 are eligible for mutation.
    frames = frames_with_pulses(20, [(2, 3), (7, 2), (11, 2), (15, 3)])
    kwargs = dict(
        range_start=4,
        range_end=15,
        start_mutation=2,
        length_mutation=2,
    )
    first, first_changes = opt.mutate_jump_inputs(
        frames, rng=random.Random(20260810), **kwargs
    )
    second, second_changes = opt.mutate_jump_inputs(
        frames, rng=random.Random(20260810), **kwargs
    )

    assert jump_bits(first) == jump_bits(second)
    assert first_changes == second_changes
    assert first[4].jump  # left boundary-crossing pulse preserved
    assert first[15].jump  # right boundary-crossing pulse preserved
    assert jump_bits(first)[:4] == jump_bits(frames)[:4]
    assert jump_bits(first)[16:] == jump_bits(frames)[16:]

    for source, mutated in first_changes:
        assert abs(mutated.start_frame - source.start_frame) <= 2
        assert abs(mutated.hold_length - source.hold_length) <= 2
        assert mutated.hold_length >= 1
        assert 4 <= mutated.start_frame <= mutated.end_frame <= 15

    pulses = opt.jump_input_pulses(first)
    assert all(
        right.start_frame - left.end_frame - 1 >= 1
        for left, right in zip(pulses, pulses[1:])
    )


def test_dense_mutation_does_not_merge_with_boundary_crossing_pulse() -> None:
    # The first pulse crosses the left mutation boundary. A valid nearby draw
    # for the next pulse must still leave the configured released gap from it.
    frames = frames_with_pulses(127, [(70, 10), (83, 9), (93, 10), (106, 2)])
    mutated, changes = opt.mutate_jump_inputs(
        frames,
        range_start=79,
        range_end=108,
        start_mutation=4,
        length_mutation=8,
        rng=random.Random(1039),
    )

    pulses = opt.jump_input_pulses(mutated)
    assert all(
        right.start_frame - left.end_frame - 1 >= 1
        for left, right in zip(pulses, pulses[1:])
    )
    assert mutated[79].jump == frames[79].jump
    assert all(
        79 <= replacement.start_frame <= replacement.end_frame <= 108
        for _source, replacement in changes
    )


def test_local_jump_mutation_recomputes_required_frames_and_adds_control(monkeypatch) -> None:
    level = open_air_level()
    original = frames_with_pulses(8, [(2, 2)])
    captured: list[tuple[str, frozenset[int], tuple[bool, ...]]] = []

    # Keep bookkeeping trivial: every requested press is treated as successful.
    monkeypatch.setattr(
        opt,
        "successful_jump_frames",
        lambda _level, frames, target: opt.jump_press_frames(frames, target),
    )

    def fake_mutate(frames, **kwargs):
        mutated = editable_frames(frames)
        mutated[2] = InputFrame(jump=False)
        mutated[3] = InputFrame(jump=True)
        mutated[4] = InputFrame(jump=True)
        return mutated, ((opt.JumpPulse(2, 2), opt.JumpPulse(3, 2)),)

    monkeypatch.setattr(opt, "mutate_jump_inputs", fake_mutate)

    def fake_single_run(level, frames, **kwargs):
        required = kwargs["required_jump_frames"]
        label = kwargs["run_label"]
        captured.append((label, required, tuple(frame.jump for frame in frames)))
        evaluation = opt.evaluate(
            level,
            frames,
            kwargs["target_frame"],
            opt.objective_function(kwargs["objective_name"], kwargs["objective_target"]),
            x_window=kwargs["x_window"],
            y_window=kwargs["y_window"],
        )
        return opt.LocalSearchRunResult(
            editable_frames(frames), evaluation, label, frozenset()
        )

    monkeypatch.setattr(opt, "_optimise_local_single_run", fake_single_run)

    opt.optimise_local_windows(
        level,
        original,
        target_frame=7,
        range_start=0,
        range_end=7,
        objective_name="max-x",
        window_size=2,
        passes=1,
        local_inputs="direction",
        window_order="random",
        restarts=1,
        seed=12345,
        jump_start_mutation=1,
        jump_length_mutation=1,
        progress=None,
    )

    assert len(captured) == 2
    control_label, control_required, control_bits = captured[0]
    mutated_label, mutated_required, mutated_bits = captured[1]
    assert control_label.startswith("unmutated control")
    assert control_required == frozenset({2})
    assert control_bits[2:4] == (True, True)
    assert mutated_label.startswith("random restart 1/1")
    assert mutated_required == frozenset({3})
    assert mutated_bits[2:5] == (False, True, True)


def test_jump_mutation_requires_direction_random_or_mixed() -> None:
    level = open_air_level()
    frames = [InputFrame() for _ in range(4)]
    common = dict(
        target_frame=3,
        range_start=0,
        range_end=3,
        objective_name="max-x",
        window_size=1,
        passes=1,
        jump_start_mutation=1,
        progress=None,
    )

    try:
        opt.optimise_local_windows(level, frames, local_inputs="all", window_order="random", **common)
    except ValueError as exc:
        assert "direction-only" in str(exc)
    else:
        raise AssertionError("expected direction-only validation error")

    try:
        opt.optimise_local_windows(level, frames, local_inputs="direction", window_order="forward", **common)
    except ValueError as exc:
        assert "window-order random or mixed" in str(exc)
    else:
        raise AssertionError("expected random/mixed validation error")


def test_immutable_jump_bare_both_preserves_start_and_hold_length() -> None:
    frames = frames_with_pulses(40, [(5, 2), (15, 3), (28, 2)])
    for seed in range(20):
        mutated, changes = opt.mutate_jump_inputs(
            frames,
            range_start=0,
            range_end=39,
            start_mutation=3,
            length_mutation=2,
            immutable_jumps=(opt.ImmutableJumpSpec(15),),
            rng=random.Random(seed),
        )
        by_start = {source.start_frame: new for source, new in changes}
        assert by_start[15] == opt.JumpPulse(15, 3)
        assert opt.jump_input_pulses(mutated)[1] == opt.JumpPulse(15, 3)


def test_immutable_jump_still_consumes_rng_draws_for_later_pulses() -> None:
    # These pulses are far enough apart that the first whole-pattern draw is
    # always structurally valid. Freezing the middle pulse should therefore
    # leave the random draws assigned to the first/last pulses unchanged.
    frames = frames_with_pulses(70, [(10, 2), (30, 2), (50, 2)])
    kwargs = dict(
        range_start=0,
        range_end=69,
        start_mutation=1,
        length_mutation=0,
    )
    _, ordinary_changes = opt.mutate_jump_inputs(
        frames, rng=random.Random(24680), **kwargs
    )
    _, immutable_changes = opt.mutate_jump_inputs(
        frames,
        rng=random.Random(24680),
        immutable_jumps=(opt.ImmutableJumpSpec(30),),
        **kwargs,
    )

    ordinary = {source.start_frame: new for source, new in ordinary_changes}
    immutable = {source.start_frame: new for source, new in immutable_changes}
    assert immutable[10] == ordinary[10]
    assert immutable[50] == ordinary[50]
    assert immutable[30] == opt.JumpPulse(30, 2)


def test_immutable_jumps_validate_source_starts_and_range() -> None:
    frames = frames_with_pulses(20, [(4, 3), (12, 4)])

    # A pulse starting within the range but crossing its right boundary is
    # already fixed by the mutator; explicitly naming it is harmless.
    mutated, changes = opt.mutate_jump_inputs(
        frames,
        range_start=4,
        range_end=13,
        start_mutation=2,
        length_mutation=2,
        immutable_jumps=(opt.ImmutableJumpSpec(12),),
        rng=random.Random(123),
    )
    assert jump_bits(mutated)[12:16] == jump_bits(frames)[12:16]
    assert all(source.start_frame != 12 for source, _ in changes)

    try:
        opt.mutate_jump_inputs(
            frames,
            range_start=4,
            range_end=13,
            start_mutation=1,
            length_mutation=1,
            immutable_jumps=(opt.ImmutableJumpSpec(5),),
            rng=random.Random(1),
        )
    except ValueError as exc:
        assert "not jump starts" in str(exc)
    else:
        raise AssertionError("expected non-jump-start validation error")

    try:
        opt.mutate_jump_inputs(
            frames,
            range_start=4,
            range_end=13,
            start_mutation=1,
            length_mutation=1,
            immutable_jumps=(opt.ImmutableJumpSpec(12), opt.ImmutableJumpSpec(12, True, False)),
            rng=random.Random(1),
        )
    except ValueError as exc:
        assert "duplicates" in str(exc)
    else:
        raise AssertionError("expected duplicate immutable-frame validation error")

    try:
        opt.mutate_jump_inputs(
            frames,
            range_start=4,
            range_end=13,
            start_mutation=1,
            length_mutation=1,
            immutable_jumps=(opt.ImmutableJumpSpec(4), opt.ImmutableJumpSpec(12), opt.ImmutableJumpSpec(18)),
            rng=random.Random(1),
        )
    except ValueError as exc:
        assert "within --range" in str(exc)
    else:
        raise AssertionError("expected outside-range validation error")


def test_local_immutable_jumps_require_enabled_mutation() -> None:
    level = open_air_level()
    frames = frames_with_pulses(8, [(2, 2)])
    try:
        opt.optimise_local_windows(
            level,
            frames,
            target_frame=7,
            range_start=0,
            range_end=7,
            objective_name="max-x",
            window_size=1,
            passes=1,
            local_inputs="direction",
            window_order="random",
            immutable_jumps=(opt.ImmutableJumpSpec(2),),
            progress=None,
        )
    except ValueError as exc:
        assert "requires --jump-start-mutation or --jump-length-mutation" in str(exc)
    else:
        raise AssertionError("expected immutable-jump/mutation validation error")



def test_parse_immutable_jumps_defaults_to_both_and_supports_each_property() -> None:
    specs = opt.parse_immutable_jumps("42,73:start,105:length,131:both")
    assert specs == (
        opt.ImmutableJumpSpec(42, True, True),
        opt.ImmutableJumpSpec(73, True, False),
        opt.ImmutableJumpSpec(105, False, True),
        opt.ImmutableJumpSpec(131, True, True),
    )
    assert [spec.mode for spec in specs] == ["both", "start", "length", "both"]


def test_parse_immutable_jumps_rejects_invalid_property_and_duplicate_frame() -> None:
    for text, expected in (
        ("42:foo", "start, length, or both"),
        ("42:start,42:length", "duplicates"),
        ("42:start:length", "FRAME[:start|length|both]"),
    ):
        try:
            opt.parse_immutable_jumps(text)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"expected immutable-jump parse error for {text!r}")


def test_start_only_immutability_allows_length_mutation() -> None:
    frames = frames_with_pulses(40, [(15, 3)])
    saw_length_change = False
    for seed in range(50):
        _mutated, changes = opt.mutate_jump_inputs(
            frames,
            range_start=0,
            range_end=39,
            start_mutation=3,
            length_mutation=2,
            immutable_jumps=(opt.ImmutableJumpSpec(15, True, False),),
            rng=random.Random(seed),
        )
        source, new = changes[0]
        assert source == opt.JumpPulse(15, 3)
        assert new.start_frame == 15
        if new.hold_length != 3:
            saw_length_change = True
    assert saw_length_change


def test_length_only_immutability_allows_start_mutation() -> None:
    frames = frames_with_pulses(40, [(15, 3)])
    saw_start_change = False
    for seed in range(50):
        _mutated, changes = opt.mutate_jump_inputs(
            frames,
            range_start=0,
            range_end=39,
            start_mutation=3,
            length_mutation=2,
            immutable_jumps=(opt.ImmutableJumpSpec(15, False, True),),
            rng=random.Random(seed),
        )
        source, new = changes[0]
        assert source == opt.JumpPulse(15, 3)
        assert new.hold_length == 3
        if new.start_frame != 15:
            saw_start_change = True
    assert saw_start_change


def test_each_immutability_mode_consumes_both_rng_draws_for_later_pulses() -> None:
    frames = frames_with_pulses(80, [(10, 2), (35, 3), (60, 2)])
    kwargs = dict(
        range_start=0,
        range_end=79,
        start_mutation=1,
        length_mutation=1,
    )
    _, ordinary_changes = opt.mutate_jump_inputs(
        frames, rng=random.Random(13579), **kwargs
    )
    ordinary = {source.start_frame: new for source, new in ordinary_changes}

    for spec in (
        opt.ImmutableJumpSpec(35, True, False),
        opt.ImmutableJumpSpec(35, False, True),
        opt.ImmutableJumpSpec(35, True, True),
    ):
        _, changes = opt.mutate_jump_inputs(
            frames,
            rng=random.Random(13579),
            immutable_jumps=(spec,),
            **kwargs,
        )
        by_start = {source.start_frame: new for source, new in changes}
        assert by_start[10] == ordinary[10]
        assert by_start[60] == ordinary[60]


def test_boundary_crossing_jump_remains_fully_fixed_even_with_partial_spec() -> None:
    frames = frames_with_pulses(20, [(12, 4)])
    for spec in (
        opt.ImmutableJumpSpec(12, True, False),
        opt.ImmutableJumpSpec(12, False, True),
    ):
        mutated, changes = opt.mutate_jump_inputs(
            frames,
            range_start=4,
            range_end=13,
            start_mutation=3,
            length_mutation=3,
            immutable_jumps=(spec,),
            rng=random.Random(99),
        )
        assert jump_bits(mutated) == jump_bits(frames)
        assert changes == ()


def test_cli_uses_immutable_jumps_and_removes_old_flag() -> None:
    parser = opt.build_parser()
    parsed = parser.parse_args([
        "local",
        "input.txt",
        "--immutable-jumps",
        "42,73:start,105:length",
    ])
    assert parsed.immutable_jumps == (
        opt.ImmutableJumpSpec(42, True, True),
        opt.ImmutableJumpSpec(73, True, False),
        opt.ImmutableJumpSpec(105, False, True),
    )
    with pytest.raises(SystemExit):
        parser.parse_args(["local", "input.txt", "--immutable-jump-frames", "42"])

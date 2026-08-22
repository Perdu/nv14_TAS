import pytest

import optimize_replay as opt
from nv14_engine import InputFrame
from nv14_replay import (
    RetimeMutation,
    apply_suffix_retime,
    decode_complex_replay,
    encode_complex_replay,
    input_transition_frames,
    valid_retime_mutations,
)


def frame(symbol: str) -> InputFrame:
    return InputFrame(
        left="L" in symbol,
        right="R" in symbol,
        jump="J" in symbol,
    )


def states(frames):
    return [(f.left, f.right, f.jump) for f in frames]


def test_input_transition_frames_uses_implicit_neutral_before_frame_zero() -> None:
    frames = [frame("."), frame("."), frame("R"), frame("R"), frame("RJ"), frame("R")]
    assert input_transition_frames(frames) == (2, 4, 5)
    assert input_transition_frames([frame("R"), frame("R"), frame(".")]) == (0, 2)


def test_suffix_retime_earlier_moves_all_downstream_transitions_together() -> None:
    # . . R R RJ RJ R R L L . .
    frames = [
        frame("."), frame("."), frame("R"), frame("R"),
        frame("RJ"), frame("RJ"), frame("R"), frame("R"),
        frame("L"), frame("L"), frame("."), frame("."),
    ]
    result = apply_suffix_retime(frames, RetimeMutation(4, -1))
    assert input_transition_frames(result) == (2, 3, 5, 7, 9)
    # The complete downstream timing pattern is unchanged: 4,6,8,10 -> 3,5,7,9.
    assert states(result) == states([
        frame("."), frame("."), frame("R"), frame("RJ"),
        frame("RJ"), frame("R"), frame("R"), frame("L"),
        frame("L"), frame("."), frame("."), frame("."),
    ])


def test_suffix_retime_later_extends_preceding_state_and_keeps_length_fixed() -> None:
    frames = [frame("."), frame("R"), frame("R"), frame("L"), frame("L"), frame("."), frame(".")]
    result = apply_suffix_retime(frames, RetimeMutation(3, +1))
    assert len(result) == len(frames)
    assert input_transition_frames(result) == (1, 4, 6)
    assert states(result) == states([
        frame("."), frame("R"), frame("R"), frame("R"),
        frame("L"), frame("L"), frame("."),
    ])


def test_retime_rejects_collision_before_zero_and_replay_end_loss() -> None:
    frames = [frame("."), frame("R"), frame("L"), frame("L"), frame("."), frame(".")]
    with pytest.raises(ValueError, match="collide"):
        apply_suffix_retime(frames, RetimeMutation(2, -1))

    starts_at_zero = [frame("R"), frame("R"), frame("."), frame(".")]
    with pytest.raises(ValueError, match="before frame 0"):
        apply_suffix_retime(starts_at_zero, RetimeMutation(0, -1))

    late_transition = [frame("."), frame("R"), frame("R"), frame("L")]
    with pytest.raises(ValueError, match="beyond the replay end"):
        apply_suffix_retime(late_transition, RetimeMutation(3, +1))


def test_jump_hold_moves_wholesale_and_trigger_is_regenerated() -> None:
    frames = [frame("."), frame("R"), frame("RJ"), frame("RJ"), frame("R"), frame("L"), frame("L")]
    retimed = apply_suffix_retime(frames, RetimeMutation(2, +1))
    assert [i for i, f in enumerate(retimed) if f.jump] == [3, 4]

    packed = encode_complex_replay(retimed)
    decoded = decode_complex_replay(packed).frames
    assert decoded[3].jump_trigger is True
    assert decoded[4].jump_trigger is False


def test_valid_retime_mutations_only_returns_applicable_offsets() -> None:
    frames = [frame("."), frame("."), frame("R"), frame("R"), frame("L"), frame("L"), frame("."), frame(".")]
    mutations = valid_retime_mutations(frames, max_retime=2)
    assert mutations
    for mutation in mutations:
        apply_suffix_retime(frames, mutation)  # must not raise
    # Transition 4 cannot move -2 because it would collide with transition 2.
    assert RetimeMutation(4, -2) not in mutations


def test_parse_retime_spec() -> None:
    assert opt.parse_retime_spec("120:-1") == (120, -1)
    assert opt.parse_retime_spec("whole:+3") == ("whole", 3)
    with pytest.raises(ValueError, match="DELTA"):
        opt.parse_retime_spec("120:0")
    with pytest.raises(ValueError, match="START"):
        opt.parse_retime_spec("nope:-1")

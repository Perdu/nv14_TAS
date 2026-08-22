from __future__ import annotations

import pytest

import nv14_auto as auto
from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    parse_level_string,
)


def _floor_level(*, exit_x: int = 700):
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    return parse_level_string(
        f"{''.join(chars)}|5^60,134!11^{exit_x},134,60,134"
    )


def _jump_ticks(frames) -> tuple[int, ...]:
    return tuple(index for index, frame in enumerate(frames[:-1]) if frame.jump)


def _changed_jump_ticks(original, changed) -> tuple[int, ...]:
    return tuple(
        index
        for index, (left, right) in enumerate(zip(original, changed))
        if left.jump != right.jump
    )


def test_v244_jump_repair_variants_cover_plus_minus_one_start_and_length() -> None:
    frames = tuple(
        InputFrame(right=index % 2 == 0, jump=3 <= index <= 5)
        for index in range(10)
    ) + (auto.NEUTRAL_INPUT,)
    config = auto.AutoConfig(
        iterations=0,
        repair_window=4,
        repair_lookback=8,
        range_start=0,
        range_end=9,
    )

    variants = auto._jump_repair_variants(
        frames,
        failure_tick=6,
        config=config,
    )
    by_description = {
        description: (changed, first_changed)
        for changed, first_changed, description in variants
    }

    assert set(by_description) == {
        "jump pulse 0 start -1 (3->2)",
        "jump pulse 0 start +1 (3->4)",
        "jump pulse 0 length -1 (3->2)",
        "jump pulse 0 length +1 (3->4)",
    }
    expected_changes = {
        "jump pulse 0 start -1 (3->2)": (2, 5),
        "jump pulse 0 start +1 (3->4)": (3, 6),
        "jump pulse 0 length -1 (3->2)": (5,),
        "jump pulse 0 length +1 (3->4)": (6,),
    }
    for description, (changed, first_changed) in by_description.items():
        assert _changed_jump_ticks(frames, changed) == expected_changes[description]
        assert first_changed == expected_changes[description][0]
        assert tuple(
            (frame.left, frame.right) for frame in changed
        ) == tuple((frame.left, frame.right) for frame in frames)


def test_v244_jump_repair_variants_require_the_relevant_edge_in_lookback_and_range() -> None:
    frames = tuple(
        InputFrame(jump=3 <= index <= 5)
        for index in range(12)
    ) + (auto.NEUTRAL_INPUT,)

    outside = auto._jump_repair_variants(
        frames,
        failure_tick=10,
        config=auto.AutoConfig(
            iterations=0,
            repair_window=3,
            repair_lookback=3,
            range_start=0,
            range_end=11,
        ),
    )
    assert outside == ()

    range_limited = auto._jump_repair_variants(
        frames,
        failure_tick=6,
        config=auto.AutoConfig(
            iterations=0,
            repair_window=4,
            repair_lookback=6,
            range_start=3,
            range_end=6,
        ),
    )
    descriptions = tuple(description for _, _, description in range_limited)
    assert "jump pulse 0 start -1 (3->2)" not in descriptions
    assert set(descriptions) == {
        "jump pulse 0 start +1 (3->4)",
        "jump pulse 0 length -1 (3->2)",
        "jump pulse 0 length +1 (3->4)",
    }


def test_v244_jump_repair_variants_visit_nearest_boundaries_first() -> None:
    frames = tuple(
        InputFrame(jump=index in {1, 4, 5, 8, 9, 10})
        for index in range(14)
    ) + (auto.NEUTRAL_INPUT,)

    variants = auto._jump_repair_variants(
        frames,
        failure_tick=11,
        config=auto.AutoConfig(
            iterations=0,
            repair_window=4,
            repair_lookback=12,
            range_start=0,
            range_end=13,
        ),
    )

    assert tuple(description for _, _, description in variants) == (
        "jump pulse 2 length -1 (3->2)",
        "jump pulse 2 length +1 (3->4)",
        "jump pulse 2 start -1 (8->7)",
        "jump pulse 2 start +1 (8->9)",
        "jump pulse 1 length -1 (2->1)",
        "jump pulse 1 length +1 (2->3)",
        "jump pulse 1 start -1 (4->3)",
        "jump pulse 1 start +1 (4->5)",
        "jump pulse 0 start -1 (1->0)",
        "jump pulse 0 start +1 (1->2)",
        "jump pulse 0 length +1 (1->2)",
    )


@pytest.mark.parametrize(
    ("seed_ticks", "reference_ticks", "failure_tick", "expected_ticks"),
    (
        ((2, 3, 4, 5), (3, 4, 5, 6), 6, (3, 4, 5, 6)),
        ((0, 1, 2, 3), (0, 1, 2, 3, 4), 5, (0, 1, 2, 3, 4)),
    ),
)
def test_v244_jump_lookback_repair_finds_start_and_length_edits(
    seed_ticks: tuple[int, ...],
    reference_ticks: tuple[int, ...],
    failure_tick: int,
    expected_ticks: tuple[int, ...],
) -> None:
    level = _floor_level()
    body_length = 16
    seed = tuple(
        InputFrame(right=index % 3 == 0, jump=index in seed_ticks)
        for index in range(body_length)
    ) + (auto.NEUTRAL_INPUT,)
    reference = tuple(
        InputFrame(right=index % 3 == 0, jump=index in reference_ticks)
        for index in range(body_length)
    ) + (auto.NEUTRAL_INPUT,)
    reference_evaluation = auto._evaluate_working(level, reference)

    repaired, branches, simulations = auto.repair_jump_mutation_lookback(
        level,
        seed,
        reference_evaluation,
        failure_tick=failure_tick,
        reference_offset=0,
        config=auto.AutoConfig(
            iterations=1,
            repair_window=4,
            repair_lookback=10,
            repair_lookahead=5,
            repair_local_limit=1_000,
            range_start=0,
            range_end=body_length - 1,
        ),
        require_failure_jump=False,
    )

    assert repaired is not None
    assert branches > 0
    assert simulations > 0
    assert _jump_ticks(repaired) == expected_ticks
    assert tuple(
        (frame.left, frame.right) for frame in repaired
    ) == tuple((frame.left, frame.right) for frame in seed)


def test_v244_primary_repair_order_is_seeded_reproducible_and_independent() -> None:
    assert auto._seeded_primary_repair_order(0, 1) == (
        "jump",
        "direction",
    )
    assert auto._seeded_primary_repair_order(0, 1) == auto._seeded_primary_repair_order(
        0,
        1,
    )
    assert auto._seeded_primary_repair_order(3, 1) == (
        "direction",
        "jump",
    )
    assert auto._seeded_primary_repair_order(0, 2) == (
        "direction",
        "jump",
    )

    direction_rng = auto._derive_repair_search_rng(0, 1, "direction")
    for _ in range(10_000):
        direction_rng.getrandbits(64)
    assert auto._seeded_primary_repair_order(0, 1) == (
        "jump",
        "direction",
    )


def test_v244_auto_runs_seeded_primary_repairs_then_existing_all_input_third(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    level = _floor_level(exit_x=140)
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    calls: list[tuple[str, int]] = []

    def record_jump(*_args, **kwargs):
        calls.append(("jump", kwargs["config"].repair_local_limit))
        return None, 1, 3

    def record_direction(*_args, **kwargs):
        calls.append(("direction", kwargs["config"].repair_local_limit))
        return None, 1, 4

    def record_all_input(*_args, **kwargs):
        calls.append(("all-input", kwargs["config"].repair_local_limit))
        return None, 1, 3

    monkeypatch.setattr(auto, "repair_jump_mutation_lookback", record_jump)
    monkeypatch.setattr(auto, "repair_direction_window", record_direction)
    monkeypatch.setattr(auto, "repair_all_input_window", record_all_input)

    result = auto.optimise_autonomous(
        level,
        source,
        auto.AutoConfig(
            iterations=5,
            beam_width=2,
            seed=0,
            cheap_pulse_limit=0,
            repair_local_limit=10,
            frame_ahead_repair_multiplier=1,
        ),
    )

    assert calls[:3] == [
        ("jump", 10),
        ("direction", 7),
        ("all-input", 3),
    ]
    assert result.stats.repair_attempts == 1
    assert result.stats.jump_repair_attempts == 1
    assert result.stats.all_input_repairs == 1
    assert result.stats.local_simulations == 10

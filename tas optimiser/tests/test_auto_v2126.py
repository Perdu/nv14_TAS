from __future__ import annotations

import random

import nv14_auto as auto
from nv14_auto import AutoConfig
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame, parse_level_string


def test_v2126_repair_rng_streams_are_reproducible_independent_and_beam_safe() -> None:
    def sample(tag: str) -> tuple[int, ...]:
        rng = auto._derive_repair_search_rng(12345, 7, tag)
        return tuple(rng.getrandbits(64) for _ in range(8))

    assert sample("direction") == sample("direction")
    assert sample("direction") != sample("all-input")
    assert tuple(
        auto._derive_repair_search_rng(12345, repair_number, "direction").getrandbits(64)
        for repair_number in (7, 8)
    )[0] != tuple(
        auto._derive_repair_search_rng(12345, repair_number, "direction").getrandbits(64)
        for repair_number in (7, 8)
    )[1]

    direction_rng = auto._derive_repair_search_rng(12345, 7, "direction")
    for _ in range(10_000):
        direction_rng.getrandbits(64)
    fallback_rng = auto._derive_repair_search_rng(12345, 7, "all-input")
    fallback_after_direction_work = tuple(
        fallback_rng.getrandbits(64) for _ in range(4)
    )
    fallback_control_rng = auto._derive_repair_search_rng(
        12345,
        7,
        "all-input",
    )
    fallback_without_direction_work = tuple(
        fallback_control_rng.getrandbits(64) for _ in range(4)
    )
    assert fallback_after_direction_work == fallback_without_direction_work

    expected_beam = random.Random(12345)
    expected = tuple(expected_beam.getrandbits(64) for _ in range(4))
    observed_beam = random.Random(12345)
    auto._derive_repair_search_rng(12345, 7, "direction")
    observed = tuple(observed_beam.getrandbits(64) for _ in range(4))
    assert observed == expected


def test_v2126_stratified_sensitivity_order_is_seeded_and_broad() -> None:
    fixed = auto._repair_sensitivity_tick_order(0, 192, 192, None)
    assert fixed == tuple(range(193))

    first = auto._repair_sensitivity_tick_order(
        0,
        192,
        192,
        auto._derive_repair_search_rng(41, 1, "direction"),
    )
    repeat = auto._repair_sensitivity_tick_order(
        0,
        192,
        192,
        auto._derive_repair_search_rng(41, 1, "direction"),
    )
    other_seed = auto._repair_sensitivity_tick_order(
        0,
        192,
        192,
        auto._derive_repair_search_rng(42, 1, "direction"),
    )

    assert first == repeat
    assert first != other_seed
    assert first[0] == 192
    assert len(first) == 193
    assert set(first) == set(range(193))

    # Frames 0..191 split exactly into 24 eight-frame strata.  The first round
    # after the failure frame must sample every stratum before any receives a
    # second probe.
    assert {tick // 8 for tick in first[1:25]} == set(range(24))


def test_v2126_fixed_orders_match_legacy_and_random_orders_keep_source_first() -> None:
    assert auto._direction_search_order(1, None, source_first=True) == (1, 0, -1)
    assert auto._direction_search_order(0, None, source_first=False) == (-1, 1)
    assert auto._pair_direction_search_order(0, 0, None) == tuple(
        (left, right)
        for left in (-1, 0, 1)
        for right in (-1, 0, 1)
    )
    assert auto._all_input_search_order((1, False), None) == (
        (1, False),
        (0, False),
        (-1, False),
        (0, True),
        (-1, True),
        (1, True),
    )

    direction_rng = auto._derive_repair_search_rng(99, 3, "direction")
    direction_order = auto._direction_search_order(
        1,
        direction_rng,
        source_first=True,
    )
    assert direction_order[0] == 1
    assert set(direction_order) == {-1, 0, 1}

    pair_rng = auto._derive_repair_search_rng(99, 3, "pair")
    pair_order = auto._pair_direction_search_order(0, -1, pair_rng)
    assert len(pair_order) == 4
    assert len(set(pair_order)) == 4
    assert all(left != 0 and right != -1 for left, right in pair_order)

    all_input_rng = auto._derive_repair_search_rng(99, 3, "all-input")
    all_input_order = auto._all_input_search_order((1, False), all_input_rng)
    assert all_input_order[0] == (1, False)
    assert len(all_input_order) == 6
    assert set(all_input_order) == {
        (direction, jump)
        for direction in (-1, 0, 1)
        for jump in (False, True)
    }


def test_v2126_random_ties_prefer_fewer_edits_then_stable_replay_key() -> None:
    source = (InputFrame(), InputFrame(), auto.NEUTRAL_INPUT)
    one_edit_left = (InputFrame(left=True), InputFrame(), auto.NEUTRAL_INPUT)
    one_edit_right = (InputFrame(right=True), InputFrame(), auto.NEUTRAL_INPUT)
    two_edits = (
        InputFrame(left=True),
        InputFrame(right=True),
        auto.NEUTRAL_INPUT,
    )

    assert auto._repair_proposal_is_better(
        source,
        one_edit_right,
        1.0,
        two_edits,
        1.0,
        randomized=True,
    )
    assert not auto._repair_proposal_is_better(
        source,
        one_edit_right,
        1.0,
        two_edits,
        1.0,
        randomized=False,
    )
    assert auto._repair_proposal_is_better(
        source,
        one_edit_left,
        1.0,
        one_edit_right,
        1.0,
        randomized=True,
    )


def test_v2126_search_order_is_reported_in_diagnostics() -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    level = parse_level_string(
        f"{''.join(chars)}|5^60,134!11^140,134,60,134",
        simulate_enemies=True,
    )
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80

    random_result = auto.optimise_autonomous(
        level,
        source,
        AutoConfig(iterations=0, repair_search_order="random"),
    )
    fixed_result = auto.optimise_autonomous(
        level,
        source,
        AutoConfig(iterations=0, repair_search_order="fixed"),
    )

    assert any(
        "local repair traversal random" in diagnostic
        and "Auto seed 0" in diagnostic
        for diagnostic in random_result.diagnostics
    )
    assert any(
        "local repair traversal fixed" in diagnostic
        and "v2.12.5-compatible" in diagnostic
        for diagnostic in fixed_result.diagnostics
    )

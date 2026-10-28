from __future__ import annotations

import nv14_auto as auto
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame, parse_level_string


def _floor_level():
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    return parse_level_string(
        f"{''.join(chars)}|5^60,134!11^140,134,60,134"
    )


def test_all_input_fallback_rejects_new_inactive_jump_edges() -> None:
    level = _floor_level()
    seed = tuple(
        [InputFrame(right=True)]
        + [InputFrame(right=True, jump=True)] * 3
        + [InputFrame(right=True)] * 16
    ) + (auto.NEUTRAL_INPUT,)
    reference = tuple([InputFrame(right=True)] * 80) + (auto.NEUTRAL_INPUT,)
    seed_evaluation = auto._evaluate_working(level, seed)
    reference_evaluation = auto._evaluate_working(level, reference)

    repaired, _branches, _simulations = auto.repair_all_input_window(
        level,
        seed,
        reference_evaluation,
        seed_evaluation=seed_evaluation,
        failure_tick=5,
        reference_offset=0,
        config=auto.AutoConfig(
            iterations=1,
            repair_window=4,
            repair_lookahead=4,
            max_jump_shift=2,
            range_start=0,
            range_end=19,
            repair_local_limit=5_000,
            repair_search_order=auto.AUTO_REPAIR_SEARCH_ORDER_FIXED,
        ),
        require_failure_jump=False,
    )

    # Releasing the middle of the held pulse can make the unchanged third
    # frame look like a new rising edge. In this route it does not call
    # Player.jump(); it must not become a descendant repair target.
    assert seed_evaluation.missed_jump_edges == ()
    assert repaired is not None
    repaired_evaluation = auto._evaluate_working(level, repaired)
    assert set(repaired_evaluation.missed_jump_edges) <= set(
        seed_evaluation.missed_jump_edges
    )

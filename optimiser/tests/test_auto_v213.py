from __future__ import annotations

import nv14_auto as auto
from nv14_auto import AlignmentMatch, AutoConfig, AutoEvaluation
from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    parse_level_string,
)


def _long_floor_level():
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    return parse_level_string(
        f"{''.join(chars)}|5^60,134!11^700,134,60,134",
        simulate_enemies=True,
    )


def test_v213_qualifying_repairs_are_not_capped_by_the_old_bank(
    monkeypatch,
) -> None:
    """More than the former default 16 repairs may run in one Auto search."""
    level = _long_floor_level()
    source = [
        InputFrame(right=(tick // 2) % 2 == 0)
        for tick in range(400)
    ]
    real_evaluate = auto._evaluate_working
    supplied_working = tuple(source) + (auto.NEUTRAL_INPUT,)
    supplied_evaluation = real_evaluate(level, supplied_working)
    assert supplied_evaluation.finish_tick is not None
    canonical_working = (
        tuple(source[: supplied_evaluation.finish_tick])
        + (auto.NEUTRAL_INPUT,)
    )

    def evaluate_only_the_source_as_complete(
        level_, working, *, trace_stride=1
    ) -> AutoEvaluation:
        fixed = tuple(working)
        if fixed in (supplied_working, canonical_working):
            return real_evaluate(
                level_, fixed, trace_stride=trace_stride
            )
        return AutoEvaluation(
            finish_tick=None,
            dead_tick=10,
            last_tick=10,
            trace=(),
            successful_jumps=(),
            jump_edges=(),
            missed_jump_edges=(),
        )

    def align_every_failed_candidate(*_args, **_kwargs) -> AlignmentMatch:
        return AlignmentMatch(
            candidate_tick=10,
            reference_tick=10,
            offset=0,
            distance=0.0,
            contact_matches=True,
            static_matches=True,
        )

    observed_local_limits: list[int] = []

    def exhaust_direction_budget(*_args, **kwargs):
        local_limit = kwargs["config"].repair_local_limit
        observed_local_limits.append(local_limit)
        return None, 1, local_limit

    monkeypatch.setattr(auto, "_evaluate_working", evaluate_only_the_source_as_complete)
    monkeypatch.setattr(auto, "find_baseline_alignment", align_every_failed_candidate)
    monkeypatch.setattr(auto, "repair_direction_window", exhaust_direction_budget)

    result = auto.optimise_autonomous(
        level,
        source,
        AutoConfig(
            iterations=80,
            beam_width=8,
            max_retime=1,
            cheap_pulse_limit=0,
            repair_local_limit=3,
            all_input_repair=False,
            max_jump_shift=0,
            max_jump_hold_delta=0,
        ),
    )

    assert result.stats.repair_attempts > 16
    assert len(observed_local_limits) == result.stats.repair_attempts
    assert set(observed_local_limits) == {3}
    assert result.stats.local_simulations == 3 * result.stats.repair_attempts
    assert not hasattr(result.stats, "repair_tokens_refilled")
    assert not hasattr(result.stats, "repair_bonus_tokens")
    assert any(
        "no global repair bank" in diagnostic
        for diagnostic in result.diagnostics
    )

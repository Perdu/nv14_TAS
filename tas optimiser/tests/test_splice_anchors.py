from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import nv14_auto as auto


def _point(
    tick: int,
    *,
    x: float | None = None,
    vx: float = 1.0,
    previous_jump_held: bool = False,
    gold: int = 0,
    mines: int = 0,
    exits: int = 0,
    locked: int = 0,
    traps: int = 0,
    complete: bool = False,
    dead: bool = False,
) -> auto.CompactTracePoint:
    return auto.CompactTracePoint(
        tick=tick,
        x=float(tick if x is None else x),
        y=100.0,
        vx=vx,
        vy=0.25,
        player_state=0,
        in_air=True,
        near_wall=False,
        wall_x=0,
        floor_x=0,
        floor_y=0,
        previous_jump_held=previous_jump_held,
        jump_events=0,
        collected_gold_mask=gold,
        exploded_mine_mask=mines,
        open_exit_mask=exits,
        opened_locked_door_mask=locked,
        triggered_trapdoor_mask=traps,
        complete=complete,
        dead=dead,
        gold_bonus_ticks=auto.GOLD_BONUS_TICKS * gold.bit_count(),
    )


class _Analysis:
    def __init__(
        self,
        points: tuple[auto.CompactTracePoint, ...],
        *,
        final_gold_mask: int | None = None,
    ) -> None:
        self._points = points
        self._final_gold_mask = (
            points[-1].collected_gold_mask
            if final_gold_mask is None
            else final_gold_mask
        )

    def materialize_trace(self):
        return self._points

    def summary(self):
        final_bonus = auto.GOLD_BONUS_TICKS * self._final_gold_mask.bit_count()
        return (
            -1,
            -1,
            self._points[-1].tick,
            False,
            -1,
            False,
            0.0,
            final_bonus,
            self._final_gold_mask,
        )


def test_find_splice_anchor_runs_returns_every_maximal_corridor() -> None:
    recipient = _Analysis(tuple(_point(tick) for tick in range(10)))
    donor_points = tuple(
        _point(
            tick,
            x=tick - 2,
            exits=(1 if tick == 7 else 0),
            gold=(2 if tick >= 8 else 0),
        )
        for tick in range(2, 12)
    )
    donor = _Analysis(donor_points)

    runs = auto.find_splice_anchor_runs(
        recipient,
        donor,
        auto.SpliceAlignmentSpec(
            minimum_run_length=4,
            position_tolerance=0.01,
            velocity_tolerance=0.01,
            objective=auto.AUTO_OBJECTIVE_HIGHSCORE,
        ),
    )

    assert [
        (
            run.recipient_start_tick,
            run.recipient_end_tick,
            run.donor_start_tick,
            run.donor_end_tick,
            run.frame_offset,
        )
        for run in runs
    ] == [(0, 4, 2, 6, 2), (6, 9, 8, 11, 2)]
    assert runs[0].length == 5
    assert runs[0].best_recipient_tick == 2
    assert runs[0].best_match_cost == 0.0
    assert runs[0].gold_matches_throughout is True
    assert runs[1].gold_matches_throughout is False
    assert runs[1].donor_gold_bonus_change == 0


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("exploded_mine_mask", 1),
        ("open_exit_mask", 1),
        ("opened_locked_door_mask", 1),
        ("triggered_trapdoor_mask", 1),
    ),
)
def test_splice_route_control_state_is_an_exact_hard_match(
    field: str,
    value: int,
) -> None:
    recipient_points = tuple(_point(tick) for tick in range(5))
    donor_points = tuple(
        replace(_point(tick), **{field: value}) for tick in range(5)
    )

    assert auto.find_splice_anchor_runs(
        _Analysis(recipient_points),
        _Analysis(donor_points),
        auto.SpliceAlignmentSpec(minimum_run_length=2),
    ) == ()


def test_splice_contact_jump_hold_and_terminal_state_are_hard_matches() -> None:
    recipient = _Analysis(tuple(_point(tick) for tick in range(6)))
    held_donor = _Analysis(
        tuple(_point(tick, previous_jump_held=True) for tick in range(6))
    )
    terminal_donor = _Analysis(
        tuple(
            _point(tick, dead=(tick == 2), complete=(tick == 3))
            for tick in range(6)
        )
    )

    assert auto.find_splice_anchor_runs(
        recipient,
        held_donor,
        auto.SpliceAlignmentSpec(minimum_run_length=2),
    ) == ()
    terminal_runs = auto.find_splice_anchor_runs(
        recipient,
        terminal_donor,
        auto.SpliceAlignmentSpec(
            minimum_run_length=2,
            minimum_frame_offset=0,
            maximum_frame_offset=0,
        ),
    )
    assert [
        (run.recipient_start_tick, run.recipient_end_tick)
        for run in terminal_runs
    ] == [(0, 1), (4, 5)]


def test_splice_tick_and_offset_ranges_are_inclusive() -> None:
    recipient = _Analysis(tuple(_point(tick) for tick in range(10)))
    donor = _Analysis(
        tuple(_point(tick, x=tick - 2) for tick in range(2, 12))
    )

    runs = auto.find_splice_anchor_runs(
        recipient,
        donor,
        auto.SpliceAlignmentSpec(
            minimum_run_length=3,
            position_tolerance=0.0,
            velocity_tolerance=0.0,
            recipient_start_tick=2,
            recipient_end_tick=8,
            donor_start_tick=4,
            donor_end_tick=10,
            minimum_frame_offset=2,
            maximum_frame_offset=2,
        ),
    )

    assert len(runs) == 1
    assert (runs[0].recipient_start_tick, runs[0].recipient_end_tick) == (2, 8)
    assert (runs[0].donor_start_tick, runs[0].donor_end_tick) == (4, 10)


def test_predict_splice_gold_accounts_for_prefix_segment_and_suffix() -> None:
    recipient = _Analysis(
        (
            _point(0, gold=0b001),
            _point(4, gold=0b011),
            _point(9, gold=0b111),
        ),
        final_gold_mask=0b111,
    )
    donor_missing = _Analysis(
        (_point(2, gold=0), _point(7, gold=0b100)),
        final_gold_mask=0b100,
    )

    prediction = auto.predict_splice_gold(
        recipient,
        donor_missing,
        recipient_entry_tick=0,
        donor_entry_tick=2,
        recipient_exit_tick=4,
        donor_exit_tick=7,
        require_reference_gold=True,
    )

    assert prediction.final_gold_mask == 0b101
    assert prediction.gold_bonus_ticks == 160
    assert prediction.gold_bonus_delta == -80
    assert prediction.finish_tick_delta == 1
    assert prediction.highscore_objective_delta == -81
    assert prediction.objective_delta(auto.AUTO_OBJECTIVE_HIGHSCORE) == -81
    assert prediction.speedrun_objective_delta == -1
    assert prediction.missing_required_gold_mask == 0b010
    assert prediction.preserves_required_gold is False

    donor_complete = _Analysis(
        (_point(2, gold=0), _point(7, gold=0b010)),
        final_gold_mask=0b010,
    )
    complete_prediction = auto.predict_splice_gold(
        recipient,
        donor_complete,
        recipient_entry_tick=0,
        donor_entry_tick=2,
        recipient_exit_tick=4,
        donor_exit_tick=7,
        require_reference_gold=True,
    )
    assert complete_prediction.final_gold_mask == 0b111
    assert complete_prediction.gold_bonus_delta == 0
    assert complete_prediction.highscore_objective_delta == -1
    assert complete_prediction.preserves_required_gold is True


def test_splice_alignment_spec_rejects_invalid_policy() -> None:
    with pytest.raises(ValueError, match="minimum_run_length"):
        auto.SpliceAlignmentSpec(minimum_run_length=1)
    with pytest.raises(ValueError, match="maximum_frame_offset"):
        auto.SpliceAlignmentSpec(
            minimum_frame_offset=2,
            maximum_frame_offset=1,
        )


def _plan_alignment_spec(*, objective: str = auto.AUTO_OBJECTIVE_SPEEDRUN):
    return auto.SpliceAlignmentSpec(
        minimum_run_length=4,
        position_tolerance=0.0,
        velocity_tolerance=0.0,
        objective=objective,
    )


def _plan_spec(*, objective: str = auto.AUTO_OBJECTIVE_SPEEDRUN, length: int = 8):
    return auto.SplicePlanSpec(
        minimum_section_length=length,
        objective=objective,
    )


def _joint_choice_analyses(*, imperfect_entry: bool = False):
    recipient = _Analysis(tuple(_point(tick) for tick in range(36)))
    donor_points = []
    for tick in range(3, 10):
        recipient_tick = tick - 3
        error = 0.0
        if imperfect_entry and recipient_tick != 3:
            error = 0.125
        donor_points.append(_point(tick, x=recipient_tick + error))
    for tick in range(22, 29):
        donor_points.append(_point(tick, x=tick - 2))
    return recipient, _Analysis(tuple(donor_points))


def _neutral_frames(count: int) -> tuple[auto.InputFrame, ...]:
    return tuple(auto.InputFrame() for _ in range(count))


def _segment_plan(
    a0: int,
    b0: int,
    a1: int,
    b1: int,
    *,
    predicted_gain: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        recipient_entry_tick=a0,
        donor_entry_tick=b0,
        recipient_exit_tick=a1,
        donor_exit_tick=b1,
        predicted_time_gain=(
            (a1 - a0) - (b1 - b0)
            if predicted_gain is None
            else predicted_gain
        ),
    )


def test_reference_segment_splice_uses_post_input_state_boundaries() -> None:
    recipient_body = tuple(
        auto.InputFrame(
            left=bool(code & 1),
            right=bool(code & 2),
            jump=bool(code & 4),
        )
        for code in range(8)
    )
    donor_body = tuple(reversed(recipient_body))
    recipient = recipient_body + (auto.NEUTRAL_INPUT,)
    donor = donor_body + (auto.NEUTRAL_INPUT,)
    plan = _segment_plan(1, 0, 6, 3)

    result = auto.apply_reference_segment_splice(
        recipient,
        donor,
        plan,
        max_body_length=6,
    )

    expected_body = (
        recipient_body[:2]
        + donor_body[1:4]
        + recipient_body[7:]
    )
    assert result == expected_body + (auto.NEUTRAL_INPUT,)
    child_end = plan.recipient_entry_tick + (
        plan.donor_exit_tick - plan.donor_entry_tick
    )
    assert result[child_end + 1] == recipient_body[plan.recipient_exit_tick + 1]
    assert plan.recipient_exit_tick - child_end == plan.predicted_time_gain


def test_reference_segment_splice_pads_to_bound_and_normalises_new_suffixes() -> None:
    recipient = (
        auto.InputFrame(left=True, jump_trigger=True),
        auto.InputFrame(right=True, jump_trigger=False),
        auto.InputFrame(jump=True, jump_trigger=True),
        auto.InputFrame(left=True, jump=True, jump_trigger=False),
        auto.NEUTRAL_INPUT,
    )
    donor = (
        auto.InputFrame(right=True, jump_trigger=True),
        auto.InputFrame(left=True, right=True, jump_trigger=False),
        auto.InputFrame(right=True, jump=True, jump_trigger=True),
        auto.NEUTRAL_INPUT,
    )
    plan = _segment_plan(0, 0, 2, 1)

    result = auto.apply_reference_segment_splice(
        recipient,
        donor,
        plan,
        max_body_length=5,
    )

    assert result[:3] == (
        recipient[0],
        auto.InputFrame(left=True, right=True),
        auto.InputFrame(left=True, jump=True),
    )
    assert result[3:] == (auto.NEUTRAL_INPUT,) * 3
    assert result[0].jump_trigger is True
    assert all(frame.jump_trigger is None for frame in result[1:])


def test_reference_segment_splice_rejects_invalid_plan_bounds() -> None:
    working = _neutral_frames(5) + (auto.NEUTRAL_INPUT,)

    with pytest.raises(ValueError, match="exit ticks must follow"):
        auto.apply_reference_segment_splice(
            working,
            working,
            _segment_plan(2, 0, 2, 1),
            max_body_length=5,
        )
    with pytest.raises(ValueError, match="donor splice"):
        auto.apply_reference_segment_splice(
            working,
            working,
            _segment_plan(0, 0, 2, 5),
            max_body_length=5,
        )
    with pytest.raises(ValueError, match="predicted_time_gain"):
        auto.apply_reference_segment_splice(
            working,
            working,
            _segment_plan(0, 0, 2, 1, predicted_gain=0),
            max_body_length=5,
        )


def test_splice_plan_requires_a_genuine_local_time_gain() -> None:
    recipient = _Analysis(tuple(_point(tick) for tick in range(41)))
    donor = _Analysis(
        tuple(
            _point(tick, x=tick + 3)
            for tick in (*range(7, 13), *range(27, 33))
        )
    )

    runs = auto.find_splice_anchor_runs(
        recipient,
        donor,
        _plan_alignment_spec(),
    )
    assert [run.frame_offset for run in runs] == [-3, -3]
    assert auto.find_splice_section_plans(
        recipient,
        donor,
        _plan_alignment_spec(),
        _plan_spec(),
        anchor_runs=runs,
    ) == ()


def test_splice_plan_uses_change_in_offset_for_predicted_gain() -> None:
    recipient = _Analysis(tuple(_point(tick) for tick in range(41)))
    donor = _Analysis(
        tuple(
            _point(tick, x=(tick - 3 if tick < 10 else tick - 1))
            for tick in (*range(3, 9), *range(21, 27))
        )
    )

    plans = auto.find_splice_section_plans(
        recipient,
        donor,
        _plan_alignment_spec(),
        _plan_spec(),
    )

    assert len(plans) == 1
    plan = plans[0]
    assert plan.entry_anchor_run.frame_offset == 3
    assert plan.exit_anchor_run.frame_offset == 1
    assert plan.predicted_time_gain == 2
    assert plan.predicted_gain == 2
    assert plan.predicted_time_gain == (
        plan.recipient_section_length - plan.donor_section_length
    )
    assert plan.recipient_section_length >= 8
    assert plan.donor_section_length >= 8
    assert plan.local_score_gain == 2


def test_splice_frames_are_jointly_scored_for_future_input_similarity() -> None:
    recipient, donor = _joint_choice_analyses(imperfect_entry=True)
    recipient_frames = _neutral_frames(40)
    donor_frames = list(_neutral_frames(40))
    # The individually closest entry is recipient 3 / donor 6.  Its next held
    # input differs, whereas the slightly less exact adjacent seams are calm.
    donor_frames[7] = auto.InputFrame(left=True)
    spec = auto.SplicePlanSpec(
        minimum_section_length=8,
        predicted_gain_weight=1.0,
        route_state_penalty_weight=0.0,
        jump_proximity_weight=0.0,
        input_mismatch_weight=10.0,
        corridor_support_weight=0.0,
        section_length_risk_weight=0.0,
        jump_rising_edge_lookahead=0,
        input_similarity_lookahead=1,
    )

    plan = auto.find_splice_section_plans(
        recipient,
        donor,
        auto.SpliceAlignmentSpec(
            minimum_run_length=4,
            position_tolerance=0.13,
            velocity_tolerance=0.0,
        ),
        spec,
        recipient_frames=recipient_frames,
        donor_frames=tuple(donor_frames),
    )[0]

    assert (plan.recipient_entry_tick, plan.donor_entry_tick) == (4, 7)
    assert plan.entry_match_cost > 0.0
    assert plan.input_mismatch_penalty == 0.0
    assert plan.plan_utility == pytest.approx(
        spec.predicted_gain_weight * plan.predicted_gain
        - plan.combined_mismatch_cost
        - plan.route_state_penalty
        - plan.seam_sensitivity_penalty
        - plan.section_length_risk_penalty
    )


def test_splice_frames_avoid_the_lookahead_before_a_jump_rising_edge() -> None:
    recipient, donor = _joint_choice_analyses(imperfect_entry=True)
    recipient_frames = _neutral_frames(40)
    donor_frames = list(_neutral_frames(40))
    donor_frames[7] = auto.InputFrame(jump=True)

    plan = auto.find_splice_section_plans(
        recipient,
        donor,
        auto.SpliceAlignmentSpec(
            minimum_run_length=4,
            position_tolerance=0.13,
            velocity_tolerance=0.0,
        ),
        auto.SplicePlanSpec(
            minimum_section_length=8,
            predicted_gain_weight=1.0,
            route_state_penalty_weight=0.0,
            jump_proximity_weight=10.0,
            input_mismatch_weight=0.0,
            corridor_support_weight=0.0,
            section_length_risk_weight=0.0,
            jump_rising_edge_lookahead=1,
            input_similarity_lookahead=0,
        ),
        recipient_frames=recipient_frames,
        donor_frames=tuple(donor_frames),
    )[0]

    assert (plan.recipient_entry_tick, plan.donor_entry_tick) == (4, 7)
    assert plan.jump_proximity_penalty == 0.0


def test_splice_frames_prefer_centrally_supported_corridor_seams() -> None:
    recipient, donor = _joint_choice_analyses()

    plan = auto.find_splice_section_plans(
        recipient,
        donor,
        _plan_alignment_spec(),
        auto.SplicePlanSpec(
            minimum_section_length=8,
            predicted_gain_weight=1.0,
            route_state_penalty_weight=0.0,
            jump_proximity_weight=0.0,
            input_mismatch_weight=0.0,
            corridor_support_weight=10.0,
            section_length_risk_weight=0.0,
            jump_rising_edge_lookahead=0,
            input_similarity_lookahead=0,
        ),
    )[0]

    assert (plan.recipient_entry_tick, plan.recipient_exit_tick) == (3, 23)
    assert plan.entry_corridor_support == 7
    assert plan.exit_corridor_support == 7
    assert plan.corridor_support_penalty == pytest.approx(20.0 / 7.0)


def test_highscore_plan_accepts_extra_gold_that_outweighs_time_loss() -> None:
    recipient = _Analysis(tuple(_point(tick) for tick in range(31)))
    donor = _Analysis(
        tuple(
            _point(
                tick,
                x=(float(tick) if tick < 10 else float(tick - 1)),
                gold=(0 if tick < 10 else 0b1),
            )
            for tick in (*range(6), *range(21, 27))
        ),
        final_gold_mask=0b1,
    )
    objective = auto.AUTO_OBJECTIVE_HIGHSCORE

    plans = auto.find_splice_section_plans(
        recipient,
        donor,
        _plan_alignment_spec(objective=objective),
        _plan_spec(objective=objective),
    )

    assert len(plans) == 1
    plan = plans[0]
    assert plan.predicted_time_gain == -1
    assert plan.donor_gold_bonus_gained == auto.GOLD_BONUS_TICKS
    assert plan.recipient_gold_bonus_gained == 0
    assert plan.local_gold_bonus_delta == auto.GOLD_BONUS_TICKS
    assert plan.local_score_gain == auto.GOLD_BONUS_TICKS - 1
    assert plan.objective_gain(objective) == auto.GOLD_BONUS_TICKS - 1


def test_highscore_plan_rejects_time_gain_outweighed_by_lost_gold() -> None:
    recipient = _Analysis(
        tuple(
            _point(tick, gold=(0 if tick < 10 else 0b1))
            for tick in range(31)
        ),
        final_gold_mask=0b1,
    )
    donor = _Analysis(
        tuple(
            _point(tick, x=(tick - 3 if tick < 10 else tick - 1))
            for tick in (*range(3, 9), *range(21, 27))
        )
    )
    objective = auto.AUTO_OBJECTIVE_HIGHSCORE

    assert auto.find_splice_section_plans(
        recipient,
        donor,
        _plan_alignment_spec(objective=objective),
        _plan_spec(objective=objective),
    ) == ()


def test_splice_plan_minimum_length_applies_to_both_replays() -> None:
    recipient = _Analysis(tuple(_point(tick) for tick in range(20)))
    donor = _Analysis(
        tuple(
            _point(tick, x=(tick - 3 if tick < 8 else tick - 1))
            for tick in (*range(3, 9), *range(9, 15))
        )
    )

    assert auto.find_splice_section_plans(
        recipient,
        donor,
        _plan_alignment_spec(),
        _plan_spec(length=12),
    ) == ()


def _anchor_run(start: int, end: int, offset: int) -> auto.SpliceAnchorRun:
    return auto.SpliceAnchorRun(
        recipient_start_tick=start,
        recipient_end_tick=end,
        donor_start_tick=start + offset,
        donor_end_tick=end + offset,
        frame_offset=offset,
        best_recipient_tick=start,
        best_donor_tick=start + offset,
        best_match_cost=0.0,
        mean_match_cost=0.0,
        best_position_error=0.0,
        best_velocity_error=0.0,
        max_position_error=0.0,
        max_velocity_error=0.0,
        gold_matches_throughout=True,
        recipient_gold_mask_start=0,
        recipient_gold_mask_end=0,
        donor_gold_mask_start=0,
        donor_gold_mask_end=0,
        recipient_gold_bonus_start=0,
        recipient_gold_bonus_end=0,
        donor_gold_bonus_start=0,
        donor_gold_bonus_end=0,
    )


def test_splice_plan_deduplication_caps_near_identical_plans() -> None:
    points = tuple(_point(tick, x=0.0, vx=0.0) for tick in range(41))
    analysis = _Analysis(points)
    runs = (
        _anchor_run(0, 3, 2),
        _anchor_run(4, 7, 2),
        _anchor_run(24, 27, 0),
        _anchor_run(28, 31, 0),
    )

    plans = auto.find_splice_section_plans(
        analysis,
        analysis,
        _plan_alignment_spec(),
        auto.SplicePlanSpec(
            minimum_section_length=8,
            deduplication_tick_bucket=100,
            plans_per_bucket=2,
        ),
        anchor_runs=runs,
    )

    assert len(plans) == 2
    assert all(plan.predicted_time_gain == 2 for plan in plans)
    assert len(
        {
            (
                plan.recipient_entry_tick,
                plan.donor_entry_tick,
                plan.recipient_exit_tick,
                plan.donor_exit_tick,
            )
            for plan in plans
        }
    ) == 2


def test_splice_plan_spec_rejects_invalid_policy() -> None:
    with pytest.raises(ValueError, match="minimum_section_length"):
        auto.SplicePlanSpec(minimum_section_length=0)
    with pytest.raises(ValueError, match="minimum_predicted_gain"):
        auto.SplicePlanSpec(minimum_predicted_gain=0)
    with pytest.raises(ValueError, match="plans_per_bucket"):
        auto.SplicePlanSpec(plans_per_bucket=3)
    with pytest.raises(ValueError, match="predicted_gain_weight"):
        auto.SplicePlanSpec(predicted_gain_weight=0.0)
    with pytest.raises(ValueError, match="jump_rising_edge_lookahead"):
        auto.SplicePlanSpec(jump_rising_edge_lookahead=-1)
    with pytest.raises(ValueError, match="input_similarity_lookahead"):
        auto.SplicePlanSpec(input_similarity_lookahead=-1)


def test_splice_plan_input_streams_must_be_supplied_together() -> None:
    recipient, donor = _joint_choice_analyses()
    with pytest.raises(ValueError, match="must be supplied together"):
        auto.find_splice_section_plans(
            recipient,
            donor,
            _plan_alignment_spec(),
            _plan_spec(),
            recipient_frames=_neutral_frames(40),
        )

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import nv14_auto as auto
import nv14_auto_parallel as parallel
from nv14_splice_index import prepare_splice_trace, splice_match_key


def _point(
    tick: int,
    *,
    x: float | None = None,
    near_wall: bool = False,
    wall_x: int = 0,
    gold: int = 0,
    complete: bool = False,
    dead: bool = False,
) -> auto.CompactTracePoint:
    return auto.CompactTracePoint(
        tick=tick,
        x=float(tick if x is None else x),
        y=100.0,
        vx=1.0,
        vy=0.0,
        player_state=0,
        in_air=False,
        near_wall=near_wall,
        wall_x=wall_x,
        floor_x=0,
        floor_y=-1,
        previous_jump_held=False,
        jump_events=0,
        collected_gold_mask=gold,
        exploded_mine_mask=0,
        open_exit_mask=0,
        opened_locked_door_mask=0,
        triggered_trapdoor_mask=0,
        complete=complete,
        dead=dead,
        gold_bonus_ticks=auto.GOLD_BONUS_TICKS * gold.bit_count(),
    )


class _Analysis:
    def __init__(self, points: tuple[auto.CompactTracePoint, ...]) -> None:
        self._points = points

    def materialize_trace(self) -> tuple[auto.CompactTracePoint, ...]:
        return self._points

    def summary(self) -> tuple[object, ...]:
        final_gold = self._points[-1].collected_gold_mask
        return (
            -1,
            -1,
            self._points[-1].tick,
            False,
            -1,
            False,
            0.0,
            auto.GOLD_BONUS_TICKS * final_gold.bit_count(),
            final_gold,
        )


def _evaluation(last_tick: int, *, jumps: tuple[int, ...] = ()) -> auto.AutoEvaluation:
    return auto.AutoEvaluation(
        finish_tick=None,
        dead_tick=None,
        last_tick=last_tick,
        trace=tuple(_point(tick) for tick in range(last_tick + 1)),
        successful_jumps=jumps,
        jump_edges=jumps,
        missed_jump_edges=(),
    )


def _frames(count: int, *, reverse: bool = False) -> tuple[auto.InputFrame, ...]:
    frames = tuple(
        auto.InputFrame(
            left=bool(code & 1),
            right=bool(code & 2),
            jump=bool(code & 4),
        )
        for code in range(count)
    )
    return tuple(reversed(frames)) if reverse else frames


def _start_plan(recipient_exit: int, donor_exit: int) -> SimpleNamespace:
    return SimpleNamespace(
        recipient_entry_tick=-1,
        donor_entry_tick=-1,
        recipient_exit_tick=recipient_exit,
        donor_exit_tick=donor_exit,
        predicted_time_gain=recipient_exit - donor_exit,
    )


def test_splice_key_ignores_dormant_wall_normal_but_not_active_contact() -> None:
    ordinary = _point(3, near_wall=False, wall_x=0)
    stale_normal = replace(ordinary, wall_x=1)
    active_left = replace(ordinary, near_wall=True, wall_x=-1)
    active_right = replace(ordinary, near_wall=True, wall_x=1)

    # CompactTracePoint.contact_key remains an exact state/debugging view.  The
    # splice-specific key alone normalises wall_x when the engine cannot read
    # it, preventing stale wall-contact history from hiding a valid corridor.
    assert ordinary.contact_key != stale_normal.contact_key
    assert auto._splice_match_key(ordinary) == auto._splice_match_key(stale_normal)
    assert splice_match_key(ordinary) == splice_match_key(stale_normal)
    assert auto._trace_distance(ordinary, stale_normal) > 0.0
    assert auto._splice_trace_distance(ordinary, stale_normal) == 0.0
    assert auto._splice_match_key(active_left) != auto._splice_match_key(active_right)
    assert splice_match_key(active_left) != splice_match_key(active_right)


def test_prepared_splice_index_groups_dormant_but_not_active_wall_normals() -> None:
    points = (
        _point(0, x=10.0, wall_x=0),
        _point(1, x=11.0, wall_x=1),
        _point(2, x=12.0, near_wall=True, wall_x=-1),
        _point(3, x=13.0, near_wall=True, wall_x=1),
    )
    prepared = prepare_splice_trace(_Analysis(points))

    dormant = prepared.match_group(splice_match_key(points[0]))
    active_left = prepared.match_group(splice_match_key(points[2]))
    active_right = prepared.match_group(splice_match_key(points[3]))

    assert dormant is not None
    assert tuple(point.tick for point in dormant.points_by_x) == (0, 1)
    assert active_left is not None and active_right is not None
    assert active_left is not active_right
    assert tuple(point.tick for point in active_left.points_by_x) == (2,)
    assert tuple(point.tick for point in active_right.points_by_x) == (3,)


def test_start_splice_copies_donor_input_zero_and_uses_existing_plan_shape() -> None:
    recipient_body = _frames(8)
    donor_body = _frames(8, reverse=True)
    plan = _start_plan(recipient_exit=5, donor_exit=3)

    result = auto.apply_reference_segment_splice(
        recipient_body + (auto.NEUTRAL_INPUT,),
        donor_body + (auto.NEUTRAL_INPUT,),
        plan,
        max_body_length=8,
    )

    expected_body = donor_body[:4] + recipient_body[6:]
    assert result == expected_body + (auto.NEUTRAL_INPUT,) * 3
    assert result[0] == donor_body[0]
    assert result[0] != recipient_body[0]


@pytest.mark.parametrize(
    ("recipient_entry", "donor_entry"),
    ((-1, 0), (0, -1), (-2, -2)),
)
def test_start_splice_rejects_mixed_or_unknown_negative_boundaries(
    recipient_entry: int,
    donor_entry: int,
) -> None:
    working = _frames(8) + (auto.NEUTRAL_INPUT,)
    plan = SimpleNamespace(
        recipient_entry_tick=recipient_entry,
        donor_entry_tick=donor_entry,
        recipient_exit_tick=5,
        donor_exit_tick=3,
        predicted_time_gain=(5 - recipient_entry) - (3 - donor_entry),
    )

    with pytest.raises(ValueError, match="start|entry|negative|non-negative"):
        auto.apply_reference_segment_splice(
            working,
            working,
            plan,
            max_body_length=8,
        )


def test_start_splice_piecewise_reference_has_no_empty_recipient_prefix() -> None:
    recipient = _evaluation(12, jumps=(1, 8, 12))
    donor = _evaluation(12, jumps=(0, 2, 3))
    plan = _start_plan(recipient_exit=8, donor_exit=6)

    legs = auto.build_splice_piecewise_reference(recipient, donor, plan)

    assert [
        (leg.child_start, leg.child_end, leg.reference_offset)
        for leg in legs
    ] == [(0, 6, 0), (7, None, 2)]
    assert legs[0].reference is donor
    assert legs[1].reference is recipient
    assert auto.map_piecewise_reference_events(
        legs,
        lambda evaluation: evaluation.successful_jumps,
    ) == (0, 2, 3, 10)


def test_start_splice_gold_prediction_uses_zero_progress_before_frame_zero() -> None:
    recipient = _Analysis(
        (
            _point(0, gold=0b001),
            _point(5, gold=0b011),
            _point(10, gold=0b111),
        )
    )
    donor = _Analysis(
        (
            _point(0, gold=0b001),
            _point(3, gold=0b101),
            _point(8, gold=0b101),
        )
    )

    prediction = auto.predict_splice_gold(
        recipient,
        donor,
        recipient_entry_tick=-1,
        donor_entry_tick=-1,
        recipient_exit_tick=5,
        donor_exit_tick=3,
        require_reference_gold=True,
    )

    assert prediction.final_gold_mask == 0b101
    assert prediction.gold_bonus_ticks == 2 * auto.GOLD_BONUS_TICKS
    assert prediction.finish_tick_delta == -2
    assert prediction.missing_required_gold_mask == 0b010


def test_section_planner_can_use_virtual_initial_state_as_ordinary_entry() -> None:
    recipient = _Analysis(tuple(_point(tick) for tick in range(24)))
    donor_points = tuple(
        _point(
            tick,
            # The routes differ initially, then the donor reaches the same
            # trajectory two ticks earlier for a supported late corridor.
            x=(100.0 + tick if tick < 8 else tick + 2.0),
        )
        for tick in range(22)
    )
    donor = _Analysis(donor_points)

    plans = auto.find_splice_section_plans(
        recipient,
        donor,
        auto.SpliceAlignmentSpec(
            minimum_run_length=4,
            position_tolerance=0.0,
            velocity_tolerance=0.0,
            recipient_start_tick=0,
        ),
        auto.SplicePlanSpec(minimum_section_length=8),
    )

    start_plans = [
        plan
        for plan in plans
        if plan.recipient_entry_tick == plan.donor_entry_tick == -1
    ]
    assert start_plans
    assert all(plan.predicted_time_gain == 2 for plan in start_plans)
    assert all(plan.recipient_section_length >= 8 for plan in start_plans)
    assert all(plan.donor_section_length >= 8 for plan in start_plans)


def test_section_planner_does_not_invent_start_entry_for_later_edit_range() -> None:
    recipient = _Analysis(tuple(_point(tick) for tick in range(24)))
    donor = _Analysis(
        tuple(
            _point(tick, x=(100.0 + tick if tick < 8 else tick + 2.0))
            for tick in range(22)
        )
    )

    plans = auto.find_splice_section_plans(
        recipient,
        donor,
        auto.SpliceAlignmentSpec(
            minimum_run_length=4,
            position_tolerance=0.0,
            velocity_tolerance=0.0,
            recipient_start_tick=1,
        ),
        auto.SplicePlanSpec(minimum_section_length=8),
    )

    assert all(
        (plan.recipient_entry_tick, plan.donor_entry_tick) != (-1, -1)
        for plan in plans
    )


def test_trusted_lane_does_not_force_a_weaker_replay_origin_plan() -> None:
    recipient = _Analysis(tuple(_point(tick) for tick in range(46)))
    donor = _Analysis(
        tuple(
            [
                *(_point(tick, x=tick - 2.0) for tick in range(2, 8)),
                *(_point(tick) for tick in range(20, 26)),
                *(
                    _point(tick, x=tick + 1.75)
                    for tick in range(34, 40)
                ),
            ]
        )
    )

    plans = auto.find_splice_section_plans(
        recipient,
        donor,
        auto.SpliceAlignmentSpec(
            minimum_run_length=4,
            position_tolerance=0.8,
            velocity_tolerance=0.0,
        ),
        auto.SplicePlanSpec(minimum_section_length=8),
    )

    assert any(plan.starts_at_initial_state for plan in plans)
    trusted = plans[0]
    assert trusted.trusted_alignment is True
    assert trusted.starts_at_initial_state is False
    assert trusted.entry_anchor_run.frame_offset == 2
    assert trusted.exit_anchor_run.frame_offset == 0
    assert trusted.predicted_time_gain == 2


def test_start_splice_interval_round_trips_through_checkpoint_validation() -> None:
    interval = parallel._splice_interval_from_checkpoint(
        [-1, 162, -1, 150],
        label="checkpoint survivor 0.splice_interval",
    )

    assert interval == (-1, 162, -1, 150)


def test_start_splice_population_niche_maps_origin_to_bucket_zero() -> None:
    member = SimpleNamespace(
        is_splice=True,
        splice_interval=(-1, 162, -1, 150),
        selection_recipient_member_id=7,
    )

    assert parallel._population_splice_niche(member) == (7, 0, 13)


def test_splice_progress_uses_active_contact_distance_at_exit_seam() -> None:
    recipient = _evaluation(12)
    donor = _evaluation(12)
    plan = _start_plan(recipient_exit=8, donor_exit=6)
    legs = auto.build_splice_piecewise_reference(recipient, donor, plan)
    candidate_trace = tuple(
        _point(tick, x=8.0, wall_x=1)
        if tick == 6
        else _point(tick)
        for tick in range(13)
    )
    candidate_evaluation = auto.AutoEvaluation(
        finish_tick=None,
        dead_tick=None,
        last_tick=12,
        trace=candidate_trace,
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
    )
    candidate = auto.AutoCandidate(
        _frames(13) + (auto.NEUTRAL_INPUT,),
        candidate_evaluation,
        "dormant wall-normal progress regression",
    )

    snapshot = auto._splice_progress_snapshot(
        candidate,
        legs,
        auto.AutoConfig(iterations=0),
        auto.SpliceRepairSpec(),
    )

    assert snapshot.exit_alignment_distance == 0.0

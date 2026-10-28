from __future__ import annotations

import pickle

import nv14_auto as auto
from nv14_auto import CompactTracePoint
from nv14_engine import InputFrame
from nv14_splice_index import prepare_splice_trace, splice_match_key


def _point(
    tick: int,
    *,
    x: float | None = None,
    dead: bool = False,
    complete: bool = False,
    previous_jump_held: bool = False,
    gold_mask: int = 0,
    mine_mask: int = 0,
) -> CompactTracePoint:
    return CompactTracePoint(
        tick=tick,
        x=float(tick if x is None else x),
        y=24.0,
        vx=0.1,
        vy=0.2,
        player_state=0,
        in_air=True,
        near_wall=False,
        wall_x=0,
        floor_x=0,
        floor_y=0,
        previous_jump_held=previous_jump_held,
        jump_events=0,
        collected_gold_mask=gold_mask,
        exploded_mine_mask=mine_mask,
        open_exit_mask=0,
        opened_locked_door_mask=0,
        triggered_trapdoor_mask=0,
        complete=complete,
        dead=dead,
        gold_bonus_ticks=gold_mask.bit_count() * 36,
    )


class _CountingAnalysis:
    def __init__(self, trace: tuple[CompactTracePoint, ...]) -> None:
        self.trace = trace
        self.materializations = 0
        terminal = max(trace, key=lambda point: point.tick) if trace else None
        self.final_gold_mask = (
            terminal.collected_gold_mask if terminal is not None else 0
        )
        self.gold_bonus_ticks = (
            terminal.gold_bonus_ticks if terminal is not None else 0
        )
        self.jump_edges = (7, 3, 7)

    def materialize_trace(self) -> tuple[CompactTracePoint, ...]:
        self.materializations += 1
        return self.trace

    def summary(self) -> tuple[object, ...]:
        last_tick = max((point.tick for point in self.trace), default=-1)
        return (
            -1,
            -1,
            last_tick,
            False,
            -1,
            False,
            0.0,
            self.gold_bonus_ticks,
            self.final_gold_mask,
        )


class _NativeLikeUnpickleableAnalysis(_CountingAnalysis):
    def __reduce__(self):
        raise TypeError("native owner must not enter a process payload")


def test_prepare_splice_trace_materializes_and_indexes_a_member_once() -> None:
    analysis = _CountingAnalysis(
        (
            _point(2, x=12.0, gold_mask=1),
            _point(0, x=10.0),
            _point(1, x=11.0),
        )
    )

    prepared = prepare_splice_trace(analysis)
    reused = prepare_splice_trace(prepared)

    assert reused is prepared
    assert analysis.materializations == 1
    assert prepared.ticks == (0, 1, 2)
    assert prepared.point(1) is prepared.trace[1]
    assert prepared.final_gold_mask == 1
    assert prepared.gold_bonus_ticks == 36
    assert prepared.jump_edges == (3, 7)


def test_prepared_ranges_and_x_windows_are_inclusive_and_route_exact() -> None:
    points = (
        _point(0, x=5.0),
        _point(1, x=3.0),
        _point(2, x=4.0, mine_mask=1),
        _point(3, x=6.0),
        _point(4, x=7.0, dead=True),
        _point(5, x=float("nan")),
    )
    prepared = prepare_splice_trace(_CountingAnalysis(points))

    assert tuple(point.tick for point in prepared.eligible_between(1, 3)) == (
        1,
        2,
        3,
    )
    ordinary = prepared.match_group(splice_match_key(points[0]))
    changed_route = prepared.match_group(splice_match_key(points[2]))
    assert ordinary is not None
    assert changed_route is not None
    assert tuple(point.tick for point in ordinary.points_by_x) == (1, 0, 3)
    assert tuple(
        point.tick
        for point in ordinary.iter_x_window(
            5.0,
            1.0,
            start_tick=0,
            end_tick=3,
        )
    ) == (0, 3)
    assert tuple(point.tick for point in changed_route.points_by_x) == (2,)


def test_frame_jump_edges_are_prepared_once_and_value_is_process_pickleable() -> None:
    analysis = _NativeLikeUnpickleableAnalysis(
        tuple(_point(tick) for tick in range(6))
    )
    frames = (
        InputFrame(),
        InputFrame(jump=True),
        InputFrame(jump=True),
        InputFrame(),
        InputFrame(jump=True),
        InputFrame(),
    )
    prepared = prepare_splice_trace(analysis, frames)

    assert prepared.jump_edges == (1, 4)
    assert prepared.frames is frames
    restored = pickle.loads(pickle.dumps(prepared))
    assert restored.trace == prepared.trace
    assert restored.ticks == prepared.ticks
    assert restored.jump_edges == (1, 4)
    assert restored.source is None
    assert restored.point(3) == prepared.point(3)
    assert restored.match_groups == prepared.match_groups


def test_prepared_anchor_plan_and_gold_paths_match_unprepared_results() -> None:
    recipient_points = tuple(_point(tick) for tick in range(41))
    donor_points = tuple(
        _point(tick, x=(tick - 3 if tick < 10 else tick - 1))
        for tick in (*range(3, 9), *range(21, 27))
    )
    frames = tuple(InputFrame() for _ in range(41))
    alignment_spec = auto.SpliceAlignmentSpec(
        minimum_run_length=4,
        position_tolerance=0.0,
        velocity_tolerance=0.0,
    )
    plan_spec = auto.SplicePlanSpec(minimum_section_length=8)

    raw_recipient = _CountingAnalysis(recipient_points)
    raw_donor = _CountingAnalysis(donor_points)
    raw_plans = auto.find_splice_section_plans(
        raw_recipient,
        raw_donor,
        alignment_spec,
        plan_spec,
        recipient_frames=frames,
        donor_frames=frames,
    )
    assert len(raw_plans) == 1
    raw_plan = raw_plans[0]
    raw_prediction = auto.predict_splice_gold(
        raw_recipient,
        raw_donor,
        recipient_entry_tick=raw_plan.recipient_entry_tick,
        donor_entry_tick=raw_plan.donor_entry_tick,
        recipient_exit_tick=raw_plan.recipient_exit_tick,
        donor_exit_tick=raw_plan.donor_exit_tick,
    )

    indexed_recipient_source = _CountingAnalysis(recipient_points)
    indexed_donor_source = _CountingAnalysis(donor_points)
    indexed_recipient = prepare_splice_trace(indexed_recipient_source, frames)
    indexed_donor = prepare_splice_trace(indexed_donor_source, frames)
    indexed_plans = auto.find_splice_section_plans(
        indexed_recipient,
        indexed_donor,
        alignment_spec,
        plan_spec,
    )
    mixed_donor_source = _CountingAnalysis(donor_points)
    mixed_plans = auto.find_splice_section_plans(
        indexed_recipient,
        mixed_donor_source,
        alignment_spec,
        plan_spec,
        recipient_frames=frames,
        donor_frames=frames,
    )
    indexed_plan = indexed_plans[0]
    indexed_prediction = auto.predict_splice_gold(
        indexed_recipient,
        indexed_donor,
        recipient_entry_tick=indexed_plan.recipient_entry_tick,
        donor_entry_tick=indexed_plan.donor_entry_tick,
        recipient_exit_tick=indexed_plan.recipient_exit_tick,
        donor_exit_tick=indexed_plan.donor_exit_tick,
    )

    assert indexed_plans == raw_plans
    assert mixed_plans == raw_plans
    assert indexed_prediction == raw_prediction
    # Planning calls materialise the raw inputs once for point maps and again
    # for anchors; prediction is a third pass.  Prepared members stay at one.
    assert raw_recipient.materializations == 3
    assert raw_donor.materializations == 3
    assert indexed_recipient_source.materializations == 1
    assert indexed_donor_source.materializations == 1

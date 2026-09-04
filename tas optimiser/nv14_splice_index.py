"""Reusable trajectory preparation for inter-run splice planning.

The population scheduler compares each completed Auto result with several
other results from the same round.  Materialising and indexing a trajectory
inside every ordered-pair job makes that nominally pairwise work repeat for
every donor and recipient.  This module keeps the member-local part of the
work in one small, pickleable value which can be prepared once and shared by
all pair jobs.

The module intentionally does not import :mod:`nv14_auto`.  Avoiding that
dependency lets ``nv14_auto`` recognise and consume ``PreparedSpliceTrace``
without an import cycle, and keeps process-worker import/start-up cheap.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass


SpliceMatchKey = tuple[object, object, object, object, object]


def splice_contact_key(point: object) -> tuple[object, ...]:
    """Return contact state after normalising fields inactive in physics.

    The engine only reads the remembered wall normal while ``near_wall`` is
    true and the remembered floor normal while the player is grounded.  It
    deliberately does not clear either normal on every later frame, so
    comparing the raw values while their contact is inactive can split
    otherwise compatible trajectories according to an old, irrelevant
    contact.

    Keep the public/raw ``contact_key`` untouched: this normalisation is only
    for splice compatibility and its associated distance calculation.
    """

    contact_key = tuple(getattr(point, "contact_key"))
    if len(contact_key) < 6:
        raise TypeError("splice contact_key must contain contact-normal state")
    normalised = list(contact_key)
    if not bool(normalised[2]):
        normalised[3] = 0
    if bool(normalised[1]):
        normalised[4] = 0
        normalised[5] = 0
    return tuple(normalised)


def splice_match_key(point: object) -> SpliceMatchKey:
    """Return the exact contact/route key required at a splice seam.

    Gold is deliberately absent: it normally does not affect player physics
    and is handled by the highscore predictor and final canonical evaluation.
    """

    return (
        splice_contact_key(point),
        getattr(point, "exploded_mine_mask"),
        getattr(point, "open_exit_mask"),
        getattr(point, "opened_locked_door_mask"),
        getattr(point, "triggered_trapdoor_mask"),
    )


def _point_is_live_and_finite(point: object) -> bool:
    return (
        not bool(getattr(point, "dead"))
        and not bool(getattr(point, "complete"))
        and all(
            math.isfinite(float(getattr(point, name)))
            for name in ("x", "y", "vx", "vy")
        )
    )


@dataclass(frozen=True, slots=True)
class PreparedSpliceMatchGroup:
    """One exact route/contact group ordered for x-window scans."""

    key: SpliceMatchKey
    points_by_x: tuple[object, ...]
    xs: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.points_by_x) != len(self.xs):
            raise ValueError("splice match-group points/x arrays differ in size")

    def x_bounds(self, centre: float, tolerance: float) -> tuple[int, int]:
        """Return the half-open slice containing every possible x match."""

        return (
            bisect_left(self.xs, centre - tolerance),
            bisect_right(self.xs, centre + tolerance),
        )

    def iter_x_window(
        self,
        centre: float,
        tolerance: float,
        *,
        start_tick: int = 0,
        end_tick: int | None = None,
    ) -> Iterator[object]:
        """Yield x-compatible points, optionally constrained by tick."""

        first, last = self.x_bounds(centre, tolerance)
        for point in self.points_by_x[first:last]:
            tick = int(getattr(point, "tick"))
            if tick < start_tick or (end_tick is not None and tick > end_tick):
                continue
            yield point


@dataclass(frozen=True, slots=True)
class PreparedSpliceTrace:
    """Materialised and indexed state for one round population member.

    All containers use ordinary tuples/dicts so the value can cross a
    ``ProcessPoolExecutor`` boundary.  The dicts are built once and then
    treated as immutable.  Point objects are shared by reference between the
    trace, tick map and route groups; pickle memoisation therefore serialises
    each point only once per job payload.
    """

    source: object | None
    trace: tuple[object, ...]
    ticks: tuple[int, ...]
    points_by_tick: dict[int, object]
    eligible_points: tuple[object, ...]
    eligible_ticks: tuple[int, ...]
    match_groups: dict[SpliceMatchKey, PreparedSpliceMatchGroup]
    jump_edges: tuple[int, ...]
    frames: tuple[object, ...] | None
    input_codes: tuple[int, ...] | None
    final_gold_mask: int
    gold_bonus_ticks: int

    def __post_init__(self) -> None:
        if len(self.trace) != len(self.ticks):
            raise ValueError("prepared splice trace points/ticks differ in size")
        if len(self.eligible_points) != len(self.eligible_ticks):
            raise ValueError(
                "prepared splice eligible points/ticks differ in size"
            )

    def materialize_trace(self) -> tuple[object, ...]:
        """Compatibility surface for existing trajectory consumers."""

        return self.trace

    def __reduce__(self):
        """Cross process boundaries without serialising a native owner.

        A source ``AutoEvaluation`` may still own a ``NativeTraceView`` when
        preparation happens inside a worker.  Every datum needed by splice
        planning is already present below, so intentionally drop ``source``
        from the payload instead of asking pickle to traverse that owner.
        """

        return (
            _restore_prepared_splice_trace,
            (
                self.trace,
                self.ticks,
                self.points_by_tick,
                self.eligible_points,
                self.eligible_ticks,
                self.match_groups,
                self.jump_edges,
                self.frames,
                self.input_codes,
                self.final_gold_mask,
                self.gold_bonus_ticks,
            ),
        )

    def point(self, tick: int) -> object | None:
        return self.points_by_tick.get(tick)

    def eligible_between(
        self,
        start_tick: int = 0,
        end_tick: int | None = None,
    ) -> tuple[object, ...]:
        """Return live finite points inside an inclusive tick range."""

        first = bisect_left(self.eligible_ticks, start_tick)
        last = (
            len(self.eligible_ticks)
            if end_tick is None
            else bisect_right(self.eligible_ticks, end_tick)
        )
        return self.eligible_points[first:last]

    def match_group(
        self,
        key: SpliceMatchKey,
    ) -> PreparedSpliceMatchGroup | None:
        return self.match_groups.get(key)

    @property
    def native_analysis(self) -> object | None:
        """Expose the source native buffer when preparation happened in-worker."""

        trace = getattr(self.source, "trace", None)
        return getattr(trace, "analysis", None)


def _restore_prepared_splice_trace(
    trace: tuple[object, ...],
    ticks: tuple[int, ...],
    points_by_tick: dict[int, object],
    eligible_points: tuple[object, ...],
    eligible_ticks: tuple[int, ...],
    match_groups: dict[SpliceMatchKey, PreparedSpliceMatchGroup],
    jump_edges: tuple[int, ...],
    frames: tuple[object, ...] | None,
    input_codes: tuple[int, ...] | None,
    final_gold_mask: int,
    gold_bonus_ticks: int,
) -> PreparedSpliceTrace:
    return PreparedSpliceTrace(
        source=None,
        trace=trace,
        ticks=ticks,
        points_by_tick=points_by_tick,
        eligible_points=eligible_points,
        eligible_ticks=eligible_ticks,
        match_groups=match_groups,
        jump_edges=jump_edges,
        frames=frames,
        input_codes=input_codes,
        final_gold_mask=final_gold_mask,
        gold_bonus_ticks=gold_bonus_ticks,
    )


def _materialize_source_trace(
    analysis: object,
    point_converter: Callable[[Sequence[object]], object] | None,
) -> tuple[object, ...]:
    materialize = getattr(analysis, "materialize_trace", None)
    if callable(materialize):
        raw_trace = materialize()
    elif isinstance(analysis, Sequence):
        raw_trace = analysis
    else:
        raise TypeError(
            "splice analysis must expose materialize_trace() or be a trace sequence"
        )

    points: list[object] = []
    for row in raw_trace:
        point = row
        if not hasattr(point, "tick"):
            if point_converter is None or not isinstance(row, Sequence):
                raise TypeError(
                    "splice trace rows must expose tick or use point_converter"
                )
            point = point_converter(row)
        # Fail here, once per member, rather than obscurely inside a pair scan.
        for name in (
            "tick",
            "x",
            "y",
            "vx",
            "vy",
            "dead",
            "complete",
            "contact_key",
            "collected_gold_mask",
            "exploded_mine_mask",
            "open_exit_mask",
            "opened_locked_door_mask",
            "triggered_trapdoor_mask",
            "gold_bonus_ticks",
            "previous_jump_held",
        ):
            if not hasattr(point, name):
                raise TypeError(f"splice trace point is missing {name}")
        points.append(point)
    points.sort(key=lambda point: int(getattr(point, "tick")))
    return tuple(points)


def _prepare_jump_edges(
    analysis: object,
    trace: Sequence[object],
    frames: tuple[object, ...] | None,
) -> tuple[int, ...]:
    if frames is not None:
        edges: list[int] = []
        previous_jump = False
        for tick, frame in enumerate(frames):
            current_jump = bool(getattr(frame, "jump"))
            if current_jump and not previous_jump:
                edges.append(tick)
            previous_jump = current_jump
        return tuple(edges)

    raw_edges = getattr(analysis, "jump_edges", None)
    if callable(raw_edges):
        raw_edges = raw_edges()
    if raw_edges is not None:
        try:
            return tuple(
                sorted({int(tick) for tick in raw_edges if int(tick) >= 0})
            )
        except TypeError:
            pass

    inferred: list[int] = []
    previous: object | None = None
    for point in trace:
        if (
            previous is not None
            and bool(getattr(point, "previous_jump_held"))
            and not bool(getattr(previous, "previous_jump_held"))
        ):
            inferred.append(int(getattr(point, "tick")))
        previous = point
    return tuple(inferred)


def _prepare_gold_summary(
    analysis: object,
    trace: Sequence[object],
) -> tuple[int, int]:
    final_mask = getattr(analysis, "final_gold_mask", None)
    final_bonus = getattr(analysis, "gold_bonus_ticks", None)
    if final_mask is not None and final_bonus is not None:
        return int(final_mask), int(final_bonus)

    summary = getattr(analysis, "summary", None)
    if callable(summary):
        raw_summary = summary()
        if isinstance(raw_summary, Sequence) and len(raw_summary) >= 9:
            return int(raw_summary[8]), int(raw_summary[7])

    if trace:
        final_point = trace[-1]
        return (
            int(getattr(final_point, "collected_gold_mask")),
            int(getattr(final_point, "gold_bonus_ticks")),
        )
    return 0, 0


def prepare_splice_trace(
    analysis: object,
    frames: Sequence[object] | None = None,
    *,
    point_converter: Callable[[Sequence[object]], object] | None = None,
) -> PreparedSpliceTrace:
    """Prepare the member-local data reused by every ordered splice pair.

    Calling this with an already prepared value is free when no replacement
    frame stream is supplied.  Production Auto evaluations already expose
    public point objects; ``point_converter`` exists for low-level native-row
    callers and tests without coupling this module back to ``nv14_auto``.
    """

    if isinstance(analysis, PreparedSpliceTrace):
        if frames is None or frames is analysis.frames:
            return analysis

    if isinstance(analysis, PreparedSpliceTrace):
        source = analysis.source
        trace = analysis.trace
    else:
        source = analysis
        trace = _materialize_source_trace(analysis, point_converter)

    prepared_frames = (
        frames
        if isinstance(frames, tuple)
        else None if frames is None else tuple(frames)
    )
    ticks = tuple(int(getattr(point, "tick")) for point in trace)
    if len(set(ticks)) != len(ticks):
        raise ValueError("splice trace contains duplicate ticks")
    points_by_tick = {
        int(getattr(point, "tick")): point for point in trace
    }
    eligible_points = tuple(
        point for point in trace if _point_is_live_and_finite(point)
    )
    eligible_ticks = tuple(
        int(getattr(point, "tick")) for point in eligible_points
    )

    grouped: dict[SpliceMatchKey, list[object]] = {}
    for point in eligible_points:
        grouped.setdefault(splice_match_key(point), []).append(point)
    match_groups: dict[SpliceMatchKey, PreparedSpliceMatchGroup] = {}
    for key, points in grouped.items():
        points.sort(
            key=lambda point: (
                float(getattr(point, "x")),
                int(getattr(point, "tick")),
            )
        )
        points_by_x = tuple(points)
        match_groups[key] = PreparedSpliceMatchGroup(
            key=key,
            points_by_x=points_by_x,
            xs=tuple(float(getattr(point, "x")) for point in points_by_x),
        )

    final_gold_mask, gold_bonus_ticks = _prepare_gold_summary(source, trace)
    input_codes = (
        None
        if prepared_frames is None
        else tuple(
            int(bool(getattr(frame, "left")))
            | (int(bool(getattr(frame, "right"))) << 1)
            | (int(bool(getattr(frame, "jump"))) << 2)
            for frame in prepared_frames
        )
    )
    return PreparedSpliceTrace(
        source=source,
        trace=trace,
        ticks=ticks,
        points_by_tick=points_by_tick,
        eligible_points=eligible_points,
        eligible_ticks=eligible_ticks,
        match_groups=match_groups,
        jump_edges=_prepare_jump_edges(source, trace, prepared_frames),
        frames=prepared_frames,
        input_codes=input_codes,
        final_gold_mask=final_gold_mask,
        gold_bonus_ticks=gold_bonus_ticks,
    )


__all__ = (
    "PreparedSpliceMatchGroup",
    "PreparedSpliceTrace",
    "SpliceMatchKey",
    "prepare_splice_trace",
    "splice_contact_key",
    "splice_match_key",
)

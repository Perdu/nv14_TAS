from __future__ import annotations

from types import SimpleNamespace

import nv14_auto as auto
from nv14_auto import AutoEvaluation, CompactTracePoint, find_baseline_alignment
from nv14_engine import InputFrame


def _point(
    tick: int,
    x: float,
    *,
    exits: int = 0,
    locked: int = 0,
    traps: int = 0,
) -> CompactTracePoint:
    return CompactTracePoint(
        tick=tick,
        x=x,
        y=100.0,
        vx=1.0,
        vy=0.0,
        player_state=0,
        in_air=False,
        near_wall=False,
        wall_x=0,
        floor_x=0,
        floor_y=0,
        previous_jump_held=False,
        jump_events=0,
        collected_gold_mask=0,
        exploded_mine_mask=0,
        open_exit_mask=exits,
        opened_locked_door_mask=locked,
        triggered_trapdoor_mask=traps,
        complete=False,
        dead=False,
    )


def _evaluation(
    points: tuple[CompactTracePoint, ...],
    *,
    completed_exit_index: int | None = None,
    finish_tick: int | None = None,
) -> AutoEvaluation:
    return AutoEvaluation(
        finish_tick=finish_tick,
        dead_tick=None,
        last_tick=points[-1].tick,
        trace=points,
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
        completed_exit_index=completed_exit_index,
    )


def test_route_control_target_reports_missing_lock_and_unwanted_trap() -> None:
    reference = _evaluation(
        (
            _point(0, 0.0),
            _point(1, 1.0, locked=1 << 4),
        )
    )
    missing_lock = _evaluation((_point(0, 0.0), _point(1, 1.0)))
    target = auto._find_route_control_repair_target(missing_lock, reference)
    assert target is not None
    assert target.candidate_tick == 1
    assert target.required_locked_door_mask == 1 << 4

    no_trap_reference = _evaluation((_point(0, 0.0), _point(1, 1.0)))
    triggered_trap = _evaluation(
        (_point(0, 0.0), _point(1, 1.0, traps=1 << 22))
    )
    target = auto._find_route_control_repair_target(
        triggered_trap, no_trap_reference
    )
    assert target is not None
    assert target.candidate_tick == 1
    assert target.forbidden_trapdoor_mask == 1 << 22


def test_alignment_requires_only_actual_completion_exit_for_auto() -> None:
    completion_bit = 1 << 1
    baseline = _evaluation(
        (
            _point(0, 0.0),
            _point(1, 10.0, exits=completion_bit),
            _point(2, 11.0, exits=completion_bit),
        ),
        completed_exit_index=1,
    )
    extra_optional_exit = _evaluation(
        (
            _point(0, 10.0, exits=completion_bit | 1),
            _point(1, 11.0, exits=completion_bit | 1),
        )
    )
    match = find_baseline_alignment(
        extra_optional_exit,
        baseline,
        max_alignment=1,
        reference_completion_exit_index=baseline.completed_exit_index,
    )
    assert match is not None
    assert not match.static_matches

    missing_completion_exit = _evaluation(
        (_point(0, 10.0, exits=1), _point(1, 11.0, exits=1))
    )
    assert (
        find_baseline_alignment(
            missing_completion_exit,
            baseline,
            max_alignment=1,
            reference_completion_exit_index=baseline.completed_exit_index,
        )
        is None
    )


def test_beam_route_control_repair_handles_no_missed_jump(monkeypatch) -> None:
    """A route-control-only beam retime must not index an empty miss tuple."""
    exit_bit = 1 << 0
    reference = _evaluation(
        (
            _point(0, 0.0),
            _point(1, 1.0, exits=exit_bit),
        ),
        completed_exit_index=0,
        finish_tick=1,
    )
    route_control_only_failure = _evaluation(
        (
            _point(0, 0.0),
            _point(1, 1.0),
        )
    )
    evaluations = iter((reference, reference, route_control_only_failure))

    def fake_evaluate(*_args, **_kwargs):
        try:
            return next(evaluations)
        except StopIteration as exc:  # pragma: no cover - guards test assumptions
            raise AssertionError("unexpected extra macro evaluation") from exc

    class DeterministicRandom:
        def random(self) -> float:
            return 0.0  # Always select the incumbent best candidate.

        def randrange(self, _stop: int) -> int:
            return 0

        def randint(self, start: int, _stop: int) -> int:
            return start

        def choice(self, values):
            return values[-1]

    def reject_boundary_retime(*_args, **_kwargs):
        # Keep the available seam for the suffix-retime turn while explicitly
        # skipping the earlier single-boundary turn. Candidate transition
        # metadata is cached in v2.45, so call-count staging is no longer a
        # stable way to distinguish those operators.
        raise ValueError("skip boundary retime")

    repair_calls: list[dict[str, int]] = []

    def record_repair(*_args, **kwargs):
        repair_calls.append(
            {
                "failure_tick": kwargs["failure_tick"],
                "required_exit_mask": kwargs["required_exit_mask"],
            }
        )
        return None, 0, 0

    monkeypatch.setattr(auto, "_evaluate_working", fake_evaluate)
    monkeypatch.setattr(auto, "verify_trimmed_replay", lambda *_a, **_k: reference)
    monkeypatch.setattr(auto, "valid_retime_mutations", lambda *_a, **_k: ())
    monkeypatch.setattr(auto, "_semantic_jump_variants", lambda *_a, **_k: ())
    monkeypatch.setattr(auto, "input_transition_frames", lambda _frames: (0,))
    monkeypatch.setattr(
        auto, "apply_single_transition_retime", reject_boundary_retime
    )
    monkeypatch.setattr(
        auto,
        "apply_suffix_retime",
        lambda frames, _mutation: [InputFrame() for _ in frames],
    )
    monkeypatch.setattr(auto, "repair_direction_window", record_repair)
    monkeypatch.setattr(auto.random, "Random", lambda _seed: DeterministicRandom())

    level = SimpleNamespace(static_world=SimpleNamespace(gold_count=0))
    result = auto.optimise_autonomous(
        level,
        [InputFrame(right=True)],
        auto.AutoConfig(
            iterations=3,
            beam_width=4,
            max_retime=1,
            repair_window=1,
            repair_lookback=1,
            max_jump_shift=0,
            max_jump_hold_delta=0,
            cheap_pulse_limit=0,
            all_input_repair=False,
        ),
    )

    assert result.finish_tick == 1
    assert repair_calls == [
        {"failure_tick": 0, "required_exit_mask": exit_bit}
    ]


def test_frame_ahead_repair_multiplier_is_shared_with_all_input_fallback(
    monkeypatch,
) -> None:
    """A measured trajectory lead expands one shared per-attempt allowance."""
    exit_bit = 1 << 0
    reference = _evaluation(
        (
            _point(0, 0.0),
            _point(1, 1.0, exits=exit_bit),
        ),
        completed_exit_index=0,
        finish_tick=1,
    )
    route_control_only_failure = _evaluation(
        (
            _point(0, 0.0),
            _point(1, 1.0),
        )
    )
    evaluations = iter((reference, reference, route_control_only_failure))

    def fake_evaluate(*_args, **_kwargs):
        try:
            return next(evaluations)
        except StopIteration as exc:  # pragma: no cover - guards test assumptions
            raise AssertionError("unexpected extra macro evaluation") from exc

    class DeterministicRandom:
        def random(self) -> float:
            return 0.0

        def randrange(self, _stop: int) -> int:
            return 0

        def randint(self, start: int, _stop: int) -> int:
            return start

        def choice(self, values):
            return values[-1]

    def reject_boundary_retime(*_args, **_kwargs):
        raise ValueError("skip boundary retime")

    direction_limits: list[int] = []
    fallback_limits: list[int] = []

    def record_direction(*_args, **kwargs):
        direction_limits.append(kwargs["config"].repair_local_limit)
        return None, 0, 3_000

    def record_fallback(*_args, **kwargs):
        fallback_limits.append(kwargs["config"].repair_local_limit)
        return None, 0, 7_000

    monkeypatch.setattr(auto, "_evaluate_working", fake_evaluate)
    monkeypatch.setattr(auto, "verify_trimmed_replay", lambda *_a, **_k: reference)
    monkeypatch.setattr(auto, "valid_retime_mutations", lambda *_a, **_k: ())
    monkeypatch.setattr(auto, "_semantic_jump_variants", lambda *_a, **_k: ())
    monkeypatch.setattr(auto, "input_transition_frames", lambda _frames: (0,))
    monkeypatch.setattr(
        auto, "apply_single_transition_retime", reject_boundary_retime
    )
    monkeypatch.setattr(
        auto,
        "apply_suffix_retime",
        lambda frames, _mutation: [InputFrame() for _ in frames],
    )
    monkeypatch.setattr(
        auto,
        "find_baseline_alignment",
        lambda *_a, **_k: auto.AlignmentMatch(
            candidate_tick=0,
            reference_tick=1,
            offset=1,
            distance=0.0,
            contact_matches=True,
            static_matches=True,
            score_lead=1,
        ),
    )
    monkeypatch.setattr(auto, "repair_direction_window", record_direction)
    monkeypatch.setattr(auto, "repair_all_input_window", record_fallback)
    monkeypatch.setattr(auto.random, "Random", lambda _seed: DeterministicRandom())

    level = SimpleNamespace(static_world=SimpleNamespace(gold_count=0))
    result = auto.optimise_autonomous(
        level,
        [InputFrame(right=True)],
        auto.AutoConfig(
            iterations=3,
            beam_width=4,
            max_retime=1,
            repair_window=1,
            repair_lookback=1,
            repair_local_limit=1_000,
            frame_ahead_repair_multiplier=10,
            max_jump_shift=0,
            max_jump_hold_delta=0,
            cheap_pulse_limit=0,
        ),
    )

    assert result.finish_tick == 1
    assert direction_limits == [10_000]
    assert fallback_limits == [7_000]
    assert result.stats.local_simulations == 10_000

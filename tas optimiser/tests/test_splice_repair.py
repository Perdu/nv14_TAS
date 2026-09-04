from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import nv14_auto as auto


def _point(
    tick: int,
    *,
    x: float | None = None,
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
        in_air=True,
        near_wall=False,
        wall_x=0,
        floor_x=0,
        floor_y=0,
        previous_jump_held=False,
        jump_events=0,
        collected_gold_mask=0,
        exploded_mine_mask=0,
        open_exit_mask=0,
        opened_locked_door_mask=0,
        triggered_trapdoor_mask=0,
        complete=complete,
        dead=dead,
    )


def _evaluation(
    last_tick: int,
    *,
    finish_tick: int | None = None,
    dead_tick: int | None = None,
    successful_jumps: tuple[int, ...] = (),
    jump_edges: tuple[int, ...] = (),
    missed_jump_edges: tuple[int, ...] = (),
    x_for_tick=None,
) -> auto.AutoEvaluation:
    return auto.AutoEvaluation(
        finish_tick=finish_tick,
        dead_tick=dead_tick,
        last_tick=last_tick,
        trace=tuple(
            _point(
                tick,
                x=(None if x_for_tick is None else x_for_tick(tick)),
                complete=tick == finish_tick,
                dead=tick == dead_tick,
            )
            for tick in range(last_tick + 1)
        ),
        successful_jumps=successful_jumps,
        jump_edges=jump_edges,
        missed_jump_edges=missed_jump_edges,
    )


def _working(count: int) -> tuple[auto.InputFrame, ...]:
    return tuple(auto.InputFrame() for _ in range(count)) + (
        auto.NEUTRAL_INPUT,
    )


def _candidate(
    evaluation: auto.AutoEvaluation,
    *,
    working: tuple[auto.InputFrame, ...] | None = None,
    sentinel_verified: bool = True,
) -> auto.AutoCandidate:
    fixed = _working(20) if working is None else working
    return auto.AutoCandidate(
        working_frames=fixed,
        evaluation=evaluation,
        origin="test",
        sentinel_verified=sentinel_verified,
        replay_key=auto._frame_key(fixed),
    )


def _plan():
    return SimpleNamespace(
        recipient_entry_tick=2,
        donor_entry_tick=2,
        recipient_exit_tick=8,
        donor_exit_tick=6,
        predicted_time_gain=2,
    )


def _offset_plan():
    return SimpleNamespace(
        recipient_entry_tick=2,
        donor_entry_tick=4,
        recipient_exit_tick=8,
        donor_exit_tick=8,
        predicted_time_gain=2,
    )


def test_splice_acceptance_uses_campaign_outcome_not_predicted_gain() -> None:
    recipient = _candidate(
        replace(
            _evaluation(100, finish_tick=100),
            pre_finish_exit_distance=20.0,
        ),
        working=_working(100),
    )
    predicted_six = SimpleNamespace(predicted_time_gain=6)
    faster_by_five = _candidate(
        replace(
            _evaluation(95, finish_tick=95),
            pre_finish_exit_distance=10.0,
        ),
        working=_working(95),
    )
    closer_same_tick = _candidate(
        replace(
            _evaluation(100, finish_tick=100),
            pre_finish_exit_distance=5.0,
        ),
        working=_working(100),
    )

    speedrun = auto.AutoConfig(iterations=0)
    assert auto._splice_acceptance_rejection(
        faster_by_five,
        recipient,
        predicted_six,
        speedrun,
        required_gold_mask=0,
    ) is None
    assert auto._splice_acceptance_rejection(
        closer_same_tick,
        recipient,
        predicted_six,
        speedrun,
        required_gold_mask=0,
    ) is None

    highscore = auto.AutoConfig(
        iterations=0,
        objective=auto.AUTO_OBJECTIVE_HIGHSCORE,
    )
    gold_recipient = _candidate(
        replace(
            recipient.evaluation,
            gold_bonus_ticks=auto.GOLD_BONUS_TICKS,
            final_gold_mask=1,
        ),
        working=_working(100),
    )
    assert auto._splice_acceptance_rejection(
        faster_by_five,
        gold_recipient,
        predicted_six,
        highscore,
        required_gold_mask=0,
    ) == "completed splice did not improve the selected campaign outcome"


def test_piecewise_reference_uses_the_inputs_which_produce_each_state() -> None:
    recipient = _evaluation(
        12,
        successful_jumps=(1, 2, 3, 8, 12),
        missed_jump_edges=(0, 9),
    )
    donor = _evaluation(
        12,
        successful_jumps=(4, 5, 6, 8, 9),
        missed_jump_edges=(7,),
    )

    legs = auto.build_splice_piecewise_reference(
        recipient,
        donor,
        _offset_plan(),
    )

    assert [
        (leg.child_start, leg.child_end, leg.reference_offset)
        for leg in legs
    ] == [(0, 2, 0), (3, 6, 2), (7, None, 2)]
    assert auto.map_piecewise_reference_events(
        legs,
        lambda evaluation: evaluation.successful_jumps,
    ) == (1, 2, 3, 4, 6, 10)
    assert auto.map_piecewise_reference_events(
        legs,
        lambda evaluation: evaluation.missed_jump_edges,
    ) == (0, 5, 7)


def test_piecewise_missed_jump_detection_maps_donor_and_suffix_events() -> None:
    recipient = _evaluation(12, successful_jumps=(1, 3, 8, 12))
    donor = _evaluation(12, successful_jumps=(4, 5, 6, 8, 9))
    legs = auto.build_splice_piecewise_reference(
        recipient,
        donor,
        _offset_plan(),
    )
    candidate = _evaluation(
        10,
        jump_edges=(1, 3, 4, 6, 10),
        successful_jumps=(1, 3, 6),
    )

    assert auto.detect_piecewise_missed_jumps(legs, candidate) == (4, 10)


@pytest.mark.parametrize(
    "alignment_found",
    (True, False),
    ids=("cached-match", "cached-none"),
)
def test_splice_snapshot_reuses_the_candidate_suffix_alignment_result(
    monkeypatch: pytest.MonkeyPatch,
    alignment_found: bool,
) -> None:
    recipient = _candidate(_evaluation(12, finish_tick=12))
    donor = _candidate(_evaluation(12, finish_tick=12))
    child_evaluation = _evaluation(10, dead_tick=10)
    legs = auto.build_splice_piecewise_reference(
        recipient.evaluation,
        donor.evaluation,
        _plan(),
    )
    alignment = (
        auto.AlignmentMatch(
            candidate_tick=9,
            reference_tick=11,
            offset=2,
            distance=0.25,
            contact_matches=True,
            static_matches=True,
            score_lead=2,
        )
        if alignment_found
        else None
    )
    alignment_scans = 0

    def fake_find_alignment(*_args, **_kwargs):
        nonlocal alignment_scans
        alignment_scans += 1
        return alignment

    monkeypatch.setattr(auto, "_evaluate_working", lambda *_a, **_k: child_evaluation)
    monkeypatch.setattr(auto, "_find_splice_suffix_alignment", fake_find_alignment)
    config = auto.AutoConfig(iterations=1)
    repair_spec = auto.SpliceRepairSpec()

    candidate = auto._evaluate_splice_candidate(
        object(),
        _working(20),
        parent=recipient,
        recipient_working=recipient.working_frames,
        piecewise_reference=legs,
        config=config,
        repair_spec=repair_spec,
        max_body_length=20,
        origin="test-splice",
        description="test splice",
    )
    snapshot = auto._splice_progress_snapshot(
        candidate,
        legs,
        config,
        repair_spec,
    )

    assert alignment_scans == 1
    assert candidate.alignment is alignment
    assert snapshot.suffix_lead == (2 if alignment_found else None)
    assert snapshot.frame_ahead is alignment_found


def test_primary_repairs_can_reuse_a_supplied_seed_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = _working(5)
    seed_evaluation = _evaluation(5)
    changed = list(seed)
    changed[0] = auto.InputFrame(jump=True)
    monkeypatch.setattr(
        auto,
        "_jump_repair_variants",
        lambda *_a, **_k: ((tuple(changed), 0, "test jump edit"),),
    )

    def reject_resimulation(*_args, **_kwargs):
        raise AssertionError("supplied seed evaluation was not reused")

    monkeypatch.setattr(auto, "_evaluate_working", reject_resimulation)
    config = auto.AutoConfig(iterations=1)

    assert auto.repair_jump_mutation_lookback(
        object(),
        seed,
        seed_evaluation,
        seed_evaluation=seed_evaluation,
        failure_tick=3,
        reference_offset=0,
        config=config,
        require_failure_jump=False,
    ) == (None, 0, 0)
    assert auto.repair_direction_window(
        object(),
        seed,
        seed_evaluation,
        seed_evaluation=seed_evaluation,
        failure_tick=3,
        reference_offset=0,
        config=config,
        require_failure_jump=False,
    ) == (None, 0, 0)


def test_repair_controller_preserves_seeded_order_and_shared_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []
    primary_seed_evaluations: list[auto.AutoEvaluation] = []

    def record_jump(*_args, **kwargs):
        calls.append(("jump", kwargs["config"].repair_local_limit))
        primary_seed_evaluations.append(kwargs["seed_evaluation"])
        return None, 1, 3

    def record_direction(*_args, **kwargs):
        calls.append(("direction", kwargs["config"].repair_local_limit))
        primary_seed_evaluations.append(kwargs["seed_evaluation"])
        return None, 1, 4

    def record_all(*_args, **kwargs):
        calls.append(("all-input", kwargs["config"].repair_local_limit))
        return None, 1, 3

    monkeypatch.setattr(auto, "repair_jump_mutation_lookback", record_jump)
    monkeypatch.setattr(auto, "repair_direction_window", record_direction)
    monkeypatch.setattr(auto, "repair_all_input_window", record_all)
    evaluation = _evaluation(4)
    config = auto.AutoConfig(
        iterations=1,
        seed=0,
        repair_local_limit=10,
        frame_ahead_repair_multiplier=1,
    )

    outcome = auto._RepairController(object(), config).attempt(
        _candidate(evaluation, working=_working(5), sentinel_verified=False),
        evaluation,
        failure_tick=4,
        reference_offset=0,
        repair_number=1,
        label="test repair",
    )

    assert calls == [
        ("jump", 10),
        ("direction", 7),
        ("all-input", 3),
    ]
    assert outcome.local_branches == 3
    assert outcome.local_simulations == 10
    assert outcome.jump_repair_attempts == 1
    assert outcome.all_input_repairs == 1
    assert len(primary_seed_evaluations) == 2
    assert all(seed is evaluation for seed in primary_seed_evaluations)


def test_junction_repair_families_share_allowance_without_starvation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    def record_jump(_level, working, *_args, **kwargs):
        calls.append(("jump", kwargs["config"].repair_local_limit))
        proposal = list(working)
        proposal[0] = auto.InputFrame(right=True)
        kwargs["score_observer"](5.0)
        return tuple(proposal), 1, 3

    def record_direction(*_args, **kwargs):
        calls.append(("direction", kwargs["config"].repair_local_limit))
        return None, 1, 4

    def record_transition(_level, working, *_args, **kwargs):
        calls.append(
            ("strategic-transition", kwargs["config"].repair_local_limit)
        )
        proposal = list(working)
        proposal[0] = auto.InputFrame(left=True)
        kwargs["score_observer"](10.0)
        return tuple(proposal), 1, 2

    def record_all(*_args, **kwargs):
        calls.append(("all-input", kwargs["config"].repair_local_limit))
        return None, 1, 3

    monkeypatch.setattr(auto, "repair_jump_mutation_lookback", record_jump)
    monkeypatch.setattr(auto, "repair_direction_window", record_direction)
    monkeypatch.setattr(
        auto,
        "repair_strategic_transition_lookback",
        record_transition,
    )
    monkeypatch.setattr(auto, "repair_all_input_window", record_all)
    evaluation = _evaluation(4)
    config = auto.AutoConfig(
        iterations=1,
        seed=0,
        repair_local_limit=12,
        frame_ahead_repair_multiplier=1,
    )

    outcome = auto._RepairController(object(), config).attempt(
        _candidate(evaluation, working=_working(5), sentinel_verified=False),
        evaluation,
        failure_tick=4,
        reference_offset=0,
        repair_number=1,
        label="junction repair",
        strategic=True,
        strategic_transition_search=True,
    )

    assert calls == [
        ("strategic-transition", 3),
        ("jump", 4),
        ("direction", 4),
        ("all-input", 3),
    ]
    assert outcome.local_branches == 4
    assert outcome.local_simulations == 12
    assert outcome.repair_method == "jump mutation"
    assert outcome.working_frames is not None
    assert outcome.working_frames[0] == auto.InputFrame(right=True)


@pytest.mark.parametrize(
    ("override", "observed_limits", "expected_simulations"),
    ((5, [2, 2, 1], 5), (None, [0, 0, 0], 21)),
)
def test_strategic_tier_honours_campaign_override_and_unlimited_zero(
    monkeypatch: pytest.MonkeyPatch,
    override: int | None,
    observed_limits: list[int],
    expected_simulations: int,
) -> None:
    calls: list[int] = []

    def record_family(*_args, **kwargs):
        limit = kwargs["config"].repair_local_limit
        calls.append(limit)
        return None, 1, limit or 7

    monkeypatch.setattr(
        auto,
        "repair_strategic_transition_lookback",
        record_family,
    )
    monkeypatch.setattr(auto, "repair_direction_window", record_family)
    monkeypatch.setattr(auto, "repair_all_input_window", record_family)
    evaluation = _evaluation(4)
    outcome = auto._RepairController(
        object(),
        auto.AutoConfig(
            iterations=1,
            repair_local_limit=0,
            max_jump_shift=0,
            max_jump_hold_delta=0,
        ),
    ).attempt(
        _candidate(evaluation, working=_working(5), sentinel_verified=False),
        evaluation,
        failure_tick=4,
        reference_offset=0,
        repair_number=1,
        label="junction repair",
        strategic=True,
        strategic_transition_search=True,
        local_limit_override=override,
    )

    assert calls == observed_limits
    assert outcome.local_simulations == expected_simulations


def test_strategic_transition_keeps_legal_local_retime_and_moved_jump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neutral = auto.InputFrame()
    jumping_right = auto.InputFrame(right=True, jump=True)
    body = (
        neutral,
        neutral,
        jumping_right,
        jumping_right,
        auto.InputFrame(left=True),
    )
    working = body + (auto.NEUTRAL_INPUT,)
    evaluation = _evaluation(5, jump_edges=(2,), missed_jump_edges=(2,))
    captured = []
    observed_requirements = {}

    def capture_patches(_level, _seed, patches, **kwargs):
        captured.extend(patches)
        observed_requirements.update(kwargs)
        candidates = tuple(
            SimpleNamespace(feasible=False) for _patch in patches
        )
        return SimpleNamespace(
            candidates=candidates,
            budget_exhausted=False,
            stats=SimpleNamespace(branches=len(patches), simulated_ticks=0),
        )

    monkeypatch.setattr(auto, "_native_patch_evaluation", capture_patches)
    proposal, _, _ = auto.repair_strategic_transition_lookback(
        object(),
        working,
        evaluation,
        seed_evaluation=evaluation,
        failure_tick=2,
        reference_offset=0,
        config=auto.AutoConfig(
            iterations=1,
            max_retime=1,
            repair_window=2,
            repair_lookback=4,
            repair_local_limit=20,
            range_start=0,
            range_end=4,
        ),
    )

    assert proposal is None
    assert any(
        len(patch) == 1
        and patch[0].frame == 2
        and patch[0].input == neutral
        for patch in captured
    )
    assert 3 in observed_requirements["required_jump_frames"]
    assert observed_requirements["required_jump_any"]
    assert observed_requirements["prune_inactive_jump"]


def test_route_control_requirements_preserve_caller_masks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def record_direction(*_args, **kwargs):
        captured.update(kwargs)
        return None, 0, 0

    monkeypatch.setattr(
        auto,
        "_find_route_control_repair_target",
        lambda *_args, **_kwargs: SimpleNamespace(
            candidate_tick=2,
            required_exit_mask=0b10,
            required_locked_door_mask=0b100,
            forbidden_trapdoor_mask=0b1000,
            label="test control",
        ),
    )
    monkeypatch.setattr(auto, "repair_direction_window", record_direction)
    evaluation = _evaluation(4)
    auto._RepairController(
        object(),
        auto.AutoConfig(
            iterations=1,
            max_jump_shift=0,
            max_jump_hold_delta=0,
            all_input_repair=False,
        ),
    ).attempt(
        _candidate(evaluation, working=_working(5), sentinel_verified=False),
        evaluation,
        failure_tick=4,
        reference_offset=0,
        repair_number=1,
        label="route repair",
        required_exit_mask=0b1,
        required_locked_door_mask=0b10,
        forbidden_trapdoor_mask=0b100,
    )

    assert captured["required_exit_mask"] == 0b11
    assert captured["required_locked_door_mask"] == 0b110
    assert captured["forbidden_trapdoor_mask"] == 0b1100


def test_splice_campaign_clamps_attempt_to_remaining_local_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipient = _candidate(_evaluation(12, finish_tick=12))
    donor = _candidate(_evaluation(12, finish_tick=12))
    evaluation_calls = 0
    snapshot_calls = 0
    overrides: list[int | None] = []

    def fake_evaluate_candidate(_level, working, **_kwargs):
        nonlocal evaluation_calls
        evaluation_calls += 1
        evaluation = _evaluation(3 + evaluation_calls, dead_tick=3 + evaluation_calls)
        return _candidate(
            evaluation,
            working=tuple(working),
            sentinel_verified=False,
        )

    def fake_snapshot(*_args, **_kwargs):
        nonlocal snapshot_calls
        snapshot_calls += 1
        return auto._SpliceProgressSnapshot(
            first_failure=1,
            last_tick=snapshot_calls,
            exit_alignment_distance=float(100 - snapshot_calls),
            suffix_lead=None,
            mapped_misses=(),
            route_control_target=None,
            frame_ahead=False,
        )

    def fake_attempt(self, candidate, reference, **kwargs):
        override = kwargs["local_limit_override"]
        overrides.append(override)
        simulations = min(2, override) if override is not None else 2
        proposal = list(candidate.working_frames)
        proposal[len(overrides) - 1] = auto.InputFrame(right=True)
        return auto._RepairAttemptOutcome(
            working_frames=tuple(proposal),
            repair_method="direction",
            failure_tick=1,
            label="entry bridge",
            local_branches=1,
            local_simulations=simulations,
            jump_repair_attempts=0,
            all_input_repairs=0,
            route_control_repair=False,
            route_control_target=None,
            frame_ahead_active=False,
        )

    monkeypatch.setattr(auto, "_evaluate_splice_candidate", fake_evaluate_candidate)
    monkeypatch.setattr(auto, "_splice_progress_snapshot", fake_snapshot)
    monkeypatch.setattr(auto, "_splice_junction_suffix_run", lambda *_a, **_k: 4)
    monkeypatch.setattr(auto._RepairController, "attempt", fake_attempt)
    plan = SimpleNamespace(
        **vars(_plan()),
        junction=True,
        junction_validation_run_length=4,
    )
    result = auto.repair_reference_segment_splice(
        object(),
        recipient,
        donor,
        plan,
        config=auto.AutoConfig(
            iterations=1,
            repair_local_limit=0,
            repair_campaign_local_limit=3,
        ),
        max_body_length=20,
    )

    assert overrides == [3, 1]
    assert result.local_simulations == 3
    assert result.rejection_reason == (
        "splice repair campaign local budget exhausted"
    )


def test_splice_campaign_widens_entry_bridge_then_accepts_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipient = _candidate(_evaluation(12, finish_tick=12))
    donor = _candidate(_evaluation(12, finish_tick=12))
    raw_evaluation = _evaluation(
        4,
        dead_tick=4,
        x_for_tick=lambda tick: tick if tick < 3 else tick + 100,
    )
    intermediate_evaluation = _evaluation(5, dead_tick=5)
    completed_evaluation = _evaluation(
        10,
        finish_tick=10,
        x_for_tick=lambda tick: tick + 2 if tick >= 7 else tick,
    )
    evaluation_calls = 0
    snapshot_calls = 0

    def fake_evaluate_candidate(_level, working, **kwargs):
        nonlocal evaluation_calls
        evaluation_calls += 1
        evaluation = (
            raw_evaluation
            if evaluation_calls == 1
            else intermediate_evaluation
            if evaluation_calls == 2
            else completed_evaluation
        )
        return _candidate(
            evaluation,
            working=tuple(working),
            sentinel_verified=evaluation.finish_tick is not None,
        )

    attempts: list[dict[str, int | None]] = []

    def fake_attempt(self, candidate, reference, **kwargs):
        attempts.append(
            {
                "range_start": self.config.range_start,
                "range_end": self.config.range_end,
                "reference_offset": kwargs["reference_offset"],
                "child_start": kwargs["candidate_start_tick"],
                "child_end": kwargs["candidate_end_tick"],
            }
        )
        proposal = None
        if len(attempts) >= 2:
            proposal = list(candidate.working_frames)
            proposal[len(attempts) - 2] = auto.InputFrame(right=True)
            proposal = tuple(proposal)
        return auto._RepairAttemptOutcome(
            working_frames=proposal,
            repair_method=(None if proposal is None else "direction"),
            failure_tick=4,
            label="entry bridge",
            local_branches=1,
            local_simulations=5,
            jump_repair_attempts=0,
            all_input_repairs=0,
            route_control_repair=False,
            route_control_target=None,
            frame_ahead_active=False,
        )

    monkeypatch.setattr(auto, "_evaluate_splice_candidate", fake_evaluate_candidate)
    monkeypatch.setattr(auto._RepairController, "attempt", fake_attempt)
    real_snapshot = auto._splice_progress_snapshot

    def count_snapshot(*args, **kwargs):
        nonlocal snapshot_calls
        snapshot_calls += 1
        return real_snapshot(*args, **kwargs)

    monkeypatch.setattr(auto, "_splice_progress_snapshot", count_snapshot)

    result = auto.repair_reference_segment_splice(
        object(),
        recipient,
        donor,
        _plan(),
        config=auto.AutoConfig(iterations=1),
        max_body_length=20,
        repair_spec=auto.SpliceRepairSpec(
            initial_bridge_window=2,
            maximum_bridge_window=4,
        ),
    )

    assert result.accepted is True
    assert result.candidate.finish_tick == 10
    assert result.attempts == 3
    assert result.local_simulations == 15
    # Raw, retained intermediate, and completed states are each scanned once;
    # the next loop iteration consumes the preceding state's stored snapshot.
    assert snapshot_calls == 3
    assert [(call["range_start"], call["range_end"]) for call in attempts] == [
        (1, 4),
        (0, 6),
        (3, 6),
    ]
    assert all(call["reference_offset"] == 0 for call in attempts)
    assert all(call["child_start"] == 3 for call in attempts)
    assert all(call["child_end"] == 6 for call in attempts)
    assert any("widened editable seam window" in line for line in result.diagnostics)


def test_splice_campaign_can_continue_past_24_attempts_within_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipient = _candidate(_evaluation(12, finish_tick=12))
    donor = _candidate(_evaluation(12, finish_tick=12))
    evaluation_calls = 0
    snapshot_calls = 0
    attempts = 0

    def fake_evaluate_candidate(_level, working, **_kwargs):
        nonlocal evaluation_calls
        evaluation_calls += 1
        completed = evaluation_calls == 26
        evaluation = (
            _evaluation(10, finish_tick=10)
            if completed
            else _evaluation(4, dead_tick=4)
        )
        return _candidate(
            evaluation,
            working=tuple(working),
            sentinel_verified=completed,
        )

    def fake_snapshot(*_args, **_kwargs):
        nonlocal snapshot_calls
        snapshot_calls += 1
        return auto._SpliceProgressSnapshot(
            first_failure=1,
            last_tick=snapshot_calls,
            exit_alignment_distance=float(100 - snapshot_calls),
            suffix_lead=None,
            mapped_misses=(),
            route_control_target=None,
            frame_ahead=False,
        )

    def fake_attempt(self, candidate, reference, **_kwargs):
        nonlocal attempts
        attempts += 1
        proposal = list(candidate.working_frames)
        for bit in range(5):
            proposal[bit] = auto.InputFrame(right=bool(attempts & (1 << bit)))
        return auto._RepairAttemptOutcome(
            working_frames=tuple(proposal),
            repair_method="direction",
            failure_tick=1,
            label="entry bridge",
            local_branches=1,
            local_simulations=1,
            jump_repair_attempts=0,
            all_input_repairs=0,
            route_control_repair=False,
            route_control_target=None,
            frame_ahead_active=False,
        )

    monkeypatch.setattr(auto, "_evaluate_splice_candidate", fake_evaluate_candidate)
    monkeypatch.setattr(auto, "_splice_progress_snapshot", fake_snapshot)
    monkeypatch.setattr(auto._RepairController, "attempt", fake_attempt)

    result = auto.repair_reference_segment_splice(
        object(),
        recipient,
        donor,
        _plan(),
        config=auto.AutoConfig(
            iterations=1,
            repair_campaign_local_limit=100,
            splice_repair_revisit_limit=30,
        ),
        max_body_length=20,
    )

    assert result.accepted is True
    assert result.attempts == 25
    assert result.local_simulations == 25
    assert not hasattr(auto.SpliceRepairSpec(), "maximum_attempts")


def test_splice_repair_spec_rejects_invalid_windows() -> None:
    with pytest.raises(ValueError, match="maximum_bridge_window"):
        auto.SpliceRepairSpec(
            initial_bridge_window=4,
            maximum_bridge_window=3,
        )
    with pytest.raises(ValueError, match="failure_region_revisit_limit"):
        auto.SpliceRepairSpec(failure_region_revisit_limit=0)

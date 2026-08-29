from __future__ import annotations

import math

import pytest

import nv14_auto as auto
from nv14_auto import (
    NEUTRAL_INPUT,
    AlignmentMatch,
    AutoCandidate,
    AutoConfig,
    AutoEvaluation,
    AutoStats,
    CompactTracePoint,
    apply_reference_suffix_splice,
    detect_shifted_missed_jumps,
    evaluate_replay_with_sentinel,
    find_baseline_alignment,
    mutate_jump_pulse,
    optimise_autonomous,
    pre_finish_exit_edge_distance,
    verify_trimmed_replay,
)
from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    parse_level_string,
)
from nv14_replay import RetimeMutation


def _empty_map() -> str:
    return "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)


def _two_contact_exit_level():
    # Switch and door occupy the same cell.  Removing the switch stops that
    # cell's linked-list traversal, so the door is first tested one tick later.
    return parse_level_string(f"{_empty_map()}|5^100,100!11^101,100,100,100")


def _running_exit_level():
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    # Level map serialization is x-major.  This floor has tile centres y=156,
    # so a radius-10 ninja is supported at y=134.
    for x in range(APP_NUM_GRIDCOLS):
        chars[x * APP_NUM_GRIDROWS + 5] = "1"
    return parse_level_string(
        f"{''.join(chars)}|5^60,134!11^140,134,60,134"
    )


def _same_tick_completion_and_death_level():
    # Tick 0 hits the exit switch, whose self-removal stops current-cell
    # traversal and inserts the door at the head.  Tick 1 therefore hits the
    # door first (completing the level), then the mine later in the same live
    # collision traversal (killing the ninja on the completion tick).
    return parse_level_string(
        f"{_empty_map()}|5^115,100!12^115,100!11^115,100,115,100"
    )


def _held_key(frames):
    return tuple((frame.left, frame.right, frame.jump) for frame in frames)


def _trace_point(tick: int, x: float, *, gold_mask: int = 0) -> CompactTracePoint:
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
        collected_gold_mask=gold_mask,
        exploded_mine_mask=0,
        open_exit_mask=0,
        complete=False,
        dead=False,
    )


def test_completed_evaluation_records_pre_sentinel_exit_distance() -> None:
    level = _two_contact_exit_level()
    evaluation = evaluate_replay_with_sentinel(level, [InputFrame()])

    assert evaluation.finish_tick == 1
    assert evaluation.completed_exit_index == 0
    pre_sentinel = evaluation.point(0)
    assert pre_sentinel is not None
    door = level.static_world.entry_for_ref(level.static_world.exit_door_ref(0))
    assert door is not None
    expected = math.hypot(door.x - pre_sentinel.x, door.y - pre_sentinel.y)
    assert evaluation.pre_finish_exit_distance == pytest.approx(expected, abs=1e-12)


def test_pre_finish_exit_edge_distance_reports_remaining_collision_gap() -> None:
    level = _running_exit_level()
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    evaluation = evaluate_replay_with_sentinel(level, source)

    assert evaluation.finish_tick == 34
    door = level.static_world.entry_for_ref(level.static_world.exit_door_ref(0))
    assert door is not None
    expected = max(
        0.0,
        evaluation.pre_finish_exit_distance - level.player.r - door.r,
    )
    assert pre_finish_exit_edge_distance(level, evaluation) == pytest.approx(
        expected, abs=1e-12
    )
    assert expected == pytest.approx(2.799439917578567, abs=1e-12)


def test_same_finish_closer_candidate_outranks_source_only_for_saved_best() -> None:
    terminal = CompactTracePoint(
        tick=100,
        x=100.0,
        y=100.0,
        vx=0.0,
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
        open_exit_mask=1,
        complete=True,
        dead=False,
    )

    def completed(distance: float, finish_tick: int = 100) -> AutoEvaluation:
        return AutoEvaluation(
            finish_tick=finish_tick,
            dead_tick=None,
            last_tick=finish_tick,
            trace=(terminal,),
            successful_jumps=(),
            jump_edges=(),
            missed_jump_edges=(),
            completed_exit_index=0,
            pre_finish_exit_distance=distance,
        )

    source = AutoCandidate(
        working_frames=(NEUTRAL_INPUT,),
        evaluation=completed(20.0),
        origin="source",
        edit_count=0,
    )
    closer = AutoCandidate(
        working_frames=(NEUTRAL_INPUT,),
        evaluation=completed(15.0),
        origin="candidate",
        edit_count=5,
        generation=2,
    )
    earlier_but_farther = AutoCandidate(
        working_frames=(NEUTRAL_INPUT,),
        evaluation=completed(1000.0, finish_tick=99),
        origin="candidate",
        edit_count=20,
        generation=3,
    )

    # Preserve v2.42's beam/frontier ordering: edit count still wins a same-time tie.
    assert auto._candidate_key(source, 100) < auto._candidate_key(closer, 100)
    # But the checkpoint/final-best ordering now keeps the closer tick-99 state.
    assert auto._best_candidate_key(closer, 100) < auto._best_candidate_key(source, 100)
    # Finish time remains the primary objective regardless of proximity.
    assert (
        auto._best_candidate_key(earlier_but_farther, 100)
        < auto._best_candidate_key(closer, 100)
    )


def test_completion_tick_is_zero_based_neutral_sentinel_index() -> None:
    level = _two_contact_exit_level()
    evaluation = evaluate_replay_with_sentinel(level, [InputFrame()])

    assert evaluation.valid
    assert evaluation.finish_tick == 1
    assert evaluation.last_tick == 1
    assert [point.tick for point in evaluation.trace] == [0, 1]
    # The public finish tick is the serialized body length even though two
    # simulation steps (input 0 and sentinel 1) were executed.
    verify_trimmed_replay(level, [InputFrame()], expected_finish_tick=1)


def test_evaluator_adds_exactly_one_sentinel_not_unbounded_postroll() -> None:
    evaluation = evaluate_replay_with_sentinel(_two_contact_exit_level(), [])

    assert not evaluation.valid
    assert evaluation.finish_tick is None
    assert evaluation.last_tick == 0
    assert len(evaluation.trace) == 1


def test_completion_wins_over_death_on_the_same_tick() -> None:
    level = _same_tick_completion_and_death_level()
    frames = [InputFrame()]

    evaluation = evaluate_replay_with_sentinel(level, frames)

    assert evaluation.finish_tick == 1
    assert evaluation.dead_tick == 1
    assert evaluation.trace[-1].complete
    assert evaluation.trace[-1].dead
    assert evaluation.valid
    verified = verify_trimmed_replay(level, frames, expected_finish_tick=1)
    assert verified.valid


def test_auto_baseline_accepts_same_tick_completion_and_death() -> None:
    level = _same_tick_completion_and_death_level()
    frames = [InputFrame()]

    result = optimise_autonomous(
        level,
        frames,
        AutoConfig(iterations=0, beam_width=2),
    )

    assert result.baseline_finish_tick == 1
    assert result.finish_tick == 1
    assert result.best.output_valid
    assert result.best.evaluation.dead_tick == 1


def test_reference_suffix_splice_continues_after_both_post_step_states() -> None:
    left = InputFrame(left=True)
    right = InputFrame(right=True)
    candidate = (left, InputFrame(), InputFrame(), NEUTRAL_INPUT)
    reference = (InputFrame(), InputFrame(), right, NEUTRAL_INPUT)
    match = AlignmentMatch(0, 1, 1, 0.0, True, True)

    result = apply_reference_suffix_splice(candidate, reference, match)

    assert _held_key(result) == _held_key((left, right, NEUTRAL_INPUT, NEUTRAL_INPUT))
    assert all(frame.jump_trigger is None for frame in result)


def test_shifted_successful_jump_diagnosis_uses_events_and_seam_mapping() -> None:
    candidate = AutoEvaluation(
        finish_tick=None,
        dead_tick=None,
        last_tick=8,
        trace=(),
        successful_jumps=(0, 8),
        jump_edges=(0, 3, 8),
        missed_jump_edges=(3,),
    )

    assert detect_shifted_missed_jumps(
        (0, 4, 9), candidate, RetimeMutation(4, -1)
    ) == (3,)
    # The +2-shifted event is beyond the simulated candidate and is ignored.
    assert detect_shifted_missed_jumps(
        (1, 7), candidate, RetimeMutation(7, 2)
    ) == ()


def test_jump_pulse_supports_combined_start_and_hold_edit() -> None:
    working = (
        InputFrame(right=True, jump=True),
        InputFrame(right=True, jump=True),
        InputFrame(right=True, jump=True),
        InputFrame(right=True),
        NEUTRAL_INPUT,
    )

    moved = mutate_jump_pulse(
        working, 0, start_delta=1, hold_delta=-1
    )

    assert [frame.jump for frame in moved] == [False, True, True, False, False]
    assert all(frame.right for frame in moved[:-1])


def test_baseline_does_not_claim_a_false_positive_alignment_to_itself() -> None:
    level = _running_exit_level()
    frames = [InputFrame()] * 5 + [InputFrame(right=True)] * 40
    evaluation = evaluate_replay_with_sentinel(level, frames)

    assert evaluation.valid
    assert find_baseline_alignment(evaluation, evaluation, max_alignment=3) is None


def test_alignment_detects_stable_future_offset_and_bounds_large_scan() -> None:
    baseline = AutoEvaluation(
        finish_tick=None,
        dead_tick=None,
        last_tick=4,
        trace=tuple(_trace_point(tick, float(tick)) for tick in range(5)),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
    )
    candidate = AutoEvaluation(
        finish_tick=None,
        dead_tick=None,
        last_tick=3,
        trace=tuple(
            _trace_point(tick, float(tick + 1), gold_mask=1)
            for tick in range(4)
        ),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
    )

    match = find_baseline_alignment(
        candidate,
        baseline,
        max_alignment=1_000_000_000,
    )

    assert match is not None
    assert (match.candidate_tick, match.reference_tick, match.offset) == (3, 4, 1)
    assert not match.static_matches


def test_beam_reserves_capacity_for_aligned_failed_frontier() -> None:
    valid_evaluation = AutoEvaluation(
        finish_tick=5,
        dead_tick=None,
        last_tick=5,
        trace=(_trace_point(5, 5.0),),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
    )
    frontier_evaluation = AutoEvaluation(
        finish_tick=None,
        dead_tick=None,
        last_tick=4,
        trace=(_trace_point(4, 5.0),),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
    )
    valid = [
        AutoCandidate(
            working_frames=(NEUTRAL_INPUT,),
            evaluation=valid_evaluation,
            origin=f"valid-{index}",
            generation=index,
            edit_count=index,
        )
        for index in range(5)
    ]
    frontier = AutoCandidate(
        working_frames=(NEUTRAL_INPUT,),
        evaluation=frontier_evaluation,
        origin="frontier",
        alignment=AlignmentMatch(4, 5, 1, 0.0, True, True),
    )
    config = AutoConfig(
        iterations=0,
        beam_width=4,
        diversity_per_bucket=10,
    )

    selected = auto._select_diverse_beam((*valid, frontier), config, 5)

    assert len(selected) == 4
    assert frontier in selected


def test_zero_budget_verifies_and_trims_source_on_its_sentinel() -> None:
    level = _running_exit_level()
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80

    result = optimise_autonomous(
        level,
        source,
        AutoConfig(
            iterations=0,
            beam_width=4,
            max_retime=1,
            repair_window=2,
            repair_lookback=2,
            max_jump_shift=0,
            max_jump_hold_delta=0,
        ),
    )

    assert result.baseline_finish_tick == 34
    assert result.finish_tick == 34
    assert len(result.frames) == 34
    assert not result.improved
    assert result.stats.macro_evaluations == 0
    assert verify_trimmed_replay(level, result.frames).finish_tick == 34


def test_raw_suffix_retime_finds_small_improvement_deterministically() -> None:
    level = _running_exit_level()
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    config = AutoConfig(
        iterations=1,
        beam_width=4,
        max_retime=1,
        seed=123,
        repair_window=2,
        repair_lookback=2,
        max_jump_shift=0,
        max_jump_hold_delta=0,
    )

    first = optimise_autonomous(level, source, config)
    second = optimise_autonomous(level, source, config)

    assert (first.baseline_finish_tick, first.finish_tick) == (34, 33)
    assert len(first.frames) == first.finish_tick
    assert _held_key(first.frames) == _held_key(second.frames)
    assert first.stats.macro_evaluations == 1


def test_v255_seeded_auto_search_preserves_exact_schedule() -> None:
    """v2.89 keeps this seeded run's public incumbent schedule stable."""
    level = _running_exit_level()
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    progress = []
    checkpoints = []

    result = optimise_autonomous(
        level,
        source,
        AutoConfig(iterations=10, beam_width=2, seed=0),
        progress=lambda update: progress.append(
            (
                update.phase,
                update.macro_evaluations,
                update.best_finish_tick,
                update.repair_index,
                update.campaign_index,
            )
        ),
        best_callback=lambda candidate: checkpoints.append(
            candidate.finish_tick
        ),
    )

    assert result.baseline_finish_tick == 34
    assert result.finish_tick == 30
    assert result.frames == (
        InputFrame(),
        *(InputFrame(right=True) for _ in range(29)),
    )
    assert result.best.mutations == (
        "boundary 5 -2",
        "suffix 3 -2",
    )
    assert checkpoints == [33, 32, 31, 30]
    assert result.stats == AutoStats(
        macro_candidates=10,
        macro_evaluations=10,
        local_branches=3,
        local_simulations=54,
        raw_retimes=2,
        boundary_retimes=1,
        suffix_splices=0,
        jump_mutations=1,
        pulse_mutations=2,
        direction_mutations=3,
        repair_attempts=1,
        jump_repair_attempts=1,
        all_input_repairs=0,
        successful_repairs=0,
        reference_epochs=4,
        deduplicated=0,
        gold_repair_attempts=0,
        successful_gold_repairs=0,
        route_control_repair_attempts=0,
        successful_route_control_repairs=0,
        structured_repair_attempts=0,
        beam_quick_repair_attempts=1,
        beam_strategic_repair_attempts=0,
        repair_campaigns=1,
        repair_campaign_attempts=1,
        repair_frontiers_queued=3,
        repair_frontiers_dropped=1,
    )
    assert progress == [
        ("baseline", 0, None, 0, 0),
        ("baseline", 0, 34, 0, 0),
        ("raw-retime", 0, 34, 0, 0),
        ("raw-retime", 1, 33, 0, 0),
        ("cheap-pulse", 1, 33, 0, 0),
        ("beam", 2, 33, 0, 0),
        ("jump-repair", 5, 33, 1, 1),
        ("jump-repair", 5, 33, 1, 1),
        ("beam", 7, 32, 0, 0),
        ("beam", 8, 31, 0, 0),
        ("beam", 9, 30, 0, 0),
        ("complete", 10, 30, 0, 0),
    ]


def test_disabling_deterministic_phase_starts_directly_with_beam(
    monkeypatch,
) -> None:
    """Beam-only runs must not plan or execute any structured bootstrap work."""

    def unexpected_structured_work(*_args, **_kwargs):
        raise AssertionError("deterministic proposal generation was not skipped")

    monkeypatch.setattr(
        auto, "valid_retime_mutations", unexpected_structured_work
    )
    monkeypatch.setattr(
        auto, "_semantic_jump_variants", unexpected_structured_work
    )
    phases: list[str] = []
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80

    result = optimise_autonomous(
        _running_exit_level(),
        source,
        AutoConfig(
            iterations=4,
            beam_width=4,
            seed=0,
            deterministic_phase=False,
        ),
        progress=lambda update: phases.append(update.phase),
    )

    structured_phases = {
        "raw-retime",
        "raw-repair",
        "cheap-pulse",
        "jump",
        "jump-retime",
        "deep-repair",
        "deferred-retime",
    }
    assert result.stats.macro_evaluations > 0
    assert "beam" in phases
    assert structured_phases.isdisjoint(phases)


def test_v213_removes_the_campaign_attempt_cap() -> None:
    config = AutoConfig(iterations=0)
    assert not hasattr(config, "repair_chain_limit")
    assert not hasattr(auto, "_planned_campaign_repairs")
    with pytest.raises(TypeError, match="repair_chain_limit"):
        AutoConfig(iterations=0, repair_chain_limit=6)


def test_invalid_config_and_incomplete_source_are_rejected() -> None:
    with pytest.raises(ValueError):
        AutoConfig(iterations=-1)
    with pytest.raises(ValueError):
        AutoConfig(beam_width=0)
    with pytest.raises(ValueError):
        AutoConfig(max_retime=0)
    with pytest.raises(ValueError):
        AutoConfig(alignment_position_tolerance=math.inf)
    with pytest.raises(ValueError, match="trace_stride must be 1"):
        AutoConfig(trace_stride=2)

    no_exit = parse_level_string(f"{_empty_map()}|5^100,100")
    with pytest.raises(ValueError, match="source replay"):
        optimise_autonomous(no_exit, [InputFrame()] * 3, AutoConfig(iterations=0))

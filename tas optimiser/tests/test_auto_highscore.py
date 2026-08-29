from __future__ import annotations

import pytest

import nv14_auto as auto
from nv14_auto import (
    AUTO_OBJECTIVE_HIGHSCORE,
    AutoCandidate,
    AutoConfig,
    AutoEvaluation,
    CompactTracePoint,
    auto_objective_value,
    evaluate_replay_with_sentinel,
    find_baseline_alignment,
    optimise_autonomous,
    verify_trimmed_replay,
)
from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    parse_level_string,
)
from nv14_replay import decode_complex_replay, editable_frames, encode_complex_replay


def _floor_level(*, with_gold: bool = False):
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    objects = "5^60,134!"
    if with_gold:
        objects += "0^100,134!"
    objects += "11^140,134,60,134"
    return parse_level_string(f"{''.join(chars)}|{objects}")


def _floor_level_with_gold_at(
    x: float,
    y: float,
    *,
    exit_x: float = 140,
):
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    objects = f"5^60,134!0^{x},{y}!11^{exit_x},134,60,134"
    return parse_level_string(f"{''.join(chars)}|{objects}")


def _point(
    tick: int,
    x: float,
    *,
    gold_mask: int = 0,
    gold_bonus_ticks: int = 0,
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
        collected_gold_mask=gold_mask,
        exploded_mine_mask=0,
        open_exit_mask=0,
        complete=False,
        dead=False,
        gold_bonus_ticks=gold_bonus_ticks,
    )


def _completed_evaluation(
    finish_tick: int,
    gold_bonus_ticks: int,
    gold_mask: int,
    *,
    pre_finish_exit_distance: float | None = None,
) -> AutoEvaluation:
    return AutoEvaluation(
        finish_tick=finish_tick,
        dead_tick=None,
        last_tick=finish_tick,
        trace=(
            _point(
                finish_tick,
                0.0,
                gold_mask=gold_mask,
                gold_bonus_ticks=gold_bonus_ticks,
            ),
        ),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
        final_gold_mask=gold_mask,
        gold_bonus_ticks=gold_bonus_ticks,
        pre_finish_exit_distance=pre_finish_exit_distance,
    )


def test_highscore_objective_uses_exact_80_tick_gold_tradeoff() -> None:
    baseline = _completed_evaluation(100, 80, 0b1)
    cases = [
        (_completed_evaluation(21, 0, 0), -1),  # 79 faster: one point worse
        (_completed_evaluation(20, 0, 0), 0),   # 80 faster: exact tie
        (_completed_evaluation(19, 0, 0), 1),   # 81 faster: one point better
        (_completed_evaluation(179, 160, 0b11), 1),  # extra gold, 79 slower
        (_completed_evaluation(180, 160, 0b11), 0),  # extra gold, 80 slower
    ]
    baseline_value = auto_objective_value(baseline, AUTO_OBJECTIVE_HIGHSCORE)
    assert baseline_value == -20
    for candidate, expected_delta in cases:
        assert (
            auto_objective_value(candidate, AUTO_OBJECTIVE_HIGHSCORE)
            - baseline_value
            == expected_delta
        )


def test_highscore_candidate_key_prefers_score_but_retains_source_on_tie() -> None:
    source_evaluation = _completed_evaluation(100, 80, 0b1)
    better_evaluation = _completed_evaluation(179, 160, 0b11)
    tied_evaluation = _completed_evaluation(20, 0, 0)
    source = AutoCandidate(
        working_frames=(InputFrame(),),
        evaluation=source_evaluation,
        origin="source",
        edit_count=0,
    )
    better = AutoCandidate(
        working_frames=(InputFrame(),),
        evaluation=better_evaluation,
        origin="candidate",
        edit_count=3,
    )
    tied = AutoCandidate(
        working_frames=(InputFrame(),),
        evaluation=tied_evaluation,
        origin="candidate",
        edit_count=1,
    )

    source_key = auto._candidate_key(
        source,
        100,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        reference_gold_mask=0b1,
    )
    better_key = auto._candidate_key(
        better,
        100,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        reference_gold_mask=0b1,
    )
    tied_key = auto._candidate_key(
        tied,
        100,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        reference_gold_mask=0b1,
    )

    assert better_key < source_key
    assert source_key < tied_key


def test_highscore_saved_best_uses_exit_proximity_after_score() -> None:
    source = AutoCandidate(
        working_frames=(InputFrame(),),
        evaluation=_completed_evaluation(
            100,
            80,
            0b1,
            pre_finish_exit_distance=20.0,
        ),
        origin="source",
        edit_count=0,
    )
    closer_tie = AutoCandidate(
        working_frames=(InputFrame(),),
        evaluation=_completed_evaluation(
            20,
            0,
            0,
            pre_finish_exit_distance=15.0,
        ),
        origin="candidate",
        edit_count=5,
        generation=2,
    )
    higher_score_but_farther = AutoCandidate(
        working_frames=(InputFrame(),),
        evaluation=_completed_evaluation(
            19,
            0,
            0,
            pre_finish_exit_distance=1000.0,
        ),
        origin="candidate",
        edit_count=20,
        generation=3,
    )

    # Preserve the existing highscore beam/frontier ordering.
    assert auto._candidate_key(
        source,
        100,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        reference_gold_mask=0b1,
    ) < auto._candidate_key(
        closer_tie,
        100,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        reference_gold_mask=0b1,
    )
    # Persisted/final-best selection now keeps the closer equal-score run.
    assert auto._best_candidate_key(
        closer_tie,
        100,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        reference_gold_mask=0b1,
    ) < auto._best_candidate_key(
        source,
        100,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        reference_gold_mask=0b1,
    )
    # Highscore value remains the primary objective regardless of proximity.
    assert auto._best_candidate_key(
        higher_score_but_farther,
        100,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        reference_gold_mask=0b1,
    ) < auto._best_candidate_key(
        closer_tie,
        100,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        reference_gold_mask=0b1,
    )


def test_strict_reference_gold_rejects_a_faster_score_improving_skip() -> None:
    baseline = _completed_evaluation(100, 80, 0b1)
    skipped = _completed_evaluation(19, 0, 0)
    config = AutoConfig(
        iterations=0,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        require_reference_gold=True,
    )

    assert not auto._objective_no_worse(
        skipped,
        baseline,
        config,
        required_gold_mask=baseline.final_gold_mask,
    )


def test_highscore_alignment_can_be_raw_time_behind_but_score_ahead() -> None:
    baseline = AutoEvaluation(
        finish_tick=None,
        dead_tick=None,
        last_tick=5,
        trace=tuple(_point(tick, float(tick)) for tick in range(6)),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
    )
    candidate = AutoEvaluation(
        finish_tick=None,
        dead_tick=None,
        last_tick=4,
        trace=tuple(
            _point(
                tick,
                float(max(0, tick - 2)),
                gold_mask=0b1,
                gold_bonus_ticks=80,
            )
            for tick in range(5)
        ),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
        final_gold_mask=0b1,
        gold_bonus_ticks=80,
    )

    match = find_baseline_alignment(
        candidate,
        baseline,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        max_alignment=3,
        max_negative_alignment=3,
    )

    assert match is not None
    assert match.offset == -2
    assert match.score_lead == 78


def test_highscore_alignment_keeps_raw_lead_when_missed_gold_makes_score_worse() -> None:
    baseline = AutoEvaluation(
        finish_tick=None,
        dead_tick=None,
        last_tick=4,
        trace=tuple(
            _point(
                tick,
                float(tick),
                gold_mask=0b1,
                gold_bonus_ticks=80,
            )
            for tick in range(5)
        ),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
        final_gold_mask=0b1,
        gold_bonus_ticks=80,
    )
    candidate = AutoEvaluation(
        finish_tick=None,
        dead_tick=None,
        last_tick=3,
        trace=tuple(
            _point(tick, float(tick + 1))
            for tick in range(4)
        ),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
    )

    match = find_baseline_alignment(
        candidate,
        baseline,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        max_alignment=2,
        max_negative_alignment=2,
    )

    assert match is not None
    assert match.offset == 1
    assert match.score_lead == -79


def test_highscore_evaluation_records_gold_mask_bonus_and_event_tick() -> None:
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    evaluation = evaluate_replay_with_sentinel(
        _floor_level(with_gold=True), source
    )

    assert evaluation.valid
    assert evaluation.finish_tick == 34
    assert evaluation.final_gold_mask == 0b1
    assert evaluation.gold_bonus_ticks == 80
    assert evaluation.gold_count == 1
    assert [(event.gold_index, event.tick) for event in evaluation.gold_events] == [
        (0, 23)
    ]
    assert evaluation.highscore_value == 46


def test_highscore_zero_budget_keeps_verified_source_with_extended_workspace() -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    level = parse_level_string(
        f"{''.join(chars)}|"
        "5^60,134!0^100,134!0^35,134!11^140,134,60,134"
    )
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    result = optimise_autonomous(
        level,
        source,
        AutoConfig(
            iterations=0,
            objective=AUTO_OBJECTIVE_HIGHSCORE,
            range_start=100,
            range_end=100,
        ),
    )

    assert result.objective == AUTO_OBJECTIVE_HIGHSCORE
    assert result.baseline_finish_tick == result.finish_tick == 34
    assert result.baseline_gold_mask == result.gold_mask == 0b1
    assert result.baseline_gold_bonus_ticks == result.gold_bonus_ticks == 80
    assert result.baseline_objective_value == result.objective_value == 46
    assert not result.improved
    assert len(result.frames) == 34
    verify_trimmed_replay(
        level,
        result.frames,
        expected_finish_tick=34,
        expected_gold_mask=0b1,
        expected_gold_bonus_ticks=80,
    )


def test_highscore_auto_can_choose_a_slower_route_for_extra_gold() -> None:
    level = _floor_level_with_gold_at(100, 117)
    source = [InputFrame(right=True)] * 100

    result = optimise_autonomous(
        level,
        source,
        AutoConfig(
            iterations=50,
            beam_width=32,
            seed=0,
            objective=AUTO_OBJECTIVE_HIGHSCORE,
        ),
    )

    assert result.baseline_finish_tick == 29
    assert result.baseline_gold_count == 0
    assert result.baseline_objective_value == -29
    # The exact-opportunity policy deliberately changes which legal insertion
    # a seeded run tries.  Keep this regression about the highscore guarantee,
    # rather than pinning an incidental stochastic route timing.
    assert result.finish_tick is not None
    assert result.finish_tick > result.baseline_finish_tick
    assert result.gold_count == 1
    assert result.gold_bonus_ticks == 80
    assert result.objective_value > result.baseline_objective_value
    assert result.improved
    assert len(result.frames) > result.baseline_finish_tick
    packed_frames = editable_frames(
        decode_complex_replay(encode_complex_replay(result.frames)).frames
    )
    verify_trimmed_replay(
        level,
        packed_frames,
        expected_finish_tick=result.finish_tick,
        expected_gold_mask=0b1,
        expected_gold_bonus_ticks=80,
    )

    no_slow_completions = optimise_autonomous(
        level,
        source,
        AutoConfig(
            iterations=50,
            beam_width=32,
            seed=0,
            objective=AUTO_OBJECTIVE_HIGHSCORE,
            max_extra_ticks=0,
        ),
    )
    assert no_slow_completions.finish_tick == 29
    assert no_slow_completions.gold_count == 0


def test_highscore_auto_keeps_reference_gold_when_skipping_it_scores_worse() -> None:
    level = _floor_level_with_gold_at(35, 134)
    source = [InputFrame(left=True)] * 9 + [InputFrame(right=True)] * 120

    result = optimise_autonomous(
        level,
        source,
        AutoConfig(
            iterations=150,
            beam_width=32,
            seed=0,
            objective=AUTO_OBJECTIVE_HIGHSCORE,
        ),
    )

    assert result.baseline_gold_mask == 0b1
    assert result.gold_mask == 0b1
    assert result.objective_value >= result.baseline_objective_value
    assert result.finish_tick < result.baseline_finish_tick


def test_strict_reference_gold_changes_end_to_end_highscore_selection() -> None:
    level = _floor_level_with_gold_at(250, 134, exit_x=90)
    source = [
        InputFrame(right=True, jump=tick == 0)
        for tick in range(80)
    ] + [InputFrame(left=True)] * 250

    ordinary = optimise_autonomous(
        level,
        source,
        AutoConfig(
            iterations=5,
            beam_width=16,
            seed=0,
            objective=AUTO_OBJECTIVE_HIGHSCORE,
        ),
    )
    strict = optimise_autonomous(
        level,
        source,
        AutoConfig(
            iterations=5,
            beam_width=16,
            seed=0,
            objective=AUTO_OBJECTIVE_HIGHSCORE,
            require_reference_gold=True,
        ),
    )

    assert ordinary.baseline_finish_tick == 163
    assert ordinary.baseline_gold_mask == 0b1
    assert ordinary.finish_tick == 11
    assert ordinary.gold_mask == 0
    assert ordinary.objective_value > ordinary.baseline_objective_value
    assert strict.gold_mask & strict.baseline_gold_mask == strict.baseline_gold_mask
    assert strict.finish_tick > ordinary.finish_tick
    assert strict.objective_value >= strict.baseline_objective_value


def test_gold_recovery_is_not_gated_by_a_repair_bank() -> None:
    level = _floor_level_with_gold_at(35, 134)
    source = [InputFrame(left=True)] * 9 + [InputFrame(right=True)] * 120
    config = AutoConfig(
        iterations=50,
        beam_width=32,
        seed=0,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
    )

    result = optimise_autonomous(level, source, config)

    assert result.stats.gold_repair_attempts > 0
    assert result.stats.successful_gold_repairs > 0
    assert not hasattr(result.stats, "repair_tokens_refilled")
    assert not hasattr(result.stats, "repair_bonus_tokens")


def test_highscore_config_defaults_to_one_gold_horizon() -> None:
    highscore = AutoConfig(iterations=0, objective=AUTO_OBJECTIVE_HIGHSCORE)
    assert highscore.effective_max_extra_ticks == 80

    with pytest.raises(ValueError, match="speedrun objective"):
        AutoConfig(iterations=0, max_extra_ticks=1)


def test_default_extra_workspace_collapses_when_source_has_every_gold() -> None:
    level = _floor_level(with_gold=True)
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80

    with pytest.raises(ValueError, match="verified replay body"):
        optimise_autonomous(
            level,
            source,
            AutoConfig(
                iterations=0,
                objective=AUTO_OBJECTIVE_HIGHSCORE,
                range_start=100,
                range_end=100,
            ),
        )

    explicit = optimise_autonomous(
        level,
        source,
        AutoConfig(
            iterations=0,
            objective=AUTO_OBJECTIVE_HIGHSCORE,
            max_extra_ticks=80,
            range_start=100,
            range_end=100,
        ),
    )
    assert explicit.finish_tick == 34


def test_no_gold_highscore_uses_the_exact_speedrun_search_schedule() -> None:
    level = _floor_level()
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    common = dict(
        iterations=50,
        beam_width=16,
        seed=0,
    )

    speedrun = optimise_autonomous(
        level,
        source,
        AutoConfig(objective="speedrun", **common),
    )
    highscore = optimise_autonomous(
        level,
        source,
        AutoConfig(objective=AUTO_OBJECTIVE_HIGHSCORE, **common),
    )

    assert highscore.frames == speedrun.frames
    assert highscore.best.mutations == speedrun.best.mutations
    assert highscore.stats == speedrun.stats
    assert highscore.finish_tick == speedrun.finish_tick

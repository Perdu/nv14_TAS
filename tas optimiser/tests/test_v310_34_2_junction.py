from __future__ import annotations

from dataclasses import replace

import pytest

import nv14_auto as auto
from nv14_engine import parse_level_string
from nv14_replay import (
    decode_complex_replay,
    editable_frames,
    parse_combined_level_replay,
)
from nv14_search import backend_info
from nv14_splice_index import splice_contact_key


HS_RECORD = r"""$34-2 go for self#metanet##1001111115000000>111111500211111000000001111110000000000000000011111100000000000000000111111000000000000000001111110000000000000000011111100000000000000000B1111100000000000000000>11111000000000000000000B1111000000000000000000>11110000000000000000000B1110000000000000000000>1110000000000000000000011100000114000000000000111031401110000003140001111111011100000011100011111110111000000111000111021501110000002150001110000011500000000000011100000000000000000000B1100000000000000000000>11000000000000000000000B1000000000000000000000>10000000000000000000000B0000000000000000000000>000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000?@000000000000000000000C|5^744,516!11^672,564,36,72!9^396,348,0,0,16,5,1,-1,0!9^420,348,0,0,17,5,1,0,0!1^564,396!1^684,396!1^624,324!1^516,276!1^732,276!1^624,228!1^540,180!1^708,180!12^768,468!12^768,432!12^768,396!12^768,504!12^768,540!0^36,276!0^36,288!0^36,300!0^36,312!0^36,324!0^36,336!0^36,348!0^36,360!0^36,372!0^36,384!0^36,396!0^36,408!3^468,48!1^624,132!10^348,48!8^396,228,1!8^420,228,1#451:17891328|1118481|17895697|17895697|17895697|17895441|17895697|17895697|89919761|89478485|72701269|89478485|89478485|90597089|89478229|89478485|89474389|22369621|73751837|89478485|89478485|89478485|17895697|17895697|17895697|17895713|89510177|115479893|36071014|17895970|17895697|17895697|17895697|17895697|34672913|1114642|17895697|17895697|17895697|17895697|97636625|89478485|89478485|107374421|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|48374306|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|3106#"""
SR_RECORD = r"""$34-2 go for self#metanet##1001111115000000>111111500211111000000001111110000000000000000011111100000000000000000111111000000000000000001111110000000000000000011111100000000000000000B1111100000000000000000>11111000000000000000000B1111000000000000000000>11110000000000000000000B1110000000000000000000>1110000000000000000000011100000114000000000000111031401110000003140001111111011100000011100011111110111000000111000111021501110000002150001110000011500000000000011100000000000000000000B1100000000000000000000>11000000000000000000000B1000000000000000000000>10000000000000000000000B0000000000000000000000>000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000?@000000000000000000000C|5^744,516!11^672,564,36,72!9^396,348,0,0,16,5,1,-1,0!9^420,348,0,0,17,5,1,0,0!1^564,396!1^684,396!1^624,324!1^516,276!1^732,276!1^624,228!1^540,180!1^708,180!12^768,468!12^768,432!12^768,396!12^768,504!12^768,540!0^36,276!0^36,288!0^36,300!0^36,312!0^36,324!0^36,336!0^36,348!0^36,360!0^36,372!0^36,384!0^36,396!0^36,408!3^468,48!1^624,132!10^348,48!8^396,228,1!8^420,228,1#287:17895442|17895697|17961232|17895697|17895697|17891601|17961217|17896541|89002257|89478485|89478485|89478485|22369621|89478493|123032901|89478500|105207125|219537732|72701269|89474389|89478485|89478485|22304209|35791406|35660322|35840546|35791586|35791362|35791361|35790866|1188386|35660322|35791394|35791394|35791394|2236930|35725858|35791394|35787042|35790880|35791394#"""


def _load(record: str):
    combined = parse_combined_level_replay(record)
    level = parse_level_string(
        combined.level_string,
        strict_shapes=True,
        simulate_enemies=True,
    )
    frames = tuple(
        editable_frames(decode_complex_replay(combined.replay_string).frames)
    )
    evaluation = auto.evaluate_replay_with_sentinel(level, frames)
    return level, frames, evaluation


@pytest.fixture(scope="module")
def replay_pair():
    info = backend_info()
    if not info.get("available") or int(info.get("wrapper_api", 0)) < 7:
        pytest.skip(f"native Auto evaluator is unavailable: {info.get('error')}")
    level, highscore_frames, highscore = _load(HS_RECORD)
    _, speedrun_frames, speedrun = _load(SR_RECORD)
    return level, highscore_frames, highscore, speedrun_frames, speedrun


def _junction_plan(highscore, highscore_frames, speedrun, speedrun_frames):
    plans = auto.find_splice_section_plans(
        highscore,
        speedrun,
        auto.SpliceAlignmentSpec(objective=auto.AUTO_OBJECTIVE_HIGHSCORE),
        auto.SplicePlanSpec(objective=auto.AUTO_OBJECTIVE_HIGHSCORE),
        recipient_frames=highscore_frames,
        donor_frames=speedrun_frames,
    )
    junctions = tuple(plan for plan in plans if plan.junction)
    assert len(junctions) == 1
    return plans, junctions[0]


def test_34_2_discovers_one_late_junction_without_weakening_corridors(
    replay_pair,
) -> None:
    _, highscore_frames, highscore, speedrun_frames, speedrun = replay_pair
    assert (highscore.finish_tick, highscore.gold_count, highscore.highscore_value) == (
        451,
        12,
        509,
    )
    assert (speedrun.finish_tick, speedrun.gold_count) == (287, 0)

    short_runs = ()

    def observe(discovered):
        nonlocal short_runs
        short_runs = discovered

    corridors = auto.find_splice_anchor_runs(
        highscore,
        speedrun,
        auto.SpliceAlignmentSpec(objective=auto.AUTO_OBJECTIVE_HIGHSCORE),
        shorter_runs_observer=observe,
    )
    assert len(corridors) == 11
    assert all(run.frame_offset != -33 for run in corridors)
    late = tuple(run for run in short_runs if run.recipient_start_tick > 100)
    assert len(late) == 1
    assert (
        late[0].recipient_start_tick,
        late[0].recipient_end_tick,
        late[0].donor_start_tick,
        late[0].donor_end_tick,
        late[0].frame_offset,
        late[0].length,
    ) == (194, 194, 161, 161, -33, 1)

    plans, junction = _junction_plan(
        highscore,
        highscore_frames,
        speedrun,
        speedrun_frames,
    )
    assert len(plans) == 29
    assert (
        junction.recipient_entry_tick,
        junction.donor_entry_tick,
        junction.recipient_exit_tick,
        junction.donor_exit_tick,
        junction.predicted_time_gain,
        junction.local_score_gain,
    ) == (-1, -1, 194, 161, 33, 33)

    for limit in (1, 2, 4):
        selected = auto.select_splice_plans_for_pair(
            plans,
            limit,
            objective=auto.AUTO_OBJECTIVE_HIGHSCORE,
        )
        assert len(selected) <= limit
        assert sum(plan.junction for plan in selected) <= 1
    assert not any(
        plan.junction
        for plan in auto.select_splice_plans_for_pair(
            plans, 1, objective=auto.AUTO_OBJECTIVE_HIGHSCORE
        )
    )
    assert any(
        plan.junction
        for plan in auto.select_splice_plans_for_pair(
            plans, 2, objective=auto.AUTO_OBJECTIVE_HIGHSCORE
        )
    )

    trusted = next(plan for plan in plans if plan.trusted_alignment)
    weaker = replace(
        junction,
        donor_exit_tick=junction.donor_exit_tick - 1,
        plan_utility=junction.plan_utility - 10.0,
    )
    stronger = replace(
        junction,
        donor_exit_tick=junction.donor_exit_tick - 2,
        predicted_time_gain=junction.predicted_time_gain + 20,
        local_score_gain=junction.local_score_gain + 20,
        plan_utility=junction.plan_utility + 100.0,
    )
    selected = auto.select_splice_plans_for_pair(
        (trusted, weaker, junction, stronger),
        2,
        objective=auto.AUTO_OBJECTIVE_HIGHSCORE,
    )
    assert selected == (trusted, stronger)
    assert sum(plan.junction for plan in selected) == 1


def test_34_2_hybrid_validates_exact_suffix_and_active_floor_normal(
    replay_pair,
) -> None:
    level, highscore_frames, highscore, speedrun_frames, speedrun = replay_pair
    _, junction = _junction_plan(
        highscore,
        highscore_frames,
        speedrun,
        speedrun_frames,
    )
    highscore_point = highscore.point(194)
    speedrun_point = speedrun.point(161)
    assert highscore_point is not None and speedrun_point is not None
    assert highscore_point.in_air and speedrun_point.in_air
    assert highscore_point.floor_x != speedrun_point.floor_x
    assert splice_contact_key(highscore_point) == splice_contact_key(speedrun_point)
    grounded = replace(highscore_point, in_air=False)
    other_grounded = replace(speedrun_point, in_air=False)
    assert splice_contact_key(grounded) != splice_contact_key(other_grounded)

    working = auto.apply_reference_segment_splice(
        highscore_frames + (auto.NEUTRAL_INPUT,),
        speedrun_frames + (auto.NEUTRAL_INPUT,),
        junction,
        max_body_length=len(highscore_frames),
    )
    raw = auto.evaluate_replay_with_sentinel(level, working[:-1])
    assert (raw.dead_tick, raw.gold_count) == (241, 0)
    suffix = auto.build_splice_piecewise_reference(
        highscore,
        speedrun,
        junction,
    )[-1]
    config = auto.AutoConfig(
        iterations=0,
        objective=auto.AUTO_OBJECTIVE_HIGHSCORE,
        max_extra_ticks=400,
    )
    assert auto._splice_junction_suffix_run(
        raw, suffix, config, maximum_run_length=32
    ) == 6

    rejected = auto.repair_reference_segment_splice(
        level,
        auto.AutoCandidate(
            highscore_frames + (auto.NEUTRAL_INPUT,), highscore, "recipient"
        ),
        auto.AutoCandidate(
            speedrun_frames + (auto.NEUTRAL_INPUT,), speedrun, "donor"
        ),
        replace(junction, junction_validation_run_length=7),
        config=config,
        max_body_length=len(highscore_frames),
    )
    assert not rejected.accepted
    assert rejected.accepted_candidate is None
    assert (rejected.attempts, rejected.local_simulations) == (0, 0)
    assert rejected.rejection_reason == (
        "junction hybrid did not establish a stable recipient suffix"
    )
    assert any(
        "junction hybrid established 6/7" in item
        for item in rejected.diagnostics
    )


def test_34_2_strategic_jump_uses_configured_budget_and_continues_gold_repair(
    replay_pair,
) -> None:
    level, highscore_frames, highscore, speedrun_frames, speedrun = replay_pair
    _, junction = _junction_plan(
        highscore,
        highscore_frames,
        speedrun,
        speedrun_frames,
    )
    working = auto.apply_reference_segment_splice(
        highscore_frames + (auto.NEUTRAL_INPUT,),
        speedrun_frames + (auto.NEUTRAL_INPUT,),
        junction,
        max_body_length=len(highscore_frames),
    )
    raw = auto.evaluate_replay_with_sentinel(level, working[:-1])
    config = auto.AutoConfig(
        iterations=0,
        objective=auto.AUTO_OBJECTIVE_HIGHSCORE,
        max_extra_ticks=400,
        repair_search_order=auto.AUTO_REPAIR_SEARCH_ORDER_FIXED,
        repair_local_limit=2_000,
        range_start=162,
        range_end=450,
        auxiliary_beam_seeds=2,
    )
    rescued, _, simulations = auto.repair_strategic_jump_insertion_lookback(
        level,
        working,
        highscore,
        seed_evaluation=raw,
        failure_tick=241,
        reference_offset=33,
        config=config,
    )
    assert rescued is not None
    assert simulations <= config.repair_local_limit
    rescue = auto.evaluate_replay_with_sentinel(level, rescued[:-1])
    assert (rescue.finish_tick, rescue.final_gold_mask, rescue.highscore_value) == (
        410,
        0xFE0,
        150,
    )
    changed = [
        tick
        for tick, (before, after) in enumerate(zip(working, rescued))
        if before != after
    ]
    assert len(changed) == 1 and changed[0] in range(181, 184)
    trigger = rescued[changed[0]]
    assert trigger.jump and trigger.horizontal == 0

    result = auto.repair_reference_segment_splice(
        level,
        auto.AutoCandidate(
            highscore_frames + (auto.NEUTRAL_INPUT,), highscore, "recipient"
        ),
        auto.AutoCandidate(
            speedrun_frames + (auto.NEUTRAL_INPUT,), speedrun, "donor"
        ),
        junction,
        config=replace(config, repair_local_limit=1_000),
        max_body_length=len(highscore_frames),
        required_gold_mask=0,
    )
    assert result.attempts >= 3
    assert result.candidate.output_valid
    assert result.candidate.evaluation.gold_count >= 8
    assert any("gold recovery targets gold:4" in item for item in result.diagnostics)
    assert any("protected mask" in item for item in result.diagnostics)
    assert any(
        mutation.startswith("strategic transition gold recovery")
        for mutation in result.candidate.mutations
    )
    assert not result.accepted
    assert result.accepted_candidate is None
    assert len(result.auxiliary_seeds) == 2
    assert [seed.beam_seed.reference_offset for seed in result.auxiliary_seeds] == [
        33,
        33,
    ]
    assert result.auxiliary_seeds[0].priority < result.auxiliary_seeds[1].priority

    # Qualification is deliberately splice-kind neutral. The junction gate
    # governs discovery; once a candidate has a verified stable suffix, an
    # otherwise identical ordinary corridor receives the same priority.
    best_seed = result.auxiliary_seeds[0].beam_seed
    seed_evaluation = auto.evaluate_replay_with_sentinel(
        level,
        best_seed.working_frames[:-1],
    )
    alignment = auto._revalidate_auxiliary_alignment(
        seed_evaluation,
        highscore,
        best_seed,
        config,
    )
    assert alignment is not None and alignment.offset == 33
    seed_candidate = auto.AutoCandidate(
        best_seed.working_frames,
        seed_evaluation,
        "v3.11 seed qualification",
        alignment=alignment,
    )
    piecewise = auto.build_splice_piecewise_reference(
        highscore,
        speedrun,
        junction,
    )
    policy = auto.SpliceRepairSpec(
        failure_region_revisit_limit=config.splice_repair_revisit_limit,
    )
    snapshot = auto._splice_progress_snapshot(
        seed_candidate,
        piecewise,
        config,
        policy,
        inherited_misses=(),
    )
    recipient = auto.AutoCandidate(
        highscore_frames + (auto.NEUTRAL_INPUT,),
        highscore,
        "recipient",
    )
    qualified = [
        auto._splice_auxiliary_seed(
            seed_candidate,
            recipient,
            replace(junction, junction=is_junction),
            piecewise,
            snapshot,
            config,
            required_gold_mask=0,
            protected_gold_mask=0,
        )
        for is_junction in (False, True)
    ]
    assert all(seed is not None for seed in qualified)
    assert qualified[0].priority == qualified[1].priority
    assert "corridor" in qualified[0].beam_seed.description
    assert "junction" in qualified[1].beam_seed.description

    # Child admission is a normal macro evaluation. The carried offset widens
    # only this revalidation, so the +33 junction survives the ordinary
    # max_alignment=3 policy without changing unrelated searches.
    child = auto.optimise_autonomous(
        level,
        highscore_frames,
        replace(
            config,
            iterations=1,
            deterministic_phase=False,
            cheap_pulse_limit=0,
            auxiliary_beam_seeds=1,
            repair_local_limit=0,
            repair_campaign_local_limit=0,
        ),
        auxiliary_seeds=(best_seed,),
    )
    auxiliary = [
        candidate
        for candidate in child.beam
        if candidate.origin == "auxiliary-splice-seed"
    ]
    assert child.stats.macro_evaluations == 1
    assert child.frames == highscore_frames
    assert len(auxiliary) == 1
    assert auxiliary[0].alignment is not None
    assert auxiliary[0].alignment.offset == 33
    replay_keys = [auto._candidate_replay_key(candidate) for candidate in child.beam]
    assert len(replay_keys) == len(set(replay_keys))


def test_strategic_transition_finite_and_unlimited_budgets(replay_pair) -> None:
    level, highscore_frames, highscore, speedrun_frames, speedrun = replay_pair
    _, junction = _junction_plan(
        highscore,
        highscore_frames,
        speedrun,
        speedrun_frames,
    )
    working = auto.apply_reference_segment_splice(
        highscore_frames + (auto.NEUTRAL_INPUT,),
        speedrun_frames + (auto.NEUTRAL_INPUT,),
        junction,
        max_body_length=len(highscore_frames),
    )
    raw = auto.evaluate_replay_with_sentinel(level, working[:-1])
    base = auto.AutoConfig(
        iterations=0,
        objective=auto.AUTO_OBJECTIVE_HIGHSCORE,
        max_extra_ticks=400,
        repair_search_order=auto.AUTO_REPAIR_SEARCH_ORDER_FIXED,
        repair_local_limit=1_000,
        range_start=162,
        range_end=450,
    )
    finite, _, finite_simulations = auto.repair_strategic_transition_lookback(
        level,
        working,
        highscore,
        seed_evaluation=raw,
        failure_tick=241,
        reference_offset=33,
        config=base,
    )
    unlimited, _, unlimited_simulations = (
        auto.repair_strategic_transition_lookback(
            level,
            working,
            highscore,
            seed_evaluation=raw,
            failure_tick=241,
            reference_offset=33,
            config=replace(base, repair_local_limit=0),
        )
    )
    assert finite_simulations == base.repair_local_limit
    assert unlimited_simulations > finite_simulations
    assert finite is None
    assert unlimited is not None
    improved = auto.evaluate_replay_with_sentinel(level, unlimited[:-1])
    assert improved.last_tick > raw.last_tick
    assert improved.gold_count > raw.gold_count


def test_strategic_jump_respects_range_and_mutation_disable(replay_pair) -> None:
    level, highscore_frames, highscore, speedrun_frames, speedrun = replay_pair
    _, junction = _junction_plan(
        highscore,
        highscore_frames,
        speedrun,
        speedrun_frames,
    )
    working = auto.apply_reference_segment_splice(
        highscore_frames + (auto.NEUTRAL_INPUT,),
        speedrun_frames + (auto.NEUTRAL_INPUT,),
        junction,
        max_body_length=len(highscore_frames),
    )
    raw = auto.evaluate_replay_with_sentinel(level, working[:-1])
    base = auto.AutoConfig(
        iterations=0,
        objective=auto.AUTO_OBJECTIVE_HIGHSCORE,
        max_extra_ticks=400,
        repair_search_order=auto.AUTO_REPAIR_SEARCH_ORDER_FIXED,
        repair_local_limit=100,
        range_start=162,
        range_end=180,
    )
    proposal, branches, simulations = auto.repair_strategic_jump_insertion_lookback(
        level,
        working,
        highscore,
        seed_evaluation=raw,
        failure_tick=241,
        reference_offset=33,
        config=base,
    )
    assert (proposal, branches, simulations) == (None, 0, 0)
    disabled = replace(
        base,
        range_end=450,
        max_jump_shift=0,
        max_jump_hold_delta=0,
    )
    proposal, branches, simulations = auto.repair_strategic_jump_insertion_lookback(
        level,
        working,
        highscore,
        seed_evaluation=raw,
        failure_tick=241,
        reference_offset=33,
        config=disabled,
    )
    assert (proposal, branches, simulations) == (None, 0, 0)

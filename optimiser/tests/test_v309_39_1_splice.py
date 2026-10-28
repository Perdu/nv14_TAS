from __future__ import annotations

import pytest

import nv14_auto as auto
from nv14_engine import parse_level_string
from nv14_replay import (
    decode_complex_replay,
    editable_frames,
    parse_combined_level_replay,
)
from nv14_search import backend_info


HS_RECORD = r"""$###111111111111111111111115000011000500500500500200000150000000000000000000001000000000000000000000000000000000000000000000000400400400400400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000700000000000000000000311000000000000111111111110000000000001111111111100000000000011111111111000000000000:1111111111000000000000000000000610000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000071000000000000;11111111110000000000001111111111100000000000711111111111|5^228,564!12^420,312!12^384,348!12^384,492!12^384,420!12^288,228!12^288,300!12^288,372!12^288,444!12^372,384!12^372,456!12^384,312!12^324,264!12^324,336!12^324,408!0^348,312!0^348,324!0^348,336!0^348,360!0^348,372!0^348,384!0^348,408!0^348,420!0^348,432!0^348,456!0^348,468!0^348,480!12^324,480!11^312,564,84,132!10^756,36!3^540,396!3^636,492!0^564,540!0^552,540!0^684,348!0^684,360!0^684,372!0^684,396!0^684,408!0^684,420!0^684,444!0^684,456!0^684,468!0^684,492!0^684,504!0^684,516!1^588,444!1^588,492!1^588,396!0^540,540!12^324,192!6^156,252,1,0,0,0!6^132,372,0,0,0,3!6^180,516,1,0,0,3!2^702,318,-0.707106781186547,-0.707106781186547!2^660,552,0,-1!0^612,540!0^624,540!0^636,540!0^588,540#489:97587472|89478485|89478485|89478485|22369621|89478493|89478485|89478485|22369621|90596974|108352853|107374182|107374182|107374182|107374182|89488934|89478485|17895697|17895697|35721489|35791394|35791394|35791394|35810850|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35810850|35791394|35791394|35791394|35791394|35791394|35791394|35791394|8738|0|0|0|31527168|17895697|17895697|17895697|17895697|17895697|220011793|89478485|17895697|17895697|17895697|17895697|17895697|17895697|17895697|34672913|35791394|35791394|35791394|35791394|17900066|17895697|17895697|1118481#"""
SR_RECORD = r"""$39-1 deliverator#metanet##111111111111111111111115000011000500500500500200000150000000000000000000001000000000000000000000000000000000000000000000000400400400400400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000700000000000000000000311000000000000111111111110000000000001111111111100000000000011111111111000000000000:1111111111000000000000000000000610000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000071000000000000;11111111110000000000001111111111100000000000711111111111|5^228,564!12^420,312!12^384,348!12^384,492!12^384,420!12^288,228!12^288,300!12^288,372!12^288,444!12^372,384!12^372,456!12^384,312!12^324,264!12^324,336!12^324,408!0^348,312!0^348,324!0^348,336!0^348,360!0^348,372!0^348,384!0^348,408!0^348,420!0^348,432!0^348,456!0^348,468!0^348,480!12^324,480!11^312,564,84,132!10^756,36!3^540,396!3^636,492!0^564,540!0^552,540!0^684,348!0^684,360!0^684,372!0^684,396!0^684,408!0^684,420!0^684,444!0^684,456!0^684,468!0^684,492!0^684,504!0^684,516!1^588,444!1^588,492!1^588,396!0^540,540!12^324,192!6^156,252,1,0,0,0!6^132,372,0,0,0,3!6^180,516,1,0,0,3!2^702,318,-0.707106781186547,-0.707106781186547!2^660,552,0,-1!0^612,540!0^624,540!0^636,540!0^588,540#241:97587217|89478485|89478485|89478485|22369621|89478493|89478485|89478485|5596501|89478510|72160596|107374182|72697446|17895765|17895697|17895697|17895697|17895697|4369|35791394|35791394|35791394|35791394|35791394|17895697|17895697|17895697|35791393|35791394|35791394|35791394|35791394|35791394|35791394|546#"""


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


def test_39_1_start_splice_detects_and_realises_twelve_tick_gain() -> None:
    info = backend_info()
    if not info.get("available") or int(info.get("wrapper_api", 0)) < 3:
        pytest.skip(f"native Auto evaluator is unavailable: {info.get('error')}")

    level, highscore_frames, highscore = _load(HS_RECORD)
    _, speedrun_frames, speedrun = _load(SR_RECORD)
    alignment = auto.SpliceAlignmentSpec(
        position_tolerance=3.0,
        velocity_tolerance=0.75,
        objective=auto.AUTO_OBJECTIVE_HIGHSCORE,
    )

    corridors = auto.find_splice_anchor_runs(highscore, speedrun, alignment)
    late_corridors = [
        corridor
        for corridor in corridors
        if corridor.frame_offset == -12
        and corridor.recipient_start_tick <= 160 <= corridor.recipient_end_tick
    ]
    assert late_corridors
    assert late_corridors[0].length >= 10
    assert late_corridors[0].mean_match_cost < 0.02

    plans = auto.find_splice_section_plans(
        highscore,
        speedrun,
        alignment,
        auto.SplicePlanSpec(objective=auto.AUTO_OBJECTIVE_HIGHSCORE),
        recipient_frames=highscore_frames,
        donor_frames=speedrun_frames,
        anchor_runs=corridors,
    )
    attempted_plans = plans[:2]
    trusted = [
        plan
        for plan in attempted_plans
        if plan.recipient_entry_tick == plan.donor_entry_tick == -1
        and plan.exit_anchor_run.frame_offset == -12
    ]

    # The physically coherent ridge must survive alongside the gain-oriented
    # exploratory candidate within the unchanged default two-attempt budget.
    assert trusted
    assert trusted[0].predicted_time_gain == 12
    assert trusted[0].trusted_alignment is True

    raw_working = auto.apply_reference_segment_splice(
        highscore_frames + (auto.NEUTRAL_INPUT,),
        speedrun_frames + (auto.NEUTRAL_INPUT,),
        trusted[0],
        max_body_length=len(highscore_frames),
    )
    result = auto.evaluate_replay_with_sentinel(level, raw_working[:-1])

    assert result.finish_tick == 477
    assert result.final_gold_mask.bit_count() == 31
    assert result.gold_bonus_ticks - result.finish_tick == 2003

    recipient = auto.AutoCandidate(
        highscore_frames + (auto.NEUTRAL_INPUT,),
        highscore,
        "v3.09 regression recipient",
    )
    donor = auto.AutoCandidate(
        speedrun_frames + (auto.NEUTRAL_INPUT,),
        speedrun,
        "v3.09 regression donor",
    )
    repaired = auto.repair_reference_segment_splice(
        level,
        recipient,
        donor,
        trusted[0],
        config=auto.AutoConfig(
            iterations=0,
            objective=auto.AUTO_OBJECTIVE_HIGHSCORE,
            max_extra_ticks=400,
        ),
        max_body_length=len(highscore_frames),
        required_gold_mask=highscore.final_gold_mask,
    )

    assert repaired.accepted is True
    assert repaired.attempts == 0
    assert repaired.local_simulations == 0
    assert repaired.candidate.finish_tick == 477
    assert repaired.candidate.evaluation.gold_count == 31
    assert repaired.candidate.evaluation.highscore_value == 2003

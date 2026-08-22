from __future__ import annotations

import sys
from dataclasses import replace

import pytest

import optimize_replay as opt
import nv14_auto as auto
from nv14_auto import AutoConfig
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame
from nv14_replay import encode_complex_replay


def test_v213_auto_parser_uses_local_step_controls_without_a_bank() -> None:
    parser = opt.build_parser()

    defaults = parser.parse_args(["auto", "input.txt"])
    assert defaults.auto_deterministic is True
    assert not hasattr(defaults, "auto_repair_refill")
    assert not hasattr(defaults, "auto_deep_repairs")
    assert not hasattr(defaults, "auto_repair_attempts")
    assert defaults.auto_repair_local_steps == 1_000
    assert defaults.auto_repair_search_order == "random"
    assert defaults.auto_frame_ahead_repair_multiplier == 10
    assert defaults.auto_campaign_local_steps == 10_000

    configured = parser.parse_args(
        [
            "auto", "input.txt",
            "--auto-no-deterministic",
            "--auto-repair-local-steps",
            "777",
            "--auto-repair-search-order",
            "fixed",
            "--auto-frame-ahead-repair-multiplier",
            "7",
            "--auto-campaign-local-steps",
            "123456",
        ]
    )
    assert configured.auto_deterministic is False
    assert configured.auto_repair_local_steps == 777
    assert configured.auto_repair_search_order == "fixed"
    assert configured.auto_frame_ahead_repair_multiplier == 7
    assert configured.auto_campaign_local_steps == 123456


@pytest.mark.parametrize(
    "removed_option",
    (
        "--auto-deep-repairs",
        "--auto-repair-refill",
        "--auto-repair-attempts",
    ),
)
def test_v213_removed_repair_bank_options_are_rejected(removed_option: str) -> None:
    parser = opt.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["auto", "input.txt", removed_option, "1"])


def test_v213_local_step_config_accepts_zero_but_rejects_negative() -> None:
    zeroed = AutoConfig(
        iterations=0,
        repair_local_limit=0,
        frame_ahead_repair_multiplier=1,
        repair_campaign_local_limit=0,
    )
    assert zeroed.repair_local_limit == 0
    assert zeroed.frame_ahead_repair_multiplier == 1
    assert zeroed.repair_campaign_local_limit == 0

    with pytest.raises(TypeError, match="deep_repair_limit"):
        AutoConfig(iterations=0, deep_repair_limit=1)
    with pytest.raises(TypeError, match="repair_refill_interval"):
        AutoConfig(iterations=0, repair_refill_interval=1)
    with pytest.raises(TypeError, match="repair_chain_limit"):
        AutoConfig(iterations=0, repair_chain_limit=1)
    assert not hasattr(auto, "_RepairBudget")
    assert not hasattr(auto, "_planned_campaign_repairs")
    assert not hasattr(auto, "_remaining_repair_obligations")
    with pytest.raises(ValueError, match="repair_local_limit"):
        AutoConfig(iterations=0, repair_local_limit=-1)
    with pytest.raises(ValueError, match="repair_search_order"):
        AutoConfig(iterations=0, repair_search_order="sideways")
    with pytest.raises(ValueError, match="frame_ahead_repair_multiplier"):
        AutoConfig(iterations=0, frame_ahead_repair_multiplier=0)
    with pytest.raises(ValueError, match="repair_campaign_local_limit"):
        AutoConfig(iterations=0, repair_campaign_local_limit=-1)


def test_v213_cli_forwards_local_repair_controls_to_auto_config(
    tmp_path, monkeypatch
) -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    level_string = f"{''.join(chars)}|5^60,134!11^140,134,60,134"
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    input_path = tmp_path / "source.txt"
    output_path = tmp_path / "output.txt"
    input_path.write_text(
        f"$v2.13 CLI#tests##{level_string}#"
        f"{encode_complex_replay(source)}#\n",
        encoding="utf-8",
    )
    observed: list[tuple[bool, int, str, int, int]] = []
    real_optimise = opt.optimise_autonomous

    def recording_optimise(level, frames, config, *, progress=None, best_callback=None):
        observed.append(
            (
                config.deterministic_phase,
                config.repair_local_limit,
                config.repair_search_order,
                config.frame_ahead_repair_multiplier,
                config.repair_campaign_local_limit,
            )
        )
        return real_optimise(
            level,
            frames,
            config,
            progress=progress,
            best_callback=best_callback,
        )

    monkeypatch.setattr(opt, "optimise_autonomous", recording_optimise)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto", str(input_path),
            "--iterations",
            "0",
            "--auto-no-deterministic",
            "--auto-repair-local-steps",
            "777",
            "--auto-repair-search-order",
            "fixed",
            "--auto-frame-ahead-repair-multiplier",
            "7",
            "--auto-campaign-local-steps",
            "123456",
            "--output",
            str(output_path),
        ],
    )

    opt.main()

    assert observed == [(False, 777, "fixed", 7, 123456)]
    assert output_path.exists()


def _candidate_with_alignment(*, offset: int, score_lead: int) -> auto.AutoCandidate:
    evaluation = auto.AutoEvaluation(
        finish_tick=None,
        dead_tick=None,
        last_tick=0,
        trace=(),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
    )
    return auto.AutoCandidate(
        working_frames=(auto.NEUTRAL_INPUT,),
        evaluation=evaluation,
        origin="test",
        alignment=auto.AlignmentMatch(
            candidate_tick=0,
            reference_tick=max(0, offset),
            offset=offset,
            distance=0.0,
            contact_matches=True,
            static_matches=True,
            score_lead=score_lead,
        ),
    )


def test_v2124_frame_ahead_multiplier_uses_trajectory_offset_and_is_sticky() -> None:
    highscore_only_lead = _candidate_with_alignment(offset=0, score_lead=80)
    measured_lead = _candidate_with_alignment(offset=1, score_lead=1)
    no_current_lead = _candidate_with_alignment(offset=0, score_lead=0)

    assert not auto._has_measured_frame_lead(highscore_only_lead)
    assert auto._has_measured_frame_lead(measured_lead)
    assert not auto._frame_ahead_repair_eligible(highscore_only_lead)
    assert auto._frame_ahead_repair_eligible(measured_lead)
    assert auto._frame_ahead_repair_eligible(
        no_current_lead,
        frame_ahead_seen=True,
    )

    config = AutoConfig(
        iterations=0,
        repair_local_limit=1_000,
        frame_ahead_repair_multiplier=10,
    )
    seen = False
    attempt_limits: list[int] = []
    for candidate in (no_current_lead, measured_lead, no_current_lead):
        active = auto._frame_ahead_repair_eligible(
            candidate,
            frame_ahead_seen=seen,
        )
        attempt_limits.append(
            auto._repair_attempt_local_limit(config, frame_ahead=active)
        )
        seen = active

    # Repair 1 is ordinary, repair 2 sees the new lead, and repair 3 keeps the
    # bonus even though its current alignment no longer reports a positive offset.
    assert attempt_limits == [1_000, 10_000, 10_000]


def test_v2124_frame_ahead_multiplier_preserves_disable_and_unlimited_semantics() -> None:
    ordinary = AutoConfig(
        iterations=0,
        repair_local_limit=777,
        frame_ahead_repair_multiplier=10,
    )
    disabled = AutoConfig(
        iterations=0,
        repair_local_limit=777,
        frame_ahead_repair_multiplier=1,
    )
    unlimited = AutoConfig(
        iterations=0,
        repair_local_limit=0,
        frame_ahead_repair_multiplier=10,
    )

    assert auto._repair_attempt_local_limit(ordinary, frame_ahead=False) == 777
    assert auto._repair_attempt_local_limit(ordinary, frame_ahead=True) == 7_770
    assert auto._repair_attempt_local_limit(disabled, frame_ahead=True) == 777
    assert auto._repair_attempt_local_limit(unlimited, frame_ahead=True) == 0


def test_v2123_direction_repair_honours_per_repair_local_step_limit() -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    level = opt.parse_level_string(
        f"{''.join(chars)}|5^60,134!11^140,134,60,134",
        simulate_enemies=True,
    )
    working = tuple([InputFrame(right=True)] * 20) + (auto.NEUTRAL_INPUT,)
    reference = auto._evaluate_working(level, working)
    shifted_trace = list(reference.trace)
    shifted_trace[13] = replace(
        shifted_trace[13], x=shifted_trace[13].x + 1_000.0
    )
    reference = replace(reference, trace=tuple(shifted_trace))

    _, _, simulations = auto.repair_direction_window(
        level,
        working,
        reference,
        failure_tick=10,
        reference_offset=0,
        config=AutoConfig(
            iterations=1,
            repair_lookback=6,
            repair_local_limit=7,
            repair_campaign_local_limit=100,
        ),
    )

    assert simulations == 7


def test_v2124_direction_repair_does_not_charge_prefix_setup() -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    level = opt.parse_level_string(
        f"{''.join(chars)}|5^60,134!11^140,134,60,134",
        simulate_enemies=True,
    )
    working = tuple([InputFrame(right=True)] * 20) + (auto.NEUTRAL_INPUT,)
    reference = auto._evaluate_working(level, working)
    shifted_trace = list(reference.trace)
    shifted_trace[13] = replace(
        shifted_trace[13], x=shifted_trace[13].x + 1_000.0
    )
    reference = replace(reference, trace=tuple(shifted_trace))

    _, branches, simulations = auto.repair_direction_window(
        level,
        working,
        reference,
        failure_tick=10,
        reference_offset=0,
        config=AutoConfig(
            iterations=1,
            repair_window=2,
            repair_lookback=2,
            repair_local_limit=1,
        ),
    )

    assert branches > 0
    assert simulations == 1


def test_v2124_all_input_repair_does_not_charge_prefix_setup() -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    level = opt.parse_level_string(
        f"{''.join(chars)}|5^60,134!11^140,134,60,134",
        simulate_enemies=True,
    )
    working = tuple([InputFrame(right=True)] * 20) + (auto.NEUTRAL_INPUT,)
    reference = auto._evaluate_working(level, working)

    _, branches, simulations = auto.repair_all_input_window(
        level,
        working,
        reference,
        seed_evaluation=reference,
        failure_tick=10,
        reference_offset=0,
        config=AutoConfig(
            iterations=1,
            repair_window=2,
            repair_lookback=2,
            repair_local_limit=1,
        ),
    )

    assert branches > 0
    assert simulations == 1


def test_v2122_best_callback_fires_for_each_new_incumbent() -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    level = opt.parse_level_string(
        f"{''.join(chars)}|5^60,134!11^140,134,60,134",
        simulate_enemies=True,
    )
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    checkpoints: list[int | None] = []

    result = auto.optimise_autonomous(
        level,
        source,
        AutoConfig(iterations=10, beam_width=2),
        best_callback=lambda candidate: checkpoints.append(candidate.finish_tick),
    )

    assert checkpoints == [33, 32, 31, 30]
    assert result.finish_tick == 30


def test_v2125_frame_ahead_multiplier_expands_campaign_local_limit_stickily() -> None:
    config = AutoConfig(
        iterations=0,
        repair_campaign_local_limit=10_000,
        frame_ahead_repair_multiplier=10,
    )
    no_lead = _candidate_with_alignment(offset=0, score_lead=0)
    measured_lead = _candidate_with_alignment(offset=1, score_lead=1)

    seen = False
    campaign_limits: list[int] = []
    for candidate in (no_lead, measured_lead, no_lead):
        seen = auto._frame_ahead_repair_eligible(
            candidate,
            frame_ahead_seen=seen,
        )
        campaign_limits.append(
            auto._repair_campaign_local_limit(config, frame_ahead=seen)
        )

    # If repair 1 creates the lead, the cap is enlarged before repair 2 is
    # considered, and remains enlarged for the rest of the campaign.
    assert campaign_limits == [10_000, 100_000, 100_000]


def test_v2125_campaign_multiplier_preserves_disable_and_unlimited_semantics() -> None:
    ordinary = AutoConfig(
        iterations=0,
        repair_campaign_local_limit=12_345,
        frame_ahead_repair_multiplier=10,
    )
    disabled = AutoConfig(
        iterations=0,
        repair_campaign_local_limit=12_345,
        frame_ahead_repair_multiplier=1,
    )
    unlimited = AutoConfig(
        iterations=0,
        repair_campaign_local_limit=0,
        frame_ahead_repair_multiplier=10,
    )

    assert auto._repair_campaign_local_limit(ordinary, frame_ahead=False) == 12_345
    assert auto._repair_campaign_local_limit(ordinary, frame_ahead=True) == 123_450
    assert auto._repair_campaign_local_limit(disabled, frame_ahead=True) == 12_345
    assert auto._repair_campaign_local_limit(unlimited, frame_ahead=True) == 0

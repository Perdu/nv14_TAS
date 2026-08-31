from __future__ import annotations

import sys
from pathlib import Path

import pytest

import optimize_replay as opt
from nv14_auto import verify_trimmed_replay
from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    parse_level_string,
)
from nv14_replay import (
    decode_complex_replay,
    editable_frames,
    encode_complex_replay,
    parse_combined_level_replay,
)


def _running_exit_level_string() -> str:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    # Map serialization is x-major.  The floor's tile centres are at y=156,
    # supporting a radius-10 ninja at y=134.
    for x in range(APP_NUM_GRIDCOLS):
        chars[x * APP_NUM_GRIDROWS + 5] = "1"
    return f"{''.join(chars)}|5^60,134!11^140,134,60,134"


def _write_completed_input(tmp_path):
    level_string = _running_exit_level_string()
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    replay_string = encode_complex_replay(source)
    input_path = tmp_path / "source.txt"
    input_path.write_text(
        f"$Auto CLI#tests##{level_string}#{replay_string}#\n",
        encoding="utf-8",
    )
    return input_path


def test_auto_parser_defaults_and_overrides() -> None:
    parser = opt.build_parser()

    defaults = parser.parse_args(["auto", "input.txt"])
    assert defaults.iterations == 5000
    assert defaults.auto_runs == 1
    assert defaults.auto_stagnation_runs == 0
    assert defaults.auto_checkpoint is None
    assert defaults.auto_resume is False
    assert defaults.auto_parents == []
    assert defaults.beam == 32
    assert defaults.max_retime == 3
    assert defaults.auto_repair_window == 6
    assert defaults.auto_repair_lookback == 192
    assert defaults.auto_max_alignment == 3
    assert defaults.auto_beam_repair_revisit_limit == 2
    assert defaults.auto_splice_repair_revisit_limit == 3
    assert not hasattr(defaults, "auto_deep_repairs")
    assert not hasattr(defaults, "auto_repair_refill")
    assert defaults.auto_objective == "speedrun"
    assert defaults.auto_require_reference_gold is False
    assert defaults.auto_max_extra_ticks is None
    assert defaults.simulate_enemies is None

    configured = parser.parse_args(
        [
            "auto", "input.txt",
            "--iterations",
            "9",
            "--auto-runs",
            "4",
            "--auto-stagnation-runs",
            "6",
            "--auto-checkpoint",
            "campaign.json",
            "--auto-resume",
            "--beam",
            "7",
            "--max-retime",
            "2",
            "--auto-repair-window",
            "4",
            "--auto-repair-lookback",
            "80",
            "--auto-max-alignment",
            "5",
            "--auto-beam-repair-revisit-limit",
            "6",
            "--auto-splice-repair-revisit-limit",
            "9",
            "--auto-objective",
            "highscore",
            "--auto-require-reference-gold",
            "--auto-max-extra-ticks",
            "160",
            "--seed",
            "41",
            "--no-simulate-enemies",
        ]
    )
    assert configured.iterations == 9
    assert configured.auto_runs == 4
    assert configured.auto_stagnation_runs == 6
    assert configured.auto_checkpoint == Path("campaign.json")
    assert configured.auto_resume is True
    assert configured.beam == 7
    assert configured.max_retime == 2
    assert configured.auto_repair_window == 4
    assert configured.auto_repair_lookback == 80
    assert configured.auto_max_alignment == 5
    assert configured.auto_beam_repair_revisit_limit == 6
    assert configured.auto_splice_repair_revisit_limit == 9
    assert configured.auto_objective == "highscore"
    assert configured.auto_require_reference_gold is True
    assert configured.auto_max_extra_ticks == 160
    assert configured.seed == 41
    assert configured.simulate_enemies is False

    random_seed = parser.parse_args(
        ["auto", "input.txt", "--seed", "random"]
    )
    assert random_seed.seed == "random"

    with pytest.raises(SystemExit):
        parser.parse_args(
            ["auto", "input.txt", "--auto-stagnation-runs", "-1"]
        )


def test_auto_parser_accepts_repeatable_starting_parents() -> None:
    args = opt.parse_arguments(
        [
            "auto",
            "parent-a.ltm",
            "--auto-parent",
            "parent-b.ltm",
            "--auto-parent",
            "parent-c.ltm",
        ]
    )

    assert args.auto_parents == [Path("parent-b.ltm"), Path("parent-c.ltm")]

    with pytest.raises(SystemExit):
        opt.parse_arguments(
            ["local", "input.txt", "--auto-parent", "parent.txt"]
        )


def test_seed_parser_rejects_non_integer_non_random() -> None:
    parser = opt.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["auto", "input.txt", "--seed", "banana"])


@pytest.mark.parametrize(
    "option",
    (
        "--auto-beam-repair-revisit-limit",
        "--auto-splice-repair-revisit-limit",
    ),
)
def test_auto_repair_revisit_limits_must_be_positive(option: str) -> None:
    parser = opt.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["auto", "input.txt", option, "0"])


def test_local_subcommand_still_requires_target_frame(tmp_path, monkeypatch) -> None:
    input_path = _write_completed_input(tmp_path)
    output_path = tmp_path / "legacy.txt"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "local", str(input_path),
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit, match="--target-frame is required"):
        opt.main()
    assert not output_path.exists()


def test_legacy_mode_option_is_rejected() -> None:
    parser = opt.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["input.txt", "--mode", "local"])


def test_auto_cli_needs_no_target_and_writes_verified_trimmed_replay(
    tmp_path, monkeypatch, capsys
) -> None:
    input_path = _write_completed_input(tmp_path)
    output_path = tmp_path / "optimized.txt"
    replay_path = tmp_path / "optimized.replay.txt"
    real_parse_level_string = opt.parse_level_string
    enemy_settings: list[bool] = []

    def recording_parse_level_string(*args, **kwargs):
        enemy_settings.append(kwargs["simulate_enemies"])
        return real_parse_level_string(*args, **kwargs)

    monkeypatch.setattr(opt, "parse_level_string", recording_parse_level_string)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto", str(input_path),
            "--iterations",
            "0",
            "--beam",
            "2",
            "--output",
            str(output_path),
            "--replay-output",
            str(replay_path),
        ],
    )

    opt.main()
    stdout = capsys.readouterr().out
    assert stdout.startswith("[auto:baseline] verifying source replay...\n")
    assert (
        "[auto:baseline] source verified at finish tick 34 "
        "(distance to exit 2.80); building autonomous search plan; "
        "budget 0 evaluations"
    ) in stdout
    assert "[auto:complete] 0/0 evaluations; best 34;" in stdout

    combined = parse_combined_level_replay(output_path.read_text(encoding="utf-8"))
    packed = decode_complex_replay(combined.replay_string)
    standalone_replay = replay_path.read_text(encoding="utf-8").strip()
    assert standalone_replay == combined.replay_string
    assert packed.tick_count == 34

    level = parse_level_string(combined.level_string, simulate_enemies=True)
    verified = verify_trimmed_replay(level, editable_frames(packed.frames))
    assert verified.valid
    assert verified.finish_tick == packed.tick_count
    assert enemy_settings == [True]


def test_v300_auto_cli_zero_iteration_selects_the_best_starting_parent(
    tmp_path, monkeypatch, capsys
) -> None:
    input_path = _write_completed_input(tmp_path)
    primary = parse_combined_level_replay(input_path.read_text(encoding="utf-8"))
    faster_replay = encode_complex_replay([InputFrame(right=True)] * 100)
    parent_path = tmp_path / "faster-parent.txt"
    parent_path.write_text(
        primary.replace_replay(faster_replay).dump() + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "multi-parent-output.txt"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto",
            str(input_path),
            "--auto-parent",
            str(parent_path),
            "--iterations",
            "0",
            "--output",
            str(output_path),
        ],
    )

    opt.main()

    stdout = capsys.readouterr().out
    output = parse_combined_level_replay(output_path.read_text(encoding="utf-8"))
    packed = decode_complex_replay(output.replay_string)
    assert output.name == primary.name
    assert output.author == primary.author
    assert packed.tick_count == 29
    assert "auto baseline finish tick: 34" in stdout
    assert "auto optimised finish tick: 29" in stdout
    assert "starting parent #2" in stdout
    assert "2 unique starting parent(s) from 2 supplied" in stdout


def test_v300_auto_cli_rejects_a_parent_from_a_different_level(
    tmp_path, monkeypatch
) -> None:
    input_path = _write_completed_input(tmp_path)
    primary = parse_combined_level_replay(input_path.read_text(encoding="utf-8"))
    different_level = "1" + primary.level_string[1:]
    fields = primary.fields.copy()
    fields[primary.level_index] = different_level
    parent_path = tmp_path / "different-level.txt"
    parent_path.write_text("#".join(fields) + "\n", encoding="utf-8")
    output_path = tmp_path / "must-not-exist.txt"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto",
            str(input_path),
            "--auto-parent",
            str(parent_path),
            "--iterations",
            "0",
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit, match="exactly the same level"):
        opt.main()
    assert not output_path.exists()


def test_auto_highscore_cli_reports_and_verifies_gold_score(
    tmp_path, monkeypatch, capsys
) -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    level_string = (
        f"{''.join(chars)}|5^60,134!0^100,134!11^140,134,60,134"
    )
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    input_path = tmp_path / "highscore-source.txt"
    input_path.write_text(
        f"$Auto highscore CLI#tests##{level_string}#"
        f"{encode_complex_replay(source)}#\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "highscore-output.txt"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto", str(input_path),
            "--auto-objective",
            "highscore",
            "--iterations",
            "0",
            "--output",
            str(output_path),
        ],
    )

    opt.main()
    stdout = capsys.readouterr().out
    assert (
        "finish tick 34 (distance to exit 2.80); building autonomous search plan; "
        "score 46; gold 1 (+80 ticks); budget 0 evaluations"
    ) in stdout
    assert "auto objective: highscore" in stdout
    assert (
        "auto baseline: finish 34; gold 1; gold bonus 80; "
        "highscore value 46"
    ) in stdout
    assert "auto optimised: finish 34 (same raw time); gold 1" in stdout

    combined = parse_combined_level_replay(output_path.read_text(encoding="utf-8"))
    packed = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string, simulate_enemies=True)
    verified = verify_trimmed_replay(
        level,
        editable_frames(packed.frames),
        expected_finish_tick=34,
        expected_gold_mask=0b1,
        expected_gold_bonus_ticks=80,
    )
    assert verified.highscore_value == 46


def test_auto_highscore_cli_can_write_a_slower_extra_gold_winner(
    tmp_path, monkeypatch, capsys
) -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        chars[column * APP_NUM_GRIDROWS + 5] = "1"
    level_string = (
        f"{''.join(chars)}|5^60,134!0^100,117!11^140,134,60,134"
    )
    source = [InputFrame(right=True)] * 100
    input_path = tmp_path / "slower-highscore-source.txt"
    input_path.write_text(
        f"$Slower highscore CLI#tests##{level_string}#"
        f"{encode_complex_replay(source)}#\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "slower-highscore-output.txt"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto", str(input_path),
            "--auto-objective",
            "highscore",
            "--iterations",
            "50",
            "--workers",
            "1",
            "--beam",
            "32",
            "--seed",
            "0",
            "--output",
            str(output_path),
        ],
    )

    opt.main()
    stdout = capsys.readouterr().out
    assert "auto baseline: finish 29; gold 0; gold bonus 0" in stdout
    assert "auto optimised:" in stdout
    assert "; gold 1; gold bonus 80; highscore value " in stdout
    assert "additional gold: gold:0" in stdout

    combined = parse_combined_level_replay(output_path.read_text(encoding="utf-8"))
    packed = decode_complex_replay(combined.replay_string)
    assert packed.tick_count > 29
    level = parse_level_string(combined.level_string, simulate_enemies=True)
    verified = verify_trimmed_replay(
        level,
        editable_frames(packed.frames),
        expected_finish_tick=packed.tick_count,
        expected_gold_mask=0b1,
        expected_gold_bonus_ticks=80,
    )
    assert verified.highscore_value > -29


@pytest.mark.parametrize(
    ("extra_args", "message"),
    [
        (
            ["--auto-require-reference-gold"],
            "only meaningful for the highscore objective",
        ),
        (["--auto-max-extra-ticks", "1"], "requires max_extra_ticks=0"),
    ],
)
def test_auto_cli_rejects_highscore_only_controls_in_speedrun_mode(
    tmp_path, monkeypatch, extra_args, message
) -> None:
    input_path = _write_completed_input(tmp_path)
    output_path = tmp_path / "invalid.txt"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto", str(input_path),
            "--iterations",
            "0",
            *extra_args,
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit, match=message):
        opt.main()
    assert not output_path.exists()


def test_auto_random_seed_is_resolved_once_reported_and_passed_to_search(
    tmp_path, monkeypatch, capsys
) -> None:
    input_path = _write_completed_input(tmp_path)
    output_path = tmp_path / "random-seed.txt"
    resolved_seed = 0x0123456789ABCDEF
    seen_seeds: list[int] = []
    real_optimise_autonomous = opt.optimise_autonomous

    def recording_optimise_autonomous(level, frames, config, *, progress=None, best_callback=None):
        seen_seeds.append(config.seed)
        return real_optimise_autonomous(
            level,
            frames,
            config,
            progress=progress,
            best_callback=best_callback,
        )

    urandom_calls: list[int] = []

    def fixed_urandom(size: int) -> bytes:
        urandom_calls.append(size)
        return resolved_seed.to_bytes(size, "big")

    monkeypatch.setattr(opt.os, "urandom", fixed_urandom)
    monkeypatch.setattr(opt, "optimise_autonomous", recording_optimise_autonomous)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto", str(input_path),
            "--iterations",
            "0",
            "--beam",
            "2",
            "--seed",
            "random",
            "--output",
            str(output_path),
        ],
    )

    opt.main()
    stdout = capsys.readouterr().out
    assert stdout.startswith(f"[auto:seed] random seed {resolved_seed}\n")
    assert urandom_calls == [8]
    assert seen_seeds == [resolved_seed]
    assert output_path.exists()


def test_random_seed_sentinel_is_auto_only(tmp_path, monkeypatch) -> None:
    input_path = _write_completed_input(tmp_path)
    output_path = tmp_path / "local.txt"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "local", str(input_path),
            "--target-frame",
            "10",
            "--seed",
            "random",
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit, match="--seed random is only supported"):
        opt.main()
    assert not output_path.exists()


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--auto-objective", "highscore"],
        ["--auto-require-reference-gold"],
        ["--auto-max-extra-ticks", "0"],
    ],
)
def test_highscore_auto_controls_are_rejected_outside_auto_mode(
    tmp_path, monkeypatch, extra_args
) -> None:
    input_path = _write_completed_input(tmp_path)
    output_path = tmp_path / "local.txt"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "local", str(input_path),
            "--target-frame",
            "10",
            *extra_args,
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit):
        opt.main()
    assert not output_path.exists()


def test_v2122_cli_checkpoints_each_best_before_search_returns(
    tmp_path, monkeypatch, capsys
) -> None:
    input_path = _write_completed_input(tmp_path)
    output_path = tmp_path / "checkpointed.txt"
    replay_path = tmp_path / "checkpointed.replay.txt"
    real_optimise = opt.optimise_autonomous
    observed_ticks: list[int] = []

    def observing_optimise(
        level, frames, config, *, progress=None, best_callback=None
    ):
        assert best_callback is not None

        def observing_callback(candidate):
            best_callback(candidate)
            # The callback must have persisted this incumbent before control
            # returns to the search.
            saved = parse_combined_level_replay(
                output_path.read_text(encoding="utf-8")
            )
            packed = decode_complex_replay(saved.replay_string)
            standalone = replay_path.read_text(encoding="utf-8").strip()
            assert standalone == saved.replay_string
            assert packed.tick_count == candidate.finish_tick
            observed_ticks.append(packed.tick_count)

        return real_optimise(
            level,
            frames,
            config,
            progress=progress,
            best_callback=observing_callback,
        )

    monkeypatch.setattr(opt, "optimise_autonomous", observing_optimise)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "auto", str(input_path),
            "--iterations",
            "10",
            "--workers",
            "1",
            "--beam",
            "2",
            "--output",
            str(output_path),
            "--replay-output",
            str(replay_path),
        ],
    )

    opt.main()
    stdout = capsys.readouterr().out
    assert observed_ticks == [33, 32, 31, 30]
    assert "[auto:checkpoint] saved best #1: finish 33" in stdout
    assert "[auto:checkpoint] saved best #4: finish 30" in stdout
    checkpoint_lines = [
        line for line in stdout.splitlines() if "[auto:checkpoint]" in line
    ]
    assert checkpoint_lines
    assert all("(distance to exit 2.80)" in line for line in checkpoint_lines)
    assert all(
        len(line) >= 11
        and line[0] == "["
        and line[3] == ":"
        and line[6] == ":"
        and line[9:11] == "] "
        for line in checkpoint_lines
    )

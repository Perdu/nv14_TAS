"""Regression tests for consistent blue starting points across search strategies."""
from __future__ import annotations

import sys

import pytest

import nv14_cli as cli
from nv14_auto import evaluate_replay_with_sentinel
from nv14_endpoint import EndpointGoal
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame, parse_level_string
from nv14_population import PopulationConfig, optimise_local_population
from nv14_random_splice import RandomSpliceConfig, optimise_random_splices
from nv14_replay import encode_complex_replay


def test_baseline_blue_and_best_still_green(capsys, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    cli._print_baseline_line("baseline frame 3", color=True)
    cli._print_best_line("new best", color=True)
    assert capsys.readouterr().out == (
        "\x1b[34mbaseline frame 3\x1b[0m\n"
        "\x1b[32mnew best\x1b[0m\n"
    )


@pytest.mark.parametrize("isatty,enabled", [(True, False), (False, True), (False, False)])
def test_baseline_plain_if_color_disabled_or_noninteractive(capsys, monkeypatch, isatty, enabled):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: isatty)
    cli._print_baseline_line("baseline frame 3", color=enabled)
    assert capsys.readouterr().out == "baseline frame 3\n"


def test_local_population_emits_baseline_before_search_results():
    level = parse_level_string("0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + "|5^60,60")
    frames = (InputFrame(),) * 15
    logs = []
    optimise_local_population(
        level, frames,
        goal=EndpointGoal(target_frame=10, objective="max-x"),
        frame_ranges=((0, 10),),
        config=PopulationConfig(iterations=2, beam=2, rounds=1, workers=1, repair_steps=0),
        progress=logs.append,
    )
    assert logs[0].startswith("[local:population:baseline] frame 10; score ")
    assert any(line.startswith("[local:population] seed ") for line in logs[1:])


def test_random_splice_reports_initial_baseline():
    from tests.test_random_splice import _baseline
    level, frames, _ = _baseline()
    logs = []
    optimise_random_splices(
        level, frames,
        RandomSpliceConfig(points=1, iterations=2, repair_iterations=2, rounds=1, beam=2),
        progress=logs.append,
    )
    assert logs[0].startswith("[auto:random-splice:baseline] verified completion at frame ")
    assert "distance to exit" in logs[0]


def test_local_windows_prints_baseline_before_search(tmp_path, monkeypatch, capsys):
    level = "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + "|5^60,60"
    frames = encode_complex_replay((InputFrame(),) * 12)
    source = tmp_path / "source.txt"
    source.write_text(f"$Test#baseline##{level}#{frames}#\n", encoding="utf-8")
    output = tmp_path / "result.txt"
    monkeypatch.setattr(sys, "argv", [
        "optimise.py", "local", str(source),
        "--target-frame", "9", "--passes", "1", "--window", "2", "--restarts", "1",
        "--output", str(output),
    ])
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    cli.main()
    lines = capsys.readouterr().out.splitlines()
    baselines = [line for line in lines if "baseline frame 9:" in line]
    assert len(baselines) == 1
    assert baselines[0].startswith("\x1b[34mbaseline frame 9:")
    assert output.exists()


def test_local_population_cli_baseline_is_blue_before_any_checkpoint(tmp_path, monkeypatch, capsys):
    level = "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + "|5^60,60"
    frames = encode_complex_replay((InputFrame(),) * 12)
    source = tmp_path / "source.txt"
    source.write_text(f"$Test#baseline##{level}#{frames}#\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "optimise.py", "local", str(source), "--search", "population",
        "--target-frame", "9", "--objective", "max-x", "--iterations", "2",
        "--beam", "2", "--rounds", "1", "--workers", "1", "--repair-steps", "0",
        "--output", str(tmp_path / "population_result.txt"),
    ])
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    cli.main()
    output = capsys.readouterr().out
    assert output.count("[local:population:baseline]") == 1
    assert "\x1b[34m[local:population:baseline]" in output
    # The baseline is available before an optional best checkpoint is saved.
    assert output.index("[local:population:baseline]") < output.index("[local:population] seed")


def test_full_auto_cli_baseline_is_blue(tmp_path, monkeypatch, capsys):
    from tests.test_auto_cli import _write_completed_input
    source = _write_completed_input(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "optimise.py", "auto", str(source),
        "--iterations", "0", "--beam", "2", "--output", str(tmp_path / "auto_result.txt"),
    ])
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    cli.main()
    output = capsys.readouterr().out
    assert output.startswith("\x1b[34m[auto:baseline] verifying source replay...")
    assert "\x1b[34mauto baseline finish tick:" in output


def test_auto_endpoint_cli_baseline_is_blue(tmp_path, monkeypatch, capsys):
    level = "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + "|5^60,60"
    frames = encode_complex_replay((InputFrame(),) * 12)
    source = tmp_path / "source.txt"
    source.write_text(f"$Test#baseline##{level}#{frames}#\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "optimise.py", "auto", str(source), "--auto-objective", "max-x",
        "--auto-target-frame", "9", "--iterations", "2", "--beam", "2",
        "--auto-runs", "1", "--workers", "1",
        "--output", str(tmp_path / "endpoint_result.txt"),
    ])
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    cli.main()
    output = capsys.readouterr().out
    assert "\x1b[34m" in output
    assert "[auto:baseline] source feasible" in output

"""CLI contracts for the opt-in bounded population strategy."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import nv14_cli as cli
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame
from nv14_objectives import AxisWindow
from nv14_replay import encode_complex_replay


def parse(*options: str):
    return cli.parse_arguments(["local", "source.txt", *options])


def test_defaults_keep_windows_and_existing_modes_unchanged():
    assert parse()._mode_configs.local.search == "windows"
    assert parse().window == 4
    assert parse().passes == 2
    assert parse().restarts == 10
    population = parse("--search", "population")._mode_configs.local
    assert (population.iterations, population.beam, population.rounds) == (10000, 32, 1)
    assert (population.stagnation_rounds, population.repair_steps,
            population.repair_lookback, population.mutation_span, population.top_results) == (20, 64, 32, 32, 1)
    auto = cli.parse_arguments(["auto", "source.txt"])
    jump = cli.parse_arguments(["jump-pattern", "source.txt"])
    assert auto.iterations == 5000
    assert jump.top_results == 10
    with pytest.raises(SystemExit):
        cli.parse_arguments(["jump-pattern", "source.txt", "--objective", "earliest-arrival"])


@pytest.mark.parametrize("option,value", [
    ("--iterations", "1"), ("--beam", "2"), ("--rounds", "1"),
    ("--stagnation-rounds", "2"), ("--repair-steps", "0"),
    ("--repair-lookback", "0"), ("--mutation-span", "3"),
    ("--top-results", "1"), ("--vx-window", "0:1"),
    ("--vy-window", "0:1"), ("--target-region", "0:1,0:1"),
    ("--arrival-start", "0"), ("--checkpoint", "state.json"),
])
def test_windows_rejects_every_explicit_population_control(option, value):
    with pytest.raises(SystemExit, match="require --search population"):
        parse(option, value)


@pytest.mark.parametrize("options", [
    ["--window", "4"], ["--passes", "2"], ["--restarts", "10"],
    ["--local-inputs", "all"], ["--window-shape", "contiguous"],
    ["--window-order", "forward"], ["--window-span", "8"],
    ["--windows-per-pass", "4"], ["--jump-start-mutation", "0"],
    ["--jump-length-mutation", "0"], ["--immutable-jumps", "2"],
    ["--physics-prune"], ["--minimum-improvement", "0"],
    ["--window-sh", "mixed"],  # argparse's accepted abbreviations must not bypass validation
])
def test_population_rejects_even_default_valued_window_controls(options):
    with pytest.raises(SystemExit, match="require --search windows"):
        parse("--search", "population", *options)


def test_population_toml_parses_geometry_controls_and_cli_override(tmp_path):
    config = tmp_path / "local.toml"
    config.write_text('''[local]
search = "population"
range = ["5:9", "12:15"]
target_frame = 20
objective = "earliest-arrival"
target_region = [40, 80, 100, 140]
arrival_start = 6
vx_window = [-2, 3]
vy_window = "-1:"
x_window = [40, 80]
top_results = 3
iterations = 40
beam = 8
rounds = 2
stagnation_rounds = 4
repair_steps = 5
repair_lookback = 8
mutation_span = 6
seed = "random"
checkpoint = "population.json"
resume = true
require_interaction = ["gold:0"]
avoid_interaction = ["trapdoor:any"]
''')
    local = parse("--config", str(config), "--iterations", "11")._mode_configs.local
    assert local.search == "population"
    assert local.frame_range == ("5:9", "12:15")
    assert local.target_region == (40, 80, 100, 140)
    assert local.vx_window == AxisWindow(-2, 3)
    assert local.vy_window == AxisWindow(-1, float("inf"))
    assert local.iterations == 11
    assert local.seed == "random"
    assert local.checkpoint_path == Path("population.json")
    assert local.resume
    assert local.require_interaction == ("gold:0",)
    assert local.avoid_interaction == ("trapdoor:any",)


def test_toml_strategy_conflicts_are_not_silently_ignored(tmp_path):
    config = tmp_path / "local.toml"
    config.write_text('[local]\nsearch = "population"\nphysics_prune = false\n')
    with pytest.raises(SystemExit, match="--physics-prune require --search windows"):
        parse("--config", str(config))
    config.write_text('[local]\nsearch = "population"\niterations = 10\n')
    with pytest.raises(SystemExit, match="--iterations require --search population"):
        parse("--config", str(config), "--search", "windows")


@pytest.mark.parametrize("options,message", [
    (["--resume"], "--resume requires --checkpoint"),
    (["--objective", "earliest-arrival"], "requires --target-region"),
    (["--target-region", "0:1,0:1"], "require --objective earliest-arrival"),
    (["--arrival-start", "1"], "require --objective earliest-arrival"),
    (["--iterations", "0"], "iterations must be at least 1"),
    (["--beam", "0"], "beam must be at least 1"),
    (["--top-results", "0"], "top-results must be at least 1"),
    (["--top-results", "4", "--beam", "3"], "top-results must not exceed beam"),
    (["--rounds", "-1"], "rounds must be non-negative"),
    (["--objective", "earliest-arrival", "--target-region", "0:1,0:1",
      "--arrival-start", "21", "--target-frame", "20"], "must not exceed"),
])
def test_population_invalid_configuration_is_rejected_before_loading_input(options, message):
    with pytest.raises(SystemExit, match=message):
        parse("--search", "population", *options)


@pytest.mark.parametrize("region", ["0:1", "0,1", ":1,0:1", "1:0,0:1", "0:1,0:inf", "nan:1,0:1"])
def test_target_region_requires_two_finite_ordered_axes(region):
    with pytest.raises((ValueError, TypeError)):
        cli.parse_target_region(region)


def test_ranked_destinations_and_checkpoint_all_have_alias_protection(tmp_path):
    config = cli.LocalConfig(search="population", top_results=3)
    output = tmp_path / "best.txt"
    protected_input = tmp_path / "best.rank02.txt"
    with pytest.raises(ValueError, match="rank 2 output and input"):
        cli._population_output_paths(config, input_path=protected_input, output_path=output,
                                     replay_output_path=None)
    with pytest.raises(ValueError, match="rank 2 output and rank 1 replay output"):
        cli._population_output_paths(config, input_path=tmp_path / "input.txt", output_path=output,
                                     replay_output_path=protected_input)
    config = cli.LocalConfig(search="population", checkpoint_path=tmp_path / "best.rank03.txt", top_results=3)
    with pytest.raises(ValueError, match="population checkpoint and rank 3 output"):
        cli._population_output_paths(config, input_path=tmp_path / "input.txt", output_path=output,
                                     replay_output_path=None)
    config = cli.LocalConfig(search="population", checkpoint_path=tmp_path / "local.toml")
    with pytest.raises(ValueError, match="population checkpoint and TOML"):
        cli._population_output_paths(config, input_path=tmp_path / "input.txt", output_path=output,
                                     replay_output_path=None, config_path=tmp_path / "local.toml")


@pytest.mark.parametrize("enemy_option,expected", [([], True), (["--no-simulate-enemies"], False)])
def test_population_enemy_default_and_dispatch(tmp_path, monkeypatch, enemy_option, expected):
    tiles = "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    level_string = f"{tiles}|5^60,134"
    packed = encode_complex_replay([InputFrame()] * 10)
    source = tmp_path / "source.txt"
    source.write_text(f"$Population CLI#tests##{level_string}#{packed}#\n")
    seen = {}
    real_parse = cli.parse_level_string

    def parse_level(text, **kwargs):
        seen["enemies"] = kwargs["simulate_enemies"]
        return real_parse(text, **kwargs)

    def population(*args, **kwargs):
        seen["dispatch"] = True
        assert args[3].search == "population"
        assert kwargs["output_path"] == tmp_path / "out.txt"

    monkeypatch.setattr(cli, "parse_level_string", parse_level)
    monkeypatch.setattr(cli, "_run_local_population", population)
    monkeypatch.setattr(sys, "argv", ["optimize_replay.py", "local", str(source),
        "--search", "population", "--target-frame", "5", "--output", str(tmp_path / "out.txt"),
        *enemy_option])
    cli.main()
    assert seen == {"enemies": expected, "dispatch": True}

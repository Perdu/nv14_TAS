from __future__ import annotations

from pathlib import Path

import pytest

import optimize_replay as opt


def _write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_auto_toml_config_supports_mode_aliases_and_cli_overrides(tmp_path) -> None:
    config = _write_config(
        tmp_path,
        """
[common]
workers = 8
retime = ["whole:+1"]

[auto]
objective = "highscore"
require_reference_gold = true
runs = 0
iterations = 10000
beam = 64
beam_repair_revisit_limit = 5
splice_repair_revisit_limit = 8
seed = "random"
deterministic = false
""",
    )

    args = opt.parse_arguments(
        [
            "auto",
            "input.txt",
            "--config",
            str(config),
            "-o",
            "output.txt",
            "--iterations",
            "7",
            "--auto-objective",
            "speedrun",
            "--retime",
            "120:-1",
        ]
    )

    assert args.output == Path("output.txt")
    assert args.workers == 8
    assert args.auto_objective == "speedrun"
    assert args.auto_require_reference_gold is True
    assert args.auto_runs == 0
    assert args.iterations == 7
    assert args.beam == 64
    assert args.auto_beam_repair_revisit_limit == 5
    assert args.auto_splice_repair_revisit_limit == 8
    assert args.seed == "random"
    assert args.auto_deterministic is False
    assert args.retime == [("whole", 1), (120, -1)]


def test_v300_auto_toml_parents_append_repeatable_cli_parents(tmp_path) -> None:
    config = _write_config(
        tmp_path,
        """
[auto]
parents = ["parent-b.ltm", "parent-c.ltm"]
""",
    )

    args = opt.parse_arguments(
        [
            "auto",
            "parent-a.ltm",
            "--config",
            str(config),
            "--auto-parent",
            "parent-d.ltm",
        ]
    )

    assert args.auto_parents == [
        Path("parent-b.ltm"),
        Path("parent-c.ltm"),
        Path("parent-d.ltm"),
    ]


def test_build_parser_applies_config_defaults_and_restores_plain_defaults(
    tmp_path,
) -> None:
    config = _write_config(tmp_path, "[auto]\niterations = 7\n")
    parser = opt.build_parser()

    configured = parser.parse_args(
        ["auto", "input.txt", "--config", str(config)]
    )
    plain = parser.parse_args(["auto", "input.txt"])

    assert configured.iterations == 7
    assert plain.iterations == 5000


def test_local_and_jump_pattern_toml_configs_parse_all_mode_specific_shapes(
    tmp_path,
) -> None:
    local_config = _write_config(
        tmp_path,
        """
[local]
target_frame = 71
range = "0:71"
objective = "min-distance"
target_point = [470.0, 432.0]
x_window = [0.0, 500.0]
window_shape = "sparse"
window_span = 12
windows_per_pass = 4
require_interaction = ["gold:0"]
avoid_interaction = ["trapdoor:any"]
python_resimulate = true
""",
    )
    local = opt.parse_arguments(
        ["local", "input.txt", "--config", str(local_config), "-o", "local.txt"]
    )
    assert local.target_frame == 71
    assert local.frame_range == "0:71"
    assert local.objective == "min-distance"
    assert local.target_point == (470.0, 432.0)
    assert str(local.x_window) == "0:500"
    assert local.window_shape == "sparse"
    assert local.window_span == 12
    assert local.windows_per_pass == 4
    assert local.require_interaction == ["gold:0"]
    assert local.avoid_interaction == ["trapdoor:any"]
    assert local.python_resimulate is True

    jump_config = _write_config(
        tmp_path,
        """
[jump-pattern]
target_frame = 175
range = "106:135"
jumps = [2, 3]
jump_length = [1, 8]
minimum_gap = 2
top_results = 4
fixed_jump_frames = [42, 73]
python_resimulate = true
""",
    )
    jump = opt.parse_arguments(
        [
            "jump-pattern",
            "input.txt",
            "--config",
            str(jump_config),
            "-o",
            "jump.txt",
        ]
    )
    assert jump.target_frame == 175
    assert jump.frame_range == "106:135"
    assert jump.jumps == (2, 3)
    assert jump.jump_length == (1, 8)
    assert jump.minimum_gap == 2
    assert jump.top_results == 4
    assert jump.python_resimulate is True
    assert jump.fixed_jump_frames == (42, 73)


def test_config_errors_are_reported_for_unknown_keys_and_invalid_values(tmp_path):
    unknown = _write_config(tmp_path, "[auto]\nnot_an_option = 1\n")
    with pytest.raises(SystemExit, match="unknown TOML option"):
        opt.parse_arguments(["auto", "input.txt", "--config", str(unknown)])

    invalid = _write_config(tmp_path, "[auto]\nworkers = 0\n")
    with pytest.raises(SystemExit, match="invalid value for TOML key"):
        opt.parse_arguments(["auto", "input.txt", "--config", str(invalid)])

    invalid_revisit = _write_config(
        tmp_path,
        "[auto]\nsplice_repair_revisit_limit = 0\n",
    )
    with pytest.raises(SystemExit, match="invalid value for TOML key"):
        opt.parse_arguments(
            ["auto", "input.txt", "--config", str(invalid_revisit)]
        )


@pytest.mark.parametrize("mode", ("auto", "local", "jump-pattern"))
def test_removed_non_strict_shapes_toml_option_is_rejected(
    tmp_path: Path, mode: str
) -> None:
    config = _write_config(tmp_path, "[common]\nnon_strict_shapes = true\n")

    with pytest.raises(SystemExit, match="unknown TOML option"):
        opt.parse_arguments([mode, "input.txt", "--config", str(config)])


@pytest.mark.parametrize(
    ("mode", "table", "setting"),
    (
        ("local", "local", "iterations = -1"),
        ("jump-pattern", "jump-pattern", 'seed = "random"'),
        ("local", "local", "deterministic = false"),
        ("local", "common", "iterations = -1"),
    ),
)
def test_wrong_mode_toml_options_are_rejected(
    tmp_path: Path, mode: str, table: str, setting: str
) -> None:
    config = _write_config(tmp_path, f"[{table}]\n{setting}\n")

    with pytest.raises(SystemExit, match="unknown TOML option"):
        opt.parse_arguments([mode, "input.txt", "--config", str(config)])


def test_examples_are_valid_for_their_selected_subcommands() -> None:
    root = Path(__file__).parents[1]
    for mode, filename in (
        ("auto", "highscore.toml"),
        ("local", "local.toml"),
        ("jump-pattern", "jump-pattern.toml"),
    ):
        args = opt.parse_arguments(
            [
                mode,
                "input.txt",
                "--config",
                str(root / "examples" / "config" / filename),
                "-o",
                "output.txt",
            ]
        )
        assert args.mode == mode


def test_parsed_namespace_materialises_typed_local_and_jump_configs(tmp_path) -> None:
    local_config = _write_config(
        tmp_path,
        """
[local]
target_frame = 71
range = "0:71"
window = 6
local_inputs = "direction"
window_order = "mixed"
jump_start_mutation = 1
workers = 2
""",
    )
    local_args = opt.parse_arguments(
        ["local", "input.txt", "--config", str(local_config)]
    )
    assert isinstance(local_args._mode_configs.local, opt.LocalConfig)
    assert local_args._mode_configs.local.window_size == 6
    assert local_args._mode_configs.local.jump_start_mutation == 1
    assert local_args._mode_configs.local.workers == 2

    jump_config = _write_config(
        tmp_path,
        """
[jump-pattern]
target_frame = 175
range = "106:135"
jumps = [2, 3]
jump_length = [1, 8]
workers = 2
""",
    )
    jump_args = opt.parse_arguments(
        ["jump-pattern", "input.txt", "--config", str(jump_config)]
    )
    assert isinstance(
        jump_args._mode_configs.jump_pattern, opt.JumpPatternConfig
    )
    assert jump_args._mode_configs.jump_pattern.jumps == (2, 3)
    assert jump_args._mode_configs.jump_pattern.jump_length == (1, 8)


def test_typed_mode_configs_validate_cross_field_constraints() -> None:
    with pytest.raises(ValueError, match="jump mutation requires"):
        opt.LocalConfig(jump_start_mutation=1)

    with pytest.raises(ValueError, match="window-span"):
        opt.LocalConfig(window_span=4)

    with pytest.raises(ValueError, match="minimum gap"):
        opt.JumpPatternConfig(minimum_gap=0)

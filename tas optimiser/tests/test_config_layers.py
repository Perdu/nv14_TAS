"""Layered TOML and unchanged [local] splice objective reuse in Auto."""
from pathlib import Path

import pytest

from nv14_cli import build_parser, parse_arguments


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_multiple_configs_overlay_in_order_for_auto_and_keep_cli_authority(tmp_path):
    first = _write(tmp_path / 'base.toml', '''[common]
workers = 8
simulate-enemies = true
[auto]
iterations = 10000
beam = 32
objective = "speedrun"
''')
    second = _write(tmp_path / 'more.toml', '''[common]
workers = 2
[auto]
beam = 16
''')
    parser = build_parser()
    args = parser.parse_args(['auto', 'input.txt', '--config', str(first),
                              '--config=' + str(second), '--beam', '64'])
    assert args.workers == 2
    assert args.beam == 64
    assert args.iterations == 10000
    assert args.config == second
    plain = parser.parse_args(['auto', 'input.txt'])
    assert plain.iterations == 5000
    assert plain.beam != 64


def test_existing_local_splice_file_imports_only_goal_values(tmp_path):
    base = _write(tmp_path / 'default.toml', '''[common]
workers = 8
simulate-enemies = true
[auto]
iterations = 10000
runs = 0
beam = 32
objective = "speedrun"
repair-window = 6
''')
    splice = _write(tmp_path / 'splice.toml', '''[local]
search = "population"
target_frame = 167
range = ":167"
simulate-enemies = false
objective = "earliest-arrival"
target_region = "382:422,377:397"
secondary_objective = "max-y"
require-interaction = ["switch", "testdoor:0", "testdoor:1", "testdoor:2"]
iterations = 13
beam = 5
''')
    args = parse_arguments(['auto', 'run.txt', '--config', str(base),
                            '--goal-config', str(splice), '--output', 'out.txt'])
    assert args.auto_objective == 'earliest-arrival'
    assert args.auto_target_frame == 167
    assert args.frame_range == ':167'
    assert args.auto_target_region == (382., 422., 377., 397.)
    assert args.auto_secondary_objective == 'max-y'
    assert args.auto_require_interaction == ['switch', 'testdoor:0', 'testdoor:1', 'testdoor:2']
    assert args.simulate_enemies is False
    assert args.workers == 8
    assert args.iterations == 10000  # not Local's 13
    assert args.beam == 32           # not Local's 5
    assert args.auto_runs == 0
    assert args.auto_repair_window == 6


def test_goal_config_priority_is_after_all_configs_before_cli(tmp_path):
    base = _write(tmp_path / 'base.toml', '''[goal]
objective = "max-x"
target-frame = 77
[auto]
objective = "speedrun"
''')
    local = _write(tmp_path / 'splice.toml', '''[local]
objective = "max-y"
target-frame = 100
''')
    result = parse_arguments(['auto', 'run.txt', '--goal-config', str(local),
                              '--config', str(base), '--target-frame', '123',
                              '--output', 'out.txt'])
    assert result.auto_objective == 'max-y'
    assert result.auto_target_frame == 123
    result = parse_arguments(['auto', 'run.txt', '--goal-config', str(local),
                              '--config', str(base), '--objective', 'min-y',
                              '--output', 'out.txt'])
    assert result.auto_objective == 'min-y'
    assert result.auto_target_frame == 100


def test_splice_import_does_not_change_other_modes(tmp_path):
    local = _write(tmp_path / 'splice.toml', '''[local]
search = "population"
objective = "earliest-arrival"
target_frame = 167
range = ":167"
target_region = "382:422,377:397"
''')
    result = parse_arguments(['local', 'run.txt', '--config', str(local), '--output', 'out.txt'])
    assert result.objective == 'earliest-arrival'
    assert result.target_frame == 167
    with pytest.raises(SystemExit, match='only supported in auto mode'):
        parse_arguments(['local', 'run.txt', '--goal-config', str(local)])


def test_goal_config_validation_missing_or_invalid_file(tmp_path):
    missing = tmp_path / 'missing.toml'
    with pytest.raises(SystemExit, match='not found'):
        parse_arguments(['auto', 'run.txt', '--goal-config', str(missing)])
    invalid = _write(tmp_path / 'invalid.toml', '[local]\ntarget-frame = "hello"\n')
    with pytest.raises(SystemExit, match='invalid value'):
        parse_arguments(['auto', 'run.txt', '--goal-config', str(invalid)])


def test_goal_config_not_applied_implicitly_as_second_regular_config(tmp_path):
    default = _write(tmp_path / 'base.toml', '[auto]\nobjective = "speedrun"\n')
    splice = _write(tmp_path / 'splice.toml', '''[local]
search="population"
objective="earliest-arrival"
target-frame=50
target-region="10:20,30:40"
''')
    result = parse_arguments(['auto', 'run.txt', '--config', str(default),
                              '--config', str(splice), '--output', 'out.txt'])
    assert result.auto_objective == 'speedrun'


def test_repeated_configs_validate_each_file(tmp_path):
    default = _write(tmp_path / 'base.toml', '[auto]\niterations=15\n')
    invalid = _write(tmp_path / 'bad.toml', '[auto]\nunknown_setting=2\n')
    with pytest.raises(SystemExit, match='unknown TOML option'):
        parse_arguments(['auto', 'run.txt', '--config', str(default),
                         '--config', str(invalid)])

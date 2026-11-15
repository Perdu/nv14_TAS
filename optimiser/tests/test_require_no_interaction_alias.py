"""The explicitly negative spelling shares the established avoidance constraint."""
from pathlib import Path
from nv14_cli import parse_arguments


def test_local_cli_and_toml_alias(tmp_path: Path):
    config = tmp_path / 'goal.toml'
    config.write_text('[local]\nrequire-no-interaction = ["testdoor:5"]\n')
    args = parse_arguments(['local', 'input.txt', '--config', str(config),
                            '--require-no-interaction', 'gold:0'])
    assert args.avoid_interaction == ['testdoor:5', 'gold:0']


def test_auto_goal_import_and_cli_alias(tmp_path: Path):
    config = tmp_path / 'goal.toml'
    config.write_text('[local]\nobjective = "earliest-arrival"\nrequire-no-interaction = ["testdoor:5"]\n')
    args = parse_arguments(['auto', 'input.txt', '--goal-config', str(config),
                            '--auto-require-no-interaction', 'gold:0'])
    assert args.auto_avoid_interaction == ['testdoor:5', 'gold:0']


def test_existing_avoid_interaction_spelling_unchanged():
    args = parse_arguments(['local', 'input.txt', '--avoid-interaction', 'testdoor:5'])
    assert args.avoid_interaction == ['testdoor:5']

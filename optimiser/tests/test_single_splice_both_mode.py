"""One Local goal gets exactly multi-splicer's shared Auto/Local backend."""

import pytest
from nv14_cli import parse_arguments, _single_splice_both_arguments
from tas import build_command


def test_both_maps_one_goal_into_both_backend_mode():
    args = parse_arguments(['both', 'source.ltm', '--config', 'examples/config.toml',
                            '--goal-config', '../splices/88-4/522.txt'])
    assert args._both_mode
    assert args.mode == 'auto'
    assert args.auto_splice_files == ('522',)
    assert args.auto_splice_mode == 'user'
    assert args.auto_splice_search == 'both'
    assert args.auto_runs == 1
    assert args.auto_splice_auto_stagnation_rounds == 5
    assert args.auto_splice_local_stagnation_rounds == 20


def test_both_preserves_explicit_patience_and_run_limit():
    args = parse_arguments(['both', 'source.ltm', '--goal-config=some/end.toml',
                            '--auto-runs', '3', '--splice-auto-stagnation-rounds', '8',
                            '--splice-local-stagnation-rounds', '12'])
    assert args.auto_runs == 3
    assert args.auto_splice_files == ('end',)
    assert args.auto_splice_auto_stagnation_rounds == 8
    assert args.auto_splice_local_stagnation_rounds == 12


def test_both_needs_local_goal_file():
    with pytest.raises(SystemExit, match='requires --goal-config'):
        _single_splice_both_arguments(['both', 'source.ltm'])


def test_tas_shortcut_for_both_uses_same_cli_mode():
    command = build_command('both', '88-4', '522', env={})
    assert 'both' in command
    assert command[command.index('--goal-config') + 1] == '../splices/88-4/522.txt'
    assert '--output' in command

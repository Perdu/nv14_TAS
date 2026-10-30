"""Named multi-splicer: deterministic file ordering, safety and CLI integration."""
from pathlib import Path
import sys

import pytest

from nv14_cli import (parse_arguments, _load_named_splice_stages,
                       _resolve_named_splice_files, main)
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from nv14_replay import encode_complex_replay
from nv14_auto import evaluate_replay_with_sentinel
from tests.test_random_splice import _baseline


def test_config_only_splice_array_selects_user_mode(tmp_path):
    cfg = tmp_path / "cfg.toml"
    cfg.write_text('[auto]\nsplice-files=["203","408","switch","end"]\n')
    args = parse_arguments(['auto', 'some.ltm', '--config', str(cfg)])
    assert args.auto_random_splice and args.auto_splice_mode == "user"
    assert args.auto_splice_files == ('203', '408', 'switch', 'end')
    assert args.auto_splice_directory is None


def test_named_files_exact_order_resolution_and_goal_parser(tmp_path):
    level, frames, _ = _baseline()
    names = ('203', '408', 'switch', 'end')
    for index, name in enumerate(names):
        (tmp_path / (name + ('.toml' if index == 2 else '.txt'))).write_text(
            f'[local]\nobjective="max-x"\ntarget-frame={12+index}\nrange="0:{12+index}"\n')
    args = parse_arguments(['auto', 'some.ltm', '--auto-splice-files', ','.join(names)])
    assert [name for name, _ in _resolve_named_splice_files(tmp_path, names)] == list(names)
    stages = _load_named_splice_stages(level, frames, args, tmp_path, names)
    assert tuple(s.name for s in stages) == names
    assert [s.goal.target_frame for s in stages] == [12, 13, 14, 15]


def test_missing_ambiguous_or_unsafe_files_rejected(tmp_path):
    (tmp_path / '203.txt').write_text('[local]\nobjective="min-y"\ntarget-frame=12\n')
    (tmp_path / '203.toml').write_text('[local]\nobjective="min-y"\ntarget-frame=12\n')
    with pytest.raises(ValueError, match='exactly one'):
        _resolve_named_splice_files(tmp_path, ('203',))
    with pytest.raises(SystemExit):
        parse_arguments(['auto', 'some.ltm', '--auto-splice-files', '203,203'])
    with pytest.raises(SystemExit):
        parse_arguments(['auto', 'some.ltm', '--auto-splice-files', '../secret'])


def test_named_stages_reject_missing_goal_definition(tmp_path):
    level, frames, _ = _baseline()
    (tmp_path / 'switch.txt').write_text('[local]\nobjective="min-y"\n')
    args = parse_arguments(['auto', 'some.ltm', '--auto-splice-files', 'switch'])
    with pytest.raises(ValueError, match='requires objective and target-frame'):
        _load_named_splice_stages(level, frames, args, tmp_path, ('switch',))


def test_completed_source_remains_valid_and_baseline_never_saved():
    level, source, base = _baseline()
    stages = [UserSpliceStage('first', EndpointGoal(10, 'max-x'), 0, 10),
              UserSpliceStage('end', EndpointGoal(14, 'max-x'), 11, 14)]
    saved = []
    result = optimise_user_splices(
        level, source, stages, RandomSpliceConfig(
            iterations=10, splice_rounds=1, rounds=1, workers=1, beam=8, seed=4),
        best_callback=saved.append)
    assert result.evaluations > 0
    checked = evaluate_replay_with_sentinel(level, result.frames)
    assert checked.valid and checked.finish_tick == len(result.frames)
    if saved:
        assert saved[-1] == result.frames
    assert result.improvements == len(saved)


def test_no_stage_skipping_when_an_earlier_requirement_is_broken(monkeypatch):
    level, source, baseline = _baseline()
    first_tick = 10
    initial_point = baseline.point(first_tick)
    # Achievable only by replay inputs of the starting source at this tick.
    stage0 = UserSpliceStage('first', EndpointGoal(
        first_tick, 'earliest-arrival',
        target_region=(initial_point.x-1, initial_point.x+1,
                       initial_point.y-1, initial_point.y+1)), 0, first_tick)
    stage1 = UserSpliceStage('end', EndpointGoal(14, 'max-x'), 0, 14)
    altered = tuple(InputFrame(left=True) for _ in source)
    import nv14_user_splice as us
    monkeypatch.setattr(us, '_local_search', lambda *a, **kw: (((altered, 14),), 1))
    result = us.optimise_user_splices(level, source, [stage0, stage1],
                    RandomSpliceConfig(rounds=1, workers=1, iterations=1))
    assert result.frames == tuple(source)
    assert result.improvements == 0


def test_cli_loads_ordered_goals_from_explicit_directory(tmp_path, monkeypatch):
    level, frames, _ = _baseline()
    input_path = tmp_path / 'source.txt'
    input_path.write_text(f'$test#author#{level.source_level_string}#'
                          f'{encode_complex_replay(frames)}#\n')
    goals = tmp_path / 'goals'; goals.mkdir()
    for name, tick in [('203', 12), ('end', 15)]:
        (goals / (name+'.txt')).write_text(
            f'[local]\nobjective="max-x"\ntarget-frame={tick}\nrange="0:{tick}"\n')
    config = tmp_path / 'config.toml'
    config.write_text('[auto]\nsplice-files=["203","end"]\n'
                      'runs=1\nsplice-iterations=8\nsplice-rounds=1\nbeam=8\nseed=0\n')
    out = tmp_path / 'optim.txt'
    monkeypatch.setattr(sys, 'argv', ['optimize_replay.py', 'auto', str(input_path),
        '--config', str(config), '--auto-splice-directory', str(goals),
        '--output', str(out), '--workers', '1'])
    main()
    # No no-op checkpoints, but a completed and validated improvement may be saved.
    if out.exists():
        from nv14_replay import parse_combined_level_replay, decode_complex_replay
        replay = parse_combined_level_replay(out.read_text())
        checked = evaluate_replay_with_sentinel(level, decode_complex_replay(replay.replay_string).frames)
        assert checked.valid and checked.finish_tick == len(decode_complex_replay(replay.replay_string).frames)

"""Random-splice must optimize goal-config endpoints, not silently optimize exits."""
from pathlib import Path
import random
import sys

import pytest

from nv14_auto import evaluate_replay_with_sentinel
from nv14_cli import main, parse_arguments
from nv14_endpoint import EndpointGoal, verify_endpoint
from nv14_engine import InputFrame
from nv14_random_splice import RandomSpliceConfig, choose_waypoints, optimise_random_splices
from nv14_replay import decode_complex_replay, encode_complex_replay, parse_combined_level_replay
from tests.test_random_splice import _baseline


def test_goal_config_overrides_speedrun_without_refusing_splice(tmp_path):
    base = tmp_path / 'random-splice.toml'
    base.write_text('[auto]\nobjective="speedrun"\nrandom-splice=true\nsplice-points=3\n')
    target = tmp_path / '694.txt'  # unchanged user convention: TOML saved as .txt
    target.write_text('[local]\nobjective="earliest-arrival"\n'
                      'target-frame=15\ntarget-region="70:120,105:160"\n'
                      'range=":15"\n')
    args = parse_arguments(['auto', '47-4.ltm', '--config', str(base),
                            '--goal-config', str(target), '--workers', '15'])
    assert args.auto_random_splice
    assert args.auto_objective == 'earliest-arrival'
    assert args.auto_target_frame == 15
    assert args.workers == 15


def test_highscore_random_splice_still_rejected():
    with pytest.raises(SystemExit, match='requires --objective speedrun'):
        parse_arguments(['auto', 'run.txt', '--auto-random-splice',
                         '--objective', 'highscore'])


def test_target_mode_improves_checkpoint_without_requiring_level_exit():
    level, _, _ = _baseline()
    # A source that doesn't finish is valid input for a bounded checkpoint.
    source = tuple([InputFrame()] * 5 + [InputFrame(right=True)] * 20)
    baseline = evaluate_replay_with_sentinel(level, source)
    assert baseline.finish_tick is None
    goal = EndpointGoal(target_frame=15, objective='max-x')
    original = verify_endpoint(level, source, goal)
    saved = []
    result = optimise_random_splices(
        level, source, RandomSpliceConfig(
            points=2, iterations=150, rounds=1, workers=1, beam=10),
        target_goal=goal, best_callback=saved.append,
    )
    checked = verify_endpoint(level, result.frames, goal)
    assert result.improvements >= 1
    assert result.evaluations > 0
    assert checked.feasible and checked.objective_key < original.objective_key
    assert saved[-1] == result.frames
    assert len(result.frames) == len(source)
    assert evaluate_replay_with_sentinel(level, result.frames).finish_tick is None


def test_earliest_arrival_can_be_reached_when_source_is_infeasible():
    level, _, _ = _baseline()
    source = tuple([InputFrame()] * 5 + [InputFrame(right=True)] * 25)
    goal = EndpointGoal(target_frame=15, objective='earliest-arrival',
                        target_region=(70., 120., 105., 160.))
    assert not verify_endpoint(level, source, goal).feasible
    outcome = optimise_random_splices(
        level, source, RandomSpliceConfig(
            points=2, iterations=180, rounds=1, workers=1, beam=10),
        target_goal=goal)
    verified = verify_endpoint(level, outcome.frames, goal)
    assert outcome.improvements >= 1
    assert verified.feasible
    assert verified.frame <= goal.target_frame


def test_range_restricts_anchors_and_edits():
    level, _, baseline = _baseline()
    cfg = RandomSpliceConfig(points=4, seed=1)
    chosen = choose_waypoints(baseline, cfg, random.Random(1),
                              min_frame=12, max_frame=19)
    assert len(chosen) == 4
    assert all(12 <= item.frame <= 19 for item in chosen)
    source = tuple([InputFrame()] * 5 + [InputFrame(right=True)] * 25)
    goal = EndpointGoal(target_frame=16, objective='max-x')
    original = source[:10]
    output = optimise_random_splices(
        level, source, RandomSpliceConfig(points=2, iterations=60, rounds=1),
        target_goal=goal, range_start=10, range_end=16)
    assert output.frames[:10] == original


def test_target_cli_writes_verified_checkpoint_and_preserves_source_length(tmp_path, monkeypatch):
    level, _, _ = _baseline()
    source = tuple([InputFrame()] * 5 + [InputFrame(right=True)] * 20)
    input_path = tmp_path / 'source.txt'
    input_path.write_text(f'$test#author#{level.source_level_string}#{encode_complex_replay(source)}#\n')
    config = tmp_path / 'random-splice.toml'
    config.write_text('[auto]\nobjective="speedrun"\nrandom-splice=true\n'
                      'runs=1\nsplice-points=2\nsplice-iterations=150\n'
                      'beam=10\nseed=0\n')
    goal_path = tmp_path / '694.txt'
    goal_path.write_text('[local]\nobjective="max-x"\ntarget_frame=15\n'
                         'range=":15"\n')
    output_path = tmp_path / 'optim.txt'
    monkeypatch.setattr(sys, 'argv', ['optimize_replay.py', 'auto', str(input_path),
                        '--config', str(config), '--goal-config', str(goal_path),
                        '--output', str(output_path), '--workers', '1'])
    main()
    assert output_path.exists()
    replay = parse_combined_level_replay(output_path.read_text()).replay_string
    improved = decode_complex_replay(replay).frames
    goal = EndpointGoal(15, 'max-x')
    assert len(improved) == len(source)
    assert verify_endpoint(level, improved, goal).objective_key < verify_endpoint(level, source, goal).objective_key


def test_complete_policy_refuses_publishing_incomplete_checkpoint():
    level, _, _ = _baseline()
    source = tuple([InputFrame()] * 5 + [InputFrame(right=True)] * 20)
    outcome = optimise_random_splices(
        level, source, RandomSpliceConfig(points=2, iterations=80, rounds=1),
        target_goal=EndpointGoal(15, 'max-x'), completion_policy='complete')
    assert outcome.improvements == 0
    assert outcome.frames == source

"""Conjunction of multiple successful jump requirements in one endpoint goal."""
from dataclasses import replace
from pathlib import Path
import pytest

from nv14_cli import parse_arguments
from nv14_endpoint import EndpointEvaluator, EndpointGoal, RequiredJump, verify_endpoint
from nv14_engine import InputFrame
from tests.test_required_jump_region import ALL, ORIGIN, floor_level, replay

JUMPS = (RequiredJump(ORIGIN, (5, 5)), RequiredJump(ORIGIN, (60, 60)))


def test_two_actual_jumps_both_required_in_earliest_goal():
    level, source = floor_level(), replay()
    goal = EndpointGoal(79, 'earliest-arrival', target_region=ALL, required_jumps=JUMPS)
    evaluator = EndpointEvaluator(level, goal, source, prefix_frame=5)
    result = evaluator.evaluate(source)
    assert result == evaluator.evaluate_reference(source)
    assert result.feasible and result.frame == 60
    assert result.jump_events == ((5, 396, 134), (60, 396, 134))
    assert result.missing_jump_indices == ()
    verify_endpoint(level, source, goal, expected=result, python_resimulate=True)
    incomplete = evaluator.evaluate(replay(jumps=(5,)))
    assert not incomplete.feasible
    assert incomplete.missing_jump_indices == (1,)
    assert incomplete.jump_events[0] == (5, 396, 134)
    assert incomplete.jump_events[1] is None


def test_fixed_frame_and_overlap():
    source = replay()
    overlapping = (RequiredJump(ORIGIN, (0, 10)), RequiredJump(ALL, (0, 10)))
    goal = EndpointGoal(79, required_jumps=overlapping)
    result = EndpointEvaluator(floor_level(), goal).evaluate(source)
    assert result.feasible
    assert result.jump_events == ((5, 396, 134), (5, 396, 134))
    # To demand distinct jumps, use non-overlapping intervals.
    assert not EndpointEvaluator(floor_level(), replace(goal, required_jumps=JUMPS)).evaluate(replay(jumps=(5,))).feasible


def test_arrival_eligibility_cannot_use_future_jump():
    goal = EndpointGoal(5, 'earliest-arrival', target_region=ALL,
                        required_jumps=(RequiredJump(ORIGIN, (5, 5)), RequiredJump(ORIGIN, (5, 5))))
    result = EndpointEvaluator(floor_level(), goal).evaluate(replay())
    assert result.feasible and result.frame == 5  # one actual jump matches both predicates
    goal = EndpointGoal(79, 'earliest-arrival', target_region=ALL,
                        required_jumps=(RequiredJump(ORIGIN, (5, 5)), RequiredJump(ORIGIN, (60, 60))),
                        arrival_start=0)
    result = EndpointEvaluator(floor_level(), goal).evaluate(replay())
    assert result.frame == 60


def test_prefix_cannot_change_and_python_verification_catches_mismatched_event():
    frames = replay()
    goal = EndpointGoal(79, required_jumps=JUMPS)
    evaluator = EndpointEvaluator(floor_level(), goal, frames, prefix_frame=10)
    assert evaluator.evaluate(frames).feasible
    changed = list(frames)
    changed[5] = InputFrame()
    with pytest.raises(ValueError, match='immutable'):
        evaluator.evaluate(changed)
    expected = EndpointEvaluator(floor_level(), goal).evaluate(frames)
    with pytest.raises(ValueError, match='verification mismatch'):
        verify_endpoint(floor_level(), replay(jumps=(5,)), goal, expected=expected)


@pytest.mark.parametrize('kwargs', [
    {'required_jumps': (RequiredJump(ORIGIN, (-1, 5)),)},
    {'required_jumps': (RequiredJump(ORIGIN, (5, 80)),)},
    {'required_jumps': (RequiredJump((5, 1, 0, 10), (5, 6)),)},
    {'required_jumps': (RequiredJump(ORIGIN, (5, 10)),), 'require_jump_region': ORIGIN},
])
def test_invalid_multiple_jumps(kwargs):
    with pytest.raises(ValueError):
        EndpointGoal(79, **kwargs)


def test_local_splice_toml_and_auto_goal_config(tmp_path):
    splice = tmp_path / 'splice.toml'
    splice.write_text('''[local]
search = "population"
target-frame = 79
range = ":79"
objective = "earliest-arrival"
target-region = "0:750,0:600"
[[local.require-jumps]]
region = "396:396,134:134"
frames = "5:5"
[[local.require-jumps]]
region = [396, 396, 134, 134]
frames = [60, 60]
''')
    args = parse_arguments(['local', 'run.txt', '--config', str(splice)])
    assert args._mode_configs.local.required_jumps == JUMPS
    common = tmp_path / 'defaults.toml'
    common.write_text('[auto]\nobjective="speedrun"\niterations=10\nbeam=8\nruns=1\n')
    args = parse_arguments(['auto', 'run.txt', '--config', str(common), '--goal-config', str(splice)])
    assert args.auto_objective == 'earliest-arrival'
    assert args.auto_require_jumps == list(JUMPS)
    assert args.iterations == 10
    assert args.beam == 8


def test_repeatable_cli_and_incompatible_modes(tmp_path):
    args = parse_arguments(['local', 'run.txt', '--search', 'population', '--target-frame', '79',
                            '--require-jumps', '396:396,134:134@5:5',
                            '--require-jumps', '396:396,134:134@60:60'])
    assert tuple(args.require_jumps) == JUMPS
    with pytest.raises(SystemExit):
        parse_arguments(['local', 'run.txt', '--require-jumps', '396:396,134:134@5:5'])
    with pytest.raises(SystemExit):
        parse_arguments(['auto', 'run.txt', '--require-jumps', '396:396,134:134@5:5'])
    with pytest.raises(SystemExit):
        parse_arguments(['local', 'run.txt', '--search', 'population', '--require-jumps', 'not-a-region'])


def test_local_auto_cli_use_same_splice_file(tmp_path):
    import subprocess
    import sys
    from nv14_replay import encode_complex_replay, parse_combined_level_replay, decode_complex_replay
    level = floor_level()
    source = tmp_path / 'source.txt'
    source.write_text(f'$Jumps#test##{level.source_level_string}#{encode_complex_replay(replay())}#\n')
    splice = tmp_path / 'splice.toml'
    splice.write_text('''[local]
search="population"
target-frame=79
range="5:79"
objective="earliest-arrival"
target-region="0:750,0:600"
[[local.require-jumps]]
region="396:396,134:134"
frames="5:5"
[[local.require-jumps]]
region="396:396,134:134"
frames="60:60"
''')
    auto_default = tmp_path/'auto.toml'
    auto_default.write_text('[auto]\nobjective="speedrun"\nruns=1\niterations=12\nbeam=8\nseed=17\n')
    goal = EndpointGoal(79, 'earliest-arrival', target_region=ALL,
                        arrival_start=5, required_jumps=JUMPS)
    for mode in ('auto','local'):
        output = tmp_path / f'{mode}.txt'
        options = (['--config', str(auto_default), '--goal-config', str(splice)] if mode == 'auto'
                   else ['--config', str(splice), '--iterations', '12', '--beam', '8',
                         '--rounds', '1', '--repair-steps', '0'])
        proc = subprocess.run([sys.executable, 'optimize_replay.py', mode, str(source),
                               *options, '--workers', '1', '--output', str(output)],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        packed = tuple(decode_complex_replay(parse_combined_level_replay(output.read_text()).replay_string).frames)
        assert verify_endpoint(level, packed, goal, python_resimulate=True).feasible


def test_checkpoint_resume_retains_multiple_jump_history(tmp_path):
    from nv14_population import PopulationConfig, optimise_local_population
    goal = EndpointGoal(79, 'earliest-arrival', target_region=ALL, arrival_start=5,
                        required_jumps=JUMPS)
    source = replay()
    cfg = PopulationConfig(iterations=12, beam=8, rounds=1, workers=1, seed=17,
                           repair_steps=0, checkpoint_path=tmp_path/'checkpoint.json')
    first = optimise_local_population(floor_level(), source, goal=goal,
                                      frame_ranges=((5,79),), config=cfg)
    again = optimise_local_population(floor_level(), source, goal=goal,
                                      frame_ranges=((5,79),), config=replace(cfg,resume=True))
    assert first.candidates == again.candidates

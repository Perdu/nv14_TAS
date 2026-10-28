"""Actual jump-origin requirements: native/reference parity and complete user workflows."""
from dataclasses import replace
import json
import math
from pathlib import Path
import random
import subprocess
import sys

import pytest

import nv14_cli as cli
from nv14_engine import InputFrame, parse_level_string
from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_native import require_native
from nv14_objectives import (AxisWindow, resolve_interaction_target,
                             resolve_interaction_requirement, resolve_interaction_avoidance,
                             TargetGeometry, TargetSelection)
from nv14_population import PopulationConfig, optimise_local_population
from nv14_replay import (encode_complex_replay, decode_complex_replay,
                         parse_combined_level_replay, editable_frames)
from tests.test_native_population_v427 import floor_level

ALL = (0, 750, 0, 600)
ORIGIN = (396, 396, 134, 134)


def replay(count=80, jumps=(5, 60), held=False):
    return tuple(InputFrame(jump=i in jumps or (held and i >= min(jumps))) for i in range(count))


def parity(level, frames, goal, prefix=0, python=True):
    evaluator = EndpointEvaluator(level, goal, frames, prefix)
    actual = evaluator.evaluate(frames)
    assert actual == evaluator.evaluate_reference(frames)
    assert actual == verify_endpoint(level, frames, goal, expected=actual, python_resimulate=python)
    return actual


@pytest.mark.parametrize('objective', ('max-x', 'min-x', 'max-y', 'min-y', 'min-distance', 'earliest-arrival'))
def test_all_positional_goals_require_an_actual_jump(objective):
    extra = ({'target_region': ALL} if objective == 'earliest-arrival' else
             {'target': TargetSelection('point', (TargetGeometry('point', 400, 134),))}
             if objective == 'min-distance' else {})
    goal = EndpointGoal(79, objective, require_jump_region=ORIGIN, **extra)
    actual = parity(floor_level(), replay(), goal)
    assert actual.feasible and actual.jump_event == (5, 396, 134) and not actual.missing_jump
    absent = parity(floor_level(), replay(jumps=()), goal)
    assert not absent.feasible and absent.jump_event is None and absent.missing_jump


@pytest.mark.parametrize('interval,feasible', [((5, 5), True), ((0, 4), False), ((6, 59), False), ((60, 60), True)])
def test_inclusive_frame_bounds_and_first_matching_jump(interval, feasible):
    goal = EndpointGoal(79, require_jump_region=ORIGIN, require_jump_frames=interval)
    actual = parity(floor_level(), replay(), goal)
    assert actual.feasible == feasible
    if feasible:
        assert actual.jump_event[0] == interval[0]


def test_origin_is_after_collisions_but_before_jump_displacement():
    level = floor_level()
    frames = replay()
    native = require_native().parse_level_string(level.source_level_string).initial_state()
    native.step_many(frames[:5])
    step = native.step(frames[5])
    assert step['jumped'] and step['jump_origin'] == (396, 134)
    assert native.player_snapshot()['pos'] == (396, 131)
    assert parity(level, frames, EndpointGoal(5, require_jump_region=ORIGIN)).feasible
    assert not parity(level, frames, EndpointGoal(5, require_jump_region=(396, 396, 131, 131))).feasible
    # An exact rectangle boundary counts; even one floating point step outside does not.
    assert not parity(level, frames, EndpointGoal(5, require_jump_region=(math.nextafter(396, math.inf), 397, 134, 134))).feasible
    # Horizontal movement is integrated before the jump; do not use the tick-start centre.
    frames = (InputFrame(right=True),) * 5 + (InputFrame(right=True, jump=True),)
    native = require_native().parse_level_string(level.source_level_string).initial_state()
    native.step_many(frames[:5])
    before = native.player_snapshot()['pos']
    step = native.step(frames[5])
    assert step['jumped'] and step['jump_origin'] != before
    x, y = step['jump_origin']
    assert parity(level, frames, EndpointGoal(5, require_jump_region=(x, x, y, y))).feasible


def test_held_button_airborne_press_and_passing_through_region_do_not_count():
    level = floor_level()
    assert not parity(level, replay(20, held=True), EndpointGoal(19, require_jump_region=ALL,
                      require_jump_frames=(6, 19))).feasible
    frames = list(replay(20))
    frames[7] = InputFrame(jump=False, jump_trigger=True)  # actual edge, but still jumping
    assert not parity(level, frames, EndpointGoal(19, require_jump_region=ALL,
                      require_jump_frames=(7, 7))).feasible
    assert not parity(level, replay(20), EndpointGoal(19, require_jump_region=(395, 397, 127, 129))).feasible


def test_explicit_trigger_counts_only_when_player_jump_executes():
    frames = list(replay(10, jumps=()))
    frames[5] = InputFrame(jump=False, jump_trigger=True)
    assert parity(floor_level(), frames, EndpointGoal(9, require_jump_region=ORIGIN)).jump_event == (5, 396, 134)


@pytest.mark.parametrize('prefix', (0, 4, 8, 80))
def test_cached_prefix_retains_jump_history(prefix):
    assert parity(floor_level(), replay(), EndpointGoal(79, require_jump_region=ORIGIN,
                  require_jump_frames=(0, 5)), prefix=prefix).feasible


def test_jump_before_arrival_start_and_same_tick_arrival():
    goal = EndpointGoal(79, 'earliest-arrival', target_region=ALL, arrival_start=20,
                        require_jump_region=ORIGIN, require_jump_frames=(5, 5))
    actual = parity(floor_level(), replay(), goal, prefix=15)
    assert actual.frame == 20 and actual.jump_event[0] == 5
    actual = parity(floor_level(), replay(), replace(goal, arrival_start=0))
    assert actual.frame == 5 and actual.jump_event[0] == 5


def test_later_jump_does_not_retroactively_validate_earlier_consumed_target():
    level = floor_level('0^396,134')
    goal = EndpointGoal(79, 'earliest-interaction',
                        interaction_target=resolve_interaction_target(level, 'gold:0'),
                        require_jump_region=ORIGIN)
    result = parity(level, replay(), goal)
    assert result.frame == 0 and result.terminal_frame == 79
    assert not result.feasible and result.jump_event is None and result.missing_jump
    assert result.interaction_events


def test_successful_jump_then_fresh_interaction_and_constraints():
    level = floor_level('0^520,134!0^100,100')
    frames = tuple(InputFrame(right=True, jump=i == 5) for i in range(110))
    goal = EndpointGoal(109, 'earliest-interaction',
                        interaction_target=resolve_interaction_target(level, 'gold:0'),
                        required_interactions=(resolve_interaction_requirement(level, 'gold:0'),),
                        avoided_interactions=(resolve_interaction_avoidance(level, 'gold:1'),),
                        require_jump_region=ALL, vy_window=AxisWindow(-9, 9))
    result = parity(level, frames, goal)
    assert result.feasible and result.jump_event[0] < result.frame


def test_dead_prefix_and_death_before_jump_are_not_feasible():
    result = parity(floor_level('12^396,134'), replay(),
                    EndpointGoal(79, require_jump_region=ALL), prefix=20)
    assert result.dead and not result.feasible and result.jump_event is None


@pytest.mark.parametrize('filename', ('example_00_1_speedrun.txt', 'example_44_0.txt', 'example_06_4_floorguards.txt'))
def test_real_replay_jump_origins_match_independent_python_physics(filename):
    combined = parse_combined_level_replay(Path(__file__).with_name(filename).read_text())
    level = parse_level_string(combined.level_string, simulate_enemies=True)
    frames = tuple(decode_complex_replay(combined.replay_string).frames)
    native = require_native().parse_level_string(level.source_level_string, simulate_enemies=True).initial_state()
    reference = level.initial_state()
    events = []
    for frame, button in enumerate(frames):
        before = reference.player.jump_events
        reference.step(button, level.tiles)
        step = native.step(button)
        assert step['jumped'] == (reference.player.jump_events > before)
        if step['jumped']:
            assert step['jump_origin'] == reference.player.last_jump_origin
            events.append((frame, *step['jump_origin']))
        else:
            assert step['jump_origin'] is None
        if frame >= 399 or step['dead'] or step['level_complete']:
            break
    assert events
    for frame, x, y in events[:8]:
        goal = EndpointGoal(frame, require_jump_region=(x, x, y, y), require_jump_frames=(frame, frame))
        assert parity(level, frames, goal).feasible


@pytest.mark.parametrize('seed', range(6))
def test_randomised_native_reference_all_fields(seed):
    rng = random.Random(seed)
    level = floor_level('0^410,134!0^300,134!11^700,134,370,134')
    frames = tuple(InputFrame(left=rng.random() < .4, right=rng.random() < .4,
                             jump=rng.random() < .3, jump_trigger=rng.choice((None, None, True, False)))
                   for _ in range(100))
    for name in ('max-x', 'earliest-arrival', 'earliest-interaction'):
        options = ({'target_region': (350, 450, 0, 140)} if name == 'earliest-arrival' else
                   {'interaction_target': resolve_interaction_target(level, 'gold:any')}
                   if name == 'earliest-interaction' else {})
        goal = EndpointGoal(99, name, require_jump_region=(390, 420, 120, 140),
                            require_jump_frames=(seed, 70), vx_window=AxisWindow(-4, 4), **options)
        parity(level, frames, goal, prefix=seed * 3)


@pytest.mark.parametrize('options', [
    ['--require-jump-frames', '1:3'],
    ['--require-jump-region', '0:1,0:1', '--require-jump-frames', '3:1'],
    ['--require-jump-region', '0:1,0:1', '--require-jump-frames', ':3'],
    ['--require-jump-region', '0:1,0:1', '--require-jump-frames', '1:'],
    ['--require-jump-region', '0:1,0:1', '--require-jump-frames', '1.0:3'],
    ['--require-jump-region', '0:1,0:1', '--require-jump-frames', '1:4', '--target-frame', '3'],
    ['--require-jump-region', 'nan:1,0:1'],
    ['--require-jump-region', '0:1,0:inf'],
])
def test_invalid_cli_configuration(options):
    with pytest.raises(SystemExit):
        cli.parse_arguments(['local', 'source.txt', '--search', 'population', *options])


@pytest.mark.parametrize('mode', ('windows', 'auto', 'jump-pattern'))
def test_other_search_modes_reject_options(mode):
    args = ['local', 'source.txt'] if mode == 'windows' else [mode, 'source.txt']
    with pytest.raises(SystemExit):
        cli.parse_arguments([*args, '--require-jump-region', '0:1,0:1'])


def test_toml_arrays_and_cli_override(tmp_path):
    config = tmp_path/'options.toml'
    config.write_text('[local]\nsearch="population"\nrequire_jump_region=[1,2,3,4]\nrequire_jump_frames=[5,6]\n')
    args = cli.parse_arguments(['local', 'source.txt', '--config', str(config), '--require-jump-frames', '7:8'])
    assert args._mode_configs.local.require_jump_region == (1, 2, 3, 4)
    assert args._mode_configs.local.require_jump_frames == (7, 8)


@pytest.mark.parametrize('kwargs', [
    {'require_jump_frames': (0, 5)},
    {'require_jump_region': ALL, 'require_jump_frames': (True, 5)},
    {'require_jump_region': ALL, 'require_jump_frames': (0, 20)},
    {'require_jump_region': (1, 0, 0, 1)},
    {'require_jump_region': (0, 1, 0, math.nan)},
])
def test_invalid_python_goals(kwargs):
    with pytest.raises(ValueError):
        EndpointGoal(19, **kwargs)


def test_default_population_interval_excludes_earlier_prefix_jump():
    goal = EndpointGoal(19, require_jump_region=ORIGIN)
    config = PopulationConfig(iterations=1, rounds=1, workers=1, repair_steps=0, seed=17)
    result = optimise_local_population(floor_level(), replay(20), goal=goal, frame_ranges=((10, 19),), config=config)
    assert not result.baseline.feasible and result.baseline.missing_jump
    result = optimise_local_population(floor_level(), replay(20), goal=replace(goal, require_jump_frames=(5, 5)),
                                      frame_ranges=((10, 19),), config=config)
    assert result.baseline.feasible and result.baseline.jump_event[0] == 5


@pytest.mark.parametrize('workers', (1, 2))
def test_population_discovers_and_verifies_jump_and_resumes_checkpoint(tmp_path, workers):
    checkpoint = tmp_path / 'population.json'
    goal = EndpointGoal(24, require_jump_region=(380, 415, 133, 135), require_jump_frames=(2, 20))
    frames = replay(30, jumps=())
    config = PopulationConfig(iterations=180, rounds=1, workers=workers, repair_steps=8,
                              seed=17, beam=8, top_results=2, checkpoint_path=checkpoint)
    result = optimise_local_population(floor_level(), frames, goal=goal, frame_ranges=((2, 24),), config=config)
    assert result.candidates and not result.baseline.feasible
    for candidate in result.candidates:
        verify_endpoint(floor_level(), candidate.frames, goal, candidate.evaluation, python_resimulate=True)
    resumed = optimise_local_population(floor_level(), frames, goal=goal, frame_ranges=((2, 24),),
                                       config=replace(config, resume=True))
    assert resumed.candidates == result.candidates
    with pytest.raises(ValueError, match='identity|goal|configuration|match|different'):
        optimise_local_population(floor_level(), frames, goal=replace(goal, require_jump_frames=(3, 20)),
                                  frame_ranges=((2, 24),), config=replace(config, resume=True))
    payload = json.loads(checkpoint.read_text())
    from nv14_checkpoint import canonical_json_bytes
    import hashlib
    payload['payload']['population'][0]['jump_event'] = [0, 396, 134]
    payload['sha256'] = hashlib.sha256(canonical_json_bytes(payload['payload'])).hexdigest()
    checkpoint.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='verification'):
        optimise_local_population(floor_level(), frames, goal=goal, frame_ranges=((2, 24),),
                                  config=replace(config, resume=True))


def test_cli_writes_packed_replay_and_reports_jump_origin(tmp_path):
    source, output = tmp_path/'source.txt', tmp_path/'result.txt'
    frames = replay(30)
    source.write_text(f'$Jump requirement#tests##{floor_level().source_level_string}#{encode_complex_replay(frames)}#\n')
    proc = subprocess.run([sys.executable, 'optimize_replay.py', 'local', str(source), '--search', 'population',
        '--range', '2:24', '--target-frame', '24', '--require-jump-region', '380:415,133:135',
        '--iterations', '50', '--workers', '1', '--seed', '17', '--python-resimulate', '--output', str(output)],
        text=True, capture_output=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'required jump at frame' in proc.stdout and 'eligible frames 2:24' in proc.stdout
    combined = parse_combined_level_replay(output.read_text())
    packed = decode_complex_replay(combined.replay_string).frames
    verify_endpoint(floor_level(), packed, EndpointGoal(24, require_jump_region=(380, 415, 133, 135),
                    require_jump_frames=(2, 24)), python_resimulate=True)


def test_native_scan_uses_one_python_result_with_requirement(monkeypatch):
    goal = EndpointGoal(79, 'earliest-arrival', target_region=ALL, arrival_start=40,
                        require_jump_region=ORIGIN)
    evaluator = EndpointEvaluator(floor_level(), goal, replay(), prefix_frame=20)
    calls = []
    original = evaluator._evaluate_state
    def capture(*a, **kw):
        calls.append(1)
        return original(*a, **kw)
    monkeypatch.setattr(evaluator, '_evaluate_state', capture)
    result = evaluator.evaluate(replay())
    assert result.feasible and calls == [1]


def test_unsatisfied_jump_distance_ties_stay_native(monkeypatch):
    frames = replay(256)
    goal = EndpointGoal(255, 'earliest-arrival', target_region=(700, 720, 120, 140),
                        require_jump_region=(100, 120, 130, 138))
    evaluator = EndpointEvaluator(floor_level(), goal, frames)
    expected = evaluator.evaluate_reference(frames)
    def unexpected(*args):
        raise AssertionError('identical jump-distance inputs must not cause a Python fallback')
    monkeypatch.setattr(evaluator, 'evaluate_reference', unexpected)
    assert evaluator.evaluate(frames) == expected

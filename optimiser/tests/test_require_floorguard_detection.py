"""Floor guard activation is a required transition, independent of drone acquisition."""
from dataclasses import replace
from pathlib import Path

import pytest

from nv14_cli import _resolve_floorguard_detection, parse_arguments, _auto_goal_from_options
from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_engine import parse_level_string
from nv14_native import require_native
from nv14_population import PopulationConfig, optimise_local_population
from nv14_replay import decode_complex_replay, parse_combined_level_replay


FIXTURE = Path(__file__).with_name("example_06_4_floorguards.txt")


def scene():
    combined = parse_combined_level_replay(FIXTURE.read_text())
    level = parse_level_string(combined.level_string, simulate_enemies=True)
    frames = decode_complex_replay(combined.replay_string).frames
    return level, frames


def both(level, frames, goal, *, prefix_frame=0):
    evaluator = EndpointEvaluator(level, goal, source_frames=frames, prefix_frame=prefix_frame)
    fast = evaluator.evaluate(frames)
    reference = evaluator.evaluate_reference(frames)
    assert fast == reference
    verify_endpoint(level, frames, goal, fast)
    return fast


def test_exact_activation_tick_vs_already_chasing():
    level, frames = scene()
    goal = EndpointGoal(target_frame=50, required_floorguard_detections=(30,),
                        require_floorguard_detection_frames=(27, 27))
    found = both(level, frames, goal)
    assert found.feasible and found.floorguard_detection_frames == (27,)
    assert found.missing_floorguard_indices == ()
    missed = both(level, frames, replace(goal, require_floorguard_detection_frames=(28, 30)),
                  prefix_frame=35)
    assert not missed.feasible
    assert missed.floorguard_detection_frames == (None,)
    assert missed.missing_floorguard_indices == (0,)


def test_reactivation_and_separate_guard_requirements():
    level, frames = scene()
    goal = EndpointGoal(target_frame=390, required_floorguard_detections=(30, 27),
                        require_floorguard_detection_frames=(0, 390))
    result = both(level, frames, goal, prefix_frame=350)
    assert result.feasible
    assert result.floorguard_detection_frames == (27, 320)
    # A later fresh acquisition of the second guard is also accepted.
    later = both(level, frames, EndpointGoal(target_frame=390,
                required_floorguard_detections=(27,), require_floorguard_detection_frames=(380, 380)))
    assert later.feasible and later.floorguard_detection_frames == (380,)


def test_earliest_arrival_cannot_finish_before_detection():
    level, frames = scene()
    goal = EndpointGoal(target_frame=55, objective="earliest-arrival", target_region=(0, 800, 0, 600),
                        arrival_start=0, required_floorguard_detections=(30,),
                        require_floorguard_detection_frames=(27, 27))
    result = both(level, frames, goal, prefix_frame=45)
    assert result.feasible
    assert result.frame == 27
    assert result.floorguard_detection_frames == (27,)
    missed = both(level, frames, replace(goal, require_floorguard_detection_frames=(28, 28)))
    assert not missed.feasible


def test_validation_and_simulate_enemies():
    for kwargs in (
        {'required_floorguard_detections': (27, 27)},
        {'required_floorguard_detections': (-1,)},
        {'require_floorguard_detection_frames': (10, 20)},
        {'required_floorguard_detections': (27,), 'require_floorguard_detection_frames': (20, 10)},
        {'required_floorguard_detections': (27,), 'require_floorguard_detection_frames': (0, 60)},
    ):
        with pytest.raises(ValueError, match='floorguard'):
            EndpointGoal(target_frame=50, **kwargs)
    level, frames = scene()
    disabled = parse_level_string(level.source_level_string, simulate_enemies=False)
    with pytest.raises(ValueError, match='simulate-enemies'):
        EndpointEvaluator(disabled, EndpointGoal(target_frame=50, required_floorguard_detections=(30,)))


def test_selector_index_is_per_object_type_and_rejects_unknown():
    level, _ = scene()
    assert _resolve_floorguard_detection(level, ['floorguard:0', 'floorguard:1']) == (27, 30)
    with pytest.raises(ValueError, match='ambiguous'):
        _resolve_floorguard_detection(level, ['floorguard'])
    with pytest.raises(ValueError, match='does not exist'):
        _resolve_floorguard_detection(level, ['floorguard:2'])
    with pytest.raises(ValueError, match='duplicate'):
        _resolve_floorguard_detection(level, ['floorguard:0', 'floorguard:0'])
    with pytest.raises(ValueError, match='floorguard:N'):
        _resolve_floorguard_detection(level, ['drone:0'])


def test_cli_and_named_goal_toml(tmp_path):
    level, frames = scene()
    goal_file = tmp_path / 'goal.toml'
    goal_file.write_text('''[local]
search = "population"
simulate-enemies = true
objective = "max-x"
target-frame = 50
require-floorguard-detection = ["floorguard:1"]
require-floorguard-detection-frames = [27, 27]
''')
    local = parse_arguments(['local', 'dummy.ltm', '--config', str(goal_file)])
    assert local.require_floorguard_detection == ['floorguard:1']
    assert local.require_floorguard_detection_frames == (27, 27)
    auto = parse_arguments(['auto', 'dummy.ltm', '--auto-objective', 'max-x',
                            '--goal-config', str(goal_file)])
    assert auto.auto_require_floorguard_detection == ['floorguard:1']
    assert auto.auto_require_floorguard_detection_frames == (27, 27)
    goal, _, _ = _auto_goal_from_options(require_native().parse_level_string(
        level.source_level_string, simulate_enemies=True), frames, auto)
    assert goal.required_floorguard_detections == (30,)
    assert goal.require_floorguard_detection_frames == (27, 27)
    cli = parse_arguments(['auto', 'dummy.ltm', '--auto-objective', 'max-x',
                           '--require-floorguard-detection', 'floorguard:0',
                           '--require-floorguard-detection-frames', '320:320'])
    assert cli.auto_require_floorguard_detection == ['floorguard:0']
    assert cli.auto_require_floorguard_detection_frames == (320, 320)


def test_population_immutable_prefix_does_not_require_future_detection():
    level, frames = scene()
    goal = EndpointGoal(target_frame=50, required_floorguard_detections=(30,),
                        require_floorguard_detection_frames=(27, 27))
    config = PopulationConfig(iterations=1, rounds=1, workers=1, repair_steps=0,
                              top_results=1, beam=4, seed=17)
    result = optimise_local_population(level, frames, goal=goal,
                                       frame_ranges=((20, 50),), config=config)
    assert result.baseline.feasible
    assert result.baseline.floorguard_detection_frames == (27,)

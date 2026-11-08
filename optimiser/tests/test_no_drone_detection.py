"""Forbidden drone acquisition is an inclusive history constraint (patch 88)."""
from dataclasses import replace

import pytest

from nv14_cli import parse_arguments, _resolve_drone_detection
from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_engine import parse_level_string
from nv14_population import PopulationConfig, optimise_local_population
from nv14_replay import decode_complex_replay
from tests.test_laser_drone import HALLOWED_LEVEL, HALLOWED_REPLAY


def scene():
    level = parse_level_string(HALLOWED_LEVEL, simulate_enemies=True)
    frames = decode_complex_replay(HALLOWED_REPLAY).frames
    return level, frames


def check(level, frames, goal, *, prefix_frame=0):
    evaluator = EndpointEvaluator(level, goal, source_frames=frames, prefix_frame=prefix_frame)
    native = evaluator.evaluate(frames)
    reference = evaluator.evaluate_reference(frames)
    # Includes detection history, feasibility, and comparable rank fields.
    verify_endpoint(level, frames, goal, native)
    return native


def test_inclusive_forbidden_interval_native_and_reference():
    level, frames = scene()
    goal = EndpointGoal(target_frame=37, forbidden_drone_detections=(6,),
                        no_drone_detection_frames=(27, 27))
    detected = check(level, frames, goal)
    assert not detected.feasible
    assert detected.forbidden_drone_detection_frames == (27,)
    assert detected.violated_drone_indices == (0,)

    # The drone has already acquired the player: a new rising edge is NOT
    # needed for forbidden detection to fail on the following tick.
    still_detecting = check(level, frames, replace(goal, no_drone_detection_frames=(28, 28)),
                            prefix_frame=28)
    assert not still_detecting.feasible
    assert still_detecting.forbidden_drone_detection_frames == (28,)

    clean = check(level, frames, replace(goal, no_drone_detection_frames=(26, 26)),
                  prefix_frame=27)
    assert clean.feasible
    assert clean.forbidden_drone_detection_frames == (None,)
    assert clean.violated_drone_indices == ()


def test_no_detection_requires_observing_the_whole_range():
    level, frames = scene()
    goal = EndpointGoal(target_frame=37, objective="earliest-arrival",
                        target_region=(0, 800, 0, 600), arrival_start=0, forbidden_drone_detections=(6,),
                        no_drone_detection_frames=(20, 26))
    result = check(level, frames, goal)
    assert result.feasible
    assert result.frame == 26
    assert not result.pending_no_drone_detection
    assert result.forbidden_drone_detection_frames == (None,)


def test_positive_and_negative_constraints_are_independent():
    level, frames = scene()
    goal = EndpointGoal(target_frame=37,
                        required_drone_detections=(6,), require_drone_detection_frames=(27, 27),
                        forbidden_drone_detections=(6,), no_drone_detection_frames=(0, 26))
    result = check(level, frames, goal)
    assert result.feasible
    assert result.drone_detection_frames == (27,)
    assert result.forbidden_drone_detection_frames == (None,)


def test_population_prefix_validation_does_not_require_future_no_detection():
    level, frames = scene()
    goal = EndpointGoal(target_frame=37, forbidden_drone_detections=(6,),
                        no_drone_detection_frames=(27, 27))
    config = PopulationConfig(iterations=1, rounds=1, workers=1, repair_steps=0,
                              top_results=1, beam=4, seed=17)
    result = optimise_local_population(level, frames, goal=goal,
                                       frame_ranges=((20, 37),), config=config)
    assert not result.baseline.feasible
    assert result.baseline.violated_drone_indices == (0,)


def test_no_drone_goal_validates_indices_windows_and_simulation():
    for kwargs in (
        {"forbidden_drone_detections": (6, 6)},
        {"forbidden_drone_detections": (-1,)},
        {"no_drone_detection_frames": (0, 1)},
        {"forbidden_drone_detections": (6,), "no_drone_detection_frames": (5, 4)},
        {"forbidden_drone_detections": (6,), "no_drone_detection_frames": (3, 38)},
    ):
        with pytest.raises(ValueError):
            EndpointGoal(target_frame=37, **kwargs)
    level = parse_level_string(HALLOWED_LEVEL, simulate_enemies=False)
    frames = decode_complex_replay(HALLOWED_REPLAY).frames
    with pytest.raises(ValueError, match="simulate-enemies"):
        EndpointEvaluator(level, EndpointGoal(target_frame=37, forbidden_drone_detections=(6,)))


def test_no_drone_config_and_cli_are_available_to_local_and_auto(tmp_path):
    level, _ = scene()
    local_config = tmp_path / "local.toml"
    local_config.write_text('''[local]
search = "population"
target-frame = 37
no-drone-detection = ["drone:0"]
no-drone-detection-frames = [20, 26]
''')
    local = parse_arguments(["local", "run.ltm", "--config", str(local_config)])
    assert local.no_drone_detection == ["drone:0"]
    assert local.no_drone_detection_frames == (20, 26)
    assert _resolve_drone_detection(level, local.no_drone_detection) == (6,)
    auto = parse_arguments(["auto", "run.ltm", "--auto-objective", "earliest-arrival",
                            "--auto-target-frame", "37", "--auto-target-region", "0:800,0:600",
                            "--no-drone-detection", "drone:0",
                            "--no-drone-detection-frames", "20:26"])
    assert auto.auto_no_drone_detection == ["drone:0"]
    assert auto.auto_no_drone_detection_frames == (20, 26)
    # Named Auto stages import the identical [local] goal syntax, including
    # drone selectors and interval, through --goal-config.
    imported = parse_arguments(["auto", "run.ltm", "--auto-objective", "max-x",
                                "--goal-config", str(local_config)])
    assert imported.auto_no_drone_detection == ["drone:0"]
    assert imported.auto_no_drone_detection_frames == (20, 26)

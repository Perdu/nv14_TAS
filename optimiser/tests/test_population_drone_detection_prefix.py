"""Regression: Local's immutable-prefix guard must not require future drone events."""

from dataclasses import replace

from nv14_endpoint import EndpointGoal
from nv14_engine import parse_level_string
from nv14_population import PopulationConfig, optimise_local_population
from nv14_replay import decode_complex_replay
from tests.test_laser_drone import HALLOWED_LEVEL, HALLOWED_REPLAY


def test_local_population_does_not_apply_drone_requirement_to_earlier_prefix():
    level = parse_level_string(HALLOWED_LEVEL, simulate_enemies=True)
    frames = decode_complex_replay(HALLOWED_REPLAY).frames
    goal = EndpointGoal(target_frame=37, required_drone_detections=(6,),
                        require_drone_detection_frames=(27, 27))
    config = PopulationConfig(iterations=1, rounds=1, workers=1, repair_steps=0,
                              top_results=1, beam=4, seed=17)

    # The immutable prefix ends at 19, but the required detection occurs at 27.
    # This formerly crashed during prefix-goal construction with the error
    # "require-drone-detection-frames must be inclusive bounds within target-frame".
    result = optimise_local_population(level, frames, goal=goal,
                                       frame_ranges=((20, 37),), config=config)
    assert result.baseline.feasible
    assert result.baseline.drone_detection_frames == (27,)

    # The actual stage still enforces the original detection window.
    missed = optimise_local_population(level, frames,
                                       goal=replace(goal, require_drone_detection_frames=(28, 28)),
                                       frame_ranges=((20, 37),), config=config)
    assert not missed.baseline.feasible
    assert missed.baseline.missing_drone_indices == (0,)

"""Exit-door distance as a secondary goal within Local population."""
from dataclasses import replace

import pytest

from nv14_auto import evaluate_replay_with_sentinel
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_engine import InputFrame
from nv14_objectives import resolve_interaction_target
from nv14_population import PopulationConfig, optimise_local_population
from tests.test_auto import _running_exit_level


def completed_variants():
    level = _running_exit_level()
    far = tuple([InputFrame(right=True)] * 24 + [InputFrame()]
                + [InputFrame(right=True)] * 4)
    close = tuple([InputFrame(right=True)] * 29)
    goal = EndpointGoal(target_frame=29, objective="earliest-interaction",
                        interaction_target=resolve_interaction_target(level, "exit:0"),
                        exit_distance_tiebreak=True)
    return level, far, close, goal


def test_exit_proximity_exactly_matches_auto_before_finish():
    level, far, close, goal = completed_variants()
    evaluator = EndpointEvaluator(level, goal)
    for frames in (far, close):
        endpoint = evaluator.evaluate(frames + (InputFrame(),))
        reference = evaluate_replay_with_sentinel(level, frames)
        assert endpoint.feasible
        assert endpoint.frame == reference.finish_tick == len(frames)
        assert endpoint.pre_finish_exit_distance == pytest.approx(
            reference.pre_finish_exit_distance, abs=1e-9)
    far_score = evaluator.evaluate(far + (InputFrame(),))
    close_score = evaluator.evaluate(close + (InputFrame(),))
    assert close_score.objective_key < far_score.objective_key
    assert close_score.progress_key < far_score.progress_key
    assert far_score.score == close_score.score == -29


def test_exit_distance_opt_in_does_not_affect_regular_local_goals():
    level, far, close, goal = completed_variants()
    plain = replace(goal, exit_distance_tiebreak=False)
    scorer = EndpointEvaluator(level, plain)
    a = scorer.evaluate(far + (InputFrame(),))
    b = scorer.evaluate(close + (InputFrame(),))
    assert a.pre_finish_exit_distance is None
    assert b.pre_finish_exit_distance is None
    assert a.objective_key == b.objective_key == (29.0, 0.0)
    assert a.progress_key == b.progress_key


def test_invalid_exit_distance_opt_in_rejected():
    level, _far, _close, goal = completed_variants()
    with pytest.raises(ValueError, match="exit-door"):
        replace(goal, objective="max-x", interaction_target=None)
    with pytest.raises(ValueError, match="exit-door"):
        replace(goal, exit_distance_tiebreak=True, interaction_target=None,
                objective="max-x")


def test_local_population_evolves_same_frame_door_gap_and_logs_both_distances():
    level, far, close, goal = completed_variants()
    frames = far + (InputFrame(),)
    progress = []
    result = optimise_local_population(
        level, frames, goal=goal, frame_ranges=((24, 24),),
        config=PopulationConfig(iterations=120, beam=12, rounds=2,
                                workers=1, repair_steps=16, top_results=4, seed=7),
        progress=progress.append)
    assert result.candidates
    assert result.candidates[0].evaluation.feasible
    assert result.candidates[0].evaluation.frame == 29
    assert (result.candidates[0].evaluation.pre_finish_exit_distance
            < result.baseline.pre_finish_exit_distance)
    assert any("pre-finish door gap=" in row for row in progress)
    assert any("closest surviving door gap=" in row for row in progress)
    verified = evaluate_replay_with_sentinel(level, result.candidates[0].frames[:-1])
    assert verified.valid
    assert verified.finish_tick == 29
    assert verified.pre_finish_exit_distance == pytest.approx(
        result.candidates[0].evaluation.pre_finish_exit_distance, abs=1e-9)


def test_exit_distance_goal_pickle_supported_in_parallel_workers():
    level, far, _close, goal = completed_variants()
    source = far + (InputFrame(),)
    result = optimise_local_population(
        level, source, goal=goal, frame_ranges=((24,24),),
        config=PopulationConfig(iterations=35, beam=8, rounds=2,
                                workers=2, repair_steps=6, top_results=4))
    assert result.candidates
    assert result.candidates[0].evaluation.pre_finish_exit_distance is not None
    assert result.candidates[0].evaluation.frame == 29

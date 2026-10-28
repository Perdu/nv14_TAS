"""Standalone Local TOML exposure of the exact exit-distance secondary goal."""
from dataclasses import replace
import math
import subprocess
import sys

import pytest

from nv14_auto import evaluate_replay_with_sentinel
from nv14_cli import LocalConfig, parse_arguments
from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_engine import InputFrame
from nv14_objectives import resolve_interaction_target
from nv14_population import PopulationConfig, optimise_local_population
from nv14_replay import encode_complex_replay, parse_combined_level_replay
from tests.test_auto import _running_exit_level
from tests.test_population_exit_distance import completed_variants


def exit_goal(level):
    return EndpointGoal(
        target_frame=29, objective="earliest-interaction",
        interaction_target=resolve_interaction_target(level, "exit:0.door"),
        secondary_objective="min-exit-distance",
    )


def test_exit_distance_secondary_ranks_equally_fast_completions():
    level, far, close, existing = completed_variants()
    goal = exit_goal(level)
    assert goal.exit_distance_tiebreak
    evaluator = EndpointEvaluator(level, goal)
    a = evaluator.evaluate(far + (InputFrame(),))
    b = evaluator.evaluate(close + (InputFrame(),))
    assert a.feasible and b.feasible
    assert a.frame == b.frame == 29
    assert b.secondary_value < a.secondary_value
    assert b.secondary_score > a.secondary_score
    assert b.progress_key < a.progress_key
    assert b.objective_key < a.objective_key
    door = level.static_world.entry_for_ref(level.static_world.exit_door_ref(0))
    radii = level.player.r + door.r
    assert radii == pytest.approx(22.0)
    for seq, result in ((far, a), (close, b)):
        auto = evaluate_replay_with_sentinel(level, seq)
        assert result.pre_finish_exit_distance == pytest.approx(auto.pre_finish_exit_distance, abs=1e-9)
        assert result.secondary_value == pytest.approx(auto.pre_finish_exit_distance - radii, abs=1e-9)
        assert result.secondary_score == pytest.approx(-result.secondary_value, abs=1e-9)
        assert verify_endpoint(level, seq + (InputFrame(),), goal, expected=result) == result
    assert b.pre_finish_exit_distance == pytest.approx(
        EndpointEvaluator(level, existing).evaluate(close + (InputFrame(),)).pre_finish_exit_distance,
    )


def test_exit_distance_secondary_population_evolves_and_reports_distance():
    level, far, _close, _goal = completed_variants()
    source = far + (InputFrame(),)
    messages = []
    result = optimise_local_population(
        level, source, goal=exit_goal(level), frame_ranges=((24, 24),),
        config=PopulationConfig(iterations=120, beam=12, rounds=2, workers=1,
                                repair_steps=16, top_results=4, seed=7),
        progress=messages.append,
    )
    assert result.candidates
    best = result.candidates[0].evaluation
    assert best.frame == 29
    assert best.secondary_value < result.baseline.secondary_value
    door = level.static_world.entry_for_ref(level.static_world.exit_door_ref(0))
    expected_gap = best.pre_finish_exit_distance - level.player.r - door.r
    assert best.secondary_value == pytest.approx(expected_gap)
    assert any("secondary min-exit-distance=" in line for line in messages)
    assert any("pre-finish door gap=" in line for line in messages)
    # The two labels must use the same physical distance definition.
    for line in messages:
        if "pre-finish door gap=" in line and "secondary min-exit-distance=" in line:
            import re
            printed_gap = float(re.search(r"pre-finish door gap=(-?[0-9.]+)px", line).group(1))
            printed_secondary = float(re.search(r"secondary min-exit-distance=([-0-9.eE]+)", line).group(1))
            assert printed_gap == pytest.approx(printed_secondary, abs=0.0051)


def test_exit_distance_secondary_toml_cli_and_saved_output(tmp_path):
    level, far, _close, _goal = completed_variants()
    original = far + (InputFrame(),)
    source = tmp_path / "source.txt"
    source.write_text(
        f"$Exit distance test#tests##{level.source_level_string}#"
        f"{encode_complex_replay(original)}#\n", encoding="utf-8",
    )
    toml = tmp_path / "splice.toml"
    toml.write_text(
        '[local]\nsearch = "population"\nobjective = "earliest-interaction"\n'
        'target_object = "exit:0.door"\nsecondary_objective = "min-exit-distance"\n'
        'range = "24:24"\ntarget_frame = 29\n'
        'iterations = 120\nbeam = 12\nrounds = 2\nworkers = 1\n'
        'repair_steps = 16\ntop_results = 1\nseed = 7\n', encoding="utf-8",
    )
    args = parse_arguments(["local", str(source), "--config", str(toml)])
    assert args._mode_configs.local.secondary_objective == "min-exit-distance"
    out = tmp_path / "optimised.txt"
    cmd = [sys.executable, "optimize_replay.py", "local", str(source),
           "--config", str(toml), "--output", str(out)]
    process = subprocess.run(cmd, cwd=__import__("pathlib").Path(__file__).resolve().parents[1],
                             text=True, capture_output=True, timeout=90)
    assert process.returncode == 0, process.stdout + process.stderr
    assert "interaction tie-break: min-exit-distance" in process.stdout
    assert "secondary min-exit-distance=" in process.stdout
    assert out.exists()
    candidate = parse_combined_level_replay(out.read_text())
    from nv14_replay import decode_complex_replay
    frames = decode_complex_replay(candidate.replay_string).frames
    assert len(frames) == len(original)
    def buttons(frame):
        return frame.left, frame.right, frame.jump
    assert all(buttons(a) == buttons(b) for a, b in
               zip(frames[:24] + frames[25:], original[:24] + original[25:]))
    scored = EndpointEvaluator(level, exit_goal(level)).evaluate(frames)
    assert scored.feasible and scored.frame == 29
    assert scored.secondary_value < EndpointEvaluator(level, exit_goal(level)).evaluate(original).secondary_value


@pytest.mark.parametrize("selector", ("gold:0", "exit:0.switch"))
def test_secondary_rejects_non_exit_door_interaction_target(selector):
    level = _running_exit_level()
    if selector == "gold:0":
        from nv14_engine import parse_level_string
        level = parse_level_string(level.source_level_string + "!0^100,100", simulate_enemies=False)
    target = resolve_interaction_target(level, selector)
    with pytest.raises(ValueError, match="exit-door target"):
        EndpointGoal(target_frame=29, objective="earliest-interaction",
                     interaction_target=target, secondary_objective="min-exit-distance")


def test_secondary_rejects_arrival_and_other_goal_types():
    with pytest.raises(ValueError, match="earliest-interaction"):
        EndpointGoal(target_frame=10, objective="earliest-arrival",
                     target_region=(0, 100, 0, 100), secondary_objective="min-exit-distance")
    with pytest.raises(ValueError, match="earliest-interaction"):
        LocalConfig(search="population", objective="earliest-arrival",
                    target_region=(0, 100, 0, 100), secondary_objective="min-exit-distance")


def test_secondary_is_not_applied_to_infeasible_endpoints():
    level, far, close, _goal = completed_variants()
    goal = replace(exit_goal(level), target_frame=20)
    evaluation = EndpointEvaluator(level, goal).evaluate(close + (InputFrame(),))
    assert not evaluation.feasible
    assert evaluation.pre_finish_exit_distance is None
    assert evaluation.secondary_value == 0.0


def test_min_exit_distance_prints_edge_gap_instead_of_centre_distance():
    level, _far, close, _goal = completed_variants()
    evaluation = EndpointEvaluator(level, exit_goal(level)).evaluate(close + (InputFrame(),))
    door = level.static_world.entry_for_ref(level.static_world.exit_door_ref(0))
    assert level.player.r == 10.0
    assert door.r == 12.0
    assert evaluation.pre_finish_exit_distance - evaluation.secondary_value == pytest.approx(22.0)
    assert evaluation.secondary_value == pytest.approx(evaluation.pre_finish_exit_distance - 22.0)
    assert evaluation.progress_key == (0, 29.0, evaluation.secondary_value)
    assert evaluation.objective_key[:2] == (29.0, evaluation.secondary_value)

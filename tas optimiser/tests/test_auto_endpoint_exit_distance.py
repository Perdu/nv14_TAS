"""Endpoint Auto presents the same signed door-edge gap as finished-run Auto."""
from dataclasses import replace
import math
import subprocess
import sys
from pathlib import Path

import pytest

from nv14_auto_endpoint import endpoint_exit_edge_distance, optimise_auto_endpoint_campaign, AutoEndpointConfig
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, APP_TILE_SCALE, InputFrame, parse_level_string
from nv14_objectives import resolve_target_object, resolve_interaction_target
from nv14_replay import encode_complex_replay

ROOT = Path(__file__).resolve().parents[1]
LEVEL = ("0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
         + "|5^60,60!11^100,100,120,100!11^300,100,320,100")


def test_exit_target_distance_uses_requested_door_and_signed_edges():
    level = parse_level_string(LEVEL)
    source = (InputFrame(),) * 16
    goal = EndpointGoal(12, objective="min-distance",
                        target=resolve_target_object(level, "exit:1"))
    evaluation = EndpointEvaluator(level, goal).evaluate(source)
    # Standing on exit:0 must not be shown as standing on targeted exit:1.
    at_first = replace(evaluation, x=100., y=100.)
    expected = 200. - level.player.r - APP_TILE_SCALE
    assert endpoint_exit_edge_distance(level, goal, at_first) == pytest.approx(expected)
    at_second = replace(evaluation, x=300., y=100.)
    assert endpoint_exit_edge_distance(level, goal, at_second) == pytest.approx(
        -level.player.r - APP_TILE_SCALE)


def test_non_exit_goal_hides_door_distance_even_when_level_contains_exits():
    level = parse_level_string(LEVEL)
    source = (InputFrame(),) * 16
    goal = EndpointGoal(12, objective="max-x")
    evaluation = EndpointEvaluator(level, goal).evaluate(source)
    at_second = replace(evaluation, x=303., y=104.)
    assert endpoint_exit_edge_distance(level, goal, at_second) is None
    switch_goal = EndpointGoal(12, objective="min-distance",
                               target=resolve_target_object(level, "exit:0.switch"))
    assert endpoint_exit_edge_distance(level, switch_goal, at_second) is None
    non_exit_goal = EndpointGoal(12, objective="min-distance",
                                 target=resolve_target_object(level, "player:0"))
    assert endpoint_exit_edge_distance(level, non_exit_goal, at_second) is None
    empty_level = parse_level_string("0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + "|5^60,60")
    assert endpoint_exit_edge_distance(empty_level, goal, at_second) is None
    assert endpoint_exit_edge_distance(level, goal, replace(at_second, x=math.nan)) is None


def test_exit_event_prefers_precise_native_pre_finish_distance():
    level = parse_level_string(LEVEL)
    source = (InputFrame(),) * 16
    goal = EndpointGoal(12, objective="earliest-interaction",
                        interaction_target=resolve_interaction_target(level, "exit:1.door"))
    evaluation = EndpointEvaluator(level, goal).evaluate(source)
    fake = replace(evaluation, pre_finish_exit_distance=25.5,
                   completed_exit_index=1, x=999., y=999.)
    assert endpoint_exit_edge_distance(level, goal, fake) == pytest.approx(
        25.5 - level.player.r - APP_TILE_SCALE)


def test_endpoint_campaign_baseline_and_progress_include_exit_gap():
    level = parse_level_string(LEVEL)
    goal = EndpointGoal(12, objective="min-distance",
                        target=resolve_target_object(level, "exit:1"))
    updates = []
    optimise_auto_endpoint_campaign(
        level, (InputFrame(),) * 16, goal,
        AutoEndpointConfig(iterations=5, beam_width=4, range_end=12, repair_steps=0),
        workers=1, runs=1, progress=updates.append,
    )
    assert any("baseline: source feasible" in line and "(distance to exit " in line
               for line in updates)
    assert any("best frame" in line and "(distance to exit " in line
               for line in updates)


def test_cli_exit_splice_shows_door_distance_in_baseline_and_summary(tmp_path):
    source = tmp_path / "run.txt"
    source.write_text(f"$Test#tests##{LEVEL}#" + encode_complex_replay([InputFrame()] * 4)
                      + "#\n", encoding="utf-8")
    goal = tmp_path / "splice.toml"
    goal.write_text('[local]\nobjective = "min-distance"\n'
                    'target-object = "exit:1"\n'
                    'target-frame = 7\nrange = ":7"\n', encoding="utf-8")
    output = tmp_path / "out.txt"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "optimize_replay.py"), "auto", str(source),
         "--goal-config", str(goal), "--output", str(output),
         "--workers", "1", "--iterations", "6", "--beam", "4", "--auto-runs", "1"],
        cwd=ROOT, capture_output=True, text=True, timeout=35)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "[auto:baseline]" in proc.stdout
    assert "(distance to exit " in proc.stdout
    assert "endpoint search complete" in proc.stdout
    assert "appended 4 neutral" in proc.stdout


def test_cli_non_exit_splice_hides_door_distance_in_progress_and_summary(tmp_path):
    source = tmp_path / "run.txt"
    source.write_text(f"$Test#tests##{LEVEL}#" + encode_complex_replay([InputFrame()] * 25)
                      + "#\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "optimize_replay.py"), "auto", str(source),
         "--objective", "max-x", "--target-frame", "20", "--range", ":20",
         "--output", str(tmp_path / "out.txt"), "--workers", "1",
         "--iterations", "250", "--beam", "8", "--auto-runs", "1"],
        cwd=ROOT, capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
    checkpoints = [line for line in result.stdout.splitlines()
                   if "[auto:checkpoint] saved best" in line]
    assert checkpoints and all("(distance to exit " not in line for line in checkpoints)
    assert any("[auto:beam]" in line for line in result.stdout.splitlines())
    assert "distance to exit" not in result.stdout


def test_exit_any_and_exit_interaction_are_targeted_but_other_interactions_are_not():
    level = parse_level_string(LEVEL)
    source = (InputFrame(),) * 16
    exit_any = EndpointGoal(12, objective="min-distance",
                            target=resolve_target_object(level, "exit:any"))
    candidate = replace(EndpointEvaluator(level, exit_any).evaluate(source),
                        x=103., y=104.)
    assert endpoint_exit_edge_distance(level, exit_any, candidate) == pytest.approx(
        5. - level.player.r - APP_TILE_SCALE)
    exit_interaction = EndpointGoal(12, objective="earliest-interaction",
                                    interaction_target=resolve_interaction_target(level, "exit:1.door"))
    assert endpoint_exit_edge_distance(level, exit_interaction, candidate) == pytest.approx(
        math.hypot(197., 4.) - level.player.r - APP_TILE_SCALE)
    switch_interaction = EndpointGoal(12, objective="earliest-interaction",
                                      interaction_target=resolve_interaction_target(level, "switch:0"))
    assert endpoint_exit_edge_distance(level, switch_interaction, candidate) is None

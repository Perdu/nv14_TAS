"""Native endpoint selection must preserve the original scorer and search order."""
from dataclasses import replace
from itertools import product
from pathlib import Path
import math
import random

import pytest

from nv14_engine import InputFrame, parse_level_string
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_native import require_native
from nv14_objectives import (AxisWindow, resolve_interaction_requirement,
                             resolve_interaction_avoidance, resolve_interaction_target,
                             TargetGeometry, TargetSelection)
from nv14_population import PopulationConfig, _input_key, optimise_local_population
from nv14_replay import parse_combined_level_replay, decode_complex_replay


def floor_level(objects=""):
    tiles = ["0"] * 713
    for x in range(31):
        tiles[x * 23 + 5] = "1"
    return parse_level_string("".join(tiles) + "|5^396,134" + ("!" + objects if objects else ""),
                              simulate_enemies=True)


def assert_parity(level, frames, goal, prefix=0):
    evaluator = EndpointEvaluator(level, goal, frames, prefix)
    actual = evaluator.evaluate(frames)
    expected = evaluator.evaluate_reference(frames)
    assert actual == expected
    return actual


def test_lossless_input_packing_and_fused_bounds_validation():
    native = require_native()
    frames = tuple(InputFrame(l, r, j, t) for l, r, j, t in
                   product((False, True), (False, True), (False, True), (None, False, True)))
    expected = bytes(int(f.left) | int(f.right) << 1 | int(f.jump) << 2 |
                     int(bool(f.jump_trigger)) << 3 | int(f.jump_trigger is None) << 4 for f in frames)
    assert _input_key(frames) == expected
    assert native.population_input_key(frames, frames, bytes(len(frames))) == (expected, 0)
    copied = tuple(replace(f) for f in frames)
    assert native.population_input_key(copied, frames, bytes(len(frames)))[1] == 0
    changed = (InputFrame(True, True, True, True),) + frames[1:]
    with pytest.raises(ValueError, match="outside"):
        native.population_input_key(changed, frames, bytes(len(frames)))
    assert native.population_input_key(changed, frames, b"\1" + bytes(len(frames) - 1))[1] == 1
    with pytest.raises(ValueError, match="length"):
        native.population_input_key(frames[:-1], frames, bytes(len(frames)))


@pytest.mark.parametrize("seed", range(12))
def test_randomised_endpoint_and_event_scans_match_all_reference_fields(seed):
    level = floor_level("0^410,134!0^450,134!0^300,134!11^700,134,370,134!"
                        "9^425,134,0,0,25,5,1,0,0!9^325,134,0,1,27,5,0,0,0")
    rng = random.Random(seed)
    choices = tuple(InputFrame(l, r, j, t) for l, r, j, t in
                    product((False, True), (False, True), (False, True), (None, False, True)))
    frames = tuple(rng.choice(choices) if i % 9 == 0 else InputFrame(right=seed % 2 == 0,
                   left=seed % 2 == 1, jump=i % 35 < 5) for i in range(100))
    required = (resolve_interaction_requirement(level, "gold:any"),)
    avoided = (resolve_interaction_avoidance(level, "trapdoor:any"),)
    goals = [EndpointGoal(89, name) for name in ("max-x", "min-x", "max-y", "min-y")]
    goals.append(EndpointGoal(89, "min-distance", target=TargetSelection("point",
                            (TargetGeometry("point", 390, 134), TargetGeometry("point", 200, 50)))))
    for secondary in (None, "max-x", "min-y", "max-vx", "min-vy"):
        goals.append(EndpointGoal(89, "earliest-arrival", target_region=(350, 450, 20, 140),
                                 arrival_start=seed * 3, required_interactions=required,
                                 avoided_interactions=avoided, secondary_objective=secondary,
                                 vx_window=AxisWindow(-4, 3), vy_window=AxisWindow(-5, 4)))
    for selector in ("gold:any", "switch:0", "testdoor:any", "exit:0.door"):
        goals.append(EndpointGoal(89, "earliest-interaction", arrival_start=seed,
                     interaction_target=resolve_interaction_target(level, selector),
                     vx_window=AxisWindow(-6, 6), required_interactions=required if seed % 2 else (),
                     avoided_interactions=avoided))
    for goal in goals:
        assert_parity(level, frames, goal, prefix=seed + 1)


@pytest.mark.parametrize("filename", ("example_00_1_speedrun.txt", "example_44_0.txt",
                                     "example_06_4_floorguards.txt", "laser_stale_endpoint.txt"))
def test_real_enemy_replay_scans_match_reference(filename):
    replay = parse_combined_level_replay(Path(__file__).with_name(filename).read_text())
    level = parse_level_string(replay.level_string, simulate_enemies=True)
    frames = tuple(decode_complex_replay(replay.replay_string).frames)
    deadline = min(399, len(frames) - 1)
    sample = EndpointEvaluator(level, EndpointGoal(deadline // 2)).evaluate_reference(frames)
    for region in ((sample.x - 1, sample.x + 1, sample.y - 1, sample.y + 1),
                   (-10, -5, -10, -5)):
        for arrival_start in (0, deadline // 4):
            goal = EndpointGoal(deadline, "earliest-arrival", target_region=region,
                                arrival_start=arrival_start, secondary_objective="max-vx")
            assert_parity(level, frames, goal, prefix=deadline // 3)


def test_native_scan_builds_only_one_public_evaluation(monkeypatch):
    level = floor_level()
    frames = (InputFrame(right=True),) * 100
    goal = EndpointGoal(99, "earliest-arrival", target_region=(650, 655, 0, 140))
    evaluator = EndpointEvaluator(level, goal)
    called = []
    original = evaluator._evaluate_state
    def capture(*args, **kwargs):
        called.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(evaluator, "_evaluate_state", capture)
    evaluator.evaluate(frames)
    assert len(called) == 1


def test_precision_sensitive_rankings_use_original_scorer(monkeypatch):
    level = floor_level()
    frames = (InputFrame(right=True),) * 30
    goal = EndpointGoal(29, "earliest-arrival", target_region=(1e15, 1e15, 0, 140))
    evaluator = EndpointEvaluator(level, goal)
    key = _input_key(frames)
    assert evaluator._native_plan.scan(evaluator._prefix, key)[-1]
    expected = evaluator.evaluate_reference(frames)
    calls = []
    original = evaluator.evaluate_reference
    def capture(values):
        calls.append(1)
        return original(values)
    monkeypatch.setattr(evaluator, "evaluate_reference", capture)
    assert evaluator.evaluate(frames) == expected
    assert calls == [1]


def test_duplicate_requirements_and_avoidances_are_counted_once():
    level = floor_level("0^100,100!0^396,134")
    frames = (InputFrame(),) * 20
    required = resolve_interaction_requirement(level, "gold:0")
    avoided = resolve_interaction_avoidance(level, "gold:1")
    goal = EndpointGoal(19, "earliest-arrival", target_region=(0, 700, 0, 600),
                        required_interactions=(required, required), avoided_interactions=(avoided, avoided))
    result = assert_parity(level, frames, goal)
    assert len(result.missing_interactions) == len(result.violated_interactions) == 1


@pytest.mark.parametrize("prefix", (0, 10))
def test_prefix_death_before_arrival_window_preserves_terminal_result(prefix):
    level = floor_level("12^396,134")
    frames = (InputFrame(),) * 20
    goal = EndpointGoal(19, "earliest-arrival", arrival_start=10, target_region=(0, 700, 0, 600))
    result = assert_parity(level, frames, goal, prefix=prefix)
    assert result.dead and not result.feasible and result.frame == 0


@pytest.mark.parametrize("objective", ("earliest-arrival", "earliest-interaction", "max-x"))
def test_seeded_search_keeps_exact_population_and_evaluation_counts(monkeypatch, objective):
    level = floor_level("0^430,134!0^300,134")
    frames = (InputFrame(),) * 100
    kwargs = ({"target_region": (425, 440, 0, 140)} if objective == "earliest-arrival" else
              {"interaction_target": resolve_interaction_target(level, "gold:any")}
              if objective == "earliest-interaction" else {})
    goal = EndpointGoal(79, objective, **kwargs)
    config = PopulationConfig(iterations=160, rounds=2, workers=1, beam=8, repair_steps=12,
                              top_results=3, seed=73)
    fast = optimise_local_population(level, frames, goal=goal, frame_ranges=((0, 20), (30, 79)), config=config)
    monkeypatch.setattr(EndpointEvaluator, "_evaluate_packed",
                        lambda self, key, frames: self.evaluate_reference(frames))
    reference = optimise_local_population(level, frames, goal=goal, frame_ranges=((0, 20), (30, 79)), config=config)
    assert fast == reference


def test_native_plan_rejects_bad_buffers_and_uninitialised_use():
    native = require_native()
    evaluator = EndpointEvaluator(floor_level(), EndpointGoal(5))
    with pytest.raises(ValueError, match="outside"):
        evaluator._native_plan.scan(evaluator._prefix, b"\20")
    with pytest.raises(ValueError, match="packed"):
        evaluator._native_plan.scan(evaluator._prefix, b"\xff" * 6)
    uninitialised = native.NativeEndpointPlan.__new__(native.NativeEndpointPlan)
    with pytest.raises(RuntimeError, match="not initialised"):
        uninitialised.scan(evaluator._prefix, b"\20" * 6)


def test_native_nonfinite_scan_continues_without_accepting_a_goal(tmp_path):
    import shutil
    import subprocess
    import sys
    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None or sys.platform == "win32":
        pytest.skip("standalone harness requires a C compiler")
    root = Path(__file__).resolve().parents[1]
    sources = ["nv14_core", "nv14_visual", "nv14_dump", "nv14_scene", "nv14_rays",
               "nv14_objects_basic", "nv14_objects_guard", "nv14_objects_ranged",
               "nv14_objects_drones", "nv14_drone_weapons", "nv14_endpoint"]
    executable = tmp_path / "endpoint-nonfinite"
    compiled = subprocess.run([
        compiler, "-std=c11", "-O1", "-fno-fast-math", "-ffp-contract=off",
        "-I", str(root / "native"), str(Path(__file__).with_name("test_native_population_nonfinite.c")),
        *(str(root / "native" / (name + ".c")) for name in sources),
        "-lm", "-o", str(executable),
    ], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

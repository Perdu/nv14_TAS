"""Velocity constraints across native windows, verification and CLI output."""
from itertools import product
import math
from pathlib import Path
import subprocess
import sys

import pytest

import nv14_cli as cli
import nv14_local
from nv14_engine import InputFrame, parse_level_string
from nv14_local import optimise_local_windows
from nv14_objectives import (
    AxisWindow, evaluate, evaluate_window_candidate, evaluate_frame_set_candidate,
    objective_function, target_from_point, resolve_interaction_requirement,
    resolve_interaction_avoidance, position_within_windows,
)
from nv14_replay import (
    encode_complex_replay, decode_complex_replay, parse_combined_level_replay,
    simulate_through_frame,
)
from nv14_search import (
    ALL_INPUT_CHOICES, NativeSearchSession, SearchSpec, compile_objective,
    evaluate_fixed_replay_native,
)


ROOT = Path(__file__).resolve().parents[1]


def level(floor=False):
    # The empty level's lower boundary supplies a floor at y=576.
    return parse_level_string("0" * (31 * 23) + ("|5^100,566" if floor else "|5^100,100"))


def velocity(state):
    p = state.player
    return p.pos.x - p.oldpos.x, p.pos.y - p.oldpos.y


@pytest.mark.parametrize("floor", [False, True])
@pytest.mark.parametrize("mutable", [(1, 2, 3), (1, 3, 5)])
@pytest.mark.parametrize("objective_name", ["max-x", "min-x", "max-y", "min-y", "min-distance"])
@pytest.mark.parametrize("bounds", [((-.2, .2), (-10, 3)), ((-.4, -.05), (-math.inf, math.inf))])
def test_native_search_matches_exhaustive_python_oracle(floor, mutable, objective_name, bounds):
    source = level(floor)
    frames = [InputFrame()] * 9
    target = target_from_point((105, 550)) if objective_name == "min-distance" else None
    objective = objective_function(objective_name, target)
    native_objective, targets = compile_objective(objective_name, target)
    best_score = -math.inf
    for inputs in product(ALL_INPUT_CHOICES, repeat=len(mutable)):
        candidate = list(frames)
        for index, value in zip(mutable, inputs):
            candidate[index] = value
        state = simulate_through_frame(source, candidate, 8)
        vx, vy = velocity(state)
        # Independent oracle: no new feasibility helper is used here.
        if (not state.player.dead and bounds[0][0] <= vx <= bounds[0][1]
                and bounds[1][0] <= vy <= bounds[1][1]):
            best_score = max(best_score, objective(state))
    result = NativeSearchSession(source).search(frames, SearchSpec(
        mutable, (ALL_INPUT_CHOICES,) * len(mutable), 8, native_objective,
        targets=targets, vx_window=bounds[0], vy_window=bounds[1],
        prune_inactive_jump=True,
    ))
    assert result.feasible == (best_score != -math.inf)
    assert result.score == best_score


@pytest.mark.parametrize("axis", ["vx", "vy"])
@pytest.mark.parametrize("offset", [0, -1, 1])
def test_exact_boundaries_fixed_suffix_and_reference_evaluators(axis, offset):
    source = level()
    frames = [InputFrame(right=True)] * 8
    objective = objective_function("max-x")
    state = simulate_through_frame(source, frames, 7)
    value = velocity(state)[axis == "vy"]
    if offset:
        value = math.nextafter(value, math.inf if offset > 0 else -math.inf)
    kwargs = {axis + "_window": AxisWindow(value, value)}
    feasible = offset == 0
    prefix = simulate_through_frame(source, frames, 0)
    assert evaluate(source, frames, 7, objective, **kwargs).feasible == feasible
    assert evaluate_fixed_replay_native(source, frames, 7, objective, **kwargs).feasible == feasible
    assert evaluate_window_candidate(source, prefix, frames[1:3], frames[3:], objective, **kwargs).feasible == feasible
    assert evaluate_frame_set_candidate(source, prefix, frames, (1, 3), (frames[1], frames[3]),
                                        target_frame=7, objective=objective, **kwargs).feasible == feasible
    # Only one assignment: the final velocity is measured after the fixed suffix.
    seed = list(frames)
    seed[1] = InputFrame()  # The kernel deliberately skips unchanged assignments.
    result = NativeSearchSession(source).search(seed, SearchSpec(
        (1,), ((frames[1],),), 7, 0, **{axis + "_window": (value, value)},
    ))
    assert result.feasible == feasible


@pytest.mark.parametrize("inputs", ["all", "direction"])
@pytest.mark.parametrize("shape", ["contiguous", "sparse", "mixed"])
def test_feasibility_repair_parallel_and_python_verification(inputs, shape):
    source = level()
    frames = [InputFrame(right=True)] * 12
    kwargs = dict(target_frame=11, range_start=1, range_end=8,
                  objective_name="max-x", window_size=3, passes=2,
                  vx_window=AxisWindow(-.3, .7), vy_window=AxisWindow(0, 4),
                  window_shape=shape, window_order="mixed", restarts=2, seed=71,
                  local_inputs=inputs, physics_prune=inputs == "direction", progress=None)
    assert not evaluate(source, frames, 11, objective_function("max-x"),
                        vx_window=kwargs["vx_window"]).feasible
    serial, result = optimise_local_windows(source, frames, workers=1, python_resimulate=True, **kwargs)
    parallel, actual = optimise_local_windows(source, frames, workers=2, **kwargs)
    assert result.feasible and actual.feasible
    assert serial == parallel and result.score == actual.score
    vx, vy = velocity(simulate_through_frame(source, parallel, 11))
    assert -.3 <= vx <= .7 and 0 <= vy <= 4
    assert parallel[0] == frames[0] and parallel[9:] == frames[9:]


@pytest.mark.parametrize("python_resimulate", [False, True])
def test_packed_output_independently_rejects_violating_velocity(python_resimulate):
    source = level()
    frames = [InputFrame(right=True)] * 8
    objective = objective_function("max-x")
    unconstrained = evaluate(source, frames, 7, objective)
    with pytest.raises(ValueError, match="clean frame-zero verification"):
        cli._verify_packed_replay_for_output(
            source, frames, target_frame=7, objective=objective,
            expected_evaluation=unconstrained, x_window=None, y_window=None,
            vx_window=AxisWindow(-2, 0), python_resimulate=python_resimulate,
        )


@pytest.mark.parametrize("axis", ["vx", "vy"])
@pytest.mark.parametrize("bounds", [(2, 1), (math.nan, 1), (math.inf, math.inf), (-math.inf, -math.inf)])
def test_invalid_api_bounds(axis, bounds):
    with pytest.raises(ValueError):
        optimise_local_windows(level(), [InputFrame()] * 4, target_frame=3,
                               range_start=0, range_end=2, objective_name="max-x",
                               window_size=2, passes=1, progress=None,
                               **{axis + "_window": AxisWindow(*bounds)})
    with pytest.raises(ValueError):
        spec = SearchSpec((0,), ((InputFrame(),),), 3, 0, **{axis + "_window": bounds})
        NativeSearchSession(level()).search([InputFrame()] * 4, spec)


def test_cli_toml_output_and_impossible_constraint(tmp_path):
    source = tmp_path / "run.txt"
    frames = [InputFrame(right=True)] * 12
    source.write_text(f"$Velocity test#tests##{level().source_level_string}#{encode_complex_replay(frames)}#\n")
    config = tmp_path / "local.toml"
    config.write_text('[local]\nsearch="windows"\ntarget_frame=11\nrange="1:8"\n'
                      'window=3\npasses=2\nvx_window=[-0.3,0.7]\nvy_window="0:"\nworkers=1\n')
    output = tmp_path / "result.txt"
    command = [sys.executable, str(ROOT / "optimize_replay.py"), "local", str(source),
               "--config", str(config), "--output", str(output)]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=40)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    combined = parse_combined_level_replay(output.read_text())
    decoded = decode_complex_replay(combined.replay_string).frames
    vx, vy = velocity(simulate_through_frame(level(), decoded, 11))
    assert -.3 <= vx <= .7 and vy >= 0
    previous = output.read_bytes()
    failed = subprocess.run(command + ["--vx-window=100:101"], cwd=ROOT,
                            text=True, capture_output=True, timeout=40)
    assert failed.returncode != 0
    assert output.read_bytes() == previous


def test_cli_windows_defaults_explicit_strategy_and_population():
    for strategy in ([], ["--search", "windows"], ["--search", "population"]):
        args = cli.parse_arguments(["local", "source.txt", *strategy,
                                    "--vx-window=-2:", "--vy-window", "0"])
        assert args._mode_configs.local.vx_window == AxisWindow(-2, math.inf)
        assert args._mode_configs.local.vy_window == AxisWindow(0, 0)
    for mode in ("auto", "jump-pattern"):
        with pytest.raises(SystemExit):
            cli.parse_arguments([mode, "source.txt", "--vx-window=0:1"])


def test_position_interactions_and_velocity_combine_without_candidate_python_steps(monkeypatch):
    source = parse_level_string("0" * (31 * 23) + "|5^100,100!0^100,100!0^120,100")
    calls = 0
    original = nv14_local.evaluate

    def baseline_only(*args, **kwargs):
        nonlocal calls
        calls += 1
        assert calls == 1, "candidate evaluation unexpectedly returned to Python"
        return original(*args, **kwargs)

    monkeypatch.setattr(nv14_local, "evaluate", baseline_only)
    frames, result = optimise_local_windows(
        source, [InputFrame()] * 9, target_frame=8, range_start=0, range_end=5,
        objective_name="max-x", window_size=3, passes=2, progress=None,
        x_window=AxisWindow(100, 102), y_window=AxisWindow(100, 120),
        vx_window=AxisWindow(.1, .3), vy_window=AxisWindow(0, 2),
        required_interactions=(resolve_interaction_requirement(source, "gold:0"),),
        avoided_interactions=(resolve_interaction_avoidance(source, "gold:1"),),
    )
    assert calls == 1 and result.feasible
    assert not result.missing_interactions and not result.violated_interactions
    state = simulate_through_frame(source, frames, 8)
    vx, vy = velocity(state)
    assert 100 <= state.player.pos.x <= 102 and 100 <= state.player.pos.y <= 120
    assert .1 <= vx <= .3 and 0 <= vy <= 2


@pytest.mark.parametrize("axis", ["x", "y"])
def test_overflowed_velocity_is_infeasible_even_with_open_bounds(axis):
    state = level().initial_state()
    setattr(state.player.pos, axis, 1e308)
    setattr(state.player.oldpos, axis, -1e308)
    assert not position_within_windows(state, **{
        "v" + axis + "_window": AxisWindow(-math.inf, math.inf),
    })

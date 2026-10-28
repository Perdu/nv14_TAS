"""Singular AVM1 states keep running, but must never become search winners."""
import math
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import nv14_engine as engine
import nv14_objectives as objectives


@pytest.mark.parametrize("field", ("pos.x", "pos.y", "oldpos.x", "oldpos.y"))
@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_nonfinite_player_rejected_even_by_constant_objective(monkeypatch, field, value):
    level = engine.parse_level_string("0" * 713 + "|5^100,100")
    state = level.initial_state()
    vector, coordinate = field.split(".")
    setattr(getattr(state.player, vector), coordinate, value)
    monkeypatch.setattr(objectives, "simulate_through_frame", lambda *args: state.clone())
    constant_score = lambda state: 0.0
    results = (
        objectives.evaluate(level, (), -1, constant_score),
        objectives.evaluate_window_candidate(level, state, (), (), constant_score),
        objectives.evaluate_frame_set_candidate(
            level, state, (engine.InputFrame(),), (0,), (engine.InputFrame(),),
            target_frame=0, objective=constant_score,
        ),
    )
    for result in results:
        assert not result.feasible
        assert result.score == -math.inf
        assert not result.state.player.dead
    # Rejecting a search endpoint does not alter the simulated source state.
    assert not state.player.dead


@pytest.mark.parametrize("score", (math.nan, math.inf, -math.inf))
def test_nonfinite_objective_score_is_infeasible(score):
    level = engine.parse_level_string("0" * 713 + "|5^100,100")
    result = objectives.evaluate(level, (), -1, lambda state: score)
    assert not result.feasible
    assert result.score == -math.inf
    assert not result.state.player.dead


def test_ordinary_finite_endpoint_remains_feasible():
    level = engine.parse_level_string("0" * 713 + "|5^100,100")
    result = objectives.evaluate(level, (), -1, objectives.objective_function("max-x"))
    assert result.feasible and result.score == 100.0


def test_native_search_pattern_and_patch_nonfinite_endpoints(tmp_path):
    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None or sys.platform == "win32":
        pytest.skip("standalone harness requires a C compiler")
    root = Path(__file__).resolve().parents[1]
    sources = ["nv14_core", "nv14_visual", "nv14_dump", "nv14_scene", "nv14_rays",
               "nv14_objects_basic", "nv14_objects_guard", "nv14_objects_ranged",
               "nv14_objects_drones", "nv14_drone_weapons", "nv14_search", "nv14_patch"]
    executable = tmp_path / "nonfinite-search"
    compile_result = subprocess.run([
        compiler, "-std=c11", "-O1", "-fno-fast-math", "-ffp-contract=off",
        "-I", str(root / "native"), str(Path(__file__).with_suffix(".c")),
        *(str(root / "native" / (name + ".c")) for name in sources),
        "-lm", "-o", str(executable),
    ], capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

"""Independent full-run and range-scaled Auto endpoint proposal budgets."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from nv14_cli import parse_arguments, resolve_auto_endpoint_iterations
from nv14_engine import InputFrame
from nv14_replay import encode_complex_replay

ROOT = Path(__file__).resolve().parents[1]
LEVEL = "0" * (31 * 23) + "|5^100,100!11^400,100,300,100"


def _source(tmp_path: Path) -> Path:
    input_path = tmp_path / "replay.txt"
    input_path.write_text(
        "$Short#tests##" + LEVEL + "#" + encode_complex_replay([InputFrame()] * 3) + "#\n",
        encoding="utf-8",
    )
    return input_path


def test_shared_auto_toml_separates_full_run_and_endpoint_budgets(tmp_path):
    config = tmp_path / "auto.toml"
    config.write_text(
        "[auto]\niterations = 10000\n"
        "endpoint-iterations = 2400\nendpoint-iterations-per-frame = 10.0\n",
        encoding="utf-8",
    )
    normal = parse_arguments(["auto", "run.txt", "--config", str(config)])
    assert normal.iterations == 10000
    assert normal.auto_endpoint_iterations == 2400
    assert normal.auto_endpoint_iterations_per_frame == 10.0
    # This is a shared Auto config: the endpoint overrides must not cause
    # complete-run speedrun/highscore to reject it.
    assert normal.auto_objective == "speedrun"
    assert resolve_auto_endpoint_iterations(
        full_run_iterations=normal.iterations,
        endpoint_iterations=normal.auto_endpoint_iterations,
        endpoint_iterations_per_frame=normal.auto_endpoint_iterations_per_frame,
        range_start=100, range_end=167,
    ) == 2400
    overridden = parse_arguments([
        "auto", "run.txt", "--config", str(config),
        "--auto-endpoint-iterations", "500",
    ])
    assert overridden.auto_endpoint_iterations == 500
    assert overridden.iterations == 10000


@pytest.mark.parametrize("start,end,rate,expected", [
    (100, 167, 20.0, 1360),
    (0, 167, 7.5, 1260),
    (0, 0, 0.1, 1),
    (3, 7, 2.5, 13),
])
def test_range_scaled_budget_uses_inclusive_editable_frames(start, end, rate, expected):
    assert resolve_auto_endpoint_iterations(
        full_run_iterations=10000, endpoint_iterations=None,
        endpoint_iterations_per_frame=rate,
        range_start=start, range_end=end,
    ) == expected


def test_historical_iteration_budget_remains_fallback():
    assert resolve_auto_endpoint_iterations(
        full_run_iterations=1234, endpoint_iterations=None,
        endpoint_iterations_per_frame=None, range_start=100, range_end=167,
    ) == 1234


@pytest.mark.parametrize("rate", ["0", "-1", "nan", "inf", "-inf", "not-a-number"])
def test_invalid_rates_rejected_by_cli(rate):
    with pytest.raises(SystemExit):
        parse_arguments(["auto", "run.txt", "--auto-endpoint-iterations-per-frame", rate])


def test_local_style_goal_uses_range_scaled_budget_and_keeps_full_run_budget(tmp_path):
    source = _source(tmp_path)
    common = tmp_path / "default.toml"
    common.write_text("[auto]\niterations = 10000\nendpoint-iterations-per-frame = 2.0\n", encoding="utf-8")
    splice = tmp_path / "splice.toml"
    splice.write_text(
        '[local]\nobjective = "min-distance"\ntarget-object = "exit:0"\n'
        'target-frame = 7\nrange = "3:7"\n',
        encoding="utf-8",
    )
    result = subprocess.run([
        sys.executable, str(ROOT / "optimize_replay.py"), "auto", str(source),
        "--config", str(common), "--goal-config", str(splice),
        "--workers", "1", "--auto-runs", "1", "--beam", "4",
        "--auto-endpoint-repair-steps", "0", "--output", str(tmp_path / "out.txt"),
    ], capture_output=True, text=True, cwd=ROOT, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "iterations per worker 10;" in result.stdout
    assert "editable frames 3:7;" in result.stdout
    assert "appended 5 neutral input frame(s)" in result.stdout


def test_fixed_endpoint_budget_precedes_rate_in_real_cli(tmp_path):
    source = _source(tmp_path)
    result = subprocess.run([
        sys.executable, str(ROOT / "optimize_replay.py"), "auto", str(source),
        "--objective", "max-x", "--target-frame", "7", "--range", "3:7",
        "--iterations", "90", "--auto-endpoint-iterations-per-frame", "2.0",
        "--auto-endpoint-iterations", "3", "--auto-endpoint-repair-steps", "0",
        "--workers", "1", "--auto-runs", "1", "--output", str(tmp_path / "out.txt"),
    ], capture_output=True, text=True, cwd=ROOT, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "iterations per worker 3;" in result.stdout

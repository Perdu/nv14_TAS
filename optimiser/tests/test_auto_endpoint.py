"""Auto's Local-compatible partial endpoint goals, and shared TOML configuration."""
from dataclasses import replace

import pytest

from nv14_auto_endpoint import (
    AutoEndpointConfig, _proposal, optimise_auto_endpoint,
    optimise_auto_endpoint_campaign,
)
from nv14_cli import parse_arguments
from nv14_endpoint import EndpointGoal, verify_endpoint
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame, parse_level_string
from nv14_replay import decode_complex_replay, editable_frames, encode_complex_replay


def _level(*, with_gold: bool = False):
    tiles = "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    objects = "|5^60,60" + ("!0^75,60" if with_gold else "")
    return parse_level_string(tiles + objects)


def _source():
    return tuple(InputFrame() for _ in range(45))


def test_endpoint_auto_can_improve_without_any_exit():
    level = _level()
    goal = EndpointGoal(target_frame=25, objective="max-x")
    source = _source()
    baseline, best, simulations = optimise_auto_endpoint(
        level, source, goal, AutoEndpointConfig(iterations=240, beam_width=16, seed=11,
                                               range_start=1, range_end=25))
    assert simulations > 0
    assert best is not None
    assert best.evaluation.score > baseline.evaluation.score
    assert best.frames[:1] == source[:1]
    assert best.frames[26:] == source[26:]
    packed = tuple(editable_frames(decode_complex_replay(encode_complex_replay(best.frames)).frames))
    assert verify_endpoint(level, packed, goal, expected=best.evaluation).feasible


def test_checkpoint_accepts_partial_but_complete_policy_rejects():
    level = _level()
    goal = EndpointGoal(target_frame=20, objective="max-x")
    cfg = AutoEndpointConfig(iterations=30, seed=4, range_end=20)
    baseline, partial, _ = optimise_auto_endpoint(level, _source(), goal, cfg)
    assert baseline.evaluation.feasible
    assert partial is not None
    baseline2, completed, _ = optimise_auto_endpoint(
        level, _source(), goal, replace(cfg, completion_policy="complete"))
    assert not baseline2.evaluation.feasible
    assert completed is None


def test_earliest_checkpoint_and_secondary_evaluate_identically_to_local():
    level = _level()
    goal = EndpointGoal(
        target_frame=30, objective="earliest-arrival", arrival_start=0,
        target_region=(60, 200, 60, 90), secondary_objective="max-vx",
    )
    _baseline, best, _ = optimise_auto_endpoint(
        level, _source(), goal,
        AutoEndpointConfig(iterations=48, seed=3, range_end=30))
    assert best is not None
    checked = verify_endpoint(level, best.frames, goal, expected=best.evaluation)
    assert checked.frame == best.evaluation.frame
    assert checked.secondary_score == best.evaluation.secondary_score


def test_section_mutations_never_modify_locked_frames():
    source = _source()
    import random
    rng = random.Random(29)
    for _ in range(300):
        trial = _proposal(source, rng=rng, config=AutoEndpointConfig(),
                          start=12, end=19, donor=tuple(InputFrame(right=True) for _ in source))
        assert len(trial) == len(source)
        assert trial[:12] == source[:12]
        assert trial[20:] == source[20:]


def test_shared_goal_toml_used_by_both_auto_and_local(tmp_path):
    config = tmp_path / "shared.toml"
    config.write_text('''[common]
workers = 1
[goal]
objective = "earliest-arrival"
target-frame = 30
target-region = [60, 90, 50, 90]
secondary-objective = "max-vx"
[auto]
iterations = 12
completion-policy = "checkpoint"
[local]
search = "population"
iterations = 12
''')
    for mode in ("auto", "local"):
        args = parse_arguments([mode, "input.txt", "--config", str(config), "--output", "out.txt"])
        assert (args.auto_objective if mode == "auto" else args.objective) == "earliest-arrival"
        assert (args.auto_target_frame if mode == "auto" else args.target_frame) == 30
        assert (args.auto_secondary_objective if mode == "auto" else args.secondary_objective) == "max-vx"
        assert (args.auto_target_region if mode == "auto" else args.target_region) == (60, 90, 50, 90)


def test_mode_specific_goal_override_and_cli_precedence(tmp_path):
    config = tmp_path / "shared.toml"
    config.write_text('''[goal]
objective = "max-y"
target-frame = 20
[auto]
objective = "max-x"
[local]
objective = "min-y"
''')
    assert parse_arguments(["auto", "input.txt", "--config", str(config), "--output", "out.txt"]).auto_objective == "max-x"
    assert parse_arguments(["local", "input.txt", "--config", str(config), "--output", "out.txt"]).objective == "min-y"
    assert parse_arguments(["auto", "input.txt", "--config", str(config), "--output", "out.txt", "--auto-objective", "min-x"]).auto_objective == "min-x"


def test_parallel_endpoint_workers_return_replay_verifiable_in_parent():
    level = _level()
    goal = EndpointGoal(target_frame=20, objective="max-x")
    base, winner, count = optimise_auto_endpoint_campaign(
        level, _source(), goal,
        AutoEndpointConfig(iterations=65, beam_width=8, seed=2, range_end=20),
        workers=2, runs=2,
    )
    assert count > 0
    assert winner is not None
    assert winner.evaluation.score >= base.evaluation.score
    assert verify_endpoint(level, winner.frames, goal, expected=winner.evaluation).feasible


def test_invalid_shared_goal_rejected_in_both_modes(tmp_path):
    config = tmp_path / "shared.toml"
    config.write_text('[goal]\nunknown-goal-option = 1\n')
    for mode in ("auto", "local"):
        with pytest.raises(SystemExit, match="unknown TOML option"):
            parse_arguments([mode, "input.txt", "--config", str(config), "--output", "out.txt"])


def test_earliest_interaction_uses_exact_local_atom_resolution():
    from nv14_objectives import resolve_interaction_target
    level = _level(with_gold=True)
    goal = EndpointGoal(target_frame=20, objective="earliest-interaction",
                        interaction_target=resolve_interaction_target(level, "gold:0"))
    baseline, best, _ = optimise_auto_endpoint(
        level, _source(), goal,
        AutoEndpointConfig(iterations=22, seed=17, range_end=20))
    assert baseline.evaluation.feasible
    assert best is not None
    checked = verify_endpoint(level, best.frames, goal, expected=best.evaluation)
    assert checked.interaction_events[0].label == "gold:0"


def test_complete_policy_accepts_a_canonical_finished_reference():
    level = parse_level_string("0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
                               + "|5^100,100!11^101,100,100,100")
    goal = EndpointGoal(target_frame=0, objective="max-x")
    baseline, winner, evaluated = optimise_auto_endpoint(
        level, (InputFrame(),), goal,
        AutoEndpointConfig(iterations=0, completion_policy="complete"))
    assert evaluated == 0
    assert baseline.evaluation.feasible
    assert winner is not None
    assert verify_endpoint(level, winner.frames, goal).feasible


def test_unified_goal_cli_aliases_are_accepted():
    for mode in ("auto", "local"):
        command = [mode, "source.txt", "--output", "out.txt", "--objective", "earliest-arrival",
                   "--target-frame", "20", "--target-region", "60:90,20:100",
                   "--secondary-objective", "max-vx"]
        if mode == "local":
            command.extend(("--search", "population"))
        args = parse_arguments(command)
        prefix = "auto_" if mode == "auto" else ""
        assert getattr(args, prefix + "target_frame") == 20
        assert getattr(args, prefix + "objective") == "earliest-arrival"
        assert getattr(args, prefix + "target_region") == (60.0, 90.0, 20.0, 100.0)


def test_both_cli_modes_run_using_identical_shared_goal(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    from nv14_replay import parse_combined_level_replay

    root = Path(__file__).resolve().parents[1]
    example = root / "examples" / "91-1.txt"
    config = tmp_path / "shared.toml"
    config.write_text('''[common]
workers = 1
simulate-enemies = false
[goal]
objective = "max-x"
target-frame = 25
range = "1:25"
[auto]
iterations = 60
beam = 8
seed = 9
[local]
search = "population"
iterations = 60
beam = 8
rounds = 1
seed = 9
''')
    for mode in ("auto", "local"):
        output = tmp_path / (mode + ".txt")
        command = [sys.executable, str(root / "optimize_replay.py"), mode,
                   str(example), "--output", str(output), "--config", str(config)]
        done = subprocess.run(command, capture_output=True, text=True, cwd=root, timeout=40)
        assert done.returncode == 0, done.stdout + done.stderr
        combined = parse_combined_level_replay(output.read_text())
        frames = decode_complex_replay(combined.replay_string).frames
        level = parse_level_string(combined.level_string, simulate_enemies=False)
        goal = EndpointGoal(target_frame=25, objective="max-x")
        assert verify_endpoint(level, frames, goal).feasible

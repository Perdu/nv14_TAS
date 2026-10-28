"""Exact event goals, checked against the independent Python physics engine."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import pytest

import nv14_cli as cli
from nv14_checkpoint import canonical_json_bytes
from nv14_engine import InputFrame, door_control_masks, parse_level_string
from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_objectives import (
    AxisWindow, InteractionTarget, resolve_interaction_avoidance,
    resolve_interaction_requirement, resolve_interaction_target,
)
from nv14_population import PopulationConfig, optimise_local_population
from nv14_replay import decode_complex_replay, encode_complex_replay


ROOT = Path(__file__).resolve().parents[1]
EMPTY_MAP = "0" * (31 * 23)


def level(objects):
    return parse_level_string(EMPTY_MAP + "|5^100,100!" + objects, simulate_enemies=True)


def goal(source, selector="gold:0", deadline=24, **kwargs):
    return EndpointGoal(deadline, "earliest-interaction",
                        interaction_target=resolve_interaction_target(source, selector), **kwargs)


def python_rows(source, frames):
    """Read raw state from the Python engine, independently of endpoint scoring."""
    state = source.initial_state()
    rows = []
    for frame in frames:
        state.step(frame, source.tiles)
        p, s = state.player, state.static_state
        locked, traps = door_control_masks(state)
        rows.append({"x": p.pos.x, "y": p.pos.y, "vx": p.pos.x - p.oldpos.x,
                     "vy": p.pos.y - p.oldpos.y, "dead": p.dead,
                     "gold": s.collected_gold_mask, "switch": s.open_exit_mask,
                     "locked": locked, "trap": traps,
                     "exit": s.completed_exit_index if s.level_complete else -1})
        if p.dead:
            break
    return rows


@pytest.mark.parametrize("objects,selector,field,label", [
    ("0^120,105", "gold:0", "gold", "gold:0"),
    ("11^300,100,120,105", "switch:0", "switch", "switch:0"),
    ("11^300,100,120,105", "exit:0.switch", "switch", "switch:0"),
    ("9^120,105,0,0,20,20,1,0,0", "testdoor:0", "locked", "testdoor:0"),
    ("9^120,105,0,1,20,20,0,0,0", "testdoor:0", "trap", "testdoor:0"),
    ("9^120,105,0,1,20,20,0,0,0", "trapdoor:0.trigger", "trap", "testdoor:0"),
    ("11^120,105,100,100", "exit:0", "exit", "exit:0.door"),
    ("11^120,105,100,100", "exit:0.door", "exit", "exit:0.door"),
])
def test_supported_events_match_first_python_tick_and_packed_replay(objects, selector, field, label):
    source = level(objects)
    frames = (InputFrame(right=True),) * 30
    target = goal(source, selector, deadline=29)
    rows = python_rows(source, frames)
    if field == "exit":
        event = next(i for i, row in enumerate(rows) if row[field] >= 0)
    else:
        event = next(i for i, row in enumerate(rows) if row[field])
    result = EndpointEvaluator(source, target).evaluate(frames)
    assert result.feasible and result.frame == event and result.score == -event
    assert [atom.label for atom in result.interaction_events] == [label]
    packed = decode_complex_replay(encode_complex_replay(frames)).frames
    assert verify_endpoint(source, packed, target, result, python_resimulate=True) == result


def test_event_deadline_and_arrival_start_are_inclusive_and_cached_prefix_is_exact():
    source = level("0^120,105")
    frames = (InputFrame(right=True),) * 30
    event = next(i for i, row in enumerate(python_rows(source, frames)) if row["gold"])
    target = goal(source, deadline=event, arrival_start=event)
    result = EndpointEvaluator(source, target, frames, prefix_frame=20).evaluate(frames)
    assert result.feasible and result.frame == event
    assert result == verify_endpoint(source, frames, target, python_resimulate=True)
    assert not EndpointEvaluator(source, replace(target, target_frame=event - 1, arrival_start=0)).evaluate(frames).feasible
    assert not EndpointEvaluator(source, replace(target, target_frame=29, arrival_start=event + 1)).evaluate(frames).feasible
    evaluator = EndpointEvaluator(source, target, frames, prefix_frame=5)
    assert evaluator.evaluate(frames) == result
    with pytest.raises(ValueError, match="immutable cached prefix"):
        evaluator.evaluate((InputFrame(left=True), *frames[1:]))


@pytest.mark.parametrize("constraint", ["velocity", "required-gold"])
def test_latched_pickup_cannot_qualify_when_constraints_only_become_true_later(constraint):
    source = level("0^100,100!0^120,105")
    frames = (InputFrame(right=True),) * 30
    kwargs = ({"vx_window": AxisWindow(.8, math.inf)} if constraint == "velocity" else
              {"required_interactions": (resolve_interaction_requirement(source, "gold:1"),)})
    target = goal(source, deadline=29, **kwargs)
    result = EndpointEvaluator(source, target).evaluate(frames)
    rows = python_rows(source, frames)
    assert rows[0]["gold"] == 1 and rows[9]["gold"] == 3 and rows[9]["vx"] > .8
    assert not result.feasible
    # Retain the actual failed interaction as the repair point, not a later
    # state which has met its requirements after consuming the target.
    assert result.frame == 0 and result.interaction_events[0].label == "gold:0"
    assert verify_endpoint(source, frames, target, result, python_resimulate=True) == result


def test_any_uses_each_fresh_object_and_ignores_consumed_prefix_alternatives():
    source = level("0^100,100!0^120,105")
    frames = (InputFrame(right=True),) * 30
    target = goal(source, "gold:any", arrival_start=5, vx_window=AxisWindow(.8, math.inf))
    result = EndpointEvaluator(source, target, frames, prefix_frame=5).evaluate(frames)
    assert result.feasible and result.frame == 9
    assert [atom.label for atom in result.interaction_events] == ["gold:1"]
    # The aggregate 'any' predicate was already true at frame zero.
    assert python_rows(source, frames)[0]["gold"] == 1
    verify_endpoint(source, frames, target, result, python_resimulate=True)
    assert EndpointEvaluator(source, replace(target, arrival_start=0)).evaluate(frames).frame == 9


def test_any_reports_simultaneous_matching_events():
    source = level("0^90,100!0^110,100")
    frames = (InputFrame(),) * 4
    target = goal(source, "gold:any", deadline=3)
    result = EndpointEvaluator(source, target).evaluate(frames)
    assert result.feasible and result.frame == 0
    assert [atom.label for atom in result.interaction_events] == ["gold:0", "gold:1"]
    verify_endpoint(source, frames, target, result, python_resimulate=True)


def test_exact_target_identity_is_not_a_count_or_any_exit_completion():
    source = level("0^100,100!0^500,500")
    frames = (InputFrame(),) * 10
    assert not EndpointEvaluator(source, goal(source, "gold:1", deadline=9)).evaluate(frames).feasible
    source = level("11^100,100,100,100!11^500,500,100,100")
    target = goal(source, "exit:1.door", deadline=9)
    result = EndpointEvaluator(source, target).evaluate(frames)
    assert python_rows(source, frames)[-1]["exit"] == 0
    assert not result.feasible
    assert not result.interaction_events
    verify_endpoint(source, frames, target, result, python_resimulate=True)


def test_deadline_constraints_include_prefix_and_same_tick_avoidances_but_not_later_death():
    source = level("0^100,100!0^120,105")
    frames = (InputFrame(right=True),) * 120
    target = goal(source, "gold:1", deadline=119, arrival_start=5,
                  required_interactions=(resolve_interaction_requirement(source, "gold:0"),))
    result = EndpointEvaluator(source, target, frames, prefix_frame=5).evaluate(frames)
    assert result.feasible and result.frame == 9 and python_rows(source, frames)[-1]["dead"]
    for selector in ("gold:0", "gold:1"):
        avoided = replace(target, avoided_interactions=(resolve_interaction_avoidance(source, selector),))
        assert not EndpointEvaluator(source, avoided).evaluate(frames).feasible
    early = goal(source, deadline=119, avoided_interactions=(resolve_interaction_avoidance(source, "gold:1"),))
    assert EndpointEvaluator(source, early).evaluate(frames).feasible


def test_same_tick_death_does_not_satisfy_local_survival_rule():
    source = level("0^110,100!12^90,100")
    frames = (InputFrame(),) * 10
    rows = python_rows(source, frames)
    assert rows[0]["gold"] == 1 and rows[0]["dead"]
    target = goal(source, deadline=9)
    result = EndpointEvaluator(source, target).evaluate(frames)
    assert result.dead and not result.feasible and result.interaction_events
    verify_endpoint(source, frames, target, result, python_resimulate=True)


def test_unreached_goal_retains_best_living_approach_before_later_death():
    source = level("0^120,90")
    frames = (InputFrame(right=True),) * 120
    result = EndpointEvaluator(source, goal(source, deadline=119)).evaluate(frames)
    assert not result.feasible and not result.dead and result.terminal_dead
    assert result.frame < result.terminal_frame and math.isfinite(result.target_distance)
    assert not result.interaction_events


def test_target_selectors_keep_public_indices_masks_and_sparse_door_ids():
    source = level("0^999!0^120,105!11^999!11^120,105,100,100")
    for selector in ("gold:1", "switch:1", "exit:1.door"):
        atom = resolve_interaction_target(source, selector).alternatives[0]
        assert atom.type_index == 1 and atom.state_index == 0
    objects = "!".join(["0^500,500"] * 70 + ["9^120,105,0,0,20,20,1,0,0"])
    source = level(objects)
    target = goal(source, "testdoor:0")
    atom = target.interaction_target.alternatives[0]
    assert atom.load_index > 64
    frames = (InputFrame(right=True),) * 30
    result = EndpointEvaluator(source, target).evaluate(frames)
    assert result.feasible and result.interaction_state[2] == 1 << atom.load_index
    verify_endpoint(source, frames, target, result, python_resimulate=True)


def test_testdoor_any_includes_locked_and_trap_but_not_proximity_doors():
    source = level("9^100,100,0,0,17,17,0,0,0!9^100,100,0,1,18,17,0,0,0!"
                   "9^120,105,0,0,19,17,1,0,0")
    targets = resolve_interaction_target(source, "testdoor:any").alternatives
    assert [(a.type_index, a.kind) for a in targets] == [(1, "trapdoor"), (2, "locked-door")]
    assert resolve_interaction_target(source, "trapdoor").alternatives == targets[:1]
    # Existing route requirements still restrict testdoor:any to locked doors.
    assert resolve_interaction_requirement(source, "testdoor:any").alternatives == targets[1:]
    with pytest.raises(ValueError, match="ordinary proximity door"):
        resolve_interaction_target(source, "testdoor:0")
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_interaction_target(source, "testdoor")


@pytest.mark.parametrize("selector", ["launchpad:0", "mine:any", "onewayplatform:0", "player", "gold:0.switch",
                                       "gold:9", "gold:-1", "gold", "exit:0.trigger", "switch:0.door", ""])
def test_unsupported_or_ambiguous_selectors_fail(selector):
    source = level("0^100,100!0^120,105!11^100,100,100,100")
    with pytest.raises(ValueError):
        resolve_interaction_target(source, selector)


def test_goal_validation_and_verification_include_event_identity():
    source = level("0^100,100")
    target = goal(source, deadline=4)
    with pytest.raises(ValueError, match="resolved interaction_target"):
        EndpointGoal(4, "earliest-interaction")
    with pytest.raises(ValueError, match="interaction_target requires"):
        replace(target, objective="max-x")
    with pytest.raises(ValueError, match="target_region requires"):
        replace(target, target_region=(0, 200, 0, 200))
    with pytest.raises(ValueError, match="at least one"):
        InteractionTarget("empty", ())
    frames = (InputFrame(),) * 5
    result = EndpointEvaluator(source, target).evaluate(frames)
    with pytest.raises(ValueError, match="interaction_events"):
        verify_endpoint(source, frames, target, replace(result, interaction_events=()))


@pytest.mark.parametrize("secondary", ["max-vx", "min-vx", "max-x", "min-y"])
def test_secondary_value_is_measured_on_event_tick(secondary):
    source = level("0^120,105")
    frames = (InputFrame(right=True),) * 30
    target = goal(source, secondary_objective=secondary)
    result = EndpointEvaluator(source, target).evaluate(frames)
    direction, attribute = secondary.split("-")
    physical = python_rows(source, frames)[result.frame][attribute]
    assert result.secondary_value == physical
    assert result.secondary_score == (physical if direction == "max" else -physical)
    verify_endpoint(source, frames, target, result, python_resimulate=True)


def test_population_prefix_diagnostics_and_explicit_earlier_eligible_event():
    source = level("0^100,100!0^120,105")
    frames = (InputFrame(right=True),) * 30
    cfg = PopulationConfig(iterations=2, workers=1, repair_steps=0)
    with pytest.raises(ValueError, match="immutable prefix already consumed.*range start earlier"):
        optimise_local_population(source, frames, goal=goal(source, arrival_start=5),
                                  frame_ranges=((5, 20),), config=cfg)
    result = optimise_local_population(source, frames, goal=goal(source, "gold:any", arrival_start=5),
                                       frame_ranges=((5, 20),), config=cfg)
    assert result.candidates[0].evaluation.interaction_events[0].label == "gold:1"
    earlier = optimise_local_population(source, frames, goal=goal(source), frame_ranges=((5, 20),), config=cfg)
    assert earlier.candidates[0].evaluation.frame == 0
    complete = level("11^100,100,100,100!0^500,500")
    with pytest.raises(ValueError, match="immutable prefix already completed"):
        optimise_local_population(complete, frames, goal=goal(complete, arrival_start=5),
                                  frame_ranges=((5, 20),), config=cfg)


@pytest.mark.parametrize("workers", [1, 2])
def test_population_finds_event_from_infeasible_seed_and_preserves_bounded_inputs(workers):
    source = level("0^120,105")
    frames = (InputFrame(),) * 35
    target = goal(source, secondary_objective="max-vx")
    ranges = ((0, 5), (7, 16))
    result = optimise_local_population(source, frames, goal=target, frame_ranges=ranges,
        config=PopulationConfig(iterations=160, rounds=2, beam=8, workers=workers,
                                repair_steps=8, mutation_span=12, seed=41, top_results=3))
    assert not result.baseline.feasible and result.candidates
    mutable = {i for lo, hi in ranges for i in range(lo, hi + 1)}
    for candidate in result.candidates:
        assert len(candidate.frames) == len(frames)
        assert all(candidate.frames[i] == frames[i] for i in range(len(frames)) if i not in mutable)
        verify_endpoint(source, candidate.frames, target, candidate.evaluation, python_resimulate=True)
    assert [c.evaluation.objective_key for c in result.candidates] == sorted(c.evaluation.objective_key for c in result.candidates)


def test_interaction_can_occur_in_fixed_gap_after_earlier_edits():
    source = level("0^120,105")
    frames = (InputFrame(right=True),) * 30
    result = optimise_local_population(source, frames, goal=goal(source), frame_ranges=((0, 1), (12, 14)),
        config=PopulationConfig(iterations=2, workers=1, repair_steps=0))
    assert result.candidates[0].evaluation.frame == 9


@pytest.mark.parametrize("workers", [1, 2])
def test_checkpoint_resume_matches_uninterrupted_and_verifies_event_metadata(tmp_path, workers):
    source = level("0^120,105!0^500,500")
    frames = (InputFrame(right=True),) * 30
    target = goal(source, secondary_objective="max-vx")
    cfg = PopulationConfig(iterations=16, beam=4, rounds=2, workers=workers, seed=17, repair_steps=2)
    full = optimise_local_population(source, frames, goal=target, frame_ranges=((0, 16),), config=cfg)
    path = tmp_path / "campaign.json"
    optimise_local_population(source, frames, goal=target, frame_ranges=((0, 16),),
                              config=replace(cfg, rounds=1, checkpoint_path=path))
    resumed = optimise_local_population(source, frames, goal=target, frame_ranges=((0, 16),),
                                       config=replace(cfg, checkpoint_path=path, resume=True))
    assert resumed.evaluations == full.evaluations
    assert [(c.frames, c.evaluation) for c in resumed.candidates] == [(c.frames, c.evaluation) for c in full.candidates]
    with pytest.raises(ValueError, match="goal.*differs"):
        optimise_local_population(source, frames, goal=goal(source, "gold:1", secondary_objective="max-vx"),
                                  frame_ranges=((0, 16),), config=replace(cfg, checkpoint_path=path, resume=True))
    envelope = json.loads(path.read_text())
    winner = next(item for item in envelope["payload"]["population"] if item["feasible"])
    assert winner["interaction_events"][0]["label"] == "gold:0"
    winner["interaction_events"] = []
    envelope["sha256"] = hashlib.sha256(canonical_json_bytes(envelope["payload"])).hexdigest()
    path.write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match="re-verification"):
        optimise_local_population(source, frames, goal=target, frame_ranges=((0, 16),),
                                  config=replace(cfg, checkpoint_path=path, resume=True))


@pytest.mark.parametrize("options,message", [
    (["--objective", "earliest-interaction"], "requires --target-object"),
    (["--objective", "earliest-interaction", "--target-object", "gold:0", "--target-point", "1,2"], "target-point"),
    (["--objective", "earliest-interaction", "--target-object", "gold:0", "--target-region", "0:1,0:1"], "target-region"),
    (["--objective", "earliest-interaction", "--target-object", "gold:0", "--arrival-start", "6", "--target-frame", "5"], "must not exceed"),
])
def test_cli_rejects_invalid_interaction_configuration_before_loading(options, message):
    with pytest.raises(SystemExit, match=message):
        cli.parse_arguments(["local", "missing.txt", "--search", "population", *options])


def test_objective_is_population_only_and_toml_target_alias_is_reused(tmp_path):
    with pytest.raises(SystemExit, match="requires --search population"):
        cli.parse_arguments(["local", "missing.txt", "--objective", "earliest-interaction", "--target-object", "gold:0"])
    with pytest.raises(SystemExit):
        cli.parse_arguments(["jump-pattern", "missing.txt", "--objective", "earliest-interaction"])
    config = tmp_path / "local.toml"
    config.write_text('[local]\nsearch="population"\nobjective="earliest-interaction"\n'
                      'target-object="switch:0"\narrival_start=5\nsecondary_objective="max-vx"\n')
    parsed = cli.parse_arguments(["local", "missing.txt", "--config", str(config), "--target-object", "gold:any"])
    assert parsed._mode_configs.local.target_object == "gold:any"
    assert parsed._mode_configs.local.arrival_start == 5
    assert parsed._mode_configs.local.secondary_objective == "max-vx"


@pytest.mark.parametrize("workers", [1, 2])
def test_cli_toml_reports_actual_event_and_preserves_packed_tail(tmp_path, workers):
    from test_population_integration import _read_replay, _run, _write_replay

    original = (InputFrame(right=True),) * 45
    source, output = tmp_path / "source.txt", tmp_path / "event.txt"
    level_string = _write_replay(source, original, "0^100,100!0^120,105")
    config = tmp_path / "interaction.toml"
    config.write_text('[local]\nsearch="population"\nobjective="earliest-interaction"\n'
                      'target_object="gold:any"\nrange="5:16"\ntarget_frame=24\n'
                      'secondary_objective="max-vx"\nvx_window="0.8:"\nrequire_interaction=["gold:0"]\n')
    stdout = _run(source, "--config", config, "--output", output, "--workers", workers,
                  "--iterations", 24, "--beam", 4, "--rounds", 1, "--repair-steps", 2,
                  "--seed", 7, "--python-resimulate")
    _, frames = _read_replay(output)
    rows = python_rows(parse_level_string(level_string, simulate_enemies=True), frames)
    event = next(i for i, row in enumerate(rows) if row["gold"] & 2)
    assert event == 9 and rows[event]["vx"] >= .8
    assert all(frames[i].horizontal == original[i].horizontal for i in range(len(frames)) if i < 5 or i > 16)
    assert len(frames) == len(original)
    assert "interaction=gold:1" in stdout and "interaction tie-break: max-vx" in stdout
    assert "eligible frames 5:24" in stdout
    reported = re.search(r"  1\. frame=(\d+); score=([^;]+);", stdout)
    assert int(reported[1]) == event and float(reported[2]) == -event


def test_cli_rejects_consumed_prefix_without_overwriting_existing_output(tmp_path):
    from test_population_integration import _write_replay

    source, output = tmp_path / "source.txt", tmp_path / "event.txt"
    _write_replay(source, (InputFrame(right=True),) * 20, "0^100,100")
    output.write_text("keep this earlier TAS\n")
    completed = subprocess.run([sys.executable, str(ROOT / "optimize_replay.py"), "local", str(source),
        "--search", "population", "--objective", "earliest-interaction", "--target-object", "gold:0",
        "--range", "5:10", "--target-frame", "15", "--workers", "1", "--iterations", "2", "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert completed.returncode != 0 and "immutable prefix already consumed" in completed.stderr
    assert "no output was written" in completed.stderr and output.read_text() == "keep this earlier TAS\n"

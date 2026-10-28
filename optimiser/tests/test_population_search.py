from __future__ import annotations

from dataclasses import replace
import json
import random

import pytest

from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_engine import InputFrame, parse_level_string
from nv14_objectives import AxisWindow
from nv14_population import (
    PopulationCandidate, PopulationConfig, _assert_bounded, _diverse_results,
    _input_key, _mutate, _select_population, optimise_local_population,
)
from nv14_replay import decode_complex_replay, encode_complex_replay


EMPTY_MAP = "0" * (31 * 23)


def level():
    return parse_level_string(EMPTY_MAP + "|5^100,100")


def candidate(frames, evaluation, edits=0):
    return PopulationCandidate(tuple(frames), evaluation, (), edits, _input_key(frames))


def test_every_mutation_operator_preserves_disjoint_ranges_and_length():
    source = tuple(InputFrame(left=i % 4 == 0, right=i % 4 == 2,
                              jump=i % 6 < 3, jump_trigger=None if i % 2 else False)
                   for i in range(35))
    goal = EndpointGoal(20)
    endpoint = EndpointEvaluator(level(), goal).evaluate(source)
    parent = candidate(source, endpoint)
    donor = candidate(tuple(InputFrame(right=True, jump=True) for _ in source), endpoint)
    ranges = ((4, 8), (13, 20))
    mutable = tuple(i for lo, hi in ranges for i in range(lo, hi + 1))
    seen = set()
    rng = random.Random(7319)
    for _ in range(1500):
        frames, label, _ = _mutate(parent, donor, ranges, mutable, rng, 32)
        _assert_bounded(source, frames, frozenset(mutable))
        assert len(frames) == len(source)
        seen.add(label.split()[0])
    assert {"horizontal", "direction", "sparse", "jump", "section", "all-input"} <= seen


def test_range_guard_checks_explicit_jump_trigger_and_suffix_length():
    source = (InputFrame(),) * 8
    changed = list(source)
    changed[0] = InputFrame(jump_trigger=False)
    with pytest.raises(ValueError, match="outside"):
        _assert_bounded(source, changed, frozenset((3, 4)))
    with pytest.raises(ValueError, match="length"):
        _assert_bounded(source, source[:-1], frozenset((3, 4)))


def test_population_evolves_with_repair_and_ignores_post_endpoint_death():
    source = (InputFrame(),) * 150
    goal = EndpointGoal(19, objective="max-x")
    ranges = ((3, 8), (12, 15))
    saved = []
    result = optimise_local_population(level(), source, goal=goal, frame_ranges=ranges,
        config=PopulationConfig(iterations=250, rounds=2, beam=8, workers=1,
                                repair_steps=16, seed=17, top_results=4),
        best_callback=lambda value: saved.append(value))
    assert result.rounds == 2
    assert result.candidates and result.candidates[0].evaluation.score > result.baseline.score
    assert len(result.candidates) > 1
    assert len({c.evaluation.state_key for c in result.candidates}) == len(result.candidates)
    assert [c.evaluation.score for c in result.candidates] == sorted(
        (c.evaluation.score for c in result.candidates), reverse=True)
    mutable = frozenset(i for lo, hi in ranges for i in range(lo, hi + 1))
    for value in result.candidates:
        _assert_bounded(source, value.frames, mutable)
        checked = verify_endpoint(level(), value.frames, goal, value.evaluation, python_resimulate=True)
        assert checked.feasible
    assert saved[-1].frames == result.candidates[0].frames
    terminal = EndpointEvaluator(level(), EndpointGoal(149)).evaluate(result.candidates[0].frames)
    assert terminal.dead


def test_earliest_arrival_finds_first_valid_tick_and_obeys_velocity():
    source = (InputFrame(),) * 12
    goal = EndpointGoal(9, objective="earliest-arrival", target_region=(100.2, 120, 0, 200),
                        vx_window=AxisWindow(0.15, 1.0))
    result = optimise_local_population(level(), source, goal=goal, frame_ranges=((0, 9),),
        config=PopulationConfig(iterations=180, rounds=2, beam=8, workers=1,
                                repair_steps=8, seed=7))
    assert not result.baseline.feasible
    winner = result.candidates[0]
    assert winner.evaluation.frame == 2
    assert winner.evaluation.score == -2
    assert 0.15 <= winner.evaluation.vx <= 1.0
    verify_endpoint(level(), winner.frames, goal, winner.evaluation, python_resimulate=True)


def test_beam_one_cannot_discard_feasible_best_for_repair_frontier():
    frames = (InputFrame(),) * 3
    valid = EndpointEvaluator(level(), EndpointGoal(2)).evaluate(frames)
    invalid = replace(valid, feasible=False, progress_key=(1, 0))
    good = candidate(frames, valid)
    bad = candidate((InputFrame(left=True),) * 3, invalid, 3)
    assert _select_population((good, bad), 1) == (good,)


def test_beam_one_checkpoint_retains_best_when_infeasible_mutations_exist(tmp_path):
    source = (InputFrame(),) * 8
    goal = EndpointGoal(7, vx_window=AxisWindow(0, 0))
    path = tmp_path / "one.json"
    config = PopulationConfig(iterations=40, beam=1, workers=1, repair_steps=0,
                              seed=318, checkpoint_path=path)
    first = optimise_local_population(level(), source, goal=goal, frame_ranges=((0, 7),), config=config)
    saved = json.loads(path.read_text())["payload"]["population"]
    assert len(saved) == 1 and saved[0]["feasible"]
    resumed = optimise_local_population(level(), source, goal=goal, frame_ranges=((0, 7),),
                                         config=replace(config, rounds=2, resume=True))
    assert resumed.candidates[0].evaluation.feasible
    assert resumed.candidates[0].evaluation.score >= first.candidates[0].evaluation.score


def test_source_jump_edges_are_normalised_before_search_and_packed_verification():
    tiles = ["0"] * (31 * 23)
    tiles[4 * 23 + 5] = "1"
    ground = parse_level_string("".join(tiles) + "|5^132,134")
    source = (InputFrame(jump=True, jump_trigger=False), InputFrame(),
              InputFrame(jump=True, jump_trigger=True), InputFrame(jump=True, jump_trigger=False))
    goal = EndpointGoal(3, objective="min-y")
    verified = []

    def save(value):
        packed = decode_complex_replay(encode_complex_replay(value.frames)).frames
        verified.append(verify_endpoint(ground, packed, goal, value.evaluation, python_resimulate=True))

    result = optimise_local_population(ground, source, goal=goal, frame_ranges=((1, 2),),
        config=PopulationConfig(iterations=50, workers=1, repair_steps=4), best_callback=save)
    assert verified and result.candidates
    assert all(frame.jump_trigger is None for frame in result.candidates[0].frames)
    for index in (0, 3):
        actual = result.candidates[0].frames[index]
        assert (actual.left, actual.right, actual.jump) == (source[index].left, source[index].right, source[index].jump)


def test_checkpoint_resume_matches_uninterrupted_and_checks_identity(tmp_path):
    source = (InputFrame(),) * 12
    goal = EndpointGoal(9)
    config = PopulationConfig(iterations=80, rounds=2, beam=6, workers=1,
                              repair_steps=6, seed=123)
    full = optimise_local_population(level(), source, goal=goal, frame_ranges=((2, 8),), config=config)
    path = tmp_path / "population.json"
    first = optimise_local_population(level(), source, goal=goal, frame_ranges=((2, 8),),
        config=replace(config, rounds=1, checkpoint_path=path))
    assert first.rounds == 1
    resumed = optimise_local_population(level(), source, goal=goal, frame_ranges=((2, 8),),
        config=replace(config, checkpoint_path=path, resume=True))
    assert resumed.rounds == full.rounds
    assert resumed.evaluations == full.evaluations
    assert resumed.candidates[0].frames == full.candidates[0].frames
    assert resumed.candidates[0].evaluation == full.candidates[0].evaluation
    with pytest.raises(ValueError, match="differs"):
        optimise_local_population(level(), source, goal=replace(goal, objective="min-x"),
            frame_ranges=((2, 8),), config=replace(config, checkpoint_path=path, resume=True))
    with pytest.raises(ValueError, match="seed differs"):
        optimise_local_population(level(), source, goal=goal, frame_ranges=((2, 8),),
            config=replace(config, checkpoint_path=path, resume=True, seed=4))
    envelope = json.loads(path.read_text())
    envelope["payload"]["rounds"] += 1
    path.write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match="integrity"):
        optimise_local_population(level(), source, goal=goal, frame_ranges=((2, 8),),
            config=replace(config, checkpoint_path=path, resume=True))


def test_population_parallel_is_deterministic_and_checkpoint_reproducible(tmp_path):
    source = (InputFrame(),) * 12
    goal = EndpointGoal(9)
    config = PopulationConfig(iterations=40, rounds=2, beam=4, workers=2,
                              repair_steps=4, seed=914, top_results=3)
    full = optimise_local_population(level(), source, goal=goal, frame_ranges=((0, 8),), config=config)
    path = tmp_path / "parallel.json"
    optimise_local_population(level(), source, goal=goal, frame_ranges=((0, 8),),
        config=replace(config, rounds=1, checkpoint_path=path))
    resumed = optimise_local_population(level(), source, goal=goal, frame_ranges=((0, 8),),
        config=replace(config, checkpoint_path=path, resume=True))
    assert resumed.evaluations == full.evaluations
    assert [(c.frames, c.evaluation) for c in resumed.candidates] == [
        (c.frames, c.evaluation) for c in full.candidates]


def test_impossible_prefix_death_errors_but_arrival_before_prefix_death_is_valid():
    source = (InputFrame(),) * 160
    with pytest.raises(ValueError, match="immutable prefix dies"):
        optimise_local_population(level(), source, goal=EndpointGoal(159), frame_ranges=((155, 159),),
            config=PopulationConfig(iterations=2, workers=1))
    result = optimise_local_population(level(), source,
        goal=EndpointGoal(159, objective="earliest-arrival", target_region=(90, 110, 90, 110)),
        frame_ranges=((155, 159),), config=PopulationConfig(iterations=2, workers=1))
    assert result.candidates[0].evaluation.frame == 0


def test_no_feasible_candidate_never_calls_saved_best_callback():
    source = (InputFrame(),) * 6
    saved = []
    result = optimise_local_population(level(), source,
        goal=EndpointGoal(5, vx_window=AxisWindow(100, 101)), frame_ranges=((0, 5),),
        config=PopulationConfig(iterations=20, workers=1, repair_steps=3),
        best_callback=saved.append)
    assert not result.candidates
    assert not saved

"""Arrival tie-breaks through native evaluation, search and user-facing I/O."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

import nv14_cli as cli
import nv14_population as population
from nv14_checkpoint import canonical_json_bytes
from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_engine import InputFrame, parse_level_string


CASES = (("max-x", "x", 1), ("max-y", "y", 1), ("max-vx", "vx", 1), ("max-vy", "vy", 1),
         ("min-x", "x", -1), ("min-y", "y", -1), ("min-vx", "vx", -1), ("min-vy", "vy", -1))
CHOICES = tuple(case[0] for case in CASES)


def ground_level():
    tiles = ["0"] * (31 * 23)
    tiles[4 * 23 + 5] = "1"
    return parse_level_string("".join(tiles) + "|5^132,134")


def arrival_goal(secondary=None, *, start=5, deadline=11):
    return EndpointGoal(deadline, objective="earliest-arrival", arrival_start=start,
                        target_region=(0, 740, 0, 550), secondary_objective=secondary)


def make_candidate(frames, evaluation, source):
    return population.PopulationCandidate(tuple(frames), evaluation,
        edits=sum(a != b for a, b in zip(frames, source)), input_key=population._input_key(frames))


@pytest.mark.parametrize("secondary,attribute,sign", CASES)
def test_secondary_measures_first_qualifying_arrival_and_signed_velocity(secondary, attribute, sign):
    level = ground_level()
    frames = (InputFrame(left=True, jump=True),) * 12
    goal = arrival_goal(secondary, start=3)
    actual = verify_endpoint(level, frames, goal, python_resimulate=True)
    endpoint = EndpointEvaluator(level, EndpointGoal(11)).evaluate(frames)
    assert actual.feasible and actual.frame == 3 and actual.score == -3
    assert actual.secondary_value == getattr(actual, attribute)
    assert actual.secondary_score == sign * actual.secondary_value
    assert actual.secondary_value != getattr(endpoint, attribute)
    if attribute in ("vx", "vy"):
        assert actual.secondary_value < 0  # use signed velocity, not magnitude
    for field in ("secondary_score", "secondary_value"):
        with pytest.raises(ValueError, match=field):
            verify_endpoint(level, frames, goal, expected=replace(actual, **{field: getattr(actual, field) + 1}))


@pytest.mark.parametrize("secondary", CHOICES)
def test_secondary_precedes_edit_count_in_beams_elites_and_ranked_results(secondary):
    level = ground_level()
    horizontal = secondary.endswith(("-x", "-vx"))
    minimise = secondary.startswith("min-")
    if horizontal:
        source = (InputFrame(),) * 12
        changed = (InputFrame(left=minimise, right=not minimise),) * 12
    else:
        source = (InputFrame(jump=not minimise),) * 12
        changed = (InputFrame(jump=minimise),) * 12
    evaluator = EndpointEvaluator(level, arrival_goal(secondary))
    baseline = make_candidate(source, evaluator.evaluate(source), source)
    better = make_candidate(changed, evaluator.evaluate(changed), source)
    assert baseline.evaluation.frame == better.evaluation.frame == 5
    assert better.evaluation.secondary_score > baseline.evaluation.secondary_score
    if minimise:
        assert better.evaluation.secondary_value < baseline.evaluation.secondary_value
    else:
        assert better.evaluation.secondary_value > baseline.evaluation.secondary_value
    assert better.edits > baseline.edits
    for candidates in ((baseline, better), (better, baseline)):
        assert min(candidates, key=population._rank) == better
        assert population._select_population(candidates, 1) == (better,)
        assert population._diverse_results(candidates, 2)[0] == better
    # Without a configured secondary, the source wins the same arrival tie.
    evaluator = EndpointEvaluator(level, arrival_goal())
    original = make_candidate(source, evaluator.evaluate(source), source)
    alternative = make_candidate(changed, evaluator.evaluate(changed), source)
    assert population._diverse_results((alternative, original), 1) == (original,)


@pytest.mark.parametrize("secondary", ("max-vx", "min-vx"))
def test_earlier_arrival_wins_over_better_secondary_velocity(secondary):
    level = ground_level()
    minimise = secondary == "min-vx"
    forward = InputFrame(left=minimise, right=not minimise)
    backward = InputFrame(left=not minimise, right=minimise)
    source = (forward,) * 12
    # Both enter the same region; a slower approach can qualify earlier with
    # less momentum than one accelerating from further left.
    region = (114, 131.8, 0, 550) if minimise else (132.2, 150, 0, 550)
    goal = EndpointGoal(11, objective="earliest-arrival", target_region=region,
                        secondary_objective=secondary)
    early_frames = (forward,) * 2 + (InputFrame(),) * 10
    late_frames = (backward,) * 2 + (forward,) * 10
    evaluator = EndpointEvaluator(level, goal)
    early = make_candidate(early_frames, evaluator.evaluate(early_frames), source)
    late = make_candidate(late_frames, evaluator.evaluate(late_frames), source)
    assert early.evaluation.feasible and late.evaluation.feasible
    assert early.evaluation.frame < late.evaluation.frame
    assert early.evaluation.secondary_score < late.evaluation.secondary_score
    assert population._select_population((late, early), 1) == (early,)
    assert population._diverse_results((late, early), 1) == (early,)


@pytest.mark.parametrize("secondary", ("max-vx", "min-vx"))
def test_exact_objective_ties_keep_edit_count_then_encoded_input_order(secondary):
    level = ground_level()
    source = (InputFrame(),) * 12
    evaluator = EndpointEvaluator(level, arrival_goal(secondary))
    # All changes are after arrival, so every objective value is identical.
    variants = [source,
        source[:8] + (InputFrame(left=True),) + source[9:],
        source[:8] + (InputFrame(right=True),) + source[9:],
        source[:8] + (InputFrame(right=True),) * 2 + source[10:]]
    candidates = [make_candidate(frames, evaluator.evaluate(frames), source) for frames in variants]
    assert len({c.evaluation.objective_key for c in candidates}) == 1
    assert sorted(reversed(candidates), key=population._primary_rank) == candidates
    assert sorted(reversed(candidates), key=population._rank) == candidates


def test_unreachable_arrivals_keep_existing_constraint_progress_order():
    frames = (InputFrame(),) * 12
    goal = replace(arrival_goal(), target_region=(500, 510, 0, 550))
    baseline = EndpointEvaluator(ground_level(), goal).evaluate(frames)
    for secondary in CHOICES:
        actual = EndpointEvaluator(ground_level(), replace(goal, secondary_objective=secondary)).evaluate(frames)
        assert not actual.feasible
        assert actual == baseline


@pytest.mark.parametrize("secondary", ("max-x", "min-x"))
def test_secondary_gain_resets_stagnation_but_edit_only_gain_does_not(monkeypatch, secondary):
    level = ground_level()
    minimise = secondary == "min-x"
    forward = InputFrame(left=minimise, right=not minimise)
    source = (InputFrame(left=not minimise, right=minimise),) * 6
    goal = arrival_goal(secondary, start=3, deadline=5)
    proposals = [
        (forward,) + source[1:],
        (forward,) * 2 + source[2:4] + (forward,) * 2,
        (forward,) * 2 + source[2:],
    ]

    def worker(job, context, observer):
        round_index, _, _, parents = job
        candidate = context.candidate(proposals[round_index - 1], (f"controlled proposal {round_index}",))
        observer(candidate, 1, 1)
        return (*parents, candidate), 1

    monkeypatch.setattr(population, "_run_worker", worker)
    saved, messages = [], []
    result = population.optimise_local_population(level, source, goal=goal, frame_ranges=((0, 5),),
        config=population.PopulationConfig(iterations=1, workers=1, rounds=0, stagnation_rounds=1),
        best_callback=saved.append, progress=messages.append)
    assert result.rounds == 3 and result.stagnant_rounds == 1
    assert len(saved) == 4  # baseline, two secondary gains, then fewer edits
    assert {c.evaluation.frame for c in saved} == {3}
    assert saved[0].evaluation.secondary_score < saved[1].evaluation.secondary_score < saved[2].evaluation.secondary_score
    assert saved[2].evaluation.secondary_score == saved[3].evaluation.secondary_score
    assert saved[3].edits < saved[2].edits
    assert result.candidates[0].frames == proposals[-1]
    assert any(f"secondary {secondary}={saved[-1].evaluation.secondary_value:.15g}" in message for message in messages)


@pytest.mark.parametrize("workers", (1, 2))
@pytest.mark.parametrize("secondary", ("max-vx", "min-vx"))
def test_secondary_search_saves_improvements_and_resumes_exactly(tmp_path, workers, secondary):
    level = ground_level()
    source = (InputFrame(),) * 12
    goal = arrival_goal(secondary)
    config = population.PopulationConfig(iterations=80, rounds=2, beam=8, workers=workers,
                                         repair_steps=4, seed=123, top_results=3)
    saved = []
    full = population.optimise_local_population(level, source, goal=goal, frame_ranges=((2, 8),),
                                                config=config, best_callback=saved.append)
    assert full.candidates[0].evaluation.frame == full.baseline.frame == 5
    assert full.candidates[0].evaluation.secondary_score > full.baseline.secondary_score
    assert saved[-1].frames == full.candidates[0].frames
    for candidate in full.candidates:
        verify_endpoint(level, candidate.frames, goal, candidate.evaluation, python_resimulate=True)
    path = tmp_path / "secondary.json"
    population.optimise_local_population(level, source, goal=goal, frame_ranges=((2, 8),),
        config=replace(config, rounds=1, checkpoint_path=path))
    resumed = population.optimise_local_population(level, source, goal=goal, frame_ranges=((2, 8),),
        config=replace(config, checkpoint_path=path, resume=True))
    assert resumed.evaluations == full.evaluations
    assert resumed.stagnant_rounds == full.stagnant_rounds
    assert resumed.candidates == full.candidates
    envelope = json.loads(path.read_text())
    assert envelope["payload"]["identity"]["goal"]["secondary_objective"] == secondary
    with pytest.raises(ValueError, match="differs"):
        population.optimise_local_population(level, source, goal=replace(goal, secondary_objective="max-x"),
            frame_ranges=((2, 8),), config=replace(config, checkpoint_path=path, resume=True))
    for field in ("secondary_score", "secondary_value"):
        tampered = json.loads(json.dumps(envelope))
        tampered["payload"]["population"][0][field] += 1
        tampered["sha256"] = hashlib.sha256(canonical_json_bytes(tampered["payload"])).hexdigest()
        path.write_text(json.dumps(tampered))
        with pytest.raises(ValueError, match="endpoint re-verification"):
            population.optimise_local_population(level, source, goal=goal, frame_ranges=((2, 8),),
                config=replace(config, checkpoint_path=path, resume=True))


@pytest.mark.parametrize("secondary", CHOICES)
def test_secondary_cli_toml_and_cli_override(tmp_path, secondary):
    config = tmp_path / "arrival.toml"
    config.write_text('[local]\nsearch = "population"\nobjective = "earliest-arrival"\n'
                      f'target_region = [0, 740, 0, 550]\nsecondary_objective = "{secondary}"\n')
    args = cli.parse_arguments(["local", "source.txt", "--config", str(config)])
    assert args._mode_configs.local.secondary_objective == secondary
    override = "min-vx" if secondary.startswith("max-") else "max-vx"
    args = cli.parse_arguments(["local", "source.txt", "--config", str(config),
                                "--secondary-objective", override])
    assert args._mode_configs.local.secondary_objective == override
    args = cli.parse_arguments(["local", "source.txt", "--search", "population",
        "--objective", "earliest-arrival", "--target-region", "0:740,0:550",
        "--secondary-objective", secondary])
    assert args._mode_configs.local.secondary_objective == secondary


@pytest.mark.parametrize("options,message", [
    (["--secondary-objective", "max-x"], "require --search population"),
    (["--search", "population", "--secondary-objective", "max-x"], "requires --objective earliest-arrival"),
    (["--search", "population", "--secondary-objective", "min-speed"], None),
])
def test_incompatible_secondary_cli_settings_fail_before_loading(options, message):
    with pytest.raises(SystemExit, match=message):
        cli.parse_arguments(["local", "source.txt", *options])


@pytest.mark.parametrize("secondary", ("min-speed", "max-speed", 1, False))
def test_invalid_secondary_toml_and_api_values_fail(tmp_path, secondary):
    config = tmp_path / "invalid.toml"
    config.write_text('[local]\nsearch = "population"\nobjective = "earliest-arrival"\n'
                      f'target_region = [0, 740, 0, 550]\nsecondary_objective = {json.dumps(secondary)}\n')
    with pytest.raises(SystemExit):
        cli.parse_arguments(["local", "source.txt", "--config", str(config)])
    with pytest.raises(ValueError, match="unknown secondary objective"):
        arrival_goal(secondary)


def test_secondary_default_scope_and_help():
    assert cli.parse_arguments(["local", "source.txt"])._mode_configs.local.secondary_objective is None
    with pytest.raises(ValueError, match="requires earliest-arrival"):
        EndpointGoal(5, secondary_objective="max-vx")
    with pytest.raises(ValueError, match="requires --objective earliest-arrival"):
        cli.LocalConfig(search="population", secondary_objective="max-vy")
    with pytest.raises(ValueError, match="require --search population"):
        cli.LocalConfig(secondary_objective="max-x")
    for mode in ("auto", "jump-pattern"):
        with pytest.raises(SystemExit):
            cli.parse_arguments([mode, "source.txt", "--secondary-objective", "max-x"])
    parsers = cli.build_parser()._command_parsers
    assert "--secondary-objective" in parsers["local"].format_help()
    assert all("--secondary-objective" not in parsers[mode].format_help() for mode in ("auto", "jump-pattern"))


@pytest.mark.parametrize("workers", (1, 2))
@pytest.mark.parametrize("secondary", ("max-vx", "min-vx"))
def test_secondary_cli_output_matches_independent_python_physics(tmp_path, workers, secondary):
    from test_population_integration import _read_replay, _run, _scan, _write_replay

    source, output = tmp_path / "source.txt", tmp_path / "arrival.txt"
    original = (InputFrame(),) * 20
    level = _write_replay(source, original)
    config = tmp_path / "arrival.toml"
    config.write_text('[local]\nsearch = "population"\nobjective = "earliest-arrival"\n'
                      'range = "2:8"\ntarget_frame = 12\narrival_start = 8\n'
                      f'target_region = [0, 200, 0, 200]\nsecondary_objective = "{secondary}"\n')
    stdout = _run(source, "--config", config, "--output", output,
        "--iterations", 160, "--workers", workers, "--rounds", 2, "--beam", 8,
        "--repair-steps", 4, "--seed", 123, "--top-results", 3, "--python-resimulate")
    values = []
    for rank in (1, 2, 3):
        path = output if rank == 1 else tmp_path / f"arrival.rank{rank:02d}.txt"
        _, frames = _read_replay(path)
        rows = _scan(level, frames)
        assert len(frames) == len(original)
        assert all((f.left, f.right, f.jump) == (False, False, False)
                   for i, f in enumerate(frames) if i < 2 or i > 8)
        x, y, vx, _, dead, *_ = rows[8]
        assert not dead and 0 <= x <= 200 and 0 <= y <= 200
        values.append(vx)
    if secondary == "min-vx":
        assert values[0] < _scan(level, original)[8][2]
    else:
        assert values[0] > _scan(level, original)[8][2]
    assert values == sorted(values, reverse=secondary == "max-vx")
    assert f"arrival tie-break: {secondary}" in stdout
    assert f"secondary {secondary}={values[0]:.15g}" in stdout
    assert "1. frame=8; score=-8;" in stdout

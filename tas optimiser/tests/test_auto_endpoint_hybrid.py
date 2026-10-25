"""Regressions for enhanced endpoint-Auto (independent of finished TAS runs)."""
from dataclasses import replace
import random

import pytest

from nv14_auto_endpoint import (
    AutoEndpointCandidate, AutoEndpointConfig, _endpoint_repair,
    _hybrid_proposal, _key, _repair_frame_candidates, _select_endpoint_beam,
    optimise_auto_endpoint,
)
from nv14_cli import parse_arguments
from nv14_endpoint import EndpointGoal, EndpointEvaluator, verify_endpoint
from tests.test_required_jump_region import floor_level, replay, ORIGIN
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame, parse_level_string


def _level():
    return parse_level_string("0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + "|5^60,60")


def test_endpoint_hybrid_preserves_editable_bounds_and_uses_local_macros():
    level = _level()
    source = tuple(InputFrame() for _ in range(36))
    goal = EndpointGoal(target_frame=23, objective="max-x")
    baseline = AutoEndpointCandidate(source, EndpointEvaluator(level, goal).evaluate(source))
    donor_frames = tuple(InputFrame(right=True) for _ in source)
    donor = AutoEndpointCandidate(donor_frames, EndpointEvaluator(level, goal).evaluate(donor_frames))
    rng = random.Random(821)
    different = 0
    for _ in range(180):
        result, anchor = _hybrid_proposal(baseline, donor, rng=rng,
                                          config=AutoEndpointConfig(), start=7, end=23)
        assert len(result) == len(source)
        assert result[:7] == source[:7]
        assert result[24:] == source[24:]
        assert 7 <= anchor <= 23
        different += result != source
    assert different > 50


def test_hybrid_beam_retains_infeasible_physical_niches():
    level = _level()
    frames = tuple(InputFrame() for _ in range(12))
    evaluation = EndpointEvaluator(level, EndpointGoal(target_frame=8)).evaluate(frames)
    candidates = []
    for i in range(12):
        edited = list(frames)
        edited[i] = InputFrame(right=True)
        feasible = i < 7
        state = replace(evaluation, feasible=feasible,
                        niche_key=("niche", i), progress_key=(0 if feasible else 1, i))
        candidates.append(AutoEndpointCandidate(tuple(edited), state))
    selected = _select_endpoint_beam(candidates, 8, _key(frames))
    assert len(selected) == 8
    assert any(c.evaluation.feasible for c in selected)
    assert any(not c.evaluation.feasible for c in selected)
    assert len({c.evaluation.niche_key for c in selected}) >= 7


def test_reference_guided_repair_restores_required_jump():
    level = floor_level()
    reference = replay(30, jumps=(5,))
    goal = EndpointGoal(target_frame=25, objective="max-x",
                        require_jump_region=ORIGIN,
                        require_jump_frames=(5, 5))
    evaluator = EndpointEvaluator(level, goal)
    original = evaluator.evaluate(reference)
    assert original.feasible
    broken = tuple(reference[:5] + (InputFrame(),) + reference[6:])
    broken_eval = evaluator.evaluate(broken)
    assert not broken_eval.feasible
    parent = AutoEndpointCandidate(reference, original)
    candidate = AutoEndpointCandidate(broken, broken_eval)
    visited = {_key(broken)}
    recovered = []

    def consider(frames):
        key = _key(frames)
        if key in visited:
            return None
        visited.add(key)
        evaluation = evaluator.evaluate(frames)
        outcome = AutoEndpointCandidate(frames, evaluation)
        if evaluation.feasible:
            recovered.append(outcome)
        return outcome

    _endpoint_repair(candidate, parent, reference, goal,
                     anchor=5, start=0, end=25,
                     config=AutoEndpointConfig(repair_steps=24),
                     rng=random.Random(0), consider=consider, budget=24)
    assert recovered
    assert verify_endpoint(level, recovered[0].frames, goal).feasible


def test_hybrid_only_obeys_budgets_and_replay_verification():
    level = _level()
    frames = tuple(InputFrame() for _ in range(42))
    goal = EndpointGoal(target_frame=24, objective="max-x")
    baseline, winner, evaluated = optimise_auto_endpoint(
        level, frames, goal, AutoEndpointConfig(
            iterations=140, beam_width=12, seed=28,
            range_start=5, range_end=24, repair_steps=12,
        ),
    )
    assert 0 < evaluated <= 140
    assert winner is not None
    assert winner.evaluation.score >= baseline.evaluation.score
    assert winner.frames[:5] == frames[:5]
    assert winner.frames[25:] == frames[25:]
    assert verify_endpoint(level, winner.frames, goal, expected=winner.evaluation).feasible


def test_cli_hybrid_only_and_compatible_toml(tmp_path):
    config = tmp_path / "splice.toml"
    config.write_text('''[local]
search = "population"
objective = "max-x"
target-frame = 25
range = ":25"
''')
    default = tmp_path / "auto.toml"
    default.write_text('''[auto]
iterations = 300
endpoint-strategy = "hybrid"
endpoint-repair-steps = 18
endpoint-repair-lookback = 50
''')
    args = parse_arguments(["auto", "source.txt", "--config", str(default),
                            "--goal-config", str(config)])
    assert args.auto_objective == "max-x"
    assert args.auto_endpoint_strategy == "hybrid"
    assert args.auto_endpoint_repair_steps == 18
    assert args.auto_endpoint_repair_lookback == 50
    # Existing configs specifying hybrid remain valid, but the option is
    # hidden because there is now only one endpoint algorithm.
    with pytest.raises(SystemExit):
        parse_arguments(["auto", "source.txt", "--config", str(default),
                         "--goal-config", str(config),
                         "--auto-endpoint-strategy", "legacy"])
    default.write_text(default.read_text().replace('"hybrid"', '"legacy"'))
    with pytest.raises(SystemExit):
        parse_arguments(["auto", "source.txt", "--config", str(default),
                         "--goal-config", str(config)])
    with pytest.raises(ValueError, match="repair-steps"):
        AutoEndpointConfig(repair_steps=-1)

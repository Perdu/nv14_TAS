"""Fast endpoint Auto must retain its original ranking and replay identity."""
from dataclasses import replace
import random

from nv14_auto_endpoint import (
    AutoEndpointCandidate, AutoEndpointConfig, _key, _packed_keys,
    _rank, optimise_auto_endpoint,
)
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame, parse_level_string
from nv14_population import (
    PopulationCandidate, _rank as _population_rank, _select_population,
    _select_population_from_ranked,
)


def _level():
    return parse_level_string("0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + "|5^60,60")


def test_native_key_preserves_legacy_held_button_identity_and_full_trigger_bits():
    frames = (
        InputFrame(), InputFrame(left=True, jump_trigger=True),
        InputFrame(right=True, jump=True, jump_trigger=False),
        InputFrame(left=True, right=True, jump=True),
    )
    packed, identity = _packed_keys(frames)
    expected = bytes(int(f.left) | (int(f.right) << 1) | (int(f.jump) << 2)
                     for f in frames)
    assert identity == expected == _key(frames)
    assert packed != identity  # trigger information remains available to physics
    altered = (frames[0], replace(frames[1], jump_trigger=False), *frames[2:])
    new_native, new_held = _packed_keys(altered)
    assert new_native != packed
    assert new_held == identity


def test_native_packed_evaluation_is_equivalent_to_normal_evaluation():
    level = _level()
    source = (InputFrame(),) * 40
    goal = EndpointGoal(target_frame=24, objective="max-x")
    scorer = EndpointEvaluator(level, goal, source, prefix_frame=5)
    frames = source[:5] + (InputFrame(right=True),) * 12 + source[17:]
    packed, identity = _packed_keys(frames)
    assert identity == _key(frames)
    assert scorer._evaluate_packed(packed, frames) == scorer.evaluate(frames)


def test_precomputed_rank_matches_legacy_tie_break():
    level = _level()
    source = (InputFrame(),) * 40
    result = EndpointEvaluator(level, EndpointGoal(target_frame=24, objective="max-x")).evaluate(source)
    source_key = _key(source)
    frames = source[:6] + (InputFrame(right=True),) * 8 + source[14:]
    identity = _key(frames)
    legacy = AutoEndpointCandidate(frames, result)
    cached = AutoEndpointCandidate(frames, result, False, identity, 8)
    assert cached == legacy
    assert _rank(cached, source_key) == _rank(legacy, source_key)


def test_presorted_local_selection_matches_original_across_niches():
    level = _level()
    source = (InputFrame(),) * 28
    evaluation = EndpointEvaluator(level, EndpointGoal(target_frame=20)).evaluate(source)
    rng = random.Random(928)
    for width in (4, 8, 16, 32):
        items = []
        for i in range(60):
            feasible = i % 3 != 0
            result = replace(
                evaluation, feasible=feasible,
                niche_key=(i % 9, i % 4),
                progress_key=(int(not feasible), rng.randrange(20)),
                score=float(rng.randrange(9)),
            )
            items.append(PopulationCandidate(
                source, result, edits=rng.randrange(15), input_key=i.to_bytes(2, "little")
            ))
        ranked = sorted(items, key=_population_rank)
        old = _select_population(items, width)
        new = _select_population_from_ranked(ranked, width)
        assert [c.input_key for c in new] == [c.input_key for c in old]


def test_seeded_search_retains_exact_best_and_evaluation_count():
    level = _level()
    source = (InputFrame(),) * 40
    goal = EndpointGoal(target_frame=24, objective="max-x")
    for progressive, expected in ((False, 218), (True, 222)):
        callbacks = []
        baseline, winner, evaluations = optimise_auto_endpoint(
            level, source, goal,
            AutoEndpointConfig(iterations=260, beam_width=16, seed=17,
                               range_start=4, range_end=24, repair_steps=0,
                               progressive_refinement=progressive),
            best_callback=lambda candidate: callbacks.append(candidate.evaluation.objective_key),
        )
        assert evaluations == expected
        assert winner is not None
        assert winner.evaluation.objective_key == (-79.53058953904592, -0.0)
        assert len(callbacks) == (5 if progressive else 7)
        assert baseline.evaluation.objective_key == (-60.0, -0.0)

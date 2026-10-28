"""Regression and microbenchmark guards for endpoint Auto's cached beam.

The reference selection below intentionally expresses the pre-optimisation
algorithm, rather than calling the new cached selector to validate itself.
"""
from dataclasses import replace
import random

from nv14_auto_endpoint import (
    AutoEndpointCandidate, _EndpointBeam, _key, _rank,
)
from nv14_endpoint import EndpointEvaluation
from nv14_engine import InputFrame


def _reference_beam(candidates, size, source_key):
    unique = {_key(candidate.frames): candidate for candidate in candidates}
    if len(unique) <= size:
        return sorted(unique.values(), key=lambda c: _rank(c, source_key))
    feasible = sorted((c for c in unique.values() if c.evaluation.feasible),
                      key=lambda c: _rank(c, source_key))
    infeasible = sorted((c for c in unique.values() if not c.evaluation.feasible),
                        key=lambda c: _rank(c, source_key))
    reserve = min(len(infeasible), max(1, size // 4), size - 1) if feasible else size
    target_valid = size - reserve if feasible else 0
    selected, used = [], set()

    def add_from(group, limit):
        if not limit:
            return
        niches, chosen = set(), []
        for candidate in group[:max(1, limit // 4)]:
            identity = _key(candidate.frames)
            if identity not in used:
                chosen.append(candidate)
                used.add(identity)
                niches.add(candidate.evaluation.niche_key)
        for candidate in group:
            if len(chosen) >= limit:
                break
            identity = _key(candidate.frames)
            if identity not in used and candidate.evaluation.niche_key not in niches:
                chosen.append(candidate)
                used.add(identity)
                niches.add(candidate.evaluation.niche_key)
        for candidate in group:
            if len(chosen) >= limit:
                break
            identity = _key(candidate.frames)
            if identity not in used:
                chosen.append(candidate)
                used.add(identity)
        selected.extend(chosen)

    add_from(feasible, target_valid)
    add_from(infeasible, reserve)
    for candidate in sorted(unique.values(), key=lambda c: _rank(c, source_key)):
        if len(selected) >= size:
            break
        identity = _key(candidate.frames)
        if identity not in used:
            selected.append(candidate)
            used.add(identity)
    return sorted(selected, key=lambda c: _rank(c, source_key))


def _evaluation(feasible, score, niche):
    return EndpointEvaluation(
        feasible=feasible, score=score, frame=30, x=80, y=60,
        vx=0, vy=0, missing_interactions=frozenset(),
        violated_interactions=frozenset(), dead=False,
        progress_key=(abs(score), niche), state_key=b"", niche_key=(niche,),
    )


def _candidates(n=450, frames=360):
    rng = random.Random(207)
    source = (InputFrame(),) * frames
    candidates = [AutoEndpointCandidate(source, _evaluation(True, 0.0, 0))]
    for index in range(n):
        edited = list(source)
        for position in rng.sample(range(frames), 7):
            bit = rng.randint(1, 7)
            edited[position] = InputFrame(bool(bit & 1), bool(bit & 2), bool(bit & 4))
        candidates.append(AutoEndpointCandidate(
            tuple(edited), _evaluation(index % 4 != 0, rng.randrange(-100, 200) / 5,
                                       index % 13),
        ))
    return candidates


def test_cached_beam_exactly_matches_original_selection_after_every_insertion():
    candidates = _candidates(260, frames=200)
    original_key = _key(candidates[0].frames)
    for width in (1, 2, 8, 16, 64):
        beam = _EndpointBeam(candidates[0], width, original_key)
        expected = [candidates[0]]
        for candidate in candidates[1:]:
            beam.add(candidate, _key(candidate.frames))
            expected = _reference_beam((*expected, candidate), width, original_key)
            assert [item.identity for item in beam.entries] == [
                _key(item.frames) for item in expected
            ]


def test_cached_beam_handles_duplicate_inputs_without_wasting_capacity():
    candidates = _candidates(12, frames=60)
    source_key = _key(candidates[0].frames)
    beam = _EndpointBeam(candidates[0], 4, source_key)
    beam.add(candidates[1], _key(candidates[1].frames))
    beam.add(candidates[1], _key(candidates[1].frames))
    assert len(beam.entries) == 2
    for candidate in candidates[2:]:
        beam.add(candidate, _key(candidate.frames))
    assert len(beam.entries) == 4
    assert len({entry.identity for entry in beam.entries}) == 4


def test_repair_and_completion_ranking_remain_part_of_cached_order():
    candidates = _candidates(28, frames=75)
    completed = replace(candidates[5], complete=True)
    cases = [candidates[0], completed, *candidates[1:5], *candidates[6:]]
    key = _key(cases[0].frames)
    beam = _EndpointBeam(cases[0], 8, key)
    expected = [cases[0]]
    for candidate in cases[1:]:
        beam.add(candidate, _key(candidate.frames))
        expected = _reference_beam((*expected, candidate), 8, key)
        assert [entry.identity for entry in beam.entries] == [
            _key(entry.frames) for entry in expected
        ]


def test_search_proposals_and_best_are_identical_with_old_beam(monkeypatch):
    """Same random seed and proposal budget should yield the same actual TAS."""
    import nv14_auto_endpoint as endpoint
    from nv14_endpoint import EndpointGoal
    from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, parse_level_string

    level = parse_level_string("0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + "|5^60,60")
    source = (InputFrame(),) * 52
    goal = EndpointGoal(target_frame=35, objective="max-x")
    original_beam_class = endpoint._EndpointBeam

    class OldBeam:
        def __init__(self, first, width, source_key):
            self.width = width
            self.source_key = source_key
            self.candidates = [first]
            self.entries = [endpoint._ranked_candidate(first, source_key)]

        def add(self, candidate, identity):
            self.candidates = _reference_beam(
                (*self.candidates, candidate), self.width, self.source_key,
            )
            self.entries = [endpoint._ranked_candidate(item, self.source_key)
                            for item in self.candidates]

    for seed in (3, 19, 71):
        cfg = endpoint.AutoEndpointConfig(
            iterations=100, beam_width=12, seed=seed, range_end=35,
            repair_steps=6,
        )
        fresh = endpoint.optimise_auto_endpoint(level, source, goal, cfg)
        with monkeypatch.context() as patch:
            patch.setattr(endpoint, "_EndpointBeam", OldBeam)
            legacy = endpoint.optimise_auto_endpoint(level, source, goal, cfg)
        assert fresh[2] == legacy[2]
        assert _key(fresh[0].frames) == _key(legacy[0].frames)
        assert (None if fresh[1] is None else _key(fresh[1].frames)) == (
            None if legacy[1] is None else _key(legacy[1].frames)
        )
    assert endpoint._EndpointBeam is original_beam_class

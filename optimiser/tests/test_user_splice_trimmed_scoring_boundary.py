"""Named-splice scoring must not treat a canonical completed movie as a search buffer."""
from __future__ import annotations

import random

import pytest

import nv14_user_splice as us
import nv14_splice_backend as backend
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_engine import InputFrame
from nv14_random_splice import RandomSpliceConfig
from tests.test_user_splice_completed_checkpoint_propagation import _completions


def _end_goal(target_frame=40):
    return EndpointGoal(target_frame, 'earliest-arrival',
                        target_region=(100, 1000, 120, 180))


@pytest.mark.parametrize(('target_frame', 'movie_length'), ((40, 29), (776, 776)))
def test_splice_endpoint_scores_short_completed_checkpoint_without_extending_it(
        target_frame, movie_length):
    level, fast, _slow = _completions()
    movie = fast + (InputFrame(),) * (movie_length - len(fast))
    goal = _end_goal(target_frame)
    with pytest.raises(ValueError, match=(
            f'target frame {target_frame} is outside a {movie_length}-frame replay')):
        EndpointEvaluator(level, goal).evaluate(movie)
    scorer = us._SpliceScoringEndpoint(EndpointEvaluator(level, goal), goal.target_frame)
    result = scorer.evaluate(movie)
    expected = EndpointEvaluator(level, goal).evaluate(
        us._materialise_splice_tail(movie, goal.target_frame))
    assert result == expected
    assert len(movie) == movie_length  # No extra tick in the saved movie.


def test_hybrid_uses_full_workspace_after_live_short_completed_best(monkeypatch):
    """Reproduce: stage best saved, then 40 is outside a 40-frame replay.

    An earlier finish returned by a backend is a canonical replay, not a
    search seed. Another backend must receive the full 41+ input workspace.
    """
    level, fast, slow = _completions()
    goal = _end_goal()
    source = slow  # Canonical 34-frame completion; search pads through frame 40.
    seen = []
    saves = []

    def fake_local_search(_level, frames, _goal, *, config, best_callback=None, **_kwargs):
        seen.append((config.search_backend, tuple(frames)))
        if config.search_backend == 'endpoint-auto':
            if best_callback:
                best_callback(fast, 24)  # Live, shortened canonical finish.
            return ((fast, 24),), 1
        assert len(frames) == 41
        assert frames[29:41] == (InputFrame(),) * 12
        return (), 0

    def splice_search(_level, branch, stage, config, rng, **kwargs):
        return backend._search_stage(
            _level, branch, stage, config, rng,
            local_search=fake_local_search, evaluator_factory=EndpointEvaluator,
            **kwargs)

    monkeypatch.setattr(us, '_search_stage', splice_search)
    stage = us.UserSpliceStage('end', goal, 0, 40)
    result = us.optimise_user_splices(
        level, source, (stage,),
        RandomSpliceConfig(search_backend='hybrid', iterations=1,
                           hybrid_auto_iterations=1, hybrid_local_rounds=1,
                           hybrid_cycles=1, rounds=1, workers=1),
        completion_policy='complete',
        stage_best_callback=lambda name, frames: saves.append((name, frames)),
    )
    assert result.frames == fast
    assert ('end', fast) in saves
    assert [kind for kind, _ in seen] == ['endpoint-auto', 'local']


def test_hybrid_preserves_boundary_when_truncated_movie_has_exact_target_length():
    level, fast, slow = _completions()
    goal = _end_goal()
    source = us._materialise_splice_tail(slow, 40)
    shortened = fast + (InputFrame(),) * (40 - len(fast))
    assert len(shortened) == goal.target_frame
    seen = []

    def fake_search(_level, frames, _goal, *, config, **_kwargs):
        seen.append((config.search_backend, len(frames)))
        return (((shortened, 24),), 0) if config.search_backend == 'endpoint-auto' else ((), 0)

    found, _used, _calls = backend._search_stage_hybrid(
        level, source,
        us.UserSpliceStage('end', goal, 0, 40),
        RandomSpliceConfig(search_backend='hybrid', iterations=1,
                           hybrid_auto_iterations=1, hybrid_local_rounds=1,
                           hybrid_cycles=1), random.Random(2),
        local_search=fake_search)
    assert seen == [('endpoint-auto', 41), ('local', 41)]
    assert found and all(len(frames) == 41 for frames, _ in found)


def test_hybrid_short_donor_keeps_noneditable_suffix_after_stage_end():
    level, fast, slow = _completions()
    original = us._materialise_splice_tail(slow, 40)
    original = original[:36] + (InputFrame(left=True),) * 5
    seen = []

    def fake_search(_level, frames, _goal, *, config, **_kwargs):
        seen.append((config.search_backend, tuple(frames)))
        return (((fast, 24),), 0) if config.search_backend == 'endpoint-auto' else ((), 0)

    backend._search_stage_hybrid(
        level, original,
        us.UserSpliceStage('end', _end_goal(), 0, 35),
        RandomSpliceConfig(search_backend='hybrid', iterations=1,
                           hybrid_auto_iterations=1, hybrid_local_rounds=1,
                           hybrid_cycles=1), random.Random(2),
        local_search=fake_search)
    assert [name for name, _ in seen] == ['endpoint-auto', 'local']
    resumed = seen[1][1]
    assert len(resumed) == len(original)
    assert resumed[:len(fast)] == fast
    assert resumed[len(fast):36] == (InputFrame(),) * (36 - len(fast))
    assert resumed[36:] == original[36:]

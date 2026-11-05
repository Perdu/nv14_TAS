"""Physically identical searches should not consume another backend budget."""
from nv14_engine import InputFrame
from nv14_user_splice import _unique_search_seeds
from tests.test_random_splice import _baseline


def test_same_replay_is_not_searched_twice():
    level, frames, _ = _baseline()
    assert _unique_search_seeds(level, [frames, frames], 10) == [frames]


def test_different_future_input_is_still_a_distinct_seed():
    level, frames, _ = _baseline()
    altered = frames[:10] + (InputFrame(left=True),) + frames[11:]
    assert _unique_search_seeds(level, [frames, altered], 10) == [frames, altered]


def test_exact_equivalent_state_deduplicates_different_prefixes(monkeypatch):
    import nv14_replay
    level, frames, _ = _baseline()
    altered = (InputFrame(left=True),) + frames[1:]
    class DummyState:
        def state_key(self):
            return ('same player, object, velocity, mask and contact state',)
    monkeypatch.setattr(nv14_replay, 'simulate_through_frame',
                        lambda *_args: DummyState())
    assert _unique_search_seeds(level, [frames, altered], 10) == [frames]

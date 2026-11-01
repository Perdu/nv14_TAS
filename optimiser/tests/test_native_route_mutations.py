"""Native route operators must agree exactly with their Python reference."""
import random
from time import perf_counter

import pytest

import nv14_route_mutations as routes
from nv14_engine import InputFrame
from nv14_native import require_native
from tests.test_auto_route_mutations import _sequence
from tests.test_random_splice import _baseline


def _reference(monkeypatch, name, parent, *, rng, start, end, donor=None, level=None):
    with monkeypatch.context() as scoped:
        scoped.setattr(routes, "_native_route_module", lambda: None)
        return routes.propose(name, parent, rng=rng, start=start, end=end,
                              donor=donor, level=level)


@pytest.mark.parametrize("name", routes.MEDIUM)
def test_native_matches_python_for_randomized_replays(monkeypatch, name):
    native = require_native()
    assert hasattr(native, "route_structural_propose")
    base = _sequence()
    for variation in range(7):
        shuffle = random.Random(variation + 50)
        replay = list(base)
        for _ in range(16):
            i = shuffle.randrange(8, len(base) - 8)
            replay[i] = InputFrame(shuffle.choice((True, False)),
                                   shuffle.choice((True, False)),
                                   shuffle.choice((True, False)),
                                   shuffle.choice((None, True, False)))
        parent = tuple(replay)
        for seed in range(25):
            left, right = 10, len(parent) - 11
            expected = _reference(monkeypatch, name, parent,
                                  rng=random.Random(seed), start=left, end=right)
            observed = routes.propose(name, parent, rng=random.Random(seed),
                                      start=left, end=right)
            assert observed == expected, (name, variation, seed)
            if observed is not None:
                assert observed[:left] == parent[:left]
                assert observed[right+1:] == parent[right+1:]


def test_native_crossover_matches_python_reference(monkeypatch):
    native = require_native()
    assert hasattr(native, "route_crossover_seam")
    level, frames, _ = _baseline()
    donor = list(frames)
    # A donor with gentle early deviations should have possible safe seams.
    for i in (2, 3, 7, 8, 11):
        donor[i] = InputFrame(right=False, left=True)
    donor = tuple(donor)
    for seed in range(20):
        args = dict(start=0, end=len(frames)-1, donor=donor, level=level)
        actual = routes.propose("state-crossover", frames,
                                rng=random.Random(seed), **args)
        expected = _reference(monkeypatch, "state-crossover", frames,
                              rng=random.Random(seed), **args)
        assert actual == expected, seed


def test_native_crossover_seams_are_correctly_tick_aligned():
    from nv14_search import NativeSearchSession
    level, frames, _ = _baseline()
    from nv14_replay import simulate_through_frame
    session = NativeSearchSession(level)
    trace = session.evaluate_replay(frames)
    for seam in (1, 3, 5, 10):
        position = trace.point(seam - 1)
        python_state = simulate_through_frame(level, frames, seam - 1).player
        assert position[1] == pytest.approx(python_state.pos.x, abs=1e-8)
        assert position[2] == pytest.approx(python_state.pos.y, abs=1e-8)
        assert position[3] == pytest.approx(python_state.pos.x - python_state.oldpos.x,
                                            abs=1e-8)


def test_native_crossover_skips_python_physics(monkeypatch):
    level, parent, _ = _baseline()
    donor = list(parent)
    donor[7] = InputFrame(left=True)

    def forbidden(*args, **kwargs):
        raise AssertionError('Python step-by-step physics used in native crossover')

    monkeypatch.setattr(routes, 'simulate_through_frame', forbidden)
    # It is acceptable for the donor to have no compatible seam: this test
    # checks that a native kernel, not Python physics, makes that decision.
    routes.propose('state-crossover', parent, rng=random.Random(4),
                   start=0, end=len(parent) - 1,
                   donor=tuple(donor), level=level)

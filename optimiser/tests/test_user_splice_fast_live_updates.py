"""Multi-splicer should not make search workers wait on persistent checkpoint IO."""

from types import SimpleNamespace

from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_replay import decode_complex_replay, editable_frames, encode_complex_replay
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_parallel_endpoint_worker_coalesces_updates_but_returns_latest(monkeypatch):
    """Throttling doesn't change the search budget or the worker's final result."""
    import nv14_auto_endpoint as auto
    import nv14_engine

    level, source, _ = _baseline()
    goal = EndpointGoal(10, 'min-x')
    emitted = []
    latest = SimpleNamespace(frames=source, evaluation=SimpleNamespace(feasible=True))
    times = iter([100.0, *(100.0 + 0.1 * i for i in range(1, 12))])
    monkeypatch.setattr(auto.time, 'monotonic', lambda: next(times))
    monkeypatch.setattr(nv14_engine, 'parse_level_string', lambda *a, **k: level)

    def fake_auto(*args, best_callback, **kwargs):
        for _ in range(10):
            best_callback(latest)
        return (None, latest, 10)

    monkeypatch.setattr(auto, 'optimise_auto_endpoint', fake_auto)
    updates = SimpleNamespace(put=emitted.append)
    payload = (level.source_level_string, level.simulate_enemies, source, goal,
               auto.AutoEndpointConfig(iterations=10), updates, 0,
               0, (), None, 30.0)
    result = auto._endpoint_worker(payload)
    assert result == (None, latest, 10)
    assert emitted == [latest]  # Only the first live notification crosses IPC.


def test_archive_is_written_once_at_stage_end_with_many_updates(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    goal = EndpointGoal(10, 'min-x')
    routes = tuple(
        tuple(InputFrame(left=(i % 2 == 0), right=(i % 2 == 1))
              for _ in range(i)) + source[i:]
        for i in range(1, 40)
    )
    calls = []
    def fake_stage(_level, _branch, _stage, _config, _rng, **kwargs):
        # Simulate an Auto phase delivering many candidates; its final frontier
        # is still processed in full even when live updates were throttled.
        for candidate in routes:
            kwargs['candidate_callback'](candidate, 10)
        return tuple((candidate, 10) for candidate in routes), 39, 1

    monkeypatch.setattr(us, '_search_stage', fake_stage)
    out = optimise_user_splices(
        level, source, [UserSpliceStage('end', goal, 0, 10)],
        RandomSpliceConfig(iterations=40, rounds=1, workers=15,
                           frontier=3, save_frontier=64),
        completion_policy='checkpoint',
        frontier_callback=lambda name, frames: calls.append((name, frames)))
    assert out.evaluations == 39
    assert len(calls) == 1
    assert calls[0][0] == 'end'
    assert len(calls[0][1]) > 3


def test_direct_editable_normalization_matches_old_round_trip():
    frames = [InputFrame(left=bool(i % 2), right=bool(i % 3),
                         jump=bool(i % 4), jump_trigger=bool(i % 5))
              for i in range(70)]
    reference = tuple(editable_frames(decode_complex_replay(
        encode_complex_replay(frames)).frames))
    assert tuple(editable_frames(frames)) == reference


def test_multiworker_named_stage_requests_coalesced_worker_reports(monkeypatch):
    import random
    import nv14_user_splice as us
    level, source, _ = _baseline()
    stage = UserSpliceStage('end', EndpointGoal(10, 'min-x'), 0, 10)
    received = []
    def fake_search(_level, _branch, _goal, **kwargs):
        received.append(kwargs['live_update_interval'])
        return (), 0
    monkeypatch.setattr(us, '_local_search', fake_search)
    us._search_stage(level, source, stage, RandomSpliceConfig(
        workers=15, search_backend='endpoint-auto', rounds=1), random.Random(1))
    assert received == [30.0]
    received.clear()
    us._search_stage(level, source, stage, RandomSpliceConfig(
        workers=1, search_backend='endpoint-auto', rounds=1), random.Random(1))
    assert received == [0.75]

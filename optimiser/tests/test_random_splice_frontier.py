"""Regressions for the exact latest-upload random-splice multi-stage fixes."""
from dataclasses import replace
import random
from types import SimpleNamespace

import pytest

import nv14_random_splice as splice
from nv14_auto import evaluate_replay_with_sentinel
from nv14_cli import parse_arguments
from nv14_engine import InputFrame
from nv14_population import PopulationCandidate
from tests.test_auto import _running_exit_level


def completed_slow_run():
    level = _running_exit_level()
    source = tuple([InputFrame(right=True)] * 10 + [InputFrame()] * 6
                   + [InputFrame(right=True)] * 20)
    original = evaluate_replay_with_sentinel(level, source)
    assert original.valid and original.finish_tick == len(source)
    return level, source, original


def test_compatible_seams_not_replaced_by_fallback(monkeypatch):
    level, source, evaluation = completed_slow_run()
    anchor = splice.Waypoint(20, evaluation.point(20).x, evaluation.point(20).y)
    monkeypatch.setattr(splice, "choose_waypoints", lambda *_args: (anchor,))
    # One feasible local candidate whose only useful splice is ahead of the
    # fallback coordinate (20 -> 22). The old code overwrote it unconditionally.
    monkeypatch.setattr(splice, "_candidate_seams", lambda *_args: ((12, 22),))
    def local_search(level, frames, goal, **kwargs):
        if goal.objective == "earliest-arrival":
            return ((source, 12),), 1
        return (), 0
    monkeypatch.setattr(splice, "_local_search", local_search)
    joins = []
    def verify(level, frames, reference, original_length):
        joins.append(tuple(frames))
        return None
    monkeypatch.setattr(splice, "_validated_improvement", verify)
    splice.optimise_random_splices(level, source,
                                   splice.RandomSpliceConfig(rounds=1, repair_anchors=0))
    assert joins
    assert joins[0] == tuple(source[:13]) + tuple(source[23:])


def test_local_search_exposes_near_miss_frontier_only_when_requested(monkeypatch):
    level, source, reference = completed_slow_run()
    goal = splice._goal(level, source, splice.Waypoint(15, 1.0, 1.0),
                        splice.RandomSpliceConfig(), deadline=15, start=0)
    feasible = SimpleNamespace(frames=source, evaluation=SimpleNamespace(feasible=True, frame=10))
    near = SimpleNamespace(frames=tuple([InputFrame()] + list(source[1:])),
                           evaluation=SimpleNamespace(feasible=False, frame=15))
    monkeypatch.setattr(splice, 'optimise_local_population', lambda *a, **k: SimpleNamespace(
        candidates=(feasible,), frontier=(near,), interrupted=False, evaluations=9))
    found, total = splice._local_search(level, source, goal, start=0,
                                        iterations=4, rounds=1, seed=7,
                                        config=splice.RandomSpliceConfig(frontier=2))
    assert total == 9 and len(found) == 1
    found, total = splice._local_search(level, source, goal, start=0,
                                        iterations=4, rounds=1, seed=7,
                                        config=splice.RandomSpliceConfig(frontier=2),
                                        include_partial=True)
    assert len(found) == 2 and any(frames == near.frames for frames, frame in found)


def test_progressive_frontier_carries_edits_over_two_waypoints(monkeypatch):
    level, source, reference = completed_slow_run()
    anchors = tuple(splice.Waypoint(t, reference.point(t).x, reference.point(t).y)
                    for t in (13, 26))
    calls = []
    def local_search(level, frames, goal, *, start, include_partial=False, **kwargs):
        calls.append((start, goal.target_frame, include_partial))
        if not include_partial:
            return (), 1  # force old one-seam path to fail
        result = list(frames)
        if goal.objective == 'earliest-arrival' and start == 0:
            result[10:13] = [InputFrame(right=True)] * 3
        elif goal.objective == 'earliest-arrival' and start == 14:
            result[13:16] = [InputFrame(right=True)] * 3
        # This candidate has not completed after the first segment, but the
        # second mutation makes the early exit possible without suffix matching.
        return ((tuple(result), goal.target_frame),), 1
    monkeypatch.setattr(splice, '_local_search', local_search)
    logs = []
    result, attempts, evals, counters = splice._progressive_frontier(
        level, source, reference, anchors,
        splice.RandomSpliceConfig(frontier=3, rounds=1), random.Random(1), logs.append)
    assert result is not None and len(result) <= 30 < len(source)
    verified = evaluate_replay_with_sentinel(level, result)
    assert verified.valid and verified.finish_tick == len(result)
    assert (0, 13, True) in calls and (14, 26, True) in calls
    assert any(k[0] == 0 and k[2] and k[1] == len(source) for k in calls)
    assert attempts >= 3 and evals >= 3
    assert counters['retained_branches'] > 0
    assert any('frontier EXIT' in m for m in logs)


def test_progressive_distance_to_exit_reported_and_ranked(monkeypatch):
    level, source, reference = completed_slow_run()
    anchors = ()
    candidates = []
    # Incomplete candidate that gets closer to exit than no movement.
    candidate = tuple([InputFrame()] * len(source))
    def local_search(level, frames, goal, **kwargs):
        return ((candidate+(InputFrame(),), goal.target_frame),), 4
    monkeypatch.setattr(splice, '_local_search', local_search)
    messages = []
    result, attempts, evaluated, counts = splice._progressive_frontier(
        level, source, reference, anchors,
        splice.RandomSpliceConfig(frontier=2, rounds=1), random.Random(1), messages.append)
    assert result is None
    assert counts['exit_near_misses'] >= 1
    assert any('edge gap' in msg and 'frontier EXIT' in msg for msg in messages)


def test_cli_frontier_toml_and_disable(tmp_path):
    cfg = tmp_path/'multi.toml'
    cfg.write_text('[auto]\nobjective="speedrun"\nrandom-splice=true\nsplice-frontier=4\n')
    args = parse_arguments(['auto', 'source.txt', '--config', str(cfg)])
    assert args.auto_splice_frontier == 4
    args = parse_arguments(['auto', 'source.txt', '--config', str(cfg),
                            '--auto-splice-frontier', '0'])
    assert args.auto_splice_frontier == 0


@pytest.mark.parametrize('invalid', [-1, 1.5, True])
def test_frontier_validation(invalid):
    with pytest.raises(ValueError, match='frontier'):
        splice.RandomSpliceConfig(frontier=invalid)


def test_exit_window_overlaps_last_checkpoint_and_saves_mid_segment_frames(monkeypatch):
    """Reproduce final waypoint only 3 frames before the door (trace 46-0).

    A narrow post-anchor search cannot edit a six-frame idle pulse in the
    middle of the completed route. An overlapping final exit search can.
    """
    level, source, reference = completed_slow_run()
    late = splice.Waypoint(33, reference.point(33).x, reference.point(33).y)
    monkeypatch.setattr(splice, "choose_waypoints", lambda *_: (late,))
    actual = splice._local_search
    starts = []

    def search(level, frames, goal, *, start, **kwargs):
        if goal.objective == 'earliest-arrival':
            return (), 0  # isolate the final exit search
        starts.append(start)
        return actual(level, frames, goal, start=start, **kwargs)

    monkeypatch.setattr(splice, '_local_search', search)
    without = splice.optimise_random_splices(
        level, source, splice.RandomSpliceConfig(
            points=1, rounds=1, exit_lookback=2,
            iterations=100, seed=2, radius=6, lookback=16),
    )
    assert starts == [34]
    assert len(without.frames) == len(source)
    starts.clear()
    with_overlap = splice.optimise_random_splices(
        level, source, splice.RandomSpliceConfig(
            points=1, rounds=1, exit_lookback=96,
            iterations=100, seed=2, radius=6, lookback=16),
    )
    assert starts == [0]
    assert len(with_overlap.frames) < len(source)
    checked = evaluate_replay_with_sentinel(level, with_overlap.frames)
    assert checked.valid and checked.finish_tick == len(with_overlap.frames)
    assert splice._control_preserved(reference, checked)


def test_exit_horizon_cli_and_toml(tmp_path):
    from nv14_cli import parse_arguments
    config = tmp_path / 'random.toml'
    config.write_text('[auto]\nobjective="speedrun"\nrandom-splice=true\n'
                      'splice-exit-lookback=120\n', encoding='utf-8')
    args = parse_arguments(['auto','source.txt','--config',str(config)])
    assert args.auto_splice_exit_lookback == 120
    assert parse_arguments(['auto','source.txt','--config',str(config),
                            '--auto-splice-exit-lookback','150']).auto_splice_exit_lookback == 150
    with pytest.raises(ValueError, match='exit_lookback'):
        splice.RandomSpliceConfig(exit_lookback=0)

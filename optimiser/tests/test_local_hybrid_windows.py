"""Local sliding-window integration of the opt-in hybrid native repair search."""
from __future__ import annotations

import pytest

import nv14_local
from nv14_cli import LocalConfig
from nv14_engine import InputFrame, parse_level_string
from nv14_local import optimise_local_windows
from nv14_objectives import evaluate, objective_function
from nv14_search import NativeSearchSession


@pytest.fixture
def simple_level():
    return parse_level_string('0' * (31 * 23) + '|5^100,100')


def test_local_config_rejects_invalid_hybrid_settings() -> None:
    for kwargs, match in (
        ({'local_beam_width': -1}, 'local-beam-width'),
        ({'local_beam_width': 4097}, 'local-beam-width'),
        ({'local_search_cache_entries': 65}, 'local-search-cache-entries'),
        ({'local_search_ticks': -1}, 'local-search-ticks'),
        ({'search': 'population', 'local_beam_width': 8}, 'require --search windows'),
        ({'search': 'population', 'local_adaptive_windows': True}, 'require --search windows'),
        ({'search': 'population', 'local_search_ticks': 500}, 'require --search windows'),
        ({'search': 'population', 'local_search_cache_entries': 3}, 'require --search windows'),
    ):
        with pytest.raises(ValueError, match=match):
            LocalConfig(**kwargs)


def test_local_hybrid_horizons() -> None:
    assert nv14_local._local_hybrid_horizons(7, True) == (2, 4, 7)
    assert nv14_local._local_hybrid_horizons(4, True) == (2, 4)
    assert nv14_local._local_hybrid_horizons(1, True) == (1,)
    assert nv14_local._local_hybrid_horizons(7, False) == (7,)


@pytest.mark.parametrize('inputs', ('all', 'direction'))
def test_hybrid_local_replay_is_verified_and_range_safe(simple_level, inputs):
    baseline_frames = [InputFrame() for _ in range(9)]
    baseline = evaluate(simple_level, baseline_frames, 8, objective_function('max-x'))
    candidate, result = optimise_local_windows(
        simple_level, baseline_frames,
        target_frame=8, range_start=2, range_end=5,
        objective_name='max-x', window_size=4, passes=1,
        local_inputs=inputs, physics_prune=inputs == 'direction',
        local_beam_width=16, local_search_cache_entries=4,
        local_adaptive_windows=True, local_search_ticks=2000,
        progress=None, workers=1, python_resimulate=True,
    )
    assert result.score > baseline.score
    assert result.score == evaluate(simple_level, candidate, 8, objective_function('max-x')).score
    assert all(candidate[tick] == baseline_frames[tick] for tick in (0, 1, 6, 7, 8))


def test_adaptive_horizons_share_a_native_tick_budget(monkeypatch, simple_level):
    records = []
    caches = []
    original_type = NativeSearchSession

    class RecordingSession:
        def __init__(self, level):
            self.inner = original_type(level)

        def configure_result_cache(self, capacity):
            caches.append(capacity)
            self.inner.configure_result_cache(capacity)

        def search(self, frames, spec):
            result = self.inner.search(frames, spec)
            records.append((spec, result))
            return result

    monkeypatch.setattr(nv14_local, 'NativeSearchSession', RecordingSession)
    frames = [InputFrame() for _ in range(11)]
    optimise_local_windows(
        simple_level, frames, target_frame=10,
        range_start=2, range_end=7, objective_name='max-x',
        window_size=6, passes=1, local_beam_width=16,
        local_search_cache_entries=3, local_adaptive_windows=True,
        local_search_ticks=600, progress=None, workers=1,
    )
    assert caches == [3]
    assert [len(spec.mutable_frames) for spec, _ in records] == [2, 4, 6]
    assert [spec.mutable_frames for spec, _ in records] == [(6, 7), (4, 5, 6, 7), (2, 3, 4, 5, 6, 7)]
    assert all(spec.beam_width == 16 and spec.beam_adaptive_inputs for spec, _ in records)
    assert sum(result.stats.simulated_ticks for _, result in records) <= 600
    assert all(spec.max_simulated_ticks > 0 for spec, _ in records)


def test_original_local_search_keeps_dfs_defaults(monkeypatch, simple_level):
    specs = []
    original_type = NativeSearchSession

    class RecordingSession:
        def __init__(self, level):
            self.inner = original_type(level)

        def search(self, frames, spec):
            specs.append(spec)
            return self.inner.search(frames, spec)

    monkeypatch.setattr(nv14_local, 'NativeSearchSession', RecordingSession)
    optimise_local_windows(
        simple_level, [InputFrame() for _ in range(4)],
        target_frame=3, range_start=1, range_end=2,
        objective_name='max-x', window_size=2, passes=1,
        progress=None, workers=1,
    )
    assert len(specs) == 1
    assert specs[0].beam_width == 0
    assert not specs[0].beam_adaptive_inputs
    assert specs[0].max_simulated_ticks == 0

"""Single named searches display their ordinary backend round/frame progress."""
from __future__ import annotations

import random

import pytest

import nv14_user_splice as us
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage
from tests.test_random_splice import _baseline


@pytest.mark.parametrize('backend', ['endpoint-auto', 'local', 'hybrid'])
def test_selected_splice_preserves_native_backend_progress(monkeypatch, backend):
    level, source, _ = _baseline()
    stage = UserSpliceStage('442', EndpointGoal(12, 'max-x'), 0, 12)
    seen = []

    def backend_runner(_level, frames, _goal, *, progress=None, config=None, **kwargs):
        assert progress is not None
        if config.search_backend == 'endpoint-auto':
            progress('baseline: source feasible; frame 12; position (1, 2)')
            progress('round 1/1: best frame 11, score 12.5')
        else:
            progress('[local:population] round 1; best 12.5 at frame 11')
        return (), 5

    monkeypatch.setattr(us, '_local_search', backend_runner)
    config = RandomSpliceConfig(search_backend=backend, workers=1,
                                iterations=2, rounds=1, splice_rounds=1,
                                hybrid_cycles=1, hybrid_local_rounds=1,
                                beam=4)
    us.optimise_user_splices(level, source, [stage], config,
                            completion_policy='checkpoint',
                            show_backend_progress=True, progress=seen.append)
    if backend != 'local':
        assert any("[auto:parallel] '442': round 1/1: best frame 11" in msg
                   for msg in seen), seen
    if backend != 'endpoint-auto':
        assert any('[local:population] round 1; best 12.5 at frame 11' in msg
                   for msg in seen), seen
    if backend != 'local':
        assert any("[auto:baseline] '442': source feasible" in msg
                   for msg in seen), seen


def test_full_multi_route_does_not_emit_backend_rounds(monkeypatch):
    level, source, _ = _baseline()
    stage = UserSpliceStage('442', EndpointGoal(12, 'max-x'), 0, 12)
    msgs = []

    def backend_runner(_level, frames, _goal, *, progress=None, **kwargs):
        assert progress is None
        return (), 5

    monkeypatch.setattr(us, '_local_search', backend_runner)
    us.optimise_user_splices(level, source, [stage],
                            RandomSpliceConfig(search_backend='endpoint-auto',
                                               workers=1, iterations=2,
                                               rounds=1, splice_rounds=1),
                            completion_policy='checkpoint', progress=msgs.append)
    assert not any('[auto:parallel]' in msg for msg in msgs)


def test_cli_single_stage_forwards_backend_output_switch(tmp_path, monkeypatch):
    import sys
    from nv14_cli import main
    from tests.test_single_stage_managed_propagation import _native_level_fixture

    source, goals, config = _native_level_fixture(tmp_path)
    flags = []
    original = us.optimise_user_splices

    def capture(level, frames, stages, options, **kwargs):
        flags.append(kwargs['show_backend_progress'])
        return original(level, frames, stages, options, **kwargs)

    monkeypatch.setattr(us, 'optimise_user_splices', capture)
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs: ((), 0, 1))
    args = ['auto', str(source), '--splice-config', str(config),
            '--auto-splice-directory', str(goals), '--auto-splice-search', 'hybrid',
            '--no-propagation', '--auto-runs', '1', '--workers', '1',
            '--output', str(tmp_path / 'best.txt')]
    monkeypatch.setattr(sys, 'argv', ['optimize_replay.py', *args, '--single-splice', '159'])
    main()
    assert flags == [True]
    flags.clear()
    monkeypatch.setattr(sys, 'argv', ['optimize_replay.py', *args])
    main()
    assert flags == [False]

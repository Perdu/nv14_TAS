"""Direct stage-graft verification is parallel, but checkpoint commits remain ordered."""
from __future__ import annotations

from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline
from tests.test_user_splice_manual_input_merge import _finished_slow_run


def test_parallel_merge_matches_serial_checkpoint_and_completion_ranking():
    level, source, _ = _baseline()
    alternate = _finished_slow_run(level)
    changed = source[:5] + (InputFrame(left=True),) + source[6:]
    stages = [UserSpliceStage(str(target), EndpointGoal(target, 'min-x'),
                              max(0, target - 6), target)
              for target in (8, 14, 20)]
    saved = {name: [source, alternate] for name in ('8', '14', '20')}

    def merge(workers):
        messages, stage_updates, best_updates = [], [], []
        result = optimise_user_splices(
            level, changed, stages,
            RandomSpliceConfig(iterations=1, workers=1, frontier=2),
            merge_workers=workers, merge_stage_bests=True, merge_only=True,
            saved_final_frames=alternate, saved_stage_candidates=saved,
            completion_policy='checkpoint', progress=messages.append,
            stage_best_callback=lambda name, frames: stage_updates.append((name, frames)),
            best_callback=best_updates.append)
        return result, stage_updates, best_updates, messages

    serial, serial_stages, serial_bests, serial_log = merge(1)
    parallel, parallel_stages, parallel_bests, parallel_log = merge(2)
    assert parallel == serial
    assert parallel_stages == serial_stages
    assert parallel_bests == serial_bests
    assert any('2 CPU worker(s)' in message for message in parallel_log)
    assert any('1 CPU worker(s)' in message for message in serial_log)
    assert any('done:' in message and 'attempted' in message for message in parallel_log)


def test_parallel_merge_worker_override_rejects_invalid_values():
    import pytest
    level, source, _ = _baseline()
    stages = [UserSpliceStage('8', EndpointGoal(8, 'min-x'), 0, 8)]
    for value in (0, -2, True, 1.2):
        with pytest.raises(ValueError, match='merge_workers'):
            optimise_user_splices(level, source, stages,
                                  RandomSpliceConfig(workers=1),
                                  merge_workers=value)


def test_cli_auto_workers_parallelises_only_merge_not_proposal_budget(tmp_path, monkeypatch):
    import sys
    import nv14_cli
    import nv14_user_splice as us
    from tests.test_user_splice_list_summary import _setup

    _level, _source, _saved, _output, _packed, argv = _setup(tmp_path)
    observed = []

    def capture(_level, source_frames, _stages, config, **kwargs):
        observed.append((config.workers, kwargs['merge_workers']))
        return us.UserSpliceResult(tuple(source_frames), 0, 0, 0)

    monkeypatch.setattr(us, 'optimise_user_splices', capture)
    monkeypatch.setattr(nv14_cli, '_automatic_jump_worker_count', lambda: 3)
    monkeypatch.setattr(sys, 'argv', [*argv, '--splice-merge-only', '--workers', 'auto'])
    nv14_cli.main()
    assert observed and observed[0] == (1, 3)

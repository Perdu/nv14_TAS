"""Patch 79: manual input seed is opt-out while input remains reporting baseline."""
from __future__ import annotations

import pytest

import nv14_user_splice as us
from nv14_cli import parse_arguments
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_cli_and_toml_flag(tmp_path):
    p = tmp_path / 'cfg.toml'
    p.write_text('[multi-splicer]\nfiles=["522"]\nuse-current-run=false\n')
    def args(*flags):
        return parse_arguments(['auto', 'a.ltm', '--splice-config', str(p), *flags])
    assert args().auto_splice_use_current_run is False
    assert args('--use-current-run').use_current_run is True
    assert args('--no-use-current-run').use_current_run is False
    p.write_text('[multi-splicer]\nfiles=["522"]\nuse-current-run="false"\n')
    with pytest.raises(SystemExit, match='must be a boolean'):
        args()


def test_disabled_current_seed_uses_saved_stage_frontiers(monkeypatch):
    level, source, _ = _baseline()
    saved = (InputFrame(left=True),) + source[1:]
    stages = [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
              for name in ('old', '522')]
    calls = []
    monkeypatch.setattr(us, '_search_stage', lambda _lvl, branch, *_a, **_kw:
                        (calls.append(tuple(branch)) or (), 0, 1))
    optimise_user_splices(level, source, stages,
                          RandomSpliceConfig(rounds=1, iterations=2),
                          start_at='522', completion_policy='checkpoint',
                          use_current_run=False,
                          saved_stage_frontiers={'old': [saved]})
    assert calls == [saved]
    assert source not in calls


def test_disabled_current_seed_requires_alternate(monkeypatch):
    level, source, _ = _baseline()
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_kw:
                        pytest.fail('must not run input search'))
    with pytest.raises(ValueError, match='no search seeds'):
        optimise_user_splices(level, source,
                              [UserSpliceStage('522', EndpointGoal(10, 'min-x'), 0, 10)],
                              RandomSpliceConfig(rounds=1, iterations=2),
                              completion_policy='checkpoint', use_current_run=False)

"""Patch 80: per-goal history depth does not truncate later-stage sources."""
from __future__ import annotations

import pytest

import nv14_cli as cli
import nv14_user_splice as us
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage
from tests.test_random_splice import _baseline


def test_stage_local_lookback_and_explicit_cli_override(tmp_path):
    root = tmp_path / 'stages'
    root.mkdir()
    (root / '230.txt').write_text('[local]\nobjective="min-x"\ntarget-frame=10\n'
                                  'range="0:10"\nlookback=4\n')
    config = root / 'multi-splicer.toml'
    config.write_text('[multi-splicer]\nfiles=["230"]\nlookback=2\n')
    level, frames, _ = _baseline()
    args = cli.parse_arguments(['auto', 'level.ltm', '--splice-config', str(config)])
    stages = cli._load_named_splice_stages(level, frames, args, root, args.auto_splice_files)
    assert stages[0].config_overrides['stage_lookback'] == 4
    args = cli.parse_arguments(['auto', 'level.ltm', '--splice-config', str(config),
                                '--splice-stage-lookback', '5'])
    stages = cli._load_named_splice_stages(level, frames, args, root, args.auto_splice_files)
    assert 'stage_lookback' not in stages[0].config_overrides
    (root / '230.txt').write_text('[local]\nobjective="min-x"\ntarget-frame=10\n'
                                  'range="0:10"\nstage-lookback=0\n')
    with pytest.raises(ValueError, match='stage-lookback'):
        cli._load_named_splice_stages(level, frames, args, root, args.auto_splice_files)


def test_stage_history_can_grow_after_shallow_stage(monkeypatch):
    level, source, _ = _baseline()
    stages = [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10,
                              config_overrides={'stage_lookback': depth})
              for name, depth in (('a',1),('b',1),('c',2),('end',3))]
    seen = []
    original = us._stage_sources_history
    def spy(history, frontier):
        seen.append(len(history))
        return original(history, frontier)
    monkeypatch.setattr(us, '_stage_sources_history', spy)
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_kw: ((), 0, 1))
    us.optimise_user_splices(level, source, stages,
                             RandomSpliceConfig(rounds=1, iterations=2,
                                                stage_lookback=1),
                             completion_policy='checkpoint')
    assert seen == [1, 1, 2, 3]

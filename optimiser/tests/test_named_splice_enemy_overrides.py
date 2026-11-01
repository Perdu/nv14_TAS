"""Named splice TOML flags must affect the physics model, not just its goal."""
from argparse import Namespace
from pathlib import Path
import sys

import pytest
from nv14_cli import _named_splice_enemy_simulation
from nv14_engine import parse_level_string, APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS


def opts(tmp_path, names=('639', '686'), **kw):
    return Namespace(mode='auto', auto_splice_mode='user',
                     auto_splice_files=names,
                     auto_splice_directory=tmp_path,
                     auto_splice_config=None, **kw)


def test_true_stage_flag_overrides_global_false(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['optimise.py'])
    (tmp_path/'639.txt').write_text('[local]\nobjective="earliest-arrival"\n')
    (tmp_path/'686.txt').write_text('[local]\nsimulate-enemies=true\n')
    enabled = _named_splice_enemy_simulation(opts(tmp_path), False)
    assert enabled is True
    sample = '0' * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + '|5^60,60!4^132,330,1'
    disabled_level = parse_level_string(sample, simulate_enemies=False)
    enabled_level = parse_level_string(sample, simulate_enemies=enabled)
    assert not any(type(obj).__name__ == 'FloorGuard' for obj in disabled_level.objects)
    assert any(type(obj).__name__ == 'FloorGuard' for obj in enabled_level.objects)


def test_false_stage_flag_does_not_disable_full_run_safety(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['optimise.py'])
    (tmp_path/'639.toml').write_text('[local]\nsimulate-enemies=false\n')
    assert _named_splice_enemy_simulation(opts(tmp_path, names=('639',)), True) is True


def test_no_stage_flag_inherits_global(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['optimise.py'])
    (tmp_path/'639.txt').write_text('[local]\nobjective="min-x"\n')
    assert _named_splice_enemy_simulation(opts(tmp_path, ('639',)), False) is False
    assert _named_splice_enemy_simulation(opts(tmp_path, ('639',)), True) is True


def test_conflicting_explicit_flags_are_allowed_with_strict_final_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['optimise.py'])
    (tmp_path/'639.txt').write_text('[local]\nsimulate-enemies=false\n')
    (tmp_path/'686.txt').write_text('[local]\nsimulate-enemies=true\n')
    assert _named_splice_enemy_simulation(opts(tmp_path), False) is True


def test_cli_explicit_override_has_last_word(tmp_path, monkeypatch):
    (tmp_path/'686.txt').write_text('[local]\nsimulate-enemies=true\n')
    monkeypatch.setattr(sys, 'argv', ['optimise.py', '--no-simulate-enemies'])
    assert _named_splice_enemy_simulation(opts(tmp_path, ('686',)), False) is False


def test_level_splice_config_directory_is_discovered(tmp_path, monkeypatch):
    level_dir = tmp_path/'99-3'
    level_dir.mkdir()
    (level_dir/'686.toml').write_text('[local]\nsimulate-enemies=true\n')
    (level_dir/'multi-splicer.toml').write_text('[multi-splicer]\nfiles=["686"]\n')
    monkeypatch.setattr(sys, 'argv', ['optimise.py', '--splice-config',
                                      str(level_dir/'multi-splicer.toml')])
    args = Namespace(mode='auto', auto_splice_mode='user',
                     auto_splice_files=('686',), auto_splice_directory=None,
                     auto_splice_config=None)
    assert _named_splice_enemy_simulation(args, False) is True

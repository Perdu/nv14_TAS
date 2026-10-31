"""The named multi-splicer can inherit regular Auto settings from a base TOML."""
from pathlib import Path

import pytest

from nv14_cli import parse_arguments


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_base_options_and_splice_specific_section_are_layered(tmp_path):
    base = _write(tmp_path / "base.toml", '''[common]
workers = 8
color = false
[auto]
objective = "speedrun"
iterations = 10000
beam = 64
progressive-refinement = true
refinement-share = 0.25
splice-iterations = 100
runs = 4
''')
    splice_dir = tmp_path / "splices"
    splice_dir.mkdir()
    splice = _write(splice_dir / "multi-splicer.toml", '''[multi-splicer]
files = ["556", "628", "end"]
search = "both"
iterations = 400
rounds = 3
frontier = 4
runs = 5
''')
    args = parse_arguments(['auto', 'level.ltm', '--config', str(base),
                            '--splice-config', str(splice)])
    assert args.workers == 8
    assert args.color is False
    assert args.iterations == 10000
    assert args.beam == 64
    assert args.auto_progressive_refinement is True
    assert args.auto_refinement_share == 0.25
    assert args.auto_splice_files == ('556', '628', 'end')
    assert args.auto_random_splice is True
    assert args.auto_splice_mode == 'user'
    assert args.auto_splice_search == 'both'
    assert args.auto_splice_iterations == 400
    assert args.auto_splice_rounds == 3
    assert args.auto_splice_frontier == 4
    assert args.auto_runs == 5
    assert args.splice_config == splice
    assert args.auto_splice_directory is None


def test_splice_table_overrides_auto_and_cli_overrides_both(tmp_path):
    base = _write(tmp_path / 'base.toml', '''[auto]
beam = 8
splice-iterations = 75
runs = 1
''')
    splice = _write(tmp_path / 'splice.toml', '''[auto]
beam = 12
splice-iterations = 250
[multi-splicer]
files = ["203", "end"]
splice-iterations = 600
beam = 24
runs = 8
''')
    args = parse_arguments(['auto', 'file.ltm', '--splice-config', str(splice),
                            '--config', str(base), '--auto-splice-iterations', '900',
                            '--beam', '128'])
    assert args.beam == 128
    assert args.auto_splice_iterations == 900
    assert args.auto_runs == 8
    assert args.iterations == 5000  # no change to ordinary Auto iterations


def test_old_auto_only_splice_file_is_supported(tmp_path):
    base = _write(tmp_path / 'base.toml', '''[common]
workers = 6
[auto]
iterations = 500
''')
    splice = _write(tmp_path / 'splice.toml', '''[auto]
splice-files = ["203", "end"]
splice-search = "both"
splice-rounds = 4
''')
    args = parse_arguments(['auto', 'file.ltm', '--config', str(base),
                            '--splice-config', str(splice)])
    assert args.workers == 6
    assert args.iterations == 500
    assert args.auto_splice_rounds == 4
    assert args.auto_splice_files == ('203', 'end')


def test_multi_splicer_table_works_in_repeated_config(tmp_path):
    base = _write(tmp_path / 'base.toml', '''[common]
workers = 6
''')
    splice = _write(tmp_path / 'splice.toml', '''[multi-splicer]
splice-files = ["203", "end"]
splice-search = "both"
splice-iterations = 700
''')
    args = parse_arguments(['auto', 'file.ltm', '--config', str(base),
                            '--config', str(splice)])
    assert args.workers == 6
    assert args.auto_splice_files == ('203', 'end')
    assert args.auto_splice_iterations == 700


def test_splicer_table_does_not_change_regular_local(tmp_path):
    file = _write(tmp_path / 'base.toml', '''[local]
objective = "min-y"
target-frame = 50
range = "10:50"
[multi-splicer]
files = ["203", "end"]
rounds = 50
''')
    args = parse_arguments(['local', 'file.ltm', '--config', str(file)])
    assert args.objective == 'min-y'
    assert args.target_frame == 50
    with pytest.raises(SystemExit, match='--splice-config is only supported in auto mode'):
        parse_arguments(['local', 'file.ltm', '--splice-config', str(file)])


def test_unknown_splice_table_setting_rejected(tmp_path):
    splice = _write(tmp_path / 'splice.toml', '''[multi-splicer]
splice-files = ["end"]
mispeled-splice-iters = 20
''')
    with pytest.raises(SystemExit, match='unknown TOML option'):
        parse_arguments(['auto', 'file.ltm', '--splice-config', str(splice)])


def test_hyphen_and_underscore_splice_sections_are_exclusive(tmp_path):
    splice = _write(tmp_path / 'splice.toml', '''[multi-splicer]
files = ["end"]
[multi_splicer]
files = ["203"]
''')
    with pytest.raises(SystemExit, match='must not define both'):
        parse_arguments(['auto', 'file.ltm', '--splice-config', str(splice)])


def test_cli_splice_flags_override_file(tmp_path):
    splice = _write(tmp_path / 'splice.toml', '''[multi-splicer]
files = ["203", "408", "end"]
start = "203"
stop = "end"
directory = "somewhere"
''')
    args = parse_arguments(['auto', 'file.ltm', '--splice-config', str(splice),
                            '--splice-start', '408', '--splice-stop', '408',
                            '--auto-splice-directory', 'override'])
    assert args.auto_splice_start == args.auto_splice_stop == '408'
    assert args.auto_splice_directory == Path('override')


def test_explicit_splice_file_activates_named_mode_over_inherited_auto_defaults(tmp_path):
    base = _write(tmp_path / 'base.toml', '''[auto]
splice-mode = "physics"
random-splice = false
iterations = 1000
''')
    splice = _write(tmp_path / 'splice.toml', '''[multi-splicer]
files = ["556", "end"]
''')
    args = parse_arguments(['auto', 'file.ltm', '--config', str(base),
                            '--splice-config', str(splice)])
    assert args.auto_random_splice is True
    assert args.auto_splice_mode == 'user'
    assert args.iterations == 1000
    with pytest.raises(SystemExit, match='splice-files requires'):
        parse_arguments(['auto', 'file.ltm', '--config', str(base),
                         '--splice-config', str(splice), '--auto-splice-mode', 'random'])


def test_endpoint_auto_splice_backend_receives_regular_refinement_settings(monkeypatch):
    """Shared [auto] settings must be used, not merely parsed and discarded."""
    from nv14_random_splice import RandomSpliceConfig, _local_search
    from nv14_endpoint import EndpointGoal
    from nv14_engine import InputFrame
    import nv14_auto_endpoint

    captured = {}

    def fake_search(level, frames, goal, config, **kwargs):
        captured['config'] = config
        return None, None, 0

    monkeypatch.setattr(nv14_auto_endpoint, 'optimise_auto_endpoint_campaign', fake_search)
    config = RandomSpliceConfig(
        search_backend='endpoint-auto',
        endpoint_auto_mutation_share=0.7,
        endpoint_progressive_refinement=True,
        endpoint_refinement_share=0.4,
        endpoint_adaptive_refinement=False,
        endpoint_refinement_cycle=64,
        endpoint_refinement_polish=False,
        endpoint_refinement_chain_steps=20,
        endpoint_shared_refinement_proposals=15,
        endpoint_performance_stats=True,
        endpoint_repair_steps=0,
    )
    _local_search(object(), (InputFrame(),) * 3,
                  EndpointGoal(target_frame=2, objective='min-x'),
                  start=0, config=config, iterations=100, rounds=2, seed=123)
    auto = captured['config']
    assert auto.auto_mutation_share == 0.7
    assert auto.progressive_refinement is True
    assert auto.refinement_share == 0.4
    assert auto.adaptive_refinement is False
    assert auto.refinement_cycle == 64
    assert auto.refinement_polish is False
    assert auto.refinement_chain_steps == 20
    assert auto.shared_refinement_proposals == 15
    assert auto.performance_stats is True
    assert auto.repair_steps == 0


def test_shared_splicer_defaults_plus_level_files_only(tmp_path):
    """The base and level TOMLs may each define half of one [multi-splicer]."""
    base = _write(tmp_path / "examples.toml", '''[common]
workers = 8
[auto]
iterations = 10000
runs = 0
beam = 64
progressive-refinement = true
[multi-splicer]
search = "both"
iterations = 400
rounds = 3
frontier = 3
runs = 5
''')
    level = tmp_path / "splices" / "97-1"
    level.mkdir(parents=True)
    splice = _write(level / "multi-splicer.toml", '''[multi-splicer]
files = ["556", "628", "739", "end"]
''')
    args = parse_arguments(["auto", "level.ltm", "--config", str(base),
                            "--splice-config", str(splice)])
    assert args.auto_splice_files == ("556", "628", "739", "end")
    assert args.auto_splice_search == "both"
    assert args.auto_splice_iterations == 400
    assert args.auto_splice_rounds == 3
    assert args.auto_splice_frontier == 3
    assert args.auto_runs == 5
    assert args.iterations == 10000
    assert args.beam == 64
    assert args.workers == 8
    assert args.auto_random_splice and args.auto_splice_mode == "user"
    assert args.splice_config.parent == level

    # Explicit CLI options retain highest priority.
    overridden = parse_arguments(["auto", "level.ltm", "--config", str(base),
                                  "--splice-config", str(splice),
                                  "--auto-runs", "7", "--auto-splice-iterations", "250"])
    assert overridden.auto_runs == 7
    assert overridden.auto_splice_iterations == 250
    assert overridden.auto_splice_rounds == 3

    # The same shared config must NOT reconfigure ordinary Auto when no
    # splice file list is selected.
    ordinary = parse_arguments(["auto", "level.ltm", "--config", str(base)])
    assert not ordinary.auto_random_splice
    assert not ordinary.auto_splice_files
    assert ordinary.auto_runs == 0
    assert ordinary.iterations == 10000


def test_level_splice_file_can_override_one_shared_option(tmp_path):
    base = _write(tmp_path / "common.toml", '''[auto]
runs = 0
[multi-splicer]
search = "both"
iterations = 400
rounds = 3
frontier = 3
runs = 5
''')
    level = _write(tmp_path / "level.toml", '''[multi-splicer]
files = ["203", "end"]
rounds = 4
''')
    args = parse_arguments(["auto", "level.ltm", "--config", str(base),
                            "--splice-config", str(level)])
    assert args.auto_splice_files == ("203", "end")
    assert args.auto_splice_search == "both"
    assert args.auto_splice_iterations == 400
    assert args.auto_splice_rounds == 4
    assert args.auto_splice_frontier == 3
    assert args.auto_runs == 5


def test_shared_example_config_has_dormant_multi_splicer_defaults():
    example = Path(__file__).resolve().parents[1] / "examples" / "config.toml"
    args = parse_arguments(["auto", "level.ltm", "--config", str(example)])
    assert not args.auto_random_splice
    assert args.auto_runs == 0  # the ordinary Auto setting, not multi runs=5
    assert args.iterations == 10000

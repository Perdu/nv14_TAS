"""Shortcuts must expand to the existing verified CLI; never bypass it."""
import pytest
import tas


def test_modes_and_templates_generate_existing_cli_options():
    env = {}
    auto = tas.build_command('auto', '53-4', env=env)
    assert '--auto-runs' in auto and auto[auto.index('--auto-runs') + 1] == '10'
    assert '../n_levels/53-4.ltm' in auto
    assert 'wip/53-4.ltm' in auto and 'wip/53-4.txt' in auto
    local = tas.build_command('local', '55-1', 'end', env=env)
    assert local[2:4] == ['local', '../n_levels/55-1.ltm']
    assert '../splices/55-1/end.txt' in local
    assert local[local.index('--stagnation-rounds') + 1] == '50'
    assert '--stagnation-rounds' in tas.build_command(
        'local', '55-1', 'end', env={'TAS_STAGNATION_LOCAL': '50'})
    goal = tas.build_command('goal', '53-4', '591', env=env)
    assert '--goal-config' in goal and '../splices/53-4/591.txt' in goal
    random = tas.build_command('random', '55-1', env=env)
    assert '--auto-stagnation-runs' in random and '--simulate-enemies' in random
    multi = tas.build_command('multi', '97-2', env=env)
    assert '--splice-config' in multi
    assert '../splices/97-2/multi-splicer.toml' in multi
    merge = tas.build_command('merge', '88-4', env=env)
    assert '--splice-merge-only' in merge and '--auto-runs' not in merge
    repair = tas.build_command('repair', '88-4', env=env)
    assert '--splice-merge-repair-only' in repair and '--auto-runs' not in repair


def test_env_and_extra_flags_override_defaults():
    env = {'TAS_WORKERS': '3', 'TAS_CONFIG': '/tmp/custom.toml',
           'TAS_OUTPUT_TEMPLATE': 'out/{level}_{splice}.ltm',
           'TAS_INPUT_TEMPLATE': 'manual/{level}.ltm'}
    command = tas.build_command('goal', '88-4', '522', env=env,
                                extra=['--workers', '7', '--auto-runs', '2'])
    assert command[-4:] == ['--workers', '7', '--auto-runs', '2']
    assert 'out/88-4_522.ltm' in command
    assert 'manual/88-4.ltm' in command
    assert '/tmp/custom.toml' in command
    with pytest.raises(ValueError, match='same file'):
        tas.build_command('auto', '88-4', env={'TAS_INPUT_TEMPLATE':'wip/{level}.ltm'})


def test_dry_run_and_loop_do_not_invoke_backend(monkeypatch, capsys):
    def forbidden(*_a, **_kw):
        pytest.fail('dry-run launched a subprocess')
    monkeypatch.setattr(tas.subprocess, 'run', forbidden)
    assert tas.main(['multi', '97-2', '--dry-run'], env={}) == 0
    assert tas.main(['loop', '97-2', '88-4', '--dry-run'], env={}) == 0
    assert tas.main(['merge', '--dry-run'], env={'LEVEL': '88-4'}) == 0
    text = capsys.readouterr().out
    assert text.count('multi-splicer.toml') == 4
    assert 'splice-merge-only' in text


def test_jaffar_presets_are_mode_specific():
    auto = tas.build_command('auto', '53-4', jaffar=True, env={})
    local = tas.build_command('local', '55-1', 'end', jaffar=True, env={})
    assert '--auto-repair-beam-width' in auto
    assert '--local-beam-width' not in auto
    assert '--local-beam-width' in local
    assert '--auto-repair-beam-width' not in local


def test_shortcuts_read_shared_auto_and_local_limits(tmp_path, monkeypatch):
    root = tmp_path / "optimiser"
    root.mkdir()
    shared = root / "examples" / "config.toml"
    shared.parent.mkdir()
    shared.write_text('[auto]\nruns = 7\n[local]\nstagnation-rounds = 33\n')
    goal = tmp_path / "splices" / "93-1" / "end.txt"
    goal.parent.mkdir(parents=True)
    goal.write_text('[local]\nsearch = "population"\n')
    monkeypatch.setattr(tas, 'ROOT', root)

    auto = tas.build_command('auto', '93-1', env={})
    assert auto[auto.index('--auto-runs') + 1] == '7'
    local = tas.build_command('local', '93-1', 'end', env={})
    assert local[local.index('--stagnation-rounds') + 1] == '33'

    # Goal and CLI limits must not be overwritten by the shared Local default.
    for setting in ('rounds = 1', 'stagnation-rounds = 9', 'stagnation_rounds = 8'):
        goal.write_text('[local]\nsearch = "population"\n' + setting + '\n')
        assert '--stagnation-rounds' not in tas.build_command('local', '93-1', 'end', env={})
    goal.write_text('[local]\nsearch = "population"\n')
    assert '--stagnation-rounds' not in tas.build_command(
        'local', '93-1', 'end', env={}, extra=('--rounds', '2'))[:-2]

    # Environment overrides still supersede shared TOML.
    auto = tas.build_command('auto', '93-1', env={'TAS_RUNS_AUTO': '11'})
    assert auto[auto.index('--auto-runs') + 1] == '11'
    local = tas.build_command('local', '93-1', 'end', env={'TAS_STAGNATION_LOCAL': '55'})
    assert local[local.index('--stagnation-rounds') + 1] == '55'
    goal.write_text('[local]\nsearch = "windows"\n')
    assert '--stagnation-rounds' not in tas.build_command('local', '93-1', 'end', env={})


def test_shortcut_shared_config_validates_selected_default(tmp_path, monkeypatch):
    monkeypatch.setattr(tas, 'ROOT', tmp_path)
    shared = tmp_path / 'examples' / 'config.toml'
    shared.parent.mkdir()
    shared.write_text('[auto]\nruns = 0\n[local]\nstagnation-rounds = 50\n')
    assert '--auto-runs' in tas.build_command('auto', '53-4', env={})
    shared.write_text('[auto]\nruns = -1\n')
    with pytest.raises(ValueError, match=r'\[auto\] runs'):
        tas.build_command('auto', '53-4', env={})
    # Explicit environment overrides don't require the shared setting.
    auto = tas.build_command('auto', '53-4', env={'TAS_RUNS_AUTO': '12'})
    assert auto[auto.index('--auto-runs') + 1] == '12'
    shared.write_text('[local]\nstagnation-rounds = 0\n')
    with pytest.raises(ValueError, match=r'\[local\] stagnation-rounds'):
        tas.build_command('local', '53-4', 'end', env={})


def test_local_shared_patience_reaches_backend_parser(tmp_path, monkeypatch):
    import nv14_cli
    root = tmp_path / 'optimiser'
    root.mkdir()
    shared = root / 'examples' / 'config.toml'
    shared.parent.mkdir()
    shared.write_text('[local]\nstagnation-rounds = 50\n')
    goal = tmp_path / 'splices' / '93-1' / 'end.txt'
    goal.parent.mkdir(parents=True)
    goal.write_text('[local]\nsearch = "population"\nobjective = "earliest-interaction"\n')
    monkeypatch.setattr(tas, 'ROOT', root)
    monkeypatch.chdir(root)
    cli = tas.build_command('local', '93-1', 'end', env={})
    parsed = nv14_cli.build_parser().parse_args(cli[2:])
    assert parsed.search == 'population'
    assert parsed.rounds == 0  # Removes the backend's implicit one-round cap.
    assert parsed.stagnation_rounds == 50

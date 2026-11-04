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
    assert '--stagnation-rounds' in local
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

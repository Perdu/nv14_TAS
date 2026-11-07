"""Per-splice Local TOML constrains both Auto and Local under named splicing."""
from dataclasses import replace

import pytest

import nv14_cli as cli
import nv14_user_splice as us
from nv14_random_splice import RandomSpliceConfig
from nv14_engine import InputFrame
from tests.test_random_splice import _baseline


def _setup(tmp_path, goal_settings, *, base='[auto]\nbeam = 12\n', shared=None):
    root = tmp_path / 'level'
    root.mkdir()
    (root / '230.txt').write_text('[local]\n' + goal_settings)
    (root / 'end.txt').write_text('[local]\nsearch="population"\n'
                                  'objective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    general = tmp_path / 'base.toml'
    general.write_text(base)
    level = root / 'multi-splicer.toml'
    level.write_text(shared or '[multi-splicer]\nfiles=["230", "end"]\nsearch="both"\n')
    args = cli.parse_arguments(['auto', 'level.ltm', '--config', str(general),
                                '--splice-config', str(level)])
    return args, root


def test_stage_goal_and_search_overrides_automatically_apply_to_both(monkeypatch, tmp_path):
    args, directory = _setup(tmp_path, '''search = "population"
objective = "earliest-arrival"
target-frame = 10
range = "2:10"
target-region = "0:800,0:600"
secondary-objective = "max-x"
iterations = 120
beam = 9
mutation-span = 64
repair-steps = 7
repair-lookback = 16
top-results = 3
''')
    level, frames, _ = _baseline()
    stages = cli._load_named_splice_stages(level, frames, args, directory, args.auto_splice_files)
    stage = stages[0]
    assert (stage.start, stage.end, stage.goal.target_frame) == (2, 10, 10)
    assert stage.goal.objective == 'earliest-arrival'
    assert stage.goal.secondary_objective == 'max-x'
    assert stage.goal.target_region == (0., 800., 0., 600.)
    assert stage.config_overrides == {
        'iterations': 120, 'beam': 9, 'endpoint_mutation_span': 64,
        'local_mutation_span': 64, 'endpoint_repair_steps': 7,
        'local_repair_steps': 7, 'endpoint_repair_lookback': 16,
        'local_repair_lookback': 16, 'backend_top_results': 3,
    }
    assert stages[1].config_overrides == {}
    calls = []

    def fake_search(level, branch, stage, config, rng, **kw):
        calls.append((stage.name, config))
        return (), 0, 1

    monkeypatch.setattr(us, '_search_stage', fake_search)
    us.optimise_user_splices(level, frames, stages,
                            RandomSpliceConfig(search_backend='both', rounds=1, iterations=400),
                            completion_policy='checkpoint')
    assert calls[0][1].search_backend == 'both'
    assert calls[0][1].iterations == 120
    assert calls[0][1].beam == 9
    assert calls[0][1].local_mutation_span == 64
    assert calls[-1][1].iterations == 400  # no leakage to the next stage


def test_explicit_cli_backend_value_precedes_stage_toml(tmp_path):
    args, directory = _setup(tmp_path, '''search="population"
objective="min-x"
target-frame=10
range="0:10"
iterations=100
beam=6
''')
    level, frames, _ = _baseline()
    explicit = cli.parse_arguments(['auto', 'level.ltm', '--config', str(tmp_path / 'base.toml'),
                                   '--splice-config', str(directory / 'multi-splicer.toml'),
                                   '--beam', '24', '--auto-splice-iterations', '300'])
    stage = cli._load_named_splice_stages(level, frames, explicit, directory, explicit.auto_splice_files)[0]
    assert stage.config_overrides == {}


def test_common_goal_defaults_are_inherited_unless_overridden(tmp_path):
    args, directory = _setup(tmp_path, '''search="population"
objective="earliest-arrival"
target-frame=10
range="0:10"
''', base='[auto]\nsecondary-objective="max-x"\n'
                   'target-region="0:800,0:600"\n')
    (directory / 'end.txt').write_text('[local]\nobjective="earliest-arrival"\n'
                                        'target-frame=10\nrange="0:10"\n')
    level, frames, _ = _baseline()
    stage = cli._load_named_splice_stages(level, frames, args, directory, args.auto_splice_files)[0]
    assert stage.goal.target_region == (0., 800., 0., 600.)
    assert stage.goal.secondary_objective == 'max-x'


def test_stagnation_override_applies_to_both_phases(tmp_path):
    args, directory = _setup(tmp_path, '''search="population"
objective="min-x"
target-frame=10
range="0:10"
stagnation-rounds=7
''', shared='[multi-splicer]\nfiles=["230","end"]\nsearch="both"\n'
             'auto-stagnation-rounds=10\nlocal-stagnation-rounds=50\n')
    level, frames, _ = _baseline()
    stage = cli._load_named_splice_stages(level, frames, args, directory, args.auto_splice_files)[0]
    assert stage.config_overrides['splice_auto_stagnation_rounds'] == 7
    assert stage.config_overrides['splice_local_stagnation_rounds'] == 7


def test_per_splice_rounds_rejected_when_ignored_by_phase_mode(tmp_path):
    args, directory = _setup(tmp_path, '''search="population"
objective="min-x"
target-frame=10
rounds=2
''', shared='[multi-splicer]\nfiles=["230","end"]\nsearch="both"\n'
             'auto-stagnation-rounds=10\nlocal-stagnation-rounds=50\n')
    level, frames, _ = _baseline()
    with pytest.raises(ValueError, match='rounds is unused'):
        cli._load_named_splice_stages(level, frames, args, directory, args.auto_splice_files)



@pytest.mark.parametrize('mode', ['hybrid', 'hybrid-restart', 'hybrid-local-control'])
def test_named_hybrid_ignores_old_multi_and_local_round_settings(tmp_path, mode, monkeypatch):
    args, directory = _setup(
        tmp_path, 'objective="min-x"\ntarget-frame=10\nrange="0:10"\n'
        'rounds=7\nstagnation-rounds=11\n',
        shared='[multi-splicer]\nfiles=["230", "end"]\n'
               f'search="{mode}"\nrounds=8\n'
               'auto-stagnation-rounds=10\nlocal-stagnation-rounds=50\n'
               'stagnation-rounds=4\nspeed="fast"\n'
               'round-speeds=["current", "slow"]\n')
    level, frames, _ = _baseline()
    stages = cli._load_named_splice_stages(level, frames, args, directory,
                                           args.auto_splice_files)
    assert stages[0].config_overrides == {}
    assert args.auto_splice_rounds == 8
    assert args.auto_splice_auto_stagnation_rounds == 10
    assert args.auto_splice_local_stagnation_rounds == 50
    assert args.auto_splice_stagnation_rounds == 4
    # Named-stage coordination ignores obsolete phase settings, but the
    # speed preset must now configure hybrid cycle patience (fast = 3).
    # Neither may activate the old continuous-phase callback path.
    calls = []
    def fake_search(_level, _branch, _stage, cfg, _rng, **kwargs):
        calls.append((cfg.search_backend, cfg.hybrid_stagnation_cycles,
                      tuple(kwargs)))
        return (), 0, 1
    monkeypatch.setattr(us, '_search_stage', fake_search)
    inherited = RandomSpliceConfig(
        search_backend=mode, rounds=1, splice_rounds=8,
        splice_auto_stagnation_rounds=10, splice_local_stagnation_rounds=50,
        splice_stagnation_rounds=4, splice_speed='fast',
        splice_round_speeds=('current', 'slow'))
    us.optimise_user_splices(level, frames, stages, inherited,
                             completion_policy='checkpoint')
    assert calls
    assert all(backend == mode and patience == 3
               and 'stage_rank' not in kwargs and 'resume_phase' not in kwargs
               for backend, patience, kwargs in calls)



@pytest.mark.parametrize('bad', ['window=4\n', 'checkpoint="saved.pkl"\n', 'search="windows"\n'])
def test_nonapplicable_splice_settings_are_rejected(tmp_path, bad):
    args, directory = _setup(tmp_path, '''objective="min-x"
target-frame=10
''' + bad)
    level, frames, _ = _baseline()
    with pytest.raises(ValueError, match='unsupported per-splice|not supported'):
        cli._load_named_splice_stages(level, frames, args, directory, args.auto_splice_files)


def test_stage_simulate_enemies_overrides_common_and_uses_actual_directory(tmp_path):
    args, directory = _setup(tmp_path, '''search="population"
objective="min-x"
target-frame=10
simulate-enemies=true
''', base='[common]\nsimulate-enemies=false\n')
    assert cli._named_splice_directory(args) == directory
    assert cli._named_splice_enemy_simulation(args, False) is True


def test_conflicting_simulate_enemies_are_per_stage(tmp_path):
    args, directory = _setup(tmp_path, '''objective="min-x"
target-frame=10
simulate-enemies=true
''', base='[common]\nsimulate-enemies=false\n')
    (directory / 'end.txt').write_text('[local]\nobjective="min-x"\n'
                                       'target-frame=10\nsimulate-enemies=false\n')
    assert cli._named_splice_enemy_simulation(args, False) is True
    from tests.test_random_splice import _baseline
    level, frames, _ = _baseline()
    stages = cli._load_named_splice_stages(level, frames, args, directory, args.auto_splice_files)
    assert [stage.simulate_enemies for stage in stages] == [True, False]


def test_explicit_simulation_cli_flag_overrides_splices(tmp_path):
    args, directory = _setup(tmp_path, '''objective="min-x"
target-frame=10
simulate-enemies=true
''')
    explicit = cli.parse_arguments(['auto', 'level.ltm', '--config', str(tmp_path / 'base.toml'),
                                   '--splice-config', str(directory / 'multi-splicer.toml'),
                                   '--no-simulate-enemies'])
    assert cli._named_splice_enemy_simulation(explicit, False) is False

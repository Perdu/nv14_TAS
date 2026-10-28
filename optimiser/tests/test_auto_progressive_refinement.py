"""Progressive endpoint Auto regression tests for the uploaded Hybrid revision."""
from dataclasses import replace

import pytest

import nv14_auto_endpoint as endpoint
from nv14_auto_endpoint import AutoEndpointConfig, optimise_auto_endpoint
from nv14_cli import parse_arguments
from nv14_endpoint import EndpointGoal, verify_endpoint
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame, parse_level_string


def _setup():
    level = parse_level_string('0' * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + '|5^60,60')
    frames = (InputFrame(),) * 40
    goal = EndpointGoal(target_frame=24, objective='max-x')
    return level, frames, goal


def test_config_validates_refinement_controls():
    for invalid in (-0.1, 1.01, float('nan'), float('inf')):
        with pytest.raises(ValueError, match='refinement-share'):
            AutoEndpointConfig(refinement_share=invalid)
    for invalid in (0, 1, 1.5, True):
        with pytest.raises(ValueError, match='refinement-cycle'):
            AutoEndpointConfig(refinement_cycle=invalid)
    with pytest.raises(ValueError, match='booleans'):
        AutoEndpointConfig(progressive_refinement=1)
    with pytest.raises(ValueError, match='booleans'):
        AutoEndpointConfig(adaptive_refinement=0)


def test_toml_controls_and_legacy_fallback(tmp_path):
    settings = tmp_path / 'refinement.toml'
    settings.write_text('''[auto]
progressive-refinement = false
refinement-share = 0.35
adaptive-refinement = false
refinement-cycle = 40
endpoint-repair-steps = 0
''')
    args = parse_arguments(['auto', 'source.ltm', '--config', str(settings)])
    assert not args.auto_progressive_refinement
    assert args.auto_refinement_share == 0.35
    assert not args.auto_adaptive_refinement
    assert args.auto_refinement_cycle == 40
    assert args.auto_endpoint_repair_steps == 0
    assert parse_arguments(['auto', 'source.ltm']).auto_progressive_refinement


def test_interleaved_proposals_have_exact_budget_and_no_repair(monkeypatch):
    level, frames, goal = _setup()
    calls = {'auto': 0, 'local': 0}

    def hybrid(parent, donor, **kwargs):
        calls['auto'] += 1
        return parent.frames, 8

    def local(parent, donor, ranges, mutable, rng, span):
        calls['local'] += 1
        return parent.frames, 'no-op', 8

    def forbidden_repair(*args, **kwargs):
        pytest.fail('progressive refinement invoked expensive endpoint repair')

    monkeypatch.setattr(endpoint, '_hybrid_proposal', hybrid)
    monkeypatch.setattr(endpoint, '_population_mutate', local)
    monkeypatch.setattr(endpoint, '_endpoint_repair', forbidden_repair)
    reports = []
    _baseline, _best, evaluated = optimise_auto_endpoint(
        level, frames, goal,
        AutoEndpointConfig(iterations=40, beam_width=8, seed=4,
                           refinement_share=0.25, refinement_cycle=20,
                           adaptive_refinement=False, repair_steps=64),
        progress=lambda proposed, unique, best: reports.append((proposed, unique)),
    )
    assert calls == {'auto': 30, 'local': 10}
    assert evaluated == 0  # No-op candidates do not invoke the native engine.
    assert reports[-1] == (40, 0)


def test_nonprogressive_fallback_keeps_previous_hybrid_path(monkeypatch):
    level, frames, goal = _setup()
    calls = {'auto': 0}

    def hybrid(parent, donor, **kwargs):
        calls['auto'] += 1
        return parent.frames, 5

    def local(*args, **kwargs):
        pytest.fail('disabled progressive path used local population search')

    monkeypatch.setattr(endpoint, '_hybrid_proposal', hybrid)
    monkeypatch.setattr(endpoint, '_population_mutate', local)
    optimise_auto_endpoint(
        level, frames, goal,
        AutoEndpointConfig(iterations=24, beam_width=8, seed=4,
                           progressive_refinement=False, repair_steps=0),
    )
    assert calls['auto'] == 24


def test_adaptation_uses_strict_improvement_rates():
    assert endpoint._next_refinement_share(0.25, 2, 10, 1, 20) == pytest.approx(0.30)
    assert endpoint._next_refinement_share(0.25, 0, 10, 1, 20) == pytest.approx(0.20)
    assert endpoint._next_refinement_share(0.25, 0, 10, 0, 20) == 0.25
    assert endpoint._next_refinement_share(0.25, 1, 10, 0, 0) == 0.25
    assert endpoint._next_refinement_share(0.50, 1, 10, 0, 10) == 0.50
    assert endpoint._next_refinement_share(0.10, 0, 10, 1, 10) == 0.10


def test_progressive_results_are_verified_and_frame_bounded():
    level, frames, goal = _setup()
    config = AutoEndpointConfig(iterations=160, beam_width=12, seed=18,
                                range_start=4, range_end=24,
                                repair_steps=0, refinement_cycle=32)
    baseline, winner, evaluated = optimise_auto_endpoint(level, frames, goal, config)
    assert 0 < evaluated <= config.iterations
    assert winner is not None
    assert winner.evaluation.objective_key <= baseline.evaluation.objective_key
    assert winner.frames[:4] == frames[:4]
    assert winner.frames[25:] == frames[25:]
    assert verify_endpoint(level, winner.frames, goal, expected=winner.evaluation).feasible

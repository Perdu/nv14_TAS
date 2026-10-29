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
    with pytest.raises(ValueError, match='booleans'):
        AutoEndpointConfig(refinement_polish=0)


def test_toml_controls_and_legacy_fallback(tmp_path):
    settings = tmp_path / 'refinement.toml'
    settings.write_text('''[auto]
progressive-refinement = false
refinement-share = 0.35
adaptive-refinement = false
refinement-cycle = 40
refinement-polish = false
endpoint-repair-steps = 0
''')
    args = parse_arguments(['auto', 'source.ltm', '--config', str(settings)])
    assert not args.auto_progressive_refinement
    assert args.auto_refinement_share == 0.35
    assert not args.auto_adaptive_refinement
    assert args.auto_refinement_cycle == 40
    assert not args.auto_refinement_polish
    assert args.auto_endpoint_repair_steps == 0
    assert parse_arguments(['auto', 'source.ltm']).auto_progressive_refinement
    assert parse_arguments(['auto', 'source.ltm']).auto_refinement_polish
    assert not parse_arguments(['auto', 'source.ltm', '--no-auto-refinement-polish']).auto_refinement_polish


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
                           adaptive_refinement=False, repair_steps=64,
                           refinement_polish=False),
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


def test_polisher_systematically_checks_one_frame_variants_and_exhausts():
    from types import SimpleNamespace
    level, frames, goal = _setup()
    import random
    leader = endpoint.AutoEndpointCandidate(frames, SimpleNamespace(frame=20))
    polisher = endpoint._SingleFramePolisher()
    rng = random.Random(17)
    changes = set()
    while (proposed := polisher.propose(leader, start=4, end=24, rng=rng)) is not None:
        indexes = [i for i, (old, new) in enumerate(zip(frames, proposed)) if old != new]
        assert len(indexes) == 1
        assert 4 <= indexes[0] <= 20
        changes.add(endpoint._key(proposed))
    assert len(changes) == 17 * 5  # six input choices minus the original
    assert polisher.propose(leader, start=4, end=24, rng=rng) is None
    changed_leader = list(frames)
    changed_leader[7] = endpoint.ALL_INPUT_CHOICES[4]
    different = endpoint.AutoEndpointCandidate(tuple(changed_leader), SimpleNamespace(frame=20))
    assert polisher.propose(different, start=4, end=24, rng=rng) is not None


def test_polishing_spends_no_extra_proposals_or_repairs(monkeypatch):
    level, frames, goal = _setup()
    calls = {'auto': 0, 'local': 0}

    def hybrid(parent, donor, **kwargs):
        calls['auto'] += 1
        return parent.frames, 8

    def local(parent, donor, ranges, mutable, rng, span):
        calls['local'] += 1
        return parent.frames, 'no-op', 8

    monkeypatch.setattr(endpoint, '_hybrid_proposal', hybrid)
    monkeypatch.setattr(endpoint, '_population_mutate', local)
    monkeypatch.setattr(endpoint, '_endpoint_repair', lambda *args, **kw: pytest.fail('repair invoked'))
    config = AutoEndpointConfig(iterations=80, beam_width=8, seed=17,
                                refinement_share=0.5, refinement_cycle=20,
                                adaptive_refinement=False, repair_steps=64)
    _baseline, best, evaluated = optimise_auto_endpoint(level, frames, goal, config)
    assert calls['auto'] == 40
    assert 0 < calls['local'] < 40  # some Local slots are deterministic polish
    assert 0 < evaluated <= 40
    assert best is not None
    assert verify_endpoint(level, best.frames, goal, expected=best.evaluation).feasible


def test_stagnation_raises_local_share_without_exceeding_cap():
    update = endpoint._stagnation_refinement_share
    assert update(0.25, 23) == 0.25
    assert update(0.25, 24) == pytest.approx(0.30)
    assert update(0.60, 48) == pytest.approx(0.65)
    assert update(0.65, 48) == 0.65
    assert update(0.8, 48) == 0.8
    assert update(0.0, 48) == 0.0


def test_chained_refinement_settings_are_configurable(tmp_path):
    with pytest.raises(ValueError, match='refinement-chain-steps'):
        AutoEndpointConfig(refinement_chain_steps=-1)
    with pytest.raises(ValueError, match='refinement-chain-steps'):
        AutoEndpointConfig(refinement_chain_steps=True)
    path = tmp_path / 'chain.toml'
    path.write_text('[auto]\nrefinement-chain-steps = 0\n')
    assert parse_arguments(['auto', 'source.ltm', '--config', str(path)]).auto_refinement_chain_steps == 0
    assert parse_arguments(['auto', 'source.ltm']).auto_refinement_chain_steps == 32


def test_repair_chain_builds_on_intermediate_improvements_without_evaluating():
    import random
    level, source, goal = _setup()
    evaluator = endpoint.EndpointEvaluator(level, goal, source, prefix_frame=4)
    changed = list(source)
    changed[8] = InputFrame(right=True)
    first = endpoint.AutoEndpointCandidate(tuple(changed), evaluator.evaluate(changed))
    chain = endpoint._BudgetedLocalChain()
    chain.seed(first, anchor=8, start=4, end=24,
               lookback=12, steps=5, rng=random.Random(11))
    assert chain.current is first
    first_proposal = chain.propose()
    assert first_proposal is not None
    assert sum(a != b for a, b in zip(first_proposal, first.frames)) == 1
    assert first_proposal[:4] == source[:4]
    assert first_proposal[25:] == source[25:]
    # Feed the chain an explicitly better simulated intermediate candidate.
    from dataclasses import replace
    improved = endpoint.AutoEndpointCandidate(
        first_proposal, replace(first.evaluation, score=first.evaluation.score + 1),
    )
    chain.observe(improved, endpoint._key(source))
    assert chain.current is improved
    second_proposal = chain.propose()
    assert second_proposal is not None
    assert sum(a != b for a, b in zip(second_proposal, improved.frames)) == 1


def test_progressive_chain_uses_existing_proposal_slots(monkeypatch):
    level, frames, goal = _setup()
    calls = {'chain': 0, 'population': 0}
    original_propose = endpoint._BudgetedLocalChain.propose

    def counted_chain(self):
        calls['chain'] += 1
        return original_propose(self)

    def improving_local(parent, donor, ranges, mutable, rng, span):
        calls['population'] += 1
        changed = list(parent.frames)
        changed[6] = InputFrame(right=True)
        return tuple(changed), 'direction pulse', 6

    def no_hybrid(parent, donor, **kw):
        return parent.frames, 6

    monkeypatch.setattr(endpoint._BudgetedLocalChain, 'propose', counted_chain)
    monkeypatch.setattr(endpoint, '_population_mutate', improving_local)
    monkeypatch.setattr(endpoint, '_hybrid_proposal', no_hybrid)
    monkeypatch.setattr(endpoint, '_endpoint_repair', lambda *args, **kw: pytest.fail('nested repair invoked'))
    config = AutoEndpointConfig(iterations=36, beam_width=8, seed=4,
                                range_start=4, range_end=24,
                                refinement_share=1.0, refinement_cycle=12,
                                refinement_polish=False, adaptive_refinement=False,
                                refinement_chain_steps=8, repair_steps=64)
    reports = []
    baseline, winner, evaluations = optimise_auto_endpoint(
        level, frames, goal, config,
        progress=lambda spent, unique, best: reports.append((spent, unique)),
    )
    assert calls['population'] > 0
    assert calls['chain'] > 0
    assert evaluations <= config.iterations
    assert reports[-1] == (config.iterations, evaluations)
    assert winner is not None
    assert winner.evaluation.objective_key <= baseline.evaluation.objective_key
    assert verify_endpoint(level, winner.frames, goal, expected=winner.evaluation).feasible

from __future__ import annotations

import random

import pytest

import nv14_auto as auto
from nv14_engine import InputFrame, parse_level_string
from nv14_search import PatchEvaluationSpec, backend_info


@pytest.fixture
def held_jump_repair():
    info = backend_info()
    if not info.get("available"):
        pytest.skip(f"native Auto evaluator is unavailable: {info.get('error')}")
    tiles = ["0"] * (31 * 23)
    for x in range(31):
        tiles[x * 23 + 5] = "1"
    level = parse_level_string("".join(tiles) + "|5^100,134")
    # A legal 31-frame hold. Inserting at frame 5 can merge with or replace
    # this pulse, changing its tail at frame 37 beyond the repair target 13.
    body = (
        (InputFrame(),) * 7
        + (InputFrame(jump=True),) * 31
        + (InputFrame(),) * 32
    )
    evaluation = auto.evaluate_replay_with_sentinel(level, body)
    config = auto.AutoConfig(
        iterations=0,
        repair_lookback=6,
        repair_lookahead=3,
        repair_local_limit=0,
    )
    return level, body + (auto.NEUTRAL_INPUT,), evaluation, config


@pytest.mark.parametrize("collision_outcome", ["merge", "replace"])
def test_strategic_repair_scores_prefix_and_retains_complete_pulse(
    held_jump_repair, monkeypatch, collision_outcome
) -> None:
    level, working, evaluation, config = held_jump_repair
    patch = auto._strategic_jump_insertion_patch(
        working[:-1],
        auto._jump_pulses(working[:-1]),
        start=5,
        length=6,
        collision_outcome=collision_outcome,
        direction="existing",
    )
    generated = tuple(auto._strategic_jump_insertion_patches(
        working, evaluation, failure_tick=10, config=config
    ))
    assert patch in generated
    assert patch[-1].frame == 37

    proposal = list(working)
    for assignment in patch:
        proposal[assignment.frame] = assignment.input
    expected = tuple(proposal)
    baseline = auto.evaluate_replay_with_sentinel(level, expected[:-1])
    assert auto._repair_evaluation_score(
        evaluation, 13, baseline.point(13)
    ) > 0.0

    # Isolate one real generated candidate so a tied short hold cannot hide
    # accidental truncation of the returned replay. The evaluator stays native.
    monkeypatch.setattr(
        auto, "_strategic_jump_insertion_patches", lambda *a, **k: iter((patch,))
    )
    scores = []
    repaired, branches, simulations = auto.repair_strategic_jump_insertion_lookback(
        level,
        working,
        baseline,
        seed_evaluation=evaluation,
        failure_tick=10,
        reference_offset=0,
        config=config,
        score_observer=scores.append,
    )
    assert repaired == expected
    assert repaired[37] != working[37]
    assert repaired[-1] == auto.NEUTRAL_INPUT
    assert scores == [0.0]
    assert branches == 1
    # Only frames 5..13 are charged, not the full edited pulse through 37.
    assert simulations == 9
    verified = auto.evaluate_replay_with_sentinel(level, repaired[:-1])
    assert auto._repair_evaluation_score(verified, 13, baseline.point(13)) == 0.0


@pytest.mark.parametrize("limit", [0, 13])
@pytest.mark.parametrize("randomized", [False, True])
def test_strategic_generated_batches_respect_native_budget(
    held_jump_repair, limit, randomized
) -> None:
    from dataclasses import replace

    level, working, evaluation, config = held_jump_repair
    config = replace(config, repair_local_limit=limit)
    patches = tuple(auto._strategic_jump_insertion_patches(
        working, evaluation, failure_tick=10, config=config
    ))
    assert any(patch[-1].frame > 13 for patch in patches)
    progress = []
    _, branches, simulations = auto.repair_strategic_jump_insertion_lookback(
        level,
        working,
        evaluation,
        seed_evaluation=evaluation,
        failure_tick=10,
        reference_offset=0,
        config=config,
        rng=random.Random(9641006931360942370) if randomized else None,
        progress=lambda b, s: progress.append((b, s)),
    )
    assert progress[-1] == (branches, simulations)
    if limit:
        assert simulations == limit
    else:
        assert branches == len(patches)
        assert simulations > 13


def test_strategic_prefix_scoring_keeps_full_editable_range_validation(
    held_jump_repair,
) -> None:
    from dataclasses import replace

    _, working, evaluation, config = held_jump_repair
    patches = tuple(auto._strategic_jump_insertion_patches(
        working,
        evaluation,
        failure_tick=10,
        config=replace(config, range_start=5, range_end=13),
    ))
    assert patches
    assert all(5 <= patch[0].frame <= patch[-1].frame <= 13 for patch in patches)


def test_native_patch_spec_still_rejects_out_of_target_assignments(
    held_jump_repair,
) -> None:
    _, working, evaluation, config = held_jump_repair
    patch = next(patch for patch in auto._strategic_jump_insertion_patches(
        working, evaluation, failure_tick=10, config=config
    ) if patch[-1].frame > 13)
    with pytest.raises(ValueError, match="native patch assignment exceeds"):
        PatchEvaluationSpec(patches=(patch,), target_frame=13)

from __future__ import annotations

from dataclasses import replace

import pytest

from nv14_engine import InputFrame, parse_level_string
from nv14_search import (
    PATCH_TIE_LOW_EDIT_LEX,
    NativeSearchSession,
    PatchAssignmentSpec,
    PatchEvaluationSpec,
    TraceTargetSpec,
    backend_info,
)


EMPTY_MAP = "0" * (31 * 23)


def _session(level_string: str | None = None) -> NativeSearchSession:
    info = backend_info()
    if not info.get("available"):
        pytest.skip(f"native patch kernel is unavailable: {info.get('error')}")
    return NativeSearchSession(
        parse_level_string(level_string or EMPTY_MAP + "|5^100,100")
    )


def _direction_patches() -> tuple[tuple[PatchAssignmentSpec, ...], ...]:
    return (
        (PatchAssignmentSpec(0, InputFrame(right=True)),),
        (PatchAssignmentSpec(0, InputFrame(left=True)),),
    )


def test_native_patch_evaluator_preserves_order_ties_and_chargeable_budget() -> None:
    frames = (InputFrame(),) * 3
    session = _session()
    supplied = session.evaluate_patches(
        frames,
        PatchEvaluationSpec(patches=_direction_patches(), target_frame=2),
    )
    randomized = session.evaluate_patches(
        frames,
        PatchEvaluationSpec(
            patches=_direction_patches(),
            target_frame=2,
            tie_policy=PATCH_TIE_LOW_EDIT_LEX,
        ),
    )
    limited = session.evaluate_patches(
        frames,
        PatchEvaluationSpec(
            patches=_direction_patches(),
            target_frame=2,
            max_simulated_ticks=4,
        ),
    )

    assert supplied.best_patch_index == 0
    assert randomized.best_patch_index == 1
    assert supplied.stats.branches == supplied.stats.cloned_states == 2
    assert supplied.stats.simulated_ticks == 6
    assert limited.budget_exhausted
    assert limited.stats.branches == 2
    assert limited.stats.simulated_ticks == 4
    assert limited.candidates[0].has_endpoint
    assert not limited.candidates[1].has_endpoint


def test_native_patch_evaluator_can_skip_unrequested_endpoint_snapshots() -> None:
    frames = (InputFrame(),) * 3
    result = _session().evaluate_patches(
        frames,
        PatchEvaluationSpec(
            patches=_direction_patches(),
            target_frame=2,
            capture_endpoints=False,
        ),
    )

    assert result.best_patch_index == 0
    assert all(candidate.feasible for candidate in result.candidates)
    assert all(not candidate.has_endpoint for candidate in result.candidates)
    assert all(candidate.player is None for candidate in result.candidates)


def test_native_patch_cached_dead_prefix_preserves_zero_work_parity() -> None:
    # The prefix cache advances through frame 1 before the first edit at frame
    # 2.  A mine at the spawn kills that cached seed, so no candidate branch
    # may be cloned or simulated afterward.
    session = _session(EMPTY_MAP + "|5^100,100!12^100,100")
    result = session.evaluate_patches(
        (InputFrame(),) * 5,
        PatchEvaluationSpec(
            patches=((PatchAssignmentSpec(2, InputFrame(right=True)),),),
            target_frame=4,
        ),
    )

    assert result.best_patch_index is None
    assert not result.budget_exhausted
    assert len(result.candidates) == 1
    assert result.candidates[0].dead
    assert not result.candidates[0].feasible
    assert not result.candidates[0].has_endpoint
    assert result.stats.branches == 0
    assert result.stats.simulated_ticks == 0
    assert result.stats.cloned_states == 0
    assert result.stats.dead_prunes == 0
    assert result.stats.inactive_jump_prunes == 0
    assert result.stats.avoided_interaction_prunes == 0


def test_native_patch_sparse_lex_skips_equal_base_and_trigger_only_edits() -> None:
    frames = (InputFrame(),) * 251
    tiles = ["0"] * (31 * 23)
    for tile_x in range(31):
        tiles[tile_x * 23 + 5] = "1"
    patches = (
        (
            PatchAssignmentSpec(150, InputFrame(jump_trigger=False)),
            PatchAssignmentSpec(250, InputFrame(right=True)),
        ),
        (
            PatchAssignmentSpec(200, InputFrame(jump_trigger=False)),
            PatchAssignmentSpec(250, InputFrame(left=True)),
        ),
        (PatchAssignmentSpec(249, InputFrame(right=True)),),
    )
    result = _session("".join(tiles) + "|5^132,134").evaluate_patches(
        frames,
        PatchEvaluationSpec(
            patches=patches,
            target_frame=250,
            tie_policy=PATCH_TIE_LOW_EDIT_LEX,
        ),
    )

    # Explicit trigger-only assignments have the same held-input key as the
    # neutral base replay.  The first real held-input difference is therefore
    # patch 2's right input at frame 249; between patches 0 and 1 it is the
    # left-vs-right input at frame 250.
    assert all(candidate.feasible for candidate in result.candidates)
    assert result.best_patch_index == 1


def test_native_patch_trace_score_preserves_arbitrary_width_mask_penalties() -> None:
    frames = (InputFrame(),) * 3
    session = _session()
    unscored = session.evaluate_patches(
        frames,
        PatchEvaluationSpec(patches=_direction_patches(), target_frame=2),
    )
    player = unscored.candidates[0].player
    assert player is not None
    x, y = player["pos"]
    old_x, old_y = player["oldpos"]
    target = TraceTargetSpec(
        x=x,
        y=y,
        vx=x - old_x,
        vy=y - old_y,
        player_state=int(player["state"]),
        in_air=bool(player["in_air"]),
        near_wall=bool(player["near_wall"]),
        wall_x=0,
        floor_x=0,
        floor_y=0,
        previous_jump_held=bool(player["previous_jump_held"]),
        collected_gold_mask=1 << 70,
        exploded_mine_mask=1 << 71,
        open_exit_mask=1 << 72,
        opened_locked_door_mask=1 << 73,
        triggered_trapdoor_mask=1 << 74,
    )
    scored = session.evaluate_patches(
        frames,
        PatchEvaluationSpec(
            patches=_direction_patches(),
            target_frame=2,
            trace_target=target,
        ),
    )

    # 0.25 gold + 0.25 mine + 8 exit + 24 locked + 24 trapdoor.
    assert scored.candidates[0].score == 56.5

    policy_weighted = session.evaluate_patches(
        frames,
        PatchEvaluationSpec(
            patches=_direction_patches(),
            target_frame=2,
            trace_target=replace(
                target,
                position_weight=0.0,
                velocity_weight=0.0,
                contact_mismatch_penalty=0.0,
                in_air_mismatch_penalty=0.0,
                near_wall_mismatch_penalty=0.0,
                gold_bit_penalty=1.0,
                mine_bit_penalty=2.0,
                exit_bit_penalty=3.0,
                locked_door_bit_penalty=4.0,
                trapdoor_bit_penalty=5.0,
            ),
        ),
    )
    assert policy_weighted.candidates[0].score == 15.0


def test_native_patch_prunes_an_inactive_edge_introduced_in_fixed_suffix() -> None:
    frames = (InputFrame(jump=True),) * 3
    result = _session().evaluate_patches(
        frames,
        PatchEvaluationSpec(
            patches=((PatchAssignmentSpec(0, InputFrame()),),),
            target_frame=2,
            prune_inactive_jump=True,
        ),
    )

    assert result.candidates[0].inactive_jump_pruned
    assert not result.candidates[0].has_endpoint
    assert result.stats.inactive_jump_prunes == 1
    assert result.stats.simulated_ticks == 2

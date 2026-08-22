from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import nv14_auto as auto
from nv14_engine import InputFrame, parse_level_string
from nv14_replay import (
    decode_complex_replay,
    editable_frames,
    parse_combined_level_replay,
)


def test_v245_adaptive_repair_cow_requires_dormant_object_headroom() -> None:
    dormant = SimpleNamespace(
        objects=[object()] * 12,
        update_uids=[1, 2],
        thinker_uids=[3],
    )
    all_active = SimpleNamespace(
        objects=[object()] * 4,
        update_uids=[0, 1, 2, 3],
        thinker_uids=[],
    )

    assert auto._repair_copy_on_write_beneficial(dormant)
    assert not auto._repair_copy_on_write_beneficial(all_active)


def test_v245_semantic_jump_variants_materialise_only_requested_prefix() -> None:
    working = tuple(
        InputFrame(right=index % 2 == 0, jump=index in {2, 3, 7, 8, 9})
        for index in range(14)
    ) + (auto.NEUTRAL_INPUT,)
    config = auto.AutoConfig(
        iterations=0,
        max_jump_shift=3,
        max_jump_hold_delta=3,
        range_end=13,
    )

    complete = auto._semantic_jump_variants(working, config)
    limited = auto._semantic_jump_variants(working, config, limit=4)

    assert len(complete) > len(limited) == 4
    assert limited == complete[:4]


def test_v245_exact_direction_seed_skips_all_mutation_simulation() -> None:
    combined = parse_combined_level_replay(
        Path(__file__).with_name("example_44_0.txt").read_text(encoding="utf-8")
    )
    level = parse_level_string(
        combined.level_string,
        strict_shapes=True,
        simulate_enemies=True,
    )
    body = tuple(editable_frames(decode_complex_replay(combined.replay_string).frames))
    working = body + (auto.NEUTRAL_INPUT,)
    reference = auto._evaluate_working(level, working)

    repaired, branches, simulations = auto.repair_direction_window(
        level,
        working,
        reference,
        failure_tick=40,
        reference_offset=0,
        config=auto.AutoConfig(
            iterations=0,
            repair_window=3,
            repair_lookback=5,
            repair_local_limit=100,
            repair_search_order=auto.AUTO_REPAIR_SEARCH_ORDER_FIXED,
        ),
        require_failure_jump=False,
    )

    assert repaired is None
    assert branches == simulations == 0


def test_v245_adaptive_cow_and_deep_repair_return_identical_results(
    monkeypatch,
) -> None:
    combined = parse_combined_level_replay(
        Path(__file__).with_name("example_44_0.txt").read_text(encoding="utf-8")
    )
    level = parse_level_string(
        combined.level_string,
        strict_shapes=True,
        simulate_enemies=True,
    )
    body = tuple(editable_frames(decode_complex_replay(combined.replay_string).frames))
    working = body + (auto.NEUTRAL_INPUT,)
    reference = auto._evaluate_working(level, working)
    target_tick = 43
    shifted_trace = list(reference.trace)
    shifted_trace[target_tick] = replace(
        shifted_trace[target_tick],
        x=shifted_trace[target_tick].x + 24.0,
    )
    shifted_reference = replace(reference, trace=tuple(shifted_trace))
    config = auto.AutoConfig(
        iterations=0,
        repair_window=3,
        repair_lookback=5,
        repair_local_limit=100,
        repair_search_order=auto.AUTO_REPAIR_SEARCH_ORDER_FIXED,
    )

    monkeypatch.setattr(auto, "_repair_copy_on_write_beneficial", lambda _state: False)
    deep = auto.repair_direction_window(
        level,
        working,
        shifted_reference,
        failure_tick=40,
        reference_offset=0,
        config=config,
        require_failure_jump=False,
    )
    monkeypatch.setattr(auto, "_repair_copy_on_write_beneficial", lambda _state: True)
    cow = auto.repair_direction_window(
        level,
        working,
        shifted_reference,
        failure_tick=40,
        reference_offset=0,
        config=config,
        require_failure_jump=False,
    )

    assert cow == deep

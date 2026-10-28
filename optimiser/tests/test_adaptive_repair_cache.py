"""Regressions for bounded exact-search reuse and adaptive repair policy."""
from dataclasses import replace

import pytest

from nv14_auto import (
    AutoConfig, _repair_horizons, _repair_horizon_budget,
    _evaluate_working, repair_all_input_window,
)
from nv14_engine import InputFrame, parse_level_string
from nv14_search import NativeSearchSession, SearchSpec, OBJECTIVE_MAX_X, backend_info


def _level():
    if not backend_info().get("available"):
        pytest.skip("build native extension first")
    return parse_level_string("0" * (31 * 23) + "|5^100,100")


def _search():
    return SearchSpec(
        mutable_frames=(0, 1),
        choices=((InputFrame(left=True), InputFrame(right=True)),) * 2,
        target_frame=2, objective=OBJECTIVE_MAX_X, beam_width=3,
    )


def test_exact_result_cache_uses_whole_prefix_and_all_search_constraints():
    session = NativeSearchSession(_level())
    session.configure_result_cache(2)
    spec = _search()
    replay = (InputFrame(),) * 4
    first = session.search(replay, spec)
    assert first.stats.simulated_ticks > 0
    hit = session.search(replay, spec)
    assert hit.best_inputs == first.best_inputs
    assert hit.score == first.score
    assert hit.stats.cache_hits == 1
    assert hit.stats.simulated_ticks == hit.stats.visited_nodes == 0
    assert session.search_cache_hits == 1

    # Changes beyond the target cannot affect this search.
    after_target = (*replay[:3], InputFrame(jump=True))
    assert session.search(after_target, spec).stats.cache_hits == 1
    # Changes within the fixed prefix must invalidate the memo.
    changed_prefix = (InputFrame(right=True), *replay[1:])
    assert session.search(changed_prefix, spec).stats.cache_hits == 0
    # Also distinguish incumbent/objective/feasibility constraints.
    assert session.search(replay, replace(spec, incumbent_score=100.0)).stats.cache_hits == 0
    with pytest.raises(ValueError, match="capacity"):
        session.configure_result_cache(65)


def test_budget_exhausted_queries_not_cached():
    session = NativeSearchSession(_level())
    session.configure_result_cache(4)
    spec = replace(_search(), max_simulated_ticks=1)
    first = session.search((InputFrame(),) * 4, spec)
    second = session.search((InputFrame(),) * 4, spec)
    assert first.budget_exhausted
    assert second.stats.simulated_ticks > 0
    assert second.stats.cache_hits == 0


def test_cache_player_snapshot_is_not_mutable_across_calls():
    session = NativeSearchSession(_level())
    session.configure_result_cache(1)
    replay = (InputFrame(),) * 4
    spec = _search()
    first = session.search(replay, spec)
    assert first.player is not None
    correct_pos = first.player["pos"]
    first.player["pos"] = (-12345.0, 0.0)
    assert session.search(replay, spec).player["pos"] == correct_pos


def test_adaptive_input_order_affects_only_priority_not_legal_choices():
    session = NativeSearchSession(_level())
    inputs = (InputFrame(),) * 2
    spec = SearchSpec(
        mutable_frames=(0,), target_frame=0, objective=OBJECTIVE_MAX_X,
        choices=((InputFrame(left=True), InputFrame(right=True)),),
        beam_width=2, max_simulated_ticks=1, incumbent_score=-float("inf"),
    )
    plain = session.search(inputs, spec)
    guided = session.search(inputs, replace(spec, beam_adaptive_inputs=True))
    assert plain.budget_exhausted and guided.budget_exhausted
    assert plain.best_inputs[0].left
    assert guided.best_inputs[0].right
    full_plain = session.search(inputs, replace(spec, max_simulated_ticks=0))
    full_guided = session.search(inputs, replace(
        spec, max_simulated_ticks=0, beam_adaptive_inputs=True))
    assert full_plain.score == full_guided.score


def test_horizon_sequence_and_budget_split():
    assert _repair_horizons(9, False) == (9,)
    assert _repair_horizons(9, True) == (2, 4, 9)
    assert _repair_horizons(3, True) == (2, 3)
    assert _repair_horizons(1, True) == (1,)
    assert _repair_horizon_budget(0, 100, 2) == 0
    assert _repair_horizon_budget(100, 30, 2) == 35
    assert _repair_horizon_budget(10, 9, 2) == 1
    with pytest.raises(ValueError, match="repair_cache_entries"):
        AutoConfig(repair_cache_entries=65)


def test_adaptive_repair_respects_total_tick_allowance():
    level = _level()
    replay = (InputFrame(),) * 8
    baseline = _evaluate_working(level, replay, trace_stride=1)
    spent = []
    repair_all_input_window(
        level, replay, baseline, failure_tick=5, reference_offset=0,
        config=AutoConfig(repair_window=4, repair_adaptive_windows=True,
                          repair_local_limit=24, repair_beam_width=4,
                          repair_cache_entries=4),
        require_failure_jump=False,
        progress=lambda _branches, ticks: spent.append(ticks),
    )
    assert len(spent) == 1
    assert 0 < spent[0] <= 24

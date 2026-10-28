"""Opt-in native reward beam: exact replay safety and bounded exploration."""
from dataclasses import replace

import pytest

from nv14_engine import InputFrame, parse_level_string
from nv14_objectives import evaluate, objective_function
from nv14_search import (
    OBJECTIVE_MAX_X,
    NativeSearchSession,
    SearchSpec,
    backend_info,
)
from nv14_auto import AutoConfig


def _session():
    if not backend_info().get("available"):
        pytest.skip("native extension not built")
    return parse_level_string("0" * (31 * 23) + "|5^100,100")


def _scenario():
    replay = (InputFrame(),) * 4
    choices = ((InputFrame(), InputFrame(left=True), InputFrame(right=True)),) * 3
    return replay, SearchSpec(
        mutable_frames=(0, 1, 2),
        choices=choices,
        target_frame=3,
        objective=OBJECTIVE_MAX_X,
        incumbent_score=-float("inf"),
        beam_width=2,
        beam_adaptive_inputs=True,
        beam_edit_penalty=0.001,
    )


def _replayed(level, replay, spec, result):
    changed = list(replay)
    for frame, value in zip(spec.mutable_frames, result.best_inputs, strict=True):
        changed[frame] = value
    return evaluate(level, changed, spec.target_frame, objective_function("max-x"))


def test_beam_finds_verified_endpoint_and_is_deterministic():
    level = _session()
    replay, spec = _scenario()
    session = NativeSearchSession(level)
    result = session.search(replay, spec)
    repeat = session.search(replay, spec)
    assert result.improved and result.feasible
    assert result.best_inputs == repeat.best_inputs
    assert result.score == repeat.score
    assert result.stats.beam_width_prunes > 0
    endpoint = _replayed(level, replay, spec, result)
    assert endpoint.feasible
    assert result.score == endpoint.score
    assert result.player["pos"] == (endpoint.state.player.pos.x,
                                    endpoint.state.player.pos.y)


def test_beam_deduplicates_identical_successors():
    level = _session()
    replay = (InputFrame(),) * 3
    spec = SearchSpec(
        mutable_frames=(0, 1),
        choices=((InputFrame(right=True), InputFrame(right=True), InputFrame()),
                 (InputFrame(right=True), InputFrame(right=True), InputFrame())),
        target_frame=2,
        objective=OBJECTIVE_MAX_X,
        beam_width=8,
    )
    result = NativeSearchSession(level).search(replay, spec)
    assert result.improved
    assert result.stats.deduplicated_prunes > 0
    assert result.score == _replayed(level, replay, spec, result).score


def test_beam_respects_budget_and_exact_terminal_window():
    level = _session()
    replay, spec = _scenario()
    session = NativeSearchSession(level)
    limited = session.search(replay, replace(spec, max_simulated_ticks=2))
    assert limited.budget_exhausted
    assert limited.stats.simulated_ticks == 2
    impossible = session.search(replay, replace(
        spec, x_window=(100000.0, 100001.0),
    ))
    assert not impossible.improved


def test_beam_width_zero_retains_dfs_results():
    level = _session()
    replay, spec = _scenario()
    session = NativeSearchSession(level)
    result = session.search(replay, replace(spec, beam_width=0))
    assert result.improved
    assert result.stats.beam_width_prunes == 0
    assert result.score == _replayed(level, replay, spec, result).score


def test_public_policy_validation():
    replay, spec = _scenario()
    with pytest.raises(ValueError, match="beam width"):
        replace(spec, beam_width=4097)
    with pytest.raises(ValueError, match="edit penalty"):
        replace(spec, beam_edit_penalty=-0.1)
    with pytest.raises(ValueError, match="repair_beam_width"):
        AutoConfig(repair_beam_width=4097)
    assert AutoConfig().repair_beam_width == 0


def test_auto_opt_in_smoke():
    from nv14_auto import optimise_autonomous, verify_trimmed_replay
    chars = ["0"] * (31 * 23)
    for x in range(31):
        chars[x * 23 + 5] = "1"
    level = parse_level_string(
        "".join(chars) + "|5^60,134!11^140,134,60,134"
    )
    replay = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    result = optimise_autonomous(
        level, replay, AutoConfig(
            iterations=1, beam_width=3, repair_beam_width=4,
            repair_local_limit=200, deterministic_phase=False,
            max_retime=1, seed=123,
        )
    )
    assert result.finish_tick <= result.baseline_finish_tick
    assert verify_trimmed_replay(level, result.frames).valid

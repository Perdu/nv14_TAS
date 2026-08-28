from __future__ import annotations

import inspect
import os
import select
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from threading import Event

import pytest

import nv14_jump
import nv14_search
from nv14_engine import InputFrame, parse_level_string
from nv14_jump import JumpPulse, apply_jump_pattern, optimise_jump_patterns
from nv14_objectives import (
    AxisWindow,
    Evaluation,
    TargetGeometry,
    TargetSelection,
    evaluate,
    objective_function,
    state_before_frame,
)
from nv14_replay import decode_complex_replay, parse_combined_level_replay
from nv14_search import (
    OBJECTIVE_MAX_X,
    OBJECTIVE_MIN_DISTANCE,
    PatternSearchSpec,
    REQUIRED_START_EVENT_JUMPED,
    NativeSearchSession,
)


HERE = Path(__file__).parent


def _load_record(name: str, *, simulate_enemies: bool = False):
    combined = parse_combined_level_replay(
        (HERE / name).read_text(encoding="utf-8")
    )
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(
        combined.level_string,
        simulate_enemies=simulate_enemies,
    )
    return replay, level


def _native_session_or_skip(level) -> NativeSearchSession:
    info = nv14_search.backend_info()
    if not info.get("available"):
        pytest.skip(
            f"native replay-search kernel is unavailable: {info.get('error')}"
        )
    if not callable(getattr(NativeSearchSession, "search_patterns", None)):
        pytest.skip("installed native search facade has no pattern-search API")
    try:
        return NativeSearchSession(level)
    except RuntimeError as exc:
        pytest.skip(f"native pattern-search kernel is unavailable: {exc}")


def _pulse_signature(result) -> tuple[tuple[int, int], ...]:
    return tuple(
        (pulse.start_frame, pulse.hold_length) for pulse in result.pulses
    )


def _point_target(x: float, y: float) -> TargetSelection:
    return TargetSelection(
        "test-point",
        (TargetGeometry("test-point", x, y),),
    )


@pytest.mark.parametrize(
    (
        "objective_name",
        "objective_target",
        "expected_pulses",
        "expected_score",
        "expected_position",
    ),
    (
        (
            "max-x",
            None,
            ((116, 1), (122, 1)),
            317.31238133675305,
            (317.31238133675305, 371.54175653911926),
        ),
        (
            "min-x",
            None,
            ((110, 2), (123, 1)),
            -309.4458990362985,
            (309.4458990362985, 342.00121284739515),
        ),
        (
            "max-y",
            None,
            ((117, 1), (123, 1)),
            379.92504846460497,
            (317.12121307628814, 379.92504846460497),
        ),
        (
            "min-y",
            None,
            ((110, 4), (123, 1)),
            -340.0346541748942,
            (309.4458990362985, 340.0346541748942),
        ),
        (
            "min-distance",
            _point_target(300.0, 340.0),
            ((110, 4), (123, 1)),
            -89.22620951578251,
            (309.4458990362985, 340.0346541748942),
        ),
    ),
)
def test_native_jump_search_matches_v275_objective_goldens(
    objective_name: str,
    objective_target: TargetSelection | None,
    expected_pulses: tuple[tuple[int, int], ...],
    expected_score: float,
    expected_position: tuple[float, float],
) -> None:
    replay, level = _load_record("example_ditched_supplied.txt")
    _native_session_or_skip(level)

    results = optimise_jump_patterns(
        level,
        replay.frames,
        target_frame=123,
        range_start=106,
        range_end=123,
        objective_name=objective_name,
        objective_target=objective_target,
        jump_count_min=2,
        jump_count_max=2,
        jump_length_min=1,
        jump_length_max=4,
        top_results=1,
        workers=1,
        progress=None,
    )

    assert len(results) == 1
    assert _pulse_signature(results[0]) == expected_pulses
    assert results[0].score == expected_score
    assert (
        results[0].evaluation.state.player.pos.x,
        results[0].evaluation.state.player.pos.y,
    ) == expected_position


def test_native_pattern_result_has_exact_python_score_player_and_stats_parity(
) -> None:
    replay, level = _load_record("example_ditched_supplied.txt")
    session = _native_session_or_skip(level)
    range_start = 106
    range_end = 123
    maximum_length = 4
    inactive_inputs = tuple(
        InputFrame(
            replay.frames[index].left,
            replay.frames[index].right,
            False,
            None,
        )
        for index in range(range_start, range_end + 1)
    )
    active_inputs = tuple(
        InputFrame(
            replay.frames[index].left,
            replay.frames[index].right,
            True,
            None,
        )
        for index in range(range_start, range_end + 1)
    )
    target = _point_target(300.0, 340.0)
    spec = PatternSearchSpec(
        range_start=range_start,
        range_end=range_end,
        inactive_inputs=inactive_inputs,
        active_inputs=active_inputs,
        target_frame=123,
        objective=OBJECTIVE_MIN_DISTANCE,
        targets=((300.0, 340.0),),
        run_count_min=2,
        run_count_max=2,
        run_length_min=1,
        start_max_lengths=tuple(
            min(maximum_length, range_end - frame + 1)
            for frame in range(range_start, range_end + 1)
        ),
        minimum_gap=1,
        fixed_starts=(),
        required_start_event_mask=REQUIRED_START_EVENT_JUMPED,
        top_results=3,
    )

    result = session.search_patterns(replay.frames, spec)

    assert len(result.candidates) == 3
    assert result.candidates[0].spans == ((110, 4), (123, 1))
    assert result.candidates[0].score == -89.22620951578251
    for native_candidate in result.candidates:
        pulses = tuple(JumpPulse(*span) for span in native_candidate.spans)
        candidate_frames = apply_jump_pattern(
            replay.frames,
            range_start=range_start,
            range_end=range_end,
            pulses=pulses,
        )
        verified = evaluate(
            level,
            candidate_frames,
            123,
            objective_function("min-distance", target),
        )
        player = verified.state.player

        assert native_candidate.score == verified.score
        assert native_candidate.player is not None
        assert native_candidate.player["pos"] == (player.pos.x, player.pos.y)
        assert native_candidate.player["oldpos"] == (
            player.oldpos.x,
            player.oldpos.y,
        )
        assert native_candidate.player["state"] == int(player.state)
        assert native_candidate.player["jump_events"] == player.jump_events
        assert native_candidate.player["dead"] == player.dead

    assert result.stats.attempted_starts == 387
    assert result.stats.successful_starts == 69
    assert result.stats.evaluated_candidates == 92
    assert result.stats.deduplicated_branches == 0
    assert result.stats.simulated_ticks > 0
    assert result.stats.cloned_states > 0


def test_native_pattern_pre_set_cancel_event_stops_a_large_search() -> None:
    replay, level = _load_record("example_motherlode.txt")
    session = _native_session_or_skip(level)
    range_start = 0
    range_end = 200
    maximum_length = 20
    inactive_inputs = tuple(
        InputFrame(
            replay.frames[index].left,
            replay.frames[index].right,
            False,
            None,
        )
        for index in range(range_start, range_end + 1)
    )
    active_inputs = tuple(
        InputFrame(
            replay.frames[index].left,
            replay.frames[index].right,
            True,
            None,
        )
        for index in range(range_start, range_end + 1)
    )
    spec = PatternSearchSpec(
        range_start=range_start,
        range_end=range_end,
        inactive_inputs=inactive_inputs,
        active_inputs=active_inputs,
        target_frame=range_end,
        objective=OBJECTIVE_MAX_X,
        run_count_min=3,
        run_count_max=4,
        run_length_min=1,
        start_max_lengths=tuple(
            min(maximum_length, range_end - frame + 1)
            for frame in range(range_start, range_end + 1)
        ),
        minimum_gap=1,
        fixed_starts=(),
        required_start_event_mask=REQUIRED_START_EVENT_JUMPED,
        top_results=10,
    )
    cancel_event = Event()
    cancel_event.set()

    with pytest.raises(KeyboardInterrupt):
        session.search_patterns(replay.frames, spec, cancel_event)


@pytest.mark.skipif(
    os.name == "nt",
    reason="portable SIGINT delivery to a piped subprocess is POSIX-specific",
)
def test_threaded_native_jump_search_exits_promptly_after_sigint() -> None:
    info = nv14_search.backend_info()
    if not info.get("available"):
        pytest.skip(
            f"native replay-search kernel is unavailable: {info.get('error')}"
        )

    script = textwrap.dedent(
        """
        from pathlib import Path

        from nv14_engine import parse_level_string
        from nv14_jump import optimise_jump_patterns
        from nv14_replay import decode_complex_replay, parse_combined_level_replay

        combined = parse_combined_level_replay(
            Path("tests/example_motherlode.txt").read_text(encoding="utf-8")
        )
        replay = decode_complex_replay(combined.replay_string)
        level = parse_level_string(combined.level_string)
        try:
            optimise_jump_patterns(
                level,
                replay.frames,
                target_frame=300,
                range_start=0,
                range_end=300,
                objective_name="max-x",
                jump_count_min=4,
                jump_count_max=5,
                jump_length_min=1,
                jump_length_max=30,
                top_results=10,
                workers=2,
                progress=lambda message: print(message, flush=True),
            )
        except KeyboardInterrupt:
            print("INTERRUPTED", flush=True)
            raise SystemExit(130)
        raise SystemExit("long native search unexpectedly completed")
        """
    )
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=HERE.parent,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert process.stdout is not None
    prefix_output: list[str] = []

    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(
                    "long native search exited before SIGINT: "
                    f"rc={process.returncode}, stdout={''.join(prefix_output) + stdout!r}, "
                    f"stderr={stderr!r}"
                )
            readable, _writable, _exceptional = select.select(
                [process.stdout], [], [], 0.1
            )
            if not readable:
                continue
            line = process.stdout.readline()
            prefix_output.append(line)
            if "2 native worker threads" in line:
                break
        else:
            pytest.fail("native worker threads did not start within 10 seconds")

        # The progress line is emitted immediately before the worker pool is
        # populated. Give both C shards time to enter the deliberately large
        # search, then ensure the workload is still live before interrupting.
        time.sleep(0.5)
        assert process.poll() is None, "long native workload was not long enough"
        process.send_signal(signal.SIGINT)
        try:
            stdout, stderr = process.communicate(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=2.0)
            pytest.fail(
                "threaded native jump search hung after SIGINT; "
                f"stdout={''.join(prefix_output) + stdout!r}, stderr={stderr!r}"
            )
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=2.0)

    output = "".join(prefix_output) + stdout
    assert process.returncode == 130, (output, stderr)
    assert "INTERRUPTED" in output


def test_native_pattern_on_completed_level_matches_reference_full_steps() -> None:
    replay, level = _load_record("example_ditched_supplied.txt")
    session = _native_session_or_skip(level)
    # The supplied replay completes on its first neutral sentinel. Search only
    # after that tick so both inactive and active alternatives begin from an
    # already-completed native state.
    frames = tuple(replay.frames) + (InputFrame(),) * 8
    range_start = len(replay.frames) + 1
    range_end = range_start + 2
    target_frame = range_end + 2
    prefix = state_before_frame(level, frames, range_start)
    assert prefix.level_complete

    spec = PatternSearchSpec(
        range_start=range_start,
        range_end=range_end,
        inactive_inputs=(InputFrame(),) * 3,
        active_inputs=(InputFrame(jump=True),) * 3,
        target_frame=target_frame,
        objective=OBJECTIVE_MAX_X,
        run_count_min=1,
        run_count_max=1,
        run_length_min=1,
        start_max_lengths=(1, 1, 1),
        minimum_gap=1,
        fixed_starts=(),
        # This exercises the generic pattern primitive rather than requiring
        # the active edge to report Player.jump().
        required_start_event_mask=0,
        top_results=3,
    )

    result = session.search_patterns(frames, spec)
    reference: dict[tuple[tuple[int, int], ...], Evaluation] = {}
    for start in range(range_start, range_end + 1):
        spans = ((start, 1),)
        candidate_frames = apply_jump_pattern(
            frames,
            range_start=range_start,
            range_end=range_end,
            pulses=(JumpPulse(start, 1),),
        )
        reference[spans] = evaluate(
            level,
            candidate_frames,
            target_frame,
            objective_function("max-x"),
        )

    assert tuple(candidate.spans for candidate in result.candidates) == tuple(
        reference
    )
    assert result.stats.attempted_starts == 3
    assert result.stats.successful_starts == 3
    assert result.stats.evaluated_candidates == 3
    for candidate in result.candidates:
        verified = reference[candidate.spans]
        player = verified.state.player
        assert verified.state.level_complete
        assert candidate.score == verified.score
        assert candidate.player is not None
        assert candidate.player["pos"] == (player.pos.x, player.pos.y)
        assert candidate.player["oldpos"] == (
            player.oldpos.x,
            player.oldpos.y,
        )
        assert candidate.player["state"] == int(player.state)
        assert candidate.player["jump_events"] == player.jump_events
        assert candidate.player["dead"] == player.dead


def test_native_jump_search_fixed_start_matches_v275_golden() -> None:
    replay, level = _load_record("example_ditched_supplied.txt")
    _native_session_or_skip(level)
    logs: list[str] = []

    results = optimise_jump_patterns(
        level,
        replay.frames,
        target_frame=123,
        range_start=106,
        range_end=123,
        objective_name="min-x",
        jump_count_min=1,
        jump_count_max=1,
        jump_length_min=1,
        jump_length_max=6,
        fixed_jump_frames=(112,),
        top_results=6,
        workers=1,
        progress=logs.append,
    )

    assert _pulse_signature(results[0]) == ((112, 1),)
    assert results[0].score == -313.52131048916664
    assert {_pulse_signature(item) for item in results} == {
        ((112, length),) for length in range(1, 7)
    }
    assert any(
        "attempted 7 starts, 6 produced Player.jump(), "
        "evaluated 6 terminal states, deduplicated 0 branches" in line
        for line in logs
    )


def test_native_jump_search_enemy_enabled_matches_v275_ranked_golden() -> None:
    replay, level = _load_record("example_44_0.txt", simulate_enemies=True)
    _native_session_or_skip(level)

    results = optimise_jump_patterns(
        level,
        replay.frames,
        target_frame=100,
        range_start=0,
        range_end=30,
        objective_name="max-x",
        jump_count_min=1,
        jump_count_max=2,
        jump_length_min=1,
        jump_length_max=4,
        top_results=5,
        workers=1,
        progress=None,
    )

    assert [(_pulse_signature(item), item.score) for item in results] == [
        (((27, 4),), 646.8290442024818),
        (((29, 2),), 646.7126939817883),
        (((28, 3),), 644.4821757090892),
        (((30, 1),), 644.1509932354736),
        (((26, 4),), 639.9398266600318),
    ]


def test_native_jump_search_honours_inclusive_windows_and_infeasibility() -> None:
    replay, level = _load_record("example_ditched_supplied.txt")
    _native_session_or_skip(level)
    common = dict(
        target_frame=123,
        range_start=106,
        range_end=123,
        objective_name="min-distance",
        objective_target=_point_target(300.0, 340.0),
        jump_count_min=2,
        jump_count_max=2,
        jump_length_min=1,
        jump_length_max=4,
        top_results=1,
        workers=1,
        progress=None,
    )

    accepted = optimise_jump_patterns(
        level,
        replay.frames,
        x_window=AxisWindow(309.4458990362985, 309.4458990362985),
        **common,
    )
    rejected = optimise_jump_patterns(
        level,
        replay.frames,
        x_window=AxisWindow(0.0, 300.0),
        **common,
    )

    assert _pulse_signature(accepted[0]) == ((110, 4), (123, 1))
    assert rejected == []


def test_jump_module_contains_policy_only_not_a_python_search_dfs() -> None:
    source = inspect.getsource(nv14_jump)

    assert "class _JumpPatternSearch" not in source
    assert "def recurse" not in source
    assert "copy_on_write_objects" not in source
    assert ".state_key()" not in source
    assert ".step(" not in source
    assert "PatternSearchSpec" in source
    assert "search_patterns" in source


def test_stale_v275_native_search_extension_has_actionable_build_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StaleSearchModule:
        __file__ = "/synthetic/_nv14_search.so"

        class SearchSession:
            def __init__(self, *_args, **_kwargs):
                raise AssertionError("stale session must be rejected by ABI check")

        @staticmethod
        def backend_info():
            return {"wrapper_api": 1, "search_abi": 1, "core_abi": 2}

    monkeypatch.setattr(nv14_search, "_search_native", StaleSearchModule())
    monkeypatch.setattr(nv14_search, "_SEARCH_LOAD_ERROR", None)

    info = nv14_search.backend_info()
    assert info["available"] is False
    assert info["backend"] == "incompatible"
    assert "got 1/1/2" in str(info["error"])
    with pytest.raises(RuntimeError, match=r"python build_native\.py"):
        NativeSearchSession(parse_level_string("0" * (31 * 23) + "|5^100,100"))

from __future__ import annotations

import ast
from dataclasses import replace
import gc
import inspect
import math
import pickle
import textwrap
from collections.abc import Sequence
from pathlib import Path

import pytest

import nv14_auto as auto
from nv14_engine import (
    InputFrame,
    Level,
    TestDoor as EngineTestDoor,
    UnsupportedTileCollision,
    door_control_masks,
    parse_level_string,
)
from nv14_replay import (
    decode_complex_replay,
    editable_frames,
    parse_combined_level_replay,
)
from nv14_search import NativeSearchSession, backend_info, require_native_search


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EMPTY_MAP = "0" * (31 * 23)
NEUTRAL = InputFrame()


def _require_native_auto() -> None:
    info = backend_info()
    if not info.get("available") or int(info.get("wrapper_api", 0)) < 3:
        pytest.skip(f"native Auto evaluator is unavailable: {info.get('error')}")


def _set_bits(mask: int):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def _python_point(
    state,
    tick: int,
    opened_locked_door_mask: int,
    triggered_trapdoor_mask: int,
) -> auto.CompactTracePoint:
    player = state.player
    static = state.static_state

    def sign_bin(value: float) -> int:
        return -1 if value < -1e-9 else 1 if value > 1e-9 else 0

    return auto.CompactTracePoint(
        tick=tick,
        x=player.pos.x,
        y=player.pos.y,
        vx=player.vx,
        vy=player.vy,
        player_state=int(player.state),
        in_air=player.in_air,
        near_wall=player.near_wall,
        wall_x=sign_bin(player.wall_n.x),
        floor_x=sign_bin(player.floor_n.x),
        floor_y=sign_bin(player.floor_n.y),
        previous_jump_held=player.previous_jump_held,
        jump_events=player.jump_events,
        collected_gold_mask=static.collected_gold_mask,
        exploded_mine_mask=static.exploded_mine_mask,
        open_exit_mask=static.open_exit_mask,
        opened_locked_door_mask=opened_locked_door_mask,
        triggered_trapdoor_mask=triggered_trapdoor_mask,
        complete=state.level_complete,
        dead=player.dead,
        gold_bonus_ticks=static.gold_bonus_ticks,
    )


def _python_reference_evaluation(
    level: Level,
    working_frames: Sequence[InputFrame],
    *,
    trace_stride: int,
) -> auto.AutoEvaluation:
    """Independent reference implementation of the removed Python tick loop."""
    state = level.initial_state()
    tracks_doors = any(
        type(obj) is EngineTestDoor and (obj.is_locked or obj.is_trap)
        for obj in state.objects
    )
    opened_locked_mask = 0
    triggered_trap_mask = 0
    if tracks_doors:
        opened_locked_mask, triggered_trap_mask = door_control_masks(state)

    trace: list[auto.CompactTracePoint] = []
    successful_jumps: list[int] = []
    jump_edges: list[int] = []
    missed_jump_edges: list[int] = []
    gold_events: list[auto.GoldCollectionEvent] = []
    route_events: list[auto.RouteControlEvent] = []
    previous_jump = False
    finish_tick: int | None = None
    dead_tick: int | None = None
    last_tick = -1
    unsupported = False
    pre_finish_exit_distance: float | None = None

    for tick, frame in enumerate(working_frames):
        pre_step_x = state.player.pos.x
        pre_step_y = state.player.pos.y
        edge = frame.jump and not previous_jump
        if edge:
            jump_edges.append(tick)
        before_jumps = state.player.jump_events
        before_gold = state.static_state.collected_gold_mask
        before_exit = state.static_state.open_exit_mask
        before_locked = opened_locked_mask
        before_trap = triggered_trap_mask
        try:
            state.step(frame, level.tiles)
        except UnsupportedTileCollision:
            if tracks_doors:
                opened_locked_mask, triggered_trap_mask = door_control_masks(state)
            unsupported = True
            last_tick = tick
            break

        for index in _set_bits(
            state.static_state.collected_gold_mask & ~before_gold
        ):
            gold_events.append(auto.GoldCollectionEvent(index, tick))
        for index in _set_bits(state.static_state.open_exit_mask & ~before_exit):
            route_events.append(auto.RouteControlEvent("exit", index, tick))
        if tracks_doors:
            opened_locked_mask, triggered_trap_mask = door_control_masks(state)
        for index in _set_bits(opened_locked_mask & ~before_locked):
            route_events.append(
                auto.RouteControlEvent("locked-door", index, tick)
            )
        for index in _set_bits(triggered_trap_mask & ~before_trap):
            route_events.append(auto.RouteControlEvent("trapdoor", index, tick))

        jumped = state.player.jump_events > before_jumps
        if jumped:
            successful_jumps.append(tick)
        elif edge:
            missed_jump_edges.append(tick)
        previous_jump = frame.jump
        last_tick = tick

        point = _python_point(
            state,
            tick,
            opened_locked_mask,
            triggered_trap_mask,
        )
        if (
            tick % trace_stride == 0
            or point.complete
            or point.dead
            or tick == len(working_frames) - 1
        ):
            trace.append(point)
        if state.player.dead:
            dead_tick = tick
        if state.level_complete:
            finish_tick = tick
            completed_exit_index = state.static_state.completed_exit_index
            if completed_exit_index is not None:
                door = level.static_world.entry_for_ref(
                    level.static_world.exit_door_ref(completed_exit_index)
                )
                if door is not None:
                    distance = math.hypot(
                        door.x - pre_step_x,
                        door.y - pre_step_y,
                    )
                    if math.isfinite(distance):
                        pre_finish_exit_distance = distance
            break
        if state.player.dead:
            break

    return auto.AutoEvaluation(
        finish_tick=finish_tick,
        dead_tick=dead_tick,
        last_tick=last_tick,
        trace=tuple(trace),
        successful_jumps=tuple(successful_jumps),
        jump_edges=tuple(jump_edges),
        missed_jump_edges=tuple(missed_jump_edges),
        unsupported=unsupported,
        final_gold_mask=state.static_state.collected_gold_mask,
        gold_bonus_ticks=state.static_state.gold_bonus_ticks,
        gold_events=tuple(gold_events),
        final_opened_locked_door_mask=opened_locked_mask,
        final_triggered_trapdoor_mask=triggered_trap_mask,
        route_control_events=tuple(route_events),
        completed_exit_index=state.static_state.completed_exit_index,
        pre_finish_exit_distance=pre_finish_exit_distance,
    )


def _python_jump_opportunity_windows(
    level: Level,
    working_frames: Sequence[InputFrame],
) -> tuple[tuple[int, int], ...]:
    """Independently probe whether a forced fresh edge would call ``jump()``."""
    state = level.initial_state()
    windows: list[list[int]] = []
    for tick, frame in enumerate(working_frames):
        alternate = state.step(
            frame,
            level.tiles,
            alternate_inputs=InputFrame(
                frame.left,
                frame.right,
                True,
                True,
            ),
        )
        if alternate is not None:
            if not windows or tick != windows[-1][1] + 1:
                windows.append([tick, tick])
            else:
                windows[-1][1] = tick
        if state.player.dead or state.level_complete:
            break
    return tuple((start, end) for start, end in windows)


def _load_bundled_replay(relative_path: str) -> tuple[Level, tuple[InputFrame, ...]]:
    combined = parse_combined_level_replay(
        (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
    )
    level = parse_level_string(
        combined.level_string,
        strict_shapes=True,
        simulate_enemies=True,
    )
    return level, tuple(decode_complex_replay(combined.replay_string).frames)


def _load_benchmark_replay(
    declared_tick: int,
) -> tuple[Level, tuple[InputFrame, ...]]:
    prefix = f"{declared_tick}: "
    rows = (PROJECT_ROOT / "examples/benchmark/Improved_TASes.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    record = next(row[len(prefix) :] for row in rows if row.startswith(prefix))
    combined = parse_combined_level_replay(record)
    level = parse_level_string(
        combined.level_string,
        strict_shapes=True,
        simulate_enemies=True,
    )
    return level, tuple(decode_complex_replay(combined.replay_string).frames)


@pytest.mark.parametrize(
    ("relative_path", "trace_stride"),
    (
        ("examples/replays/example_motherlode.txt", 7),
        ("tests/example_44_0.txt", 1),
    ),
)
def test_native_auto_evaluation_exactly_matches_python_engine_reference(
    relative_path: str,
    trace_stride: int,
) -> None:
    _require_native_auto()
    level, frames = _load_bundled_replay(relative_path)
    working = tuple(editable_frames(frames)) + (NEUTRAL,)

    native = auto.evaluate_replay_with_sentinel(
        level,
        frames,
        trace_stride=trace_stride,
    )
    reference = _python_reference_evaluation(
        level,
        working,
        trace_stride=trace_stride,
    )

    assert native == reference
    assert native.valid
    assert native.successful_jumps
    assert native.jump_edges
    assert native.gold_events
    assert any(event.kind == "exit" for event in native.route_control_events)
    if trace_stride > 1:
        expected_ticks = tuple(range(0, native.finish_tick + 1, trace_stride))
        if expected_ticks[-1] != native.finish_tick:
            expected_ticks += (native.finish_tick,)
        assert tuple(point.tick for point in native.trace) == expected_ticks


def test_native_step_result_and_analysis_expose_exact_jump_opportunities() -> None:
    _require_native_auto()
    level, frames = _load_bundled_replay("examples/replays/example_motherlode.txt")
    working = tuple(editable_frames(frames)) + (NEUTRAL,)
    native_module = require_native_search()
    floor_map = list(EMPTY_MAP)
    for column in range(31):
        floor_map[column * 23 + 5] = "1"
    native_state = native_module.parse_level_string(
        "".join(floor_map) + "|5^60,134",
    ).initial_state()

    neutral = native_state.step(False, False, False, False)
    triggered = native_state.step(False, False, True, True)
    held = native_state.step(False, False, True, False)

    assert neutral["jump_callable"] is True
    assert triggered["jump_callable"] is True
    assert triggered["jumped"] is True
    assert held["jump_callable"] is False

    analysis = NativeSearchSession(level).evaluate_replay(
        working,
        trace_stride=7,
    )
    expected = _python_jump_opportunity_windows(level, working)

    # The opportunity data is dense even though ordinary trace points are not.
    assert analysis.jump_opportunity_windows() == expected
    assert len(analysis.jump_opportunity_windows()) > 1
    assert analysis.to_dict()["jump_opportunity_windows"] == expected


def test_native_auto_decoder_preserves_wide_gold_and_door_masks() -> None:
    _require_native_auto()
    padding = "!".join("0^500,500" for _ in range(70))
    objects = (
        f"{padding}!0^90,84"
        "!9^90,84,0,0,10,3,1,0,0"
        "!9^90,84,0,1,11,3,0,0,0"
        "!5^90,84"
    )
    level = parse_level_string(f"{EMPTY_MAP}|{objects}")
    frames = (NEUTRAL,)
    working = frames + (NEUTRAL,)

    native = auto.evaluate_replay_with_sentinel(level, frames)
    reference = _python_reference_evaluation(level, working, trace_stride=1)

    assert native == reference
    assert native.final_gold_mask == 1 << 70
    assert native.final_opened_locked_door_mask == 1 << 71
    assert native.final_triggered_trapdoor_mask == 1 << 72
    assert native.gold_events == (auto.GoldCollectionEvent(70, 1),)
    assert native.route_control_events == (
        auto.RouteControlEvent("trapdoor", 72, 0),
        auto.RouteControlEvent("locked-door", 71, 1),
    )
    assert native.trace[0].triggered_trapdoor_mask == 1 << 72
    assert native.trace[1].collected_gold_mask == 1 << 70
    assert native.trace[1].opened_locked_door_mask == 1 << 71


def test_native_auto_preserves_completion_and_death_on_the_same_tick() -> None:
    _require_native_auto()
    level = parse_level_string(
        f"{EMPTY_MAP}|5^115,100!12^115,100!11^115,100,115,100"
    )
    frames = (NEUTRAL,)

    native = auto.evaluate_replay_with_sentinel(level, frames)
    reference = _python_reference_evaluation(
        level,
        frames + (NEUTRAL,),
        trace_stride=1,
    )

    assert native == reference
    assert native.finish_tick == native.dead_tick == 1
    assert native.trace[-1].complete
    assert native.trace[-1].dead
    assert native.valid


def test_auto_evaluator_contains_no_python_simulation_loop() -> None:
    source = textwrap.dedent(inspect.getsource(auto._evaluate_working))
    tree = ast.parse(source)
    attribute_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "evaluate_replay" in attribute_calls
    assert "step" not in attribute_calls
    assert "initial_state" not in attribute_calls


def test_native_analysis_stays_lazy_until_a_point_is_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_native_auto()
    level, frames = _load_bundled_replay("tests/example_44_0.txt")
    working = tuple(editable_frames(frames)) + (NEUTRAL,)
    session = NativeSearchSession(level)
    analysis = session.evaluate_replay(working)
    native = require_native_search()

    assert isinstance(analysis, native.NativeReplayAnalysis)
    assert not isinstance(analysis, dict)
    assert int(analysis.trace_count) > 300

    created = 0
    point_type = auto.CompactTracePoint

    def counted_point(*args, **kwargs):
        nonlocal created
        created += 1
        return point_type(*args, **kwargs)

    monkeypatch.setattr(auto, "CompactTracePoint", counted_point)
    evaluation = auto.evaluate_replay_with_sentinel(level, frames)

    assert created == 0
    assert evaluation == evaluation
    assert evaluation.valid
    assert evaluation._terminal_summary() is not None
    assert auto.find_baseline_alignment(evaluation, evaluation) is None
    assert created == 0
    with pytest.raises(TypeError):
        evaluation.trace[1.5]

    point = evaluation.point(100)
    assert isinstance(point, point_type)
    assert point.tick == 100
    assert created == 1

    materialised = evaluation.materialize_trace()
    assert len(materialised) == len(evaluation.trace)
    assert created == 1 + len(evaluation.trace)

    # The result owns its buffers independently of the SearchSession.
    del session
    gc.collect()
    assert analysis.point(100)[0] == 100


@pytest.mark.parametrize(
    ("objective", "max_negative_alignment"),
    ((auto.AUTO_OBJECTIVE_SPEEDRUN, 0), (auto.AUTO_OBJECTIVE_HIGHSCORE, 80)),
)
def test_native_alignment_scan_matches_materialised_python_fallback(
    objective: str,
    max_negative_alignment: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_native_auto()
    candidate_level, candidate_frames = _load_benchmark_replay(342)
    baseline_level, baseline_frames = _load_benchmark_replay(343)
    candidate = auto.evaluate_replay_with_sentinel(
        candidate_level, candidate_frames
    )
    baseline = auto.evaluate_replay_with_sentinel(baseline_level, baseline_frames)

    created = 0
    point_type = auto.CompactTracePoint

    def counted_point(*args, **kwargs):
        nonlocal created
        created += 1
        return point_type(*args, **kwargs)

    monkeypatch.setattr(auto, "CompactTracePoint", counted_point)
    native_match = auto.find_baseline_alignment(
        candidate,
        baseline,
        max_alignment=3,
        max_negative_alignment=max_negative_alignment,
        objective=objective,
    )
    assert created == 0
    assert native_match == auto.AlignmentMatch(
        candidate_tick=341,
        reference_tick=342,
        offset=1,
        distance=pytest.approx(0.07448999630361518),
        contact_matches=True,
        static_matches=True,
        score_lead=1,
    )

    material_candidate = replace(candidate, trace=tuple(candidate.trace))
    material_baseline = replace(baseline, trace=tuple(baseline.trace))
    python_match = auto.find_baseline_alignment(
        material_candidate,
        material_baseline,
        max_alignment=3,
        max_negative_alignment=max_negative_alignment,
        objective=objective,
    )
    assert native_match == python_match


def test_native_alignment_distance_is_bit_exact_with_python_float_power() -> None:
    _require_native_auto()
    level, frames = _load_benchmark_replay(343)
    changed = list(frames)
    changed[176] = InputFrame(left=True, jump=True)
    changed[189] = InputFrame(right=True)
    changed[198] = InputFrame()
    baseline = auto.evaluate_replay_with_sentinel(level, frames)
    candidate = auto.evaluate_replay_with_sentinel(level, changed)

    native_match = auto.find_baseline_alignment(
        candidate,
        baseline,
        max_alignment=3,
        max_negative_alignment=80,
        objective=auto.AUTO_OBJECTIVE_HIGHSCORE,
    )
    python_match = auto.find_baseline_alignment(
        replace(candidate, trace=tuple(candidate.trace)),
        replace(baseline, trace=tuple(baseline.trace)),
        max_alignment=3,
        max_negative_alignment=80,
        objective=auto.AUTO_OBJECTIVE_HIGHSCORE,
    )

    assert native_match == python_match
    assert native_match is not None
    assert (
        native_match.candidate_tick,
        native_match.reference_tick,
        native_match.offset,
    ) == (240, 239, -1)


def test_native_route_scan_and_multiprocessing_materialisation_are_portable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_native_auto()
    level, frames = _load_benchmark_replay(302)
    baseline = auto.evaluate_replay_with_sentinel(level, frames)
    changed = list(frames)
    changed[0] = InputFrame(jump=True)
    candidate = auto.evaluate_replay_with_sentinel(level, changed)

    created = 0
    point_type = auto.CompactTracePoint

    def counted_point(*args, **kwargs):
        nonlocal created
        created += 1
        return point_type(*args, **kwargs)

    monkeypatch.setattr(auto, "CompactTracePoint", counted_point)
    native_target = auto._find_route_control_repair_target(candidate, baseline)
    assert native_target == auto.RouteControlRepairTarget(
        candidate_tick=169,
        reference_tick=169,
        required_exit_mask=2,
        required_locked_door_mask=0,
        forbidden_trapdoor_mask=0,
    )
    assert created == 0

    material_candidate = replace(candidate, trace=tuple(candidate.trace))
    material_baseline = replace(baseline, trace=tuple(baseline.trace))
    assert auto._find_route_control_repair_target(
        material_candidate, material_baseline
    ) == native_target

    monkeypatch.setattr(auto, "CompactTracePoint", point_type)
    restored = pickle.loads(pickle.dumps(baseline))
    assert isinstance(restored.trace, tuple)
    assert restored == baseline
    assert restored.valid


def test_native_bounded_splice_alignment_matches_python_fallback_and_stays_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_native_auto()
    candidate_level, candidate_frames = _load_benchmark_replay(342)
    reference_level, reference_frames = _load_benchmark_replay(343)
    candidate = auto.evaluate_replay_with_sentinel(
        candidate_level, candidate_frames
    )
    reference = auto.evaluate_replay_with_sentinel(
        reference_level, reference_frames
    )
    config = auto.AutoConfig(iterations=1, beam_width=1, max_alignment=3)
    suffix = auto.PiecewiseReferenceLeg(
        child_start=240,
        child_end=None,
        reference=reference,
        reference_offset=1,
    )

    created = 0
    point_type = auto.CompactTracePoint

    def counted_point(*args, **kwargs):
        nonlocal created
        created += 1
        return point_type(*args, **kwargs)

    monkeypatch.setattr(auto, "CompactTracePoint", counted_point)
    native_match = auto._find_splice_suffix_alignment(
        candidate,
        suffix,
        config,
        minimum_run_length=2,
    )
    assert native_match is not None
    assert created == 0

    monkeypatch.setattr(auto, "CompactTracePoint", point_type)
    material_candidate = replace(candidate, trace=tuple(candidate.trace))
    material_reference = replace(reference, trace=tuple(reference.trace))
    python_match = auto._find_splice_suffix_alignment(
        material_candidate,
        replace(suffix, reference=material_reference),
        config,
        minimum_run_length=2,
    )
    assert native_match == python_match

    one_tick = auto.PiecewiseReferenceLeg(
        child_start=100,
        child_end=100,
        reference=reference,
        reference_offset=0,
    )
    material_one_tick = replace(one_tick, reference=material_reference)
    assert auto._piecewise_leg_match_run(candidate, one_tick, config) == 1
    assert auto._piecewise_leg_match_run(
        material_candidate,
        material_one_tick,
        config,
    ) == 1


def test_native_splice_alignment_preserves_sparse_trace_no_match_semantics() -> None:
    _require_native_auto()
    level, frames = _load_benchmark_replay(343)
    sparse = auto.evaluate_replay_with_sentinel(level, frames, trace_stride=7)
    material = replace(sparse, trace=tuple(sparse.trace))
    config = auto.AutoConfig(iterations=1, beam_width=1, max_alignment=0)
    native_leg = auto.PiecewiseReferenceLeg(0, None, sparse, 0)
    material_leg = replace(native_leg, reference=material)

    native_match = auto._find_splice_suffix_alignment(
        sparse,
        native_leg,
        config,
        minimum_run_length=2,
    )
    python_match = auto._find_splice_suffix_alignment(
        material,
        material_leg,
        config,
        minimum_run_length=2,
    )

    assert native_match is None
    assert native_match == python_match
    assert auto._piecewise_leg_match_run(sparse, native_leg, config) == 1
    assert auto._piecewise_leg_match_run(
        material,
        material_leg,
        config,
    ) == 1


def test_native_bounded_route_scan_is_inclusive_and_matches_python_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_native_auto()
    level, frames = _load_benchmark_replay(302)
    reference = auto.evaluate_replay_with_sentinel(level, frames)
    changed = list(frames)
    changed[0] = InputFrame(jump=True)
    candidate = auto.evaluate_replay_with_sentinel(level, changed)
    material_candidate = replace(candidate, trace=tuple(candidate.trace))
    material_reference = replace(reference, trace=tuple(reference.trace))

    created = 0
    point_type = auto.CompactTracePoint

    def counted_point(*args, **kwargs):
        nonlocal created
        created += 1
        return point_type(*args, **kwargs)

    monkeypatch.setattr(auto, "CompactTracePoint", counted_point)
    native_at_boundary = auto._find_route_control_repair_target(
        candidate,
        reference,
        candidate_start_tick=169,
        candidate_end_tick=169,
    )
    native_before = auto._find_route_control_repair_target(
        candidate,
        reference,
        candidate_start_tick=0,
        candidate_end_tick=168,
    )
    assert created == 0

    monkeypatch.setattr(auto, "CompactTracePoint", point_type)
    python_at_boundary = auto._find_route_control_repair_target(
        material_candidate,
        material_reference,
        candidate_start_tick=169,
        candidate_end_tick=169,
    )
    python_before = auto._find_route_control_repair_target(
        material_candidate,
        material_reference,
        candidate_start_tick=0,
        candidate_end_tick=168,
    )
    assert native_at_boundary == python_at_boundary
    assert native_at_boundary is not None
    assert native_at_boundary.candidate_tick == 169
    assert native_before is None
    assert native_before == python_before


def test_native_bounded_route_scan_preserves_wide_masks() -> None:
    _require_native_auto()
    padding = "!".join("0^500,500" for _ in range(70))
    reference_objects = (
        f"{padding}!0^90,84"
        "!9^90,84,0,0,10,3,1,0,0"
        "!9^90,84,0,1,11,3,0,0,0"
        "!5^90,84"
    )
    candidate_objects = (
        f"{padding}!0^90,84"
        "!0^500,500"
        "!0^500,500"
        "!5^90,84"
    )
    reference = auto.evaluate_replay_with_sentinel(
        parse_level_string(f"{EMPTY_MAP}|{reference_objects}"),
        (NEUTRAL,),
    )
    candidate = auto.evaluate_replay_with_sentinel(
        parse_level_string(f"{EMPTY_MAP}|{candidate_objects}"),
        (NEUTRAL,),
    )

    native_target = auto._find_route_control_repair_target(
        candidate,
        reference,
        candidate_start_tick=1,
        candidate_end_tick=1,
    )
    python_target = auto._find_route_control_repair_target(
        replace(candidate, trace=tuple(candidate.trace)),
        replace(reference, trace=tuple(reference.trace)),
        candidate_start_tick=1,
        candidate_end_tick=1,
    )

    assert native_target == python_target
    assert native_target is not None
    assert native_target.required_locked_door_mask == 1 << 71

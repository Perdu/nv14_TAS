from __future__ import annotations

import ctypes
import importlib

import pytest


TRACE_ABI = 2
ANALYSIS_ABI = 1


class _TracePoint(ctypes.Structure):
    _fields_ = [
        ("tick", ctypes.c_uint64),
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("vx", ctypes.c_double),
        ("vy", ctypes.c_double),
        ("jump_events", ctypes.c_uint64),
        ("gold_bonus_ticks", ctypes.c_uint64),
        ("player_state", ctypes.c_int32),
        ("wall_x", ctypes.c_int8),
        ("floor_x", ctypes.c_int8),
        ("floor_y", ctypes.c_int8),
        ("in_air", ctypes.c_uint8),
        ("near_wall", ctypes.c_uint8),
        ("previous_jump_held", ctypes.c_uint8),
        ("complete", ctypes.c_uint8),
        ("dead", ctypes.c_uint8),
        ("reserved", ctypes.c_uint8 * 4),
    ]


class _TraceResult(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("struct_size", ctypes.c_uint32),
        ("populated", ctypes.c_uint8),
        ("unsupported", ctypes.c_uint8),
        ("has_pre_finish_exit_distance", ctypes.c_uint8),
        ("reserved_flags", ctypes.c_uint8 * 5),
        ("finish_tick", ctypes.c_int64),
        ("dead_tick", ctypes.c_int64),
        ("last_tick", ctypes.c_int64),
        ("completed_exit_index", ctypes.c_int64),
        ("pre_finish_exit_distance", ctypes.c_double),
        ("gold_bonus_ticks", ctypes.c_uint64),
        ("trace", ctypes.POINTER(_TracePoint)),
        ("trace_count", ctypes.c_size_t),
        ("trace_capacity", ctypes.c_size_t),
        ("trace_collected_gold_words", ctypes.POINTER(ctypes.c_uint64)),
        ("trace_exploded_mine_words", ctypes.POINTER(ctypes.c_uint64)),
        ("trace_open_exit_words", ctypes.POINTER(ctypes.c_uint64)),
        ("trace_opened_locked_door_words", ctypes.POINTER(ctypes.c_uint64)),
        ("trace_triggered_trapdoor_words", ctypes.POINTER(ctypes.c_uint64)),
        ("collected_gold_word_count", ctypes.c_size_t),
        ("exploded_mine_word_count", ctypes.c_size_t),
        ("open_exit_word_count", ctypes.c_size_t),
        ("door_word_count", ctypes.c_size_t),
        ("final_collected_gold_words", ctypes.POINTER(ctypes.c_uint64)),
        ("final_exploded_mine_words", ctypes.POINTER(ctypes.c_uint64)),
        ("final_open_exit_words", ctypes.POINTER(ctypes.c_uint64)),
        ("final_opened_locked_door_words", ctypes.POINTER(ctypes.c_uint64)),
        ("final_triggered_trapdoor_words", ctypes.POINTER(ctypes.c_uint64)),
        ("successful_jumps", ctypes.POINTER(ctypes.c_uint64)),
        ("successful_jump_count", ctypes.c_size_t),
        ("jump_edges", ctypes.POINTER(ctypes.c_uint64)),
        ("jump_edge_count", ctypes.c_size_t),
        ("missed_jump_edges", ctypes.POINTER(ctypes.c_uint64)),
        ("missed_jump_edge_count", ctypes.c_size_t),
        ("jump_callable_windows", ctypes.c_void_p),
        ("jump_callable_window_count", ctypes.c_size_t),
        ("gold_events", ctypes.c_void_p),
        ("gold_event_count", ctypes.c_size_t),
        ("gold_event_capacity", ctypes.c_size_t),
        ("route_control_events", ctypes.c_void_p),
        ("route_control_event_count", ctypes.c_size_t),
        ("route_control_event_capacity", ctypes.c_size_t),
    ]


class _SpliceSpec(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("struct_size", ctypes.c_uint32),
        ("candidate_start_tick", ctypes.c_uint64),
        ("candidate_end_tick", ctypes.c_uint64),
        ("minimum_run_length", ctypes.c_uint64),
        ("minimum_offset", ctypes.c_int64),
        ("maximum_offset", ctypes.c_int64),
        ("position_tolerance", ctypes.c_double),
        ("velocity_tolerance", ctypes.c_double),
        ("position_weight", ctypes.c_double),
        ("velocity_weight", ctypes.c_double),
        ("contact_mismatch_penalty", ctypes.c_double),
        ("in_air_mismatch_penalty", ctypes.c_double),
        ("near_wall_mismatch_penalty", ctypes.c_double),
        ("gold_bit_penalty", ctypes.c_double),
        ("mine_bit_penalty", ctypes.c_double),
        ("exit_bit_penalty", ctypes.c_double),
        ("locked_door_bit_penalty", ctypes.c_double),
        ("trapdoor_bit_penalty", ctypes.c_double),
    ]


class _SpliceResult(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("struct_size", ctypes.c_uint32),
        ("found", ctypes.c_uint8),
        ("contact_matches", ctypes.c_uint8),
        ("static_matches", ctypes.c_uint8),
        ("reserved", ctypes.c_uint8 * 5),
        ("candidate_tick", ctypes.c_int64),
        ("reference_tick", ctypes.c_int64),
        ("offset", ctypes.c_int64),
        ("score_lead", ctypes.c_int64),
        ("run_length", ctypes.c_uint64),
        ("distance", ctypes.c_double),
    ]


def _native_library() -> ctypes.CDLL:
    try:
        native = importlib.import_module("_nv14_native")
    except ImportError as exc:
        pytest.skip(f"native extension is unavailable: {exc}")
    library = ctypes.CDLL(native.__file__)
    try:
        function = library.nv14_replay_trace_find_splice_alignment
    except AttributeError:
        pytest.skip("native splice alignment symbol is not exported")
    function.argtypes = [
        ctypes.POINTER(_TraceResult),
        ctypes.POINTER(_TraceResult),
        ctypes.POINTER(_SpliceSpec),
        ctypes.POINTER(_SpliceResult),
    ]
    function.restype = ctypes.c_int
    return library


def _trace(point: _TracePoint) -> tuple[_TraceResult, _TracePoint]:
    result = _TraceResult(
        abi_version=TRACE_ABI,
        struct_size=ctypes.sizeof(_TraceResult),
        populated=1,
        finish_tick=-1,
        dead_tick=-1,
        last_tick=0,
        completed_exit_index=-1,
        trace=ctypes.pointer(point),
        trace_count=1,
        trace_capacity=1,
    )
    return result, point


def _matches(
    *,
    candidate_near_wall: bool,
    reference_near_wall: bool,
    candidate_wall_x: int = 1,
    reference_wall_x: int = -1,
    candidate_in_air: bool = False,
    reference_in_air: bool = False,
    candidate_floor_x: int = 0,
    reference_floor_x: int = 0,
) -> bool:
    library = _native_library()
    candidate, candidate_point = _trace(
        _TracePoint(
            tick=0,
            wall_x=candidate_wall_x,
            near_wall=candidate_near_wall,
            in_air=candidate_in_air,
            floor_x=candidate_floor_x,
        )
    )
    reference, reference_point = _trace(
        _TracePoint(
            tick=0,
            wall_x=reference_wall_x,
            near_wall=reference_near_wall,
            in_air=reference_in_air,
            floor_x=reference_floor_x,
        )
    )
    spec = _SpliceSpec(
        abi_version=ANALYSIS_ABI,
        struct_size=ctypes.sizeof(_SpliceSpec),
        candidate_start_tick=0,
        candidate_end_tick=0,
        minimum_run_length=1,
        minimum_offset=0,
        maximum_offset=0,
        position_tolerance=0.0,
        velocity_tolerance=0.0,
        position_weight=1.0,
        velocity_weight=1.0,
        contact_mismatch_penalty=16.0,
        in_air_mismatch_penalty=8.0,
        near_wall_mismatch_penalty=8.0,
        gold_bit_penalty=1.0,
        mine_bit_penalty=1.0,
        exit_bit_penalty=1.0,
        locked_door_bit_penalty=1.0,
        trapdoor_bit_penalty=1.0,
    )
    output = _SpliceResult(
        abi_version=ANALYSIS_ABI,
        struct_size=ctypes.sizeof(_SpliceResult),
    )

    status = library.nv14_replay_trace_find_splice_alignment(
        ctypes.byref(candidate),
        ctypes.byref(reference),
        ctypes.byref(spec),
        ctypes.byref(output),
    )
    # Keep the pointees alive until after the native call.
    assert candidate_point.tick == reference_point.tick == 0
    assert status in (0, 1)
    return bool(output.found)


def test_native_splice_ignores_inactive_stale_wall_normal() -> None:
    assert _matches(candidate_near_wall=False, reference_near_wall=False)


def test_native_splice_accepts_equal_active_wall_contact() -> None:
    assert _matches(
        candidate_near_wall=True,
        reference_near_wall=True,
        candidate_wall_x=1,
        reference_wall_x=1,
    )


def test_native_splice_ignores_inactive_airborne_floor_normal() -> None:
    assert _matches(
        candidate_near_wall=False,
        reference_near_wall=False,
        candidate_in_air=True,
        reference_in_air=True,
        candidate_floor_x=0,
        reference_floor_x=1,
    )


def test_native_splice_keeps_grounded_floor_normal_exact() -> None:
    assert not _matches(
        candidate_near_wall=False,
        reference_near_wall=False,
        candidate_floor_x=0,
        reference_floor_x=1,
    )


def test_native_splice_keeps_airborne_state_exact() -> None:
    assert not _matches(
        candidate_near_wall=False,
        reference_near_wall=False,
        candidate_in_air=True,
        reference_in_air=False,
    )


@pytest.mark.parametrize(
    ("candidate_near_wall", "reference_near_wall"),
    [(True, True), (True, False), (False, True)],
)
def test_native_splice_keeps_active_wall_contact_exact(
    candidate_near_wall: bool,
    reference_near_wall: bool,
) -> None:
    assert not _matches(
        candidate_near_wall=candidate_near_wall,
        reference_near_wall=reference_near_wall,
    )

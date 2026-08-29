# cython: language_level=3
# cython: binding=True
# cython: boundscheck=False
# cython: wraparound=False
"""Unified ownership and marshalling layer for the native engine/search APIs.

Gameplay and traversal logic belong in the hand-written C units. This module
owns opaque handles and result buffers, converts Python plans and replay inputs
to their compact C representations, releases the GIL while C runs, and converts
snapshots/results back to ordinary Python values.
"""

from cpython.exc cimport PyErr_CheckSignals
from cpython.mem cimport PyMem_Free, PyMem_Malloc
from cpython.ref cimport PyObject
from libc.stddef cimport size_t
from libc.stdint cimport int32_t, int64_t, int8_t, uint8_t, uint16_t, uint32_t, uint64_t
from libc.string cimport memcpy, memset

from collections.abc import Mapping as _Mapping
import operator as _operator


cdef extern from "nv14_core.h":
    cdef unsigned int NV14_CORE_ABI_VERSION

    ctypedef struct nv14_level:
        pass

    ctypedef struct nv14_state:
        pass

    ctypedef enum nv14_status:
        NV14_STATUS_OK
        NV14_STATUS_INVALID_ARGUMENT
        NV14_STATUS_OUT_OF_MEMORY
        NV14_STATUS_INVALID_LEVEL
        NV14_STATUS_UNSUPPORTED_TILE
        NV14_STATUS_UNSUPPORTED_OBJECTS
        NV14_STATUS_OUT_OF_BOUNDS
        NV14_STATUS_BUFFER_TOO_SMALL
        NV14_STATUS_HOOK_ERROR
        NV14_STATUS_PHASE_ERROR

    ctypedef enum nv14_mask_kind:
        NV14_MASK_COLLECTED_GOLD
        NV14_MASK_EXPLODED_MINE
        NV14_MASK_OPEN_EXIT

    ctypedef enum nv14_capability:
        NV14_CAP_TILE_COLLISION
        NV14_CAP_STATIC_OBJECTS
        NV14_CAP_ONEWAY_PLATFORM
        NV14_CAP_LAUNCH_PAD
        NV14_CAP_COMPLETE_STEP
        NV14_CAP_OBJECT_HOOKS

    ctypedef uint32_t nv14_object_type_mask

    ctypedef struct nv14_error:
        nv14_status code
        size_t byte_offset
        int object_type
        int tile_id
        int tile_i
        int tile_j
        char message[192]

    ctypedef struct nv14_input:
        uint8_t left
        uint8_t right
        uint8_t jump
        int8_t jump_trigger

    ctypedef struct nv14_vec2:
        double x
        double y

    ctypedef struct nv14_player_snapshot:
        nv14_vec2 pos
        nv14_vec2 oldpos
        double r
        double xw
        double yw
        double maxspeed_air
        double maxspeed_ground
        double ground_accel
        double air_accel
        double norm_grav
        double jump_grav
        double norm_drag
        double win_drag
        double wall_friction
        double skid_friction
        double stand_friction
        double jump_amt
        double jump_y_bias
        int32_t max_jump_time
        double terminal_vel
        double g
        double d
        int32_t state
        int32_t jump_timer
        uint8_t was_in_air
        uint8_t in_air
        uint8_t near_wall
        uint8_t dead
        nv14_vec2 wall_n
        nv14_vec2 floor_n
        nv14_vec2 floor_n0
        nv14_vec2 floor_n1
        nv14_vec2 old_v
        int32_t floor_count
        uint8_t previous_jump_held
        uint8_t celeb_was_in_air
        uint16_t reserved_flags
        uint64_t jump_events
        int32_t cell_i
        int32_t cell_j

    ctypedef struct nv14_object_descriptor:
        int32_t object_type
        uint32_t load_index
        uint32_t parameter_count
        double parameters[10]

    ctypedef struct nv14_step_result:
        uint64_t frame_before
        uint64_t frame_after
        uint64_t jump_events_before
        uint64_t jump_events_after
        uint8_t dead
        uint8_t level_complete
        uint8_t jumped
        uint8_t collected_gold
        uint8_t exploded_mine
        uint8_t opened_exit
        uint8_t unsupported
        uint8_t jump_callable

    nv14_level *nv14_level_create(
        const char *level_string,
        size_t level_length,
        int simulate_enemies,
        nv14_error *error_out,
    ) nogil
    void nv14_level_retain(nv14_level *level) noexcept nogil
    void nv14_level_release(nv14_level *level) noexcept nogil
    uint32_t nv14_level_capabilities(const nv14_level *level) noexcept nogil
    nv14_object_type_mask nv14_level_unsupported_object_mask(
        const nv14_level *level,
    ) noexcept nogil
    size_t nv14_level_object_count(const nv14_level *level) noexcept nogil
    nv14_status nv14_level_object_descriptor_at(
        const nv14_level *level,
        size_t index,
        nv14_object_descriptor *descriptor_out,
    ) noexcept nogil
    size_t nv14_level_gold_count(const nv14_level *level) noexcept nogil
    size_t nv14_level_mine_count(const nv14_level *level) noexcept nogil
    size_t nv14_level_exit_count(const nv14_level *level) noexcept nogil

    nv14_state *nv14_state_create(
        const nv14_level *level,
        nv14_error *error_out,
    ) nogil
    nv14_state *nv14_state_clone(
        const nv14_state *state,
        nv14_error *error_out,
    ) nogil
    void nv14_state_destroy(nv14_state *state) noexcept nogil
    nv14_status nv14_state_step(
        nv14_state *state,
        nv14_input input_frame,
        nv14_step_result *result_out,
    ) noexcept nogil
    nv14_status nv14_state_step_many(
        nv14_state *state,
        const nv14_input *inputs,
        size_t input_count,
        int stop_on_dead,
        int stop_on_complete,
        size_t *consumed_out,
        nv14_step_result *last_result_out,
    ) noexcept nogil
    nv14_status nv14_state_get_player(
        const nv14_state *state,
        nv14_player_snapshot *player_out,
    ) noexcept nogil
    uint64_t nv14_state_frame(const nv14_state *state) noexcept nogil
    int nv14_state_level_complete(const nv14_state *state) noexcept nogil
    uint64_t nv14_state_gold_bonus_ticks(const nv14_state *state) noexcept nogil
    int64_t nv14_state_completed_exit_index(const nv14_state *state) noexcept nogil
    size_t nv14_state_mask_word_count(
        const nv14_state *state,
        nv14_mask_kind kind,
    ) noexcept nogil
    nv14_status nv14_state_copy_mask(
        const nv14_state *state,
        nv14_mask_kind kind,
        uint64_t *words_out,
        size_t word_capacity,
    ) noexcept nogil
    size_t nv14_state_key_size(
        const nv14_state *state,
        int precision,
    ) noexcept nogil
    nv14_status nv14_state_write_key(
        const nv14_state *state,
        int precision,
        unsigned char *buffer,
        size_t buffer_size,
        size_t *written_out,
    ) noexcept nogil
    const char *nv14_status_string(nv14_status status) noexcept nogil


cdef extern from *:
    """
    static int nv14_wrapper_strict_fp(void) {
    #ifdef NV14_STRICT_FP
        return 1;
    #else
        return 0;
    #endif
    }
    """
    int nv14_wrapper_strict_fp() noexcept nogil


cdef extern from "nv14_objects_basic.h":
    nv14_status nv14_objects_basic_register() noexcept


cdef extern from "nv14_objects_guard.h":
    nv14_status nv14_objects_guard_register() noexcept


cdef extern from "nv14_objects_ranged.h":
    nv14_status nv14_objects_ranged_register() noexcept


cdef extern from "nv14_drone_weapons.h":
    nv14_status nv14_drone_weapons_register() noexcept


cdef extern from "nv14_objects_drones.h":
    nv14_status nv14_objects_drones_register() noexcept


cdef str _status_text(nv14_status status):
    cdef const char *message = nv14_status_string(status)
    if message == NULL:
        return f"native status {<int>status}"
    return (<bytes>message).decode("utf-8", "replace")


cdef object _raise_status(nv14_status status, str operation):
    cdef str message = f"{operation}: {_status_text(status)}"
    if status == NV14_STATUS_OUT_OF_MEMORY:
        raise MemoryError(message)
    if status in (
        NV14_STATUS_INVALID_ARGUMENT,
        NV14_STATUS_INVALID_LEVEL,
        NV14_STATUS_OUT_OF_BOUNDS,
        NV14_STATUS_BUFFER_TOO_SMALL,
        NV14_STATUS_PHASE_ERROR,
    ):
        raise ValueError(message)
    if status in (NV14_STATUS_UNSUPPORTED_TILE, NV14_STATUS_UNSUPPORTED_OBJECTS):
        raise NotImplementedError(message)
    raise RuntimeError(message)


cdef object _raise_create_error(nv14_error *error, str operation):
    cdef const char *raw_message = &error.message[0]
    cdef str message
    if raw_message[0] != 0:
        message = (<bytes>raw_message).decode("utf-8", "replace")
    else:
        message = _status_text(error.code)
    message = f"{operation}: {message} (byte offset {error.byte_offset})"
    if error.code == NV14_STATUS_OUT_OF_MEMORY:
        raise MemoryError(message)
    if error.code in (NV14_STATUS_UNSUPPORTED_TILE, NV14_STATUS_UNSUPPORTED_OBJECTS):
        raise NotImplementedError(message)
    if error.code in (NV14_STATUS_INVALID_ARGUMENT, NV14_STATUS_INVALID_LEVEL):
        raise ValueError(message)
    raise RuntimeError(message)


cdef void _register_builtin_object_modules() except *:
    """Install native gameplay modules once while Python owns the GIL."""
    cdef nv14_status status = nv14_objects_basic_register()
    if status != NV14_STATUS_OK:
        raise ImportError(
            "register native basic-object module: " + _status_text(status)
        )
    status = nv14_objects_guard_register()
    if status != NV14_STATUS_OK:
        raise ImportError(
            "register native floor-guard module: " + _status_text(status)
        )
    status = nv14_objects_ranged_register()
    if status != NV14_STATUS_OK:
        raise ImportError(
            "register native ranged-enemy module: " + _status_text(status)
        )
    status = nv14_drone_weapons_register()
    if status != NV14_STATUS_OK:
        raise ImportError(
            "register native drone-weapon callbacks: " + _status_text(status)
        )
    status = nv14_objects_drones_register()
    if status != NV14_STATUS_OK:
        raise ImportError(
            "register native drone module: " + _status_text(status)
        )


_register_builtin_object_modules()


cdef int _fill_input(object frame, nv14_input *output) except -1:
    cdef object trigger
    if hasattr(frame, "left"):
        output.left = <uint8_t>bool(frame.left)
        output.right = <uint8_t>bool(frame.right)
        output.jump = <uint8_t>bool(frame.jump)
        trigger = getattr(frame, "jump_trigger", None)
    else:
        try:
            count = len(frame)
        except TypeError as exc:
            raise TypeError(
                "native input must expose left/right/jump attributes or be a "
                "three/four-item sequence"
            ) from exc
        if count not in (3, 4):
            raise ValueError("native input sequences must contain 3 or 4 values")
        output.left = <uint8_t>bool(frame[0])
        output.right = <uint8_t>bool(frame[1])
        output.jump = <uint8_t>bool(frame[2])
        trigger = None if count == 3 else frame[3]
    output.jump_trigger = <int8_t>(-1 if trigger is None else int(bool(trigger)))
    return 0


cdef dict _step_result_dict(const nv14_step_result *result):
    return {
        "frame_before": result.frame_before,
        "frame_after": result.frame_after,
        "jump_events_before": result.jump_events_before,
        "jump_events_after": result.jump_events_after,
        "dead": bool(result.dead),
        "level_complete": bool(result.level_complete),
        "jumped": bool(result.jumped),
        "collected_gold": bool(result.collected_gold),
        "exploded_mine": bool(result.exploded_mine),
        "opened_exit": bool(result.opened_exit),
        "unsupported": bool(result.unsupported),
        "jump_callable": bool(result.jump_callable),
    }


cdef dict _player_dict(const nv14_player_snapshot *player):
    return {
        "pos": (player.pos.x, player.pos.y),
        "oldpos": (player.oldpos.x, player.oldpos.y),
        "r": player.r,
        "xw": player.xw,
        "yw": player.yw,
        "maxspeed_air": player.maxspeed_air,
        "maxspeed_ground": player.maxspeed_ground,
        "ground_accel": player.ground_accel,
        "air_accel": player.air_accel,
        "norm_grav": player.norm_grav,
        "jump_grav": player.jump_grav,
        "norm_drag": player.norm_drag,
        "win_drag": player.win_drag,
        "wall_friction": player.wall_friction,
        "skid_friction": player.skid_friction,
        "stand_friction": player.stand_friction,
        "jump_amt": player.jump_amt,
        "jump_y_bias": player.jump_y_bias,
        "max_jump_time": player.max_jump_time,
        "terminal_vel": player.terminal_vel,
        "g": player.g,
        "d": player.d,
        "state": player.state,
        "jump_timer": player.jump_timer,
        "was_in_air": bool(player.was_in_air),
        "in_air": bool(player.in_air),
        "near_wall": bool(player.near_wall),
        "dead": bool(player.dead),
        "wall_n": (player.wall_n.x, player.wall_n.y),
        "floor_n": (player.floor_n.x, player.floor_n.y),
        "floor_n0": (player.floor_n0.x, player.floor_n0.y),
        "floor_n1": (player.floor_n1.x, player.floor_n1.y),
        "old_v": (player.old_v.x, player.old_v.y),
        "floor_count": player.floor_count,
        "previous_jump_held": bool(player.previous_jump_held),
        "celeb_was_in_air": bool(player.celeb_was_in_air),
        "jump_events": player.jump_events,
        "cell_i": player.cell_i,
        "cell_j": player.cell_j,
    }


cdef object _mask_as_int(const nv14_state *state, nv14_mask_kind kind):
    cdef size_t word_count = nv14_state_mask_word_count(state, kind)
    cdef uint64_t *words = NULL
    cdef nv14_status status
    cdef Py_ssize_t index
    cdef object value = 0
    if word_count == 0:
        return value
    if word_count > (<size_t>-1) // sizeof(uint64_t):
        raise OverflowError("native mask is too large to marshal")
    words = <uint64_t *>PyMem_Malloc(word_count * sizeof(uint64_t))
    if words == NULL:
        raise MemoryError("unable to allocate native mask buffer")
    try:
        status = nv14_state_copy_mask(state, kind, words, word_count)
        if status != NV14_STATUS_OK:
            _raise_status(status, "copy native state mask")
        for index in range(<Py_ssize_t>word_count - 1, -1, -1):
            value = (value << 64) | words[index]
        return value
    finally:
        PyMem_Free(words)


cdef class NativeLevel:
    """Owned immutable handle to a level fully supported by the C core."""

    cdef nv14_level *_handle
    cdef bytes _encoded_level
    cdef bint _simulate_enemies

    def __cinit__(self):
        self._handle = NULL

    def __dealloc__(self):
        if self._handle != NULL:
            nv14_level_release(self._handle)
            self._handle = NULL

    @property
    def backend(self):
        return "native-core"

    @property
    def level_string(self):
        return self._encoded_level.decode("utf-8")

    @property
    def simulate_enemies(self):
        return bool(self._simulate_enemies)

    @property
    def capabilities(self):
        return nv14_level_capabilities(self._handle)

    @property
    def unsupported_object_mask(self):
        return nv14_level_unsupported_object_mask(self._handle)

    @property
    def object_count(self):
        return nv14_level_object_count(self._handle)

    @property
    def gold_count(self):
        return nv14_level_gold_count(self._handle)

    @property
    def mine_count(self):
        return nv14_level_mine_count(self._handle)

    @property
    def exit_count(self):
        return nv14_level_exit_count(self._handle)

    def object_descriptors(self):
        cdef size_t count = nv14_level_object_count(self._handle)
        cdef size_t index
        cdef size_t parameter_index
        cdef nv14_object_descriptor descriptor
        cdef nv14_status status
        result = []
        parameters = None
        for index in range(count):
            status = nv14_level_object_descriptor_at(
                self._handle,
                index,
                &descriptor,
            )
            if status != NV14_STATUS_OK:
                _raise_status(status, "read native object descriptor")
            if descriptor.parameter_count > 10:
                raise RuntimeError(
                    "native object descriptor exceeds the wrapper ABI capacity"
                )
            parameters = []
            for parameter_index in range(descriptor.parameter_count):
                parameters.append(descriptor.parameters[parameter_index])
            result.append(
                {
                    "object_type": descriptor.object_type,
                    "load_index": descriptor.load_index,
                    "parameters": tuple(parameters),
                }
            )
        return tuple(result)

    def initial_state(self):
        cdef nv14_error error
        cdef nv14_state *state_handle
        memset(&error, 0, sizeof(nv14_error))
        state_handle = nv14_state_create(self._handle, &error)
        if state_handle == NULL:
            _raise_create_error(&error, "create native simulation state")
        return NativeState._from_handle(self, state_handle)

    def simulate(self, frames, *, stop_on_dead=True, stop_on_complete=False):
        state = self.initial_state()
        return state.step_many(
            frames,
            stop_on_dead=stop_on_dead,
            stop_on_complete=stop_on_complete,
        )

    def __reduce__(self):
        return (
            _rebuild_native_level,
            (self.level_string, bool(self._simulate_enemies)),
        )


cdef class NativeState:
    """Owned mutable state used by the native fixed-input batch API."""

    cdef nv14_state *_handle
    cdef NativeLevel _level

    def __cinit__(self):
        self._handle = NULL

    @staticmethod
    cdef NativeState _from_handle(NativeLevel level, nv14_state *handle):
        cdef NativeState result
        try:
            result = NativeState.__new__(NativeState)
            result._level = level
        except BaseException:
            nv14_state_destroy(handle)
            raise
        result._handle = handle
        return result

    def __dealloc__(self):
        if self._handle != NULL:
            nv14_state_destroy(self._handle)
            self._handle = NULL

    @property
    def backend(self):
        return "native-core"

    @property
    def level(self):
        return self._level

    @property
    def frame(self):
        return nv14_state_frame(self._handle)

    @property
    def level_complete(self):
        return bool(nv14_state_level_complete(self._handle))

    def clone(self):
        cdef nv14_error error
        cdef nv14_state *state_handle
        memset(&error, 0, sizeof(nv14_error))
        state_handle = nv14_state_clone(self._handle, &error)
        if state_handle == NULL:
            _raise_create_error(&error, "clone native simulation state")
        return NativeState._from_handle(self._level, state_handle)

    def player_snapshot(self):
        cdef nv14_player_snapshot player
        cdef nv14_status status = nv14_state_get_player(self._handle, &player)
        if status != NV14_STATUS_OK:
            _raise_status(status, "read native player state")
        return _player_dict(&player)

    def static_state(self):
        return {
            "collected_gold_mask": _mask_as_int(
                self._handle,
                NV14_MASK_COLLECTED_GOLD,
            ),
            "exploded_mine_mask": _mask_as_int(
                self._handle,
                NV14_MASK_EXPLODED_MINE,
            ),
            "open_exit_mask": _mask_as_int(
                self._handle,
                NV14_MASK_OPEN_EXIT,
            ),
            "level_complete": bool(nv14_state_level_complete(self._handle)),
            "gold_bonus_ticks": nv14_state_gold_bonus_ticks(self._handle),
            "completed_exit_index": nv14_state_completed_exit_index(self._handle),
        }

    def snapshot(self):
        return {
            "backend": "native-core",
            "frame": nv14_state_frame(self._handle),
            "player": self.player_snapshot(),
            "static_state": self.static_state(),
        }

    def step(self, *args):
        """Advance once from an input object or 3/4 individual input values."""
        cdef nv14_input input_frame
        cdef nv14_step_result result
        cdef nv14_status status
        if len(args) == 1:
            frame = args[0]
        elif len(args) in (3, 4):
            frame = args
        else:
            raise TypeError(
                "step expects one InputFrame-like object or "
                "left, right, jump[, jump_trigger]"
            )
        _fill_input(frame, &input_frame)
        memset(&result, 0, sizeof(nv14_step_result))
        with nogil:
            status = nv14_state_step(self._handle, input_frame, &result)
        if status != NV14_STATUS_OK:
            _raise_status(status, "step native simulation state")
        if result.unsupported:
            raise NotImplementedError("native state encountered an unsupported object")
        return _step_result_dict(&result)

    def step_many(self, frames, *, stop_on_dead=True, stop_on_complete=False):
        cdef tuple materialized = tuple(frames)
        cdef Py_ssize_t count = len(materialized)
        cdef Py_ssize_t index
        cdef nv14_input *inputs = NULL
        cdef size_t consumed = 0
        cdef nv14_step_result last_result
        cdef nv14_status status
        cdef int native_stop_on_dead = 1 if stop_on_dead else 0
        cdef int native_stop_on_complete = 1 if stop_on_complete else 0
        if count > 0:
            if <size_t>count > (<size_t>-1) // sizeof(nv14_input):
                raise OverflowError("native input batch is too large")
            inputs = <nv14_input *>PyMem_Malloc(count * sizeof(nv14_input))
            if inputs == NULL:
                raise MemoryError("unable to allocate native input batch")
        try:
            for index in range(count):
                _fill_input(materialized[index], &inputs[index])
            memset(&last_result, 0, sizeof(nv14_step_result))
            with nogil:
                status = nv14_state_step_many(
                    self._handle,
                    inputs,
                    <size_t>count,
                    native_stop_on_dead,
                    native_stop_on_complete,
                    &consumed,
                    &last_result,
                )
            if status != NV14_STATUS_OK:
                _raise_status(status, "step native simulation batch")
            if last_result.unsupported:
                raise NotImplementedError(
                    "native state encountered an unsupported object"
                )
            return {
                "consumed": consumed,
                "last_step": (
                    None if consumed == 0 else _step_result_dict(&last_result)
                ),
                "state": self.snapshot(),
            }
        finally:
            if inputs != NULL:
                PyMem_Free(inputs)

    def state_key(self, *, precision=None):
        """Return an exact key scoped to this state's immutable level."""
        cdef int native_precision
        if precision is not None:
            raise NotImplementedError(
                "rounded native state keys are not implemented"
            )
        native_precision = -1
        cdef size_t key_size = nv14_state_key_size(self._handle, native_precision)
        cdef unsigned char *buffer = NULL
        cdef size_t written = 0
        cdef nv14_status status
        if key_size == 0:
            raise RuntimeError("native core returned an invalid empty state key")
        buffer = <unsigned char *>PyMem_Malloc(key_size)
        if buffer == NULL:
            raise MemoryError("unable to allocate native state-key buffer")
        try:
            status = nv14_state_write_key(
                self._handle,
                native_precision,
                buffer,
                key_size,
                &written,
            )
            if status != NV14_STATUS_OK:
                _raise_status(status, "write native state key")
            return bytes((<char *>buffer)[:written])
        finally:
            PyMem_Free(buffer)


def parse_level_string(
    str level_string,
    *,
    bint strict_shapes=True,
    bint simulate_enemies=False,
):
    """Return a native level or raise ``NotImplementedError`` if ineligible."""
    cdef bytes encoded = level_string.encode("utf-8")
    cdef nv14_error error
    cdef nv14_level *level_handle
    cdef uint32_t capabilities
    cdef uint32_t unsupported_mask
    cdef NativeLevel result
    cdef const char *level_bytes = <const char *>encoded
    cdef size_t level_length = <size_t>len(encoded)
    cdef int native_simulate_enemies = 1 if simulate_enemies else 0
    memset(&error, 0, sizeof(nv14_error))
    with nogil:
        level_handle = nv14_level_create(
            level_bytes,
            level_length,
            native_simulate_enemies,
            &error,
        )
    if level_handle == NULL:
        _raise_create_error(&error, "parse native level")

    capabilities = nv14_level_capabilities(level_handle)
    unsupported_mask = nv14_level_unsupported_object_mask(level_handle)
    if unsupported_mask != 0 or not (capabilities & NV14_CAP_COMPLETE_STEP):
        nv14_level_release(level_handle)
        raise NotImplementedError(
            "level is outside the native core's complete-step capability "
            f"(capabilities=0x{capabilities:x}, "
            f"unsupported_object_mask=0x{unsupported_mask:x})"
        )

    try:
        result = NativeLevel.__new__(NativeLevel)
        # Transfer ownership only after all Python-reference assignments have
        # succeeded, so an allocation failure cannot leak or double-release.
        result._encoded_level = encoded
        result._simulate_enemies = simulate_enemies
    except BaseException:
        nv14_level_release(level_handle)
        raise
    result._handle = level_handle
    return result


def _rebuild_native_level(str level_string, bint simulate_enemies):
    """Pickle reconstruction helper kept at extension-module scope."""
    return parse_level_string(
        level_string,
        simulate_enemies=simulate_enemies,
    )


def simulate_batch(
    str level_string,
    frames,
    *,
    bint simulate_enemies=False,
    bint stop_on_dead=True,
    bint stop_on_complete=False,
):
    """Parse and simulate one eligible fixed-input batch entirely in C."""
    level = parse_level_string(
        level_string,
        simulate_enemies=simulate_enemies,
    )
    return level.simulate(
        frames,
        stop_on_dead=stop_on_dead,
        stop_on_complete=stop_on_complete,
    )


def backend_info():
    return {
        "wrapper_api": 1,
        "core_abi": NV14_CORE_ABI_VERSION,
        "implementation": "cython-unified-native",
        "strict_fp": bool(nv14_wrapper_strict_fp()),
        "complete_step_capability": NV14_CAP_COMPLETE_STEP,
        "complete_enemy_engine": True,
        "native_object_type_mask": (1 << 13) - 1,
        "native_tile_id_count": 34,
    }


cdef extern from "nv14_search.h":
    cdef unsigned int NV14_SEARCH_ABI_VERSION

    ctypedef enum nv14_search_status:
        NV14_SEARCH_OK
        NV14_SEARCH_INVALID_ARGUMENT
        NV14_SEARCH_OUT_OF_MEMORY
        NV14_SEARCH_CORE_ERROR
        NV14_SEARCH_CANCELLED

    ctypedef enum nv14_search_objective:
        NV14_SEARCH_MAX_X
        NV14_SEARCH_MIN_X
        NV14_SEARCH_MAX_Y
        NV14_SEARCH_MIN_Y
        NV14_SEARCH_MIN_DISTANCE
        NV14_SEARCH_TRACE_DISTANCE
        NV14_SEARCH_CONSTANT

    ctypedef enum nv14_search_interaction_kind:
        NV14_SEARCH_INTERACTION_GOLD
        NV14_SEARCH_INTERACTION_EXIT_SWITCH
        NV14_SEARCH_INTERACTION_LOCKED_DOOR
        NV14_SEARCH_INTERACTION_TRAPDOOR

    ctypedef struct nv14_search_trace_target:
        double x
        double y
        double vx
        double vy
        int32_t player_state
        int8_t wall_x
        int8_t floor_x
        int8_t floor_y
        uint8_t in_air
        uint8_t near_wall
        uint8_t previous_jump_held
        double position_weight
        double velocity_weight
        double contact_mismatch_penalty
        double in_air_mismatch_penalty
        double near_wall_mismatch_penalty
        double gold_bit_penalty
        double mine_bit_penalty
        double exit_bit_penalty
        double locked_door_bit_penalty
        double trapdoor_bit_penalty
        const uint64_t *collected_gold
        size_t collected_gold_word_count
        const uint64_t *exploded_mine
        size_t exploded_mine_word_count
        const uint64_t *open_exit
        size_t open_exit_word_count
        const uint64_t *opened_locked_door
        size_t opened_locked_door_word_count
        const uint64_t *triggered_trapdoor
        size_t triggered_trapdoor_word_count

    ctypedef struct nv14_search_target:
        double x
        double y

    ctypedef struct nv14_search_interaction_atom:
        uint8_t kind
        size_t index

    ctypedef struct nv14_search_interaction_group:
        size_t first_atom
        size_t atom_count

    ctypedef int (*nv14_search_cancel_fn)(void *userdata) noexcept nogil

    ctypedef struct nv14_search_spec:
        uint32_t abi_version
        uint32_t struct_size
        const nv14_input *replay
        size_t replay_count
        size_t target_frame
        const size_t *mutable_frames
        size_t mutable_count
        const size_t *choices_begin
        const nv14_input *choices
        size_t choice_count
        nv14_search_objective objective
        const nv14_search_target *targets
        size_t target_count
        const nv14_search_trace_target *trace_target
        uint8_t has_x_window
        uint8_t has_y_window
        uint8_t prune_inactive_jump
        uint8_t physics_prune
        uint8_t skip_unchanged_final_step
        uint8_t require_all_constraints
        uint8_t required_jump_any
        uint8_t tie_break_low_edit_lex
        double x_minimum
        double x_maximum
        double y_minimum
        double y_maximum
        const nv14_search_interaction_atom *required_atoms
        size_t required_atom_count
        const nv14_search_interaction_group *required_groups
        size_t required_group_count
        const nv14_search_interaction_atom *avoided_atoms
        size_t avoided_atom_count
        const nv14_search_interaction_group *avoided_groups
        size_t avoided_group_count
        const uint8_t *incumbent_missing_requirements
        const uint8_t *incumbent_violated_avoidances
        const size_t *required_jump_frames
        size_t required_jump_count
        const uint8_t *incumbent_missing_jumps
        const size_t *ignored_jump_frames
        size_t ignored_jump_count
        uint64_t minimum_jump_events
        double incumbent_score
        uint8_t incumbent_feasible
        uint64_t max_simulated_ticks
        const nv14_state *prefix_state
        size_t prefix_frame
        nv14_search_cancel_fn cancel
        void *cancel_userdata
        uint64_t cancel_poll_interval

    ctypedef struct nv14_search_stats:
        uint64_t visited_nodes
        uint64_t evaluated_leaves
        uint64_t simulated_ticks
        uint64_t cloned_states
        uint64_t inactive_jump_prunes
        uint64_t missed_jump_prunes
        uint64_t dead_prunes
        uint64_t deduplicated_prunes
        uint64_t physics_prunes
        uint64_t avoided_interaction_prunes

    ctypedef struct nv14_search_result:
        uint8_t improved
        uint8_t feasible
        uint8_t budget_exhausted
        double score
        nv14_input *best_inputs
        size_t best_input_count
        uint8_t *missing_requirements
        size_t missing_requirement_count
        uint8_t *violated_avoidances
        size_t violated_avoidance_count
        uint8_t *missing_jumps
        size_t missing_jump_count
        nv14_player_snapshot player
        uint8_t has_player_snapshot
        nv14_search_stats stats

    ctypedef struct nv14_pattern_span:
        size_t start_frame
        size_t length

    ctypedef struct nv14_pattern_search_spec:
        uint32_t abi_version
        uint32_t struct_size
        const nv14_input *replay
        size_t replay_count
        size_t target_frame
        size_t range_start
        size_t range_end
        const nv14_input *inactive_inputs
        const nv14_input *active_inputs
        size_t pattern_input_count
        nv14_search_objective objective
        const nv14_search_target *targets
        size_t target_count
        uint8_t has_x_window
        uint8_t has_y_window
        double x_minimum
        double x_maximum
        double y_minimum
        double y_maximum
        size_t run_count_min
        size_t run_count_max
        size_t run_length_min
        const size_t *start_max_lengths
        size_t start_max_length_count
        size_t minimum_gap
        const size_t *fixed_starts
        size_t fixed_start_count
        uint32_t required_start_event_mask
        size_t top_results
        size_t shard_index
        size_t shard_count
        const nv14_state *prefix_state
        size_t prefix_frame
        nv14_search_cancel_fn cancel
        void *cancel_userdata
        uint64_t cancel_poll_interval

    ctypedef struct nv14_pattern_search_stats:
        uint64_t attempted_starts
        uint64_t successful_starts
        uint64_t evaluated_candidates
        uint64_t deduplicated_branches
        uint64_t simulated_ticks
        uint64_t cloned_states

    ctypedef struct nv14_pattern_search_candidate:
        double score
        nv14_pattern_span *spans
        size_t span_count
        nv14_player_snapshot player

    ctypedef struct nv14_pattern_search_result:
        nv14_pattern_search_candidate *candidates
        size_t candidate_count
        nv14_pattern_search_stats stats

    int nv14_search_result_init(
        nv14_search_result *result,
        size_t caller_size,
    ) noexcept nogil
    nv14_search_status nv14_search_run(
        const nv14_level *level,
        const nv14_search_spec *spec,
        nv14_search_result *result_out,
        nv14_error *error_out,
    ) noexcept nogil
    void nv14_search_result_destroy(nv14_search_result *result) noexcept nogil
    int nv14_pattern_search_result_init(
        nv14_pattern_search_result *result,
        size_t caller_size,
    ) noexcept nogil
    nv14_search_status nv14_pattern_search_run(
        const nv14_level *level,
        const nv14_pattern_search_spec *spec,
        nv14_pattern_search_result *result_out,
        nv14_error *error_out,
    ) noexcept nogil
    void nv14_pattern_search_result_destroy(
        nv14_pattern_search_result *result,
    ) noexcept nogil


cdef extern from "nv14_auto.h":
    cdef unsigned int NV14_REPLAY_TRACE_ABI_VERSION
    cdef unsigned int NV14_REPLAY_ANALYSIS_ABI_VERSION

    ctypedef enum nv14_replay_trace_status:
        NV14_REPLAY_TRACE_OK
        NV14_REPLAY_TRACE_INVALID_ARGUMENT
        NV14_REPLAY_TRACE_OUT_OF_MEMORY
        NV14_REPLAY_TRACE_CORE_ERROR

    ctypedef struct nv14_replay_trace_point:
        uint64_t tick
        double x
        double y
        double vx
        double vy
        uint64_t jump_events
        uint64_t gold_bonus_ticks
        int32_t player_state
        int8_t wall_x
        int8_t floor_x
        int8_t floor_y
        uint8_t in_air
        uint8_t near_wall
        uint8_t previous_jump_held
        uint8_t complete
        uint8_t dead

    ctypedef struct nv14_replay_gold_event:
        size_t gold_index
        uint64_t tick

    ctypedef struct nv14_replay_tick_window:
        uint64_t start_tick
        uint64_t end_tick

    ctypedef struct nv14_replay_route_event:
        size_t index
        uint64_t tick
        uint8_t kind

    ctypedef struct nv14_replay_trace_result:
        uint8_t populated
        uint8_t unsupported
        uint8_t has_pre_finish_exit_distance
        int64_t finish_tick
        int64_t dead_tick
        int64_t last_tick
        int64_t completed_exit_index
        double pre_finish_exit_distance
        uint64_t gold_bonus_ticks
        nv14_replay_trace_point *trace
        size_t trace_count
        uint64_t *trace_collected_gold_words
        uint64_t *trace_exploded_mine_words
        uint64_t *trace_open_exit_words
        uint64_t *trace_opened_locked_door_words
        uint64_t *trace_triggered_trapdoor_words
        size_t collected_gold_word_count
        size_t exploded_mine_word_count
        size_t open_exit_word_count
        size_t door_word_count
        uint64_t *final_collected_gold_words
        uint64_t *final_exploded_mine_words
        uint64_t *final_open_exit_words
        uint64_t *final_opened_locked_door_words
        uint64_t *final_triggered_trapdoor_words
        uint64_t *successful_jumps
        size_t successful_jump_count
        uint64_t *jump_edges
        size_t jump_edge_count
        uint64_t *missed_jump_edges
        size_t missed_jump_edge_count
        nv14_replay_tick_window *jump_callable_windows
        size_t jump_callable_window_count
        nv14_replay_gold_event *gold_events
        size_t gold_event_count
        nv14_replay_route_event *route_control_events
        size_t route_control_event_count

    ctypedef enum nv14_replay_alignment_objective:
        NV14_REPLAY_ALIGNMENT_SPEEDRUN
        NV14_REPLAY_ALIGNMENT_HIGHSCORE

    ctypedef struct nv14_replay_alignment_spec:
        uint32_t abi_version
        uint32_t struct_size
        uint64_t max_alignment
        uint64_t max_negative_alignment
        uint64_t scan_limit
        int64_t reference_completion_exit_index
        double position_tolerance
        double velocity_tolerance
        double position_weight
        double velocity_weight
        double contact_mismatch_penalty
        double in_air_mismatch_penalty
        double near_wall_mismatch_penalty
        double gold_bit_penalty
        double mine_bit_penalty
        double exit_bit_penalty
        double locked_door_bit_penalty
        double trapdoor_bit_penalty
        uint8_t objective

    ctypedef struct nv14_replay_alignment_result:
        uint32_t abi_version
        uint32_t struct_size
        uint8_t found
        uint8_t contact_matches
        uint8_t static_matches
        int64_t candidate_tick
        int64_t reference_tick
        int64_t offset
        int64_t score_lead
        double distance

    int nv14_replay_trace_result_init(
        nv14_replay_trace_result *result,
        size_t caller_size,
    ) noexcept nogil
    void nv14_replay_trace_result_destroy(
        nv14_replay_trace_result *result,
    ) noexcept nogil
    int nv14_replay_trace_find_point_index(
        const nv14_replay_trace_result *result,
        uint64_t tick,
        size_t *index_out,
    ) noexcept nogil
    int nv14_replay_trace_find_alignment(
        const nv14_replay_trace_result *candidate,
        const nv14_replay_trace_result *reference,
        const nv14_replay_alignment_spec *spec,
        nv14_replay_alignment_result *result_out,
    ) noexcept nogil
    int nv14_replay_trace_find_route_divergence(
        const nv14_replay_trace_result *candidate,
        const nv14_replay_trace_result *reference,
        int64_t reference_offset,
        int64_t reference_completion_exit_index,
        size_t *candidate_index_out,
        size_t *reference_index_out,
    ) noexcept nogil
    nv14_replay_trace_status nv14_replay_trace_run(
        const nv14_level *level,
        const nv14_input *inputs,
        size_t input_count,
        size_t trace_stride,
        nv14_replay_trace_result *result_out,
        nv14_error *error_out,
    ) noexcept nogil


cdef extern from "nv14_patch.h":
    cdef unsigned int NV14_PATCH_ABI_VERSION

    ctypedef enum nv14_patch_tie_policy:
        NV14_PATCH_TIE_SUPPLIED_ORDER
        NV14_PATCH_TIE_LOW_EDIT_LEX

    ctypedef struct nv14_patch_assignment:
        size_t frame
        nv14_input input

    ctypedef struct nv14_patch_span:
        size_t first_assignment
        size_t assignment_count

    ctypedef struct nv14_patch_spec:
        uint32_t abi_version
        uint32_t struct_size
        const nv14_input *replay
        size_t replay_count
        size_t target_frame
        const nv14_patch_assignment *assignments
        size_t assignment_count
        const nv14_patch_span *patches
        size_t patch_count
        const nv14_search_trace_target *trace_target
        const nv14_search_interaction_atom *required_atoms
        size_t required_atom_count
        const nv14_search_interaction_group *required_groups
        size_t required_group_count
        const nv14_search_interaction_atom *avoided_atoms
        size_t avoided_atom_count
        const nv14_search_interaction_group *avoided_groups
        size_t avoided_group_count
        const size_t *required_jump_frames
        size_t required_jump_count
        const size_t *ignored_jump_frames
        size_t ignored_jump_count
        uint8_t required_jump_any
        uint8_t prune_inactive_jump
        uint8_t tie_policy
        uint8_t capture_endpoints
        uint64_t minimum_jump_events
        uint64_t max_simulated_ticks
        const nv14_state *prefix_state
        size_t prefix_frame
        nv14_search_cancel_fn cancel
        void *cancel_userdata
        uint64_t cancel_poll_interval

    ctypedef struct nv14_patch_candidate_result:
        uint8_t feasible
        uint8_t has_endpoint
        uint8_t dead
        uint8_t inactive_jump_pruned
        uint8_t avoided_interaction_pruned
        double score
        nv14_player_snapshot endpoint

    ctypedef struct nv14_patch_stats:
        uint64_t branches
        uint64_t simulated_ticks
        uint64_t cloned_states
        uint64_t inactive_jump_prunes
        uint64_t dead_prunes
        uint64_t avoided_interaction_prunes

    ctypedef struct nv14_patch_result:
        nv14_patch_candidate_result *candidates
        size_t candidate_count
        size_t best_patch_index
        uint8_t budget_exhausted
        nv14_patch_stats stats

    int nv14_patch_result_init(
        nv14_patch_result *result,
        size_t caller_size,
    ) noexcept nogil
    nv14_search_status nv14_patch_run(
        const nv14_level *level,
        const nv14_patch_spec *spec,
        nv14_patch_result *result_out,
        nv14_error *error_out,
    ) noexcept nogil
    void nv14_patch_result_destroy(nv14_patch_result *result) noexcept nogil


cdef void *_checked_alloc(
    size_t count,
    size_t item_size,
    str description,
) except NULL:
    cdef void *result
    if count == 0:
        raise RuntimeError("zero-sized native allocation was requested")
    if item_size != 0 and count > (<size_t>-1) // item_size:
        raise OverflowError(f"{description} is too large")
    result = PyMem_Malloc(count * item_size)
    if result == NULL:
        raise MemoryError(f"unable to allocate {description}")
    return result


cdef void *_checked_calloc(
    size_t count,
    size_t item_size,
    str description,
) except NULL:
    cdef void *result = _checked_alloc(count, item_size, description)
    memset(result, 0, count * item_size)
    return result


cdef int _as_size(object value, size_t *output, str description) except -1:
    cdef object converted
    try:
        converted = _operator.index(value)
    except TypeError as exc:
        raise TypeError(f"{description} must be an integer") from exc
    if converted < 0:
        raise OverflowError(f"{description} must be non-negative")
    output[0] = converted
    return 0


cdef int _as_u64(object value, uint64_t *output, str description) except -1:
    cdef object converted
    try:
        converted = _operator.index(value)
    except TypeError as exc:
        raise TypeError(f"{description} must be an integer") from exc
    if converted < 0:
        raise OverflowError(f"{description} must be non-negative")
    output[0] = converted
    return 0


cdef int _as_i64(object value, int64_t *output, str description) except -1:
    cdef object converted
    try:
        converted = _operator.index(value)
    except TypeError as exc:
        raise TypeError(f"{description} must be an integer") from exc
    if converted < -(1 << 63) or converted > (1 << 63) - 1:
        raise OverflowError(f"{description} exceeds signed 64-bit range")
    output[0] = converted
    return 0


cdef long _as_long(object value, str description) except? -1:
    cdef object converted
    try:
        converted = _operator.index(value)
    except TypeError as exc:
        raise TypeError(f"{description} must be an integer") from exc
    return converted


cdef object _required(object mapping, str key, object alias=None):
    try:
        return mapping[key]
    except KeyError:
        if alias is not None:
            try:
                return mapping[alias]
            except KeyError:
                pass
    raise KeyError(f"native search payload is missing {key}")


cdef int _marshal_inputs(
    object frames,
    nv14_input **inputs_out,
    size_t *count_out,
    str description,
    bint require_nonempty,
) except -1:
    cdef tuple sequence = tuple(frames)
    cdef Py_ssize_t count = len(sequence)
    cdef Py_ssize_t index
    cdef nv14_input *inputs = NULL
    if require_nonempty and count == 0:
        raise ValueError(f"{description} must not be empty")
    if count > 0:
        inputs = <nv14_input *>_checked_alloc(
            <size_t>count,
            sizeof(nv14_input),
            description,
        )
    try:
        for index in range(count):
            _fill_input(sequence[index], &inputs[index])
    except BaseException:
        PyMem_Free(inputs)
        raise
    inputs_out[0] = inputs
    count_out[0] = <size_t>count
    return 0


cdef int _marshal_sizes(
    object values,
    size_t **values_out,
    size_t *count_out,
    str description,
) except -1:
    cdef tuple sequence = tuple(values)
    cdef Py_ssize_t count = len(sequence)
    cdef Py_ssize_t index
    cdef size_t *result = NULL
    if count > 0:
        result = <size_t *>_checked_alloc(
            <size_t>count,
            sizeof(size_t),
            description,
        )
    try:
        for index in range(count):
            _as_size(sequence[index], &result[index], description)
    except BaseException:
        PyMem_Free(result)
        raise
    values_out[0] = result
    count_out[0] = <size_t>count
    return 0


cdef int _marshal_targets(
    object values,
    nv14_search_target **targets_out,
    size_t *count_out,
    str description,
) except -1:
    cdef tuple sequence = tuple(values)
    cdef Py_ssize_t count = len(sequence)
    cdef Py_ssize_t index
    cdef tuple pair
    cdef nv14_search_target *targets = NULL
    if count > 0:
        targets = <nv14_search_target *>_checked_alloc(
            <size_t>count,
            sizeof(nv14_search_target),
            description,
        )
    try:
        for index in range(count):
            pair = tuple(sequence[index])
            if len(pair) != 2:
                raise ValueError("each native target must be an (x, y) pair")
            targets[index].x = float(pair[0])
            targets[index].y = float(pair[1])
    except BaseException:
        PyMem_Free(targets)
        raise
    targets_out[0] = targets
    count_out[0] = <size_t>count
    return 0


cdef int _marshal_window(
    object value,
    uint8_t *present_out,
    double *minimum_out,
    double *maximum_out,
    str description,
) except -1:
    cdef tuple pair
    if value is None:
        present_out[0] = 0
        return 0
    pair = tuple(value)
    if len(pair) != 2:
        raise ValueError(f"{description} must contain minimum and maximum")
    minimum_out[0] = float(pair[0])
    maximum_out[0] = float(pair[1])
    present_out[0] = 1
    return 0


cdef int _marshal_groups(
    object values,
    nv14_search_interaction_atom **atoms_out,
    size_t *atom_count_out,
    nv14_search_interaction_group **groups_out,
    size_t *group_count_out,
    str description,
) except -1:
    cdef tuple outer = tuple(values)
    cdef list materialized = []
    cdef tuple group
    cdef tuple pair
    cdef Py_ssize_t group_count = len(outer)
    cdef Py_ssize_t group_index
    cdef Py_ssize_t atom_index = 0
    cdef Py_ssize_t current_index
    cdef size_t flat_count = 0
    cdef long kind
    cdef nv14_search_interaction_atom *atoms = NULL
    cdef nv14_search_interaction_group *groups = NULL

    for group_index in range(group_count):
        group = tuple(outer[group_index])
        if not group:
            raise ValueError("interaction groups must not be empty")
        materialized.append(group)
        if <size_t>len(group) > (<size_t>-1) - flat_count:
            raise OverflowError("interaction atom array is too large")
        flat_count += <size_t>len(group)

    if group_count > 0:
        groups = <nv14_search_interaction_group *>_checked_alloc(
            <size_t>group_count,
            sizeof(nv14_search_interaction_group),
            "native interaction groups",
        )
    if flat_count > 0:
        atoms = <nv14_search_interaction_atom *>_checked_calloc(
            flat_count,
            sizeof(nv14_search_interaction_atom),
            "native interaction atoms",
        )
    try:
        for group_index in range(group_count):
            group = materialized[group_index]
            groups[group_index].first_atom = <size_t>atom_index
            groups[group_index].atom_count = <size_t>len(group)
            for current_index in range(len(group)):
                pair = tuple(group[current_index])
                if len(pair) != 2:
                    raise ValueError(
                        "interaction atoms must be (kind, index) pairs"
                    )
                kind = _as_long(pair[0], "interaction kind")
                if (
                    kind < NV14_SEARCH_INTERACTION_GOLD
                    or kind > NV14_SEARCH_INTERACTION_TRAPDOOR
                ):
                    raise ValueError(f"unknown native interaction kind {kind}")
                atoms[atom_index].kind = <uint8_t>kind
                _as_size(pair[1], &atoms[atom_index].index, "interaction index")
                atom_index += 1
    except BaseException:
        PyMem_Free(atoms)
        PyMem_Free(groups)
        raise

    atoms_out[0] = atoms
    atom_count_out[0] = flat_count
    groups_out[0] = groups
    group_count_out[0] = <size_t>group_count
    return 0


cdef int _marshal_index_flags(
    object values,
    size_t flag_count,
    uint8_t **flags_out,
    str description,
) except -1:
    cdef tuple sequence = tuple(values)
    cdef Py_ssize_t index
    cdef size_t flag_index
    cdef uint8_t *flags = NULL
    if flag_count > 0:
        flags = <uint8_t *>_checked_calloc(flag_count, 1, description)
    try:
        for index in range(len(sequence)):
            _as_size(sequence[index], &flag_index, description)
            if flag_index >= flag_count:
                raise ValueError(f"{description} contains an out-of-range index")
            flags[flag_index] = 1
    except BaseException:
        PyMem_Free(flags)
        raise
    flags_out[0] = flags
    return 0


cdef int _marshal_missing_jump_flags(
    object values,
    const size_t *required_frames,
    size_t required_count,
    uint8_t **flags_out,
) except -1:
    cdef tuple sequence = tuple(values)
    cdef Py_ssize_t index
    cdef size_t required_index
    cdef size_t frame
    cdef bint found
    cdef uint8_t *flags = NULL
    if required_count > 0:
        flags = <uint8_t *>_checked_calloc(
            required_count,
            1,
            "incumbent missing-jump flags",
        )
    try:
        for index in range(len(sequence)):
            _as_size(sequence[index], &frame, "missing jump frame")
            found = False
            for required_index in range(required_count):
                if required_frames[required_index] == frame:
                    flags[required_index] = 1
                    found = True
                    break
            if not found:
                raise ValueError(
                    f"incumbent missing jump frame {frame} is not required"
                )
    except BaseException:
        PyMem_Free(flags)
        raise
    flags_out[0] = flags
    return 0


cdef int _marshal_nonnegative_mask(
    object value,
    uint64_t **words_out,
    size_t *word_count_out,
    str description,
) except -1:
    cdef object integer
    cdef object current
    cdef size_t word_count
    cdef size_t index
    cdef uint64_t *words = NULL
    try:
        integer = _operator.index(value)
    except TypeError as exc:
        raise TypeError(f"{description} must be a non-negative integer") from exc
    if integer < 0:
        raise ValueError(f"{description} must be non-negative")
    word_count = <size_t>((integer.bit_length() + 63) // 64)
    if word_count > 0:
        words = <uint64_t *>_checked_calloc(
            word_count,
            sizeof(uint64_t),
            description,
        )
    current = integer
    try:
        for index in range(word_count):
            words[index] = current & ((1 << 64) - 1)
            current >>= 64
    except BaseException:
        PyMem_Free(words)
        raise
    words_out[0] = words
    word_count_out[0] = word_count
    return 0


cdef class _SearchMarshal:
    cdef nv14_search_spec spec
    cdef nv14_search_trace_target trace_target
    cdef nv14_input *replay
    cdef size_t *mutable_frames
    cdef size_t *choices_begin
    cdef nv14_input *choices
    cdef nv14_search_target *targets
    cdef nv14_search_interaction_atom *required_atoms
    cdef nv14_search_interaction_group *required_groups
    cdef nv14_search_interaction_atom *avoided_atoms
    cdef nv14_search_interaction_group *avoided_groups
    cdef uint8_t *incumbent_missing_requirements
    cdef uint8_t *incumbent_violated_avoidances
    cdef size_t *required_jump_frames
    cdef uint8_t *incumbent_missing_jumps
    cdef size_t *ignored_jump_frames
    cdef uint64_t *trace_collected_gold
    cdef uint64_t *trace_exploded_mine
    cdef uint64_t *trace_open_exit
    cdef uint64_t *trace_opened_locked_door
    cdef uint64_t *trace_triggered_trapdoor

    def __cinit__(self):
        memset(&self.spec, 0, sizeof(nv14_search_spec))
        memset(&self.trace_target, 0, sizeof(nv14_search_trace_target))
        self.replay = NULL
        self.mutable_frames = NULL
        self.choices_begin = NULL
        self.choices = NULL
        self.targets = NULL
        self.required_atoms = NULL
        self.required_groups = NULL
        self.avoided_atoms = NULL
        self.avoided_groups = NULL
        self.incumbent_missing_requirements = NULL
        self.incumbent_violated_avoidances = NULL
        self.required_jump_frames = NULL
        self.incumbent_missing_jumps = NULL
        self.ignored_jump_frames = NULL
        self.trace_collected_gold = NULL
        self.trace_exploded_mine = NULL
        self.trace_open_exit = NULL
        self.trace_opened_locked_door = NULL
        self.trace_triggered_trapdoor = NULL

    def __dealloc__(self):
        PyMem_Free(self.replay)
        PyMem_Free(self.mutable_frames)
        PyMem_Free(self.choices_begin)
        PyMem_Free(self.choices)
        PyMem_Free(self.targets)
        PyMem_Free(self.required_atoms)
        PyMem_Free(self.required_groups)
        PyMem_Free(self.avoided_atoms)
        PyMem_Free(self.avoided_groups)
        PyMem_Free(self.incumbent_missing_requirements)
        PyMem_Free(self.incumbent_violated_avoidances)
        PyMem_Free(self.required_jump_frames)
        PyMem_Free(self.incumbent_missing_jumps)
        PyMem_Free(self.ignored_jump_frames)
        PyMem_Free(self.trace_collected_gold)
        PyMem_Free(self.trace_exploded_mine)
        PyMem_Free(self.trace_open_exit)
        PyMem_Free(self.trace_opened_locked_door)
        PyMem_Free(self.trace_triggered_trapdoor)

    cdef int _load_choices(self, object values) except -1:
        cdef tuple outer = tuple(values)
        cdef list groups = []
        cdef tuple group
        cdef Py_ssize_t group_index
        cdef Py_ssize_t item_index
        cdef Py_ssize_t flat_index = 0
        cdef size_t flat_count = 0
        if <size_t>len(outer) != self.spec.mutable_count:
            raise ValueError(
                "native search requires one choice group per mutable frame"
            )
        self.choices_begin = <size_t *>_checked_alloc(
            self.spec.mutable_count + 1,
            sizeof(size_t),
            "native choice offsets",
        )
        self.choices_begin[0] = 0
        for group_index in range(len(outer)):
            group = tuple(outer[group_index])
            if not group:
                raise ValueError("native search choice groups must not be empty")
            groups.append(group)
            if <size_t>len(group) > (<size_t>-1) - flat_count:
                raise OverflowError("native choice array is too large")
            flat_count += <size_t>len(group)
            self.choices_begin[group_index + 1] = flat_count
        if flat_count > 0:
            self.choices = <nv14_input *>_checked_alloc(
                flat_count,
                sizeof(nv14_input),
                "native choice array",
            )
        for group_index in range(len(groups)):
            group = groups[group_index]
            for item_index in range(len(group)):
                _fill_input(group[item_index], &self.choices[flat_index])
                flat_index += 1
        self.spec.choices_begin = self.choices_begin
        self.spec.choices = self.choices
        self.spec.choice_count = flat_count
        return 0

    cdef int _load_trace_target(self, object mapping) except -1:
        cdef long player_state
        cdef long wall_x
        cdef long floor_x
        cdef long floor_y
        cdef nv14_search_trace_target *target = &self.trace_target
        if not isinstance(mapping, _Mapping):
            raise TypeError("trace_target must be a mapping")

        target.x = float(_required(mapping, "x"))
        target.y = float(_required(mapping, "y"))
        target.vx = float(_required(mapping, "vx"))
        target.vy = float(_required(mapping, "vy"))
        player_state = _as_long(
            _required(mapping, "player_state"),
            "player_state",
        )
        wall_x = _as_long(_required(mapping, "wall_x"), "wall_x")
        floor_x = _as_long(_required(mapping, "floor_x"), "floor_x")
        floor_y = _as_long(_required(mapping, "floor_y"), "floor_y")
        # Validate the semantic domain, not merely the backing C integer
        # width.  Apart from rejecting states the native scorer cannot use,
        # this avoids Cython spelling INT32_MIN as ``-2147483648L``.  MSVC's
        # 32-bit ``long`` gives that expression unsigned comparison semantics,
        # which made every ordinary non-negative player state look too small
        # on Windows.
        if player_state < 0 or player_state > 7:
            raise ValueError("trace_target player_state is out of range")
        if (
            wall_x < -1
            or wall_x > 1
            or floor_x < -1
            or floor_x > 1
            or floor_y < -1
            or floor_y > 1
        ):
            raise ValueError("trace_target normal bin is out of range")
        target.player_state = <int32_t>player_state
        target.wall_x = <int8_t>wall_x
        target.floor_x = <int8_t>floor_x
        target.floor_y = <int8_t>floor_y
        target.in_air = <uint8_t>bool(_required(mapping, "in_air"))
        target.near_wall = <uint8_t>bool(_required(mapping, "near_wall"))
        target.previous_jump_held = <uint8_t>bool(
            _required(mapping, "previous_jump_held")
        )
        target.position_weight = float(_required(mapping, "position_weight"))
        target.velocity_weight = float(_required(mapping, "velocity_weight"))
        target.contact_mismatch_penalty = float(
            _required(mapping, "contact_mismatch_penalty")
        )
        target.in_air_mismatch_penalty = float(
            _required(mapping, "in_air_mismatch_penalty")
        )
        target.near_wall_mismatch_penalty = float(
            _required(mapping, "near_wall_mismatch_penalty")
        )
        target.gold_bit_penalty = float(_required(mapping, "gold_bit_penalty"))
        target.mine_bit_penalty = float(_required(mapping, "mine_bit_penalty"))
        target.exit_bit_penalty = float(_required(mapping, "exit_bit_penalty"))
        target.locked_door_bit_penalty = float(
            _required(mapping, "locked_door_bit_penalty")
        )
        target.trapdoor_bit_penalty = float(
            _required(mapping, "trapdoor_bit_penalty")
        )

        _marshal_nonnegative_mask(
            _required(mapping, "collected_gold_mask"),
            &self.trace_collected_gold,
            &target.collected_gold_word_count,
            "collected_gold_mask",
        )
        _marshal_nonnegative_mask(
            _required(mapping, "exploded_mine_mask"),
            &self.trace_exploded_mine,
            &target.exploded_mine_word_count,
            "exploded_mine_mask",
        )
        _marshal_nonnegative_mask(
            _required(mapping, "open_exit_mask"),
            &self.trace_open_exit,
            &target.open_exit_word_count,
            "open_exit_mask",
        )
        _marshal_nonnegative_mask(
            _required(mapping, "opened_locked_door_mask"),
            &self.trace_opened_locked_door,
            &target.opened_locked_door_word_count,
            "opened_locked_door_mask",
        )
        _marshal_nonnegative_mask(
            _required(mapping, "triggered_trapdoor_mask"),
            &self.trace_triggered_trapdoor,
            &target.triggered_trapdoor_word_count,
            "triggered_trapdoor_mask",
        )
        target.collected_gold = self.trace_collected_gold
        target.exploded_mine = self.trace_exploded_mine
        target.open_exit = self.trace_open_exit
        target.opened_locked_door = self.trace_opened_locked_door
        target.triggered_trapdoor = self.trace_triggered_trapdoor
        self.spec.trace_target = target
        return 0

    cdef int load(self, object frames, object payload) except -1:
        cdef object value
        cdef long objective
        if not isinstance(payload, _Mapping):
            raise TypeError("native search payload must be a mapping")
        self.spec.abi_version = NV14_SEARCH_ABI_VERSION
        self.spec.struct_size = sizeof(nv14_search_spec)

        _marshal_inputs(
            frames,
            &self.replay,
            &self.spec.replay_count,
            "native search replay",
            True,
        )
        self.spec.replay = self.replay
        _as_size(
            _required(payload, "target_frame"),
            &self.spec.target_frame,
            "target_frame",
        )
        _marshal_sizes(
            _required(payload, "mutable_frames"),
            &self.mutable_frames,
            &self.spec.mutable_count,
            "mutable_frames must be a sequence of integers",
        )
        self.spec.mutable_frames = self.mutable_frames
        if self.spec.mutable_count == 0:
            raise ValueError("native search requires mutable frames")
        if (
            self.spec.target_frame >= self.spec.replay_count
            or self.mutable_frames[0] >= self.spec.replay_count
        ):
            raise ValueError("native search frames exceed the supplied replay")
        self._load_choices(_required(payload, "choices"))

        objective = _as_long(_required(payload, "objective"), "objective")
        if objective < NV14_SEARCH_MAX_X or objective > NV14_SEARCH_CONSTANT:
            raise ValueError("unknown native search objective")
        self.spec.objective = <nv14_search_objective>objective

        value = _required(payload, "trace_target")
        if value is not None:
            self._load_trace_target(value)
        elif objective == NV14_SEARCH_TRACE_DISTANCE:
            raise ValueError(
                "trace-distance native search requires trace_target"
            )

        _marshal_targets(
            _required(payload, "targets"),
            &self.targets,
            &self.spec.target_count,
            "native target array",
        )
        self.spec.targets = self.targets
        _marshal_window(
            _required(payload, "x_window"),
            &self.spec.has_x_window,
            &self.spec.x_minimum,
            &self.spec.x_maximum,
            "x_window",
        )
        _marshal_window(
            _required(payload, "y_window"),
            &self.spec.has_y_window,
            &self.spec.y_minimum,
            &self.spec.y_maximum,
            "y_window",
        )
        _marshal_groups(
            _required(payload, "required_groups", "required_interactions"),
            &self.required_atoms,
            &self.spec.required_atom_count,
            &self.required_groups,
            &self.spec.required_group_count,
            "required_groups must be a sequence of interaction groups",
        )
        self.spec.required_atoms = self.required_atoms
        self.spec.required_groups = self.required_groups
        _marshal_groups(
            _required(payload, "avoided_groups", "avoided_interactions"),
            &self.avoided_atoms,
            &self.spec.avoided_atom_count,
            &self.avoided_groups,
            &self.spec.avoided_group_count,
            "avoided_groups must be a sequence of interaction groups",
        )
        self.spec.avoided_atoms = self.avoided_atoms
        self.spec.avoided_groups = self.avoided_groups
        _marshal_index_flags(
            _required(payload, "incumbent_missing_requirements"),
            self.spec.required_group_count,
            &self.incumbent_missing_requirements,
            "incumbent_missing_requirements",
        )
        self.spec.incumbent_missing_requirements = (
            self.incumbent_missing_requirements
        )
        _marshal_index_flags(
            _required(payload, "incumbent_violated_avoidances"),
            self.spec.avoided_group_count,
            &self.incumbent_violated_avoidances,
            "incumbent_violated_avoidances",
        )
        self.spec.incumbent_violated_avoidances = (
            self.incumbent_violated_avoidances
        )
        _marshal_sizes(
            _required(payload, "required_jump_frames"),
            &self.required_jump_frames,
            &self.spec.required_jump_count,
            "required_jump_frames must be a sequence of integers",
        )
        self.spec.required_jump_frames = self.required_jump_frames
        _marshal_missing_jump_flags(
            _required(
                payload,
                "incumbent_missing_jump_frames",
                "incumbent_missing_jumps",
            ),
            self.required_jump_frames,
            self.spec.required_jump_count,
            &self.incumbent_missing_jumps,
        )
        self.spec.incumbent_missing_jumps = self.incumbent_missing_jumps
        _marshal_sizes(
            _required(payload, "ignored_jump_frames"),
            &self.ignored_jump_frames,
            &self.spec.ignored_jump_count,
            "ignored_jump_frames must be a sequence of integers",
        )
        self.spec.ignored_jump_frames = self.ignored_jump_frames
        _as_u64(
            _required(payload, "minimum_jump_events"),
            &self.spec.minimum_jump_events,
            "minimum_jump_events",
        )
        self.spec.incumbent_score = float(_required(payload, "incumbent_score"))
        self.spec.incumbent_feasible = <uint8_t>bool(
            _required(payload, "incumbent_feasible")
        )
        self.spec.prune_inactive_jump = <uint8_t>bool(
            _required(payload, "prune_inactive_jump")
        )
        self.spec.physics_prune = <uint8_t>bool(
            _required(payload, "physics_prune")
        )
        self.spec.require_all_constraints = <uint8_t>bool(
            _required(payload, "require_all_constraints")
        )
        self.spec.required_jump_any = <uint8_t>bool(
            _required(payload, "required_jump_any")
        )
        self.spec.tie_break_low_edit_lex = <uint8_t>bool(
            _required(payload, "tie_break_low_edit_lex")
        )
        _as_u64(
            _required(payload, "max_simulated_ticks"),
            &self.spec.max_simulated_ticks,
            "max_simulated_ticks",
        )
        try:
            value = payload["skip_unchanged_final_step"]
        except KeyError:
            self.spec.skip_unchanged_final_step = 0
        else:
            self.spec.skip_unchanged_final_step = <uint8_t>bool(value)
        return 0


cdef class _PatchMarshal:
    cdef nv14_patch_spec spec
    cdef _SearchMarshal common
    cdef nv14_patch_assignment *assignments
    cdef nv14_patch_span *patches

    def __cinit__(self):
        memset(&self.spec, 0, sizeof(nv14_patch_spec))
        self.common = _SearchMarshal()
        self.assignments = NULL
        self.patches = NULL

    def __dealloc__(self):
        PyMem_Free(self.assignments)
        PyMem_Free(self.patches)

    cdef int _load_patches(self, object values) except -1:
        cdef tuple outer = tuple(values)
        cdef list materialized = []
        cdef tuple patch
        cdef tuple pair
        cdef Py_ssize_t patch_index
        cdef Py_ssize_t assignment_index = 0
        cdef Py_ssize_t current_index
        cdef size_t assignment_count = 0
        if len(outer) > 0:
            self.patches = <nv14_patch_span *>_checked_alloc(
                <size_t>len(outer),
                sizeof(nv14_patch_span),
                "native patch spans",
            )
        for patch_index in range(len(outer)):
            patch = tuple(outer[patch_index])
            if not patch:
                raise ValueError("native patches must not be empty")
            materialized.append(patch)
            if <size_t>len(patch) > (<size_t>-1) - assignment_count:
                raise OverflowError("native patch assignment array is too large")
            self.patches[patch_index].first_assignment = assignment_count
            self.patches[patch_index].assignment_count = <size_t>len(patch)
            assignment_count += <size_t>len(patch)
        if assignment_count > 0:
            self.assignments = <nv14_patch_assignment *>_checked_alloc(
                assignment_count,
                sizeof(nv14_patch_assignment),
                "native patch assignments",
            )
        for patch_index in range(len(materialized)):
            patch = materialized[patch_index]
            for current_index in range(len(patch)):
                pair = tuple(patch[current_index])
                if len(pair) != 2:
                    raise ValueError(
                        "patch assignments must be (frame, input) pairs"
                    )
                _as_size(
                    pair[0],
                    &self.assignments[assignment_index].frame,
                    "patch assignment frame",
                )
                _fill_input(
                    pair[1],
                    &self.assignments[assignment_index].input,
                )
                assignment_index += 1
        self.spec.assignments = self.assignments
        self.spec.assignment_count = assignment_count
        self.spec.patches = self.patches
        self.spec.patch_count = <size_t>len(outer)
        return 0

    cdef int load(self, object frames, object payload) except -1:
        cdef object value
        cdef long tie_policy
        if not isinstance(payload, _Mapping):
            raise TypeError("native patch payload must be a mapping")
        self.spec.abi_version = NV14_PATCH_ABI_VERSION
        self.spec.struct_size = sizeof(nv14_patch_spec)
        _marshal_inputs(
            frames,
            &self.common.replay,
            &self.spec.replay_count,
            "native patch replay",
            True,
        )
        self.spec.replay = self.common.replay
        _as_size(
            _required(payload, "target_frame"),
            &self.spec.target_frame,
            "target_frame",
        )
        self._load_patches(_required(payload, "patches"))
        value = _required(payload, "trace_target")
        if value is not None:
            self.common._load_trace_target(value)
            self.spec.trace_target = &self.common.trace_target
        _marshal_groups(
            _required(payload, "required_groups", "required_interactions"),
            &self.common.required_atoms,
            &self.spec.required_atom_count,
            &self.common.required_groups,
            &self.spec.required_group_count,
            "required_groups must be a sequence of interaction groups",
        )
        self.spec.required_atoms = self.common.required_atoms
        self.spec.required_groups = self.common.required_groups
        _marshal_groups(
            _required(payload, "avoided_groups", "avoided_interactions"),
            &self.common.avoided_atoms,
            &self.spec.avoided_atom_count,
            &self.common.avoided_groups,
            &self.spec.avoided_group_count,
            "avoided_groups must be a sequence of interaction groups",
        )
        self.spec.avoided_atoms = self.common.avoided_atoms
        self.spec.avoided_groups = self.common.avoided_groups
        _marshal_sizes(
            _required(payload, "required_jump_frames"),
            &self.common.required_jump_frames,
            &self.spec.required_jump_count,
            "required_jump_frames must be a sequence of integers",
        )
        self.spec.required_jump_frames = self.common.required_jump_frames
        _marshal_sizes(
            _required(payload, "ignored_jump_frames"),
            &self.common.ignored_jump_frames,
            &self.spec.ignored_jump_count,
            "ignored_jump_frames must be a sequence of integers",
        )
        self.spec.ignored_jump_frames = self.common.ignored_jump_frames
        self.spec.required_jump_any = <uint8_t>bool(
            _required(payload, "required_jump_any")
        )
        self.spec.prune_inactive_jump = <uint8_t>bool(
            _required(payload, "prune_inactive_jump")
        )
        self.spec.capture_endpoints = <uint8_t>bool(
            _required(payload, "capture_endpoints")
        )
        tie_policy = _as_long(_required(payload, "tie_policy"), "tie_policy")
        if (
            tie_policy < NV14_PATCH_TIE_SUPPLIED_ORDER
            or tie_policy > NV14_PATCH_TIE_LOW_EDIT_LEX
        ):
            raise ValueError("unknown native patch tie policy")
        self.spec.tie_policy = <uint8_t>tie_policy
        _as_u64(
            _required(payload, "minimum_jump_events"),
            &self.spec.minimum_jump_events,
            "minimum_jump_events",
        )
        _as_u64(
            _required(payload, "max_simulated_ticks"),
            &self.spec.max_simulated_ticks,
            "max_simulated_ticks",
        )
        return 0


cdef class _PatternMarshal:
    cdef nv14_pattern_search_spec spec
    cdef nv14_input *replay
    cdef nv14_input *inactive_inputs
    cdef nv14_input *active_inputs
    cdef nv14_search_target *targets
    cdef size_t *start_max_lengths
    cdef size_t *fixed_starts

    def __cinit__(self):
        memset(&self.spec, 0, sizeof(nv14_pattern_search_spec))
        self.replay = NULL
        self.inactive_inputs = NULL
        self.active_inputs = NULL
        self.targets = NULL
        self.start_max_lengths = NULL
        self.fixed_starts = NULL

    def __dealloc__(self):
        PyMem_Free(self.replay)
        PyMem_Free(self.inactive_inputs)
        PyMem_Free(self.active_inputs)
        PyMem_Free(self.targets)
        PyMem_Free(self.start_max_lengths)
        PyMem_Free(self.fixed_starts)

    cdef int load(self, object frames, object payload) except -1:
        cdef size_t inactive_count = 0
        cdef size_t active_count = 0
        cdef long objective
        cdef object event_value
        cdef uint64_t event_mask
        if not isinstance(payload, _Mapping):
            raise TypeError("native pattern-search payload must be a mapping")
        self.spec.abi_version = NV14_SEARCH_ABI_VERSION
        self.spec.struct_size = sizeof(nv14_pattern_search_spec)
        _marshal_inputs(
            frames,
            &self.replay,
            &self.spec.replay_count,
            "native pattern replay",
            True,
        )
        self.spec.replay = self.replay
        _as_size(_required(payload, "range_start"), &self.spec.range_start, "range_start")
        _as_size(_required(payload, "range_end"), &self.spec.range_end, "range_end")
        _as_size(_required(payload, "target_frame"), &self.spec.target_frame, "target_frame")
        _as_size(_required(payload, "run_count_min"), &self.spec.run_count_min, "run_count_min")
        _as_size(_required(payload, "run_count_max"), &self.spec.run_count_max, "run_count_max")
        _as_size(_required(payload, "run_length_min"), &self.spec.run_length_min, "run_length_min")
        _as_size(_required(payload, "minimum_gap"), &self.spec.minimum_gap, "minimum_gap")
        _as_size(_required(payload, "top_results"), &self.spec.top_results, "top_results")
        _as_size(_required(payload, "shard_index"), &self.spec.shard_index, "shard_index")
        _as_size(_required(payload, "shard_count"), &self.spec.shard_count, "shard_count")
        _marshal_inputs(
            _required(payload, "inactive_inputs"),
            &self.inactive_inputs,
            &inactive_count,
            "inactive_inputs",
            True,
        )
        _marshal_inputs(
            _required(payload, "active_inputs"),
            &self.active_inputs,
            &active_count,
            "active_inputs",
            True,
        )
        if inactive_count != active_count:
            raise ValueError(
                "inactive_inputs and active_inputs must have equal lengths"
            )
        self.spec.inactive_inputs = self.inactive_inputs
        self.spec.active_inputs = self.active_inputs
        self.spec.pattern_input_count = inactive_count
        objective = _as_long(_required(payload, "objective"), "objective")
        if objective < NV14_SEARCH_MAX_X or objective > NV14_SEARCH_MIN_DISTANCE:
            raise ValueError("unknown native pattern objective")
        self.spec.objective = <nv14_search_objective>objective
        _marshal_targets(
            _required(payload, "targets"),
            &self.targets,
            &self.spec.target_count,
            "native pattern target array",
        )
        self.spec.targets = self.targets
        _marshal_window(
            _required(payload, "x_window"),
            &self.spec.has_x_window,
            &self.spec.x_minimum,
            &self.spec.x_maximum,
            "x_window",
        )
        _marshal_window(
            _required(payload, "y_window"),
            &self.spec.has_y_window,
            &self.spec.y_minimum,
            &self.spec.y_maximum,
            "y_window",
        )
        _marshal_sizes(
            _required(payload, "start_max_lengths"),
            &self.start_max_lengths,
            &self.spec.start_max_length_count,
            "start_max_lengths must be a sequence of integers",
        )
        self.spec.start_max_lengths = self.start_max_lengths
        _marshal_sizes(
            _required(payload, "fixed_starts"),
            &self.fixed_starts,
            &self.spec.fixed_start_count,
            "fixed_starts must be a sequence of integers",
        )
        self.spec.fixed_starts = self.fixed_starts
        event_value = _required(payload, "required_start_event_mask")
        _as_u64(event_value, &event_mask, "required_start_event_mask")
        if event_mask > (<uint32_t>-1):
            raise OverflowError("required_start_event_mask exceeds uint32")
        self.spec.required_start_event_mask = <uint32_t>event_mask
        return 0


cdef object _words_to_int(const uint64_t *words, size_t word_count):
    cdef object value = 0
    cdef size_t index = word_count
    while index > 0:
        index -= 1
        value = (value << 64) | words[index]
    return value


cdef tuple _u64_tuple(const uint64_t *values, size_t count):
    cdef list result = []
    cdef size_t index
    for index in range(count):
        result.append(values[index])
    return tuple(result)


cdef tuple _trace_point_tuple(
    const nv14_replay_trace_result *result,
    size_t index,
):
    cdef const nv14_replay_trace_point *point = &result.trace[index]
    cdef const uint64_t *gold = NULL
    cdef const uint64_t *mines = NULL
    cdef const uint64_t *exits = NULL
    cdef const uint64_t *locked = NULL
    cdef const uint64_t *traps = NULL
    if result.collected_gold_word_count > 0:
        gold = (
            result.trace_collected_gold_words
            + index * result.collected_gold_word_count
        )
    if result.exploded_mine_word_count > 0:
        mines = (
            result.trace_exploded_mine_words
            + index * result.exploded_mine_word_count
        )
    if result.open_exit_word_count > 0:
        exits = (
            result.trace_open_exit_words
            + index * result.open_exit_word_count
        )
    if result.door_word_count > 0:
        locked = (
            result.trace_opened_locked_door_words
            + index * result.door_word_count
        )
        traps = (
            result.trace_triggered_trapdoor_words
            + index * result.door_word_count
        )
    return (
        point.tick,
        point.x,
        point.y,
        point.vx,
        point.vy,
        point.player_state,
        bool(point.in_air),
        bool(point.near_wall),
        point.wall_x,
        point.floor_x,
        point.floor_y,
        bool(point.previous_jump_held),
        point.jump_events,
        _words_to_int(gold, result.collected_gold_word_count),
        _words_to_int(mines, result.exploded_mine_word_count),
        _words_to_int(exits, result.open_exit_word_count),
        _words_to_int(locked, result.door_word_count),
        _words_to_int(traps, result.door_word_count),
        bool(point.complete),
        bool(point.dead),
        point.gold_bonus_ticks,
    )


cdef tuple _trace_masks_tuple(
    const nv14_replay_trace_result *result,
    size_t index,
):
    cdef const uint64_t *gold = NULL
    cdef const uint64_t *mines = NULL
    cdef const uint64_t *exits = NULL
    cdef const uint64_t *locked = NULL
    cdef const uint64_t *traps = NULL
    if result.collected_gold_word_count > 0:
        gold = (
            result.trace_collected_gold_words
            + index * result.collected_gold_word_count
        )
    if result.exploded_mine_word_count > 0:
        mines = (
            result.trace_exploded_mine_words
            + index * result.exploded_mine_word_count
        )
    if result.open_exit_word_count > 0:
        exits = (
            result.trace_open_exit_words
            + index * result.open_exit_word_count
        )
    if result.door_word_count > 0:
        locked = (
            result.trace_opened_locked_door_words
            + index * result.door_word_count
        )
        traps = (
            result.trace_triggered_trapdoor_words
            + index * result.door_word_count
        )
    return (
        _words_to_int(gold, result.collected_gold_word_count),
        _words_to_int(mines, result.exploded_mine_word_count),
        _words_to_int(exits, result.open_exit_word_count),
        _words_to_int(locked, result.door_word_count),
        _words_to_int(traps, result.door_word_count),
    )


cdef class NativeTrace:
    """Owned C replay-analysis buffer with lazy Python materialisation."""

    cdef nv14_replay_trace_result _result
    cdef bint _ready

    def __cinit__(self):
        memset(&self._result, 0, sizeof(nv14_replay_trace_result))
        self._ready = bool(
            nv14_replay_trace_result_init(
                &self._result,
                sizeof(nv14_replay_trace_result),
            )
        )
        if not self._ready:
            raise RuntimeError("initialise native replay trace result")

    def __dealloc__(self):
        if self._ready:
            nv14_replay_trace_result_destroy(&self._result)
            self._ready = False

    cdef nv14_replay_trace_result *pointer(self) noexcept:
        return &self._result

    @property
    def trace_count(self):
        return self._result.trace_count

    def point_at(self, index):
        """Materialise one trace row by sequence index."""
        cdef object converted = _operator.index(index)
        cdef object count = self._result.trace_count
        cdef size_t native_index
        if converted < 0:
            converted += count
        if converted < 0 or converted >= count:
            raise IndexError("native replay-analysis point index out of range")
        native_index = converted
        return _trace_point_tuple(&self._result, native_index)

    def point(self, tick):
        """Materialise the captured point at an exact frame, if present."""
        cdef uint64_t native_tick
        cdef size_t index = 0
        cdef int status
        _as_u64(tick, &native_tick, "trace tick")
        with nogil:
            status = nv14_replay_trace_find_point_index(
                &self._result, native_tick, &index
            )
        if status < 0:
            raise RuntimeError("query native replay-analysis point")
        if status == 0:
            return None
        return _trace_point_tuple(&self._result, index)

    def masks(self, tick):
        """Return the five persistent masks captured at an exact frame."""
        cdef uint64_t native_tick
        cdef size_t index = 0
        cdef int status
        _as_u64(tick, &native_tick, "trace tick")
        with nogil:
            status = nv14_replay_trace_find_point_index(
                &self._result, native_tick, &index
            )
        if status < 0:
            raise RuntimeError("query native replay-analysis masks")
        if status == 0:
            return None
        return _trace_masks_tuple(&self._result, index)

    def terminal_flags(self):
        """Return ``(complete, dead)`` without constructing a trace point."""
        cdef size_t count = self._result.trace_count
        cdef const nv14_replay_trace_point *point
        if count == 0:
            return None
        point = &self._result.trace[count - 1]
        return (bool(point.complete), bool(point.dead))

    def terminal_summary(self):
        """Return terminal ranking fields and masks without a point object."""
        cdef size_t count = self._result.trace_count
        cdef size_t index
        cdef const nv14_replay_trace_point *point
        cdef tuple masks
        if count == 0:
            return None
        index = count - 1
        point = &self._result.trace[index]
        masks = _trace_masks_tuple(&self._result, index)
        return (
            point.tick,
            point.x,
            point.y,
            point.player_state,
            bool(point.dead),
            bool(point.complete),
            masks[0],
            masks[1],
            masks[2],
            masks[3],
            masks[4],
        )

    def summary(self):
        """Return the terminal replay summary, excluding trajectory rows."""
        cdef nv14_replay_trace_result *result = &self._result
        return (
            result.finish_tick,
            result.dead_tick,
            result.last_tick,
            bool(result.unsupported),
            result.completed_exit_index,
            bool(result.has_pre_finish_exit_distance),
            result.pre_finish_exit_distance,
            result.gold_bonus_ticks,
            _words_to_int(
                result.final_collected_gold_words,
                result.collected_gold_word_count,
            ),
            _words_to_int(
                result.final_exploded_mine_words,
                result.exploded_mine_word_count,
            ),
            _words_to_int(
                result.final_open_exit_words,
                result.open_exit_word_count,
            ),
            _words_to_int(
                result.final_opened_locked_door_words,
                result.door_word_count,
            ),
            _words_to_int(
                result.final_triggered_trapdoor_words,
                result.door_word_count,
            ),
        )

    def successful_jumps(self):
        return _u64_tuple(
            self._result.successful_jumps,
            self._result.successful_jump_count,
        )

    def jump_edges(self):
        return _u64_tuple(
            self._result.jump_edges,
            self._result.jump_edge_count,
        )

    def missed_jump_edges(self):
        return _u64_tuple(
            self._result.missed_jump_edges,
            self._result.missed_jump_edge_count,
        )

    def jump_opportunity_windows(self):
        """Return exact inclusive pre-Think ranges that can invoke ``jump()``."""
        cdef list windows = []
        cdef size_t index
        for index in range(self._result.jump_callable_window_count):
            windows.append((
                self._result.jump_callable_windows[index].start_tick,
                self._result.jump_callable_windows[index].end_tick,
            ))
        return tuple(windows)

    def gold_events(self):
        cdef list events = []
        cdef size_t index
        for index in range(self._result.gold_event_count):
            events.append(
                (
                    self._result.gold_events[index].gold_index,
                    self._result.gold_events[index].tick,
                )
            )
        return tuple(events)

    def route_control_events(self):
        cdef list events = []
        cdef size_t index
        for index in range(self._result.route_control_event_count):
            events.append(
                (
                    self._result.route_control_events[index].kind,
                    self._result.route_control_events[index].index,
                    self._result.route_control_events[index].tick,
                )
            )
        return tuple(events)

    def materialize_trace(self):
        """Explicitly convert every captured row for reporting/debugging."""
        cdef list trace = []
        cdef size_t index
        for index in range(self._result.trace_count):
            trace.append(_trace_point_tuple(&self._result, index))
        return tuple(trace)

    def find_alignment(
        self,
        NativeTrace reference,
        *,
        objective,
        max_alignment,
        max_negative_alignment,
        scan_limit,
        reference_completion_exit_index,
        position_tolerance,
        velocity_tolerance,
        position_weight,
        velocity_weight,
        contact_mismatch_penalty,
        in_air_mismatch_penalty,
        near_wall_mismatch_penalty,
        gold_bit_penalty,
        mine_bit_penalty,
        exit_bit_penalty,
        locked_door_bit_penalty,
        trapdoor_bit_penalty,
    ):
        """Run the allocation-free generic trajectory alignment query."""
        cdef nv14_replay_alignment_spec spec
        cdef nv14_replay_alignment_result result
        cdef uint64_t native_objective
        cdef int status
        memset(&spec, 0, sizeof(nv14_replay_alignment_spec))
        memset(&result, 0, sizeof(nv14_replay_alignment_result))
        spec.abi_version = NV14_REPLAY_ANALYSIS_ABI_VERSION
        spec.struct_size = sizeof(nv14_replay_alignment_spec)
        result.abi_version = NV14_REPLAY_ANALYSIS_ABI_VERSION
        result.struct_size = sizeof(nv14_replay_alignment_result)
        _as_u64(objective, &native_objective, "alignment objective")
        if native_objective > NV14_REPLAY_ALIGNMENT_HIGHSCORE:
            raise ValueError("alignment objective is invalid")
        spec.objective = <uint8_t>native_objective
        _as_u64(max_alignment, &spec.max_alignment, "max alignment")
        _as_u64(
            max_negative_alignment,
            &spec.max_negative_alignment,
            "max negative alignment",
        )
        _as_u64(scan_limit, &spec.scan_limit, "alignment scan limit")
        _as_i64(
            reference_completion_exit_index,
            &spec.reference_completion_exit_index,
            "reference completion exit index",
        )
        spec.position_tolerance = float(position_tolerance)
        spec.velocity_tolerance = float(velocity_tolerance)
        spec.position_weight = float(position_weight)
        spec.velocity_weight = float(velocity_weight)
        spec.contact_mismatch_penalty = float(contact_mismatch_penalty)
        spec.in_air_mismatch_penalty = float(in_air_mismatch_penalty)
        spec.near_wall_mismatch_penalty = float(near_wall_mismatch_penalty)
        spec.gold_bit_penalty = float(gold_bit_penalty)
        spec.mine_bit_penalty = float(mine_bit_penalty)
        spec.exit_bit_penalty = float(exit_bit_penalty)
        spec.locked_door_bit_penalty = float(locked_door_bit_penalty)
        spec.trapdoor_bit_penalty = float(trapdoor_bit_penalty)
        with nogil:
            status = nv14_replay_trace_find_alignment(
                &self._result,
                &reference._result,
                &spec,
                &result,
            )
        if status < 0:
            raise RuntimeError("query native replay-analysis alignment")
        if status == 0 or not result.found:
            return None
        return (
            result.candidate_tick,
            result.reference_tick,
            result.offset,
            result.distance,
            bool(result.contact_matches),
            bool(result.static_matches),
            result.score_lead,
        )

    def find_route_divergence(
        self,
        NativeTrace reference,
        *,
        reference_offset=0,
        reference_completion_exit_index=-1,
    ):
        """Return the first persistent route-control mask divergence."""
        cdef int64_t native_offset
        cdef int64_t native_exit_index
        cdef size_t candidate_index = 0
        cdef size_t reference_index = 0
        cdef int status
        cdef tuple candidate_masks
        cdef tuple reference_masks
        cdef object completion_bit
        _as_i64(reference_offset, &native_offset, "reference offset")
        _as_i64(
            reference_completion_exit_index,
            &native_exit_index,
            "reference completion exit index",
        )
        with nogil:
            status = nv14_replay_trace_find_route_divergence(
                &self._result,
                &reference._result,
                native_offset,
                native_exit_index,
                &candidate_index,
                &reference_index,
            )
        if status < 0:
            raise RuntimeError("query native replay-analysis route divergence")
        if status == 0:
            return None
        candidate_masks = _trace_masks_tuple(&self._result, candidate_index)
        reference_masks = _trace_masks_tuple(
            &reference._result, reference_index
        )
        completion_bit = (
            0 if native_exit_index < 0 else (<object>1) << native_exit_index
        )
        return (
            self._result.trace[candidate_index].tick,
            reference._result.trace[reference_index].tick,
            completion_bit
            if (
                reference_masks[2] & completion_bit
                and not candidate_masks[2] & completion_bit
            )
            else 0,
            reference_masks[3] & ~candidate_masks[3],
            candidate_masks[4] & ~reference_masks[4],
        )

    def to_dict(self):
        """Explicit compatibility/debug materialisation of the full result."""
        cdef nv14_replay_trace_result *result = &self._result
        return {
            "finish_tick": result.finish_tick,
            "dead_tick": result.dead_tick,
            "last_tick": result.last_tick,
            "unsupported": bool(result.unsupported),
            "completed_exit_index": result.completed_exit_index,
            "has_pre_finish_exit_distance": bool(
                result.has_pre_finish_exit_distance
            ),
            "pre_finish_exit_distance": result.pre_finish_exit_distance,
            "gold_bonus_ticks": result.gold_bonus_ticks,
            "trace": self.materialize_trace(),
            "successful_jumps": self.successful_jumps(),
            "jump_edges": self.jump_edges(),
            "missed_jump_edges": self.missed_jump_edges(),
            "jump_opportunity_windows": self.jump_opportunity_windows(),
            "gold_events": self.gold_events(),
            "route_control_events": self.route_control_events(),
            "final_gold_mask": _words_to_int(
                result.final_collected_gold_words,
                result.collected_gold_word_count,
            ),
            "final_exploded_mine_mask": _words_to_int(
                result.final_exploded_mine_words,
                result.exploded_mine_word_count,
            ),
            "final_open_exit_mask": _words_to_int(
                result.final_open_exit_words,
                result.open_exit_word_count,
            ),
            "final_opened_locked_door_mask": _words_to_int(
                result.final_opened_locked_door_words,
                result.door_word_count,
            ),
            "final_triggered_trapdoor_mask": _words_to_int(
                result.final_triggered_trapdoor_words,
                result.door_word_count,
            ),
        }


# Public descriptive name for the v2.81 owner API.  Keep NativeTrace itself
# for source and third-party compatibility with the unified v2.79/v2.80 module.
NativeReplayAnalysis = NativeTrace


cdef tuple _inputs_to_tuple(const nv14_input *inputs, size_t count):
    cdef list result = []
    cdef size_t index
    cdef object trigger
    for index in range(count):
        trigger = (
            None
            if inputs[index].jump_trigger < 0
            else bool(inputs[index].jump_trigger)
        )
        result.append(
            (
                bool(inputs[index].left),
                bool(inputs[index].right),
                bool(inputs[index].jump),
                trigger,
            )
        )
    return tuple(result)


cdef tuple _flag_indices(const uint8_t *flags, size_t count):
    cdef list result = []
    cdef size_t index
    for index in range(count):
        if flags[index]:
            result.append(index)
    return tuple(result)


cdef tuple _missing_jump_frames(
    const uint8_t *flags,
    const size_t *frames,
    size_t count,
):
    cdef list result = []
    cdef size_t index
    for index in range(count):
        if flags[index]:
            result.append(frames[index])
    return tuple(result)


cdef dict _search_stats_dict(const nv14_search_stats *stats):
    return {
        "visited_nodes": stats.visited_nodes,
        "evaluated_leaves": stats.evaluated_leaves,
        "simulated_ticks": stats.simulated_ticks,
        "cloned_states": stats.cloned_states,
        "inactive_jump_prunes": stats.inactive_jump_prunes,
        "missed_jump_prunes": stats.missed_jump_prunes,
        "dead_prunes": stats.dead_prunes,
        "deduplicated_prunes": stats.deduplicated_prunes,
        "physics_prunes": stats.physics_prunes,
        "avoided_interaction_prunes": stats.avoided_interaction_prunes,
    }


cdef dict _search_result_dict(
    const nv14_search_result *result,
    _SearchMarshal marshal,
):
    return {
        "player": (
            _player_dict(&result.player)
            if result.has_player_snapshot
            else None
        ),
        "improved": bool(result.improved),
        "feasible": bool(result.feasible),
        "budget_exhausted": bool(result.budget_exhausted),
        "score": result.score,
        "best_inputs": _inputs_to_tuple(
            result.best_inputs,
            result.best_input_count,
        ),
        "missing_requirement_indices": _flag_indices(
            result.missing_requirements,
            result.missing_requirement_count,
        ),
        "violated_avoidance_indices": _flag_indices(
            result.violated_avoidances,
            result.violated_avoidance_count,
        ),
        "missing_jump_frames": _missing_jump_frames(
            result.missing_jumps,
            marshal.spec.required_jump_frames,
            result.missing_jump_count,
        ),
        "stats": _search_stats_dict(&result.stats),
    }


cdef dict _patch_stats_dict(const nv14_patch_stats *stats):
    return {
        "branches": stats.branches,
        "simulated_ticks": stats.simulated_ticks,
        "cloned_states": stats.cloned_states,
        "inactive_jump_prunes": stats.inactive_jump_prunes,
        "dead_prunes": stats.dead_prunes,
        "avoided_interaction_prunes": stats.avoided_interaction_prunes,
    }


cdef dict _patch_result_dict(const nv14_patch_result *result):
    cdef list candidates = []
    cdef size_t index
    cdef const nv14_patch_candidate_result *candidate
    for index in range(result.candidate_count):
        candidate = &result.candidates[index]
        candidates.append(
            {
                "player": (
                    _player_dict(&candidate.endpoint)
                    if candidate.has_endpoint
                    else None
                ),
                "feasible": bool(candidate.feasible),
                "has_endpoint": bool(candidate.has_endpoint),
                "dead": bool(candidate.dead),
                "inactive_jump_pruned": bool(candidate.inactive_jump_pruned),
                "avoided_interaction_pruned": bool(
                    candidate.avoided_interaction_pruned
                ),
                "score": candidate.score,
            }
        )
    return {
        "best_patch_index": (
            None if result.best_patch_index == (<size_t>-1)
            else result.best_patch_index
        ),
        "budget_exhausted": bool(result.budget_exhausted),
        "candidates": tuple(candidates),
        "stats": _patch_stats_dict(&result.stats),
    }


cdef dict _pattern_stats_dict(const nv14_pattern_search_stats *stats):
    return {
        "attempted_starts": stats.attempted_starts,
        "successful_starts": stats.successful_starts,
        "evaluated_candidates": stats.evaluated_candidates,
        "deduplicated_branches": stats.deduplicated_branches,
        "simulated_ticks": stats.simulated_ticks,
        "cloned_states": stats.cloned_states,
    }


cdef dict _pattern_result_dict(const nv14_pattern_search_result *result):
    cdef list candidates = []
    cdef list spans
    cdef size_t candidate_index
    cdef size_t span_index
    cdef const nv14_pattern_search_candidate *candidate
    for candidate_index in range(result.candidate_count):
        candidate = &result.candidates[candidate_index]
        spans = []
        for span_index in range(candidate.span_count):
            spans.append(
                (
                    candidate.spans[span_index].start_frame,
                    candidate.spans[span_index].length,
                )
            )
        candidates.append(
            {
                "spans": tuple(spans),
                "score": candidate.score,
                "player": _player_dict(&candidate.player),
            }
        )
    return {
        "candidates": tuple(candidates),
        "stats": _pattern_stats_dict(&result.stats),
    }


cdef str _native_error_text(nv14_error *error, nv14_status fallback):
    cdef const char *raw
    if error != NULL:
        raw = &error.message[0]
        if raw[0] != 0:
            return (<bytes>raw).decode("utf-8", "replace")
        if error.code != NV14_STATUS_OK:
            return _status_text(error.code)
    return _status_text(fallback)


cdef object _raise_search_status(
    nv14_search_status status,
    nv14_error *error,
    str operation,
):
    cdef str message
    if status == NV14_SEARCH_OUT_OF_MEMORY:
        raise MemoryError(f"{operation} exhausted memory")
    if status == NV14_SEARCH_INVALID_ARGUMENT:
        message = _native_error_text(error, NV14_STATUS_INVALID_ARGUMENT)
        raise ValueError(f"{operation}: {message}")
    if status == NV14_SEARCH_CORE_ERROR:
        if error != NULL and error.code != NV14_STATUS_OK:
            _raise_status(error.code, operation)
        raise RuntimeError(f"{operation}: native core error")
    if status == NV14_SEARCH_CANCELLED:
        raise KeyboardInterrupt(f"{operation} cancelled")
    raise RuntimeError(f"{operation}: native search status {<int>status}")


cdef class SearchSession:
    """Owned level and replay-prefix cache shared by every search kernel."""

    cdef nv14_level *_level
    cdef nv14_state *_prefix_state
    cdef size_t _prefix_frame
    cdef nv14_input *_cached_replay
    cdef size_t _cached_replay_count
    cdef bint _simulate_enemies
    cdef bint _searching
    cdef object _cancel_event
    cdef object _cancel_error

    def __cinit__(self):
        self._level = NULL
        self._prefix_state = NULL
        self._prefix_frame = 0
        self._cached_replay = NULL
        self._cached_replay_count = 0
        self._simulate_enemies = False
        self._searching = False
        self._cancel_event = None
        self._cancel_error = None

    def __init__(
        self,
        str level_string,
        *,
        bint simulate_enemies=False,
    ):
        cdef bytes encoded = level_string.encode("utf-8")
        cdef const char *level_bytes = <const char *>encoded
        cdef size_t level_length = <size_t>len(encoded)
        cdef nv14_level *level
        cdef nv14_error error
        if self._searching:
            raise RuntimeError(
                "a native search session cannot be reinitialised during a search"
            )
        memset(&error, 0, sizeof(nv14_error))
        with nogil:
            level = nv14_level_create(
                level_bytes,
                level_length,
                1 if simulate_enemies else 0,
                &error,
            )
        if level == NULL:
            _raise_create_error(&error, "parse native search level")
        nv14_state_destroy(self._prefix_state)
        nv14_level_release(self._level)
        PyMem_Free(self._cached_replay)
        self._level = level
        self._prefix_state = NULL
        self._prefix_frame = 0
        self._cached_replay = NULL
        self._cached_replay_count = 0
        self._simulate_enemies = simulate_enemies

    def __dealloc__(self):
        nv14_state_destroy(self._prefix_state)
        nv14_level_release(self._level)
        PyMem_Free(self._cached_replay)

    cdef int _guard_idle(self) except -1:
        if self._level == NULL:
            raise RuntimeError("uninitialised native search session")
        if self._searching:
            raise RuntimeError(
                "a native search session cannot run concurrent searches"
            )
        return 0

    cdef int _refresh_prefix(
        self,
        const nv14_input *replay,
        size_t replay_count,
        size_t prefix_frame,
    ) except -1:
        cdef size_t common_count
        cdef size_t first_difference = 0
        cdef size_t start_frame = 0
        cdef size_t step_count
        cdef size_t consumed = 0
        cdef bint cached_prefix_valid = False
        cdef nv14_input *new_replay = NULL
        cdef nv14_state *new_state = NULL
        cdef nv14_error error
        cdef nv14_step_result last_result
        cdef nv14_status status

        common_count = min(self._cached_replay_count, replay_count)
        while (
            first_difference < common_count
            and self._cached_replay[first_difference].left
                == replay[first_difference].left
            and self._cached_replay[first_difference].right
                == replay[first_difference].right
            and self._cached_replay[first_difference].jump
                == replay[first_difference].jump
            and self._cached_replay[first_difference].jump_trigger
                == replay[first_difference].jump_trigger
        ):
            first_difference += 1
        if (
            first_difference == common_count
            and self._cached_replay_count == replay_count
        ):
            first_difference = <size_t>-1
        if (
            self._prefix_state != NULL
            and prefix_frame >= self._prefix_frame
            and first_difference >= self._prefix_frame
        ):
            cached_prefix_valid = True

        if replay_count > 0:
            new_replay = <nv14_input *>_checked_alloc(
                replay_count,
                sizeof(nv14_input),
                "native replay cache",
            )
            memcpy(new_replay, replay, replay_count * sizeof(nv14_input))
        if cached_prefix_valid and prefix_frame == self._prefix_frame:
            PyMem_Free(self._cached_replay)
            self._cached_replay = new_replay
            self._cached_replay_count = replay_count
            return 0

        memset(&error, 0, sizeof(nv14_error))
        if cached_prefix_valid:
            new_state = nv14_state_clone(self._prefix_state, &error)
            start_frame = self._prefix_frame
        else:
            new_state = nv14_state_create(self._level, &error)
            start_frame = 0
        if new_state == NULL:
            PyMem_Free(new_replay)
            _raise_create_error(
                &error,
                (
                    "clone native prefix search state"
                    if cached_prefix_valid
                    else "create native prefix search state"
                ),
            )
        step_count = prefix_frame - start_frame
        memset(&last_result, 0, sizeof(nv14_step_result))
        status = nv14_state_step_many(
            new_state,
            replay + start_frame,
            step_count,
            0,
            0,
            &consumed,
            &last_result,
        )
        if (
            status != NV14_STATUS_OK
            or consumed != step_count
            or last_result.unsupported
        ):
            nv14_state_destroy(new_state)
            PyMem_Free(new_replay)
            if status == NV14_STATUS_OK:
                status = NV14_STATUS_UNSUPPORTED_OBJECTS
            _raise_status(status, "simulate native search prefix")

        nv14_state_destroy(self._prefix_state)
        PyMem_Free(self._cached_replay)
        self._prefix_state = new_state
        self._prefix_frame = prefix_frame
        self._cached_replay = new_replay
        self._cached_replay_count = replay_count
        return 0

    cdef void _start(self, object cancel_event) except *:
        self._searching = True
        self._cancel_event = cancel_event
        self._cancel_error = None

    cdef void _finish(self):
        self._searching = False
        self._cancel_event = None

    cdef object _take_cancel_error(self):
        cdef object error = self._cancel_error
        self._cancel_error = None
        return error

    def evaluate_replay(self, frames, *, trace_stride=1):
        cdef nv14_input *inputs = NULL
        cdef size_t input_count = 0
        cdef size_t native_stride
        cdef nv14_error error
        cdef nv14_replay_trace_status status
        cdef NativeTrace trace
        cdef nv14_replay_trace_result *trace_result
        self._guard_idle()
        _as_size(trace_stride, &native_stride, "trace_stride")
        if native_stride < 1:
            raise ValueError("trace_stride must be positive")
        _marshal_inputs(
            frames,
            &inputs,
            &input_count,
            "native replay trace",
            True,
        )
        trace = NativeTrace()
        trace_result = trace.pointer()
        memset(&error, 0, sizeof(nv14_error))
        self._start(None)
        try:
            with nogil:
                status = nv14_replay_trace_run(
                    self._level,
                    inputs,
                    input_count,
                    native_stride,
                    trace_result,
                    &error,
                )
            if status == NV14_REPLAY_TRACE_OK:
                return trace
            if status == NV14_REPLAY_TRACE_OUT_OF_MEMORY:
                raise MemoryError("native replay trace exhausted memory")
            if status == NV14_REPLAY_TRACE_INVALID_ARGUMENT:
                raise ValueError(
                    "evaluate native replay trace: "
                    + _native_error_text(&error, NV14_STATUS_INVALID_ARGUMENT)
                )
            if error.code != NV14_STATUS_OK:
                _raise_status(error.code, "evaluate native replay trace")
            raise RuntimeError("evaluate native replay trace: native core error")
        finally:
            self._finish()
            PyMem_Free(inputs)

    def search(self, frames, payload):
        cdef _SearchMarshal marshal
        cdef nv14_search_result result
        cdef nv14_error error
        cdef nv14_search_status status
        cdef object cancel_error
        self._guard_idle()
        marshal = _SearchMarshal()
        marshal.load(frames, payload)
        self._refresh_prefix(
            marshal.spec.replay,
            marshal.spec.replay_count,
            marshal.spec.mutable_frames[0],
        )
        marshal.spec.prefix_state = self._prefix_state
        marshal.spec.prefix_frame = self._prefix_frame
        marshal.spec.cancel = _cancel_search
        marshal.spec.cancel_userdata = <void *><PyObject *>self
        marshal.spec.cancel_poll_interval = 16384
        memset(&result, 0, sizeof(nv14_search_result))
        if not nv14_search_result_init(&result, sizeof(nv14_search_result)):
            raise RuntimeError("initialise native search result")
        memset(&error, 0, sizeof(nv14_error))
        self._start(None)
        try:
            with nogil:
                status = nv14_search_run(
                    self._level,
                    &marshal.spec,
                    &result,
                    &error,
                )
            cancel_error = self._take_cancel_error()
            if cancel_error is not None:
                raise cancel_error
            if status != NV14_SEARCH_OK:
                _raise_search_status(status, &error, "run native search")
            return _search_result_dict(&result, marshal)
        finally:
            self._finish()
            nv14_search_result_destroy(&result)

    def evaluate_patches(self, frames, payload, cancel_event=None):
        cdef _PatchMarshal marshal
        cdef nv14_patch_result result
        cdef nv14_error error
        cdef nv14_search_status status
        cdef object cancel_error
        cdef size_t patch_index
        cdef size_t first_assignment
        cdef size_t prefix_frame
        self._guard_idle()
        marshal = _PatchMarshal()
        marshal.load(frames, payload)
        if marshal.spec.patch_count != 0:
            first_assignment = marshal.spec.patches[0].first_assignment
            prefix_frame = marshal.spec.assignments[first_assignment].frame
            for patch_index in range(1, marshal.spec.patch_count):
                first_assignment = marshal.spec.patches[patch_index].first_assignment
                if marshal.spec.assignments[first_assignment].frame < prefix_frame:
                    prefix_frame = marshal.spec.assignments[first_assignment].frame
            if (
                marshal.spec.required_jump_count != 0
                and marshal.spec.required_jump_frames[0] < prefix_frame
            ):
                prefix_frame = marshal.spec.required_jump_frames[0]
            self._refresh_prefix(
                marshal.spec.replay,
                marshal.spec.replay_count,
                prefix_frame,
            )
            marshal.spec.prefix_state = self._prefix_state
            marshal.spec.prefix_frame = self._prefix_frame
        marshal.spec.cancel = _cancel_search
        marshal.spec.cancel_userdata = <void *><PyObject *>self
        marshal.spec.cancel_poll_interval = 16384
        memset(&result, 0, sizeof(nv14_patch_result))
        if not nv14_patch_result_init(&result, sizeof(nv14_patch_result)):
            raise RuntimeError("initialise native patch result")
        memset(&error, 0, sizeof(nv14_error))
        self._start(cancel_event)
        try:
            with nogil:
                status = nv14_patch_run(
                    self._level,
                    &marshal.spec,
                    &result,
                    &error,
                )
            cancel_error = self._take_cancel_error()
            if cancel_error is not None:
                raise cancel_error
            if status != NV14_SEARCH_OK:
                _raise_search_status(
                    status,
                    &error,
                    "run native patch evaluation",
                )
            return _patch_result_dict(&result)
        finally:
            self._finish()
            nv14_patch_result_destroy(&result)

    def search_patterns(self, frames, payload, cancel_event=None):
        cdef _PatternMarshal marshal
        cdef nv14_pattern_search_result result
        cdef nv14_error error
        cdef nv14_search_status status
        cdef object cancel_error
        self._guard_idle()
        marshal = _PatternMarshal()
        marshal.load(frames, payload)
        self._refresh_prefix(
            marshal.spec.replay,
            marshal.spec.replay_count,
            marshal.spec.range_start,
        )
        marshal.spec.prefix_state = self._prefix_state
        marshal.spec.prefix_frame = self._prefix_frame
        marshal.spec.cancel = _cancel_search
        marshal.spec.cancel_userdata = <void *><PyObject *>self
        marshal.spec.cancel_poll_interval = 16384
        memset(&result, 0, sizeof(nv14_pattern_search_result))
        if not nv14_pattern_search_result_init(
            &result,
            sizeof(nv14_pattern_search_result),
        ):
            raise RuntimeError("initialise native pattern-search result")
        memset(&error, 0, sizeof(nv14_error))
        self._start(cancel_event)
        try:
            with nogil:
                status = nv14_pattern_search_run(
                    self._level,
                    &marshal.spec,
                    &result,
                    &error,
                )
            cancel_error = self._take_cancel_error()
            if cancel_error is not None:
                raise cancel_error
            if status != NV14_SEARCH_OK:
                _raise_search_status(
                    status,
                    &error,
                    "run native pattern search",
                )
            return _pattern_result_dict(&result)
        finally:
            self._finish()
            nv14_pattern_search_result_destroy(&result)


cdef int _cancel_search_with_gil(PyObject *userdata) noexcept:
    cdef SearchSession session
    cdef object error
    session = <SearchSession><object>userdata
    try:
        PyErr_CheckSignals()
        if (
            session._cancel_event is not None
            and bool(session._cancel_event.is_set())
        ):
            return 1
    except BaseException as error:
        session._cancel_error = error
        return 1
    return 0


cdef int _cancel_search(void *userdata) noexcept nogil:
    with gil:
        return _cancel_search_with_gil(<PyObject *>userdata)


def search_backend_info():
    """Return ABI metadata for search APIs in this unified extension."""
    return {
        "available": True,
        "wrapper_api": 6,
        "search_abi": NV14_SEARCH_ABI_VERSION,
        "patch_abi": NV14_PATCH_ABI_VERSION,
        "trace_abi": NV14_REPLAY_TRACE_ABI_VERSION,
        "analysis_abi": NV14_REPLAY_ANALYSIS_ABI_VERSION,
        "core_abi": NV14_CORE_ABI_VERSION,
        "implementation": "cython-unified-native",
        "strict_fp": bool(nv14_wrapper_strict_fp()),
    }

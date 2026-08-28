/*
 * Source-order native ports of BounceBlockObject, ThwompObject, and
 * TestDoorObject from n v1.4.
 *
 * Mutable payloads live entirely in the core-owned nv14_object_runtime array,
 * so state clones remain a bounded set of memcpy operations.  Do not compile
 * this unit with fast-math or floating-point contraction: the deliberately
 * split temporaries below mirror nv14_engine.py and the AVM1 operation order.
 */

#include "nv14_objects_basic.h"

#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#define NV14_BOUNCE_XW (NV14_TILE_SCALE * 0.8)
#define NV14_BOUNCE_YW (NV14_TILE_SCALE * 0.8)
#define NV14_BOUNCE_STIFF 0.05
#define NV14_BOUNCE_MASS 0.2
#define NV14_BOUNCE_SLEEP_THRESHOLD 40

#define NV14_THWOMP_XW (NV14_TILE_SCALE * 0.75)
#define NV14_THWOMP_YW (NV14_TILE_SCALE * 0.75)
#define NV14_THWOMP_FALL_SPEED (NV14_TILE_SCALE * 0.3571428571428572)
#define NV14_THWOMP_RAISE_SPEED (NV14_TILE_SCALE * 0.1428571428571429)

#define NV14_DOOR_SWITCH_R (NV14_TILE_SCALE * 0.4166666666666667)
#define NV14_DOOR_PROXIMITY_R (NV14_TILE_SCALE * 0.8333333333333334)
#define NV14_DOOR_MAX_TIMER 5

enum nv14_bounce_f64_slot {
    NV14_BOUNCE_POS_X = 0,
    NV14_BOUNCE_POS_Y = 1,
    NV14_BOUNCE_OLD_X = 2,
    NV14_BOUNCE_OLD_Y = 3
};

enum nv14_bounce_i64_slot {
    NV14_BOUNCE_ASLEEP = 0,
    NV14_BOUNCE_SLEEP_TIMER = 1
};

enum nv14_thwomp_f64_slot {
    NV14_THWOMP_POS_X = 0,
    NV14_THWOMP_POS_Y = 1,
    NV14_THWOMP_GOAL_X = 2,
    NV14_THWOMP_GOAL_Y = 3,
    NV14_THWOMP_FALLGOAL_X = 4,
    NV14_THWOMP_FALLGOAL_Y = 5,
    NV14_THWOMP_DIR_X = 6,
    NV14_THWOMP_DIR_Y = 7,
    NV14_THWOMP_SPEED = 8
};

enum nv14_thwomp_i64_slot {
    NV14_THWOMP_MOVE_DIR = 0,
    NV14_THWOMP_IS_MOVING = 1,
    NV14_THWOMP_MODE = 2,
    NV14_THWOMP_MIN_I = 3,
    NV14_THWOMP_MIN_J = 4,
    NV14_THWOMP_MAX_I = 5,
    NV14_THWOMP_MAX_J = 6
};

enum nv14_door_i64_slot {
    NV14_DOOR_VERT = 0,
    NV14_DOOR_IS_TRAP = 1,
    NV14_DOOR_IS_LOCKED = 2,
    NV14_DOOR_FRONT_I = 3,
    NV14_DOOR_FRONT_J = 4,
    NV14_DOOR_FRONT_SIDE = 5,
    NV14_DOOR_BACK_I = 6,
    NV14_DOOR_BACK_J = 7,
    NV14_DOOR_BACK_SIDE = 8,
    NV14_DOOR_OPEN_FRONT = 9,
    NV14_DOOR_OPEN_BACK = 10,
    NV14_DOOR_IS_OPEN = 11,
    NV14_DOOR_TIMER = 12,
    NV14_DOOR_UPDATING = 13,
    NV14_DOOR_TRIGGER_ACTIVE = 14
};

nv14_status nv14_objects_basic_door_interactions_at(
    const nv14_state *state,
    size_t object_index,
    int *locked_open_out,
    int *trap_triggered_out
)
{
    const nv14_native_object *object;
    const nv14_object_runtime *runtime;
    if (state == NULL || locked_open_out == NULL ||
        trap_triggered_out == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    *locked_open_out = 0;
    *trap_triggered_out = 0;
    if (object_index >= state->level->native_object_count)
        return NV14_STATUS_OUT_OF_BOUNDS;
    object = &state->level->native_objects[object_index];
    if (object->kind != NV14_NATIVE_TESTDOOR)
        return NV14_STATUS_OUT_OF_BOUNDS;
    runtime = nv14_internal_object_runtime_const(state, object_index);
    if (runtime == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    *locked_open_out =
        runtime->i64[NV14_DOOR_IS_LOCKED] != 0 &&
        runtime->i64[NV14_DOOR_IS_OPEN] != 0;
    *trap_triggered_out =
        runtime->i64[NV14_DOOR_IS_TRAP] != 0 &&
        runtime->i64[NV14_DOOR_TRIGGER_ACTIVE] == 0;
    return NV14_STATUS_OK;
}

nv14_status nv14_objects_basic_door_interactions(
    const nv14_state *state,
    uint32_t load_index,
    int *locked_open_out,
    int *trap_triggered_out
)
{
    size_t low = 0;
    size_t high;
    if (state == NULL || locked_open_out == NULL ||
        trap_triggered_out == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    *locked_open_out = 0;
    *trap_triggered_out = 0;
    /* Native objects are appended in serialized load order.  Kernels query
       persistent door state frequently, so resolve the sparse load id with a
       binary search instead of rescanning every object for every atom/tick. */
    high = state->level->native_object_count;
    while (low < high) {
        size_t middle = low + (high - low) / 2u;
        if (state->level->native_objects[middle].load_index < load_index)
            low = middle + 1u;
        else
            high = middle;
    }
    if (low >= state->level->native_object_count ||
        state->level->native_objects[low].load_index != load_index)
        return NV14_STATUS_OUT_OF_BOUNDS;
    return nv14_objects_basic_door_interactions_at(
        state, low, locked_open_out, trap_triggered_out
    );
}

static nv14_status nv14_basic_invalid_level(
    nv14_error *error_out,
    int object_type,
    const char *message
)
{
    if (error_out != NULL) {
        memset(error_out, 0, sizeof(*error_out));
        error_out->code = NV14_STATUS_INVALID_LEVEL;
        error_out->object_type = object_type;
        error_out->tile_id = -1;
        error_out->tile_i = -1;
        error_out->tile_j = -1;
        if (message != NULL) {
            (void)snprintf(
                error_out->message,
                sizeof(error_out->message),
                "%s",
                message
            );
        }
    }
    return NV14_STATUS_INVALID_LEVEL;
}

static const nv14_tile *nv14_basic_tile_at(
    const nv14_level *level,
    int i,
    int j
)
{
    if (level == NULL || i < 0 || i >= NV14_TILE_COLS ||
        j < 0 || j >= NV14_TILE_ROWS) {
        return NULL;
    }
    return &level->tiles[(size_t)i * NV14_TILE_ROWS + (size_t)j];
}

static size_t nv14_basic_edge_index(int i, int j, int side)
{
    return ((size_t)i * NV14_TILE_ROWS + (size_t)j) * 4u + (size_t)side;
}

static int nv14_basic_level_edge(
    const nv14_level *level,
    int i,
    int j,
    int side
)
{
    size_t index = nv14_basic_edge_index(i, j, side);
    int override = level->initial_edge_overrides[index];
    if (override >= 0) return override;
    return level->tiles[(size_t)i * NV14_TILE_ROWS + (size_t)j].edges[side];
}

static void nv14_basic_level_set_edge(
    nv14_level *level,
    int i,
    int j,
    int side,
    int value
)
{
    level->initial_edge_overrides[nv14_basic_edge_index(i, j, side)] =
        (int8_t)value;
}

static void nv14_basic_state_set_edge(
    nv14_state *state,
    int i,
    int j,
    int side,
    int value
)
{
    /* Route state mutations through the core so its derived sparse-key index
       remains synchronized with the authoritative override array. */
    (void)nv14_state_set_edge_override(state, i, j, side, value);
}

static int nv14_basic_trunc_int(double value, int *result_out)
{
    if (!isfinite(value) || value < (double)INT_MIN || value > (double)INT_MAX)
        return 0;
    *result_out = (int)value;
    return 1;
}

static nv14_status nv14_basic_append(
    nv14_level *level,
    nv14_native_kind kind,
    const nv14_object_descriptor *descriptor,
    double x,
    double y,
    double r,
    const nv14_object_runtime *runtime,
    size_t *object_index_out
)
{
    nv14_status status = nv14_internal_level_append_object(
        level,
        kind,
        1,
        descriptor->load_index,
        descriptor->load_index,
        x,
        y,
        0.0,
        0.0,
        r,
        runtime,
        object_index_out
    );
    /* An unusual out-of-grid object remains valid to the Python parser but
       cannot participate in the bounded native collision grid. */
    if (status == NV14_STATUS_OUT_OF_BOUNDS)
        return NV14_STATUS_UNSUPPORTED_OBJECTS;
    return status;
}

static nv14_status nv14_basic_init_bounce(
    nv14_level *level,
    const nv14_object_descriptor *descriptor
)
{
    nv14_object_runtime runtime;
    memset(&runtime, 0, sizeof(runtime));
    runtime.f64[NV14_BOUNCE_POS_X] = descriptor->parameters[0];
    runtime.f64[NV14_BOUNCE_POS_Y] = descriptor->parameters[1];
    runtime.f64[NV14_BOUNCE_OLD_X] = descriptor->parameters[0];
    runtime.f64[NV14_BOUNCE_OLD_Y] = descriptor->parameters[1];
    runtime.i64[NV14_BOUNCE_ASLEEP] = 1;
    return nv14_basic_append(
        level,
        NV14_NATIVE_BOUNCE,
        descriptor,
        descriptor->parameters[0],
        descriptor->parameters[1],
        0.0,
        &runtime,
        NULL
    );
}

static nv14_status nv14_basic_init_thwomp(
    nv14_level *level,
    const nv14_object_descriptor *descriptor,
    nv14_error *error_out
)
{
    const double x = descriptor->parameters[0];
    const double y = descriptor->parameters[1];
    int direction_enum;
    int cell_i;
    int cell_j;
    int goal_i;
    int goal_j;
    int probe_i;
    int probe_j;
    int mini;
    int minj;
    int maxi;
    int maxj;
    double direction_x = 0.0;
    double direction_y = 0.0;
    double goal_x = x;
    double goal_y = y;
    const nv14_tile *cell;
    const nv14_tile *probe;
    nv14_object_runtime runtime;
    nv14_status status;
    size_t object_index;

    if (!nv14_basic_trunc_int(descriptor->parameters[2], &direction_enum) ||
        direction_enum < 0 || direction_enum > 3) {
        return nv14_basic_invalid_level(
            error_out,
            NV14_OBJ_THWOMP,
            "thwomp direction is outside 0..3"
        );
    }
    if (!nv14_internal_floor_index(x, NV14_TILE_W, &cell_i) ||
        !nv14_internal_floor_index(y, NV14_TILE_H, &cell_j)) {
        return NV14_STATUS_UNSUPPORTED_OBJECTS;
    }
    cell = nv14_basic_tile_at(level, cell_i, cell_j);
    if (cell == NULL) return NV14_STATUS_UNSUPPORTED_OBJECTS;

    probe_i = cell_i;
    probe_j = cell_j;
    if (direction_enum == 0) {
        direction_x = 1.0;
        ++probe_i;
    } else if (direction_enum == 1) {
        direction_y = 1.0;
        ++probe_j;
    } else if (direction_enum == 2) {
        direction_x = -1.0;
        --probe_i;
    } else {
        direction_y = -1.0;
        --probe_j;
    }
    probe = nv14_basic_tile_at(level, probe_i, probe_j);
    while (probe != NULL && probe->tile_id == NV14_TID_EMPTY) {
        if (direction_enum == 0) {
            goal_x += 2.0 * NV14_TILE_SCALE;
            ++probe_i;
        } else if (direction_enum == 1) {
            goal_y += 2.0 * NV14_TILE_SCALE;
            ++probe_j;
        } else if (direction_enum == 2) {
            goal_x -= 2.0 * NV14_TILE_SCALE;
            --probe_i;
        } else {
            goal_y -= 2.0 * NV14_TILE_SCALE;
            --probe_j;
        }
        probe = nv14_basic_tile_at(level, probe_i, probe_j);
    }
    if (probe == NULL) return NV14_STATUS_UNSUPPORTED_OBJECTS;

    if (direction_enum == 0) {
        goal_x += NV14_THWOMP_XW;
        goal_x -= x - cell->x;
    } else if (direction_enum == 1) {
        goal_y += NV14_THWOMP_YW;
        goal_y -= y - cell->y;
    } else if (direction_enum == 2) {
        goal_x -= NV14_THWOMP_XW;
        goal_x -= x - cell->x;
    } else {
        goal_y -= NV14_THWOMP_YW;
        goal_y -= y - cell->y;
    }

    if (!nv14_internal_floor_index(goal_x, NV14_TILE_W, &goal_i) ||
        !nv14_internal_floor_index(goal_y, NV14_TILE_H, &goal_j) ||
        nv14_basic_tile_at(level, goal_i, goal_j) == NULL) {
        return NV14_STATUS_UNSUPPORTED_OBJECTS;
    }
    mini = cell_i;
    minj = cell_j;
    maxi = goal_i;
    maxj = goal_j;
    if (direction_x < 0.0) {
        int temporary = mini;
        mini = maxi;
        maxi = temporary;
    }
    if (direction_y < 0.0) {
        int temporary = minj;
        minj = maxj;
        maxj = temporary;
    }

    memset(&runtime, 0, sizeof(runtime));
    runtime.f64[NV14_THWOMP_POS_X] = x;
    runtime.f64[NV14_THWOMP_POS_Y] = y;
    runtime.f64[NV14_THWOMP_GOAL_X] = goal_x;
    runtime.f64[NV14_THWOMP_GOAL_Y] = goal_y;
    runtime.f64[NV14_THWOMP_FALLGOAL_X] = goal_x;
    runtime.f64[NV14_THWOMP_FALLGOAL_Y] = goal_y;
    runtime.f64[NV14_THWOMP_DIR_X] = direction_x;
    runtime.f64[NV14_THWOMP_DIR_Y] = direction_y;
    runtime.f64[NV14_THWOMP_SPEED] = NV14_THWOMP_FALL_SPEED;
    runtime.i64[NV14_THWOMP_MOVE_DIR] = 1;
    runtime.i64[NV14_THWOMP_MIN_I] = mini;
    runtime.i64[NV14_THWOMP_MIN_J] = minj;
    runtime.i64[NV14_THWOMP_MAX_I] = maxi;
    runtime.i64[NV14_THWOMP_MAX_J] = maxj;

    status = nv14_basic_append(
        level,
        NV14_NATIVE_THWOMP,
        descriptor,
        x,
        y,
        0.0,
        &runtime,
        &object_index
    );
    if (status != NV14_STATUS_OK) return status;
    return nv14_internal_level_start_update(level, object_index);
}

static void nv14_basic_write_initial_door_edges(
    nv14_level *level,
    const nv14_object_runtime *runtime
)
{
    int front_value = runtime->i64[NV14_DOOR_IS_OPEN]
        ? (int)runtime->i64[NV14_DOOR_OPEN_FRONT]
        : NV14_EID_SOLID;
    int back_value = runtime->i64[NV14_DOOR_IS_OPEN]
        ? (int)runtime->i64[NV14_DOOR_OPEN_BACK]
        : NV14_EID_SOLID;
    nv14_basic_level_set_edge(
        level,
        (int)runtime->i64[NV14_DOOR_FRONT_I],
        (int)runtime->i64[NV14_DOOR_FRONT_J],
        (int)runtime->i64[NV14_DOOR_FRONT_SIDE],
        front_value
    );
    nv14_basic_level_set_edge(
        level,
        (int)runtime->i64[NV14_DOOR_BACK_I],
        (int)runtime->i64[NV14_DOOR_BACK_J],
        (int)runtime->i64[NV14_DOOR_BACK_SIDE],
        back_value
    );
}

static nv14_status nv14_basic_init_door(
    nv14_level *level,
    const nv14_object_descriptor *descriptor,
    nv14_error *error_out
)
{
    int vert;
    int base_i;
    int base_j;
    int delta_i;
    int delta_j;
    int64_t door_i_wide;
    int64_t door_j_wide;
    int door_i;
    int door_j;
    int front_i;
    int front_j;
    int front_side;
    int back_i;
    int back_j;
    int back_side;
    int is_trap = descriptor->parameters[3] != 0.0;
    int is_locked = descriptor->parameters[6] != 0.0;
    int is_open;
    double trigger_x;
    double trigger_y;
    double trigger_r;
    const nv14_tile *door_cell;
    nv14_object_runtime runtime;
    nv14_status status;

    if (!nv14_basic_trunc_int(descriptor->parameters[2], &vert) ||
        !nv14_basic_trunc_int(descriptor->parameters[4], &base_i) ||
        !nv14_basic_trunc_int(descriptor->parameters[5], &base_j) ||
        !nv14_basic_trunc_int(descriptor->parameters[7], &delta_i) ||
        !nv14_basic_trunc_int(descriptor->parameters[8], &delta_j)) {
        return nv14_basic_invalid_level(
            error_out,
            NV14_OBJ_TESTDOOR,
            "test door contains an invalid integer parameter"
        );
    }
    door_i_wide = (int64_t)base_i + (int64_t)delta_i;
    door_j_wide = (int64_t)base_j + (int64_t)delta_j;
    if (door_i_wide < INT_MIN || door_i_wide > INT_MAX ||
        door_j_wide < INT_MIN || door_j_wide > INT_MAX) {
        return NV14_STATUS_UNSUPPORTED_OBJECTS;
    }
    door_i = (int)door_i_wide;
    door_j = (int)door_j_wide;
    door_cell = nv14_basic_tile_at(level, door_i, door_j);
    if (door_cell == NULL) return NV14_STATUS_UNSUPPORTED_OBJECTS;

    if (vert == 1) {
        trigger_x = door_cell->x;
        trigger_y = door_cell->y + NV14_TILE_SCALE;
        front_i = door_i;
        front_j = door_j;
        front_side = NV14_EDGE_D;
        back_i = door_i;
        back_j = door_j + 1;
        back_side = NV14_EDGE_U;
    } else {
        trigger_x = door_cell->x + NV14_TILE_SCALE;
        trigger_y = door_cell->y;
        front_i = door_i;
        front_j = door_j;
        front_side = NV14_EDGE_R;
        back_i = door_i + 1;
        back_j = door_j;
        back_side = NV14_EDGE_L;
    }
    if (nv14_basic_tile_at(level, front_i, front_j) == NULL ||
        nv14_basic_tile_at(level, back_i, back_j) == NULL) {
        return NV14_STATUS_UNSUPPORTED_OBJECTS;
    }

    if (is_locked) {
        is_trap = 0;
        is_open = 0;
        trigger_x = descriptor->parameters[0];
        trigger_y = descriptor->parameters[1];
        trigger_r = NV14_DOOR_SWITCH_R;
    } else if (is_trap) {
        is_open = 1;
        trigger_x = descriptor->parameters[0];
        trigger_y = descriptor->parameters[1];
        trigger_r = NV14_DOOR_SWITCH_R;
    } else {
        is_open = 0;
        trigger_r = NV14_DOOR_PROXIMITY_R;
    }

    memset(&runtime, 0, sizeof(runtime));
    runtime.i64[NV14_DOOR_VERT] = vert;
    runtime.i64[NV14_DOOR_IS_TRAP] = is_trap;
    runtime.i64[NV14_DOOR_IS_LOCKED] = is_locked;
    runtime.i64[NV14_DOOR_FRONT_I] = front_i;
    runtime.i64[NV14_DOOR_FRONT_J] = front_j;
    runtime.i64[NV14_DOOR_FRONT_SIDE] = front_side;
    runtime.i64[NV14_DOOR_BACK_I] = back_i;
    runtime.i64[NV14_DOOR_BACK_J] = back_j;
    runtime.i64[NV14_DOOR_BACK_SIDE] = back_side;
    runtime.i64[NV14_DOOR_OPEN_FRONT] = nv14_basic_level_edge(
        level, front_i, front_j, front_side
    );
    runtime.i64[NV14_DOOR_OPEN_BACK] = nv14_basic_level_edge(
        level, back_i, back_j, back_side
    );
    runtime.i64[NV14_DOOR_IS_OPEN] = is_open;
    runtime.i64[NV14_DOOR_TRIGGER_ACTIVE] = 1;

    status = nv14_basic_append(
        level,
        NV14_NATIVE_TESTDOOR,
        descriptor,
        trigger_x,
        trigger_y,
        trigger_r,
        &runtime,
        NULL
    );
    if (status != NV14_STATUS_OK) return status;
    /* Init calls UpdateEdges immediately.  This mutation must precede the
       next serialized door so shared-edge open states are captured exactly. */
    nv14_basic_write_initial_door_edges(level, &runtime);
    return NV14_STATUS_OK;
}

static nv14_status nv14_basic_descriptor_init(
    nv14_level *level,
    const nv14_object_descriptor *descriptor,
    nv14_error *error_out
)
{
    if (level == NULL || descriptor == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    if (descriptor->object_type == NV14_OBJ_BOUNCE)
        return nv14_basic_init_bounce(level, descriptor);
    if (descriptor->object_type == NV14_OBJ_THWOMP)
        return nv14_basic_init_thwomp(level, descriptor, error_out);
    if (descriptor->object_type == NV14_OBJ_TESTDOOR)
        return nv14_basic_init_door(level, descriptor, error_out);
    return NV14_STATUS_UNSUPPORTED_OBJECTS;
}

static void nv14_basic_door_write_edges(
    nv14_state *state,
    const nv14_object_runtime *runtime
)
{
    int front_value = runtime->i64[NV14_DOOR_IS_OPEN]
        ? (int)runtime->i64[NV14_DOOR_OPEN_FRONT]
        : NV14_EID_SOLID;
    int back_value = runtime->i64[NV14_DOOR_IS_OPEN]
        ? (int)runtime->i64[NV14_DOOR_OPEN_BACK]
        : NV14_EID_SOLID;
    nv14_basic_state_set_edge(
        state,
        (int)runtime->i64[NV14_DOOR_FRONT_I],
        (int)runtime->i64[NV14_DOOR_FRONT_J],
        (int)runtime->i64[NV14_DOOR_FRONT_SIDE],
        front_value
    );
    nv14_basic_state_set_edge(
        state,
        (int)runtime->i64[NV14_DOOR_BACK_I],
        (int)runtime->i64[NV14_DOOR_BACK_J],
        (int)runtime->i64[NV14_DOOR_BACK_SIDE],
        back_value
    );
}

static nv14_status nv14_basic_door_open(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    runtime->i64[NV14_DOOR_IS_OPEN] = 1;
    nv14_basic_door_write_edges(state, runtime);
    if (!runtime->i64[NV14_DOOR_IS_TRAP] &&
        !runtime->i64[NV14_DOOR_IS_LOCKED]) {
        nv14_status status = nv14_internal_start_update(state, object_index);
        if (status != NV14_STATUS_OK) return status;
        runtime->i64[NV14_DOOR_UPDATING] = 1;
    }
    return NV14_STATUS_OK;
}

static void nv14_basic_door_close(nv14_state *state, size_t object_index)
{
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    nv14_internal_end_update(state, object_index);
    runtime->i64[NV14_DOOR_UPDATING] = 0;
    runtime->i64[NV14_DOOR_IS_OPEN] = 0;
    nv14_basic_door_write_edges(state, runtime);
}

static nv14_status nv14_basic_update_bounce(
    nv14_state *state,
    size_t object_index
)
{
    const nv14_native_object *object = &state->level->native_objects[object_index];
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    double old_x_before;
    double old_y_before;
    double current_x;
    double current_y;
    double dx;
    double dy;
    if (runtime->i64[NV14_BOUNCE_ASLEEP]) return NV14_STATUS_OK;

    old_x_before = runtime->f64[NV14_BOUNCE_OLD_X];
    old_y_before = runtime->f64[NV14_BOUNCE_OLD_Y];
    runtime->f64[NV14_BOUNCE_OLD_X] = runtime->f64[NV14_BOUNCE_POS_X];
    current_x = runtime->f64[NV14_BOUNCE_OLD_X];
    runtime->f64[NV14_BOUNCE_OLD_Y] = runtime->f64[NV14_BOUNCE_POS_Y];
    current_y = runtime->f64[NV14_BOUNCE_OLD_Y];
    runtime->f64[NV14_BOUNCE_POS_X] += 0.99 * (current_x - old_x_before);
    runtime->f64[NV14_BOUNCE_POS_Y] += 0.99 * (current_y - old_y_before);
    dx = object->x - runtime->f64[NV14_BOUNCE_POS_X];
    dy = object->y - runtime->f64[NV14_BOUNCE_POS_Y];
    if (0.0 < dx * dx + dy * dy) {
        runtime->f64[NV14_BOUNCE_POS_X] += dx * NV14_BOUNCE_STIFF;
        runtime->f64[NV14_BOUNCE_POS_Y] += dy * NV14_BOUNCE_STIFF;
    }
    ++runtime->i64[NV14_BOUNCE_SLEEP_TIMER];
    return NV14_STATUS_OK;
}

static void nv14_basic_thwomp_start_fall(nv14_object_runtime *runtime)
{
    runtime->i64[NV14_THWOMP_IS_MOVING] = 1;
    runtime->f64[NV14_THWOMP_SPEED] = NV14_THWOMP_FALL_SPEED;
    runtime->i64[NV14_THWOMP_MOVE_DIR] = 1;
    runtime->f64[NV14_THWOMP_GOAL_X] =
        runtime->f64[NV14_THWOMP_FALLGOAL_X];
    runtime->f64[NV14_THWOMP_GOAL_Y] =
        runtime->f64[NV14_THWOMP_FALLGOAL_Y];
    runtime->i64[NV14_THWOMP_MODE] = 1;
}

static void nv14_basic_thwomp_start_raise(
    nv14_object_runtime *runtime,
    const nv14_native_object *object
)
{
    runtime->i64[NV14_THWOMP_IS_MOVING] = 1;
    runtime->f64[NV14_THWOMP_SPEED] = NV14_THWOMP_RAISE_SPEED;
    runtime->i64[NV14_THWOMP_MOVE_DIR] = -1;
    runtime->f64[NV14_THWOMP_GOAL_X] = object->x;
    runtime->f64[NV14_THWOMP_GOAL_Y] = object->y;
    runtime->i64[NV14_THWOMP_MODE] = 1;
}

static void nv14_basic_thwomp_start_wait(nv14_object_runtime *runtime)
{
    runtime->i64[NV14_THWOMP_IS_MOVING] = 0;
    runtime->i64[NV14_THWOMP_MODE] = 0;
}

static nv14_status nv14_basic_update_thwomp(
    nv14_state *state,
    size_t object_index
)
{
    const nv14_native_object *object = &state->level->native_objects[object_index];
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    int was_moving = runtime->i64[NV14_THWOMP_MODE] == 1;
    if (runtime->i64[NV14_THWOMP_MODE] == 0) {
        if (runtime->f64[NV14_THWOMP_DIR_X] == 0.0) {
            if (fabs(
                    runtime->f64[NV14_THWOMP_POS_X] - state->player.pos.x
                ) < 2.0 * (NV14_THWOMP_XW + state->player.xw) &&
                runtime->i64[NV14_THWOMP_MIN_J] <= state->player.cell_j &&
                state->player.cell_j <= runtime->i64[NV14_THWOMP_MAX_J]) {
                nv14_basic_thwomp_start_fall(runtime);
            }
        } else {
            if (fabs(
                    runtime->f64[NV14_THWOMP_POS_Y] - state->player.pos.y
                ) < 2.0 * (NV14_THWOMP_YW + state->player.yw) &&
                runtime->i64[NV14_THWOMP_MIN_I] <= state->player.cell_i &&
                state->player.cell_i <= runtime->i64[NV14_THWOMP_MAX_I]) {
                nv14_basic_thwomp_start_fall(runtime);
            }
        }
    } else {
        double dx = runtime->f64[NV14_THWOMP_GOAL_X] -
            runtime->f64[NV14_THWOMP_POS_X];
        double dy = runtime->f64[NV14_THWOMP_GOAL_Y] -
            runtime->f64[NV14_THWOMP_POS_Y];
        double distance2 = dx * dx + dy * dy;
        double speed = runtime->f64[NV14_THWOMP_SPEED];
        if (distance2 < speed * speed) {
            runtime->f64[NV14_THWOMP_POS_X] =
                runtime->f64[NV14_THWOMP_GOAL_X];
            runtime->f64[NV14_THWOMP_POS_Y] =
                runtime->f64[NV14_THWOMP_GOAL_Y];
            if (runtime->i64[NV14_THWOMP_MOVE_DIR] == 1)
                nv14_basic_thwomp_start_raise(runtime, object);
            else
                nv14_basic_thwomp_start_wait(runtime);
        } else {
            runtime->f64[NV14_THWOMP_POS_X] +=
                (double)runtime->i64[NV14_THWOMP_MOVE_DIR] *
                runtime->f64[NV14_THWOMP_DIR_X] * speed;
            runtime->f64[NV14_THWOMP_POS_Y] +=
                (double)runtime->i64[NV14_THWOMP_MOVE_DIR] *
                runtime->f64[NV14_THWOMP_DIR_Y] * speed;
        }
    }
    if (was_moving) {
        int cell_i;
        int cell_j;
        if (!nv14_internal_floor_index(
                runtime->f64[NV14_THWOMP_POS_X], NV14_TILE_W, &cell_i
            ) ||
            !nv14_internal_floor_index(
                runtime->f64[NV14_THWOMP_POS_Y], NV14_TILE_H, &cell_j
            )) {
            return NV14_STATUS_OUT_OF_BOUNDS;
        }
        return nv14_internal_grid_move(state, object_index, cell_i, cell_j);
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_basic_update_door(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    if (!runtime->i64[NV14_DOOR_UPDATING]) return NV14_STATUS_OK;
    ++runtime->i64[NV14_DOOR_TIMER];
    if (NV14_DOOR_MAX_TIMER < runtime->i64[NV14_DOOR_TIMER])
        nv14_basic_door_close(state, object_index);
    return NV14_STATUS_OK;
}

static nv14_status nv14_basic_update_object(
    nv14_state *state,
    size_t object_index
)
{
    const nv14_native_object *object;
    if (state == NULL || object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    object = &state->level->native_objects[object_index];
    if (object->kind == NV14_NATIVE_BOUNCE)
        return nv14_basic_update_bounce(state, object_index);
    if (object->kind == NV14_NATIVE_THWOMP)
        return nv14_basic_update_thwomp(state, object_index);
    if (object->kind == NV14_NATIVE_TESTDOOR)
        return nv14_basic_update_door(state, object_index);
    return NV14_STATUS_UNSUPPORTED_OBJECTS;
}

static nv14_status nv14_basic_think_object(
    nv14_state *state,
    size_t object_index
)
{
    const nv14_native_object *object;
    nv14_object_runtime *runtime;
    if (state == NULL || object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    object = &state->level->native_objects[object_index];
    if (object->kind != NV14_NATIVE_BOUNCE)
        return NV14_STATUS_UNSUPPORTED_OBJECTS;
    runtime = nv14_internal_object_runtime(state, object_index);
    if (NV14_BOUNCE_SLEEP_THRESHOLD <
        runtime->i64[NV14_BOUNCE_SLEEP_TIMER]) {
        nv14_internal_end_update(state, object_index);
        nv14_internal_end_think(state, object_index);
        runtime->i64[NV14_BOUNCE_ASLEEP] = 1;
        runtime->f64[NV14_BOUNCE_OLD_X] =
            runtime->f64[NV14_BOUNCE_POS_X];
        runtime->f64[NV14_BOUNCE_OLD_Y] =
            runtime->f64[NV14_BOUNCE_POS_Y];
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_basic_collide_bounce(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    nv14_player_snapshot *player = &state->player;
    double dy = player->pos.y - runtime->f64[NV14_BOUNCE_POS_Y];
    double pen_y = NV14_BOUNCE_YW + player->yw - fabs(dy);
    if (0.0 < pen_y) {
        double dx = player->pos.x - runtime->f64[NV14_BOUNCE_POS_X];
        double pen_x = NV14_BOUNCE_XW + player->xw - fabs(dx);
        if (0.0 < pen_x) {
            if (pen_y < pen_x) {
                double normal_y = 1.0;
                if (dy < 0.0) {
                    normal_y = -1.0;
                    pen_y *= -1.0;
                }
                runtime->f64[NV14_BOUNCE_POS_Y] -=
                    (1.0 - NV14_BOUNCE_MASS) * pen_y;
                nv14_internal_player_report_object(
                    player,
                    0.0,
                    NV14_BOUNCE_MASS * pen_y,
                    0.0,
                    normal_y
                );
            } else {
                double normal_x = 1.0;
                if (dx < 0.0) {
                    pen_x *= -1.0;
                    normal_x = -1.0;
                }
                runtime->f64[NV14_BOUNCE_POS_X] -=
                    (1.0 - NV14_BOUNCE_MASS) * pen_x;
                nv14_internal_player_report_object(
                    player,
                    NV14_BOUNCE_MASS * pen_x,
                    0.0,
                    normal_x,
                    0.0
                );
            }
            runtime->i64[NV14_BOUNCE_SLEEP_TIMER] = 0;
            if (runtime->i64[NV14_BOUNCE_ASLEEP]) {
                nv14_status status = nv14_internal_start_update(
                    state, object_index
                );
                if (status != NV14_STATUS_OK) return status;
                status = nv14_internal_start_think(state, object_index);
                if (status != NV14_STATUS_OK) return status;
                runtime->i64[NV14_BOUNCE_ASLEEP] = 0;
            }
        }
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_basic_collide_thwomp(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    nv14_player_snapshot *player = &state->player;
    double dy = player->pos.y - runtime->f64[NV14_THWOMP_POS_Y];
    double pen_y = NV14_THWOMP_YW + player->yw - fabs(dy);
    double dx;
    double pen_x;
    if (pen_y <= 0.0) return NV14_STATUS_OK;
    dx = player->pos.x - runtime->f64[NV14_THWOMP_POS_X];
    pen_x = NV14_THWOMP_XW + player->xw - fabs(dx);
    if (pen_x <= 0.0) return NV14_STATUS_OK;

    if (pen_y < pen_x) {
        if (dy < 0.0) {
            if (runtime->f64[NV14_THWOMP_DIR_Y] < 0.0)
                player->dead = 1;
            else
                nv14_internal_player_report_object(
                    player, 0.0, -pen_y, 0.0, -1.0
                );
        } else {
            if (runtime->f64[NV14_THWOMP_DIR_Y] > 0.0)
                player->dead = 1;
            else
                nv14_internal_player_report_object(
                    player, 0.0, pen_y, 0.0, 1.0
                );
        }
    } else if (dx < 0.0) {
        if (runtime->f64[NV14_THWOMP_DIR_X] < 0.0)
            player->dead = 1;
        else
            nv14_internal_player_report_object(
                player, -pen_x, 0.0, -1.0, 0.0
            );
    } else {
        if (runtime->f64[NV14_THWOMP_DIR_X] > 0.0)
            player->dead = 1;
        else
            nv14_internal_player_report_object(
                player, pen_x, 0.0, 1.0, 0.0
            );
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_basic_collide_door(
    nv14_state *state,
    size_t object_index,
    int *removed_current_out
)
{
    const nv14_native_object *object = &state->level->native_objects[object_index];
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    nv14_player_snapshot *player = &state->player;
    double dx;
    double dy;
    if (!runtime->i64[NV14_DOOR_TRIGGER_ACTIVE]) return NV14_STATUS_OK;
    dx = object->x - player->pos.x;
    dy = object->y - player->pos.y;
    if (sqrt(dx * dx + dy * dy) < object->r + player->r) {
        runtime->i64[NV14_DOOR_TIMER] = 0;
        if (runtime->i64[NV14_DOOR_IS_TRAP]) {
            nv14_basic_door_close(state, object_index);
            runtime->i64[NV14_DOOR_TRIGGER_ACTIVE] = 0;
            nv14_internal_grid_remove(state, object_index);
            *removed_current_out = 1;
        } else if (!runtime->i64[NV14_DOOR_IS_OPEN]) {
            return nv14_basic_door_open(state, object_index);
        }
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_basic_collide_player(
    nv14_state *state,
    size_t object_index,
    int *handled_out,
    int *removed_current_out
)
{
    const nv14_native_object *object;
    if (handled_out != NULL) *handled_out = 0;
    if (removed_current_out != NULL) *removed_current_out = 0;
    if (state == NULL || handled_out == NULL || removed_current_out == NULL ||
        object_index >= state->level->native_object_count) {
        return NV14_STATUS_INVALID_ARGUMENT;
    }
    object = &state->level->native_objects[object_index];
    if (object->kind == NV14_NATIVE_BOUNCE) {
        *handled_out = 1;
        return nv14_basic_collide_bounce(state, object_index);
    }
    if (object->kind == NV14_NATIVE_THWOMP) {
        *handled_out = 1;
        return nv14_basic_collide_thwomp(state, object_index);
    }
    if (object->kind == NV14_NATIVE_TESTDOOR) {
        *handled_out = 1;
        return nv14_basic_collide_door(
            state, object_index, removed_current_out
        );
    }
    return NV14_STATUS_OK;
}

static const nv14_internal_object_module NV14_BASIC_MODULE = {
    NV14_INTERNAL_OBJECT_MODULE_ABI_VERSION,
    sizeof(nv14_internal_object_module),
    (UINT32_C(1) << NV14_OBJ_BOUNCE) |
        (UINT32_C(1) << NV14_OBJ_THWOMP) |
        (UINT32_C(1) << NV14_OBJ_TESTDOOR),
    0,
    "objects-basic",
    NULL,
    nv14_basic_descriptor_init,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    nv14_basic_update_object,
    nv14_basic_think_object,
    nv14_basic_collide_player,
    NULL,
    NULL,
    NULL
};

const nv14_internal_object_module *nv14_objects_basic_module(void)
{
    return &NV14_BASIC_MODULE;
}

nv14_status nv14_objects_basic_register(void)
{
    return nv14_internal_register_object_module(&NV14_BASIC_MODULE);
}

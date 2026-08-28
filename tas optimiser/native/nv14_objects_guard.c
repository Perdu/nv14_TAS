/* Native FloorGuardObject (serialized object type 4).
 *
 * Source quirks retained here include the unqualified `dir` initialization
 * (all guards start with +1), the right-then-left support scan without a
 * cursor reset, activation from the player's previous-tick stored cell, and
 * AddToGrid before the guard's y coordinate is snapped to the floor.
 */

#include "nv14_objects_guard.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>

enum nv14_guard_f64_slot {
    NV14_GUARD_POS_X = 0,
    NV14_GUARD_POS_Y = 1,
    NV14_GUARD_RADIUS = 2,
    NV14_GUARD_SPEED = 3,
    NV14_GUARD_MIN_X = 4,
    NV14_GUARD_MAX_X = 5
};

enum nv14_guard_i64_slot {
    NV14_GUARD_DIRECTION = 0,
    NV14_GUARD_MIN_I = 1,
    NV14_GUARD_MAX_I = 2,
    NV14_GUARD_CELL_I = 3,
    NV14_GUARD_CELL_J = 4,
    NV14_GUARD_CHASING = 5
};

static const nv14_tile *nv14_guard_tile(
    const nv14_level *level,
    int i,
    int j
)
{
    if (level == NULL || i < 0 || i >= NV14_TILE_COLS ||
        j < 0 || j >= NV14_TILE_ROWS)
        return NULL;
    return &level->tiles[i * NV14_TILE_ROWS + j];
}

static int nv14_guard_level_edge(
    const nv14_level *level,
    const nv14_tile *tile,
    int side
)
{
    size_t index =
        ((size_t)tile->i * NV14_TILE_ROWS + (size_t)tile->j) * 4u +
        (size_t)side;
    int override_value = level->initial_edge_overrides[index];
    return override_value >= 0 ? override_value : tile->edges[side];
}

static nv14_status nv14_guard_descriptor_init(
    nv14_level *level,
    const nv14_object_descriptor *descriptor,
    nv14_error *error_out
)
{
    nv14_object_runtime runtime = {{0.0}, {0}};
    const nv14_tile *cell;
    const nv14_tile *cursor;
    double x;
    double y;
    double radius;
    double speed;
    double snapped_y;
    double min_x;
    double max_x;
    int cell_i;
    int cell_j;
    int cursor_i;
    int mini;
    int maxi;
    size_t object_index;
    nv14_status status;
    (void)error_out;
    if (level == NULL || descriptor == NULL ||
        descriptor->object_type != NV14_OBJ_FLOORGUARD)
        return NV14_STATUS_INVALID_ARGUMENT;
    if (descriptor->parameter_count != 3)
        return NV14_STATUS_INVALID_LEVEL;
    x = descriptor->parameters[0];
    y = descriptor->parameters[1];
    if (!isfinite(x) || !isfinite(y) ||
        !isfinite(descriptor->parameters[2]))
        return NV14_STATUS_UNSUPPORTED_OBJECTS;
    if (!nv14_internal_floor_index(x, NV14_TILE_W, &cell_i) ||
        !nv14_internal_floor_index(y, NV14_TILE_H, &cell_j))
        return NV14_STATUS_INVALID_LEVEL;
    cell = nv14_guard_tile(level, cell_i, cell_j);
    if (cell == NULL) return NV14_STATUS_INVALID_LEVEL;

    radius = NV14_TILE_SCALE * 0.5;
    speed = NV14_TILE_SCALE * 0.4285714285714286;
    snapped_y = cell->y + NV14_TILE_SCALE - radius;

    cursor_i = cell_i;
    for (;;) {
        ++cursor_i;
        cursor = nv14_guard_tile(level, cursor_i, cell_j);
        if (cursor == NULL) return NV14_STATUS_INVALID_LEVEL;
        if (NV14_TID_EMPTY < cursor->tile_id ||
            nv14_guard_level_edge(level, cursor, NV14_EDGE_D) != NV14_EID_SOLID) {
            max_x = cursor->x - NV14_TILE_SCALE - radius;
            break;
        }
    }

    /* Do not reset cursor_i: this is the source's asymmetric corridor scan. */
    for (;;) {
        --cursor_i;
        cursor = nv14_guard_tile(level, cursor_i, cell_j);
        if (cursor == NULL) return NV14_STATUS_INVALID_LEVEL;
        if (NV14_TID_EMPTY < cursor->tile_id ||
            nv14_guard_level_edge(level, cursor, NV14_EDGE_D) != NV14_EID_SOLID) {
            min_x = cursor->x + NV14_TILE_SCALE + radius;
            break;
        }
    }

    mini = cell_i;
    maxi = cell_i;
    cursor_i = cell_i;
    for (;;) {
        ++cursor_i;
        cursor = nv14_guard_tile(level, cursor_i, cell_j);
        if (cursor == NULL) return NV14_STATUS_INVALID_LEVEL;
        if (NV14_TID_EMPTY < cursor->tile_id) break;
        ++maxi;
    }
    cursor_i = cell_i;
    for (;;) {
        --cursor_i;
        cursor = nv14_guard_tile(level, cursor_i, cell_j);
        if (cursor == NULL) return NV14_STATUS_INVALID_LEVEL;
        if (NV14_TID_EMPTY < cursor->tile_id) break;
        --mini;
    }

    runtime.f64[NV14_GUARD_POS_X] = x;
    runtime.f64[NV14_GUARD_POS_Y] = snapped_y;
    runtime.f64[NV14_GUARD_RADIUS] = radius;
    runtime.f64[NV14_GUARD_SPEED] = speed;
    runtime.f64[NV14_GUARD_MIN_X] = min_x;
    runtime.f64[NV14_GUARD_MAX_X] = max_x;
    runtime.i64[NV14_GUARD_DIRECTION] = 1;
    runtime.i64[NV14_GUARD_MIN_I] = mini;
    runtime.i64[NV14_GUARD_MAX_I] = maxi;
    runtime.i64[NV14_GUARD_CELL_I] = cell_i;
    runtime.i64[NV14_GUARD_CELL_J] = cell_j;
    runtime.i64[NV14_GUARD_CHASING] = 0;

    status = nv14_internal_level_append_object(
        level,
        NV14_NATIVE_FLOORGUARD,
        1,
        descriptor->load_index,
        0,
        x,
        y,
        0.0,
        0.0,
        radius,
        &runtime,
        &object_index
    );
    if (status != NV14_STATUS_OK) return status;
    return nv14_internal_level_start_update(level, object_index);
}

static nv14_status nv14_guard_update_object(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime;
    double pos_x;
    double pos_y;
    double speed;
    int direction;
    int cell_i;
    int cell_j;
    int new_i;
    int new_j;
    if (state == NULL || object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    runtime = nv14_internal_object_runtime(state, object_index);
    cell_i = (int)runtime->i64[NV14_GUARD_CELL_I];
    cell_j = (int)runtime->i64[NV14_GUARD_CELL_J];
    if (!runtime->i64[NV14_GUARD_CHASING]) {
        if (cell_j == state->player.cell_j &&
            runtime->i64[NV14_GUARD_MIN_I] <= state->player.cell_i &&
            state->player.cell_i <= runtime->i64[NV14_GUARD_MAX_I]) {
            runtime->i64[NV14_GUARD_CHASING] = 1;
            if (state->player.cell_i < cell_i)
                runtime->i64[NV14_GUARD_DIRECTION] = -1;
            else if (cell_i < state->player.cell_i)
                runtime->i64[NV14_GUARD_DIRECTION] = 1;
            else
                runtime->i64[NV14_GUARD_CHASING] = 0;
        }
        return NV14_STATUS_OK;
    }

    pos_x = runtime->f64[NV14_GUARD_POS_X];
    pos_y = runtime->f64[NV14_GUARD_POS_Y];
    speed = runtime->f64[NV14_GUARD_SPEED];
    direction = (int)runtime->i64[NV14_GUARD_DIRECTION];
    if (direction < 0) {
        if (fabs(pos_x - runtime->f64[NV14_GUARD_MIN_X]) < speed) {
            pos_x = runtime->f64[NV14_GUARD_MIN_X];
            runtime->i64[NV14_GUARD_CHASING] = 0;
        } else {
            pos_x += (double)direction * speed;
        }
    } else {
        if (fabs(runtime->f64[NV14_GUARD_MAX_X] - pos_x) < speed) {
            pos_x = runtime->f64[NV14_GUARD_MAX_X];
            runtime->i64[NV14_GUARD_CHASING] = 0;
        } else {
            pos_x += (double)direction * speed;
        }
    }
    runtime->f64[NV14_GUARD_POS_X] = pos_x;
    if (!nv14_internal_floor_index(pos_x, NV14_TILE_W, &new_i) ||
        !nv14_internal_floor_index(pos_y, NV14_TILE_H, &new_j))
        return NV14_STATUS_OUT_OF_BOUNDS;
    runtime->i64[NV14_GUARD_CELL_I] = new_i;
    runtime->i64[NV14_GUARD_CELL_J] = new_j;
    return nv14_internal_grid_move(state, object_index, new_i, new_j);
}

static nv14_status nv14_guard_collide_player(
    nv14_state *state,
    size_t object_index,
    int *handled_out,
    int *removed_current_out
)
{
    const nv14_object_runtime *runtime;
    double dx;
    double dy;
    if (state == NULL || handled_out == NULL || removed_current_out == NULL ||
        object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    runtime = nv14_internal_object_runtime(state, object_index);
    *handled_out = 1;
    *removed_current_out = 0;
    dx = runtime->f64[NV14_GUARD_POS_X] - state->player.pos.x;
    dy = runtime->f64[NV14_GUARD_POS_Y] - state->player.pos.y;
    if (sqrt(dx * dx + dy * dy) <
        runtime->f64[NV14_GUARD_RADIUS] + state->player.r)
        state->player.dead = 1;
    return NV14_STATUS_OK;
}

static const nv14_internal_object_module nv14_objects_guard_module = {
    NV14_INTERNAL_OBJECT_MODULE_ABI_VERSION,
    sizeof(nv14_internal_object_module),
    UINT32_C(1) << NV14_OBJ_FLOORGUARD,
    0,
    "floor-guard",
    NULL,
    nv14_guard_descriptor_init,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    nv14_guard_update_object,
    NULL,
    nv14_guard_collide_player,
    NULL,
    NULL,
    NULL
};

nv14_status nv14_objects_guard_register(void)
{
    return nv14_internal_register_object_module(&nv14_objects_guard_module);
}

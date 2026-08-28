/*
 * Source-order native port of DroneObject's common tile-centre navigation,
 * chaser AI, and Zap weapon.  Laser/Chaingun state machines plug into the
 * callback contract in nv14_drones_internal.h.
 *
 * Strict double evaluation order is intentional.  Compile with the same
 * no-fast-math/no-contraction flags as nv14_core.c.
 */

#include "nv14_objects_drones.h"

#include <limits.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define NV14_DRONE_RADIUS (NV14_TILE_SCALE * 0.75)
#define NV14_DRONE_BASE_SPEED (NV14_TILE_SCALE * 0.07142857142857143)

#define NV14_DRONE_MOVE_SURFACE_CW 0
#define NV14_DRONE_MOVE_SURFACE_CCW 1
#define NV14_DRONE_MOVE_WANDER_CW 2
#define NV14_DRONE_MOVE_WANDER_CCW 3
#define NV14_DRONE_MOVE_WANDER_ALTERNATING 4
#define NV14_DRONE_MOVE_WANDER_RANDOM 5

#define NV14_AI_DIR_R 0
#define NV14_AI_DIR_D 1
#define NV14_AI_DIR_L 2
#define NV14_AI_DIR_U 3

#define NV14_AI_ROT_0 0
#define NV14_AI_ROT_90 1
#define NV14_AI_ROT_180 2
#define NV14_AI_ROT_270 3

static const int NV14_MOVE_CHUCHU_CW[4] = {
    NV14_AI_ROT_0,
    NV14_AI_ROT_90,
    NV14_AI_ROT_270,
    NV14_AI_ROT_180
};
static const int NV14_MOVE_CHUCHU_CCW[4] = {
    NV14_AI_ROT_0,
    NV14_AI_ROT_270,
    NV14_AI_ROT_90,
    NV14_AI_ROT_180
};
static const int NV14_MOVE_SURFACE_CW[4] = {
    NV14_AI_ROT_90,
    NV14_AI_ROT_0,
    NV14_AI_ROT_270,
    NV14_AI_ROT_180
};
static const int NV14_MOVE_SURFACE_CCW[4] = {
    NV14_AI_ROT_270,
    NV14_AI_ROT_0,
    NV14_AI_ROT_90,
    NV14_AI_ROT_180
};

static const int NV14_DRONE_EDGE_SIDE[4] = {
    NV14_EDGE_R,
    NV14_EDGE_D,
    NV14_EDGE_L,
    NV14_EDGE_U
};
static const int NV14_DRONE_EDGE_DI[4] = {1, 0, -1, 0};
static const int NV14_DRONE_EDGE_DJ[4] = {0, 1, 0, -1};
static const double NV14_DRONE_DIR_X[4] = {1.0, 0.0, -1.0, 0.0};
static const double NV14_DRONE_DIR_Y[4] = {0.0, 1.0, 0.0, -1.0};

static const nv14_drone_weapon_hooks *NV14_DRONE_WEAPON_HOOKS[3];

static void nv14_drone_set_error(
    nv14_error *error_out,
    nv14_status status,
    const char *message
)
{
    if (error_out == NULL) return;
    memset(error_out, 0, sizeof(*error_out));
    error_out->code = status;
    error_out->object_type = NV14_OBJ_DRONE;
    error_out->tile_id = -1;
    error_out->tile_i = -1;
    error_out->tile_j = -1;
    if (message != NULL)
        (void)snprintf(
            error_out->message,
            sizeof(error_out->message),
            "%s",
            message
        );
}

static const nv14_tile *nv14_drone_tile(
    const nv14_level *level,
    int i,
    int j
)
{
    if (level == NULL || i < 0 || i >= NV14_TILE_COLS ||
        j < 0 || j >= NV14_TILE_ROWS)
        return NULL;
    return &level->tiles[(size_t)i * NV14_TILE_ROWS + (size_t)j];
}

static int nv14_drone_edge_value(
    const nv14_state *state,
    const nv14_tile *tile,
    int side
)
{
    if (state->edge_override_count == 0) return tile->edges[side];
    size_t index =
        ((size_t)tile->i * NV14_TILE_ROWS + (size_t)tile->j) * 4u +
        (size_t)side;
    int override_value = state->edge_overrides[index];
    return override_value >= 0 ? override_value : tile->edges[side];
}

static int nv14_drone_weapon_from_kind(nv14_native_kind kind)
{
    if (kind == NV14_NATIVE_DRONE_ZAP) return NV14_DRONE_WEAPON_ZAP;
    if (kind == NV14_NATIVE_DRONE_LASER) return NV14_DRONE_WEAPON_LASER;
    if (kind == NV14_NATIVE_DRONE_CHAINGUN)
        return NV14_DRONE_WEAPON_CHAINGUN;
    return -1;
}

static nv14_native_kind nv14_drone_kind_from_weapon(int weapon_type)
{
    if (weapon_type == NV14_DRONE_WEAPON_ZAP)
        return NV14_NATIVE_DRONE_ZAP;
    if (weapon_type == NV14_DRONE_WEAPON_LASER)
        return NV14_NATIVE_DRONE_LASER;
    return NV14_NATIVE_DRONE_CHAINGUN;
}

static const nv14_drone_weapon_hooks *nv14_drone_hooks(int weapon_type)
{
    if (weapon_type < NV14_DRONE_WEAPON_LASER ||
        weapon_type > NV14_DRONE_WEAPON_CHAINGUN)
        return NULL;
    return NV14_DRONE_WEAPON_HOOKS[weapon_type];
}

nv14_status nv14_drones_register_weapon_hooks(
    const nv14_drone_weapon_hooks *hooks
)
{
    const nv14_drone_weapon_hooks *registered;
    if (hooks == NULL ||
        hooks->abi_version != NV14_DRONE_WEAPON_HOOKS_ABI_VERSION ||
        hooks->struct_size < sizeof(*hooks) ||
        hooks->weapon_type < NV14_DRONE_WEAPON_LASER ||
        hooks->weapon_type > NV14_DRONE_WEAPON_CHAINGUN ||
        hooks->update_nonmoving == NULL || hooks->think == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    registered = NV14_DRONE_WEAPON_HOOKS[hooks->weapon_type];
    if (registered == hooks) return NV14_STATUS_OK;
    if (registered != NULL) return NV14_STATUS_INVALID_ARGUMENT;
    NV14_DRONE_WEAPON_HOOKS[hooks->weapon_type] = hooks;
    return NV14_STATUS_OK;
}

static int nv14_drone_trunc_int(double value, int *result_out)
{
    if (!isfinite(value) || value < (double)INT_MIN || value > (double)INT_MAX)
        return 0;
    *result_out = (int)value;
    return 1;
}

static nv14_status nv14_drone_descriptor_init(
    nv14_level *level,
    const nv14_object_descriptor *descriptor,
    nv14_error *error_out
)
{
    nv14_object_runtime runtime;
    const nv14_drone_weapon_hooks *hooks;
    const nv14_tile *cell;
    nv14_native_kind kind;
    nv14_status status;
    size_t object_index;
    double x;
    double y;
    double speed;
    int cell_i;
    int cell_j;
    int move_type;
    int weapon_type;
    int current_direction;

    if (level == NULL || descriptor == NULL ||
        descriptor->object_type != NV14_OBJ_DRONE)
        return NV14_STATUS_INVALID_ARGUMENT;
    if (!level->simulate_enemies) return NV14_STATUS_OK;
    if (descriptor->parameter_count != 6) {
        nv14_drone_set_error(
            error_out,
            NV14_STATUS_UNSUPPORTED_OBJECTS,
            "DroneObject requires six parameters"
        );
        return NV14_STATUS_UNSUPPORTED_OBJECTS;
    }
    x = descriptor->parameters[0];
    y = descriptor->parameters[1];
    if (!isfinite(x) || !isfinite(y) ||
        !isfinite(descriptor->parameters[3]) ||
        !nv14_drone_trunc_int(descriptor->parameters[2], &move_type) ||
        !nv14_drone_trunc_int(descriptor->parameters[4], &weapon_type) ||
        !nv14_drone_trunc_int(
            descriptor->parameters[5], &current_direction
        ) ||
        move_type < NV14_DRONE_MOVE_SURFACE_CW ||
        move_type > NV14_DRONE_MOVE_WANDER_RANDOM ||
        weapon_type < NV14_DRONE_WEAPON_ZAP ||
        weapon_type > NV14_DRONE_WEAPON_CHAINGUN ||
        current_direction < NV14_AI_DIR_R ||
        current_direction > NV14_AI_DIR_U) {
        nv14_drone_set_error(
            error_out,
            NV14_STATUS_UNSUPPORTED_OBJECTS,
            "DroneObject has invalid movement, weapon, or direction parameters"
        );
        return NV14_STATUS_UNSUPPORTED_OBJECTS;
    }
    if (!nv14_internal_floor_index(x, NV14_TILE_W, &cell_i) ||
        !nv14_internal_floor_index(y, NV14_TILE_H, &cell_j)) {
        nv14_drone_set_error(
            error_out,
            NV14_STATUS_OUT_OF_BOUNDS,
            "DroneObject position is outside native cell coordinates"
        );
        return NV14_STATUS_OUT_OF_BOUNDS;
    }
    cell = nv14_drone_tile(level, cell_i, cell_j);
    if (cell == NULL) {
        nv14_drone_set_error(
            error_out,
            NV14_STATUS_OUT_OF_BOUNDS,
            "DroneObject position is outside the tile map"
        );
        return NV14_STATUS_OUT_OF_BOUNDS;
    }

    hooks = nv14_drone_hooks(weapon_type);
    if (weapon_type != NV14_DRONE_WEAPON_ZAP && hooks == NULL)
        return NV14_STATUS_UNSUPPORTED_OBJECTS;

    memset(&runtime, 0, sizeof(runtime));
    runtime.f64[NV14_DRONE_POS_X] = cell->x;
    runtime.f64[NV14_DRONE_POS_Y] = cell->y;
    runtime.f64[NV14_DRONE_GOAL_X] = cell->x;
    runtime.f64[NV14_DRONE_GOAL_Y] = cell->y;
    speed = NV14_DRONE_BASE_SPEED;
    if (weapon_type == NV14_DRONE_WEAPON_ZAP)
        speed *= 2.0;
    else if (weapon_type == NV14_DRONE_WEAPON_LASER)
        speed *= 0.5;
    else
        speed *= 0.75;
    runtime.f64[NV14_DRONE_SPEED] = speed;
    runtime.i64[NV14_DRONE_CUR_DIR] = current_direction;
    runtime.i64[NV14_DRONE_MOVE_TYPE] = move_type;
    runtime.i64[NV14_DRONE_CELL_I] = cell_i;
    runtime.i64[NV14_DRONE_CELL_J] = cell_j;
    runtime.i64[NV14_DRONE_IS_CHASER] =
        weapon_type == NV14_DRONE_WEAPON_ZAP &&
        descriptor->parameters[3] != 0.0;
    runtime.i64[NV14_DRONE_IS_CHASING] = 0;
    runtime.i64[NV14_DRONE_SURFACE_FUTURE_DIR] = -1;
    runtime.i64[NV14_DRONE_SURFACE_GRAB_PENDING] = 0;
    runtime.i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_MOVING;

    if (hooks != NULL && hooks->init_runtime != NULL) {
        status = hooks->init_runtime(level, descriptor, &runtime, error_out);
        if (status != NV14_STATUS_OK) return status;
    }

    kind = nv14_drone_kind_from_weapon(weapon_type);
    status = nv14_internal_level_append_object(
        level,
        kind,
        1,
        descriptor->load_index,
        0,
        cell->x,
        cell->y,
        0.0,
        0.0,
        NV14_DRONE_RADIUS,
        &runtime,
        &object_index
    );
    if (status != NV14_STATUS_OK) {
        nv14_drone_set_error(
            error_out,
            status,
            "cannot append native DroneObject"
        );
        return status;
    }
    status = nv14_internal_level_start_update(level, object_index);
    if (status != NV14_STATUS_OK) return status;
    if (weapon_type != NV14_DRONE_WEAPON_ZAP)
        status = nv14_internal_level_start_think(level, object_index);
    return status;
}

static int nv14_drone_rotate(int current_direction, int rotation)
{
    if (rotation < NV14_AI_ROT_0 || rotation > NV14_AI_ROT_270)
        return current_direction;
    return (current_direction + rotation) % 4;
}

static nv14_status nv14_drone_test_edge(
    nv14_state *state,
    nv14_object_runtime *runtime,
    int direction,
    int *open_out
)
{
    const nv14_tile *cell;
    const nv14_tile *next_cell;
    int cell_i;
    int cell_j;
    int side;
    if (open_out == NULL || direction < NV14_AI_DIR_R ||
        direction > NV14_AI_DIR_U)
        return NV14_STATUS_INVALID_ARGUMENT;
    *open_out = 0;
    cell_i = (int)runtime->i64[NV14_DRONE_CELL_I];
    cell_j = (int)runtime->i64[NV14_DRONE_CELL_J];
    cell = nv14_drone_tile(state->level, cell_i, cell_j);
    if (cell == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
    side = NV14_DRONE_EDGE_SIDE[direction];
    if (nv14_drone_edge_value(state, cell, side) != NV14_EID_OFF)
        return NV14_STATUS_OK;
    next_cell = nv14_drone_tile(
        state->level,
        cell_i + NV14_DRONE_EDGE_DI[direction],
        cell_j + NV14_DRONE_EDGE_DJ[direction]
    );
    if (next_cell == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
    runtime->f64[NV14_DRONE_GOAL_X] = next_cell->x;
    runtime->f64[NV14_DRONE_GOAL_Y] = next_cell->y;
    *open_out = 1;
    return NV14_STATUS_OK;
}

static const int *nv14_drone_move_list(int move_type)
{
    if (move_type == NV14_DRONE_MOVE_SURFACE_CW)
        return NV14_MOVE_SURFACE_CW;
    if (move_type == NV14_DRONE_MOVE_SURFACE_CCW)
        return NV14_MOVE_SURFACE_CCW;
    if (move_type == NV14_DRONE_MOVE_WANDER_CCW)
        return NV14_MOVE_CHUCHU_CCW;
    return NV14_MOVE_CHUCHU_CW;
}

static nv14_status nv14_drone_get_goal_simple(
    nv14_state *state,
    nv14_object_runtime *runtime,
    const int rotations[4],
    int *direction_out
)
{
    int current_direction;
    int index;
    if (direction_out == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    current_direction = (int)runtime->i64[NV14_DRONE_CUR_DIR];
    for (index = 0; index < 4; ++index) {
        int open;
        int direction = nv14_drone_rotate(
            current_direction, rotations[index]
        );
        nv14_status status = nv14_drone_test_edge(
            state, runtime, direction, &open
        );
        if (status != NV14_STATUS_OK) return status;
        if (open) {
            *direction_out = direction;
            return NV14_STATUS_OK;
        }
    }
    *direction_out = current_direction;
    return NV14_STATUS_OK;
}

static nv14_status nv14_drone_get_new_goal(
    nv14_state *state,
    nv14_object_runtime *runtime,
    int *direction_out
)
{
    int move_type = (int)runtime->i64[NV14_DRONE_MOVE_TYPE];
    int current_direction = (int)runtime->i64[NV14_DRONE_CUR_DIR];
    const int *rotations;
    nv14_status status;
    if (move_type == NV14_DRONE_MOVE_WANDER_ALTERNATING) {
        rotations = runtime->i64[NV14_DRONE_AI_COUNTER2] == 0
            ? NV14_MOVE_CHUCHU_CW
            : NV14_MOVE_CHUCHU_CCW;
        status = nv14_drone_get_goal_simple(
            state, runtime, rotations, direction_out
        );
        if (status != NV14_STATUS_OK) return status;
        if (*direction_out != current_direction)
            runtime->i64[NV14_DRONE_AI_COUNTER2] =
                1 - runtime->i64[NV14_DRONE_AI_COUNTER2];
        return NV14_STATUS_OK;
    }
    if (move_type == NV14_DRONE_MOVE_WANDER_RANDOM) {
        int was_even = runtime->i64[NV14_DRONE_AI_COUNTER] % 2 == 0;
        rotations = was_even ? NV14_MOVE_CHUCHU_CW : NV14_MOVE_CHUCHU_CCW;
        status = nv14_drone_get_goal_simple(
            state, runtime, rotations, direction_out
        );
        if (status != NV14_STATUS_OK) return status;
        if (*direction_out != current_direction)
            runtime->i64[NV14_DRONE_AI_COUNTER] = was_even ? 1 : 0;
        return NV14_STATUS_OK;
    }
    return nv14_drone_get_goal_simple(
        state,
        runtime,
        nv14_drone_move_list(move_type),
        direction_out
    );
}

static nv14_status nv14_drone_find_target(
    nv14_state *state,
    nv14_object_runtime *runtime,
    int direction,
    int target_cells,
    int *found_out
)
{
    const nv14_tile *origin;
    const nv14_tile *cell;
    int side;
    int di;
    int dj;
    int distance = 0;
    if (found_out == NULL || target_cells < 0 ||
        direction < NV14_AI_DIR_R || direction > NV14_AI_DIR_U)
        return NV14_STATUS_INVALID_ARGUMENT;
    *found_out = 0;
    origin = nv14_drone_tile(
        state->level,
        (int)runtime->i64[NV14_DRONE_CELL_I],
        (int)runtime->i64[NV14_DRONE_CELL_J]
    );
    if (origin == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
    cell = origin;
    side = NV14_DRONE_EDGE_SIDE[direction];
    di = NV14_DRONE_EDGE_DI[direction];
    dj = NV14_DRONE_EDGE_DJ[direction];

    while (distance < target_cells) {
        ++distance;
        if (nv14_drone_edge_value(state, cell, side) != NV14_EID_OFF)
            return NV14_STATUS_OK;
        cell = nv14_drone_tile(state->level, cell->i + di, cell->j + dj);
        if (cell == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
    }
    while (nv14_drone_edge_value(state, cell, side) == NV14_EID_OFF) {
        ++distance;
        cell = nv14_drone_tile(state->level, cell->i + di, cell->j + dj);
        if (cell == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
    }

    if (direction == NV14_AI_DIR_R) {
        runtime->f64[NV14_DRONE_GOAL_X] =
            origin->x + (double)distance * (2.0 * NV14_TILE_SCALE);
    } else if (direction == NV14_AI_DIR_D) {
        runtime->f64[NV14_DRONE_GOAL_Y] =
            origin->y + (double)distance * (2.0 * NV14_TILE_SCALE);
    } else if (direction == NV14_AI_DIR_L) {
        runtime->f64[NV14_DRONE_GOAL_X] =
            origin->x - (double)distance * (2.0 * NV14_TILE_SCALE);
    } else {
        runtime->f64[NV14_DRONE_GOAL_Y] =
            origin->y - (double)distance * (2.0 * NV14_TILE_SCALE);
    }
    *found_out = 1;
    return NV14_STATUS_OK;
}

static nv14_status nv14_drone_chase_axis(
    nv14_state *state,
    nv14_object_runtime *runtime,
    int *chasing_out
)
{
    int cell_dx;
    int cell_dy;
    int target_cells;
    int direction;
    int found;
    int current_direction = (int)runtime->i64[NV14_DRONE_CUR_DIR];
    nv14_status status;
    *chasing_out = 0;
    cell_dx = state->player.cell_i - (int)runtime->i64[NV14_DRONE_CELL_I];
    cell_dy = state->player.cell_j - (int)runtime->i64[NV14_DRONE_CELL_J];
    if (abs(cell_dx) < 1) {
        target_cells = abs(cell_dy);
        if (state->player.pos.y < runtime->f64[NV14_DRONE_POS_Y]) {
            if (current_direction == NV14_AI_DIR_D) return NV14_STATUS_OK;
            direction = NV14_AI_DIR_U;
        } else {
            if (current_direction == NV14_AI_DIR_U) return NV14_STATUS_OK;
            direction = NV14_AI_DIR_D;
        }
    } else if (abs(cell_dy) < 1) {
        target_cells = abs(cell_dx);
        if (state->player.pos.x < runtime->f64[NV14_DRONE_POS_X]) {
            if (current_direction == NV14_AI_DIR_R) return NV14_STATUS_OK;
            direction = NV14_AI_DIR_L;
        } else {
            if (current_direction == NV14_AI_DIR_L) return NV14_STATUS_OK;
            direction = NV14_AI_DIR_R;
        }
    } else {
        return NV14_STATUS_OK;
    }
    status = nv14_drone_find_target(
        state, runtime, direction, target_cells, &found
    );
    if (status != NV14_STATUS_OK || !found) return status;
    runtime->i64[NV14_DRONE_CUR_DIR] = direction;
    if (runtime->i64[NV14_DRONE_MOVE_TYPE] < NV14_DRONE_MOVE_WANDER_CW) {
        int rotation =
            runtime->i64[NV14_DRONE_MOVE_TYPE] ==
                NV14_DRONE_MOVE_SURFACE_CW
            ? NV14_AI_ROT_270
            : NV14_AI_ROT_90;
        runtime->i64[NV14_DRONE_SURFACE_GRAB_PENDING] = 1;
        runtime->i64[NV14_DRONE_SURFACE_FUTURE_DIR] =
            nv14_drone_rotate(direction, rotation);
    }
    *chasing_out = 1;
    return NV14_STATUS_OK;
}

static nv14_status nv14_drone_chase(
    nv14_state *state,
    nv14_object_runtime *runtime,
    int *chasing_out
)
{
    *chasing_out = 0;
    if (!runtime->i64[NV14_DRONE_IS_CHASER]) return NV14_STATUS_OK;
    if (runtime->i64[NV14_DRONE_SURFACE_GRAB_PENDING]) {
        runtime->i64[NV14_DRONE_SURFACE_GRAB_PENDING] = 0;
        if (runtime->i64[NV14_DRONE_SURFACE_FUTURE_DIR] >= 0)
            runtime->i64[NV14_DRONE_CUR_DIR] =
                runtime->i64[NV14_DRONE_SURFACE_FUTURE_DIR];
        return NV14_STATUS_OK;
    }
    return nv14_drone_chase_axis(state, runtime, chasing_out);
}

nv14_status nv14_drones_update_move(
    nv14_state *state,
    size_t object_index,
    int allow_zap_chase
)
{
    const nv14_native_object *object;
    nv14_object_runtime *runtime;
    nv14_status status;
    double pos_x;
    double pos_y;
    double goal_x;
    double goal_y;
    double dx;
    double dy;
    double speed;
    int current_direction;
    int old_i;
    int old_j;
    int new_i;
    int new_j;
    if (state == NULL || object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    object = &state->level->native_objects[object_index];
    if (nv14_drone_weapon_from_kind((nv14_native_kind)object->kind) < 0)
        return NV14_STATUS_INVALID_ARGUMENT;
    runtime = nv14_internal_object_runtime(state, object_index);
    runtime->i64[NV14_DRONE_AI_COUNTER] += 1;
    pos_x = runtime->f64[NV14_DRONE_POS_X];
    pos_y = runtime->f64[NV14_DRONE_POS_Y];
    goal_x = runtime->f64[NV14_DRONE_GOAL_X];
    goal_y = runtime->f64[NV14_DRONE_GOAL_Y];
    dx = goal_x - pos_x;
    dy = goal_y - pos_y;
    speed = runtime->f64[NV14_DRONE_SPEED];
    if (dx * dx + dy * dy < speed * speed) {
        int chasing = 0;
        int direction;
        pos_x = goal_x;
        pos_y = goal_y;
        runtime->f64[NV14_DRONE_POS_X] = pos_x;
        runtime->f64[NV14_DRONE_POS_Y] = pos_y;
        if (allow_zap_chase && object->kind == NV14_NATIVE_DRONE_ZAP) {
            status = nv14_drone_chase(state, runtime, &chasing);
            if (status != NV14_STATUS_OK) return status;
        }
        if (chasing) {
            runtime->i64[NV14_DRONE_IS_CHASING] = 1;
        } else {
            status = nv14_drone_get_new_goal(state, runtime, &direction);
            if (status != NV14_STATUS_OK) return status;
            runtime->i64[NV14_DRONE_CUR_DIR] = direction;
            runtime->i64[NV14_DRONE_IS_CHASING] = 0;
        }
    } else {
        double move_speed = speed;
        current_direction = (int)runtime->i64[NV14_DRONE_CUR_DIR];
        if (current_direction < NV14_AI_DIR_R ||
            current_direction > NV14_AI_DIR_U)
            return NV14_STATUS_INVALID_LEVEL;
        if (allow_zap_chase && object->kind == NV14_NATIVE_DRONE_ZAP &&
            runtime->i64[NV14_DRONE_IS_CHASING])
            move_speed *= 2.0;
        pos_x += NV14_DRONE_DIR_X[current_direction] * move_speed;
        pos_y += NV14_DRONE_DIR_Y[current_direction] * move_speed;
        runtime->f64[NV14_DRONE_POS_X] = pos_x;
        runtime->f64[NV14_DRONE_POS_Y] = pos_y;
    }

    old_i = (int)runtime->i64[NV14_DRONE_CELL_I];
    old_j = (int)runtime->i64[NV14_DRONE_CELL_J];
    /* A drone normally advances only a fraction of a cell per tick.  Its
       stored cell is authoritative for the live grid, so retain it without
       two floor operations and a no-op grid_move while the new position is
       still inside the same half-open tile interval.  Bounds in the supported
       tile domain are exact binary64 integers.  Boundary, non-finite,
       out-of-domain and genuinely changed-cell cases retain the generic path. */
    if (old_i >= 0 && old_i < NV14_TILE_COLS &&
        old_j >= 0 && old_j < NV14_TILE_ROWS &&
        pos_x >= (double)old_i * NV14_TILE_W &&
        pos_x < ((double)old_i + 1.0) * NV14_TILE_W &&
        pos_y >= (double)old_j * NV14_TILE_H &&
        pos_y < ((double)old_j + 1.0) * NV14_TILE_H) {
        return NV14_STATUS_OK;
    }
    if (!nv14_internal_floor_index(pos_x, NV14_TILE_W, &new_i) ||
        !nv14_internal_floor_index(pos_y, NV14_TILE_H, &new_j))
        return NV14_STATUS_OUT_OF_BOUNDS;
    runtime->i64[NV14_DRONE_CELL_I] = new_i;
    runtime->i64[NV14_DRONE_CELL_J] = new_j;
    return nv14_internal_grid_move(state, object_index, new_i, new_j);
}

nv14_status nv14_drones_start_moving(
    nv14_state *state,
    size_t object_index
)
{
    nv14_status status;
    if (state == NULL || object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    status = nv14_internal_start_think(state, object_index);
    if (status != NV14_STATUS_OK) return status;
    nv14_internal_object_runtime(state, object_index)->i64[NV14_DRONE_MODE] =
        NV14_DRONE_MODE_MOVING;
    return NV14_STATUS_OK;
}

static nv14_status nv14_drone_update_object(
    nv14_state *state,
    size_t object_index
)
{
    const nv14_native_object *object;
    const nv14_drone_weapon_hooks *hooks;
    int weapon_type;
    if (state == NULL || object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    object = &state->level->native_objects[object_index];
    weapon_type = nv14_drone_weapon_from_kind((nv14_native_kind)object->kind);
    if (weapon_type < 0) return NV14_STATUS_UNSUPPORTED_OBJECTS;
    if (weapon_type == NV14_DRONE_WEAPON_ZAP)
        return nv14_drones_update_move(state, object_index, 1);
    if (nv14_internal_object_runtime(state, object_index)->
            i64[NV14_DRONE_MODE] ==
        NV14_DRONE_MODE_MOVING)
        return nv14_drones_update_move(state, object_index, 0);
    hooks = nv14_drone_hooks(weapon_type);
    if (hooks == NULL) return NV14_STATUS_UNSUPPORTED_OBJECTS;
    return hooks->update_nonmoving(state, object_index);
}

static nv14_status nv14_drone_think_object(
    nv14_state *state,
    size_t object_index
)
{
    const nv14_native_object *object;
    const nv14_drone_weapon_hooks *hooks;
    int weapon_type;
    if (state == NULL || object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    object = &state->level->native_objects[object_index];
    weapon_type = nv14_drone_weapon_from_kind((nv14_native_kind)object->kind);
    hooks = nv14_drone_hooks(weapon_type);
    if (hooks == NULL) return NV14_STATUS_UNSUPPORTED_OBJECTS;
    return hooks->think(state, object_index);
}

static nv14_status nv14_drone_collide_player(
    nv14_state *state,
    size_t object_index,
    int *handled_out,
    int *removed_current_out
)
{
    const nv14_native_object *object;
    const nv14_object_runtime *runtime;
    double dx;
    double dy;
    double contact_radius;
    if (handled_out != NULL) *handled_out = 0;
    if (removed_current_out != NULL) *removed_current_out = 0;
    if (state == NULL || handled_out == NULL || removed_current_out == NULL ||
        object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    object = &state->level->native_objects[object_index];
    if (nv14_drone_weapon_from_kind((nv14_native_kind)object->kind) < 0)
        return NV14_STATUS_OK;
    *handled_out = 1;
    if (object->kind != NV14_NATIVE_DRONE_ZAP) return NV14_STATUS_OK;
    runtime = nv14_internal_object_runtime(state, object_index);
    dx = runtime->f64[NV14_DRONE_POS_X] - state->player.pos.x;
    dy = runtime->f64[NV14_DRONE_POS_Y] - state->player.pos.y;
    contact_radius = object->r + state->player.r;
    if (dx * dx + dy * dy < contact_radius * contact_radius)
        state->player.dead = 1;
    return NV14_STATUS_OK;
}

static const nv14_internal_object_module NV14_DRONES_MODULE = {
    NV14_INTERNAL_OBJECT_MODULE_ABI_VERSION,
    sizeof(nv14_internal_object_module),
    UINT32_C(1) << NV14_OBJ_DRONE,
    0,
    "drone-common-zap",
    NULL,
    nv14_drone_descriptor_init,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    nv14_drone_update_object,
    nv14_drone_think_object,
    nv14_drone_collide_player,
    NULL,
    NULL,
    NULL
};

const nv14_internal_object_module *nv14_objects_drones_module(void)
{
    return &NV14_DRONES_MODULE;
}

nv14_status nv14_objects_drones_register(void)
{
    return nv14_internal_register_object_module(&NV14_DRONES_MODULE);
}

nv14_status nv14_objects_drones_snapshot(
    const nv14_state *state,
    uint32_t load_index,
    nv14_drone_snapshot *out
)
{
    const nv14_native_object *object = NULL;
    const nv14_object_runtime *runtime;
    size_t object_index;
    int weapon_type;
    if (state == NULL || out == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    for (object_index = 0;
         object_index < state->level->native_object_count;
         ++object_index) {
        const nv14_native_object *candidate =
            &state->level->native_objects[object_index];
        weapon_type = nv14_drone_weapon_from_kind(
            (nv14_native_kind)candidate->kind
        );
        if (candidate->load_index == load_index && weapon_type >= 0) {
            object = candidate;
            break;
        }
    }
    if (object == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
    weapon_type = nv14_drone_weapon_from_kind((nv14_native_kind)object->kind);
    runtime = nv14_internal_object_runtime_const(state, object_index);
    memset(out, 0, sizeof(*out));
    out->load_index = object->load_index;
    out->weapon_type = weapon_type;
    out->move_type = (int)runtime->i64[NV14_DRONE_MOVE_TYPE];
    out->current_direction = (int)runtime->i64[NV14_DRONE_CUR_DIR];
    out->position.x = runtime->f64[NV14_DRONE_POS_X];
    out->position.y = runtime->f64[NV14_DRONE_POS_Y];
    out->goal.x = runtime->f64[NV14_DRONE_GOAL_X];
    out->goal.y = runtime->f64[NV14_DRONE_GOAL_Y];
    out->speed = runtime->f64[NV14_DRONE_SPEED];
    out->cell_i = (int32_t)runtime->i64[NV14_DRONE_CELL_I];
    out->cell_j = (int32_t)runtime->i64[NV14_DRONE_CELL_J];
    out->ai_counter = runtime->i64[NV14_DRONE_AI_COUNTER];
    out->ai_counter2 = runtime->i64[NV14_DRONE_AI_COUNTER2];
    out->is_chaser = runtime->i64[NV14_DRONE_IS_CHASER] != 0;
    out->is_chasing = runtime->i64[NV14_DRONE_IS_CHASING] != 0;
    out->surface_future_direction =
        (int)runtime->i64[NV14_DRONE_SURFACE_FUTURE_DIR];
    out->surface_grab_pending =
        runtime->i64[NV14_DRONE_SURFACE_GRAB_PENDING] != 0;
    out->mode = (int)runtime->i64[NV14_DRONE_MODE];
    out->updating = state->update_active[object_index] != 0;
    out->thinking = state->thinker_active[object_index] != 0;
    out->grid_active = state->object_cell_slot[object_index] >= 0;
    return NV14_STATUS_OK;
}

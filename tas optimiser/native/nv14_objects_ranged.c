/*
 * Source-order ports of n v1.4's gauss turret and homing rocket launcher.
 * Floating-point ordering is intentional; compile under the core's strict FP
 * flags and do not enable contraction or fast-math.
 */

#include "nv14_objects_ranged.h"

#include "nv14_rays.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define NV14_RANGED_PREFIRE_DELAY 10
#define NV14_RANGED_POSTFIRE_DELAY 10
#define NV14_TURRET_CLOSE_AIM_SPEED 0.05
#define NV14_TURRET_MID_AIM_SPEED 0.035
#define NV14_TURRET_FAR_AIM_SPEED 0.03
#define NV14_TURRET_SHOT_RATE 60.0
#define NV14_TURRET_OUTER_THRESHOLD ((NV14_TILE_SCALE * 8.0) * (NV14_TILE_SCALE * 8.0))
#define NV14_TURRET_INNER_THRESHOLD ((NV14_TILE_SCALE * 2.0) * (NV14_TILE_SCALE * 2.0))
#define NV14_TURRET_MID_DISTANCE \
    (0.25 * (NV14_TILE_SCALE * 8.0) + 0.75 * (NV14_TILE_SCALE * 2.0))
#define NV14_TURRET_MID_THRESHOLD \
    (NV14_TURRET_MID_DISTANCE * NV14_TURRET_MID_DISTANCE)
#define NV14_HOMING_MAX_SPEED (NV14_TILE_SCALE * 0.2857142857142857)
#define NV14_HOMING_START_ACCEL 0.1
#define NV14_HOMING_ACCEL_RATE 1.1
#define NV14_HOMING_TURN_RATE 0.1

enum nv14_turret_f64_slot {
    NV14_TURRET_VIEW_X = 0,
    NV14_TURRET_VIEW_Y = 1,
    NV14_TURRET_TARGET_X = 2,
    NV14_TURRET_TARGET_Y = 3,
    NV14_TURRET_AIM_X = 4,
    NV14_TURRET_AIM_Y = 5,
    NV14_TURRET_AIM_SPEED = 6,
    NV14_TURRET_SHOT_TIMER = 7
};

enum nv14_homing_f64_slot {
    NV14_HOMING_POS_X = 0,
    NV14_HOMING_POS_Y = 1,
    NV14_HOMING_DIR_X = 2,
    NV14_HOMING_DIR_Y = 3,
    NV14_HOMING_VIEW_X = 4,
    NV14_HOMING_VIEW_Y = 5,
    NV14_HOMING_SPEED = 6,
    NV14_HOMING_CURRENT_ACCEL = 7
};

enum nv14_ranged_i64_slot {
    NV14_RANGED_MODE = 0,
    NV14_RANGED_FIRE_DELAY_TIMER = 1,
    NV14_RANGED_CELL_I = 2,
    NV14_RANGED_CELL_J = 3
};

static void nv14_ranged_set_error(
    nv14_error *error_out,
    nv14_status status,
    int object_type,
    const char *message
)
{
    if (error_out == NULL) return;
    memset(error_out, 0, sizeof(*error_out));
    error_out->code = status;
    error_out->object_type = object_type;
    error_out->tile_id = -1;
    error_out->tile_i = -1;
    error_out->tile_j = -1;
    if (message != NULL)
        (void)snprintf(error_out->message, sizeof(error_out->message), "%s", message);
}

static int nv14_ranged_object_type(
    const nv14_level *level,
    size_t object_index
)
{
    const nv14_native_object *object;
    if (level == NULL || object_index >= level->native_object_count)
        return -1;
    object = &level->native_objects[object_index];
    if (object->load_index >= level->descriptor_count)
        return -1;
    return level->descriptors[object->load_index].object_type;
}

static const nv14_tile *nv14_ranged_tile_at(
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

static int nv14_ranged_edge_value(
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

static nv14_status nv14_ranged_query_point(
    const nv14_level *level,
    double x,
    double y,
    const nv14_tile **cell_out,
    int *solid_out
)
{
    int i;
    int j;
    double dx;
    double dy;
    double vx;
    double vy;
    double radius;
    const nv14_tile *cell;

    if (level == NULL || solid_out == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    *solid_out = 0;
    if (!nv14_internal_floor_index(x, NV14_TILE_W, &i) ||
        !nv14_internal_floor_index(y, NV14_TILE_H, &j))
        return NV14_STATUS_OUT_OF_BOUNDS;
    cell = nv14_ranged_tile_at(level, i, j);
    if (cell == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
    if (cell_out != NULL) *cell_out = cell;
    if (cell->tile_id == NV14_TID_EMPTY)
        return NV14_STATUS_OK;
    if (cell->ctype == NV14_CTYPE_FULL) {
        *solid_out = 1;
        return NV14_STATUS_OK;
    }
    dx = x - cell->x;
    dy = y - cell->y;
    if (cell->ctype == NV14_CTYPE_HALF) {
        *solid_out =
            dx * (double)cell->signx + dy * (double)cell->signy <= 0.0;
    } else if (cell->ctype == NV14_CTYPE_45DEG) {
        *solid_out = dx * cell->sx + dy * cell->sy <= 0.0;
    } else if (cell->ctype == NV14_CTYPE_CONCAVE) {
        vx = cell->x + (double)cell->signx * NV14_TILE_SCALE - x;
        vy = cell->y + (double)cell->signy * NV14_TILE_SCALE - y;
        radius = NV14_TILE_SCALE * 2.0;
        *solid_out = radius * radius <= vx * vx + vy * vy;
    } else if (cell->ctype == NV14_CTYPE_CONVEX) {
        vx = x - (cell->x - (double)cell->signx * NV14_TILE_SCALE);
        vy = y - (cell->y - (double)cell->signy * NV14_TILE_SCALE);
        radius = NV14_TILE_SCALE * 2.0;
        *solid_out = vx * vx + vy * vy <= radius * radius;
    } else if (cell->ctype == NV14_CTYPE_22DEGS) {
        vx = x - (cell->x + (double)cell->signx * NV14_TILE_SCALE);
        vy = y - (cell->y - (double)cell->signy * NV14_TILE_SCALE);
        *solid_out = vx * cell->sx + vy * cell->sy <= 0.0;
    } else if (cell->ctype == NV14_CTYPE_22DEGB) {
        vx = x - (cell->x - (double)cell->signx * NV14_TILE_SCALE);
        vy = y - (cell->y + (double)cell->signy * NV14_TILE_SCALE);
        *solid_out = vx * cell->sx + vy * cell->sy <= 0.0;
    } else if (cell->ctype == NV14_CTYPE_67DEGS) {
        vx = x - (cell->x - (double)cell->signx * NV14_TILE_SCALE);
        vy = y - (cell->y + (double)cell->signy * NV14_TILE_SCALE);
        *solid_out = vx * cell->sx + vy * cell->sy <= 0.0;
    } else if (cell->ctype == NV14_CTYPE_67DEGB) {
        vx = x - (cell->x + (double)cell->signx * NV14_TILE_SCALE);
        vy = y - (cell->y - (double)cell->signy * NV14_TILE_SCALE);
        *solid_out = vx * cell->sx + vy * cell->sy <= 0.0;
    } else {
        return NV14_STATUS_UNSUPPORTED_TILE;
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_ranged_descriptor_init(
    nv14_level *level,
    const nv14_object_descriptor *descriptor,
    nv14_error *error_out
)
{
    nv14_object_runtime runtime;
    nv14_native_kind kind;
    size_t object_index;
    nv14_status status;
    int object_type;
    int cell_i;
    int cell_j;
    double x;
    double y;

    if (level == NULL || descriptor == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    object_type = descriptor->object_type;
    if (object_type != NV14_OBJ_TURRET && object_type != NV14_OBJ_HOMING)
        return NV14_STATUS_UNSUPPORTED_OBJECTS;
    if (!level->simulate_enemies) return NV14_STATUS_OK;
    if (descriptor->parameter_count != 2 ||
        !isfinite(descriptor->parameters[0]) ||
        !isfinite(descriptor->parameters[1])) {
        nv14_ranged_set_error(
            error_out,
            NV14_STATUS_INVALID_LEVEL,
            object_type,
            "ranged object requires two finite coordinates"
        );
        return NV14_STATUS_INVALID_LEVEL;
    }
    x = descriptor->parameters[0];
    y = descriptor->parameters[1];
    if (!nv14_internal_floor_index(x, NV14_TILE_W, &cell_i) ||
        !nv14_internal_floor_index(y, NV14_TILE_H, &cell_j)) {
        nv14_ranged_set_error(
            error_out,
            NV14_STATUS_OUT_OF_BOUNDS,
            object_type,
            "ranged object position is outside native cell coordinates"
        );
        return NV14_STATUS_OUT_OF_BOUNDS;
    }

    memset(&runtime, 0, sizeof(runtime));
    if (object_type == NV14_OBJ_TURRET) {
        kind = NV14_NATIVE_TURRET;
        runtime.f64[NV14_TURRET_AIM_X] = x;
        runtime.f64[NV14_TURRET_AIM_Y] = y;
        runtime.f64[NV14_TURRET_AIM_SPEED] = NV14_TURRET_FAR_AIM_SPEED;
        runtime.i64[NV14_RANGED_MODE] = NV14_RANGED_TURRET_WAITING;
    } else {
        kind = NV14_NATIVE_HOMING;
        runtime.f64[NV14_HOMING_POS_X] = x;
        runtime.f64[NV14_HOMING_POS_Y] = y;
        runtime.f64[NV14_HOMING_DIR_X] = 7.0;
        runtime.f64[NV14_HOMING_DIR_Y] = 6.0;
        runtime.f64[NV14_HOMING_VIEW_X] = 4.0;
        runtime.f64[NV14_HOMING_VIEW_Y] = 56.0;
        runtime.f64[NV14_HOMING_CURRENT_ACCEL] = NV14_HOMING_START_ACCEL;
        runtime.i64[NV14_RANGED_MODE] = NV14_RANGED_HOMING_IDLE;
        runtime.i64[NV14_RANGED_CELL_I] = cell_i;
        runtime.i64[NV14_RANGED_CELL_J] = cell_j;
    }

    status = nv14_internal_level_append_object(
        level,
        kind,
        0,
        descriptor->load_index,
        0,
        x,
        y,
        0.0,
        0.0,
        0.0,
        &runtime,
        &object_index
    );
    if (status != NV14_STATUS_OK) {
        nv14_ranged_set_error(
            error_out,
            status,
            object_type,
            "cannot append ranged native object"
        );
        return status;
    }
    status = nv14_internal_level_start_think(level, object_index);
    if (status != NV14_STATUS_OK)
        nv14_ranged_set_error(
            error_out,
            status,
            object_type,
            "cannot start ranged object thinker"
        );
    return status;
}

static nv14_status nv14_turret_line_of_sight(
    nv14_state *state,
    size_t object_index,
    int *detected_out
)
{
    const nv14_native_object *object =
        &state->level->native_objects[object_index];
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    nv14_vec2 p0;
    nv14_ray_query_result query;
    nv14_status status;

    p0.x = object->x;
    p0.y = object->y;
    status = nv14_rays_query_circle(
        state->level,
        state,
        p0,
        state->player.pos,
        state->player.pos,
        state->player.r,
        &query
    );
    if (status != NV14_STATUS_OK) return status;
    runtime->f64[NV14_TURRET_VIEW_X] = query.point.x;
    runtime->f64[NV14_TURRET_VIEW_Y] = query.point.y;
    *detected_out = query.object_hit;
    return NV14_STATUS_OK;
}

static nv14_status nv14_turret_fire(
    nv14_state *state,
    size_t object_index
)
{
    const nv14_native_object *object =
        &state->level->native_objects[object_index];
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    nv14_vec2 p0;
    nv14_vec2 aim;
    nv14_ray_query_result query;
    nv14_status status;

    p0.x = object->x;
    p0.y = object->y;
    aim.x = runtime->f64[NV14_TURRET_AIM_X];
    aim.y = runtime->f64[NV14_TURRET_AIM_Y];
    status = nv14_rays_query_circle(
        state->level,
        state,
        p0,
        aim,
        state->player.pos,
        state->player.r,
        &query
    );
    if (status != NV14_STATUS_OK) return status;
    runtime->f64[NV14_TURRET_TARGET_X] = query.point.x;
    runtime->f64[NV14_TURRET_TARGET_Y] = query.point.y;
    if (query.object_hit) state->player.dead = 1;
    return NV14_STATUS_OK;
}

static nv14_status nv14_turret_update_targeting(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    double predicted_x;
    double predicted_y;
    double error_x;
    double error_y;
    double aim_speed;
    double distance_sq;

    predicted_x = 2.0 * state->player.pos.x - state->player.oldpos.x;
    predicted_y = 2.0 * state->player.pos.y - state->player.oldpos.y;
    error_x = runtime->f64[NV14_TURRET_AIM_X] - predicted_x;
    error_y = runtime->f64[NV14_TURRET_AIM_Y] - predicted_y;
    aim_speed = runtime->f64[NV14_TURRET_AIM_SPEED];
    runtime->f64[NV14_TURRET_AIM_X] -= aim_speed * error_x;
    runtime->f64[NV14_TURRET_AIM_Y] -= aim_speed * error_y;
    distance_sq = error_x * error_x + error_y * error_y;

    if (NV14_TURRET_OUTER_THRESHOLD < distance_sq) {
        runtime->f64[NV14_TURRET_AIM_SPEED] = NV14_TURRET_FAR_AIM_SPEED;
        return NV14_STATUS_OK;
    }
    if (distance_sq < NV14_TURRET_INNER_THRESHOLD) {
        runtime->f64[NV14_TURRET_SHOT_TIMER] -=
            (double)(2u + state->frame % UINT64_C(4));
    } else if (distance_sq < NV14_TURRET_MID_THRESHOLD) {
        runtime->f64[NV14_TURRET_AIM_SPEED] = NV14_TURRET_CLOSE_AIM_SPEED;
        runtime->f64[NV14_TURRET_SHOT_TIMER] -=
            (double)(1u + state->frame % UINT64_C(2));
    } else {
        runtime->f64[NV14_TURRET_AIM_SPEED] = NV14_TURRET_MID_AIM_SPEED;
        runtime->f64[NV14_TURRET_SHOT_TIMER] -= 0.5;
    }
    if (runtime->f64[NV14_TURRET_SHOT_TIMER] < 0.0) {
        runtime->f64[NV14_TURRET_SHOT_TIMER] = NV14_TURRET_SHOT_RATE;
        runtime->i64[NV14_RANGED_MODE] = NV14_RANGED_TURRET_PREFIRE;
        runtime->i64[NV14_RANGED_FIRE_DELAY_TIMER] = 0;
        nv14_internal_end_think(state, object_index);
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_turret_update(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    int64_t mode = runtime->i64[NV14_RANGED_MODE];
    int detected;
    nv14_status status;

    if (mode == NV14_RANGED_TURRET_WAITING)
        return NV14_STATUS_OK;
    if (mode == NV14_RANGED_TURRET_TARGETING)
        return nv14_turret_update_targeting(state, object_index);
    if (mode == NV14_RANGED_TURRET_PREFIRE) {
        ++runtime->i64[NV14_RANGED_FIRE_DELAY_TIMER];
        if (NV14_RANGED_PREFIRE_DELAY <=
            runtime->i64[NV14_RANGED_FIRE_DELAY_TIMER]) {
            status = nv14_turret_line_of_sight(state, object_index, &detected);
            if (status != NV14_STATUS_OK) return status;
            if (detected) {
                status = nv14_turret_fire(state, object_index);
                if (status != NV14_STATUS_OK) return status;
            }
            status = nv14_internal_start_think(state, object_index);
            if (status != NV14_STATUS_OK) return status;
            runtime->i64[NV14_RANGED_MODE] = NV14_RANGED_TURRET_POSTFIRE;
            runtime->i64[NV14_RANGED_FIRE_DELAY_TIMER] = 0;
        }
        return NV14_STATUS_OK;
    }

    ++runtime->i64[NV14_RANGED_FIRE_DELAY_TIMER];
    if (NV14_RANGED_POSTFIRE_DELAY <=
        runtime->i64[NV14_RANGED_FIRE_DELAY_TIMER]) {
        status = nv14_turret_line_of_sight(state, object_index, &detected);
        if (status != NV14_STATUS_OK) return status;
        if (!detected) {
            runtime->i64[NV14_RANGED_MODE] = NV14_RANGED_TURRET_WAITING;
            nv14_internal_end_update(state, object_index);
        } else {
            runtime->i64[NV14_RANGED_MODE] = NV14_RANGED_TURRET_TARGETING;
            runtime->f64[NV14_TURRET_SHOT_TIMER] = NV14_TURRET_SHOT_RATE;
        }
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_turret_think(
    nv14_state *state,
    size_t object_index
)
{
    const nv14_native_object *object =
        &state->level->native_objects[object_index];
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    int64_t mode = runtime->i64[NV14_RANGED_MODE];
    int detected;
    nv14_status status =
        nv14_turret_line_of_sight(state, object_index, &detected);
    if (status != NV14_STATUS_OK) return status;

    if (mode == NV14_RANGED_TURRET_WAITING) {
        if (detected) {
            runtime->i64[NV14_RANGED_MODE] = NV14_RANGED_TURRET_TARGETING;
            runtime->f64[NV14_TURRET_AIM_SPEED] =
                NV14_TURRET_FAR_AIM_SPEED;
            runtime->f64[NV14_TURRET_AIM_X] = object->x;
            runtime->f64[NV14_TURRET_AIM_Y] = object->y;
            runtime->f64[NV14_TURRET_SHOT_TIMER] = NV14_TURRET_SHOT_RATE;
            return nv14_internal_start_update(state, object_index);
        }
    } else if ((mode == NV14_RANGED_TURRET_TARGETING ||
                mode == NV14_RANGED_TURRET_POSTFIRE) && !detected) {
        runtime->i64[NV14_RANGED_MODE] = NV14_RANGED_TURRET_WAITING;
        nv14_internal_end_update(state, object_index);
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_homing_explode(
    nv14_state *state,
    size_t object_index,
    int restart_thinker
)
{
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    nv14_internal_end_update(state, object_index);
    nv14_internal_grid_remove(state, object_index);
    runtime->i64[NV14_RANGED_MODE] = NV14_RANGED_HOMING_IDLE;
    if (restart_thinker)
        return nv14_internal_start_think(state, object_index);
    return NV14_STATUS_OK;
}

static nv14_status nv14_homing_fire(
    nv14_state *state,
    size_t object_index
)
{
    const nv14_native_object *object =
        &state->level->native_objects[object_index];
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    double dx;
    double dy;
    double length;
    int cell_i;
    int cell_j;
    nv14_status status;

    runtime->f64[NV14_HOMING_CURRENT_ACCEL] = NV14_HOMING_START_ACCEL;
    runtime->f64[NV14_HOMING_SPEED] = 0.0;
    runtime->f64[NV14_HOMING_POS_X] = object->x;
    runtime->f64[NV14_HOMING_POS_Y] = object->y;
    if (!nv14_internal_floor_index(object->x, NV14_TILE_W, &cell_i) ||
        !nv14_internal_floor_index(object->y, NV14_TILE_H, &cell_j))
        return NV14_STATUS_OUT_OF_BOUNDS;
    runtime->i64[NV14_RANGED_CELL_I] = cell_i;
    runtime->i64[NV14_RANGED_CELL_J] = cell_j;
    status = nv14_internal_grid_move(state, object_index, cell_i, cell_j);
    if (status != NV14_STATUS_OK) return status;

    dx = state->player.pos.x - object->x;
    dy = state->player.pos.y - object->y;
    length = sqrt(dx * dx + dy * dy);
    if (length != 0.0) {
        runtime->f64[NV14_HOMING_DIR_X] = dx / length;
        runtime->f64[NV14_HOMING_DIR_Y] = dy / length;
    }
    runtime->i64[NV14_RANGED_MODE] = NV14_RANGED_HOMING_ACTIVE;
    return NV14_STATUS_OK;
}

static nv14_status nv14_homing_update_active(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    const nv14_tile *cell;
    const nv14_tile *old_cell;
    double speed;
    double predicted_x;
    double predicted_y;
    double rocket_next_x;
    double rocket_next_y;
    double dx;
    double dy;
    double target_len;
    double cross;
    double steer_x;
    double steer_y;
    double direction_len;
    int old_i;
    int old_j;
    int new_i;
    int new_j;
    int side = -1;
    int solid;
    nv14_status status;

    speed = runtime->f64[NV14_HOMING_SPEED];
    if (speed < NV14_HOMING_MAX_SPEED) {
        runtime->f64[NV14_HOMING_CURRENT_ACCEL] *= NV14_HOMING_ACCEL_RATE;
        runtime->f64[NV14_HOMING_SPEED] +=
            runtime->f64[NV14_HOMING_CURRENT_ACCEL];
    } else {
        runtime->f64[NV14_HOMING_SPEED] = NV14_HOMING_MAX_SPEED;
    }
    speed = runtime->f64[NV14_HOMING_SPEED];
    runtime->f64[NV14_HOMING_POS_X] +=
        speed * runtime->f64[NV14_HOMING_DIR_X];
    runtime->f64[NV14_HOMING_POS_Y] +=
        speed * runtime->f64[NV14_HOMING_DIR_Y];

    status = nv14_ranged_query_point(
        state->level,
        runtime->f64[NV14_HOMING_POS_X],
        runtime->f64[NV14_HOMING_POS_Y],
        &cell,
        &solid
    );
    if (status != NV14_STATUS_OK) return status;
    if (solid) return nv14_homing_explode(state, object_index, 1);

    old_i = (int)runtime->i64[NV14_RANGED_CELL_I];
    old_j = (int)runtime->i64[NV14_RANGED_CELL_J];
    new_i = cell->i;
    new_j = cell->j;
    if (new_i != old_i || new_j != old_j) {
        status = nv14_internal_grid_move(state, object_index, new_i, new_j);
        if (status != NV14_STATUS_OK) return status;
        runtime->i64[NV14_RANGED_CELL_I] = new_i;
        runtime->i64[NV14_RANGED_CELL_J] = new_j;
        old_cell = nv14_ranged_tile_at(state->level, old_i, old_j);
        if (old_cell == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
        if (new_i == old_i + 1 && new_j == old_j)
            side = NV14_EDGE_R;
        else if (new_i == old_i - 1 && new_j == old_j)
            side = NV14_EDGE_L;
        else if (new_i == old_i && new_j == old_j - 1)
            side = NV14_EDGE_U;
        else if (new_i == old_i && new_j == old_j + 1)
            side = NV14_EDGE_D;
        if (side >= 0 &&
            nv14_ranged_edge_value(state, old_cell, side) == NV14_EID_SOLID)
            return nv14_homing_explode(state, object_index, 1);
    }

    predicted_x = 2.0 * state->player.pos.x - state->player.oldpos.x;
    predicted_y = 2.0 * state->player.pos.y - state->player.oldpos.y;
    rocket_next_x = runtime->f64[NV14_HOMING_POS_X] +
        speed * runtime->f64[NV14_HOMING_DIR_X];
    rocket_next_y = runtime->f64[NV14_HOMING_POS_Y] +
        speed * runtime->f64[NV14_HOMING_DIR_Y];
    dx = predicted_x - rocket_next_x;
    dy = predicted_y - rocket_next_y;
    target_len = sqrt(dx * dx + dy * dy);
    if (target_len == 0.0) return NV14_STATUS_OK;
    dx /= target_len;
    dy /= target_len;
    cross = (-runtime->f64[NV14_HOMING_DIR_Y]) * dx +
        runtime->f64[NV14_HOMING_DIR_X] * dy;
    steer_x = cross * (-runtime->f64[NV14_HOMING_DIR_Y]);
    steer_y = cross * runtime->f64[NV14_HOMING_DIR_X];
    runtime->f64[NV14_HOMING_DIR_X] += steer_x * NV14_HOMING_TURN_RATE;
    runtime->f64[NV14_HOMING_DIR_Y] += steer_y * NV14_HOMING_TURN_RATE;
    direction_len = sqrt(
        runtime->f64[NV14_HOMING_DIR_X] *
            runtime->f64[NV14_HOMING_DIR_X] +
        runtime->f64[NV14_HOMING_DIR_Y] *
            runtime->f64[NV14_HOMING_DIR_Y]
    );
    if (direction_len != 0.0) {
        runtime->f64[NV14_HOMING_DIR_X] /= direction_len;
        runtime->f64[NV14_HOMING_DIR_Y] /= direction_len;
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_homing_update(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    int64_t mode = runtime->i64[NV14_RANGED_MODE];
    if (mode == NV14_RANGED_HOMING_IDLE)
        return NV14_STATUS_OK;
    if (mode == NV14_RANGED_HOMING_PREFIRE) {
        ++runtime->i64[NV14_RANGED_FIRE_DELAY_TIMER];
        if (NV14_RANGED_PREFIRE_DELAY <=
            runtime->i64[NV14_RANGED_FIRE_DELAY_TIMER])
            return nv14_homing_fire(state, object_index);
        return NV14_STATUS_OK;
    }
    return nv14_homing_update_active(state, object_index);
}

static nv14_status nv14_homing_think(
    nv14_state *state,
    size_t object_index
)
{
    const nv14_native_object *object =
        &state->level->native_objects[object_index];
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    nv14_vec2 base;
    nv14_ray_query_result query;
    nv14_status status;

    base.x = object->x;
    base.y = object->y;
    status = nv14_rays_query_circle(
        state->level,
        state,
        base,
        state->player.pos,
        state->player.pos,
        state->player.r,
        &query
    );
    if (status != NV14_STATUS_OK) return status;
    runtime->f64[NV14_HOMING_VIEW_X] = query.point.x;
    runtime->f64[NV14_HOMING_VIEW_Y] = query.point.y;
    if (query.object_hit) {
        runtime->i64[NV14_RANGED_MODE] = NV14_RANGED_HOMING_PREFIRE;
        runtime->i64[NV14_RANGED_FIRE_DELAY_TIMER] = 0;
        nv14_internal_end_think(state, object_index);
        return nv14_internal_start_update(state, object_index);
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_ranged_update_object(
    nv14_state *state,
    size_t object_index
)
{
    int object_type;
    if (state == NULL || object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    object_type = nv14_ranged_object_type(state->level, object_index);
    if (object_type == NV14_OBJ_TURRET)
        return nv14_turret_update(state, object_index);
    if (object_type == NV14_OBJ_HOMING)
        return nv14_homing_update(state, object_index);
    return NV14_STATUS_UNSUPPORTED_OBJECTS;
}

static nv14_status nv14_ranged_think_object(
    nv14_state *state,
    size_t object_index
)
{
    int object_type;
    if (state == NULL || object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    object_type = nv14_ranged_object_type(state->level, object_index);
    if (object_type == NV14_OBJ_TURRET)
        return nv14_turret_think(state, object_index);
    if (object_type == NV14_OBJ_HOMING)
        return nv14_homing_think(state, object_index);
    return NV14_STATUS_UNSUPPORTED_OBJECTS;
}

static nv14_status nv14_ranged_collide_player(
    nv14_state *state,
    size_t object_index,
    int *handled_out,
    int *removed_current_out
)
{
    nv14_object_runtime *runtime;
    double dx;
    double dy;
    double distance;
    int object_type;
    nv14_status status;

    if (handled_out != NULL) *handled_out = 0;
    if (removed_current_out != NULL) *removed_current_out = 0;
    if (state == NULL || object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    object_type = nv14_ranged_object_type(state->level, object_index);
    if (object_type == NV14_OBJ_TURRET) {
        if (handled_out != NULL) *handled_out = 1;
        return NV14_STATUS_OK;
    }
    if (object_type != NV14_OBJ_HOMING)
        return NV14_STATUS_UNSUPPORTED_OBJECTS;
    if (handled_out != NULL) *handled_out = 1;
    runtime = nv14_internal_object_runtime(state, object_index);
    if (runtime->i64[NV14_RANGED_MODE] != NV14_RANGED_HOMING_ACTIVE)
        return NV14_STATUS_OK;
    dx = state->player.pos.x - runtime->f64[NV14_HOMING_POS_X];
    dy = state->player.pos.y - runtime->f64[NV14_HOMING_POS_Y];
    distance = sqrt(dx * dx + dy * dy);
    if (distance < state->player.r) {
        state->player.dead = 1;
        status = nv14_homing_explode(state, object_index, 0);
        if (status != NV14_STATUS_OK) return status;
        if (removed_current_out != NULL) *removed_current_out = 1;
    }
    return NV14_STATUS_OK;
}

static const nv14_internal_object_module nv14_ranged_module = {
    NV14_INTERNAL_OBJECT_MODULE_ABI_VERSION,
    sizeof(nv14_internal_object_module),
    (UINT32_C(1) << NV14_OBJ_TURRET) |
        (UINT32_C(1) << NV14_OBJ_HOMING),
    0,
    "ranged-enemies",
    NULL,
    nv14_ranged_descriptor_init,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    nv14_ranged_update_object,
    nv14_ranged_think_object,
    nv14_ranged_collide_player,
    NULL,
    NULL,
    NULL
};

const nv14_internal_object_module *nv14_objects_ranged_module(void)
{
    return &nv14_ranged_module;
}

nv14_status nv14_objects_ranged_register(void)
{
    return nv14_internal_register_object_module(&nv14_ranged_module);
}

nv14_status nv14_objects_ranged_snapshot(
    const nv14_state *state,
    uint32_t load_index,
    nv14_ranged_snapshot *out
)
{
    size_t object_index;
    const nv14_native_object *object = NULL;
    const nv14_object_runtime *runtime;
    int object_type;

    if (state == NULL || out == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    for (object_index = 0;
         object_index < state->level->native_object_count;
         ++object_index) {
        const nv14_native_object *candidate =
            &state->level->native_objects[object_index];
        if (candidate->load_index == load_index &&
            (candidate->kind == NV14_NATIVE_TURRET ||
             candidate->kind == NV14_NATIVE_HOMING)) {
            object = candidate;
            break;
        }
    }
    if (object == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
    object_type = nv14_ranged_object_type(state->level, object_index);
    runtime = nv14_internal_object_runtime_const(state, object_index);
    memset(out, 0, sizeof(*out));
    out->object_type = object_type;
    out->load_index = object->load_index;
    out->mode = (int)runtime->i64[NV14_RANGED_MODE];
    out->fire_delay_timer = runtime->i64[NV14_RANGED_FIRE_DELAY_TIMER];
    out->base_position.x = object->x;
    out->base_position.y = object->y;
    out->updating = state->update_active[object_index] != 0;
    out->thinking = state->thinker_active[object_index] != 0;
    out->grid_active = state->object_cell_slot[object_index] >= 0;

    if (object_type == NV14_OBJ_TURRET) {
        out->position = out->base_position;
        out->view.x = runtime->f64[NV14_TURRET_VIEW_X];
        out->view.y = runtime->f64[NV14_TURRET_VIEW_Y];
        out->target.x = runtime->f64[NV14_TURRET_TARGET_X];
        out->target.y = runtime->f64[NV14_TURRET_TARGET_Y];
        out->aim.x = runtime->f64[NV14_TURRET_AIM_X];
        out->aim.y = runtime->f64[NV14_TURRET_AIM_Y];
        out->aim_speed = runtime->f64[NV14_TURRET_AIM_SPEED];
        out->shot_timer = runtime->f64[NV14_TURRET_SHOT_TIMER];
    } else {
        out->position.x = runtime->f64[NV14_HOMING_POS_X];
        out->position.y = runtime->f64[NV14_HOMING_POS_Y];
        out->direction.x = runtime->f64[NV14_HOMING_DIR_X];
        out->direction.y = runtime->f64[NV14_HOMING_DIR_Y];
        out->view.x = runtime->f64[NV14_HOMING_VIEW_X];
        out->view.y = runtime->f64[NV14_HOMING_VIEW_Y];
        out->speed = runtime->f64[NV14_HOMING_SPEED];
        out->current_acceleration =
            runtime->f64[NV14_HOMING_CURRENT_ACCEL];
        out->cell_i = (int32_t)runtime->i64[NV14_RANGED_CELL_I];
        out->cell_j = (int32_t)runtime->i64[NV14_RANGED_CELL_J];
    }
    return NV14_STATUS_OK;
}

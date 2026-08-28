/*
 * Source-order ports of n v1.4's laser and chaingun DroneObject weapons.
 * Navigation and object ownership are supplied by nv14_objects_drones.c.
 * Compile with the core's strict binary64 flags; arithmetic ordering here is
 * gameplay state and must not be contracted or reassociated.
 */

#include "nv14_drone_weapons.h"

#include "nv14_rays.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define NV14_DRONE_LASER_PREFIRE_DELAY INT64_C(30)
#define NV14_DRONE_LASER_RATE INT64_C(80)
#define NV14_DRONE_LASER_POSTFIRE_DELAY INT64_C(40)

#define NV14_DRONE_CHAIN_PREFIRE_DELAY INT64_C(35)
#define NV14_DRONE_CHAIN_RATE INT64_C(6)
#define NV14_DRONE_CHAIN_POSTFIRE_DELAY INT64_C(60)

static int nv14_drone_weapon_kind(
    const nv14_level *level,
    size_t object_index
)
{
    const nv14_native_object *object;
    if (level == NULL || object_index >= level->native_object_count)
        return -1;
    object = &level->native_objects[object_index];
    if (object->kind == NV14_NATIVE_DRONE_LASER)
        return NV14_DRONE_WEAPON_LASER;
    if (object->kind == NV14_NATIVE_DRONE_CHAINGUN)
        return NV14_DRONE_WEAPON_CHAINGUN;
    return -1;
}

static nv14_status nv14_drone_laser_init(
    nv14_level *level,
    const nv14_object_descriptor *descriptor,
    nv14_object_runtime *runtime,
    nv14_error *error_out
)
{
    (void)level;
    (void)descriptor;
    (void)error_out;
    if (runtime == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    runtime->i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_MOVING;
    runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER] = 0;
    runtime->i64[NV14_DRONE_LASER_TIMER] = 0;
    return NV14_STATUS_OK;
}

static nv14_status nv14_drone_chain_init(
    nv14_level *level,
    const nv14_object_descriptor *descriptor,
    nv14_object_runtime *runtime,
    nv14_error *error_out
)
{
    (void)level;
    (void)descriptor;
    (void)error_out;
    if (runtime == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    runtime->f64[NV14_DRONE_CHAIN_SPREAD] = 0.3;
    runtime->i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_MOVING;
    runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER] = 0;
    runtime->i64[NV14_DRONE_CHAIN_TIMER] = 0;
    runtime->i64[NV14_DRONE_CHAIN_MAX_COUNT] = 8;
    runtime->i64[NV14_DRONE_CHAIN_CURRENT] = 0;
    return NV14_STATUS_OK;
}

static nv14_status nv14_drone_target_query(
    nv14_state *state,
    size_t object_index,
    nv14_ray_query_result *query_out
)
{
    nv14_object_runtime *runtime;
    nv14_vec2 position;
    if (state == NULL || query_out == NULL ||
        object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    runtime = nv14_internal_object_runtime(state, object_index);
    position.x = runtime->f64[NV14_DRONE_POS_X];
    position.y = runtime->f64[NV14_DRONE_POS_Y];
    return nv14_rays_query_circle(
        state->level,
        state,
        position,
        state->player.pos,
        state->player.pos,
        state->player.r,
        query_out
    );
}

static nv14_status nv14_drone_laser_think(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime;
    nv14_ray_query_result query;
    nv14_ray_hit tile;
    nv14_vec2 position;
    double dx;
    double dy;
    nv14_status status;

    if (state == NULL || object_index >= state->level->native_object_count ||
        nv14_drone_weapon_kind(state->level, object_index) !=
            NV14_DRONE_WEAPON_LASER)
        return NV14_STATUS_INVALID_ARGUMENT;
    runtime = nv14_internal_object_runtime(state, object_index);
    status = nv14_drone_target_query(state, object_index, &query);
    if (status != NV14_STATUS_OK) return status;
    runtime->f64[NV14_DRONE_LASER_VIEW_X] = query.point.x;
    runtime->f64[NV14_DRONE_LASER_VIEW_Y] = query.point.y;
    if (!query.object_hit) return NV14_STATUS_OK;

    /* StartFiring_Laser: leave the thinker ring before locking the beam. */
    nv14_internal_end_think(state, object_index);
    runtime->i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_PREFIRE;
    runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER] = 0;
    position.x = runtime->f64[NV14_DRONE_POS_X];
    position.y = runtime->f64[NV14_DRONE_POS_Y];
    status = nv14_rays_collide_tiles(
        state->level,
        state,
        position,
        query.point,
        0,
        0.0,
        &tile
    );
    if (status != NV14_STATUS_OK) return status;
    if (tile.hit) {
        runtime->f64[NV14_DRONE_LASER_TARGET_X] = tile.point.x;
        runtime->f64[NV14_DRONE_LASER_TARGET_Y] = tile.point.y;
    } else {
        /* Solid borders make this unreachable for ordinary levels. */
        runtime->f64[NV14_DRONE_LASER_TARGET_X] = query.point.x;
        runtime->f64[NV14_DRONE_LASER_TARGET_Y] = query.point.y;
    }
    dx = runtime->f64[NV14_DRONE_LASER_TARGET_X] -
        runtime->f64[NV14_DRONE_POS_X];
    dy = runtime->f64[NV14_DRONE_LASER_TARGET_Y] -
        runtime->f64[NV14_DRONE_POS_Y];
    runtime->f64[NV14_DRONE_LASER_VECTOR_X] = dx;
    runtime->f64[NV14_DRONE_LASER_VECTOR_Y] = dy;
    runtime->f64[NV14_DRONE_LASER_LENGTH] = sqrt(dx * dx + dy * dy);
    if (runtime->f64[NV14_DRONE_LASER_LENGTH] == 0.0) {
        runtime->i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_POSTFIRE;
        runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER] = 0;
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_drone_chain_think(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime;
    nv14_ray_query_result query;
    nv14_status status;
    if (state == NULL || object_index >= state->level->native_object_count ||
        nv14_drone_weapon_kind(state->level, object_index) !=
            NV14_DRONE_WEAPON_CHAINGUN)
        return NV14_STATUS_INVALID_ARGUMENT;
    runtime = nv14_internal_object_runtime(state, object_index);
    status = nv14_drone_target_query(state, object_index, &query);
    if (status != NV14_STATUS_OK) return status;
    runtime->f64[NV14_DRONE_CHAIN_VIEW_X] = query.point.x;
    runtime->f64[NV14_DRONE_CHAIN_VIEW_Y] = query.point.y;
    if (query.object_hit) {
        /* StartFiring_Chaingun ends Think and changes only prefire state. */
        nv14_internal_end_think(state, object_index);
        runtime->i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_PREFIRE;
        runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER] = 0;
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_drone_laser_update(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime;
    int64_t mode;
    double projection;
    double closest_x;
    double closest_y;
    double dx;
    double dy;
    if (state == NULL || object_index >= state->level->native_object_count ||
        nv14_drone_weapon_kind(state->level, object_index) !=
            NV14_DRONE_WEAPON_LASER)
        return NV14_STATUS_INVALID_ARGUMENT;
    runtime = nv14_internal_object_runtime(state, object_index);
    mode = runtime->i64[NV14_DRONE_MODE];

    if (mode == NV14_DRONE_MODE_PREFIRE) {
        ++runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER];
        if (NV14_DRONE_LASER_PREFIRE_DELAY <=
            runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER]) {
            runtime->i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_FIRING;
            runtime->f64[NV14_DRONE_LASER_LENGTH] *=
                runtime->f64[NV14_DRONE_LASER_LENGTH];
            runtime->i64[NV14_DRONE_LASER_TIMER] = 0;
        }
        return NV14_STATUS_OK;
    }
    if (mode == NV14_DRONE_MODE_FIRING) {
        dx = state->player.pos.x - runtime->f64[NV14_DRONE_POS_X];
        dy = state->player.pos.y - runtime->f64[NV14_DRONE_POS_Y];
        projection = dx * runtime->f64[NV14_DRONE_LASER_VECTOR_X] +
            dy * runtime->f64[NV14_DRONE_LASER_VECTOR_Y];
        projection /= runtime->f64[NV14_DRONE_LASER_LENGTH];
        if (projection < 0.0) {
            closest_x = runtime->f64[NV14_DRONE_POS_X];
            closest_y = runtime->f64[NV14_DRONE_POS_Y];
        } else if (projection < 1.0) {
            closest_x = runtime->f64[NV14_DRONE_POS_X] +
                projection * runtime->f64[NV14_DRONE_LASER_VECTOR_X];
            closest_y = runtime->f64[NV14_DRONE_POS_Y] +
                projection * runtime->f64[NV14_DRONE_LASER_VECTOR_Y];
        } else {
            closest_x = runtime->f64[NV14_DRONE_LASER_TARGET_X];
            closest_y = runtime->f64[NV14_DRONE_LASER_TARGET_Y];
        }
        dx = closest_x - state->player.pos.x;
        dy = closest_y - state->player.pos.y;
        if (sqrt(dx * dx + dy * dy) < state->player.r) {
            /* StopFiring_Laser precedes KillPlayer. */
            runtime->i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_POSTFIRE;
            runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER] = 0;
            state->player.dead = 1;
            return NV14_STATUS_OK;
        }
        ++runtime->i64[NV14_DRONE_LASER_TIMER];
        if (NV14_DRONE_LASER_RATE <=
            runtime->i64[NV14_DRONE_LASER_TIMER]) {
            runtime->i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_POSTFIRE;
            runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER] = 0;
        }
        return NV14_STATUS_OK;
    }
    if (mode == NV14_DRONE_MODE_POSTFIRE) {
        ++runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER];
        if (NV14_DRONE_LASER_POSTFIRE_DELAY <=
            runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER])
            return nv14_drones_start_moving(state, object_index);
        return NV14_STATUS_OK;
    }
    return NV14_STATUS_INVALID_ARGUMENT;
}

static void nv14_drone_chain_stop(nv14_object_runtime *runtime)
{
    runtime->i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_POSTFIRE;
    runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER] = 0;
}

static nv14_status nv14_drone_chain_fire(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    double dx;
    double dy;
    double distance;
    double player_dx;
    double player_dy;
    double side_dot;

    runtime->i64[NV14_DRONE_CHAIN_TIMER] = 0;
    runtime->i64[NV14_DRONE_CHAIN_MAX_COUNT] =
        INT64_C(4) + (int64_t)(state->frame % UINT64_C(5));
    runtime->f64[NV14_DRONE_CHAIN_SPREAD] =
        0.1 + 0.1 * (double)(UINT64_C(1) + state->frame % UINT64_C(3));
    runtime->i64[NV14_DRONE_CHAIN_CURRENT] = 0;
    runtime->i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_FIRING;

    dx = state->player.pos.x - runtime->f64[NV14_DRONE_POS_X];
    dy = state->player.pos.y - runtime->f64[NV14_DRONE_POS_Y];
    distance = sqrt(dx * dx + dy * dy);
    if (distance == 0.0) {
        nv14_drone_chain_stop(runtime);
        return NV14_STATUS_OK;
    }
    dx /= distance;
    dy /= distance;
    runtime->f64[NV14_DRONE_CHAIN_TARGET_X] = dx;
    runtime->f64[NV14_DRONE_CHAIN_TARGET_Y] = dy;
    player_dx = state->player.pos.x - state->player.oldpos.x;
    player_dy = state->player.pos.y - state->player.oldpos.y;
    side_dot = player_dx * -dy + player_dy * dx;
    if (side_dot < 0.0) {
        runtime->f64[NV14_DRONE_CHAIN_VECTOR_X] = dy;
        runtime->f64[NV14_DRONE_CHAIN_VECTOR_Y] = -dx;
    } else {
        runtime->f64[NV14_DRONE_CHAIN_VECTOR_X] = -dy;
        runtime->f64[NV14_DRONE_CHAIN_VECTOR_Y] = dx;
    }
    return NV14_STATUS_OK;
}

static nv14_status nv14_drone_chain_update_firing(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime =
        nv14_internal_object_runtime(state, object_index);
    nv14_vec2 position;
    nv14_vec2 shot_target;
    nv14_ray_query_result query;
    double spread_offset;
    double shot_dx;
    double shot_dy;
    nv14_status status;

    ++runtime->i64[NV14_DRONE_CHAIN_TIMER];
    if (runtime->i64[NV14_DRONE_CHAIN_TIMER] < NV14_DRONE_CHAIN_RATE)
        return NV14_STATUS_OK;
    runtime->i64[NV14_DRONE_CHAIN_TIMER] = 0;
    if (runtime->i64[NV14_DRONE_CHAIN_MAX_COUNT] <
        runtime->i64[NV14_DRONE_CHAIN_CURRENT]) {
        nv14_drone_chain_stop(runtime);
        return NV14_STATUS_OK;
    }

    spread_offset =
        ((double)runtime->i64[NV14_DRONE_CHAIN_CURRENT] /
         (double)runtime->i64[NV14_DRONE_CHAIN_MAX_COUNT] - 0.5) *
        runtime->f64[NV14_DRONE_CHAIN_SPREAD];
    shot_dx = runtime->f64[NV14_DRONE_CHAIN_TARGET_X] +
        spread_offset * runtime->f64[NV14_DRONE_CHAIN_VECTOR_X];
    shot_dy = runtime->f64[NV14_DRONE_CHAIN_TARGET_Y] +
        spread_offset * runtime->f64[NV14_DRONE_CHAIN_VECTOR_Y];
    position.x = runtime->f64[NV14_DRONE_POS_X];
    position.y = runtime->f64[NV14_DRONE_POS_Y];
    shot_target.x = position.x + shot_dx;
    shot_target.y = position.y + shot_dy;
    runtime->f64[NV14_DRONE_CHAIN_SHOT_X] = shot_target.x;
    runtime->f64[NV14_DRONE_CHAIN_SHOT_Y] = shot_target.y;
    status = nv14_rays_query_circle(
        state->level,
        state,
        position,
        shot_target,
        state->player.pos,
        state->player.r,
        &query
    );
    if (status != NV14_STATUS_OK) return status;
    runtime->f64[NV14_DRONE_CHAIN_VIEW_X] = query.point.x;
    runtime->f64[NV14_DRONE_CHAIN_VIEW_Y] = query.point.y;
    if (query.object_hit) {
        /* StopFiring_Chaingun runs before KillPlayer; the source still
           increments chaingunCurNum after both calls. */
        nv14_drone_chain_stop(runtime);
        state->player.dead = 1;
    }
    ++runtime->i64[NV14_DRONE_CHAIN_CURRENT];
    return NV14_STATUS_OK;
}

static nv14_status nv14_drone_chain_update(
    nv14_state *state,
    size_t object_index
)
{
    nv14_object_runtime *runtime;
    int64_t mode;
    if (state == NULL || object_index >= state->level->native_object_count ||
        nv14_drone_weapon_kind(state->level, object_index) !=
            NV14_DRONE_WEAPON_CHAINGUN)
        return NV14_STATUS_INVALID_ARGUMENT;
    runtime = nv14_internal_object_runtime(state, object_index);
    mode = runtime->i64[NV14_DRONE_MODE];
    if (mode == NV14_DRONE_MODE_PREFIRE) {
        ++runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER];
        if (NV14_DRONE_CHAIN_PREFIRE_DELAY <=
            runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER])
            return nv14_drone_chain_fire(state, object_index);
        return NV14_STATUS_OK;
    }
    if (mode == NV14_DRONE_MODE_FIRING)
        return nv14_drone_chain_update_firing(state, object_index);
    if (mode == NV14_DRONE_MODE_POSTFIRE) {
        ++runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER];
        if (NV14_DRONE_CHAIN_POSTFIRE_DELAY <=
            runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER])
            return nv14_drones_start_moving(state, object_index);
        return NV14_STATUS_OK;
    }
    return NV14_STATUS_INVALID_ARGUMENT;
}

static const nv14_drone_weapon_hooks NV14_LASER_HOOKS = {
    NV14_DRONE_WEAPON_HOOKS_ABI_VERSION,
    sizeof(nv14_drone_weapon_hooks),
    NV14_DRONE_WEAPON_LASER,
    0,
    "laser-drone",
    nv14_drone_laser_init,
    nv14_drone_laser_update,
    nv14_drone_laser_think
};

static const nv14_drone_weapon_hooks NV14_CHAIN_HOOKS = {
    NV14_DRONE_WEAPON_HOOKS_ABI_VERSION,
    sizeof(nv14_drone_weapon_hooks),
    NV14_DRONE_WEAPON_CHAINGUN,
    0,
    "chaingun-drone",
    nv14_drone_chain_init,
    nv14_drone_chain_update,
    nv14_drone_chain_think
};

const nv14_drone_weapon_hooks *nv14_drone_laser_hooks(void)
{
    return &NV14_LASER_HOOKS;
}

const nv14_drone_weapon_hooks *nv14_drone_chaingun_hooks(void)
{
    return &NV14_CHAIN_HOOKS;
}

nv14_status nv14_drone_weapons_register(void)
{
    nv14_status status = nv14_drones_register_weapon_hooks(&NV14_LASER_HOOKS);
    if (status != NV14_STATUS_OK) return status;
    return nv14_drones_register_weapon_hooks(&NV14_CHAIN_HOOKS);
}

nv14_status nv14_drone_weapons_snapshot(
    const nv14_state *state,
    uint32_t load_index,
    nv14_drone_weapon_snapshot *out
)
{
    size_t object_index;
    const nv14_native_object *object = NULL;
    const nv14_object_runtime *runtime;
    int weapon_type;
    if (state == NULL || out == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    for (object_index = 0;
         object_index < state->level->native_object_count;
         ++object_index) {
        const nv14_native_object *candidate =
            &state->level->native_objects[object_index];
        if (candidate->load_index == load_index &&
            (candidate->kind == NV14_NATIVE_DRONE_LASER ||
             candidate->kind == NV14_NATIVE_DRONE_CHAINGUN)) {
            object = candidate;
            break;
        }
    }
    if (object == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
    weapon_type = nv14_drone_weapon_kind(state->level, object_index);
    runtime = nv14_internal_object_runtime_const(state, object_index);
    memset(out, 0, sizeof(*out));
    out->load_index = object->load_index;
    out->weapon_type = weapon_type;
    out->mode = (int)runtime->i64[NV14_DRONE_MODE];
    out->fire_delay_timer = runtime->i64[NV14_DRONE_FIRE_DELAY_TIMER];
    out->weapon_timer = runtime->i64[NV14_DRONE_WEAPON_TIMER];
    out->view.x = runtime->f64[NV14_DRONE_AUX0];
    out->view.y = runtime->f64[NV14_DRONE_AUX1];
    out->target.x = runtime->f64[NV14_DRONE_AUX2];
    out->target.y = runtime->f64[NV14_DRONE_AUX3];
    out->vector.x = runtime->f64[NV14_DRONE_AUX4];
    out->vector.y = runtime->f64[NV14_DRONE_AUX5];
    if (weapon_type == NV14_DRONE_WEAPON_LASER) {
        out->laser_length = runtime->f64[NV14_DRONE_LASER_LENGTH];
    } else {
        out->shot_target.x = runtime->f64[NV14_DRONE_CHAIN_SHOT_X];
        out->shot_target.y = runtime->f64[NV14_DRONE_CHAIN_SHOT_Y];
        out->spread = runtime->f64[NV14_DRONE_CHAIN_SPREAD];
        out->maximum_shot_index =
            runtime->i64[NV14_DRONE_CHAIN_MAX_COUNT];
        out->current_shot_index = runtime->i64[NV14_DRONE_CHAIN_CURRENT];
    }
    return NV14_STATUS_OK;
}

/* Focused native regressions using the same C sources as the extension.
 * Internal runtime access lets these tests create retained-output states
 * without adding production debug APIs or altering optimiser hot paths.
 */
#include "nv14_drone_weapons.h"
#include "nv14_objects_drones.h"
#include "nv14_objects_ranged.h"
#include "nv14_rays.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "line %d: %s\n", __LINE__, #condition); return 1; \
} } while (0)
#define OK(expression) CHECK((expression) == NV14_STATUS_OK)

/* Ranged slots are private to nv14_objects_ranged.c. These named test aliases
 * access aim/timing solely to dispatch its real prefire callback. */
enum { TEST_RANGED_MODE = 0, TEST_RANGED_DELAY = 1,
       TEST_TURRET_AIM_X = 4, TEST_TURRET_AIM_Y = 5 };

static size_t object_index(const nv14_level *level, int kind)
{
    size_t i;
    for (i = 0; i < level->native_object_count; ++i)
        if (level->native_objects[i].kind == kind) return i;
    return level->native_object_count;
}

static nv14_vec2 view_of(nv14_state *state, size_t index)
{
    uint32_t uid = state->level->native_objects[index].load_index;
    int kind = state->level->native_objects[index].kind;
    if (kind == NV14_NATIVE_DRONE_LASER || kind == NV14_NATIVE_DRONE_CHAINGUN) {
        nv14_drone_weapon_snapshot snapshot;
        nv14_drone_weapons_snapshot(state, uid, &snapshot);
        return snapshot.view;
    } else {
        nv14_ranged_snapshot snapshot;
        nv14_objects_ranged_snapshot(state, uid, &snapshot);
        return snapshot.view;
    }
}

static nv14_vec2 target_of(nv14_state *state, size_t index)
{
    nv14_ranged_snapshot snapshot;
    nv14_objects_ranged_snapshot(state,
        state->level->native_objects[index].load_index, &snapshot);
    return snapshot.target;
}

static nv14_status think(nv14_state *state, size_t index)
{
    const nv14_native_object *object = &state->level->native_objects[index];
    return state->level->object_modules[object->module_index]->think_object(state, index);
}

static int equal_keys(nv14_state *a, nv14_state *b)
{
    size_t n = nv14_state_key_size(a, -1), na, nb;
    unsigned char *buffer;
    int equal;
    if (n == 0 || n != nv14_state_key_size(b, -1)) return 0;
    buffer = malloc(2 * n);
    if (!buffer) return 0;
    equal = nv14_state_write_key(a, -1, buffer, n, &na) == NV14_STATUS_OK &&
            nv14_state_write_key(b, -1, buffer + n, n, &nb) == NV14_STATUS_OK &&
            na == nb && memcmp(buffer, buffer + n, na) == 0;
    free(buffer);
    return equal;
}

int main(int argc, char **argv)
{
    nv14_level *level;
    nv14_state *state, *clone;
    nv14_error error;
    nv14_ray_query_result query;
    nv14_ray_hit tile;
    nv14_object_runtime *laser, *chain, *turret;
    nv14_vec2 point, origin = {250.71428571428575, 300.0};
    nv14_vec2 aim = {145.7842857144547, 384.61668308940745};
    nv14_vec2 away = {400.0, 100.0}, far = {1000.0, 300.0};
    nv14_vec2 border_origins[4] = {{12, 300}, {780, 300}, {300, 12}, {300, 588}};
    nv14_vec2 border_aims[4] = {{0, 300}, {800, 300}, {300, 0}, {300, 600}};
    size_t laser_i, chain_i, turret_i, homing_i, indices[4], i;
    int tick, mode;

    CHECK(argc == 2);
    OK(nv14_drone_weapons_register());
    OK(nv14_objects_drones_register());
    OK(nv14_objects_ranged_register());
    level = nv14_level_create(argv[1], strlen(argv[1]), 1, &error);
    CHECK(level != NULL);
    state = nv14_state_create(level, &error);
    CHECK(state != NULL);
    laser_i = object_index(level, NV14_NATIVE_DRONE_LASER);
    chain_i = object_index(level, NV14_NATIVE_DRONE_CHAINGUN);
    turret_i = object_index(level, NV14_NATIVE_TURRET);
    homing_i = object_index(level, NV14_NATIVE_HOMING);
    CHECK(laser_i < level->native_object_count && chain_i < level->native_object_count);
    CHECK(turret_i < level->native_object_count && homing_i < level->native_object_count);
    laser = nv14_internal_object_runtime(state, laser_i);
    chain = nv14_internal_object_runtime(state, chain_i);
    turret = nv14_internal_object_runtime(state, turret_i);

    /* Source constructor values matter before the first no-write call. */
    CHECK(laser->f64[NV14_DRONE_LASER_VIEW_X] == 9.0);
    CHECK(laser->f64[NV14_DRONE_LASER_VIEW_Y] == 4.0);
    CHECK(laser->f64[NV14_DRONE_LASER_TARGET_X] == 4.0);
    CHECK(laser->f64[NV14_DRONE_LASER_TARGET_Y] == 5.0);
    CHECK(laser->f64[NV14_DRONE_LASER_VECTOR_X] == 5.0);
    CHECK(laser->f64[NV14_DRONE_LASER_VECTOR_Y] == 7.0);
    CHECK(laser->f64[NV14_DRONE_LASER_LENGTH] == 7.0);
    CHECK(chain->f64[NV14_DRONE_CHAIN_SHOT_X] == 3.0);
    CHECK(chain->f64[NV14_DRONE_CHAIN_SHOT_Y] == 6.0);
    point = view_of(state, homing_i);
    CHECK(point.x == 4.0 && point.y == 56.0);

    for (i = 0; i < 4; ++i) {
        OK(nv14_rays_collide_tiles(level, state, border_origins[i], border_aims[i], 0, 0.0, &tile));
        CHECK(!tile.hit);
        OK(nv14_rays_query_circle(level, state, border_origins[i], border_aims[i], away, 10.0, &query));
        CHECK(!query.object_hit && !query.circle_hit && !query.tile_hit);
    }

    OK(nv14_rays_collide_tiles(level, state, origin, aim, 0, 0.0, &tile));
    CHECK(!tile.hit);
    OK(nv14_rays_collide_tiles(level, state, origin, origin, 0, 0.0, &tile));
    CHECK(!tile.hit);
    OK(nv14_rays_query_circle(level, state, origin, aim, away, 10.0, &query));
    CHECK(!query.object_hit && !query.circle_hit && !query.tile_hit);
    OK(nv14_rays_query_circle(level, state, origin, origin, origin, 10.0, &query));
    CHECK(!query.object_hit && !query.circle_hit && !query.tile_hit);
    OK(nv14_rays_query_circle(level, state, origin, far, far, 10.0, &query));
    CHECK(!query.object_hit && query.tile_hit);
    CHECK(query.point.x == 768.0 && query.point.y == 300.0);

    /* Every acquiring object first writes a wall endpoint, then receives a
       zero-direction query which must preserve that exact endpoint. */
    indices[0] = laser_i; indices[1] = chain_i;
    indices[2] = turret_i; indices[3] = homing_i;
    for (i = 0; i < 4; ++i) {
        const nv14_native_object *object = &level->native_objects[indices[i]];
        state->player.pos = far;
        OK(think(state, indices[i]));
        point = view_of(state, indices[i]);
        CHECK(point.x == 768.0 && point.y == 300.0);
        state->player.pos.x = object->x;
        state->player.pos.y = object->y;
        OK(think(state, indices[i]));
        point = view_of(state, indices[i]);
        CHECK(point.x == 768.0 && point.y == 300.0);
    }

    /* Fire once successfully, complete its entire cycle, then miss the map.
       The second beam retains the preceding nonzero endpoint and damage. */
    laser->f64[NV14_DRONE_POS_X] = origin.x;
    laser->f64[NV14_DRONE_POS_Y] = origin.y;
    state->player.pos.x = 400.0; state->player.pos.y = 300.0;
    OK(nv14_drone_laser_hooks()->think(state, laser_i));
    CHECK(laser->f64[NV14_DRONE_LASER_TARGET_X] == 768.0);
    CHECK(laser->f64[NV14_DRONE_LASER_TARGET_Y] == 300.0);
    state->player.pos = away;
    for (tick = 0; tick < 150; ++tick)
        OK(nv14_drone_laser_hooks()->update_nonmoving(state, laser_i));
    CHECK(laser->i64[NV14_DRONE_MODE] == NV14_DRONE_MODE_MOVING);
    for (mode = NV14_DRONE_MODE_MOVING; mode <= NV14_DRONE_MODE_POSTFIRE; mode += 3) {
        laser->i64[NV14_DRONE_MODE] = mode;
        clone = nv14_state_clone(state, &error);
        CHECK(clone != NULL && equal_keys(state, clone));
        nv14_internal_object_runtime(clone, laser_i)->f64[NV14_DRONE_LASER_TARGET_X] = 4.0;
        CHECK(!equal_keys(state, clone));
        nv14_state_destroy(clone);
    }
    laser->i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_MOVING;
    state->player.pos.x = 138.0; state->player.pos.y = 390.89401499999997;
    OK(nv14_drone_laser_hooks()->think(state, laser_i));
    CHECK(laser->f64[NV14_DRONE_LASER_TARGET_X] == 768.0);
    CHECK(laser->f64[NV14_DRONE_LASER_TARGET_Y] == 300.0);
    CHECK(laser->f64[NV14_DRONE_LASER_VECTOR_Y] == 0.0);
    state->player.pos = away;
    for (tick = 0; tick < 30; ++tick)
        OK(nv14_drone_laser_hooks()->update_nonmoving(state, laser_i));
    state->player.pos.x = 400.0; state->player.pos.y = 300.0;
    OK(nv14_drone_laser_hooks()->update_nonmoving(state, laser_i));
    CHECK(state->player.dead);
    state->player.dead = 0;
    state->player.pos = away;

    /* Turret fire uses a separate retained target from its acquisition view.
       First write a wall, then test a no-wall miss and a zero direction. */
    for (tick = 0; tick < 3; ++tick) {
        nv14_vec2 shot = tick == 0 ? far : (tick == 1 ? aim : origin);
        turret->i64[TEST_RANGED_MODE] = NV14_RANGED_TURRET_PREFIRE;
        turret->i64[TEST_RANGED_DELAY] = 9;
        turret->f64[TEST_TURRET_AIM_X] = shot.x;
        turret->f64[TEST_TURRET_AIM_Y] = shot.y;
        OK(nv14_objects_ranged_module()->update_object(state, turret_i));
        point = target_of(state, turret_i);
        CHECK(point.x == 768.0 && point.y == 300.0);
        CHECK(!state->player.dead);
    }

    /* Middle chaingun shots have no spread: retain view on either no-write
       case, and still replace it when a false result comes from a wall. */
    chain->f64[NV14_DRONE_POS_X] = origin.x;
    chain->f64[NV14_DRONE_POS_Y] = origin.y;
    for (tick = 0; tick < 3; ++tick) {
        chain->i64[NV14_DRONE_MODE] = NV14_DRONE_MODE_FIRING;
        chain->i64[NV14_DRONE_CHAIN_TIMER] = 5;
        chain->i64[NV14_DRONE_CHAIN_MAX_COUNT] = 4;
        chain->i64[NV14_DRONE_CHAIN_CURRENT] = 2;
        chain->f64[NV14_DRONE_CHAIN_VIEW_X] = 77.0;
        chain->f64[NV14_DRONE_CHAIN_VIEW_Y] = 88.0;
        chain->f64[NV14_DRONE_CHAIN_TARGET_X] = tick == 0 ? aim.x - origin.x : (tick == 1 ? 0.0 : 1.0);
        chain->f64[NV14_DRONE_CHAIN_TARGET_Y] = tick == 0 ? aim.y - origin.y : 0.0;
        OK(nv14_drone_chaingun_hooks()->update_nonmoving(state, chain_i));
        point = view_of(state, chain_i);
        CHECK(point.x == (tick == 2 ? 768.0 : 77.0));
        CHECK(point.y == (tick == 2 ? 300.0 : 88.0));
        CHECK(!state->player.dead);
    }

    nv14_state_destroy(state);
    nv14_level_release(level);
    return 0;
}

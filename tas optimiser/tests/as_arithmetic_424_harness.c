/* Source-derived binary64 edge cases through real native callbacks. */
#include "nv14_objects_drones.h"
#include "nv14_objects_ranged.h"
#include "nv14_rays.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

#define CHECK(c) do { if (!(c)) { \
    fprintf(stderr, "line %d: %s\n", __LINE__, #c); return 1; \
} } while (0)
#define OK(e) CHECK((e) == NV14_STATUS_OK)

int main(int argc, char **argv)
{
    nv14_ray_hit hit;
    nv14_vec2 centre = {13.0, 13.0};
    nv14_tile tile;
    nv14_level *level;
    nv14_state *state;
    nv14_error error;
    nv14_object_runtime *rocket;
    nv14_ranged_snapshot snapshot;
    nv14_ray_query_result query;
    size_t i, zap_i = 0, rocket_i = 0;
    int handled, removed;
    double d = 1.0 / sqrt(2.0), speed = 12.0 * 0.2857142857142857;
    CHECK(argc == 2);
    OK(nv14_rays_circle_first_hit(0.0, 0.0, d, d, centre, 10.0, &hit));
    CHECK(hit.hit && hit.distance == 8.38477631085023);
    OK(nv14_rays_circle_first_hit(0.0, 0.0, NAN, NAN, centre, 10.0, &hit));
    CHECK(!hit.hit);
    memset(&tile, 0, sizeof(tile));
    tile.x = tile.y = 36.0;
    tile.signx = tile.signy = 1;
    tile.tile_id = 9; tile.ctype = NV14_CTYPE_CONCAVE;
    OK(nv14_rays_test_tile(60.0, 60.0, -d, -d, &tile, &hit));
    CHECK(hit.hit && hit.point.x == 31.02943725152287);
    CHECK(hit.point.y == hit.point.x);
    tile.tile_id = 13; tile.ctype = NV14_CTYPE_CONVEX;
    OK(nv14_rays_test_tile(47.0, 47.0, d, d, &tile, &hit));
    CHECK(hit.hit && hit.point.x == 7.029437251522872);
    CHECK(hit.point.y == hit.point.x);

    OK(nv14_objects_drones_register());
    OK(nv14_objects_ranged_register());
    level = nv14_level_create(argv[1], strlen(argv[1]), 1, &error);
    CHECK(level != NULL);
    state = nv14_state_create(level, &error);
    CHECK(state != NULL);
    {
        nv14_vec2 origin = {100.0, 100.0}, target = {NAN, NAN};
        OK(nv14_rays_query_circle(level, state, origin, target, centre, 10.0, &query));
        CHECK(!query.object_hit && query.tile_hit);
        CHECK(isnan(query.point.x) && isnan(query.point.y));
        OK(nv14_rays_query_circle(level, state, target, origin, centre, 10.0, &query));
        CHECK(!query.object_hit && !query.circle_hit && !query.tile_hit);
    }
    for (i = 0; i < level->native_object_count; ++i) {
        if (level->native_objects[i].kind == NV14_NATIVE_DRONE_ZAP) zap_i = i;
        if (level->native_objects[i].kind == NV14_NATIVE_HOMING) rocket_i = i;
    }
    state->player.pos.x = 36.05;
    state->player.pos.y = 54.99993421041241;
    OK(nv14_objects_drones_module()->collide_player(state, zap_i, &handled, &removed));
    CHECK(handled && !state->player.dead);
    state->player.pos.y = nextafter(state->player.pos.y, -INFINITY);
    OK(nv14_objects_drones_module()->collide_player(state, zap_i, &handled, &removed));
    CHECK(state->player.dead);
    state->player.dead = 0;

    /* Homing slots are private; fixture aliases avoid a production debug API. */
    rocket = nv14_internal_object_runtime(state, rocket_i);
    rocket->i64[0] = NV14_RANGED_HOMING_ACTIVE;
    rocket->f64[0] = rocket->f64[1] = 300.0;
    rocket->f64[2] = 1.0; rocket->f64[3] = 0.0;
    rocket->f64[6] = speed;
    OK(nv14_internal_grid_move(state, rocket_i, 12, 12));
    state->player.pos.x = (300.0 + speed) + speed;
    state->player.pos.y = 300.0;
    state->player.oldpos = state->player.pos;
    OK(nv14_objects_ranged_module()->update_object(state, rocket_i));
    CHECK(isnan(rocket->f64[2]) && isnan(rocket->f64[3]));
    CHECK(isfinite(rocket->f64[0]) && isfinite(rocket->f64[1]));
    OK(nv14_objects_ranged_module()->update_object(state, rocket_i));
    CHECK(isnan(rocket->f64[0]) && isnan(rocket->f64[1]));
    CHECK(rocket->i64[0] == NV14_RANGED_HOMING_ACTIVE);
    OK(nv14_objects_ranged_snapshot(state, level->native_objects[rocket_i].load_index, &snapshot));
    CHECK(!snapshot.grid_active);
    OK(nv14_objects_ranged_module()->collide_player(state, rocket_i, &handled, &removed));
    CHECK(!state->player.dead);
    nv14_state_destroy(state);
    nv14_level_release(level);
    return 0;
}

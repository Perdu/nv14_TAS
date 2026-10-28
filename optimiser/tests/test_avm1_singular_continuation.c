/* Force rare state transitions without production testing APIs. */
#include "../native/nv14_core.c"
#include "nv14_objects_drones.h"
#include "nv14_drones_internal.h"
#include "nv14_objects_ranged.h"
#include "nv14_drone_weapons.h"
#include <stdio.h>
#include <limits.h>

#define CHECK(c) do { if (!(c)) { fprintf(stderr,"line %d: %s\n",__LINE__,#c); return 1; } } while (0)
#define OK(c) CHECK((c) == NV14_STATUS_OK)

int main(int argc, char **argv)
{
    nv14_level *level;
    nv14_state *state;
    nv14_error error;
    nv14_input input = {0};
    nv14_object_runtime *drone;
    nv14_tile tile = {0};
    nv14_step_result result;
    size_t index = 0;
    int i;
    CHECK(argc == 2);
    OK(nv14_drone_weapons_register());
    OK(nv14_objects_drones_register());
    OK(nv14_objects_ranged_register());
    level = nv14_level_create(argv[1], strlen(argv[1]), 1, &error);
    CHECK(level != NULL);
    state = nv14_state_create(level, &error);
    CHECK(state != NULL);
    while (index < level->native_object_count &&
           level->native_objects[index].kind != NV14_NATIVE_DRONE_ZAP) ++index;
    CHECK(index < level->native_object_count);
    drone = nv14_internal_object_runtime(state, index);
    OK(nv14_state_step(state, input, &result));
    CHECK(drone->i64[NV14_DRONE_CUR_DIR] == -1);
    CHECK(drone->f64[NV14_DRONE_POS_X] == 84.0);
    for (i=0;i<4;++i) OK(nv14_state_step(state, input, &result));
    CHECK(drone->i64[NV14_DRONE_CUR_DIR] == -1);
    CHECK(drone->f64[NV14_DRONE_POS_X] == 84.0);
    /* A chaser may find a newly opened route, but source SetDir's existing
       undefined direction guard ignores its valid requested direction. */
    drone->i64[NV14_DRONE_IS_CHASER] = 1;
    state->player.pos.x = state->player.oldpos.x = 132.0;
    state->player.pos.y = state->player.oldpos.y = 84.0;
    state->player.cell_i = 5;
    state->player.cell_j = 3;
    OK(nv14_state_set_edge_override(state, 3, 3, NV14_EDGE_R, NV14_EID_OFF));
    OK(nv14_drones_update_move(state, index, 1));
    CHECK(drone->i64[NV14_DRONE_CUR_DIR] == -1);
    CHECK(drone->i64[NV14_DRONE_IS_CHASING] == 1);
    CHECK(drone->f64[NV14_DRONE_GOAL_X] > 84.0);
    OK(nv14_drones_update_move(state, index, 1));
    CHECK(isnan(drone->f64[NV14_DRONE_POS_X]));
    CHECK(isnan(drone->f64[NV14_DRONE_POS_Y]));
    CHECK(state->object_cell_slot[index] == -1);
    CHECK(drone->i64[NV14_DRONE_CELL_I] == INT_MIN);

    tile.x = tile.y = 108.0;
    tile.signx = tile.signy = 1;
    state->player.pos.x = state->player.pos.y = 96.0;
    CHECK(nv14_project_circle_convex(40.,40.,1,0,&state->player,&tile) == NV14_COL_OTHER);
    CHECK(isnan(state->player.pos.x) && isnan(state->player.pos.y));
    for (i=0;i<3;++i) {
        OK(nv14_state_step(state,input,&result));
        CHECK(!state->player.dead);
        CHECK(isnan(state->player.pos.x) && isnan(state->player.pos.y));
        CHECK(state->player.cell_i == INT_MIN && !state->player.near_wall);
    }
    /* Missing cell 33 must unlink immediately (dense query margin extends
       further, but it isn't an ActionScript TileMapCell). Re-entry inserts. */
    OK(nv14_internal_grid_move(state,index,32,4));
    CHECK(state->object_cell_slot[index] >= 0);
    OK(nv14_internal_grid_move(state,index,33,4));
    CHECK(state->object_cell_slot[index] == -1);
    OK(nv14_internal_grid_move(state,index,32,4));
    CHECK(state->object_cell_slot[index] >= 0);
    nv14_state_destroy(state);
    nv14_level_release(level);
    return 0;
}

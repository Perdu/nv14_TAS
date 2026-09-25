/* Shared-step event isolation and endpoint history ownership (no Python wrapper). */
#include "nv14_endpoint.h"
#include "nv14_internal.h"
#include <assert.h>
#include <math.h>
#include <string.h>

int main(void)
{
    char text[1024];
    memset(text, '0', 713);
    for (int x = 0; x < 31; ++x) text[x * 23 + 5] = '1';
    strcpy(text + 713, "|5^396,134");
    nv14_error error = {0};
    nv14_level *level = nv14_level_create(text, strlen(text), 0, &error);
    assert(level);
    nv14_state *state = nv14_state_create(level, &error);
    assert(state);
    nv14_input neutral = {0, 0, 0, -1}, press = {0, 0, 1, -1};
    nv14_step_result step, alternate;
    nv14_player_snapshot alternate_player;
    assert(nv14_state_step(state, neutral, &step) == NV14_STATUS_OK);
    nv14_state *saved = nv14_state_clone(state, &error);
    assert(saved);
    assert(nv14_internal_state_step_alternate(state, neutral, press,
        &alternate_player, &step, &alternate) == NV14_STATUS_OK);
    assert(!step.jumped && step.jump_origin_x == 0 && step.jump_origin_y == 0);
    assert(alternate.jumped && alternate.jump_origin_x == 396 && alternate.jump_origin_y == 134);
    assert(state->player.pos.y == 134 && alternate_player.pos.y == 131);
    assert(nv14_state_copy_into(state, saved, &error) == NV14_STATUS_OK);
    assert(nv14_internal_state_step_alternate(state, press, neutral,
        &alternate_player, &step, &alternate) == NV14_STATUS_OK);
    assert(step.jumped && step.jump_origin_x == 396 && step.jump_origin_y == 134);
    assert(!alternate.jumped && alternate.jump_origin_x == 0 && alternate.jump_origin_y == 0);
    assert(state->player.pos.y == 131 && alternate_player.pos.y == 134);
    assert(nv14_state_step(state, press, &step) == NV14_STATUS_OK);
    assert(!step.jumped && step.jump_origin_x == 0 && step.jump_origin_y == 0);

    nv14_endpoint_plan plan = {0};
    plan.target_frame = 7;
    plan.has_jump_region = 1;
    plan.jump_region[0] = plan.jump_region[1] = 396;
    plan.jump_region[2] = plan.jump_region[3] = 134;
    plan.jump_start = 1; plan.jump_end = 7;
    plan.prefix_jump.frame = -1;
    for (int i = 0; i < 4; ++i) {
        plan.lower[i] = -INFINITY; plan.upper[i] = INFINITY;
    }
    uint8_t inputs[8];
    memset(inputs, 16, sizeof(inputs));
    inputs[1] = 20; /* held jump, derived edge */
    nv14_endpoint_result result = {0};
    assert(nv14_endpoint_scan(&plan, saved, inputs, 8, &result) == NV14_STATUS_OK);
    assert(result.jump.frame == 1 && result.jump.x == 396 && result.jump.y == 134);
    assert(result.state->frame == 8 && saved->frame == 1);
    nv14_state_destroy(result.state);
    /* A native caller may encounter exceptional player positions: never latch them. */
    saved->player.pos.x = saved->player.oldpos.x = NAN;
    assert(nv14_endpoint_scan(&plan, saved, inputs, 8, &result) == NV14_STATUS_OK);
    assert(result.jump.frame == -1);
    nv14_state_destroy(result.state);
    nv14_state_destroy(saved);
    nv14_state_destroy(state);
    nv14_level_release(level);
    return 0;
}

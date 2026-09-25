/* Force unusual player states independently of collision reachability. */
#include "nv14_endpoint.h"
#include "nv14_internal.h"
#include <assert.h>
#include <math.h>
#include <string.h>

int main(void)
{
    char text[4096];
    memset(text, '0', 713);
    strcpy(text + 713, "|5^100,100");
    nv14_error error = {0};
    nv14_level *level = nv14_level_create(text, strlen(text), 0, &error);
    assert(level);
    nv14_endpoint_plan plan = {0};
    plan.target_frame = 7;
    plan.earliest = plan.has_region = 1;
    plan.region[0] = 0; plan.region[1] = 700;
    plan.region[2] = 0; plan.region[3] = 600;
    for (int i = 0; i < 4; ++i) {
        plan.lower[i] = -INFINITY; plan.upper[i] = INFINITY;
    }
    uint8_t inputs[8];
    memset(inputs, 16, sizeof(inputs));
    const double values[] = {NAN, INFINITY, -INFINITY};
    for (int i = 0; i < 3; ++i) {
        nv14_state *prefix = nv14_state_create(level, &error);
        assert(prefix);
        prefix->player.pos.x = prefix->player.oldpos.x = values[i];
        nv14_endpoint_result out = {0};
        assert(nv14_endpoint_scan(&plan, prefix, inputs, 8, &out) == NV14_STATUS_OK);
        assert(out.state && out.state->frame == 1);
        assert(out.terminal_frame == 7 && !out.terminal_dead);
        assert(!isfinite(out.state->player.pos.x) && !out.state->player.dead);
        assert(prefix->frame == 0); /* immutable starting state */
        nv14_state_destroy(out.state);
        nv14_state_destroy(prefix);
    }
    nv14_level_release(level);
    /* Multiword masks and simultaneous fresh events, including a failed event
     * whose later frozen/consumed states must not replace the repair point. */
    for (int i = 0; i < 70; ++i) strcat(text, "!0^500,500");
    strcat(text, "!0^90,100!0^110,100");
    level = nv14_level_create(text, strlen(text), 0, &error);
    assert(level);
    nv14_state *prefix = nv14_state_create(level, &error);
    nv14_endpoint_atom targets[2] = {{70, 90, 100, 0, 1}, {71, 110, 100, 0, 1}};
    nv14_endpoint_atom required = {0, 500, 500, 0, 1};
    nv14_endpoint_group group = {0, 1};
    plan.targets = targets; plan.target_count = 2;
    plan.atoms = &required; plan.required = &group; plan.required_count = 1;
    uint8_t events[2] = {0};
    nv14_endpoint_result out = {0};
    out.events = events;
    assert(nv14_endpoint_scan(&plan, prefix, inputs, 8, &out) == NV14_STATUS_OK);
    assert(out.state->frame == 1 && out.terminal_frame == 7);
    assert(events[0] && events[1]);
    assert(nv14_internal_mask_test(out.state->collected_gold, 70));
    assert(nv14_internal_mask_test(out.state->collected_gold, 71));
    nv14_state_destroy(out.state);
    plan.required_count = 0;
    assert(nv14_endpoint_scan(&plan, prefix, inputs, 8, &out) == NV14_STATUS_OK);
    assert(out.state->frame == 1 && out.terminal_frame == 0);
    assert(events[0] && events[1]);
    nv14_state_destroy(out.state);
    nv14_state_destroy(prefix);
    nv14_level_release(level);
    return 0;
}

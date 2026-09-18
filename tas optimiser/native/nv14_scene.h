#ifndef NV14_SCENE_H
#define NV14_SCENE_H

/* Optional, query-only scene export. Calling these functions does not enable
 * animation, alter gameplay state, or allocate native memory. Ordinary search
 * never calls them and has no additional tick/clone/key work. */
#include "nv14_core.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NV14_SCENE_ABI_VERSION 1u

typedef struct nv14_scene_object {
    size_t id;
    uint32_t state_index;
    int kind;
    nv14_object_descriptor descriptor;
    nv14_vec2 position;
    nv14_vec2 base_position;
    double radius;
    int active, visible, updating, thinking, grid_active;
    int mode, asleep, moving, is_open, is_locked, is_trap;
    int trigger_active, horizontal, chasing, direction_index, weapon_type;
    int rocket_visible, crosshair_visible, beam_visible, shot_visible;
    nv14_vec2 previous_position, direction, door_position, rocket_position;
    nv14_vec2 goal, view, target, aim, vector, shot_target, beam_end;
    double rocket_rotation_deg, speed, shot_timer, laser_length;
    int64_t fire_delay_timer, weapon_timer, shot_index, maximum_shot_index;
} nv14_scene_object;

size_t nv14_scene_object_count(const nv14_state *state);
const char *nv14_scene_kind_name(int kind);
nv14_status nv14_scene_object_at(
    const nv14_state *state, size_t object_index, nv14_scene_object *out
);

#ifdef __cplusplus
}
#endif
#endif

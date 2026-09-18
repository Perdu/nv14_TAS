#ifndef NV14_OBJECTS_BASIC_H
#define NV14_OBJECTS_BASIC_H

/* Native implementations of the source game's always-simulated mutable
 * objects: BounceBlock (1), Thwomp (8), and TestDoor (9).
 *
 * This is a private sibling-module interface.  Register the module exactly
 * once before constructing any nv14_level; registration is idempotent.
 */

#include "nv14_internal.h"

#ifdef __cplusplus
extern "C" {
#endif

const nv14_internal_object_module *nv14_objects_basic_module(void);
nv14_status nv14_objects_basic_register(void);

/* Query-only presentation data. No runtime slots are added for rendering. */
typedef struct nv14_basic_scene_snapshot {
    nv14_vec2 position;
    nv14_vec2 previous_position;
    nv14_vec2 direction;
    nv14_vec2 door_position;
    int mode;
    int asleep;
    int moving;
    int is_open;
    int is_locked;
    int is_trap;
    int trigger_active;
    int horizontal;
    int64_t door_timer;
} nv14_basic_scene_snapshot;

nv14_status nv14_objects_basic_scene_at(
    const nv14_state *state, size_t object_index,
    nv14_basic_scene_snapshot *out
);

/* Read the two permanent TestDoor interaction states by serialized load id.
 * The search kernel uses this narrow accessor instead of depending on the
 * basic module's private runtime-slot layout.  A missing/non-door load id
 * leaves both outputs false and returns NV14_STATUS_OUT_OF_BOUNDS. */
nv14_status nv14_objects_basic_door_interactions(
    const nv14_state *state,
    uint32_t load_index,
    int *locked_open_out,
    int *trap_triggered_out
);

/* O(1) variant for kernels which have already resolved native-object order. */
nv14_status nv14_objects_basic_door_interactions_at(
    const nv14_state *state,
    size_t object_index,
    int *locked_open_out,
    int *trap_triggered_out
);

#ifdef __cplusplus
}
#endif

#endif /* NV14_OBJECTS_BASIC_H */

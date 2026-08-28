#ifndef NV14_OBJECTS_DRONES_H
#define NV14_OBJECTS_DRONES_H

/* Native type-6 DroneObject common navigation and Zap weapon behavior. */

#include "nv14_drones_internal.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct nv14_drone_snapshot {
    uint32_t load_index;
    int weapon_type;
    int move_type;
    int current_direction;
    nv14_vec2 position;
    nv14_vec2 goal;
    double speed;
    int32_t cell_i;
    int32_t cell_j;
    int64_t ai_counter;
    int64_t ai_counter2;
    int is_chaser;
    int is_chasing;
    int surface_future_direction;
    int surface_grab_pending;
    int mode;
    int updating;
    int thinking;
    int grid_active;
} nv14_drone_snapshot;

const nv14_internal_object_module *nv14_objects_drones_module(void);
nv14_status nv14_objects_drones_register(void);

/* Diagnostic state view used by native differential harnesses. */
nv14_status nv14_objects_drones_snapshot(
    const nv14_state *state,
    uint32_t load_index,
    nv14_drone_snapshot *out
);

#ifdef __cplusplus
}
#endif

#endif /* NV14_OBJECTS_DRONES_H */

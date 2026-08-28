#ifndef NV14_OBJECTS_RANGED_H
#define NV14_OBJECTS_RANGED_H

/* Native TurretObject (3) and HomingLauncherObject (10) implementations.
 *
 * This is a private sibling-module interface.  Register it before constructing
 * any nv14_level.  Registration is idempotent and object state lives entirely
 * in the core-owned fixed runtime blocks.
 */

#include "nv14_internal.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum nv14_ranged_turret_mode {
    NV14_RANGED_TURRET_WAITING = 0,
    NV14_RANGED_TURRET_TARGETING = 1,
    NV14_RANGED_TURRET_PREFIRE = 2,
    NV14_RANGED_TURRET_POSTFIRE = 3
} nv14_ranged_turret_mode;

typedef enum nv14_ranged_homing_mode {
    NV14_RANGED_HOMING_IDLE = 0,
    NV14_RANGED_HOMING_PREFIRE = 1,
    NV14_RANGED_HOMING_ACTIVE = 2
} nv14_ranged_homing_mode;

/* Internal diagnostic view used by differential tests and future wrappers. */
typedef struct nv14_ranged_snapshot {
    int object_type;
    uint32_t load_index;
    int mode;
    int64_t fire_delay_timer;
    nv14_vec2 base_position;
    nv14_vec2 position;
    nv14_vec2 direction;
    nv14_vec2 view;
    nv14_vec2 target;
    nv14_vec2 aim;
    double speed;
    double current_acceleration;
    double aim_speed;
    double shot_timer;
    int32_t cell_i;
    int32_t cell_j;
    int updating;
    int thinking;
    int grid_active;
} nv14_ranged_snapshot;

const nv14_internal_object_module *nv14_objects_ranged_module(void);
nv14_status nv14_objects_ranged_register(void);

/* Locate a ranged object by serialized load index and copy its mutable state. */
nv14_status nv14_objects_ranged_snapshot(
    const nv14_state *state,
    uint32_t load_index,
    nv14_ranged_snapshot *out
);

#ifdef __cplusplus
}
#endif

#endif /* NV14_OBJECTS_RANGED_H */

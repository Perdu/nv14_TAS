#ifndef NV14_DRONE_WEAPONS_H
#define NV14_DRONE_WEAPONS_H

/* Native LaserDrone and ChaingunDrone weapon state machines.
 *
 * Common type-6 parsing, navigation, grid movement and update scheduling live
 * in nv14_objects_drones.c.  Register these immutable weapon callbacks before
 * constructing a level that enables enemies.
 */

#include "nv14_drones_internal.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct nv14_drone_weapon_snapshot {
    uint32_t load_index;
    int weapon_type;
    int mode;
    int64_t fire_delay_timer;
    int64_t weapon_timer;
    int64_t maximum_shot_index;
    int64_t current_shot_index;
    nv14_vec2 view;
    nv14_vec2 target;
    nv14_vec2 vector;
    nv14_vec2 shot_target;
    double laser_length;
    double spread;
} nv14_drone_weapon_snapshot;

const nv14_drone_weapon_hooks *nv14_drone_laser_hooks(void);
const nv14_drone_weapon_hooks *nv14_drone_chaingun_hooks(void);

/* Register both tables.  The underlying registry makes repeated calls safe. */
nv14_status nv14_drone_weapons_register(void);

/* Diagnostic view for focused differential tests. */
nv14_status nv14_drone_weapons_snapshot(
    const nv14_state *state,
    uint32_t load_index,
    nv14_drone_weapon_snapshot *out
);

#ifdef __cplusplus
}
#endif

#endif /* NV14_DRONE_WEAPONS_H */

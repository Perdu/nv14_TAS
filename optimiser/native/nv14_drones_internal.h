#ifndef NV14_DRONES_INTERNAL_H
#define NV14_DRONES_INTERNAL_H

/* Private contract shared by the type-6 drone navigation module and the
 * Laser/Chaingun weapon implementation.  This is deliberately not part of
 * nv14_core.h's public ABI.
 *
 * Common navigation owns slots 0..4 (f64) and 0..10 (i64).  Weapon callbacks
 * may use the named auxiliary slots below, but must not change the common
 * slots except for NV14_DRONE_MODE and their documented timers.  Every slot
 * is core-owned, cloned by memcpy, and included in the native state key.
 */

#include "nv14_internal.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NV14_DRONE_WEAPON_HOOKS_ABI_VERSION 1u

typedef enum nv14_drone_weapon_type {
    NV14_DRONE_WEAPON_ZAP = 0,
    NV14_DRONE_WEAPON_LASER = 1,
    NV14_DRONE_WEAPON_CHAINGUN = 2
} nv14_drone_weapon_type;

typedef enum nv14_drone_mode {
    NV14_DRONE_MODE_MOVING = 0,
    NV14_DRONE_MODE_PREFIRE = 1,
    NV14_DRONE_MODE_FIRING = 2,
    NV14_DRONE_MODE_POSTFIRE = 3
} nv14_drone_mode;

typedef enum nv14_drone_f64_slot {
    NV14_DRONE_POS_X = 0,
    NV14_DRONE_POS_Y = 1,
    NV14_DRONE_GOAL_X = 2,
    NV14_DRONE_GOAL_Y = 3,
    NV14_DRONE_SPEED = 4,

    NV14_DRONE_AUX0 = 5,
    NV14_DRONE_AUX1 = 6,
    NV14_DRONE_AUX2 = 7,
    NV14_DRONE_AUX3 = 8,
    NV14_DRONE_AUX4 = 9,
    NV14_DRONE_AUX5 = 10,
    NV14_DRONE_AUX6 = 11,
    NV14_DRONE_AUX7 = 12,
    NV14_DRONE_AUX8 = 13,
    NV14_DRONE_AUX9 = 14,
    NV14_DRONE_AUX10 = 15,

    /* Laser aliases. */
    NV14_DRONE_LASER_VIEW_X = NV14_DRONE_AUX0,
    NV14_DRONE_LASER_VIEW_Y = NV14_DRONE_AUX1,
    NV14_DRONE_LASER_TARGET_X = NV14_DRONE_AUX2,
    NV14_DRONE_LASER_TARGET_Y = NV14_DRONE_AUX3,
    NV14_DRONE_LASER_VECTOR_X = NV14_DRONE_AUX4,
    NV14_DRONE_LASER_VECTOR_Y = NV14_DRONE_AUX5,
    NV14_DRONE_LASER_LENGTH = NV14_DRONE_AUX6,

    /* Chaingun aliases. */
    NV14_DRONE_CHAIN_VIEW_X = NV14_DRONE_AUX0,
    NV14_DRONE_CHAIN_VIEW_Y = NV14_DRONE_AUX1,
    NV14_DRONE_CHAIN_TARGET_X = NV14_DRONE_AUX2,
    NV14_DRONE_CHAIN_TARGET_Y = NV14_DRONE_AUX3,
    NV14_DRONE_CHAIN_VECTOR_X = NV14_DRONE_AUX4,
    NV14_DRONE_CHAIN_VECTOR_Y = NV14_DRONE_AUX5,
    NV14_DRONE_CHAIN_SHOT_X = NV14_DRONE_AUX6,
    NV14_DRONE_CHAIN_SHOT_Y = NV14_DRONE_AUX7,
    NV14_DRONE_CHAIN_SPREAD = NV14_DRONE_AUX8
} nv14_drone_f64_slot;

typedef enum nv14_drone_i64_slot {
    NV14_DRONE_CUR_DIR = 0,
    NV14_DRONE_MOVE_TYPE = 1,
    NV14_DRONE_CELL_I = 2,
    NV14_DRONE_CELL_J = 3,
    NV14_DRONE_AI_COUNTER = 4,
    NV14_DRONE_AI_COUNTER2 = 5,
    NV14_DRONE_IS_CHASER = 6,
    NV14_DRONE_IS_CHASING = 7,
    NV14_DRONE_SURFACE_FUTURE_DIR = 8,
    NV14_DRONE_SURFACE_GRAB_PENDING = 9,
    NV14_DRONE_MODE = 10,
    NV14_DRONE_FIRE_DELAY_TIMER = 11,
    NV14_DRONE_WEAPON_TIMER = 12,
    NV14_DRONE_WEAPON_COUNT = 13,
    NV14_DRONE_WEAPON_INDEX = 14,
    NV14_DRONE_WEAPON_AUX = 15,

    NV14_DRONE_LASER_TIMER = NV14_DRONE_WEAPON_TIMER,
    NV14_DRONE_CHAIN_TIMER = NV14_DRONE_WEAPON_TIMER,
    NV14_DRONE_CHAIN_MAX_COUNT = NV14_DRONE_WEAPON_COUNT,
    NV14_DRONE_CHAIN_CURRENT = NV14_DRONE_WEAPON_INDEX
} nv14_drone_i64_slot;

/* A weapon unit registers one immutable callback table for Laser and one for
 * Chaingun before any nv14_level is constructed.  Zap is implemented by the
 * common module and cannot be overridden.
 *
 * init_runtime runs after common slots have been initialised but before the
 * object is appended.  update_nonmoving is called only while MODE is PREFIRE,
 * FIRING, or POSTFIRE; common navigation handles MOVING.  think is called by
 * the shared round-robin scheduler and is responsible for EndThink when it
 * acquires the player, exactly as DroneObject.StartFiring does.
 */
typedef struct nv14_drone_weapon_hooks {
    uint32_t abi_version;
    uint32_t struct_size;
    int weapon_type;
    uint32_t reserved;
    const char *name;
    nv14_status (*init_runtime)(
        nv14_level *level,
        const nv14_object_descriptor *descriptor,
        nv14_object_runtime *runtime,
        nv14_error *error_out
    );
    nv14_status (*update_nonmoving)(nv14_state *state, size_t object_index);
    nv14_status (*think)(nv14_state *state, size_t object_index);
} nv14_drone_weapon_hooks;

nv14_status nv14_drones_register_weapon_hooks(
    const nv14_drone_weapon_hooks *hooks
);

/* Shared helpers for weapon callbacks. */
nv14_status nv14_drones_update_move(
    nv14_state *state,
    size_t object_index,
    int allow_zap_chase
);
nv14_status nv14_drones_start_moving(
    nv14_state *state,
    size_t object_index
);

#ifdef __cplusplus
}
#endif

#endif /* NV14_DRONES_INTERNAL_H */

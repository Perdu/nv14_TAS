#ifndef NV14_OBJECTS_GUARD_H
#define NV14_OBJECTS_GUARD_H

#include "nv14_internal.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Idempotent when this exact module has already been registered. */
nv14_status nv14_objects_guard_register(void);

/* Source IdleAfterDeath; invoked only on death/completion transitions. */
void nv14_objects_guard_idle_after_death(nv14_state *state, size_t object_index);

typedef struct nv14_guard_scene_snapshot {
    nv14_vec2 position;
    int direction;
    int chasing;
} nv14_guard_scene_snapshot;

nv14_status nv14_objects_guard_scene_at(
    const nv14_state *state, size_t object_index,
    nv14_guard_scene_snapshot *out
);

#ifdef __cplusplus
}
#endif

#endif /* NV14_OBJECTS_GUARD_H */

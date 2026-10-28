#ifndef NV14_VISUAL_INTERNAL_H
#define NV14_VISUAL_INTERNAL_H

#include "nv14_visual.h"

typedef struct nv14_visual_tracker {
    nv14_visual_snapshot snapshot;
    uint32_t timeline_frames;
    int auto_draw;
    int celebration_variant;
} nv14_visual_tracker;

/* Called only when a tracker has been explicitly allocated. */
void nv14_visual_begin_tick(nv14_visual_tracker *visual);
void nv14_visual_state_changed(
    nv14_visual_tracker *visual, const nv14_player_snapshot *player
);
void nv14_visual_relax_rotation(nv14_visual_tracker *visual);
void nv14_visual_advance_run(
    nv14_visual_tracker *visual, double vx, double vy, double nx, double ny
);
void nv14_visual_celebrate_air(nv14_visual_tracker *visual);
void nv14_visual_celebrate_ground(nv14_visual_tracker *visual);
void nv14_visual_finish_tick(nv14_visual_tracker *visual, const nv14_state *state);

#endif

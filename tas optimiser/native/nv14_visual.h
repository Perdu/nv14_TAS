#ifndef NV14_VISUAL_H
#define NV14_VISUAL_H

/* Optional, observation-only player animation. No Flash renderer is required.
 * Sprite 898's labels/stop frames come from the supplied n_v14.swf; see
 * docs/NATIVE_VISUAL_STATE.md for timing and terminal-state limitations. */
#include "nv14_core.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NV14_VISUAL_ABI_VERSION 1u

typedef enum nv14_visual_animation {
    NV14_ANIM_STAND = 0,
    NV14_ANIM_SKID,
    NV14_ANIM_RUN,
    NV14_ANIM_JUMP,
    NV14_ANIM_WALLSLIDE,
    NV14_ANIM_CELEBRATE_OLD,
    NV14_ANIM_CELEBRATE_NEW1,
    NV14_ANIM_CELEBRATE_NEW2,
    NV14_ANIM_CELEBRATE_NEW3,
    NV14_ANIM_CELEBRATE_NEW4,
    NV14_ANIM_CELEBRATE_NEW5,
    NV14_ANIM_CELEBRATE_NEW6,
    NV14_ANIM_CELEBRATE_NEW7,
    NV14_ANIM_CELEBRATE_NEW8,
    NV14_ANIM_CELEBRATE_NEW9,
    NV14_ANIM_RAGDOLL,
    NV14_ANIM_CELEBRATE_UNRESOLVED
} nv14_visual_animation;

typedef enum nv14_visual_render_mode {
    NV14_RENDER_STATIC_GROUND = 0,
    NV14_RENDER_RUN,
    NV14_RENDER_IN_AIR,
    NV14_RENDER_WALLSLIDE,
    NV14_RENDER_RAGDOLL
} nv14_visual_render_mode;

typedef struct nv14_visual_snapshot {
    double x;
    double y;
    double rotation_deg;
    double run_remainder;
    int32_t facing;
    int32_t animation;
    int32_t current_frame;  /* 1-based SWF frame; 0 means unresolved/not a sprite. */
    int32_t previous_frame; /* Draw_Normal's prevframe, before Render. */
    int32_t run_frame;      /* 0 until the first AdvanceRunAnim call. */
    int32_t render_mode;
    uint8_t playing;
    uint8_t visible;
    uint8_t terminal;
    uint8_t reserved;
} nv14_visual_snapshot;

/* Enable only at frame zero, before stepping. Repeated enable is rejected.
 * timeline_frames=3 and auto_draw=1 define the nominal 120/40 fps schedule.
 * For an externally recorded schedule use 0/0 plus advance/draw below.
 * celebration_variant=0 leaves the random choice unresolved; 1..9 supplies a
 * choice explicitly. This does not seed or consume the gameplay RNG.
 * Disable before replacing a player snapshot; clone/copy preserve the tracker.
 * Gameplay state keys deliberately exclude this observation-only data. */
nv14_status nv14_state_enable_visuals(
    nv14_state *state, uint32_t timeline_frames, int auto_draw,
    int celebration_variant
);
nv14_status nv14_state_disable_visuals(nv14_state *state);
int nv14_state_visuals_enabled(const nv14_state *state);
nv14_status nv14_state_get_visual(
    const nv14_state *state, nv14_visual_snapshot *snapshot_out
);
nv14_status nv14_state_advance_visual_timeline(nv14_state *state, uint32_t frames);
nv14_status nv14_state_draw_visual(nv14_state *state);
const char *nv14_visual_animation_name(int animation);
const char *nv14_visual_render_name(int render_mode);

#ifdef __cplusplus
}
#endif
#endif

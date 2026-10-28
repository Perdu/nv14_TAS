#include "nv14_visual_internal.h"
#include "nv14_internal.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

/* Exact FrameLabel and DoAction(stop) tags of DefineSprite 898 (797 frames).
 * These tables contain animation metadata, not artwork or limb geometry. */
static const int nv14_animation_starts[] = {
    1, 12, 13, 85, 104, 105, 106, 167, 234, 313, 355, 449, 507, 659, 744
};
static const int nv14_stop_frames[] = {
    11, 166, 233, 312, 354, 448, 506, 658, 743, 797
};
static const char *const nv14_animation_names[] = {
    "STAND", "SKID", "RUN", "JUMP", "WALLSLIDE", "CELEBRATE_OLD",
    "CELEBRATE_NEW1", "CELEBRATE_NEW2", "CELEBRATE_NEW3",
    "CELEBRATE_NEW4", "CELEBRATE_NEW5", "CELEBRATE_NEW6",
    "CELEBRATE_NEW7", "CELEBRATE_NEW8", "CELEBRATE_NEW9",
    "RAGDOLL", "CELEBRATE_UNRESOLVED"
};

const char *nv14_visual_animation_name(int animation)
{
    if (animation < 0 || animation > NV14_ANIM_CELEBRATE_UNRESOLVED)
        return "UNKNOWN";
    return nv14_animation_names[animation];
}

const char *nv14_visual_render_name(int render_mode)
{
    static const char *const names[] = {
        "static_ground", "run", "in_air", "wallslide", "ragdoll"
    };
    if (render_mode < 0 || render_mode > NV14_RENDER_RAGDOLL) return "unknown";
    return names[render_mode];
}

static void nv14_visual_goto(nv14_visual_snapshot *s, int frame, int play)
{
    int index;
    /* A first-ever RenderRun has an undefined runanimcurframe: Flash leaves
     * the frame selected by Run() in place. Zero represents that undefined
     * value. Run() does NOT reset a previously defined runanimcurframe. */
    if (frame < 1 || frame > 797) return;
    s->current_frame = frame;
    s->playing = (uint8_t)(play != 0);
    for (index = NV14_ANIM_CELEBRATE_NEW9; index >= 0; --index) {
        if (frame >= nv14_animation_starts[index]) {
            s->animation = index;
            break;
        }
    }
    for (index = 0; index < 10; ++index)
        if (frame == nv14_stop_frames[index]) s->playing = 0;
}

static void nv14_visual_advance(nv14_visual_tracker *visual, uint32_t frames)
{
    nv14_visual_snapshot *s = &visual->snapshot;
    int index;
    if (s->terminal || !s->playing || s->current_frame == 0 || frames == 0)
        return;
    for (index = 0; index < 10; ++index) {
        int stop = nv14_stop_frames[index];
        if (stop >= s->current_frame) {
            uint32_t remaining = (uint32_t)(stop - s->current_frame);
            if (frames >= remaining) nv14_visual_goto(s, stop, 0);
            else nv14_visual_goto(s, s->current_frame + (int)frames, 1);
            return;
        }
    }
}

static void nv14_visual_face_movement(
    nv14_visual_snapshot *s, const nv14_player_snapshot *p
)
{
    double vx = p->pos.x - p->oldpos.x;
    if (vx > 0.0) s->facing = 1;
    else if (vx < 0.0) s->facing = -1;
}

static double nv14_visual_floor_rotation(double nx, double ny)
{
    double degrees;
    if (nx == 0.0) degrees = -90.0;
    else if (ny == 0.0) degrees = nx < 0.0 ? 180.0 : 0.0;
    else {
        degrees = atan(ny / nx) / 0.017453292519943295;
        if (nx < 0.0) degrees += 180.0;
    }
    degrees += 90.0;
    /* MovieClip._rotation stores a signed angle, including left slopes. */
    if (degrees > 180.0) degrees -= 360.0;
    else if (degrees < -180.0) degrees += 360.0;
    return degrees;
}

static void nv14_visual_draw(
    nv14_visual_tracker *visual, const nv14_player_snapshot *p
)
{
    nv14_visual_snapshot *s = &visual->snapshot;
    if (!s->visible) return;
    s->previous_frame = s->current_frame;
    s->x = p->pos.x;
    s->y = p->pos.y;
    if (s->render_mode != NV14_RENDER_WALLSLIDE)
        nv14_visual_face_movement(s, p);
    if (s->render_mode == NV14_RENDER_IN_AIR) {
        double vy = p->pos.y - p->oldpos.y;
        double pose;
        if (!isfinite(vy)) return;
        if (vy < 0.0) pose = vy < -1.0 ? -1.0 : vy;
        else pose = vy > 2.5 ? 1.0 : sqrt(vy / 2.5);
        nv14_visual_goto(s, 94 + (int)floor(pose * 9.0), 0);
    } else if (s->render_mode == NV14_RENDER_RUN ||
               s->render_mode == NV14_RENDER_STATIC_GROUND) {
        if (s->render_mode == NV14_RENDER_RUN)
            nv14_visual_goto(s, s->run_frame, 0);
        s->rotation_deg = nv14_visual_floor_rotation(p->floor_n.x, p->floor_n.y);
    }
}

nv14_status nv14_state_enable_visuals(
    nv14_state *state, uint32_t timeline_frames, int auto_draw,
    int celebration_variant
)
{
    nv14_visual_tracker *visual;
    if (state == NULL || state->visual != NULL || state->frame != 0 ||
        state->phase != 0 || state->level_complete || state->player.dead ||
        memcmp(&state->player, &state->level->initial_player,
            sizeof(state->player)) != 0 ||
        celebration_variant < 0 || celebration_variant > 9 ||
        (auto_draw != 0 && auto_draw != 1))
        return NV14_STATUS_INVALID_ARGUMENT;
    visual = (nv14_visual_tracker *)calloc(1, sizeof(*visual));
    if (visual == NULL) return NV14_STATUS_OUT_OF_MEMORY;
    visual->timeline_frames = timeline_frames;
    visual->auto_draw = auto_draw;
    visual->celebration_variant = celebration_variant;
    visual->snapshot.facing = 1;
    visual->snapshot.visible = 1;
    visual->snapshot.previous_frame = 1;
    visual->snapshot.x = state->player.pos.x;
    visual->snapshot.y = state->player.pos.y;
    nv14_visual_goto(&visual->snapshot, 1, 1);
    state->visual = visual;
    return NV14_STATUS_OK;
}

nv14_status nv14_state_disable_visuals(nv14_state *state)
{
    if (state == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    if (state->phase != 0) return NV14_STATUS_PHASE_ERROR;
    free(state->visual);
    state->visual = NULL;
    return NV14_STATUS_OK;
}

int nv14_state_visuals_enabled(const nv14_state *state)
{
    return state != NULL && state->visual != NULL;
}

nv14_status nv14_state_get_visual(
    const nv14_state *state, nv14_visual_snapshot *snapshot_out
)
{
    if (state == NULL || state->visual == NULL || snapshot_out == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    if (state->phase != 0) return NV14_STATUS_PHASE_ERROR;
    *snapshot_out = state->visual->snapshot;
    return NV14_STATUS_OK;
}

nv14_status nv14_state_advance_visual_timeline(nv14_state *state, uint32_t frames)
{
    if (state == NULL || state->visual == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    if (state->phase != 0) return NV14_STATUS_PHASE_ERROR;
    nv14_visual_advance(state->visual, frames);
    return NV14_STATUS_OK;
}

nv14_status nv14_state_draw_visual(nv14_state *state)
{
    if (state == NULL || state->visual == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    if (state->phase != 0) return NV14_STATUS_PHASE_ERROR;
    nv14_visual_draw(state->visual, &state->player);
    return NV14_STATUS_OK;
}

void nv14_visual_begin_tick(nv14_visual_tracker *visual)
{
    nv14_visual_advance(visual, visual->timeline_frames);
}

void nv14_visual_state_changed(
    nv14_visual_tracker *visual, const nv14_player_snapshot *player
)
{
    nv14_visual_snapshot *s = &visual->snapshot;
    switch (player->state) {
    case NV14_PLAYER_STANDING:
        s->render_mode = NV14_RENDER_STATIC_GROUND;
        nv14_visual_goto(s, 1, 1);
        break;
    case NV14_PLAYER_RUNNING:
        s->render_mode = NV14_RENDER_RUN;
        nv14_visual_goto(s, 13, 0);
        s->run_remainder = 0.0;
        break;
    case NV14_PLAYER_SKIDDING:
        s->render_mode = NV14_RENDER_STATIC_GROUND;
        nv14_visual_goto(s, 12, 0);
        break;
    case NV14_PLAYER_JUMPING:
        s->rotation_deg = 0.0;
        s->render_mode = NV14_RENDER_IN_AIR;
        break;
    case NV14_PLAYER_FALLING:
        s->render_mode = NV14_RENDER_IN_AIR;
        break;
    case NV14_PLAYER_WALLSLIDING:
        s->render_mode = NV14_RENDER_WALLSLIDE;
        s->facing = (int32_t)-player->wall_n.x;
        s->rotation_deg = 0.0;
        nv14_visual_goto(s, 104, 0);
        break;
    default:
        break;
    }
}

void nv14_visual_relax_rotation(nv14_visual_tracker *visual)
{
    visual->snapshot.rotation_deg -= 0.1 * visual->snapshot.rotation_deg;
}

void nv14_visual_advance_run(
    nv14_visual_tracker *visual, double vx, double vy, double nx, double ny
)
{
    nv14_visual_snapshot *s = &visual->snapshot;
    double amount = fabs(vx * -ny + vy * nx) / 0.9;
    double whole;
    amount += s->run_remainder;
    if (!isfinite(amount) || s->current_frame == 0) return;
    whole = floor(amount);
    s->run_remainder = amount - whole;
    s->run_frame = 13 + (int)fmod((s->current_frame - 13) + whole, 72.0);
}

void nv14_visual_celebrate_air(nv14_visual_tracker *visual)
{
    visual->snapshot.render_mode = NV14_RENDER_IN_AIR;
}

void nv14_visual_celebrate_ground(nv14_visual_tracker *visual)
{
    nv14_visual_snapshot *s = &visual->snapshot;
    s->render_mode = NV14_RENDER_STATIC_GROUND;
    if (visual->celebration_variant != 0) {
        int animation = NV14_ANIM_CELEBRATE_NEW1 + visual->celebration_variant - 1;
        nv14_visual_goto(s, nv14_animation_starts[animation], 1);
    } else {
        s->animation = NV14_ANIM_CELEBRATE_UNRESOLVED;
        s->current_frame = 0;
        s->playing = 1;
    }
}

void nv14_visual_finish_tick(nv14_visual_tracker *visual, const nv14_state *state)
{
    nv14_visual_snapshot *s = &visual->snapshot;
    if (s->terminal) return;
    if (state->player.dead) {
        /* Gameplay deliberately stops at death. Do not invent a ragdoll pose
         * from the collision circle or alter the existing death semantics. */
        s->visible = 0;
        s->playing = 0;
        s->animation = NV14_ANIM_RAGDOLL;
        s->render_mode = NV14_RENDER_RAGDOLL;
        s->current_frame = 0;
    } else if (visual->auto_draw) {
        nv14_visual_draw(visual, &state->player);
    }
    s->terminal = (uint8_t)(state->player.dead || state->level_complete);
}

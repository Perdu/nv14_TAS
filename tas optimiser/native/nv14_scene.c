#include "nv14_scene.h"
#include "nv14_internal.h"
#include "nv14_objects_basic.h"
#include "nv14_objects_guard.h"
#include "nv14_objects_ranged.h"
#include "nv14_objects_drones.h"
#include "nv14_drone_weapons.h"

#include <math.h>
#include <string.h>

size_t nv14_scene_object_count(const nv14_state *state)
{
    return state == NULL ? 0 : state->level->native_object_count;
}

const char *nv14_scene_kind_name(int kind)
{
    static const char *names[] = {
        "gold", "mine", "exit_switch", "exit_door", "oneway", "launch",
        "bounce", "thwomp", "testdoor", "turret", "homing", "floorguard",
        "drone_zap", "drone_laser", "drone_chaingun"
    };
    return kind < 0 || kind >= 15 ? "unknown" : names[kind];
}

nv14_status nv14_scene_object_at(
    const nv14_state *state, size_t object_index, nv14_scene_object *out
)
{
    const nv14_native_object *object;
    nv14_status status;
    if (state == NULL || out == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    if (object_index >= state->level->native_object_count)
        return NV14_STATUS_OUT_OF_BOUNDS;
    object = &state->level->native_objects[object_index];
    memset(out, 0, sizeof(*out));
    out->id = object_index;
    out->kind = object->kind;
    out->state_index = object->state_index;
    out->descriptor = state->level->descriptors[object->load_index];
    out->position.x = out->base_position.x = object->x;
    out->position.y = out->base_position.y = object->y;
    out->radius = object->r;
    out->direction.x = object->a;
    out->direction.y = object->b;
    out->active = out->visible = 1;
    out->updating = state->update_active[object_index] != 0;
    out->thinking = state->thinker_active[object_index] != 0;
    out->grid_active = state->object_cell_slot[object_index] >= 0;
    out->mode = -1;
    out->weapon_type = -1;
    if (object->kind == NV14_NATIVE_GOLD) {
        out->active = out->visible = !nv14_internal_mask_test(
            state->collected_gold, object->state_index);
    } else if (object->kind == NV14_NATIVE_MINE) {
        out->active = out->visible = !nv14_internal_mask_test(
            state->exploded_mine, object->state_index);
    } else if (object->kind == NV14_NATIVE_EXIT_SWITCH ||
               object->kind == NV14_NATIVE_EXIT_DOOR) {
        out->is_open = nv14_internal_mask_test(state->open_exit, object->state_index);
        if (object->kind == NV14_NATIVE_EXIT_SWITCH)
            out->active = !out->is_open;
        else
            out->active = out->is_open;
    } else if (object->kind >= NV14_NATIVE_BOUNCE &&
               object->kind <= NV14_NATIVE_TESTDOOR) {
        nv14_basic_scene_snapshot basic;
        status = nv14_objects_basic_scene_at(state, object_index, &basic);
        if (status != NV14_STATUS_OK) return status;
        out->position = basic.position;
        out->previous_position = basic.previous_position;
        out->direction = basic.direction;
        out->door_position = basic.door_position;
        out->mode = basic.mode;
        out->asleep = basic.asleep;
        out->moving = basic.moving;
        out->is_open = basic.is_open;
        out->is_locked = basic.is_locked;
        out->is_trap = basic.is_trap;
        out->trigger_active = basic.trigger_active;
        out->horizontal = basic.horizontal;
    } else if (object->kind == NV14_NATIVE_FLOORGUARD) {
        nv14_guard_scene_snapshot guard;
        status = nv14_objects_guard_scene_at(state, object_index, &guard);
        if (status != NV14_STATUS_OK) return status;
        out->position = guard.position;
        out->direction.x = guard.direction;
        out->direction.y = 0.0;
        out->chasing = guard.chasing;
    } else if (object->kind == NV14_NATIVE_TURRET ||
               object->kind == NV14_NATIVE_HOMING) {
        nv14_ranged_snapshot ranged;
        status = nv14_objects_ranged_snapshot(state, object->load_index, &ranged);
        if (status != NV14_STATUS_OK) return status;
        out->mode = ranged.mode;
        out->view = ranged.view;
        out->target = ranged.target;
        out->aim = ranged.aim;
        out->direction = ranged.direction;
        out->speed = ranged.speed;
        out->shot_timer = ranged.shot_timer;
        out->fire_delay_timer = ranged.fire_delay_timer;
        if (object->kind == NV14_NATIVE_HOMING) {
            out->rocket_position = ranged.position;
            out->rocket_visible = ranged.mode == NV14_RANGED_HOMING_ACTIVE;
            out->rocket_rotation_deg = atan2(ranged.direction.y, ranged.direction.x)
                / 0.0174532925199433;
        } else {
            out->crosshair_visible = ranged.mode != NV14_RANGED_TURRET_WAITING;
            /* POSTFIRE alone does not prove a shot: LOS can cancel Fire().
             * Do not invent a gauss beam without retained event history. */
        }
    } else if (object->kind >= NV14_NATIVE_DRONE_ZAP &&
               object->kind <= NV14_NATIVE_DRONE_CHAINGUN) {
        nv14_drone_snapshot drone;
        status = nv14_objects_drones_snapshot(state, object->load_index, &drone);
        if (status != NV14_STATUS_OK) return status;
        out->position = drone.position;
        out->goal = drone.goal;
        out->mode = drone.mode;
        out->speed = drone.speed;
        out->chasing = drone.is_chasing;
        out->direction_index = drone.current_direction;
        out->weapon_type = drone.weapon_type;
        if (drone.current_direction == 0) out->direction.x = 1.0;
        else if (drone.current_direction == 1) out->direction.y = 1.0;
        else if (drone.current_direction == 2) out->direction.x = -1.0;
        else if (drone.current_direction == 3) out->direction.y = -1.0;
        if (drone.weapon_type != NV14_DRONE_WEAPON_ZAP) {
            nv14_drone_weapon_snapshot weapon;
            status = nv14_drone_weapons_snapshot(state, object->load_index, &weapon);
            if (status != NV14_STATUS_OK) return status;
            out->view = weapon.view;
            out->target = weapon.target;
            out->vector = weapon.vector;
            out->shot_target = weapon.shot_target;
            out->fire_delay_timer = weapon.fire_delay_timer;
            out->weapon_timer = weapon.weapon_timer;
            out->shot_index = weapon.current_shot_index;
            out->maximum_shot_index = weapon.maximum_shot_index;
            if (drone.weapon_type == NV14_DRONE_WEAPON_LASER) {
                out->beam_end = weapon.target;
                /* The engine changes its length slot from length to length²
                 * while firing. Export a consistent geometric length. */
                out->laser_length = hypot(weapon.vector.x, weapon.vector.y);
                out->beam_visible = drone.mode == NV14_DRONE_MODE_FIRING;
            } else {
                out->beam_end = weapon.view;
                /* A firing shot resets weapon_timer and increments the shot
                 * index. Include a lethal last shot's POSTFIRE transition. */
                out->shot_visible = weapon.weapon_timer == 0 &&
                    weapon.current_shot_index > 0 &&
                    (drone.mode == NV14_DRONE_MODE_FIRING ||
                     (drone.mode == NV14_DRONE_MODE_POSTFIRE && state->player.dead));
            }
        }
    }
    return NV14_STATUS_OK;
}

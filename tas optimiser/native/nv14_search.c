/* Generic native replay-search kernel.  See nv14_search.h. */

#include "nv14_search.h"

#include "nv14_internal.h"
#include "nv14_objects_basic.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct nv14_seen_entry {
    uint64_t hash;
    size_t key_size;
    unsigned char *key;
    uint8_t used;
} nv14_seen_entry;

typedef struct nv14_seen_set {
    nv14_seen_entry *entries;
    size_t capacity;
    size_t count;
} nv14_seen_set;

typedef struct nv14_search_context {
    const nv14_level *level;
    const nv14_search_spec *spec;
    nv14_search_result *result;
    nv14_seen_set seen;
    nv14_state **state_pool;
    size_t state_pool_count;
    nv14_input *chosen;
    uint8_t *missing_stack;
    uint8_t *candidate_missing_requirements;
    uint8_t *candidate_violated_avoidances;
    uint8_t *physics_jump_edges;
    uint64_t poll_counter;
    uint64_t next_poll;
    int budget_exhausted;
    nv14_search_status status;
    nv14_error core_error;
} nv14_search_context;

typedef struct nv14_pattern_search_context {
    const nv14_level *level;
    const nv14_pattern_search_spec *spec;
    nv14_pattern_search_result *result;
    nv14_seen_set seen;
    nv14_state **walking_states;
    nv14_state **hold_states;
    nv14_state *tail_state;
    nv14_pattern_span *path;
    size_t run_count_limit;
    uint64_t poll_counter;
    uint64_t next_poll;
    uint64_t root_branch_ordinal;
    uint64_t feasible_ordinal;
    nv14_search_status status;
    nv14_error core_error;
} nv14_pattern_search_context;

static void nv14_search_set_error(
    nv14_error *error_out,
    nv14_status code,
    const char *message
)
{
    if (error_out == NULL) return;
    memset(error_out, 0, sizeof(*error_out));
    error_out->code = code;
    error_out->object_type = -1;
    error_out->tile_id = -1;
    error_out->tile_i = -1;
    error_out->tile_j = -1;
    if (message != NULL)
        (void)snprintf(error_out->message, sizeof(error_out->message), "%s", message);
}

static int nv14_search_size_product(size_t a, size_t b, size_t *out)
{
    if (b != 0 && a > SIZE_MAX / b) return 0;
    *out = a * b;
    return 1;
}

static int nv14_search_input_equal(nv14_input a, nv14_input b)
{
    return a.left == b.left && a.right == b.right &&
        a.jump == b.jump && a.jump_trigger == b.jump_trigger;
}

static int nv14_search_flags_subset(
    const uint8_t *candidate,
    const uint8_t *reference,
    size_t count
)
{
    size_t index;
    for (index = 0; index < count; ++index) {
        if (candidate[index] != 0 && reference[index] == 0) return 0;
    }
    return 1;
}

static int nv14_search_flags_equal(
    const uint8_t *left,
    const uint8_t *right,
    size_t count
)
{
    return count == 0 || memcmp(left, right, count) == 0;
}

static int nv14_search_flags_any(const uint8_t *flags, size_t count)
{
    size_t index;
    for (index = 0; index < count; ++index) {
        if (flags[index] != 0) return 1;
    }
    return 0;
}

static int nv14_search_flags_canonical(const uint8_t *flags, size_t count)
{
    size_t index;
    for (index = 0; index < count; ++index) {
        if (flags[index] > 1u) return 0;
    }
    return 1;
}

static uint64_t nv14_search_read_u64_le(const unsigned char *bytes)
{
    return (uint64_t)bytes[0] |
        ((uint64_t)bytes[1] << 8) |
        ((uint64_t)bytes[2] << 16) |
        ((uint64_t)bytes[3] << 24) |
        ((uint64_t)bytes[4] << 32) |
        ((uint64_t)bytes[5] << 40) |
        ((uint64_t)bytes[6] << 48) |
        ((uint64_t)bytes[7] << 56);
}

static uint64_t nv14_search_rotl64(uint64_t value, unsigned int bits)
{
    return (value << bits) | (value >> (64u - bits));
}

static uint64_t nv14_search_hash_bytes(
    const unsigned char *bytes,
    size_t size
)
{
    /* Deduplication retains and compares every exact key, so the hash only
       chooses a probe sequence.  Mix eight bytes at a time to avoid the long
       byte-wise dependency chain of FNV-1a on large mutable-object states. */
    const uint64_t prime1 = UINT64_C(11400714785074694791);
    const uint64_t prime2 = UINT64_C(14029467366897019727);
    const uint64_t prime4 = UINT64_C(9650029242287828579);
    const uint64_t prime5 = UINT64_C(2870177450012600261);
    uint64_t hash = prime5 + (uint64_t)size;
    while (size >= 8u) {
        uint64_t mixed = nv14_search_read_u64_le(bytes) * prime2;
        mixed = nv14_search_rotl64(mixed, 31u) * prime1;
        hash ^= mixed;
        hash = nv14_search_rotl64(hash, 27u) * prime1 + prime4;
        bytes += 8u;
        size -= 8u;
    }
    while (size-- != 0) {
        hash ^= (uint64_t)*bytes++ * prime5;
        hash = nv14_search_rotl64(hash, 11u) * prime1;
    }
    hash ^= hash >> 33;
    hash *= prime2;
    hash ^= hash >> 29;
    hash *= UINT64_C(1609587929392839161);
    hash ^= hash >> 32;
    /* A zero hash is valid because entries carry an explicit used flag. */
    return hash;
}

static void nv14_seen_destroy(nv14_seen_set *set)
{
    size_t index;
    if (set == NULL) return;
    if (set->entries != NULL) {
        for (index = 0; index < set->capacity; ++index)
            free(set->entries[index].key);
        free(set->entries);
    }
    memset(set, 0, sizeof(*set));
}

static int nv14_seen_grow(nv14_seen_set *set)
{
    size_t new_capacity = set->capacity == 0 ? 1024u : set->capacity * 2u;
    nv14_seen_entry *new_entries;
    size_t index;
    if (new_capacity < set->capacity ||
        new_capacity > SIZE_MAX / sizeof(*new_entries))
        return 0;
    new_entries = (nv14_seen_entry *)calloc(new_capacity, sizeof(*new_entries));
    if (new_entries == NULL) return 0;
    for (index = 0; index < set->capacity; ++index) {
        nv14_seen_entry entry = set->entries[index];
        size_t slot;
        if (!entry.used) continue;
        slot = (size_t)entry.hash & (new_capacity - 1u);
        while (new_entries[slot].used)
            slot = (slot + 1u) & (new_capacity - 1u);
        new_entries[slot] = entry;
    }
    free(set->entries);
    set->entries = new_entries;
    set->capacity = new_capacity;
    return 1;
}

/* Consume an allocated key. Return 1 for an existing exact key, 0 for a new
   insertion, and -1 on OOM. */
static int nv14_seen_insert_owned(
    nv14_seen_set *set,
    unsigned char *key,
    size_t key_size
)
{
    uint64_t hash = nv14_search_hash_bytes(key, key_size);
    size_t slot;
    if (set->capacity == 0 || (set->count + 1u) * 10u >= set->capacity * 7u) {
        if (!nv14_seen_grow(set)) {
            free(key);
            return -1;
        }
    }
    slot = (size_t)hash & (set->capacity - 1u);
    while (set->entries[slot].used) {
        nv14_seen_entry *entry = &set->entries[slot];
        if (entry->hash == hash && entry->key_size == key_size &&
            memcmp(entry->key, key, key_size) == 0) {
            free(key);
            return 1;
        }
        slot = (slot + 1u) & (set->capacity - 1u);
    }
    set->entries[slot].used = 1;
    set->entries[slot].hash = hash;
    set->entries[slot].key_size = key_size;
    set->entries[slot].key = key;
    ++set->count;
    return 0;
}

/* Return 1 for an existing exact key, 0 for a newly inserted key, -1 on OOM,
   and -2 when the core could not serialize the state. */
static int nv14_seen_test_and_insert(
    nv14_seen_set *set,
    const nv14_state *state,
    size_t logical_frame,
    const uint8_t *missing_jumps,
    size_t missing_jump_count
)
{
    size_t state_size = nv14_state_key_size(state, -1);
    size_t key_size;
    size_t written = 0;
    unsigned char *key;
    nv14_status status;
    if (state_size == 0 || state_size > SIZE_MAX - missing_jump_count ||
        state_size + missing_jump_count > SIZE_MAX - sizeof(logical_frame))
        return -2;
    key_size = state_size + missing_jump_count + sizeof(logical_frame);
    key = (unsigned char *)malloc(key_size == 0 ? 1u : key_size);
    if (key == NULL) return -1;
    status = nv14_state_write_key(state, -1, key, state_size, &written);
    if (status != NV14_STATUS_OK || written != state_size) {
        free(key);
        return -2;
    }
    if (missing_jump_count != 0)
        memcpy(key + state_size, missing_jumps, missing_jump_count);
    /* Identical emulator states reached before different replay frames are not
       interchangeable: the remaining fixed suffix and mutable choices differ.
       Keep the logical frame in the exact key, matching the v2.73 Python DFS. */
    memcpy(key + state_size + missing_jump_count,
        &logical_frame, sizeof(logical_frame));
    return nv14_seen_insert_owned(set, key, key_size);
}

static int nv14_search_poll(nv14_search_context *context)
{
    uint64_t interval;
    ++context->poll_counter;
    if (context->spec->cancel == NULL) return 1;
    interval = context->spec->cancel_poll_interval;
    if (interval == 0) interval = UINT64_C(16384);
    if (context->poll_counter < context->next_poll) return 1;
    context->next_poll = context->poll_counter + interval;
    if (context->spec->cancel(context->spec->cancel_userdata)) {
        context->status = NV14_SEARCH_CANCELLED;
        return 0;
    }
    return 1;
}

static nv14_state *nv14_search_clone(
    nv14_search_context *context,
    const nv14_state *source
)
{
    nv14_error error;
    nv14_state *result;
    result = nv14_state_clone(source, &error);
    if (result == NULL) {
        context->status = error.code == NV14_STATUS_OUT_OF_MEMORY
            ? NV14_SEARCH_OUT_OF_MEMORY : NV14_SEARCH_CORE_ERROR;
        context->core_error = error;
        return NULL;
    }
    ++context->result->stats.cloned_states;
    return result;
}

static int nv14_search_copy_state(
    nv14_search_context *context,
    nv14_state *destination,
    const nv14_state *source
)
{
    nv14_error error;
    nv14_status status;
    status = nv14_state_copy_into(destination, source, &error);
    if (status != NV14_STATUS_OK) {
        context->status = status == NV14_STATUS_OUT_OF_MEMORY
            ? NV14_SEARCH_OUT_OF_MEMORY : NV14_SEARCH_CORE_ERROR;
        context->core_error = error;
        return 0;
    }
    ++context->result->stats.cloned_states;
    return 1;
}

static int nv14_search_step(
    nv14_search_context *context,
    nv14_state *state,
    nv14_input input,
    nv14_step_result *result_out
)
{
    nv14_status status;
    if (context->spec->max_simulated_ticks != 0 &&
        context->result->stats.simulated_ticks >=
            context->spec->max_simulated_ticks) {
        context->budget_exhausted = 1;
        context->result->budget_exhausted = 1;
        return 0;
    }
    memset(result_out, 0, sizeof(*result_out));
    status = nv14_state_step(state, input, result_out);
    ++context->result->stats.simulated_ticks;
    if (!nv14_search_poll(context)) return 0;
    if (status != NV14_STATUS_OK || result_out->unsupported) {
        context->status = NV14_SEARCH_CORE_ERROR;
        nv14_search_set_error(
            &context->core_error,
            status == NV14_STATUS_OK ? NV14_STATUS_UNSUPPORTED_OBJECTS : status,
            result_out->unsupported
                ? "search encountered an unsupported native object"
                : nv14_status_string(status)
        );
        return 0;
    }
    return 1;
}

static int nv14_search_interaction_atom_satisfied(
    const nv14_state *state,
    const nv14_search_interaction_atom *atom
)
{
    int locked_open = 0;
    int trap_triggered = 0;
    if (atom->kind == NV14_SEARCH_INTERACTION_GOLD) {
        return atom->index < state->level->gold_count &&
            nv14_internal_mask_test(state->collected_gold, atom->index);
    }
    if (atom->kind == NV14_SEARCH_INTERACTION_EXIT_SWITCH) {
        return atom->index < state->level->exit_count &&
            nv14_internal_mask_test(state->open_exit, atom->index);
    }
    if (atom->kind == NV14_SEARCH_INTERACTION_LOCKED_DOOR ||
        atom->kind == NV14_SEARCH_INTERACTION_TRAPDOOR) {
        if (atom->index > UINT32_MAX) return 0;
        nv14_status status = nv14_objects_basic_door_interactions(
            state,
            (uint32_t)atom->index,
            &locked_open,
            &trap_triggered
        );
        if (status != NV14_STATUS_OK) return 0;
        return atom->kind == NV14_SEARCH_INTERACTION_LOCKED_DOOR
            ? locked_open : trap_triggered;
    }
    return 0;
}

static int nv14_search_group_satisfied(
    const nv14_state *state,
    const nv14_search_interaction_atom *atoms,
    const nv14_search_interaction_group *group
)
{
    size_t index;
    for (index = 0; index < group->atom_count; ++index) {
        if (nv14_search_interaction_atom_satisfied(
                state, &atoms[group->first_atom + index]))
            return 1;
    }
    return 0;
}

static int nv14_search_any_avoidance_triggered(
    const nv14_search_context *context,
    const nv14_state *state
)
{
    const nv14_search_spec *spec = context->spec;
    size_t index;
    for (index = 0; index < spec->avoided_group_count; ++index) {
        if (nv14_search_group_satisfied(
                state, spec->avoided_atoms, &spec->avoided_groups[index]))
            return 1;
    }
    return 0;
}

static void nv14_search_terminal_interactions(
    nv14_search_context *context,
    const nv14_state *state
)
{
    const nv14_search_spec *spec = context->spec;
    size_t index;
    for (index = 0; index < spec->required_group_count; ++index) {
        context->candidate_missing_requirements[index] =
            !nv14_search_group_satisfied(
                state, spec->required_atoms, &spec->required_groups[index]);
    }
    for (index = 0; index < spec->avoided_group_count; ++index) {
        context->candidate_violated_avoidances[index] =
            nv14_search_group_satisfied(
                state, spec->avoided_atoms, &spec->avoided_groups[index]);
    }
}

static size_t nv14_search_required_jump_index(
    const nv14_search_spec *spec,
    size_t frame
)
{
    size_t low = 0;
    size_t high = spec->required_jump_count;
    while (low < high) {
        size_t middle = low + (high - low) / 2u;
        size_t value = spec->required_jump_frames[middle];
        if (value < frame) low = middle + 1u;
        else high = middle;
    }
    if (low < spec->required_jump_count &&
        spec->required_jump_frames[low] == frame)
        return low;
    return SIZE_MAX;
}

static int nv14_search_jump_frame_ignored(
    const nv14_search_spec *spec,
    size_t frame
)
{
    size_t low = 0;
    size_t high = spec->ignored_jump_count;
    while (low < high) {
        size_t middle = low + (high - low) / 2u;
        if (spec->ignored_jump_frames[middle] < frame) low = middle + 1u;
        else high = middle;
    }
    return low < spec->ignored_jump_count &&
        spec->ignored_jump_frames[low] == frame;
}

/* Update direction-search jump state after one exact step.  Return 0 when the
   step introduced a newly missed jump and the branch must be pruned. */
static int nv14_search_update_required_jump(
    nv14_search_context *context,
    size_t frame,
    const nv14_step_result *step_result,
    uint8_t *missing
)
{
    size_t index = nv14_search_required_jump_index(context->spec, frame);
    if (index == SIZE_MAX) return 1;
    if (context->spec->required_jump_any) {
        if (step_result->jumped &&
            !nv14_search_jump_frame_ignored(context->spec, frame))
            memset(missing, 0, context->spec->required_jump_count);
        return 1;
    }
    if (step_result->jumped) {
        if (nv14_search_jump_frame_ignored(context->spec, frame)) return 1;
        missing[index] = 0;
        return 1;
    }
    if (context->spec->incumbent_missing_jumps[index] == 0) {
        ++context->result->stats.missed_jump_prunes;
        return 0;
    }
    missing[index] = 1;
    return 1;
}

static int nv14_search_frame_is_mutable(
    const nv14_search_spec *spec,
    size_t frame
)
{
    size_t low = 0;
    size_t high = spec->mutable_count;
    while (low < high) {
        size_t middle = low + (high - low) / 2u;
        if (spec->mutable_frames[middle] < frame) low = middle + 1u;
        else high = middle;
    }
    return low < spec->mutable_count && spec->mutable_frames[low] == frame;
}

static int nv14_search_preserve_failed_press(
    const nv14_search_spec *spec,
    size_t frame
)
{
    size_t next = frame + 1u;
    return next > frame && next <= spec->target_frame &&
        !nv14_search_frame_is_mutable(spec, next) && spec->replay[next].jump;
}

static size_t nv14_search_popcount_u64(uint64_t value)
{
    size_t count = 0;
    while (value != 0) {
        value &= value - UINT64_C(1);
        ++count;
    }
    return count;
}

static size_t nv14_search_mask_difference_count(
    const uint64_t *left,
    size_t left_count,
    const uint64_t *right,
    size_t right_count
)
{
    size_t count = left_count > right_count ? left_count : right_count;
    size_t index;
    size_t differences = 0;
    for (index = 0; index < count; ++index) {
        uint64_t left_word = index < left_count ? left[index] : 0;
        uint64_t right_word = index < right_count ? right[index] : 0;
        differences += nv14_search_popcount_u64(left_word ^ right_word);
    }
    return differences;
}

static int nv14_search_mask_test_words(
    const uint64_t *words,
    size_t word_count,
    size_t index
)
{
    size_t word = index >> 6;
    return word < word_count &&
        (words[word] & (UINT64_C(1) << (index & 63u))) != 0;
}

static int nv14_search_sign_bin(double value)
{
    return value < -1e-9 ? -1 : value > 1e-9 ? 1 : 0;
}

static size_t nv14_search_door_mask_difference_count(
    const nv14_state *state,
    const uint64_t *target,
    size_t target_word_count,
    int trapdoor
)
{
    size_t differences = nv14_search_mask_difference_count(
        NULL, 0, target, target_word_count);
    size_t object_index;
    for (object_index = 0;
         object_index < state->level->native_object_count;
         ++object_index) {
        const nv14_native_object *object =
            &state->level->native_objects[object_index];
        int locked_open = 0;
        int trap_triggered = 0;
        int actual;
        int expected;
        if (object->kind != NV14_NATIVE_TESTDOOR) continue;
        if (nv14_objects_basic_door_interactions_at(
                state,
                object_index,
                &locked_open,
                &trap_triggered) != NV14_STATUS_OK)
            continue;
        actual = trapdoor ? trap_triggered : locked_open;
        if (!actual) continue;
        expected = nv14_search_mask_test_words(
            target, target_word_count, object->load_index);
        if (expected) --differences;
        else ++differences;
    }
    return differences;
}

double nv14_search_trace_distance(
    const nv14_search_trace_target *target,
    const nv14_state *state
)
{
    const nv14_player_snapshot *player = &state->player;
    double x = player->pos.x;
    double y = player->pos.y;
    double vx = player->pos.x - player->oldpos.x;
    double vy = player->pos.y - player->oldpos.y;
    double dx = x - target->x;
    double dy = y - target->y;
    double dvx = vx - target->vx;
    double dvy = vy - target->vy;
    int wall_x = nv14_search_sign_bin(player->wall_n.x);
    int floor_x = nv14_search_sign_bin(player->floor_n.x);
    int floor_y = nv14_search_sign_bin(player->floor_n.y);
    int contact_matches =
        player->state == target->player_state &&
        (player->in_air != 0) == (target->in_air != 0) &&
        (player->near_wall != 0) == (target->near_wall != 0) &&
        wall_x == target->wall_x &&
        floor_x == target->floor_x &&
        floor_y == target->floor_y &&
        (player->previous_jump_held != 0) ==
            (target->previous_jump_held != 0);
    double static_penalty = target->gold_bit_penalty * (double)
        nv14_search_mask_difference_count(
            state->collected_gold,
            (state->level->gold_count + 63u) / 64u,
            target->collected_gold,
            target->collected_gold_word_count);
    static_penalty += target->mine_bit_penalty * (double)
        nv14_search_mask_difference_count(
            state->exploded_mine,
            (state->level->mine_count + 63u) / 64u,
            target->exploded_mine,
            target->exploded_mine_word_count);
    double contact_penalty = contact_matches
        ? 0.0 : target->contact_mismatch_penalty;
    static_penalty += target->exit_bit_penalty * (double)
        nv14_search_mask_difference_count(
        state->open_exit,
        (state->level->exit_count + 63u) / 64u,
        target->open_exit,
        target->open_exit_word_count);
    static_penalty += target->locked_door_bit_penalty * (double)
        nv14_search_door_mask_difference_count(
        state,
        target->opened_locked_door,
        target->opened_locked_door_word_count,
        0);
    static_penalty += target->trapdoor_bit_penalty * (double)
        nv14_search_door_mask_difference_count(
        state,
        target->triggered_trapdoor,
        target->triggered_trapdoor_word_count,
        1);
    if ((player->in_air != 0) != (target->in_air != 0))
        contact_penalty += target->in_air_mismatch_penalty;
    if ((player->near_wall != 0) != (target->near_wall != 0))
        contact_penalty += target->near_wall_mismatch_penalty;
    return target->position_weight * (dx * dx + dy * dy) +
        target->velocity_weight * (dvx * dvx + dvy * dvy) +
        contact_penalty + static_penalty;
}

static double nv14_search_score(
    const nv14_search_spec *spec,
    const nv14_state *state
)
{
    double x = state->player.pos.x;
    double y = state->player.pos.y;
    size_t index;
    if (spec->objective == NV14_SEARCH_MAX_X) return x;
    if (spec->objective == NV14_SEARCH_MIN_X) return -x;
    if (spec->objective == NV14_SEARCH_MAX_Y) return y;
    if (spec->objective == NV14_SEARCH_MIN_Y) return -y;
    if (spec->objective == NV14_SEARCH_MIN_DISTANCE) {
        double best = INFINITY;
        for (index = 0; index < spec->target_count; ++index) {
            double dx = x - spec->targets[index].x;
            double dy = y - spec->targets[index].y;
            double distance = dx * dx + dy * dy;
            if (distance < best) best = distance;
        }
        return -best;
    }
    if (spec->objective == NV14_SEARCH_TRACE_DISTANCE)
        return -nv14_search_trace_distance(spec->trace_target, state);
    if (spec->objective == NV14_SEARCH_CONSTANT) return 0.0;
    return -INFINITY;
}

static int nv14_search_position_feasible(
    const nv14_search_spec *spec,
    const nv14_state *state
)
{
    double x = state->player.pos.x;
    double y = state->player.pos.y;
    return (!spec->has_x_window ||
            (x >= spec->x_minimum && x <= spec->x_maximum)) &&
        (!spec->has_y_window ||
            (y >= spec->y_minimum && y <= spec->y_maximum));
}

static unsigned int nv14_search_input_key(nv14_input input)
{
    return (unsigned int)(input.left != 0) |
        ((unsigned int)(input.right != 0) << 1) |
        ((unsigned int)(input.jump != 0) << 2);
}

static int nv14_search_candidate_tie_better(
    const nv14_search_context *context
)
{
    const nv14_search_spec *spec = context->spec;
    const nv14_search_result *best = context->result;
    size_t candidate_edits = 0;
    size_t best_edits = 0;
    size_t index;
    for (index = 0; index < spec->mutable_count; ++index) {
        nv14_input source = spec->replay[spec->mutable_frames[index]];
        if (!nv14_search_input_equal(context->chosen[index], source))
            ++candidate_edits;
        if (!nv14_search_input_equal(best->best_inputs[index], source))
            ++best_edits;
    }
    if (candidate_edits != best_edits)
        return candidate_edits < best_edits;
    for (index = 0; index < spec->mutable_count; ++index) {
        unsigned int candidate_key =
            nv14_search_input_key(context->chosen[index]);
        unsigned int best_key = nv14_search_input_key(best->best_inputs[index]);
        if (candidate_key != best_key) return candidate_key < best_key;
    }
    return 0;
}

static int nv14_search_candidate_better(
    const nv14_search_context *context,
    double score,
    int feasible,
    const uint8_t *missing_requirements,
    const uint8_t *violated_avoidances,
    const uint8_t *missing_jumps
)
{
    const nv14_search_spec *spec = context->spec;
    const nv14_search_result *best = context->result;
    int candidate_dominates;
    int best_dominates;
    if (!feasible) return 0;
    if (!nv14_search_flags_subset(
            missing_requirements,
            spec->incumbent_missing_requirements,
            spec->required_group_count) ||
        !nv14_search_flags_subset(
            violated_avoidances,
            spec->incumbent_violated_avoidances,
            spec->avoided_group_count) ||
        !nv14_search_flags_subset(
            missing_jumps,
            spec->incumbent_missing_jumps,
            spec->required_jump_count))
        return 0;
    if (!best->feasible) return 1;

    candidate_dominates =
        nv14_search_flags_subset(
            missing_requirements,
            best->missing_requirements,
            spec->required_group_count) &&
        nv14_search_flags_subset(
            violated_avoidances,
            best->violated_avoidances,
            spec->avoided_group_count) &&
        nv14_search_flags_subset(
            missing_jumps,
            best->missing_jumps,
            spec->required_jump_count);
    best_dominates =
        nv14_search_flags_subset(
            best->missing_requirements,
            missing_requirements,
            spec->required_group_count) &&
        nv14_search_flags_subset(
            best->violated_avoidances,
            violated_avoidances,
            spec->avoided_group_count) &&
        nv14_search_flags_subset(
            best->missing_jumps,
            missing_jumps,
            spec->required_jump_count);
    if (candidate_dominates && !best_dominates) return 1;
    if (best_dominates && !candidate_dominates) return 0;
    if (!candidate_dominates || !best_dominates) return 0;
    if (score > best->score) return 1;
    if (score < best->score) return 0;
    return spec->tie_break_low_edit_lex &&
        nv14_search_candidate_tie_better(context);
}

static void nv14_search_save_candidate(
    nv14_search_context *context,
    const nv14_state *state,
    double score,
    const uint8_t *missing_jumps
)
{
    const nv14_search_spec *spec = context->spec;
    nv14_search_result *result = context->result;
    result->improved = 1;
    result->feasible = 1;
    result->score = score;
    if (spec->mutable_count != 0)
        memcpy(result->best_inputs, context->chosen,
            spec->mutable_count * sizeof(*result->best_inputs));
    if (spec->required_group_count != 0)
        memcpy(result->missing_requirements,
            context->candidate_missing_requirements,
            spec->required_group_count);
    if (spec->avoided_group_count != 0)
        memcpy(result->violated_avoidances,
            context->candidate_violated_avoidances,
            spec->avoided_group_count);
    if (spec->required_jump_count != 0)
        memcpy(result->missing_jumps, missing_jumps,
            spec->required_jump_count);
    result->player = state->player;
    result->has_player_snapshot = 1;
}

static int nv14_search_horizontal_interval_can_improve(
    const nv14_search_spec *spec,
    double lower,
    double upper,
    double best_score
)
{
    double feasible_low = lower;
    double feasible_high = upper;
    if (spec->has_x_window) {
        if (feasible_low < spec->x_minimum) feasible_low = spec->x_minimum;
        if (feasible_high > spec->x_maximum) feasible_high = spec->x_maximum;
        if (feasible_low > feasible_high) return 0;
    }
    if (isinf(best_score) && best_score < 0.0) return 1;
    if (spec->objective == NV14_SEARCH_MAX_X)
        return feasible_high > best_score;
    if (spec->objective == NV14_SEARCH_MIN_X)
        return -feasible_low > best_score;
    return 1;
}

static void nv14_search_loose_horizontal_bounds(
    const nv14_search_context *context,
    const nv14_state *state,
    size_t logical_frame,
    double *lower_out,
    double *upper_out
)
{
    const nv14_search_spec *spec = context->spec;
    const nv14_player_snapshot *player = &state->player;
    size_t remaining = logical_frame <= spec->target_frame
        ? spec->target_frame + 1u - logical_frame : 0u;
    size_t frame;
    size_t edges = 0;
    double x = player->pos.x;
    double vx;
    double base_speed;
    double jump_dx;
    double displacement;
    if (remaining == 0) {
        *lower_out = x;
        *upper_out = x;
        return;
    }
    for (frame = logical_frame; frame <= spec->target_frame; ++frame)
        edges += context->physics_jump_edges[frame] != 0;
    jump_dx = 1.5 * player->jump_amt;
    vx = player->pos.x - player->oldpos.x;
    base_speed = player->maxspeed_ground;
    if (player->maxspeed_air > base_speed) base_speed = player->maxspeed_air;
    if (fabs(vx) > base_speed) base_speed = fabs(vx);
    displacement = (double)remaining * (base_speed + (double)edges * jump_dx) +
        (double)edges * jump_dx;
    *lower_out = x - displacement;
    *upper_out = x + displacement;
}

static double nv14_search_project_horizontal(
    const nv14_search_context *context,
    const nv14_state *state,
    size_t logical_frame,
    int direction
)
{
    const nv14_search_spec *spec = context->spec;
    const nv14_player_snapshot *player = &state->player;
    double x = player->pos.x;
    double velocity = player->pos.x - player->oldpos.x;
    double max_speed = player->maxspeed_ground > player->maxspeed_air
        ? player->maxspeed_ground : player->maxspeed_air;
    double acceleration = 2.0 * player->ground_accel;
    double jump_dx = 1.5 * player->jump_amt;
    size_t frame;
    for (frame = logical_frame; frame <= spec->target_frame; ++frame) {
        velocity *= player->d;
        x += velocity;
        if (direction > 0) {
            if (velocity < max_speed) {
                velocity += acceleration;
                if (velocity > max_speed) velocity = max_speed;
            }
        } else if (velocity > -max_speed) {
            velocity -= acceleration;
            if (velocity < -max_speed) velocity = -max_speed;
        }
        if (context->physics_jump_edges[frame]) {
            x += (double)direction * jump_dx;
            if (direction > 0) {
                double boosted = velocity + jump_dx;
                velocity = boosted > jump_dx ? boosted : jump_dx;
            } else {
                double boosted = velocity - jump_dx;
                velocity = boosted < -jump_dx ? boosted : -jump_dx;
            }
        }
    }
    return x;
}

static int nv14_search_physics_allows(
    const nv14_search_context *context,
    const nv14_state *state,
    size_t logical_frame,
    const uint8_t *missing_jumps
)
{
    const nv14_search_spec *spec = context->spec;
    const nv14_search_result *best = context->result;
    double best_score = best->score;
    double loose_low;
    double loose_high;
    double projected_left;
    double projected_right;
    double tight_low;
    double tight_high;
    int missing_strictly_better;
    if (!spec->physics_prune) return 1;
    if (spec->objective != NV14_SEARCH_MAX_X &&
        spec->objective != NV14_SEARCH_MIN_X && !spec->has_x_window)
        return 1;
    missing_strictly_better =
        nv14_search_flags_subset(
            missing_jumps, best->missing_jumps, spec->required_jump_count) &&
        !nv14_search_flags_equal(
            missing_jumps, best->missing_jumps, spec->required_jump_count);
    if (!best->feasible || nv14_search_flags_any(
            best->missing_requirements, spec->required_group_count) ||
        nv14_search_flags_any(
            best->violated_avoidances, spec->avoided_group_count) ||
        missing_strictly_better)
        best_score = -INFINITY;
    nv14_search_loose_horizontal_bounds(
        context, state, logical_frame, &loose_low, &loose_high);
    if (!nv14_search_horizontal_interval_can_improve(
            spec, loose_low, loose_high, best_score))
        return 0;
    projected_left = nv14_search_project_horizontal(
        context, state, logical_frame, -1);
    projected_right = nv14_search_project_horizontal(
        context, state, logical_frame, 1);
    tight_low = projected_left < projected_right
        ? projected_left : projected_right;
    tight_high = projected_left > projected_right
        ? projected_left : projected_right;
    return nv14_search_horizontal_interval_can_improve(
        spec, tight_low, tight_high, best_score);
}

/* Common node-time pruning.  This intentionally runs before exact dedup, just
   like the v2.73 DFS. */
static int nv14_search_node_allows(
    nv14_search_context *context,
    const nv14_state *state,
    size_t logical_frame,
    const uint8_t *missing_jumps
)
{
    const nv14_search_spec *spec = context->spec;
    if (context->budget_exhausted) return 0;
    ++context->result->stats.visited_nodes;
    if (!nv14_search_poll(context)) return 0;
    if (nv14_search_any_avoidance_triggered(context, state)) {
        ++context->result->stats.avoided_interaction_prunes;
        return 0;
    }
    if (!spec->required_jump_any &&
        spec->required_jump_count != 0 && context->result->feasible &&
        !nv14_search_flags_subset(
            missing_jumps,
            context->result->missing_jumps,
            spec->required_jump_count)) {
        ++context->result->stats.missed_jump_prunes;
        return 0;
    }
    if (!nv14_search_physics_allows(
            context, state, logical_frame, missing_jumps)) {
        ++context->result->stats.physics_prunes;
        return 0;
    }
    return 1;
}

static int nv14_search_dedup(
    nv14_search_context *context,
    const nv14_state *state,
    size_t logical_frame,
    const uint8_t *missing_jumps
)
{
    int seen = nv14_seen_test_and_insert(
        &context->seen,
        state,
        logical_frame,
        missing_jumps,
        context->spec->required_jump_count
    );
    if (seen == 1) {
        ++context->result->stats.deduplicated_prunes;
        return 0;
    }
    if (seen == -1) context->status = NV14_SEARCH_OUT_OF_MEMORY;
    else if (seen == -2) {
        context->status = NV14_SEARCH_CORE_ERROR;
        nv14_search_set_error(
            &context->core_error,
            NV14_STATUS_INVALID_ARGUMENT,
            "native core could not serialize a search state key"
        );
    }
    return seen == 0;
}

static int nv14_search_advance_fixed(
    nv14_search_context *context,
    nv14_state *state,
    size_t start_frame,
    size_t end_frame,
    uint8_t *missing_jumps
)
{
    size_t frame;
    for (frame = start_frame; frame < end_frame; ++frame) {
        nv14_step_result step_result;
        if (!nv14_search_node_allows(
                context, state, frame, missing_jumps))
            return 0;
        if (frame != context->spec->mutable_frames[0] &&
            !nv14_search_dedup(context, state, frame, missing_jumps))
            return 0;
        if (!nv14_search_step(
                context, state, context->spec->replay[frame], &step_result))
            return 0;
        if (step_result.dead) {
            ++context->result->stats.dead_prunes;
            return 0;
        }
        if (!nv14_search_update_required_jump(
                context, frame, &step_result, missing_jumps))
            return 0;
    }
    return 1;
}

static void nv14_search_evaluate_leaf(
    nv14_search_context *context,
    nv14_state *state,
    uint8_t *missing_jumps,
    int changed
)
{
    const nv14_search_spec *spec = context->spec;
    size_t frame = spec->mutable_frames[spec->mutable_count - 1u] + 1u;
    double score;
    if (!nv14_search_node_allows(context, state, frame, missing_jumps)) return;
    ++context->result->stats.evaluated_leaves;
    if (!changed) return;

    for (; frame <= spec->target_frame; ++frame) {
        nv14_step_result step_result;
        int previous_jump_held = state->player.previous_jump_held != 0;
        int state_was_jumping = state->player.state == NV14_PLAYER_JUMPING;
        int source_jump_edge = spec->replay[frame].jump &&
            (frame == 0 || !spec->replay[frame - 1u].jump);
        if (!nv14_search_step(
                context, state, spec->replay[frame], &step_result))
            return;
        if (nv14_search_any_avoidance_triggered(context, state)) {
            ++context->result->stats.avoided_interaction_prunes;
            return;
        }
        if (!nv14_search_update_required_jump(
                context, frame, &step_result, missing_jumps))
            return;
        if (spec->prune_inactive_jump && spec->replay[frame].jump &&
            spec->replay[frame].jump_trigger < 0 &&
            !previous_jump_held && !state_was_jumping &&
            !step_result.jumped && !source_jump_edge) {
            ++context->result->stats.inactive_jump_prunes;
            return;
        }
        if (step_result.dead) return;
    }
    if (!nv14_search_position_feasible(spec, state)) return;
    score = nv14_search_score(spec, state);
    nv14_search_terminal_interactions(context, state);
    if (spec->require_all_constraints &&
        (nv14_search_flags_any(
             context->candidate_missing_requirements,
             spec->required_group_count) ||
         nv14_search_flags_any(
             context->candidate_violated_avoidances,
             spec->avoided_group_count) ||
         nv14_search_flags_any(
             missing_jumps,
             spec->required_jump_count) ||
         state->player.jump_events < spec->minimum_jump_events))
        return;
    if (nv14_search_candidate_better(
            context,
            score,
            1,
            context->candidate_missing_requirements,
            context->candidate_violated_avoidances,
            missing_jumps)) {
        nv14_search_save_candidate(context, state, score, missing_jumps);
    }
}

static void nv14_search_recurse(
    nv14_search_context *context,
    nv14_state *state,
    size_t depth,
    uint8_t *missing_jumps,
    int changed
)
{
    const nv14_search_spec *spec = context->spec;
    size_t frame = spec->mutable_frames[depth];
    size_t choice_index;
    size_t choice_start;
    size_t choice_end;
    if (context->status != NV14_SEARCH_OK) return;
    if (!nv14_search_node_allows(context, state, frame, missing_jumps)) return;
    if (depth != 0 &&
        !nv14_search_dedup(context, state, frame, missing_jumps))
        return;

    choice_start = spec->choices_begin[depth];
    choice_end = spec->choices_begin[depth + 1u];
    for (choice_index = choice_start;
         choice_index < choice_end && context->status == NV14_SEARCH_OK &&
            !context->budget_exhausted;
         ++choice_index) {
        nv14_input candidate = spec->choices[choice_index];
        nv14_state *child = context->state_pool[depth + 1u];
        nv14_step_result step_result;
        uint8_t *child_missing = context->missing_stack +
            (depth + 1u) * spec->required_jump_count;
        int child_changed;
        size_t next_frame;
        context->chosen[depth] = candidate;
        child_changed = changed ||
            !nv14_search_input_equal(candidate, spec->replay[frame]);
        if (spec->skip_unchanged_final_step &&
            depth + 1u == spec->mutable_count && !child_changed) {
            ++context->result->stats.evaluated_leaves;
            continue;
        }
        if (!nv14_search_copy_state(context, child, state)) return;
        if (spec->required_jump_count != 0)
            memcpy(child_missing, missing_jumps, spec->required_jump_count);
        if (!nv14_search_step(context, child, candidate, &step_result)) {
            return;
        }
        if (step_result.dead) {
            ++context->result->stats.dead_prunes;
            continue;
        }
        if (!nv14_search_update_required_jump(
                context, frame, &step_result, child_missing)) {
            continue;
        }

        if (spec->prune_inactive_jump && candidate.jump &&
            candidate.jump_trigger < 0 &&
            !state->player.previous_jump_held &&
            !step_result.jumped &&
            state->player.state != NV14_PLAYER_JUMPING &&
            !nv14_search_preserve_failed_press(spec, frame)) {
            ++context->result->stats.inactive_jump_prunes;
            continue;
        }

        if (depth + 1u == spec->mutable_count) {
            nv14_search_evaluate_leaf(
                context, child, child_missing, child_changed);
            continue;
        }
        next_frame = spec->mutable_frames[depth + 1u];
        if (frame + 1u < next_frame &&
            !nv14_search_advance_fixed(
                context, child, frame + 1u, next_frame, child_missing)) {
            continue;
        }
        nv14_search_recurse(
            context, child, depth + 1u, child_missing, child_changed);
    }
}

static int nv14_search_validate_groups(
    const nv14_search_interaction_group *groups,
    size_t group_count,
    size_t atom_count
)
{
    size_t index;
    if (group_count != 0 && groups == NULL) return 0;
    for (index = 0; index < group_count; ++index) {
        if (groups[index].atom_count == 0 ||
            groups[index].first_atom > atom_count ||
            groups[index].atom_count > atom_count - groups[index].first_atom)
            return 0;
    }
    return 1;
}

static int nv14_search_validate_atoms(
    const nv14_level *level,
    const nv14_state *prefix_state,
    const nv14_search_interaction_atom *atoms,
    size_t atom_count
)
{
    size_t index;
    if (atom_count != 0 && atoms == NULL) return 0;
    for (index = 0; index < atom_count; ++index) {
        const nv14_search_interaction_atom *atom = &atoms[index];
        if (atom->kind == NV14_SEARCH_INTERACTION_GOLD) {
            if (atom->index >= nv14_level_gold_count(level)) return 0;
        } else if (atom->kind == NV14_SEARCH_INTERACTION_EXIT_SWITCH) {
            if (atom->index >= nv14_level_exit_count(level)) return 0;
        } else if (atom->kind == NV14_SEARCH_INTERACTION_LOCKED_DOOR ||
                   atom->kind == NV14_SEARCH_INTERACTION_TRAPDOOR) {
            int locked_open;
            int trap_triggered;
            if (atom->index > UINT32_MAX ||
                nv14_objects_basic_door_interactions(
                    prefix_state,
                    (uint32_t)atom->index,
                    &locked_open,
                    &trap_triggered
                ) != NV14_STATUS_OK)
                return 0;
        } else {
            return 0;
        }
    }
    return 1;
}

int nv14_search_trace_target_valid(
    const nv14_search_trace_target *target
)
{
    if (target == NULL ||
        !isfinite(target->x) || !isfinite(target->y) ||
        !isfinite(target->vx) || !isfinite(target->vy) ||
        target->player_state < NV14_PLAYER_STANDING ||
        target->player_state > NV14_PLAYER_CELEBRATING ||
        target->wall_x < -1 || target->wall_x > 1 ||
        target->floor_x < -1 || target->floor_x > 1 ||
        target->floor_y < -1 || target->floor_y > 1 ||
        target->in_air > 1 || target->near_wall > 1 ||
        target->previous_jump_held > 1 ||
        !isfinite(target->position_weight) ||
        target->position_weight < 0.0 ||
        !isfinite(target->velocity_weight) ||
        target->velocity_weight < 0.0 ||
        !isfinite(target->contact_mismatch_penalty) ||
        target->contact_mismatch_penalty < 0.0 ||
        !isfinite(target->in_air_mismatch_penalty) ||
        target->in_air_mismatch_penalty < 0.0 ||
        !isfinite(target->near_wall_mismatch_penalty) ||
        target->near_wall_mismatch_penalty < 0.0 ||
        !isfinite(target->gold_bit_penalty) ||
        target->gold_bit_penalty < 0.0 ||
        !isfinite(target->mine_bit_penalty) ||
        target->mine_bit_penalty < 0.0 ||
        !isfinite(target->exit_bit_penalty) ||
        target->exit_bit_penalty < 0.0 ||
        !isfinite(target->locked_door_bit_penalty) ||
        target->locked_door_bit_penalty < 0.0 ||
        !isfinite(target->trapdoor_bit_penalty) ||
        target->trapdoor_bit_penalty < 0.0 ||
        (target->collected_gold_word_count != 0 &&
         target->collected_gold == NULL) ||
        (target->exploded_mine_word_count != 0 &&
         target->exploded_mine == NULL) ||
        (target->open_exit_word_count != 0 &&
         target->open_exit == NULL) ||
        (target->opened_locked_door_word_count != 0 &&
         target->opened_locked_door == NULL) ||
        (target->triggered_trapdoor_word_count != 0 &&
         target->triggered_trapdoor == NULL))
        return 0;
    return 1;
}

static int nv14_search_validate_spec(
    const nv14_level *level,
    const nv14_search_spec *spec,
    nv14_error *error_out
)
{
    size_t index;
    if (level == NULL || spec == NULL ||
        spec->abi_version != NV14_SEARCH_ABI_VERSION ||
        spec->struct_size < sizeof(*spec) || spec->replay == NULL ||
        spec->mutable_frames == NULL || spec->mutable_count == 0 ||
        spec->mutable_count == SIZE_MAX ||
        spec->choices_begin == NULL || spec->choices == NULL ||
        spec->target_frame >= spec->replay_count ||
        spec->prefix_state == NULL ||
        spec->prefix_frame != spec->mutable_frames[0] ||
        spec->prefix_frame > UINT64_MAX ||
        nv14_state_frame(spec->prefix_state) != (uint64_t)spec->prefix_frame ||
        nv14_state_level(spec->prefix_state) != level) {
        nv14_search_set_error(
            error_out, NV14_STATUS_INVALID_ARGUMENT,
            "invalid or incompatible native search specification"
        );
        return 0;
    }
    if (spec->objective < NV14_SEARCH_MAX_X ||
        spec->objective > NV14_SEARCH_CONSTANT ||
        (spec->target_count != 0 && spec->targets == NULL) ||
        (spec->objective == NV14_SEARCH_MIN_DISTANCE &&
         (spec->targets == NULL || spec->target_count == 0)) ||
        (spec->objective == NV14_SEARCH_TRACE_DISTANCE &&
         !nv14_search_trace_target_valid(spec->trace_target)) ||
        (spec->has_x_window &&
         (isnan(spec->x_minimum) || isnan(spec->x_maximum) ||
          spec->x_minimum > spec->x_maximum)) ||
        (spec->has_y_window &&
         (isnan(spec->y_minimum) || isnan(spec->y_maximum) ||
          spec->y_minimum > spec->y_maximum)) ||
        isnan(spec->incumbent_score)) {
        nv14_search_set_error(
            error_out, NV14_STATUS_INVALID_ARGUMENT,
            "invalid native search objective or coordinate window"
        );
        return 0;
    }
    for (index = 0; index < spec->target_count; ++index) {
        if (!isfinite(spec->targets[index].x) ||
            !isfinite(spec->targets[index].y)) {
            nv14_search_set_error(
                error_out,
                NV14_STATUS_INVALID_ARGUMENT,
                "native search target coordinates must be finite"
            );
            return 0;
        }
    }
    if (!nv14_search_validate_atoms(
            level,
            spec->prefix_state,
            spec->required_atoms,
            spec->required_atom_count) ||
        !nv14_search_validate_atoms(
            level,
            spec->prefix_state,
            spec->avoided_atoms,
            spec->avoided_atom_count) ||
        !nv14_search_validate_groups(
            spec->required_groups,
            spec->required_group_count,
            spec->required_atom_count) ||
        !nv14_search_validate_groups(
            spec->avoided_groups,
            spec->avoided_group_count,
            spec->avoided_atom_count) ||
        (spec->required_group_count != 0 &&
         spec->incumbent_missing_requirements == NULL) ||
        (spec->avoided_group_count != 0 &&
         spec->incumbent_violated_avoidances == NULL) ||
        (spec->required_jump_count != 0 &&
         (spec->required_jump_frames == NULL ||
          spec->incumbent_missing_jumps == NULL)) ||
        (spec->ignored_jump_count != 0 &&
         spec->ignored_jump_frames == NULL)) {
        nv14_search_set_error(
            error_out, NV14_STATUS_INVALID_ARGUMENT,
            "invalid native search interaction or jump constraints"
        );
        return 0;
    }
    if (!nv14_search_flags_canonical(
            spec->incumbent_missing_requirements,
            spec->required_group_count) ||
        !nv14_search_flags_canonical(
            spec->incumbent_violated_avoidances,
            spec->avoided_group_count) ||
        !nv14_search_flags_canonical(
            spec->incumbent_missing_jumps,
            spec->required_jump_count)) {
        nv14_search_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "native incumbent flags must contain only zero or one"
        );
        return 0;
    }
    for (index = 0; index < spec->mutable_count; ++index) {
        size_t frame = spec->mutable_frames[index];
        size_t choice_index;
        if (frame > spec->target_frame ||
            (index != 0 && frame <= spec->mutable_frames[index - 1u]) ||
            spec->choices_begin[index] >= spec->choices_begin[index + 1u] ||
            spec->choices_begin[index + 1u] > spec->choice_count) {
            nv14_search_set_error(
                error_out, NV14_STATUS_INVALID_ARGUMENT,
                "mutable frames/choice offsets are not sorted and bounded"
            );
            return 0;
        }
        if (spec->physics_prune) {
            for (choice_index = spec->choices_begin[index];
                 choice_index < spec->choices_begin[index + 1u];
                 ++choice_index) {
                const nv14_input *choice = &spec->choices[choice_index];
                const nv14_input *source = &spec->replay[frame];
                if (choice->jump != source->jump ||
                    choice->jump_trigger != source->jump_trigger) {
                    nv14_search_set_error(
                        error_out,
                        NV14_STATUS_INVALID_ARGUMENT,
                        "physics pruning requires jump-preserving choices"
                    );
                    return 0;
                }
            }
        }
    }
    if (spec->choices_begin[0] != 0 ||
        spec->choices_begin[spec->mutable_count] != spec->choice_count) {
        nv14_search_set_error(
            error_out, NV14_STATUS_INVALID_ARGUMENT,
            "native search choice offsets do not cover the flat choice array"
        );
        return 0;
    }
    for (index = 0; index < spec->required_jump_count; ++index) {
        if (spec->required_jump_frames[index] > spec->target_frame ||
            (index != 0 && spec->required_jump_frames[index] <=
                spec->required_jump_frames[index - 1u])) {
            nv14_search_set_error(
                error_out, NV14_STATUS_INVALID_ARGUMENT,
                "required jump frames are not strictly sorted and bounded"
            );
            return 0;
        }
    }
    for (index = 0; index < spec->ignored_jump_count; ++index) {
        if (spec->ignored_jump_frames[index] > spec->target_frame ||
            (index != 0 && spec->ignored_jump_frames[index] <=
                spec->ignored_jump_frames[index - 1u])) {
            nv14_search_set_error(
                error_out, NV14_STATUS_INVALID_ARGUMENT,
                "ignored jump frames are not strictly sorted and bounded"
            );
            return 0;
        }
    }
    return 1;
}

static int nv14_search_allocate_result(
    const nv14_search_spec *spec,
    nv14_search_result *result
)
{
    size_t bytes;
    size_t index;
    (void)nv14_search_result_init(result, result->struct_size);
    result->score = spec->incumbent_score;
    result->feasible = spec->incumbent_feasible != 0;
    result->best_input_count = spec->mutable_count;
    result->missing_requirement_count = spec->required_group_count;
    result->violated_avoidance_count = spec->avoided_group_count;
    result->missing_jump_count = spec->required_jump_count;
    if (!nv14_search_size_product(
            spec->mutable_count, sizeof(*result->best_inputs), &bytes))
        return 0;
    result->best_inputs = (nv14_input *)malloc(bytes == 0 ? 1u : bytes);
    result->missing_requirements = (uint8_t *)malloc(
        spec->required_group_count == 0 ? 1u : spec->required_group_count);
    result->violated_avoidances = (uint8_t *)malloc(
        spec->avoided_group_count == 0 ? 1u : spec->avoided_group_count);
    result->missing_jumps = (uint8_t *)malloc(
        spec->required_jump_count == 0 ? 1u : spec->required_jump_count);
    if (result->best_inputs == NULL || result->missing_requirements == NULL ||
        result->violated_avoidances == NULL || result->missing_jumps == NULL)
        return 0;
    for (index = 0; index < spec->mutable_count; ++index)
        result->best_inputs[index] = spec->replay[spec->mutable_frames[index]];
    if (spec->required_group_count != 0)
        memcpy(result->missing_requirements,
            spec->incumbent_missing_requirements,
            spec->required_group_count);
    if (spec->avoided_group_count != 0)
        memcpy(result->violated_avoidances,
            spec->incumbent_violated_avoidances,
            spec->avoided_group_count);
    if (spec->required_jump_count != 0)
        memcpy(result->missing_jumps,
            spec->incumbent_missing_jumps,
            spec->required_jump_count);
    return 1;
}

nv14_search_status nv14_search_run(
    const nv14_level *level,
    const nv14_search_spec *spec,
    nv14_search_result *result_out,
    nv14_error *error_out
)
{
    nv14_search_context context;
    nv14_state *root = NULL;
    uint8_t *root_missing;
    size_t bytes;
    size_t index;
    if (result_out == NULL ||
        result_out->abi_version != NV14_SEARCH_ABI_VERSION ||
        result_out->struct_size < sizeof(*result_out)) {
        nv14_search_set_error(
            error_out, NV14_STATUS_INVALID_ARGUMENT,
            "native search result buffer is null or ABI-incompatible"
        );
        return NV14_SEARCH_INVALID_ARGUMENT;
    }
    if (result_out->best_inputs != NULL ||
        result_out->missing_requirements != NULL ||
        result_out->violated_avoidances != NULL ||
        result_out->missing_jumps != NULL) {
        nv14_search_set_error(
            error_out, NV14_STATUS_INVALID_ARGUMENT,
            "native search result must be initialized or destroyed before reuse"
        );
        return NV14_SEARCH_INVALID_ARGUMENT;
    }
    if (!nv14_search_validate_spec(level, spec, error_out))
        return NV14_SEARCH_INVALID_ARGUMENT;
    if (!nv14_search_allocate_result(spec, result_out)) {
        nv14_search_result_destroy(result_out);
        nv14_search_set_error(
            error_out, NV14_STATUS_OUT_OF_MEMORY,
            "unable to allocate native search result"
        );
        return NV14_SEARCH_OUT_OF_MEMORY;
    }

    memset(&context, 0, sizeof(context));
    context.level = level;
    context.spec = spec;
    context.result = result_out;
    context.status = NV14_SEARCH_OK;
    context.next_poll = spec->cancel_poll_interval == 0
        ? UINT64_C(16384) : spec->cancel_poll_interval;
    if (!nv14_search_size_product(
            spec->mutable_count, sizeof(*context.chosen), &bytes))
        context.status = NV14_SEARCH_OUT_OF_MEMORY;
    else
        context.chosen = (nv14_input *)malloc(bytes == 0 ? 1u : bytes);
    if (!nv14_search_size_product(
            spec->mutable_count + 1u,
            spec->required_jump_count,
            &bytes))
        context.status = NV14_SEARCH_OUT_OF_MEMORY;
    else
        context.missing_stack = (uint8_t *)calloc(bytes == 0 ? 1u : bytes, 1u);
    context.candidate_missing_requirements = (uint8_t *)calloc(
        spec->required_group_count == 0 ? 1u : spec->required_group_count, 1u);
    context.candidate_violated_avoidances = (uint8_t *)calloc(
        spec->avoided_group_count == 0 ? 1u : spec->avoided_group_count, 1u);
    if (spec->physics_prune)
        context.physics_jump_edges = (uint8_t *)calloc(spec->replay_count, 1u);
    context.state_pool_count = spec->mutable_count + 1u;
    if (!nv14_search_size_product(
            context.state_pool_count, sizeof(*context.state_pool), &bytes))
        context.status = NV14_SEARCH_OUT_OF_MEMORY;
    else
        context.state_pool = (nv14_state **)calloc(
            context.state_pool_count, sizeof(*context.state_pool));
    if (context.chosen == NULL || context.missing_stack == NULL ||
        context.candidate_missing_requirements == NULL ||
        context.candidate_violated_avoidances == NULL ||
        (spec->physics_prune && context.physics_jump_edges == NULL) ||
        context.state_pool == NULL)
        context.status = NV14_SEARCH_OUT_OF_MEMORY;

    if (context.status == NV14_SEARCH_OK && spec->physics_prune) {
        int previous = spec->mutable_frames[0] == 0
            ? 0 : spec->replay[spec->mutable_frames[0] - 1u].jump != 0;
        for (index = spec->mutable_frames[0]; index <= spec->target_frame; ++index) {
            int held = spec->replay[index].jump != 0;
            context.physics_jump_edges[index] = held && !previous;
            previous = held;
        }
    }
    root_missing = context.missing_stack;
    if (context.status == NV14_SEARCH_OK) {
        for (index = 0; index < spec->required_jump_count; ++index) {
            if (spec->required_jump_any)
                root_missing[index] = 1;
            else if (spec->required_jump_frames[index] < spec->mutable_frames[0])
                root_missing[index] = spec->incumbent_missing_jumps[index];
        }
        for (index = 0;
             index < context.state_pool_count &&
                context.status == NV14_SEARCH_OK;
             ++index)
            context.state_pool[index] =
                nv14_search_clone(&context, spec->prefix_state);
        root = context.state_pool[0];
        /* Pool construction is setup; count only allocation-free branch
           copies performed by the actual traversal. */
        result_out->stats.cloned_states = 0;
    }
    if (context.status == NV14_SEARCH_OK && root != NULL)
        nv14_search_recurse(&context, root, 0, root_missing, 0);

    if (context.state_pool != NULL) {
        for (index = 0; index < context.state_pool_count; ++index)
            nv14_state_destroy(context.state_pool[index]);
    }
    nv14_seen_destroy(&context.seen);
    free(context.chosen);
    free(context.missing_stack);
    free(context.candidate_missing_requirements);
    free(context.candidate_violated_avoidances);
    free(context.physics_jump_edges);
    free(context.state_pool);

    if (context.status != NV14_SEARCH_OK) {
        if (context.status == NV14_SEARCH_CORE_ERROR && error_out != NULL)
            *error_out = context.core_error;
        else if (context.status == NV14_SEARCH_OUT_OF_MEMORY)
            nv14_search_set_error(
                error_out, NV14_STATUS_OUT_OF_MEMORY,
                "native search exhausted memory"
            );
        nv14_search_result_destroy(result_out);
    }
    return context.status;
}

/* -------------------------------------------------------------------------
 * Generic constrained-run search
 * ------------------------------------------------------------------------- */

static int nv14_pattern_poll(nv14_pattern_search_context *context)
{
    uint64_t interval;
    ++context->poll_counter;
    if (context->spec->cancel == NULL) return 1;
    interval = context->spec->cancel_poll_interval;
    if (interval == 0) interval = UINT64_C(16384);
    if (context->poll_counter < context->next_poll) return 1;
    context->next_poll = context->poll_counter + interval;
    if (context->spec->cancel(context->spec->cancel_userdata)) {
        context->status = NV14_SEARCH_CANCELLED;
        return 0;
    }
    return 1;
}

static void nv14_pattern_core_failure(
    nv14_pattern_search_context *context,
    nv14_status status,
    const nv14_step_result *step_result
)
{
    context->status = status == NV14_STATUS_OUT_OF_MEMORY
        ? NV14_SEARCH_OUT_OF_MEMORY : NV14_SEARCH_CORE_ERROR;
    nv14_search_set_error(
        &context->core_error,
        status == NV14_STATUS_OK ? NV14_STATUS_UNSUPPORTED_OBJECTS : status,
        step_result != NULL && step_result->unsupported
            ? "pattern search encountered an unsupported native object"
            : nv14_status_string(status)
    );
}

static int nv14_pattern_copy_state(
    nv14_pattern_search_context *context,
    nv14_state *destination,
    const nv14_state *source
)
{
    nv14_error error;
    nv14_status status;
    status = nv14_state_copy_into(destination, source, &error);
    if (status != NV14_STATUS_OK) {
        context->status = status == NV14_STATUS_OUT_OF_MEMORY
            ? NV14_SEARCH_OUT_OF_MEMORY : NV14_SEARCH_CORE_ERROR;
        context->core_error = error;
        return 0;
    }
    ++context->result->stats.cloned_states;
    return 1;
}

static nv14_state *nv14_pattern_clone_state(
    nv14_pattern_search_context *context,
    const nv14_state *source
)
{
    nv14_error error;
    nv14_state *result;
    result = nv14_state_clone(source, &error);
    if (result == NULL) {
        context->status = error.code == NV14_STATUS_OUT_OF_MEMORY
            ? NV14_SEARCH_OUT_OF_MEMORY : NV14_SEARCH_CORE_ERROR;
        context->core_error = error;
        return NULL;
    }
    ++context->result->stats.cloned_states;
    return result;
}

static int nv14_pattern_step(
    nv14_pattern_search_context *context,
    nv14_state *state,
    nv14_input input,
    nv14_step_result *result_out
)
{
    nv14_status status;
    memset(result_out, 0, sizeof(*result_out));
    status = nv14_state_step(state, input, result_out);
    ++context->result->stats.simulated_ticks;
    if (!nv14_pattern_poll(context)) return 0;
    if (status != NV14_STATUS_OK || result_out->unsupported) {
        nv14_pattern_core_failure(context, status, result_out);
        return 0;
    }
    return 1;
}

static uint32_t nv14_pattern_step_events(const nv14_step_result *result)
{
    uint32_t events = 0;
    if (result->jumped) events |= NV14_PATTERN_EVENT_JUMPED;
    return events;
}

/* Advance walking_state with inactive input and, in hold_state, materialize
   the active alternative.  The native core's late-input fork shares object
   updates and all collision work.  A conservative two-complete-step fallback
   keeps this generic if a future object module gains post-player effects. */
static int nv14_pattern_step_start_alternatives(
    nv14_pattern_search_context *context,
    nv14_state *walking_state,
    nv14_state *hold_state,
    nv14_input inactive_input,
    nv14_input active_input,
    nv14_step_result *inactive_result,
    nv14_step_result *active_result,
    int *active_available_out
)
{
    nv14_status status;
    *active_available_out = 0;
    memset(inactive_result, 0, sizeof(*inactive_result));
    memset(active_result, 0, sizeof(*active_result));
    if (nv14_internal_state_can_step_alternate(walking_state)) {
        nv14_player_snapshot alternate_player;
        status = nv14_internal_state_step_alternate(
            walking_state,
            inactive_input,
            active_input,
            &alternate_player,
            inactive_result,
            active_result
        );
        context->result->stats.simulated_ticks += 2u;
        if (!nv14_pattern_poll(context)) return 0;
        if (status != NV14_STATUS_OK || inactive_result->unsupported ||
            active_result->unsupported) {
            nv14_pattern_core_failure(context, status, inactive_result);
            return 0;
        }
        if (!active_result->dead &&
            (nv14_pattern_step_events(active_result) &
             context->spec->required_start_event_mask) ==
                context->spec->required_start_event_mask) {
            if (!nv14_pattern_copy_state(context, hold_state, walking_state))
                return 0;
            hold_state->player = alternate_player;
            *active_available_out = 1;
        }
        return 1;
    }

    if (!nv14_pattern_copy_state(context, hold_state, walking_state)) return 0;
    if (!nv14_pattern_step(context, hold_state, active_input, active_result))
        return 0;
    if (!nv14_pattern_step(context, walking_state, inactive_input, inactive_result))
        return 0;
    if (!active_result->dead &&
        (nv14_pattern_step_events(active_result) &
         context->spec->required_start_event_mask) ==
            context->spec->required_start_event_mask)
        *active_available_out = 1;
    return 1;
}

static double nv14_pattern_score(
    const nv14_pattern_search_spec *spec,
    const nv14_state *state
)
{
    double x = state->player.pos.x;
    double y = state->player.pos.y;
    size_t index;
    if (spec->objective == NV14_SEARCH_MAX_X) return x;
    if (spec->objective == NV14_SEARCH_MIN_X) return -x;
    if (spec->objective == NV14_SEARCH_MAX_Y) return y;
    if (spec->objective == NV14_SEARCH_MIN_Y) return -y;
    if (spec->objective == NV14_SEARCH_MIN_DISTANCE) {
        double best = INFINITY;
        for (index = 0; index < spec->target_count; ++index) {
            double dx = x - spec->targets[index].x;
            double dy = y - spec->targets[index].y;
            double distance = dx * dx + dy * dy;
            if (distance < best) best = distance;
        }
        return -best;
    }
    return -INFINITY;
}

static int nv14_pattern_position_feasible(
    const nv14_pattern_search_spec *spec,
    const nv14_state *state
)
{
    double x = state->player.pos.x;
    double y = state->player.pos.y;
    return (!spec->has_x_window ||
            (x >= spec->x_minimum && x <= spec->x_maximum)) &&
        (!spec->has_y_window ||
         (y >= spec->y_minimum && y <= spec->y_maximum));
}

static size_t nv14_pattern_worst_candidate(
    const nv14_pattern_search_result *result
)
{
    size_t worst = 0;
    size_t index;
    for (index = 1; index < result->candidate_count; ++index) {
        const nv14_pattern_search_candidate *candidate =
            &result->candidates[index];
        const nv14_pattern_search_candidate *current =
            &result->candidates[worst];
        if (candidate->score < current->score ||
            (candidate->score == current->score &&
             candidate->traversal_ordinal > current->traversal_ordinal))
            worst = index;
    }
    return worst;
}

static void nv14_pattern_retain(
    nv14_pattern_search_context *context,
    const nv14_player_snapshot *player,
    double score,
    size_t span_count
)
{
    nv14_pattern_search_result *result = context->result;
    nv14_pattern_search_candidate *candidate;
    size_t index;
    uint64_t ordinal = ++context->feasible_ordinal;
    if (result->candidate_count < result->candidate_capacity) {
        index = result->candidate_count++;
    } else {
        index = nv14_pattern_worst_candidate(result);
        candidate = &result->candidates[index];
        /* Retain the first encountered candidates at an equal cutoff score,
           matching the strict replacement rule of the Python heap. */
        if (!(score > candidate->score)) return;
    }
    candidate = &result->candidates[index];
    candidate->score = score;
    candidate->span_count = span_count;
    candidate->player = *player;
    candidate->traversal_ordinal = ordinal;
    if (span_count != 0)
        memcpy(
            candidate->spans,
            context->path,
            span_count * sizeof(*candidate->spans)
        );
}

static int nv14_pattern_candidate_compare(const void *left, const void *right)
{
    const nv14_pattern_search_candidate *a =
        (const nv14_pattern_search_candidate *)left;
    const nv14_pattern_search_candidate *b =
        (const nv14_pattern_search_candidate *)right;
    if (a->score > b->score) return -1;
    if (a->score < b->score) return 1;
    if (a->traversal_ordinal < b->traversal_ordinal) return -1;
    if (a->traversal_ordinal > b->traversal_ordinal) return 1;
    return 0;
}

static int nv14_pattern_seen_test_and_insert(
    nv14_seen_set *set,
    const nv14_state *state,
    size_t cursor,
    size_t used,
    size_t required_release_frames,
    size_t fixed_index,
    uint64_t root_ordinal
)
{
    size_t state_size = nv14_state_key_size(state, -1);
    size_t aux_size = 4u * sizeof(size_t) + sizeof(root_ordinal);
    size_t key_size;
    size_t written = 0;
    unsigned char *key;
    unsigned char *cursor_out;
    nv14_status status;
    if (state_size == 0 || state_size > SIZE_MAX - aux_size) return -2;
    key_size = state_size + aux_size;
    key = (unsigned char *)malloc(key_size);
    if (key == NULL) return -1;
    status = nv14_state_write_key(state, -1, key, state_size, &written);
    if (status != NV14_STATUS_OK || written != state_size) {
        free(key);
        return -2;
    }
    cursor_out = key + state_size;
    memcpy(cursor_out, &cursor, sizeof(cursor));
    cursor_out += sizeof(cursor);
    memcpy(cursor_out, &used, sizeof(used));
    cursor_out += sizeof(used);
    memcpy(cursor_out, &required_release_frames, sizeof(required_release_frames));
    cursor_out += sizeof(required_release_frames);
    memcpy(cursor_out, &fixed_index, sizeof(fixed_index));
    cursor_out += sizeof(fixed_index);
    memcpy(cursor_out, &root_ordinal, sizeof(root_ordinal));
    return nv14_seen_insert_owned(set, key, key_size);
}

static int nv14_pattern_dedup(
    nv14_pattern_search_context *context,
    const nv14_state *state,
    size_t cursor,
    size_t used,
    size_t required_release_frames,
    size_t fixed_index,
    uint64_t root_ordinal
)
{
    int seen = nv14_pattern_seen_test_and_insert(
        &context->seen,
        state,
        cursor,
        used,
        required_release_frames,
        fixed_index,
        root_ordinal
    );
    if (seen == 1) {
        ++context->result->stats.deduplicated_branches;
        return 0;
    }
    if (seen == -1) context->status = NV14_SEARCH_OUT_OF_MEMORY;
    else if (seen == -2) {
        context->status = NV14_SEARCH_CORE_ERROR;
        nv14_search_set_error(
            &context->core_error,
            NV14_STATUS_INVALID_ARGUMENT,
            "native core could not serialize a pattern-search state key"
        );
    }
    return seen == 0;
}

static void nv14_pattern_evaluate_tail(
    nv14_pattern_search_context *context,
    const nv14_state *state_after_run,
    size_t next_frame,
    size_t span_count
)
{
    const nv14_pattern_search_spec *spec = context->spec;
    nv14_state *state = context->tail_state;
    size_t frame;
    ++context->result->stats.evaluated_candidates;
    if (!nv14_pattern_copy_state(context, state, state_after_run)) return;
    for (frame = next_frame;
         frame <= spec->range_end && context->status == NV14_SEARCH_OK;
         ++frame) {
        nv14_step_result step_result;
        if (!nv14_pattern_step(
                context,
                state,
                spec->inactive_inputs[frame - spec->range_start],
                &step_result))
            return;
        if (step_result.dead) return;
    }
    for (frame = spec->range_end + 1u;
         frame <= spec->target_frame && context->status == NV14_SEARCH_OK;
         ++frame) {
        nv14_step_result step_result;
        if (!nv14_pattern_step(context, state, spec->replay[frame], &step_result))
            return;
        if (step_result.dead) return;
    }
    if (!nv14_pattern_position_feasible(spec, state)) return;
    nv14_pattern_retain(
        context,
        &state->player,
        nv14_pattern_score(spec, state),
        span_count
    );
}

static void nv14_pattern_recurse(
    nv14_pattern_search_context *context,
    const nv14_state *state_before_cursor,
    size_t cursor,
    size_t used,
    size_t required_release_frames,
    size_t fixed_index,
    uint64_t root_ordinal
);

static void nv14_pattern_dispatch_run(
    nv14_pattern_search_context *context,
    const nv14_state *state_after_run,
    size_t next_frame,
    size_t count,
    size_t fixed_index,
    uint64_t root_ordinal
)
{
    const nv14_pattern_search_spec *spec = context->spec;
    int can_evaluate;
    int can_recurse;
    if (count == 1u) {
        root_ordinal = context->root_branch_ordinal++;
        if ((size_t)(root_ordinal % spec->shard_count) != spec->shard_index)
            return;
    }
    can_evaluate = fixed_index == spec->fixed_start_count &&
        count >= spec->run_count_min && count <= context->run_count_limit;
    can_recurse = count < context->run_count_limit &&
        next_frame <= spec->range_end;
    if (can_evaluate)
        nv14_pattern_evaluate_tail(context, state_after_run, next_frame, count);
    if (can_recurse && context->status == NV14_SEARCH_OK)
        nv14_pattern_recurse(
            context,
            state_after_run,
            next_frame,
            count,
            spec->minimum_gap,
            fixed_index,
            root_ordinal
        );
}

static void nv14_pattern_recurse(
    nv14_pattern_search_context *context,
    const nv14_state *state_before_cursor,
    size_t cursor,
    size_t used,
    size_t required_release_frames,
    size_t fixed_index,
    uint64_t root_ordinal
)
{
    const nv14_pattern_search_spec *spec = context->spec;
    nv14_state *walking_state;
    nv14_state *hold_state;
    size_t start;
    size_t next_fixed;
    int have_fixed;
    if (context->status != NV14_SEARCH_OK ||
        used >= context->run_count_limit ||
        cursor > spec->range_end)
        return;
    if (spec->fixed_start_count - fixed_index >
        context->run_count_limit - used)
        return;
    if (fixed_index < spec->fixed_start_count &&
        spec->fixed_starts[fixed_index] < cursor)
        return;
    if (!nv14_pattern_dedup(
            context,
            state_before_cursor,
            cursor,
            used,
            required_release_frames,
            fixed_index,
            root_ordinal))
        return;

    walking_state = context->walking_states[used];
    hold_state = context->hold_states[used];
    if (!nv14_pattern_copy_state(context, walking_state, state_before_cursor))
        return;
    start = cursor;
    while (required_release_frames != 0) {
        nv14_step_result step_result;
        if (start > spec->range_end) return;
        if (fixed_index < spec->fixed_start_count &&
            start == spec->fixed_starts[fixed_index])
            return;
        if (!nv14_pattern_step(
                context,
                walking_state,
                spec->inactive_inputs[start - spec->range_start],
                &step_result))
            return;
        if (step_result.dead) return;
        ++start;
        --required_release_frames;
    }

    have_fixed = fixed_index < spec->fixed_start_count;
    next_fixed = have_fixed ? spec->fixed_starts[fixed_index] : 0;
    while (start <= spec->range_end && context->status == NV14_SEARCH_OK) {
        nv14_step_result inactive_result;
        nv14_step_result active_result;
        size_t max_length_here;
        size_t length;
        size_t child_fixed_index;
        int fixed_start;
        int active_available;
        if (have_fixed && start > next_fixed) return;
        if (spec->run_length_min > spec->range_end - start + 1u) break;
        fixed_start = have_fixed && start == next_fixed;
        if (used != 0 || spec->shard_index == 0)
            ++context->result->stats.attempted_starts;
        if (!nv14_pattern_step_start_alternatives(
                context,
                walking_state,
                hold_state,
                spec->inactive_inputs[start - spec->range_start],
                spec->active_inputs[start - spec->range_start],
                &inactive_result,
                &active_result,
                &active_available))
            return;

        if (active_available) {
            if (used != 0 || spec->shard_index == 0)
                ++context->result->stats.successful_starts;
            child_fixed_index = fixed_start ? fixed_index + 1u : fixed_index;
            max_length_here =
                spec->start_max_lengths[start - spec->range_start];
            if (child_fixed_index < spec->fixed_start_count) {
                size_t following_fixed = spec->fixed_starts[child_fixed_index];
                size_t fixed_distance = following_fixed - start;
                size_t fixed_limit = fixed_distance > spec->minimum_gap
                    ? fixed_distance - spec->minimum_gap : 0;
                if (max_length_here > fixed_limit)
                    max_length_here = fixed_limit;
            }
            length = 1;
            while (length <= max_length_here &&
                   context->status == NV14_SEARCH_OK) {
                if (length >= spec->run_length_min) {
                    context->path[used].start_frame = start;
                    context->path[used].length = length;
                    nv14_pattern_dispatch_run(
                        context,
                        hold_state,
                        start + length,
                        used + 1u,
                        child_fixed_index,
                        root_ordinal
                    );
                }
                ++length;
                if (length <= max_length_here) {
                    size_t hold_frame = start + length - 1u;
                    nv14_step_result hold_result;
                    if (!nv14_pattern_step(
                            context,
                            hold_state,
                            spec->active_inputs[hold_frame - spec->range_start],
                            &hold_result))
                        return;
                    if (hold_result.dead) break;
                }
            }
        }
        if (fixed_start) return;
        if (inactive_result.dead) return;
        ++start;
    }
}

static int nv14_pattern_validate_input(nv14_input input)
{
    return input.left <= 1u && input.right <= 1u && input.jump <= 1u &&
        input.jump_trigger >= -1 && input.jump_trigger <= 1;
}

static int nv14_pattern_validate_spec(
    const nv14_level *level,
    const nv14_pattern_search_spec *spec,
    nv14_error *error_out
)
{
    size_t range_count;
    size_t index;
    if (level == NULL || spec == NULL ||
        spec->abi_version != NV14_SEARCH_ABI_VERSION ||
        spec->struct_size < sizeof(*spec) || spec->replay == NULL ||
        spec->range_start > spec->range_end ||
        spec->range_end > spec->target_frame ||
        spec->target_frame >= spec->replay_count ||
        spec->range_end == SIZE_MAX ||
        spec->inactive_inputs == NULL || spec->active_inputs == NULL ||
        spec->start_max_lengths == NULL ||
        spec->run_count_min == 0 ||
        spec->run_count_max < spec->run_count_min ||
        spec->run_length_min == 0 || spec->minimum_gap == 0 ||
        spec->top_results == 0 || spec->shard_count == 0 ||
        spec->shard_index >= spec->shard_count ||
        spec->prefix_state == NULL ||
        spec->prefix_frame != spec->range_start ||
        spec->prefix_frame > UINT64_MAX ||
        nv14_state_frame(spec->prefix_state) != (uint64_t)spec->prefix_frame ||
        nv14_state_level(spec->prefix_state) != level ||
        (spec->required_start_event_mask & ~NV14_PATTERN_EVENT_JUMPED) != 0) {
        nv14_search_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "invalid or incompatible native pattern-search specification"
        );
        return 0;
    }
    range_count = spec->range_end - spec->range_start + 1u;
    if (spec->pattern_input_count != range_count ||
        spec->start_max_length_count != range_count ||
        (spec->fixed_start_count != 0 && spec->fixed_starts == NULL) ||
        spec->fixed_start_count > spec->run_count_max ||
        spec->objective < NV14_SEARCH_MAX_X ||
        spec->objective > NV14_SEARCH_MIN_DISTANCE ||
        (spec->target_count != 0 && spec->targets == NULL) ||
        (spec->objective == NV14_SEARCH_MIN_DISTANCE &&
         (spec->targets == NULL || spec->target_count == 0)) ||
        (spec->has_x_window &&
         (isnan(spec->x_minimum) || isnan(spec->x_maximum) ||
          spec->x_minimum > spec->x_maximum)) ||
        (spec->has_y_window &&
         (isnan(spec->y_minimum) || isnan(spec->y_maximum) ||
          spec->y_minimum > spec->y_maximum))) {
        nv14_search_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "invalid native pattern bounds, objective or coordinate window"
        );
        return 0;
    }
    for (index = 0; index < range_count; ++index) {
        size_t maximum = spec->start_max_lengths[index];
        if (!nv14_pattern_validate_input(spec->inactive_inputs[index]) ||
            !nv14_pattern_validate_input(spec->active_inputs[index]) ||
            maximum > range_count - index) {
            nv14_search_set_error(
                error_out,
                NV14_STATUS_INVALID_ARGUMENT,
                "invalid native pattern input or per-start maximum length"
            );
            return 0;
        }
    }
    for (index = 0; index < spec->target_count; ++index) {
        if (!isfinite(spec->targets[index].x) ||
            !isfinite(spec->targets[index].y)) {
            nv14_search_set_error(
                error_out,
                NV14_STATUS_INVALID_ARGUMENT,
                "native pattern target coordinates must be finite"
            );
            return 0;
        }
    }
    for (index = 0; index < spec->fixed_start_count; ++index) {
        size_t frame = spec->fixed_starts[index];
        if (frame < spec->range_start || frame > spec->range_end ||
            (index != 0 && frame <= spec->fixed_starts[index - 1u]) ||
            (index != 0 &&
             (frame - spec->fixed_starts[index - 1u] < spec->run_length_min ||
              frame - spec->fixed_starts[index - 1u] - spec->run_length_min <
                spec->minimum_gap))) {
            nv14_search_set_error(
                error_out,
                NV14_STATUS_INVALID_ARGUMENT,
                "native fixed pattern starts are not sorted, bounded and feasible"
            );
            return 0;
        }
    }
    return 1;
}

static int nv14_pattern_allocate_result(
    const nv14_pattern_search_spec *spec,
    size_t run_count_limit,
    nv14_pattern_search_result *result
)
{
    size_t index;
    size_t bytes;
    (void)nv14_pattern_search_result_init(result, result->struct_size);
    if (!nv14_search_size_product(
            spec->top_results, sizeof(*result->candidates), &bytes))
        return 0;
    result->candidates = (nv14_pattern_search_candidate *)calloc(
        spec->top_results, sizeof(*result->candidates)
    );
    if (result->candidates == NULL) return 0;
    result->candidate_capacity = spec->top_results;
    if (!nv14_search_size_product(
            run_count_limit, sizeof(nv14_pattern_span), &bytes))
        return 0;
    for (index = 0; index < result->candidate_capacity; ++index) {
        result->candidates[index].spans = (nv14_pattern_span *)malloc(
            bytes == 0 ? 1u : bytes
        );
        if (result->candidates[index].spans == NULL) return 0;
    }
    return 1;
}

int nv14_pattern_search_result_init(
    nv14_pattern_search_result *result,
    size_t caller_size
)
{
    if (result == NULL || caller_size < 2u * sizeof(uint32_t) ||
        caller_size > UINT32_MAX)
        return 0;
    memset(result, 0, caller_size);
    result->abi_version = NV14_SEARCH_ABI_VERSION;
    result->struct_size = (uint32_t)caller_size;
    return 1;
}

void nv14_pattern_search_result_destroy(nv14_pattern_search_result *result)
{
    size_t caller_size;
    size_t index;
    if (result == NULL ||
        result->abi_version != NV14_SEARCH_ABI_VERSION ||
        result->struct_size < sizeof(*result))
        return;
    caller_size = result->struct_size;
    if (result->candidates != NULL) {
        for (index = 0; index < result->candidate_capacity; ++index)
            free(result->candidates[index].spans);
        free(result->candidates);
    }
    (void)nv14_pattern_search_result_init(result, caller_size);
}

nv14_search_status nv14_pattern_search_run(
    const nv14_level *level,
    const nv14_pattern_search_spec *spec,
    nv14_pattern_search_result *result_out,
    nv14_error *error_out
)
{
    nv14_pattern_search_context context;
    size_t index;
    size_t bytes;
    size_t run_count_limit;
    if (result_out == NULL ||
        result_out->abi_version != NV14_SEARCH_ABI_VERSION ||
        result_out->struct_size < sizeof(*result_out)) {
        nv14_search_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "native pattern result buffer is null or ABI-incompatible"
        );
        return NV14_SEARCH_INVALID_ARGUMENT;
    }
    if (result_out->candidates != NULL) {
        nv14_search_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "native pattern result must be initialized or destroyed before reuse"
        );
        return NV14_SEARCH_INVALID_ARGUMENT;
    }
    if (!nv14_pattern_validate_spec(level, spec, error_out))
        return NV14_SEARCH_INVALID_ARGUMENT;
    run_count_limit = spec->range_end - spec->range_start + 1u;
    if (run_count_limit > spec->run_count_max)
        run_count_limit = spec->run_count_max;
    if (!nv14_pattern_allocate_result(spec, run_count_limit, result_out)) {
        nv14_pattern_search_result_destroy(result_out);
        nv14_search_set_error(
            error_out,
            NV14_STATUS_OUT_OF_MEMORY,
            "unable to allocate native pattern-search result"
        );
        return NV14_SEARCH_OUT_OF_MEMORY;
    }

    memset(&context, 0, sizeof(context));
    context.level = level;
    context.spec = spec;
    context.result = result_out;
    context.run_count_limit = run_count_limit;
    context.status = NV14_SEARCH_OK;
    context.next_poll = spec->cancel_poll_interval == 0
        ? UINT64_C(16384) : spec->cancel_poll_interval;
    if (!nv14_search_size_product(
            run_count_limit, sizeof(*context.walking_states), &bytes))
        context.status = NV14_SEARCH_OUT_OF_MEMORY;
    else
        context.walking_states = (nv14_state **)calloc(
            run_count_limit, sizeof(*context.walking_states)
        );
    if (!nv14_search_size_product(
            run_count_limit, sizeof(*context.hold_states), &bytes))
        context.status = NV14_SEARCH_OUT_OF_MEMORY;
    else
        context.hold_states = (nv14_state **)calloc(
            run_count_limit, sizeof(*context.hold_states)
        );
    if (!nv14_search_size_product(
            run_count_limit, sizeof(*context.path), &bytes))
        context.status = NV14_SEARCH_OUT_OF_MEMORY;
    else
        context.path = (nv14_pattern_span *)calloc(
            run_count_limit, sizeof(*context.path)
        );
    if (context.walking_states == NULL || context.hold_states == NULL ||
        context.path == NULL)
        context.status = NV14_SEARCH_OUT_OF_MEMORY;
    for (index = 0;
         index < run_count_limit && context.status == NV14_SEARCH_OK;
         ++index) {
        context.walking_states[index] =
            nv14_pattern_clone_state(&context, spec->prefix_state);
        context.hold_states[index] =
            nv14_pattern_clone_state(&context, spec->prefix_state);
    }
    if (context.status == NV14_SEARCH_OK)
        context.tail_state =
            nv14_pattern_clone_state(&context, spec->prefix_state);
    /* Pool construction is setup rather than traversal cloning. */
    result_out->stats.cloned_states = 0;
    if (context.status == NV14_SEARCH_OK &&
        spec->run_count_min <= run_count_limit)
        nv14_pattern_recurse(
            &context,
            spec->prefix_state,
            spec->range_start,
            0,
            0,
            0,
            UINT64_MAX
        );
    if (context.status == NV14_SEARCH_OK && result_out->candidate_count > 1u)
        qsort(
            result_out->candidates,
            result_out->candidate_count,
            sizeof(*result_out->candidates),
            nv14_pattern_candidate_compare
        );

    if (context.walking_states != NULL) {
        for (index = 0; index < run_count_limit; ++index)
            nv14_state_destroy(context.walking_states[index]);
    }
    if (context.hold_states != NULL) {
        for (index = 0; index < run_count_limit; ++index)
            nv14_state_destroy(context.hold_states[index]);
    }
    nv14_state_destroy(context.tail_state);
    nv14_seen_destroy(&context.seen);
    free(context.walking_states);
    free(context.hold_states);
    free(context.path);

    if (context.status != NV14_SEARCH_OK) {
        if (context.status == NV14_SEARCH_CORE_ERROR && error_out != NULL)
            *error_out = context.core_error;
        else if (context.status == NV14_SEARCH_OUT_OF_MEMORY)
            nv14_search_set_error(
                error_out,
                NV14_STATUS_OUT_OF_MEMORY,
                "native pattern search exhausted memory"
            );
        nv14_pattern_search_result_destroy(result_out);
    }
    return context.status;
}

int nv14_search_result_init(
    nv14_search_result *result,
    size_t caller_size
)
{
    if (result == NULL || caller_size < 2u * sizeof(uint32_t) ||
        caller_size > UINT32_MAX)
        return 0;
    memset(result, 0, caller_size);
    result->abi_version = NV14_SEARCH_ABI_VERSION;
    result->struct_size = (uint32_t)caller_size;
    return 1;
}

void nv14_search_result_destroy(nv14_search_result *result)
{
    size_t caller_size;
    if (result == NULL ||
        result->abi_version != NV14_SEARCH_ABI_VERSION ||
        result->struct_size < sizeof(*result))
        return;
    caller_size = result->struct_size;
    free(result->best_inputs);
    free(result->missing_requirements);
    free(result->violated_avoidances);
    free(result->missing_jumps);
    (void)nv14_search_result_init(result, caller_size);
}

const char *nv14_search_status_string(nv14_search_status status)
{
    switch (status) {
        case NV14_SEARCH_OK: return "ok";
        case NV14_SEARCH_INVALID_ARGUMENT: return "invalid argument";
        case NV14_SEARCH_OUT_OF_MEMORY: return "out of memory";
        case NV14_SEARCH_CORE_ERROR: return "native engine error";
        case NV14_SEARCH_CANCELLED: return "cancelled";
        default: return "unknown native search status";
    }
}

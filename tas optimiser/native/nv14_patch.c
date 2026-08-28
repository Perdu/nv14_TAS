/* Ordered sparse-patch evaluator.  See nv14_patch.h. */

#include "nv14_patch.h"

#include "nv14_internal.h"
#include "nv14_objects_basic.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct nv14_patch_checkpoint {
    size_t frame;
    nv14_state *state;
} nv14_patch_checkpoint;

typedef struct nv14_patch_context {
    const nv14_level *level;
    const nv14_patch_spec *spec;
    nv14_patch_result *result;
    uint8_t *seed_jumped;
    uint8_t *jump_hits;
    nv14_patch_checkpoint *checkpoints;
    size_t checkpoint_count;
    uint64_t poll_counter;
    nv14_search_status status;
    nv14_error core_error;
} nv14_patch_context;

static void nv14_patch_set_error(
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

static int nv14_patch_size_product(size_t a, size_t b, size_t *out)
{
    if (b != 0 && a > SIZE_MAX / b) return 0;
    *out = a * b;
    return 1;
}

static void nv14_patch_counter_increment(uint64_t *counter)
{
    if (*counter != UINT64_MAX) ++*counter;
}

static int nv14_patch_input_valid(nv14_input input)
{
    return input.left <= 1u && input.right <= 1u && input.jump <= 1u &&
        input.jump_trigger >= -1 && input.jump_trigger <= 1;
}

static int nv14_patch_input_equal(nv14_input left, nv14_input right)
{
    return left.left == right.left && left.right == right.right &&
        left.jump == right.jump && left.jump_trigger == right.jump_trigger;
}

static unsigned int nv14_patch_input_key(nv14_input input)
{
    return (unsigned int)(input.left != 0) |
        ((unsigned int)(input.right != 0) << 1) |
        ((unsigned int)(input.jump != 0) << 2);
}

static int nv14_patch_input_trigger(nv14_input input, int previous_jump_held)
{
    return input.jump_trigger < 0
        ? (input.jump != 0 && !previous_jump_held)
        : input.jump_trigger != 0;
}

static int nv14_patch_poll(nv14_patch_context *context)
{
    uint64_t interval;
    if (context->spec->cancel == NULL) return 1;
    interval = context->spec->cancel_poll_interval;
    if (interval == 0) interval = UINT64_C(16384);
    if (context->poll_counter != UINT64_MAX) ++context->poll_counter;
    if (context->poll_counter < interval) return 1;
    context->poll_counter = 0;
    if (context->spec->cancel(context->spec->cancel_userdata)) {
        context->status = NV14_SEARCH_CANCELLED;
        return 0;
    }
    return 1;
}

static int nv14_patch_step(
    nv14_patch_context *context,
    nv14_state *state,
    nv14_input input,
    int charge,
    nv14_step_result *step_out
)
{
    nv14_status status;
    if (charge && context->spec->max_simulated_ticks != 0 &&
        context->result->stats.simulated_ticks >=
            context->spec->max_simulated_ticks) {
        context->result->budget_exhausted = 1;
        return 0;
    }
    memset(step_out, 0, sizeof(*step_out));
    status = nv14_state_step(state, input, step_out);
    if (charge)
        nv14_patch_counter_increment(&context->result->stats.simulated_ticks);
    if (!nv14_patch_poll(context)) return 0;
    if (status != NV14_STATUS_OK || step_out->unsupported) {
        context->status = NV14_SEARCH_CORE_ERROR;
        nv14_patch_set_error(
            &context->core_error,
            status == NV14_STATUS_OK ? NV14_STATUS_UNSUPPORTED_OBJECTS : status,
            step_out->unsupported
                ? "patch evaluation encountered an unsupported native object"
                : nv14_status_string(status)
        );
        return 0;
    }
    return 1;
}

static int nv14_patch_copy_state(
    nv14_patch_context *context,
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
    nv14_patch_counter_increment(&context->result->stats.cloned_states);
    return 1;
}

static nv14_state *nv14_patch_clone_setup(
    nv14_patch_context *context,
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
    }
    return result;
}

static int nv14_patch_interaction_atom_satisfied(
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
        nv14_status status;
        if (atom->index > UINT32_MAX) return 0;
        status = nv14_objects_basic_door_interactions(
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

static int nv14_patch_group_satisfied(
    const nv14_state *state,
    const nv14_search_interaction_atom *atoms,
    const nv14_search_interaction_group *group
)
{
    size_t index;
    for (index = 0; index < group->atom_count; ++index) {
        if (nv14_patch_interaction_atom_satisfied(
                state, &atoms[group->first_atom + index]))
            return 1;
    }
    return 0;
}

static int nv14_patch_any_avoidance_triggered(
    const nv14_patch_spec *spec,
    const nv14_state *state
)
{
    size_t index;
    for (index = 0; index < spec->avoided_group_count; ++index) {
        if (nv14_patch_group_satisfied(
                state, spec->avoided_atoms, &spec->avoided_groups[index]))
            return 1;
    }
    return 0;
}

static int nv14_patch_all_requirements_satisfied(
    const nv14_patch_spec *spec,
    const nv14_state *state
)
{
    size_t index;
    for (index = 0; index < spec->required_group_count; ++index) {
        if (!nv14_patch_group_satisfied(
                state, spec->required_atoms, &spec->required_groups[index]))
            return 0;
    }
    return 1;
}

static size_t nv14_patch_lower_bound(
    const size_t *values,
    size_t count,
    size_t value
)
{
    size_t low = 0;
    size_t high = count;
    while (low < high) {
        size_t middle = low + (high - low) / 2u;
        if (values[middle] < value) low = middle + 1u;
        else high = middle;
    }
    return low;
}

static int nv14_patch_frame_in_sorted(
    const size_t *values,
    size_t count,
    size_t frame
)
{
    size_t index = nv14_patch_lower_bound(values, count, frame);
    return index < count && values[index] == frame;
}

static void nv14_patch_record_jump(
    const nv14_patch_spec *spec,
    uint8_t *hits,
    size_t frame
)
{
    size_t index = nv14_patch_lower_bound(
        spec->required_jump_frames, spec->required_jump_count, frame);
    if (index < spec->required_jump_count &&
        spec->required_jump_frames[index] == frame &&
        !nv14_patch_frame_in_sorted(
            spec->ignored_jump_frames, spec->ignored_jump_count, frame))
        hits[index] = 1;
}

static int nv14_patch_jump_requirement_satisfied(
    const nv14_patch_spec *spec,
    const uint8_t *hits
)
{
    size_t index;
    if (spec->required_jump_count == 0) return 1;
    if (spec->required_jump_any) {
        for (index = 0; index < spec->required_jump_count; ++index) {
            if (hits[index]) return 1;
        }
        return 0;
    }
    for (index = 0; index < spec->required_jump_count; ++index) {
        if (!hits[index]) return 0;
    }
    return 1;
}

static int nv14_patch_checkpoint_compare(const void *left, const void *right)
{
    const nv14_patch_checkpoint *a = (const nv14_patch_checkpoint *)left;
    const nv14_patch_checkpoint *b = (const nv14_patch_checkpoint *)right;
    return a->frame < b->frame ? -1 : a->frame > b->frame ? 1 : 0;
}

static nv14_patch_checkpoint *nv14_patch_find_checkpoint(
    nv14_patch_context *context,
    size_t frame
)
{
    size_t low = 0;
    size_t high = context->checkpoint_count;
    while (low < high) {
        size_t middle = low + (high - low) / 2u;
        if (context->checkpoints[middle].frame < frame) low = middle + 1u;
        else high = middle;
    }
    if (low < context->checkpoint_count &&
        context->checkpoints[low].frame == frame)
        return &context->checkpoints[low];
    return NULL;
}

static size_t nv14_patch_held_edit_count(
    const nv14_patch_spec *spec,
    size_t patch_index
)
{
    const nv14_patch_span *span = &spec->patches[patch_index];
    size_t count = 0;
    size_t index;
    for (index = 0; index < span->assignment_count; ++index) {
        const nv14_patch_assignment *assignment =
            &spec->assignments[span->first_assignment + index];
        if (nv14_patch_input_key(assignment->input) !=
            nv14_patch_input_key(spec->replay[assignment->frame]))
            ++count;
    }
    return count;
}

static int nv14_patch_lex_less(
    const nv14_patch_spec *spec,
    size_t candidate_index,
    size_t incumbent_index
)
{
    const nv14_patch_span *candidate = &spec->patches[candidate_index];
    const nv14_patch_span *incumbent = &spec->patches[incumbent_index];
    size_t candidate_cursor = 0;
    size_t incumbent_cursor = 0;
    /* Every unassigned frame has the same base-replay key on both sides, so
       merge only the ordered assignment streams instead of scanning the dense
       replay prefix.  Trigger-only assignments remain in the merge and compare
       equal to the base held-input key, preserving the existing tie rule. */
    while (candidate_cursor < candidate->assignment_count ||
           incumbent_cursor < incumbent->assignment_count) {
        const nv14_patch_assignment *candidate_assignment =
            candidate_cursor < candidate->assignment_count
                ? &spec->assignments[
                    candidate->first_assignment + candidate_cursor]
                : NULL;
        const nv14_patch_assignment *incumbent_assignment =
            incumbent_cursor < incumbent->assignment_count
                ? &spec->assignments[
                    incumbent->first_assignment + incumbent_cursor]
                : NULL;
        size_t candidate_frame = candidate_assignment != NULL
            ? candidate_assignment->frame : SIZE_MAX;
        size_t incumbent_frame = incumbent_assignment != NULL
            ? incumbent_assignment->frame : SIZE_MAX;
        size_t frame = candidate_frame < incumbent_frame
            ? candidate_frame : incumbent_frame;
        unsigned int candidate_key = candidate_frame == frame
            ? nv14_patch_input_key(candidate_assignment->input)
            : nv14_patch_input_key(spec->replay[frame]);
        unsigned int incumbent_key = incumbent_frame == frame
            ? nv14_patch_input_key(incumbent_assignment->input)
            : nv14_patch_input_key(spec->replay[frame]);
        if (candidate_key != incumbent_key)
            return candidate_key < incumbent_key;
        if (candidate_frame == frame) ++candidate_cursor;
        if (incumbent_frame == frame) ++incumbent_cursor;
    }
    return 0;
}

static int nv14_patch_candidate_is_best(
    const nv14_patch_context *context,
    size_t candidate_index
)
{
    const nv14_patch_result *result = context->result;
    const nv14_patch_candidate_result *candidate =
        &result->candidates[candidate_index];
    const nv14_patch_candidate_result *incumbent;
    size_t candidate_edits;
    size_t incumbent_edits;
    if (!candidate->feasible || !isfinite(candidate->score)) return 0;
    if (result->best_patch_index == SIZE_MAX) return 1;
    incumbent = &result->candidates[result->best_patch_index];
    if (candidate->score < incumbent->score) return 1;
    if (candidate->score > incumbent->score ||
        context->spec->tie_policy != NV14_PATCH_TIE_LOW_EDIT_LEX)
        return 0;
    candidate_edits = nv14_patch_held_edit_count(
        context->spec, candidate_index);
    incumbent_edits = nv14_patch_held_edit_count(
        context->spec, result->best_patch_index);
    if (candidate_edits != incumbent_edits)
        return candidate_edits < incumbent_edits;
    return nv14_patch_lex_less(
        context->spec, candidate_index, result->best_patch_index);
}

static int nv14_patch_validate_groups(
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

static int nv14_patch_validate_atoms(
    const nv14_level *level,
    const nv14_state *initial_state,
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
                    initial_state,
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

static int nv14_patch_validate_sorted_frames(
    const size_t *frames,
    size_t count,
    size_t target_frame
)
{
    size_t index;
    if (count != 0 && frames == NULL) return 0;
    for (index = 0; index < count; ++index) {
        if (frames[index] > target_frame ||
            (index != 0 && frames[index] <= frames[index - 1u]))
            return 0;
    }
    return 1;
}

static int nv14_patch_validate_structure(
    const nv14_level *level,
    const nv14_patch_spec *spec,
    nv14_error *error_out
)
{
    size_t patch_index;
    size_t replay_index;
    size_t assignment_cursor = 0;
    if (level == NULL || spec == NULL ||
        spec->abi_version != NV14_PATCH_ABI_VERSION ||
        spec->struct_size < sizeof(*spec) || spec->replay == NULL ||
        spec->replay_count == 0 || spec->target_frame >= spec->replay_count ||
        (spec->patch_count != 0 && spec->patches == NULL) ||
        (spec->assignment_count != 0 && spec->assignments == NULL) ||
        (spec->patch_count == 0) != (spec->assignment_count == 0) ||
        (spec->patch_count != 0 &&
         (spec->prefix_state == NULL ||
          spec->prefix_frame > spec->target_frame ||
          spec->prefix_frame > UINT64_MAX ||
          nv14_state_frame(spec->prefix_state) !=
              (uint64_t)spec->prefix_frame ||
          nv14_state_level(spec->prefix_state) != level))) {
        nv14_patch_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "invalid or incompatible native patch specification"
        );
        return 0;
    }
    if (spec->tie_policy > NV14_PATCH_TIE_LOW_EDIT_LEX ||
        (spec->trace_target != NULL &&
         !nv14_search_trace_target_valid(spec->trace_target)) ||
        !nv14_patch_validate_groups(
            spec->required_groups,
            spec->required_group_count,
            spec->required_atom_count) ||
        !nv14_patch_validate_groups(
            spec->avoided_groups,
            spec->avoided_group_count,
            spec->avoided_atom_count) ||
        (spec->required_atom_count != 0 && spec->required_atoms == NULL) ||
        (spec->avoided_atom_count != 0 && spec->avoided_atoms == NULL) ||
        !nv14_patch_validate_sorted_frames(
            spec->required_jump_frames,
            spec->required_jump_count,
            spec->target_frame) ||
        !nv14_patch_validate_sorted_frames(
            spec->ignored_jump_frames,
            spec->ignored_jump_count,
            spec->target_frame) ||
        (spec->patch_count != 0 && spec->required_jump_count != 0 &&
         spec->required_jump_frames[0] < spec->prefix_frame)) {
        nv14_patch_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "invalid patch objective, interaction, or jump constraints"
        );
        return 0;
    }
    for (replay_index = 0; replay_index <= spec->target_frame; ++replay_index) {
        if (!nv14_patch_input_valid(spec->replay[replay_index])) {
            nv14_patch_set_error(
                error_out,
                NV14_STATUS_INVALID_ARGUMENT,
                "base replay contains an invalid native input"
            );
            return 0;
        }
    }
    for (patch_index = 0; patch_index < spec->patch_count; ++patch_index) {
        const nv14_patch_span *span = &spec->patches[patch_index];
        size_t local_index;
        if (span->assignment_count == 0 ||
            span->first_assignment != assignment_cursor ||
            span->first_assignment > spec->assignment_count ||
            span->assignment_count >
                spec->assignment_count - span->first_assignment) {
            nv14_patch_set_error(
                error_out,
                NV14_STATUS_INVALID_ARGUMENT,
                "patch spans do not partition the assignment array"
            );
            return 0;
        }
        for (local_index = 0;
             local_index < span->assignment_count;
             ++local_index) {
            const nv14_patch_assignment *assignment =
                &spec->assignments[span->first_assignment + local_index];
            if (assignment->frame > spec->target_frame ||
                !nv14_patch_input_valid(assignment->input) ||
                nv14_patch_input_equal(
                    assignment->input, spec->replay[assignment->frame]) ||
                (local_index == 0 &&
                 assignment->frame < spec->prefix_frame) ||
                (local_index != 0 &&
                 assignment->frame <=
                    spec->assignments[
                        span->first_assignment + local_index - 1u].frame)) {
                nv14_patch_set_error(
                    error_out,
                    NV14_STATUS_INVALID_ARGUMENT,
                    "patch assignments are not changed, sorted, and bounded"
                );
                return 0;
            }
        }
        assignment_cursor += span->assignment_count;
    }
    if (assignment_cursor != spec->assignment_count) {
        nv14_patch_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "patch spans do not cover the assignment array"
        );
        return 0;
    }
    return 1;
}

static int nv14_patch_allocate_result(
    const nv14_patch_spec *spec,
    nv14_patch_result *result
)
{
    size_t bytes;
    size_t index;
    (void)nv14_patch_result_init(result, result->struct_size);
    result->candidate_count = spec->patch_count;
    result->best_patch_index = SIZE_MAX;
    if (!nv14_patch_size_product(
            spec->patch_count, sizeof(*result->candidates), &bytes))
        return 0;
    result->candidates = (nv14_patch_candidate_result *)calloc(
        bytes == 0 ? 1u : bytes, 1u);
    if (result->candidates == NULL) return 0;
    for (index = 0; index < spec->patch_count; ++index)
        result->candidates[index].score = INFINITY;
    return 1;
}

static int nv14_patch_build_checkpoint_index(nv14_patch_context *context)
{
    size_t bytes;
    size_t patch_index;
    size_t unique_count;
    if (context->spec->patch_count == 0) return 1;
    if (!nv14_patch_size_product(
            context->spec->patch_count,
            sizeof(*context->checkpoints),
            &bytes))
        return 0;
    context->checkpoints = (nv14_patch_checkpoint *)calloc(bytes, 1u);
    if (context->checkpoints == NULL) return 0;
    for (patch_index = 0;
         patch_index < context->spec->patch_count;
         ++patch_index) {
        const nv14_patch_span *span = &context->spec->patches[patch_index];
        context->checkpoints[patch_index].frame =
            context->spec->assignments[span->first_assignment].frame;
    }
    qsort(
        context->checkpoints,
        context->spec->patch_count,
        sizeof(*context->checkpoints),
        nv14_patch_checkpoint_compare
    );
    unique_count = 0;
    for (patch_index = 0;
         patch_index < context->spec->patch_count;
         ++patch_index) {
        if (unique_count == 0 ||
            context->checkpoints[patch_index].frame !=
                context->checkpoints[unique_count - 1u].frame) {
            context->checkpoints[unique_count].frame =
                context->checkpoints[patch_index].frame;
            context->checkpoints[unique_count].state = NULL;
            ++unique_count;
        }
    }
    context->checkpoint_count = unique_count;
    return 1;
}

static int nv14_patch_materialize_seed(
    nv14_patch_context *context,
    nv14_state *seed
)
{
    const nv14_patch_spec *spec = context->spec;
    size_t checkpoint_index = 0;
    size_t frame;
    if (seed->player.dead) return 1;
    for (frame = spec->prefix_frame; frame <= spec->target_frame; ++frame) {
        nv14_step_result step_result;
        while (checkpoint_index < context->checkpoint_count &&
               context->checkpoints[checkpoint_index].frame == frame) {
            context->checkpoints[checkpoint_index].state =
                nv14_patch_clone_setup(context, seed);
            if (context->checkpoints[checkpoint_index].state == NULL)
                return 0;
            ++checkpoint_index;
        }
        /* No later base state can be observed by any candidate. */
        if (checkpoint_index == context->checkpoint_count) return 1;
        if (!nv14_patch_step(
                context, seed, spec->replay[frame], 0, &step_result))
            return 0;
        context->seed_jumped[frame] = step_result.jumped != 0;
        if (step_result.dead) break;
    }
    return 1;
}

static void nv14_patch_evaluate_one(
    nv14_patch_context *context,
    nv14_state *working,
    size_t patch_index
)
{
    const nv14_patch_spec *spec = context->spec;
    const nv14_patch_span *span = &spec->patches[patch_index];
    const nv14_patch_assignment *first_assignment =
        &spec->assignments[span->first_assignment];
    nv14_patch_candidate_result *candidate =
        &context->result->candidates[patch_index];
    nv14_patch_checkpoint *checkpoint = nv14_patch_find_checkpoint(
        context, first_assignment->frame);
    size_t assignment_cursor = 0;
    size_t frame;
    int previous_candidate_jump = first_assignment->frame == 0
        ? 0 : spec->replay[first_assignment->frame - 1u].jump != 0;

    if (checkpoint == NULL || checkpoint->state == NULL) {
        candidate->dead = 1;
        return;
    }
    if (spec->max_simulated_ticks != 0 &&
        context->result->stats.simulated_ticks >= spec->max_simulated_ticks) {
        context->result->budget_exhausted = 1;
        return;
    }
    nv14_patch_counter_increment(&context->result->stats.branches);
    if (!nv14_patch_copy_state(context, working, checkpoint->state)) return;
    if (spec->required_jump_count != 0)
        memset(context->jump_hits, 0, spec->required_jump_count);
    for (frame = 0; frame < spec->required_jump_count; ++frame) {
        size_t required_frame = spec->required_jump_frames[frame];
        if (required_frame >= first_assignment->frame) break;
        if (context->seed_jumped[required_frame] &&
            !nv14_patch_frame_in_sorted(
                spec->ignored_jump_frames,
                spec->ignored_jump_count,
                required_frame))
            context->jump_hits[frame] = 1;
    }

    for (frame = first_assignment->frame;
         frame <= spec->target_frame;
         ++frame) {
        nv14_input input = spec->replay[frame];
        nv14_input base_input = spec->replay[frame];
        nv14_step_result step_result;
        int previous_base_jump = frame == 0
            ? 0 : spec->replay[frame - 1u].jump != 0;
        int introduced_trigger;
        int state_was_jumping =
            working->player.state == NV14_PLAYER_JUMPING;
        if (assignment_cursor < span->assignment_count) {
            const nv14_patch_assignment *assignment =
                &spec->assignments[
                    span->first_assignment + assignment_cursor];
            if (assignment->frame == frame) {
                input = assignment->input;
                ++assignment_cursor;
            }
        }
        introduced_trigger =
            nv14_patch_input_trigger(input, previous_candidate_jump) &&
            !nv14_patch_input_trigger(base_input, previous_base_jump);
        if (!nv14_patch_step(context, working, input, 1, &step_result))
            return;
        previous_candidate_jump = input.jump != 0;
        if (step_result.jumped)
            nv14_patch_record_jump(spec, context->jump_hits, frame);
        if (spec->prune_inactive_jump && introduced_trigger &&
            !state_was_jumping && !step_result.jumped) {
            candidate->inactive_jump_pruned = 1;
            nv14_patch_counter_increment(
                &context->result->stats.inactive_jump_prunes);
            return;
        }
        if (step_result.dead) {
            candidate->dead = 1;
            nv14_patch_counter_increment(&context->result->stats.dead_prunes);
            return;
        }
        if (nv14_patch_any_avoidance_triggered(spec, working)) {
            candidate->avoided_interaction_pruned = 1;
            nv14_patch_counter_increment(
                &context->result->stats.avoided_interaction_prunes);
            return;
        }
    }
    if (spec->capture_endpoints) {
        candidate->endpoint = working->player;
        candidate->has_endpoint = 1;
    }
    if (!nv14_patch_all_requirements_satisfied(spec, working) ||
        !nv14_patch_jump_requirement_satisfied(spec, context->jump_hits) ||
        working->player.jump_events < spec->minimum_jump_events)
        return;
    candidate->feasible = 1;
    candidate->score = spec->trace_target == NULL
        ? 0.0 : nv14_search_trace_distance(spec->trace_target, working);
    if (nv14_patch_candidate_is_best(context, patch_index))
        context->result->best_patch_index = patch_index;
}

nv14_search_status nv14_patch_run(
    const nv14_level *level,
    const nv14_patch_spec *spec,
    nv14_patch_result *result_out,
    nv14_error *error_out
)
{
    nv14_patch_context context;
    nv14_state *seed = NULL;
    nv14_state *working = NULL;
    nv14_error error;
    size_t jump_bytes;
    size_t seed_jump_count;
    size_t checkpoint_index;
    size_t patch_index;
    if (error_out != NULL) memset(error_out, 0, sizeof(*error_out));
    if (result_out == NULL ||
        result_out->abi_version != NV14_PATCH_ABI_VERSION ||
        result_out->struct_size < sizeof(*result_out)) {
        nv14_patch_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "native patch result buffer is null or ABI-incompatible"
        );
        return NV14_SEARCH_INVALID_ARGUMENT;
    }
    if (result_out->candidates != NULL) {
        nv14_patch_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "native patch result must be initialized or destroyed before reuse"
        );
        return NV14_SEARCH_INVALID_ARGUMENT;
    }
    if (!nv14_patch_validate_structure(level, spec, error_out))
        return NV14_SEARCH_INVALID_ARGUMENT;

    memset(&context, 0, sizeof(context));
    context.level = level;
    context.spec = spec;
    context.result = result_out;
    context.status = NV14_SEARCH_OK;

    seed = spec->patch_count == 0
        ? nv14_state_create(level, &error)
        : nv14_state_clone(spec->prefix_state, &error);
    if (seed == NULL) {
        if (error_out != NULL) *error_out = error;
        return error.code == NV14_STATUS_OUT_OF_MEMORY
            ? NV14_SEARCH_OUT_OF_MEMORY : NV14_SEARCH_CORE_ERROR;
    }
    if (!nv14_patch_validate_atoms(
            level,
            seed,
            spec->required_atoms,
            spec->required_atom_count) ||
        !nv14_patch_validate_atoms(
            level,
            seed,
            spec->avoided_atoms,
            spec->avoided_atom_count)) {
        nv14_state_destroy(seed);
        nv14_patch_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "patch interaction atoms do not exist in this level"
        );
        return NV14_SEARCH_INVALID_ARGUMENT;
    }
    if (!nv14_patch_allocate_result(spec, result_out)) {
        nv14_state_destroy(seed);
        nv14_patch_result_destroy(result_out);
        nv14_patch_set_error(
            error_out,
            NV14_STATUS_OUT_OF_MEMORY,
            "unable to allocate native patch result"
        );
        return NV14_SEARCH_OUT_OF_MEMORY;
    }
    if (spec->patch_count == 0) {
        nv14_state_destroy(seed);
        return NV14_SEARCH_OK;
    }

    seed_jump_count = spec->target_frame + 1u;
    context.seed_jumped = (uint8_t *)calloc(seed_jump_count, 1u);
    if (!nv14_patch_size_product(
            spec->required_jump_count, sizeof(*context.jump_hits), &jump_bytes))
        context.status = NV14_SEARCH_OUT_OF_MEMORY;
    else
        context.jump_hits = (uint8_t *)calloc(
            jump_bytes == 0 ? 1u : jump_bytes, 1u);
    if (context.seed_jumped == NULL || context.jump_hits == NULL ||
        !nv14_patch_build_checkpoint_index(&context))
        context.status = NV14_SEARCH_OUT_OF_MEMORY;

    if (context.status == NV14_SEARCH_OK &&
        !nv14_patch_materialize_seed(&context, seed) &&
        context.status == NV14_SEARCH_OK && !result_out->budget_exhausted)
        context.status = NV14_SEARCH_CORE_ERROR;
    if (context.status == NV14_SEARCH_OK) {
        working = nv14_state_create(level, &error);
        if (working == NULL) {
            context.status = error.code == NV14_STATUS_OUT_OF_MEMORY
                ? NV14_SEARCH_OUT_OF_MEMORY : NV14_SEARCH_CORE_ERROR;
            context.core_error = error;
        }
    }
    for (patch_index = 0;
         patch_index < spec->patch_count &&
            context.status == NV14_SEARCH_OK &&
            !result_out->budget_exhausted;
         ++patch_index)
        nv14_patch_evaluate_one(&context, working, patch_index);

    nv14_state_destroy(seed);
    nv14_state_destroy(working);
    for (checkpoint_index = 0;
         checkpoint_index < context.checkpoint_count;
         ++checkpoint_index)
        nv14_state_destroy(context.checkpoints[checkpoint_index].state);
    free(context.seed_jumped);
    free(context.jump_hits);
    free(context.checkpoints);

    if (context.status != NV14_SEARCH_OK) {
        if (context.status == NV14_SEARCH_CORE_ERROR && error_out != NULL)
            *error_out = context.core_error;
        else if (context.status == NV14_SEARCH_OUT_OF_MEMORY)
            nv14_patch_set_error(
                error_out,
                NV14_STATUS_OUT_OF_MEMORY,
                "native patch evaluation exhausted memory"
            );
        else if (context.status == NV14_SEARCH_CANCELLED)
            nv14_patch_set_error(
                error_out,
                NV14_STATUS_OK,
                "native patch evaluation was cancelled"
            );
        nv14_patch_result_destroy(result_out);
    }
    return context.status;
}

int nv14_patch_result_init(
    nv14_patch_result *result,
    size_t caller_size
)
{
    if (result == NULL || caller_size < 2u * sizeof(uint32_t) ||
        caller_size > UINT32_MAX)
        return 0;
    memset(result, 0, caller_size);
    result->abi_version = NV14_PATCH_ABI_VERSION;
    result->struct_size = (uint32_t)caller_size;
    if (caller_size >= offsetof(nv14_patch_result, best_patch_index) +
            sizeof(result->best_patch_index))
        result->best_patch_index = SIZE_MAX;
    return 1;
}

void nv14_patch_result_destroy(nv14_patch_result *result)
{
    size_t caller_size;
    if (result == NULL ||
        result->abi_version != NV14_PATCH_ABI_VERSION ||
        result->struct_size < sizeof(*result))
        return;
    caller_size = result->struct_size;
    free(result->candidates);
    (void)nv14_patch_result_init(result, caller_size);
}

/* Generic native replay trajectory evaluator.  See nv14_auto.h. */

#include "nv14_auto.h"

#include "nv14_internal.h"
#include "nv14_objects_basic.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct nv14_replay_trace_door {
    size_t object_index;
    uint32_t load_index;
} nv14_replay_trace_door;

typedef struct nv14_replay_trace_workspace {
    nv14_replay_trace_door *doors;
    size_t door_count;
    uint64_t *before_collected_gold;
    uint64_t *before_open_exit;
    uint64_t *before_opened_locked_door;
    uint64_t *before_triggered_trapdoor;
} nv14_replay_trace_workspace;

static void nv14_replay_trace_clear_error(nv14_error *error_out)
{
    if (error_out == NULL) return;
    memset(error_out, 0, sizeof(*error_out));
    error_out->code = NV14_STATUS_OK;
    error_out->object_type = -1;
    error_out->tile_id = -1;
    error_out->tile_i = -1;
    error_out->tile_j = -1;
}

static void nv14_replay_trace_set_error(
    nv14_error *error_out,
    nv14_status code,
    const char *message
)
{
    nv14_replay_trace_clear_error(error_out);
    if (error_out == NULL) return;
    error_out->code = code;
    if (message != NULL) {
        (void)snprintf(
            error_out->message,
            sizeof(error_out->message),
            "%s",
            message
        );
    }
}

static int nv14_replay_trace_size_product(size_t a, size_t b, size_t *out)
{
    if (out == NULL || (b != 0 && a > SIZE_MAX / b)) return 0;
    *out = a * b;
    return 1;
}

static int nv14_replay_trace_size_sum(size_t a, size_t b, size_t *out)
{
    if (out == NULL || a > SIZE_MAX - b) return 0;
    *out = a + b;
    return 1;
}

static size_t nv14_replay_trace_word_count(size_t bit_count)
{
    return bit_count / 64u + (bit_count % 64u != 0u);
}

static void *nv14_replay_trace_calloc_array(
    size_t count,
    size_t element_size,
    int *ok_out
)
{
    size_t bytes;
    void *allocation;
    if (ok_out == NULL) return NULL;
    if (!*ok_out) return NULL;
    if (count == 0) return NULL;
    if (!nv14_replay_trace_size_product(count, element_size, &bytes)) {
        *ok_out = 0;
        return NULL;
    }
    allocation = calloc(1, bytes);
    if (allocation == NULL) *ok_out = 0;
    return allocation;
}

static uint64_t *nv14_replay_trace_calloc_mask_rows(
    size_t row_count,
    size_t word_count,
    int *ok_out
)
{
    size_t words;
    if (!nv14_replay_trace_size_product(row_count, word_count, &words)) {
        if (ok_out != NULL) *ok_out = 0;
        return NULL;
    }
    return (uint64_t *)nv14_replay_trace_calloc_array(
        words, sizeof(uint64_t), ok_out
    );
}

static void nv14_replay_trace_workspace_destroy(
    nv14_replay_trace_workspace *workspace
)
{
    if (workspace == NULL) return;
    free(workspace->doors);
    free(workspace->before_collected_gold);
    free(workspace->before_open_exit);
    free(workspace->before_opened_locked_door);
    free(workspace->before_triggered_trapdoor);
    memset(workspace, 0, sizeof(*workspace));
}

static int nv14_replay_trace_input_valid(nv14_input input)
{
    return input.left <= 1u && input.right <= 1u && input.jump <= 1u &&
        input.jump_trigger >= -1 && input.jump_trigger <= 1;
}

static int8_t nv14_replay_trace_sign_bin(double value)
{
    if (value < -1e-9) return -1;
    if (value > 1e-9) return 1;
    return 0;
}

static int nv14_replay_trace_result_is_clean(
    const nv14_replay_trace_result *result
)
{
    return result != NULL && result->populated == 0 &&
        result->trace == NULL &&
        result->trace_collected_gold_words == NULL &&
        result->trace_exploded_mine_words == NULL &&
        result->trace_open_exit_words == NULL &&
        result->trace_opened_locked_door_words == NULL &&
        result->trace_triggered_trapdoor_words == NULL &&
        result->final_collected_gold_words == NULL &&
        result->final_exploded_mine_words == NULL &&
        result->final_open_exit_words == NULL &&
        result->final_opened_locked_door_words == NULL &&
        result->final_triggered_trapdoor_words == NULL &&
        result->successful_jumps == NULL &&
        result->jump_edges == NULL &&
        result->missed_jump_edges == NULL &&
        result->jump_callable_windows == NULL &&
        result->gold_events == NULL &&
        result->route_control_events == NULL;
}

int nv14_replay_trace_result_init(
    nv14_replay_trace_result *result,
    size_t caller_size
)
{
    if (result == NULL || caller_size < 2u * sizeof(uint32_t) ||
        caller_size > UINT32_MAX)
        return 0;
    memset(result, 0, caller_size);
    result->abi_version = NV14_REPLAY_TRACE_ABI_VERSION;
    result->struct_size = (uint32_t)caller_size;
    /* A header-only buffer is useful for safe ABI probing.  Do not touch any
     * field beyond it until the caller proves it supplied the full layout. */
    if (caller_size >= sizeof(*result)) {
        result->finish_tick = -1;
        result->dead_tick = -1;
        result->last_tick = -1;
        result->completed_exit_index = -1;
    }
    return 1;
}

void nv14_replay_trace_result_destroy(nv14_replay_trace_result *result)
{
    size_t caller_size;
    if (result == NULL ||
        result->abi_version != NV14_REPLAY_TRACE_ABI_VERSION ||
        result->struct_size < sizeof(*result))
        return;
    caller_size = result->struct_size;
    free(result->trace);
    free(result->trace_collected_gold_words);
    free(result->trace_exploded_mine_words);
    free(result->trace_open_exit_words);
    free(result->trace_opened_locked_door_words);
    free(result->trace_triggered_trapdoor_words);
    free(result->final_collected_gold_words);
    free(result->final_exploded_mine_words);
    free(result->final_open_exit_words);
    free(result->final_opened_locked_door_words);
    free(result->final_triggered_trapdoor_words);
    free(result->successful_jumps);
    free(result->jump_edges);
    free(result->missed_jump_edges);
    free(result->jump_callable_windows);
    free(result->gold_events);
    free(result->route_control_events);
    (void)nv14_replay_trace_result_init(result, caller_size);
}

static int nv14_replay_trace_result_queryable(
    const nv14_replay_trace_result *result
)
{
    return result != NULL &&
        result->abi_version == NV14_REPLAY_TRACE_ABI_VERSION &&
        result->struct_size >= sizeof(*result) && result->populated != 0 &&
        (result->trace_count == 0 || result->trace != NULL);
}

static int nv14_replay_trace_is_dense(
    const nv14_replay_trace_result *result
)
{
    return result->trace_count != 0 && result->last_tick >= 0 &&
        result->trace[0].tick == 0 &&
        result->trace[result->trace_count - 1u].tick ==
            (uint64_t)result->last_tick &&
        (uint64_t)result->trace_count ==
            (uint64_t)result->last_tick + UINT64_C(1);
}

/* The caller has already validated the result and cached its density. */
static int nv14_replay_trace_find_point_index_known(
    const nv14_replay_trace_result *result,
    int dense,
    uint64_t tick,
    size_t *index_out
)
{
    size_t low = 0;
    size_t high;
    if (dense) {
        if (tick > (uint64_t)result->last_tick) return 0;
        *index_out = (size_t)tick;
        return 1;
    }
    high = result->trace_count;
    while (low < high) {
        size_t middle = low + (high - low) / 2u;
        uint64_t middle_tick = result->trace[middle].tick;
        if (middle_tick < tick)
            low = middle + 1u;
        else
            high = middle;
    }
    if (low >= result->trace_count || result->trace[low].tick != tick)
        return 0;
    *index_out = low;
    return 1;
}

static uint64_t nv14_replay_trace_row_word(
    const uint64_t *rows,
    size_t row,
    size_t word_count,
    size_t word
)
{
    if (rows == NULL || word >= word_count) return UINT64_C(0);
    return rows[row * word_count + word];
}

static unsigned int nv14_replay_trace_popcount(uint64_t value)
{
    unsigned int count = 0;
    while (value != 0) {
        value &= value - UINT64_C(1);
        ++count;
    }
    return count;
}

static size_t nv14_replay_trace_xor_popcount(
    const uint64_t *left_rows,
    size_t left_row,
    size_t left_words,
    const uint64_t *right_rows,
    size_t right_row,
    size_t right_words
)
{
    size_t word;
    size_t count = 0;
    size_t words = left_words > right_words ? left_words : right_words;
    for (word = 0; word < words; ++word) {
        uint64_t left = nv14_replay_trace_row_word(
            left_rows, left_row, left_words, word
        );
        uint64_t right = nv14_replay_trace_row_word(
            right_rows, right_row, right_words, word
        );
        count += nv14_replay_trace_popcount(left ^ right);
    }
    return count;
}

static int nv14_replay_trace_masks_equal(
    const uint64_t *left_rows,
    size_t left_row,
    size_t left_words,
    const uint64_t *right_rows,
    size_t right_row,
    size_t right_words
)
{
    size_t word;
    size_t words = left_words > right_words ? left_words : right_words;
    for (word = 0; word < words; ++word) {
        if (nv14_replay_trace_row_word(
                left_rows, left_row, left_words, word
            ) != nv14_replay_trace_row_word(
                right_rows, right_row, right_words, word
            ))
            return 0;
    }
    return 1;
}

static int nv14_replay_trace_mask_has_bit(
    const uint64_t *rows,
    size_t row,
    size_t word_count,
    int64_t bit
)
{
    uint64_t unsigned_bit;
    size_t word;
    if (bit < 0) return 0;
    unsigned_bit = (uint64_t)bit;
    if (unsigned_bit / UINT64_C(64) > (uint64_t)SIZE_MAX) return 0;
    word = (size_t)(unsigned_bit / UINT64_C(64));
    if (word >= word_count) return 0;
    return (
        nv14_replay_trace_row_word(rows, row, word_count, word) &
        (UINT64_C(1) << (unsigned int)(unsigned_bit % UINT64_C(64)))
    ) != 0;
}

static int nv14_replay_trace_mask_has_reference_only_bits(
    const uint64_t *candidate_rows,
    size_t candidate_row,
    size_t candidate_words,
    const uint64_t *reference_rows,
    size_t reference_row,
    size_t reference_words
)
{
    size_t word;
    for (word = 0; word < reference_words; ++word) {
        uint64_t candidate = nv14_replay_trace_row_word(
            candidate_rows, candidate_row, candidate_words, word
        );
        uint64_t reference = nv14_replay_trace_row_word(
            reference_rows, reference_row, reference_words, word
        );
        if ((reference & ~candidate) != 0) return 1;
    }
    return 0;
}

int nv14_replay_trace_find_point_index(
    const nv14_replay_trace_result *result,
    uint64_t tick,
    size_t *index_out
)
{
    if (!nv14_replay_trace_result_queryable(result) || index_out == NULL)
        return -1;
    return nv14_replay_trace_find_point_index_known(
        result, nv14_replay_trace_is_dense(result), tick, index_out
    );
}

static int nv14_replay_trace_contact_equal(
    const nv14_replay_trace_point *left,
    const nv14_replay_trace_point *right
)
{
    return left->player_state == right->player_state &&
        left->in_air == right->in_air &&
        left->near_wall == right->near_wall &&
        left->wall_x == right->wall_x &&
        left->floor_x == right->floor_x &&
        left->floor_y == right->floor_y &&
        left->previous_jump_held == right->previous_jump_held;
}

static int nv14_replay_trace_splice_contact_equal(
    const nv14_replay_trace_point *left,
    const nv14_replay_trace_point *right
)
{
    /* wall_x and floor_{x,y} are the most recently observed contact normals.
     * The simulation does not clear them on every later frame.  They cannot
     * affect player physics while away from a wall or airborne respectively,
     * so sectional splice matching compares them only while active. */
    return left->player_state == right->player_state &&
        left->in_air == right->in_air &&
        left->near_wall == right->near_wall &&
        (!left->near_wall || left->wall_x == right->wall_x) &&
        (left->in_air || (
            left->floor_x == right->floor_x &&
            left->floor_y == right->floor_y
        )) &&
        left->previous_jump_held == right->previous_jump_held;
}

static int nv14_replay_trace_route_matches(
    const nv14_replay_trace_result *candidate,
    size_t candidate_row,
    const nv14_replay_trace_result *reference,
    size_t reference_row,
    int64_t completion_exit_index
)
{
    if (completion_exit_index < 0) {
        return nv14_replay_trace_masks_equal(
            candidate->trace_open_exit_words,
            candidate_row,
            candidate->open_exit_word_count,
            reference->trace_open_exit_words,
            reference_row,
            reference->open_exit_word_count
        );
    }
    return !nv14_replay_trace_mask_has_bit(
            reference->trace_open_exit_words,
            reference_row,
            reference->open_exit_word_count,
            completion_exit_index
        ) || nv14_replay_trace_mask_has_bit(
            candidate->trace_open_exit_words,
            candidate_row,
            candidate->open_exit_word_count,
            completion_exit_index
    );
}

static double nv14_replay_trace_python_square(double value)
{
    /* Python float ``value ** 2`` reaches libm pow.  A constant exponent lets
       optimizing C compilers strength-reduce pow back to multiplication,
       which can differ by one ULP and change an alignment tie. */
    volatile double exponent = 2.0;
    return pow(value, exponent);
}

static double nv14_replay_trace_distance(
    const nv14_replay_trace_result *candidate,
    size_t candidate_row,
    const nv14_replay_trace_result *reference,
    size_t reference_row,
    const nv14_replay_alignment_spec *spec,
    int contact_matches
)
{
    const nv14_replay_trace_point *left = &candidate->trace[candidate_row];
    const nv14_replay_trace_point *right = &reference->trace[reference_row];
    double dx = left->x - right->x;
    double dy = left->y - right->y;
    double dvx = left->vx - right->vx;
    double dvy = left->vy - right->vy;
    double contact_penalty = contact_matches
        ? 0.0 : spec->contact_mismatch_penalty;
    double static_penalty = 0.0;
    if (left->in_air != right->in_air)
        contact_penalty += spec->in_air_mismatch_penalty;
    if (left->near_wall != right->near_wall)
        contact_penalty += spec->near_wall_mismatch_penalty;
    static_penalty += spec->gold_bit_penalty *
        (double)nv14_replay_trace_xor_popcount(
            candidate->trace_collected_gold_words,
            candidate_row,
            candidate->collected_gold_word_count,
            reference->trace_collected_gold_words,
            reference_row,
            reference->collected_gold_word_count
        );
    static_penalty += spec->mine_bit_penalty *
        (double)nv14_replay_trace_xor_popcount(
            candidate->trace_exploded_mine_words,
            candidate_row,
            candidate->exploded_mine_word_count,
            reference->trace_exploded_mine_words,
            reference_row,
            reference->exploded_mine_word_count
        );
    static_penalty += spec->exit_bit_penalty *
        (double)nv14_replay_trace_xor_popcount(
            candidate->trace_open_exit_words,
            candidate_row,
            candidate->open_exit_word_count,
            reference->trace_open_exit_words,
            reference_row,
            reference->open_exit_word_count
        );
    static_penalty += spec->locked_door_bit_penalty *
        (double)nv14_replay_trace_xor_popcount(
            candidate->trace_opened_locked_door_words,
            candidate_row,
            candidate->door_word_count,
            reference->trace_opened_locked_door_words,
            reference_row,
            reference->door_word_count
        );
    static_penalty += spec->trapdoor_bit_penalty *
        (double)nv14_replay_trace_xor_popcount(
            candidate->trace_triggered_trapdoor_words,
            candidate_row,
            candidate->door_word_count,
            reference->trace_triggered_trapdoor_words,
            reference_row,
            reference->door_word_count
        );
    return spec->position_weight *
            (nv14_replay_trace_python_square(dx) +
             nv14_replay_trace_python_square(dy)) +
        spec->velocity_weight *
            (nv14_replay_trace_python_square(dvx) +
             nv14_replay_trace_python_square(dvy)) +
        contact_penalty + static_penalty;
}

static int nv14_replay_trace_static_equal(
    const nv14_replay_trace_result *candidate,
    size_t candidate_row,
    const nv14_replay_trace_result *reference,
    size_t reference_row
)
{
    return nv14_replay_trace_masks_equal(
            candidate->trace_collected_gold_words,
            candidate_row,
            candidate->collected_gold_word_count,
            reference->trace_collected_gold_words,
            reference_row,
            reference->collected_gold_word_count
        ) && nv14_replay_trace_masks_equal(
            candidate->trace_exploded_mine_words,
            candidate_row,
            candidate->exploded_mine_word_count,
            reference->trace_exploded_mine_words,
            reference_row,
            reference->exploded_mine_word_count
        ) && nv14_replay_trace_masks_equal(
            candidate->trace_open_exit_words,
            candidate_row,
            candidate->open_exit_word_count,
            reference->trace_open_exit_words,
            reference_row,
            reference->open_exit_word_count
        ) && nv14_replay_trace_masks_equal(
            candidate->trace_opened_locked_door_words,
            candidate_row,
            candidate->door_word_count,
            reference->trace_opened_locked_door_words,
            reference_row,
            reference->door_word_count
        ) && nv14_replay_trace_masks_equal(
            candidate->trace_triggered_trapdoor_words,
            candidate_row,
            candidate->door_word_count,
            reference->trace_triggered_trapdoor_words,
            reference_row,
            reference->door_word_count
        );
}

static int nv14_replay_trace_splice_route_equal(
    const nv14_replay_trace_result *candidate,
    size_t candidate_row,
    const nv14_replay_trace_result *reference,
    size_t reference_row
)
{
    return nv14_replay_trace_masks_equal(
            candidate->trace_exploded_mine_words,
            candidate_row,
            candidate->exploded_mine_word_count,
            reference->trace_exploded_mine_words,
            reference_row,
            reference->exploded_mine_word_count
        ) && nv14_replay_trace_masks_equal(
            candidate->trace_open_exit_words,
            candidate_row,
            candidate->open_exit_word_count,
            reference->trace_open_exit_words,
            reference_row,
            reference->open_exit_word_count
        ) && nv14_replay_trace_masks_equal(
            candidate->trace_opened_locked_door_words,
            candidate_row,
            candidate->door_word_count,
            reference->trace_opened_locked_door_words,
            reference_row,
            reference->door_word_count
        ) && nv14_replay_trace_masks_equal(
            candidate->trace_triggered_trapdoor_words,
            candidate_row,
            candidate->door_word_count,
            reference->trace_triggered_trapdoor_words,
            reference_row,
            reference->door_word_count
        );
}

static uint64_t nv14_replay_trace_abs_offset(int64_t value)
{
    return value < 0 ? (uint64_t)(-(value + 1)) + UINT64_C(1)
                     : (uint64_t)value;
}

static int nv14_replay_trace_score_lead(
    int64_t offset,
    uint64_t candidate_bonus,
    uint64_t reference_bonus,
    int64_t *score_lead_out
)
{
    uint64_t difference;
    int64_t signed_difference;
    if (score_lead_out == NULL || candidate_bonus > (uint64_t)INT64_MAX ||
        reference_bonus > (uint64_t)INT64_MAX)
        return 0;
    if (candidate_bonus >= reference_bonus) {
        difference = candidate_bonus - reference_bonus;
        signed_difference = (int64_t)difference;
        if (offset > INT64_MAX - signed_difference) return 0;
        *score_lead_out = offset + signed_difference;
    } else {
        difference = reference_bonus - candidate_bonus;
        signed_difference = (int64_t)difference;
        if (offset < INT64_MIN + signed_difference) return 0;
        *score_lead_out = offset - signed_difference;
    }
    return 1;
}

static int nv14_replay_alignment_spec_valid(
    const nv14_replay_alignment_spec *spec,
    const nv14_replay_alignment_result *result
)
{
    if (spec == NULL || result == NULL ||
        spec->abi_version != NV14_REPLAY_ANALYSIS_ABI_VERSION ||
        spec->struct_size < sizeof(*spec) ||
        result->abi_version != NV14_REPLAY_ANALYSIS_ABI_VERSION ||
        result->struct_size < sizeof(*result) ||
        spec->scan_limit == 0 || spec->max_alignment > (uint64_t)INT64_MAX ||
        spec->max_negative_alignment > (uint64_t)INT64_MAX ||
        (spec->objective != NV14_REPLAY_ALIGNMENT_SPEEDRUN &&
         spec->objective != NV14_REPLAY_ALIGNMENT_HIGHSCORE))
        return 0;
    return isfinite(spec->position_tolerance) &&
        spec->position_tolerance >= 0.0 &&
        isfinite(spec->velocity_tolerance) &&
        spec->velocity_tolerance >= 0.0 &&
        isfinite(spec->position_weight) && spec->position_weight >= 0.0 &&
        isfinite(spec->velocity_weight) && spec->velocity_weight >= 0.0 &&
        isfinite(spec->contact_mismatch_penalty) &&
        spec->contact_mismatch_penalty >= 0.0 &&
        isfinite(spec->in_air_mismatch_penalty) &&
        spec->in_air_mismatch_penalty >= 0.0 &&
        isfinite(spec->near_wall_mismatch_penalty) &&
        spec->near_wall_mismatch_penalty >= 0.0 &&
        isfinite(spec->gold_bit_penalty) && spec->gold_bit_penalty >= 0.0 &&
        isfinite(spec->mine_bit_penalty) && spec->mine_bit_penalty >= 0.0 &&
        isfinite(spec->exit_bit_penalty) && spec->exit_bit_penalty >= 0.0 &&
        isfinite(spec->locked_door_bit_penalty) &&
        spec->locked_door_bit_penalty >= 0.0 &&
        isfinite(spec->trapdoor_bit_penalty) &&
        spec->trapdoor_bit_penalty >= 0.0;
}

int nv14_replay_trace_find_alignment(
    const nv14_replay_trace_result *candidate,
    const nv14_replay_trace_result *reference,
    const nv14_replay_alignment_spec *spec,
    nv14_replay_alignment_result *result_out
)
{
    size_t row;
    size_t first_row;
    size_t best_candidate_row = 0;
    size_t best_reference_row = 0;
    size_t best_run_length = 0;
    uint64_t best_run_tick = 0;
    double best_average = INFINITY;
    int64_t best_offset = 0;
    int64_t best_score_lead = 0;
    int have_previous = 0;
    uint64_t previous_tick = 0;
    uint64_t run_start_tick = 0;
    int64_t run_offset = 0;
    double run_distance = 0.0;
    int64_t run_min_score_lead = 0;
    uint32_t result_size;
    int reference_dense;

    if (!nv14_replay_trace_result_queryable(candidate) ||
        !nv14_replay_trace_result_queryable(reference) ||
        !nv14_replay_alignment_spec_valid(spec, result_out))
        return -1;
    result_size = result_out->struct_size;
    memset(result_out, 0, sizeof(*result_out));
    result_out->abi_version = NV14_REPLAY_ANALYSIS_ABI_VERSION;
    result_out->struct_size = result_size;
    result_out->candidate_tick = -1;
    result_out->reference_tick = -1;

    if (candidate->trace_count == 0 || reference->trace_count == 0)
        return 0;
    if (spec->objective == NV14_REPLAY_ALIGNMENT_SPEEDRUN &&
        spec->max_alignment < 1u)
        return 0;
    if (spec->objective == NV14_REPLAY_ALIGNMENT_HIGHSCORE &&
        spec->max_alignment < 1u && spec->max_negative_alignment < 1u)
        return 0;
    reference_dense = nv14_replay_trace_is_dense(reference);

    first_row = candidate->trace_count > spec->scan_limit
        ? candidate->trace_count - (size_t)spec->scan_limit : 0u;
    for (row = first_row; row < candidate->trace_count; ++row) {
        const nv14_replay_trace_point *point = &candidate->trace[row];
        size_t zero_row = 0;
        int zero_found;
        double zero_distance = INFINITY;
        int found_match = 0;
        size_t match_row = 0;
        double match_distance = INFINITY;
        int64_t match_offset = 0;
        int64_t match_score_lead = 0;
        int64_t minimum_offset;
        int64_t maximum_offset;
        int64_t offset;
        size_t run_length;
        double average;
        int replace_best = 0;

        if (point->dead || point->complete || point->tick > (uint64_t)INT64_MAX)
            continue;
        zero_found = nv14_replay_trace_find_point_index_known(
            reference, reference_dense, point->tick, &zero_row
        );
        if (zero_found < 0) return -1;
        if (zero_found > 0)
            zero_distance = nv14_replay_trace_distance(
                candidate,
                row,
                reference,
                zero_row,
                spec,
                nv14_replay_trace_contact_equal(
                    point, &reference->trace[zero_row]
                )
            );

        if (spec->objective == NV14_REPLAY_ALIGNMENT_SPEEDRUN) {
            int64_t remaining = reference->last_tick - (int64_t)point->tick;
            if (remaining < 1) continue;
            minimum_offset = 1;
            maximum_offset = (int64_t)spec->max_alignment < remaining
                ? (int64_t)spec->max_alignment : remaining;
        } else {
            uint64_t limited_negative = spec->max_negative_alignment;
            if (limited_negative > point->tick) limited_negative = point->tick;
            minimum_offset = -(int64_t)limited_negative;
            maximum_offset = (int64_t)spec->max_alignment;
            if (reference->last_tick - (int64_t)point->tick < maximum_offset)
                maximum_offset = reference->last_tick - (int64_t)point->tick;
            if (minimum_offset > maximum_offset) continue;
        }

        for (offset = minimum_offset; ; ++offset) {
            int64_t reference_tick = (int64_t)point->tick + offset;
            size_t reference_row = 0;
            int lookup = reference_tick < 0 ? 0 :
                nv14_replay_trace_find_point_index_known(
                    reference,
                    reference_dense,
                    (uint64_t)reference_tick,
                    &reference_row
                );
            if (lookup < 0) return -1;
            if (lookup > 0) {
                const nv14_replay_trace_point *reference_point =
                    &reference->trace[reference_row];
                int64_t score_lead = offset;
                int eligible = !reference_point->dead;
                double distance = INFINITY;
                if (spec->objective == NV14_REPLAY_ALIGNMENT_HIGHSCORE) {
                    if (!nv14_replay_trace_score_lead(
                            offset,
                            point->gold_bonus_ticks,
                            reference_point->gold_bonus_ticks,
                            &score_lead
                        ))
                        return -1;
                    if (offset == 0 && score_lead == 0) eligible = 0;
                }
                if (eligible && !nv14_replay_trace_route_matches(
                        candidate,
                        row,
                        reference,
                        reference_row,
                        spec->reference_completion_exit_index
                    ))
                    eligible = 0;
                if (eligible && !nv14_replay_trace_contact_equal(
                        point, reference_point
                    ))
                    eligible = 0;
                if (eligible) {
                    double dx = point->x - reference_point->x;
                    double dy = point->y - reference_point->y;
                    /* Component rejection is exact and leaves NaNs to hypot,
                     * preserving the original unordered-comparison behavior. */
                    if (fabs(dx) > spec->position_tolerance ||
                        fabs(dy) > spec->position_tolerance ||
                        hypot(dx, dy) > spec->position_tolerance)
                        eligible = 0;
                }
                if (eligible) {
                    double dvx = point->vx - reference_point->vx;
                    double dvy = point->vy - reference_point->vy;
                    if (fabs(dvx) > spec->velocity_tolerance ||
                        fabs(dvy) > spec->velocity_tolerance ||
                        hypot(dvx, dvy) > spec->velocity_tolerance)
                        eligible = 0;
                }
                if (eligible) {
                    distance = nv14_replay_trace_distance(
                        candidate,
                        row,
                        reference,
                        reference_row,
                        spec,
                        nv14_replay_trace_contact_equal(
                            point, reference_point
                        )
                    );
                    if (spec->objective == NV14_REPLAY_ALIGNMENT_HIGHSCORE &&
                        offset != 0 && distance + 1e-6 >= zero_distance)
                        eligible = 0;
                }
                if (eligible) {
                    int better = !found_match || distance < match_distance;
                    if (!better && distance == match_distance &&
                        spec->objective == NV14_REPLAY_ALIGNMENT_SPEEDRUN)
                        better = offset < match_offset;
                    if (!better && distance == match_distance &&
                        spec->objective == NV14_REPLAY_ALIGNMENT_HIGHSCORE) {
                        if (score_lead > match_score_lead)
                            better = 1;
                        else if (score_lead == match_score_lead &&
                            nv14_replay_trace_abs_offset(offset) <
                            nv14_replay_trace_abs_offset(match_offset))
                            better = 1;
                        else if (score_lead == match_score_lead &&
                            nv14_replay_trace_abs_offset(offset) ==
                            nv14_replay_trace_abs_offset(match_offset) &&
                            reference_tick <
                            (int64_t)reference->trace[match_row].tick)
                            better = 1;
                    }
                    if (better) {
                        found_match = 1;
                        match_row = reference_row;
                        match_distance = distance;
                        match_offset = offset;
                        match_score_lead = score_lead;
                    }
                }
            }
            if (offset == maximum_offset) break;
        }
        if (!found_match ||
            (spec->objective == NV14_REPLAY_ALIGNMENT_SPEEDRUN &&
             !(match_distance + 1e-6 < zero_distance)))
            continue;

        if (!have_previous || point->tick != previous_tick + UINT64_C(1) ||
            match_offset != run_offset) {
            run_start_tick = point->tick;
            run_offset = match_offset;
            run_distance = match_distance;
            run_min_score_lead = match_score_lead;
        } else {
            run_distance += match_distance;
            if (match_score_lead < run_min_score_lead)
                run_min_score_lead = match_score_lead;
        }
        have_previous = 1;
        previous_tick = point->tick;
        run_length = (size_t)(point->tick - run_start_tick + UINT64_C(1));
        if (run_length < 2u) continue;
        average = run_distance / (double)run_length;
        if (best_run_length == 0 || run_length > best_run_length)
            replace_best = 1;
        else if (run_length == best_run_length && point->tick > best_run_tick)
            replace_best = 1;
        else if (run_length == best_run_length && point->tick == best_run_tick) {
            if (spec->objective == NV14_REPLAY_ALIGNMENT_SPEEDRUN) {
                if (average < best_average ||
                    (average == best_average && run_offset > best_offset))
                    replace_best = 1;
            } else if (run_min_score_lead > best_score_lead ||
                (run_min_score_lead == best_score_lead &&
                 (average < best_average ||
                  (average == best_average &&
                   nv14_replay_trace_abs_offset(run_offset) <
                   nv14_replay_trace_abs_offset(best_offset)))))
                replace_best = 1;
        }
        if (replace_best) {
            best_run_length = run_length;
            best_run_tick = point->tick;
            best_average = average;
            best_offset = run_offset;
            best_score_lead = spec->objective == NV14_REPLAY_ALIGNMENT_SPEEDRUN
                ? run_offset : run_min_score_lead;
            best_candidate_row = row;
            best_reference_row = match_row;
        }
    }

    if (best_run_length == 0) return 0;
    result_out->found = 1;
    result_out->contact_matches = 1;
    result_out->static_matches = (uint8_t)nv14_replay_trace_static_equal(
        candidate, best_candidate_row, reference, best_reference_row
    );
    result_out->candidate_tick =
        (int64_t)candidate->trace[best_candidate_row].tick;
    result_out->reference_tick =
        (int64_t)reference->trace[best_reference_row].tick;
    result_out->offset = best_offset;
    result_out->score_lead = best_score_lead;
    result_out->distance = best_average;
    return 1;
}

static int nv14_replay_splice_alignment_spec_valid(
    const nv14_replay_splice_alignment_spec *spec,
    const nv14_replay_splice_alignment_result *result
)
{
    if (spec == NULL || result == NULL ||
        spec->abi_version != NV14_REPLAY_ANALYSIS_ABI_VERSION ||
        spec->struct_size < sizeof(*spec) ||
        result->abi_version != NV14_REPLAY_ANALYSIS_ABI_VERSION ||
        result->struct_size < sizeof(*result) ||
        spec->minimum_run_length == 0 ||
        spec->minimum_offset > spec->maximum_offset)
        return 0;
    return isfinite(spec->position_tolerance) &&
        spec->position_tolerance >= 0.0 &&
        isfinite(spec->velocity_tolerance) &&
        spec->velocity_tolerance >= 0.0 &&
        isfinite(spec->position_weight) && spec->position_weight >= 0.0 &&
        isfinite(spec->velocity_weight) && spec->velocity_weight >= 0.0 &&
        isfinite(spec->contact_mismatch_penalty) &&
        spec->contact_mismatch_penalty >= 0.0 &&
        isfinite(spec->in_air_mismatch_penalty) &&
        spec->in_air_mismatch_penalty >= 0.0 &&
        isfinite(spec->near_wall_mismatch_penalty) &&
        spec->near_wall_mismatch_penalty >= 0.0 &&
        isfinite(spec->gold_bit_penalty) && spec->gold_bit_penalty >= 0.0 &&
        isfinite(spec->mine_bit_penalty) && spec->mine_bit_penalty >= 0.0 &&
        isfinite(spec->exit_bit_penalty) && spec->exit_bit_penalty >= 0.0 &&
        isfinite(spec->locked_door_bit_penalty) &&
        spec->locked_door_bit_penalty >= 0.0 &&
        isfinite(spec->trapdoor_bit_penalty) &&
        spec->trapdoor_bit_penalty >= 0.0;
}

int nv14_replay_trace_find_splice_alignment(
    const nv14_replay_trace_result *candidate,
    const nv14_replay_trace_result *reference,
    const nv14_replay_splice_alignment_spec *spec,
    nv14_replay_splice_alignment_result *result_out
)
{
    uint64_t candidate_end_tick;
    int candidate_dense;
    int reference_dense;
    int64_t offset;
    uint64_t best_run_length = 0;
    uint64_t best_run_tick = 0;
    double best_average = INFINITY;
    int64_t best_offset = 0;
    int64_t best_score_lead = 0;
    size_t best_candidate_row = 0;
    size_t best_reference_row = 0;
    uint32_t result_size;
    nv14_replay_alignment_spec distance_spec;

    if (!nv14_replay_trace_result_queryable(candidate) ||
        !nv14_replay_trace_result_queryable(reference) ||
        !nv14_replay_splice_alignment_spec_valid(spec, result_out))
        return -1;
    result_size = result_out->struct_size;
    memset(result_out, 0, sizeof(*result_out));
    result_out->abi_version = NV14_REPLAY_ANALYSIS_ABI_VERSION;
    result_out->struct_size = result_size;
    result_out->candidate_tick = -1;
    result_out->reference_tick = -1;

    if (candidate->trace_count == 0 || reference->trace_count == 0 ||
        candidate->last_tick < 0)
        return 0;
    candidate_end_tick = spec->candidate_end_tick;
    if (candidate_end_tick > (uint64_t)candidate->last_tick)
        candidate_end_tick = (uint64_t)candidate->last_tick;
    if (spec->candidate_start_tick > candidate_end_tick)
        return 0;
    candidate_dense = nv14_replay_trace_is_dense(candidate);
    reference_dense = nv14_replay_trace_is_dense(reference);

    /* Reuse the bit-exact generic distance implementation.  It reads only
     * these policy fields from the temporary specification. */
    memset(&distance_spec, 0, sizeof(distance_spec));
    distance_spec.position_weight = spec->position_weight;
    distance_spec.velocity_weight = spec->velocity_weight;
    distance_spec.contact_mismatch_penalty =
        spec->contact_mismatch_penalty;
    distance_spec.in_air_mismatch_penalty =
        spec->in_air_mismatch_penalty;
    distance_spec.near_wall_mismatch_penalty =
        spec->near_wall_mismatch_penalty;
    distance_spec.gold_bit_penalty = spec->gold_bit_penalty;
    distance_spec.mine_bit_penalty = spec->mine_bit_penalty;
    distance_spec.exit_bit_penalty = spec->exit_bit_penalty;
    distance_spec.locked_door_bit_penalty =
        spec->locked_door_bit_penalty;
    distance_spec.trapdoor_bit_penalty = spec->trapdoor_bit_penalty;

    for (offset = spec->minimum_offset; ; ++offset) {
        uint64_t child_tick;
        uint64_t run_length = 0;
        double run_distance = 0.0;
        for (child_tick = spec->candidate_start_tick; ; ++child_tick) {
            size_t candidate_row = 0;
            size_t reference_row = 0;
            int candidate_lookup;
            int reference_lookup = 0;
            int eligible = 0;
            int64_t reference_tick = -1;
            int64_t score_lead = 0;
            double distance = INFINITY;
            double average;
            int replace_best = 0;

            candidate_lookup = nv14_replay_trace_find_point_index_known(
                candidate, candidate_dense, child_tick, &candidate_row
            );
            if (candidate_lookup < 0) return -1;
            if (candidate_lookup > 0 && child_tick <= (uint64_t)INT64_MAX) {
                int64_t signed_child_tick = (int64_t)child_tick;
                if (!((offset > 0 &&
                       signed_child_tick > INT64_MAX - offset) ||
                      (offset < 0 &&
                       signed_child_tick < INT64_MIN - offset))) {
                    reference_tick = signed_child_tick + offset;
                    if (reference_tick >= 0) {
                        reference_lookup =
                            nv14_replay_trace_find_point_index_known(
                                reference,
                                reference_dense,
                                (uint64_t)reference_tick,
                                &reference_row
                            );
                        if (reference_lookup < 0) return -1;
                    }
                }
            }
            if (candidate_lookup > 0 && reference_lookup > 0) {
                const nv14_replay_trace_point *point =
                    &candidate->trace[candidate_row];
                const nv14_replay_trace_point *reference_point =
                    &reference->trace[reference_row];
                eligible = !point->dead && !point->complete &&
                    !reference_point->dead && !reference_point->complete &&
                    isfinite(point->x) && isfinite(point->y) &&
                    isfinite(point->vx) && isfinite(point->vy) &&
                    isfinite(reference_point->x) &&
                    isfinite(reference_point->y) &&
                    isfinite(reference_point->vx) &&
                    isfinite(reference_point->vy) &&
                    nv14_replay_trace_splice_contact_equal(
                        point, reference_point
                    ) &&
                    nv14_replay_trace_splice_route_equal(
                        candidate,
                        candidate_row,
                        reference,
                        reference_row
                    );
                if (eligible) {
                    double dx = point->x - reference_point->x;
                    double dy = point->y - reference_point->y;
                    if (fabs(dx) > spec->position_tolerance ||
                        fabs(dy) > spec->position_tolerance ||
                        hypot(dx, dy) > spec->position_tolerance)
                        eligible = 0;
                }
                if (eligible) {
                    double dvx = point->vx - reference_point->vx;
                    double dvy = point->vy - reference_point->vy;
                    if (fabs(dvx) > spec->velocity_tolerance ||
                        fabs(dvy) > spec->velocity_tolerance ||
                        hypot(dvx, dvy) > spec->velocity_tolerance)
                        eligible = 0;
                }
                if (eligible) {
                    distance = nv14_replay_trace_distance(
                        candidate,
                        candidate_row,
                        reference,
                        reference_row,
                        &distance_spec,
                        nv14_replay_trace_splice_contact_equal(
                            point, reference_point
                        )
                    );
                    if (!nv14_replay_trace_score_lead(
                            offset,
                            point->gold_bonus_ticks,
                            reference_point->gold_bonus_ticks,
                            &score_lead
                        ))
                        return -1;
                }
            }

            if (!eligible) {
                run_length = 0;
                run_distance = 0.0;
            } else {
                ++run_length;
                run_distance += distance;
                if (run_length >= spec->minimum_run_length) {
                    average = run_distance / (double)run_length;
                    if (best_run_length == 0 ||
                        run_length > best_run_length)
                        replace_best = 1;
                    else if (run_length == best_run_length &&
                             child_tick > best_run_tick)
                        replace_best = 1;
                    else if (run_length == best_run_length &&
                             child_tick == best_run_tick) {
                        if (score_lead > best_score_lead)
                            replace_best = 1;
                        else if (score_lead == best_score_lead &&
                                 average < best_average)
                            replace_best = 1;
                        else if (score_lead == best_score_lead &&
                                 average == best_average &&
                                 offset > best_offset)
                            replace_best = 1;
                    }
                    if (replace_best) {
                        best_run_length = run_length;
                        best_run_tick = child_tick;
                        best_average = average;
                        best_offset = offset;
                        best_score_lead = score_lead;
                        best_candidate_row = candidate_row;
                        best_reference_row = reference_row;
                    }
                }
            }
            if (child_tick == candidate_end_tick) break;
        }
        if (offset == spec->maximum_offset) break;
    }

    if (best_run_length == 0) return 0;
    result_out->found = 1;
    result_out->contact_matches = 1;
    result_out->static_matches = (uint8_t)nv14_replay_trace_static_equal(
        candidate, best_candidate_row, reference, best_reference_row
    );
    result_out->candidate_tick =
        (int64_t)candidate->trace[best_candidate_row].tick;
    result_out->reference_tick =
        (int64_t)reference->trace[best_reference_row].tick;
    result_out->offset = best_offset;
    result_out->score_lead = best_score_lead;
    result_out->run_length = best_run_length;
    result_out->distance = best_average;
    return 1;
}

int nv14_replay_trace_find_route_divergence(
    const nv14_replay_trace_result *candidate,
    const nv14_replay_trace_result *reference,
    int64_t reference_offset,
    int64_t reference_completion_exit_index,
    size_t *candidate_index_out,
    size_t *reference_index_out
)
{
    return nv14_replay_trace_find_route_divergence_bounded(
        candidate,
        reference,
        reference_offset,
        reference_completion_exit_index,
        UINT64_C(0),
        UINT64_MAX,
        candidate_index_out,
        reference_index_out
    );
}

int nv14_replay_trace_find_route_divergence_bounded(
    const nv14_replay_trace_result *candidate,
    const nv14_replay_trace_result *reference,
    int64_t reference_offset,
    int64_t reference_completion_exit_index,
    uint64_t candidate_start_tick,
    uint64_t candidate_end_tick,
    size_t *candidate_index_out,
    size_t *reference_index_out
)
{
    size_t row;
    if (!nv14_replay_trace_result_queryable(candidate) ||
        !nv14_replay_trace_result_queryable(reference) ||
        candidate_index_out == NULL || reference_index_out == NULL)
        return -1;
    for (row = 0; row < candidate->trace_count; ++row) {
        uint64_t candidate_tick = candidate->trace[row].tick;
        int64_t reference_tick;
        size_t reference_row;
        int lookup;
        int required_exit = 0;
        int required_locked;
        int forbidden_trap;
        if (candidate_tick < candidate_start_tick) continue;
        if (candidate_tick > candidate_end_tick) break;
        if (candidate_tick > (uint64_t)INT64_MAX) return -1;
        if ((reference_offset > 0 &&
             (int64_t)candidate_tick > INT64_MAX - reference_offset) ||
            (reference_offset < 0 &&
             (int64_t)candidate_tick < INT64_MIN - reference_offset))
            continue;
        reference_tick = (int64_t)candidate_tick + reference_offset;
        if (reference_tick < 0) continue;
        lookup = nv14_replay_trace_find_point_index(
            reference, (uint64_t)reference_tick, &reference_row
        );
        if (lookup < 0) return -1;
        if (lookup == 0) continue;
        if (reference_completion_exit_index >= 0) {
            required_exit = nv14_replay_trace_mask_has_bit(
                    reference->trace_open_exit_words,
                    reference_row,
                    reference->open_exit_word_count,
                    reference_completion_exit_index
                ) && !nv14_replay_trace_mask_has_bit(
                    candidate->trace_open_exit_words,
                    row,
                    candidate->open_exit_word_count,
                    reference_completion_exit_index
                );
        }
        required_locked = nv14_replay_trace_mask_has_reference_only_bits(
            candidate->trace_opened_locked_door_words,
            row,
            candidate->door_word_count,
            reference->trace_opened_locked_door_words,
            reference_row,
            reference->door_word_count
        );
        forbidden_trap = nv14_replay_trace_mask_has_reference_only_bits(
            reference->trace_triggered_trapdoor_words,
            reference_row,
            reference->door_word_count,
            candidate->trace_triggered_trapdoor_words,
            row,
            candidate->door_word_count
        );
        if (required_exit || required_locked || forbidden_trap) {
            *candidate_index_out = row;
            *reference_index_out = reference_row;
            return 1;
        }
    }
    return 0;
}

static int nv14_replay_trace_collect_door_indices(
    const nv14_level *level,
    nv14_replay_trace_workspace *workspace,
    nv14_error *error_out
)
{
    size_t object_count = nv14_level_object_count(level);
    size_t index;
    size_t tracked_count = 0;
    int allocation_ok = 1;
    nv14_object_descriptor descriptor;

    for (index = 0; index < object_count; ++index) {
        nv14_status status = nv14_level_object_descriptor_at(
            level, index, &descriptor
        );
        if (status != NV14_STATUS_OK) {
            nv14_replay_trace_set_error(
                error_out,
                status,
                "unable to inspect serialized object descriptors"
            );
            return -1;
        }
        if (descriptor.object_type == NV14_OBJ_TESTDOOR &&
            descriptor.parameter_count >= 7u &&
            (descriptor.parameters[3] != 0.0 ||
             descriptor.parameters[6] != 0.0))
            ++tracked_count;
    }
    workspace->doors =
        (nv14_replay_trace_door *)nv14_replay_trace_calloc_array(
            tracked_count, sizeof(*workspace->doors), &allocation_ok
        );
    if (!allocation_ok) {
        nv14_replay_trace_set_error(
            error_out,
            NV14_STATUS_OUT_OF_MEMORY,
            "unable to allocate persistent-door index table"
        );
        return 0;
    }
    workspace->door_count = tracked_count;
    tracked_count = 0;
    for (index = 0; index < object_count; ++index) {
        nv14_status status = nv14_level_object_descriptor_at(
            level, index, &descriptor
        );
        if (status != NV14_STATUS_OK) {
            nv14_replay_trace_set_error(
                error_out,
                status,
                "unable to inspect serialized object descriptors"
            );
            return -1;
        }
        if (descriptor.object_type != NV14_OBJ_TESTDOOR ||
            descriptor.parameter_count < 7u ||
            (descriptor.parameters[3] == 0.0 &&
             descriptor.parameters[6] == 0.0))
            continue;
        if (descriptor.load_index >= object_count) {
            nv14_replay_trace_set_error(
                error_out,
                NV14_STATUS_INVALID_LEVEL,
                "persistent door has an out-of-range serialized load index"
            );
            return -1;
        }
        {
            size_t low = 0;
            size_t high = level->native_object_count;
            while (low < high) {
                size_t middle = low + (high - low) / 2u;
                if (level->native_objects[middle].load_index <
                    descriptor.load_index)
                    low = middle + 1u;
                else
                    high = middle;
            }
            if (low >= level->native_object_count ||
                level->native_objects[low].kind != NV14_NATIVE_TESTDOOR ||
                level->native_objects[low].load_index != descriptor.load_index) {
                nv14_replay_trace_set_error(
                    error_out,
                    NV14_STATUS_INVALID_LEVEL,
                    "persistent door has no native runtime index"
                );
                return -1;
            }
            workspace->doors[tracked_count].object_index = low;
            workspace->doors[tracked_count].load_index = descriptor.load_index;
            ++tracked_count;
        }
    }
    return 1;
}

static void nv14_replay_trace_capture_static_masks(
    const nv14_state *state,
    nv14_replay_trace_result *result
)
{
    if (result->collected_gold_word_count != 0)
        memcpy(
            result->final_collected_gold_words,
            state->collected_gold,
            result->collected_gold_word_count * sizeof(uint64_t)
        );
    if (result->exploded_mine_word_count != 0)
        memcpy(
            result->final_exploded_mine_words,
            state->exploded_mine,
            result->exploded_mine_word_count * sizeof(uint64_t)
        );
    if (result->open_exit_word_count != 0)
        memcpy(
            result->final_open_exit_words,
            state->open_exit,
            result->open_exit_word_count * sizeof(uint64_t)
        );
}

static void nv14_replay_trace_capture_changed_static_masks(
    const nv14_state *state,
    const nv14_step_result *step_result,
    nv14_replay_trace_result *result
)
{
    if (step_result->collected_gold &&
        result->collected_gold_word_count != 0)
        memcpy(
            result->final_collected_gold_words,
            state->collected_gold,
            result->collected_gold_word_count * sizeof(uint64_t)
        );
    if (step_result->exploded_mine &&
        result->exploded_mine_word_count != 0)
        memcpy(
            result->final_exploded_mine_words,
            state->exploded_mine,
            result->exploded_mine_word_count * sizeof(uint64_t)
        );
    if (step_result->opened_exit && result->open_exit_word_count != 0)
        memcpy(
            result->final_open_exit_words,
            state->open_exit,
            result->open_exit_word_count * sizeof(uint64_t)
        );
}

static nv14_status nv14_replay_trace_capture_door_masks(
    const nv14_state *state,
    const nv14_replay_trace_workspace *workspace,
    nv14_replay_trace_result *result
)
{
    size_t index;
    if (result->door_word_count != 0) {
        memset(
            result->final_opened_locked_door_words,
            0,
            result->door_word_count * sizeof(uint64_t)
        );
        memset(
            result->final_triggered_trapdoor_words,
            0,
            result->door_word_count * sizeof(uint64_t)
        );
    }
    for (index = 0; index < workspace->door_count; ++index) {
        const nv14_replay_trace_door *door = &workspace->doors[index];
        uint32_t load_index = door->load_index;
        int locked_open = 0;
        int trap_triggered = 0;
        nv14_status status = nv14_objects_basic_door_interactions_at(
            state, door->object_index, &locked_open, &trap_triggered
        );
        if (status != NV14_STATUS_OK) return status;
        if (locked_open)
            result->final_opened_locked_door_words[load_index / 64u] |=
                UINT64_C(1) << (load_index % 64u);
        if (trap_triggered)
            result->final_triggered_trapdoor_words[load_index / 64u] |=
                UINT64_C(1) << (load_index % 64u);
    }
    return NV14_STATUS_OK;
}

static void nv14_replay_trace_copy_words(
    uint64_t *destination,
    const uint64_t *source,
    size_t word_count
)
{
    if (word_count != 0)
        memcpy(destination, source, word_count * sizeof(uint64_t));
}

static void nv14_replay_trace_copy_mask_row(
    uint64_t *rows,
    size_t row,
    const uint64_t *source,
    size_t word_count
)
{
    if (word_count != 0) {
        memcpy(
            rows + row * word_count,
            source,
            word_count * sizeof(uint64_t)
        );
    }
}

static unsigned int nv14_replay_trace_low_bit_index(uint64_t value)
{
    unsigned int index = 0;
    /* Callers pass a nonzero value.  This portable loop also keeps the unit
     * buildable with MSVC without compiler-specific bit-scan intrinsics. */
    while ((value & UINT64_C(1)) == 0) {
        value >>= 1;
        ++index;
    }
    return index;
}

static int nv14_replay_trace_record_gold_events(
    nv14_replay_trace_result *result,
    const uint64_t *before,
    const uint64_t *after,
    size_t bit_count,
    uint64_t tick
)
{
    size_t word_count = nv14_replay_trace_word_count(bit_count);
    size_t word;
    for (word = 0; word < word_count; ++word) {
        uint64_t added = after[word] & ~before[word];
        while (added != 0) {
            unsigned int offset = nv14_replay_trace_low_bit_index(added);
            size_t bit = word * 64u + offset;
            uint64_t flag = UINT64_C(1) << offset;
            added &= ~flag;
            if (bit >= bit_count) continue;
            if (result->gold_event_count >= result->gold_event_capacity)
                return 0;
            result->gold_events[result->gold_event_count].gold_index = bit;
            result->gold_events[result->gold_event_count].tick = tick;
            ++result->gold_event_count;
        }
    }
    return 1;
}

static int nv14_replay_trace_record_route_events(
    nv14_replay_trace_result *result,
    const uint64_t *before,
    const uint64_t *after,
    size_t bit_count,
    uint64_t tick,
    nv14_replay_route_event_kind kind
)
{
    size_t word_count = nv14_replay_trace_word_count(bit_count);
    size_t word;
    for (word = 0; word < word_count; ++word) {
        uint64_t added = after[word] & ~before[word];
        while (added != 0) {
            unsigned int offset = nv14_replay_trace_low_bit_index(added);
            size_t bit = word * 64u + offset;
            uint64_t flag = UINT64_C(1) << offset;
            nv14_replay_route_event *event;
            added &= ~flag;
            if (bit >= bit_count) continue;
            if (result->route_control_event_count >=
                result->route_control_event_capacity)
                return 0;
            event = &result->route_control_events[
                result->route_control_event_count++
            ];
            event->kind = (uint8_t)kind;
            event->index = bit;
            event->tick = tick;
        }
    }
    return 1;
}

static int nv14_replay_trace_append_point(
    const nv14_state *state,
    uint64_t tick,
    nv14_replay_trace_result *result,
    nv14_error *error_out
)
{
    size_t row = result->trace_count;
    nv14_replay_trace_point *point;
    const nv14_player_snapshot *player = &state->player;
    if (row >= result->trace_capacity) {
        nv14_replay_trace_set_error(
            error_out,
            NV14_STATUS_OUT_OF_BOUNDS,
            "native replay trace exceeded its validated capacity"
        );
        return 0;
    }
    point = &result->trace[row];
    point->tick = tick;
    point->x = player->pos.x;
    point->y = player->pos.y;
    point->vx = player->pos.x - player->oldpos.x;
    point->vy = player->pos.y - player->oldpos.y;
    point->jump_events = player->jump_events;
    point->gold_bonus_ticks = state->gold_bonus_ticks;
    point->player_state = player->state;
    point->wall_x = nv14_replay_trace_sign_bin(player->wall_n.x);
    point->floor_x = nv14_replay_trace_sign_bin(player->floor_n.x);
    point->floor_y = nv14_replay_trace_sign_bin(player->floor_n.y);
    point->in_air = player->in_air != 0;
    point->near_wall = player->near_wall != 0;
    point->previous_jump_held = player->previous_jump_held != 0;
    point->complete = state->level_complete != 0;
    point->dead = player->dead != 0;

    nv14_replay_trace_copy_mask_row(
        result->trace_collected_gold_words,
        row,
        result->final_collected_gold_words,
        result->collected_gold_word_count
    );
    nv14_replay_trace_copy_mask_row(
        result->trace_exploded_mine_words,
        row,
        result->final_exploded_mine_words,
        result->exploded_mine_word_count
    );
    nv14_replay_trace_copy_mask_row(
        result->trace_open_exit_words,
        row,
        result->final_open_exit_words,
        result->open_exit_word_count
    );
    nv14_replay_trace_copy_mask_row(
        result->trace_opened_locked_door_words,
        row,
        result->final_opened_locked_door_words,
        result->door_word_count
    );
    nv14_replay_trace_copy_mask_row(
        result->trace_triggered_trapdoor_words,
        row,
        result->final_triggered_trapdoor_words,
        result->door_word_count
    );
    ++result->trace_count;
    return 1;
}

static int nv14_replay_trace_exit_centre(
    const nv14_level *level,
    int64_t completed_exit_index,
    double *x_out,
    double *y_out
)
{
    size_t index;
    if (level == NULL || completed_exit_index < 0 ||
        x_out == NULL || y_out == NULL)
        return 0;
    for (index = 0; index < level->native_object_count; ++index) {
        const nv14_native_object *object = &level->native_objects[index];
        if (object->kind == NV14_NATIVE_EXIT_DOOR &&
            (uint64_t)object->state_index ==
                (uint64_t)completed_exit_index) {
            *x_out = object->x;
            *y_out = object->y;
            return 1;
        }
    }
    return 0;
}

static int nv14_replay_trace_allocate_result(
    const nv14_level *level,
    const nv14_state *state,
    size_t input_count,
    size_t trace_stride,
    size_t door_count,
    nv14_replay_trace_result *result
)
{
    size_t route_event_capacity;
    int ok = 1;
    result->populated = 1;
    result->collected_gold_word_count = nv14_state_mask_word_count(
        state, NV14_MASK_COLLECTED_GOLD
    );
    result->exploded_mine_word_count = nv14_state_mask_word_count(
        state, NV14_MASK_EXPLODED_MINE
    );
    result->open_exit_word_count = nv14_state_mask_word_count(
        state, NV14_MASK_OPEN_EXIT
    );
    /* Preserve trace ABI 1: door-mask width is defined by serialized object
       count even when no persistent door is present.  The hot loop still
       skips door-state scans and before-mask maintenance in that case. */
    result->door_word_count = nv14_replay_trace_word_count(
        nv14_level_object_count(level)
    );
    if (input_count != 0) {
        result->trace_capacity = (input_count - 1u) / trace_stride + 1u;
        if (trace_stride > 1u && result->trace_capacity < input_count)
            ++result->trace_capacity;
    }
    result->trace = (nv14_replay_trace_point *)
        nv14_replay_trace_calloc_array(
            result->trace_capacity, sizeof(*result->trace), &ok
        );
    result->trace_collected_gold_words = nv14_replay_trace_calloc_mask_rows(
        result->trace_capacity, result->collected_gold_word_count, &ok
    );
    result->trace_exploded_mine_words = nv14_replay_trace_calloc_mask_rows(
        result->trace_capacity, result->exploded_mine_word_count, &ok
    );
    result->trace_open_exit_words = nv14_replay_trace_calloc_mask_rows(
        result->trace_capacity, result->open_exit_word_count, &ok
    );
    result->trace_opened_locked_door_words =
        nv14_replay_trace_calloc_mask_rows(
            result->trace_capacity, result->door_word_count, &ok
        );
    result->trace_triggered_trapdoor_words =
        nv14_replay_trace_calloc_mask_rows(
            result->trace_capacity, result->door_word_count, &ok
        );
    result->final_collected_gold_words =
        (uint64_t *)nv14_replay_trace_calloc_array(
            result->collected_gold_word_count,
            sizeof(*result->final_collected_gold_words),
            &ok
        );
    result->final_exploded_mine_words =
        (uint64_t *)nv14_replay_trace_calloc_array(
            result->exploded_mine_word_count,
            sizeof(*result->final_exploded_mine_words),
            &ok
        );
    result->final_open_exit_words =
        (uint64_t *)nv14_replay_trace_calloc_array(
            result->open_exit_word_count,
            sizeof(*result->final_open_exit_words),
            &ok
        );
    result->final_opened_locked_door_words =
        (uint64_t *)nv14_replay_trace_calloc_array(
            result->door_word_count,
            sizeof(*result->final_opened_locked_door_words),
            &ok
        );
    result->final_triggered_trapdoor_words =
        (uint64_t *)nv14_replay_trace_calloc_array(
            result->door_word_count,
            sizeof(*result->final_triggered_trapdoor_words),
            &ok
        );
    result->successful_jumps = (uint64_t *)nv14_replay_trace_calloc_array(
        input_count, sizeof(*result->successful_jumps), &ok
    );
    result->jump_edges = (uint64_t *)nv14_replay_trace_calloc_array(
        input_count, sizeof(*result->jump_edges), &ok
    );
    result->missed_jump_edges = (uint64_t *)nv14_replay_trace_calloc_array(
        input_count, sizeof(*result->missed_jump_edges), &ok
    );
    result->jump_callable_windows = (nv14_replay_tick_window *)
        nv14_replay_trace_calloc_array(
            input_count, sizeof(*result->jump_callable_windows), &ok
        );
    result->gold_event_capacity = nv14_level_gold_count(level);
    result->gold_events = (nv14_replay_gold_event *)
        nv14_replay_trace_calloc_array(
            result->gold_event_capacity, sizeof(*result->gold_events), &ok
        );
    if (!nv14_replay_trace_size_sum(
            nv14_level_exit_count(level), door_count, &route_event_capacity))
        ok = 0;
    else
        result->route_control_event_capacity = route_event_capacity;
    result->route_control_events = (nv14_replay_route_event *)
        nv14_replay_trace_calloc_array(
            result->route_control_event_capacity,
            sizeof(*result->route_control_events),
            &ok
        );
    return ok;
}

static int nv14_replay_trace_allocate_workspace_masks(
    const nv14_replay_trace_result *result,
    nv14_replay_trace_workspace *workspace
)
{
    int ok = 1;
    workspace->before_collected_gold =
        (uint64_t *)nv14_replay_trace_calloc_array(
            result->collected_gold_word_count,
            sizeof(*workspace->before_collected_gold),
            &ok
        );
    workspace->before_open_exit =
        (uint64_t *)nv14_replay_trace_calloc_array(
            result->open_exit_word_count,
            sizeof(*workspace->before_open_exit),
            &ok
        );
    workspace->before_opened_locked_door =
        (uint64_t *)nv14_replay_trace_calloc_array(
            result->door_word_count,
            sizeof(*workspace->before_opened_locked_door),
            &ok
        );
    workspace->before_triggered_trapdoor =
        (uint64_t *)nv14_replay_trace_calloc_array(
            result->door_word_count,
            sizeof(*workspace->before_triggered_trapdoor),
            &ok
        );
    return ok;
}

nv14_replay_trace_status nv14_replay_trace_run(
    const nv14_level *level,
    const nv14_input *inputs,
    size_t input_count,
    size_t trace_stride,
    nv14_replay_trace_result *result_out,
    nv14_error *error_out
)
{
    nv14_replay_trace_workspace workspace;
    nv14_state *state = NULL;
    nv14_error core_error;
    nv14_replay_trace_status return_status = NV14_REPLAY_TRACE_OK;
    nv14_status status;
    size_t tick;
    int previous_jump = 0;
    int door_status;

    memset(&workspace, 0, sizeof(workspace));
    nv14_replay_trace_clear_error(error_out);
    if (result_out == NULL ||
        result_out->abi_version != NV14_REPLAY_TRACE_ABI_VERSION ||
        result_out->struct_size < sizeof(*result_out)) {
        nv14_replay_trace_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "native replay-trace result buffer is null or ABI-incompatible"
        );
        return NV14_REPLAY_TRACE_INVALID_ARGUMENT;
    }
    if (!nv14_replay_trace_result_is_clean(result_out)) {
        nv14_replay_trace_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "native replay-trace result must be initialized or destroyed before reuse"
        );
        return NV14_REPLAY_TRACE_INVALID_ARGUMENT;
    }
    if (level == NULL || (input_count != 0 && inputs == NULL) ||
        trace_stride == 0 || input_count > (size_t)INT64_MAX) {
        nv14_replay_trace_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            "invalid native replay-trace level, input buffer, count, or stride"
        );
        return NV14_REPLAY_TRACE_INVALID_ARGUMENT;
    }
    for (tick = 0; tick < input_count; ++tick) {
        if (!nv14_replay_trace_input_valid(inputs[tick])) {
            nv14_replay_trace_set_error(
                error_out,
                NV14_STATUS_INVALID_ARGUMENT,
                "native replay trace contains a non-canonical input"
            );
            return NV14_REPLAY_TRACE_INVALID_ARGUMENT;
        }
    }
    if (nv14_level_unsupported_object_mask(level) != 0) {
        nv14_replay_trace_set_error(
            error_out,
            NV14_STATUS_UNSUPPORTED_OBJECTS,
            "native replay trace requires a fully supported native level"
        );
        return NV14_REPLAY_TRACE_CORE_ERROR;
    }

    nv14_replay_trace_clear_error(&core_error);
    state = nv14_state_create(level, &core_error);
    if (state == NULL) {
        if (error_out != NULL) *error_out = core_error;
        return core_error.code == NV14_STATUS_OUT_OF_MEMORY
            ? NV14_REPLAY_TRACE_OUT_OF_MEMORY
            : NV14_REPLAY_TRACE_CORE_ERROR;
    }
    door_status = nv14_replay_trace_collect_door_indices(
        level, &workspace, &core_error
    );
    if (door_status <= 0) {
        if (error_out != NULL) *error_out = core_error;
        return_status = door_status == 0
            ? NV14_REPLAY_TRACE_OUT_OF_MEMORY
            : NV14_REPLAY_TRACE_CORE_ERROR;
        goto fail;
    }
    if (!nv14_replay_trace_allocate_result(
            level,
            state,
            input_count,
            trace_stride,
            workspace.door_count,
            result_out
        ) || !nv14_replay_trace_allocate_workspace_masks(
            result_out, &workspace
        )) {
        nv14_replay_trace_set_error(
            &core_error,
            NV14_STATUS_OUT_OF_MEMORY,
            "unable to allocate native replay-trace result"
        );
        if (error_out != NULL) *error_out = core_error;
        return_status = NV14_REPLAY_TRACE_OUT_OF_MEMORY;
        goto fail;
    }
    nv14_replay_trace_capture_static_masks(state, result_out);
    status = NV14_STATUS_OK;
    if (workspace.door_count != 0)
        status = nv14_replay_trace_capture_door_masks(
            state, &workspace, result_out
        );
    if (status != NV14_STATUS_OK) {
        nv14_replay_trace_set_error(
            &core_error, status, "unable to capture initial native route masks"
        );
        if (error_out != NULL) *error_out = core_error;
        return_status = NV14_REPLAY_TRACE_CORE_ERROR;
        goto fail;
    }
    nv14_replay_trace_copy_words(
        workspace.before_collected_gold,
        result_out->final_collected_gold_words,
        result_out->collected_gold_word_count
    );
    nv14_replay_trace_copy_words(
        workspace.before_open_exit,
        result_out->final_open_exit_words,
        result_out->open_exit_word_count
    );
    nv14_replay_trace_copy_words(
        workspace.before_opened_locked_door,
        result_out->final_opened_locked_door_words,
        result_out->door_word_count
    );
    nv14_replay_trace_copy_words(
        workspace.before_triggered_trapdoor,
        result_out->final_triggered_trapdoor_words,
        result_out->door_word_count
    );

    for (tick = 0; tick < input_count; ++tick) {
        double pre_player_x = state->player.pos.x;
        double pre_player_y = state->player.pos.y;
        nv14_step_result step_result;
        int edge = inputs[tick].jump != 0 && !previous_jump;

        if (edge) result_out->jump_edges[result_out->jump_edge_count++] = tick;
        status = nv14_state_step(state, inputs[tick], &step_result);
        if (status == NV14_STATUS_UNSUPPORTED_TILE) {
            /* Match the Python evaluator: the failed tick counts as last_tick,
             * emits no point/events, but persistent state already changed by
             * the partial step remains visible in the final masks. */
            result_out->unsupported = 1;
            result_out->last_tick = (int64_t)tick;
            nv14_replay_trace_capture_static_masks(state, result_out);
            status = NV14_STATUS_OK;
            if (workspace.door_count != 0)
                status = nv14_replay_trace_capture_door_masks(
                    state, &workspace, result_out
                );
            if (status != NV14_STATUS_OK) {
                nv14_replay_trace_set_error(
                    &core_error,
                    status,
                    "unable to capture masks after unsupported native tile"
                );
                if (error_out != NULL) *error_out = core_error;
                return_status = NV14_REPLAY_TRACE_CORE_ERROR;
                goto fail;
            }
            break;
        }
        if (status != NV14_STATUS_OK || step_result.unsupported) {
            nv14_status reported = status != NV14_STATUS_OK
                ? status : NV14_STATUS_UNSUPPORTED_OBJECTS;
            nv14_replay_trace_set_error(
                &core_error,
                reported,
                status != NV14_STATUS_OK
                    ? nv14_status_string(status)
                    : "native replay step reported unsupported mechanics"
            );
            if (error_out != NULL) *error_out = core_error;
            return_status = NV14_REPLAY_TRACE_CORE_ERROR;
            goto fail;
        }
        nv14_replay_trace_capture_changed_static_masks(
            state, &step_result, result_out
        );
        status = NV14_STATUS_OK;
        if (workspace.door_count != 0)
            status = nv14_replay_trace_capture_door_masks(
                state, &workspace, result_out
            );
        if (status != NV14_STATUS_OK) {
            nv14_replay_trace_set_error(
                &core_error, status, "unable to capture native route masks"
            );
            if (error_out != NULL) *error_out = core_error;
            return_status = NV14_REPLAY_TRACE_CORE_ERROR;
            goto fail;
        }
        if ((step_result.collected_gold &&
             !nv14_replay_trace_record_gold_events(
                result_out,
                workspace.before_collected_gold,
                result_out->final_collected_gold_words,
                nv14_level_gold_count(level),
                (uint64_t)tick
            )) || (step_result.opened_exit &&
             !nv14_replay_trace_record_route_events(
                result_out,
                workspace.before_open_exit,
                result_out->final_open_exit_words,
                nv14_level_exit_count(level),
                (uint64_t)tick,
                NV14_REPLAY_ROUTE_EXIT_SWITCH
            )) || (workspace.door_count != 0 &&
             (!nv14_replay_trace_record_route_events(
                result_out,
                workspace.before_opened_locked_door,
                result_out->final_opened_locked_door_words,
                nv14_level_object_count(level),
                (uint64_t)tick,
                NV14_REPLAY_ROUTE_LOCKED_DOOR
            ) || !nv14_replay_trace_record_route_events(
                result_out,
                workspace.before_triggered_trapdoor,
                result_out->final_triggered_trapdoor_words,
                nv14_level_object_count(level),
                (uint64_t)tick,
                NV14_REPLAY_ROUTE_TRAPDOOR
            )))) {
            nv14_replay_trace_set_error(
                &core_error,
                NV14_STATUS_OUT_OF_BOUNDS,
                "native replay route-event capacity invariant was violated"
            );
            if (error_out != NULL) *error_out = core_error;
            return_status = NV14_REPLAY_TRACE_CORE_ERROR;
            goto fail;
        }
        if (step_result.collected_gold)
            nv14_replay_trace_copy_words(
                workspace.before_collected_gold,
                result_out->final_collected_gold_words,
                result_out->collected_gold_word_count
            );
        if (step_result.opened_exit)
            nv14_replay_trace_copy_words(
                workspace.before_open_exit,
                result_out->final_open_exit_words,
                result_out->open_exit_word_count
            );
        if (workspace.door_count != 0) {
            nv14_replay_trace_copy_words(
                workspace.before_opened_locked_door,
                result_out->final_opened_locked_door_words,
                result_out->door_word_count
            );
            nv14_replay_trace_copy_words(
                workspace.before_triggered_trapdoor,
                result_out->final_triggered_trapdoor_words,
                result_out->door_word_count
            );
        }

        if (step_result.jump_callable) {
            if (result_out->jump_callable_window_count != 0 &&
                result_out->jump_callable_windows[
                    result_out->jump_callable_window_count - 1u
                ].end_tick + UINT64_C(1) == (uint64_t)tick) {
                result_out->jump_callable_windows[
                    result_out->jump_callable_window_count - 1u
                ].end_tick = (uint64_t)tick;
            } else {
                nv14_replay_tick_window *window =
                    &result_out->jump_callable_windows[
                        result_out->jump_callable_window_count++
                    ];
                window->start_tick = (uint64_t)tick;
                window->end_tick = (uint64_t)tick;
            }
        }
        if (step_result.jumped)
            result_out->successful_jumps[
                result_out->successful_jump_count++
            ] = tick;
        else if (edge)
            result_out->missed_jump_edges[
                result_out->missed_jump_edge_count++
            ] = tick;
        previous_jump = inputs[tick].jump != 0;
        result_out->last_tick = (int64_t)tick;

        if (tick % trace_stride == 0 || step_result.level_complete ||
            step_result.dead || tick == input_count - 1u) {
            if (!nv14_replay_trace_append_point(
                    state, (uint64_t)tick, result_out, &core_error
                )) {
                if (error_out != NULL) *error_out = core_error;
                return_status = NV14_REPLAY_TRACE_CORE_ERROR;
                goto fail;
            }
        }
        if (step_result.dead) result_out->dead_tick = (int64_t)tick;
        if (step_result.level_complete) {
            double exit_x;
            double exit_y;
            double distance;
            result_out->finish_tick = (int64_t)tick;
            result_out->completed_exit_index = state->completed_exit_index;
            if (nv14_replay_trace_exit_centre(
                    level,
                    result_out->completed_exit_index,
                    &exit_x,
                    &exit_y
                )) {
                distance = hypot(
                    exit_x - pre_player_x,
                    exit_y - pre_player_y
                );
                if (isfinite(distance)) {
                    result_out->has_pre_finish_exit_distance = 1;
                    result_out->pre_finish_exit_distance = distance;
                }
            }
            break;
        }
        if (step_result.dead) break;
    }

    result_out->gold_bonus_ticks = state->gold_bonus_ticks;
    result_out->completed_exit_index = state->completed_exit_index;
    nv14_state_destroy(state);
    nv14_replay_trace_workspace_destroy(&workspace);
    nv14_replay_trace_clear_error(error_out);
    return NV14_REPLAY_TRACE_OK;

fail:
    nv14_state_destroy(state);
    nv14_replay_trace_workspace_destroy(&workspace);
    nv14_replay_trace_result_destroy(result_out);
    return return_status;
}

const char *nv14_replay_trace_status_string(nv14_replay_trace_status status)
{
    switch (status) {
        case NV14_REPLAY_TRACE_OK: return "ok";
        case NV14_REPLAY_TRACE_INVALID_ARGUMENT: return "invalid argument";
        case NV14_REPLAY_TRACE_OUT_OF_MEMORY: return "out of memory";
        case NV14_REPLAY_TRACE_CORE_ERROR: return "native engine error";
        default: return "unknown native replay-trace status";
    }
}

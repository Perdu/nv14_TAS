#include "nv14_dump.h"
#include "nv14_internal.h"

#include <string.h>

static nv14_status capture(
    nv14_state *state,
    const nv14_input *inputs,
    size_t input_count,
    nv14_player_dump_row *rows,
    size_t capacity,
    size_t *written_out,
    uint64_t *gold_ticks,
    uint64_t *gold_before
)
{
    size_t index;
    nv14_player_snapshot player;
    nv14_visual_snapshot visual;
    nv14_status status;
    if (written_out != NULL) *written_out = 0;
    if (state == NULL || written_out == NULL || capacity < input_count ||
        (input_count != 0 && (inputs == NULL || rows == NULL)))
        return NV14_STATUS_INVALID_ARGUMENT;
    if (gold_ticks != NULL) {
        size_t gold_count = nv14_level_gold_count(state->level);
        size_t words = (gold_count + 63) / 64;
        if (words && gold_before == NULL) return NV14_STATUS_INVALID_ARGUMENT;
        memset(gold_ticks, 0, gold_count * sizeof(*gold_ticks));
        if (words) memcpy(gold_before, state->collected_gold, words * sizeof(*gold_before));
    }
    status = nv14_state_get_visual(state, &visual);
    if (status != NV14_STATUS_OK) return status;
    status = nv14_state_get_player(state, &player);
    if (status != NV14_STATUS_OK) return status;
    for (index = 0; index < input_count; ++index) {
        if (inputs[index].left > 1 || inputs[index].right > 1 ||
            inputs[index].jump > 1 || inputs[index].jump_trigger < -1 ||
            inputs[index].jump_trigger > 1)
            return NV14_STATUS_INVALID_ARGUMENT;
    }
    for (index = 0; index < input_count; ++index) {
        nv14_player_dump_row *row = &rows[index];
        if (player.dead || nv14_state_level_complete(state)) break;
        memset(row, 0, sizeof(*row));
        row->input = inputs[index];
        if (row->input.jump_trigger < 0)
            row->input.jump_trigger = (int8_t)(
                row->input.jump && !player.previous_jump_held
            );
        status = nv14_state_step(state, inputs[index], &row->step);
        if (status != NV14_STATUS_OK) return status;
        if (row->step.unsupported) return NV14_STATUS_UNSUPPORTED_OBJECTS;
        status = nv14_state_get_player(state, &row->player);
        if (status != NV14_STATUS_OK) return status;
        status = nv14_state_get_visual(state, &row->visual);
        if (status != NV14_STATUS_OK) return status;
        row->gold_bonus_ticks = nv14_state_gold_bonus_ticks(state);
        /* Optional video capture only: enumerate changed bits on pickup ticks.
         * No gameplay hooks, scene snapshots or per-gold work on other ticks. */
        if (gold_ticks != NULL && row->step.collected_gold) {
            size_t word, words = (nv14_level_gold_count(state->level) + 63) / 64;
            for (word = 0; word < words; ++word) {
                uint64_t current = state->collected_gold[word];
                uint64_t changed = current & ~gold_before[word];
                size_t bit = word * 64;
                for (; changed; changed >>= 1, ++bit)
                    if (changed & 1) gold_ticks[bit] = (uint64_t)index + 1;
                gold_before[word] = current;
            }
        }
        player = row->player;
        *written_out = index + 1;
    }
    return NV14_STATUS_OK;
}

nv14_status nv14_player_dump_capture(
    nv14_state *state, const nv14_input *inputs, size_t input_count,
    nv14_player_dump_row *rows, size_t capacity, size_t *written_out
)
{
    return capture(state, inputs, input_count, rows, capacity, written_out, NULL, NULL);
}

nv14_status nv14_player_dump_capture_gold(
    nv14_state *state, const nv14_input *inputs, size_t input_count,
    nv14_player_dump_row *rows, size_t capacity, size_t *written_out,
    uint64_t *gold_ticks, size_t gold_capacity, uint64_t *gold_before
)
{
    if (state == NULL || gold_ticks == NULL ||
        gold_capacity < nv14_level_gold_count(state->level))
        return NV14_STATUS_INVALID_ARGUMENT;
    return capture(state, inputs, input_count, rows, capacity, written_out,
                   gold_ticks, gold_before);
}

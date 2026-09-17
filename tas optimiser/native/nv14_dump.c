#include "nv14_dump.h"

#include <string.h>

nv14_status nv14_player_dump_capture(
    nv14_state *state,
    const nv14_input *inputs,
    size_t input_count,
    nv14_player_dump_row *rows,
    size_t capacity,
    size_t *written_out
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
        player = row->player;
        *written_out = index + 1;
    }
    return NV14_STATUS_OK;
}

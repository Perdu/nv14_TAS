#ifndef NV14_DUMP_H
#define NV14_DUMP_H

#include "nv14_core.h"
#include "nv14_visual.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NV14_PLAYER_DUMP_ABI_VERSION 1u

typedef struct nv14_player_dump_row {
    nv14_input input; /* jump_trigger is resolved to 0/1 before stepping. */
    nv14_step_result step;
    nv14_player_snapshot player;
    nv14_visual_snapshot visual;
    uint64_t gold_bonus_ticks;
} nv14_player_dump_row;

/* Capture post-step player/visual state into a caller-owned chunk. The state
 * must have visual tracking enabled. Stops after including the first death or
 * completion row; an already-terminal state produces zero rows. No capture-buffer
 * allocation, formatting, Python callbacks, or synthetic inputs occur here.
 * capacity must be at least input_count; invalid arguments are rejected before
 * stepping. On a core error, written_out counts only completed captured rows. */
nv14_status nv14_player_dump_capture(
    nv14_state *state,
    const nv14_input *inputs,
    size_t input_count,
    nv14_player_dump_row *rows,
    size_t capacity,
    size_t *written_out
);

/* Additive video-only capture. gold_ticks has gold_capacity entries (at least
 * the level's gold count); receives 1-based chunk-local pickup ticks, or zero.
 * gold_before is caller scratch with ceil(gold_count/64) words. No allocations
 * or callbacks occur. Previously collected bits never become new events. */
nv14_status nv14_player_dump_capture_gold(
    nv14_state *state, const nv14_input *inputs, size_t input_count,
    nv14_player_dump_row *rows, size_t capacity, size_t *written_out,
    uint64_t *gold_ticks, size_t gold_capacity, uint64_t *gold_before
);

#ifdef __cplusplus
}
#endif
#endif

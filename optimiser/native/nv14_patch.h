#ifndef NV14_PATCH_H
#define NV14_PATCH_H

/*
 * Ordered sparse-patch evaluator used by Auto.
 *
 * Python owns mutation policy and supplies complete, ordered candidate patches.
 * This unit owns only the hot mechanics: exact prefix checkpoint construction,
 * allocation-free state restoration, candidate simulation, hard interaction
 * and jump checks, route-distance scoring, and deterministic best retention.
 */

#include "nv14_search.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NV14_PATCH_ABI_VERSION 2u

typedef struct nv14_patch_assignment {
    size_t frame;
    nv14_input input;
} nv14_patch_assignment;

/* Spans form a contiguous partition of the flat assignment array.  Every span
   is non-empty and its assignments have strictly increasing frame numbers. */
typedef struct nv14_patch_span {
    size_t first_assignment;
    size_t assignment_count;
} nv14_patch_span;

typedef enum nv14_patch_tie_policy {
    /* Equal finite scores retain the first feasible patch supplied by Python. */
    NV14_PATCH_TIE_SUPPLIED_ORDER = 0,
    /* Auto's randomized-search rule: fewer held-input edits, then the
       lexicographically smaller packed L/R/J replay, wins an equal finite tie. */
    NV14_PATCH_TIE_LOW_EDIT_LEX = 1
} nv14_patch_tie_policy;

typedef struct nv14_patch_spec {
    uint32_t abi_version;
    uint32_t struct_size;

    const nv14_input *replay;
    size_t replay_count;
    size_t target_frame;

    const nv14_patch_assignment *assignments;
    size_t assignment_count;
    const nv14_patch_span *patches;
    size_t patch_count;

    /* NULL gives every feasible endpoint score 0.  A non-NULL target uses the
       exact weighted CompactTracePoint distance used by Auto. */
    const nv14_search_trace_target *trace_target;

    /* Every required group is hard-required and every avoided group is
       hard-forbidden.  Atoms inside one group are alternatives (logical OR). */
    const nv14_search_interaction_atom *required_atoms;
    size_t required_atom_count;
    const nv14_search_interaction_group *required_groups;
    size_t required_group_count;
    const nv14_search_interaction_atom *avoided_atoms;
    size_t avoided_atom_count;
    const nv14_search_interaction_group *avoided_groups;
    size_t avoided_group_count;

    /* Required and ignored frame arrays are strictly increasing and bounded by
       target_frame.  When required_jump_any is set, one non-ignored required
       frame must call Player.jump(); otherwise every required frame must do so.
       ignored_jump_frames implements Auto's "new jump" rule by preventing seed
       successes at those frames from satisfying the hard requirement. */
    const size_t *required_jump_frames;
    size_t required_jump_count;
    const size_t *ignored_jump_frames;
    size_t ignored_jump_count;
    uint8_t required_jump_any;
    uint8_t prune_inactive_jump;
    uint8_t tie_policy;
    /* Materialise player snapshots only when Python policy needs them. */
    uint8_t capture_endpoints;
    uint8_t reserved_flags[4];

    /* Optional absolute floor for the terminal Player.jump_events counter.
       Auto uses seed_jump_events + 1 when a repair must add a genuinely new
       success even if it also displaces an existing successful jump. */
    uint64_t minimum_jump_events;

    /* Zero is unlimited.  Seed simulation and checkpoint creation are setup;
       each attempted patch is charged independently from its first assignment
       through target_frame, even when candidates share a checkpoint. */
    uint64_t max_simulated_ticks;

    /* State immediately before prefix_frame.  The session wrapper owns this
       cached base-replay prefix; prefix_frame must not follow any candidate's
       first assignment or any required jump frame. */
    const nv14_state *prefix_state;
    size_t prefix_frame;

    nv14_search_cancel_fn cancel;
    void *cancel_userdata;
    uint64_t cancel_poll_interval;
} nv14_patch_spec;

typedef struct nv14_patch_candidate_result {
    uint8_t feasible;
    uint8_t has_endpoint;
    uint8_t dead;
    uint8_t inactive_jump_pruned;
    uint8_t avoided_interaction_pruned;
    uint8_t reserved[3];
    double score;
    nv14_player_snapshot endpoint;
} nv14_patch_candidate_result;

typedef struct nv14_patch_stats {
    uint64_t branches;
    uint64_t simulated_ticks;
    uint64_t cloned_states;
    uint64_t inactive_jump_prunes;
    uint64_t dead_prunes;
    uint64_t avoided_interaction_prunes;
} nv14_patch_stats;

typedef struct nv14_patch_result {
    uint32_t abi_version;
    uint32_t struct_size;
    nv14_patch_candidate_result *candidates;
    size_t candidate_count;
    /* SIZE_MAX when no fully evaluated feasible patch was found. */
    size_t best_patch_index;
    uint8_t budget_exhausted;
    uint8_t reserved[7];
    nv14_patch_stats stats;
} nv14_patch_result;

int nv14_patch_result_init(
    nv14_patch_result *result,
    size_t caller_size
);

/* result_out must be in the clean state produced by init or destroy. */
nv14_search_status nv14_patch_run(
    const nv14_level *level,
    const nv14_patch_spec *spec,
    nv14_patch_result *result_out,
    nv14_error *error_out
);

void nv14_patch_result_destroy(nv14_patch_result *result);

#ifdef __cplusplus
}
#endif

#endif /* NV14_PATCH_H */

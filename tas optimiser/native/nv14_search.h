#ifndef NV14_SEARCH_H
#define NV14_SEARCH_H

/*
 * Generic native replay-search kernels.
 *
 * Python owns policy: it selects mutable frames, supplies each frame's ordered
 * input choices, compiles objectives/constraints into this data-only spec, and
 * decides whether to accept the returned candidate.  This module owns the hot
 * mechanics only: Cartesian choice enumeration or constrained active-input run
 * enumeration, state cloning, exact simulation, deduplication, pruning,
 * scoring, and deterministic candidate retention.
 */

#include "nv14_core.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NV14_SEARCH_ABI_VERSION 3u

typedef enum nv14_search_status {
    NV14_SEARCH_OK = 0,
    NV14_SEARCH_INVALID_ARGUMENT = 1,
    NV14_SEARCH_OUT_OF_MEMORY = 2,
    NV14_SEARCH_CORE_ERROR = 3,
    NV14_SEARCH_CANCELLED = 4
} nv14_search_status;

typedef enum nv14_search_objective {
    NV14_SEARCH_MAX_X = 0,
    NV14_SEARCH_MIN_X = 1,
    NV14_SEARCH_MAX_Y = 2,
    NV14_SEARCH_MIN_Y = 3,
    NV14_SEARCH_MIN_DISTANCE = 4,
    /* Weighted route-state distance.  This is deliberately data-driven: the
       caller supplies a compact reference point while the kernel evaluates
       the exact terminal state reached by each candidate. */
    NV14_SEARCH_TRACE_DISTANCE = 5,
    NV14_SEARCH_CONSTANT = 6
} nv14_search_objective;

typedef struct nv14_search_trace_target {
    double x;
    double y;
    double vx;
    double vy;
    int32_t player_state;
    int8_t wall_x;
    int8_t floor_x;
    int8_t floor_y;
    uint8_t in_air;
    uint8_t near_wall;
    uint8_t previous_jump_held;
    uint8_t reserved;

    /* Python supplies the objective definition; native kernels evaluate it. */
    double position_weight;
    double velocity_weight;
    double contact_mismatch_penalty;
    double in_air_mismatch_penalty;
    double near_wall_mismatch_penalty;
    double gold_bit_penalty;
    double mine_bit_penalty;
    double exit_bit_penalty;
    double locked_door_bit_penalty;
    double trapdoor_bit_penalty;

    const uint64_t *collected_gold;
    size_t collected_gold_word_count;
    const uint64_t *exploded_mine;
    size_t exploded_mine_word_count;
    const uint64_t *open_exit;
    size_t open_exit_word_count;
    /* Door masks use serialized object load indices. */
    const uint64_t *opened_locked_door;
    size_t opened_locked_door_word_count;
    const uint64_t *triggered_trapdoor;
    size_t triggered_trapdoor_word_count;
} nv14_search_trace_target;

/* Shared endpoint evaluator used by Cartesian and sparse-patch kernels. */
double nv14_search_trace_distance(
    const nv14_search_trace_target *target,
    const nv14_state *state
);

int nv14_search_trace_target_valid(
    const nv14_search_trace_target *target
);

typedef enum nv14_search_interaction_kind {
    NV14_SEARCH_INTERACTION_GOLD = 0,
    NV14_SEARCH_INTERACTION_EXIT_SWITCH = 1,
    NV14_SEARCH_INTERACTION_LOCKED_DOOR = 2,
    NV14_SEARCH_INTERACTION_TRAPDOOR = 3
} nv14_search_interaction_kind;

typedef struct nv14_search_target {
    double x;
    double y;
} nv14_search_target;

typedef struct nv14_search_interaction_atom {
    uint8_t kind;
    uint8_t reserved[7];
    size_t index;
} nv14_search_interaction_atom;

typedef struct nv14_search_interaction_group {
    size_t first_atom;
    size_t atom_count;
} nv14_search_interaction_group;

typedef int (*nv14_search_cancel_fn)(void *userdata);

typedef struct nv14_search_spec {
    uint32_t abi_version;
    uint32_t struct_size;

    const nv14_input *replay;
    size_t replay_count;
    size_t target_frame;

    /* Strictly increasing mutable replay indices.  choices_begin has
       mutable_count + 1 entries and indexes the flat choices array. */
    const size_t *mutable_frames;
    size_t mutable_count;
    const size_t *choices_begin;
    const nv14_input *choices;
    size_t choice_count;

    nv14_search_objective objective;
    const nv14_search_target *targets;
    size_t target_count;
    const nv14_search_trace_target *trace_target;

    uint8_t has_x_window;
    uint8_t has_y_window;
    uint8_t prune_inactive_jump;
    /* Physics pruning is valid only when every supplied choice preserves the
       replay frame's jump and jump_trigger fields. The kernel validates this
       precondition; Python currently enables it only for direction search. */
    uint8_t physics_prune;
    uint8_t skip_unchanged_final_step;
    /* When true, every interaction condition and the configured jump
       requirement is a hard feasibility condition rather than a dominance
       dimension relative to the incumbent. */
    uint8_t require_all_constraints;
    /* Treat required_jump_frames as alternatives of which any one must
       succeed.  ignored_jump_frames can exclude successes already present in
       a damaged seed, so repair searches can require a genuinely new event. */
    uint8_t required_jump_any;
    uint8_t tie_break_low_edit_lex;
    uint8_t reserved_pruning;
    double x_minimum;
    double x_maximum;
    double y_minimum;
    double y_maximum;

    const nv14_search_interaction_atom *required_atoms;
    size_t required_atom_count;
    const nv14_search_interaction_group *required_groups;
    size_t required_group_count;
    const nv14_search_interaction_atom *avoided_atoms;
    size_t avoided_atom_count;
    const nv14_search_interaction_group *avoided_groups;
    size_t avoided_group_count;

    /* One byte per group: nonzero means that hard condition is present in the
       incumbent's terminal state. */
    const uint8_t *incumbent_missing_requirements;
    const uint8_t *incumbent_violated_avoidances;

    /* Required jump frames are sorted.  The incumbent array has one byte per
       required frame and is also the auxiliary state appended to dedup keys. */
    const size_t *required_jump_frames;
    size_t required_jump_count;
    const uint8_t *incumbent_missing_jumps;
    const size_t *ignored_jump_frames;
    size_t ignored_jump_count;
    uint64_t minimum_jump_events;

    double incumbent_score;
    uint8_t incumbent_feasible;
    uint8_t reserved_flags[7];

    /* Zero is unlimited. Prefix materialisation is performed by the session
       wrapper and is intentionally outside this search-work allowance. */
    uint64_t max_simulated_ticks;

    /* The supplied prefix state is the state immediately before prefix_frame.
       It may come from a native per-session cache. */
    const nv14_state *prefix_state;
    size_t prefix_frame;

    /* Called at a bounded node interval while the wrapper has released its
       runtime lock.  A nonzero return cancels the search. */
    nv14_search_cancel_fn cancel;
    void *cancel_userdata;
    uint64_t cancel_poll_interval;
} nv14_search_spec;

typedef struct nv14_search_stats {
    uint64_t visited_nodes;
    uint64_t evaluated_leaves;
    uint64_t simulated_ticks;
    uint64_t cloned_states;
    uint64_t inactive_jump_prunes;
    uint64_t missed_jump_prunes;
    uint64_t dead_prunes;
    uint64_t deduplicated_prunes;
    uint64_t physics_prunes;
    uint64_t avoided_interaction_prunes;
} nv14_search_stats;

typedef struct nv14_search_result {
    /* Initialized by nv14_search_result_init. They protect the result buffer
       independently of the input-spec size check. */
    uint32_t abi_version;
    uint32_t struct_size;
    uint8_t improved;
    uint8_t feasible;
    uint8_t budget_exhausted;
    uint8_t reserved[5];
    double score;
    nv14_input *best_inputs;
    size_t best_input_count;
    uint8_t *missing_requirements;
    size_t missing_requirement_count;
    uint8_t *violated_avoidances;
    size_t violated_avoidance_count;
    uint8_t *missing_jumps;
    size_t missing_jump_count;
    nv14_player_snapshot player;
    uint8_t has_player_snapshot;
    uint8_t reserved_snapshot[7];
    nv14_search_stats stats;
} nv14_search_result;

/* Generic constrained-run search.  Python supplies the inactive and active
   input streams and the temporal policy as scalar bounds.  The kernel does
   not attach meaning to the active input; jump-pattern uses the JUMPED event
   requirement below, while other callers may enumerate arbitrary held-input
   runs without an event requirement. */
typedef enum nv14_pattern_start_event {
    NV14_PATTERN_EVENT_JUMPED = 1u << 0
} nv14_pattern_start_event;

typedef struct nv14_pattern_span {
    size_t start_frame;
    size_t length;
} nv14_pattern_span;

typedef struct nv14_pattern_search_spec {
    uint32_t abi_version;
    uint32_t struct_size;

    const nv14_input *replay;
    size_t replay_count;
    size_t target_frame;
    size_t range_start;
    size_t range_end;

    /* One entry per frame in the inclusive range, indexed relative to
       range_start.  The inactive stream is used outside spans and the active
       stream inside them. */
    const nv14_input *inactive_inputs;
    const nv14_input *active_inputs;
    size_t pattern_input_count;

    nv14_search_objective objective;
    const nv14_search_target *targets;
    size_t target_count;
    uint8_t has_x_window;
    uint8_t has_y_window;
    uint8_t reserved_windows[6];
    double x_minimum;
    double x_maximum;
    double y_minimum;
    double y_maximum;

    size_t run_count_min;
    size_t run_count_max;
    size_t run_length_min;
    /* Per possible absolute start frame, indexed relative to range_start.
       A value below run_length_min disables that start. */
    const size_t *start_max_lengths;
    size_t start_max_length_count;
    size_t minimum_gap;
    const size_t *fixed_starts;
    size_t fixed_start_count;
    uint32_t required_start_event_mask;
    uint32_t reserved_event;

    size_t top_results;
    /* Completed first-run branches are numbered in deterministic DFS order.
       A shard visits ordinals for which ordinal % shard_count == shard_index. */
    size_t shard_index;
    size_t shard_count;

    const nv14_state *prefix_state;
    size_t prefix_frame;
    nv14_search_cancel_fn cancel;
    void *cancel_userdata;
    uint64_t cancel_poll_interval;
} nv14_pattern_search_spec;

typedef struct nv14_pattern_search_stats {
    uint64_t attempted_starts;
    uint64_t successful_starts;
    uint64_t evaluated_candidates;
    uint64_t deduplicated_branches;
    uint64_t simulated_ticks;
    uint64_t cloned_states;
} nv14_pattern_search_stats;

typedef struct nv14_pattern_search_candidate {
    double score;
    nv14_pattern_span *spans;
    size_t span_count;
    nv14_player_snapshot player;
    uint64_t traversal_ordinal;
} nv14_pattern_search_candidate;

typedef struct nv14_pattern_search_result {
    uint32_t abi_version;
    uint32_t struct_size;
    nv14_pattern_search_candidate *candidates;
    size_t candidate_count;
    size_t candidate_capacity;
    nv14_pattern_search_stats stats;
} nv14_pattern_search_result;

/* Initializes an empty result object. Pass sizeof(*result) from the caller so
   a newer library cannot overwrite an older caller's smaller result buffer.
   Returns zero for NULL, undersized, or unrepresentably large buffers. Call
   this once before the first run. A successful result owns its array fields
   until destroy is called; destroy returns it to the initialized state. */
int nv14_search_result_init(
    nv14_search_result *result,
    size_t caller_size
);

/* result_out must be in the clean state produced by init or destroy. Passing
   an undestroyed successful result is rejected so its owned arrays cannot be
   leaked. Invalid specifications leave a clean result safe to destroy. */
nv14_search_status nv14_search_run(
    const nv14_level *level,
    const nv14_search_spec *spec,
    nv14_search_result *result_out,
    nv14_error *error_out
);

/* Frees owned arrays and leaves the result initialized for another run.
   ABI-incompatible result buffers are ignored rather than dereferenced. */
void nv14_search_result_destroy(nv14_search_result *result);

int nv14_pattern_search_result_init(
    nv14_pattern_search_result *result,
    size_t caller_size
);

nv14_search_status nv14_pattern_search_run(
    const nv14_level *level,
    const nv14_pattern_search_spec *spec,
    nv14_pattern_search_result *result_out,
    nv14_error *error_out
);

void nv14_pattern_search_result_destroy(nv14_pattern_search_result *result);
const char *nv14_search_status_string(nv14_search_status status);

#ifdef __cplusplus
}
#endif

#endif /* NV14_SEARCH_H */

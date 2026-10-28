#ifndef NV14_AUTO_H
#define NV14_AUTO_H

/*
 * Generic native replay trajectory evaluator for autonomous search.
 *
 * Python owns replay policy, including the packed-replay neutral sentinel.
 * This module owns only the hot mechanics: initial-state construction, exact
 * replay simulation, route-event detection, and compact trace capture.
 * Consequently nv14_replay_trace_run() deliberately accepts an empty replay
 * and does not require the final input to be neutral.
 */

#include "nv14_core.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NV14_REPLAY_TRACE_ABI_VERSION 2u
#define NV14_REPLAY_ANALYSIS_ABI_VERSION 1u

typedef enum nv14_replay_trace_status {
    NV14_REPLAY_TRACE_OK = 0,
    NV14_REPLAY_TRACE_INVALID_ARGUMENT = 1,
    NV14_REPLAY_TRACE_OUT_OF_MEMORY = 2,
    NV14_REPLAY_TRACE_CORE_ERROR = 3
} nv14_replay_trace_status;

typedef enum nv14_replay_route_event_kind {
    NV14_REPLAY_ROUTE_EXIT_SWITCH = 0,
    NV14_REPLAY_ROUTE_LOCKED_DOOR = 1,
    NV14_REPLAY_ROUTE_TRAPDOOR = 2
} nv14_replay_route_event_kind;

/* Scalar post-step route-matching state.  Arbitrary-width masks for point i
 * are stored in the result's five flat trace-mask arrays beginning at
 * i * the corresponding *_word_count. */
typedef struct nv14_replay_trace_point {
    uint64_t tick;
    double x;
    double y;
    double vx;
    double vy;
    uint64_t jump_events;
    uint64_t gold_bonus_ticks;
    int32_t player_state;
    int8_t wall_x;
    int8_t floor_x;
    int8_t floor_y;
    uint8_t in_air;
    uint8_t near_wall;
    uint8_t previous_jump_held;
    uint8_t complete;
    uint8_t dead;
    uint8_t reserved[4];
} nv14_replay_trace_point;

typedef struct nv14_replay_gold_event {
    size_t gold_index;
    uint64_t tick;
} nv14_replay_gold_event;

/* Inclusive pre-Think tick range in which a fresh edge calls Player.jump(). */
typedef struct nv14_replay_tick_window {
    uint64_t start_tick;
    uint64_t end_tick;
} nv14_replay_tick_window;

/* EXIT_SWITCH indices are exit state indices.  LOCKED_DOOR and TRAPDOOR
 * indices are serialized object load indices, matching the corresponding
 * persistent masks. */
typedef struct nv14_replay_route_event {
    size_t index;
    uint64_t tick;
    uint8_t kind;
    uint8_t reserved[7];
} nv14_replay_route_event;

typedef struct nv14_replay_trace_result {
    /* Initialized by nv14_replay_trace_result_init.  These fields protect the
     * output buffer independently of the input arguments. */
    uint32_t abi_version;
    uint32_t struct_size;

    /* Set after a successful call, including an empty replay.  Call destroy
     * before reusing the result even when it happens to own no arrays. */
    uint8_t populated;
    uint8_t unsupported;
    uint8_t has_pre_finish_exit_distance;
    uint8_t reserved_flags[5];

    /* -1 denotes absence.  A death on finish_tick is retained exactly; the
     * Python policy layer decides that completion wins on the same tick. */
    int64_t finish_tick;
    int64_t dead_tick;
    int64_t last_tick;
    int64_t completed_exit_index;
    double pre_finish_exit_distance;
    uint64_t gold_bonus_ticks;

    nv14_replay_trace_point *trace;
    size_t trace_count;
    size_t trace_capacity;

    /* Flat row-major trace masks.  Each array contains trace_capacity rows;
     * only the first trace_count rows are populated. */
    uint64_t *trace_collected_gold_words;
    uint64_t *trace_exploded_mine_words;
    uint64_t *trace_open_exit_words;
    uint64_t *trace_opened_locked_door_words;
    uint64_t *trace_triggered_trapdoor_words;

    size_t collected_gold_word_count;
    size_t exploded_mine_word_count;
    size_t open_exit_word_count;
    /* Door masks are indexed by serialized object load index, so their width
     * is derived from nv14_level_object_count(), not the number of doors. */
    size_t door_word_count;

    uint64_t *final_collected_gold_words;
    uint64_t *final_exploded_mine_words;
    uint64_t *final_open_exit_words;
    uint64_t *final_opened_locked_door_words;
    uint64_t *final_triggered_trapdoor_words;

    uint64_t *successful_jumps;
    size_t successful_jump_count;
    uint64_t *jump_edges;
    size_t jump_edge_count;
    uint64_t *missed_jump_edges;
    size_t missed_jump_edge_count;
    nv14_replay_tick_window *jump_callable_windows;
    size_t jump_callable_window_count;

    nv14_replay_gold_event *gold_events;
    size_t gold_event_count;
    size_t gold_event_capacity;
    nv14_replay_route_event *route_control_events;
    size_t route_control_event_count;
    size_t route_control_event_capacity;
} nv14_replay_trace_result;

typedef enum nv14_replay_alignment_objective {
    NV14_REPLAY_ALIGNMENT_SPEEDRUN = 0,
    NV14_REPLAY_ALIGNMENT_HIGHSCORE = 1
} nv14_replay_alignment_objective;

/* Python owns these policy weights and bounds.  The native query merely scans
 * two already-evaluated trajectory buffers without materialising point
 * objects. */
typedef struct nv14_replay_alignment_spec {
    uint32_t abi_version;
    uint32_t struct_size;
    uint64_t max_alignment;
    uint64_t max_negative_alignment;
    uint64_t scan_limit;
    int64_t reference_completion_exit_index;
    double position_tolerance;
    double velocity_tolerance;
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
    uint8_t objective;
    uint8_t reserved[7];
} nv14_replay_alignment_spec;

typedef struct nv14_replay_alignment_result {
    uint32_t abi_version;
    uint32_t struct_size;
    uint8_t found;
    uint8_t contact_matches;
    uint8_t static_matches;
    uint8_t reserved[5];
    int64_t candidate_tick;
    int64_t reference_tick;
    int64_t offset;
    int64_t score_lead;
    double distance;
} nv14_replay_alignment_result;

/* Bounds and policy for the exact route/contact matcher used by sectional
 * splice repair.  Tick and offset bounds are inclusive.  Gold remains a soft
 * distance component; every other persistent route mask must match exactly. */
typedef struct nv14_replay_splice_alignment_spec {
    uint32_t abi_version;
    uint32_t struct_size;
    uint64_t candidate_start_tick;
    uint64_t candidate_end_tick;
    uint64_t minimum_run_length;
    int64_t minimum_offset;
    int64_t maximum_offset;
    double position_tolerance;
    double velocity_tolerance;
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
} nv14_replay_splice_alignment_spec;

typedef struct nv14_replay_splice_alignment_result {
    uint32_t abi_version;
    uint32_t struct_size;
    uint8_t found;
    uint8_t contact_matches;
    uint8_t static_matches;
    uint8_t reserved[5];
    int64_t candidate_tick;
    int64_t reference_tick;
    int64_t offset;
    int64_t score_lead;
    uint64_t run_length;
    double distance;
} nv14_replay_splice_alignment_result;

/* Pass sizeof(*result) as caller_size.  Returns zero for NULL, undersized, or
 * unrepresentably large buffers. */
int nv14_replay_trace_result_init(
    nv14_replay_trace_result *result,
    size_t caller_size
);

/* Frees every owned array and returns an ABI-compatible result to the clean
 * initialized state.  ABI-incompatible buffers are ignored. */
void nv14_replay_trace_result_destroy(nv14_replay_trace_result *result);

/* Exact-tick lookup over a dense or strided trace.  Returns -1 for invalid
 * arguments, 0 when absent, and 1 with index_out populated when found. */
int nv14_replay_trace_find_point_index(
    const nv14_replay_trace_result *result,
    uint64_t tick,
    size_t *index_out
);

/* Find the best stable alignment under caller-supplied policy.  The query is
 * allocation-free and returns -1 for invalid arguments, 0 for no match, and
 * 1 for a populated result. */
int nv14_replay_trace_find_alignment(
    const nv14_replay_trace_result *candidate,
    const nv14_replay_trace_result *reference,
    const nv14_replay_alignment_spec *spec,
    nv14_replay_alignment_result *result_out
);

/* Find the best stable splice match run in one bounded candidate region and
 * inclusive offset range.  Ranking exactly follows the Python sectional
 * suffix scan: run length, end tick, score lead, mean distance, then offset. */
int nv14_replay_trace_find_splice_alignment(
    const nv14_replay_trace_result *candidate,
    const nv14_replay_trace_result *reference,
    const nv14_replay_splice_alignment_spec *spec,
    nv14_replay_splice_alignment_result *result_out
);

/* Find the first persistent route-control divergence.  Only row indices are
 * returned; language bindings may materialise the few differing masks on
 * demand.  Return values follow the same -1/0/1 convention. */
int nv14_replay_trace_find_route_divergence(
    const nv14_replay_trace_result *candidate,
    const nv14_replay_trace_result *reference,
    int64_t reference_offset,
    int64_t reference_completion_exit_index,
    size_t *candidate_index_out,
    size_t *reference_index_out
);

/* Bounded form used by piecewise splice legs.  Bounds are inclusive. */
int nv14_replay_trace_find_route_divergence_bounded(
    const nv14_replay_trace_result *candidate,
    const nv14_replay_trace_result *reference,
    int64_t reference_offset,
    int64_t reference_completion_exit_index,
    uint64_t candidate_start_tick,
    uint64_t candidate_end_tick,
    size_t *candidate_index_out,
    size_t *reference_index_out
);

/* Simulate inputs from a fresh initial state.  trace_stride must be positive.
 * NV14_STATUS_UNSUPPORTED_TILE is represented as a successful partial result
 * with unsupported=1, exactly like nv14_auto.py's AutoEvaluation.  Other core
 * failures return NV14_REPLAY_TRACE_CORE_ERROR and leave result_out clean. */
nv14_replay_trace_status nv14_replay_trace_run(
    const nv14_level *level,
    const nv14_input *inputs,
    size_t input_count,
    size_t trace_stride,
    nv14_replay_trace_result *result_out,
    nv14_error *error_out
);

const char *nv14_replay_trace_status_string(nv14_replay_trace_status status);

#ifdef __cplusplus
}
#endif

#endif /* NV14_AUTO_H */

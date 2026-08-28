#ifndef NV14_CORE_H
#define NV14_CORE_H

/*
 * Native hot-path core for the n v1.4 TAS replay optimiser.
 *
 * The API deliberately keeps level and state layouts opaque.  This lets the
 * object implementation grow without making Cython-generated clients depend
 * on compiler padding or on an internal object union.  All gameplay scalar
 * values are binary64 doubles; callers must compile the implementation without
 * fast-math or floating-point contraction.
 */

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NV14_CORE_ABI_VERSION 2u
#define NV14_MAP_CHARS 713u
#define NV14_GRID_COLS 31
#define NV14_GRID_ROWS 23
#define NV14_TILE_COLS 33
#define NV14_TILE_ROWS 25
#define NV14_OBJECT_PARAM_CAPACITY 10u

typedef struct nv14_level nv14_level;
typedef struct nv14_state nv14_state;

typedef enum nv14_status {
    NV14_STATUS_OK = 0,
    NV14_STATUS_INVALID_ARGUMENT = 1,
    NV14_STATUS_OUT_OF_MEMORY = 2,
    NV14_STATUS_INVALID_LEVEL = 3,
    NV14_STATUS_UNSUPPORTED_TILE = 4,
    NV14_STATUS_UNSUPPORTED_OBJECTS = 5,
    NV14_STATUS_OUT_OF_BOUNDS = 6,
    NV14_STATUS_BUFFER_TOO_SMALL = 7,
    NV14_STATUS_HOOK_ERROR = 8,
    NV14_STATUS_PHASE_ERROR = 9
} nv14_status;

typedef enum nv14_player_state {
    NV14_PLAYER_STANDING = 0,
    NV14_PLAYER_RUNNING = 1,
    NV14_PLAYER_SKIDDING = 2,
    NV14_PLAYER_JUMPING = 3,
    NV14_PLAYER_FALLING = 4,
    NV14_PLAYER_WALLSLIDING = 5,
    NV14_PLAYER_RAGDOLL = 6,
    NV14_PLAYER_CELEBRATING = 7
} nv14_player_state;

typedef enum nv14_mask_kind {
    NV14_MASK_COLLECTED_GOLD = 0,
    NV14_MASK_EXPLODED_MINE = 1,
    NV14_MASK_OPEN_EXIT = 2
} nv14_mask_kind;

typedef enum nv14_capability {
    NV14_CAP_TILE_COLLISION = 1u << 0,
    NV14_CAP_STATIC_OBJECTS = 1u << 1,
    NV14_CAP_ONEWAY_PLATFORM = 1u << 2,
    NV14_CAP_LAUNCH_PAD = 1u << 3,
    NV14_CAP_COMPLETE_STEP = 1u << 4,
    NV14_CAP_OBJECT_HOOKS = 1u << 5
} nv14_capability;

/* One bit at the serialized object type position (0..31). */
typedef uint32_t nv14_object_type_mask;

typedef struct nv14_error {
    nv14_status code;
    size_t byte_offset;
    int object_type;
    int tile_id;
    int tile_i;
    int tile_j;
    char message[192];
} nv14_error;

/* jump_trigger: -1 derives the edge from held input, 0/1 is explicit. */
typedef struct nv14_input {
    uint8_t left;
    uint8_t right;
    uint8_t jump;
    int8_t jump_trigger;
} nv14_input;

typedef struct nv14_vec2 {
    double x;
    double y;
} nv14_vec2;

/*
 * Complete mutable Player payload.  It is a value snapshot, not an ABI view
 * into nv14_state, and may safely cross the Cython boundary.
 */
typedef struct nv14_player_snapshot {
    nv14_vec2 pos;
    nv14_vec2 oldpos;
    double r;
    double xw;
    double yw;
    double maxspeed_air;
    double maxspeed_ground;
    double ground_accel;
    double air_accel;
    double norm_grav;
    double jump_grav;
    double norm_drag;
    double win_drag;
    double wall_friction;
    double skid_friction;
    double stand_friction;
    double jump_amt;
    double jump_y_bias;
    int32_t max_jump_time;
    double terminal_vel;
    double g;
    double d;
    int32_t state;
    int32_t jump_timer;
    uint8_t was_in_air;
    uint8_t in_air;
    uint8_t near_wall;
    uint8_t dead;
    nv14_vec2 wall_n;
    nv14_vec2 floor_n;
    nv14_vec2 floor_n0;
    nv14_vec2 floor_n1;
    nv14_vec2 old_v;
    int32_t floor_count;
    uint8_t previous_jump_held;
    uint8_t celeb_was_in_air;
    uint16_t reserved_flags;
    uint64_t jump_events;
    int32_t cell_i;
    int32_t cell_j;
} nv14_player_snapshot;

/* Parsed descriptor retained for future native object modules. */
typedef struct nv14_object_descriptor {
    int32_t object_type;
    uint32_t load_index;
    uint32_t parameter_count;
    double parameters[NV14_OBJECT_PARAM_CAPACITY];
} nv14_object_descriptor;

typedef struct nv14_step_result {
    uint64_t frame_before;
    uint64_t frame_after;
    uint64_t jump_events_before;
    uint64_t jump_events_after;
    uint8_t dead;
    uint8_t level_complete;
    uint8_t jumped;
    uint8_t collected_gold;
    uint8_t exploded_mine;
    uint8_t opened_exit;
    uint8_t unsupported;
    uint8_t reserved;
} nv14_step_result;

typedef enum nv14_hook_phase {
    NV14_HOOK_PRE_PLAYER = 0,
    NV14_HOOK_PLAYER_OBJECT_COLLISION = 1,
    NV14_HOOK_POST_PLAYER = 2
} nv14_hook_phase;

typedef nv14_status (*nv14_step_hook_fn)(
    void *userdata,
    nv14_hook_phase phase,
    const nv14_level *level,
    nv14_state *state,
    const nv14_input *input
);

typedef enum nv14_hook_flag {
    /* The hook performs the complete live object-grid traversal, including
       static colliders.  Native static traversal is skipped. */
    NV14_HOOK_REPLACE_COLLISION_TRAVERSAL = 1u << 0,
    /* The hook implements every dynamic serialized object required by level. */
    NV14_HOOK_SUPPORTS_DYNAMIC_OBJECTS = 1u << 1
} nv14_hook_flag;

typedef struct nv14_step_hooks {
    uint32_t abi_version;
    uint32_t struct_size;
    uint32_t flags;
    uint32_t reserved;
    nv14_step_hook_fn callback;
    void *userdata;
} nv14_step_hooks;

/* Construction and immutable level metadata. */
nv14_level *nv14_level_create(
    const char *level_string,
    size_t level_length,
    int simulate_enemies,
    nv14_error *error_out
);
void nv14_level_retain(nv14_level *level);
void nv14_level_release(nv14_level *level);
uint32_t nv14_level_capabilities(const nv14_level *level);
nv14_object_type_mask nv14_level_unsupported_object_mask(const nv14_level *level);
size_t nv14_level_object_count(const nv14_level *level);
nv14_status nv14_level_object_descriptor_at(
    const nv14_level *level,
    size_t index,
    nv14_object_descriptor *descriptor_out
);
size_t nv14_level_gold_count(const nv14_level *level);
size_t nv14_level_mine_count(const nv14_level *level);
size_t nv14_level_exit_count(const nv14_level *level);

/* Mutable state lifecycle.  States retain their level. */
nv14_state *nv14_state_create(const nv14_level *level, nv14_error *error_out);
nv14_state *nv14_state_clone(const nv14_state *state, nv14_error *error_out);
/* Overwrite an already allocated state with an exact same-level copy.  This
 * allocation-free form is intended for native search-state pools. */
nv14_status nv14_state_copy_into(
    nv14_state *destination,
    const nv14_state *source,
    nv14_error *error_out
);
void nv14_state_destroy(nv14_state *state);
const nv14_level *nv14_state_level(const nv14_state *state);

/* Exact tick API and a low-overhead fixed-input batch form. */
nv14_status nv14_state_step(
    nv14_state *state,
    nv14_input input,
    nv14_step_result *result_out
);
nv14_status nv14_state_step_with_hooks(
    nv14_state *state,
    nv14_input input,
    const nv14_step_hooks *hooks,
    nv14_step_result *result_out
);
nv14_status nv14_state_step_many(
    nv14_state *state,
    const nv14_input *inputs,
    size_t input_count,
    int stop_on_dead,
    int stop_on_complete,
    size_t *consumed_out,
    nv14_step_result *last_result_out
);

/* Split phase API for a wrapper or future object module. */
nv14_status nv14_state_begin_player_step(nv14_state *state);
nv14_status nv14_state_collide_native_objects(nv14_state *state);
nv14_status nv14_state_finish_player_step(
    nv14_state *state,
    nv14_input input,
    nv14_step_result *result_out
);

/* State access/mutation used by Cython proxy objects and callbacks. */
nv14_status nv14_state_get_player(
    const nv14_state *state,
    nv14_player_snapshot *player_out
);
nv14_status nv14_state_set_player(
    nv14_state *state,
    const nv14_player_snapshot *player
);
uint64_t nv14_state_frame(const nv14_state *state);
int nv14_state_level_complete(const nv14_state *state);
void nv14_state_set_level_complete(nv14_state *state, int complete);
uint64_t nv14_state_gold_bonus_ticks(const nv14_state *state);
int64_t nv14_state_completed_exit_index(const nv14_state *state);

/* Dynamic arbitrary-width static-object masks. */
size_t nv14_state_mask_word_count(const nv14_state *state, nv14_mask_kind kind);
nv14_status nv14_state_copy_mask(
    const nv14_state *state,
    nv14_mask_kind kind,
    uint64_t *words_out,
    size_t word_capacity
);

/* Door/bounce native modules can override individual precomputed tile edges. */
nv14_status nv14_state_set_edge_override(
    nv14_state *state,
    int tile_i,
    int tile_j,
    int side,
    int edge_value
);
nv14_status nv14_state_clear_edge_override(
    nv14_state *state,
    int tile_i,
    int tile_j,
    int side
);

/* Exact phase-zero state serialization, scoped to one immutable level.  It
   includes the gameplay frame counter; callers must not compare keys from
   different levels.  The format is private but deterministic for an ABI
   version.  precision < 0 means exact binary64. */
size_t nv14_state_key_size(const nv14_state *state, int precision);
nv14_status nv14_state_write_key(
    const nv14_state *state,
    int precision,
    unsigned char *buffer,
    size_t buffer_size,
    size_t *written_out
);

const char *nv14_status_string(nv14_status status);

#ifdef __cplusplus
}
#endif

#endif /* NV14_CORE_H */

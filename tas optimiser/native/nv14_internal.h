#ifndef NV14_INTERNAL_H
#define NV14_INTERNAL_H

/* Private native-engine layout shared by nv14_core.c and future object units.
 * This is not a stable external ABI.  Cython and third-party callers must use
 * only nv14_core.h.
 */

#include "nv14_core.h"

#define NV14_TILE_SCALE 12.0
#define NV14_TILE_W 24.0
#define NV14_TILE_H 24.0
#define NV14_PLAYER_R (NV14_TILE_SCALE * 0.8333333333333334)
#define NV14_ROOT2 1.4142135623730950488
#define NV14_ROOT5 2.23606797749979

#define NV14_TID_EMPTY 0
#define NV14_TID_FULL 1
#define NV14_TID_HALFD 30
#define NV14_TID_HALFR 31
#define NV14_TID_HALFU 32
#define NV14_TID_HALFL 33
#define NV14_TID_67DEGPNS 22
#define NV14_TID_67DEGNNS 23
#define NV14_TID_67DEGNPS 24
#define NV14_TID_67DEGPPS 25

#define NV14_CTYPE_EMPTY 0
#define NV14_CTYPE_FULL 1
#define NV14_CTYPE_45DEG 2
#define NV14_CTYPE_CONCAVE 6
#define NV14_CTYPE_CONVEX 10
#define NV14_CTYPE_22DEGS 14
#define NV14_CTYPE_22DEGB 18
#define NV14_CTYPE_67DEGS 22
#define NV14_CTYPE_67DEGB 26
#define NV14_CTYPE_HALF 30

#define NV14_EID_OFF 0
#define NV14_EID_INTERESTING 1
#define NV14_EID_SOLID 2

#define NV14_EDGE_U 0
#define NV14_EDGE_D 1
#define NV14_EDGE_L 2
#define NV14_EDGE_R 3

#define NV14_COL_NONE 0
#define NV14_COL_AXIS 1
#define NV14_COL_OTHER 2

#define NV14_OBJ_GOLD 0
#define NV14_OBJ_BOUNCE 1
#define NV14_OBJ_LAUNCH 2
#define NV14_OBJ_TURRET 3
#define NV14_OBJ_FLOORGUARD 4
#define NV14_OBJ_PLAYER 5
#define NV14_OBJ_DRONE 6
#define NV14_OBJ_ONEWAY 7
#define NV14_OBJ_THWOMP 8
#define NV14_OBJ_TESTDOOR 9
#define NV14_OBJ_HOMING 10
#define NV14_OBJ_EXIT 11
#define NV14_OBJ_MINE 12

#define NV14_CELL_MIN_I (-1)
#define NV14_CELL_MIN_J (-1)
#define NV14_CELL_MAX_I (NV14_GRID_COLS + 2)
#define NV14_CELL_MAX_J (NV14_GRID_ROWS + 2)
#define NV14_CELL_STRIDE (NV14_CELL_MAX_J - NV14_CELL_MIN_J + 1)
#define NV14_CELL_HEIGHT (NV14_CELL_MAX_I - NV14_CELL_MIN_I + 1)
#define NV14_CELL_SLOTS (NV14_CELL_STRIDE * NV14_CELL_HEIGHT)
#define NV14_EDGE_OVERRIDE_SLOTS (NV14_TILE_COLS * NV14_TILE_ROWS * 4)
#define NV14_EDGE_OVERRIDE_WORDS ((NV14_EDGE_OVERRIDE_SLOTS + 63u) / 64u)

/* Mutable object kinds own one fixed-size, zero-initialised runtime block.
 * Immutable objects retain their stable native-object indices but have no
 * per-state runtime entry.  Object modules assign their own slot meanings.
 * Keeping the representation scalar-only makes clone/free/key handling
 * core-owned and prevents per-branch heap allocations. */
#define NV14_OBJECT_RUNTIME_F64_SLOTS 16
#define NV14_OBJECT_RUNTIME_I64_SLOTS 16
#define NV14_INTERNAL_MAX_OBJECT_MODULES 4
#define NV14_INTERNAL_OBJECT_MODULE_ABI_VERSION 1u

typedef struct nv14_object_runtime {
    double f64[NV14_OBJECT_RUNTIME_F64_SLOTS];
    int64_t i64[NV14_OBJECT_RUNTIME_I64_SLOTS];
} nv14_object_runtime;

typedef struct nv14_tile {
    int16_t i;
    int16_t j;
    int16_t tile_id;
    int16_t ctype;
    int8_t signx;
    int8_t signy;
    int8_t edges[4];
    int8_t reserved;
    double x;
    double y;
    double sx;
    double sy;
} nv14_tile;

typedef enum nv14_native_kind {
    NV14_NATIVE_GOLD = 0,
    NV14_NATIVE_MINE = 1,
    NV14_NATIVE_EXIT_SWITCH = 2,
    NV14_NATIVE_EXIT_DOOR = 3,
    NV14_NATIVE_ONEWAY = 4,
    NV14_NATIVE_LAUNCH = 5,
    NV14_NATIVE_BOUNCE = 6,
    NV14_NATIVE_THWOMP = 7,
    NV14_NATIVE_TESTDOOR = 8,
    NV14_NATIVE_TURRET = 9,
    NV14_NATIVE_HOMING = 10,
    NV14_NATIVE_FLOORGUARD = 11,
    NV14_NATIVE_DRONE_ZAP = 12,
    NV14_NATIVE_DRONE_LASER = 13,
    NV14_NATIVE_DRONE_CHAINGUN = 14
} nv14_native_kind;

#define NV14_NO_RUNTIME_INDEX UINT32_MAX

static inline int nv14_internal_kind_has_mutable_runtime(uint8_t kind)
{
    return kind >= NV14_NATIVE_BOUNCE &&
        kind <= NV14_NATIVE_DRONE_CHAINGUN;
}

typedef struct nv14_native_object {
    uint8_t kind;
    uint8_t initially_gridded;
    uint8_t module_index;
    uint8_t reserved;
    uint32_t load_index;
    uint32_t state_index;
    uint32_t runtime_index;
    int32_t cell_i;
    int32_t cell_j;
    double x;
    double y;
    double a;
    double b;
    double r;
} nv14_native_object;

typedef struct nv14_internal_object_module nv14_internal_object_module;

/* Modules are registered once, before level construction.  Descriptor
 * callbacks run in serialized spawn order, so a module can append its native
 * object and capture/write door edges without losing cross-type ordering.
 * The core owns the shared update/think scheduler and live collision grid. */
struct nv14_internal_object_module {
    uint32_t abi_version;
    uint32_t struct_size;
    nv14_object_type_mask supported_type_mask;
    uint32_t reserved;
    const char *name;
    nv14_status (*level_begin)(nv14_level *level, nv14_error *error_out);
    nv14_status (*descriptor_init)(
        nv14_level *level,
        const nv14_object_descriptor *descriptor,
        nv14_error *error_out
    );
    nv14_status (*level_finish)(nv14_level *level, nv14_error *error_out);
    void (*level_destroy)(nv14_level *level);
    nv14_status (*state_init)(nv14_state *state, nv14_error *error_out);
    nv14_status (*state_clone)(
        nv14_state *destination,
        const nv14_state *source,
        nv14_error *error_out
    );
    void (*state_destroy)(nv14_state *state);
    nv14_status (*update_object)(nv14_state *state, size_t object_index);
    nv14_status (*think_object)(nv14_state *state, size_t object_index);
    nv14_status (*collide_player)(
        nv14_state *state,
        size_t object_index,
        int *handled_out,
        int *removed_current_out
    );
    nv14_status (*post_player)(nv14_state *state);
    size_t (*extra_key_size)(const nv14_state *state);
    nv14_status (*write_extra_key)(
        const nv14_state *state,
        unsigned char *buffer,
        size_t buffer_size,
        size_t *written_out
    );
};

struct nv14_level {
    size_t reference_count;
    int simulate_enemies;
    uint32_t capabilities;
    nv14_object_type_mask unsupported_object_mask;
    nv14_tile tiles[NV14_TILE_COLS * NV14_TILE_ROWS];
    nv14_object_descriptor *descriptors;
    size_t descriptor_count;
    nv14_native_object *native_objects;
    size_t native_object_count;
    size_t native_object_capacity;
    nv14_object_runtime *initial_object_runtime;
    size_t initial_object_runtime_capacity;
    size_t mutable_runtime_count;
    size_t *initial_update_order;
    size_t initial_update_count;
    size_t *initial_thinker_order;
    size_t initial_thinker_count;
    /* Level modules may write initial overrides directly during parsing; the
       core builds the derived sparse index after all level_finish hooks. */
    int8_t initial_edge_overrides[NV14_EDGE_OVERRIDE_SLOTS];
    uint64_t initial_edge_override_active[NV14_EDGE_OVERRIDE_WORDS];
    uint16_t initial_edge_override_count;
    const nv14_internal_object_module *object_modules[
        NV14_INTERNAL_MAX_OBJECT_MODULES
    ];
    size_t object_module_count;
    size_t gold_count;
    size_t mine_count;
    size_t exit_count;
    nv14_player_snapshot initial_player;
};

struct nv14_state {
    nv14_level *level;
    nv14_player_snapshot player;
    uint64_t frame;
    uint8_t level_complete;
    uint8_t phase;
    uint8_t event_collected_gold;
    uint8_t event_exploded_mine;
    uint8_t event_opened_exit;
    uint8_t phase_skip_player;
    uint8_t reserved[2];
    uint64_t phase_jump_events_before;
    uint64_t gold_bonus_ticks;
    int64_t completed_exit_index;
    void *mutable_block;
    size_t mutable_block_size;
    uint64_t *collected_gold;
    uint64_t *exploded_mine;
    uint64_t *open_exit;
    int32_t cell_heads[NV14_CELL_SLOTS];
    int32_t *object_next;
    int32_t *object_prev;
    int32_t *object_cell_slot;
    nv14_object_runtime *object_runtime;
    size_t *update_order;
    size_t update_count;
    uint8_t *update_active;
    size_t *thinker_order;
    size_t thinker_count;
    uint8_t *thinker_active;
    size_t *scheduler_scratch;
    uint32_t think_timer;
    uint32_t think_rate;
    /* State modules must use nv14_state_set_edge_override() and
       nv14_state_clear_edge_override() so the sparse index stays synchronized. */
    int8_t edge_overrides[NV14_EDGE_OVERRIDE_SLOTS];
    uint64_t edge_override_active[NV14_EDGE_OVERRIDE_WORDS];
    uint16_t edge_override_count;
};

/* Callers use these only for kinds accepted by
 * nv14_internal_kind_has_mutable_runtime().  Runtime indices are assigned in
 * native-object order, so the compact array preserves deterministic key and
 * clone ordering without burdening immutable objects. */
static inline nv14_object_runtime *nv14_internal_object_runtime(
    nv14_state *state,
    size_t object_index
)
{
    return state->object_runtime +
        state->level->native_objects[object_index].runtime_index;
}

static inline const nv14_object_runtime *nv14_internal_object_runtime_const(
    const nv14_state *state,
    size_t object_index
)
{
    return state->object_runtime +
        state->level->native_objects[object_index].runtime_index;
}

/* Internal helpers intentionally exported only to sibling native units. */
nv14_status nv14_internal_register_object_module(
    const nv14_internal_object_module *module
);
nv14_status nv14_internal_level_append_object(
    nv14_level *level,
    nv14_native_kind kind,
    int initially_gridded,
    uint32_t load_index,
    uint32_t state_index,
    double x,
    double y,
    double a,
    double b,
    double r,
    const nv14_object_runtime *initial_runtime,
    size_t *object_index_out
);
nv14_status nv14_internal_level_start_update(
    nv14_level *level,
    size_t object_index
);
nv14_status nv14_internal_level_start_think(
    nv14_level *level,
    size_t object_index
);
size_t nv14_internal_word_count(size_t bits);
int nv14_internal_mask_test(const uint64_t *words, size_t bit);
void nv14_internal_mask_set(uint64_t *words, size_t bit);
int nv14_internal_cell_slot(int i, int j);
int nv14_internal_floor_index(double value, double divisor, int *out);
void nv14_internal_grid_add(nv14_state *state, size_t object_index, int slot);
void nv14_internal_grid_remove(nv14_state *state, size_t object_index);
nv14_status nv14_internal_grid_move(
    nv14_state *state,
    size_t object_index,
    int cell_i,
    int cell_j
);
nv14_status nv14_internal_start_update(nv14_state *state, size_t object_index);
void nv14_internal_end_update(nv14_state *state, size_t object_index);
nv14_status nv14_internal_start_think(nv14_state *state, size_t object_index);
void nv14_internal_end_think(nv14_state *state, size_t object_index);
void nv14_internal_player_report_object(
    nv14_player_snapshot *player,
    double px,
    double py,
    double nx,
    double ny
);
void nv14_internal_player_launch(nv14_player_snapshot *player, double x, double y);
void nv14_internal_player_fall(nv14_player_snapshot *player);
void nv14_internal_player_celebrate(nv14_player_snapshot *player);

/* Search-only late-input fork.  Object updates, object collisions and tile
 * collisions are executed once using primary_input.  The completed primary
 * state remains in `state`; alternate_player_out/result_out describe the same
 * tick with alternate_input applied at Player.Think.  This is exact only while
 * no registered module has a post_player callback, which the capability
 * predicate checks before the state is touched. */
int nv14_internal_state_can_step_alternate(const nv14_state *state);
nv14_status nv14_internal_state_step_alternate(
    nv14_state *state,
    nv14_input primary_input,
    nv14_input alternate_input,
    nv14_player_snapshot *alternate_player_out,
    nv14_step_result *primary_result_out,
    nv14_step_result *alternate_result_out
);

#endif /* NV14_INTERNAL_H */

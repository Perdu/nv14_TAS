#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif

/*
 * Native hot-path core for nv14_engine.py.
 *
 * Floating-point fidelity is part of the interface.  Compile without
 * fast-math and with FP contraction disabled.  Expressions below intentionally
 * retain the temporary assignments and operation order of the Python/AVM1
 * reference implementation.
 */

#include "nv14_internal.h"

#include <errno.h>
#include <locale.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const nv14_internal_object_module *nv14_registered_modules[
    NV14_INTERNAL_MAX_OBJECT_MODULES
];
static size_t nv14_registered_module_count;

static void nv14_clear_error(nv14_error *error_out)
{
    if (error_out != NULL) {
        memset(error_out, 0, sizeof(*error_out));
        error_out->code = NV14_STATUS_OK;
        error_out->object_type = -1;
        error_out->tile_id = -1;
        error_out->tile_i = -1;
        error_out->tile_j = -1;
    }
}

static void nv14_set_error(
    nv14_error *error_out,
    nv14_status code,
    size_t byte_offset,
    const char *message
)
{
    if (error_out == NULL) {
        return;
    }
    nv14_clear_error(error_out);
    error_out->code = code;
    error_out->byte_offset = byte_offset;
    if (message != NULL) {
        (void)snprintf(error_out->message, sizeof(error_out->message), "%s", message);
    }
}

nv14_status nv14_internal_register_object_module(
    const nv14_internal_object_module *module
)
{
    size_t index;
    if (module == NULL ||
        module->abi_version != NV14_INTERNAL_OBJECT_MODULE_ABI_VERSION ||
        module->struct_size < sizeof(*module) ||
        module->supported_type_mask == 0) {
        return NV14_STATUS_INVALID_ARGUMENT;
    }
    for (index = 0; index < nv14_registered_module_count; ++index) {
        const nv14_internal_object_module *registered =
            nv14_registered_modules[index];
        if (registered == module) return NV14_STATUS_OK;
        if ((registered->supported_type_mask & module->supported_type_mask) != 0)
            return NV14_STATUS_INVALID_ARGUMENT;
    }
    if (nv14_registered_module_count >= NV14_INTERNAL_MAX_OBJECT_MODULES)
        return NV14_STATUS_OUT_OF_MEMORY;
    nv14_registered_modules[nv14_registered_module_count++] = module;
    return NV14_STATUS_OK;
}

static int nv14_module_index_for_type(
    const nv14_level *level,
    int object_type
)
{
    size_t index;
    nv14_object_type_mask bit;
    if (level == NULL || object_type < 0 || object_type >= 32) return -1;
    bit = UINT32_C(1) << object_type;
    for (index = 0; index < level->object_module_count; ++index) {
        const nv14_internal_object_module *module = level->object_modules[index];
        if ((module->supported_type_mask & bit) != 0) return (int)index;
    }
    return -1;
}

static const nv14_internal_object_module *nv14_module_for_type(
    const nv14_level *level,
    int object_type
)
{
    int index = nv14_module_index_for_type(level, object_type);
    return index >= 0 ? level->object_modules[index] : NULL;
}

static size_t nv14_word_count(size_t bits)
{
    return bits / 64u + (bits % 64u != 0u);
}

_Static_assert(
    NV14_EDGE_OVERRIDE_SLOTS <= UINT16_MAX,
    "sparse edge-override key indices must fit in uint16"
);
_Static_assert(
    NV14_CELL_SLOTS <= UINT16_MAX,
    "sparse grid cell slots must fit in uint16 with a -1 sentinel"
);
_Static_assert(
    NV14_INTERNAL_MAX_OBJECT_MODULES < UINT8_MAX,
    "cached object-module indices must fit beside the invalid sentinel"
);

static int nv14_level_index_initial_edge_overrides(nv14_level *level)
{
    size_t index;
    uint16_t count = 0;
    memset(
        level->initial_edge_override_active,
        0,
        sizeof(level->initial_edge_override_active)
    );
    for (index = 0; index < NV14_EDGE_OVERRIDE_SLOTS; ++index) {
        int value = level->initial_edge_overrides[index];
        if (value >= 0) {
            if (value > NV14_EID_SOLID) return 0;
            level->initial_edge_override_active[index >> 6] |=
                UINT64_C(1) << (index & 63u);
            ++count;
        } else if (value != -1) {
            return 0;
        }
    }
    level->initial_edge_override_count = count;
    return 1;
}

static int nv14_mask_test(const uint64_t *words, size_t bit)
{
    return (int)((words[bit >> 6] >> (bit & 63u)) & UINT64_C(1));
}

static void nv14_mask_set(uint64_t *words, size_t bit)
{
    words[bit >> 6] |= UINT64_C(1) << (bit & 63u);
}

static int nv14_cell_slot(int i, int j)
{
    if (i < NV14_CELL_MIN_I || i > NV14_CELL_MAX_I ||
        j < NV14_CELL_MIN_J || j > NV14_CELL_MAX_J) {
        return -1;
    }
    return (i - NV14_CELL_MIN_I) * NV14_CELL_STRIDE + j - NV14_CELL_MIN_J;
}

static nv14_tile *nv14_tile_at(nv14_level *level, int i, int j)
{
    if (i < 0 || i >= NV14_TILE_COLS || j < 0 || j >= NV14_TILE_ROWS) {
        return NULL;
    }
    return &level->tiles[i * NV14_TILE_ROWS + j];
}

static const nv14_tile *nv14_tile_at_const(const nv14_level *level, int i, int j)
{
    if (i < 0 || i >= NV14_TILE_COLS || j < 0 || j >= NV14_TILE_ROWS) {
        return NULL;
    }
    return &level->tiles[i * NV14_TILE_ROWS + j];
}

static int nv14_python_floor_index(double value, double divisor, int *out)
{
    double q = value / divisor;
    /* Player, object and ray coordinates are normally non-negative.  C's
       conversion to int truncates toward zero, which is exactly floor() for
       that common range.  Keep the division as a separate binary64 operation
       and retain the source-equivalent fallback for negative, non-finite and
       out-of-range quotients. */
    if (q >= 0.0 && q <= (double)INT32_MAX) {
        *out = (int)q;
        return 1;
    }
    q = floor(q);
    if (!isfinite(q) || q < (double)INT32_MIN || q > (double)INT32_MAX) {
        return 0;
    }
    *out = (int)q;
    return 1;
}

static void nv14_player_defaults(nv14_player_snapshot *player, double x, double y)
{
    memset(player, 0, sizeof(*player));
    player->pos.x = x;
    player->pos.y = y;
    player->oldpos = player->pos;
    player->r = NV14_PLAYER_R;
    player->xw = NV14_PLAYER_R;
    player->yw = NV14_PLAYER_R;
    player->maxspeed_air = player->r * 0.5;
    player->maxspeed_ground = player->r * 0.5;
    player->ground_accel = 0.15;
    player->air_accel = 0.1;
    player->norm_grav = 0.15;
    player->jump_grav = 0.025;
    player->norm_drag = 0.99;
    player->win_drag = 0.8;
    player->wall_friction = 0.13;
    player->skid_friction = 0.92;
    player->stand_friction = 0.8;
    player->jump_amt = 1.0;
    player->jump_y_bias = 2.0;
    player->max_jump_time = 30;
    player->terminal_vel = player->r * 0.9;
    player->g = 0.15;
    player->d = 0.99;
    player->state = NV14_PLAYER_STANDING;
    player->was_in_air = 1;
    player->in_air = 1;
    (void)nv14_python_floor_index(x, NV14_TILE_W, &player->cell_i);
    (void)nv14_python_floor_index(y, NV14_TILE_H, &player->cell_j);
}

static void nv14_tile_update_type(nv14_tile *cell)
{
    int tile_id = cell->tile_id;
    int offset;
    if (tile_id == NV14_TID_EMPTY) {
        cell->ctype = NV14_CTYPE_EMPTY;
        cell->signx = 0;
        cell->signy = 0;
        cell->sx = 0.0;
        cell->sy = 0.0;
        return;
    }
    if (tile_id == NV14_TID_FULL) {
        cell->ctype = NV14_CTYPE_FULL;
        cell->signx = 0;
        cell->signy = 0;
        cell->sx = 0.0;
        cell->sy = 0.0;
        return;
    }
    if (tile_id >= 2 && tile_id < 30) {
        if (tile_id < 6) {
            cell->ctype = NV14_CTYPE_45DEG;
            offset = tile_id - 2;
        } else if (tile_id < 10) {
            cell->ctype = NV14_CTYPE_CONCAVE;
            offset = tile_id - 6;
        } else if (tile_id < 14) {
            cell->ctype = NV14_CTYPE_CONVEX;
            offset = tile_id - 10;
        } else if (tile_id < 18) {
            cell->ctype = NV14_CTYPE_22DEGS;
            offset = tile_id - 14;
        } else if (tile_id < 22) {
            cell->ctype = NV14_CTYPE_22DEGB;
            offset = tile_id - 18;
        } else if (tile_id < 26) {
            cell->ctype = NV14_CTYPE_67DEGS;
            offset = tile_id - 22;
        } else {
            cell->ctype = NV14_CTYPE_67DEGB;
            offset = tile_id - 26;
        }
        cell->signx = (int8_t)((offset == 0 || offset == 3) ? 1 : -1);
        cell->signy = (int8_t)((offset == 0 || offset == 1) ? -1 : 1);
        if (cell->ctype == NV14_CTYPE_45DEG) {
            cell->sx = (double)cell->signx / sqrt(2.0);
            cell->sy = (double)cell->signy / sqrt(2.0);
        } else if (cell->ctype == NV14_CTYPE_22DEGS ||
                   cell->ctype == NV14_CTYPE_22DEGB) {
            cell->sx = (double)cell->signx / NV14_ROOT5;
            cell->sy = (double)cell->signy * 2.0 / NV14_ROOT5;
        } else if (cell->ctype == NV14_CTYPE_67DEGS ||
                   cell->ctype == NV14_CTYPE_67DEGB) {
            cell->sx = (double)cell->signx * 2.0 / NV14_ROOT5;
            cell->sy = (double)cell->signy / NV14_ROOT5;
        } else {
            cell->sx = 0.0;
            cell->sy = 0.0;
        }
        return;
    }
    cell->ctype = NV14_CTYPE_HALF;
    cell->signx = 0;
    cell->signy = 0;
    if (tile_id == NV14_TID_HALFD) {
        cell->signy = -1;
    } else if (tile_id == NV14_TID_HALFU) {
        cell->signy = 1;
    } else if (tile_id == NV14_TID_HALFL) {
        cell->signx = 1;
    } else if (tile_id == NV14_TID_HALFR) {
        cell->signx = -1;
    }
    cell->sx = (double)cell->signx;
    cell->sy = (double)cell->signy;
}

static int nv14_edge_u(const nv14_tile *cell, const nv14_tile *n)
{
    if (cell->tile_id == 0) {
        if (n->tile_id == 0) return NV14_EID_OFF;
        if (n->tile_id == 1) return NV14_EID_SOLID;
        return (n->signy * -1 <= 0 ||
                n->tile_id == NV14_TID_67DEGPNS ||
                n->tile_id == NV14_TID_67DEGNNS)
            ? NV14_EID_INTERESTING : NV14_EID_SOLID;
    }
    if (cell->tile_id == 1) {
        if (n->tile_id == 0 || n->tile_id == 1) return NV14_EID_OFF;
        return (n->signy * -1 <= 0 ||
                n->tile_id == NV14_TID_67DEGPNS ||
                n->tile_id == NV14_TID_67DEGNNS)
            ? NV14_EID_INTERESTING : NV14_EID_OFF;
    }
    if (0 <= cell->signy * -1) {
        if (n->tile_id == 0) return NV14_EID_OFF;
        if (n->tile_id == 1) return NV14_EID_SOLID;
        return (n->signy * -1 <= 0 ||
                n->tile_id == NV14_TID_67DEGPNS ||
                n->tile_id == NV14_TID_67DEGNNS)
            ? NV14_EID_INTERESTING : NV14_EID_SOLID;
    }
    if (cell->tile_id == NV14_TID_67DEGPPS ||
        cell->tile_id == NV14_TID_67DEGNPS) {
        if (n->tile_id == 0) return NV14_EID_OFF;
        if (n->tile_id == 1) return NV14_EID_SOLID;
        if (n->signy * -1 <= 0 ||
            n->tile_id == NV14_TID_67DEGPNS ||
            n->tile_id == NV14_TID_67DEGNNS)
            return NV14_EID_INTERESTING;
        return (0 < n->signy * -1 || n->tile_id == 1)
            ? NV14_EID_SOLID : NV14_EID_OFF;
    }
    if (n->tile_id == 0 || n->tile_id == 1) return NV14_EID_OFF;
    return (n->signy * -1 <= 0 ||
            n->tile_id == NV14_TID_67DEGPNS ||
            n->tile_id == NV14_TID_67DEGNNS)
        ? NV14_EID_INTERESTING : NV14_EID_OFF;
}

static int nv14_edge_d(const nv14_tile *cell, const nv14_tile *n)
{
    if (cell->tile_id == 0) {
        if (n->tile_id == 0) return NV14_EID_OFF;
        if (n->tile_id == 1) return NV14_EID_SOLID;
        return (n->signy <= 0 ||
                n->tile_id == NV14_TID_67DEGPPS ||
                n->tile_id == NV14_TID_67DEGNPS)
            ? NV14_EID_INTERESTING : NV14_EID_SOLID;
    }
    if (cell->tile_id == 1) {
        if (n->tile_id == 0 || n->tile_id == 1) return NV14_EID_OFF;
        return (n->signy <= 0 ||
                n->tile_id == NV14_TID_67DEGPPS ||
                n->tile_id == NV14_TID_67DEGNPS)
            ? NV14_EID_INTERESTING : NV14_EID_OFF;
    }
    if (0 <= cell->signy) {
        if (n->tile_id == 0) return NV14_EID_OFF;
        if (n->tile_id == 1) return NV14_EID_SOLID;
        return (n->signy <= 0 ||
                n->tile_id == NV14_TID_67DEGPPS ||
                n->tile_id == NV14_TID_67DEGNPS)
            ? NV14_EID_INTERESTING : NV14_EID_SOLID;
    }
    if (cell->tile_id == NV14_TID_67DEGPNS ||
        cell->tile_id == NV14_TID_67DEGNNS) {
        if (n->tile_id == 0) return NV14_EID_OFF;
        if (n->tile_id == 1) return NV14_EID_SOLID;
        if (n->signy <= 0 ||
            n->tile_id == NV14_TID_67DEGPPS ||
            n->tile_id == NV14_TID_67DEGNPS)
            return NV14_EID_INTERESTING;
        return (0 < n->signy || n->tile_id == 1)
            ? NV14_EID_SOLID : NV14_EID_OFF;
    }
    if (n->tile_id == 0 || n->tile_id == 1) return NV14_EID_OFF;
    return (n->signy <= 0 ||
            n->tile_id == NV14_TID_67DEGPPS ||
            n->tile_id == NV14_TID_67DEGNPS)
        ? NV14_EID_INTERESTING : NV14_EID_OFF;
}

static int nv14_edge_r(const nv14_tile *cell, const nv14_tile *n)
{
    if (cell->tile_id == 0) {
        if (n->tile_id == 0) return NV14_EID_OFF;
        if (n->tile_id == 1) return NV14_EID_SOLID;
        return (n->signx <= 0 || n->tile_id == 14 || n->tile_id == 17)
            ? NV14_EID_INTERESTING : NV14_EID_SOLID;
    }
    if (cell->tile_id == 1) {
        if (n->tile_id == 0 || n->tile_id == 1) return NV14_EID_OFF;
        return (n->signx <= 0 || n->tile_id == 14 || n->tile_id == 17)
            ? NV14_EID_INTERESTING : NV14_EID_OFF;
    }
    if (0 <= cell->signx) {
        if (n->tile_id == 0) return NV14_EID_OFF;
        if (n->tile_id == 1) return NV14_EID_SOLID;
        return (n->signx <= 0 || n->tile_id == 14 || n->tile_id == 17)
            ? NV14_EID_INTERESTING : NV14_EID_SOLID;
    }
    if (cell->tile_id == 15 || cell->tile_id == 16) {
        if (n->tile_id == 0) return NV14_EID_OFF;
        if (n->tile_id == 1) return NV14_EID_SOLID;
        if (n->signx <= 0 || n->tile_id == 14 || n->tile_id == 17)
            return NV14_EID_INTERESTING;
        return (n->tile_id == 1 || 0 < n->signx)
            ? NV14_EID_SOLID : NV14_EID_OFF;
    }
    if (n->tile_id == 0 || n->tile_id == 1) return NV14_EID_OFF;
    return (n->signx <= 0 || n->tile_id == 14 || n->tile_id == 17)
        ? NV14_EID_INTERESTING : NV14_EID_OFF;
}

static int nv14_edge_l(const nv14_tile *cell, const nv14_tile *n)
{
    if (cell->tile_id == 0) {
        if (n->tile_id == 0) return NV14_EID_OFF;
        if (n->tile_id == 1) return NV14_EID_SOLID;
        return (n->signx * -1 <= 0 || n->tile_id == 15 || n->tile_id == 16)
            ? NV14_EID_INTERESTING : NV14_EID_SOLID;
    }
    if (cell->tile_id == 1) {
        if (n->tile_id == 0 || n->tile_id == 1) return NV14_EID_OFF;
        return (n->signx * -1 <= 0 || n->tile_id == 15 || n->tile_id == 16)
            ? NV14_EID_INTERESTING : NV14_EID_OFF;
    }
    if (0 <= cell->signx * -1) {
        if (n->tile_id == 0) return NV14_EID_OFF;
        if (n->tile_id == 1) return NV14_EID_SOLID;
        return (n->signx * -1 <= 0 || n->tile_id == 15 || n->tile_id == 16)
            ? NV14_EID_INTERESTING : NV14_EID_SOLID;
    }
    if (cell->tile_id == 14 || cell->tile_id == 17) {
        if (n->tile_id == 0) return NV14_EID_OFF;
        if (n->tile_id == 1) return NV14_EID_SOLID;
        if (n->signx * -1 <= 0 || n->tile_id == 15 || n->tile_id == 16)
            return NV14_EID_INTERESTING;
        return (0 < n->signx * -1 || n->tile_id == 1)
            ? NV14_EID_SOLID : NV14_EID_OFF;
    }
    if (n->tile_id == 0 || n->tile_id == 1) return NV14_EID_OFF;
    return (n->signx * -1 <= 0 || n->tile_id == 15 || n->tile_id == 16)
        ? NV14_EID_INTERESTING : NV14_EID_OFF;
}

static void nv14_level_update_edges(nv14_level *level)
{
    int i;
    int j;
    for (i = 0; i < NV14_TILE_COLS; ++i) {
        for (j = 0; j < NV14_TILE_ROWS; ++j) {
            nv14_tile *cell = nv14_tile_at(level, i, j);
            nv14_tile_update_type(cell);
        }
    }
    for (i = 0; i < NV14_TILE_COLS; ++i) {
        for (j = 0; j < NV14_TILE_ROWS; ++j) {
            nv14_tile *cell = nv14_tile_at(level, i, j);
            const nv14_tile *up = j > 0 ? nv14_tile_at_const(level, i, j - 1) : cell;
            const nv14_tile *down = j + 1 < NV14_TILE_ROWS
                ? nv14_tile_at_const(level, i, j + 1) : cell;
            const nv14_tile *left = i > 0 ? nv14_tile_at_const(level, i - 1, j) : cell;
            const nv14_tile *right = i + 1 < NV14_TILE_COLS
                ? nv14_tile_at_const(level, i + 1, j) : cell;
            cell->edges[NV14_EDGE_U] = (int8_t)nv14_edge_u(cell, up);
            cell->edges[NV14_EDGE_D] = (int8_t)nv14_edge_d(cell, down);
            cell->edges[NV14_EDGE_L] = (int8_t)nv14_edge_l(cell, left);
            cell->edges[NV14_EDGE_R] = (int8_t)nv14_edge_r(cell, right);
        }
    }
}

static int nv14_count_objects(const char *begin, const char *end)
{
    int count = 0;
    const char *p;
    if (begin >= end) return 0;
    count = 1;
    for (p = begin; p < end; ++p) {
        if (*p == '!') ++count;
    }
    return count;
}

static int nv14_parse_long_token(const char *begin, const char *end, long *out)
{
    char buffer[64];
    char *parse_end;
    size_t length = (size_t)(end - begin);
    long value;
    if (length == 0 || length >= sizeof(buffer)) return 0;
    memcpy(buffer, begin, length);
    buffer[length] = '\0';
    errno = 0;
    value = strtol(buffer, &parse_end, 10);
    if (errno != 0 || parse_end != buffer + length) return 0;
    *out = value;
    return 1;
}

static int nv14_parse_double_token(const char *begin, const char *end, double *out)
{
    char buffer[128];
    char *parse_end;
    size_t length = (size_t)(end - begin);
    double value;
    if (length == 0 || length >= sizeof(buffer)) return 0;
    memcpy(buffer, begin, length);
    buffer[length] = '\0';
    errno = 0;
#if defined(_WIN32)
    {
        _locale_t c_locale = _create_locale(LC_NUMERIC, "C");
        if (c_locale == NULL) return 0;
        value = _strtod_l(buffer, &parse_end, c_locale);
        _free_locale(c_locale);
    }
#else
    {
        locale_t c_locale = newlocale(LC_NUMERIC_MASK, "C", (locale_t)0);
        if (c_locale == (locale_t)0) return 0;
        value = strtod_l(buffer, &parse_end, c_locale);
        freelocale(c_locale);
    }
#endif
    if (errno == ERANGE || parse_end != buffer + length) return 0;
    *out = value;
    return 1;
}

static int nv14_level_reserve_initial_runtime(
    nv14_level *level,
    size_t required
)
{
    nv14_object_runtime *resized;
    size_t capacity;
    if (required <= level->initial_object_runtime_capacity) return 1;
    capacity = level->initial_object_runtime_capacity;
    if (capacity == 0) capacity = 4;
    while (capacity < required) {
        if (capacity > SIZE_MAX / 2u) {
            capacity = required;
            break;
        }
        capacity *= 2u;
    }
    if (capacity > SIZE_MAX / sizeof(*resized)) return 0;
    resized = (nv14_object_runtime *)realloc(
        level->initial_object_runtime,
        capacity * sizeof(*resized)
    );
    if (resized == NULL) return 0;
    level->initial_object_runtime = resized;
    level->initial_object_runtime_capacity = capacity;
    return 1;
}

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
)
{
    nv14_native_object *obj;
    size_t object_index;
    size_t runtime_index = SIZE_MAX;
    int cell_i;
    int cell_j;
    if (level == NULL || level->native_objects == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    if (level->native_object_count >= level->native_object_capacity)
        return NV14_STATUS_OUT_OF_MEMORY;
    if (!nv14_python_floor_index(x, NV14_TILE_W, &cell_i) ||
        !nv14_python_floor_index(y, NV14_TILE_H, &cell_j))
        return NV14_STATUS_OUT_OF_BOUNDS;
    if (nv14_internal_kind_has_mutable_runtime((uint8_t)kind)) {
        if (level->mutable_runtime_count >= (size_t)UINT32_MAX ||
            !nv14_level_reserve_initial_runtime(
                level, level->mutable_runtime_count + 1u
            ))
            return NV14_STATUS_OUT_OF_MEMORY;
        runtime_index = level->mutable_runtime_count++;
        if (initial_runtime != NULL)
            level->initial_object_runtime[runtime_index] = *initial_runtime;
        else
            memset(
                &level->initial_object_runtime[runtime_index],
                0,
                sizeof(level->initial_object_runtime[runtime_index])
            );
    }
    object_index = level->native_object_count++;
    obj = &level->native_objects[object_index];
    memset(obj, 0, sizeof(*obj));
    obj->kind = (uint8_t)kind;
    obj->initially_gridded = initially_gridded != 0;
    obj->module_index = UINT8_MAX;
    if (load_index < level->descriptor_count) {
        int module_index = nv14_module_index_for_type(
            level,
            level->descriptors[load_index].object_type
        );
        if (module_index >= 0) obj->module_index = (uint8_t)module_index;
    }
    obj->load_index = load_index;
    obj->state_index = state_index;
    obj->runtime_index = runtime_index == SIZE_MAX
        ? NV14_NO_RUNTIME_INDEX
        : (uint32_t)runtime_index;
    obj->cell_i = cell_i;
    obj->cell_j = cell_j;
    obj->x = x;
    obj->y = y;
    obj->a = a;
    obj->b = b;
    obj->r = r;
    if (object_index_out != NULL) *object_index_out = object_index;
    return NV14_STATUS_OK;
}

static nv14_status nv14_internal_level_start_scheduler(
    nv14_level *level,
    size_t object_index,
    size_t *order,
    size_t *count
)
{
    size_t index;
    if (level == NULL || order == NULL || count == NULL ||
        object_index >= level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    for (index = 0; index < *count; ++index) {
        if (order[index] == object_index) return NV14_STATUS_OK;
    }
    if (*count >= level->native_object_capacity) return NV14_STATUS_OUT_OF_MEMORY;
    memmove(order + 1, order, *count * sizeof(*order));
    order[0] = object_index;
    ++*count;
    return NV14_STATUS_OK;
}

nv14_status nv14_internal_level_start_update(
    nv14_level *level,
    size_t object_index
)
{
    return nv14_internal_level_start_scheduler(
        level,
        object_index,
        level != NULL ? level->initial_update_order : NULL,
        level != NULL ? &level->initial_update_count : NULL
    );
}

nv14_status nv14_internal_level_start_think(
    nv14_level *level,
    size_t object_index
)
{
    return nv14_internal_level_start_scheduler(
        level,
        object_index,
        level != NULL ? level->initial_thinker_order : NULL,
        level != NULL ? &level->initial_thinker_count : NULL
    );
}

static int nv14_descriptor_add_native(
    nv14_level *level,
    size_t *native_index,
    uint8_t kind,
    uint8_t initially_gridded,
    uint32_t load_index,
    uint32_t state_index,
    double x,
    double y,
    double a,
    double b,
    double r
)
{
    nv14_status status;
    level->native_object_count = *native_index;
    status = nv14_internal_level_append_object(
        level,
        (nv14_native_kind)kind,
        initially_gridded,
        load_index,
        state_index,
        x,
        y,
        a,
        b,
        r,
        NULL,
        NULL
    );
    *native_index = level->native_object_count;
    return status == NV14_STATUS_OK;
}

static int nv14_required_parameter_count(int object_type)
{
    switch (object_type) {
        case NV14_OBJ_GOLD:
        case NV14_OBJ_BOUNCE:
        case NV14_OBJ_PLAYER:
        case NV14_OBJ_MINE:
            return 2;
        case NV14_OBJ_LAUNCH:
        case NV14_OBJ_EXIT:
            return 4;
        case NV14_OBJ_ONEWAY:
        case NV14_OBJ_THWOMP:
            return 3;
        case NV14_OBJ_TESTDOOR:
            return 9;
        default:
            return -1;
    }
}

static int nv14_object_is_simulated(int object_type, int simulate_enemies)
{
    if (object_type == NV14_OBJ_GOLD ||
        object_type == NV14_OBJ_BOUNCE ||
        object_type == NV14_OBJ_LAUNCH ||
        object_type == NV14_OBJ_PLAYER ||
        object_type == NV14_OBJ_ONEWAY ||
        object_type == NV14_OBJ_THWOMP ||
        object_type == NV14_OBJ_TESTDOOR ||
        object_type == NV14_OBJ_EXIT ||
        object_type == NV14_OBJ_MINE) {
        return 1;
    }
    return simulate_enemies &&
        (object_type == NV14_OBJ_TURRET ||
         object_type == NV14_OBJ_FLOORGUARD ||
         object_type == NV14_OBJ_DRONE ||
         object_type == NV14_OBJ_HOMING);
}

nv14_level *nv14_level_create(
    const char *level_string,
    size_t level_length,
    int simulate_enemies,
    nv14_error *error_out
)
{
    nv14_level *level = NULL;
    const char *separator;
    const char *object_begin;
    const char *object_end;
    const char *entry;
    size_t object_count;
    size_t descriptor_index = 0;
    size_t native_index = 0;
    size_t map_index = 0;
    size_t player_count = 0;
    size_t gold_index = 0;
    size_t mine_index = 0;
    size_t exit_index = 0;
    nv14_object_type_mask native_cell_unsupported_mask = 0;
    int i;
    int j;

    nv14_clear_error(error_out);
    if (level_string == NULL) {
        nv14_set_error(error_out, NV14_STATUS_INVALID_ARGUMENT, 0, "level string is null");
        return NULL;
    }
    separator = (const char *)memchr(level_string, '|', level_length);
    if (separator == NULL) {
        nv14_set_error(
            error_out,
            NV14_STATUS_INVALID_LEVEL,
            level_length,
            "level string has no map/object separator"
        );
        return NULL;
    }
    if ((size_t)(separator - level_string) != NV14_MAP_CHARS) {
        nv14_set_error(
            error_out,
            NV14_STATUS_INVALID_LEVEL,
            (size_t)(separator - level_string),
            "map must contain exactly 713 characters"
        );
        return NULL;
    }

    level = (nv14_level *)calloc(1, sizeof(*level));
    if (level == NULL) {
        nv14_set_error(error_out, NV14_STATUS_OUT_OF_MEMORY, 0, "cannot allocate level");
        return NULL;
    }
    level->reference_count = 1;
    level->simulate_enemies = simulate_enemies != 0;
    level->object_module_count = nv14_registered_module_count;
    if (level->object_module_count != 0) {
        memcpy(
            level->object_modules,
            nv14_registered_modules,
            level->object_module_count * sizeof(level->object_modules[0])
        );
    }
    memset(
        level->initial_edge_overrides,
        0xff,
        sizeof(level->initial_edge_overrides)
    );
    level->capabilities = NV14_CAP_STATIC_OBJECTS |
        NV14_CAP_ONEWAY_PLATFORM |
        NV14_CAP_LAUNCH_PAD |
        NV14_CAP_OBJECT_HOOKS;

    for (i = 0; i < NV14_TILE_COLS; ++i) {
        for (j = 0; j < NV14_TILE_ROWS; ++j) {
            nv14_tile *tile = nv14_tile_at(level, i, j);
            tile->i = (int16_t)i;
            tile->j = (int16_t)j;
            tile->x = NV14_TILE_SCALE + (double)i * NV14_TILE_W;
            tile->y = NV14_TILE_SCALE + (double)j * NV14_TILE_H;
            tile->tile_id = (i == 0 || i == NV14_TILE_COLS - 1 ||
                             j == 0 || j == NV14_TILE_ROWS - 1)
                ? NV14_TID_FULL : NV14_TID_EMPTY;
        }
    }
    for (i = 0; i < NV14_GRID_COLS; ++i) {
        for (j = 0; j < NV14_GRID_ROWS; ++j) {
            unsigned char ch = (unsigned char)level_string[map_index++];
            int tile_id = (int)ch - 48;
            nv14_tile *tile;
            if (tile_id < 0 || tile_id > 33) {
                nv14_set_error(
                    error_out,
                    NV14_STATUS_UNSUPPORTED_TILE,
                    map_index - 1,
                    "map contains a tile id outside 0..33"
                );
                if (error_out != NULL) {
                    error_out->tile_id = tile_id;
                    error_out->tile_i = i + 1;
                    error_out->tile_j = j + 1;
                }
                nv14_level_release(level);
                return NULL;
            }
            tile = nv14_tile_at(level, i + 1, j + 1);
            tile->tile_id = (int16_t)tile_id;
        }
    }
    nv14_level_update_edges(level);
    level->capabilities |= NV14_CAP_TILE_COLLISION;

    object_begin = separator + 1;
    object_end = level_string + level_length;
    object_count = (size_t)nv14_count_objects(object_begin, object_end);
    level->descriptor_count = object_count;
    level->native_object_capacity = object_count * 2u;
    if (object_count != 0) {
        level->descriptors = (nv14_object_descriptor *)calloc(
            object_count, sizeof(*level->descriptors)
        );
        level->native_objects = (nv14_native_object *)calloc(
            level->native_object_capacity, sizeof(*level->native_objects)
        );
        level->initial_update_order = (size_t *)malloc(
            level->native_object_capacity * sizeof(*level->initial_update_order)
        );
        level->initial_thinker_order = (size_t *)malloc(
            level->native_object_capacity * sizeof(*level->initial_thinker_order)
        );
        if (level->descriptors == NULL || level->native_objects == NULL ||
            level->initial_update_order == NULL ||
            level->initial_thinker_order == NULL) {
            nv14_set_error(error_out, NV14_STATUS_OUT_OF_MEMORY, 0, "cannot allocate object descriptors");
            nv14_level_release(level);
            return NULL;
        }
    }

    for (map_index = 0; map_index < level->object_module_count; ++map_index) {
        const nv14_internal_object_module *module = level->object_modules[map_index];
        if (module->level_begin != NULL) {
            nv14_status status = module->level_begin(level, error_out);
            if (status != NV14_STATUS_OK) {
                if (error_out != NULL && error_out->code == NV14_STATUS_OK)
                    error_out->code = status;
                nv14_level_release(level);
                return NULL;
            }
        }
    }

    entry = object_begin;
    while (entry < object_end) {
        const char *entry_end = (const char *)memchr(entry, '!', (size_t)(object_end - entry));
        const char *caret;
        const char *token;
        long object_type_long;
        int object_type;
        size_t param_count = 0;
        double params[NV14_OBJECT_PARAM_CAPACITY];
        nv14_object_descriptor *descriptor;
        int descriptor_nonfinite = 0;
        int required_parameter_count;
        if (entry_end == NULL) entry_end = object_end;
        if (entry == entry_end) {
            nv14_set_error(
                error_out,
                NV14_STATUS_INVALID_LEVEL,
                (size_t)(entry - level_string),
                "empty object entry"
            );
            nv14_level_release(level);
            return NULL;
        }
        caret = (const char *)memchr(entry, '^', (size_t)(entry_end - entry));
        if (caret == NULL || !nv14_parse_long_token(entry, caret, &object_type_long) ||
            object_type_long < INT32_MIN || object_type_long > INT32_MAX) {
            nv14_set_error(
                error_out,
                NV14_STATUS_INVALID_LEVEL,
                (size_t)(entry - level_string),
                "invalid object type"
            );
            nv14_level_release(level);
            return NULL;
        }
        object_type = (int)object_type_long;
        descriptor = &level->descriptors[descriptor_index];
        descriptor->object_type = object_type;
        descriptor->load_index = (uint32_t)descriptor_index;
        token = caret + 1;
        while (token <= entry_end) {
            const char *comma = token < entry_end
                ? (const char *)memchr(token, ',', (size_t)(entry_end - token))
                : NULL;
            const char *token_end = comma != NULL ? comma : entry_end;
            if (token_end > token) {
                double value;
                if (!nv14_parse_double_token(token, token_end, &value)) {
                    nv14_set_error(
                        error_out,
                        NV14_STATUS_INVALID_LEVEL,
                        (size_t)(token - level_string),
                        "invalid object parameter"
                    );
                    nv14_level_release(level);
                    return NULL;
                }
                if (param_count >= NV14_OBJECT_PARAM_CAPACITY) {
                    nv14_set_error(
                        error_out,
                        NV14_STATUS_INVALID_LEVEL,
                        (size_t)(token - level_string),
                        "object has more than ten parameters"
                    );
                    nv14_level_release(level);
                    return NULL;
                }
                params[param_count] = value;
                descriptor->parameters[param_count] = value;
                if (!isfinite(value)) descriptor_nonfinite = 1;
                ++param_count;
            }
            if (comma == NULL) break;
            token = comma + 1;
        }
        descriptor->parameter_count = (uint32_t)param_count;

        required_parameter_count = nv14_required_parameter_count(object_type);
        if (required_parameter_count >= 0 &&
            param_count != (size_t)required_parameter_count) {
            /* The Python reference retains malformed static descriptors in
               all_specs but deliberately omits their colliders. */
            if (object_type == NV14_OBJ_GOLD ||
                object_type == NV14_OBJ_MINE ||
                object_type == NV14_OBJ_EXIT) {
                ++descriptor_index;
                entry = entry_end < object_end ? entry_end + 1 : object_end;
                continue;
            }
            nv14_set_error(
                error_out,
                NV14_STATUS_INVALID_LEVEL,
                (size_t)(entry - level_string),
                "object has an invalid parameter count"
            );
            if (error_out != NULL) error_out->object_type = object_type;
            nv14_level_release(level);
            return NULL;
        }

        if (descriptor_nonfinite &&
            nv14_object_is_simulated(object_type, simulate_enemies)) {
            if (object_type >= 0 && object_type < 32)
                level->unsupported_object_mask |= UINT32_C(1) << object_type;
            if (object_type == NV14_OBJ_PLAYER) {
                /* Keep the dormant native payload finite.  The capability
                   mask forces the loader to use the Python reference path. */
                nv14_player_defaults(&level->initial_player, 0.0, 0.0);
                ++player_count;
            } else if (object_type == NV14_OBJ_GOLD) {
                ++gold_index;
            } else if (object_type == NV14_OBJ_MINE) {
                ++mine_index;
            } else if (object_type == NV14_OBJ_EXIT) {
                ++exit_index;
            }
        } else if (object_type == NV14_OBJ_PLAYER) {
            nv14_player_defaults(&level->initial_player, params[0], params[1]);
            ++player_count;
        } else if (object_type == NV14_OBJ_GOLD) {
            if (!nv14_descriptor_add_native(level, &native_index,
                    NV14_NATIVE_GOLD, 1, (uint32_t)descriptor_index,
                    (uint32_t)gold_index, params[0], params[1], 0.0, 0.0, 6.0)) {
                native_cell_unsupported_mask |= UINT32_C(1) << NV14_OBJ_GOLD;
            }
            ++gold_index;
        } else if (object_type == NV14_OBJ_MINE) {
            if (!nv14_descriptor_add_native(level, &native_index,
                    NV14_NATIVE_MINE, 1, (uint32_t)descriptor_index,
                    (uint32_t)mine_index, params[0], params[1], 0.0, 0.0, 4.0)) {
                native_cell_unsupported_mask |= UINT32_C(1) << NV14_OBJ_MINE;
            }
            ++mine_index;
        } else if (object_type == NV14_OBJ_EXIT) {
            if (!nv14_descriptor_add_native(level, &native_index,
                    NV14_NATIVE_EXIT_SWITCH, 1, (uint32_t)descriptor_index,
                    (uint32_t)exit_index, params[2], params[3], 0.0, 0.0, 6.0)) {
                native_cell_unsupported_mask |= UINT32_C(1) << NV14_OBJ_EXIT;
            }
            if (!nv14_descriptor_add_native(level, &native_index,
                    NV14_NATIVE_EXIT_DOOR, 0, (uint32_t)descriptor_index,
                    (uint32_t)exit_index, params[0], params[1], 0.0, 0.0, 12.0)) {
                native_cell_unsupported_mask |= UINT32_C(1) << NV14_OBJ_EXIT;
            }
            ++exit_index;
        } else if (object_type == NV14_OBJ_ONEWAY) {
            int direction;
            double dx = 0.0;
            double dy = 0.0;
            if (param_count != 3 || !isfinite(params[2]) ||
                params[2] < (double)INT32_MIN || params[2] > (double)INT32_MAX) {
                nv14_set_error(error_out, NV14_STATUS_INVALID_LEVEL,
                    (size_t)(entry - level_string), "one-way platform has invalid parameters");
                nv14_level_release(level);
                return NULL;
            }
            direction = (int)params[2];
            if (direction == 0) dx = 1.0;
            else if (direction == 1) dy = 1.0;
            else if (direction == 2) dx = -1.0;
            else if (direction == 3) dy = -1.0;
            else {
                nv14_set_error(error_out, NV14_STATUS_INVALID_LEVEL,
                    (size_t)(entry - level_string), "one-way direction is outside 0..3");
                nv14_level_release(level);
                return NULL;
            }
            if (!nv14_descriptor_add_native(level, &native_index,
                    NV14_NATIVE_ONEWAY, 1, (uint32_t)descriptor_index, 0,
                    params[0], params[1], dx, dy, 0.0)) {
                native_cell_unsupported_mask |= UINT32_C(1) << NV14_OBJ_ONEWAY;
            }
        } else if (object_type == NV14_OBJ_LAUNCH) {
            if (!nv14_descriptor_add_native(level, &native_index,
                    NV14_NATIVE_LAUNCH, 1, (uint32_t)descriptor_index, 0,
                    params[0], params[1], params[2], params[3], 6.0)) {
                native_cell_unsupported_mask |= UINT32_C(1) << NV14_OBJ_LAUNCH;
            }
        } else if (object_type == NV14_OBJ_BOUNCE ||
                   object_type == NV14_OBJ_THWOMP ||
                   object_type == NV14_OBJ_TESTDOOR) {
            const nv14_internal_object_module *module =
                nv14_module_for_type(level, object_type);
            if (module != NULL && module->descriptor_init != NULL) {
                nv14_status status = module->descriptor_init(level, descriptor, error_out);
                if (status == NV14_STATUS_UNSUPPORTED_OBJECTS) {
                    level->unsupported_object_mask |= UINT32_C(1) << object_type;
                } else if (status != NV14_STATUS_OK) {
                    if (error_out != NULL && error_out->code == NV14_STATUS_OK)
                        error_out->code = status;
                    nv14_level_release(level);
                    return NULL;
                }
                native_index = level->native_object_count;
            } else {
                level->unsupported_object_mask |= UINT32_C(1) << object_type;
            }
        } else if (simulate_enemies &&
                   (object_type == NV14_OBJ_TURRET ||
                    object_type == NV14_OBJ_FLOORGUARD ||
                    object_type == NV14_OBJ_DRONE ||
                    object_type == NV14_OBJ_HOMING)) {
            const nv14_internal_object_module *module =
                nv14_module_for_type(level, object_type);
            if (module != NULL && module->descriptor_init != NULL) {
                nv14_status status = module->descriptor_init(level, descriptor, error_out);
                if (status == NV14_STATUS_UNSUPPORTED_OBJECTS) {
                    level->unsupported_object_mask |= UINT32_C(1) << object_type;
                } else if (status != NV14_STATUS_OK) {
                    if (error_out != NULL && error_out->code == NV14_STATUS_OK)
                        error_out->code = status;
                    nv14_level_release(level);
                    return NULL;
                }
                native_index = level->native_object_count;
            } else {
                level->unsupported_object_mask |= UINT32_C(1) << object_type;
            }
        }

        ++descriptor_index;
        entry = entry_end < object_end ? entry_end + 1 : object_end;
    }

    /* A terminal '!' contributes an object in the counting pass but leaves no
       loop iteration.  Reject it just as Python's empty entry parser does. */
    if (descriptor_index != object_count) {
        nv14_set_error(
            error_out,
            NV14_STATUS_INVALID_LEVEL,
            level_length == 0 ? 0 : level_length - 1,
            "empty object entry"
        );
        nv14_level_release(level);
        return NULL;
    }

    for (map_index = 0; map_index < level->object_module_count; ++map_index) {
        const nv14_internal_object_module *module = level->object_modules[map_index];
        if (module->level_finish != NULL) {
            nv14_status status = module->level_finish(level, error_out);
            if (status != NV14_STATUS_OK) {
                if (error_out != NULL && error_out->code == NV14_STATUS_OK)
                    error_out->code = status;
                nv14_level_release(level);
                return NULL;
            }
        }
    }

    if (!nv14_level_index_initial_edge_overrides(level)) {
        nv14_set_error(
            error_out,
            NV14_STATUS_INVALID_LEVEL,
            0,
            "object module produced an invalid tile-edge override"
        );
        nv14_level_release(level);
        return NULL;
    }

    if (player_count != 1) {
        nv14_set_error(error_out, NV14_STATUS_INVALID_LEVEL, 0,
            "level must contain exactly one player object");
        nv14_level_release(level);
        return NULL;
    }
    level->native_object_count = native_index;
    level->gold_count = gold_index;
    level->mine_count = mine_index;
    level->exit_count = exit_index;
    level->unsupported_object_mask |= native_cell_unsupported_mask;
    if ((level->capabilities & NV14_CAP_TILE_COLLISION) != 0 &&
        level->unsupported_object_mask == 0) {
        level->capabilities |= NV14_CAP_COMPLETE_STEP;
    }
    return level;
}

void nv14_level_retain(nv14_level *level)
{
    if (level != NULL) ++level->reference_count;
}

void nv14_level_release(nv14_level *level)
{
    size_t index;
    if (level == NULL) return;
    if (level->reference_count > 1) {
        --level->reference_count;
        return;
    }
    for (index = level->object_module_count; index > 0; --index) {
        const nv14_internal_object_module *module = level->object_modules[index - 1];
        if (module->level_destroy != NULL) module->level_destroy(level);
    }
    free(level->descriptors);
    free(level->native_objects);
    free(level->initial_object_runtime);
    free(level->initial_update_order);
    free(level->initial_thinker_order);
    free(level);
}

uint32_t nv14_level_capabilities(const nv14_level *level)
{
    return level != NULL ? level->capabilities : 0;
}

nv14_object_type_mask nv14_level_unsupported_object_mask(const nv14_level *level)
{
    return level != NULL ? level->unsupported_object_mask : UINT32_MAX;
}

size_t nv14_level_object_count(const nv14_level *level)
{
    return level != NULL ? level->descriptor_count : 0;
}

nv14_status nv14_level_object_descriptor_at(
    const nv14_level *level,
    size_t index,
    nv14_object_descriptor *descriptor_out
)
{
    if (level == NULL || descriptor_out == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    if (index >= level->descriptor_count) return NV14_STATUS_OUT_OF_BOUNDS;
    *descriptor_out = level->descriptors[index];
    return NV14_STATUS_OK;
}

size_t nv14_level_gold_count(const nv14_level *level)
{
    return level != NULL ? level->gold_count : 0;
}

size_t nv14_level_mine_count(const nv14_level *level)
{
    return level != NULL ? level->mine_count : 0;
}

size_t nv14_level_exit_count(const nv14_level *level)
{
    return level != NULL ? level->exit_count : 0;
}

static void nv14_grid_add(nv14_state *state, size_t object_index, int slot)
{
    int32_t old_head;
    if (slot < 0 || slot >= NV14_CELL_SLOTS) return;
    old_head = state->cell_heads[slot];
    state->object_prev[object_index] = -1;
    state->object_next[object_index] = old_head;
    state->object_cell_slot[object_index] = slot;
    if (old_head >= 0) state->object_prev[old_head] = (int32_t)object_index;
    state->cell_heads[slot] = (int32_t)object_index;
}

static void nv14_grid_remove(nv14_state *state, size_t object_index)
{
    int32_t slot = state->object_cell_slot[object_index];
    int32_t previous;
    int32_t next;
    if (slot < 0) return;
    previous = state->object_prev[object_index];
    next = state->object_next[object_index];
    if (previous >= 0) state->object_next[previous] = next;
    else state->cell_heads[slot] = next;
    if (next >= 0) state->object_prev[next] = previous;
    state->object_prev[object_index] = -1;
    state->object_next[object_index] = -1;
    state->object_cell_slot[object_index] = -1;
}

nv14_status nv14_internal_grid_move(
    nv14_state *state,
    size_t object_index,
    int cell_i,
    int cell_j
)
{
    int slot;
    if (state == NULL || object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    slot = nv14_cell_slot(cell_i, cell_j);
    /* The Python object grid is an unbounded dictionary, while the native
       dense grid covers only map cells plus the player-query margin.  An
       object outside that representable region cannot collide with an
       in-bounds player: unlink it without treating the source-valid movement
       as an error.  A later move back into the margin re-adds it below. */
    if (slot < 0) {
        nv14_grid_remove(state, object_index);
        return NV14_STATUS_OK;
    }
    if (state->object_cell_slot[object_index] == slot) return NV14_STATUS_OK;
    nv14_grid_remove(state, object_index);
    nv14_grid_add(state, object_index, slot);
    return NV14_STATUS_OK;
}

static nv14_status nv14_internal_scheduler_start(
    nv14_state *state,
    size_t object_index,
    size_t *order,
    size_t *count,
    uint8_t *active
)
{
    if (state == NULL || order == NULL || count == NULL || active == NULL ||
        object_index >= state->level->native_object_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    if (active[object_index]) return NV14_STATUS_OK;
    if (*count >= state->level->native_object_count)
        return NV14_STATUS_OUT_OF_MEMORY;
    memmove(order + 1, order, *count * sizeof(*order));
    order[0] = object_index;
    active[object_index] = 1;
    ++*count;
    return NV14_STATUS_OK;
}

static void nv14_internal_scheduler_end(
    nv14_state *state,
    size_t object_index,
    size_t *order,
    size_t *count,
    uint8_t *active
)
{
    size_t index;
    if (state == NULL || order == NULL || count == NULL || active == NULL ||
        object_index >= state->level->native_object_count ||
        !active[object_index])
        return;
    for (index = 0; index < *count; ++index) {
        if (order[index] == object_index) {
            memmove(
                order + index,
                order + index + 1,
                (*count - index - 1) * sizeof(*order)
            );
            --*count;
            break;
        }
    }
    active[object_index] = 0;
}

nv14_status nv14_internal_start_update(nv14_state *state, size_t object_index)
{
    return nv14_internal_scheduler_start(
        state,
        object_index,
        state != NULL ? state->update_order : NULL,
        state != NULL ? &state->update_count : NULL,
        state != NULL ? state->update_active : NULL
    );
}

void nv14_internal_end_update(nv14_state *state, size_t object_index)
{
    nv14_internal_scheduler_end(
        state,
        object_index,
        state != NULL ? state->update_order : NULL,
        state != NULL ? &state->update_count : NULL,
        state != NULL ? state->update_active : NULL
    );
}

nv14_status nv14_internal_start_think(nv14_state *state, size_t object_index)
{
    return nv14_internal_scheduler_start(
        state,
        object_index,
        state != NULL ? state->thinker_order : NULL,
        state != NULL ? &state->thinker_count : NULL,
        state != NULL ? state->thinker_active : NULL
    );
}

void nv14_internal_end_think(nv14_state *state, size_t object_index)
{
    nv14_internal_scheduler_end(
        state,
        object_index,
        state != NULL ? state->thinker_order : NULL,
        state != NULL ? &state->thinker_count : NULL,
        state != NULL ? state->thinker_active : NULL
    );
}

static const nv14_internal_object_module *nv14_module_for_object(
    const nv14_state *state,
    size_t object_index
)
{
    const nv14_native_object *object;
    if (state == NULL || object_index >= state->level->native_object_count)
        return NULL;
    object = &state->level->native_objects[object_index];
    if (object->module_index >= state->level->object_module_count) return NULL;
    return state->level->object_modules[object->module_index];
}

static nv14_status nv14_run_native_object_updates(nv14_state *state)
{
    size_t count;
    size_t index;
    if (state->update_count != 0) {
        count = state->update_count;
        memcpy(
            state->scheduler_scratch,
            state->update_order,
            count * sizeof(*state->scheduler_scratch)
        );
        for (index = 0; index < count; ++index) {
            size_t object_index = state->scheduler_scratch[index];
            const nv14_internal_object_module *module;
            nv14_status status;
            if (object_index >= state->level->native_object_count ||
                !state->update_active[object_index])
                continue;
            module = nv14_module_for_object(state, object_index);
            if (module == NULL || module->update_object == NULL)
                return NV14_STATUS_UNSUPPORTED_OBJECTS;
            status = module->update_object(state, object_index);
            if (status != NV14_STATUS_OK) return status;
        }
    }
    if (state->thinker_count == 0) return NV14_STATUS_OK;
    if (state->think_rate < state->think_timer) {
        size_t current = state->thinker_order[0];
        const nv14_internal_object_module *module =
            nv14_module_for_object(state, current);
        nv14_status status;
        state->think_timer = 0;
        if (module == NULL || module->think_object == NULL)
            return NV14_STATUS_UNSUPPORTED_OBJECTS;
        status = module->think_object(state, current);
        if (status != NV14_STATUS_OK) return status;
        if (state->thinker_count > 1 &&
            (!state->thinker_active[current] ||
             state->thinker_order[0] == current)) {
            size_t first = state->thinker_order[0];
            memmove(
                state->thinker_order,
                state->thinker_order + 1,
                (state->thinker_count - 1) * sizeof(*state->thinker_order)
            );
            state->thinker_order[state->thinker_count - 1] = first;
        }
    } else {
        ++state->think_timer;
    }
    return NV14_STATUS_OK;
}

static int nv14_state_reserve_block_field(
    size_t *total,
    size_t count,
    size_t element_size,
    size_t alignment,
    size_t *offset_out
)
{
    size_t padding;
    size_t bytes;
    if (count == 0) {
        *offset_out = SIZE_MAX;
        return 1;
    }
    padding = (alignment - (*total % alignment)) % alignment;
    if (*total > SIZE_MAX - padding) return 0;
    *total += padding;
    if (element_size != 0 && count > SIZE_MAX / element_size) return 0;
    bytes = count * element_size;
    if (*total > SIZE_MAX - bytes) return 0;
    *offset_out = *total;
    *total += bytes;
    return 1;
}

static int nv14_state_allocate_arrays(nv14_state *state, int clear_memory)
{
    const nv14_level *level = state->level;
    size_t object_count = level->native_object_count;
    size_t runtime_count = level->mutable_runtime_count;
    size_t gold_words = nv14_word_count(level->gold_count);
    size_t mine_words = nv14_word_count(level->mine_count);
    size_t exit_words = nv14_word_count(level->exit_count);
    size_t total = 0;
    size_t off_gold;
    size_t off_mine;
    size_t off_exit;
    size_t off_next;
    size_t off_prev;
    size_t off_cell;
    size_t off_runtime;
    size_t off_update_order;
    size_t off_update_active;
    size_t off_thinker_order;
    size_t off_thinker_active;
    size_t off_scratch;
    unsigned char *block;

#define NV14_RESERVE_FIELD(count_, type_, offset_) \
    nv14_state_reserve_block_field( \
        &total, (count_), sizeof(type_), _Alignof(type_), &(offset_) \
    )
    if (!NV14_RESERVE_FIELD(gold_words, uint64_t, off_gold) ||
        !NV14_RESERVE_FIELD(mine_words, uint64_t, off_mine) ||
        !NV14_RESERVE_FIELD(exit_words, uint64_t, off_exit) ||
        !NV14_RESERVE_FIELD(object_count, int32_t, off_next) ||
        !NV14_RESERVE_FIELD(object_count, int32_t, off_prev) ||
        !NV14_RESERVE_FIELD(object_count, int32_t, off_cell) ||
        !NV14_RESERVE_FIELD(runtime_count, nv14_object_runtime, off_runtime) ||
        !NV14_RESERVE_FIELD(object_count, size_t, off_update_order) ||
        !NV14_RESERVE_FIELD(object_count, uint8_t, off_update_active) ||
        !NV14_RESERVE_FIELD(object_count, size_t, off_thinker_order) ||
        !NV14_RESERVE_FIELD(object_count, uint8_t, off_thinker_active) ||
        !NV14_RESERVE_FIELD(object_count, size_t, off_scratch)) {
#undef NV14_RESERVE_FIELD
        return 0;
    }
#undef NV14_RESERVE_FIELD
    if (total == 0) return 1;
    block = clear_memory
        ? (unsigned char *)calloc(1, total)
        : (unsigned char *)malloc(total);
    if (block == NULL) return 0;
    state->mutable_block = block;
    state->mutable_block_size = total;
#define NV14_BLOCK_POINTER(offset_, type_) \
    ((offset_) == SIZE_MAX ? NULL : (type_ *)(void *)(block + (offset_)))
    state->collected_gold = NV14_BLOCK_POINTER(off_gold, uint64_t);
    state->exploded_mine = NV14_BLOCK_POINTER(off_mine, uint64_t);
    state->open_exit = NV14_BLOCK_POINTER(off_exit, uint64_t);
    state->object_next = NV14_BLOCK_POINTER(off_next, int32_t);
    state->object_prev = NV14_BLOCK_POINTER(off_prev, int32_t);
    state->object_cell_slot = NV14_BLOCK_POINTER(off_cell, int32_t);
    state->object_runtime =
        NV14_BLOCK_POINTER(off_runtime, nv14_object_runtime);
    state->update_order = NV14_BLOCK_POINTER(off_update_order, size_t);
    state->update_active = NV14_BLOCK_POINTER(off_update_active, uint8_t);
    state->thinker_order = NV14_BLOCK_POINTER(off_thinker_order, size_t);
    state->thinker_active = NV14_BLOCK_POINTER(off_thinker_active, uint8_t);
    state->scheduler_scratch = NV14_BLOCK_POINTER(off_scratch, size_t);
#undef NV14_BLOCK_POINTER
    return 1;
}

nv14_state *nv14_state_create(const nv14_level *level_const, nv14_error *error_out)
{
    nv14_state *state;
    nv14_level *level = (nv14_level *)level_const;
    size_t index;
    nv14_clear_error(error_out);
    if (level == NULL) {
        nv14_set_error(error_out, NV14_STATUS_INVALID_ARGUMENT, 0, "level is null");
        return NULL;
    }
    state = (nv14_state *)calloc(1, sizeof(*state));
    if (state == NULL) {
        nv14_set_error(error_out, NV14_STATUS_OUT_OF_MEMORY, 0, "cannot allocate state");
        return NULL;
    }
    state->level = level;
    nv14_level_retain(level);
    state->player = level->initial_player;
    state->completed_exit_index = -1;
    state->think_rate = 2;
    memset(state->cell_heads, 0xff, sizeof(state->cell_heads));
    memcpy(
        state->edge_overrides,
        level->initial_edge_overrides,
        sizeof(state->edge_overrides)
    );
    memcpy(
        state->edge_override_active,
        level->initial_edge_override_active,
        sizeof(state->edge_override_active)
    );
    state->edge_override_count = level->initial_edge_override_count;
    if (!nv14_state_allocate_arrays(state, 1)) {
        nv14_set_error(error_out, NV14_STATUS_OUT_OF_MEMORY, 0, "cannot allocate mutable state arrays");
        nv14_state_destroy(state);
        return NULL;
    }
    for (index = 0; index < level->native_object_count; ++index) {
        state->object_next[index] = -1;
        state->object_prev[index] = -1;
        state->object_cell_slot[index] = -1;
        if (level->native_objects[index].initially_gridded) {
            int slot = nv14_cell_slot(
                level->native_objects[index].cell_i,
                level->native_objects[index].cell_j
            );
            nv14_grid_add(state, index, slot);
        }
    }
    if (level->mutable_runtime_count != 0) {
        memcpy(
            state->object_runtime,
            level->initial_object_runtime,
            level->mutable_runtime_count * sizeof(*state->object_runtime)
        );
    }
    state->update_count = level->initial_update_count;
    if (state->update_count != 0)
        memcpy(
            state->update_order,
            level->initial_update_order,
            state->update_count * sizeof(*state->update_order)
        );
    for (index = 0; index < state->update_count; ++index)
        state->update_active[state->update_order[index]] = 1;
    state->thinker_count = level->initial_thinker_count;
    if (state->thinker_count != 0)
        memcpy(
            state->thinker_order,
            level->initial_thinker_order,
            state->thinker_count * sizeof(*state->thinker_order)
        );
    for (index = 0; index < state->thinker_count; ++index)
        state->thinker_active[state->thinker_order[index]] = 1;
    for (index = 0; index < level->object_module_count; ++index) {
        const nv14_internal_object_module *module = level->object_modules[index];
        if (module->state_init != NULL) {
            nv14_status status = module->state_init(state, error_out);
            if (status != NV14_STATUS_OK) {
                if (error_out != NULL && error_out->code == NV14_STATUS_OK)
                    error_out->code = status;
                nv14_state_destroy(state);
                return NULL;
            }
        }
    }
    return state;
}

nv14_state *nv14_state_clone(const nv14_state *source, nv14_error *error_out)
{
    nv14_state *state;
    nv14_status copy_status;
    nv14_clear_error(error_out);
    if (source == NULL) {
        nv14_set_error(error_out, NV14_STATUS_INVALID_ARGUMENT, 0, "state is null");
        return NULL;
    }
    state = (nv14_state *)calloc(1, sizeof(*state));
    if (state == NULL) {
        nv14_set_error(error_out, NV14_STATUS_OUT_OF_MEMORY, 0, "cannot allocate cloned state");
        return NULL;
    }
    state->level = source->level;
    nv14_level_retain(state->level);
    if (!nv14_state_allocate_arrays(state, 0)) {
        nv14_set_error(error_out, NV14_STATUS_OUT_OF_MEMORY, 0, "cannot allocate cloned state arrays");
        nv14_state_destroy(state);
        return NULL;
    }
    copy_status = nv14_state_copy_into(state, source, error_out);
    if (copy_status != NV14_STATUS_OK) {
        nv14_state_destroy(state);
        return NULL;
    }
    return state;
}

nv14_status nv14_state_copy_into(
    nv14_state *destination,
    const nv14_state *source,
    nv14_error *error_out
)
{
    size_t object_count;
    size_t words;
    size_t module_index;
    nv14_clear_error(error_out);
    if (destination == NULL || source == NULL ||
        destination == source || destination->level != source->level ||
        destination->mutable_block_size != source->mutable_block_size) {
        nv14_set_error(
            error_out,
            NV14_STATUS_INVALID_ARGUMENT,
            0,
            "search-state copy requires distinct, layout-compatible states"
        );
        return NV14_STATUS_INVALID_ARGUMENT;
    }
    destination->player = source->player;
    destination->frame = source->frame;
    destination->level_complete = source->level_complete;
    destination->phase = source->phase;
    destination->event_collected_gold = source->event_collected_gold;
    destination->event_exploded_mine = source->event_exploded_mine;
    destination->event_opened_exit = source->event_opened_exit;
    destination->phase_skip_player = source->phase_skip_player;
    memcpy(destination->reserved, source->reserved, sizeof(destination->reserved));
    destination->phase_jump_events_before = source->phase_jump_events_before;
    destination->gold_bonus_ticks = source->gold_bonus_ticks;
    destination->completed_exit_index = source->completed_exit_index;
    destination->update_count = source->update_count;
    destination->thinker_count = source->thinker_count;
    destination->think_timer = source->think_timer;
    destination->think_rate = source->think_rate;
    memcpy(destination->cell_heads, source->cell_heads,
        sizeof(destination->cell_heads));
    memcpy(destination->edge_overrides, source->edge_overrides,
        sizeof(destination->edge_overrides));
    memcpy(
        destination->edge_override_active,
        source->edge_override_active,
        sizeof(destination->edge_override_active)
    );
    destination->edge_override_count = source->edge_override_count;

    object_count = source->level->native_object_count;
    if (object_count != 0) {
        memcpy(destination->object_next, source->object_next,
            object_count * sizeof(*destination->object_next));
        memcpy(destination->object_prev, source->object_prev,
            object_count * sizeof(*destination->object_prev));
        memcpy(destination->object_cell_slot, source->object_cell_slot,
            object_count * sizeof(*destination->object_cell_slot));
        memcpy(destination->update_order, source->update_order,
            source->update_count * sizeof(*destination->update_order));
        memcpy(destination->update_active, source->update_active,
            object_count * sizeof(*destination->update_active));
        memcpy(destination->thinker_order, source->thinker_order,
            source->thinker_count * sizeof(*destination->thinker_order));
        memcpy(destination->thinker_active, source->thinker_active,
            object_count * sizeof(*destination->thinker_active));
    }
    if (source->level->mutable_runtime_count != 0)
        memcpy(
            destination->object_runtime,
            source->object_runtime,
            source->level->mutable_runtime_count *
                sizeof(*destination->object_runtime)
        );
    words = nv14_word_count(source->level->gold_count);
    if (words != 0)
        memcpy(destination->collected_gold, source->collected_gold,
            words * sizeof(*destination->collected_gold));
    words = nv14_word_count(source->level->mine_count);
    if (words != 0)
        memcpy(destination->exploded_mine, source->exploded_mine,
            words * sizeof(*destination->exploded_mine));
    words = nv14_word_count(source->level->exit_count);
    if (words != 0)
        memcpy(destination->open_exit, source->open_exit,
            words * sizeof(*destination->open_exit));
    for (module_index = 0;
         module_index < source->level->object_module_count;
         ++module_index) {
        const nv14_internal_object_module *module =
            source->level->object_modules[module_index];
        if (module->state_clone != NULL) {
            nv14_status status = module->state_clone(
                destination, source, error_out
            );
            if (status != NV14_STATUS_OK) {
                if (error_out != NULL && error_out->code == NV14_STATUS_OK)
                    error_out->code = status;
                return status;
            }
        }
    }
    return NV14_STATUS_OK;
}

void nv14_state_destroy(nv14_state *state)
{
    size_t index;
    if (state == NULL) return;
    if (state->level != NULL) {
        for (index = state->level->object_module_count; index > 0; --index) {
            const nv14_internal_object_module *module =
                state->level->object_modules[index - 1];
            if (module->state_destroy != NULL) module->state_destroy(state);
        }
    }
    free(state->mutable_block);
    nv14_level_release(state->level);
    free(state);
}

const nv14_level *nv14_state_level(const nv14_state *state)
{
    return state != NULL ? state->level : NULL;
}

static void nv14_player_record_normal(nv14_player_snapshot *player, double nx, double ny)
{
    if (ny == 0.0) {
        player->near_wall = 1;
        player->wall_n.x = nx;
        player->wall_n.y = ny;
    } else if (ny < 0.0) {
        if (player->floor_count == 0) {
            player->floor_n0.x = nx;
            player->floor_n0.y = ny;
            ++player->floor_count;
        } else {
            player->floor_count = 1;
            player->floor_n1.x = nx;
            player->floor_n1.y = ny;
            ++player->floor_count;
        }
    }
}

static void nv14_player_report_world(
    nv14_player_snapshot *player,
    double px,
    double py,
    double nx,
    double ny
)
{
    player->pos.x += px;
    player->pos.y += py;
    if (0.8 * (player->r * player->r) < px * px + py * py) {
        player->dead = 1;
        return;
    }
    nv14_player_record_normal(player, nx, ny);
}

static void nv14_player_report_object(
    nv14_player_snapshot *player,
    double px,
    double py,
    double nx,
    double ny
)
{
    player->pos.x += px;
    player->pos.y += py;
    nv14_player_record_normal(player, nx, ny);
}

static void nv14_player_fall(nv14_player_snapshot *player)
{
    if (player->state == NV14_PLAYER_JUMPING) player->g = player->norm_grav;
    player->state = NV14_PLAYER_FALLING;
}

static void nv14_player_launch(nv14_player_snapshot *player, double x, double y)
{
    player->oldpos.x = player->pos.x;
    player->oldpos.y = player->pos.y;
    player->pos.x += x;
    player->pos.y += y;
    nv14_player_fall(player);
}

static void nv14_player_jump(nv14_player_snapshot *player, double x, double y)
{
    double vx;
    double vy;
    ++player->jump_events;
    if (player->state == NV14_PLAYER_JUMPING) player->g = player->norm_grav;
    player->state = NV14_PLAYER_JUMPING;
    player->g = player->jump_grav;
    vx = player->pos.x - player->oldpos.x;
    vy = player->pos.y - player->oldpos.y;
    if (vx * x < 0.0) player->oldpos.x = player->pos.x;
    if (vy * y < 0.0) player->oldpos.y = player->pos.y;
    player->pos.x += x * player->jump_amt;
    player->pos.y += y * (player->jump_amt + player->jump_y_bias);
    player->jump_timer = 0;
}

static void nv14_player_celebrate(nv14_player_snapshot *player)
{
    if (player->state == NV14_PLAYER_JUMPING) player->g = player->norm_grav;
    player->state = NV14_PLAYER_CELEBRATING;
    player->celeb_was_in_air = player->in_air;
}

static int nv14_query_point(const nv14_level *level, double x, double y, nv14_status *status)
{
    int i;
    int j;
    const nv14_tile *cell;
    double dx;
    double dy;
    if (!nv14_python_floor_index(x, NV14_TILE_W, &i) ||
        !nv14_python_floor_index(y, NV14_TILE_H, &j)) {
        *status = NV14_STATUS_OUT_OF_BOUNDS;
        return 0;
    }
    cell = nv14_tile_at_const(level, i, j);
    if (cell == NULL) {
        *status = NV14_STATUS_OUT_OF_BOUNDS;
        return 0;
    }
    if (cell->tile_id == NV14_TID_EMPTY) return 0;
    if (cell->ctype == NV14_CTYPE_FULL) return 1;
    dx = x - cell->x;
    dy = y - cell->y;
    if (cell->ctype == NV14_CTYPE_HALF) {
        return dx * (double)cell->signx + dy * (double)cell->signy <= 0.0;
    }
    if (cell->ctype == NV14_CTYPE_45DEG) {
        return dx * cell->sx + dy * cell->sy <= 0.0;
    }
    if (cell->ctype == NV14_CTYPE_CONCAVE) {
        double vx = cell->x + (double)cell->signx * NV14_TILE_SCALE - x;
        double vy = cell->y + (double)cell->signy * NV14_TILE_SCALE - y;
        double radius = NV14_TILE_SCALE * 2.0;
        return radius * radius <= vx * vx + vy * vy;
    }
    if (cell->ctype == NV14_CTYPE_CONVEX) {
        double vx = x - (cell->x - (double)cell->signx * NV14_TILE_SCALE);
        double vy = y - (cell->y - (double)cell->signy * NV14_TILE_SCALE);
        double radius = NV14_TILE_SCALE * 2.0;
        return vx * vx + vy * vy <= radius * radius;
    }
    if (cell->ctype == NV14_CTYPE_22DEGS) {
        double vx = x - (cell->x + (double)cell->signx * NV14_TILE_SCALE);
        double vy = y - (cell->y - (double)cell->signy * NV14_TILE_SCALE);
        return vx * cell->sx + vy * cell->sy <= 0.0;
    }
    if (cell->ctype == NV14_CTYPE_22DEGB) {
        double vx = x - (cell->x - (double)cell->signx * NV14_TILE_SCALE);
        double vy = y - (cell->y + (double)cell->signy * NV14_TILE_SCALE);
        return vx * cell->sx + vy * cell->sy <= 0.0;
    }
    if (cell->ctype == NV14_CTYPE_67DEGS) {
        double vx = x - (cell->x - (double)cell->signx * NV14_TILE_SCALE);
        double vy = y - (cell->y + (double)cell->signy * NV14_TILE_SCALE);
        return vx * cell->sx + vy * cell->sy <= 0.0;
    }
    if (cell->ctype == NV14_CTYPE_67DEGB) {
        double vx = x - (cell->x + (double)cell->signx * NV14_TILE_SCALE);
        double vy = y - (cell->y - (double)cell->signy * NV14_TILE_SCALE);
        return vx * cell->sx + vy * cell->sy <= 0.0;
    }
    *status = NV14_STATUS_UNSUPPORTED_TILE;
    return 0;
}

static nv14_status nv14_player_handle_collisions(
    nv14_player_snapshot *player,
    const nv14_level *level
)
{
    if (player->floor_count > 0) {
        player->in_air = 0;
        if (player->floor_count > 1) {
            double dot = player->floor_n0.x * player->floor_n1.x +
                player->floor_n0.y * player->floor_n1.y;
            if (dot > 0.9) {
                if (!((player->floor_n0.x == player->floor_n.x &&
                       player->floor_n0.y == player->floor_n.y) ||
                      (player->floor_n1.x == player->floor_n.x &&
                       player->floor_n1.y == player->floor_n.y))) {
                    player->floor_n = player->floor_n1;
                }
            } else {
                double nx = 0.5 * (player->floor_n0.x + player->floor_n1.x);
                double ny = 0.5 * (player->floor_n0.y + player->floor_n1.y);
                double length = sqrt(nx * nx + ny * ny);
                if (length == 0.0) {
                    player->floor_n = player->floor_n0;
                } else {
                    player->floor_n.x = nx / length;
                    player->floor_n.y = ny / length;
                }
            }
        } else {
            player->floor_n = player->floor_n0;
        }
        if (player->was_in_air) {
            double impact = player->old_v.x * player->floor_n.x +
                player->old_v.y * player->floor_n.y;
            impact -= 2.0 * fabs(player->floor_n.y);
            if (player->old_v.y > 0.0 && impact < -player->terminal_vel) {
                player->dead = 1;
            }
        }
    }
    if (player->in_air && !player->near_wall) {
        double probe = player->r + 0.1;
        nv14_status status = NV14_STATUS_OK;
        if (nv14_query_point(level, player->pos.x + probe, player->pos.y, &status)) {
            player->near_wall = 1;
            player->wall_n.x = -1.0;
            player->wall_n.y = 0.0;
        } else if (status != NV14_STATUS_OK) {
            return status;
        } else if (nv14_query_point(level, player->pos.x - probe, player->pos.y, &status)) {
            player->near_wall = 1;
            player->wall_n.x = 1.0;
            player->wall_n.y = 0.0;
        } else if (status != NV14_STATUS_OK) {
            return status;
        }
    }
    return NV14_STATUS_OK;
}

static void nv14_player_think(
    nv14_player_snapshot *player,
    int horizontal,
    int jump_held,
    int jump_trigger
)
{
    double vx = player->pos.x - player->oldpos.x;
    double vy = player->pos.y - player->oldpos.y;
    int state = player->state;
    if (state == NV14_PLAYER_CELEBRATING) {
        if (player->in_air) {
            if (!player->celeb_was_in_air) {
                player->d = player->norm_drag;
                player->celeb_was_in_air = 1;
            }
        } else {
            if (player->celeb_was_in_air) player->d = player->win_drag;
            player->celeb_was_in_air = 0;
        }
        return;
    }
    if (player->in_air) {
        double candidate = vx + (double)horizontal * player->air_accel;
        if (fabs(candidate) < player->maxspeed_air) vx = candidate;
        player->oldpos.x = player->pos.x - vx;
        if (state < NV14_PLAYER_JUMPING) {
            nv14_player_fall(player);
            return;
        }
        if (state == NV14_PLAYER_JUMPING) {
            ++player->jump_timer;
            if (!jump_held || player->jump_timer > player->max_jump_time)
                nv14_player_fall(player);
            return;
        }
        if (player->near_wall) {
            if (jump_trigger) {
                double jump_x;
                double jump_y_bias;
                if (state == NV14_PLAYER_WALLSLIDING &&
                    (double)horizontal * player->wall_n.x < 0.0) {
                    jump_x = 1.0;
                    jump_y_bias = 0.5;
                } else {
                    jump_x = 1.5;
                    jump_y_bias = 0.7;
                }
                nv14_player_jump(
                    player,
                    player->wall_n.x * jump_x,
                    player->wall_n.y - jump_y_bias
                );
                return;
            }
            if (state == NV14_PLAYER_WALLSLIDING) {
                if ((double)horizontal * player->wall_n.x > 0.0) {
                    nv14_player_fall(player);
                    return;
                }
                {
                    double speed = fabs(vy);
                    double friction_delta = -player->wall_friction * speed;
                    player->oldpos.y = player->pos.y - (vy + friction_delta);
                }
                return;
            }
            if (vy > 0.0 && (double)horizontal * player->wall_n.x < 0.0) {
                player->state = NV14_PLAYER_WALLSLIDING;
                return;
            }
        } else if (state == NV14_PLAYER_WALLSLIDING) {
            nv14_player_fall(player);
            return;
        }
        return;
    }
    {
        double candidate = vx + (double)horizontal * player->ground_accel;
        if (fabs(candidate) < player->maxspeed_ground) vx = candidate;
        player->oldpos.x = player->pos.x - vx;
        if (state > NV14_PLAYER_SKIDDING) {
            if (state == NV14_PLAYER_JUMPING) player->g = player->norm_grav;
            player->state = vx * (double)horizontal > 0.0
                ? NV14_PLAYER_RUNNING : NV14_PLAYER_SKIDDING;
            return;
        }
        if (jump_trigger) {
            if ((double)horizontal * player->floor_n.x < 0.0)
                nv14_player_jump(player, 0.0, -0.7);
            else
                nv14_player_jump(player, player->floor_n.x, player->floor_n.y);
            return;
        }
        if (state == NV14_PLAYER_RUNNING) {
            double nx = player->floor_n.x;
            double ny = player->floor_n.y;
            double tangent_speed = vx * -ny + vy * nx;
            double tangent_abs = fabs(tangent_speed);
            double direction_test = vx * tangent_abs;
            if ((double)horizontal * direction_test <= 0.0) {
                player->state = NV14_PLAYER_SKIDDING;
                return;
            }
            if ((double)horizontal * nx < 0.0) {
                double accel_y = -fabs(nx);
                double accel_x = nx < 0.0 ? -ny : ny;
                double abs_ny = fabs(ny);
                double candidate_x;
                double candidate_y;
                accel_x *= 0.5 * abs_ny;
                accel_y *= 0.5 * abs_ny;
                candidate_x = vx + accel_x * player->ground_accel;
                candidate_y = vy + accel_y * player->ground_accel;
                if (fabs(candidate) < player->maxspeed_ground) {
                    vx = candidate_x;
                    vy = candidate_y;
                }
                player->oldpos.x = player->pos.x - vx;
                player->oldpos.y = player->pos.y - vy;
            }
            return;
        }
        if (state == NV14_PLAYER_SKIDDING) {
            double nx = player->floor_n.x;
            double ny = player->floor_n.y;
            double tangent_abs = fabs(vx * -ny + vy * nx);
            double direction_test = vx * tangent_abs;
            if (direction_test * (double)horizontal > 0.0) {
                player->state = NV14_PLAYER_RUNNING;
                return;
            }
            if (tangent_abs < 0.1) {
                player->state = NV14_PLAYER_STANDING;
                return;
            }
            vx *= player->skid_friction;
            player->oldpos.x = player->pos.x - vx;
            return;
        }
        if (horizontal != 0) {
            player->state = NV14_PLAYER_RUNNING;
            return;
        }
        {
            double nx = player->floor_n.x;
            double ny = player->floor_n.y;
            double tangent_abs = fabs(vx * -ny + vy * nx);
            if (tangent_abs >= 0.1) {
                player->state = NV14_PLAYER_SKIDDING;
                return;
            }
            vx *= player->stand_friction;
            vy *= player->stand_friction;
            player->oldpos.x = player->pos.x - vx;
            player->oldpos.y = player->pos.y - vy;
        }
    }
}

static int nv14_native_object_active(const nv14_state *state, const nv14_native_object *obj)
{
    size_t bit = obj->state_index;
    if (obj->kind == NV14_NATIVE_GOLD) return !nv14_mask_test(state->collected_gold, bit);
    if (obj->kind == NV14_NATIVE_MINE) return !nv14_mask_test(state->exploded_mine, bit);
    if (obj->kind == NV14_NATIVE_EXIT_SWITCH) return !nv14_mask_test(state->open_exit, bit);
    if (obj->kind == NV14_NATIVE_EXIT_DOOR) return nv14_mask_test(state->open_exit, bit);
    return 1;
}

static nv14_status nv14_test_native_object(
    nv14_state *state,
    size_t object_index,
    int *removed_current
)
{
    const nv14_native_object *obj = &state->level->native_objects[object_index];
    nv14_player_snapshot *player = &state->player;
    *removed_current = 0;
    if (!nv14_native_object_active(state, obj)) return NV14_STATUS_OK;
    if (obj->kind <= NV14_NATIVE_EXIT_DOOR) {
        double dx = obj->x - player->pos.x;
        double dy = obj->y - player->pos.y;
        if (sqrt(dx * dx + dy * dy) >= obj->r + player->r)
            return NV14_STATUS_OK;
        if (obj->kind == NV14_NATIVE_GOLD) {
            nv14_mask_set(state->collected_gold, obj->state_index);
            state->gold_bonus_ticks += 80;
            state->event_collected_gold = 1;
            *removed_current = 1;
        } else if (obj->kind == NV14_NATIVE_MINE) {
            nv14_mask_set(state->exploded_mine, obj->state_index);
            player->dead = 1;
            state->event_exploded_mine = 1;
            *removed_current = 1;
        } else if (obj->kind == NV14_NATIVE_EXIT_SWITCH) {
            size_t door_index;
            nv14_mask_set(state->open_exit, obj->state_index);
            state->event_opened_exit = 1;
            *removed_current = 1;
            for (door_index = 0; door_index < state->level->native_object_count; ++door_index) {
                const nv14_native_object *door = &state->level->native_objects[door_index];
                if (door->kind == NV14_NATIVE_EXIT_DOOR &&
                    door->state_index == obj->state_index) {
                    nv14_grid_add(state, door_index, nv14_cell_slot(door->cell_i, door->cell_j));
                    break;
                }
            }
        } else {
            nv14_player_celebrate(player);
            state->completed_exit_index = (int64_t)obj->state_index;
            state->level_complete = 1;
        }
        return NV14_STATUS_OK;
    }
    if (obj->kind == NV14_NATIVE_ONEWAY) {
        double dy = player->pos.y - obj->y;
        double pen_y = NV14_TILE_SCALE + player->yw - fabs(dy);
        if (pen_y > 0.0) {
            double dx = player->pos.x - obj->x;
            double pen_x = NV14_TILE_SCALE + player->xw - fabs(dx);
            if (pen_x > 0.0) {
                if (obj->a == 0.0) {
                    double movement = player->pos.y - player->oldpos.y;
                    if (movement * obj->b <= 0.0) {
                        double previous_edge_delta = player->oldpos.y - obj->b * player->yw -
                            (obj->y + obj->b * NV14_TILE_SCALE);
                        if (previous_edge_delta * obj->b >= 0.0) {
                            double correction = obj->y + obj->b * NV14_TILE_SCALE -
                                (player->pos.y - obj->b * player->yw);
                            nv14_player_report_object(player, 0.0, correction, 0.0, obj->b);
                        }
                    }
                } else {
                    double movement = player->pos.x - player->oldpos.x;
                    if (movement * obj->a <= 0.0) {
                        double previous_edge_delta = player->oldpos.x - obj->a * player->xw -
                            (obj->x + obj->a * NV14_TILE_SCALE);
                        if (previous_edge_delta * obj->a >= 0.0) {
                            double correction = obj->x + obj->a * NV14_TILE_SCALE -
                                (player->pos.x - obj->a * player->xw);
                            nv14_player_report_object(player, correction, 0.0, obj->a, 0.0);
                        }
                    }
                }
            }
        }
        return NV14_STATUS_OK;
    }
    if (obj->kind == NV14_NATIVE_LAUNCH) {
        double vx = obj->x - player->pos.x;
        double vy = obj->y - player->pos.y;
        if (sqrt(vx * vx + vy * vy) < obj->r + player->r) {
            double dx = obj->x - (player->pos.x - obj->a * player->r);
            double dy = obj->y - (player->pos.y - obj->b * player->r);
            double along_normal = dx * obj->a + dy * obj->b;
            if (along_normal >= 0.0) {
                double y_factor = 1.0;
                if (obj->b < 0.0) y_factor += fabs(obj->b);
                nv14_player_launch(
                    player,
                    obj->a * (NV14_TILE_SCALE * 0.4285714285714286),
                    obj->b * (NV14_TILE_SCALE * 0.4285714285714286) * y_factor
                );
            }
        }
    }
    if (obj->kind == NV14_NATIVE_LAUNCH) return NV14_STATUS_OK;
    {
        const nv14_internal_object_module *module =
            nv14_module_for_object(state, object_index);
        int handled = 0;
        nv14_status status;
        if (module == NULL || module->collide_player == NULL)
            return NV14_STATUS_UNSUPPORTED_OBJECTS;
        status = module->collide_player(
            state, object_index, &handled, removed_current
        );
        if (status != NV14_STATUS_OK) return status;
        return handled ? NV14_STATUS_OK : NV14_STATUS_UNSUPPORTED_OBJECTS;
    }
}

static nv14_status nv14_state_begin_player_step_internal(nv14_state *state)
{
    nv14_player_snapshot *player;
    nv14_status status;
    double old_x_before;
    double old_y_before;
    double current_x;
    double current_y;
    if (state == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    if (state->phase != 0) return NV14_STATUS_PHASE_ERROR;
    if (!state->level_complete) {
        status = nv14_run_native_object_updates(state);
        if (status != NV14_STATUS_OK) return status;
    }
    state->event_collected_gold = 0;
    state->event_exploded_mine = 0;
    state->event_opened_exit = 0;
    state->phase_jump_events_before = state->player.jump_events;
    state->phase_skip_player = state->level_complete || state->player.dead;
    state->phase = 1;
    if (state->level_complete || state->player.dead) return NV14_STATUS_OK;
    player = &state->player;
    old_x_before = player->oldpos.x;
    old_y_before = player->oldpos.y;
    player->oldpos.x = player->pos.x;
    current_x = player->oldpos.x;
    player->oldpos.y = player->pos.y;
    current_y = player->oldpos.y;
    player->pos.x += player->d * (current_x - old_x_before);
    player->pos.y += player->d * (current_y - old_y_before) + player->g;
    if (!nv14_python_floor_index(player->pos.x, NV14_TILE_W, &player->cell_i) ||
        !nv14_python_floor_index(player->pos.y, NV14_TILE_H, &player->cell_j)) {
        return NV14_STATUS_OUT_OF_BOUNDS;
    }
    player->old_v.x = player->pos.x - player->oldpos.x;
    player->old_v.y = player->pos.y - player->oldpos.y;
    player->was_in_air = player->in_air;
    player->near_wall = 0;
    player->in_air = 1;
    player->floor_count = 0;
    return NV14_STATUS_OK;
}

nv14_status nv14_state_begin_player_step(nv14_state *state)
{
    return nv14_state_begin_player_step_internal(state);
}

static nv14_status nv14_state_collide_native_objects_internal(nv14_state *state)
{
    static const int offsets[9][2] = {
        {0, 0}, {0, 1}, {1, 1}, {-1, 1}, {-1, 0},
        {-1, -1}, {1, 0}, {1, -1}, {0, -1}
    };
    int k;
    if (state == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    if (state->phase != 1) return NV14_STATUS_PHASE_ERROR;
    if (state->level_complete || state->player.dead) return NV14_STATUS_OK;
    if (state->level->native_object_count == 0) return NV14_STATUS_OK;
    for (k = 0; k < 9; ++k) {
        int slot = nv14_cell_slot(
            state->player.cell_i + offsets[k][0],
            state->player.cell_j + offsets[k][1]
        );
        int32_t object_index = slot >= 0 ? state->cell_heads[slot] : -1;
        while (object_index >= 0) {
            int32_t next = state->object_next[object_index];
            int removed = 0;
            nv14_status status = nv14_test_native_object(
                state, (size_t)object_index, &removed
            );
            if (status != NV14_STATUS_OK) return status;
            if (removed) {
                nv14_grid_remove(state, (size_t)object_index);
            }
            if (state->player.dead) break;
            if (removed) break;
            object_index = next;
        }
        if (state->player.dead) break;
    }
    return NV14_STATUS_OK;
}

nv14_status nv14_state_collide_native_objects(nv14_state *state)
{
    return nv14_state_collide_native_objects_internal(state);
}

static int nv14_edge_value(
    const nv14_state *state,
    const nv14_tile *tile,
    int side
)
{
    if (state->edge_override_count == 0) return tile->edges[side];
    size_t index = ((size_t)tile->i * NV14_TILE_ROWS + (size_t)tile->j) * 4u +
        (size_t)side;
    int override_value = state->edge_overrides[index];
    return override_value >= 0 ? override_value : tile->edges[side];
}

static int nv14_project_circle_full(
    double x,
    double y,
    int o_h,
    int o_v,
    nv14_player_snapshot *player,
    const nv14_tile *tile
)
{
    if (o_h == 0) {
        if (o_v == 0) {
            if (x < y) {
                double vx = player->pos.x - tile->x;
                if (vx < 0.0)
                    nv14_player_report_world(player, -x, 0.0, -1.0, 0.0);
                else
                    nv14_player_report_world(player, x, 0.0, 1.0, 0.0);
            } else {
                double vy = player->pos.y - tile->y;
                if (vy < 0.0)
                    nv14_player_report_world(player, 0.0, -y, 0.0, -1.0);
                else
                    nv14_player_report_world(player, 0.0, y, 0.0, 1.0);
            }
            return NV14_COL_AXIS;
        }
        nv14_player_report_world(player, 0.0, y * (double)o_v, 0.0, (double)o_v);
        return NV14_COL_AXIS;
    }
    if (o_v == 0) {
        nv14_player_report_world(player, x * (double)o_h, 0.0, (double)o_h, 0.0);
        return NV14_COL_AXIS;
    }
    {
        double corner_x = tile->x + (double)o_h * NV14_TILE_SCALE;
        double corner_y = tile->y + (double)o_v * NV14_TILE_SCALE;
        double vx = player->pos.x - corner_x;
        double vy = player->pos.y - corner_y;
        double length = sqrt(vx * vx + vy * vy);
        double penetration = player->r - length;
        if (penetration > 0.0) {
            if (length == 0.0) {
                vx = (double)o_h / sqrt(2.0);
                vy = (double)o_v / sqrt(2.0);
            } else {
                vx /= length;
                vy /= length;
            }
            nv14_player_report_world(
                player, vx * penetration, vy * penetration, vx, vy
            );
            return NV14_COL_OTHER;
        }
    }
    return NV14_COL_NONE;
}

static int nv14_project_circle_concave(
    double x,
    double y,
    int o_h,
    int o_v,
    nv14_player_snapshot *player,
    const nv14_tile *tile
)
{
    int signx = tile->signx;
    int signy = tile->signy;
    if (o_h == 0) {
        if (o_v == 0) {
            double vx = tile->x + (double)signx * NV14_TILE_SCALE - player->pos.x;
            double vy = tile->y + (double)signy * NV14_TILE_SCALE - player->pos.y;
            double radius = NV14_TILE_SCALE * 2.0;
            double length = sqrt(vx * vx + vy * vy);
            double penetration = length + player->r - radius;
            if (0.0 < penetration) {
                double len_p;
                if (x < y) {
                    len_p = x;
                    y = 0.0;
                    if (player->pos.x - tile->x < 0.0) x *= -1.0;
                } else {
                    len_p = y;
                    x = 0.0;
                    if (player->pos.y - tile->y < 0.0) y *= -1.0;
                }
                if (len_p < penetration) {
                    nv14_player_report_world(player, x, y, x / len_p, y / len_p);
                    return NV14_COL_AXIS;
                }
                vx /= length;
                vy /= length;
                nv14_player_report_world(
                    player, vx * penetration, vy * penetration, vx, vy
                );
                return NV14_COL_OTHER;
            }
            return NV14_COL_NONE;
        }
        if (signy * o_v < 0) {
            nv14_player_report_world(player, 0.0, y * (double)o_v, 0.0, (double)o_v);
            return NV14_COL_AXIS;
        }
        {
            double corner_x = tile->x - (double)signx * NV14_TILE_SCALE;
            double corner_y = tile->y + (double)o_v * NV14_TILE_SCALE;
            double vx = player->pos.x - corner_x;
            double vy = player->pos.y - corner_y;
            double length = sqrt(vx * vx + vy * vy);
            double penetration = player->r - length;
            if (0.0 < penetration) {
                if (length == 0.0) {
                    vx = 0.0;
                    vy = (double)o_v;
                } else {
                    vx /= length;
                    vy /= length;
                }
                nv14_player_report_world(
                    player, vx * penetration, vy * penetration, vx, vy
                );
                return NV14_COL_OTHER;
            }
        }
        return NV14_COL_NONE;
    }
    if (o_v == 0) {
        if (signx * o_h < 0) {
            nv14_player_report_world(player, x * (double)o_h, 0.0, (double)o_h, 0.0);
            return NV14_COL_AXIS;
        }
        {
            double corner_x = tile->x + (double)o_h * NV14_TILE_SCALE;
            double corner_y = tile->y - (double)signy * NV14_TILE_SCALE;
            double vx = player->pos.x - corner_x;
            double vy = player->pos.y - corner_y;
            double length = sqrt(vx * vx + vy * vy);
            double penetration = player->r - length;
            if (0.0 < penetration) {
                if (length == 0.0) {
                    vx = (double)o_h;
                    vy = 0.0;
                } else {
                    vx /= length;
                    vy /= length;
                }
                nv14_player_report_world(
                    player, vx * penetration, vy * penetration, vx, vy
                );
                return NV14_COL_OTHER;
            }
        }
        return NV14_COL_NONE;
    }
    if (0 < signx * o_h + signy * o_v) return NV14_COL_NONE;
    {
        double corner_x = tile->x + (double)o_h * NV14_TILE_SCALE;
        double corner_y = tile->y + (double)o_v * NV14_TILE_SCALE;
        double vx = player->pos.x - corner_x;
        double vy = player->pos.y - corner_y;
        double length = sqrt(vx * vx + vy * vy);
        double penetration = player->r - length;
        if (0.0 < penetration) {
            if (length == 0.0) {
                vx = (double)o_h / sqrt(2.0);
                vy = (double)o_v / sqrt(2.0);
            } else {
                vx /= length;
                vy /= length;
            }
            nv14_player_report_world(
                player, vx * penetration, vy * penetration, vx, vy
            );
            return NV14_COL_OTHER;
        }
    }
    return NV14_COL_NONE;
}

static int nv14_project_circle_convex_arc(
    nv14_player_snapshot *player,
    const nv14_tile *tile
)
{
    double vx = player->pos.x -
        (tile->x - (double)tile->signx * NV14_TILE_SCALE);
    double vy = player->pos.y -
        (tile->y - (double)tile->signy * NV14_TILE_SCALE);
    double radius = NV14_TILE_SCALE * 2.0;
    double length = sqrt(vx * vx + vy * vy);
    double penetration = radius + player->r - length;
    if (0.0 < penetration) {
        vx /= length;
        vy /= length;
        nv14_player_report_world(
            player, vx * penetration, vy * penetration, vx, vy
        );
        return NV14_COL_OTHER;
    }
    return NV14_COL_NONE;
}

static int nv14_project_circle_convex(
    double x,
    double y,
    int o_h,
    int o_v,
    nv14_player_snapshot *player,
    const nv14_tile *tile
)
{
    int signx = tile->signx;
    int signy = tile->signy;
    if (o_h == 0) {
        if (o_v == 0) {
            double vx = player->pos.x -
                (tile->x - (double)signx * NV14_TILE_SCALE);
            double vy = player->pos.y -
                (tile->y - (double)signy * NV14_TILE_SCALE);
            double radius = NV14_TILE_SCALE * 2.0;
            double length = sqrt(vx * vx + vy * vy);
            double penetration = radius + player->r - length;
            if (0.0 < penetration) {
                double len_p;
                if (x < y) {
                    len_p = x;
                    y = 0.0;
                    if (player->pos.x - tile->x < 0.0) x *= -1.0;
                } else {
                    len_p = y;
                    x = 0.0;
                    if (player->pos.y - tile->y < 0.0) y *= -1.0;
                }
                if (len_p < penetration) {
                    nv14_player_report_world(player, x, y, x / len_p, y / len_p);
                    return NV14_COL_AXIS;
                }
                vx /= length;
                vy /= length;
                nv14_player_report_world(
                    player, vx * penetration, vy * penetration, vx, vy
                );
                return NV14_COL_OTHER;
            }
            return NV14_COL_NONE;
        }
        if (signy * o_v < 0) {
            nv14_player_report_world(player, 0.0, y * (double)o_v, 0.0, (double)o_v);
            return NV14_COL_AXIS;
        }
        return nv14_project_circle_convex_arc(player, tile);
    }
    if (o_v == 0) {
        if (signx * o_h < 0) {
            nv14_player_report_world(player, x * (double)o_h, 0.0, (double)o_h, 0.0);
            return NV14_COL_AXIS;
        }
        return nv14_project_circle_convex_arc(player, tile);
    }
    if (0 < signx * o_h + signy * o_v)
        return nv14_project_circle_convex_arc(player, tile);
    {
        double corner_x = tile->x + (double)o_h * NV14_TILE_SCALE;
        double corner_y = tile->y + (double)o_v * NV14_TILE_SCALE;
        double vx = player->pos.x - corner_x;
        double vy = player->pos.y - corner_y;
        double length = sqrt(vx * vx + vy * vy);
        double penetration = player->r - length;
        if (0.0 < penetration) {
            if (length == 0.0) {
                vx = (double)o_h / sqrt(2.0);
                vy = (double)o_v / sqrt(2.0);
            } else {
                vx /= length;
                vy /= length;
            }
            nv14_player_report_world(
                player, vx * penetration, vy * penetration, vx, vy
            );
            return NV14_COL_OTHER;
        }
    }
    return NV14_COL_NONE;
}

static int nv14_project_circle_45(
    double x,
    double y,
    int o_h,
    int o_v,
    nv14_player_snapshot *player,
    const nv14_tile *tile
)
{
    int signx = tile->signx;
    int signy = tile->signy;
    if (o_h == 0) {
        if (o_v == 0) {
            double nx = tile->sx;
            double ny = tile->sy;
            double vx = player->pos.x - nx * player->r - tile->x;
            double vy = player->pos.y - ny * player->r - tile->y;
            double dp = vx * nx + vy * ny;
            if (dp < 0.0) {
                double len_p;
                double slope_len;
                nx *= -dp;
                ny *= -dp;
                if (x < y) {
                    len_p = x;
                    y = 0.0;
                    if (player->pos.x - tile->x < 0.0) x *= -1.0;
                } else {
                    len_p = y;
                    x = 0.0;
                    if (player->pos.y - tile->y < 0.0) y *= -1.0;
                }
                slope_len = sqrt(nx * nx + ny * ny);
                if (len_p < slope_len) {
                    nv14_player_report_world(player, x, y, x / len_p, y / len_p);
                    return NV14_COL_AXIS;
                }
                nv14_player_report_world(player, nx, ny, tile->sx, tile->sy);
                return NV14_COL_OTHER;
            }
        } else {
            double nx;
            double ny;
            double vx;
            double vy;
            double perpendicular;
            if (signy * o_v < 0) {
                nv14_player_report_world(player, 0.0, y * (double)o_v, 0.0, (double)o_v);
                return NV14_COL_AXIS;
            }
            nx = tile->sx;
            ny = tile->sy;
            vx = player->pos.x - (tile->x - (double)signx * NV14_TILE_SCALE);
            vy = player->pos.y - (tile->y + (double)o_v * NV14_TILE_SCALE);
            perpendicular = vx * -ny + vy * nx;
            if (0.0 < perpendicular * (double)signx * (double)signy) {
                double length = sqrt(vx * vx + vy * vy);
                double penetration = player->r - length;
                if (0.0 < penetration) {
                    vx /= length;
                    vy /= length;
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                    return NV14_COL_OTHER;
                }
            } else {
                double dp = vx * nx + vy * ny;
                double penetration = player->r - fabs(dp);
                if (0.0 < penetration) {
                    nv14_player_report_world(
                        player, nx * penetration, ny * penetration, nx, ny
                    );
                    return NV14_COL_OTHER;
                }
            }
        }
        return NV14_COL_NONE;
    }
    if (o_v == 0) {
        double nx;
        double ny;
        double vx;
        double vy;
        double perpendicular;
        if (signx * o_h < 0) {
            nv14_player_report_world(player, x * (double)o_h, 0.0, (double)o_h, 0.0);
            return NV14_COL_AXIS;
        }
        nx = tile->sx;
        ny = tile->sy;
        vx = player->pos.x - (tile->x + (double)o_h * NV14_TILE_SCALE);
        vy = player->pos.y - (tile->y - (double)signy * NV14_TILE_SCALE);
        perpendicular = vx * -ny + vy * nx;
        if (perpendicular * (double)signx * (double)signy < 0.0) {
            double length = sqrt(vx * vx + vy * vy);
            double penetration = player->r - length;
            if (0.0 < penetration) {
                vx /= length;
                vy /= length;
                nv14_player_report_world(
                    player, vx * penetration, vy * penetration, vx, vy
                );
                return NV14_COL_OTHER;
            }
        } else {
            double dp = vx * nx + vy * ny;
            double penetration = player->r - fabs(dp);
            if (0.0 < penetration) {
                nv14_player_report_world(
                    player, nx * penetration, ny * penetration, nx, ny
                );
                return NV14_COL_OTHER;
            }
        }
        return NV14_COL_NONE;
    }
    if (0 < signx * o_h + signy * o_v) return NV14_COL_NONE;
    {
        double corner_x = tile->x + (double)o_h * NV14_TILE_SCALE;
        double corner_y = tile->y + (double)o_v * NV14_TILE_SCALE;
        double vx = player->pos.x - corner_x;
        double vy = player->pos.y - corner_y;
        double length = sqrt(vx * vx + vy * vy);
        double penetration = player->r - length;
        if (0.0 < penetration) {
            if (length == 0.0) {
                vx = (double)o_h / sqrt(2.0);
                vy = (double)o_v / sqrt(2.0);
            } else {
                vx /= length;
                vy /= length;
            }
            nv14_player_report_world(
                player, vx * penetration, vy * penetration, vx, vy
            );
            return NV14_COL_OTHER;
        }
    }
    return NV14_COL_NONE;
}

static int nv14_project_circle_half(
    double x,
    double y,
    int o_h,
    int o_v,
    nv14_player_snapshot *player,
    const nv14_tile *tile
)
{
    int signx = tile->signx;
    int signy = tile->signy;
    int side = o_h * signx + o_v * signy;
    if (0 < side) return NV14_COL_NONE;
    if (o_h == 0) {
        if (o_v == 0) {
            double radius = player->r;
            double vx = player->pos.x - (double)signx * radius - tile->x;
            double vy = player->pos.y - (double)signy * radius - tile->y;
            double nx = (double)signx;
            double ny = (double)signy;
            double dp = vx * nx + vy * ny;
            if (dp < 0.0) {
                double slope_len;
                double axis_len;
                nx *= -dp;
                ny *= -dp;
                slope_len = sqrt(nx * nx + ny * ny);
                axis_len = sqrt(x * x + y * y);
                if (axis_len < slope_len) {
                    nv14_player_report_world(
                        player, x, y, x / axis_len, y / axis_len
                    );
                    return NV14_COL_AXIS;
                }
                nv14_player_report_world(
                    player, nx, ny, (double)signx, (double)signy
                );
                return NV14_COL_OTHER;
            }
        } else if (side == 0) {
            double vx = player->pos.x - tile->x;
            if (vx * (double)signx < 0.0) {
                nv14_player_report_world(player, 0.0, y * (double)o_v, 0.0, (double)o_v);
                return NV14_COL_AXIS;
            }
            {
                double vy = player->pos.y -
                    (tile->y + (double)o_v * NV14_TILE_SCALE);
                double length = sqrt(vx * vx + vy * vy);
                double penetration = player->r - length;
                if (0.0 < penetration) {
                    if (length == 0.0) {
                        vx = (double)signx / sqrt(2.0);
                        vy = (double)o_v / sqrt(2.0);
                    } else {
                        vx /= length;
                        vy /= length;
                    }
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                    return NV14_COL_OTHER;
                }
            }
        } else {
            nv14_player_report_world(player, 0.0, y * (double)o_v, 0.0, (double)o_v);
            return NV14_COL_AXIS;
        }
        return NV14_COL_NONE;
    }
    if (o_v == 0) {
        if (side == 0) {
            double vy = player->pos.y - tile->y;
            if (vy * (double)signy < 0.0) {
                nv14_player_report_world(player, x * (double)o_h, 0.0, (double)o_h, 0.0);
                return NV14_COL_AXIS;
            }
            {
                double vx = player->pos.x -
                    (tile->x + (double)o_h * NV14_TILE_SCALE);
                double length = sqrt(vx * vx + vy * vy);
                double penetration = player->r - length;
                if (0.0 < penetration) {
                    if (length == 0.0) {
                        vx = (double)signx / sqrt(2.0);
                        vy = (double)o_v / sqrt(2.0);
                    } else {
                        vx /= length;
                        vy /= length;
                    }
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                    return NV14_COL_OTHER;
                }
            }
        } else {
            nv14_player_report_world(player, x * (double)o_h, 0.0, (double)o_h, 0.0);
            return NV14_COL_AXIS;
        }
        return NV14_COL_NONE;
    }
    {
        double corner_x = tile->x + (double)o_h * NV14_TILE_SCALE;
        double corner_y = tile->y + (double)o_v * NV14_TILE_SCALE;
        double vx = player->pos.x - corner_x;
        double vy = player->pos.y - corner_y;
        double length = sqrt(vx * vx + vy * vy);
        double penetration = player->r - length;
        if (0.0 < penetration) {
            if (length == 0.0) {
                vx = (double)o_h / sqrt(2.0);
                vy = (double)o_v / sqrt(2.0);
            } else {
                vx /= length;
                vy /= length;
            }
            nv14_player_report_world(
                player, vx * penetration, vy * penetration, vx, vy
            );
            return NV14_COL_OTHER;
        }
    }
    return NV14_COL_NONE;
}

static int nv14_project_circle_22deg_s(
    double x,
    double y,
    int o_h,
    int o_v,
    nv14_player_snapshot *player,
    const nv14_tile *tile
)
{
    int signx = tile->signx;
    int signy = tile->signy;
    if (0 < signy * o_v) return NV14_COL_NONE;
    if (o_h == 0) {
        if (o_v == 0) {
            double nx = tile->sx;
            double ny = tile->sy;
            double radius = player->r;
            double vx = player->pos.x -
                (tile->x - (double)signx * NV14_TILE_SCALE);
            double vy = player->pos.y - tile->y;
            double perpendicular = vx * -ny + vy * nx;
            if (0.0 < perpendicular * (double)signx * (double)signy) {
                double length = sqrt(vx * vx + vy * vy);
                double penetration = radius - length;
                if (0.0 < penetration) {
                    vx /= length;
                    vy /= length;
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                    return NV14_COL_OTHER;
                }
            } else {
                double dp;
                vx -= radius * nx;
                vy -= radius * ny;
                dp = vx * nx + vy * ny;
                if (dp < 0.0) {
                    double slope_len;
                    double len_p;
                    nx *= -dp;
                    ny *= -dp;
                    slope_len = sqrt(nx * nx + ny * ny);
                    if (x < y) {
                        len_p = x;
                        y = 0.0;
                        if (player->pos.x - tile->x < 0.0) x *= -1.0;
                    } else {
                        len_p = y;
                        x = 0.0;
                        if (player->pos.y - tile->y < 0.0) y *= -1.0;
                    }
                    if (len_p < slope_len) {
                        nv14_player_report_world(
                            player, x, y, x / len_p, y / len_p
                        );
                        return NV14_COL_AXIS;
                    }
                    nv14_player_report_world(player, nx, ny, tile->sx, tile->sy);
                    return NV14_COL_OTHER;
                }
            }
        } else {
            nv14_player_report_world(player, 0.0, y * (double)o_v, 0.0, (double)o_v);
            return NV14_COL_AXIS;
        }
        return NV14_COL_NONE;
    }
    if (o_v == 0) {
        if (signx * o_h < 0) {
            double corner_x = tile->x - (double)signx * NV14_TILE_SCALE;
            double corner_y = tile->y;
            double vx = player->pos.x - corner_x;
            double vy = player->pos.y - corner_y;
            if (vy * (double)signy < 0.0) {
                nv14_player_report_world(player, x * (double)o_h, 0.0, (double)o_h, 0.0);
                return NV14_COL_AXIS;
            }
            {
                double length = sqrt(vx * vx + vy * vy);
                double penetration = player->r - length;
                if (0.0 < penetration) {
                    if (length == 0.0) {
                        vx = (double)o_h / sqrt(2.0);
                        vy = (double)o_v / sqrt(2.0);
                    } else {
                        vx /= length;
                        vy /= length;
                    }
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                    return NV14_COL_OTHER;
                }
            }
        } else {
            double nx = tile->sx;
            double ny = tile->sy;
            double vx = player->pos.x -
                (tile->x + (double)o_h * NV14_TILE_SCALE);
            double vy = player->pos.y -
                (tile->y - (double)signy * NV14_TILE_SCALE);
            double perpendicular = vx * -ny + vy * nx;
            if (perpendicular * (double)signx * (double)signy < 0.0) {
                double length = sqrt(vx * vx + vy * vy);
                double penetration = player->r - length;
                if (0.0 < penetration) {
                    vx /= length;
                    vy /= length;
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                    return NV14_COL_OTHER;
                }
            } else {
                double dp = vx * nx + vy * ny;
                double penetration = player->r - fabs(dp);
                if (0.0 < penetration) {
                    nv14_player_report_world(
                        player, nx * penetration, ny * penetration, nx, ny
                    );
                    return NV14_COL_OTHER;
                }
            }
        }
        return NV14_COL_NONE;
    }
    {
        double corner_x = tile->x + (double)o_h * NV14_TILE_SCALE;
        double corner_y = tile->y + (double)o_v * NV14_TILE_SCALE;
        double vx = player->pos.x - corner_x;
        double vy = player->pos.y - corner_y;
        double length = sqrt(vx * vx + vy * vy);
        double penetration = player->r - length;
        if (0.0 < penetration) {
            if (length == 0.0) {
                vx = (double)o_h / sqrt(2.0);
                vy = (double)o_v / sqrt(2.0);
            } else {
                vx /= length;
                vy /= length;
            }
            nv14_player_report_world(
                player, vx * penetration, vy * penetration, vx, vy
            );
            return NV14_COL_OTHER;
        }
    }
    return NV14_COL_NONE;
}

static int nv14_project_circle_22deg_b(
    double x,
    double y,
    int o_h,
    int o_v,
    nv14_player_snapshot *player,
    const nv14_tile *tile
)
{
    int signx = tile->signx;
    int signy = tile->signy;
    if (o_h == 0) {
        if (o_v == 0) {
            double nx = tile->sx;
            double ny = tile->sy;
            double radius = player->r;
            double vx = player->pos.x - nx * radius -
                (tile->x - (double)signx * NV14_TILE_SCALE);
            double vy = player->pos.y - ny * radius -
                (tile->y + (double)signy * NV14_TILE_SCALE);
            double dp = vx * nx + vy * ny;
            if (dp < 0.0) {
                double slope_len;
                double len_p;
                nx *= -dp;
                ny *= -dp;
                slope_len = sqrt(nx * nx + ny * ny);
                if (x < y) {
                    len_p = x;
                    y = 0.0;
                    if (player->pos.x - tile->x < 0.0) x *= -1.0;
                } else {
                    len_p = y;
                    x = 0.0;
                    if (player->pos.y - tile->y < 0.0) y *= -1.0;
                }
                if (len_p < slope_len) {
                    nv14_player_report_world(player, x, y, x / len_p, y / len_p);
                    return NV14_COL_AXIS;
                }
                nv14_player_report_world(player, nx, ny, tile->sx, tile->sy);
                return NV14_COL_OTHER;
            }
        } else {
            double nx;
            double ny;
            double vx;
            double vy;
            double perpendicular;
            if (signy * o_v < 0) {
                nv14_player_report_world(player, 0.0, y * (double)o_v, 0.0, (double)o_v);
                return NV14_COL_AXIS;
            }
            nx = tile->sx;
            ny = tile->sy;
            vx = player->pos.x -
                (tile->x - (double)signx * NV14_TILE_SCALE);
            vy = player->pos.y -
                (tile->y + (double)signy * NV14_TILE_SCALE);
            perpendicular = vx * -ny + vy * nx;
            if (0.0 < perpendicular * (double)signx * (double)signy) {
                double length = sqrt(vx * vx + vy * vy);
                double penetration = player->r - length;
                if (0.0 < penetration) {
                    vx /= length;
                    vy /= length;
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                    return NV14_COL_OTHER;
                }
            } else {
                double dp = vx * nx + vy * ny;
                double penetration = player->r - fabs(dp);
                if (0.0 < penetration) {
                    nv14_player_report_world(
                        player, nx * penetration, ny * penetration, nx, ny
                    );
                    return NV14_COL_OTHER;
                }
            }
        }
        return NV14_COL_NONE;
    }
    if (o_v == 0) {
        if (signx * o_h < 0) {
            nv14_player_report_world(player, x * (double)o_h, 0.0, (double)o_h, 0.0);
            return NV14_COL_AXIS;
        }
        {
            double vx = player->pos.x -
                (tile->x + (double)signx * NV14_TILE_SCALE);
            double vy = player->pos.y - tile->y;
            double nx;
            double ny;
            double perpendicular;
            if (vy * (double)signy < 0.0) {
                nv14_player_report_world(player, x * (double)o_h, 0.0, (double)o_h, 0.0);
                return NV14_COL_AXIS;
            }
            nx = tile->sx;
            ny = tile->sy;
            perpendicular = vx * -ny + vy * nx;
            if (perpendicular * (double)signx * (double)signy < 0.0) {
                double length = sqrt(vx * vx + vy * vy);
                double penetration = player->r - length;
                if (0.0 < penetration) {
                    vx /= length;
                    vy /= length;
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                    return NV14_COL_OTHER;
                }
            } else {
                double dp = vx * nx + vy * ny;
                double penetration = player->r - fabs(dp);
                if (0.0 < penetration) {
                    nv14_player_report_world(
                        player, nx * penetration, ny * penetration, tile->sx, tile->sy
                    );
                    return NV14_COL_OTHER;
                }
            }
        }
        return NV14_COL_NONE;
    }
    if (0 < signx * o_h + signy * o_v) {
        double nx = (double)signx * 1.0 / NV14_ROOT5;
        double ny = (double)signy * 2.0 / NV14_ROOT5;
        double radius = player->r;
        double vx = player->pos.x - nx * radius -
            (tile->x - (double)signx * NV14_TILE_SCALE);
        double vy = player->pos.y - ny * radius -
            (tile->y + (double)signy * NV14_TILE_SCALE);
        double dp = vx * nx + vy * ny;
        if (dp < 0.0) {
            nv14_player_report_world(
                player, -nx * dp, -ny * dp, tile->sx, tile->sy
            );
            return NV14_COL_OTHER;
        }
        return NV14_COL_NONE;
    }
    {
        double corner_x = tile->x + (double)o_h * NV14_TILE_SCALE;
        double corner_y = tile->y + (double)o_v * NV14_TILE_SCALE;
        double vx = player->pos.x - corner_x;
        double vy = player->pos.y - corner_y;
        double length = sqrt(vx * vx + vy * vy);
        double penetration = player->r - length;
        if (0.0 < penetration) {
            if (length == 0.0) {
                vx = (double)o_h / sqrt(2.0);
                vy = (double)o_v / sqrt(2.0);
            } else {
                vx /= length;
                vy /= length;
            }
            nv14_player_report_world(
                player, vx * penetration, vy * penetration, vx, vy
            );
            return NV14_COL_OTHER;
        }
    }
    return NV14_COL_NONE;
}

static int nv14_project_circle_67deg_s(
    double x,
    double y,
    int o_h,
    int o_v,
    nv14_player_snapshot *player,
    const nv14_tile *tile
)
{
    int signx = tile->signx;
    int signy = tile->signy;
    if (0 < signx * o_h) return NV14_COL_NONE;
    if (o_h == 0) {
        if (o_v == 0) {
            double nx = tile->sx;
            double ny = tile->sy;
            double radius = player->r;
            double vx = player->pos.x - tile->x;
            double vy = player->pos.y -
                (tile->y - (double)signy * NV14_TILE_SCALE);
            double perpendicular = vx * -ny + vy * nx;
            if (perpendicular * (double)signx * (double)signy < 0.0) {
                double length = sqrt(vx * vx + vy * vy);
                double penetration = radius - length;
                if (0.0 < penetration) {
                    vx /= length;
                    vy /= length;
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                    return NV14_COL_OTHER;
                }
            } else {
                double dp;
                vx -= radius * nx;
                vy -= radius * ny;
                dp = vx * nx + vy * ny;
                if (dp < 0.0) {
                    double slope_len;
                    double len_p;
                    nx *= -dp;
                    ny *= -dp;
                    slope_len = sqrt(nx * nx + ny * ny);
                    if (x < y) {
                        len_p = x;
                        y = 0.0;
                        if (player->pos.x - tile->x < 0.0) x *= -1.0;
                    } else {
                        len_p = y;
                        x = 0.0;
                        if (player->pos.y - tile->y < 0.0) y *= -1.0;
                    }
                    if (len_p < slope_len) {
                        nv14_player_report_world(player, x, y, x / len_p, y / len_p);
                        return NV14_COL_AXIS;
                    }
                    nv14_player_report_world(player, nx, ny, tile->sx, tile->sy);
                    return NV14_COL_OTHER;
                }
            }
        } else if (signy * o_v < 0) {
            double corner_x = tile->x;
            double corner_y = tile->y - (double)signy * NV14_TILE_SCALE;
            double vx = player->pos.x - corner_x;
            double vy = player->pos.y - corner_y;
            if (vx * (double)signx < 0.0) {
                nv14_player_report_world(player, 0.0, y * (double)o_v, 0.0, (double)o_v);
                return NV14_COL_AXIS;
            }
            {
                double length = sqrt(vx * vx + vy * vy);
                double penetration = player->r - length;
                if (0.0 < penetration) {
                    if (length == 0.0) {
                        vx = (double)o_h / sqrt(2.0);
                        vy = (double)o_v / sqrt(2.0);
                    } else {
                        vx /= length;
                        vy /= length;
                    }
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                    return NV14_COL_OTHER;
                }
            }
        } else {
            double nx = tile->sx;
            double ny = tile->sy;
            double vx = player->pos.x -
                (tile->x - (double)signx * NV14_TILE_SCALE);
            double vy = player->pos.y -
                (tile->y + (double)o_v * NV14_TILE_SCALE);
            double perpendicular = vx * -ny + vy * nx;
            if (0.0 < perpendicular * (double)signx * (double)signy) {
                double length = sqrt(vx * vx + vy * vy);
                double penetration = player->r - length;
                if (0.0 < penetration) {
                    vx /= length;
                    vy /= length;
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                    return NV14_COL_OTHER;
                }
            } else {
                double dp = vx * nx + vy * ny;
                double penetration = player->r - fabs(dp);
                if (0.0 < penetration) {
                    nv14_player_report_world(
                        player, nx * penetration, ny * penetration, tile->sx, tile->sy
                    );
                    return NV14_COL_OTHER;
                }
            }
        }
        return NV14_COL_NONE;
    }
    if (o_v == 0) {
        nv14_player_report_world(player, x * (double)o_h, 0.0, (double)o_h, 0.0);
        return NV14_COL_AXIS;
    }
    {
        double corner_x = tile->x + (double)o_h * NV14_TILE_SCALE;
        double corner_y = tile->y + (double)o_v * NV14_TILE_SCALE;
        double vx = player->pos.x - corner_x;
        double vy = player->pos.y - corner_y;
        double length = sqrt(vx * vx + vy * vy);
        double penetration = player->r - length;
        if (0.0 < penetration) {
            if (length == 0.0) {
                vx = (double)o_h / sqrt(2.0);
                vy = (double)o_v / sqrt(2.0);
            } else {
                vx /= length;
                vy /= length;
            }
            nv14_player_report_world(
                player, vx * penetration, vy * penetration, vx, vy
            );
            return NV14_COL_OTHER;
        }
    }
    return NV14_COL_NONE;
}

static int nv14_project_circle_67deg_b(
    double x,
    double y,
    int o_h,
    int o_v,
    nv14_player_snapshot *player,
    const nv14_tile *tile
)
{
    int signx = tile->signx;
    int signy = tile->signy;
    if (o_h == 0) {
        if (o_v == 0) {
            double nx = tile->sx;
            double ny = tile->sy;
            double radius = player->r;
            double vx = player->pos.x - nx * radius -
                (tile->x + (double)signx * NV14_TILE_SCALE);
            double vy = player->pos.y - ny * radius -
                (tile->y - (double)signy * NV14_TILE_SCALE);
            double dp = vx * nx + vy * ny;
            if (dp < 0.0) {
                double slope_len;
                double len_p;
                nx *= -dp;
                ny *= -dp;
                slope_len = sqrt(nx * nx + ny * ny);
                if (x < y) {
                    len_p = x;
                    y = 0.0;
                    if (player->pos.x - tile->x < 0.0) x *= -1.0;
                } else {
                    len_p = y;
                    x = 0.0;
                    if (player->pos.y - tile->y < 0.0) y *= -1.0;
                }
                if (len_p < slope_len) {
                    nv14_player_report_world(player, x, y, x / len_p, y / len_p);
                    return NV14_COL_AXIS;
                }
                nv14_player_report_world(player, nx, ny, tile->sx, tile->sy);
                return NV14_COL_OTHER;
            }
        } else {
            double vx;
            double vy;
            double nx;
            double ny;
            double perpendicular;
            if (signy * o_v < 0) {
                nv14_player_report_world(player, 0.0, y * (double)o_v, 0.0, (double)o_v);
                return NV14_COL_AXIS;
            }
            vx = player->pos.x - tile->x;
            vy = player->pos.y -
                (tile->y + (double)signy * NV14_TILE_SCALE);
            if (vx * (double)signx < 0.0) {
                nv14_player_report_world(player, 0.0, y * (double)o_v, 0.0, (double)o_v);
                return NV14_COL_AXIS;
            }
            nx = tile->sx;
            ny = tile->sy;
            perpendicular = vx * -ny + vy * nx;
            if (0.0 < perpendicular * (double)signx * (double)signy) {
                double length = sqrt(vx * vx + vy * vy);
                double penetration = player->r - length;
                if (0.0 < penetration) {
                    vx /= length;
                    vy /= length;
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                    return NV14_COL_OTHER;
                }
            } else {
                double dp = vx * nx + vy * ny;
                double penetration = player->r - fabs(dp);
                if (0.0 < penetration) {
                    nv14_player_report_world(
                        player, nx * penetration, ny * penetration, nx, ny
                    );
                    return NV14_COL_OTHER;
                }
            }
        }
        return NV14_COL_NONE;
    }
    if (o_v == 0) {
        double nx;
        double ny;
        double vx;
        double vy;
        double perpendicular;
        if (signx * o_h < 0) {
            nv14_player_report_world(player, x * (double)o_h, 0.0, (double)o_h, 0.0);
            return NV14_COL_AXIS;
        }
        nx = (double)signx * 2.0 / NV14_ROOT5;
        ny = (double)signy * 1.0 / NV14_ROOT5;
        vx = player->pos.x -
            (tile->x + (double)signx * NV14_TILE_SCALE);
        vy = player->pos.y -
            (tile->y - (double)signy * NV14_TILE_SCALE);
        perpendicular = vx * -ny + vy * nx;
        if (perpendicular * (double)signx * (double)signy < 0.0) {
            double length = sqrt(vx * vx + vy * vy);
            double penetration = player->r - length;
            if (0.0 < penetration) {
                vx /= length;
                vy /= length;
                nv14_player_report_world(
                    player, vx * penetration, vy * penetration, vx, vy
                );
                return NV14_COL_OTHER;
            }
        } else {
            double dp = vx * nx + vy * ny;
            double penetration = player->r - fabs(dp);
            if (0.0 < penetration) {
                nv14_player_report_world(
                    player, nx * penetration, ny * penetration, tile->sx, tile->sy
                );
                return NV14_COL_OTHER;
            }
        }
        return NV14_COL_NONE;
    }
    if (0 < signx * o_h + signy * o_v) {
        double nx = tile->sx;
        double ny = tile->sy;
        double radius = player->r;
        double vx = player->pos.x - nx * radius -
            (tile->x + (double)signx * NV14_TILE_SCALE);
        double vy = player->pos.y - ny * radius -
            (tile->y - (double)signy * NV14_TILE_SCALE);
        double dp = vx * nx + vy * ny;
        if (dp < 0.0) {
            nv14_player_report_world(
                player, -nx * dp, -ny * dp, tile->sx, tile->sy
            );
            return NV14_COL_OTHER;
        }
        return NV14_COL_NONE;
    }
    {
        double corner_x = tile->x + (double)o_h * NV14_TILE_SCALE;
        double corner_y = tile->y + (double)o_v * NV14_TILE_SCALE;
        double vx = player->pos.x - corner_x;
        double vy = player->pos.y - corner_y;
        double length = sqrt(vx * vx + vy * vy);
        double penetration = player->r - length;
        if (0.0 < penetration) {
            if (length == 0.0) {
                vx = (double)o_h / sqrt(2.0);
                vy = (double)o_v / sqrt(2.0);
            } else {
                vx /= length;
                vy /= length;
            }
            nv14_player_report_world(
                player, vx * penetration, vy * penetration, vx, vy
            );
            return NV14_COL_OTHER;
        }
    }
    return NV14_COL_NONE;
}

static nv14_status nv14_resolve_circle_tile(
    double x,
    double y,
    int o_h,
    int o_v,
    nv14_player_snapshot *player,
    const nv14_tile *tile,
    int *collision_out
)
{
    if (tile->tile_id == NV14_TID_EMPTY) {
        *collision_out = NV14_COL_NONE;
        return NV14_STATUS_OK;
    }
    if (tile->ctype == NV14_CTYPE_FULL) {
        *collision_out = nv14_project_circle_full(x, y, o_h, o_v, player, tile);
        return NV14_STATUS_OK;
    }
    if (tile->ctype == NV14_CTYPE_45DEG) {
        *collision_out = nv14_project_circle_45(x, y, o_h, o_v, player, tile);
        return NV14_STATUS_OK;
    }
    if (tile->ctype == NV14_CTYPE_CONCAVE) {
        *collision_out = nv14_project_circle_concave(x, y, o_h, o_v, player, tile);
        return NV14_STATUS_OK;
    }
    if (tile->ctype == NV14_CTYPE_CONVEX) {
        *collision_out = nv14_project_circle_convex(x, y, o_h, o_v, player, tile);
        return NV14_STATUS_OK;
    }
    if (tile->ctype == NV14_CTYPE_22DEGS) {
        *collision_out = nv14_project_circle_22deg_s(x, y, o_h, o_v, player, tile);
        return NV14_STATUS_OK;
    }
    if (tile->ctype == NV14_CTYPE_22DEGB) {
        *collision_out = nv14_project_circle_22deg_b(x, y, o_h, o_v, player, tile);
        return NV14_STATUS_OK;
    }
    if (tile->ctype == NV14_CTYPE_67DEGS) {
        *collision_out = nv14_project_circle_67deg_s(x, y, o_h, o_v, player, tile);
        return NV14_STATUS_OK;
    }
    if (tile->ctype == NV14_CTYPE_67DEGB) {
        *collision_out = nv14_project_circle_67deg_b(x, y, o_h, o_v, player, tile);
        return NV14_STATUS_OK;
    }
    if (tile->ctype == NV14_CTYPE_HALF) {
        *collision_out = nv14_project_circle_half(x, y, o_h, o_v, player, tile);
        return NV14_STATUS_OK;
    }
    *collision_out = NV14_COL_NONE;
    return NV14_STATUS_UNSUPPORTED_TILE;
}

static nv14_status nv14_collide_circle_tiles(nv14_state *state)
{
    nv14_player_snapshot *player = &state->player;
    const nv14_level *level = state->level;
    const nv14_tile *centre;
    const nv14_tile *v_neighbour = NULL;
    const nv14_tile *h_neighbour = NULL;
    double cx;
    double cy;
    double dx;
    double dy;
    double px;
    double py;
    int centre_i;
    int centre_j;
    int crossed_v = 0;
    int crossed_h = 0;
    int col_v = NV14_COL_NONE;
    int col_h = NV14_COL_NONE;
    int o_v = 0;
    int o_h = 0;
    nv14_status status;
    if (!nv14_python_floor_index(player->pos.x, NV14_TILE_W, &centre_i) ||
        !nv14_python_floor_index(player->pos.y, NV14_TILE_H, &centre_j))
        return NV14_STATUS_OUT_OF_BOUNDS;
    centre = nv14_tile_at_const(level, centre_i, centre_j);
    if (centre == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
    cx = centre->x;
    cy = centre->y;
    dx = player->pos.x - cx;
    dy = player->pos.y - cy;
    if (centre->tile_id > NV14_TID_EMPTY) {
        px = NV14_TILE_SCALE + player->r - fabs(dx);
        py = NV14_TILE_SCALE + player->r - fabs(dy);
        status = nv14_resolve_circle_tile(px, py, 0, 0, player, centre, &col_v);
        if (status != NV14_STATUS_OK) return status;
    }
    dy = player->pos.y - cy;
    py = fabs(dy) + player->r - NV14_TILE_SCALE;
    if (py > 0.0) {
        int edge_value;
        crossed_v = 1;
        if (dy < 0.0) {
            edge_value = nv14_edge_value(state, centre, NV14_EDGE_U);
            v_neighbour = nv14_tile_at_const(level, centre_i, centre_j - 1);
            o_v = 1;
        } else {
            edge_value = nv14_edge_value(state, centre, NV14_EDGE_D);
            v_neighbour = nv14_tile_at_const(level, centre_i, centre_j + 1);
            o_v = -1;
        }
        if (v_neighbour == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
        if (edge_value > NV14_EID_OFF) {
            if (edge_value == NV14_EID_SOLID) {
                col_v = NV14_COL_AXIS;
                nv14_player_report_world(
                    player, 0.0, py * (double)o_v, 0.0, (double)o_v
                );
            } else {
                status = nv14_resolve_circle_tile(
                    0.0, py, 0, o_v, player, v_neighbour, &col_v
                );
                if (status != NV14_STATUS_OK) return status;
            }
        }
    }
    dx = player->pos.x - cx;
    px = fabs(dx) + player->r - NV14_TILE_SCALE;
    if (px > 0.0) {
        int edge_value;
        crossed_h = 1;
        if (dx < 0.0) {
            edge_value = nv14_edge_value(state, centre, NV14_EDGE_L);
            h_neighbour = nv14_tile_at_const(level, centre_i - 1, centre_j);
            o_h = 1;
        } else {
            edge_value = nv14_edge_value(state, centre, NV14_EDGE_R);
            h_neighbour = nv14_tile_at_const(level, centre_i + 1, centre_j);
            o_h = -1;
        }
        if (h_neighbour == NULL) return NV14_STATUS_OUT_OF_BOUNDS;
        if (edge_value > NV14_EID_OFF) {
            if (edge_value == NV14_EID_SOLID) {
                col_h = NV14_COL_AXIS;
                nv14_player_report_world(
                    player, px * (double)o_h, 0.0, (double)o_h, 0.0
                );
            } else {
                status = nv14_resolve_circle_tile(
                    px, 0.0, o_h, 0, player, h_neighbour, &col_h
                );
                if (status != NV14_STATUS_OK) return status;
            }
        }
    }
    if (crossed_h && col_h != NV14_COL_AXIS &&
        crossed_v && col_v != NV14_COL_AXIS) {
        const nv14_tile *h_cell;
        const nv14_tile *v_cell;
        const nv14_tile *diagonal;
        int edge_h;
        int edge_v;
        if (dx < 0.0 && dy < 0.0) {
            h_cell = nv14_tile_at_const(level, centre_i, centre_j - 1);
            v_cell = nv14_tile_at_const(level, centre_i - 1, centre_j);
            diagonal = nv14_tile_at_const(level, centre_i - 1, centre_j - 1);
            if (h_cell == NULL || v_cell == NULL || diagonal == NULL)
                return NV14_STATUS_OUT_OF_BOUNDS;
            edge_h = nv14_edge_value(state, h_cell, NV14_EDGE_L);
            edge_v = nv14_edge_value(state, v_cell, NV14_EDGE_U);
        } else if (dx < 0.0 && dy > 0.0) {
            h_cell = nv14_tile_at_const(level, centre_i, centre_j + 1);
            v_cell = nv14_tile_at_const(level, centre_i - 1, centre_j);
            diagonal = nv14_tile_at_const(level, centre_i - 1, centre_j + 1);
            if (h_cell == NULL || v_cell == NULL || diagonal == NULL)
                return NV14_STATUS_OUT_OF_BOUNDS;
            edge_h = nv14_edge_value(state, h_cell, NV14_EDGE_L);
            edge_v = nv14_edge_value(state, v_cell, NV14_EDGE_D);
        } else if (dx > 0.0 && dy > 0.0) {
            h_cell = nv14_tile_at_const(level, centre_i, centre_j + 1);
            v_cell = nv14_tile_at_const(level, centre_i + 1, centre_j);
            diagonal = nv14_tile_at_const(level, centre_i + 1, centre_j + 1);
            if (h_cell == NULL || v_cell == NULL || diagonal == NULL)
                return NV14_STATUS_OUT_OF_BOUNDS;
            edge_h = nv14_edge_value(state, h_cell, NV14_EDGE_R);
            edge_v = nv14_edge_value(state, v_cell, NV14_EDGE_D);
        } else if (dx > 0.0 && dy < 0.0) {
            h_cell = nv14_tile_at_const(level, centre_i, centre_j - 1);
            v_cell = nv14_tile_at_const(level, centre_i + 1, centre_j);
            diagonal = nv14_tile_at_const(level, centre_i + 1, centre_j - 1);
            if (h_cell == NULL || v_cell == NULL || diagonal == NULL)
                return NV14_STATUS_OUT_OF_BOUNDS;
            edge_h = nv14_edge_value(state, h_cell, NV14_EDGE_R);
            edge_v = nv14_edge_value(state, v_cell, NV14_EDGE_U);
        } else {
            return NV14_STATUS_OK;
        }
        if (edge_h + edge_v > 0) {
            if (edge_h == NV14_EID_SOLID || edge_v == NV14_EID_SOLID) {
                double corner_x = diagonal->x + (double)o_h * NV14_TILE_SCALE;
                double corner_y = diagonal->y + (double)o_v * NV14_TILE_SCALE;
                double vx = player->pos.x - corner_x;
                double vy = player->pos.y - corner_y;
                double length = sqrt(vx * vx + vy * vy);
                double penetration = player->r - length;
                if (penetration > 0.0) {
                    if (length == 0.0) {
                        vx = (double)o_h / sqrt(2.0);
                        vy = (double)o_v / sqrt(2.0);
                    } else {
                        vx /= length;
                        vy /= length;
                    }
                    nv14_player_report_world(
                        player, vx * penetration, vy * penetration, vx, vy
                    );
                }
            } else {
                double px2 = fabs(player->pos.x - diagonal->x) +
                    player->r - NV14_TILE_SCALE;
                double py2 = fabs(player->pos.y - diagonal->y) +
                    player->r - NV14_TILE_SCALE;
                int ignored;
                status = nv14_resolve_circle_tile(
                    px2, py2, o_h, o_v, player, diagonal, &ignored
                );
                if (status != NV14_STATUS_OK) return status;
            }
        }
    }
    return NV14_STATUS_OK;
}

static void nv14_fill_step_result(
    const nv14_state *state,
    uint64_t frame_before,
    uint64_t jumps_before,
    uint8_t jump_callable,
    nv14_status status,
    nv14_step_result *result_out
)
{
    if (result_out == NULL) return;
    memset(result_out, 0, sizeof(*result_out));
    result_out->frame_before = frame_before;
    result_out->frame_after = state->frame;
    result_out->jump_events_before = jumps_before;
    result_out->jump_events_after = state->player.jump_events;
    result_out->dead = state->player.dead;
    result_out->level_complete = state->level_complete;
    result_out->jumped = state->player.jump_events > jumps_before;
    result_out->collected_gold = state->event_collected_gold;
    result_out->exploded_mine = state->event_exploded_mine;
    result_out->opened_exit = state->event_opened_exit;
    result_out->unsupported = status == NV14_STATUS_UNSUPPORTED_TILE ||
        status == NV14_STATUS_UNSUPPORTED_OBJECTS;
    result_out->jump_callable = jump_callable;
}

static int nv14_player_jump_callable(const nv14_player_snapshot *player)
{
    int state = player->state;
    if (state == NV14_PLAYER_CELEBRATING) return 0;
    if (player->in_air) {
        if (state < NV14_PLAYER_JUMPING || state == NV14_PLAYER_JUMPING)
            return 0;
        return player->near_wall != 0;
    }
    return state <= NV14_PLAYER_SKIDDING;
}

static nv14_status nv14_finish_player_step_internal(
    nv14_state *state,
    nv14_input input,
    const nv14_step_hooks *hooks,
    nv14_step_result *result_out,
    const nv14_input *alternate_input,
    nv14_player_snapshot *alternate_player_out,
    nv14_step_result *alternate_result_out
)
{
    nv14_status status = NV14_STATUS_OK;
    uint64_t frame_before;
    uint64_t jumps_before;
    size_t module_index;
    int horizontal;
    int jump_trigger;
    uint8_t jump_callable = 0;
    nv14_player_snapshot alternate_player;
    int have_alternate = alternate_input != NULL;
    if (state == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    if (state->phase != 1) return NV14_STATUS_PHASE_ERROR;
    if (have_alternate &&
        (alternate_player_out == NULL || alternate_result_out == NULL ||
         hooks != NULL))
        return NV14_STATUS_INVALID_ARGUMENT;
    frame_before = state->frame;
    jumps_before = state->phase_jump_events_before;
    /* A door touched during this collision pass sets level_complete, but the
       source still performs tile collision and ThinkCelebrate on that same
       frame.  Only a state that was already complete before Begin skips the
       player tick. */
    if (!state->phase_skip_player && !state->player.dead) {
        double pre_tile_x = state->player.pos.x;
        double pre_tile_y = state->player.pos.y;
        int collision_i;
        int collision_j;
        status = nv14_collide_circle_tiles(state);
        if (status != NV14_STATUS_OK) {
            nv14_fill_step_result(
                state, frame_before, jumps_before, jump_callable, status, result_out
            );
            return status;
        }
        status = nv14_player_handle_collisions(&state->player, state->level);
        if (status != NV14_STATUS_OK) {
            nv14_fill_step_result(
                state, frame_before, jumps_before, jump_callable, status, result_out
            );
            return status;
        }
        if (state->player.pos.x == pre_tile_x && state->player.pos.y == pre_tile_y) {
            if (!nv14_python_floor_index(pre_tile_x, NV14_TILE_W, &collision_i) ||
                !nv14_python_floor_index(pre_tile_y, NV14_TILE_H, &collision_j)) {
                return NV14_STATUS_OUT_OF_BOUNDS;
            }
            state->player.cell_i = collision_i;
            state->player.cell_j = collision_j;
        } else if (!nv14_python_floor_index(
                       state->player.pos.x, NV14_TILE_W, &state->player.cell_i) ||
                   !nv14_python_floor_index(
                       state->player.pos.y, NV14_TILE_H, &state->player.cell_j)) {
            return NV14_STATUS_OUT_OF_BOUNDS;
        }
        jump_callable = (uint8_t)nv14_player_jump_callable(&state->player);
        if (have_alternate) {
            int alternate_jump_trigger;
            int alternate_horizontal;
            alternate_player = state->player;
            alternate_jump_trigger = alternate_input->jump_trigger < 0
                ? (alternate_input->jump != 0 &&
                   !alternate_player.previous_jump_held)
                : alternate_input->jump_trigger != 0;
            alternate_horizontal =
                (alternate_input->right != 0) - (alternate_input->left != 0);
            nv14_player_think(
                &alternate_player,
                alternate_horizontal,
                alternate_input->jump != 0,
                alternate_jump_trigger
            );
            alternate_player.previous_jump_held = alternate_input->jump != 0;
        }
        jump_trigger = input.jump_trigger < 0
            ? (input.jump != 0 && !state->player.previous_jump_held)
            : input.jump_trigger != 0;
        horizontal = (input.right != 0) - (input.left != 0);
        nv14_player_think(&state->player, horizontal, input.jump != 0, jump_trigger);
        state->player.previous_jump_held = input.jump != 0;
    } else if (have_alternate) {
        alternate_player = state->player;
    }
    for (module_index = 0;
         module_index < state->level->object_module_count;
         ++module_index) {
        const nv14_internal_object_module *module =
            state->level->object_modules[module_index];
        if (module->post_player != NULL) {
            status = module->post_player(state);
            if (status != NV14_STATUS_OK) {
                nv14_fill_step_result(
                    state, frame_before, jumps_before, jump_callable,
                    status, result_out
                );
                return status;
            }
        }
    }
    if (hooks != NULL && hooks->callback != NULL) {
        status = hooks->callback(
            hooks->userdata, NV14_HOOK_POST_PLAYER, state->level, state, &input
        );
        if (status != NV14_STATUS_OK) {
            nv14_fill_step_result(
                state, frame_before, jumps_before, jump_callable, status, result_out
            );
            return NV14_STATUS_HOOK_ERROR;
        }
    }
    ++state->frame;
    state->phase = 0;
    nv14_fill_step_result(
        state, frame_before, jumps_before, jump_callable, NV14_STATUS_OK, result_out
    );
    if (have_alternate) {
        memset(alternate_result_out, 0, sizeof(*alternate_result_out));
        alternate_result_out->frame_before = frame_before;
        alternate_result_out->frame_after = state->frame;
        alternate_result_out->jump_events_before = jumps_before;
        alternate_result_out->jump_events_after = alternate_player.jump_events;
        alternate_result_out->dead = alternate_player.dead;
        alternate_result_out->level_complete = state->level_complete;
        alternate_result_out->jumped =
            alternate_player.jump_events > jumps_before;
        alternate_result_out->collected_gold = state->event_collected_gold;
        alternate_result_out->exploded_mine = state->event_exploded_mine;
        alternate_result_out->opened_exit = state->event_opened_exit;
        alternate_result_out->jump_callable = jump_callable;
        *alternate_player_out = alternate_player;
    }
    return NV14_STATUS_OK;
}

nv14_status nv14_state_finish_player_step(
    nv14_state *state,
    nv14_input input,
    nv14_step_result *result_out
)
{
    return nv14_finish_player_step_internal(
        state, input, NULL, result_out, NULL, NULL, NULL
    );
}

static nv14_status nv14_state_step_internal(
    nv14_state *state,
    nv14_input input,
    const nv14_step_hooks *hooks,
    nv14_step_result *result_out
)
{
    nv14_status status;
    uint64_t frame_before;
    uint64_t jumps_before;
    int replace_collision = 0;
    if (state == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    frame_before = state->frame;
    jumps_before = state->player.jump_events;
    if ((state->level->capabilities & NV14_CAP_TILE_COLLISION) == 0) {
        nv14_fill_step_result(state, frame_before, jumps_before,
            0, NV14_STATUS_UNSUPPORTED_TILE, result_out);
        return NV14_STATUS_UNSUPPORTED_TILE;
    }
    if (state->level->unsupported_object_mask != 0) {
        if (hooks == NULL ||
            (hooks->flags & NV14_HOOK_SUPPORTS_DYNAMIC_OBJECTS) == 0) {
            nv14_fill_step_result(state, frame_before, jumps_before,
                0, NV14_STATUS_UNSUPPORTED_OBJECTS, result_out);
            return NV14_STATUS_UNSUPPORTED_OBJECTS;
        }
    }
    if (hooks != NULL) {
        if (hooks->abi_version != NV14_CORE_ABI_VERSION ||
            hooks->struct_size < sizeof(*hooks))
            return NV14_STATUS_INVALID_ARGUMENT;
        replace_collision =
            (hooks->flags & NV14_HOOK_REPLACE_COLLISION_TRAVERSAL) != 0;
    }
    if (state->level_complete) {
        state->event_collected_gold = 0;
        state->event_exploded_mine = 0;
        state->event_opened_exit = 0;
        ++state->frame;
        nv14_fill_step_result(
            state, frame_before, jumps_before, 0, NV14_STATUS_OK, result_out
        );
        return NV14_STATUS_OK;
    }
    if (hooks != NULL && hooks->callback != NULL) {
        status = hooks->callback(
            hooks->userdata, NV14_HOOK_PRE_PLAYER, state->level, state, &input
        );
        if (status != NV14_STATUS_OK) return NV14_STATUS_HOOK_ERROR;
    }
    status = nv14_state_begin_player_step_internal(state);
    if (status != NV14_STATUS_OK) return status;
    if (!state->player.dead) {
        if (replace_collision) {
            if (hooks == NULL || hooks->callback == NULL) return NV14_STATUS_INVALID_ARGUMENT;
            status = hooks->callback(
                hooks->userdata,
                NV14_HOOK_PLAYER_OBJECT_COLLISION,
                state->level,
                state,
                &input
            );
            if (status != NV14_STATUS_OK) return NV14_STATUS_HOOK_ERROR;
        } else {
            status = nv14_state_collide_native_objects_internal(state);
            if (status != NV14_STATUS_OK) return status;
            if (hooks != NULL && hooks->callback != NULL) {
                status = hooks->callback(
                    hooks->userdata,
                    NV14_HOOK_PLAYER_OBJECT_COLLISION,
                    state->level,
                    state,
                    &input
                );
                if (status != NV14_STATUS_OK) return NV14_STATUS_HOOK_ERROR;
            }
        }
    }
    return nv14_finish_player_step_internal(
        state, input, hooks, result_out, NULL, NULL, NULL
    );
}

nv14_status nv14_state_step_with_hooks(
    nv14_state *state,
    nv14_input input,
    const nv14_step_hooks *hooks,
    nv14_step_result *result_out
)
{
    return nv14_state_step_internal(state, input, hooks, result_out);
}

nv14_status nv14_state_step(
    nv14_state *state,
    nv14_input input,
    nv14_step_result *result_out
)
{
    return nv14_state_step_internal(state, input, NULL, result_out);
}

int nv14_internal_state_can_step_alternate(const nv14_state *state)
{
    size_t module_index;
    if (state == NULL || state->phase != 0 || state->level_complete) return 0;
    for (module_index = 0;
         module_index < state->level->object_module_count;
         ++module_index) {
        const nv14_internal_object_module *module =
            state->level->object_modules[module_index];
        /* An alternate Player.Think could change a post-player callback's
           mutable world effects.  Fall back to two complete steps if a future
           module introduces one. */
        if (module->post_player != NULL) return 0;
    }
    return 1;
}

nv14_status nv14_internal_state_step_alternate(
    nv14_state *state,
    nv14_input primary_input,
    nv14_input alternate_input,
    nv14_player_snapshot *alternate_player_out,
    nv14_step_result *primary_result_out,
    nv14_step_result *alternate_result_out
)
{
    nv14_status status;
    uint64_t frame_before;
    uint64_t jumps_before;
    if (state == NULL || alternate_player_out == NULL ||
        primary_result_out == NULL || alternate_result_out == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    memset(primary_result_out, 0, sizeof(*primary_result_out));
    memset(alternate_result_out, 0, sizeof(*alternate_result_out));
    frame_before = state->frame;
    jumps_before = state->player.jump_events;
    if (!nv14_internal_state_can_step_alternate(state))
        return NV14_STATUS_INVALID_ARGUMENT;
    if ((state->level->capabilities & NV14_CAP_TILE_COLLISION) == 0) {
        nv14_fill_step_result(
            state,
            frame_before,
            jumps_before,
            0,
            NV14_STATUS_UNSUPPORTED_TILE,
            primary_result_out
        );
        return NV14_STATUS_UNSUPPORTED_TILE;
    }
    if (state->level->unsupported_object_mask != 0) {
        nv14_fill_step_result(
            state,
            frame_before,
            jumps_before,
            0,
            NV14_STATUS_UNSUPPORTED_OBJECTS,
            primary_result_out
        );
        return NV14_STATUS_UNSUPPORTED_OBJECTS;
    }
    status = nv14_state_begin_player_step_internal(state);
    if (status != NV14_STATUS_OK) return status;
    if (!state->player.dead) {
        status = nv14_state_collide_native_objects_internal(state);
        if (status != NV14_STATUS_OK) return status;
    }
    return nv14_finish_player_step_internal(
        state,
        primary_input,
        NULL,
        primary_result_out,
        &alternate_input,
        alternate_player_out,
        alternate_result_out
    );
}

nv14_status nv14_state_step_many(
    nv14_state *state,
    const nv14_input *inputs,
    size_t input_count,
    int stop_on_dead,
    int stop_on_complete,
    size_t *consumed_out,
    nv14_step_result *last_result_out
)
{
    size_t index;
    nv14_status status = NV14_STATUS_OK;
    nv14_step_result result;
    if (consumed_out != NULL) *consumed_out = 0;
    if (state == NULL || (input_count != 0 && inputs == NULL))
        return NV14_STATUS_INVALID_ARGUMENT;
    memset(&result, 0, sizeof(result));
    for (index = 0; index < input_count; ++index) {
        status = nv14_state_step_internal(
            state, inputs[index], NULL, &result
        );
        if (status != NV14_STATUS_OK) break;
        if ((stop_on_dead && result.dead) ||
            (stop_on_complete && result.level_complete)) {
            ++index;
            break;
        }
    }
    if (consumed_out != NULL) *consumed_out = index;
    if (last_result_out != NULL) *last_result_out = result;
    return status;
}

nv14_status nv14_state_get_player(
    const nv14_state *state,
    nv14_player_snapshot *player_out
)
{
    if (state == NULL || player_out == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    *player_out = state->player;
    return NV14_STATUS_OK;
}

nv14_status nv14_state_set_player(
    nv14_state *state,
    const nv14_player_snapshot *player
)
{
    if (state == NULL || player == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    state->player = *player;
    return NV14_STATUS_OK;
}

uint64_t nv14_state_frame(const nv14_state *state)
{
    return state != NULL ? state->frame : 0;
}

int nv14_state_level_complete(const nv14_state *state)
{
    return state != NULL && state->level_complete;
}

void nv14_state_set_level_complete(nv14_state *state, int complete)
{
    if (state != NULL) state->level_complete = complete != 0;
}

uint64_t nv14_state_gold_bonus_ticks(const nv14_state *state)
{
    return state != NULL ? state->gold_bonus_ticks : 0;
}

int64_t nv14_state_completed_exit_index(const nv14_state *state)
{
    return state != NULL ? state->completed_exit_index : -1;
}

size_t nv14_state_mask_word_count(const nv14_state *state, nv14_mask_kind kind)
{
    if (state == NULL) return 0;
    if (kind == NV14_MASK_COLLECTED_GOLD)
        return nv14_word_count(state->level->gold_count);
    if (kind == NV14_MASK_EXPLODED_MINE)
        return nv14_word_count(state->level->mine_count);
    if (kind == NV14_MASK_OPEN_EXIT)
        return nv14_word_count(state->level->exit_count);
    return 0;
}

nv14_status nv14_state_copy_mask(
    const nv14_state *state,
    nv14_mask_kind kind,
    uint64_t *words_out,
    size_t word_capacity
)
{
    const uint64_t *source;
    size_t words;
    if (state == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    words = nv14_state_mask_word_count(state, kind);
    if (words == 0) return NV14_STATUS_OK;
    if (words_out == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    if (word_capacity < words) return NV14_STATUS_BUFFER_TOO_SMALL;
    if (kind == NV14_MASK_COLLECTED_GOLD) source = state->collected_gold;
    else if (kind == NV14_MASK_EXPLODED_MINE) source = state->exploded_mine;
    else if (kind == NV14_MASK_OPEN_EXIT) source = state->open_exit;
    else return NV14_STATUS_INVALID_ARGUMENT;
    memcpy(words_out, source, words * sizeof(uint64_t));
    return NV14_STATUS_OK;
}

nv14_status nv14_state_set_edge_override(
    nv14_state *state,
    int tile_i,
    int tile_j,
    int side,
    int edge_value
)
{
    size_t index;
    uint64_t bit;
    if (state == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    if (tile_i < 0 || tile_i >= NV14_TILE_COLS ||
        tile_j < 0 || tile_j >= NV14_TILE_ROWS ||
        side < 0 || side > 3 || edge_value < 0 || edge_value > 2)
        return NV14_STATUS_OUT_OF_BOUNDS;
    index = ((size_t)tile_i * NV14_TILE_ROWS + (size_t)tile_j) * 4u +
        (size_t)side;
    bit = UINT64_C(1) << (index & 63u);
    if ((state->edge_override_active[index >> 6] & bit) == 0) {
        if (state->edge_override_count >= NV14_EDGE_OVERRIDE_SLOTS)
            return NV14_STATUS_OUT_OF_BOUNDS;
        state->edge_override_active[index >> 6] |= bit;
        ++state->edge_override_count;
    }
    state->edge_overrides[index] = (int8_t)edge_value;
    return NV14_STATUS_OK;
}

nv14_status nv14_state_clear_edge_override(
    nv14_state *state,
    int tile_i,
    int tile_j,
    int side
)
{
    size_t index;
    uint64_t bit;
    if (state == NULL) return NV14_STATUS_INVALID_ARGUMENT;
    if (tile_i < 0 || tile_i >= NV14_TILE_COLS ||
        tile_j < 0 || tile_j >= NV14_TILE_ROWS || side < 0 || side > 3)
        return NV14_STATUS_OUT_OF_BOUNDS;
    index = ((size_t)tile_i * NV14_TILE_ROWS + (size_t)tile_j) * 4u +
        (size_t)side;
    bit = UINT64_C(1) << (index & 63u);
    if ((state->edge_override_active[index >> 6] & bit) != 0) {
        if (state->edge_override_count == 0)
            return NV14_STATUS_INVALID_ARGUMENT;
        state->edge_override_active[index >> 6] &= ~bit;
        --state->edge_override_count;
    }
    state->edge_overrides[index] = -1;
    return NV14_STATUS_OK;
}

static void nv14_key_write_u16(unsigned char **cursor, uint16_t value)
{
    unsigned char *p = *cursor;
    p[0] = (unsigned char)(value & 0xffu);
    p[1] = (unsigned char)((value >> 8) & 0xffu);
    *cursor = p + 2;
}

static void nv14_key_write_u32(unsigned char **cursor, uint32_t value)
{
    unsigned char *p = *cursor;
    p[0] = (unsigned char)(value & 0xffu);
    p[1] = (unsigned char)((value >> 8) & 0xffu);
    p[2] = (unsigned char)((value >> 16) & 0xffu);
    p[3] = (unsigned char)((value >> 24) & 0xffu);
    *cursor = p + 4;
}

static void nv14_key_write_u64(unsigned char **cursor, uint64_t value)
{
    unsigned char *p = *cursor;
    int shift;
    for (shift = 0; shift < 64; shift += 8)
        *p++ = (unsigned char)((value >> shift) & UINT64_C(0xff));
    *cursor = p;
}

static void nv14_key_write_double(unsigned char **cursor, double value)
{
    uint64_t bits;
    if (value == 0.0) value = 0.0; /* canonicalise negative zero. */
    memcpy(&bits, &value, sizeof(bits));
    nv14_key_write_u64(cursor, bits);
}

static unsigned int nv14_key_trailing_zero_u64(uint64_t value)
{
#if defined(__GNUC__) || defined(__clang__)
    return (unsigned int)__builtin_ctzll((unsigned long long)value);
#else
    unsigned int count = 0;
    while ((value & UINT64_C(1)) == 0) {
        value >>= 1;
        ++count;
    }
    return count;
#endif
}

static int nv14_key_size_add(size_t *size, size_t addition)
{
    if (*size > SIZE_MAX - addition) return 0;
    *size += addition;
    return 1;
}

static int nv14_key_size_add_product(
    size_t *size,
    size_t count,
    size_t element_size
)
{
    if (element_size != 0 && count > SIZE_MAX / element_size) return 0;
    return nv14_key_size_add(size, count * element_size);
}

size_t nv14_state_key_size(const nv14_state *state, int precision)
{
    size_t object_count;
    size_t runtime_object_count;
    size_t size = 0;
    size_t module_index;
    if (state == NULL || precision >= 0 || state->phase != 0) return 0;
    object_count = state->level->native_object_count;
    runtime_object_count = state->level->mutable_runtime_count;
    if (object_count > (size_t)INT32_MAX ||
        state->update_count > object_count ||
        state->thinker_count > object_count ||
        state->edge_override_count > NV14_EDGE_OVERRIDE_SLOTS)
        return 0;

    /* magic/version + frame + player + flags/static state + edge count. */
    if (!nv14_key_size_add(
            &size,
            8u + 8u + 8u * 8u + 4u * 4u + 6u + 8u + 8u + 2u
        ) ||
        /* A valid linked grid is uniquely reconstructible from each object's
           next index and cell slot; heads and previous links are derived. */
        !nv14_key_size_add_product(&size, object_count, 4u + 2u) ||
        !nv14_key_size_add_product(
            &size,
            runtime_object_count,
            (NV14_OBJECT_RUNTIME_F64_SLOTS +
             NV14_OBJECT_RUNTIME_I64_SLOTS) * 8u
        ) ||
        /* think timer/rate plus the two scheduler counts. */
        !nv14_key_size_add(&size, 4u + 4u + 8u + 8u) ||
        !nv14_key_size_add_product(&size, state->update_count, 8u) ||
        !nv14_key_size_add_product(&size, state->thinker_count, 8u) ||
        !nv14_key_size_add_product(
            &size, nv14_word_count(state->level->gold_count), 8u
        ) ||
        !nv14_key_size_add_product(
            &size, nv14_word_count(state->level->mine_count), 8u
        ) ||
        !nv14_key_size_add_product(
            &size, nv14_word_count(state->level->exit_count), 8u
        ) ||
        /* Sorted sparse entries: uint16 index plus uint8 edge value. */
        !nv14_key_size_add_product(
            &size, (size_t)state->edge_override_count, 2u + 1u
        ))
        return 0;
    for (module_index = 0;
         module_index < state->level->object_module_count;
         ++module_index) {
        const nv14_internal_object_module *module =
            state->level->object_modules[module_index];
        if (module->extra_key_size != NULL &&
            !nv14_key_size_add(&size, module->extra_key_size(state)))
            return 0;
    }
    return size;
}

nv14_status nv14_state_write_key(
    const nv14_state *state,
    int precision,
    unsigned char *buffer,
    size_t buffer_size,
    size_t *written_out
)
{
    unsigned char *cursor;
    size_t required;
    size_t index;
    size_t slot;
    size_t words;
    size_t module_index;
    size_t edge_written = 0;
    const nv14_player_snapshot *p;
    if (written_out != NULL) *written_out = 0;
    if (state == NULL || buffer == NULL || precision >= 0)
        return NV14_STATUS_INVALID_ARGUMENT;
    required = nv14_state_key_size(state, precision);
    if (required == 0) return NV14_STATUS_INVALID_ARGUMENT;
    if (buffer_size < required) return NV14_STATUS_BUFFER_TOO_SMALL;
    cursor = buffer;
    memcpy(cursor, "NV14KEY4", 8);
    cursor += 8;
    nv14_key_write_u64(&cursor, state->frame);
    p = &state->player;
    nv14_key_write_double(&cursor, p->pos.x);
    nv14_key_write_double(&cursor, p->pos.y);
    nv14_key_write_double(&cursor, p->oldpos.x);
    nv14_key_write_double(&cursor, p->oldpos.y);
    nv14_key_write_double(&cursor, p->g);
    nv14_key_write_double(&cursor, p->d);
    nv14_key_write_double(&cursor, p->floor_n.x);
    nv14_key_write_double(&cursor, p->floor_n.y);
    nv14_key_write_u32(&cursor, (uint32_t)p->state);
    nv14_key_write_u32(&cursor, (uint32_t)p->jump_timer);
    nv14_key_write_u32(&cursor, (uint32_t)p->cell_i);
    nv14_key_write_u32(&cursor, (uint32_t)p->cell_j);
    *cursor++ = p->in_air;
    *cursor++ = p->near_wall;
    *cursor++ = p->previous_jump_held;
    *cursor++ = p->celeb_was_in_air;
    *cursor++ = p->dead;
    *cursor++ = state->level_complete;
    nv14_key_write_u64(&cursor, state->gold_bonus_ticks);
    nv14_key_write_u64(&cursor, (uint64_t)state->completed_exit_index);
    nv14_key_write_u16(&cursor, state->edge_override_count);
    for (index = 0; index < NV14_EDGE_OVERRIDE_WORDS; ++index) {
        uint64_t active = state->edge_override_active[index];
        while (active != 0) {
            unsigned int bit = nv14_key_trailing_zero_u64(active);
            size_t edge_index = index * 64u + bit;
            int edge_value;
            if (edge_index >= NV14_EDGE_OVERRIDE_SLOTS ||
                edge_written >= state->edge_override_count)
                return NV14_STATUS_INVALID_ARGUMENT;
            edge_value = state->edge_overrides[edge_index];
            if (edge_value < 0 || edge_value > NV14_EID_SOLID)
                return NV14_STATUS_INVALID_ARGUMENT;
            nv14_key_write_u16(&cursor, (uint16_t)edge_index);
            *cursor++ = (unsigned char)edge_value;
            ++edge_written;
            active &= active - UINT64_C(1);
        }
    }
    if (edge_written != state->edge_override_count)
        return NV14_STATUS_INVALID_ARGUMENT;
    for (index = 0; index < state->level->native_object_count; ++index) {
        int32_t next = state->object_next[index];
        int32_t cell_slot = state->object_cell_slot[index];
        if (next < -1 || (next >= 0 && (size_t)next >=
                state->level->native_object_count) ||
            cell_slot < -1 || cell_slot >= NV14_CELL_SLOTS)
            return NV14_STATUS_INVALID_ARGUMENT;
        nv14_key_write_u32(&cursor, (uint32_t)next);
        nv14_key_write_u16(&cursor, (uint16_t)cell_slot);
    }
    for (index = 0; index < state->level->mutable_runtime_count; ++index) {
        for (slot = 0; slot < NV14_OBJECT_RUNTIME_F64_SLOTS; ++slot)
            nv14_key_write_double(&cursor, state->object_runtime[index].f64[slot]);
        for (slot = 0; slot < NV14_OBJECT_RUNTIME_I64_SLOTS; ++slot)
            nv14_key_write_u64(
                &cursor, (uint64_t)state->object_runtime[index].i64[slot]
            );
    }
    nv14_key_write_u32(&cursor, state->think_timer);
    nv14_key_write_u32(&cursor, state->think_rate);
    nv14_key_write_u64(&cursor, (uint64_t)state->update_count);
    for (index = 0; index < state->update_count; ++index)
        nv14_key_write_u64(&cursor, (uint64_t)state->update_order[index]);
    nv14_key_write_u64(&cursor, (uint64_t)state->thinker_count);
    for (index = 0; index < state->thinker_count; ++index)
        nv14_key_write_u64(&cursor, (uint64_t)state->thinker_order[index]);
    words = nv14_word_count(state->level->gold_count);
    for (index = 0; index < words; ++index)
        nv14_key_write_u64(&cursor, state->collected_gold[index]);
    words = nv14_word_count(state->level->mine_count);
    for (index = 0; index < words; ++index)
        nv14_key_write_u64(&cursor, state->exploded_mine[index]);
    words = nv14_word_count(state->level->exit_count);
    for (index = 0; index < words; ++index)
        nv14_key_write_u64(&cursor, state->open_exit[index]);
    for (module_index = 0;
         module_index < state->level->object_module_count;
         ++module_index) {
        const nv14_internal_object_module *module =
            state->level->object_modules[module_index];
        if (module->write_extra_key != NULL) {
            size_t module_written = 0;
            size_t remaining = required - (size_t)(cursor - buffer);
            nv14_status status = module->write_extra_key(
                state, cursor, remaining, &module_written
            );
            if (status != NV14_STATUS_OK) return status;
            if (module->extra_key_size == NULL ||
                module_written != module->extra_key_size(state) ||
                module_written > remaining)
                return NV14_STATUS_INVALID_ARGUMENT;
            cursor += module_written;
        }
    }
    if ((size_t)(cursor - buffer) != required) return NV14_STATUS_INVALID_ARGUMENT;
    if (written_out != NULL) *written_out = required;
    return NV14_STATUS_OK;
}

const char *nv14_status_string(nv14_status status)
{
    switch (status) {
        case NV14_STATUS_OK: return "ok";
        case NV14_STATUS_INVALID_ARGUMENT: return "invalid argument";
        case NV14_STATUS_OUT_OF_MEMORY: return "out of memory";
        case NV14_STATUS_INVALID_LEVEL: return "invalid level";
        case NV14_STATUS_UNSUPPORTED_TILE: return "unsupported tile";
        case NV14_STATUS_UNSUPPORTED_OBJECTS: return "unsupported objects";
        case NV14_STATUS_OUT_OF_BOUNDS: return "out of bounds";
        case NV14_STATUS_BUFFER_TOO_SMALL: return "buffer too small";
        case NV14_STATUS_HOOK_ERROR: return "object hook error";
        case NV14_STATUS_PHASE_ERROR: return "invalid player-step phase";
        default: return "unknown native engine status";
    }
}

/* Sibling native object units include nv14_internal.h and use these wrappers;
   the public ABI remains opaque in nv14_core.h. */
size_t nv14_internal_word_count(size_t bits)
{
    return nv14_word_count(bits);
}

int nv14_internal_mask_test(const uint64_t *words, size_t bit)
{
    return nv14_mask_test(words, bit);
}

void nv14_internal_mask_set(uint64_t *words, size_t bit)
{
    nv14_mask_set(words, bit);
}

int nv14_internal_cell_slot(int i, int j)
{
    return nv14_cell_slot(i, j);
}

int nv14_internal_floor_index(double value, double divisor, int *out)
{
    return nv14_python_floor_index(value, divisor, out);
}

void nv14_internal_grid_add(nv14_state *state, size_t object_index, int slot)
{
    nv14_grid_add(state, object_index, slot);
}

void nv14_internal_grid_remove(nv14_state *state, size_t object_index)
{
    nv14_grid_remove(state, object_index);
}

void nv14_internal_player_report_object(
    nv14_player_snapshot *player,
    double px,
    double py,
    double nx,
    double ny
)
{
    nv14_player_report_object(player, px, py, nx, ny);
}

void nv14_internal_player_launch(nv14_player_snapshot *player, double x, double y)
{
    nv14_player_launch(player, x, y);
}

void nv14_internal_player_fall(nv14_player_snapshot *player)
{
    nv14_player_fall(player);
}

void nv14_internal_player_celebrate(nv14_player_snapshot *player)
{
    nv14_player_celebrate(player);
}

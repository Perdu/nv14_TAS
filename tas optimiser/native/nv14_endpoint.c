#include "nv14_endpoint.h"
#include "nv14_internal.h"
#include "nv14_objects_basic.h"

#include <float.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

static int satisfied(const nv14_state *s, const nv14_endpoint_atom *a, int exit_event)
{
    int locked = 0, trap = 0;
    switch (a->kind) {
    case 0: return a->index < s->level->gold_count &&
                   nv14_internal_mask_test(s->collected_gold, a->index);
    case 1: return a->index < s->level->exit_count &&
                   nv14_internal_mask_test(s->open_exit, a->index);
    case 2: case 3:
        if (a->index > UINT32_MAX) return 0;
        if (nv14_objects_basic_door_interactions(s, (uint32_t)a->index,
                                                &locked, &trap) != NV14_STATUS_OK)
            return 0;
        return a->kind == 2 ? locked : trap;
    case 4: return exit_event && s->level_complete && s->completed_exit_index >= 0 &&
                   (uint64_t)s->completed_exit_index == a->index;
    default: return 0;
    }
}

static int group_satisfied(const nv14_state *s, const nv14_endpoint_plan *p,
                           const nv14_endpoint_group *g)
{
    for (size_t i = 0; i < g->count; ++i)
        if (satisfied(s, &p->atoms[g->first + i], 0)) return 1;
    return 0;
}

static double outside(double value, double lo, double hi)
{
    return fmax(fmax(lo - value, value - hi), 0.0);
}

/* Python squares with pow(), and math.hypot may round differently from libc.
 * Preserve the expression order and flag numerically indistinguishable
 * rankings for the original Python reference scorer. The final public score
 * is always built by that scorer, even on the ordinary fast path. */
static double square(double x, int *overflow)
{
    double value = pow(x, 2.0);
    if (isfinite(x) && !isfinite(value)) *overflow = 1;
    return value;
}

typedef struct endpoint_rank {
    size_t violated, missing, pending;
    int exhausted, dead, events, finite, missing_jump;
    double penalty, frame;
    double values[4];
    double distances[8]; /* exact arguments to the metric's square/hypot calls */
} endpoint_rank;

static int discrete_compare(const endpoint_rank *a, const endpoint_rank *b)
{
#define CMP(field) if (a->field != b->field) return a->field < b->field ? -1 : 1
    CMP(exhausted); CMP(violated); CMP(missing); CMP(dead);
#undef CMP
    return 0;
}

static int identical_metric_inputs(const endpoint_rank *a, const endpoint_rank *b)
{
    /* All interaction bits are permanent. Equal missing/pending counts on a
     * single chronological trajectory imply the same remaining identities. */
    if (a->pending != b->pending || a->events != b->events) return 0;
    for (int i = 0; i < 8; ++i)
        if (a->distances[i] != b->distances[i]) return 0;
    /* A missing jump's geometry is fully described by distances[6:8]. Only
     * missing object interactions need the original player position as well. */
    if (a->missing > (size_t)a->missing_jump || (a->pending && !a->events))
        for (int i = 0; i < 2; ++i)
            if (a->values[i] != b->values[i]) return 0;
    return 1;
}

nv14_status nv14_endpoint_scan(
    const nv14_endpoint_plan *p, const nv14_state *prefix,
    const uint8_t *inputs, size_t input_count, nv14_endpoint_result *out)
{
    nv14_state *state = NULL, *best = NULL;
    uint8_t *previous = NULL, *events = NULL;
    endpoint_rank best_rank = {0};
    nv14_endpoint_jump jump = {-1, 0.0, 0.0};
    nv14_error error = {0};
    nv14_status status = NV14_STATUS_OK;
    int ambiguous = 0, overflow = 0;
    if (!p || !prefix || !out || !inputs || p->target_frame >= input_count ||
        prefix->frame > p->target_frame + 1 || (p->target_count && !out->events))
        return NV14_STATUS_INVALID_ARGUMENT;
    if (p->has_jump_region) jump = p->prefix_jump;
    out->jump = jump;
    out->state = NULL;
    out->eligible = out->needs_reference = 0;
    if (p->target_count) {
        previous = calloc(p->target_count, 1);
        events = calloc(p->target_count, 1);
        if (!previous || !events) { status = NV14_STATUS_OUT_OF_MEMORY; goto done; }
        memset(out->events, 0, p->target_count);
        for (size_t i = 0; i < p->target_count; ++i)
            previous[i] = (uint8_t)satisfied(prefix, &p->targets[i], 1);
    }
    state = nv14_state_clone(prefix, &error);
    if (!state) { status = error.code; goto done; }
    for (size_t frame = (size_t)state->frame; frame <= p->target_frame && !state->player.dead; ++frame) {
        uint8_t code = inputs[frame];
        nv14_input input = {code & 1, (code >> 1) & 1, (code >> 2) & 1,
                            (int8_t)((code & 16) ? -1 : ((code >> 3) & 1))};
        nv14_step_result step;
        status = nv14_state_step(state, input, &step);
        if (status != NV14_STATUS_OK) goto done;
        if (step.unsupported) { status = NV14_STATUS_UNSUPPORTED_OBJECTS; goto done; }
        /* Track before endpoint eligibility filtering, including fixed-frame goals. */
        if (p->has_jump_region && jump.frame < 0 && step.jumped &&
            frame >= p->jump_start && frame <= p->jump_end &&
            isfinite(step.jump_origin_x) && isfinite(step.jump_origin_y) &&
            step.jump_origin_x >= p->jump_region[0] && step.jump_origin_x <= p->jump_region[1] &&
            step.jump_origin_y >= p->jump_region[2] && step.jump_origin_y <= p->jump_region[3]) {
            jump.frame = (int64_t)frame;
            jump.x = step.jump_origin_x;
            jump.y = step.jump_origin_y;
        }
        if (!p->earliest) continue;
        endpoint_rank rank = {0};
        rank.dead = state->player.dead;
        rank.values[0] = state->player.pos.x;
        rank.values[1] = state->player.pos.y;
        rank.values[2] = state->player.pos.x - state->player.oldpos.x;
        rank.values[3] = state->player.pos.y - state->player.oldpos.y;
        rank.finite = isfinite(rank.values[0]) && isfinite(rank.values[1]) &&
                      isfinite(rank.values[2]) && isfinite(rank.values[3]);
        rank.frame = rank.finite ? (double)frame : INFINITY;
        double target_distance = INFINITY;
        for (size_t i = 0; i < p->target_count; ++i) {
            const nv14_endpoint_atom *a = &p->targets[i];
            int now = satisfied(state, a, 1);
            events[i] = (uint8_t)(now && !previous[i]);
            rank.events += events[i];
            previous[i] = (uint8_t)now;
            if (!state->level_complete && !now) {
                ++rank.pending;
                if (rank.finite)
                    target_distance = fmin(target_distance,
                        hypot(rank.values[0] - a->x, rank.values[1] - a->y));
            }
        }
        if (frame < p->arrival_start) continue;
        int missing_jump = p->has_jump_region && jump.frame < 0;
        rank.missing_jump = missing_jump;
        rank.exhausted = (p->target_count && !rank.events && !rank.pending) ||
                         (missing_jump && frame >= p->jump_end);
        rank.missing += missing_jump;
        if (!p->target_count || rank.events) target_distance = 0.0;
        double missing_distance = 0.0;
        for (size_t i = 0; i < p->required_count; ++i) {
            const nv14_endpoint_group *g = &p->required[i];
            if (group_satisfied(state, p, g)) continue;
            ++rank.missing;
            if (!rank.finite) continue;
            double distance = INFINITY;
            int positioned = 0;
            for (size_t j = 0; j < g->count; ++j) {
                const nv14_endpoint_atom *a = &p->atoms[g->first + j];
                if (a->has_position) {
                    positioned = 1;
                    distance = fmin(distance, hypot(rank.values[0] - a->x,
                                                    rank.values[1] - a->y));
                }
            }
            if (positioned) missing_distance += distance;
        }
        for (size_t i = 0; i < p->avoided_count; ++i)
            rank.violated += group_satisfied(state, p, &p->avoided[i]);
        double constraint = 0.0, region = 0.0;
        if (rank.finite) {
            for (int i = 0; i < 4; ++i) {
                rank.distances[i] = outside(rank.values[i], p->lower[i], p->upper[i]);
                constraint += square(rank.distances[i], &overflow);
            }
            if (p->has_region) {
                rank.distances[4] = outside(rank.values[0], p->region[0], p->region[1]);
                rank.distances[5] = outside(rank.values[1], p->region[2], p->region[3]);
                region = hypot(rank.distances[4], rank.distances[5]);
            }
            rank.penalty = constraint + square(region, &overflow) +
                           square(missing_distance, &overflow) + square(target_distance, &overflow);
            if (missing_jump) {
                rank.distances[6] = outside(rank.values[0], p->jump_region[0], p->jump_region[1]);
                rank.distances[7] = outside(rank.values[1], p->jump_region[2], p->jump_region[3]);
                rank.penalty += square(hypot(rank.distances[6], rank.distances[7]), &overflow);
            }
        } else rank.penalty = INFINITY;
        int feasible = rank.finite && !rank.dead && !rank.missing && !rank.violated &&
                       constraint == 0.0 && region == 0.0 &&
                       (!p->target_count || rank.events);
        int comparison = best ? discrete_compare(&rank, &best_rank) : -1;
        int better = !best || comparison < 0;
        if (best && comparison == 0) {
            better = rank.penalty < best_rank.penalty ||
                (rank.penalty == best_rank.penalty && rank.frame < best_rank.frame);
            double scale = fmax(fabs(rank.penalty), fabs(best_rank.penalty));
            double tolerance = 64.0 * (double)(p->required_count + 1) * DBL_EPSILON * scale;
            tolerance = fmax(tolerance, 64.0 * (DBL_MIN * DBL_EPSILON));
            int close = isfinite(scale) &&
                fabs(rank.penalty - best_rank.penalty) <= tolerance;
            if (close && !identical_metric_inputs(&rank, &best_rank)) ambiguous = 1;
            else if (better && !close) ambiguous = 0;
        } else if (better) ambiguous = 0;
        if (feasible || better) {
            if (!best) {
                best = nv14_state_clone(state, &error);
                if (!best) { status = error.code; goto done; }
            } else {
                status = nv14_state_copy_into(best, state, &error);
                if (status != NV14_STATUS_OK) goto done;
            }
            best_rank = rank;
            out->jump = jump;
            out->eligible = 1;
            if (p->target_count) memcpy(out->events, events, p->target_count);
        }
        if (feasible) { ambiguous = 0; break; }
    }
    out->terminal_frame = (int64_t)state->frame - 1;
    out->terminal_dead = state->player.dead;
    out->needs_reference = (uint8_t)(ambiguous || overflow);
    if (!best) { best = state; state = NULL; out->jump = jump; }
    out->state = best;
    best = NULL;
done:
    nv14_state_destroy(state);
    nv14_state_destroy(best);
    free(previous);
    free(events);
    return status;
}

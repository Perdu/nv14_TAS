/*
 * Ray-query subsystem from nv14_engine.py / n v1.4 ActionScript.
 *
 * Floating-point expression order is intentional.  Compile without fast-math
 * and with FP contraction disabled, just like nv14_core.c.
 */

#include "nv14_rays.h"

#include <math.h>
#include <stddef.h>

static void nv14_ray_hit_clear(nv14_ray_hit *out)
{
    out->hit = 0;
    out->point.x = 0.0;
    out->point.y = 0.0;
    out->distance = INFINITY;
}

static const nv14_tile *nv14_rays_tile_at(
    const nv14_level *level,
    int i,
    int j
)
{
    if (i < 0 || i >= NV14_TILE_COLS || j < 0 || j >= NV14_TILE_ROWS)
        return NULL;
    return &level->tiles[(size_t)i * NV14_TILE_ROWS + (size_t)j];
}

static int nv14_rays_edge_value(
    const nv14_state *state,
    const nv14_tile *tile,
    int side
)
{
    size_t index;
    int override_value;

    if (state == NULL || state->edge_override_count == 0)
        return tile->edges[side];
    index = ((size_t)tile->i * NV14_TILE_ROWS + (size_t)tile->j) * 4u +
        (size_t)side;
    override_value = state->edge_overrides[index];
    return override_value >= 0 ? override_value : tile->edges[side];
}

nv14_status nv14_rays_circle_first_hit(
    double px,
    double py,
    double dx,
    double dy,
    nv14_vec2 object_position,
    double radius,
    nv14_ray_hit *out
)
{
    double vx;
    double vy;
    double a;
    double b;
    double c;
    double disc;
    double root;
    double denom;
    double t1;
    double t2;
    double t;

    if (out == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    nv14_ray_hit_clear(out);

    vx = px - object_position.x;
    vy = py - object_position.y;
    a = dx * dx + dy * dy;
    b = 2.0 * (dx * vx + dy * vy);
    c = vx * vx + vy * vy - radius * radius;
    disc = b * b - 4.0 * a * c;
    if (disc < 0.0)
        return NV14_STATUS_OK;
    root = sqrt(disc);
    denom = 2.0 * a;
    t1 = (-b + root) / denom;
    t2 = (-b - root) / denom;
    if (t2 < 0.0) {
        if (t1 < 0.0)
            return NV14_STATUS_OK;
        t = t1;
    } else if (t1 < 0.0) {
        t = t2;
    } else {
        t = t2 < t1 ? t2 : t1;
    }
    out->hit = 1;
    out->point.x = px + t * dx;
    out->point.y = py + t * dy;
    out->distance = t;
    return NV14_STATUS_OK;
}

nv14_status nv14_rays_test_tile(
    double px,
    double py,
    double dx,
    double dy,
    const nv14_tile *tile,
    nv14_ray_hit *out
)
{
    double signx;
    double signy;
    double sx;
    double sy;
    double vx;
    double vy;
    double ox;
    double oy;
    double denom;
    double u;
    double cx;
    double cy;
    double a;
    double b;
    double radius;
    double c;
    double disc;
    double root;
    double denom2;
    double q1;
    double q2;
    double q;
    double yoff;
    double xoff;

    if (tile == NULL || out == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    nv14_ray_hit_clear(out);
    if (tile->tile_id <= NV14_TID_EMPTY || tile->ctype == NV14_CTYPE_FULL)
        return NV14_STATUS_OK;

    if (tile->ctype == NV14_CTYPE_45DEG) {
        signx = tile->signx;
        signy = tile->signy;
        if (0.0 <= signx * dx + signy * dy)
            return NV14_STATUS_OK;
        vx = signx * NV14_TILE_SCALE;
        vy = -signy * NV14_TILE_SCALE;
        ox = tile->x - px;
        oy = tile->y - py;
        denom = dx * vy - dy * vx;
        if (denom == 0.0)
            return NV14_STATUS_OK;
        u = (dy * ox - dx * oy) / denom;
        if (fabs(u) <= 1.0) {
            out->hit = 1;
            out->point.x = tile->x + u * vx;
            out->point.y = tile->y + u * vy;
        }
    } else if (tile->ctype == NV14_CTYPE_CONCAVE) {
        signx = tile->signx;
        signy = tile->signy;
        if (0.0 <= signx * dx + signy * dy)
            return NV14_STATUS_OK;
        sx = signx * NV14_TILE_SCALE;
        sy = -signy * NV14_TILE_SCALE;
        ox = tile->x - px;
        oy = tile->y - py;
        denom = dx * sy - dy * sx;
        if (denom == 0.0)
            return NV14_STATUS_OK;
        u = (dy * ox - dx * oy) / denom;
        if (fabs(u) > 1.0)
            return NV14_STATUS_OK;
        cx = -sx - ox;
        cy = sy - oy;
        a = dx * dx + dy * dy;
        b = 2.0 * (dx * cx + dy * cy);
        radius = NV14_TILE_SCALE * 2.0;
        c = cx * cx + cy * cy - radius * radius;
        disc = b * b - 4.0 * a * c;
        if (disc < 0.0)
            return NV14_STATUS_OK;
        root = sqrt(disc);
        denom2 = 2.0 * a;
        q1 = (-b + root) / denom2;
        q2 = (-b - root) / denom2;
        q = q2 < q1 ? q1 : q2;
        /* The source selects the farther quadratic root for a concave arc. */
        if (q2 < q1)
            q = q1;
        else
            q = q2;
        out->hit = 1;
        out->point.x = px + q * dx;
        out->point.y = py + q * dy;
    } else if (tile->ctype == NV14_CTYPE_CONVEX) {
        signx = tile->signx;
        signy = tile->signy;
        ox = px - (tile->x - signx * NV14_TILE_SCALE);
        oy = py - (tile->y - signy * NV14_TILE_SCALE);
        a = dx * dx + dy * dy;
        b = 2.0 * (dx * ox + dy * oy);
        radius = NV14_TILE_SCALE * 2.0;
        c = ox * ox + oy * oy - radius * radius;
        disc = b * b - 4.0 * a * c;
        if (disc < 0.0)
            return NV14_STATUS_OK;
        root = sqrt(disc);
        denom = 2.0 * a;
        q1 = (-b + root) / denom;
        q2 = (-b - root) / denom;
        q = q2 < q1 ? q2 : q1;
        out->hit = 1;
        out->point.x = px + q * dx;
        out->point.y = py + q * dy;
    } else if (tile->ctype == NV14_CTYPE_HALF) {
        signx = tile->signx;
        signy = tile->signy;
        ox = tile->x - px;
        oy = tile->y - py;
        if (0.0 <= ox * signx + oy * signy) {
            out->hit = 1;
            out->point.x = px;
            out->point.y = py;
        } else {
            if (0.0 <= signx * dx + signy * dy)
                return NV14_STATUS_OK;
            vx = signy * NV14_TILE_SCALE;
            vy = signx * NV14_TILE_SCALE;
            denom = dx * vy - dy * vx;
            if (denom == 0.0)
                return NV14_STATUS_OK;
            u = (dy * ox - dx * oy) / denom;
            if (fabs(u) <= 1.0) {
                out->hit = 1;
                out->point.x = tile->x + u * vx;
                out->point.y = tile->y + u * vy;
            }
        }
    } else if (tile->ctype == NV14_CTYPE_22DEGS) {
        sx = tile->sx;
        sy = tile->sy;
        signx = tile->signx;
        signy = tile->signy;
        ox = tile->x - signx * NV14_TILE_SCALE - px;
        oy = tile->y - py;
        if (0.0 <= ox * signx && 0.0 <= oy * signy) {
            out->hit = 1;
            out->point.x = px;
            out->point.y = py;
        } else {
            if (0.0 <= sx * dx + sy * dy)
                return NV14_STATUS_OK;
            ox += signx * NV14_TILE_SCALE;
            yoff = signy * 0.5 * NV14_TILE_SCALE;
            oy -= yoff;
            vx = -signy * NV14_TILE_SCALE;
            vy = 0.5 * signx * NV14_TILE_SCALE;
            denom = dx * vy - dy * vx;
            if (denom == 0.0)
                return NV14_STATUS_OK;
            u = (dy * ox - dx * oy) / denom;
            if (fabs(u) <= 1.0) {
                out->hit = 1;
                out->point.x = tile->x + u * vx;
                out->point.y = tile->y - yoff + u * vy;
            }
        }
    } else if (tile->ctype == NV14_CTYPE_22DEGB) {
        sx = tile->sx;
        sy = tile->sy;
        signx = tile->signx;
        signy = tile->signy;
        ox = tile->x - px;
        oy = tile->y - py;
        if (ox * signx <= 0.0 && 0.0 <= oy * signy) {
            out->hit = 1;
            out->point.x = px;
            out->point.y = py;
        } else {
            if (0.0 <= sx * dx + sy * dy)
                return NV14_STATUS_OK;
            yoff = signy * 0.5 * NV14_TILE_SCALE;
            oy += yoff;
            vx = -signy * NV14_TILE_SCALE;
            vy = 0.5 * signx * NV14_TILE_SCALE;
            denom = dx * vy - dy * vx;
            if (denom == 0.0)
                return NV14_STATUS_OK;
            u = (dy * ox - dx * oy) / denom;
            if (fabs(u) <= 1.0) {
                out->hit = 1;
                out->point.x = tile->x + u * vx;
                out->point.y = tile->y + yoff + u * vy;
            }
        }
    } else if (tile->ctype == NV14_CTYPE_67DEGS) {
        sx = tile->sx;
        sy = tile->sy;
        signx = tile->signx;
        signy = tile->signy;
        ox = tile->x - px;
        oy = tile->y - signy * NV14_TILE_SCALE - py;
        if (0.0 <= ox * signx && 0.0 <= oy * signy) {
            out->hit = 1;
            out->point.x = px;
            out->point.y = py;
        } else {
            if (0.0 <= sx * dx + sy * dy)
                return NV14_STATUS_OK;
            oy += signy * NV14_TILE_SCALE;
            xoff = signx * 0.5 * NV14_TILE_SCALE;
            ox -= xoff;
            vx = -0.5 * signy * NV14_TILE_SCALE;
            vy = signx * NV14_TILE_SCALE;
            denom = dx * vy - dy * vx;
            if (denom == 0.0)
                return NV14_STATUS_OK;
            u = (dy * ox - dx * oy) / denom;
            if (fabs(u) <= 1.0) {
                out->hit = 1;
                out->point.x = tile->x - xoff + u * vx;
                out->point.y = tile->y + u * vy;
            }
        }
    } else if (tile->ctype == NV14_CTYPE_67DEGB) {
        sx = tile->sx;
        sy = tile->sy;
        signx = tile->signx;
        signy = tile->signy;
        ox = tile->x - px;
        oy = tile->y - py;
        if (oy * signy <= 0.0 && 0.0 <= ox * signx) {
            out->hit = 1;
            out->point.x = px;
            out->point.y = py;
        } else {
            if (0.0 <= sx * dx + sy * dy)
                return NV14_STATUS_OK;
            xoff = signx * 0.5 * NV14_TILE_SCALE;
            ox += xoff;
            vx = -0.5 * signy * NV14_TILE_SCALE;
            vy = signx * NV14_TILE_SCALE;
            denom = dx * vy - dy * vx;
            if (denom == 0.0)
                return NV14_STATUS_OK;
            u = (dy * ox - dx * oy) / denom;
            if (fabs(u) <= 1.0) {
                out->hit = 1;
                out->point.x = tile->x + xoff + u * vx;
                out->point.y = tile->y + u * vy;
            }
        }
    }

    if (out->hit)
        out->distance =
            (out->point.x - px) * dx + (out->point.y - py) * dy;
    return NV14_STATUS_OK;
}

static nv14_status nv14_rays_collide_tiles_normalized(
    const nv14_level *level,
    const nv14_state *state,
    nv14_vec2 p0,
    double dx,
    double dy,
    int has_max_entry_distance,
    double max_entry_distance,
    nv14_ray_hit *out
)
{
    int i;
    int j;
    int step_x;
    int step_y;
    int side;
    int next_i;
    int next_j;
    int edge_value;
    double tmax_x;
    double tmax_y;
    double tdelta_x;
    double tdelta_y;
    double crossing_t;
    double crossing_x;
    double crossing_y;
    const nv14_tile *cell;
    const nv14_tile *next_cell;
    nv14_ray_hit shaped_hit;
    nv14_status status;

    nv14_ray_hit_clear(out);
    if (!nv14_internal_floor_index(p0.x, NV14_TILE_W, &i) ||
        !nv14_internal_floor_index(p0.y, NV14_TILE_H, &j))
        return NV14_STATUS_OUT_OF_BOUNDS;
    cell = nv14_rays_tile_at(level, i, j);
    if (cell == NULL)
        return NV14_STATUS_OUT_OF_BOUNDS;

    step_x = dx < 0.0 ? -1 : (0.0 < dx ? 1 : 0);
    step_y = dy < 0.0 ? -1 : (0.0 < dy ? 1 : 0);
    if (step_x < 0) {
        tmax_x = (cell->x - NV14_TILE_SCALE - p0.x) / dx;
        tdelta_x = 2.0 * NV14_TILE_SCALE / -dx;
    } else if (0 < step_x) {
        tmax_x = (cell->x + NV14_TILE_SCALE - p0.x) / dx;
        tdelta_x = 2.0 * NV14_TILE_SCALE / dx;
    } else {
        tmax_x = 100000000.0;
        tdelta_x = 0.0;
    }
    if (step_y < 0) {
        tmax_y = (cell->y - NV14_TILE_SCALE - p0.y) / dy;
        tdelta_y = 2.0 * NV14_TILE_SCALE / -dy;
    } else if (0 < step_y) {
        tmax_y = (cell->y + NV14_TILE_SCALE - p0.y) / dy;
        tdelta_y = 2.0 * NV14_TILE_SCALE / dy;
    } else {
        tmax_y = 100000000.0;
        tdelta_y = 0.0;
    }

    if (cell->tile_id > NV14_TID_EMPTY &&
        cell->ctype != NV14_CTYPE_FULL) {
        status = nv14_rays_test_tile(p0.x, p0.y, dx, dy, cell, out);
        if (status != NV14_STATUS_OK || out->hit)
            return status;
    }

    while (cell != NULL) {
        if (tmax_x < tmax_y) {
            side = step_x < 0 ? NV14_EDGE_L : NV14_EDGE_R;
            next_i = cell->i + step_x;
            next_j = cell->j;
            crossing_t = tmax_x;
            tmax_x += tdelta_x;
        } else {
            side = step_y < 0 ? NV14_EDGE_U : NV14_EDGE_D;
            next_i = cell->i;
            next_j = cell->j + step_y;
            crossing_t = tmax_y;
            tmax_y += tdelta_y;
        }

        if (has_max_entry_distance && max_entry_distance < crossing_t)
            return NV14_STATUS_OK;

        edge_value = nv14_rays_edge_value(state, cell, side);
        next_cell = nv14_rays_tile_at(level, next_i, next_j);
        if (0 < edge_value) {
            crossing_x = p0.x + crossing_t * dx;
            crossing_y = p0.y + crossing_t * dy;
            if (edge_value == NV14_EID_SOLID) {
                out->hit = 1;
                out->point.x = crossing_x;
                out->point.y = crossing_y;
                out->distance = crossing_t;
                return NV14_STATUS_OK;
            }
            if (next_cell != NULL &&
                next_cell->tile_id > NV14_TID_EMPTY &&
                next_cell->ctype != NV14_CTYPE_FULL) {
                status = nv14_rays_test_tile(
                    crossing_x,
                    crossing_y,
                    dx,
                    dy,
                    next_cell,
                    &shaped_hit
                );
                if (status != NV14_STATUS_OK)
                    return status;
                if (shaped_hit.hit) {
                    out->hit = 1;
                    out->point = shaped_hit.point;
                    out->distance =
                        (out->point.x - p0.x) * dx +
                        (out->point.y - p0.y) * dy;
                    return NV14_STATUS_OK;
                }
            }
        }
        cell = next_cell;
    }
    return NV14_STATUS_OK;
}

nv14_status nv14_rays_collide_tiles(
    const nv14_level *level,
    const nv14_state *state,
    nv14_vec2 p0,
    nv14_vec2 p1,
    int has_max_entry_distance,
    double max_entry_distance,
    nv14_ray_hit *out
)
{
    double vx;
    double vy;
    double length;
    double dx;
    double dy;

    if (level == NULL || out == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    if (state != NULL && state->level != level)
        return NV14_STATUS_INVALID_ARGUMENT;
    nv14_ray_hit_clear(out);
    vx = p1.x - p0.x;
    vy = p1.y - p0.y;
    length = sqrt(vx * vx + vy * vy);
    if (length == 0.0)
        return NV14_STATUS_OK;
    dx = vx / length;
    dy = vy / length;
    return nv14_rays_collide_tiles_normalized(
        level,
        state,
        p0,
        dx,
        dy,
        has_max_entry_distance,
        max_entry_distance,
        out
    );
}

nv14_status nv14_rays_query_circle(
    const nv14_level *level,
    const nv14_state *state,
    nv14_vec2 p0,
    nv14_vec2 p1,
    nv14_vec2 object_position,
    double radius,
    nv14_ray_query_result *out
)
{
    double vx;
    double vy;
    double length;
    double dx;
    double dy;
    nv14_ray_hit circle;
    nv14_ray_hit tile;
    nv14_status status;

    if (level == NULL || out == NULL)
        return NV14_STATUS_INVALID_ARGUMENT;
    if (state != NULL && state->level != level)
        return NV14_STATUS_INVALID_ARGUMENT;
    out->object_hit = 0;
    out->circle_hit = 0;
    out->tile_hit = 0;
    out->point.x = 0.0;
    out->point.y = 0.0;
    out->circle_distance = INFINITY;
    out->tile_distance = INFINITY;

    vx = p1.x - p0.x;
    vy = p1.y - p0.y;
    length = sqrt(vx * vx + vy * vy);
    if (length == 0.0)
        return NV14_STATUS_OK;
    dx = vx / length;
    dy = vy / length;

    status = nv14_rays_circle_first_hit(
        p0.x,
        p0.y,
        dx,
        dy,
        object_position,
        radius,
        &circle
    );
    if (status != NV14_STATUS_OK)
        return status;
    status = nv14_rays_collide_tiles_normalized(
        level,
        state,
        p0,
        dx,
        dy,
        circle.hit,
        circle.distance + NV14_RAY_TILE_BACKTRACK_MARGIN,
        &tile
    );
    if (status != NV14_STATUS_OK)
        return status;

    out->circle_hit = circle.hit;
    out->tile_hit = tile.hit;
    out->circle_distance = circle.distance;
    out->tile_distance = tile.distance;
    if (circle.hit && (!tile.hit || circle.distance <= tile.distance)) {
        out->object_hit = 1;
        out->point = circle.point;
    } else if (tile.hit) {
        out->point = tile.point;
    }
    return NV14_STATUS_OK;
}

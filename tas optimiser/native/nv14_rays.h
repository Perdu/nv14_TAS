#ifndef NV14_RAYS_H
#define NV14_RAYS_H

/*
 * Internal ray-query geometry for the n v1.4 native engine.
 *
 * This interface intentionally depends on nv14_internal.h and is not part of
 * the stable Cython-facing ABI.  Directions passed to the primitive helpers
 * are expected to be normalized, as they are in the ActionScript source.
 */

#include "nv14_internal.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NV14_RAY_TILE_BACKTRACK_MARGIN 64.0

typedef struct nv14_ray_hit {
    int hit;
    nv14_vec2 point;
    double distance;
} nv14_ray_hit;

typedef struct nv14_ray_query_result {
    /* True only when the circle is the first visible collision. */
    int object_hit;
    /* The unoccluded geometric circle test, retained for native callers. */
    int circle_hit;
    int tile_hit;
    /* Matches QueryRayObj: circle point, blocking tile point, or (0, 0). */
    nv14_vec2 point;
    double circle_distance;
    double tile_distance;
} nv14_ray_query_result;

/* Port of TestRay_Circle.  dx/dy must be a normalized, non-zero direction. */
nv14_status nv14_rays_circle_first_hit(
    double px,
    double py,
    double dx,
    double dy,
    nv14_vec2 object_position,
    double radius,
    nv14_ray_hit *out
);

/* Port of TestRayTile for one shaped tile. */
nv14_status nv14_rays_test_tile(
    double px,
    double py,
    double dx,
    double dy,
    const nv14_tile *tile,
    nv14_ray_hit *out
);

/*
 * Port of CollideRayvsTiles.  p1 selects the direction; like the source, the
 * traversal is an infinite ray rather than a segment ending at p1.  When
 * state is non-NULL, its dense edge overrides take precedence over base tile
 * edges.  A cutoff stops before entering a DDA cell whose entry distance is
 * greater than max_entry_distance; equality is deliberately still tested.
 */
nv14_status nv14_rays_collide_tiles(
    const nv14_level *level,
    const nv14_state *state,
    nv14_vec2 p0,
    nv14_vec2 p1,
    int has_max_entry_distance,
    double max_entry_distance,
    nv14_ray_hit *out
);

/*
 * Port of QueryRayObj for a circle.  Tile traversal uses the source-compatible
 * curved-tile backtrack allowance after a circle intersection is known.
 */
nv14_status nv14_rays_query_circle(
    const nv14_level *level,
    const nv14_state *state,
    nv14_vec2 p0,
    nv14_vec2 p1,
    nv14_vec2 object_position,
    double radius,
    nv14_ray_query_result *out
);

#ifdef __cplusplus
}
#endif

#endif /* NV14_RAYS_H */

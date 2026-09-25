#ifndef NV14_ENDPOINT_H
#define NV14_ENDPOINT_H

#include "nv14_core.h"

/* A compiled, immutable endpoint plan. Indices are static-state indices for
 * gold/exits and serialized load indices for doors; they are never bit counts. */
typedef struct nv14_endpoint_atom {
    size_t index;
    double x, y;
    uint8_t kind; /* gold, exit switch, locked door, trapdoor, exit door */
    uint8_t has_position;
} nv14_endpoint_atom;

typedef struct nv14_endpoint_group {
    size_t first, count;
} nv14_endpoint_group;

typedef struct nv14_endpoint_plan {
    size_t target_frame, arrival_start;
    uint8_t earliest, has_region;
    double lower[4], upper[4]; /* x, y, vx, vy; absent windows use infinities */
    double region[4];
    nv14_endpoint_atom *atoms;
    nv14_endpoint_group *required, *avoided;
    size_t required_count, avoided_count;
    nv14_endpoint_atom *targets;
    size_t target_count;
} nv14_endpoint_plan;

typedef struct nv14_endpoint_result {
    nv14_state *state; /* owned selected state; caller destroys it */
    uint8_t *events;   /* caller allocates target_count bytes */
    int64_t terminal_frame;
    uint8_t terminal_dead, eligible, needs_reference;
} nv14_endpoint_result;

/* Packed inputs use PopulationCandidate.input_key's lossless five-bit format.
 * No Python objects, snapshots, dictionaries or state keys in the tick loop. */
nv14_status nv14_endpoint_scan(
    const nv14_endpoint_plan *plan, const nv14_state *prefix,
    const uint8_t *inputs, size_t input_count, nv14_endpoint_result *out
);

#endif

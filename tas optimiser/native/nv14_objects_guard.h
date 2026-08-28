#ifndef NV14_OBJECTS_GUARD_H
#define NV14_OBJECTS_GUARD_H

#include "nv14_internal.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Idempotent when this exact module has already been registered. */
nv14_status nv14_objects_guard_register(void);

#ifdef __cplusplus
}
#endif

#endif /* NV14_OBJECTS_GUARD_H */

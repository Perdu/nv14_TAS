/* Optional, rendering-only coverage rasterisation. No engine dependency.
 *
 * Keep binary64 expression order identical to nv14_vector's Python fallback.
 * Both masks are sampled at pixel centres. Stroke capsules use a strict
 * distance comparison; fills use the even-odd rule, including nested holes.
 * All input objects are copied before releasing the GIL for pixel work.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define SAMPLES 4

/* CPython float **2 calls libm pow, which can round one ULP differently
 * from x*x. A volatile function pointer prevents constant-exponent compiler
 * substitution, preserving the strict boundary comparison in the fallback. */
static double (*volatile python_power)(double, double) = pow;

typedef struct { double x, y; } Point;
typedef struct { Point *points; Py_ssize_t count; } Contour;
typedef struct {
    Contour *contours;
    Py_ssize_t count;
    Py_ssize_t points;
} Geometry;

static void geometry_free(Geometry *g)
{
    Py_ssize_t i;
    for (i = 0; i < g->count; ++i) PyMem_Free(g->contours[i].points);
    PyMem_Free(g->contours);
    memset(g, 0, sizeof(*g));
}

static int geometry_read(PyObject *object, Geometry *g)
{
    PyObject *outer = PySequence_Fast(object, "contours must be a sequence");
    Py_ssize_t i;
    memset(g, 0, sizeof(*g));
    if (!outer) return 0;
    g->count = PySequence_Fast_GET_SIZE(outer);
    if ((size_t)g->count > SIZE_MAX / sizeof(Contour)) {
        Py_DECREF(outer);
        PyErr_NoMemory();
        return 0;
    }
    g->contours = PyMem_Calloc((size_t)g->count, sizeof(Contour));
    if (g->count && !g->contours) {
        g->count = 0;
        Py_DECREF(outer);
        PyErr_NoMemory();
        return 0;
    }
    for (i = 0; i < g->count; ++i) {
        PyObject *row = PySequence_Fast(PySequence_Fast_GET_ITEM(outer, i),
                                        "a contour must be a sequence");
        Py_ssize_t j, count;
        Point *points;
        if (!row) goto error;
        count = PySequence_Fast_GET_SIZE(row);
        if ((size_t)count > SIZE_MAX / sizeof(Point) ||
            count > PY_SSIZE_T_MAX - g->points) {
            Py_DECREF(row);
            PyErr_NoMemory();
            goto error;
        }
        points = PyMem_Malloc((size_t)count * sizeof(Point));
        if (count && !points) {
            Py_DECREF(row);
            PyErr_NoMemory();
            goto error;
        }
        g->contours[i].points = points;
        g->contours[i].count = count;
        g->points += count;
        for (j = 0; j < count; ++j) {
            PyObject *pair = PySequence_Fast(PySequence_Fast_GET_ITEM(row, j),
                                            "points must be pairs");
            if (!pair) { Py_DECREF(row); goto error; }
            if (PySequence_Fast_GET_SIZE(pair) != 2) {
                Py_DECREF(pair);
                Py_DECREF(row);
                PyErr_SetString(PyExc_ValueError, "points must contain two coordinates");
                goto error;
            }
            points[j].x = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(pair, 0));
            points[j].y = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(pair, 1));
            Py_DECREF(pair);
            if (PyErr_Occurred()) { Py_DECREF(row); goto error; }
            if (!isfinite(points[j].x) || !isfinite(points[j].y)) {
                Py_DECREF(row);
                PyErr_SetString(PyExc_ValueError, "vector coordinates must be finite");
                goto error;
            }
        }
        Py_DECREF(row);
    }
    Py_DECREF(outer);
    return 1;
error:
    Py_DECREF(outer);
    geometry_free(g);
    return 0;
}

static PyObject *mask_new(Py_ssize_t width, Py_ssize_t height)
{
    PyObject *result;
    if (width < 0 || height < 0 || (height && width > PY_SSIZE_T_MAX / height)) {
        PyErr_SetString(PyExc_ValueError, "invalid mask size");
        return NULL;
    }
    result = PyBytes_FromStringAndSize(NULL, width * height);
    if (result) memset(PyBytes_AS_STRING(result), 0, (size_t)(width * height));
    return result;
}

/* Clamp before converting to an integer, including extreme clipped artwork. */
static Py_ssize_t clipped_ceil(double coordinate, Py_ssize_t limit)
{
    if (coordinate <= 0.) return 0;
    if (coordinate >= (double)limit) return limit;
    return (Py_ssize_t)ceil(coordinate);
}

typedef struct { double x, y, slope; Py_ssize_t first, end; } Edge;

static int compare_double(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

static PyObject *fill_mask(PyObject *self, PyObject *args)
{
    Py_ssize_t width, height, i, j, edge_count = 0;
    PyObject *contours, *result;
    Geometry g;
    Edge *edges;
    double *intersections;
    unsigned char *pixels;
    (void)self;
    if (!PyArg_ParseTuple(args, "nnO:fill_mask", &width, &height, &contours)) return NULL;
    result = mask_new(width, height);
    if (!result) return NULL;
    if (!geometry_read(contours, &g)) { Py_DECREF(result); return NULL; }
    if ((size_t)g.points > SIZE_MAX / sizeof(Edge)) {
        geometry_free(&g); Py_DECREF(result); return PyErr_NoMemory();
    }
    edges = PyMem_Malloc((size_t)g.points * sizeof(Edge));
    intersections = PyMem_Malloc((size_t)g.points * sizeof(double));
    if (g.points && (!edges || !intersections)) {
        PyMem_Free(edges); PyMem_Free(intersections);
        geometry_free(&g); Py_DECREF(result); return PyErr_NoMemory();
    }
    for (i = 0; i < g.count; ++i) {
        Contour *c = &g.contours[i];
        if (c->count < 3) continue;
        for (j = 0; j < c->count; ++j) {
            Point p0 = c->points[j], p1 = c->points[(j + 1) % c->count];
            Edge e;
            if (p0.y == p1.y) continue;
            if (p1.y < p0.y) { Point swap = p0; p0 = p1; p1 = swap; }
            e.x = p0.x; e.y = p0.y;
            e.slope = (p1.x - p0.x) / (p1.y - p0.y);
            e.first = clipped_ceil(p0.y - .5, height);
            e.end = clipped_ceil(p1.y - .5, height);
            edges[edge_count++] = e;
        }
    }
    pixels = (unsigned char *)PyBytes_AS_STRING(result);
    Py_BEGIN_ALLOW_THREADS
    for (i = 0; i < height; ++i) {
        Py_ssize_t count = 0;
        for (j = 0; j < edge_count; ++j) {
            Edge *e = &edges[j];
            if (i >= e->first && i < e->end)
                intersections[count++] = e->x + ((double)i + .5 - e->y) * e->slope;
        }
        if (count < 2) continue;
        qsort(intersections, (size_t)count, sizeof(double), compare_double);
        for (j = 0; j + 1 < count; j += 2) {
            Py_ssize_t start = clipped_ceil(intersections[j] - .5, width);
            Py_ssize_t end = clipped_ceil(intersections[j + 1] - .5, width);
            if (start < end) memset(pixels + i * width + start, 255, (size_t)(end - start));
        }
    }
    Py_END_ALLOW_THREADS
    PyMem_Free(edges); PyMem_Free(intersections); geometry_free(&g);
    return result;
}

static int grid_fit(Geometry *g)
{
    Py_ssize_t i, j;
    for (i = 0; i < g->count; ++i) {
        Contour *c = &g->contours[i];
        Point *original;
        if (c->count < 2) continue;
        original = PyMem_Malloc((size_t)c->count * sizeof(Point));
        if (!original) { PyErr_NoMemory(); return 0; }
        memcpy(original, c->points, (size_t)c->count * sizeof(Point));
        for (j = 0; j + 1 < c->count; ++j) {
            if (fabs(original[j].x - original[j+1].x) < 1e-6)
                c->points[j].x = c->points[j+1].x =
                    (floor(original[j].x / SAMPLES + .5) + .5) * SAMPLES;
            if (fabs(original[j].y - original[j+1].y) < 1e-6)
                c->points[j].y = c->points[j+1].y =
                    (floor(original[j].y / SAMPLES + .5) + .5) * SAMPLES;
        }
        if (original[0].x == original[c->count-1].x &&
            original[0].y == original[c->count-1].y) {
            if (c->points[0].x != original[0].x)
                c->points[c->count-1].x = c->points[0].x;
            else c->points[0].x = c->points[c->count-1].x;
            if (c->points[0].y != original[0].y)
                c->points[c->count-1].y = c->points[0].y;
            else c->points[0].y = c->points[c->count-1].y;
        }
        PyMem_Free(original);
    }
    return 1;
}

static PyObject *stroke_mask(PyObject *self, PyObject *args)
{
    Py_ssize_t width, height, i, j;
    double stroke_width, radius, radius2;
    int fit = 1;
    PyObject *contours, *result;
    Geometry g;
    unsigned char *pixels;
    (void)self;
    if (!PyArg_ParseTuple(args, "nnOd|p:stroke_mask", &width, &height, &contours,
                         &stroke_width, &fit)) return NULL;
    if (!isfinite(stroke_width) || stroke_width < 0.) {
        PyErr_SetString(PyExc_ValueError, "stroke width must be finite and non-negative");
        return NULL;
    }
    result = mask_new(width, height);
    if (!result) return NULL;
    if (!geometry_read(contours, &g)) { Py_DECREF(result); return NULL; }
    if (fit && stroke_width == SAMPLES && !grid_fit(&g)) {
        geometry_free(&g); Py_DECREF(result); return NULL;
    }
    radius = stroke_width / 2.; radius2 = radius * radius;
    pixels = (unsigned char *)PyBytes_AS_STRING(result);
    Py_BEGIN_ALLOW_THREADS
    for (i = 0; i < g.count; ++i) {
        Contour *c = &g.contours[i];
        for (j = 0; j + 1 < c->count; ++j) {
            double x0 = c->points[j].x, y0 = c->points[j].y;
            double x1 = c->points[j+1].x, y1 = c->points[j+1].y;
            double dx = x1 - x0, dy = y1 - y0, length2 = dx*dx + dy*dy;
            Py_ssize_t xmin = clipped_ceil(fmin(x0, x1) - radius - .5, width);
            Py_ssize_t xmax = clipped_ceil(fmax(x0, x1) + radius - .5, width);
            Py_ssize_t ymin = clipped_ceil(fmin(y0, y1) - radius - .5, height);
            Py_ssize_t ymax = clipped_ceil(fmax(y0, y1) + radius - .5, height);
            Py_ssize_t x, y;
            for (y = ymin; y < ymax; ++y) {
                double py = (double)y + .5 - y0;
                Py_ssize_t row = y * width;
                for (x = xmin; x < xmax; ++x) {
                    double px, t, ex, ey;
                    if (pixels[row + x]) continue;
                    px = (double)x + .5 - x0;
                    t = length2 ? (px*dx + py*dy) / length2 : 0.;
                    if (t > 1.) t = 1.;
                    if (t < 0.) t = 0.;
                    ex = px - t*dx; ey = py - t*dy;
                    if (python_power(ex, 2.) + python_power(ey, 2.) < radius2)
                        pixels[row + x] = 255;
                }
            }
        }
    }
    Py_END_ALLOW_THREADS
    geometry_free(&g);
    return result;
}

/* A compiled artwork contains only immutable geometry. Its supersample buffer
 * is reused between poses; a concurrent call uses its own temporary buffer. */
typedef struct { char kind; double values[4]; } Command;
typedef struct {
    Command *commands;
    Py_ssize_t count;
    int fill, stroke, curved;
    double stroke_width;
} CompiledPath;
typedef struct {
    CompiledPath *paths;
    Py_ssize_t count;
    unsigned char *samples;
    Py_ssize_t sample_capacity;
    int busy;
} CompiledArt;
#define ART_CAPSULE "nv14.compiled_opaque_art.v1"
#define MAX_RETAINED_SAMPLES (4 * 1024 * 1024)
#define TOTAL_RETAINED_SAMPLES (16 * 1024 * 1024)
static Py_ssize_t retained_sample_bytes = 0;

static void compiled_art_free(CompiledArt *art)
{
    Py_ssize_t i;
    for (i = 0; i < art->count; ++i) PyMem_Free(art->paths[i].commands);
    PyMem_Free(art->paths);
    retained_sample_bytes -= art->sample_capacity;
    PyMem_Free(art->samples);
    PyMem_Free(art);
}

static void compiled_art_destructor(PyObject *capsule)
{
    CompiledArt *art = PyCapsule_GetPointer(capsule, ART_CAPSULE);
    if (art) compiled_art_free(art);
}

static int opaque_color(PyObject *path, const char *name, int *present)
{
    PyObject *color = PyDict_GetItemString(path, name), *alpha;
    double value;
    *present = color && color != Py_None;
    if (!*present) return 1;
    alpha = PySequence_GetItem(color, 3);
    if (!alpha) return 0;
    value = PyFloat_AsDouble(alpha);
    Py_DECREF(alpha);
    if (PyErr_Occurred()) return 0;
    if (value != 255) {
        PyErr_SetString(PyExc_ValueError, "compiled artwork must be opaque");
        return 0;
    }
    return 1;
}

static PyObject *compile_art(PyObject *self, PyObject *paths)
{
    PyObject *sequence = PySequence_Fast(paths, "paths must be a sequence");
    CompiledArt *art;
    Py_ssize_t i;
    (void)self;
    if (!sequence) return NULL;
    art = PyMem_Calloc(1, sizeof(*art));
    if (!art) { Py_DECREF(sequence); return PyErr_NoMemory(); }
    art->count = PySequence_Fast_GET_SIZE(sequence);
    art->paths = PyMem_Calloc((size_t)art->count, sizeof(*art->paths));
    if (art->count && !art->paths) {
        art->count = 0; PyErr_NoMemory(); goto error;
    }
    for (i = 0; i < art->count; ++i) {
        PyObject *path = PySequence_Fast_GET_ITEM(sequence, i), *commands, *value;
        CompiledPath *out = &art->paths[i];
        Py_ssize_t j;
        if (!PyDict_Check(path)) {
            PyErr_SetString(PyExc_TypeError, "paths must contain dictionaries"); goto error;
        }
        if (!opaque_color(path, "fill", &out->fill) ||
            !opaque_color(path, "stroke", &out->stroke)) goto error;
        value = PyDict_GetItemString(path, "stroke_width");
        if (out->stroke) {
            if (!value) { PyErr_SetString(PyExc_KeyError, "stroke_width"); goto error; }
            out->stroke_width = PyFloat_AsDouble(value);
            if (PyErr_Occurred()) goto error;
            if (!isfinite(out->stroke_width)) {
                PyErr_SetString(PyExc_ValueError, "stroke width must be finite"); goto error;
            }
        }
        value = PyDict_GetItemString(path, "commands");
        if (!value) { PyErr_SetString(PyExc_KeyError, "commands"); goto error; }
        commands = PySequence_Fast(value, "commands must be a sequence");
        if (!commands) goto error;
        out->count = PySequence_Fast_GET_SIZE(commands);
        out->commands = PyMem_Calloc((size_t)out->count, sizeof(Command));
        if (out->count && !out->commands) {
            Py_DECREF(commands); PyErr_NoMemory(); goto error;
        }
        for (j = 0; j < out->count; ++j) {
            PyObject *cmd = PySequence_Fast(PySequence_Fast_GET_ITEM(commands, j),
                                           "commands must be sequences");
            const char *name;
            Py_ssize_t k, coordinates;
            Command *target = &out->commands[j];
            if (!cmd) { Py_DECREF(commands); goto error; }
            if (PySequence_Fast_GET_SIZE(cmd) < 1) {
                PyErr_SetString(PyExc_ValueError, "empty vector command");
                Py_DECREF(cmd); Py_DECREF(commands); goto error;
            }
            name = PyUnicode_AsUTF8(PySequence_Fast_GET_ITEM(cmd, 0));
            if (!name) { Py_DECREF(cmd); Py_DECREF(commands); goto error; }
            target->kind = name[0];
            if (!name[0] || name[1] || !strchr("MLQZ", name[0])) {
                PyErr_Format(PyExc_ValueError, "Unsupported vector command: %s", name);
                Py_DECREF(cmd); Py_DECREF(commands); goto error;
            }
            coordinates = target->kind == 'Q' ? 4 : target->kind == 'Z' ? 0 : 2;
            if (PySequence_Fast_GET_SIZE(cmd) < coordinates + 1) {
                PyErr_SetString(PyExc_ValueError, "incomplete vector command");
                Py_DECREF(cmd); Py_DECREF(commands); goto error;
            }
            for (k = 0; k < coordinates; ++k) {
                target->values[k] = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(cmd, k+1));
                if (PyErr_Occurred() || !isfinite(target->values[k])) {
                    if (!PyErr_Occurred())
                        PyErr_SetString(PyExc_ValueError, "vector coordinates must be finite");
                    Py_DECREF(cmd); Py_DECREF(commands); goto error;
                }
            }
            out->curved |= target->kind == 'Q';
            Py_DECREF(cmd);
        }
        Py_DECREF(commands);
    }
    Py_DECREF(sequence);
    {
        PyObject *capsule = PyCapsule_New(art, ART_CAPSULE, compiled_art_destructor);
        if (!capsule) compiled_art_free(art);
        return capsule;
    }
error:
    Py_DECREF(sequence);
    compiled_art_free(art);
    return NULL;
}

typedef struct {
    Point *points;
    Py_ssize_t count, capacity;
} PointBuilder;

static int append_point(PointBuilder *builder, Point point)
{
    if (builder->count == builder->capacity) {
        Py_ssize_t capacity = builder->capacity ? builder->capacity * 2 : 32;
        Point *points;
        if (capacity < builder->capacity || (size_t)capacity > SIZE_MAX/sizeof(Point)) {
            PyErr_NoMemory(); return 0;
        }
        points = PyMem_Realloc(builder->points, (size_t)capacity * sizeof(Point));
        if (!points) { PyErr_NoMemory(); return 0; }
        builder->points = points;
        builder->capacity = capacity;
    }
    builder->points[builder->count++] = point;
    return 1;
}

static Point transformed_point(const double *values, const double *m,
                               const double *phase, const double *origin)
{
    Point result;
    /* Keep both additions distinct: (a*x+b*y+phase)-origin is observably
     * different from a*x+b*y+(phase-origin) on strict capsule boundaries. */
    result.x = (m[0]*values[0] + m[1]*values[1] + phase[0] - origin[0]) * SAMPLES;
    result.y = (m[2]*values[0] + m[3]*values[1] + phase[1] - origin[1]) * SAMPLES;
    return result;
}

static int append_quadratic(PointBuilder *out, Point start, Point control,
                            Point end, int depth)
{
    double dx = start.x - 2*control.x + end.x;
    double dy = start.y - 2*control.y + end.y;
    double error = hypot(dx, dy) / 4;
    Point a, b, mid;
    /* CPython's compensated hypot may differ from platform libm by an ULP.
     * Only a subdivision decision right at the threshold can observe that
     * difference; ask the running interpreter for its exact result there. */
    if (fabs(error - .125) <= 1e-12) {
        PyObject *module = PyImport_ImportModule("math"), *value;
        if (!module) return 0;
        value = PyObject_CallMethod(module, "hypot", "dd", dx, dy);
        Py_DECREF(module);
        if (!value) return 0;
        error = PyFloat_AsDouble(value) / 4;
        Py_DECREF(value);
        if (PyErr_Occurred()) return 0;
    }
    if (error <= .125 || depth == 16) return append_point(out, end);
    a.x = (start.x + control.x)/2; a.y = (start.y + control.y)/2;
    b.x = (control.x + end.x)/2; b.y = (control.y + end.y)/2;
    mid.x = (a.x+b.x)/2; mid.y = (a.y+b.y)/2;
    return append_quadratic(out, start, a, mid, depth+1) &&
           append_quadratic(out, mid, b, end, depth+1);
}

static int finish_contour(Geometry *geometry, PointBuilder *builder)
{
    if (!builder->count) return 1;
    geometry->contours[geometry->count].points = builder->points;
    geometry->contours[geometry->count].count = builder->count;
    geometry->points += builder->count;
    geometry->count++;
    memset(builder, 0, sizeof(*builder));
    return 1;
}

static int transform_path(const CompiledPath *path, const double *m,
                          const double *phase, const double *origin, Geometry *g)
{
    PointBuilder builder = {0};
    Py_ssize_t i;
    memset(g, 0, sizeof(*g));
    g->contours = PyMem_Calloc((size_t)path->count + 1, sizeof(Contour));
    if (!g->contours) { PyErr_NoMemory(); return 0; }
    for (i = 0; i < path->count; ++i) {
        const Command *command = &path->commands[i];
        Point point;
        if (command->kind == 'Z') {
            if (builder.count && (builder.points[0].x != builder.points[builder.count-1].x ||
                                  builder.points[0].y != builder.points[builder.count-1].y))
                if (!append_point(&builder, builder.points[0])) goto error;
            continue;
        }
        point = transformed_point(command->values, m, phase, origin);
        if (!isfinite(point.x) || !isfinite(point.y)) {
            PyErr_SetString(PyExc_ValueError, "vector coordinates must be finite"); goto error;
        }
        if (command->kind == 'M') finish_contour(g, &builder);
        if (command->kind == 'Q') {
            Point end = transformed_point(command->values+2, m, phase, origin);
            if (!builder.count) {
                PyErr_SetString(PyExc_IndexError, "quadratic command requires a starting point"); goto error;
            }
            if (!isfinite(end.x) || !isfinite(end.y)) {
                PyErr_SetString(PyExc_ValueError, "vector coordinates must be finite"); goto error;
            }
            if (!append_quadratic(&builder, builder.points[builder.count-1], point, end, 0)) goto error;
        } else if (!append_point(&builder, point)) goto error;
    }
    finish_contour(g, &builder);
    return 1;
error:
    PyMem_Free(builder.points);
    geometry_free(g);
    return 0;
}

static int union_fill(Py_ssize_t width, Py_ssize_t height, const Geometry *g,
                      unsigned char *pixels)
{
    Py_ssize_t i, j, edge_count = 0;
    Edge *edges = PyMem_Malloc((size_t)g->points * sizeof(Edge));
    double *intersections = PyMem_Malloc((size_t)g->points * sizeof(double));
    if (g->points && (!edges || !intersections)) {
        PyMem_Free(edges); PyMem_Free(intersections); PyErr_NoMemory(); return 0;
    }
    for (i = 0; i < g->count; ++i) {
        const Contour *c = &g->contours[i];
        if (c->count < 3) continue;
        for (j = 0; j < c->count; ++j) {
            Point p0 = c->points[j], p1 = c->points[(j+1) % c->count];
            Edge *edge;
            if (p0.y == p1.y) continue;
            if (p1.y < p0.y) { Point swap = p0; p0 = p1; p1 = swap; }
            edge = &edges[edge_count++];
            edge->x = p0.x; edge->y = p0.y;
            edge->slope = (p1.x - p0.x) / (p1.y - p0.y);
            edge->first = clipped_ceil(p0.y - .5, height);
            edge->end = clipped_ceil(p1.y - .5, height);
        }
    }
    Py_BEGIN_ALLOW_THREADS
    for (i = 0; i < height; ++i) {
        Py_ssize_t count = 0;
        for (j = 0; j < edge_count; ++j) {
            Edge *edge = &edges[j];
            if (i >= edge->first && i < edge->end)
                intersections[count++] = edge->x + ((double)i + .5 - edge->y) * edge->slope;
        }
        if (count < 2) continue;
        qsort(intersections, (size_t)count, sizeof(double), compare_double);
        for (j = 0; j+1 < count; j += 2) {
            Py_ssize_t start = clipped_ceil(intersections[j] - .5, width);
            Py_ssize_t end = clipped_ceil(intersections[j+1] - .5, width);
            if (start < end) memset(pixels + i*width + start, 255, (size_t)(end-start));
        }
    }
    Py_END_ALLOW_THREADS
    PyMem_Free(edges); PyMem_Free(intersections);
    return 1;
}

static void union_stroke(Py_ssize_t width, Py_ssize_t height, const Geometry *g,
                         double stroke_width, unsigned char *pixels)
{
    Py_ssize_t i, j;
    double radius = stroke_width / 2., radius2 = radius * radius;
    Py_BEGIN_ALLOW_THREADS
    for (i = 0; i < g->count; ++i) {
        const Contour *c = &g->contours[i];
        for (j = 0; j+1 < c->count; ++j) {
            double x0 = c->points[j].x, y0 = c->points[j].y;
            double x1 = c->points[j+1].x, y1 = c->points[j+1].y;
            double dx = x1-x0, dy = y1-y0, length2 = dx*dx + dy*dy;
            Py_ssize_t xmin = clipped_ceil(fmin(x0, x1) - radius - .5, width);
            Py_ssize_t xmax = clipped_ceil(fmax(x0, x1) + radius - .5, width);
            Py_ssize_t ymin = clipped_ceil(fmin(y0, y1) - radius - .5, height);
            Py_ssize_t ymax = clipped_ceil(fmax(y0, y1) + radius - .5, height);
            Py_ssize_t x, y;
            for (y = ymin; y < ymax; ++y) {
                double py = (double)y + .5 - y0;
                Py_ssize_t row = y*width;
                for (x = xmin; x < xmax; ++x) {
                    double px, t, ex, ey;
                    if (pixels[row+x]) continue;
                    px = (double)x + .5 - x0;
                    t = length2 ? (px*dx + py*dy) / length2 : 0.;
                    if (t > 1.) t = 1.;
                    if (t < 0.) t = 0.;
                    ex = px - t*dx; ey = py - t*dy;
                    if (python_power(ex, 2.) + python_power(ey, 2.) < radius2)
                        pixels[row+x] = 255;
                }
            }
        }
    }
    Py_END_ALLOW_THREADS
}

static PyObject *alpha_mask(PyObject *self, PyObject *args)
{
    PyObject *capsule, *result = NULL;
    CompiledArt *art;
    Py_ssize_t width, height, sw, sh, count, i;
    double m[4], phase[2], origin[2], stroke_scale;
    unsigned char *samples = NULL;
    int retained = 0;
    (void)self;
    if (!PyArg_ParseTuple(args, "Onn(dddd)(dd)(dd)d:alpha_mask", &capsule, &width, &height,
                          &m[0], &m[1], &m[2], &m[3], &phase[0], &phase[1],
                          &origin[0], &origin[1], &stroke_scale)) return NULL;
    art = PyCapsule_GetPointer(capsule, ART_CAPSULE);
    if (!art) return NULL;
    for (i = 0; i < 4; ++i) if (!isfinite(m[i])) goto invalid;
    for (i = 0; i < 2; ++i) if (!isfinite(phase[i]) || !isfinite(origin[i])) goto invalid;
    if (!isfinite(stroke_scale) || stroke_scale < 0.) goto invalid;
    if (width < 0 || height < 0 || width > PY_SSIZE_T_MAX/SAMPLES ||
        height > PY_SSIZE_T_MAX/SAMPLES ||
        (height && width > PY_SSIZE_T_MAX/(SAMPLES*SAMPLES)/height)) goto invalid;
    sw = width*SAMPLES; sh = height*SAMPLES; count = sw*sh;
    result = mask_new(width, height);
    if (!result) return NULL;
    if (!art->busy && count <= MAX_RETAINED_SAMPLES &&
        (count <= art->sample_capacity ||
         retained_sample_bytes + count - art->sample_capacity <= TOTAL_RETAINED_SAMPLES)) {
        if (count > art->sample_capacity) {
            samples = PyMem_Realloc(art->samples, (size_t)count);
            if (!samples) { Py_DECREF(result); return PyErr_NoMemory(); }
            retained_sample_bytes += count - art->sample_capacity;
            art->samples = samples; art->sample_capacity = count;
        }
        samples = art->samples; art->busy = 1; retained = 1;
    } else {
        samples = PyMem_Malloc((size_t)count);
        if (count && !samples) { Py_DECREF(result); return PyErr_NoMemory(); }
    }
    if (count) memset(samples, 0, (size_t)count);
    for (i = 0; i < art->count; ++i) {
        CompiledPath *path = &art->paths[i];
        Geometry geometry;
        if (!transform_path(path, m, phase, origin, &geometry)) goto error;
        if (path->fill && !union_fill(sw, sh, &geometry, samples)) {
            geometry_free(&geometry); goto error;
        }
        if (path->stroke) {
            double scaled = path->stroke_width * stroke_scale;
            double stroke_width = (scaled > 1. ? scaled : 1.) * SAMPLES;
            if (!isfinite(stroke_width)) {
                geometry_free(&geometry);
                PyErr_SetString(PyExc_ValueError, "stroke width must be finite"); goto error;
            }
            if (!path->curved && stroke_width == SAMPLES && !grid_fit(&geometry)) {
                geometry_free(&geometry); goto error;
            }
            union_stroke(sw, sh, &geometry, stroke_width, samples);
        }
        geometry_free(&geometry);
    }
    {
        unsigned char *out = (unsigned char *)PyBytes_AS_STRING(result);
        Py_ssize_t x, y;
        /* Pillow BOX reduces horizontally, rounds to uint8, then reduces
         * vertically and rounds again. A single 16-sample average differs. */
        Py_BEGIN_ALLOW_THREADS
        for (y = 0; y < height; ++y) {
            for (x = 0; x < width; ++x) {
                unsigned int vertical = 0;
                Py_ssize_t row;
                for (row = 0; row < SAMPLES; ++row) {
                    const unsigned char *p = samples + (y*SAMPLES+row)*sw + x*SAMPLES;
                    vertical += (p[0]+p[1]+p[2]+p[3]+2)/4;
                }
                out[y*width+x] = (unsigned char)((vertical+2)/4);
            }
        }
        Py_END_ALLOW_THREADS
    }
    if (retained) art->busy = 0; else PyMem_Free(samples);
    return result;
error:
    if (retained) art->busy = 0; else PyMem_Free(samples);
    Py_DECREF(result);
    return NULL;
invalid:
    PyErr_SetString(PyExc_ValueError, "invalid alpha mask size or transform");
    return NULL;
}

/* Compact immutable RGBA records are prepared once by the retained renderer.
 * Composite a bounded RGB patch without relying on Pillow's private C ABI. */
typedef struct {
    const unsigned char *pixels;
    Py_ssize_t width, height, x, y;
} RGBASprite;

static int coordinate_difference(Py_ssize_t position, Py_ssize_t origin,
                                 Py_ssize_t *result)
{
    if ((origin < 0 && position > PY_SSIZE_T_MAX + origin) ||
        (origin > 0 && position < PY_SSIZE_T_MIN + origin)) {
        PyErr_SetString(PyExc_ValueError, "sprite coordinate difference is too large");
        return 0;
    }
    *result = position - origin;
    return 1;
}

static PyObject *composite_rgba(PyObject *self, PyObject *args)
{
    Py_ssize_t width, height, origin_x = 0, origin_y = 0, count, i, length;
    PyObject *rgb, *records, *sequence = NULL, *result = NULL;
    RGBASprite *sprites = NULL;
    unsigned char *destination;
    (void)self;
    if (!PyArg_ParseTuple(args, "nnOO|nn:composite_rgba", &width, &height,
                          &rgb, &records, &origin_x, &origin_y)) return NULL;
    if (width < 0 || height < 0 ||
        (height && width > PY_SSIZE_T_MAX / 3 / height)) {
        PyErr_SetString(PyExc_ValueError, "invalid RGB patch size");
        return NULL;
    }
    length = width * height * 3;
    if (!PyBytes_Check(rgb) || PyBytes_GET_SIZE(rgb) != length) {
        PyErr_SetString(PyExc_ValueError, "RGB patch must contain width*height*3 immutable bytes");
        return NULL;
    }
    /* A tuple also pins records supplied as a mutable list while the GIL is
     * released. Each individual record and its pixel payload are immutable. */
    sequence = PySequence_Tuple(records);
    if (!sequence) return NULL;
    count = PySequence_Fast_GET_SIZE(sequence);
    if ((size_t)count > SIZE_MAX / sizeof(RGBASprite)) {
        Py_DECREF(sequence);
        return PyErr_NoMemory();
    }
    sprites = PyMem_Calloc((size_t)count, sizeof(RGBASprite));
    if (count && !sprites) { Py_DECREF(sequence); return PyErr_NoMemory(); }
    for (i = 0; i < count; ++i) {
        PyObject *record = PySequence_Fast_GET_ITEM(sequence, i), *pixels;
        RGBASprite *sprite = &sprites[i];
        Py_ssize_t x, y;
        if (!PyTuple_Check(record) || PyTuple_GET_SIZE(record) != 5) {
            PyErr_SetString(PyExc_ValueError, "sprite records must be (RGBA bytes, width, height, x, y)");
            goto error;
        }
        pixels = PyTuple_GET_ITEM(record, 0);
        sprite->width = PyLong_AsSsize_t(PyTuple_GET_ITEM(record, 1));
        sprite->height = PyLong_AsSsize_t(PyTuple_GET_ITEM(record, 2));
        x = PyLong_AsSsize_t(PyTuple_GET_ITEM(record, 3));
        y = PyLong_AsSsize_t(PyTuple_GET_ITEM(record, 4));
        if (PyErr_Occurred()) goto error;
        if (sprite->width < 0 || sprite->height < 0 ||
            (sprite->height && sprite->width > PY_SSIZE_T_MAX / 4 / sprite->height) ||
            !PyBytes_Check(pixels) ||
            PyBytes_GET_SIZE(pixels) != sprite->width * sprite->height * 4) {
            PyErr_SetString(PyExc_ValueError, "invalid RGBA sprite size or immutable pixels");
            goto error;
        }
        if (!coordinate_difference(x, origin_x, &sprite->x) ||
            !coordinate_difference(y, origin_y, &sprite->y)) goto error;
        sprite->pixels = (const unsigned char *)PyBytes_AS_STRING(pixels);
    }
    result = PyBytes_FromStringAndSize(PyBytes_AS_STRING(rgb), length);
    if (!result) goto error;
    destination = (unsigned char *)PyBytes_AS_STRING(result);
    /* All referenced objects remain alive and immutable while the GIL is free. */
    Py_BEGIN_ALLOW_THREADS
    for (i = 0; i < count; ++i) {
        RGBASprite *sprite = &sprites[i];
        Py_ssize_t sx, sy, dx, dy, columns, rows, row, column;
        if (!sprite->width || !sprite->height || sprite->x >= width || sprite->y >= height ||
            sprite->x <= -sprite->width || sprite->y <= -sprite->height) continue;
        sx = sprite->x < 0 ? -sprite->x : 0;
        sy = sprite->y < 0 ? -sprite->y : 0;
        dx = sprite->x < 0 ? 0 : sprite->x;
        dy = sprite->y < 0 ? 0 : sprite->y;
        columns = sprite->width - sx;
        if (columns > width - dx) columns = width - dx;
        rows = sprite->height - sy;
        if (rows > height - dy) rows = height - dy;
        for (row = 0; row < rows; ++row) {
            const unsigned char *source = sprite->pixels + ((sy + row) * sprite->width + sx) * 4;
            unsigned char *out = destination + ((dy + row) * width + dx) * 3;
            for (column = 0; column < columns; ++column, source += 4, out += 3) {
                unsigned int alpha = source[3], channel;
                if (!alpha) continue;
                if (alpha == 255) { out[0] = source[0]; out[1] = source[1]; out[2] = source[2]; continue; }
                for (channel = 0; channel < 3; ++channel) {
                    /* Pillow's BLEND/DIV255, including its integer rounding. */
                    unsigned int value = out[channel] * (255 - alpha) + source[channel] * alpha + 128;
                    out[channel] = (unsigned char)((value + (value >> 8)) >> 8);
                }
            }
        }
    }
    Py_END_ALLOW_THREADS
error:
    PyMem_Free(sprites);
    Py_DECREF(sequence);
    return result;
}

static PyMethodDef methods[] = {
    {"composite_rgba", composite_rgba, METH_VARARGS, "Paste ordered RGBA sprites onto a bounded RGB patch with exact Pillow rounding."},
    {"compile_art", compile_art, METH_O, "Compile immutable opaque vector commands."},
    {"alpha_mask", alpha_mask, METH_VARARGS, "Transform and rasterise complete opaque artwork with exact BOX reduction."},
    {"fill_mask", fill_mask, METH_VARARGS, "Even-odd binary fill coverage; releases the GIL."},
    {"stroke_mask", stroke_mask, METH_VARARGS, "Round capsule stroke coverage; releases the GIL."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_nv14_render_native",
    "Optional native vector rasterisation, independent of simulation.",
    -1, methods, NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC PyInit__nv14_render_native(void) { return PyModule_Create(&module); }

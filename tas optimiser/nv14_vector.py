"""Small optional rasteriser for the pinned SWF's solid vector artwork.

Coordinates are already in game units. Hairlines are rasterised after the
final transform, with one output pixel as the minimum stroke width. Pillow is
loaded only while rendering. No simulation or timeline state is owned here.
"""
from __future__ import annotations

import math
from collections import OrderedDict

SAMPLES = 4
_native = None
_native_checked = False
# Keep the source alive to prevent id reuse, and a separate snapshot to notice
# edits to caller-owned artwork. Comparing JSON-shaped artwork is implemented
# by Python's C containers and avoids rebuilding command tuples every frame.
_compiled_art_cache = OrderedDict()
_COMPILED_ART_CACHE_LIMIT = 512


def _compiled_art(art):
    key = id(art)
    cached = _compiled_art_cache.get(key)
    if cached is not None and cached[0] is art and cached[1] == art:
        _compiled_art_cache.move_to_end(key)
        return cached[2]
    from copy import deepcopy
    snapshot = deepcopy(art)
    compiled = _native.compile_art(snapshot["paths"])
    _compiled_art_cache[key] = (art, snapshot, compiled)
    _compiled_art_cache.move_to_end(key)
    while len(_compiled_art_cache) > _COMPILED_ART_CACHE_LIMIT:
        _compiled_art_cache.popitem(last=False)
    return compiled


def native_backend_available():
    """Load the optional rendering extension on the first rendering request."""
    global _native, _native_checked
    if not _native_checked:
        try:
            import _nv14_render_native
        except ImportError:
            _native = None
        else:
            _native = _nv14_render_native
        _native_checked = True
    return _native is not None


def _contours(commands, point):
    result, contour = [], []

    def quadratic(start, control, end, depth=0):
        # Convex hull error bound in supersampled device coordinates.
        error = math.hypot(start[0] - 2*control[0] + end[0],
                           start[1] - 2*control[1] + end[1]) / 4
        if error <= .125 or depth == 16:
            contour.append(end)
            return
        a = ((start[0]+control[0])/2, (start[1]+control[1])/2)
        b = ((control[0]+end[0])/2, (control[1]+end[1])/2)
        mid = ((a[0]+b[0])/2, (a[1]+b[1])/2)
        quadratic(start, a, mid, depth+1)
        quadratic(mid, b, end, depth+1)

    for cmd in commands:
        if cmd[0] == "M":
            if contour:
                result.append(contour)
            contour = [point(cmd[1], cmd[2])]
        elif cmd[0] == "L":
            contour.append(point(cmd[1], cmd[2]))
        elif cmd[0] == "Q":
            quadratic(contour[-1], point(cmd[1], cmd[2]), point(cmd[3], cmd[4]))
        elif cmd[0] == "Z":
            if contour and contour[-1] != contour[0]:
                contour.append(contour[0])
        else:
            raise ValueError(f"Unsupported vector command: {cmd[0]}")
    if contour:
        result.append(contour)
    return result


def _fill_mask(size, contours, Image, ImageDraw):
    """Even-odd scan conversion at pixel centres, including nested holes.

    Avoid ImageDraw.polygon's inclusive right/bottom edges and artificial
    bridges between separate SVG subpaths.
    """
    if native_backend_available():
        return Image.frombytes("L", size, _native.fill_mask(*size, contours))
    return _fill_mask_python(size, contours, Image, ImageDraw)


def _fill_mask_python(size, contours, Image, ImageDraw):
    rows = {}
    for contour in contours:
        if len(contour) < 3:
            continue
        for (x0, y0), (x1, y1) in zip(contour, contour[1:] + contour[:1]):
            if y0 == y1:
                continue
            if y1 < y0:
                x0, x1, y0, y1 = x1, x0, y1, y0
            slope = (x1-x0)/(y1-y0)
            for y in range(max(0, math.ceil(y0-.5)), min(size[1], math.ceil(y1-.5))):
                rows.setdefault(y, []).append(x0+(y+.5-y0)*slope)
    mask = Image.new("L", size)
    draw = ImageDraw.Draw(mask)
    for y, intersections in rows.items():
        intersections.sort()
        for start, end in zip(intersections[::2], intersections[1::2]):
            start = max(0, math.ceil(start-.5))
            end = min(size[0]-1, math.ceil(end-.5)-1)
            if start <= end:
                draw.line((start, y, end, y), fill=255)
    return mask


def _stroke_mask(size, contours, width, Image, *, grid_fit=True):
    """Union of round segment capsules, sampled at pixel centres.

    A single mask prevents semi-transparent joins/overlapping segments from
    accumulating opacity. It also preserves zero-height ninja limb paths.
    """
    if native_backend_available():
        return Image.frombytes("L", size,
                               _native.stroke_mask(*size, contours, width, grid_fit))
    return _stroke_mask_python(size, contours, width, Image, grid_fit=grid_fit)


def _stroke_mask_python(size, contours, width, Image, *, grid_fit=True):
    pixels = bytearray(size[0] * size[1])
    radius = width / 2
    radius2 = radius * radius
    for contour in contours:
        if width == SAMPLES and grid_fit:
            # Flash grid-fits axis-aligned hairlines to one device-pixel
            # centre. Merely antialiasing a line on an integer boundary
            # would split it into two pale rows, unlike the reference game.
            fitted = [list(p) for p in contour]
            for i in range(len(contour)-1):
                for axis in (0, 1):
                    if abs(contour[i][axis]-contour[i+1][axis]) < 1e-6:
                        value = (math.floor(contour[i][axis]/SAMPLES+.5)+.5)*SAMPLES
                        fitted[i][axis] = fitted[i+1][axis] = value
            if len(contour) > 1 and contour[0] == contour[-1]:
                # Both neighbours constrain the repeated closing vertex.
                for axis in (0, 1):
                    if fitted[0][axis] != contour[0][axis]:
                        fitted[-1][axis] = fitted[0][axis]
                    else:
                        fitted[0][axis] = fitted[-1][axis]
            contour = fitted
        for (x0, y0), (x1, y1) in zip(contour, contour[1:]):
            dx, dy = x1-x0, y1-y0
            length2 = dx*dx + dy*dy
            xmin = max(0, math.ceil(min(x0, x1)-radius-.5))
            xmax = min(size[0], math.ceil(max(x0, x1)+radius-.5))
            ymin = max(0, math.ceil(min(y0, y1)-radius-.5))
            ymax = min(size[1], math.ceil(max(y0, y1)+radius-.5))
            for y in range(ymin, ymax):
                py = y+.5-y0
                row = y * size[0]
                for x in range(xmin, xmax):
                    if pixels[row+x]:
                        continue
                    px = x+.5-x0
                    t = max(0., min(1., (px*dx+py*dy)/length2)) if length2 else 0.
                    if (px-t*dx)**2 + (py-t*dy)**2 < radius2:
                        pixels[row+x] = 255
    return Image.frombytes("L", size, bytes(pixels))


def rasterize(art, transform, phase=(0., 0.), clip=None, *, alpha_only=False):
    """Return an image and output-pixel offset from a MovieClip's origin.

    ``transform`` maps game coordinates to device pixels. ``clip`` optionally
    limits extreme dynamic transforms to the visible viewport. ``alpha_only``
    returns an L coverage mask, independent of artwork colour. Opaque artwork
    uses binary mask unions at sample resolution, avoiding RGBA layers.
    """
    from PIL import Image, ImageDraw

    a, b, c, d = transform
    px, py = phase
    x0, y0, x1, y1 = art["bounds"]
    corners = [(a*x+b*y+px, c*x+d*y+py)
               for x in (x0, x1) for y in (y0, y1)]
    stroke_scale = math.sqrt(abs(a*d-b*c))
    max_width = max((max(1., item.get("stroke_width", 0.)*stroke_scale)
                     for item in art["paths"] if item.get("stroke") is not None), default=0.)
    pad = max_width / 2 + 1
    left = math.floor(min(x for x, _ in corners)-pad)
    top = math.floor(min(y for _, y in corners)-pad)
    right = math.ceil(max(x for x, _ in corners)+pad)
    bottom = math.ceil(max(y for _, y in corners)+pad)
    if clip is not None:
        left, top = max(left, clip[0]), max(top, clip[1])
        right, bottom = min(right, clip[2]), min(bottom, clip[3])
    if right <= left or bottom <= top:
        return Image.new("L" if alpha_only else "RGBA", (1, 1)), left, top
    size = ((right-left)*SAMPLES, (bottom-top)*SAMPLES)
    opaque_alpha = alpha_only and all(
        color is None or color[3] == 255
        for item in art["paths"] for color in (item.get("fill"), item.get("stroke")))
    if opaque_alpha and native_backend_available() and hasattr(_native, "alpha_mask"):
        pixels = _native.alpha_mask(_compiled_art(art), right-left, bottom-top,
                                    transform, phase, (left, top), stroke_scale)
        return Image.frombytes("L", (right-left, bottom-top), pixels), left, top
    canvas = Image.new("L" if opaque_alpha else "RGBA", size)
    if opaque_alpha:
        from PIL import ImageChops

    def point(x, y):
        return ((a*x+b*y+px-left)*SAMPLES, (c*x+d*y+py-top)*SAMPLES)

    def paint(mask, color):
        nonlocal canvas
        if opaque_alpha:
            # All masks are binary before BOX downsampling. Their maximum is
            # exactly the source-over alpha of opaque layers, including joins.
            canvas = ImageChops.lighter(canvas, mask)
            return
        if color[3] != 255:
            mask = mask.point([round(v*color[3]/255) for v in range(256)])
        layer = Image.new("RGBA", size, tuple(color[:3]) + (0,))
        layer.putalpha(mask)
        canvas.alpha_composite(layer)

    for item in art["paths"]:
        contours = _contours(item["commands"], point)
        if item.get("fill") is not None:
            paint(_fill_mask(size, contours, Image, ImageDraw), item["fill"])
        if item.get("stroke") is not None:
            width = max(1., item["stroke_width"]*stroke_scale) * SAMPLES
            paint(_stroke_mask(size, contours, width, Image,
                               grid_fit=not any(cmd[0] == "Q" for cmd in item["commands"])),
                  item["stroke"])
    # BOX integrates coverage without ringing outside the original shapes.
    canvas = canvas.resize((right-left, bottom-top), Image.Resampling.BOX)
    if alpha_only and not opaque_alpha:
        canvas = canvas.getchannel("A")
    return canvas, left, top

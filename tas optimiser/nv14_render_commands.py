"""Private, optional Pillow draw records for exact incremental replay rendering.

No Pillow import occurs until an actual command is replayed. Draw records retain
already transformed artwork; they never own or modify gameplay snapshots.
"""
from __future__ import annotations


def freeze(value):
    """Snapshot JSON-shaped caller data without copying immutable draw records."""
    if isinstance(value, dict):
        return tuple((key, freeze(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def intersects(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class Command:
    __slots__ = ("kind", "args", "bounds", "signature", "bytes_used", "key")

    def __init__(self, kind, args, bounds):
        self.kind, self.args, self.bounds = kind, args, bounds
        self.key = None
        if kind == "paste":
            image, box, mask = args
            is_image = hasattr(image, "getbands")
            self.signature = (kind, id(image) if is_image else freeze(image), box, id(mask))
            self.bytes_used = ((image.width * image.height * len(image.getbands())) if is_image else 0)
            if mask is not None and mask is not image:
                self.bytes_used += mask.width * mask.height * len(mask.getbands())
        else:
            self.signature = (kind, args)
            self.bytes_used = 0

    def draw(self, canvas, origin=(0, 0)):
        ox, oy = origin
        if self.kind == "paste":
            image, box, mask = self.args
            shifted = tuple(value - (ox if index % 2 == 0 else oy)
                            for index, value in enumerate(box))
            canvas.paste(image, shifted, mask)
        else:
            from PIL import ImageDraw
            draw = ImageDraw.Draw(canvas)
            if self.kind == "line":
                points, fill, width = self.args
                draw.line([(x-ox, y-oy) for x, y in points], fill=fill, width=width)
            else:
                box, fill, outline, width = self.args
                draw.ellipse(tuple(value - (ox if index % 2 == 0 else oy)
                                   for index, value in enumerate(box)),
                             fill=fill, outline=outline, width=width)


class DrawList:
    """A minimal paste/primitive sink that retains groups unchanged between ticks."""
    MAX_CACHE_BYTES = 32 * 1024 * 1024
    MAX_CACHE_GROUPS = 4096

    def __init__(self, size, previous, stats):
        self.size = size
        self.commands = []
        self.groups = {}
        self.previous = previous
        self.stats = stats
        self.cache_bytes = 0

    def paste(self, image, box=(0, 0), mask=None):
        box = tuple(box)
        if len(box) == 2:
            bounds = (*box, box[0] + image.width, box[1] + image.height)
        else:
            bounds = box
        self.commands.append(Command("paste", (image, box, mask), bounds))

    def line(self, points, fill, width):
        points = tuple(points)
        # Pillow's thick line rasterisation, inclusive endpoints and joins
        # remain inside this deliberately conservative integer rectangle.
        bounds = (min(p[0] for p in points)-width, min(p[1] for p in points)-width,
                  max(p[0] for p in points)+width+1, max(p[1] for p in points)+width+1)
        self.commands.append(Command("line", (points, fill, width), bounds))

    def ellipse(self, box, fill, outline, width):
        bounds = (box[0]-width, box[1]-width, box[2]+width+1, box[3]+width+1)
        self.commands.append(Command("ellipse", (tuple(box), fill, outline, width), bounds))

    def capture(self, key, state, callback):
        self.capture_signature(key, freeze(state), callback)

    def capture_signature(self, key, signature, callback):
        """Capture using an already immutable render-only state signature."""
        previous = self.previous.get(key)
        if previous is not None and previous[0] == signature:
            commands = previous[1]
            self.commands.extend(commands)
            self.stats["command_cache_hits"] += 1
            size = previous[2] if len(previous) > 2 else sum(command.bytes_used for command in commands)
        else:
            first = len(self.commands)
            callback()
            commands = tuple(self.commands[first:])
            for index, command in enumerate(commands):
                command.key = (key, index)
            self.stats["command_cache_misses"] += 1
            size = sum(command.bytes_used for command in commands)
        if (self.cache_bytes + size <= self.MAX_CACHE_BYTES
                and len(self.groups) < self.MAX_CACHE_GROUPS):
            self.groups[key] = (signature, commands, size)
            self.cache_bytes += size


class CommandIndex:
    """Incremental device-space grid with commands returned in paint order.

    Small scenes use a direct scan. Large overlays live in a separate bucket,
    so the terrain image does not occupy every grid cell. Membership changes
    only when a command's bounds change, including moves outside the viewport.
    """
    MIN_COMMANDS = 64
    MAX_CELLS_PER_COMMAND = 64
    _UNKEYED = object()

    def __init__(self, size, cell_size=64):
        self.size = size
        self.cell_size = max(1, int(cell_size))
        self.commands = ()
        self._entries = {}
        self._order = {}
        self._cells = {}
        self._large = set()
        self._wide_lines = set()
        self._indexed = False

    def _cell_range(self, bounds):
        from math import ceil, floor
        width, height = self.size
        a, b, c, d = bounds
        a, b, c, d = max(0, a), max(0, b), min(width, c), min(height, d)
        if a >= c or b >= d:
            return 0, 0, 0, 0
        cell = self.cell_size
        return floor(a / cell), floor(b / cell), ceil(c / cell), ceil(d / cell)

    def _add(self, key, command):
        a, b, c, d = self._cell_range(command.bounds)
        if (c-a)*(d-b) > self.MAX_CELLS_PER_COMMAND:
            self._large.add(key)
            cells = None
        else:
            cells = tuple((x, y) for y in range(b, d) for x in range(a, c))
            for cell in cells:
                self._cells.setdefault(cell, set()).add(key)
        self._entries[key] = (command, cells)

    def _remove(self, key, entry):
        cells = entry[1]
        if cells is None:
            self._large.discard(key)
        else:
            for cell in cells:
                bucket = self._cells[cell]
                bucket.remove(key)
                if not bucket:
                    del self._cells[cell]

    def update(self, commands):
        """Update memberships and return changed ``(before, after)`` pairs.

        Relative reordering invalidates common commands as well: translucent
        overlap can change even when every individual sprite is unchanged.
        """
        entries, old_order = self._entries, self._order
        new_order, changes = {}, []
        last_old_index, reordered = -1, False
        indexed = len(commands) >= self.MIN_COMMANDS
        if indexed != self._indexed:
            # Only threshold crossings rebuild the spatial membership. Keep
            # previous commands long enough to compute the normal dirty set.
            self._cells.clear()
            self._large.clear()
        rebuild = indexed and not self._indexed
        for index, command in enumerate(commands):
            key = command.key
            if key is None:
                key = (self._UNKEYED, index)
            new_order[key] = index
            entry = entries.get(key)
            before = entry[0] if entry is not None else None
            if before is not None:
                old_index = old_order[key]
                if old_index < last_old_index:
                    reordered = True
                last_old_index = old_index
            if before is not command and (before is None or before.signature != command.signature):
                changes.append((before, command))
            if indexed:
                if rebuild or before is None:
                    self._add(key, command)
                elif before.bounds != command.bounds:
                    self._remove(key, entry)
                    self._add(key, command)
                elif before is not command:
                    entries[key] = (command, entry[1])
            else:
                entries[key] = (command, ())
            if command.kind == "line" and command.args[2] > 1:
                self._wide_lines.add(key)
            else:
                self._wide_lines.discard(key)
        for key in old_order.keys() - new_order.keys():
            entry = entries.pop(key)
            changes.append((entry[0], None))
            if indexed and not rebuild:
                self._remove(key, entry)
            self._wide_lines.discard(key)
        if reordered:
            # Reordering is rare and conservative invalidation is cheaper than
            # tracking every changed overlap or comparing all key pairs.
            changes.extend((None, entry[0]) for entry in entries.values())
        self.commands = commands
        self._order = new_order
        self._indexed = indexed
        return changes

    def query(self, rect):
        """Return only intersecting commands, preserving strict painter order."""
        if not self._indexed:
            return [command for command in self.commands if intersects(command.bounds, rect)]
        a, b, c, d = self._cell_range(rect)
        keys = self._large.copy()
        for y in range(b, d):
            for x in range(a, c):
                keys.update(self._cells.get((x, y), ()))
        entries = self._entries
        return [entries[key][0] for key in sorted(keys, key=self._order.__getitem__)
                if intersects(entries[key][0].bounds, rect)]

    def intersects_wide_line(self, rectangles):
        return any(intersects(self._entries[key][0].bounds, rect)
                   for key in self._wide_lines for rect in rectangles)


def dirty_regions(old, new, size, *, changes=None, index=None):
    """Disjoint dirty rectangles, or None when a full redraw is cheaper.

    Keys include drawing layer and depth position; additions/removals cannot
    shift the immutable terrain command into a spurious whole-frame change.
    """
    rectangles = []
    width, height = size
    if changes is None:
        previous = {command.key: command for command in old}
        current = {command.key: command for command in new}
        changes = ((previous.get(key), current.get(key))
                   for key in previous.keys() | current.keys()
                   if (key not in previous or key not in current
                       or previous[key].signature != current[key].signature))
    for before, after in changes:
        for command in (before, after):
            if command is None:
                continue
            a, b, c, d = command.bounds
            rect = (max(0, a), max(0, b), min(width, c), min(height, d))
            if rect[0] >= rect[2] or rect[1] >= rect[3]:
                continue
            # Repeatedly merge intersecting rectangles. Restart after a merge
            # so the output stays disjoint and translucent pixels blend once.
            i = 0
            while i < len(rectangles):
                other = rectangles[i]
                if intersects(rect, other):
                    rect = (min(rect[0], other[0]), min(rect[1], other[1]),
                            max(rect[2], other[2]), max(rect[3], other[3]))
                    rectangles.pop(i)
                    i = 0
                else:
                    i += 1
            rectangles.append(rect)
            if len(rectangles) > 48:
                # Small animation pieces can arrive before a later, larger
                # player/sprite bound joins them. Falling back immediately
                # makes redraw cost depend on command enumeration order.
                # Coalesce a compact cluster instead, keeping the merge scan
                # bounded even for thousands of scattered changing sprites.
                combined = (min(r[0] for r in rectangles), min(r[1] for r in rectangles),
                            max(r[2] for r in rectangles), max(r[3] for r in rectangles))
                if (combined[2]-combined[0])*(combined[3]-combined[1]) > width*height*.55:
                    return None
                rectangles[:] = [combined]
    if sum((r[2]-r[0])*(r[3]-r[1]) for r in rectangles) > width*height*.55:
        return None
    # Pillow widelines construct rounded polygon edges in device coordinates.
    # Translating their endpoints into a cropped patch can change edge pixels,
    # even for integer offsets. Keep the original viewport for any redraw that
    # intersects a wide line; untouched lines can stay on the retained canvas.
    if (index.intersects_wide_line(rectangles) if index is not None else
            any(command.kind == "line" and command.args[2] > 1
                and any(intersects(command.bounds, rect) for rect in rectangles)
                for command in new)):
        return None
    return rectangles

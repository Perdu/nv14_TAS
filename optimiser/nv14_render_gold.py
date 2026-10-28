"""Bounded, optional native batching of retained gold paste commands.

The extension consumes public RGB/RGBA byte buffers, not Pillow internals. Small
or sparse groups retain Pillow's direct paste path. Every batch is contiguous in
paint order, including primary gold and the shaded secondary collection clips.
"""
from __future__ import annotations

from collections import OrderedDict


class GoldBatchRenderer:
    MIN_BATCH = 16
    MAX_PATCH_PIXELS = 256 * 1024
    MAX_AREA_RATIO = 4
    MAX_CACHE_BYTES = 8 * 1024 * 1024
    MAX_CACHE_ITEMS = 4096

    def __init__(self):
        try:
            from _nv14_render_native import composite_rgba
        except ImportError:
            composite_rgba = None
        self._composite = composite_rgba
        self._images = OrderedDict()
        self._commands = OrderedDict()
        self._groups = OrderedDict()
        self._image_bytes = self._command_bytes = 0
        self._group_bytes = 0
        self.batches = self.pastes = 0

    def clear(self):
        self._images.clear()
        self._commands.clear()
        self._groups.clear()
        self._image_bytes = self._command_bytes = 0
        self._group_bytes = 0

    @staticmethod
    def _eligible(command):
        key = command.key
        if (command.kind != "paste" or key is None or
                key[0][0] not in ("secondary-gold", "primary-gold")):
            return False
        image, box, mask = command.args
        return (mask is image and image.mode == "RGBA" and len(box) == 2 and
                isinstance(box[0], int) and isinstance(box[1], int))

    def _record(self, command):
        key = id(command)
        entry = self._commands.get(key)
        if entry is not None:
            self._commands.move_to_end(key)
            return entry[1]
        image, (x, y), _ = command.args
        image_key = id(image)
        entry = self._images.get(image_key)
        if entry is None:
            pixels = image.tobytes()
            if len(pixels) <= self.MAX_CACHE_BYTES:
                self._images[image_key] = (image, pixels)
                self._image_bytes += len(pixels)
                while (self._image_bytes > self.MAX_CACHE_BYTES or
                       len(self._images) > self.MAX_CACHE_ITEMS):
                    _, (_, old) = self._images.popitem(last=False)
                    self._image_bytes -= len(old)
        else:
            self._images.move_to_end(image_key)
            pixels = entry[1]
        record = (pixels, image.width, image.height, x, y)
        # Charge each record for its bytes even when several share one sprite;
        # this conservatively bounds references after image-cache eviction.
        if len(pixels) <= self.MAX_CACHE_BYTES:
            self._commands[key] = (command, record)
            self._command_bytes += len(pixels)
            while (self._command_bytes > self.MAX_CACHE_BYTES or
                   len(self._commands) > self.MAX_CACHE_ITEMS):
                _, (_, old) = self._commands.popitem(last=False)
                self._command_bytes -= len(old[0])
        return record

    def _prepare_group(self, canvas, commands, origin):
        ox, oy = origin
        width, height = canvas.size
        left, top, right, bottom = ox + width, oy + height, ox, oy
        occupied = 0
        visible = []
        for command in commands:
            a, b, c, d = command.bounds
            a, b, c, d = max(a, ox), max(b, oy), min(c, ox + width), min(d, oy + height)
            if a >= c or b >= d:
                continue
            visible.append(command)
            left, top, right, bottom = min(left, a), min(top, b), max(right, c), max(bottom, d)
            occupied += (c - a) * (d - b)
        area = (right - left) * (bottom - top)
        if not visible:
            return (), (), 0
        if (len(visible) < self.MIN_BATCH or area > self.MAX_PATCH_PIXELS or
                area > occupied * self.MAX_AREA_RATIO):
            return None, (), 0
        box = (left - ox, top - oy, right - ox, bottom - oy)
        records = tuple(self._record(command) for command in visible)
        return box, records, sum(len(record[0]) for record in records)

    def _draw_group(self, canvas, commands, origin):
        if len(commands) < self.MIN_BATCH:
            for command in commands:
                command.draw(canvas, origin)
            return
        # Identical retained groups recur across ticks. Cache both positive and
        # negative batching decisions, including patch origins, so sparse gold
        # does not repeatedly pay to rediscover that direct paste is cheaper.
        key = (origin, canvas.size, tuple(commands))
        prepared = self._groups.get(key)
        if prepared is None:
            box, records, size = self._prepare_group(canvas, commands, origin)
            # Commands retain their source images even for a rejected group.
            size += sum(command.bytes_used for command in commands) + 64 * len(commands)
            prepared = (box, records, size)
            if size <= self.MAX_CACHE_BYTES:
                self._groups[key] = prepared
                self._group_bytes += size
                while self._group_bytes > self.MAX_CACHE_BYTES or len(self._groups) > 64:
                    _, (_, _, old_size) = self._groups.popitem(last=False)
                    self._group_bytes -= old_size
        else:
            self._groups.move_to_end(key)
        box, records, _ = prepared
        if box is None:
            for command in commands:
                command.draw(canvas, origin)
            return
        if not box:
            return
        from PIL import Image
        patch = canvas.crop(box)
        pixels = self._composite(patch.width, patch.height, patch.tobytes(),
                                 records, box[0] + origin[0], box[1] + origin[1])
        canvas.paste(Image.frombytes("RGB", patch.size, pixels), box)
        self.batches += 1
        self.pastes += len(records)

    def draw(self, canvas, commands, origin=(0, 0)):
        if (self._composite is None or canvas.mode != "RGB" or
                (hasattr(commands, "__len__") and len(commands) < self.MIN_BATCH)):
            for command in commands:
                command.draw(canvas, origin)
            return
        group = []
        for command in commands:
            if self._eligible(command):
                group.append(command)
            else:
                if group:
                    self._draw_group(canvas, group, origin)
                    group.clear()
                command.draw(canvas, origin)
        if group:
            self._draw_group(canvas, group, origin)

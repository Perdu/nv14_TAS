"""Optional headless rendering of native replay scene snapshots.

Nothing imports Pillow until SceneRenderer is constructed. Rendering observes a
snapshot; it never advances physics, animations, random generators or events.
The renderer includes original ninja poses, terrain, and optional externally
tracked object timelines, eye rotation and particle draw records. It omits the
Flash GUI, sound and ragdolls. See docs/VIDEO_ENCODING.md.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path

MAP_SIZE = (792, 600)
TERRAIN = (121, 121, 136)  # TileMapCell: Color.setRGB(7960968)
BACKGROUND = (202, 202, 208)  # n_v14.swf SetBackgroundColor
SECONDARY_PLAYER_COLOR = (53, 104, 168)
_WALL_KINDS = frozenset(("exit_door", "exit_switch", "testdoor", "oneway",
                         "launch", "turret", "homing"))

# Only fields consumed by the drawing code participate in retained signatures.
# Physics/debug fields in native snapshots can change without changing a pixel.
_OBJECT_FIELDS = {
    "exit_door": ("is_open",), "exit_switch": ("is_open",),
    "oneway": ("direction",), "launch": (),
    "testdoor": ("door_x", "door_y", "horizontal", "is_open", "is_locked",
                 "is_trap", "trigger_active"),
    "bounce": (), "thwomp": ("direction",), "floorguard": ("chasing",),
    "homing": ("mode",), "turret": (),
}
_DRONE_FIELDS = ("chasing", "mode", "direction", "view", "beam_visible",
                 "beam_start", "beam_end", "shot_visible", "shot_target")


def _draw_value(value):
    # Scene coordinates/descriptor parameters may be lists in caller snapshots.
    return tuple(value) if isinstance(value, list) else value


def _player_signature(visual):
    return (visual.get("visible", True), visual.get("frame"), visual.get("x"),
            visual.get("y"), visual.get("rotation_deg", 0), visual.get("facing", 1))


def _object_signature(obj, particles, visual):
    kind = obj["kind"]
    if visual is not None:
        shot = obj.get("shot_visible") and not particles
        return (kind, visual, bool(shot),
                (obj["x"], obj["y"], _draw_value(obj.get("beam_end", obj.get("shot_target"))))
                if shot else None)
    if not obj.get("visible", True):
        return (kind, False)
    geometry = (kind, obj["x"], obj["y"])
    if kind in ("gold", "mine"):
        return geometry
    fields = _DRONE_FIELDS if kind.startswith("drone_") else _OBJECT_FIELDS.get(kind, ())
    return (geometry, _draw_value(obj.get("parameters", ())), particles,
            tuple(_draw_value(obj.get(name)) for name in fields))


def _weapon_signature(obj, visual):
    if visual is not None:
        return (visual.rocket, visual.crosshair)
    if obj["kind"] == "homing":
        return (obj.get("rocket_visible"), obj.get("rocket_x"), obj.get("rocket_y"),
                obj.get("rocket_rotation_deg", 0), _draw_value(obj.get("rocket_direction")))
    if obj["kind"] == "turret":
        return (obj.get("crosshair_visible"), _draw_value(obj.get("aim")), obj.get("mode"))
    return ()


def _hidden_gold(obj, visual, particles):
    if obj["kind"] != "gold" or obj.get("visible", True):
        return False
    if visual is None:
        return True
    return (not any(sprite is not None and sprite.visible for sprite in
                    (visual.body, visual.trigger, visual.blast, visual.beam))
            and not (obj.get("shot_visible") and not particles))


@lru_cache(maxsize=128)
def _gold_tint_luts(color):
    """Map the original gold's light/dark detail around the ghost's colour.

    The central SWF fill is RGB (226, 226, 0), luminance 200 in Pillow's L
    conversion. Anchor it to the supplied colour, darken towards black below
    it and lighten towards white above it. This retains the original border,
    inset squares and bright highlight, including changing collection artwork.
    Tables are small and shared; pixel operations remain inside Pillow.
    """
    return tuple(tuple(round(channel * value / 200) if value <= 200 else
                       round(channel + (255 - channel) * (value - 200) / 55)
                       for value in range(256)) for channel in color)


def validate_player_label(label):
    if label is not None and not isinstance(label, str):
        raise TypeError("player labels must be strings or None")
    if label and (len(label) > 128 or not label.isprintable()):
        raise ValueError("player labels must be single-line printable text, at most 128 characters")


def validate_label_size(size):
    if isinstance(size, bool) or not isinstance(size, int) or not 6 <= size <= 32:
        raise ValueError("label_size must be an integer from 6 to 32 game pixels")


def validate_label_position(position):
    if position not in ("follow", "top-left"):
        raise ValueError("label_position must be 'follow' or 'top-left'")


class _ImageCache:
    """Small LRU with limits on pixel storage *and* entry overhead.

    Values are either images or (image, left, top) tuples. Budgets are per
    renderer, so worker-local caches have a predictable upper bound. Oversize
    one-off transforms are usable without displacing the reusable artwork.
    """

    def __init__(self, max_bytes, max_entries=2048):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.bytes_used = 0
        self._entries = OrderedDict()

    @staticmethod
    def _size(value):
        images = value if isinstance(value, tuple) else (value,)
        return sum(image.width * image.height * len(image.getbands())
                   for image in images if hasattr(image, "getbands"))

    def get(self, key):
        value = self._entries.get(key)
        if value is not None:
            self._entries.move_to_end(key)
        return value

    def put(self, key, value):
        size = self._size(value)
        if size > self.max_bytes:
            return
        previous = self._entries.pop(key, None)
        if previous is not None:
            self.bytes_used -= self._size(previous)
        self._entries[key] = value
        self.bytes_used += size
        while self.bytes_used > self.max_bytes or len(self._entries) > self.max_entries:
            _, oldest = self._entries.popitem(last=False)
            self.bytes_used -= self._size(oldest)

    def __len__(self):
        return len(self._entries)

    def items(self):
        return self._entries.items()


# Process-local preparation caches. Only internal immutable artwork is shared;
# caller-visible manifests and returned frames remain independent.
_TERRAIN_CACHE = _ImageCache(64 * 1024 * 1024, 16)
_TILE_MASK_CACHE = _ImageCache(8 * 1024 * 1024, 512)
_JSON_CACHE = OrderedDict()
_JSON_CACHE_BYTES = 0


def _load_art_json(path):
    global _JSON_CACHE_BYTES
    path = path.resolve()
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    cached = _JSON_CACHE.get(key)
    if cached is not None:
        _JSON_CACHE.move_to_end(key)
        return cached[0]
    result = json.loads(path.read_text("utf-8"))
    if stat.st_size <= 32 * 1024 * 1024:
        _JSON_CACHE[key] = (result, stat.st_size)
        _JSON_CACHE_BYTES += stat.st_size
        while _JSON_CACHE_BYTES > 32 * 1024 * 1024 or len(_JSON_CACHE) > 8:
            _, (_, size) = _JSON_CACHE.popitem(last=False)
            _JSON_CACHE_BYTES -= size
    return result


class SceneRenderer:
    """Render ``NativeState.scene_snapshot()`` to an independent RGB image.

    ``level_data`` is a raw level string or an nv14_engine.Level. ``scale`` is
    a positive integer; exported dimensions are 792*scale by 600*scale. Assets
    default to the bundled nv14_assets directory. A supplied directory must
    contain a manifest.json; missing/corrupt requested assets raise an error.
    Instances cache terrain and bounded sprite transforms and are reusable for
    independent snapshots of the same level. ``render_quality='exact'`` keeps
    original subpixel coverage; optional ``'fast'`` uses a lazy player atlas
    with positions on an eighth-output-pixel grid and whole-degree rotations.
    Object and particle artwork is exact in both modes.
    """

    def __init__(self, level_data, *, assets_path=None, scale=1,
                 background=BACKGROUND, terrain=TERRAIN, render_quality="exact",
                 _terrain_layers=None, incremental=True):
        if isinstance(scale, bool) or not isinstance(scale, int) or scale < 1:
            raise ValueError("scale must be a positive integer")
        if render_quality not in ("exact", "fast"):
            raise ValueError("render_quality must be 'exact' or 'fast'")
        try:
            from PIL import Image, ImageDraw
        except ImportError as exc:
            raise ImportError(
                "Video rendering requires Pillow; install the video extra "
                "with 'python -m pip install .[video]' or install Pillow."
            ) from exc
        import nv14_engine as engine
        self._Image, self._ImageDraw, self._engine = Image, ImageDraw, engine
        self.scale = scale
        self.render_quality = render_quality
        self.incremental = bool(incremental)
        self.stats = dict(full_frames=0, dirty_frames=0, unchanged_frames=0,
                          drawn_pixels=0, command_cache_hits=0,
                          command_cache_misses=0, terrain_cache_hits=0,
                          object_order_cache_hits=0)
        self.performance_stats = self.stats
        self.reset_frame_cache()
        self.size = tuple(v * scale for v in MAP_SIZE)
        if isinstance(level_data, str):
            # Only parse immutable geometry: the native engine already owns
            # enemy simulation. No second Python simulation is performed.
            self.level = engine.parse_level_string(level_data)
        elif isinstance(level_data, engine.Level):
            self.level = level_data
        else:
            raise TypeError("level_data must be a raw level string or Level")
        self.assets_path = (Path(assets_path) if assets_path is not None else
                            Path(__file__).resolve().parent / "nv14_assets")
        manifest_path = self.assets_path / "manifest.json"
        try:
            self.manifest = deepcopy(_load_art_json(manifest_path))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot load video asset manifest: {manifest_path}") from exc
        if self.manifest.get("schema_version") != 1:
            raise ValueError("Unsupported video asset manifest schema")
        self._images = _ImageCache(16 * 1024 * 1024, 192)
        self._transforms = _ImageCache(16 * 1024 * 1024)
        # Colour-independent luminance/alpha atlas shared by all ghost colours.
        self._gold_sources = _ImageCache(8 * 1024 * 1024, 1024)
        self._player_transforms = _ImageCache(8 * 1024 * 1024)
        self._player_masks = _ImageCache(8 * 1024 * 1024, 8192)
        self._label_images = _ImageCache(2 * 1024 * 1024, 512)
        self._label_fonts = {}
        self._vectors = None
        # Enemy physics can be deliberately disabled for a diagnostic export.
        # Preserve their level artwork at the descriptor positions in that
        # case, since disabled native enemies have no state objects at all.
        enemy_kinds = {engine.OBJTYPE_TURRET: "turret",
                       engine.OBJTYPE_FLOORGUARD: "floorguard",
                       engine.OBJTYPE_HOMINGLAUNCHER: "homing"}
        self._frozen_enemies = []
        for spec in self.level.all_specs:
            kind = enemy_kinds.get(spec.obj_type)
            if spec.obj_type == engine.OBJTYPE_DRONE and len(spec.params) >= 5:
                kind = {0: "drone_zap", 1: "drone_laser", 2: "drone_chaingun"}.get(int(spec.params[4]))
            if kind:
                self._frozen_enemies.append({"kind": kind, "load_index": spec.load_index,
                    "x": spec.params[0], "y": spec.params[1], "parameters": spec.params})
        if _terrain_layers is None:
            self._background = Image.new("RGB", self.size, background)
            tile_geometry = tuple((cell.pos.x, cell.pos.y, cell.tile_id,
                                   cell.ctype, cell.signx, cell.signy, cell.sx,
                                   cell.sy, cell.xw, cell.yw)
                                  for col in self.level.tiles.grid for cell in col)
            terrain_key = (scale, tuple(terrain) if not isinstance(terrain, str) else terrain,
                           type(self.level.tiles), type(self.level.tiles).query_point, tile_geometry)
            self._tiles = _TERRAIN_CACHE.get(terrain_key)
            if self._tiles is None:
                self._tiles = self._terrain_layer(terrain)
                _TERRAIN_CACHE.put(terrain_key, self._tiles)
            else:
                self.stats["terrain_cache_hits"] += 1
        else:
            # Internal spawn seed: the parent has already rasterised immutable
            # geometry. Pillow pickles these layers once per worker, avoiding
            # repeated Python coverage sampling (particularly costly at scale4).
            # render() copies the background and only reads the terrain layer.
            if (not isinstance(_terrain_layers, (tuple, list))
                    or len(_terrain_layers) != 2
                    or any(not isinstance(layer, Image.Image) or layer.size != self.size
                           or layer.mode != mode for layer, mode in
                           zip(_terrain_layers, ("RGB", "RGBA")))):
                raise ValueError("worker terrain layers must be RGB/RGBA images matching the render size")
            self._background, self._tiles = _terrain_layers

    def _terrain_layer(self, color):
        """Rasterise each tile with the engine's exact solid-point predicate.

        Identical tile shapes share masks. Four-by-four coverage sampling
        smooths slopes/arcs without outlining tiles or exposing internal seams.
        This is done once, outside the per-frame rendering path.
        """
        image = self._Image.new("RGBA", self.size)
        masks = {}
        side = 24 * self.scale
        for column in self.level.tiles.grid:
            for cell in column:
                if cell.tile_id == 0:
                    continue
                shape = (self.scale, cell.tile_id, cell.ctype, cell.signx, cell.signy,
                         cell.sx, cell.sy, cell.xw, cell.yw,
                         type(self.level.tiles).query_point)
                # Preserve the historical once-per-shape rasterisation inside
                # each map. Across maps include the first cell's position so
                # custom floating-point geometry uses identical sample points.
                shared_shape = shape + (cell.pos.x, cell.pos.y)
                mask = masks.get(shape)
                if mask is None:
                    mask = _TILE_MASK_CACHE.get(shared_shape)
                if mask is None:
                    if cell.tile_id == 1:
                        mask = self._Image.new("L", (side, side), 255)
                    else:
                        x0, y0 = cell.pos.x - 12, cell.pos.y - 12
                        samples = 4
                        high_side = side * samples
                        data = bytes(255 if self.level.tiles.query_point(
                            x0 + (px + .5) / (self.scale * samples),
                            y0 + (py + .5) / (self.scale * samples), cell) else 0
                            for py in range(high_side) for px in range(high_side))
                        mask = self._Image.frombytes("L", (high_side, high_side), data)
                        mask = mask.resize((side, side), self._Image.Resampling.BOX)
                    _TILE_MASK_CACHE.put(shared_shape, mask)
                masks[shape] = mask
                # Store straight-alpha terrain. Pasting RGB through a mask
                # onto transparent black would premultiply its colour twice
                # when this layer is later composited over the scene.
                tile = self._Image.new("RGBA", (side, side), color)
                tile.putalpha(mask)
                image.paste(tile, (round((cell.pos.x - 12) * self.scale),
                                   round((cell.pos.y - 12) * self.scale)))
        return image

    def _asset_info(self, name, frame=None):
        if name.startswith("object:"):
            clip = name.partition(":")[2]
            info = self.manifest.get("object_animations", {}).get("clips", {}).get(clip, {}).get("frames", {}).get(str(frame))
            if info is None:
                raise ValueError(f"Object animation {clip!r} frame {frame!r} is missing from the asset pack")
            return info
        if name.startswith("particle:"):
            symbol = name.partition(":")[2]
            info = self.manifest.get("particles", {}).get("clips", {}).get(symbol, {}).get("frames", {}).get(str(frame))
            if info is None:
                raise ValueError(f"Particle sprite {symbol!r} frame {frame!r} is missing from the asset pack")
            return info
        if name == "ninja":
            frames = self.manifest.get("ninja", {}).get("frames", {})
            info = frames.get(str(frame))
            if info is None:
                raise ValueError(f"Ninja sprite frame {frame!r} is missing from the asset pack")
            return info
        return self.manifest.get("objects", {}).get(name)

    def _image(self, info):
        name = info["file"]
        cached = self._images.get(name)
        if cached is not None:
            return cached
        path = (self.assets_path / name).resolve()
        if not path.is_relative_to(self.assets_path.resolve()):
            raise ValueError("Asset paths must stay inside the asset directory")
        try:
            with self._Image.open(path) as loaded:
                result = loaded.convert("RGBA")
        except OSError as exc:
            raise ValueError(f"Cannot load video sprite {path}") from exc
        self._images.put(name, result)
        return result

    def _sprite(self, canvas, name, x, y, *, frame=None, rotation=0., facing=1,
                width=None, height=None, scale_x=1., scale_y=1., tint=None,
                shaded_tint=False):
        info = self._asset_info(name, frame)
        if info is None:
            return False
        # Transforms depend only on the sprite, never its world position.
        if not all(math.isfinite(v) for v in (x, y, rotation, scale_x, scale_y)):
            return False
        if scale_x == 0 or scale_y == 0:
            return True
        player = name == "ninja"
        if player and self.render_quality == "fast":
            # Quantise the full device coordinate before splitting its integer
            # and fractional parts, so .99 correctly carries into the next
            # pixel (also for negative world coordinates).
            x = round(x * self.scale * 8) / (self.scale * 8)
            y = round(y * self.scale * 8) / (self.scale * 8)
            rotation = float(round(rotation) % 360)
        if "vector" in info:
            self._vector_sprite(canvas, info["vector"], x, y, rotation=rotation,
                                facing=facing, scale_x=scale_x, scale_y=scale_y,
                                tint=tint, player=player, shaded_tint=shaded_tint)
            return True
        key = (name, frame, rotation, facing, width, height, scale_x, scale_y,
               None if player else tint)
        if shaded_tint:
            key += ("shaded",)
        source_key = key[:-2] if shaded_tint and tint is not None else None
        cache = self._player_transforms if player else self._transforms
        cached = cache.get(key)
        if cached is None and source_key is not None:
            cached = self._shade_cached(source_key, tint)
            if cached is not None:
                cache.put(key, cached)
        if cached is None:
            source = self._image(info)
            if "crop" in info:
                # Legacy static exports have only crop bounds. They are
                # representative images, centred at their game object.
                source = source.crop(info["crop"])
                sx = (width or info.get("width", source.width)) * self.scale / source.width
                sy = (height or width or info.get("height", source.height)) * self.scale / source.height
                ox, oy = source.width / 2, source.height / 2
            else:
                ppu = info.get("pixels_per_unit", self.manifest.get("pixels_per_unit", 1))
                if ppu <= 0:
                    raise ValueError("Sprite pixels_per_unit must be positive")
                sx = sy = self.scale / ppu
                ox, oy = info.get("origin", (source.width / 2, source.height / 2))
            sx *= scale_x * (-1 if facing < 0 else 1)
            sy *= scale_y
            rad = math.radians(rotation)
            a, b = math.cos(rad) * sx, -math.sin(rad) * sy
            c, d = math.sin(rad) * sx, math.cos(rad) * sy
            corners = [(a * (px - ox) + b * (py - oy),
                        c * (px - ox) + d * (py - oy))
                       for px, py in ((0, 0), (source.width, 0),
                                      (0, source.height), source.size)]
            left = math.floor(min(p[0] for p in corners)) - 1
            top = math.floor(min(p[1] for p in corners)) - 1
            right = math.ceil(max(p[0] for p in corners)) + 1
            bottom = math.ceil(max(p[1] for p in corners)) + 1
            cacheable = right - left <= 2 * self.size[0] and bottom - top <= 2 * self.size[1]
            if not cacheable:
                # Extreme replay velocities can stretch dust enormously.
                # Rasterise only its visible part instead of allocating a
                # huge off-screen bitmap; this position-dependent crop is
                # deliberately excluded from the transform cache.
                px, py = round(x * self.scale), round(y * self.scale)
                left, top = max(left, -px), max(top, -py)
                right, bottom = min(right, self.size[0] - px), min(bottom, self.size[1] - py)
                if right <= left or bottom <= top:
                    return True
            det = a * d - b * c
            inverse = (d / det, -b / det, ox + (d * left - b * top) / det,
                       -c / det, a / det, oy + (-c * left + a * top) / det)
            sprite = source.transform((right - left, bottom - top),
                self._Image.Transform.AFFINE, inverse,
                resample=self._Image.Resampling.BICUBIC)
            if not player:
                sprite = self._tint_sprite(sprite, tint, shaded=shaded_tint,
                    source_key=source_key if cacheable else None, left=left, top=top)
            cached = sprite, left, top
            if cacheable:
                cache.put(key, cached)
        sprite, left, top = cached
        position = round(x * self.scale) + left, round(y * self.scale) + top
        if player and tint is not None:
            mask_entry = self._player_masks.get(key)
            if mask_entry is None:
                mask_entry = sprite.getchannel("A"), left, top
                # Position-dependent clipping must never enter this cache.
                if cache.get(key) is not None:
                    self._player_masks.put(key, mask_entry)
            mask = mask_entry[0]
            canvas.paste(tint, (*position, position[0]+mask.width,
                                position[1]+mask.height), mask)
        else:
            canvas.paste(sprite, position, sprite)
        return True

    def _shade_cached(self, source_key, tint):
        source = self._gold_sources.get(source_key)
        if source is None:
            original = self._transforms.get(source_key + (None,))
            if original is None:
                return None
            sprite, left, top = original
            source = sprite.convert("L"), sprite.getchannel("A"), left, top
            self._gold_sources.put(source_key, source)
        light, alpha, left, top = source
        channels = tuple(light.point(table) for table in _gold_tint_luts(tuple(tint)))
        return self._Image.merge("RGBA", (*channels, alpha)), left, top

    def _tint_sprite(self, sprite, tint, *, shaded=False, source_key=None, left=0, top=0):
        if tint is None:
            return sprite
        if shaded:
            light = sprite.convert("L")
            alpha = sprite.getchannel("A")
            if source_key is not None:
                self._gold_sources.put(source_key, (light, alpha, left, top))
            channels = tuple(light.point(table) for table in _gold_tint_luts(tuple(tint)))
            return self._Image.merge("RGBA", (*channels, alpha))
        result = self._Image.new("RGBA", sprite.size, tint)
        result.putalpha(sprite.getchannel("A"))
        return result

    def _vector_sprite(self, canvas, name, x, y, *, rotation, facing, scale_x, scale_y,
                       tint=None, player=False, shaded_tint=False):
        from nv14_vector import rasterize

        if self._vectors is None:
            info = self.manifest.get("vectors", {})
            path = (self.assets_path / info.get("file", "vectors.json")).resolve()
            if not path.is_relative_to(self.assets_path.resolve()):
                raise ValueError("Asset paths must stay inside the asset directory")
            try:
                pack = _load_art_json(path)
            except (OSError, ValueError) as exc:
                raise ValueError(f"Cannot load video vector artwork: {path}") from exc
            if pack.get("schema_version") != 1:
                raise ValueError("Unsupported vector artwork schema")
            self._vectors = pack["sprites"]
        if name not in self._vectors:
            raise ValueError(f"Vector sprite {name!r} is missing from the asset pack")
        px, py = math.floor(x*self.scale), math.floor(y*self.scale)
        phase = (round(x*self.scale-px, 8), round(y*self.scale-py, 8))
        key = ("vector", name, rotation, facing, scale_x, scale_y, phase,
               None if player else tint)
        if shaded_tint:
            key += ("shaded",)
        source_key = key[:-2] if shaded_tint and tint is not None else None
        mask_only = player and tint is not None
        cache = (self._player_masks if mask_only else self._player_transforms
                 if player else self._transforms)
        cached = cache.get(key)
        if cached is None and source_key is not None:
            cached = self._shade_cached(source_key, tint)
            if cached is not None:
                cache.put(key, cached)
        if cached is None and mask_only:
            # A primary rendered earlier already contains this exact coverage.
            artwork = self._player_transforms.get(key)
            if artwork is not None:
                cached = artwork[0].getchannel("A"), artwork[1], artwork[2]
                cache.put(key, cached)
        if cached is None:
            rad = math.radians(rotation)
            sx = self.scale * scale_x * (-1 if facing < 0 else 1)
            sy = self.scale * scale_y
            transform = (math.cos(rad)*sx, -math.sin(rad)*sy,
                         math.sin(rad)*sx, math.cos(rad)*sy)
            art = self._vectors[name]
            x0, y0, x1, y1 = art["bounds"]
            a, b, c, d = transform
            width = abs(a)*(x1-x0) + abs(b)*(y1-y0)
            height = abs(c)*(x1-x0) + abs(d)*(y1-y0)
            cacheable = width <= 2*self.size[0] and height <= 2*self.size[1]
            clip = None if cacheable else (-px, -py, self.size[0]-px, self.size[1]-py)
            if mask_only:
                sprite, left, top = rasterize(art, transform, phase, clip, alpha_only=True)
            else:
                sprite, left, top = rasterize(art, transform, phase, clip)
                sprite = self._tint_sprite(sprite, tint, shaded=shaded_tint,
                    source_key=source_key if cacheable else None, left=left, top=top)
            cached = sprite, left, top
            if cacheable:
                cache.put(key, cached)
        sprite, left, top = cached
        if mask_only:
            canvas.paste(tint, (px+left, py+top, px+left+sprite.width,
                                py+top+sprite.height), sprite)
        else:
            canvas.paste(sprite, (px+left, py+top), sprite)

    def _line(self, canvas, points, fill, width=1):
        if not all(math.isfinite(v) for p in points for v in p):
            return
        points = [(round(x * self.scale), round(y * self.scale)) for x, y in points]
        width = max(1, round(width * self.scale))
        if hasattr(canvas, "commands"):
            canvas.line(points, fill, width)
        else:
            self._ImageDraw.Draw(canvas).line(points, fill=fill, width=width)

    def _circle(self, canvas, x, y, radius, fill=None, outline=None, width=1):
        s = self.scale
        box = tuple(round(v * s) for v in (x-radius, y-radius, x+radius, y+radius))
        width = max(1, round(width*s))
        if hasattr(canvas, "commands"):
            canvas.ellipse(box, fill, outline, width)
        else:
            self._ImageDraw.Draw(canvas).ellipse(box, fill=fill, outline=outline, width=width)

    def _animated_sprite(self, canvas, sprite):
        if sprite is not None and sprite.visible:
            self._sprite(canvas, "object:" + sprite.clip, sprite.x, sprite.y,
                         frame=sprite.frame, rotation=sprite.rotation,
                         scale_x=sprite.scale_x, scale_y=sprite.scale_y)

    def _object(self, canvas, obj, *, particle_effects=False, object_visual=None):
        if object_visual is not None:
            # A collected gold object is removed from gameplay immediately,
            # while its independent MovieClip continues the collection tween.
            self._animated_sprite(canvas, object_visual.body)
            self._animated_sprite(canvas, object_visual.trigger)
            if object_visual.eye_rotation is not None and object_visual.body.visible:
                eye = "drone_chaingun_eye" if obj["kind"] == "drone_chaingun" else "drone_eye"
                self._sprite(canvas, eye, object_visual.body.x, object_visual.body.y,
                             rotation=object_visual.eye_rotation)
            beam = getattr(object_visual, "beam", None)
            if beam is not None and beam.visible:
                self._line(canvas, [beam.start, beam.end], beam.color, beam.width)
            self._animated_sprite(canvas, object_visual.blast)
            # With particles disabled preserve the existing instantaneous
            # chaingun ray visual; object clips and eye easing are independent.
            if obj.get("shot_visible") and not particle_effects:
                self._line(canvas, [(obj["x"], obj["y"]), obj.get("beam_end", obj["shot_target"])], "#ede5b2", 1)
            return
        if not obj.get("visible", True):
            return
        kind, x, y = obj["kind"], obj["x"], obj["y"]
        if not (math.isfinite(x) and math.isfinite(y)):
            return
        p = obj.get("parameters", ())
        if kind in ("gold", "mine"):
            size = 6 if kind == "gold" else 8
            if not self._sprite(canvas, kind, x, y, width=size):
                self._circle(canvas, x, y, size / 2, "#e4c929" if kind == "gold" else "#bc2940")
        elif kind == "exit_door":
            opened = obj.get("is_open", False)
            name = "exit_open" if opened else "exit"
            if not self._sprite(canvas, name, x, y, width=24):
                self._circle(canvas, x, y, 11, "#525261", "#e4d455" if opened else "#1d1d25", 2)
        elif kind == "exit_switch":
            name = "exit_switch_open" if obj.get("is_open") else "exit_switch"
            if not self._sprite(canvas, name, x, y, width=12, height=7.5):
                self._circle(canvas, x, y, 5, "#cabf56" if obj.get("is_open") else "#414149")
        elif kind == "oneway":
            dx, dy = obj.get("direction", (0, -1))
            if len(p) > 2:
                dx, dy = ((1, 0), (0, 1), (-1, 0), (0, -1))[int(p[2]) % 4]
            cx, cy = x + dx * 12, y + dy * 12
            rotation = math.degrees(math.atan2(dy, dx)) + 90
            if not self._sprite(canvas, "oneway", x, y, rotation=rotation):
                self._line(canvas, [(cx-dy*12, cy+dx*12), (cx+dy*12, cy-dx*12)], "#202028", 1.5)
        elif kind == "launch":
            dx, dy = p[2:4] if len(p) >= 4 else (0, -1)
            rotation = math.degrees(math.atan2(dy, dx)) + 90
            if not self._sprite(canvas, "launchpad", x, y, width=15, height=5, rotation=rotation):
                self._line(canvas, [(x-dy*10, y+dx*10), (x+dy*10, y-dx*10)], "#747c40", 4)
        elif kind == "testdoor":
            dx, dy = obj.get("door_x", x), obj.get("door_y", y)
            horizontal = obj.get("horizontal", False)
            if not obj.get("is_open", False):
                ends = [(dx-12, dy), (dx+12, dy)] if horizontal else [(dx, dy-12), (dx, dy+12)]
                self._line(canvas, ends, "#373742", 2)
            if obj.get("is_locked") or obj.get("is_trap"):
                name = "door_switch_trap" if obj.get("is_trap") else "door_switch"
                if not obj.get("trigger_active", True):
                    name += "_open"
                if not self._sprite(canvas, name, x, y, width=7.5):
                    self._circle(canvas, x, y, 3, "#94949d", "#555563")
        elif kind in ("bounce", "thwomp", "floorguard"):
            name, size = {"bounce": ("bounce_block", 19.2),
                          "thwomp": ("thwump", 18), "floorguard": ("floorguard", 12)}[kind]
            rotation = 0
            if kind == "thwomp":
                dx, dy = obj.get("direction", (0, 1))
                rotation = math.degrees(math.atan2(dy, dx)) - 90
            elif kind == "floorguard" and obj.get("chasing"):
                name = "floorguard_active"
            self._sprite(canvas, name, x, y, width=size, rotation=rotation)
        elif kind.startswith("drone_"):
            name = kind
            if kind == "drone_zap" and len(p) >= 6 and p[5]:
                name = "drone_chase_active" if obj.get("chasing") else "drone_chase_idle"
            elif kind != "drone_zap" and obj.get("mode") in (1, 2):
                name += "_prefire" if obj["mode"] == 1 else "_firing"
            if not self._sprite(canvas, name, x, y, width=18):
                self._sprite(canvas, "drone", x, y, width=18)
            dx, dy = obj.get("direction", (1, 0))
            if obj.get("mode", 0) in (1, 2, 3):
                view = obj.get("view", (x+dx, y+dy))
                dx, dy = view[0] - x, view[1] - y
            length = math.hypot(dx, dy)
            if length:
                eye = "drone_chaingun_eye" if kind == "drone_chaingun" else "drone_eye"
                if not self._sprite(canvas, eye, x, y, rotation=math.degrees(math.atan2(dy, dx))):
                    self._circle(canvas, x+dx/length*4, y+dy/length*4, 2, "#292934")
            if obj.get("beam_visible"):
                self._line(canvas, [obj["beam_start"], obj["beam_end"]], "#e64646", 2)
            if obj.get("shot_visible") and not particle_effects:
                # view/beam_end is QueryRayObj's actual hit position; the
                # intended shot_target can lie beyond an intervening wall.
                self._line(canvas, [(x, y), obj.get("beam_end", obj["shot_target"])], "#ede5b2", 1)
        elif kind in ("homing", "turret"):
            name = "turret"
            if kind == "homing":
                name = "homing_launcher_active" if obj.get("mode", 0) > 0 else "homing_launcher"
            self._sprite(canvas, name, x, y, width=12)

    def _foreground_weapons(self, canvas, objects, object_visuals=None):
        # Launchers/turrets themselves live in LAYER_WALLS; their rocket and
        # crosshair MovieClips live in LAYER_OBJECTS, above the other walls.
        for obj in objects:
            visual = (object_visuals or {}).get(obj.get("id"))
            if visual is not None:
                self._animated_sprite(canvas, visual.rocket)
                self._animated_sprite(canvas, visual.crosshair)
                continue
            if obj["kind"] == "homing" and obj.get("rocket_visible"):
                x, y = obj["rocket_x"], obj["rocket_y"]
                rotation = obj.get("rocket_rotation_deg", 0)
                if not self._sprite(canvas, "rocket", x, y, rotation=rotation):
                    dx, dy = obj.get("rocket_direction", (1, 0))
                    self._line(canvas, [(x-dx*4, y-dy*4), (x+dx*4, y+dy*4)], "#c3303e", 3)
            if obj["kind"] == "turret" and obj.get("crosshair_visible"):
                x, y = obj["aim"]
                color = "#b1303a" if obj.get("mode") == 2 else "#636371"
                self._circle(canvas, x, y, 7, outline=color)
                for dx, dy in ((1, 0), (0, 1)):
                    self._line(canvas, [(x-dx*10, y-dy*10), (x+dx*10, y+dy*10)], color)

    def _particles(self, canvas, particles, layer):
        for p in particles:
            if p.layer != layer:
                continue
            info = self._asset_info("particle:" + p.symbol, p.frame)
            if "line" in info:
                # Flash hairlines survive zero-height/width transforms. The
                # vector path also prevents diagonal gauss trails getting
                # thicker as the target distance increases.
                line = info["line"]
                rad = math.radians(p.rotation)
                c, s = math.cos(rad), math.sin(rad)
                points = [(p.x + c*x*p.scale_x - s*y*p.scale_y,
                           p.y + s*x*p.scale_x + c*y*p.scale_y)
                          for x, y in line["points"]]
                if line.get("opacity", 1) < 1:
                    if not all(math.isfinite(v) for point in points for v in point):
                        continue
                    device = [(round(x*self.scale), round(y*self.scale)) for x, y in points]
                    # Retain only the affected pixels, but rasterise in the
                    # original viewport before cropping. Pillow widelines can
                    # change edge coverage when their coordinates are shifted.
                    padding = self.scale + 1
                    left = max(0, min(x for x, _ in device)-padding)
                    top = max(0, min(y for _, y in device)-padding)
                    right = min(self.size[0], max(x for x, _ in device)+padding)
                    bottom = min(self.size[1], max(y for _, y in device)+padding)
                    if left >= right or top >= bottom:
                        continue
                    overlay = self._Image.new("RGBA", self.size)
                    color = line["color"].lstrip("#")
                    rgba = tuple(int(color[i:i+2], 16) for i in (0, 2, 4)) + (round(255*line["opacity"]),)
                    self._ImageDraw.Draw(overlay).line(device, fill=rgba, width=self.scale)
                    overlay = overlay.crop((left, top, right, bottom))
                    canvas.paste(overlay, (left, top), overlay)
                else:
                    self._line(canvas, points, line["color"])
            else:
                self._sprite(canvas, "particle:" + p.symbol, p.x, p.y, frame=p.frame,
                             rotation=p.rotation, scale_x=p.scale_x, scale_y=p.scale_y)

    def _player(self, canvas, visual, *, color=None):
        if visual.get("visible", True) and visual.get("frame") is not None:
            x, y = visual["x"], visual["y"]
            if all(math.isfinite(v) for v in (x, y, visual.get("rotation_deg", 0))):
                self._sprite(canvas, "ninja", x, y, frame=visual["frame"],
                             rotation=visual.get("rotation_deg", 0),
                             facing=visual.get("facing", 1), tint=color)

    def _label_sprite(self, text, color, size, *, max_width=MAP_SIZE[0]-4, stroke_width=1):
        # The original embedded font covers Western text. Unsupported glyphs
        # become '?' rather than silently switching to a different GUI font.
        text = text.encode("cp1252", errors="replace").decode("cp1252")
        key = (text, color, size, max_width, stroke_width)
        sprite = self._label_images.get(key)
        if sprite is not None:
            return sprite
        font = self._label_fonts.get(size)
        if font is None:
            from PIL import ImageFont
            path = Path(__file__).resolve().parent / "nv14_assets" / "fonts" / "n_gui.ttf"
            try:
                font = ImageFont.truetype(str(path), size=size, layout_engine=ImageFont.Layout.BASIC)
            except OSError as exc:
                raise ValueError(f"Cannot load original N GUI label font: {path}") from exc
            self._label_fonts[size] = font
        # Keep labels inside the stage, even at a large user-selected font size.
        original = text
        while True:
            left, top, right, bottom = font.getbbox(text)
            if right - left + 2 <= max_width:
                break
            if not original:
                raise ValueError("static labels do not fit the picture; reduce label_size "
                                 "or leave more labels empty")
            original = original[:-1]
            text = original.rstrip() + "..."
        sprite = self._Image.new("RGBA", (max(1, right-left) + 2, max(1, bottom-top) + 2))
        self._ImageDraw.Draw(sprite).text((1-left, 1-top), text, font=font,
            fill=color + (255,), stroke_width=stroke_width, stroke_fill=BACKGROUND + (255,))
        # Rasterise on the original pixel-font grid and enlarge exactly. This
        # avoids blurred glyphs and colour fringes at larger video scales.
        if self.scale != 1:
            sprite = sprite.resize((sprite.width*self.scale, sprite.height*self.scale),
                                   self._Image.Resampling.NEAREST)
        self._label_images.put(key, sprite)
        return sprite

    def _level_credit(self, canvas, text):
        # NinjaGui places guiLevelNameMC at (396, 580), above the bottom
        # border. Keep the original GUI font crisp and the credit above tiles.
        sprite = self._label_sprite(text, (0, 0, 0), 8,
                                    max_width=MAP_SIZE[0]-48, stroke_width=0)
        canvas.paste(sprite, ((self.size[0]-sprite.width)//2, 580*self.scale), sprite)

    def _static_player_labels(self, canvas, players, size):
        # A single cached transparent legend keeps layout and text rasterisation
        # out of the per-frame path, including full redraws and worker renders.
        entries = []
        for _, _, text, color in players:
            validate_player_label(text)
            if text and text.strip():
                entries.append((text, color))
        if not entries:
            return
        key = ("legend", tuple(entries), size)
        legend = self._label_images.get(key)
        margin, gap = 32, 12
        if legend is None:
            available_width = MAP_SIZE[0] - 2*margin
            sprites = [self._label_sprite(text, color, size, max_width=available_width)
                       for text, color in entries]
            row_height = max(sprite.height for sprite in sprites) + 4*self.scale
            rows = max(1, ((MAP_SIZE[1]-2*margin)*self.scale + 4*self.scale) // row_height)
            columns = (len(entries)+rows-1) // rows
            column_width = (available_width-gap*(columns-1)) // columns
            if column_width <= 0:
                raise ValueError("static labels do not fit the picture; reduce label_size "
                                 "or leave more labels empty")
            if columns > 1:
                sprites = [self._label_sprite(text, color, size, max_width=column_width)
                           for text, color in entries]
            positions = [((i//rows)*(column_width+gap)*self.scale, (i%rows)*row_height)
                         for i in range(len(sprites))]
            width = max(x+sprite.width for (x, y), sprite in zip(positions, sprites))
            height = max(y+sprite.height for (x, y), sprite in zip(positions, sprites))
            legend = self._Image.new("RGBA", (width, height))
            for position, sprite in zip(positions, sprites):
                # Copy RGBA directly; using the sprite as a mask here would
                # apply antialiasing twice when compositing the legend later.
                legend.paste(sprite, position)
            self._label_images.put(key, legend)
        canvas.paste(legend, (margin*self.scale, margin*self.scale), legend)

    def _player_labels(self, canvas, capture, players, size):
        from nv14_render_commands import intersects

        occupied = []
        padding, gap = 2*self.scale, 2*self.scale
        for key, visual, text, color in players:
            validate_player_label(text)
            if not text or not text.strip() or not visual.get("visible", True) or visual.get("frame") is None:
                continue
            x, y = visual["x"], visual["y"]
            if not all(math.isfinite(v) for v in (x, y, visual.get("rotation_deg", 0))):
                continue
            # Do not leave a floating caption at the edge for an off-stage ninja.
            if not (-10 <= x <= MAP_SIZE[0]+10 and -10 <= y <= MAP_SIZE[1]+10):
                continue
            sprite = self._label_sprite(text, color, size)
            left = max(padding, min(self.size[0]-padding-sprite.width,
                                    round(x*self.scale - sprite.width/2)))
            preferred = max(padding, min(self.size[1]-padding-sprite.height,
                                         round((y-15)*self.scale)-sprite.height))
            top = preferred
            column = sorted((other for other in occupied
                             if left < other[2] and other[0] < left+sprite.width),
                            key=lambda other: other[1])
            # Prefer stacking upwards. Near the upper edge, try downwards.
            # If the entire column is occupied, keep following the player;
            # no finite viewport can separate an unlimited number of captions.
            for direction in (-1, 1):
                top = preferred
                # Sweep each overlapping column once per direction, rather
                # than repeatedly rescanning every caption in a large crowd.
                for other in (reversed(column) if direction < 0 else column):
                    box = (left, top, left+sprite.width, top+sprite.height)
                    if intersects(box, other):
                        top = (other[1]-sprite.height-gap if direction < 0 else other[3]+gap)
                if padding <= top <= self.size[1]-padding-sprite.height:
                    break
            else:
                top = preferred
            box = (left, top, left+sprite.width, top+sprite.height)
            occupied.append(box)
            capture(("label", key), (text, color, size, box),
                    lambda: canvas.paste(sprite, (left, top), sprite))

    def _render_full(self, scene, *, particles=None, object_visuals=None,
                     secondary_players=(), show_primary_player=True,
                     secondary_gold=(),
                     primary_label=None, label_size=8, label_position="follow",
                     level_credit=None, _canvas=None):
        """Return an RGB frame from optional immutable cosmetic draw records.

        ``particles`` comes from ParticleSystem; ``object_visuals`` from
        ObjectVisualSystem. Repeated renders cannot age clips or turn eyes.
        Omit both for the v4.04 representative-art rendering behaviour.
        ``secondary_players`` contains visual_snapshot() dictionaries with an
        optional RGB ``color`` tuple (default: darker blue). Only their ninja
        artwork is used. The primary is drawn on top; all players remain below
        foreground particles and tiles. Hide the primary during a delayed start
        with ``show_primary_player=False``; its world is still rendered.
        Optional ``primary_label`` and each secondary's ``label`` follow their
        visible player in the original GUI font. Text is drawn above the world
        so terrain cannot obscure it; nearby labels are stacked when possible.
        ``label_position='top-left'`` instead shows a fixed legend, primary
        first, regardless of player visibility. Supply hidden secondary records
        too when a custom loop delays starts and wants a stable complete legend.
        """
        validate_player_label(primary_label)
        validate_label_size(label_size)
        validate_label_position(label_position)
        secondary_players = tuple(secondary_players)
        canvas = self._background.copy() if _canvas is None else _canvas
        def capture(key, state, draw):
            if _canvas is None:
                draw()
            else:
                canvas.capture_signature(key, state, draw)
        particle_effects = particles is not None
        particles = tuple(particles) if particle_effects else ()
        object_visuals = {v.id: v for v in object_visuals} if object_visuals is not None else {}
        objects = scene.get("objects", ())
        if scene.get("simulate_enemies") is False:
            present = {obj["load_index"] for obj in objects}
            objects = [*objects, *(obj for obj in self._frozen_enemies
                                   if obj["load_index"] not in present)]
        # MovieClip depths follow descriptor construction, not native runtime
        # categories. The native exit is split into switch/door records while
        # the source creates its door first, then its switch at the next depth.
        layout = tuple((obj.get("load_index", obj.get("id", 0)),
                        int(obj["kind"] == "exit_switch")) for obj in objects)
        if layout != self._object_layout:
            self._object_layout = layout
            self._object_indices = sorted(range(len(objects)), key=layout.__getitem__)
        else:
            self.stats["object_order_cache_hits"] += 1
        objects = [objects[index] for index in self._object_indices]
        for index, obj in enumerate(objects):
            if obj["kind"] in _WALL_KINDS:
                ov = object_visuals.get(obj.get("id"))
                capture(("wall", index), _object_signature(obj, particle_effects, ov),
                        lambda: self._object(canvas, obj, particle_effects=particle_effects,
                                             object_visual=ov))
        for index, particle in enumerate(particles):
            if particle.layer == "back":
                capture(("back", index), particle,
                        lambda: self._particles(canvas, (particle,), "back"))
        for index, obj in enumerate(objects):
            ov = object_visuals.get(obj.get("id"))
            if obj["kind"] not in _WALL_KINDS:
                if _hidden_gold(obj, ov, particle_effects):
                    continue
                key = ("primary-gold" if obj["kind"] == "gold" else "object", index)
                capture(key, _object_signature(obj, particle_effects, ov),
                        lambda: self._object(canvas, obj, particle_effects=particle_effects,
                                             object_visual=ov))
            else:
                capture(("object", index), _weapon_signature(obj, ov),
                        lambda: self._foreground_weapons(canvas, (obj,), object_visuals))
        for gold in secondary_gold:
            def draw_gold(gold=gold):
                if gold.frame is None:
                    self._sprite(canvas, "gold", gold.x, gold.y, width=6,
                                 tint=gold.color, shaded_tint=True)
                else:
                    self._sprite(canvas, "object:gold", gold.x, gold.y,
                                 frame=gold.frame, tint=gold.color, shaded_tint=True)
            capture(("secondary-gold", *gold.key), gold, draw_gold)
        visual = scene.get("visual")
        if visual is None:
            raise ValueError("Scene has no player visuals; enable_visuals() before replaying")
        for index, secondary in enumerate(reversed(tuple(secondary_players))):
            color = tuple(secondary.get("color", SECONDARY_PLAYER_COLOR))
            if len(color) != 3 or any(isinstance(c, bool) or not isinstance(c, int)
                                      or not 0 <= c <= 255 for c in color):
                raise ValueError("secondary player color must contain three RGB integers from 0 to 255")
            capture(("secondary", index), (_player_signature(secondary), color),
                    lambda: self._player(canvas, secondary, color=color))
        if show_primary_player:
            capture(("primary", 0), _player_signature(visual), lambda: self._player(canvas, visual))
        for index, particle in enumerate(particles):
            if particle.layer == "front":
                capture(("front", index), particle,
                        lambda: self._particles(canvas, (particle,), "front"))
        capture(("terrain", 0), id(self._tiles),
                lambda: canvas.paste(self._tiles, (0, 0), self._tiles))
        if primary_label or any(player.get("label") for player in secondary_players):
            labels = ([("primary", visual, primary_label, (0, 0, 0))]
                      if (show_primary_player or label_position == "top-left") and primary_label else [])
            labels.extend((index, secondary, secondary.get("label"),
                           tuple(secondary.get("color", SECONDARY_PLAYER_COLOR)))
                          for index, secondary in enumerate(secondary_players))
            if label_position == "top-left":
                signature = (label_size, tuple((text, color) for _, _, text, color in labels))
                capture(("label-legend", 0), signature,
                        lambda: self._static_player_labels(canvas, labels, label_size))
            else:
                self._player_labels(canvas, capture, labels, label_size)
        if level_credit:
            capture(("level-credit", 0), level_credit,
                    lambda: self._level_credit(canvas, level_credit))
        return canvas


    def reset_frame_cache(self):
        """Discard replay history while retaining bounded artwork/preparation caches.

        Statistics remain cumulative so a reusable encoder can report deltas.
        """
        self._previous_canvas = None
        self._previous_commands = ()
        self._command_groups = {}
        self._command_index = None
        self._object_layout = None
        self._object_indices = ()
        if hasattr(self, "_gold_batch"):
            self._gold_batch.clear()

    def _render_retained(self, scene, **options):
        from nv14_render_commands import CommandIndex, DrawList, dirty_regions
        from nv14_render_gold import GoldBatchRenderer
        if not self.incremental:
            self.stats["full_frames"] += 1
            self.stats["drawn_pixels"] += self.size[0] * self.size[1]
            return self._render_full(scene, **options)
        drawlist = DrawList(self.size, self._command_groups, self.stats)
        self._render_full(scene, _canvas=drawlist, **options)
        commands = drawlist.commands
        if self._command_index is None:
            self._command_index = CommandIndex(self.size)
        changes = self._command_index.update(commands)
        if not hasattr(self, "_gold_batch"):
            self._gold_batch = GoldBatchRenderer()
        regions = (None if self._previous_canvas is None else
                   dirty_regions(self._previous_commands, commands, self.size,
                                 changes=changes, index=self._command_index))
        if regions is None:
            canvas = self._background.copy()
            self._gold_batch.draw(canvas, commands)
            self.stats["full_frames"] += 1
            self.stats["drawn_pixels"] += self.size[0] * self.size[1]
        else:
            canvas = self._previous_canvas
            for rect in regions:
                patch = self._background.crop(rect)
                self._gold_batch.draw(patch, self._command_index.query(rect), rect[:2])
                canvas.paste(patch, rect[:2])
                self.stats["drawn_pixels"] += (rect[2]-rect[0])*(rect[3]-rect[1])
            self.stats["dirty_frames" if regions else "unchanged_frames"] += 1
        self._previous_canvas = canvas
        self._previous_commands = commands
        self._command_groups = drawlist.groups
        return canvas

    def render(self, scene, *, particles=None, object_visuals=None,
               secondary_players=(), show_primary_player=True,
               secondary_gold=(),
               primary_label=None, label_size=8, label_position="follow", level_credit=None):
        """Return an independent RGB image; unchanged scene regions are reused.

        Accepts the same immutable cosmetic records as previous releases.
        Players remain below foreground particles and terrain; optional labels
        are overlaid above them. ``level_credit`` adds a fixed GUI-font caption
        at the bottom of the stage, independently of player visibility. Use
        ``incremental=False`` when constructing the renderer to force complete
        redraws for diagnostics. No rendering path advances gameplay/cosmetics.
        """
        canvas = self._render_retained(scene, particles=particles,
            secondary_gold=secondary_gold,
            object_visuals=object_visuals, secondary_players=secondary_players,
            show_primary_player=show_primary_player, primary_label=primary_label,
            label_size=label_size, label_position=label_position, level_credit=level_credit)
        # The retained canvas is private: callers may mutate or keep each
        # returned image without affecting subsequent frames.
        return canvas.copy() if self.incremental else canvas

    def render_into(self, scene, buffer, **options):
        """Write packed RGB into a caller-owned contiguous writable buffer.

        Pillow's raw encoder emits bounded chunks directly into the supplied
        shared-memory slot, avoiding an independent RGB image and a full-frame
        intermediate bytes allocation. The buffer must be exactly frame-sized.
        """
        view = memoryview(buffer)
        try:
            if view.readonly or not view.c_contiguous:
                raise ValueError("frame buffer must be writable and C-contiguous")
            byteview = view.cast("B")
            try:
                if byteview.nbytes != self.size[0] * self.size[1] * 3:
                    raise ValueError("frame buffer size must match the RGB frame size")
                canvas = self._render_retained(scene, **options)
                encoder = self._Image._getencoder("RGB", "raw", ("RGB", 0, 1))
                encoder.setimage(canvas.im, (0, 0) + canvas.size)
                position = 0
                try:
                    while True:
                        _, status, data = encoder.encode(max(256 * 1024, self.size[0] * 4))
                        byteview[position:position+len(data)] = data
                        position += len(data)
                        if status:
                            if status < 0:
                                raise RuntimeError(f"RGB frame packing failed with code {status}")
                            break
                finally:
                    encoder.cleanup()
                if position != byteview.nbytes:
                    raise RuntimeError("RGB frame packing returned an incomplete frame")
            finally:
                byteview.release()
        finally:
            view.release()

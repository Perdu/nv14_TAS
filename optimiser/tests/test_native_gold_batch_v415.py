"""Ordered batches must match Pillow's per-sprite clipping and integer blend."""
import random
import sys

import pytest

Image = pytest.importorskip("PIL.Image")
from nv14_render_commands import Command
from nv14_render_gold import GoldBatchRenderer


def command(image, x, y, index, layer="secondary-gold"):
    result = Command("paste", (image, (x, y), image),
                     (x, y, x + image.width, y + image.height))
    result.key = ((layer, index), 0)
    return result


def random_image(rng, mode, size):
    return Image.frombytes(mode, size, rng.randbytes(size[0] * size[1] * len(mode)))


def test_native_blending_matches_all_alpha_values_and_overlapping_order():
    native = pytest.importorskip("_nv14_render_native")
    rng = random.Random(415)
    background = random_image(rng, "RGB", (256, 9))
    original = background.tobytes()
    records = []
    for row in range(9):
        pixels = bytes(channel for alpha in range(256)
                       for channel in (rng.randrange(256), rng.randrange(256), rng.randrange(256), alpha))
        sprite = Image.frombytes("RGBA", (256, 1), pixels)
        records.append((pixels, 256, 1, -row, row))
        background.paste(sprite, (-row, row), sprite)
    # A second pass overlaps every alpha value and exercises cumulative rounding.
    for pixels, width, height, x, y in records[::-1]:
        sprite = Image.frombytes("RGBA", (width, height), pixels)
        background.paste(sprite, (x + 3, y), sprite)
    records.extend((pixels, width, height, x + 3, y)
                   for pixels, width, height, x, y in records[::-1])
    assert native.composite_rgba(256, 9, original, records) == background.tobytes()


@pytest.mark.parametrize("origin", [(0, 0), (101, -87)])
def test_native_clipping_random_sprites_and_patch_origins(origin):
    native = pytest.importorskip("_nv14_render_native")
    rng = random.Random(414)
    background = random_image(rng, "RGB", (31, 23))
    original = background.tobytes()
    records = []
    for _ in range(60):
        size = (rng.randrange(1, 26), rng.randrange(1, 20))
        sprite = random_image(rng, "RGBA", size)
        x, y = rng.randrange(-35, 50), rng.randrange(-25, 35)
        background.paste(sprite, (x, y), sprite)
        records.append((sprite.tobytes(), *size, x + origin[0], y + origin[1]))
    assert native.composite_rgba(31, 23, original, records, *origin) == background.tobytes()


def test_batch_preserves_interleaved_non_gold_paint_and_clipped_patch():
    pytest.importorskip("_nv14_render_native")
    rng = random.Random(415)
    commands = []
    for group in range(3):
        commands.extend(command(random_image(rng, "RGBA", (9, 7)),
                                10 + index * 3, 7 + group, group * 20 + index)
                        for index in range(20))
        commands.append(command(random_image(rng, "RGBA", (9, 7)), 40, 10,
                                group, layer="player"))
    expected = Image.new("RGB", (65, 12), (23, 67, 130))
    actual = expected.copy()
    for item in commands:
        item.draw(expected, (12, 9))
    batch = GoldBatchRenderer()
    batch.draw(actual, iter(commands), (12, 9))
    assert actual.tobytes() == expected.tobytes()
    assert batch.batches == 3
    assert batch.pastes == 60
    # Retained commands and sprite buffers are reused on the second frame.
    image_cache = tuple(batch._images.values())
    batch.draw(actual, commands, (12, 9))
    assert tuple(batch._images.values()) == image_cache


def test_small_sparse_and_missing_native_groups_use_pillow(monkeypatch):
    sprite = Image.new("RGBA", (4, 4), (221, 41, 78, 123))
    commands = [command(sprite, index * 30, index % 2 * 70, index) for index in range(20)]
    expected = Image.new("RGB", (610, 90), (41, 69, 91))
    actual = expected.copy()
    for item in commands:
        item.draw(expected)
    batch = GoldBatchRenderer()
    batch.draw(actual, commands)
    assert actual.tobytes() == expected.tobytes()
    assert batch.batches == 0
    monkeypatch.setitem(sys.modules, "_nv14_render_native", None)
    fallback = GoldBatchRenderer()
    assert fallback._composite is None
    fallback.draw(actual, commands[:2])
    for item in commands[:2]:
        item.draw(expected)
    assert actual.tobytes() == expected.tobytes()


def test_native_validates_buffers_sizes_and_coordinate_overflow():
    native = pytest.importorskip("_nv14_render_native")
    cases = [(-1, 1, b"", []), (1, 1, b"", []),
             (1, 1, b"abc", [(b"123", 1, 1, 0, 0)]),
             (1, 1, b"abc", [(b"1234", -1, -1, 0, 0)]),
             (1, 1, b"abc", [(b"1234", 1, 1, sys.maxsize, 0)], -1, 0)]
    for args in cases:
        with pytest.raises(ValueError):
            native.composite_rgba(*args)


def test_batch_caches_are_bounded_and_clearable():
    batch = GoldBatchRenderer()
    batch.MAX_CACHE_BYTES = 128
    batch.MAX_CACHE_ITEMS = 2
    for index in range(8):
        batch._record(command(Image.new("RGBA", (4, 4)), 0, 0, index))
    assert len(batch._images) <= 2
    assert len(batch._commands) <= 2
    assert batch._image_bytes <= 128
    assert batch._command_bytes <= 128
    batch.clear()
    assert not batch._images and not batch._commands
    assert batch._image_bytes == batch._command_bytes == 0

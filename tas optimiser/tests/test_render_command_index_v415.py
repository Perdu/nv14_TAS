"""Spatial lookup must preserve exact overlapping sprite composition."""
import random

import pytest

Image = pytest.importorskip("PIL.Image")
from nv14_render_commands import Command, CommandIndex, DrawList, dirty_regions, intersects


def sprite(key, box, color=(40, 90, 170, 123)):
    image = Image.new("RGBA", (box[2]-box[0], box[3]-box[1]), color)
    command = Command("paste", (image, box[:2], image), box)
    command.key = key
    return command


def render(commands, size):
    image = Image.new("RGB", size, (181, 175, 163))
    for command in commands:
        command.draw(image)
    return image


def test_incremental_index_queries_match_scan_for_moves_removals_and_thresholds():
    rng = random.Random(415)
    size = (350, 250)
    index = CommandIndex(size, cell_size=24)
    commands = []
    for count in (4, 63, 64, 100, 87, 40, 120, 0, 80):
        commands = commands[:count]
        while len(commands) < count:
            k = len(commands)
            x, y = rng.randrange(-30, 360), rng.randrange(-20, 260)
            commands.append(sprite(k, (x, y, x+20, y+15)))
        for k in range(0, len(commands), 9):
            x, y = rng.randrange(-30, 360), rng.randrange(-20, 260)
            commands[k] = sprite(k, (x, y, x+20, y+15))
        # A large overlay takes the global bucket, including translucency.
        current = commands + [sprite("terrain", (-10, -10, 370, 270))]
        index.update(current)
        for _ in range(40):
            x, y = rng.randrange(340), rng.randrange(240)
            rect = (x, y, min(x+50, size[0]), min(y+40, size[1]))
            assert index.query(rect) == [command for command in current
                                        if intersects(command.bounds, rect)]


def test_dirty_recomposition_stays_exact_with_reordering_and_new_sprites():
    rng = random.Random(4151)
    size = (220, 190)
    commands = []
    for k in range(100):
        x, y = rng.randrange(200), rng.randrange(170)
        commands.append(sprite(k, (x, y, x+20, y+20),
                               (rng.randrange(256), 70, rng.randrange(256), 123)))
    index = CommandIndex(size, cell_size=32)
    index.update(commands)
    actual = render(commands, size)
    for tick in range(12):
        previous = commands
        commands = list(previous)
        if tick % 3 == 0:
            commands[30:50] = reversed(commands[30:50])
        elif tick % 3 == 1:
            x, y = rng.randrange(200), rng.randrange(170)
            commands[tick] = sprite(previous[tick].key, (x, y, x+20, y+20))
        else:
            commands.pop(20)
            commands.insert(40, sprite(("new", tick), (100, 100, 120, 120)))
        changes = index.update(commands)
        regions = dirty_regions(previous, commands, size, changes=changes, index=index)
        if regions is None:
            actual = render(commands, size)
        else:
            for rect in regions:
                patch = Image.new("RGB", (rect[2]-rect[0], rect[3]-rect[1]), (181, 175, 163))
                for command in index.query(rect):
                    command.draw(patch, rect[:2])
                actual.paste(patch, rect[:2])
        assert actual.tobytes() == render(commands, size).tobytes()


def test_unchanged_commands_keep_grid_membership_and_hide_offscreen_sprites(monkeypatch):
    index = CommandIndex((200, 200), cell_size=20)
    commands = [sprite(k, (k*3, 20, k*3+10, 30)) for k in range(80)]
    index.update(commands)
    memberships = {key: value[1] for key, value in index._entries.items()}

    def fail(*args):
        pytest.fail("unchanged sprite recomputed its grid membership")

    monkeypatch.setattr(index, "_cell_range", fail)
    assert index.update(commands) == []
    assert all(index._entries[key][1] is cells for key, cells in memberships.items())
    assert index._entries[79][1] == ()


def test_wide_line_fallback_survives_indexed_and_small_scenes():
    for count in (1, 70):
        size = (200, 200)
        index = CommandIndex(size)
        commands = [sprite(k, (140, 140, 150, 150)) for k in range(count)]
        line = Command("line", (((0, 20), (150, 180)), (70, 80, 90), 3), (-3, 17, 154, 184))
        line.key = "line"
        before = commands + [line]
        index.update(before)
        after = before + [sprite("new", (20, 20, 30, 30))]
        changes = index.update(after)
        assert dirty_regions(before, after, size, changes=changes, index=index) is None


def test_compact_signatures_reuse_commands_and_cached_byte_accounting(monkeypatch):
    stats = {"command_cache_hits": 0, "command_cache_misses": 0}
    draw = DrawList((100, 100), {}, stats)
    image = Image.new("RGBA", (5, 5))
    draw.capture_signature("gold", (1, (70, 80, 90)), lambda: draw.paste(image, (10, 10), image))
    assert draw.cache_bytes == 100
    next_draw = DrawList((100, 100), draw.groups, stats)

    def fail(*args):
        pytest.fail("compact immutable signature should not be recursively frozen")

    import nv14_render_commands
    monkeypatch.setattr(nv14_render_commands, "freeze", fail)
    next_draw.capture_signature("gold", (1, (70, 80, 90)), fail)
    assert next_draw.commands[0] is draw.commands[0]
    assert next_draw.cache_bytes == 100
    assert stats == {"command_cache_hits": 1, "command_cache_misses": 1}


def test_many_small_changes_stay_incremental_before_a_late_bridging_sprite():
    size = (792, 600)
    # Model a row of shrinking collection clips: each is initially disjoint,
    # but the moving player's later bounds bridge more than 48 of them.
    changes = [sprite(k, (40+k*6, 120, 42+k*6, 123)) for k in range(80)]
    changes.append(sprite("bridge", (40, 120, 516, 124)))
    index = CommandIndex(size)
    changed = index.update(changes)
    regions = dirty_regions([], changes, size, changes=changed, index=index)
    assert regions is not None
    assert sum((r[2]-r[0])*(r[3]-r[1]) for r in regions) < size[0]*size[1]/100
    actual = render([], size)
    for rect in regions:
        patch = Image.new("RGB", (rect[2]-rect[0], rect[3]-rect[1]), (181, 175, 163))
        for command in index.query(rect):
            command.draw(patch, rect[:2])
        actual.paste(patch, rect[:2])
    assert actual.tobytes() == render(changes, size).tobytes()


def test_many_widely_scattered_changes_keep_bounded_full_redraw_fallback():
    size = (792, 600)
    changes = [sprite((x, y), (x, y, x+2, y+2))
               for y in range(0, 600, 90) for x in range(0, 792, 110)]
    index = CommandIndex(size)
    changed = index.update(changes)
    assert dirty_regions([], changes, size, changes=changed, index=index) is None

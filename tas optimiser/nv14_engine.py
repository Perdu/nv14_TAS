"""Deterministic, source-faithful starter emulator for Metanet's n v1.4.

Current scope:
- exact player Verlet integration and state machine from n_v14_codedump.as;
- exact collision traversal and player circle projection for all n v1.4 static tile shapes (IDs 0-33);
- exact one-way platform, launch-pad, TestDoor, thwomp and short-window bounce-block interaction;
- shared drone navigation, round-robin thinker scheduling, and optional floorguard/zap/laser/chaingun/homing-launcher/turret simulation;
- mutable world-state cloning for replay optimisation;
- level-string parsing (31 x 23 map plus object list);
- no rendering, sound, particles, or unsupported enemy types.

The design deliberately preserves operation order and stores both ``pos`` and
``oldpos`` because velocity is implicit: v = pos - oldpos.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
import math
from typing import Iterable, Iterator, Sequence

# Bound once for the high-frequency grid-index paths.  This is the same C
# function as math.floor; avoiding repeated module attribute lookup matters
# across the millions of cell calculations in optimiser simulations.
_floor = math.floor

# Game constants from the ActionScript dump.
APP_TILE_SCALE = 12.0
APP_NUM_GRIDCOLS = 31  # x dimension
APP_NUM_GRIDROWS = 23  # y dimension
CHAR_PAD = 48

# QueryRayObj may stop DDA after a player-circle hit, but source curved-tile
# helpers use un-clipped circle roots. A hit from a newly entered cell can lie
# behind its entry point by at most one arc radius plus one cell diagonal:
# 24 + 24 * sqrt(2) < 58 px. Round that bound up for floating-point margin.
_RAY_TILE_BACKTRACK_MARGIN = 64.0

TID_EMPTY = 0
TID_FULL = 1
TID_45DEGPN = 2
TID_45DEGNN = 3
TID_45DEGNP = 4
TID_45DEGPP = 5
TID_CONCAVEPN = 6
TID_CONCAVENN = 7
TID_CONCAVENP = 8
TID_CONCAVEPP = 9
TID_CONVEXPN = 10
TID_CONVEXNN = 11
TID_CONVEXNP = 12
TID_CONVEXPP = 13
TID_22DEGPNS = 14
TID_22DEGNNS = 15
TID_22DEGNPS = 16
TID_22DEGPPS = 17
TID_22DEGPNB = 18
TID_22DEGNNB = 19
TID_22DEGNPB = 20
TID_22DEGPPB = 21
TID_67DEGPNS = 22
TID_67DEGNNS = 23
TID_67DEGNPS = 24
TID_67DEGPPS = 25
TID_67DEGPNB = 26
TID_67DEGNNB = 27
TID_67DEGNPB = 28
TID_67DEGPPB = 29
TID_HALFD = 30
TID_HALFR = 31
TID_HALFU = 32
TID_HALFL = 33

CTYPE_EMPTY = 0
CTYPE_FULL = 1
CTYPE_45DEG = 2
CTYPE_CONCAVE = 6
CTYPE_CONVEX = 10
CTYPE_22DEGS = 14
CTYPE_22DEGB = 18
CTYPE_67DEGS = 22
CTYPE_67DEGB = 26
CTYPE_HALF = 30

EID_OFF = 0
EID_INTERESTING = 1
EID_SOLID = 2

EDGE_U = 0
EDGE_D = 1
EDGE_L = 2
EDGE_R = 3

EdgeKey = tuple[int, int, int]
EdgeOverrides = dict[EdgeKey, int]

OBJTYPE_GOLD = 0
OBJTYPE_BOUNCEBLOCK = 1
OBJTYPE_LAUNCHPAD = 2
OBJTYPE_TURRET = 3
OBJTYPE_FLOORGUARD = 4
OBJTYPE_PLAYER = 5
OBJTYPE_DRONE = 6
OBJTYPE_ONEWAYPLATFORM = 7
OBJTYPE_THWOMP = 8
OBJTYPE_TESTDOOR = 9
OBJTYPE_HOMINGLAUNCHER = 10
OBJTYPE_EXIT = 11
OBJTYPE_MINE = 12

AI_DIR_R = 0
AI_DIR_D = 1
AI_DIR_L = 2
AI_DIR_U = 3

AI_ROT_0 = 0
AI_ROT_90 = 1
AI_ROT_180 = 2
AI_ROT_270 = 3

DRONEMOVE_SURFACEFOLLOW_CW = 0
DRONEMOVE_SURFACEFOLLOW_CCW = 1
DRONEMOVE_WANDER_CW = 2
DRONEMOVE_WANDER_CCW = 3
DRONEMOVE_WANDER_ALTERNATING = 4
DRONEMOVE_WANDER_RANDOM = 5

DRONEWEAP_ZAP = 0
DRONEWEAP_LASER = 1
DRONEWEAP_CHAINGUN = 2

MOVE_LIST_CHUCHU_CW = (AI_ROT_0, AI_ROT_90, AI_ROT_270, AI_ROT_180)
MOVE_LIST_CHUCHU_CCW = (AI_ROT_0, AI_ROT_270, AI_ROT_90, AI_ROT_180)
MOVE_LIST_SURFACE_CW = (AI_ROT_90, AI_ROT_0, AI_ROT_270, AI_ROT_180)
MOVE_LIST_SURFACE_CCW = (AI_ROT_270, AI_ROT_0, AI_ROT_90, AI_ROT_180)
DRONE_DIR_VECTORS = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))
# (edge side, cell-i delta, cell-j delta), in AI_DIR_* order.
DRONE_EDGE_INFO = (
    (EDGE_R, 1, 0),
    (EDGE_D, 0, 1),
    (EDGE_L, -1, 0),
    (EDGE_U, 0, -1),
)

COL_NONE = 0
COL_AXIS = 1
COL_OTHER = 2


class PlayerState(IntEnum):
    STANDING = 0
    RUNNING = 1
    SKIDDING = 2
    JUMPING = 3
    FALLING = 4
    WALLSLIDING = 5
    RAGDOLL = 6
    CELEBRATING = 7


class DroneMode(IntEnum):
    MOVING = 0
    PREFIRE = 1
    FIRING = 2
    POSTFIRE = 3


class HomingMode(IntEnum):
    IDLE = 0
    PREFIRE = 1
    HOMING = 2


class TurretMode(IntEnum):
    WAITING = 0
    TARGETING = 1
    PREFIRE = 2
    POSTFIRE = 3


@dataclass(slots=True)
class Vec2:
    x: float = 0.0
    y: float = 0.0

    def copy(self) -> "Vec2":
        return Vec2(self.x, self.y)


@dataclass(frozen=True, slots=True)
class InputFrame:
    left: bool = False
    right: bool = False
    jump: bool = False
    jump_trigger: bool | None = None

    @property
    def horizontal(self) -> int:
        return int(self.right) - int(self.left)


@dataclass(slots=True)
class ObjectSpec:
    obj_type: int
    params: tuple[float, ...]
    load_index: int


class StaticColliderKind(IntEnum):
    GOLD = 0
    MINE = 1
    EXIT_SWITCH = 2
    EXIT_DOOR = 3


GRIDREF_OBJECT = 0
GRIDREF_STATIC = 1
GridRef = tuple[int, int, int]

# Object-grid occupancy uses one bit per cell, including a one-cell margin
# around the complete tile grid.  Every cached nine-cell player neighbourhood
# is inside this range, so an integer mask can prove that the whole traversal
# is empty without nine dictionary probes.  Objects outside the range cannot
# overlap a cached in-grid neighbourhood and remain available through the
# ordinary dictionary representation for generic/out-of-grid callers.
_OCCUPANCY_MIN_I = -1
_OCCUPANCY_MIN_J = -1
_OCCUPANCY_MAX_I = APP_NUM_GRIDCOLS + 2
_OCCUPANCY_MAX_J = APP_NUM_GRIDROWS + 2
_OCCUPANCY_STRIDE = _OCCUPANCY_MAX_J - _OCCUPANCY_MIN_J + 1
_OCCUPANCY_HEIGHT = _OCCUPANCY_MAX_I - _OCCUPANCY_MIN_I + 1
_OCCUPANCY_BITS = tuple(
    1 << index for index in range(_OCCUPANCY_STRIDE * _OCCUPANCY_HEIGHT)
)
_OCCUPANCY_UNSET = -1


def _grid_cell_bit(cell: tuple[int, int]) -> int:
    cell_i, cell_j = cell
    if (
        _OCCUPANCY_MIN_I <= cell_i <= _OCCUPANCY_MAX_I
        and _OCCUPANCY_MIN_J <= cell_j <= _OCCUPANCY_MAX_J
    ):
        index = (
            (cell_i - _OCCUPANCY_MIN_I) * _OCCUPANCY_STRIDE
            + cell_j
            - _OCCUPANCY_MIN_J
        )
        return _OCCUPANCY_BITS[index]
    return 0


def _collision_neighbourhood_mask(cell_i: int, cell_j: int) -> int:
    return (
        _grid_cell_bit((cell_i, cell_j))
        | _grid_cell_bit((cell_i, cell_j + 1))
        | _grid_cell_bit((cell_i + 1, cell_j + 1))
        | _grid_cell_bit((cell_i - 1, cell_j + 1))
        | _grid_cell_bit((cell_i - 1, cell_j))
        | _grid_cell_bit((cell_i - 1, cell_j - 1))
        | _grid_cell_bit((cell_i + 1, cell_j))
        | _grid_cell_bit((cell_i + 1, cell_j - 1))
        | _grid_cell_bit((cell_i, cell_j - 1))
    )


# Tile geometry is identical across levels.  Share the 825 large integer masks
# instead of allocating another copy on every TileCell of every parsed level.
_COLLISION_NEIGHBOURHOOD_MASKS = tuple(
    tuple(
        _collision_neighbourhood_mask(cell_i, cell_j)
        for cell_j in range(APP_NUM_GRIDROWS + 2)
    )
    for cell_i in range(APP_NUM_GRIDCOLS + 2)
)


def object_grid_ref(uid: int) -> GridRef:
    return (GRIDREF_OBJECT, uid, 0)


@dataclass(slots=True)
class ObjectGridState:
    """Persistent port of TileMapCell's per-cell object linked lists.

    The first item in each cell is the list head. AddToGrid and Moved insert at
    the head. Membership changes only on explicit source-style grid operations,
    not merely because an object's position changed.
    """

    cells: dict[tuple[int, int], list[GridRef]] = field(default_factory=dict)
    membership: dict[GridRef, tuple[int, int]] = field(default_factory=dict)
    object_cells: list[tuple[int, int] | None] = field(default_factory=list, repr=False)
    occupancy_mask: int = field(
        default=_OCCUPANCY_UNSET,
        repr=False,
        compare=False,
    )
    _state_key_cache: tuple | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _copy_on_write: bool = field(
        default=False,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        # Preserve direct public dataclass construction with prepopulated
        # ``cells``.  Internal clones pass a non-negative derived mask and stay
        # O(1); ordinary empty construction initializes to zero here.
        if self.occupancy_mask == _OCCUPANCY_UNSET:
            mask = 0
            for cell, refs in self.cells.items():
                if refs:
                    mask |= _grid_cell_bit(cell)
            self.occupancy_mask = mask

    def clone(self, *, copy_on_write: bool = True) -> "ObjectGridState":
        if copy_on_write:
            cells = self.cells
            membership = self.membership
            object_cells = self.object_cells
        else:
            cells = {
                cell: refs.copy()
                for cell, refs in self.cells.items()
            }
            membership = self.membership.copy()
            object_cells = self.object_cells.copy()
        cloned = ObjectGridState(
            cells,
            membership,
            object_cells,
            self.occupancy_mask,
        )
        # The key contains only immutable cell/reference tuples, so a branch
        # can reuse it until its first grid mutation.  The mutable containers
        # are shared until one branch performs an actual grid operation unless
        # a caller explicitly requests a detached clone.
        cloned._state_key_cache = self._state_key_cache
        if copy_on_write:
            self._copy_on_write = True
            cloned._copy_on_write = True
        return cloned

    def _ensure_mutable(self) -> None:
        if not self._copy_on_write:
            return
        self.cells = {
            cell: refs.copy()
            for cell, refs in self.cells.items()
        }
        self.membership = self.membership.copy()
        self.object_cells = self.object_cells.copy()
        self._copy_on_write = False

    def add(self, ref: GridRef, cell: tuple[int, int]) -> None:
        # AddToGrid removes/reinserts an existing ref at the head, so this is
        # always a state-key mutation even when the destination cell is the
        # same one.
        self._ensure_mutable()
        self._state_key_cache = None
        if ref in self.membership:
            self.remove(ref)
        refs = self.cells.get(cell)
        if refs is None:
            self.cells[cell] = [ref]
            self.occupancy_mask |= _grid_cell_bit(cell)
        else:
            if not refs:
                self.occupancy_mask |= _grid_cell_bit(cell)
            refs.insert(0, ref)
        self.membership[ref] = cell
        if ref[0] == GRIDREF_OBJECT:
            uid = ref[1]
            if uid >= len(self.object_cells):
                self.object_cells.extend([None] * (uid + 1 - len(self.object_cells)))
            self.object_cells[uid] = cell

    def remove(self, ref: GridRef) -> bool:
        cell = self.membership.get(ref)
        if cell is None:
            return False
        self._ensure_mutable()
        self.membership.pop(ref, None)
        self._state_key_cache = None
        refs = self.cells.get(cell)
        if refs is not None:
            try:
                refs.remove(ref)
            except ValueError:
                pass
            if not refs:
                del self.cells[cell]
                self.occupancy_mask &= ~_grid_cell_bit(cell)
        if ref[0] == GRIDREF_OBJECT:
            uid = ref[1]
            if uid < len(self.object_cells):
                self.object_cells[uid] = None
        return True

    def moved(self, ref: GridRef, cell: tuple[int, int]) -> bool:
        old = self.membership.get(ref)
        if old is None or old == cell:
            return False
        self.remove(ref)
        self.add(ref, cell)
        return True

    def moved_xy(self, ref: GridRef, cell_i: int, cell_j: int) -> bool:
        """Fast path for the common cell-index form used by moving objects."""
        if ref[0] == GRIDREF_OBJECT and ref[1] < len(self.object_cells):
            old = self.object_cells[ref[1]]
        else:
            old = self.membership.get(ref)
        if old is None or (old[0] == cell_i and old[1] == cell_j):
            return False
        self._ensure_mutable()
        self._state_key_cache = None
        # This is the hot path for moving enemies.  Inline the remove/add
        # sequence so the common cell transition does not perform a second
        # membership lookup or two Python method calls.  The linked-list
        # semantics remain identical: remove from the old cell, then insert at
        # the head of the new cell.
        self.membership.pop(ref, None)
        old_refs = self.cells.get(old)
        if old_refs is not None:
            try:
                old_refs.remove(ref)
            except ValueError:
                pass
            if not old_refs:
                del self.cells[old]
                self.occupancy_mask &= ~_grid_cell_bit(old)
        new_cell = (cell_i, cell_j)
        new_refs = self.cells.get(new_cell)
        if new_refs is None:
            self.cells[new_cell] = [ref]
            self.occupancy_mask |= _grid_cell_bit(new_cell)
        else:
            if not new_refs:
                self.occupancy_mask |= _grid_cell_bit(new_cell)
            new_refs.insert(0, ref)
        self.membership[ref] = new_cell
        if ref[0] == GRIDREF_OBJECT:
            self.object_cells[ref[1]] = new_cell
        return True

    def moved_object_xy(
        self, uid: int, ref: GridRef, cell_i: int, cell_j: int
    ) -> bool:
        """Move a known object without rechecking the generic ref shape.

        ObjectManager already has a dense UID slot and cached object ref for
        every simulated object.  Keeping this object-only variant separate
        preserves the generic ``moved_xy`` API while removing two branches and
        one list-length check from the enemy update loop.
        """
        old = self.object_cells[uid]
        if old is None or (old[0] == cell_i and old[1] == cell_j):
            return False
        self._ensure_mutable()
        self._state_key_cache = None
        self.membership.pop(ref, None)
        old_refs = self.cells.get(old)
        if old_refs is not None:
            try:
                old_refs.remove(ref)
            except ValueError:
                pass
            if not old_refs:
                del self.cells[old]
                self.occupancy_mask &= ~_grid_cell_bit(old)
        new_cell = (cell_i, cell_j)
        new_refs = self.cells.get(new_cell)
        if new_refs is None:
            self.cells[new_cell] = [ref]
            self.occupancy_mask |= _grid_cell_bit(new_cell)
        else:
            if not new_refs:
                self.occupancy_mask |= _grid_cell_bit(new_cell)
            new_refs.insert(0, ref)
        self.membership[ref] = new_cell
        self.object_cells[uid] = new_cell
        return True

    def entries(self, cell: tuple[int, int]) -> tuple[GridRef, ...]:
        return tuple(self.cells.get(cell, ()))

    def entries_live(self, cell: tuple[int, int]) -> Sequence[GridRef]:
        """Return the current cell chain without allocating a snapshot.

        Player collision traversal stops immediately whenever it removes the
        current entry, which is the only mutation that can occur during that
        traversal.  The live list is therefore safe there and avoids a tuple
        allocation for every queried cell.  ``entries()`` remains the stable
        snapshot API for callers that need the old behaviour.
        """
        return self.cells.get(cell, ())

    def state_key(self) -> tuple:
        cached = self._state_key_cache
        if cached is not None:
            return cached
        cached = tuple(
            (cell, tuple(refs))
            for cell, refs in sorted(self.cells.items())
            if refs
        )
        self._state_key_cache = cached
        return cached


@dataclass(frozen=True, slots=True)
class StaticCollider:
    kind: StaticColliderKind
    x: float
    y: float
    r: float
    state_index: int
    load_index: int
    cell_i: int
    cell_j: int

    def is_active(self, state: "StaticObjectState") -> bool:
        bit = 1 << self.state_index
        if self.kind == StaticColliderKind.GOLD:
            return not (state.collected_gold_mask & bit)
        if self.kind == StaticColliderKind.MINE:
            return not (state.exploded_mine_mask & bit)
        if self.kind == StaticColliderKind.EXIT_SWITCH:
            return not (state.open_exit_mask & bit)
        return bool(state.open_exit_mask & bit)

    @property
    def grid_ref(self) -> GridRef:
        return (GRIDREF_STATIC, int(self.kind), self.state_index)


@dataclass(slots=True)
class StaticObjectState:
    collected_gold_mask: int = 0
    exploded_mine_mask: int = 0
    open_exit_mask: int = 0
    level_complete: bool = False
    gold_bonus_ticks: int = 0
    completed_exit_index: int | None = None

    def clone(self) -> "StaticObjectState":
        return StaticObjectState(
            self.collected_gold_mask,
            self.exploded_mine_mask,
            self.open_exit_mask,
            self.level_complete,
            self.gold_bonus_ticks,
            self.completed_exit_index,
        )

    def state_key(self) -> tuple[int, int, int, bool, int, int | None]:
        return (
            self.collected_gold_mask,
            self.exploded_mine_mask,
            self.open_exit_mask,
            self.level_complete,
            self.gold_bonus_ticks,
            self.completed_exit_index,
        )


@dataclass(slots=True)
class StaticWorld:
    by_cell: dict[tuple[int, int], tuple[StaticCollider, ...]]
    by_ref: dict[GridRef, StaticCollider] = field(default_factory=dict)
    gold_count: int = 0
    mine_count: int = 0
    exit_count: int = 0

    @classmethod
    def from_specs(cls, specs: Sequence[ObjectSpec], tiles: "TileMap") -> "StaticWorld":
        by_cell_lists: dict[tuple[int, int], list[StaticCollider]] = {}
        gold_index = 0
        mine_index = 0
        exit_index = 0

        def add(
            kind: StaticColliderKind,
            x: float,
            y: float,
            r: float,
            state_index: int,
            load_index: int,
        ) -> None:
            cell_i = _floor(x / tiles.tw)
            cell_j = _floor(y / tiles.th)
            collider = StaticCollider(
                kind, x, y, r, state_index, load_index, cell_i, cell_j
            )
            by_cell_lists.setdefault((cell_i, cell_j), []).append(collider)

        for spec in specs:
            if spec.obj_type == OBJTYPE_GOLD and len(spec.params) == 2:
                x, y = spec.params
                add(
                    StaticColliderKind.GOLD,
                    x,
                    y,
                    APP_TILE_SCALE * 0.5,
                    gold_index,
                    spec.load_index,
                )
                gold_index += 1
            elif spec.obj_type == OBJTYPE_MINE and len(spec.params) == 2:
                x, y = spec.params
                add(
                    StaticColliderKind.MINE,
                    x,
                    y,
                    APP_TILE_SCALE / 3.0,
                    mine_index,
                    spec.load_index,
                )
                mine_index += 1
            elif spec.obj_type == OBJTYPE_EXIT and len(spec.params) == 4:
                door_x, door_y, switch_x, switch_y = spec.params
                add(
                    StaticColliderKind.EXIT_SWITCH,
                    switch_x,
                    switch_y,
                    APP_TILE_SCALE * 0.5,
                    exit_index,
                    spec.load_index,
                )
                add(
                    StaticColliderKind.EXIT_DOOR,
                    door_x,
                    door_y,
                    APP_TILE_SCALE,
                    exit_index,
                    spec.load_index,
                )
                exit_index += 1

        by_cell = {cell: tuple(items) for cell, items in by_cell_lists.items()}
        by_ref = {entry.grid_ref: entry for items in by_cell.values() for entry in items}
        return cls(by_cell, by_ref, gold_index, mine_index, exit_index)

    @property
    def is_empty(self) -> bool:
        return not self.by_cell

    def entries_in_cell(self, cell_i: int, cell_j: int) -> tuple[StaticCollider, ...]:
        return self.by_cell.get((cell_i, cell_j), ())

    def entry_for_ref(self, ref: GridRef) -> StaticCollider | None:
        return self.by_ref.get(ref)

    def exit_door_ref(self, state_index: int) -> GridRef:
        return (GRIDREF_STATIC, int(StaticColliderKind.EXIT_DOOR), state_index)


@dataclass(slots=True)
class TileCell:
    i: int
    j: int
    pos: Vec2
    xw: float = APP_TILE_SCALE
    yw: float = APP_TILE_SCALE
    tile_id: int = TID_EMPTY
    ctype: int = CTYPE_EMPTY
    signx: int = 0
    signy: int = 0
    sx: float = 0.0
    sy: float = 0.0
    e_u: int = EID_OFF
    e_d: int = EID_OFF
    e_l: int = EID_OFF
    e_r: int = EID_OFF
    # Fixed-order tuple used by the simulation hot paths.  The individual
    # edge fields remain part of the diagnostic/public representation.
    edges: tuple[int, int, int, int] = field(
        default=(EID_OFF, EID_OFF, EID_OFF, EID_OFF),
        init=False,
        repr=False,
        compare=False,
    )
    # Stable dictionary keys used when a door/bounce correction overrides an
    # edge.  Constructing these once avoids a tuple allocation in enemy ray
    # and navigation checks while retaining the public coordinate-key format.
    edge_keys: tuple[EdgeKey, EdgeKey, EdgeKey, EdgeKey] = field(
        init=False,
        repr=False,
        compare=False,
    )
    # Player.CollideVsObjects visits these nine object-grid cells in this exact
    # order on every live tick.  They depend only on the immutable tile index,
    # so cache them alongside the edge keys rather than rebuilding ten tuples
    # for every simulated frame.
    object_collision_cells: tuple[tuple[int, int], ...] = field(
        init=False,
        repr=False,
        compare=False,
    )
    object_collision_mask: int = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        i = self.i
        j = self.j
        self.edge_keys = (
            (i, j, EDGE_U),
            (i, j, EDGE_D),
            (i, j, EDGE_L),
            (i, j, EDGE_R),
        )
        self.object_collision_cells = (
            (i, j),
            (i, j + 1),
            (i + 1, j + 1),
            (i - 1, j + 1),
            (i - 1, j),
            (i - 1, j - 1),
            (i + 1, j),
            (i + 1, j - 1),
            (i, j - 1),
        )
        if (
            0 <= i < len(_COLLISION_NEIGHBOURHOOD_MASKS)
            and 0 <= j < len(_COLLISION_NEIGHBOURHOOD_MASKS[i])
        ):
            self.object_collision_mask = _COLLISION_NEIGHBOURHOOD_MASKS[i][j]
        else:
            # Preserve direct/public TileCell construction outside the normal
            # level-grid dimensions. Player.step uses the dictionary fallback
            # for such cells, but keeping this cache coherent is inexpensive.
            self.object_collision_mask = _collision_neighbourhood_mask(i, j)


class UnsupportedTileCollision(RuntimeError):
    pass


class TileMap:
    """Tile map with the same one-cell solid border as the game.

    The original level string is column-major: all 23 y-cells for x=0, then
    all 23 y-cells for x=1, and so on.
    """

    def __init__(self, map_string: str, *, strict_shapes: bool = True) -> None:
        expected = APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS
        if len(map_string) != expected:
            raise ValueError(f"map string has {len(map_string)} chars; expected {expected}")
        self.rows = APP_NUM_GRIDCOLS
        self.cols = APP_NUM_GRIDROWS
        self.xw = APP_TILE_SCALE
        self.yw = APP_TILE_SCALE
        self.tw = 2.0 * self.xw
        self.th = 2.0 * self.yw
        self.strict_shapes = strict_shapes

        self.grid: list[list[TileCell]] = []
        for i in range(self.rows + 2):
            col: list[TileCell] = []
            for j in range(self.cols + 2):
                col.append(TileCell(i=i, j=j, pos=Vec2(self.xw + i * self.tw, self.yw + j * self.th)))
            self.grid.append(col)

        # Solid outer border.
        for i in range(self.rows + 2):
            self.grid[i][0].tile_id = TID_FULL
            self.grid[i][self.cols + 1].tile_id = TID_FULL
        for j in range(self.cols + 2):
            self.grid[0][j].tile_id = TID_FULL
            self.grid[self.rows + 1][j].tile_id = TID_FULL

        cnum = 0
        for i in range(self.rows):
            for j in range(self.cols):
                self.grid[i + 1][j + 1].tile_id = ord(map_string[cnum]) - CHAR_PAD
                cnum += 1
        self._update_all_edges()

    def get(self, i: int, j: int) -> TileCell:
        grid = self.grid
        return grid[i][j]

    def get_tile_xy(self, x: float, y: float) -> TileCell:
        tw = self.tw
        th = self.th
        i = _floor(x / tw)
        j = _floor(y / th)
        return self.grid[i][j]

    @staticmethod
    def base_edge(cell: TileCell, side: int) -> int:
        if side == EDGE_U:
            return cell.e_u
        if side == EDGE_D:
            return cell.e_d
        if side == EDGE_L:
            return cell.e_l
        if side == EDGE_R:
            return cell.e_r
        raise ValueError(f"unknown edge side {side}")

    @classmethod
    def edge(
        cls,
        cell: TileCell,
        side: int,
        overrides: EdgeOverrides | None = None,
    ) -> int:
        if overrides:
            value = overrides.get(cell.edge_keys[side])
            if value is not None:
                return value
        # Keep the override behaviour above, but avoid a second Python helper
        # call for the overwhelmingly common no-override path.
        if side == EDGE_U:
            return cell.e_u
        if side == EDGE_D:
            return cell.e_d
        if side == EDGE_L:
            return cell.e_l
        if side == EDGE_R:
            return cell.e_r
        raise ValueError(f"unknown edge side {side}")

    @staticmethod
    def _edge_plain(
        cell: TileCell, side: int, _overrides: EdgeOverrides | None = None
    ) -> int:
        """Internal valid-side edge lookup for the no-override hot path."""
        return cell.edges[side]

    @staticmethod
    def _update_type(cell: TileCell) -> None:
        tile_id = cell.tile_id
        if tile_id == TID_EMPTY:
            cell.ctype = CTYPE_EMPTY
            cell.signx = cell.signy = 0
            cell.sx = cell.sy = 0.0
            return
        if tile_id == TID_FULL:
            cell.ctype = CTYPE_FULL
            cell.signx = cell.signy = 0
            cell.sx = cell.sy = 0.0
            return

        groups = (
            (range(2, 6), CTYPE_45DEG),
            (range(6, 10), CTYPE_CONCAVE),
            (range(10, 14), CTYPE_CONVEX),
            (range(14, 18), CTYPE_22DEGS),
            (range(18, 22), CTYPE_22DEGB),
            (range(22, 26), CTYPE_67DEGS),
            (range(26, 30), CTYPE_67DEGB),
        )
        for ids, ctype in groups:
            if tile_id in ids:
                cell.ctype = ctype
                offset = tile_id - ids.start
                # pn, nn, np, pp
                cell.signx = 1 if offset in (0, 3) else -1
                cell.signy = -1 if offset in (0, 1) else 1
                if ctype == CTYPE_45DEG:
                    cell.sx = cell.signx / math.sqrt(2.0)
                    cell.sy = cell.signy / math.sqrt(2.0)
                elif ctype in (CTYPE_22DEGS, CTYPE_22DEGB):
                    root5 = 2.23606797749979
                    cell.sx = cell.signx / root5
                    cell.sy = cell.signy * 2.0 / root5
                elif ctype in (CTYPE_67DEGS, CTYPE_67DEGB):
                    root5 = 2.23606797749979
                    cell.sx = cell.signx * 2.0 / root5
                    cell.sy = cell.signy / root5
                else:
                    cell.sx = cell.sy = 0.0
                return

        cell.ctype = CTYPE_HALF
        if tile_id == TID_HALFD:
            cell.signx, cell.signy = 0, -1
        elif tile_id == TID_HALFU:
            cell.signx, cell.signy = 0, 1
        elif tile_id == TID_HALFL:
            cell.signx, cell.signy = 1, 0
        elif tile_id == TID_HALFR:
            cell.signx, cell.signy = -1, 0
        else:
            raise ValueError(f"unknown tile id {tile_id}")
        cell.sx = float(cell.signx)
        cell.sy = float(cell.signy)

    def _update_all_edges(self) -> None:
        for col in self.grid:
            for cell in col:
                self._update_type(cell)

        for i in range(self.rows + 2):
            for j in range(self.cols + 2):
                cell = self.grid[i][j]
                up = self.grid[i][j - 1] if j > 0 else cell
                down = self.grid[i][j + 1] if j < self.cols + 1 else cell
                left = self.grid[i - 1][j] if i > 0 else cell
                right = self.grid[i + 1][j] if i < self.rows + 1 else cell
                cell.e_u = self._edge_u(cell, up)
                cell.e_d = self._edge_d(cell, down)
                cell.e_l = self._edge_l(cell, left)
                cell.e_r = self._edge_r(cell, right)
                cell.edges = (cell.e_u, cell.e_d, cell.e_l, cell.e_r)

    @staticmethod
    def _edge_u(cell: TileCell, n: TileCell) -> int:
        if cell.tile_id == TID_EMPTY:
            if n.tile_id == TID_EMPTY:
                return EID_OFF
            if n.tile_id == TID_FULL:
                return EID_SOLID
            return EID_INTERESTING if (n.signy * -1 <= 0 or n.tile_id in (TID_67DEGPNS, TID_67DEGNNS)) else EID_SOLID
        if cell.tile_id == TID_FULL:
            if n.tile_id in (TID_EMPTY, TID_FULL):
                return EID_OFF
            return EID_INTERESTING if (n.signy * -1 <= 0 or n.tile_id in (TID_67DEGPNS, TID_67DEGNNS)) else EID_OFF
        if 0 <= cell.signy * -1:
            if n.tile_id == TID_EMPTY:
                return EID_OFF
            if n.tile_id == TID_FULL:
                return EID_SOLID
            return EID_INTERESTING if (n.signy * -1 <= 0 or n.tile_id in (TID_67DEGPNS, TID_67DEGNNS)) else EID_SOLID
        if cell.tile_id in (TID_67DEGPPS, TID_67DEGNPS):
            if n.tile_id == TID_EMPTY:
                return EID_OFF
            if n.tile_id == TID_FULL:
                return EID_SOLID
            if n.signy * -1 <= 0 or n.tile_id in (TID_67DEGPNS, TID_67DEGNNS):
                return EID_INTERESTING
            return EID_SOLID if (0 < n.signy * -1 or n.tile_id == TID_FULL) else EID_OFF
        if n.tile_id in (TID_EMPTY, TID_FULL):
            return EID_OFF
        return EID_INTERESTING if (n.signy * -1 <= 0 or n.tile_id in (TID_67DEGPNS, TID_67DEGNNS)) else EID_OFF

    @staticmethod
    def _edge_d(cell: TileCell, n: TileCell) -> int:
        if cell.tile_id == TID_EMPTY:
            if n.tile_id == TID_EMPTY:
                return EID_OFF
            if n.tile_id == TID_FULL:
                return EID_SOLID
            return EID_INTERESTING if (n.signy <= 0 or n.tile_id in (TID_67DEGPPS, TID_67DEGNPS)) else EID_SOLID
        if cell.tile_id == TID_FULL:
            if n.tile_id in (TID_EMPTY, TID_FULL):
                return EID_OFF
            return EID_INTERESTING if (n.signy <= 0 or n.tile_id in (TID_67DEGPPS, TID_67DEGNPS)) else EID_OFF
        if 0 <= cell.signy:
            if n.tile_id == TID_EMPTY:
                return EID_OFF
            if n.tile_id == TID_FULL:
                return EID_SOLID
            return EID_INTERESTING if (n.signy <= 0 or n.tile_id in (TID_67DEGPPS, TID_67DEGNPS)) else EID_SOLID
        if cell.tile_id in (TID_67DEGPNS, TID_67DEGNNS):
            if n.tile_id == TID_EMPTY:
                return EID_OFF
            if n.tile_id == TID_FULL:
                return EID_SOLID
            if n.signy <= 0 or n.tile_id in (TID_67DEGPPS, TID_67DEGNPS):
                return EID_INTERESTING
            return EID_SOLID if (0 < n.signy or n.tile_id == TID_FULL) else EID_OFF
        if n.tile_id in (TID_EMPTY, TID_FULL):
            return EID_OFF
        return EID_INTERESTING if (n.signy <= 0 or n.tile_id in (TID_67DEGPPS, TID_67DEGNPS)) else EID_OFF

    @staticmethod
    def _edge_r(cell: TileCell, n: TileCell) -> int:
        if cell.tile_id == TID_EMPTY:
            if n.tile_id == TID_EMPTY:
                return EID_OFF
            if n.tile_id == TID_FULL:
                return EID_SOLID
            return EID_INTERESTING if (n.signx <= 0 or n.tile_id in (TID_22DEGPNS, TID_22DEGPPS)) else EID_SOLID
        if cell.tile_id == TID_FULL:
            if n.tile_id in (TID_EMPTY, TID_FULL):
                return EID_OFF
            return EID_INTERESTING if (n.signx <= 0 or n.tile_id in (TID_22DEGPNS, TID_22DEGPPS)) else EID_OFF
        if 0 <= cell.signx:
            if n.tile_id == TID_EMPTY:
                return EID_OFF
            if n.tile_id == TID_FULL:
                return EID_SOLID
            return EID_INTERESTING if (n.signx <= 0 or n.tile_id in (TID_22DEGPNS, TID_22DEGPPS)) else EID_SOLID
        if cell.tile_id in (TID_22DEGNNS, TID_22DEGNPS):
            if n.tile_id == TID_EMPTY:
                return EID_OFF
            if n.tile_id == TID_FULL:
                return EID_SOLID
            if n.signx <= 0 or n.tile_id in (TID_22DEGPNS, TID_22DEGPPS):
                return EID_INTERESTING
            return EID_SOLID if (n.tile_id == TID_FULL or 0 < n.signx) else EID_OFF
        if n.tile_id in (TID_EMPTY, TID_FULL):
            return EID_OFF
        return EID_INTERESTING if (n.signx <= 0 or n.tile_id in (TID_22DEGPNS, TID_22DEGPPS)) else EID_OFF

    @staticmethod
    def _edge_l(cell: TileCell, n: TileCell) -> int:
        if cell.tile_id == TID_EMPTY:
            if n.tile_id == TID_EMPTY:
                return EID_OFF
            if n.tile_id == TID_FULL:
                return EID_SOLID
            return EID_INTERESTING if (n.signx * -1 <= 0 or n.tile_id in (TID_22DEGNNS, TID_22DEGNPS)) else EID_SOLID
        if cell.tile_id == TID_FULL:
            if n.tile_id in (TID_EMPTY, TID_FULL):
                return EID_OFF
            return EID_INTERESTING if (n.signx * -1 <= 0 or n.tile_id in (TID_22DEGNNS, TID_22DEGNPS)) else EID_OFF
        if 0 <= cell.signx * -1:
            if n.tile_id == TID_EMPTY:
                return EID_OFF
            if n.tile_id == TID_FULL:
                return EID_SOLID
            return EID_INTERESTING if (n.signx * -1 <= 0 or n.tile_id in (TID_22DEGNNS, TID_22DEGNPS)) else EID_SOLID
        if cell.tile_id in (TID_22DEGPNS, TID_22DEGPPS):
            if n.tile_id == TID_EMPTY:
                return EID_OFF
            if n.tile_id == TID_FULL:
                return EID_SOLID
            if n.signx * -1 <= 0 or n.tile_id in (TID_22DEGNNS, TID_22DEGNPS):
                return EID_INTERESTING
            return EID_SOLID if (0 < n.signx * -1 or n.tile_id == TID_FULL) else EID_OFF
        if n.tile_id in (TID_EMPTY, TID_FULL):
            return EID_OFF
        return EID_INTERESTING if (n.signx * -1 <= 0 or n.tile_id in (TID_22DEGNNS, TID_22DEGNPS)) else EID_OFF

    def query_point(
        self, x: float, y: float, cell: TileCell | None = None
    ) -> bool:
        # Keep the exact floor/indexing behaviour of get_tile_xy while
        # avoiding a helper call in this frequently used query.  Homing
        # missiles can pass their already-indexed post-move cell.
        if cell is None:
            cell = self.grid[_floor(x / self.tw)][_floor(y / self.th)]
        if cell.tile_id == TID_EMPTY:
            return False
        if cell.ctype == CTYPE_FULL:
            return True
        dx = x - cell.pos.x
        dy = y - cell.pos.y
        if cell.ctype == CTYPE_HALF:
            return dx * cell.signx + dy * cell.signy <= 0.0
        if cell.ctype == CTYPE_45DEG:
            return dx * cell.sx + dy * cell.sy <= 0.0
        if cell.ctype == CTYPE_CONCAVE:
            vx = cell.pos.x + cell.signx * cell.xw - x
            vy = cell.pos.y + cell.signy * cell.yw - y
            radius = cell.xw * 2.0
            return radius * radius <= vx * vx + vy * vy
        if cell.ctype == CTYPE_CONVEX:
            vx = x - (cell.pos.x - cell.signx * cell.xw)
            vy = y - (cell.pos.y - cell.signy * cell.yw)
            radius = cell.xw * 2.0
            return vx * vx + vy * vy <= radius * radius
        if cell.ctype == CTYPE_22DEGS:
            vx = x - (cell.pos.x + cell.signx * cell.xw)
            vy = y - (cell.pos.y - cell.signy * cell.yw)
            return vx * cell.sx + vy * cell.sy <= 0.0
        if cell.ctype == CTYPE_22DEGB:
            vx = x - (cell.pos.x - cell.signx * cell.xw)
            vy = y - (cell.pos.y + cell.signy * cell.yw)
            return vx * cell.sx + vy * cell.sy <= 0.0
        if cell.ctype == CTYPE_67DEGS:
            vx = x - (cell.pos.x - cell.signx * cell.xw)
            vy = y - (cell.pos.y + cell.signy * cell.yw)
            return vx * cell.sx + vy * cell.sy <= 0.0
        if cell.ctype == CTYPE_67DEGB:
            vx = x - (cell.pos.x + cell.signx * cell.xw)
            vy = y - (cell.pos.y - cell.signy * cell.yw)
            return vx * cell.sx + vy * cell.sy <= 0.0
        if self.strict_shapes:
            raise UnsupportedTileCollision(
                f"point query reached unsupported tile id {cell.tile_id} at ({cell.i},{cell.j})"
            )
        return False

    def collide_circle(
        self,
        player: "Player",
        edge_overrides: EdgeOverrides | None = None,
        centre: TileCell | None = None,
    ) -> None:
        """Source-order port of CollideCirclevsTileMap for EMPTY/FULL tiles."""
        p = player.pos
        r = player.r
        grid = self.grid
        resolve = self._resolve_circle_tile
        if centre is None:
            centre = grid[_floor(p.x / self.tw)][_floor(p.y / self.th)]
        cx = centre.pos.x
        cy = centre.pos.y
        xw = centre.xw
        yw = centre.yw
        dx = p.x - cx
        dy = p.y - cy

        if centre.tile_id > TID_EMPTY:
            px = xw + r - abs(dx)
            py = yw + r - abs(dy)
            resolve(px, py, 0, 0, player, centre)

        crossed_v = False
        col_v = COL_NONE
        dy = p.y - cy
        py = abs(dy) + r - yw
        v_neighbour: TileCell | None = None
        o_v = 0
        if py > 0.0:
            crossed_v = True
            if dy < 0.0:
                if edge_overrides:
                    edge_value = edge_overrides.get(centre.edge_keys[EDGE_U])
                    if edge_value is None:
                        edge_value = centre.edges[EDGE_U]
                else:
                    edge_value = centre.edges[EDGE_U]
                v_neighbour = grid[centre.i][centre.j - 1]
                o_v = 1
            else:
                if edge_overrides:
                    edge_value = edge_overrides.get(centre.edge_keys[EDGE_D])
                    if edge_value is None:
                        edge_value = centre.edges[EDGE_D]
                else:
                    edge_value = centre.edges[EDGE_D]
                v_neighbour = grid[centre.i][centre.j + 1]
                o_v = -1
            if edge_value > EID_OFF:
                if edge_value == EID_SOLID:
                    col_v = COL_AXIS
                    player.report_collision_world(0.0, py * o_v, 0.0, float(o_v), v_neighbour)
                else:
                    col_v = resolve(0.0, py, 0, o_v, player, v_neighbour)

        crossed_h = False
        col_h = COL_NONE
        dx = p.x - cx
        px = abs(dx) + r - xw
        h_neighbour: TileCell | None = None
        o_h = 0
        if px > 0.0:
            crossed_h = True
            if dx < 0.0:
                if edge_overrides:
                    edge_value = edge_overrides.get(centre.edge_keys[EDGE_L])
                    if edge_value is None:
                        edge_value = centre.edges[EDGE_L]
                else:
                    edge_value = centre.edges[EDGE_L]
                h_neighbour = grid[centre.i - 1][centre.j]
                o_h = 1
            else:
                if edge_overrides:
                    edge_value = edge_overrides.get(centre.edge_keys[EDGE_R])
                    if edge_value is None:
                        edge_value = centre.edges[EDGE_R]
                else:
                    edge_value = centre.edges[EDGE_R]
                h_neighbour = grid[centre.i + 1][centre.j]
                o_h = -1
            if edge_value > EID_OFF:
                if edge_value == EID_SOLID:
                    col_h = COL_AXIS
                    player.report_collision_world(px * o_h, 0.0, float(o_h), 0.0, h_neighbour)
                else:
                    col_h = resolve(px, 0.0, o_h, 0, player, h_neighbour)

        if crossed_h and col_h != COL_AXIS and crossed_v and col_v != COL_AXIS:
            # Same diagonal choice and edge tests as the original.
            if dx < 0.0 and dy < 0.0:
                h_cell = grid[centre.i][centre.j - 1]
                v_cell = grid[centre.i - 1][centre.j]
                if edge_overrides:
                    edge_h = edge_overrides.get(h_cell.edge_keys[EDGE_L])
                    if edge_h is None:
                        edge_h = h_cell.edges[EDGE_L]
                    edge_v = edge_overrides.get(v_cell.edge_keys[EDGE_U])
                    if edge_v is None:
                        edge_v = v_cell.edges[EDGE_U]
                else:
                    edge_h = h_cell.edges[EDGE_L]
                    edge_v = v_cell.edges[EDGE_U]
                diagonal = grid[centre.i - 1][centre.j - 1]
            elif dx < 0.0 and dy > 0.0:
                h_cell = grid[centre.i][centre.j + 1]
                v_cell = grid[centre.i - 1][centre.j]
                if edge_overrides:
                    edge_h = edge_overrides.get(h_cell.edge_keys[EDGE_L])
                    if edge_h is None:
                        edge_h = h_cell.edges[EDGE_L]
                    edge_v = edge_overrides.get(v_cell.edge_keys[EDGE_D])
                    if edge_v is None:
                        edge_v = v_cell.edges[EDGE_D]
                else:
                    edge_h = h_cell.edges[EDGE_L]
                    edge_v = v_cell.edges[EDGE_D]
                diagonal = grid[centre.i - 1][centre.j + 1]
            elif dx > 0.0 and dy > 0.0:
                h_cell = grid[centre.i][centre.j + 1]
                v_cell = grid[centre.i + 1][centre.j]
                if edge_overrides:
                    edge_h = edge_overrides.get(h_cell.edge_keys[EDGE_R])
                    if edge_h is None:
                        edge_h = h_cell.edges[EDGE_R]
                    edge_v = edge_overrides.get(v_cell.edge_keys[EDGE_D])
                    if edge_v is None:
                        edge_v = v_cell.edges[EDGE_D]
                else:
                    edge_h = h_cell.edges[EDGE_R]
                    edge_v = v_cell.edges[EDGE_D]
                diagonal = grid[centre.i + 1][centre.j + 1]
            elif dx > 0.0 and dy < 0.0:
                h_cell = grid[centre.i][centre.j - 1]
                v_cell = grid[centre.i + 1][centre.j]
                if edge_overrides:
                    edge_h = edge_overrides.get(h_cell.edge_keys[EDGE_R])
                    if edge_h is None:
                        edge_h = h_cell.edges[EDGE_R]
                    edge_v = edge_overrides.get(v_cell.edge_keys[EDGE_U])
                    if edge_v is None:
                        edge_v = v_cell.edges[EDGE_U]
                else:
                    edge_h = h_cell.edges[EDGE_R]
                    edge_v = v_cell.edges[EDGE_U]
                diagonal = grid[centre.i + 1][centre.j - 1]
            else:
                return

            if edge_h + edge_v > 0:
                if edge_h == EID_SOLID or edge_v == EID_SOLID:
                    corner_x = diagonal.pos.x + o_h * diagonal.xw
                    corner_y = diagonal.pos.y + o_v * diagonal.yw
                    vx = player.pos.x - corner_x
                    vy = player.pos.y - corner_y
                    length = math.sqrt(vx * vx + vy * vy)
                    penetration = player.r - length
                    if penetration > 0.0:
                        if length == 0.0:
                            vx = o_h / math.sqrt(2.0)
                            vy = o_v / math.sqrt(2.0)
                        else:
                            vx /= length
                            vy /= length
                        player.report_collision_world(vx * penetration, vy * penetration, vx, vy, diagonal)
                else:
                    px2 = abs(player.pos.x - diagonal.pos.x) + r - diagonal.xw
                    py2 = abs(player.pos.y - diagonal.pos.y) + r - diagonal.yw
                    resolve(px2, py2, o_h, o_v, player, diagonal)

    def _resolve_circle_tile(
        self,
        x: float,
        y: float,
        o_h: int,
        o_v: int,
        player: "Player",
        tile: TileCell,
    ) -> int:
        if tile.tile_id == TID_EMPTY:
            return COL_NONE
        if tile.ctype == CTYPE_FULL:
            return self._project_circle_full(x, y, o_h, o_v, player, tile)
        if tile.ctype == CTYPE_45DEG:
            return self._project_circle_45(x, y, o_h, o_v, player, tile)
        if tile.ctype == CTYPE_CONCAVE:
            return self._project_circle_concave(x, y, o_h, o_v, player, tile)
        if tile.ctype == CTYPE_CONVEX:
            return self._project_circle_convex(x, y, o_h, o_v, player, tile)
        if tile.ctype == CTYPE_22DEGS:
            return self._project_circle_22deg_s(x, y, o_h, o_v, player, tile)
        if tile.ctype == CTYPE_22DEGB:
            return self._project_circle_22deg_b(x, y, o_h, o_v, player, tile)
        if tile.ctype == CTYPE_67DEGS:
            return self._project_circle_67deg_s(x, y, o_h, o_v, player, tile)
        if tile.ctype == CTYPE_67DEGB:
            return self._project_circle_67deg_b(x, y, o_h, o_v, player, tile)
        if tile.ctype == CTYPE_HALF:
            return self._project_circle_half(x, y, o_h, o_v, player, tile)
        if self.strict_shapes:
            raise UnsupportedTileCollision(
                f"circle collision reached unsupported tile id {tile.tile_id} at ({tile.i},{tile.j})"
            )
        return COL_NONE

    @staticmethod
    def _project_circle_concave(
        x: float, y: float, o_h: int, o_v: int, player: "Player", tile: TileCell
    ) -> int:
        """Source-order port of ``ProjCircle_Concave``."""
        signx = tile.signx
        signy = tile.signy

        if o_h == 0:
            if o_v == 0:
                vx = tile.pos.x + signx * tile.xw - player.pos.x
                vy = tile.pos.y + signy * tile.yw - player.pos.y
                radius = tile.xw * 2.0
                length = math.sqrt(vx * vx + vy * vy)
                penetration = length + player.r - radius
                if 0.0 < penetration:
                    if x < y:
                        len_p = x
                        y = 0.0
                        if player.pos.x - tile.pos.x < 0.0:
                            x *= -1.0
                    else:
                        len_p = y
                        x = 0.0
                        if player.pos.y - tile.pos.y < 0.0:
                            y *= -1.0
                    if len_p < penetration:
                        player.report_collision_world(x, y, x / len_p, y / len_p, tile)
                        return COL_AXIS
                    vx /= length
                    vy /= length
                    player.report_collision_world(
                        vx * penetration, vy * penetration, vx, vy, tile
                    )
                    return COL_OTHER
                return COL_NONE

            if signy * o_v < 0:
                player.report_collision_world(0.0, y * o_v, 0.0, float(o_v), tile)
                return COL_AXIS
            corner_x = tile.pos.x - signx * tile.xw
            corner_y = tile.pos.y + o_v * tile.yw
            vx = player.pos.x - corner_x
            vy = player.pos.y - corner_y
            length = math.sqrt(vx * vx + vy * vy)
            penetration = player.r - length
            if 0.0 < penetration:
                if length == 0.0:
                    vx = 0.0
                    vy = float(o_v)
                else:
                    vx /= length
                    vy /= length
                player.report_collision_world(
                    vx * penetration, vy * penetration, vx, vy, tile
                )
                return COL_OTHER
            return COL_NONE

        if o_v == 0:
            if signx * o_h < 0:
                player.report_collision_world(x * o_h, 0.0, float(o_h), 0.0, tile)
                return COL_AXIS
            corner_x = tile.pos.x + o_h * tile.xw
            corner_y = tile.pos.y - signy * tile.yw
            vx = player.pos.x - corner_x
            vy = player.pos.y - corner_y
            length = math.sqrt(vx * vx + vy * vy)
            penetration = player.r - length
            if 0.0 < penetration:
                if length == 0.0:
                    vx = float(o_h)
                    vy = 0.0
                else:
                    vx /= length
                    vy /= length
                player.report_collision_world(
                    vx * penetration, vy * penetration, vx, vy, tile
                )
                return COL_OTHER
            return COL_NONE

        if 0 < signx * o_h + signy * o_v:
            return COL_NONE
        corner_x = tile.pos.x + o_h * tile.xw
        corner_y = tile.pos.y + o_v * tile.yw
        vx = player.pos.x - corner_x
        vy = player.pos.y - corner_y
        length = math.sqrt(vx * vx + vy * vy)
        penetration = player.r - length
        if 0.0 < penetration:
            if length == 0.0:
                vx = o_h / math.sqrt(2.0)
                vy = o_v / math.sqrt(2.0)
            else:
                vx /= length
                vy /= length
            player.report_collision_world(vx * penetration, vy * penetration, vx, vy, tile)
            return COL_OTHER
        return COL_NONE

    @staticmethod
    def _project_circle_convex(
        x: float, y: float, o_h: int, o_v: int, player: "Player", tile: TileCell
    ) -> int:
        """Source-order port of ``ProjCircle_Convex``."""
        signx = tile.signx
        signy = tile.signy

        def project_arc() -> int:
            vx = player.pos.x - (tile.pos.x - signx * tile.xw)
            vy = player.pos.y - (tile.pos.y - signy * tile.yw)
            radius = tile.xw * 2.0
            length = math.sqrt(vx * vx + vy * vy)
            penetration = radius + player.r - length
            if 0.0 < penetration:
                vx /= length
                vy /= length
                player.report_collision_world(
                    vx * penetration, vy * penetration, vx, vy, tile
                )
                return COL_OTHER
            return COL_NONE

        if o_h == 0:
            if o_v == 0:
                vx = player.pos.x - (tile.pos.x - signx * tile.xw)
                vy = player.pos.y - (tile.pos.y - signy * tile.yw)
                radius = tile.xw * 2.0
                length = math.sqrt(vx * vx + vy * vy)
                penetration = radius + player.r - length
                if 0.0 < penetration:
                    if x < y:
                        len_p = x
                        y = 0.0
                        if player.pos.x - tile.pos.x < 0.0:
                            x *= -1.0
                    else:
                        len_p = y
                        x = 0.0
                        if player.pos.y - tile.pos.y < 0.0:
                            y *= -1.0
                    if len_p < penetration:
                        player.report_collision_world(x, y, x / len_p, y / len_p, tile)
                        return COL_AXIS
                    vx /= length
                    vy /= length
                    player.report_collision_world(
                        vx * penetration, vy * penetration, vx, vy, tile
                    )
                    return COL_OTHER
                return COL_NONE

            if signy * o_v < 0:
                player.report_collision_world(0.0, y * o_v, 0.0, float(o_v), tile)
                return COL_AXIS
            return project_arc()

        if o_v == 0:
            if signx * o_h < 0:
                player.report_collision_world(x * o_h, 0.0, float(o_h), 0.0, tile)
                return COL_AXIS
            return project_arc()

        if 0 < signx * o_h + signy * o_v:
            return project_arc()

        corner_x = tile.pos.x + o_h * tile.xw
        corner_y = tile.pos.y + o_v * tile.yw
        vx = player.pos.x - corner_x
        vy = player.pos.y - corner_y
        length = math.sqrt(vx * vx + vy * vy)
        penetration = player.r - length
        if 0.0 < penetration:
            if length == 0.0:
                vx = o_h / math.sqrt(2.0)
                vy = o_v / math.sqrt(2.0)
            else:
                vx /= length
                vy /= length
            player.report_collision_world(vx * penetration, vy * penetration, vx, vy, tile)
            return COL_OTHER
        return COL_NONE

    @staticmethod
    def _project_circle_45(
        x: float, y: float, o_h: int, o_v: int, player: "Player", tile: TileCell
    ) -> int:
        signx = tile.signx
        signy = tile.signy
        if o_h == 0:
            if o_v == 0:
                nx = tile.sx
                ny = tile.sy
                vx = player.pos.x - nx * player.r - tile.pos.x
                vy = player.pos.y - ny * player.r - tile.pos.y
                dp = vx * nx + vy * ny
                if dp < 0.0:
                    nx *= -dp
                    ny *= -dp
                    if x < y:
                        len_p = x
                        y = 0.0
                        if player.pos.x - tile.pos.x < 0.0:
                            x *= -1.0
                    else:
                        len_p = y
                        x = 0.0
                        if player.pos.y - tile.pos.y < 0.0:
                            y *= -1.0
                    slope_len = math.sqrt(nx * nx + ny * ny)
                    if len_p < slope_len:
                        player.report_collision_world(x, y, x / len_p, y / len_p, tile)
                        return COL_AXIS
                    player.report_collision_world(nx, ny, tile.sx, tile.sy, tile)
                    return COL_OTHER
            else:
                if signy * o_v < 0:
                    player.report_collision_world(0.0, y * o_v, 0.0, float(o_v), tile)
                    return COL_AXIS
                nx = tile.sx
                ny = tile.sy
                vx = player.pos.x - (tile.pos.x - signx * tile.xw)
                vy = player.pos.y - (tile.pos.y + o_v * tile.yw)
                perpendicular = vx * -ny + vy * nx
                if 0.0 < perpendicular * signx * signy:
                    length = math.sqrt(vx * vx + vy * vy)
                    penetration = player.r - length
                    if 0.0 < penetration:
                        vx /= length
                        vy /= length
                        player.report_collision_world(vx * penetration, vy * penetration, vx, vy, tile)
                        return COL_OTHER
                else:
                    dp = vx * nx + vy * ny
                    penetration = player.r - abs(dp)
                    if 0.0 < penetration:
                        player.report_collision_world(nx * penetration, ny * penetration, nx, ny, tile)
                        return COL_OTHER
            return COL_NONE

        if o_v == 0:
            if signx * o_h < 0:
                player.report_collision_world(x * o_h, 0.0, float(o_h), 0.0, tile)
                return COL_AXIS
            nx = tile.sx
            ny = tile.sy
            vx = player.pos.x - (tile.pos.x + o_h * tile.xw)
            vy = player.pos.y - (tile.pos.y - signy * tile.yw)
            perpendicular = vx * -ny + vy * nx
            if perpendicular * signx * signy < 0.0:
                length = math.sqrt(vx * vx + vy * vy)
                penetration = player.r - length
                if 0.0 < penetration:
                    vx /= length
                    vy /= length
                    player.report_collision_world(vx * penetration, vy * penetration, vx, vy, tile)
                    return COL_OTHER
            else:
                dp = vx * nx + vy * ny
                penetration = player.r - abs(dp)
                if 0.0 < penetration:
                    player.report_collision_world(nx * penetration, ny * penetration, nx, ny, tile)
                    return COL_OTHER
            return COL_NONE

        if 0 < signx * o_h + signy * o_v:
            return COL_NONE
        corner_x = tile.pos.x + o_h * tile.xw
        corner_y = tile.pos.y + o_v * tile.yw
        vx = player.pos.x - corner_x
        vy = player.pos.y - corner_y
        length = math.sqrt(vx * vx + vy * vy)
        penetration = player.r - length
        if 0.0 < penetration:
            if length == 0.0:
                vx = o_h / math.sqrt(2.0)
                vy = o_v / math.sqrt(2.0)
            else:
                vx /= length
                vy /= length
            player.report_collision_world(vx * penetration, vy * penetration, vx, vy, tile)
            return COL_OTHER
        return COL_NONE

    @staticmethod
    def _project_circle_half(
        x: float, y: float, o_h: int, o_v: int, player: "Player", tile: TileCell
    ) -> int:
        """Source-order port of ``ProjCircle_Half``."""
        signx = tile.signx
        signy = tile.signy
        side = o_h * signx + o_v * signy
        if 0 < side:
            return COL_NONE

        if o_h == 0:
            if o_v == 0:
                radius = player.r
                vx = player.pos.x - signx * radius - tile.pos.x
                vy = player.pos.y - signy * radius - tile.pos.y
                nx = float(signx)
                ny = float(signy)
                dp = vx * nx + vy * ny
                if dp < 0.0:
                    nx *= -dp
                    ny *= -dp
                    slope_len = math.sqrt(nx * nx + ny * ny)
                    axis_len = math.sqrt(x * x + y * y)
                    if axis_len < slope_len:
                        player.report_collision_world(
                            x, y, x / axis_len, y / axis_len, tile
                        )
                        return COL_AXIS
                    player.report_collision_world(nx, ny, float(signx), float(signy), tile)
                    return COL_OTHER
            else:
                if side == 0:
                    vx = player.pos.x - tile.pos.x
                    if vx * signx < 0.0:
                        player.report_collision_world(0.0, y * o_v, 0.0, float(o_v), tile)
                        return COL_AXIS
                    vy = player.pos.y - (tile.pos.y + o_v * tile.yw)
                    length = math.sqrt(vx * vx + vy * vy)
                    penetration = player.r - length
                    if 0.0 < penetration:
                        if length == 0.0:
                            vx = signx / math.sqrt(2.0)
                            vy = o_v / math.sqrt(2.0)
                        else:
                            vx /= length
                            vy /= length
                        player.report_collision_world(
                            vx * penetration, vy * penetration, vx, vy, tile
                        )
                        return COL_OTHER
                else:
                    player.report_collision_world(0.0, y * o_v, 0.0, float(o_v), tile)
                    return COL_AXIS
            return COL_NONE

        if o_v == 0:
            if side == 0:
                vy = player.pos.y - tile.pos.y
                if vy * signy < 0.0:
                    player.report_collision_world(x * o_h, 0.0, float(o_h), 0.0, tile)
                    return COL_AXIS
                vx = player.pos.x - (tile.pos.x + o_h * tile.xw)
                length = math.sqrt(vx * vx + vy * vy)
                penetration = player.r - length
                if 0.0 < penetration:
                    if length == 0.0:
                        # Preserve the ActionScript routine literally.  For a
                        # vertical half tile signx==0 and o_v==0 here, so the
                        # decompiled source also yields a zero fallback normal.
                        vx = signx / math.sqrt(2.0)
                        vy = o_v / math.sqrt(2.0)
                    else:
                        vx /= length
                        vy /= length
                    player.report_collision_world(
                        vx * penetration, vy * penetration, vx, vy, tile
                    )
                    return COL_OTHER
            else:
                player.report_collision_world(x * o_h, 0.0, float(o_h), 0.0, tile)
                return COL_AXIS
            return COL_NONE

        corner_x = tile.pos.x + o_h * tile.xw
        corner_y = tile.pos.y + o_v * tile.yw
        vx = player.pos.x - corner_x
        vy = player.pos.y - corner_y
        length = math.sqrt(vx * vx + vy * vy)
        penetration = player.r - length
        if 0.0 < penetration:
            if length == 0.0:
                vx = o_h / math.sqrt(2.0)
                vy = o_v / math.sqrt(2.0)
            else:
                vx /= length
                vy /= length
            player.report_collision_world(vx * penetration, vy * penetration, vx, vy, tile)
            return COL_OTHER
        return COL_NONE

    @staticmethod
    def _project_circle_22deg_s(
        x: float, y: float, o_h: int, o_v: int, player: "Player", tile: TileCell
    ) -> int:
        """Source-order port of ``ProjCircle_22DegS``."""
        signx = tile.signx
        signy = tile.signy
        if 0 < signy * o_v:
            return COL_NONE

        if o_h == 0:
            if o_v == 0:
                nx = tile.sx
                ny = tile.sy
                radius = player.r
                vx = player.pos.x - (tile.pos.x - signx * tile.xw)
                vy = player.pos.y - tile.pos.y
                perpendicular = vx * -ny + vy * nx
                if 0.0 < perpendicular * signx * signy:
                    length = math.sqrt(vx * vx + vy * vy)
                    penetration = radius - length
                    if 0.0 < penetration:
                        vx /= length
                        vy /= length
                        player.report_collision_world(
                            vx * penetration, vy * penetration, vx, vy, tile
                        )
                        return COL_OTHER
                else:
                    vx -= radius * nx
                    vy -= radius * ny
                    dp = vx * nx + vy * ny
                    if dp < 0.0:
                        nx *= -dp
                        ny *= -dp
                        slope_len = math.sqrt(nx * nx + ny * ny)
                        if x < y:
                            len_p = x
                            y = 0.0
                            if player.pos.x - tile.pos.x < 0.0:
                                x *= -1.0
                        else:
                            len_p = y
                            x = 0.0
                            if player.pos.y - tile.pos.y < 0.0:
                                y *= -1.0
                        if len_p < slope_len:
                            player.report_collision_world(
                                x, y, x / len_p, y / len_p, tile
                            )
                            return COL_AXIS
                        player.report_collision_world(nx, ny, tile.sx, tile.sy, tile)
                        return COL_OTHER
            else:
                player.report_collision_world(0.0, y * o_v, 0.0, float(o_v), tile)
                return COL_AXIS
            return COL_NONE

        if o_v == 0:
            if signx * o_h < 0:
                corner_x = tile.pos.x - signx * tile.xw
                corner_y = tile.pos.y
                vx = player.pos.x - corner_x
                vy = player.pos.y - corner_y
                if vy * signy < 0.0:
                    player.report_collision_world(x * o_h, 0.0, float(o_h), 0.0, tile)
                    return COL_AXIS
                length = math.sqrt(vx * vx + vy * vy)
                penetration = player.r - length
                if 0.0 < penetration:
                    if length == 0.0:
                        vx = o_h / math.sqrt(2.0)
                        vy = o_v / math.sqrt(2.0)
                    else:
                        vx /= length
                        vy /= length
                    player.report_collision_world(
                        vx * penetration, vy * penetration, vx, vy, tile
                    )
                    return COL_OTHER
            else:
                nx = tile.sx
                ny = tile.sy
                vx = player.pos.x - (tile.pos.x + o_h * tile.xw)
                vy = player.pos.y - (tile.pos.y - signy * tile.yw)
                perpendicular = vx * -ny + vy * nx
                if perpendicular * signx * signy < 0.0:
                    length = math.sqrt(vx * vx + vy * vy)
                    penetration = player.r - length
                    if 0.0 < penetration:
                        vx /= length
                        vy /= length
                        player.report_collision_world(
                            vx * penetration, vy * penetration, vx, vy, tile
                        )
                        return COL_OTHER
                else:
                    dp = vx * nx + vy * ny
                    penetration = player.r - abs(dp)
                    if 0.0 < penetration:
                        player.report_collision_world(
                            nx * penetration, ny * penetration, nx, ny, tile
                        )
                        return COL_OTHER
            return COL_NONE

        corner_x = tile.pos.x + o_h * tile.xw
        corner_y = tile.pos.y + o_v * tile.yw
        vx = player.pos.x - corner_x
        vy = player.pos.y - corner_y
        length = math.sqrt(vx * vx + vy * vy)
        penetration = player.r - length
        if 0.0 < penetration:
            if length == 0.0:
                vx = o_h / math.sqrt(2.0)
                vy = o_v / math.sqrt(2.0)
            else:
                vx /= length
                vy /= length
            player.report_collision_world(vx * penetration, vy * penetration, vx, vy, tile)
            return COL_OTHER
        return COL_NONE

    @staticmethod
    def _project_circle_22deg_b(
        x: float, y: float, o_h: int, o_v: int, player: "Player", tile: TileCell
    ) -> int:
        """Source-order port of ``ProjCircle_22DegB``."""
        signx = tile.signx
        signy = tile.signy

        if o_h == 0:
            if o_v == 0:
                nx = tile.sx
                ny = tile.sy
                radius = player.r
                vx = player.pos.x - nx * radius - (tile.pos.x - signx * tile.xw)
                vy = player.pos.y - ny * radius - (tile.pos.y + signy * tile.yw)
                dp = vx * nx + vy * ny
                if dp < 0.0:
                    nx *= -dp
                    ny *= -dp
                    slope_len = math.sqrt(nx * nx + ny * ny)
                    if x < y:
                        len_p = x
                        y = 0.0
                        if player.pos.x - tile.pos.x < 0.0:
                            x *= -1.0
                    else:
                        len_p = y
                        x = 0.0
                        if player.pos.y - tile.pos.y < 0.0:
                            y *= -1.0
                    if len_p < slope_len:
                        player.report_collision_world(x, y, x / len_p, y / len_p, tile)
                        return COL_AXIS
                    player.report_collision_world(nx, ny, tile.sx, tile.sy, tile)
                    return COL_OTHER
            else:
                if signy * o_v < 0:
                    player.report_collision_world(0.0, y * o_v, 0.0, float(o_v), tile)
                    return COL_AXIS
                nx = tile.sx
                ny = tile.sy
                vx = player.pos.x - (tile.pos.x - signx * tile.xw)
                vy = player.pos.y - (tile.pos.y + signy * tile.yw)
                perpendicular = vx * -ny + vy * nx
                if 0.0 < perpendicular * signx * signy:
                    length = math.sqrt(vx * vx + vy * vy)
                    penetration = player.r - length
                    if 0.0 < penetration:
                        vx /= length
                        vy /= length
                        player.report_collision_world(
                            vx * penetration, vy * penetration, vx, vy, tile
                        )
                        return COL_OTHER
                else:
                    dp = vx * nx + vy * ny
                    penetration = player.r - abs(dp)
                    if 0.0 < penetration:
                        player.report_collision_world(
                            nx * penetration, ny * penetration, nx, ny, tile
                        )
                        return COL_OTHER
            return COL_NONE

        if o_v == 0:
            if signx * o_h < 0:
                player.report_collision_world(x * o_h, 0.0, float(o_h), 0.0, tile)
                return COL_AXIS
            vx = player.pos.x - (tile.pos.x + signx * tile.xw)
            vy = player.pos.y - tile.pos.y
            if vy * signy < 0.0:
                player.report_collision_world(x * o_h, 0.0, float(o_h), 0.0, tile)
                return COL_AXIS
            nx = tile.sx
            ny = tile.sy
            perpendicular = vx * -ny + vy * nx
            if perpendicular * signx * signy < 0.0:
                length = math.sqrt(vx * vx + vy * vy)
                penetration = player.r - length
                if 0.0 < penetration:
                    vx /= length
                    vy /= length
                    player.report_collision_world(
                        vx * penetration, vy * penetration, vx, vy, tile
                    )
                    return COL_OTHER
            else:
                dp = vx * nx + vy * ny
                penetration = player.r - abs(dp)
                if 0.0 < penetration:
                    player.report_collision_world(
                        nx * penetration, ny * penetration, tile.sx, tile.sy, tile
                    )
                    return COL_OTHER
            return COL_NONE

        if 0 < signx * o_h + signy * o_v:
            root5 = 2.23606797749979
            nx = signx * 1.0 / root5
            ny = signy * 2.0 / root5
            radius = player.r
            vx = player.pos.x - nx * radius - (tile.pos.x - signx * tile.xw)
            vy = player.pos.y - ny * radius - (tile.pos.y + signy * tile.yw)
            dp = vx * nx + vy * ny
            if dp < 0.0:
                player.report_collision_world(
                    -nx * dp, -ny * dp, tile.sx, tile.sy, tile
                )
                return COL_OTHER
            return COL_NONE

        corner_x = tile.pos.x + o_h * tile.xw
        corner_y = tile.pos.y + o_v * tile.yw
        vx = player.pos.x - corner_x
        vy = player.pos.y - corner_y
        length = math.sqrt(vx * vx + vy * vy)
        penetration = player.r - length
        if 0.0 < penetration:
            if length == 0.0:
                vx = o_h / math.sqrt(2.0)
                vy = o_v / math.sqrt(2.0)
            else:
                vx /= length
                vy /= length
            player.report_collision_world(vx * penetration, vy * penetration, vx, vy, tile)
            return COL_OTHER
        return COL_NONE

    @staticmethod
    def _project_circle_67deg_s(
        x: float, y: float, o_h: int, o_v: int, player: "Player", tile: TileCell
    ) -> int:
        """Source-order port of ``ProjCircle_67DegS``."""
        signx = tile.signx
        signy = tile.signy
        if 0 < signx * o_h:
            return COL_NONE

        if o_h == 0:
            if o_v == 0:
                nx = tile.sx
                ny = tile.sy
                radius = player.r
                vx = player.pos.x - tile.pos.x
                vy = player.pos.y - (tile.pos.y - signy * tile.yw)
                perpendicular = vx * -ny + vy * nx
                if perpendicular * signx * signy < 0.0:
                    length = math.sqrt(vx * vx + vy * vy)
                    penetration = radius - length
                    if 0.0 < penetration:
                        vx /= length
                        vy /= length
                        player.report_collision_world(
                            vx * penetration, vy * penetration, vx, vy, tile
                        )
                        return COL_OTHER
                else:
                    vx -= radius * nx
                    vy -= radius * ny
                    dp = vx * nx + vy * ny
                    if dp < 0.0:
                        nx *= -dp
                        ny *= -dp
                        slope_len = math.sqrt(nx * nx + ny * ny)
                        if x < y:
                            len_p = x
                            y = 0.0
                            if player.pos.x - tile.pos.x < 0.0:
                                x *= -1.0
                        else:
                            len_p = y
                            x = 0.0
                            if player.pos.y - tile.pos.y < 0.0:
                                y *= -1.0
                        if len_p < slope_len:
                            player.report_collision_world(x, y, x / len_p, y / len_p, tile)
                            return COL_AXIS
                        player.report_collision_world(nx, ny, tile.sx, tile.sy, tile)
                        return COL_OTHER
            else:
                if signy * o_v < 0:
                    corner_x = tile.pos.x
                    corner_y = tile.pos.y - signy * tile.yw
                    vx = player.pos.x - corner_x
                    vy = player.pos.y - corner_y
                    if vx * signx < 0.0:
                        player.report_collision_world(0.0, y * o_v, 0.0, float(o_v), tile)
                        return COL_AXIS
                    length = math.sqrt(vx * vx + vy * vy)
                    penetration = player.r - length
                    if 0.0 < penetration:
                        if length == 0.0:
                            vx = o_h / math.sqrt(2.0)
                            vy = o_v / math.sqrt(2.0)
                        else:
                            vx /= length
                            vy /= length
                        player.report_collision_world(
                            vx * penetration, vy * penetration, vx, vy, tile
                        )
                        return COL_OTHER
                else:
                    nx = tile.sx
                    ny = tile.sy
                    vx = player.pos.x - (tile.pos.x - signx * tile.xw)
                    vy = player.pos.y - (tile.pos.y + o_v * tile.yw)
                    perpendicular = vx * -ny + vy * nx
                    if 0.0 < perpendicular * signx * signy:
                        length = math.sqrt(vx * vx + vy * vy)
                        penetration = player.r - length
                        if 0.0 < penetration:
                            vx /= length
                            vy /= length
                            player.report_collision_world(
                                vx * penetration, vy * penetration, vx, vy, tile
                            )
                            return COL_OTHER
                    else:
                        dp = vx * nx + vy * ny
                        penetration = player.r - abs(dp)
                        if 0.0 < penetration:
                            player.report_collision_world(
                                nx * penetration, ny * penetration, tile.sx, tile.sy, tile
                            )
                            return COL_OTHER
            return COL_NONE

        if o_v == 0:
            player.report_collision_world(x * o_h, 0.0, float(o_h), 0.0, tile)
            return COL_AXIS

        corner_x = tile.pos.x + o_h * tile.xw
        corner_y = tile.pos.y + o_v * tile.yw
        vx = player.pos.x - corner_x
        vy = player.pos.y - corner_y
        length = math.sqrt(vx * vx + vy * vy)
        penetration = player.r - length
        if 0.0 < penetration:
            if length == 0.0:
                vx = o_h / math.sqrt(2.0)
                vy = o_v / math.sqrt(2.0)
            else:
                vx /= length
                vy /= length
            player.report_collision_world(vx * penetration, vy * penetration, vx, vy, tile)
            return COL_OTHER
        return COL_NONE

    @staticmethod
    def _project_circle_67deg_b(
        x: float, y: float, o_h: int, o_v: int, player: "Player", tile: TileCell
    ) -> int:
        """Source-order port of ``ProjCircle_67DegB``."""
        signx = tile.signx
        signy = tile.signy

        if o_h == 0:
            if o_v == 0:
                nx = tile.sx
                ny = tile.sy
                radius = player.r
                vx = player.pos.x - nx * radius - (tile.pos.x + signx * tile.xw)
                vy = player.pos.y - ny * radius - (tile.pos.y - signy * tile.yw)
                dp = vx * nx + vy * ny
                if dp < 0.0:
                    nx *= -dp
                    ny *= -dp
                    slope_len = math.sqrt(nx * nx + ny * ny)
                    if x < y:
                        len_p = x
                        y = 0.0
                        if player.pos.x - tile.pos.x < 0.0:
                            x *= -1.0
                    else:
                        len_p = y
                        x = 0.0
                        if player.pos.y - tile.pos.y < 0.0:
                            y *= -1.0
                    if len_p < slope_len:
                        player.report_collision_world(x, y, x / len_p, y / len_p, tile)
                        return COL_AXIS
                    player.report_collision_world(nx, ny, tile.sx, tile.sy, tile)
                    return COL_OTHER
            else:
                if signy * o_v < 0:
                    player.report_collision_world(0.0, y * o_v, 0.0, float(o_v), tile)
                    return COL_AXIS
                vx = player.pos.x - tile.pos.x
                vy = player.pos.y - (tile.pos.y + signy * tile.yw)
                if vx * signx < 0.0:
                    player.report_collision_world(0.0, y * o_v, 0.0, float(o_v), tile)
                    return COL_AXIS
                nx = tile.sx
                ny = tile.sy
                perpendicular = vx * -ny + vy * nx
                if 0.0 < perpendicular * signx * signy:
                    length = math.sqrt(vx * vx + vy * vy)
                    penetration = player.r - length
                    if 0.0 < penetration:
                        vx /= length
                        vy /= length
                        player.report_collision_world(
                            vx * penetration, vy * penetration, vx, vy, tile
                        )
                        return COL_OTHER
                else:
                    dp = vx * nx + vy * ny
                    penetration = player.r - abs(dp)
                    if 0.0 < penetration:
                        player.report_collision_world(
                            nx * penetration, ny * penetration, nx, ny, tile
                        )
                        return COL_OTHER
            return COL_NONE

        if o_v == 0:
            if signx * o_h < 0:
                player.report_collision_world(x * o_h, 0.0, float(o_h), 0.0, tile)
                return COL_AXIS
            root5 = 2.23606797749979
            nx = signx * 2.0 / root5
            ny = signy * 1.0 / root5
            vx = player.pos.x - (tile.pos.x + signx * tile.xw)
            vy = player.pos.y - (tile.pos.y - signy * tile.yw)
            perpendicular = vx * -ny + vy * nx
            if perpendicular * signx * signy < 0.0:
                length = math.sqrt(vx * vx + vy * vy)
                penetration = player.r - length
                if 0.0 < penetration:
                    vx /= length
                    vy /= length
                    player.report_collision_world(
                        vx * penetration, vy * penetration, vx, vy, tile
                    )
                    return COL_OTHER
            else:
                dp = vx * nx + vy * ny
                penetration = player.r - abs(dp)
                if 0.0 < penetration:
                    player.report_collision_world(
                        nx * penetration, ny * penetration, tile.sx, tile.sy, tile
                    )
                    return COL_OTHER
            return COL_NONE

        if 0 < signx * o_h + signy * o_v:
            nx = tile.sx
            ny = tile.sy
            radius = player.r
            vx = player.pos.x - nx * radius - (tile.pos.x + signx * tile.xw)
            vy = player.pos.y - ny * radius - (tile.pos.y - signy * tile.yw)
            dp = vx * nx + vy * ny
            if dp < 0.0:
                player.report_collision_world(-nx * dp, -ny * dp, tile.sx, tile.sy, tile)
                return COL_OTHER
            return COL_NONE

        corner_x = tile.pos.x + o_h * tile.xw
        corner_y = tile.pos.y + o_v * tile.yw
        vx = player.pos.x - corner_x
        vy = player.pos.y - corner_y
        length = math.sqrt(vx * vx + vy * vy)
        penetration = player.r - length
        if 0.0 < penetration:
            if length == 0.0:
                vx = o_h / math.sqrt(2.0)
                vy = o_v / math.sqrt(2.0)
            else:
                vx /= length
                vy /= length
            player.report_collision_world(vx * penetration, vy * penetration, vx, vy, tile)
            return COL_OTHER
        return COL_NONE

    @staticmethod
    def _project_circle_full(
        x: float, y: float, o_h: int, o_v: int, player: "Player", tile: TileCell
    ) -> int:
        if o_h == 0:
            if o_v == 0:
                if x < y:
                    vx = player.pos.x - tile.pos.x
                    if vx < 0.0:
                        player.report_collision_world(-x, 0.0, -1.0, 0.0, tile)
                    else:
                        player.report_collision_world(x, 0.0, 1.0, 0.0, tile)
                else:
                    vy = player.pos.y - tile.pos.y
                    if vy < 0.0:
                        player.report_collision_world(0.0, -y, 0.0, -1.0, tile)
                    else:
                        player.report_collision_world(0.0, y, 0.0, 1.0, tile)
                return COL_AXIS
            player.report_collision_world(0.0, y * o_v, 0.0, float(o_v), tile)
            return COL_AXIS
        if o_v == 0:
            player.report_collision_world(x * o_h, 0.0, float(o_h), 0.0, tile)
            return COL_AXIS

        corner_x = tile.pos.x + o_h * tile.xw
        corner_y = tile.pos.y + o_v * tile.yw
        vx = player.pos.x - corner_x
        vy = player.pos.y - corner_y
        length = math.sqrt(vx * vx + vy * vy)
        penetration = player.r - length
        if penetration > 0.0:
            if length == 0.0:
                vx = o_h / math.sqrt(2.0)
                vy = o_v / math.sqrt(2.0)
            else:
                vx /= length
                vy /= length
            player.report_collision_world(vx * penetration, vy * penetration, vx, vy, tile)
            return COL_OTHER
        return COL_NONE


def _ray_circle_first_hit(
    px: float,
    py: float,
    dx: float,
    dy: float,
    obj_pos: Vec2,
    radius: float,
) -> tuple[bool, Vec2, float]:
    """Port of TestRay_Circle for a normalized ray direction."""
    vx = px - obj_pos.x
    vy = py - obj_pos.y
    a = dx * dx + dy * dy
    b = 2.0 * (dx * vx + dy * vy)
    c = vx * vx + vy * vy - radius * radius
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return False, Vec2(), math.inf
    root = math.sqrt(disc)
    denom = 2.0 * a
    t1 = (-b + root) / denom
    t2 = (-b - root) / denom
    if t2 < 0.0:
        if t1 < 0.0:
            return False, Vec2(), math.inf
        t = t1
    elif t1 < 0.0:
        t = t2
    else:
        t = t2 if t2 < t1 else t1
    return True, Vec2(px + t * dx, py + t * dy), t


def _test_ray_tile(
    px: float,
    py: float,
    dx: float,
    dy: float,
    t: TileCell,
) -> tuple[bool, Vec2]:
    """Source-order TestRayTile geometry tests from n v1.4."""
    if t.tile_id <= TID_EMPTY or t.ctype == CTYPE_FULL:
        return False, Vec2()

    if t.ctype == CTYPE_45DEG:
        signx = t.signx
        signy = t.signy
        if 0.0 <= signx * dx + signy * dy:
            return False, Vec2()
        vx = signx * t.xw
        vy = -signy * t.yw
        ox = t.pos.x - px
        oy = t.pos.y - py
        denom = dx * vy - dy * vx
        if denom == 0.0:
            return False, Vec2()
        u = (dy * ox - dx * oy) / denom
        if abs(u) <= 1.0:
            return True, Vec2(t.pos.x + u * vx, t.pos.y + u * vy)
        return False, Vec2()

    if t.ctype == CTYPE_CONCAVE:
        signx = t.signx
        signy = t.signy
        if 0.0 <= signx * dx + signy * dy:
            return False, Vec2()
        sx = signx * t.xw
        sy = -signy * t.yw
        ox = t.pos.x - px
        oy = t.pos.y - py
        denom = dx * sy - dy * sx
        if denom == 0.0:
            return False, Vec2()
        u = (dy * ox - dx * oy) / denom
        if abs(u) > 1.0:
            return False, Vec2()
        cx = -sx - ox
        cy = sy - oy
        a = dx * dx + dy * dy
        b = 2.0 * (dx * cx + dy * cy)
        radius = t.xw * 2.0
        c = cx * cx + cy * cy - radius * radius
        disc = b * b - 4.0 * a * c
        if disc < 0.0:
            return False, Vec2()
        root = math.sqrt(disc)
        denom2 = 2.0 * a
        q1 = (-b + root) / denom2
        q2 = (-b - root) / denom2
        q = q1 if q2 < q1 else q2
        # The ActionScript selects the farther root for this concave arc.
        if q2 < q1:
            q = q1
        else:
            q = q2
        return True, Vec2(px + q * dx, py + q * dy)

    if t.ctype == CTYPE_CONVEX:
        signx = t.signx
        signy = t.signy
        ox = px - (t.pos.x - signx * t.xw)
        oy = py - (t.pos.y - signy * t.yw)
        a = dx * dx + dy * dy
        b = 2.0 * (dx * ox + dy * oy)
        radius = t.xw * 2.0
        c = ox * ox + oy * oy - radius * radius
        disc = b * b - 4.0 * a * c
        if disc < 0.0:
            return False, Vec2()
        root = math.sqrt(disc)
        denom = 2.0 * a
        q1 = (-b + root) / denom
        q2 = (-b - root) / denom
        q = q2 if q2 < q1 else q1
        return True, Vec2(px + q * dx, py + q * dy)

    if t.ctype == CTYPE_HALF:
        signx = t.signx
        signy = t.signy
        ox = t.pos.x - px
        oy = t.pos.y - py
        if 0.0 <= ox * signx + oy * signy:
            return True, Vec2(px, py)
        if 0.0 <= signx * dx + signy * dy:
            return False, Vec2()
        vx = signy * t.xw
        vy = signx * t.yw
        denom = dx * vy - dy * vx
        if denom == 0.0:
            return False, Vec2()
        u = (dy * ox - dx * oy) / denom
        if abs(u) <= 1.0:
            return True, Vec2(t.pos.x + u * vx, t.pos.y + u * vy)
        return False, Vec2()

    if t.ctype == CTYPE_22DEGS:
        sx = t.sx
        sy = t.sy
        signx = t.signx
        signy = t.signy
        ox = t.pos.x - signx * t.xw - px
        oy = t.pos.y - py
        if 0.0 <= ox * signx and 0.0 <= oy * signy:
            return True, Vec2(px, py)
        if 0.0 <= sx * dx + sy * dy:
            return False, Vec2()
        ox += signx * t.xw
        yoff = signy * 0.5 * t.yw
        oy -= yoff
        vx = -signy * t.xw
        vy = 0.5 * signx * t.yw
        denom = dx * vy - dy * vx
        if denom == 0.0:
            return False, Vec2()
        u = (dy * ox - dx * oy) / denom
        if abs(u) <= 1.0:
            return True, Vec2(t.pos.x + u * vx, t.pos.y - yoff + u * vy)
        return False, Vec2()

    if t.ctype == CTYPE_22DEGB:
        sx = t.sx
        sy = t.sy
        signx = t.signx
        signy = t.signy
        ox = t.pos.x - px
        oy = t.pos.y - py
        if ox * signx <= 0.0 and 0.0 <= oy * signy:
            return True, Vec2(px, py)
        if 0.0 <= sx * dx + sy * dy:
            return False, Vec2()
        yoff = signy * 0.5 * t.yw
        oy += yoff
        vx = -signy * t.xw
        vy = 0.5 * signx * t.yw
        denom = dx * vy - dy * vx
        if denom == 0.0:
            return False, Vec2()
        u = (dy * ox - dx * oy) / denom
        if abs(u) <= 1.0:
            return True, Vec2(t.pos.x + u * vx, t.pos.y + yoff + u * vy)
        return False, Vec2()

    if t.ctype == CTYPE_67DEGS:
        sx = t.sx
        sy = t.sy
        signx = t.signx
        signy = t.signy
        ox = t.pos.x - px
        oy = t.pos.y - signy * t.yw - py
        if 0.0 <= ox * signx and 0.0 <= oy * signy:
            return True, Vec2(px, py)
        if 0.0 <= sx * dx + sy * dy:
            return False, Vec2()
        oy += signy * t.yw
        xoff = signx * 0.5 * t.xw
        ox -= xoff
        vx = -0.5 * signy * t.xw
        vy = signx * t.yw
        denom = dx * vy - dy * vx
        if denom == 0.0:
            return False, Vec2()
        u = (dy * ox - dx * oy) / denom
        if abs(u) <= 1.0:
            return True, Vec2(t.pos.x - xoff + u * vx, t.pos.y + u * vy)
        return False, Vec2()

    if t.ctype == CTYPE_67DEGB:
        sx = t.sx
        sy = t.sy
        signx = t.signx
        signy = t.signy
        ox = t.pos.x - px
        oy = t.pos.y - py
        if oy * signy <= 0.0 and 0.0 <= ox * signx:
            return True, Vec2(px, py)
        if 0.0 <= sx * dx + sy * dy:
            return False, Vec2()
        xoff = signx * 0.5 * t.xw
        ox += xoff
        vx = -0.5 * signy * t.xw
        vy = signx * t.yw
        denom = dx * vy - dy * vx
        if denom == 0.0:
            return False, Vec2()
        u = (dy * ox - dx * oy) / denom
        if abs(u) <= 1.0:
            return True, Vec2(t.pos.x + xoff + u * vx, t.pos.y + u * vy)
        return False, Vec2()

    return False, Vec2()


def collide_ray_tiles(
    tiles: TileMap,
    p0: Vec2,
    p1: Vec2,
    edge_overrides: EdgeOverrides | None = None,
    *,
    _ray: tuple[float, float, float] | None = None,
    _max_entry_distance: float | None = None,
) -> tuple[bool, Vec2, float]:
    """Port of CollideRayvsTiles using the tile-edge DDA traversal.

    ``_max_entry_distance`` is an internal DDA-cell-entry cutoff used by
    ``QueryRayObj`` after a player circle hit. Its conservative curved-tile
    margin means a later DDA cell cannot return an earlier source intersection.
    Public callers retain the unbounded source traversal.
    """
    grid = tiles.grid
    if _ray is None:
        cell = grid[_floor(p0.x / tiles.tw)][_floor(p0.y / tiles.th)]
        vx = p1.x - p0.x
        vy = p1.y - p0.y
        length = math.sqrt(vx * vx + vy * vy)
        if length == 0.0:
            return False, Vec2(), math.inf
        dx = vx / length
        dy = vy / length
    else:
        length, dx, dy = _ray
        cell = grid[_floor(p0.x / tiles.tw)][_floor(p0.y / tiles.th)]

    step_x = -1 if dx < 0.0 else (1 if 0.0 < dx else 0)
    step_y = -1 if dy < 0.0 else (1 if 0.0 < dy else 0)
    if step_x < 0:
        tmax_x = (cell.pos.x - cell.xw - p0.x) / dx
        tdelta_x = 2.0 * cell.xw / -dx
    elif 0 < step_x:
        tmax_x = (cell.pos.x + cell.xw - p0.x) / dx
        tdelta_x = 2.0 * cell.xw / dx
    else:
        tmax_x = 100000000.0
        tdelta_x = 0.0
    if step_y < 0:
        tmax_y = (cell.pos.y - cell.yw - p0.y) / dy
        tdelta_y = 2.0 * cell.yw / -dy
    elif 0 < step_y:
        tmax_y = (cell.pos.y + cell.yw - p0.y) / dy
        tdelta_y = 2.0 * cell.yw / dy
    else:
        tmax_y = 100000000.0
        tdelta_y = 0.0

    # Empty and full cells are the two overwhelmingly common ray cases.  The
    # geometry helper returns a temporary failure vector for its legacy
    # two-value API; skip that call entirely when the early result is known.
    if cell.tile_id > TID_EMPTY and cell.ctype != CTYPE_FULL:
        hit, point = _test_ray_tile(p0.x, p0.y, dx, dy, cell)
        if hit:
            distance = (point.x - p0.x) * dx + (point.y - p0.y) * dy
            return True, point, distance

    while True:
        if tmax_x < tmax_y:
            side = EDGE_L if step_x < 0 else EDGE_R
            next_i = cell.i + step_x
            next_j = cell.j
            crossing_t = tmax_x
            tmax_x += tdelta_x
        else:
            side = EDGE_U if step_y < 0 else EDGE_D
            next_i = cell.i
            next_j = cell.j + step_y
            crossing_t = tmax_y
            tmax_y += tdelta_y

        # Keep cells within QueryRayObj's conservative curved-tile margin.
        # A same-distance entry stays on the original traversal so its existing
        # circle-priority comparison decides the exact floating-point tie.
        if (
            _max_entry_distance is not None
            and _max_entry_distance < crossing_t
        ):
            return False, Vec2(), math.inf

        if edge_overrides:
            edge_value = edge_overrides.get(cell.edge_keys[side])
            if edge_value is None:
                edge_value = cell.edges[side]
        else:
            edge_value = cell.edges[side]
        next_cell = grid[next_i][next_j]
        if 0 < edge_value:
            # Empty-edge crossings need only advance the DDA cell.  Defer the
            # intersection coordinates until a solid or shaped edge can use
            # them; the arithmetic and its order are unchanged on that path.
            crossing_x = p0.x + crossing_t * dx
            crossing_y = p0.y + crossing_t * dy
            if edge_value == EID_SOLID:
                return True, Vec2(crossing_x, crossing_y), crossing_t
            if next_cell.tile_id > TID_EMPTY and next_cell.ctype != CTYPE_FULL:
                hit, point = _test_ray_tile(crossing_x, crossing_y, dx, dy, next_cell)
                if hit:
                    distance = (point.x - p0.x) * dx + (point.y - p0.y) * dy
                    return True, point, distance
        cell = next_cell


def query_ray_circle(
    tiles: TileMap,
    p0: Vec2,
    p1: Vec2,
    obj_pos: Vec2,
    radius: float,
    edge_overrides: EdgeOverrides | None = None,
) -> tuple[bool, Vec2]:
    """Port of QueryRayObj for the player's circular collision volume."""
    vx = p1.x - p0.x
    vy = p1.y - p0.y
    length = math.sqrt(vx * vx + vy * vy)
    if length == 0.0:
        return False, Vec2()
    dx = vx / length
    dy = vy / length
    circle_hit, circle_point, circle_distance = _ray_circle_first_hit(
        p0.x, p0.y, dx, dy, obj_pos, radius
    )
    tile_hit, tile_point, tile_distance = collide_ray_tiles(
        tiles,
        p0,
        p1,
        edge_overrides,
        _ray=(length, dx, dy),
        _max_entry_distance=(
            circle_distance + _RAY_TILE_BACKTRACK_MARGIN if circle_hit else None
        ),
    )
    if circle_hit and (not tile_hit or circle_distance <= tile_distance):
        return True, circle_point
    return False, tile_point if tile_hit else Vec2()


@dataclass(slots=True)
class OneWayPlatform:
    pos: Vec2
    dir: Vec2
    xw: float = APP_TILE_SCALE
    yw: float = APP_TILE_SCALE
    load_index: int = 0

    @classmethod
    def from_spec(cls, spec: ObjectSpec) -> "OneWayPlatform":
        x, y, enum = spec.params
        enum_i = int(enum)
        direction = {
            AI_DIR_R: Vec2(1.0, 0.0),
            AI_DIR_D: Vec2(0.0, 1.0),
            AI_DIR_L: Vec2(-1.0, 0.0),
            AI_DIR_U: Vec2(0.0, -1.0),
        }[enum_i]
        return cls(Vec2(x, y), direction, load_index=spec.load_index)

    def clone(self) -> "OneWayPlatform":
        return OneWayPlatform(self.pos.copy(), self.dir.copy(), self.xw, self.yw, self.load_index)

    def update(self) -> None:
        pass

    def test_player(self, guy: "Player") -> None:
        dy = guy.pos.y - self.pos.y
        pen_y = self.yw + guy.yw - abs(dy)
        if pen_y > 0.0:
            dx = guy.pos.x - self.pos.x
            pen_x = self.xw + guy.xw - abs(dx)
            if pen_x > 0.0:
                if self.dir.x == 0.0:
                    movement = guy.pos.y - guy.oldpos.y
                    if movement * self.dir.y <= 0.0:
                        previous_edge_delta = (
                            guy.oldpos.y
                            - self.dir.y * guy.yw
                            - (self.pos.y + self.dir.y * self.yw)
                        )
                        if previous_edge_delta * self.dir.y >= 0.0:
                            correction = (
                                self.pos.y
                                + self.dir.y * self.yw
                                - (guy.pos.y - self.dir.y * guy.yw)
                            )
                            guy.report_collision_object(0.0, correction, 0.0, self.dir.y, self)
                else:
                    movement = guy.pos.x - guy.oldpos.x
                    if movement * self.dir.x <= 0.0:
                        previous_edge_delta = (
                            guy.oldpos.x
                            - self.dir.x * guy.xw
                            - (self.pos.x + self.dir.x * self.xw)
                        )
                        if previous_edge_delta * self.dir.x >= 0.0:
                            correction = (
                                self.pos.x
                                + self.dir.x * self.xw
                                - (guy.pos.x - self.dir.x * guy.xw)
                            )
                            guy.report_collision_object(correction, 0.0, self.dir.x, 0.0, self)


@dataclass(slots=True)
class LaunchPad:
    pos: Vec2
    nx: float
    ny: float
    r: float = APP_TILE_SCALE * 0.5
    strength: float = APP_TILE_SCALE * 0.4285714285714286
    load_index: int = 0

    @classmethod
    def from_spec(cls, spec: ObjectSpec) -> "LaunchPad":
        x, y, nx, ny = spec.params
        return cls(Vec2(x, y), nx, ny, load_index=spec.load_index)

    def clone(self) -> "LaunchPad":
        return LaunchPad(self.pos.copy(), self.nx, self.ny, self.r, self.strength, self.load_index)

    def update(self) -> None:
        pass

    def test_player(self, guy: "Player") -> None:
        vx = self.pos.x - guy.pos.x
        vy = self.pos.y - guy.pos.y
        if math.sqrt(vx * vx + vy * vy) < self.r + guy.r:
            dx = self.pos.x - (guy.pos.x - self.nx * guy.r)
            dy = self.pos.y - (guy.pos.y - self.ny * guy.r)
            along_normal = dx * self.nx + dy * self.ny
            if along_normal >= 0.0:
                y_factor = 1.0
                if self.ny < 0.0:
                    y_factor += abs(self.ny)
                guy.launch(self.nx * self.strength, self.ny * self.strength * y_factor)


@dataclass(slots=True)
class BounceBlock:
    pos: Vec2
    oldpos: Vec2
    anchor: Vec2
    xw: float = APP_TILE_SCALE * 0.8
    yw: float = APP_TILE_SCALE * 0.8
    stiff: float = 0.05
    mass: float = 0.2
    asleep: bool = True
    sleep_threshold: int = 40
    sleep_timer: int = 0
    load_index: int = 0

    @classmethod
    def from_spec(cls, spec: ObjectSpec) -> "BounceBlock":
        x, y = spec.params
        anchor = Vec2(x, y)
        return cls(anchor.copy(), anchor.copy(), anchor, load_index=spec.load_index)

    def clone(self) -> "BounceBlock":
        return BounceBlock(
            Vec2(self.pos.x, self.pos.y),
            Vec2(self.oldpos.x, self.oldpos.y),
            # The anchor is a level constant; BounceBlock only reads it while
            # springing back, so branches can safely share this Vec2.
            self.anchor,
            self.xw,
            self.yw,
            self.stiff,
            self.mass,
            self.asleep,
            self.sleep_threshold,
            self.sleep_timer,
            self.load_index,
        )

    def update(self) -> None:
        if self.asleep:
            return
        old_x_before = self.oldpos.x
        old_y_before = self.oldpos.y
        self.oldpos.x = self.pos.x
        current_x = self.oldpos.x
        self.oldpos.y = self.pos.y
        current_y = self.oldpos.y
        self.pos.x += 0.99 * (current_x - old_x_before)
        self.pos.y += 0.99 * (current_y - old_y_before)
        dx = self.anchor.x - self.pos.x
        dy = self.anchor.y - self.pos.y
        if 0.0 < dx * dx + dy * dy:
            self.pos.x += dx * self.stiff
            self.pos.y += dy * self.stiff
        self.sleep_timer += 1

    def think(self) -> bool:
        """Return True when the source Think() puts the block to sleep."""
        if self.sleep_threshold < self.sleep_timer:
            self.asleep = True
            self.oldpos.x = self.pos.x
            self.oldpos.y = self.pos.y
            return True
        return False

    def test_player(self, guy: "Player") -> None:
        dy = guy.pos.y - self.pos.y
        pen_y = self.yw + guy.yw - abs(dy)
        if 0.0 < pen_y:
            dx = guy.pos.x - self.pos.x
            pen_x = self.xw + guy.xw - abs(dx)
            if 0.0 < pen_x:
                if pen_y < pen_x:
                    if dy < 0.0:
                        normal_y = -1.0
                        pen_y *= -1.0
                    else:
                        normal_y = 1.0
                    self.pos.y -= (1.0 - self.mass) * pen_y
                    guy.report_collision_object(0.0, self.mass * pen_y, 0.0, normal_y, self)
                else:
                    if dx < 0.0:
                        pen_x *= -1.0
                        normal_x = -1.0
                    else:
                        normal_x = 1.0
                    self.pos.x -= (1.0 - self.mass) * pen_x
                    guy.report_collision_object(self.mass * pen_x, 0.0, normal_x, 0.0, self)
                self.sleep_timer = 0
                if self.asleep:
                    self.asleep = False


@dataclass(slots=True)
class FloorGuard:
    """Source-faithful n v1.4 floor guard (object type 4).

    Floor guards are always members of ObjectManager's update list.  While
    idle they watch the player's *stored* tile cell from the previous player
    tick.  Entering the same row anywhere inside the source-computed activation
    span switches the guard to chase mode; movement begins on the following
    frame because objects.Tick() calls the currently selected Update method only
    once per frame.  Contact is a strict circle-overlap electric kill and is
    tested later during Player.Tick(), after the guard has already moved.
    """

    pos: Vec2
    r: float
    speed: float
    dir: int
    min_x: float
    max_x: float
    mini: int
    maxi: int
    cell_i: int
    cell_j: int
    chasing: bool = False
    load_index: int = 0

    @classmethod
    def from_spec(
        cls,
        spec: ObjectSpec,
        tiles: TileMap,
        edge_overrides: EdgeOverrides | None = None,
    ) -> "FloorGuard":
        if len(spec.params) != 3:
            raise ValueError(
                f"FloorGuardObject expects 3 parameters, got {len(spec.params)}"
            )

        x, y, _dir_param = spec.params
        radius = tiles.xw * 0.5
        speed = tiles.xw * 0.4285714285714286

        # Source calls AddToGrid/Moved before snapping y, so its initial cell is
        # determined from the serialized position.  The supplied levels place
        # guards in the same row after the snap, but preserving this order also
        # matches malformed/custom data.
        cell = tiles.get_tile_xy(x, y)
        snapped_y = cell.pos.y + cell.yw - radius

        # The original ActionScript accidentally tests the unqualified global
        # ``dir`` instead of params[2].  In the traced game this global is
        # undefined, so the comparison is false and every guard initializes to
        # +1.  StartChasing overwrites dir as soon as movement is activated.
        direction = 1

        # Init first walks right until either a non-empty tile or a non-solid
        # downward edge is found.  Crucially, it then walks LEFT from that
        # stopping cell without resetting the cursor to the guard's own cell.
        cursor = cell
        while True:
            cursor = tiles.get(cursor.i + 1, cursor.j)
            if (
                TID_EMPTY < cursor.tile_id
                or tiles.edge(cursor, EDGE_D, edge_overrides) != EID_SOLID
            ):
                max_x = cursor.pos.x - cursor.xw - radius
                break

        while True:
            cursor = tiles.get(cursor.i - 1, cursor.j)
            if (
                TID_EMPTY < cursor.tile_id
                or tiles.edge(cursor, EDGE_D, edge_overrides) != EID_SOLID
            ):
                min_x = cursor.pos.x + cursor.xw + radius
                break

        # The activation range is intentionally different from the movement
        # support range: it only looks for non-empty tiles and ignores eD.
        mini = cell.i
        maxi = cell.i
        cursor = cell
        while True:
            cursor = tiles.get(cursor.i + 1, cursor.j)
            if TID_EMPTY < cursor.tile_id:
                break
            maxi += 1

        cursor = cell
        while True:
            cursor = tiles.get(cursor.i - 1, cursor.j)
            if TID_EMPTY < cursor.tile_id:
                break
            mini -= 1

        return cls(
            pos=Vec2(x, snapped_y),
            r=radius,
            speed=speed,
            dir=direction,
            min_x=min_x,
            max_x=max_x,
            mini=mini,
            maxi=maxi,
            cell_i=cell.i,
            cell_j=cell.j,
            chasing=False,
            load_index=spec.load_index,
        )

    def clone(self) -> "FloorGuard":
        return FloorGuard(
            pos=self.pos.copy(),
            r=self.r,
            speed=self.speed,
            dir=self.dir,
            min_x=self.min_x,
            max_x=self.max_x,
            mini=self.mini,
            maxi=self.maxi,
            cell_i=self.cell_i,
            cell_j=self.cell_j,
            chasing=self.chasing,
            load_index=self.load_index,
        )

    def start_chasing(self, player: "Player") -> None:
        self.chasing = True
        if player.cell_i < self.cell_i:
            self.dir = -1
        elif self.cell_i < player.cell_i:
            self.dir = 1
        else:
            # Source calls StopChasing when both occupy the same column.
            self.chasing = False

    def update(self, player: "Player", tiles: TileMap) -> None:
        if not self.chasing:
            if self.cell_j == player.cell_j and self.mini <= player.cell_i <= self.maxi:
                self.start_chasing(player)
            return

        if self.dir < 0:
            if abs(self.pos.x - self.min_x) < self.speed:
                self.pos.x = self.min_x
                self.chasing = False
            else:
                self.pos.x += self.dir * self.speed
        else:
            if abs(self.max_x - self.pos.x) < self.speed:
                self.pos.x = self.max_x
                self.chasing = False
            else:
                self.pos.x += self.dir * self.speed

        # objects.Moved(this) runs after both movement and endpoint snapping.
        self.cell_i = _floor(self.pos.x / tiles.tw)
        self.cell_j = _floor(self.pos.y / tiles.th)

    def test_player(self, guy: "Player") -> None:
        dx = self.pos.x - guy.pos.x
        dy = self.pos.y - guy.pos.y
        if math.sqrt(dx * dx + dy * dy) < self.r + guy.r:
            guy.dead = True


class DroneBase:
    """Shared tile-centre navigation used by all n v1.4 drone weapons.

    Weapon subclasses provide their own firing/contact behaviour. Zap drones
    additionally override the arrival and movement-speed hooks for chaser AI.
    """

    @property
    def cur_dir_v(self) -> Vec2:
        # Keep the fresh Vec2 returned by the original API, but avoid building
        # a four-entry dictionary on every moving-drone tick.
        if self.cur_dir == AI_DIR_R:
            return Vec2(1.0, 0.0)
        if self.cur_dir == AI_DIR_D:
            return Vec2(0.0, 1.0)
        if self.cur_dir == AI_DIR_L:
            return Vec2(-1.0, 0.0)
        if self.cur_dir == AI_DIR_U:
            return Vec2(0.0, -1.0)
        raise KeyError(self.cur_dir)

    def _move_list(self) -> tuple[int, int, int, int]:
        if self.move_type == DRONEMOVE_SURFACEFOLLOW_CW:
            return MOVE_LIST_SURFACE_CW
        if self.move_type == DRONEMOVE_SURFACEFOLLOW_CCW:
            return MOVE_LIST_SURFACE_CCW
        if self.move_type == DRONEMOVE_WANDER_CCW:
            return MOVE_LIST_CHUCHU_CCW
        return MOVE_LIST_CHUCHU_CW

    @staticmethod
    def _rotate_dir(cur_dir: int, rotation: int) -> int:
        if rotation < AI_ROT_0 or AI_ROT_270 < rotation:
            return cur_dir
        return (cur_dir + rotation) % 4

    def _test_edge(
        self,
        direction: int,
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> bool:
        grid = tiles.grid
        cell = grid[self.cell_i][self.cell_j]
        if direction < AI_DIR_R or AI_DIR_U < direction:
            return False
        side, di, dj = DRONE_EDGE_INFO[direction]
        if edge_overrides:
            edge_value = edge_overrides.get(cell.edge_keys[side])
            if edge_value is None:
                edge_value = cell.edges[side]
        else:
            edge_value = cell.edges[side]
        if edge_value != EID_OFF:
            return False
        next_cell = grid[cell.i + di][cell.j + dj]
        self.goal.x = next_cell.pos.x
        self.goal.y = next_cell.pos.y
        return True

    def _get_new_goal_simple(
        self,
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
        move_list: tuple[int, int, int, int] | None = None,
    ) -> int:
        rotations = self._move_list() if move_list is None else move_list
        for rotation in rotations:
            direction = self._rotate_dir(self.cur_dir, rotation)
            if self._test_edge(direction, tiles, edge_overrides):
                return direction
        return self.cur_dir

    def _get_new_goal(self, tiles: TileMap, edge_overrides: EdgeOverrides) -> int:
        if self.move_type == DRONEMOVE_WANDER_ALTERNATING:
            rotations = MOVE_LIST_CHUCHU_CW if self.ai_counter2 == 0 else MOVE_LIST_CHUCHU_CCW
            direction = self._get_new_goal_simple(tiles, edge_overrides, rotations)
            if direction != self.cur_dir:
                self.ai_counter2 = 1 - self.ai_counter2
            return direction
        if self.move_type == DRONEMOVE_WANDER_RANDOM:
            rotations = MOVE_LIST_CHUCHU_CW if self.ai_counter % 2 == 0 else MOVE_LIST_CHUCHU_CCW
            direction = self._get_new_goal_simple(tiles, edge_overrides, rotations)
            if direction != self.cur_dir:
                self.ai_counter = 1 if self.ai_counter % 2 == 0 else 0
            return direction
        return self._get_new_goal_simple(tiles, edge_overrides)

    def _movement_speed(self) -> float:
        return self.speed

    def _on_reach_goal(
        self,
        player: "Player" | None,
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> None:
        self.cur_dir = self._get_new_goal(tiles, edge_overrides)

    def _update_move(
        self,
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
        player: "Player" | None = None,
    ) -> None:
        self.ai_counter += 1
        pos = self.pos
        goal = self.goal
        tw = tiles.tw
        th = tiles.th
        dx = goal.x - pos.x
        dy = goal.y - pos.y
        speed = self.speed
        if dx * dx + dy * dy < speed * speed:
            pos.x = goal.x
            pos.y = goal.y
            self._on_reach_goal(player, tiles, edge_overrides)
            # Arrival can begin movement on either axis, so retain the full
            # source-style cell reindex at the snapped position.
            self.cell_i = _floor(pos.x / tw)
            self.cell_j = _floor(pos.y / th)
        else:
            # The tuple contains the same four literal vectors as the source
            # branch below, without repeatedly testing all four directions.
            cur_dir = self.cur_dir
            if cur_dir < AI_DIR_R or AI_DIR_U < cur_dir:
                raise KeyError(cur_dir)
            direction_x, direction_y = DRONE_DIR_VECTORS[cur_dir]
            # The only current caller that supplies ``player`` is ZapDrone,
            # whose source path doubles speed while its axis chase is active.
            # Keep the non-chasing base path allocation/dispatch free while
            # retaining ``_movement_speed`` for direct API callers and future
            # non-standard DroneBase subclasses.
            if player is None:
                move_speed = speed
            elif type(self) is ZapDrone:
                move_speed = speed * (2.0 if self.is_chasing else 1.0)
            else:
                move_speed = self._movement_speed()
            pos.x += direction_x * move_speed
            pos.y += direction_y * move_speed
            # A moving drone follows one cardinal axis.  Its other cell index
            # is already exact and cannot change until a later turn.
            if direction_x:
                self.cell_i = _floor(pos.x / tw)
            else:
                self.cell_j = _floor(pos.y / th)


@dataclass(slots=True)
class LaserDrone(DroneBase):
    """Source-faithful n v1.4 laser drone.

    Laser drones do not collide physically with the player. They move in the
    ObjectManager update phase, periodically acquire the player through the
    shared thinker scheduler, lock a ray to the acquisition direction, then
    run the 30/80/40 prefire/firing/postfire state machine.
    """

    pos: Vec2
    goal: Vec2
    cur_dir: int
    move_type: int
    speed: float
    cell_i: int
    cell_j: int
    ai_counter: int = 0
    ai_counter2: int = 0
    mode: DroneMode = DroneMode.MOVING
    fire_delay_timer: int = 0
    laser_timer: int = 0
    view: Vec2 = field(default_factory=Vec2)
    targ: Vec2 = field(default_factory=Vec2)
    targ2: Vec2 = field(default_factory=Vec2)
    laser_len: float = 0.0
    load_index: int = 0
    r: float = APP_TILE_SCALE * 0.75
    prefire_delay: int = 30
    laser_rate: int = 80
    postfire_delay: int = 40

    @classmethod
    def from_spec(cls, spec: ObjectSpec, tiles: TileMap) -> "LaserDrone":
        if len(spec.params) != 6:
            raise ValueError(f"DroneObject expects 6 parameters, got {len(spec.params)}")
        x, y, move_type, _is_chaser, weapon_type, cur_dir = spec.params
        if int(weapon_type) != DRONEWEAP_LASER:
            raise ValueError("LaserDrone.from_spec requires a laser weapon drone")
        cell = tiles.get_tile_xy(x, y)
        pos = cell.pos.copy()
        base_speed = APP_TILE_SCALE * 0.07142857142857143
        return cls(
            pos=pos,
            goal=pos.copy(),
            cur_dir=int(cur_dir),
            move_type=int(move_type),
            speed=base_speed * 0.5,
            cell_i=cell.i,
            cell_j=cell.j,
            load_index=spec.load_index,
        )

    def clone(self) -> "LaserDrone":
        return LaserDrone(
            self.pos.copy(),
            self.goal.copy(),
            self.cur_dir,
            self.move_type,
            self.speed,
            self.cell_i,
            self.cell_j,
            self.ai_counter,
            self.ai_counter2,
            self.mode,
            self.fire_delay_timer,
            self.laser_timer,
            self.view.copy(),
            self.targ.copy(),
            self.targ2.copy(),
            self.laser_len,
            self.load_index,
            self.r,
            self.prefire_delay,
            self.laser_rate,
            self.postfire_delay,
        )

    def _start_firing(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
        view: Vec2,
    ) -> None:
        self.mode = DroneMode.PREFIRE
        self.fire_delay_timer = 0
        self.view.x = view.x
        self.view.y = view.y
        hit, target, _distance = collide_ray_tiles(
            tiles, self.pos, self.view, edge_overrides
        )
        if not hit:
            # The source level has a solid outer border, so a non-zero ray
            # should always terminate. Keep the acquisition point as a safe
            # fallback for malformed/nonstandard maps.
            target = self.view.copy()
        self.targ.x = target.x
        self.targ.y = target.y
        self.targ2.x = self.targ.x - self.pos.x
        self.targ2.y = self.targ.y - self.pos.y
        self.laser_len = math.sqrt(
            self.targ2.x * self.targ2.x + self.targ2.y * self.targ2.y
        )
        if self.laser_len == 0.0:
            self.mode = DroneMode.POSTFIRE
            self.fire_delay_timer = 0

    def think(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> bool:
        """Run Think_TargetPlayer; return True if the drone leaves think list."""
        detected, view = query_ray_circle(
            tiles,
            self.pos,
            player.pos,
            player.pos,
            player.r,
            edge_overrides,
        )
        self.view.x = view.x
        self.view.y = view.y
        if detected:
            self._start_firing(player, tiles, edge_overrides, view)
            return True
        return False

    def update(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> bool:
        """Update the drone; return True when StartMoving re-adds its thinker."""
        if self.mode == DroneMode.MOVING:
            self._update_move(tiles, edge_overrides)
            return False

        if self.mode == DroneMode.PREFIRE:
            self.fire_delay_timer += 1
            if self.prefire_delay <= self.fire_delay_timer:
                self.mode = DroneMode.FIRING
                self.laser_len *= self.laser_len
                self.laser_timer = 0
            return False

        if self.mode == DroneMode.FIRING:
            vx = player.pos.x - self.pos.x
            vy = player.pos.y - self.pos.y
            projection = vx * self.targ2.x + vy * self.targ2.y
            projection /= self.laser_len
            if projection < 0.0:
                closest_x = self.pos.x
                closest_y = self.pos.y
            elif projection < 1.0:
                closest_x = self.pos.x + projection * self.targ2.x
                closest_y = self.pos.y + projection * self.targ2.y
            else:
                closest_x = self.targ.x
                closest_y = self.targ.y
            dx = closest_x - player.pos.x
            dy = closest_y - player.pos.y
            if math.sqrt(dx * dx + dy * dy) < player.r:
                self.mode = DroneMode.POSTFIRE
                self.fire_delay_timer = 0
                player.dead = True
                return False
            self.laser_timer += 1
            if self.laser_rate <= self.laser_timer:
                self.mode = DroneMode.POSTFIRE
                self.fire_delay_timer = 0
            return False

        self.fire_delay_timer += 1
        if self.postfire_delay <= self.fire_delay_timer:
            self.mode = DroneMode.MOVING
            return True
        return False

    def test_player(self, _guy: "Player") -> None:
        # DroneObject.TestVsPlayer is empty for laser drones.
        return


@dataclass(slots=True)
class ChaingunDrone(DroneBase):
    """Source-faithful n v1.4 chaingun drone.

    Chaingun drones share the normal drone movement and round-robin targeting
    scheduler.  On acquisition they track the player for 35 frames, lock aim
    at the end of prefire, then fire a deterministic spread burst at six-frame
    intervals.  The burst size/spread are functions of the absolute game frame.
    """

    pos: Vec2
    goal: Vec2
    cur_dir: int
    move_type: int
    speed: float
    cell_i: int
    cell_j: int
    ai_counter: int = 0
    ai_counter2: int = 0
    mode: DroneMode = DroneMode.MOVING
    fire_delay_timer: int = 0
    chaingun_timer: int = 0
    chaingun_max_num: int = 8
    chaingun_cur_num: int = 0
    chaingun_spread: float = 0.3
    view: Vec2 = field(default_factory=Vec2)
    targ: Vec2 = field(default_factory=Vec2)
    targ2: Vec2 = field(default_factory=Vec2)
    targ3: Vec2 = field(default_factory=Vec2)
    load_index: int = 0
    r: float = APP_TILE_SCALE * 0.75
    prefire_delay: int = 35
    chaingun_rate: int = 6
    postfire_delay: int = 60

    @classmethod
    def from_spec(cls, spec: ObjectSpec, tiles: TileMap) -> "ChaingunDrone":
        if len(spec.params) != 6:
            raise ValueError(f"DroneObject expects 6 parameters, got {len(spec.params)}")
        x, y, move_type, _is_chaser, weapon_type, cur_dir = spec.params
        if int(weapon_type) != DRONEWEAP_CHAINGUN:
            raise ValueError("ChaingunDrone.from_spec requires a chaingun weapon drone")
        cell = tiles.get_tile_xy(x, y)
        pos = cell.pos.copy()
        base_speed = APP_TILE_SCALE * 0.07142857142857143
        return cls(
            pos=pos,
            goal=pos.copy(),
            cur_dir=int(cur_dir),
            move_type=int(move_type),
            speed=base_speed * 0.75,
            cell_i=cell.i,
            cell_j=cell.j,
            load_index=spec.load_index,
        )

    def clone(self) -> "ChaingunDrone":
        return ChaingunDrone(
            self.pos.copy(),
            self.goal.copy(),
            self.cur_dir,
            self.move_type,
            self.speed,
            self.cell_i,
            self.cell_j,
            self.ai_counter,
            self.ai_counter2,
            self.mode,
            self.fire_delay_timer,
            self.chaingun_timer,
            self.chaingun_max_num,
            self.chaingun_cur_num,
            self.chaingun_spread,
            self.view.copy(),
            self.targ.copy(),
            self.targ2.copy(),
            self.targ3.copy(),
            self.load_index,
            self.r,
            self.prefire_delay,
            self.chaingun_rate,
            self.postfire_delay,
        )

    def _start_firing(self, view: Vec2) -> None:
        self.mode = DroneMode.PREFIRE
        self.fire_delay_timer = 0
        self.view.x = view.x
        self.view.y = view.y

    def think(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> bool:
        """Run Think_TargetPlayer; return True if the drone leaves think list."""
        detected, view = query_ray_circle(
            tiles,
            self.pos,
            player.pos,
            player.pos,
            player.r,
            edge_overrides,
        )
        self.view.x = view.x
        self.view.y = view.y
        if detected:
            self._start_firing(view)
            return True
        return False

    def _fire_chaingun(self, player: "Player", game_time: int) -> None:
        self.chaingun_timer = 0
        self.chaingun_max_num = 4 + game_time % 5
        self.chaingun_spread = 0.1 + 0.1 * (1 + game_time % 3)
        self.chaingun_cur_num = 0
        self.mode = DroneMode.FIRING

        dx = player.pos.x - self.pos.x
        dy = player.pos.y - self.pos.y
        distance = math.sqrt(dx * dx + dy * dy)
        if distance == 0.0:
            self.mode = DroneMode.POSTFIRE
            self.fire_delay_timer = 0
            return
        dx /= distance
        dy /= distance
        self.targ.x = dx
        self.targ.y = dy

        player_dx = player.pos.x - player.oldpos.x
        player_dy = player.pos.y - player.oldpos.y
        side_dot = player_dx * -dy + player_dy * dx
        if side_dot < 0.0:
            self.targ2.x = dy
            self.targ2.y = -dx
        else:
            self.targ2.x = -dy
            self.targ2.y = dx

    def update(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
        game_time: int,
    ) -> bool:
        """Update the drone; return True when StartMoving re-adds its thinker."""
        if self.mode == DroneMode.MOVING:
            self._update_move(tiles, edge_overrides)
            return False

        if self.mode == DroneMode.PREFIRE:
            self.fire_delay_timer += 1
            if self.prefire_delay <= self.fire_delay_timer:
                self._fire_chaingun(player, game_time)
            return False

        if self.mode == DroneMode.FIRING:
            self.chaingun_timer += 1
            if self.chaingun_rate <= self.chaingun_timer:
                self.chaingun_timer = 0
                # The source comparison is strictly maxNum < curNum.  It
                # therefore fires indices 0..maxNum inclusive, then waits one
                # more full rate interval before entering postfire.
                if self.chaingun_max_num < self.chaingun_cur_num:
                    self.mode = DroneMode.POSTFIRE
                    self.fire_delay_timer = 0
                    return False

                spread_offset = (
                    self.chaingun_cur_num / self.chaingun_max_num - 0.5
                ) * self.chaingun_spread
                shot_dx = self.targ.x + spread_offset * self.targ2.x
                shot_dy = self.targ.y + spread_offset * self.targ2.y
                self.targ3.x = self.pos.x + shot_dx
                self.targ3.y = self.pos.y + shot_dy
                hit_player, view = query_ray_circle(
                    tiles,
                    self.pos,
                    self.targ3,
                    player.pos,
                    player.r,
                    edge_overrides,
                )
                self.view.x = view.x
                self.view.y = view.y
                if hit_player:
                    # StopFiring_Chaingun runs before KillPlayer, but the
                    # remainder of Update_FiringChaingun still increments the
                    # shot counter after the kill call.
                    self.mode = DroneMode.POSTFIRE
                    self.fire_delay_timer = 0
                    player.dead = True
                self.chaingun_cur_num += 1
            return False

        self.fire_delay_timer += 1
        if self.postfire_delay <= self.fire_delay_timer:
            self.mode = DroneMode.MOVING
            return True
        return False

    def test_player(self, _guy: "Player") -> None:
        # DroneObject.TestVsPlayer is empty for chaingun drones.
        return


@dataclass(slots=True)
class Turret:
    """Source-faithful n v1.4 gauss turret (object type 3).

    Turrets are idle members of the shared round-robin thinker ring.  A clear
    QueryRayObj line of sight starts target tracking and inserts the turret into
    ObjectManager's update list.  The crosshair follows the player's one-frame
    extrapolated position, with the source distance bands controlling both aim
    speed and the non-linear shot countdown.  Once the countdown passes below
    zero the aim point is locked for a ten-frame prefire; the turret leaves the
    thinker ring during that prefire, fires one instantaneous hard-bullet ray,
    then rejoins the thinker ring for a ten-frame postfire period.
    """

    pos: Vec2
    view: Vec2
    targ: Vec2
    aim: Vec2
    mode: TurretMode = TurretMode.WAITING
    aim_speed: float = 0.03
    shot_timer: float = 0.0
    fire_delay_timer: int = 0
    load_index: int = 0
    close_aim_speed: float = 0.05
    mid_aim_speed: float = 0.035
    far_aim_speed: float = 0.03
    outer_threshold: float = (APP_TILE_SCALE * 8.0) ** 2
    inner_threshold: float = (APP_TILE_SCALE * 2.0) ** 2
    mid_threshold: float = (0.25 * (APP_TILE_SCALE * 8.0) + 0.75 * (APP_TILE_SCALE * 2.0)) ** 2
    shot_rate: float = 60.0
    prefire_delay: int = 10
    postfire_delay: int = 10

    @classmethod
    def from_spec(cls, spec: ObjectSpec, tiles: TileMap) -> "Turret":
        if len(spec.params) != 2:
            raise ValueError(f"TurretObject expects 2 parameters, got {len(spec.params)}")
        x, y = spec.params
        outer = tiles.xw * 8.0
        inner = tiles.xw * 2.0
        mid = 0.25 * outer + 0.75 * inner
        pos = Vec2(x, y)
        return cls(
            pos=pos,
            view=Vec2(),
            targ=Vec2(),
            aim=pos.copy(),
            load_index=spec.load_index,
            outer_threshold=outer * outer,
            inner_threshold=inner * inner,
            mid_threshold=mid * mid,
        )

    def clone(self) -> "Turret":
        return Turret(
            self.pos.copy(),
            self.view.copy(),
            self.targ.copy(),
            self.aim.copy(),
            self.mode,
            self.aim_speed,
            self.shot_timer,
            self.fire_delay_timer,
            self.load_index,
            self.close_aim_speed,
            self.mid_aim_speed,
            self.far_aim_speed,
            self.outer_threshold,
            self.inner_threshold,
            self.mid_threshold,
            self.shot_rate,
            self.prefire_delay,
            self.postfire_delay,
        )

    @property
    def updating(self) -> bool:
        return self.mode != TurretMode.WAITING

    @property
    def thinking(self) -> bool:
        return self.mode != TurretMode.PREFIRE

    def _line_of_sight(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> bool:
        detected, view = query_ray_circle(
            tiles,
            self.pos,
            player.pos,
            player.pos,
            player.r,
            edge_overrides,
        )
        self.view.x = view.x
        self.view.y = view.y
        return detected

    def _start_targeting(self) -> None:
        self.mode = TurretMode.TARGETING
        self.aim_speed = self.far_aim_speed
        self.aim.x = self.pos.x
        self.aim.y = self.pos.y
        self.shot_timer = self.shot_rate

    def _stop_targeting(self) -> None:
        self.mode = TurretMode.WAITING

    def _keep_targeting(self) -> None:
        # Source KeepTargetting does not reset aim or aimSpeed; only the shot
        # timer and Update/Think callbacks are restored.
        self.mode = TurretMode.TARGETING
        self.shot_timer = self.shot_rate

    def think(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> str | None:
        """Run Think_Waiting/Think_Targetting.

        Return ``"start_update"`` when StartTargetting calls StartUpdate, and
        ``"end_update"`` when StopTargetting calls EndUpdate.  Turrets only
        leave/rejoin the thinker ring from their Update methods, not Think.
        """
        detected = self._line_of_sight(player, tiles, edge_overrides)
        if self.mode == TurretMode.WAITING:
            if detected:
                self._start_targeting()
                return "start_update"
            return None

        # POSTFIRE and TARGETING both use Think_Targetting.  PREFIRE is absent
        # from the thinker ring and should never be dispatched here.
        if self.mode in (TurretMode.TARGETING, TurretMode.POSTFIRE) and not detected:
            self._stop_targeting()
            return "end_update"
        return None

    def _update_targeting(self, player: "Player", frame: int) -> bool:
        predicted_x = 2.0 * player.pos.x - player.oldpos.x
        predicted_y = 2.0 * player.pos.y - player.oldpos.y
        error_x = self.aim.x - predicted_x
        error_y = self.aim.y - predicted_y

        # The source computes the distance band from the pre-update error, then
        # moves aim using the speed selected on the *previous* frame.
        self.aim.x -= self.aim_speed * error_x
        self.aim.y -= self.aim_speed * error_y
        distance_sq = error_x * error_x + error_y * error_y

        if self.outer_threshold < distance_sq:
            self.aim_speed = self.far_aim_speed
            return False

        if distance_sq < self.inner_threshold:
            # Deliberately preserve aim_speed in the innermost band.
            self.shot_timer -= 2 + frame % 4
        elif distance_sq < self.mid_threshold:
            self.aim_speed = self.close_aim_speed
            self.shot_timer -= 1 + frame % 2
        else:
            self.aim_speed = self.mid_aim_speed
            self.shot_timer -= 0.5

        if self.shot_timer < 0.0:
            self.shot_timer = self.shot_rate
            self.mode = TurretMode.PREFIRE
            self.fire_delay_timer = 0
            # StartFiring calls EndThink(this).
            return True
        return False

    def _fire(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> bool:
        # Fire shoots through the locked aim point, not at the player's current
        # position. QueryRayObj is an infinite ray in that direction.
        hit_player, target = query_ray_circle(
            tiles,
            self.pos,
            self.aim,
            player.pos,
            player.r,
            edge_overrides,
        )
        self.targ.x = target.x
        self.targ.y = target.y
        if hit_player:
            player.dead = True
        return hit_player

    def _stop_firing(self) -> None:
        # StopFiring immediately StartThink()s the turret and enters postfire.
        self.mode = TurretMode.POSTFIRE
        self.fire_delay_timer = 0

    def update(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
        frame: int,
    ) -> str | None:
        """Run the current Update callback.

        Returns ``"end_think"`` for StartFiring, ``"start_think"`` for
        StopFiring, and ``"end_update"`` when postfire loses line of sight.
        """
        if self.mode == TurretMode.WAITING:
            return None

        if self.mode == TurretMode.TARGETING:
            if self._update_targeting(player, frame):
                return "end_think"
            return None

        if self.mode == TurretMode.PREFIRE:
            self.fire_delay_timer += 1
            if self.prefire_delay <= self.fire_delay_timer:
                if self._line_of_sight(player, tiles, edge_overrides):
                    self._fire(player, tiles, edge_overrides)
                self._stop_firing()
                return "start_think"
            return None

        # Update_PostFire runs while Think_Targetting is active.  At expiry it
        # performs its own LOS test before the shared thinker phase.
        self.fire_delay_timer += 1
        if self.postfire_delay <= self.fire_delay_timer:
            if not self._line_of_sight(player, tiles, edge_overrides):
                self._stop_targeting()
                return "end_update"
            self._keep_targeting()
        return None

    def test_player(self, _guy: "Player") -> None:
        # TurretObject is not inserted into the collision grid.
        return


@dataclass(slots=True)
class HomingLauncher:
    """Source-faithful n v1.4 homing rocket launcher.

    The launcher spends its idle state in the shared round-robin thinker ring.
    On a clear QueryRayObj line of sight it leaves that ring for a ten-frame
    prefire, launches from ``basepos``, then accelerates and steers once per
    ObjectManager update until the missile hits a tile/solid crossed edge or
    overlaps the ninja.  Terrain explosions immediately reinsert the launcher
    into the thinker ring, matching ``ExplodeMissile()->StartIdle()``.
    """

    basepos: Vec2
    pos: Vec2
    mdir: Vec2
    view: Vec2
    speed: float
    curaccel: float
    cell_i: int
    cell_j: int
    mode: HomingMode = HomingMode.IDLE
    fire_delay_timer: int = 0
    load_index: int = 0
    maxspeed: float = APP_TILE_SCALE * 0.2857142857142857
    startaccel: float = 0.1
    accelrate: float = 1.1
    turnrate: float = 0.1
    prefire_delay: int = 10

    @classmethod
    def from_spec(cls, spec: ObjectSpec, tiles: TileMap) -> "HomingLauncher":
        if len(spec.params) != 2:
            raise ValueError(
                f"HomingLauncherObject expects 2 parameters, got {len(spec.params)}"
            )
        x, y = spec.params
        cell = tiles.get_tile_xy(x, y)
        base = Vec2(x, y)
        return cls(
            basepos=base,
            pos=base.copy(),
            mdir=Vec2(7.0, 6.0),
            view=Vec2(4.0, 56.0),
            speed=0.0,
            curaccel=0.1,
            cell_i=cell.i,
            cell_j=cell.j,
            load_index=spec.load_index,
        )

    def clone(self) -> "HomingLauncher":
        return HomingLauncher(
            self.basepos.copy(),
            self.pos.copy(),
            self.mdir.copy(),
            self.view.copy(),
            self.speed,
            self.curaccel,
            self.cell_i,
            self.cell_j,
            self.mode,
            self.fire_delay_timer,
            self.load_index,
            self.maxspeed,
            self.startaccel,
            self.accelrate,
            self.turnrate,
            self.prefire_delay,
        )

    @property
    def grid_active(self) -> bool:
        # AddToGrid happens only in FireMissile and RemoveFromGrid in Explode.
        return self.mode == HomingMode.HOMING

    def think(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> bool:
        """Run HomingLauncherObject.Think; True means EndThink(this)."""
        detected, view = query_ray_circle(
            tiles,
            self.basepos,
            player.pos,
            player.pos,
            player.r,
            edge_overrides,
        )
        self.view.x = view.x
        self.view.y = view.y
        if detected:
            self.mode = HomingMode.PREFIRE
            self.fire_delay_timer = 0
            return True
        return False

    def _fire_missile(self, player: "Player", tiles: TileMap) -> None:
        self.curaccel = self.startaccel
        self.speed = 0.0
        self.pos.x = self.basepos.x
        self.pos.y = self.basepos.y
        cell = tiles.grid[_floor(self.pos.x / tiles.tw)][_floor(self.pos.y / tiles.th)]
        self.cell_i = cell.i
        self.cell_j = cell.j

        dx = player.pos.x - self.basepos.x
        dy = player.pos.y - self.basepos.y
        length = math.sqrt(dx * dx + dy * dy)
        if length != 0.0:
            self.mdir.x = dx / length
            self.mdir.y = dy / length
        self.mode = HomingMode.HOMING

    def _explode(self) -> None:
        self.mode = HomingMode.IDLE

    def _crossed_edge(
        self,
        tiles: TileMap,
        old_i: int,
        old_j: int,
        new_i: int,
        new_j: int,
        edge_overrides: EdgeOverrides,
    ) -> int:
        old_cell = tiles.grid[old_i][old_j]
        if new_i == old_i + 1 and new_j == old_j:
            side = EDGE_R
        elif new_i == old_i - 1 and new_j == old_j:
            side = EDGE_L
        elif new_i == old_i and new_j == old_j - 1:
            side = EDGE_U
        elif new_i == old_i and new_j == old_j + 1:
            side = EDGE_D
        else:
            return EID_OFF
        if edge_overrides:
            edge_value = edge_overrides.get(old_cell.edge_keys[side])
            if edge_value is not None:
                return edge_value
        return old_cell.edges[side]

    def update(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> bool:
        """Run the current Update method; True means StartIdle/StartThink."""
        if self.mode == HomingMode.IDLE:
            return False

        if self.mode == HomingMode.PREFIRE:
            self.fire_delay_timer += 1
            if self.prefire_delay <= self.fire_delay_timer:
                self._fire_missile(player, tiles)
            return False

        # Update_Homing preserves the ActionScript operation order exactly:
        # accelerate -> move -> point/tile test -> grid move/edge test -> steer.
        if self.speed < self.maxspeed:
            self.curaccel *= self.accelrate
            self.speed += self.curaccel
        else:
            self.speed = self.maxspeed

        self.pos.x += self.speed * self.mdir.x
        self.pos.y += self.speed * self.mdir.y

        # Point-query and cell tracking use the same post-move cell.  Reuse
        # that lookup so homing missiles do not floor/index the grid twice.
        cell = tiles.grid[
            _floor(self.pos.x / tiles.tw)
        ][_floor(self.pos.y / tiles.th)]
        if tiles.query_point(self.pos.x, self.pos.y, cell):
            self._explode()
            return True

        old_i = self.cell_i
        old_j = self.cell_j
        new_i = cell.i
        new_j = cell.j
        if new_i != old_i or new_j != old_j:
            self.cell_i = new_i
            self.cell_j = new_j
            if (
                self._crossed_edge(
                    tiles, old_i, old_j, new_i, new_j, edge_overrides
                )
                == EID_SOLID
            ):
                self._explode()
                return True

        predicted_x = 2.0 * player.pos.x - player.oldpos.x
        predicted_y = 2.0 * player.pos.y - player.oldpos.y
        rocket_next_x = self.pos.x + self.speed * self.mdir.x
        rocket_next_y = self.pos.y + self.speed * self.mdir.y
        dx = predicted_x - rocket_next_x
        dy = predicted_y - rocket_next_y
        target_len = math.sqrt(dx * dx + dy * dy)

        # A zero target vector would produce NaNs in AVM1. It does not occur in
        # the supplied trace; keeping the prior heading is the least invasive
        # deterministic fallback for malformed/synthetic test positions.
        if target_len == 0.0:
            return False
        dx /= target_len
        dy /= target_len

        cross = (-self.mdir.y) * dx + self.mdir.x * dy
        steer_x = cross * (-self.mdir.y)
        steer_y = cross * self.mdir.x
        self.mdir.x += steer_x * self.turnrate
        self.mdir.y += steer_y * self.turnrate

        direction_len = math.sqrt(self.mdir.x * self.mdir.x + self.mdir.y * self.mdir.y)
        if direction_len != 0.0:
            self.mdir.x /= direction_len
            self.mdir.y /= direction_len
        return False

    def test_player(self, guy: "Player") -> None:
        if self.mode != HomingMode.HOMING:
            return
        dx = guy.pos.x - self.pos.x
        dy = guy.pos.y - self.pos.y
        if math.sqrt(dx * dx + dy * dy) < guy.r:
            # KillPlayer runs before ExplodeMissile. Once the ninja is dead the
            # branch is terminal, so the death-specific StartIdle thinker
            # suppression has no further gameplay consequence here.
            guy.dead = True
            self._explode()


@dataclass(slots=True)
class ZapDrone(DroneBase):
    """Source-faithful n v1.4 zap drone movement, chasing, and contact kill."""

    pos: Vec2
    goal: Vec2
    cur_dir: int
    move_type: int
    speed: float
    cell_i: int
    cell_j: int
    ai_counter: int = 0
    ai_counter2: int = 0
    is_chaser: bool = False
    is_chasing: bool = False
    surface_future_dir: int | None = None
    surface_grab_pending: bool = False
    load_index: int = 0
    r: float = APP_TILE_SCALE * 0.75

    @classmethod
    def from_spec(cls, spec: ObjectSpec, tiles: TileMap) -> "ZapDrone":
        if len(spec.params) != 6:
            raise ValueError(f"DroneObject expects 6 parameters, got {len(spec.params)}")
        x, y, move_type, is_chaser, weapon_type, cur_dir = spec.params
        if int(weapon_type) != DRONEWEAP_ZAP:
            raise ValueError("ZapDrone.from_spec requires a zap weapon drone")
        cell = tiles.get_tile_xy(x, y)
        pos = cell.pos.copy()
        base_speed = APP_TILE_SCALE * 0.07142857142857143
        return cls(
            pos=pos,
            goal=pos.copy(),
            cur_dir=int(cur_dir),
            move_type=int(move_type),
            speed=base_speed * 2.0,
            cell_i=cell.i,
            cell_j=cell.j,
            is_chaser=bool(is_chaser),
            load_index=spec.load_index,
        )

    def clone(self) -> "ZapDrone":
        return ZapDrone(
            self.pos.copy(),
            self.goal.copy(),
            self.cur_dir,
            self.move_type,
            self.speed,
            self.cell_i,
            self.cell_j,
            self.ai_counter,
            self.ai_counter2,
            self.is_chaser,
            self.is_chasing,
            self.surface_future_dir,
            self.surface_grab_pending,
            self.load_index,
            self.r,
        )

    def _movement_speed(self) -> float:
        # Update_Move doubles an already doubled zap speed while actively
        # chasing a player along a clear row/column.
        return self.speed * (2.0 if self.is_chasing else 1.0)

    @staticmethod
    def _dir_edge(direction: int) -> tuple[int, int, int]:
        if direction < AI_DIR_R or AI_DIR_U < direction:
            raise ValueError(f"unknown AI direction {direction}")
        return DRONE_EDGE_INFO[direction]

    def _find_target(
        self,
        direction: int,
        target_cells: int,
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> bool:
        """Port DroneObject.FindTarget.

        The player only has to be reachable for ``target_cells`` cells. Once
        that is established, the goal extends past the player to the first wall.
        """
        side, di, dj = self._dir_edge(direction)
        distance = 0
        grid = tiles.grid
        cell = grid[self.cell_i][self.cell_j]

        while distance < target_cells:
            distance += 1
            if edge_overrides:
                edge_value = edge_overrides.get(cell.edge_keys[side])
                if edge_value is None:
                    edge_value = cell.edges[side]
            else:
                edge_value = cell.edges[side]
            if edge_value != EID_OFF:
                return False
            cell = grid[cell.i + di][cell.j + dj]

        while True:
            if edge_overrides:
                edge_value = edge_overrides.get(cell.edge_keys[side])
                if edge_value is None:
                    edge_value = cell.edges[side]
            else:
                edge_value = cell.edges[side]
            if edge_value != EID_OFF:
                break
            distance += 1
            cell = grid[cell.i + di][cell.j + dj]

        origin = grid[self.cell_i][self.cell_j]
        if direction == AI_DIR_R:
            self.goal.x = origin.pos.x + distance * (2.0 * origin.xw)
        elif direction == AI_DIR_D:
            self.goal.y = origin.pos.y + distance * (2.0 * origin.yw)
        elif direction == AI_DIR_L:
            self.goal.x = origin.pos.x - distance * (2.0 * origin.xw)
        else:  # AI_DIR_U
            self.goal.y = origin.pos.y - distance * (2.0 * origin.yw)
        return True

    def _chase_axis_search(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> bool:
        cell_dx = player.cell_i - self.cell_i
        cell_dy = player.cell_j - self.cell_j

        if abs(cell_dx) < 1:
            target_cells = abs(cell_dy)
            if player.pos.y < self.pos.y:
                if self.cur_dir == AI_DIR_D:
                    return False
                direction = AI_DIR_U
            else:
                if self.cur_dir == AI_DIR_U:
                    return False
                direction = AI_DIR_D
        elif abs(cell_dy) < 1:
            target_cells = abs(cell_dx)
            if player.pos.x < self.pos.x:
                if self.cur_dir == AI_DIR_R:
                    return False
                direction = AI_DIR_L
            else:
                if self.cur_dir == AI_DIR_L:
                    return False
                direction = AI_DIR_R
        else:
            return False

        if not self._find_target(direction, target_cells, tiles, edge_overrides):
            return False

        self.cur_dir = direction
        if self.move_type < DRONEMOVE_WANDER_CW:
            self.surface_grab_pending = True
            rotation = (
                AI_ROT_270
                if self.move_type == DRONEMOVE_SURFACEFOLLOW_CW
                else AI_ROT_90
            )
            self.surface_future_dir = self._rotate_dir(direction, rotation)
        return True

    def _chase(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> bool:
        if not self.is_chaser:
            return False
        if self.surface_grab_pending:
            # Chase_SurfaceGrab restores Chase_AxisSearch, turns toward the
            # surface-following direction, then returns false. Update_Move then
            # immediately runs GetNewGoal from that direction.
            self.surface_grab_pending = False
            if self.surface_future_dir is not None:
                self.cur_dir = self.surface_future_dir
            return False
        return self._chase_axis_search(player, tiles, edge_overrides)

    def _on_reach_goal(
        self,
        player: "Player" | None,
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> None:
        if player is not None and self._chase(player, tiles, edge_overrides):
            self.is_chasing = True
        else:
            self.cur_dir = self._get_new_goal(tiles, edge_overrides)
            self.is_chasing = False

    def update(
        self,
        player: "Player",
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> None:
        self._update_move(tiles, edge_overrides, player)

    def test_player(self, guy: "Player") -> None:
        dx = self.pos.x - guy.pos.x
        dy = self.pos.y - guy.pos.y
        distance_sq = dx * dx + dy * dy
        contact_radius = self.r + guy.r
        if distance_sq < contact_radius * contact_radius:
            # KillPlayer's impulse/contact-point arguments only matter after
            # death; the optimiser stops simulating a dead branch immediately.
            guy.dead = True


@dataclass(slots=True)
class Thwomp:
    """Source-faithful ``ThwompObject`` movement and player collision."""

    pos: Vec2
    anchor: Vec2
    fallgoal: Vec2
    goal: Vec2
    dir: Vec2
    dir_enum: int
    mini: int
    minj: int
    maxi: int
    maxj: int
    xw: float = APP_TILE_SCALE * 0.75
    yw: float = APP_TILE_SCALE * 0.75
    movedir: int = 1
    fallspeed: float = APP_TILE_SCALE * 0.3571428571428572
    raisespeed: float = APP_TILE_SCALE * 0.1428571428571429
    speed: float = APP_TILE_SCALE * 0.3571428571428572
    is_moving: bool = False
    mode: int = 0  # 0 waiting, 1 moving
    load_index: int = 0

    @classmethod
    def from_spec(cls, spec: ObjectSpec, tiles: TileMap) -> "Thwomp":
        if len(spec.params) != 3:
            raise ValueError(f"ThwompObject expects 3 parameters, got {len(spec.params)}")
        x, y, enum = spec.params
        enum_i = int(enum)
        direction = {
            AI_DIR_R: Vec2(1.0, 0.0),
            AI_DIR_D: Vec2(0.0, 1.0),
            AI_DIR_L: Vec2(-1.0, 0.0),
            AI_DIR_U: Vec2(0.0, -1.0),
        }[enum_i]
        pos = Vec2(x, y)
        anchor = pos.copy()
        cell = tiles.get_tile_xy(x, y)
        gx, gy = x, y

        if enum_i == AI_DIR_U:
            probe = tiles.get(cell.i, cell.j - 1)
            while probe.tile_id == TID_EMPTY:
                gy -= 2.0 * cell.yw
                probe = tiles.get(probe.i, probe.j - 1)
            gy -= APP_TILE_SCALE * 0.75
            gy -= y - cell.pos.y
        elif enum_i == AI_DIR_D:
            probe = tiles.get(cell.i, cell.j + 1)
            while probe.tile_id == TID_EMPTY:
                gy += 2.0 * cell.yw
                probe = tiles.get(probe.i, probe.j + 1)
            gy += APP_TILE_SCALE * 0.75
            gy -= y - cell.pos.y
        elif enum_i == AI_DIR_L:
            probe = tiles.get(cell.i - 1, cell.j)
            while probe.tile_id == TID_EMPTY:
                gx -= 2.0 * cell.xw
                probe = tiles.get(probe.i - 1, probe.j)
            gx -= APP_TILE_SCALE * 0.75
            gx -= x - cell.pos.x
        elif enum_i == AI_DIR_R:
            probe = tiles.get(cell.i + 1, cell.j)
            while probe.tile_id == TID_EMPTY:
                gx += 2.0 * cell.xw
                probe = tiles.get(probe.i + 1, probe.j)
            gx += APP_TILE_SCALE * 0.75
            gx -= x - cell.pos.x
        else:
            raise ValueError(f"invalid Thwomp direction enum {enum_i}")

        fallgoal = Vec2(gx, gy)
        goal_cell = tiles.get_tile_xy(gx, gy)
        mini = cell.i
        minj = cell.j
        maxi = goal_cell.i
        maxj = goal_cell.j
        if direction.x < 0.0:
            mini, maxi = maxi, mini
        if direction.y < 0.0:
            minj, maxj = maxj, minj

        return cls(
            pos=pos,
            anchor=anchor,
            fallgoal=fallgoal,
            goal=fallgoal.copy(),
            dir=direction,
            dir_enum=enum_i,
            mini=mini,
            minj=minj,
            maxi=maxi,
            maxj=maxj,
            load_index=spec.load_index,
        )

    def clone(self) -> "Thwomp":
        return Thwomp(
            self.pos.copy(),
            self.anchor.copy(),
            self.fallgoal.copy(),
            self.goal.copy(),
            self.dir.copy(),
            self.dir_enum,
            self.mini,
            self.minj,
            self.maxi,
            self.maxj,
            self.xw,
            self.yw,
            self.movedir,
            self.fallspeed,
            self.raisespeed,
            self.speed,
            self.is_moving,
            self.mode,
            self.load_index,
        )

    def start_fall(self) -> None:
        self.is_moving = True
        self.speed = self.fallspeed
        self.movedir = 1
        self.goal.x = self.fallgoal.x
        self.goal.y = self.fallgoal.y
        self.mode = 1

    def start_raise(self) -> None:
        self.is_moving = True
        self.speed = self.raisespeed
        self.movedir = -1
        self.goal.x = self.anchor.x
        self.goal.y = self.anchor.y
        self.mode = 1

    def start_wait(self) -> None:
        self.is_moving = False
        self.mode = 0

    def update(self, player: "Player") -> None:
        mode = self.mode
        pos = self.pos
        if mode == 0:
            # ObjectManager.Tick() runs before Player.Tick(), so the source sees
            # the player's cell retained from the end of the previous tick.
            player_pos = player.pos
            if self.dir.x == 0.0:
                if abs(pos.x - player_pos.x) < 2.0 * (self.xw + player.xw):
                    if self.minj <= player.cell_j <= self.maxj:
                        self.start_fall()
            else:
                if abs(pos.y - player_pos.y) < 2.0 * (self.yw + player.yw):
                    if self.mini <= player.cell_i <= self.maxi:
                        self.start_fall()
            return

        dx = self.goal.x - self.pos.x
        dy = self.goal.y - self.pos.y
        distance2 = dx * dx + dy * dy
        if distance2 < self.speed * self.speed:
            pos.x = self.goal.x
            pos.y = self.goal.y
            if self.movedir == 1:
                self.start_raise()
            else:
                self.start_wait()
        else:
            pos.x += self.movedir * self.dir.x * self.speed
            pos.y += self.movedir * self.dir.y * self.speed

    def test_player(self, guy: "Player") -> None:
        dy = guy.pos.y - self.pos.y
        pen_y = self.yw + guy.yw - abs(dy)
        if pen_y <= 0.0:
            return
        dx = guy.pos.x - self.pos.x
        pen_x = self.xw + guy.xw - abs(dx)
        if pen_x <= 0.0:
            return

        if pen_y < pen_x:
            if dy < 0.0:
                if self.dir.y < 0.0:
                    guy.dead = True
                else:
                    guy.report_collision_object(0.0, -pen_y, 0.0, -1.0, self)
            else:
                if self.dir.y > 0.0:
                    guy.dead = True
                else:
                    guy.report_collision_object(0.0, pen_y, 0.0, 1.0, self)
        else:
            if dx < 0.0:
                if self.dir.x < 0.0:
                    guy.dead = True
                else:
                    guy.report_collision_object(-pen_x, 0.0, -1.0, 0.0, self)
            else:
                if self.dir.x > 0.0:
                    guy.dead = True
                else:
                    guy.report_collision_object(pen_x, 0.0, 1.0, 0.0, self)


@dataclass(slots=True)
class TestDoor:
    """Source-order implementation of ``TestDoorObject``.

    Doors are zero-thickness dynamic tile edges.  Their mutable edge state is
    kept on the object rather than written into ``TileMap`` so cloned search
    branches remain independent while sharing the immutable map geometry.
    """

    pos: Vec2
    r: float
    vert: int
    is_trap: bool
    door_i: int
    door_j: int
    is_locked: bool
    delta_i: int
    delta_j: int
    door_pos: Vec2
    door_size: float
    front_key: EdgeKey
    back_key: EdgeKey
    open_state_front: int
    open_state_back: int
    is_open: bool
    door_timer: int = 0
    max_timer: int = 5
    updating: bool = False
    trigger_active: bool = True
    load_index: int = 0

    @classmethod
    def from_spec(
        cls,
        spec: ObjectSpec,
        tiles: TileMap,
        edge_overrides: EdgeOverrides,
    ) -> "TestDoor":
        if len(spec.params) != 9:
            raise ValueError(
                f"TestDoorObject expects 9 parameters, got {len(spec.params)}"
            )

        x, y, vert, is_trap, base_i, base_j, is_locked, delta_i, delta_j = spec.params
        vert_i = int(vert)
        trap = bool(is_trap)
        locked = bool(is_locked)
        di = int(delta_i)
        dj = int(delta_j)
        door_i = int(base_i) + di
        door_j = int(base_j) + dj
        door_cell = tiles.get(door_i, door_j)
        door_pos = door_cell.pos.copy()

        if vert_i == 1:
            door_pos.y += door_cell.yw
            door_size = door_cell.xw
            front_key = (door_i, door_j, EDGE_D)
            back_key = (door_i, door_j + 1, EDGE_U)
        else:
            door_pos.x += door_cell.xw
            door_size = door_cell.yw
            front_key = (door_i, door_j, EDGE_R)
            back_key = (door_i + 1, door_j, EDGE_L)

        front_cell = tiles.get(front_key[0], front_key[1])
        back_cell = tiles.get(back_key[0], back_key[1])
        # Init captures the edge values at the moment this object is spawned.
        # This matters in the one built-in level where two doors share an edge.
        open_front = tiles.edge(front_cell, front_key[2], edge_overrides)
        open_back = tiles.edge(back_cell, back_key[2], edge_overrides)

        if locked:
            # A locked door's object position is its circular switch.
            pos = Vec2(x, y)
            radius = tiles.xw * 0.4166666666666667
            trap = False
            initially_open = False
        elif trap:
            # A trap door begins open and its circular trigger closes it once.
            pos = Vec2(x, y)
            radius = tiles.xw * 0.4166666666666667
            initially_open = True
        else:
            # A normal proximity door uses the doorway itself as the trigger.
            pos = door_pos.copy()
            radius = tiles.xw * 0.8333333333333334
            initially_open = False

        door = cls(
            pos=pos,
            r=radius,
            vert=vert_i,
            is_trap=trap,
            door_i=door_i,
            door_j=door_j,
            is_locked=locked,
            delta_i=di,
            delta_j=dj,
            door_pos=door_pos,
            door_size=door_size,
            front_key=front_key,
            back_key=back_key,
            open_state_front=open_front,
            open_state_back=open_back,
            is_open=initially_open,
            load_index=spec.load_index,
        )
        # Source calls UpdateEdges() at the end of Init().
        door.write_edge_overrides(edge_overrides)
        return door

    def clone(self) -> "TestDoor":
        return TestDoor(
            pos=self.pos.copy(),
            r=self.r,
            vert=self.vert,
            is_trap=self.is_trap,
            door_i=self.door_i,
            door_j=self.door_j,
            is_locked=self.is_locked,
            delta_i=self.delta_i,
            delta_j=self.delta_j,
            door_pos=self.door_pos.copy(),
            door_size=self.door_size,
            front_key=self.front_key,
            back_key=self.back_key,
            open_state_front=self.open_state_front,
            open_state_back=self.open_state_back,
            is_open=self.is_open,
            door_timer=self.door_timer,
            max_timer=self.max_timer,
            updating=self.updating,
            trigger_active=self.trigger_active,
            load_index=self.load_index,
        )

    def update(self, edge_overrides: EdgeOverrides) -> None:
        # Only an open, ordinary trek door is placed on the source update list.
        if not self.updating:
            return
        self.door_timer += 1
        if self.max_timer < self.door_timer:
            self.close(edge_overrides)

    def test_player(self, guy: "Player", edge_overrides: EdgeOverrides) -> None:
        if not self.trigger_active:
            return
        dx = self.pos.x - guy.pos.x
        dy = self.pos.y - guy.pos.y
        if math.sqrt(dx * dx + dy * dy) < self.r + guy.r:
            self.door_timer = 0
            if self.is_trap:
                self.close(edge_overrides)
                # Source removes the trigger from the object grid and nulls
                # TestVsPlayer, so the trap can never reopen itself.
                self.trigger_active = False
            elif not self.is_open:
                self.open(edge_overrides)

    def open(self, edge_overrides: EdgeOverrides) -> None:
        self.is_open = True
        self.write_edge_overrides(edge_overrides)
        if not self.is_trap and not self.is_locked:
            self.updating = True

    def close(self, edge_overrides: EdgeOverrides) -> None:
        self.updating = False
        self.is_open = False
        self.write_edge_overrides(edge_overrides)

    def write_edge_overrides(self, overrides: EdgeOverrides) -> None:
        if self.is_open:
            overrides[self.front_key] = self.open_state_front
            overrides[self.back_key] = self.open_state_back
        else:
            overrides[self.front_key] = EID_SOLID
            overrides[self.back_key] = EID_SOLID


PhysicsObject = OneWayPlatform | LaunchPad | BounceBlock | FloorGuard | ZapDrone | LaserDrone | ChaingunDrone | HomingLauncher | Turret | Thwomp | TestDoor

# Player collision callbacks mutate their object only for these types.  The
# other physics objects either are immutable descriptors or only modify the
# player's state, so copy-on-write branches can keep sharing them through the
# collision traversal.
_PLAYER_COLLISION_MUTABLE_TYPES = (BounceBlock, HomingLauncher, TestDoor)


def _clone_physics_objects(objects: Sequence[PhysicsObject]) -> list[PhysicsObject]:
    """Clone mutable physics objects while sharing immutable descriptors.

    One-way platforms and launch pads contain no simulation-mutated state;
    sharing them across branches is equivalent to cloning them for all engine
    operations and avoids copying their vectors in every search branch.
    """
    return [
        obj if type(obj) in (OneWayPlatform, LaunchPad) else obj.clone()
        for obj in objects
    ]


@dataclass(slots=True)
class Player:
    pos: Vec2
    oldpos: Vec2
    r: float = APP_TILE_SCALE * 0.8333333333333334
    xw: float = APP_TILE_SCALE * 0.8333333333333334
    yw: float = APP_TILE_SCALE * 0.8333333333333334

    maxspeed_air: float = field(init=False)
    maxspeed_ground: float = field(init=False)
    ground_accel: float = 0.15
    air_accel: float = 0.1
    norm_grav: float = 0.15
    jump_grav: float = 0.025
    norm_drag: float = 0.99
    win_drag: float = 0.8
    wall_friction: float = 0.13
    skid_friction: float = 0.92
    stand_friction: float = 0.8
    jump_amt: float = 1.0
    jump_y_bias: float = 2.0
    max_jump_time: int = 30
    terminal_vel: float = field(init=False)

    g: float = 0.15
    d: float = 0.99
    state: PlayerState = PlayerState.STANDING
    jump_timer: int = 0
    was_in_air: bool = True
    in_air: bool = True
    near_wall: bool = False
    wall_n: Vec2 = field(default_factory=Vec2)
    floor_n: Vec2 = field(default_factory=Vec2)
    floor_n0: Vec2 = field(default_factory=Vec2)
    floor_n1: Vec2 = field(default_factory=Vec2)
    old_v: Vec2 = field(default_factory=Vec2)
    floor_count: int = 0
    dead: bool = False
    previous_jump_held: bool = False
    celeb_was_in_air: bool = False
    # Instrumentation only: number of times Player.jump() has actually run.
    # This deliberately is not part of state_key(), because it has no effect on
    # future physics. Search code can compare the counter before/after a frame
    # to distinguish a successful jump from a jump button press that did nothing.
    jump_events: int = 0
    # Tile-grid cell retained by ObjectManager.Moved(); thwomp AI reads this
    # before the player integrates the next frame.
    cell_i: int = 0
    cell_j: int = 0

    def __post_init__(self) -> None:
        self.maxspeed_air = self.r * 0.5
        self.maxspeed_ground = self.r * 0.5
        self.terminal_vel = self.r * 0.9

    @classmethod
    def spawn(cls, x: float, y: float) -> "Player":
        p = Vec2(x, y)
        player = cls(pos=p.copy(), oldpos=p.copy())
        player.cell_i = _floor(x / (2.0 * APP_TILE_SCALE))
        player.cell_j = _floor(y / (2.0 * APP_TILE_SCALE))
        return player

    def clone(self) -> "Player":
        # Explicit copying avoids copy/deepcopy overhead in search loops.
        # Construct the slotted object directly: Player.spawn() would allocate
        # default vectors and run initialization that this clone immediately
        # overwrites. Every mutable vector remains branch-local, while the
        # scalar physics configuration is preserved exactly.
        q = object.__new__(Player)
        q.pos = Vec2(self.pos.x, self.pos.y)
        q.oldpos = Vec2(self.oldpos.x, self.oldpos.y)
        q.r = self.r
        q.xw = self.xw
        q.yw = self.yw
        q.maxspeed_air = self.maxspeed_air
        q.maxspeed_ground = self.maxspeed_ground
        q.ground_accel = self.ground_accel
        q.air_accel = self.air_accel
        q.norm_grav = self.norm_grav
        q.jump_grav = self.jump_grav
        q.norm_drag = self.norm_drag
        q.win_drag = self.win_drag
        q.wall_friction = self.wall_friction
        q.skid_friction = self.skid_friction
        q.stand_friction = self.stand_friction
        q.jump_amt = self.jump_amt
        q.jump_y_bias = self.jump_y_bias
        q.max_jump_time = self.max_jump_time
        q.terminal_vel = self.terminal_vel
        q.g = self.g
        q.d = self.d
        q.state = self.state
        q.jump_timer = self.jump_timer
        q.was_in_air = self.was_in_air
        q.in_air = self.in_air
        q.near_wall = self.near_wall
        q.wall_n = Vec2(self.wall_n.x, self.wall_n.y)
        q.floor_n = Vec2(self.floor_n.x, self.floor_n.y)
        q.floor_n0 = Vec2(self.floor_n0.x, self.floor_n0.y)
        q.floor_n1 = Vec2(self.floor_n1.x, self.floor_n1.y)
        q.old_v = Vec2(self.old_v.x, self.old_v.y)
        q.floor_count = self.floor_count
        q.dead = self.dead
        q.previous_jump_held = self.previous_jump_held
        q.celeb_was_in_air = self.celeb_was_in_air
        q.jump_events = self.jump_events
        q.cell_i = self.cell_i
        q.cell_j = self.cell_j
        return q

    @property
    def vx(self) -> float:
        return self.pos.x - self.oldpos.x

    @property
    def vy(self) -> float:
        return self.pos.y - self.oldpos.y

    def prepare_to_collide(self) -> None:
        self.old_v.x = self.pos.x - self.oldpos.x
        self.old_v.y = self.pos.y - self.oldpos.y
        self.was_in_air = self.in_air
        self.near_wall = False
        self.in_air = True
        self.floor_count = 0

    def report_collision_world(
        self, px: float, py: float, nx: float, ny: float, _tile: TileCell | None
    ) -> None:
        self.pos.x += px
        self.pos.y += py
        if 0.8 * (self.r * self.r) < px * px + py * py:
            self.dead = True
            return
        self._record_normal(nx, ny)

    def report_collision_object(
        self, px: float, py: float, nx: float, ny: float, _obj: object
    ) -> None:
        self.pos.x += px
        self.pos.y += py
        self._record_normal(nx, ny)

    def _record_normal(self, nx: float, ny: float) -> None:
        if ny == 0.0:
            self.near_wall = True
            self.wall_n.x = nx
            self.wall_n.y = ny
        elif ny < 0.0:
            if self.floor_count == 0:
                self.floor_n0.x = nx
                self.floor_n0.y = ny
                self.floor_count += 1
            else:
                # The original decompilation always executes this branch and
                # forces fCount to 2, retaining only the latest second normal.
                self.floor_count = 1
                self.floor_n1.x = nx
                self.floor_n1.y = ny
                self.floor_count += 1

    def handle_collisions(self, tiles: TileMap) -> None:
        if self.floor_count > 0:
            self.in_air = False
            if self.floor_count > 1:
                dot = self.floor_n0.x * self.floor_n1.x + self.floor_n0.y * self.floor_n1.y
                if dot > 0.9:
                    if not (
                        (self.floor_n0.x == self.floor_n.x and self.floor_n0.y == self.floor_n.y)
                        or (self.floor_n1.x == self.floor_n.x and self.floor_n1.y == self.floor_n.y)
                    ):
                        self.floor_n.x = self.floor_n1.x
                        self.floor_n.y = self.floor_n1.y
                else:
                    nx = 0.5 * (self.floor_n0.x + self.floor_n1.x)
                    ny = 0.5 * (self.floor_n0.y + self.floor_n1.y)
                    length = math.sqrt(nx * nx + ny * ny)
                    if length == 0.0:
                        self.floor_n.x = self.floor_n0.x
                        self.floor_n.y = self.floor_n0.y
                    else:
                        self.floor_n.x = nx / length
                        self.floor_n.y = ny / length
            else:
                self.floor_n.x = self.floor_n0.x
                self.floor_n.y = self.floor_n0.y

            if self.was_in_air:
                impact = self.old_v.x * self.floor_n.x + self.old_v.y * self.floor_n.y
                impact -= 2.0 * abs(self.floor_n.y)
                if self.old_v.y > 0.0 and impact < -self.terminal_vel:
                    self.dead = True

        if self.in_air and not self.near_wall:
            probe = self.r + 0.1
            if tiles.query_point(self.pos.x + probe, self.pos.y):
                self.near_wall = True
                self.wall_n.x = -1.0
                self.wall_n.y = 0.0
            elif tiles.query_point(self.pos.x - probe, self.pos.y):
                self.near_wall = True
                self.wall_n.x = 1.0
                self.wall_n.y = 0.0

    def _test_static_collider(
        self, entry: StaticCollider, state: StaticObjectState
    ) -> bool:
        """Test one active static collider; return whether it removed itself."""
        dx = entry.x - self.pos.x
        dy = entry.y - self.pos.y
        if math.sqrt(dx * dx + dy * dy) >= entry.r + self.r:
            return False

        bit = 1 << entry.state_index
        if entry.kind == StaticColliderKind.GOLD:
            state.collected_gold_mask |= bit
            state.gold_bonus_ticks += 80
            return True
        if entry.kind == StaticColliderKind.MINE:
            state.exploded_mine_mask |= bit
            self.dead = True
            return True
        if entry.kind == StaticColliderKind.EXIT_SWITCH:
            state.open_exit_mask |= bit
            return True

        self.celebrate()
        state.completed_exit_index = entry.state_index
        state.level_complete = True
        return False

    def step(
        self,
        inputs: InputFrame,
        tiles: TileMap,
        objects: Sequence[PhysicsObject] = (),
        edge_overrides: EdgeOverrides | None = None,
        static_world: StaticWorld | None = None,
        static_state: StaticObjectState | None = None,
        grid_state: ObjectGridState | None = None,
        object_lookup: dict[int, PhysicsObject] | None = None,
        scheduler_events: list[tuple[str, int]] | None = None,
        object_slots: Sequence[PhysicsObject | None] | None = None,
        object_type_slots: Sequence[type | None] | None = None,
        alternate_inputs: InputFrame | None = None,
        alternate_jump: bool = False,
        object_mutator: Callable[[int], None] | None = None,
        # SimulationState passes only the shared object UIDs whose collision
        # callbacks can mutate object state.  None retains the legacy callback
        # behaviour for direct Player.step() callers.
        shared_object_mask: int | None = None,
    ) -> "Player | None":
        if self.dead:
            return None

        # TickNormal integration, preserving source operation order.
        old_x_before = self.oldpos.x
        old_y_before = self.oldpos.y
        self.oldpos.x = self.pos.x
        current_x = self.oldpos.x
        self.oldpos.y = self.pos.y
        current_y = self.oldpos.y
        drag = self.d
        self.pos.x += drag * (current_x - old_x_before)
        self.pos.y += drag * (current_y - old_y_before) + self.g

        # objects.Moved(this) occurs here in TickNormal. CollideVsObjects then
        # traverses the current cell and eight neighbours in this exact order.
        integrated_x = self.pos.x
        integrated_y = self.pos.y
        integrated_i = _floor(integrated_x / tiles.tw)
        integrated_j = _floor(integrated_y / tiles.th)
        self.cell_i = integrated_i
        self.cell_j = integrated_j
        cell_i = integrated_i
        cell_j = integrated_j
        try:
            collision_cell = tiles.grid[cell_i][cell_j]
        except IndexError:
            collision_cell = None
        if (
            collision_cell is not None
            and collision_cell.i == cell_i
            and collision_cell.j == cell_j
        ):
            collision_cells = collision_cell.object_collision_cells
            collision_mask = collision_cell.object_collision_mask
        else:
            # Preserve the legacy coordinate keys for direct callers that put
            # the player outside the normal non-negative map grid.  Python's
            # negative grid indexing cannot use the cached TileCell indices.
            collision_cells = (
                (cell_i, cell_j),
                (cell_i, cell_j + 1),
                (cell_i + 1, cell_j + 1),
                (cell_i - 1, cell_j + 1),
                (cell_i - 1, cell_j),
                (cell_i - 1, cell_j - 1),
                (cell_i + 1, cell_j),
                (cell_i + 1, cell_j - 1),
                (cell_i, cell_j - 1),
            )
            collision_mask = 0

        # Object collision order comes from ObjectManager/TileMapCell's live
        # linked lists, not from current positions or load order. Build a small
        # temporary grid only for legacy direct Player.step() callers; normal
        # SimulationState execution always supplies its persistent grid_state.
        if grid_state is None:
            grid_state = ObjectGridState()
            for obj in sorted(objects, key=lambda item: item.load_index):
                if isinstance(obj, Turret):
                    continue
                if isinstance(obj, HomingLauncher) and not obj.grid_active:
                    continue
                grid_state.add(
                    object_grid_ref(obj.load_index),
                    (_floor(obj.pos.x / tiles.tw), _floor(obj.pos.y / tiles.th)),
                )
            if static_world is not None and static_state is not None:
                for entries in static_world.by_cell.values():
                    for entry in entries:
                        if entry.kind == StaticColliderKind.EXIT_DOOR:
                            continue
                        if entry.is_active(static_state):
                            grid_state.add(entry.grid_ref, (entry.cell_i, entry.cell_j))

        objects_by_uid = (
            {obj.load_index: obj for obj in objects}
            if object_lookup is None
            else object_lookup
        )

        self.prepare_to_collide()
        grid_cells = grid_state.cells
        # About half of corpus ticks have no object-grid entry anywhere in the
        # ordered nine-cell neighbourhood.  The derived integer mask proves
        # that common case without nine Python dictionary probes.  Generic
        # out-of-grid callers retain the earlier dictionary disjointness path.
        # With no collider to run, the grid cannot mutate during the skipped
        # pass.
        if collision_mask:
            if not grid_state.occupancy_mask & collision_mask:
                collision_cells = ()
        elif grid_cells.keys().isdisjoint(collision_cells):
            collision_cells = ()
        # Fetch each cell through ``grid_state`` rather than binding
        # ``grid_state.cells.get`` once for the whole traversal.  Removing a
        # collider can detach a shared copy-on-write grid by replacing its
        # ``cells`` dictionary; later cells must then see the replacement (and,
        # for an exit switch, the newly inserted exit-door reference).
        # The traversal still stops immediately whenever the current reference
        # removes itself, so an iterator from the detached dictionary is never
        # observed after its current entry changes.
        static_entries = static_world.by_ref if static_world is not None else None
        for cell in collision_cells:
            refs = grid_state.cells.get(cell, ())
            for ref in refs:
                removed_current = False
                if ref[0] == GRIDREF_OBJECT:
                    uid = ref[1]
                    if object_slots is None:
                        obj = objects_by_uid.get(uid)
                    else:
                        # SimulationState builds this dense slot table for all
                        # object grid references, so the UID is always a valid
                        # direct index on this hot path.
                        obj = object_slots[uid]
                    if obj is None:
                        continue
                    obj_type = (
                        type(obj)
                        if object_type_slots is None
                        else object_type_slots[uid]
                    )
                    if (
                        object_mutator is not None
                        and (
                            shared_object_mask is None
                            or shared_object_mask & (1 << uid)
                        )
                    ):
                        object_mutator(uid)
                        if shared_object_mask is not None:
                            shared_object_mask &= ~(1 << uid)
                        obj = (
                            object_slots[uid]
                            if object_slots is not None
                            else objects_by_uid.get(uid)
                        )
                        if obj is None:
                            continue
                    if obj_type is TestDoor:
                        if edge_overrides is None:
                            edge_overrides = {}
                        was_active = obj.trigger_active
                        was_updating = obj.updating
                        obj.test_player(self, edge_overrides)
                        if (
                            scheduler_events is not None
                            and not was_updating
                            and obj.updating
                        ):
                            # TestDoor.Open calls ObjectManager.StartUpdate at
                            # the exact point of contact. Preserve that event's
                            # order relative to other object contacts in this
                            # Player.CollideVsObjects traversal.
                            scheduler_events.append(("start_update", obj.load_index))
                        if was_active and not obj.trigger_active:
                            grid_state.remove(ref)
                            removed_current = True
                    else:
                        was_asleep = obj_type is BounceBlock and obj.asleep
                        obj.test_player(self)
                        if (
                            scheduler_events is not None
                            and was_asleep
                            and obj_type is BounceBlock
                            and not obj.asleep
                        ):
                            # BounceBlock.Wake calls StartUpdate followed by
                            # StartThink immediately. Multiple blocks can wake
                            # during one collision pass, and StartThink makes
                            # each new block the current thinker. Recording the
                            # live collision order is therefore essential.
                            scheduler_events.append(("wake_bounce", obj.load_index))
                        if obj_type is HomingLauncher and self.dead:
                            # TestVsPlayer calls ExplodeMissile after KillPlayer.
                            # ExplodeMissile calls EndUpdate and removes the
                            # missile from the grid. KillPlayer has already
                            # replaced StartIdle with StartIdle_Death, so the
                            # launcher does not rejoin the thinker ring.
                            if scheduler_events is not None:
                                scheduler_events.append(
                                    ("end_update", obj.load_index)
                                )
                            grid_state.remove(ref)
                            removed_current = True
                else:
                    if static_entries is None or static_state is None:
                        continue
                    entry = static_entries.get(ref)
                    if entry is None:
                        continue
                    bit = 1 << entry.state_index
                    if entry.kind == StaticColliderKind.GOLD:
                        active = not (static_state.collected_gold_mask & bit)
                    elif entry.kind == StaticColliderKind.MINE:
                        active = not (static_state.exploded_mine_mask & bit)
                    elif entry.kind == StaticColliderKind.EXIT_SWITCH:
                        active = not (static_state.open_exit_mask & bit)
                    else:
                        active = bool(static_state.open_exit_mask & bit)
                    if not active:
                        continue
                    removed_current = self._test_static_collider(entry, static_state)
                    if removed_current:
                        grid_state.remove(ref)
                        if entry.kind == StaticColliderKind.EXIT_SWITCH:
                            door_ref = static_world.exit_door_ref(entry.state_index)
                            door = static_entries.get(door_ref)
                            if door is not None:
                                grid_state.add(door_ref, (door.cell_i, door.cell_j))

                if self.dead:
                    break
                if removed_current:
                    # TileMapCell.RemoveObj sets current.next = null.
                    break
            if self.dead:
                break
        if self.dead:
            return

        # The tile collision routine needs the cell containing the player's
        # post-object-collision position.  Compute it here so the routine can
        # reuse the result without another get_tile_xy helper call.
        if self.pos.x == integrated_x and self.pos.y == integrated_y:
            collision_i = integrated_i
            collision_j = integrated_j
        else:
            collision_i = _floor(self.pos.x / tiles.tw)
            collision_j = _floor(self.pos.y / tiles.th)
        collision_centre = tiles.grid[collision_i][collision_j]
        pre_tile_x = self.pos.x
        pre_tile_y = self.pos.y
        tiles.collide_circle(self, edge_overrides, collision_centre)
        self.handle_collisions(tiles)
        # Second objects.Moved(this) in TickNormal, before Think()/Jump().
        if self.pos.x == pre_tile_x and self.pos.y == pre_tile_y:
            self.cell_i = collision_i
            self.cell_j = collision_j
        else:
            self.cell_i = _floor(self.pos.x / tiles.tw)
            self.cell_j = _floor(self.pos.y / tiles.th)

        jump_trigger = (
            inputs.jump and not self.previous_jump_held
            if inputs.jump_trigger is None
            else inputs.jump_trigger
        )
        # Jump-pattern search always probes the same horizontal input with a
        # held jump. Keep this compact path separate from the general alternate
        # InputFrame API so the hot loop does not repeatedly read a second
        # frame's horizontal/jump fields.
        horizontal = int(inputs.right) - int(inputs.left)
        alternate_player: Player | None = None
        if alternate_jump:
            alternate_jump_trigger = not self.previous_jump_held
            if self._would_invoke_jump(alternate_jump_trigger):
                alternate_player = self.clone()
                alternate_player._think(horizontal, True, alternate_jump_trigger)
                alternate_player.previous_jump_held = True
        elif alternate_inputs is not None:
            alternate_jump_trigger = (
                alternate_inputs.jump and not self.previous_jump_held
                if alternate_inputs.jump_trigger is None
                else alternate_inputs.jump_trigger
            )
            if self._would_invoke_jump(alternate_jump_trigger):
                alternate_player = self.clone()
                alternate_horizontal = int(alternate_inputs.right) - int(
                    alternate_inputs.left
                )
                alternate_player._think(
                    alternate_horizontal,
                    alternate_inputs.jump,
                    alternate_jump_trigger,
                )
                alternate_player.previous_jump_held = alternate_inputs.jump
        # Avoid the property call in the per-tick path; InputFrame.horizontal
        # is exactly this subtraction of the two held-button booleans.
        self._think(horizontal, inputs.jump, jump_trigger)
        self.previous_jump_held = inputs.jump
        return alternate_player

    def _think(self, horizontal: int, jump_held: bool, jump_trigger: bool) -> None:
        vx = self.pos.x - self.oldpos.x
        vy = self.pos.y - self.oldpos.y
        state = self.state

        if state == PlayerState.CELEBRATING:
            self._think_celebrate()
            return

        if self.in_air:
            candidate = vx + horizontal * self.air_accel
            if abs(candidate) < self.maxspeed_air:
                vx = candidate
            self.oldpos.x = self.pos.x - vx

            if state < PlayerState.JUMPING:
                self.fall()
                return
            if state == PlayerState.JUMPING:
                self.jump_timer += 1
                if (not jump_held) or self.jump_timer > self.max_jump_time:
                    self.fall()
                return

            if self.near_wall:
                if jump_trigger:
                    if state == PlayerState.WALLSLIDING and horizontal * self.wall_n.x < 0:
                        jump_x = 1.0
                        jump_y_bias = 0.5
                    else:
                        jump_x = 1.5
                        jump_y_bias = 0.7
                    self.jump(self.wall_n.x * jump_x, self.wall_n.y - jump_y_bias)
                    return
                if state == PlayerState.WALLSLIDING:
                    if horizontal * self.wall_n.x > 0:
                        self.fall()
                        return
                    speed = abs(vy)
                    friction_delta = -self.wall_friction * speed
                    self.oldpos.y = self.pos.y - (vy + friction_delta)
                    return
                if vy > 0.0 and horizontal * self.wall_n.x < 0:
                    self.state = PlayerState.WALLSLIDING
                    return
            elif state == PlayerState.WALLSLIDING:
                self.fall()
                return
            return

        candidate = vx + horizontal * self.ground_accel
        if abs(candidate) < self.maxspeed_ground:
            vx = candidate
        self.oldpos.x = self.pos.x - vx

        if state > PlayerState.SKIDDING:
            # Run()/Skid() in the game call ExitState(). Leaving JUMPING
            # therefore runs ExitJump(), restoring normal gravity.
            if state == PlayerState.JUMPING:
                self.g = self.norm_grav
            if vx * horizontal > 0.0:
                self.state = PlayerState.RUNNING
            else:
                self.state = PlayerState.SKIDDING
            return

        if jump_trigger:
            if horizontal * self.floor_n.x < 0.0:
                self.jump(0.0, -0.7)
            else:
                self.jump(self.floor_n.x, self.floor_n.y)
            return

        if state == PlayerState.RUNNING:
            nx = self.floor_n.x
            ny = self.floor_n.y
            tangent_speed = vx * -ny + vy * nx
            tangent_abs = abs(tangent_speed)
            direction_test = vx * tangent_abs
            if horizontal * direction_test <= 0.0:
                self.state = PlayerState.SKIDDING
                return
            if horizontal * nx < 0.0:
                accel_y = -abs(nx)
                accel_x = -ny if nx < 0.0 else ny
                abs_ny = abs(ny)
                accel_x *= 0.5 * abs_ny
                accel_y *= 0.5 * abs_ny
                candidate_x = vx + accel_x * self.ground_accel
                candidate_y = vy + accel_y * self.ground_accel
                # Source checks abs(v8), where v8 is the earlier x candidate.
                if abs(candidate) < self.maxspeed_ground:
                    vx = candidate_x
                    vy = candidate_y
                self.oldpos.x = self.pos.x - vx
                self.oldpos.y = self.pos.y - vy
            return

        if state == PlayerState.SKIDDING:
            nx = self.floor_n.x
            ny = self.floor_n.y
            tangent_abs = abs(vx * -ny + vy * nx)
            direction_test = vx * tangent_abs
            if direction_test * horizontal > 0.0:
                self.state = PlayerState.RUNNING
                return
            if tangent_abs < 0.1:
                self.state = PlayerState.STANDING
                return
            vx *= self.skid_friction
            self.oldpos.x = self.pos.x - vx
            return

        if horizontal != 0:
            self.state = PlayerState.RUNNING
            return

        nx = self.floor_n.x
        ny = self.floor_n.y
        tangent_abs = abs(vx * -ny + vy * nx)
        if tangent_abs >= 0.1:
            self.state = PlayerState.SKIDDING
            return
        vx *= self.stand_friction
        vy *= self.stand_friction
        self.oldpos.x = self.pos.x - vx
        self.oldpos.y = self.pos.y - vy

    def celebrate(self) -> None:
        # Player.Celebrate() calls the current ExitState before switching Think
        # to ThinkCelebrate. Only ExitJump has physics-relevant behaviour.
        if self.state == PlayerState.JUMPING:
            self.g = self.norm_grav
        self.state = PlayerState.CELEBRATING
        self.celeb_was_in_air = self.in_air

    def _think_celebrate(self) -> None:
        # Rendering/animation randomness is intentionally omitted; only the
        # drag transitions in ThinkCelebrate affect subsequent physics.
        if self.in_air:
            if not self.celeb_was_in_air:
                self.d = self.norm_drag
                self.celeb_was_in_air = True
        else:
            if self.celeb_was_in_air:
                self.d = self.win_drag
            self.celeb_was_in_air = False

    def jump(self, x: float, y: float) -> None:
        self.jump_events += 1
        if self.state == PlayerState.JUMPING:
            self.g = self.norm_grav
        self.state = PlayerState.JUMPING
        self.g = self.jump_grav
        vx = self.pos.x - self.oldpos.x
        vy = self.pos.y - self.oldpos.y
        if vx * x < 0.0:
            self.oldpos.x = self.pos.x
        if vy * y < 0.0:
            self.oldpos.y = self.pos.y
        self.pos.x += x * self.jump_amt
        self.pos.y += y * (self.jump_amt + self.jump_y_bias)
        self.jump_timer = 0

    def fall(self) -> None:
        if self.state == PlayerState.JUMPING:
            self.g = self.norm_grav
        self.state = PlayerState.FALLING

    def _would_invoke_jump(self, jump_trigger: bool) -> bool:
        """Return whether the current Think state would call ``jump()``."""
        if not jump_trigger or self.state == PlayerState.CELEBRATING:
            return False
        if self.in_air:
            if self.state < PlayerState.JUMPING or self.state == PlayerState.JUMPING:
                return False
            return self.near_wall
        return self.state <= PlayerState.SKIDDING

    def launch(self, x: float, y: float) -> None:
        self.oldpos.x = self.pos.x
        self.oldpos.y = self.pos.y
        self.pos.x += x
        self.pos.y += y
        self.fall()

    def state_key(self, *, precision: int | None = None) -> tuple:
        """Hashable state for brute-force deduplication.

        ``precision=None`` is exact Python-float equality. A small decimal
        precision can be useful for heuristic beam searches, but not for final
        verification.
        """
        values = (
            self.pos.x,
            self.pos.y,
            self.oldpos.x,
            self.oldpos.y,
            float(self.g),
            float(self.d),
            int(self.state),
            self.jump_timer,
            self.in_air,
            self.near_wall,
            self.floor_n.x,
            self.floor_n.y,
            self.previous_jump_held,
            self.celeb_was_in_air,
            self.dead,
            self.cell_i,
            self.cell_j,
        )
        if precision is None:
            return values
        rounded: list[object] = []
        for value in values:
            rounded.append(round(value, precision) if isinstance(value, float) else value)
        return tuple(rounded)


@dataclass(slots=True)
class SimulationState:
    player: Player
    objects: list[PhysicsObject]
    edge_overrides: EdgeOverrides = field(default_factory=dict)
    frame: int = 0
    think_timer: int = 0
    think_rate: int = 2
    thinker_uids: list[int] = field(default_factory=list)
    update_uids: list[int] = field(default_factory=list)
    grid_state: ObjectGridState = field(default_factory=ObjectGridState)
    static_world: StaticWorld | None = None
    static_state: StaticObjectState = field(default_factory=StaticObjectState)
    objects_by_uid: dict[int, PhysicsObject] = field(init=False, repr=False)
    object_grid_refs: dict[int, GridRef] = field(init=False, repr=False)
    object_slots: list[PhysicsObject | None] = field(init=False, repr=False)
    object_type_slots: list[type | None] = field(init=False, repr=False)
    object_ref_slots: list[GridRef | None] = field(init=False, repr=False)
    object_indices_by_uid: dict[int, int] = field(init=False, repr=False)
    scheduler_events_required: bool = field(init=False, repr=False)
    update_snapshot_required: bool = field(init=False, repr=False)
    update_uid_mask: int = field(init=False, repr=False, compare=False)
    player_collision_mutable_mask: int = field(init=False, repr=False, compare=False)
    _shared_object_mask: int = field(init=False, repr=False, compare=False)
    _scheduler_events: list[tuple[str, int]] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        # The object list is stable for the lifetime of a simulation branch;
        # only object fields and scheduler/grid membership mutate. Keeping this
        # lookup avoids rebuilding a dictionary once per simulated frame.
        self.objects_by_uid = {obj.load_index: obj for obj in self.objects}
        self.object_grid_refs = {
            uid: (GRIDREF_OBJECT, uid, 0) for uid in self.objects_by_uid
        }
        max_uid = max(self.objects_by_uid, default=-1)
        self.object_slots = [None] * (max_uid + 1)
        self.object_type_slots = [None] * (max_uid + 1)
        self.object_ref_slots = [None] * (max_uid + 1)
        self.object_indices_by_uid = {}
        for object_index, (uid, obj) in enumerate(self.objects_by_uid.items()):
            self.object_slots[uid] = obj
            self.object_type_slots[uid] = type(obj)
            self.object_ref_slots[uid] = (GRIDREF_OBJECT, uid, 0)
            self.object_indices_by_uid[uid] = object_index
        if len(self.grid_state.object_cells) < len(self.object_slots):
            self.grid_state.object_cells.extend(
                [None] * (len(self.object_slots) - len(self.grid_state.object_cells))
            )
        self.scheduler_events_required = any(
            type(obj) in (BounceBlock, TestDoor, HomingLauncher)
            for obj in self.objects
        )
        # Only these callbacks can mutate update_uids during ObjectManager's
        # update traversal.  Other exact supported types keep a stable list,
        # so they can avoid both the per-frame copy and live-membership test.
        self.update_snapshot_required = any(
            type(obj) in (Turret, TestDoor, HomingLauncher) for obj in self.objects
        )
        self.update_uid_mask = 0
        for uid in self.update_uids:
            self.update_uid_mask |= 1 << uid
        self.player_collision_mutable_mask = 0
        for uid, obj_type in enumerate(self.object_type_slots):
            if obj_type in _PLAYER_COLLISION_MUTABLE_TYPES:
                self.player_collision_mutable_mask |= 1 << uid
        self._shared_object_mask = 0
        self._scheduler_events = []

    @property
    def level_complete(self) -> bool:
        return self.static_state.level_complete

    def clone(
        self,
        *,
        player: Player | None = None,
        copy_on_write_objects: bool = False,
    ) -> "SimulationState":
        # Construct the slotted state directly.  The derived UID tables have
        # the same shape on every branch; rebuilding them through the dataclass
        # constructor used to add avoidable dictionary/list setup to every
        # search clone.  They still receive fresh containers where callers can
        # mutate them, while the immutable ref tuples are copied shallowly.
        # Direction-only DFS can request object copy-on-write: the child then
        # shares object instances until _ensure_object_mutable() is called by
        # an update, thinker, or collision callback.
        objects = (
            self.objects.copy()
            if copy_on_write_objects
            else _clone_physics_objects(self.objects)
        )
        cloned = object.__new__(SimulationState)
        # Jump-pattern search can provide the already-independent player made
        # by Player.step's alternate-input probe. Avoid cloning the original
        # player only to overwrite it immediately after the world clone.
        cloned.player = self.player.clone() if player is None else player
        cloned.objects = objects
        cloned.edge_overrides = self.edge_overrides.copy()
        cloned.frame = self.frame
        cloned.think_timer = self.think_timer
        cloned.think_rate = self.think_rate
        cloned.thinker_uids = self.thinker_uids.copy()
        cloned.update_uids = self.update_uids.copy()
        cloned.grid_state = self.grid_state.clone()
        cloned.static_world = self.static_world
        cloned.static_state = self.static_state.clone()
        # These lookup tables contain only immutable UID/type/reference
        # descriptors. Sharing them avoids three per-branch container copies;
        # the mutable object-slot table remains branch-local below.
        cloned.object_grid_refs = self.object_grid_refs
        cloned.object_slots = self.object_slots.copy()
        if copy_on_write_objects:
            # Both branches may remain live after the clone. Mark the source
            # as sharing too, so a later source-side step detaches before it
            # mutates an object still visible to the child branch.
            shared_object_mask = (1 << len(self.object_slots)) - 1
            self._shared_object_mask |= shared_object_mask
            cloned.objects_by_uid = self.objects_by_uid.copy()
            cloned._shared_object_mask = shared_object_mask
        else:
            cloned._shared_object_mask = 0
            cloned.objects_by_uid = {obj.load_index: obj for obj in objects}
            for obj in objects:
                cloned.object_slots[obj.load_index] = obj
        cloned.object_type_slots = self.object_type_slots
        cloned.object_ref_slots = self.object_ref_slots
        cloned.object_indices_by_uid = self.object_indices_by_uid
        cloned.scheduler_events_required = self.scheduler_events_required
        cloned.update_snapshot_required = self.update_snapshot_required
        cloned.update_uid_mask = self.update_uid_mask
        cloned.player_collision_mutable_mask = self.player_collision_mutable_mask
        cloned._scheduler_events = []
        return cloned

    def _ensure_object_mutable(self, uid: int) -> None:
        """Detach one shared physics object before a branch can mutate it."""
        bit = 1 << uid
        if not self._shared_object_mask & bit:
            return
        self._shared_object_mask &= ~bit
        obj = self.object_slots[uid]
        if obj is None:
            return
        cloned = obj.clone()
        self.object_slots[uid] = cloned
        self.objects_by_uid[uid] = cloned
        self.objects[self.object_indices_by_uid[uid]] = cloned

    def _object_by_uid(self, uid: int) -> PhysicsObject | None:
        obj = self.object_slots[uid] if 0 <= uid < len(self.object_slots) else None
        if obj is not None:
            return obj
        # Some source objects participate in the shared thinker ring even when
        # their behaviour is outside this emulator's current scope.  Keeping
        # their UID in the ring preserves round-robin timing for supported
        # enemies such as homing launchers.
        return None

    def start_think(self, uid: int) -> None:
        """Port ObjectManager.StartThink; list index 0 is curThinker."""
        if uid in self.thinker_uids:
            return
        if not self.thinker_uids:
            self.thinker_uids.append(uid)
        else:
            self.thinker_uids.insert(0, uid)

    def end_think(self, uid: int) -> None:
        """Port ObjectManager.EndThink while preserving the current successor."""
        try:
            self.thinker_uids.remove(uid)
        except ValueError:
            return

    def start_update(self, uid: int) -> None:
        """Port ObjectManager.StartUpdate and AVM1 numeric enumeration order.

        In the traced AVM1 player, newly added numeric UID properties enumerate
        before older ones. Treating index 0 as the next for-in entry reproduces
        both initialization (reverse StartUpdate order) and dynamic insertion.
        """
        if uid not in self.update_uids:
            self.update_uids.insert(0, uid)
            self.update_uid_mask |= 1 << uid

    def end_update(self, uid: int) -> None:
        try:
            self.update_uids.remove(uid)
        except ValueError:
            return
        self.update_uid_mask &= ~(1 << uid)

    # Backwards-compatible diagnostic view retained for callers/tests that used
    # the pre-v2.7 turret-only scheduler. It is no longer scheduler state.
    @property
    def turret_update_uids(self) -> list[int]:
        return [
            uid for uid in self.update_uids
            if isinstance(self._object_by_uid(uid), Turret)
        ]

    @turret_update_uids.setter
    def turret_update_uids(self, values: Sequence[int]) -> None:
        non_turrets = [
            uid for uid in self.update_uids
            if not isinstance(self._object_by_uid(uid), Turret)
        ]
        self.update_uids = list(values) + non_turrets
        self.update_uid_mask = 0
        for uid in self.update_uids:
            self.update_uid_mask |= 1 << uid

    def start_turret_update(self, uid: int) -> None:
        self.start_update(uid)

    def end_turret_update(self, uid: int) -> None:
        self.end_update(uid)

    def _tick_thinker(self, tiles: TileMap) -> None:
        if not self.thinker_uids:
            return
        if self.think_rate < self.think_timer:
            self.think_timer = 0
            uid = self.thinker_uids[0]
            obj = self._object_by_uid(uid)
            removed = False
            if obj is None:
                # Passive scheduling placeholder for an unsupported thinker.
                pass
            else:
                if self._shared_object_mask & (1 << uid):
                    self._ensure_object_mutable(uid)
                    obj = self._object_by_uid(uid)
            if obj is not None and self.object_type_slots[uid] is BounceBlock:
                if obj.think():
                    self.end_update(uid)
                    self.end_think(uid)
                    removed = True
            elif obj is not None and self.object_type_slots[uid] is Turret:
                action = obj.think(self.player, tiles, self.edge_overrides)
                if action == "start_update":
                    self.start_update(uid)
                elif action == "end_update":
                    self.end_update(uid)
            elif obj is not None and self.object_type_slots[uid] is HomingLauncher:
                if obj.think(self.player, tiles, self.edge_overrides):
                    # StartFiring: EndThink(this), StartUpdate(this).
                    self.end_think(uid)
                    self.start_update(uid)
                    removed = True
            elif obj is not None and self.object_type_slots[uid] in (LaserDrone, ChaingunDrone):
                if obj.think(self.player, tiles, self.edge_overrides):
                    self.end_think(uid)
                    removed = True

            if removed:
                # Source Tick() advances *after* Think(). EndThink(current) has
                # already set curThinker to the removed node's successor, so the
                # unconditional curThinker=curThinker.next skips that successor.
                if len(self.thinker_uids) > 1:
                    self.thinker_uids.append(self.thinker_uids.pop(0))
            elif len(self.thinker_uids) > 1 and self.thinker_uids[0] == uid:
                self.thinker_uids.append(self.thinker_uids.pop(0))
        else:
            self.think_timer += 1

    def step(
        self,
        inputs: InputFrame,
        tiles: TileMap,
        *,
        alternate_inputs: InputFrame | None = None,
        alternate_jump: bool = False,
    ) -> "Player | None":
        if self.static_state.level_complete:
            self.frame += 1
            return None

        player = self.player
        edge_overrides = self.edge_overrides
        grid_state = self.grid_state
        object_slots = self.object_slots
        object_type_slots = self.object_type_slots
        object_ref_slots = self.object_ref_slots
        frame = self.frame

        # NinjaGame.Tick -> ObjectManager.Tick. for-in walks the shared update
        # object using AVM1 enumeration order. Snapshotting the current keys
        # matches the observed behaviour for changes made by Update callbacks.
        update_uids = self.update_uids
        shared_mask = self._shared_object_mask
        shared_update_mask = shared_mask & self.update_uid_mask
        if update_uids:
            snapshot_required = self.update_snapshot_required
            iteration_uids = update_uids.copy() if snapshot_required else update_uids
            for uid in iteration_uids:
                if snapshot_required and uid not in update_uids:
                    continue
                obj = object_slots[uid]
                if obj is None:
                    continue
                if shared_update_mask:
                    bit = 1 << uid
                    if shared_update_mask & bit:
                        self._ensure_object_mutable(uid)
                        shared_mask &= ~bit
                        shared_update_mask &= ~bit
                        obj = object_slots[uid]
                ref = object_ref_slots[uid]

                # Exact-type dispatch is ordered by corpus update frequency.
                # This changes only the Python branch cost; each UID still
                # executes in the source-faithful update_uids order above.
                obj_type = object_type_slots[uid]
                if obj_type is ZapDrone:
                    # This exact-type branch can bypass ZapDrone.update's
                    # one-line public wrapper on the per-drone/per-tick path.
                    obj._update_move(tiles, edge_overrides, player)
                    old_cell = grid_state.object_cells[uid]
                    if old_cell is not None and (
                        old_cell[0] != obj.cell_i or old_cell[1] != obj.cell_j
                    ):
                        grid_state.moved_object_xy(uid, ref, obj.cell_i, obj.cell_j)
                elif obj_type is Thwomp:
                    was_moving = obj.mode == 1
                    # Inline Thwomp.Update here because it is called for every
                    # moving/waiting thwomp on every simulation tick.  The
                    # public method remains below for direct callers; this is
                    # the same branch and arithmetic order as that method.
                    if obj.mode == 0:
                        player_pos = player.pos
                        if obj.dir.x == 0.0:
                            if abs(obj.pos.x - player_pos.x) < 2.0 * (obj.xw + player.xw):
                                if obj.minj <= player.cell_j <= obj.maxj:
                                    obj.start_fall()
                        else:
                            if abs(obj.pos.y - player_pos.y) < 2.0 * (obj.yw + player.yw):
                                if obj.mini <= player.cell_i <= obj.maxi:
                                    obj.start_fall()
                    else:
                        dx = obj.goal.x - obj.pos.x
                        dy = obj.goal.y - obj.pos.y
                        distance2 = dx * dx + dy * dy
                        if distance2 < obj.speed * obj.speed:
                            obj.pos.x = obj.goal.x
                            obj.pos.y = obj.goal.y
                            if obj.movedir == 1:
                                obj.start_raise()
                            else:
                                obj.start_wait()
                        else:
                            obj.pos.x += obj.movedir * obj.dir.x * obj.speed
                            obj.pos.y += obj.movedir * obj.dir.y * obj.speed
                    if was_moving:
                        new_i = _floor(obj.pos.x / tiles.tw)
                        new_j = _floor(obj.pos.y / tiles.th)
                        old_cell = grid_state.object_cells[uid]
                        if old_cell is not None and (
                            old_cell[0] != new_i or old_cell[1] != new_j
                        ):
                            grid_state.moved_object_xy(uid, ref, new_i, new_j)
                elif obj_type is FloorGuard:
                    # Inline the small guard movement callback on the local
                    # search hot path; its source ordering and endpoint
                    # snapping are unchanged.
                    was_chasing = obj.chasing
                    if not was_chasing:
                        if (
                            obj.cell_j == player.cell_j
                            and obj.mini <= player.cell_i <= obj.maxi
                        ):
                            obj.start_chasing(player)
                    else:
                        if obj.dir < 0:
                            if abs(obj.pos.x - obj.min_x) < obj.speed:
                                obj.pos.x = obj.min_x
                                obj.chasing = False
                            else:
                                obj.pos.x += obj.dir * obj.speed
                        else:
                            if abs(obj.max_x - obj.pos.x) < obj.speed:
                                obj.pos.x = obj.max_x
                                obj.chasing = False
                            else:
                                obj.pos.x += obj.dir * obj.speed
                        obj.cell_i = _floor(obj.pos.x / tiles.tw)
                        obj.cell_j = _floor(obj.pos.y / tiles.th)
                        old_cell = grid_state.object_cells[uid]
                        if old_cell is not None and (
                            old_cell[0] != obj.cell_i or old_cell[1] != obj.cell_j
                        ):
                            grid_state.moved_object_xy(
                                uid, ref, obj.cell_i, obj.cell_j
                            )
                elif obj_type is Turret:
                    action = obj.update(player, tiles, edge_overrides, frame)
                    if action == "end_think":
                        self.end_think(uid)
                    elif action == "start_think":
                        self.start_think(uid)
                    elif action == "end_update":
                        self.end_update(uid)
                elif obj_type is LaserDrone:
                    # Moving laser drones do not read the player and are the
                    # overwhelmingly common state on long local searches.
                    # Bypass the public wrapper's mode dispatch while keeping
                    # its exact transition path for firing states.
                    if obj.mode is DroneMode.MOVING:
                        obj._update_move(tiles, edge_overrides)
                        restarted = False
                    else:
                        restarted = obj.update(player, tiles, edge_overrides)
                    if restarted:
                        self.start_think(uid)
                    old_cell = grid_state.object_cells[uid]
                    if old_cell is not None and (
                        old_cell[0] != obj.cell_i or old_cell[1] != obj.cell_j
                    ):
                        grid_state.moved_object_xy(uid, ref, obj.cell_i, obj.cell_j)
                elif obj_type is BounceBlock:
                    # Deliberately no ObjectManager.Moved call: the source leaves a
                    # displaced bounceblock linked to its original cell.
                    # BounceBlock.Update is a no-op while asleep. Keep that
                    # overwhelmingly common case out of the per-object method
                    # dispatch, while retaining the exact arithmetic for active
                    # blocks inline on the local-search hot path.
                    if not obj.asleep:
                        old_x_before = obj.oldpos.x
                        old_y_before = obj.oldpos.y
                        obj.oldpos.x = obj.pos.x
                        current_x = obj.oldpos.x
                        obj.oldpos.y = obj.pos.y
                        current_y = obj.oldpos.y
                        obj.pos.x += 0.99 * (current_x - old_x_before)
                        obj.pos.y += 0.99 * (current_y - old_y_before)
                        dx = obj.anchor.x - obj.pos.x
                        dy = obj.anchor.y - obj.pos.y
                        if 0.0 < dx * dx + dy * dy:
                            obj.pos.x += dx * obj.stiff
                            obj.pos.y += dy * obj.stiff
                        obj.sleep_timer += 1
                elif obj_type is HomingLauncher:
                    was_in_grid = grid_state.object_cells[uid] is not None
                    restarted_idle = obj.update(player, tiles, edge_overrides)
                    if not was_in_grid and obj.grid_active:
                        # FireMissile calls AddToGrid before Update_Homing begins.
                        grid_state.add(ref, (obj.cell_i, obj.cell_j))
                    elif was_in_grid and obj.grid_active:
                        old_cell = grid_state.object_cells[uid]
                        if old_cell[0] != obj.cell_i or old_cell[1] != obj.cell_j:
                            grid_state.moved_object_xy(
                                uid, ref, obj.cell_i, obj.cell_j
                            )
                    if restarted_idle:
                        # ExplodeMissile: EndUpdate, RemoveFromGrid, StartThink.
                        self.end_update(uid)
                        grid_state.remove(ref)
                        self.start_think(uid)
                elif obj_type is ChaingunDrone:
                    # As with lasers, retain the full update callback for
                    # firing states but take the player-independent movement
                    # path directly.
                    if obj.mode is DroneMode.MOVING:
                        obj._update_move(tiles, edge_overrides)
                        restarted = False
                    else:
                        restarted = obj.update(player, tiles, edge_overrides, frame)
                    if restarted:
                        self.start_think(uid)
                    old_cell = grid_state.object_cells[uid]
                    if old_cell is not None and (
                        old_cell[0] != obj.cell_i or old_cell[1] != obj.cell_j
                    ):
                        grid_state.moved_object_xy(uid, ref, obj.cell_i, obj.cell_j)
                elif obj_type is TestDoor:
                    obj.update(edge_overrides)
                    if not obj.updating:
                        self.end_update(uid)
                else:
                    obj.update()

        # Avoid a Python method call on levels/ticks with no active thinker;
        # _tick_thinker retains its own guard for public/direct callers.
        if self.thinker_uids:
            self._tick_thinker(tiles)
        alternate_player: Player | None = None
        collision_shared_mask = (
            self._shared_object_mask & self.player_collision_mutable_mask
        )
        if not player.dead:
            if self.scheduler_events_required:
                scheduler_events = self._scheduler_events
                scheduler_events.clear()
            else:
                scheduler_events = None
            alternate_player = player.step(
                inputs,
                tiles,
                self.objects,
                edge_overrides,
                self.static_world,
                self.static_state,
                grid_state,
                self.objects_by_uid,
                scheduler_events,
                object_slots,
                object_type_slots,
                object_mutator=(
                    self._ensure_object_mutable
                    if collision_shared_mask
                    else None
                ),
                shared_object_mask=collision_shared_mask,
                alternate_inputs=alternate_inputs,
                alternate_jump=alternate_jump,
            )

            # These source calls occur during Player.CollideVsObjects, after
            # this frame's ObjectManager update/think phase. Applying them now
            # is equivalent for execution timing, while retaining their exact
            # contact order. A post-pass over self.objects is not equivalent:
            # StartThink inserts before curThinker and makes the new object
            # current, so reversing two same-frame wakes changes the ring.
            if scheduler_events:
                for action, uid in scheduler_events:
                    if action == "wake_bounce":
                        self.start_update(uid)
                        self.start_think(uid)
                    elif action == "start_update":
                        self.start_update(uid)
                    elif action == "end_update":
                        self.end_update(uid)
        self.frame += 1
        return alternate_player

    def state_key(self, *, precision: int | None = None) -> tuple:
        object_values: list[object] = []
        for obj in self.objects:
            obj_type = type(obj)
            if obj_type is BounceBlock:
                values = (
                    obj.pos.x,
                    obj.pos.y,
                    obj.oldpos.x,
                    obj.oldpos.y,
                    obj.asleep,
                    obj.sleep_timer,
                )
                if precision is not None:
                    values = tuple(
                        round(value, precision) if isinstance(value, float) else value
                        for value in values
                    )
                object_values.extend(values)
            elif obj_type is ZapDrone:
                values = (
                    obj.pos.x,
                    obj.pos.y,
                    obj.goal.x,
                    obj.goal.y,
                    obj.cur_dir,
                    obj.cell_i,
                    obj.cell_j,
                    obj.ai_counter,
                    obj.ai_counter2,
                    obj.is_chaser,
                    obj.is_chasing,
                    obj.surface_future_dir,
                    obj.surface_grab_pending,
                )
                if precision is not None:
                    values = tuple(
                        round(value, precision) if isinstance(value, float) else value
                        for value in values
                    )
                object_values.extend(values)
            elif obj_type is HomingLauncher:
                common_values = (int(obj.mode),)
                if obj.mode == HomingMode.PREFIRE:
                    mode_values = (obj.fire_delay_timer,)
                elif obj.mode == HomingMode.HOMING:
                    mode_values = (
                        obj.pos.x,
                        obj.pos.y,
                        obj.mdir.x,
                        obj.mdir.y,
                        obj.speed,
                        obj.curaccel,
                        obj.cell_i,
                        obj.cell_j,
                    )
                else:
                    mode_values = ()
                values = common_values + mode_values
                if precision is not None:
                    values = tuple(
                        round(value, precision) if isinstance(value, float) else value
                        for value in values
                    )
                object_values.extend(values)
            elif obj_type is ChaingunDrone:
                common_values = (
                    obj.pos.x,
                    obj.pos.y,
                    obj.goal.x,
                    obj.goal.y,
                    obj.cur_dir,
                    obj.cell_i,
                    obj.cell_j,
                    obj.ai_counter,
                    obj.ai_counter2,
                    int(obj.mode),
                )
                if obj.mode == DroneMode.PREFIRE:
                    mode_values = (obj.fire_delay_timer,)
                elif obj.mode == DroneMode.FIRING:
                    mode_values = (
                        obj.chaingun_timer,
                        obj.chaingun_max_num,
                        obj.chaingun_cur_num,
                        obj.chaingun_spread,
                        obj.targ.x,
                        obj.targ.y,
                        obj.targ2.x,
                        obj.targ2.y,
                    )
                elif obj.mode == DroneMode.POSTFIRE:
                    mode_values = (obj.fire_delay_timer,)
                else:
                    mode_values = ()
                values = common_values + mode_values
                if precision is not None:
                    values = tuple(
                        round(value, precision) if isinstance(value, float) else value
                        for value in values
                    )
                object_values.extend(values)
            elif obj_type is LaserDrone:
                common_values = (
                    obj.pos.x,
                    obj.pos.y,
                    obj.goal.x,
                    obj.goal.y,
                    obj.cur_dir,
                    obj.cell_i,
                    obj.cell_j,
                    obj.ai_counter,
                    obj.ai_counter2,
                    int(obj.mode),
                )
                if obj.mode == DroneMode.PREFIRE:
                    mode_values = (
                        obj.fire_delay_timer,
                        obj.targ.x,
                        obj.targ.y,
                        obj.targ2.x,
                        obj.targ2.y,
                        obj.laser_len,
                    )
                elif obj.mode == DroneMode.FIRING:
                    mode_values = (
                        obj.laser_timer,
                        obj.targ.x,
                        obj.targ.y,
                        obj.targ2.x,
                        obj.targ2.y,
                        obj.laser_len,
                    )
                elif obj.mode == DroneMode.POSTFIRE:
                    mode_values = (obj.fire_delay_timer,)
                else:
                    mode_values = ()
                values = common_values + mode_values
                if precision is not None:
                    values = tuple(
                        round(value, precision) if isinstance(value, float) else value
                        for value in values
                    )
                object_values.extend(values)
            elif obj_type is Turret:
                # view/targ are diagnostic/drawing outputs only; they are
                # overwritten before any gameplay use, so excluding them keeps
                # search deduplication from splitting equivalent branches.
                values = (
                    int(obj.mode),
                    obj.aim.x,
                    obj.aim.y,
                    obj.aim_speed,
                    obj.shot_timer,
                    obj.fire_delay_timer,
                )
                if precision is not None:
                    values = tuple(
                        round(value, precision) if isinstance(value, float) else value
                        for value in values
                    )
                object_values.extend(values)
            elif obj_type is FloorGuard:
                values = (
                    obj.pos.x,
                    obj.pos.y,
                    obj.dir,
                    obj.cell_i,
                    obj.cell_j,
                    obj.chasing,
                )
                if precision is not None:
                    values = tuple(
                        round(value, precision) if isinstance(value, float) else value
                        for value in values
                    )
                object_values.extend(values)
            elif obj_type is Thwomp:
                values = (
                    obj.pos.x,
                    obj.pos.y,
                    obj.goal.x,
                    obj.goal.y,
                    obj.movedir,
                    obj.speed,
                    obj.is_moving,
                    obj.mode,
                )
                if precision is not None:
                    values = tuple(
                        round(value, precision) if isinstance(value, float) else value
                        for value in values
                    )
                object_values.extend(values)
            elif obj_type is TestDoor:
                object_values.extend(
                    (
                        obj.is_open,
                        obj.door_timer,
                        obj.updating,
                        obj.trigger_active,
                    )
                )
        edge_values = tuple(sorted(self.edge_overrides.items()))
        thinker_values = (self.think_timer, self.think_rate, tuple(self.thinker_uids))
        update_values = tuple(self.update_uids)
        grid_values = self.grid_state.state_key()
        return (
            self.player.state_key(precision=precision),
            *object_values,
            edge_values,
            thinker_values,
            update_values,
            grid_values,
            self.static_state.state_key(),
        )


def door_control_masks(state: SimulationState) -> tuple[int, int]:
    """Return permanent locked-key and trap-trigger state by stable load id.

    Locked ``TestDoor`` switches never close after activation, while trapdoor
    triggers permanently remove themselves after firing.  Encoding both using
    each object's serialized ``load_index`` gives callers a stable identity that
    survives cloned search branches and does not depend on object-list order.
    """
    opened_locked_doors = 0
    triggered_trapdoors = 0
    for obj in state.objects:
        if not isinstance(obj, TestDoor):
            continue
        bit = 1 << obj.load_index
        if obj.is_locked and obj.is_open:
            opened_locked_doors |= bit
        if obj.is_trap and not obj.trigger_active:
            triggered_trapdoors |= bit
    return opened_locked_doors, triggered_trapdoors


@dataclass(slots=True)
class Level:
    tiles: TileMap
    player: Player
    objects: list[PhysicsObject]
    all_specs: list[ObjectSpec]
    static_world: StaticWorld = field(default_factory=lambda: StaticWorld({}))
    initial_edge_overrides: EdgeOverrides = field(default_factory=dict)
    simulate_enemies: bool = False
    passive_thinker_uids: tuple[int, ...] = ()
    source_level_string: str | None = None
    _initial_thinker_uids: tuple[int, ...] | None = field(
        default=None, init=False, repr=False
    )
    _initial_update_uids: tuple[int, ...] | None = field(
        default=None, init=False, repr=False
    )
    _initial_grid_state: ObjectGridState | None = field(
        default=None, init=False, repr=False
    )

    def initial_state(self) -> SimulationState:
        if self._initial_grid_state is None:
            targeting_drone_uids = sorted(
                (
                    obj.load_index
                    for obj in self.objects
                    if isinstance(
                        obj, (LaserDrone, ChaingunDrone, HomingLauncher, Turret)
                    )
                )
            )
            targeting_drone_uids.extend(self.passive_thinker_uids)
            targeting_drone_uids.sort()
            # Each StartThink inserts before curThinker and becomes current.
            self._initial_thinker_uids = tuple(reversed(targeting_drone_uids))

            objects_by_uid = {obj.load_index: obj for obj in self.objects}
            grid_state = ObjectGridState()
            update_uids: list[int] = []
            gold_index = 0
            mine_index = 0
            exit_index = 0

            # Replay level objects are spawned in serialized order. Replaying
            # their initial AddToGrid/StartUpdate operations gives exact
            # head/enumeration order instead of deriving either structure from
            # final positions.
            for spec in self.all_specs:
                obj = objects_by_uid.get(spec.load_index)
                if obj is not None:
                    if not isinstance(obj, (Turret, HomingLauncher)):
                        if isinstance(
                            obj, (FloorGuard, ZapDrone, LaserDrone, ChaingunDrone)
                        ):
                            cell = (obj.cell_i, obj.cell_j)
                        else:
                            cell = (
                                _floor(obj.pos.x / self.tiles.tw),
                                _floor(obj.pos.y / self.tiles.th),
                            )
                        grid_state.add(object_grid_ref(spec.load_index), cell)

                    if isinstance(
                        obj, (FloorGuard, Thwomp, ZapDrone, LaserDrone, ChaingunDrone)
                    ):
                        # StartUpdate during Init; newest numeric UID enumerates
                        # first.
                        update_uids.insert(0, spec.load_index)

                if spec.obj_type == OBJTYPE_GOLD:
                    ref = (GRIDREF_STATIC, int(StaticColliderKind.GOLD), gold_index)
                    entry = self.static_world.entry_for_ref(ref)
                    if entry is not None:
                        grid_state.add(ref, (entry.cell_i, entry.cell_j))
                    gold_index += 1
                elif spec.obj_type == OBJTYPE_MINE:
                    ref = (GRIDREF_STATIC, int(StaticColliderKind.MINE), mine_index)
                    entry = self.static_world.entry_for_ref(ref)
                    if entry is not None:
                        grid_state.add(ref, (entry.cell_i, entry.cell_j))
                    mine_index += 1
                elif spec.obj_type == OBJTYPE_EXIT:
                    # ExitObject.Init grids only the trigger. PlayerHitTrigger
                    # later removes it and AddToGrid(exit) inserts the door at
                    # the head.
                    ref = (
                        GRIDREF_STATIC,
                        int(StaticColliderKind.EXIT_SWITCH),
                        exit_index,
                    )
                    entry = self.static_world.entry_for_ref(ref)
                    if entry is not None:
                        grid_state.add(ref, (entry.cell_i, entry.cell_j))
                    exit_index += 1

            self._initial_update_uids = tuple(update_uids)
            self._initial_grid_state = grid_state

        assert self._initial_thinker_uids is not None
        assert self._initial_update_uids is not None
        assert self._initial_grid_state is not None

        # The cached level template must remain pristine across independent
        # initial states.  Detach once here; only search clones use the
        # copy-on-write form.
        grid_state = self._initial_grid_state.clone(copy_on_write=False)

        return SimulationState(
            player=self.player.clone(),
            objects=_clone_physics_objects(self.objects),
            edge_overrides=self.initial_edge_overrides.copy(),
            frame=0,
            think_timer=0,
            think_rate=2,
            thinker_uids=list(self._initial_thinker_uids),
            update_uids=list(self._initial_update_uids),
            grid_state=grid_state,
            static_world=self.static_world,
            static_state=StaticObjectState(),
        )


def parse_level_string(
    level_string: str,
    *,
    strict_shapes: bool = True,
    simulate_enemies: bool = False,
) -> Level:
    try:
        map_string, object_string = level_string.split("|", 1)
    except ValueError as exc:
        raise ValueError("level string must contain '|' between map and objects") from exc

    tiles = TileMap(map_string, strict_shapes=strict_shapes)
    specs: list[ObjectSpec] = []
    if object_string:
        for load_index, entry in enumerate(object_string.split("!")):
            type_text, params_text = entry.split("^", 1)
            params = tuple(float(x) for x in params_text.split(",") if x != "")
            specs.append(ObjectSpec(int(type_text), params, load_index))

    player_specs = [s for s in specs if s.obj_type == OBJTYPE_PLAYER]
    if len(player_specs) != 1:
        raise ValueError(f"expected exactly one player object, found {len(player_specs)}")
    px, py = player_specs[0].params
    player = Player.spawn(px, py)

    supported: list[PhysicsObject] = []
    passive_thinker_uids: list[int] = []
    initial_edge_overrides: EdgeOverrides = {}
    for spec in specs:
        if spec.obj_type == OBJTYPE_ONEWAYPLATFORM:
            supported.append(OneWayPlatform.from_spec(spec))
        elif spec.obj_type == OBJTYPE_LAUNCHPAD:
            supported.append(LaunchPad.from_spec(spec))
        elif spec.obj_type == OBJTYPE_BOUNCEBLOCK:
            supported.append(BounceBlock.from_spec(spec))
        elif spec.obj_type == OBJTYPE_FLOORGUARD and simulate_enemies:
            supported.append(FloorGuard.from_spec(spec, tiles, initial_edge_overrides))
        elif spec.obj_type == OBJTYPE_DRONE and simulate_enemies:
            if len(spec.params) == 6:
                weapon_type = int(spec.params[4])
                if weapon_type == DRONEWEAP_ZAP:
                    supported.append(ZapDrone.from_spec(spec, tiles))
                elif weapon_type == DRONEWEAP_LASER:
                    supported.append(LaserDrone.from_spec(spec, tiles))
                elif weapon_type == DRONEWEAP_CHAINGUN:
                    supported.append(ChaingunDrone.from_spec(spec, tiles))
        elif spec.obj_type == OBJTYPE_HOMINGLAUNCHER and simulate_enemies:
            supported.append(HomingLauncher.from_spec(spec, tiles))
        elif spec.obj_type == OBJTYPE_TURRET and simulate_enemies:
            supported.append(Turret.from_spec(spec, tiles))
        elif spec.obj_type == OBJTYPE_THWOMP:
            supported.append(Thwomp.from_spec(spec, tiles))
        elif spec.obj_type == OBJTYPE_TESTDOOR:
            supported.append(TestDoor.from_spec(spec, tiles, initial_edge_overrides))

    # Gold, mines, and exit/switches are immutable spatial descriptors shared
    # by every branch. Only their compact bitmask state is cloned.
    static_world = StaticWorld.from_specs(specs, tiles)

    # Grid linked lists insert at the head, so within a cell collision order is
    # reverse load order. This global approximation is exact when the selected
    # section's supported objects occupy the same queried cells.
    supported.sort(key=lambda obj: obj.load_index, reverse=True)
    return Level(
        tiles=tiles,
        player=player,
        objects=supported,
        all_specs=specs,
        static_world=static_world,
        initial_edge_overrides=initial_edge_overrides,
        simulate_enemies=simulate_enemies,
        passive_thinker_uids=tuple(passive_thinker_uids),
        source_level_string=level_string,
    )


def iter_actions() -> Iterator[InputFrame]:
    """Six practical control states: L/neutral/R crossed with jump held/released."""
    for horizontal in (-1, 0, 1):
        for jump in (False, True):
            yield InputFrame(left=horizontal < 0, right=horizontal > 0, jump=jump)


def simulate(
    level: Level,
    inputs: Iterable[InputFrame],
    *,
    clone_player: bool = True,
) -> Player:
    # ``clone_player`` is retained for API compatibility; simulations now clone
    # all mutable world objects as well as the player.
    state = level.initial_state()
    for frame in inputs:
        state.step(frame, level.tiles)
        if state.player.dead:
            break
    return state.player

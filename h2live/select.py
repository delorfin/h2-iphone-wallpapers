"""Chooses interesting map views by absolute rules, from what `fheroes2 --scout-maps` reports.

A window is the tile rectangle the renderer draws for one wallpaper: the visible area plus the pan
margin. Every chosen window must pass every rule; the bonus score only orders passing windows.
"""

import json
import math
import os
import pickle
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from random import Random

import numpy as np

TILE = 32

# The rules. Each is a hard limit; a window that misses any one is never used.
MAX_EMPTY_SQUARE = 4  # tiles; a 5x5 patch with no object reads as empty space
MAX_REPEAT_GROUP = 2  # identical objects touching each other, a pair is fine
MAX_TYPE_SHARE = 0.6  # of the occupied tiles, for the most common MP2 object type
MIN_TYPES = 3
MIN_ANIMATED_OBJECTS = 2
MIN_ANIMATED_TERRAIN = 4  # tiles of water or lava, which shimmer through palette cycling
# Share of 32x32 tiles in a rendered still that exactly duplicate another; the median view has 25%.
MAX_DUPLICATE_TILES = 0.4

RULES = ("empty", "repetition", "monoculture", "few types", "no animation")

GROUNDS = ("unknown", "water", "grass", "snow", "swamp", "lava", "desert", "dirt", "wasteland", "beach")
ANIMATED_GROUNDS = (GROUNDS.index("water"), GROUNDS.index("lava"))
OBJECT_LAYER, BACKGROUND_LAYER = 0, 1
OBJ_NONE, OBJ_COAST = 0, 28
# Bump when the cached form of scouted maps changes.
CACHE_VERSION = 1


def _base_type(object_type: int) -> int:
    """MP2 marks an object's action tile with its base type + 128 (and + 384 for Resurrection objects)."""
    return object_type - 128 if 128 <= object_type < 256 or object_type >= 384 else object_type


@dataclass(frozen=True)
class Window:
    """Tile rectangle: x, y of the top left tile, w, h in tiles."""

    x: int
    y: int
    w: int
    h: int

    def inside(self, m: "ScoutedMap") -> bool:
        return self.x >= 0 and self.y >= 0 and self.x + self.w <= m.width and self.y + self.h <= m.height

    def overlaps(self, other: "Window") -> bool:
        return (self.x < other.x + other.w and other.x < self.x + self.w
                and self.y < other.y + other.h and other.y < self.y + self.h)


@dataclass(frozen=True)
class View:
    """A window placed on a map, as the renderer takes it."""

    map: str
    x: int
    y: int


@dataclass
class Verdict:
    values: dict
    failures: list[str]


@dataclass
class ScoutedMap:
    path: str
    width: int
    height: int
    occupied: np.ndarray  # (height, width) bool
    ground: np.ndarray  # (height, width) index into GROUNDS
    kind: np.ndarray  # (height, width) base MP2 object type; 0 empty, -1 occupied by an unknown type
    # One entry per object (parts sharing a uid). Signature -1: nothing solid, e.g. a water ripple.
    signature: np.ndarray
    x0: np.ndarray
    y0: np.ndarray
    x1: np.ndarray
    y1: np.ndarray
    animated: np.ndarray
    links: np.ndarray = field(default=None)  # (n, 2) pairs of touching identical objects

    def __post_init__(self):
        if self.links is None:
            self.links = _find_links(self)


def window_tiles(width_px: int, height_px: int) -> tuple[int, int]:
    """Tiles the renderer touches for a view of this many map pixels drawn from a tile corner."""
    return math.ceil(width_px / TILE), math.ceil(height_px / TILE)


def load_map(scout: dict) -> ScoutedMap:
    width, height, tiles = scout["width"], scout["height"], scout["tiles"]
    occupied = np.zeros(width * height, bool)
    ground = np.zeros(width * height, np.int8)
    kind = np.zeros(width * height, np.int16)
    objects: dict = defaultdict(lambda: {"solid": set(), "tiles": [], "solid_tiles": [], "animated": False})
    for index, tile in enumerate(tiles):
        occupied[index] = tile["occupied"]
        ground[index] = GROUNDS.index(tile["ground"]) if tile["ground"] in GROUNDS else 0
        solid_types = []
        for n, (uid, icn, sprite, layer, animated, part_type) in enumerate(tile["parts"]):
            obj = objects[uid if uid else ("tile", index, n)]
            obj["tiles"].append(index)
            obj["animated"] |= bool(animated)
            if layer in (OBJECT_LAYER, BACKGROUND_LAYER):
                obj["solid"].add((icn, sprite))
                obj["solid_tiles"].append(index)
                if part_type != OBJ_NONE:
                    solid_types.append(_base_type(part_type))
        if tile["occupied"]:
            main = _base_type(tile["object"])
            kind[index] = main if main not in (OBJ_NONE, OBJ_COAST) else (solid_types[0] if solid_types else -1)

    signatures: dict = {}
    rows = []
    for obj in objects.values():
        where = np.array(obj["solid_tiles"] or obj["tiles"])
        xs, ys = where % width, where // width
        signature = signatures.setdefault(frozenset(obj["solid"]), len(signatures)) if obj["solid"] else -1
        rows.append((signature, xs.min(), ys.min(), xs.max(), ys.max(), obj["animated"]))
    columns = np.array(rows, dtype=np.int64).reshape(-1, 6).T
    return ScoutedMap(
        path=scout["map"], width=width, height=height,
        occupied=occupied.reshape(height, width), ground=ground.reshape(height, width), kind=kind.reshape(height, width),
        signature=columns[0].astype(np.int32), x0=columns[1].astype(np.int16), y0=columns[2].astype(np.int16),
        x1=columns[3].astype(np.int16), y1=columns[4].astype(np.int16), animated=columns[5].astype(bool),
    )


def _find_links(m: ScoutedMap) -> np.ndarray:
    """Pairs of objects with the same sprites whose tiles touch, diagonals included."""
    links = []
    order = np.argsort(m.signature, kind="stable")
    signatures = m.signature[order]
    starts = np.flatnonzero(np.diff(signatures, prepend=-2))
    for start, end in zip(starts, list(starts[1:]) + [len(order)]):
        group = order[start:end]
        if signatures[start] < 0 or len(group) < 2:
            continue
        x0, y0, x1, y1 = (a[group].astype(np.int32) for a in (m.x0, m.y0, m.x1, m.y1))
        touch = ((x0[:, None] <= x1[None, :] + 1) & (x0[None, :] <= x1[:, None] + 1)
                 & (y0[:, None] <= y1[None, :] + 1) & (y0[None, :] <= y1[:, None] + 1))
        a, b = np.nonzero(np.triu(touch, 1))
        links.append(np.stack([group[a], group[b]], axis=1))
    return np.concatenate(links) if links else np.zeros((0, 2), np.int64)


def _present(m: ScoutedMap, win: Window) -> np.ndarray:
    return (m.x0 < win.x + win.w) & (m.x1 >= win.x) & (m.y0 < win.y + win.h) & (m.y1 >= win.y)


def _area(grid: np.ndarray, win: Window) -> np.ndarray:
    return grid[win.y:win.y + win.h, win.x:win.x + win.w]


def largest_empty_square(m: ScoutedMap, win: Window) -> int:
    empty = ~_area(m.occupied, win)
    size = np.zeros((empty.shape[0] + 1, empty.shape[1] + 1), np.int32)
    for y in range(empty.shape[0]):
        for x in range(empty.shape[1]):
            if empty[y, x]:
                size[y + 1, x + 1] = 1 + min(size[y, x + 1], size[y + 1, x], size[y, x])
    return int(size.max())


def largest_repeat_group(m: ScoutedMap, win: Window) -> int:
    present = _present(m, win) & (m.signature >= 0)
    parent = {int(i): int(i) for i in np.flatnonzero(present)}

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in m.links:
        if present[a] and present[b]:
            parent[root(int(a))] = root(int(b))
    sizes = defaultdict(int)
    for i in parent:
        sizes[root(i)] += 1
    return max(sizes.values(), default=0)


def type_mix(m: ScoutedMap, win: Window) -> tuple[float, int]:
    """Share of occupied tiles held by the most common object type, and the number of types."""
    kinds = _area(m.kind, win)
    occupied = int(_area(m.occupied, win).sum())
    types, counts = np.unique(kinds[kinds > 0], return_counts=True)
    return (int(counts.max()) / occupied if occupied and len(counts) else 0.0), len(types)


def animation(m: ScoutedMap, win: Window) -> tuple[int, int]:
    """Animated objects and tiles of animated terrain in the window."""
    terrain = int(np.isin(_area(m.ground, win), ANIMATED_GROUNDS).sum())
    return int((_present(m, win) & m.animated).sum()), terrain


def bonus(m: ScoutedMap, win: Window) -> int:
    """Only orders passing windows: distinct object sprites plus distinct terrains."""
    signatures = np.unique(m.signature[_present(m, win) & (m.signature >= 0)])
    return len(signatures) + len(np.unique(_area(m.ground, win)))


def check(m: ScoutedMap, win: Window) -> Verdict:
    if not win.inside(m):
        return Verdict({"inside": False}, ["off map"])
    share, types = type_mix(m, win)
    animated_objects, animated_terrain = animation(m, win)
    values = {
        "inside": True,
        "empty": largest_empty_square(m, win),
        "repetition": largest_repeat_group(m, win),
        "share": share,
        "types": types,
        "animated objects": animated_objects,
        "animated terrain": animated_terrain,
    }
    failures = []
    if values["empty"] > MAX_EMPTY_SQUARE:
        failures.append("empty")
    if values["repetition"] > MAX_REPEAT_GROUP:
        failures.append("repetition")
    if share > MAX_TYPE_SHARE:
        failures.append("monoculture")
    if types < MIN_TYPES:
        failures.append("few types")
    if animated_objects < MIN_ANIMATED_OBJECTS and animated_terrain < MIN_ANIMATED_TERRAIN:
        failures.append("no animation")
    return Verdict(values, failures)


# Every window position of a map at once.

def _integral(grid: np.ndarray) -> np.ndarray:
    out = np.zeros((grid.shape[0] + 1, grid.shape[1] + 1), np.int32)
    out[1:, 1:] = grid.astype(np.int32).cumsum(0).cumsum(1)
    return out


def _box_sums(grid: np.ndarray, w: int, h: int) -> np.ndarray:
    """Sum of `grid` over every w x h box, indexed by the box's top left tile."""
    s = _integral(grid)
    return s[h:, w:] - s[:-h, w:] - s[h:, :-w] + s[:-h, :-w]


def _window_range(start: np.ndarray, end: np.ndarray, size: int, count: int) -> tuple[np.ndarray, np.ndarray]:
    """Window positions along one axis whose span meets tiles start..end."""
    return np.maximum(start - size + 1, 0), np.minimum(end, count - 1)


def _count_rects(y0, y1, x0, x1, shape) -> np.ndarray:
    """How many of the given inclusive rectangles of window positions cover each position."""
    keep = (y0 <= y1) & (x0 <= x1)
    y0, y1, x0, x1 = y0[keep], y1[keep], x0[keep], x1[keep]
    diff = np.zeros((shape[0] + 1, shape[1] + 1), np.int32)
    np.add.at(diff, (y0, x0), 1)
    np.add.at(diff, (y0, x1 + 1), -1)
    np.add.at(diff, (y1 + 1, x0), -1)
    np.add.at(diff, (y1 + 1, x1 + 1), 1)
    return diff.cumsum(0).cumsum(1)[:shape[0], :shape[1]]


def passing_windows(m: ScoutedMap, w: int, h: int) -> dict[str, np.ndarray]:
    """Per rule, a (rows, columns) grid telling whether the window with that top left tile passes."""
    shape = (max(m.height - h + 1, 0), max(m.width - w + 1, 0))
    if 0 in shape:
        return {rule: np.zeros(shape, bool) for rule in (*RULES, "all")}

    grids = {}
    side = MAX_EMPTY_SQUARE + 1
    if w >= side and h >= side:
        empty_blocks = _box_sums(m.occupied, side, side) == 0
        grids["empty"] = _box_sums(empty_blocks, w - side + 1, h - side + 1) == 0
    else:
        grids["empty"] = np.ones(shape, bool)

    # Any group of three or more contains a chain a-b-c; a window fails if it meets all three objects.
    wy0, wy1 = _window_range(m.y0.astype(np.int32), m.y1.astype(np.int32), h, shape[0])
    wx0, wx1 = _window_range(m.x0.astype(np.int32), m.x1.astype(np.int32), w, shape[1])
    neighbours = defaultdict(list)
    for a, b in m.links:
        neighbours[a].append(b)
        neighbours[b].append(a)
    chains = [(a, b, c) for b, near in neighbours.items() for i, a in enumerate(near) for c in near[i + 1:]]
    if chains:
        a, b, c = np.array(chains).T
        repeats = _count_rects(np.maximum.reduce([wy0[a], wy0[b], wy0[c]]), np.minimum.reduce([wy1[a], wy1[b], wy1[c]]),
                               np.maximum.reduce([wx0[a], wx0[b], wx0[c]]), np.minimum.reduce([wx1[a], wx1[b], wx1[c]]), shape)
        grids["repetition"] = repeats == 0
    else:
        grids["repetition"] = np.ones(shape, bool)

    occupied = _box_sums(m.occupied, w, h)
    most, types = np.zeros(shape, np.int32), np.zeros(shape, np.int32)
    for kind in np.unique(m.kind[m.kind > 0]):
        count = _box_sums(m.kind == kind, w, h)
        most = np.maximum(most, count)
        types += count > 0
    grids["monoculture"] = most <= MAX_TYPE_SHARE * occupied + 1e-9
    grids["few types"] = types >= MIN_TYPES

    animated = m.animated
    objects = _count_rects(wy0[animated], wy1[animated], wx0[animated], wx1[animated], shape)
    terrain = _box_sums(np.isin(m.ground, ANIMATED_GROUNDS), w, h)
    grids["no animation"] = (objects >= MIN_ANIMATED_OBJECTS) | (terrain >= MIN_ANIMATED_TERRAIN)

    grids["all"] = np.logical_and.reduce([grids[rule] for rule in RULES])
    return grids


class NotEnoughViews(Exception):
    pass


def select_views(maps: list[ScoutedMap], count: int, w: int, h: int, rng: Random, exclude=(), candidates: int = 4) -> list[View]:
    """`count` passing views, one per map in random order before any map gets a second.

    Views on one map never overlap, nor overlap an excluded view. Within a map the pick is random,
    with the bonus score choosing among a few random candidates.
    """
    blocked = defaultdict(list)
    for view in exclude:
        blocked[view.map].append(Window(view.x, view.y, w, h))
    open_windows = {}
    for m in maps:
        ys, xs = np.nonzero(passing_windows(m, w, h)["all"])
        if len(xs):
            open_windows[m.path] = (m, [Window(int(x), int(y), w, h) for x, y in zip(xs, ys)])

    views: list[View] = []
    order = list(open_windows)
    rng.shuffle(order)
    while len(views) < count and order:
        still_open = []
        for path in order:
            if len(views) == count:
                break
            m, windows = open_windows[path]
            windows = [win for win in windows if not any(win.overlaps(b) for b in blocked[path])]
            if not windows:
                continue
            pick = max(rng.sample(windows, min(candidates, len(windows))), key=lambda win: bonus(m, win))
            views.append(View(path, pick.x, pick.y))
            blocked[path].append(pick)
            open_windows[path] = (m, windows)
            still_open.append(path)
        order = still_open
    if len(views) < count:
        raise NotEnoughViews(f"Found {len(views)} of {count} views that pass every rule; "
                             "ask for fewer or relax a rule in h2live/select.py")
    return views


def duplicate_tile_share(pixels: np.ndarray) -> float:
    """Share of 32x32 tiles of a still that exactly repeat another tile, for the grid alignment with the most."""
    best = 0.0
    height, width = pixels.shape
    for oy in range(min(TILE, height)):
        for ox in range(min(TILE, width)):
            rows, cols = (height - oy) // TILE, (width - ox) // TILE
            if rows * cols < 2:
                continue
            tiles = pixels[oy:oy + rows * TILE, ox:ox + cols * TILE].reshape(rows, TILE, cols, TILE).swapaxes(1, 2)
            flat = np.ascontiguousarray(tiles.reshape(rows * cols, TILE * TILE)).view(f"V{TILE * TILE}").ravel()
            _, inverse, counts = np.unique(flat, return_inverse=True, return_counts=True)
            best = max(best, float((counts[inverse] > 1).sum()) / len(flat))
    return best


def bmp_pixels(path: Path) -> np.ndarray:
    """Palette indices of an 8-bit BMP, top row first."""
    data = path.read_bytes()
    offset = int.from_bytes(data[10:14], "little")
    width = int.from_bytes(data[18:22], "little", signed=True)
    height = int.from_bytes(data[22:26], "little", signed=True)
    stride = (width + 3) // 4 * 4
    rows = np.frombuffer(data, np.uint8, abs(height) * stride, offset).reshape(abs(height), stride)[:, :width]
    return rows if height < 0 else rows[::-1]


# Scouting.

def scout_maps(renderer: Path, game_data: Path, cache_dir: Path) -> list[ScoutedMap]:
    """Every map the renderer can load, scouted once per renderer build and cached."""
    stat = renderer.stat()
    cache = cache_dir / f"maps-v{CACHE_VERSION}-{stat.st_size}-{stat.st_mtime_ns}.pickle"
    # The cache is ours alone, written just below from the renderer's output.
    if cache.exists():
        return pickle.loads(cache.read_bytes())

    with tempfile.TemporaryDirectory() as scratch:
        result = subprocess.run([str(renderer), "--scout-maps", scratch], capture_output=True, text=True,
                                env={**os.environ, "FHEROES2_DATA": str(game_data)})
        if result.returncode != 0:
            raise RuntimeError(f"scouting maps failed with exit code {result.returncode}: {result.stderr[-2000:]}")
        maps = [load_map(json.loads(path.read_text())) for path in sorted(Path(scratch).glob("*.json"))]

    cache_dir.mkdir(parents=True, exist_ok=True)
    for old in cache_dir.glob("maps-*.pickle"):
        old.unlink()
    cache.write_bytes(pickle.dumps(maps))
    return maps

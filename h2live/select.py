"""Chooses interesting map views by absolute rules, from what `fheroes2 --scout-maps` reports.

A window is the tile rectangle the renderer draws for one wallpaper: the visible area plus the pan
margin. Every chosen window must pass every rule; the bonus score only orders passing windows.
"""

import json
import math
import os
import pickle
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from random import Random

import numpy as np

from h2live.gamedata import maps_folder

TILE = 32

# The rules. Each is a hard limit; a window that misses any one is never used.
# A tile is blank when it has no object and its terrain matches all 8 neighbours; tiles along a
# border between terrains are not blank. Roads and rivers don't fill space (sheet 2-02, 2-38).
# The lock screen clock covers about 7 tile rows at the top of the window, but the rules still look at
# the whole window: empty space under the clock read as "emptyish" too (sheet 2-33).
# "Sheet" tags refer to the author's calibration verdicts, pinned in tests/test_sheet_verdicts.py.
MAX_EMPTY_SQUARE = 5  # tiles; a blank 6x6 square reads as empty space
# Share of the view in blank 2x2 patches: views whose objects bunch up between blank gaps fail.
BLANK_PATCH = 2
MAX_BLANK_PATCH_SHARE = 0.45
MIN_OCCUPIED_SHARE = 0.22  # of the view's tiles holding an object
# A view fails when one sprite has this many copies and covers this share of the objects' area.
FREQUENT_COPIES = 8
MAX_SPRITE_SHARE = 0.65
MAX_TYPE_SHARE = 0.65  # of the occupied tiles, for the most common MP2 object type
MIN_TYPES = 3
MIN_ANIMATED_OBJECTS = 2
MIN_ANIMATED_TERRAIN = 4  # tiles of water or lava, which shimmer through palette cycling

RULES = ("empty", "clumped", "sparse", "repetition", "frequency", "monoculture", "few types", "no animation")

GROUNDS = ("unknown", "water", "grass", "snow", "swamp", "lava", "desert", "dirt", "wasteland", "beach")
ANIMATED_GROUNDS = (GROUNDS.index("water"), GROUNDS.index("lava"))
OBJECT_LAYER, BACKGROUND_LAYER, TERRAIN_LAYER = 0, 1, 3
# Terrain-layer sprites that run along the ground (roads, rivers); other terrain-layer sprites are
# small objects such as cracks, holes and flowers.
LINE_ICNS = (30, 45)
OBJ_NONE, OBJ_COAST = 0, 28
# Bump when the cached form of scouted maps changes.
CACHE_VERSION = 5


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
    blank: np.ndarray  # (height, width) bool
    ground: np.ndarray  # (height, width) index into GROUNDS
    kind: np.ndarray  # (height, width) base MP2 object type; 0 empty, -1 occupied by an unknown type
    # One entry per object (parts sharing a uid). Signature -1: nothing solid, e.g. a water ripple.
    signature: np.ndarray
    x0: np.ndarray
    y0: np.ndarray
    x1: np.ndarray
    y1: np.ndarray
    animated: np.ndarray
    # Identical objects in a regular arrangement: (n, 3) touching rows at equal steps, (n, 4) 2x2 blocks.
    lines: np.ndarray = field(default=None)
    blocks: np.ndarray = field(default=None)
    # Tiles that lie in some blank 2x2 patch.
    in_blank_patch: np.ndarray = field(default=None)

    def __post_init__(self):
        if self.lines is None:
            self.lines, self.blocks = _find_patterns(self)
        if self.in_blank_patch is None:
            patches = np.zeros((self.height + 2 * (BLANK_PATCH - 1), self.width + 2 * (BLANK_PATCH - 1)), bool)
            if self.height >= BLANK_PATCH and self.width >= BLANK_PATCH:
                patches[BLANK_PATCH - 1:self.height, BLANK_PATCH - 1:self.width] = (
                    _box_sums(self.blank, BLANK_PATCH, BLANK_PATCH) == BLANK_PATCH ** 2)
            self.in_blank_patch = _box_sums(patches, BLANK_PATCH, BLANK_PATCH)[:self.height, :self.width] > 0


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
        ground[index] = GROUNDS.index(tile["ground"]) if tile["ground"] in GROUNDS else 0
        solid_types = []
        decorated = False
        for n, (uid, icn, sprite, layer, animated, part_type) in enumerate(tile["parts"]):
            obj = objects[uid if uid else ("tile", index, n)]
            obj["tiles"].append(index)
            obj["animated"] |= bool(animated)
            is_decoration = layer == TERRAIN_LAYER and icn not in LINE_ICNS
            decorated |= is_decoration
            if layer in (OBJECT_LAYER, BACKGROUND_LAYER) or is_decoration:
                obj["solid"].add((icn, sprite))
                obj["solid_tiles"].append(index)
                if part_type != OBJ_NONE:
                    solid_types.append(_base_type(part_type))
        occupied[index] = tile["occupied"] or decorated
        if tile["occupied"]:
            main = _base_type(tile["object"])
            kind[index] = main if main not in (OBJ_NONE, OBJ_COAST) else (solid_types[0] if solid_types else -1)
        elif decorated:
            kind[index] = -1

    ground_grid = ground.reshape(height, width)
    padded = np.full((height + 2, width + 2), -1, np.int16)
    padded[1:-1, 1:-1] = ground_grid
    uniform = np.ones((height, width), bool)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            near = padded[dy:dy + height, dx:dx + width]
            uniform &= (near == ground_grid) | (near == -1)
    blank = uniform & ~occupied.reshape(height, width)

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
        occupied=occupied.reshape(height, width), blank=blank, ground=ground_grid, kind=kind.reshape(height, width),
        signature=columns[0].astype(np.int32), x0=columns[1].astype(np.int16), y0=columns[2].astype(np.int16),
        x1=columns[3].astype(np.int16), y1=columns[4].astype(np.int16), animated=columns[5].astype(bool),
    )


def _find_patterns(m: ScoutedMap) -> tuple[np.ndarray, np.ndarray]:
    """Identical objects in a row or block: three touching copies in a straight line, or four as a 2x2 block.

    Identical objects have the same shape, so one step between their top left tiles moves the whole
    object. Irregular clusters, such as most forests and mountain ranges, have neither.
    """
    lines, blocks = set(), set()
    order = np.argsort(m.signature, kind="stable")
    signatures = m.signature[order]
    starts = np.flatnonzero(np.diff(signatures, prepend=-2))
    for start, end in zip(starts, list(starts[1:]) + [len(order)]):
        group = order[start:end]
        if signatures[start] < 0 or len(group) < 3:
            continue
        x0, y0, x1, y1 = (a[group].astype(np.int32) for a in (m.x0, m.y0, m.x1, m.y1))
        touch = ((x0[:, None] <= x1[None, :] + 1) & (x0[None, :] <= x1[:, None] + 1)
                 & (y0[:, None] <= y1[None, :] + 1) & (y0[None, :] <= y1[:, None] + 1))
        np.fill_diagonal(touch, False)
        at = {(int(x), int(y)): int(i) for x, y, i in zip(x0, y0, group)}
        steps = defaultdict(list)
        for a, b in zip(*np.nonzero(touch)):
            steps[int(group[a])].append((int(x0[b] - x0[a]), int(y0[b] - y0[a])))
        # Rows run along a row, column or diagonal, each copy clear of the last. Overlapping copies
        # blend into one mass (a forest), and slanted steps read as a loose cluster.
        w, h = int(x1[0] - x0[0]) + 1, int(y1[0] - y0[0]) + 1
        for i, x, y in zip(group, x0, y0):
            i, x, y = int(i), int(x), int(y)
            steps[i] = [(dx, dy) for dx, dy in steps[i]
                        if (dx, dy) != (0, 0) and (dx == 0 or abs(dx) >= w) and (dy == 0 or abs(dy) >= h)]
            for dx, dy in steps[i]:
                c = at.get((x + 2 * dx, y + 2 * dy))
                if c is not None:
                    b = at[(x + dx, y + dy)]
                    lines.add((min(i, c), b, max(i, c)))
            for dx, _ in (st for st in steps[i] if st[1] == 0 and st[0] > 0):
                for _, dy in (st for st in steps[i] if st[0] == 0 and st[1] > 0):
                    d = at.get((x + dx, y + dy))
                    if d is not None:
                        blocks.add((i, at[(x + dx, y)], at[(x, y + dy)], d))
    return (np.array(sorted(lines), np.int64).reshape(-1, 3), np.array(sorted(blocks), np.int64).reshape(-1, 4))


def _present(m: ScoutedMap, win: Window) -> np.ndarray:
    return (m.x0 < win.x + win.w) & (m.x1 >= win.x) & (m.y0 < win.y + win.h) & (m.y1 >= win.y)


def _area(grid: np.ndarray, win: Window) -> np.ndarray:
    return grid[win.y:win.y + win.h, win.x:win.x + win.w]


def empty_square(m: ScoutedMap, win: Window) -> tuple[int, int, int]:
    """Side and top left tile (relative to the window) of the largest blank square."""
    empty = _area(m.blank, win)
    size = np.zeros((empty.shape[0] + 1, empty.shape[1] + 1), np.int32)
    for y in range(empty.shape[0]):
        for x in range(empty.shape[1]):
            if empty[y, x]:
                size[y + 1, x + 1] = 1 + min(size[y, x + 1], size[y + 1, x], size[y, x])
    y, x = np.unravel_index(np.argmax(size), size.shape)
    side = int(size[y, x])
    return side, int(x) - side, int(y) - side


def largest_empty_square(m: ScoutedMap, win: Window) -> int:
    return empty_square(m, win)[0]


def _areas(m: ScoutedMap) -> np.ndarray:
    return (m.x1.astype(np.int32) - m.x0 + 1) * (m.y1.astype(np.int32) - m.y0 + 1)


def top_sprite(m: ScoutedMap, win: Window) -> tuple[int, float]:
    """Copies of the most common sprite in the window, and its share of all objects' area (bounding boxes)."""
    present = _present(m, win) & (m.signature >= 0)
    if not present.any():
        return 0, 0.0
    signatures, inverse = np.unique(m.signature[present], return_inverse=True)
    copies = np.bincount(inverse)
    area = np.bincount(inverse, weights=_areas(m)[present])
    top = int(np.argmax(area))
    return int(copies[top]), float(area[top] / area.sum())


def blank_patch_share(m: ScoutedMap, win: Window) -> float:
    return float(_area(m.in_blank_patch, win).mean())


def occupied_share(m: ScoutedMap, win: Window) -> float:
    return float(_area(m.occupied, win).mean())


def regular_patterns(m: ScoutedMap, win: Window) -> list[tuple[int, ...]]:
    """Rows and blocks of identical objects that are all in the window."""
    present = _present(m, win)
    return [tuple(int(i) for i in p) for patterns in (m.lines, m.blocks) for p in patterns if present[p].all()]


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
    copies, sprite_share = top_sprite(m, win)
    values = {
        "inside": True,
        "empty": largest_empty_square(m, win),
        "blank patches": blank_patch_share(m, win),
        "occupied": occupied_share(m, win),
        "repetition": len(regular_patterns(m, win)),
        "top sprite copies": copies,
        "top sprite share": sprite_share,
        "share": share,
        "types": types,
        "animated objects": animated_objects,
        "animated terrain": animated_terrain,
    }
    failures = []
    if values["empty"] > MAX_EMPTY_SQUARE:
        failures.append("empty")
    if values["blank patches"] > MAX_BLANK_PATCH_SHARE + 1e-9:
        failures.append("clumped")
    if values["occupied"] < MIN_OCCUPIED_SHARE - 1e-9:
        failures.append("sparse")
    if values["repetition"]:
        failures.append("repetition")
    if copies >= FREQUENT_COPIES and sprite_share > MAX_SPRITE_SHARE + 1e-9:
        failures.append("frequency")
    if share > MAX_TYPE_SHARE + 1e-9:
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


def _count_rects(y0, y1, x0, x1, shape, weights=None) -> np.ndarray:
    """How many of the given inclusive rectangles of window positions cover each position (or their summed weights)."""
    keep = (y0 <= y1) & (x0 <= x1)
    y0, y1, x0, x1 = y0[keep], y1[keep], x0[keep], x1[keep]
    weights = np.ones(len(y0), np.int64) if weights is None else weights[keep]
    diff = np.zeros((shape[0] + 1, shape[1] + 1), weights.dtype)
    np.add.at(diff, (y0, x0), weights)
    np.add.at(diff, (y0, x1 + 1), -weights)
    np.add.at(diff, (y1 + 1, x0), -weights)
    np.add.at(diff, (y1 + 1, x1 + 1), weights)
    return diff.cumsum(0).cumsum(1)[:shape[0], :shape[1]]


def passing_windows(m: ScoutedMap, w: int, h: int) -> dict[str, np.ndarray]:
    """Per rule, a (rows, columns) grid telling whether the window with that top left tile passes."""
    shape = (max(m.height - h + 1, 0), max(m.width - w + 1, 0))
    if 0 in shape:
        return {rule: np.zeros(shape, bool) for rule in (*RULES, "all")}

    grids = {}
    def window_sums(grid: np.ndarray, box_w: int, box_h: int) -> np.ndarray:
        return _box_sums(grid, box_w, box_h)[:shape[0], :shape[1]]

    side = MAX_EMPTY_SQUARE + 1
    if w >= side and h >= side:
        empty_blocks = _box_sums(m.blank, side, side) == side * side
        grids["empty"] = window_sums(empty_blocks, w - side + 1, h - side + 1) == 0
    else:
        grids["empty"] = np.ones(shape, bool)

    grids["clumped"] = window_sums(m.in_blank_patch, w, h) <= MAX_BLANK_PATCH_SHARE * w * h + 1e-9
    grids["sparse"] = window_sums(m.occupied, w, h) >= MIN_OCCUPIED_SHARE * w * h - 1e-9
    occupied = _box_sums(m.occupied, w, h)

    # A window fails if it meets every object of some row or block.
    wy0, wy1 = _window_range(m.y0.astype(np.int32), m.y1.astype(np.int32), h, shape[0])
    wx0, wx1 = _window_range(m.x0.astype(np.int32), m.x1.astype(np.int32), w, shape[1])
    repeats = np.zeros(shape, np.int32)
    for patterns in (m.lines, m.blocks):
        if len(patterns):
            members = patterns.T
            repeats += _count_rects(np.max(wy0[members], axis=0), np.min(wy1[members], axis=0),
                                    np.max(wx0[members], axis=0), np.min(wx1[members], axis=0), shape)
    grids["repetition"] = repeats == 0

    # Only sprites with enough copies somewhere on the map can fail the frequency rule.
    solid = m.signature >= 0
    areas = _areas(m).astype(np.int64)
    total = _count_rects(wy0[solid], wy1[solid], wx0[solid], wx1[solid], shape, areas[solid])
    frequent = np.zeros(shape, bool)
    signatures, counts = np.unique(m.signature[solid], return_counts=True)
    for signature in signatures[counts >= FREQUENT_COPIES]:
        mine = m.signature == signature
        copies = _count_rects(wy0[mine], wy1[mine], wx0[mine], wx1[mine], shape)
        area = _count_rects(wy0[mine], wy1[mine], wx0[mine], wx1[mine], shape, areas[mine])
        frequent |= (copies >= FREQUENT_COPIES) & (area > MAX_SPRITE_SHARE * total + 1e-9)
    grids["frequency"] = ~frequent

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


# Scouting.

# fheroes2's own maps (.fh2m), shipped with the engine so the tool has maps beyond the user's game data.
BUNDLED_MAPS = Path(__file__).resolve().parents[1] / "engine" / "maps"
MAP_SUFFIXES = (".mp2", ".mx2", ".fh2m")


def map_files(game_data: Path) -> list[Path]:
    """The maps in the user's game data, then the maps bundled with the engine."""
    bundled = Path(os.environ.get("H2LIVE_BUNDLED_MAPS", BUNDLED_MAPS))
    found = []
    for folder in (maps_folder(game_data), bundled):
        if folder is not None and folder.is_dir():
            found += sorted((p for p in folder.iterdir() if p.suffix.lower() in MAP_SUFFIXES), key=lambda p: p.name.lower())
    return found


# How long one engine call may take; on some errors the engine waits forever on a dialog nobody sees.
ENGINE_TIMEOUT = 600


class ScoutFailed(Exception):
    """The engine failed for a reason other than the map, e.g. missing game data or a crash."""


def engine_error(stderr: str) -> str:
    lines = [line for line in stderr.splitlines() if "[ERROR]" in line]
    return (lines[-1] if lines else stderr.strip()[-300:]) or "no error message"


def scout_one(renderer: Path, game_data: Path, map_file: Path) -> "ScoutedMap | None":
    """Scouts one map in its own renderer process: loading several maps in one process lets engine
    state carry over, so random objects would differ from the later render. None if the map itself
    can't be loaded; ScoutFailed for anything else, which says nothing about the map."""
    with tempfile.TemporaryDirectory() as scratch:
        try:
            result = subprocess.run([str(renderer), "--scout-maps", scratch, str(map_file)], capture_output=True,
                                    text=True, env={**os.environ, "FHEROES2_DATA": str(game_data)}, timeout=ENGINE_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ScoutFailed(f"the engine took over {ENGINE_TIMEOUT} s on {map_file}") from None
        written = list(Path(scratch).glob("*.json"))
        if written:
            return load_map(json.loads(written[0].read_text()))
        if "Could not read map" in result.stderr or "Could not load map" in result.stderr:
            return None
        raise ScoutFailed(engine_error(result.stderr))


def scout_maps(renderer: Path, game_data: Path, cache_dir: Path, maps: list[Path] | None = None) -> list[ScoutedMap]:
    """Every map the renderer can load. The cache remembers each map file by size and modification time,
    so only new or changed maps get scouted; removed maps drop out; a renderer rebuild or other game data
    rescouts all. Maps that fail for reasons other than the map itself are left out of the cache and retried."""
    stat = renderer.stat()
    build = f"{stat.st_size}-{stat.st_mtime_ns} {game_data.resolve()}"
    cache = cache_dir / f"maps-v{CACHE_VERSION}.pickle"
    known = {}
    # The cache is ours alone, written below from the renderer's output.
    if cache.exists():
        stored = pickle.loads(cache.read_bytes())
        if stored["build"] == build:
            known = stored["maps"]

    files = maps if maps is not None else map_files(game_data)
    stamps = {str(f): (f.stat().st_size, f.stat().st_mtime_ns) for f in files}
    todo = [f for f in files if str(f) not in known or known[str(f)][0] != stamps[str(f)]]
    def attempt(map_file: Path) -> "ScoutedMap | None | ScoutFailed":
        try:
            return scout_one(renderer, game_data, map_file)
        except ScoutFailed as error:
            return error

    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        fresh = list(pool.map(attempt, todo))
    failures = [(f, result) for f, result in zip(todo, fresh) if isinstance(result, ScoutFailed)]
    # Maps that can't be loaded are kept as None, so they aren't retried every batch.
    current = {path: known[path] for path in stamps if path in known and known[path][0] == stamps[path]}
    current.update({str(f): (stamps[str(f)], result) for f, result in zip(todo, fresh) if not isinstance(result, ScoutFailed)})

    if current != known or not cache.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        partial = cache.with_suffix(".partial")
        partial.write_bytes(pickle.dumps({"build": build, "maps": current}))
        partial.replace(cache)  # a batch killed mid-write leaves the old cache intact
        for old in cache_dir.glob("maps-*.pickle"):
            if old != cache:
                old.unlink()

    found = [scouted for path, (_, scouted) in sorted(current.items()) if scouted is not None]
    if failures and found:
        print(f"{len(failures)} maps couldn't be scouted and will be retried next time; "
              f"{Path(failures[0][0]).name}: {failures[0][1]}", file=sys.stderr)
    if not found:
        reason = f"; the engine said: {failures[-1][1]}" if failures else ""
        raise RuntimeError(f"scouting found no loadable maps in {game_data} or the bundled maps{reason}")
    return found

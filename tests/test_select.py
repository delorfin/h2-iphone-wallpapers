import random

import numpy as np
import pytest

from h2live.select import (
    NotEnoughViews,
    View,
    Window,
    animation,
    check,
    duplicate_tile_share,
    blank_patch_share,
    top_sprite,
    empty_square,
    largest_empty_square,
    load_map,
    occupied_share,
    passing_windows,
    regular_patterns,
    select_views,
    type_mix,
    window_tiles,
)

TREES, MOUNTAINS, ROCK, LAKE = 99, 100, 103, 104
TREE_ICN, MOUNTAIN_ICN, ROCK_ICN = 49, 32, 51
ROAD_ICN, DIRT_DECOR_ICN = 30, 56


class Scout:
    """Builds a scout record like `fheroes2 --scout-maps` writes, one object at a time."""

    def __init__(self, width: int, height: int, ground: str = "grass"):
        self.width, self.height = width, height
        self.tiles = [{"ground": ground, "object": 0, "occupied": False, "parts": []} for _ in range(width * height)]
        self.next_uid = 1

    def tile(self, x: int, y: int) -> dict:
        return self.tiles[y * self.width + x]

    def add(self, x: int, y: int, kind: int = TREES, icn: int = TREE_ICN, sprite: int = 0, size: tuple[int, int] = (1, 1),
            animated: bool = False) -> "Scout":
        """An object of `size` tiles with its top left at x, y; `sprite` picks its set of sprites."""
        uid, self.next_uid = self.next_uid, self.next_uid + 1
        w, h = size
        for dy in range(h):
            for dx in range(w):
                tile = self.tile(x + dx, y + dy)
                tile["object"], tile["occupied"] = kind, True
                tile["parts"].append([uid, icn, sprite * 16 + dy * w + dx, 0, int(animated), kind])
        return self

    def shadow(self, x: int, y: int, animated: bool = False) -> "Scout":
        uid, self.next_uid = self.next_uid, self.next_uid + 1
        self.tile(x, y)["parts"].append([uid, 50, 7, 2, int(animated), 0])
        return self

    def terrain(self, x: int, y: int, icn: int) -> "Scout":
        """A terrain-layer part: a road, river or ground decoration."""
        uid, self.next_uid = self.next_uid, self.next_uid + 1
        self.tile(x, y)["parts"].append([uid, icn, 3, 3, 0, 0])
        return self

    def water(self, x: int, y: int, w: int, h: int) -> "Scout":
        for dy in range(h):
            for dx in range(w):
                self.tile(x + dx, y + dy)["ground"] = "water"
        return self

    def map(self, path: str = "test.mp2"):
        return load_map({"map": path, "width": self.width, "height": self.height, "tiles": self.tiles})


def whole(scout: Scout) -> Window:
    return Window(0, 0, scout.width, scout.height)


def good_scout(width: int = 14, height: int = 22, seed: int = 0) -> Scout:
    """Dense, varied and animated: every rule passes."""
    rng = random.Random(seed)
    scout = Scout(width, height)
    kinds = [(TREES, TREE_ICN), (MOUNTAINS, MOUNTAIN_ICN), (ROCK, ROCK_ICN)]
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            kind, icn = kinds[(x // 2 + y // 2) % 3]
            scout.add(x, y, kind, icn, sprite=rng.randrange(1000), animated=(x % 6, y % 6) == (0, 0))
    return scout


# Empty space

def fill_except(scout: Scout, holes: list[tuple[int, int, int, int]]) -> Scout:
    """Covers the map with varied 1x1 objects of three types, except inside the (x, y, w, h) holes."""
    kinds = [(TREES, TREE_ICN), (MOUNTAINS, MOUNTAIN_ICN), (ROCK, ROCK_ICN)]
    for y in range(scout.height):
        for x in range(scout.width):
            if not any(hx <= x < hx + hw and hy <= y < hy + hh for hx, hy, hw, hh in holes):
                kind, icn = kinds[(x + y) % 3]
                scout.add(x, y, kind, icn, sprite=y * scout.width + x)
    return scout


def test_largest_empty_square_of_a_blank_map_is_the_short_side():
    scout = Scout(6, 9)
    assert largest_empty_square(scout.map(), whole(scout)) == 6


def test_largest_empty_square_measures_the_hole():
    assert largest_empty_square(good_scout().map(), whole(good_scout())) == 1
    hole = fill_except(Scout(14, 22), [(3, 5, 6, 6)])
    assert largest_empty_square(hole.map(), whole(hole)) == 6
    assert "empty" in check(hole.map(), whole(hole)).failures


def test_a_five_tile_hole_is_allowed():
    # Sheet 2-06 has one and the user found it fine.
    hole = fill_except(Scout(14, 22), [(3, 5, 5, 5)])
    assert largest_empty_square(hole.map(), whole(hole)) == 5
    assert "empty" not in check(hole.map(), whole(hole)).failures


def test_empty_space_at_the_top_counts():
    # The clock covers the top of the view, but the user still called sheet 2-33 "emptyish at top".
    hole = fill_except(Scout(14, 22), [(0, 0, 6, 6)])
    assert "empty" in check(hole.map(), whole(hole)).failures


def test_empty_square_reports_where_the_hole_is():
    hole = fill_except(Scout(8, 8), [(2, 3, 3, 3)])
    assert empty_square(hole.map(), Window(1, 1, 7, 7)) == (3, 1, 2)


def test_tiles_on_a_terrain_border_are_not_empty():
    # Water on the left half, grass on the right: the two columns along the shore don't count as empty.
    scout = Scout(10, 10).water(0, 0, 5, 10)
    assert largest_empty_square(scout.map(), whole(scout)) == 4


def test_open_water_and_shadows_are_empty():
    scout = Scout(6, 6, ground="water")
    for x in range(6):
        scout.shadow(x, 2)
    assert largest_empty_square(scout.map(), whole(scout)) == 6


def test_roads_and_rivers_are_empty_ground():
    # Sheet 2-02 and 2-38 are plain ground crossed by roads and rivers, and read as empty.
    scout = Scout(9, 9)
    for y in range(9):
        scout.terrain(4, y, ROAD_ICN)
    assert largest_empty_square(scout.map(), whole(scout)) == 9


def test_terrain_decorations_are_objects():
    # Cracks, holes and flowers sit on the terrain layer but read as objects (sheet 07's "empty" square had one).
    scout = Scout(9, 9).terrain(4, 4, DIRT_DECOR_ICN)
    m = scout.map()
    assert m.occupied[4, 4]
    assert largest_empty_square(m, whole(scout)) == 4


def test_empty_square_only_counts_inside_the_window():
    scout = fill_except(Scout(10, 10), [(0, 0, 5, 10)])
    m = scout.map()
    assert largest_empty_square(m, Window(0, 0, 10, 10)) == 5
    assert largest_empty_square(m, Window(3, 0, 7, 10)) == 2


# Clumping: objects bunched together with blank patches between them

GRID_OF_HOLES = [(x, y, 4, 4) for x in (0, 5, 10) for y in (0, 5, 10, 15)]


def test_blank_patches_share_counts_tiles_in_blank_two_by_two_patches():
    assert blank_patch_share(good_scout().map(), Window(0, 0, 14, 22)) == 0
    clumped = fill_except(Scout(14, 22), GRID_OF_HOLES)
    assert blank_patch_share(clumped.map(), Window(0, 0, 14, 22)) == 12 * 16 / 308
    # Single blank tiles and 1-tile-wide strips are not patches.
    strips = fill_except(Scout(14, 22), [(x, 0, 1, 22) for x in (1, 4, 7, 10)])
    assert blank_patch_share(strips.map(), whole(strips)) == 0


def test_many_small_blank_patches_are_clumped():
    clumped = fill_except(Scout(14, 22), GRID_OF_HOLES)
    verdict = check(clumped.map(), whole(clumped))
    assert "empty" not in verdict.failures
    assert "clumped" in verdict.failures


def test_a_few_small_blank_patches_are_fine():
    spread = fill_except(Scout(14, 22), GRID_OF_HOLES[:4])
    assert blank_patch_share(spread.map(), whole(spread)) == 64 / 308
    assert "clumped" not in check(spread.map(), whole(spread)).failures


# Sparse views

def test_fewer_than_22_percent_of_tiles_with_objects_is_sparse():
    sparse = Scout(10, 10)
    for i in range(21):
        sparse.add(i % 10, 3 * (i // 10), (TREES, MOUNTAINS, ROCK)[i % 3], TREE_ICN, sprite=i)
    assert occupied_share(sparse.map(), whole(sparse)) == 0.21
    assert "sparse" in check(sparse.map(), whole(sparse)).failures
    sparse.add(5, 9, ROCK, ROCK_ICN, sprite=99)
    assert "sparse" not in check(sparse.map(), whole(sparse)).failures


# Repetition: identical objects in a regular arrangement

@pytest.mark.parametrize("step", [(1, 0), (0, 1), (1, 1), (1, -1)])
def test_three_identical_objects_in_a_line_repeat(step):
    scout = Scout(10, 10)
    for i in range(3):
        scout.add(4 + i * step[0], 4 + i * step[1], sprite=5)
    assert len(regular_patterns(scout.map(), whole(scout))) == 1
    assert "repetition" in check(scout.map(), whole(scout)).failures


def test_a_row_of_identical_mountains_repeats():
    row = Scout(12, 4)
    for x in (0, 3, 6):
        row.add(x, 1, MOUNTAINS, MOUNTAIN_ICN, sprite=2, size=(3, 2))
    assert regular_patterns(row.map(), whole(row))
    varied = Scout(12, 4)
    for x, sprite in ((0, 2), (3, 3), (6, 2)):
        varied.add(x, 1, MOUNTAINS, MOUNTAIN_ICN, sprite=sprite, size=(3, 2))
    assert not regular_patterns(varied.map(), whole(varied))


def test_a_block_of_identical_resource_piles_repeats():
    scout = Scout(6, 6).add(1, 1, sprite=7).add(2, 1, sprite=7).add(1, 2, sprite=7).add(2, 2, sprite=7)
    assert regular_patterns(scout.map(), whole(scout))


def test_a_pair_of_identical_objects_is_allowed():
    scout = Scout(10, 3).add(1, 1, sprite=5).add(2, 1, sprite=5).add(3, 1, sprite=6)
    assert not regular_patterns(scout.map(), whole(scout))


def test_identical_objects_in_an_irregular_cluster_are_allowed():
    # Like sheet 13-16: forests and ranges of one sprite whose outline is not a row or block.
    scout = Scout(6, 6)
    for x, y in ((0, 0), (1, 0), (0, 1), (2, 1), (1, 2)):
        scout.add(x, y, sprite=5)
    assert not regular_patterns(scout.map(), whole(scout))
    zigzag = Scout(6, 6).add(2, 1, sprite=5).add(1, 2, sprite=5).add(2, 3, sprite=5)
    assert not regular_patterns(zigzag.map(), whole(zigzag))


def test_identical_objects_stepping_on_a_slant_are_a_cluster():
    # Sheet 2-22 to 2-24: big trees stepping two right and three down read as a forest, not a row.
    scout = Scout(12, 12)
    for i in range(3):
        scout.add(2 * i, 3 * i, sprite=3, size=(3, 3))
    assert not regular_patterns(scout.map(), whole(scout))


def test_identical_big_objects_on_a_true_diagonal_repeat():
    scout = Scout(12, 12)
    for i in range(3):
        scout.add(3 * i, 3 * i, sprite=3, size=(3, 3))
    assert regular_patterns(scout.map(), whole(scout))


def test_overlapping_identical_objects_blend_rather_than_repeat():
    # Sheet 14: big trees stepping two tiles right and one down overlap into one forest.
    scout = Scout(12, 8)
    for i in range(3):
        scout.add(2 * i, i, sprite=3, size=(3, 3))
    assert not regular_patterns(scout.map(), whole(scout))


def test_identical_objects_with_a_gap_do_not_form_a_row():
    scout = Scout(10, 3).add(0, 1, sprite=5).add(2, 1, sprite=5).add(4, 1, sprite=5)
    assert not regular_patterns(scout.map(), whole(scout))


def test_same_sprites_in_another_icn_are_different_objects():
    scout = Scout(10, 3).add(1, 1, sprite=5).add(2, 1, TREES, ROCK_ICN, sprite=5).add(3, 1, sprite=5)
    assert not regular_patterns(scout.map(), whole(scout))


def test_a_varied_forest_passes():
    scout = Scout(14, 22)
    # Five tree sprites placed so that the same sprite never lands within one tile of itself.
    for y in range(22):
        for x in range(14):
            scout.add(x, y, sprite=(x + 2 * y) % 5)
    assert not regular_patterns(scout.map(), whole(scout))


def test_a_forest_planted_in_a_grid_fails():
    scout = Scout(14, 22)
    for y in range(0, 22, 2):
        for x in range(0, 14, 2):
            scout.add(x, y, sprite=1, size=(2, 2))
    assert "repetition" in check(scout.map(), whole(scout)).failures


def test_repetition_only_counts_objects_in_the_window():
    scout = Scout(10, 3).add(1, 1, sprite=5).add(2, 1, sprite=5).add(3, 1, sprite=5)
    assert not regular_patterns(scout.map(), Window(2, 0, 8, 3))


# Frequency: too many copies of one sprite anywhere in the view

def test_many_copies_of_one_sprite_covering_most_objects_fail():
    # Sheet 2-30: dozens of the same creature and tree.
    scout = Scout(14, 22)
    for i in range(12):
        scout.add(2 * (i % 6), 4 * (i // 6), sprite=1, size=(1, 2))
    scout.add(0, 12, MOUNTAINS, MOUNTAIN_ICN, sprite=2, size=(2, 2)).add(4, 12, ROCK, ROCK_ICN, sprite=3)
    copies, share = top_sprite(scout.map(), whole(scout))
    assert (copies, share) == (12, 24 / 29)
    assert "frequency" in check(scout.map(), whole(scout)).failures


def test_many_copies_among_plenty_of_other_objects_pass():
    # Sheet 2-31: lots of one wreck, but it holds only about half of the objects' area.
    scout = Scout(14, 22)
    for i in range(12):
        scout.add(2 * (i % 6), 4 * (i // 6), sprite=1)
    for i in range(12):
        scout.add(2 * (i % 6), 10 + 4 * (i // 6), ROCK, ROCK_ICN, sprite=100 + i)
    assert top_sprite(scout.map(), whole(scout)) == (12, 0.5)
    assert "frequency" not in check(scout.map(), whole(scout)).failures


def test_a_few_big_copies_are_not_frequent():
    scout = Scout(14, 22)
    for i in range(3):
        scout.add(0, 4 * i, MOUNTAINS, MOUNTAIN_ICN, sprite=2, size=(5, 3))
    scout.add(8, 0, ROCK, ROCK_ICN)
    assert "frequency" not in check(scout.map(), whole(scout)).failures


# Object types

def test_one_object_type_over_65_percent_is_a_monoculture():
    scout = Scout(10, 1)
    for x in range(7):
        scout.add(x, 0, TREES, sprite=x)
    scout.add(7, 0, MOUNTAINS, MOUNTAIN_ICN).add(8, 0, ROCK, ROCK_ICN).add(9, 0, LAKE, ROCK_ICN, sprite=3)
    share, distinct = type_mix(scout.map(), whole(scout))
    assert (share, distinct) == (0.7, 4)
    assert "monoculture" in check(scout.map(), whole(scout)).failures


def test_sixty_percent_is_allowed():
    # Sheet 2-28 at 64% was fine too.
    scout = Scout(10, 1)
    for x in range(6):
        scout.add(x, 0, TREES, sprite=x)
    for x in range(6, 10):
        scout.add(x, 0, (MOUNTAINS, ROCK)[x % 2], ROCK_ICN, sprite=x)
    assert type_mix(scout.map(), whole(scout)) == (0.6, 3)
    assert "monoculture" not in check(scout.map(), whole(scout)).failures


def test_two_object_types_are_too_few():
    scout = Scout(4, 1).add(0, 0, TREES).add(1, 0, MOUNTAINS, MOUNTAIN_ICN).add(2, 0, TREES, sprite=2)
    assert type_mix(scout.map(), whole(scout)) == (2 / 3, 2)
    assert "few types" in check(scout.map(), whole(scout)).failures


def test_action_objects_count_as_their_base_type():
    # MP2 marks the entrance tile of an object with its base type + 128.
    scout = Scout(3, 1).add(0, 0, 23, sprite=1).add(1, 0, 23 + 128, sprite=2).add(2, 0, TREES)
    assert type_mix(scout.map(), whole(scout)) == (2 / 3, 2)


# Animation

def test_one_animated_object_is_not_enough():
    scout = good_scout()
    for tile in scout.tiles:
        for part in tile["parts"]:
            part[4] = 0
    scout.tile(0, 0)["parts"][0][4] = 1
    assert animation(scout.map(), whole(scout)) == (1, 0)
    assert "no animation" in check(scout.map(), whole(scout)).failures


def test_two_animated_objects_or_water_animate():
    scout = good_scout()
    assert animation(scout.map(), whole(scout))[0] >= 2
    assert "no animation" not in check(scout.map(), whole(scout)).failures
    still = Scout(14, 22).water(0, 0, 3, 3)
    assert animation(still.map(), whole(still)) == (0, 9)
    assert "no animation" not in check(still.map(), whole(still)).failures


def test_animated_shadow_parts_count_as_animated_objects():
    scout = Scout(5, 5).shadow(1, 1, animated=True).shadow(3, 3, animated=True)
    assert animation(scout.map(), whole(scout)) == (2, 0)


# Placement

def test_window_must_lie_inside_the_map():
    m = good_scout().map()
    assert Window(0, 0, 14, 22).inside(m)
    assert not Window(1, 0, 14, 22).inside(m)
    assert not Window(0, -1, 14, 22).inside(m)
    assert "off map" in check(m, Window(1, 0, 14, 22)).failures


def test_windows_overlap_when_they_share_a_tile():
    a = Window(0, 0, 14, 22)
    assert a.overlaps(Window(13, 21, 14, 22))
    assert not a.overlaps(Window(14, 0, 14, 22))
    assert not a.overlaps(Window(0, 22, 14, 22))


def test_window_tiles_cover_the_rendered_pixels():
    assert window_tiles(420, 700) == (14, 22)
    assert window_tiles(416, 704) == (13, 22)


def test_a_good_view_passes_every_rule():
    scout = good_scout()
    verdict = check(scout.map(), whole(scout))
    assert verdict.failures == []
    assert verdict.values["empty"] == 1


# Every window at once

def random_scout(seed: int) -> Scout:
    rng = random.Random(seed)
    scout = Scout(30, 34)
    scout.water(0, 0, rng.randrange(1, 10), rng.randrange(1, 10))
    # Density varies with the seed so that the sparse and clumped rules go both ways.
    for _ in range(90 + 40 * (seed % 4)):
        w, h = rng.choice([(1, 1), (1, 1), (2, 1), (2, 2), (3, 2)])
        x, y = rng.randrange(30 - w + 1), rng.randrange(34 - h + 1)
        if any(scout.tile(x + dx, y + dy)["occupied"] for dx in range(w) for dy in range(h)):
            continue
        # Mostly trees, from a pool of 2-4 types, so the type rules pass and fail across the map.
        kind = TREES if rng.random() < 0.6 else rng.choice([MOUNTAINS, ROCK, LAKE][:1 + seed % 3])
        scout.add(x, y, kind, TREE_ICN, sprite=rng.randrange(4), size=(w, h), animated=rng.random() < 0.05)
    road = rng.randrange(30)
    for y in range(34):
        if not scout.tile(road, y)["occupied"]:
            scout.terrain(road, y, ROAD_ICN)
    return scout


@pytest.mark.parametrize("seed", range(6))
def test_passing_windows_agree_with_checking_each_window(seed):
    m = random_scout(seed).map()
    grid = passing_windows(m, 14, 22)
    assert grid["all"].shape == (34 - 22 + 1, 30 - 14 + 1)
    for y in range(grid["all"].shape[0]):
        for x in range(grid["all"].shape[1]):
            failures = check(m, Window(x, y, 14, 22)).failures
            for rule, passes in grid.items():
                if rule != "all":
                    assert passes[y, x] == (rule not in failures), (rule, x, y)
            assert grid["all"][y, x] == (not failures)


def test_maps_smaller_than_the_window_have_no_windows():
    grid = passing_windows(good_scout(10, 10).map(), 14, 22)
    assert grid["all"].size == 0


# Choosing views

def test_select_spreads_views_across_maps():
    maps = [good_scout(14, 22, seed).map(f"m{seed}.mp2") for seed in range(3)]
    views = select_views(maps, 3, 14, 22, random.Random(1))
    assert sorted(v.map for v in views) == ["m0.mp2", "m1.mp2", "m2.mp2"]
    assert all(isinstance(v, View) and (v.x, v.y) == (0, 0) for v in views)


def test_select_takes_several_non_overlapping_views_from_one_map():
    # Room for three windows side by side, so the first pick never blocks the second.
    big = good_scout(42, 66).map()
    views = select_views([big], 2, 14, 22, random.Random(0))
    windows = [Window(v.x, v.y, 14, 22) for v in views]
    assert len(windows) == 2
    assert not any(a.overlaps(b) for i, a in enumerate(windows) for b in windows[i + 1:])


def test_select_skips_excluded_views():
    maps = [good_scout(14, 22, seed).map(f"m{seed}.mp2") for seed in range(2)]
    views = select_views(maps, 1, 14, 22, random.Random(0), exclude=[View("m0.mp2", 0, 0)])
    assert views == [View("m1.mp2", 0, 0)]


def test_select_stops_when_there_are_not_enough_good_views():
    maps = [good_scout().map("good.mp2"), Scout(14, 22).map("empty.mp2")]
    with pytest.raises(NotEnoughViews, match="1 of 2"):
        select_views(maps, 2, 14, 22, random.Random(0))


# Rendered backstop

def test_duplicate_tile_share():
    rng = np.random.default_rng(0)
    noise = rng.integers(0, 256, (64, 96), dtype=np.uint8)
    assert duplicate_tile_share(noise) == 0
    tile = rng.integers(0, 256, (32, 32), dtype=np.uint8)
    assert duplicate_tile_share(np.tile(tile, (2, 3))) == 1
    half = noise.copy()
    half[:32] = np.tile(tile, (1, 3))
    assert duplicate_tile_share(half) == 0.5


def test_duplicate_tile_share_finds_the_grid():
    rng = np.random.default_rng(1)
    tiles = np.tile(rng.integers(0, 256, (32, 32), dtype=np.uint8), (3, 4))
    shifted = rng.integers(0, 256, (96 + 5, 128 + 9), dtype=np.uint8)
    shifted[5:, 9:] = tiles
    assert duplicate_tile_share(shifted) > 0.5

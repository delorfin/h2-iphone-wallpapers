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
    empty_square,
    largest_empty_square,
    largest_repeat_group,
    load_map,
    passing_windows,
    repeat_group,
    select_views,
    type_mix,
    window_tiles,
)

TREES, MOUNTAINS, ROCK, LAKE = 99, 100, 103, 104
TREE_ICN, MOUNTAIN_ICN, ROCK_ICN = 49, 32, 51


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

def test_largest_empty_square_of_a_blank_map_is_the_short_side():
    scout = Scout(6, 9)
    assert largest_empty_square(scout.map(), whole(scout)) == 6


def test_largest_empty_square_measures_the_hole():
    scout = good_scout()
    m = scout.map()
    assert largest_empty_square(m, whole(scout)) == 1
    hole = Scout(14, 22)
    for y in range(22):
        for x in range(14):
            if not (3 <= x < 8 and 5 <= y < 10):
                hole.add(x, y, sprite=x * 100 + y)
    assert largest_empty_square(hole.map(), whole(hole)) == 5
    assert "empty" in check(hole.map(), whole(hole)).failures


def test_a_four_tile_hole_is_allowed():
    hole = Scout(14, 22)
    for y in range(22):
        for x in range(14):
            if not (3 <= x < 7 and 5 <= y < 9):
                hole.add(x, y, sprite=x * 100 + y)
    assert largest_empty_square(hole.map(), whole(hole)) == 4
    assert "empty" not in check(hole.map(), whole(hole)).failures


def test_empty_square_reports_where_the_hole_is():
    hole = Scout(8, 8)
    for y in range(8):
        for x in range(8):
            if not (2 <= x < 5 and 3 <= y < 6):
                hole.add(x, y, sprite=x * 10 + y)
    assert empty_square(hole.map(), Window(1, 1, 7, 7)) == (3, 1, 2)


def test_shadows_and_water_do_not_fill_space():
    scout = Scout(6, 6).water(0, 0, 6, 6)
    for x in range(6):
        scout.shadow(x, 2)
    assert largest_empty_square(scout.map(), whole(scout)) == 6


def test_empty_square_only_counts_inside_the_window():
    scout = Scout(10, 10)
    for y in range(10):
        for x in range(5, 10):
            scout.add(x, y, sprite=x * 10 + y)
    m = scout.map()
    assert largest_empty_square(m, Window(0, 0, 10, 10)) == 5
    assert largest_empty_square(m, Window(3, 0, 7, 10)) == 2


# Repetition

def test_three_identical_objects_in_a_row_repeat():
    scout = Scout(10, 3).add(1, 1, sprite=5).add(2, 1, sprite=5).add(3, 1, sprite=5)
    assert largest_repeat_group(scout.map(), whole(scout)) == 3
    assert "repetition" in check(scout.map(), whole(scout)).failures


def test_repeat_group_lists_the_linked_objects():
    m = Scout(10, 3).add(1, 1, sprite=5).add(2, 1, sprite=5).add(3, 1, sprite=5).add(6, 1, sprite=5).map()
    group = repeat_group(m, Window(0, 0, 10, 3))
    assert sorted(int(m.x0[i]) for i in group) == [1, 2, 3]


def test_a_pair_of_identical_objects_is_allowed():
    scout = Scout(10, 3).add(1, 1, sprite=5).add(2, 1, sprite=5).add(3, 1, sprite=6)
    assert largest_repeat_group(scout.map(), whole(scout)) == 2


def test_diagonal_neighbours_link():
    scout = Scout(10, 4).add(1, 0, sprite=5).add(2, 1, sprite=5).add(3, 2, sprite=5)
    assert largest_repeat_group(scout.map(), whole(scout)) == 3


def test_identical_objects_with_a_gap_do_not_link():
    # The user chose adjacency only: a one-tile gap separates objects.
    scout = Scout(10, 3).add(0, 1, sprite=5).add(2, 1, sprite=5).add(4, 1, sprite=5)
    assert largest_repeat_group(scout.map(), whole(scout)) == 1


def test_multi_tile_objects_repeat_as_whole_objects():
    row = Scout(12, 4)
    for x in (0, 3, 6):
        row.add(x, 1, MOUNTAINS, MOUNTAIN_ICN, sprite=2, size=(3, 2))
    assert largest_repeat_group(row.map(), whole(row)) == 3
    varied = Scout(12, 4)
    for x, sprite in ((0, 2), (3, 3), (6, 2)):
        varied.add(x, 1, MOUNTAINS, MOUNTAIN_ICN, sprite=sprite, size=(3, 2))
    assert largest_repeat_group(varied.map(), whole(varied)) == 1


def test_same_sprites_in_another_icn_are_different_objects():
    scout = Scout(10, 3).add(1, 1, sprite=5).add(2, 1, TREES, ROCK_ICN, sprite=5).add(3, 1, sprite=5)
    assert largest_repeat_group(scout.map(), whole(scout)) == 1


def test_a_varied_forest_passes():
    scout = Scout(14, 22)
    # Five tree sprites placed so that the same sprite never lands within one tile of itself.
    for y in range(22):
        for x in range(14):
            scout.add(x, y, sprite=(x + 2 * y) % 5)
    assert largest_repeat_group(scout.map(), whole(scout)) == 1


def test_a_forest_of_one_tree_fails():
    scout = Scout(14, 22)
    for y in range(0, 22, 2):
        for x in range(0, 14, 2):
            scout.add(x, y, sprite=1, size=(2, 2))
    assert largest_repeat_group(scout.map(), whole(scout)) > 2


def test_repetition_only_counts_objects_in_the_window():
    scout = Scout(10, 3).add(1, 1, sprite=5).add(2, 1, sprite=5).add(3, 1, sprite=5)
    assert largest_repeat_group(scout.map(), Window(2, 0, 8, 3)) == 2


# Object types

def test_one_object_type_over_sixty_percent_is_a_monoculture():
    scout = Scout(10, 1)
    for x in range(7):
        scout.add(x, 0, TREES, sprite=x)
    scout.add(7, 0, MOUNTAINS, MOUNTAIN_ICN).add(8, 0, ROCK, ROCK_ICN).add(9, 0, LAKE, ROCK_ICN, sprite=3)
    share, distinct = type_mix(scout.map(), whole(scout))
    assert (share, distinct) == (0.7, 4)
    assert "monoculture" in check(scout.map(), whole(scout)).failures


def test_sixty_percent_is_allowed():
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
    for _ in range(170):
        w, h = rng.choice([(1, 1), (1, 1), (2, 1), (2, 2), (3, 2)])
        x, y = rng.randrange(30 - w + 1), rng.randrange(34 - h + 1)
        if any(scout.tile(x + dx, y + dy)["occupied"] for dx in range(w) for dy in range(h)):
            continue
        # Mostly trees, from a pool of 2-4 types, so the type rules pass and fail across the map.
        kind = TREES if rng.random() < 0.6 else rng.choice([MOUNTAINS, ROCK, LAKE][:1 + seed % 3])
        scout.add(x, y, kind, TREE_ICN, sprite=rng.randrange(4), size=(w, h), animated=rng.random() < 0.05)
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

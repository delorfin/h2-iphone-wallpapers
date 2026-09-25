"""Engine modes that feed view selection: --scout-maps and --render-views. Needs the built renderer."""

import json
import os
import struct
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RENDERER = REPO / "fheroes2"
GAME_DATA = Path.home() / "Library/Application Support/fheroes2"
MAP = GAME_DATA / "maps" / "Abyss.MP2"
TILE = 32

pytestmark = pytest.mark.skipif(not RENDERER.exists() or not MAP.exists(),
                                reason="build the renderer first: ios-livephoto/build.sh")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(RENDERER), *args], capture_output=True, text=True, timeout=300,
        env={**os.environ, "FHEROES2_DATA": str(GAME_DATA)},
    )


def scout(out: Path) -> dict:
    result = run("--scout-maps", str(out), str(MAP))
    assert result.returncode == 0, result.stderr
    files = list(out.glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text())


def bmp_rows(path: Path) -> tuple[int, int, list[bytes]]:
    """Top-down rows of palette indices of an 8-bit BMP."""
    data = path.read_bytes()
    offset = struct.unpack("<I", data[10:14])[0]
    width, height = struct.unpack("<ii", data[18:26])
    stride = (width + 3) // 4 * 4
    rows = [data[offset + r * stride: offset + r * stride + width] for r in range(abs(height))]
    return width, abs(height), rows if height < 0 else rows[::-1]


@pytest.fixture(scope="module")
def scouted(tmp_path_factory) -> dict:
    return scout(tmp_path_factory.mktemp("scout"))


def test_scout_describes_every_tile(scouted):
    assert Path(scouted["map"]).name == MAP.name
    assert len(scouted["tiles"]) == scouted["width"] * scouted["height"]
    occupied = [t for t in scouted["tiles"] if t["occupied"]]
    assert 0 < len(occupied) < len(scouted["tiles"])
    for tile in occupied[:50]:
        assert any(part[3] in (0, 1) for part in tile["parts"])  # object or background layer


def test_scout_names_the_object_type_of_parts(scouted):
    trees = 99  # MP2::OBJ_TREES
    assert any(part[5] == trees for tile in scouted["tiles"] for part in tile["parts"])


def test_scout_groups_multi_tile_objects_by_uid(scouted):
    tiles_per_uid = {}
    for tile in scouted["tiles"]:
        for uid, *_ in tile["parts"]:
            tiles_per_uid[uid] = tiles_per_uid.get(uid, 0) + 1
    assert max(tiles_per_uid.values()) > 1


def test_scout_marks_animated_parts_and_water(scouted):
    assert any(part[4] for tile in scouted["tiles"] for part in tile["parts"])
    assert any(tile["ground"] == "water" for tile in scouted["tiles"])


def test_scout_is_deterministic(scouted, tmp_path):
    # Random resources and monsters must come out the same when the view is rendered later.
    assert scout(tmp_path) == scouted


def render_views(tmp_path: Path, views: list[tuple[int, int]], width=420, height=700, frames=2) -> subprocess.CompletedProcess:
    spec = tmp_path / "views.txt"
    spec.write_text("".join(f"{x} {y} {MAP}\n" for x, y in views))
    return run("--render-views", str(spec), str(tmp_path / "out"), str(width), str(height), str(frames))


def test_render_views_writes_the_wallpaper_layout(tmp_path):
    result = render_views(tmp_path, [(0, 0), (5, 7)])
    assert result.returncode == 0, result.stderr
    views = sorted((tmp_path / "out").iterdir())
    assert [v.name for v in views] == ["000", "001"]
    for view in views:
        assert sorted(f.name for f in view.glob("f*.bmp")) == ["f00.bmp", "f01.bmp"]
        assert bmp_rows(view / "f00.bmp")[:2] == (420, 700)
        assert Path((view / "map.txt").read_text().strip()).name == MAP.name
    assert (views[1] / "view.txt").read_text().split() == ["5", "7"]


def test_render_views_puts_the_tile_at_the_top_left(tmp_path):
    # Separate runs, so animated objects are at the same step in every picture.
    pictures = []
    for x, y in [(4, 6), (5, 6), (4, 7)]:
        (tmp_path / f"{x}_{y}").mkdir()
        assert render_views(tmp_path / f"{x}_{y}", [(x, y)], frames=1).returncode == 0
        pictures.append(bmp_rows(tmp_path / f"{x}_{y}/out/000/f00.bmp")[2])
    base, right, down = pictures
    # One tile to the right shifts the picture left by one tile; one down shifts it up.
    assert all(right[r][:300] == base[r][TILE:TILE + 300] for r in range(700))
    assert all(down[r] == base[r + TILE] for r in range(600))


def test_render_views_is_deterministic(tmp_path):
    for run_dir in ("a", "b"):
        (tmp_path / run_dir).mkdir()
        assert render_views(tmp_path / run_dir, [(3, 3)], frames=1).returncode == 0
    assert (tmp_path / "a/out/000/f00.bmp").read_bytes() == (tmp_path / "b/out/000/f00.bmp").read_bytes()


def test_render_views_rejects_views_off_the_map(scouted, tmp_path):
    # 420x700 needs 14x22 tiles; one more column than the map has must fail.
    assert render_views(tmp_path, [(scouted["width"] - 13, 0)], frames=1).returncode != 0
    assert render_views(tmp_path, [(-1, 0)], frames=1).returncode != 0


def test_render_wallpapers_still_works(tmp_path):
    result = run("--render-wallpapers", str(tmp_path), "1", "420", "700", "1")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "000" / "f00.bmp").exists()


# Has random-race castles and random artifacts/resources, which the tests above' map lacks.
RANDOM_MAP = GAME_DATA / "maps" / "BELTWAY.MP2"


def scout_one(out: Path, map_file: Path) -> dict:
    result = run("--scout-maps", str(out), str(map_file))
    assert result.returncode == 0, result.stderr
    return json.loads(next(out.glob("*.json")).read_text())


def test_scouting_random_castles_is_repeatable(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    assert scout_one(tmp_path / "a", RANDOM_MAP) == scout_one(tmp_path / "b", RANDOM_MAP)


def test_scouted_map_does_not_depend_on_other_maps_in_the_batch(tmp_path):
    from h2live.select import scout_maps
    alone = scout_maps(RENDERER, GAME_DATA, tmp_path / "alone", maps=[RANDOM_MAP])
    together = scout_maps(RENDERER, GAME_DATA, tmp_path / "together", maps=[MAP, RANDOM_MAP])
    a, b = (next(m for m in scouted if Path(m.path).name == RANDOM_MAP.name) for scouted in (alone, together))
    for field in ("occupied", "ground", "kind", "signature", "x0", "y0", "animated"):
        assert (getattr(a, field) == getattr(b, field)).all(), field


def test_rendered_view_does_not_depend_on_other_views_in_the_batch(tmp_path):
    from h2live.batch import render_views
    from h2live.select import View
    view = View(map=str(RANDOM_MAP), x=25, y=10)
    render_views(RENDERER, [view], tmp_path / "alone", 420, 700, 1)
    render_views(RENDERER, [View(map=str(MAP), x=3, y=3), View(map=str(MAP), x=5, y=7), view], tmp_path / "together", 420, 700, 1)
    assert (tmp_path / "alone/000/f00.bmp").read_bytes() == (tmp_path / "together/002/f00.bmp").read_bytes()

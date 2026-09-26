import os
import struct
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RENDERER = REPO / "engine" / "fheroes2"
# Non-bundle macOS builds only look in ~/.fheroes2 unless told otherwise.
GAME_DATA = Path.home() / "Library/Application Support/fheroes2"
# HoMM2 animates water by rotating these palette entries rather than swapping sprites.
WATER = range(231, 236)

pytestmark = pytest.mark.skipif(not RENDERER.exists(), reason="build the renderer first: ./build.sh")


def bmp_size(path: Path) -> tuple[int, int]:
    width, height = struct.unpack("<ii", path.read_bytes()[18:26])
    return width, abs(height)


def bmp_indices(path: Path) -> bytes:
    """Palette indices of an 8-bit BMP (row order doesn't matter for comparing frames)."""
    data = path.read_bytes()
    return data[struct.unpack("<I", data[10:14])[0]:]


def render(out: Path, count: int, width: int, height: int, frames: int = 8) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(RENDERER), "--render-wallpapers", str(out), str(count), str(width), str(height), str(frames)],
        capture_output=True, text=True, timeout=600,
        env={**os.environ, "FHEROES2_DATA": str(GAME_DATA)},
    )


def test_renders_count_views_of_frames_each(tmp_path):
    result = render(tmp_path, 2, 420, 700)
    assert result.returncode == 0, result.stderr
    views = sorted(p for p in tmp_path.iterdir() if p.is_dir())
    assert [v.name for v in views] == ["000", "001"]
    for view in views:
        frames = sorted(view.glob("f*.bmp"))
        assert len(frames) == 8
        assert {bmp_size(f) for f in frames} == {(420, 700)}
        assert len({f.read_bytes() for f in frames}) > 1, f"{view} has no animation"
        assert (view / "map.txt").read_text().strip()


def test_water_shimmers_between_frames(tmp_path):
    assert render(tmp_path, 4, 420, 700, frames=2).returncode == 0
    shimmering = []
    for view in sorted(p for p in tmp_path.iterdir() if p.is_dir()):
        first, second = bmp_indices(view / "f00.bmp"), bmp_indices(view / "f01.bmp")
        water = [i for i, index in enumerate(first) if index in WATER]
        if len(water) > 1000:
            shimmering.append(sum(first[i] != second[i] for i in water) / len(water))
    assert shimmering, "none of the 4 random views had water; rerun"
    assert min(shimmering) > 0.5


def test_two_runs_pick_different_maps(tmp_path):
    maps = []
    for run in ("a", "b"):
        assert render(tmp_path / run, 3, 420, 700, frames=1).returncode == 0
        maps.append(sorted((tmp_path / run / d / "map.txt").read_text() for d in ("000", "001", "002")))
    assert maps[0] != maps[1]


def test_views_larger_than_small_maps_still_render(tmp_path):
    # 1600 px is 50 tiles: wider than 36x36 and 72x72 maps, so the renderer must pick bigger ones.
    result = render(tmp_path, 2, 1600, 1600, frames=1)
    assert result.returncode == 0, result.stderr
    assert {bmp_size(v / "f00.bmp") for v in tmp_path.iterdir()} == {(1600, 1600)}


@pytest.mark.parametrize("width, height", [(0, 700), (420, 0), (5000, 700)])
def test_rejects_view_sizes_out_of_range(tmp_path, width, height):
    assert render(tmp_path / "out", 1, width, height).returncode != 0
    assert not (tmp_path / "out").exists()


def test_renderer_is_built_without_developer_assertions():
    # Some shipped maps trip loader assertions (e.g. extra bytes at the end of "Easy Walk.mp2")
    # that release builds skip; with them compiled in, a batch aborts at random.
    assert b"fs.tell() + 4 == fs.size()" not in RENDERER.read_bytes()

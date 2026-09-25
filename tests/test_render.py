import os
import struct
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RENDERER = REPO / "fheroes2"
# Non-bundle macOS builds only look in ~/.fheroes2 unless told otherwise.
GAME_DATA = Path.home() / "Library/Application Support/fheroes2"

pytestmark = pytest.mark.skipif(not RENDERER.exists(), reason="build the renderer first: ios-livephoto/build.sh")


def bmp_size(path: Path) -> tuple[int, int]:
    width, height = struct.unpack("<ii", path.read_bytes()[18:26])
    return width, abs(height)


def render(out: Path, count: int, scale: int, frames: int = 8) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(RENDERER), "--render-wallpapers", str(out), str(count), str(scale), str(frames)],
        capture_output=True, text=True, timeout=600,
        env={**os.environ, "FHEROES2_DATA": str(GAME_DATA)},
    )


def test_renders_count_views_of_frames_each(tmp_path):
    result = render(tmp_path, 2, 3)
    assert result.returncode == 0, result.stderr
    views = sorted(p for p in tmp_path.iterdir() if p.is_dir())
    assert [v.name for v in views] == ["000", "001"]
    for view in views:
        frames = sorted(view.glob("f*.bmp"))
        assert len(frames) == 8
        assert {bmp_size(f) for f in frames} == {(360, 640)}
        assert len({f.read_bytes() for f in frames}) > 1, f"{view} has no animation"
        assert (view / "map.txt").read_text().strip()


def test_two_runs_pick_different_maps(tmp_path):
    maps = []
    for run in ("a", "b"):
        assert render(tmp_path / run, 3, 3, frames=1).returncode == 0
        maps.append(sorted((tmp_path / run / d / "map.txt").read_text() for d in ("000", "001", "002")))
    assert maps[0] != maps[1]


@pytest.mark.parametrize("scale", [1, 5])
def test_rejects_scale_outside_2_to_4(tmp_path, scale):
    assert render(tmp_path / "out", 1, scale).returncode != 0
    assert not (tmp_path / "out").exists()


def test_renderer_is_built_without_developer_assertions():
    # Some shipped maps trip loader assertions (e.g. extra bytes at the end of "Easy Walk.mp2")
    # that release builds skip; with them compiled in, a batch aborts at random.
    assert b"fs.tell() + 4 == fs.size()" not in RENDERER.read_bytes()

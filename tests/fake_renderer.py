"""Stands in for fheroes2's --scout-maps and --render-views so batch tests don't need game data.

Scouts one map per call, like the batch asks: a.mp2, b.mp2 and dull.mp2 are small maps with one good
view each; empty.mp2 has nothing on it; broken.mp2 can't be read, the way the engine reports a bad map;
crash.mp2 fails for another reason, like missing game data. Views of "dull.mp2" render as one flat
colour. FAKE_SCOUT_LOG, if set, collects the name of every map scouted.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

TREES, MOUNTAINS, ROCK = 99, 100, 103


def good_map(name: str, seed: int) -> dict:
    width, height = 14, 22
    tiles = [{"ground": "grass", "object": 0, "occupied": False, "parts": []} for _ in range(width * height)]
    uid = 1
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            kind = (TREES, MOUNTAINS, ROCK)[(x // 2 + y // 2) % 3]
            tile = tiles[y * width + x]
            tile.update(object=kind, occupied=True)
            tile["parts"].append([uid, 49, (uid * 7 + seed) % 256, 0, int(x == y), kind])
            uid += 1
    return {"map": name, "width": width, "height": height, "tiles": tiles}


def scout(out: Path, map_file: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    name = Path(map_file).name
    if os.environ.get("FAKE_SCOUT_LOG"):
        with open(os.environ["FAKE_SCOUT_LOG"], "a") as log:
            log.write(name + "\n")
    if name == "broken.mp2":
        sys.exit(f"[ERROR]\tScoutMaps:  Could not read map {map_file}")
    if name == "crash.mp2":
        sys.exit("[ERROR]\tmain:  Exception 'No AGG data files found.' occurred during application runtime.")
    if name == "empty.mp2":
        maps = [{"map": "empty.mp2", "width": 14, "height": 22,
                 "tiles": [{"ground": "grass", "object": 0, "occupied": False, "parts": []}] * (14 * 22)}]
    else:
        maps = [good_map(name, ["a.mp2", "b.mp2", "dull.mp2"].index(name))]
    for m in maps:
        (out / f"{m['map']}.json").write_text(json.dumps(m))


def render(view: Path, width: str, height: str, frames: str, source: str) -> None:
    view.mkdir(parents=True)
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"{source}:s={width}x{height}:r=40", "-frames:v", frames,
         "-pix_fmt", "pal8", "-start_number", "0", str(view / "f%02d.bmp")],
        check=True,
    )


flag = sys.argv[1]
if flag == "--scout-maps":
    scout(Path(sys.argv[2]), sys.argv[3])
elif flag == "--render-views":
    _, _, views, out, width, height, frames = sys.argv
    for i, line in enumerate(Path(views).read_text().splitlines()):
        x, y, name = line.split(" ", 2)
        view = Path(out) / f"{i:03d}"
        render(view, width, height, frames, "color=c=green" if name == "dull.mp2" else "mandelbrot=start_scale=3")
        (view / "map.txt").write_text(f"{name}\n")
        (view / "view.txt").write_text(f"{x} {y}\n")
else:
    sys.exit(f"unexpected arguments {sys.argv[1:]}")

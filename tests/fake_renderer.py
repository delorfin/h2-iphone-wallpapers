"""Stands in for `fheroes2 --render-wallpapers` so batch tests don't need game data."""

import subprocess
import sys
from pathlib import Path

_, flag, out, count, width, height, frames = sys.argv
assert flag == "--render-wallpapers"
for i in range(int(count)):
    view = Path(out) / f"{i:03d}"
    view.mkdir(parents=True)
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={width}x{height}:r=40", "-frames:v", frames,
         "-start_number", "0", str(view / "f%02d.bmp")],
        check=True,
    )
    (view / "map.txt").write_text("fake.mp2\n")

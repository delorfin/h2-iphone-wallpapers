"""Stands in for `fheroes2 --render-wallpapers` so batch tests don't need game data."""

import subprocess
import sys
from pathlib import Path

_, flag, out, count, scale, frames = sys.argv
assert flag == "--render-wallpapers"
size = f"{1080 // int(scale)}x{1920 // int(scale)}"
for i in range(int(count)):
    view = Path(out) / f"{i:03d}"
    view.mkdir(parents=True)
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=8", "-frames:v", frames,
         "-start_number", "0", str(view / "f%02d.bmp")],
        check=True,
    )
    (view / "map.txt").write_text("fake.mp2\n")

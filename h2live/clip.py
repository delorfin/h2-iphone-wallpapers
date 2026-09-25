"""Turns one rendered map view into the 1-second clip a Live Photo wallpaper plays."""

import subprocess
from pathlib import Path

# iOS rejects Live Photo wallpapers in any other size.
WIDTH, HEIGHT = 1080, 1920
OUTPUT_FPS = 60


def make_clip(frames_dir: Path, out: Path, brightness: int, steps_per_second: int = 8) -> None:
    if not 1 <= brightness <= 100:
        raise ValueError(f"brightness must be 1-100, got {brightness}")
    frames = sorted(frames_dir.glob("f*.bmp"))
    if len(frames) != steps_per_second:
        raise ValueError(f"expected {steps_per_second} frames in {frames_dir}, found {len(frames)}")

    level = brightness / 100
    # Nearest-neighbour keeps the pixel art sharp; every renderer size divides 1080x1920 exactly.
    video_filter = (
        f"scale={WIDTH}:{HEIGHT}:flags=neighbor,"
        f"colorchannelmixer=rr={level}:gg={level}:bb={level},"
        "format=yuv420p"
    )
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-framerate", str(steps_per_second), "-i", str(frames_dir / "f%02d.bmp"),
         "-vf", video_filter, "-r", str(OUTPUT_FPS), "-frames:v", str(OUTPUT_FPS),
         "-c:v", "libx265", "-crf", "20", "-tag:v", "hvc1", "-x265-params", "log-level=error",
         str(out)],
        check=True,
    )

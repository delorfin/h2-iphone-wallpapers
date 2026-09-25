import json
import subprocess
from pathlib import Path

import pytest


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def mean_luma(path: Path) -> float:
    gray = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True, capture_output=True,
    ).stdout
    return sum(gray) / len(gray)


def gray_frame(path: Path, index: int) -> tuple[int, int, bytes]:
    """Width, height and 8-bit gray pixels of video frame `index` (first video track)."""
    info = probe(path)["streams"][0]
    width, height = info["width"], info["height"]
    gray = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-map", "0:v:0", "-vf", f"select=eq(n\\,{index})",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True, capture_output=True,
    ).stdout
    return width, height, gray


def write_frames(view: Path, source: str) -> Path:
    """Eight game poses at 420x700, shaped like one renderer view at scale 3 with the pan margin."""
    view.mkdir()
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", source, "-frames:v", "8",
         "-start_number", "0", str(view / "f%02d.bmp")],
        check=True,
    )
    return view


@pytest.fixture
def frames_dir(tmp_path: Path) -> Path:
    return write_frames(tmp_path / "000", "testsrc2=s=420x700:r=8")


@pytest.fixture
def still_frames_dir(tmp_path: Path) -> Path:
    """A view whose content never changes, so any movement in the clip is the pan."""
    return write_frames(tmp_path / "still", "testsrc2=s=420x700:r=8,loop=loop=-1:size=1")

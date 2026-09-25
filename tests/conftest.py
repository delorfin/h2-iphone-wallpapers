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


@pytest.fixture
def frames_dir(tmp_path: Path) -> Path:
    """Eight 360x640 frames shaped like one renderer view (scale 3)."""
    view = tmp_path / "000"
    view.mkdir()
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=8", "-frames:v", "8",
         "-start_number", "0", str(view / "f%02d.bmp")],
        check=True,
    )
    return view

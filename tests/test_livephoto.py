import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from conftest import probe
from h2live.clip import make_clip
from h2live.livephoto import make_live_photo


def tags(path: Path) -> dict:
    # QuickTimeUTC shows video dates in local time, as Photos does; they are stored in UTC.
    out = subprocess.run(
        ["exiftool", "-json", "-G", "-ee3", "-api", "QuickTimeUTC", str(path)], check=True, capture_output=True, text=True
    ).stdout
    return json.loads(out)[0]


@pytest.fixture
def pair(frames_dir, tmp_path):
    clip = tmp_path / "clip.mov"
    make_clip(frames_dir, clip, brightness=70)
    out = tmp_path / "live"
    out.mkdir()
    return make_live_photo(clip, out, "H2_000", datetime(1996, 1, 1, 0, 5))


def test_files_are_named_after_the_item(pair):
    heic, mov = pair
    assert (heic.name, mov.name) == ("H2_000.HEIC", "H2_000.mov")


def test_still_and_video_share_one_content_identifier(pair):
    heic, mov = pair
    assert tags(heic)["MakerNotes:ContentIdentifier"] == tags(mov)["QuickTime:ContentIdentifier"]


def test_track_layout_matches_the_proven_golive_output(pair):
    _, mov = pair
    streams = probe(mov)["streams"]
    assert [s["codec_type"] for s in streams] == ["video", "video", "data", "data"]
    clip_track = streams[0]
    assert (clip_track["width"], clip_track["height"]) == (1080, 1920)
    assert clip_track["codec_tag_string"] == "hvc1"
    assert 0.95 <= float(clip_track["duration"]) <= 1.1


def test_still_is_1080x1920(pair):
    heic, _ = pair
    t = tags(heic)
    assert (t["File:ImageWidth"], t["File:ImageHeight"]) == (1080, 1920)


def test_capture_date_is_the_requested_one(pair):
    heic, mov = pair
    assert tags(heic)["EXIF:DateTimeOriginal"] == "1996:01:01 00:05:00"
    assert tags(mov)["QuickTime:CreateDate"].startswith("1996:01:01")


def test_no_location_is_written(pair):
    for path in pair:
        assert not [k for k in tags(path) if "GPS" in k or "Location" in k], path

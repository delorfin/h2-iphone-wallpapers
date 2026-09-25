import pytest

from conftest import mean_luma, probe
from h2live.clip import make_clip


def test_clip_is_one_second_1080x1920_hevc_at_60fps(frames_dir, tmp_path):
    out = tmp_path / "clip.mov"
    make_clip(frames_dir, out, brightness=70)
    video = probe(out)["streams"][0]
    assert (video["width"], video["height"]) == (1080, 1920)
    assert video["codec_tag_string"] == "hvc1"
    assert video["r_frame_rate"] == "60/1"
    assert int(video["nb_frames"]) == 60


def test_brightness_dims_the_picture(frames_dir, tmp_path):
    make_clip(frames_dir, tmp_path / "full.mov", brightness=100)
    make_clip(frames_dir, tmp_path / "half.mov", brightness=50)
    ratio = mean_luma(tmp_path / "half.mov") / mean_luma(tmp_path / "full.mov")
    # Video luma has a black-level offset, so 50% brightness lands near, not exactly at, half.
    assert 0.35 < ratio < 0.65


def test_rejects_wrong_frame_count(frames_dir, tmp_path):
    (frames_dir / "f07.bmp").unlink()
    with pytest.raises(ValueError, match="expected 8 frames"):
        make_clip(frames_dir, tmp_path / "clip.mov", brightness=70)


@pytest.mark.parametrize("brightness", [0, 101])
def test_rejects_brightness_out_of_range(frames_dir, tmp_path, brightness):
    with pytest.raises(ValueError, match="brightness"):
        make_clip(frames_dir, tmp_path / "clip.mov", brightness=brightness)

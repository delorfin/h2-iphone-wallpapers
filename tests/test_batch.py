import sys
from pathlib import Path

from h2live.batch import main

FAKE = Path(__file__).with_name("fake_renderer.py")


def fake_renderer(tmp_path: Path) -> str:
    wrapper = tmp_path / "renderer"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
    wrapper.chmod(0o755)
    return str(wrapper)


def test_builds_one_pair_per_view_without_importing(tmp_path):
    out = tmp_path / "batch"
    code = main(["--out", str(out), "--count", "2", "--no-import", "--renderer", fake_renderer(tmp_path)])
    assert code == 0
    assert sorted(p.name for p in (out / "live").iterdir()) == ["H2_000.HEIC", "H2_000.mov", "H2_001.HEIC", "H2_001.mov"]


def test_refuses_non_empty_output_dir(tmp_path):
    out = tmp_path / "batch"
    out.mkdir()
    (out / "old.txt").write_text("previous batch")
    assert main(["--out", str(out), "--count", "1", "--no-import", "--renderer", fake_renderer(tmp_path)]) != 0
    assert sorted(p.name for p in out.iterdir()) == ["old.txt"]


def test_renderer_failure_stops_the_batch(tmp_path):
    failing = tmp_path / "renderer"
    failing.write_text("#!/bin/sh\nexit 3\n")
    failing.chmod(0o755)
    assert main(["--out", str(tmp_path / "batch"), "--count", "1", "--no-import", "--renderer", str(failing)]) != 0


def fake_renderer_with(tmp_path: Path, maps: str) -> str:
    wrapper = tmp_path / "renderer"
    wrapper.write_text(f"#!/bin/sh\nFAKE_MAPS={maps} exec {sys.executable} {FAKE} \"$@\"\n")
    wrapper.chmod(0o755)
    return str(wrapper)


def run(tmp_path: Path, count: int, maps: str = "good") -> int:
    return main(["--out", str(tmp_path / "batch"), "--count", str(count), "--no-import",
                 "--renderer", fake_renderer_with(tmp_path, maps), "--scout-cache", str(tmp_path / "cache")])


def test_renders_every_view_that_passes_the_map_rules(tmp_path):
    # dull.mp2 renders flat; the user dropped the image check because it rejected views they liked.
    assert run(tmp_path, 3) == 0
    frames = tmp_path / "batch/frames"
    assert sorted((d / "map.txt").read_text().strip() for d in frames.iterdir()) == ["a.mp2", "b.mp2", "dull.mp2"]
    assert all((d / "view.txt").read_text().split() == ["0", "0"] for d in frames.iterdir())


def test_stops_with_a_message_when_too_few_views_pass(tmp_path, capsys):
    assert run(tmp_path, 4) != 0
    assert "3 of 4" in capsys.readouterr().err
    assert not (tmp_path / "batch/live").exists()


def test_stops_when_no_map_has_a_good_view(tmp_path, capsys):
    assert run(tmp_path, 1, maps="empty") != 0
    assert "0 of 1" in capsys.readouterr().err


def test_scouting_is_cached_per_renderer_build(tmp_path):
    assert run(tmp_path, 1) == 0
    assert len(list((tmp_path / "cache").glob("*.pickle"))) == 1


def test_default_scout_cache_follows_the_environment(tmp_path, scout_cache):
    out = tmp_path / "batch"
    assert main(["--out", str(out), "--count", "1", "--no-import", "--renderer", fake_renderer(tmp_path)]) == 0
    assert len(list(scout_cache.glob("*.pickle"))) == 1

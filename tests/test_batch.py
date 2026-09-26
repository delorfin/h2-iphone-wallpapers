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
    code = main(["--out", str(out), "--count", "2", "--no-import", "--renderer", fake_renderer(tmp_path),
                 "--game-data", str(fake_game_data(tmp_path, "good"))])
    assert code == 0
    assert sorted(p.name for p in (out / "live").iterdir()) == ["H2_000.HEIC", "H2_000.mov", "H2_001.HEIC", "H2_001.mov"]


def test_refuses_non_empty_output_dir(tmp_path):
    out = tmp_path / "batch"
    out.mkdir()
    (out / "old.txt").write_text("previous batch")
    assert main(["--out", str(out), "--count", "1", "--no-import", "--renderer", fake_renderer(tmp_path),
                 "--game-data", str(fake_game_data(tmp_path, "good"))]) != 0
    assert sorted(p.name for p in out.iterdir()) == ["old.txt"]


def test_renderer_failure_stops_the_batch(tmp_path):
    failing = tmp_path / "renderer"
    failing.write_text("#!/bin/sh\nexit 3\n")
    failing.chmod(0o755)
    assert main(["--out", str(tmp_path / "batch"), "--count", "1", "--no-import", "--renderer", str(failing),
                 "--game-data", str(fake_game_data(tmp_path, "good"))]) != 0


def fake_game_data(tmp_path: Path, maps: str) -> Path:
    folder = tmp_path / "game-data"
    (folder / "maps").mkdir(parents=True, exist_ok=True)
    for name in (["empty.mp2"] if maps == "empty" else ["a.mp2", "b.mp2", "dull.mp2"]):
        (folder / "maps" / name).write_text("fake")
    return folder


def run(tmp_path: Path, count: int, maps: str = "good") -> int:
    return main(["--out", str(tmp_path / "batch"), "--count", str(count), "--no-import",
                 "--renderer", fake_renderer(tmp_path), "--scout-cache", str(tmp_path / "cache"),
                 "--game-data", str(fake_game_data(tmp_path, maps))])


def test_renders_every_view_that_passes_the_map_rules(tmp_path):
    # dull.mp2 renders flat; the user dropped the image check because it rejected views they liked.
    assert run(tmp_path, 3) == 0
    views = (tmp_path / "batch/views.txt").read_text().splitlines()
    assert sorted(Path(line.split(" ", 2)[2]).name for line in views) == ["a.mp2", "b.mp2", "dull.mp2"]
    assert all(line.split()[:2] == ["0", "0"] for line in views)


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
    assert main(["--out", str(out), "--count", "1", "--no-import", "--renderer", fake_renderer(tmp_path),
                 "--game-data", str(fake_game_data(tmp_path, "good"))]) == 0
    assert len(list(scout_cache.glob("*.pickle"))) == 1


def test_without_import_only_the_finished_live_photos_and_view_list_stay(tmp_path):
    assert run(tmp_path, 2) == 0
    assert sorted(p.name for p in (tmp_path / "batch").iterdir()) == ["live", "views.txt"]


def test_after_import_only_the_view_list_stays(tmp_path, monkeypatch):
    # Photos keeps its own copy of every imported file, so the rendered stages are no longer needed.
    import h2live.batch as batch
    imported = []
    monkeypatch.setattr(batch, "import_pairs", lambda pairs, album: imported.extend(pairs) or len(pairs))
    code = main(["--out", str(tmp_path / "batch"), "--count", "2", "--renderer", fake_renderer(tmp_path),
                 "--scout-cache", str(tmp_path / "cache"), "--game-data", str(fake_game_data(tmp_path, "good"))])
    assert code == 0 and len(imported) == 2
    assert sorted(p.name for p in (tmp_path / "batch").iterdir()) == ["views.txt"]

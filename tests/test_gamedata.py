import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from h2live import gamedata
from h2live.gamedata import NoGameData, find_game_data, get_demo, maps_folder


def game_folder(path: Path, data: str = "DATA", agg: str = "HEROES2.AGG") -> Path:
    (path / data).mkdir(parents=True)
    (path / data / agg).write_bytes(b"agg")
    return path


@pytest.fixture
def places(tmp_path, monkeypatch):
    """Points the default fheroes2 and demo folders at empty temporary paths."""
    monkeypatch.setattr(gamedata, "FHEROES2_DATA", tmp_path / "fheroes2")
    monkeypatch.setenv("H2LIVE_DEMO_DIR", str(tmp_path / "demo"))
    return tmp_path


def test_given_folder_wins(places):
    game_folder(places / "fheroes2")
    given = game_folder(places / "original")
    assert find_game_data(given) == given


def test_given_folder_without_the_graphics_archive_is_refused(places):
    (places / "empty").mkdir()
    with pytest.raises(NoGameData, match="HEROES2.AGG"):
        find_game_data(places / "empty")


def test_finds_the_graphics_archive_in_any_letter_case(places):
    folder = game_folder(places / "original", data="data", agg="heroes2.agg")
    assert find_game_data(folder) == folder


def test_defaults_to_the_fheroes2_folder(places):
    game_folder(places / "fheroes2", data="data")
    game_folder(places / "demo")
    assert find_game_data(None) == places / "fheroes2"


def test_falls_back_to_a_downloaded_demo(places):
    (places / "fheroes2").mkdir()  # fheroes2 installed, but no game data copied into it
    game_folder(places / "demo")
    assert find_game_data(None) == places / "demo"


def test_without_game_data_lists_the_options(places):
    with pytest.raises(NoGameData) as error:
        find_game_data(None)
    message = str(error.value)
    assert "fheroes2" in message and "--game-data" in message and "h2live get-demo" in message


def test_maps_folder_in_any_letter_case(tmp_path):
    (tmp_path / "MAPS").mkdir()
    assert maps_folder(tmp_path) == tmp_path / "MAPS"
    assert maps_folder(tmp_path / "missing") is None


def demo_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("DATA/HEROES2.AGG", b"graphics")
        archive.writestr("MAPS/BROKENA.MP2", b"map")
        archive.writestr("HEROES2.EXE", b"game")
        archive.writestr("../escape.txt", b"no")
    return buffer.getvalue()


def fake_download(content: bytes):
    def download(url: str, to: Path) -> None:
        to.write_bytes(content)
    return download


def test_get_demo_keeps_only_the_graphics_and_maps(tmp_path):
    content = demo_zip()
    get_demo(tmp_path / "demo", download=fake_download(content), sha256=hashlib.sha256(content).hexdigest())
    files = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())
    assert files == ["demo/DATA/HEROES2.AGG", "demo/MAPS/BROKENA.MP2"]
    assert find_game_data(tmp_path / "demo") == tmp_path / "demo"


def test_get_demo_refuses_an_unexpected_download(tmp_path):
    with pytest.raises(RuntimeError, match="checksum"):
        get_demo(tmp_path / "demo", download=fake_download(demo_zip()), sha256="0" * 64)
    assert not (tmp_path / "demo").exists()


def test_get_demo_pins_the_official_archive():
    assert gamedata.DEMO_URL == "https://archive.org/download/HeroesofMightandMagicIITheSuccessionWars_1020/h2demo.zip"
    assert gamedata.DEMO_SHA256 == "12048c8b03875c81e69534a3813aaf6340975e77b762dc1b79a4ff5514240e3c"

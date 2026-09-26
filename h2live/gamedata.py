"""Finds the HoMM2 game data the renderer draws with, and downloads the free demo on request."""

import hashlib
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# Where fheroes2 keeps its data on macOS; non-bundle builds only look in ~/.fheroes2 unless told otherwise.
FHEROES2_DATA = Path.home() / "Library/Application Support/fheroes2"
# The demo fheroes2's own download_demo_version.sh fetches. It is not ours to redistribute, so it is
# downloaded only when asked, straight from the archive.
DEMO_URL = "https://archive.org/download/HeroesofMightandMagicIITheSuccessionWars_1020/h2demo.zip"
DEMO_SHA256 = "12048c8b03875c81e69534a3813aaf6340975e77b762dc1b79a4ff5514240e3c"

OPTIONS = """No HoMM2 game data found. Any one of these works:
  - fheroes2 with the game's files installed: {fheroes2} (the default place)
  - an original HoMM2 install (e.g. from GOG): h2live batch --game-data <folder with DATA and MAPS>
  - the free demo (one map; the art is the full game's): h2live get-demo"""


class NoGameData(Exception):
    pass


def demo_dir() -> Path:
    return Path(os.environ.get("H2LIVE_DEMO_DIR", Path.home() / "Library/Application Support/h2live/demo"))


def child(folder: Path, name: str) -> Path | None:
    """`folder/name` in whatever letter case it has on disk: installs differ (DATA, data)."""
    if not folder.is_dir():
        return None
    return next((p for p in folder.iterdir() if p.name.lower() == name.lower()), None)


def maps_folder(game_data: Path) -> Path | None:
    return child(game_data, "maps")


def has_graphics(folder: Path) -> bool:
    data = child(folder, "data")
    return data is not None and child(data, "heroes2.agg") is not None


def find_game_data(given: Path | None) -> Path:
    """The folder given, else fheroes2's data folder, else a downloaded demo."""
    if given is not None:
        if not has_graphics(given):
            raise NoGameData(f"{given} has no DATA/HEROES2.AGG; point --game-data at the folder that holds DATA and MAPS")
        return given
    for folder in (FHEROES2_DATA, demo_dir()):
        if has_graphics(folder):
            return folder
    raise NoGameData(OPTIONS.format(fheroes2=FHEROES2_DATA))


def download(url: str, to: Path) -> None:
    with urllib.request.urlopen(url) as response, to.open("wb") as out:
        shutil.copyfileobj(response, out)


def get_demo(dest: Path, download=download, sha256: str = DEMO_SHA256) -> None:
    """Downloads the demo and keeps only what the renderer reads: the graphics archive and the maps."""
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / "h2demo.zip"
        download(DEMO_URL, archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != sha256:
            raise RuntimeError(f"the download from {DEMO_URL} doesn't match the expected checksum; not using it")
        with zipfile.ZipFile(archive) as demo:
            for name in demo.namelist():
                parts = name.upper().split("/")
                if parts == ["DATA", "HEROES2.AGG"] or (len(parts) == 2 and parts[0] == "MAPS" and parts[1].endswith(".MP2")):
                    target = dest / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(demo.read(name))


def get_demo_command() -> int:
    dest = demo_dir()
    print(f"Downloading the HoMM2 demo from {DEMO_URL} …")
    get_demo(dest)
    print(f"Saved its graphics and map to {dest}. h2live doesn't redistribute the demo; please keep these files")
    print("to yourself too. h2live batch uses them when no fheroes2 game data is found.")
    return 0

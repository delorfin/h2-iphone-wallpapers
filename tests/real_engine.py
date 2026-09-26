"""The built renderer and the game data it draws with, for tests that run the real engine."""

from pathlib import Path

import pytest

from h2live.gamedata import NoGameData, find_game_data, maps_folder

REPO = Path(__file__).resolve().parents[1]
RENDERER = REPO / "engine" / "fheroes2"
BUNDLED_MAPS = REPO / "engine" / "maps"

try:
    GAME_DATA = find_game_data(None)
except NoGameData:
    GAME_DATA = None

needs_engine = pytest.mark.skipif(
    not RENDERER.exists() or GAME_DATA is None,
    reason="needs the renderer (./build.sh) and game data (fheroes2's, or h2live get-demo)")


def game_maps() -> list[Path]:
    folder = maps_folder(GAME_DATA) if GAME_DATA else None
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in (".mp2", ".mx2")) if folder else []

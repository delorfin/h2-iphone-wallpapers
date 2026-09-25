"""The user's verdicts on the first calibration sheet, checked against the real maps."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from h2live.select import Window, check, load_map

REPO = Path(__file__).resolve().parents[2]
RENDERER = REPO / "fheroes2"
GAME_DATA = Path.home() / "Library/Application Support/fheroes2"
MAPS = GAME_DATA / "maps"

pytestmark = pytest.mark.skipif(not RENDERER.exists() or not MAPS.exists(),
                                reason="build the renderer first: ios-livephoto/build.sh")


@pytest.fixture(scope="module")
def scouted(tmp_path_factory):
    out = tmp_path_factory.mktemp("scout")
    names = ['Beautifu.MX2', 'ContinentPerdu.mp2', 'Dark One.mp2', 'Element.MP2', 'Empires.mp2', 'GHOSTPLT.MX2', 'ISLEWOND.MP2', 'KNIGHTS40.MX2', 'LittlePe.MX2', 'Map_0127.MP2', 'OLDKI_00.MP2', 'Pax1.mp2', 'Plains.MX2', 'RIDDLAND.MP2', 'SANDTIME.MX2', 'Soul Mirror.mp2', 'THETREAC.MP2', 'TheSwamp.mp2', 'WOTR!.MX2', 'deathwh2.mp2', 'mobydick.mx2', 'scandina.mp2', 'thearena.mp2']
    result = subprocess.run([str(RENDERER), "--scout-maps", str(out), *(str(MAPS / n) for n in names)],
                            capture_output=True, text=True, timeout=300,
                            env={**os.environ, "FHEROES2_DATA": str(GAME_DATA)})
    assert result.returncode == 0, result.stderr
    return {n: load_map(json.loads((out / f"{n}.json").read_text())) for n in names}


def failures(scouted, name: str, x: int, y: int) -> list[str]:
    return check(scouted[name], Window(x, y, 14, 22)).failures


@pytest.mark.parametrize("name, x, y", [
    ("Dark One.mp2", 40, 69),  # 04: empty top and bottom, objects in chunks
    ("LittlePe.MX2", 4, 77),  # 23: almost empty
    ("deathwh2.mp2", 4, 23),  # 24: almost empty sea
])
def test_views_the_user_rejected_fail(scouted, name, x, y):
    assert failures(scouted, name, x, y)


@pytest.mark.parametrize("name, x, y", [
    ("ISLEWOND.MP2", 99, 119),  # 13: three diagonal objects with others between
    ("Soul Mirror.mp2", 120, 10),  # 14-16: forests and ranges that aren't square
    ("scandina.mp2", 130, 74),
    ("Pax1.mp2", 1, 42),
])
def test_irregular_repeats_the_user_accepted_pass_the_repetition_rule(scouted, name, x, y):
    assert "repetition" not in failures(scouted, name, x, y)


def test_the_dirt_crack_in_sheet_07_counts_as_an_object(scouted):
    # A terrain-layer decoration (OBJNDIRT sprites 143-144) at tiles 42,46 and 43,46.
    assert scouted["RIDDLAND.MP2"].occupied[46, 42]


# Every other view the user saw marked PASS, and 13-16, which the user accepted. Sheet 12 and 26 are
# as sparse as 04 by every measure tried and now fail too.
@pytest.mark.parametrize("name, x, y", [
    ("OLDKI_00.MP2", 0, 76),  # 01,
    ("Plains.MX2", 36, 77),  # 02,
    ("SANDTIME.MX2", 48, 31),  # 03,
    ("TheSwamp.mp2", 91, 84),  # 09,
    ("THETREAC.MP2", 20, 2),  # 10,
    ("Element.MP2", 34, 35),  # 11,
    ("ISLEWOND.MP2", 99, 119),  # 13,
    ("Soul Mirror.mp2", 120, 10),  # 14,
    ("scandina.mp2", 130, 74),  # 15,
    ("Pax1.mp2", 1, 42),  # 16,
    ("Beautifu.MX2", 47, 31),  # 17,
    ("GHOSTPLT.MX2", 92, 111),  # 18,
    ("ContinentPerdu.mp2", 14, 60),  # 19,
    ("KNIGHTS40.MX2", 4, 45),  # 25,
    ("mobydick.mx2", 26, 62),  # 27,
    ("Map_0127.MP2", 105, 101),  # 28,
    ("Empires.mp2", 31, 113),  # 32,
    ("WOTR!.MX2", 130, 80),  # 33,
    ("thearena.mp2", 6, 3),  # 34,
])
def test_views_the_user_accepted_pass(scouted, name, x, y):
    assert failures(scouted, name, x, y) == []

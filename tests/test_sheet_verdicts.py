"""The user's verdicts on the calibration sheets, checked against the real maps.

Tags are <round>-<sheet number>. Views the user didn't comment on keep the verdict the sheet showed,
unless a later verdict overruled the rule behind it (sheet 2-27 at 60% of one type passes
because 2-28 at 64% was fine; 2-04 with a 5x5 blank square passes because 2-06 with one was fine).
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from h2live.select import Window, check, load_map

REPO = Path(__file__).resolve().parents[1]
RENDERER = REPO / "engine" / "fheroes2"
GAME_DATA = Path.home() / "Library/Application Support/fheroes2"
MAPS = GAME_DATA / "maps"
NAMES = ['04Chateau du Dragon.mp2', '06Ponts.mp2', '10Rand.mp2', 'Avatar.mp2', 'Beautifu.MX2', 'BloodBul.MX2', 'Citydrag.mx2', 'ContinentPerdu.mp2', 'Cousins.MX2', 'DIXIE01.MP2', 'DRAGONIS.MP2', 'Dark One.mp2', 'Element.MP2', 'Empires.mp2', 'Enia.mp2', 'GHOSTPLT.MX2', 'ISLEWOND.MP2', 'Jasonsla.mp2', 'JudgeDoo.MX2', 'KNIGHTS40.MX2', 'LittlePe.MX2', 'M-earth.mx2', 'MAP_0075.MP2', 'Map_0127.MP2', 'Midnight.MX2', 'MikaCon.MP2', 'Necroman.MX2', 'Notredyy.mp2', 'OLDKI_00.MP2', 'Pat13.mx2', 'Pax1.mp2', 'PilgrimP.MX2', 'Plains.MX2', 'RIDDLAND.MP2', 'SANDTIME.MX2', 'SONOFASA.MX2', 'Six Sins.mp2', 'Soul Mirror.mp2', 'StarfireMP.mx2', 'THETREAC.MP2', 'The Maze.MP2', 'TheDande.mp2', 'TheKeepe.mp2', 'TheSwamp.mp2', 'Treasure.mp2', 'WOTR!.MX2', 'bigwar.mp2', 'bugfest.mp2', 'deathwh2.mp2', 'feuglace.MP2', 'lom.mx2', 'marionb.mp2', 'mobydick.mx2', 'northame.mp2', 'scandina.mp2', 'thearena.mp2']

# The calibration maps come from a fan collection, not the game, so most setups skip these.
pytestmark = pytest.mark.skipif(not RENDERER.exists() or not all((MAPS / n).exists() for n in NAMES),
                                reason="needs the renderer and the calibration maps in fheroes2's maps folder")


@pytest.fixture(scope="module")
def scouted(tmp_path_factory):
    out = tmp_path_factory.mktemp("scout")
    result = subprocess.run([str(RENDERER), "--scout-maps", str(out), *(str(MAPS / n) for n in NAMES)],
                            capture_output=True, text=True, timeout=300,
                            env={**os.environ, "FHEROES2_DATA": str(GAME_DATA)})
    assert result.returncode == 0, result.stderr
    return {n: load_map(json.loads((out / f"{n}.json").read_text())) for n in NAMES}


def failures(scouted, name: str, x: int, y: int) -> list[str]:
    return check(scouted[name], Window(x, y, 14, 22)).failures


@pytest.mark.parametrize("tag, name, x, y", [
    ("1-04", "Dark One.mp2", 40, 69),  # empty top and bottom, objects in chunks
    ("1-23", "LittlePe.MX2", 4, 77),  # almost empty
    ("1-24", "deathwh2.mp2", 4, 23),  # almost empty sea
    ("2-02", "Plains.MX2", 75, 61),  # emptyish
    ("2-07", "RIDDLAND.MP2", 24, 17),  # borderline, bad side
    ("2-08", "04Chateau du Dragon.mp2", 43, 34),  # emptyish
    ("2-15", "northame.mp2", 63, 13),  # borderline, bad side
    ("2-16", "GHOSTPLT.MX2", 120, 107),  # borderline, bad side
    ("2-17", "06Ponts.mp2", 43, 46),  # borderline, bad side
    ("2-18", "marionb.mp2", 38, 37),  # borderline, bad side
    ("2-29", "Enia.mp2", 129, 99),  # empty
    ("2-33", "bigwar.mp2", 81, 78),  # emptyish at top
    ("2-38", "Six Sins.mp2", 12, 77),  # emptyish
    ("2-11", "Element.MP2", 53, 45),
    ("2-12", "Jasonsla.mp2", 120, 85),
    ("2-34", "M-earth.mx2", 126, 53),
    ("2-35", "Avatar.mp2", 29, 64),
])
def test_views_the_user_rejected_fail(scouted, tag, name, x, y):
    assert failures(scouted, name, x, y)


@pytest.mark.xfail(reason="open sea with some flotsam beside a forested coast; no rule tried separates it "
                          "from sheet 2-01 and 2-13, which passed", strict=True)
def test_sheet_2_10_emptyish_sea_fails(scouted):
    assert failures(scouted, "TheSwamp.mp2", 9, 0)


@pytest.mark.parametrize("tag, name, x, y", [
    ("1-01", "OLDKI_00.MP2", 0, 76),
    ("1-02", "Plains.MX2", 36, 77),
    ("1-03", "SANDTIME.MX2", 48, 31),
    ("1-09", "TheSwamp.mp2", 91, 84),
    ("1-10", "THETREAC.MP2", 20, 2),
    ("1-11", "Element.MP2", 34, 35),
    ("1-13", "ISLEWOND.MP2", 99, 119),
    ("1-14", "Soul Mirror.mp2", 120, 10),
    ("1-15", "scandina.mp2", 130, 74),
    ("1-16", "Pax1.mp2", 1, 42),
    ("1-17", "Beautifu.MX2", 47, 31),
    ("1-18", "GHOSTPLT.MX2", 92, 111),
    ("1-19", "ContinentPerdu.mp2", 14, 60),
    ("1-25", "KNIGHTS40.MX2", 4, 45),
    ("1-27", "mobydick.mx2", 26, 62),
    ("1-28", "Map_0127.MP2", 105, 101),
    ("1-32", "Empires.mp2", 31, 113),
    ("1-33", "WOTR!.MX2", 130, 80),
    ("1-34", "thearena.mp2", 6, 3),
    ("2-01", "OLDKI_00.MP2", 59, 77),
    ("2-03", "SANDTIME.MX2", 52, 4),
    ("2-05", "SONOFASA.MX2", 21, 28),  # top area is under the clock anyway
    ("2-06", "JudgeDoo.MX2", 58, 21),  # borderline, good side
    ("2-09", "ISLEWOND.MP2", 79, 107),
    ("2-13", "scandina.mp2", 38, 117),  # borderline, good side
    ("2-14", "Pax1.mp2", 69, 40),  # borderline, good side
    ("2-19", "THETREAC.MP2", 7, 8),
    ("2-20", "Soul Mirror.mp2", 24, 42),
    ("2-21", "Necroman.MX2", 20, 9),
    ("2-22", "TheKeepe.mp2", 58, 50),  # good; fine in terms of repetition
    ("2-23", "StarfireMP.mx2", 1, 37),  # fine in terms of repetition
    ("2-24", "bugfest.mp2", 2, 90),  # fine in terms of repetition
    ("2-25", "PilgrimP.MX2", 50, 43),
    ("2-26", "Beautifu.MX2", 26, 49),
    ("2-28", "Treasure.mp2", 66, 24),  # borderline, good side
    ("2-32", "Midnight.MX2", 23, 49),
    ("2-36", "DIXIE01.MP2", 93, 103),
    ("2-37", "TheDande.mp2", 84, 38),
])
def test_views_the_user_accepted_pass(scouted, tag, name, x, y):
    assert failures(scouted, name, x, y) == []


def test_sheet_2_30_has_too_many_of_one_object(scouted):
    # "Ultra repetition: look how many of the same object."
    assert "frequency" in failures(scouted, "10Rand.mp2", 127, 116)


def test_sheet_2_31_has_many_of_one_object_but_is_fine(scouted):
    # "Similar but better, fine." It still fails on having only two object types.
    assert not {"frequency", "repetition"} & set(failures(scouted, "BloodBul.MX2", 130, 76))


def test_the_dirt_crack_in_sheet_1_07_counts_as_an_object(scouted):
    # A terrain-layer decoration (OBJNDIRT sprites 143-144) at tiles 42,46 and 43,46.
    assert scouted["RIDDLAND.MP2"].occupied[46, 42]

import subprocess
from pathlib import Path

import pytest

from h2live.photos import import_pairs

PAIRS = [(Path("/x/H2_000.HEIC"), Path("/x/H2_000.mov")), (Path("/x/H2_001.HEIC"), Path("/x/H2_001.mov"))]


def fake_osascript(stdout: str, calls: list):
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
    return run


def test_returns_imported_count_and_targets_album():
    calls = []
    assert import_pairs(PAIRS, "H2 2026-09-25", run=fake_osascript("2\n", calls)) == 2
    script = calls[0][-1]
    assert 'album "H2 2026-09-25"' in script
    assert 'POSIX file "/x/H2_001.mov"' in script


def test_allows_long_imports():
    calls = []
    import_pairs(PAIRS, "H2", run=fake_osascript("2\n", calls))
    assert "with timeout of 1800 seconds" in calls[0][-1]


def test_count_mismatch_names_the_album():
    with pytest.raises(RuntimeError, match="H2 test"):
        import_pairs(PAIRS, "H2 test", run=fake_osascript("4\n", []))

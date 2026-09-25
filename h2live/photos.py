"""Imports Live Photo pairs into a Photos album.

Goes through the Photos app with AppleScript: it pairs the still and video into
one Live Photo, and it doesn't need the Photos privacy permission that the
terminal lacks.
"""

import subprocess
from pathlib import Path


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def import_pairs(pairs: list[tuple[Path, Path]], album: str, run=subprocess.run) -> int:
    files = ", ".join(f"POSIX file {_quote(str(path))}" for pair in pairs for path in pair)
    # A batch of 60 pairs takes minutes; AppleScript's default timeout is 2 minutes.
    script = f"""with timeout of 1800 seconds
tell application "Photos"
set imported to import {{{files}}} skip check duplicates true
if not (exists album {_quote(album)}) then make new album named {_quote(album)}
add imported to album {_quote(album)}
return count of imported
end tell
end timeout"""
    result = run(["osascript", "-e", script], check=True, capture_output=True, text=True)
    imported = int(result.stdout.strip())
    if imported != len(pairs):
        raise RuntimeError(
            f"Photos imported {imported} items into album {album!r}, expected {len(pairs)} Live Photos; "
            "some pairs were not recognised as Live Photos"
        )
    return imported

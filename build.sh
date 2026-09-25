#!/bin/sh
# Builds the renderer. `make` overwrites ./fheroes2 in place, and macOS then kills the
# overwritten binary on launch (stale code signature cache), so replace it with a new file.
set -e
cd "$(dirname "$0")/.."
make -j8
rm -f fheroes2
cp src/dist/fheroes2/fheroes2 fheroes2

#!/bin/sh
# Builds the renderer as a release build. The Makefile keeps developer assertions on, and some
# shipped maps trip them, so pass NDEBUG. After changing flags, run `make clean` once first.
# `make` overwrites ./fheroes2 in place, and macOS then kills the overwritten binary on launch
# (stale code signature cache), so replace it with a new file.
set -e
cd "$(dirname "$0")/.."
CPPFLAGS="-DNDEBUG" make -j8
rm -f fheroes2
cp src/dist/fheroes2/fheroes2 fheroes2

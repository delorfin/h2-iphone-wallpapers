###########################################################################
#   fheroes2: https://github.com/ihhub/fheroes2                           #
#   Copyright (C) 2021 - 2025                                             #
#                                                                         #
#   This program is free software; you can redistribute it and/or modify  #
#   it under the terms of the GNU General Public License as published by  #
#   the Free Software Foundation; either version 2 of the License, or     #
#   (at your option) any later version.                                   #
#                                                                         #
#   This program is distributed in the hope that it will be useful,       #
#   but WITHOUT ANY WARRANTY; without even the implied warranty of        #
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         #
#   GNU General Public License for more details.                          #
#                                                                         #
#   You should have received a copy of the GNU General Public License     #
#   along with this program; if not, write to the                         #
#   Free Software Foundation, Inc.,                                       #
#   59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.             #
###########################################################################
# Changed in 2026 for h2-iphone-wallpapers: builds only the engine binary.

# Options:
#
# FHEROES2_STRICT_COMPILATION: build in strict compilation mode (turns warnings into errors)
# FHEROES2_WITH_DEBUG: build in debug mode
# FHEROES2_WITH_ASAN: build with UB Sanitizer and Address Sanitizer (small runtime overhead, incompatible with FHEROES2_WITH_TSAN)
# FHEROES2_WITH_TSAN: build with UB Sanitizer and Thread Sanitizer (large runtime overhead, incompatible with FHEROES2_WITH_ASAN)
# FHEROES2_WITH_IMAGE: build with SDL_image (requires libpng)
# FHEROES2_WITH_SYSTEM_SMACKER: build with an external libsmacker instead of the bundled one
# FHEROES2_DATA: set the built-in path to the fheroes2 data directory (e.g. /usr/share/fheroes2)

# Trimmed for h2-iphone-wallpapers: builds only the engine binary (no translations, tools or app bundle).

.PHONY: all clean

all:
	$(MAKE) -C src/dist
	cp src/dist/fheroes2/fheroes2 .

clean:
	$(MAKE) -C src/dist clean
	-rm -rf fheroes2

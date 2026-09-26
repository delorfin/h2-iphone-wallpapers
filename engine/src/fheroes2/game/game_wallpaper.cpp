/***************************************************************************
 *   fheroes2: https://github.com/ihhub/fheroes2                           *
 *   Copyright (C) 2019 - 2023                                             *
 *                                                                         *
 *   Free Heroes2 Engine: http://sourceforge.net/projects/fheroes2         *
 *   Copyright (C) 2009 by Andrey Afletdinov <fheroes2@gmail.com>          *
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 *   This program is distributed in the hope that it will be useful,       *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU General Public License for more details.                          *
 *                                                                         *
 *   You should have received a copy of the GNU General Public License     *
 *   along with this program; if not, write to the                         *
 *   Free Software Foundation, Inc.,                                       *
 *   59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.             *
 ***************************************************************************/

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <optional>
#include <ostream>
#include <sstream>
#include <string>
#include <system_error>
#include <vector>

#include "SDL.h"
#include "game.h" // IWYU pragma: associated
#include "game_delays.h"
#include "game_interface.h"
#include "game_mode.h"
#include "ground.h"
#include "heroes.h"
#include "image.h"
#include "image_tool.h"
#include "interface_gamearea.h"
#include "jni.h"
#include "localevent.h"
#include "logging.h"
#include "maps.h"
#include "maps_fileinfo.h"
#include "map_object_info.h"
#include "maps_tiles.h"
#include "math_base.h"
#include "pal.h"
#include "mp2.h"
#include "players.h"
#include "rand.h"
#include "screen.h"
#include "settings.h"
#include "system.h"
#include "world.h"

namespace
{
    uint32_t lastMapUpdate = 0;
    int regionUpdateCount = 0;
    int lastScale = -1;
    fheroes2::ResolutionInfo lastResolution;
    std::filesystem::file_time_type lastConfigMtime;

    enum class LiveWallpaperEvent : int32_t
    {
        // These values must stay in sync with the WALLPAPER_EVENT_* constants in SDLActivity.java.
        Hide,
        UpdateConfigs,
        ResizeDisplay,
    };

    bool isHidePending = false;

#if defined( __ANDROID__ )
    constexpr int COMMAND_PAUSE_NOW = 0x8000 + 1;
#endif

    constexpr uint32_t EVENT_POLL_DELAY = 32;

    constexpr int TILE_WIDTH = 32;

    void lwpLog( const char * event )
    {
        VERBOSE_LOG( "LWP " << event << " | isHidePending=" << isHidePending << " lastMapUpdate=" << lastMapUpdate )
    }

    void pushWallpaperEvent( LiveWallpaperEvent code )
    {
        VERBOSE_LOG( "pushWallpaperEvent code=" << static_cast<int32_t>( code ) )

        if ( SDL_WasInit( SDL_INIT_EVENTS ) == 0 ) {
            return;
        }

        SDL_Event event;
        SDL_zero( event );
        event.type = SDL_USEREVENT;
        event.user.code = static_cast<int32_t>( code );
        SDL_PushEvent( &event );
    }

    void renderMap()
    {
        if ( world.w() <= 0 ) {
            return;
        }

        Interface::GameArea const & gameArea = Interface::AdventureMap::Get().getGameArea();
        fheroes2::Display & display = fheroes2::Display::instance();

        Game::updateAdventureMapAnimationIndex();
        gameArea.Redraw( display, Interface::RedrawLevelType::LEVEL_OBJECTS | Interface::RedrawLevelType::LEVEL_HEROES );
        display.render();
    }

    int32_t randomAxisCenter( int32_t displayPx, int32_t mapTiles )
    {
        const int32_t halfScreenTiles = displayPx / TILE_WIDTH / 2;
        return Rand::Get( halfScreenTiles + 1, mapTiles - halfScreenTiles - 1 );
    }

    void randomizeGameArea()
    {
        if ( world.w() <= 0 ) {
            return;
        }

        fheroes2::Display & display = fheroes2::Display::instance();
        const int32_t x = randomAxisCenter( display.width(), World::Get().w() );
        const int32_t y = randomAxisCenter( display.height(), World::Get().h() );

        VERBOSE_LOG( "randomizeGameArea x=" << x << " y=" << y )

        Interface::AdventureMap::Get().getGameArea().SetCenter( { x, y } );

        renderMap();
    }

    constexpr int mapLevels = Interface::RedrawLevelType::LEVEL_OBJECTS | Interface::RedrawLevelType::LEVEL_HEROES;

    // HoMM2 animates water, lava and treasure glints by rotating palette entries, which the screen
    // applies on output; saved frames need the same rotation baked in.
    fheroes2::Image cycledFrame( const fheroes2::Display & display, const uint32_t step )
    {
        fheroes2::Image frame( display.width(), display.height() );
        fheroes2::Copy( display, frame );
        fheroes2::ApplyPalette( frame, PAL::GetCyclingPalette( step ) );
        return frame;
    }

    // A view with nothing animated (open grass) would make a Live Photo without motion.
    bool viewHasAnimation( const Interface::GameArea & gameArea, fheroes2::Display & display )
    {
        gameArea.Redraw( display, mapLevels );
        const fheroes2::Image first = cycledFrame( display, 0 );
        const size_t size = static_cast<size_t>( display.width() ) * display.height();

        for ( uint32_t step = 1; step < 4; ++step ) {
            Game::updateAdventureMapAnimationIndex();
            gameArea.Redraw( display, mapLevels );
            const fheroes2::Image next = cycledFrame( display, step );
            if ( !std::equal( first.image(), first.image() + size, next.image() ) ) {
                return true;
            }
        }
        return false;
    }

    // The random centre needs at least one spare tile beyond each half of the view.
    bool viewFitsMap( const int32_t width, const int32_t height )
    {
        const auto fits = []( const int32_t viewPx, const int32_t mapTiles ) { return mapTiles >= 2 * ( viewPx / TILE_WIDTH / 2 ) + 2; };
        return fits( width, world.w() ) && fits( height, world.h() );
    }

    // Saves `frames` animation steps of the current view, plus the map name, into <outDir>/<index>.
    std::optional<std::string> saveView( const std::string & outDir, const int index, const int frames )
    {
        fheroes2::Display & display = fheroes2::Display::instance();
        const Interface::GameArea & gameArea = Interface::AdventureMap::Get().getGameArea();

        char name[16];
        std::snprintf( name, sizeof( name ), "%03d", index );
        const std::string dir = System::concatPath( outDir, name );
        std::filesystem::create_directories( dir );

        for ( int frame = 0; frame < frames; ++frame ) {
            Game::updateAdventureMapAnimationIndex();
            gameArea.Redraw( display, mapLevels );
            std::snprintf( name, sizeof( name ), "f%02d.bmp", frame );
            const std::string path = System::concatPath( dir, name );
            if ( !fheroes2::Save( cycledFrame( display, static_cast<uint32_t>( frame ) ), path ) ) {
                ERROR_LOG( "Could not save " << path )
                return std::nullopt;
            }
        }

        std::ofstream( System::concatPath( dir, "map.txt" ) ) << Settings::Get().getCurrentMapInfo().filename << '\n';
        return dir;
    }

    // Keeps made-up hero UIDs clear of the map's object UIDs.
    constexpr uint32_t heroUidBase = 0xF0000000;

    void writeJsonString( std::ostream & out, const std::string & text )
    {
        out << '"';
        for ( const char c : text ) {
            if ( c == '"' || c == '\\' ) {
                out << '\\' << c;
            }
            else if ( static_cast<unsigned char>( c ) < 0x20 ) {
                char escaped[8];
                std::snprintf( escaped, sizeof( escaped ), "\\u%04x", static_cast<unsigned char>( c ) );
                out << escaped;
            }
            else {
                out << c;
            }
        }
        out << '"';
    }

    const char * groundName( const int ground )
    {
        switch ( ground ) {
        case Maps::Ground::DESERT:
            return "desert";
        case Maps::Ground::SNOW:
            return "snow";
        case Maps::Ground::SWAMP:
            return "swamp";
        case Maps::Ground::WASTELAND:
            return "wasteland";
        case Maps::Ground::BEACH:
            return "beach";
        case Maps::Ground::LAVA:
            return "lava";
        case Maps::Ground::DIRT:
            return "dirt";
        case Maps::Ground::GRASS:
            return "grass";
        case Maps::Ground::WATER:
            return "water";
        default:
            return "unknown";
        }
    }

    // The renderer animates an object part by cycling through the sprites that follow it, and draws
    // monsters from an animated set of their own.
    bool isPartAnimated( const Maps::ObjectPart & part )
    {
        if ( part.icnType == MP2::OBJ_ICN_TYPE_MONS32 ) {
            return true;
        }
        const Maps::ObjectPartInfo * info = Maps::getObjectPartByIcn( part.icnType, part.icnIndex );
        return info != nullptr && info->animationFrames > 0;
    }

    void writePart( std::ostream & out, const Maps::ObjectPart & part, bool & isFirst )
    {
        out << ( isFirst ? "" : "," ) << '[' << part._uid << ',' << static_cast<int>( part.icnType ) << ',' << static_cast<int>( part.icnIndex ) << ','
            << static_cast<int>( part.layerType ) << ',' << ( isPartAnimated( part ) ? 1 : 0 ) << ',' << static_cast<int>( Maps::getObjectTypeByIcn( part.icnType, part.icnIndex ) )
            << ']';
        isFirst = false;
    }

    // Describes the loaded map for view selection: per tile, row by row, the terrain, the MP2 object
    // type, whether an object stands there, and every object part as [uid, icnType, icnIndex, layer, animated, MP2 object type].
    void writeScout( std::ostream & out, const std::string & mapFile )
    {
        out << "{\"map\":";
        writeJsonString( out, mapFile );
        out << ",\"width\":" << world.w() << ",\"height\":" << world.h() << ",\"tiles\":[";

        for ( int32_t index = 0; index < world.w() * world.h(); ++index ) {
            const Maps::Tile & tile = world.getTile( index );
            const Maps::ObjectPart & main = tile.getMainObjectPart();
            const bool hasMain = main.icnType != MP2::OBJ_ICN_TYPE_UNKNOWN;
            const bool hasHero = tile.getMainObjectType() == MP2::OBJ_HERO;

            bool isOccupied = hasHero || ( hasMain && !main.isPassabilityTransparent() );
            for ( const Maps::ObjectPart & part : tile.getGroundObjectParts() ) {
                isOccupied = isOccupied || !part.isPassabilityTransparent();
            }
            // Top parts are the upper halves of tall objects (tree crowns, peaks) drawn over this tile.
            isOccupied = isOccupied || !tile.getTopObjectParts().empty();

            out << ( index == 0 ? "" : "," ) << "{\"ground\":\"" << groundName( tile.GetGround() ) << "\",\"object\":" << static_cast<int>( tile.getMainObjectType() )
                << ",\"occupied\":" << ( isOccupied ? "true" : "false" ) << ",\"parts\":[";
            bool isFirst = true;
            for ( const Maps::ObjectPart & part : tile.getGroundObjectParts() ) {
                writePart( out, part, isFirst );
            }
            if ( hasMain ) {
                writePart( out, main, isFirst );
            }
            for ( const Maps::ObjectPart & part : tile.getTopObjectParts() ) {
                writePart( out, part, isFirst );
            }
            if ( hasHero ) {
                // Heroes are drawn from their own state rather than object parts.
                const Heroes * hero = tile.getHero();
                const int heroId = ( hero != nullptr ) ? hero->GetID() : 0;
                writePart( out, Maps::ObjectPart( Maps::OBJECT_LAYER, heroUidBase + static_cast<uint32_t>( heroId ), MP2::OBJ_ICN_TYPE_MINIHERO, static_cast<uint8_t>( heroId ) ),
                           isFirst );
            }
            out << "]}";
        }
        out << "]}\n";
    }

    // FNV-1a: unlike std::hash, it stays the same across standard library versions, which keeps cached scouts valid.
    uint64_t nameSeed( const std::string & name )
    {
        uint64_t hash = 14695981039346656037ULL;
        for ( const char c : name ) {
            hash = ( hash ^ static_cast<uint8_t>( c ) ) * 1099511628211ULL;
        }
        return hash;
    }

    // Seeds the generator from the map name while the map loads, so random castle races, heroes,
    // resources, monsters and artifacts come out the same when a view is scouted and when it is rendered
    // later. SetStartGame() already picks random races, so the seed must be in place before it.
    bool loadMap( const Maps::FileInfo & info, const bool isRepeatable )
    {
        Rand::PCG32 & generator = Rand::CurrentThreadRandomDevice();
        const Rand::PCG32 savedGenerator = generator;
        if ( isRepeatable ) {
            generator = Rand::PCG32( nameSeed( System::GetFileName( info.filename ) ) );
        }

        Settings & conf = Settings::Get();
        conf.setCurrentMapInfo( info );
        conf.GetPlayers().SetStartGame();
        const bool isLoaded = world.LoadMapMP2( info.filename, false );
        if ( isRepeatable ) {
            generator = savedGenerator;
        }

        if ( !isLoaded ) {
            VERBOSE_LOG( "LWP map load FAILED file=" << info.filename.c_str() )
            return false;
        }

        fheroes2::Display & display = fheroes2::Display::instance();
        Interface::AdventureMap::Get().getGameArea().generate( { display.width(), display.height() }, true );
        return true;
    }

    bool loadRandomMap()
    {
        Settings & conf = Settings::Get();
        const Maps::FileInfo currentMap = conf.getCurrentMapInfo();

        MapsFileInfoList mapsList = Maps::getAllMapFileInfos( 1 );

        if ( world.w() > 0 ) {
            mapsList.erase( std::remove_if( mapsList.begin(), mapsList.end(),
                                            [&currentMap]( const Maps::FileInfo & info ) { return info.filename == currentMap.filename; } ),
                            mapsList.end() );
        }

        if ( mapsList.empty() ) {
            VERBOSE_LOG( "LWP map load SKIPPED (no map to load) file=" << currentMap.filename.c_str() )
            return false;
        }

        const uint32_t randomMapIndex = Rand::Get( 0, mapsList.size() - 1 );
        const Maps::FileInfo & nextMap = mapsList.at( randomMapIndex );

        VERBOSE_LOG( "LWP map load START file=" << nextMap.filename.c_str() )
        if ( !loadMap( nextMap, false ) ) {
            return false;
        }
        VERBOSE_LOG( "LWP map load FINISH file=" << nextMap.filename.c_str() )
        return true;
    }

    bool shouldUpdateMapRegion()
    {
        uint32_t const updateInterval = Settings::Get().GetLWPMapUpdateInterval();
        uint32_t const currentTime = std::time( nullptr );
        bool const isExpired = lastMapUpdate <= currentTime - updateInterval;

        VERBOSE_LOG( "ShouldUpdateMapRegion" << " interval:" << updateInterval << " current: " << currentTime << " last update: " << lastMapUpdate )

        return isExpired;
    }

    int regionUpdatesPerMap()
    {
        switch ( World::Get().w() ) {
        case Maps::MEDIUM:
            return 15;
        case Maps::LARGE:
            return 20;
        case Maps::XLARGE:
            return 30;
        case Maps::SMALL:
        default:
            return 10;
        }
    }

    void randomizeVisibleMapPart()
    {
        if ( !shouldUpdateMapRegion() ) {
            return;
        }

        if ( regionUpdateCount >= regionUpdatesPerMap() ) {
            loadRandomMap();
            regionUpdateCount = 0;
        }

        randomizeGameArea();

        ++regionUpdateCount;
        lastMapUpdate = std::time( nullptr );
    }

    void readConfigFile()
    {
        const std::string configurationFileName( Settings::configFileName );
        const std::string confFile = Settings::GetLastFile( "", configurationFileName );

        if ( !System::IsFile( confFile ) ) {
            return;
        }

        std::error_code ec;
        const std::filesystem::file_time_type mtime = std::filesystem::last_write_time( confFile, ec );
        if ( !ec && mtime == lastConfigMtime ) {
            VERBOSE_LOG( "readConfigFile skipped (unchanged)" )
            return;
        }
        lastConfigMtime = mtime;

        VERBOSE_LOG( "readConfigFile" )
        Settings::Get().Read( confFile );
    }

    void resizeDisplay()
    {
        fheroes2::Display & display = fheroes2::Display::instance();
        const int scale = Settings::Get().GetLWPScale();
        const fheroes2::ResolutionInfo resolution = display.getScaledScreenSize( scale );

        if ( scale == lastScale && resolution == lastResolution ) {
            VERBOSE_LOG( "resizeDisplay skipped (scale " << scale << " unchanged)" )
            return;
        }
        lastScale = scale;
        lastResolution = resolution;

        VERBOSE_LOG( "resizeDisplay scale: " << scale )

        Interface::GameArea & gameArea = Interface::AdventureMap::Get().getGameArea();
        const fheroes2::Point center = gameArea.getCurrentCenterInPixels();

        display.setResolution( resolution );
        gameArea.generate( { display.width(), display.height() }, true );
        gameArea.SetCenterInPixels( center );
    }

    void updateBrightness()
    {
        int brightness = Settings::Get().GetLWPBrightness();
        int brightnessAlpha = ( 100 - brightness ) * 255 / 100;
        VERBOSE_LOG( "updateBrightness value: " << brightness << " alpha: " << brightnessAlpha )
        fheroes2::engine().setBrightness( brightnessAlpha );
    }

    void rereadAndApplyConfigs()
    {
        readConfigFile();
        resizeDisplay();
        updateBrightness();
    }

    void handleKeyUp( SDL_Keysym keysym )
    {
        Settings & conf = Settings::Get();
        Interface::GameArea & gameArea = Interface::AdventureMap::Get().getGameArea();

        int const offsetMultiplier = keysym.mod & KMOD_SHIFT ? 10 : 1;
        int const offset = TILE_WIDTH * offsetMultiplier;

        switch ( keysym.scancode ) {
        case SDL_SCANCODE_SPACE:
            randomizeVisibleMapPart();
            break;
        case SDL_SCANCODE_1:
        case SDL_SCANCODE_2:
        case SDL_SCANCODE_3:
        case SDL_SCANCODE_4:
        case SDL_SCANCODE_5:
            conf.SetLWPScale( keysym.scancode - SDL_SCANCODE_1 + 1 );
            break;
        case SDL_SCANCODE_0:
            conf.SetLWPScale( 0 );
            break;
        case SDL_SCANCODE_UP:
            gameArea.ShiftCenter( { 0, -offset } );
            return;
        case SDL_SCANCODE_DOWN:
            gameArea.ShiftCenter( { 0, offset } );
            return;
        case SDL_SCANCODE_LEFT:
            gameArea.ShiftCenter( { -offset, 0 } );
            return;
        case SDL_SCANCODE_RIGHT:
            gameArea.ShiftCenter( { offset, 0 } );
            return;
        case SDL_SCANCODE_ESCAPE:
            exit( 0 );
        default:
            break;
        }

        conf.Save( Settings::configFileName );
        rereadAndApplyConfigs();
    }

    bool handleSDLEvents()
    {
        SDL_Event event;

        while ( SDL_PollEvent( &event ) ) {
            switch ( event.type ) {
            case SDL_RENDER_TARGETS_RESET:
                VERBOSE_LOG( "SDL_RENDER_TARGETS_RESET" )
                fheroes2::Display::instance().render();
                break;
            case SDL_RENDER_DEVICE_RESET:
                VERBOSE_LOG( "SDL_RENDER_DEVICE_RESET" )
                LocalEvent::onRenderDeviceResetEvent();
                fheroes2::Display::instance().render();
                break;
            case SDL_USEREVENT:
                switch ( static_cast<LiveWallpaperEvent>( event.user.code ) ) {
                case LiveWallpaperEvent::Hide:
                    isHidePending = true;
                    lwpLog( "hidden: loading map + rendering frame" );
                    randomizeVisibleMapPart();
                    break;
                case LiveWallpaperEvent::UpdateConfigs:
                    rereadAndApplyConfigs();
                    break;
                case LiveWallpaperEvent::ResizeDisplay:
                    resizeDisplay();
                    break;
                default:
                    break;
                }
                lwpLog( "handled wallpaper event" );
                break;
            case SDL_KEYUP:
                handleKeyUp( event.key.keysym );
                break;
            default:
                break;
            }
        }

        return false;
    }

    fheroes2::GameMode renderWallpaper()
    {
        while ( true ) {
            handleSDLEvents();

            if ( isHidePending ) {
                isHidePending = false;
#if defined( __ANDROID__ )
                SDL_AndroidSendMessage( COMMAND_PAUSE_NOW, 0 );
#endif
                lwpLog( "hidden: frame posted, sent COMMAND_PAUSE_NOW" );
                continue;
            }

            if ( Game::validateAnimationDelay( Game::DelayType::MAPS_DELAY ) ) {
                renderMap();
            }

            SDL_Delay( EVENT_POLL_DELAY );
        }
    }
}

extern "C" JNIEXPORT void JNICALL Java_org_libsdl_app_SDLActivity_pushWallpaperEvent( [[maybe_unused]] JNIEnv * env, [[maybe_unused]] jclass cls, jint code )
{
    pushWallpaperEvent( static_cast<LiveWallpaperEvent>( code ) );
}

fheroes2::GameMode Game::Wallpaper()
{
    rereadAndApplyConfigs();
    loadRandomMap();

    return renderWallpaper();
}

int Game::RenderWallpapers( const std::string & outDir, const int count, const int width, const int height, const int frames )
{
    // Views larger than this fit no map (the biggest is 144x144 tiles).
    constexpr int32_t maxViewPx = 4096;
    constexpr int maxMapAttempts = 20;
    constexpr int maxViewAttempts = 10;

    if ( count < 1 || frames < 1 || width < TILE_WIDTH || height < TILE_WIDTH || width > maxViewPx || height > maxViewPx ) {
        ERROR_LOG( "Usage: --render-wallpapers <dir> <count >= 1> <width 32-4096> <height 32-4096> <frames >= 1>" )
        return EXIT_FAILURE;
    }

    fheroes2::Display & display = fheroes2::Display::instance();
    display.setResolution( { width, height, width, height } );
    const Interface::GameArea & gameArea = Interface::AdventureMap::Get().getGameArea();

    for ( int i = 0; i < count; ++i ) {
        for ( int attempt = 1; !loadRandomMap() || !viewFitsMap( width, height ); ++attempt ) {
            if ( attempt >= maxMapAttempts ) {
                ERROR_LOG( "Could not load a map that fits a " << width << "x" << height << " view after " << maxMapAttempts << " attempts" )
                return EXIT_FAILURE;
            }
        }

        randomizeGameArea();
        for ( int attempt = 1; attempt < maxViewAttempts && !viewHasAnimation( gameArea, display ); ++attempt ) {
            randomizeGameArea();
        }

        if ( !saveView( outDir, i, frames ).has_value() ) {
            return EXIT_FAILURE;
        }
    }

    return EXIT_SUCCESS;
}

int Game::ScoutMaps( const std::string & outDir, const std::vector<std::string> & mapFiles )
{
    MapsFileInfoList maps;
    if ( mapFiles.empty() ) {
        maps = Maps::getAllMapFileInfos( 1 );
    }
    for ( const std::string & file : mapFiles ) {
        Maps::FileInfo info;
        if ( !info.readMP2Map( file, false ) ) {
            ERROR_LOG( "Could not read map " << file )
            return EXIT_FAILURE;
        }
        maps.emplace_back( std::move( info ) );
    }

    std::filesystem::create_directories( outDir );
    int failed = 0;
    for ( const Maps::FileInfo & info : maps ) {
        if ( !loadMap( info, true ) ) {
            ERROR_LOG( "Could not load map " << info.filename )
            ++failed;
            continue;
        }

        const std::string path = System::concatPath( outDir, System::GetFileName( info.filename ) + ".json" );
        std::ofstream out( path );
        writeScout( out, info.filename );
        if ( !out ) {
            ERROR_LOG( "Could not write " << path )
            return EXIT_FAILURE;
        }
    }

    // A few shipped maps are broken; scouting the rest is still useful, so only a named map must load.
    return ( !mapFiles.empty() && failed > 0 ) ? EXIT_FAILURE : EXIT_SUCCESS;
}

int Game::RenderViews( const std::string & viewsFile, const std::string & outDir, const int width, const int height, const int frames )
{
    constexpr int32_t maxViewPx = 4096;

    if ( frames < 1 || width < TILE_WIDTH || height < TILE_WIDTH || width > maxViewPx || height > maxViewPx ) {
        ERROR_LOG( "Usage: --render-views <views file> <dir> <width 32-4096> <height 32-4096> <frames >= 1>" )
        return EXIT_FAILURE;
    }

    // One view per line: "<left tile> <top tile> <map file>", the tile being the top left corner of the rendered area.
    std::ifstream views( viewsFile );
    if ( !views ) {
        ERROR_LOG( "Could not read " << viewsFile )
        return EXIT_FAILURE;
    }

    fheroes2::Display & display = fheroes2::Display::instance();
    display.setResolution( { width, height, width, height } );
    Interface::GameArea & gameArea = Interface::AdventureMap::Get().getGameArea();

    std::string line;
    std::string loadedMap;
    for ( int i = 0; std::getline( views, line ); ++i ) {
        std::istringstream fields( line );
        int32_t x = -1;
        int32_t y = -1;
        std::string mapFile;
        fields >> x >> y >> std::ws;
        std::getline( fields, mapFile );
        if ( fields.fail() || mapFile.empty() ) {
            ERROR_LOG( "Bad view line " << i + 1 << ": " << line )
            return EXIT_FAILURE;
        }

        if ( mapFile != loadedMap ) {
            Maps::FileInfo info;
            if ( !info.readMP2Map( mapFile, false ) || !loadMap( info, true ) ) {
                ERROR_LOG( "Could not load map " << mapFile )
                return EXIT_FAILURE;
            }
            loadedMap = mapFile;
        }

        // The pan must never show the area outside the map.
        if ( x < 0 || y < 0 || x * TILE_WIDTH + width > world.w() * TILE_WIDTH || y * TILE_WIDTH + height > world.h() * TILE_WIDTH ) {
            ERROR_LOG( "View " << x << " " << y << " does not fit the " << world.w() << "x" << world.h() << " map " << mapFile )
            return EXIT_FAILURE;
        }

        gameArea.SetCenterInPixels( { x * TILE_WIDTH + width / 2, y * TILE_WIDTH + height / 2 } );

        const std::optional<std::string> dir = saveView( outDir, i, frames );
        if ( !dir.has_value() ) {
            return EXIT_FAILURE;
        }
        std::ofstream( System::concatPath( *dir, "view.txt" ) ) << x << ' ' << y << '\n';
    }

    return EXIT_SUCCESS;
}

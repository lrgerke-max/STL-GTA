import pygame
import sys
import os
import json
import math
import random

# ============================================================
# STL-GTA: a gritty, top-down, GTA1-style driving sandbox
# set in a stylized St. Louis. Rendered at a chunky internal
# resolution and upscaled 2x for that classic 256-color PS1 feel.
# ============================================================

# --- Render / window constants ---
# The game draws to a low-res internal buffer (chunky pixels = 1997),
# then nearest-neighbour-upscales to the real window so it stays retro.
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
SCREEN_WIDTH = 640          # internal render buffer width
SCREEN_HEIGHT = 360         # internal render buffer height
SCALE_FACTOR = 2
FPS = 60

TILE_SIZE = 64
MAP_TILES_W = 100
MAP_TILES_H = 100
MAP_WIDTH = MAP_TILES_W * TILE_SIZE
MAP_HEIGHT = MAP_TILES_H * TILE_SIZE

PLAYER_SIZE = 28
PLAYER_SPEED = 4.2

# Sprite draw scale. Purely cosmetic: collision rects stay 34x18 (car) and
# 14x14 (ped) so physics and collisions are untouched. Cars read at ~5.3% of
# screen width at 1.0, but a 320x256 PS1 view reads a car at ~7.5%, so the
# sprites are drawn slightly over their collider to match that.
SPRITE_SCALE_CAR = 1.30
# Peds are authored at 13x13, already sized for the 14x14 collision rect.
# Any non-integer scale (13 -> 16) doubles some pixel rows and not others,
# which breaks the uniform chunky-pixel look, so they ship unscaled.
SPRITE_SCALE_PED = 1.0
SHADOW_DX = 3               # southeast, matching the building shadows
SHADOW_DY = 3

PARKED_CAR_COUNT = 22       # kerbside cars available to steal
MOVING_CAR_COUNT = 8        # ambient traffic actually in motion

# Ambient traffic used to run at the player's own 9.5 top speed on a 0.55
# throttle, so it was uncatchable on foot (PLAYER_SPEED is 4.2). Traffic speed
# and lane discipline now live in the traffic_ai section, which owns the
# tuning constants; wander_ai below is kept only as a fallback.
PLAYER_CAR_MAX_SPEED = 9.5
ROAD_LINES = set(range(4, MAP_TILES_W, 8))

RADAR_SIZE = 78             # smaller than the old 110px minimap, GTA1 proportions
STAR_BLOCK_W = 76           # width of the 6-slot wanted star row

# --- Tile types ---
TILE_GRASS = 0
TILE_ROAD = 1
TILE_WATER = 2
TILE_BUILDING = 3
TILE_PARK = 4
TILE_PLAZA = 5              # walkable landmark ground: plazas, alleys, concourses

# --- Urban palette: gritty 90s-console St. Louis. Aged asphalt and grime,
#     but brick-forward and a stop brighter than pure GTA1 monochrome so the
#     sidewalk grid and red-brick fabric actually read (ref: sprite sheets). ---
COLOR_SKY_BG = (12, 12, 16)          # near-black void behind the map
COLOR_GRASS = (86, 102, 60)          # city grass, a touch greener
COLOR_GRASS_DARK = (72, 88, 52)      # mottled patch
COLOR_ROAD = (58, 58, 62)            # asphalt, lifted off black
COLOR_ROAD_DARK = (46, 46, 50)       # tire-grime streak
COLOR_ROAD_LIGHT = (70, 70, 74)      # worn patch
COLOR_ROAD_LINE = (204, 180, 84)     # faded yellow centre line
COLOR_ROAD_LINE_WHITE = (172, 168, 156)
COLOR_CRACK = (30, 30, 34)
COLOR_SIDEWALK = (150, 144, 132)     # pale concrete, reads as a real kerb grid
COLOR_SIDEWALK_SEAM = (118, 112, 102)
COLOR_CROSSWALK = (200, 195, 182)
COLOR_WATER = (44, 66, 90)           # Mississippi, murky blue-grey
COLOR_WATER_LINE = (74, 104, 128)    # ripple highlight
COLOR_WATER_DARK = (32, 50, 70)
COLOR_PARK = (80, 106, 56)
COLOR_PARK_DARK = (68, 94, 50)
COLOR_PARK_TREE = (50, 78, 42)
COLOR_PLAZA_SEAM = (104, 100, 94)    # paving joints on landmark ground
COLOR_TREE_SHADOW = (16, 22, 14)
COLOR_OUTLINE = (18, 16, 18)
COLOR_BUILDING_WALL = (46, 34, 34)   # warm brick-shadow on exposed side walls
COLOR_SHADOW = (0, 0, 0)
COLOR_LOT = (74, 74, 78)             # surface parking / vacant asphalt

# St. Louis is a brick city: red, brown, buff and limestone masonry. Block
# fabric picks from these deterministically so neighbourhoods vary but never
# flicker. Kept muted enough to sit under the grime pass.
CITY_BRICKS = [
    (156, 86, 66),      # classic STL red brick
    (134, 72, 56),      # darker red brick
    (170, 132, 98),     # buff / tan brick
    (120, 92, 74),      # brown brick
    (176, 168, 150),    # grey limestone
    (150, 104, 78),     # orange-brown brick
    (110, 98, 96),      # weathered painted masonry
]

# Storefront awnings on the hybrid facades: muted shop colours.
_AWNING_COLORS = [
    (150, 66, 58), (74, 104, 92), (72, 92, 128), (170, 132, 70),
    (110, 78, 120), (86, 110, 76),
]
# Landmark districts whose street level should always read as shopfronts.
_COMMERCIAL_LANDMARKS = {
    "Delmar Loop", "Grand Center Arts District", "Central West End",
    "The Hill", "Downtown & Busch Stadium",
}

PLAYER_COLOR = (206, 92, 110)
POLICE_COLOR = (46, 64, 152)
# Muted 90s console body paint - dirty primaries, nothing saturated.
CAR_COLORS = [
    (150, 62, 52),      # rust red
    (108, 112, 68),     # dull olive
    (74, 100, 132),     # faded blue
    (198, 188, 152),    # cream
    (114, 86, 62),      # brown
    (98, 116, 106),     # grey-green
    (118, 56, 66),      # maroon
    (60, 68, 82),       # slate
]

# --- Landmarks: real St. Louis places, spread across the world grid ---
# (x_tile, y_tile, w_tiles, h_tiles, kind, name, color)
LANDMARK_OPEN_GROUND = {"Gateway Arch"}

# Positions trace the real St. Louis map (north = up, Mississippi on the east
# edge): the Arch on the riverfront with downtown and the ballpark just inland,
# Soulard and the brewery south of downtown by the river, a midtown spine
# (Grand Center -> Central West End) running west to Forest Park, the Delmar
# Loop up in the north-west, and the south-city parks (The Hill, Tower Grove)
# down in the south. Compressed and not to scale, but recognisable in the hand.
LANDMARKS = [
    # --- East: the river, the Arch, downtown, the ballpark ---
    (87, 42, 9, 12, "building", "Gateway Arch", (170, 172, 168)),
    (71, 41, 13, 12, "building", "Downtown & Busch Stadium", (118, 108, 122)),
    (73, 60, 11, 10, "building", "Soulard & Anheuser-Busch", (150, 92, 58)),
    # --- Midtown spine, running west from downtown ---
    (50, 40, 9, 9, "building", "Grand Center Arts District", (108, 78, 136)),
    (30, 28, 9, 10, "building", "Central West End", (96, 104, 132)),
    (5, 30, 22, 22, "park", "Forest Park", COLOR_PARK),
    # --- North-west ---
    (9, 8, 15, 6, "building", "Delmar Loop", (150, 84, 76)),
    # --- South city ---
    (28, 60, 9, 8, "building", "The Hill", (156, 108, 66)),
    (42, 63, 14, 13, "park", "Tower Grove Park", COLOR_PARK),
]

CIVILIAN_VARIANTS = ['sedan', 'coupe', 'van', 'pickup', 'taxi']

# What ambient traffic / parked cars roll from. The St. Louis service vehicles
# (a City refuse truck, a box truck, a school bus, a Hill delivery scooter) are
# in the mix but rare, so the streets still read as mostly ordinary cars.
CIVILIAN_WEIGHTED = (['sedan'] * 6 + ['coupe'] * 4 + ['van'] * 3 + ['pickup'] * 3
                     + ['taxi'] * 2 + ['box_truck'] * 2 + ['vespa'] * 2
                     + ['bus'] * 1 + ['garbage_truck'] * 1)

# Per-variant handling + collider size. Anything absent uses the car defaults
# (34x18, max_steer 0.045, speed_factor 1.0). speed_factor scales traffic pace.
VEHICLE_TUNING = {
    'garbage_truck': dict(w=42, h=18, acceleration=0.15, max_steer=0.034, speed_factor=0.66),
    'bus':           dict(w=44, h=18, acceleration=0.17, max_steer=0.032, speed_factor=0.72),
    'box_truck':     dict(w=38, h=18, acceleration=0.20, max_steer=0.038, speed_factor=0.85),
    'vespa':         dict(w=16, h=12, acceleration=0.42, max_steer=0.060, speed_factor=1.08),
}

# (variant, colour) -> ([sprite] * 24, [shadow] * 24), filled by bake_car_sprites().
CAR_SPRITES = {}


def _scale_frames(frames, factor):
    """Nearest-neighbour upscale so the baked pixels stay hard."""
    if factor == 1.0:
        return frames
    out = []
    for f in frames:
        w, h = f.get_size()
        out.append(pygame.transform.scale(f, (max(1, int(round(w * factor))),
                                              max(1, int(round(h * factor))))))
    return out


def bake_car_sprites():
    """Bake every (variant, colour) pair once.

    Must run after pygame.display.set_mode so convert_alpha() has a display to
    convert against, and must be eager rather than lazy: Car.draw early-returns
    off-screen, so a lazy cache would hitch as new colours drive into view.
    """
    global CAR_SPRITES
    if CAR_SPRITES:
        return
    sets = {}
    for variant in CIVILIAN_VARIANTS:
        # taxi carries a fixed livery, so one bake covers every colour slot
        colors = [None] if variant == 'taxi' else CAR_COLORS
        for col in colors:
            frames = _scale_frames(cars_bake_variant(variant, col), SPRITE_SCALE_CAR)
            entry = (frames, [cars_make_shadow(f) for f in frames])
            if col is None:
                for c in CAR_COLORS:
                    sets[(variant, c)] = entry
            else:
                sets[(variant, col)] = entry
    for variant in cars_POLICE_FLASH_SETS:
        frames = _scale_frames(cars_bake_variant(variant), SPRITE_SCALE_CAR)
        entry = (frames, [cars_make_shadow(f) for f in frames])
        for c in CAR_COLORS + [POLICE_COLOR]:
            sets[(variant, c)] = entry
    # St. Louis service vehicles: fixed liveries, so one bake covers every
    # colour slot the spawner might ask for (same trick as the taxi).
    for variant in ('garbage_truck', 'bus', 'box_truck', 'vespa'):
        frames = _scale_frames(cars_bake_variant(variant), SPRITE_SCALE_CAR)
        entry = (frames, [cars_make_shadow(f) for f in frames])
        for c in CAR_COLORS:
            sets[(variant, c)] = entry
    CAR_SPRITES = sets


PED_SPRITES = {}


def bake_ped_sprites():
    """Bake the walk/idle sheets and their shadows once, after set_mode."""
    global PED_SPRITES
    if PED_SPRITES:
        return
    dog_bake()
    atlas = peds_bake_all()
    out = {}
    for pal, sets in atlas.items():
        walk = [_scale_frames(sets['walk'][d], SPRITE_SCALE_PED) for d in range(peds_DIRS)]
        idle = _scale_frames(sets['idle'], SPRITE_SCALE_PED)
        out[pal] = {
            'walk': walk,
            'idle': idle,
            'walk_sh': [[peds_make_shadow(f) for f in row] for row in walk],
            'idle_sh': [peds_make_shadow(f) for f in idle],
        }
    PED_SPRITES = out


def ped_sprite(palette, facing, moving, anim):
    """Pick the (sprite, shadow) pair for a pedestrian's current step."""
    sets = PED_SPRITES.get(palette) or PED_SPRITES[next(iter(PED_SPRITES))]
    d = facing % peds_DIRS
    if not moving:
        return sets['idle'][d], sets['idle_sh'][d]
    f = int(anim) % peds_WALK_FRAMES
    return sets['walk'][d][f], sets['walk_sh'][d][f]


POLICE_STATION_TILE = (64, 46)   # downtown, just west of the ballpark district


def _hash2(a, b, salt=0):
    """Order-stable deterministic hash for map generation (no random module)."""
    n = (a * 73856093) ^ (b * 19349663) ^ (salt * 83492791)
    n &= 0x7fffffff
    n = ((n * 1103515245) >> 13) & 0x7fffffff
    return n


# --- City block fabric ----------------------------------------------------
# The road grid is range(4, W, 8), so each block is the 7x7 span of tiles
# between two road lines. Every such block gets a deterministic character so
# the world reads as a dense brick city instead of empty lawn.
BLOCK_BUILT = 0
BLOCK_PARK = 1
BLOCK_LOT = 2


def _block_kind(bx, by):
    h = _hash2(bx, by, 4242) % 100
    if h < 9:
        return BLOCK_PARK
    if h < 16:
        return BLOCK_LOT
    return BLOCK_BUILT


def _block_brick(bx, by):
    return CITY_BRICKS[_hash2(bx, by, 99) % len(CITY_BRICKS)]


def _fill_city_blocks(game_map):
    """Stamp buildings / parks / lots into every grass block between roads.

    Runs before the landmark pass so landmarks cleanly overwrite the fabric.
    Leaves a one-tile walkable sidewalk ring inside each built block and an
    occasional mid-block alley, so peds have somewhere to walk and blocks are
    not solid walls.
    """
    for by, top in enumerate(range(5, MAP_TILES_H, 8)):
        for bx, left in enumerate(range(5, MAP_TILES_W, 8)):
            kind = _block_kind(bx, by)
            brick = _block_brick(bx, by)
            alley_col = 3 if (_hash2(bx, by, 7) & 1) else -1
            alley_row = 3 if (_hash2(bx, by, 13) & 1) else -1
            courtyard = _hash2(bx, by, 21) % 5 == 0
            for j in range(7):
                for i in range(7):
                    x, y = left + i, top + j
                    if not (0 <= x < MAP_TILES_W and 0 <= y < MAP_TILES_H):
                        continue
                    if game_map[y][x]['type'] != TILE_GRASS:
                        continue                       # road, water or already built
                    # Sidewalk only on the north & west faces; the south & east
                    # faces borrow the neighbouring road's own apron.
                    walk = i == 0 or j == 0 or i == alley_col or j == alley_row
                    if kind == BLOCK_PARK:
                        game_map[y][x] = {'type': TILE_PARK, 'collidable': False,
                                          'landmark': None, 'color': COLOR_PARK}
                    elif kind == BLOCK_LOT:
                        game_map[y][x] = {'type': TILE_PLAZA, 'collidable': False,
                                          'landmark': None, 'color': COLOR_LOT}
                    elif walk or (courtyard and 2 <= i <= 4 and 2 <= j <= 4):
                        game_map[y][x] = {'type': TILE_PLAZA, 'collidable': False,
                                          'landmark': None, 'color': COLOR_SIDEWALK}
                    else:
                        game_map[y][x] = {'type': TILE_BUILDING, 'collidable': True,
                                          'landmark': None, 'color': brick}


def build_map():
    """Generate the tile grid: roads on a grid, river along the east edge,
    a dense brick block fabric between the roads, landmarks stamped on top."""
    game_map = [[None] * MAP_TILES_W for _ in range(MAP_TILES_H)]
    road_lines = set(range(4, MAP_TILES_W, 8))

    for y in range(MAP_TILES_H):
        for x in range(MAP_TILES_W):
            if x in road_lines or y in road_lines:
                tile = {'type': TILE_ROAD, 'collidable': False, 'landmark': None, 'color': COLOR_ROAD}
            elif x >= MAP_TILES_W - 3:
                tile = {'type': TILE_WATER, 'collidable': True, 'landmark': None, 'color': COLOR_WATER}
            else:
                tile = {'type': TILE_GRASS, 'collidable': False, 'landmark': None, 'color': COLOR_GRASS}
            game_map[y][x] = tile

    _fill_city_blocks(game_map)

    for (lx, ly, lw, lh, kind, name, color) in LANDMARKS:
        for y in range(ly, min(ly + lh, MAP_TILES_H)):
            for x in range(lx, min(lx + lw, MAP_TILES_W)):
                game_map[y][x] = _landmark_tile(x - lx, y - ly, lw, lh, kind, name, color)
    return game_map


def _blend(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _landmark_tile(lx, ly, lw, lh, kind, name, color):
    """Build one tile of a landmark.

    Landmarks used to be solid rectangles, which walled them off completely:
    landmark_at() reads the tile under the player's centre, so a fully
    collidable footprint made every building landmark impossible to reach or
    discover. Now the footprint is mostly walkable ground with structures
    standing in it, and the outer ring is always open so you can walk in.
    """
    if kind == "park":
        return {'type': TILE_PARK, 'collidable': False, 'landmark': name, 'color': color}

    perimeter = lx == 0 or ly == 0 or lx == lw - 1 or ly == lh - 1
    if name in LANDMARK_OPEN_GROUND:
        # open monument grounds: only a small central structure is solid
        solid = lx == lw // 2 and abs(ly - lh // 2) <= 1
    else:
        # city district: 2x2 blocks of buildings separated by walkable alleys
        solid = (not perimeter) and (lx % 3 != 0) and (ly % 3 != 0)

    if solid:
        return {'type': TILE_BUILDING, 'collidable': True, 'landmark': name, 'color': color}
    return {'type': TILE_PLAZA, 'collidable': False, 'landmark': name,
            'color': _blend(color, COLOR_SIDEWALK, 0.55)}


GAME_MAP = build_map()


def tile_at(col, row):
    if 0 <= row < MAP_TILES_H and 0 <= col < MAP_TILES_W:
        return GAME_MAP[row][col]
    return None


def tile_type_at(col, row):
    tile = tile_at(col, row)
    return tile['type'] if tile else None


def _noise(c, r, salt=0):
    """Deterministic pseudo-random hash so tile texturing never flickers
    between frames (draw() runs every frame)."""
    n = (c * 73856093) ^ (r * 19349663) ^ (salt * 83492791)
    n &= 0x7fffffff
    n = ((n * 1103515245) >> 16) & 0x7fffffff
    return n


def is_blocked(rect):
    """True if rect overlaps any collidable tile."""
    start_col = max(0, rect.left // TILE_SIZE - 1)
    end_col = min(MAP_TILES_W - 1, rect.right // TILE_SIZE + 1)
    start_row = max(0, rect.top // TILE_SIZE - 1)
    end_row = min(MAP_TILES_H - 1, rect.bottom // TILE_SIZE + 1)
    for r in range(start_row, end_row + 1):
        for c in range(start_col, end_col + 1):
            tile = GAME_MAP[r][c]
            if tile['collidable']:
                tile_rect = pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                if rect.colliderect(tile_rect):
                    return True
    return False


def landmark_at(rect):
    col = rect.centerx // TILE_SIZE
    row = rect.centery // TILE_SIZE
    tile = tile_at(col, row)
    return tile['landmark'] if tile else None


def random_open_spawn(road_only=False):
    """Find a random walkable/drivable tile far from the map edge."""
    for _ in range(200):
        c = random.randint(5, MAP_TILES_W - 6)
        r = random.randint(5, MAP_TILES_H - 6)
        tile = GAME_MAP[r][c]
        if road_only and tile['type'] != TILE_ROAD:
            continue
        if not road_only and tile['collidable']:
            continue
        return c * TILE_SIZE + TILE_SIZE // 2, r * TILE_SIZE + TILE_SIZE // 2
    return MAP_WIDTH // 2, MAP_HEIGHT // 2




# ==========================================================
# Baked art: gfx_fx
# ==========================================================
"""Shared gritty PS1-era palette helpers and cheap post-processing for the
top-down GTA1-style game.

Only depends on pygame and math. No file I/O, no assets, no display init here.
"""




# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
# Muted, dirty 1997-console urban colours. Grouped by role; index order is not
# meaningful, fx_nearest() does the lookup.

fx_GTA1_PALETTE = [
    # --- near-black outlines / shadow ---
    (8, 8, 10),
    (18, 18, 22),
    (28, 28, 32),

    # --- asphalt / road surface ---
    (38, 38, 42),
    (48, 48, 52),
    (58, 58, 62),
    (70, 70, 74),

    # --- dirty concrete / sidewalk / kerb ---
    (84, 84, 86),
    (98, 96, 92),
    (112, 110, 104),
    (128, 125, 116),
    (146, 142, 132),

    # --- road markings ---
    (168, 148, 56),    # faded road-line yellow
    (196, 178, 78),    # brighter worn yellow
    (186, 186, 178),   # dirty white line
    (214, 212, 202),   # fresher white line

    # --- river / murky water ---
    (28, 40, 36),
    (40, 56, 48),
    (56, 72, 58),      # green-brown Mississippi
    (72, 84, 64),

    # --- city grass / dry parkland ---
    (46, 62, 34),
    (62, 80, 42),
    (84, 96, 50),
    (106, 112, 62),    # sun-dried grass

    # --- brick / masonry ---
    (72, 38, 32),
    (96, 50, 40),
    (122, 64, 50),     # brick red
    (140, 86, 66),
    (110, 88, 70),     # brown stone
    (138, 116, 92),    # sandstone

    # --- muted car body colours ---
    (118, 44, 36),     # rust red
    (150, 58, 44),     # faded red
    (92, 32, 44),      # maroon
    (86, 92, 52),      # dull olive
    (60, 76, 60),      # dark green
    (52, 74, 100),     # faded blue
    (76, 104, 132),    # dusty steel blue
    (34, 46, 66),      # midnight navy
    (196, 186, 152),   # cream
    (224, 220, 208),   # off-white
    (104, 76, 48),     # brown
    (150, 118, 60),    # tan / beige
    (60, 60, 66),      # charcoal
    (158, 156, 154),   # dull silver

    # --- skin tones, light to dark ---
    (232, 200, 176),
    (208, 170, 140),
    (180, 138, 106),
    (146, 104, 76),
    (108, 74, 52),
    (72, 48, 34),

    # --- HUD ---
    (212, 172, 48),    # HUD gold
    (240, 208, 92),    # HUD gold highlight
    (72, 176, 88),     # HUD green (health)
    (156, 220, 120),   # HUD green highlight
    (186, 48, 40),     # HUD red (damage / wanted)
    (232, 96, 72),     # HUD red highlight
    (36, 32, 28),      # HUD panel backing
]


fx__nearest_cache = {}


def fx_nearest(rgb):
    """Snap an arbitrary colour to the closest fx_GTA1_PALETTE entry."""
    key = (rgb[0], rgb[1], rgb[2])
    hit = fx__nearest_cache.get(key)
    if hit is not None:
        return hit
    r, g, b = key
    best = fx_GTA1_PALETTE[0]
    best_d = 1 << 30
    for pr, pg, pb in fx_GTA1_PALETTE:
        dr = r - pr
        dg = g - pg
        db = b - pb
        d = dr * dr + dg * dg + db * db
        if d < best_d:
            best_d = d
            best = (pr, pg, pb)
    fx__nearest_cache[key] = best
    return best


def fx__clamp255(v):
    if v < 0:
        return 0
    if v > 255:
        return 255
    return int(v)


def fx_shade(rgb, factor):
    """Multiply brightness by factor, clamped to 0-255, ints out."""
    return (
        fx__clamp255(rgb[0] * factor),
        fx__clamp255(rgb[1] * factor),
        fx__clamp255(rgb[2] * factor),
    )


def fx_tint(rgb, other, t):
    """Linear blend from rgb (t=0) to other (t=1)."""
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return (
        fx__clamp255(rgb[0] + (other[0] - rgb[0]) * t),
        fx__clamp255(rgb[1] + (other[1] - rgb[1]) * t),
        fx__clamp255(rgb[2] + (other[2] - rgb[2]) * t),
    )


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def fx__fast_alpha(surf):
    """convert_alpha() when a display mode exists, otherwise leave as-is."""
    try:
        return surf.convert_alpha()
    except pygame.error:
        return surf


class fx_PostFX:
    """Optional CRT-ish post effects applied at the upscale step.

    All overlays are built once at construction and only blitted per frame, so
    present() allocates nothing and runs no Python per-pixel loops.
    """

    SCANLINE_ALPHA = 48      # per spec: roughly 40-55
    VIGNETTE_MAX_ALPHA = 96  # darkest corner alpha
    EDGE_ALPHA = 40          # subtle edge darkening baked into the vignette

    def __init__(self, w, h, scale):
        self.w = w
        self.h = h
        self.scale = scale
        self.out_w = int(w * scale)
        self.out_h = int(h * scale)

        self.scanlines_on = False
        self.vignette_on = False

        self._scanlines = self._build_scanlines(self.out_w, self.out_h)
        self._vignette = self._build_vignette(self.out_w, self.out_h)

        # Cached destination size so present() can detect a window that is not
        # the assumed out_w/out_h and rebuild overlays once, not per frame.
        self._overlay_size = (self.out_w, self.out_h)

    # -- overlay construction ------------------------------------------------

    def _build_scanlines(self, w, h):
        """One dark horizontal line every 2 output pixels."""
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        line = (0, 0, 0, self.SCANLINE_ALPHA)
        for y in range(0, h, 2):
            pygame.draw.line(surf, line, (0, y), (w - 1, y))
        return fx__fast_alpha(surf)

    def _build_vignette(self, w, h):
        """Coarse per-cell darkening toward the corners and edges.

        16x16 px cells over 1280x720 is 80x45 = 3600 fills, cheap and smooth
        enough at this alpha range.
        """
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))

        cell = 16
        cx = w * 0.5
        cy = h * 0.5
        # Normalise radius so the corner sits at 1.0.
        max_r = math.hypot(cx, cy)
        inner = 0.45   # no darkening inside this normalised radius
        span = 1.0 - inner
        peak = self.VIGNETTE_MAX_ALPHA

        fill = surf.fill
        for y in range(0, h, cell):
            ch = cell if y + cell <= h else h - y
            dy = (y + ch * 0.5) - cy
            dy2 = dy * dy
            for x in range(0, w, cell):
                cw = cell if x + cell <= w else w - x
                dx = (x + cw * 0.5) - cx
                r = math.sqrt(dx * dx + dy2) / max_r
                if r <= inner:
                    continue
                t = (r - inner) / span
                if t > 1.0:
                    t = 1.0
                a = int(peak * t * t)  # quadratic falloff, soft shoulder
                if a > 0:
                    fill((0, 0, 0, a), (x, y, cw, ch))

        # Free extra: a few nested rects so the very border darkens a touch
        # more. Drawn into a scratch surface then merged with BLEND_RGBA_MAX so
        # it can only ever deepen the vignette, never punch a lighter hole in
        # the corners. Baked in at construction, so it costs nothing per frame.
        edge = pygame.Surface((w, h), pygame.SRCALPHA)
        edge.fill((0, 0, 0, 0))
        edge_step = max(2, min(w, h) // 90)
        for i in range(3):
            a = int(self.EDGE_ALPHA * (3 - i) / 3)
            if a <= 0:
                continue
            inset = i * edge_step
            rect = pygame.Rect(inset, inset, w - inset * 2, h - inset * 2)
            pygame.draw.rect(edge, (0, 0, 0, a), rect, edge_step)
        surf.blit(edge, (0, 0), special_flags=pygame.BLEND_RGBA_MAX)

        return fx__fast_alpha(surf)

    # -- state ---------------------------------------------------------------

    def set_scanlines(self, on):
        self.scanlines_on = bool(on)

    def set_vignette(self, on):
        self.vignette_on = bool(on)

    def toggle(self):
        """off -> scanlines -> scanlines+vignette -> off."""
        if not self.scanlines_on and not self.vignette_on:
            self.scanlines_on = True
            self.vignette_on = False
        elif self.scanlines_on and not self.vignette_on:
            self.vignette_on = True
        else:
            self.scanlines_on = False
            self.vignette_on = False
        return (self.scanlines_on, self.vignette_on)

    def is_off(self):
        return not self.scanlines_on and not self.vignette_on

    # -- per-frame -----------------------------------------------------------

    def present(self, src_surface, dest_window):
        """Upscale src into dest_window, then blit any enabled overlays."""
        size = dest_window.get_size()
        pygame.transform.scale(src_surface, size, dest_window)

        if not self.scanlines_on and not self.vignette_on:
            return  # identical to the plain scale path, zero extra cost

        if size != self._overlay_size:
            # Window changed size: rebuild once, not per frame.
            self._scanlines = self._build_scanlines(size[0], size[1])
            self._vignette = self._build_vignette(size[0], size[1])
            self._overlay_size = size

        if self.scanlines_on:
            dest_window.blit(self._scanlines, (0, 0))
        if self.vignette_on:
            dest_window.blit(self._vignette, (0, 0))
        return


# ==========================================================
# Baked art: gfx_cars
# ==========================================================
"""Pre-baked top-down pixel-art car sprites for a 640x360 GTA1-style renderer.

Cars are authored once as chunky 1x pixel art facing east (+X), scaled up by an
integer supersample factor, rotated with the unfiltered pygame.transform.rotate,
then scaled back down with pygame.transform.scale (also unfiltered).  Nothing is
smoothed or antialiased, so the result stays hard-edged at a 2x upscale.

Public API
    cars_ANGLE_STEPS
    cars_VARIANTS
    cars_ALL_SETS
    cars_BODY_COLORS
    cars_bake_all()
    cars_bake_variant(name, body_color=None)
    cars_angle_index(radians)
    cars_police_lightbar_overlay(angle_idx, phase)
    cars_make_shadow(surface)
"""




cars_ANGLE_STEPS = 24

cars__SS = 8        # supersample factor used only during rotation
cars__MARGIN = 2    # transparent pixels kept around every baked sprite

# --- palette -----------------------------------------------------------------
cars_OUTLINE = (18, 16, 18)
cars_GLASS_FRONT = (150, 168, 190)
cars_GLASS_REAR = (124, 142, 164)
cars_TIRE = (28, 26, 30)
cars_HEADLIGHT = (255, 234, 172)
cars_TAILLIGHT = (178, 48, 42)

cars_LIGHTBAR_OFF = (84, 84, 92)
cars_LIGHTBAR_RED = (198, 46, 42)
cars_LIGHTBAR_BLUE = (58, 94, 196)

cars_TAXI_BODY = (196, 158, 46)
cars_TAXI_SIGN = (44, 40, 38)
cars_TAXI_SIGN_LIT = (222, 206, 148)

cars_POLICE_BODY = (44, 46, 52)
cars_POLICE_DOOR = (214, 214, 206)

cars_SHADOW_ALPHA = 115  # 45% of 255

# Muted 90s console car colours (no saturated primaries).
cars_BODY_COLORS = [
    (138, 62, 48),    # rust red
    (104, 106, 62),   # dull olive
    (72, 96, 122),    # faded blue
    (204, 192, 158),  # cream
    (110, 84, 60),    # brown
    (92, 108, 96),    # grey-green
    (104, 46, 54),    # maroon
    (198, 198, 190),  # off-white
]

# --- variants ----------------------------------------------------------------
# L/H are the full sprite footprint in game pixels (wheel nubs included).
# hood/ws/roof/rw are x-lengths measured from the nose backwards; the trunk (or
# pickup bed) gets whatever length is left over.
cars__SPECS = {
    'sedan':  dict(L=34, H=18, nose=2, tail=1, hood=8, ws=4, roof=7, rw=4,
                   win_inset=4, wheel_len=5, axle_f=5, axle_r=5),
    'coupe':  dict(L=30, H=18, nose=2, tail=2, hood=8, ws=4, roof=5, rw=3,
                   win_inset=4, wheel_len=5, axle_f=4, axle_r=4),
    'van':    dict(L=40, H=20, nose=1, tail=1, hood=4, ws=4, roof=23, rw=3,
                   win_inset=4, wheel_len=5, axle_f=5, axle_r=4, seam=True),
    'pickup': dict(L=38, H=19, nose=1, tail=1, hood=8, ws=4, roof=6, rw=3,
                   win_inset=4, wheel_len=5, axle_f=5, axle_r=4, bed=True),
    'taxi':   dict(L=34, H=18, nose=2, tail=1, hood=8, ws=4, roof=7, rw=4,
                   win_inset=4, wheel_len=5, axle_f=5, axle_r=5, taxi=True),
    'police': dict(L=35, H=18, nose=2, tail=1, hood=8, ws=4, roof=8, rw=4,
                   win_inset=4, wheel_len=5, axle_f=5, axle_r=5, police=True),
}

cars_VARIANTS = ['sedan', 'coupe', 'van', 'pickup', 'taxi', 'police']

# Extra pre-lit police sets; cars_bake_all() returns these too but they are not
# meant to be picked as a random traffic car.
cars_POLICE_FLASH_SETS = ['police_flash_a', 'police_flash_b']
cars_ALL_SETS = cars_VARIANTS + cars_POLICE_FLASH_SETS

# Default paint per variant (cars_bake_variant() takes an explicit colour instead).
cars__DEFAULT_COLOR = {
    'sedan': cars_BODY_COLORS[2],
    'coupe': cars_BODY_COLORS[0],
    'van': cars_BODY_COLORS[3],
    'pickup': cars_BODY_COLORS[1],
    'taxi': cars_TAXI_BODY,
    'police': cars_POLICE_BODY,
}

cars__CACHE = None            # {set_name: [Surface] * cars_ANGLE_STEPS}
cars__OVERLAY_CACHE = None    # {phase: [Surface] * cars_ANGLE_STEPS}


# --- small colour helpers ----------------------------------------------------
def cars__mix(c, other, t):
    return (int(c[0] + (other[0] - c[0]) * t),
            int(c[1] + (other[1] - c[1]) * t),
            int(c[2] + (other[2] - c[2]) * t))


def cars__lighter(c):
    return cars__mix(c, (255, 255, 255), 0.22)


def cars__darker(c, t=0.30):
    return cars__mix(c, (0, 0, 0), t)


def cars_random_body_color(rng=None):
    """Pick one of the muted body colours."""
    return (rng or random).choice(cars_BODY_COLORS)


# --- geometry ----------------------------------------------------------------
def cars__geom(spec):
    L = spec['L']
    H = spec['H']
    g = {'L': L, 'H': H, 'by0': 1, 'by1': H - 2}
    xf = L - 2                       # front-most interior column
    g['nose_x'] = xf
    g['ws_x1'] = xf - spec['hood']
    g['ws_x0'] = g['ws_x1'] - spec['ws'] + 1
    g['roof_x1'] = g['ws_x0'] - 1
    g['roof_x0'] = g['roof_x1'] - spec['roof'] + 1
    g['rwin_x1'] = g['roof_x0'] - 1
    g['rwin_x0'] = g['rwin_x1'] - spec['rw'] + 1
    g['trunk_x1'] = g['rwin_x0'] - 1
    g['trunk_x0'] = 1
    g['win_y0'] = g['by0'] + spec['win_inset']
    g['win_y1'] = g['by1'] - spec['win_inset']
    roof_cx = (g['roof_x0'] + g['roof_x1']) // 2
    g['bar_x0'] = roof_cx - 1
    g['bar_x1'] = roof_cx + 1
    g['bar_y0'] = g['by0'] + 2
    g['bar_y1'] = g['by1'] - 2
    return g


def cars__span(spec, y):
    """Horizontal body span (x0, x1) for a row, or None outside the body."""
    by0 = 1
    rows = spec['H'] - 2
    r = y - by0
    if r < 0 or r >= rows:
        return None
    d = min(r, rows - 1 - r)         # distance from the long edge
    f = 2 if d == 0 else (1 if d == 1 else 0)
    return (0 + spec['tail'] * f, spec['L'] - 1 - spec['nose'] * f)


def cars__put(grid, x, y, c):
    if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
        grid[y][x] = c


def cars__fill_rect(grid, x0, y0, x1, y1, c, inside_only=True):
    for y in range(y0, y1 + 1):
        if y < 0 or y >= len(grid):
            continue
        for x in range(x0, x1 + 1):
            if x < 0 or x >= len(grid[0]):
                continue
            if inside_only:
                cur = grid[y][x]
                if cur is None or cur == cars_OUTLINE:
                    continue
            grid[y][x] = c


# --- sprite construction -----------------------------------------------------
def cars__build_grid(spec, body):
    L = spec['L']
    H = spec['H']
    g = cars__geom(spec)
    grid = [[None] * L for _ in range(H)]

    # body fill
    for y in range(H):
        s = cars__span(spec, y)
        if s is None:
            continue
        for x in range(s[0], s[1] + 1):
            grid[y][x] = body

    # livery under the shading pass so the shading follows the paint
    if spec.get('police'):
        cars__fill_rect(grid, g['rwin_x0'], g['by0'] + 1,
                   g['ws_x1'], g['win_y0'] - 1, cars_POLICE_DOOR)
        cars__fill_rect(grid, g['rwin_x0'], g['win_y1'] + 1,
                   g['ws_x1'], g['by1'] - 1, cars_POLICE_DOOR)

    # 1px outline all the way round the silhouette
    for y in range(H):
        s = cars__span(spec, y)
        if s is None:
            continue
        grid[y][s[0]] = cars_OUTLINE
        grid[y][s[1]] = cars_OUTLINE
    for x in range(L):
        col = [y for y in range(H) if grid[y][x] is not None]
        if col:
            grid[col[0]][x] = cars_OUTLINE
            grid[col[-1]][x] = cars_OUTLINE

    # form: darker along the bottom/right, lighter along the top/left
    for y in range(H):
        for x in range(L):
            c = grid[y][x]
            if c is None or c == cars_OUTLINE:
                continue
            def edge(xx, yy):
                if yy < 0 or yy >= H or xx < 0 or xx >= L:
                    return True
                n = grid[yy][xx]
                return n is None or n == cars_OUTLINE
            if edge(x, y + 1) or edge(x + 1, y):
                grid[y][x] = cars__darker(c)
            elif edge(x, y - 1) or edge(x - 1, y):
                grid[y][x] = cars__lighter(c)

    # pickup bed: recessed dark floor with a rim
    if spec.get('bed'):
        bx0, bx1 = g['trunk_x0'] + 1, g['trunk_x1']
        by0, by1 = 3, H - 4
        cars__fill_rect(grid, bx0, by0, bx1, by1, cars__darker(body, 0.42))
        rim = cars__darker(body, 0.66)
        cars__fill_rect(grid, bx0, by0, bx1, by0, rim)
        cars__fill_rect(grid, bx0, by1, bx1, by1, rim)
        cars__fill_rect(grid, bx0, by0, bx0, by1, rim)
        cars__fill_rect(grid, bx1, by0, bx1, by1, rim)

    # van: door seam so the long roof is not one flat slab
    if spec.get('seam'):
        sx = (g['roof_x0'] + g['roof_x1']) // 2
        cars__fill_rect(grid, sx, g['by0'] + 1, sx, g['by1'] - 1,
                   cars__darker(body, 0.20))

    # glass
    cars__fill_rect(grid, g['ws_x0'], g['win_y0'], g['ws_x1'], g['win_y1'],
               cars_GLASS_FRONT)
    cars__fill_rect(grid, g['rwin_x0'], g['win_y0'] + 1,
               g['rwin_x1'], g['win_y1'] - 1, cars_GLASS_REAR)

    # roof furniture
    if spec.get('taxi'):
        cx = (g['roof_x0'] + g['roof_x1']) // 2
        cy = (g['by0'] + g['by1']) // 2
        cars__fill_rect(grid, cx - 1, cy - 2, cx + 1, cy + 2, cars_TAXI_SIGN)
        cars__fill_rect(grid, cx - 1, cy, cx + 1, cy, cars_TAXI_SIGN_LIT)
    if spec.get('police'):
        cars__draw_lightbar(grid, g, None)

    # wheel nubs poking out of both long sides
    fw1 = L - 1 - spec['axle_f']
    fw0 = fw1 - spec['wheel_len'] + 1
    rw0 = spec['axle_r']
    rw1 = rw0 + spec['wheel_len'] - 1
    for x0, x1 in ((fw0, fw1), (rw0, rw1)):
        for x in range(x0, x1 + 1):
            cars__put(grid, x, 0, cars_TIRE)
            cars__put(grid, x, H - 1, cars_TIRE)

    # head / tail lights, sitting just inside the outline
    for y in (3, 4, H - 5, H - 4):
        s = cars__span(spec, y)
        if s is None:
            continue
        cars__put(grid, s[1] - 1, y, cars_HEADLIGHT)
        cars__put(grid, s[1] - 2, y, cars_HEADLIGHT)
        cars__put(grid, s[0] + 1, y, cars_TAILLIGHT)
        cars__put(grid, s[0] + 2, y, cars_TAILLIGHT)

    return grid


# --------------------------------------------------------------------------
# Hand-built big vehicles + the scooter. These are not car-shaped, so they
# skip cars__SPECS / cars__span and lay pixels straight into an east-facing
# grid[y][x], then reuse the shared rotate + shadow pipeline.
# --------------------------------------------------------------------------
cars_BIG_SPECS = {
    'garbage_truck': (48, 22),
    'bus':           (54, 20),
    'box_truck':     (44, 20),
}


def cars__put_r(grid, x0, y0, x1, y1, c):
    H, L = len(grid), len(grid[0])
    for y in range(max(0, y0), min(H, y1 + 1)):
        for x in range(max(0, x0), min(L, x1 + 1)):
            grid[y][x] = c


def cars__outline_shade(grid):
    """1px near-black outline round any filled shape, then NW-light / SE-dark
    form shading -- the cheap version of cars__build_grid's passes for grids
    that were not built from a spec silhouette."""
    H, L = len(grid), len(grid[0])
    edge = []
    for y in range(H):
        for x in range(L):
            if grid[y][x] is not None:
                continue
            if any(0 <= x + dx < L and 0 <= y + dy < H
                   and grid[y + dy][x + dx] not in (None, cars_OUTLINE)
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                edge.append((x, y))
    for x, y in edge:
        grid[y][x] = cars_OUTLINE
    snap = [row[:] for row in grid]

    def bare(x, y):
        return (not (0 <= x < L and 0 <= y < H)
                or snap[y][x] is None or snap[y][x] == cars_OUTLINE)

    for y in range(H):
        for x in range(L):
            c = snap[y][x]
            if c is None or c == cars_OUTLINE:
                continue
            if bare(x, y + 1) or bare(x + 1, y):
                grid[y][x] = cars__darker(c, 0.24)
            elif bare(x, y - 1) or bare(x - 1, y):
                grid[y][x] = cars__lighter(c)


def cars_big_grid(kind):
    L, H = cars_BIG_SPECS[kind]
    grid = [[None] * L for _ in range(H)]
    top, bot = 1, H - 2                        # body sits between the wheel nubs

    if kind == 'garbage_truck':
        cab = (74, 108, 150)                   # St. Louis City blue cab
        box = (58, 120, 78)                    # green refuse body
        cars__put_r(grid, 2, top, 33, bot, box)
        for x in range(5, 33, 4):
            cars__put_r(grid, x, top + 1, x, bot - 1, cars__darker(box, 0.25))
        cars__put_r(grid, 1, top + 3, 3, bot - 3, cars__darker(box, 0.45))   # loader
        cars__put_r(grid, 34, top, 46, bot, cab)
        cars__put_r(grid, 44, top + 2, 45, bot - 2, cars_GLASS_FRONT)
        cars__put_r(grid, 36, top + 3, 39, bot - 3, (216, 216, 208))         # door
    elif kind == 'bus':
        body = (232, 182, 40)                  # school-bus yellow
        trim = (26, 26, 28)
        glass = (120, 150, 170)
        cars__put_r(grid, 2, top, L - 2, bot, body)
        cars__put_r(grid, 3, top, L - 7, top, trim)
        cars__put_r(grid, 3, bot, L - 7, bot, trim)
        for x in range(6, L - 10, 6):
            cars__put_r(grid, x, top + 1, x + 3, top + 2, glass)
            cars__put_r(grid, x, bot - 2, x + 3, bot - 1, glass)
        cars__put_r(grid, L - 6, top + 2, L - 3, bot - 2, cars_GLASS_FRONT)
        cars__put_r(grid, 1, top + 2, 2, bot - 2, trim)
    else:  # box_truck
        box = (210, 206, 198)
        cab = (108, 114, 124)
        cars__put_r(grid, 2, top, 32, bot, box)
        for x in range(6, 32, 6):
            cars__put_r(grid, x, top + 1, x, bot - 1, cars__darker(box, 0.12))
        cars__put_r(grid, 33, top + 1, 43, bot - 1, cab)
        cars__put_r(grid, 41, top + 2, 42, bot - 2, cars_GLASS_FRONT)

    for ax in (5, L - 10):                     # wheel nubs on both flanks
        for x in range(ax, ax + 5):
            grid[0][x] = cars_TIRE
            grid[H - 1][x] = cars_TIRE
    cars__put_r(grid, L - 3, top + 1, L - 2, top + 2, cars_HEADLIGHT)
    cars__put_r(grid, L - 3, bot - 2, L - 2, bot - 1, cars_HEADLIGHT)
    cars__put_r(grid, 2, top + 1, 3, top + 2, cars_TAILLIGHT)
    cars__put_r(grid, 2, bot - 2, 3, bot - 1, cars_TAILLIGHT)
    cars__outline_shade(grid)
    return grid


def cars_rail_sprite(kind):
    """One long east-facing light-rail / trolley surface. Rail vehicles only
    ever travel along their line, so there is no 24-angle bake -- just this and
    a horizontal flip for the westbound run."""
    if kind == 'metrolink':
        L, H, seg = 116, 16, 56
        body, band, glass = (56, 96, 150), (228, 198, 70), (150, 180, 200)
    else:  # trolley
        L, H, seg = 60, 15, 60
        body, band, glass = (150, 54, 48), (214, 200, 172), (150, 170, 190)
    grid = [[None] * L for _ in range(H)]
    top, bot = 1, H - 2
    cars__put_r(grid, 1, top, L - 2, bot, body)
    cars__put_r(grid, 1, H // 2, L - 2, H // 2, band)
    for x in range(4, L - 5, 8):
        cars__put_r(grid, x, top + 2, x + 4, top + 3, glass)
        cars__put_r(grid, x, bot - 3, x + 4, bot - 2, glass)
    for sx in range(seg, L - 4, seg):
        cars__put_r(grid, sx, top, sx, bot, cars_OUTLINE)
    cars__put_r(grid, L - 3, top + 2, L - 2, bot - 2, cars_HEADLIGHT)
    if kind == 'trolley':
        cars__put_r(grid, L // 2, 0, L // 2, top, (40, 40, 44))   # trolley pole
    cars__outline_shade(grid)
    return _scale_frames([cars__grid_to_surface(grid)], SPRITE_SCALE_CAR)[0]


def cars_scooter_grid():
    L, H = 18, 10
    grid = [[None] * L for _ in range(H)]
    body = (74, 132, 84)                       # Vespa green
    seat = (52, 48, 52)
    box = (156, 120, 80)                       # cardboard delivery box
    m0, m1 = 3, H - 4
    cars__put_r(grid, 4, m0, 13, m1, body)
    cars__put_r(grid, 12, m0 - 1, 15, m1 + 1, body)          # front cowl
    cars__put_r(grid, 5, m0 + 1, 8, m1 - 1, seat)
    cars__put_r(grid, 1, m0, 4, m1, box)                     # rear box
    cars__put_r(grid, 1, m0, 1, m1, cars__darker(box, 0.3))
    cars__put_r(grid, 15, H // 2 - 1, 15, H // 2, (60, 60, 68))   # rider / bars
    for ax in (3, 13):
        grid[m0 - 1][ax] = cars_TIRE
        grid[m1 + 1][ax] = cars_TIRE
    grid[H // 2][16] = cars_HEADLIGHT
    cars__outline_shade(grid)
    return grid


def cars__draw_lightbar(grid, g, phase):
    """Roof light bar.  phase None = unlit, 0 = left red / right blue, 1 = swap.

    'Left' is the car's left flank, which is the -Y (top) half of the
    east-facing base art since +Y points down on screen.
    """
    x0, x1 = g['bar_x0'], g['bar_x1']
    y0, y1 = g['bar_y0'], g['bar_y1']
    mid = (y0 + y1) // 2
    if phase is None:
        cars__fill_rect(grid, x0, y0, x1, y1, cars_LIGHTBAR_OFF, inside_only=False)
        cars__fill_rect(grid, x0, y1, x1, y1, cars__darker(cars_LIGHTBAR_OFF),
                   inside_only=False)
        return
    left = cars_LIGHTBAR_RED if phase == 0 else cars_LIGHTBAR_BLUE
    right = cars_LIGHTBAR_BLUE if phase == 0 else cars_LIGHTBAR_RED
    cars__fill_rect(grid, x0, y0, x1, mid, left, inside_only=False)
    cars__fill_rect(grid, x0, mid + 1, x1, y1, right, inside_only=False)


def cars__grid_to_surface(grid):
    h = len(grid)
    w = len(grid[0])
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 0))
    for y in range(h):
        row = grid[y]
        for x in range(w):
            c = row[x]
            if c is not None:
                surf.set_at((x, y), (c[0], c[1], c[2], 255))
    return surf


def cars__finish(surf):
    # convert_alpha only when a display exists; alpha stays hard either way.
    if pygame.display.get_init() and pygame.display.get_surface() is not None:
        try:
            return surf.convert_alpha()
        except pygame.error:
            return surf
    return surf


def cars__bake_angles(base):
    """Rotate one east-facing base sprite into cars_ANGLE_STEPS chunky sprites."""
    w, h = base.get_size()
    big = pygame.transform.scale(base, (w * cars__SS, h * cars__SS))
    out = []
    for i in range(cars_ANGLE_STEPS):
        deg = 360.0 * i / cars_ANGLE_STEPS
        # negative because pygame rotates counter-clockwise while our angles
        # grow clockwise on screen (+Y down).
        rot = pygame.transform.rotate(big, -deg)
        tw = max(1, int(math.floor(rot.get_width() / float(cars__SS) + 0.5)))
        th = max(1, int(math.floor(rot.get_height() / float(cars__SS) + 0.5)))
        small = pygame.transform.scale(rot, (tw, th))
        surf = pygame.Surface((tw + 2 * cars__MARGIN, th + 2 * cars__MARGIN),
                              pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        surf.blit(small, (cars__MARGIN, cars__MARGIN))
        out.append(cars__finish(surf))
    return out


# --- public API --------------------------------------------------------------
def cars_angle_index(radians):
    """Index 0..cars_ANGLE_STEPS-1; 0 = east, growing clockwise on screen."""
    step = (2.0 * math.pi) / cars_ANGLE_STEPS
    return int(math.floor(radians / step + 0.5)) % cars_ANGLE_STEPS


def cars_bake_variant(name, body_color=None):
    """Bake one variant into a list of cars_ANGLE_STEPS surfaces."""
    if name in cars_BIG_SPECS:
        return cars__bake_angles(cars__grid_to_surface(cars_big_grid(name)))
    if name == 'vespa':
        return cars__bake_angles(cars__grid_to_surface(cars_scooter_grid()))
    key = 'police' if name in cars_POLICE_FLASH_SETS else name
    spec = cars__SPECS[key]
    body = body_color or cars__DEFAULT_COLOR[key]
    if key in ('taxi', 'police'):
        body = cars__DEFAULT_COLOR[key]      # liveries keep their own paint
    grid = cars__build_grid(spec, body)
    if name in cars_POLICE_FLASH_SETS:
        cars__draw_lightbar(grid, cars__geom(spec), 0 if name.endswith('_a') else 1)
    return cars__bake_angles(cars__grid_to_surface(grid))


def cars__bake_overlays():
    spec = cars__SPECS['police']
    g = cars__geom(spec)
    sets = {}
    for phase in (0, 1):
        grid = [[None] * spec['L'] for _ in range(spec['H'])]
        cars__draw_lightbar(grid, g, phase)
        # Same base surface size as the police sprite, so rotation and the
        # nearest-neighbour downsample land the bar on exactly the same pixels.
        sets[phase] = cars__bake_angles(cars__grid_to_surface(grid))
    return sets


def cars_bake_all():
    """Bake every sprite set once.  {set_name: [Surface] * cars_ANGLE_STEPS}."""
    global cars__CACHE, cars__OVERLAY_CACHE
    if cars__CACHE is None:
        cars__CACHE = dict((name, cars_bake_variant(name)) for name in cars_ALL_SETS)
        cars__OVERLAY_CACHE = cars__bake_overlays()
    return cars__CACHE


def cars_police_lightbar_overlay(angle_idx, phase):
    """Transparent overlay holding only the roof light bar for that angle.

    Blit it over the 'police' sprite at the same centre.  phase 0 = left red /
    right blue, phase 1 = swapped.  Returns None for a bad index or phase.
    """
    if cars__OVERLAY_CACHE is None:
        cars_bake_all()
    if phase not in (0, 1):
        return None
    try:
        idx = int(angle_idx) % cars_ANGLE_STEPS
    except (TypeError, ValueError):
        return None
    return cars__OVERLAY_CACHE[phase][idx]


def cars_make_shadow(surface):
    """Hard-edged black silhouette at 45% alpha, for a southeast drop shadow."""
    if surface.get_flags() & pygame.SRCALPHA:
        sh = surface.copy()
    else:
        sh = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        sh.fill((0, 0, 0, 0))
        sh.blit(surface, (0, 0))
    # zero the RGB and scale the existing alpha down; no blur, no soft edge.
    sh.fill((0, 0, 0, cars_SHADOW_ALPHA), None, pygame.BLEND_RGBA_MULT)
    return sh


# ==========================================================
# Baked art: gfx_peds
# ==========================================================
"""Baked pixel-art pedestrians for the hybrid top-down / elevation look.

The camera is top-down, but people are read face-first the way the St. Louis
reference sheets draw them: small front / back / profile figures. Each
archetype (commuter, dog walker, sax busker, Cardinals player, hi-vis worker,
elder with a cane, ...) is a spec of clothing palette + accessories.
peds__figure() stamps head / torso / limbs as hard 1px rects with a 4-frame
walk swing; one surface is baked per (archetype-variant, direction, frame).
Diagonals reuse the profile view; the west-facing dirs are the east art
mirrored. No antialiasing, so it survives the 2x nearest upscale.

Public API
    peds_DIRS, peds_WALK_FRAMES
    peds_bake_all()      -> {key: {'walk': [dir][frame], 'idle': [dir]}}
    peds_random_archetype(include_cop=False) -> key str  (e.g. "commuter#2")
    peds_gait(key) -> float          speed multiplier for that archetype
    peds_has_dog(key) -> bool
    peds_dir_index(dx, dy) / peds_dir_index_from_angle(radians) -> 0..7
    peds_make_shadow(surface)
    PEDS_PLAYER_KEY, peds_COP_KEY
"""


# ------------------------------------------------------------------ geometry

peds_DIRS = 8
peds_WALK_FRAMES = 4
peds_SPRITE_W = 16
peds_SPRITE_H = 22

peds_SHADOW_ALPHA = 115
peds__OUTLINE = (18, 16, 18)
peds__EYE = (24, 20, 26)
peds__SWING = (0, 1, 0, -1)          # frames 0/2 pass, 1/3 the stride extremes


# --------------------------------------------------------------- directions
def peds_dir_index_from_angle(radians):
    """0..7 from an angle. 0 = east, increasing clockwise (+Y is down)."""
    return int(math.floor(radians / (math.pi / 4.0) + 0.5)) % peds_DIRS


def peds_dir_index(dx, dy):
    """0..7 from a movement vector. +X east, +Y south."""
    if dx == 0 and dy == 0:
        return 2                          # default: facing the camera
    return peds_dir_index_from_angle(math.atan2(dy, dx))


#: dir -> (view, mirror). 0=E 1=SE 2=S 3=SW 4=W 5=NW 6=N 7=NE
peds__DIR_VIEW = (
    ('side', False), ('side', False), ('front', False), ('side', True),
    ('side', True),  ('back', True),  ('back', False),  ('back', False),
)


# ------------------------------------------------------------------ palette
peds__SKIN = (
    ((242, 210, 184), (206, 170, 144)),
    ((224, 180, 142), (188, 144, 110)),
    ((192, 142, 102), (154, 108, 74)),
    ((150, 104, 72),  (116, 76, 50)),
    ((104, 70, 48),   (76, 48, 32)),
)
# Kept a clear step above the (18,16,18) outline so small heads still read.
peds__HAIR = {
    'black': (52, 46, 54), 'dbrown': (74, 52, 40), 'brown': (110, 78, 50),
    'blond': (190, 158, 100), 'grey': (176, 174, 170), 'auburn': (132, 72, 48),
}
peds__HAIR_POOL = ('black', 'dbrown', 'brown', 'blond', 'auburn', 'black', 'dbrown')

# shirt (base, shade)
_TEAL = ((70, 112, 108), (44, 78, 76))
_GREYBLUE = ((96, 118, 140), (62, 84, 104))
_OLIVE = ((104, 116, 70), (68, 82, 46))
_MAROON = ((122, 52, 58), (84, 34, 42))
_PURPLE = ((114, 92, 138), (78, 62, 98))
_BRICKY = ((162, 84, 62), (114, 56, 42))
_ROSE = ((180, 122, 124), (128, 82, 86))
_MUSTARD = ((198, 162, 74), (140, 112, 46))
_OFFWHT = ((216, 210, 196), (168, 162, 150))
_SLATE = ((92, 98, 108), (60, 64, 74))
_NAVY = ((48, 58, 92), (30, 38, 64))
_CHARC = ((66, 64, 70), (44, 42, 48))
_CARDS = ((228, 226, 218), (196, 194, 186))         # Cardinals home whites

_PA_DENIM = (58, 70, 98)
_PA_KHAKI = (152, 134, 100)
_PA_GREY = (76, 76, 82)
_PA_BROWN = (86, 64, 46)
_PA_BLACK = (44, 42, 48)
_PA_NAVY = (40, 46, 74)
_PA_CHARC = (56, 54, 60)
_PA_CARDS = (222, 220, 212)

_SHOE = (42, 40, 44)
_SAX = (224, 184, 74)
_SAX_D = (150, 118, 42)
_HIVIS = (234, 122, 42)
_HIVIS_LT = (236, 232, 216)
_HARDHAT = (236, 200, 68)
_BAT = (200, 158, 106)
_FEDORA = (52, 44, 46)


def peds__dk(c, t=0.64):
    return (int(c[0] * t), int(c[1] * t), int(c[2] * t))


#: archetype -> spawn spec. w = spawn weight, gait = speed x, acc = accessory
#: set, sh / pa = clothing colour choices indexed by the ped's variant number.
peds_ARCHETYPES = {
    'commuter':   dict(w=3, gait=1.00, acc=('shoulder_bag',),
                       sh=(_TEAL, _GREYBLUE, _OLIVE),   pa=(_PA_KHAKI, _PA_GREY, _PA_DENIM)),
    'suit':       dict(w=2, gait=1.05, acc=('briefcase',),
                       sh=(_SLATE, _NAVY, _CHARC),      pa=(_PA_CHARC, _PA_NAVY, _PA_GREY)),
    'streetwear': dict(w=3, gait=1.12, acc=('hood',),
                       sh=(_MAROON, _PURPLE, _BRICKY),  pa=(_PA_DENIM, _PA_BLACK, _PA_GREY)),
    'shopper':    dict(w=2, gait=0.85, acc=('totes',),
                       sh=(_ROSE, _MUSTARD, _OFFWHT),   pa=(_PA_DENIM, _PA_KHAKI, _PA_GREY)),
    'dog_walker': dict(w=2, gait=0.95, acc=(), dog=True,
                       sh=(_OLIVE, _TEAL, _BRICKY),     pa=(_PA_DENIM, _PA_KHAKI, _PA_GREY)),
    'elder':      dict(w=2, gait=0.55, acc=('cane',), hair='grey',
                       sh=(_OFFWHT, _GREYBLUE, _SLATE), pa=(_PA_GREY, _PA_KHAKI, _PA_BROWN)),
    'hi_vis':     dict(w=1, gait=0.90, acc=('hardhat', 'hivis'),
                       sh=(_MUSTARD, _MUSTARD, _MUSTARD), pa=(_PA_DENIM, _PA_BROWN, _PA_GREY)),
    'jogger':     dict(w=1, gait=1.80, acc=('cap',),
                       sh=(_TEAL, _ROSE, _OFFWHT),      pa=(_PA_BLACK, _PA_NAVY, _PA_GREY)),
    'tourist':    dict(w=2, gait=0.80, acc=('cap', 'shoulder_bag'),
                       sh=(_MUSTARD, _TEAL, _OFFWHT),   pa=(_PA_KHAKI, _PA_DENIM, _PA_GREY)),
    'busker_sax': dict(w=1, gait=0.24, acc=('fedora', 'sax'),
                       sh=(_MAROON, _SLATE, _BRICKY),   pa=(_PA_CHARC, _PA_BROWN, _PA_BLACK)),
    'cardinals':  dict(w=1, gait=1.00, acc=('cap', 'bat'), cap=(176, 42, 44),
                       sh=(_CARDS, _CARDS, _CARDS),     pa=(_PA_CARDS, _PA_CARDS, _PA_CARDS)),
}

peds_COP_KEY = 'cop#0'
PEDS_PLAYER_KEY = 'player#0'
peds__SPECIAL = {
    'cop':    dict(gait=1.0, acc=('cap',), cap=(40, 48, 78),
                   sh=(_NAVY,), pa=(_PA_NAVY,)),
    'player': dict(gait=1.0, acc=('jacket',),
                   sh=(((96, 48, 46), (64, 32, 30)),), pa=(_PA_DENIM,)),
}
peds__VARIANTS = 3


def peds__arch_spec(arch):
    return peds_ARCHETYPES.get(arch) or peds__SPECIAL[arch]


peds__SPEC_CACHE = {}


def peds__resolve(key):
    """Concrete per-ped colour + accessory spec for a "<archetype>#<variant>" key."""
    hit = peds__SPEC_CACHE.get(key)
    if hit is not None:
        return hit
    arch, _, vs = key.partition('#')
    v = int(vs or 0)
    base = peds__arch_spec(arch)
    acc = set(base.get('acc', ()))
    salt = sum(ord(ch) for ch in arch)
    sh = base['sh'][v % len(base['sh'])]
    pa = base['pa'][v % len(base['pa'])]
    skin, skin_d = peds__SKIN[_hash2(salt, v, 5) % len(peds__SKIN)]
    hair_name = base.get('hair') or peds__HAIR_POOL[_hash2(salt, v, 9) % len(peds__HAIR_POOL)]
    if 'hivis' in acc:
        accent, accent_d = _HIVIS, peds__dk(_HIVIS)
    elif arch == 'shopper':
        accent = ((182, 92, 72), (74, 132, 150), (204, 172, 82))[v % 3]
        accent_d = peds__dk(accent)
    elif 'bat' in acc:
        accent, accent_d = _BAT, peds__dk(_BAT)
    elif 'jacket' in acc:
        accent, accent_d = (96, 48, 46), (58, 30, 28)
    else:
        accent, accent_d = (150, 120, 86), (96, 74, 52)
    if 'hardhat' in acc:
        hat, hat_d = _HARDHAT, peds__dk(_HARDHAT)
    elif 'fedora' in acc:
        hat, hat_d = _FEDORA, peds__dk(_FEDORA, 0.6)
    else:
        hat = base.get('cap', (60, 62, 72))
        hat_d = peds__dk(hat, 0.6)
    spec = dict(acc=acc, skin=skin, skin_d=skin_d, hair=peds__HAIR[hair_name],
                shirt=sh[0], shirt_d=sh[1], pants=pa, pants_d=peds__dk(pa, 0.72),
                shoe=_SHOE, accent=accent, accent_d=accent_d, hat=hat, hat_d=hat_d)
    peds__SPEC_CACHE[key] = spec
    return spec


# ---------------------------------------------------------------- materials
(M_E, M_OUT, M_SKIN, M_SKIN_D, M_HAIR, M_HAIR_LT, M_SH, M_SH_D, M_PA, M_PA_D,
 M_SHOE, M_EYE, M_HAT, M_HAT_D, M_ACC, M_ACC_D, M_MET, M_MET_D, M_LT) = range(19)


def _lt(c, t=1.34):
    return (min(255, int(c[0] * t)), min(255, int(c[1] * t)), min(255, int(c[2] * t)))


def peds__colmap(spec):
    return {
        M_OUT: peds__OUTLINE, M_SKIN: spec['skin'], M_SKIN_D: spec['skin_d'],
        M_HAIR: spec['hair'], M_HAIR_LT: _lt(spec['hair'], 1.28),
        M_SH: spec['shirt'], M_SH_D: spec['shirt_d'],
        M_PA: spec['pants'], M_PA_D: spec['pants_d'], M_SHOE: spec['shoe'],
        M_EYE: peds__EYE, M_HAT: spec['hat'], M_HAT_D: spec['hat_d'],
        M_ACC: spec['accent'], M_ACC_D: spec['accent_d'],
        M_MET: _SAX, M_MET_D: _SAX_D, M_LT: _HIVIS_LT,
    }


# ------------------------------------------------------------- figure stamp
def peds__mk():
    return [[M_E] * peds_SPRITE_W for _ in range(peds_SPRITE_H)]


def peds__gx(g, x, y):
    if 0 <= x < peds_SPRITE_W and 0 <= y < peds_SPRITE_H:
        return g[y][x]
    return M_E


def peds__p(g, x, y, m):
    if 0 <= x < peds_SPRITE_W and 0 <= y < peds_SPRITE_H:
        g[y][x] = m


def peds__r(g, x0, y0, x1, y1, m):
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    for y in range(max(0, y0), min(peds_SPRITE_H, y1 + 1)):
        row = g[y]
        for x in range(max(0, x0), min(peds_SPRITE_W, x1 + 1)):
            row[x] = m


def peds__fig_front(g, spec, s):
    o = -1 if s else 0                     # 1px bounce at the stride extreme
    acc = spec['acc']
    if 'hood' in acc:
        peds__r(g, 3, 2 + o, 12, 8 + o, M_SH)
    peds__r(g, 5, 2 + o, 10, 7 + o, M_HAIR)
    peds__r(g, 5, 2 + o, 10, 2 + o, M_HAIR_LT)     # top-of-head sheen
    peds__r(g, 6, 4 + o, 9, 7 + o, M_SKIN)
    peds__p(g, 5, 5 + o, M_SKIN)
    peds__p(g, 10, 5 + o, M_SKIN)
    peds__p(g, 6, 5 + o, M_EYE)
    peds__p(g, 9, 5 + o, M_EYE)
    peds__r(g, 7, 8 + o, 8, 8 + o, M_SKIN)
    peds__r(g, 4, 9 + o, 11, 9 + o, M_SH)
    peds__r(g, 5, 9 + o, 10, 15 + o, M_SH)
    lh = 1 if s > 0 else 0
    rh = 1 if s < 0 else 0
    peds__r(g, 3, 10 + o, 4, 13 + o + lh, M_SH)
    peds__r(g, 3, 14 + o + lh, 4, 15 + o + lh, M_SKIN)
    peds__r(g, 11, 10 + o, 12, 13 + o + rh, M_SH)
    peds__r(g, 11, 14 + o + rh, 12, 15 + o + rh, M_SKIN)
    ll = 1 if s < 0 else 0
    rl = 1 if s > 0 else 0
    peds__r(g, 5, 16 + o, 7, 19 + o + ll, M_PA)
    peds__r(g, 8, 16 + o, 10, 19 + o + rl, M_PA)
    peds__r(g, 5, 20 + o + ll, 7, 20 + o + ll, M_SHOE)
    peds__r(g, 8, 20 + o + rl, 10, 20 + o + rl, M_SHOE)


def peds__fig_back(g, spec, s):
    o = -1 if s else 0
    acc = spec['acc']
    if 'hood' in acc:
        peds__r(g, 3, 2 + o, 12, 8 + o, M_SH)
    peds__r(g, 4, 2 + o, 11, 9 + o, M_HAIR)          # bigger head on the back view
    peds__r(g, 4, 2 + o, 11, 2 + o, M_HAIR_LT)
    peds__r(g, 4, 10 + o, 11, 10 + o, M_SH)          # shoulders
    peds__r(g, 5, 10 + o, 10, 15 + o, M_SH)
    if 'jacket' in acc:
        peds__r(g, 5, 10 + o, 10, 14 + o, M_ACC)
    lh = 1 if s > 0 else 0
    rh = 1 if s < 0 else 0
    peds__r(g, 3, 10 + o, 4, 15 + o + lh, M_SH)
    peds__r(g, 11, 10 + o, 12, 15 + o + rh, M_SH)
    ll = 1 if s < 0 else 0
    rl = 1 if s > 0 else 0
    peds__r(g, 5, 16 + o, 7, 19 + o + ll, M_PA)
    peds__r(g, 8, 16 + o, 10, 19 + o + rl, M_PA)
    peds__r(g, 5, 20 + o + ll, 7, 20 + o + ll, M_SHOE)
    peds__r(g, 8, 20 + o + rl, 10, 20 + o + rl, M_SHOE)


def peds__fig_side(g, spec, s):
    o = -1 if s else 0
    acc = spec['acc']
    if 'hood' in acc:
        peds__r(g, 4, 2 + o, 11, 8 + o, M_SH)
    peds__r(g, 5, 2 + o, 10, 7 + o, M_HAIR)
    peds__r(g, 5, 2 + o, 10, 2 + o, M_HAIR_LT)
    peds__r(g, 8, 4 + o, 10, 7 + o, M_SKIN)
    peds__p(g, 11, 5 + o, M_SKIN)
    peds__p(g, 9, 5 + o, M_EYE)
    peds__r(g, 7, 8 + o, 8, 8 + o, M_SKIN)
    peds__r(g, 6, 9 + o, 10, 15 + o, M_SH)
    peds__r(g, 6, 10 + o, 6, 14 + o, M_SH_D)
    ax = 8 + s
    peds__r(g, ax, 10 + o, ax + 1, 13 + o, M_SH)
    peds__r(g, ax, 14 + o, ax + 1, 15 + o, M_SKIN)
    nx = 8 + max(0, s)
    fx = 6 - max(0, -s)
    peds__r(g, fx, 16 + o, fx + 2, 19 + o, M_PA_D)
    peds__r(g, fx, 20 + o, fx + 2, 20 + o, M_SHOE)
    peds__r(g, nx, 16 + o, nx + 2, 19 + o, M_PA)
    peds__r(g, nx, 20 + o, nx + 2, 20 + o, M_SHOE)


def peds__acc(g, view, spec, s):
    acc = spec['acc']
    o = -1 if s else 0
    if 'fedora' in acc:
        peds__r(g, 3, 3 + o, 12, 3 + o, M_HAT_D)
        peds__r(g, 5, 1 + o, 10, 3 + o, M_HAT)
    if 'cap' in acc:
        peds__r(g, 5, 2 + o, 10, 3 + o, M_HAT)
        if view == 'front':
            peds__r(g, 6, 4 + o, 9, 4 + o, M_HAT_D)
        elif view == 'side':
            peds__r(g, 10, 3 + o, 12, 3 + o, M_HAT_D)
    if 'hardhat' in acc:
        peds__r(g, 5, 1 + o, 10, 3 + o, M_HAT)
        peds__r(g, 4, 3 + o, 11, 3 + o, M_HAT_D)
    if 'hivis' in acc:
        if view == 'side':
            peds__r(g, 6, 9 + o, 10, 15 + o, M_ACC)
            peds__r(g, 6, 12 + o, 10, 12 + o, M_LT)
        else:
            peds__r(g, 5, 9 + o, 10, 15 + o, M_ACC)
            peds__r(g, 5, 11 + o, 10, 11 + o, M_LT)
            peds__r(g, 5, 14 + o, 10, 14 + o, M_LT)
    if 'shoulder_bag' in acc and view != 'back':
        for k in range(6):
            peds__p(g, 4 + k, 9 + o + k, M_ACC_D)
        peds__r(g, 10, 13 + o, 12, 16 + o, M_ACC)
    if 'briefcase' in acc and view != 'back':
        peds__r(g, 12, 13 + o, 14, 16 + o, M_ACC)
        peds__p(g, 13, 12 + o, M_OUT)
    if 'totes' in acc and view != 'back':
        peds__r(g, 2, 14 + o, 4, 17 + o, M_ACC)
        peds__r(g, 12, 14 + o, 14, 17 + o, M_ACC_D)
    if 'cane' in acc and view != 'back':
        for k in range(8):
            peds__p(g, 13, 13 + o + k, M_MET_D)
        peds__p(g, 12, 13 + o, M_MET_D)
    if 'sax' in acc and view != 'back':
        peds__r(g, 10, 9 + o, 11, 13 + o, M_MET)
        peds__p(g, 12, 13 + o, M_MET)
        peds__p(g, 12, 14 + o, M_MET)
        peds__p(g, 11, 15 + o, M_MET)
        peds__p(g, 11, 8 + o, M_MET_D)
    if 'bat' in acc:
        for k in range(7):
            peds__p(g, 10 + k // 2, 9 + o - k, M_ACC)
    if 'jacket' in acc and view == 'front':
        peds__r(g, 5, 9 + o, 10, 14 + o, M_ACC)
        peds__r(g, 7, 9 + o, 8, 14 + o, M_ACC_D)


def peds__shade(g):
    hits = []
    for y in range(peds_SPRITE_H):
        for x in range(peds_SPRITE_W):
            m = g[y][x]
            if m == M_SH and (peds__gx(g, x + 1, y) == M_E or peds__gx(g, x, y + 1) == M_E):
                hits.append((x, y, M_SH_D))
            elif m == M_PA and (peds__gx(g, x + 1, y) == M_E or peds__gx(g, x, y + 1) == M_E):
                hits.append((x, y, M_PA_D))
    for x, y, m in hits:
        g[y][x] = m


def peds__outline(g):
    edge = []
    for y in range(peds_SPRITE_H):
        for x in range(peds_SPRITE_W):
            if g[y][x] != M_E:
                continue
            found = False
            for oy in (-1, 0, 1):
                for ox in (-1, 0, 1):
                    if (ox or oy) and peds__gx(g, x + ox, y + oy) not in (M_E, M_OUT):
                        found = True
                        break
                if found:
                    break
            if found:
                edge.append((x, y))
    for x, y in edge:
        g[y][x] = M_OUT


def peds__surface(g, spec):
    cm = peds__colmap(spec)
    surf = pygame.Surface((peds_SPRITE_W, peds_SPRITE_H), pygame.SRCALPHA)
    for y in range(peds_SPRITE_H):
        for x in range(peds_SPRITE_W):
            m = g[y][x]
            if m == M_E:
                continue
            c = cm.get(m)
            if c is not None:
                surf.set_at((x, y), (c[0], c[1], c[2], 255))
    if pygame.display.get_init() and pygame.display.get_surface() is not None:
        try:
            surf = surf.convert_alpha()
        except pygame.error:
            pass
    return surf


def peds__build(view, s, key):
    spec = peds__resolve(key)
    g = peds__mk()
    if view == 'front':
        peds__fig_front(g, spec, s)
    elif view == 'back':
        peds__fig_back(g, spec, s)
    else:
        peds__fig_side(g, spec, s)
    peds__acc(g, view, spec, s)
    peds__shade(g)
    peds__outline(g)
    return peds__surface(g, spec)


# ------------------------------------------------------------------- baking
peds__BAKED = None


def peds__all_keys():
    keys = [f"{a}#{v}" for a in peds_ARCHETYPES for v in range(peds__VARIANTS)]
    keys += [peds_COP_KEY, PEDS_PLAYER_KEY]
    return keys


def peds_bake_all():
    """Bake once -> {key: {'walk': [dir][frame], 'idle': [dir]}}."""
    global peds__BAKED
    if peds__BAKED is not None:
        return peds__BAKED
    out = {}
    for key in peds__all_keys():
        walk, idle = [], []
        for d in range(peds_DIRS):
            view, mir = peds__DIR_VIEW[d]
            frames = []
            for fr in range(peds_WALK_FRAMES):
                surf = peds__build(view, peds__SWING[fr], key)
                if mir:
                    surf = pygame.transform.flip(surf, True, False)
                frames.append(surf)
            walk.append(frames)
            isurf = peds__build(view, 0, key)
            if mir:
                isurf = pygame.transform.flip(isurf, True, False)
            idle.append(isurf)
        out[key] = {'walk': walk, 'idle': idle}
    peds__BAKED = out
    return out


def peds_clear_cache():
    """Drop the baked sheets (e.g. after a display mode change)."""
    global peds__BAKED
    peds__BAKED = None
    peds__SPEC_CACHE.clear()


peds__WEIGHTED = []
for _a, _s in peds_ARCHETYPES.items():
    peds__WEIGHTED += [_a] * _s['w']


def peds_random_archetype(include_cop=False):
    """A weighted-random "<archetype>#<variant>" key for a fresh pedestrian."""
    if include_cop and random.random() < 0.08:
        return peds_COP_KEY
    a = random.choice(peds__WEIGHTED)
    return f"{a}#{random.randrange(peds__VARIANTS)}"


def peds_gait(key):
    return peds__arch_spec(key.split('#')[0])['gait']


def peds_has_dog(key):
    return bool(peds__arch_spec(key.split('#')[0]).get('dog'))


def peds_make_shadow(surface):
    """Hard-edged black silhouette of a sprite, for a south-east drop shadow."""
    w, h = surface.get_size()
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(h):
        for x in range(w):
            if surface.get_at((x, y))[3] >= 128:
                out.set_at((x, y), (0, 0, 0, peds_SHADOW_ALPHA))
    return out


# ==========================================================
# Baked art: gfx_followers
# ==========================================================
"""A trailing dog for the dog_walker ped: a 13x9 side-view sprite in 4 compass
facings (east authored, west mirrored, north/south rotated) with a 2-frame
trot. Baked once alongside the peds."""

dog_DIRS = 4                    # 0=E 1=S 2=W 3=N
dog_FRAMES = 2
dog__W, dog__H = 13, 9
dog__OUT = (18, 16, 18)
dog__COLORS = (
    ((120, 84, 52), (88, 60, 38)),        # brown
    ((60, 54, 52), (40, 36, 36)),         # black
    ((182, 156, 116), (140, 116, 82)),    # tan
    ((206, 202, 192), (166, 162, 152)),   # white
)
dog__BAKED = None


def dog__grid(frame, base, dark):
    g = [[None] * dog__W for _ in range(dog__H)]

    def r(x0, y0, x1, y1, c):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if 0 <= x < dog__W and 0 <= y < dog__H:
                    g[y][x] = c

    r(3, 3, 8, 6, base)             # body
    r(8, 2, 10, 5, base)            # head (facing east)
    g[4][11] = base                 # snout
    g[2][8] = dark                  # ear
    g[3][2] = dark
    g[2][2] = dark                  # tail, up
    g[3][10] = dog__OUT             # eye
    lo = frame                      # legs alternate between the two frames
    r(4, 7, 4, 8 - lo, dark)
    r(7, 7, 7, 7 + lo, dark)
    r(5, 7, 5, 7 + (1 - lo), dark)
    r(8, 7, 8, 8 - (1 - lo), dark)
    edge = []
    for y in range(dog__H):
        for x in range(dog__W):
            if g[y][x] is not None:
                continue
            if any(0 <= x + ox < dog__W and 0 <= y + oy < dog__H
                   and g[y + oy][x + ox] not in (None, dog__OUT)
                   for ox in (-1, 0, 1) for oy in (-1, 0, 1) if ox or oy):
                edge.append((x, y))
    for x, y in edge:
        g[y][x] = dog__OUT
    return g


def dog__surface(g):
    surf = pygame.Surface((dog__W, dog__H), pygame.SRCALPHA)
    for y in range(dog__H):
        for x in range(dog__W):
            c = g[y][x]
            if c is not None:
                surf.set_at((x, y), (c[0], c[1], c[2], 255))
    if pygame.display.get_init() and pygame.display.get_surface() is not None:
        try:
            surf = surf.convert_alpha()
        except pygame.error:
            pass
    return surf


def dog_bake():
    """Bake once -> {colour_index: [dir][frame] -> (sprite, shadow)}."""
    global dog__BAKED
    if dog__BAKED is not None:
        return dog__BAKED
    out = {}
    for ci, (base, dark) in enumerate(dog__COLORS):
        dirs = []
        for d in range(dog_DIRS):
            frames = []
            for fr in range(dog_FRAMES):
                s = dog__surface(dog__grid(fr, base, dark))
                if d == 2:
                    s = pygame.transform.flip(s, True, False)
                elif d == 1:
                    s = pygame.transform.rotate(s, -90)
                elif d == 3:
                    s = pygame.transform.rotate(s, 90)
                frames.append((s, peds_make_shadow(s)))
            dirs.append(frames)
        out[ci] = dirs
    dog__BAKED = out
    return out


def dog_dir_index(dx, dy):
    if abs(dx) >= abs(dy):
        return 0 if dx >= 0 else 2
    return 1 if dy >= 0 else 3


def dog_sprite(ci, facing, anim):
    dirs = (dog__BAKED or dog_bake())[ci % len(dog__COLORS)]
    return dirs[facing % dog_DIRS][int(anim) % dog_FRAMES]



# ==========================================================
# Baked art: gfx_hud
# ==========================================================
"""GTA1 (1997) style arcade HUD primitives for a 640x360 internal render buffer.

Self contained: procedural 5x7 bitmap font, chunky outlined numerals, pixel
wanted-stars, recessed bevel panels and a radar bezel. No pygame.font, no
antialiasing, no external assets. Everything is baked once into surface caches.
"""


# ---------------------------------------------------------------------------
# Palette - muted, slightly dirty 90s console values over near-black shadow.
# ---------------------------------------------------------------------------

hud_HUD_WHITE = (232, 228, 208)
hud_HUD_GOLD = (255, 196, 40)
hud_HUD_GREEN = (96, 200, 88)
hud_HUD_RED = (204, 56, 40)
hud_HUD_SHADOW = (10, 8, 12)
hud_HUD_PANEL = (28, 28, 38)
hud_HUD_BEVEL_LIGHT = (108, 108, 124)
hud_HUD_BEVEL_DARK = (14, 14, 20)

# Secondary shades derived from the palette above.
hud_HUD_GOLD_DARK = (140, 92, 12)
hud_HUD_GOLD_HOT = (255, 248, 206)
hud_HUD_GREEN_DARK = (24, 80, 32)
hud_HUD_GREY_DIM = (84, 84, 96)
hud_HUD_OUTLINE = (18, 14, 18)

# Font metrics.
hud_GLYPH_W = 5
hud_GLYPH_H = 7
hud_GLYPH_GAP = 1  # in unscaled pixels, scaled with the hud_text

# ---------------------------------------------------------------------------
# Bitmap font. 5 wide x 7 tall, '#' = ink, '.' = empty. Uppercase only.
# ---------------------------------------------------------------------------

hud__FONT = {
    "A": ".###.|#...#|#...#|#####|#...#|#...#|#...#",
    "B": "####.|#...#|#...#|####.|#...#|#...#|####.",
    "C": ".###.|#...#|#....|#....|#....|#...#|.###.",
    "D": "####.|#...#|#...#|#...#|#...#|#...#|####.",
    "E": "#####|#....|#....|####.|#....|#....|#####",
    "F": "#####|#....|#....|####.|#....|#....|#....",
    "G": ".###.|#...#|#....|#.###|#...#|#...#|.###.",
    "H": "#...#|#...#|#...#|#####|#...#|#...#|#...#",
    "I": "#####|..#..|..#..|..#..|..#..|..#..|#####",
    "J": "..###|...#.|...#.|...#.|...#.|#..#.|.##..",
    "K": "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#",
    "L": "#....|#....|#....|#....|#....|#....|#####",
    "M": "#...#|##.##|#.#.#|#.#.#|#...#|#...#|#...#",
    "N": "#...#|##..#|#.#.#|#..##|#...#|#...#|#...#",
    "O": ".###.|#...#|#...#|#...#|#...#|#...#|.###.",
    "P": "####.|#...#|#...#|####.|#....|#....|#....",
    "Q": ".###.|#...#|#...#|#...#|#.#.#|#..#.|.##.#",
    "R": "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
    "S": ".####|#....|#....|.###.|....#|....#|####.",
    "T": "#####|..#..|..#..|..#..|..#..|..#..|..#..",
    "U": "#...#|#...#|#...#|#...#|#...#|#...#|.###.",
    "V": "#...#|#...#|#...#|#...#|#...#|.#.#.|..#..",
    "W": "#...#|#...#|#...#|#.#.#|#.#.#|#.#.#|.#.#.",
    "X": "#...#|#...#|.#.#.|..#..|.#.#.|#...#|#...#",
    "Y": "#...#|#...#|.#.#.|..#..|..#..|..#..|..#..",
    "Z": "#####|....#|...#.|..#..|.#...|#....|#####",
    "0": ".###.|#...#|#..##|#.#.#|##..#|#...#|.###.",
    "1": "..#..|.##..|..#..|..#..|..#..|..#..|.###.",
    "2": ".###.|#...#|....#|...#.|..#..|.#...|#####",
    "3": "####.|....#|....#|.###.|....#|....#|####.",
    "4": "...#.|..##.|.#.#.|#..#.|#####|...#.|...#.",
    "5": "#####|#....|####.|....#|....#|#...#|.###.",
    "6": "..##.|.#...|#....|####.|#...#|#...#|.###.",
    "7": "#####|....#|...#.|..#..|.#...|.#...|.#...",
    "8": ".###.|#...#|#...#|.###.|#...#|#...#|.###.",
    "9": ".###.|#...#|#...#|.####|....#|...#.|.##..",
    " ": ".....|.....|.....|.....|.....|.....|.....",
    ".": ".....|.....|.....|.....|.....|.##..|.##..",
    ",": ".....|.....|.....|.....|.##..|.##..|.#...",
    ":": ".....|.##..|.##..|.....|.##..|.##..|.....",
    "-": ".....|.....|.....|.###.|.....|.....|.....",
    "$": "..#..|.####|#.#..|.###.|..#.#|####.|..#..",
    "!": "..#..|..#..|..#..|..#..|..#..|.....|..#..",
    "?": ".###.|#...#|....#|..##.|..#..|.....|..#..",
    "/": "....#|....#|...#.|..#..|.#...|#....|#....",
    "'": "..#..|..#..|..#..|.....|.....|.....|.....",
    "%": "##..#|##..#|...#.|..#..|.#...|#..##|#..##",
    "&": ".##..|#..#.|#.#..|.#...|#.#.#|#..#.|.##.#",
}

hud__MISSING = "#####|#...#|#...#|#...#|#...#|#...#|#####"

# ---------------------------------------------------------------------------
# Wanted star. 9x9 core silhouette, dilated by 1px -> 11x11 drawn footprint.
# ---------------------------------------------------------------------------

hud__STAR = [
    "....#....",
    "...###...",
    "...###...",
    "#########",
    ".#######.",
    "..#####..",
    "..#####..",
    ".##...##.",
    ".#.....#.",
]

hud_STAR_W = len(hud__STAR[0]) + 2
hud_STAR_H = len(hud__STAR) + 2
hud_STAR_GAP = 2
hud__PULSE_STEPS = 6

# ---------------------------------------------------------------------------
# Caches. All keyed so nothing is rebuilt per frame.
# ---------------------------------------------------------------------------

hud__baked = False
hud__rows = {}          # char -> tuple of row strings
hud__glyphs = {}        # (char, color, scale) -> Surface
hud__big = {}           # (char, color, outline, scale) -> Surface (1px outline)
hud__stars = {}         # (kind, level, scale) -> Surface
hud__panels = {}        # (w, h, fill, alpha, bevel, inset) -> Surface


def hud__conv(surf):
    """convert_alpha when a display exists, otherwise leave the surface alone."""
    if pygame.display.get_init() and pygame.display.get_surface() is not None:
        try:
            return surf.convert_alpha()
        except pygame.error:
            return surf
    return surf


def hud_bake():
    """Build the font atlas and cached surfaces. Safe to call repeatedly."""
    global hud__baked
    if hud__baked:
        return
    for ch, pattern in hud__FONT.items():
        rows = pattern.split("|")
        rows = [r.ljust(hud_GLYPH_W, ".")[:hud_GLYPH_W] for r in rows]
        while len(rows) < hud_GLYPH_H:
            rows.append("." * hud_GLYPH_W)
        hud__rows[ch] = tuple(rows[:hud_GLYPH_H])
    hud__rows[None] = tuple(hud__MISSING.split("|"))
    hud__baked = True
    # Warm every combination the HUD touches per frame so nothing allocates later.
    for ch in hud__FONT:
        for col in (hud_HUD_WHITE, hud_HUD_SHADOW):
            hud__glyphs[(ch, col, 1)] = hud__make_glyph(ch, col, 1)
    for ch in "0123456789$-":
        for col in (hud_HUD_WHITE, hud_HUD_GREEN):
            hud__big[(ch, col, hud_HUD_OUTLINE, 2)] = hud__make_big(ch, col, hud_HUD_OUTLINE, 2)
        hud__big[(ch, hud_HUD_SHADOW, hud_HUD_SHADOW, 2)] = hud__make_big(ch, hud_HUD_SHADOW, hud_HUD_SHADOW, 2)
    for level in range(hud__PULSE_STEPS):
        hud__stars[("lit", level, 1)] = hud__make_star("lit", level, 1)
    hud__stars[("dim", 0, 1)] = hud__make_star("dim", 0, 1)


def hud__pattern(ch):
    rows = hud__rows.get(ch)
    if rows is None:
        rows = hud__rows[None]
    return rows


# ---------------------------------------------------------------------------
# Glyph surfaces
# ---------------------------------------------------------------------------

def hud__make_glyph(ch, color, scale):
    surf = pygame.Surface((hud_GLYPH_W * scale, hud_GLYPH_H * scale), pygame.SRCALPHA)
    rows = hud__pattern(ch)
    for ry, row in enumerate(rows):
        run = 0
        for rx in range(hud_GLYPH_W + 1):
            on = rx < hud_GLYPH_W and row[rx] == "#"
            if on:
                run += 1
                continue
            if run:
                surf.fill(color, ((rx - run) * scale, ry * scale, run * scale, scale))
                run = 0
    return hud__conv(surf)


def hud__glyph(ch, color, scale):
    key = (ch, color, scale)
    surf = hud__glyphs.get(key)
    if surf is None:
        surf = hud__make_glyph(ch, color, scale)
        hud__glyphs[key] = surf
    return surf


def hud__make_big(ch, color, outline, scale):
    """Glyph with a hard 1px outline. Footprint grows by 1px on every side."""
    core = hud__make_glyph(ch, outline, scale)
    surf = pygame.Surface((hud_GLYPH_W * scale + 2, hud_GLYPH_H * scale + 2), pygame.SRCALPHA)
    for ox, oy in ((0, 0), (1, 0), (2, 0), (0, 1), (2, 1), (0, 2), (1, 2), (2, 2)):
        surf.blit(core, (ox, oy))
    surf.blit(hud__make_glyph(ch, color, scale), (1, 1))
    return hud__conv(surf)


def hud__big_glyph(ch, color, outline, scale):
    key = (ch, color, outline, scale)
    surf = hud__big.get(key)
    if surf is None:
        surf = hud__make_big(ch, color, outline, scale)
        hud__big[key] = surf
    return surf


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def hud_text_width(s, scale=1):
    """Pixel width of s when drawn with hud_text() at the given scale."""
    if not s:
        return 0
    best = 0
    for line in str(s).split("\n"):
        n = len(line)
        w = 0 if n == 0 else n * (hud_GLYPH_W + hud_GLYPH_GAP) * scale - hud_GLYPH_GAP * scale
        if w > best:
            best = w
    return best


def hud_text_height(s="", scale=1):
    lines = max(1, str(s).count("\n") + 1)
    return lines * (hud_GLYPH_H + hud_GLYPH_GAP) * scale - hud_GLYPH_GAP * scale


def hud_text(surf, s, x, y, color=hud_HUD_WHITE, shadow=True, scale=1):
    """Draw chunky pixel hud_text. Returns (w, h) of the block drawn."""
    if not hud__baked:
        hud_bake()
    s = str(s).upper()
    step = (hud_GLYPH_W + hud_GLYPH_GAP) * scale
    line_step = (hud_GLYPH_H + hud_GLYPH_GAP) * scale
    off = scale
    cy = y
    for line in s.split("\n"):
        cx = x
        for ch in line:
            if ch != " ":
                if shadow:
                    surf.blit(hud__glyph(ch, hud_HUD_SHADOW, scale), (cx + off, cy + off))
                surf.blit(hud__glyph(ch, color, scale), (cx, cy))
            cx += step
        cy += line_step
    return (hud_text_width(s, scale), hud_text_height(s, scale))


# ---------------------------------------------------------------------------
# Big odometer numerals
# ---------------------------------------------------------------------------

def hud__draw_big_string(surf, s, x_right, y, color, scale, shadow_offset=2):
    """Right aligned outlined numerals with a hard offset drop shadow."""
    if not hud__baked:
        hud_bake()
    step = (hud_GLYPH_W + hud_GLYPH_GAP) * scale
    total = len(s) * step - hud_GLYPH_GAP * scale
    x = x_right - total
    cx = x
    for ch in s:
        if ch != " ":
            sil = hud__big_glyph(ch, hud_HUD_SHADOW, hud_HUD_SHADOW, scale)
            surf.blit(sil, (cx - 1 + shadow_offset, y - 1 + shadow_offset))
        cx += step
    cx = x
    for ch in s:
        if ch != " ":
            surf.blit(hud__big_glyph(ch, color, hud_HUD_OUTLINE, scale), (cx - 1, y - 1))
        cx += step
    return (total, hud_GLYPH_H * scale)


def hud_draw_score(surf, value, x_right, y, scale=2, color=hud_HUD_WHITE, pad=0):
    """Big right-aligned odometer-style number in the top right."""
    if not hud__baked:
        hud_bake()
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 0
    s = str(abs(n))
    if pad > 0:
        s = s.rjust(pad, "0")
    if n < 0:
        s = "-" + s
    hud__draw_big_string(surf, s, x_right, y, color, scale)


def hud_draw_cash(surf, amount, x_right, y, scale=2, color=hud_HUD_GREEN, pad=0):
    """Like hud_draw_score but with a leading $ and a green tint."""
    if not hud__baked:
        hud_bake()
    try:
        n = int(amount)
    except (TypeError, ValueError):
        n = 0
    s = str(abs(n))
    if pad > 0:
        s = s.rjust(pad, "0")
    s = "$" + s
    if n < 0:
        s = "-" + s
    hud__draw_big_string(surf, s, x_right, y, color, scale)


# ---------------------------------------------------------------------------
# Wanted stars
# ---------------------------------------------------------------------------

def hud__star_masks():
    """Return (fill, ring) cell sets in the 11x11 footprint (core offset by 1)."""
    fill = set()
    for ry, row in enumerate(hud__STAR):
        for rx, c in enumerate(row):
            if c == "#":
                fill.add((rx + 1, ry + 1))
    ring = set()
    for cx, cy in fill:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                p = (cx + dx, cy + dy)
                if p not in fill:
                    ring.add(p)
    return fill, ring


def hud__make_star(kind, level, scale):
    surf = pygame.Surface((hud_STAR_W * scale, hud_STAR_H * scale), pygame.SRCALPHA)
    fill, ring = hud__star_masks()
    if kind == "lit":
        t = level / float(max(1, hud__PULSE_STEPS - 1))
        body = tuple(
            int(hud_HUD_GOLD[i] + (hud_HUD_GOLD_HOT[i] - hud_HUD_GOLD[i]) * t) for i in range(3)
        )
        edge = hud_HUD_GOLD_DARK
        cells = ((ring, edge), (fill, body))
    else:
        cells = ((ring, hud_HUD_GREY_DIM),)
    for group, col in cells:
        for cx, cy in group:
            surf.fill(col, (cx * scale, cy * scale, scale, scale))
    return hud__conv(surf)


def hud__star(kind, level, scale):
    key = (kind, level, scale)
    surf = hud__stars.get(key)
    if surf is None:
        surf = hud__make_star(kind, level, scale)
        hud__stars[key] = surf
    return surf


def hud_draw_stars(surf, wanted, x, y, ticks, scale=1, slots=6):
    """Wanted stars. Lit = gold (newest one pulses), unlit = dim outline."""
    if not hud__baked:
        hud_bake()
    slots = max(0, min(6, int(slots)))
    wanted = max(0, min(slots, int(wanted)))
    # Newest star breathes between base gold and a hot near-white gold.
    k = 0.5 + 0.5 * math.sin(float(ticks) * 0.006)
    level = int(k * (hud__PULSE_STEPS - 1) + 0.5)
    step = (hud_STAR_W + hud_STAR_GAP) * scale
    for i in range(slots):
        px = x + i * step
        if i < wanted:
            lvl = level if i == wanted - 1 else 0
            surf.blit(hud__star("lit", lvl, scale), (px, y))
        else:
            surf.blit(hud__star("dim", 0, scale), (px, y))
    w = 0 if slots == 0 else slots * step - hud_STAR_GAP * scale
    return (w, hud_STAR_H * scale)


# ---------------------------------------------------------------------------
# Panels and frames
# ---------------------------------------------------------------------------

def hud__make_panel(w, h, fill, alpha, bevel, inset):
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    surf.fill(fill + (255 if alpha is None else alpha,))
    if bevel and w > 1 and h > 1:
        hi = hud_HUD_BEVEL_DARK if inset else hud_HUD_BEVEL_LIGHT
        lo = hud_HUD_BEVEL_LIGHT if inset else hud_HUD_BEVEL_DARK
        surf.fill(hi, (0, 0, w, 1))
        surf.fill(hi, (0, 0, 1, h))
        surf.fill(lo, (0, h - 1, w, 1))
        surf.fill(lo, (w - 1, 0, 1, h))
    return hud__conv(surf)


def hud_draw_panel(surf, rect, fill=hud_HUD_PANEL, alpha=None, bevel=True, inset=True):
    """Recessed dark panel with a hard bevel, used behind HUD blocks."""
    if not hud__baked:
        hud_bake()
    r = pygame.Rect(rect)
    if r.w <= 0 or r.h <= 0:
        return
    key = (r.w, r.h, fill, alpha, bevel, inset)
    panel = hud__panels.get(key)
    if panel is None:
        panel = hud__make_panel(r.w, r.h, fill, alpha, bevel, inset)
        hud__panels[key] = panel
    surf.blit(panel, r.topleft)


def hud_draw_radar_frame(surf, rect, thickness=3):
    """Chunky bevelled bezel drawn strictly AROUND rect. Interior untouched."""
    if not hud__baked:
        hud_bake()
    r = pygame.Rect(rect)
    t = max(1, int(thickness))
    o = r.inflate(t * 2, t * 2)
    # Border band only - four rects that never overlap the radar interior.
    surf.fill(hud_HUD_PANEL, (o.left, o.top, o.w, t))
    surf.fill(hud_HUD_PANEL, (o.left, r.bottom, o.w, t))
    surf.fill(hud_HUD_PANEL, (o.left, r.top, t, r.h))
    surf.fill(hud_HUD_PANEL, (r.right, r.top, t, r.h))
    # Raised outer edge.
    surf.fill(hud_HUD_BEVEL_LIGHT, (o.left, o.top, o.w, 1))
    surf.fill(hud_HUD_BEVEL_LIGHT, (o.left, o.top, 1, o.h))
    surf.fill(hud_HUD_BEVEL_DARK, (o.left, o.bottom - 1, o.w, 1))
    surf.fill(hud_HUD_BEVEL_DARK, (o.right - 1, o.top, 1, o.h))
    # Recessed inner lip, one pixel outside the radar rect.
    surf.fill(hud_HUD_BEVEL_DARK, (r.left - 1, r.top - 1, r.w + 2, 1))
    surf.fill(hud_HUD_BEVEL_DARK, (r.left - 1, r.top - 1, 1, r.h + 2))
    surf.fill(hud_HUD_BEVEL_LIGHT, (r.left - 1, r.bottom, r.w + 2, 1))
    surf.fill(hud_HUD_BEVEL_LIGHT, (r.right, r.top - 1, 1, r.h + 2))
    # Corner rivets.
    if t >= 3:
        for cx, cy in ((o.left + 1, o.top + 1), (o.right - 3, o.top + 1),
                       (o.left + 1, o.bottom - 3), (o.right - 3, o.bottom - 3)):
            surf.fill(hud_HUD_BEVEL_LIGHT, (cx, cy, 2, 2))


hud_CHARSET = "".join(sorted(hud__FONT.keys()))


# ==========================================================
# Baked art: gfx_props
# ==========================================================
"""Street furniture / props for the GTA1-style top-down St. Louis sandbox.

Hard-pixel sprites baked once into small SRCALPHA surfaces, plus a
deterministic placement function so the same tile always grows the same
prop (no flicker, no random module at call time).

Usage from the renderer:

    import gfx_props
    gfx_props.props_bake()
    for (name, ox, oy) in gfx_props.props_props_for_tile(c, r, t, sidewalk):
        ax, ay = gfx_props.props_anchor_offset(name)
        sx = c * props_TILE_SIZE + ox - ax - camera.x
        sy = r * props_TILE_SIZE + oy - ay - camera.y
        sh = gfx_props.props_get_shadow(name)
        screen.blit(sh, (sx + 2, sy + 2))     # shadows fall south-east
        screen.blit(gfx_props.props_get(name), (sx, sy))

The (ox, oy) returned by props_props_for_tile is the prop's GROUND ANCHOR inside
the 64x64 tile; props_anchor_offset(name) is that same anchor measured from the
sprite's top-left, so subtracting it gives the blit position.
"""


# --- Tile constants (mirrored from main.py; do not import main) ---
props_TILE_SIZE = 64
props_TILE_GRASS = 0
props_TILE_ROAD = 1
props_TILE_WATER = 2
props_TILE_BUILDING = 3
props_TILE_PARK = 4

# Road grid: main.py uses road_lines = set(range(4, MAP_TILES_W, 8)),
# so index i carries a road when (i - 4) % 8 == 0.
props_ROAD_ORIGIN = 4
props_ROAD_STEP = 8

# --- Muted 90s console palette ---
props_C_OUT = (18, 16, 18)            # near-black outline, matches COLOR_OUTLINE
props_C_POLE = (86, 88, 92)
props_C_POLE_DARK = (58, 60, 64)
props_C_METAL = (114, 110, 100)
props_C_METAL_DARK = (82, 78, 70)
props_C_LAMP = (214, 198, 138)        # warm bulb, not neon
props_C_LAMP_DIM = (168, 154, 104)
props_C_RED = (140, 60, 52)
props_C_RED_DARK = (104, 44, 38)
props_C_RED_LIT = (172, 70, 60)
props_C_GREEN_BIN = (72, 90, 62)
props_C_GREEN_BIN_LID = (86, 104, 74)
props_C_GREEN_BIN_DARK = (48, 62, 42)
props_C_WOOD = (112, 84, 54)
props_C_WOOD_DARK = (78, 58, 38)
props_C_BLUE_MAIL = (54, 70, 108)
props_C_BLUE_MAIL_LIT = (70, 88, 128)
props_C_BOOTH = (60, 78, 96)
props_C_BOOTH_LIT = (78, 96, 112)
props_C_GLASS = (38, 50, 64)
props_C_SIGN = (150, 146, 134)
props_C_SIGN_DARK = (52, 56, 64)
props_C_ASPHALT_DARK = (44, 44, 46)
props_C_ASPHALT_RIM = (58, 58, 60)
props_C_ASPHALT_NOTCH = (34, 34, 36)
props_C_CONE = (162, 92, 52)
props_C_CONE_BAND = (188, 182, 168)
props_C_CONE_BASE = (44, 42, 44)
props_C_STONE = (104, 100, 94)
props_C_STONE_DARK = (78, 74, 70)
props_C_SOIL = (60, 50, 42)
props_C_SHRUB = (62, 80, 50)
props_C_SHRUB_LIT = (78, 96, 62)
props_C_NEWS = (66, 84, 86)
props_C_NEWS_LIT = (84, 102, 104)
props_C_SIGNAL_BOX = (46, 50, 46)
props_C_SIGNAL_LENS = (176, 142, 58)
props_C_SIGNAL_DEAD = (30, 34, 32)

props_SHADOW_ALPHA = 115              # 45% of 255

props_PROPS = [
    'streetlight', 'hydrant', 'trafficlight', 'dumpster', 'trashcan',
    'bench', 'mailbox', 'phonebooth', 'bus_stop', 'manhole', 'roadcone',
    'planter', 'newsbox',
]

# Props that never cast a shadow (flat on the ground).
props__FLAT = frozenset(('manhole',))

# Ground anchor of each sprite, measured from its top-left pixel.
props__ANCHORS = {
    'streetlight': (4, 10),
    'hydrant': (3, 7),
    'trafficlight': (3, 9),
    'dumpster': (7, 9),
    'trashcan': (3, 7),
    'bench': (6, 5),
    'mailbox': (4, 8),
    'phonebooth': (4, 10),
    'bus_stop': (2, 12),
    'manhole': (5, 5),
    'roadcone': (3, 8),
    'planter': (5, 10),
    'newsbox': (4, 9),
}

props__SPRITES = {}
props__SHADOWS = {}
props__BAKED = False


# ============================================================
# Deterministic hash (local copy of main.props__noise)
# ============================================================
def props__noise(c, r, salt=0):
    """Same integer hash main.py uses, so placement never flickers."""
    n = (c * 73856093) ^ (r * 19349663) ^ (salt * 83492791)
    n &= 0x7fffffff
    n = ((n * 1103515245) >> 16) & 0x7fffffff
    return n


# ============================================================
# Sprite drawing helpers
# ============================================================
def props__surf(w, h):
    return pygame.Surface((w, h), pygame.SRCALPHA)


def props__box(s, x, y, w, h, fill, outline=props_C_OUT):
    """Outlined rectangle: 1px near-black border with a flat fill inside."""
    if outline is not None:
        s.fill(outline, (x, y, w, h))
        if w > 2 and h > 2:
            s.fill(fill, (x + 1, y + 1, w - 2, h - 2))
    else:
        s.fill(fill, (x, y, w, h))


def props__rect(s, x, y, w, h, color):
    s.fill(color, (x, y, w, h))


# ============================================================
# Individual props (top-down, hard pixels, 1px outline)
# ============================================================
def props__build_streetlight():
    # Pole + arm reaching north, bright head, short warm pool on the pavement.
    s = props__surf(12, 12)
    pygame.draw.ellipse(s, (206, 190, 132, 34), (1, 2, 11, 10))
    pygame.draw.ellipse(s, (214, 198, 140, 52), (3, 4, 7, 6))
    # arm / pole
    props__box(s, 2, 3, 4, 8, props_C_POLE)
    props__rect(s, 3, 4, 1, 6, props_C_POLE_DARK)
    # lamp head
    props__box(s, 0, 0, 6, 5, props_C_LAMP_DIM)
    props__rect(s, 2, 2, 2, 1, props_C_LAMP)
    # base collar
    props__box(s, 1, 8, 6, 4, props_C_POLE_DARK)
    props__rect(s, 3, 9, 2, 2, props_C_POLE)
    return s


def props__build_hydrant():
    s = props__surf(7, 8)
    # side arms: outline band with the caps poking out past the body
    props__box(s, 0, 2, 7, 3, props_C_RED_DARK)
    props__rect(s, 0, 3, 7, 1, props_C_RED_LIT)
    # body
    props__box(s, 1, 0, 5, 8, props_C_RED)
    props__rect(s, 2, 1, 3, 1, props_C_RED_LIT)
    props__rect(s, 2, 6, 3, 1, props_C_RED_DARK)
    return s


def props__build_trafficlight():
    s = props__surf(7, 10)
    # signal housing
    props__box(s, 0, 0, 7, 7, props_C_SIGNAL_BOX)
    props__rect(s, 2, 1, 3, 3, props_C_SIGNAL_LENS)      # lit lamp
    props__rect(s, 3, 2, 1, 1, (206, 178, 96))     # hot centre
    props__rect(s, 2, 4, 3, 2, props_C_SIGNAL_DEAD)      # dark lenses
    # short pole below
    props__box(s, 1, 6, 4, 4, props_C_POLE)
    props__rect(s, 2, 7, 2, 2, props_C_POLE_DARK)
    return s


def props__build_dumpster():
    s = props__surf(14, 10)
    props__box(s, 0, 0, 14, 10, props_C_GREEN_BIN)
    props__rect(s, 1, 1, 12, 5, props_C_GREEN_BIN_LID)   # lids
    props__rect(s, 1, 5, 12, 1, props_C_GREEN_BIN_DARK)  # lid seam
    props__rect(s, 7, 1, 1, 4, props_C_GREEN_BIN_DARK)   # split between lids
    props__rect(s, 1, 8, 12, 1, props_C_GREEN_BIN_DARK)  # grimy base
    return s


def props__build_trashcan():
    s = props__surf(7, 8)
    props__box(s, 0, 0, 7, 8, props_C_METAL)
    props__rect(s, 1, 1, 5, 2, props_C_METAL_DARK)       # lid
    props__rect(s, 2, 4, 1, 3, props_C_METAL_DARK)       # ribs
    props__rect(s, 4, 4, 1, 3, props_C_METAL_DARK)
    return s


def props__build_bench():
    s = props__surf(12, 6)
    props__box(s, 0, 0, 12, 6, props_C_WOOD)
    props__rect(s, 1, 2, 10, 1, props_C_WOOD_DARK)       # slat seams
    props__rect(s, 1, 4, 10, 1, props_C_WOOD_DARK)
    props__rect(s, 2, 1, 1, 4, props_C_WOOD_DARK)        # legs
    props__rect(s, 9, 1, 1, 4, props_C_WOOD_DARK)
    return s


def props__build_mailbox():
    s = props__surf(8, 9)
    props__box(s, 0, 0, 8, 9, props_C_BLUE_MAIL)
    props__rect(s, 1, 1, 6, 2, props_C_BLUE_MAIL_LIT)    # rounded lid
    props__rect(s, 2, 4, 4, 1, (30, 38, 58))       # slot
    props__rect(s, 2, 7, 1, 1, props_C_OUT)              # legs
    props__rect(s, 5, 7, 1, 1, props_C_OUT)
    return s


def props__build_phonebooth():
    s = props__surf(9, 11)
    props__box(s, 0, 0, 9, 11, props_C_BOOTH)
    props__rect(s, 1, 1, 7, 2, props_C_BOOTH_LIT)        # roof cap
    props__rect(s, 2, 4, 5, 5, props_C_GLASS)            # glass
    props__rect(s, 4, 4, 1, 5, props_C_BOOTH)            # door frame
    return s


def props__build_bus_stop():
    s = props__surf(6, 13)
    props__box(s, 0, 0, 6, 7, props_C_SIGN)              # sign plate
    props__rect(s, 1, 2, 4, 1, props_C_SIGN_DARK)        # lettering suggestion
    props__rect(s, 1, 4, 3, 1, props_C_SIGN_DARK)
    props__box(s, 1, 6, 3, 7, props_C_POLE)              # pole
    return s


def props__build_manhole():
    # Flat on the asphalt: no outline, no shadow.
    s = props__surf(10, 10)
    pygame.draw.ellipse(s, props_C_ASPHALT_RIM, (0, 0, 10, 10))
    pygame.draw.ellipse(s, props_C_ASPHALT_DARK, (1, 1, 8, 8))
    props__rect(s, 3, 3, 4, 1, props_C_ASPHALT_NOTCH)
    props__rect(s, 3, 6, 4, 1, props_C_ASPHALT_NOTCH)
    return s


def props__build_roadcone():
    s = props__surf(7, 9)
    props__box(s, 0, 5, 7, 4, props_C_CONE_BASE)         # square base
    props__box(s, 1, 0, 5, 7, props_C_CONE)              # cone body
    props__rect(s, 2, 3, 3, 1, props_C_CONE_BAND)        # reflective band
    props__rect(s, 3, 1, 1, 1, (188, 116, 68))     # tip
    return s


def props__build_planter():
    s = props__surf(11, 11)
    props__box(s, 0, 0, 11, 11, props_C_STONE)
    props__rect(s, 1, 8, 9, 1, props_C_STONE_DARK)
    props__rect(s, 2, 2, 7, 6, props_C_SOIL)             # soil
    props__rect(s, 3, 3, 5, 4, props_C_SHRUB)            # shrub mass
    props__rect(s, 4, 3, 2, 1, props_C_SHRUB_LIT)
    props__rect(s, 3, 5, 1, 2, props_C_SHRUB_LIT)
    props__rect(s, 6, 6, 2, 1, props_C_SOIL)
    return s


def props__build_newsbox():
    s = props__surf(8, 10)
    props__box(s, 0, 0, 8, 10, props_C_NEWS)
    props__rect(s, 1, 1, 6, 1, props_C_NEWS_LIT)         # lid
    props__rect(s, 2, 3, 4, 4, props_C_GLASS)            # window
    props__rect(s, 3, 4, 2, 2, props_C_SIGN)             # paper behind glass
    props__rect(s, 2, 8, 1, 1, props_C_OUT)              # legs
    props__rect(s, 5, 8, 1, 1, props_C_OUT)
    return s


props__BUILDERS = {
    'streetlight': props__build_streetlight,
    'hydrant': props__build_hydrant,
    'trafficlight': props__build_trafficlight,
    'dumpster': props__build_dumpster,
    'trashcan': props__build_trashcan,
    'bench': props__build_bench,
    'mailbox': props__build_mailbox,
    'phonebooth': props__build_phonebooth,
    'bus_stop': props__build_bus_stop,
    'manhole': props__build_manhole,
    'roadcone': props__build_roadcone,
    'planter': props__build_planter,
    'newsbox': props__build_newsbox,
}


# ============================================================
# Baking
# ============================================================
def props__make_shadow(src, flat):
    """Hard-edged 45% black silhouette of the solid pixels."""
    w, h = src.get_size()
    sh = props__surf(w, h)
    if flat:
        return sh  # flat props cast nothing
    for y in range(h):
        for x in range(w):
            if src.get_at((x, y))[3] >= 200:   # skip soft glow pixels
                sh.set_at((x, y), (0, 0, 0, props_SHADOW_ALPHA))
    return sh


def props__convert(s):
    try:
        return s.convert_alpha()
    except pygame.error:
        return s


def props_bake():
    """Build every prop sprite + shadow once. Safe to call repeatedly."""
    global props__BAKED
    if props__BAKED:
        return
    for name in props_PROPS:
        src = props__BUILDERS[name]()
        props__SHADOWS[name] = props__convert(props__make_shadow(src, name in props__FLAT))
        props__SPRITES[name] = props__convert(src)
    props__BAKED = True


def props_get(name):
    """The baked sprite for a prop."""
    if not props__BAKED:
        props_bake()
    return props__SPRITES[name]


def props_get_shadow(name):
    """Hard-edged 45%-alpha black silhouette, for a south-east offset blit.
    Flat props (manhole) return a fully transparent surface."""
    if not props__BAKED:
        props_bake()
    return props__SHADOWS[name]


def props_anchor_offset(name):
    """Where the sprite's ground base sits relative to its blit point."""
    return props__ANCHORS[name]


# ============================================================
# Placement
# ============================================================
def props__is_road_line(i):
    return i >= 0 and (i - props_ROAD_ORIGIN) % props_ROAD_STEP == 0


def props__place(name, bx, by):
    """Clamp a prop so its sprite stays fully inside the 64px tile, then
    return its (name, anchor_x, anchor_y) triple."""
    ax, ay = props__ANCHORS[name]
    w, h = props__SPRITES[name].get_size() if props__BAKED else (14, 14)
    tx = min(max(bx - ax, 0), props_TILE_SIZE - w)
    ty = min(max(by - ay, 0), props_TILE_SIZE - h)
    return (name, tx + ax, ty + ay)


# Weighted grab-bag of small sidewalk clutter.
props__MISC = (
    ('hydrant', 3), ('trashcan', 3), ('planter', 3), ('bench', 2),
    ('mailbox', 2), ('newsbox', 2), ('bus_stop', 2), ('phonebooth', 1),
)
props__MISC_TABLE = []
for _n, _w in props__MISC:
    props__MISC_TABLE.extend([_n] * _w)

# Streetlights land on the tiles whose index along the street is 2 or 6
# mod 8: one every 4 tiles (256px), and never on a junction corner or the
# crossing itself, so every street keeps an unbroken rhythm.
props_LIGHT_PHASES = (2, 6)
props_MISC_CHANCE = 6        # percent of eligible sidewalk tiles with clutter
props_DUMPSTER_CHANCE = 4    # percent of alley-ish sidewalk tiles
props_MANHOLE_CHANCE = 3     # percent of road tiles
props_CONE_CHANCE = 2        # percent of road tiles


def props_props_for_tile(c, r, tile_type, is_sidewalk):
    """Deterministic list of (name, offset_x, offset_y) for tile (c, r).

    Offsets are the prop's ground anchor in pixels inside the 64x64 tile.
    Most tiles return []; props are deliberately sparse (roughly 4-10 on a
    640x360 screen)."""
    if not props__BAKED:
        props_bake()

    # --- Road surface: manholes and cones only, and rarely ---
    if tile_type == props_TILE_ROAD:
        n = props__noise(c, r, 41)
        roll = n % 100
        vertical = props__is_road_line(c)
        horizontal = props__is_road_line(r)
        if roll < props_MANHOLE_CHANCE:
            if vertical and horizontal:
                return [props__place('manhole', 32, 32)]
            if vertical:
                return [props__place('manhole', 32, 10 + (n >> 7) % 44)]
            return [props__place('manhole', 10 + (n >> 7) % 44, 32)]
        if roll < props_MANHOLE_CHANCE + props_CONE_CHANCE:
            if vertical:
                return [props__place('roadcone', 14 + (n >> 11) % 8, 12 + (n >> 5) % 40)]
            return [props__place('roadcone', 12 + (n >> 5) % 40, 14 + (n >> 11) % 8)]
        return []

    # --- Everything else is furniture, sidewalks only ---
    if tile_type in (props_TILE_WATER, props_TILE_BUILDING) or not is_sidewalk:
        return []

    road_e = props__is_road_line(c + 1)
    road_w = props__is_road_line(c - 1)
    road_s = props__is_road_line(r + 1)
    road_n = props__is_road_line(r - 1)
    if not (road_e or road_w or road_s or road_n):
        return []  # not actually kerbside

    vert_street = road_e or road_w
    horz_street = road_s or road_n
    corner = vert_street and horz_street

    # Curb bands: sit just inside the tile edge that faces the street.
    cx = 58 if road_e else (6 if road_w else 32)
    cy = 58 if road_s else (14 if road_n else 32)

    n = props__noise(c, r, 47)

    # 1. Traffic lights: only where a horizontal and a vertical street meet,
    #    and only on two opposite corners so junctions stay readable.
    if corner:
        if (road_e and road_s) or (road_w and road_n):
            return [props__place('trafficlight', cx, cy)]
        return []

    # 2. Streetlights: a regular rhythm down one side of each street.
    if vert_street and road_e:                       # west kerb of a N-S street
        if r % props_ROAD_STEP in props_LIGHT_PHASES:
            return [props__place('streetlight', cx, 20 + (n % 24))]
    elif horz_street and road_s:                     # north kerb of an E-W street
        if c % props_ROAD_STEP in props_LIGHT_PHASES:
            return [props__place('streetlight', 20 + (n % 24), cy)]

    # 3. Dumpsters: alley-ish, away from the junctions.
    near_junction = props__near_intersection(c, r)
    roll = n % 100
    if not near_junction and roll < props_DUMPSTER_CHANCE:
        if vert_street:
            return [props__place('dumpster', cx, 18 + ((n >> 9) % 28))]
        return [props__place('dumpster', 18 + ((n >> 9) % 28), cy)]

    # 4. Sparse small clutter along the kerb.
    if props_DUMPSTER_CHANCE <= roll < props_DUMPSTER_CHANCE + props_MISC_CHANCE:
        name = props__MISC_TABLE[(n >> 13) % len(props__MISC_TABLE)]
        if vert_street:
            return [props__place(name, cx, 14 + ((n >> 17) % 36))]
        return [props__place(name, 14 + ((n >> 17) % 36), cy)]

    return []


def props__near_intersection(c, r):
    """True if this tile touches the 3x3 block around a road crossing."""
    for dc in (-1, 0, 1):
        if not props__is_road_line(c + dc):
            continue
        for dr in (-1, 0, 1):
            if props__is_road_line(r + dr):
                return True
    return False


# ==========================================================
# Baked art: gfx_roofs
# ==========================================================
"""Rooftop detail generator for the GTA1-style St. Louis sandbox.

Self-contained: imports only pygame and math. Every placement is derived
from a LOCAL copy of main.py's roofs__noise hash, so a given tile always draws
the identical rooftop on every frame (draw() runs at 60fps - any
nondeterminism would flicker).

Public API:
    roofs_bake()
    roofs_ROOF_STYLES
    roofs_style_for(c, r, landmark_name)
    roofs_draw_roof_detail(surface, roof_rect, base_color, c, r, style)
    roofs_roof_base_variants(base_color, c, r)

Lighting convention matches the map: every raised element casts a small
SOUTH-EAST shadow (+x, +y).
"""


# ============================================================
# Deterministic hashing (local copy - do not import from main)
# ============================================================


def roofs__noise(c, r, salt=0):
    """Same hash main.py uses for tile texturing."""
    n = (c * 73856093) ^ (r * 19349663) ^ (salt * 83492791)
    n &= 0x7fffffff
    n = ((n * 1103515245) >> 16) & 0x7fffffff
    return n


def roofs__name_hash(name):
    """Stable FNV-1a over a string. Python's built-in hash() for str is
    randomised per process, so it cannot be used for determinism."""
    h = 2166136261
    for ch in name:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h & 0x7FFFFFFF


# ============================================================
# Colour helpers - everything derives from the tile's base colour
# ============================================================

roofs__SHADE_CACHE = {}

# Absolute colours are limited to glass, gravel speckle and bare metal.
roofs__GLASS = (186, 206, 220)
roofs__GLASS_DEEP = (120, 146, 166)
roofs__GRIT_DARK = (34, 33, 35)
roofs__GRIT_LIGHT = (126, 122, 116)
roofs__METAL = (148, 150, 148)
roofs__METAL_DARK = (72, 74, 74)


def roofs__shade(color, f):
    """Multiply/lighten a colour by f, memoised (quantised to 1%)."""
    fq = int(f * 100)
    key = (color[0], color[1], color[2], fq)
    v = roofs__SHADE_CACHE.get(key)
    if v is None:
        v = (min(255, (color[0] * fq) // 100),
             min(255, (color[1] * fq) // 100),
             min(255, (color[2] * fq) // 100))
        roofs__SHADE_CACHE[key] = v
    return v


def roofs_roof_base_variants(base_color, c, r):
    """Slight deterministic per-tile variation so a big landmark block is
    not one flat colour. Returns (fill, edge, trim)."""
    n = roofs__noise(c, r, 17)
    f = 0.93 + (n % 13) * 0.012          # 0.93 .. 1.07
    return roofs__shade(base_color, f), roofs__shade(base_color, 0.55), roofs__shade(base_color, 1.22)


# ============================================================
# Styles
# ============================================================

roofs_ROOF_STYLES = [
    'gravel',      # tar-and-gravel speckle plus a couple of vents
    'hvac',        # cluster of AC units with dark grilles
    'skylight',    # pale glass panels with a frame cross
    'watertower',  # round tank on legs - midwest rooftop staple
    'stairbox',    # roof access hut with a door edge
    'vents',       # row of small pipe circles
    'helipad',     # big circle with an H (rare, tall landmarks only)
    'billboard',   # raised sign panel on a strut
    'ductwork',    # long thin duct runs snaking across the roof
]

# Weighted pools. helipad never appears outside tall landmarks.
roofs__COMMON_POOL = ('gravel', 'gravel', 'gravel', 'hvac', 'hvac', 'vents',
                'vents', 'ductwork', 'skylight', 'stairbox', 'watertower',
                'billboard')

roofs__LANDMARK_POOL = ('hvac', 'gravel', 'ductwork', 'skylight', 'watertower',
                  'vents', 'stairbox', 'gravel', 'billboard', 'hvac')

# Name fragments that suggest a tall downtown structure (helipad candidates).
roofs__TALL_HINTS = ('downtown', 'arch', 'stadium', 'center', 'centre', 'tower',
               'plaza', 'bank', 'district')

# Styles whose feature is a single object - shown on only some tiles of a
# multi-tile block so a landmark does not grow a forest of water towers.
roofs__SPARSE = {'watertower': 6, 'stairbox': 4, 'billboard': 6, 'helipad': 7}

roofs__STYLE_CACHE = {}
roofs__SPECKLE = []
roofs__DISPATCH = {}
roofs__BAKED = False


def roofs__is_tall(name):
    low = name.lower()
    for k in roofs__TALL_HINTS:
        if k in low:
            return True
    return False


def roofs_style_for(c, r, landmark_name):
    """Deterministic style pick. A landmark hashes on its NAME so every
    tile of the same building shares one style and the block reads as a
    single structure."""
    key = (c, r, landmark_name)
    s = roofs__STYLE_CACHE.get(key)
    if s is not None:
        return s
    if landmark_name:
        h = roofs__name_hash(landmark_name)
        # helipad is reserved for tall downtown-ish landmarks, and rare
        if (h % 5) == 0 and roofs__is_tall(landmark_name):
            s = 'helipad'
        else:
            s = roofs__LANDMARK_POOL[(h >> 14) % len(roofs__LANDMARK_POOL)]
    else:
        s = roofs__COMMON_POOL[roofs__noise(c, r, 101) % len(roofs__COMMON_POOL)]
    roofs__STYLE_CACHE[key] = s
    return s


def roofs_bake():
    """Precompute lookup tables. Cheap, idempotent, no display needed."""
    global roofs__BAKED
    del roofs__SPECKLE[:]
    for i in range(48):
        n = roofs__noise(i * 3 + 1, i * 11 + 7, 1013)
        m = roofs__noise(i * 7 + 5, i * 5 + 2, 2027)
        roofs__SPECKLE.append(((n >> 3) & 0xFF, (m >> 5) & 0xFF))
    roofs__SHADE_CACHE.clear()
    roofs__STYLE_CACHE.clear()
    roofs__DISPATCH.clear()
    roofs__DISPATCH.update({
        'gravel': roofs__d_gravel,
        'hvac': roofs__d_hvac,
        'skylight': roofs__d_skylight,
        'watertower': roofs__d_watertower,
        'stairbox': roofs__d_stairbox,
        'vents': roofs__d_vents,
        'helipad': roofs__d_helipad,
        'billboard': roofs__d_billboard,
        'ductwork': roofs__d_ductwork,
    })
    roofs__BAKED = True


# ============================================================
# Small drawing primitives (surface.fill is clipped and fast)
# ============================================================


def roofs__gate(c, r, salt, one_in):
    return (roofs__noise(c, r, salt) % one_in) == 0


def roofs__speckle(surf, x, y, w, h, base, c, r, count):
    """Fixed number of gravel dots from the baked offset table."""
    dark = roofs__shade(base, 0.74)
    lite = roofs__shade(base, 1.16)
    span_x = max(1, w - 6)
    span_y = max(1, h - 6)
    idx = roofs__noise(c, r, 23) % (len(roofs__SPECKLE) - count)
    for i in range(count):
        fx, fy = roofs__SPECKLE[idx + i]
        px = x + 3 + (fx * span_x >> 8)
        py = y + 3 + (fy * span_y >> 8)
        if i & 1:
            surf.fill(lite, (px, py, 2, 2))
        else:
            surf.fill(dark, (px, py, 3, 2))
    # a pinch of true grit so the tar reads as tar
    fx, fy = roofs__SPECKLE[idx]
    surf.fill(roofs__GRIT_DARK, (x + 3 + (fy * span_x >> 8), y + 3 + (fx * span_y >> 8), 2, 2))
    fx, fy = roofs__SPECKLE[idx + 1]
    surf.fill(roofs__GRIT_LIGHT, (x + 3 + (fy * span_x >> 8), y + 3 + (fx * span_y >> 8), 1, 2))


def roofs__pipe(surf, cx, cy, rad, sh):
    """A vent pipe: SE shadow blob, metal ring, dark throat."""
    pygame.draw.circle(surf, sh, (cx + 1, cy + 2), rad)
    pygame.draw.circle(surf, roofs__METAL, (cx, cy), rad)
    pygame.draw.circle(surf, roofs__METAL_DARK, (cx, cy), max(1, rad - 2))


def roofs__accent(surf, x, y, w, h, base, c, r, always=False):
    """Per-tile extra so a large single-style block still varies. Forced on
    the tiles of a sparse style that did not get the main feature, so no
    rooftop is left bare."""
    n = roofs__noise(c, r, 907)
    if not always and n % 5:
        return
    sh = roofs__shade(base, 0.30)
    ax = x + 5 + ((n >> 5) % max(1, w - 16))
    ay = y + 5 + ((n >> 11) % max(1, h - 16))
    if (n >> 3) & 1:
        roofs__pipe(surf, ax + 3, ay + 3, 3, sh)
    else:
        surf.fill(sh, (ax + 2, ay + 2, 8, 7))
        surf.fill(roofs__shade(base, 0.8), (ax, ay, 8, 7))
        surf.fill(roofs__shade(base, 1.1), (ax, ay, 8, 2))
    if always and ((n >> 17) & 1):
        bx = x + 4 + ((n >> 19) % max(1, w - 14))
        by = y + 4 + ((n >> 23) % max(1, h - 10))
        surf.fill(sh, (bx + 1, by + 1, 11, 4))          # low kerb / duct stub
        surf.fill(roofs__shade(base, 0.86), (bx, by, 11, 4))


# ============================================================
# Style renderers - x, y, w, h are the roof rect in screen space
# ============================================================


def roofs__d_gravel(surf, x, y, w, h, base, c, r):
    roofs__speckle(surf, x, y, w, h, base, c, r, 10)
    sh = roofs__shade(base, 0.30)
    n = roofs__noise(c, r, 29)
    roofs__pipe(surf, x + 8 + (n % max(1, w - 18)), y + 8 + ((n >> 9) % max(1, h - 18)), 3, sh)
    roofs__pipe(surf, x + 6 + ((n >> 5) % max(1, w - 14)), y + 10 + ((n >> 17) % max(1, h - 20)), 2, sh)


def roofs__d_hvac(surf, x, y, w, h, base, c, r):
    n = roofs__noise(c, r, 31)
    count = 2 + (n % 3)
    body = roofs__shade(base, 0.80)
    top = roofs__shade(base, 1.12)
    grille = roofs__shade(base, 0.42)
    sh = roofs__shade(base, 0.28)
    roofs__speckle(surf, x, y, w, h, base, c, r, 3)
    for i in range(count):
        m = roofs__noise(c, r, 41 + i)
        uw = 10 + (m % 9)
        uh = 8 + ((m >> 5) % 8)
        ux = x + 2 + ((m >> 9) % max(1, w - uw - 5))
        uy = y + 2 + ((m >> 15) % max(1, h - uh - 5))
        surf.fill(sh, (ux + 2, uy + 2, uw, uh))
        surf.fill(body, (ux, uy, uw, uh))
        surf.fill(top, (ux, uy, uw, 2))
        surf.fill(grille, (ux + 2, uy + 3, uw - 4, uh - 5))


def roofs__d_skylight(surf, x, y, w, h, base, c, r):
    n = roofs__noise(c, r, 51)
    count = 1 + (n & 1)
    frame = roofs__shade(base, 0.50)
    sh = roofs__shade(base, 0.30)
    roofs__speckle(surf, x, y, w, h, base, c, r, 4)
    for i in range(count):
        m = roofs__noise(c, r, 61 + i)
        pw = 14 + (m % 10)
        ph = 10 + ((m >> 4) % 9)
        px = x + 3 + ((m >> 8) % max(1, w - pw - 7))
        py = y + 3 + ((m >> 14) % max(1, h - ph - 7))
        surf.fill(sh, (px + 1, py + 1, pw, ph))
        surf.fill(frame, (px, py, pw, ph))
        surf.fill(roofs__GLASS_DEEP, (px + 1, py + 1, pw - 2, ph - 2))
        surf.fill(roofs__GLASS, (px + 1, py + 1, pw - 2, (ph - 2) // 2))
        surf.fill(frame, (px + pw // 2, py + 1, 1, ph - 2))
        surf.fill(frame, (px + 1, py + ph // 2, pw - 2, 1))


def roofs__d_watertower(surf, x, y, w, h, base, c, r):
    roofs__speckle(surf, x, y, w, h, base, c, r, 8)
    if not roofs__gate(c, r, 73, roofs__SPARSE['watertower']):
        roofs__accent(surf, x, y, w, h, base, c, r, True)
        return
    n = roofs__noise(c, r, 71)
    rad = 9 + (n % 4)
    cx = x + rad + 4 + ((n >> 4) % max(1, w - 2 * rad - 9))
    cy = y + rad + 5 + ((n >> 12) % max(1, h - 2 * rad - 11))
    sh = roofs__shade(base, 0.28)
    tank = roofs__shade(base, 0.88)
    band = roofs__shade(base, 0.58)
    lit = roofs__shade(base, 1.18)
    # cast shadow on the roof, south-east
    pygame.draw.ellipse(surf, sh, (cx - rad + 3, cy + rad // 2, rad * 2, rad))
    # legs under the tank
    pygame.draw.line(surf, roofs__METAL_DARK, (cx - rad + 3, cy + 2), (cx - rad + 1, cy + rad + 3), 2)
    pygame.draw.line(surf, roofs__METAL_DARK, (cx, cy + 2), (cx + 1, cy + rad + 4), 2)
    pygame.draw.line(surf, roofs__METAL_DARK, (cx + rad - 3, cy + 2), (cx + rad - 1, cy + rad + 3), 2)
    pygame.draw.circle(surf, tank, (cx, cy), rad)
    pygame.draw.circle(surf, lit, (cx - 2, cy - 2), max(1, rad - 4))
    pygame.draw.circle(surf, band, (cx, cy), rad, 1)
    pygame.draw.arc(surf, lit, (cx - rad, cy - rad, rad * 2, rad * 2),
                    math.pi * 0.55, math.pi * 1.35, 2)


def roofs__d_stairbox(surf, x, y, w, h, base, c, r):
    roofs__speckle(surf, x, y, w, h, base, c, r, 8)
    if not roofs__gate(c, r, 79, roofs__SPARSE['stairbox']):
        roofs__accent(surf, x, y, w, h, base, c, r, True)
        return
    n = roofs__noise(c, r, 81)
    bw = 16 + (n % 7)
    bh = 13 + ((n >> 5) % 6)
    bx = x + 3 + ((n >> 10) % max(1, w - bw - 7))
    by = y + 3 + ((n >> 16) % max(1, h - bh - 7))
    sh = roofs__shade(base, 0.26)
    wall = roofs__shade(base, 0.72)
    top = roofs__shade(base, 1.14)
    edge = roofs__shade(base, 0.44)
    surf.fill(sh, (bx + 3, by + 3, bw, bh))
    surf.fill(wall, (bx, by, bw, bh))
    surf.fill(top, (bx, by, bw, bh - 4))          # lit upper face
    pygame.draw.rect(surf, edge, (bx, by, bw, bh), 1)
    surf.fill(edge, (bx + bw - 7, by + 4, 5, bh - 5))   # door on the east face
    surf.fill(roofs__shade(base, 0.90), (bx + bw - 7, by + 4, 1, bh - 5))


def roofs__d_vents(surf, x, y, w, h, base, c, r):
    n = roofs__noise(c, r, 91)
    roofs__speckle(surf, x, y, w, h, base, c, r, 4)
    sh = roofs__shade(base, 0.30)
    rail = roofs__shade(base, 0.62)
    count = 3 + (n % 3)
    ry = y + 8 + ((n >> 7) % max(1, h - 20))
    rx = x + 5 + ((n >> 13) % max(1, w - 8 * count - 8))
    surf.fill(rail, (rx - 2, ry + 1, count * 8 + 2, 2))
    for i in range(count):
        rad = 3 if (n >> i) & 1 else 2
        roofs__pipe(surf, rx + i * 8, ry - ((n >> (i + 3)) & 1), rad, sh)


def roofs__d_helipad(surf, x, y, w, h, base, c, r):
    roofs__speckle(surf, x, y, w, h, base, c, r, 8)
    if not roofs__gate(c, r, 97, roofs__SPARSE['helipad']):
        roofs__accent(surf, x, y, w, h, base, c, r, True)
        return
    cx = x + w // 2
    cy = y + h // 2
    rad = min(w, h) // 2 - 4
    if rad < 6:
        return
    pad = roofs__shade(base, 0.84)
    mark = roofs__shade(base, 1.45)
    ring = roofs__shade(base, 0.50)
    pygame.draw.circle(surf, pad, (cx, cy), rad)
    pygame.draw.circle(surf, mark, (cx, cy), rad, 2)
    pygame.draw.circle(surf, ring, (cx, cy), rad - 4, 1)
    hw = rad // 2
    hh = rad - 3
    surf.fill(mark, (cx - hw, cy - hh // 2, 3, hh))
    surf.fill(mark, (cx + hw - 3, cy - hh // 2, 3, hh))
    surf.fill(mark, (cx - hw, cy - 1, hw * 2, 3))


def roofs__d_billboard(surf, x, y, w, h, base, c, r):
    roofs__speckle(surf, x, y, w, h, base, c, r, 8)
    if not roofs__gate(c, r, 103, roofs__SPARSE['billboard']):
        roofs__accent(surf, x, y, w, h, base, c, r, True)
        return
    n = roofs__noise(c, r, 107)
    pw = 24 + (n % 12)
    ph = 10 + ((n >> 5) % 5)
    px = x + 3 + ((n >> 9) % max(1, w - pw - 7))
    py = y + 4 + ((n >> 15) % max(1, h - ph - 16))
    sh = roofs__shade(base, 0.24)
    frame = roofs__shade(base, 0.46)
    # sign face: a faded ad, channel-rotated off the building's own colour
    face = (min(255, base[2] * 115 // 100), min(255, base[0] * 90 // 100),
            min(255, base[1] * 105 // 100))
    # raised: shadow falls further south-east than a flat object's
    surf.fill(sh, (px + 4, py + 6, pw, ph))
    pygame.draw.line(surf, frame, (px + 4, py + ph), (px + 5, py + ph + 6), 2)
    pygame.draw.line(surf, frame, (px + pw - 5, py + ph), (px + pw - 4, py + ph + 6), 2)
    surf.fill(frame, (px, py, pw, ph))
    surf.fill(face, (px + 1, py + 1, pw - 2, ph - 2))
    surf.fill(roofs__shade(face, 1.35), (px + 3, py + 3, pw - 8, 2))
    surf.fill(roofs__shade(face, 0.70), (px + 3, py + ph - 4, pw // 2, 2))


def roofs__d_ductwork(surf, x, y, w, h, base, c, r):
    n = roofs__noise(c, r, 111)
    roofs__speckle(surf, x, y, w, h, base, c, r, 4)
    sh = roofs__shade(base, 0.28)
    duct = roofs__shade(base, 0.86)
    lit = roofs__shade(base, 1.15)
    seam = roofs__shade(base, 0.60)
    t = 6 + (n % 3)                                  # duct thickness
    ry = y + 6 + ((n >> 5) % max(1, h - t - 14))     # horizontal run
    cx = x + 8 + ((n >> 11) % max(1, w - t - 18))    # vertical run
    # horizontal run
    surf.fill(sh, (x + 2, ry + 2, w - 4, t))
    surf.fill(duct, (x, ry, w, t))
    surf.fill(lit, (x, ry, w, 2))
    surf.fill(seam, (x + w // 3, ry, 1, t))
    # vertical run dropping south off the elbow
    surf.fill(sh, (cx + 2, ry + 2, t, h - (ry - y) - 2))
    surf.fill(duct, (cx, ry, t, h - (ry - y)))
    surf.fill(lit, (cx, ry, 2, h - (ry - y)))
    surf.fill(seam, (cx, ry + (h - (ry - y)) // 2, t, 1))
    # elbow junction box
    surf.fill(sh, (cx, ry - 1, t + 4, t + 4))
    surf.fill(roofs__shade(base, 0.94), (cx - 2, ry - 3, t + 4, t + 4))


# ============================================================
# Entry point
# ============================================================


def roofs_draw_roof_detail(surface, roof_rect, base_color, c, r, style):
    """Draw one tile's rooftop clutter into surface, strictly clipped to
    roof_rect (which is already in screen space)."""
    if not roofs__BAKED:
        roofs_bake()
    if not isinstance(roof_rect, pygame.Rect):
        roof_rect = pygame.Rect(roof_rect)
    w = roof_rect.width
    h = roof_rect.height
    if w < 12 or h < 12:
        return
    prev = surface.get_clip()
    area = roof_rect.clip(prev) if prev is not None else roof_rect
    if area.width <= 0 or area.height <= 0:
        return
    surface.set_clip(area)
    try:
        roofs__DISPATCH.get(style, roofs__d_gravel)(surface, roof_rect.x, roof_rect.y, w, h,
                                        base_color, c, r)
    finally:
        surface.set_clip(prev)


roofs_bake()



# ==========================================================
# Baked art: gfx_parking
# ==========================================================
"""Kerbside parking spots for the top-down GTA1-style St. Louis sandbox.

Most cars in GTA1 are PARKED at the kerb; only a few are actually moving.
This module answers the one question main.py needs: "where would a parked car
believably sit?"  It returns world-pixel centres plus a heading, so the caller
can spawn a Car there with driver=None and simply never call wander_ai() on it.

Design
    * Roads are a 1-tile grid (a tile is road if its col OR row is a road line),
      so every street is exactly one 64px tile wide.  A 34x18 car parked
      14-18px off the centre line sits tight against the kerb and leaves the
      rest of the tile as a driving lane.
    * Spots are never placed on a junction tile or the tile next to one - real
      kerbs are kept clear near corners, and it keeps intersections readable.
    * Slots are packed at parking_SLOT_SPACING px along the street, then thinned into
      runs of 2-5 cars with gaps, so kerbs look occupied rather than walled in.
    * Opposite kerbs never take the same longitudinal slot, so there is always
      a clear channel down every street for moving traffic.
    * Everything is derived from a deterministic hash: the same map always
      produces the same car park, with no use of `random` at call time.

Public API
    parking_set_blocked_fn(fn)                        inject main.is_blocked
    parking_parking_spots(max_count, near, radius)    -> [(x, y, angle, side), ...]
    parking_spots_in_rect(rect)                       -> [(x, y, angle, side), ...]
    parking_nearest_spot(x, y)                        -> (x, y, angle, side) or None
    parking_is_legal_spot(x, y, angle)                -> bool

`angle` is radians with 0 = east and +Y down, matching Car.angle.
`side` is -1 for the west/north kerb and +1 for the east/south kerb.
"""


# --- Map constants (mirrored from main.py; this module never imports main) ---
parking_TILE_SIZE = 64
parking_MAP_TILES_W = 100
parking_MAP_TILES_H = 100
parking_MAP_WIDTH = parking_MAP_TILES_W * parking_TILE_SIZE
parking_MAP_HEIGHT = parking_MAP_TILES_H * parking_TILE_SIZE

# main.py: road_lines = set(range(4, parking_MAP_TILES_W, 8))
parking_ROAD_ORIGIN = 4
parking_ROAD_STEP = 8
parking_ROAD_LINES = tuple(range(parking_ROAD_ORIGIN, parking_MAP_TILES_W, parking_ROAD_STEP))
parking__ROAD_SET = frozenset(parking_ROAD_LINES)

parking_WATER_COL_START = parking_MAP_TILES_W - 3       # cols 97-99 are river, unless road

parking_CAR_W = 34                              # Car collision rect, nose to tail
parking_CAR_H = 18

# --- Parking layout ---
parking_KERB_OFFSET_MIN = 14        # px from the tile centre line to the car centre
parking_KERB_OFFSET_MAX = 18
parking_SLOT_SPACING = 38           # 34px car + a 4px bumper gap
parking_MIN_SLOTS_PER_SEGMENT = 2   # a stub too short for a pair gets no parking
parking_RUN_MIN = 2                 # cars per unbroken run
parking_RUN_MAX = 5
parking_GAP_MIN = 1                 # empty slots between runs
parking_GAP_MAX = 3
parking_EMPTY_SEGMENT_PCT = 22      # percent of (block, kerb) pairs left bare

# Headings, radians, 0 = east, +Y down.
parking_ANG_E = 0.0
parking_ANG_S = math.pi * 0.5
parking_ANG_W = math.pi
parking_ANG_N = math.pi * 1.5

parking_AXIS_NS = 0                 # street runs north-south (a road COLUMN)
parking_AXIS_EW = 1                 # street runs east-west   (a road ROW)

# Landmark footprints, derived from LANDMARKS: (col, row, w, h, collidable).
# They are stamped over the road grid, so a "road" tile inside one can actually
# be a building wall or the middle of Forest Park - no kerb parking there.
# Parks stay open (collidable=False); anything built blocks kerb parking.
parking__LANDMARKS = tuple(
    (lx, ly, lw, lh, kind != "park")
    for (lx, ly, lw, lh, kind, _name, _color) in LANDMARKS
)


def parking__tile_set(collidable_only):
    out = set()
    for (lx, ly, lw, lh, solid) in parking__LANDMARKS:
        if collidable_only and not solid:
            continue
        for r in range(ly, min(ly + lh, parking_MAP_TILES_H)):
            for c in range(lx, min(lx + lw, parking_MAP_TILES_W)):
                out.add((c, r))
    return frozenset(out)


parking__SOLID_LANDMARK_TILES = parking__tile_set(True)
parking__ANY_LANDMARK_TILES = parking__tile_set(False)


def parking__noise(c, r, salt=0):
    """Deterministic pseudo-random hash (local copy of main.parking__noise)."""
    n = (c * 73856093) ^ (r * 19349663) ^ (salt * 83492791)
    n &= 0x7fffffff
    n = ((n * 1103515245) >> 16) & 0x7fffffff
    return n


def parking_is_road_line(i):
    return i in parking__ROAD_SET


def parking_is_road_tile(c, r):
    """Geometric road test, ignoring whatever got stamped on top."""
    if not (0 <= c < parking_MAP_TILES_W and 0 <= r < parking_MAP_TILES_H):
        return False
    return c in parking__ROAD_SET or r in parking__ROAD_SET


def parking__tile_collidable(c, r):
    """Exact mirror of main.build_map's collidable flag, for standalone use."""
    if not (0 <= c < parking_MAP_TILES_W and 0 <= r < parking_MAP_TILES_H):
        return True                      # off-map counts as solid
    if (c, r) in parking__SOLID_LANDMARK_TILES:
        return True                      # landmarks are stamped last
    if c in parking__ROAD_SET or r in parking__ROAD_SET:
        return False                     # roads beat the river band
    return c >= parking_WATER_COL_START


def parking__fallback_blocked(rect):
    """Stand-in for main.is_blocked when no blocked-fn has been injected."""
    c0 = max(0, rect.left // parking_TILE_SIZE)
    c1 = min(parking_MAP_TILES_W - 1, (rect.right - 1) // parking_TILE_SIZE)
    r0 = max(0, rect.top // parking_TILE_SIZE)
    r1 = min(parking_MAP_TILES_H - 1, (rect.bottom - 1) // parking_TILE_SIZE)
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            if parking__tile_collidable(c, r):
                return True
    return False


parking__blocked_fn = None
parking__cache = None


def parking_set_blocked_fn(fn):
    """Inject main.is_blocked (or any rect -> bool) and drop the cache."""
    global parking__blocked_fn, parking__cache
    parking__blocked_fn = fn
    parking__cache = None


def parking_car_rect(x, y, angle):
    """Axis-aligned bounds of a 34x18 car centred at (x, y) at that heading.

    Exact for the four cardinal headings parked cars actually use; a safe
    over-estimate for anything in between.
    """
    ca = abs(math.cos(angle))
    sa = abs(math.sin(angle))
    hw = (parking_CAR_W * ca + parking_CAR_H * sa) * 0.5
    hh = (parking_CAR_W * sa + parking_CAR_H * ca) * 0.5
    left = int(math.floor(x - hw + 0.5))
    top = int(math.floor(y - hh + 0.5))
    right = int(math.floor(x + hw + 0.5))
    bottom = int(math.floor(y + hh + 0.5))
    return pygame.Rect(left, top, right - left, bottom - top)


def parking_is_legal_spot(x, y, angle):
    """True if a parked car fits here without clipping scenery or the map edge."""
    rect = parking_car_rect(x, y, angle)
    if rect.left < 0 or rect.top < 0 or rect.right > parking_MAP_WIDTH or rect.bottom > parking_MAP_HEIGHT:
        return False
    blocked = parking__blocked_fn or parking__fallback_blocked
    return not blocked(rect)


# --- Street segmentation -----------------------------------------------------
# Along any street, the tile index across it is illegal when it is a junction
# line or within one tile of one.  Both axes share the same road-line set, so
# one list of legal runs serves every street.

def parking__legal_runs():
    banned = set()
    for line in parking_ROAD_LINES:
        banned.update((line - 1, line, line + 1))
    runs = []
    start = None
    for i in range(parking_MAP_TILES_H):
        if i in banned:
            if start is not None:
                runs.append((start, i - 1))
                start = None
        elif start is None:
            start = i
    if start is not None:
        runs.append((start, parking_MAP_TILES_H - 1))
    return tuple(runs)


parking__SEGMENTS = parking__legal_runs()


def parking__run_indices(n, axis, line, seg, side):
    """Which of a block's n slots are occupied: runs of 2-5 cars with gaps."""
    salt = 700 + axis * 13 + (0 if side < 0 else 7)
    h0 = parking__noise(line, seg, salt)
    if h0 % 100 < parking_EMPTY_SEGMENT_PCT:
        return ()
    out = []
    j = h0 % 2                      # nudge the first run off the block start
    step = 0
    while j < n:
        h = parking__noise(line * 31 + seg, j + step * 17, salt + 1)
        run = parking_RUN_MIN + h % (parking_RUN_MAX - parking_RUN_MIN + 1)
        for _ in range(run):
            if j >= n:
                break
            out.append(j)
            j += 1
        j += parking_GAP_MIN + ((h >> 9) % (parking_GAP_MAX - parking_GAP_MIN + 1))
        step += 1
    return tuple(out)


def parking__heading(axis, side):
    """Parked as if the car pulled in facing with traffic."""
    if axis == parking_AXIS_NS:
        return parking_ANG_N if side < 0 else parking_ANG_S      # west kerb north, east kerb south
    return parking_ANG_E if side < 0 else parking_ANG_W          # north kerb east, south kerb west


def parking__build():
    """Generate every legal kerb spot on the map.  Deterministic."""
    spots = []
    for axis in (parking_AXIS_NS, parking_AXIS_EW):
        for line in parking_ROAD_LINES:
            centre = line * parking_TILE_SIZE + parking_TILE_SIZE // 2
            for seg, (i0, i1) in enumerate(parking__SEGMENTS):
                seg_px = i0 * parking_TILE_SIZE
                seg_len = (i1 - i0 + 1) * parking_TILE_SIZE
                n = seg_len // parking_SLOT_SPACING
                if n < parking_MIN_SLOTS_PER_SEGMENT:
                    continue
                # Centre the slot run inside the block so both ends stay clear
                # of the junction-adjacent tiles.
                base = seg_px + (seg_len - n * parking_SLOT_SPACING) // 2 + parking_SLOT_SPACING // 2

                first = -1 if (parking__noise(line, seg, 101 + axis) >> 3) & 1 == 0 else 1
                taken = set()
                for side in (first, -first):
                    angle = parking__heading(axis, side)
                    for j in parking__run_indices(n, axis, line, seg, side):
                        if j in taken:
                            continue        # keep the opposite kerb clear here
                        taken.add(j)
                        along = base + j * parking_SLOT_SPACING
                        off = parking_KERB_OFFSET_MIN + parking__noise(line + j, seg, 311 + axis) % (
                            parking_KERB_OFFSET_MAX - parking_KERB_OFFSET_MIN + 1)
                        lat = centre + side * off
                        x, y = (lat, along) if axis == parking_AXIS_NS else (along, lat)
                        if (x // parking_TILE_SIZE, y // parking_TILE_SIZE) in parking__ANY_LANDMARK_TILES:
                            continue        # no kerb parking inside a landmark
                        if parking_is_legal_spot(x, y, angle):
                            spots.append((x, y, angle, side))
    spots.sort(key=lambda s: (s[1], s[0]))
    return spots


def parking__all():
    global parking__cache
    if parking__cache is None:
        parking__cache = parking__build()
    return parking__cache


def parking__sample(spots, max_count):
    """Even stride sample so a capped request still spreads over the region."""
    if max_count is None:
        return spots
    if max_count <= 0:
        return []
    total = len(spots)
    if total <= max_count:
        return spots
    step = total / float(max_count)
    return [spots[min(total - 1, int(i * step))] for i in range(max_count)]


def parking_parking_spots(max_count=None, near=None, radius=None):
    """Kerb parking spots as [(x, y, angle, side), ...].

    near      optional (x, y) anchor; results come back nearest-first.
    radius    optional px limit around `near`.
    max_count caps the result, sampled evenly rather than truncated.
    """
    spots = parking__all()
    if near is not None:
        nx, ny = near
        if radius is not None:
            r2 = radius * radius
            spots = [s for s in spots
                     if (s[0] - nx) ** 2 + (s[1] - ny) ** 2 <= r2]
        else:
            spots = list(spots)
        spots.sort(key=lambda s: (s[0] - nx) ** 2 + (s[1] - ny) ** 2)
    return parking__sample(spots, max_count)


def parking_spots_in_rect(rect):
    """Every spot whose centre falls inside a pygame.Rect (or 4-tuple)."""
    if not isinstance(rect, pygame.Rect):
        rect = pygame.Rect(rect)
    x0, y0, x1, y1 = rect.left, rect.top, rect.right, rect.bottom
    return [s for s in parking__all() if x0 <= s[0] < x1 and y0 <= s[1] < y1]


def parking_nearest_spot(x, y):
    """Closest spot to a world position, or None if the map has none."""
    best = None
    best_d = None
    for s in parking__all():
        d = (s[0] - x) ** 2 + (s[1] - y) ** 2
        if best_d is None or d < best_d:
            best_d = d
            best = s
    return best



# ==========================================================
# Baked art: traffic_ai
# ==========================================================
"""Ambient city traffic AI for the top-down GTA1-style sandbox.

Drop-in replacement for ``Car.wander_ai``.  Unhurried, lane-disciplined traffic
that only ever changes heading axis inside an intersection tile, slows for
junctions and for the car in front, and cruises well below the player's top
speed so a player on foot can jog alongside and jack it.

Integration (main.py)
---------------------
    import traffic_ai

    traffic_ai.traffic_set_hooks(is_blocked, GAME_MAP, TILE_SIZE,
                         MAP_TILES_W, MAP_TILES_H, road_lines)

    # after building self.cars
    for c in self.cars:
        traffic_ai.traffic_init_car(c)

    # in Game.update, replacing `car.wander_ai()`
    for car in self.cars:
        if car.driver is None:
            traffic_ai.traffic_drive(car, self.cars)

    # in toggle_enter_exit: the AI parks max_speed at traffic pace, so hand the
    # car back to the player at player pace, and re-arm the AI on exit.
    car.driver = 'player'; traffic_ai.traffic_take_over(car)      # entering
    car.driver = None;     traffic_ai.traffic_hand_back(car)      # leaving

Physics contract
----------------
Only ``input_throttle``, ``input_steer`` and ``max_speed`` are written, and
``traffic_drive()`` ends with exactly one ``physics_step()`` call, exactly like the
wander_ai it replaces.  ``velocity`` and ``angle`` are never assigned.

Why max_speed is modulated per frame: the physics turn rate is
``steer_angle * (|velocity| / max_speed)`` per frame, so the turning *radius*
is ``max_speed / steer_angle`` -- independent of how fast the car is actually
going.  Easing max_speed down into a junction is therefore the only way to get
a tight, believable corner (and it doubles as the "slow for the junction"
behaviour).  It never rises above traffic_TRAFFIC_MAX_SPEED.

Determinism: every random choice comes from a per-car ``random.Random`` seeded
from a hash of that car's own spawn position and angle, so a headless run
reproduces exactly.
"""




# --------------------------------------------------------------------------
# Tuning
# --------------------------------------------------------------------------

traffic_TRAFFIC_MAX_SPEED = 3.8      # ambient top speed. Player car is 9.5, foot is 4.2
traffic_TRAFFIC_THROTTLE = 0.30      # cruise throttle: gentle 0.084 px/frame^2 pickup

traffic_PLAYER_MAX_SPEED = 9.5       # restored by traffic_take_over() when the player jacks one

traffic_LANE_OFFSET = 15.0           # px right of the road-tile centre line
traffic_LANE_MARGIN = 2.0            # px of clearance kept off a collidable kerb
traffic_LANE_OVERHANG = 6.0          # px a lane may sit outside the tile when it is open

traffic_LOOKAHEAD = 34.0             # pure-pursuit look-ahead along the lane
traffic_STEER_GAIN = 2.4
traffic_STEER_DAMP = 4.0             # damps the physics' steer_angle integrator

traffic_JUNCTION_SPEED = 2.8         # cap for driving straight through a junction
traffic_TURN_SPEED = 2.1             # cap while cornering -> ~21px turning radius
traffic_JUNCTION_SLOW_DIST = 96.0    # start easing off this far from the junction centre
traffic_DECIDE_DIST = 52.0           # pick the exit this far out
traffic_TURN_IN_DIST = 22.0          # start the corner this far before the lane corner
traffic_TURN_HOLD_FRAMES = 26        # keep the corner speed cap this long after turn-in

traffic_MIN_MAX_SPEED = 1.1          # max_speed floor (physics divides by it)
traffic_EASE_UP = 0.05               # max_speed change per frame, accelerating
traffic_EASE_DOWN = 0.12             # max_speed change per frame, slowing

traffic_FOLLOW_LOOK = 84.0           # forward cone length for the car in front
traffic_FOLLOW_LAT = 19.0            # forward cone half-width
traffic_FOLLOW_MIN_GAP = 30.0        # centre-to-centre distance treated as "stopped"
traffic_FOLLOW_GAIN = 0.115          # speed allowed per px of gap beyond the minimum

traffic_JUNCTION_BOX = 52.0          # radius around a junction centre counted as "in it"
traffic_YIELD_CARE_DIST = 84.0       # only yield once this close to the junction
traffic_YIELD_CLEAR_DIST = 22.0      # never stop once this deep into the junction

traffic_HALT_PATIENCE = 150          # frames stopped before the anti-deadlock creep
traffic_CREEP_FRAMES = 90            # how long a creep lasts
traffic_CREEP_SPEED = 1.5            # creep pace, slow enough to still read as yielding
traffic_PROBE_AHEAD = 26             # px in front of the nose checked for a wall

traffic_SEGMENT_SCAN = 9             # tiles scanned ahead when validating an exit

traffic_TILE_ROAD = 1

# 0 = east, 1 = south, 2 = west, 3 = north.  Matches angle = index * pi/2
# because +Y is down, so index == round(angle / (pi/2)) % 4.
traffic__DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))


# --------------------------------------------------------------------------
# Injected world hooks
# --------------------------------------------------------------------------

traffic__is_blocked = None
traffic__MAP = None
traffic__TS = 64
traffic__MW = 0
traffic__MH = 0
traffic__ROAD_LINES = frozenset()
traffic__LINES = ()


def traffic_set_hooks(is_blocked_fn, game_map, tile_size, map_tiles_w, map_tiles_h, road_lines):
    """Inject main.py's world globals so this module stays standalone."""
    global traffic__is_blocked, traffic__MAP, traffic__TS, traffic__MW, traffic__MH, traffic__ROAD_LINES, traffic__LINES
    traffic__is_blocked = is_blocked_fn
    traffic__MAP = game_map
    traffic__TS = int(tile_size)
    traffic__MW = int(map_tiles_w)
    traffic__MH = int(map_tiles_h)
    traffic__ROAD_LINES = frozenset(int(v) for v in road_lines)
    traffic__LINES = tuple(sorted(traffic__ROAD_LINES))


# --------------------------------------------------------------------------
# Tile helpers
# --------------------------------------------------------------------------

def traffic__tile(col, row):
    if 0 <= row < traffic__MH and 0 <= col < traffic__MW:
        return traffic__MAP[row][col]
    return None


def traffic__is_road(col, row):
    t = traffic__tile(col, row)
    return t is not None and t['type'] == traffic_TILE_ROAD and not t['collidable']


def traffic__is_open(col, row):
    t = traffic__tile(col, row)
    return t is not None and not t['collidable']


def traffic__is_junction(col, row):
    return (col in traffic__ROAD_LINES and row in traffic__ROAD_LINES and traffic__is_road(col, row))


def traffic__centre(idx):
    return idx * traffic__TS + traffic__TS * 0.5


def traffic__segment_clear(col, row, d, max_steps=traffic_SEGMENT_SCAN):
    """True if the road runs unbroken from (col,row) to the next junction.

    Rejects exits whose corridor is stamped over by a landmark, so a car never
    commits to a leg it cannot finish.
    """
    dx, dy = traffic__DIRS[d]
    c, r = col, row
    for _ in range(max_steps):
        c += dx
        r += dy
        if not traffic__is_road(c, r):
            return False
        if c in traffic__ROAD_LINES and r in traffic__ROAD_LINES:
            return True
    return True


# --------------------------------------------------------------------------
# Lane geometry
# --------------------------------------------------------------------------

def traffic__lane_coord(d, line):
    """Lateral world coordinate of the right-hand lane centre.

    ``line`` is the road-line row index for an east/west axis, or the road-line
    column index for a north/south axis.  Right of the heading is
    ``(-hy, hx)``, so eastbound sits south of the centre line, southbound sits
    west of it -- ordinary right-hand traffic.
    """
    hx, hy = traffic__DIRS[d]
    base = traffic__centre(line)
    if hy == 0:
        return base + hx * traffic_LANE_OFFSET
    return base - hy * traffic_LANE_OFFSET


def traffic__lane_clamped(d, line, col, row):
    """Lane coordinate pulled in so the car's AABB clears a collidable kerb.

    Car rects never rotate: a car is 34px wide in X whatever way it points, so
    a north/south lane at the full offset would graze a building that abuts the
    road.  Only tightens the lane, never widens it past the ideal offset.
    """
    hx, hy = traffic__DIRS[d]
    lane = traffic__lane_coord(d, line)
    base = traffic__centre(line)
    half = traffic__TS * 0.5
    if hy == 0:
        # travelling horizontally: lateral axis is Y, half-extent is height/2
        extent = 9.0
        lo_open = traffic__is_open(col, line - 1)
        hi_open = traffic__is_open(col, line + 1)
    else:
        extent = 17.0
        lo_open = traffic__is_open(line - 1, row)
        hi_open = traffic__is_open(line + 1, row)
    lo = base - half - traffic_LANE_OVERHANG if lo_open else base - half + extent + traffic_LANE_MARGIN
    hi = base + half + traffic_LANE_OVERHANG if hi_open else base + half - extent - traffic_LANE_MARGIN
    if lo > hi:
        return base
    return min(hi, max(lo, lane))


# --------------------------------------------------------------------------
# Per-car state
# --------------------------------------------------------------------------

def traffic__new_state(car):
    # Seeded purely from the car's own spawn state -- no module-level counter --
    # so rebuilding the same cars reproduces the same traffic exactly, however
    # many times this module has been used already in the process.
    seed = ((int(car.rect.centerx) * 40503)
            ^ (int(car.rect.centery) * 73856093)
            ^ (int(car.angle * 10000.0) * 19349663)) & 0x7fffffff
    return {
        'dir': 0,
        'line': 0,
        'rng': random.Random(seed),
        'id': seed,
        'junction': None,       # (col, row) of the latched next junction
        'j_along': 0.0,         # its centre projected on the heading axis
        'next_dir': None,       # chosen exit, once decided
        'last_junction': None,  # junction just consumed, skipped by the search
        'turn_hold': 0,
        'wait': 0,
        'halt': 0,
        'creep': 0,
    }


def traffic_init_car(car):
    """Give a Car the lane/heading/timer state this AI needs.

    Picks the heading axis closest to the car's current angle among the legal
    ones, so nothing has to be teleported or snapped.
    """
    st = traffic__new_state(car)
    car._traffic_ai = st
    car.max_speed = traffic_TRAFFIC_MAX_SPEED
    car.input_throttle = 0.0
    car.input_steer = 0.0

    col = int(car.rect.centerx) // traffic__TS
    row = int(car.rect.centery) // traffic__TS

    # Candidate axes: whichever corridor(s) this tile belongs to.
    cands = []
    if row in traffic__ROAD_LINES:
        cands.extend(((0, row), (2, row)))
    if col in traffic__ROAD_LINES:
        cands.extend(((1, col), (3, col)))
    if not cands:
        # Off the grid entirely: aim along the nearest road line.
        near_row = min(traffic__LINES, key=lambda v: abs(v - row)) if traffic__LINES else row
        near_col = min(traffic__LINES, key=lambda v: abs(v - col)) if traffic__LINES else col
        if abs(near_row - row) <= abs(near_col - col):
            cands = [(0, near_row), (2, near_row)]
        else:
            cands = [(1, near_col), (3, near_col)]

    facing = int(round(car.angle / (math.pi * 0.5))) % 4

    def rank(item):
        d, _line = item
        turn = abs(((d - facing + 2) % 4) - 2)          # 0 straight .. 2 reverse
        clear = 0 if traffic__segment_clear(col, row, d) else 1  # clear legs first
        return (clear, turn, d)

    cands.sort(key=rank)
    st['dir'], st['line'] = cands[0]
    car.wander_dir = traffic__WANDER_DIR_MAP[st['dir']]


# main.py's wander_dir order is [(1,0), (-1,0), (0,1), (0,-1)]; keep it in sync
# so anything still reading that attribute sees something sane.
traffic__WANDER_DIR_MAP = {0: 0, 2: 1, 1: 2, 3: 3}


def traffic_aligned_spawn_angle(car):
    """The lane heading this car settled on, in radians (call after traffic_init_car).

    ``Car.__init__`` hands out a random angle, so a freshly spawned car spends
    its first half second swinging into lane -- the one and only place traffic
    turns away from a junction, and it looks like the old swerving.  main.py owns
    ``car.angle``, so the fix lives there, not here::

        traffic_ai.traffic_init_car(c)
        c.angle = traffic_ai.traffic_aligned_spawn_angle(c)
    """
    st = getattr(car, '_traffic_ai', None)
    d = st['dir'] if st is not None else 0
    return d * math.pi * 0.5


def traffic_take_over(car):
    """Hand the car to the player: restore the player-grade top speed."""
    car.max_speed = traffic_PLAYER_MAX_SPEED
    car.input_throttle = 0.0
    car.input_steer = 0.0


def traffic_hand_back(car):
    """Player got out: re-arm the ambient AI from wherever the car ended up."""
    traffic_init_car(car)


# --------------------------------------------------------------------------
# Junction search / choice
# --------------------------------------------------------------------------

def traffic__next_junction(st, d, px, py):
    """Nearest junction ahead on the current corridor: (col, row, along)."""
    hx, hy = traffic__DIRS[d]
    along = px * hx + py * hy
    last = st['last_junction']
    best = None
    if hy == 0:
        row = st['line']
        for c in traffic__LINES:
            if not traffic__is_junction(c, row):
                continue
            if last is not None and last == (c, row):
                continue
            a = traffic__centre(c) * hx
            if a > along + 0.5 and (best is None or a < best[2]):
                best = (c, row, a)
    else:
        col = st['line']
        for r in traffic__LINES:
            if not traffic__is_junction(col, r):
                continue
            if last is not None and last == (col, r):
                continue
            a = traffic__centre(r) * hy
            if a > along + 0.5 and (best is None or a < best[2]):
                best = (col, r, a)
    return best


def traffic__choose_exit(st, jcol, jrow, d):
    """Pick a legal exit, preferring straight on; U-turn only as a last resort."""
    opts = []
    reverse = (d + 2) % 4
    u_ok = False
    for cand in range(4):
        if not traffic__segment_clear(jcol, jrow, cand):
            continue
        if cand == reverse:
            u_ok = True
            continue
        opts.append((cand, 6.0 if cand == d else 2.0))
    if not opts:
        return reverse if u_ok else d
    total = sum(w for _c, w in opts)
    pick = st['rng'].random() * total
    for cand, w in opts:
        pick -= w
        if pick <= 0.0:
            return cand
    return opts[-1][0]


# --------------------------------------------------------------------------
# Traffic awareness
# --------------------------------------------------------------------------

def traffic__blocked_ahead(car, hx, hy):
    """True if the car's nose is up against a collidable tile."""
    if traffic__is_blocked is None:
        return False
    probe = pygame.Rect(car.rect).move(int(hx * traffic_PROBE_AHEAD), int(hy * traffic_PROBE_AHEAD))
    return traffic__is_blocked(probe)


def traffic__axis_of(other):
    st = getattr(other, '_traffic_ai', None)
    if st is not None:
        return st['dir']
    return int(round(other.angle / (math.pi * 0.5))) % 4


def traffic__follow_cap(car, neighbours, fx, fy):
    """Speed allowed by whatever is in the forward cone (None = unrestricted).

    Oncoming traffic is deliberately ignored.  It is separated by a full lane
    width, it passes in a few frames, and main.py runs no car-car collision
    between AI cars anyway -- whereas braking for it deadlocks both cars
    permanently: a stopped car cannot steer (the physics needs |velocity| > 0.15)
    so neither can ever pull back into its own lane.  Stationary cars still
    count, so a parked or jammed car is always given room.
    """
    cap = None
    px, py = car.rect.centerx, car.rect.centery
    for other in neighbours:
        if other is car:
            continue
        dx = other.rect.centerx - px
        dy = other.rect.centery - py
        f = dx * fx + dy * fy
        if f <= 0.0 or f > traffic_FOLLOW_LOOK:
            continue
        if abs(dx * -fy + dy * fx) > traffic_FOLLOW_LAT:
            continue
        if abs(other.velocity) > 0.4:
            if math.cos(other.angle) * fx + math.sin(other.angle) * fy < 0.25:
                continue                     # oncoming: it will pass, don't brake
        allow = (f - traffic_FOLLOW_MIN_GAP) * traffic_FOLLOW_GAIN
        if allow < 0.0:
            allow = 0.0
        if cap is None or allow < cap:
            cap = allow
    return cap


def traffic__should_yield(car, st, neighbours, jcol, jrow, dist_j):
    """True if crossing traffic owns the junction we are about to enter."""
    if jcol is None or dist_j > traffic_YIELD_CARE_DIST or dist_j < traffic_YIELD_CLEAR_DIST:
        return False
    jx = traffic__centre(jcol)
    jy = traffic__centre(jrow)
    mine = math.hypot(car.rect.centerx - jx, car.rect.centery - jy)
    my_axis = st['dir'] & 1
    for other in neighbours:
        if other is car:
            continue
        ox = other.rect.centerx - jx
        oy = other.rect.centery - jy
        theirs = math.hypot(ox, oy)
        if theirs > traffic_JUNCTION_BOX:
            continue
        if (traffic__axis_of(other) & 1) == my_axis:
            continue                      # same axis: the follow rule handles it
        if theirs < mine - 4.0:
            return True
        if abs(theirs - mine) <= 4.0:
            other_st = getattr(other, '_traffic_ai', None)
            other_id = other_st['id'] if other_st is not None else -1
            if other_id < st['id']:
                return True
    return False


# --------------------------------------------------------------------------
# One frame of driving
# --------------------------------------------------------------------------

def traffic_drive(car, neighbours=()):
    """One frame of ambient driving.  Ends with exactly one physics_step()."""
    st = getattr(car, '_traffic_ai', None)
    if st is None:
        traffic_init_car(car)
        st = car._traffic_ai

    ts = traffic__TS
    px = car.rect.centerx
    py = car.rect.centery
    col = int(px) // ts
    row = int(py) // ts

    # --- forget the junction we just left ---------------------------------
    lj = st['last_junction']
    if lj is not None and (col, row) != lj:
        if math.hypot(px - traffic__centre(lj[0]), py - traffic__centre(lj[1])) > 72.0:
            st['last_junction'] = None

    d = st['dir']
    hx, hy = traffic__DIRS[d]

    # --- keep the corridor index honest -----------------------------------
    if hy == 0:
        if row != st['line'] and row in traffic__ROAD_LINES and traffic__is_road(col, row):
            st['line'] = row
    else:
        if col != st['line'] and col in traffic__ROAD_LINES and traffic__is_road(col, row):
            st['line'] = col

    along = px * hx + py * hy

    # --- latch the next junction ------------------------------------------
    if st['junction'] is None:
        found = traffic__next_junction(st, d, px, py)
        if found is not None:
            st['junction'] = (found[0], found[1])
            st['j_along'] = found[2]
            st['next_dir'] = None

    jcol = jrow = None
    dist_j = 1e9
    if st['junction'] is not None:
        jcol, jrow = st['junction']
        dist_j = st['j_along'] - along

    # --- decide the exit ---------------------------------------------------
    if jcol is not None and st['next_dir'] is None and dist_j <= traffic_DECIDE_DIST:
        st['next_dir'] = traffic__choose_exit(st, jcol, jrow, d)

    # --- turn in, or pass straight through ---------------------------------
    nd = st['next_dir']
    if jcol is not None and nd is not None:
        if nd == d:
            if dist_j < -18.0:
                st['last_junction'] = (jcol, jrow)
                st['junction'] = None
                st['next_dir'] = None
                jcol = jrow = None
                dist_j = 1e9
        else:
            nhx, nhy = traffic__DIRS[nd]
            new_line = jcol if nhy != 0 else jrow
            new_lane = traffic__lane_coord(nd, new_line)
            old_lane = traffic__lane_coord(d, st['line'])
            if nhy == 0:
                corner_x, corner_y = old_lane, new_lane
            else:
                corner_x, corner_y = new_lane, old_lane
            corner_along = corner_x * hx + corner_y * hy
            entry_along = st['j_along'] - ts * 0.5
            turn_in = max(corner_along - traffic_TURN_IN_DIST, entry_along + 3.0)
            on_tile = (col == jcol and row == jrow)
            if along >= turn_in and on_tile:
                # The only place a heading axis ever changes: inside a junction.
                st['dir'] = d = nd
                hx, hy = nhx, nhy
                st['line'] = new_line
                st['last_junction'] = (jcol, jrow)
                st['junction'] = None
                st['next_dir'] = None
                st['turn_hold'] = traffic_TURN_HOLD_FRAMES
                nd = None
                jcol = jrow = None
                dist_j = 1e9
                along = px * hx + py * hy

    # --- pure-pursuit steering toward the lane centre ----------------------
    lane = traffic__lane_clamped(d, st['line'], col, row)
    if hy == 0:
        tx = px + hx * traffic_LOOKAHEAD
        ty = lane
    else:
        tx = lane
        ty = py + hy * traffic_LOOKAHEAD
    diff = (math.atan2(ty - py, tx - px) - car.angle + math.pi) % math.tau - math.pi
    steer = diff * traffic_STEER_GAIN - car.steer_angle * traffic_STEER_DAMP
    car.input_steer = -1.0 if steer < -1.0 else (1.0 if steer > 1.0 else steer)

    # --- how fast do we want to be going -----------------------------------
    target = traffic_TRAFFIC_MAX_SPEED
    if st['turn_hold'] > 0:
        st['turn_hold'] -= 1
        target = traffic_TURN_SPEED
    if jcol is not None and dist_j < traffic_JUNCTION_SLOW_DIST:
        cap = traffic_TURN_SPEED if (nd is not None and nd != d) else traffic_JUNCTION_SPEED
        t = dist_j / traffic_JUNCTION_SLOW_DIST
        if t < 0.0:
            t = 0.0
        target = min(target, cap + (traffic_TRAFFIC_MAX_SPEED - cap) * t)

    err = abs(diff)
    if err > 0.30:
        eased = traffic_TRAFFIC_MAX_SPEED - (err - 0.30) * 3.0
        target = min(target, max(1.5, eased))

    fx = math.cos(car.angle)
    fy = math.sin(car.angle)
    follow = traffic__follow_cap(car, neighbours, fx, fy)
    if follow is not None and follow < target:
        target = follow

    if st['creep'] <= 0 and traffic__should_yield(car, st, neighbours, jcol, jrow, dist_j):
        target = 0.0
        st['wait'] += 1
    else:
        st['wait'] = 0

    # --- nothing is allowed to stay stopped forever -------------------------
    # Any hold (a queue, a yield, a wall) that lasts too long turns into a slow
    # creep, which is enough to break a mutual stand-off: once a car rolls, it
    # can steer again and sort itself out.
    if abs(car.velocity) < 0.2:
        st['halt'] += 1
    else:
        st['halt'] = 0
    if st['halt'] > traffic_HALT_PATIENCE:
        st['halt'] = 0
        st['creep'] = traffic_CREEP_FRAMES
    creep_reverse = False
    if st['creep'] > 0:
        st['creep'] -= 1
        if traffic__blocked_ahead(car, hx, hy):
            creep_reverse = True             # nose in a wall: back off instead
        elif target < traffic_CREEP_SPEED:
            target = traffic_CREEP_SPEED

    # --- max_speed sets both the speed cap and the turning radius ----------
    want = target if target > traffic_MIN_MAX_SPEED else traffic_MIN_MAX_SPEED
    ms = car.max_speed
    if want > ms:
        ms = min(want, ms + traffic_EASE_UP)
    elif want < ms:
        ms = max(want, ms - traffic_EASE_DOWN)
    car.max_speed = min(ms, traffic_TRAFFIC_MAX_SPEED * getattr(car, 'speed_factor', 1.0))

    # --- throttle -----------------------------------------------------------
    v = car.velocity
    if creep_reverse:
        # Back out of a wall.  Never touches the heading axis, so the "turns
        # only at junctions" guarantee holds even during recovery.
        car.input_throttle = -0.5
        car.input_steer = 0.0
    elif target <= 0.05:
        car.input_throttle = -0.8 if v > 0.12 else 0.0
    elif v < target - 0.10:
        car.input_throttle = traffic_TRAFFIC_THROTTLE
    elif v > target + 0.45:
        car.input_throttle = -0.35
    else:
        car.input_throttle = 0.0

    car.physics_step()



# ==========================================================
# Baked art: gfx_landmarks
# ==========================================================
"""Recognisable-from-above art for the St. Louis landmarks.

Every landmark is composed ONCE across its whole footprint (never per tile),
baked into a cached Surface at its exact pixel size, and afterwards only
blitted.  Compositions are built from aerial/plan-view research notes; each
_bake_* function documents the real-world facts it is drawing.

Only pygame + math.  No file I/O, no display-mode changes, no `random`:
layout jitter comes from the local lm__noise() hash so nothing ever flickers.
Shadows are always cast SOUTH-EAST to match the rest of the game.
"""



# --------------------------------------------------------------------------
# palette - muted, gritty, 90s console.  Near-black outlines everywhere.
# --------------------------------------------------------------------------
lm_OUTLINE = (18, 16, 18)
lm_SHADOW = (10, 9, 11)
lm_WALL = (34, 32, 36)

lm_GRASS = (68, 84, 56)
lm_GRASS_DK = (58, 74, 48)
lm_GRASS_LT = (80, 96, 62)
lm_TREE = (44, 60, 38)
lm_TREE_LT = (58, 76, 44)
lm_TREE_DK = (32, 46, 30)
lm_TREE_SHADOW = (14, 18, 12)

lm_WATER = (30, 52, 70)
lm_WATER_LT = (52, 82, 104)
lm_WATER_DK = (22, 40, 56)

lm_CONCRETE = (104, 100, 96)
lm_CONCRETE_DK = (84, 80, 76)
lm_CONCRETE_LT = (126, 122, 116)
lm_GRAVEL = (120, 110, 92)
lm_GRAVEL_DK = (98, 90, 74)
lm_ASPHALT = (52, 52, 54)
lm_ASPHALT_LT = (62, 62, 64)
lm_ASPHALT_DK = (42, 42, 44)
lm_LINE_W = (150, 148, 140)
lm_LINE_Y = (150, 136, 72)

lm_STEEL = (150, 152, 152)
lm_STEEL_HI = (198, 200, 198)
lm_STEEL_LO = (96, 100, 104)

lm_BRICK = (124, 64, 50)
lm_BRICK_DK = (98, 50, 40)
lm_BRICK_LT = (146, 84, 62)
lm_BRICK_BROWN = (108, 66, 48)
lm_TERRACOTTA = (140, 76, 54)
lm_TAR = (72, 70, 72)
lm_TAR_LT = (88, 86, 88)
lm_SLATE = (78, 80, 86)
lm_SLATE_DK = (60, 62, 68)
lm_LIMESTONE = (158, 150, 130)
lm_LIMESTONE_DK = (124, 116, 100)
lm_VERDIGRIS = (78, 118, 100)
lm_VERDIGRIS_DK = (54, 90, 76)

lm_DIRT = (128, 84, 56)
lm_DIRT_DK = (106, 66, 44)
lm_TURF = (64, 96, 50)
lm_TURF_LT = (76, 108, 58)
lm_CHALK = (200, 198, 188)
lm_SEAT_RED = (112, 58, 54)
lm_SEAT_RED_DK = (86, 44, 42)
lm_SAND = (172, 158, 120)
lm_GOLD = (168, 140, 70)
lm_MARQUEE = (206, 190, 138)
lm_NEON_RED = (156, 62, 58)

lm_ROWHOUSE_ROOFS = ((92, 66, 58), (78, 74, 72), (104, 74, 60), (86, 80, 82),
                  (112, 84, 66), (68, 66, 70))
lm_HILL_ROOFS = ((124, 88, 68), (106, 100, 96), (138, 100, 74), (114, 108, 102),
              (96, 74, 62), (128, 116, 100))
lm_AWNING_COLS = ((122, 62, 58), (72, 92, 96), (128, 104, 56), (86, 78, 108),
               (70, 96, 70), (132, 88, 60))

lm_TILE = 64

# --------------------------------------------------------------------------
# public data
# --------------------------------------------------------------------------

#: landmark name (exactly as in main.LANDMARKS) -> style key
# Only the landmarks that need a bespoke composition. The district landmarks
# (CWE, The Hill, Delmar Loop, Grand Center) now read through the generic
# brick-block + hybrid-facade renderer, tinted by their LANDMARKS colour and
# flagged commercial in _COMMERCIAL_LANDMARKS - which looks better than the
# old abstract top-down blobs did.
lm_LANDMARK_ART = {
    "Gateway Arch": "arch",
    "Downtown & Busch Stadium": "stadium",
    "Soulard & Anheuser-Busch": "brewery",
    "Forest Park": "forest_park",
    "Tower Grove Park": "tower_grove",
}

#: natural footprint of each landmark in tiles, derived from main.LANDMARKS.
#: Used by lm_bake() so the common sizes are ready before the first frame.
lm_FOOTPRINT_TILES = {
    name: (w, h) for (x, y, w, h, kind, name, color) in LANDMARKS
}

#: walkable ground / plaza colour per style
lm__GROUND = {
    "arch": (66, 82, 54),
    "stadium": (96, 92, 88),
    "brewery": (70, 68, 68),
    "forest_park": (68, 84, 56),
    "central_west_end": (102, 98, 94),
    "the_hill": (100, 96, 92),
    "delmar_loop": (100, 96, 92),
    "tower_grove": (68, 84, 56),
    "grand_center": (98, 94, 90),
}

#: label position as a fraction of the footprint, chosen to sit on calm art
lm__LABEL_AT = {
    "arch": (0.46, 0.40),
    "stadium": (0.34, 0.93),
    "brewery": (0.50, 0.93),
    "forest_park": (0.50, 0.93),
    "central_west_end": (0.50, 0.93),
    "the_hill": (0.50, 0.93),
    "delmar_loop": (0.50, 0.06),
    "tower_grove": (0.50, 0.93),
    "grand_center": (0.50, 0.93),
}

lm__CACHE = {}
lm__CACHE_LIMIT = 32


# --------------------------------------------------------------------------
# deterministic hash - never use `random` here, draw() runs every frame
# --------------------------------------------------------------------------
def lm__noise(c, r, salt=0):
    """Stable pseudo-random integer for a (column, row, salt) triple."""
    n = (int(c) * 73856093) ^ (int(r) * 19349663) ^ (int(salt) * 83492791)
    n &= 0x7FFFFFFF
    n = ((n * 1103515245) >> 16) & 0x7FFFFFFF
    return n


def lm__n01(c, r, salt=0):
    return (lm__noise(c, r, salt) % 4096) / 4096.0


def lm__pick(seq, c, r, salt=0):
    return seq[lm__noise(c, r, salt) % len(seq)]


def lm__shade(col, f):
    return (max(0, min(255, int(col[0] * f))),
            max(0, min(255, int(col[1] * f))),
            max(0, min(255, int(col[2] * f))))


# --------------------------------------------------------------------------
# small drawing helpers (lm_bake time only)
# --------------------------------------------------------------------------
def lm__new(w, h):
    return pygame.Surface((int(w), int(h)))


def lm__r(surf, col, x, y, w, h):
    w = int(w)
    h = int(h)
    if w <= 0 or h <= 0:
        return
    pygame.draw.rect(surf, col, (int(x), int(y), w, h))


def lm__line(surf, col, a, b, width=1):
    pygame.draw.line(surf, col, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), width)


def lm__lin(a0, a1, n):
    return [a0 + (a1 - a0) * i / float(n) for i in range(n + 1)]


def lm__fill_mottle(surf, w, h, base, alts, salt, cell=7, hit=4):
    surf.fill(base)
    na = len(alts)
    for r in range(0, int(h) // cell + 1):
        for c in range(0, int(w) // cell + 1):
            n = lm__noise(c, r, salt)
            if n % hit:
                continue
            lm__r(surf, alts[(n >> 5) % na], c * cell, r * cell, cell, cell)


def lm__mottle_rect(surf, rect, alts, salt, cell=5, hit=4):
    x0, y0, rw, rh = rect
    na = len(alts)
    for r in range(0, int(rh) // cell + 1):
        for c in range(0, int(rw) // cell + 1):
            n = lm__noise(c, r, salt)
            if n % hit:
                continue
            lm__r(surf, alts[(n >> 5) % na],
               x0 + c * cell, y0 + r * cell,
               min(cell, x0 + rw - (x0 + c * cell)),
               min(cell, y0 + rh - (y0 + r * cell)))


def lm__block(surf, x, y, bw, bh, roof, depth=4, drop=5, wall=lm_WALL, outline=True):
    """Pseudo-3D extruded block: SE drop shadow, side walls, roof pulled NW."""
    x, y, bw, bh = int(x), int(y), int(bw), int(bh)
    if bw < 2 or bh < 2:
        return pygame.Rect(x, y, max(1, bw), max(1, bh))
    if drop:
        lm__r(surf, lm_SHADOW, x + drop, y + drop, bw, bh)
    lm__r(surf, wall, x, y, bw, bh)
    rf = pygame.Rect(x, y, max(1, bw - depth), max(1, bh - depth))
    pygame.draw.rect(surf, roof, rf)
    if outline:
        pygame.draw.rect(surf, lm_OUTLINE, rf, 1)
    return rf


def lm__roof_clutter(surf, rf, salt, dense=3, base=lm_TAR):
    """HVAC boxes / vents / skylights so roofs are not flat colour."""
    dark = lm__shade(base, 0.7)
    for i in range(dense):
        n = lm__noise(rf.x, rf.y, salt + i * 7)
        bw = 4 + (n % 5)
        bh = 3 + ((n >> 4) % 5)
        px = rf.x + 3 + ((n >> 8) % max(1, rf.w - bw - 6))
        py = rf.y + 3 + ((n >> 14) % max(1, rf.h - bh - 6))
        lm__r(surf, lm_SHADOW, px + 2, py + 2, bw, bh)
        lm__r(surf, dark, px, py, bw, bh)


def lm__tree(surf, x, y, rad, salt=0, shadow=True):
    x, y, rad = int(x), int(y), max(2, int(rad))
    if shadow:
        pygame.draw.circle(surf, lm_TREE_SHADOW, (x + 3, y + 3), rad)
    tone = lm_TREE if (lm__noise(x, y, salt) & 1) else lm_TREE_DK
    pygame.draw.circle(surf, tone, (x, y), rad)
    pygame.draw.circle(surf, lm_TREE_LT, (x - max(1, rad // 3), y - max(1, rad // 3)),
                       max(1, rad // 2))
    pygame.draw.circle(surf, lm_OUTLINE, (x, y), rad, 1)


def lm__tree_line(surf, pts, spacing, rad, salt, jitter=0):
    """Plant trees at even arc-length intervals along a polyline."""
    if len(pts) < 2:
        return
    acc = 0.0
    prev = pts[0]
    lm__tree(surf, prev[0], prev[1], rad, salt)
    for p in pts[1:]:
        seg = math.hypot(p[0] - prev[0], p[1] - prev[1])
        if seg <= 0.0001:
            continue
        t = 0.0
        while acc + (seg - t) >= spacing:
            t += spacing - acc
            acc = 0.0
            x = prev[0] + (p[0] - prev[0]) * (t / seg)
            y = prev[1] + (p[1] - prev[1]) * (t / seg)
            if jitter:
                x += (lm__n01(int(x), int(y), salt) - 0.5) * jitter
                y += (lm__n01(int(x), int(y), salt + 1) - 0.5) * jitter
            lm__tree(surf, x, y, rad, salt)
        acc += seg - t
        prev = p


def lm__thick_path(surf, pts, width, col, edge=None):
    w = max(1, int(width))
    for i in range(len(pts) - 1):
        lm__line(surf, col, pts[i], pts[i + 1], w)
    if w > 2:
        for p in pts:
            pygame.draw.circle(surf, col, (int(p[0]), int(p[1])), w // 2)
    if edge:
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy) or 1.0
            px, py = -dy / L * (w / 2.0), dx / L * (w / 2.0)
            lm__line(surf, edge, (a[0] + px, a[1] + py), (b[0] + px, b[1] + py), 1)
            lm__line(surf, edge, (a[0] - px, a[1] - py), (b[0] - px, b[1] - py), 1)


def lm__poly(surf, col, pts, width=0):
    if len(pts) < 3:
        return
    pygame.draw.polygon(surf, col, [(int(p[0]), int(p[1])) for p in pts], width)


def lm__poly_spans(pts, y):
    xs = []
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if y1 == y2:
            continue
        if (y1 <= y < y2) or (y2 <= y < y1):
            xs.append(x1 + (y - y1) * (x2 - x1) / float(y2 - y1))
    xs.sort()
    return xs


def lm__water_poly(surf, pts, salt, rim=None, ripple=True):
    """Fill a polygon as water, textured only INSIDE via scanline spans."""
    lm__poly(surf, lm_WATER, pts)
    if rim:
        lm__poly(surf, rim, pts, 2)
    if ripple:
        ys = [p[1] for p in pts]
        y0, y1 = int(min(ys)) + 2, int(max(ys)) - 1
        for y in range(y0, y1, 5):
            xs = lm__poly_spans(pts, y + 0.5)
            for i in range(0, len(xs) - 1, 2):
                a, b = xs[i] + 3, xs[i + 1] - 3
                x = a + (lm__noise(int(a), y, salt) % 9)
                guard = 0
                while x < b - 3 and guard < 64:
                    guard += 1
                    ln = 3 + (lm__noise(int(x), y, salt + 1) % 6)
                    if x + ln > b:
                        break
                    lm__r(surf, lm_WATER_LT, x, y, ln, 1)
                    x += ln + 6 + (lm__noise(int(x), y, salt + 2) % 11)
    lm__poly(surf, lm_WATER_DK, pts, 1)


def lm__blob(cx, cy, rx, ry, salt, n=22, amp=0.22):
    pts = []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        k = 1.0 + amp * (lm__n01(i, 0, salt) - 0.5) * 2.0
        pts.append((cx + math.cos(a) * rx * k, cy + math.sin(a) * ry * k))
    return pts


def lm__lens(x0, x1, y, bow, thick, n=22, taper=0.22):
    """A curved, tapered lagoon/pond shape - the Arch's curving ponds."""
    top, bot = [], []
    for i in range(n + 1):
        t = i / float(n)
        x = x0 + (x1 - x0) * t
        k = math.sin(math.pi * t)
        yc = y + bow * k
        half = thick * 0.5 * (taper + (1.0 - taper) * k)
        top.append((x, yc - half))
        bot.append((x, yc + half))
    return top + bot[::-1]


def lm__bowed(x0, x1, y, bow, n=20):
    return [(x0 + (x1 - x0) * (i / float(n)),
             y + bow * math.sin(math.pi * (i / float(n)))) for i in range(n + 1)]


def lm__catenary(x0, x1, ybase, yapex, n=56, a=2.05):
    ch = math.cosh(a) - 1.0
    pts = []
    for i in range(n + 1):
        t = -1.0 + 2.0 * i / n
        x = x0 + (x1 - x0) * (i / float(n))
        y = yapex + (ybase - yapex) * (math.cosh(a * t) - 1.0) / ch
        pts.append((x, y))
    return pts


def lm__ribbon(surf, pts, w_end, w_mid, col, dx=0.0, dy=0.0):
    """Tapered band along a polyline - the Arch leg profile (54ft -> 17ft)."""
    n = len(pts) - 1
    for i in range(n):
        x1, y1 = pts[i][0] + dx, pts[i][1] + dy
        x2, y2 = pts[i + 1][0] + dx, pts[i + 1][1] + dy
        t = abs((i + 0.5) / n - 0.5) * 2.0
        wd = w_mid + (w_end - w_mid) * (t ** 1.4)
        ddx, ddy = x2 - x1, y2 - y1
        L = math.hypot(ddx, ddy) or 1.0
        px, py = -ddy / L * wd * 0.5, ddx / L * wd * 0.5
        lm__poly(surf, col, [(x1 + px, y1 + py), (x2 + px, y2 + py),
                          (x2 - px, y2 - py), (x1 - px, y1 - py)])


def lm__alpha_poly(surf, pts, rgba):
    """Soft cast shadow that lets ground texture read through (lm_bake only)."""
    w, h = surf.get_size()
    lay = pygame.Surface((w, h), pygame.SRCALPHA)
    lm__poly(lay, rgba, pts)
    surf.blit(lay, (0, 0))


def lm__alpha_shape(surf, draw_fn):
    w, h = surf.get_size()
    lay = pygame.Surface((w, h), pygame.SRCALPHA)
    draw_fn(lay)
    surf.blit(lay, (0, 0))


def lm__road(surf, x, y, rw, rh, horizontal, salt, dashes=True, sidewalk=6):
    """A street with kerbs and a faded centre line."""
    lm__r(surf, lm_ASPHALT, x, y, rw, rh)
    lm__mottle_rect(surf, (int(x), int(y), int(rw), int(rh)),
                 (lm_ASPHALT_DK, lm_ASPHALT_LT), salt, 6, 5)
    if sidewalk:
        if horizontal:
            lm__r(surf, lm_CONCRETE, x, y - sidewalk, rw, sidewalk)
            lm__r(surf, lm_CONCRETE, x, y + rh, rw, sidewalk)
            lm__line(surf, lm_CONCRETE_DK, (x, y - 1), (x + rw, y - 1))
            lm__line(surf, lm_CONCRETE_DK, (x, y + rh), (x + rw, y + rh))
        else:
            lm__r(surf, lm_CONCRETE, x - sidewalk, y, sidewalk, rh)
            lm__r(surf, lm_CONCRETE, x + rw, y, sidewalk, rh)
            lm__line(surf, lm_CONCRETE_DK, (x - 1, y), (x - 1, y + rh))
            lm__line(surf, lm_CONCRETE_DK, (x + rw, y), (x + rw, y + rh))
    if dashes:
        if horizontal:
            cy = y + rh // 2
            for px in range(int(x) + 3, int(x + rw) - 6, 14):
                lm__r(surf, lm_LINE_Y, px, cy - 1, 8, 2)
        else:
            cx = x + rw // 2
            for py in range(int(y) + 3, int(y + rh) - 6, 14):
                lm__r(surf, lm_LINE_Y, cx - 1, py, 2, 8)


def lm__parking(surf, x, y, pw, ph, salt, horizontal=True):
    lm__r(surf, lm_ASPHALT_LT, x, y, pw, ph)
    lm__mottle_rect(surf, (int(x), int(y), int(pw), int(ph)),
                 (lm_ASPHALT, lm_ASPHALT_DK), salt, 6, 5)
    pygame.draw.rect(surf, lm_OUTLINE, (int(x), int(y), int(pw), int(ph)), 1)
    if horizontal:
        for px in range(int(x) + 8, int(x + pw) - 4, 11):
            lm__r(surf, lm_LINE_W, px, y + 4, 1, min(16, ph - 8))
            lm__r(surf, lm_LINE_W, px, y + ph - 4 - min(16, ph - 8), 1, min(16, ph - 8))
    else:
        for py in range(int(y) + 8, int(y + ph) - 4, 11):
            lm__r(surf, lm_LINE_W, x + 4, py, min(16, pw - 8), 1)


# --------------------------------------------------------------------------
# 1. GATEWAY ARCH
# --------------------------------------------------------------------------
def lm__bake_arch(w, h):
    """Gateway Arch + grounds.

    Research: 630ft stainless catenary, legs 630ft apart, each leg 54ft wide
    at the base tapering to 17ft at the top; Saarinen's arch stands on Dan
    Kiley's 90-acre landscape - curving reflecting ponds with groves of trees
    and a wide allee three trees deep on each side of the walk, all echoing
    the arch's curve.  Grand Staircase and cobblestone levee drop east to the
    Mississippi; the Old Courthouse (cruciform plan, four wings, oxidised
    copper dome) sits west, framed by the arch.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, lm_GRASS, (lm_GRASS_DK, lm_GRASS_LT), 11, 7)

    cx = w * 0.46

    # ---- levee + Grand Staircase down to the river, east edge -------------
    lev = max(22, int(w * 0.13))
    lx = int(w - lev)
    lm__r(s, lm_CONCRETE_DK, lx, 0, lev, h)
    for ry in range(0, int(h), 5):
        for rx in range(lx, int(w), 7):
            n = lm__noise(rx, ry, 5)
            if n % 3:
                continue
            lm__r(s, lm_CONCRETE if n & 8 else lm_GRAVEL_DK, rx, ry, 6, 4)
    st0, st1 = int(h * 0.28), int(h * 0.66)
    for y in range(st0, st1, 6):
        lm__r(s, lm_CONCRETE_LT, lx + 2, y, lev - 4, 4)
        lm__line(s, lm_CONCRETE_DK, (lx + 2, y + 4), (lx + lev - 3, y + 4))
    lm__line(s, lm_OUTLINE, (lx, 0), (lx, h))
    # riverfront promenade
    lm__r(s, lm_GRAVEL, lx - 12, 0, 10, h)
    lm__line(s, lm_OUTLINE, (lx - 13, 0), (lx - 13, h))

    # ---- the great lawn oval under the arch --------------------------------
    ov = pygame.Rect(int(w * 0.08), int(h * 0.16), int(w * 0.74), int(h * 0.48))
    pygame.draw.ellipse(s, lm_GRASS_LT, ov)
    pygame.draw.ellipse(s, lm_GRASS_DK, ov, 2)

    # ---- Kiley's curving walks, ponds and allees ---------------------------
    walk_n = lm__bowed(w * 0.06, w * 0.88, h * 0.16, -h * 0.055)
    walk_s = lm__bowed(w * 0.06, w * 0.88, h * 0.685, h * 0.075)
    lm__thick_path(s, walk_n, 7, lm_GRAVEL, lm_GRAVEL_DK)
    lm__thick_path(s, walk_s, 7, lm_GRAVEL, lm_GRAVEL_DK)

    pond_a = lm__lens(w * 0.09, w * 0.46, h * 0.815, -h * 0.045, h * 0.085)
    pond_b = lm__lens(w * 0.54, w * 0.91, h * 0.815, -h * 0.045, h * 0.085)
    for p in (pond_a, pond_b):
        lm__poly(s, lm_CONCRETE_DK, [(px, py + 2) for (px, py) in p])
        lm__water_poly(s, p, 17)
    # walk curving between the two ponds
    lm__thick_path(s, lm__bowed(w * 0.06, w * 0.90, h * 0.755, -h * 0.03), 6,
                lm_GRAVEL, lm_GRAVEL_DK)

    # allee: rows of trees three deep along the walk, clear of the ponds
    for k, off in enumerate((-28, -16, 20)):
        row = [(px, py + off) for (px, py) in lm__bowed(w * 0.04, w * 0.92,
                                                     h * 0.665, h * 0.075)]
        lm__tree_line(s, row, 26, 7, 30 + k, 2)
    lm__tree_line(s, lm__bowed(w * 0.33, w * 0.91, h * 0.925, -h * 0.02), 26, 7, 34, 2)
    # groves flanking the lawn
    for k, ang in enumerate(lm__lin(0.0, math.pi * 2, 26)[:-1]):
        rx, ry = w * 0.46, h * 0.30
        px = cx + math.cos(ang) * rx
        py = h * 0.40 + math.sin(ang) * ry
        if px < 6 or px > lx - 16 or py < 8 or py > h * 0.62:
            continue
        lm__tree(s, px, py, 8, 41 + k)

    # ---- the arch ----------------------------------------------------------
    lx0, lx1 = w * 0.145, w * 0.775
    ybase, yapex = h * 0.575, h * 0.115
    pts = lm__catenary(lx0, lx1, ybase, yapex, 56, 2.05)
    w_end = max(9.0, w * 0.045)
    w_mid = max(4.0, w_end * 0.33)

    sh_dx, sh_dy = w * 0.075, h * 0.075
    lm__alpha_shape(s, lambda lay: lm__ribbon(lay, pts, w_end + 2, w_mid + 2,
                                        (8, 7, 9, 165), sh_dx, sh_dy))

    lm__ribbon(s, pts, w_end + 2, w_mid + 2, lm_OUTLINE)
    lm__ribbon(s, pts, w_end, w_mid, lm_STEEL)
    lm__ribbon(s, pts, w_end * 0.34, w_mid * 0.40, lm_STEEL_LO, 1.6, 1.6)
    lm__ribbon(s, pts, w_end * 0.34, w_mid * 0.40, lm_STEEL_HI, -1.4, -1.4)

    # triangular leg footings on their concrete pads
    for (fx, fy) in ((lx0, ybase), (lx1, ybase)):
        pad = [(fx - w_end * 0.95, fy - 3), (fx + w_end * 0.95, fy - 3),
               (fx + w_end * 1.25, fy + w_end * 0.9),
               (fx - w_end * 1.25, fy + w_end * 0.9)]
        lm__alpha_poly(s, [(px + 5, py + 5) for (px, py) in pad], (8, 7, 9, 150))
        lm__poly(s, lm_CONCRETE, pad)
        lm__poly(s, lm_OUTLINE, pad, 1)
        lm__poly(s, lm_STEEL_LO, [(fx - w_end * 0.5, fy - 2), (fx + w_end * 0.5, fy - 2),
                            (fx, fy + w_end * 0.55)])

    # ---- Old Courthouse: cruciform, four wings, verdigris dome -------------
    bw, bh = min(86, int(w * 0.24)), min(70, int(h * 0.14))
    bx, by = int(w * 0.05), int(h * 0.845)
    lm__r(s, lm_CONCRETE, bx - 6, by - 6, bw + 12, bh + 12)
    pygame.draw.rect(s, lm_CONCRETE_DK, (bx - 6, by - 6, bw + 12, bh + 12), 1)
    lm__block(s, bx, by + bh * 0.30, bw, bh * 0.40, lm_LIMESTONE, 3, 5)
    lm__block(s, bx + bw * 0.33, by, bw * 0.34, bh, lm_LIMESTONE, 3, 5)
    dcx, dcy = int(bx + bw * 0.50), int(by + bh * 0.50)
    dr = max(7, int(min(bw, bh) * 0.26))
    pygame.draw.circle(s, lm_SHADOW, (dcx + 4, dcy + 4), dr)
    pygame.draw.circle(s, lm_VERDIGRIS, (dcx, dcy), dr)
    pygame.draw.circle(s, lm_VERDIGRIS_DK, (dcx, dcy), dr, 1)
    pygame.draw.circle(s, (104, 148, 128), (dcx - dr // 3, dcy - dr // 3),
                       max(2, dr // 3))
    pygame.draw.circle(s, lm_OUTLINE, (dcx, dcy), dr, 1)
    pygame.draw.circle(s, lm_LIMESTONE, (dcx, dcy), 2)

    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


# --------------------------------------------------------------------------
# 2. DOWNTOWN & BUSCH STADIUM
# --------------------------------------------------------------------------
def lm__bake_stadium(w, h):
    """Busch Stadium, open-air ballpark, plus a slice of downtown.

    Research: nearly circular bowl, >800ft outside diameter, three seating
    decks completely ringing the field, no roof.  336ft down the lines,
    400ft to centre.  From above: a green mown outfield fan, the brown
    infield arc with its grass diamond and white chalk foul lines, home
    plate at the near side, all inside a red-seat ring.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, lm_CONCRETE, (lm_CONCRETE_DK, lm_CONCRETE_LT), 61, 8, 5)

    scx, scy = w * 0.355, h * 0.50
    orx, ory = w * 0.335, h * 0.465

    def ell(f):
        return pygame.Rect(int(scx - orx * f), int(scy - ory * f),
                           int(orx * 2 * f), int(ory * 2 * f))

    # street ring + shadow of the bowl
    pygame.draw.ellipse(s, lm_SHADOW, ell(1.0).move(7, 7))
    pygame.draw.ellipse(s, lm_CONCRETE_DK, ell(1.0))
    pygame.draw.ellipse(s, lm_OUTLINE, ell(1.0), 2)
    pygame.draw.ellipse(s, lm_SEAT_RED_DK, ell(0.955))
    pygame.draw.ellipse(s, lm_SEAT_RED, ell(0.88))
    pygame.draw.ellipse(s, lm_SEAT_RED_DK, ell(0.80))
    pygame.draw.ellipse(s, lm_SEAT_RED, ell(0.72))
    pygame.draw.ellipse(s, lm_CONCRETE_DK, ell(0.645))
    pygame.draw.ellipse(s, lm_OUTLINE, ell(0.645), 1)

    # radial aisles through the decks
    for i in range(28):
        a = 2.0 * math.pi * i / 28.0
        ca, sa = math.cos(a), math.sin(a)
        lm__line(s, lm_SEAT_RED_DK if i % 2 else lm_OUTLINE,
              (scx + ca * orx * 0.655, scy + sa * ory * 0.655),
              (scx + ca * orx * 0.985, scy + sa * ory * 0.985), 1)
    # light standards on the rim
    for i in range(8):
        a = 2.0 * math.pi * (i + 0.5) / 8.0
        px = scx + math.cos(a) * orx * 0.985
        py = scy + math.sin(a) * ory * 0.985
        lm__r(s, lm_SHADOW, px - 2, py - 1, 8, 5)
        lm__r(s, lm_CONCRETE_LT, px - 4, py - 3, 8, 5)
        pygame.draw.rect(s, lm_OUTLINE, (int(px - 4), int(py - 3), 8, 5), 1)

    # ---- the field ---------------------------------------------------------
    frx, fry = orx * 0.63, ory * 0.63
    pygame.draw.ellipse(s, lm_DIRT, ell(0.63))          # warning track
    pygame.draw.ellipse(s, lm__shade(lm_TURF, 0.86), ell(0.63).inflate(-16, -16))
    hx, hy = scx, scy + fry * 0.70

    def wall_hit(a):
        lo, hi = 4.0, max(frx, fry) * 2.4
        for _ in range(22):
            mid = (lo + hi) * 0.5
            px = hx + math.cos(a) * mid
            py = hy + math.sin(a) * mid
            v = ((px - scx) / (frx - 8.0)) ** 2 + ((py - scy) / (fry - 8.0)) ** 2
            if v > 1.0:
                hi = mid
            else:
                lo = mid
        return lo

    a0, a1 = math.pi * 1.25, math.pi * 1.75
    seg = 12
    angs = lm__lin(a0, a1, seg)
    for i in range(seg):
        col = lm_TURF_LT if i % 2 else lm_TURF
        band = [(hx, hy)]
        for a in lm__lin(angs[i], angs[i + 1], 4):
            rr = wall_hit(a)
            band.append((hx + math.cos(a) * rr, hy + math.sin(a) * rr))
        lm__poly(s, col, band)
    # outfield wall along the fan edge
    wallpts = []
    for a in lm__lin(a0, a1, 26):
        rr = wall_hit(a)
        wallpts.append((hx + math.cos(a) * rr, hy + math.sin(a) * rr))
    lm__thick_path(s, wallpts, 3, (46, 62, 46))

    # infield dirt arc
    inf_r = wall_hit(math.pi * 1.5) * 0.40
    arc = [(hx, hy)]
    for a in lm__lin(a0, a1, 14):
        arc.append((hx + math.cos(a) * inf_r, hy + math.sin(a) * inf_r))
    lm__poly(s, lm_DIRT, arc)
    lm__poly(s, lm_DIRT_DK, arc, 1)

    # base-path diamond, grass infield, bases, mound
    d = inf_r * 0.60
    home = (hx, hy - 4)
    first = (hx + d, hy - d - 4)
    second = (hx, hy - 2 * d - 4)
    third = (hx - d, hy - d - 4)
    ctr = (hx, hy - d - 4)
    inner = [(ctr[0] + (p[0] - ctr[0]) * 0.70, ctr[1] + (p[1] - ctr[1]) * 0.70)
             for p in (home, first, second, third)]
    lm__poly(s, lm_TURF, inner)
    lm__poly(s, lm__shade(lm_TURF, 0.85), inner, 1)
    pygame.draw.circle(s, lm_DIRT, (int(ctr[0]), int(ctr[1])), max(4, int(d * 0.20)))
    pygame.draw.circle(s, lm_DIRT_DK, (int(ctr[0]), int(ctr[1])), max(4, int(d * 0.20)), 1)
    lm__r(s, lm_CHALK, ctr[0] - 2, ctr[1] - 1, 4, 2)
    for p in (first, second, third):
        lm__r(s, lm_CHALK, p[0] - 2, p[1] - 2, 5, 5)
    lm__poly(s, lm_CHALK, [(home[0], home[1] - 3), (home[0] + 3, home[1]),
                     (home[0] + 3, home[1] + 3), (home[0] - 3, home[1] + 3),
                     (home[0] - 3, home[1])])
    # backstop dirt behind the plate
    lm__poly(s, lm_DIRT, [(hx - 20, hy + 2), (hx + 20, hy + 2),
                    (hx + 26, hy + 15), (hx - 26, hy + 15)])
    # chalk foul lines
    for a in (a0, a1):
        rr = wall_hit(a)
        lm__line(s, lm_CHALK, (hx, hy), (hx + math.cos(a) * rr, hy + math.sin(a) * rr), 1)

    # ---- downtown blocks along the east side --------------------------------
    dx0 = int(w * 0.715)
    lm__road(s, dx0 - 18, 0, 12, h, False, 63, True, 0)
    lm__road(s, dx0 - 6, int(h * 0.47), int(w - dx0 + 6), 12, True, 64, True, 0)
    cols = [(dx0, int(w * 0.128)), (int(dx0 + w * 0.152), int(w * 0.108))]
    tones = ((74, 72, 80), (92, 86, 90), (62, 60, 68), (104, 96, 94),
             (80, 74, 68), (56, 58, 66))
    for ci, (bx, bw2) in enumerate(cols):
        y = 10
        i = 0
        while y < h - 30:
            n = lm__noise(ci, i, 71)
            bh2 = 44 + (n % 62)
            if y > h * 0.42 and y < h * 0.50:
                y = int(h * 0.50)
                continue
            if y + bh2 > h * 0.44 and y < h * 0.44:
                bh2 = int(h * 0.44 - y)
            if y + bh2 > h - 12:
                bh2 = int(h - 12 - y)
            if bh2 < 18:
                break
            wob = (n >> 7) % 3 * 6
            if (n >> 11) % 7 == 0 and bh2 > 34:
                lm__parking(s, bx, y, bw2 - wob, bh2, 73 + i, False)
            else:
                rf = lm__block(s, bx, y, bw2 - wob, bh2, lm__pick(tones, ci, i, 72), 5, 8)
                lm__r(s, lm__shade(tones[(n >> 3) % len(tones)], 1.25),
                   rf.x + 3, rf.y + 3, rf.w - 6, 3)
                lm__roof_clutter(s, rf, 80 + ci + i, 3)
            y += bh2 + 12
            i += 1
    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


# --------------------------------------------------------------------------
# 3. SOULARD / ANHEUSER-BUSCH BREWERY
# --------------------------------------------------------------------------
def lm__bake_brewery(w, h):
    """Anheuser-Busch, Soulard: 142 acres, ~140 red-brick structures.

    Research: dense red-brick Romanesque blocks on tight streets, crenellated
    towers, the 1891 Brew House, rail spurs threading the complex, rows of
    fermenting/storage tanks, and tall brick smokestacks - the stacks and
    their long shadows are the giveaway from the air.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, (70, 68, 68), (lm_ASPHALT_LT, (82, 78, 76)), 91, 6, 4)

    # rail spur along the south edge
    ry = int(h * 0.90)
    lm__r(s, lm_GRAVEL_DK, 0, ry - 6, w, 16)
    for x in range(0, int(w), 7):
        lm__r(s, (62, 52, 44), x, ry - 5, 4, 14)
    lm__r(s, lm_STEEL_LO, 0, ry - 1, w, 2)
    lm__r(s, lm_STEEL_LO, 0, ry + 6, w, 2)

    # brick blocks on a tight grid
    roofs = (lm_BRICK, lm_BRICK_DK, lm_BRICK_BROWN, lm_TAR, lm_BRICK_LT, lm_TAR_LT)
    gx, gy = 6, 6
    cw, chh = 82, 74
    row = 0
    y = gy
    while y < h * 0.86 - 30:
        col = 0
        x = gx
        while x < w - 40:
            n = lm__noise(col, row, 93)
            bw = cw - 10 + (n % 3) * 8
            bh = chh - 12 + ((n >> 3) % 3) * 8
            if x + bw > w - 6:
                bw = int(w - 6 - x)
            if y + bh > h * 0.86:
                bh = int(h * 0.86 - y)
            if bw > 16 and bh > 14:
                roof = lm__pick(roofs, col, row, 94)
                rf = lm__block(s, x, y, bw, bh, roof, 4, 6)
                # sawtooth skylights on the long industrial roofs
                if (n >> 6) % 3 == 0 and rf.w > 26:
                    for sx in range(rf.x + 4, rf.right - 6, 9):
                        lm__r(s, (150, 152, 148), sx, rf.y + 4, 4, rf.h - 8)
                        lm__r(s, lm__shade(roof, 0.6), sx + 4, rf.y + 4, 2, rf.h - 8)
                elif (n >> 6) % 3 == 1:
                    for j in range(3):
                        m = lm__noise(col, row, 95 + j)
                        lm__r(s, lm_SHADOW, rf.x + 5 + m % max(1, rf.w - 14) + 2,
                           rf.y + 5 + (m >> 5) % max(1, rf.h - 12) + 2, 7, 5)
                        lm__r(s, lm__shade(roof, 0.62), rf.x + 5 + m % max(1, rf.w - 14),
                           rf.y + 5 + (m >> 5) % max(1, rf.h - 12), 7, 5)
                else:
                    lm__r(s, lm__shade(roof, 1.12), rf.x + 3, rf.y + 3, rf.w - 6, 3)
                    lm__r(s, lm__shade(roof, 0.78), rf.x + 3, rf.centery, rf.w - 6, 2)
            x += bw + 12
            col += 1
        y += chh - 6
        row += 1

    # the Brew House: crenellated tower block
    tx, ty, tw, th = int(w * 0.53), int(h * 0.13), 92, 84
    rf = lm__block(s, tx, ty, tw, th, lm_BRICK_DK, 5, 9)
    lm__r(s, lm_BRICK_LT, rf.x + 6, rf.y + 6, rf.w - 12, rf.h - 12)
    pygame.draw.rect(s, lm_OUTLINE, (rf.x + 6, rf.y + 6, rf.w - 12, rf.h - 12), 1)
    for cxx in range(rf.x + 2, rf.right - 4, 8):      # crenellations
        lm__r(s, lm_BRICK_DK, cxx, rf.y + 1, 4, 4)
        lm__r(s, lm_BRICK_DK, cxx, rf.bottom - 5, 4, 4)
    for cyy in range(rf.y + 2, rf.bottom - 4, 8):
        lm__r(s, lm_BRICK_DK, rf.x + 1, cyy, 4, 4)
        lm__r(s, lm_BRICK_DK, rf.right - 5, cyy, 4, 4)

    # storage / fermenting tanks
    for i in range(5):
        tcx = int(w * 0.10) + i * 30
        tcy = int(h * 0.79)
        pygame.draw.circle(s, lm_SHADOW, (tcx + 5, tcy + 5), 13)
        pygame.draw.circle(s, (132, 134, 132), (tcx, tcy), 13)
        pygame.draw.circle(s, (168, 170, 166), (tcx - 4, tcy - 4), 6)
        pygame.draw.circle(s, lm_STEEL_LO, (tcx, tcy), 13, 1)
        pygame.draw.circle(s, lm_OUTLINE, (tcx, tcy), 13, 1)

    # ---- smokestacks, the landmark read -------------------------------------
    def stack(cxs, cys, rad, length):
        d = (0.72, 0.69)
        px, py = -d[1] * rad, d[0] * rad
        tip = (cxs + d[0] * length, cys + d[1] * length)
        lm__alpha_poly(s, [(cxs + px, cys + py), (cxs - px, cys - py),
                        (tip[0] - px * 0.55, tip[1] - py * 0.55),
                        (tip[0] + px * 0.55, tip[1] + py * 0.55)], (8, 7, 9, 185))
        pygame.draw.circle(s, lm_BRICK_DK, (int(cxs), int(cys)), rad)
        pygame.draw.circle(s, lm_BRICK, (int(cxs), int(cys)), rad - 2)
        pygame.draw.circle(s, lm_BRICK_LT, (int(cxs - rad * 0.3), int(cys - rad * 0.3)),
                           max(2, rad // 3))
        pygame.draw.circle(s, (30, 26, 26), (int(cxs), int(cys)), max(2, rad // 2))
        pygame.draw.circle(s, lm_OUTLINE, (int(cxs), int(cys)), rad, 1)

    stack(w * 0.27, h * 0.34, 19, min(w, h) * 0.52)
    stack(w * 0.79, h * 0.55, 11, min(w, h) * 0.32)
    stack(w * 0.12, h * 0.60, 8, min(w, h) * 0.24)

    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


# --------------------------------------------------------------------------
# 4. FOREST PARK
# --------------------------------------------------------------------------
def lm__bake_forest_park(w, h):
    """Forest Park, 1326 acres.

    Research: the Emerson Grand Basin (long formal basin with fountains) at
    the foot of Art Hill, the Cass Gilbert Palace of Fine Arts (Saint Louis
    Art Museum) crowning the hill; Post-Dispatch Lake and connected lagoons
    with wooded islands north/east; 36 holes of golf with bunkers on the
    west; The Muny's fan of open-air seating; wooded edges and a ring road.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, lm_GRASS, (lm_GRASS_DK, lm_GRASS_LT), 101, 8, 5)

    # ---- ring road ---------------------------------------------------------
    ring = pygame.Rect(int(w * 0.055), int(h * 0.06), int(w * 0.89), int(h * 0.88))
    pygame.draw.ellipse(s, lm_OUTLINE, ring.inflate(4, 4))
    pygame.draw.ellipse(s, lm_ASPHALT, ring)
    pygame.draw.ellipse(s, lm_ASPHALT_DK, ring.inflate(-9, -9))
    pygame.draw.ellipse(s, lm_ASPHALT, ring.inflate(-13, -13))
    pygame.draw.ellipse(s, lm_OUTLINE, ring.inflate(-22, -22))
    pygame.draw.ellipse(s, lm_GRASS, ring.inflate(-26, -26))
    _fill_inside = ring.inflate(-26, -26)
    lm__mottle_rect(s, (_fill_inside.x, _fill_inside.y, _fill_inside.w, _fill_inside.h),
                 (lm_GRASS_DK, lm_GRASS_LT), 102, 8, 6)

    # ---- Grand Basin + Art Hill + Art Museum --------------------------------
    bcx, bcy = w * 0.42, h * 0.545
    bw2, bh2 = w * 0.20, h * 0.055
    basin = []
    for a in lm__lin(0, math.pi * 2, 30):
        basin.append((bcx + math.cos(a) * bw2, bcy + math.sin(a) * bh2))
    lm__poly(s, lm_CONCRETE, [(px, py + 3) for (px, py) in basin])
    lm__poly(s, lm_CONCRETE_LT, basin)
    inner = [(bcx + (px - bcx) * 0.90, bcy + (py - bcy) * 0.78) for (px, py) in basin]
    lm__water_poly(s, inner, 103, lm_WATER_DK)
    for i in range(8):
        fx = bcx - bw2 * 0.80 + i * (bw2 * 1.60 / 7.0)
        pygame.draw.circle(s, (140, 168, 184), (int(fx), int(bcy)), 3)
        pygame.draw.circle(s, lm_WATER_LT, (int(fx), int(bcy)), 5, 1)

    # Art Hill: broad contour bands of open turf climbing to the museum
    for i in range(6):
        f = 1.10 - i * 0.13
        band = pygame.Rect(int(bcx - bw2 * f), int(bcy - bh2 - 16 - i * 22),
                           int(bw2 * 2 * f), 46)
        pygame.draw.ellipse(s, lm__shade(lm_GRASS_LT, 1.01 + i * 0.035), band)
    mus_w, mus_h = min(int(bw2 * 0.95), 240), 78
    mx, my = int(bcx - mus_w / 2), int(bcy - bh2 - 176)
    lm__r(s, lm_CONCRETE_DK, mx - 12, my - 8, mus_w + 24, mus_h + 22)
    pygame.draw.rect(s, lm_GRASS_DK, (mx - 12, my - 8, mus_w + 24, mus_h + 22), 1)
    # wings either side of a taller central hall
    lm__block(s, mx, my + 8, mus_w * 0.30, mus_h - 8, lm_LIMESTONE_DK, 4, 7)
    lm__block(s, mx + mus_w * 0.70, my + 8, mus_w * 0.30, mus_h - 8, lm_LIMESTONE_DK, 4, 7)
    rf = lm__block(s, mx + mus_w * 0.28, my, mus_w * 0.44, mus_h, lm_LIMESTONE, 5, 9)
    lm__r(s, lm__shade(lm_LIMESTONE, 0.84), rf.x + 5, rf.y + 5, rf.w - 10, rf.h - 24)
    pygame.draw.rect(s, lm_OUTLINE, (rf.x + 5, rf.y + 5, rf.w - 10, rf.h - 24), 1)
    lm__r(s, lm_LIMESTONE_DK, rf.x + 3, rf.bottom - 19, rf.w - 6, 16)
    for px in range(int(rf.x + 6), int(rf.right - 8), 9):     # portico columns
        lm__r(s, lm_LIMESTONE, px, rf.bottom - 17, 5, 12)
        lm__r(s, lm_SHADOW, px + 5, rf.bottom - 15, 3, 12)
    pygame.draw.rect(s, lm_OUTLINE, (int(rf.x + 3), int(rf.bottom - 19),
                                  int(rf.w - 6), 16), 1)
    # the grand stair and allee down the hill to the basin
    lm__thick_path(s, [(bcx, my + mus_h + 8), (bcx, bcy - bh2 - 6)], 11,
                lm_GRAVEL, lm_GRAVEL_DK)
    for yy in range(int(my + mus_h + 10), int(bcy - bh2 - 8), 9):
        lm__r(s, lm_GRAVEL_DK, bcx - 5, yy, 11, 2)

    # ---- Post-Dispatch Lake, lagoons and channels ---------------------------
    lake = lm__blob(w * 0.695, h * 0.61, w * 0.115, h * 0.115, 104, 26, 0.10)
    lm__poly(s, lm_GRAVEL_DK, [(px + 2, py + 2) for (px, py) in lake])
    lm__water_poly(s, lake, 105, lm_WATER_DK)
    isl = lm__blob(w * 0.705, h * 0.595, w * 0.030, h * 0.032, 106, 14, 0.16)
    lm__poly(s, lm_GRASS_DK, isl)
    lm__poly(s, lm_OUTLINE, isl, 1)
    for k in range(4):
        lm__tree(s, w * 0.705 + (k % 2) * 14 - 7, h * 0.595 + (k // 2) * 13 - 6, 7, 107 + k)
    lag = lm__blob(w * 0.20, h * 0.745, w * 0.075, h * 0.055, 108, 22, 0.12)
    lm__water_poly(s, lag, 109, lm_WATER_DK)
    lag2 = lm__blob(w * 0.545, h * 0.800, w * 0.055, h * 0.042, 110, 20, 0.12)
    lm__water_poly(s, lag2, 111, lm_WATER_DK)
    lm__thick_path(s, [(w * 0.545, h * 0.775), (w * 0.60, h * 0.72),
                    (w * 0.625, h * 0.675)], 9, lm_WATER, lm_WATER_DK)

    # ---- golf: fairways, bunkers, greens ------------------------------------
    for i, (fx, fy, frx, fry) in enumerate(((0.165, 0.26, 0.085, 0.055),
                                            (0.30, 0.185, 0.070, 0.042),
                                            (0.155, 0.44, 0.065, 0.045))):
        fair = lm__blob(w * fx, h * fy, w * frx, h * fry, 112 + i, 18, 0.20)
        lm__poly(s, lm__shade(lm_GRASS_LT, 1.06), fair)
        lm__poly(s, lm_GRASS_DK, fair, 1)
        gx2, gy2 = w * fx + w * frx * 0.55, h * fy - h * fry * 0.35
        pygame.draw.circle(s, (96, 118, 66), (int(gx2), int(gy2)), 13)
        pygame.draw.circle(s, lm_GRASS_DK, (int(gx2), int(gy2)), 13, 1)
        lm__line(s, (210, 206, 196), (gx2, gy2), (gx2, gy2 - 7), 1)
        lm__r(s, (168, 62, 58), gx2, gy2 - 7, 4, 3)
        bunk = lm__blob(w * fx - w * frx * 0.45, h * fy + h * fry * 0.45, 15, 9,
                     115 + i, 12, 0.28)
        lm__poly(s, lm_SAND, bunk)
        lm__poly(s, lm__shade(lm_SAND, 0.72), bunk, 1)

    # ---- The Muny: fan of open-air seating ----------------------------------
    mcx, mcy = w * 0.795, h * 0.235
    lm__r(s, lm_SHADOW, mcx - 40, mcy - 26, 84, 30)
    lm__r(s, lm_CONCRETE_DK, mcx - 44, mcy - 30, 84, 26)
    pygame.draw.rect(s, lm_OUTLINE, (int(mcx - 44), int(mcy - 30), 84, 26), 1)
    for i in range(7):
        rr = 22 + i * 9
        pts = [(mcx + math.cos(a) * rr, mcy + math.sin(a) * rr * 0.92)
               for a in lm__lin(math.radians(18), math.radians(162), 12)]
        lm__thick_path(s, pts, 5, lm_SEAT_RED if i % 2 else lm_SEAT_RED_DK)
    pygame.draw.circle(s, lm_CONCRETE, (int(mcx), int(mcy)), 16)
    pygame.draw.circle(s, lm_OUTLINE, (int(mcx), int(mcy)), 16, 1)

    # ---- paths -------------------------------------------------------------
    lm__thick_path(s, lm__bowed(w * 0.10, w * 0.90, h * 0.32, h * 0.09), 6, lm_GRAVEL, lm_GRAVEL_DK)
    lm__thick_path(s, lm__bowed(w * 0.12, w * 0.88, h * 0.80, -h * 0.10), 6, lm_GRAVEL, lm_GRAVEL_DK)
    lm__thick_path(s, [(w * 0.42, h * 0.62), (w * 0.46, h * 0.72), (w * 0.58, h * 0.76),
                    (w * 0.66, h * 0.72)], 6, lm_GRAVEL, lm_GRAVEL_DK)

    # ---- woods -------------------------------------------------------------
    for r in range(4, int(h / 34) - 1):
        for c in range(3, int(w / 34) - 1):
            n = lm__noise(c, r, 120)
            if n % 7:
                continue
            px = c * 34 + (n % 13)
            py = r * 34 + ((n >> 4) % 13)
            # keep the hero features readable
            if abs(px - bcx) < bw2 + 40 and -300 < (py - bcy) < 190:
                continue
            if math.hypot(px - w * 0.685, py - h * 0.60) < w * 0.14:
                continue
            if math.hypot(px - mcx, py - mcy) < 90:
                continue
            lm__tree(s, px, py, 8 + (n >> 9) % 3, 121)
    # dense wooded rim, two ragged rows deep
    n_h = max(2, int(w / 21))
    n_v = max(2, int(h / 21))
    for i in range(n_h):
        t = i / float(n_h - 1)
        for d in range(2):
            j = lm__noise(i, d, 126)
            lm__tree(s, 10 + t * (w - 20) + (j % 9) - 4, 11 + d * 17 + ((j >> 5) % 9), 9, 122)
            lm__tree(s, 10 + t * (w - 20) + ((j >> 9) % 9) - 4,
                  h - 12 - d * 17 - ((j >> 14) % 9), 9, 123)
    for i in range(n_v):
        t = i / float(n_v - 1)
        for d in range(2):
            j = lm__noise(i, d, 127)
            lm__tree(s, 11 + d * 17 + (j % 9), 10 + t * (h - 20) + ((j >> 5) % 9) - 4, 9, 124)
            lm__tree(s, w - 12 - d * 17 - ((j >> 9) % 9),
                  10 + t * (h - 20) + ((j >> 14) % 9) - 4, 9, 125)

    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


# --------------------------------------------------------------------------
# 5. CENTRAL WEST END
# --------------------------------------------------------------------------
def lm__bake_cwe(w, h):
    """Central West End: dense brick city.

    Research: Edwardian/Romanesque/Victorian brick townhouses and rowhouses,
    apartment flats around courtyards, tree-lined boulevards (Lindell, West
    Pine), about a dozen gated "private places" - loop/cul-de-sac streets off
    the grid - and the Cathedral Basilica's green domes.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, (100, 96, 92), (lm_CONCRETE, lm_CONCRETE_DK), 131, 6, 5)

    street = 22
    cell_w = int((w - street) / max(1, round((w - street) / 172.0)))
    cell_h = int((h - street) / max(1, round((h - street) / 148.0)))

    # streets first
    for gx in range(0, int(w) + cell_w, cell_w):
        lm__road(s, gx - street // 2 + 6, 0, street - 12, h, False, 132, True, 6)
    for gy in range(0, int(h) + cell_h, cell_h):
        lm__road(s, 0, gy - street // 2 + 6, w, street - 12, True, 133, True, 6)

    blocks = []
    ry = 0
    for gy in range(0, int(h) - 20, cell_h):
        rx = 0
        for gx in range(0, int(w) - 20, cell_w):
            bx = gx + street // 2 + 4
            by = gy + street // 2 + 4
            bw = cell_w - street - 4
            bh = cell_h - street - 4
            if bx + bw > w - 4:
                bw = int(w - 4 - bx)
            if by + bh > h - 4:
                bh = int(h - 4 - by)
            if bw > 24 and bh > 24:
                blocks.append((rx, ry, bx, by, bw, bh))
            rx += 1
        ry += 1

    for (rx, ry, bx, by, bw, bh) in blocks:
        kind = lm__noise(rx, ry, 134) % 5
        lm__r(s, (74, 76, 62), bx, by, bw, bh)          # back gardens
        lm__mottle_rect(s, (bx, by, bw, bh), (lm_GRASS_DK, lm_GRASS), 135, 5, 4)
        if kind == 4 and bw > 90 and bh > 70:
            # a whole-block apartment building around a courtyard light-well
            roof = lm__pick(lm_ROWHOUSE_ROOFS, rx, ry, 136)
            rf = lm__block(s, bx, by, bw, bh, roof, 4, 7)
            for k in range(1, 4):                     # party-wall seams
                lm__r(s, lm__shade(roof, 0.66), rf.x + k * rf.w // 4, rf.y + 2, 2, rf.h - 4)
            lm__r(s, lm__shade(roof, 1.16), rf.x + 3, rf.y + 3, rf.w - 6, 3)
            court = pygame.Rect(rf.x + 22, rf.y + 20, rf.w - 44, rf.h - 40)
            if court.w > 16 and court.h > 14:
                lm__r(s, lm_SHADOW, court.x, court.y, court.w, 5)
                lm__r(s, (78, 84, 62), court.x, court.y + 3, court.w, court.h - 3)
                lm__mottle_rect(s, (court.x, court.y + 3, court.w, court.h - 3),
                             (lm_GRASS_DK, lm_GRASS), 137, 5, 3)
                lm__r(s, lm_CONCRETE, court.centerx - 5, court.y + 4, 10, court.h - 4)
                for k in range(max(1, court.w // 26)):
                    lm__tree(s, court.x + 12 + k * 26, court.bottom - 9, 6, 139 + k)
                pygame.draw.rect(s, lm_OUTLINE, court, 1)
        else:
            # two back-to-back rows of narrow rowhouses
            hw, gap = 20, 3
            depth = max(18, int(bh * 0.36))
            n = max(1, int((bw - 4) // (hw + gap)))
            pad = int((bw - (n * (hw + gap) - gap)) / 2)
            for i in range(n):
                hx = bx + pad + i * (hw + gap)
                for (hy, sd) in ((by + 2, 140), (by + bh - depth - 2, 141)):
                    roof = lm__pick(lm_ROWHOUSE_ROOFS, i, ry * 3 + rx, sd)
                    rf = lm__block(s, hx, hy, hw, depth, roof, 3, 4)
                    lm__r(s, lm__shade(roof, 1.18), rf.x + 2, rf.y + 2, rf.w - 4, 3)
                    lm__r(s, lm__shade(roof, 0.72), rf.x + 2, rf.centery - 1, rf.w - 4, 2)
                    if lm__noise(i, ry + rx, sd) % 3 == 0:
                        lm__r(s, (52, 48, 46), rf.centerx - 2, rf.y + 5, 4, 4)

    # street trees along every kerb
    for gx in range(0, int(w) + cell_w, cell_w):
        for py in range(14, int(h) - 8, 26):
            lm__tree(s, gx - street // 2 - 2, py, 6, 142)
            lm__tree(s, gx + street // 2 + 2, py + 13, 6, 143)
    for gy in range(0, int(h) + cell_h, cell_h):
        for px in range(14, int(w) - 8, 26):
            lm__tree(s, px, gy - street // 2 - 2, 6, 144)
            lm__tree(s, px + 13, gy + street // 2 + 2, 6, 145)

    # Cathedral Basilica: cruciform with green domes, top-left block
    if blocks:
        bx, by, bw, bh = blocks[0][2], blocks[0][3], blocks[0][4], blocks[0][5]
        lm__r(s, lm_CONCRETE, bx, by, bw, bh)
        pygame.draw.rect(s, lm_CONCRETE_DK, (bx, by, bw, bh), 1)
        cw2, ch2 = min(bw - 8, 96), min(bh - 8, 78)
        cx2, cy2 = bx + (bw - cw2) // 2, by + (bh - ch2) // 2
        lm__block(s, cx2 + cw2 * 0.30, cy2, cw2 * 0.38, ch2, lm_LIMESTONE, 3, 6)
        lm__block(s, cx2, cy2 + ch2 * 0.32, cw2, ch2 * 0.34, lm_LIMESTONE, 3, 6)
        dcx, dcy = int(cx2 + cw2 * 0.49), int(cy2 + ch2 * 0.48)
        pygame.draw.circle(s, lm_SHADOW, (dcx + 4, dcy + 4), 15)
        pygame.draw.circle(s, lm_VERDIGRIS, (dcx, dcy), 15)
        pygame.draw.circle(s, (104, 148, 128), (dcx - 5, dcy - 5), 6)
        pygame.draw.circle(s, lm_OUTLINE, (dcx, dcy), 15, 1)
        for (tx, ty) in ((cx2 + 6, cy2 + 4), (cx2 + cw2 - 18, cy2 + 4)):
            lm__r(s, lm_SHADOW, tx + 3, ty + 3, 12, 12)
            lm__r(s, lm_VERDIGRIS_DK, tx, ty, 12, 12)
            pygame.draw.rect(s, lm_OUTLINE, (int(tx), int(ty), 12, 12), 1)

    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


# --------------------------------------------------------------------------
# 6. THE HILL
# --------------------------------------------------------------------------
def lm__bake_the_hill(w, h):
    """The Hill: ~50 tight square blocks of Italian-American St. Louis.

    Research: small brick shotgun houses, bungalows and two-family flats on
    narrow lots, built almost to the sidewalk with tiny yards and rear
    alleys; St. Ambrose church with its tile roof anchors the neighbourhood,
    and bocce courts sit behind the social clubs.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, (98, 94, 90), (lm_CONCRETE, lm_CONCRETE_DK), 151, 6, 5)

    street = 20
    cell_w = int((w - street) / max(1, round((w - street) / 118.0)))
    cell_h = int((h - street) / max(1, round((h - street) / 106.0)))
    for gx in range(0, int(w) + cell_w, cell_w):
        lm__road(s, gx - 6, 0, 14, h, False, 152, False, 6)
    for gy in range(0, int(h) + cell_h, cell_h):
        lm__road(s, 0, gy - 6, w, 14, True, 153, False, 6)

    lot, gap, depth = 13, 2, 21
    ry = 0
    for gy in range(0, int(h) - 16, cell_h):
        rx = 0
        for gx in range(0, int(w) - 16, cell_w):
            bx, by = gx + 16, gy + 16
            bw = cell_w - 30
            bh = cell_h - 30
            if bx + bw > w - 4:
                bw = int(w - 4 - bx)
            if by + bh > h - 4:
                bh = int(h - 4 - by)
            if bw < 22 or bh < 22:
                rx += 1
                continue
            lm__r(s, (76, 82, 60), bx, by, bw, bh)
            lm__mottle_rect(s, (bx, by, bw, bh), (lm_GRASS_DK, lm_GRASS), 154, 5, 4)
            # rear alley
            lm__r(s, lm_ASPHALT_LT, bx, by + bh // 2 - 3, bw, 7)
            n = max(1, int((bw - 2) // (lot + gap)))
            pad = int((bw - (n * (lot + gap) - gap)) / 2)
            for i in range(n):
                hx = bx + pad + i * (lot + gap)
                for (hy, sd) in ((by + 1, 155), (by + bh - depth - 1, 156)):
                    if hy + depth > by + bh:
                        continue
                    roof = lm__pick(lm_HILL_ROOFS, i + rx, ry, sd)
                    rf = lm__block(s, hx, hy, lot, depth, roof, 3, 3)
                    # gable ridge down the middle
                    lm__r(s, lm__shade(roof, 1.22), rf.x + 1, rf.centery - 1, rf.w - 2, 2)
                    lm__r(s, lm__shade(roof, 0.74), rf.x + 1, rf.y + 1, rf.w - 2, 2)
                    lm__r(s, lm__shade(roof, 0.74), rf.x + 1, rf.bottom - 3, rf.w - 2, 2)
            rx += 1
        ry += 1

    # St. Ambrose: cruciform, terracotta tile roof, bell tower + piazza
    cw2, ch2 = min(84, int(w * 0.22)), min(66, int(h * 0.20))
    cx2, cy2 = int(w * 0.40), int(h * 0.38)
    lm__r(s, lm_CONCRETE, cx2 - 8, cy2 - 8, cw2 + 16, ch2 + 16)
    pygame.draw.rect(s, lm_CONCRETE_DK, (cx2 - 8, cy2 - 8, cw2 + 16, ch2 + 16), 1)
    lm__block(s, cx2 + cw2 * 0.32, cy2, cw2 * 0.36, ch2, lm_TERRACOTTA, 3, 6)
    lm__block(s, cx2, cy2 + ch2 * 0.30, cw2, ch2 * 0.34, lm_TERRACOTTA, 3, 6)
    for px in range(int(cx2) + 2, int(cx2 + cw2) - 4, 5):    # tile courses
        lm__r(s, lm__shade(lm_TERRACOTTA, 0.78), px, cy2 + ch2 * 0.30, 2, ch2 * 0.34 - 3)
    lm__r(s, lm_SHADOW, cx2 + cw2 * 0.36 + 4, cy2 - 10, 18, 18)
    lm__r(s, lm_BRICK_DK, cx2 + cw2 * 0.36, cy2 - 14, 18, 18)
    lm__r(s, lm_TERRACOTTA, cx2 + cw2 * 0.36 + 4, cy2 - 10, 10, 10)
    pygame.draw.rect(s, lm_OUTLINE, (int(cx2 + cw2 * 0.36), int(cy2 - 14), 18, 18), 1)

    # bocce courts
    for i in range(2):
        bxx, byy = int(w * 0.10), int(h * 0.74) + i * 20
        lm__r(s, lm_SHADOW, bxx + 3, byy + 3, 72, 14)
        lm__r(s, (150, 132, 96), bxx, byy, 72, 14)
        pygame.draw.rect(s, (86, 66, 48), (bxx, byy, 72, 14), 2)
        lm__r(s, (170, 154, 116), bxx + 3, byy + 3, 66, 3)

    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


# --------------------------------------------------------------------------
# 7. DELMAR LOOP
# --------------------------------------------------------------------------
def lm__bake_delmar_loop(w, h):
    """The Delmar Loop: an eight-block commercial STRIP on one street.

    Research: 150+ shops and 55 restaurants in continuous storefronts facing
    each other across Delmar Blvd; brass stars of the St. Louis Walk of Fame
    set into six blocks of sidewalk; the 1924 Tivoli Theatre with its
    marquee; the Loop Trolley rails run down the middle of the street; car
    parks and alleys sit behind the shop rows.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, (96, 92, 88), (lm_CONCRETE, lm_CONCRETE_DK), 161, 6, 5)

    road_h = 44
    walk = 16
    ry = int(h * 0.50 - road_h / 2)
    store_d = int(min(86, (ry - walk) - 34))

    # cross streets carve the strip into blocks
    cross = [int(w * f) for f in (0.255, 0.545, 0.835)]
    cross_w = 20

    # ---- back-of-house: alleys, car parks, the residential fabric behind ---
    for (zy, zh) in ((6, ry - walk - store_d - 20), (ry + road_h + walk + store_d + 14,
                                                     int(h) - (ry + road_h + walk +
                                                               store_d + 14) - 6)):
        if zh < 24:
            continue
        bx = 8
        k = 0
        while bx < w - 20:
            n = lm__noise(k, zy, 171)
            bwd = 46 + (n % 4) * 16
            if bx + bwd > w - 8:
                bwd = int(w - 8 - bx)
            if bwd < 20:
                break
            if any(bx < cxx + cross_w and bx + bwd > cxx - 4 for cxx in cross):
                bx += bwd + 6
                k += 1
                continue
            if n % 3 == 0:
                lm__parking(s, bx, zy + 4, bwd, zh - 8, 172 + k, True)
            else:
                sub = max(1, bwd // 24)
                for j in range(sub):
                    hw2 = bwd // sub - 3
                    rf = lm__block(s, bx + j * (bwd // sub), zy + 6, hw2, zh - 14,
                                lm__pick(lm_ROWHOUSE_ROOFS, k, j, 173), 3, 5)
                    lm__r(s, lm__shade(lm__pick(lm_ROWHOUSE_ROOFS, k, j, 173), 1.2),
                       rf.x + 2, rf.centery - 1, rf.w - 4, 2)
            bx += bwd + 8
            k += 1
    for ay in (ry - walk - store_d - 14, ry + road_h + walk + store_d + 2):
        lm__r(s, lm_ASPHALT_LT, 0, ay, w, 12)
        lm__mottle_rect(s, (0, int(ay), int(w), 12), (lm_ASPHALT, lm_ASPHALT_DK), 174, 5, 4)
        lm__line(s, lm_OUTLINE, (0, ay), (w, ay))
        lm__line(s, lm_OUTLINE, (0, ay + 11), (w, ay + 11))

    # pavement + carriageway go down first so the awnings can sit on them
    lm__r(s, lm_CONCRETE, 0, ry - walk, w, walk)
    lm__r(s, lm_CONCRETE, 0, ry + road_h, w, walk)
    lm__r(s, lm_ASPHALT, 0, ry, w, road_h)
    lm__mottle_rect(s, (0, ry, int(w), road_h), (lm_ASPHALT_DK, lm_ASPHALT_LT), 166, 6, 5)
    lm__line(s, lm_CONCRETE_DK, (0, ry - 1), (w, ry - 1))
    lm__line(s, lm_CONCRETE_DK, (0, ry + road_h), (w, ry + road_h))

    # rows of storefronts, north and south
    rows = ((ry - walk - store_d, 1), (ry + road_h + walk, -1))
    x = 8
    idx = 0
    tivoli_x = None
    while x < w - 20:
        n = lm__noise(idx, 0, 162)
        sw = 26 + (n % 4) * 7
        if idx == 4:
            sw = 74            # the Tivoli
            tivoli_x = x
        if x + sw > w - 8:
            sw = int(w - 8 - x)
        if sw < 14:
            break
        hit = [cxx for cxx in cross if x < cxx + cross_w and x + sw > cxx - 4]
        if hit:
            x = hit[0] + cross_w + 4
            idx += 1
            continue
        for (ty, face) in rows:
            roof = lm__pick((lm_TAR, (96, 74, 62), (84, 82, 84), lm_BRICK_BROWN,
                          (108, 88, 70), lm_SLATE), idx, ty, 163)
            if idx == 4:
                roof = (86, 62, 58)
            rf = lm__block(s, x, ty, sw, store_d, roof, 4, 6)
            lm__r(s, lm__shade(roof, 0.7), rf.x + 2, rf.y + 2, rf.w - 4, rf.h - 4)
            lm__r(s, lm__shade(roof, 1.1), rf.x + 4, rf.y + 4, rf.w - 8, rf.h - 8)
            pygame.draw.rect(s, lm_OUTLINE, (rf.x + 2, rf.y + 2, rf.w - 4, rf.h - 4), 1)
            if idx == 4:
                # the Tivoli: barrel-vaulted auditorium roof over the shops
                for i, yy in enumerate(range(rf.y + 6, rf.bottom - 5, 5)):
                    t = abs((yy - rf.centery) / max(1.0, rf.h * 0.5))
                    lm__r(s, lm__shade(roof, 1.30 - t * 0.55), rf.x + 6, yy, rf.w - 12, 4)
                pygame.draw.rect(s, lm_OUTLINE, (rf.x + 5, rf.y + 5, rf.w - 10,
                                              rf.h - 10), 1)
            else:
                lm__roof_clutter(s, rf, 164 + idx % 3, 2, roof)
            # awning over the pavement, facing the street
            aw_y = ty + store_d - 2 if face > 0 else ty - 9
            acol = lm__pick(lm_AWNING_COLS, idx, ty, 165)
            lm__r(s, lm_SHADOW, x + 3, aw_y + 3, sw - 2, 10)
            lm__r(s, acol, x, aw_y, sw - 2, 10)
            for sx in range(int(x), int(x + sw - 3), 6):
                lm__r(s, lm__shade(acol, 0.72), sx, aw_y, 3, 10)
            pygame.draw.rect(s, lm_OUTLINE, (int(x), int(aw_y), int(sw - 2), 10), 1)
        x += sw + 4
        idx += 1

    # cross streets, everywhere except across the boulevard itself
    for cxx in cross:
        lm__road(s, cxx, 0, cross_w, ry - walk, False, 175, True, 5)
        lm__road(s, cxx, ry + road_h + walk, cross_w, h - (ry + road_h + walk),
              False, 175, True, 5)

    # street markings
    # trolley rails down the centre
    lm__r(s, lm_STEEL_LO, 0, ry + road_h // 2 - 5, w, 2)
    lm__r(s, lm_STEEL_LO, 0, ry + road_h // 2 + 3, w, 2)
    for px in range(0, int(w), 12):
        lm__r(s, lm_ASPHALT_DK, px, ry + road_h // 2 - 5, 5, 10)
    # lane dashes
    for px in range(4, int(w) - 8, 16):
        lm__r(s, lm_LINE_Y, px, ry + 9, 9, 2)
        lm__r(s, lm_LINE_Y, px, ry + road_h - 11, 9, 2)
    # Walk of Fame brass stars in both pavements
    for px in range(10, int(w) - 6, 16):
        for sy in (ry - walk + 4, ry + road_h + walk - 5):
            pygame.draw.circle(s, lm__shade(lm_GOLD, 0.6), (px + 1, sy + 1), 3)
            pygame.draw.circle(s, lm_GOLD, (px, sy), 3)
            pygame.draw.circle(s, (206, 186, 118), (px - 1, sy - 1), 1)
    # kerbside lamps and trees
    for px in range(20, int(w) - 10, 44):
        lm__r(s, lm_SHADOW, px + 3, ry - 8, 4, 4)
        lm__r(s, (58, 56, 54), px, ry - 11, 4, 4)
        lm__r(s, lm_SHADOW, px + 25, ry + road_h + 9, 4, 4)
        lm__r(s, (58, 56, 54), px + 22, ry + road_h + 6, 4, 4)
    for px in range(42, int(w) - 10, 44):
        lm__tree(s, px, ry - 6, 5, 167)
        lm__tree(s, px + 22, ry + road_h + 6, 5, 168)

    # the Tivoli marquee, projecting over the pavement
    if tivoli_x is not None:
        mx = int(tivoli_x + 5)
        mw = 64
        my = int(ry - walk + 1)
        lm__r(s, lm_SHADOW, mx + 4, my + 4, mw, 14)
        lm__r(s, lm_NEON_RED, mx, my, mw, 14)
        lm__r(s, lm_MARQUEE, mx + 2, my + 2, mw - 4, 10)
        lm__r(s, lm__shade(lm_MARQUEE, 0.7), mx + 5, my + 6, mw - 10, 2)
        for lx2 in range(mx + 3, mx + mw - 3, 5):
            pygame.draw.circle(s, lm_GOLD, (lx2, my + 1), 1)
            pygame.draw.circle(s, lm_GOLD, (lx2, my + 12), 1)
        pygame.draw.rect(s, lm_OUTLINE, (mx, my, mw, 14), 1)
        # vertical blade sign out over the street
        lm__r(s, lm_SHADOW, mx + mw // 2 - 2, my + 14, 13, 26)
        lm__r(s, lm_NEON_RED, mx + mw // 2 - 6, my + 12, 13, 26)
        pygame.draw.rect(s, lm_OUTLINE, (mx + mw // 2 - 6, my + 12, 13, 26), 1)
        for ly in range(my + 15, my + 36, 5):
            pygame.draw.circle(s, lm_MARQUEE, (mx + mw // 2, ly), 2)

    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


# --------------------------------------------------------------------------
# 8. TOWER GROVE PARK
# --------------------------------------------------------------------------
def lm__bake_tower_grove(w, h):
    """Tower Grove Park: 289 acres, best-preserved Gardenesque city park.

    Research: Henry Shaw's 1872 plan - a wide central allee with a drive and
    parallel walks running the length of the park, curvilinear roads and
    paths toward the edges, twelve ornate pavilions/follies and a music
    stand, and the stone Ruins of the Old Lindell Hotel standing beside a
    lily pond.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, lm_GRASS, (lm_GRASS_DK, lm_GRASS_LT), 181, 8, 5)

    cx, cy = w * 0.52, h * 0.50

    # perimeter drive + gates
    per = pygame.Rect(int(w * 0.045), int(h * 0.055), int(w * 0.91), int(h * 0.89))
    pygame.draw.rect(s, lm_GRAVEL, per, 13)
    pygame.draw.rect(s, lm_GRAVEL_DK, per.inflate(-11, -11), 3)
    pygame.draw.rect(s, lm_OUTLINE, per, 1)
    pygame.draw.rect(s, lm_OUTLINE, per.inflate(-26, -26), 1)
    for (gx, gy) in ((per.centerx, per.top), (per.centerx, per.bottom),
                     (per.left, per.centery), (per.right, per.centery)):
        lm__r(s, lm_SHADOW, gx - 10, gy - 4, 24, 12)
        lm__r(s, lm_LIMESTONE_DK, gx - 13, gy - 7, 8, 14)
        lm__r(s, lm_LIMESTONE_DK, gx + 5, gy - 7, 8, 14)
        pygame.draw.rect(s, lm_OUTLINE, (int(gx - 13), int(gy - 7), 8, 14), 1)
        pygame.draw.rect(s, lm_OUTLINE, (int(gx + 5), int(gy - 7), 8, 14), 1)

    # ---- the central allee: drive + parallel walks + rows of trees ---------
    ax0, ax1 = w * 0.07, w * 0.93
    lm__r(s, lm_GRAVEL, ax0, cy - 9, ax1 - ax0, 18)
    lm__line(s, lm_GRAVEL_DK, (ax0, cy - 9), (ax1, cy - 9))
    lm__line(s, lm_GRAVEL_DK, (ax0, cy + 8), (ax1, cy + 8))
    for off in (-30, 30):
        lm__r(s, lm_GRAVEL_DK, ax0, cy + off - 3, ax1 - ax0, 6)

    # ---- radiating allees from the carriage concourse ----------------------
    for i in range(8):
        a = math.pi * 2 * i / 8.0 + math.pi / 8.0
        ln = min(w, h) * 0.40
        p0 = (cx + math.cos(a) * 60, cy + math.sin(a) * 60)
        p1 = (cx + math.cos(a) * ln, cy + math.sin(a) * ln)
        lm__thick_path(s, [(cx + math.cos(a) * 46, cy + math.sin(a) * 46), p1],
                    7, lm_GRAVEL, lm_GRAVEL_DK)
        nx, ny = -math.sin(a), math.cos(a)
        for sgn in (-1, 1):
            row = [(p0[0] + nx * 15 * sgn, p0[1] + ny * 15 * sgn),
                   (p1[0] + nx * 15 * sgn, p1[1] + ny * 15 * sgn)]
            lm__tree_line(s, row, 31, 8, 182 + i)

    # allee tree rows
    for off in (-48, -68, 48, 68):
        lm__tree_line(s, [(ax0 + 6, cy + off), (ax1 - 6, cy + off)], 31, 8, 183)

    # ---- carriage concourse + music stand ----------------------------------
    pygame.draw.circle(s, lm_GRAVEL, (int(cx), int(cy)), 46)
    pygame.draw.circle(s, lm_GRAVEL_DK, (int(cx), int(cy)), 46, 2)
    pygame.draw.circle(s, lm_GRASS, (int(cx), int(cy)), 30)
    pygame.draw.circle(s, lm_OUTLINE, (int(cx), int(cy)), 46, 1)
    pygame.draw.circle(s, lm_OUTLINE, (int(cx), int(cy)), 30, 1)
    oct_pts = [(cx + math.cos(math.pi * 2 * i / 8 + 0.39) * 17,
                cy + math.sin(math.pi * 2 * i / 8 + 0.39) * 17) for i in range(8)]
    lm__poly(s, lm_SHADOW, [(px + 5, py + 5) for (px, py) in oct_pts])
    lm__poly(s, (150, 128, 78), oct_pts)
    lm__poly(s, lm_OUTLINE, oct_pts, 1)
    lm__poly(s, (188, 168, 108), [(cx + (px - cx) * 0.55, cy + (py - cy) * 0.55)
                               for (px, py) in oct_pts])
    pygame.draw.circle(s, lm_LIMESTONE, (int(cx), int(cy)), 3)

    # ---- ornate pavilions --------------------------------------------------
    pav_cols = ((146, 74, 66), (72, 106, 108), (150, 126, 72),
                (96, 82, 122), (128, 96, 62))
    for i, (px, py) in enumerate(((0.20, 0.24), (0.78, 0.26), (0.30, 0.78),
                                  (0.72, 0.76), (0.86, 0.50))):
        pxx, pyy = w * px, h * py
        rr = 15
        pts = [(pxx + math.cos(math.pi * 2 * k / 8 + 0.39) * rr,
                pyy + math.sin(math.pi * 2 * k / 8 + 0.39) * rr) for k in range(8)]
        lm__poly(s, lm_SHADOW, [(a + 5, b + 5) for (a, b) in pts])
        lm__poly(s, pav_cols[i % len(pav_cols)], pts)
        lm__poly(s, lm_OUTLINE, pts, 1)
        lm__poly(s, lm__shade(pav_cols[i % len(pav_cols)], 1.3),
              [(pxx + (a - pxx) * 0.5, pyy + (b - pyy) * 0.5) for (a, b) in pts])
        pygame.draw.circle(s, lm_GOLD, (int(pxx), int(pyy)), 2)
        lm__thick_path(s, [(pxx, pyy), (pxx + (cx - pxx) * 0.35,
                                     pyy + (cy - pyy) * 0.35)], 5, lm_GRAVEL_DK)

    # ---- the Ruins + lily pond ---------------------------------------------
    rx0, ry0 = w * 0.135, h * 0.585
    pond = lm__blob(rx0 + 46, ry0 + 30, 52, 30, 184, 20, 0.24)
    lm__water_poly(s, pond, 185, lm_WATER_DK)
    for k in range(9):
        lx2 = rx0 + 14 + (lm__noise(k, 0, 186) % 66)
        ly2 = ry0 + 14 + (lm__noise(k, 1, 187) % 34)
        pygame.draw.circle(s, (62, 92, 56), (int(lx2), int(ly2)), 3)
        pygame.draw.circle(s, lm_TREE_DK, (int(lx2), int(ly2)), 3, 1)
    # the Ruins: the salvaged Old Lindell Hotel arcade above the pond
    rw2, rh2 = 104, 30
    rux, ruy = int(rx0 - 8), int(ry0 - 40)
    lm__r(s, lm_SHADOW, rux + 6, ruy + 6, rw2, rh2)
    lm__r(s, lm_GRAVEL, rux - 6, ruy - 5, rw2 + 12, rh2 + 12)
    lm__r(s, lm_LIMESTONE_DK, rux, ruy, rw2, rh2)
    lm__r(s, lm_LIMESTONE, rux + 2, ruy + 2, rw2 - 4, rh2 - 4)
    for k in range(4):                       # four ruined arch openings
        ax2 = rux + 7 + k * 24
        lm__r(s, (46, 44, 42), ax2, ruy + 8, 14, rh2 - 10)
        pygame.draw.circle(s, (46, 44, 42), (ax2 + 7, ruy + 9), 7)
        pygame.draw.circle(s, lm_LIMESTONE_DK, (ax2 + 7, ruy + 9), 7, 1)
        lm__r(s, lm_LIMESTONE_DK, ax2 - 3, ruy + 2, 3, rh2 - 4)
    lm__r(s, lm_GRASS_DK, rux + 20, ruy - 3, 12, 5)
    lm__r(s, lm_GRASS_DK, rux + 68, ruy - 3, 9, 5)
    pygame.draw.rect(s, lm_OUTLINE, (rux, ruy, rw2, rh2), 1)

    # ---- curvilinear paths on the west half + woods -------------------------
    lm__thick_path(s, lm__bowed(w * 0.09, w * 0.46, h * 0.20, h * 0.10), 6, lm_GRAVEL, lm_GRAVEL_DK)
    lm__thick_path(s, lm__bowed(w * 0.09, w * 0.46, h * 0.84, -h * 0.11), 6, lm_GRAVEL, lm_GRAVEL_DK)
    lm__thick_path(s, lm__bowed(w * 0.56, w * 0.94, h * 0.19, h * 0.09), 6, lm_GRAVEL, lm_GRAVEL_DK)
    lm__thick_path(s, lm__bowed(w * 0.56, w * 0.94, h * 0.85, -h * 0.10), 6, lm_GRAVEL, lm_GRAVEL_DK)

    for r in range(2, int(h / 32)):
        for c in range(2, int(w / 32)):
            n = lm__noise(c, r, 188)
            if n % 6:
                continue
            px = c * 32 + (n % 11)
            py = r * 32 + ((n >> 4) % 11)
            if abs(py - cy) < 44 or math.hypot(px - cx, py - cy) < 96:
                continue
            if math.hypot(px - (rx0 + 46), py - (ry0 + 20)) < 80:
                continue
            lm__tree(s, px, py, 8 + (n >> 9) % 3, 189)

    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


# --------------------------------------------------------------------------
# 9. GRAND CENTER ARTS DISTRICT
# --------------------------------------------------------------------------
def lm__bake_grand_center(w, h):
    """Grand Center: theatres and civic halls on Grand Boulevard.

    Research: the 1929 Fox Theatre (4,500 seats, big marquee and vertical
    blade sign, huge stage house behind the auditorium), Powell Hall (1925,
    home of the symphony), the Sun Theater and the Sheldon - 20+ venues on a
    few blocks, with plazas and public art between the larger civic slabs.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, (96, 92, 88), (lm_CONCRETE, lm_CONCRETE_DK), 191, 6, 5)

    bx0 = int(w * 0.46)
    bw0 = int(w * 0.11)
    lm__r(s, lm_CONCRETE, bx0 - 12, 0, bw0 + 24, h)
    lm__road(s, bx0, 0, bw0, h, False, 192, True, 10)
    for cyy in (int(h * 0.045), int(h * 0.50), int(h * 0.95)):   # crosswalks
        for k in range(4):
            lm__r(s, lm_CONCRETE_LT, bx0 + 2 + k * 14, cyy, 9, 12)
    for py in range(6, int(h) - 6, 34):       # lamp standards
        lm__r(s, lm_SHADOW, bx0 - 12, py + 3, 5, 5)
        lm__r(s, (56, 54, 52), bx0 - 15, py, 5, 5)
        lm__r(s, lm_SHADOW, bx0 + bw0 + 12, py + 20, 5, 5)
        lm__r(s, (56, 54, 52), bx0 + bw0 + 9, py + 17, 5, 5)
    for py in range(24, int(h) - 20, 46):     # boulevard street trees
        lm__tree(s, bx0 - 7, py, 6, 199)
        lm__tree(s, bx0 + bw0 + 6, py + 22, 6, 200)

    def auditorium(x, y, aw, ah, roof, salt, barrel=True):
        rf = lm__block(s, x, y, aw, ah, roof, 6, 9)
        if barrel:
            for i, yy in enumerate(range(rf.y + 4, rf.bottom - 3, 5)):
                t = abs((yy - rf.centery) / max(1.0, rf.h * 0.5))
                lm__r(s, lm__shade(roof, 1.22 - t * 0.5), rf.x + 4, yy, rf.w - 8, 4)
        lm__roof_clutter(s, rf, salt, 3, roof)
        return rf

    # ---- Fox Theatre, west of the boulevard --------------------------------
    fx, fy = int(w * 0.055), int(h * 0.10)
    fw, fh = int(w * 0.37), int(h * 0.40)
    stage = lm__block(s, fx, fy, fw * 0.42, fh, (58, 56, 62), 7, 12)
    lm__r(s, lm__shade((58, 56, 62), 1.2), stage.x + 4, stage.y + 4, stage.w - 8, 4)
    aud = auditorium(fx + fw * 0.42, fy, fw * 0.58, fh, (104, 72, 62), 193)
    lobby = lm__block(s, fx + fw * 0.58, fy + fh * 0.12, fw * 0.44, fh * 0.72,
                   (124, 88, 70), 5, 8)
    lm__r(s, lm__shade((124, 88, 70), 0.75), lobby.x + 3, lobby.y + 3, lobby.w - 6, lobby.h - 6)
    lm__r(s, lm__shade((124, 88, 70), 1.15), lobby.x + 6, lobby.y + 6, lobby.w - 12, lobby.h - 12)
    # marquee out over the pavement toward Grand
    mx = lobby.right - 2
    my = int(lobby.centery - 20)
    mw = max(22, bx0 - 6 - mx)
    lm__r(s, lm_SHADOW, mx + 5, my + 5, mw, 40)
    lm__r(s, lm_NEON_RED, mx, my, mw, 40)
    lm__r(s, lm_MARQUEE, mx + 3, my + 3, mw - 6, 34)
    for k in range(3):
        lm__r(s, lm__shade(lm_MARQUEE, 0.66), mx + 5, my + 9 + k * 9, mw - 10, 3)
    for lx2 in range(mx + 3, mx + mw - 2, 5):
        pygame.draw.circle(s, lm_GOLD, (lx2, my + 1), 1)
        pygame.draw.circle(s, lm_GOLD, (lx2, my + 38), 1)
    pygame.draw.rect(s, lm_OUTLINE, (mx, my, mw, 40), 1)
    # vertical blade sign
    lm__r(s, lm_SHADOW, mx + mw // 2 - 2, my - 52, 16, 52)
    lm__r(s, lm_NEON_RED, mx + mw // 2 - 7, my - 56, 16, 56)
    pygame.draw.rect(s, lm_OUTLINE, (mx + mw // 2 - 7, my - 56, 16, 56), 1)
    for ly in range(my - 52, my - 3, 6):
        pygame.draw.circle(s, lm_MARQUEE, (mx + mw // 2 + 1, ly), 2)

    # ---- Powell Hall, east of the boulevard --------------------------------
    px0 = int(bx0 + bw0 + 14)
    pw0 = int(w - px0 - 10)
    ph0 = int(h * 0.34)
    py0 = int(h * 0.09)
    ph_rf = auditorium(px0, py0, pw0, ph0, (98, 92, 84), 194)
    # curved colonnaded front facing the street
    for i in range(9):
        t = i / 8.0
        yy = ph_rf.y + 6 + t * (ph_rf.h - 12)
        xx = ph_rf.x + 2 + math.sin(math.pi * t) * 5
        lm__r(s, lm_LIMESTONE, xx, yy, 5, 4)
        lm__r(s, lm_SHADOW, xx + 5, yy + 2, 2, 4)
    pygame.draw.rect(s, lm_OUTLINE, (ph_rf.x, ph_rf.y, ph_rf.w, ph_rf.h), 1)
    mx2 = ph_rf.x - 1
    lm__r(s, lm_SHADOW, mx2 - 14, ph_rf.centery - 6, 18, 16)
    lm__r(s, (86, 74, 108), mx2 - 18, ph_rf.centery - 10, 18, 16)
    lm__r(s, lm_MARQUEE, mx2 - 15, ph_rf.centery - 7, 12, 10)
    pygame.draw.rect(s, lm_OUTLINE, (mx2 - 18, ph_rf.centery - 10, 18, 16), 1)

    # ---- Sun Theater + Sheldon, south blocks -------------------------------
    sy0 = int(h * 0.60)
    auditorium(int(w * 0.06), sy0, int(w * 0.20), int(h * 0.28), (92, 70, 66), 195)
    sheldon = auditorium(int(w * 0.29), sy0, int(w * 0.14), int(h * 0.28),
                         lm_BRICK_BROWN, 196, False)
    sun = auditorium(px0, int(h * 0.52), int(pw0 * 0.55), int(h * 0.30),
                     (84, 80, 88), 197)

    def small_marquee(x, y, mw2, col):
        x, y, mw2 = int(x), int(y), int(mw2)
        lm__r(s, lm_SHADOW, x + 4, y + 4, mw2, 15)
        lm__r(s, col, x, y, mw2, 15)
        lm__r(s, lm_MARQUEE, x + 2, y + 2, mw2 - 4, 11)
        lm__r(s, lm__shade(lm_MARQUEE, 0.7), x + 4, y + 7, mw2 - 8, 2)
        for lx3 in range(x + 3, x + mw2 - 2, 5):
            pygame.draw.circle(s, lm_GOLD, (lx3, y + 1), 1)
            pygame.draw.circle(s, lm_GOLD, (lx3, y + 13), 1)
        pygame.draw.rect(s, lm_OUTLINE, (x, y, mw2, 15), 1)

    # marquees facing Grand from the smaller houses
    small_marquee(sheldon.right - 2, sheldon.y + 20,
                  max(16, bx0 - 12 - sheldon.right), (86, 60, 96))
    small_marquee(sun.x - 20, sun.bottom - 40, 20, lm_NEON_RED)

    # ---- plaza with light poles and planters --------------------------------
    plz = pygame.Rect(int(px0 + pw0 * 0.60), int(h * 0.52), int(pw0 * 0.40),
                      int(h * 0.42))
    lm__r(s, lm_CONCRETE_LT, plz.x, plz.y, plz.w, plz.h)
    for r in range(plz.y + 5, plz.bottom - 3, 10):
        lm__line(s, lm_CONCRETE_DK, (plz.x + 2, r), (plz.right - 3, r))
    for c in range(plz.x + 5, plz.right - 3, 10):
        lm__line(s, lm_CONCRETE, (c, plz.y + 2), (c, plz.bottom - 3))
    # sculpture court in the middle
    pcx, pcy = plz.centerx, plz.centery
    pygame.draw.circle(s, lm_CONCRETE_DK, (pcx, pcy), 22)
    pygame.draw.circle(s, lm_CONCRETE, (pcx, pcy), 16)
    pygame.draw.circle(s, lm_OUTLINE, (pcx, pcy), 22, 1)
    lm__r(s, lm_SHADOW, pcx - 2, pcy - 3, 12, 12)
    lm__r(s, (146, 108, 62), pcx - 6, pcy - 7, 12, 12)
    pygame.draw.rect(s, lm_OUTLINE, (pcx - 6, pcy - 7, 12, 12), 1)
    for k in range(8):
        a = math.pi * 2 * k / 8.0
        lxp = int(pcx + math.cos(a) * 34)
        lyp = int(pcy + math.sin(a) * 34)
        if not plz.inflate(-10, -10).collidepoint(lxp, lyp):
            continue
        lm__r(s, lm_SHADOW, lxp + 3, lyp + 3, 4, 4)
        lm__r(s, (58, 56, 54), lxp, lyp, 4, 4)
    pygame.draw.rect(s, lm_OUTLINE, plz, 1)
    for k in range(3):
        px3 = plz.x + 10 + k * 20
        if px3 > plz.right - 12:
            break
        lm__r(s, (74, 70, 62), px3 - 8, plz.bottom - 20, 16, 16)
        lm__tree(s, px3, plz.bottom - 12, 7, 198 + k)

    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


lm__BAKERS = {
    "arch": lm__bake_arch,
    "stadium": lm__bake_stadium,
    "brewery": lm__bake_brewery,
    "forest_park": lm__bake_forest_park,
    "central_west_end": lm__bake_cwe,
    "the_hill": lm__bake_the_hill,
    "delmar_loop": lm__bake_delmar_loop,
    "tower_grove": lm__bake_tower_grove,
    "grand_center": lm__bake_grand_center,
}


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def lm_has_art(name):
    """True when this landmark has a hand-made composition."""
    return name in lm_LANDMARK_ART


def lm_ground_color(name):
    """The walkable ground / plaza colour under this landmark."""
    return lm__GROUND.get(lm_LANDMARK_ART.get(name), lm_GRASS)


def lm_label_anchor(name, rect):
    """Centre point the caller should use for the landmark's text label."""
    rect = pygame.Rect(rect)
    fx, fy = lm__LABEL_AT.get(lm_LANDMARK_ART.get(name), (0.5, 0.5))
    return (int(rect.left + rect.width * fx), int(rect.top + rect.height * fy))


def lm__surface_for(style, w, h):
    key = (style, w, h)
    art = lm__CACHE.get(key)
    if art is not None:
        return art
    art = lm__BAKERS[style](w, h)
    try:
        if pygame.display.get_surface() is not None:
            art = art.convert()
    except pygame.error:
        pass
    if len(lm__CACHE) >= lm__CACHE_LIMIT:
        lm__CACHE.pop(next(iter(lm__CACHE)))
    lm__CACHE[key] = art
    return art


def lm_bake():
    """Pre-render every landmark at its natural footprint size.

    Call once after pygame.display.set_mode(); safe to call again (no-op for
    anything already cached).
    """
    for name, (tw, th) in lm_FOOTPRINT_TILES.items():
        style = lm_LANDMARK_ART.get(name)
        if style is None:
            continue
        lm__surface_for(style, tw * lm_TILE, th * lm_TILE)


def lm_draw_landmark(surface, name, rect, camera_clip):
    """Blit the whole landmark composition across `rect` (screen space).

    `rect` is the landmark's full footprint with the camera already applied;
    `camera_clip` is the visible region.  Nothing is ever drawn outside
    either one, and the caller's clip rect is restored afterwards.
    """
    style = lm_LANDMARK_ART.get(name)
    if style is None:
        return
    rect = pygame.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    if camera_clip is None:
        area = rect.clip(surface.get_rect())
    else:
        area = rect.clip(pygame.Rect(camera_clip))
    if area.width <= 0 or area.height <= 0:
        return
    art = lm__surface_for(style, rect.width, rect.height)
    old = surface.get_clip()
    try:
        surface.set_clip(area)
        surface.blit(art, rect.topleft)
    finally:
        surface.set_clip(old)

# ============================================================
# Camera
# ============================================================
class Camera:
    def __init__(self):
        self.x = 0
        self.y = 0

    def center_on(self, rect):
        self.x = rect.centerx - SCREEN_WIDTH // 2
        self.y = rect.centery - SCREEN_HEIGHT // 2
        self.x = max(0, min(MAP_WIDTH - SCREEN_WIDTH, self.x))
        self.y = max(0, min(MAP_HEIGHT - SCREEN_HEIGHT, self.y))

    def apply(self, rect):
        return rect.move(-self.x, -self.y)

    def apply_pos(self, pos):
        return (pos[0] - self.x, pos[1] - self.y)

    def visible_tile_range(self):
        start_col = max(0, self.x // TILE_SIZE - 1)
        end_col = min(MAP_TILES_W, (self.x + SCREEN_WIDTH) // TILE_SIZE + 2)
        start_row = max(0, self.y // TILE_SIZE - 1)
        end_row = min(MAP_TILES_H, (self.y + SCREEN_HEIGHT) // TILE_SIZE + 2)
        return start_col, end_col, start_row, end_row


# ============================================================
# Entities
# ============================================================
class Car:
    """A drivable vehicle: physics-driven, steerable, cartoon-rendered."""

    def __init__(self, x, y, color=None, variant=None):
        self.color = color or random.choice(CAR_COLORS)
        self.variant = variant or random.choice(CIVILIAN_WEIGHTED)
        tune = VEHICLE_TUNING.get(self.variant, {})
        self.width, self.height = tune.get('w', 34), tune.get('h', 18)
        self.rect = pygame.Rect(0, 0, self.width, self.height)
        self.rect.center = (x, y)
        self.angle = random.uniform(0, math.tau)
        self.velocity = 0.0
        self.steer_angle = 0.0
        self.max_speed = 9.5
        self.acceleration = tune.get('acceleration', 0.28)
        self.brake_force = 0.5
        self.drag = 0.965
        self.max_steer = tune.get('max_steer', 0.045)
        # Big rigs top out slower and turn wider; the scooter is nippy. Applied
        # against traffic pace in traffic_drive() / wander_ai().
        self.speed_factor = tune.get('speed_factor', 1.0)
        self.input_throttle = 0.0
        self.input_steer = 0.0
        self.driver = None  # 'player', 'police', or None (parked/wandering)
        self.parked = False  # parked cars sit at the kerb until someone gets in
        self.wander_dir = random.choice([0, 1, 2, 3])

    def move_forward_check(self, dx, dy):
        temp = self.rect.move(int(dx), int(dy))
        if is_blocked(temp) or not (0 <= temp.left and temp.right <= MAP_WIDTH
                                     and 0 <= temp.top and temp.bottom <= MAP_HEIGHT):
            return False
        self.rect.topleft = temp.topleft
        return True

    def physics_step(self):
        if self.input_throttle > 0:
            self.velocity += self.acceleration * self.input_throttle
        elif self.input_throttle < 0:
            self.velocity += self.brake_force * self.input_throttle
        self.velocity = max(-self.max_speed / 2, min(self.max_speed, self.velocity))

        if self.input_throttle == 0:
            self.velocity *= self.drag
            if abs(self.velocity) < 0.02:
                self.velocity = 0.0

        if abs(self.velocity) > 0.15:
            reverse = -1 if self.velocity < 0 else 1
            self.steer_angle += self.input_steer * self.max_steer * reverse
            self.steer_angle = max(-self.max_steer * 2.2, min(self.max_steer * 2.2, self.steer_angle))
            self.angle += self.steer_angle * (abs(self.velocity) / self.max_speed)
        if self.input_steer == 0:
            self.steer_angle *= 0.8

        dx = math.cos(self.angle) * self.velocity
        dy = math.sin(self.angle) * self.velocity
        if not self.move_forward_check(dx, dy):
            self.velocity *= -0.35
            return True  # collided
        return False

    def at_intersection(self):
        """True when the car is near the middle of a crossing tile.

        road_lines = range(4, W, 8), so a crossing is col % 8 == 4 and
        row % 8 == 4. Turning is only allowed here; the old AI re-rolled its
        heading anywhere on the map, which is what made traffic swerve
        mid-block and grind along kerbs.
        """
        c, r = self.rect.centerx // TILE_SIZE, self.rect.centery // TILE_SIZE
        if c % 8 != 4 or r % 8 != 4:
            return False
        ox = abs(self.rect.centerx - (c * TILE_SIZE + TILE_SIZE // 2))
        oy = abs(self.rect.centery - (r * TILE_SIZE + TILE_SIZE // 2))
        return ox < 16 and oy < 16

    def wander_ai(self):
        """Ambient traffic: cruise slowly, turn only at intersections."""
        self.max_speed = traffic_TRAFFIC_MAX_SPEED * self.speed_factor
        self.input_throttle = traffic_TRAFFIC_THROTTLE
        self.input_steer = 0.0
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        dx, dy = directions[self.wander_dir]
        probe = self.rect.move(int(dx * TILE_SIZE * 0.8), int(dy * TILE_SIZE * 0.8))
        target_angle = math.atan2(dy, dx)
        if is_blocked(probe) or (self.at_intersection() and random.random() < 0.04):
            choices = [i for i, (ddx, ddy) in enumerate(directions)
                       if not is_blocked(self.rect.move(int(ddx * TILE_SIZE * 0.8), int(ddy * TILE_SIZE * 0.8)))]
            if choices:
                self.wander_dir = random.choice(choices)
                dx, dy = directions[self.wander_dir]
                target_angle = math.atan2(dy, dx)
        diff = (target_angle - self.angle + math.pi) % math.tau - math.pi
        self.input_steer = max(-1, min(1, diff * 2))
        self.physics_step()

    def chase_ai(self, target_pos):
        tx, ty = target_pos
        dx, dy = tx - self.rect.centerx, ty - self.rect.centery
        target_angle = math.atan2(dy, dx)
        diff = (target_angle - self.angle + math.pi) % math.tau - math.pi
        self.input_steer = max(-1, min(1, diff * 2.2))
        dist = math.hypot(dx, dy)
        self.input_throttle = 1.0 if dist > 40 else 0.0
        self.max_speed = 8.0
        self.physics_step()

    def draw(self, screen, camera, flash_phase=0):
        """Blit a pre-baked pixel sprite for the nearest of 24 headings.

        Replaces the old per-frame transform.rotate: the art is authored at 1x,
        rotated at 8x and nearest-downsampled once at startup, so edges stay
        hard instead of resampling into mush every frame.
        """
        screen_pos = camera.apply_pos(self.rect.center)
        if not (-60 < screen_pos[0] < SCREEN_WIDTH + 60 and -60 < screen_pos[1] < SCREEN_HEIGHT + 60):
            return
        variant = self.variant
        if variant == 'police':
            variant = cars_POLICE_FLASH_SETS[flash_phase % 2]
        # self.angle is never normalised anywhere in the physics, so the index
        # helper has to survive negative and unbounded values. It does (% N).
        idx = cars_angle_index(self.angle)
        sprite, shadow = CAR_SPRITES.get((variant, self.color), (None, None))
        if sprite is None:
            sprite, shadow = CAR_SPRITES[(variant, CAR_COLORS[0])]
        sprite, shadow = sprite[idx], shadow[idx]
        rect = sprite.get_rect(center=(int(screen_pos[0]), int(screen_pos[1])))
        screen.blit(shadow, rect.move(SHADOW_DX, SHADOW_DY))
        screen.blit(sprite, rect)


class RailVehicle:
    """Ambient MetroLink light rail / Loop trolley: runs one fixed row, wraps
    around, never collides. Pure set dressing so the city reads as alive."""

    def __init__(self, sprite, y, speed, x=0.0):
        self.sprite = sprite
        self.flip = pygame.transform.flip(sprite, True, False)
        self.shadow = cars_make_shadow(sprite)
        self.shadow_flip = pygame.transform.flip(self.shadow, True, False)
        self.h = sprite.get_height()
        self.w = sprite.get_width()
        self.y = y
        self.speed = speed
        self.x = x

    def update(self):
        self.x += self.speed
        if self.speed > 0 and self.x > MAP_WIDTH + 48:
            self.x = -self.w - 48
        elif self.speed < 0 and self.x < -self.w - 48:
            self.x = MAP_WIDTH + 48

    def draw(self, screen, camera):
        sx = self.x - camera.x
        sy = self.y - camera.y - self.h // 2
        if sx > SCREEN_WIDTH or sx + self.w < 0 or sy > SCREEN_HEIGHT or sy + self.h < 0:
            return
        east = self.speed >= 0
        img = self.sprite if east else self.flip
        screen.blit(self.shadow if east else self.shadow_flip,
                    (int(sx + SHADOW_DX), int(sy + SHADOW_DY)))
        screen.blit(img, (int(sx), int(sy)))


def build_rail_vehicles():
    """A couple of MetroLink trains on a downtown-latitude line, plus a Loop
    trolley up on the Delmar row."""
    ml = cars_rail_sprite('metrolink')
    tr = cars_rail_sprite('trolley')
    row_dt = 44 * TILE_SIZE + TILE_SIZE // 2       # E-W road line through downtown
    row_loop = 12 * TILE_SIZE + TILE_SIZE // 2     # E-W road line at the Delmar Loop
    return [
        RailVehicle(ml, row_dt, 3.1, x=-500),
        RailVehicle(ml, row_dt, -3.1, x=MAP_WIDTH + 1400),
        RailVehicle(tr, row_loop, 1.9, x=0.0),
    ]


class Follower:
    """A pet/child that trails a pedestrian a fixed distance behind. Currently
    just the dog_walker's dog. Chases a lagging target point, never collides."""

    def __init__(self, kind='dog'):
        self.kind = kind
        self.ci = random.randrange(len(dog__COLORS))
        self.x = self.y = 0.0
        self.facing = 0
        self.anim = 0.0
        self.placed = False

    def update(self, tx, ty):
        if not self.placed:
            self.x, self.y, self.placed = tx, ty, True
        dx, dy = tx - self.x, ty - self.y
        dist = math.hypot(dx, dy)
        if dist > 6:
            step = min(2.6, dist * 0.2)
            self.x += dx / dist * step
            self.y += dy / dist * step
            self.facing = dog_dir_index(dx, dy)
            self.anim += 0.25

    def draw(self, screen, camera):
        pos = camera.apply_pos((self.x, self.y))
        if not (-16 < pos[0] < SCREEN_WIDTH + 16 and -16 < pos[1] < SCREEN_HEIGHT + 16):
            return
        sprite, shadow = dog_sprite(self.ci, self.facing, self.anim)
        rect = sprite.get_rect(center=(int(pos[0]), int(pos[1])))
        screen.blit(shadow, rect.move(SHADOW_DX, SHADOW_DY))
        screen.blit(sprite, rect)


class Pedestrian:
    def __init__(self, x, y, kind=None):
        self.rect = pygame.Rect(0, 0, 14, 14)
        self.rect.center = (x, y)
        self.kind = kind or peds_random_archetype()
        self.dir = [random.choice([-1, 0, 1]), random.choice([-1, 0, 1])]
        self.speed = 0.8 * peds_gait(self.kind)
        self.retarget_timer = 0
        self.bump_cooldown = 0
        self.facing = 2
        self.anim = 0.0
        self.follower = Follower('dog') if peds_has_dog(self.kind) else None

    def update(self):
        self.retarget_timer -= 1
        if self.retarget_timer <= 0:
            self.dir = [random.choice([-1, 0, 1]), random.choice([-1, 0, 1])]
            self.retarget_timer = random.randint(60, 180)
        if self.bump_cooldown > 0:
            self.bump_cooldown -= 1
        dx, dy = self.dir[0] * self.speed, self.dir[1] * self.speed
        if dx or dy:
            self.facing = peds_dir_index(dx, dy)
            self.anim += 0.16          # ~8fps walk cycle at 60fps
        temp = self.rect.move(int(dx), int(dy))
        if is_blocked(temp):
            self.dir = [random.choice([-1, 0, 1]), random.choice([-1, 0, 1])]
        else:
            self.rect.topleft = temp.topleft
        if self.follower:
            # dog trails ~15px behind the walker's heading
            hx = self.dir[0] if (self.dir[0] or self.dir[1]) else 0
            hy = self.dir[1] if (self.dir[0] or self.dir[1]) else 1
            self.follower.update(self.rect.centerx - hx * 15 - 6,
                                 self.rect.centery - hy * 15)

    def draw(self, screen, camera):
        pos = camera.apply_pos(self.rect.center)
        if not (-24 < pos[0] < SCREEN_WIDTH + 24 and -24 < pos[1] < SCREEN_HEIGHT + 24):
            return
        if self.follower:
            self.follower.draw(screen, camera)
        px, py = int(pos[0]), int(pos[1])
        sprite, shadow = ped_sprite(self.kind, self.facing,
                                    self.dir[0] or self.dir[1], self.anim)
        rect = sprite.get_rect(center=(px, py))
        screen.blit(shadow, rect.move(SHADOW_DX, SHADOW_DY))
        screen.blit(sprite, rect)


class Toast:
    def __init__(self, text, ms=2400):
        self.text = text
        self.expires = pygame.time.get_ticks() + ms


# ============================================================
# Game
# ============================================================
class Game:
    def __init__(self):
        pygame.init()
        pygame.font.init()
        self.window = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption("STL-GTA: St. Louis Sandbox")
        self.screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        # Art bakes. All of these run after set_mode() above, which is required
        # for convert_alpha() to pick up the display format.
        bake_car_sprites()
        lm_bake()
        bake_ped_sprites()
        props_bake()
        roofs_bake()
        hud_bake()
        self.postfx = fx_PostFX(SCREEN_WIDTH, SCREEN_HEIGHT, SCALE_FACTOR)
        self.frame = 0
        self.radar_base = None

        self.camera = Camera()
        px, py = random_open_spawn()
        self.player_rect = pygame.Rect(0, 0, PLAYER_SIZE, PLAYER_SIZE)
        self.player_rect.center = (px, py)
        self.player_dir = [0, 0]
        self.player_facing = 2
        self.player_anim = 0.0
        self.driving = None  # Car instance the player is currently driving, or None

        # Most traffic is parked at the kerb, GTA1 style, so there is always a
        # car you can walk up to and steal. The rest drive as ambient traffic.
        parking_set_blocked_fn(is_blocked)
        self.cars = []
        for (sx, sy, sangle, _side) in parking_parking_spots(
                max_count=PARKED_CAR_COUNT, near=(px, py), radius=1400):
            # kerb spots are sized for ordinary cars, so keep the big rigs out
            car = Car(sx, sy, variant=random.choice(CIVILIAN_VARIANTS))
            car.angle = sangle
            car.parked = True
            car.velocity = 0.0
            self.cars.append(car)
        for _ in range(MOVING_CAR_COUNT):
            cx, cy = random_open_spawn(road_only=True)
            self.cars.append(Car(cx, cy))

        self.rail = build_rail_vehicles()

        traffic_set_hooks(is_blocked, GAME_MAP, TILE_SIZE,
                          MAP_TILES_W, MAP_TILES_H, ROAD_LINES)
        for car in self.cars:
            traffic_init_car(car)
            if not car.parked:
                # Car.__init__ hands out a random heading; snap moving traffic
                # into its lane so it does not swing across the road on frame 1
                car.angle = traffic_aligned_spawn_angle(car)

        self.pedestrians = []
        for _ in range(40):
            px2, py2 = random_open_spawn()
            self.pedestrians.append(Pedestrian(px2, py2, self._ped_kind_for(px2, py2)))

        station_x = POLICE_STATION_TILE[0] * TILE_SIZE
        station_y = POLICE_STATION_TILE[1] * TILE_SIZE
        self.police_station = (station_x, station_y)
        self.police = []

        self.wanted_level = 0
        self.score = 0
        self.cash = 0
        self.discovered = set()
        self.toasts = []
        self.infraction_cooldown = 0
        self.wanted_decay_timer = 0
        self.busted_flash = 0
        self.running = True

    # ---------------- persistence ----------------
    def save_game(self):
        state = {
            'player': {'x': self.player_rect.centerx, 'y': self.player_rect.centery},
            'score': self.score,
            'cash': self.cash,
            'wanted_level': self.wanted_level,
            'discovered': list(self.discovered),
        }
        try:
            with open("savegame.json", 'w') as f:
                json.dump(state, f)
            self.add_toast("Game saved")
        except OSError as e:
            self.add_toast(f"Save failed: {e}")

    def load_game(self):
        if not os.path.exists("savegame.json"):
            self.add_toast("No save file found")
            return
        try:
            with open("savegame.json", 'r') as f:
                state = json.load(f)
            self.player_rect.center = (state['player']['x'], state['player']['y'])
            self.score = state.get('score', 0)
            self.cash = state.get('cash', 0)
            self.wanted_level = state.get('wanted_level', 0)
            self.discovered = set(state.get('discovered', []))
            self.add_toast("Game loaded")
        except (OSError, json.JSONDecodeError, KeyError) as e:
            self.add_toast(f"Load failed: {e}")

    # ---------------- helpers ----------------
    def add_toast(self, text):
        self.toasts.append(Toast(text))

    def active_rect(self):
        return self.driving.rect if self.driving else self.player_rect

    @staticmethod
    def _ped_kind_for(x, y):
        """Bias a few pedestrians to their turf: ballplayers by the stadium,
        street musicians in the arts districts. Everyone else is random."""
        col, row = x // TILE_SIZE, y // TILE_SIZE
        for (lx, ly, lw, lh, _kind, name, _c) in LANDMARKS:
            if lx - 3 <= col <= lx + lw + 3 and ly - 3 <= row <= ly + lh + 3:
                if name == "Downtown & Busch Stadium" and random.random() < 0.5:
                    return f"cardinals#{random.randrange(peds__VARIANTS)}"
                if name in ("Grand Center Arts District", "Delmar Loop") and random.random() < 0.4:
                    return f"busker_sax#{random.randrange(peds__VARIANTS)}"
        return None

    # ---------------- input ----------------
    def handle_events(self):
        keys = pygame.key.get_pressed()

        if self.driving:
            throttle = 0.0
            if keys[pygame.K_w] or keys[pygame.K_UP]:
                throttle += 1.0
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:
                throttle -= 1.0
            steer = 0.0
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                steer -= 1.0
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                steer += 1.0
            self.driving.input_throttle = throttle
            self.driving.input_steer = steer
        else:
            dx = dy = 0
            if keys[pygame.K_w] or keys[pygame.K_UP]:
                dy -= 1
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:
                dy += 1
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                dx -= 1
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                dx += 1
            if dx and dy:
                dx *= 0.707
                dy *= 0.707
            self.player_dir = [dx, dy]

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    self.running = False
                elif event.key == pygame.K_e:
                    self.toggle_enter_exit()
                elif event.key == pygame.K_F5:
                    self.save_game()
                elif event.key == pygame.K_F2:
                    self.postfx.toggle()
                elif event.key == pygame.K_F9:
                    self.load_game()

    def toggle_enter_exit(self):
        if self.driving:
            self.driving.driver = None
            self.driving.parked = True
            traffic_hand_back(self.driving)
            exit_pos = (self.driving.rect.centerx - 40, self.driving.rect.centery)
            self.player_rect.center = exit_pos
            self.driving = None
            return
        for car in self.cars:
            if car.driver is None and car.rect.inflate(24, 24).colliderect(self.player_rect):
                car.driver = 'player'
                car.parked = False
                car.max_speed = PLAYER_CAR_MAX_SPEED
                self.driving = car
                self.add_toast("Jacked a ride!")
                self.score += 20
                self.cash += 20
                return

    # ---------------- update ----------------
    def update(self):
        self.frame += 1
        if self.driving:
            collided = self.driving.physics_step()
            if collided:
                self.wanted_bump(0.15, cooldown_key='wall')
        else:
            dx = self.player_dir[0] * PLAYER_SPEED
            dy = self.player_dir[1] * PLAYER_SPEED
            temp = self.player_rect.move(int(dx), int(dy))
            if not is_blocked(temp):
                self.player_rect.topleft = temp.topleft

        self.camera.center_on(self.active_rect())

        for car in self.cars:
            if car.driver is None and not car.parked:
                traffic_drive(car, self.cars)

        for ped in self.pedestrians:
            ped.update()

        for rv in self.rail:
            rv.update()

        self.handle_collisions()
        self.update_police()
        self.update_wanted_decay()
        self.check_landmark_discovery()
        self.toasts = [t for t in self.toasts if pygame.time.get_ticks() < t.expires]
        if self.busted_flash > 0:
            self.busted_flash -= 1

    def wanted_bump(self, amount, cooldown_key):
        if self.infraction_cooldown <= 0:
            self.wanted_level = min(5, self.wanted_level + amount)
            self.infraction_cooldown = 45

    def handle_collisions(self):
        if self.infraction_cooldown > 0:
            self.infraction_cooldown -= 1
        if not self.driving:
            return
        for ped in self.pedestrians:
            if ped.bump_cooldown <= 0 and self.driving.rect.colliderect(ped.rect.inflate(6, 6)):
                ped.bump_cooldown = 90
                push = pygame.Vector2(ped.rect.centerx - self.driving.rect.centerx,
                                       ped.rect.centery - self.driving.rect.centery)
                if push.length() > 0:
                    push = push.normalize() * 24
                    ped.rect.move_ip(int(push.x), int(push.y))
                self.score += 5
                self.cash += 5
                self.wanted_bump(1, 'pedestrian')
                self.add_toast("Yikes! +5")
        for car in self.cars:
            if car is self.driving or car.driver == 'player':
                continue
            if self.driving.rect.colliderect(car.rect):
                self.wanted_bump(0.5, 'traffic')

    def update_police(self):
        target_count = max(0, int(self.wanted_level))
        while len(self.police) < target_count:
            px, py = self.police_station
            cop = Car(px + random.randint(-40, 40), py + random.randint(-40, 40), color=POLICE_COLOR)
            cop.driver = 'police'
            cop.max_speed = 8.0
            self.police.append(cop)
        while len(self.police) > target_count:
            self.police.pop()

        active = self.active_rect()
        for cop in self.police:
            cop.chase_ai(active.center)
            if cop.rect.colliderect(active) and self.busted_flash <= 0:
                self.busted()

    def busted(self):
        self.add_toast("BUSTED!")
        self.busted_flash = FPS * 2
        self.wanted_level = 0
        self.police = []
        if self.driving:
            self.driving.driver = None
            self.driving.parked = True
            self.driving = None
        px, py = random_open_spawn()
        self.player_rect.center = (px, py)
        self.score = max(0, self.score - 50)
        self.cash = max(0, self.cash - 50)

    def update_wanted_decay(self):
        if self.wanted_level <= 0:
            return
        self.wanted_decay_timer += 1
        if self.wanted_decay_timer > FPS * 6:
            self.wanted_decay_timer = 0
            self.wanted_level = max(0, self.wanted_level - 1)
            if self.wanted_level == 0:
                self.add_toast("Cops gave up chasing you")
                self.score += 100
                self.cash += 100

    def check_landmark_discovery(self):
        name = landmark_at(self.active_rect())
        if name and name not in self.discovered:
            self.discovered.add(name)
            self.score += 150
            self.cash += 150
            self.add_toast(f"Discovered: {name}!")

    # ---------------- drawing ----------------
    def draw_tile(self, c, r):
        """Flat terrain: asphalt, sidewalks, markings, parks, water."""
        tile = GAME_MAP[r][c]
        rect = self.camera.apply(pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE))
        t = tile['type']

        if t == TILE_BUILDING:
            return  # roofs + shadows rendered in their own passes

        if t == TILE_PLAZA:
            pygame.draw.rect(self.screen, tile['color'], rect)
            n = _noise(c, r, 17)
            pygame.draw.line(self.screen, COLOR_PLAZA_SEAM,
                             (rect.left, rect.centery), (rect.right, rect.centery), 1)
            pygame.draw.line(self.screen, COLOR_PLAZA_SEAM,
                             (rect.centerx, rect.top), (rect.centerx, rect.bottom), 1)
            for i in range(2):
                gx = rect.left + ((n >> (i * 6)) % 52) + 6
                gy = rect.top + ((n >> (i * 6 + 3)) % 52) + 6
                pygame.draw.rect(self.screen, COLOR_SIDEWALK_SEAM, (gx, gy, 5, 4))
            return

        if t == TILE_PARK:
            pygame.draw.rect(self.screen, tile['color'], rect)
            for i in range(3):
                n = _noise(c, r, 5 + i)
                gx = rect.left + (n % 50) + 6
                gy = rect.top + ((n >> 7) % 50) + 6
                pygame.draw.rect(self.screen, COLOR_PARK_DARK, (gx, gy, 6, 5))
            if (c * 7 + r * 13) % 11 == 0:
                pygame.draw.circle(self.screen, COLOR_TREE_SHADOW,
                                   (rect.centerx + 5, rect.centery + 5), TILE_SIZE // 3 + 2)
                pygame.draw.circle(self.screen, COLOR_PARK_TREE, rect.center, TILE_SIZE // 3)
            return

        if t == TILE_WATER:
            pygame.draw.rect(self.screen, COLOR_WATER, rect)
            n = _noise(c, r, 7)
            for i in range(2):
                wx = rect.left + ((n >> (i * 8)) % 46) + 8
                wy = rect.top + ((n >> (i * 8 + 4)) % 46) + 8
                pygame.draw.rect(self.screen, COLOR_WATER_DARK, (wx, wy, 10, 5))
            pygame.draw.line(self.screen, COLOR_WATER_LINE,
                             (rect.left, rect.centery), (rect.right, rect.centery), 1)
            return

        # --- Roads ---
        pygame.draw.rect(self.screen, COLOR_ROAD, rect)
        n = _noise(c, r, 3)

        # sidewalk aprons on edges that border a non-road tile
        for dr, dc, horizontal in ((0, -1, True), (0, 1, True), (-1, 0, False), (1, 0, False)):
            nt = tile_type_at(c + dc, r + dr)
            if nt == TILE_ROAD:
                continue
            if horizontal:  # apron running along a vertical road edge
                x0 = rect.left + 3 if dc < 0 else rect.right - 12
                pygame.draw.rect(self.screen, COLOR_SIDEWALK, (x0, rect.top + 3, 9, TILE_SIZE - 6))
                pygame.draw.line(self.screen, COLOR_SIDEWALK_SEAM,
                                 (x0 + (9 if dc > 0 else 0), rect.top + 3),
                                 (x0 + (9 if dc > 0 else 0), rect.bottom - 3), 1)
            else:  # apron running along a horizontal road edge
                y0 = rect.top + 3 if dr < 0 else rect.bottom - 12
                pygame.draw.rect(self.screen, COLOR_SIDEWALK, (rect.left + 3, y0, TILE_SIZE - 6, 9))
                pygame.draw.line(self.screen, COLOR_SIDEWALK_SEAM,
                                 (rect.left + 3, y0 + (9 if dr > 0 else 0)),
                                 (rect.right - 3, y0 + (9 if dr > 0 else 0)), 1)

        # intersection: zebra crossings, no centre lines through it
        if c % 8 == 0 and r % 8 == 0:
            self.draw_crosswalk(rect, c, r)
            return

        # tire-grime streak down the lane centre (follows the road direction)
        if r % 8 == 0:
            pygame.draw.rect(self.screen, COLOR_ROAD_DARK, (rect.left + 4, rect.centery - 4, TILE_SIZE - 8, 8))
        else:
            pygame.draw.rect(self.screen, COLOR_ROAD_DARK, (rect.centerx - 4, rect.top + 4, 8, TILE_SIZE - 8))

        # worn patches + cracks
        for i in range(2):
            px = rect.left + ((n >> (i * 10)) % 42) + 8
            py = rect.top + ((n >> (i * 10 + 5)) % 42) + 8
            pygame.draw.rect(self.screen, COLOR_ROAD_LIGHT, (px, py, 7, 4))
            pygame.draw.line(self.screen, COLOR_CRACK, (px + 2, py - 1), (px + 6, py + 4), 1)

        # faded dashed centre line
        if (c % 8) not in (3, 4, 5):
            for y in range(rect.top + 4, rect.bottom - 8, 14):
                pygame.draw.rect(self.screen, COLOR_ROAD_LINE, (rect.centerx - 2, y, 4, 8))
        if (r % 8) not in (3, 4, 5):
            for x in range(rect.left + 4, rect.right - 8, 14):
                pygame.draw.rect(self.screen, COLOR_ROAD_LINE, (x, rect.centery - 2, 8, 4))

    def draw_props(self, c, r):
        """Street furniture. Placement is deterministic per tile so nothing
        flickers between frames."""
        tile = GAME_MAP[r][c]
        ttype = tile['type']
        if ttype in (TILE_WATER, TILE_BUILDING) or self.landmark_has_art(tile):
            return
        is_sidewalk = ttype != TILE_ROAD and (
            tile_type_at(c - 1, r) == TILE_ROAD or tile_type_at(c + 1, r) == TILE_ROAD or
            tile_type_at(c, r - 1) == TILE_ROAD or tile_type_at(c, r + 1) == TILE_ROAD)
        items = props_props_for_tile(c, r, ttype, is_sidewalk)
        if not items:
            return
        base = self.camera.apply(pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE))
        for name, ox, oy in items:
            ax, ay = props_anchor_offset(name)
            x, y = base.left + ox + ax, base.top + oy + ay
            shadow = props_get_shadow(name)
            if shadow is not None:
                self.screen.blit(shadow, (x + SHADOW_DX, y + SHADOW_DY))
            self.screen.blit(props_get(name), (x, y))

    def draw_crosswalk(self, rect, c, r):
        """Zebra stripes on the approach edges that continue as road."""
        for dx, dy, horizontal in ((0, -1, True), (0, 1, True), (-1, 0, False), (1, 0, False)):
            if tile_type_at(c + dx, r + dy) != TILE_ROAD:
                continue
            if horizontal:  # bars span the vertical road (north/south approach)
                y0 = rect.top + 4 if dy < 0 else rect.bottom - 13
                for i in range(3):
                    pygame.draw.rect(self.screen, COLOR_CROSSWALK,
                                     (rect.left + 9 + i * 15, y0, 8, 9))
            else:  # bars span the horizontal road (east/west approach)
                x0 = rect.left + 4 if dx < 0 else rect.right - 13
                for i in range(3):
                    pygame.draw.rect(self.screen, COLOR_CROSSWALK,
                                     (x0, rect.top + 9 + i * 15, 9, 8))

    def landmark_has_art(self, tile):
        name = tile['landmark']
        return name is not None and lm_has_art(name)

    def draw_landmark_art(self):
        """Blit each visible landmark as one composition over its whole
        footprint. These replace the generic tile/roof passes for those tiles,
        so the Gateway Arch reads as an arch instead of a grey slab."""
        clip = pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
        for (lx, ly, lw, lh, kind, name, color) in LANDMARKS:
            if not lm_has_art(name):
                continue
            rect = self.camera.apply(pygame.Rect(lx * TILE_SIZE, ly * TILE_SIZE,
                                                 lw * TILE_SIZE, lh * TILE_SIZE))
            if rect.colliderect(clip):
                lm_draw_landmark(self.screen, name, rect, clip)

    def draw_building_shadow(self, c, r):
        """Cast shadow of an extruded block onto the ground south-east of it.
        Drawn after terrain so it darkens streets, before roofs so it stays
        hidden behind the next block to the south/east."""
        tile = GAME_MAP[r][c]
        if tile['type'] != TILE_BUILDING or self.landmark_has_art(tile):
            return
        rect = self.camera.apply(pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE))
        pygame.draw.rect(self.screen, COLOR_SHADOW, rect.move(8, 8))

    def draw_building_roof(self, c, r):
        """Pseudo-3D building: dark side walls on the east/south faces with
        the roof pulled back toward the north-west, plus rooftop clutter.
        The roof is a stop darker than the tile's brick colour so the lit
        south facade (draw_building_facade) reads as the front of the block."""
        tile = GAME_MAP[r][c]
        if tile['type'] != TILE_BUILDING or self.landmark_has_art(tile):
            return
        rect = self.camera.apply(pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE))
        base = tile['color']
        roof_col = _blend(base, (0, 0, 0), 0.34)
        darker = tuple(int(v * 0.55) for v in base)

        pygame.draw.rect(self.screen, COLOR_BUILDING_WALL, rect)
        roof = (rect.left, rect.top, rect.width - 8, rect.height - 8)
        pygame.draw.rect(self.screen, roof_col, roof)
        pygame.draw.rect(self.screen, darker, roof, 1)

        # rooftop clutter: deterministic per tile, one shared style per landmark
        style = roofs_style_for(c, r, tile['landmark'])
        roofs_draw_roof_detail(self.screen, pygame.Rect(roof), roof_col, c, r, style)

    def draw_building_facade(self, c, r):
        """Hybrid look: a building tile whose south neighbour is open ground
        shows its front wall - brick courses, a row of windows, and either a
        storefront or a residential stoop at street level - instead of roof."""
        tile = GAME_MAP[r][c]
        if tile['type'] != TILE_BUILDING or self.landmark_has_art(tile):
            return
        south = tile_at(c, r + 1)
        if south is None or south['type'] in (TILE_BUILDING, TILE_WATER):
            return                                  # interior of the mass
        rect = self.camera.apply(pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE))
        if rect.right < 0 or rect.left > SCREEN_WIDTH or rect.bottom < -8 or rect.top > SCREEN_HEIGHT:
            return

        base = tile['color']
        wall = _blend(base, COLOR_SIDEWALK, 0.22)          # lit front, brighter than roof
        wall_lo = _blend(base, (0, 0, 0), 0.28)
        course = _blend(base, (0, 0, 0), 0.34)
        trim = _blend(base, COLOR_SIDEWALK, 0.55)
        n = _noise(c, r, 71)
        WALL_H, SKIRT = 24, 7
        top_y = rect.bottom - WALL_H

        pygame.draw.rect(self.screen, wall, (rect.left, top_y, TILE_SIZE, WALL_H + SKIRT))
        pygame.draw.rect(self.screen, trim, (rect.left, top_y - 2, TILE_SIZE, 3))          # cornice
        for yy in range(top_y + 5, rect.bottom + SKIRT, 6):
            pygame.draw.line(self.screen, course, (rect.left, yy), (rect.right - 1, yy))
        pygame.draw.rect(self.screen, wall_lo, (rect.left, rect.bottom - 2, TILE_SIZE, SKIRT + 2))
        pygame.draw.line(self.screen, COLOR_OUTLINE, (rect.left, rect.bottom + SKIRT - 1),
                         (rect.right - 1, rect.bottom + SKIRT - 1))

        kind = n % 10
        if kind == 0:                                       # blank party wall
            if n & 16:                                      # ...with a downspout
                pygame.draw.rect(self.screen, course, (rect.left + 30, top_y, 2, WALL_H))
            return
        commercial = tile['landmark'] in _COMMERCIAL_LANDMARKS
        storefront = commercial or kind <= 3
        win_y = top_y + 6
        if storefront:
            awn = _AWNING_COLORS[n % len(_AWNING_COLORS)]
            pygame.draw.rect(self.screen, _blend(awn, (0, 0, 0), 0.3),
                             (rect.left + 2, win_y - 5, TILE_SIZE - 4, 6))
            pygame.draw.rect(self.screen, awn, (rect.left + 2, win_y - 5, TILE_SIZE - 4, 4))
            sw = pygame.Rect(rect.left + 5, win_y + 2, TILE_SIZE - 26, rect.bottom + SKIRT - win_y - 3)
            pygame.draw.rect(self.screen, (44, 52, 60), sw)
            pygame.draw.rect(self.screen, (120, 150, 168) if n & 8 else (150, 120, 70),
                             sw.inflate(-4, -6))            # lit shop glass
            pygame.draw.rect(self.screen, (26, 22, 24),
                             (rect.right - 17, win_y, 12, rect.bottom + SKIRT - win_y))  # door
            pygame.draw.rect(self.screen, trim, (rect.right - 17, win_y, 12, 2))
        else:
            xs = (rect.left + 12, rect.left + 40) if kind in (4, 5) else \
                 (rect.left + 7, rect.left + 26, rect.left + 45)
            for wx in xs:
                lit = _noise(c, r, wx) % 3 == 0
                glass = (210, 184, 120) if lit else (44, 52, 64)
                pygame.draw.rect(self.screen, (18, 16, 20), (wx - 1, win_y - 1, 15, 15))
                pygame.draw.rect(self.screen, glass, (wx, win_y, 13, 13))
                pygame.draw.line(self.screen, (18, 16, 20), (wx + 6, win_y), (wx + 6, win_y + 12))
                pygame.draw.line(self.screen, trim, (wx - 1, win_y + 13), (wx + 13, win_y + 13))
            if kind in (6, 7):                              # zig-zag fire escape
                for k in range(3):
                    fy = top_y + 4 + k * 7
                    pygame.draw.line(self.screen, COLOR_OUTLINE,
                                     (rect.left + 6, fy), (rect.right - 6, fy))
            pygame.draw.rect(self.screen, trim, (rect.centerx - 7, rect.bottom, 14, SKIRT))
            pygame.draw.rect(self.screen, (26, 22, 24), (rect.centerx - 4, rect.bottom - 6, 8, 6))

    def draw(self):
        self.screen.fill(COLOR_SKY_BG)
        start_col, end_col, start_row, end_row = self.camera.visible_tile_range()
        for r in range(start_row, end_row):
            for c in range(start_col, end_col):
                self.draw_tile(c, r)
        self.draw_landmark_art()
        for r in range(start_row, end_row):
            for c in range(start_col, end_col):
                self.draw_props(c, r)
        for r in range(start_row, end_row):
            for c in range(start_col, end_col):
                self.draw_building_shadow(c, r)
        for r in range(start_row, end_row):
            for c in range(start_col, end_col):
                self.draw_building_roof(c, r)
        for r in range(start_row, end_row):
            for c in range(start_col, end_col):
                self.draw_building_facade(c, r)

        for (lx, ly, lw, lh, kind, name, color) in LANDMARKS:
            frect = self.camera.apply(pygame.Rect(lx * TILE_SIZE, ly * TILE_SIZE,
                                                  lw * TILE_SIZE, lh * TILE_SIZE))
            sx, sy = lm_label_anchor(name, frect) if lm_has_art(name) else frect.center
            if -50 < sx < SCREEN_WIDTH + 50 and -50 < sy < SCREEN_HEIGHT + 50:
                lw = hud_text_width(name, 1)
                hud_text(self.screen, name, int(sx) - lw // 2, int(sy) - 3,
                         hud_HUD_WHITE, True, 1)

        for rv in self.rail:
            rv.draw(self.screen, self.camera)

        for ped in self.pedestrians:
            ped.draw(self.screen, self.camera)
        # Frame-driven, not wall-clock, so headless captures stay deterministic.
        flash = (self.frame // 8) % 2
        for car in self.cars:
            if car is not self.driving:
                car.draw(self.screen, self.camera, flash)
        for cop in self.police:
            cop.draw(self.screen, self.camera, flash)

        if self.driving:
            self.driving.draw(self.screen, self.camera, flash)
        else:
            ppos = self.camera.apply_pos(self.player_rect.center)
            sx, sy = int(ppos[0]), int(ppos[1])
            moving = self.player_dir[0] or self.player_dir[1]
            if moving:
                self.player_facing = peds_dir_index(self.player_dir[0], self.player_dir[1])
                self.player_anim += 0.16
            sprite, shadow = ped_sprite(PEDS_PLAYER_KEY, self.player_facing,
                                        moving, self.player_anim)
            rect = sprite.get_rect(center=(sx, sy))
            self.screen.blit(shadow, rect.move(SHADOW_DX, SHADOW_DY))
            self.screen.blit(sprite, rect)

        self.draw_hud()
        if self.busted_flash > FPS:
            flash_surf = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            flash_surf.fill((255, 0, 0, 60))
            self.screen.blit(flash_surf, (0, 0))
            bw = hud_text_width("BUSTED!", 3)
            hud_text(self.screen, "BUSTED!", (SCREEN_WIDTH - bw) // 2,
                     SCREEN_HEIGHT // 2 - 10, hud_HUD_RED, True, 3)

        self.postfx.present(self.screen, self.window)
        pygame.display.flip()

    def build_radar_base(self):
        """Pre-render the static map once.

        The previous HUD re-filled a 40x40 grid of rects every single frame,
        which profiled as roughly half the total frame cost. The map never
        changes, so it is baked to one surface and blitted.
        """
        surf = pygame.Surface((RADAR_SIZE, RADAR_SIZE))
        surf.fill((16, 16, 22))
        scale = RADAR_SIZE / float(MAP_WIDTH)
        step = max(1, MAP_TILES_W // 48)
        cell = max(1, int(step * TILE_SIZE * scale + 0.5))
        for r in range(0, MAP_TILES_H, step):
            for c in range(0, MAP_TILES_W, step):
                surf.fill(GAME_MAP[r][c]['color'],
                          (int(c * TILE_SIZE * scale), int(r * TILE_SIZE * scale), cell, cell))
        return surf

    def draw_hud(self):
        """GTA1 arcade gauge: chunky score and cash right-aligned at the top,
        wanted stars and the radar stacked beneath on the same right edge."""
        right = SCREEN_WIDTH - 10
        ticks = pygame.time.get_ticks()

        hud_draw_score(self.screen, self.score, right, 8, 2)
        hud_draw_cash(self.screen, self.cash, right, 32, 2)

        star_w = hud_draw_stars(self.screen, self.wanted_level,
                                right - STAR_BLOCK_W, 56, ticks)[0]

        # radar, aligned to the same right edge as the gauge above it
        rx, ry = right - RADAR_SIZE, 74
        if self.radar_base is None:
            self.radar_base = self.build_radar_base()
        self.screen.blit(self.radar_base, (rx, ry))
        scale = RADAR_SIZE / float(MAP_WIDTH)
        active = self.active_rect()
        pygame.draw.circle(self.screen, hud_HUD_WHITE,
                           (int(rx + active.centerx * scale),
                            int(ry + active.centery * scale)), 2)
        for cop in self.police:
            pygame.draw.circle(self.screen, hud_HUD_RED,
                               (int(rx + cop.rect.centerx * scale),
                                int(ry + cop.rect.centery * scale)), 1)
        hud_draw_radar_frame(self.screen, pygame.Rect(rx, ry, RADAR_SIZE, RADAR_SIZE))

        # mode readout, bottom left
        mode = "DRIVING" if self.driving else "ON FOOT"
        hud_text(self.screen, mode, 12, SCREEN_HEIGHT - 18, hud_HUD_GOLD, True, 1)

        # toasts stack above the mode readout
        for i, toast in enumerate(reversed(self.toasts[-3:])):
            hud_text(self.screen, toast.text, 12, SCREEN_HEIGHT - 32 - i * 12,
                     hud_HUD_WHITE, True, 1)

    # ---------------- main loop ----------------
    def run(self):
        print("=" * 60)
        print("  STL-GTA: St. Louis Open-World Sandbox")
        print("=" * 60)
        print("  WASD / Arrows - Move or Drive")
        print("  E             - Enter / Exit Vehicle")
        print("  F5 / F9       - Save / Load")
        print("  ESC / Q       - Quit")
        print(f"  Explore {len(LANDMARKS)} St. Louis landmarks. Reckless driving raises your wanted level!")
        print("=" * 60)

        while self.running:
            self.handle_events()
            if not self.running:
                break
            self.update()
            self.draw()
            self.clock.tick(FPS)

        pygame.quit()


def main():
    Game().run()


if __name__ == "__main__":
    main()

import pygame
import argparse
import collections
import sys
import os
import json
import math
import random

import missions as mission_logic
import throwables as throwable_logic

GAME_DIR = os.path.dirname(os.path.abspath(__file__))
# Saves belong to the player, not whichever folder happened to be current when
# a desktop shortcut launched the game. Keep the old repo-adjacent file as a
# read-only migration source so existing progress is not stranded.
_user_data_root = (os.environ.get('LOCALAPPDATA')
                   or os.environ.get('XDG_DATA_HOME')
                   or os.path.join(os.path.expanduser('~'), '.local', 'share'))
SAVE_PATH = os.path.join(_user_data_root, 'STL-GTA', 'savegame.json')
LEGACY_SAVE_PATH = os.path.join(GAME_DIR, 'savegame.json')

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
# The original 4.2 crossed a whole city block in under two seconds and made
# every key-tap feel like a lunge. 3.6 is still arcade-fast, but gives corners,
# pedestrians and storefronts enough time to register.
PLAYER_SPEED = 3.6
PLAYER_SPRINT_SPEED = 5.0
PLAYER_STAMINA_MAX = FPS * 3.0
PLAYER_STAMINA_DRAIN = 1.0
PLAYER_STAMINA_REGEN = 0.65
PLAYER_STAMINA_HIDDEN_REGEN = 1.05
FOOT_ACCEL_RESPONSE = 0.42    # fraction of the gap to target speed closed/step
FOOT_BRAKE_RESPONSE = 0.58    # stopping stays a little crisper than starting

# Sprite draw scale. Purely cosmetic: collision rects stay 34x18 (car) and
# 14x14 (ped) so physics and traffic spacing are untouched. At 1.0 the game
# read like a map viewed from too high up: street details were charming only
# after somebody explained what they were. A modest nearest-neighbour lift
# keeps the city in view while making a person, motorcycle, truck livery, and
# hydrant legible during normal play rather than only in a screenshot crop.
SPRITE_SCALE_CAR = 1.45
SPRITE_SCALE_PED = 1.50
SHADOW_DX = 3               # southeast, matching the building shadows
SHADOW_DY = 3

# Measured at 22 moving cars: a mean of 3.7 pairs of AI cars overlapping each
# other at any moment, 11 at worst, and ambient traffic averaging 1.26 px/step
# against its own 3.25 cap - i.e. permanently jammed. A 64px street simply
# does not have room for that many cars once each one is also braking for its
# neighbours. Fewer cars, moving properly, read as a busier city than more
# cars stacked in a knot.
PARKED_CAR_COUNT = 22       # includes two fixed local showcase vehicles below
MOVING_CAR_COUNT = 10       # calmer local bubble; parked cars keep theft plentiful
PEDESTRIAN_COUNT = 72       # people on the street

# --- Population streaming -------------------------------------------------
# The map is 100x100 tiles and the viewport sees 0.56% of it, so a population
# scattered over the whole city puts nobody on screen: 40 pedestrians measured
# 0.0 visible on average. Raising the raw count cannot fix that - you would
# need ~1800 of them. Instead the pool stays modest and anything that wanders
# out of earshot is recycled into the ring just outside the view, which is what
# GTA1 did: the city you cannot see does not need simulating.
POP_KEEP_RADIUS = 760       # px from the player before an entity is recycled
# The respawn ring hugs the viewport: its inner edge is just past the screen
# corner (hypot(320, 180) = 367) so nothing ever pops into view, but close
# enough that moving even a little sweeps fresh traffic and people into shot.
POP_RESPAWN_MIN = 390
POP_RESPAWN_MAX = 650
POP_RECYCLE_PER_STEP = 3    # spread the work over frames, avoid mass teleports
POP_AHEAD_SPREAD = 1.9      # radians either side of travel to bias respawns into
POP_AHEAD_SPEED = 2.5       # px/step of travel before that bias kicks in
# Concentrating traffic near the player also concentrates its jams. A car that
# has sat still off-screen this long has deadlocked against its neighbours, so
# recycle it rather than let the knot grow.
POP_STALL_STEPS = FPS * 5
POP_OFFSCREEN = 400         # px: past the screen corner, safe to teleport

# Ambient traffic used to run at the player's own 9.5 top speed on a 0.55
# throttle, so it was uncatchable on foot. Traffic speed
# and lane discipline now live in the traffic_ai section, which owns the
# tuning constants; wander_ai below is kept only as a fallback.
#
# 8.6 px/step is 516 px/s across a 640px-wide viewport: you crossed the whole
# screen in 1.2s and a city block in 1.0s, which is where "everything happens
# faster than you can react" came from. 6.4 still crosses the entire 6400px
# map in seventeen seconds - a proper cross-town chase - while leaving time to
# read a junction before you are in it.
PLAYER_CAR_MAX_SPEED = 6.4
PLAYER_THROTTLE_RESPONSE = 0.44   # progressive pedal, not an on/off switch
# Power tapers as you approach the ceiling, so the top of the range has to be
# earned and holding it feels like something. Fraction of acceleration lost at
# top speed.
PLAYER_POWER_FADE = 0.55
PLAYER_COAST_DRAG = 0.9885   # lifting off no longer scrubs a third of your speed
PLAYER_BRAKE = 0.40
PLAYER_REVERSE_ACCEL = 0.20
PLAYER_REVERSE_RATIO = 0.62  # reverse is useful, but never the fastest escape line

# --- Cornering ------------------------------------------------------------
# The old model integrated steer_angle and then multiplied the yaw by
# (0.45 + 0.55 * speed_frac), so the car turned *harder* the faster it went:
# 288 deg/s at top speed, a 103px radius that shrank to 43px when you slowed
# down. Backwards, and the reason the car felt like it was on rails until it
# suddenly was not.
#
# Now it is a bicycle model: yaw = speed * steer_angle * PLAYER_YAW_GAIN, with
# the steering *lock* fading as speed rises. Radius therefore grows with
# speed - 30px crawling, ~190px flat out - so you brake for corners, and yaw
# peaks in the mid range exactly like a real car.
PLAYER_YAW_GAIN = 0.74
PLAYER_LOCK_FADE = 0.82      # fraction of steering lock given up at top speed
PLAYER_STEER_RATE = 0.115    # of the gap to full lock closed per step
PLAYER_STEER_RETURN = 0.20   # ... and how fast the wheel self-centres
# Lateral grip budget, px/step^2. Ask the tyres for more cornering force than
# this and the nose washes wide instead: carry too much speed into a bend and
# you understeer into the far kerb, which is the entire skill of the game.
PLAYER_GRIP = 0.215
# The handbrake gets a LARGER budget, not a smaller one. Locking the rears
# does not stop the front tyres steering - it stops the back holding a line,
# which is the whole point: the nose comes round faster and the car keeps
# travelling the way it was already going (LAT_RETAIN_HANDBRAKE below is what
# carries the slide). Setting this below PLAYER_GRIP made pulling the
# handbrake turn the car *slower* than not pulling it, measured at 89 deg/s
# against 155.
PLAYER_GRIP_HANDBRAKE = 0.40

# --- Camera ---------------------------------------------------------------
# The lead used to be `sin(angle) * v * 15 * aspect` on the vertical, which at
# top speed is 229px of lead against a 180px half-viewport: driving north or
# south the camera pushed the car clean off the bottom of the screen. Measured
# 822 frames out of frame in a 1920-frame sweep. The lead is now expressed as
# a fraction of each axis' own half-viewport, so it can never do that again -
# and Camera.center_on clamps it a second time as a backstop.
CAM_LEAD_STEPS = 16.0        # steps of travel the view tries to look ahead
CAM_LEAD_MAX_X = 0.34        # of the half-viewport, horizontally
CAM_LEAD_MAX_Y = 0.30        # ... and vertically, where there is less room
CAM_LEAD_EASE = 0.075        # how fast the lead follows a change of direction
CAM_SAFE_MARGIN_X = 96       # px of frame the player may never be pushed into
CAM_SAFE_MARGIN_Y = 62
CAM_FOOT_LEAD = 30.0         # on foot: a fixed nudge, there is no speed to read
# --- The street network ----------------------------------------------------
# This used to be `set(range(4, MAP_TILES_W, 8))` in both directions: a perfect
# square lattice, every block the same size, not one street with a name. No
# city looks like that and St. Louis looks like it least of all - the whole
# character of driving here is that the grid is interrupted. Three things
# changed:
#
#   1. The lines are now an explicit, IRREGULAR list. County blocks out west
#      are long, downtown blocks are short, exactly as they are on the ground.
#   2. Every line carries a real street name and a class. Arterials are wider
#      and carry the traffic; locals are the side streets.
#   3. The named DIAGONALS exist. Gravois, Manchester and Natural Bridge do
#      not run at right angles to anything, which is the single most St. Louis
#      fact about driving here, and the reason "TAKE GRAVOIS, THEY'LL NEVER
#      FOLLOW" is a thing somebody yells at you.
#
# Anything that needs "is this a road line" asks ROAD_LINES / STREET_AT; the
# old ROAD_ORIGIN / ROAD_STEP pair is kept only because the props and parking
# sections advertise them, and a uniform step is no longer meaningful.
#
# One shared list of line indices for both axes. A very large amount of this
# file asks "is index i a road line" without saying which axis it means
# (is_road_crossing, the traffic lane model, parking, cop navigation), so
# giving the two axes different spacings would quietly desync all of it. The
# irregularity - which is the part you can actually see - lives in the gaps.
ROAD_LINE_LIST = (2, 9, 15, 21, 27, 32, 37, 43, 50, 57, 63, 68, 73, 79, 86, 93)
ROAD_LINES = set(ROAD_LINE_LIST)

# The names, per axis. Ordered west-to-east and north-to-south to match the
# geography the LANDMARKS table traces. A line that falls inside a park or a
# landmark simply does not exist there, which is correct: Forest Park has no
# through streets, and neither does Tower Grove Park.
NS_STREET_NAMES = {
    2:  "BIG BEND BLVD",
    9:  "SKINKER BLVD",
    15: "HAMPTON AVE",
    21: "MACKLIND AVE",
    27: "ARSENAL ST",           # the short north-south leg out west
    32: "KINGSHIGHWAY",         # Forest Park's east wall, the CWE's west
    37: "VANDEVENTER",
    43: "MORGANFORD RD",
    50: "COMPTON AVE",
    57: "GRAND BLVD",           # runs straight through Grand Center
    63: "JEFFERSON AVE",
    68: "14TH ST",
    73: "TUCKER BLVD",
    79: "BROADWAY",
    86: "4TH ST",
    93: "WHARF ST",
}
EW_STREET_NAMES = {
    2:  "RIVERVIEW BLVD",
    9:  "NATURAL BRIDGE",
    15: "ST LOUIS AVE",
    21: "DELMAR BLVD",          # the Loop rides it; so does the Divide
    27: "LINDELL BLVD",         # Forest Park's north wall
    32: "OLIVE ST",              # downtown approach to the Eads Bridge
    37: "MARKET ST",            # downtown to the Arch, on the Arch's own axis
    43: "CHOUTEAU AVE",
    50: "ARSENAL ST",           # carries the Poplar Street Bridge
    57: "MAGNOLIA AVE",         # Tower Grove Park's north wall
    63: "GRAVOIS AVE",          # the grid leg; the diagonal is the real one
    68: "CHEROKEE ST",
    73: "MERAMEC ST",
    79: "CHIPPEWA ST",          # Ted Drewes is on it, which is the point
    86: "DELOR ST",
    93: "LOUGHBOROUGH",
}
ARTERIAL_NS = frozenset((2, 9, 15, 32, 57, 63, 73, 79))
ARTERIAL_EW = frozenset((9, 21, 27, 37, 43, 50, 79, 93))
ARTERIAL_LINES = ARTERIAL_NS | ARTERIAL_EW

# Compatibility: the props and parking sections re-export these. There is no
# single step any more, so this is the *median* gap - used only for sizing
# heuristics (how far apart to scatter a prop), never to decide road-ness.
# Anything that wants to know whether an index is a street must ask ROAD_LINES.
ROAD_ORIGIN = min(ROAD_LINE_LIST)
ROAD_STEP = 6


def street_name(col, row):
    """The street a tile is on, or None. A diagonal wins over the grid: if you
    are on Gravois you are on Gravois, whatever it happens to be crossing."""
    if (col, row) in globals().get('RIVER_DES_PERES_TILES', ()):
        return "RIVER DES PERES CHANNEL"
    if (col, row) in globals().get('CHAIN_OF_ROCKS_TILES', ()):
        return "OLD CHAIN OF ROCKS BRIDGE"
    diagonal = DIAGONAL_AT.get((col, row))
    if diagonal:
        return diagonal
    on_ns = col in ROAD_LINES
    on_ew = row in ROAD_LINES
    if on_ns and on_ew:
        return f"{NS_STREET_NAMES.get(col, '')} & {EW_STREET_NAMES.get(row, '')}".strip(" &")
    if on_ns:
        return NS_STREET_NAMES.get(col)
    if on_ew:
        return EW_STREET_NAMES.get(row)
    return None

# The diagonals, as (name, (col0,row0), (col1,row1), width in tiles). These are
# stamped AFTER the landmarks, so they cut the grid the way the real ones cut
# the city instead of being erased by the first district they touch.
#
# Gravois leaves downtown heading south-west and does not stop being annoying
# until Affton; it crosses Morganford at Bevo Mill, which is why the windmill
# is where it is. Manchester runs west-south-west out through the Grove.
# West Florissant runs north-west through the north side; Natural Bridge is
# the grid arterial at row 9. Giving both pieces one name made the road cross
# itself on the map and made turn callouts actively misleading.
# (name, polyline of (col,row), width in tiles). A polyline, not a segment,
# because the real ones bend: Gravois leaves downtown between Union Station
# and the ballpark, runs down the EAST side of Tower Grove Park - the park is
# west of Gravois, ask anyone - and only then swings out to the windmill at
# Morganford, which is why Bevo Mill sits in the fork.
DIAGONAL_STREETS = (
    # One tile is already a complete two-lane street (the regular streets use
    # the same 64px envelope). The old two-tile stamp made every diagonal a
    # 128px asphalt plaza. Gravois also aimed its centreline through Bevo Mill;
    # this bend passes east of the mill before turning south-west.
    ("GRAVOIS AVE", ((71, 51), (52, 73), (50, 77), (39, 83),
                     (36, 88), (24, 96)), 1),
    ("MANCHESTER AVE", ((58, 40), (2, 47)), 1),
    ("WEST FLORISSANT AVE", ((66, 30), (8, 4)), 1),
)


def _diagonal_run(points, width):
    """Every tile of a multi-leg diagonal, in order, de-duplicated."""
    out, seen = [], set()
    for a, b in zip(points, points[1:]):
        for t in _diagonal_tiles(a, b, width):
            if t not in seen:
                seen.add(t)
                out.append(t)
    return tuple(out)


def _diagonal_headings(points, width):
    """tile -> the unit vector the street is actually travelling there.

    The tiles are a 4-connected staircase because collision and reachability
    are 4-connected, but the *street* is not a staircase: it runs at about 40
    degrees. Renderers need the real heading, or every tile gets boxed in
    square kerbs and the road reads as a flight of stairs, which is exactly
    what it looked like.
    """
    out = {}
    for a, b in zip(points, points[1:]):
        dc, dr = b[0] - a[0], b[1] - a[1]
        mag = math.hypot(dc, dr) or 1.0
        unit = (dc / mag, dr / mag)
        for t in _diagonal_tiles(a, b, width):
            out.setdefault(t, unit)
    return out


def _diagonal_tiles(start, end, width):
    """A 4-connected staircase between two points, `width` tiles thick.

    Deliberately NOT a raw Bresenham line. Bresenham steps diagonally, which
    leaves consecutive tiles touching only at a corner - and every reachability
    check in this file (and every car collider) is 4-connected, so a corner
    touch is a wall. Stepping one axis at a time costs nothing visually at
    64px per tile and gives a road you can actually drive down.
    """
    (c0, r0), (c1, r1) = start, end
    dc, dr = c1 - c0, r1 - r0
    steps = max(abs(dc), abs(dr))
    if steps == 0:
        return ()
    # Thicken across the shallow axis, so a mostly-east-west diagonal gets its
    # extra lanes stacked north-south and still reads as one road.
    thicken_rows = abs(dc) >= abs(dr)
    tiles, seen = [], set()
    col, row = c0, r0

    def claim(c, r):
        for w in range(width):
            t = (c, r + w) if thicken_rows else (c + w, r)
            if t not in seen:
                seen.add(t)
                tiles.append(t)

    claim(col, row)
    for i in range(1, steps + 1):
        want_c = c0 + int(round(dc * i / steps))
        want_r = r0 + int(round(dr * i / steps))
        while col != want_c or row != want_r:
            if col != want_c:
                col += 1 if want_c > col else -1
            else:
                row += 1 if want_r > row else -1
            claim(col, row)
    return tuple(t for t in tiles
                 if 0 <= t[0] < MAP_TILES_W and 0 <= t[1] < MAP_TILES_H)


#: (col,row) -> street name, for every tile any diagonal occupies.
DIAGONAL_AT = {}
#: (col,row) -> (ux, uy), the direction the diagonal runs through that tile.
DIAGONAL_DIR = {}
for _dname, _dpts, _dw in DIAGONAL_STREETS:
    for _t in _diagonal_run(_dpts, _dw):
        DIAGONAL_AT.setdefault(_t, _dname)
    for _t, _u in _diagonal_headings(_dpts, _dw).items():
        DIAGONAL_DIR.setdefault(_t, _u)

# Curbs stop at the mouth of a crossing. The diagonal asphalt continues over
# the cardinal street, but its sidewalk shoulders must not make two pale bars
# across the intersecting carriageway.
DIAGONAL_GRID_CROSSINGS = frozenset(
    (col, row) for col, row in DIAGONAL_AT
    if col in ROAD_LINES or row in ROAD_LINES
)
del _dname, _dpts, _dw, _t, _u

# Speedometer scale. A bare 8.4 was calibrated against a top speed the car no
# longer has, so the needle topped out at 54 - derive it instead, and a stock
# sedan reads 85 while a Trans Am reads 95 whatever the tuning does next.
HUD_TOP_MPH = 85
HUD_MPH_PER_PX = HUD_TOP_MPH / PLAYER_CAR_MAX_SPEED

RADAR_SIZE = 86             # GTA1 proportions, a shade larger than the old 78
# The radar shows a WINDOW on the city, not the whole thing. At the old
# whole-map scale (78px for 6400px of world, 0.0122 px per world px) a city
# block was six radar pixels and, at four stars, the player dot and five cop
# dots occupied an eight-pixel smear - it could tell you neither where the
# next turn was nor where the police were, which are the only two things a
# radar exists for. The whole-city view lives on the M / TAB map screen,
# which already does it well.
RADAR_WORLD = 1120          # world px across the radar: 17 tiles, ~2 blocks
RADAR_BASE_PX = 800         # the city baked once at this size, then sub-sampled
STAR_BLOCK_W = 76           # width of the 6-slot wanted star row
MAP_OVERVIEW_SIZE = 300     # side of the full-city map drawn by the M / TAB screen

# --- Gamepad (Xbox 360 / XInput layout) ----------------------------------
# SDL2 reports an XInput pad with this axis and button order; anything that
# presents the same layout (Xbox One, most XInput clones) works unchanged.
PAD_DEADZONE = 0.26         # stick slop before we call it input
PAD_TRIGGER_DEADZONE = 0.12
PAD_AX_LX, PAD_AX_LY = 0, 1
PAD_AX_LT = 2
PAD_AX_RX, PAD_AX_RY = 3, 4
PAD_AX_RT = 5
PAD_A, PAD_B, PAD_X, PAD_Y = 0, 1, 2, 3
PAD_LB, PAD_RB, PAD_BACK, PAD_START = 4, 5, 6, 7
# Buttons route through the existing keydown handler, so pause / map / save
# behave identically however you pressed them.
PAD_BUTTON_KEYS = {
    PAD_A: pygame.K_e,          # jack / leave a car
    PAD_RB: pygame.K_q,          # cycle weapon
    PAD_X: pygame.K_SPACE,      # punch or shoot
    PAD_B: pygame.K_SPACE,
    PAD_Y: pygame.K_m,          # full city map
    PAD_BACK: pygame.K_m,
    PAD_START: pygame.K_ESCAPE,  # pause (and back out of the map)
}

# --- Simulation timing ---------------------------------------------------
# Every tuning constant in this file (PLAYER_SPEED, accelerations, drag,
# steer rates) is authored per *simulation step*, not per second. The main
# loop therefore runs a fixed-step accumulator: real elapsed time is banked
# and spent in exact 1/60s slices, so the sim is identical at 30fps, 60fps
# or 240fps instead of running in slow motion whenever a frame is late.
SIM_DT = 1.0 / FPS
MAX_SIM_STEPS = 5           # steps per rendered frame before we drop time
MAX_FRAME_TIME = 0.25       # a stall longer than this is discarded, not caught up

# --- Game states ---
STATE_PLAYING = 0
STATE_PAUSED = 1
STATE_DEAD = 2              # the WASTED / BUSTED ritual, before you respawn
STATE_TITLE = 3
STATE_CHARACTER = 4

# --- Death / respawn ------------------------------------------------------
# Dying used to be a two-second red flash that you played straight through:
# wasted() teleported you a few tiles sideways and handed control straight
# back, so the screen said WASTED while you were still driving. Death is now
# its own state - input is dead, the sim idles, the banner holds - and you
# always come back under the Gateway Arch.
DEATH_HOLD_STEPS = FPS * 3          # how long the WASTED / BUSTED card holds
DEATH_FADE_STEPS = FPS              # of that, the tail spent fading to black
DEATH_SKIP_AFTER_STEPS = FPS * 3 // 4  # let the result land before accepting Continue

# --- Wanted level / police ------------------------------------------------
WANTED_MAX = 5
# Per-offence re-arm delay in sim steps, so one long scrape is one offence.
INFRACTION_COOLDOWN = {
    'pedestrian': FPS * 1,
    'traffic': FPS * 3,
    'cop': FPS * 2,
    'gunfire': FPS * 2,
}
COP_SPAWN_MIN = 420         # px: cops arrive from off-screen, not from downtown
COP_SPAWN_MAX = 900
BUST_CONTACT_STEPS = 90     # ~1.5s of sustained contact before you get busted
BUST_RELIEF = 6             # bust meter drains quickly once you break the hold
# You cannot be pulled out of a moving car. Below this, a cruiser leaning on
# you counts as an arrest in progress; above it, it is just a ram - it hurts
# and it shunts you, but the door stays shut. Without this one number a single
# mistake at speed was terminal: touch a wall, lose your momentum for a second
# and the chase was simply over, which is the "one error and you're caught"
# complaint in a nutshell. Now a bad corner costs you your lead, not the run.
BUST_MAX_SPEED = 2.4        # px/step
HEAT_GRACE = FPS * 3        # steps clean before the wanted level starts to fall
# Steps to shed one star, indexed by the level you are shedding *from*. Low
# stars go fast so a one-star scrape resolves inside a block; high stars are
# a real commitment.
WANTED_DECAY_BY_STAR = (0, FPS * 6, FPS * 6, FPS * 9, FPS * 9, FPS * 9)
WANTED_DECAY_STEPS = FPS * 8   # fallback / test reference
# Bail scales with how hot you were when they took you, so a five-star bust
# is a real loss and running is worth something.
BAIL_MAX_LOSS = 1000       # an arrest hurts, but never wipes out a successful session
BAIL_BY_STAR = (100, 100, 250, 500, 1000, 1000)
BAIL_COST = 250             # reference figure; see bail_for()

# --- Police senses: the chase is now a game of being seen ----------------
# Cops used to be handed the player's exact position every step forever, so
# there was no such thing as hiding: a wall between you and a cruiser only
# slowed it down. A cop now has to have *line of sight* to know where you are.
# Break it and it drives to where it last saw you, hunts around, and gives up.
COP_SIGHT = 340             # px: reference figure; see COP_SIGHT_BY_STAR
COP_SIGHT_FOV = 1.10        # radians: reference; see COP_FOV_BY_STAR
COP_SIGHT_CLOSE = 90        # px: this close they hear you regardless of facing
COP_SEARCH_STEPS = FPS * 10  # how long a cop hunts your last known position
# Control, calling it in. A cop with no line of sight used to hunt one stale
# point and then give up, so a chase died the moment you turned a corner - at
# 6 px/step that is about a second, and the "chase across the map" never
# happened. A car being driven hard down a public street is conspicuous:
# every so often the units still looking get an updated fix on it. Stop, or
# get off the road and out of sight, and the radio goes quiet - the hiding
# mechanic is untouched, because hidden players broadcast nothing.
COP_RADIO_STEPS = FPS * 2    # how often a searching unit gets a fresh fix
COP_RADIO_SPEED = 3.0        # px/step below which you are not worth calling in
COP_RADIO_RANGE = 1600       # px: how far the net coordinates over
COP_SEARCH_WANDER = 150     # px it will cast around that point while searching
COP_PATROL_STEPS = FPS * 8  # circling the block after the search runs dry

# Per-star escalation. The shape that matters: one star is a lone beat cop
# on foot you can lose in a gangway, five stars is the whole department in
# cars. Escalating by adding another identical cruiser - which is what this
# used to do - gives the top of the ladder no identity and the bottom no
# chance. Index == wanted level.
COP_COUNT_BY_STAR = (0, 0, 1, 2, 3, 4)      # cruisers
COP_FOOT_BY_STAR = (0, 1, 1, 1, 2, 3)       # beat cops / tactical foot response
# Every one of these used to sit ABOVE the player's own top speed, so a
# straight-line flee from two stars closed 274px in ten seconds and there was
# no such thing as outrunning the police - only outliving them. Escalation is
# now numbers, aggression and how long they hold the scent; pace is pegged to
# the player's car. A standard sedan (PLAYER_CAR_MAX_SPEED) outruns one and
# two stars, matches three, and is marginally slower than four and five -
# which is what makes stealing a Trans Am (speed_factor 1.12) at five stars
# the right move rather than a cosmetic one.
COP_SPEED_BY_STAR = (0.0, 5.8, 6.1, 6.4, 6.7, 7.0)
# Absolute sight radius in px, NOT a multiple of a base. The screen is only
# 640x360, so anything over ~300 lets a cop see you from off the edge of the
# frame, which always reads as cheating however true it is.
COP_SIGHT_BY_STAR = (0, 190, 230, 265, 290, 300)
COP_FOV_BY_STAR = (0.0, 0.95, 1.00, 1.05, 1.10, 1.20)     # radians, half-angle
# Steps before the *first* unit of a fresh star actually turns up. One star
# used to conjure a cruiser on top of you inside a second.
COP_RESPONSE_BY_STAR = (0, FPS * 3, FPS * 2, FPS * 1, FPS // 2, 0)
JURISDICTION_CONFIRM_STEPS = 30
CITY_LIMIT_COL = 9

# --- High-heat containment -------------------------------------------------
# Four stars changes the shape of the pursuit instead of merely adding another
# faster cruiser. Dispatch closes a road ahead with two parked units and a
# spike strip; five stars fields a second closure and replaces passed blocks
# faster. Placement is deterministic and only accepts complete footprints on
# non-collidable road geometry.
ROADBLOCK_COUNT_BY_STAR = (0, 0, 0, 0, 1, 2)
ROADBLOCK_AHEAD_MIN = 360
ROADBLOCK_AHEAD_MAX = 980
ROADBLOCK_PREFERRED = (520, 760)
ROADBLOCK_RETIRE_BEHIND = 360
ROADBLOCK_RETIRE_DISTANCE = 620
ROADBLOCK_REDEPLOY_BY_STAR = (0, 0, 0, 0, FPS * 4, FPS * 2)
ROADBLOCK_STRIP_LONG = 52
ROADBLOCK_STRIP_THICK = 10
ROADBLOCK_HIT_COOLDOWN = FPS
SPIKE_PUNCTURE_STEPS = FPS * 8
SPIKE_SPEED_SCALE = 0.48
SPIKE_STEER_SCALE = 0.58
SPIKE_ENTRY_SPEED_SCALE = 0.62
SPIKE_DAMAGE = 8.0

# --- Beat cops on foot ----------------------------------------------------
# The art has been baked since the pedestrian pass (peds_COP_KEY) and never
# had any behaviour attached. A foot cop is the only unit that can actually
# complete an arrest on a player who is also on foot: a cruiser doing 10 px a
# step runs you over long before the bust meter fills.
COP_FOOT_SEARCH_SPEED = 3.10
COP_FOOT_CHASE_SPEED = 3.85
COP_FOOT_BURST_SPEED = 4.15
COP_FOOT_BURST_STEPS = FPS
COP_FOOT_SPEED = COP_FOOT_CHASE_SPEED  # compatibility / tuning reference
COP_FOOT_SIGHT = 185
COP_FOOT_FOV = 0.95
COP_FOOT_GIVEUP = FPS * 9
COP_FOOT_RESPAWN = FPS * 4
COP_FOOT_HP = 70.0
COP_FOOT_HIT_STUN = 18
COP_FOOT_KNOCKDOWN = FPS * 2

# The crime scene. Cops dispatched for a star are sent to where the offence
# happened, not conjured with a fix on the player - without this a low star
# is not a chase, it is a countdown, because the lone unit spawns 400-900px
# out with no idea which way to look and simply never finds you.
CRIME_SCENE_STALE = FPS * 12

# --- Hiding ---------------------------------------------------------------
# Standing still, out of sight, off the street. Do it and the heat drains
# several times faster - the "duck into a gangway and hold your breath" beat
# that every good chase in the series has.
HIDE_STILL_SPEED = 1.2      # px/step below which you count as holding still
HIDE_ARM_STEPS = FPS * 1    # steps of stillness+cover before HIDDEN latches
HIDE_DECAY_SCALE = 3.0      # how much faster stars shed while hidden
HIDE_CAR_STEPS = FPS * 2    # sitting still in a parked car also counts
HIDE_ARCH_SCALE = 6.0       # under the span of the Arch, it drains twice again

# --- On-foot damage -------------------------------------------------------
# A car sitting on top of you used to apply its full damage *every step*: a
# cruiser at 9.9 dealt 44 HP a step, so the player died in three frames with
# no chance to react. One hit now costs one hit, then you get thrown clear and
# briefly cannot be hit again.
HURT_IMMUNE_STEPS = 45      # 0.75s of i-frames after a car hits you on foot
# One scrape is one impact. The three contact-damage sites (a wall, a rammed
# car, a cruiser leaning on you) all run once per step for as long as the rects
# overlap; without this a half-second graze was thirty hits.
CRASH_DAMAGE_COOLDOWN = 20  # steps between impacts from sustained contact
# What a crash costs YOU, per px/step of impact speed. The damage you deal is
# deliberately left alone - ramming a car off the road should still wreck it in
# a handful of hits - but the car you are sitting in has to survive a chase
# across the city, and at the old figures forty seconds of hard driving totalled
# it whether or not the police were anywhere near.
PLAYER_WALL_DAMAGE = 0.80
PLAYER_RAM_DAMAGE = 0.45
# Impact thresholds, as fractions of the player's top speed rather than the
# literals they used to be. Every one of these was authored against a 9.5 top
# speed; left as numbers they silently became "only at 70% of flat out" the
# moment the car got slower, which is how a game quietly stops reacting to
# anything you do.
IMPACT_MIN_SPEED = PLAYER_CAR_MAX_SPEED * 0.32   # worth a sound and sparks
IMPACT_HURT_SPEED = PLAYER_CAR_MAX_SPEED * 0.42  # worth damage
IMPACT_HEAVY_SPEED = PLAYER_CAR_MAX_SPEED * 0.68  # worth a frame of hitstop
RAM_SPEED = PLAYER_CAR_MAX_SPEED * 0.50          # a shunt, not a nudge
ROADKILL_DAMAGE = 3.4       # HP per px/step of closing speed
ROADKILL_MAX = 30.0         # HP ceiling on a single hit, whatever the speed
RESPAWN_IMMUNE_STEPS = FPS * 2   # you come to next to live Memorial Drive traffic
COP_RAMMING_STAR = 4        # below this, cops brake for you instead of mowing

# --- "Where'd you go to high school?" -------------------------------------
# The question. You will be asked it, by strangers, within ninety seconds of
# arriving, and the answer places you on a map more precisely than an address
# would. Walk into somebody slowly and there is a one-in-six chance they turn
# round and ask - and whatever you say, they say OH and walk off.
HS_CHANCE = 6               # 1 in N barged pedestrians ask
HS_COOLDOWN = FPS * 12      # steps before anybody asks again
HS_QUESTION = "WHERE'D YOU GO TO HIGH SCHOOL?"
HS_ANSWERS = ("SLUH", "CBC", "MEHLVILLE", "KIRKWOOD", "VASHON", "ROSATI")
HS_REPLIES = ("OH.", "OH, OKAY.", "HUH.", "OH, YOU KNOW MY COUSIN.",
              "MY BROTHER WENT THERE.")

# Short, local two-person scenes. The first field is either None (citywide) or
# a tuple of neighbourhood keys from hood_at(). They appear both when you brush
# past somebody and occasionally between two calm pedestrians near the player.
#
# This table used to hold 29 scenes: 15 citywide and 14 hood-tagged, spread
# over 11 neighbourhoods. Measured, that meant 83-100% of everything you heard
# ANYWHERE in the city came out of the same 15-item bag, `west` had no local
# lines at all, and selection was a bare random.choice with no memory - so it
# repeated itself back to back. On a 7-second cooldown a five-minute walk drew
# about forty scenes from a pool of sixteen.
#
# It now holds ~300, every one of the 24 neighbourhoods has at least ten of its
# own, and STL_CHATTER deals them from a shuffled bag that will not repeat a
# scene until the deck runs out. What you hear in Soulard is mostly Soulard.
CHATTER_COOLDOWN = FPS * 7
CHATTER_CHECK_STEPS = FPS * 3
CHATTER_BARGE_CHANCE = 3
CHATTER_LOCAL_BIAS = 0.72     # how often a scene comes from the local deck
CHATTER_RECENT = 14           # scenes remembered across a hood boundary

STL_CONVERSATIONS = (
    # ---------------------------------------------------------------- citywide
    (None, "CITY OR COUNTY?", "I KNEW THIS WOULD HAPPEN."),
    (None, "TAKE 40.", "THE SIGN SAYS 64.", "I SAID 40."),
    (None, "WHICH SCHNUCKS?", "THE ONE BY THE OLD SCHNUCKS."),
    (None, "TAKING KINGSHIGHWAY?", "NOT IF I WANT TO ARRIVE."),
    (None, "WHERE ON KINGSHIGHWAY?", "NORTH OR SOUTH OF MANCHESTER?",
     "THAT'S WHAT I'M ASKING."),
    (None, "THAT LIGHT WAS RED.", "IT WAS ST. LOUIS YELLOW."),
    # The city and county test the outdoor sirens the first MONDAY at eleven.
    (None, "TORNADO SIREN?", "FIRST MONDAY. ELEVEN SHARP."),
    (None, "HOW MUCH SNOW?", "ENOUGH TO BUY ALL THE BREAD."),
    (None, "T-RAVS?", "YOU BROUGHT MARINARA, RIGHT?"),
    (None, "THE CARDS ARE REBUILDING.", "SINCE WHEN DO WE SAY THAT?"),
    (None, "CITY MUSEUM WITH KIDS?", "BRING KNEE PADS."),
    (None, "TAKE GRAVOIS.", "WHICH PART?", "EXACTLY."),
    (None, "THAT POTHOLE HAS TENURE.", "THE CONE DOES TOO."),
    (None, "MEET AT THE OLD ARENA.", "IT'S BEEN GONE THIRTY YEARS.",
     "YOU KNOW WHERE I MEAN."),
    (None, "KSHE AGAIN?", "ALWAYS."),
    (None, "THE CITY'S IN NO COUNTY.", "SINCE 1876.", "WE VOTED FOR THAT."),
    (None, "EARNINGS TAX?", "ONE PERCENT.", "FOREVER."),
    (None, "GO CRAZY, FOLKS.", "DON'T. I'LL CRY."),
    (None, "THAT'S A WINNER.", "SAY IT AGAIN."),
    (None, "KMOX AT ELEVEN TWENTY.", "IT COMES IN FROM ANYWHERE."),
    (None, "OPENING DAY IS A HOLIDAY.", "NOT LEGALLY.",
     "LEGALLY IS NOT THE POINT."),
    (None, "PORK STEAK SEASON?", "IT'S ALWAYS PORK STEAK SEASON."),
    (None, "MAULL'S OR NOTHING.", "NOTHING, THEN.", "GET OUT."),
    (None, "IT'S CUSTARD.", "I SAID ICE CREAM.", "YOU SAID WRONG."),
    (None, "PROVEL ISN'T CHEESE.", "SAY THAT LOUDER."),
    (None, "ST. PAUL SANDWICH?", "EGG FOO YOUNG ON WHITE.", "WITH PICKLE."),
    (None, "HOOSIER.", "THAT MEANS SOMETHING ELSE EVERYWHERE.", "NOT HERE."),
    (None, "YOU WARSHED IT?", "I WARSHED IT."),
    (None, "FARTY-FAR.", "FORTY-FOUR.", "THAT'S WHAT I SAID."),
    (None, "WHERE'D YOU PARK?", "BY WHERE THE BANK USED TO BE."),
    (None, "IS IT HUMID?", "IT'S SEPTEMBER."),
    (None, "THE MUNY'S FREE SEATS.", "FIFTEEN HUNDRED OF THEM.",
     "SINCE NINETEEN NINETEEN."),
    (None, "THE ZOO'S FREE TOO.", "AND THE ART MUSEUM.", "WE VOTED FOR THAT."),
    (None, "SEEN THE RIVER?", "IT'S DOING WHAT IT DOES."),
    (None, "EIGHTY-EIGHT MUNICIPALITIES.", "IN ONE COUNTY.", "EIGHTY-EIGHT."),
    (None, "WHOSE SPEED TRAP IS THIS?", "DEPENDS WHICH BLOCK."),
    (None, "BOARD OF ALDERMEN?", "FOURTEEN NOW.", "USED TO BE TWENTY-EIGHT."),
    (None, "THE BLUES WON IT.", "TWENTY-NINETEEN.", "I STILL HEAR THAT SONG."),
    (None, "PLAY GLORIA.", "IT'S TUESDAY.", "PLAY GLORIA."),
    (None, "KA-KAW.", "KA-KAW."),
    (None, "WHAT IS A BILLIKEN?", "NOBODY KNOWS.", "THAT'S THE ANSWER."),
    (None, "THE RAMS LEFT.", "WE GOT PAID.", "STILL."),
    (None, "TURKEY DAY GAME?", "WEBSTER AND KIRKWOOD.",
     "OLDEST WEST OF THE RIVER."),
    (None, "MIZZOU OR ILLINI?", "IN THIS ECONOMY?"),
    (None, "FROZEN CUSTARD IN JANUARY?", "THEY SELL TREES IN JANUARY.",
     "I'LL TAKE BOTH."),
    (None, "GOOEY BUTTER FOR BREAKFAST?", "IT HAS BUTTER. BREAKFAST FOOD."),
    (None, "SLINGER AT MIDNIGHT?", "I RESPECT MYSELF. SO YES."),
    (None, "IMO'S IS A SQUARE.", "BEYOND COMPARE.", "DON'T ENCOURAGE HIM."),
    (None, "GRAND OR CHIPPEWA?", "IS IT SUMMER?", "CHIPPEWA THEN."),
    (None, "THE FLOOD OF NINETY-THREE.", "MY BASEMENT REMEMBERS."),
    (None, "GUMBO FLATS.", "THEY CALL IT THE VALLEY NOW.", "IT'S GUMBO FLATS."),
    (None, "SEEN A VESS BOTTLE?", "THE BIG ONE?", "THERE'S ONLY THE BIG ONE."),
    (None, "CHAIN OF ROCKS BEND.", "TWENTY-TWO DEGREES.", "IN A BRIDGE."),
    (None, "WHERE'S THE HODIAMONT?", "UNDER ALL THIS.", "STILL THERE."),
    (None, "DOES METROLINK GO SOUTH?", "NO.", "STILL NO."),

    # ------------------------------------------------------------------- loop
    (("loop",), "THE LOOP TROLLEY?", "DON'T START."),
    (("loop",), "IT RUNS TWO MILES.", "WHEN IT RUNS."),
    (("loop",), "WHOSE STAR IS THAT?", "READ IT.", "OH. OF COURSE IT IS."),
    (("loop",), "DARTS AT BLUEBERRY HILL?", "I'VE LOST THERE FOR YEARS."),
    (("loop",), "CHUCK BERRY PLAYED HERE.", "MONTHLY.", "DOWNSTAIRS."),
    (("loop",), "U CITY OR THE CITY?", "THE LINE'S RIGHT THERE.",
     "IT ALWAYS IS."),
    (("loop",), "PARKING ON DELMAR?", "THE GARAGE.", "NOBODY USES THE GARAGE."),
    (("loop",), "FITZ'S BOTTLES IN THE WINDOW.", "I WATCH IT EVERY TIME.",
     "SO DOES EVERYONE."),
    (("loop",), "TIVOLI STILL OPEN?", "ASK AGAIN NEXT YEAR."),
    (("loop",), "THE LIONS ON THE GATES.", "THAT'S HOW YOU KNOW."),

    # --------------------------------------------------------------- wellston
    (("wellston",), "THE OLD LOOP TERMINAL.", "BUSES CAME FROM EVERYWHERE.",
     "NOT ANYMORE."),
    (("wellston",), "WELLS-GOODFELLOW.", "SAY THE WHOLE THING.",
     "PEOPLE SHORTEN IT."),
    (("wellston",), "THE CORNER STORE'S BACK?", "NEW AWNING AND ALL."),
    (("wellston",), "THAT CHURCH IS OLDER THAN THE STREET.",
     "MOST OF THEM ARE."),
    (("wellston",), "WHO CUTS YOUR HAIR?", "SAME MAN SINCE I WAS NINE."),
    (("wellston",), "THEY TOOK THE WHOLE BLOCK.", "THEY'LL CALL IT GREEN SPACE.",
     "IT'S A LOT."),
    (("wellston",), "BUS COMES WHEN?", "SOON IS THE SCHEDULE."),
    (("wellston",), "THAT'S A BRICK THIEF.", "THEY TAKE THE WHOLE WALL.",
     "FOR PATIOS SOMEPLACE ELSE."),
    (("wellston",), "GARDEN'S COMING IN.", "TOMATOES OUT OF A VACANT LOT.",
     "BEST ONES THERE ARE."),
    (("wellston",), "YOU FROM OVER NORTH?", "BORN AND STAYED."),

    # ------------------------------------------------------------------- west
    (("west",), "CLAYTON OR THE CITY?", "WHICHEVER TAXES ME LESS.",
     "THAT'S BOTH."),
    (("west",), "PARKING GARAGE IS FIFTEEN.", "AN HOUR?", "A HALF HOUR."),
    (("west",), "THE COUNTY SEAT'S RIGHT THERE.",
     "AND NO COUNTY OWNS THE CITY.", "CORRECT."),
    (("west",), "STRAUB'S BAG?", "I DIDN'T WANT ANYONE TO SEE.",
     "EVERYONE SAW."),
    (("west",), "SCHOOL DISTRICT LINES.", "THAT'S WHY THE HOUSE COSTS THAT."),
    (("west",), "LUNCH IN CLAYTON?", "BRING THE EXPENSE ACCOUNT."),
    (("west",), "MAPLEWOOD'S GOT GOOD FOOD NOW.", "SINCE WHEN?",
     "SINCE A WHILE."),
    (("west",), "RICHMOND HEIGHTS OR BRENTWOOD?", "YOU CROSSED FOUR CITIES.",
     "IN A MILE."),
    (("west",), "WHOSE POLICE ARE THOSE?",
     "DEPENDS ON THE SIDE OF THE STREET."),
    (("west",), "BIG BEND MEETS EVERYTHING.", "AND AGREES WITH NOTHING."),

    # -------------------------------------------------------------------- cwe
    (("cwe",), "COFFEE ON EUCLID?", "ONLY IF YOU FIND PARKING."),
    (("cwe",), "THE BASILICA'S MOSAICS.", "FORTY-ONE MILLION PIECES.",
     "I COUNTED TWO."),
    (("cwe",), "LEFT BANK STILL THERE?", "SOME THINGS HOLD."),
    (("cwe",), "THE CHASE.", "MY PARENTS DANCED THERE.",
     "EVERYONE'S PARENTS DID."),
    (("cwe",), "STRAUB'S PRICES?", "YOU'RE PAYING FOR THE BAG."),
    (("cwe",), "T.S. ELIOT GREW UP HERE.", "AND LEFT.", "AND SAID SO."),
    (("cwe",), "GASLIGHT SQUARE'S GONE.", "MY UNCLE WON'T ACCEPT IT."),
    (("cwe",), "THAT'S A PRIVATE STREET.", "WITH GATES.", "AND OPINIONS."),
    (("cwe",), "HOSPITAL PARKING?", "TAKE THE METROLINK.",
     "THAT'S ACTUALLY RIGHT."),
    (("cwe",), "MANSARD ROOF.", "EVERY ONE OF THEM.",
     "LIMESTONE UNDERNEATH."),

    # ------------------------------------------------------------- forestpark
    (("forestpark",), "BIGGER THAN CENTRAL PARK.", "SAY IT LOUDER.",
     "BIGGER THAN CENTRAL PARK."),
    (("forestpark",), "THE ZOO'S FREE.", "THE ART MUSEUM'S FREE.",
     "THE TAX PAYS FOR IT."),
    (("forestpark",), "SLEDDING ART HILL?", "IF IT SNOWS.", "IT'LL SNOW."),
    (("forestpark",), "THE FAIR WAS RIGHT HERE.", "NINETEEN OH FOUR.",
     "THEY LEFT US THE BASIN."),
    (("forestpark",), "WHO'S THE STATUE?", "SAINT LOUIS HIMSELF.",
     "ON A HORSE."),
    (("forestpark",), "MUNY TONIGHT?", "FREE SEATS AT THE BACK.",
     "GET THERE AT SIX."),
    (("forestpark",), "THE JEWEL BOX IS GLASS.", "ALL OF IT.",
     "SINCE THIRTY-SIX."),
    (("forestpark",), "BOATHOUSE OR PICNIC?", "BOTH. IN THAT ORDER."),
    (("forestpark",), "DON'T DRIVE ACROSS THE BASIN.", "IT'S WATER.",
     "PEOPLE TRY."),
    (("forestpark",), "GOLF, TENNIS, A ZOO, A THEATER.", "IN ONE PARK.",
     "AND A PLANETARIUM."),

    # ------------------------------------------------------------------ grand
    (("grand",), "GRAND IS CLOSED.", "WHICH BLOCK? YES."),
    (("grand",), "THE FOX IS BYZANTINE.", "AND SIAMESE.",
     "AT THE SAME TIME."),
    (("grand",), "POWELL OR THE SHELDON?", "DEPENDS WHO'S PLAYING."),
    (("grand",), "SLU'S RIGHT THERE.", "WHAT IS A BILLIKEN?", "STOP ASKING."),
    (("grand",), "THIS WAS ALL THEATERS.", "IT'S THEATERS AGAIN.",
     "TOOK A WHILE."),
    (("grand",), "JAZZ ST. LOUIS TONIGHT.", "MILES CAME FROM ACROSS THE RIVER.",
     "EAST SIDE."),
    (("grand",), "SCOTT JOPLIN LIVED NEAR HERE.", "THE HOUSE IS STILL UP."),
    (("grand",), "PARKING FOR THE FOX?", "PAY THE MAN WITH THE FLAG.",
     "ALWAYS PAY HIM."),
    (("grand",), "GRAND VIADUCT AGAIN?", "THEY REBUILT IT ONCE.",
     "THEY'LL DO IT AGAIN."),
    (("grand",), "INTERMISSION LINE?", "AROUND THE LOBBY.", "TWICE."),

    # ------------------------------------------------------------------ grove
    (("grove",), "MANCHESTER IS MOVING.", "NOT THIS LIGHT, IT ISN'T."),
    (("grove",), "THIS WAS ALL WAREHOUSES.", "NOW IT'S ALL PATIOS."),
    (("grove",), "THE SIGN OVER THE STREET.",
     "THAT'S HOW YOU KNOW YOU'RE IN IT."),
    (("grove",), "URBAN CHESTNUT?", "THE BIERGARTEN'S ROUND BACK."),
    (("grove",), "PRIDE ON MANCHESTER.", "THE WHOLE STREET.", "ALL DAY."),
    (("grove",), "FOREST PARK SOUTHEAST.", "NOBODY SAYS THAT.",
     "THE MAP DOES."),
    (("grove",), "PARKING BEHIND THE BAR?", "THAT'S SOMEBODY'S ALLEY."),
    (("grove",), "THE HOSPITAL'S EATING THE BLOCK.", "SLOWLY.", "STEADILY."),
    (("grove",), "TAQUERIA AFTER MIDNIGHT?", "THAT'S THE WHOLE PLAN."),
    (("grove",), "THAT USED TO BE A TIRE SHOP.",
     "EVERYTHING USED TO BE A TIRE SHOP."),

    # ------------------------------------------------------------------- shaw
    (("shaw",), "SHAW'S GARDEN.", "IT'S THE BOTANICAL GARDEN.",
     "IT'S SHAW'S GARDEN."),
    (("shaw",), "THE CLIMATRON'S A FULLER DOME.",
     "FIRST ONE MADE A GREENHOUSE.", "NINETEEN SIXTY."),
    (("shaw",), "SEIWA-EN IS THE BIGGEST.", "IN NORTH AMERICA.",
     "AND IT'S RIGHT THERE."),
    (("shaw",), "THE LINNEAN HOUSE.", "OLDEST GREENHOUSE OUT HERE.",
     "STILL RUNNING."),
    (("shaw",), "HENRY SHAW'S BURIED IN IT.", "IN THE GARDEN?",
     "IN THE GARDEN."),
    (("shaw",), "ORCHID SHOW LINE?", "OUT TO THE GATE."),
    (("shaw",), "THE BLOCK'S ALL BRICK.", "AND ALL THE SAME YEAR.",
     "ONE BUILDER."),
    (("shaw",), "TOWER GROVE AVENUE.", "THE PARK'S THAT WAY.",
     "THE GARDEN'S THIS WAY."),
    (("shaw",), "KINGSHIGHWAY TO VANDEVENTER.", "THAT'S THE WHOLE THING.",
     "IT'S ENOUGH."),
    (("shaw",), "SMELL THAT?", "THAT'S THE GARDEN.",
     "IN APRIL IT'S UNFAIR."),

    # --------------------------------------------------------------- downtown
    (("downtown",), "PARK ON TUCKER?", "NOT WITH THAT SIGN.", "WHICH SIGN?"),
    (("downtown",), "WASHINGTON AVENUE LOFTS.", "USED TO BE SHOE FACTORIES.",
     "ALL OF THEM."),
    (("downtown",), "THE WAINWRIGHT'S THE FIRST.", "ONE OF THEM.",
     "SULLIVAN BUILT IT."),
    (("downtown",), "DRED SCOTT WAS TRIED HERE.", "IN THAT COURTHOUSE.",
     "TWICE."),
    (("downtown",), "THE WHISPERING ARCH.", "STAND AT THE OTHER END.",
     "I'LL SAY SOMETHING RUDE."),
    (("downtown",), "SCHOOL BUS ON THE ROOF.", "CITY MUSEUM.",
     "OF COURSE IT IS."),
    (("downtown",), "GAME LETTING OUT?", "FORTY THOUSAND ON ONE STREET."),
    (("downtown",), "SLINGER AFTER THE GAME?", "THAT'S THE TRADITION."),
    (("downtown",), "THE OLD POST OFFICE.", "THEY ALMOST LOST IT.", "TWICE."),
    (("downtown",), "WHICH NUMBERED STREET?", "BROADWAY IS FIFTH.",
     "THAT HELPS NOBODY."),

    # ------------------------------------------------------------- riverfront
    (("riverfront",), "COBBLESTONES.", "IN HEELS?", "IN ANY SHOES."),
    (("riverfront",), "THE EADS WAS THE FIRST.", "STEEL ARCH OVER THIS RIVER.",
     "EIGHTEEN SEVENTY-FOUR."),
    (("riverfront",), "THE ARCH IS SIX-THIRTY.", "FEET?",
     "FEET. AND JUST AS WIDE."),
    (("riverfront",), "THE TRAM PODS ARE TINY.", "FIVE PEOPLE.",
     "KNEES TOUCHING."),
    (("riverfront",), "YOU CAN WALK UNDER IT.", "PEOPLE FORGET THAT.",
     "STRAIGHT UNDER."),
    (("riverfront",), "SAARINEN WON THE COMPETITION.",
     "HIS FATHER GOT THE TELEGRAM.", "BY MISTAKE."),
    (("riverfront",), "THE LANDING'S QUIET NOW.", "IT HAD ITS DECADE."),
    (("riverfront",), "RIVER'S UP.", "IT'S ALWAYS EITHER UP OR DOWN."),
    (("riverfront",), "THAT BARGE IS A QUARTER MILE.",
     "THEY TIE FIFTEEN TOGETHER.", "AND STEER IT."),
    (("riverfront",), "SUNRISE THROUGH THE LEGS.", "WORTH THE ALARM.",
     "ONCE."),

    # ---------------------------------------------------------------- soulard
    (("soulard",), "SOULARD PARKING?", "THAT'S A GOOD ONE."),
    (("soulard",), "MARKET'S OPEN SINCE SEVENTEEN SEVENTY-NINE.",
     "BEFORE THE COUNTRY.", "BY A LITTLE."),
    (("soulard",), "MARDI GRAS?", "PARK IN BENTON PARK.",
     "AND WALK. AND WALK."),
    (("soulard",), "MCGURK'S GARDEN'S FULL.", "IT'S ALWAYS FULL.",
     "IT'S WORTH IT."),
    (("soulard",), "GUS'S PRETZELS ON ARSENAL.", "GET THE BRATWURST ONE.",
     "GET TWO."),
    (("soulard",), "THESE ARE ALL FRENCH LOTS.", "LONG AND THIN.",
     "THAT'S WHY THE ALLEYS."),
    (("soulard",), "BEADS IN THE TREES.", "SINCE FEBRUARY.",
     "SINCE SOME FEBRUARY."),
    (("soulard",), "THAT'S A BALCONY, NOT A PORCH.", "IT'S IRON.",
     "IT'S ORIGINAL."),
    (("soulard",), "SMELL THE BREWERY?", "THAT'S THE HOPS.",
     "SOME DAYS IT'S THE MASH."),
    (("soulard",), "ANOTHER CORNER BAR?", "THERE'S ONE ON EVERY CORNER.",
     "THAT'S THE DESIGN."),

    # ------------------------------------------------------------- bentonpark
    (("bentonpark",), "THE BREWERY TOUR'S FREE.", "AND THEY POUR AT THE END.",
     "TWO."),
    (("bentonpark",), "CLYDESDALES COMING THROUGH.", "EIGHT OF THEM.",
     "STAND BACK."),
    (("bentonpark",), "THE LEMP MANSION.", "HAUNTED?", "ASK THE STAFF."),
    (("bentonpark",), "THE LEMP CAVES ARE UNDER US.", "ACTUALLY UNDER US?",
     "RIGHT NOW."),
    (("bentonpark",), "THE BREW HOUSE IS A LANDMARK.", "A NATIONAL ONE.",
     "LOOK AT THE IRONWORK."),
    (("bentonpark",), "BEECHWOOD AGED.", "THAT'S REAL.",
     "THEY REALLY DO THAT."),
    (("bentonpark",), "VENICE CAFE.", "THE WHOLE BUILDING'S MOSAIC.",
     "INSIDE AND OUT."),
    (("bentonpark",), "PICK YOUR ALLEY.", "THEY ALL COME OUT SOMEWHERE.",
     "EVENTUALLY."),
    (("bentonpark",), "THAT'S A CARRIAGE HOUSE.", "SOMEBODY LIVES IN IT.",
     "SOMEBODY ALWAYS DOES."),
    (("bentonpark",), "SMELLS LIKE BREAD.", "IT'S BEER.",
     "IT'S BREAD THAT GAVE UP."),

    # -------------------------------------------------------------- lafayette
    (("lafayette",), "OLDEST PARK WEST OF THE RIVER.", "SAYS WHO?",
     "SAYS THE PARK."),
    (("lafayette",), "THE TORNADO TOOK THIS BLOCK.", "EIGHTEEN NINETY-SIX.",
     "THEY BUILT IT BACK."),
    (("lafayette",), "PAINTED LADIES.", "EVERY COLOUR ON THE SQUARE.",
     "AND A COMMITTEE."),
    (("lafayette",), "THAT IRON FENCE IS ORIGINAL.", "MOST OF IT.",
     "THE REST IS PATIENT."),
    (("lafayette",), "THIS WAS ALL BOARDED UP.", "IN THE SEVENTIES.",
     "PEOPLE FORGET."),
    (("lafayette",), "PARK'S FULL OF DOGS.", "THAT IS THE PARK'S JOB."),
    (("lafayette",), "MANSARD AND A TURRET.", "ON A ROWHOUSE.",
     "THEY HAD MONEY."),
    (("lafayette",), "WALK TO DOWNTOWN?", "TEN MINUTES.",
     "IF THE TRAIN'S NOT THROUGH."),
    (("lafayette",), "THE GAZEBO'S BOOKED.", "IT'S ALWAYS BOOKED.",
     "SOMEBODY'S ALWAYS MARRYING."),
    (("lafayette",), "SQUARE OR PARK?", "THE PARK'S IN THE SQUARE.",
     "NOW YOU'VE GOT IT."),

    # ------------------------------------------------------------- comptonhts
    (("comptonhts",), "THREE WATER TOWERS LEFT.", "IN THE WHOLE COUNTRY?",
     "SEVEN. WE HAVE THREE."),
    (("comptonhts",), "THAT ONE'S THE PRETTY ONE.", "COMPTON HILL.",
     "YOU CAN CLIMB IT SOMETIMES."),
    (("comptonhts",), "TWO HUNDRED SIX STEPS.", "TO THE TOP.",
     "I COUNTED ONCE."),
    (("comptonhts",), "PRIVATE PLACE.", "GATES AND ALL.", "DON'T DRIVE IN."),
    (("comptonhts",), "THESE STREETS HAVE RULES.", "WRITTEN DOWN?",
     "WRITTEN DOWN."),
    (("comptonhts",), "IT NEVER HELD WATER.", "IT'S A WATER TOWER.",
     "IT HELD THE PRESSURE."),
    (("comptonhts",), "THE RESERVOIR'S BEHIND IT.", "STILL WORKING.",
     "STILL FENCED."),
    (("comptonhts",), "TOWER GROVE OR COMPTON HILL?", "DIFFERENT TOWERS.",
     "DIFFERENT NEIGHBOURHOODS."),
    (("comptonhts",), "THAT'S LIMESTONE, NOT PAINT.", "ALL OF IT.",
     "THEY DON'T BUILD THAT."),
    (("comptonhts",), "WHO LIVED HERE?", "BREWERS.",
     "ALL OF THEM. BREWERS."),

    # ------------------------------------------------------------------- hill
    (("hill",), "THE HILL SHORTCUT?", "FOLLOW THE HYDRANTS."),
    (("hill",), "GREEN, WHITE AND RED.", "EVERY HYDRANT.",
     "THAT'S THE BORDER."),
    (("hill",), "BERRA AND GARAGIOLA.", "SAME STREET.",
     "ACROSS FROM EACH OTHER."),
    (("hill",), "ELIZABETH AVENUE.", "THAT'S THE ONE.",
     "THERE'S A SIGN NOW."),
    (("hill",), "GIOIA'S HOT SALAMI.", "GET IT ON A SANDWICH.",
     "GET IT ON ANYTHING."),
    (("hill",), "VOLPI'S BEEN HERE A CENTURY.", "AND THEN SOME.",
     "SINCE NINETEEN OH TWO."),
    (("hill",), "BOCCE TONIGHT?", "IF IT'S DRY.",
     "IT'S ALWAYS DRY ENOUGH."),
    (("hill",), "THE HOUSES ARE FOUR ROOMS.", "AND SPOTLESS.",
     "AND FULL OF PEOPLE."),
    (("hill",), "MISSOURI BAKING OR THE OTHER?", "MISSOURI BAKING.",
     "OBVIOUSLY."),
    (("hill",), "SUNDAY GRAVY?", "STARTED IT AT SEVEN.", "IN THE MORNING."),

    # ---------------------------------------------------------------- dogtown
    (("dogtown",), "THE REAL PARADE'S HERE.", "DOWNTOWN'S IS BIGGER.",
     "OURS IS REAL."),
    (("dogtown",), "SEVENTEENTH OF MARCH.", "WHATEVER DAY IT LANDS ON.",
     "WE DON'T MOVE IT."),
    (("dogtown",), "WHY DOGTOWN?", "NOBODY AGREES.",
     "THAT'S THE BEST PART."),
    (("dogtown",), "CLAYTON-TAMM.", "THAT'S THE MAP NAME.", "IT'S DOGTOWN."),
    (("dogtown",), "MINERS BUILT THESE.", "CLAY MINERS.",
     "RIGHT UNDER THE PARK."),
    (("dogtown",), "PARK'S RIGHT THERE.", "WALK TO THE ZOO.", "PEOPLE DO."),
    (("dogtown",), "TAMM AVENUE ON A SATURDAY.", "EVERY PUB.", "EVERY ONE."),
    (("dogtown",), "THAT'S A SHOTGUN HOUSE.", "AND THE ONE BEHIND IT.",
     "AND THE ONE BEHIND THAT."),
    (("dogtown",), "SEE THE FLAGS?", "IRISH TRICOLOUR.", "ALL YEAR."),
    (("dogtown",), "PARKING ON PARADE DAY?", "NO.", "JUST NO."),

    # ------------------------------------------------------------- towergrove
    (("towergrove",), "TWO HUNDRED EIGHTY-NINE ACRES.",
     "SHAW GAVE IT TO THE CITY.", "AND KEPT PAYING FOR IT."),
    (("towergrove",), "THE RUINS AREN'T RUINS.", "THEY BUILT THEM LIKE THAT.",
     "OUT OF A BURNT HOTEL."),
    (("towergrove",), "TWELVE PAVILIONS.", "COUNT THEM SOMETIME.", "TWELVE."),
    (("towergrove",), "FARMERS MARKET SATURDAY?", "GET THERE EARLY.",
     "EARLIER THAN THAT."),
    (("towergrove",), "MOKABE'S IS STILL OPEN.", "IT'S ALWAYS BEEN OPEN.",
     "THAT'S THE POINT."),
    (("towergrove",), "THE PALM HOUSE.", "THAT'S THE PIPER.",
     "IT'S THE OLDEST ONE."),
    (("towergrove",), "SOUTH GRAND'S FOUR BLOCKS.", "AND SEVEN COUNTRIES.",
     "AT LEAST."),
    (("towergrove",), "PARK OR PARK?", "THE PARK, OR THE NEIGHBOURHOOD?",
     "SEE, THAT'S THE PROBLEM."),
    (("towergrove",), "THE CENTRAL ALLEE.", "STRAIGHT AS A RULER.",
     "A MILE OF IT."),
    (("towergrove",), "IT'S GARDENESQUE.", "THAT'S A REAL WORD.",
     "IT IS HERE."),

    # --------------------------------------------------------------- cherokee
    (("cherokee",), "ANTIQUES OR TACOS?", "THAT IS NOT A REAL CHOICE."),
    (("cherokee",), "EAST END'S ANTIQUES.", "WEST END'S MERCADOS.",
     "WALK THE WHOLE THING."),
    (("cherokee",), "CINCO DE MAYO ON CHEROKEE.", "THE STREET CLOSES.",
     "ALL OF IT."),
    (("cherokee",), "PANADERIA'S OPEN?", "SIX IN THE MORNING.",
     "GET THE CONCHA."),
    (("cherokee",), "MEET AT THE BIG STATUE.", "IT'S BEEN THERE FOREVER.",
     "EVERYBODY MEETS THERE."),
    (("cherokee",), "PRINT SHOP IN THE BACK.", "LETTERPRESS.",
     "STILL RUNNING."),
    (("cherokee",), "THERE'S A CAVE UNDER HERE.", "CHEROKEE CAVE.",
     "THEY SEALED IT."),
    (("cherokee",), "RECORD STORE'S MOVED.", "TWO DOORS DOWN.",
     "SAME BINS."),
    (("cherokee",), "HOW DO YOU SAY IT?", "SAY IT LIKE YOU LIVE HERE.",
     "CHER-O-KEE."),
    (("cherokee",), "EVERYTHING'S CASH.", "MOST THINGS.", "BRING CASH."),

    # --------------------------------------------------------------- Lambert
    (("lambert",), "WHICH TERMINAL?", "THE ONE WITH THE ARCHES.",
     "THAT'S STILL TWO OF THEM."),
    (("lambert",), "YAMASAKI DREW THAT ROOF.", "BEFORE THE TOWERS.",
     "LONG BEFORE."),
    (("lambert",), "TWA USED TO OWN THIS PLACE.", "FELT LIKE IT.",
     "RED ON EVERYTHING."),
    (("lambert",), "METROLINK'S DOWNSTAIRS.", "RED LINE?", "ONLY LINE HERE."),
    (("lambert",), "NORTH HANLEY NEXT.", "THEN UMSL.", "THEN THE CITY."),
    (("lambert",), "MCDONNELL BUILT JETS HERE.", "AND SPACECRAFT.",
     "MERCURY AND GEMINI."),
    (("lambert",), "YOU PARKED WHERE?", "ECONOMY LOT D.",
     "WRITE THAT DOWN."),
    (("lambert",), "THE RUNWAY CROSSES NATURAL BRIDGE.", "UNDER IT.",
     "KEEP YOUR HEAD DOWN."),
    (("lambert",), "IS THAT YOUR BAG?", "SAME COLOR.", "NOT MY BAG."),
    (("lambert",), "FLIGHT'S DELAYED.", "WEATHER HERE OR THERE?",
     "YES."),

    # ------------------------------------------------------ Wells-Goodfellow
    (("wellsgoodfellow",), "WELLS OR GOODFELLOW?", "BOTH. THAT'S THE NAME.",
     "DON'T DROP THE S."),
    (("wellsgoodfellow",), "CITY LINE'S RIGHT THERE.", "WELLSTON'S PAST IT.",
     "DIFFERENT PLACE."),
    (("wellsgoodfellow",), "NATURAL BRIDGE IS SOUTH.", "THE ROAD OR THE PLACE?",
     "THE ROAD THIS TIME."),
    (("wellsgoodfellow",), "THE 94 STILL COMES?", "EVENTUALLY.", "BRING A COAT."),
    (("wellsgoodfellow",), "THAT BRICK WAS RED ONCE.", "STILL IS UNDERNEATH.",
     "MOST THINGS ARE."),
    (("wellsgoodfellow",), "GOODFELLOW RUNS NORTH.", "UNTIL IT DOESN'T.",
     "THAT'S DIRECTIONS."),
    (("wellsgoodfellow",), "CORNER STORE'S OPEN.", "LIGHT'S ON.",
     "THAT MEANS OPEN."),
    (("wellsgoodfellow",), "THE ALLEY CUTS THROUGH.", "IF THE TRUCK'S NOT THERE.",
     "IT'S TRASH DAY."),
    (("wellsgoodfellow",), "THAT'S THE CITY LIMIT.", "NO SIGN?", "YOU CAN TELL."),
    (("wellsgoodfellow",), "WE'RE NOT WELLSTON.", "TELL THE MAP.", "WE JUST DID."),

    # ------------------------------------------------------------- fairground
    (("fairground",), "FAIRGROUND PARK'S OPEN.", "LAKE SIDE OR BALL FIELD?",
     "MAKE A WHOLE LOOP."),
    (("fairground",), "THE FAIR USED TO BE HERE.", "THAT'S WHY THE NAME.",
     "BIGGER THAN YOU THINK."),
    (("fairground",), "BEAR PITS ARE OVER THERE.", "NO BEARS NOW.",
     "JUST THE STONE."),
    (("fairground",), "MAY DAY PARADE'S COMING.", "BANDS FIRST.", "FLOATS AFTER."),
    (("fairground",), "THE POOL STORY?", "THAT'S A LONG STORY.", "LEARN IT ANYWAY."),
    (("fairground",), "O'FALLON'S NEXT BLOCK.", "PARK OR NEIGHBORHOOD?",
     "BOTH AGAIN."),
    (("fairground",), "SUMNER'S SOUTH OF HERE.", "CHUCK BERRY'S SCHOOL.",
     "AND TINA TURNER'S."),
    (("fairground",), "SUNDAY GAME AT TWO.", "WHICH FIELD?", "FOLLOW THE COOLER."),
    (("fairground",), "THAT LAKE FREEZES?", "NOT ENOUGH.", "SOMEBODY STILL TRIES."),
    (("fairground",), "ONE HUNDRED THIRTY-ONE ACRES.", "YOU COUNTED?",
     "THE CITY DID."),

    # ------------------------------------------------------------ collegehill
    (("collegehill",), "SEE THE RED TOWER?", "BISSELL.", "TWO HUNDRED SIX FEET."),
    (("collegehill",), "THE OTHER TOWER'S WHITE.", "GRAND AVENUE.",
     "WE KEEP BOTH STRAIGHT."),
    (("collegehill",), "THAT LOOKS LIKE A MINARET.", "MOORISH REVIVAL.",
     "IN NORTH CITY."),
    (("collegehill",), "HYDE PARK'S SOUTH.", "OLD NORTH AFTER THAT.",
     "KEEP GOING."),
    (("collegehill",), "CROWN CANDY?", "DOWN FOURTEENTH.", "BRING CASH."),
    (("collegehill",), "THE RIVER'S CLOSE.", "CAN'T SEE IT FROM HERE.",
     "THE LEVEE'S IN THE WAY."),
    (("collegehill",), "THOSE STANDPIPES WORKED.", "PRESSURE FOR THE WHOLE CITY.",
     "BEFORE PUMPS CAUGHT UP."),
    (("collegehill",), "COLLEGE HILL HAD A COLLEGE?", "ONCE.",
     "THE NAME STAYED."),
    (("collegehill",), "NORTH BROADWAY'S EAST.", "TRUCKS ALL NIGHT.",
     "SAME AS ALWAYS."),
    (("collegehill",), "THE TOWER LIGHTS UP.", "WHEN?", "WHEN SOMEBODY PAYS."),

    # ------------------------------------------------------------------ ville
    (("ville",), "SUMNER WAS THE FIRST.", "FIRST OUT HERE, ANYWAY.",
     "EIGHTEEN SEVENTY-FIVE."),
    (("ville",), "CHUCK BERRY WENT THERE.", "AND TINA.", "AND ARTHUR ASHE."),
    (("ville",), "DICK GREGORY TOO.", "SAME HALLS.", "ALL OF THEM."),
    (("ville",), "ANNIE MALONE MADE MILLIONS.", "AND GAVE IT BACK.",
     "TO THIS BLOCK."),
    (("ville",), "THE MAY DAY PARADE.", "STILL RUNS.", "OVER A CENTURY."),
    (("ville",), "HOMER G. PHILLIPS.", "THEY TRAINED DOCTORS HERE.",
     "WHEN NOWHERE ELSE WOULD."),
    (("ville",), "THIS WAS THE PLACE TO BE.", "IT HAD TO BE.",
     "SO WE MADE IT THE PLACE."),
    (("ville",), "FAIRGROUND PARK'S THAT WAY.", "THE POOL.",
     "THAT'S A LONGER STORY."),
    (("ville",), "SOUL FOOD ON THE CORNER?", "SINCE BEFORE YOU.",
     "SINCE BEFORE ME."),
    (("ville",), "THEY CALL IT THE VILLE.", "JUST THE VILLE.",
     "EVERYBODY KNOWS."),

    # --------------------------------------------------------------- oldnorth
    (("oldnorth",), "CROWN CANDY LINE?", "WORTH IT. BRING CASH."),
    (("oldnorth",), "SINCE NINETEEN THIRTEEN.", "SAME FAMILY.",
     "SAME BOOTHS."),
    (("oldnorth",), "FIVE MALTS IN THIRTY MINUTES.", "AND THEY'RE FREE.",
     "NOBODY WINS."),
    (("oldnorth",), "GET THE BLT.", "HOW MUCH BACON?", "YOU'LL SEE."),
    (("oldnorth",), "OLD NORTH OR HYDE PARK?", "DEPENDS WHO'S ASKING."),
    (("oldnorth",), "FOURTEENTH STREET MALL.", "THEY CLOSED IT TO CARS.",
     "THEN OPENED IT BACK."),
    (("oldnorth",), "THAT'S A GERMAN CHURCH.", "HYDE PARK'S FULL OF THEM.",
     "SPIRES EVERYWHERE."),
    (("oldnorth",), "BRICK BY BRICK.", "THAT'S HOW THEY'RE DOING IT.",
     "HOUSE BY HOUSE."),
    (("oldnorth",), "SOME OF THE OLDEST BLOCKS.", "IN THE WHOLE CITY.",
     "EIGHTEEN FORTIES."),
    (("oldnorth",), "CUT THROUGH FAIRGROUND PARK?", "NOT DURING THE PARADE."),

    # ------------------------------------------------------------ southampton
    (("southampton",), "TED DREWES ON CHIPPEWA.", "THE LINE'S IN THE STREET.",
     "IT'S SUPPOSED TO BE."),
    (("southampton",), "CONCRETE, NOT A SHAKE.", "THEY TURN IT OVER.",
     "IF IT FALLS OUT IT'S FREE."),
    (("southampton",), "THEY SELL CHRISTMAS TREES.", "SAME LOT.",
     "SAME FAMILY."),
    (("southampton",), "ROUTE SIXTY-SIX RAN HERE.", "RIGHT DOWN CHIPPEWA.",
     "THAT'S WHY THE STAND'S THERE."),
    (("southampton",), "BUNGALOW OR TWO-FAMILY?", "COUNT THE FRONT DOORS."),
    (("southampton",), "THE ALLEY'S STILL OPEN.", "LEAGUE NIGHT'S TUESDAY.",
     "DON'T COME TUESDAY."),
    (("southampton",), "GRAVOIS CUTS RIGHT THROUGH.", "IT DOES THAT EVERYWHERE.",
     "IT'S ITS WHOLE PERSONALITY."),
    (("southampton",), "SOUTHTOWN FAMOUS-BARR.", "IT'S A HARDWARE STORE NOW.",
     "I KNOW WHAT IT IS."),
    (("southampton",), "EVERY YARD'S GOT A STATUE.", "MARY IN A BATHTUB.",
     "THAT'S THE STYLE."),
    (("southampton",), "PRINCETON HEIGHTS?", "SOUTHAMPTON.",
     "SAME FOUR BLOCKS, DIFFERENT ARGUMENT."),

    # ------------------------------------------------------------------- bevo
    (("bevo",), "MEET ME BY THE WINDMILL.", "WHICH WINDMILL?",
     "THERE IS ONE WINDMILL."),
    (("bevo",), "BUSCH BUILT IT.", "AS A ROADHOUSE.",
     "HALFWAY TO HIS FARM."),
    (("bevo",), "GRBIC OR THE OTHER ONE?", "GRBIC.", "GET THE BUREK."),
    (("bevo",), "CEVAPI WITH THE FLATBREAD.", "AND THE ONIONS.",
     "ALL OF THE ONIONS."),
    (("bevo",), "LITTLE BOSNIA.", "BIGGEST OUTSIDE BOSNIA.", "RIGHT HERE."),
    (("bevo",), "THEY CAME IN THE NINETIES.", "AND BOUGHT THE BLOCK.",
     "AND FIXED THE BLOCK."),
    (("bevo",), "GRAVOIS AND MORGANFORD.", "THAT'S THE CORNER.",
     "THAT'S WHY THE MILL'S THERE."),
    (("bevo",), "COFFEE'S DIFFERENT HERE.", "IT COMES IN A LITTLE POT.",
     "DRINK IT SLOW."),
    (("bevo",), "DUTCHTOWN'S NEXT OVER.", "IT'S ALL DUTCHTOWN TO ME.",
     "DON'T SAY THAT HERE."),
    (("bevo",), "THE MILL'S BEEN CLOSED.", "AND OPEN.",
     "AND CLOSED. IT'LL BE BACK."),

    # ---------------------------------------------------------------- sthills
    (("sthills",), "FRANCIS PARK IN OCTOBER.", "THE WHOLE LOOP.",
     "EVERYBODY WALKS IT."),
    (("sthills",), "THE OTHER TED DREWES.", "THERE ARE TWO.",
     "PEOPLE WILL CORRECT YOU."),
    (("sthills",), "WHICH PARISH?", "THAT'S HOW WE GIVE DIRECTIONS.",
     "STILL."),
    (("sthills",), "THESE ARE ALL LIMESTONE.", "AND ART DECO.",
     "ONE DEVELOPER, ONE DECADE."),
    (("sthills",), "HAMPTON TO KINGSHIGHWAY.", "THAT'S THE HILLS.",
     "ROUGHLY."),
    (("sthills",), "THE LEAVES IN THE PARK.", "PEOPLE DRIVE OVER FOR IT.",
     "FROM THE COUNTY."),
    (("sthills",), "EVERY HOUSE HAS A CHIMNEY.", "AND NONE OF THEM WORK.",
     "THEY'RE FOR LOOKS."),
    (("sthills",), "IT'S THE CITY.", "IT DOESN'T FEEL LIKE THE CITY.",
     "IT'S STILL THE CITY."),
    (("sthills",), "BOWLING OR THE PARISH HALL?", "SAME PEOPLE.",
     "SAME NIGHT."),
    (("sthills",), "CHIPPEWA OR WATSON?", "WATSON'S FASTER.",
     "CHIPPEWA'S PRETTIER."),

    # ------------------------------------------------------------- carondelet
    (("carondelet",), "VIDE POCHE.", "EMPTY POCKET.",
     "THE FRENCH NAMED US THAT."),
    (("carondelet",), "IT WAS ITS OWN TOWN.", "UNTIL EIGHTEEN SEVENTY.",
     "THEN THE CITY TOOK IT."),
    (("carondelet",), "BLUES CITY DELI.", "THE LINE'S OUT THE DOOR.",
     "THERE'S A BAND AT LUNCH."),
    (("carondelet",), "THE IVORY TRIANGLE.", "THAT'S THE NAME.",
     "IT'S ACTUALLY A TRIANGLE."),
    (("carondelet",), "THE MILL'S DOWN THERE.", "STILL RUNNING.",
     "STILL LOUD."),
    (("carondelet",), "SUSAN BLOW STARTED IT HERE.", "THE FIRST KINDERGARTEN.",
     "IN THE COUNTRY."),
    (("carondelet",), "THE RIVER'S RIGHT THERE.", "YOU CAN'T GET TO IT.",
     "THAT'S THE PROBLEM."),
    (("carondelet",), "HOLLY HILLS BOULEVARD.", "THAT'S A NICE DRIVE.",
     "TAKE IT SLOW."),
    (("carondelet",), "SOUTH BROADWAY GOES ON.", "ALL THE WAY DOWN.",
     "PAST EVERYTHING."),
    (("carondelet",), "FURTHEST SOUTH IN THE CITY.", "AND THE OLDEST.",
     "BOTH."),
)

# One-liners from a single pedestrian. Same tagging shape as the scenes above.
STL_SOLO_BARKS = (
    (None, "IT'S THE HUMIDITY."),
    (None, "PARK ANYWHERE, HE SAYS."),
    (None, "THAT'S NOT A LANE."),
    (None, "COULD USE A SLINGER."),
    (None, "SIREN TESTING AGAIN."),
    (None, "MY KNEE SAYS RAIN."),
    (None, "SIX WEEKS OF CONSTRUCTION."),
    (None, "THEY REPAVED IT WRONG."),
    (None, "I'M NOT PAYING TO PARK."),
    (None, "GO CARDS."),
    (None, "LET'S GO BLUES."),
    (None, "IT WAS BETTER BEFORE."),
    (None, "IT'S GETTING BETTER."),
    (None, "I TOOK 40. IT'S 40."),
    (None, "THIRTY MINUTES ANYWHERE."),
    (None, "THAT'S A COUNTY PLATE."),
    (None, "GRAVOIS AGAIN."),
    (None, "PUT IT ON A PORK STEAK."),
    (None, "WHERE'D YOU GO TO SCHOOL, THOUGH."),
    (None, "BREAD AND MILK. JUST IN CASE."),
    (("lambert",), "GATE CHANGED AGAIN."),
    (("lambert",), "TAKE METROLINK THIS TIME."),
    (("loop",), "MIND THE TROLLEY TRACK."),
    (("loop",), "SOMEBODY'S BUSKING AGAIN."),
    (("wellston",), "THE 94 RUNS THROUGH HERE."),
    (("wellston",), "MY GRANDMOTHER'S HOUSE WAS THERE."),
    (("wellsgoodfellow",), "CITY LINE'S ONE BLOCK WEST."),
    (("wellsgoodfellow",), "DON'T CALL THIS WELLSTON."),
    (("fairground",), "PARK LOOP'S A GOOD WALK."),
    (("fairground",), "PARADE PRACTICE AGAIN."),
    (("collegehill",), "RED TOWER'S THAT WAY."),
    (("collegehill",), "YOU CAN SEE BOTH STANDPIPES."),
    (("west",), "VALIDATE YOUR TICKET."),
    (("west",), "FOUR CITIES IN A MILE."),
    (("cwe",), "WHOLE STREET SMELLS LIKE BREAD."),
    (("cwe",), "THE GATES CLOSE AT NINE."),
    (("forestpark",), "WHERE'D THEY PUT THE ELEPHANTS?"),
    (("forestpark",), "IT'S ALL FREE, YOU KNOW."),
    (("grand",), "CURTAIN'S AT EIGHT."),
    (("grand",), "THAT ORGAN'S ORIGINAL."),
    (("grove",), "PATIO'S OPEN."),
    (("grove",), "IT WAS A MACHINE SHOP."),
    (("shaw",), "THE DOME'S THAT WAY."),
    (("shaw",), "ORCHIDS THROUGH MARCH."),
    (("downtown",), "GAME'S IN THE SEVENTH."),
    (("downtown",), "THAT'S TWELVE DOLLARS TO PARK."),
    (("riverfront",), "WATCH THE COBBLES."),
    (("riverfront",), "TRAM'S GOT AN HOUR WAIT."),
    (("soulard",), "BEADS FROM FEBRUARY."),
    (("soulard",), "MARKET CLOSES AT FIVE."),
    (("bentonpark",), "THAT'S THE MASH YOU SMELL."),
    (("bentonpark",), "HORSES COME THROUGH AT TWO."),
    (("lafayette",), "MIND THE IRONWORK."),
    (("lafayette",), "THE COMMITTEE WILL HEAR ABOUT IT."),
    (("comptonhts",), "DON'T DRIVE UP THE PRIVATE."),
    (("comptonhts",), "TOWER'S OPEN THE FULL MOON."),
    (("hill",), "LOOK AT THE HYDRANT."),
    (("hill",), "GRAVY'S ON SINCE SEVEN."),
    (("dogtown",), "PARADE'S IN MARCH."),
    (("dogtown",), "TAMM'S PACKED ALREADY."),
    (("towergrove",), "MARKET'S TILL NOON."),
    (("towergrove",), "MIND THE PAVILION, IT'S BOOKED."),
    (("cherokee",), "CASH ONLY, FRIEND."),
    (("cherokee",), "SHOP'S OPEN TILL SEVEN."),
    (("ville",), "PARADE COMES DOWN THIS WAY."),
    (("ville",), "THAT SCHOOL MADE PEOPLE."),
    (("oldnorth",), "LINE'S ALREADY ROUND THE CORNER."),
    (("oldnorth",), "BRING CASH FOR THE MALT."),
    (("southampton",), "CONCRETE'S WORTH THE WAIT."),
    (("southampton",), "SIXTY-SIX CAME THROUGH HERE."),
    (("bevo",), "MILL'S CLOSED AGAIN."),
    (("bevo",), "BUREK'S OUT OF THE OVEN."),
    (("sthills",), "WALK THE PARK LOOP."),
    (("sthills",), "WHICH PARISH ARE YOU?"),
    (("carondelet",), "MILL'S ON SECOND SHIFT."),
    (("carondelet",), "DELI'S GOT A BAND TODAY."),
)

# What somebody says when they watch you do something. Not tagged by hood:
# these are reactions, and they read as reactions anywhere.
STL_REACTION_BARKS = (
    "THAT'S NOT YOUR CAR.", "HE TOOK THE BUS!", "IN A REFUSE TRUCK?",
    "THAT'S THE SIDEWALK!", "MY LAWN!", "CALL SOMEBODY!",
    "HE'S HEADED FOR GRAVOIS.", "GOOD LUCK ON KINGSHIGHWAY.",
    "THAT'S A TRANS AM.", "KSHE'S ON IN THERE.", "SLOW DOWN, IT'S A SCHOOL DAY.",
    "THAT'S A ONE WAY!", "YOU'RE ON THE TRACKS!", "THE GATE'S DOWN!",
    "PARK IT ANYWHERE, WHY DON'T YOU.", "COUNTY PLATES. FIGURES.",
    "I'M CALLING THE ALDERMAN.", "MY COUSIN DRIVES ONE OF THOSE.",
    "THAT'LL BUFF OUT.", "TELL ME THAT'S INSURED.",
    "WHERE'D YOU LEARN THAT, THE COUNTY?", "HE'S GOING THE WRONG WAY UP TUCKER.",
    "NOT THROUGH THE MARKET!", "THAT'S A HISTORIC WALL!",
    "SOMEBODY GET A PLATE NUMBER.", "HE HIT THE CONE. THE FAMOUS ONE.",
    "THAT'S A METROBUS, MAN.", "YOU CAN'T DRIVE ON THE BASIN!",
)

# Cop radio and shouts. A few are St. Louis specific, because the jurisdiction
# question is a genuine feature of being chased around here.
STL_COP_BARKS = (
    "PULL IT OVER.", "CITY UNIT, EASTBOUND.", "SUSPECT ON GRAVOIS.",
    "HE'S HEADED FOR THE COUNTY LINE.", "THAT'S NOT OUR JURISDICTION.",
    "IT IS NOW.", "LOST HIM IN THE GANGWAYS.", "CHECK THE ALLEY.",
    "UNITS TO KINGSHIGHWAY.", "HE CROSSED DELMAR.", "BLOCK THE BRIDGE.",
    "HE'S IN THE PARK. AGAIN.", "STOP THE VEHICLE.", "OUT OF THE CAR.",
    "DO NOT RUN.", "HE'S RUNNING.", "SOUTHBOUND ON BROADWAY.",
    "WE HAVE HIM ON TUCKER.", "HOLD AT THE CROSSING.",
    "TRAIN'S COMING, HOLD UP.", "HE WENT DOWN CHEROKEE.",
    "GET AHEAD OF HIM AT ARSENAL.",
)

# Panic lines, per neighbourhood, with a citywide fallback. All five of these
# used to be citywide, so a chase through Soulard and a chase through the Ville
# sounded exactly the same.
STL_PANIC_LINES = (
    "I DIDN'T SEE A THING!", "THAT IS NOT A LANE!", "NOT THE PARKED CAR!",
    "WHO TAUGHT YOU TO DRIVE?", "TAKE GRAVOIS, THEY'LL NEVER FOLLOW!",
    "CALL SOMEBODY!", "GET OFF THE STREET!", "NOT AGAIN!",
)
STL_PANIC_BY_HOOD = {
    'lambert': ("NOT ON THE RUNWAY!", "THAT IS NOT A PICKUP LANE!"),
    'loop': ("NOT ON DELMAR!", "MIND THE TRACK!"),
    'wellston': ("NOT ON THIS BLOCK!", "SOMEBODY CALL IT IN!"),
    'wellsgoodfellow': ("NOT ACROSS GOODFELLOW!", "THAT'S THE CITY LINE!"),
    'fairground': ("NOT THROUGH THE PARK!", "THE BALL FIELD'S FULL!"),
    'collegehill': ("NOT BY THE RED TOWER!", "WATCH THE HILL!"),
    'west': ("THIS IS CLAYTON!", "I PAY TAXES FOR THIS!"),
    'cwe': ("NOT ON EUCLID!", "GET BEHIND THE GATES!"),
    'forestpark': ("THERE ARE CHILDREN HERE!", "NOT IN THE PARK!"),
    'grand': ("THE SHOW'S LETTING OUT!", "NOT ON GRAND!"),
    'grove': ("NOT ON MANCHESTER!", "GET IN THE BAR!"),
    'shaw': ("NOT BY THE GARDEN!", "MIND THE GLASSHOUSE!"),
    'downtown': ("NOT ON WASHINGTON!", "SOMEBODY GET SECURITY!"),
    'riverfront': ("WATCH THE COBBLES!", "NOT BY THE ARCH!"),
    'soulard': ("NOT THROUGH THE MARKET!", "MIND THE BALCONY!"),
    'bentonpark': ("NOT BY THE BREWERY!", "THE HORSES ARE OUT!"),
    'lafayette': ("NOT THE IRONWORK!", "THAT FENCE IS ORIGINAL!"),
    'comptonhts': ("THIS IS A PRIVATE PLACE!", "NOT UP THE HILL!"),
    'hill': ("NOT ON THE HILL!", "MIND THE BOCCE COURT!"),
    'dogtown': ("NOT ON TAMM!", "THE PARADE'S IN MARCH!"),
    'towergrove': ("NOT THROUGH THE MARKET!", "MIND THE PAVILION!"),
    'cherokee': ("NOT ON CHEROKEE!", "GET IN THE SHOP!"),
    'ville': ("NOT ON THIS STREET!", "THE CHILDREN ARE OUT!"),
    'oldnorth': ("NOT BY CROWN CANDY!", "THE LINE'S RIGHT THERE!"),
    'southampton': ("THERE'S A LINE OUT THERE!", "NOT ON CHIPPEWA!"),
    'bevo': ("NOT BY THE MILL!", "GET INSIDE!"),
    'sthills': ("NOT IN FRANCIS PARK!", "THIS IS A QUIET STREET!"),
    'carondelet': ("NOT DOWN BROADWAY!", "SOMEBODY STOP HIM!"),
}


def _scene_index(scenes):
    """Split a tagged table into (citywide, {hood: [...]})."""
    wide, local = [], {}
    for scene in scenes:
        hoods = scene[0]
        if hoods is None:
            wide.append(scene)
            continue
        for hood in hoods:
            local.setdefault(hood, []).append(scene)
    return tuple(wide), {k: tuple(v) for k, v in local.items()}


STL_CITYWIDE, STL_LOCAL_BY_HOOD = _scene_index(STL_CONVERSATIONS)
SOLO_CITYWIDE, SOLO_BY_HOOD = _scene_index(STL_SOLO_BARKS)


class ChatterBag:
    """Deal scenes without replacement.

    A bare random.choice over a 16-item pool repeats itself constantly, and
    the old chatter did exactly that - which is the single biggest reason the
    city sounded like it only knew fifteen things. This deals from a shuffled
    deck per key, reshuffles only when the deck is empty, and keeps a short
    global memory so crossing a neighbourhood boundary does not immediately
    replay what you just heard on the other side.
    """

    def __init__(self, recent=CHATTER_RECENT):
        self.decks = {}
        self.recent = collections.deque(maxlen=recent)

    def deal(self, key, pool, rng=random):
        pool = tuple(pool)
        if not pool:
            return None
        deck = self.decks.get(key)
        if not deck:
            deck = list(pool)
            rng.shuffle(deck)
            # Do not let a fresh shuffle open with something just heard.
            # Preferred: anything not in the recent window at all. Guaranteed:
            # never the card dealt immediately before - which matters most
            # when the deck is smaller than the window, because then every
            # card is "recent" and the soft rule has nothing to pick.
            if len(deck) > 1:
                last = self.recent[-1] if self.recent else None
                pick = next((i for i, sc in enumerate(deck)
                             if sc not in self.recent), None)
                if pick is None:
                    pick = next((i for i, sc in enumerate(deck)
                                 if sc != last), 0)
                if pick:
                    deck[0], deck[pick] = deck[pick], deck[0]
            self.decks[key] = deck
        scene = deck.pop(0)
        self.recent.append(scene)
        return scene

    def pick(self, hood, wide, by_hood, rng=random, bias=CHATTER_LOCAL_BIAS):
        """A local scene most of the time, a citywide one the rest."""
        local = by_hood.get(hood, ())
        if local and (not wide or rng.random() < bias):
            return self.deal(('local', hood), local, rng)
        return self.deal(('wide',), wide, rng)


# Character-creator list: regular campuses serving a high-school grade across
# the core St. Louis metro, with current whole-school enrollment >= 100. That
# means City/County plus St. Charles, Jefferson, Franklin and the Metro East
# counties of Madison, St. Clair and Monroe. Public entries were checked against
# MO DESE / IL ISBE; private entries against NCES PSS, ISBE and current sites.
# Virtual, admin-only, CTE-only, special/alternative and duplicate campuses are
# excluded. The tag stays compact because this still has to fit a 640px screen.
STL_HIGH_SCHOOLS = (
    # County public
    ("Affton High School", "COUNTY PUBLIC"),
    ("Bayless Senior High School", "COUNTY PUBLIC"),
    ("Brentwood High School", "COUNTY PUBLIC"),
    ("Clayton High School", "COUNTY PUBLIC"),
    ("Eureka High School", "COUNTY PUBLIC"),
    ("Hancock High School", "COUNTY PUBLIC"),
    ("Hazelwood Central High School", "COUNTY PUBLIC"),
    ("Hazelwood East High School", "COUNTY PUBLIC"),
    ("Hazelwood West High School", "COUNTY PUBLIC"),
    ("Jennings High School", "COUNTY PUBLIC"),
    ("Kirkwood High School", "COUNTY PUBLIC"),
    ("Ladue Horton Watkins High School", "COUNTY PUBLIC"),
    ("Lafayette High School", "COUNTY PUBLIC"),
    ("Lindbergh High School", "COUNTY PUBLIC"),
    ("Maplewood Richmond Heights High School", "COUNTY PUBLIC"),
    ("Marquette High School", "COUNTY PUBLIC"),
    ("McCluer High School", "COUNTY PUBLIC"),
    ("McCluer North High School", "COUNTY PUBLIC"),
    ("Mehlville High School", "COUNTY PUBLIC"),
    ("Normandy High School", "COUNTY PUBLIC"),
    ("Oakville High School", "COUNTY PUBLIC"),
    ("Parkway Central High School", "COUNTY PUBLIC"),
    ("Parkway North High School", "COUNTY PUBLIC"),
    ("Parkway South High School", "COUNTY PUBLIC"),
    ("Parkway West High School", "COUNTY PUBLIC"),
    ("Pattonville High School", "COUNTY PUBLIC"),
    ("Ritenour High School", "COUNTY PUBLIC"),
    ("Riverview Gardens High School", "COUNTY PUBLIC"),
    ("Rockwood Summit High School", "COUNTY PUBLIC"),
    ("STEAM Academy at McCluer South-Berkeley", "COUNTY PUBLIC"),
    ("The Innovation School at Cool Valley", "COUNTY PUBLIC"),
    ("University City High School", "COUNTY PUBLIC"),
    ("Valley Park High School", "COUNTY PUBLIC"),
    ("Webster Groves High School", "COUNTY PUBLIC"),
    # Technical / special district
    ("North Technical High School", "TECHNICAL"),
    ("Northview High School", "TECHNICAL"),
    ("South Technical High School", "TECHNICAL"),
    # City public
    ("Beaumont CTE High School", "CITY PUBLIC"),
    ("Carnahan School of the Future", "CITY PUBLIC"),
    ("Central Visual and Performing Arts High School", "CITY PUBLIC"),
    ("Collegiate School of Medicine and Bioscience", "CITY PUBLIC"),
    ("Gateway STEM High School", "CITY PUBLIC"),
    ("McKinley Classical Leadership Academy", "CITY PUBLIC"),
    ("Metro Academic and Classical High School", "CITY PUBLIC"),
    ("Miller Career Academy", "CITY PUBLIC"),
    ("Roosevelt High School", "CITY PUBLIC"),
    ("Soldan International Studies", "CITY PUBLIC"),
    ("Sumner High School", "CITY PUBLIC"),
    ("Vashon High School", "CITY PUBLIC"),
    # City charter
    ("BELIEVE Academy STL", "CHARTER"),
    ("Confluence Preparatory Academy", "CHARTER"),
    ("Gateway Science Academy High School", "CHARTER"),
    ("Grand Center Arts Academy High School", "CHARTER"),
    ("Kairos High School", "CHARTER"),
    ("KIPP St. Louis High School", "CHARTER"),
    ("Lift for Life Academy High School", "CHARTER"),
    # Private / parochial
    ("Al-Salam Day School", "PRIVATE"),
    ("Bishop DuBourg High School", "PRIVATE"),
    ("Cardinal Ritter College Prep", "PRIVATE"),
    ("Chaminade College Preparatory School", "PRIVATE"),
    ("Christian Academy of Greater St. Louis", "PRIVATE"),
    ("Christian Brothers College High School", "PRIVATE"),
    ("Cor Jesu Academy", "PRIVATE"),
    ("Crossroads College Preparatory School", "PRIVATE"),
    ("De Smet Jesuit", "PRIVATE"),
    ("H.F. Epstein Hebrew Academy", "PRIVATE"),
    ("Incarnate Word Academy", "PRIVATE"),
    ("John Burroughs School", "PRIVATE"),
    ("Logos School", "PRIVATE"),
    ("Lutheran High School North", "PRIVATE"),
    ("Lutheran High School South", "PRIVATE"),
    ("MICDS", "PRIVATE"),
    ("Nerinx Hall", "PRIVATE"),
    ("North County Christian School", "PRIVATE"),
    ("Notre Dame High School", "PRIVATE"),
    ("Principia School", "PRIVATE"),
    ("Providence Classical Christian Academy", "PRIVATE"),
    ("Rosati-Kain Academy", "PRIVATE"),
    ("Saint Louis Priory School", "PRIVATE"),
    ("St. John Vianney High School", "PRIVATE"),
    ("St. Joseph's Academy", "PRIVATE"),
    ("St. Louis University High School", "PRIVATE"),
    ("St. Mary's South Side Catholic High School", "PRIVATE"),
    ("The Fulton School", "PRIVATE"),
    ("Ursuline Academy", "PRIVATE"),
    ("Villa Duchesne", "PRIVATE"),
    ("Visitation Academy", "PRIVATE"),
    ("Westminster Christian Academy", "PRIVATE"),
    ("Whitfield School", "PRIVATE"),
    # St. Charles County public
    ("Emil E. Holt Sr. High School", "ST CHARLES PUBLIC"),
    ("Francis Howell Central High School", "ST CHARLES PUBLIC"),
    ("Francis Howell High School", "ST CHARLES PUBLIC"),
    ("Francis Howell North High School", "ST CHARLES PUBLIC"),
    ("Ft. Zumwalt East High School", "ST CHARLES PUBLIC"),
    ("Ft. Zumwalt North High School", "ST CHARLES PUBLIC"),
    ("Ft. Zumwalt South High School", "ST CHARLES PUBLIC"),
    ("Ft. Zumwalt West High School", "ST CHARLES PUBLIC"),
    ("Liberty High School", "ST CHARLES PUBLIC"),
    ("North Point High School", "ST CHARLES PUBLIC"),
    ("Orchard Farm High School", "ST CHARLES PUBLIC"),
    ("St. Charles High School", "ST CHARLES PUBLIC"),
    ("St. Charles West High School", "ST CHARLES PUBLIC"),
    ("Timberland High School", "ST CHARLES PUBLIC"),
    # Jefferson County public
    ("Crystal City High School", "JEFFERSON PUBLIC"),
    ("De Soto Sr. High School", "JEFFERSON PUBLIC"),
    ("Festus Sr. High School", "JEFFERSON PUBLIC"),
    ("Fox Sr. High School", "JEFFERSON PUBLIC"),
    ("Grandview High School", "JEFFERSON PUBLIC"),
    ("Herculaneum High School", "JEFFERSON PUBLIC"),
    ("Hillsboro High School", "JEFFERSON PUBLIC"),
    ("Jefferson High School", "JEFFERSON PUBLIC"),
    ("Northwest High School", "JEFFERSON PUBLIC"),
    ("Seckman Sr. High School", "JEFFERSON PUBLIC"),
    ("Windsor High School", "JEFFERSON PUBLIC"),
    # Franklin County public
    ("New Haven High School", "FRANKLIN PUBLIC"),
    ("Pacific High School", "FRANKLIN PUBLIC"),
    ("St. Clair High School", "FRANKLIN PUBLIC"),
    ("Sullivan Sr. High School", "FRANKLIN PUBLIC"),
    ("Union High School", "FRANKLIN PUBLIC"),
    ("Washington High School", "FRANKLIN PUBLIC"),
    # Missouri outer-metro private
    ("Christian School District", "ST CHARLES PRIVATE"),
    ("Duchesne High School", "ST CHARLES PRIVATE"),
    ("Lutheran High School of St. Charles County", "ST CHARLES PRIVATE"),
    ("St. Dominic High School", "ST CHARLES PRIVATE"),
    ("St. John Paul II Preparatory", "ST CHARLES PRIVATE"),
    ("St. Pius X Catholic High School", "JEFFERSON PRIVATE"),
    ("Crosspoint Christian School", "FRANKLIN PRIVATE"),
    ("St. Francis Borgia High School", "FRANKLIN PRIVATE"),
    # Madison County, Illinois public
    ("Alton High School", "MADISON PUBLIC"),
    ("Civic Memorial High School", "MADISON PUBLIC"),
    ("Collinsville High School", "MADISON PUBLIC"),
    ("East Alton-Wood River High School", "MADISON PUBLIC"),
    ("Edwardsville High School", "MADISON PUBLIC"),
    ("Granite City High School", "MADISON PUBLIC"),
    ("Highland High School", "MADISON PUBLIC"),
    ("Madison Senior High School", "MADISON PUBLIC"),
    ("Roxana Sr. High School", "MADISON PUBLIC"),
    ("Triad High School", "MADISON PUBLIC"),
    # St. Clair County, Illinois public
    ("Belleville High School-East", "ST CLAIR PUBLIC"),
    ("Belleville High School-West", "ST CLAIR PUBLIC"),
    ("Cahokia High School", "ST CLAIR PUBLIC"),
    ("Dupo High School", "ST CLAIR PUBLIC"),
    ("East St. Louis Senior High School", "ST CLAIR PUBLIC"),
    ("Freeburg Community High School", "ST CLAIR PUBLIC"),
    ("Lebanon High School", "ST CLAIR PUBLIC"),
    ("Marissa Jr. & Sr. High School", "ST CLAIR PUBLIC"),
    ("Mascoutah High School", "ST CLAIR PUBLIC"),
    ("New Athens High School", "ST CLAIR PUBLIC"),
    ("O Fallon High School", "ST CLAIR PUBLIC"),
    ("SIU Charter School of East St. Louis", "ST CLAIR CHARTER"),
    # Monroe County, Illinois public
    ("Columbia High School", "MONROE PUBLIC"),
    ("Valmeyer High School", "MONROE PUBLIC"),
    ("Waterloo High School", "MONROE PUBLIC"),
    # Metro East private
    ("Father McGivney Catholic High School", "MADISON PRIVATE"),
    ("Marquette Catholic High School", "MADISON PRIVATE"),
    ("Maryville Christian School", "MADISON PRIVATE"),
    ("Metro-East Lutheran High School", "MADISON PRIVATE"),
    ("Rivers of Life Christian School", "MADISON PRIVATE"),
    ("Althoff Catholic High School", "ST CLAIR PRIVATE"),
    ("First Baptist Academy", "ST CLAIR PRIVATE"),
    ("Governor French Academy", "ST CLAIR PRIVATE"),
    ("Gibault Catholic", "MONROE PRIVATE"),
)
HS_SPECIAL_CHOICES = (
    ("NOT FROM AROUND HERE", "BOLD CHOICE"),
    ("MY SCHOOL ISN'T LISTED", "TAKE IT UP WITH DESE"),
)
HS_SEARCH_ALIASES = {
    "SLUH": "St. Louis University High School",
    "CBC": "Christian Brothers College High School",
    "CVPA": "Central Visual and Performing Arts High School",
    "MRH": "Maplewood Richmond Heights High School",
    "MICDS": "MICDS",
    "VIANNEY": "St. John Vianney High School",
    "ROSATI": "Rosati-Kain Academy",
    "FHC": "Francis Howell Central High School",
    "FHHS": "Francis Howell High School",
    "FHN": "Francis Howell North High School",
    "FZE": "Ft. Zumwalt East High School",
    "FZN": "Ft. Zumwalt North High School",
    "FZS": "Ft. Zumwalt South High School",
    "FZW": "Ft. Zumwalt West High School",
    "ESTL": "East St. Louis Senior High School",
    "OFALLON": "O Fallon High School",
}
CHARACTER_LOOKS = (
    "RED JACKET", "TEAL WINDBREAKER", "GOLD HOODIE",
    "PURPLE SWEATER", "CREAM TEE", "CARDINALS WHITE",
)

# --- Street names -------------------------------------------------------
# The grid was already here; it just had no names on it, and a St. Louis
# street grid without Gravois or Kingshighway on it is any city's street grid.
# Roads run every 8 tiles (range(4, W, 8)), so these are keyed by that line.
# Names run north to south and west to east, roughly where they really are.
STREET_ROWS = {
    12: "DELMAR", 20: "PAGE", 28: "LINDELL", 36: "OLIVE", 44: "MARKET",
    52: "CHOUTEAU", 60: "ARSENAL", 68: "GRAVOIS", 76: "CHIPPEWA",
    84: "MERAMEC", 92: "LOUGHBORO",
}
STREET_COLS = {
    4: "SKINKER", 12: "HAMPTON", 20: "KINGSHWY", 28: "VANDEVNTR",
    36: "GRAND", 44: "JEFFERSON", 52: "TUCKER", 60: "BROADWAY",
    68: "MEMORIAL", 76: "WHARF", 84: "LEONOR K",
}

# --- Potholes -------------------------------------------------------------
# City of St. Louis. One of them has had a cone in it for years, and it is the
# same cone in the same hole every session, because that is also true.
POTHOLE_COUNT = 34
# A pothole is a joke and a jolt, not a health bar. At 7.0 the thirty-four of
# them scattered across the city were quietly the single largest thing eating a
# chase car - measured at 46 of 100hp over forty seconds of driving, with no
# police involved at all. It still costs you 12% of your speed and a faceful of
# screen shake, which in a pursuit is the part that hurts.
POTHOLE_DAMAGE = 2.5
POTHOLE_RADIUS = 22

# --- The bank under the Arch ---------------------------------------------
# Cash you are carrying is not yours yet. Drive or walk under the span of the
# Gateway Arch and it banks. Die and every unbanked dollar hits the pavement
# where you died, recoverable for a minute if you dare go back for it.
#
# This is the spine the sandbox was missing. Before it, cash arrived from
# deliveries and left only as bail - and bail is min(cash, cost), so once you
# were broke, which took about sixty seconds, getting busted was free and the
# number top-right never moved again for the rest of the session. Now there
# is a reason to drive somewhere specific, a reason to stop, a reason to be
# frightened of dying, and a "one more run before I bank" decision every
# forty-five seconds.
BANK_RADIUS = 150           # px from the centre of the Arch footprint
BANK_MIN = 1                # do not spam the callout for nothing
DROPPED_CASH_LIFE = FPS * 60    # how long your dropped roll waits for you
DROPPED_CASH_RADIUS = 34
SAVE_VERSION = 6
ARCH_JOB_TARGET = 50000     # banked. The door at the end of the ladder.
ARCH_JOB_SECONDS = 90
ARCH_JOB_SCORE = 50000
ARCH_VICTORY_HOLD_STEPS = FPS * 5
ARCH_LOCKED = 'locked'
ARCH_READY = 'ready'
ARCH_CUTTER = 'cutter'
ARCH_RETURN = 'arch'
ARCH_ESCAPE = 'escape'
ARCH_LAY_LOW = 'lay_low'
ARCH_COMPLETE = 'complete'
ARCH_ACTIVE_PHASES = frozenset((ARCH_CUTTER, ARCH_RETURN, ARCH_ESCAPE, ARCH_LAY_LOW))

# --- Jobs -----------------------------------------------------------------
# The delivery loop: cash comes from finishing runs, score comes from chaos.
# Keeping them separate is the whole point - one rewards care, one doesn't.
JOB_MARKER_RADIUS = 46      # px: how close counts as arriving
JOB_BASE_PAY = 90
JOB_PAY_PER_TILE = 4.0
JOB_SECONDS_PER_TILE = 0.60
JOB_MIN_SECONDS = 25.0
JOB_MIN_TILE_SPAN = 12      # never pair two landmarks that are basically adjacent
JOB_STREAK_BONUS = 0.15     # +15% per consecutive on-time drop, capped below
JOB_STREAK_CAP = 6
JOB_HEAT_LIMIT = 3          # no dispatcher will hand you a run at 3+ stars
# The pickup leg has no clock, which is right - exploring toward a job should
# never be punished - but it also meant a run you did not want sat on the HUD
# for the whole session. It expires, and R rerolls it on the spot.
JOB_OFFER_SECONDS = 100
# Deliver and the next run is already on the table, worth more if you take it
# straight away. This replaces two seconds of silence with a decision.
JOB_CHAIN_WINDOW = FPS * 6
JOB_CHAIN_BONUS = 0.20
JOB_MASTERY_BONUS = 200     # first completion of each run type
CITY_EVENT_JOB_BONUS = 0.10 # today's civic mess makes every completed run richer
JOB_KIND_ORDER = ('courier', 'rush', 'hot', 'heavy')

# --- Side jobs ------------------------------------------------------------
# One contact rotates through three very different verbs. E accepts it on
# foot; active side work temporarily owns the objective marker and HUD.
SIDE_MISSION_CONTACT_NAMES = ("City Museum", "Grand Center Arts District",
                              "Bevo Mill")
SIDE_MISSION_CONTACT_RADIUS = 38
SIDE_MISSION_TARGET_RADIUS = 20
SIDE_MISSION_COOLDOWN = FPS * 5
SIDE_MISSION_MARKER_COLORS = ((232, 92, 188), (126, 42, 104))

# --- The body shop --------------------------------------------------------
# Kingshighway. Drive in hot, come out a different colour. The classic GTA
# cash sink, and the game's first answer to "what do I spend money on" beyond
# bail - which was previously the entire economy.
BODY_SHOP_COST = 300
BODY_SHOP_RADIUS = 52
BODY_SHOP_TILES = ((21, 45), (52, 68), (75, 28))

# --- Chaos score multiplier --------------------------------------------------
# The GTA1 compulsion spine: every reckless act feeds a running multiplier,
# parking bleeds it, and death (busted / wasted) wipes it. Chaos score is
# multiplied; delivery cash and the flat delivery bonus are not.
MULT_MAX = 8
MULT_RUNG = 55             # chaos points banked per multiplier rung
MULT_DECAY_GRACE = FPS * 7 # steps of no chaos before the multiplier starts to fall
MULT_DECAY_STEP = FPS * 3  # steps per rung shed after that

# --- Kill Frenzy -----------------------------------------------------------
FRENZY_SECONDS = 45
FRENZY_COOLDOWN = FPS * 10   # after one ends before the next icon appears
# The streak ladder. It used to stop at 20 and the window that held a streak
# together was two seconds, which on a 64px street is about one person - so the
# ladder above ten was decoration nobody ever saw. The window now grows with
# the streak (COMBO_WINDOW below), and the rungs keep coming.
COMBO_SHOUTS = {5: "GOURANGA!", 10: "SLINGER STREAK",
                15: "TOTAL CARNAGE", 20: "ST LOUIS HATES YOU",
                25: "MOUND CITY MASSACRE", 30: "CALL THE ARCHBISHOP",
                40: "SOUTH SIDE IS CLOSED", 50: "GATEWAY TO THE OTHER PLACE"}
# Steps a streak survives without a fresh hit. Two seconds flat meant a streak
# died between one crowd and the next; it now stretches as the streak grows, so
# a run through three blocks of sidewalk stays a single run.
COMBO_WINDOW_MIN = FPS * 2
COMBO_WINDOW_MAX = FPS * 5
COMBO_WINDOW_RUNGS = 14     # streak length at which the window is fully open

# --- On-foot player health ----------------------------------------------
PLAYER_MAX_HP = 100.0
PLAYER_HP_REGEN = 0.06      # per step, when not freshly hit

# --- Splatter -------------------------------------------------------------
# Below this closing speed a pedestrian is knocked down and gets up again;
# at or above it they do not. Both of these were authored against a 9.5 top
# speed (0.55 and 0.26 of it); against the current PLAYER_CAR_MAX_SPEED the old
# literals would have put splattering at 81% of flat out, i.e. almost never -
# which is the wrong way round, because running people down is the best thing
# in the game. Kept as fractions so they cannot drift out of scale again.
SPLAT_SPEED = PLAYER_CAR_MAX_SPEED * 0.55
# Below this a car-on-pedestrian contact is a bump, not an offence.
NUDGE_SPEED = PLAYER_CAR_MAX_SPEED * 0.27
DECAL_MAX = 64              # ground stains kept before the oldest is dropped

# --- Combat ---------------------------------------------------------------
PUNCH_RANGE = 30            # px from the player's centre
PUNCH_ARC = 1.15            # radians, half-angle of the swing
PUNCH_COOLDOWN = 16         # steps between swings
PUNCH_DAMAGE = 26.0         # against a car / actor
BAT_RANGE = 39
BAT_ARC = 1.35
BAT_COOLDOWN = 22
BAT_DAMAGE = 82.0
SHOOT_COOLDOWN = 11         # pistol compatibility reference
BULLET_SPEED = 13.0
BULLET_LIFE = 42            # steps (~9 tiles of travel)
BULLET_DAMAGE = 34.0        # pistol compatibility reference
PISTOL_AMMO = 24            # rounds per pickup
SHOTGUN_AMMO = 10
SMG_AMMO = 72
WEAPON_ORDER = ('fists', 'bat', 'pistol', 'shotgun', 'smg',
                throwable_logic.TIMED_EXPLOSIVE, throwable_logic.FIRE_BOTTLE)
WEAPON_PICKUP_KINDS = ('pistol', 'bat', 'shotgun', 'smg',
                       throwable_logic.TIMED_EXPLOSIVE,
                       throwable_logic.FIRE_BOTTLE)
WEAPON_DEFS = {
    'fists': {'label': 'FISTS', 'melee': True, 'range': PUNCH_RANGE,
              'arc': PUNCH_ARC, 'cooldown': PUNCH_COOLDOWN,
              'damage': PUNCH_DAMAGE, 'car_damage': PUNCH_DAMAGE},
    'bat': {'label': 'BASEBALL BAT', 'melee': True, 'range': BAT_RANGE,
            'arc': BAT_ARC, 'cooldown': BAT_COOLDOWN,
            'damage': BAT_DAMAGE, 'car_damage': 44.0},
    'pistol': {'label': 'PISTOL', 'ammo': PISTOL_AMMO, 'cooldown': SHOOT_COOLDOWN,
               'damage': BULLET_DAMAGE, 'speed': BULLET_SPEED,
               'life': BULLET_LIFE, 'pellets': 1, 'spread': 0.0},
    'shotgun': {'label': 'SHOTGUN', 'ammo': SHOTGUN_AMMO, 'cooldown': 30,
                'damage': 30.0, 'speed': 12.0, 'life': 24,
                'pellets': 6, 'spread': 0.30},
    'smg': {'label': 'SMG', 'ammo': SMG_AMMO, 'cooldown': 4,
            'damage': 19.0, 'speed': 14.0, 'life': 38,
            'pellets': 1, 'spread': 0.06},
    throwable_logic.TIMED_EXPLOSIVE: {
        'label': 'SATCHEL', 'ammo': 2, 'cooldown': 42, 'throwable': True,
    },
    throwable_logic.FIRE_BOTTLE: {
        'label': 'FIRE BOTTLE', 'ammo': 2, 'cooldown': 30,
        'throwable': True,
    },
}
WEAPON_PICKUP_COUNT = 18
WEAPON_RESPAWN = FPS * 25

# --- St. Louis grub: the power-up layer ----------------------------------
# Pork steak and provel were shop signs, which is wrong twice over - neither
# is a shop, and both are much funnier as something you eat off the street
# mid-chase. These are GTA1 power-ups: walk over one, a clock starts, the
# screen shouts, and for a few seconds you are different.
#
# key -> (label, seconds, hud colour, marker colour, one-line effect)
GRUB_KINDS = {
    # The south-city Sunday cookout in a bun. Heals you outright and then
    # makes you hard to put down - this is the flagship.
    'pork_steak': ("PORK STEAK", 20, (238, 216, 158), (150, 78, 54),
                   "half damage taken"),
    # A basket of t-ravs. Common, cheap, straight heal, no timer.
    'toasted_rav': ("T-RAVS", 0, (244, 226, 160), (176, 132, 66),
                    "heals you"),
    # Sugar rush. Legend says a baker got the proportions wrong and the city
    # decided to keep it that way.
    'gooey_butter': ("GOOEY BUTTER", 15, (250, 226, 150), (214, 178, 92),
                     "faster on foot and on the gas"),
    # Ted Drewes hands it to you upside down to prove it will not fall out.
    'concrete': ("CONCRETE", 14, (246, 240, 226), (222, 218, 208),
                 "you do not go down, and you hit harder"),
    # Provel: not a cheese, a civic argument. Throw it under a cruiser.
    'provel': ("PROVEL", 14, (226, 230, 240), (226, 214, 150),
               "the cops lose their grip"),
    # A tallboy in a brown bag. Doubles the chaos multiplier's appetite and
    # makes the wheel wander, which is the joke and the trade.
    'tallboy': ("TALLBOY", 18, (226, 232, 236), (150, 156, 168),
                "double chaos, wandering wheel"),
}
GRUB_PICKUP_COUNT = 14      # scattered on reachable ground at once
GRUB_RESPAWN = FPS * 30
GRUB_RADIUS = 26            # px: how close counts as eating it
GRUB_HEAL = 42.0            # HP a food pickup restores
GRUB_SPEED_BONUS = 1.30     # gooey butter: on foot and on the throttle
GRUB_ARMOUR = 0.5           # pork steak: incoming damage multiplier
GRUB_RAM_BONUS = 2.0        # concrete: damage you deal by ramming
GRUB_COP_GRIP = 0.62        # provel: cop max speed while they are sliding

# Every fixed callout / shout string, gathered so the font-coverage test can
# assert the bitmap font actually has every glyph they need.
CALLOUT_STRINGS = (
    "DELIVERED!", "BUSTED!", "WASTED", "LOST 'EM", "NEW TURF",
    "MULTIPLIER LOST", "MULTIPLIER X8", "KILL FRENZY!", "FRENZY OVER",
    "FRENZY DONE", "JACKED!", "12 LEFT", "YOU MONSTER",
    # chase senses + the death card
    "SPOTTED", "SEARCHING", "HIDDEN", "BAIL $250", "WRECK TOTALLED",
    # St. Louis grub
    "PORK STEAK", "T-RAVS", "GOOEY BUTTER", "CONCRETE", "PROVEL",
    "TALLBOY", "+42HP", "PORK STEAK 20",
    # St. Louis
    "CITY OF ST LOUIS", HS_QUESTION, "CROSSED DELMAR",
    "RESPRAYED", "HOT STREAK", "BODY SHOP - $300", "-$300",
    ) + tuple(STREET_ROWS.values()) + tuple(STREET_COLS.values()) + tuple(
        HS_ANSWERS) + tuple(HS_REPLIES) + (
    # the bank under the Arch
    "BANKED $1200", "GOT IT BACK", "$50000 TO THE ARCH JOB",
    "THE ARCH JOB IS OPEN", "DROPPED $900 - GO GET IT",
    "THE ARCH JOB", "GOT THE CUTTER", "RUN!", "ARCH JOB FAILED",
    "ARCH JOB COMPLETE", "THE ITALIAN JOB. MISSOURI RULES.",
    "RUN DOWN ON THE STREET", "SCORE 0", "CASH $0", "RUNS 0   STREAK 0",
    "COMING TO UNDER THE ARCH", "RELEASED FROM THE STATION",
)

# --- Tile types ---
TILE_GRASS = 0
TILE_ROAD = 1
TILE_WATER = 2
TILE_BUILDING = 3
TILE_PARK = 4
TILE_PLAZA = 5              # walkable landmark ground: plazas, alleys, concourses
TILE_RAIL = 6               # dedicated, non-road rail right-of-way

# --- MetroLink -------------------------------------------------------------
# This was one dead-straight row across the entire map at row 53, chosen
# because row 53 happened to be free of collisions. Two things wrong with
# that. It ran through the Compton Hill Water Tower's lawn; and row 53 is
# south city, where the real MetroLink conspicuously does not go - which is a
# thing people here complain about, not a thing to build.
#
# The Red Line's actual alignment comes in from the north-west beside Delmar,
# runs east along Forest Park's north edge, serves the Central West End and
# Grand, swings south around downtown and crosses the Mississippi on the Eads.
# It is a polyline, so the trains follow a polyline.
#
# Waypoints are (col, row) and every leg is axis-aligned. At this compressed
# scale the central corridor turns east on Olive and crosses the Eads north of
# the Arch grounds. The previous alignment dropped to Chouteau and then ran
# through the middle of the Arch footprint to reach the river.
METROLINK_WAYPOINTS = (
    (2, 2), (2, 23),        # Lambert / North Hanley / UMSL compressed north-west
    (12, 23),               # east beside Delmar
    (12, 26), (62, 26),     # south a block, then east past the park and the CWE
    (62, 32),               # compact downtown connector, west of the Arch
    (82, 32),               # Olive to Laclede's Landing and the Eads
)
#: named stops, west to east: (col, row, name)
METROLINK_STATIONS = (
    (2, 2, "LAMBERT AIRPORT"),
    (2, 9, "NORTH HANLEY"),
    (2, 15, "UMSL"),
    (3, 23, "ROCK ROAD"),
    (6, 23, "WELLSTON"),
    (12, 25, "DELMAR LOOP"),
    (20, 26, "FOREST PK-DEBALIVIERE"),
    (34, 26, "CENTRAL WEST END"),
    (50, 26, "GRAND"),
    (62, 30, "UNION STATION"),
    (68, 32, "CIVIC CENTER"),
    (76, 32, "8TH & PINE"),
    (86, 32, "LACLEDE'S LANDING"),
)
METROLINK_TRACK_OFFSETS = (-10, 10)
# The Loop Trolley. It runs on Delmar and it does not go very far, which is
# the entire joke and also the entire truth: about two miles, Loop to the
# History Museum. It used to run the full width of the map.
# The Clydesdale beat: west along Gravois' grid leg, then south down Broadway
# past the brewery. Both legs are clear of buildings, and neither of them is
# the river.
CLYDESDALE_ROW = 63
CLYDESDALE_WEST = 59
CLYDESDALE_COL = 79
CLYDESDALE_SOUTH = 72

TROLLEY_ROW = 21
TROLLEY_COL_MIN = 0
TROLLEY_COL_MAX = 34
TROLLEY_SPEED = 1.9
RAIL_GATE_WARNING_DISTANCE = 360.0
RAIL_GATE_ARM_RATE = 0.028
RAIL_GATE_STOP_DISTANCE = 92.0
RAIL_GATE_LANE_HALF_WIDTH = 25.0
RAIL_TRAIN_COLLISION_DAMAGE = 220.0

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
COLOR_SHADOW = (24, 20, 22)
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
# Landmark districts whose street level should usually read as shopfronts.
_COMMERCIAL_LANDMARKS = {
    "Delmar Loop", "Grand Center Arts District", "Central West End",
    "The Hill", "Downtown", "Soulard Farmers Market", "Cherokee Street",
}
_FABRIC_LANDMARKS = {
    "Delmar Loop", "Grand Center Arts District", "Central West End", "The Hill",
}


def facade_is_storefront(landmark, kind):
    """Choose mixed-use frontage without letting an entire district become a
    shopping-mall texture. The Hill keeps businesses on roughly half of its
    exposed tiles; its two-family flats get to exist between them."""
    if landmark == "The Hill":
        return kind in (1, 2, 3, 4)
    return landmark in _COMMERCIAL_LANDMARKS or kind <= 3


def building_art_color(c, r, tile):
    """Break district-sized landmark rectangles back into individual brick
    buildings. Bespoke landmarks stay coherent; neighborhood fabric varies."""
    base = tile['color']
    if tile.get('landmark') in _FABRIC_LANDMARKS:
        local = CITY_BRICKS[_noise(c, r, 607) % len(CITY_BRICKS)]
        return _blend(base, local, 0.76)
    return base

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
#
# Collision layout per landmark. The old single rule stamped a 3x3 maze of
# 2x2 blocks into every "building" landmark, which made them miserable to
# deliver into: no legible way in, and the drop marker could land deep in an
# alley. Each landmark now gets a shape that matches its art and reads at a
# glance - see _landmark_tile().
LANDMARK_LAYOUT = {
    "Lambert Airport": "airport",
    "Gateway Arch": "arch",              # two leg footings; walk under the span
    "Busch Stadium": "stadium",          # solid bowl, one gate to the field
    "Ted Drewes": "drivein",             # stand at the back, queue in the lot
    "Ted Drewes on Grand": "drivein",
    "Soulard Farmers Market": "market",  # open sheds you walk the aisles of
    "Union Station": "trainshed",        # one arched entry, a shed of columns
    "Compton Hill Water Tower": "tower",  # one solid tile in an open lawn
    "Bissell Street Water Tower": "tower",
    "Bevo Mill": "tower",
    "Cherokee Street": "strip",          # two shop rows with the street between
    # Henry Shaw's garden is a GARDEN. It had no entry here at all, so it fell
    # through to the default "district" layout and generated a ring of
    # buildings around a courtyard - a wall of masonry standing in the middle
    # of the Missouri Botanical Garden. The only solid mass in a garden is the
    # glass: the Climatron, the Linnean House, Shaw's own house.
    "Missouri Botanical Garden": "garden",
    # Brick blocks with yard streets between them, matching the art.
    "Anheuser-Busch Brewery": "brewery",
    # The four districts whose own art draws its own street grid.
    "Central West End": "blocks",
    "The Hill": "blocks",
    "Delmar Loop": "blocks",
    "Grand Center Arts District": "blocks",
}
LANDMARK_DEFAULT_LAYOUT = "district"     # building ring + gates + open courtyard

# Bespoke district art may carry a real named street through its footprint.
# Keep that street in the collision/traffic map as road rather than letting the
# landmark's coarse tile mask turn the painted carriageway into a wall. Grand
# Boulevard is drawn north/south through the middle of Grand Center at column
# 57; it must remain continuous between the grid roads above and below.
LANDMARK_THROUGH_ROADS = {
    "Lambert Airport": {
        'cols': frozenset((2,)),
        'rows': frozenset((2,)),
    },
    "Grand Center Arts District": {
        'cols': frozenset((57,)),
        'rows': frozenset(),
    },
}

# Positions trace the real St. Louis map (north = up, Mississippi on the east
# edge): the Arch on the riverfront with downtown and the ballpark just inland,
# Soulard and the brewery south of downtown by the river, a midtown spine
# (Grand Center -> Central West End) running west to Forest Park, the Delmar
# Loop up in the north-west, and the south-city parks (The Hill, Tower Grove)
# down in the south. Compressed and not to scale, but recognisable in the hand.
LANDMARKS = [
    # --- Compressed northwest annex ---------------------------------------
    (0, 0, 8, 8, "building", "Lambert Airport", (142, 148, 156)),
    # --- East: the river, the Arch, downtown, the ballpark ---
    (82, 40, 9, 12, "building", "Gateway Arch", (170, 172, 168)),
    # Busch III was sited so the Arch stands over centre field; the two used
    # to be half a map apart, with downtown fused onto the ballpark.
    # Fit the bowl inside the short downtown block. Chouteau (row 43), Poplar
    # (row 50), Broadway (73) and 7th (79) now remain actual asphalt instead
    # of sidewalk seams around a landmark painted over the road graph.
    (74, 44, 5, 6, "building", "Busch Stadium", (118, 108, 122)),
    (63, 32, 12, 10, "building", "Downtown", (104, 100, 112)),
    # Soulard Market and the brewery were one landmark and are a mile and a
    # half apart: the market is 7th & Lafayette, the brewery is down past
    # Arsenal by the river, and you can smell which is which.
    (74, 51, 5, 6, "building", "Soulard Farmers Market", (168, 120, 72)),
    (67, 66, 10, 9, "building", "Anheuser-Busch Brewery", (150, 92, 58)),
    # --- Midtown spine, running north-west from downtown ---
    # Grand & Washington is most of a mile NORTH of Market Street; Grand
    # Center used to sit on a line with the ballpark.
    (53, 31, 9, 9, "building", "Grand Center Arts District", (108, 78, 136)),
    (32, 28, 9, 10, "building", "Central West End", (96, 104, 132)),
    (11, 27, 20, 16, "park", "Forest Park", COLOR_PARK),
    # --- North-west ---
    # Delmar & Skinker is under a mile north of the park - you can see one
    # from the other - not marooned in the corner of the map. Its east end
    # lands above Forest Park's north-west corner, which puts the Delmar
    # Divide on a real row.
    (1, 15, 15, 5, "building", "Delmar Loop", (150, 84, 76)),
    # --- North City anchors ------------------------------------------------
    (51, 10, 6, 5, "park", "Fairground Park", COLOR_PARK),
    (80, 10, 5, 5, "building", "Bissell Street Water Tower", (178, 146, 112)),
    # --- South city ---
    # Ted Drewes on Chippewa: a low white custard stand set back behind its
    # lot, with the queue that never goes away. It was at (37,53) - NORTH of
    # both The Hill and Tower Grove Park, about three miles from where it
    # belongs. Nobody in this city has ever driven north to get custard.
    (5, 77, 6, 4, "building", "Ted Drewes", (226, 222, 212)),
    # And the other one, on Grand. There are two. This is a fact people will
    # correct you about.
    (45, 74, 5, 3, "building", "Ted Drewes on Grand", (226, 222, 212)),
    (23, 55, 10, 9, "building", "The Hill", (156, 108, 66)),
    (38, 59, 14, 13, "park", "Tower Grove Park", COLOR_PARK),
    # --- Downtown, working out from the Arch ---
    # The green dome you see framed through the Arch. Dred Scott was tried
    # here, and the Arch was deliberately sited on its axis - so it goes on
    # the Arch's own row, which is the whole composition.
    (76, 33, 5, 5, "building", "Old Courthouse", (196, 190, 172)),
    # Union Station: the headhouse, the shed, and the clock tower.
    # These sit inside their irregular city blocks instead of on top of the
    # road graph. Market/Chouteau and the 18th/Tucker corridors stay car-wide.
    (64, 44, 4, 6, "building", "Union Station", (176, 166, 142)),
    # City Museum: a former shoe factory with a school bus on the roof.
    (58, 44, 5, 6, "building", "City Museum", (150, 66, 58)),
    # --- South city ---
    # Compton Hill Water Tower: one of three still standing, which is more
    # than any other city in the country has, and locals will tell you.
    (48, 52, 5, 5, "building", "Compton Hill Water Tower", (196, 180, 150)),
    # Henry Shaw's garden, half a mile from Henry Shaw's park.
    (30, 46, 8, 7, "building", "Missouri Botanical Garden", (96, 128, 84)),
    # Meet me by the windmill.
    (32, 82, 5, 5, "building", "Bevo Mill", (206, 190, 164)),
    # Cherokee Street: antiques at the east end, mercados at the west.
    (54, 76, 16, 4, "building", "Cherokee Street", (168, 100, 62)),
]

# One line of real St. Louis for every landmark and every named feature
# inside one. Discovery used to fire "Discovered: X!" and nothing else, which
# is a scoring event, not a city. Everything here is checkable.
LANDMARK_PLAQUES = {
    "Lambert Airport":
        "Yamasaki's arched terminal opened in 1956, built for the jet age.",
    "Gateway Arch":
        "630 feet, and exactly as wide. Saarinen, finished 1965.",
    "Fairground Park":
        "A 131-acre North City park, home to generations of games and gatherings.",
    "Bissell Street Water Tower":
        "The 206-foot Red Water Tower has watched over North City since 1885.",
    "Busch Stadium":
        "Sited so the Arch stands over centre field.",
    "Downtown":
        "The Wainwright of 1891 is one of the first true skyscrapers.",
    "Soulard Farmers Market":
        "Trading since 1779 - before the Louisiana Purchase.",
    "Anheuser-Busch Brewery":
        "The Brew House is a National Historic Landmark. So are the horses.",
    "Grand Center Arts District":
        "The Fox opened in 1929 and seats over 4,000.",
    "Central West End":
        "The Basilica holds the largest mosaic collection in the world.",
    "Forest Park":
        "1,300 acres - half again the size of Central Park.",
    "Delmar Loop":
        "Chuck Berry played Blueberry Hill monthly for 17 years.",
    "Ted Drewes":
        "Frozen custard on Route 66 since 1930. Christmas trees after.",
    "Ted Drewes on Grand":
        "The other one. There are two, and people will correct you.",
    "The Hill":
        "Yogi Berra and Joe Garagiola grew up across the street from each other.",
    "Tower Grove Park":
        "289 acres of Henry Shaw's Victorian Gardenesque, given to the city.",
    "Old Courthouse":
        "Dred Scott sued for his freedom here, in 1846.",
    "Union Station":
        "Once the largest and busiest train station in the world.",
    "City Museum":
        "A shoe factory that Bob Cassilly turned inside out.",
    "Compton Hill Water Tower":
        "One of only seven standing water towers left in the country.",
    "Missouri Botanical Garden":
        "Founded in 1859 - America's oldest continuously operating botanical garden.",
    "Bevo Mill":
        "Built by August Busch in 1917, halfway to his farm.",
    "Cherokee Street":
        "Antiques at one end, mercados at the other, cash at both.",
    # named places inside a landmark
    "The Grand Basin":
        "Dug for the 1904 World's Fair and never filled in.",
    "Art Hill":
        "Free art museum at the top, sledding down it the moment it snows.",
    "Saint Louis Art Museum":
        "Built as the Fair's Palace of Fine Art. Still free.",
    "The Muny":
        "America's oldest and largest outdoor theatre - 1,500 free seats since 1919.",
    "Saint Louis Zoo":
        "Free, by a tax the region voted on itself.",
    "The Jewel Box":
        "A greenhouse of glass and steel, 1936, in the middle of a park.",
    "The Climatron":
        "Buckminster Fuller's dome, 1960 - the first geodesic conservatory.",
    "Seiwa-en":
        "14 acres: the largest Japanese garden in North America.",
    "The Linnean House":
        "1882. The oldest continuously operating greenhouse west of the Mississippi.",
    "Tower Grove House":
        "Henry Shaw's country home. He is buried a few steps away.",
}

# Road rows carried across the Mississippi. The Eads is north of the Arch;
# putting it on row 43 made both the bridge and MetroLink bisect the memorial
# grounds. Row 32 is the north-downtown approach, and row 50 remains the
# southern Poplar Street crossing. Both are named grid streets.
RIVER_BRIDGES = (32, 50)
# Tiny land remnants left between the two river-bank offsets. They have no
# connection to the street flood fill and read as accidental concrete islands.
RIVER_POCKET_TILES = ((89, 12), (90, 12), (82, 18), (83, 18),
                      (89, 60), (90, 60))
CHAIN_OF_ROCKS_WAYPOINTS = ((91, 2), (94, 2), (99, 4))
RIVER_DES_PERES_WAYPOINTS = ((0, 96), (24, 96), (40, 94),
                             (68, 96), (91, 96))
CHAIN_OF_ROCKS_TILES = frozenset(_diagonal_run(CHAIN_OF_ROCKS_WAYPOINTS, 1))
RIVER_DES_PERES_TILES = frozenset(_diagonal_run(RIVER_DES_PERES_WAYPOINTS, 1))

# --- Features inside a landmark -------------------------------------------
# Forest Park is one landmark, but it contains four or five places a St.
# Louisan would name separately - and until now they were only paint. You
# could jog straight across the Emerson Grand Basin. Each of these claims its
# tiles inside the parent landmark, so it is discoverable in its own right,
# and the basin is real water you have to go round.
#
# Positions are fractions of the parent footprint so they track the baked art
# rather than being hand-copied tile numbers that silently drift apart.
# (parent, name, fx, fy, fw, fh, solid)
LANDMARK_FEATURES = (
    ("Forest Park", "The Grand Basin", 0.235, 0.515, 0.375, 0.105, True),
    ("Forest Park", "Art Hill", 0.250, 0.300, 0.345, 0.200, False),
    ("Forest Park", "Saint Louis Art Museum", 0.330, 0.190, 0.190, 0.105, False),
    ("Forest Park", "The Muny", 0.720, 0.150, 0.170, 0.160, False),
    ("Forest Park", "Saint Louis Zoo", 0.210, 0.720, 0.210, 0.150, False),
    ("Forest Park", "The Jewel Box", 0.470, 0.760, 0.110, 0.090, False),
    # The garden's own named places. The Climatron is the one you can pick out
    # from across the map, so it gets to be discoverable in its own right the
    # way the Grand Basin is; Seiwa-en is real water you have to go round.
    ("Missouri Botanical Garden", "The Climatron", 0.230, 0.130, 0.260, 0.300, False),
    ("Missouri Botanical Garden", "Seiwa-en", 0.620, 0.280, 0.260, 0.300, True),
    ("Missouri Botanical Garden", "The Linnean House", 0.120, 0.700, 0.380, 0.140, False),
    ("Missouri Botanical Garden", "Tower Grove House", 0.740, 0.700, 0.140, 0.140, False),
)

CIVILIAN_VARIANTS = ['sedan', 'coupe', 'van', 'pickup', 'taxi', 'trans_am']

# Kerbside cars use their own weighting: the black Trans Am should be the car
# you tell somebody about seeing, not one sixth of every block.
PARKED_VARIANTS_WEIGHTED = (['sedan'] * 8 + ['coupe'] * 5 + ['van'] * 4
                            + ['pickup'] * 4 + ['taxi'] * 2 + ['trans_am'])

# What ambient traffic / parked cars roll from. The St. Louis service vehicles
# (orange City refuse, sweeping, and forestry trucks, a box truck, a school
# bus, a Hill delivery scooter) are in the mix but rare, so the streets still
# read as mostly ordinary cars without increasing the fixed traffic count.
CIVILIAN_WEIGHTED = (['sedan'] * 6 + ['coupe'] * 4 + ['van'] * 3 + ['pickup'] * 3
                      + ['taxi'] * 2 + ['box_truck'] * 2 + ['vespa'] * 2
                      + ['bus'] * 1 + ['metrobus_70'] * 1
                      + ['garbage_truck'] * 1 + ['street_sweeper'] * 1
                      + ['forestry_truck'] * 1 + ['trans_am'] * 1)

# Random rarity made the orange truck absent from roughly two games in three,
# and streaming preserves a car's variant forever. Reserve a real fleet slot so
# the detail is part of St. Louis rather than something tests alone can see.
GUARANTEED_AMBIENT_VARIANTS = ('garbage_truck', 'metrobus_70')
ROUTE_70_COL = 57

# Rare local jokes belong at destinations, not clogging the ambient-traffic
# pool. There is exactly one of each, parked where a player can deliberately
# go find and steal it.
SHOWCASE_VEHICLES = (
    ('mudfoot', "Busch Stadium"),
    ('grocery_cart', "Soulard Farmers Market"),
)
SHOWCASE_VARIANTS = frozenset(v for v, _name in SHOWCASE_VEHICLES)
LOCAL_LEGENDS = {
    'mudfoot': {
        'name': "THE ORIGINAL",
        'venue': "Busch Stadium",
        'rumor': "A monster truck is crushing scrap near Busch Stadium.",
        'color': (96, 156, 244),
        'offset': (-TILE_SIZE * 0.8, TILE_SIZE * 0.6),
    },
    'grocery_cart': {
        'name': "THE BIG CART",
        'venue': "Soulard Farmers Market",
        'rumor': "Somebody parked a giant grocery cart near Soulard Market.",
        'color': (238, 78, 72),
        'offset': (TILE_SIZE * 0.7, -TILE_SIZE * 0.6),
    },
}
LOCAL_LEGEND_HINT_FIRST = FPS * 8
LOCAL_LEGEND_HINT_GAP = FPS * 75
LOCAL_LEGEND_DISCOVERY_RADIUS = TILE_SIZE * 2.5

LOCAL_CHALLENGE_REWARD = 750
LOCAL_CHALLENGE_TIMES = {
    'mudfoot': FPS * 60,
    'grocery_cart': FPS * 75,
    'trash_day': FPS * 120,
    'hill_hydrants': FPS * 90,
    'chain_escape': FPS * 75,
}
TRASH_DAY_TILES = ((15, 57), (21, 68), (32, 79),
                   (43, 73), (57, 63), (63, 57))
CART_SLALOM_TILES = ((73, 50), (79, 50), (79, 57),
                     (73, 57), (68, 57), (68, 50))
MUDFOOT_SCRAP_OFFSETS = ((-82, -54), (0, -70), (82, -54),
                         (-62, 62), (62, 62))
LOCAL_CHALLENGE_COLORS = {
    'mudfoot': (96, 156, 244),
    'grocery_cart': (238, 78, 72),
    'trash_day': (238, 134, 40),
    'hill_hydrants': (60, 202, 92),
    'chain_escape': (116, 190, 206),
}
CHAIN_ESCAPE_TILES = ((2, 2), (32, 2), (63, 2), (91, 2), (94, 2), (99, 4))

RADIO_STATIONS = (
    {
        'name': "K-SHE 95ISH",
        'color': (236, 116, 54),
        'breaks': (
            "Heritage rock, KSHE-ish and proudly stuck in the left lane.",
            "Traffic: somebody lost a ladder on forty again.",
            "This set goes out to everyone calling Highway 40 Highway 40.",
            "The forecast says eighty, then hail, then eighty again.",
        ),
    },
    {
        'name': "K-D-H-X 88ISH",
        'color': (100, 206, 176),
        'breaks': (
            "Community radio: one basement, twelve genres, no algorithm.",
            "Coming up: a local band whose drummer works at Vintage Vinyl.",
            "Listener calendar: block party, record fair, questionable puppet show.",
            "You are west of the river. The signal is doing its best.",
        ),
    },
    {
        'name': "K-M-O-X 1120ISH",
        'color': (166, 190, 232),
        'breaks': (
            "News, weather, traffic, baseball, and weather interrupting baseball.",
            "Caller says the Cardinals need one more middle reliever.",
            "Avoid Grand. No reason given. You already understand.",
            "Tonight's low is somehow tomorrow afternoon's high.",
        ),
    },
)
RADIO_BREAK_FIRST = FPS * 18
RADIO_BREAK_GAP = FPS * 38

CITY_EVENT_DEFS = {
    'cardinals_day': ("CARDINALS DAY", "Downtown is red. Traffic is not moving.", (214, 56, 58)),
    'soulard_parade': ("SOULARD PARADE", "Barricades, beads, and absolutely no parking.", (154, 74, 186)),
    'dogtown_parade': ("DOGTOWN PARADE", "The whole neighborhood called in Irish.", (62, 176, 86)),
    'first_monday': ("FIRST MONDAY", "It is eleven. Those are only the sirens.", (232, 190, 64)),
    'tower_grove_market': ("MARKET DAY", "Tower Grove has produce and nowhere to park.", (92, 170, 84)),
    'cherokee_festival': ("CHEROKEE STREET", "The street belongs to the crowd today.", (224, 112, 60)),
    'blues_night': ("GLORIA NIGHT", "Every bar has found the same song.", (72, 126, 214)),
    'grand_construction': ("GRAND CONSTRUCTION", "One lane closed. Nobody knows which one.", (236, 134, 40)),
    'trolley_delay': ("LOOP TROLLEY DELAY", "Two miles of track. Infinite possibilities.", (202, 76, 70)),
    'halloween_jokes': ("ST. LOUIS HALLOWEEN", "Tell a joke or nobody hands over candy.", (238, 126, 38)),
}
HALLOWEEN_JOKES = (
    "Why did the toasted ravioli cross the road? It was breaded that way.",
    "What high school did the ghost attend? Boo-mont.",
    "Why is the Arch calm? Nothing gets under its skin but everybody walks under it.",
    "What does a St. Louis vampire order? A concrete, hold the sunlight.",
    "Why did the temp tag expire? It was only printed for one administration.",
)
CITY_EVENT_ANNOUNCE_AT = FPS * 4
CITY_EVENT_VENUES = {
    'cardinals_day': (76, 47),
    'soulard_parade': (76, 54),
    'dogtown_parade': (15, 53),
    'tower_grove_market': (45, 63),
    'cherokee_festival': (62, 78),
    'blues_night': (76, 47),
    'grand_construction': (57, 35),
    'trolley_delay': (8, 17),
}
CITY_EVENT_TRAFFIC_SCALE = {
    'cardinals_day': 0.72,
    'soulard_parade': 0.55,
    'dogtown_parade': 0.58,
    'tower_grove_market': 0.72,
    'cherokee_festival': 0.62,
    'blues_night': 0.78,
    'grand_construction': 0.48,
    'trolley_delay': 0.65,
}

# Default car collider. The kerbside parking layout is sized against this, so
# it is a named constant both places can assert on rather than a loose 34/18.
VEHICLE_DEFAULT_W = 34
VEHICLE_DEFAULT_H = 18

# --- Handling: grip, and the handbrake ------------------------------------
# The car used to move *exactly* along its heading every step - no slip angle,
# no lateral momentum, no oversteer. That is a tank, not a car, and it made
# the one manoeuvre the whole series is built around impossible to express:
# stab the handbrake, let the back step out, rotate while carrying your
# momentum, power out of the corner.
#
# Measured on the old model: a 90-degree turn from one 64px street into
# another needs a ~40px radius, which capped corner-entry speed at 2.6 px/step
# against the original top speed of 9.5. You shed 73% of your speed at every single
# intersection, and that mandatory near-stop is what read as "driving a truck
# through mud". Player throttle and steering now also ease in separately from AI.
# How much sideways velocity SURVIVES each step. Higher means less grip, so
# the handbrake figure is the larger one: locking the back wheels is what lets
# the slide persist long enough to rotate the car.
LAT_RETAIN = 0.84           # tyres bite: a slide washes out in ~7 steps
LAT_RETAIN_HANDBRAKE = 0.965   # back end loose: it keeps going where it was
HANDBRAKE_STEER = 1.7       # steering authority multiplier while it is held
HANDBRAKE_DRAG = 0.955      # forward speed bleed while it is held
SLIP_SCREECH = 1.1          # px/step of lateral travel before the tyres howl
SKID_MIN_SLIP = 1.6         # ... and before they leave a mark on the road

# Per-variant handling + collider size. Anything absent uses the car defaults
# (34x18, max_steer 0.045, speed_factor 1.0). speed_factor scales traffic pace.
VEHICLE_TUNING = {
    'garbage_truck': dict(w=42, h=18, acceleration=0.15, max_steer=0.034, speed_factor=0.72),
    'street_sweeper':dict(w=38, h=18, acceleration=0.18, max_steer=0.038, speed_factor=0.76),
    'forestry_truck':dict(w=40, h=18, acceleration=0.19, max_steer=0.037, speed_factor=0.80),
    'bus':           dict(w=44, h=18, acceleration=0.17, max_steer=0.032, speed_factor=0.78),
    'metrobus_70':   dict(w=44, h=18, acceleration=0.18, max_steer=0.032, speed_factor=0.80),
    'box_truck':     dict(w=38, h=18, acceleration=0.20, max_steer=0.038, speed_factor=0.86),
    'vespa':         dict(w=16, h=12, acceleration=0.42, max_steer=0.060, speed_factor=1.15),
    'trans_am':      dict(w=34, h=18, acceleration=0.38, max_steer=0.052, speed_factor=1.12),
    # St. Louis built the original monster-truck legend; this affectionate
    # unbranded homage has the huge footprint, durability and pothole manners.
    'mudfoot':       dict(w=46, h=28, acceleration=0.34, max_steer=0.038, speed_factor=1.06),
    # A giant supermarket parade cart once rolled through local childhoods.
    'grocery_cart':  dict(w=48, h=24, acceleration=0.18, max_steer=0.050, speed_factor=0.72),
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
        # Fixed-livery cars need one bake, mapped to any colour key a spawner
        # can hand us. The Trans Am itself stores the fixed black key.
        colors = [None] if variant in ('taxi', 'trans_am') else CAR_COLORS
        for col in colors:
            frames = _scale_frames(cars_bake_variant(variant, col), SPRITE_SCALE_CAR)
            entry = (frames, [cars_make_shadow(f) for f in frames])
            if col is None:
                for c in CAR_COLORS:
                    sets[(variant, c)] = entry
                if variant == 'trans_am':
                    sets[(variant, cars_TRANS_AM_BODY)] = entry
            else:
                sets[(variant, col)] = entry
    for variant in cars_POLICE_FLASH_SETS:
        frames = _scale_frames(cars_bake_variant(variant), SPRITE_SCALE_CAR)
        entry = (frames, [cars_make_shadow(f) for f in frames])
        for c in CAR_COLORS + [POLICE_COLOR]:
            sets[(variant, c)] = entry
    # St. Louis service vehicles: fixed liveries, so one bake covers every
    # colour slot the spawner might ask for (same trick as the taxi).
    for variant in ('garbage_truck', 'street_sweeper', 'forestry_truck',
                    'bus', 'metrobus_70', 'box_truck', 'vespa', 'mudfoot',
                    'grocery_cart'):
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


# The Justice Center, downtown between Tucker and the ballpark. Kept clear of
# every landmark footprint: it used to land inside Union Station once that
# went in, which walled a released player - and any cop spawned there - into
# a train shed.
POLICE_STATION_TILE = (68, 52)


def _hash2(a, b, salt=0):
    """Order-stable deterministic hash for map generation (no random module)."""
    n = (a * 73856093) ^ (b * 19349663) ^ (salt * 83492791)
    n &= 0x7fffffff
    n = ((n * 1103515245) >> 13) & 0x7fffffff
    return n


# --- City block fabric ----------------------------------------------------
# Blocks are the irregular spans between the named road lines. Every span gets
# a deterministic character so the world reads as a dense brick city instead
# of empty lawn.
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
    # Sample a tile inside the block. The grid is irregular, so walk the real
    # line list rather than multiplying by a step that no longer exists.
    lines = sorted(ROAD_LINES)
    col = lines[min(bx, len(lines) - 1)] + 1
    row = lines[min(by, len(lines) - 1)] + 1
    pool = HOOD_BRICKS.get(hood_at(col, row), tuple(CITY_BRICKS))
    return pool[_hash2(bx, by, 99) % len(pool)]


def _block_spans(limit):
    """Return the [start, end) non-road spans between named streets."""
    lines = sorted(ROAD_LINES)
    spans = []
    prev = -1
    for line in lines:
        if line - 1 >= prev + 1:
            spans.append((prev + 1, line))
        prev = line
    if prev + 1 < limit:
        spans.append((prev + 1, limit))
    return [(start, end) for start, end in spans if end > start]


def _fill_city_blocks(game_map):
    """Stamp buildings / parks / lots into every grass block between roads.

    Runs before the landmark pass so landmarks cleanly overwrite the fabric.
    Leaves a one-tile walkable sidewalk ring inside each built block and an
    occasional mid-block alley, so peds have somewhere to walk and blocks are
    not solid walls.
    """
    col_spans = _block_spans(MAP_TILES_W)
    row_spans = _block_spans(MAP_TILES_H)
    for by, (top, bottom) in enumerate(row_spans):
        for bx, (left, right) in enumerate(col_spans):
            bw, bh = right - left, bottom - top
            if bw <= 0 or bh <= 0:
                continue
            kind = _block_kind(bx, by)
            brick = _block_brick(bx, by)
            # Alleys and courtyards are placed as a FRACTION of the block, so
            # a short downtown block and a long county block both get one in
            # the middle instead of the short one having its alley fall
            # outside it entirely.
            alley_col = bw // 2 if (bw >= 5 and _hash2(bx, by, 7) & 1) else -1
            alley_row = bh // 2 if (bh >= 5 and _hash2(bx, by, 13) & 1) else -1
            courtyard = bw >= 5 and bh >= 5 and _hash2(bx, by, 21) % 5 == 0
            for j in range(bh):
                for i in range(bw):
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
                    elif walk or (courtyard and 1 < i < bw - 2 and 1 < j < bh - 2):
                        game_map[y][x] = {'type': TILE_PLAZA, 'collidable': False,
                                          'landmark': None, 'color': COLOR_SIDEWALK}
                    else:
                        game_map[y][x] = {'type': TILE_BUILDING, 'collidable': True,
                                          'landmark': None, 'color': brick}


def river_bank(row):
    """West bank of the Mississippi on this row.

    The river used to be three dead-straight tiles at the east edge. At the
    Arch it is about two thousand feet wide and it bends, so the bank wanders
    a couple of tiles - enough to stop it reading as a canal - and the water
    is six tiles instead of three.
    """
    bank = MAP_TILES_W - 8
    if row < 20:
        bank += 2                    # the northward bend past the Chain of Rocks
    elif 40 <= row <= 55:
        bank -= 1                    # the bow the Arch sits inside
    return bank


def build_map():
    """Generate the tile grid: roads on a grid, the Mississippi down the east
    side, a dense brick block fabric between the roads, landmarks on top."""
    game_map = [[None] * MAP_TILES_W for _ in range(MAP_TILES_H)]
    road_lines = ROAD_LINES          # the named, irregular network

    for y in range(MAP_TILES_H):
        for x in range(MAP_TILES_W):
            if x in road_lines or y in road_lines:
                tile = {'type': TILE_ROAD, 'collidable': False, 'landmark': None, 'color': COLOR_ROAD}
            elif x >= MAP_TILES_W - 3:
                tile = {'type': TILE_WATER, 'collidable': True,
                        'landmark': None, 'color': COLOR_WATER}
            else:
                tile = {'type': TILE_GRASS, 'collidable': False, 'landmark': None, 'color': COLOR_GRASS}
            game_map[y][x] = tile

    _fill_city_blocks(game_map)

    for (lx, ly, lw, lh, kind, name, color) in LANDMARKS:
        for y in range(ly, min(ly + lh, MAP_TILES_H)):
            for x in range(lx, min(lx + lw, MAP_TILES_W)):
                through = LANDMARK_THROUGH_ROADS.get(name)
                if (through is not None
                        and (x in through['cols'] or y in through['rows'])):
                    game_map[y][x] = {
                        'type': TILE_ROAD, 'collidable': False,
                        'landmark': name, 'color': COLOR_ROAD,
                        'street': street_name(x, y),
                    }
                else:
                    game_map[y][x] = _landmark_tile(
                        x - lx, y - ly, lw, lh, kind, name, color)

    _stamp_features(game_map)
    _stamp_diagonals(game_map)
    # The river goes in before the rail, not after: it rebuilds the bridge
    # decks wholesale, which used to wipe the rail tag straight back off the
    # Eads and leave the MetroLink running on untagged road.
    _stamp_river(game_map)
    _stamp_special_routes(game_map)
    _stamp_rail_corridors(game_map)
    return game_map


#: Landmarks a diagonal is allowed to cut through. These are neighbourhoods
#: with a district/strip layout - a street through them is what they are made
#: of. The single-building landmarks (the Arch's legs, the stadium bowl, the
#: market sheds, a water tower) are never cut.
DIAGONAL_MAY_CUT = frozenset((
    "Downtown", "Central West End", "Grand Center Arts District",
    "The Hill", "Delmar Loop", "Cherokee Street",
))


def _stamp_diagonals(game_map):
    """Cut Gravois, Manchester and Natural Bridge across the finished grid.

    Stamped after the landmarks on purpose. A diagonal that the first district
    it touches erases is not an arterial, it is a driveway - and the whole
    point of Gravois is that it ignores everything in its way for nine miles.
    What it will not do is punch a hole through a landmark whose shape IS the
    landmark, so DIAGONAL_MAY_CUT gates it.
    """
    for name, points, width in DIAGONAL_STREETS:
        for (col, row) in _diagonal_run(points, width):
            tile = game_map[row][col]
            if tile['type'] == TILE_WATER:
                continue                       # never bridge on a whim
            owner = tile.get('landmark')
            if owner is not None and owner not in DIAGONAL_MAY_CUT:
                continue
            game_map[row][col] = {
                'type': TILE_ROAD, 'collidable': False,
                'landmark': owner, 'color': COLOR_ROAD,
                'street': name, 'diagonal': True,
            }


#: feature name -> the landmark it belongs to. _stamp_features renames a tile
#: to the feature that claims it ("The Climatron"), which silently broke every
#: "does this tile belong to a landmark with hand-made art" test - so the
#: generic building passes drew procedural houses straight over the dome.
LANDMARK_FEATURE_PARENT = {name: parent
                           for (parent, name, _fx, _fy, _fw, _fh, _s)
                           in LANDMARK_FEATURES}


def landmark_owner(name):
    """The landmark a tile belongs to, following a feature up to its parent."""
    return LANDMARK_FEATURE_PARENT.get(name, name)


def _stamp_features(game_map):
    """Claim the named places inside a landmark, and make the basin wet.

    Only the landmark name and (for water) the collision change; the ground
    type stays whatever the parent painted, so the baked art still shows
    through. Run before _compute_reachable so a sealed pocket would be caught.
    """
    parents = {e[5]: e for e in LANDMARKS}
    for (parent, name, fx, fy, fw, fh, solid) in LANDMARK_FEATURES:
        entry = parents.get(parent)
        if entry is None:
            continue
        lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
        x0 = lx + int(round(fx * lw))
        y0 = ly + int(round(fy * lh))
        x1 = min(lx + lw, x0 + max(1, int(round(fw * lw))))
        y1 = min(ly + lh, y0 + max(1, int(round(fh * lh))))
        for y in range(max(0, y0), min(MAP_TILES_H, y1)):
            for x in range(max(0, x0), min(MAP_TILES_W, x1)):
                tile = game_map[y][x]
                tile['landmark'] = name
                if solid:
                    tile['type'] = TILE_WATER
                    tile['collidable'] = True


def _metrolink_route():
    """The full waypoint list, with the last leg run out over the Eads."""
    pts = list(METROLINK_WAYPOINTS)
    end_row = pts[-1][1]
    pts.append((MAP_TILES_W - 1, end_row))
    return tuple(pts)


METROLINK_ROUTE = _metrolink_route()
METROLINK_ROW = METROLINK_WAYPOINTS[3][1]   # the long east-west leg, row 26


def metrolink_segments():
    """Axis-aligned (c0, r0, c1, r1, axis) legs, west to east."""
    legs = []
    for (c0, r0), (c1, r1) in zip(METROLINK_ROUTE, METROLINK_ROUTE[1:]):
        if c0 == c1 and r0 == r1:
            continue
        if c0 != c1 and r0 != r1:
            raise AssertionError(f"MetroLink leg {(c0, r0)}->{(c1, r1)} is not axis-aligned")
        legs.append((c0, r0, c1, r1, 'h' if r0 == r1 else 'v'))
    return tuple(legs)


METROLINK_SEGMENTS = metrolink_segments()


def metrolink_tiles():
    """Ordered, de-duplicated (col, row, axis) the alignment occupies."""
    out, seen = [], set()
    for c0, r0, c1, r1, axis in METROLINK_SEGMENTS:
        if axis == 'h':
            step = 1 if c1 >= c0 else -1
            leg = [(c, r0) for c in range(c0, c1 + step, step)]
        else:
            step = 1 if r1 >= r0 else -1
            leg = [(c0, r) for r in range(r0, r1 + step, step)]
        for (c, r) in leg:
            if (c, r) in seen:
                # a corner shared with the previous leg: the later leg's axis
                # wins, because that is the direction the train leaves on
                out = [e for e in out if (e[0], e[1]) != (c, r)]
            seen.add((c, r))
            out.append((c, r, axis))
    return tuple(out)


METROLINK_TILES = metrolink_tiles()


def _stamp_rail_corridors(game_map):
    """Cut the MetroLink right-of-way in after the landmarks are stamped.

    Three kinds of tile, because a light rail line is three different things
    along its length:

      * dedicated - its own ballasted right-of-way. It CARVES: a rail cut goes
        through the block fabric rather than politely going round it, which is
        what a right-of-way is and why the alignment can be chosen for
        geography instead of for whichever row happened to be empty.
      * crossing  - a street crosses it at grade. Keep the road, hang gates.
      * embedded  - the rail runs along a street or a district's open ground.
        Keep the tile exactly as it is and only inset the rails.
    """
    # A landmark whose collision shape IS the landmark (a stadium bowl, the
    # market sheds, a water tower, the Arch grounds) is never touched.
    protected = {name for name, layout in LANDMARK_LAYOUT.items()
                 if layout not in ("district", "strip")
                 and name not in ("Lambert Airport", "Delmar Loop")}
    for (col, row, axis) in METROLINK_TILES:
        if not (0 <= col < MAP_TILES_W and 0 <= row < MAP_TILES_H):
            continue
        existing = game_map[row][col]
        if existing['type'] == TILE_WATER:
            continue
        owner = existing.get('landmark')
        parallel_road = (row in ROAD_LINES) if axis == 'h' else (col in ROAD_LINES)
        cross_road = (col in ROAD_LINES) if axis == 'h' else (row in ROAD_LINES)
        if owner is not None and owner in protected:
            continue                       # never cut a landmark that is a shape
        if owner == "Delmar Loop" and existing['collidable']:
            existing['type'] = TILE_RAIL
            existing['collidable'] = False
            existing['color'] = (72, 68, 62)
        if parallel_road or owner is not None:
            existing['rail'] = 'metrolink'
            existing['rail_axis'] = axis
            existing['rail_crossing'] = False
            existing['rail_embedded'] = True
        elif cross_road:
            existing['type'] = TILE_ROAD
            existing['collidable'] = False
            existing['color'] = COLOR_ROAD
            existing['rail'] = 'metrolink'
            existing['rail_axis'] = axis
            existing['rail_crossing'] = True
        else:
            game_map[row][col] = {
                'type': TILE_RAIL, 'collidable': False,
                'landmark': owner, 'color': (72, 68, 62),
                'rail': 'metrolink', 'rail_axis': axis,
                'rail_crossing': False, 'rail_embedded': False,
            }

    # Corner pads. A train is longer than the 64px tile it turns through, so
    # a bare right-angle would leave its body hanging over the block on the
    # inside of the curve. Reserving the tiles around each corner is both what
    # a real curve radius looks like and what keeps the body on reserved rail.
    # Every interior corner of the ROUTE, not of the waypoint list: the
    # route appends the run out over the Eads, which turns the last
    # waypoint into a corner that would otherwise get no radius.
    corners = {(c, r) for (c, r) in METROLINK_ROUTE[1:-1]}
    for (col, row) in corners:
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                c, r = col + dc, row + dr
                if not (0 <= c < MAP_TILES_W and 0 <= r < MAP_TILES_H):
                    continue
                tile = game_map[r][c]
                if tile['type'] == TILE_WATER or tile.get('rail'):
                    continue
                owner = tile.get('landmark')
                if owner is not None and owner in protected:
                    # A curve may clip a protected landmark's OPEN ground -
                    # the stadium's outer apron, the Arch's plaza. Inset the
                    # rails and leave the tile exactly as it is; never carve.
                    if not tile['collidable']:
                        tile['rail'] = 'metrolink'
                        tile['rail_axis'] = 'h'
                        tile['rail_crossing'] = False
                        tile['rail_embedded'] = True
                    continue
                game_map[r][c] = {
                    'type': TILE_RAIL, 'collidable': False,
                    'landmark': owner, 'color': (72, 68, 62),
                    'rail': 'metrolink', 'rail_axis': 'h',
                    'rail_crossing': False, 'rail_embedded': False,
                }

    # A rail vehicle's body extends behind its centre when it reaches a
    # bumper. Lambert's new terminal starts only two tiles from the map edge,
    # so its westbound train used to put the rear third through a solid
    # terminal tile during the turnaround. Reserve a short straight headshunt
    # behind the first waypoint; this is track the train physically occupies,
    # even though its centre never travels over it.
    (c0, r0), (c1, r1) = METROLINK_ROUTE[:2]
    dc = 0 if c1 == c0 else (-1 if c1 > c0 else 1)
    dr = 0 if r1 == r0 else (-1 if r1 > r0 else 1)
    axis = 'h' if dr == 0 else 'v'
    for step in (1, 2):
        c, r = c0 + dc * step, r0 + dr * step
        if not (0 <= c < MAP_TILES_W and 0 <= r < MAP_TILES_H):
            continue
        owner = game_map[r][c].get('landmark')
        game_map[r][c] = {
            'type': TILE_RAIL, 'collidable': False,
            'landmark': owner, 'color': (72, 68, 62),
            'rail': 'metrolink', 'rail_axis': axis,
            'rail_crossing': False, 'rail_embedded': False,
        }

    # The Loop trolley is street-running: rails inset into Delmar, no separate
    # right-of-way and no gates. It also stops after two miles, like the real
    # one, instead of crossing the entire city.
    for col in range(TROLLEY_COL_MIN, min(TROLLEY_COL_MAX + 1, river_bank(TROLLEY_ROW))):
        tile = game_map[TROLLEY_ROW][col]
        if (tile['type'] == TILE_ROAD and not tile['collidable']
                and tile.get('rail') != 'metrolink'):
            tile['rail'] = 'trolley'


def _stamp_river(game_map):
    """Cut the Mississippi in last, over everything else.

    It has to be last. The road grid runs every eighth row clean across the
    map, so before this the river was crossed by a dozen invisible bridges and
    the city fabric filled in on top of the water - measured: rows 20 and 60
    were solid road from the levee to the Illinois bank. Stamping the river
    over the finished map means exactly two crossings exist, the ones named in
    RIVER_BRIDGES, and everything else is water.
    """
    for y in range(MAP_TILES_H):
        bank = river_bank(y)
        for x in range(bank, MAP_TILES_W):
            if y in RIVER_BRIDGES:
                game_map[y][x] = {'type': TILE_ROAD, 'collidable': False,
                                  'landmark': None, 'color': COLOR_ROAD}
            elif x >= MAP_TILES_W - 2:
                # The Illinois levee. There is a whole other state over there.
                game_map[y][x] = {'type': TILE_GRASS, 'collidable': False,
                                  'landmark': None, 'color': COLOR_GRASS_DARK}
            else:
                game_map[y][x] = {'type': TILE_WATER, 'collidable': True,
                                   'landmark': None, 'color': COLOR_WATER}
    for x, y in RIVER_POCKET_TILES:
        game_map[y][x] = {'type': TILE_WATER, 'collidable': True,
                          'landmark': None, 'color': COLOR_WATER}


def _stamp_special_routes(game_map):
    """Restore the two non-grid escape routes after the river owns its banks."""
    for col, row in RIVER_DES_PERES_TILES:
        if 0 <= col < MAP_TILES_W and 0 <= row < MAP_TILES_H:
            game_map[row][col] = {
                'type': TILE_PLAZA, 'collidable': False, 'landmark': None,
                'color': (104, 108, 106), 'des_peres': True,
                'street': "RIVER DES PERES CHANNEL",
            }
    for col, row in CHAIN_OF_ROCKS_TILES:
        if 0 <= col < MAP_TILES_W and 0 <= row < MAP_TILES_H:
            game_map[row][col] = {
                'type': TILE_ROAD, 'collidable': False, 'landmark': None,
                'color': (92, 94, 92), 'chain_of_rocks': True,
                'street': "OLD CHAIN OF ROCKS BRIDGE",
            }


def _blend(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---------------------------------------------------------------------------
# Neighbourhood character: which shop signs and which housing stock a block
# gets. Real St. Louis reads completely differently north to south - the Hill
# is delis and pizzerias over brick shotguns, the Loop and Grand Center are
# theatres and record shops, south city is Cherokee antiques and Bevo flats.
# Everything here is a deterministic lookup keyed on the tile, so no frame ever
# re-rolls a sign or a roof.
# ---------------------------------------------------------------------------
# (text <= 10 chars so it fits a 64px shopfront at scale 1, bg, fg)
SIGN_IMOS = ("IMO'S", (30, 86, 48), (238, 234, 214))
SIGN_OYSTER = ("OYSTER BAR", (58, 32, 92), (238, 158, 226))
SIGN_ANTIQUES = ("ANTIQUES", (92, 56, 34), (238, 214, 150))
SIGN_CROWN = ("CROWN", (188, 96, 132), (250, 242, 236))
SIGN_CUSTARD = ("CUSTARD", (176, 46, 44), (246, 240, 226))
SIGN_RAVIOLI = ("RAVIOLI", (140, 44, 40), (244, 226, 160))
SIGN_SLINGERS = ("EAT-RITE", (52, 66, 80), (226, 236, 240))
SIGN_BODEGA = ("BODEGA", (166, 96, 40), (244, 232, 200))
SIGN_FOX = ("FOX", (46, 38, 30), (248, 210, 96))
SIGN_GROVE = ("THE GROVE", (58, 48, 96), (230, 190, 240))
SIGN_DELI = ("DELI", (58, 76, 56), (240, 236, 216))
SIGN_PIZZERIA = ("PIZZERIA", (150, 44, 40), (242, 234, 208))
SIGN_BAKERY = ("BAKERY", (170, 140, 74), (52, 38, 26))
SIGN_RECORDS = ("RECORDS", (40, 52, 74), (226, 226, 236))
# Pork steak and provel used to hang here as shop signs. Neither is a shop -
# a pork steak is what is on your neighbour's grill on a Sunday and provel is
# an argument, not a storefront. Both moved to GRUB_KINDS as power-ups. What
# replaced them are things that really do have signs out front in this city.
SIGN_FROZEN = ("FROZEN CUS", (176, 46, 44), (246, 240, 226))
SIGN_TAVERN = ("TAVERN", (58, 62, 74), (226, 226, 216))
SIGN_HARDWARE = ("HARDWARE", (74, 84, 62), (238, 234, 214))
SIGN_LAUNDRY = ("LAUNDRY", (86, 106, 122), (236, 240, 244))
SIGN_BBQ = ("BBQ", (104, 66, 38), (238, 216, 158))
# --- per-neighbourhood specifics --------------------------------------
SIGN_VOLPI = ("VOLPI", (140, 44, 40), (244, 226, 160))
SIGN_GIOIA = ("GIOIA'S", (30, 86, 48), (238, 234, 214))
SIGN_BOCCE = ("BOCCE", (74, 96, 62), (238, 234, 214))
SIGN_TIVOLI = ("TIVOLI", (46, 38, 30), (248, 210, 96))
SIGN_FITZ = ("FITZ'S", (96, 58, 34), (232, 222, 196))
SIGN_VINTAGE = ("VINTAGE", (58, 48, 96), (230, 190, 240))
SIGN_PAGEANT = ("PAGEANT", (40, 52, 74), (226, 226, 236))
SIGN_STRAUBS = ("STRAUBS", (58, 76, 56), (240, 236, 216))
SIGN_GASLIGHT = ("GASLIGHT", (46, 44, 52), (238, 214, 150))
SIGN_CAFE = ("CAFE", (92, 56, 34), (238, 214, 150))
SIGN_POWELL = ("POWELL", (58, 32, 92), (238, 210, 150))
SIGN_SHELDON = ("SHELDON", (46, 38, 30), (232, 222, 196))
SIGN_JAZZ = ("JAZZ ST L", (40, 52, 74), (226, 226, 236))
SIGN_ATOMIC = ("ATOMIC", (58, 48, 96), (240, 190, 220))
SIGN_RAINBOW = ("RAINBOW", (52, 50, 90), (240, 200, 230))
SIGN_UNION = ("UNION STN", (78, 74, 72), (232, 226, 210))
SIGN_CITYMUS = ("CITY MUSM", (150, 66, 58), (244, 230, 200))
SIGN_MCGURKS = ("MCGURK'S", (34, 74, 52), (232, 230, 214))
SIGN_MARKET = ("MARKET", (166, 96, 40), (244, 232, 200))
SIGN_MARDI = ("MARDI GRAS", (86, 52, 118), (240, 214, 110))
SIGN_SCHNUCKS = ("SCHNUCKS", (52, 66, 96), (232, 236, 244))
SIGN_MAULLS = ("MAULLS", (104, 66, 38), (238, 216, 158))
SIGN_GRBIC = ("GRBIC", (64, 76, 92), (234, 234, 226))
SIGN_CEVAPI = ("CEVAPI", (98, 70, 50), (240, 226, 190))
SIGN_BEVO = ("BEVO MILL", (140, 96, 48), (244, 232, 200))
SIGN_MERCADO = ("MERCADO", (168, 88, 44), (250, 240, 200))
SIGN_TAQUERIA = ("TAQUERIA", (48, 108, 76), (246, 238, 206))
SIGN_PANADERIA = ("PANADERIA", (188, 132, 52), (56, 40, 28))
SIGN_CASALOMA = ("CASA LOMA", (58, 54, 62), (238, 230, 214))
SIGN_TATTOO = ("TATTOO", (40, 40, 48), (226, 226, 236))
SIGN_CROWNCNDY = ("CROWN CNDY", (188, 96, 132), (250, 242, 236))
SIGN_CHURCH = ("CHURCH", (60, 58, 72), (238, 234, 220))
SIGN_BEAUTY = ("BEAUTY", (128, 64, 108), (248, 236, 240))
SIGN_LIQUOR = ("LIQUOR", (120, 48, 44), (246, 230, 190))

# --- signs for the neighbourhoods the old coarse map could not tell apart ---
SIGN_LANDING = ("LANDING", (96, 84, 66), (238, 226, 198))
SIGN_COBBLES = ("COBBLES", (78, 72, 68), (226, 220, 206))
SIGN_MORGAN = ("MORGAN ST", (70, 66, 78), (232, 228, 214))
SIGN_MUNY = ("THE MUNY", (58, 48, 96), (244, 226, 160))
SIGN_FREEZOO = ("FREE ZOO", (48, 96, 66), (240, 238, 216))
SIGN_ARTMUS = ("ART MUSEUM", (110, 104, 92), (244, 240, 226))
SIGN_JEWELBOX = ("JEWEL BOX", (62, 96, 74), (236, 244, 226))
SIGN_BOATHOUSE = ("BOATHOUSE", (72, 88, 116), (232, 240, 246))
SIGN_DOGTOWN = ("DOGTOWN", (30, 96, 56), (240, 236, 214))
SIGN_PARADE = ("PARADE", (34, 88, 52), (244, 232, 176))
SIGN_PUB = ("PUB", (46, 72, 54), (232, 228, 210))
SIGN_CLIMATRON = ("CLIMATRON", (48, 104, 92), (226, 244, 238))
SIGN_SHAWS = ("SHAW'S", (58, 96, 62), (238, 240, 218))
SIGN_ORCHIDS = ("ORCHIDS", (108, 66, 118), (246, 230, 244))
SIGN_NURSERY = ("NURSERY", (66, 100, 60), (236, 242, 214))
SIGN_TOWERGRV = ("TOWER GRV", (62, 92, 58), (238, 240, 216))
SIGN_RUINS = ("THE RUINS", (120, 114, 96), (242, 236, 216))
SIGN_FARMERS = ("FARMERS", (150, 112, 52), (246, 238, 206))
SIGN_PALMHOUSE = ("PALM HOUSE", (70, 104, 78), (234, 244, 224))
SIGN_MOKABES = ("MOKABE'S", (92, 64, 104), (242, 228, 246))
SIGN_WATERTWR = ("WATER TWR", (140, 132, 110), (246, 240, 220))
SIGN_MANSION = ("MANSION", (86, 62, 58), (240, 226, 208))
SIGN_LAFAYETTE = ("LAFAYETTE", (98, 70, 116), (244, 230, 246))
SIGN_IRONWORK = ("IRONWORK", (54, 52, 58), (226, 224, 216))
SIGN_LEMP = ("LEMP", (92, 46, 44), (240, 220, 196))
SIGN_BREWERY = ("BREWERY", (146, 92, 44), (248, 234, 196))
SIGN_CLYDES = ("CLYDESDALE", (110, 66, 40), (244, 230, 200))
SIGN_VENICE = ("VENICE", (120, 60, 130), (248, 228, 246))
SIGN_GUS = ("GUS'S", (156, 108, 48), (250, 238, 208))
SIGN_BEADS = ("BEADS", (110, 62, 140), (248, 216, 120))
SIGN_BOWLING = ("BOWLING", (58, 68, 110), (236, 238, 248))
SIGN_SOUTHTOWN = ("SOUTHTOWN", (86, 76, 62), (238, 232, 212))
SIGN_BUREK = ("BUREK", (104, 84, 60), (244, 232, 206))
SIGN_MILL = ("THE MILL", (140, 96, 48), (246, 234, 204))
SIGN_FRANCIS = ("FRANCIS PK", (56, 92, 62), (236, 240, 216))
SIGN_PARISH = ("PARISH", (66, 62, 84), (238, 234, 220))
SIGN_VIDEPOCHE = ("VIDE POCHE", (78, 70, 90), (238, 232, 220))
SIGN_BLUESCITY = ("BLUES CITY", (44, 62, 100), (238, 240, 250))
SIGN_IVORY = ("IVORY", (140, 132, 118), (246, 242, 228))
SIGN_SUMNER = ("SUMNER", (64, 60, 96), (242, 236, 220))
SIGN_ANNIEM = ("ANNIE M.", (128, 70, 110), (250, 238, 242))
SIGN_BARBER = ("BARBER", (52, 68, 104), (240, 240, 248))
SIGN_SOULFOOD = ("SOUL FOOD", (128, 76, 40), (248, 232, 198))
SIGN_OLDNORTH = ("OLD NORTH", (110, 68, 54), (242, 226, 202))
SIGN_HYDEPARK = ("HYDE PARK", (74, 88, 62), (238, 240, 216))
SIGN_GROCERY = ("GROCERY", (60, 84, 68), (236, 238, 218))
SIGN_CLAYTON = ("CLAYTON", (74, 80, 96), (236, 240, 246))
SIGN_BANK = ("BANK", (56, 62, 76), (232, 234, 240))
SIGN_WASHAVE = ("WASH AVE", (72, 68, 80), (234, 230, 240))
SIGN_LOFTS = ("LOFTS", (86, 80, 74), (236, 232, 222))
SIGN_BILLIKEN = ("BILLIKEN", (58, 46, 92), (244, 226, 160))
SIGN_BASILICA = ("BASILICA", (72, 92, 118), (246, 238, 210))
SIGN_LEFTBANK = ("LEFT BANK", (66, 74, 92), (238, 236, 224))
SIGN_CHASE = ("THE CHASE", (94, 80, 62), (244, 236, 212))
SIGN_EUCLID = ("EUCLID", (88, 70, 96), (242, 232, 240))
SIGN_BLUEBERRY = ("BLUEBERRY", (52, 58, 118), (238, 236, 250))
SIGN_CHUCKB = ("CHUCK B", (40, 44, 62), (242, 224, 120))
SIGN_TROLLEY = ("TROLLEY", (108, 62, 50), (242, 228, 202))
SIGN_WALKFAME = ("WALK FAME", (58, 52, 46), (246, 220, 120))
SIGN_MOBAKING = ("MO BAKING", (166, 130, 66), (56, 40, 26))
SIGN_URBANCHES = ("URBAN CH", (72, 96, 68), (238, 240, 216))
SIGN_CINCO = ("CINCO", (176, 96, 44), (250, 240, 202))
SIGN_WELLSTON = ("WELLSTON", (92, 78, 66), (238, 230, 214))

# Twenty-four neighbourhoods, not eleven. The eleven-way split still did real
# violence to the map, and it showed up as signs hanging in the wrong city:
# 'south' alone was 30.6% of the whole map - Tower Grove AND Shaw AND Dutchtown
# AND Bevo AND Carondelet AND St. Louis Hills AND Lafayette Square, plus the
# overflow from Forest Park and Union Station, all drawing shop signs from one
# eleven-item bag. The Botanical Garden came back 'grove', so Manchester Ave
# nightlife signage hung round Shaw's Garden; City Museum came back 'south', so
# a downtown loft block advertised Ted Drewes and Bevo Mill; half of Cherokee
# Street came back 'soulard', so McGurk's hung on Cherokee.
#
# HOOD_REGIONS is a priority-ordered list of (col0, row0, col1, row1, hood),
# inclusive, first match wins - which is far easier to assert against a
# landmark footprint than a ladder of ifs, and test_smoke does exactly that.
HOOD_REGIONS = (
    # --- the river and downtown -------------------------------------------
    (82, 26, 99, 55, 'riverfront'),    # Laclede's Landing, the Arch grounds
    (50, 24, 62, 43, 'grand'),         # Grand Center, Midtown, SLU
    (54, 26, 81, 50, 'downtown'),      # Washington Ave, the ballpark, the lofts
    # --- the central corridor ---------------------------------------------
    (31, 24, 49, 43, 'cwe'),           # Central West End, Euclid, the Basilica
    (8, 24, 30, 43, 'forestpark'),     # Forest Park itself and its ring
    (0, 10, 26, 23, 'loop'),           # the Delmar Loop, University City
    (0, 0, 7, 8, 'lambert'),            # compressed airport / North County annex
    (8, 0, 26, 9, 'wellsgoodfellow'),   # city neighborhood, east of Wellston
    (43, 0, 57, 14, 'fairground'),      # Fairground Park and O'Fallon
    (63, 0, 85, 14, 'collegehill'),     # College Hill and the standpipes
    (0, 0, 26, 9, 'wellston'),         # Wells-Goodfellow, Wellston
    (27, 0, 62, 23, 'ville'),          # The Ville, Fairground, JeffVanderLou
    (63, 0, 99, 25, 'oldnorth'),       # Old North, Hyde Park, College Hill
    (0, 24, 7, 62, 'west'),            # Clayton, Richmond Heights, Maplewood
    # --- the near south ----------------------------------------------------
    (28, 44, 40, 54, 'shaw'),          # Shaw: Henry Shaw's garden is in it
    (24, 44, 45, 54, 'grove'),         # The Grove, Forest Park Southeast
    (18, 55, 37, 68, 'hill'),          # The Hill
    (8, 44, 23, 62, 'dogtown'),        # Dogtown, Clayton-Tamm
    (44, 44, 53, 58, 'comptonhts'),    # Compton Heights, the water tower
    (54, 51, 62, 65, 'lafayette'),     # Lafayette Square
    (63, 51, 99, 64, 'soulard'),       # Soulard, the market, Mardi Gras
    (50, 74, 71, 85, 'cherokee'),      # Cherokee Street, Gravois Park
    (59, 65, 99, 79, 'bentonpark'),    # Benton Park, the brewery, Lemp
    (38, 53, 58, 73, 'towergrove'),    # Tower Grove Park and Tower Grove South
    # --- the deep south ----------------------------------------------------
    (38, 74, 49, 88, 'southampton'),   # Southampton, Princeton Heights
    (24, 69, 49, 99, 'bevo'),          # Bevo Mill, Little Bosnia, Dutchtown
    (0, 63, 23, 99, 'sthills'),        # St. Louis Hills, Francis Park
    (50, 80, 99, 99, 'carondelet'),    # Carondelet, Patch, Holly Hills
)
HOOD_FALLBACK = 'bevo'

#: What the city calls each one out loud. Shown when you cross a boundary.
HOOD_NAMES = {
    'lambert': "LAMBERT AIRPORT",
    'riverfront': "LACLEDE'S LANDING",
    'downtown': "DOWNTOWN",
    'grand': "GRAND CENTER",
    'cwe': "CENTRAL WEST END",
    'forestpark': "FOREST PARK",
    'loop': "THE DELMAR LOOP",
    'wellston': "WELLSTON",
    'wellsgoodfellow': "WELLS-GOODFELLOW",
    'fairground': "FAIRGROUND",
    'collegehill': "COLLEGE HILL",
    'ville': "THE VILLE",
    'oldnorth': "OLD NORTH",
    'west': "CLAYTON",
    'shaw': "SHAW",
    'grove': "THE GROVE",
    'hill': "THE HILL",
    'dogtown': "DOGTOWN",
    'comptonhts': "COMPTON HEIGHTS",
    'lafayette': "LAFAYETTE SQUARE",
    'soulard': "SOULARD",
    'cherokee': "CHEROKEE STREET",
    'bentonpark': "BENTON PARK",
    'towergrove': "TOWER GROVE",
    'southampton': "SOUTHAMPTON",
    'bevo': "BEVO MILL",
    'sthills': "ST. LOUIS HILLS",
    'carondelet': "CARONDELET",
}


def hood_at(col, row):
    """Which neighbourhood a tile is in, first match wins."""
    for (c0, r0, c1, r1, hood) in HOOD_REGIONS:
        if c0 <= col <= c1 and r0 <= row <= r1:
            return hood
    return HOOD_FALLBACK


def hood_name(hood):
    return HOOD_NAMES.get(hood, hood.upper())


def police_jurisdiction_at(col, row):
    """The compressed western city line: Skinker separates city and county."""
    return 'county' if col < CITY_LIMIT_COL and row < 63 else 'city'


HOOD_SIGNS = {
    'lambert': (SIGN_CAFE, SIGN_HARDWARE, SIGN_BBQ, SIGN_GROCERY,
                SIGN_TAVERN, SIGN_SCHNUCKS),
    # The Loop: theatres, records, vintage, Fitz's bottling its own root beer,
    # Chuck Berry on the Walk of Fame, and a trolley nobody will stop bringing up
    'loop': (SIGN_TIVOLI, SIGN_PAGEANT, SIGN_FITZ, SIGN_VINTAGE, SIGN_RECORDS,
             SIGN_TATTOO, SIGN_CAFE, SIGN_BLUEBERRY, SIGN_CHUCKB, SIGN_TROLLEY,
             SIGN_WALKFAME),
    # Wells-Goodfellow / Wellston: corner stores, churches, the old loop
    'wellston': (SIGN_WELLSTON, SIGN_CHURCH, SIGN_GROCERY, SIGN_BARBER,
                 SIGN_LIQUOR, SIGN_BEAUTY, SIGN_BBQ),
    'wellsgoodfellow': (SIGN_CHURCH, SIGN_GROCERY, SIGN_BARBER,
                        SIGN_LIQUOR, SIGN_BEAUTY, SIGN_BBQ),
    'fairground': (SIGN_CHURCH, SIGN_GROCERY, SIGN_BARBER,
                   SIGN_BEAUTY, SIGN_BBQ),
    'collegehill': (SIGN_CHURCH, SIGN_GROCERY, SIGN_BARBER,
                    SIGN_LIQUOR, SIGN_BBQ),
    # Clayton and the inner county: banks, coffee, a Straub's
    'west': (SIGN_CLAYTON, SIGN_BANK, SIGN_CAFE, SIGN_BAKERY, SIGN_STRAUBS,
             SIGN_SCHNUCKS, SIGN_TAVERN),
    # Central West End: limestone, mansard, Euclid, the Basilica's mosaics
    'cwe': (SIGN_STRAUBS, SIGN_GASLIGHT, SIGN_CAFE, SIGN_BAKERY, SIGN_TAVERN,
            SIGN_BASILICA, SIGN_LEFTBANK, SIGN_CHASE, SIGN_EUCLID),
    # Forest Park: everything in it is free, which locals will tell you
    'forestpark': (SIGN_MUNY, SIGN_FREEZOO, SIGN_ARTMUS, SIGN_JEWELBOX,
                   SIGN_BOATHOUSE, SIGN_CAFE),
    # Grand Center: the Fox, Powell, the Sheldon, Jazz St. Louis, SLU
    'grand': (SIGN_FOX, SIGN_POWELL, SIGN_SHELDON, SIGN_JAZZ, SIGN_CAFE,
              SIGN_BILLIKEN),
    # The Grove: Manchester, converted industrial storefronts, Urban Chestnut
    'grove': (SIGN_GROVE, SIGN_ATOMIC, SIGN_RAINBOW, SIGN_TAVERN, SIGN_TATTOO,
              SIGN_URBANCHES),
    # Shaw: Henry Shaw's garden, and the nurseries that grew up around it
    'shaw': (SIGN_CLIMATRON, SIGN_SHAWS, SIGN_ORCHIDS, SIGN_NURSERY,
             SIGN_CAFE, SIGN_BAKERY, SIGN_TAVERN),
    # Downtown: Washington Ave lofts, the oyster bar, Union Station, City Museum
    'downtown': (SIGN_OYSTER, SIGN_SLINGERS, SIGN_UNION, SIGN_CITYMUS,
                 SIGN_LAUNDRY, SIGN_BODEGA, SIGN_IMOS, SIGN_WASHAVE, SIGN_LOFTS),
    # Laclede's Landing: cobblestones, warehouses, the riverboats
    'riverfront': (SIGN_LANDING, SIGN_COBBLES, SIGN_MORGAN, SIGN_TAVERN,
                   SIGN_OYSTER),
    # Soulard: McGurk's, the market since 1779, Mardi Gras, Gus's pretzels
    'soulard': (SIGN_MCGURKS, SIGN_MARKET, SIGN_MARDI, SIGN_OYSTER,
                SIGN_TAVERN, SIGN_BODEGA, SIGN_GUS, SIGN_BEADS),
    # Benton Park: the brewery, the Clydesdales, Lemp, the Venice Cafe
    'bentonpark': (SIGN_BREWERY, SIGN_CLYDES, SIGN_LEMP, SIGN_VENICE,
                   SIGN_TAVERN, SIGN_BODEGA),
    # Lafayette Square: the oldest park west of the Mississippi, and its iron
    'lafayette': (SIGN_LAFAYETTE, SIGN_IRONWORK, SIGN_MANSION, SIGN_CAFE,
                  SIGN_TAVERN),
    # Compton Heights: the water tower, and the mansions behind the private
    'comptonhts': (SIGN_WATERTWR, SIGN_MANSION, SIGN_CAFE, SIGN_CHURCH,
                   SIGN_HARDWARE),
    # The Hill: delis, ravioli, Volpi, Gioia's, bocce, Missouri Baking
    'hill': (SIGN_DELI, SIGN_PIZZERIA, SIGN_BAKERY, SIGN_RAVIOLI, SIGN_VOLPI,
             SIGN_GIOIA, SIGN_BOCCE, SIGN_MOBAKING),
    # Dogtown: the parade that locals insist is the real one, and the pubs
    'dogtown': (SIGN_DOGTOWN, SIGN_PARADE, SIGN_PUB, SIGN_TAVERN, SIGN_PARISH,
                SIGN_HARDWARE),
    # Tower Grove: the park, the Ruins, the farmers market, Mokabe's
    'towergrove': (SIGN_TOWERGRV, SIGN_RUINS, SIGN_FARMERS, SIGN_PALMHOUSE,
                   SIGN_MOKABES, SIGN_CAFE, SIGN_TAVERN),
    # Cherokee: antiques at the east end, mercados and Cinco at the west
    'cherokee': (SIGN_ANTIQUES, SIGN_MERCADO, SIGN_TAQUERIA, SIGN_PANADERIA,
                 SIGN_CASALOMA, SIGN_TATTOO, SIGN_CINCO, SIGN_RECORDS),
    # The Ville: Sumner, Annie Malone, the churches, the barber shops
    'ville': (SIGN_SUMNER, SIGN_ANNIEM, SIGN_BARBER, SIGN_SOULFOOD,
              SIGN_CHURCH, SIGN_BEAUTY, SIGN_BBQ, SIGN_LIQUOR),
    # Old North: Crown Candy since 1913, and the corner groceries
    'oldnorth': (SIGN_CROWNCNDY, SIGN_CROWN, SIGN_OLDNORTH, SIGN_HYDEPARK,
                 SIGN_GROCERY, SIGN_CHURCH, SIGN_BBQ),
    # Southampton / Princeton Heights: Ted Drewes on Chippewa, bowling, bungalows
    'southampton': (SIGN_CUSTARD, SIGN_FROZEN, SIGN_BOWLING, SIGN_SOUTHTOWN,
                    SIGN_HARDWARE, SIGN_SCHNUCKS, SIGN_IMOS),
    # Bevo: the windmill, and Little Bosnia around it
    'bevo': (SIGN_BEVO, SIGN_MILL, SIGN_GRBIC, SIGN_CEVAPI, SIGN_BUREK,
             SIGN_TAVERN, SIGN_HARDWARE, SIGN_MAULLS),
    # St. Louis Hills: Ted Drewes, Francis Park, the parish, the bowling alley
    'sthills': (SIGN_CUSTARD, SIGN_FRANCIS, SIGN_PARISH, SIGN_BOWLING,
                SIGN_SCHNUCKS, SIGN_HARDWARE, SIGN_IMOS),
    # Carondelet: Vide Poche, Blues City Deli, the Ivory Triangle
    'carondelet': (SIGN_VIDEPOCHE, SIGN_BLUESCITY, SIGN_IVORY, SIGN_TAVERN,
                   SIGN_CHURCH, SIGN_BBQ, SIGN_HARDWARE),
}
HOOD_HOUSES = {
    'lambert': ('flat_front', 'gable_brick', 'shotgun'),
    'loop': ('mansard', 'mansard', 'painted_lady', 'gable_brick'),
    'wellston': ('gable_brick', 'shotgun', 'flat_front', 'gable_brick'),
    'wellsgoodfellow': ('gable_brick', 'shotgun', 'flat_front', 'gable_brick'),
    'fairground': ('gable_brick', 'mansard', 'shotgun', 'gable_brick'),
    'collegehill': ('gable_brick', 'flat_front', 'shotgun', 'mansard'),
    'west': ('mansard', 'painted_lady', 'gable_brick'),
    'cwe': ('mansard', 'mansard', 'painted_lady', 'gable_brick'),
    'forestpark': ('mansard', 'painted_lady', 'gable_brick'),
    'grand': ('mansard', 'gable_brick', 'painted_lady'),
    'grove': ('gable_brick', 'gable_brick', 'shotgun', 'mansard'),
    'shaw': ('gable_brick', 'mansard', 'painted_lady', 'gable_brick'),
    'downtown': ('mansard', 'mansard', 'gable_brick', 'painted_lady'),
    'riverfront': ('flat_front', 'gable_brick', 'mansard'),
    'soulard': ('flat_front', 'gable_brick', 'gable_brick', 'mansard', 'shotgun'),
    'bentonpark': ('flat_front', 'gable_brick', 'shotgun', 'mansard'),
    'lafayette': ('painted_lady', 'painted_lady', 'mansard', 'gable_brick'),
    'comptonhts': ('mansard', 'painted_lady', 'gable_brick'),
    'hill': ('flat_front', 'flat_front', 'shotgun', 'shotgun', 'gable_brick',
             'gable_brick', 'mansard'),
    'dogtown': ('flat_front', 'shotgun', 'gable_brick', 'gable_brick'),
    'towergrove': ('gable_brick', 'painted_lady', 'mansard', 'flat_front'),
    'cherokee': ('flat_front', 'gable_brick', 'painted_lady', 'shotgun', 'mansard'),
    'ville': ('gable_brick', 'mansard', 'gable_brick', 'shotgun'),
    'oldnorth': ('gable_brick', 'mansard', 'gable_brick', 'shotgun', 'flat_front'),
    'southampton': ('flat_front', 'flat_front', 'gable_brick', 'shotgun'),
    'bevo': ('flat_front', 'shotgun', 'gable_brick', 'flat_front'),
    'sthills': ('gable_brick', 'gable_brick', 'flat_front', 'mansard'),
    'carondelet': ('flat_front', 'shotgun', 'gable_brick', 'gable_brick'),
}

# Masonry is regional too. The generated facade sprite and the exposed roof
# beneath it now agree on the district instead of every block drawing from one
# citywide bag of brick.
HOOD_BRICKS = {
    'lambert': (CITY_BRICKS[3], CITY_BRICKS[4], CITY_BRICKS[6]),
    'loop': (CITY_BRICKS[0], CITY_BRICKS[2], CITY_BRICKS[4]),
    'wellston': (CITY_BRICKS[0], CITY_BRICKS[1], CITY_BRICKS[6]),
    'wellsgoodfellow': (CITY_BRICKS[0], CITY_BRICKS[1], CITY_BRICKS[6]),
    'fairground': (CITY_BRICKS[0], CITY_BRICKS[1], CITY_BRICKS[3]),
    'collegehill': (CITY_BRICKS[0], CITY_BRICKS[3], CITY_BRICKS[6]),
    'west': (CITY_BRICKS[0], CITY_BRICKS[2], CITY_BRICKS[4], CITY_BRICKS[4]),
    'cwe': (CITY_BRICKS[4], CITY_BRICKS[4], CITY_BRICKS[2], CITY_BRICKS[0]),
    'forestpark': (CITY_BRICKS[4], CITY_BRICKS[2], CITY_BRICKS[4]),
    'grand': (CITY_BRICKS[4], CITY_BRICKS[2], CITY_BRICKS[0]),
    'grove': (CITY_BRICKS[0], CITY_BRICKS[5], CITY_BRICKS[6]),
    'shaw': (CITY_BRICKS[0], CITY_BRICKS[2], CITY_BRICKS[4]),
    'downtown': (CITY_BRICKS[1], CITY_BRICKS[2], CITY_BRICKS[4], CITY_BRICKS[6]),
    'riverfront': (CITY_BRICKS[3], CITY_BRICKS[1], CITY_BRICKS[6]),
    'soulard': (CITY_BRICKS[0], CITY_BRICKS[0], CITY_BRICKS[1], CITY_BRICKS[5]),
    'bentonpark': (CITY_BRICKS[0], CITY_BRICKS[1], CITY_BRICKS[5]),
    'lafayette': (CITY_BRICKS[0], CITY_BRICKS[4], CITY_BRICKS[6]),
    'comptonhts': (CITY_BRICKS[4], CITY_BRICKS[2], CITY_BRICKS[0]),
    'hill': (CITY_BRICKS[0], CITY_BRICKS[2], CITY_BRICKS[5]),
    'dogtown': (CITY_BRICKS[0], CITY_BRICKS[5], CITY_BRICKS[3]),
    'towergrove': (CITY_BRICKS[0], CITY_BRICKS[2], CITY_BRICKS[4]),
    'cherokee': (CITY_BRICKS[0], CITY_BRICKS[1], CITY_BRICKS[5], CITY_BRICKS[6]),
    'ville': (CITY_BRICKS[0], CITY_BRICKS[1], CITY_BRICKS[3], CITY_BRICKS[6]),
    'oldnorth': (CITY_BRICKS[0], CITY_BRICKS[1], CITY_BRICKS[3], CITY_BRICKS[6]),
    'southampton': (CITY_BRICKS[0], CITY_BRICKS[2], CITY_BRICKS[3]),
    'bevo': (CITY_BRICKS[0], CITY_BRICKS[3], CITY_BRICKS[5]),
    'sthills': (CITY_BRICKS[2], CITY_BRICKS[0], CITY_BRICKS[4]),
    'carondelet': (CITY_BRICKS[0], CITY_BRICKS[3], CITY_BRICKS[5]),
}

# The native 64px atlas only ships twelve district families. A neighbourhood
# the atlas has no art for borrows the closest one it does, so a new hood
# still gets live sprites at one address in three instead of dropping back to
# nothing but procedural storefronts.
HOOD_ATLAS_ALIAS = {
    'lambert': 'west',
    'wellston': 'north', 'forestpark': 'cwe', 'shaw': 'south',
    'wellsgoodfellow': 'north', 'fairground': 'north', 'collegehill': 'north',
    'riverfront': 'downtown', 'bentonpark': 'soulard', 'lafayette': 'soulard',
    'comptonhts': 'cwe', 'dogtown': 'hill', 'towergrove': 'south',
    'ville': 'north', 'oldnorth': 'north', 'southampton': 'south',
    'bevo': 'south', 'sthills': 'south', 'carondelet': 'south',
}

# Native 64px hard-pixel atlas. It is authored at runtime size by
# tools/build_pixel_facades.py: no high-resolution source art, resampling, or
# antialiased alpha enters the game. Downtown receives two extra roof types.
BUILDING_ATLAS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'sprites',
    'stlouis-neighborhood-buildings-pixel.png')
BUILDING_ATLAS_PATHS = (BUILDING_ATLAS_PATH,)  # compatibility / test reference
BUILDING_ATLAS_COLUMNS = 6
BUILDING_ATLAS_ROWS = 4
BUILDING_ATLAS_CELL_SIZE = 64
BUILDING_ATLAS_HOODS = (
    'soulard', 'soulard', 'hill', 'hill', 'cwe', 'cwe',
    'loop', 'loop', 'grand', 'grand', 'grove', 'grove',
    'cherokee', 'cherokee', 'north', 'north', 'south', 'south',
    'downtown', 'downtown', 'west', 'west', 'downtown', 'downtown',
)
NEIGHBORHOOD_BUILDING_SPRITES = collections.defaultdict(list)


def bake_neighborhood_building_sprites():
    """Slice the native-resolution atlas into district-specific 64px sprites."""
    if NEIGHBORHOOD_BUILDING_SPRITES:
        return
    for atlas_path in BUILDING_ATLAS_PATHS:
        try:
            atlas = pygame.image.load(atlas_path).convert_alpha()
        except (pygame.error, OSError):
            continue
        expected = (BUILDING_ATLAS_COLUMNS * BUILDING_ATLAS_CELL_SIZE,
                    BUILDING_ATLAS_ROWS * BUILDING_ATLAS_CELL_SIZE)
        if atlas.get_size() != expected:
            continue
        for index, hood in enumerate(BUILDING_ATLAS_HOODS):
            col = index % BUILDING_ATLAS_COLUMNS
            row = index // BUILDING_ATLAS_COLUMNS
            cell = atlas.subsurface(pygame.Rect(
                col * BUILDING_ATLAS_CELL_SIZE,
                row * BUILDING_ATLAS_CELL_SIZE,
                BUILDING_ATLAS_CELL_SIZE,
                BUILDING_ATLAS_CELL_SIZE)).copy()
            if cell.get_bounding_rect(min_alpha=1).width <= 0:
                continue
            NEIGHBORHOOD_BUILDING_SPRITES[hood].append(cell)
    # Neighbourhoods the atlas has no family for borrow their nearest cousin.
    for hood, source in HOOD_ATLAS_ALIAS.items():
        if not NEIGHBORHOOD_BUILDING_SPRITES.get(hood):
            NEIGHBORHOOD_BUILDING_SPRITES[hood] = list(
                NEIGHBORHOOD_BUILDING_SPRITES.get(source, ()))


def hood_pick_sign(col, row, n):
    pool = HOOD_SIGNS[hood_at(col, row)]
    return pool[(n >> 7) % len(pool)]


def hood_pick_house(col, row, n):
    pool = HOOD_HOUSES[hood_at(col, row)]
    return pool[(n >> 9) % len(pool)]


def _lm_solid_arch(lx, ly, lw, lh):
    """The Arch is a *vertical* catenary: in plan it is two leg footings and a
    span 600ft overhead. Only the footings block you - everything between and
    under the legs is open ground you can walk straight through. Columns and
    base row track the fractions lm__bake_arch() draws the legs at, so the
    collision sits exactly under the steel."""
    leg_a = max(1, int(round(0.145 * lw)))
    leg_b = min(lw - 2, int(round(0.775 * lw)))
    base = int(round(0.575 * lh))
    return lx in (leg_a, leg_b) and base - 1 <= ly <= base


def _lm_solid_stadium(lx, ly, lw, lh):
    """Busch Stadium as a real bowl: the seating ring is a hard wall, the field
    inside is open, and a single gate corridor due south is the only way in.
    Ellipse centre/radii match lm__bake_stadium()'s art."""
    cx, cy = 0.355 * lw, 0.50 * lh
    rx, ry = max(1.0, 0.335 * lw), max(1.0, 0.465 * lh)
    dx = (lx + 0.5 - cx) / rx
    dy = (ly + 0.5 - cy) / ry
    v = dx * dx + dy * dy
    if v > 1.0 or v < 0.40:
        return False                      # outside the bowl, or on the field
    # the one gate: a 3-tile corridor running south from the field to the street
    if abs(lx - int(round(cx))) <= 1 and (ly + 0.5) >= cy:
        return False
    return True


def _lm_solid_district(lx, ly, lw, lh):
    """A city block you can actually use, and one that still reads as a dense
    neighbourhood: a walkable apron outside, a band of buildings, an alley,
    a second band on the bigger blocks, and a small courtyard in the middle
    where the drop marker lands. Every band has a gate through the middle of
    all four sides, so there is always a legible way in and nothing is sealed.
    """
    if lw < 6 or lh < 6:
        return False                      # too small for a ring; leave it open
    # Depth from the nearest edge puts every tile on exactly one ring, so the
    # gates of one ring can never accidentally punch a hole in another's corner.
    depth = min(lx, ly, lw - 1 - lx, lh - 1 - ly)
    if depth == 0:
        return False                      # approach apron
    if depth == 1:                        # outer building band
        if (ly == 1 or ly == lh - 2) and abs(lx - lw // 2) <= 1:
            return False                  # north / south gate
        if (lx == 1 or lx == lw - 2) and abs(ly - lh // 2) <= 1:
            return False                  # east / west gate
        return True
    if depth == 2:
        return False                      # the alley between the two bands
    if depth == 3 and lw >= 8 and lh >= 8:
        if (ly == 3 or ly == lh - 4) and lx == lw // 2:
            return False
        if (lx == 3 or lx == lw - 4) and ly == lh // 2:
            return False
        return True
    return False                          # inner courtyard


def _lm_solid_blocks(lx, ly, lw, lh):
    """Fine-grained blocks with streets between them.

    The four district bakers (the CWE, The Hill, the Loop, Grand Center) draw
    their OWN street grid on a roughly two-tile pitch - rows of houses with a
    street between and a rear alley behind. Under the old "district" layout
    what you saw and what you could walk through disagreed completely: the art
    showed continuous rows, the collision was a ring with a hollow courtyard.
    This matches the collision to the picture.
    """
    if lx == 0 or ly == 0 or lx == lw - 1 or ly == lh - 1:
        return False                      # approach apron all the way round
    if ly % 2 == 0:
        return False                      # the street between the rows
    if lx % 3 == 0:
        return False                      # cross streets
    return True


#: the brewery yard grid, shared by the collision mask and the art so that
#: what you can walk on and what you can see agree. Every third column and row
#: is a yard lane; the outer ring is the approach apron off the street.
BREWERY_LANE = 3


def brewery_is_block(lx, ly, lw, lh):
    """True where the brewery has a building on it."""
    if lx <= 0 or ly <= 0 or lx >= lw - 1 or ly >= lh - 1:
        return False
    return lx % BREWERY_LANE != 0 and ly % BREWERY_LANE != 0


def brewery_blocks(lw, lh):
    """The campus as whole block rects, in tiles: (col, row, w, h)."""
    out = []
    row = 1
    while row < lh - 1:
        if row % BREWERY_LANE == 0:
            row += 1
            continue
        span_h = 0
        while (row + span_h < lh - 1
               and (row + span_h) % BREWERY_LANE != 0):
            span_h += 1
        col = 1
        while col < lw - 1:
            if col % BREWERY_LANE == 0:
                col += 1
                continue
            span_w = 0
            while (col + span_w < lw - 1
                   and (col + span_w) % BREWERY_LANE != 0):
                span_w += 1
            out.append((col, row, span_w, span_h))
            col += span_w
        row += span_h
    return tuple(out)


def _lm_solid_brewery(lx, ly, lw, lh):
    """Anheuser-Busch: brick blocks with yard streets you drive between.

    It used to fall through to the default district layout - a ring of walls
    round a hollow courtyard - while the art drew 140 red-brick roofs edge to
    edge across the whole footprint. So the middle of the brewery was open
    ground that looked exactly like roofs, and you crossed it not knowing
    whether you were on a street or on top of the Brew House. Same mask now
    feeds both.
    """
    return brewery_is_block(lx, ly, lw, lh)


def _lm_solid_garden(lx, ly, lw, lh):
    """A botanical garden: open ground, and glasshouses you cannot walk through.

    Everything else - the beds, the allees, the lawns - is walkable, and the
    Japanese garden's lake is cut in separately as real water by the feature
    pass, so you have to go round it rather than jog across it.
    """
    # The Climatron: a two-tile dome, and the thing you can see from off the map.
    cx, cy = lw * 0.42, lh * 0.34
    if abs(lx + 0.5 - cx) <= 1.0 and abs(ly + 0.5 - cy) <= 1.0:
        return True
    house_row = int(lh * 0.72)
    # The Linnean House: a long, low glass barrel along the south walk.
    if ly == house_row and 1 <= lx <= max(1, int(lw * 0.38)):
        return True
    # Tower Grove House, Shaw's own place, off at the east end.
    if lx == lw - 2 and ly == house_row:
        return True
    return False


def _lm_solid_tower(lx, ly, lw, lh):
    """A single tower in an open lawn: one solid tile, dead centre.

    You can walk right round it, which is what makes a water tower useful to
    navigate by - it reads from every direction and never blocks a route.
    """
    return lx == lw // 2 and ly == lh // 2


def _lm_solid_strip(lx, ly, lw, lh):
    """A commercial strip: two rows of shopfronts with the street between
    them, and a cross street punched through every few blocks."""
    if ly == lh // 2:
        return False                      # the street itself
    if lx % 5 == 0:
        return False                      # cross streets
    return 0 < ly < lh - 1


def _lm_solid_trainshed(lx, ly, lw, lh):
    """Union Station: the headhouse across the north with one arched entry,
    then the train shed - rows of columns you walk between - and a plaza on
    the south side where the Meeting of the Waters fountain sits."""
    if ly == 0:
        return not (abs(lx - lw // 2) <= 1)   # the great arched entry
    if ly >= lh - 1:
        return False                          # the plaza
    return lx % 3 == 0                        # shed columns


def _lm_solid_market(lx, ly, lw, lh):
    """Soulard Market: open-sided sheds with aisles you walk down.

    Open since 1779, and the point of it is that you go *through* it - so the
    solid mass is the shed bars and everything between them is walkable, with
    a street apron north and south.
    """
    if ly == 0 or ly == lh - 1:
        return False                      # street apron, both sides
    if lx == 0 or lx == lw - 1:
        return False                      # walk round the ends
    return ly % 2 == 1                    # shed bars; aisles between them


def _lm_solid_drivein(lx, ly, lw, lh):
    """A walk-up stand: the building is a bar across the back, the front is an
    open lot you queue and park in. Side aprons stay open so you can get round."""
    if lx == 0 or lx == lw - 1:
        return False
    return ly < max(1, lh - 2)


def _lm_solid_airport(lx, ly, lw, lh):
    """A terminal bar beside an otherwise open apron and runway."""
    if lx == 2 or ly == 2:
        return False
    return 1 <= lx < lw - 1 and ly in (4, 5)


_LM_SOLID = {
    "airport": _lm_solid_airport,
    "arch": _lm_solid_arch,
    "stadium": _lm_solid_stadium,
    "district": _lm_solid_district,
    "drivein": _lm_solid_drivein,
    "market": _lm_solid_market,
    "tower": _lm_solid_tower,
    "strip": _lm_solid_strip,
    "trainshed": _lm_solid_trainshed,
    "garden": _lm_solid_garden,
    "blocks": _lm_solid_blocks,
    "brewery": _lm_solid_brewery,
}


def _landmark_tile(lx, ly, lw, lh, kind, name, color):
    """Build one tile of a landmark.

    Landmarks used to be solid rectangles, which walled them off completely:
    landmark_at() reads the tile under the player's centre, so a fully
    collidable footprint made every building landmark impossible to reach or
    discover. Each landmark now carries a named layout (LANDMARK_LAYOUT) whose
    solid mass matches its baked art and always leaves a legible way in.
    """
    if kind == "park":
        return {'type': TILE_PARK, 'collidable': False, 'landmark': name, 'color': color}

    layout = LANDMARK_LAYOUT.get(name, LANDMARK_DEFAULT_LAYOUT)
    if _LM_SOLID[layout](lx, ly, lw, lh):
        return {'type': TILE_BUILDING, 'collidable': True, 'landmark': name, 'color': color}
    return {'type': TILE_PLAZA, 'collidable': False, 'landmark': name,
            'color': _blend(color, COLOR_SIDEWALK, 0.55)}


GAME_MAP = build_map()


def _compute_reachable():
    """Flood-fill the walkable tile graph outward from the street network.

    Anything this does not reach is a sealed pocket - a courtyard with no gate,
    the hollow inside a solid mass - and nothing the game *places* (a job
    marker, a spawn, a weapon pickup) may land there. A drop marker inside a
    sealed block is the single most infuriating bug this map can produce: the
    objective reads as reachable and simply is not.
    """
    reach = [[False] * MAP_TILES_W for _ in range(MAP_TILES_H)]
    start = None
    for r in range(MAP_TILES_H):
        for c in range(MAP_TILES_W):
            tile = GAME_MAP[r][c]
            if tile['type'] == TILE_ROAD and not tile['collidable']:
                start = (c, r)
                break
        if start:
            break
    if start is None:
        return reach
    reach[start[1]][start[0]] = True
    stack = [start]
    while stack:
        c, r = stack.pop()
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nc, nr = c + dc, r + dr
            if not (0 <= nc < MAP_TILES_W and 0 <= nr < MAP_TILES_H):
                continue
            if reach[nr][nc] or GAME_MAP[nr][nc]['collidable']:
                continue
            reach[nr][nc] = True
            stack.append((nc, nr))
    return reach


WALK_REACHABLE = _compute_reachable()


def is_reachable(x, y):
    """True if a pixel position sits on open ground connected to the streets."""
    c, r = int(x) // TILE_SIZE, int(y) // TILE_SIZE
    if 0 <= r < MAP_TILES_H and 0 <= c < MAP_TILES_W:
        return WALK_REACHABLE[r][c]
    return False


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


def rect_hits_tag(rect, tag):
    """True when a collider overlaps a map tile carrying a route tag."""
    start_col = max(0, rect.left // TILE_SIZE)
    end_col = min(MAP_TILES_W - 1, rect.right // TILE_SIZE)
    start_row = max(0, rect.top // TILE_SIZE)
    end_row = min(MAP_TILES_H - 1, rect.bottom // TILE_SIZE)
    for row in range(start_row, end_row + 1):
        for col in range(start_col, end_col + 1):
            tile = GAME_MAP[row][col]
            if tile.get(tag) and rect.colliderect(
                    pygame.Rect(col * TILE_SIZE, row * TILE_SIZE,
                                TILE_SIZE, TILE_SIZE)):
                return True
    return False


def pedestrian_ground_is_clear(rect):
    """True when a pedestrian's whole collider is on reachable ground.

    Pedestrian spawners normally choose an open tile centre, but the live pool
    is long-lived: knockback, streamed repositioning and replacement spawns all
    reuse the same objects and can expose a bad placement immediately.  Keep a
    stricter, named invariant than ``not is_blocked`` so a walker can never be
    accepted on a building tile (and visually read as standing on its roof).
    """
    rect = pygame.Rect(rect)
    if (rect.left < 0 or rect.top < 0
            or rect.right > MAP_WIDTH or rect.bottom > MAP_HEIGHT):
        return False
    if is_blocked(rect) or not is_reachable(rect.centerx, rect.centery):
        return False
    start_col = rect.left // TILE_SIZE
    end_col = (rect.right - 1) // TILE_SIZE
    start_row = rect.top // TILE_SIZE
    end_row = (rect.bottom - 1) // TILE_SIZE
    for row in range(start_row, end_row + 1):
        for col in range(start_col, end_col + 1):
            if GAME_MAP[row][col]['type'] == TILE_BUILDING:
                return False
    return True


def sight_blocked(ax, ay, bx, by):
    """True when a building stands between two world points.

    A cheap DDA walk of the tile grid: step along the segment at half a tile
    and stop at the first collidable tile. This is what turns the police from
    omniscient trackers into something you can actually hide from, so it runs
    once per cop per step and has to stay cheap - no allocation, no sqrt in
    the loop beyond the single length.
    """
    dx, dy = bx - ax, by - ay
    dist = math.hypot(dx, dy)
    if dist < 1.0:
        return False
    steps = int(dist / (TILE_SIZE * 0.5)) + 1
    sx, sy = dx / steps, dy / steps
    x, y = ax, ay
    for _ in range(steps):
        x += sx
        y += sy
        col, row = int(x) // TILE_SIZE, int(y) // TILE_SIZE
        if not (0 <= col < MAP_TILES_W and 0 <= row < MAP_TILES_H):
            return True
        if GAME_MAP[row][col]['collidable']:
            return True
    return False


def in_cover(x, y):
    """True when this point is somewhere you could plausibly duck out of view.

    Not the middle of a four-lane street. Anything walkable that is *not* road
    and has a solid tile within one tile of it: a gangway between two flats,
    an alley behind a block, the treeline of a park, under the Arch's span.
    """
    col, row = int(x) // TILE_SIZE, int(y) // TILE_SIZE
    if not (0 <= col < MAP_TILES_W and 0 <= row < MAP_TILES_H):
        return False
    here = GAME_MAP[row][col]
    if here['collidable'] or here['type'] == TILE_ROAD:
        return False
    for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
        c2, r2 = col + dc, row + dr
        if 0 <= c2 < MAP_TILES_W and 0 <= r2 < MAP_TILES_H:
            t = GAME_MAP[r2][c2]
            if t['collidable'] or t['type'] == TILE_PARK:
                return True
    return False


def walk_path(from_pt, to_pt, limit=1400):
    """Breadth-first walkable route between two world points, as waypoints.

    Whiskers are not enough for someone on foot. A cop with a two-flat due
    west of him and the player beyond it will slide along it, back off, try
    the other way, and oscillate at a fixed distance forever - measured at a
    steady 270px for twenty-five seconds. A block is only ever a few tiles
    across, so an actual search over the tile grid is both cheap and correct.

    Returns a list of world points from just-after the start to the goal, or
    None if the goal is unreachable inside `limit` expanded tiles. Callers
    re-run this every half second or so, not every step.
    """
    sc, sr = int(from_pt[0]) // TILE_SIZE, int(from_pt[1]) // TILE_SIZE
    gc, gr = int(to_pt[0]) // TILE_SIZE, int(to_pt[1]) // TILE_SIZE
    if not (0 <= sc < MAP_TILES_W and 0 <= sr < MAP_TILES_H):
        return None
    if not (0 <= gc < MAP_TILES_W and 0 <= gr < MAP_TILES_H):
        return None
    if (sc, sr) == (gc, gr):
        return [to_pt]
    if GAME_MAP[gr][gc]['collidable']:
        return None
    came = {(sc, sr): None}
    queue = collections.deque(((sc, sr),))
    seen = 0
    found = False
    while queue and seen < limit:
        cur = queue.popleft()
        seen += 1
        if cur == (gc, gr):
            found = True
            break
        cc, cr = cur
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nc, nr = cc + dc, cr + dr
            if not (0 <= nc < MAP_TILES_W and 0 <= nr < MAP_TILES_H):
                continue
            if (nc, nr) in came or GAME_MAP[nr][nc]['collidable']:
                continue
            came[(nc, nr)] = cur
            queue.append((nc, nr))
    if not found:
        return None
    out = []
    node = (gc, gr)
    while node is not None and node != (sc, sr):
        out.append((node[0] * TILE_SIZE + TILE_SIZE // 2,
                    node[1] * TILE_SIZE + TILE_SIZE // 2))
        node = came[node]
    out.reverse()
    if out:
        out[-1] = tuple(to_pt)        # finish on the real point, not its tile
    return out


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
        if not WALK_REACHABLE[r][c]:
            continue                       # never spawn inside a sealed pocket
        return c * TILE_SIZE + TILE_SIZE // 2, r * TILE_SIZE + TILE_SIZE // 2
    return MAP_WIDTH // 2, MAP_HEIGHT // 2


def ring_spawn_near(ax, ay, road_only=False, rmin=POP_RESPAWN_MIN,
                    rmax=POP_RESPAWN_MAX, heading=None, spread=POP_AHEAD_SPREAD):
    """A reachable tile centre in an annulus around (ax, ay).

    Used to seed and to recycle the street population, so people and traffic
    are always where the player actually is rather than smeared over a map
    that is 99.4% off-screen. Returns None if nothing suitable was found.

    `heading` biases the ring toward the way the player is travelling. Driving
    at full speed crosses the whole keep radius in about a second, so a
    uniform ring wastes half its budget behind you on entities you will never
    meet; weighting it forward is what keeps traffic in the windscreen.
    """
    for _ in range(28):
        if heading is None:
            ang = random.uniform(0, math.tau)
        else:
            ang = heading + random.uniform(-spread, spread)
        dist = random.uniform(rmin, rmax)
        col = int(ax + math.cos(ang) * dist) // TILE_SIZE
        row = int(ay + math.sin(ang) * dist) // TILE_SIZE
        if not (2 <= col < MAP_TILES_W - 2 and 2 <= row < MAP_TILES_H - 2):
            continue
        tile = GAME_MAP[row][col]
        if tile['collidable'] or not WALK_REACHABLE[row][col]:
            continue
        if road_only and tile['type'] != TILE_ROAD:
            continue
        return col * TILE_SIZE + TILE_SIZE // 2, row * TILE_SIZE + TILE_SIZE // 2
    return None


def free_point_near(x, y, w, h, max_rings=6, require_reachable=True):
    """Nearest position to (x, y) where a w x h rect does not overlap anything.

    Used anywhere the game has to *place* something rather than move it:
    getting out of a car, dropping a job marker on a landmark, respawning.
    Returns None when there is genuinely no room within max_rings tiles, so
    callers can refuse the action instead of stuffing the player into a wall.

    require_reachable also rejects open ground that is walled off from the
    street network, so nothing is ever placed somewhere you cannot walk to.
    """
    probe = pygame.Rect(0, 0, w, h)
    step = TILE_SIZE // 2
    for ring in range(max_rings + 1):
        # ring 0 is the requested spot itself; later rings spiral outward in
        # half-tile steps, nearest candidates first.
        if ring == 0:
            candidates = ((0, 0),)
        else:
            d = ring * step
            candidates = ((0, -d), (0, d), (-d, 0), (d, 0),
                          (-d, -d), (d, -d), (-d, d), (d, d))
        for ox, oy in candidates:
            probe.center = (int(x + ox), int(y + oy))
            if probe.left < 0 or probe.top < 0 or probe.right > MAP_WIDTH or probe.bottom > MAP_HEIGHT:
                continue
            if is_blocked(probe):
                continue
            if require_reachable and not is_reachable(probe.centerx, probe.centery):
                continue
            return probe.centerx, probe.centery
    return None


def pedestrian_point_near(x, y, max_rings=6):
    """Resolve a candidate into a safe 14px pedestrian placement."""
    probe = pygame.Rect(0, 0, 14, 14)
    probe.center = (int(x), int(y))
    if pedestrian_ground_is_clear(probe):
        return probe.center
    spot = free_point_near(x, y, probe.width, probe.height,
                           max_rings=max_rings, require_reachable=True)
    if spot is None:
        return None
    probe.center = spot
    return probe.center if pedestrian_ground_is_clear(probe) else None


def random_pedestrian_point():
    """Return a valid pedestrian point, with a deterministic exhaustive fallback."""
    for _ in range(32):
        spot = pedestrian_point_near(*random_open_spawn(), max_rings=4)
        if spot is not None:
            return spot
    probe = pygame.Rect(0, 0, 14, 14)
    for row in range(1, MAP_TILES_H - 1):
        for col in range(1, MAP_TILES_W - 1):
            probe.center = (col * TILE_SIZE + TILE_SIZE // 2,
                            row * TILE_SIZE + TILE_SIZE // 2)
            if pedestrian_ground_is_clear(probe):
                return probe.center
    raise RuntimeError("map contains no valid pedestrian ground")


def landmark_rect(entry):
    """Pixel-space footprint of a LANDMARKS tuple."""
    lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
    return pygame.Rect(lx * TILE_SIZE, ly * TILE_SIZE, lw * TILE_SIZE, lh * TILE_SIZE)


def landmark_dropoff_point(entry):
    """A standable point inside (or just outside) a landmark's footprint.

    Job markers have to sit somewhere the player can physically reach, and
    several landmark footprints are solid building mass in the middle, so this
    walks the footprint for open ground before falling back to the perimeter.
    """
    rect = landmark_rect(entry)
    spot = free_point_near(rect.centerx, rect.centery, 24, 24, max_rings=4)
    if spot is not None:
        return spot
    # Middle is solid: try the four edge midpoints, then give up to the centre.
    for px, py in ((rect.centerx, rect.top - TILE_SIZE // 2),
                   (rect.centerx, rect.bottom + TILE_SIZE // 2),
                   (rect.left - TILE_SIZE // 2, rect.centery),
                   (rect.right + TILE_SIZE // 2, rect.centery)):
        spot = free_point_near(px, py, 24, 24, max_rings=3)
        if spot is not None:
            return spot
    return rect.center




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
cars_TRANS_AM_BODY = (30, 29, 32)
cars_TRANS_AM_GOLD = (206, 154, 54)
cars_METROBUS_BLUE = (42, 82, 142)
cars_METROBUS_RED = (184, 48, 48)
cars_METROBUS_ROUTE = (242, 184, 52)
cars_CITY_SERVICE_ORANGE = (218, 104, 32)
cars_CITY_SERVICE_LETTERING = (24, 22, 20)
cars_MUDFOOT_WHITE = (230, 232, 224)
cars_MUDFOOT_RED = (196, 48, 44)
cars_CART_PANEL = (240, 232, 204)
cars_CART_INK = (170, 38, 42)
cars_CART_BAG_COLORS = ((226, 190, 54), (92, 146, 72),
                        (232, 126, 54), (118, 88, 156))

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
    'trans_am': dict(L=34, H=18, nose=2, tail=2, hood=11, ws=3, roof=5, rw=3,
                      win_inset=4, wheel_len=5, axle_f=5, axle_r=5, trans_am=True),
    'police': dict(L=35, H=18, nose=2, tail=1, hood=8, ws=4, roof=8, rw=4,
                   win_inset=4, wheel_len=5, axle_f=5, axle_r=5, police=True),
}

cars_VARIANTS = ['sedan', 'coupe', 'van', 'pickup', 'taxi', 'trans_am', 'police']

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
    'trans_am': cars_TRANS_AM_BODY,
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
    if spec.get('trans_am'):
        # Gold hood bird and a split T-top: three pixels each, but at game
        # scale they are the unmistakable South City parking-lot silhouette.
        hc = (g['ws_x1'] + g['nose_x']) // 2
        cy = (g['by0'] + g['by1']) // 2
        cars__put(grid, hc, cy, cars_TRANS_AM_GOLD)
        cars__put(grid, hc - 1, cy - 1, cars_TRANS_AM_GOLD)
        cars__put(grid, hc - 1, cy + 1, cars_TRANS_AM_GOLD)
        tc = (g['roof_x0'] + g['roof_x1']) // 2
        cars__fill_rect(grid, tc, g['win_y0'], tc, g['win_y1'], cars_OUTLINE)

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
    'street_sweeper':(44, 22),
    'forestry_truck':(46, 22),
    'bus':           (54, 20),
    'metrobus_70':   (54, 20),
    'box_truck':     (44, 20),
    'mudfoot':       (46, 30),
    'grocery_cart':  (52, 26),
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
        # St. Louis refuse trucks are rolling city equipment, not anonymous
        # green dumpsters. Safety orange makes the silhouette legible in
        # traffic; a real pixel-wordmark on both flanks still reads after the
        # game's normal sprite scale and at every cardinal heading.
        cab = cars_CITY_SERVICE_ORANGE
        box = cars_CITY_SERVICE_ORANGE
        cars__put_r(grid, 2, top, 33, bot, box)
        for x in range(5, 33, 4):
            cars__put_r(grid, x, top + 1, x, bot - 1, cars__darker(box, 0.25))
        cars__put_r(grid, 1, top + 3, 3, bot - 3, cars__darker(box, 0.45))   # loader
        cars__put_r(grid, 34, top, 46, bot, cab)
        cars__put_r(grid, 44, top + 2, 45, bot - 2, cars_GLASS_FRONT)
        cars__put_r(grid, 36, top + 3, 39, bot - 3, cars__lighter(cab))      # door

        glyphs = {
            'C': ("###", "#..", "#..", "#..", "###"),
            'I': ("###", ".#.", ".#.", ".#.", "###"),
            'T': ("###", ".#.", ".#.", ".#.", ".#."),
            'Y': ("#.#", "#.#", ".#.", ".#.", ".#."),
        }
        for y0 in (top + 2, bot - 6):
            for i, letter in enumerate("CITY"):
                for gy, bits in enumerate(glyphs[letter]):
                    for gx, bit in enumerate(bits):
                        if bit == '#':
                            cars__put(grid, 7 + i * 4 + gx, y0 + gy,
                                      cars_CITY_SERVICE_LETTERING)
    elif kind == 'street_sweeper':
        orange = cars_CITY_SERVICE_ORANGE
        ink = cars_CITY_SERVICE_LETTERING
        # Short forward cab, low debris hopper, curb brush and water tank.
        cars__put_r(grid, 3, top + 3, 28, bot - 2, orange)
        cars__put_r(grid, 29, top, 42, bot, orange)
        cars__put_r(grid, 39, top + 2, 41, bot - 2, cars_GLASS_FRONT)
        cars__put_r(grid, 31, top + 3, 34, bot - 3, cars__lighter(orange))
        cars__put_r(grid, 5, top + 5, 25, top + 7, ink)
        cars__put_r(grid, 5, bot - 7, 25, bot - 5, ink)
        # Twin yellow rotary brushes protrude at the kerb edges.
        brush = (224, 178, 54)
        for bx in (14, 23):
            cars__put_r(grid, bx, 0, bx + 5, 3, ink)
            cars__put_r(grid, bx + 1, 0, bx + 4, 1, brush)
            cars__put_r(grid, bx, H - 4, bx + 5, H - 1, ink)
            cars__put_r(grid, bx + 1, H - 2, bx + 4, H - 1, brush)
        # Black municipal lettering remains readable at normal sprite scale.
        for y0 in (top + 1, bot - 5):
            cars__put_r(grid, 8, y0, 10, y0 + 4, ink)
            cars__put_r(grid, 14, y0, 16, y0 + 4, ink)
            cars__put_r(grid, 8, y0, 16, y0, ink)
            cars__put_r(grid, 8, y0 + 4, 16, y0 + 4, ink)
    elif kind == 'forestry_truck':
        orange = cars_CITY_SERVICE_ORANGE
        ink = cars_CITY_SERVICE_LETTERING
        # Forestry utility pickup with a chip box, ladder rack and beacon.
        cars__put_r(grid, 3, top + 2, 28, bot - 2, orange)
        cars__put_r(grid, 29, top, 44, bot, orange)
        cars__put_r(grid, 41, top + 2, 43, bot - 2, cars_GLASS_FRONT)
        cars__put_r(grid, 32, top + 3, 36, bot - 3, cars__lighter(orange))
        cars__put_r(grid, 4, top + 1, 27, top + 2, ink)
        cars__put_r(grid, 4, bot - 2, 27, bot - 1, ink)
        for rx in (7, 23):
            cars__put_r(grid, rx, top, rx + 1, bot, ink)
        cars__put_r(grid, 7, top, 25, top, ink)
        cars__put_r(grid, 7, bot, 25, bot, ink)
        # CITY bars plus a tiny green tree badge distinguish it from refuse.
        for y0 in (top + 4, bot - 7):
            cars__put_r(grid, 9, y0, 20, y0 + 1, ink)
            cars__put_r(grid, 9, y0 + 3, 20, y0 + 4, ink)
        tree = (58, 104, 54)
        cars__put_r(grid, 24, top + 5, 27, top + 8, tree)
        cars__put_r(grid, 25, bot - 8, 27, bot - 5, tree)
        cars__put_r(grid, 34, 0, 38, 1, cars_METROBUS_ROUTE)
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
    elif kind == 'metrobus_70':
        body = (218, 220, 216)
        glass = (92, 126, 154)
        dark = (24, 28, 36)
        cars__put_r(grid, 2, top, L - 2, bot, body)
        # Bi-State/Metro blue with a thin red slash, visible from either curb.
        cars__put_r(grid, 3, top + 3, L - 7, top + 5, cars_METROBUS_BLUE)
        cars__put_r(grid, 3, bot - 5, L - 7, bot - 3, cars_METROBUS_BLUE)
        cars__put_r(grid, 24, top + 3, 25, top + 5, cars_METROBUS_RED)
        cars__put_r(grid, 24, bot - 5, 25, bot - 3, cars_METROBUS_RED)
        for x in range(5, L - 11, 6):
            cars__put_r(grid, x, top + 1, x + 3, top + 2, glass)
            cars__put_r(grid, x, bot - 2, x + 3, bot - 1, glass)
        cars__put_r(grid, L - 7, top + 2, L - 3, bot - 2, cars_GLASS_FRONT)
        # Roof route box: an actual 3x5 "70", not just a yellow rectangle.
        cars__put_r(grid, 20, 7, 32, 13, dark)
        seven = ("###", "..#", ".#.", ".#.", ".#.")
        zero = ("###", "#.#", "#.#", "#.#", "###")
        for ox, glyph in ((22, seven), (27, zero)):
            for gy, row in enumerate(glyph):
                for gx, bit in enumerate(row):
                    if bit == '#':
                        cars__put(grid, ox + gx, 8 + gy, cars_METROBUS_ROUTE)
    elif kind == 'mudfoot':
        body = (62, 78, 126)                    # period blue, no sponsor marks
        body_hi = (92, 110, 164)
        legend_white = cars_MUDFOOT_WHITE
        legend_red = cars_MUDFOOT_RED
        chassis = (40, 36, 38)
        hub = (150, 152, 148)
        # Four enormous tyres, with a small lifted pickup floating above them.
        for ax in (7, 32):
            cars__put_r(grid, ax, 1, ax + 8, 8, cars_TIRE)
            cars__put_r(grid, ax, H - 9, ax + 8, H - 2, cars_TIRE)
            cars__put_r(grid, ax + 3, 3, ax + 5, 6, hub)
            cars__put_r(grid, ax + 3, H - 7, ax + 5, H - 4, hub)
        cars__put_r(grid, 6, 12, 40, 17, chassis)
        cars__put_r(grid, 10, 8, 38, 21, body)
        cars__put_r(grid, 11, 9, 24, 20, cars__darker(body, 0.35))  # pickup bed
        cars__put_r(grid, 26, 9, 38, 20, body_hi)                   # cab
        cars__put_r(grid, 35, 11, 38, 18, cars_GLASS_FRONT)
        cars__put_r(grid, 27, 11, 30, 18, cars_GLASS_REAR)
        cars__put_r(grid, 38, 10, 43, 19, body)                     # hood
        # High-contrast period show-truck livery. The old all-blue pickup read
        # as ordinary traffic until the post-entry toast explained the joke.
        cars__put_r(grid, 10, 9, 24, 10, legend_white)
        cars__put_r(grid, 10, 19, 24, 20, legend_white)
        cars__put_r(grid, 31, 9, 37, 10, legend_white)
        cars__put_r(grid, 31, 19, 37, 20, legend_white)
        cars__put_r(grid, 39, 13, 43, 16, legend_white)
        cars__put_r(grid, 40, 14, 42, 15, legend_red)
    elif kind == 'grocery_cart':
        red = (176, 48, 48)
        metal = (178, 180, 176)
        dark = (70, 66, 68)
        # Long push handle, wire basket, child seat and undercarriage. It is
        # unmistakably the parade cart without copying a store wordmark.
        cars__put_r(grid, 1, 4, 3, H - 5, red)
        cars__put_r(grid, 2, 4, 10, 5, red)
        cars__put_r(grid, 2, H - 6, 10, H - 5, red)
        cars__put_r(grid, 9, 3, 44, H - 4, metal)
        cars__put_r(grid, 11, 5, 42, H - 6, None)
        for x in range(12, 43, 6):
            cars__put_r(grid, x, 4, x, H - 5, red)
        for y in range(7, H - 6, 5):
            cars__put_r(grid, 10, y, 43, y, red)
        cars__put_r(grid, 13, 8, 21, H - 9, (206, 198, 172))       # child seat
        # Two cream parade placards and a load of bright grocery bags make the
        # enormous vehicle read as a promotional cart before it is entered.
        panel = cars_CART_PANEL
        ink = cars_CART_INK
        for y0 in (4, H - 9):
            cars__put_r(grid, 23, y0, 39, y0 + 4, panel)
            # A chunky supermarket-S mark survives rotation and 1.45x scaling.
            cars__put_r(grid, 25, y0 + 1, 31, y0 + 1, ink)
            cars__put_r(grid, 25, y0 + 2, 27, y0 + 2, ink)
            cars__put_r(grid, 29, y0 + 2, 31, y0 + 2, ink)
            cars__put_r(grid, 25, y0 + 3, 31, y0 + 3, ink)
        for (x, y), color in zip(((24, 10), (29, 13), (35, 10), (39, 14)),
                                 cars_CART_BAG_COLORS):
            cars__put_r(grid, x, y, x + 3, y + 3, color)
        cars__put_r(grid, 10, H // 2 - 1, 47, H // 2 + 1, dark)
        cars__put_r(grid, 44, 6, 49, H - 7, red)                    # basket nose
    else:  # box_truck
        box = (210, 206, 198)
        cab = (108, 114, 124)
        cars__put_r(grid, 2, top, 32, bot, box)
        for x in range(6, 32, 6):
            cars__put_r(grid, x, top + 1, x, bot - 1, cars__darker(box, 0.12))
        cars__put_r(grid, 33, top + 1, 43, bot - 1, cab)
        cars__put_r(grid, 41, top + 2, 42, bot - 2, cars_GLASS_FRONT)

    if kind not in ('mudfoot', 'grocery_cart'):
        for ax in (5, L - 10):                 # wheel nubs on both flanks
            for x in range(ax, ax + 5):
                grid[0][x] = cars_TIRE
                grid[H - 1][x] = cars_TIRE
    elif kind == 'grocery_cart':
        for ax in (15, 39):
            cars__put_r(grid, ax, 0, ax + 3, 2, cars_TIRE)
            cars__put_r(grid, ax, H - 3, ax + 3, H - 1, cars_TIRE)
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


def cars_clydesdale_sprite():
    """The Budweiser hitch: eight horses, two abreast, and a red beer wagon
    with a Dalmatian on the seat.

    It runs on a fixed line through Soulard like the light rail does, at a
    walk, and it is exactly as wide as the lane. You cannot make it move. You
    cannot go round it. Honking does nothing, because it is eight horses.
    """
    L, H = 118, 26
    grid = [[None] * L for _ in range(H)]
    hide = (108, 64, 38)
    hide_dk = (74, 42, 24)
    hide_lt = (138, 90, 56)
    sock = (236, 230, 218)
    mane = (52, 34, 22)
    tack = (38, 32, 36)
    wagon = (152, 40, 38)
    wagon_dk = (108, 26, 26)
    gold = (200, 162, 62)
    cream = (228, 220, 198)

    def horse(hx, hy):
        # barrel, with a lit top line and a shadowed belly
        cars__put_r(grid, hx, hy + 2, hx + 11, hy + 6, hide)
        cars__put_r(grid, hx + 1, hy + 2, hx + 10, hy + 2, hide_lt)
        cars__put_r(grid, hx, hy + 6, hx + 11, hy + 6, hide_dk)
        cars__put_r(grid, hx, hy + 3, hx + 1, hy + 5, hide_dk)       # haunch
        # neck rising forward, then the head
        cars__put_r(grid, hx + 11, hy + 1, hx + 13, hy + 5, hide)
        cars__put_r(grid, hx + 12, hy + 1, hx + 13, hy + 2, hide_lt)
        cars__put_r(grid, hx + 14, hy + 1, hx + 16, hy + 3, hide)    # head
        grid[hy + 2][hx + 16] = hide_dk                              # muzzle
        cars__put_r(grid, hx + 11, hy, hx + 13, hy, mane)            # mane
        grid[hy][hx + 1] = mane                                      # tail root
        cars__put_r(grid, hx - 1, hy + 1, hx - 1, hy + 4, mane)      # tail
        # four legs, and the feathered white feet Clydesdales are known for
        for lx in (hx + 2, hx + 4, hx + 8, hx + 10):
            grid[hy + 7][lx] = hide_dk
            grid[hy + 8][lx] = sock
        cars__put_r(grid, hx + 4, hy + 1, hx + 9, hy + 1, tack)      # harness

    for pair in range(4):
        hx = 32 + pair * 21
        horse(hx, 0)
        horse(hx, 13)

    # the wagon: red, gold-trimmed, cream side panel, tall cartwheels
    cars__put_r(grid, 2, 4, 28, H - 5, wagon)
    cars__put_r(grid, 2, 4, 28, 5, wagon_dk)
    cars__put_r(grid, 4, 8, 25, H - 9, cream)
    cars__put_r(grid, 4, 8, 25, 8, gold)
    cars__put_r(grid, 4, H - 9, 25, H - 9, gold)
    cars__put_r(grid, 2, H - 6, 28, H - 5, wagon_dk)
    for wx in (6, 23):
        cars__put_r(grid, wx, 3, wx + 1, H - 4, (54, 46, 42))
        cars__put_r(grid, wx, 3, wx + 1, 3, (86, 76, 68))
    cars__put_r(grid, 26, 9, 28, 13, (58, 52, 56))        # the driver
    cars__put_r(grid, 26, 14, 28, 16, cream)              # and the Dalmatian
    grid[15][27] = (34, 32, 34)
    grid[16][26] = (34, 32, 34)
    # traces from the wagon to the lead pair
    cars__put_r(grid, 29, 5, 31, 5, tack)
    cars__put_r(grid, 29, H - 7, 31, H - 7, tack)

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
    if key in ('taxi', 'police', 'trans_am'):
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
    # Local-only types (w=0): streamed in on their turf, never sprinkled over
    # the entire metro area like a theme-park costume.
    'cards_fan':  dict(w=0, gait=0.92, acc=('cap', 'foam_finger'), cap=(176, 42, 44),
                       sh=(_MAROON, _CARDS, _BRICKY),   pa=(_PA_DENIM, _PA_KHAKI, _PA_CARDS)),
    'hoosier':    dict(w=0, gait=0.88, acc=('mullet', 'tallboy'), hair='brown',
                       sh=(_OFFWHT, _GREYBLUE, _MAROON), pa=(_PA_DENIM, _PA_DENIM, _PA_BLACK)),
    'trick_or_treater': dict(w=0, gait=0.82, acc=('hood',),
                             sh=(_MUSTARD, _PURPLE, _TEAL),
                             pa=(_PA_BLACK, _PA_NAVY, _PA_GREY)),
}

peds_COP_KEY = 'cop#0'
PEDS_PLAYER_KEYS = tuple(f'player#{i}' for i in range(len(CHARACTER_LOOKS)))
PEDS_PLAYER_KEY = PEDS_PLAYER_KEYS[0]
peds__SPECIAL = {
    'cop':    dict(gait=1.0, acc=('cap',), cap=(40, 48, 78),
                   sh=(_NAVY,), pa=(_PA_NAVY,)),
    'player': dict(gait=1.0, acc=('jacket',),
                   sh=(_MAROON, _TEAL, _MUSTARD, _PURPLE, _OFFWHT, _CARDS),
                   pa=(_PA_DENIM, _PA_BLACK, _PA_BROWN, _PA_GREY, _PA_DENIM, _PA_CARDS)),
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
    elif arch == 'cards_fan':
        accent, accent_d = (190, 42, 46), (112, 28, 30)
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
    if 'mullet' in acc:
        # Business in front, enough party in back to survive a 16px sprite.
        if view == 'back':
            peds__r(g, 4, 6 + o, 11, 10 + o, M_HAIR)
            peds__r(g, 5, 10 + o, 10, 11 + o, M_HAIR)
        elif view == 'side':
            peds__r(g, 4, 6 + o, 7, 10 + o, M_HAIR)
        else:
            peds__r(g, 4, 6 + o, 5, 9 + o, M_HAIR)
            peds__r(g, 10, 6 + o, 11, 9 + o, M_HAIR)
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
    if 'foam_finger' in acc and view != 'back':
        peds__r(g, 12, 7 + o, 14, 12 + o, M_ACC)
        peds__r(g, 13, 4 + o, 14, 7 + o, M_ACC)
        peds__p(g, 12, 5 + o, M_ACC)
    if 'tallboy' in acc and view != 'back':
        peds__r(g, 1, 13 + o, 3, 18 + o, M_LT)
        peds__r(g, 1, 15 + o, 3, 16 + o, M_ACC)
        peds__r(g, 1, 13 + o, 3, 13 + o, M_OUT)
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
    keys += [peds_COP_KEY] + list(PEDS_PLAYER_KEYS)
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
    ">": "#....|.#...|..#..|...#.|..#..|.#...|#....",
    "\"": ".#.#.|.#.#.|.#.#.|.....|.....|.....|.....",
    # +, ( and ) were missing: live strings like "+5" and "(x2 streak)" were
    # rendering as filled MISSING boxes in-game. The callout / pop-number layer
    # leans on "+" hard, so they earn their place.
    "+": ".....|..#..|..#..|#####|..#..|..#..|.....",
    "(": "..#..|.#...|.#...|.#...|.#...|.#...|..#..",
    ")": "..#..|...#.|...#.|...#.|...#.|...#.|..#..",
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


def hud_draw_stars(surf, wanted, x, y, ticks, scale=1, slots=6, blink=False):
    """Wanted stars. Lit = gold (newest one pulses), unlit = dim outline.

    `blink` drops the lit stars out four times a second. That is the single
    most important piece of feedback in a chase and the game had no signal for
    it at all: solid means somebody has eyes on you, blinking means they are
    searching and the clock is running - run, or hold your breath.
    """
    if not hud__baked:
        hud_bake()
    slots = max(0, min(6, int(slots)))
    wanted = max(0, min(slots, int(wanted)))
    if wanted <= 0:
        return (0, 0)          # nothing is happening; do not draw grey noise
    # Newest star breathes between base gold and a hot near-white gold.
    k = 0.5 + 0.5 * math.sin(float(ticks) * 0.006)
    level = int(k * (hud__PULSE_STEPS - 1) + 0.5)
    step = (hud_STAR_W + hud_STAR_GAP) * scale
    dark = blink and (int(ticks) // 125) % 2 == 0
    for i in range(slots):
        px = x + i * step
        if i < wanted and not dark:
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


# --- Tile constants ---
# These used to be hand-copied literals with a "mirrored from main.py, do not
# import main" note from when this was a separate module. It is not a separate
# module any more, and the copies were a live trap: bumping TILE_SIZE or
# MAP_TILES_W at the top of the file left props/parking/traffic silently
# addressing a different grid than everything else. They are now aliases.
props_TILE_SIZE = TILE_SIZE
props_TILE_GRASS = TILE_GRASS
props_TILE_ROAD = TILE_ROAD
props_TILE_WATER = TILE_WATER
props_TILE_BUILDING = TILE_BUILDING
props_TILE_PARK = TILE_PARK
props_TILE_PLAZA = TILE_PLAZA

# Road grid: an explicit, irregular list of named streets. props_ROAD_STEP is
# only a spacing heuristic now (how often to hang a streetlight); road-ness is
# membership of props_ROAD_LINES.
props_ROAD_ORIGIN = ROAD_ORIGIN
props_ROAD_STEP = ROAD_STEP
props_ROAD_LINES = frozenset(ROAD_LINES)

# --- Muted 90s console palette ---
props_C_OUT = (18, 16, 18)            # near-black outline, matches COLOR_OUTLINE
props_C_POLE = (86, 88, 92)
props_C_POLE_DARK = (58, 60, 64)
props_C_METAL = (114, 110, 100)
props_C_METAL_DARK = (82, 78, 70)
props_C_LAMP = (214, 198, 138)        # warm bulb, not neon
props_C_LAMP_DIM = (168, 154, 104)
# St. Louis fire hydrants are chrome-yellow with a red bonnet + caps.
props_C_RED = (198, 158, 46)          # hydrant body (gold)
props_C_RED_DARK = (150, 118, 36)     # body shade
props_C_RED_LIT = (176, 58, 48)       # bonnet / side-cap red
props_C_HILL_GREEN = (38, 132, 64)
props_C_HILL_WHITE = (242, 238, 220)
props_C_HILL_RED = (202, 48, 44)
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
    'streetlight', 'hydrant', 'hydrant_hill', 'trafficlight', 'dumpster',
    'trashcan',
    'bench', 'mailbox', 'phonebooth', 'bus_stop', 'manhole', 'roadcone',
    'planter', 'newsbox', 'chainlink', 'above_pool', 'tub_madonna',
    'backyard_bbq', 'clothesline',
]

# Props that never cast a shadow (flat on the ground).
props__FLAT = frozenset(('manhole', 'above_pool'))

# Ground anchor of each sprite, measured from its top-left pixel.
props__ANCHORS = {
    'streetlight': (4, 10),
    'hydrant': (3, 7),
    'hydrant_hill': (5, 13),
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
    'chainlink': (10, 11),
    'above_pool': (11, 13),
    'tub_madonna': (5, 13),
    'backyard_bbq': (12, 15),
    'clothesline': (13, 14),
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


def props__build_hydrant_hill():
    """The Hill paints its hydrants green, white and red. Every corner. It is
    the first thing anyone from here notices about the neighbourhood, and it
    costs one extra sprite."""
    # The old 7x8 mark collapsed to a white speck at gameplay scale. A wider
    # 11x14 silhouette leaves each Italian-tricolour section several chunky
    # pixels tall while keeping the footprint tiny beside a pedestrian.
    s = props__surf(11, 14)
    props__box(s, 0, 5, 11, 5, props_C_HILL_RED)        # side caps / arms
    props__rect(s, 1, 7, 2, 1, props_C_HILL_WHITE)
    props__rect(s, 8, 7, 2, 1, props_C_HILL_WHITE)
    props__box(s, 3, 2, 5, 11, props_C_HILL_WHITE)      # central barrel
    props__rect(s, 4, 4, 1, 6, (255, 252, 236))         # hard highlight
    props__box(s, 2, 0, 7, 5, props_C_HILL_GREEN)       # green bonnet
    props__rect(s, 3, 1, 4, 1, (72, 166, 92))
    props__box(s, 2, 10, 7, 4, props_C_HILL_RED)        # broad red foot
    props__rect(s, 3, 11, 4, 1, (224, 76, 66))
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


def props__build_chainlink():
    """A single backyard fence panel. At this scale the alternating diagonals
    read more clearly than a literal wire mesh, especially while moving."""
    s = props__surf(21, 12)
    wire = (142, 146, 142)
    wire_hi = (188, 190, 178)
    # Steel posts and top/bottom rails.
    props__rect(s, 0, 0, 2, 12, props_C_METAL_DARK)
    props__rect(s, 19, 0, 2, 12, props_C_METAL_DARK)
    props__rect(s, 1, 1, 19, 1, wire_hi)
    props__rect(s, 1, 10, 19, 1, wire)
    for x in range(2, 19, 5):
        pygame.draw.line(s, wire, (x, 2), (min(x + 5, 19), 10))
        pygame.draw.line(s, wire_hi, (x, 10), (min(x + 5, 19), 2))
    return s


def props__build_above_pool():
    """The blue oval that occupies half of a South City postage-stamp yard."""
    s = props__surf(23, 14)
    pygame.draw.ellipse(s, props_C_OUT, (0, 1, 23, 13))
    pygame.draw.ellipse(s, (164, 170, 164), (1, 2, 21, 11))
    pygame.draw.ellipse(s, (48, 120, 154), (3, 3, 17, 8))
    pygame.draw.arc(s, (116, 190, 210), (4, 4, 15, 6), 0.2, 2.8, 1)
    # Tiny white ladder on the east rim.
    props__rect(s, 19, 3, 1, 8, (220, 218, 202))
    props__rect(s, 21, 4, 1, 8, (220, 218, 202))
    for y in (5, 8, 11):
        props__rect(s, 19, y, 3, 1, (220, 218, 202))
    return s


def props__build_tub_madonna():
    """A bathtub shrine: sincere, specific, and instantly South City."""
    s = props__surf(11, 14)
    stone = (210, 204, 188)
    stone_lo = (146, 140, 130)
    # Half-buried tub shell and the dark niche inside it.
    pygame.draw.ellipse(s, props_C_OUT, (0, 0, 11, 14))
    pygame.draw.ellipse(s, stone, (1, 1, 9, 12))
    pygame.draw.ellipse(s, (54, 50, 54), (3, 3, 5, 9))
    props__rect(s, 0, 10, 11, 4, stone_lo)
    props__rect(s, 1, 10, 9, 2, stone)
    # Blue robe, pale face, one gold votive pixel.
    props__rect(s, 4, 5, 3, 6, (54, 86, 146))
    props__rect(s, 5, 3, 2, 2, (220, 184, 144))
    props__rect(s, 2, 10, 1, 1, (224, 170, 58))
    return s


def props__build_backyard_bbq():
    """Kettle grill, two folding chairs and the cooler nobody is guarding."""
    s = props__surf(25, 16)
    # Weber-shaped kettle with three tiny legs and one hot coal pixel.
    pygame.draw.circle(s, props_C_OUT, (12, 6), 5)
    pygame.draw.circle(s, (66, 62, 64), (12, 6), 4)
    props__rect(s, 8, 4, 9, 1, (126, 122, 116))
    props__rect(s, 11, 10, 2, 5, props_C_METAL_DARK)
    props__rect(s, 8, 14, 3, 1, props_C_METAL_DARK)
    props__rect(s, 14, 14, 3, 1, props_C_METAL_DARK)
    props__rect(s, 12, 6, 1, 1, (212, 104, 48))
    # Mismatched folding lawn chairs: green webbing and Cardinals red.
    for x, col in ((1, (72, 116, 76)), (19, (166, 46, 46))):
        props__box(s, x, 7, 5, 6, col)
        props__rect(s, x + 1, 9, 3, 1, props_C_OUT)
        props__rect(s, x + 1, 13, 1, 3, props_C_METAL)
        props__rect(s, x + 3, 13, 1, 3, props_C_METAL)
    return s


def props__build_clothesline():
    """A yard-width line with sheets, a red towel and impossible optimism."""
    s = props__surf(27, 15)
    pole = (94, 84, 72)
    props__rect(s, 1, 1, 2, 14, pole)
    props__rect(s, 24, 1, 2, 14, pole)
    pygame.draw.line(s, (184, 178, 158), (2, 2), (25, 2), 1)
    # White sheet, blue work shirt, Cardinals towel.
    props__box(s, 5, 2, 7, 7, (218, 214, 198))
    props__rect(s, 6, 3, 5, 1, (238, 234, 218))
    props__box(s, 14, 2, 4, 6, (72, 102, 142))
    props__box(s, 20, 2, 3, 5, (174, 42, 44))
    return s


props__BUILDERS = {
    'streetlight': props__build_streetlight,
    'hydrant': props__build_hydrant,
    'hydrant_hill': props__build_hydrant_hill,
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
    'chainlink': props__build_chainlink,
    'above_pool': props__build_above_pool,
    'tub_madonna': props__build_tub_madonna,
    'backyard_bbq': props__build_backyard_bbq,
    'clothesline': props__build_clothesline,
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
    # Was `(i - origin) % step == 0`. The grid is irregular now, so the only
    # honest answer is membership of the actual line list.
    return i in props_ROAD_LINES


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

# The Hill does not leave this detail to a random clutter roll. These curb
# anchors ring the neighborhood on walkable sidewalk tiles and use the local
# green-white-red paint job.
HILL_HYDRANT_TILES = {
    (22, 52): (6, 32),
    (22, 55): (6, 32),
    (23, 51): (32, 14),
    (26, 51): (32, 14),
    (36, 58): (58, 32),
    (33, 67): (32, 58),
}

# Streetlights land on the tiles whose index along the street is 2 or 6
# mod 8: one every 4 tiles (256px), and never on a junction corner or the
# crossing itself, so every street keeps an unbroken rhythm.
props_LIGHT_PHASES = (2, 5)   # two lamps per block against ROAD_STEP 6

# Which neighbourhoods put a chainlink fence, an above-ground pool, a Mary in
# a bathtub, a kettle grill or a clothesline in the back yard. This used to
# read `district in ('hill', 'south')`, and 'south' was a single region
# covering a third of the map; when that split into real neighbourhoods the
# jokes quietly vanished from the entire south side. Named, so a test can hold
# it to the actual hood list.
props_YARD_HOODS = frozenset((
    'hill', 'dogtown', 'bevo', 'sthills', 'southampton', 'carondelet',
    'towergrove', 'cherokee', 'shaw', 'wellston', 'ville', 'oldnorth',
))
props_MISC_CHANCE = 6        # percent of eligible sidewalk tiles with clutter
props_DUMPSTER_CHANCE = 4    # percent of alley-ish sidewalk tiles
props_MANHOLE_CHANCE = 3     # percent of road tiles
props_CONE_CHANCE = 2        # percent of road tiles


def props_props_for_tile(c, r, tile_type, is_sidewalk, district=None):
    """Deterministic list of (name, offset_x, offset_y) for tile (c, r).

    Offsets are the prop's ground anchor in pixels inside the 64x64 tile.
    Most tiles return []; props are deliberately sparse (roughly 4-10 on a
    640x360 screen)."""
    if not props__BAKED:
        props_bake()

    if (c, r) in HILL_HYDRANT_TILES and is_sidewalk:
        return [props__place('hydrant_hill', *HILL_HYDRANT_TILES[(c, r)])]

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

    # --- South City postage-stamp yards ---------------------------------
    # The block generator uses non-kerbside plaza tiles for alleys and tiny
    # courtyards. They are walkable, so these stay visual-only and sparse.
    if tile_type == props_TILE_PLAZA and not is_sidewalk and district in props_YARD_HOODS:
        n = props__noise(c, r, 149)
        phase = n % 31
        if phase < 3:
            return [props__place('chainlink', 14 + ((n >> 8) % 34), 18 + ((n >> 13) % 28))]
        if phase == 6:
            return [props__place('above_pool', 18 + ((n >> 9) % 28), 22 + ((n >> 15) % 22))]
        if phase == 11:
            return [props__place('tub_madonna', 12 + ((n >> 10) % 40), 20 + ((n >> 16) % 24))]
        if phase in (15, 16):
            return [props__place('backyard_bbq', 16 + ((n >> 7) % 30), 24 + ((n >> 14) % 18))]
        if phase == 23:
            return [props__place('clothesline', 17 + ((n >> 10) % 26), 20 + ((n >> 16) % 22))]
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
    # District labels cover many unrelated buildings. Hash their roofs per
    # address; only actual single landmarks should share one roof treatment.
    style_landmark = None if landmark_name in _FABRIC_LANDMARKS else landmark_name
    key = (c, r, style_landmark)
    s = roofs__STYLE_CACHE.get(key)
    if s is not None:
        return s
    if style_landmark:
        h = roofs__name_hash(style_landmark)
        # helipad is reserved for tall downtown-ish landmarks, and rare
        if (h % 5) == 0 and roofs__is_tall(style_landmark):
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


# --- Map constants (aliases of the canonical values at the top of the file) ---
parking_TILE_SIZE = TILE_SIZE
parking_MAP_TILES_W = MAP_TILES_W
parking_MAP_TILES_H = MAP_TILES_H
parking_MAP_WIDTH = MAP_WIDTH
parking_MAP_HEIGHT = MAP_HEIGHT

parking_ROAD_ORIGIN = ROAD_ORIGIN
parking_ROAD_STEP = ROAD_STEP
# Was re-derived from origin/step, which silently disagreed with the real grid
# the moment the grid stopped being uniform. Take the actual lines.
parking_ROAD_LINES = tuple(sorted(ROAD_LINES))
parking__ROAD_SET = frozenset(parking_ROAD_LINES)

parking_WATER_COL_START = parking_MAP_TILES_W - 3       # cols 97-99 are river, unless road

parking_CAR_W = 34                              # Car collision rect, nose to tail
parking_CAR_H = 18
assert (parking_CAR_W, parking_CAR_H) == (VEHICLE_DEFAULT_W, VEHICLE_DEFAULT_H), \
    "kerb slots are sized for the default car collider"

# --- Parking layout ---
# Parked cars used to sit 14-18px off the tile centre line while the moving
# lane sits at traffic_LANE_OFFSET = 15px off the SAME line: every kerbside car
# was parked in the middle of the driving lane. Ambient traffic therefore had
# to brake to a dead stop behind each one, forever, and everything behind it
# queued up - which is where the knots of stacked cars came from. Parking now
# hugs the kerb (a 34x18 car at 23px still fits inside the 64px road tile), and
# traffic_drive() pulls out around whatever is left.
parking_KERB_OFFSET_MIN = 21        # px from the tile centre line to the car centre
parking_KERB_OFFSET_MAX = 23
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


def parking__on_asphalt(x, y, angle):
    """Every tile the parked car covers is actually paved.

    `parking_is_road_tile` is geometric - "col or row is a road line" - and
    `parking_is_legal_spot` only asks whether the rect is *blocked*. Grass is
    not blocked. So every road-line tile that the landmark pass turned into
    lawn or plaza still handed out kerb bays, which is why cars were parked on
    the Arch grounds, on the Grand Basin's apron, and in the middle of parks.
    Ask the finished map what the tile actually is.
    """
    grid = globals().get('GAME_MAP')
    if not grid:
        return parking_is_road_tile(int(x) // parking_TILE_SIZE,
                                    int(y) // parking_TILE_SIZE)
    rect = parking_car_rect(x, y, angle)
    c0 = rect.left // parking_TILE_SIZE
    c1 = (rect.right - 1) // parking_TILE_SIZE
    r0 = rect.top // parking_TILE_SIZE
    r1 = (rect.bottom - 1) // parking_TILE_SIZE
    for row in range(r0, r1 + 1):
        if not (0 <= row < parking_MAP_TILES_H):
            return False
        for col in range(c0, c1 + 1):
            if not (0 <= col < parking_MAP_TILES_W):
                return False
            if grid[row][col]['type'] != TILE_ROAD:
                return False
    return True


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
                        if not parking__on_asphalt(x, y, angle):
                            continue        # nor on lawn/water that replaced a road
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

traffic_TRAFFIC_MAX_SPEED = 3.25     # catchable on foot; unhurried on the tight grid
traffic_TRAFFIC_THROTTLE = 0.30      # cruise throttle: gentle 0.084 px/frame^2 pickup

traffic_PLAYER_MAX_SPEED = PLAYER_CAR_MAX_SPEED

traffic_LANE_OFFSET = 15.0           # px right of the road-tile centre line
traffic_LANE_MARGIN = 2.0            # px of clearance kept off a collidable kerb
traffic_LANE_OVERHANG = 6.0          # px a lane may sit outside the tile when it is open

traffic_LOOKAHEAD = 48.0             # measured: 99% of mid-block headings stay within 10deg
traffic_STEER_GAIN = 2.4
traffic_STEER_DAMP = 4.0             # damps the physics' steer_angle integrator

traffic_JUNCTION_SPEED = 2.55        # cap for driving straight through a junction
traffic_TURN_SPEED = 1.95            # a readable corner inside a 64px crossing
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

traffic_HALT_PATIENCE = 75           # frames stopped before the anti-deadlock creep
traffic_CREEP_FRAMES = 90            # how long a creep lasts
traffic_CREEP_SPEED = 1.5            # creep pace, slow enough to still read as yielding
traffic_PROBE_AHEAD = 26             # px in front of the nose checked for a wall

traffic_SEGMENT_SCAN = 18            # covers the longest irregular block plus its next junction

# --- Pulling out around a stopped obstacle --------------------------------
# A kerbside car, a wreck, a car the player rammed into the gutter: any of
# them used to stop a lane permanently, because the follow rule brakes for
# stationary traffic and nothing ever moved it. Real traffic goes around.
# When something stopped sits in the cone, the lane target shifts toward the
# centre line by up to traffic_PASS_SHIFT px and the speed floor keeps the car
# rolling, so it eases out, passes, and tucks back in.
traffic_PASS_LOOK = 78.0             # px ahead a stopped obstacle triggers a pass
traffic_PASS_SHIFT = 16.0            # px toward the centre line at full commit
traffic_PASS_RATE = 0.09             # how fast the lane target slides across
traffic_PASS_SPEED = 1.45            # speed floor while easing past something
traffic_PASS_STILL = 0.35            # px/step below which a neighbour is "stopped"

traffic_TILE_ROAD = TILE_ROAD

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
traffic__rail_gate_hold = None


def traffic_set_hooks(is_blocked_fn, game_map, tile_size, map_tiles_w, map_tiles_h,
                      road_lines, rail_gate_hold=None):
    """Inject main.py's world globals so this module stays standalone."""
    global traffic__is_blocked, traffic__MAP, traffic__TS, traffic__MW, traffic__MH
    global traffic__ROAD_LINES, traffic__LINES, traffic__rail_gate_hold
    traffic__is_blocked = is_blocked_fn
    traffic__MAP = game_map
    traffic__TS = int(tile_size)
    traffic__MW = int(map_tiles_w)
    traffic__MH = int(map_tiles_h)
    traffic__ROAD_LINES = frozenset(int(v) for v in road_lines)
    traffic__LINES = tuple(sorted(traffic__ROAD_LINES))
    traffic__rail_gate_hold = rail_gate_hold


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


def traffic__is_grid_road(col, row):
    """A road tile this cardinal-only driver can actually follow.

    The map also contains diagonal arterials. They are legitimate player roads,
    but this AI only understands named north/south and east/west corridors. A
    diagonal tile used as a spawn used to be snapped sideways to the nearest
    grid line, which could be a MetroLink cut, a plaza, or a landmark lawn.
    """
    tile = traffic__tile(col, row)
    if not (traffic__is_road(col, row)
            and (col in traffic__ROAD_LINES or row in traffic__ROAD_LINES)):
        return False
    if tile.get('chain_of_rocks'):
        return False
    # Cars may cross MetroLink at a marked grade crossing, but they must not
    # turn onto or spawn along its embedded/reserved alignment. The Loop
    # trolley is explicitly street-running on Delmar, so ordinary traffic is
    # allowed to share that road.
    rail = tile.get('rail')
    return (rail is None or rail == 'trolley'
            or bool(tile.get('rail_crossing')))


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


def traffic__lane_bounds(d, line, col, row):
    """(lo, hi) the lane coordinate may occupy without grazing a kerb.

    Car rects never rotate: a car is 34px wide in X whatever way it points, so
    a north/south lane at the full offset would graze a building that abuts the
    road.
    """
    hx, hy = traffic__DIRS[d]
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
    return lo, hi


def traffic__lane_clamped(d, line, col, row, shift=0.0):
    """Lane coordinate pulled in so the car's AABB clears a collidable kerb.

    ``shift`` is the pull-out offset used to pass a stopped obstacle; it is
    applied before the clamp, so easing around a parked car can never ease the
    car into a wall instead.  Only tightens the lane, never widens it past the
    ideal offset.
    """
    lane = traffic__lane_coord(d, line) + shift
    lo, hi = traffic__lane_bounds(d, line, col, row)
    if lo > hi:
        return traffic__centre(line)
    return min(hi, max(lo, lane))


def traffic__pass_axis(d):
    """Sign that converts a "shift right of the heading" into lane coords."""
    hx, hy = traffic__DIRS[d]
    return hx if hy == 0 else -hy


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
        'pass': 0.0,            # current pull-out offset, lane coords
        'safe_pos': None,       # last centre known to be on the cardinal road grid
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

    if traffic__is_grid_road(col, row):
        st['safe_pos'] = car.rect.center

    # Candidate axes: whichever corridor(s) this tile belongs to. Route 70 is
    # a route, not a livery that gets to wander down Chippewa.
    cands = []
    if traffic__is_road(col, row) and row in traffic__ROAD_LINES:
        cands.extend(((0, row), (2, row)))
    if traffic__is_road(col, row) and col in traffic__ROAD_LINES:
        cands.extend(((1, col), (3, col)))
    if car.variant == 'metrobus_70':
        st['fixed_line'] = ROUTE_70_COL
        cands = [item for item in cands
                 if item[0] in (1, 3) and item[1] == ROUTE_70_COL]
    if not cands:
        # A parked/player-abandoned car may legitimately be on a driveway,
        # diagonal, rail cut or plaza. Do not invent a cardinal corridor and
        # make it drive across whatever happens to lie between it and that line.
        st['valid'] = False
        return False

    facing = int(round(car.angle / (math.pi * 0.5))) % 4

    def rank(item):
        d, _line = item
        turn = abs(((d - facing + 2) % 4) - 2)          # 0 straight .. 2 reverse
        clear = 0 if traffic__segment_clear(col, row, d) else 1  # clear legs first
        return (clear, turn, d)

    cands.sort(key=rank)
    st['dir'], st['line'] = cands[0]
    st['valid'] = True
    car.wander_dir = traffic__WANDER_DIR_MAP[st['dir']]
    return True


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


def traffic_snap_to_lane(car):
    """Seat freshly streamed traffic on its lane instead of the centre stripe.

    Population spawners deliberately return tile centres. On a road that is the
    yellow line, 15px away from either legal lane, so every new car used to spend
    its first visible half-block driving diagonally. Only brand-new/off-screen
    traffic calls this helper; handing a parked player car back to the AI never
    teleports it.
    """
    st = getattr(car, '_traffic_ai', None)
    if st is None:
        if not traffic_init_car(car):
            return False
        st = car._traffic_ai
    if not st.get('valid', False):
        return False
    col = int(car.rect.centerx) // traffic__TS
    row = int(car.rect.centery) // traffic__TS
    old = car.rect.center
    d = st['dir']
    _hx, hy = traffic__DIRS[d]
    lane = traffic__lane_clamped(d, st['line'], col, row)
    if hy == 0:
        car.rect.centery = int(round(lane))
    else:
        car.rect.centerx = int(round(lane))
    if traffic__is_blocked is not None and traffic__is_blocked(car.rect):
        car.rect.center = old
        return False
    car.angle = traffic_aligned_spawn_angle(car)
    car.steer_angle = 0.0
    car.vlat = 0.0
    car._prev_angle = car.angle
    st['safe_pos'] = car.rect.center
    return True


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
    if st.get('fixed_line') is not None:
        if traffic__segment_clear(jcol, jrow, d):
            return d
        reverse = (d + 2) % 4
        return reverse if traffic__segment_clear(jcol, jrow, reverse) else d
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
    """Scan the forward cone.  Returns (cap, pass_side).

    ``cap`` is the speed the car in front allows, or None for a clear road.
    ``pass_side`` is -1 / +1 when something *stopped* is sitting in the cone
    and the lane should be shifted that way to get around it, or 0 for
    nothing to pull out for.

    Oncoming traffic is deliberately ignored.  It is separated by a full lane
    width, it passes in a few frames, and main.py runs no car-car collision
    between AI cars anyway -- whereas braking for it deadlocks both cars
    permanently: a stopped car cannot steer (the physics needs |velocity| > 0.15)
    so neither can ever pull back into its own lane.

    Stationary obstacles no longer set a hard cap either. Parked cars, wrecks
    and jammed cars sit in the driving lane all day; braking to nothing behind
    one and waiting for it to move is a wait that never ends, and it was the
    single biggest source of stacked-up traffic. They ask for a pass instead.
    """
    cap = None
    pass_side = 0
    nearest_static = traffic_PASS_LOOK
    px, py = car.rect.centerx, car.rect.centery
    for other in neighbours:
        if other is car:
            continue
        dx = other.rect.centerx - px
        dy = other.rect.centery - py
        f = dx * fx + dy * fy
        if f <= 0.0 or f > traffic_FOLLOW_LOOK:
            continue
        lat = dx * -fy + dy * fx
        if abs(lat) > traffic_FOLLOW_LAT:
            continue
        moving = abs(other.velocity) > traffic_PASS_STILL
        if moving and abs(other.velocity) > 0.4:
            if math.cos(other.angle) * fx + math.sin(other.angle) * fy < 0.25:
                continue                     # oncoming: it will pass, don't brake
        if not moving:
            # Something parked in our way. Go around it rather than queue.
            if f < nearest_static:
                nearest_static = f
                # Pull toward whichever side it is NOT on; dead ahead, pull
                # left, which on right-hand traffic is toward the centre line.
                pass_side = -1 if lat >= 0.0 else 1
            continue
        allow = (f - traffic_FOLLOW_MIN_GAP) * traffic_FOLLOW_GAIN
        if allow < 0.0:
            allow = 0.0
        if cap is None or allow < cap:
            cap = allow
    return cap, pass_side


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

def traffic__recover_to_grid(car, st):
    """Put a wayward ambient vehicle back at its last valid road point."""
    safe = st.get('safe_pos')
    if safe is not None:
        car.rect.center = safe
    car.velocity = 0.0
    st['dir'] = (st['dir'] + 2) % 4
    car.angle = st['dir'] * math.pi * 0.5
    car.steer_angle = 0.0
    car.vlat = 0.0
    st['junction'] = None
    st['next_dir'] = None
    st['last_junction'] = None
    st['halt'] = 0
    st['creep'] = 0


def traffic_drive(car, neighbours=()):
    """One frame of ambient driving.  Ends with exactly one physics_step()."""
    st = getattr(car, '_traffic_ai', None)
    if st is None:
        if not traffic_init_car(car):
            car.velocity = 0.0
            return
        st = car._traffic_ai
    if not st.get('valid', False):
        car.velocity = 0.0
        return

    ts = traffic__TS
    px = car.rect.centerx
    py = car.rect.centery
    col = int(px) // ts
    row = int(py) // ts

    # Never continue across open non-road ground. Collision alone cannot help:
    # ballast, landmark plazas and lawns are intentionally walkable. Restore
    # the last road position (normally only a few pixels behind), turn around,
    # and let the ordinary junction logic find a different route.
    if not traffic__is_grid_road(col, row):
        traffic__recover_to_grid(car, st)
        return
    st['safe_pos'] = car.rect.center

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

    # --- pull out around anything stopped in the lane ----------------------
    # Done before the steering so the lane target already includes the offset.
    fx0 = math.cos(car.angle)
    fy0 = math.sin(car.angle)
    follow, pass_side = traffic__follow_cap(car, neighbours, fx0, fy0)
    want_pass = pass_side * traffic_PASS_SHIFT * traffic__pass_axis(d)
    st['pass'] += (want_pass - st['pass']) * traffic_PASS_RATE
    if abs(st['pass']) < 0.4:
        st['pass'] = 0.0

    # --- pure-pursuit steering toward the lane centre ----------------------
    lane = traffic__lane_clamped(d, st['line'], col, row, st['pass'])
    # Did the pull-out survive the kerb clamp? On a bridge deck, or a street
    # walled in on both sides, there is nowhere to go: the pass is refused and
    # the car queues normally instead of driving into the obstacle at the
    # pass speed floor.
    room_to_pass = abs(lane - traffic__lane_clamped(d, st['line'], col, row)) > 6.0
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

    if follow is not None and follow < target:
        target = follow

    gate_hold = bool(traffic__rail_gate_hold and traffic__rail_gate_hold(car))
    if gate_hold:
        target = 0.0
        st['creep'] = 0

    # Easing out around something stopped: keep rolling. Braking to a halt
    # beside a parked car is how a lane used to die permanently.
    if pass_side and room_to_pass and target < traffic_PASS_SPEED:
        target = traffic_PASS_SPEED

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
    if st['halt'] > traffic_HALT_PATIENCE and not gate_hold:
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

    # physics_step can cross a tile boundary on this very frame. Repair it
    # immediately so rendering and collision never get one frame of a car on
    # a lawn, plaza, roof, or reserved rail bed.
    new_col = car.rect.centerx // ts
    new_row = car.rect.centery // ts
    if not traffic__is_grid_road(new_col, new_row):
        traffic__recover_to_grid(car, st)



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
    "Lambert Airport": "lambert",
    "Gateway Arch": "arch",
    "Busch Stadium": "stadium",
    "Anheuser-Busch Brewery": "brewery",
    "Forest Park": "forest_park",
    "Fairground Park": "forest_park",
    "Tower Grove Park": "tower_grove",
    "Ted Drewes": "ted_drewes",
    "Ted Drewes on Grand": "ted_drewes",
    "Compton Hill Water Tower": "water_tower",
    "Bissell Street Water Tower": "water_tower",
    "Bevo Mill": "bevo",
    "Old Courthouse": "courthouse",
    "Union Station": "union_station",
    "City Museum": "city_museum",
    "Missouri Botanical Garden": "botanical",
    # These four bakers - several hundred lines of authored art each, with
    # ground colours and label anchors already registered - existed and were
    # reachable from NOTHING: no landmark name mapped to them, so the Central
    # West End, The Hill, the Delmar Loop and Grand Center all fell through to
    # the generic district building ring and drew as the same grey block. That
    # is a large part of why the neighbourhoods felt interchangeable.
    "Central West End": "central_west_end",
    "The Hill": "the_hill",
    "Delmar Loop": "delmar_loop",
    "Grand Center Arts District": "grand_center",
}

#: natural footprint of each landmark in tiles, derived from main.LANDMARKS.
#: Used by lm_bake() so the common sizes are ready before the first frame.
lm_FOOTPRINT_TILES = {
    name: (w, h) for (x, y, w, h, kind, name, color) in LANDMARKS
}

#: walkable ground / plaza colour per style
lm__GROUND = {
    "lambert": (86, 90, 94),
    "arch": (66, 82, 54),
    "stadium": (96, 92, 88),
    "ted_drewes": (52, 52, 54),
    "brewery": (70, 68, 68),
    "forest_park": (68, 84, 56),
    "central_west_end": (102, 98, 94),
    "the_hill": (100, 96, 92),
    "delmar_loop": (100, 96, 92),
    "tower_grove": (68, 84, 56),
    "grand_center": (98, 94, 90),
    "water_tower": (68, 84, 56),
    "bevo": (68, 84, 56),
    "courthouse": (100, 96, 92),
    "union_station": (100, 96, 92),
    "city_museum": (100, 96, 92),
    "botanical": (66, 86, 54),
}

#: label position as a fraction of the footprint, chosen to sit on calm art
lm__LABEL_AT = {
    "lambert": (0.52, 0.92),
    "arch": (0.46, 0.40),
    "stadium": (0.34, 0.93),
    "ted_drewes": (0.50, 0.97),
    "brewery": (0.50, 0.93),
    "forest_park": (0.50, 0.93),
    "central_west_end": (0.50, 0.93),
    "the_hill": (0.50, 0.93),
    "delmar_loop": (0.50, 0.06),
    "tower_grove": (0.50, 0.93),
    "grand_center": (0.50, 0.93),
    "water_tower": (0.50, 0.95),
    "bevo": (0.50, 0.06),
    "courthouse": (0.50, 0.95),
    "union_station": (0.50, 0.97),
    "city_museum": (0.50, 0.95),
    "botanical": (0.50, 0.96),
}

lm__CACHE = {}
lm__FG_CACHE = {}
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


def lm__bake_arch_foreground(w, h):
    """Only the elevated steel and its footings, for the actor occlusion pass.

    The full Arch composition is ground art and is drawn before actors.  A
    second transparent pass puts the elevated span back over them, making a
    walk across the lawn read as going *under* the Arch rather than over a
    silver stripe painted on the ground.
    """
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    lx0, lx1 = w * 0.145, w * 0.775
    ybase, yapex = h * 0.575, h * 0.115
    pts = lm__catenary(lx0, lx1, ybase, yapex, 56, 2.05)
    w_end = max(9.0, w * 0.045)
    w_mid = max(4.0, w_end * 0.33)
    lm__ribbon(s, pts, w_end + 2, w_mid + 2, lm_OUTLINE)
    lm__ribbon(s, pts, w_end, w_mid, lm_STEEL)
    lm__ribbon(s, pts, w_end * 0.34, w_mid * 0.40, lm_STEEL_LO, 1.6, 1.6)
    lm__ribbon(s, pts, w_end * 0.34, w_mid * 0.40, lm_STEEL_HI, -1.4, -1.4)
    for fx in (lx0, lx1):
        pad = [(fx - w_end * 0.95, ybase - 3),
               (fx + w_end * 0.95, ybase - 3),
               (fx + w_end * 1.25, ybase + w_end * 0.9),
               (fx - w_end * 1.25, ybase + w_end * 0.9)]
        lm__poly(s, lm_CONCRETE, pad)
        lm__poly(s, lm_OUTLINE, pad, 1)
        lm__poly(s, lm_STEEL_LO,
                 [(fx - w_end * 0.5, ybase - 2),
                  (fx + w_end * 0.5, ybase - 2),
                  (fx, ybase + w_end * 0.55)])
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

    # Blocks on the SAME tile grid the collision mask uses. The old loop laid
    # roofs on a 94x68px pitch of its own invention while the collision was a
    # hollow ring, so the middle of the brewery was walkable ground painted to
    # look like roofs - which is why crossing it felt like walking on rooftops.
    lw = max(3, int(round(w / float(lm_TILE))))
    lh = max(3, int(round(h / float(lm_TILE))))
    tw = w / float(lw)
    th = h / float(lh)

    # --- yard streets: cobble, kerbs, a painted centre line ------------------
    lane_fill = (96, 92, 88)
    def lane_h(j):
        lm__r(s, lane_fill, 0, j * th, w, th)
        for x in range(0, int(w), 11):        # setts
            lm__r(s, (84, 80, 78), x, j * th + 2, 6, th - 4)
        lm__r(s, (176, 158, 96), 0, j * th + th * 0.5 - 1, w, 2)

    def lane_v(i):
        lm__r(s, lane_fill, i * tw, 0, tw, h)
        for y in range(0, int(h), 11):
            lm__r(s, (84, 80, 78), i * tw + 2, y, tw - 4, 6)
        lm__r(s, (176, 158, 96), i * tw + tw * 0.5 - 1, 0, 2, h)

    for j in range(lh):
        if j == 0 or j == lh - 1 or j % BREWERY_LANE == 0:
            lane_h(j)
    for i in range(lw):
        if i == 0 or i == lw - 1 or i % BREWERY_LANE == 0:
            lane_v(i)

    # rail spur down the south apron, where the yard meets the levee tracks
    ry = (lh - 1) * th + th * 0.5
    lm__r(s, lm_GRAVEL_DK, 0, ry - 8, w, 18)
    for x in range(0, int(w), 7):
        lm__r(s, (62, 52, 44), x, ry - 7, 4, 16)
    lm__r(s, lm_STEEL_LO, 0, ry - 2, w, 2)
    lm__r(s, lm_STEEL_LO, 0, ry + 6, w, 2)

    # --- the buildings ------------------------------------------------------
    roofs = (lm_BRICK, lm_BRICK_DK, lm_BRICK_BROWN, lm_TAR, lm_BRICK_LT, lm_TAR_LT)
    blocks = brewery_blocks(lw, lh)
    brew_house = blocks[len(blocks) // 6] if blocks else None
    for (bc, br, bcw, bch) in blocks:
        x, y = bc * tw + 3, br * th + 3
        bw, bh = bcw * tw - 6, bch * th - 6
        n = lm__noise(bc, br, 93)
        if (bc, br) == (brew_house or (-1, -1))[:2]:
            continue                       # drawn last, taller than the rest
        roof = lm__pick(roofs, bc, br, 94)
        rf = lm__block(s, x, y, bw, bh, roof, 5, 7)
        kind = (n >> 6) % 3
        if kind == 0 and rf.w > 26:        # sawtooth glasshouse roof
            for sx in range(rf.x + 5, rf.right - 7, 9):
                lm__r(s, (150, 152, 148), sx, rf.y + 5, 4, rf.h - 10)
                lm__r(s, lm__shade(roof, 0.6), sx + 4, rf.y + 5, 2, rf.h - 10)
        elif kind == 1:
            lm__roof_clutter(s, rf, 95 + bc, dense=4, base=roof)
            for i in range(3):             # rooftop fermenting tanks
                tcx = rf.x + 14 + i * 20
                tcy = rf.bottom - 16
                if tcx + 12 > rf.right:
                    break
                pygame.draw.circle(s, lm_SHADOW, (tcx + 4, tcy + 4), 10)
                pygame.draw.circle(s, (132, 134, 132), (tcx, tcy), 10)
                pygame.draw.circle(s, (168, 170, 166), (tcx - 3, tcy - 3), 5)
                pygame.draw.circle(s, lm_OUTLINE, (tcx, tcy), 10, 1)
        else:
            lm__r(s, lm__shade(roof, 1.12), rf.x + 4, rf.y + 4, rf.w - 8, 3)
            lm__r(s, lm__shade(roof, 0.78), rf.x + 4, rf.centery, rf.w - 8, 2)
        # loading dock on the yard side, so the block reads as enterable
        lm__r(s, (52, 44, 40), rf.x + rf.w // 3, rf.bottom - 4, rf.w // 3, 5)

    # the Brew House: crenellated tower block, on its own block
    if brew_house is not None:
        bc, br, bcw, bch = brew_house
        rf = lm__block(s, bc * tw + 1, br * th + 1, bcw * tw - 2, bch * th - 2,
                       lm_BRICK_DK, 6, 11)
        lm__r(s, lm_BRICK_LT, rf.x + 7, rf.y + 7, rf.w - 14, rf.h - 14)
        pygame.draw.rect(s, lm_OUTLINE, (rf.x + 7, rf.y + 7, rf.w - 14, rf.h - 14), 1)
        for cxx in range(rf.x + 2, rf.right - 4, 8):
            lm__r(s, lm_BRICK_DK, cxx, rf.y + 1, 4, 4)
            lm__r(s, lm_BRICK_DK, cxx, rf.bottom - 5, 4, 4)
        for cyy in range(rf.y + 2, rf.bottom - 4, 8):
            lm__r(s, lm_BRICK_DK, rf.x + 1, cyy, 4, 4)
            lm__r(s, lm_BRICK_DK, rf.right - 5, cyy, 4, 4)

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
def lm__fp_basin(s, w, h, bcx, bcy, bw2, bh2):
    """The Emerson Grand Basin: coping, jets, plumes and the cascades.

    The old version was one flat blue ellipse with eight 3px dots on it, so
    the single most photographed thing in Forest Park read as a pond. It now
    gets a limestone coping ring, a proper centre jet with a plume, a ring of
    smaller jets, and the stepped cascades climbing north toward Art Hill.
    """
    ring = []
    for a in lm__lin(0, math.pi * 2, 42):
        ring.append((bcx + math.cos(a) * bw2, bcy + math.sin(a) * bh2))
    # cast shadow, then the stone coping, then the water inside it
    lm__poly(s, lm_SHADOW, [(px, py + 4) for (px, py) in ring])
    lm__poly(s, lm_LIMESTONE, ring)
    lm__poly(s, lm_LIMESTONE_DK, ring, 2)
    inner = [(bcx + (px - bcx) * 0.90, bcy + (py - bcy) * 0.80) for (px, py) in ring]
    lm__water_poly(s, inner, 103, lm_WATER_DK)

    # jets: a tall centre plume flanked by a row either side
    def jet(jx, jy, size):
        pygame.draw.circle(s, lm_WATER_LT, (int(jx), int(jy)), size + 3, 1)
        lm__r(s, (196, 216, 226), jx - 1, jy - size * 2, 2, size * 2)
        pygame.draw.circle(s, (214, 228, 234), (int(jx), int(jy - size * 2)), size)
        pygame.draw.circle(s, (238, 246, 248), (int(jx), int(jy - size * 2 - 1)),
                           max(1, size // 2))

    jet(bcx, bcy, 6)
    span = bw2 * 0.72
    for i in range(-3, 4):
        if i == 0:
            continue
        jet(bcx + i * span / 3.0, bcy + (2 if i % 2 else -2), 3)

    # the cascades: stepped basins stepping up the hill to the north
    casc_top = bcy - bh2 - 6
    for i in range(5):
        cw = bw2 * (0.40 - i * 0.055)
        cy = casc_top - i * 15
        lm__r(s, lm_SHADOW, bcx - cw, cy - 8, cw * 2, 12)
        lm__r(s, lm_LIMESTONE, bcx - cw, cy - 10, cw * 2, 12)
        lm__r(s, lm_WATER_LT, bcx - cw + 3, cy - 8, cw * 2 - 6, 6)
        lm__r(s, lm_WATER, bcx - cw + 3, cy - 5, cw * 2 - 6, 3)
        pygame.draw.rect(s, lm_LIMESTONE_DK,
                         (int(bcx - cw), int(cy - 10), int(cw * 2), 12), 1)

    # pergola pavilions flanking the basin, the pair everyone walks between
    for side in (-1, 1):
        px = bcx + side * (bw2 + 26)
        lm__r(s, lm_SHADOW, px - 12, bcy - 16, 26, 36)
        lm__r(s, lm_LIMESTONE, px - 14, bcy - 18, 26, 36)
        pygame.draw.rect(s, lm_LIMESTONE_DK, (int(px - 14), int(bcy - 18), 26, 36), 1)
        for cy2 in range(int(bcy - 14), int(bcy + 14), 8):
            lm__r(s, lm_LIMESTONE_DK, px - 11, cy2, 4, 5)
            lm__r(s, lm_LIMESTONE_DK, px + 4, cy2, 4, 5)


def lm__fp_apotheosis(s, x, y):
    """The Apotheosis of St. Louis: the king on his horse at the head of Art
    Hill, sword raised. Deliberately oversized for its plan footprint - at
    true scale it is four pixels, and this is the one silhouette everyone who
    has ever sledded that hill will recognise."""
    lm__r(s, lm_SHADOW, x - 14, y - 6, 34, 30)              # plinth shadow
    lm__r(s, lm_LIMESTONE_DK, x - 18, y - 10, 34, 30)       # plinth
    lm__r(s, lm_LIMESTONE, x - 16, y - 8, 30, 26)
    pygame.draw.rect(s, lm_OUTLINE, (int(x - 18), int(y - 10), 34, 30), 1)
    lm__r(s, lm_LIMESTONE_DK, x - 21, y + 18, 40, 5)        # base course
    # horse in plan: a long body with a raised head, in weathered bronze
    lm__r(s, lm_VERDIGRIS_DK, x - 10, y - 2, 20, 13)
    lm__r(s, lm_VERDIGRIS, x - 9, y - 3, 17, 11)
    lm__r(s, lm_VERDIGRIS_DK, x - 3, y - 12, 7, 11)         # neck
    lm__r(s, lm_VERDIGRIS, x - 2, y - 11, 5, 9)
    lm__r(s, lm_VERDIGRIS_DK, x - 2, y - 17, 5, 6)          # head
    lm__r(s, lm_VERDIGRIS, x - 2, y - 1, 5, 5)              # rider
    lm__r(s, (196, 224, 206), x + 4, y - 14, 2, 14)         # the raised sword
    pygame.draw.rect(s, lm_OUTLINE, (int(x - 10), int(y - 2), 20, 13), 1)


def lm__fp_jewel_box(s, x, y):
    """The Jewel Box: a stepped glasshouse of five descending glazed tiers.
    Nothing else in the park looks anything like it from above."""
    lm__r(s, lm_SHADOW, x - 26, y - 14, 60, 36)
    for i, (iw, ih) in enumerate(((34, 30), (26, 24), (18, 18))):
        gx, gy = x - iw / 2, y - ih / 2
        lm__r(s, (150, 176, 178), gx, gy, iw, ih)
        pygame.draw.rect(s, lm_STEEL_LO, (int(gx), int(gy), int(iw), int(ih)), 1)
        for mx in range(int(gx) + 4, int(gx + iw) - 1, 5):    # glazing bars
            lm__r(s, (108, 138, 142), mx, gy + 1, 1, ih - 2)
        lm__r(s, (196, 214, 214), gx + 2, gy + 2, iw - 4, 2)  # highlight
    lm__r(s, lm_LIMESTONE, x - 5, y + 15, 10, 6)              # entry porch


def lm__fp_flight_cage(s, x, y):
    """The 1904 World's Fair Flight Cage at the Zoo: a vast wire-mesh barrel
    vault. Reads as a lattice dome ringed by aviary paths."""
    pygame.draw.circle(s, lm_SHADOW, (int(x + 3), int(y + 4)), 30)
    pygame.draw.circle(s, (86, 104, 78), (int(x), int(y)), 30)
    pygame.draw.circle(s, lm_STEEL_LO, (int(x), int(y)), 30, 2)
    for a in lm__lin(0, math.pi * 2, 14):                     # meridian wires
        lm__line(s, lm_STEEL, (x, y), (x + math.cos(a) * 29, y + math.sin(a) * 29), 1)
    for rr in (11, 20, 27):                                   # hoop wires
        pygame.draw.circle(s, lm_STEEL, (int(x), int(y)), rr, 1)
    pygame.draw.circle(s, (60, 82, 58), (int(x), int(y)), 8)  # planting inside
    pygame.draw.circle(s, lm_WATER_DK, (int(x - 5), int(y + 4)), 4)


def lm__bake_forest_park(w, h):
    """Forest Park, 1326 acres - bigger than Central Park, and St. Louis will
    tell you so unprompted.

    Research, roughly north-up as the park actually sits: the Emerson Grand
    Basin with its cascades at the foot of Art Hill; the Cass Gilbert Palace
    of Fine Arts (Saint Louis Art Museum) crowning the hill with the
    Apotheosis of St. Louis out front; Post-Dispatch Lake and the Boathouse
    east; the Muny's fan of open-air seating north-east; the Saint Louis Zoo
    and its 1904 Flight Cage south-west of the museum; the Jewel Box down in
    the south-east; the World's Fair Pavilion on Government Hill; golf on the
    west; a wooded rim and the ring road all the way round.
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

    # ---- Art Hill: terraced turf climbing north from the basin -------------
    bcx, bcy = w * 0.42, h * 0.565
    bw2, bh2 = w * 0.185, h * 0.050
    hill_top = bcy - bh2 - 210
    # Broad contour bands, each a stop lighter than the last, so the slope
    # reads as a slope from above. This is the hill the whole city sleds.
    for i in range(9):
        f = 1.22 - i * 0.085
        band = pygame.Rect(int(bcx - bw2 * f), int(hill_top + (8 - i) * 24 - 30),
                           int(bw2 * 2 * f), 60)
        pygame.draw.ellipse(s, lm__shade(lm_GRASS, 1.00 + i * 0.045), band)
        pygame.draw.ellipse(s, lm__shade(lm_GRASS_DK, 1.00 + i * 0.03), band, 1)

    # ---- Saint Louis Art Museum: Cass Gilbert, limestone, pedimented -------
    mus_w = max(120, min(int(bw2 * 1.35), 300))
    mus_h = 96
    mx, my = int(bcx - mus_w / 2), int(hill_top - 96)
    lm__r(s, lm_SHADOW, mx - 8, my + 6, mus_w + 20, mus_h + 20)
    lm__r(s, lm_CONCRETE_DK, mx - 14, my - 10, mus_w + 28, mus_h + 26)   # terrace
    pygame.draw.rect(s, lm_LIMESTONE_DK, (mx - 14, my - 10, mus_w + 28, mus_h + 26), 2)
    # long wings either side of a taller central hall
    lm__block(s, mx, my + 14, mus_w * 0.31, mus_h - 14, lm_LIMESTONE_DK, 4, 6)
    lm__block(s, mx + mus_w * 0.69, my + 14, mus_w * 0.31, mus_h - 14,
              lm_LIMESTONE_DK, 4, 6)
    rf = lm__block(s, mx + mus_w * 0.28, my, mus_w * 0.44, mus_h, lm_LIMESTONE, 5, 8)
    lm__r(s, lm__shade(lm_LIMESTONE, 0.86), rf.x + 6, rf.y + 6, rf.w - 12, rf.h - 30)
    pygame.draw.rect(s, lm_OUTLINE, (rf.x + 6, rf.y + 6, rf.w - 12, rf.h - 30), 1)
    # the pediment and the three great arches of the south portico
    lm__r(s, lm_LIMESTONE_DK, rf.x + 2, rf.bottom - 24, rf.w - 4, 20)
    for k in range(3):
        ax = rf.x + 6 + k * (rf.w - 12) / 3.0
        aw = (rf.w - 12) / 3.0 - 5
        lm__r(s, lm_SHADOW, ax, rf.bottom - 21, aw, 15)
        pygame.draw.arc(s, lm_LIMESTONE,
                        (int(ax), int(rf.bottom - 26), int(aw), 20),
                        0.0, math.pi, 2)
    pygame.draw.rect(s, lm_OUTLINE, (rf.x + 2, rf.bottom - 24, rf.w - 4, 20), 1)

    # the grand allee and stair running down the hill to the basin
    lm__thick_path(s, [(bcx, rf.bottom + 40), (bcx, bcy - bh2 - 86)], 15,
                   lm_GRAVEL, lm_GRAVEL_DK)
    for yy in range(int(rf.bottom + 42), int(bcy - bh2 - 88), 8):
        lm__r(s, lm_GRAVEL_DK, bcx - 7, yy, 15, 2)
    # the king on his horse, on the terrace at the head of the stair
    lm__fp_apotheosis(s, bcx, rf.bottom + 26)

    # ---- the Grand Basin ---------------------------------------------------
    lm__fp_basin(s, w, h, bcx, bcy, bw2, bh2)

    # ---- Post-Dispatch Lake, the Boathouse, lagoons ------------------------
    lake = lm__blob(w * 0.755, h * 0.615, w * 0.112, h * 0.112, 104, 26, 0.10)
    lm__poly(s, lm_GRAVEL_DK, [(px + 2, py + 2) for (px, py) in lake])
    lm__water_poly(s, lake, 105, lm_WATER_DK)
    isl = lm__blob(w * 0.765, h * 0.600, w * 0.030, h * 0.032, 106, 14, 0.16)
    lm__poly(s, lm_GRASS_DK, isl)
    lm__poly(s, lm_OUTLINE, isl, 1)
    for k in range(4):
        lm__tree(s, w * 0.765 + (k % 2) * 14 - 7, h * 0.600 + (k // 2) * 13 - 6, 7, 107 + k)
    # the Boathouse and its dock of hire boats on the west shore
    bhx, bhy = w * 0.672, h * 0.628
    lm__r(s, lm_SHADOW, bhx - 20, bhy - 10, 46, 26)
    lm__block(s, bhx - 24, bhy - 14, 46, 26, (118, 82, 60), 4, 0)
    lm__r(s, lm_TAR_LT, bhx + 22, bhy - 4, 16, 4)                  # the dock
    for k in range(4):
        lm__r(s, (188, 176, 150), bhx + 26 + (k % 2) * 9, bhy + 2 + k * 5, 8, 3)
    lag = lm__blob(w * 0.125, h * 0.690, w * 0.068, h * 0.050, 108, 22, 0.12)
    lm__water_poly(s, lag, 109, lm_WATER_DK)
    lag2 = lm__blob(w * 0.560, h * 0.815, w * 0.055, h * 0.042, 110, 20, 0.12)
    lm__water_poly(s, lag2, 111, lm_WATER_DK)
    lm__thick_path(s, [(w * 0.560, h * 0.790), (w * 0.615, h * 0.735),
                       (w * 0.640, h * 0.690)], 9, lm_WATER, lm_WATER_DK)

    # ---- golf: fairways, bunkers, greens ------------------------------------
    for i, (fx, fy, frx, fry) in enumerate(((0.150, 0.235, 0.080, 0.050),
                                            (0.285, 0.165, 0.066, 0.040),
                                            (0.140, 0.410, 0.062, 0.042))):
        fair = lm__blob(w * fx, h * fy, w * frx, h * fry, 112 + i, 18, 0.20)
        lm__poly(s, lm__shade(lm_GRASS_LT, 1.08), fair)
        lm__poly(s, lm_GRASS_DK, fair, 1)
        gx2, gy2 = w * fx + w * frx * 0.55, h * fy - h * fry * 0.35
        pygame.draw.circle(s, (104, 128, 70), (int(gx2), int(gy2)), 13)
        pygame.draw.circle(s, lm_GRASS_DK, (int(gx2), int(gy2)), 13, 1)
        lm__line(s, (210, 206, 196), (gx2, gy2), (gx2, gy2 - 7), 1)
        lm__r(s, (168, 62, 58), gx2, gy2 - 7, 4, 3)
        bunk = lm__blob(w * fx - w * frx * 0.45, h * fy + h * fry * 0.45, 15, 9,
                        115 + i, 12, 0.28)
        lm__poly(s, lm_SAND, bunk)
        lm__poly(s, lm__shade(lm_SAND, 0.72), bunk, 1)

    # ---- The Muny: fan of open-air seating, stage house at its back --------
    mcx, mcy = w * 0.800, h * 0.220
    lm__r(s, lm_SHADOW, mcx - 44, mcy - 34, 92, 34)
    lm__block(s, mcx - 48, mcy - 38, 92, 32, lm_CONCRETE_DK, 4, 0)
    lm__r(s, lm_TAR, mcx - 40, mcy - 32, 76, 8)                    # fly tower
    for i in range(9):
        rr = 22 + i * 10
        pts = [(mcx + math.cos(a) * rr, mcy + math.sin(a) * rr * 0.92)
               for a in lm__lin(math.radians(16), math.radians(164), 14)]
        lm__thick_path(s, pts, 6, lm_SEAT_RED if i % 2 else lm_SEAT_RED_DK)
    pygame.draw.circle(s, lm_CONCRETE, (int(mcx), int(mcy)), 17)   # the stage
    pygame.draw.circle(s, lm_OUTLINE, (int(mcx), int(mcy)), 17, 1)
    # the two famous oaks that used to stand in the middle of the seating
    lm__tree(s, mcx - 30, mcy + 34, 10, 190)
    lm__tree(s, mcx + 30, mcy + 34, 10, 191)

    # ---- Saint Louis Zoo, south-west of the hill ---------------------------
    zcx, zcy = w * 0.315, h * 0.795
    zoo = pygame.Rect(int(zcx - w * 0.105), int(zcy - h * 0.075),
                      int(w * 0.210), int(h * 0.150))
    lm__r(s, lm__shade(lm_GRASS, 1.05), zoo.x, zoo.y, zoo.w, zoo.h)
    pygame.draw.rect(s, lm_GRAVEL_DK, zoo, 2)
    # enclosures: a grid of paddocks with pools and shelters
    for i in range(6):
        n = lm__noise(i, 3, 193)
        ex = zoo.x + 12 + (i % 3) * (zoo.w - 76) / 3.0
        ey = zoo.y + 12 + (i // 3) * (zoo.h - 30) / 2.0
        ew, eh = (zoo.w - 88) / 3.0, (zoo.h - 40) / 2.0
        lm__r(s, lm__shade((132, 116, 88), 1.0 + (n % 3) * 0.07), ex, ey, ew, eh)
        pygame.draw.rect(s, lm_GRAVEL_DK, (int(ex), int(ey), int(ew), int(eh)), 1)
        pygame.draw.circle(s, lm_WATER_DK,
                           (int(ex + ew * 0.30), int(ey + eh * 0.62)),
                           max(3, int(min(ew, eh) * 0.16)))
        lm__r(s, lm_TAR_LT, ex + ew * 0.60, ey + eh * 0.20, ew * 0.26, eh * 0.26)
        lm__tree(s, ex + ew * 0.82, ey + eh * 0.80, 6, 194 + i)
    lm__fp_flight_cage(s, zoo.right - 46, zoo.centery)
    # the zoo entrance and its sculpture group, on the north side facing the
    # basin - the animals-on-a-plinth group everybody has a photo in front of
    lm__r(s, lm_LIMESTONE, zoo.centerx - 26, zoo.top - 8, 52, 12)
    pygame.draw.rect(s, lm_LIMESTONE_DK, (zoo.centerx - 26, zoo.top - 8, 52, 12), 1)
    lm__r(s, lm_LIMESTONE_DK, zoo.centerx - 9, zoo.top - 20, 18, 12)
    pygame.draw.circle(s, lm_LIMESTONE, (int(zoo.centerx - 4), int(zoo.top - 18)), 4)
    pygame.draw.circle(s, lm_LIMESTONE, (int(zoo.centerx + 4), int(zoo.top - 15)), 3)

    # ---- the Jewel Box and the World's Fair Pavilion -----------------------
    lm__fp_jewel_box(s, w * 0.525, h * 0.800)
    wfx, wfy = w * 0.610, h * 0.300
    lm__r(s, lm_SHADOW, wfx - 28, wfy - 12, 62, 30)
    lm__block(s, wfx - 32, wfy - 16, 62, 28, lm_TERRACOTTA, 4, 0)
    for cx2 in range(int(wfx - 28), int(wfx + 26), 8):             # colonnade
        lm__r(s, lm_LIMESTONE, cx2, wfy + 10, 4, 7)
    lm__r(s, lm_LIMESTONE_DK, wfx - 32, wfy + 16, 62, 3)

    # ---- paths -------------------------------------------------------------
    lm__thick_path(s, lm__bowed(w * 0.10, w * 0.90, h * 0.32, h * 0.09), 6,
                   lm_GRAVEL, lm_GRAVEL_DK)
    lm__thick_path(s, lm__bowed(w * 0.12, w * 0.88, h * 0.84, -h * 0.10), 6,
                   lm_GRAVEL, lm_GRAVEL_DK)
    lm__thick_path(s, [(bcx, h * 0.640), (w * 0.44, h * 0.720),
                       (w * 0.525, h * 0.755), (w * 0.62, h * 0.735),
                       (w * 0.68, h * 0.700)], 6, lm_GRAVEL, lm_GRAVEL_DK)
    # the walk from the basin down to the zoo gate
    lm__thick_path(s, [(bcx - w * 0.06, h * 0.625), (w * 0.34, h * 0.700),
                       (w * 0.315, h * 0.716)], 6, lm_GRAVEL, lm_GRAVEL_DK)

    # ---- woods -------------------------------------------------------------
    keep_clear = (
        (zoo.centerx, zoo.centery, max(zoo.w, zoo.h) * 0.70),
        (w * 0.525, h * 0.800, 66),
        (wfx, wfy, 74),
        (w * 0.755, h * 0.615, w * 0.15),
        (mcx, mcy, 112),
        (w * 0.125, h * 0.690, w * 0.10),
    )
    for r in range(4, int(h / 34) - 1):
        for c in range(3, int(w / 34) - 1):
            n = lm__noise(c, r, 120)
            if n % 7:
                continue
            px = c * 34 + (n % 13)
            py = r * 34 + ((n >> 4) % 13)
            # keep the hero features readable
            if abs(px - bcx) < bw2 + 44 and -330 < (py - bcy) < 200:
                continue
            if any(math.hypot(px - kx, py - ky) < kr for (kx, ky, kr) in keep_clear):
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
def lm__bake_water_tower(w, h):
    """The Compton Hill Water Tower.

    St. Louis has three of these still standing, which is more than the rest
    of the country put together, and you will be told so. Buff limestone
    shaft, conical copper roof gone green, and - the thing that actually makes
    it work as a landmark - a shadow longer than any building's, so you can
    pick it out from blocks away.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, lm_GRASS, (lm_GRASS_DK, lm_GRASS_LT), 401, 7, 5)
    cx, cy = w * 0.5, h * 0.42
    r = max(6, int(min(w, h) * 0.13))

    # the lawn it stands in, and the low iron fence round that
    pygame.draw.circle(s, lm__shade(lm_GRASS, 1.06), (int(cx), int(cy)),
                       int(r * 2.6))
    pygame.draw.circle(s, lm_GRASS_DK, (int(cx), int(cy)), int(r * 2.6), 1)
    for a in lm__lin(0, math.pi * 2, 34):
        pygame.draw.circle(s, (52, 50, 48),
                           (int(cx + math.cos(a) * r * 2.6),
                            int(cy + math.sin(a) * r * 2.6)), 1)
    # a gravel apron at the base only
    pygame.draw.circle(s, lm_GRAVEL, (int(cx), int(cy)), int(r * 1.45))
    pygame.draw.circle(s, lm_GRAVEL_DK, (int(cx), int(cy)), int(r * 1.45), 1)

    # the long shadow, thrown south-east, longer than any building's
    lm__alpha_poly(s, [(cx - r * 0.8, cy + r * 0.2), (cx + r * 0.8, cy - r * 0.3),
                       (cx + r * 4.6, cy + r * 3.6), (cx + r * 2.4, cy + r * 4.2)],
                   (10, 12, 10, 110))

    # the shaft, then the roof pulled north-west so it reads as height
    pygame.draw.circle(s, lm_LIMESTONE_DK, (int(cx), int(cy)), r)
    pygame.draw.circle(s, lm_LIMESTONE, (int(cx - r * 0.10), int(cy - r * 0.10)),
                       int(r * 0.94))
    pygame.draw.circle(s, lm_OUTLINE, (int(cx), int(cy)), r, 1)
    for a in lm__lin(0, math.pi * 2, 12):        # the stone piers round it
        pygame.draw.circle(s, lm_LIMESTONE_DK,
                           (int(cx + math.cos(a) * r * 0.86),
                            int(cy + math.sin(a) * r * 0.86)), max(1, r // 8))
    pygame.draw.circle(s, lm_VERDIGRIS_DK, (int(cx - r * 0.18), int(cy - r * 0.26)),
                       int(r * 0.62))
    pygame.draw.circle(s, lm_VERDIGRIS, (int(cx - r * 0.28), int(cy - r * 0.38)),
                       int(r * 0.40))
    pygame.draw.circle(s, (226, 220, 200), (int(cx - r * 0.32), int(cy - r * 0.46)),
                       max(1, r // 7))

    # a ring of park trees, kept well inside the frame
    for i in range(12):
        a = i * (math.tau / 12) + 0.3
        n = lm__noise(i, 3, 402)
        rad = r * 3.4 + (n % 3) * 4
        px, py = cx + math.cos(a) * rad, cy + math.sin(a) * rad
        if 10 < px < w - 10 and 10 < py < h - 10:
            lm__tree(s, px, py, 8, 403 + i)
    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


def lm__bake_bevo(w, h):
    """The Bevo Mill: an octagonal Bavarian roadhouse with four turning sails.

    "Meet me by the windmill" is a real sentence in this city. The sails are
    baked at a fixed angle - a rotating landmark is a whole system - but they
    are long and dark against the roof, which is enough to read.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, lm_GRASS, (lm_GRASS_DK, lm_GRASS_LT), 411, 7, 5)
    cx, cy = w * 0.5, h * 0.5
    r = int(min(w, h) * 0.17)

    lm__r(s, lm_ASPHALT, w * 0.06, h * 0.66, w * 0.88, h * 0.22)      # the lot
    lm__mottle_rect(s, (int(w * 0.06), int(h * 0.66), int(w * 0.88), int(h * 0.22)),
                    (lm_ASPHALT_LT, lm_ASPHALT_DK), 412, 6, 5)

    # half-timbered wing to the south-east
    lm__block(s, cx + r * 0.6, cy + r * 0.3, r * 2.4, r * 1.5, (168, 92, 62), 3, 4)
    lm__r(s, (206, 190, 164), cx + r * 0.8, cy + r * 0.55, r * 2.0, r * 0.9)
    for bx in range(int(cx + r * 0.9), int(cx + r * 2.7), 6):
        lm__r(s, (86, 62, 48), bx, cy + r * 0.55, 2, int(r * 0.9))

    # the octagon: stucco drum under a steep red tile cone
    pts = [(cx + math.cos(a) * r, cy + math.sin(a) * r)
           for a in lm__lin(0, math.pi * 2, 8)]
    lm__poly(s, lm_SHADOW, [(x + 3, y + 4) for (x, y) in pts])
    lm__poly(s, (206, 190, 164), pts)
    lm__poly(s, lm_OUTLINE, pts, 1)
    inner = [(cx + (x - cx) * 0.72, cy + (y - cy) * 0.72) for (x, y) in pts]
    lm__poly(s, lm_TERRACOTTA, inner)
    lm__poly(s, lm__shade(lm_TERRACOTTA, 0.78), inner, 1)
    pygame.draw.circle(s, (188, 150, 70), (int(cx), int(cy)), 3)   # the eagle vane

    # four sails, latticed, at a fixed 45 degrees
    for k in range(4):
        a = k * (math.pi / 2) + math.pi / 4
        ex, ey = cx + math.cos(a) * r * 2.5, cy + math.sin(a) * r * 2.5
        lm__line(s, (58, 44, 34), (cx, cy), (ex, ey), 3)
        px, py = -math.sin(a), math.cos(a)
        for t in (0.45, 0.62, 0.79, 0.96):
            mx2, my2 = cx + math.cos(a) * r * 2.5 * t, cy + math.sin(a) * r * 2.5 * t
            lm__line(s, (86, 66, 50), (mx2 - px * 4, my2 - py * 4),
                     (mx2 + px * 4, my2 + py * 4), 1)
    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


def lm__bake_courthouse(w, h):
    """The Old Courthouse: a cross-plan block under a cast-iron dome gone
    verdigris. Dred Scott was tried here, and the Arch stands on its axis."""
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, lm_CONCRETE, (lm_CONCRETE_DK, lm_CONCRETE_LT),
                    421, 8, 5)
    cx, cy = w * 0.5, h * 0.5
    arm_l, arm_w = min(w, h) * 0.44, min(w, h) * 0.24

    for i in range(10):                       # plaza trees round the edge
        n = lm__noise(i, 1, 422)
        lm__tree(s, 12 + (n % max(1, int(w - 24))), 12 + ((n >> 6) % max(1, int(h - 24))),
                 8, 423 + i)

    # the four porticoed wings
    lm__r(s, lm_SHADOW, cx - arm_w / 2 + 4, cy - arm_l + 5, arm_w, arm_l * 2)
    lm__r(s, lm_SHADOW, cx - arm_l + 4, cy - arm_w / 2 + 5, arm_l * 2, arm_w)
    for rect in ((cx - arm_w / 2, cy - arm_l, arm_w, arm_l * 2),
                 (cx - arm_l, cy - arm_w / 2, arm_l * 2, arm_w)):
        lm__r(s, lm_LIMESTONE, *rect)
        pygame.draw.rect(s, lm_LIMESTONE_DK,
                         (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])), 1)
    # pediments: a band of column shadows on each face
    for (bx, by, bw2, bh2, vert) in (
            (cx - arm_w / 2, cy - arm_l, arm_w, 7, False),
            (cx - arm_w / 2, cy + arm_l - 7, arm_w, 7, False),
            (cx - arm_l, cy - arm_w / 2, 7, arm_w, True),
            (cx + arm_l - 7, cy - arm_w / 2, 7, arm_w, True)):
        lm__r(s, lm_LIMESTONE_DK, bx, by, bw2, bh2)
        if vert:
            for k in range(3):
                lm__r(s, lm_SHADOW, bx + 2, by + 4 + k * 6, 4, 3)
        else:
            for k in range(3):
                lm__r(s, lm_SHADOW, bx + 4 + k * 6, by + 2, 3, 4)

    # the dome: concentric rings out to verdigris, ribs, and a gold finial
    dr = int(min(w, h) * 0.19)
    for i, col in enumerate((lm_VERDIGRIS_DK, lm_VERDIGRIS,
                             _blend(lm_VERDIGRIS, (255, 255, 255), 0.22))):
        pygame.draw.circle(s, col, (int(cx), int(cy)), int(dr * (1.0 - i * 0.22)))
    for a in lm__lin(0, math.pi * 2, 8):
        lm__line(s, lm_VERDIGRIS_DK, (cx, cy),
                 (cx + math.cos(a) * dr, cy + math.sin(a) * dr), 1)
    pygame.draw.circle(s, lm_OUTLINE, (int(cx), int(cy)), dr, 1)
    pygame.draw.circle(s, (206, 172, 74), (int(cx), int(cy)), 3)
    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


def lm__bake_union_station(w, h):
    """Union Station: limestone headhouse and clock tower across the north,
    the great train shed behind it, and the fountain plaza to the south."""
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, lm_CONCRETE, (lm_CONCRETE_DK, lm_CONCRETE_LT),
                    431, 8, 5)

    # --- the shed: ribs over dark glass, rails and two parked cars ---------
    shed = pygame.Rect(int(w * 0.06), int(h * 0.30), int(w * 0.88), int(h * 0.42))
    lm__r(s, (38, 40, 46), shed.x, shed.y, shed.w, shed.h)
    # the barrel-vault ribs: light steel over dark glazing, alternating, so
    # the shed reads as a roof rather than as a dark rectangle
    rib = max(3, shed.h // 13)
    for i in range(0, shed.h - 2, rib * 2):
        lm__r(s, (104, 110, 118), shed.x + 2, shed.y + 2 + i, shed.w - 4, rib)
        lm__r(s, (138, 144, 152), shed.x + 2, shed.y + 2 + i, shed.w - 4, 1)
    for cx2 in range(shed.x + 6, shed.right - 6, max(8, shed.w // 12)):
        lm__r(s, (58, 62, 70), cx2, shed.y + 2, 2, shed.h - 4)
    for k, ry in enumerate((shed.y + shed.h * 0.34, shed.y + shed.h * 0.66)):
        lm__r(s, (72, 74, 80), shed.x + 6, ry, shed.w - 12, 1)
        lm__r(s, (72, 74, 80), shed.x + 6, ry + 4, shed.w - 12, 1)
        car_x = shed.x + 14 + k * shed.w * 0.42
        lm__r(s, (46, 82, 62), car_x, ry - 4, shed.w * 0.30, 9)
        lm__r(s, (216, 208, 186), car_x + 2, ry - 2, shed.w * 0.30 - 4, 2)
    pygame.draw.rect(s, lm_OUTLINE, shed, 1)

    # --- the headhouse and its clock tower --------------------------------
    head = pygame.Rect(int(w * 0.06), int(h * 0.06), int(w * 0.88), int(h * 0.24))
    lm__r(s, lm_SHADOW, head.x + 4, head.y + 5, head.w, head.h)
    lm__r(s, lm_LIMESTONE_DK, head.x, head.y, head.w, head.h)
    lm__r(s, lm_LIMESTONE, head.x + 2, head.y + 2, head.w - 4, head.h - 6)
    for wx in range(head.x + 8, head.right - 8, 11):
        lm__r(s, (56, 60, 68), wx, head.y + 6, 5, head.h - 14)
    # the great arched entry, dead centre, where the layout leaves the gate
    ax = head.centerx
    lm__r(s, (34, 32, 36), ax - 9, head.bottom - 12, 18, 12)
    pygame.draw.arc(s, lm_LIMESTONE_DK,
                    (int(ax - 11), int(head.bottom - 20), 22, 18), 0.0, math.pi, 2)
    # tower at the west end
    tw = pygame.Rect(head.x + 4, head.y - 6, 14, head.h + 10)
    lm__r(s, lm_SHADOW, tw.x + 3, tw.y + 4, tw.w, tw.h)
    lm__r(s, lm_LIMESTONE, tw.x, tw.y, tw.w, tw.h)
    pygame.draw.rect(s, lm_LIMESTONE_DK, tw, 1)
    pygame.draw.circle(s, (232, 226, 206), (tw.centerx, tw.y + 9), 5)
    pygame.draw.circle(s, lm_OUTLINE, (tw.centerx, tw.y + 9), 5, 1)
    lm__line(s, lm_OUTLINE, (tw.centerx, tw.y + 9), (tw.centerx, tw.y + 5), 1)
    lm__line(s, lm_OUTLINE, (tw.centerx, tw.y + 9), (tw.centerx + 3, tw.y + 10), 1)
    lm__r(s, lm_VERDIGRIS, tw.x + 1, tw.y - 5, tw.w - 2, 5)      # copper cap

    # --- the plaza and the Meeting of the Waters --------------------------
    fx, fy = w * 0.5, h * 0.85
    basin = [(fx + math.cos(a) * w * 0.16, fy + math.sin(a) * h * 0.075)
             for a in lm__lin(0, math.pi * 2, 26)]
    lm__poly(s, lm_LIMESTONE, basin)
    lm__poly(s, lm_LIMESTONE_DK, basin, 1)
    inner = [(fx + (x - fx) * 0.86, fy + (y - fy) * 0.80) for (x, y) in basin]
    lm__water_poly(s, inner, 432, lm_WATER_DK)
    for i in range(7):                 # the bronze figures in the water
        a = i * (math.tau / 7)
        lm__r(s, lm_VERDIGRIS_DK, fx + math.cos(a) * w * 0.075 - 1,
              fy + math.sin(a) * h * 0.035 - 2, 2, 4)
    lm__r(s, (196, 216, 226), fx - 1, fy - 9, 2, 9)
    pygame.draw.circle(s, (222, 236, 240), (int(fx), int(fy - 10)), 3)
    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


def lm__bake_city_museum(w, h):
    """City Museum: a red-brick shoe factory with a school bus hanging off the
    roof, a Ferris wheel beside it, and two aeroplanes wired into a tangle.

    The roof IS the building - that is the entire point of the place - so
    everything up there is sized as a fraction of the roof rather than in
    fixed pixels, and the bus and the planes are drawn overhanging their own
    edges.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, lm_CONCRETE, (lm_CONCRETE_DK, lm_CONCRETE_LT),
                    441, 8, 5)
    body = pygame.Rect(int(w * 0.10), int(h * 0.16), int(w * 0.80), int(h * 0.64))
    lm__r(s, lm_SHADOW, body.x + 6, body.y + 7, body.w, body.h)
    rf = lm__block(s, body.x, body.y, body.w, body.h, lm_BRICK, 6, 0)
    lm__mottle_rect(s, (rf.x, rf.y, rf.w, rf.h), (lm_BRICK_DK, lm_BRICK_LT),
                    442, 6, 3)
    # a parapet, so the roof has an edge the furniture can hang over
    pygame.draw.rect(s, lm_BRICK_DK, rf, 3)
    pygame.draw.rect(s, lm_OUTLINE, rf, 1)
    u = min(rf.w, rf.h) / 100.0          # one unit = 1% of the roof

    # the Ferris wheel, north-west
    wx, wy = rf.x + rf.w * 0.26, rf.y + rf.h * 0.30
    wr = int(22 * u)
    pygame.draw.circle(s, lm_SHADOW, (int(wx + 3), int(wy + 4)), wr)
    pygame.draw.circle(s, (188, 184, 176), (int(wx), int(wy)), wr, max(2, int(3 * u)))
    for a2 in lm__lin(0, math.pi * 2, 8):
        lm__line(s, (150, 146, 140), (wx, wy),
                 (wx + math.cos(a2) * wr, wy + math.sin(a2) * wr), max(1, int(2 * u)))
        pygame.draw.circle(s, (206, 96, 74),
                           (int(wx + math.cos(a2) * wr), int(wy + math.sin(a2) * wr)),
                           max(2, int(4 * u)))
    pygame.draw.circle(s, (120, 116, 112), (int(wx), int(wy)), max(2, int(5 * u)))

    # two fuselages and the wire tangle wired between them
    px, py = rf.x + rf.w * 0.60, rf.y + rf.h * 0.34
    qx, qy = rf.x + rf.w * 0.44, rf.y + rf.h * 0.68
    for (ax2, ay2, ln, wing) in ((px, py, 46 * u, 34 * u), (qx, qy, 38 * u, 28 * u)):
        lm__r(s, lm_SHADOW, ax2 + 3, ay2 + 4, ln, 9 * u)
        lm__r(s, (172, 176, 182), ax2, ay2, ln, 9 * u)
        lm__r(s, (206, 210, 216), ax2, ay2, ln, 3 * u)
        lm__r(s, (146, 150, 158), ax2 + ln * 0.28, ay2 - wing * 0.5, ln * 0.22, wing)
        lm__r(s, (120, 124, 132), ax2 + ln * 0.90, ay2 - wing * 0.22, ln * 0.10,
              wing * 0.44)
    for i in range(18):
        n = lm__noise(i, 2, 444)
        lm__line(s, (168, 168, 176),
                 (px + (n % int(max(2, 46 * u))), py + ((n >> 5) % 9)),
                 (qx + ((n >> 9) % int(max(2, 38 * u))), qy + ((n >> 14) % 9)),
                 1)

    # the school bus, nose up, hanging off the north-east corner
    bw, bh = 40 * u, 15 * u
    bx, by = rf.right - bw * 0.55, rf.y - bh * 0.35
    lm__r(s, lm_SHADOW, bx + 3, by + 4, bw, bh)
    lm__r(s, (206, 166, 48), bx, by, bw, bh)
    lm__r(s, (238, 208, 96), bx, by, bw, bh * 0.28)
    for k in range(5):
        lm__r(s, (66, 80, 96), bx + bw * (0.08 + k * 0.17), by + bh * 0.34,
              bw * 0.12, bh * 0.34)
    lm__r(s, (44, 40, 38), bx + bw * 0.90, by, bw * 0.10, bh)
    pygame.draw.rect(s, lm_OUTLINE, (int(bx), int(by), int(bw), int(bh)), 1)

    # the spiral slide, coming down the south face
    sx2, sy2 = rf.centerx + rf.w * 0.14, rf.bottom - 10 * u
    for i in range(30):
        t = i / 29.0
        a2 = t * math.pi * 3.4
        lm__r(s, (206, 122, 60),
              sx2 + math.cos(a2) * (20 * u - t * 13 * u),
              sy2 + t * 26 * u + math.sin(a2) * (9 * u - t * 5 * u),
              max(2, int(3 * u)), max(2, int(3 * u)))

    # a queue at the door, because there always is one
    for i in range(7):
        n = lm__noise(i, 4, 445)
        lm__r(s, ((72, 96, 120), (128, 72, 68), (86, 84, 96))[n % 3],
              rf.centerx - rf.w * 0.24 + (i % 4) * 7 * u,
              rf.bottom + 6 * u + (i // 4) * 7 * u,
              max(2, int(4 * u)), max(3, int(5 * u)))
    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


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


def lm__bake_ted_drewes(w, h):
    """Ted Drewes Frozen Custard, Chippewa (Route 66).

    Research: a low, wide, flat-roofed white stand set back behind its lot,
    green-trimmed, with a long row of walk-up service windows under a red
    TED DREWES band and a yellow FROZEN CUSTARD strip above it. The queue
    spilling across the lot is the landmark as much as the building is.
    """
    s = lm__new(w, h)
    # the lot: asphalt with faded bay stripes
    lm__fill_mottle(s, w, h, lm_ASPHALT, (lm_ASPHALT_LT, lm_ASPHALT_DK), 211, 7, 5)

    # Vertical budget, top to bottom: signage band, the stand, the queue, the
    # lot. Everything is measured off h so nothing clips off the surface.
    sign_h = max(20, int(h * 0.16))
    by = sign_h + 3
    bh = max(26, int(h * 0.40))
    bx, bw = 8, int(w) - 16
    lot_y = by + bh

    for px in range(14, int(w) - 14, max(26, int(w * 0.11))):
        lm__line(s, lm_LINE_W, (px, lot_y + 34), (px, h - 8))
    lm__line(s, lm_LINE_Y, (6, h - 6), (w - 6, h - 6), 2)

    # ---- roof signage: yellow FROZEN CUSTARD over the red TED DREWES ------
    td, fc = "TED DREWES", "FROZEN CUSTARD"
    sign_w = min(bw, max(hud_text_width(td, 2), hud_text_width(fc, 1)) + 14)
    sx0 = bx + (bw - sign_w) // 2
    lm__r(s, lm_SHADOW, sx0 + 4, 6, sign_w, sign_h)
    lm__r(s, (214, 190, 66), sx0, 2, sign_w, 10)             # yellow strip
    pygame.draw.rect(s, lm_OUTLINE, (sx0, 2, sign_w, 10), 1)
    if hud_text_width(fc, 1) <= sign_w - 4:
        hud_text(s, fc, sx0 + (sign_w - hud_text_width(fc, 1)) // 2, 3,
                 (48, 40, 24), False, 1)
    lm__r(s, (176, 46, 44), sx0, 12, sign_w, sign_h - 10)    # red band
    pygame.draw.rect(s, lm_OUTLINE, (sx0, 12, sign_w, sign_h - 10), 1)
    hud_text(s, td, sx0 + (sign_w - hud_text_width(td, 2)) // 2, 15,
             (246, 240, 226), False, 2)

    # ---- the stand -------------------------------------------------------
    lm__r(s, lm_SHADOW, bx + 6, by + 6, bw, bh)
    lm__r(s, (228, 226, 218), bx, by, bw, bh)                # white block
    lm__r(s, (204, 202, 194), bx, by + bh - 8, bw, 8)        # base shade
    lm__r(s, (54, 96, 62), bx, by + bh - 12, bw, 4)          # green trim band
    lm__r(s, (176, 46, 44), bx, by, bw, 3)                   # red roof edge
    pygame.draw.rect(s, lm_OUTLINE, (bx, by, bw, bh), 1)

    # ---- the row of walk-up service windows ------------------------------
    win_h = max(12, int(bh * 0.42))
    win_y = by + int(bh * 0.28)
    slots = max(3, bw // 34)
    pad = max(4, (bw - slots * 24) // (slots + 1))
    for i in range(slots):
        wx = bx + pad + i * (24 + pad)
        if wx + 22 > bx + bw:
            break
        lm__r(s, (26, 30, 34), wx, win_y, 22, win_h)
        lm__r(s, (128, 168, 176), wx + 2, win_y + 2, 18, win_h - 7)   # lit glass
        lm__r(s, (196, 214, 216), wx + 2, win_y + 2, 18, 3)
        lm__r(s, (150, 148, 140), wx - 2, win_y + win_h - 3, 26, 4)   # counter
        pygame.draw.rect(s, lm_OUTLINE, (wx, win_y, 22, win_h), 1)

    # ---- the queue: the landmark as much as the building is --------------
    coats = ((176, 74, 66), (66, 96, 148), (196, 176, 96), (86, 140, 96),
             (150, 96, 160), (198, 130, 78), (94, 100, 112))
    qx, idx = bx + 6, 0
    while qx < bx + bw - 12:
        n = lm__noise(idx, 0, 217)
        px = qx + (n % 3)
        py = lot_y + 6 + ((n >> 5) % 9)
        lm__r(s, lm_SHADOW, px + 1, py + 11, 8, 3)
        lm__r(s, coats[idx % len(coats)], px, py + 4, 7, 8)  # body
        lm__r(s, (198, 158, 128), px + 1, py, 5, 5)          # head
        lm__r(s, (40, 38, 44), px, py + 12, 7, 3)            # legs
        if n & 16:                                           # holding a cone
            lm__r(s, (238, 234, 220), px + 7, py + 4, 3, 4)
        qx += 12 + (n % 5)
        idx += 1

    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


# --------------------------------------------------------------------------
# 14. MISSOURI BOTANICAL GARDEN
# --------------------------------------------------------------------------
def lm__bake_botanical(w, h):
    """Shaw's Garden, and the Climatron.

    Research: Henry Shaw opened it to the public in 1859 and it has never
    closed, which makes it the oldest botanical garden in continuous operation
    in the country. The Climatron is a Buckminster Fuller geodesic dome, built
    1960 - the first geodesic structure ever used as a conservatory - 70 feet
    high, 175 across, with no interior support of any kind. Seiwa-en, opened
    1977, is the largest Japanese garden in North America: a 14-acre lake with
    islands, a drum bridge and a teahouse. The Linnean House of 1882 is the
    oldest continuously operating greenhouse west of the Mississippi. Tower
    Grove House was Shaw's country home, and his mausoleum stands near it.

    Composition puts the dome dead centre and lets it own the silhouette, the
    way the catenary owns the Arch.
    """
    s = lm__new(w, h)
    lm__fill_mottle(s, w, h, lm_GRASS, (lm_GRASS_DK, lm_GRASS_LT), 613, 8, 5)

    GLASS = (150, 186, 178)
    GLASS_DK = (104, 140, 138)
    GLASS_HI = (206, 230, 222)
    BED = ((150, 74, 86), (176, 132, 60), (128, 92, 148), (188, 168, 92))

    # ---- perimeter: a low stone wall and a hedge inside it ----------------
    per = pygame.Rect(int(w * 0.03), int(h * 0.04), int(w * 0.94), int(h * 0.92))
    pygame.draw.rect(s, lm_LIMESTONE_DK, per, 5)
    pygame.draw.rect(s, lm_OUTLINE, per, 1)
    pygame.draw.rect(s, lm_TREE_DK, per.inflate(-14, -14), 4)

    # ---- the main allee: gravel, north gate down to the house -------------
    cx, cy = w * 0.42, h * 0.34
    gate_x = int(w * 0.42)
    lm__thick_path(s, [(gate_x, per.top), (gate_x, int(h * 0.86))],
                   int(h * 0.045), lm_GRAVEL, lm_GRAVEL_DK)
    lm__thick_path(s, [(per.left + 8, int(h * 0.70)), (per.right - 8, int(h * 0.70))],
                   int(h * 0.035), lm_GRAVEL, lm_GRAVEL_DK)
    # a curving walk out to the Japanese garden
    walk = [(gate_x, int(h * 0.50)), (int(w * 0.55), int(h * 0.46)),
            (int(w * 0.64), int(h * 0.44)), (int(w * 0.70), int(h * 0.52))]
    lm__thick_path(s, walk, max(3, int(h * 0.022)), lm_GRAVEL, lm_GRAVEL_DK)

    # ---- formal parterre beds, north-east quarter -------------------------
    bx0, by0 = int(w * 0.58), int(h * 0.10)
    for row in range(3):
        for col in range(3):
            bx = bx0 + col * int(w * 0.11)
            by = by0 + row * int(h * 0.09)
            bw2, bh2 = int(w * 0.085), int(h * 0.062)
            lm__r(s, lm_DIRT_DK, bx, by, bw2, bh2)
            lm__r(s, BED[(row * 3 + col) % len(BED)], bx + 1, by + 1, bw2 - 2, bh2 - 2)
            pygame.draw.rect(s, lm_OUTLINE, (bx, by, bw2, bh2), 1)
    # boxwood edging along the allee
    for yy in range(int(h * 0.10), int(h * 0.64), 12):
        lm__r(s, lm_TREE_DK, gate_x - int(w * 0.055), yy, 5, 8)
        lm__r(s, lm_TREE_DK, gate_x + int(w * 0.045), yy, 5, 8)

    # ---- SEIWA-EN: the lake, the island, the drum bridge ------------------
    lake = lm__blob(w * 0.750, h * 0.430, w * 0.125, h * 0.135, 907, n=24, amp=0.16)
    lm__water_poly(s, lake, 907, rim=lm_GRASS_DK)
    isl = lm__blob(w * 0.775, h * 0.415, w * 0.032, h * 0.030, 911, n=14, amp=0.25)
    lm__poly(s, lm_GRASS, isl)
    lm__poly(s, lm_OUTLINE, isl, 1)
    lm__tree(s, w * 0.775, h * 0.410, max(3, int(h * 0.022)), 913)
    # drum bridge: a red arch over the neck of the lake
    bx1, bx2 = int(w * 0.665), int(w * 0.735)
    by = int(h * 0.482)
    arc = lm__bowed(bx1, bx2, by, -int(h * 0.045))
    lm__thick_path(s, arc, 4, (150, 62, 54))
    lm__thick_path(s, arc, 1, (196, 108, 88))
    # teahouse on the far bank
    th = lm__block(s, int(w * 0.855), int(h * 0.335), int(w * 0.075), int(h * 0.062),
                   (96, 72, 54), depth=3, drop=3, wall=lm_LIMESTONE_DK)
    lm__r(s, (58, 46, 38), th.x, th.y, th.w, 2)
    # stone lanterns round the shore
    for (lx0, ly0) in ((0.648, 0.386), (0.742, 0.545), (0.868, 0.452)):
        px, py = int(w * lx0), int(h * ly0)
        lm__r(s, lm_SHADOW, px + 2, py + 2, 5, 8)
        lm__r(s, lm_LIMESTONE, px, py, 5, 8)
        lm__r(s, lm_LIMESTONE_DK, px - 1, py - 2, 7, 3)

    # ---- THE LINNEAN HOUSE: 1882, a long glass barrel ---------------------
    lh_x, lh_y = int(w * 0.10), int(h * 0.755)
    lh_w, lh_h = int(w * 0.38), int(h * 0.105)
    lm__r(s, lm_SHADOW, lh_x + 4, lh_y + 4, lh_w, lh_h)
    lm__r(s, lm_LIMESTONE_DK, lh_x, lh_y, lh_w, lh_h)
    lm__r(s, GLASS, lh_x + 3, lh_y + 3, lh_w - 6, lh_h - 6)
    for gx in range(lh_x + 6, lh_x + lh_w - 4, 7):
        lm__line(s, GLASS_DK, (gx, lh_y + 3), (gx, lh_y + lh_h - 4))
    lm__r(s, GLASS_HI, lh_x + 4, lh_y + 4, lh_w - 8, 2)
    # the limestone end wall with its three niches
    lm__r(s, lm_LIMESTONE, lh_x, lh_y - 3, int(w * 0.055), lh_h + 6)
    pygame.draw.rect(s, lm_OUTLINE, (lh_x, lh_y - 3, int(w * 0.055), lh_h + 6), 1)
    pygame.draw.rect(s, lm_OUTLINE, (lh_x, lh_y, lh_w, lh_h), 1)

    # ---- TOWER GROVE HOUSE and Shaw's mausoleum ---------------------------
    hx, hy = int(w * 0.745), int(h * 0.745)
    hr = lm__block(s, hx, hy, int(w * 0.115), int(h * 0.105), lm_TERRACOTTA,
                   depth=4, drop=5, wall=lm_BRICK_DK)
    lm__r(s, lm_BRICK, hr.x + 2, hr.y + 2, hr.w - 4, hr.h - 4)
    # the belvedere tower on its corner
    lm__r(s, lm_SHADOW, hr.right - 8, hr.y - 12, 12, 16)
    lm__r(s, lm_BRICK_DK, hr.right - 11, hr.y - 15, 12, 18)
    lm__r(s, lm_VERDIGRIS, hr.right - 12, hr.y - 18, 14, 4)
    pygame.draw.rect(s, lm_OUTLINE, (hr.right - 11, hr.y - 15, 12, 18), 1)
    # mausoleum: a small domed limestone box in its own lawn
    mx, my = int(w * 0.905), int(h * 0.795)
    lm__r(s, lm_SHADOW, mx + 3, my + 3, 16, 14)
    lm__r(s, lm_LIMESTONE, mx, my, 16, 14)
    pygame.draw.circle(s, lm_LIMESTONE_DK, (mx + 8, my), 8)
    pygame.draw.circle(s, lm_OUTLINE, (mx + 8, my), 8, 1)
    pygame.draw.rect(s, lm_OUTLINE, (mx, my, 16, 14), 1)

    # ---- THE CLIMATRON ----------------------------------------------------
    # Fuller's dome, 1960. In plan it is a circle of glass on a triangulated
    # net with nothing holding it up from inside, so that is what gets drawn:
    # rings, spokes, and the chords between them that make the triangles.
    rad = int(min(w, h) * 0.175)
    icx, icy = int(cx), int(cy)
    pygame.draw.circle(s, lm_SHADOW, (icx + 5, icy + 6), rad + 2)
    # the concrete apron it stands on
    pygame.draw.circle(s, lm_CONCRETE_DK, (icx, icy), rad + 7)
    pygame.draw.circle(s, lm_CONCRETE, (icx, icy), rad + 5)
    pygame.draw.circle(s, lm_OUTLINE, (icx, icy), rad + 7, 1)
    # glass, shaded from the top-left so it reads as a dome and not a disc
    for i in range(rad, 0, -2):
        t = i / float(rad)
        col = (int(GLASS_DK[0] + (GLASS_HI[0] - GLASS_DK[0]) * (1.0 - t) ** 1.4),
               int(GLASS_DK[1] + (GLASS_HI[1] - GLASS_DK[1]) * (1.0 - t) ** 1.4),
               int(GLASS_DK[2] + (GLASS_HI[2] - GLASS_DK[2]) * (1.0 - t) ** 1.4))
        pygame.draw.circle(s, col, (icx - int(rad * 0.10 * t), icy - int(rad * 0.12 * t)), i)
    # the geodesic net: latitude rings plus spokes, then chords for triangles
    rings = [rad, int(rad * 0.78), int(rad * 0.55), int(rad * 0.31)]
    for rr in rings:
        pygame.draw.circle(s, GLASS_DK, (icx, icy), rr, 1)
    spokes = 16
    for i in range(spokes):
        a = 2.0 * math.pi * i / spokes
        lm__line(s, GLASS_DK, (icx, icy),
                 (icx + math.cos(a) * rad, icy + math.sin(a) * rad))
    for ri in range(len(rings) - 1):
        r_out, r_in = rings[ri], rings[ri + 1]
        for i in range(spokes):
            a0 = 2.0 * math.pi * i / spokes
            a1 = 2.0 * math.pi * (i + 1) / spokes
            lm__line(s, GLASS_DK,
                     (icx + math.cos(a0) * r_out, icy + math.sin(a0) * r_out),
                     (icx + math.cos(a1) * r_in, icy + math.sin(a1) * r_in))
    # specular highlight, north-west, and the hard rim
    for k in range(3):
        pygame.draw.arc(s, GLASS_HI,
                        (icx - rad + 4 + k, icy - rad + 4 + k,
                         rad * 2 - 8 - 2 * k, rad * 2 - 8 - 2 * k),
                        math.radians(150), math.radians(215), 1)
    pygame.draw.circle(s, lm_OUTLINE, (icx, icy), rad, 2)
    # the entry vestibule on the south side
    lm__r(s, lm_SHADOW, icx - 7, icy + rad - 1, 16, 12)
    lm__r(s, lm_LIMESTONE, icx - 9, icy + rad - 3, 16, 12)
    pygame.draw.rect(s, lm_OUTLINE, (icx - 9, icy + rad - 3, 16, 12), 1)

    # ---- planting: specimen trees, but never over the dome ----------------
    for (tx, ty, rr) in ((0.10, 0.16, 0.030), (0.16, 0.30, 0.026),
                         (0.09, 0.46, 0.028), (0.20, 0.58, 0.024),
                         (0.62, 0.30, 0.026), (0.90, 0.30, 0.028),
                         (0.90, 0.50, 0.026), (0.32, 0.88, 0.024),
                         (0.55, 0.88, 0.026), (0.06, 0.86, 0.024)):
        lm__tree(s, w * tx, h * ty, max(3, int(min(w, h) * rr)), 617)

    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


def lm__bake_lambert(w, h):
    """Yamasaki's four arched terminal shells, runway and aircraft apron."""
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    s.fill((86, 90, 94))
    # runway on the north edge and the MetroLink/road spine down the west
    lm__r(s, (52, 54, 58), 0, int(h * 0.13), w, max(18, int(h * 0.12)))
    for x in range(10, w - 10, 32):
        lm__r(s, (222, 214, 164), x, int(h * 0.19), 16, 2)
    lm__r(s, (64, 66, 70), int(w * 0.18), 0, max(18, int(w * 0.12)), h)
    # the 1956 terminal: four linked concrete vaults
    tx, ty = int(w * 0.30), int(h * 0.48)
    tw, th = int(w * 0.58), int(h * 0.22)
    lm__r(s, lm_SHADOW, tx + 6, ty + 7, tw, th)
    lm__r(s, (184, 184, 176), tx, ty, tw, th)
    vault = max(16, tw // 4)
    for i in range(4):
        x0 = tx + i * vault
        pygame.draw.arc(s, (238, 234, 220),
                        (x0, ty - th // 2, vault + 3, th + 3), 0, math.pi, 4)
        lm__r(s, (60, 82, 94), x0 + 5, ty + th // 2, vault - 8, th // 3)
    pygame.draw.rect(s, lm_OUTLINE, (tx, ty, tw, th), 2)
    # two tiny aircraft make the apron read instantly from above
    for ax, ay, flip in ((int(w * 0.48), int(h * 0.34), 1),
                         (int(w * 0.72), int(h * 0.80), -1)):
        pygame.draw.line(s, (222, 224, 220), (ax - 18, ay), (ax + 18, ay), 4)
        pygame.draw.line(s, (222, 224, 220), (ax, ay - 13 * flip),
                         (ax, ay + 15 * flip), 3)
        pygame.draw.polygon(s, (222, 224, 220),
                            ((ax, ay - 17 * flip), (ax - 4, ay - 9 * flip),
                             (ax + 4, ay - 9 * flip)))
    pygame.draw.rect(s, lm_OUTLINE, (0, 0, w, h), 1)
    return s


lm__BAKERS = {
    "lambert": lm__bake_lambert,
    "arch": lm__bake_arch,
    "stadium": lm__bake_stadium,
    "ted_drewes": lm__bake_ted_drewes,
    "brewery": lm__bake_brewery,
    "forest_park": lm__bake_forest_park,
    "central_west_end": lm__bake_cwe,
    "the_hill": lm__bake_the_hill,
    "delmar_loop": lm__bake_delmar_loop,
    "tower_grove": lm__bake_tower_grove,
    "grand_center": lm__bake_grand_center,
    "water_tower": lm__bake_water_tower,
    "bevo": lm__bake_bevo,
    "courthouse": lm__bake_courthouse,
    "union_station": lm__bake_union_station,
    "city_museum": lm__bake_city_museum,
    "botanical": lm__bake_botanical,
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


def lm_draw_arch_foreground(surface, rect, camera_clip=None):
    """Draw the Arch's elevated steel after actors, clipped to its footprint."""
    rect = pygame.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    area = rect.clip(surface.get_rect())
    if camera_clip is not None:
        area = area.clip(pygame.Rect(camera_clip))
    if area.width <= 0 or area.height <= 0:
        return
    key = (rect.width, rect.height)
    art = lm__FG_CACHE.get(key)
    if art is None:
        art = lm__bake_arch_foreground(rect.width, rect.height)
        try:
            if pygame.display.get_surface() is not None:
                art = art.convert_alpha()
        except pygame.error:
            pass
        lm__FG_CACHE[key] = art
    old = surface.get_clip()
    try:
        surface.set_clip(area)
        surface.blit(art, rect.topleft)
    finally:
        surface.set_clip(old)

# ==========================================================
# Baked audio: snd
# ==========================================================
"""Procedurally synthesised effects plus the packaged MIDI soundtrack.

The rest of this project bakes every pixel it draws; the audio does the same
thing with waveforms. Everything here is written into `array('h')` buffers and
handed to `pygame.mixer.Sound(buffer=...)`, which needs nothing but the
standard library - deliberately NOT `pygame.sndarray`, which hard-imports
numpy. A full bank of ~40 sounds bakes in about a tenth of a second at boot,
against the second the sprite bake already costs.

Channel map. The reserved channels below are never stolen by a fire-and-forget
Sound.play(), because an engine note or a siren that gets cut out from under
you is far more noticeable than a missing bin-lid clatter:

    0-1   engine A / B   crossfade pair, looping
    2     tyres          screech loop, volume-driven, never re-triggered
    3     siren          the nearest cop only
    4-5   radio          crossfade pair, looping
    6     ambient        river / cicadas / brewery, crossfaded by district
    7     UI             pickups, chimes, level-ups
    8+    SFX pool       impacts, gunshots, yells, explosions
"""
import array as _array

snd_SR = 22050
GAME_MUSIC_SOURCE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'music', 'AUD_HO1036.mid')
GAME_MUSIC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'music', 'gloria-8bit.wav')
GAME_MUSIC_VOLUME = 0.32
snd_CH_ENGINE_A = 0
snd_CH_ENGINE_B = 1
snd_CH_TYRES = 2
snd_CH_SIREN = 3
snd_CH_RADIO_A = 4
snd_CH_RADIO_B = 5
snd_CH_AMBIENT = 6
snd_CH_UI = 7
snd_RESERVED = 8
snd_CHANNELS = 24

# Engine loops are baked at these fundamental *periods in whole samples*, not
# at frequencies. Sound.play(loops=-1) repeats the whole buffer, so a loop that
# is not a whole number of cycles clicks once per lap; deriving the frequency
# from an integer period makes every loop seamless by construction.
snd_ENGINE_PERIODS = (245, 220, 196, 175, 156, 139, 124, 110, 98, 87, 78, 70)
snd_ENGINE_CYCLES = 4

snd__bank = {}
snd__ready = False
snd__enabled = False
snd__rng = random.Random(0xA0D10)   # deterministic: the bank is identical every boot
snd__last_played = {}               # key -> frame, for rate limiting
snd__frame = 0
snd__master = 0.85
snd__duck_until = 0                 # frame the radio comes back up on


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------
def snd__saw(ph):
    return ph * 2.0 - 1.0


def snd__sqr(ph):
    return 1.0 if ph < 0.5 else -1.0


def snd__tri(ph):
    return 4.0 * abs(ph - 0.5) - 1.0


def snd__env(i, n, k=3.0):
    """Exponential decay from 1 to 0 over n samples."""
    if n <= 0:
        return 0.0
    return max(0.0, 1.0 - i / float(n)) ** k


def snd__buf(samples, gain=1.0):
    """Interleave a mono float list into a clipped stereo 16-bit buffer."""
    out = _array.array('h', bytes(4 * len(samples)))
    for i, v in enumerate(samples):
        s = int(max(-1.0, min(1.0, v * gain)) * 30000)
        out[i * 2] = s
        out[i * 2 + 1] = s
    return out


def snd__sound(samples, gain=1.0):
    try:
        return pygame.mixer.Sound(buffer=snd__buf(samples, gain))
    except (pygame.error, ValueError):
        return None


def snd__noise():
    return snd__rng.uniform(-1.0, 1.0)


# --------------------------------------------------------------------------
# the bank
# --------------------------------------------------------------------------
def snd__make_engine(period, load=False):
    """One engine loop: stacked saws plus a square sub and combustion grit.

    The saw at the fundamental is the exhaust note, the octave above is the
    rasp, the square an octave below is the lump you feel rather than hear,
    and the noise is what stops it sounding like a test tone.
    """
    n = period * snd_ENGINE_CYCLES
    out = []
    y = 0.0
    for i in range(n):
        ph = (i / float(period)) % 1.0
        v = (snd__saw(ph) * 0.45
             + snd__saw((ph * 2.0 + 0.3) % 1.0) * 0.22
             + snd__sqr((ph * 0.5) % 1.0) * 0.18
             + snd__noise() * (0.09 if load else 0.06))
        y = y + (v - y) * 0.25          # one-pole lowpass; takes the fizz off
        out.append(y)
    return out


def snd__make_screech():
    """Band-limited noise with a rubber judder on it."""
    n = int(snd_SR * 0.40)
    out = []
    lo = lo2 = sub = 0.0
    for i in range(n):
        x = snd__noise()
        lo = lo + (x - lo) * 0.35
        lo2 = lo2 + (lo - lo2) * 0.35
        sub = sub + (lo2 - sub) * 0.06
        band = lo2 - sub                          # crude bandpass ~1.2-2.5kHz
        am = 0.72 + 0.28 * math.sin(i * math.tau * 30.0 / snd_SR)
        out.append(band * am)
    return out


def snd__make_impact(severity):
    """Noise burst that darkens as it decays, a low thump, and some metal.

    The sweeping lowpass is the whole trick: a noise burst at a fixed
    brightness reads as hiss, and the same burst getting darker as it dies
    reads as something heavy hitting something else.
    """
    n = int(snd_SR * (0.18 + 0.04 * severity))
    thump_f = 90.0 - 12.0 * severity
    partials = ((900.0, 0.10), (1400.0, 0.07), (2100.0, 0.05))
    out = []
    y = 0.0
    for i in range(n):
        e = snd__env(i, n, 3.0)
        a = 0.90 - 0.70 * (i / float(n))          # sweep the filter closed
        y = y + (snd__noise() - y) * a
        v = y * e * (0.35 + 0.16 * severity)
        v += math.sin(i * math.tau * thump_f / snd_SR) * snd__env(i, n, 5.0) * 0.45
        if i < n * 0.35:
            for f, amp in partials:
                v += math.sin(i * math.tau * f / snd_SR) * snd__env(i, int(n * 0.35), 4.0) * amp
        out.append(v)
    return out


def snd__make_scrape():
    n = int(snd_SR * 0.30)
    out = []
    y = 0.0
    for i in range(n):
        y = y + (snd__noise() - y) * 0.5
        ring = math.sin(i * math.tau * 1800.0 / snd_SR) * 0.10
        out.append((y * 0.35 + ring) * (0.6 + 0.4 * math.sin(i * 0.004)))
    return out


def snd__make_punch(connect):
    n = int(snd_SR * (0.11 if connect else 0.07))
    out = []
    y = 0.0
    for i in range(n):
        e = snd__env(i, n, 3.5)
        y = y + (snd__noise() - y) * (0.22 if connect else 0.75)
        v = y * e * (0.55 if connect else 0.22)
        if connect:
            v += math.sin(i * math.tau * 110.0 / snd_SR) * snd__env(i, n, 4.0) * 0.5
        out.append(v)
    return out


def snd__make_gunshot():
    """With the downtown slapback - the canyon slap between buildings is what
    a gunshot actually sounds like on Washington Avenue."""
    n = int(snd_SR * 0.30)
    dry = []
    y = 0.0
    for i in range(n):
        e = snd__env(i, int(snd_SR * 0.14), 4.0)
        y = y + (snd__noise() - y) * max(0.12, 0.95 - 3.0 * (i / float(n)))
        v = y * e * 0.8
        v += math.sin(i * math.tau * 180.0 / snd_SR) * snd__env(i, int(snd_SR * 0.09), 5.0) * 0.4
        dry.append(v)
    d1 = int(snd_SR * 0.055)
    d2 = int(snd_SR * 0.110)
    out = list(dry)
    for i in range(n):
        if i >= d1:
            out[i] += dry[i - d1] * 0.30
        if i >= d2:
            out[i] += dry[i - d2] * 0.12
    return out


def snd__make_explosion():
    n = int(snd_SR * 0.90)
    out = []
    y = 0.0
    phase = 0.0
    for i in range(n):
        t = i / float(n)
        # (1) the chest hit: a sine sweeping 90 -> 35 Hz
        f = 90.0 - 55.0 * min(1.0, i / (snd_SR * 0.35))
        phase += math.tau * f / snd_SR
        v = math.sin(phase) * snd__env(i, int(snd_SR * 0.45), 2.0) * 0.75
        # (2) broadband noise that darkens as it decays - the layer that sells it
        a = max(0.15, 0.9 - 0.75 * t)
        y = y + (snd__noise() - y) * a
        atk = min(1.0, i / (snd_SR * 0.06))
        v += y * atk * snd__env(i, n, 2.2) * 0.55
        out.append(v)
    # (3) debris ticks scattered through the tail
    for _ in range(9):
        at = snd__rng.randint(int(snd_SR * 0.25), n - 400)
        amp = snd__rng.uniform(0.10, 0.26)
        for k in range(300):
            out[at + k] += snd__noise() * snd__env(k, 300, 4.0) * amp
    return out


def snd__make_siren(kind, pitch=1.0):
    """Two genuinely different sirens, because this city genuinely has two
    police forces and they do not sound the same.

    'yelp' is the city: a fast electronic sweep, aggressive and modern.
    'wail' is the county: an old mechanical rise and fall, slower and sadder.
    """
    if kind == 'yelp':
        period = 0.25
        f0, f1 = 700.0 * pitch, 1500.0 * pitch
    else:
        period = 2.40
        f0, f1 = 500.0 * pitch, 1300.0 * pitch
    n = int(snd_SR * period * 2)
    out = []
    phase = 0.0
    for i in range(n):
        t = (i / float(n)) * 2.0
        k = t if t < 1.0 else 2.0 - t          # up then down
        if kind == 'yelp':
            k = (i % int(snd_SR * period)) / float(int(snd_SR * period))
        f = f0 + (f1 - f0) * k
        phase += math.tau * f / snd_SR
        v = snd__tri(((phase / math.tau) % 1.0)) * 0.42
        if kind == 'wail':
            v += math.sin(phase * 3.0) * 0.15   # the mechanical rasp
        out.append(v)
    return out


def snd__make_yell(seed, contour):
    """A pitched buzz through a couple of resonances - no words, but the
    prosody carries it. Two of these get local cadences: a flat two-syllable
    fall, and the rising two-syllable question everybody here asks you."""
    rng = random.Random(seed)
    base = rng.uniform(150.0, 250.0)
    n = int(snd_SR * 0.34)
    out = []
    phase = 0.0
    y = 0.0
    for i in range(n):
        t = i / float(n)
        if contour == 'fall':                   # "HOO-sier"
            k = 1.10 - 0.35 * t
            amp = 1.0 if t < 0.45 else (0.85 if t < 0.55 else 1.0)
        elif contour == 'question':             # "where'd you go to...?"
            k = 0.92 + 0.42 * t
            amp = 1.0 if t < 0.40 else (0.7 if t < 0.52 else 1.0)
        else:
            k = 1.0 + 0.25 * math.sin(t * 4.0)
            amp = 1.0
        phase += math.tau * base * k / snd_SR
        v = snd__saw((phase / math.tau) % 1.0)
        y = y + (v - y) * 0.30                  # vowel-ish resonance
        env = min(1.0, t * 8.0) * snd__env(i, n, 1.6)
        out.append(y * env * amp * 0.55)
    return out


def snd__make_chime(notes, hold=0.18):
    """Triangle arpeggio with a detuned second voice."""
    per = int(snd_SR * hold)
    out = [0.0] * (per * len(notes))
    for k, f in enumerate(notes):
        for i in range(per):
            e = min(1.0, i / 60.0) * snd__env(i, per, 3.0)
            ph = (i * f / snd_SR) % 1.0
            ph2 = (i * f * 1.003 / snd_SR) % 1.0
            out[k * per + i] += (snd__tri(ph) * 0.5 + snd__tri(ph2) * 0.3) * e * 0.5
    return out


def snd__make_train_horn():
    """The real grade-crossing signal, and the single most St. Louis sound
    available: three notes a minor third apart, which is exactly why a train
    horn sounds like a train horn and not like a trumpet."""
    n = int(snd_SR * 2.2)
    out = []
    y = 0.0
    for i in range(n):
        env = min(1.0, i / (snd_SR * 0.20)) * (
            1.0 if i < n * 0.65 else snd__env(i - int(n * 0.65), int(n * 0.35), 1.6))
        v = 0.0
        for f, a in ((311.0, 0.40), (370.0, 0.34), (466.0, 0.26)):
            v += snd__saw((i * f / snd_SR) % 1.0) * a
        y = y + (v - y) * 0.18
        out.append(y * env * 0.55)
    return out


def snd__make_cicadas():
    n = int(snd_SR * 1.0)
    out = []
    y = lo = 0.0
    for i in range(n):
        y = y + (snd__noise() - y) * 0.45
        lo = lo + (y - lo) * 0.10
        band = y - lo
        am = 0.5 + 0.5 * math.sin(i * math.tau * 12.0 / snd_SR)
        out.append(band * am * 0.22)
    return out


def snd__make_vehicle_signature(kind):
    """Short spatial cues for rare/service vehicles before they enter view."""
    n = int(snd_SR * (0.48 if kind == 'bigblock' else 0.34))
    out = []
    phase = 0.0
    filtered = 0.0
    for i in range(n):
        t = i / float(n)
        env = min(1.0, t * 10.0) * snd__env(i, n, 1.4)
        if kind == 'bigblock':
            freq = 48.0 + 7.0 * math.sin(t * math.tau * 4.0)
            phase += math.tau * freq / snd_SR
            pulse = 0.68 + 0.32 * math.sin(t * math.tau * 8.0)
            value = (snd__saw((phase / math.tau) % 1.0) * 0.46
                     + math.sin(phase * 2.0) * 0.30) * pulse
        elif kind == 'cart_rattle':
            tick = 1.0 if i % max(1, int(snd_SR * 0.047)) < 38 else 0.0
            filtered += (snd__noise() - filtered) * 0.42
            value = filtered * tick * 0.55 + math.sin(i * math.tau * 1640 / snd_SR) * tick * 0.18
        elif kind == 'hydraulic':
            filtered += (snd__noise() - filtered) * (0.08 + t * 0.35)
            value = filtered * 0.42 + math.sin(i * math.tau * (70 + 90 * t) / snd_SR) * 0.30
        else:  # reverse beep
            gate = 1.0 if (i // int(snd_SR * 0.09)) % 2 == 0 else 0.0
            value = snd__sqr((i * 930.0 / snd_SR) % 1.0) * gate * 0.42
        out.append(value * env)
    return out


def snd_bake():
    """Bake the whole bank. Safe to call twice; a no-op without a mixer."""
    global snd__ready, snd__enabled
    if snd__ready:
        return
    snd__ready = True
    if pygame.mixer.get_init() is None:
        snd__enabled = False
        return
    try:
        pygame.mixer.set_num_channels(snd_CHANNELS)
        pygame.mixer.set_reserved(snd_RESERVED)
    except pygame.error:
        snd__enabled = False
        return

    b = snd__bank
    for i, period in enumerate(snd_ENGINE_PERIODS):
        b[f'engine{i}'] = snd__sound(snd__make_engine(period), 0.9)
        b[f'engineload{i}'] = snd__sound(snd__make_engine(period, load=True), 0.9)
    b['screech'] = snd__sound(snd__make_screech(), 0.8)
    b['scrape'] = snd__sound(snd__make_scrape(), 0.7)
    for sev in range(3):
        b[f'impact{sev}'] = snd__sound(snd__make_impact(sev), 0.85)
    b['punch'] = snd__sound(snd__make_punch(True), 0.8)
    b['whiff'] = snd__sound(snd__make_punch(False), 0.6)
    b['gun'] = snd__sound(snd__make_gunshot(), 0.8)
    b['boom'] = snd__sound(snd__make_explosion(), 1.0)
    for p, tag in ((0.94, 'lo'), (1.0, 'mid'), (1.06, 'hi')):
        b[f'yelp{tag}'] = snd__sound(snd__make_siren('yelp', p), 0.55)
        b[f'wail{tag}'] = snd__sound(snd__make_siren('wail', p), 0.55)
    for i, contour in enumerate(('fall', 'question', 'flat', 'flat')):
        b[f'yell{i}'] = snd__sound(snd__make_yell(1000 + i, contour), 0.7)
    b['pickup'] = snd__sound(snd__make_chime((659.3, 987.8)), 0.6)
    b['weapon'] = snd__sound(snd__make_chime((659.3, 830.6, 987.8)), 0.6)
    b['frenzy'] = snd__sound(snd__make_chime((659.3, 830.6, 987.8, 1318.5)), 0.75)
    b['cash'] = snd__sound(snd__make_chime((987.8, 1318.5), 0.13), 0.6)
    b['bad'] = snd__sound(snd__make_chime((330.0, 233.1), 0.22), 0.6)
    b['horn'] = snd__sound(snd__make_train_horn(), 0.7)
    b['cicadas'] = snd__sound(snd__make_cicadas(), 0.5)
    b['bigblock'] = snd__sound(snd__make_vehicle_signature('bigblock'), 0.78)
    b['cart_rattle'] = snd__sound(snd__make_vehicle_signature('cart_rattle'), 0.64)
    b['hydraulic'] = snd__sound(snd__make_vehicle_signature('hydraulic'), 0.70)
    b['reverse_beep'] = snd__sound(snd__make_vehicle_signature('reverse_beep'), 0.58)
    for index, notes in enumerate(((220.0, 330.0, 440.0),
                                   (293.7, 370.0, 523.3),
                                   (196.0, 246.9, 293.7))):
        b[f'radio{index}'] = snd__sound(snd__make_chime(notes, 0.10), 0.42)
    snd__enabled = any(v is not None for v in b.values())


# --------------------------------------------------------------------------
# playback
# --------------------------------------------------------------------------
def snd_set_frame(frame):
    global snd__frame
    snd__frame = frame


def snd_pan_volume(world_pos, cam_pos, vol=1.0, reach=620.0):
    """Equal-power pan plus distance rolloff, as (left, right)."""
    dx = world_pos[0] - cam_pos[0]
    dy = world_pos[1] - cam_pos[1]
    d = math.hypot(dx, dy)
    v = vol * snd__master * max(0.0, 1.0 - d / reach) ** 1.5
    if v <= 0.0:
        return (0.0, 0.0)
    pan = max(-1.0, min(1.0, dx / (SCREEN_WIDTH * 0.5)))
    return (v * math.sqrt((1.0 - pan) * 0.5), v * math.sqrt((1.0 + pan) * 0.5))


def snd_rate_ok(key, gap):
    """True if this key may fire again, and arm it if so.

    Without this a wall scrape fires every single step - the collision path
    runs at 60Hz - and the city becomes a wall of noise.
    """
    last = snd__last_played.get(key, -10 ** 9)
    if snd__frame - last < gap:
        return False
    snd__last_played[key] = snd__frame
    return True


def snd_play(key, world_pos=None, cam_pos=None, vol=1.0, gap=0, reach=620.0):
    """Fire and forget on the SFX pool.

    `gap` rate-limits a key to one hit every N frames. Without it a wall
    scrape fires every single step and the city becomes a wall of noise.
    """
    if gap and not snd_rate_ok(key, gap):
        return None
    if not snd__enabled:
        return None
    sound = snd__bank.get(key)
    if sound is None:
        return None
    ch = pygame.mixer.find_channel(True)
    if ch is None:
        return None
    ch.play(sound)
    if world_pos is not None and cam_pos is not None:
        left, right = snd_pan_volume(world_pos, cam_pos, vol, reach)
        if left <= 0.0 and right <= 0.0:
            ch.stop()
            return None
        ch.set_volume(left, right)
    else:
        ch.set_volume(vol * snd__master)
    return ch


def snd_loop(channel, key, vol, left=None, right=None):
    """Hold a looping sound on a reserved channel, restarting only if it is
    not already the thing playing there."""
    if not snd__enabled:
        return
    sound = snd__bank.get(key)
    ch = pygame.mixer.Channel(channel)
    if sound is None:
        ch.stop()
        return
    if ch.get_sound() is not sound:
        ch.play(sound, loops=-1)
    if left is None:
        ch.set_volume(vol * snd__master)
    else:
        ch.set_volume(left, right)


def snd_stop(channel):
    if not snd__enabled:
        return
    pygame.mixer.Channel(channel).stop()


def snd_duck(frames=24):
    """Drop the ambient bed for a moment so an explosion feels enormous."""
    global snd__duck_until
    snd__duck_until = max(snd__duck_until, snd__frame + frames)


def snd_ducking():
    return 0.35 if snd__frame < snd__duck_until else 1.0


def snd_engine_bucket(speed_frac):
    n = len(snd_ENGINE_PERIODS)
    return max(0, min(n - 1, int(speed_frac * (n - 1) + 0.5)))


# ============================================================
# Camera
# ============================================================
class Job:
    """One courier run: collect at a St. Louis landmark, drop at another one
    before the clock runs out.

    This is the loop the city exists to serve. The timer deliberately does not
    start until the cargo is aboard, so exploring toward a pickup is never
    punished - the pressure only switches on once you have accepted it.
    """

    # What you are carrying now depends on WHERE you collected it. The old
    # nine-item list was picked at random with no relation to the pickup, so
    # you would load a BREWERY KEG at Ted Drewes and a CRATE OF PROVEL at the
    # Botanical Garden.
    CARGO_BY_PICKUP = {
        "Lambert Airport": ("A MISROUTED SUITCASE", "JET ENGINE PARTS",
                            "A BOX OF TWA POSTERS"),
        "Anheuser-Busch Brewery": ("BREWERY KEG", "A PALLET OF LONGNECKS",
                                   "BEECHWOOD CHIPS", "CLYDESDALE TACK"),
        "Ted Drewes": ("A CONCRETE, UPSIDE DOWN", "FROZEN CUSTARD",
                       "A CHRISTMAS TREE"),
        "Ted Drewes on Grand": ("A CONCRETE, UPSIDE DOWN", "FROZEN CUSTARD"),
        "The Hill": ("TOASTED RAVIOLI", "HOT SALAMI FROM GIOIA'S",
                     "A WHEEL OF VOLPI", "SUNDAY GRAVY, STILL HOT",
                     "A CASE OF BOCCE BALLS"),
        "Missouri Botanical Garden": ("A CRATE OF ORCHIDS", "CLIMATRON SEEDLINGS",
                                      "A KOI, IN A BAG"),
        "Tower Grove Park": ("FARMERS MARKET TOMATOES", "A PAVILION AWNING"),
        "Soulard Farmers Market": ("A BUSHEL OF PEACHES", "GUS'S PRETZELS",
                                   "TWENTY POUNDS OF ONIONS"),
        "Busch Stadium": ("BALLPARK NACHOS", "A CASE OF FOAM FINGERS",
                          "THE GROUNDSKEEPER'S TARP"),
        "Union Station": ("A TRUNK OFF THE 4:15", "HOTEL LINEN"),
        "City Museum": ("SOMETHING FROM THE ROOF", "A CRATE OF LOOSE PARTS",
                        "ONE BOWLING LANE"),
        "Old Courthouse": ("A BOX OF COURT RECORDS", "A ROLL OF BLUEPRINTS"),
        "Gateway Arch": ("A TRAM POD PART", "STAINLESS STEEL PANELS"),
        "Grand Center Arts District": ("A THEATRE ORGAN BENCH",
                                       "THE FOX'S MARQUEE BULBS",
                                       "A DOUBLE BASS"),
        "Central West End": ("STRAUB'S GROCERIES", "A BOX FROM LEFT BANK",
                             "A CRATE OF MOSAIC TILE"),
        "Delmar Loop": ("A CRATE OF RECORDS", "FITZ'S ROOT BEER",
                        "A WALK OF FAME STAR"),
        "Forest Park": ("MUNY COSTUMES", "A JEWEL BOX PALM",
                        "SOMETHING FROM THE ZOO"),
        "Fairground Park": ("MAY DAY BANNERS", "A CRATE OF BASEBALLS",
                            "PARK PAVILION CHAIRS"),
        "Compton Hill Water Tower": ("A PRESSURE GAUGE", "206 STEPS OF SCAFFOLD"),
        "Bissell Street Water Tower": ("A STANDPIPE GAUGE", "RED BRICK SAMPLES"),
        "Bevo Mill": ("BUREK, STILL WARM", "A SACK OF FLOUR"),
        "Cherokee Street": ("A PALLET OF ANTIQUES", "PAN DULCE AT DAWN",
                            "A LETTERPRESS DRAWER"),
        "Downtown": ("A LOFT'S WORTH OF BOXES", "SLINGER SPECIAL",
                     "A PALLET OF SHOE LASTS"),
    }
    #: fallback for anywhere without its own list
    CARGO = ("TOASTED RAVIOLI", "GOOEY BUTTER CAKE", "CRATE OF PROVEL",
             "BALLPARK NACHOS", "FROZEN CUSTARD", "SLINGER SPECIAL",
             "PORK STEAKS", "BOX OF FIREWORKS", "A CASE OF VESS",
             "GOOEY BUTTER, DAY OLD", "A COOLER OF PORK STEAKS",
             "SOMEBODY'S SCHNUCKS ORDER", "A BAG OF T-RAVS",
             "MAULL'S, BY THE CASE", "IMO'S, GETTING COLD",
             "A CROWN CANDY MALT, MELTING", "AN ST. PAUL SANDWICH",
             "FIVE POUNDS OF PROVEL", "A CASE OF KSHE BUMPER STICKERS")

    @classmethod
    def cargo_for(cls, pickup_name):
        """Something that plausibly comes from where you are standing."""
        pool = cls.CARGO_BY_PICKUP.get(pickup_name)
        return random.choice(pool if pool else cls.CARGO)

    # label, clock multiplier, base-payout multiplier, appropriate cargo pool.
    # Each card changes the way a route plays instead of merely renaming the
    # same box: rushes squeeze the clock, hot loads begin a chase, and heavy
    # hauls make the active vehicle carry real weight.
    KINDS = {
        'courier': ("COURIER", 1.00, 1.00, CARGO),
        'rush': ("RUSH", 0.72, 1.45,
                 ("FROZEN CUSTARD", "BALLPARK NACHOS", "SLINGER SPECIAL")),
        'hot': ("HOT LOAD", 1.00, 1.55,
                ("BOX OF FIREWORKS", "BREWERY KEG", "CRATE OF PROVEL")),
        'heavy': ("HEAVY HAUL", 1.18, 1.50,
                  ("BREWERY KEG", "CRATE OF PROVEL", "PORK STEAKS")),
    }

    def __init__(self, pickup, dropoff, kind='courier'):
        self.pickup = pickup
        self.dropoff = dropoff
        self.kind = kind if kind in self.KINDS else 'courier'
        self.label, time_scale, pay_scale, cargo_pool = self.KINDS[self.kind]
        self.cargo = (self.cargo_for(pickup[5]) if self.kind == 'courier'
                      else random.choice(cargo_pool))
        # The offer clock. Only runs before pickup; once the cargo is aboard
        # the delivery clock takes over.
        self.offer_left = int(JOB_OFFER_SECONDS * FPS)
        self.hot = False              # taken inside the chain window
        self.pickup_pos = landmark_dropoff_point(pickup)
        self.drop_pos = landmark_dropoff_point(dropoff)
        self.collected = False

        span = math.hypot(self.drop_pos[0] - self.pickup_pos[0],
                          self.drop_pos[1] - self.pickup_pos[1]) / TILE_SIZE
        self.span_tiles = span
        self.time_limit = max(JOB_MIN_SECONDS, span * JOB_SECONDS_PER_TILE) * time_scale
        self.steps_left = int(self.time_limit * FPS)
        self.base_reward = int((JOB_BASE_PAY + span * JOB_PAY_PER_TILE) * pay_scale)

    # -- state ------------------------------------------------------------
    @property
    def target_pos(self):
        return self.drop_pos if self.collected else self.pickup_pos

    @property
    def target_name(self):
        return (self.dropoff if self.collected else self.pickup)[5]

    @property
    def seconds_left(self):
        return max(0.0, self.steps_left / float(FPS))

    def collect(self):
        self.collected = True
        self.steps_left = int(self.time_limit * FPS)

    def tick(self):
        """Advance one sim step. True once the clock has run out."""
        if not self.collected:
            return False
        if self.steps_left > 0:
            self.steps_left -= 1
        return self.steps_left <= 0

    def payout(self, streak):
        """On-time reward, boosted by the current delivery streak, plus a
        bonus for the time you actually had left on the clock."""
        mult = 1.0 + JOB_STREAK_BONUS * min(streak, JOB_STREAK_CAP)
        spare = self.steps_left / float(max(1, int(self.time_limit * FPS)))
        return int(self.base_reward * mult * (1.0 + 0.35 * spare))

    @staticmethod
    def generate(exclude=None, kind='courier'):
        """Pair two landmarks that are far enough apart to be worth driving.

        Falls back to any distinct pair if the span filter finds nothing, so
        this can never return None and stall the loop.
        """
        pool = [lm for lm in LANDMARKS if lm[5] != exclude]
        if len(pool) < 2:
            pool = list(LANDMARKS)
        far = []
        for i, a in enumerate(pool):
            for b in pool[i + 1:]:
                span = math.hypot(a[0] - b[0], a[1] - b[1])
                if span >= JOB_MIN_TILE_SPAN:
                    far.append((a, b))
        pair = random.choice(far) if far else random.sample(list(LANDMARKS), 2)
        a, b = pair
        if random.random() < 0.5:
            a, b = b, a
        return Job(a, b, kind=kind)


class Frenzy:
    """A GTA1 Kill Frenzy: grab the icon, the screen screams a target and a
    clock, and you go berserk for a fat score payout and a free multiplier."""

    # kind -> (banner, target count, completion bonus)
    KINDS = {
        'ped': ("MOW DOWN {n} LOCALS", 14, 3500),
        'car': ("WRECK {n} MOTORS", 8, 6000),
        'cop': ("DROP {n} COPS", 6, 9000),
    }

    def __init__(self, kind):
        banner, target, bonus = self.KINDS[kind]
        self.kind = kind
        self.target = target
        self.remaining = target
        self.bonus = bonus
        self.steps_left = FRENZY_SECONDS * FPS
        self.banner = banner.replace("{n}", str(target))


class FootCop:
    """A mortal beat cop who can search alleys, pursue, arrest, and be knocked down."""

    def __init__(self, x, y):
        self.rect = pygame.Rect(0, 0, 14, 14)
        self.rect.center = (int(x), int(y))
        self.fx = float(x)
        self.fy = float(y)
        self.kind = peds_COP_KEY
        self.angle = 0.0            # facing, for the sight cone
        self.facing = 2
        self.anim = 0.0
        self.alert = 'search'
        self.last_seen = None
        self.search_timer = COP_FOOT_GIVEUP
        self.lost_timer = 0
        self.sight_range = COP_FOOT_SIGHT
        self.stuck = 0
        self.detour = random.choice((-1.0, 1.0))   # which way he rounds a block
        self.path = []           # walkable waypoints from walk_path()
        self.repath_in = 0       # steps until the route is recomputed
        self.path_goal = None    # what the current route was built for
        self.hp = COP_FOOT_HP
        self.hit_stun = 0
        self.down_timer = 0
        self.bump_cooldown = 0
        self.knock = pygame.Vector2()
        self.move_speed = COP_FOOT_SEARCH_SPEED
        self.chase_steps = 0

    def _walk(self, ang):
        """Try one full step along `ang`. True if he actually went anywhere."""
        nx = self.fx + math.cos(ang) * self.move_speed
        ny = self.fy + math.sin(ang) * self.move_speed
        probe = self.rect.copy()
        probe.center = (int(round(nx)), int(round(ny)))
        if (probe.left < 0 or probe.top < 0
                or probe.right > MAP_WIDTH or probe.bottom > MAP_HEIGHT):
            return False
        if is_blocked(probe):
            return False
        self.fx, self.fy = nx, ny
        self.rect.center = probe.center
        return True

    def tick_hit_state(self):
        """Apply knockback and return True while the officer cannot pursue."""
        if self.bump_cooldown > 0:
            self.bump_cooldown -= 1
        if self.knock.length_squared() > 0.05:
            nx, ny = self.fx + self.knock.x, self.fy + self.knock.y
            probe = self.rect.copy()
            probe.center = (int(round(nx)), int(round(ny)))
            if (0 <= probe.left and 0 <= probe.top
                    and probe.right <= MAP_WIDTH and probe.bottom <= MAP_HEIGHT
                    and not is_blocked(probe)):
                self.fx, self.fy = nx, ny
                self.rect.center = probe.center
            self.knock *= 0.76
        else:
            self.knock.update(0, 0)
        if self.down_timer > 0:
            self.down_timer -= 1
            self.anim = 0.0
            return True
        if self.hit_stun > 0:
            self.hit_stun -= 1
            return True
        return False

    def step_toward(self, target):
        """Walk a real route to the target.

        A straight line plus whiskers is not enough for someone on foot: a cop
        with a two-flat between him and the player slides along it, backs off,
        tries the other way, and oscillates at a fixed distance forever - he
        was measured holding a steady 270px for twenty-five seconds. So he
        gets an actual path (walk_path) over the tile grid, recomputed twice a
        second or whenever the target moves a tile, and walks its waypoints.
        The straight line is still tried first, because most of the time there
        is nothing in the way and a route would just round off his corners.
        """
        self.repath_in -= 1
        goal_tile = (int(target[0]) // TILE_SIZE, int(target[1]) // TILE_SIZE)
        if self.repath_in <= 0 or goal_tile != self.path_goal:
            self.path_goal = goal_tile
            self.repath_in = 30
            self.path = walk_path(self.rect.center, target) or []

        dist = math.hypot(target[0] - self.fx, target[1] - self.fy)
        if dist < 8.0:
            self.stuck += 1
            self.anim = (self.anim + 0.10) % 4.0
            return

        # Drop waypoints already reached, then aim at the next one.
        while self.path and math.hypot(self.path[0][0] - self.fx,
                                       self.path[0][1] - self.fy) < 10.0:
            self.path.pop(0)
        aim = self.path[0] if self.path else target
        want = math.atan2(aim[1] - self.fy, aim[0] - self.fx)

        before = dist
        if self._walk(want):
            self.angle = want
        else:
            # Clipping a corner between two waypoints; shave round it.
            for off in (0.7 * self.detour, -0.7 * self.detour,
                        1.4 * self.detour, -1.4 * self.detour):
                if self._walk(want + off):
                    self.angle = want + off
                    break
        after = math.hypot(target[0] - self.fx, target[1] - self.fy)
        if after < before - 0.5:
            self.stuck = 0
        else:
            self.stuck += 1
            if self.stuck > 20:
                self.stuck = 0
                self.detour = -self.detour
                self.repath_in = 0          # ask for a fresh route
        self.facing = peds_dir_index(math.cos(self.angle), math.sin(self.angle))
        self.anim = (self.anim + 0.22) % 4.0


class Camera:
    def __init__(self):
        self.x = 0
        self.y = 0
        # Smoothed look-ahead: the view leads the car in its direction of
        # travel so you see where you are going instead of sitting dead
        # centre. Eased toward the target so it never snaps.
        self.lead_x = 0.0
        self.lead_y = 0.0
        # Impact shake. Set by draw() from Game.shake each frame, folded into
        # apply()/apply_pos() only - center_on never touches it, so the sim and
        # the camera-pan tests read a stable self.x / self.y.
        self.shake_ox = 0.0
        self.shake_oy = 0.0

    def snap_to(self, rect):
        """Cut straight to a rect with no lead and no easing.

        Used when the player is teleported (respawn, load): easing across half
        a mile of city would otherwise smear the whole map past the camera.
        """
        self.lead_x = 0.0
        self.lead_y = 0.0
        self.center_on(rect)

    def center_on(self, rect, lead=(0.0, 0.0)):
        self.lead_x += (lead[0] - self.lead_x) * CAM_LEAD_EASE
        self.lead_y += (lead[1] - self.lead_y) * CAM_LEAD_EASE
        # Backstop. Whatever the caller asks for, the subject stays inside the
        # frame by at least the safe margin: a look-ahead that pushes the car
        # you are steering off the bottom of the screen is never the right
        # answer, and that is exactly what the old vertical lead did at speed.
        cap_x = max(0.0, SCREEN_WIDTH * 0.5 - CAM_SAFE_MARGIN_X)
        cap_y = max(0.0, SCREEN_HEIGHT * 0.5 - CAM_SAFE_MARGIN_Y)
        self.lead_x = max(-cap_x, min(cap_x, self.lead_x))
        self.lead_y = max(-cap_y, min(cap_y, self.lead_y))
        self.x = int(rect.centerx + self.lead_x) - SCREEN_WIDTH // 2
        self.y = int(rect.centery + self.lead_y) - SCREEN_HEIGHT // 2
        self.x = max(0, min(MAP_WIDTH - SCREEN_WIDTH, self.x))
        self.y = max(0, min(MAP_HEIGHT - SCREEN_HEIGHT, self.y))

    def apply(self, rect):
        # round(), not int(). Truncation biases every shake offset toward zero,
        # which is why a maxed-out screen shake read as a 1-2px hum.
        return rect.move(-self.x + round(self.shake_ox), -self.y + round(self.shake_oy))

    def apply_pos(self, pos):
        return (pos[0] - self.x + round(self.shake_ox),
                pos[1] - self.y + round(self.shake_oy))

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
        self.variant = variant or random.choice(CIVILIAN_WEIGHTED)
        self.color = (cars_TRANS_AM_BODY if self.variant == 'trans_am'
                      else color or random.choice(CAR_COLORS))
        tag_hash = (int(x) * 31 + int(y) * 17
                    + sum((index + 1) * ord(ch) for index, ch in enumerate(self.variant)))
        self.temp_tag = self.variant in CIVILIAN_VARIANTS and tag_hash % 100 < 8
        self.police_agency = 'city'
        tune = VEHICLE_TUNING.get(self.variant, {})
        self.width = tune.get('w', VEHICLE_DEFAULT_W)
        self.height = tune.get('h', VEHICLE_DEFAULT_H)
        self.rect = pygame.Rect(0, 0, self.width, self.height)
        self.rect.center = (x, y)
        self.angle = random.uniform(0, math.tau)
        self.velocity = 0.0
        self.steer_angle = 0.0
        # Sub-pixel travel carried between steps; see take_subpixel().
        self.sub_x = 0.0
        self.sub_y = 0.0
        # Every vehicle used to top out at exactly 9.5 under the player -
        # the bus, the refuse truck, the Vespa and the sedan were the same
        # car, and only the time taken to reach it differed. speed_factor was
        # applied by the AI paths and never to you, so which car you stole
        # made no difference at all. It does now.
        #
        # It is PLAYER_CAR_MAX_SPEED, not a second literal: toggle_enter_exit
        # sets that on the way in and apply_grub_to_car re-reads base_max_speed
        # every step, so a different number here silently won the argument and
        # the documented player top speed was never the one in effect.
        self.max_speed = PLAYER_CAR_MAX_SPEED * tune.get('speed_factor', 1.0)
        # The ceiling this car came with. Power-ups and the police AI both
        # write max_speed, so anything that raises it needs a baseline it can
        # restore rather than compounding on itself every step.
        self.base_max_speed = self.max_speed
        self.acceleration = tune.get('acceleration', 0.28)
        self.brake_force = 0.5
        self.drag = 0.965
        self.max_steer = tune.get('max_steer', 0.045)
        # Big rigs top out slower and turn wider; the scooter is nippy. Applied
        # against traffic pace in traffic_drive() / wander_ai().
        self.speed_factor = tune.get('speed_factor', 1.0)
        self.input_throttle = 0.0
        self.input_steer = 0.0
        self.input_handbrake = False
        # Lateral velocity, in the car's own frame. The tyres scrub it away
        # every step; how fast they scrub it is the whole handling model.
        self.vlat = 0.0
        self.slip = 0.0          # |vlat| last step, for screech and skid marks
        self.driver = None  # 'player', 'police', or None (parked/wandering)
        self.parked = False  # parked cars sit at the kerb until someone gets in
        self.wander_dir = random.choice([0, 1, 2, 3])
        # Pursuit bookkeeping, used only by chase_ai().
        self.pinned = 0          # consecutive steps making no headway
        self.reverse_timer = 0   # steps left of a back-out manoeuvre
        self.reverse_side = 1
        self.escape_timer = 0    # finish the turn before re-aiming at the target
        # --- police senses (see update_police) --------------------------
        self.alert = 'chase'     # 'chase' (I see you) | 'search' (I did)
        self.last_seen = None    # world point where the player was last seen
        self.search_timer = 0    # steps left before this cop gives up
        self.lost_timer = 0      # consecutive steps with no line of sight
        self.sight_range = COP_SIGHT
        self.stall = 0           # steps stopped in traffic; feeds the jam breaker
        # Damage model. Enough hits and the car catches fire (burn > 0, a fuse
        # counting down) then explodes. Trucks soak more, the scooter is paper.
        self.max_hp = {'bus': 200.0, 'garbage_truck': 185.0,
                       'street_sweeper': 165.0, 'forestry_truck': 155.0,
                       'box_truck': 145.0,
                       'mudfoot': 190.0, 'grocery_cart': 125.0,
                       'vespa': 32.0}.get(self.variant, 100.0)
        self.hp = self.max_hp
        self.burn = 0            # >0 = on fire, steps until it goes up
        self.crash_cd = 0        # steps until this car can take contact damage again
        # Roadblock spikes do not explode a car. They temporarily halve its
        # pace and steering authority, with a separate cooldown so resting on
        # the strip cannot repeatedly apply the impact beat.
        self.puncture_steps = 0
        self.spike_cd = 0

    def damage(self, amount):
        """Take `amount` of impact damage; light the fuse at zero HP."""
        if self.burn > 0 or amount <= 0:
            return
        self.hp -= amount
        if self.hp <= 0.0:
            self.hp = 0.0
            self.burn = int(FPS * 1.4)   # ~1.4s of smoking before the blast

    def crash_damage(self, amount):
        """Impact damage from *sustained contact* - a wall, a car, a cruiser.

        Those three sites fire once per simulation step for as long as the two
        rects overlap, and nothing rate-limited them: leaning on a kerb for a
        second was sixty separate impacts and about 420 points of damage
        against an 80hp car. Every scripted chase in the playtest rig ended
        the same way inside fifteen seconds - WRECK TOTALLED - with the
        nearest cruiser still five hundred pixels back. One scrape is one
        impact now, however long you hold it.
        """
        if self.crash_cd > 0:
            return
        self.crash_cd = CRASH_DAMAGE_COOLDOWN
        self.damage(amount)

    def tick_crash_cooldown(self):
        if self.crash_cd > 0:
            self.crash_cd -= 1
        if self.puncture_steps > 0:
            self.puncture_steps -= 1
        if self.spike_cd > 0:
            self.spike_cd -= 1

    def drive_gear(self):
        """Arcade transmission state used by the HUD, lamps, and engine load."""
        if self.velocity < -0.08 or (self.input_throttle < 0 and self.velocity < 0.3):
            return 'R'
        if self.velocity > 0.08:
            return 'D'
        return 'N'

    def take_subpixel(self, dx, dy):
        """Bank this step's float travel and hand back whole pixels.

        pygame.Rect holds integers, so `rect.move(int(dx), int(dy))` threw
        away the fraction of every single step. That is not a rounding
        nicety, it was the engine's largest single bug:

          * a car travelling 0.9 px/step moved ZERO pixels, forever, which is
            how ambient traffic ended up in permanent knots - the lead car of
            a queue creeping at under a pixel a step could never actually
            leave, so everything behind it stopped too;
          * on a diagonal the loss is per axis, so heading 45 degrees cost 12%
            of your speed against heading due east - the car was measurably
            faster along the compass points than between them;
          * 6.10 and 6.40 px/step both truncated to 6, which is why a cop
            0.3 px/step slower than you never fell behind.

        Carrying the remainder makes travel exact over time in every
        direction, for every vehicle.
        """
        self.sub_x += dx
        self.sub_y += dy
        mx = int(self.sub_x)          # trunc toward zero; the sign is kept
        my = int(self.sub_y)
        self.sub_x -= mx
        self.sub_y -= my
        return mx, my

    def move_forward_check(self, dx, dy):
        temp = self.rect.move(int(dx), int(dy))
        bike_gate = (self.variant != 'vespa'
                     and rect_hits_tag(temp, 'chain_of_rocks')
                     and not rect_hits_tag(self.rect, 'chain_of_rocks'))
        if is_blocked(temp) or bike_gate or not (0 <= temp.left and temp.right <= MAP_WIDTH
                                     and 0 <= temp.top and temp.bottom <= MAP_HEIGHT):
            return False
        self.rect.topleft = temp.topleft
        return True

    def physics_step(self):
        # Two handling models live here. Anything with a driver - you or a
        # cruiser - gets the bicycle model below, where the turning radius
        # grows with speed and the tyres have a finite grip budget. Ambient
        # traffic (driver is None) keeps the original speed-proportional turn,
        # because traffic_drive()'s whole lane-following geometry is tuned
        # against "radius == max_speed / steer_angle" and rewriting the
        # physics under it would put every AI car in the kerb.
        human = self.driver is not None

        if self.input_throttle > 0:
            if human:
                # Power fades toward the ceiling: the last of the top end has
                # to be worked for instead of arriving in half a second.
                frac = min(1.0, abs(self.velocity) / max(1.0, self.max_speed))
                response = PLAYER_THROTTLE_RESPONSE * (1.0 - PLAYER_POWER_FADE * frac)
            else:
                response = 1.0
            self.velocity += self.acceleration * self.input_throttle * response
        elif self.input_throttle < 0:
            if human:
                brake = PLAYER_BRAKE if self.velocity > 0 else PLAYER_REVERSE_ACCEL
            else:
                brake = self.brake_force
            self.velocity += brake * self.input_throttle
        reverse_limit = self.max_speed * PLAYER_REVERSE_RATIO
        self.velocity = max(-reverse_limit, min(self.max_speed, self.velocity))

        if self.input_throttle == 0:
            self.velocity *= PLAYER_COAST_DRAG if human else self.drag
            if abs(self.velocity) < 0.02:
                self.velocity = 0.0

        hb = bool(self.input_handbrake) and self.driver == 'player'
        if human:
            # --- steering: speed-sensitive lock, rate-limited -------------
            # Lock fades as speed rises, so the wheel you can actually use at
            # 6 px/step is a quarter of the wheel you have when parking. That
            # single term is what turns a twitchy hovercraft into a car.
            speed_frac = min(1.0, abs(self.velocity) / max(1.0, self.max_speed))
            lock = self.max_steer * (1.0 - PLAYER_LOCK_FADE * speed_frac)
            if self.puncture_steps > 0:
                lock *= SPIKE_STEER_SCALE
            if hb:
                lock *= HANDBRAKE_STEER
            want = self.input_steer * lock
            rate = PLAYER_STEER_RATE if self.input_steer else PLAYER_STEER_RETURN
            self.steer_angle += (want - self.steer_angle) * rate
            self.steer_angle = max(-lock, min(lock, self.steer_angle))
            if abs(self.velocity) > 0.12:
                # Bicycle model. Yaw is proportional to how fast the car is
                # actually travelling, so a stationary car cannot spin on the
                # spot and a fast one sweeps wide. velocity is signed, which
                # is what makes reversing swing the nose the other way - the
                # old model had to special-case that and got it backwards.
                yaw = self.velocity * self.steer_angle * PLAYER_YAW_GAIN
                # ... but only up to what the tyres will hold. Over-ask and
                # the nose washes wide: understeer, not a hidden speed cap.
                grip = PLAYER_GRIP_HANDBRAKE if hb else PLAYER_GRIP
                demand = abs(self.velocity * yaw)
                if demand > grip:
                    yaw *= grip / demand
                self.angle += yaw
        else:
            if abs(self.velocity) > 0.15:
                reverse = -1 if self.velocity < 0 else 1
                self.steer_angle += self.input_steer * self.max_steer * reverse
                self.steer_angle = max(-self.max_steer * 2.2,
                                       min(self.max_steer * 2.2, self.steer_angle))
                self.angle += self.steer_angle * min(1.0, abs(self.velocity) / self.max_speed)
            if self.input_steer == 0:
                self.steer_angle *= 0.8

        # --- grip ---------------------------------------------------------
        # Rotating the nose does not rotate the car's momentum with it. The
        # difference between the two is the lateral component, and the tyres
        # scrub it away over the next few steps - fast with grip, slowly with
        # the handbrake down, which is what lets the back end come round.
        retain = LAT_RETAIN_HANDBRAKE if hb else LAT_RETAIN
        prev_angle = getattr(self, '_prev_angle', self.angle)
        turned = (self.angle - prev_angle + math.pi) % math.tau - math.pi
        self._prev_angle = self.angle
        # momentum that failed to follow the nose becomes sideways travel
        self.vlat -= self.velocity * math.sin(turned)
        self.vlat *= retain
        if abs(self.vlat) < 0.02:
            self.vlat = 0.0
        self.slip = abs(self.vlat)
        if hb:
            self.velocity *= HANDBRAKE_DRAG

        fwd_x, fwd_y = math.cos(self.angle), math.sin(self.angle)
        dx, dy = self.take_subpixel(fwd_x * self.velocity - fwd_y * self.vlat,
                                    fwd_y * self.velocity + fwd_x * self.vlat)
        if dx == 0 and dy == 0:
            return False               # under a pixel this step; it is banked
        if self.move_forward_check(dx, dy):
            return False
        # Blocked head-on. Try each axis alone so the car slides along the wall
        # instead of dead-stopping on every kerb graze - that stop-and-bounce
        # was most of what made the narrow streets feel undriveable. An axis
        # only counts as a slide if it actually had travel in it: hitting a
        # wall square-on (one axis ~0) is a real thunk, not a free slide.
        slid_x = dx != 0 and self.move_forward_check(dx, 0)
        slid_y = dy != 0 and self.move_forward_check(0, dy)
        if slid_x or slid_y:
            self.velocity *= 0.86      # scrub a little speed on the scrape
            self.vlat *= 0.5
            return False
        self.velocity *= -0.18         # true head-on: soft stop, faint kickback
        self.vlat = 0.0
        self.sub_x = self.sub_y = 0.0  # do not spend banked travel into a wall
        self.unwedge()
        return True  # collided

    def unwedge(self):
        """Last resort when the car has buried itself in geometry.

        A head-on sets velocity *= -0.18, so a car that ends a step actually
        overlapping a solid tile can never drive or reverse out of it - both
        just bounce, forever. Measured: 265 of these in one ten-minute
        session. Nudge toward the nearest free cardinal instead of leaving the
        player pressing reverse at a wall that will not let go.
        """
        if not is_blocked(self.rect):
            return
        for step in (6, 12, 20, 30, 44, 60, 80, 104):
            for ddx, ddy in ((0, -1), (0, 1), (-1, 0), (1, 0),
                             (-1, -1), (1, -1), (-1, 1), (1, 1)):
                probe = self.rect.move(ddx * step, ddy * step)
                if (probe.left >= 0 and probe.top >= 0
                        and probe.right <= MAP_WIDTH and probe.bottom <= MAP_HEIGHT
                        and not is_blocked(probe)):
                    self.rect.topleft = probe.topleft
                    self.velocity = 0.0
                    self.vlat = 0.0
                    return

    def at_intersection(self):
        """True when the car is near the middle of a crossing tile.

        ROAD_LINES owns the grid, so a crossing is where both tile indices are
        members. Turning is only allowed here; the old AI re-rolled its
        heading anywhere on the map, which is what made traffic swerve
        mid-block and grind along kerbs.
        """
        c, r = self.rect.centerx // TILE_SIZE, self.rect.centery // TILE_SIZE
        if c not in ROAD_LINES or r not in ROAD_LINES:
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

    def probe_clear(self, angle, dist):
        """True when the car's own footprint can sit `dist` px along `angle`."""
        probe = self.rect.copy()
        probe.center = (int(self.rect.centerx + math.cos(angle) * dist),
                        int(self.rect.centery + math.sin(angle) * dist))
        if (probe.left < 0 or probe.top < 0
                or probe.right > MAP_WIDTH or probe.bottom > MAP_HEIGHT):
            return False
        return not is_blocked(probe)

    def chase_ai(self, target_pos, brake_at=34):
        """Pursue target_pos using three forward whiskers.

        The previous version aimed the nose straight at the player and held the
        throttle down, so the first building between cop and player ended the
        chase - the cop just ground along the wall until the wanted level
        decayed. Now a blocked centre whisker steers toward whichever side is
        open, throttle eases off so the car can actually rotate, and anything
        pinned for half a second reverses out and tries a different line.
        """
        tx, ty = target_pos
        dx, dy = tx - self.rect.centerx, ty - self.rect.centery
        dist = math.hypot(dx, dy)
        diff = (math.atan2(dy, dx) - self.angle + math.pi) % math.tau - math.pi
        # max_speed is set per star by update_police (COP_SPEED_BY_STAR), so a
        # one-star beat cop is genuinely outrunnable and a five-star unit is
        # not. Fall back to the base figure for a cop driven outside a chase.
        if self.max_speed <= 0:
            self.max_speed = COP_SPEED_BY_STAR[WANTED_MAX]

        # --- back out of a pin -------------------------------------------
        if self.reverse_timer > 0:
            self.reverse_timer -= 1
            self.input_throttle = -1.0
            self.input_steer = float(self.reverse_side)
            self.physics_step()
            if self.reverse_timer == 0:
                self.escape_timer = 42
            return

        # Reversing creates room but does not clear the obstacle by itself.
        # Hold the complementary forward arc long enough to round the corner;
        # immediately aiming at the target drove the cruiser into the same wall.
        if self.escape_timer > 0:
            self.escape_timer -= 1
            self.input_throttle = 1.0
            self.input_steer = float(-self.reverse_side)
            self.physics_step()
            return

        if abs(self.velocity) < 0.4 and dist > 60:
            self.pinned += 1
            if self.pinned > 30:                 # ~0.5s of going nowhere
                self.pinned = 0
                self.reverse_timer = 26
                self.reverse_side = random.choice((-1, 1))
        else:
            self.pinned = 0

        # --- whiskers: straight ahead, then +/- 40 degrees ---------------
        ahead = self.probe_clear(self.angle, 46)
        steer = diff * 2.2
        if not ahead:
            left = self.probe_clear(self.angle - 0.70, 42)
            right = self.probe_clear(self.angle + 0.70, 42)
            if right and not left:
                steer = 1.6
            elif left and not right:
                steer = -1.6
            else:
                steer = 1.6 if diff >= 0 else -1.6

        self.input_steer = max(-1.0, min(1.0, steer))
        if dist <= brake_at:
            # Arrest, not manslaughter: below COP_RAMMING_STAR the cruiser
            # stops short of a player on foot and holds them instead.
            self.input_throttle = -0.4 if abs(self.velocity) > 1.2 else 0.0
        else:
            self.input_throttle = 1.0 if ahead else 0.5
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
        if self.variant == 'police' and self.police_agency == 'county':
            # County cars are white-belted instead of the city's solid blue.
            # This tiny overlay stays readable at every baked heading.
            pygame.draw.rect(screen, (238, 236, 224),
                             (int(screen_pos[0]) - 7, int(screen_pos[1]) - 2, 14, 4))
            pygame.draw.rect(screen, (36, 62, 118),
                             (int(screen_pos[0]) - 2, int(screen_pos[1]) - 2, 4, 4))
        if self.temp_tag:
            # The crooked paper temp tag: tiny, bright, and unmistakably taped
            # to the rear instead of mounted like a plate.
            fx, fy = math.cos(self.angle), math.sin(self.angle)
            tx = int(round(screen_pos[0] - fx * self.width * SPRITE_SCALE_CAR * 0.48))
            ty = int(round(screen_pos[1] - fy * self.width * SPRITE_SCALE_CAR * 0.48))
            pygame.draw.rect(screen, COLOR_OUTLINE, (tx - 2, ty - 2, 6, 5))
            pygame.draw.rect(screen, (244, 240, 218), (tx - 1, ty - 1, 4, 3))
            screen.fill((72, 70, 66), (tx + 1, ty, 1, 1))
        if self.drive_gear() == 'R':
            # Two hard-pixel white lamps make reverse legible at a glance. The
            # rear is opposite the heading; side offsets follow the car's local
            # width so the lights stay attached through all 24 baked headings.
            fx, fy = math.cos(self.angle), math.sin(self.angle)
            sx, sy = -fy, fx
            rear = self.width * SPRITE_SCALE_CAR * 0.43
            spread = self.height * SPRITE_SCALE_CAR * 0.24
            cx = screen_pos[0] - fx * rear
            cy = screen_pos[1] - fy * rear
            for side in (-1, 1):
                lx = int(round(cx + sx * spread * side))
                ly = int(round(cy + sy * spread * side))
                pygame.draw.rect(screen, COLOR_OUTLINE, (lx - 1, ly - 1, 4, 4))
                pygame.draw.rect(screen, (232, 238, 210), (lx, ly, 2, 2))
        if self.puncture_steps > 0:
            # Hard red wheel ticks survive every body colour and heading. The
            # HUD carries the text; this keeps the damage readable in-world.
            fx, fy = math.cos(self.angle), math.sin(self.angle)
            sx, sy = -fy, fx
            for end in (-1, 1):
                for side in (-1, 1):
                    wx = int(round(screen_pos[0] + fx * self.width * 0.34 * end
                                   + sx * self.height * 0.42 * side))
                    wy = int(round(screen_pos[1] + fy * self.width * 0.34 * end
                                   + sy * self.height * 0.42 * side))
                    pygame.draw.rect(screen, (212, 54, 42), (wx - 1, wy - 1, 3, 3))


def metrolink_polyline(offset=0.0):
    """The route in world pixels, as tile-centre points, west to east.

    `offset` shifts the line sideways by that many pixels (positive = south on
    an east-west leg, east on a north-south leg) so the two tracks sit either
    side of the centre line.
    """
    pts = []
    for i, (col, row) in enumerate(METROLINK_ROUTE):
        x = col * TILE_SIZE + TILE_SIZE * 0.5
        y = row * TILE_SIZE + TILE_SIZE * 0.5
        if offset:
            prev = METROLINK_ROUTE[i - 1] if i > 0 else None
            nxt = METROLINK_ROUTE[i + 1] if i + 1 < len(METROLINK_ROUTE) else None
            # Offset perpendicular to every leg that touches this point. On a
            # corner both apply, and (x+off, y+off) is exactly where the two
            # offset lines meet - so the parallel tracks stay parallel round
            # the bend instead of collapsing onto each other.
            if any(p is not None and p[1] == row for p in (prev, nxt)):
                y += offset
            if any(p is not None and p[0] == col for p in (prev, nxt)):
                x += offset
        pts.append((x, y))
    return tuple(pts)


class RailVehicle:
    """A vehicle that runs along a polyline track, nose first.

    It used to be a fixed `y` and a scalar `x`, which is why the MetroLink was
    a single straight row across the whole map. Position is now a distance
    along a path, so the line is free to turn corners - and the Red Line turns
    four of them between Wellston and the Eads Bridge.
    """

    def __init__(self, sprite, path, speed, s=0.0, *, kind='metrolink'):
        self.sprite = sprite
        self.flip = pygame.transform.flip(sprite, True, False)
        self.vert = pygame.transform.rotate(sprite, 90)
        self.vert_flip = pygame.transform.rotate(sprite, -90)
        self.shadow = cars_make_shadow(sprite)
        self.shadow_flip = pygame.transform.flip(self.shadow, True, False)
        self.shadow_vert = pygame.transform.rotate(self.shadow, 90)
        self.shadow_vert_flip = pygame.transform.rotate(self.shadow, -90)
        self.h = sprite.get_height()
        self.w = sprite.get_width()
        self.kind = kind
        self.path = tuple(path)
        self.legs = []
        total = 0.0
        for (x0, y0), (x1, y1) in zip(self.path, self.path[1:]):
            length = math.hypot(x1 - x0, y1 - y0)
            if length <= 0.0:
                continue
            self.legs.append((total, length, x0, y0, (x1 - x0) / length,
                              (y1 - y0) / length))
            total += length
        self.length = total
        self.speed = speed
        self.s = max(0.0, min(total, float(s)))
        self.x, self.y, self.dx, self.dy = 0.0, 0.0, 1.0, 0.0
        self._place()

    def _place(self):
        pos = max(0.0, min(self.length, self.s))
        for index, (start, length, x0, y0, ux, uy) in enumerate(self.legs):
            if pos <= start + length or index == len(self.legs) - 1:
                along = pos - start
                self.x = x0 + ux * along
                self.y = y0 + uy * along
                self.dx, self.dy = ux, uy
                return

    @property
    def horizontal(self):
        return abs(self.dx) >= abs(self.dy)

    @property
    def rect(self):
        w, h = (self.w, self.h) if self.horizontal else (self.h, self.w)
        return pygame.Rect(int(round(self.x - w / 2)),
                           int(round(self.y - h / 2)), w, h)

    @property
    def centerx(self):
        return self.x

    @property
    def centery(self):
        return self.y

    def update(self):
        self.s += self.speed
        if self.s <= 0.0:
            self.s = 0.0
            self.speed = abs(self.speed)
        elif self.s >= self.length:
            self.s = self.length
            self.speed = -abs(self.speed)
        self._place()

    def _frames(self):
        forward = self.speed >= 0
        if self.horizontal:
            east = (self.dx >= 0) == forward
            return (self.sprite if east else self.flip,
                    self.shadow if east else self.shadow_flip)
        south = (self.dy >= 0) == forward
        return (self.vert_flip if south else self.vert,
                self.shadow_vert_flip if south else self.shadow_vert)

    def draw(self, screen, camera):
        image, shadow = self._frames()
        w, h = image.get_size()
        sx = self.x - camera.x - w / 2
        sy = self.y - camera.y - h / 2
        if sx > SCREEN_WIDTH or sx + w < 0 or sy > SCREEN_HEIGHT or sy + h < 0:
            return
        screen.blit(shadow, (int(sx + SHADOW_DX), int(sy + SHADOW_DY)))
        screen.blit(image, (int(sx), int(sy)))


class RailCrossing:
    """One MetroLink grade crossing with an animated paired gate."""

    def __init__(self, col, row=None, axis='h'):
        self.col = int(col)
        self.row = int(METROLINK_ROW if row is None else row)
        self.axis = axis                    # direction the RAIL runs here
        self.x = self.col * TILE_SIZE + TILE_SIZE // 2
        self.y = self.row * TILE_SIZE + TILE_SIZE // 2
        self.arm = 0.0              # 0 upright, 1 blocking the road
        self.state = 'open'
        self.warning = False

    def distance_to_train(self, trains):
        distances = []
        for train in trains:
            if train.kind != 'metrolink':
                continue
            half = train.w * 0.5
            cy = getattr(train, 'centery', self.y)
            gap = math.hypot(train.centerx - self.x, cy - self.y)
            distances.append(max(0.0, gap - half))
        return min(distances) if distances else float('inf')

    def update(self, trains):
        distance = self.distance_to_train(trains)
        was_warning = self.warning
        self.warning = distance <= RAIL_GATE_WARNING_DISTANCE
        target = 1.0 if self.warning else 0.0
        if self.arm < target:
            self.arm = min(target, self.arm + RAIL_GATE_ARM_RATE)
        elif self.arm > target:
            self.arm = max(target, self.arm - RAIL_GATE_ARM_RATE)
        if self.arm >= 0.98:
            self.state = 'closed'
        elif self.arm <= 0.02:
            self.state = 'open'
        elif target > self.arm:
            self.state = 'closing'
        else:
            self.state = 'opening'
        return self.warning and not was_warning

    def holds(self, car):
        """True for a road vehicle approaching, never one clearing the rail.

        The rail runs along `self.axis`, so the road that crosses it runs
        along the other one. Both orientations exist now that the alignment
        turns corners.
        """
        if self.arm < 0.18:
            return False
        if self.axis == 'h':                 # rail east-west, road north-south
            along, across = car.rect.centerx - self.x, self.y - car.rect.centery
        else:                                # rail north-south, road east-west
            along, across = car.rect.centery - self.y, self.x - car.rect.centerx
        if abs(along) > RAIL_GATE_LANE_HALF_WIDTH:
            return False
        travel = pygame.Vector2(math.cos(car.angle), math.sin(car.angle))
        if car.velocity < -0.1:
            travel *= -1
        toward = travel.y if self.axis == 'h' else travel.x
        if abs(toward) < 0.55:
            return False
        approach = across * (1 if toward > 0 else -1)
        return 12.0 <= approach <= RAIL_GATE_STOP_DISTANCE


def build_rail_crossings():
    """Every place a street crosses the MetroLink at grade, in route order."""
    out = []
    for (col, row, axis) in METROLINK_TILES:
        if not (0 <= col < MAP_TILES_W and 0 <= row < MAP_TILES_H):
            continue
        tile = GAME_MAP[row][col]
        if tile.get('rail') == 'metrolink' and tile.get('rail_crossing'):
            out.append(RailCrossing(col, row, axis))
    return out


def build_rail_vehicles():
    """Two MetroLink trains on the real Red Line alignment, a Loop trolley
    that goes about two miles because that is how far it goes, and the
    Clydesdales walking a Soulard street at the pace of eight horses, which
    is the pace of eight horses."""
    ml = cars_rail_sprite('metrolink')
    tr = cars_rail_sprite('trolley')
    cl = cars_clydesdale_sprite()
    west = metrolink_polyline(METROLINK_TRACK_OFFSETS[0])
    east = metrolink_polyline(METROLINK_TRACK_OFFSETS[1])
    row_loop = TROLLEY_ROW * TILE_SIZE + TILE_SIZE // 2
    trolley_path = ((TROLLEY_COL_MIN * TILE_SIZE + TILE_SIZE * 0.5, row_loop),
                    (TROLLEY_COL_MAX * TILE_SIZE + TILE_SIZE * 0.5, row_loop))
    # The hitch walks a short Soulard beat and turns round, because that is
    # what it does. It used to be handed the full map width on row 57, which
    # ran the eight-horse hitch straight through the Farmers Market sheds and
    # then out across the Mississippi - 11 solid or water tiles in all.
    def _t(i):
        return i * TILE_SIZE + TILE_SIZE // 2
    horses = ((_t(CLYDESDALE_WEST), _t(CLYDESDALE_ROW)),
              (_t(CLYDESDALE_COL), _t(CLYDESDALE_ROW)),
              (_t(CLYDESDALE_COL), _t(CLYDESDALE_SOUTH)))
    trains = [
        RailVehicle(ml, west, 3.1, s=600.0, kind='metrolink'),
        RailVehicle(ml, east, -3.1, kind='metrolink'),
        RailVehicle(tr, trolley_path, TROLLEY_SPEED, kind='trolley'),
        RailVehicle(cl, horses, 0.55, s=TILE_SIZE * 6.0, kind='clydesdale'),
    ]
    trains[1].s = trains[1].length - 1300.0
    trains[1]._place()
    return trains


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
        self.dir = [random.choice([-1, 0, 1]), random.choice([-1, 0, 1])]
        self.set_kind(kind)
        self.retarget_timer = 0
        self.bump_cooldown = 0
        self.facing = 2
        self.anim = 0.0
        # Reaction state machine: calm -> alarmed/flee (scatter from a threat)
        # / gawk (stop and stare at a fresh body) / down (bowled over, sprawled
        # a beat). This is the loudest 'the city is alive' signal there is.
        self.mood = 'calm'
        self.mood_timer = 0
        self.threat = None                 # unit (dx, dy) pointing away from danger
        self.knock = pygame.Vector2()      # decaying shove from being hit
        self.down_timer = 0
        self.event_actor = False
        self.event_kid = False
        self.joke_told = False

    def set_kind(self, kind=None):
        """Retype a streamed pedestrian without leaving dog or gait ghosts."""
        self.kind = kind or peds_random_archetype()
        self.speed = 0.8 * peds_gait(self.kind)
        self.follower = Follower('dog') if peds_has_dog(self.kind) else None
        if self.follower is not None:
            self.follower.x = float(self.rect.centerx)
            self.follower.y = float(self.rect.centery)
            self.follower.placed = True

    def _sense(self, game):
        """Look for a reason to run. First hit wins; keeps it cheap."""
        ax, ay = game.active_rect().center
        cx, cy = self.rect.centerx, self.rect.centery
        if game.driving is not None and abs(game.driving.velocity) > 2.4:
            dx, dy = cx - ax, cy - ay
            if dx * dx + dy * dy < 96 * 96:
                self._flee((dx, dy), random.randint(70, 110))
                return
        if game.wanted_level >= 1:
            dx, dy = cx - ax, cy - ay
            if dx * dx + dy * dy < 150 * 150:
                self._flee((dx, dy), random.randint(50, 90))
                return
        for cop in game.police:
            dx, dy = cx - cop.rect.centerx, cy - cop.rect.centery
            if dx * dx + dy * dy < 72 * 72:
                self._flee((dx, dy), random.randint(45, 75))
                return

    def _flee(self, away, ticks):
        n = math.hypot(away[0], away[1]) or 1.0
        self.threat = (away[0] / n, away[1] / n)
        self.mood = 'flee'
        self.mood_timer = ticks

    def gawk_at(self, spot, ticks):
        dx, dy = spot[0] - self.rect.centerx, spot[1] - self.rect.centery
        n = math.hypot(dx, dy) or 1.0
        self.threat = (dx / n, dy / n)
        self.mood = 'gawk'
        self.mood_timer = ticks

    def _try_move(self, dx, dy):
        temp = self.rect.move(int(dx), int(dy))
        if pedestrian_ground_is_clear(temp):
            self.rect.topleft = temp.topleft
            return True
        return False

    def update(self, game=None):
        # 1. knockback from being hit, always applied first
        if self.knock.length_squared() > 0.06:
            if not self._try_move(self.knock.x, self.knock.y):
                self.knock *= 0.4
            self.knock *= 0.80
            self.anim += 0.5
        else:
            self.knock.update(0, 0)

        # 2. sprawled on the ground - just tick the timer
        if self.down_timer > 0:
            self.down_timer -= 1
            if self.bump_cooldown > 0:
                self.bump_cooldown -= 1
            return

        if self.bump_cooldown > 0:
            self.bump_cooldown -= 1

        if game is not None and self.mood not in ('flee', 'gawk'):
            self._sense(game)

        if self.mood in ('flee', 'gawk'):
            self.mood_timer -= 1
            if self.mood_timer <= 0:
                self.mood = 'calm'
                self.threat = None

        if self.mood == 'gawk':
            if self.threat:
                self.facing = peds_dir_index(self.threat[0], self.threat[1])
            return

        if self.mood == 'flee' and self.threat:
            spd = self.speed * 2.1
            fx, fy = self.threat[0] * spd, self.threat[1] * spd
            self.facing = peds_dir_index(fx, fy)
            self.anim += 0.34
            if not self._try_move(fx, fy):
                # sidestep along the threat instead of stalling into the wall
                if not self._try_move(-fy, fx):
                    self._try_move(fy, -fx)
            self._update_dog()
            return

        # 3. calm wander (original behaviour)
        self.retarget_timer -= 1
        if self.retarget_timer <= 0:
            self.dir = [random.choice([-1, 0, 1]), random.choice([-1, 0, 1])]
            self.retarget_timer = random.randint(60, 180)
        dx, dy = self.dir[0] * self.speed, self.dir[1] * self.speed
        if dx or dy:
            self.facing = peds_dir_index(dx, dy)
            self.anim += 0.16          # ~8fps walk cycle at 60fps
        if not self._try_move(dx, dy):
            self.dir = [random.choice([-1, 0, 1]), random.choice([-1, 0, 1])]
        self._update_dog()

    def _update_dog(self):
        if not self.follower:
            return
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
        moving = self.dir[0] or self.dir[1] or self.mood == 'flee'
        sprite, shadow = ped_sprite(self.kind, self.facing, moving, self.anim)
        if self.down_timer > 0:                 # sprawled: lay the sprite over
            sprite = pygame.transform.rotate(sprite, 78)
            shadow = pygame.transform.rotate(shadow, 78)
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
    def __init__(self, start_fullscreen=True):
        # pre_init has to run before pygame.init() opens the audio device.
        # 22050 is plenty for this material and halves both the bake time and
        # the memory; a 512-sample buffer is 23ms of latency, which keeps a
        # punch feeling connected to the button - 1024 is audibly late.
        try:
            pygame.mixer.pre_init(snd_SR, -16, 2, 512)
        except pygame.error:
            pass
        pygame.init()
        pygame.font.init()
        # Headless (CI / smoke tests) runs on the dummy SDL driver: keep the
        # plain fixed-size surface there. A real window opens borderless
        # fullscreen by default, scaled to the display; SCALED means SDL does
        # the aspect-correct letterboxing and toggle_fullscreen() is reliable,
        # RESIZABLE lets the window be dragged to any size. F11 toggles it.
        self._headless = os.environ.get("SDL_VIDEODRIVER") == "dummy"
        self.fullscreen = False
        if self._headless:
            self.window = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        else:
            flags = pygame.RESIZABLE | pygame.SCALED
            if start_fullscreen:
                flags |= pygame.FULLSCREEN
            try:
                self.window = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), flags)
                self.fullscreen = bool(start_fullscreen)
            except pygame.error:
                # Some drivers refuse SCALED/FULLSCREEN at create time; a plain
                # resizable window still plays fine and F11 can try again later.
                self.window = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT),
                                                      pygame.RESIZABLE)
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
        bake_neighborhood_building_sprites()
        hud_bake()
        # Audio is baked the same way as the art: waveforms into buffers, once,
        # at boot. Silent and harmless when there is no mixer (CI, dummy driver).
        if not self._headless:
            snd_bake()
        self.postfx = fx_PostFX(SCREEN_WIDTH, SCREEN_HEIGHT, SCALE_FACTOR)
        self.frame = 0
        self.radar_base = None

        self.camera = Camera()
        px, py = random_open_spawn()
        self.player_rect = pygame.Rect(0, 0, PLAYER_SIZE, PLAYER_SIZE)
        self.player_rect.center = (px, py)
        # Sub-pixel position. The rect is integer-only, so walking used to run
        # through int() every step: a 0.707 diagonal at speed 4.2 truncated
        # 2.97 to 2, and any fraction was thrown away entirely. Keeping the
        # real position here and rounding into the rect fixes both.
        self.player_fx = float(self.player_rect.centerx)
        self.player_fy = float(self.player_rect.centery)
        self.player_dir = [0, 0]
        self.player_motion = pygame.Vector2()
        self.player_stamina = PLAYER_STAMINA_MAX
        self.sprinting = False
        self.sprint_active = False
        self.sprint_ready = True
        self.player_facing = 2
        self.player_aim = 0.0        # radians; where a punch / shot goes
        self.player_anim = 0.0
        self.driving = None  # Car instance the player is currently driving, or None

        # Most traffic is parked at the kerb, GTA1 style, so there is always a
        # car you can walk up to and steal. The rest drive as ambient traffic.
        parking_set_blocked_fn(is_blocked)
        # Spawning now asks the traffic module whether a tile belongs to the
        # cardinal grid, so install its read-only map hooks before creating the
        # first moving car. The crossing callback is only used during updates,
        # after self.rail_crossings exists.
        traffic_set_hooks(is_blocked, GAME_MAP, TILE_SIZE,
                          MAP_TILES_W, MAP_TILES_H, ROAD_LINES,
                          self.rail_gate_holds)
        self.cars = []
        ordinary_parked = PARKED_CAR_COUNT - len(SHOWCASE_VEHICLES) - 1
        bays = parking_parking_spots(max_count=ordinary_parked,
                                     near=(px, py), radius=1400)
        for (sx, sy, sangle, _side) in bays[:ordinary_parked]:
            # kerb spots are sized for ordinary cars, so keep the big rigs out
            car = Car(sx, sy, variant=random.choice(PARKED_VARIANTS_WEIGHTED))
            car.angle = sangle
            car.parked = True
            car.velocity = 0.0
            self.cars.append(car)
        # Two destination vehicles replace ordinary parked cars in the total
        # population budget. They stay at their venues until the player takes
        # them instead of being streamed into a random kerb bay.
        by_name = {entry[5]: entry for entry in LANDMARKS}
        for variant, venue in SHOWCASE_VEHICLES:
            tune = VEHICLE_TUNING[variant]
            target = landmark_dropoff_point(by_name[venue])
            spot = free_point_near(target[0], target[1], tune['w'], tune['h'],
                                   max_rings=8)
            if spot is None:
                continue
            car = Car(spot[0], spot[1], variant=variant)
            car.angle = 0.0
            car.parked = True
            car.velocity = 0.0
            self.cars.append(car)
        self.chain_bike = None
        self.chain_bike_home = None
        airport_spot = free_point_near(
            *landmark_dropoff_point(by_name["Lambert Airport"]),
            VEHICLE_TUNING['vespa']['w'], VEHICLE_TUNING['vespa']['h'],
            max_rings=8)
        if airport_spot is not None:
            self.chain_bike_home = (int(airport_spot[0]), int(airport_spot[1]))
            self.chain_bike = Car(*airport_spot, variant='vespa')
            self.chain_bike.angle = 0.0
            self.chain_bike.parked = True
            self.chain_bike.velocity = 0.0
            self.cars.append(self.chain_bike)
        for traffic_index in range(MOVING_CAR_COUNT):
            # seeded around the player, not smeared over the whole map, so the
            # first street you see already has traffic on it - and never on top
            # of a car that is already there. Diagonal arterials are player
            # roads but not valid inputs to the cardinal traffic driver.
            guaranteed = (GUARANTEED_AMBIENT_VARIANTS[traffic_index]
                          if traffic_index < len(GUARANTEED_AMBIENT_VARIANTS)
                          else None)
            variant = guaranteed or random.choice(CIVILIAN_WEIGHTED)
            # Put the guaranteed civic vehicles in the near ring on boot. A
            # guarantee somewhere in a 100x100 map is still invisible in play.
            spawn_outer = 360 if guaranteed else POP_KEEP_RADIUS
            spot = (self.route_70_spawn(py)
                    if variant == 'metrobus_70' else
                    self.free_spawn_spot(
                        tries=24, grid_traffic=True, ax=px, ay=py, road_only=True,
                        rmin=140, rmax=spawn_outer))
            if spot is None:
                spot = self.fallback_traffic_spawn()
            cx, cy = spot if spot else random_open_spawn(road_only=True)
            self.cars.append(Car(cx, cy, variant=variant))

        self.rail = build_rail_vehicles()
        self.rail_crossings = build_rail_crossings()

        for car in self.cars:
            traffic_init_car(car)
            if not car.parked:
                traffic_snap_to_lane(car)
        # Snapping to the lane happens after every car exists, so it can shove
        # a moving car onto a kerbside one that was placed before it. Settle
        # the whole population before the first frame is ever drawn.
        for _ in range(12):
            self.unstack_traffic()

        self.pedestrians = []
        for _ in range(PEDESTRIAN_COUNT):
            candidate = ring_spawn_near(px, py, rmin=50, rmax=POP_KEEP_RADIUS)
            if candidate is None:
                candidate = random_pedestrian_point()
            spot = pedestrian_point_near(*candidate, max_rings=8)
            if spot is None:                       # map-wide fallback, practically unreachable
                spot = random_pedestrian_point()
            px2, py2 = spot
            self.pedestrians.append(Pedestrian(px2, py2, self._ped_kind_for(px2, py2)))
        self._kerb_queue = []      # cached kerb spots for recycling parked cars

        # POLICE_STATION_TILE names a building tile, so its raw centre is solid
        # ground. Resolve it once to the nearest standable spot: anything that
        # spawns there (a cop, or you after a bust) would otherwise be sealed
        # inside the wall with move_forward_check failing forever.
        station_x = POLICE_STATION_TILE[0] * TILE_SIZE + TILE_SIZE // 2
        station_y = POLICE_STATION_TILE[1] * TILE_SIZE + TILE_SIZE // 2
        self.police_station = free_point_near(
            station_x, station_y, VEHICLE_DEFAULT_W, VEHICLE_DEFAULT_H,
            max_rings=10) or (station_x, station_y)
        self.police = []
        self.roadblocks = []       # deterministic high-heat containment points
        self.roadblock_serial = 0
        self.roadblock_deploy_after = 0

        # --- progression -------------------------------------------------
        # score and cash used to be incremented in lockstep everywhere, which
        # made one of them redundant. They now mean different things: cash is
        # earned by finishing delivery runs, score is the chaos counter.
        self.wanted_level = 0
        self.score = 0
        self.best_score = 0
        self.cash = 200          # on you, and losable; see the bank at the Arch
        self.banked = 0          # safe. Only banked money counts for the ladder.
        self.dropped = []        # rolls of cash left where somebody died
        self.discovered = set()
        self.legend_rumors = set()
        self.legend_discovered = set()
        self.legend_garage = set()
        self.legend_mastery = set()
        self.legend_hint_after = LOCAL_LEGEND_HINT_FIRST
        self.local_challenge = None
        self.hill_hint_shown = False
        self.toasts = []
        self.speech_bubbles = []  # timed world-space dialogue anchored to speakers
        self.busted_flash = 0
        self.wasted_flash = 0
        self.running = True

        # --- death ritual --------------------------------------------------
        # Death is a state, not a decorative flash. See enter_death().
        self.death_timer = 0
        self.death_kind = None       # 'wasted' | 'busted'
        self.death_note = ""         # the line under the big word
        self.death_stats = None      # snapshot of the run you just ended

        # --- police senses / hiding ---------------------------------------
        self.spotted = False         # a cop has line of sight on you *now*
        self.was_spotted = False     # for the edge-triggered "Spotted!" toast
        self.searching = False       # cops are hunting your last known spot
        self.hidden = False          # still, in cover, unseen: heat drains fast
        self.hide_timer = 0
        self.cop_dispatch = 0        # steps until the next cruiser is sent
        self.pursuit_agency = police_jurisdiction_at(px // TILE_SIZE, py // TILE_SIZE)
        self.pending_pursuit_agency = self.pursuit_agency
        self.jurisdiction_timer = 0
        self.hurt_cd = 0             # i-frames after a car hits you on foot
        self.foot_police = []        # beat cops; the unit that can arrest you
        self.foot_cop_respawn = 0    # a dropped officer stays gone for a beat
        self.crime_pos = None        # where the offence that raised this star was
        self.crime_frame = -10 ** 9
        self.hs_cooldown = 0         # steps before anybody asks you again
        self.chatter_cooldown = FPS * 2
        # Where you are, in words. Nothing in the game ever told you which
        # neighbourhood you were standing in or which street you were on, and
        # a player who cannot name a district cannot notice it changed.
        self.hood_now = None
        self.hood_banner = 0         # steps left on the big crossing title
        self.street_now = None
        # Shuffled-bag dealer for every spoken pool, so the city stops
        # saying the same fifteen things.
        self.chatter = ChatterBag()
        self.body_shops = []
        for (bcol, brow) in BODY_SHOP_TILES:
            spot = free_point_near(bcol * TILE_SIZE + TILE_SIZE // 2,
                                   brow * TILE_SIZE + TILE_SIZE // 2,
                                   VEHICLE_DEFAULT_W, VEHICLE_DEFAULT_H,
                                   max_rings=8)
            if spot is not None:
                self.body_shops.append(spot)
        self.shop_cooldown = 0
        self.hs_asked = 0            # how many times you have answered it
        self.peak_star = 0           # highest star reached this life
        self.chase_steps = 0         # steps spent at 1+ stars this life
        self.longest_chase = 0

        # --- chaos multiplier + combo ----------------------------------
        self.multiplier = 1
        self.mult_prog = 0.0
        self.mult_decay = 0
        self.combo = 0            # consecutive ped hits in a short window
        self.combo_timer = 0

        # --- kill frenzy ---------------------------------------------------
        self.frenzy = None           # active Frenzy, or None
        self.frenzy_icon = None      # (x, y, kind) pickup on the map, or None
        self.frenzy_cooldown = FPS * 5

        # --- juice: shake / hitstop / particles / pops / callouts --------
        self.shake = 0.0             # camera shake amplitude, decays to 0
        self.freeze = 0              # hitstop: whole sim steps to skip
        self.hit_flash = 0           # white screen flash, frames
        self.fx = []                 # particle pool (capped)
        self.pops = []               # world-space rising numbers (capped)
        self.callouts = []           # big centre-screen shouts (capped)
        self.decals = []             # ground stains: blood, scorch (capped)
        self.player_hp = PLAYER_MAX_HP

        # --- combat -------------------------------------------------------
        self.weapon = 'fists'
        self.ammo = 0
        self.weapon_ammo = {kind: 0 for kind in WEAPON_ORDER}
        self.owned_weapons = {'fists'}
        self.attack_cd = 0           # steps until the next punch / shot
        self.attack_held = False     # automatic fire for the SMG
        self.punch_timer = 0         # >0 while the swing is on screen
        self.bullets = []
        self.throwable_system = throwable_logic.ThrowableSystem()
        # A deterministic mix keeps the first pickup a pistol for a gentle
        # introduction, then seeds every other weapon around the city.
        self.weapon_pickups = []
        for i in range(WEAPON_PICKUP_COUNT):
            wx, wy = random_open_spawn()
            kind = WEAPON_PICKUP_KINDS[i % len(WEAPON_PICKUP_KINDS)]
            self.weapon_pickups.append({'x': wx, 'y': wy, 'taken': 0,
                                        'kind': kind})

        # --- grub: the St. Louis power-up layer ---------------------------
        # key -> sim step the effect expires on. Absent means not running.
        self.grub_until = {}
        # Potholes, placed deterministically on road tiles and weighted
        # south and north, where they really are worse.
        self.potholes = []
        prng = random.Random(0xC171E5)
        tries = 0
        while len(self.potholes) < POTHOLE_COUNT and tries < 4000:
            tries += 1
            col = prng.randrange(4, MAP_TILES_W - 4)
            row = prng.randrange(4, MAP_TILES_H - 4)
            if tile_type_at(col, row) != TILE_ROAD:
                continue
            if hood_at(col, row) not in ('south', 'north', 'cherokee', 'hill'):
                if prng.random() < 0.6:
                    continue
            self.potholes.append({
                'x': col * TILE_SIZE + TILE_SIZE // 2 + prng.randrange(-14, 15),
                'y': row * TILE_SIZE + TILE_SIZE // 2 + prng.randrange(-14, 15),
                'seed': prng.randrange(1 << 30),
                # exactly one of them has the cone, and it is always this one
                'cone': len(self.potholes) == 7,
                'hit': -10 ** 9})

        self.grub_pickups = []
        for _ in range(GRUB_PICKUP_COUNT):
            gx, gy = random_open_spawn()
            self.grub_pickups.append({'x': gx, 'y': gy, 'taken': 0,
                                      'kind': random.choice(list(GRUB_KINDS))})

        # --- jobs ---------------------------------------------------------
        self.recent_job_kinds = []
        self.job_types_done = set()
        self.job = self.deal_job()
        self.jobs_done = 0
        self.jobs_failed = 0
        self.streak = 0
        self.best_streak = 0
        self.job_cooldown = 0
        self.chain_until = 0         # frame the hot-streak bonus expires on
        self.side_mission = None
        self.side_mission_serial = 0
        self.side_mission_cooldown = 0
        self.side_target_car = None
        self.side_target_pos = None
        self.smash_targets = []
        self.side_missions_done = 0
        self.side_missions_failed = 0
        # The promise at $50,000 is a real finale, not a toast. Unlock and
        # completion persist; an attempt itself restarts clean after death/load.
        self.arch_job_unlocked = False
        self.arch_job_completed = False
        self.arch_job_phase = ARCH_LOCKED
        self.arch_job_timer = 0
        self.arch_job_offer_after = 0
        self.arch_victory_timer = 0

        # --- who are you? -------------------------------------------------
        # This is intentionally lightweight mechanically and extremely heavy
        # culturally. Your outfit changes the baked player sprite; your high
        # school follows you into the question every St. Louisan eventually asks.
        self.character_look = 0
        self.character_school = "NOT FROM AROUND HERE"
        self.title_index = 0
        self.setup_row = 0
        self.school_open = False
        self.school_query = ""
        self.school_cursor = 0
        self._save_probe_signature = None
        self._save_probe_valid = False

        # --- heat ---------------------------------------------------------
        self.infraction_at = {}   # offence key -> sim step it may re-arm at
        self.heat_timer = 0       # steps since the last crime / last cop sighting
        self.wanted_decay_timer = 0
        self.bust_meter = 0       # sustained cop contact; you get a chance to run

        # --- loop / debug --------------------------------------------------
        # Tests and scripted captures enter play directly. A human gets a real
        # front door to the game instead of materializing on Memorial Drive.
        self.state = STATE_PLAYING if self._headless else STATE_TITLE
        self.accumulator = 0.0
        self.show_debug = False
        self.show_map = False        # full-city map overlay (M / TAB)
        self.map_overview = None     # lazily baked static map surface
        self.fps_now = 0.0
        self.sim_steps = 1
        self.hud_left_y = 8
        self.music_available = False
        self.music_started = False
        self.music_paused = False
        self.music_muted = False
        self.radio_index = 0
        self.radio_break_after = RADIO_BREAK_FIRST
        self.radio_break_serial = 0
        self.city_event_seed = random.randrange(1 << 30)
        self.city_event_key = tuple(CITY_EVENT_DEFS)[self.city_event_seed % len(CITY_EVENT_DEFS)]
        self.city_event_announced = False
        self.halloween_kids = []
        self.halloween_jokes_told = 0
        if not self._headless:
            self.load_soundtrack()

        # --- gamepad -------------------------------------------------------
        self.pad = None
        self._pad_trig_rest = {}   # axis -> lowest value seen, to spot the
        try:                       # -1..+1 trigger convention vs 0..1
            pygame.joystick.init()
            self.open_gamepad()
        except pygame.error:
            self.pad = None

    # ---------------- persistence ----------------
    @staticmethod
    def _save_read_path(path=None):
        if path is not None:
            return os.fspath(path)
        return SAVE_PATH if os.path.isfile(SAVE_PATH) else LEGACY_SAVE_PATH

    @staticmethod
    def _read_save_state(path=None):
        """Read and validate a current save before any live state is changed.

        The title screen probes this too. A file merely existing is not enough
        to advertise CONTINUE: truncated JSON, structurally malformed data and
        old schemas all stay on the safe NEW GAME path instead of failing after
        the player has already selected them.
        """
        path = Game._save_read_path(path)
        with open(path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        if not isinstance(state, dict):
            raise ValueError("save root is not an object")
        if state.get('version') != SAVE_VERSION:
            raise ValueError(f"unsupported save version {state.get('version')!r}")

        player = state.get('player')
        if not isinstance(player, dict):
            raise ValueError("save has no player position")
        try:
            px = float(player['x'])
            py = float(player['y'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid player position") from exc
        if (not math.isfinite(px) or not math.isfinite(py)
                or not 0 <= px <= MAP_WIDTH or not 0 <= py <= MAP_HEIGHT):
            raise ValueError("player position is outside the city")

        for key in ('character', 'arch_job', 'weapons'):
            if not isinstance(state.get(key), dict):
                raise ValueError(f"invalid {key} record")
        for key in ('discovered', 'job_types_done'):
            value = state.get(key)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"invalid {key} list")
        for key in ('legend_rumors', 'legend_discovered', 'legend_garage',
                    'legend_mastery'):
            value = state.get(key, [])
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"invalid {key} list")
        for key in ('radio_index', 'radio_break_serial', 'city_event_seed'):
            if key in state and (isinstance(state[key], bool) or not isinstance(state[key], int)):
                raise ValueError(f"invalid {key}")
        arsenal = state['weapons']
        owned = arsenal.get('owned')
        ammo = arsenal.get('ammo')
        if (not isinstance(owned, list)
                or not all(isinstance(item, str) for item in owned)
                or not isinstance(ammo, dict)
                or not isinstance(arsenal.get('selected'), str)):
            raise ValueError("invalid weapons record")

        numeric = ('score', 'cash', 'banked', 'wanted_level', 'jobs_done',
                   'jobs_failed', 'side_missions_done', 'side_missions_failed',
                   'side_mission_serial', 'best_streak')
        for key in numeric:
            value = state.get(key)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"invalid {key}")
            if value < 0:
                raise ValueError(f"negative {key}")
        for kind, amount in ammo.items():
            if not isinstance(kind, str):
                raise ValueError("invalid ammunition type")
            if isinstance(amount, bool) or not isinstance(amount, int):
                raise ValueError("invalid ammunition count")
            if amount < 0:
                raise ValueError("negative ammunition")
        return state

    def loadable_save_exists(self, path=None):
        """Cheap title-screen probe, reparsing only when the file changes."""
        path = self._save_read_path(path)
        absolute = os.path.abspath(path)
        try:
            stat = os.stat(path)
            signature = (absolute, stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = (absolute, None, None)
        if signature == self._save_probe_signature:
            return self._save_probe_valid
        try:
            self._read_save_state(path)
            valid = True
        except (OSError, json.JSONDecodeError, ValueError):
            valid = False
        self._save_probe_signature = signature
        self._save_probe_valid = valid
        return valid

    def save_game(self, announce=True, path=None):
        here = self.active_rect().center
        self._store_current_ammo()
        state = {
            'version': SAVE_VERSION,
            'player': {'x': here[0], 'y': here[1]},
            'score': self.score,
            'cash': self.cash,
            'banked': self.banked,
            'wanted_level': self.wanted_level,
            'discovered': list(self.discovered),
            'legend_rumors': sorted(self.legend_rumors),
            'legend_discovered': sorted(self.legend_discovered),
            'legend_garage': sorted(self.legend_garage),
            'legend_mastery': sorted(self.legend_mastery),
            'radio_index': self.radio_index,
            'radio_break_serial': self.radio_break_serial,
            'city_event_seed': self.city_event_seed,
            'jobs_done': self.jobs_done,
            'jobs_failed': self.jobs_failed,
            'side_missions_done': self.side_missions_done,
            'side_missions_failed': self.side_missions_failed,
            'side_mission_serial': self.side_mission_serial,
            'best_streak': self.best_streak,
            'job_types_done': sorted(self.job_types_done),
            'character': {
                'look': self.character_look,
                'high_school': self.character_school,
            },
            'arch_job': {
                'unlocked': self.arch_job_unlocked,
                'completed': self.arch_job_completed,
            },
            'weapons': {
                'selected': self.weapon,
                'owned': sorted(self.owned_weapons),
                'ammo': self.weapon_ammo,
            },
        }
        try:
            target = os.fspath(path) if path is not None else SAVE_PATH
            parent = os.path.dirname(os.path.abspath(target))
            os.makedirs(parent, exist_ok=True)
            with open(target, 'w', encoding='utf-8') as f:
                json.dump(state, f)
            self._save_probe_signature = None
            if announce:
                self.add_toast("Game saved")
        except OSError as e:
            self.add_toast(f"Save failed: {e}")

    def load_game(self, path=None):
        try:
            state = self._read_save_state(path)
            if self.driving:                      # step out before teleporting
                self.driving.driver = None
                self.driving.parked = True
                traffic_hand_back(self.driving)
                self.driving = None
            self.player_rect.center = (state['player']['x'], state['player']['y'])
            self.player_fx = float(self.player_rect.centerx)
            self.player_fy = float(self.player_rect.centery)
            self.score = state.get('score', 0)
            self.cash = state.get('cash', 0)
            self.banked = state.get('banked', 0)
            self.wanted_level = min(WANTED_MAX, max(0, int(state.get('wanted_level', 0))))
            self.discovered = set(state.get('discovered', []))
            self.legend_rumors = {
                kind for kind in state.get('legend_rumors', []) if kind in LOCAL_LEGENDS
            }
            self.legend_discovered = {
                kind for kind in state.get('legend_discovered', []) if kind in LOCAL_LEGENDS
            }
            self.legend_garage = {
                kind for kind in state.get('legend_garage', []) if kind in LOCAL_LEGENDS
            }
            valid_mastery = (set(LOCAL_LEGENDS)
                             | {'trash_day', 'hill_hydrants', 'chain_escape'})
            self.legend_mastery = {
                kind for kind in state.get('legend_mastery', []) if kind in valid_mastery
            }
            self.local_challenge = None
            self.hill_hint_shown = 'hill_hydrants' in self.legend_mastery
            self.radio_index = int(state.get('radio_index', 0)) % len(RADIO_STATIONS)
            self.radio_break_serial = max(0, int(state.get('radio_break_serial', 0)))
            prior_event_seed = int(state.get('city_event_seed', self.city_event_seed))
            self.city_event_seed = (prior_event_seed * 1103515245 + 12345) & 0x3fffffff
            self.city_event_key = tuple(CITY_EVENT_DEFS)[self.city_event_seed % len(CITY_EVENT_DEFS)]
            self.city_event_announced = False
            self.halloween_kids = []
            self.halloween_jokes_told = 0
            self.reset_city_event_world()
            self.radio_break_after = self.frame + RADIO_BREAK_FIRST
            self.legend_hint_after = self.frame + LOCAL_LEGEND_HINT_FIRST
            self.jobs_done = state.get('jobs_done', 0)
            self.jobs_failed = state.get('jobs_failed', 0)
            self.side_missions_done = state.get('side_missions_done', 0)
            self.side_missions_failed = state.get('side_missions_failed', 0)
            self.side_mission_serial = state.get('side_mission_serial', 0)
            self.best_streak = state.get('best_streak', 0)
            self.job_types_done = {
                kind for kind in state.get('job_types_done', [])
                if kind in JOB_KIND_ORDER
            }
            self.recent_job_kinds = []
            profile = state.get('character', {})
            try:
                look = int(profile.get('look', 0))
            except (TypeError, ValueError):
                look = 0
            self.character_look = max(0, min(len(CHARACTER_LOOKS) - 1, look))
            valid_schools = {name for name, _group in HS_SPECIAL_CHOICES + STL_HIGH_SCHOOLS}
            school = str(profile.get('high_school', "NOT FROM AROUND HERE"))
            self.character_school = school if school in valid_schools else "NOT FROM AROUND HERE"
            arch = state.get('arch_job', {})
            self.arch_job_completed = bool(arch.get('completed', False))
            # v2 and early v3 saves had only the bank balance. Crossing the old
            # advertised threshold still earns the promised door permanently.
            self.arch_job_unlocked = bool(
                arch.get('unlocked', False) or self.arch_job_completed or
                self.banked >= ARCH_JOB_TARGET)
            self.arch_job_phase = (ARCH_COMPLETE if self.arch_job_completed else
                                   ARCH_READY if self.arch_job_unlocked else ARCH_LOCKED)
            self.arch_job_timer = 0
            self.arch_job_offer_after = self.frame + FPS * 2
            self.arch_victory_timer = 0
            self.streak = 0
            self.police = []
            self.foot_police = []
            self.roadblocks = []
            self.speech_bubbles = []
            here = self.active_rect().center
            self.pursuit_agency = police_jurisdiction_at(
                here[0] // TILE_SIZE, here[1] // TILE_SIZE)
            self.pending_pursuit_agency = self.pursuit_agency
            self.jurisdiction_timer = 0
            self.side_mission = None
            self.side_mission_cooldown = FPS * 2
            self.side_target_car = None
            self.side_target_pos = None
            self.smash_targets = []
            self.roadblock_deploy_after = self.frame
            self.foot_cop_respawn = 0
            self.bust_meter = 0
            self.peak_star = self.wanted_level
            self.crime_pos = None
            self.spotted = False
            self.was_spotted = False
            self.searching = False
            self.hidden = False
            self.hide_timer = 0
            self.heat_timer = 0
            self.wanted_decay_timer = 0
            arsenal = state.get('weapons', {})
            owned = {kind for kind in arsenal.get('owned', ['fists'])
                     if kind in WEAPON_DEFS}
            self.owned_weapons = owned | {'fists'}
            raw_ammo = arsenal.get('ammo', {})
            self.weapon_ammo = {
                kind: max(0, int(raw_ammo.get(kind, 0)))
                for kind in WEAPON_ORDER
            }
            self.throwable_system = throwable_logic.ThrowableSystem({
                kind: self.weapon_ammo.get(kind, 0)
                for kind in throwable_logic.THROWABLE_ORDER
            })
            for kind in throwable_logic.THROWABLE_ORDER:
                self.weapon_ammo[kind] = self.throwable_system.inventory(kind)
            selected = arsenal.get('selected', 'fists')
            if (selected not in self.owned_weapons
                    or (not WEAPON_DEFS[selected].get('melee')
                        and self.weapon_ammo.get(selected, 0) <= 0)):
                selected = 'fists'
            self.weapon = selected
            self.ammo = self.weapon_ammo.get(selected, 0)
            self.player_stamina = PLAYER_STAMINA_MAX
            self.sprint_ready = True
            self.sprint_active = False
            # Runs and finale attempts are not resumable. A latched finale gets
            # the objective exclusively; locked/completed games redeal normally.
            self.job = (None if self.arch_job_unlocked and not self.arch_job_completed
                        else self.deal_job())
            self.camera.snap_to(self.player_rect)
            self.add_toast("Game loaded")
            return True
        except FileNotFoundError:
            self.add_toast("No save file found")
            return False
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            self.add_toast(f"Load failed: {e}")
            return False

    # ---------------- helpers ----------------
    def add_toast(self, text):
        self.toasts.append(Toast(text))

    @staticmethod
    def speech_label(speaker):
        if speaker == 'player':
            return 'YOU'
        archetype = getattr(speaker, 'kind', 'local').split('#', 1)[0]
        return {
            'commuter': 'COMMUTER', 'suit': 'OFFICE WORKER',
            'streetwear': 'LOCAL', 'shopper': 'SHOPPER',
            'dog_walker': 'DOG WALKER', 'elder': 'NEIGHBOR',
            'hi_vis': 'ROAD CREW', 'jogger': 'JOGGER',
            'tourist': 'VISITOR', 'busker_sax': 'BUSKER',
            'cardinals': 'BALLPLAYER', 'cards_fan': 'CARDS FAN',
            'hoosier': 'SOUTH SIDER', 'cop': 'OFFICER',
        }.get(archetype, 'LOCAL')

    def add_speech_bubble(self, speaker, text, delay=0, duration=None):
        """Queue one frame-timed line over the person actually saying it."""
        start = self.frame + int(delay)
        duration = duration or int(FPS * 1.10)
        self.speech_bubbles.append({
            'speaker': speaker, 'text': str(text).upper(),
            'start': start, 'end': start + duration,
        })
        if len(self.speech_bubbles) > 12:
            del self.speech_bubbles[:-12]

    def active_rect(self):
        return self.driving.rect if self.driving else self.player_rect

    def arch_center(self):
        """World centre of the Gateway Arch footprint, or the station."""
        for entry in LANDMARKS:
            if entry[5] == "Gateway Arch":
                return ((entry[0] + entry[2] / 2.0) * TILE_SIZE,
                        (entry[1] + entry[3] / 2.0) * TILE_SIZE)
        return self.police_station

    def landmark_job_point(self, name):
        entry = next((entry for entry in LANDMARKS if entry[5] == name), None)
        return landmark_dropoff_point(entry) if entry is not None else self.arch_center()

    def arch_job_target_pos(self):
        if not self.arch_job_unlocked or self.arch_job_completed:
            return None
        if self.arch_job_phase in (ARCH_READY, ARCH_RETURN):
            return self.arch_center()
        if self.arch_job_phase == ARCH_CUTTER:
            return self.landmark_job_point("City Museum")
        if self.arch_job_phase in (ARCH_ESCAPE, ARCH_LAY_LOW):
            # Once you are on The Hill, LAY_LOW is a state, not a bullseye.
            if self.arch_job_phase == ARCH_LAY_LOW and self.on_the_hill():
                return None
            return self.landmark_job_point("The Hill")
        return None

    def on_the_hill(self):
        x, y = self.active_rect().center
        return hood_at(int(x) // TILE_SIZE, int(y) // TILE_SIZE) == 'hill'

    def arch_job_objective_text(self):
        phase = self.arch_job_phase
        if phase == ARCH_READY:
            return "MEET UNDER THE ARCH", "COME CLEAN", False
        if phase == ARCH_CUTTER:
            return "PICK UP AT CITY MUSEUM", "BORROW A CUTTER", False
        if phase == ARCH_RETURN:
            return "TAKE THE CUTTER TO GATEWAY ARCH", "YOU NEED A GETAWAY CAR", False
        if phase == ARCH_ESCAPE:
            return "GET IT TO THE HILL", "43 LB OF STAINLESS STEEL", True
        if phase == ARCH_LAY_LOW:
            if self.on_the_hill():
                return "LOSE THE COPS ON THE HILL", "USE THE GANGWAYS", True
            return "GET BACK TO THE HILL", "THE PACKAGE IS GETTING HEAVY", True
        return None

    def fail_arch_job(self, reason):
        if self.arch_job_phase not in ARCH_ACTIVE_PHASES:
            return
        self.arch_job_phase = ARCH_READY
        self.arch_job_timer = 0
        self.arch_job_offer_after = self.frame + FPS * 2
        self.add_callout("ARCH JOB FAILED", hud_HUD_RED, scale=2)
        self.add_toast(reason)

    def complete_arch_job(self):
        if self.arch_job_completed:
            return
        self.arch_job_completed = True
        self.arch_job_unlocked = True
        self.arch_job_phase = ARCH_COMPLETE
        self.arch_job_timer = 0
        self.arch_victory_timer = ARCH_VICTORY_HOLD_STEPS
        self.add_score(ARCH_JOB_SCORE, self.active_rect().center, mult=False)
        self.add_callout("ARCH JOB COMPLETE", hud_HUD_GOLD, scale=2)
        self.add_toast("The Italian Job. Missouri rules.")
        self.play_sound('cash', vol=1.0)
        # Let the finale breathe. Ordinary work returns after the card, not in
        # the same frame as the fifty-grand payoff.
        self.job = None
        self.job_cooldown = 0
        self.save_game(announce=False)

    def update_arch_victory(self):
        """Hold the whole city for one earned beat, then reopen the sandbox."""
        if self.arch_victory_timer <= 0:
            return False
        self.arch_victory_timer -= 1
        if self.arch_victory_timer <= 0 and self.job is None:
            self.job = self.deal_job()
            self.add_toast("St. Louis keeps moving.")
        return True

    def update_arch_job(self):
        """The real end of the $50,000 ladder. This sits beside the ordinary
        courier system so the finale can fail/retry without corrupting a Job."""
        # update_police() can enter the death state earlier in the same frame;
        # never let its wanted reset masquerade as a successful lay-low.
        if self.state != STATE_PLAYING:
            return
        if not self.arch_job_unlocked or self.arch_job_completed:
            return
        # A delivery already in the boot when the threshold is crossed gets to
        # finish. An unaccepted offer does not outrank the finale.
        if self.arch_job_phase == ARCH_READY and self.job is not None and self.job.collected:
            return

        here = self.active_rect().center
        target = self.arch_job_target_pos()
        near = (target is not None and
                math.hypot(here[0] - target[0], here[1] - target[1]) <= JOB_MARKER_RADIUS)

        if self.arch_job_phase == ARCH_READY:
            if self.frame < self.arch_job_offer_after:
                return
            if not near:
                return
            if self.wanted_level > 0:
                if self.frame % (FPS * 2) == 0:
                    self.add_toast("Come back clean. The Arch has enough attention.")
                return
            self.job = None
            self.arch_job_phase = ARCH_CUTTER
            self.add_callout("THE ARCH JOB", hud_HUD_GOLD, scale=2)
            self.add_toast("City Museum has a cutter. Of course it does.")
            self.play_sound('pickup', vol=0.7)
            return

        if self.arch_job_phase == ARCH_CUTTER:
            if near:
                self.arch_job_phase = ARCH_RETURN
                self.add_callout("GOT THE CUTTER", hud_HUD_GREEN, scale=2)
                self.add_toast("City Museum had a spare. Of course.")
                self.play_sound('pickup', vol=0.7)
            return

        if self.arch_job_phase == ARCH_RETURN:
            if not near:
                return
            if self.driving is None:
                if self.frame % (FPS * 2) == 0:
                    self.add_toast("You need a getaway car")
                return
            self.arch_job_phase = ARCH_ESCAPE
            self.arch_job_timer = ARCH_JOB_SECONDS * FPS
            self.hidden = False
            self.hide_timer = 0
            self.infraction_at.pop('arch_job', None)
            self.wanted_bump(WANTED_MAX - self.wanted_level, 'arch_job')
            self.cop_dispatch = 0
            self.add_callout("RUN!", hud_HUD_RED, scale=3)
            self.add_toast("The whole city saw that")
            self.add_toast("Cargo: 43 lb of stainless steel")
            self.play_sound('bad', vol=1.0)
            return

        if self.arch_job_phase in (ARCH_ESCAPE, ARCH_LAY_LOW):
            self.arch_job_timer = max(0, self.arch_job_timer - 1)
            if self.arch_job_timer <= 0:
                self.fail_arch_job("Too slow. Somebody put the piece back.")
                return
            if self.arch_job_phase == ARCH_ESCAPE and near:
                self.arch_job_phase = ARCH_LAY_LOW
                self.add_toast("Now lose them in the gangways")
            if (self.arch_job_phase == ARCH_LAY_LOW and self.on_the_hill() and
                    self.wanted_level == 0):
                self.complete_arch_job()

    def update_bank(self):
        """Under the span: bank what you are carrying."""
        if self.cash < BANK_MIN:
            return
        ax, ay = self.arch_center()
        here = self.active_rect().center
        if math.hypot(here[0] - ax, here[1] - ay) > BANK_RADIUS:
            return
        amount = int(self.cash)
        self.banked += amount
        self.cash -= amount
        self.add_callout(f"BANKED ${amount}", hud_HUD_GREEN, scale=2)
        self.play_sound('cash', vol=0.8)
        self.add_pop(here, f"${amount}", hud_HUD_GREEN)
        left = max(0, ARCH_JOB_TARGET - self.banked)
        if not self.arch_job_unlocked and left:
            self.add_toast(f"${left} to the Arch job")
        elif not self.arch_job_unlocked:
            self.arch_job_unlocked = True
            self.arch_job_phase = ARCH_READY
            self.arch_job_offer_after = self.frame + FPS * 2
            if self.job is not None and not self.job.collected:
                self.job = None
            self.add_callout("THE ARCH JOB", hud_HUD_GOLD, scale=2)
            self.add_toast("The Arch job is open. Somebody's waiting.")
            self.save_game(announce=False)
        elif self.arch_job_completed:
            self.add_toast("Safe under the Arch")
        else:
            self.add_toast("The Arch job is waiting under the Arch")

    def drop_cash(self, amount, pos):
        """Leave a roll of cash on the pavement where you went down."""
        if amount < BANK_MIN:
            return
        self.dropped.append({'x': pos[0], 'y': pos[1], 'amount': int(amount),
                             'born': self.frame})

    def update_dropped_cash(self):
        pr = self.active_rect()
        keep = []
        for d in self.dropped:
            if self.frame - d['born'] > DROPPED_CASH_LIFE:
                continue
            if math.hypot(pr.centerx - d['x'], pr.centery - d['y']) < DROPPED_CASH_RADIUS:
                self.cash += d['amount']
                self.add_pop((d['x'], d['y']), f"+${d['amount']}", hud_HUD_GREEN)
                self.add_callout("GOT IT BACK", hud_HUD_GREEN, scale=1)
                self.play_sound('cash', vol=0.7)
                continue
            keep.append(d)
        self.dropped = keep

    def arch_respawn_point(self):
        """Under the span of the Gateway Arch: where every life starts.

        The Arch's collision shape is two leg footings with open ground
        between them (_lm_solid_arch), so the centre of its footprint is
        walkable and unmistakable - you come to on the riverfront lawn with
        the legs either side of you, which is the one place on this map that
        can only be St. Louis.
        """
        for entry in LANDMARKS:
            if entry[5] != "Gateway Arch":
                continue
            lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
            cx = (lx + lw / 2.0) * TILE_SIZE
            cy = (ly + lh / 2.0) * TILE_SIZE
            spot = free_point_near(int(cx), int(cy), PLAYER_SIZE, PLAYER_SIZE,
                                   max_rings=12)
            if spot is not None:
                return spot
        return self.police_station

    # ---------------- feedback: score / pops / callouts ----------------
    def add_score(self, base, world_pos=None, mult=True):
        """Single funnel for every point the game awards. Chaos points run
        through the multiplier and feed it; delivery bonuses pass mult=False
        so the careful loop stays flat. Spawns a floating +N where it happened
        and a MULTIPLIER X? callout when a rung is crossed."""
        factor = self.multiplier if mult else 1
        gain = int(base * factor)
        self.score += gain
        if world_pos is not None:
            self.add_pop(world_pos, f"+{gain}",
                         hud_HUD_GOLD if mult and factor > 1 else hud_HUD_GREEN)
        if mult and base > 0:
            # A tallboy makes every reckless thing you do count twice toward
            # the next rung. It also makes you drive like this.
            self.mult_prog += base * (2.0 if self.grub_active('tallboy') else 1.0)
            self.mult_decay = 0
            rose = False
            while self.mult_prog >= MULT_RUNG and self.multiplier < MULT_MAX:
                self.mult_prog -= MULT_RUNG
                self.multiplier += 1
                rose = True
            if rose:                    # one callout for the landing rung, not each
                self.add_callout(f"MULTIPLIER X{self.multiplier}", hud_HUD_GOLD,
                                 scale=2, tag='mult')
        return gain

    def bump_multiplier(self, rungs):
        self.multiplier = min(MULT_MAX, self.multiplier + rungs)
        self.mult_decay = 0

    def reset_multiplier(self):
        if self.multiplier > 1:
            self.add_callout("MULTIPLIER LOST", hud_HUD_RED, tag='mult')
        self.multiplier = 1
        self.mult_prog = 0.0
        self.mult_decay = 0

    def update_multiplier(self):
        """Park and the multiplier bleeds away - keeps you moving and reckless."""
        if self.multiplier <= 1 and self.mult_prog <= 0.0:
            self.mult_decay = 0
            return
        self.mult_decay += 1
        if self.mult_decay < MULT_DECAY_GRACE:
            return
        if (self.mult_decay - MULT_DECAY_GRACE) % MULT_DECAY_STEP == 0:
            if self.mult_prog > 0.0:
                self.mult_prog = 0.0
            elif self.multiplier > 1:
                self.multiplier -= 1

    def add_pop(self, world_pos, text, col):
        # Three of these used to land on the same pixel and read as mush.
        # Fanning them out by index is enough to keep them all countable.
        n = len(self.pops)
        self.pops.append({'x': float(world_pos[0]) + (n % 3 - 1) * 14,
                          'y': float(world_pos[1]) - (n % 2) * 9,
                          'text': text, 'col': col, 'born': self.frame})
        if len(self.pops) > 48:
            del self.pops[:len(self.pops) - 48]

    def add_callout(self, text, col=None, ttl=None, scale=2, tag=None):
        """Big centre-screen shout.

        `tag` makes a callout *replace* its predecessor instead of queueing
        behind it. Without it MULTIPLIER X2, X3 and MULTIPLIER LOST all sat on
        screen at once, three states of one thing shouting over each other.
        """
        if tag is not None:
            self.callouts = [c for c in self.callouts if c.get('tag') != tag]
        self.callouts.append({'text': text, 'col': col or hud_HUD_GOLD,
                              'born': self.frame, 'ttl': ttl or FPS * 2,
                              'scale': scale, 'tag': tag})
        if len(self.callouts) > 3:
            self.callouts.pop(0)

    # ---------------- feedback: impact juice ----------------
    def load_soundtrack(self):
        """Load the packaged MIDI without making audio support a boot requirement."""
        if pygame.mixer.get_init() is None or not os.path.isfile(GAME_MUSIC_PATH):
            return False
        try:
            pygame.mixer.music.load(GAME_MUSIC_PATH)
            pygame.mixer.music.set_volume(GAME_MUSIC_VOLUME)
        except (pygame.error, OSError):
            return False
        self.music_available = True
        return True

    def sync_soundtrack(self):
        """Start, pause, or resume music to match the front-end/game state."""
        if not self.music_available:
            return
        should_play = (self.state in (STATE_PLAYING, STATE_DEAD)
                       and not self.music_muted)
        try:
            if should_play and not self.music_started:
                pygame.mixer.music.play(-1)
                self.music_started = True
                self.music_paused = False
            elif should_play and self.music_paused:
                pygame.mixer.music.unpause()
                self.music_paused = False
            elif not should_play and self.music_started and not self.music_paused:
                pygame.mixer.music.pause()
                self.music_paused = True
        except pygame.error:
            self.music_available = False

    def toggle_soundtrack(self):
        if not self.music_available:
            self.add_toast("Music unavailable")
            return
        self.music_muted = not self.music_muted
        self.sync_soundtrack()
        self.add_toast("Music off" if self.music_muted else "Music on")

    def cycle_radio(self):
        if self.driving is not None and self.driving.variant == 'trans_am':
            self.radio_index = 0
            self.add_toast("THE RADIO IS STILL STUCK ON K-SHE 95ISH")
            return
        self.radio_index = (self.radio_index + 1) % len(RADIO_STATIONS)
        self.radio_break_after = self.frame + FPS * 2
        station = RADIO_STATIONS[self.radio_index]
        self.add_callout(station['name'], station['color'], ttl=FPS, scale=1)
        self.play_sound(f'radio{self.radio_index}', vol=0.65)

    def update_radio_programming(self):
        if self.driving is None or self.frame < self.radio_break_after:
            return
        station = RADIO_STATIONS[self.radio_index]
        line = station['breaks'][self.radio_break_serial % len(station['breaks'])]
        self.radio_break_serial += 1
        self.radio_break_after = self.frame + RADIO_BREAK_GAP
        self.add_toast(f"{station['name']}: {line}")
        self.play_sound(f'radio{self.radio_index}', vol=0.42, gap=FPS)

    def reset_city_event_world(self):
        """Undo temporary actors and rail tuning before staging another day."""
        for ped in self.pedestrians:
            if getattr(ped, 'event_actor', False):
                ped.set_kind(self._ped_kind_for(*ped.rect.center))
            ped.event_actor = False
            ped.event_kid = False
            ped.joke_told = False
        self.halloween_kids = []
        for vehicle in self.rail:
            if vehicle.kind == 'trolley':
                vehicle.speed = math.copysign(TROLLEY_SPEED, vehicle.speed or 1.0)

    def stage_city_event_people(self):
        """Retype a visible slice of the crowd so today's event changes streets."""
        self.reset_city_event_world()
        tile = CITY_EVENT_VENUES.get(self.city_event_key)
        center = ((tile[0] * TILE_SIZE + TILE_SIZE // 2,
                   tile[1] * TILE_SIZE + TILE_SIZE // 2)
                  if tile is not None else self.active_rect().center)
        nearby = sorted(self.pedestrians,
                        key=lambda ped: math.dist(center, ped.rect.center))[:10]
        key = self.city_event_key
        if key == 'halloween_jokes':
            self.halloween_kids = nearby[:4]
            for index, ped in enumerate(self.halloween_kids):
                ped.set_kind(f'trick_or_treater#{index % peds__VARIANTS}')
                ped.event_kid = True
                ped.event_actor = True
                ped.joke_told = False
        else:
            archetype = {
                'cardinals_day': 'cards_fan',
                'soulard_parade': 'tourist',
                'dogtown_parade': 'tourist',
                'tower_grove_market': 'shopper',
                'cherokee_festival': 'streetwear',
                'grand_construction': 'hi_vis',
                'blues_night': 'streetwear',
            }.get(key)
            if archetype:
                for index, ped in enumerate(nearby[:6]):
                    ped.set_kind(f'{archetype}#{index % peds__VARIANTS}')
                    ped.event_actor = True
                    angle = math.tau * index / 6.0
                    spot = pedestrian_point_near(
                        center[0] + math.cos(angle) * (54 + 10 * (index % 2)),
                        center[1] + math.sin(angle) * (54 + 10 * (index % 2)),
                        max_rings=5)
                    if spot is not None:
                        ped.rect.center = spot

    def city_event_center(self):
        tile = CITY_EVENT_VENUES.get(self.city_event_key)
        if tile is None:
            return None
        return (tile[0] * TILE_SIZE + TILE_SIZE // 2,
                tile[1] * TILE_SIZE + TILE_SIZE // 2)

    def update_city_event(self):
        if not self.city_event_announced and self.frame >= CITY_EVENT_ANNOUNCE_AT:
            self.city_event_announced = True
            title, line, color = CITY_EVENT_DEFS[self.city_event_key]
            self.add_callout(title, color, ttl=FPS * 2, scale=2)
            self.add_toast(line)
            self.stage_city_event_people()
            if self.city_event_key == 'first_monday':
                self.play_sound('wailmid', self.active_rect().center, vol=0.62)
            elif self.city_event_key == 'blues_night':
                self.radio_index = 0
            elif self.city_event_key == 'trolley_delay':
                for vehicle in self.rail:
                    if vehicle.kind == 'trolley':
                        vehicle.speed = math.copysign(0.65, vehicle.speed)
        elif self.city_event_key == 'halloween_jokes' and self.frame % (FPS * 8) == 0:
            # Streamed children keep the costume even after population recycling.
            for index, ped in enumerate(self.halloween_kids):
                if not getattr(ped, 'joke_told', False):
                    ped.set_kind(f'trick_or_treater#{index % peds__VARIANTS}')

        center = self.city_event_center()
        scale = CITY_EVENT_TRAFFIC_SCALE.get(self.city_event_key)
        if center is not None and scale is not None:
            # Named events happen in their named neighborhoods. Ambient cars
            # bunch and crawl there, while the player's car stays responsive.
            limit = (TILE_SIZE * 6) ** 2
            for car in self.cars:
                if car.driver is None and not car.parked:
                    dx = car.rect.centerx - center[0]
                    dy = car.rect.centery - center[1]
                    if dx * dx + dy * dy <= limit:
                        cap = car.base_max_speed * scale
                        car.velocity = max(-cap, min(cap, car.velocity))

    def try_halloween_joke(self):
        if self.city_event_key != 'halloween_jokes' or self.driving is not None:
            return False
        center = self.player_rect.center
        candidates = [ped for ped in self.halloween_kids
                      if ped in self.pedestrians
                      and not getattr(ped, 'joke_told', False)
                      and math.dist(center, ped.rect.center) <= 46]
        if not candidates:
            return False
        child = min(candidates, key=lambda ped: math.dist(center, ped.rect.center))
        child.joke_told = True
        joke = HALLOWEEN_JOKES[self.halloween_jokes_told % len(HALLOWEEN_JOKES)]
        self.halloween_jokes_told += 1
        self.cash += 25
        self.player_hp = min(PLAYER_MAX_HP, self.player_hp + 12)
        self.add_callout("JOKE FOR CANDY", CITY_EVENT_DEFS['halloween_jokes'][2],
                         ttl=FPS * 2, scale=1)
        self.add_toast(joke)
        self.add_pop(child.rect.center, "+$25 + CANDY", hud_HUD_GOLD)
        self.play_sound('cash', child.rect.center, vol=0.55)
        return True

    def update_special_vehicle_audio(self):
        center = self.active_rect().center
        audible = [car for car in self.cars
                   if math.dist(center, car.rect.center) <= 900]
        for variant, key, cadence, volume, reach in (
                ('mudfoot', 'bigblock', 92, 0.72, 920),
                ('grocery_cart', 'cart_rattle', 73, 0.62, 760)):
            candidates = [car for car in audible if car.variant == variant]
            if candidates and self.frame % cadence == 0:
                nearest = min(candidates, key=lambda car: math.dist(center, car.rect.center))
                self.play_sound(key, nearest.rect.center, vol=volume,
                                gap=cadence - 10, reach=reach)
        trucks = [car for car in audible
                  if car.variant in ('garbage_truck', 'street_sweeper',
                                     'forestry_truck')]
        if trucks:
            nearest = min(trucks, key=lambda car: math.dist(center, car.rect.center))
            if nearest.velocity < -0.15 and self.frame % 55 == 0:
                self.play_sound('reverse_beep', nearest.rect.center, vol=0.60,
                                gap=45, reach=800)
            elif self.frame % 181 == 0:
                self.play_sound('hydraulic', nearest.rect.center, vol=0.55,
                                gap=150, reach=760)

    def draw_city_event_world(self):
        """Keep the event's interaction legible without adding another map icon."""
        if self.city_event_key != 'halloween_jokes' or self.driving is not None:
            return
        for child in self.halloween_kids:
            if getattr(child, 'joke_told', False):
                continue
            sx, sy = self.camera.apply_pos(child.rect.center)
            if not (-24 < sx < SCREEN_WIDTH + 24 and -24 < sy < SCREEN_HEIGHT + 24):
                continue
            pulse = 10 + (self.frame // 6) % 3
            pygame.draw.circle(self.screen, (250, 142, 58),
                               (int(sx), int(sy)), pulse, 1)
            label = "E: TELL JOKE"
            hud_text(self.screen, label,
                     int(sx) - hud_text_width(label, 1) // 2, int(sy) - 24,
                     (255, 224, 130), True, 1)

    def play_sound(self, key, world_pos=None, vol=1.0, gap=0, reach=620.0):
        """Every sound the game makes goes through here, so the camera is the
        listener and one call site can never forget to pan."""
        if not snd__enabled:
            return
        snd_play(key, world_pos, self.active_rect().center, vol, gap, reach)

    def play_impact(self, world_pos, speed, gap=6):
        """Three severities of crunch, picked by how hard it landed."""
        sev = 0 if speed < 4.0 else (1 if speed < 7.0 else 2)
        self.play_sound(f'impact{sev}', world_pos,
                        vol=0.45 + 0.18 * sev, gap=gap)

    def kick(self, amp, freeze=0, flash=0):
        """One call for 'something just hit': camera shake + optional hitstop
        + optional white flash. All render-side or a whole-step skip, so the
        sim stays frame-rate-independent and the invariants stay trivially
        satisfied on a frozen step."""
        self.shake = min(10.0, self.shake + amp)
        if freeze > self.freeze:
            self.freeze = min(4, freeze)
        if flash > self.hit_flash:
            self.hit_flash = min(6, flash)

    def spawn_burst(self, world_pos, n, kinds=('spark',), spd=2.5):
        """A puff of 1-2px particles. Jitter is seeded per burst from the frame
        and position, so ordering between bursts can never matter."""
        rng = random.Random(self.frame * 9173 + int(world_pos[0]) * 31
                            + int(world_pos[1]) * 7 + len(self.fx))
        for _ in range(n):
            ang = rng.uniform(0, math.tau)
            v = rng.uniform(0.3, 1.0) * spd
            self.fx.append({'x': float(world_pos[0]), 'y': float(world_pos[1]),
                            'vx': math.cos(ang) * v, 'vy': math.sin(ang) * v,
                            'life': rng.randint(11, 26),
                            'kind': kinds[rng.randrange(len(kinds))]})
        if len(self.fx) > 240:
            del self.fx[:len(self.fx) - 240]

    def update_fx(self):
        for p in self.fx:
            p['x'] += p['vx']
            p['y'] += p['vy']
            if p['kind'] == 'smoke':
                p['vy'] -= 0.05
                p['vx'] *= 0.93
                p['vy'] *= 0.95
            else:
                p['vy'] += 0.13
                p['vx'] *= 0.90
                p['vy'] *= 0.92
            p['life'] -= 1
        if self.fx:
            self.fx = [p for p in self.fx if p['life'] > 0]
        if self.shake > 0.0:
            self.shake *= 0.85
            if self.shake < 0.4:
                self.shake = 0.0
        if self.hit_flash > 0:
            self.hit_flash -= 1

    # ---------------- gore + ground stains ----------------
    def add_decal(self, world_pos, kind='blood', size=1.0):
        """A permanent-ish stain on the road. Deterministic per decal from the
        frame + position, so a captured frame is reproducible."""
        self.decals.append({'x': float(world_pos[0]), 'y': float(world_pos[1]),
                            'kind': kind, 'size': size,
                            'seed': (self.frame * 2654435761
                                     + int(world_pos[0]) * 40503
                                     + int(world_pos[1])) & 0x7fffffff})
        if len(self.decals) > DECAL_MAX:
            del self.decals[:len(self.decals) - DECAL_MAX]

    def combo_window(self):
        """How long the current streak survives without a fresh hit.

        A flat two seconds meant a streak died in the gap between one knot of
        people and the next, so nothing above the second rung of the ladder
        was reachable. It opens up as the streak grows: get one going and the
        game gives you room to keep it.
        """
        t = min(1.0, self.combo / float(COMBO_WINDOW_RUNGS))
        return int(COMBO_WINDOW_MIN + (COMBO_WINDOW_MAX - COMBO_WINDOW_MIN) * t)

    def bump_combo(self, world_pos, base, speed=0.0):
        """One rung of a rampage streak: score, shout, heat."""
        self.combo += 1
        self.combo_timer = self.combo_window()
        # Speed is the whole read on a splatter - a 6 px/step hit through a
        # crowd should pay very differently from rolling into somebody at
        # walking pace, and it did not before.
        boost = 1.0 + min(1.0, speed / max(1.0, PLAYER_CAR_MAX_SPEED)) * 0.9
        self.add_score(int(base * min(self.combo, 16) * boost), world_pos)
        if self.combo in COMBO_SHOUTS:
            self.add_callout(COMBO_SHOUTS[self.combo], hud_HUD_RED, scale=2)
            self.bump_multiplier(1)
        if self.combo == 12:
            self.wanted_level = max(self.wanted_level, 3)
            self.add_callout("YOU MONSTER", hud_HUD_RED)

    def splatter_ped(self, ped, impulse, score=True, speed=0.0):
        """Kill a pedestrian: gore, a stain that stays, and a replacement
        walker somewhere else so the street never empties out."""
        pos = ped.rect.center
        self.add_decal(pos, 'blood', 1.0)
        self.spawn_burst(pos, 9, ('blood', 'blood', 'debris'), 2.6)
        self.kick(2.2)
        if ped in self.pedestrians:
            self.pedestrians.remove(ped)
            if ped in self.halloween_kids:
                self.halloween_kids.remove(ped)
            spot = random_pedestrian_point()
            nx, ny = spot
            self.pedestrians.append(Pedestrian(nx, ny, self._ped_kind_for(nx, ny)))
        if score:
            self.bump_combo(pos, 12, speed)
            self.frenzy_hit('ped')
            self.wanted_bump(1, 'pedestrian')
        # everyone who saw it runs
        for other in self.pedestrians:
            ox = other.rect.centerx - pos[0]
            oy = other.rect.centery - pos[1]
            if ox * ox + oy * oy < 130 * 130 and other.down_timer <= 0:
                other._flee((ox, oy), random.randint(80, 140))

    # ---------------- combat ----------------
    def aim_angle(self):
        """Where an attack goes: the way you last walked, or drove."""
        if self.driving is not None:
            return self.driving.angle
        return self.player_aim

    def _store_current_ammo(self):
        if self.weapon in self.weapon_ammo and not WEAPON_DEFS[self.weapon].get('melee'):
            self.weapon_ammo[self.weapon] = max(0, int(self.ammo))

    def equip_weapon(self, kind, announce=True):
        if kind not in WEAPON_DEFS or kind not in self.owned_weapons:
            return False
        self._store_current_ammo()
        self.weapon = kind
        self.ammo = self.weapon_ammo.get(kind, 0)
        if announce:
            self.add_toast(WEAPON_DEFS[kind]['label'])
        return True

    def cycle_weapon(self, step=1):
        """Cycle only through weapons currently owned and usable."""
        self._store_current_ammo()
        available = [kind for kind in WEAPON_ORDER
                     if kind in self.owned_weapons
                     and (WEAPON_DEFS[kind].get('melee')
                          or self.weapon_ammo.get(kind, 0) > 0)]
        if not available:
            available = ['fists']
        try:
            index = available.index(self.weapon)
        except ValueError:
            index = -1 if step >= 0 else 0
        return self.equip_weapon(available[(index + step) % len(available)])

    def player_attack(self):
        """SPACE: swing the selected melee weapon or fire the selected gun."""
        if self.state != STATE_PLAYING or self.show_map:
            return
        if self.driving is not None:
            self.add_toast("Get out to fight")
            return
        if self.attack_cd > 0:
            return
        info = WEAPON_DEFS.get(self.weapon, WEAPON_DEFS['fists'])
        if info.get('melee'):
            self.swing_melee(self.weapon)
        elif info.get('throwable') and self.ammo > 0:
            self.throw_weapon()
        elif self.ammo > 0:
            self.fire_weapon()
        else:
            self.owned_weapons.discard(self.weapon)
            self.equip_weapon('bat' if 'bat' in self.owned_weapons else 'fists', False)
            self.add_toast("Out of ammo")

    def throw_punch(self):
        """Compatibility wrapper used by tests and the original control path."""
        return self.swing_melee('fists')

    def throw_weapon(self):
        """Launch the selected explosive using the common 60 Hz sidecar."""
        kind = self.weapon
        if kind not in throwable_logic.THROWABLE_ORDER:
            return False
        ang = self.aim_angle()
        result = self.throwable_system.throw(
            kind, self.player_rect.center,
            (math.cos(ang), math.sin(ang)), owner_id='player')
        if not result.success:
            if result.reason == 'empty':
                self.owned_weapons.discard(kind)
                self.equip_weapon('bat' if 'bat' in self.owned_weapons else 'fists', False)
                self.add_toast("Out of ammo")
            return False
        self.attack_cd = WEAPON_DEFS[kind]['cooldown']
        self.ammo = self.throwable_system.inventory(kind)
        self.weapon_ammo[kind] = self.ammo
        self.play_sound('whiff', self.player_rect.center, vol=0.55)
        self.spawn_burst(self.player_rect.center, 3, ('debris',), 1.6)
        self.wanted_bump(1, 'gunfire')
        if self.ammo <= 0:
            self.owned_weapons.discard(kind)
            self.equip_weapon('bat' if 'bat' in self.owned_weapons else 'fists', False)
        return True

    def swing_melee(self, kind=None):
        kind = kind if kind in ('fists', 'bat') else 'fists'
        info = WEAPON_DEFS[kind]
        reach = info['range']
        arc = info['arc']
        self.attack_cd = info['cooldown']
        self.punch_timer = 8
        self.play_sound('whiff', self.player_rect.center, vol=0.5)
        ang = self.aim_angle()
        px, py = self.player_rect.center
        tip = (px + math.cos(ang) * reach * 0.8,
               py + math.sin(ang) * reach * 0.8)
        self.spawn_burst(tip, 2, ('debris',), 1.0)
        hit_any = False
        actors = ([('cop', cop) for cop in self.foot_police]
                  + [('ped', ped) for ped in self.pedestrians])
        actors.sort(key=lambda item: math.hypot(item[1].rect.centerx - px,
                                                item[1].rect.centery - py))
        for actor_kind, actor in actors:
            if not self._in_arc(actor.rect.center, ang, reach, arc):
                continue
            hit_any = True
            kb = pygame.Vector2(math.cos(ang), math.sin(ang)) * (9.0 if kind == 'bat' else 6.5)
            if actor_kind == 'cop':
                self.damage_foot_cop(actor, info['damage'], kb, cause=kind)
            else:
                ped = actor
                if kind == 'bat' or ped.down_timer > 0:
                    self.splatter_ped(ped, kb)
                else:
                    ped.knock = kb
                    ped.mood = 'down'
                    ped.down_timer = random.randint(50, 90)
                    self.add_score(6, ped.rect.center)
                    self.wanted_bump(1, 'pedestrian')
                    self.spawn_burst(ped.rect.center, 3, ('debris',), 1.6)
            self.kick(1.4)
            break
        if not hit_any:
            for car in self.combat_vehicle_pool():
                if not self._in_arc(car.rect.center, ang, reach + 6, arc):
                    continue
                car.damage(info['car_damage'])
                self.play_sound('punch', car.rect.center, vol=0.6)
                self.spawn_burst(car.rect.center, 4, ('spark', 'glass'), 2.0)
                self.kick(1.6)
                if car in self.police:
                    self.wanted_bump(1, 'cop')
                break

    def fire_pistol(self):
        """Compatibility wrapper for the original pistol-only API."""
        self.owned_weapons.add('pistol')
        if self.weapon != 'pistol':
            self.weapon = 'pistol'
        self.ammo = self.weapon_ammo.get('pistol', self.ammo)
        return self.fire_weapon()

    def fire_weapon(self):
        kind = self.weapon
        info = WEAPON_DEFS.get(kind)
        if info is None or info.get('melee') or self.ammo <= 0:
            return
        self.play_sound('gun', self.player_rect.center, vol=0.7)
        self.attack_cd = info['cooldown']
        self.ammo -= 1
        self.weapon_ammo[kind] = self.ammo
        ang = self.aim_angle()
        px, py = self.player_rect.center
        mx = px + math.cos(ang) * 12
        my = py + math.sin(ang) * 12
        pellets = info.get('pellets', 1)
        spread = info.get('spread', 0.0)
        for index in range(pellets):
            if pellets <= 1:
                shot_ang = ang + random.uniform(-spread, spread)
            else:
                shot_ang = ang + spread * (index / (pellets - 1) - 0.5) * 2.0
                shot_ang += random.uniform(-0.018, 0.018)
            self.bullets.append({
                'x': float(mx), 'y': float(my),
                'vx': math.cos(shot_ang) * info['speed'],
                'vy': math.sin(shot_ang) * info['speed'],
                'life': info['life'], 'damage': info['damage'], 'kind': kind})
        burst = 7 if kind == 'shotgun' else 3
        self.spawn_burst((mx, my), burst, ('spark',), 2.8 if kind == 'shotgun' else 2.2)
        self.kick(2.0 if kind == 'shotgun' else 0.6 if kind == 'smg' else 0.8)
        self.wanted_bump(1, 'gunfire')
        if self.ammo <= 0:
            self.owned_weapons.discard(kind)
            self.equip_weapon('bat' if 'bat' in self.owned_weapons else 'fists', False)
            self.add_toast("Out of ammo")

    def _in_arc(self, target, ang, reach, arc=PUNCH_ARC):
        px, py = self.player_rect.center
        dx, dy = target[0] - px, target[1] - py
        if dx * dx + dy * dy > reach * reach:
            return False
        diff = (math.atan2(dy, dx) - ang + math.pi) % math.tau - math.pi
        return abs(diff) <= arc

    def damage_foot_cop(self, cop, damage, impulse=None, cause='attack', lethal=False):
        """One damage route for fists, bats, bullets, blasts and car impacts."""
        if cop not in self.foot_police:
            return False
        impulse = pygame.Vector2(impulse or (0, 0))
        cop.hp -= float(damage)
        cop.hit_stun = max(cop.hit_stun, COP_FOOT_HIT_STUN)
        cop.knock = impulse
        cop.alert = 'chase'
        cop.last_seen = self.player_rect.center
        cop.search_timer = COP_FOOT_GIVEUP
        cop.chase_steps = 0
        self.bust_meter = max(0, self.bust_meter - BUST_CONTACT_STEPS // 3)
        self.spawn_burst(cop.rect.center, 4, ('blood', 'debris'), 1.9)
        self.play_sound('punch', cop.rect.center, vol=0.65, gap=3)
        self.wanted_bump(1, 'cop')
        if lethal or cop.hp <= 0:
            self.kill_foot_cop(cop, cause, impulse)
        elif damage >= PUNCH_DAMAGE:
            cop.down_timer = max(cop.down_timer, COP_FOOT_KNOCKDOWN)
            self.add_score(30, cop.rect.center)
        return True

    def kill_foot_cop(self, cop, cause='attack', impulse=None):
        if cop not in self.foot_police:
            return False
        pos = cop.rect.center
        self.foot_police.remove(cop)
        self.foot_cop_respawn = max(self.foot_cop_respawn, COP_FOOT_RESPAWN)
        self.add_decal(pos, 'blood', 1.15)
        self.spawn_burst(pos, 11, ('blood', 'blood', 'debris'), 3.0)
        self.kick(3.0, freeze=1)
        self.add_score(250, pos)
        self.add_callout("OFFICER DOWN", hud_HUD_RED, ttl=FPS, scale=1)
        self.frenzy_hit('cop')
        # Killing an officer is never a one-star misunderstanding.
        self.wanted_level = min(WANTED_MAX, max(3, self.wanted_level + 1))
        self.peak_star = max(self.peak_star, self.wanted_level)
        self.heat_timer = 0
        self.wanted_decay_timer = 0
        self.crime_pos = pos
        self.crime_frame = self.frame
        for ped in self.pedestrians:
            dx, dy = ped.rect.centerx - pos[0], ped.rect.centery - pos[1]
            if dx * dx + dy * dy < 160 * 160:
                ped._flee((dx, dy), random.randint(100, 170))
        return True

    def update_bullets(self):
        if not self.bullets:
            return
        live = []
        for b in self.bullets:
            b['x'] += b['vx']
            b['y'] += b['vy']
            b['life'] -= 1
            if b['life'] <= 0:
                continue
            if not (0 <= b['x'] < MAP_WIDTH and 0 <= b['y'] < MAP_HEIGHT):
                continue
            hit = pygame.Rect(0, 0, 4, 4)
            hit.center = (int(b['x']), int(b['y']))
            if is_blocked(hit):
                self.spawn_burst(hit.center, 3, ('spark',), 1.8)
                continue
            if self.damage_smash_target(hit, b.get('damage', BULLET_DAMAGE)):
                continue
            struck = False
            for cop in list(self.foot_police):
                if cop.rect.inflate(5, 5).colliderect(hit):
                    self.damage_foot_cop(
                        cop, b.get('damage', BULLET_DAMAGE),
                        pygame.Vector2(b['vx'], b['vy']) * 0.42,
                        cause=b.get('kind', 'pistol'))
                    struck = True
                    break
            if struck:
                continue
            for ped in list(self.pedestrians):
                if ped.rect.inflate(4, 4).colliderect(hit):
                    self.splatter_ped(ped, pygame.Vector2(b['vx'], b['vy']) * 0.35)
                    struck = True
                    break
            if struck:
                continue
            for car in self.combat_vehicle_pool():
                if car is self.driving or not car.rect.colliderect(hit):
                    continue
                car.damage(b.get('damage', BULLET_DAMAGE))
                self.play_impact(car.rect.center, 5.0, gap=3)
                self.spawn_burst(hit.center, 4, ('spark', 'glass'), 2.2)
                if car in self.police:
                    self.wanted_bump(1, 'cop')
                struck = True
                break
            if struck:
                continue
            live.append(b)
        self.bullets = live

    def throwable_targets(self):
        """Snapshot live actors for the renderer-agnostic throwable system."""
        targets = []
        lookup = {}

        def add(kind, actor, position, radius, blast=1.0, fire=1.0):
            key = (kind, id(actor))
            lookup[key] = actor
            targets.append(throwable_logic.TargetSnapshot(
                key, position, radius, blast, fire))

        for cop in self.foot_police:
            add('cop', cop, cop.rect.center, 7.0)
        for ped in self.pedestrians:
            add('ped', ped, ped.rect.center, 7.0)
        for target in self.smash_targets:
            if target['hp'] > 0:
                add('smash', target, target['pos'], 9.0)
        for car in self.combat_vehicle_pool():
            if car is self.driving:
                continue
            add('car', car, car.rect.center, max(car.width, car.height) * 0.5,
                blast=0.72, fire=0.55)
        if self.driving is not None:
            add('car', self.driving, self.driving.rect.center,
                max(self.driving.width, self.driving.height) * 0.5,
                blast=0.72, fire=0.55)
        else:
            add('player', self, self.player_rect.center, PLAYER_SIZE * 0.35,
                blast=0.65, fire=0.5)
        return tuple(targets), lookup

    @staticmethod
    def throwable_collision(_old, new):
        hit = pygame.Rect(0, 0, 4, 4)
        hit.center = (int(new[0]), int(new[1]))
        return is_blocked(hit)

    def update_throwables(self):
        targets, lookup = self.throwable_targets()
        events = self.throwable_system.update(
            1, targets=targets, collision_query=self.throwable_collision)
        for impact in events.impacts:
            kinds = ('glass', 'spark') if impact.kind == throwable_logic.FIRE_BOTTLE else ('debris',)
            self.spawn_burst(impact.position, 5, kinds, 1.8)
            self.play_impact(impact.position, 4.0, gap=4)
        for blast in events.blasts:
            self.spawn_burst(blast.center, 32,
                             ('spark', 'spark', 'smoke', 'debris'), 5.2)
            self.add_decal(blast.center, 'scorch', 1.7)
            self.play_sound('boom', blast.center, vol=1.0, gap=4, reach=950.0)
            snd_duck(30)
            self.kick(8.0, freeze=2, flash=5)
            self.add_score(75, blast.center, mult=True)
            self.wanted_bump(1, 'explosion')
        for fire in events.fires_started:
            self.add_decal(fire.center, 'scorch', 1.25)
            self.spawn_burst(fire.center, 16, ('spark', 'smoke'), 3.0)
            self.play_sound('boom', fire.center, vol=0.65, gap=4, reach=650.0)
            self.kick(3.5, flash=2)
            self.wanted_bump(1, 'explosion')

        killed_peds = set()
        for event in events.damage:
            actor = lookup.get(event.target_id)
            if actor is None:
                continue
            kind = event.target_id[0]
            impulse = pygame.Vector2(event.impulse)
            if kind == 'cop' and actor in self.foot_police:
                self.damage_foot_cop(actor, event.damage, impulse,
                                     cause=event.cause,
                                     lethal=event.damage >= actor.hp)
            elif kind == 'ped' and actor in self.pedestrians and actor not in killed_peds:
                killed_peds.add(actor)
                self.splatter_ped(actor, impulse, speed=PLAYER_CAR_MAX_SPEED)
            elif kind == 'car':
                actor.damage(event.damage)
                if actor in self.police or actor in self.roadblock_units():
                    self.wanted_bump(1, 'cop')
            elif kind == 'smash' and actor.get('hp', 0) > 0:
                rect = pygame.Rect(0, 0, 16, 20)
                rect.center = actor['pos']
                self.damage_smash_target(rect, event.damage)
            elif kind == 'player' and self.state == STATE_PLAYING:
                self.player_hp -= event.damage
                self.hurt_cd = max(self.hurt_cd, event.status_steps)
                if self.player_hp <= 0:
                    self.player_hp = 0
                    self.wasted("CAUGHT IN THE BLAST")

    def update_weapon_pickups(self):
        pr = self.active_rect()
        for w in self.weapon_pickups:
            if w['taken']:
                if self.frame - w['taken'] >= WEAPON_RESPAWN:
                    w['taken'] = 0
                continue
            if math.hypot(pr.centerx - w['x'], pr.centery - w['y']) < 26:
                w['taken'] = self.frame
                kind = w.get('kind', 'pistol')
                info = WEAPON_DEFS[kind]
                self._store_current_ammo()
                self.owned_weapons.add(kind)
                if info.get('throwable'):
                    self.throwable_system.add_inventory(kind, info['ammo'])
                    self.weapon_ammo[kind] = self.throwable_system.inventory(kind)
                elif not info.get('melee'):
                    self.weapon_ammo[kind] = min(999, self.weapon_ammo.get(kind, 0)
                                                  + info['ammo'])
                self.weapon = kind
                self.ammo = self.weapon_ammo.get(kind, 0)
                self.play_sound('weapon', vol=0.7)
                self.add_callout(info['label'], hud_HUD_GOLD, ttl=FPS, scale=1)
                pop = "+BAT" if info.get('melee') else f"+{info['ammo']}"
                self.add_pop((w['x'], w['y']), pop, hud_HUD_GOLD)

    # ---------------- grub: St. Louis power-ups ----------------
    def grub_active(self, key):
        """True while that power-up is still running."""
        return self.grub_until.get(key, 0) > self.frame

    def grub_seconds_left(self, key):
        return max(0, (self.grub_until.get(key, 0) - self.frame)) // FPS

    def eat_grub(self, kind, world_pos):
        """Take a food pickup: heal, start its clock, and shout about it."""
        label, secs, hud_col, _marker, _blurb = GRUB_KINDS[kind]
        self.player_hp = min(PLAYER_MAX_HP, self.player_hp + GRUB_HEAL)
        if secs:
            self.grub_until[kind] = self.frame + secs * FPS
        self.add_callout(label, hud_col, ttl=FPS, scale=1)
        self.add_pop(world_pos, f"+{int(GRUB_HEAL)}HP", hud_col)
        self.play_sound('pickup', vol=0.7)
        self.kick(1.0)
        self.spawn_burst(world_pos, 6, ('spark',), 1.4)

    def update_grub(self):
        """Walk-over pickups on a respawn timer, same shape as the pistols."""
        pr = self.active_rect()
        for g in self.grub_pickups:
            if g['taken']:
                if self.frame - g['taken'] >= GRUB_RESPAWN:
                    g['taken'] = 0
                    # come back somewhere else, as a different thing to eat
                    g['x'], g['y'] = random_open_spawn()
                    g['kind'] = random.choice(list(GRUB_KINDS))
                continue
            if math.hypot(pr.centerx - g['x'], pr.centery - g['y']) < GRUB_RADIUS:
                g['taken'] = self.frame
                self.eat_grub(g['kind'], (g['x'], g['y']))

    def apply_grub_to_car(self):
        """Push the active food effects into the car you are driving.

        Gooey butter lifts the ceiling; a tallboy makes the wheel wander, so
        the score bonus it carries is paid for in a car that will not hold a
        line. Both are restored the moment the clock runs out because the
        baseline is re-read from the variant tuning every step.
        """
        car = self.driving
        if car is None:
            return
        puncture = SPIKE_SPEED_SCALE if car.puncture_steps > 0 else 1.0
        heavy = (0.86 if self.job is not None
                 and self.job.collected and self.job.kind == 'heavy' else 1.0)
        car.max_speed = (car.base_max_speed * self.grub_speed_scale()
                         * puncture * heavy)
        if self.grub_active('tallboy') and abs(car.velocity) > 1.0:
            # a slow wander, not a twitch: sine on the frame counter
            car.input_steer = max(-1.0, min(1.0, car.input_steer
                                            + math.sin(self.frame * 0.06) * 0.34))

    def grub_speed_scale(self):
        """Gooey butter: a sugar rush you can feel in the legs and the pedal."""
        return GRUB_SPEED_BONUS if self.grub_active('gooey_butter') else 1.0

    def grub_ram_scale(self):
        """A Ted Drewes concrete is so thick they hand it to you upside down
        to prove it will not fall out. Neither will you."""
        return GRUB_RAM_BONUS if self.grub_active('concrete') else 1.0

    def grub_self_ram(self):
        """The other half of the concrete: it costs your own paintwork less."""
        return 0.5 if self.grub_active('concrete') else 1.0

    # ---------------- population streaming ----------------
    def travel_heading(self):
        """Direction of travel in radians, or None when barely moving. Used to
        aim the respawn ring at the road ahead instead of the one behind."""
        if self.driving is not None:
            if abs(self.driving.velocity) < POP_AHEAD_SPEED:
                return None
            return self.driving.angle if self.driving.velocity > 0 else \
                self.driving.angle + math.pi
        dx, dy = self.player_dir[0], self.player_dir[1]
        if math.hypot(dx, dy) * PLAYER_SPEED < POP_AHEAD_SPEED:
            return None
        return math.atan2(dy, dx)

    #: how much clear space a respawning vehicle wants around it, in px. A car
    #: is 34x18; 40 keeps a bumper's worth between two of them.
    SPAWN_CLEARANCE = 40

    def spot_is_free(self, x, y, skip=None, pad=None):
        """True if no other vehicle is already sitting there.

        Nothing used to ask. Kerb bays came off a shuffled queue that was
        rebuilt from scratch every time it emptied, so the same bay was handed
        to a second car a few seconds later; moving cars respawned on a tile
        centre with no occupancy test at all. Either way you got two cars in
        one place, which reads as a spawn bug because it is one.
        """
        pad = self.SPAWN_CLEARANCE if pad is None else pad
        box = pygame.Rect(0, 0, pad, pad)
        box.center = (int(x), int(y))
        for other in self.cars:
            if other is not skip and other.rect.colliderect(box):
                return False
        for unit in getattr(self, 'police', ()):
            if unit is not skip and unit.rect.colliderect(box):
                return False
        if self.driving is None and self.player_rect.colliderect(box):
            return False
        return True

    def free_spawn_spot(self, tries=6, skip=None, grid_traffic=False, **kwargs):
        """Retry a ring spawn until it does not overlap an existing vehicle."""
        for _ in range(tries):
            spot = ring_spawn_near(**kwargs)
            if spot is None:
                return None
            if grid_traffic:
                col, row = int(spot[0]) // TILE_SIZE, int(spot[1]) // TILE_SIZE
                if not traffic__is_grid_road(col, row):
                    continue
            if self.spot_is_free(*spot, skip=skip):
                return spot
        return None

    def route_70_spawn(self, near_y, skip=None):
        """Nearest free Grand Boulevard tile for the permanent Route 70 bus."""
        rows = sorted(range(2, MAP_TILES_H - 2),
                      key=lambda row: abs((row * TILE_SIZE + TILE_SIZE // 2) - near_y))
        for row in rows:
            if not traffic__is_grid_road(ROUTE_70_COL, row):
                continue
            spot = (ROUTE_70_COL * TILE_SIZE + TILE_SIZE // 2,
                    row * TILE_SIZE + TILE_SIZE // 2)
            if self.spot_is_free(*spot, skip=skip):
                return spot
        return None

    def fallback_traffic_spawn(self, skip=None):
        """Find a guaranteed free cardinal-road centre without random retries."""
        candidates = []
        for row in range(2, MAP_TILES_H - 2):
            for col in range(2, MAP_TILES_W - 2):
                if traffic__is_grid_road(col, row):
                    candidates.append((col * TILE_SIZE + TILE_SIZE // 2,
                                       row * TILE_SIZE + TILE_SIZE // 2))
        if not candidates:
            return None
        start = random.randrange(len(candidates))
        for index in range(len(candidates)):
            spot = candidates[(start + index) % len(candidates)]
            if self.spot_is_free(*spot, skip=skip):
                return spot
        return None

    def _kerb_spot(self, skip=None):
        """A kerbside parking bay in the ring just outside the view."""
        for _ in range(2):
            if not self._kerb_queue:
                ax, ay = self.active_rect().center
                try:
                    spots = parking_parking_spots(max_count=16, near=(ax, ay),
                                                  radius=POP_RESPAWN_MAX)
                except (TypeError, ValueError):
                    spots = ()
                self._kerb_queue = [
                    spot for spot in spots
                    if math.hypot(spot[0] - ax, spot[1] - ay) >= POP_RESPAWN_MIN
                ]
                random.shuffle(self._kerb_queue)
            while self._kerb_queue:
                spot = self._kerb_queue.pop()
                if self.spot_is_free(spot[0], spot[1], skip=skip):
                    return spot
        return None

    def update_population(self):
        """Recycle anything that has wandered far away back to just off-screen.

        The viewport is 0.56% of the map, so a population spread over the whole
        city is a population you never see - 40 pedestrians measured 0.0 visible
        on average. Keeping the same modest pool but always near the player is
        what makes the streets look inhabited, and it costs nothing extra: the
        entities were being simulated either way.
        """
        ax, ay = self.active_rect().center
        limit = POP_KEEP_RADIUS * POP_KEEP_RADIUS
        moved = 0
        heading = self.travel_heading()

        for ped in self.pedestrians:
            if moved >= POP_RECYCLE_PER_STEP:
                break
            invalid_ground = not pedestrian_ground_is_clear(ped.rect)
            if (self.city_event_announced and getattr(ped, 'event_actor', False)
                    and not invalid_ground):
                continue
            if ped.down_timer > 0 and not invalid_ground:
                # Do not vanish a body mid-fall unless it is already somewhere
                # impossible, such as a roof tile exposed by bad placement.
                continue
            dx, dy = ped.rect.centerx - ax, ped.rect.centery - ay
            if dx * dx + dy * dy <= limit and not invalid_ground:
                continue
            candidate = ring_spawn_near(ax, ay, heading=heading)
            spot = (pedestrian_point_near(*candidate, max_rings=3)
                    if candidate is not None else None)
            if spot is None and invalid_ground:
                # A corrupt live placement is repaired even if the preferred
                # off-screen ring happened not to find a candidate this step.
                spot = random_pedestrian_point()
            if spot is None:
                continue
            ped.rect.center = spot
            ped.set_kind(self._ped_kind_for(*spot))
            ped.mood = 'calm'
            ped.mood_timer = 0
            ped.down_timer = 0
            ped.bump_cooldown = 0
            ped.knock.update(0, 0)
            if ped.follower:
                ped.follower.x, ped.follower.y = float(spot[0]), float(spot[1])
                ped.follower.placed = True
            moved += 1

        for car in self.cars:
            if moved >= POP_RECYCLE_PER_STEP * 2:
                break
            if (car is self.driving or car is self.side_target_car
                    or car.driver is not None or car.burn > 0):
                continue
            if car.parked and (car.variant in SHOWCASE_VARIANTS
                               or car is self.chain_bike):
                continue
            dx, dy = car.rect.centerx - ax, car.rect.centery - ay
            d2 = (dy * dy if car.variant == 'metrobus_70'
                  else dx * dx + dy * dy)
            # A deadlocked knot of traffic well off-screen is worth breaking up
            # even though it has not drifted out of range. car.stall is counted
            # in the traffic loop in update(), which visits every car.
            jammed = (car.stall > POP_STALL_STEPS
                      and d2 > POP_OFFSCREEN * POP_OFFSCREEN)
            if d2 <= limit and not jammed:
                continue
            car.stall = 0
            if car.parked:
                bay = self._kerb_spot(skip=car)
                if bay is None:
                    continue
                car.rect.center = (int(bay[0]), int(bay[1]))
                car.angle = bay[2]
                car.velocity = 0.0
            else:
                spot = (self.route_70_spawn(ay, skip=car)
                        if car.variant == 'metrobus_70' else
                        self.free_spawn_spot(skip=car, ax=ax, ay=ay,
                                             road_only=True, heading=heading,
                                             grid_traffic=True))
                if spot is None:
                    spot = self.fallback_traffic_spawn(skip=car)
                if spot is None:
                    continue
                car.rect.center = spot
                car.velocity = 0.0
                traffic_init_car(car)
                traffic_snap_to_lane(car)
            car.hp = car.max_hp
            moved += 1

    # ---------------- wrecks + explosions ----------------
    def roadblock_units(self):
        """Return the deployed cruisers that are not in the chase-car pool."""
        return [unit for block in self.roadblocks for unit in block['cars']]

    def combat_vehicle_pool(self):
        """All non-player vehicles that can be struck or destroyed."""
        return list(self.cars) + list(self.police) + self.roadblock_units()

    def update_wrecks(self):
        """Tick every burning car's fuse; detonate the ones that reach zero."""
        pool = self.combat_vehicle_pool()
        if self.driving is not None and self.driving not in pool:
            pool.append(self.driving)
        going = []
        for car in pool:
            if car.burn > 0:
                car.burn -= 1
                if car.burn % 3 == 0:
                    self.spawn_burst(car.rect.center, 1, ('smoke',), 0.7)
                if car.burn == 0:
                    going.append(car)
        for car in going:
            self.explode(car)

    def explode(self, car):
        pos = car.rect.center
        if car is self.side_target_car:
            self.side_mission_event('vehicle_destroyed', vehicle_id=id(car))
        self.spawn_burst(pos, 28, ('spark', 'spark', 'smoke', 'debris'), 4.6)
        self.add_decal(pos, 'scorch', 1.5)
        # Duck the ambient bed under it; that is most of why an explosion
        # feels enormous rather than just loud.
        self.play_sound('boom', pos, vol=1.0, gap=4, reach=900.0)
        snd_duck(30)
        self.kick(7.5, freeze=2, flash=5)
        self.add_score(60, pos, mult=True)
        for ped in self.pedestrians:
            dx, dy = ped.rect.centerx - pos[0], ped.rect.centery - pos[1]
            if dx * dx + dy * dy < 62 * 62 and ped.down_timer <= 0:
                ped.mood = 'down'
                ped.down_timer = random.randint(50, 90)
                n = math.hypot(dx, dy) or 1.0
                ped.knock = pygame.Vector2(dx / n, dy / n) * 5.0
        for cop in list(self.foot_police):
            dx, dy = cop.rect.centerx - pos[0], cop.rect.centery - pos[1]
            if dx * dx + dy * dy < 72 * 72:
                n = math.hypot(dx, dy) or 1.0
                impulse = pygame.Vector2(dx / n, dy / n) * 8.0
                self.damage_foot_cop(cop, 90.0, impulse,
                                     cause='explosion', lethal=True)
        for other in self.combat_vehicle_pool():
            if other is car:
                continue
            dx, dy = other.rect.centerx - pos[0], other.rect.centery - pos[1]
            if dx * dx + dy * dy < 72 * 72:
                other.damage(46)                 # may light its own fuse -> chain
                other.velocity += 2.0
        roadblock = next((block for block in self.roadblocks
                          if car in block['cars']), None)
        is_player = car is self.driving
        is_police = car in self.police or roadblock is not None
        self.frenzy_hit('cop' if is_police else 'car')
        if is_police:
            if car in self.police:
                self.police.remove(car)          # update_police re-tops this step
            else:
                # Taking out either parked cruiser opens the whole closure;
                # the replacement comes later instead of materialising in the blast.
                self.roadblocks.remove(roadblock)
                self.roadblock_deploy_after = max(
                    self.roadblock_deploy_after,
                    self.frame + ROADBLOCK_REDEPLOY_BY_STAR[self.wanted_level])
        elif car in self.cars:
            fixed_variant = (car.variant if car.variant in SHOWCASE_VARIANTS
                             else 'vespa' if car is self.chain_bike else None)
            self.cars.remove(car)
            if fixed_variant is not None:
                if fixed_variant == 'vespa':
                    target = self.chain_bike_home
                else:
                    venue = LOCAL_LEGENDS[fixed_variant]['venue']
                    entry = next(item for item in LANDMARKS if item[5] == venue)
                    target = landmark_dropoff_point(entry)
                tune = VEHICLE_TUNING[fixed_variant]
                spot = free_point_near(*target, tune['w'], tune['h'], max_rings=8)
                if spot is None:
                    spot = target
                fresh = Car(*spot, variant=fixed_variant)
                fresh.angle = 0.0
                fresh.parked = True
                fresh.velocity = 0.0
                if fixed_variant == 'vespa':
                    self.chain_bike = fresh
            else:
                cx, cy = random_open_spawn(road_only=True)
                fresh = Car(cx, cy)
                traffic_init_car(fresh)
                traffic_snap_to_lane(fresh)
            self.cars.append(fresh)
        if is_player:
            self.wasted()

    def wasted(self, note="WRECK TOTALLED"):
        """Killed. Hold the card, then wake up under the Arch.

        This used to hand control straight back after moving you a few tiles
        sideways, so the screen said WASTED over a game you were still
        playing. Death now owns the next three seconds.
        """
        if self.state == STATE_DEAD:
            return
        if self.arch_job_phase in ARCH_ACTIVE_PHASES:
            self.fail_arch_job("The Arch job is back on the table")
        self.wasted_flash = FPS * 2
        if self.driving is not None:
            self.driving.driver = None
            self.driving = None                  # it is a wreck; do not hand it back
        if self.job is not None and self.job.collected:
            self.fail_job("Wreck - cargo lost")
        self.enter_death('wasted', note)

    def enter_death(self, kind, note):
        """Shared ritual for both ways of losing. Freeze, show, respawn.

        Everything that has to be true the instant you die is done here, so
        the police-count invariant and the multiplier can never be observed
        half-torn-down: the sim keeps running during the hold, it just runs
        with the player parked and the wanted level already at zero.
        """
        self.side_mission_event(
            'player_busted' if kind == 'busted' else 'player_wasted')
        self.local_challenge = None
        self.play_sound('bad', vol=0.9)
        snd_duck(FPS)
        self.state = STATE_DEAD
        self.death_kind = kind
        self.death_note = note
        self.death_timer = DEATH_HOLD_STEPS
        # Getting killed scatters everything you were carrying across the
        # pavement; getting arrested does not, because they hand your effects
        # back at the desk minus the bail. That is the whole difference
        # between the two deaths, and it makes surrendering to a chase a real
        # decision when you are holding a big roll.
        lost = 0
        if kind == 'wasted':
            lost = int(self.cash)
            if lost >= BANK_MIN:
                self.drop_cash(lost, self.active_rect().center)
                self.cash -= lost
        self.death_stats = {
            'score': self.score,
            'cash': self.banked,
            'dropped': lost,
            'jobs': self.jobs_done,
            'streak': self.streak,
            'peak_star': self.peak_star,
            'chase': self.longest_chase,
        }
        self.reset_multiplier()
        self.wanted_level = 0
        self.police = []
        self.roadblocks = []       # deterministic high-heat containment points
        self.speech_bubbles = []
        self.roadblock_serial = 0
        self.roadblock_deploy_after = 0
        self.foot_police = []
        self.foot_cop_respawn = 0
        self.bust_meter = 0
        self.heat_timer = 0
        self.wanted_decay_timer = 0
        self.cop_dispatch = 0
        here = self.active_rect().center
        self.pursuit_agency = police_jurisdiction_at(
            here[0] // TILE_SIZE, here[1] // TILE_SIZE)
        self.pending_pursuit_agency = self.pursuit_agency
        self.jurisdiction_timer = 0
        self.crime_pos = None
        self.spotted = False
        self.was_spotted = False
        self.searching = False
        self.hidden = False
        self.hide_timer = 0
        self.player_dir = [0, 0]
        self.sprinting = False
        self.sprint_active = False
        self.attack_held = False
        self.combo = 0
        self.combo_timer = 0
        self.throwable_system = throwable_logic.ThrowableSystem({
            kind: self.weapon_ammo.get(kind, 0)
            for kind in throwable_logic.THROWABLE_ORDER
        })

    def finish_death(self):
        """The card is done: put the player back on the map and hand over.

        Both ways of dying land under the Arch. One respawn anchor teaches the
        map - you learn the riverfront because you keep waking up on it - and
        the difference between the two deaths lives in the card and in what
        each one takes off you, not in where you come to.
        """
        spot = self.arch_respawn_point()
        self.player_rect.center = spot if spot is not None else random_open_spawn()
        self.player_fx = float(self.player_rect.centerx)
        self.player_fy = float(self.player_rect.centery)
        self.player_hp = PLAYER_MAX_HP
        self.player_stamina = PLAYER_STAMINA_MAX
        self.sprint_ready = True
        # You come to on the lawn next to live Memorial Drive traffic, so the
        # i-frames here are longer than an ordinary hit's.
        self.hurt_cd = RESPAWN_IMMUNE_STEPS
        self.player_dir = [0, 0]
        self.player_motion.update(0, 0)
        self.peak_star = 0
        self.chase_steps = 0
        self.longest_chase = 0
        self.grub_until = {}
        self.camera.snap_to(self.player_rect)
        self.state = STATE_PLAYING
        self.death_kind = None
        self.death_timer = 0
        if self.arch_job_unlocked and not self.arch_job_completed:
            # Both deaths respawn under the Arch; without a fresh arm delay the
            # failed finale would restart before the player took one step.
            self.arch_job_offer_after = self.frame + FPS * 2
        if (self.job is None and self.job_cooldown <= 0 and
                (not self.arch_job_unlocked or self.arch_job_completed)):
            self.job = self.deal_job()

    def lay_skid_marks(self):
        """Two dark stripes under the back wheels whenever the car is sliding.

        The decal system and the tyre-grime road art were already here; this
        is what makes the city *record* your driving, which is exactly the
        reward a handbrake needs in order to be worth pressing.
        """
        car = self.driving
        if car is None or car.slip < SKID_MIN_SLIP:
            return
        if self.frame % 2:
            return
        back = -math.cos(car.angle) * 11, -math.sin(car.angle) * 11
        side = -math.sin(car.angle) * 6, math.cos(car.angle) * 6
        for sgn in (-1, 1):
            self.add_decal((car.rect.centerx + back[0] + side[0] * sgn,
                            car.rect.centery + back[1] + side[1] * sgn),
                           'skid', 0.34)

    def update_body_shop(self):
        """Drive in hot, come out a different colour, $300 lighter.

        Only from a car, because the joke is a respray - and only with a
        wanted level, so it is a decision you make under pressure rather than
        a button you press for nothing.
        """
        if self.shop_cooldown > 0:
            self.shop_cooldown -= 1
            return
        if self.driving is None or self.wanted_level <= 0:
            return
        if self.arch_job_phase in (ARCH_ESCAPE, ARCH_LAY_LOW):
            if self.frame % (FPS * 2) == 0:
                self.add_toast("No respray with part of the Arch in the car")
            return
        here = self.driving.rect.center
        for (sx, sy) in self.body_shops:
            if math.hypot(here[0] - sx, here[1] - sy) > BODY_SHOP_RADIUS:
                continue
            if self.cash + self.banked < BODY_SHOP_COST:
                if self.frame % (FPS * 2) == 0:
                    self.add_toast(f"Respray is ${BODY_SHOP_COST}. Come back.")
                return
            paid = min(self.cash, BODY_SHOP_COST)
            self.cash -= paid
            self.banked -= (BODY_SHOP_COST - paid)
            self.shop_cooldown = FPS * 6
            self.wanted_level = 0
            self.police = []
            self.foot_police = []
            self.roadblocks = []
            self.roadblock_deploy_after = self.frame
            self.bust_meter = 0
            self.heat_timer = 0
            self.wanted_decay_timer = 0
            self.crime_pos = None
            self.driving.color = cars_random_body_color()
            self.driving.hp = self.driving.max_hp
            self.driving.puncture_steps = 0
            self.driving.spike_cd = 0
            self.add_callout("RESPRAYED", hud_HUD_GREEN, scale=2)
            self.add_pop(here, f"-${BODY_SHOP_COST}", hud_HUD_RED)
            self.play_sound('cash', vol=0.7)
            return

    def check_potholes(self):
        """City of St. Louis."""
        car = self.driving
        if car is None or abs(car.velocity) < 3.0:
            return
        for hole in self.potholes:
            if self.frame - hole['hit'] < FPS:
                continue
            if math.hypot(car.rect.centerx - hole['x'],
                          car.rect.centery - hole['y']) > POTHOLE_RADIUS:
                continue
            hole['hit'] = self.frame
            if car.variant == 'mudfoot':
                car.velocity *= 0.98
                self.kick(1.0)
                self.add_callout("BIG TIRES", hud_HUD_GOLD,
                                 ttl=FPS, scale=1, tag='pothole')
                return
            car.damage(POTHOLE_DAMAGE)
            car.velocity *= 0.88
            self.kick(3.2)
            self.spawn_burst(car.rect.center, 4, ('debris',), 1.6)
            self.play_impact(car.rect.center, 4.5, gap=20)
            self.add_callout("CITY OF ST LOUIS", hud_HUD_GREY_DIM,
                             ttl=FPS, scale=1, tag='pothole')
            return

    def check_roadkill_risk(self):
        """On foot, a car doing real speed that hits you can put you down.

        The old version applied the full hit *every step* the car overlapped
        you, so a cruiser resting against you dealt ~44 HP a frame and killed
        you in three - that is the "instantly dead on foot" bug. One contact
        is now one hit: you take it, you get thrown clear, and you are briefly
        untouchable while you get up.
        """
        if self.hurt_cd > 0:
            self.hurt_cd -= 1
            return
        pr = self.player_rect
        for car in list(self.cars) + list(self.police):
            speed = abs(car.velocity)
            # The same threshold that decides whether a car kills a pedestrian
            # decides whether one hurts you: on foot you are a pedestrian, and
            # the rule reading both ways is what makes it learnable. (It used
            # to be a bare 4.0, tuned against a top speed the game no longer
            # has.)
            if speed < SPLAT_SPEED or not car.rect.colliderect(pr.inflate(2, 2)):
                continue
            # Capped, so even a ten-star cruiser cannot take a third of the
            # bar off you in a single touch.
            damage = min(ROADKILL_MAX, speed * ROADKILL_DAMAGE)
            if self.grub_active('pork_steak'):
                damage *= GRUB_ARMOUR       # a pork steak is structural
            if self.grub_active('concrete'):
                damage *= 0.65              # and a concrete does not tip over
            self.player_hp -= damage
            self.hurt_cd = HURT_IMMUNE_STEPS
            kb = pygame.Vector2(pr.centerx - car.rect.centerx,
                                pr.centery - car.rect.centery)
            if kb.length() == 0:
                kb = pygame.Vector2(math.cos(car.angle), math.sin(car.angle))
            # Thrown clear of the wheels, harder the faster you were hit -
            # a flat 6px shove left you still under the car next step.
            kb = kb.normalize() * (6 + speed * 1.4)
            # Shove along the contact normal, giving up a step at a time, so a
            # player pinned against a wall still ends up somewhere standable.
            for frac in (1.0, 0.66, 0.33):
                mv = pr.move(int(kb.x * frac), int(kb.y * frac))
                if not is_blocked(mv):
                    self.player_rect.topleft = mv.topleft
                    self.player_fx = float(self.player_rect.centerx)
                    self.player_fy = float(self.player_rect.centery)
                    break
            self.kick(2.4)
            self.spawn_burst(pr.center, 5, ('debris',), 2.2)
            if self.player_hp <= 0:
                self.player_hp = 0.0
                self.wasted("RUN DOWN ON THE STREET")
            return

    # ---------------- kill frenzy ----------------
    def spawn_frenzy_icon(self):
        """Drop a frenzy pickup on a road tile within reach but off-screen."""
        active = self.active_rect()
        for _ in range(50):
            ang = random.uniform(0, math.tau)
            dist = random.uniform(360, 900)
            x = active.centerx + math.cos(ang) * dist
            y = active.centery + math.sin(ang) * dist
            col, row = int(x) // TILE_SIZE, int(y) // TILE_SIZE
            if not (2 <= col < MAP_TILES_W - 2 and 2 <= row < MAP_TILES_H - 2):
                continue
            if tile_type_at(col, row) != TILE_ROAD:
                continue
            spot = free_point_near(col * TILE_SIZE + TILE_SIZE // 2,
                                   row * TILE_SIZE + TILE_SIZE // 2,
                                   PLAYER_SIZE, PLAYER_SIZE, max_rings=1)
            if spot is not None:
                kinds = ('ped', 'car', 'cop')
                kind = kinds[(self.frame // 7) % len(kinds)]
                self.frenzy_icon = (spot[0], spot[1], kind)
                return

    def update_frenzy(self):
        if self.frenzy is not None:
            self.frenzy.steps_left -= 1
            if self.frenzy.steps_left <= 0:
                self.add_callout("FRENZY OVER", hud_HUD_GREY_DIM)
                self.frenzy = None
                self.frenzy_cooldown = FRENZY_COOLDOWN
            return
        if self.frenzy_icon is None:
            if self.frenzy_cooldown > 0:
                self.frenzy_cooldown -= 1
            else:
                self.spawn_frenzy_icon()
            return
        ix, iy, kind = self.frenzy_icon
        a = self.active_rect()
        if math.hypot(a.centerx - ix, a.centery - iy) <= JOB_MARKER_RADIUS:
            self.frenzy = Frenzy(kind)
            self.frenzy_icon = None
            self.add_callout("KILL FRENZY!", hud_HUD_RED, ttl=int(FPS * 2.5), scale=3)
            self.add_callout(self.frenzy.banner, hud_HUD_GOLD, ttl=int(FPS * 2.5), scale=1)
            self.bump_multiplier(1)

    def frenzy_hit(self, kind):
        f = self.frenzy
        if f is None or f.kind != kind or f.remaining <= 0:
            return
        f.remaining -= 1
        self.add_score(40, mult=True)
        if f.remaining <= 0:
            self.add_score(f.bonus, self.active_rect().center, mult=False)
            self.add_callout(f"FRENZY DONE +{f.bonus}", hud_HUD_GREEN, scale=2)
            self.bump_multiplier(2)
            self.frenzy = None
            self.frenzy_cooldown = FRENZY_COOLDOWN
        else:
            self.add_callout(f"{f.remaining} LEFT", hud_HUD_GOLD, ttl=FPS, scale=2)

    #: which body a neighbourhood is likely to put on the street, and how
    #: often. Used to be one 5% hoosier roll in a single giant 'south' region;
    #: every district now has somebody who reads as being from there.
    HOOD_PED_BIAS = {
        'sthills': (('hoosier', 0.16),),
        'southampton': (('hoosier', 0.14),),
        'bevo': (('hoosier', 0.12),),
        'carondelet': (('hoosier', 0.12),),
        'towergrove': (('hoosier', 0.06),),
        'cherokee': (('hoosier', 0.05),),
        'dogtown': (('hoosier', 0.10),),
        'hill': (('hoosier', 0.05),),
        'loop': (('busker_sax', 0.18),),
        'grand': (('busker_sax', 0.18),),
        'grove': (('busker_sax', 0.08),),
        'downtown': (('cards_fan', 0.10),),
        'riverfront': (('cards_fan', 0.08),),
        'soulard': (('cards_fan', 0.06),),
    }

    @staticmethod
    def _ped_kind_for(x, y):
        """Bias pedestrians to their turf: ballplayers by the stadium, street
        musicians in the arts districts, south siders on the south side."""
        col, row = x // TILE_SIZE, y // TILE_SIZE
        for (lx, ly, lw, lh, _kind, name, _c) in LANDMARKS:
            if lx - 3 <= col <= lx + lw + 3 and ly - 3 <= row <= ly + lh + 3:
                if name == "Busch Stadium" and random.random() < 0.78:
                    return f"cards_fan#{random.randrange(peds__VARIANTS)}"
                if name in ("Grand Center Arts District", "Delmar Loop") and random.random() < 0.4:
                    return f"busker_sax#{random.randrange(peds__VARIANTS)}"
        for kind, chance in Game.HOOD_PED_BIAS.get(hood_at(col, row), ()):
            if random.random() < chance:
                return f"{kind}#{random.randrange(peds__VARIANTS)}"
        return None

    # ---------------- gamepad ----------------
    def open_gamepad(self):
        """Bind the first connected pad, if there is one. Safe to call again
        on hot-plug; a machine with no pad just keeps self.pad as None."""
        if not pygame.joystick.get_init():
            return
        try:
            if pygame.joystick.get_count() == 0:
                self.pad = None
                return
            if self.pad is not None:
                return
            pad = pygame.joystick.Joystick(0)
            pad.init()
        except pygame.error:
            self.pad = None
            return
        self.pad = pad
        self._pad_trig_rest.clear()
        try:
            self.add_toast(f"Pad: {pad.get_name()[:20]}")
        except pygame.error:
            pass

    def drop_gamepad(self):
        self.pad = None
        self._pad_trig_rest.clear()

    def pad_axis(self, idx, dead=PAD_DEADZONE):
        """Deadzoned stick axis, 0.0 when there is no pad or no such axis."""
        if self.pad is None:
            return 0.0
        try:
            if idx >= self.pad.get_numaxes():
                return 0.0
            v = self.pad.get_axis(idx)
        except pygame.error:
            self.drop_gamepad()
            return 0.0
        return 0.0 if abs(v) < dead else max(-1.0, min(1.0, v))

    def pad_trigger(self, idx):
        """Analogue trigger as 0..1.

        SDL2 usually reports triggers as -1 at rest through +1 fully pressed,
        but some drivers report a plain 0..1. Rather than guess, remember the
        lowest value this axis has ever produced: a pad using the signed
        convention shows about -1 the moment the trigger is released, which is
        its resting state, so the calibration lands on the first frame.
        """
        if self.pad is None:
            return 0.0
        try:
            if idx >= self.pad.get_numaxes():
                return 0.0
            v = self.pad.get_axis(idx)
        except pygame.error:
            self.drop_gamepad()
            return 0.0
        rest = self._pad_trig_rest.get(idx, 0.0)
        if v < rest:
            rest = v
            self._pad_trig_rest[idx] = v
        if rest <= -0.5:
            v = (v + 1.0) * 0.5
        return 0.0 if v < PAD_TRIGGER_DEADZONE else min(1.0, v)

    def pad_button(self, idx):
        if self.pad is None:
            return False
        try:
            return idx < self.pad.get_numbuttons() and bool(self.pad.get_button(idx))
        except pygame.error:
            self.drop_gamepad()
            return False

    def pad_hat(self):
        """D-pad as (x, y) with y already flipped to screen coordinates."""
        if self.pad is None:
            return (0, 0)
        try:
            if self.pad.get_numhats() == 0:
                return (0, 0)
            hx, hy = self.pad.get_hat(0)
        except pygame.error:
            self.drop_gamepad()
            return (0, 0)
        return (hx, -hy)

    def handle_pad_button(self, button):
        if (button == PAD_Y and self.state == STATE_PLAYING
                and not self.show_map and self.driving is not None):
            self.cycle_radio()
            return
        if self.state in (STATE_TITLE, STATE_CHARACTER):
            if button == PAD_A:
                self.handle_keydown(pygame.K_RETURN)
            elif button == PAD_B:
                self.handle_keydown(pygame.K_ESCAPE)
            elif self.state == STATE_CHARACTER and self.school_open and button == PAD_LB:
                self.handle_keydown(pygame.K_PAGEUP)
            elif self.state == STATE_CHARACTER and self.school_open and button == PAD_RB:
                self.handle_keydown(pygame.K_PAGEDOWN)
            return
        key = PAD_BUTTON_KEYS.get(button)
        if key is not None:
            self.handle_keydown(key)

    def handle_pad_hat(self, value):
        """Turn a D-pad edge into the same one-shot menu movement as arrows."""
        if self.state not in (STATE_TITLE, STATE_CHARACTER):
            return
        hx, hy = value
        if hy > 0:
            self.handle_keydown(pygame.K_UP)
        elif hy < 0:
            self.handle_keydown(pygame.K_DOWN)
        elif hx < 0:
            self.handle_keydown(pygame.K_LEFT)
        elif hx > 0:
            self.handle_keydown(pygame.K_RIGHT)

    def pad_handbrake(self):
        """LB is the handbrake. It sits under the left index finger, which is
        where every driving game in the last thirty years has put it."""
        if self.pad is None:
            return False
        try:
            return bool(self.pad.get_button(PAD_LB))
        except pygame.error:
            return False

    def apply_pad_driving(self, throttle, steer):
        """Right trigger accelerates, left brakes/reverses, left stick steers.
        A / B stand in on a pad whose triggers are digital."""
        rt, lt = self.pad_trigger(PAD_AX_RT), self.pad_trigger(PAD_AX_LT)
        if rt or lt:
            throttle = rt - lt
        elif self.pad_button(PAD_A):
            throttle = 1.0
        elif self.pad_button(PAD_B):
            throttle = -1.0
        ax = self.pad_axis(PAD_AX_LX)
        if ax:
            steer = ax
        hx, _hy = self.pad_hat()
        if hx:
            steer = float(hx)
        return throttle, steer

    def apply_pad_walking(self, dx, dy):
        """Analogue walking: a half-deflected stick is a half-speed walk. The
        right stick aims, so you can shoot one way while backing off another."""
        ax, ay = self.pad_axis(PAD_AX_LX), self.pad_axis(PAD_AX_LY)
        if ax or ay:
            mag = math.hypot(ax, ay)
            if mag > 1.0:
                ax, ay = ax / mag, ay / mag
            dx, dy = ax, ay
        else:
            hx, hy = self.pad_hat()
            if hx or hy:
                if hx and hy:
                    hx, hy = hx * 0.707, hy * 0.707
                dx, dy = float(hx), float(hy)
        rx, ry = self.pad_axis(PAD_AX_RX), self.pad_axis(PAD_AX_RY)
        if rx or ry:
            self.player_aim = math.atan2(ry, rx)
        return dx, dy

    # ---------------- title / character input ----------------
    def title_options(self):
        options = ["NEW GAME"]
        if self.loadable_save_exists():
            options.insert(0, "CONTINUE")
        options.append("QUIT")
        return tuple(options)

    @staticmethod
    def _school_norm(text):
        return ''.join(ch for ch in str(text).upper() if ch.isalnum())

    def school_matches(self, query=None):
        """Searchable combobox rows. Common local abbreviations are indexed too,
        because nobody in St. Louis types the formal expansion of SLUH."""
        query = self.school_query if query is None else query
        needle = self._school_norm(query)
        tokens = [self._school_norm(part) for part in str(query).split() if part]
        rows = HS_SPECIAL_CHOICES + STL_HIGH_SCHOOLS
        if not needle:
            return list(rows)
        out = []
        for row in rows:
            name = row[0]
            aliases = ' '.join(alias for alias, target in HS_SEARCH_ALIASES.items()
                               if target == name)
            haystack = self._school_norm(name + aliases)
            if needle in haystack or (tokens and all(token in haystack for token in tokens)):
                out.append(row)
        return out

    def handle_title_key(self, key):
        options = self.title_options()
        if key in (pygame.K_UP, pygame.K_w):
            self.title_index = (self.title_index - 1) % len(options)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.title_index = (self.title_index + 1) % len(options)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_e):
            choice = options[self.title_index]
            if choice == "CONTINUE":
                if self.load_game():
                    self.state = STATE_PLAYING
            elif choice == "NEW GAME":
                self.state = STATE_CHARACTER
                self.setup_row = 0
                self.school_open = False
                self.school_query = ""
            else:
                self.running = False

    def _open_school_picker(self):
        self.school_open = True
        self.school_query = ""
        rows = self.school_matches("")
        self.school_cursor = next((i for i, row in enumerate(rows)
                                   if row[0] == self.character_school), 0)

    def handle_character_key(self, key, text=""):
        if self.school_open:
            rows = self.school_matches()
            if key == pygame.K_ESCAPE:
                self.school_open = False
                self.school_query = ""
            elif key == pygame.K_UP:
                self.school_cursor = max(0, self.school_cursor - 1)
            elif key == pygame.K_DOWN:
                self.school_cursor = min(max(0, len(rows) - 1), self.school_cursor + 1)
            elif key == pygame.K_PAGEUP:
                self.school_cursor = max(0, self.school_cursor - 9)
            elif key == pygame.K_PAGEDOWN:
                self.school_cursor = min(max(0, len(rows) - 1), self.school_cursor + 9)
            elif key == pygame.K_HOME:
                self.school_cursor = 0
            elif key == pygame.K_END:
                self.school_cursor = max(0, len(rows) - 1)
            elif key == pygame.K_BACKSPACE:
                self.school_query = self.school_query[:-1]
                self.school_cursor = 0
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if rows:
                    self.character_school = rows[self.school_cursor][0]
                    self.school_open = False
                    self.school_query = ""
            elif text and text.isprintable() and len(self.school_query) < 28:
                # Search accepts letters, digits, spaces, dots, apostrophes and
                # hyphens; everything is normalized before matching.
                if text.isalnum() or text in " .'-":
                    self.school_query += text.upper()
                    self.school_cursor = 0
            return

        if key == pygame.K_ESCAPE:
            self.state = STATE_TITLE
            return
        if key in (pygame.K_UP, pygame.K_w):
            self.setup_row = (self.setup_row - 1) % 3
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.setup_row = (self.setup_row + 1) % 3
        elif key in (pygame.K_LEFT, pygame.K_a):
            if self.setup_row == 0:
                self.character_look = (self.character_look - 1) % len(CHARACTER_LOOKS)
            elif self.setup_row == 1:
                self._open_school_picker()
        elif key in (pygame.K_RIGHT, pygame.K_d):
            if self.setup_row == 0:
                self.character_look = (self.character_look + 1) % len(CHARACTER_LOOKS)
            elif self.setup_row == 1:
                self._open_school_picker()
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_e):
            if self.setup_row == 0:
                self.character_look = (self.character_look + 1) % len(CHARACTER_LOOKS)
            elif self.setup_row == 1:
                self._open_school_picker()
            else:
                self.state = STATE_PLAYING
                self.save_game()
                if self.character_school == "NOT FROM AROUND HERE":
                    self.add_toast("Welcome anyway. Keep your plates up to date.")
                else:
                    self.add_toast("Good. Now everybody knows your business.")

    # ---------------- input ----------------
    def handle_events(self):
        """Pump the OS queue first, then sample held keys.

        Order matters: pygame.key.get_pressed() is only refreshed by pumping
        the event queue, so the old code (get_pressed *before* event.get)
        steered the car with last frame's input on every single frame.
        """
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self.handle_keydown(event.key, getattr(event, 'unicode', ''))
            elif event.type == pygame.JOYBUTTONDOWN:
                self.handle_pad_button(event.button)
            elif event.type == pygame.MOUSEWHEEL:
                if self.state == STATE_PLAYING and not self.show_map:
                    self.cycle_weapon(-1 if event.y > 0 else 1)
            elif event.type == pygame.JOYHATMOTION:
                self.handle_pad_hat(event.value)
            elif event.type == pygame.JOYDEVICEADDED:
                self.open_gamepad()
            elif event.type == pygame.JOYDEVICEREMOVED:
                self.drop_gamepad()
                self.open_gamepad()

        if self.state != STATE_PLAYING or self.show_map or self.arch_victory_timer > 0:
            # Paused, dead, or reading the map: hold everything still rather
            # than letting the last throttle value keep the car rolling on.
            if self.driving:
                self.driving.input_throttle = 0.0
                self.driving.input_steer = 0.0
            self.player_dir = [0, 0]
            self.sprinting = False
            self.attack_held = False
            return

        keys = pygame.key.get_pressed()

        if self.driving:
            self.sprinting = False
            self.attack_held = False
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
            if self.pad is not None:
                throttle, steer = self.apply_pad_driving(throttle, steer)
            hb = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
            if self.pad is not None:
                hb = hb or self.pad_handbrake()
            self.driving.input_handbrake = bool(hb)
            if hb:
                # More lock while the back is loose, so the rotation you paid
                # for with grip is one you can actually steer.
                steer *= HANDBRAKE_STEER
            self.driving.input_throttle = max(-1.0, min(1.0, throttle))
            self.driving.input_steer = max(-1.0, min(1.0, steer))
        else:
            dx = dy = 0.0
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
            if self.pad is not None:
                dx, dy = self.apply_pad_walking(dx, dy)
            self.player_dir = [dx, dy]
            sprint = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
            if self.pad is not None:
                sprint = sprint or self.pad_handbrake()
            self.sprinting = bool(sprint)
            self.attack_held = bool(keys[pygame.K_SPACE] or keys[pygame.K_f])
            if self.pad is not None:
                self.attack_held = (self.attack_held or self.pad_button(PAD_X)
                                    or self.pad_button(PAD_B))

    def handle_keydown(self, key, text=""):
        """One-shot keys. ESC pauses; nothing quits outright from play.

        The old bindings had ESC *and* Q hard-quitting mid-drive with no
        confirmation and no autosave, and Q sits right next to WASD. Quitting
        now only happens from the pause menu.
        """
        if key == pygame.K_F11:
            self.toggle_fullscreen()
            return
        if key == pygame.K_F4:
            self.toggle_soundtrack()
            return
        if self.arch_victory_timer > 0:
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE,
                       pygame.K_e, pygame.K_ESCAPE):
                self.arch_victory_timer = 1
            return

        if self.state == STATE_TITLE:
            self.handle_title_key(key)
            return
        if self.state == STATE_CHARACTER:
            self.handle_character_key(key, text)
            return

        if self.show_map:
            if key in (pygame.K_m, pygame.K_TAB, pygame.K_ESCAPE):
                self.show_map = False
            return

        if key in (pygame.K_m, pygame.K_TAB):
            if self.state == STATE_PLAYING:
                self.show_map = True
            return

        if key in (pygame.K_ESCAPE, pygame.K_p, pygame.K_F1):
            self.toggle_pause()
            return

        if self.state == STATE_DEAD:
            if (key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_e)
                    and self.death_can_skip()):
                self.finish_death()
            return

        if self.state == STATE_PAUSED:
            if key == pygame.K_q:
                self.running = False
            elif key == pygame.K_F5:
                self.save_game()
            elif key == pygame.K_F9:
                self.load_game()
            return

        if key == pygame.K_F6:
            if self.driving is not None:
                self.cycle_radio()
            return

        if key in (pygame.K_SPACE, pygame.K_f):
            self.player_attack()
        elif key == pygame.K_q:
            self.cycle_weapon()
        elif key == pygame.K_e:
            if not self.try_halloween_joke():
                self.toggle_enter_exit()
        elif key == pygame.K_r:
            self.reroll_job()
        elif key == pygame.K_F5:
            self.save_game()
        elif key == pygame.K_F9:
            self.load_game()
        elif key == pygame.K_F2:
            self.postfx.toggle()
        elif key == pygame.K_F3:
            self.show_debug = not self.show_debug

    def toggle_pause(self):
        if self.state == STATE_DEAD:
            return              # you cannot pause your way out of a WASTED
        self.state = STATE_PLAYING if self.state == STATE_PAUSED else STATE_PAUSED

    def toggle_fullscreen(self):
        """F11: swap between borderless fullscreen and a resizable window.

        With the SCALED display flag pygame's toggle_fullscreen() is stable and
        keeps the aspect ratio (SDL letterboxes), so there is nothing to
        rebuild here - present() already scales into whatever size it is given.
        """
        if self._headless:
            return
        try:
            pygame.display.toggle_fullscreen()
            self.fullscreen = not self.fullscreen
        except pygame.error as e:
            self.add_toast(f"Fullscreen failed: {e}")

    def exit_vehicle(self):
        """Step out onto real ground, or refuse.

        The old code dropped the player at car.centerx - 40 with no collision
        test at all, so getting out anywhere with a wall to your left put you
        inside a building - or in the Mississippi - with no way back out.
        """
        car = self.driving
        heading = car.angle
        # Prefer the kerb side, then the other side, then behind, then ahead.
        for offset in (heading + math.pi / 2, heading - math.pi / 2,
                       heading + math.pi, heading):
            tx = car.rect.centerx + math.cos(offset) * 34
            ty = car.rect.centery + math.sin(offset) * 34
            spot = free_point_near(tx, ty, PLAYER_SIZE, PLAYER_SIZE, max_rings=2)
            if spot is not None:
                self.player_rect.center = spot
                car.driver = None
                car.parked = True
                car.input_throttle = 0.0
                car.input_steer = 0.0
                traffic_hand_back(car)
                self.driving = None
                self.side_mission_event('vehicle_exited', vehicle_id=id(car))
                return True
        self.add_toast("No room to get out!")
        return False

    def toggle_enter_exit(self):
        if self.driving:
            self.exit_vehicle()
            return
        if self.try_start_side_mission():
            return
        # Nearest jackable car wins, so standing between two does not pick
        # whichever happens to be earlier in the list.
        best, best_d = None, None
        for car in self.cars:
            if car.driver is not None:
                continue
            if not car.rect.inflate(24, 24).colliderect(self.player_rect):
                continue
            d = math.hypot(car.rect.centerx - self.player_rect.centerx,
                           car.rect.centery - self.player_rect.centery)
            if best_d is None or d < best_d:
                best, best_d = car, d
        if best is None:
            return
        best.driver = 'player'
        best.parked = False
        speed_factor = VEHICLE_TUNING.get(best.variant, {}).get('speed_factor', 1.0)
        best.max_speed = PLAYER_CAR_MAX_SPEED * speed_factor
        self.driving = best
        self.side_mission_event('vehicle_entered', vehicle_id=id(best))
        self.add_callout("JACKED!", hud_HUD_GOLD, ttl=FPS, scale=1)
        if best.variant in LOCAL_LEGENDS:
            self.legend_rumors.add(best.variant)
            self.legend_discovered.add(best.variant)
            if best.variant not in self.legend_garage:
                self.legend_garage.add(best.variant)
                self.add_callout("GARAGE UNLOCKED", hud_HUD_GOLD, ttl=FPS, scale=1)
            self.start_local_challenge(best.variant)
        elif best.variant == 'garbage_truck':
            self.start_local_challenge('trash_day')
        elif best is self.chain_bike:
            if self.start_local_challenge('chain_escape'):
                self.wanted_bump(3, 'chain_escape')
        if best.variant == 'trans_am':
            self.radio_index = 0
            self.add_toast("THE RADIO IS STUCK ON K-SHE 95ISH")
        elif best.variant == 'mudfoot':
            self.add_callout("THE ORIGINAL", hud_HUD_GOLD, scale=2)
            self.add_toast("BUILT BIG IN ST. LOUIS")
        elif best.variant == 'grocery_cart':
            self.add_callout("CART PARADE!", hud_HUD_GOLD, scale=2)
            self.add_toast("CLEANUP ON EVERY AISLE")
        if best.temp_tag:
            self.add_toast("THAT TEMP TAG EXPIRED THREE PRESIDENTS AGO")
            if (best.rect.centerx // TILE_SIZE + best.rect.centery // TILE_SIZE) % 4 == 0:
                self.wanted_bump(1, 'temp_tag')
        self.add_score(20, best.rect.center)

    # ---------------- on-foot movement ----------------
    def sync_player_float(self):
        """Re-seat the sub-pixel position on the rect after anything teleports
        the player (bust, wreck, load, stepping out of a car, a test)."""
        if (abs(self.player_fx - self.player_rect.centerx) > 1.5
                or abs(self.player_fy - self.player_rect.centery) > 1.5):
            self.player_fx = float(self.player_rect.centerx)
            self.player_fy = float(self.player_rect.centery)
            self.player_motion.update(0, 0)

    def move_player_on_foot(self):
        """Walk with sub-pixel precision and wall sliding.

        The old version moved int(dx), int(dy) as one all-or-nothing step, so
        diagonals lost a third of their speed to truncation and clipping any
        corner stopped you dead. Now each axis resolves on its own against the
        float position: brush a building and you slide along it.
        """
        self.sync_player_float()
        moving = bool(self.player_dir[0] or self.player_dir[1])
        self.sprint_active = bool(self.sprinting and moving and self.sprint_ready
                                  and self.player_stamina > 0)
        if self.sprint_active:
            self.player_stamina = max(0.0, self.player_stamina - PLAYER_STAMINA_DRAIN)
            if self.player_stamina <= 0:
                self.sprint_ready = False
        else:
            regen = PLAYER_STAMINA_HIDDEN_REGEN if self.hidden else PLAYER_STAMINA_REGEN
            self.player_stamina = min(PLAYER_STAMINA_MAX, self.player_stamina + regen)
            if self.player_stamina >= PLAYER_STAMINA_MAX * 0.35:
                self.sprint_ready = True
        base_speed = PLAYER_SPRINT_SPEED if self.sprint_active else PLAYER_SPEED
        speed = base_speed * self.grub_speed_scale()
        target = pygame.Vector2(self.player_dir[0] * speed,
                                self.player_dir[1] * speed)
        response = FOOT_ACCEL_RESPONSE if target.length_squared() else FOOT_BRAKE_RESPONSE
        self.player_motion += (target - self.player_motion) * response
        if self.player_motion.length_squared() < 0.001:
            self.player_motion.update(0, 0)
        dx, dy = self.player_motion.x, self.player_motion.y
        if dx == 0.0 and dy == 0.0:
            return
        if target.length_squared():
            self.player_aim = math.atan2(target.y, target.x)
        probe = self.player_rect.copy()
        for ax, ay in ((dx, 0.0), (0.0, dy)):
            if ax == 0.0 and ay == 0.0:
                continue
            nx, ny = self.player_fx + ax, self.player_fy + ay
            probe.center = (int(round(nx)), int(round(ny)))
            if (probe.left < 0 or probe.top < 0
                    or probe.right > MAP_WIDTH or probe.bottom > MAP_HEIGHT):
                continue
            if is_blocked(probe):
                if ax:
                    self.player_motion.x = 0.0
                if ay:
                    self.player_motion.y = 0.0
                continue
            self.player_fx, self.player_fy = nx, ny
            self.player_rect.center = probe.center

    # ---------------- update ----------------
    #: most a car is shoved out of another in one step, px. Ambient cars can
    #: close at 6.5px/step, so the old 4px cap literally lost ground while two
    #: cars approached and allowed a pileup to deepen indefinitely.
    UNSTACK_STEP = 8

    @staticmethod
    def traffic_footprint(car):
        """Cardinal, orientation-aware footprint used only for AI separation.

        Car.rect is deliberately an unrotated physics AABB. A northbound sedan
        therefore appears 34px wide to code even though its rendered body is
        only 18px across. Opposing north/south lanes are 30px apart, so the old
        separator saw correctly lane-centred cars as overlapping and shoved
        them off the street onto rail cuts and open landmark ground.
        """
        vertical = abs(math.sin(car.angle)) > abs(math.cos(car.angle))
        w, h = ((car.rect.h, car.rect.w) if vertical
                else (car.rect.w, car.rect.h))
        footprint = pygame.Rect(0, 0, w, h)
        footprint.center = car.rect.center
        return footprint

    def unstack_traffic(self):
        """Push overlapping AI cars apart, by the depth they actually overlap.

        main.py deliberately runs no car-to-car collision between AI cars -
        adding one deadlocks the grid, because a stopped car cannot steer.
        The cost of that was cars sitting *inside* each other: measured at a
        mean of 3.7 overlapping pairs on screen, 11 at worst, which is the
        "piling up on top of each other" you can see from the street.
        """
        traffic = [c for c in self.cars
                   if c.driver is None and c is not self.driving]
        for i, a in enumerate(traffic):
            for b in traffic[i + 1:]:
                ar, br = self.traffic_footprint(a), self.traffic_footprint(b)
                if not ar.colliderect(br):
                    continue
                if a.parked and b.parked:
                    continue                 # neither of them is going anywhere
                over = ar.clip(br)
                dx = ar.centerx - br.centerx
                dy = ar.centery - br.centery
                if dx == 0 and dy == 0:
                    dx = 1
                # Push out of the shallow axis: that is the way out.
                if over.w <= over.h:
                    axes = ((1 if dx >= 0 else -1, 0), (0, 1 if dy >= 0 else -1))
                    push = over.w
                else:
                    axes = ((0, 1 if dy >= 0 else -1), (1 if dx >= 0 else -1, 0))
                    push = over.h
                push = max(1, min(self.UNSTACK_STEP, push))
                # A parked car takes the whole shove; two movers split it.
                movable = [(a, 1), (b, -1)]
                if a.parked:
                    movable = [(b, -1)]
                elif b.parked:
                    movable = [(a, 1)]
                for car, sign in movable:
                    step = push if len(movable) == 1 else max(1, push // 2)
                    # Preferred axis first, the other one as a fallback: on a
                    # bridge deck or a walled street the sideways shove has
                    # nowhere to go and the cars would stay welded together.
                    for px_, py_ in axes:
                        moved = car.rect.move(px_ * sign * step, py_ * sign * step)
                        col, row = moved.centerx // TILE_SIZE, moved.centery // TILE_SIZE
                        on_route = car.parked or traffic__is_grid_road(col, row)
                        if (on_route
                                and 0 <= moved.left and moved.right <= MAP_WIDTH
                                and 0 <= moved.top and moved.bottom <= MAP_HEIGHT
                                and not is_blocked(moved)):
                            car.rect.topleft = moved.topleft
                            break

    def _camera_lead(self):
        """How far ahead of the player the view should sit, in world px.

        Each axis is capped at its own fraction of its own half-viewport, so
        the amount of road you get ahead of you scales with speed but the car
        is always comfortably inside the frame. The vertical budget is
        smaller because the vertical half-viewport is smaller - the previous
        version scaled it *up* by the aspect ratio and drove the car off the
        bottom of the screen at anything over half throttle.
        """
        half_w = SCREEN_WIDTH * 0.5
        half_h = SCREEN_HEIGHT * 0.5
        if self.driving:
            v = self.driving.velocity
            frac = min(1.0, abs(v) / max(1.0, self.driving.base_max_speed))
            reach = math.copysign(frac, v) * CAM_LEAD_STEPS * self.driving.base_max_speed
            ax = math.cos(self.driving.angle) * reach
            ay = math.sin(self.driving.angle) * reach
        else:
            ax = self.player_dir[0] * CAM_FOOT_LEAD
            ay = self.player_dir[1] * CAM_FOOT_LEAD
        lx = max(-half_w * CAM_LEAD_MAX_X, min(half_w * CAM_LEAD_MAX_X, ax))
        ly = max(-half_h * CAM_LEAD_MAX_Y, min(half_h * CAM_LEAD_MAX_Y, ay))
        return (lx, ly)

    def update(self):
        """One fixed 1/60s simulation step."""
        self.frame += 1
        if self.update_arch_victory():
            return
        # Hitstop: freeze the whole sim for a frame or two on a big impact.
        # step_sim only ever calls update() in whole SIM_DT slices, so N frozen
        # steps is exactly N/60s on any machine, and nothing changed this step
        # so every invariant is trivially still true.
        if self.freeze > 0:
            self.freeze -= 1
            return
        if self.state == STATE_DEAD:
            self.update_death()
            return
        self.update_rail_crossings()
        if self.driving:
            self.apply_grub_to_car()
            # Scraping a wall used to raise your wanted level. Bouncing off a
            # kerb is not a crime; only the offences in handle_collisions are.
            pre_speed = abs(self.driving.velocity)
            hit = self.driving.physics_step()
            if hit and pre_speed > IMPACT_MIN_SPEED:
                # gap: a wall scrape fires every single step otherwise
                self.play_impact(self.driving.rect.center, pre_speed, gap=8)
                self.kick(min(6.0, pre_speed * 1.0),
                          freeze=1 if pre_speed > IMPACT_HEAVY_SPEED else 0)
                self.spawn_burst(self.driving.rect.center, int(2 + pre_speed),
                                 ('spark', 'spark', 'debris'), pre_speed * 0.5)
                if pre_speed > IMPACT_HURT_SPEED:
                    self.driving.crash_damage(pre_speed * PLAYER_WALL_DAMAGE)
        else:
            self.move_player_on_foot()

        self.camera.center_on(self.active_rect(), self._camera_lead())

        for car in self.cars:
            if car.driver is None and not car.parked:
                traffic_drive(car, self.cars)
                # how long this car has been going nowhere, for the jam breaker
                car.stall = car.stall + 1 if abs(car.velocity) < 0.3 else 0
            elif car.parked and abs(car.velocity) > 0.05:
                # shunted at the kerb: let it coast to a stop instead of
                # absorbing the hit and sitting there like scenery
                car.input_throttle = 0.0
                car.input_steer = 0.0
                car.physics_step()

        self.unstack_traffic()
        for car in self.cars:
            car.tick_crash_cooldown()
        for cop in self.police:
            cop.tick_crash_cooldown()
        if self.driving is not None:
            self.driving.tick_crash_cooldown()

        for ped in self.pedestrians:
            ped.update(self)
        self.update_chatter()

        for rv in self.rail:
            rv.update()
        self.update_train_collisions()

        self.handle_collisions()
        self.update_local_challenge()
        self.check_potholes()
        if not self.driving:
            self.check_roadkill_risk()
        self.update_bullets()
        self.update_throwables()
        self.update_weapon_pickups()
        self.update_grub()
        self.update_bank()
        self.update_dropped_cash()
        self.update_body_shop()
        self.lay_skid_marks()
        if self.hs_cooldown > 0:
            self.hs_cooldown -= 1
        if self.attack_cd > 0:
            self.attack_cd -= 1
        if self.attack_held and self.weapon == 'smg' and self.attack_cd <= 0:
            self.player_attack()
        if self.punch_timer > 0:
            self.punch_timer -= 1
        self.update_population()
        self.update_city_event()
        self.update_radio_programming()
        self.update_special_vehicle_audio()
        self.update_wrecks()
        self.update_police()
        self.update_side_mission()
        self.update_wanted_decay()
        self.update_arch_job()
        self.update_job()
        self.update_frenzy()
        self.update_multiplier()
        self.update_local_legends()
        self.check_landmark_discovery()
        self.update_place_names()
        self.update_fx()

        if self.combo_timer > 0:
            self.combo_timer -= 1
            if self.combo_timer == 0:
                self.combo = 0
        self.callouts = [c for c in self.callouts
                         if self.frame - c['born'] < c['ttl']]
        self.pops = [p for p in self.pops if self.frame - p['born'] < 46]
        if self.score > self.best_score:
            self.best_score = self.score
        if not self.driving and self.player_hp < PLAYER_MAX_HP:
            self.player_hp = min(PLAYER_MAX_HP, self.player_hp + PLAYER_HP_REGEN)

        self.speech_bubbles = [bubble for bubble in self.speech_bubbles
                               if self.frame <= bubble['end']
                               and (bubble['speaker'] == 'player'
                                    or bubble['speaker'] in self.pedestrians)]
        self.toasts = [t for t in self.toasts if pygame.time.get_ticks() < t.expires]
        if self.busted_flash > 0:
            self.busted_flash -= 1
        if self.wasted_flash > 0:
            self.wasted_flash -= 1
        self.update_audio()

    def update_audio(self):
        """Drive the looping buses: engine, tyres, sirens, ambient bed.

        Everything here is a *held* sound whose volume and pitch bucket change
        - never a re-trigger. Restarting an engine loop every step is the
        classic way to turn a car into a machine gun.
        """
        if not snd__enabled:
            return
        snd_set_frame(self.frame)
        cam = self.active_rect().center

        # --- engine ------------------------------------------------------
        car = self.driving
        if car is not None:
            frac = min(1.0, abs(car.velocity) / max(1.0, car.base_max_speed))
            bucket = snd_engine_bucket(frac)
            vol = (0.13 + 0.34 * frac) * snd__master
            snd_loop(snd_CH_ENGINE_A, f'engine{bucket}', vol)
            if car.input_throttle > 0 or (car.input_throttle < 0 and car.velocity <= 0):
                # A second loop a bucket up, quieter. The beating between the
                # two is what makes an engine sound like it is working rather
                # than droning.
                up = min(len(snd_ENGINE_PERIODS) - 1, bucket + 1)
                snd_loop(snd_CH_ENGINE_B, f'engineload{up}', vol * 0.55)
            else:
                snd_stop(snd_CH_ENGINE_B)
            # --- tyres: one channel, volume-driven, never re-triggered ----
            if car.slip > SLIP_SCREECH:
                snd_loop(snd_CH_TYRES, 'screech',
                         min(0.5, (car.slip - SLIP_SCREECH) * 0.22) * snd__master)
            else:
                snd_stop(snd_CH_TYRES)
        else:
            snd_stop(snd_CH_ENGINE_A)
            snd_stop(snd_CH_ENGINE_B)
            snd_stop(snd_CH_TYRES)

        # --- sirens: the nearest unit only -------------------------------
        # City yelp against county wail. St. Louis genuinely has two police
        # forces and they genuinely do not sound the same, so the escalation
        # is audible before it is visible - which also solves not being able
        # to tell which car in traffic is a cop.
        nearest, best = None, 1e9
        for cop in self.police:
            d = math.hypot(cop.rect.centerx - cam[0], cop.rect.centery - cam[1])
            if d < best:
                nearest, best = cop, d
        if nearest is not None and best < 700:
            county = nearest.police_agency == 'county'
            closing = -nearest.velocity if nearest.velocity else 0.0
            tag = 'hi' if closing < -3 else ('lo' if closing > 3 else 'mid')
            key = ('wail' if county else 'yelp') + tag
            left, right = snd_pan_volume(nearest.rect.center, cam, 0.55, 760.0)
            snd_loop(snd_CH_SIREN, key, 0.0, left, right)
        else:
            snd_stop(snd_CH_SIREN)

        # --- the ambient bed --------------------------------------------
        # A train horn on the river and cicadas in the parks. If this game
        # ships one ambient sound it should be the horn.
        duck = snd_ducking()
        col = int(cam[0]) // TILE_SIZE
        row = int(cam[1]) // TILE_SIZE
        near_river = col >= river_bank(row) - 12
        if near_river and self.frame % (FPS * 26) == 0:
            snd_play('horn', vol=0.5 * duck)
        if tile_type_at(col, row) == TILE_PARK:
            snd_loop(snd_CH_AMBIENT, 'cicadas', 0.22 * duck * snd__master)
        else:
            snd_stop(snd_CH_AMBIENT)

    def update_death(self):
        """The three seconds you are not playing.

        The world keeps breathing behind the card - traffic rolls, particles
        settle, the wreck you are lying next to finishes burning - but nothing
        can hurt you and nothing you do reaches the game.
        """
        self.death_timer -= 1
        for car in self.cars:
            if car.driver is None and not car.parked:
                traffic_drive(car, self.cars)
        for rv in self.rail:
            rv.update()
        self.update_wrecks()
        self.update_fx()
        self.callouts = [c for c in self.callouts
                         if self.frame - c['born'] < c['ttl']]
        self.pops = [p for p in self.pops if self.frame - p['born'] < 46]
        self.toasts = [t for t in self.toasts if pygame.time.get_ticks() < t.expires]
        if self.busted_flash > 0:
            self.busted_flash -= 1
        if self.wasted_flash > 0:
            self.wasted_flash -= 1
        if snd__enabled:
            snd_stop(snd_CH_ENGINE_A)
            snd_stop(snd_CH_ENGINE_B)
            snd_stop(snd_CH_TYRES)
            snd_stop(snd_CH_SIREN)
        if self.death_timer <= 0:
            self.finish_death()

    def death_can_skip(self):
        """True once the result card has been readable for a short beat."""
        return (self.state == STATE_DEAD
                and self.death_timer <= DEATH_HOLD_STEPS - DEATH_SKIP_AFTER_STEPS)

    # ---------------- side jobs ----------------
    def side_mission_contact(self):
        name = SIDE_MISSION_CONTACT_NAMES[
            self.side_mission_serial % len(SIDE_MISSION_CONTACT_NAMES)]
        return self.landmark_job_point(name), name

    def try_start_side_mission(self):
        """Accept the current contact's job when E is pressed nearby."""
        if (self.driving is not None or self.side_mission is not None
                or self.local_challenge is not None
                or self.side_mission_cooldown > 0
                or self.arch_job_phase in ARCH_ACTIVE_PHASES):
            return False
        contact, _name = self.side_mission_contact()
        if math.hypot(self.player_rect.centerx - contact[0],
                      self.player_rect.centery - contact[1]) > SIDE_MISSION_CONTACT_RADIUS:
            return False

        family = mission_logic.MISSION_FAMILIES[
            self.side_mission_serial % len(mission_logic.MISSION_FAMILIES)]
        self.side_target_car = None
        self.side_target_pos = None
        self.smash_targets = []
        if family == mission_logic.VEHICLE_THEFT:
            candidates = [car for car in self.cars
                          if car is not self.driving and car.burn <= 0]
            if not candidates:
                self.add_toast("No suitable ride on the street")
                return True
            origin = pygame.Vector2(contact)
            target = max(candidates, key=lambda car: (
                1 if car.variant == 'trans_am' else 0,
                -pygame.Vector2(car.rect.center).distance_to(origin)))
            self.side_target_car = target
            shops = self.body_shops or [self.landmark_job_point("The Hill")]
            self.side_target_pos = max(
                shops, key=lambda pos: pygame.Vector2(pos).distance_to(target.rect.center))
            vehicle_name = target.variant.replace('_', ' ').upper()
            self.side_mission = mission_logic.VehicleTheftMission(
                id(target), vehicle_name, chop_shop_id='chop_shop',
                reward=1100, time_limit_steps=FPS * 80)
        elif family == mission_logic.SMASH_TARGETS:
            base = pygame.Vector2(self.landmark_job_point("Grand Center Arts District"))
            offsets = ((-180, -70), (-95, 110), (15, -135),
                       (95, 95), (180, -35), (235, 125))
            for index, (ox, oy) in enumerate(offsets):
                pos = free_point_near(base.x + ox, base.y + oy, 14, 14,
                                      max_rings=8)
                if pos is None:
                    continue
                self.smash_targets.append({
                    'id': f'grand-glass-{index}', 'pos': pos,
                    'hp': 55.0, 'last_hit': -10 ** 9,
                })
            if not self.smash_targets:
                self.add_toast("The Grand job fell through")
                return True
            self.side_mission = mission_logic.SmashTargetsMission(
                [target['id'] for target in self.smash_targets],
                reward=1500, time_limit_steps=FPS * 65)
        else:
            self.side_target_pos = self.landmark_job_point("The Hill")
            self.side_mission = mission_logic.EvadeHeatMission(
                safehouse_id='hill', cool_steps=FPS * 6,
                reward=1900, time_limit_steps=FPS * 90)

        update = self.side_mission.start()
        if family == mission_logic.EVADE_HEAT and self.wanted_level < 3:
            self.wanted_bump(3 - self.wanted_level, 'side_job')
        self.add_callout(update.name.upper(), SIDE_MISSION_MARKER_COLORS[0],
                         ttl=FPS * 2, scale=1, tag='side-job')
        self.add_toast(update.objective)
        return True

    def handle_side_mission_update(self, update):
        if update is None or not (update.complete or update.failed):
            return False
        if update.complete:
            self.cash += update.reward_delta
            self.side_missions_done += 1
            self.add_score(250, mult=False)
            self.add_callout("SIDE JOB COMPLETE", hud_HUD_GREEN, scale=2)
            self.add_pop(self.active_rect().center, f"+${update.reward_delta}",
                         hud_HUD_GREEN)
            self.play_sound('cash', vol=0.8)
        else:
            self.side_missions_failed += 1
            self.add_callout("SIDE JOB FAILED", hud_HUD_RED, scale=1)
            self.play_sound('bad', vol=0.65)
        self.add_toast(update.message or update.objective)
        self.side_mission = None
        self.side_target_car = None
        self.side_target_pos = None
        self.smash_targets = []
        self.side_mission_serial += 1
        self.side_mission_cooldown = SIDE_MISSION_COOLDOWN
        return True

    def side_mission_event(self, event, **data):
        if self.side_mission is None:
            return False
        return self.handle_side_mission_update(
            self.side_mission.on_event(event, **data))

    def damage_smash_target(self, hit_rect, damage):
        if (self.side_mission is None
                or self.side_mission.family != mission_logic.SMASH_TARGETS):
            return False
        for target in self.smash_targets:
            if target['hp'] <= 0:
                continue
            rect = pygame.Rect(0, 0, 16, 20)
            rect.center = target['pos']
            if not rect.inflate(5, 5).colliderect(hit_rect):
                continue
            target['hp'] -= float(damage)
            target['last_hit'] = self.frame
            self.spawn_burst(target['pos'], 7, ('glass', 'debris'), 2.4)
            self.play_impact(target['pos'], 5.0, gap=2)
            if target['hp'] <= 0:
                target['hp'] = 0
                self.add_score(25, target['pos'])
                self.side_mission_event('target_smashed', target_id=target['id'])
            return True
        return False

    def update_side_mission(self):
        if self.side_mission_cooldown > 0:
            self.side_mission_cooldown -= 1
        mission = self.side_mission
        if mission is None:
            return
        if mission.family == mission_logic.VEHICLE_THEFT:
            target = self.side_target_car
            if target is None:
                self.side_mission_event('vehicle_destroyed', vehicle_id=-1)
                return
            if (mission.stage in ('deliver', 'recover') and self.driving is target
                    and self.side_target_pos is not None
                    and pygame.Vector2(target.rect.center).distance_to(
                        self.side_target_pos) <= BODY_SHOP_RADIUS):
                if self.side_mission_event(
                        'location_reached', location_id='chop_shop',
                        vehicle_id=id(target), condition=target.hp / target.max_hp):
                    return
        elif mission.family == mission_logic.SMASH_TARGETS and self.driving is not None:
            speed = abs(self.driving.velocity)
            if speed >= 1.4:
                for target in self.smash_targets:
                    if (target['hp'] > 0 and self.frame - target['last_hit'] > 12):
                        rect = pygame.Rect(0, 0, 16, 20)
                        rect.center = target['pos']
                        if self.driving.rect.colliderect(rect):
                            self.damage_smash_target(rect, speed * 14.0)
                            self.driving.velocity *= 0.82
                            break
        elif mission.family == mission_logic.EVADE_HEAT:
            update = mission.tick(1, wanted_level=self.wanted_level,
                                  spotted=self.spotted)
            if self.handle_side_mission_update(update):
                return
            if (mission.stage == 'reach_safehouse' and self.side_target_pos is not None
                    and pygame.Vector2(self.active_rect().center).distance_to(
                        self.side_target_pos) <= JOB_MARKER_RADIUS):
                self.side_mission_event('location_reached', location_id='hill')
            return
        self.handle_side_mission_update(mission.tick())

    # ---------------- jobs ----------------
    def deal_job(self, exclude=None):
        """Deal a different run card from the recent two whenever possible."""
        choices = [kind for kind in JOB_KIND_ORDER
                   if kind not in self.recent_job_kinds[-2:]]
        if not choices:
            choices = list(JOB_KIND_ORDER)
        kind = random.choice(choices)
        self.recent_job_kinds.append(kind)
        self.recent_job_kinds = self.recent_job_kinds[-2:]
        return Job.generate(exclude=exclude, kind=kind)

    def update_job(self):
        """Advance the courier run: pickup, clock, drop-off, payout."""
        if self.side_mission is not None or self.local_challenge is not None:
            return
        finale_pending = self.arch_job_unlocked and not self.arch_job_completed
        if finale_pending and not (self.arch_job_phase == ARCH_READY and
                                    self.job is not None and self.job.collected):
            if self.job is not None and not self.job.collected:
                self.job = None
            return
        if self.job_cooldown > 0:
            self.job_cooldown -= 1
            if self.job_cooldown == 0 and self.job is None:
                self.job = self.deal_job()
                self.add_toast(f"New run: {self.job.pickup[5]}")
            return
        if self.job is None:
            self.job = self.deal_job()
            return

        active = self.active_rect()
        tx, ty = self.job.target_pos
        near = math.hypot(active.centerx - tx, active.centery - ty) <= JOB_MARKER_RADIUS

        if not self.job.collected:
            # An offer you never take goes stale rather than sitting on the
            # HUD for the whole session.
            self.job.offer_left -= 1
            if self.job.offer_left <= 0:
                self.job = None
                self.job_cooldown = FPS
                self.add_toast("That run went to somebody else")
                return
            if not near:
                return
            if self.wanted_level >= JOB_HEAT_LIMIT:
                # One toast, not one per frame.
                if self.frame % (FPS * 2) == 0:
                    self.add_toast("Too hot - lose the cops first")
                return
            self.job.collect()
            if self.chain_until > self.frame:
                self.job.hot = True
                self.add_callout("HOT STREAK", hud_HUD_GOLD, scale=1, tag='chain')
            if self.job.kind == 'hot':
                self.wanted_bump(2, 'hot_job')
                self.add_callout("HOT LOAD", hud_HUD_RED, scale=2, tag='hot_job')
            elif self.job.kind == 'heavy':
                self.add_toast("Heavy load: top speed reduced")
            self.add_toast(f"Picked up: {self.job.cargo}")
            self.play_sound('pickup', vol=0.5)
            return

        if self.job.tick():
            self.fail_job("Too slow - run lost")
            return
        if near:
            mastered = self.job.kind not in self.job_types_done
            paid = self.job.payout(self.streak)
            if self.job.hot:
                paid = int(paid * (1.0 + JOB_CHAIN_BONUS))
            if mastered:
                paid += JOB_MASTERY_BONUS
                self.job_types_done.add(self.job.kind)
            paid = int(round(paid * (1.0 + CITY_EVENT_JOB_BONUS)))
            self.cash += paid
            self.add_score(50, mult=False)         # the careful loop stays flat
            self.jobs_done += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
            tail = f" (x{self.streak} streak)" if self.streak > 1 else ""
            self.add_toast(f"Delivered! ${paid}{tail}")
            if mastered:
                self.add_callout("NEW RUN MASTERED", hud_HUD_GOLD, scale=2)
                self.add_toast(
                    f"Run types {len(self.job_types_done)}/{len(JOB_KIND_ORDER)} mastered")
            else:
                self.add_callout("DELIVERED!", hud_HUD_GREEN, scale=2)
            self.add_pop(active.center, f"+${paid}", hud_HUD_GREEN)
            self.play_sound('cash', vol=0.8)
            # The next run is already on the table. Take it inside the window
            # and it pays more - which replaces two seconds of silence with a
            # decision, and is the cheapest retention in the game.
            if self.arch_job_unlocked and not self.arch_job_completed:
                self.job = None
                self.job_cooldown = 0
                self.chain_until = 0
                self.add_toast("Somebody is waiting under the Arch")
            else:
                self.job = self.deal_job()
                self.job_cooldown = 0
                self.chain_until = self.frame + JOB_CHAIN_WINDOW
                self.add_toast(f"Next: {self.job.pickup[5]} (+{int(JOB_CHAIN_BONUS * 100)}% if you hurry)")

    def reroll_job(self):
        """R: throw this run back. Only before you have picked the cargo up -
        once it is in the boot it is yours."""
        if (self.arch_job_unlocked and not self.arch_job_completed) or self.job is None or self.job.collected:
            return
        self.job = self.deal_job()
        self.chain_until = 0
        self.add_toast(f"New run: {self.job.pickup[5]}")

    def fail_job(self, reason):
        if self.job is None:
            return
        self.jobs_failed += 1
        self.streak = 0
        self.job = None
        self.job_cooldown = FPS * 2
        self.add_toast(reason)

    # ---------------- heat ----------------
    def wanted_bump(self, stars, key):
        """Commit an offence worth `stars`, rate-limited per offence type.

        Wanted levels are whole stars now. The old code added fractions
        (0.15 for a wall scrape, 0.5 for a fender bender) and then spawned
        int(wanted_level) cops, so the star display and the actual police
        response disagreed with each other for most of a chase.
        """
        if self.frame < self.infraction_at.get(key, 0):
            return
        self.infraction_at[key] = self.frame + INFRACTION_COOLDOWN.get(key, FPS)
        was = self.wanted_level
        self.wanted_level = min(WANTED_MAX, self.wanted_level + stars)
        self.peak_star = max(self.peak_star, self.wanted_level)
        self.heat_timer = 0
        self.wanted_decay_timer = 0
        # Somebody saw you do it and called it in. Units dispatched for this
        # star are sent *here*, not conjured with a fix on wherever you have
        # got to since - without this a low star is not a chase, it is a
        # countdown, because a lone unit spawns 400-900px out with no idea
        # which way to look and simply never finds you.
        self.crime_pos = self.active_rect().center
        self.crime_frame = self.frame
        if self.wanted_level > was and self.wanted_level == 1:
            self.foot_cop_respawn = max(self.foot_cop_respawn,
                                        COP_RESPONSE_BY_STAR[1])
            self.add_toast("Wanted! Lose them or get busted")

    def barge_pedestrians(self):
        """On foot you are a solid object too: shoulder people out of the way
        instead of ghosting straight through them."""
        pr = self.player_rect
        for ped in self.pedestrians:
            if ped.down_timer > 0 or not pr.colliderect(ped.rect.inflate(2, 2)):
                continue
            push = pygame.Vector2(ped.rect.centerx - pr.centerx,
                                  ped.rect.centery - pr.centery)
            if push.length() == 0:
                push = pygame.Vector2(1, 0)
            ped.knock = push.normalize() * 2.4
            if ped.mood == 'calm':
                if self.maybe_ask_high_school(ped):
                    continue
                if self.maybe_start_stl_conversation(ped):
                    continue
                if self.wanted_level > 0 and self.chatter_cooldown <= 0:
                    self.chatter_cooldown = FPS * 4
                    self.add_toast(self.panic_line(ped))
                ped._flee((push.x, push.y), random.randint(40, 70))

    def maybe_ask_high_school(self, ped):
        """The question. Character creation supplies the only answer you get."""
        if self.hs_cooldown > 0 or self.wanted_level > 0:
            return False
        if random.randrange(HS_CHANCE):
            return False
        self.hs_cooldown = HS_COOLDOWN
        self.chatter_cooldown = CHATTER_COOLDOWN
        self.hs_asked += 1
        answer = self.character_school
        # Use the abbreviation locals actually say when one is canonical.
        answer = next((alias for alias, target in HS_SEARCH_ALIASES.items()
                       if target == answer), answer)
        if self.character_school == "NOT FROM AROUND HERE":
            reply = "OH. THEN WHY ARE YOU HERE?"
        elif self.character_school == "MY SCHOOL ISN'T LISTED":
            reply = "HUH. TAKE IT UP WITH DESE."
        else:
            # Say it three times and somebody finally knows your cousin.
            reply = (HS_REPLIES[3] if self.hs_asked % 3 == 0
                     else HS_REPLIES[self.hs_asked % len(HS_REPLIES)])
        self.add_speech_bubble(ped, HS_QUESTION)
        self.add_speech_bubble('player', answer, delay=int(FPS * 1.05))
        self.add_speech_bubble(ped, reply, delay=int(FPS * 2.10))
        self.play_sound(f'yell{self.hs_asked % 4}', ped.rect.center,
                        vol=0.35, gap=30)
        ped.mood = 'gawk'
        ped.mood_timer = FPS
        return True

    def panic_line(self, ped):
        """A scared local says something local. All five panic lines used to
        be citywide, so the Ville and Soulard screamed the same thing."""
        hood = hood_at(ped.rect.centerx // TILE_SIZE, ped.rect.centery // TILE_SIZE)
        local = STL_PANIC_BY_HOOD.get(hood, ())
        if local and random.random() < CHATTER_LOCAL_BIAS:
            return random.choice(local)
        return random.choice(STL_PANIC_LINES)

    def maybe_solo_bark(self, ped):
        """One passer-by says one thing. No partner required, so this fires in
        the thin crowds where a two-hander never gets a chance."""
        if self.chatter_cooldown > 0 or self.wanted_level > 0:
            return False
        hood = hood_at(ped.rect.centerx // TILE_SIZE, ped.rect.centery // TILE_SIZE)
        scene = self.chatter.pick(hood, SOLO_CITYWIDE, SOLO_BY_HOOD)
        if scene is None:
            return False
        self.chatter_cooldown = CHATTER_COOLDOWN // 2
        self.add_speech_bubble(ped, scene[1])
        return True

    def reaction_bark(self, ped):
        """Somebody watched you do that."""
        if self.chatter_cooldown > 0:
            return False
        self.chatter_cooldown = FPS * 3
        self.add_speech_bubble(ped, self.chatter.deal(
            ('react',), STL_REACTION_BARKS))
        return True

    def maybe_start_stl_conversation(self, ped, partner=None, forced=False):
        """Start one tagged local exchange, never over an active chase."""
        if self.chatter_cooldown > 0 or self.wanted_level > 0:
            return False
        if not forced and random.randrange(CHATTER_BARGE_CHANCE):
            return False
        hood = hood_at(ped.rect.centerx // TILE_SIZE, ped.rect.centery // TILE_SIZE)
        # Was: build the whole eligible list and random.choice it, every time,
        # with no memory. Deal from a shuffled deck instead, biased to the
        # neighbourhood you are actually standing in.
        scene = self.chatter.pick(hood, STL_CITYWIDE, STL_LOCAL_BY_HOOD)
        if scene is None:
            return False
        lines = scene[1:]
        self.chatter_cooldown = CHATTER_COOLDOWN
        for index, line in enumerate(lines):
            if index % 2 == 0:
                speaker = ped
            else:
                speaker = partner if partner is not None else 'player'
            self.add_speech_bubble(speaker, line, delay=index * int(FPS * 1.05))
        self.play_sound(f'yell{(self.frame // 7) % 4}', ped.rect.center,
                        vol=0.28, gap=45)
        ped.mood = 'gawk'
        ped.mood_timer = FPS * 2
        if partner is not None:
            ped.gawk_at(partner.rect.center, FPS * 2)
            partner.gawk_at(ped.rect.center, FPS * 2)
        return True

    def update_chatter(self):
        """Let nearby calm pedestrians occasionally talk to each other."""
        if self.chatter_cooldown > 0:
            self.chatter_cooldown -= 1
        if (self.chatter_cooldown > 0 or self.wanted_level > 0
                or self.frame % CHATTER_CHECK_STEPS != 0):
            return
        ax, ay = self.active_rect().center
        nearby = [ped for ped in self.pedestrians
                  if ped.mood == 'calm' and ped.down_timer <= 0
                  and (ped.rect.centerx - ax) ** 2 + (ped.rect.centery - ay) ** 2
                  < 190 ** 2]
        random.shuffle(nearby)
        for i, ped in enumerate(nearby):
            partner = next((other for other in nearby[i + 1:]
                            if (other.rect.centerx - ped.rect.centerx) ** 2
                            + (other.rect.centery - ped.rect.centery) ** 2 < 62 ** 2), None)
            if partner is not None:
                self.maybe_start_stl_conversation(ped, partner, forced=True)
                return
        # Nobody is standing close enough to anybody to hold a conversation.
        # A lone passer-by can still say one thing - which is what keeps the
        # thinner neighbourhoods from being silent.
        if nearby and random.random() < 0.5:
            self.maybe_solo_bark(nearby[0])

    # ---------------- rail traffic control ----------------
    def rail_gate_holds(self, car):
        return any(crossing.holds(car) for crossing in self.rail_crossings)

    def update_rail_crossings(self):
        """Animate gates from train position and sound each warning edge once."""
        here = pygame.Vector2(self.active_rect().center)
        for crossing in self.rail_crossings:
            started = crossing.update(self.rail)
            if (started and here.distance_to((crossing.x, crossing.y)) < 950):
                self.play_sound('horn', (crossing.x, crossing.y), vol=0.72,
                                gap=FPS, reach=1200.0)

    def update_train_collisions(self):
        """Closed gates are advice; ignoring one gives the train right-of-way."""
        trains = [vehicle for vehicle in self.rail
                  if vehicle.kind == 'metrolink']
        if not trains:
            return
        vehicles = self.combat_vehicle_pool()
        if self.driving is not None and self.driving not in vehicles:
            vehicles.append(self.driving)
        for train in trains:
            hitbox = train.rect.inflate(-6, -4)
            travel = 1.0 if train.speed >= 0 else -1.0
            for car in vehicles:
                if not hitbox.colliderect(car.rect):
                    continue
                if self.frame - getattr(car, 'train_hit_frame', -10 ** 9) < FPS:
                    continue
                car.train_hit_frame = self.frame
                car.damage(RAIL_TRAIN_COLLISION_DAMAGE)
                car.velocity = travel * min(4.0, abs(train.speed) + 0.7)
                car.vlat += travel * 2.8
                self.spawn_burst(car.rect.center, 18,
                                 ('spark', 'glass', 'debris'), 4.2)
                self.play_impact(car.rect.center, 9.0, gap=4)
                self.kick(7.0, freeze=2, flash=4)
                if car is self.driving:
                    self.add_callout("TRAIN WINS", hud_HUD_RED, ttl=FPS, scale=2)

            for ped in list(self.pedestrians):
                if hitbox.colliderect(ped.rect):
                    impulse = pygame.Vector2(travel * 11.0, 0.0)
                    self.splatter_ped(ped, impulse, score=False)
            if self.driving is None and hitbox.colliderect(self.player_rect):
                self.player_hp = 0
                self.wasted("HIT BY METROLINK")
                return

    def handle_collisions(self):
        if not self.driving:
            self.barge_pedestrians()
            return
        speed = abs(self.driving.velocity)
        for ped in list(self.pedestrians):
            if ped.bump_cooldown <= 0 and self.driving.rect.colliderect(ped.rect.inflate(6, 6)):
                ped.bump_cooldown = 90
                # Knockback along a blend of the car's heading and the radial,
                # scaled by speed - a flat-out clip launches, a crawl stumbles.
                travel_sign = -1.0 if self.driving.velocity < 0 else 1.0
                heading = pygame.Vector2(math.cos(self.driving.angle),
                                         math.sin(self.driving.angle)) * travel_sign
                radial = pygame.Vector2(ped.rect.centerx - self.driving.rect.centerx,
                                        ped.rect.centery - self.driving.rect.centery)
                radial = radial.normalize() if radial.length() > 0 else heading
                mag = 2.5 + min(PLAYER_CAR_MAX_SPEED, speed) * 2.1
                kb = heading * 0.6 + radial * 0.7
                kb = kb.normalize() * mag if kb.length() > 0 else radial * mag
                if speed >= SPLAT_SPEED:
                    # Hit at real speed: they do not get back up.
                    self.play_impact(ped.rect.center, speed, gap=3)
                    self.play_sound(f'yell{self.frame % 4}', ped.rect.center,
                                    vol=0.55, gap=10)
                    self.kick(1.3 + min(3.0, speed * 0.45))
                    self.splatter_ped(ped, kb, speed=speed)
                    continue
                ped.knock = kb
                if speed > 2.0:
                    ped.mood = 'down'
                    ped.down_timer = random.randint(45, 80)
                    ped.mood_timer = 0
                # Chaos pays in score, never in cash - the delivery loop is the
                # only thing that puts money in your pocket. Combo stacks the
                # per-hit value; GTA1's GOURANGA lives here.
                self.bump_combo(ped.rect.center, 5, speed)
                # Rolling into somebody in a parking bay is not a crime. This
                # used to fire at *any* closing speed including 0.0, which
                # criminalised careful driving: a measured pilot that yielded,
                # braked and swerved still spent a quarter of a ten-minute
                # session at 3+ stars and, with JOB_HEAT_LIMIT blocking
                # pickups above three, completed no deliveries at all.
                if speed >= NUDGE_SPEED:
                    self.wanted_bump(1, 'pedestrian')
                self.kick(1.3 + min(3.0, speed * 0.28))
                self.spawn_burst(ped.rect.center, 4, ('debris',), 1.8)
                self.frenzy_hit('ped')
                for other in self.pedestrians:
                    if other is ped or other.mood in ('flee', 'down'):
                        continue
                    ox = other.rect.centerx - ped.rect.centerx
                    oy = other.rect.centery - ped.rect.centery
                    if ox * ox + oy * oy < 82 * 82:
                        other.gawk_at(ped.rect.center, random.randint(90, 150))
        for cop in list(self.foot_police):
            if cop.bump_cooldown > 0 or not self.driving.rect.colliderect(cop.rect.inflate(6, 6)):
                continue
            cop.bump_cooldown = 75
            travel_sign = -1.0 if self.driving.velocity < 0 else 1.0
            heading = pygame.Vector2(math.cos(self.driving.angle),
                                     math.sin(self.driving.angle)) * travel_sign
            radial = pygame.Vector2(cop.rect.centerx - self.driving.rect.centerx,
                                    cop.rect.centery - self.driving.rect.centery)
            radial = radial.normalize() if radial.length() > 0 else heading
            impulse = heading * 0.65 + radial * 0.65
            if impulse.length() > 0:
                impulse = impulse.normalize() * (3.0 + speed * 2.1)
            self.play_impact(cop.rect.center, speed, gap=3)
            if speed >= SPLAT_SPEED:
                self.damage_foot_cop(cop, COP_FOOT_HP, impulse,
                                     cause='vehicle', lethal=True)
            elif speed >= NUDGE_SPEED:
                self.damage_foot_cop(cop, max(18.0, speed * 12.0), impulse,
                                     cause='vehicle')
                cop.down_timer = max(cop.down_timer, COP_FOOT_KNOCKDOWN)
        for car in self.cars:
            if car is self.driving or car.driver == 'player':
                continue
            if self.driving.rect.colliderect(car.rect):
                self.shunt(car, speed)
                # A nudge in traffic is not a crime; a real shunt is.
                if speed > RAM_SPEED:
                    self.add_score(2, car.rect.center)
                    self.wanted_bump(1, 'traffic')
                    self.kick(min(5.0, speed * 0.8),
                              freeze=1 if speed > IMPACT_HEAVY_SPEED else 0)
                    self.spawn_burst(car.rect.center, int(2 + speed),
                                     ('spark', 'glass'), speed * 0.5)
                    self.play_impact(car.rect.center, speed)
                    self.driving.crash_damage(speed * PLAYER_RAM_DAMAGE * self.grub_self_ram())
                    car.crash_damage(speed * 1.6 * self.grub_ram_scale())
        for cop in self.police:
            if self.driving.rect.colliderect(cop.rect):
                self.shunt(cop, speed)
                if speed > RAM_SPEED:
                    self.wanted_bump(1, 'cop')
                    self.kick(min(5.0, speed * 0.8))
                    self.spawn_burst(cop.rect.center, int(2 + speed),
                                     ('spark', 'glass'), speed * 0.5)
                    self.play_impact(cop.rect.center, speed)
                    self.driving.crash_damage(speed * PLAYER_RAM_DAMAGE * self.grub_self_ram())
                    cop.crash_damage(speed * 1.3 * self.grub_ram_scale())

    def shunt(self, other, speed):
        """Momentum transfer into a rammed car: shove it down the contact
        normal, yaw it away from an off-centre hit, and bleed the matching
        speed off you. Traffic used to absorb a 9.5 broadside without so much
        as twitching, which made ramming feel like driving through a poster."""
        me = self.driving
        if me is None or speed < 0.4:
            return
        normal = pygame.Vector2(other.rect.centerx - me.rect.centerx,
                                other.rect.centery - me.rect.centery)
        if normal.length() == 0:
            normal = pygame.Vector2(math.cos(me.angle), math.sin(me.angle))
        normal = normal.normalize()
        heading = pygame.Vector2(math.cos(other.angle), math.sin(other.angle))
        # how much of the shove lands along the victim's own axis vs sideways
        along = heading.dot(normal)
        mass_ratio = max(0.35, min(2.2, me.max_hp / max(1.0, other.max_hp)))
        push = min(6.0, speed * 0.55 * mass_ratio)
        other.velocity = max(-other.max_speed, min(other.max_speed,
                                                   other.velocity + push * along))
        # sideways component spins it: cross product sign picks the direction
        cross = heading.x * normal.y - heading.y * normal.x
        other.angle += cross * push * 0.055
        other.steer_angle *= 0.4
        me.velocity *= max(0.45, 1.0 - 0.06 * mass_ratio)

    # ---------------- police ----------------
    def update_pursuit_agency(self):
        """Confirm a city-line crossing, then hand the same chase to new units."""
        center = self.active_rect().center
        agency = police_jurisdiction_at(center[0] // TILE_SIZE,
                                        center[1] // TILE_SIZE)
        if self.wanted_level <= 0:
            self.pursuit_agency = agency
            self.pending_pursuit_agency = agency
            self.jurisdiction_timer = 0
            return False
        if agency == self.pursuit_agency:
            self.pending_pursuit_agency = agency
            self.jurisdiction_timer = 0
            return False
        if agency != self.pending_pursuit_agency:
            self.pending_pursuit_agency = agency
            self.jurisdiction_timer = 1
            return False
        self.jurisdiction_timer += 1
        if self.jurisdiction_timer < JURISDICTION_CONFIRM_STEPS:
            return False
        self.pursuit_agency = agency
        self.jurisdiction_timer = 0
        self.police = []
        self.foot_police = []
        self.roadblocks = []
        self.cop_dispatch = max(self.cop_dispatch, FPS // 2)
        label = "COUNTY TAKES IT" if agency == 'county' else "CITY HAS IT"
        self.add_callout(label, hud_HUD_GOLD, ttl=FPS, scale=1,
                         tag='jurisdiction')
        self.add_toast("Dispatch: that's yours now. Negative, they crossed back.")
        return True

    def cop_spawn_point(self, agency=None):
        """A road tile off-screen but within reach, so cops actually arrive.

        Every cop used to spawn at the downtown station regardless of where the
        player was, which on a 6400px map meant they spent the whole (6 second)
        wanted timer driving toward a chase that had already ended.
        """
        active = self.active_rect()
        for _ in range(60):
            ang = random.uniform(0, math.tau)
            dist = random.uniform(COP_SPAWN_MIN, COP_SPAWN_MAX)
            x = active.centerx + math.cos(ang) * dist
            y = active.centery + math.sin(ang) * dist
            col, row = int(x) // TILE_SIZE, int(y) // TILE_SIZE
            if not (2 <= col < MAP_TILES_W - 2 and 2 <= row < MAP_TILES_H - 2):
                continue
            if tile_type_at(col, row) != TILE_ROAD:
                continue
            if agency is not None and police_jurisdiction_at(col, row) != agency:
                continue
            spot = free_point_near(col * TILE_SIZE + TILE_SIZE // 2,
                                   row * TILE_SIZE + TILE_SIZE // 2,
                                   VEHICLE_DEFAULT_W, VEHICLE_DEFAULT_H, max_rings=1)
            if spot is not None and self.spot_is_free(*spot):
                return spot
        if agency in (None, 'city') and self.spot_is_free(*self.police_station):
            return self.police_station
        return None

    def cop_can_see(self, cop, target, fov=None):
        """Can this cruiser actually see the player right now?

        Three gates, cheapest first: range, then a forward cone (you can slip
        in behind a cop that has driven past you), then a wall check. Anything
        very close counts regardless of facing - they can hear you.
        """
        dx = target[0] - cop.rect.centerx
        dy = target[1] - cop.rect.centery
        dist = math.hypot(dx, dy)
        if dist > cop.sight_range:
            return False
        if dist > COP_SIGHT_CLOSE:
            bearing = (math.atan2(dy, dx) - cop.angle + math.pi) % math.tau - math.pi
            if abs(bearing) > (COP_SIGHT_FOV if fov is None else fov):
                return False
        return not sight_blocked(cop.rect.centerx, cop.rect.centery,
                                 target[0], target[1])

    def hide_scale(self):
        """How fast heat drains while hidden. Under the span of the Gateway
        Arch it drains twice again - the map's anchor should be mechanically
        special, and it is where you respawn, so you learn it immediately."""
        if landmark_at(self.player_rect) == "Gateway Arch":
            return HIDE_ARCH_SCALE
        return HIDE_DECAY_SCALE

    def update_hiding(self):
        """Latch the HIDDEN state: still, unseen, and off the street.

        This is the mechanic the chase was missing. Sprinting down the middle
        of Market Street does not lose anybody; ducking into a gangway off The
        Hill and standing dead still for a second does - and so does sitting
        in a parked car with the engine off while a cruiser goes by, which is
        the driving layer's own version of the same move.
        """
        if self.spotted:
            self.hide_timer = 0
            self.hidden = False
            return
        if self.driving is not None:
            # Sat in a car, off the gas, going nowhere.
            if abs(self.driving.velocity) > 0.5 or self.driving.input_throttle:
                self.hide_timer = 0
                self.hidden = False
                return
            self.hide_timer += 1
            if self.hide_timer >= HIDE_CAR_STEPS and not self.hidden:
                self.hidden = True
                if self.wanted_level > 0:
                    self.add_callout("HIDDEN", hud_HUD_GOLD, scale=1)
            return
        moving = math.hypot(self.player_dir[0], self.player_dir[1]) * PLAYER_SPEED
        if moving > HIDE_STILL_SPEED or not in_cover(self.player_rect.centerx,
                                                    self.player_rect.centery):
            self.hide_timer = 0
            self.hidden = False
            return
        self.hide_timer += 1
        if self.hide_timer >= HIDE_ARM_STEPS and not self.hidden:
            self.hidden = True
            if self.wanted_level > 0:
                self.add_callout("HIDDEN", hud_HUD_GOLD, scale=1)

    def dispatch_target(self):
        """Where a freshly dispatched unit should be told to go.

        The crime scene while it is fresh, otherwise wherever anyone still
        has eyes on you, otherwise your current position as a last resort.
        """
        if (self.crime_pos is not None
                and self.frame - self.crime_frame < CRIME_SCENE_STALE):
            return self.crime_pos
        for unit in list(self.police) + list(self.foot_police):
            if unit.alert == 'chase' and unit.last_seen is not None:
                return unit.last_seen
        return self.active_rect().center

    def update_foot_police(self, star, active, active_c):
        """Beat cops: the only unit that can complete an arrest on foot."""
        want = COP_FOOT_BY_STAR[star]
        if self.foot_cop_respawn > 0:
            self.foot_cop_respawn -= 1
        while len(self.foot_police) < want and self.foot_cop_respawn <= 0:
            aim = self.dispatch_target()
            spot = ring_spawn_near(aim[0], aim[1], rmin=330, rmax=620)
            if spot is None:
                spot = free_point_near(aim[0], aim[1], 14, 14, max_rings=8)
            if spot is None:
                break
            cop = FootCop(*spot)
            cop.last_seen = aim
            cop.search_timer = COP_FOOT_GIVEUP
            self.foot_police.append(cop)
        while len(self.foot_police) > want:
            self.foot_police.pop()

        seen = False
        touching = False
        for cop in self.foot_police:
            if cop.tick_hit_state():
                cop.move_speed = COP_FOOT_SEARCH_SPEED
                continue
            cop.sight_range = COP_FOOT_SIGHT
            if self.cop_can_see(cop, active_c, fov=COP_FOOT_FOV):
                if cop.alert != 'chase':
                    cop.chase_steps = 0
                else:
                    cop.chase_steps += 1
                cop.alert = 'chase'
                cop.last_seen = active_c
                cop.search_timer = COP_FOOT_GIVEUP
                cop.lost_timer = 0
                cop.move_speed = (COP_FOOT_BURST_SPEED
                                  if cop.chase_steps < COP_FOOT_BURST_STEPS
                                  else COP_FOOT_CHASE_SPEED)
                seen = True
            else:
                cop.chase_steps = 0
                cop.lost_timer += 1
                cop.search_timer -= 1
                if cop.alert == 'chase':
                    cop.alert = 'search'
                cop.move_speed = COP_FOOT_SEARCH_SPEED
                if cop.search_timer <= 0 or cop.last_seen is None:
                    cop.last_seen = self.cop_search_point(cop)
                    cop.search_timer = COP_FOOT_GIVEUP // 2
            cop.step_toward(cop.last_seen or active_c)
            if cop.alert == 'chase' and cop.rect.colliderect(active.inflate(2, 2)):
                touching = True
        return seen, touching

    def pursuit_heading(self):
        """Unit vector describing where a containment point belongs."""
        if self.driving is not None:
            angle = self.driving.angle
            if self.driving.velocity < -0.2:
                angle += math.pi
            return pygame.Vector2(math.cos(angle), math.sin(angle))
        motion = pygame.Vector2(self.player_dir)
        if motion.length_squared() > 0:
            return motion.normalize()
        return pygame.Vector2(math.cos(self.player_aim), math.sin(self.player_aim))

    @staticmethod
    def roadblock_layout(cx, cy, orientation):
        """Collision geometry for a complete two-car closure at ``cx, cy``."""
        if orientation == 'horizontal':
            strip = pygame.Rect(0, 0, ROADBLOCK_STRIP_THICK, ROADBLOCK_STRIP_LONG)
            strip.center = (cx, cy)
            cars = ((cx - 34, cy - 15, 0.0), (cx + 34, cy + 15, math.pi))
        else:
            strip = pygame.Rect(0, 0, ROADBLOCK_STRIP_LONG, ROADBLOCK_STRIP_THICK)
            strip.center = (cx, cy)
            cars = ((cx - 15, cy - 34, math.pi / 2),
                    (cx + 15, cy + 34, -math.pi / 2))
        return strip, cars

    def roadblock_spawn_point(self, slot=0):
        """Best deterministic, legal road closure ahead of the player.

        Every road tile in the forward envelope is scored by lateral miss and
        distance from the slot's preferred range. Intersections are excluded so
        the strip has an unambiguous road axis, and the complete strip plus both
        cruiser colliders must fit before a candidate can win.
        """
        origin = pygame.Vector2(self.active_rect().center)
        heading = self.pursuit_heading()
        preferred = ROADBLOCK_PREFERRED[min(slot, len(ROADBLOCK_PREFERRED) - 1)]
        candidates = []
        for row in range(2, MAP_TILES_H - 2):
            for col in range(2, MAP_TILES_W - 2):
                tile = GAME_MAP[row][col]
                if tile['type'] != TILE_ROAD or tile['collidable']:
                    continue
                if police_jurisdiction_at(col, row) != self.pursuit_agency:
                    continue
                horizontal = row in ROAD_LINES and col not in ROAD_LINES
                vertical = col in ROAD_LINES and row not in ROAD_LINES
                if not horizontal and not vertical:
                    continue
                road_dir = pygame.Vector2(1, 0) if horizontal else pygame.Vector2(0, 1)
                if abs(road_dir.dot(heading)) < 0.48:
                    continue
                center = pygame.Vector2(col * TILE_SIZE + TILE_SIZE // 2,
                                        row * TILE_SIZE + TILE_SIZE // 2)
                rel = center - origin
                ahead = rel.dot(heading)
                if not ROADBLOCK_AHEAD_MIN <= ahead <= ROADBLOCK_AHEAD_MAX:
                    continue
                lateral = abs(rel.cross(heading))
                orientation = 'horizontal' if horizontal else 'vertical'
                score = lateral * 2.2 + abs(ahead - preferred)
                candidates.append((score, row, col, orientation, center))

        occupied = list(self.cars) + list(self.police)
        if self.driving is not None:
            occupied = [car for car in occupied if car is not self.driving]
        for _score, _row, _col, orientation, center in sorted(candidates,
                                                               key=lambda item: item[:3]):
            cx, cy = int(center.x), int(center.y)
            if any(math.hypot(cx - block['center'][0], cy - block['center'][1]) < 210
                   for block in self.roadblocks):
                continue
            strip, specs = self.roadblock_layout(cx, cy, orientation)
            if is_blocked(strip) or not pygame.Rect(0, 0, MAP_WIDTH, MAP_HEIGHT).contains(strip):
                continue
            unit_rects = []
            legal = True
            for ux, uy, _angle in specs:
                rect = pygame.Rect(0, 0, VEHICLE_DEFAULT_W, VEHICLE_DEFAULT_H)
                rect.center = (ux, uy)
                if is_blocked(rect) or not pygame.Rect(0, 0, MAP_WIDTH, MAP_HEIGHT).contains(rect):
                    legal = False
                    break
                unit_rects.append(rect)
            if not legal:
                continue
            # Do not materialise on a moving entity. This does not affect the
            # deterministic road score; it only advances to the next legal tile.
            if any(rect.colliderect(car.rect.inflate(8, 8))
                   for rect in unit_rects for car in occupied):
                continue
            return (cx, cy, orientation, strip, specs)
        return None

    def deploy_roadblock(self, slot=0):
        placement = self.roadblock_spawn_point(slot)
        if placement is None:
            return False
        cx, cy, orientation, strip, specs = placement
        units = []
        for ux, uy, angle in specs:
            unit = Car(ux, uy, color=POLICE_COLOR, variant='police')
            unit.police_agency = self.pursuit_agency
            unit.angle = angle
            unit.velocity = 0.0
            unit.driver = 'roadblock'
            unit.parked = True
            units.append(unit)
        self.roadblock_serial += 1
        self.roadblocks.append({
            'center': (cx, cy), 'orientation': orientation, 'strip': strip,
            'cars': units, 'serial': self.roadblock_serial,
            'spawn_frame': self.frame, 'last_hit': -10 ** 9,
            'last_impact': -10 ** 9,
        })
        self.add_callout("ROADBLOCK AHEAD", hud_HUD_RED, ttl=FPS, scale=1,
                         tag='roadblock')
        return True

    def update_roadblocks(self, star):
        """Maintain the star-indexed containment quota and redeploy passed blocks."""
        target = ROADBLOCK_COUNT_BY_STAR[star]
        if target <= 0:
            self.roadblocks = []
            self.roadblock_deploy_after = self.frame
            return
        if self.driving is None:
            return

        heading = self.pursuit_heading()
        origin = pygame.Vector2(self.driving.rect.center)
        kept = []
        retired = False
        for block in self.roadblocks:
            rel = pygame.Vector2(block['center']) - origin
            far_behind = (rel.length() > ROADBLOCK_RETIRE_DISTANCE
                          and rel.dot(heading) < -ROADBLOCK_RETIRE_BEHIND)
            too_far = rel.length() > ROADBLOCK_AHEAD_MAX + ROADBLOCK_RETIRE_DISTANCE
            if far_behind or too_far:
                retired = True
            else:
                kept.append(block)
        self.roadblocks = kept[:target]
        if retired:
            self.roadblock_deploy_after = max(
                self.roadblock_deploy_after,
                self.frame + ROADBLOCK_REDEPLOY_BY_STAR[star])

        seen_target = getattr(self, 'roadblock_target_seen', 0)
        if target > seen_target:
            self.roadblock_deploy_after = min(self.roadblock_deploy_after, self.frame)
        self.roadblock_target_seen = target
        if len(self.roadblocks) < target and self.frame >= self.roadblock_deploy_after:
            if self.deploy_roadblock(len(self.roadblocks)):
                self.roadblock_deploy_after = (
                    self.frame + ROADBLOCK_REDEPLOY_BY_STAR[star])
            else:
                self.roadblock_deploy_after = self.frame + FPS

    def update_roadblock_contacts(self):
        """Resolve spike and parked-unit contact against the player car."""
        car = self.driving
        if car is None:
            return
        speed = abs(car.velocity)
        for block in self.roadblocks:
            if (speed >= 0.6 and car.spike_cd <= 0
                    and car.rect.colliderect(block['strip'])):
                car.spike_cd = ROADBLOCK_HIT_COOLDOWN
                car.puncture_steps = max(car.puncture_steps, SPIKE_PUNCTURE_STEPS)
                car.hp = max(1.0, car.hp - SPIKE_DAMAGE)
                car.velocity *= SPIKE_ENTRY_SPEED_SCALE
                car.vlat += 0.9 if block['serial'] % 2 else -0.9
                block['last_hit'] = self.frame
                self.kick(4.0, freeze=1)
                self.spawn_burst(car.rect.center, 9, ('spark', 'debris'), 2.4)
                self.play_impact(car.rect.center, max(4.0, speed), gap=15)
                self.add_callout("TIRES SHREDDED", hud_HUD_RED, ttl=FPS * 2,
                                 scale=2, tag='spikes')
                self.add_toast("SPIKE STRIP - SPEED AND STEERING CRIPPLED")

            for unit in block['cars']:
                if not car.rect.colliderect(unit.rect):
                    continue
                overlap = car.rect.clip(unit.rect)
                if overlap.width <= overlap.height:
                    dx = -(overlap.width + 1) if car.rect.centerx < unit.rect.centerx else overlap.width + 1
                    candidate = car.rect.move(dx, 0)
                else:
                    dy = -(overlap.height + 1) if car.rect.centery < unit.rect.centery else overlap.height + 1
                    candidate = car.rect.move(0, dy)
                if (pygame.Rect(0, 0, MAP_WIDTH, MAP_HEIGHT).contains(candidate)
                        and not is_blocked(candidate)):
                    car.rect.topleft = candidate.topleft
                if speed > 1.0 and self.frame - block['last_impact'] >= ROADBLOCK_HIT_COOLDOWN:
                    block['last_impact'] = self.frame
                    car.crash_damage(min(18.0, speed * PLAYER_RAM_DAMAGE))
                    car.velocity *= -0.20
                    car.vlat *= 0.35
                    self.kick(min(5.5, speed), freeze=1)
                    self.spawn_burst(car.rect.center, 6, ('spark', 'glass'), 2.0)
                    self.play_impact(car.rect.center, speed, gap=12)

    def update_police(self):
        self.update_pursuit_agency()
        star = min(self.wanted_level, WANTED_MAX)
        target_count = COP_COUNT_BY_STAR[star]
        active = self.active_rect()
        active_c = active.center
        self.update_roadblocks(star)
        self.update_roadblock_contacts()

        # Dispatch delay: a fresh star no longer materialises a cruiser on top
        # of you. At one star the call has to go out first.
        if len(self.police) < target_count:
            if self.cop_dispatch > 0:
                self.cop_dispatch -= 1
            else:
                spot = self.cop_spawn_point(self.pursuit_agency)
                if spot is None:
                    # Every off-screen approach is occupied this frame. Wait
                    # briefly instead of materialising a cruiser inside a car.
                    self.cop_dispatch = FPS // 2
                else:
                    sx, sy = spot
                    cop = Car(sx, sy, color=POLICE_COLOR, variant='police')
                    cop.police_agency = self.pursuit_agency
                    cop.driver = 'police'
                    # Cops used to spawn with Car.__init__'s random heading *and*
                    # a random civilian body, so a patrol car could arrive as a
                    # blue school bus pointed the wrong way. Now: a cruiser
                    # pointed at the address the call came from.
                    aim = self.dispatch_target()
                    cop.angle = math.atan2(aim[1] - sy, aim[0] - sx)
                    cop.last_seen = aim
                    cop.search_timer = COP_SEARCH_STEPS
                    self.police.append(cop)
                    self.cop_dispatch = COP_RESPONSE_BY_STAR[star]
        while len(self.police) > target_count:
            self.police.pop()

        # Is the player conspicuous enough to be called in? A car being driven
        # hard down a street is; a stopped one, or anyone who has gone to
        # ground, is not.
        radio = (self.driving is not None and not self.hidden
                 and abs(self.driving.velocity) >= COP_RADIO_SPEED)

        touching = False
        seen = False
        searching = False
        for cop in self.police:
            cop.max_speed = COP_SPEED_BY_STAR[star]
            if radio and math.hypot(cop.rect.centerx - active_c[0],
                                    cop.rect.centery - active_c[1]) > COP_RADIO_RANGE:
                radio_this = False
            else:
                radio_this = radio
            if self.grub_active('provel'):
                # A wheel of provel under a cruiser. It is not a cheese, it is
                # a lubricant, and everyone from here knows it.
                cop.max_speed *= GRUB_COP_GRIP
            cop.sight_range = COP_SIGHT_BY_STAR[star]
            if self.cop_can_see(cop, active_c, fov=COP_FOV_BY_STAR[star]):
                cop.alert = 'chase'
                cop.last_seen = active_c
                cop.search_timer = COP_SEARCH_STEPS
                cop.lost_timer = 0
                seen = True
            else:
                cop.lost_timer += 1
                cop.search_timer -= 1
                if cop.alert == 'chase':
                    cop.alert = 'search'
                if radio_this and self.frame % COP_RADIO_STEPS == 0:
                    # Called in over the air rather than seen: a fix good
                    # enough to keep the pursuit alive across a few blocks,
                    # never good enough to be the same as eyes on you.
                    cop.last_seen = active_c
                    cop.search_timer = COP_SEARCH_STEPS
                elif cop.search_timer <= 0 or cop.last_seen is None:
                    # Given up on that spot. Cast around it rather than
                    # beelining somewhere it has no reason to go.
                    cop.last_seen = self.cop_search_point(cop)
                    cop.search_timer = COP_SEARCH_STEPS // 2
                searching = True

            aim = cop.last_seen or active_c
            # Below COP_RAMMING_STAR a cruiser is trying to arrest you, not
            # kill you: it eases off well short of a pedestrian.
            brake_at = 34 if (star >= COP_RAMMING_STAR or self.driving) else 52
            cop.chase_ai(aim, brake_at=brake_at)
            # A cruiser can pin a stopped car, but it cannot reach through the
            # windshield or magically handcuff somebody standing on a sidewalk.
            if self.driving is not None and cop.rect.colliderect(active.inflate(4, 4)):
                touching = True

        foot_seen, foot_touch = self.update_foot_police(star, active, active_c)
        seen = seen or foot_seen
        touching = touching or foot_touch
        searching = searching or any(c.alert != 'chase' for c in self.foot_police)

        self.spotted = seen
        self.searching = searching and not seen
        self.update_hiding()
        if self.wanted_level > 0:
            self.chase_steps += 1
            self.longest_chase = max(self.longest_chase, self.chase_steps)
        else:
            self.chase_steps = 0

        # A single frame of contact used to bust you instantly. Now the cops
        # have to hold you for ~0.9s, so shaking one off in a scrape is a real
        # skill rather than a coin flip - and they can only do it to a car
        # that has actually been stopped. Trading paint at speed is a wreck in
        # progress, not an arrest.
        if self.driving is not None and abs(self.driving.velocity) > BUST_MAX_SPEED:
            touching = False
        if touching and self.state == STATE_PLAYING:
            self.bust_meter += 1
            if self.bust_meter >= BUST_CONTACT_STEPS:
                self.busted()
        else:
            self.bust_meter = max(0, self.bust_meter - BUST_RELIEF)

        # Heat only holds while somebody can actually *see* you. Sitting on the
        # far side of a brick two-flat from a cruiser is not being caught.
        if seen:
            self.heat_timer = 0
        self.was_spotted = seen

    def cop_search_point(self, cop):
        """Somewhere plausible for a cop that has lost you to go and look."""
        base = cop.last_seen or cop.rect.center
        for _ in range(12):
            ang = random.uniform(0, math.tau)
            dist = random.uniform(COP_SEARCH_WANDER * 0.4, COP_SEARCH_WANDER)
            x = base[0] + math.cos(ang) * dist
            y = base[1] + math.sin(ang) * dist
            col, row = int(x) // TILE_SIZE, int(y) // TILE_SIZE
            if not (2 <= col < MAP_TILES_W - 2 and 2 <= row < MAP_TILES_H - 2):
                continue
            if tile_type_at(col, row) == TILE_ROAD:
                return (x, y)
        return base

    def busted(self):
        """Booked and released at the station, minus bail.

        The old version teleported you to a random tile anywhere on a 100x100
        map, which meant every bust also destroyed your sense of where you
        were. You now come out of the station you were taken to.
        """
        if self.state == STATE_DEAD:
            return
        if self.arch_job_phase in ARCH_ACTIVE_PHASES:
            self.fail_arch_job("Evidence impounded. The Arch job can wait.")
        # Bail scales with how hot you were when they took you, so a five-star
        # bust is a real loss and running is worth something.
        bail = min(BAIL_MAX_LOSS,
                   BAIL_BY_STAR[min(self.peak_star, WANTED_MAX)])
        from_hand = min(self.cash, bail)
        self.cash -= from_hand
        from_bank = min(self.banked, bail - from_hand)
        self.banked -= from_bank
        bail = from_hand + from_bank
        self.busted_flash = FPS * 2
        if self.driving:
            self.driving.driver = None
            self.driving.parked = True
            traffic_hand_back(self.driving)
            self.driving = None
        if self.job is not None and self.job.collected:
            self.fail_job("Cargo impounded")
        self.enter_death('busted', f"BAIL ${bail}")

    def update_wanted_decay(self):
        """Stars only fall once you are genuinely clear.

        Previously the level dropped one star every 6 seconds no matter what,
        so the correct play against the police was to stop the car and wait.
        The timer now resets whenever a cop is near you (see update_police) or
        you commit a fresh offence, so you have to actually break line of
        sight and put distance between you and them.
        """
        if self.wanted_level <= 0:
            self.heat_timer = 0
            self.wanted_decay_timer = 0
            return
        # Hiding is worth something concrete: cover skips most of the grace
        # period and then sheds stars several times faster than walking away.
        gain = self.hide_scale() if self.hidden else 1.0
        grace = HEAT_GRACE // 3 if self.hidden else HEAT_GRACE
        self.heat_timer += 1
        if self.heat_timer < grace:
            return
        self.wanted_decay_timer += gain
        if self.wanted_decay_timer >= WANTED_DECAY_BY_STAR[self.wanted_level]:
            self.wanted_decay_timer = 0
            peak = self.peak_star
            self.wanted_level = max(0, self.wanted_level - 1)
            if self.wanted_level < 4:
                self.roadblocks = []
                self.roadblock_deploy_after = self.frame
            # Shed a cop with the star, this same step, so the police count
            # never disagrees with the star display even for one frame. (A far
            # cop that update_police wouldn't trim on count alone.)
            trimmed = COP_COUNT_BY_STAR[self.wanted_level]
            while len(self.police) > trimmed:
                self.police.pop()
            if self.wanted_level == 0:
                # Shedding five stars used to pay the same flat 100 as losing a
                # single beat cop - less than running over twenty people. The
                # payout is now squared in the heat you actually shook.
                self.foot_police = []
                self.add_callout("LOST 'EM", hud_HUD_GOLD, scale=2)
                self.add_score(100 * max(1, peak) ** 2,
                               self.active_rect().center, mult=False)
                where = landmark_at(self.active_rect())
                self.add_toast(f"Lost 'em in {where}" if where else "Lost 'em")

    HOOD_BANNER_STEPS = FPS * 3

    def update_place_names(self):
        """Track the neighbourhood and street under the player.

        Crossing into a new neighbourhood raises a short title, GTA-style.
        The street name updates quietly under the radar.
        """
        rect = self.active_rect()
        col, row = rect.centerx // TILE_SIZE, rect.centery // TILE_SIZE
        hood = hood_at(col, row)
        if hood != self.hood_now:
            if self.hood_now is not None:
                self.hood_banner = self.HOOD_BANNER_STEPS
            self.hood_now = hood
        elif self.hood_banner > 0:
            self.hood_banner -= 1
        name = street_name(col, row)
        if name is not None:
            self.street_now = name

    def check_landmark_discovery(self):
        name = landmark_at(self.active_rect())
        if name and name not in self.discovered:
            self.discovered.add(name)
            self.add_score(150, self.active_rect().center, mult=False)
            self.add_callout("NEW TURF", hud_HUD_GOLD, scale=1)
            self.add_toast(f"Discovered: {name}!")
            plaque = LANDMARK_PLAQUES.get(name)
            if plaque:
                self.add_toast(plaque)

    def local_legend_car(self, variant):
        return next((car for car in self.cars if car.variant == variant), None)

    def local_legend_marker(self, variant):
        """Exact after discovery; a deliberately fuzzy venue rumor before it."""
        info = LOCAL_LEGENDS[variant]
        car = self.local_legend_car(variant)
        if variant in self.legend_discovered and car is not None:
            return car.rect.center
        entry = next(item for item in LANDMARKS if item[5] == info['venue'])
        x, y = landmark_dropoff_point(entry)
        ox, oy = info['offset']
        return int(x + ox), int(y + oy)

    def update_local_legends(self):
        """Deal sparse rumors and recognize a rare ride before it is entered."""
        pending = [kind for kind, _venue in SHOWCASE_VEHICLES
                   if kind not in self.legend_rumors]
        if pending and self.frame >= self.legend_hint_after:
            kind = pending[0]
            self.legend_rumors.add(kind)
            self.legend_hint_after = self.frame + LOCAL_LEGEND_HINT_GAP
            self.add_callout("LOCAL LEGEND RUMOR", LOCAL_LEGENDS[kind]['color'],
                             ttl=FPS * 2, scale=1)
            self.add_toast(LOCAL_LEGENDS[kind]['rumor'])

        center = self.active_rect().center
        for kind in LOCAL_LEGENDS:
            if kind in self.legend_discovered:
                continue
            car = self.local_legend_car(kind)
            if car is None or math.dist(center, car.rect.center) > LOCAL_LEGEND_DISCOVERY_RADIUS:
                continue
            self.legend_rumors.add(kind)
            self.legend_discovered.add(kind)
            info = LOCAL_LEGENDS[kind]
            self.add_score(500, car.rect.center, mult=False)
            self.add_callout(info['name'], info['color'], ttl=FPS * 2, scale=2)
            self.add_toast(f"Local Legend discovered near {info['venue']}")

        # The first painted hydrant is the start line, not background clutter.
        if ('hill_hydrants' not in self.legend_mastery
                and self.local_challenge is None and self.driving is None):
            hydrants = self.hill_hydrant_positions()
            nearest = min((math.dist(center, point), point) for point in hydrants)
            if nearest[0] <= 34:
                self.start_local_challenge('hill_hydrants', first=nearest[1])
            elif self.hood_now == 'hill' and not self.hill_hint_shown:
                self.hill_hint_shown = True
                self.add_toast("The Hill challenge: follow the painted hydrants on foot")

    @staticmethod
    def tile_route_points(tiles):
        return [(c * TILE_SIZE + TILE_SIZE // 2,
                 r * TILE_SIZE + TILE_SIZE // 2) for c, r in tiles]

    @staticmethod
    def hill_hydrant_positions():
        return [(c * TILE_SIZE + ox, r * TILE_SIZE + oy)
                for (c, r), (ox, oy) in HILL_HYDRANT_TILES.items()]

    def start_local_challenge(self, kind, first=None):
        if self.local_challenge is not None or kind in self.legend_mastery:
            return False
        if (self.side_mission is not None
                or (self.job is not None and self.job.collected)
                or self.arch_job_phase in ARCH_ACTIVE_PHASES):
            return False
        # An unaccepted dispatcher card is only an offer. Park it while the
        # local activity owns the objective HUD, then deal a fresh one after.
        if self.job is not None:
            self.job = None
            self.job_cooldown = 0
        challenge = {
            'kind': kind,
            'steps_left': LOCAL_CHALLENGE_TIMES[kind],
            'time_limit': LOCAL_CHALLENGE_TIMES[kind],
            'index': 0,
        }
        if kind == 'mudfoot':
            car = self.local_legend_car('mudfoot')
            if car is None:
                return False
            targets = []
            for ox, oy in MUDFOOT_SCRAP_OFFSETS:
                want = (car.rect.centerx + ox, car.rect.centery + oy)
                rect = pygame.Rect(0, 0, 34, 16)
                rect.center = want
                if is_blocked(rect):
                    spot = free_point_near(*want, rect.w, rect.h, max_rings=3,
                                           require_reachable=False)
                    if spot is not None:
                        rect.center = spot
                targets.append({'rect': rect, 'hit': False})
            challenge['targets'] = targets
            head, sub = "BIGFOOT'S FIRST CRUSH", "FLATTEN 5 JUNK CARS"
        elif kind == 'grocery_cart':
            challenge['points'] = self.tile_route_points(CART_SLALOM_TILES)
            challenge['last_hp'] = self.driving.hp if self.driving else 0.0
            head, sub = "THE BIG CART SLALOM", "KEEP THE GROCERIES IN"
        elif kind == 'trash_day':
            challenge['points'] = self.tile_route_points(TRASH_DAY_TILES)
            head, sub = "TRASH DAY", "EMPTY 6 ALLEY DUMPSTERS"
        elif kind == 'chain_escape':
            if self.driving is not self.chain_bike:
                return False
            challenge['points'] = self.tile_route_points(CHAIN_ESCAPE_TILES)
            head, sub = "CHAIN OF ROCKS RUN", "BIKES FIT WHERE CRUISERS DON'T"
        else:
            points = self.hill_hydrant_positions()
            if first in points:
                at = points.index(first)
                points = points[at:] + points[:at]
                challenge['index'] = 1
            challenge['points'] = points
            head, sub = "THE HILL HYDRANT CIRCUIT", "FOLLOW GREEN WHITE AND RED"
        self.local_challenge = challenge
        self.add_callout(head, LOCAL_CHALLENGE_COLORS[kind], ttl=FPS * 2, scale=1)
        self.add_toast(sub)
        return True

    def finish_local_challenge(self):
        challenge = self.local_challenge
        if challenge is None:
            return
        kind = challenge['kind']
        self.legend_mastery.add(kind)
        if kind == 'chain_escape':
            self.wanted_level = 0
            self.police = []
            self.foot_police = []
            self.roadblocks = []
            self.add_callout("CROSSED THE MISSISSIPPI", hud_HUD_GREEN,
                             ttl=FPS * 2, scale=1)
        self.cash += LOCAL_CHALLENGE_REWARD
        self.add_score(750, self.active_rect().center, mult=False)
        self.add_callout("LOCAL LEGEND MASTERED", hud_HUD_GOLD, ttl=FPS * 2, scale=2)
        self.add_toast(f"${LOCAL_CHALLENGE_REWARD}  Garage medal earned")
        self.local_challenge = None
        if self.job is None:
            self.job_cooldown = max(self.job_cooldown, FPS)

    def fail_local_challenge(self, reason):
        if self.local_challenge is None:
            return
        self.add_callout("LOCAL CHALLENGE FAILED", hud_HUD_RED, ttl=FPS, scale=1)
        self.add_toast(reason)
        self.local_challenge = None
        if self.job is None:
            self.job_cooldown = max(self.job_cooldown, FPS)

    def local_challenge_marker(self):
        challenge = self.local_challenge
        if challenge is None:
            return None
        if challenge['kind'] == 'mudfoot':
            target = next((item for item in challenge['targets'] if not item['hit']), None)
            return target['rect'].center if target else None
        points = challenge.get('points', ())
        index = challenge.get('index', 0)
        return points[index] if index < len(points) else None

    def local_challenge_hud(self):
        challenge = self.local_challenge
        if challenge is None:
            return None
        kind = challenge['kind']
        if kind == 'mudfoot':
            done = sum(item['hit'] for item in challenge['targets'])
            text = f"CRUSH JUNK CARS {done}/{len(challenge['targets'])}"
            head = "BIGFOOT'S FIRST CRUSH"
        else:
            done = challenge['index']
            total = len(challenge['points'])
            text = f"CHECKPOINTS {done}/{total}"
            head = {'grocery_cart': "THE BIG CART SLALOM",
                    'trash_day': "TRASH DAY",
                    'hill_hydrants': "THE HILL HYDRANTS",
                    'chain_escape': "CHAIN OF ROCKS RUN"}[kind]
        return head, text, challenge['steps_left'], challenge['time_limit']

    def update_local_challenge(self):
        challenge = self.local_challenge
        if challenge is None:
            return
        challenge['steps_left'] -= 1
        if challenge['steps_left'] <= 0:
            self.fail_local_challenge("Time's up")
            return
        kind = challenge['kind']
        if kind == 'mudfoot':
            if self.driving is None or self.driving.variant != 'mudfoot':
                return
            if abs(self.driving.velocity) < 1.8:
                return
            for target in challenge['targets']:
                if target['hit'] or not self.driving.rect.colliderect(target['rect']):
                    continue
                target['hit'] = True
                self.spawn_burst(target['rect'].center, 12, ('spark', 'debris'), 3.4)
                self.play_impact(target['rect'].center, 7.0, gap=2)
                done = sum(item['hit'] for item in challenge['targets'])
                self.add_callout(f"CRUSHED {done}/{len(challenge['targets'])}",
                                 LOCAL_CHALLENGE_COLORS[kind], ttl=FPS, scale=1)
            if all(item['hit'] for item in challenge['targets']):
                self.finish_local_challenge()
            return

        required = {'grocery_cart': 'grocery_cart', 'trash_day': 'garbage_truck',
                    'chain_escape': 'vespa'}.get(kind)
        if required is not None and (self.driving is None or self.driving.variant != required):
            return
        if kind == 'hill_hydrants' and self.driving is not None:
            return
        if kind == 'grocery_cart' and self.driving is not None:
            hp = self.driving.hp
            if hp < challenge.get('last_hp', hp) - 1.0 and challenge['index']:
                challenge['index'] = 0
                self.add_callout("GROCERIES EVERYWHERE", hud_HUD_RED, ttl=FPS, scale=1)
            challenge['last_hp'] = hp
        marker = self.local_challenge_marker()
        if marker is None or math.dist(self.active_rect().center, marker) > 44:
            return
        challenge['index'] += 1
        done, total = challenge['index'], len(challenge['points'])
        self.add_callout(f"{done}/{total}", LOCAL_CHALLENGE_COLORS[kind], ttl=FPS, scale=1)
        if done >= total:
            self.finish_local_challenge()

    # ---------------- drawing ----------------
    _TREE_GREENS = ((58, 84, 46), (50, 74, 40), (66, 92, 52), (46, 66, 38))

    def _draw_street_tree(self, cx, cy, variant):
        """A small boulevard tree: SE shadow blob, canopy, a fleck of highlight."""
        canopy = self._TREE_GREENS[variant % len(self._TREE_GREENS)]
        pygame.draw.circle(self.screen, COLOR_TREE_SHADOW, (cx + 4, cy + 5), 10)
        pygame.draw.circle(self.screen, (48, 38, 30), (cx, cy + 6), 2)          # trunk
        pygame.draw.circle(self.screen, canopy, (cx, cy), 9)
        pygame.draw.circle(self.screen, _blend(canopy, (255, 255, 255), 0.22), (cx - 3, cy - 3), 3)

    def draw_tile(self, c, r):
        """Flat terrain: asphalt, sidewalks, markings, parks, water."""
        tile = GAME_MAP[r][c]
        rect = self.camera.apply(pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE))
        t = tile['type']

        if tile.get('des_peres'):
            pygame.draw.rect(self.screen, (106, 110, 108), rect)
            pygame.draw.line(self.screen, (70, 74, 76), rect.topleft,
                             rect.topright, 3)
            pygame.draw.line(self.screen, (70, 74, 76), rect.bottomleft,
                             rect.bottomright, 3)
            pygame.draw.line(self.screen, (54, 82, 88),
                             (rect.left, rect.centery),
                             (rect.right, rect.centery), 4)
            pygame.draw.line(self.screen, (142, 146, 142),
                             (rect.left, rect.centery - 12),
                             (rect.right, rect.centery - 12), 1)
            return

        if tile.get('chain_of_rocks'):
            pygame.draw.rect(self.screen, (64, 78, 76), rect)
            pygame.draw.line(self.screen, (198, 184, 142), rect.topleft,
                             rect.topright, 3)
            pygame.draw.line(self.screen, (198, 184, 142), rect.bottomleft,
                             rect.bottomright, 3)
            pygame.draw.line(self.screen, (230, 202, 98),
                             (rect.left, rect.centery),
                             (rect.right, rect.centery), 1)
            return

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
            # boulevard tree: kerbside sidewalk tiles, deterministic ~1 in 4
            if tile['landmark'] is None and n % 4 == 0 and (
                    tile_type_at(c, r + 1) == TILE_ROAD or tile_type_at(c, r - 1) == TILE_ROAD
                    or tile_type_at(c - 1, r) == TILE_ROAD or tile_type_at(c + 1, r) == TILE_ROAD):
                self._draw_street_tree(rect.centerx, rect.centery, (n >> 5) & 3)
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

        if t == TILE_GRASS:
            pygame.draw.rect(self.screen, COLOR_GRASS, rect)
            n = _noise(c, r, 9)
            for i in range(3):
                gx = rect.left + ((n >> (i * 5)) % 52) + 4
                gy = rect.top + ((n >> (i * 5 + 2)) % 52) + 4
                pygame.draw.rect(self.screen, COLOR_GRASS_DARK, (gx, gy, 6, 5))
            if n % 3 == 0:
                self._draw_street_tree(rect.centerx, rect.centery, (n >> 6) & 3)
            return

        if t == TILE_RAIL:
            pygame.draw.rect(self.screen, (72, 68, 62), rect)
            n = _noise(c, r, 31)
            for i in range(7):
                gx = rect.left + ((n >> (i * 3)) % 58) + 3
                gy = rect.top + ((n >> (i * 4 + 2)) % 46) + 9
                shade = (92, 88, 80) if i & 1 else (54, 52, 50)
                self.screen.fill(shade, (gx, gy, 3, 2))
            return

        # --- Roads ---
        # Diagonal tiles reserve a walkable corridor, but the asphalt itself is
        # drawn once as a continuous polyline in draw_diagonal_network().  A
        # square of asphalt per tile was the source of the staircase/plaza look.
        # At a diagonal/grid crossing the square beneath the smooth diagonal
        # must remain the cardinal road. Treating every diagonal reservation
        # as sidewalk left pale triangular curb wedges across the mouth of the
        # intersecting street. Only off-grid diagonal tiles need this neutral
        # sidewalk underlay.
        if tile.get('diagonal') and c not in ROAD_LINES and r not in ROAD_LINES:
            pygame.draw.rect(self.screen, COLOR_SIDEWALK, rect)
            n = _noise(c, r, 17)
            pygame.draw.line(self.screen, COLOR_PLAZA_SEAM,
                             (rect.left, rect.centery), (rect.right, rect.centery), 1)
            pygame.draw.line(self.screen, COLOR_PLAZA_SEAM,
                             (rect.centerx, rect.top), (rect.centerx, rect.bottom), 1)
            px = rect.left + (n % 48) + 8
            py = rect.top + ((n >> 6) % 48) + 8
            pygame.draw.rect(self.screen, COLOR_SIDEWALK_SEAM, (px, py, 5, 3))
            return

        pygame.draw.rect(self.screen, COLOR_ROAD, rect)
        n = _noise(c, r, 3)

        # Sidewalk aprons sit *inside* the 64px road tile. They were 9px deep
        # on both sides, leaving only 46 visible pixels of asphalt under a
        # 23px-tall rendered car. Six keeps the kerb readable without making a
        # legal two-lane road look like an alley.
        apron = 6
        # A diagonal/cardinal crossing is one continuous intersection mouth.
        # Cardinal edge aprons here recreated the very curb bars that the
        # diagonal shoulder pass clips away, so leave the whole underlay paved.
        if not tile.get('diagonal'):
            for dr, dc, horizontal in ((0, -1, True), (0, 1, True), (-1, 0, False), (1, 0, False)):
                nt = tile_type_at(c + dc, r + dr)
                if nt == TILE_ROAD:
                    continue
                if horizontal:  # apron running along a vertical road edge
                    x0 = rect.left + 2 if dc < 0 else rect.right - apron - 2
                    pygame.draw.rect(self.screen, COLOR_SIDEWALK, (x0, rect.top + 2, apron, TILE_SIZE - 4))
                    pygame.draw.line(self.screen, COLOR_SIDEWALK_SEAM,
                                     (x0 + (apron if dc > 0 else 0), rect.top + 2),
                                     (x0 + (apron if dc > 0 else 0), rect.bottom - 2), 1)
                else:  # apron running along a horizontal road edge
                    y0 = rect.top + 2 if dr < 0 else rect.bottom - apron - 2
                    pygame.draw.rect(self.screen, COLOR_SIDEWALK, (rect.left + 2, y0, TILE_SIZE - 4, apron))
                    pygame.draw.line(self.screen, COLOR_SIDEWALK_SEAM,
                                     (rect.left + 2, y0 + (apron if dr > 0 else 0)),
                                     (rect.right - 2, y0 + (apron if dr > 0 else 0)), 1)

        # intersection: zebra crossings, no centre lines through it
        if c in ROAD_LINES and r in ROAD_LINES:
            self.draw_crosswalk(rect, c, r)
            return

        # tire-grime streak down the lane centre (follows the road direction)
        if r in ROAD_LINES:
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
        if c in ROAD_LINES and r not in ROAD_LINES:
            for y in range(rect.top + 4, rect.bottom - 8, 14):
                pygame.draw.rect(self.screen, COLOR_ROAD_LINE, (rect.centerx - 2, y, 4, 8))
        if r in ROAD_LINES and c not in ROAD_LINES:
            for x in range(rect.left + 4, rect.right - 8, 14):
                pygame.draw.rect(self.screen, COLOR_ROAD_LINE, (x, rect.centery - 2, 8, 4))

    DIAG_ROAD_WIDTH = 50
    DIAG_KERB_WIDTH = 62

    @staticmethod
    def ground_color_at(c, r):
        """What colour the flat ground of a tile is drawn, or None if it is a
        building (those get their own roof pass) or plain asphalt."""
        if not (0 <= c < MAP_TILES_W and 0 <= r < MAP_TILES_H):
            return None
        tile = GAME_MAP[r][c]
        t = tile['type']
        if t in (TILE_BUILDING, TILE_ROAD):
            return None
        if t == TILE_GRASS:
            return COLOR_GRASS
        if t == TILE_WATER:
            return COLOR_WATER
        if t == TILE_RAIL:
            return (72, 68, 62)
        return tile['color']            # park and plaza carry their own

    def draw_diagonal_road(self, rect, c, r):
        """Draw the clipped piece of a smooth diagonal through one tile.

        Kept as a small rendering primitive for tests and previews; normal
        gameplay draws whole polylines at once so no tile seam can square them.
        """
        pygame.draw.rect(self.screen, COLOR_SIDEWALK, rect)
        ux, uy = DIAGONAL_DIR.get((c, r), (0.75, 0.66))
        cx, cy = rect.center
        ends = ((cx - ux * 54, cy - uy * 54), (cx + ux * 54, cy + uy * 54))
        pygame.draw.line(self.screen, COLOR_SIDEWALK_SEAM, *ends, self.DIAG_KERB_WIDTH)
        pygame.draw.line(self.screen, COLOR_SIDEWALK, *ends, self.DIAG_KERB_WIDTH - 2)
        pygame.draw.line(self.screen, COLOR_ROAD, *ends, self.DIAG_ROAD_WIDTH)
        pygame.draw.line(self.screen, COLOR_ROAD_DARK, *ends, 7)
        pygame.draw.line(self.screen, COLOR_ROAD_LINE,
                         (cx - ux * 13, cy - uy * 13),
                         (cx + ux * 3, cy + uy * 3), 3)

    def draw_diagonal_network(self):
        """Draw every named diagonal as one continuous, normal-width road."""
        routes = []
        for _name, points, _width in DIAGONAL_STREETS:
            screen_points = [
                (int(c * TILE_SIZE + TILE_SIZE * 0.5 - self.camera.x),
                 int(r * TILE_SIZE + TILE_SIZE * 0.5 - self.camera.y))
                for c, r in points
            ]
            if len(screen_points) < 2:
                continue
            routes.append(screen_points)

        # Draw shoulders on their own transparent layer, then punch out each
        # cardinal crossing before compositing. Drawing the shoulder directly
        # onto the world left two curb-coloured bars across every intersecting
        # road even though the tile beneath it was correctly asphalt.
        shoulders = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        for screen_points in routes:
            pygame.draw.lines(shoulders, COLOR_SIDEWALK_SEAM, False,
                              screen_points, self.DIAG_KERB_WIDTH)
            pygame.draw.lines(shoulders, COLOR_SIDEWALK, False,
                              screen_points, self.DIAG_KERB_WIDTH - 2)
        for col, row in DIAGONAL_GRID_CROSSINGS:
            crossing = self.camera.apply(
                pygame.Rect(col * TILE_SIZE, row * TILE_SIZE,
                            TILE_SIZE, TILE_SIZE))
            shoulders.fill((0, 0, 0, 0), crossing)
        self.screen.blit(shoulders, (0, 0))

        for screen_points in routes:
            pygame.draw.lines(self.screen, COLOR_ROAD, False,
                              screen_points, self.DIAG_ROAD_WIDTH)
            pygame.draw.lines(self.screen, COLOR_ROAD_DARK, False,
                              screen_points, 7)

            # Dashed centre line follows the true polyline, not the tile steps.
            for (x0, y0), (x1, y1) in zip(screen_points, screen_points[1:]):
                dx, dy = x1 - x0, y1 - y0
                length = math.hypot(dx, dy)
                if length <= 0:
                    continue
                ux, uy = dx / length, dy / length
                pos = 6.0
                while pos < length:
                    end = min(length, pos + 13.0)
                    pygame.draw.line(self.screen, COLOR_ROAD_LINE,
                                     (x0 + ux * pos, y0 + uy * pos),
                                     (x0 + ux * end, y0 + uy * end), 3)
                    pos += 27.0

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
        items = props_props_for_tile(c, r, ttype, is_sidewalk, hood_at(c, r))
        if not items:
            return
        base = self.camera.apply(pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE))
        for name, ox, oy in items:
            # The Hill paints its hydrants green, white and red - every
            # corner, and it is the first thing anyone from here notices
            # about the neighbourhood. The props module has no idea what a
            # neighbourhood is, so the swap happens here at the draw site.
            if name == 'hydrant' and hood_at(c, r) == 'hill':
                name = 'hydrant_hill'
            ax, ay = props_anchor_offset(name)
            x, y = base.left + ox - ax, base.top + oy - ay
            shadow = props_get_shadow(name)
            if shadow is not None:
                self.screen.blit(shadow, (x + SHADOW_DX, y + SHADOW_DY))
            self.screen.blit(props_get(name), (x, y))

    def draw_crosswalk(self, rect, c, r):
        """Small, evenly spaced zebra bars on each live approach."""
        bar = 6
        # Starts mirror exactly around the tile centre. Constant stride made
        # the final bar one pixel lopsided after a 90-degree rotation.
        starts = (9, 22, 36, 49)
        for dx, dy, horizontal in ((0, -1, True), (0, 1, True), (-1, 0, False), (1, 0, False)):
            if tile_type_at(c + dx, r + dy) != TILE_ROAD:
                continue
            if horizontal:  # bars span the vertical road (north/south approach)
                y0 = rect.top + 6 if dy < 0 else rect.bottom - 12
                for start in starts:
                    pygame.draw.rect(self.screen, COLOR_CROSSWALK,
                                     (rect.left + start, y0, bar, bar))
            else:  # bars span the horizontal road (east/west approach)
                x0 = rect.left + 6 if dx < 0 else rect.right - 12
                for start in starts:
                    pygame.draw.rect(self.screen, COLOR_CROSSWALK,
                                     (x0, rect.top + start, bar, bar))

    def landmark_has_art(self, tile):
        name = tile['landmark']
        return name is not None and lm_has_art(landmark_owner(name))

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

    def draw_arch_foreground(self):
        """Occlude actors with the elevated Arch after the entity pass."""
        entry = next(e for e in LANDMARKS if e[5] == "Gateway Arch")
        rect = self.camera.apply(pygame.Rect(entry[0] * TILE_SIZE,
                                             entry[1] * TILE_SIZE,
                                             entry[2] * TILE_SIZE,
                                             entry[3] * TILE_SIZE))
        lm_draw_arch_foreground(self.screen, rect,
                                pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT))

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
        base = building_art_color(c, r, tile)
        roof_col = _blend(base, (0, 0, 0), 0.20)
        darker = tuple(int(v * 0.55) for v in base)

        pygame.draw.rect(self.screen, COLOR_BUILDING_WALL, rect)
        roof = (rect.left, rect.top, rect.width - 8, rect.height - 8)
        pygame.draw.rect(self.screen, roof_col, roof)
        pygame.draw.rect(self.screen, darker, roof, 1)

        # rooftop clutter: deterministic per tile, one shared style per landmark
        style = roofs_style_for(c, r, tile['landmark'])
        roofs_draw_roof_detail(self.screen, pygame.Rect(roof), roof_col, c, r, style)

    def _draw_neighborhood_building(self, rect, c, r):
        """Blit one native 64px district tile directly over its collider."""
        hood = hood_at(c, r)
        variants = NEIGHBORHOOD_BUILDING_SPRITES.get(hood, ())
        if not variants:
            return False
        if hood == 'downtown' and len(variants) > 1 and c >= river_bank(r) - 8:
            sprite = variants[-1]             # sawtooth riverfront warehouse
        else:
            sprite = variants[_noise(c, r, 3307) % len(variants)]
        self.screen.blit(sprite, rect.topleft)
        return True

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

        # One in three exposed addresses uses the generated district atlases; the
        # others retain procedural storefront/house variants. Both choices are
        # deterministic, so a street keeps its identity as the camera moves.
        if _noise(c, r, 3299) % 3 == 0 and self._draw_neighborhood_building(rect, c, r):
            return

        base = building_art_color(c, r, tile)
        wall = _blend(base, COLOR_SIDEWALK, 0.22)          # lit front, brighter than roof
        wall_lo = _blend(base, (0, 0, 0), 0.28)
        course = _blend(base, (0, 0, 0), 0.34)
        trim = _blend(base, COLOR_SIDEWALK, 0.55)
        n = _noise(c, r, 71)
        WALL_H, SKIRT = 32, 8
        top_y = rect.bottom - WALL_H

        pygame.draw.rect(self.screen, wall, (rect.left, top_y, TILE_SIZE, WALL_H + SKIRT))
        pygame.draw.rect(self.screen, trim, (rect.left, top_y - 2, TILE_SIZE, 3))          # cornice
        for yy in range(top_y + 5, rect.bottom + SKIRT, 6):
            pygame.draw.line(self.screen, course, (rect.left, yy), (rect.right - 1, yy))
            # Staggered vertical joints turn stripes into brickwork without
            # making the moving scene buzz with one-pixel noise.
            offset = 4 if ((yy - top_y) // 6) % 2 else 10
            for xx in range(rect.left + offset, rect.right, 16):
                pygame.draw.line(self.screen, course, (xx, yy - 4), (xx, yy - 1))
        pygame.draw.rect(self.screen, wall_lo, (rect.left, rect.bottom - 2, TILE_SIZE, SKIRT + 2))
        pygame.draw.line(self.screen, COLOR_OUTLINE, (rect.left, rect.bottom + SKIRT - 1),
                         (rect.right - 1, rect.bottom + SKIRT - 1))

        kind = n % 10
        if kind == 0:                                       # blank party wall
            if n & 16:                                      # ...with a downspout
                pygame.draw.rect(self.screen, course, (rect.left + 30, top_y, 2, WALL_H))
            return
        storefront = facade_is_storefront(tile['landmark'], kind)
        win_y = top_y + 6
        if storefront:
            self._facade_storefront(rect, c, r, n, top_y, win_y, SKIRT, trim)
        else:
            self._facade_house(rect, c, r, n, top_y, win_y, WALL_H, SKIRT,
                               base, wall, course, trim)

    # -- named St. Louis storefronts ---------------------------------------
    def _facade_storefront(self, rect, c, r, n, top_y, win_y, SKIRT, trim):
        """A shop with a real sign on it. Half the character of a St. Louis
        street is the names over the doors, and the HUD font can spell them."""
        name, sign_bg, sign_fg = hood_pick_sign(c, r, n)
        awn = _AWNING_COLORS[n % len(_AWNING_COLORS)]

        # sign board across the top of the shopfront
        sb = pygame.Rect(rect.left + 2, top_y + 1, TILE_SIZE - 4, 9)
        pygame.draw.rect(self.screen, _blend(sign_bg, (0, 0, 0), 0.45), sb.move(1, 1))
        pygame.draw.rect(self.screen, sign_bg, sb)
        pygame.draw.rect(self.screen, _blend(sign_bg, (255, 255, 255), 0.30), sb, 1)
        tw = hud_text_width(name, 1)
        if tw <= sb.width:
            hud_text(self.screen, name, sb.x + (sb.width - tw) // 2, sb.y + 1,
                     sign_fg, False, 1)
        if name == "FOX":                                    # marquee bulbs
            for bx in range(sb.left + 2, sb.right - 1, 5):
                self.screen.fill((248, 226, 150), (bx, sb.bottom, 2, 2))

        # awning, glass, door
        ay = sb.bottom + 2
        pygame.draw.rect(self.screen, _blend(awn, (0, 0, 0), 0.35),
                         (rect.left + 2, ay, TILE_SIZE - 4, 5))
        pygame.draw.rect(self.screen, awn, (rect.left + 2, ay, TILE_SIZE - 4, 3))
        for sx in range(rect.left + 4, rect.right - 4, 8):   # awning stripes
            self.screen.fill(_blend(awn, (255, 255, 255), 0.35), (sx, ay, 3, 3))
        sw = pygame.Rect(rect.left + 5, ay + 6, TILE_SIZE - 26,
                         rect.bottom + SKIRT - ay - 7)
        if sw.height > 3:
            pygame.draw.rect(self.screen, (44, 52, 60), sw)
            pygame.draw.rect(self.screen, (120, 150, 168) if n & 8 else (150, 120, 70),
                             sw.inflate(-4, -4))            # lit shop glass
        pygame.draw.rect(self.screen, (26, 22, 24),
                         (rect.right - 17, ay + 5, 12, rect.bottom + SKIRT - ay - 5))
        pygame.draw.rect(self.screen, trim, (rect.right - 17, ay + 5, 12, 2))

    # -- St. Louis housing stock -------------------------------------------
    _PAINTED_LADY = ((132, 108, 156), (86, 122, 132), (168, 132, 96),
                     (150, 96, 104), (104, 128, 100), (176, 156, 112))

    def _facade_house(self, rect, c, r, n, top_y, win_y, WALL_H, SKIRT,
                      base, wall, course, trim):
        """Five real St. Louis house types instead of one generic wall: the
        Second Empire mansard rowhouse, a gabled brick two-flat, a painted
        lady, and a south-city shotgun."""
        style = hood_pick_house(c, r, n)
        dark = _blend(base, (0, 0, 0), 0.45)

        if style == 'painted_lady':
            body = self._PAINTED_LADY[(n >> 5) % len(self._PAINTED_LADY)]
            pygame.draw.rect(self.screen, body,
                             (rect.left, top_y, TILE_SIZE, WALL_H + SKIRT))
            wall = body
            trim = _blend(body, (255, 255, 255), 0.55)
            course = _blend(body, (0, 0, 0), 0.30)

        if style == 'flat_front':
            # The South City two-family flat: paired doors, limestone window
            # caps, bracketed cornice and just enough gingerbread brick to be
            # recognizable from a moving car. The shared stoop is the punchline.
            limestone = _blend(trim, (238, 230, 204), 0.45)
            brick_hi = _blend(wall, (210, 142, 110), 0.20)
            cornice_y = top_y - 3
            pygame.draw.rect(self.screen, dark,
                             (rect.left, cornice_y, TILE_SIZE, 5))
            pygame.draw.rect(self.screen, limestone,
                             (rect.left + 2, cornice_y, TILE_SIZE - 4, 2))
            for bx in range(rect.left + 5, rect.right - 5, 9):
                pygame.draw.rect(self.screen, brick_hi, (bx, top_y + 1, 4, 3))
                pygame.draw.rect(self.screen, dark, (bx + 1, top_y + 4, 2, 2))

            # Four tall upper windows, deliberately narrow like the real stock.
            for wi, wx in enumerate((rect.left + 6, rect.left + 20,
                                     rect.left + 37, rect.left + 51)):
                lit = _noise(c, r, 701 + wi * 19) % 4 == 0
                glass = (214, 180, 112) if lit else (42, 54, 66)
                pygame.draw.rect(self.screen, limestone, (wx - 2, top_y + 6, 12, 2))
                pygame.draw.rect(self.screen, COLOR_OUTLINE, (wx - 1, top_y + 8, 10, 10))
                pygame.draw.rect(self.screen, glass, (wx, top_y + 9, 8, 8))
                pygame.draw.line(self.screen, dark, (wx + 4, top_y + 9),
                                 (wx + 4, top_y + 16))
                pygame.draw.rect(self.screen, limestone, (wx - 2, top_y + 18, 12, 2))

            # Mirrored entrances with transoms and individual colored doors.
            doors_y = top_y + 21
            for di, dx in enumerate((rect.centerx - 14, rect.centerx + 1)):
                door_col = ((76, 104, 90), (112, 58, 52))[(n + di) & 1]
                pygame.draw.rect(self.screen, limestone, (dx - 2, doors_y - 2, 15, 3))
                pygame.draw.rect(self.screen, COLOR_OUTLINE, (dx - 1, doors_y, 13, 18))
                pygame.draw.rect(self.screen, door_col, (dx, doors_y + 1, 11, 16))
                pygame.draw.rect(self.screen, (190, 202, 194), (dx + 2, doors_y + 2, 7, 3))
                pygame.draw.rect(self.screen, limestone, (dx + 4, doors_y - 5, 5, 3))
                self.screen.fill((224, 188, 92), (dx + 8, doors_y + 10, 1, 1))
            # One broad limestone stoop serving both halves.
            for k in range(4):
                pygame.draw.rect(self.screen, _blend(limestone, dark, 0.10 * k),
                                 (rect.centerx - 17 - k, rect.bottom + k * 2,
                                  35 + k * 2, 3))
            return

        if style in ('gable_brick', 'painted_lady', 'shotgun'):
            # a peaked roofline poking above the cornice
            peak = 7 if style != 'shotgun' else 4
            apex = (rect.centerx, top_y - 2 - peak)
            pygame.draw.polygon(self.screen, _blend(wall, (0, 0, 0), 0.35),
                                [(rect.left + 2, top_y), apex, (rect.right - 2, top_y)])
            pygame.draw.polygon(self.screen, COLOR_OUTLINE,
                                [(rect.left + 2, top_y), apex, (rect.right - 2, top_y)], 1)
            if style == 'gable_brick' and (n & 32):          # chimney
                pygame.draw.rect(self.screen, dark, (rect.right - 14, top_y - 10, 5, 9))
        elif style == 'mansard':
            # steep slate mansard with two dormers
            pygame.draw.rect(self.screen, (58, 60, 68), (rect.left, top_y - 8, TILE_SIZE, 9))
            pygame.draw.rect(self.screen, (44, 46, 54), (rect.left, top_y - 1, TILE_SIZE, 2))
            for dx in (rect.left + 13, rect.right - 22):
                pygame.draw.rect(self.screen, (72, 74, 82), (dx, top_y - 11, 9, 8))
                lit = _noise(c, r, 311 + dx - rect.left) % 3 == 0
                pygame.draw.rect(self.screen, (206, 178, 116) if lit else (38, 44, 56),
                                 (dx + 2, top_y - 9, 5, 5))
                pygame.draw.rect(self.screen, COLOR_OUTLINE, (dx, top_y - 11, 9, 8), 1)

        # windows: tall pairs on the rowhouses, one wide light on a shotgun
        if style == 'shotgun':
            xs, ww, wh = (rect.left + 8,), 20, 12
        elif style == 'mansard':
            xs, ww, wh = (rect.left + 8, rect.left + 26), 12, 15
        else:
            xs, ww, wh = (rect.left + 7, rect.left + 25), 13, 13
        for wi, wx in enumerate(xs):
            # Salt on the window's index within the tile, never on wx:
            # wx is a screen coordinate, so keying the noise off it re-rolled
            # every window on every camera move and the lights flickered as
            # you walked. (c, r, wi) is fixed to the building.
            lit = _noise(c, r, 137 + wi * 41) % 3 == 0
            glass = (210, 184, 120) if lit else (44, 52, 64)
            pygame.draw.rect(self.screen, (18, 16, 20), (wx - 1, win_y - 1, ww + 2, wh + 2))
            pygame.draw.rect(self.screen, glass, (wx, win_y, ww, wh))
            pygame.draw.line(self.screen, (18, 16, 20),
                             (wx + ww // 2, win_y), (wx + ww // 2, win_y + wh - 1))
            pygame.draw.rect(self.screen, trim, (wx - 2, win_y + wh, ww + 4, 2))
            if style in ('mansard', 'painted_lady'):          # stone lintel
                pygame.draw.rect(self.screen, trim, (wx - 2, win_y - 3, ww + 4, 2))

        # front door + stoop: the thing every one of these houses has
        door_x = rect.right - 20
        door_h = rect.bottom + SKIRT - win_y - 2
        pygame.draw.rect(self.screen, dark, (door_x, win_y + 2, 13, door_h))
        pygame.draw.rect(self.screen, (30, 24, 26), (door_x + 2, win_y + 4, 9, door_h - 2))
        pygame.draw.rect(self.screen, trim, (door_x, win_y + 2, 13, 2))
        if style == 'shotgun':                               # full-width porch
            pygame.draw.rect(self.screen, trim, (rect.left + 3, win_y - 3, TILE_SIZE - 6, 3))
            for px in (rect.left + 5, rect.right - 8):
                pygame.draw.rect(self.screen, trim, (px, win_y, 2, door_h + 2))
        # stone steps down to the pavement
        for k in range(3):
            pygame.draw.rect(self.screen, _blend(trim, (0, 0, 0), 0.12 * k),
                             (door_x - k, rect.bottom + k * 2, 13 + k * 2, 3))

    # ---------------- front-end screens ----------------
    @staticmethod
    def _fit_menu_text(text, max_width, scale=1):
        text = str(text).upper()
        if hud_text_width(text, scale) <= max_width:
            return text
        suffix = "..."
        while text and hud_text_width(text + suffix, scale) > max_width:
            text = text[:-1]
        return text + suffix

    def _draw_title_city(self):
        """Procedural title backdrop: river, brick skyline, Arch and one car.
        It is deliberately an illustration of the game's own visual language,
        not an image file disguised as a loading screen."""
        self.screen.fill((7, 11, 27))
        for y in range(0, SCREEN_HEIGHT, 18):
            col = (8 + y // 30, 13 + y // 38, 31 + y // 24)
            pygame.draw.rect(self.screen, col, (0, y, SCREEN_WIDTH, 18))
        # Sodium-orange moon, half hidden by the city.
        pygame.draw.circle(self.screen, (188, 112, 60), (489, 91), 42)
        pygame.draw.circle(self.screen, (214, 148, 78), (478, 82), 30)

        # Uneven brick skyline and its few lit windows.
        x = 0
        while x < SCREEN_WIDTH:
            n = _noise(x // 17, 3, 1701)
            w = 25 + n % 34
            h = 45 + (n >> 6) % 95
            top = 276 - h
            brick = CITY_BRICKS[(n >> 11) % len(CITY_BRICKS)]
            brick = _blend(brick, (5, 8, 18), 0.42)
            pygame.draw.rect(self.screen, (10, 8, 14), (x + 4, top + 5, w, h))
            pygame.draw.rect(self.screen, brick, (x, top, w, h))
            pygame.draw.line(self.screen, _blend(brick, (255, 255, 255), 0.18),
                             (x, top), (x + w - 1, top))
            for wy in range(top + 10, 268, 15):
                for wx in range(x + 7, x + w - 5, 12):
                    lit = _noise(wx, wy, 1723) % 7 == 0
                    pygame.draw.rect(self.screen, (206, 154, 78) if lit else (24, 30, 42),
                                     (wx, wy, 4, 6))
            x += w + 3

        # Riverfront geography, in the right order: dry Arch lawn, stone
        # levee, then Mississippi. The old freeway polygon was literally
        # painted on top of the water and the water covered both Arch feet.
        pygame.draw.rect(self.screen, (55, 72, 48), (0, 268, SCREEN_WIDTH, 39))
        pygame.draw.rect(self.screen, (92, 94, 88), (0, 307, SCREEN_WIDTH, 17))
        pygame.draw.line(self.screen, (154, 150, 136), (0, 307),
                         (SCREEN_WIDTH, 307), 2)
        for xx in range(-8, SCREEN_WIDTH, 25):
            pygame.draw.line(self.screen, (62, 64, 62), (xx, 314),
                             (xx + 13, 314), 1)
        pygame.draw.rect(self.screen, (28, 72, 104), (0, 324, SCREEN_WIDTH, 36))
        for yy in (333, 349):
            for xx in range((yy * 7) % 31, SCREEN_WIDTH, 43):
                pygame.draw.rect(self.screen, (58, 112, 140), (xx, yy, 22, 2))

        # The Arch lands visibly on the lawn. Drawing it after the shoreline
        # prevents any foreground layer from sawing the feet off again.
        points = []
        for i in range(33):
            t = math.pi * i / 32.0
            points.append((int(320 + 108 * math.cos(t)),
                           int(285 - 178 * math.sin(t))))
        pygame.draw.lines(self.screen, (24, 28, 38), False,
                          [(x + 5, y + 6) for x, y in points], 15)
        pygame.draw.lines(self.screen, (164, 174, 180), False, points, 12)
        pygame.draw.lines(self.screen, (224, 226, 218), False,
                          [(x - 2, y - 1) for x, y in points], 3)
        for foot_x in (212, 428):
            pygame.draw.rect(self.screen, (30, 32, 36), (foot_x - 12, 287, 24, 6))
            pygame.draw.rect(self.screen, (150, 154, 152), (foot_x - 10, 285, 20, 5))

        # A diagonal view of the black-and-gold local Trans Am reads as a car,
        # unlike the doubled side-on sedan that looked like a red shoebox.
        entry = CAR_SPRITES.get(('trans_am', cars_TRANS_AM_BODY))
        if entry:
            angle = 2
            car = entry[0][angle]
            shadow = entry[1][angle]
            size = (int(car.get_width() * 1.45), int(car.get_height() * 1.45))
            car = pygame.transform.scale(car, size)
            shadow = pygame.transform.scale(shadow, size)
            rect = car.get_rect(center=(538, 286))
            self.screen.blit(shadow, rect.move(4, 4))
            self.screen.blit(car, rect)

    def draw_title_screen(self):
        self._draw_title_city()
        title = "STL GTA"
        hud_text(self.screen, title,
                 (SCREEN_WIDTH - hud_text_width(title, 4)) // 2, 25,
                 hud_HUD_WHITE, True, 4)
        sub = "A LOVE LETTER WITH A WANTED LEVEL"
        hud_text(self.screen, sub,
                 (SCREEN_WIDTH - hud_text_width(sub, 1)) // 2, 66,
                 hud_HUD_GOLD, True, 1)

        options = self.title_options()
        self.title_index %= len(options)
        pw, ph = 176, 22 + len(options) * 25
        px, py = (SCREEN_WIDTH - pw) // 2, 176
        hud_draw_panel(self.screen, pygame.Rect(px, py, pw, ph), alpha=226)
        for i, option in enumerate(options):
            selected = i == self.title_index
            if selected:
                pygame.draw.rect(self.screen, (72, 54, 42),
                                 (px + 7, py + 8 + i * 25, pw - 14, 18))
            label = ("> " if selected else "  ") + option
            hud_text(self.screen, label, px + 17, py + 13 + i * 25,
                     hud_HUD_GOLD if selected else hud_HUD_WHITE, True, 1)
        hint = "ARROWS + ENTER"
        hud_text(self.screen, hint,
                 (SCREEN_WIDTH - hud_text_width(hint, 1)) // 2, 348,
                 hud_HUD_GREY_DIM, True, 1)

    def draw_character_screen(self):
        self.screen.fill((32, 25, 28))
        # Brick wall, limestone sill and a dark strip of South City pavement.
        for y in range(0, 274, 12):
            offset = -16 if (y // 12) % 2 else 0
            pygame.draw.line(self.screen, (72, 46, 44), (0, y), (SCREEN_WIDTH, y))
            for x in range(offset, SCREEN_WIDTH, 32):
                pygame.draw.line(self.screen, (70, 44, 42), (x, y), (x, y + 11))
        pygame.draw.rect(self.screen, (166, 154, 132), (0, 270, SCREEN_WIDTH, 8))
        pygame.draw.rect(self.screen, (48, 48, 52), (0, 278, SCREEN_WIDTH, 82))

        title = "MAKE YOUR PERSON"
        hud_text(self.screen, title, 20, 16, hud_HUD_GOLD, True, 2)
        hud_text(self.screen, "ST. LOUIS NEEDS TO KNOW TWO THINGS.", 22, 40,
                 hud_HUD_WHITE, True, 1)

        # Live baked-sprite preview: this is the exact character entering play.
        key = PEDS_PLAYER_KEYS[self.character_look % len(PEDS_PLAYER_KEYS)]
        sprite, _shadow = ped_sprite(key, 2, False, 0)
        preview = pygame.transform.scale(sprite,
                                         (sprite.get_width() * 6, sprite.get_height() * 6))
        shadow = pygame.Surface((116, 34), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 105), shadow.get_rect())
        self.screen.blit(shadow, (58, 230))
        self.screen.blit(preview, preview.get_rect(center=(116, 172)))

        rows = (
            ("LOOK", CHARACTER_LOOKS[self.character_look]),
            ("HIGH SCHOOL", self.character_school),
            ("", "HIT THE STREET"),
        )
        x, w = 205, 410
        ys = (82, 141, 221)
        hs = (45, 64, 40)
        for i, ((label, value), y, h) in enumerate(zip(rows, ys, hs)):
            selected = i == self.setup_row
            hud_draw_panel(self.screen, pygame.Rect(x, y, w, h),
                           fill=(54, 42, 42) if selected else hud_HUD_PANEL,
                           alpha=235)
            if label:
                hud_text(self.screen, label, x + 12, y + 8,
                         hud_HUD_GOLD if selected else hud_HUD_GREY_DIM, True, 1)
                shown = self._fit_menu_text(value, w - 30)
                hud_text(self.screen, shown, x + 12, y + 24,
                         hud_HUD_WHITE, True, 1)
            else:
                prefix = "> " if selected else "  "
                line = prefix + value
                hud_text(self.screen, line,
                         x + (w - hud_text_width(line, 2)) // 2, y + 11,
                         hud_HUD_GOLD if selected else hud_HUD_WHITE, True, 2)
        hud_text(self.screen, "UP/DOWN CHOOSE   LEFT/RIGHT CHANGE   ENTER SELECT",
                 18, 340, hud_HUD_GREY_DIM, True, 1)

        if self.school_open:
            self.draw_school_picker()

    def draw_school_picker(self):
        dim = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        dim.fill((4, 5, 10, 190))
        self.screen.blit(dim, (0, 0))
        panel = pygame.Rect(40, 34, 560, 292)
        hud_draw_panel(self.screen, panel, alpha=248)
        hud_text(self.screen, "WHERE'D YOU GO TO HIGH SCHOOL?", 57, 48,
                 hud_HUD_GOLD, True, 2)
        query = self.school_query if self.school_query else "TYPE TO FILTER..."
        hud_draw_panel(self.screen, pygame.Rect(56, 73, 528, 24),
                       fill=(26, 28, 34), alpha=255)
        hud_text(self.screen, self._fit_menu_text(query, 505), 65, 82,
                 hud_HUD_WHITE if self.school_query else hud_HUD_GREY_DIM, True, 1)

        rows = self.school_matches()
        if rows:
            self.school_cursor = max(0, min(self.school_cursor, len(rows) - 1))
            visible = 12
            start = max(0, min(self.school_cursor - visible // 2,
                               max(0, len(rows) - visible)))
            for line, idx in enumerate(range(start, min(len(rows), start + visible))):
                name, group = rows[idx]
                y = 106 + line * 16
                selected = idx == self.school_cursor
                if selected:
                    pygame.draw.rect(self.screen, (78, 58, 42), (55, y - 3, 530, 15))
                lead = ">" if selected else " "
                shown = self._fit_menu_text(name, 380)
                hud_text(self.screen, lead + " " + shown, 62, y,
                         hud_HUD_GOLD if selected else hud_HUD_WHITE, True, 1)
                tag = self._fit_menu_text(group, 108)
                hud_text(self.screen, tag, 574 - hud_text_width(tag, 1), y,
                         hud_HUD_GREY_DIM, True, 1)
            count = f"{self.school_cursor + 1}/{len(rows)}"
        else:
            hud_text(self.screen, "NO MATCH. TRY FEWER LETTERS.", 65, 120,
                     hud_HUD_RED, True, 1)
            count = "0/0"
        hud_text(self.screen, count, 576 - hud_text_width(count, 1), 305,
                 hud_HUD_GREY_DIM, True, 1)
        hud_text(self.screen, "ENTER PICK   ESC CANCEL   PGUP/PGDN MOVE",
                 58, 305, hud_HUD_GREY_DIM, True, 1)

    def draw_roadblock_strips(self):
        """Steel spike teeth and warning end-caps, beneath the parked units."""
        viewport = pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
        for block in self.roadblocks:
            rect = self.camera.apply(block['strip'])
            if not rect.colliderect(viewport):
                continue
            pygame.draw.rect(self.screen, (20, 22, 24), rect)
            pygame.draw.rect(self.screen, (224, 186, 54), rect, 2)
            if block['orientation'] == 'horizontal':
                for y in range(rect.top + 4, rect.bottom - 2, 7):
                    pygame.draw.polygon(self.screen, (210, 218, 220),
                                        ((rect.left + 2, y + 2),
                                         (rect.centerx, y - 2),
                                         (rect.right - 2, y + 2)))
                caps = ((rect.centerx, rect.top - 5), (rect.centerx, rect.bottom + 5))
            else:
                for x in range(rect.left + 4, rect.right - 2, 7):
                    pygame.draw.polygon(self.screen, (210, 218, 220),
                                        ((x + 2, rect.top + 2),
                                         (x - 2, rect.centery),
                                         (x + 2, rect.bottom - 2)))
                caps = ((rect.left - 5, rect.centery), (rect.right + 5, rect.centery))
            for x, y in caps:
                pygame.draw.circle(self.screen, COLOR_OUTLINE, (x, y), 4)
                pygame.draw.circle(self.screen, hud_HUD_RED, (x, y), 2)

    @staticmethod
    def rounded_rail_path(points, radius=20.0, steps=6):
        """Replace right-angle polyline vertices with short quadratic bends."""
        if len(points) < 3:
            return [(float(x), float(y)) for x, y in points]
        out = [(float(points[0][0]), float(points[0][1]))]
        for index in range(1, len(points) - 1):
            prev = pygame.Vector2(points[index - 1])
            corner = pygame.Vector2(points[index])
            nxt = pygame.Vector2(points[index + 1])
            incoming = corner - prev
            outgoing = nxt - corner
            if incoming.length_squared() == 0 or outgoing.length_squared() == 0:
                continue
            incoming = incoming.normalize()
            outgoing = outgoing.normalize()
            if abs(incoming.dot(outgoing)) > 0.999:
                out.append((corner.x, corner.y))
                continue
            cut = min(radius, corner.distance_to(prev) * 0.35,
                      corner.distance_to(nxt) * 0.35)
            entry = corner - incoming * cut
            leave = corner + outgoing * cut
            out.append((entry.x, entry.y))
            for step in range(1, steps + 1):
                t = step / float(steps)
                q = ((1.0 - t) ** 2 * entry
                     + 2.0 * (1.0 - t) * t * corner
                     + t * t * leave)
                out.append((q.x, q.y))
        out.append((float(points[-1][0]), float(points[-1][1])))
        return out

    def draw_rail_track(self, centerline):
        """Draw sleepers and two steel rails along a smoothly bent track."""
        if len(centerline) < 2:
            return
        pts = [pygame.Vector2(p) for p in centerline]

        # Sleepers only belong on ballasted right-of-way. Embedded track and
        # grade crossings retain their asphalt instead of acquiring a sudden
        # row of timber bars at the surface transition.
        distance = 0.0
        next_tie = 0.0
        for a, b in zip(pts, pts[1:]):
            delta = b - a
            length = delta.length()
            if length <= 0.01:
                continue
            tangent = delta / length
            normal = pygame.Vector2(-tangent.y, tangent.x)
            while next_tie <= distance + length:
                p = a + tangent * (next_tie - distance)
                world_x = p.x + self.camera.x
                world_y = p.y + self.camera.y
                col, row = int(world_x) // TILE_SIZE, int(world_y) // TILE_SIZE
                tile = tile_at(col, row)
                if tile is not None and tile['type'] == TILE_RAIL:
                    pygame.draw.line(self.screen, (76, 54, 42),
                                     p - normal * 7, p + normal * 7, 3)
                next_tie += 14.0
            distance += length

        # Offset each steel rail from the local tangent of the smooth path.
        for rail_offset in (-4.0, 4.0):
            rail = []
            for index, point in enumerate(pts):
                before = pts[max(0, index - 1)]
                after = pts[min(len(pts) - 1, index + 1)]
                tangent = after - before
                if tangent.length_squared() == 0:
                    tangent = pygame.Vector2(1.0, 0.0)
                else:
                    tangent = tangent.normalize()
                normal = pygame.Vector2(-tangent.y, tangent.x)
                rail.append(point + normal * rail_offset)
            pygame.draw.lines(self.screen, (34, 34, 38), False, rail, 3)
            pygame.draw.lines(self.screen, (178, 184, 180), False, rail, 1)

    def draw_rail_infrastructure(self):
        """MetroLink ballast and double rail along the whole polyline, station
        platforms at the named stops, plus the street-running trolley rail."""
        clip = pygame.Rect(-40, -40, SCREEN_WIDTH + 80, SCREEN_HEIGHT + 80)
        for c0, r0, c1, r1, axis in METROLINK_SEGMENTS:
            x0 = c0 * TILE_SIZE + TILE_SIZE // 2 - self.camera.x
            y0 = r0 * TILE_SIZE + TILE_SIZE // 2 - self.camera.y
            x1 = c1 * TILE_SIZE + TILE_SIZE // 2 - self.camera.x
            y1 = r1 * TILE_SIZE + TILE_SIZE // 2 - self.camera.y
            if axis == 'h':
                bounds = pygame.Rect(int(min(x0, x1)), int(y0 - 24),
                                     int(abs(x1 - x0)) + 1, 48)
            else:
                bounds = pygame.Rect(int(x0 - 24), int(min(y0, y1)),
                                     48, int(abs(y1 - y0)) + 1)
            if not bounds.colliderect(clip):
                continue

            # Ballast belongs only to dedicated right-of-way tiles. The old
            # whole-segment bed covered embedded street running with gravel,
            # then a small crossing patch abruptly painted the road back over
            # the rails. Drawing the bed from the stamped tile classification
            # makes dedicated -> embedded -> grade-crossing transitions agree
            # with collision and preserves one continuous pair of railheads.
            if axis == 'h':
                first, last = sorted((c0, c1))
                for col in range(first, last + 1):
                    tile = GAME_MAP[r0][col]
                    if tile['type'] != TILE_RAIL or tile.get('rail_embedded'):
                        continue
                    left = int(col * TILE_SIZE - self.camera.x)
                    pygame.draw.rect(self.screen, (66, 62, 58),
                                     (left, int(y0 - 24), TILE_SIZE, 48))
            else:
                first, last = sorted((r0, r1))
                for row in range(first, last + 1):
                    tile = GAME_MAP[row][c0]
                    if tile['type'] != TILE_RAIL or tile.get('rail_embedded'):
                        continue
                    top = int(row * TILE_SIZE - self.camera.y)
                    pygame.draw.rect(self.screen, (66, 62, 58),
                                     (int(x0 - 24), top, 48, TILE_SIZE))


        # Draw each track as one path. Segment-by-segment rails formerly met as
        # a hard plus-sign at corners; the train turned while its rails did not.
        for offset in METROLINK_TRACK_OFFSETS:
            points = [(x - self.camera.x, y - self.camera.y)
                      for x, y in metrolink_polyline(offset)]
            self.draw_rail_track(self.rounded_rail_path(points))

        # station platforms, with the name on the shelter
        for (col, row, name) in METROLINK_STATIONS:
            px = int(col * TILE_SIZE + TILE_SIZE // 2 - self.camera.x)
            py = int(row * TILE_SIZE + TILE_SIZE // 2 - self.camera.y)
            if not (-120 < px < SCREEN_WIDTH + 120 and -80 < py < SCREEN_HEIGHT + 80):
                continue
            plat = pygame.Rect(px - 46, py - 34, 92, 13)
            pygame.draw.rect(self.screen, (150, 148, 142), plat)
            pygame.draw.rect(self.screen, COLOR_OUTLINE, plat, 1)
            pygame.draw.rect(self.screen, (86, 96, 116), (px - 26, py - 44, 52, 11))
            pygame.draw.rect(self.screen, COLOR_OUTLINE, (px - 26, py - 44, 52, 11), 1)
            label = name[:11]
            hud_text(self.screen, label,
                     px - hud_text_width(label, 1) // 2, py - 42,
                     hud_HUD_WHITE, True, 1)

        # the Loop trolley: rails inset into Delmar, and only where it runs
        trolley_y = TROLLEY_ROW * TILE_SIZE + TILE_SIZE // 2
        tsy = int(trolley_y - self.camera.y)
        tleft = int(TROLLEY_COL_MIN * TILE_SIZE - self.camera.x)
        tright = int((TROLLEY_COL_MAX + 1) * TILE_SIZE - self.camera.x)
        if -12 < tsy < SCREEN_HEIGHT + 12 and tright >= 0 and tleft <= SCREEN_WIDTH:
            for offset in (-6, 6):
                pygame.draw.line(self.screen, (32, 32, 36),
                                 (tleft, tsy + offset + 1),
                                 (tright, tsy + offset + 1), 3)
                pygame.draw.line(self.screen, (170, 174, 170),
                                 (tleft, tsy + offset), (tright, tsy + offset), 1)

    def draw_rail_crossing_gates(self):
        """Paired animated arms and alternating red crossing lamps."""
        for crossing in self.rail_crossings:
            sx, sy = self.camera.apply_pos((crossing.x, crossing.y))
            if not (-70 < sx < SCREEN_WIDTH + 70 and -70 < sy < SCREEN_HEIGHT + 70):
                continue
            flash = bool((self.frame // 7) & 1)
            setups = ((-28, -35, -math.pi / 2, math.pi / 2),
                      (28, 35, math.pi / 2, math.pi / 2))
            for ox, oy, base_angle, sweep in setups:
                px, py = int(sx + ox), int(sy + oy)
                pygame.draw.rect(self.screen, COLOR_OUTLINE, (px - 4, py - 4, 9, 10))
                pygame.draw.rect(self.screen, (190, 190, 178), (px - 2, py - 3, 5, 8))
                for lx in (-3, 3):
                    lit = crossing.warning and flash == (lx > 0)
                    color = hud_HUD_RED if lit else (82, 24, 24)
                    pygame.draw.circle(self.screen, COLOR_OUTLINE, (px + lx, py - 7), 3)
                    pygame.draw.circle(self.screen, color, (px + lx, py - 7), 2)
                angle = base_angle + sweep * crossing.arm
                length = 52
                ex = px + int(math.cos(angle) * length)
                ey = py + int(math.sin(angle) * length)
                pygame.draw.line(self.screen, COLOR_OUTLINE, (px, py), (ex, ey), 6)
                for index in range(7):
                    a = index / 7.0
                    b = (index + 1) / 7.0
                    p1 = (px + int((ex - px) * a), py + int((ey - py) * a))
                    p2 = (px + int((ex - px) * b), py + int((ey - py) * b))
                    pygame.draw.line(self.screen,
                                     hud_HUD_RED if index & 1 else (238, 232, 206),
                                     p1, p2, 3)

    def draw_side_mission_world(self):
        """Contact and breakable props, kept as chunky world objects."""
        if self.side_mission is None and self.side_mission_cooldown <= 0:
            (cx, cy), _name = self.side_mission_contact()
            sx, sy = self.camera.apply_pos((cx, cy))
            if -24 < sx < SCREEN_WIDTH + 24 and -24 < sy < SCREEN_HEIGHT + 24:
                pulse = (self.frame // 7) % 3
                pygame.draw.circle(self.screen, SIDE_MISSION_MARKER_COLORS[1],
                                   (int(sx), int(sy)), 12 + pulse)
                pygame.draw.circle(self.screen, SIDE_MISSION_MARKER_COLORS[0],
                                   (int(sx), int(sy)), 9 + pulse, 2)
                hud_text(self.screen, "?", int(sx) - 2, int(sy) - 5,
                         hud_HUD_WHITE, True, 1)
                label = "SIDE JOB"
                hud_text(self.screen, label,
                         int(sx) - hud_text_width(label, 1) // 2,
                         int(sy) + 15, SIDE_MISSION_MARKER_COLORS[0], True, 1)
        for index, target in enumerate(self.smash_targets):
            if target['hp'] <= 0:
                continue
            sx, sy = self.camera.apply_pos(target['pos'])
            if not (-20 < sx < SCREEN_WIDTH + 20 and -20 < sy < SCREEN_HEIGHT + 20):
                continue
            x, y = int(sx), int(sy)
            flash = self.frame - target['last_hit'] < 5
            body = hud_HUD_WHITE if flash else (72, 92, 108)
            self.screen.fill((30, 28, 30), (x - 7, y + 7, 15, 4))
            self.screen.fill(body, (x - 6, y - 8, 13, 16))
            self.screen.fill((186, 214, 224), (x - 4, y - 6, 9, 9))
            self.screen.fill(SIDE_MISSION_MARKER_COLORS[0], (x - 7, y - 10, 15, 3))
            hud_text(self.screen, str(index + 1), x - 2, y - 4,
                     (32, 30, 34), True, 1)

    def draw_local_legend_markers(self):
        """World labels make the joke readable before the player steals it."""
        for kind in self.legend_rumors:
            car = self.local_legend_car(kind)
            if car is None:
                continue
            sx, sy = self.camera.apply_pos(car.rect.center)
            if not (-60 < sx < SCREEN_WIDTH + 60 and -60 < sy < SCREEN_HEIGHT + 60):
                continue
            info = LOCAL_LEGENDS[kind]
            pulse = 13 + (self.frame // 8) % 3
            pygame.draw.circle(self.screen, info['color'], (int(sx), int(sy)), pulse, 2)
            label = info['name'] if kind in self.legend_discovered else "LOCAL LEGEND ?"
            hud_text(self.screen, label, int(sx) - hud_text_width(label, 1) // 2,
                     int(sy) - pulse - 10, info['color'], True, 1)

    def draw_local_challenge_world(self):
        challenge = self.local_challenge
        if challenge is None or challenge['kind'] != 'mudfoot':
            return
        for target in challenge['targets']:
            if target['hit']:
                continue
            rect = self.camera.apply(target['rect'])
            if not rect.colliderect(pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)):
                continue
            pygame.draw.rect(self.screen, (26, 26, 30), rect.inflate(4, 4))
            pygame.draw.rect(self.screen, (112, 72, 62), rect)
            pygame.draw.rect(self.screen, (164, 178, 184),
                             (rect.centerx - 7, rect.top + 3, 14, 5))
            pygame.draw.line(self.screen, hud_HUD_RED, rect.topleft,
                             rect.bottomright, 2)

    def draw(self):
        if self.state == STATE_TITLE:
            self.draw_title_screen()
            self.postfx.present(self.screen, self.window)
            pygame.display.flip()
            return
        if self.state == STATE_CHARACTER:
            self.draw_character_screen()
            self.postfx.present(self.screen, self.window)
            pygame.display.flip()
            return
        self.screen.fill(COLOR_SKY_BG)
        # Impact shake: a frame-driven jitter folded into the camera for the
        # world + entity passes only. Zero at rest, so it never perturbs the
        # camera-pan test.
        if self.shake > 0.0:
            # sin(frame * 2.7) at 60fps is 25.8Hz - a buzz, not a shake. Just
            # under 9Hz reads as an impact you can feel.
            self.camera.shake_ox = math.sin(self.frame * 0.95) * self.shake
            self.camera.shake_oy = math.cos(self.frame * 1.13) * self.shake
        else:
            self.camera.shake_ox = self.camera.shake_oy = 0.0
        start_col, end_col, start_row, end_row = self.camera.visible_tile_range()
        for r in range(start_row, end_row):
            for c in range(start_col, end_col):
                self.draw_tile(c, r)
        self.draw_diagonal_network()
        self.draw_landmark_art()
        self.draw_decals()          # stains sit on the ground, under everything
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
        self.draw_rail_infrastructure()
        self.draw_roadblock_strips()
        self.draw_side_mission_world()
        self.draw_local_challenge_world()

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
        self.draw_city_event_world()
        # Frame-driven, not wall-clock, so headless captures stay deterministic.
        flash = (self.frame // 8) % 2
        for car in self.cars:
            if car is not self.driving:
                car.draw(self.screen, self.camera, flash)
        for block in self.roadblocks:
            for unit in block['cars']:
                unit.draw(self.screen, self.camera, flash)
        for cop in self.police:
            cop.draw(self.screen, self.camera, flash)

        self.draw_local_legend_markers()

        if self.driving:
            self.driving.draw(self.screen, self.camera, flash)
            self.draw_arch_cargo()
        else:
            ppos = self.camera.apply_pos(self.player_rect.center)
            sx, sy = int(ppos[0]), int(ppos[1])
            moving = self.player_dir[0] or self.player_dir[1]
            if moving:
                self.player_facing = peds_dir_index(self.player_dir[0], self.player_dir[1])
                self.player_anim += 0.16
            player_key = PEDS_PLAYER_KEYS[self.character_look % len(PEDS_PLAYER_KEYS)]
            sprite, shadow = ped_sprite(player_key, self.player_facing,
                                        moving, self.player_anim)
            rect = sprite.get_rect(center=(sx, sy))
            self.screen.blit(shadow, rect.move(SHADOW_DX, SHADOW_DY))
            self.screen.blit(sprite, rect)

        self.draw_rail_crossing_gates()
        self.draw_punch()
        self.draw_bullets()
        self.draw_throwables()
        self.draw_fx()
        self.draw_weapon_pickups()
        self.draw_grub_pickups()
        self.draw_body_shops()
        self.draw_potholes()
        self.draw_dropped_cash()
        self.draw_foot_police()
        self.draw_arch_foreground()
        self.draw_speech_bubbles()
        self.draw_frenzy_icon()
        self.draw_job_marker()
        self.draw_pops()
        # White flash on a big hit, one or two frames.
        if self.hit_flash > 0:
            # A flash should be gone before you know it was there. 27% white
            # held over six frames was a fog you consciously perceived as a
            # rendering artefact rather than an impact.
            fl = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            fl.fill((255, 255, 255, min(210, int(210 * self.hit_flash / 2.0))))
            self.screen.blit(fl, (0, 0))
        if self.arch_victory_timer > 0:
            # The finale gets the whole screen for one beat. HUD numbers,
            # courier work and stale chase callouts would cheapen the landing.
            self.draw_arch_victory_card()
        elif self.state == STATE_DEAD:
            # Nothing else draws over a death card. The old build kept the
            # stars, radar, multiplier, frenzy clock, toasts and three stale
            # callouts at full strength on top of it.
            self.draw_death_card()
        else:
            self.draw_hud()
            self.draw_callouts()

        if self.show_debug:
            self.draw_debug()
        if self.state == STATE_PAUSED:
            self.draw_pause()
        if self.show_map:
            self.draw_map_screen()

        self.postfx.present(self.screen, self.window)
        pygame.display.flip()

    def draw_arch_cargo(self):
        """Strap the stolen 43-pound Arch slice visibly to the getaway car."""
        if (self.driving is None or
                self.arch_job_phase not in (ARCH_ESCAPE, ARCH_LAY_LOW)):
            return False
        cx, cy = self.camera.apply_pos(self.driving.rect.center)
        a = self.driving.angle
        fx, fy = math.cos(a), math.sin(a)
        sx, sy = -fy, fx

        def quad(length, width, ox=0.0, oy=0.0):
            mx, my = cx + sx * ox + fx * oy, cy + sy * ox + fy * oy
            return [(int(mx + fx * dl + sx * dw), int(my + fy * dl + sy * dw))
                    for dl, dw in ((-length, -width), (length, -width),
                                   (length, width), (-length, width))]

        pygame.draw.polygon(self.screen, (14, 14, 18), quad(11, 4, 0, 2))
        pygame.draw.polygon(self.screen, (164, 174, 178), quad(10, 3, 0, 1))
        pygame.draw.line(self.screen, (232, 234, 226),
                         (int(cx - fx * 8 - sx * 2), int(cy - fy * 8 - sy * 2)),
                         (int(cx + fx * 8 - sx * 2), int(cy + fy * 8 - sy * 2)), 1)
        # Two ratchet straps: safety first during a five-star felony.
        for along in (-4, 5):
            px, py = cx + fx * along, cy + fy * along
            pygame.draw.line(self.screen, (174, 46, 42),
                             (int(px - sx * 4), int(py - sy * 4)),
                             (int(px + sx * 4), int(py + sy * 4)), 2)
        return True

    def draw_arch_victory_card(self):
        """A five-second end card over the exact street where you escaped."""
        dim = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        dim.fill((5, 7, 12, 226))
        self.screen.blit(dim, (0, 0))

        # A compact silver Arch owns the top half; the shape is redrawn from
        # primitives so the no-runtime-assets promise remains intact.
        points = []
        for i in range(33):
            t = math.pi * i / 32.0
            points.append((int(320 + 74 * math.cos(t)),
                           int(166 - 112 * math.sin(t))))
        pygame.draw.lines(self.screen, (20, 18, 24), False,
                          [(x + 4, y + 5) for x, y in points], 13)
        pygame.draw.lines(self.screen, (170, 180, 184), False, points, 10)
        pygame.draw.lines(self.screen, (232, 232, 220), False,
                          [(x - 2, y - 1) for x, y in points], 2)

        line = "THE ARCH JOB"
        hud_text(self.screen, line,
                 (SCREEN_WIDTH - hud_text_width(line, 2)) // 2, 185,
                 hud_HUD_WHITE, True, 2)
        line = "COMPLETE"
        hud_text(self.screen, line,
                 (SCREEN_WIDTH - hud_text_width(line, 4)) // 2, 211,
                 hud_HUD_GOLD, True, 4)
        line = f"+${ARCH_JOB_SCORE} SCORE   43 LB LIGHTER"
        hud_text(self.screen, line,
                 (SCREEN_WIDTH - hud_text_width(line, 1)) // 2, 254,
                 hud_HUD_GREEN, True, 1)
        line = "THE ITALIAN JOB. MISSOURI RULES."
        hud_text(self.screen, line,
                 (SCREEN_WIDTH - hud_text_width(line, 1)) // 2, 275,
                 hud_HUD_WHITE, True, 1)
        if (self.arch_victory_timer // 24) % 2 == 0:
            line = "PRESS ENTER TO KEEP DRIVING"
            hud_text(self.screen, line,
                     (SCREEN_WIDTH - hud_text_width(line, 1)) // 2, 326,
                     hud_HUD_GREY_DIM, True, 1)

    # ---------------- the death card ----------------
    def draw_death_card(self):
        """WASTED / BUSTED, held for three seconds over a darkening city.

        The old version was a two-second red tint you played straight through.
        This is a round ending: the world dims, the word lands, the run's
        numbers are read back to you, and the last line tells you where you
        are about to wake up.
        """
        done = 1.0 - max(0.0, self.death_timer / float(DEATH_HOLD_STEPS))
        wrecked = self.death_kind == 'wasted'
        fade = 0.0
        if self.death_timer < DEATH_FADE_STEPS:
            fade = 1.0 - self.death_timer / float(DEATH_FADE_STEPS)

        # Go DARK, not red. The old card washed the screen in (255,0,0,60) and
        # then drew the word in HUD_RED on top of it - the most important
        # message in the game rendered darker than its own background, legible
        # only by its drop shadow. Kill the field, then the word can be the
        # brightest thing on screen.
        dim = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        dim.fill((12, 9, 14, int(120 + 110 * fade)))
        self.screen.blit(dim, (0, 0))
        blood = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        blood.fill((150, 20, 16, int(46 * max(0.0, 1.0 - done * 1.4))))
        self.screen.blit(blood, (0, 0))

        word = "WASTED" if wrecked else "BUSTED!"
        color = (250, 226, 196) if wrecked else hud_HUD_GOLD
        # The word punches in over the first ~0.2s, then holds.
        scale = 4 if done > 0.07 else 3
        bw = hud_text_width(word, scale)
        top = SCREEN_HEIGHT // 2 - 44
        hud_text(self.screen, word, (SCREEN_WIDTH - bw) // 2, top, color, True, scale)

        note = self.death_note or ""
        if note:
            nw = hud_text_width(note, 1)
            hud_text(self.screen, note, (SCREEN_WIDTH - nw) // 2,
                     top + hud_text_height(word, scale) + 6,
                     hud_HUD_WHITE, True, 1)

        # The run's numbers, read back once it has landed. Peak star and
        # longest chase are the two that make you want another go.
        if done > 0.30 and self.death_stats:
            st = self.death_stats
            chase = st.get('chase', 0) // FPS
            lines = [
                f"SCORE {st['score']}",
                f"BANKED ${int(st['cash'])}",
                f"RUNS {st['jobs']}   STREAK {st['streak']}",
                f"TOP STAR {st.get('peak_star', 0)}   "
                f"CHASE {chase // 60}:{chase % 60:02d}",
            ]
            if st.get('dropped'):
                lines.append(f"DROPPED ${st['dropped']} - GO GET IT")
            y = top + hud_text_height(word, scale) + 24
            for ln in lines:
                lw = hud_text_width(ln, 1)
                hud_text(self.screen, ln, (SCREEN_WIDTH - lw) // 2, y,
                         hud_HUD_WHITE, True, 1)
                y += hud_text_height(ln, 1) + 3

        if done > 0.55:
            where = ("COMING TO UNDER THE ARCH" if wrecked
                     else "BOOKED AT THE JUSTICE CENTER")
            ww = hud_text_width(where, 1)
            hud_text(self.screen, where, (SCREEN_WIDTH - ww) // 2,
                     SCREEN_HEIGHT - 34, hud_HUD_GREY_DIM, True, 1)
            # The compulsion spine, on every card, every time: GTA1's
            # "$1,000,000 unlocks the next city" in one row.
            left = max(0, ARCH_JOB_TARGET - self.banked)
            if self.arch_job_completed:
                goal = "ARCH JOB COMPLETE"
            elif self.arch_job_unlocked:
                goal = "THE ARCH JOB IS OPEN"
            else:
                goal = f"${left} TO THE ARCH JOB"
            gw = hud_text_width(goal, 1)
            hud_text(self.screen, goal, (SCREEN_WIDTH - gw) // 2,
                     SCREEN_HEIGHT - 22, hud_HUD_GOLD, True, 1)

        if self.death_can_skip():
            prompt = "ENTER / A TO KEEP PLAYING"
            pw = hud_text_width(prompt, 1)
            hud_text(self.screen, prompt, (SCREEN_WIDTH - pw) // 2,
                     SCREEN_HEIGHT - 48, hud_HUD_WHITE, True, 1)

    # ---------------- feedback rendering ----------------
    _DECAL_COLORS = {
        'blood': ((104, 18, 24), (74, 12, 18), (140, 34, 34)),
        'scorch': ((30, 27, 26), (18, 16, 16), (52, 46, 42)),
        'skid': ((38, 36, 38), (28, 26, 28), (48, 46, 48)),
    }

    def draw_decals(self):
        """Ground stains, drawn on the road under everything that moves. A
        splatter you can still see two blocks later is the whole point."""
        clip_w, clip_h = SCREEN_WIDTH, SCREEN_HEIGHT
        for d in self.decals:
            sx, sy = self.camera.apply_pos((d['x'], d['y']))
            if not (-24 < sx < clip_w + 24 and -24 < sy < clip_h + 24):
                continue
            mid, dark, lite = self._DECAL_COLORS.get(d['kind'],
                                                     self._DECAL_COLORS['blood'])
            n = d['seed']
            bx, by = int(sx), int(sy)
            scale = d['size']
            for i in range(7):
                n = (n * 1103515245 + 12345) & 0x7fffffff
                ox = ((n >> 4) % 21) - 10
                oy = ((n >> 11) % 21) - 10
                rad = 2 + ((n >> 18) % 3)
                col = dark if i % 3 == 0 else mid
                pygame.draw.circle(self.screen, col,
                                   (bx + int(ox * scale), by + int(oy * scale)),
                                   max(1, int(rad * scale)))
            n = (n * 1103515245 + 12345) & 0x7fffffff
            self.screen.fill(lite, (bx + ((n >> 6) % 9) - 4,
                                    by + ((n >> 13) % 9) - 4, 2, 2))

    def draw_bullets(self):
        for b in self.bullets:
            sx, sy = self.camera.apply_pos((b['x'], b['y']))
            if not (0 <= sx < SCREEN_WIDTH and 0 <= sy < SCREEN_HEIGHT):
                continue
            tx = sx - b['vx'] * 0.45
            ty = sy - b['vy'] * 0.45
            tracer = {'shotgun': (255, 196, 112),
                      'smg': (214, 238, 220)}.get(b.get('kind'), (255, 236, 168))
            pygame.draw.line(self.screen, tracer,
                             (int(tx), int(ty)), (int(sx), int(sy)), 2)

    def draw_throwables(self):
        """Hard-pixel projectiles and persistent ground fire."""
        for zone in self.throwable_system.fire_zones():
            sx, sy = self.camera.apply_pos(zone.center)
            if not (-80 < sx < SCREEN_WIDTH + 80 and -80 < sy < SCREEN_HEIGHT + 80):
                continue
            pulse = (self.frame + zone.zone_id * 3) % 8
            for ox, oy, size in ((-22, 4, 9), (-8, -7, 11), (8, 5, 10),
                                 (23, -3, 8), (1, 16, 7)):
                x, y = int(sx + ox), int(sy + oy)
                pygame.draw.circle(self.screen, (92, 42, 30), (x, y), size)
                pygame.draw.rect(self.screen, (232, 92, 42),
                                 (x - 3, y - 7 - pulse // 3, 6, 9))
                pygame.draw.rect(self.screen, (255, 202, 70),
                                 (x - 1, y - 10 - pulse // 2, 3, 7))
        for item in self.throwable_system.projectiles():
            sx, sy = self.camera.apply_pos(item.position)
            if not (-12 < sx < SCREEN_WIDTH + 12 and -12 < sy < SCREEN_HEIGHT + 12):
                continue
            y = int(sy - item.height)
            x = int(sx)
            pygame.draw.ellipse(self.screen, (26, 24, 26),
                                (x - 4, int(sy) + 2, 9, 4))
            if item.kind == throwable_logic.TIMED_EXPLOSIVE:
                pygame.draw.rect(self.screen, (48, 48, 52), (x - 4, y - 3, 9, 7))
                pygame.draw.rect(self.screen, (178, 156, 86), (x - 3, y - 2, 7, 2))
                if (item.fuse_remaining // 6) % 2 == 0:
                    self.screen.fill(hud_HUD_RED, (x + 3, y - 4, 2, 2))
            else:
                pygame.draw.rect(self.screen, (66, 110, 74), (x - 3, y - 4, 6, 9))
                pygame.draw.rect(self.screen, (236, 228, 184), (x - 2, y - 6, 4, 3))
                self.screen.fill((240, 124, 44), (x - 1, y - 8, 2, 3))

    def draw_weapon_pickups(self):
        bob = (self.frame // 8) % 2
        for w in self.weapon_pickups:
            if w['taken']:
                continue
            sx, sy = self.camera.apply_pos((w['x'], w['y']))
            if not (-16 < sx < SCREEN_WIDTH + 16 and -16 < sy < SCREEN_HEIGHT + 16):
                continue
            x, y = int(sx) - 6, int(sy) - 5 - bob
            kind = w.get('kind', 'pistol')
            accent = {'pistol': (212, 184, 90), 'bat': (178, 124, 72),
                      'shotgun': (188, 76, 58), 'smg': (74, 142, 118),
                      throwable_logic.TIMED_EXPLOSIVE: (214, 164, 54),
                      throwable_logic.FIRE_BOTTLE: (206, 74, 42)}[kind]
            self.screen.fill((26, 24, 26), (x + 1, y + 8, 12, 3))     # shadow
            self.screen.fill((58, 56, 62), (x, y, 12, 7))             # crate
            self.screen.fill((92, 90, 98), (x, y, 12, 2))
            self.screen.fill(accent, (x + 1, y + 2, 10, 3))
            if kind == 'bat':
                pygame.draw.line(self.screen, (232, 208, 162),
                                 (x + 2, y + 5), (x + 9, y), 2)
            elif kind == 'pistol':
                self.screen.fill((230, 222, 190), (x + 4, y + 1, 5, 2))
                self.screen.fill((230, 222, 190), (x + 7, y + 3, 2, 3))
            elif kind == 'shotgun':
                self.screen.fill((226, 220, 190), (x + 1, y + 1, 10, 1))
            elif kind == throwable_logic.TIMED_EXPLOSIVE:
                self.screen.fill((42, 42, 46), (x + 3, y, 6, 6))
                self.screen.fill((240, 186, 62), (x + 8, y, 2, 2))
            elif kind == throwable_logic.FIRE_BOTTLE:
                self.screen.fill((82, 124, 78), (x + 4, y, 5, 6))
                self.screen.fill((238, 220, 172), (x + 5, y - 1, 3, 2))
            else:
                self.screen.fill((220, 226, 214), (x + 2, y + 1, 8, 2))
                self.screen.fill((220, 226, 214), (x + 4, y + 3, 3, 2))

    # Each food is drawn as itself rather than as a generic crate, because
    # the whole joke only lands if you can tell a pork steak from a concrete
    # at a glance while doing 9 px a step down Gravois.
    def _grub_pork_steak(self, x, y):
        self.screen.fill((92, 48, 34), (x - 7, y - 4, 14, 9))       # the steak
        self.screen.fill((150, 78, 54), (x - 6, y - 3, 12, 6))
        self.screen.fill((186, 112, 78), (x - 4, y - 2, 8, 2))      # sauce sheen
        self.screen.fill((70, 60, 52), (x - 7, y - 1, 14, 1))       # grill mark
        self.screen.fill((234, 214, 170), (x + 4, y - 5, 4, 3))     # the bone

    def _grub_toasted_rav(self, x, y):
        self.screen.fill((72, 60, 48), (x - 8, y - 3, 16, 8))       # the basket
        for i in range(3):
            self.screen.fill((196, 152, 82), (x - 7 + i * 5, y - 5, 4, 4))
            self.screen.fill((228, 194, 128), (x - 6 + i * 5, y - 4, 2, 1))
        self.screen.fill((160, 46, 42), (x - 2, y + 3, 5, 2))       # marinara

    def _grub_gooey_butter(self, x, y):
        self.screen.fill((188, 150, 88), (x - 7, y - 4, 14, 9))     # the slab
        self.screen.fill((236, 208, 132), (x - 6, y - 3, 12, 6))
        self.screen.fill((250, 238, 206), (x - 5, y - 3, 10, 2))    # powder sugar
        self.screen.fill((248, 246, 240), (x - 3, y - 5, 3, 2))

    def _grub_concrete(self, x, y):
        self.screen.fill((172, 166, 156), (x - 4, y - 2, 9, 9))     # the cup
        self.screen.fill((238, 234, 224), (x - 5, y - 6, 11, 5))    # custard
        self.screen.fill((252, 250, 246), (x - 4, y - 7, 6, 2))
        self.screen.fill((150, 44, 40), (x + 1, y - 8, 3, 2))       # cherry

    def _grub_provel(self, x, y):
        self.screen.fill((176, 150, 78), (x - 7, y - 4, 14, 9))     # the wheel
        self.screen.fill((228, 214, 148), (x - 6, y - 3, 12, 6))
        for k, (ox, oy) in enumerate(((-3, -1), (1, 0), (3, 2))):   # the holes
            self.screen.fill((178, 158, 96), (x + ox, y + oy, 2, 2))

    def _grub_tallboy(self, x, y):
        self.screen.fill((44, 42, 46), (x - 4, y - 8, 9, 14))       # the can
        self.screen.fill((150, 156, 168), (x - 3, y - 7, 7, 12))
        self.screen.fill((196, 60, 56), (x - 3, y - 3, 7, 3))       # the band
        self.screen.fill((226, 230, 236), (x - 3, y - 7, 3, 11))    # highlight

    _GRUB_ART = {
        'pork_steak': _grub_pork_steak,
        'toasted_rav': _grub_toasted_rav,
        'gooey_butter': _grub_gooey_butter,
        'concrete': _grub_concrete,
        'provel': _grub_provel,
        'tallboy': _grub_tallboy,
    }

    def draw_grub_pickups(self):
        bob = (self.frame // 7) % 3 - 1
        for g in self.grub_pickups:
            if g['taken']:
                continue
            sx, sy = self.camera.apply_pos((g['x'], g['y']))
            if not (-16 < sx < SCREEN_WIDTH + 16 and -16 < sy < SCREEN_HEIGHT + 16):
                continue
            x, y = int(sx), int(sy) + bob
            self.screen.fill((22, 20, 24), (x - 7, y + 6, 15, 3))   # ground shadow
            art = self._GRUB_ART.get(g['kind'])
            if art is not None:
                art(self, x, y)

    def draw_body_shops(self):
        """A roll-up garage door with a paint stripe over it. Drive in hot."""
        for (sx, sy) in self.body_shops:
            px, py = self.camera.apply_pos((sx, sy))
            if not (-60 < px < SCREEN_WIDTH + 60 and -60 < py < SCREEN_HEIGHT + 60):
                continue
            x, y = int(px), int(py)
            open_now = self.wanted_level > 0 and self.shop_cooldown <= 0
            self.screen.fill((26, 26, 30), (x - 22, y - 16, 44, 32))
            self.screen.fill((62, 66, 74), (x - 20, y - 14, 40, 28))
            for i in range(4):                       # the roller door slats
                self.screen.fill((44, 48, 56), (x - 19, y - 12 + i * 7, 38, 2))
            band = (110, 170, 220) if open_now else (78, 84, 92)
            self.screen.fill(band, (x - 20, y - 18, 40, 4))
            if open_now and (self.frame // 14) % 2 == 0:
                self.screen.fill((196, 226, 244), (x - 4, y - 18, 8, 4))

    def draw_potholes(self):
        """An irregular black hole with a ragged asphalt rim and a puddle."""
        for hole in self.potholes:
            sx, sy = self.camera.apply_pos((hole['x'], hole['y']))
            if not (-30 < sx < SCREEN_WIDTH + 30 and -30 < sy < SCREEN_HEIGHT + 30):
                continue
            x, y = int(sx), int(sy)
            n = hole['seed']
            for i in range(6):
                n = (n * 1103515245 + 12345) & 0x7fffffff
                ox = ((n >> 4) % 17) - 8
                oy = ((n >> 11) % 13) - 6
                rad = 4 + ((n >> 18) % 4)
                pygame.draw.circle(self.screen, (26, 24, 26), (x + ox, y + oy), rad)
            pygame.draw.circle(self.screen, (16, 15, 17), (x, y), 6)
            pygame.draw.circle(self.screen, (54, 62, 66), (x - 2, y + 1), 2)
            if hole['cone']:
                # The cone. It has been there for years. It will be there next
                # year. Everyone knows about it. Nobody has moved it.
                self.screen.fill((28, 26, 28), (x + 5, y - 1, 9, 3))
                self.screen.fill((196, 96, 34), (x + 7, y - 9, 5, 9))
                self.screen.fill((228, 226, 218), (x + 7, y - 6, 5, 2))
                self.screen.fill((214, 118, 48), (x + 8, y - 12, 3, 4))

    def draw_dropped_cash(self):
        """A roll of notes where somebody died, blinking as it goes stale."""
        for d in self.dropped:
            age = self.frame - d['born']
            if age > DROPPED_CASH_LIFE:
                continue
            # last five seconds: flash, so you know the clock is running out
            if age > DROPPED_CASH_LIFE - FPS * 5 and (self.frame // 6) % 2 == 0:
                continue
            sx, sy = self.camera.apply_pos((d['x'], d['y']))
            if not (-16 < sx < SCREEN_WIDTH + 16 and -16 < sy < SCREEN_HEIGHT + 16):
                continue
            x, y = int(sx), int(sy) + ((self.frame // 9) % 3 - 1)
            self.screen.fill((20, 26, 20), (x - 7, y + 4, 15, 3))
            self.screen.fill((48, 78, 52), (x - 7, y - 4, 14, 8))    # the band
            self.screen.fill((104, 148, 100), (x - 6, y - 3, 12, 6))
            self.screen.fill((198, 226, 190), (x - 5, y - 2, 10, 2))
            self.screen.fill(hud_HUD_GOLD, (x - 1, y - 1, 3, 3))

    def draw_foot_police(self):
        """Beat cops, with a ring under anyone who currently has eyes on you.

        The ring is the whole readability story for foot cops: the sprite is
        14px in a crowd of 90 other 14px sprites, and you need to know at a
        glance whether the one behind you has seen you or is still guessing.
        """
        for cop in self.foot_police:
            pos = self.camera.apply_pos(cop.rect.center)
            if not (-24 < pos[0] < SCREEN_WIDTH + 24
                    and -24 < pos[1] < SCREEN_HEIGHT + 24):
                continue
            px, py = int(pos[0]), int(pos[1])
            if cop.down_timer <= 0:
                ring = hud_HUD_RED if cop.alert == 'chase' else hud_HUD_GOLD
                if cop.alert == 'chase' and (self.frame // 8) % 2 == 0:
                    ring = _blend(ring, (255, 240, 220), 0.5)
                pygame.draw.ellipse(self.screen, ring, (px - 9, py + 3, 18, 7), 1)
            sprite, shadow = ped_sprite(cop.kind, cop.facing,
                                        cop.down_timer <= 0, cop.anim)
            if cop.down_timer > 0:
                sprite = pygame.transform.rotate(sprite, 90)
                shadow = pygame.transform.rotate(shadow, 90)
            rect = sprite.get_rect(center=(px, py))
            self.screen.blit(shadow, rect.move(SHADOW_DX, SHADOW_DY))
            self.screen.blit(sprite, rect)

    def draw_punch(self):
        """A two-frame arc where the fist lands, so a swing reads on screen."""
        if self.punch_timer <= 0 or self.driving is not None:
            return
        ang = self.aim_angle()
        px, py = self.camera.apply_pos(self.player_rect.center)
        info = WEAPON_DEFS.get(self.weapon, WEAPON_DEFS['fists'])
        reach = info.get('range', PUNCH_RANGE)
        r = reach * (0.55 + 0.45 * (8 - self.punch_timer) / 8.0)
        col = hud_HUD_WHITE if self.punch_timer > 4 else hud_HUD_GREY_DIM
        if self.weapon == 'bat':
            side = -0.62 + (8 - self.punch_timer) / 8.0 * 1.24
            ex = px + math.cos(ang + side) * r
            ey = py + math.sin(ang + side) * r
            pygame.draw.line(self.screen, (194, 142, 84), (int(px), int(py)),
                             (int(ex), int(ey)), 3)
            pygame.draw.circle(self.screen, col, (int(ex), int(ey)), 2)
            return
        for k in (-0.5, 0.0, 0.5):
            ex = px + math.cos(ang + k) * r
            ey = py + math.sin(ang + k) * r
            pygame.draw.line(self.screen, col, (int(px), int(py)),
                             (int(ex), int(ey)), 1)
        fx = px + math.cos(ang) * r
        fy = py + math.sin(ang) * r
        pygame.draw.circle(self.screen, col, (int(fx), int(fy)), 3)

    def draw_fx(self):
        for p in self.fx:
            sx, sy = self.camera.apply_pos((p['x'], p['y']))
            if not (0 <= sx < SCREEN_WIDTH and 0 <= sy < SCREEN_HEIGHT):
                continue
            x, y = int(sx), int(sy)
            k = p['kind']
            if k == 'spark':
                col = (255, 232, 150) if p['life'] > 9 else (224, 122, 40)
                self.screen.fill(col, (x, y, 2, 2))
            elif k == 'glass':
                self.screen.fill((150, 172, 184), (x, y, 1, 2))
            elif k == 'smoke':
                g = min(150, 54 + p['life'] * 4)
                self.screen.fill((g, g, g), (x, y, 2, 2))
            elif k == 'blood':
                self.screen.fill((132, 24, 28) if p['life'] > 10 else (86, 16, 20),
                                 (x, y, 2, 2))
            else:  # debris
                self.screen.fill((88, 82, 74), (x, y, 2, 2))

    @staticmethod
    def _speech_lines(text, max_width=190):
        words = str(text).split()
        lines = []
        current = ''
        for word in words:
            trial = word if not current else f"{current} {word}"
            if current and hud_text_width(trial, 1) > max_width:
                lines.append(current)
                current = word
            else:
                current = trial
        if current:
            lines.append(current)
        return lines or ['...']

    def draw_speech_bubbles(self):
        """Render active dialogue over its speaker instead of in the HUD feed."""
        for bubble in self.speech_bubbles:
            if not bubble['start'] <= self.frame <= bubble['end']:
                continue
            speaker = bubble['speaker']
            anchor = self.active_rect().center if speaker == 'player' else speaker.rect.center
            sx, sy = self.camera.apply_pos(anchor)
            if not (-40 < sx < SCREEN_WIDTH + 40 and -40 < sy < SCREEN_HEIGHT + 40):
                continue
            label = self.speech_label(speaker)
            lines = self._speech_lines(bubble['text'])
            width = max([hud_text_width(label, 1)]
                        + [hud_text_width(line, 1) for line in lines]) + 10
            height = 10 + len(lines) * 9 + 8
            x = max(5, min(SCREEN_WIDTH - width - 5, int(sx - width * 0.5)))
            y = int(sy - height - 16)
            below = y < 5
            if below:
                y = int(sy + 13)
            y = max(5, min(SCREEN_HEIGHT - height - 5, y))

            tip_x = max(x + 5, min(x + width - 6, int(sx)))
            if below:
                pointer = ((tip_x - 4, y), (tip_x + 4, y), (int(sx), int(sy) + 5))
            else:
                pointer = ((tip_x - 4, y + height - 1),
                           (tip_x + 4, y + height - 1), (int(sx), int(sy) - 5))
            pygame.draw.polygon(self.screen, (16, 16, 20), pointer)
            pygame.draw.rect(self.screen, (16, 16, 20), (x, y, width, height))
            pygame.draw.rect(self.screen, (118, 112, 104), (x, y, width, height), 1)
            hud_text(self.screen, label, x + 5, y + 4, hud_HUD_GOLD, False, 1)
            for index, line in enumerate(lines):
                hud_text(self.screen, line, x + 5, y + 13 + index * 9,
                         hud_HUD_WHITE, False, 1)

    def draw_pops(self):
        for p in self.pops:
            age = self.frame - p['born']
            sx, sy = self.camera.apply_pos((p['x'], p['y'] - age * 0.8))
            if -40 < sx < SCREEN_WIDTH + 40 and -20 < sy < SCREEN_HEIGHT + 20:
                hud_text(self.screen, p['text'],
                         int(sx) - hud_text_width(p['text'], 1) // 2, int(sy),
                         p['col'], True, 1)

    def draw_callouts(self):
        y = 34
        for c in self.callouts:
            sc = c['scale']
            if self.frame - c['born'] < 5 and sc > 1:   # scale-punch on spawn
                sc -= 1
            w = hud_text_width(c['text'], sc)
            hud_text(self.screen, c['text'], (SCREEN_WIDTH - w) // 2, y,
                     c['col'], True, sc)
            y += hud_text_height(c['text'], sc) + 5

    def draw_frenzy_icon(self):
        if self.frenzy_icon is None:
            return
        ix, iy, _kind = self.frenzy_icon
        sx, sy = self.camera.apply_pos((ix, iy))
        pulse = (self.frame // 5) % 3
        if -20 < sx < SCREEN_WIDTH + 20 and -20 < sy < SCREEN_HEIGHT + 20:
            for i, rad in enumerate((14 + pulse, 9 + pulse)):
                pygame.draw.circle(self.screen, hud_HUD_RED if i == 0 else (250, 210, 90),
                                   (int(sx), int(sy)), rad, 2)
            hud_text(self.screen, "!", int(sx) - 2, int(sy) - 6, hud_HUD_WHITE, True, 1)

    # ---------------- objective rendering ----------------
    JOB_MARKER_COLORS = ((250, 214, 78), (196, 150, 34))
    JOB_DROP_COLORS = ((110, 226, 118), (44, 146, 62))

    def side_mission_marker(self):
        mission = self.side_mission
        if mission is None:
            return None
        if mission.family == mission_logic.VEHICLE_THEFT:
            if mission.stage in ('steal', 'recover') and self.side_target_car is not None:
                return self.side_target_car.rect.center
            return self.side_target_pos
        if mission.family == mission_logic.SMASH_TARGETS:
            live = [target for target in self.smash_targets if target['hp'] > 0]
            if not live:
                return None
            here = pygame.Vector2(self.active_rect().center)
            return min(live, key=lambda item: here.distance_to(item['pos']))['pos']
        if mission.family == mission_logic.EVADE_HEAT and mission.stage == 'reach_safehouse':
            return self.side_target_pos
        return None

    def side_mission_hud(self):
        mission = self.side_mission
        if mission is None:
            return None
        if mission.family == mission_logic.VEHICLE_THEFT:
            if mission.stage == 'steal':
                sub = "STEAL THE MARKED RIDE"
            elif mission.stage == 'recover':
                sub = "GET BACK IN THE MARKED RIDE"
            else:
                sub = "DELIVER IT TO THE CHOP SHOP"
        elif mission.family == mission_logic.SMASH_TARGETS:
            sub = f"SMASH TARGETS {mission.progress}/{mission.target}"
        elif mission.stage == 'break_contact':
            sub = "BREAK POLICE CONTACT"
        elif mission.stage == 'lay_low':
            remain = max(0, mission.cool_steps - mission.clean_steps)
            sub = f"STAY UNSEEN {math.ceil(remain / FPS)}S"
        else:
            sub = "MAKE THE SAFEHOUSE ON THE HILL"
        return mission.name.upper(), sub, mission.steps_left

    def current_objective_marker(self):
        """One marker contract for world, radar and map."""
        finale_owns = (self.arch_job_unlocked and not self.arch_job_completed and
                       not (self.arch_job_phase == ARCH_READY and self.job is not None
                            and self.job.collected))
        if finale_owns:
            pos = self.arch_job_target_pos()
            if pos is None:
                return None
            colors = (self.JOB_DROP_COLORS if self.arch_job_phase in
                      (ARCH_ESCAPE, ARCH_LAY_LOW) else self.JOB_MARKER_COLORS)
            return pos, colors[0], colors[1]
        local = self.local_challenge_marker()
        if local is not None:
            color = LOCAL_CHALLENGE_COLORS[self.local_challenge['kind']]
            return local, color, _blend(color, (0, 0, 0), 0.5)
        side = self.side_mission_marker()
        if side is not None:
            return side, SIDE_MISSION_MARKER_COLORS[0], SIDE_MISSION_MARKER_COLORS[1]
        if self.job is not None:
            colors = self.JOB_DROP_COLORS if self.job.collected else self.JOB_MARKER_COLORS
            return self.job.target_pos, colors[0], colors[1]
        return None

    def draw_job_marker(self):
        """Ground marker for the current objective, plus an edge-of-screen
        chevron when it is off camera.

        Without this the player is told to go to 'The Hill' and handed a
        100x100 tile city with no indication of which way that is.
        """
        marker = self.current_objective_marker()
        if marker is None:
            return
        (tx, ty), bright, dark = marker
        sx, sy = self.camera.apply_pos((tx, ty))
        pulse = (self.frame // 6) % 4                # 4-step chunky pulse

        margin = 18
        if -margin < sx < SCREEN_WIDTH + margin and -margin < sy < SCREEN_HEIGHT + margin:
            sx, sy = int(sx), int(sy)
            for i, radius in enumerate((16 + pulse, 11 + pulse)):
                pygame.draw.circle(self.screen, dark if i else bright,
                                   (sx, sy), radius, 2)
            pygame.draw.rect(self.screen, bright, (sx - 2, sy - 2, 5, 5))
            return

        # Off-screen: clamp a chevron to the viewport edge, pointing at it.
        cx, cy = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2
        ang = math.atan2(sy - cy, sx - cx)
        ex = max(margin, min(SCREEN_WIDTH - margin, cx + math.cos(ang) * SCREEN_WIDTH))
        ey = max(margin, min(SCREEN_HEIGHT - margin, cy + math.sin(ang) * SCREEN_HEIGHT))
        ex, ey = int(ex), int(ey)
        nose = (ex + int(math.cos(ang) * 9), ey + int(math.sin(ang) * 9))
        left = (ex + int(math.cos(ang + 2.4) * 9), ey + int(math.sin(ang + 2.4) * 9))
        right = (ex + int(math.cos(ang - 2.4) * 9), ey + int(math.sin(ang - 2.4) * 9))
        pygame.draw.polygon(self.screen, dark, (nose, left, right))
        pygame.draw.polygon(self.screen, bright, (nose, left, right), 1)

    # ---------------- overlays ----------------
    PAUSE_LINES = (
        ("W / UP", "FORWARD / ACCELERATE"),
        ("S / DOWN", "BACK UP / BRAKE"),
        ("A D / LEFT RIGHT", "MOVE / STEER"),
        ("LSHIFT", "SPRINT / HANDBRAKE"),
        ("E", "CAR / ACCEPT SIDE JOB"),
        ("R", "REROLL THE RUN ON OFFER"),
        ("SPACE / F", "USE WEAPON"),
        ("Q / WHEEL", "CYCLE WEAPON IN PLAY"),
        ("GAMEPAD", "RT GO  LT BRAKE  A CAR"),
        ("", "LB SPRINT/BRAKE  RB WEAPON"),
        ("", "X / B USE WEAPON"),
        ("M / TAB", "FULL CITY MAP"),
        ("F11", "FULLSCREEN"),
        ("ESC / P", "PAUSE"),
        ("F5 / F9", "SAVE / LOAD"),
        ("F2", "CRT FILTER"),
        ("F3", "DEBUG OVERLAY"),
        ("F4", "MUSIC ON / OFF"),
        ("F6", "CHANGE RADIO STATION"),
        ("Q", "QUIT - FROM HERE ONLY"),
    )

    def draw_pause(self):
        """Pause screen doubling as the controls reference.

        The controls used to be printed to stdout at launch - a terminal the
        player cannot see while the window has focus. They live in the game now.
        """
        dim = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        dim.fill((6, 6, 10, 170))
        self.screen.blit(dim, (0, 0))

        pw, ph = 300, 34 + len(self.PAUSE_LINES) * 12 + 26
        px = (SCREEN_WIDTH - pw) // 2
        py = (SCREEN_HEIGHT - ph) // 2
        hud_draw_panel(self.screen, pygame.Rect(px, py, pw, ph), alpha=232)

        title = "PAUSED"
        hud_text(self.screen, title, px + (pw - hud_text_width(title, 2)) // 2,
                 py + 10, hud_HUD_GOLD, True, 2)
        y = py + 32
        for key, what in self.PAUSE_LINES:
            hud_text(self.screen, key, px + 14, y, hud_HUD_GOLD, True, 1)
            hud_text(self.screen, what, px + 128, y, hud_HUD_WHITE, True, 1)
            y += 12

        stat = f"RUNS {self.jobs_done}  LOST {self.jobs_failed}  BEST X{self.best_streak}"
        hud_text(self.screen, stat, px + (pw - hud_text_width(stat, 1)) // 2,
                 py + ph - 16, hud_HUD_GREY_DIM, True, 1)

    # ---------------- full-city map (M / TAB) ----------------
    def build_map_overview(self):
        """Bake the whole 100x100 tile grid down to one MAP_OVERVIEW_SIZE
        square, with every landmark footprint outlined and numbered. Static,
        so it is built once and cached, same as the HUD radar."""
        mv = MAP_OVERVIEW_SIZE
        surf = pygame.Surface((mv, mv))
        surf.fill((12, 12, 16))
        s = mv / float(MAP_WIDTH)
        cell = max(1, int(math.ceil(TILE_SIZE * s)))
        for r in range(MAP_TILES_H):
            row = GAME_MAP[r]
            py = int(r * TILE_SIZE * s)
            for c in range(MAP_TILES_W):
                surf.fill(row[c]['color'], (int(c * TILE_SIZE * s), py, cell, cell))
        for i, (lx, ly, lw, lh, _kind, _name, color) in enumerate(LANDMARKS, 1):
            rx, ry = int(lx * TILE_SIZE * s), int(ly * TILE_SIZE * s)
            rw = max(4, int(lw * TILE_SIZE * s))
            rh = max(4, int(lh * TILE_SIZE * s))
            pygame.draw.rect(surf, _blend(color, (255, 255, 255), 0.55),
                             (rx, ry, rw, rh), 1)
            tag = str(i)
            hud_text(surf, tag, rx + (rw - hud_text_width(tag, 1)) // 2,
                     ry + (rh - 7) // 2, hud_HUD_WHITE, True, 1)
        return surf

    def draw_map_screen(self):
        """Full-screen city map: where you are, where the job is, where the
        heat is. Freezes the sim while it is up (see run() / handle_events)."""
        mv = MAP_OVERVIEW_SIZE
        if self.map_overview is None:
            self.map_overview = self.build_map_overview()

        # Full opaque repaint - the map owns the screen, and a translucent
        # scrim let the bright HUD ghost through underneath it.
        self.screen.fill((8, 9, 13))
        panel = pygame.Rect(12, 8, SCREEN_WIDTH - 24, SCREEN_HEIGHT - 16)
        hud_draw_panel(self.screen, panel, alpha=255)

        title = "ST. LOUIS"
        hud_text(self.screen, title, (SCREEN_WIDTH - hud_text_width(title, 2)) // 2,
                 panel.top + 7, hud_HUD_GOLD, True, 2)

        mx, my = panel.left + 14, panel.top + 28
        self.screen.blit(self.map_overview, (mx, my))
        pygame.draw.rect(self.screen, hud_HUD_GREY_DIM, (mx - 1, my - 1, mv + 2, mv + 2), 1)
        s = mv / float(MAP_WIDTH)

        def to_map(wx, wy):
            return mx + int(wx * s), my + int(wy * s)

        for shop in self.body_shops:
            sx2, sy2 = to_map(*shop)
            pygame.draw.circle(self.screen, (110, 170, 220), (sx2, sy2), 3)
            pygame.draw.circle(self.screen, (12, 16, 28), (sx2, sy2), 3, 1)

        for kind in sorted(self.legend_rumors):
            lx, ly = to_map(*self.local_legend_marker(kind))
            color = LOCAL_LEGENDS[kind]['color']
            pygame.draw.circle(self.screen, color, (lx, ly), 4, 1)
            hud_text(self.screen,
                     "L" if kind in self.legend_discovered else "?",
                     lx - 2, ly - 3, color, True, 1)

        stx, sty = to_map(*self.police_station)
        pygame.draw.circle(self.screen, (90, 150, 240), (stx, sty), 3)
        pygame.draw.circle(self.screen, (12, 16, 28), (stx, sty), 3, 1)

        finale_marker = (self.current_objective_marker()
                          if self.arch_job_unlocked and not self.arch_job_completed and
                          not (self.arch_job_phase == ARCH_READY and self.job is not None
                               and self.job.collected) else None)
        if finale_marker is not None:
            (pos, bright, _dark) = finale_marker
            jx, jy = to_map(*pos)
            pulse = 5 + (self.frame // 6) % 3
            pygame.draw.circle(self.screen, bright, (jx, jy), 4)
            pygame.draw.circle(self.screen, hud_HUD_WHITE, (jx, jy), pulse, 1)
        elif self.job is not None:
            for pos, col, active in (
                    (self.job.pickup_pos, hud_HUD_GOLD, not self.job.collected),
                    (self.job.drop_pos, hud_HUD_GREEN, self.job.collected)):
                jx, jy = to_map(*pos)
                if active:
                    pulse = 5 + (self.frame // 6) % 3
                    pygame.draw.circle(self.screen, col, (jx, jy), 4)
                    pygame.draw.circle(self.screen, hud_HUD_WHITE, (jx, jy), pulse, 1)
                else:
                    pygame.draw.circle(self.screen, col, (jx, jy), 3, 1)

        for cop in self.police:
            cx, cy = to_map(cop.rect.centerx, cop.rect.centery)
            pygame.draw.circle(self.screen, hud_HUD_RED, (cx, cy), 2)

        active = self.active_rect()
        ppx, ppy = to_map(active.centerx, active.centery)
        pygame.draw.circle(self.screen, hud_HUD_WHITE, (ppx, ppy), 3)
        pygame.draw.circle(self.screen, (0, 0, 0), (ppx, ppy), 3, 1)
        if self.driving:
            pygame.draw.line(self.screen, hud_HUD_WHITE, (ppx, ppy),
                             (ppx + int(math.cos(self.driving.angle) * 10),
                              ppy + int(math.sin(self.driving.angle) * 10)), 2)

        # Street names on the arterials. Cheapest authenticity per byte on
        # the whole map: the grid was already correct, it just had no names.
        for row, name in STREET_ROWS.items():
            _, ly2 = to_map(0, row * TILE_SIZE + TILE_SIZE // 2)
            hud_text(self.screen, name, mx + 3, ly2 - 3, (172, 168, 150), True, 1)
        # North-south names stagger over two rows: at map scale the columns
        # are 26px apart and the names are up to 55px wide, so one row of them
        # was an unreadable smear.
        for i, (col, name) in enumerate(sorted(STREET_COLS.items())):
            lx2, _ = to_map(col * TILE_SIZE + TILE_SIZE // 2, 0)
            w = hud_text_width(name, 1)
            if lx2 - w // 2 < mx or lx2 + w // 2 > mx + mv:
                continue
            hud_text(self.screen, name, lx2 - w // 2,
                     my + mv - (17 if i % 2 else 9), (172, 168, 150), True, 1)

        # The legend runs down the side in as many columns as it needs. With
        # twenty landmarks a single column ran off the bottom of the panel.
        lx0 = mx + mv + 14
        avail = panel.bottom - 20 - my
        rows = max(1, avail // 9)
        entries = [(f"{i} {name}", _blend(color, (255, 255, 255), 0.3))
                   for i, (_a, _b, _c, _d, _kind, name, color)
                   in enumerate(LANDMARKS, 1)]
        entries.append(("", None))
        entries += [("YOU", (232, 232, 232)), ("PICKUP", hud_HUD_GOLD),
                     ("DROP-OFF", hud_HUD_GREEN), ("POLICE", hud_HUD_RED),
                     ("STATION", (90, 150, 240)),
                     ("BODY SHOP $300", (110, 170, 220))]
        for kind, info in LOCAL_LEGENDS.items():
            if kind in self.legend_mastery:
                status = "MASTERED"
            elif kind in self.legend_garage:
                status = "GARAGE"
            elif kind in self.legend_discovered:
                status = "FOUND"
            elif kind in self.legend_rumors:
                status = "RUMOR"
            else:
                status = "???"
            entries.append((f"L {info['name']} {status}", info['color']))
        hydrant_status = "MASTERED" if 'hill_hydrants' in self.legend_mastery else "OPEN"
        trash_status = "MASTERED" if 'trash_day' in self.legend_mastery else "OPEN"
        chain_status = "MASTERED" if 'chain_escape' in self.legend_mastery else "OPEN"
        entries += [(f"HILL HYDRANTS {hydrant_status}", props_C_HILL_GREEN),
                    (f"TRASH DAY {trash_status}", cars_CITY_SERVICE_ORANGE),
                    (f"CHAIN OF ROCKS {chain_status}", (116, 190, 206))]
        colw = 104
        for i, (name, col) in enumerate(entries):
            cx = lx0 + (i // rows) * colw
            cy = my + (i % rows) * 9
            if not name:
                continue
            if col is not None:
                self.screen.fill(col, (cx, cy + 1, 5, 5))
            hud_text(self.screen, name, cx + 8, cy, hud_HUD_WHITE, True, 1)

        hint = "M / TAB / ESC  CLOSE MAP"
        hud_text(self.screen, hint, (SCREEN_WIDTH - hud_text_width(hint, 1)) // 2,
                 panel.bottom - 13, hud_HUD_GREY_DIM, True, 1)

    # Chase state, read straight off the police senses. Without this the
    # line-of-sight rules are invisible and the player never learns that
    # ducking into a gangway is a move - so it sits right under the stars.
    _CHASE_STATES = (
        ('spotted', "SPOTTED", hud_HUD_RED),
        ('searching', "SEARCHING", hud_HUD_GOLD),
        ('hidden', "HIDDEN", hud_HUD_GREEN),
    )

    def draw_grub_strip(self, right, y):
        """Whatever you last ate, and how long it has left, right-aligned."""
        for key in GRUB_KINDS:
            if not self.grub_active(key):
                continue
            label, _secs, col, _marker, _blurb = GRUB_KINDS[key]
            txt = f"{label} {self.grub_seconds_left(key)}"
            hud_text(self.screen, txt, right - hud_text_width(txt, 1), y, col, True, 1)
            y += 10

    def draw_chase_state(self, right, y, ticks):
        if self.wanted_level <= 0 and not self.hidden:
            return
        if self.spotted:
            key, label, color = self._CHASE_STATES[0]
        elif self.hidden:
            key, label, color = self._CHASE_STATES[2]
        elif self.searching:
            key, label, color = self._CHASE_STATES[1]
        else:
            return
        # SPOTTED blinks; the two good states hold steady so relief reads.
        if key == 'spotted' and (ticks // 220) % 2 == 0:
            color = _blend(color, (255, 220, 200), 0.55)
        w = hud_text_width(label, 1)
        hud_text(self.screen, label, right - w, y, color, True, 1)

    def draw_debug(self):
        """F3 readout. Frame budget, sim steps and world state in one place -
        previously there was no way to tell a 60fps run from a 20fps one."""
        active = self.active_rect()
        lines = (
            f"FPS {self.fps_now:0.0f}  STEPS {self.sim_steps}",
            f"TILE {active.centerx // TILE_SIZE},{active.centery // TILE_SIZE}",
            f"CARS {len(self.cars)}  COPS {len(self.police)}  PEDS {len(self.pedestrians)}",
            f"WANTED {self.wanted_level}  HEAT {self.heat_timer}  BUST {self.bust_meter}",
            f"SEEN {int(self.spotted)}  HUNT {int(self.searching)}  "
            f"HIDE {int(self.hidden)}  DISP {self.cop_dispatch}",
            f"STATE {'DRIVE' if self.driving else 'FOOT'}  FRAME {self.frame}",
        )
        w = max(hud_text_width(s, 1) for s in lines) + 12
        top = self.hud_left_y + 4
        hud_draw_panel(self.screen, pygame.Rect(8, top, w, len(lines) * 10 + 8), alpha=190)
        for i, s in enumerate(lines):
            hud_text(self.screen, s, 14, top + 4 + i * 10, hud_HUD_GREEN, True, 1)

    def build_radar_base(self):
        """Pre-render the whole city once, big, so the radar can window into it.

        The previous HUD re-filled a 40x40 grid of rects every single frame,
        which profiled as roughly half the total frame cost; the map never
        changes, so it is baked. It is now baked at RADAR_BASE_PX rather than
        at radar size, because the radar shows a moving window rather than the
        entire map - a 640KB surface, and one subsurface + scale per frame.
        """
        surf = pygame.Surface((RADAR_BASE_PX, RADAR_BASE_PX))
        surf.fill((16, 16, 22))
        cell = max(1, RADAR_BASE_PX // MAP_TILES_W + 1)
        for r in range(MAP_TILES_H):
            py = r * RADAR_BASE_PX // MAP_TILES_H
            for c in range(MAP_TILES_W):
                surf.fill(GAME_MAP[r][c]['color'],
                          (c * RADAR_BASE_PX // MAP_TILES_W, py, cell, cell))
        return surf

    def draw_radar(self, rx, ry):
        """A local window on the city, with the player as a pointed triangle
        and anything important outside the window pinned to the rim.

        The rim chevrons are the piece the old whole-map radar structurally
        could not provide: "they are coming from the north" is the single most
        useful thing a chase radar can tell you.
        """
        if self.radar_base is None:
            self.radar_base = self.build_radar_base()
        active = self.active_rect()
        cx, cy = active.center
        half = RADAR_WORLD * 0.5
        # world -> base-surface pixels
        b = RADAR_BASE_PX / float(MAP_WIDTH)
        win = int(RADAR_WORLD * b)
        bx = int(max(0, min(RADAR_BASE_PX - win, (cx - half) * b)))
        by = int(max(0, min(RADAR_BASE_PX - win, (cy - half) * b)))
        view = self.radar_base.subsurface(pygame.Rect(bx, by, win, win))
        self.screen.blit(pygame.transform.scale(view, (RADAR_SIZE, RADAR_SIZE)),
                         (rx, ry))

        # world -> radar pixels, for whatever is inside the window
        left = bx / b
        top = by / b
        k = RADAR_SIZE / float(RADAR_WORLD)

        def blip(pos, colour, size=2):
            px = rx + (pos[0] - left) * k
            py = ry + (pos[1] - top) * k
            if rx <= px < rx + RADAR_SIZE and ry <= py < ry + RADAR_SIZE:
                self.screen.fill(colour, (int(px) - size // 2, int(py) - size // 2,
                                          size, size))
                return True
            return False

        def chevron(pos, colour):
            """Pin an off-window thing to the rim at its true bearing."""
            ang = math.atan2(pos[1] - cy, pos[0] - cx)
            r = RADAR_SIZE * 0.5 - 4
            px = int(rx + RADAR_SIZE * 0.5 + math.cos(ang) * r)
            py = int(ry + RADAR_SIZE * 0.5 + math.sin(ang) * r)
            tip = (px + math.cos(ang) * 3, py + math.sin(ang) * 3)
            a = (px + math.cos(ang + 2.4) * 4, py + math.sin(ang + 2.4) * 4)
            c = (px + math.cos(ang - 2.4) * 4, py + math.sin(ang - 2.4) * 4)
            pygame.draw.polygon(self.screen, colour,
                                [(int(tip[0]), int(tip[1])),
                                 (int(a[0]), int(a[1])), (int(c[0]), int(c[1]))])

        for shop in self.body_shops:
            blip(shop, (110, 170, 220), 3)
        for d in self.dropped:
            blip((d['x'], d['y']), hud_HUD_GREEN, 3)
        for g in self.grub_pickups:
            if not g['taken']:
                blip((g['x'], g['y']), GRUB_KINDS[g['kind']][3], 2)
        for kind in self.legend_rumors:
            blip(self.local_legend_marker(kind), LOCAL_LEGENDS[kind]['color'],
                 4 if kind in self.legend_discovered else 3)
        if self.frenzy_icon is not None:
            blip(self.frenzy_icon[:2], hud_HUD_RED, 3)
        if self.side_mission is None and self.side_mission_cooldown <= 0:
            contact, _name = self.side_mission_contact()
            blip(contact, SIDE_MISSION_MARKER_COLORS[0], 3)
        marker = self.current_objective_marker()
        if marker is not None:
            pos, bright, _dark = marker
            if not blip(pos, bright, 3):
                chevron(pos, bright)
        for cop in list(self.police) + list(self.foot_police):
            if not blip(cop.rect.center, hud_HUD_RED, 2):
                chevron(cop.rect.center, hud_HUD_RED)
        for block in self.roadblocks:
            if not blip(block['center'], (246, 194, 52), 5):
                chevron(block['center'], (246, 194, 52))

        # the player: a triangle pointed the way you are actually facing, which
        # a dot can never be, and which is most of why the old radar was hard
        # to navigate by
        if self.driving is not None:
            head = self.driving.angle
        elif self.player_dir[0] or self.player_dir[1]:
            head = math.atan2(self.player_dir[1], self.player_dir[0])
        else:
            head = self.player_aim
        pcx = rx + RADAR_SIZE * 0.5
        pcy = ry + RADAR_SIZE * 0.5
        pts = [(pcx + math.cos(head) * 5, pcy + math.sin(head) * 5),
               (pcx + math.cos(head + 2.5) * 4, pcy + math.sin(head + 2.5) * 4),
               (pcx + math.cos(head - 2.5) * 4, pcy + math.sin(head - 2.5) * 4)]
        pygame.draw.polygon(self.screen, hud_HUD_WHITE,
                            [(int(x), int(y)) for x, y in pts])
        hud_draw_radar_frame(self.screen, pygame.Rect(rx, ry, RADAR_SIZE, RADAR_SIZE))

    def draw_place_names(self, right):
        """The street you are on, bottom right, and a neighbourhood title
        across the middle for a moment after you cross a boundary."""
        if self.street_now:
            txt = self.street_now
            w = hud_text_width(txt, 1)
            x = right - w
            y = SCREEN_HEIGHT - 16
            pygame.draw.rect(self.screen, (12, 12, 16), (x - 4, y - 3, w + 8, 13))
            hud_text(self.screen, txt, x, y, hud_HUD_WHITE, True, 1)
        if self.hood_banner > 0 and self.hood_now:
            txt = hood_name(self.hood_now)
            fade = min(1.0, self.hood_banner / float(FPS))
            w = hud_text_width(txt, 2)
            x = (SCREEN_WIDTH - w) // 2
            y = SCREEN_HEIGHT - 62
            box = pygame.Rect(x - 8, y - 5, w + 16, 22)
            shade = pygame.Surface(box.size, pygame.SRCALPHA)
            shade.fill((10, 10, 14, int(190 * fade)))
            self.screen.blit(shade, box.topleft)
            pygame.draw.rect(self.screen, hud_HUD_GOLD, box, 1)
            hud_text(self.screen, txt, x, y, hud_HUD_GOLD, True, 2)

    def draw_hud(self):
        """GTA1 arcade gauge: chunky score and cash right-aligned at the top,
        wanted stars and the radar stacked beneath on the same right edge."""
        right = SCREEN_WIDTH - 10
        ticks = pygame.time.get_ticks()

        self.draw_place_names(right)
        hud_draw_score(self.screen, self.score, right, 6, 2)
        # Two numbers, because they mean different things: white is the roll
        # in your pocket, which you lose when you are killed, and gold is what
        # you have banked under the Arch, which is yours for good.
        hud_draw_cash(self.screen, self.cash, right, 24, 2)
        if self.arch_job_completed:
            btxt = "ARCH JOB COMPLETE"
        elif self.arch_job_unlocked:
            btxt = "ARCH JOB READY" if self.arch_job_phase == ARCH_READY else "ARCH JOB ACTIVE"
        else:
            btxt = f"ARCH ${int(self.banked)}/${ARCH_JOB_TARGET}"
        hud_text(self.screen, btxt, right - hud_text_width(btxt, 1), 42,
                 hud_HUD_GOLD, True, 1)

        # slots=WANTED_MAX, not the default 6: the sixth slot was
        # unreachable by construction and ate 13px of the block forever.
        star_w = hud_draw_stars(self.screen, self.wanted_level,
                                right - STAR_BLOCK_W, 53, ticks,
                                slots=WANTED_MAX,
                                blink=not self.spotted and self.wanted_level > 0)[0]
        self.draw_chase_state(right, 64, ticks)

        # radar, aligned to the same right edge as the gauge above it
        rx, ry = right - RADAR_SIZE, 76
        self.draw_radar(rx, ry)

        # speedometer, immediately under the radar. Speed was previously not
        # represented anywhere on screen - no number, no bar, no engine note -
        # in a game whose entire verb is driving.
        if self.driving is not None:
            gear = self.driving.drive_gear()
            v = abs(self.driving.velocity)
            frac = min(1.0, v / max(1.0, self.driving.base_max_speed))
            bar_y = ry + RADAR_SIZE + 5
            pygame.draw.rect(self.screen, (30, 30, 38), (rx, bar_y, RADAR_SIZE, 5))
            col = ((174, 224, 232) if gear == 'R'
                   else hud_HUD_RED if frac > 0.92
                   else hud_HUD_GOLD if frac > 0.70 else hud_HUD_WHITE)
            pygame.draw.rect(self.screen, col,
                             (rx, bar_y, int(RADAR_SIZE * frac), 5))
            mph = f"{gear} {int(v * HUD_MPH_PER_PX)} MPH"
            hud_text(self.screen, mph, right - hud_text_width(mph, 1),
                     bar_y + 7, hud_HUD_GREY_DIM, True, 1)
            station = RADIO_STATIONS[self.radio_index]['name']
            hud_text(self.screen, station, right - hud_text_width(station, 1),
                     bar_y + 16, RADIO_STATIONS[self.radio_index]['color'], True, 1)
            if self.driving.puncture_steps > 0:
                tires = f"TIRES {math.ceil(self.driving.puncture_steps / FPS)}S"
                hud_text(self.screen, tires, right - hud_text_width(tires, 1),
                         bar_y + 25, hud_HUD_RED, True, 1)

        # chaos multiplier + its progress bar, under the speedo
        cy0 = ry + RADAR_SIZE + 35
        # A multiplier of 1 is no multiplier; the old `or mult_prog > 0`
        # drew "X1" with a bar, which is a HUD element meaning nothing.
        if self.multiplier > 1:
            mtxt = f"X{self.multiplier}"
            hud_text(self.screen, mtxt, right - hud_text_width(mtxt, 2), cy0,
                     hud_HUD_GOLD, True, 2)
            fr = 1.0 if self.multiplier >= MULT_MAX else self.mult_prog / MULT_RUNG
            pygame.draw.rect(self.screen, (30, 30, 38), (rx, cy0 + 17, RADAR_SIZE, 3))
            pygame.draw.rect(self.screen, hud_HUD_GOLD,
                             (rx, cy0 + 17, int(RADAR_SIZE * max(0.0, min(1.0, fr))), 3))
        if self.frenzy is not None:
            ft = f"FRENZY {self.frenzy.remaining}  {self.frenzy.steps_left // FPS}S"
            hud_text(self.screen, ft, right - hud_text_width(ft, 1), cy0 + 24,
                     hud_HUD_RED, True, 1)

        self.hud_left_y = self.draw_objective()
        self.draw_bust_meter()
        self.draw_grub_strip(right, ry + RADAR_SIZE + 44)

        # damage / health bar, bottom left above the toasts
        # Always on. A bar that only appears once you are hurt means you
        # learn where it lives during the one moment you cannot afford to go
        # looking for it. DAMAGE also renamed: a bar labelled DAMAGE that
        # empties as you take damage is backwards.
        hp_frac = self.player_hp / PLAYER_MAX_HP
        hlabel = "HEALTH"
        if self.driving is not None:
            hp_frac = self.driving.hp / self.driving.max_hp
            hlabel = "CAR"
        if hp_frac is not None:
            by = SCREEN_HEIGHT - 72
            pygame.draw.rect(self.screen, (30, 30, 38), (12, by, 78, 4))
            hcol = (hud_HUD_GREEN if hp_frac > 0.5
                    else hud_HUD_GOLD if hp_frac > 0.25 else hud_HUD_RED)
            pygame.draw.rect(self.screen, hcol, (12, by, int(78 * max(0.0, hp_frac)), 4))
            hud_text(self.screen, hlabel, 12, by - 10, hud_HUD_GREY_DIM, True, 1)
            if self.driving is None:
                stamina = max(0.0, min(1.0, self.player_stamina / PLAYER_STAMINA_MAX))
                pygame.draw.rect(self.screen, (30, 30, 38), (100, by, 64, 4))
                scol = hud_HUD_GOLD if self.sprint_ready else hud_HUD_GREY_DIM
                pygame.draw.rect(self.screen, scol, (100, by, int(64 * stamina), 4))
                hud_text(self.screen, "SPRINT", 100, by - 10,
                         hud_HUD_GREY_DIM, True, 1)

        # mode + weapon readout, bottom left
        mode = "DRIVING" if self.driving else "ON FOOT"
        hud_text(self.screen, mode, 12, SCREEN_HEIGHT - 18, hud_HUD_GOLD, True, 1)
        info = WEAPON_DEFS.get(self.weapon, WEAPON_DEFS['fists'])
        arm = info['label'] if info.get('melee') else f"{info['label']} {self.ammo}"
        hud_text(self.screen, arm, 12 + hud_text_width(mode, 1) + 12,
                 SCREEN_HEIGHT - 18,
                 hud_HUD_WHITE if self.weapon != 'fists' else hud_HUD_GREY_DIM, True, 1)

        # toasts stack above the mode readout
        for i, toast in enumerate(reversed(self.toasts[-3:])):
            hud_text(self.screen, toast.text, 12, SCREEN_HEIGHT - 32 - i * 12,
                     hud_HUD_WHITE, True, 1)

    def draw_objective(self):
        """Top-left objective block: what to do, where, and how long you have.

        Returns the y the next left-column overlay may start at.
        """
        finale_owns = (self.arch_job_unlocked and not self.arch_job_completed and
                       not (self.arch_job_phase == ARCH_READY and self.job is not None
                            and self.job.collected))
        arch_text = self.arch_job_objective_text() if finale_owns else None
        if arch_text is not None:
            head, sub, timed = arch_text
            clock_gutter = hud_text_width("000", 1) + 8 if timed else 0
            pw = max(hud_text_width(head, 1) + clock_gutter,
                     hud_text_width(sub, 1)) + 16
            ph = 40 if timed else 34
            hud_draw_panel(self.screen, pygame.Rect(8, 8, pw, ph), alpha=215)
            color = hud_HUD_GREEN if self.arch_job_phase == ARCH_LAY_LOW else hud_HUD_GOLD
            hud_text(self.screen, head, 15, 13, color, True, 1)
            hud_text(self.screen, sub, 15, 24, hud_HUD_GREY_DIM, True, 1)
            if timed:
                frac = self.arch_job_timer / float(max(1, ARCH_JOB_SECONDS * FPS))
                bw = pw - 16
                bar = pygame.Rect(15, 34, bw, 4)
                pygame.draw.rect(self.screen, (30, 30, 38), bar)
                fill = int(bw * max(0.0, min(1.0, frac)))
                if fill:
                    pygame.draw.rect(self.screen,
                                     hud_HUD_RED if frac < 0.25 else hud_HUD_GREEN,
                                     (bar.x, bar.y, fill, bar.h))
                secs = str(int(math.ceil(self.arch_job_timer / float(FPS))))
                hud_text(self.screen, secs,
                         8 + pw - hud_text_width(secs, 1) - 7, 13,
                         hud_HUD_RED if frac < 0.25 else hud_HUD_WHITE, True, 1)
            return 8 + ph

        local_text = self.local_challenge_hud()
        if local_text is not None:
            head, sub, steps_left, limit = local_text
            head = self._fit_menu_text(head, 254)
            sub = self._fit_menu_text(sub, 254)
            clock_gutter = hud_text_width("000", 1) + 8
            pw = min(286, max(hud_text_width(head, 1) + clock_gutter,
                              hud_text_width(sub, 1)) + 16)
            hud_draw_panel(self.screen, pygame.Rect(8, 8, pw, 40), alpha=218)
            color = LOCAL_CHALLENGE_COLORS[self.local_challenge['kind']]
            hud_text(self.screen, head, 15, 13, color, True, 1)
            hud_text(self.screen, sub, 15, 24, hud_HUD_WHITE, True, 1)
            frac = steps_left / float(max(1, limit))
            bw = pw - 16
            pygame.draw.rect(self.screen, (30, 30, 38), (15, 34, bw, 4))
            pygame.draw.rect(self.screen, hud_HUD_RED if frac < 0.25 else color,
                             (15, 34, int(bw * max(0.0, min(1.0, frac))), 4))
            secs = str(int(math.ceil(steps_left / float(FPS))))
            hud_text(self.screen, secs, 8 + pw - hud_text_width(secs, 1) - 7,
                     13, hud_HUD_RED if frac < 0.25 else hud_HUD_WHITE, True, 1)
            return 48

        side_text = self.side_mission_hud()
        if side_text is not None:
            head, sub, steps_left = side_text
            head = self._fit_menu_text(head, 254)
            sub = self._fit_menu_text(sub, 254)
            clock_gutter = hud_text_width("000", 1) + 8
            pw = min(286, max(hud_text_width(head, 1) + clock_gutter,
                              hud_text_width(sub, 1)) + 16)
            hud_draw_panel(self.screen, pygame.Rect(8, 8, pw, 40), alpha=218)
            hud_text(self.screen, head, 15, 13,
                     SIDE_MISSION_MARKER_COLORS[0], True, 1)
            hud_text(self.screen, sub, 15, 24, hud_HUD_WHITE, True, 1)
            frac = steps_left / float(max(1, self.side_mission.time_limit_steps))
            bw = pw - 16
            pygame.draw.rect(self.screen, (30, 30, 38), (15, 34, bw, 4))
            pygame.draw.rect(self.screen,
                             hud_HUD_RED if frac < 0.25 else SIDE_MISSION_MARKER_COLORS[0],
                             (15, 34, int(bw * max(0.0, min(1.0, frac))), 4))
            secs = str(int(math.ceil(steps_left / float(FPS))))
            hud_text(self.screen, secs,
                     8 + pw - hud_text_width(secs, 1) - 7, 13,
                     hud_HUD_RED if frac < 0.25 else hud_HUD_WHITE, True, 1)
            return 48

        if self.job is None:
            return 8
        job = self.job
        verb = "DELIVER TO" if job.collected else "PICK UP AT"
        col = hud_HUD_GREEN if job.collected else hud_HUD_GOLD
        head = f"{verb} {job.target_name}"
        sub = (f"{job.label}: {job.cargo} / CITY +10%" if job.collected
               else f"{job.label}  PAYS ${job.base_reward} + CITY 10%")

        # The countdown is drawn right-aligned on the headline row, so the
        # panel has to reserve a gutter for it or a long landmark name runs
        # straight under the digits.
        clock_gutter = hud_text_width("000", 1) + 8 if job.collected else 0
        pw = max(hud_text_width(head, 1) + clock_gutter, hud_text_width(sub, 1)) + 16
        ph = 40 if job.collected else 34
        hud_draw_panel(self.screen, pygame.Rect(8, 8, pw, ph), alpha=205)
        hud_text(self.screen, head, 15, 13, col, True, 1)
        hud_text(self.screen, sub, 15, 24, hud_HUD_GREY_DIM, True, 1)

        if job.collected:
            # Timer bar; turns red inside the last quarter so the pressure reads
            # at a glance without having to parse a number.
            frac = job.steps_left / float(max(1, int(job.time_limit * FPS)))
            bw = pw - 16
            fill = int(bw * max(0.0, min(1.0, frac)))
            bar = pygame.Rect(15, 34, bw, 4)
            pygame.draw.rect(self.screen, (30, 30, 38), bar)
            if fill > 0:
                shade = hud_HUD_RED if frac < 0.25 else hud_HUD_GREEN
                pygame.draw.rect(self.screen, shade, (bar.x, bar.y, fill, bar.h))
            secs = f"{job.seconds_left:0.0f}"
            hud_text(self.screen, secs, 8 + pw - hud_text_width(secs, 1) - 7, 13,
                     hud_HUD_RED if frac < 0.25 else hud_HUD_WHITE, True, 1)

        y = 8 + ph
        if self.streak > 1:
            s = f"STREAK X{self.streak}"
            hud_text(self.screen, s, 15, y + 3, hud_HUD_GOLD, True, 1)
            y += 14
        return y

    def draw_bust_meter(self):
        """Sustained-contact bar. Shows you are being taken, and that letting
        go of the throttle is not the same as being caught."""
        if self.bust_meter <= 0:
            return
        frac = min(1.0, self.bust_meter / float(BUST_CONTACT_STEPS))
        bw = 96
        x = (SCREEN_WIDTH - bw) // 2
        y = SCREEN_HEIGHT - 34
        label = "BUSTING"
        hud_text(self.screen, label, x + (bw - hud_text_width(label, 1)) // 2,
                 y - 11, hud_HUD_RED, True, 1)
        pygame.draw.rect(self.screen, (30, 30, 38), (x, y, bw, 5))
        pygame.draw.rect(self.screen, hud_HUD_RED, (x, y, int(bw * frac), 5))

    # ---------------- main loop ----------------
    def step_sim(self, elapsed):
        """Spend `elapsed` real seconds as whole 1/60s simulation steps.

        Everything in this file - PLAYER_SPEED, car acceleration, drag, steer
        rates, traffic pacing, timers - is authored per step, and the old loop
        just called update() once per rendered frame. That silently tied the
        speed of the whole game to the frame rate: a machine holding 30fps
        played the entire city in half speed, and one running unlocked played
        it at double. Banking real time and spending it in fixed slices keeps
        the sim identical everywhere, and the MAX_SIM_STEPS clamp stops a long
        stall (dragging the window, waking from sleep) from spiralling into a
        hundred catch-up steps at once.
        """
        self.accumulator += min(elapsed, MAX_FRAME_TIME)
        steps = 0
        while self.accumulator >= SIM_DT and steps < MAX_SIM_STEPS:
            self.update()
            self.accumulator -= SIM_DT
            steps += 1
        if self.accumulator > SIM_DT * MAX_SIM_STEPS:
            self.accumulator = 0.0          # too far behind; drop the debt
        self.sim_steps = steps
        return steps

    def should_advance_sim(self):
        """Whether wall-clock time should be converted into simulation steps."""
        return self.state in (STATE_PLAYING, STATE_DEAD) and not self.show_map

    def run(self):
        print("=" * 60)
        print("  STL-GTA: St. Louis Open-World Sandbox")
        print("=" * 60)
        print("  Deliver cargo between landmarks for cash. Cops want a word.")
        print("  M / TAB - Full city map    F11 - Fullscreen")
        print("  ESC / P - Pause (full controls listed there)")
        print("=" * 60)
        self.add_toast("M for the map  -  ESC for controls")

        self.accumulator = 0.0
        while self.running:
            elapsed = self.clock.tick(FPS) / 1000.0
            self.fps_now = self.clock.get_fps()
            self.handle_events()
            self.sync_soundtrack()
            if not self.running:
                break
            if self.should_advance_sim():
                self.step_sim(elapsed)
            else:
                self.accumulator = 0.0      # do not bank time while paused / mapping
                self.sim_steps = 0
            self.draw()

        if self.music_started and pygame.mixer.get_init() is not None:
            pygame.mixer.music.stop()
        pygame.quit()

    # ---------------- headless ----------------
    def run_headless(self, frames, shot_path=None, seed=None):
        """Boot, simulate `frames` steps with scripted input, check invariants.

        This is what makes the game testable in CI: no window, no player, no
        wall clock. Returns 0 on success and 1 on the first invariant breach,
        with the failure printed.
        """
        rng = random.Random(seed if seed is not None else 1234)
        script = [(pygame.K_w, 0.55), (pygame.K_a, 0.15), (pygame.K_d, 0.15)]
        self.add_toast("Headless run")
        for i in range(frames):
            if i % 90 == 0:
                self.toggle_enter_exit()
            if self.driving:
                self.driving.input_throttle = 1.0
                self.driving.input_steer = rng.choice((-1.0, 0.0, 0.0, 1.0))
            else:
                self.player_dir = [rng.choice((-1, 0, 1)), rng.choice((-1, 0, 1))]
            self.step_sim(SIM_DT)
            self.draw()
            problem = self.check_invariants()
            if problem:
                print(f"FAIL at step {i}: {problem}")
                return 1
        if shot_path:
            pygame.image.save(self.window, shot_path)
            print(f"wrote {shot_path}")
        print(f"OK: {frames} steps, {len(self.cars)} cars, {len(self.pedestrians)} peds, "
              f"score={self.score} cash={self.cash} runs={self.jobs_done}")
        return 0

    def check_invariants(self):
        """Things that must hold every single step. Returns a reason or None."""
        def finite(*vals):
            return all(v == v and abs(v) != float('inf') for v in vals)

        p = self.active_rect()
        if not (0 <= p.centerx <= MAP_WIDTH and 0 <= p.centery <= MAP_HEIGHT):
            return f"player left the map at {p.center}"
        if not 0 <= self.wanted_level <= WANTED_MAX:
            return f"wanted level out of range: {self.wanted_level}"
        # Cops are dispatched on a delay now (COP_RESPONSE_BY_STAR), so the
        # count climbs *toward* the star's quota rather than matching it the
        # same step. The invariant that still has to hold absolutely is that
        # it never exceeds the quota, and that zero stars means zero cops.
        quota = COP_COUNT_BY_STAR[self.wanted_level]
        if len(self.police) > quota:
            return (f"police count {len(self.police)} exceeds "
                    f"{quota} for {self.wanted_level} stars")
        if self.wanted_level == 0 and self.police:
            return f"{len(self.police)} cops on the street at zero stars"
        foot_quota = COP_FOOT_BY_STAR[self.wanted_level]
        if len(self.foot_police) > foot_quota:
            return (f"foot cop count {len(self.foot_police)} exceeds "
                    f"{foot_quota} for {self.wanted_level} stars")
        for cop in self.foot_police:
            if not (0 <= cop.rect.centerx <= MAP_WIDTH
                    and 0 <= cop.rect.centery <= MAP_HEIGHT):
                return f"foot cop left the map at {cop.rect.center}"
        roadblock_quota = ROADBLOCK_COUNT_BY_STAR[self.wanted_level]
        if len(self.roadblocks) > roadblock_quota:
            return (f"roadblock count {len(self.roadblocks)} exceeds "
                    f"{roadblock_quota} for {self.wanted_level} stars")
        for block in self.roadblocks:
            col = block['center'][0] // TILE_SIZE
            row = block['center'][1] // TILE_SIZE
            if tile_type_at(col, row) != TILE_ROAD or is_blocked(block['strip']):
                return f"roadblock left road geometry at {block['center']}"
            if len(block['cars']) != 2 or any(is_blocked(car.rect) for car in block['cars']):
                return f"roadblock has illegal cruiser footprint at {block['center']}"
        for train in (vehicle for vehicle in self.rail
                      if vehicle.kind == 'metrolink'):
            if not 0.0 <= train.s <= train.length:
                return f"MetroLink left its track bounds at s={train.s:.1f}"
            # The body must stay on reserved rail. Sample the centre line
            # rather than the corners: a train is longer than the 64px tile
            # it turns through, so on a corner its bounding box legitimately
            # overhangs the block on the inside of the curve.
            for ahead in (-train.w * 0.4, 0.0, train.w * 0.4):
                col = max(0, min(MAP_TILES_W - 1,
                                 int(train.x + train.dx * ahead) // TILE_SIZE))
                row = max(0, min(MAP_TILES_H - 1,
                                 int(train.y + train.dy * ahead) // TILE_SIZE))
                tile = GAME_MAP[row][col]
                if tile['collidable'] or tile.get('rail') != 'metrolink':
                    return f"MetroLink left reserved rail at {col},{row}"
        for crossing in self.rail_crossings:
            if not 0.0 <= crossing.arm <= 1.0:
                return f"rail gate arm out of range at column {crossing.col}"
            tile = GAME_MAP[crossing.row][crossing.col]
            if tile['type'] != TILE_ROAD or not tile.get('rail_crossing'):
                return (f"rail crossing lost road geometry at "
                        f"{crossing.col},{crossing.row}")
        if self.cash < 0:
            return f"negative cash: {self.cash}"
        if self.score < 0:
            return f"negative score: {self.score}"
        if not 1 <= self.multiplier <= MULT_MAX:
            return f"multiplier out of range: {self.multiplier}"
        if not finite(self.player_hp) or self.player_hp > PLAYER_MAX_HP + 0.5:
            return f"player hp out of range: {self.player_hp}"
        if (not finite(self.player_stamina)
                or not 0 <= self.player_stamina <= PLAYER_STAMINA_MAX + 0.5):
            return f"player stamina out of range: {self.player_stamina}"
        if self.weapon not in WEAPON_DEFS or self.weapon not in self.owned_weapons:
            return f"invalid selected weapon: {self.weapon}"
        if self.ammo < 0:
            return f"negative ammo: {self.ammo}"
        if self.frenzy is not None and self.frenzy.steps_left < 0:
            return "frenzy timer went negative"
        valid_arch = {ARCH_LOCKED, ARCH_READY, ARCH_CUTTER, ARCH_RETURN,
                      ARCH_ESCAPE, ARCH_LAY_LOW, ARCH_COMPLETE}
        if self.arch_job_phase not in valid_arch:
            return f"invalid Arch job phase: {self.arch_job_phase}"
        if self.arch_job_completed and self.arch_job_phase != ARCH_COMPLETE:
            return "completed Arch job left its completion phase"
        if self.arch_job_phase != ARCH_LOCKED and not self.arch_job_unlocked:
            return "locked Arch job has an active phase"
        if self.arch_job_timer < 0:
            return "Arch job timer went negative"
        if len(self.fx) > 240 or len(self.pops) > 48 or len(self.callouts) > 3:
            return "a feedback pool grew unbounded"
        for ped in self.pedestrians:
            if not pedestrian_ground_is_clear(ped.rect):
                col = ped.rect.centerx // TILE_SIZE
                row = ped.rect.centery // TILE_SIZE
                return f"pedestrian left walkable ground at {col},{row}"
        for car in self.cars + self.police:
            if not finite(car.angle, car.velocity, car.hp):
                return f"car physics went non-finite: {car.variant}"
            if not -1.0 <= car.hp <= car.max_hp + 0.5:
                return f"car hp out of range: {car.hp}/{car.max_hp}"
            if not (-TILE_SIZE <= car.rect.centerx <= MAP_WIDTH + TILE_SIZE
                    and -TILE_SIZE <= car.rect.centery <= MAP_HEIGHT + TILE_SIZE):
                return f"car left the map at {car.rect.center}"
        for cop in self.foot_police:
            if not finite(cop.fx, cop.fy, cop.hp) or not 0 < cop.hp <= COP_FOOT_HP:
                return f"foot cop state invalid: {cop.hp} at {cop.rect.center}"
        if self.job is not None and self.job.collected and self.job.steps_left < 0:
            return "job timer went negative"
        if self.driving is not None and self.driving.driver != 'player':
            return "driving a car that does not know it has a driver"
        return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="stl-gta", description="STL-GTA: a top-down St. Louis driving sandbox.")
    parser.add_argument("--headless", action="store_true",
                        help="run without a window and exit (smoke test / CI)")
    parser.add_argument("--frames", type=int, default=600,
                        help="simulation steps to run in headless mode")
    parser.add_argument("--shot", metavar="PATH",
                        help="save a PNG of the final headless frame")
    parser.add_argument("--seed", type=int, help="seed the RNG for a repeatable run")
    parser.add_argument("--windowed", action="store_true",
                        help="start in a resizable window instead of fullscreen (F11 toggles either way)")
    args = parser.parse_args(argv)

    if args.headless:
        # Must be set before pygame opens a display.
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    if args.seed is not None:
        random.seed(args.seed)

    game = Game(start_fullscreen=not args.windowed)
    if args.headless:
        code = game.run_headless(args.frames, args.shot, args.seed)
        pygame.quit()
        return code
    game.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

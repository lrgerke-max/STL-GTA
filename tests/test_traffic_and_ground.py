"""What is drivable, what is walkable, and nothing standing in the same place.

Every assertion here exists because the thing it checks was visibly wrong in
play: kerb parking handed out on lawns and on the Mississippi, the eight-horse
Clydesdale hitch walking through the Farmers Market and then across the river,
ambient cars coming to rest inside each other and inside parked cars, Gravois
drawn as a flight of stairs, and a brewery whose art and collision disagreed
so completely that crossing the yard felt like walking over roofs.
"""

import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402
import main as M  # noqa: E402


# ------------------------------------------------------------- parking ----
def test_no_car_is_ever_parked_on_a_lawn_or_in_the_river():
    """Kerb bays only on asphalt.

    `parking_is_legal_spot` only asked whether the rect was *blocked*, and
    grass is not blocked, so every road-line tile the landmark pass turned
    into park, lawn, rail ballast or open water still handed out parking.
    136 of 1,636 bays were off the road: 102 of them in the Mississippi.
    """
    off = []
    for (x, y, angle, _side) in M.parking__all():
        rect = M.parking_car_rect(x, y, angle)
        for r in range(rect.top // 64, (rect.bottom - 1) // 64 + 1):
            for c in range(rect.left // 64, (rect.right - 1) // 64 + 1):
                if M.GAME_MAP[r][c]["type"] != M.TILE_ROAD:
                    off.append((c, r, M.GAME_MAP[r][c]["type"]))
    assert not off, f"{len(off)} kerb bays are not on a road: {off[:6]}"


def test_there_is_still_plenty_of_kerb_parking_left():
    """The asphalt rule must not have emptied the streets."""
    assert len(M.parking__all()) > 1200


# ---------------------------------------------------------- the horses ----
def test_the_clydesdales_stay_on_soulard_streets():
    """They used to be handed the full map width on row 57, which walked the
    hitch through the Farmers Market sheds and out across the Mississippi."""
    game = M.Game()
    horses = [v for v in game.rail if v.kind == "clydesdale"]
    assert len(horses) == 1
    hitch = horses[0]
    bad = []
    for s in range(0, int(hitch.length) + 1, 8):
        hitch.s = float(s)
        hitch._place()
        col, row = int(hitch.x) // 64, int(hitch.y) // 64
        tile = M.GAME_MAP[row][col]
        if tile["collidable"] or tile["type"] == M.TILE_WATER:
            bad.append((col, row))
    assert not bad, f"the hitch walks through {sorted(set(bad))}"
    # ... and it is a beat, not a parade across the whole city
    assert hitch.length < M.MAP_WIDTH * 0.4


# -------------------------------------------------------- the diagonals ---
def test_every_diagonal_tile_knows_which_way_the_street_runs():
    """The tiles are a 4-connected staircase because collision is. The street
    is not, and the renderer needs the real heading or it draws stairs."""
    assert set(M.DIAGONAL_DIR) == set(M.DIAGONAL_AT)
    for (tile, (ux, uy)) in M.DIAGONAL_DIR.items():
        assert abs((ux * ux + uy * uy) - 1.0) < 1e-6, tile
        # off the grid on both axes: Manchester's drift is shallow, but it is
        # still a drift, and the markings have to follow it
        assert min(abs(ux), abs(uy)) > 0.02, (tile, ux, uy)
    # Gravois is the steep one, and it must not have been flattened
    steep = [d for (t, d) in M.DIAGONAL_DIR.items()
             if M.DIAGONAL_AT[t] == "GRAVOIS AVE"]
    assert steep and min(min(abs(a), abs(b)) for (a, b) in steep) > 0.4


def test_diagonals_are_normal_two_lane_width_and_miss_landmarks():
    """The first diagonal pass stamped two full 64px tiles side by side, so
    Manchester and Gravois read as 128px asphalt plazas. Gravois' centreline
    also entered Bevo Mill's footprint instead of passing beside the fork."""
    assert all(width == 1 for _name, _points, width in M.DIAGONAL_STREETS)
    footprints = {
        name: {(c, r) for c in range(lx, lx + lw) for r in range(ly, ly + lh)}
        for lx, ly, lw, lh, _kind, name, _color in M.LANDMARKS
    }
    for name, points, width in M.DIAGONAL_STREETS:
        route = set(M._diagonal_run(points, width))
        for landmark, footprint in footprints.items():
            assert not route & footprint, \
                f"{name} enters {landmark}: {sorted(route & footprint)}"


def test_a_diagonal_tile_is_drawn_as_a_diagonal_not_as_a_boxed_square():
    """Drawing a diagonal tile must chamfer its outside corners, so the kerb
    runs at the street's angle instead of round every 64px step."""
    game = M.Game()
    tile = next((c, r) for (c, r) in M.DIAGONAL_AT
                if M.tile_type_at(c, r) == M.TILE_ROAD
                and c not in M.ROAD_LINES and r not in M.ROAD_LINES
                and any(M.Game.ground_color_at(c + dc, r + dr) is not None
                        for dc in (-1, 1) for dr in (-1, 1)))
    rect = pygame.Rect(0, 0, 64, 64)
    game.screen.fill((255, 0, 255))
    game.draw_diagonal_road(rect, tile[0], tile[1])
    corners = [game.screen.get_at((1, 1))[:3], game.screen.get_at((62, 1))[:3],
               game.screen.get_at((1, 62))[:3], game.screen.get_at((62, 62))[:3]]
    assert any(c != M.COLOR_ROAD for c in corners), \
        "no corner was chamfered - the tile is still a square of asphalt"
    assert game.screen.get_at((32, 32))[:3] != (255, 0, 255), "no asphalt drawn"


def test_metrolink_and_eads_pass_north_of_the_arch_grounds():
    """The first polyline ended on row 43 inside the Arch's 9x12 footprint;
    rails and the Eads deck visibly crossed the middle of the memorial lawn."""
    arch = next(e for e in M.LANDMARKS if e[5] == "Gateway Arch")
    ax, ay, aw, ah = arch[:4]
    footprint = {(c, r) for c in range(ax, ax + aw) for r in range(ay, ay + ah)}
    route = {(c, r) for c, r, _axis in M.METROLINK_TILES}
    assert not route & footprint
    assert min(M.RIVER_BRIDGES) < ay


def test_river_bend_has_no_unreachable_concrete_islands():
    """Six open plaza tiles survived the river-bank bend but had no path back
    to land: (89,12), (90,12), (82,18), (83,18), (89,60), and (90,60)."""
    for col, row in M.RIVER_POCKET_TILES:
        tile = M.GAME_MAP[row][col]
        assert tile['type'] == M.TILE_WATER and tile['collidable'], (col, row)


# ----------------------------------------------------------- the brewery --
def test_the_brewery_yard_is_ground_and_its_blocks_are_buildings():
    """One mask feeds the collision and the art. It used to be a hollow
    district ring under 140 roofs drawn edge to edge, so the walkable middle
    of the brewery was painted to look like rooftops."""
    entry = next(e for e in M.LANDMARKS if e[5] == "Anheuser-Busch Brewery")
    lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
    assert M.LANDMARK_LAYOUT["Anheuser-Busch Brewery"] == "brewery"

    on_block = set()
    for (bc, br, bw, bh) in M.brewery_blocks(lw, lh):
        for r in range(br, br + bh):
            for c in range(bc, bc + bw):
                on_block.add((c, r))
    assert on_block, "the campus has no buildings on it"

    open_tiles = sealed = 0
    for r in range(ly, ly + lh):
        for c in range(lx, lx + lw):
            solid = M.GAME_MAP[r][c]["collidable"]
            assert solid == ((c - lx, r - ly) in on_block), \
                f"art and collision disagree at {c},{r}"
            if not solid:
                open_tiles += 1
                if not M.WALK_REACHABLE[r][c]:
                    sealed += 1
    assert sealed == 0, f"{sealed} brewery yard tiles are sealed off"
    assert open_tiles >= lw * lh // 3, "the yard streets are too narrow to drive"


# ----------------------------------------------------------- spawn rules --
def test_nothing_respawns_on_top_of_a_car_that_is_already_there():
    """Kerb bays came off a shuffled queue rebuilt from scratch every time it
    emptied, and moving cars respawned on a tile centre with no occupancy test
    at all. Either way you got two cars in one place."""
    random.seed(11)
    game = M.Game()
    occupied = game.cars[0]
    assert not game.spot_is_free(occupied.rect.centerx, occupied.rect.centery)
    assert game.spot_is_free(occupied.rect.centerx, occupied.rect.centery,
                             skip=occupied)
    # One city is an anecdote. Build a dozen and check none of them opens with
    # two cars in the same place.
    for seed in range(12):
        random.seed(seed)
        cars = M.Game().cars
        pairs = [(a, b) for i, a in enumerate(cars) for b in cars[i + 1:]
                 if a.rect.colliderect(b.rect)]
        assert not pairs, f"seed {seed}: {len(pairs)} cars overlap on frame one"


def test_police_spawner_rejects_an_occupied_road_point(monkeypatch):
    """The civilian spawner had an occupancy check but the police spawner had
    zero: it accepted the first legal point even when a car already occupied it."""
    game = M.Game()
    blocker = M.Car(*game.police_station, variant='sedan')
    game.cars = [blocker]
    game.police = []
    monkeypatch.setattr(M, 'free_point_near', lambda *_a, **_kw: blocker.rect.center)
    assert game.cop_spawn_point() is None


def test_traffic_does_not_come_to_rest_inside_another_car():
    """Parked cars used to be left out of the unstacking pass entirely, and
    the shove was one pixel a step - far slower than two cars close head-on.
    Measured over 2,000 steps: a car buried 30% or more inside another on
    12.5-14.6% of frames, at up to a total merge."""
    random.seed(5)
    game = M.Game()
    game.state = M.STATE_PLAYING
    bad = 0
    for _ in range(600):
        game.player_dir = [random.choice([-1, 0, 1]), random.choice([-1, 0, 1])]
        game.update()
        cars = [c for c in game.cars
                if c.driver is None and c is not game.driving]
        for i, a in enumerate(cars):
            for b in cars[i + 1:]:
                if not a.rect.colliderect(b.rect):
                    continue
                over = a.rect.clip(b.rect)
                small = min(a.rect.w * a.rect.h, b.rect.w * b.rect.h)
                if over.w * over.h >= 0.30 * small:
                    bad += 1
    assert bad <= 40, f"{bad} badly stacked car pairs over 600 steps"

"""What is drivable, what is walkable, and nothing standing in the same place.

Every assertion here exists because the thing it checks was visibly wrong in
play: kerb parking handed out on lawns and on the Mississippi, the eight-horse
Clydesdale hitch walking through the Farmers Market and then across the river,
ambient cars coming to rest inside each other and inside parked cars, Gravois
drawn as a flight of stairs, and a brewery whose art and collision disagreed
so completely that crossing the yard felt like walking over roofs.
"""

import os
import math
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
    """A tile knows the heading of whichever leg of the street passes closest.

    The reservation is the painted band now, not a staircase, but the reason
    the heading has to be carried per tile is unchanged: the renderer needs
    the street's real angle or it boxes every tile in square kerbs, and the
    road reads as a flight of stairs."""
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
    also entered Bevo Mill's footprint instead of passing beside the fork.

    Still true now the reservation is the painted band rather than a one-tile
    staircase: the band is measured off DIAG_KERB_WIDTH, which is 62px - just
    under a single tile - so widening the reservation to match the paint did
    not widen the street."""
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


def test_diagonal_grid_crossings_keep_the_cardinal_road_underlay():
    """A crossing tile needs road beneath the diagonal, not sidewalk wedges."""
    game = M.Game()
    crossings = [(c, r) for c, r in M.DIAGONAL_AT
                 if (c in M.ROAD_LINES) != (r in M.ROAD_LINES)]
    assert crossings, "no diagonal crosses a cardinal street between junctions"

    for col, row in crossings:
        game.camera.x = col * M.TILE_SIZE
        game.camera.y = row * M.TILE_SIZE
        game.screen.fill((255, 0, 255))
        game.draw_tile(col, row)
        road_pixels = sum(
            game.screen.get_at((x, y))[:3] == M.COLOR_ROAD
            for y in range(M.TILE_SIZE)
            for x in range(M.TILE_SIZE)
        )
        assert road_pixels > 1500, \
            f"sidewalk underlay cuts through crossing at {col},{row}"


def test_diagonal_shoulders_stop_at_the_cardinal_crossing_mouth():
    """The diagonal's asphalt crosses the street; its curbs do not."""
    game = M.Game()
    crossing = next((tile for tile in M.DIAGONAL_GRID_CROSSINGS
                     if (tile[0] in M.ROAD_LINES) != (tile[1] in M.ROAD_LINES)))
    col, row = crossing
    game.camera.x = col * M.TILE_SIZE
    game.camera.y = row * M.TILE_SIZE
    game.screen.fill((1, 2, 3))
    game.draw_tile(col, row)
    game.draw_diagonal_network()

    ux, uy = M.DIAGONAL_DIR[crossing]
    # These points lie in the old 50..62px shoulder band, on opposite sides
    # of the diagonal centre. Both must expose the intersecting asphalt now.
    normal = pygame.Vector2(-uy, ux)
    for side in (-1, 1):
        point = pygame.Vector2(32, 32) + normal * 28 * side
        color = game.screen.get_at((round(point.x), round(point.y)))[:3]
        assert color not in (M.COLOR_SIDEWALK, M.COLOR_SIDEWALK_SEAM), \
            f"diagonal curb crosses cardinal asphalt at {crossing}: {color}"


def test_crosswalk_bars_are_small_even_and_balanced():
    game = M.Game()
    junction = next((c, r) for c in sorted(M.ROAD_LINES)
                    for r in sorted(M.ROAD_LINES)
                    if all(M.tile_type_at(c + dc, r + dr) == M.TILE_ROAD
                           for dc, dr in ((0, -1), (0, 1), (-1, 0), (1, 0))))
    game.screen.fill((1, 2, 3))
    game.draw_crosswalk(pygame.Rect(0, 0, 64, 64), *junction)
    pixels = [(x, y) for y in range(64) for x in range(64)
              if game.screen.get_at((x, y))[:3] == M.COLOR_CROSSWALK]
    assert 500 <= len(pixels) <= 600, f"crosswalk paint is oversized: {len(pixels)}px"
    xs = [x for x, _y in pixels]
    ys = [y for _x, y in pixels]
    assert min(xs) == min(ys) == 6
    assert max(xs) == max(ys) == 57
    # Rotating the compact pattern 90 degrees produces the same set.
    assert set(pixels) == {(63 - y, x) for x, y in pixels}


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

    # A named street beats the mask. CHEROKEE ST, MERAMEC ST and 14TH ST all
    # cross this campus, and before they were punched through, 17 tiles of
    # signposted two-lane street were solid brick - you drove at a street with
    # a name on it and hit a wall. Where the two disagree the street wins, and
    # Game.draw_landmark_streets repaints that asphalt over the baked campus
    # art, so the collision and the picture still agree.
    crossed = 0
    open_tiles = sealed = 0
    for r in range(ly, ly + lh):
        for c in range(lx, lx + lw):
            solid = M.GAME_MAP[r][c]["collidable"]
            if c in M.ROAD_LINES or r in M.ROAD_LINES:
                assert not solid, f"the street at {c},{r} is walled off"
                assert M.WALK_REACHABLE[r][c], \
                    f"the street at {c},{r} is open but cut off"
                crossed += 1
            else:
                assert solid == ((c - lx, r - ly) in on_block), \
                    f"art and collision disagree at {c},{r}"
            if not solid:
                open_tiles += 1
                if not M.WALK_REACHABLE[r][c]:
                    sealed += 1
    assert crossed, "no named street crosses the brewery - check the grid"
    assert sealed == 0, f"{sealed} brewery yard tiles are sealed off"
    assert open_tiles >= lw * lh // 3, "the yard streets are too narrow to drive"


def test_stadium_art_uses_the_same_angular_mask_as_collision():
    entry = next(e for e in M.LANDMARKS if e[5] == "Busch Stadium")
    _x, _y, lw, lh = entry[:4]
    art = M.lm__bake_stadium_angular(lw * M.TILE_SIZE, lh * M.TILE_SIZE)
    seat_colors = {M.lm_SEAT_RED, M.lm_SEAT_RED_DK}
    for ly in range(lh):
        for lx in range(lw):
            pixel = art.get_at((lx * M.TILE_SIZE + 11,
                                ly * M.TILE_SIZE + 11))[:3]
            if M._lm_solid_stadium(lx, ly, lw, lh):
                assert pixel in seat_colors, (lx, ly, pixel)
    field_pixel = art.get_at((2 * M.TILE_SIZE + M.TILE_SIZE // 2,
                              2 * M.TILE_SIZE + M.TILE_SIZE // 2))[:3]
    assert field_pixel not in seat_colors


def test_grand_and_hill_art_bakers_share_the_collision_predicates():
    assert M.LANDMARK_LAYOUT["Grand Center Arts District"] == "grand_blocks"
    assert M.LANDMARK_LAYOUT["The Hill"] == "hill_blocks"
    assert M.lm__BAKERS["grand_center"] is M.lm__bake_grand_center_aligned
    assert M.lm__BAKERS["the_hill"] is M.lm__bake_the_hill_aligned


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
                ar = game.traffic_footprint(a)
                br = game.traffic_footprint(b)
                if not ar.colliderect(br):
                    continue
                over = ar.clip(br)
                small = min(ar.w * ar.h, br.w * br.h)
                if over.w * over.h >= 0.30 * small:
                    bad += 1
    assert bad <= 40, f"{bad} badly stacked car pairs over 600 steps"


def test_streamed_traffic_stays_on_the_cardinal_road_grid():
    """Diagonal roads and open rail/landmark ground are not AI corridors.

    The ambient driver only understands cardinal named streets. A diagonal
    spawn used to be snapped toward the nearest grid line, sometimes directly
    onto MetroLink ballast or a landmark plaza, and from there collision saw
    open ground and allowed the car to keep driving across it.
    """
    for seed in range(6):
        random.seed(seed)
        game = M.Game()
        game.state = M.STATE_PLAYING
        for _ in range(900):
            game.update()
            for car in game.cars:
                if car.driver is not None or car.parked:
                    continue
                col, row = car.rect.centerx // M.TILE_SIZE, car.rect.centery // M.TILE_SIZE
                assert M.traffic__is_grid_road(col, row), (
                    f"seed {seed}: {car.variant} left traffic grid for "
                    f"{M.GAME_MAP[row][col]} at {(col, row)}")


def test_offroad_traffic_restores_its_last_road_position_and_turns_around():
    game = M.Game()
    edge = None
    for row in range(2, M.MAP_TILES_H - 2):
        for col in range(2, M.MAP_TILES_W - 2):
            if not M.traffic__is_grid_road(col, row):
                continue
            for direction, (dx, dy) in enumerate(M.traffic__DIRS):
                other = M.GAME_MAP[row + dy][col + dx]
                if not other['collidable'] and not M.traffic__is_grid_road(col + dx, row + dy):
                    edge = (col, row, col + dx, row + dy, direction)
                    break
            if edge:
                break
        if edge:
            break
    assert edge is not None, "map has no road edge beside open non-road ground"

    col, row, off_col, off_row, direction = edge
    car = M.Car(col * M.TILE_SIZE + M.TILE_SIZE // 2,
                row * M.TILE_SIZE + M.TILE_SIZE // 2, variant='sedan')
    car.angle = direction * math.pi * 0.5
    car.driver = None
    car.parked = False
    assert M.traffic_init_car(car)
    assert M.traffic_snap_to_lane(car)
    safe = car.rect.center
    car.rect.center = (off_col * M.TILE_SIZE + M.TILE_SIZE // 2,
                       off_row * M.TILE_SIZE + M.TILE_SIZE // 2)
    M.traffic_drive(car, (car,))
    assert car.rect.center == safe
    assert car.velocity == 0.0
    assert M.traffic__is_grid_road(car.rect.centerx // M.TILE_SIZE,
                                   car.rect.centery // M.TILE_SIZE)


def test_unstack_does_not_shove_correct_opposing_lanes_off_the_road():
    game = M.Game()
    point = None
    for col in sorted(M.ROAD_LINES):
        for row in range(2, M.MAP_TILES_H - 2):
            if row not in M.ROAD_LINES and M.traffic__is_grid_road(col, row):
                point = col, row
                break
        if point:
            break
    assert point is not None
    col, row = point
    y = row * M.TILE_SIZE + M.TILE_SIZE // 2
    south_x = int(M.traffic__lane_coord(1, col))
    north_x = int(M.traffic__lane_coord(3, col))
    south = M.Car(south_x, y, variant='sedan')
    north = M.Car(north_x, y, variant='sedan')
    south.angle, north.angle = math.pi * 0.5, math.pi * 1.5
    south.driver = north.driver = None
    south.parked = north.parked = False
    # Their unrotated physics AABBs overlap, but their rendered/cardinal
    # footprints do not: these are two correctly occupied opposing lanes.
    assert south.rect.colliderect(north.rect)
    assert not game.traffic_footprint(south).colliderect(game.traffic_footprint(north))
    before = south.rect.center, north.rect.center
    game.cars = [south, north]
    game.unstack_traffic()
    assert (south.rect.center, north.rect.center) == before


# ------------------------------------------- streets you can actually drive --
def test_no_named_street_is_ever_walled_off():
    """A street with a name, a sign and two lanes has to go where it says.

    Measured before `_open_street_lines` existed: 39 tiles of named,
    signposted street were solid brick. Broadway and Tucker stopped dead
    inside Downtown, Cherokee and Meramec inside the brewery, Vandeventer
    inside the Central West End, Skinker inside Ted Drewes and the Delmar
    Loop, Compton inside the water tower. You drove at a street with a name on
    it and hit a wall.

    Two things may still interrupt a street, and both are visible to the
    player: the Mississippi (which crosses at exactly RIVER_BRIDGES), and a
    landmark named in LANDMARK_STREETS_EXEMPT. Anything else is the bug.
    """
    walled = []
    exempt = []
    for row in range(M.MAP_TILES_H):
        for col in range(M.MAP_TILES_W):
            if not (col in M.ROAD_LINES or row in M.ROAD_LINES):
                continue
            tile = M.GAME_MAP[row][col]
            if not tile["collidable"] or tile["type"] == M.TILE_WATER:
                continue
            parent = M.landmark_owner(tile.get("landmark"))
            if parent in M.LANDMARK_STREETS_EXEMPT:
                exempt.append((col, row, parent))
            else:
                walled.append((col, row, tile["type"], tile.get("landmark")))
    assert not walled, f"{len(walled)} tiles of named street are solid: {walled[:8]}"

    # An exemption is a hole in the invariant, so it has to stay a small,
    # deliberate one. A whole arterial swallowed by an "exempt" landmark would
    # otherwise pass this test in silence.
    assert len(exempt) <= 4, (
        f"exempt landmarks are walling {len(exempt)} street tiles: {exempt}")
    for _col, _row, parent in exempt:
        assert parent in M.LANDMARK_STREETS_EXEMPT


def test_a_street_the_invariant_opened_is_not_still_painted_as_a_building():
    """The tiles _open_street_lines opens are drivable ground, and the
    landmark's baked art has no idea a wall came out of it.

    Without Game.draw_landmark_streets the block stays painted over ground you
    can now drive on - a roof on a surface with no collision, which is the
    same lie as a wall in a street, from the other side. This walks the actual
    rendered frame rather than the baked composition, because the fix is a
    draw pass and the baked art is still (correctly) unchanged.
    """
    structure = {M.lm_LIMESTONE, M.lm_LIMESTONE_DK, M.lm_BRICK, M.lm_BRICK_DK,
                 M.lm_BRICK_LT, M.lm_BRICK_BROWN, M.lm_TERRACOTTA,
                 M.lm_VERDIGRIS, M.lm_VERDIGRIS_DK, M.lm_SLATE, M.lm_SLATE_DK,
                 M.lm_STEEL, M.lm_STEEL_HI}
    cut = [(c, r) for r in range(M.MAP_TILES_H) for c in range(M.MAP_TILES_W)
           if M.GAME_MAP[r][c].get("street_cut")]
    assert cut, "the street invariant opened nothing - did the map change?"

    game = M.Game()
    game.cars, game.pedestrians = [], []
    for col, row in cut:
        assert not M.GAME_MAP[row][col]["collidable"]
        game.camera.x = col * M.TILE_SIZE + M.TILE_SIZE // 2 - M.SCREEN_WIDTH // 2
        game.camera.y = row * M.TILE_SIZE + M.TILE_SIZE // 2 - M.SCREEN_HEIGHT // 2
        game.camera.shake_ox = game.camera.shake_oy = 0.0
        game.screen.fill(M.COLOR_SKY_BG)
        sc, ec, sr, er = game.camera.visible_tile_range()
        for r in range(sr, er):
            for c in range(sc, ec):
                game.draw_tile(c, r)
        game.draw_landmark_art()
        game.draw_landmark_streets(sc, ec, sr, er)
        ox = col * M.TILE_SIZE - game.camera.x
        oy = row * M.TILE_SIZE - game.camera.y
        seen = [game.screen.get_at((int(ox + dx), int(oy + dy)))[:3]
                for dy in range(6, M.TILE_SIZE - 5, 6)
                for dx in range(6, M.TILE_SIZE - 5, 6)]
        painted = sum(px in structure for px in seen)
        assert painted / float(len(seen)) < 0.25, (
            f"{col},{row} is drivable but still painted as a building "
            f"({painted}/{len(seen)} structure pixels)")


def test_every_named_street_is_reachable_for_its_whole_length():
    """Open is not enough: every tile of it has to be reachable from the net.

    A street can be perfectly clear and still be useless if the only ways on
    to it are walled - which is what a sealed landmark interior looks like
    from the inside.

    Note WHARF ST (col 93) is legitimately short: the river bank swings west
    below row 19 and the Mississippi takes the rest of it. Water is the one
    thing allowed to end a street, so it is skipped rather than counted.
    """
    for line in sorted(M.ROAD_LINES):
        for axis in ("ns", "ew"):
            tiles = [(i, line) if axis == "ew" else (line, i)
                     for i in range(M.MAP_TILES_W if axis == "ew"
                                    else M.MAP_TILES_H)]
            # Water and the deliberate exemptions above are walls, and a wall
            # is not expected to be reachable - test_no_named_street_is_ever_
            # walled_off is what governs those. This test is about open tiles
            # that are nonetheless cut off from the network.
            live = [(c, r) for c, r in tiles
                    if M.GAME_MAP[r][c]["type"] != M.TILE_WATER
                    and not M.GAME_MAP[r][c]["collidable"]]
            unreachable = [t for t in live if not M.WALK_REACHABLE[t[1]][t[0]]]
            assert not unreachable, (
                f"{axis} line {line} has {len(unreachable)} tiles cut off "
                f"from the street network: {unreachable[:6]}")


def test_nothing_solid_stands_in_a_diagonal_as_it_is_painted():
    """The tile reservation IS the painted band, so it cannot disagree with it.

    The reservation used to be a 4-connected staircase while the renderer drew
    a straight polyline of asphalt. They disagreed on 53 tiles across the three
    diagonals, and every one was a building standing in the middle of the road:
    asphalt under a brick facade, which you could see and then drive into.
    """
    for name, points, width in M.DIAGONAL_STREETS:
        reserved = set(M._diagonal_run(points, width))
        painted = M._band_tiles(points, M.DIAG_KERB_WIDTH * width * 0.5)
        assert not (painted - reserved), (
            f"{name} is painted on unreserved tiles: {sorted(painted - reserved)[:8]}")
        solid = [t for t in reserved if M.GAME_MAP[t[1]][t[0]]["collidable"]]
        assert not solid, f"{name} has {len(solid)} solid tiles in it: {solid[:8]}"


def test_every_off_grid_route_is_one_connected_run():
    """4-connected, because every collider and reachability check here is."""
    routes = [(name, M._diagonal_run(points, width))
              for name, points, width in M.DIAGONAL_STREETS]
    routes.append(("CHAIN OF ROCKS", tuple(M.CHAIN_OF_ROCKS_TILES)))
    routes.append(("DES PERES", tuple(M.RIVER_DES_PERES_TILES)))
    for name, tiles in routes:
        assert tiles, f"{name} claims no tiles"
        pool = set(tiles)
        seen, stack = {tiles[0]}, [tiles[0]]
        while stack:
            col, row = stack.pop()
            for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (col + dc, row + dr)
                if nxt in pool and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        assert seen == pool, (
            f"{name} is in {len(pool) - len(seen)} disconnected pieces")


def test_the_chain_of_rocks_bend_is_a_bend_and_not_a_flight_of_stairs():
    """The 22-degree kink is the only thing anybody knows about this bridge.

    Drawn per-tile it came out as four stairs, because each 64px tile got a
    horizontal rail along its own top and bottom edge. The deck is one
    polyline now, so the railing turns once, where the deck turns.
    """
    pts = M.CHAIN_OF_ROCKS_WAYPOINTS
    assert len(pts) >= 3, "no bend in the waypoints at all"
    legs = []
    for a, b in zip(pts, pts[1:]):
        legs.append(math.atan2(b[1] - a[1], b[0] - a[0]))
    turns = [abs(math.degrees(b - a)) for a, b in zip(legs, legs[1:])]
    assert len(turns) == 1, f"the deck turns {len(turns)} times, not once"
    assert 15.0 < turns[0] < 30.0, f"the kink is {turns[0]:.1f} degrees"

    # and the tile pass must NOT be painting per-tile deck edges any more
    game = M.Game()
    col, row = next(iter(M.CHAIN_OF_ROCKS_TILES))
    game.camera.x, game.camera.y = col * M.TILE_SIZE, row * M.TILE_SIZE
    game.screen.fill((255, 0, 255))
    game.draw_tile(col, row)
    top = [game.screen.get_at((x, 1))[:3] for x in range(8, 56)]
    assert len(set(top)) <= 2, (
        "draw_tile is still drawing a deck rail along the tile edge")


def test_the_named_streets_bridge_the_des_peres_channel():
    """The channel is below grade and the city carries on south of it.

    Painted straight over the top, it made sixteen named north-south streets
    vanish for three tiles and reappear on the far side.
    """
    assert len(M.DES_PERES_CROSSINGS) >= 12, (
        f"only {len(M.DES_PERES_CROSSINGS)} streets cross the channel")
    for col, (row0, row1) in M.DES_PERES_CROSSINGS.items():
        assert col in M.ROAD_LINES
        for row in range(row0, row1 + 1):
            assert not M.GAME_MAP[row][col]["collidable"], (
                f"the crossing at {col},{row} is blocked")


def test_no_street_furniture_on_a_bridge_deck_or_in_a_flood_channel():
    """Nobody puts a hydrant on a bridge or a bench in the bottom of a
    concrete channel; the props pass saw a road tile and furnished it. 34."""
    game = M.Game()
    for col, row in set(M.CHAIN_OF_ROCKS_TILES) | set(M.RIVER_DES_PERES_TILES):
        game.camera.x, game.camera.y = col * M.TILE_SIZE, row * M.TILE_SIZE
        game.screen.fill((255, 0, 255))
        game.draw_props(col, row)
        painted = sum(game.screen.get_at((x, y))[:3] != (255, 0, 255)
                      for y in range(0, M.TILE_SIZE, 4)
                      for x in range(0, M.TILE_SIZE, 4))
        assert painted == 0, f"a prop is standing on the route at {col},{row}"


def test_no_open_ground_is_sealed_away_from_the_streets():
    """A courtyard with no gate is where drop markers go to be unreachable.

    _fill_city_blocks cut 2x2 courtyards into the middle of large blocks and
    left no throat out of them: four tiles of open plaza the street network
    could not reach.
    """
    sealed = [(c, r) for r in range(M.MAP_TILES_H) for c in range(M.MAP_TILES_W)
              if not M.GAME_MAP[r][c]["collidable"] and not M.WALK_REACHABLE[r][c]]
    assert not sealed, f"{len(sealed)} tiles of open ground are sealed off: {sealed[:8]}"

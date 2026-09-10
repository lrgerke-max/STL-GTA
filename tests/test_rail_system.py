"""MetroLink right-of-way, crossings, traffic control, and collision tests."""

import math
import os
import random
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402
import pytest  # noqa: E402
import main as M  # noqa: E402


@pytest.fixture(scope="module")
def game():
    random.seed(5302)
    return M.Game()


def train_tile(train):
    col = max(0, min(M.MAP_TILES_W - 1, int(train.x) // M.TILE_SIZE))
    row = max(0, min(M.MAP_TILES_H - 1, int(train.y) // M.TILE_SIZE))
    return M.GAME_MAP[row][col]


def test_metrolink_has_continuous_reserved_track_and_real_grade_crossings(game):
    """The alignment is a polyline now, not one row across the whole map."""
    assert len(game.rail_crossings) >= 8

    for (col, row, _axis) in M.METROLINK_TILES:
        if not (0 <= col < M.MAP_TILES_W and 0 <= row < M.MAP_TILES_H):
            continue
        tile = M.GAME_MAP[row][col]
        if tile['type'] == M.TILE_WATER:
            continue
        assert not tile['collidable'], f"solid tile on the alignment at {col},{row}"
        assert tile.get('rail') == 'metrolink', f"unreserved tile at {col},{row}"
        if tile.get('rail_crossing'):
            assert tile['type'] == M.TILE_ROAD
        elif not tile.get('rail_embedded'):
            assert tile['type'] == M.TILE_RAIL

    for crossing in game.rail_crossings:
        tile = M.GAME_MAP[crossing.row][crossing.col]
        assert tile['type'] == M.TILE_ROAD and tile.get('rail_crossing')

    # the trolley runs on Delmar and STOPS, which is the whole point of it
    assert all(M.GAME_MAP[M.TROLLEY_ROW][col].get('rail') == 'trolley'
               for col in range(M.TROLLEY_COL_MIN, M.TROLLEY_COL_MAX + 1)
               if M.GAME_MAP[M.TROLLEY_ROW][col]['type'] == M.TILE_ROAD)
    beyond = M.TROLLEY_COL_MAX + 4
    assert M.GAME_MAP[M.TROLLEY_ROW][beyond].get('rail') != 'trolley'


def test_metrolink_serves_the_stations_it_really_serves_and_skips_south_city():
    """Row 53 was south city, where the Red Line conspicuously does not go -
    and it ran straight through the Compton Hill Water Tower's lawn."""
    on_route = {(c, r) for (c, r, _a) in M.METROLINK_TILES}

    tower = next(e for e in M.LANDMARKS if e[5] == "Compton Hill Water Tower")
    lx, ly, lw, lh = tower[0], tower[1], tower[2], tower[3]
    footprint = {(c, r) for c in range(lx, lx + lw) for r in range(ly, ly + lh)}
    assert not (on_route & footprint), "MetroLink is back in the water tower's lawn"

    # it must pass within sight of the places it actually stops at
    for want in ("Forest Park", "Central West End", "Downtown"):
        entry = next(e for e in M.LANDMARKS if e[5] == want)
        ex, ey, ew, eh = entry[0], entry[1], entry[2], entry[3]
        near = any(ex - 4 <= c <= ex + ew + 4 and ey - 4 <= r <= ey + eh + 4
                   for (c, r) in on_route)
        assert near, f"MetroLink never comes near {want}"

    names = {name for (_c, _r, name) in M.METROLINK_STATIONS}
    assert {"ROCK ROAD", "CENTRAL WEST END", "GRAND", "UNION STATION"} <= names
    for col, row, _name in M.METROLINK_STATIONS:
        assert any(abs(c - col) + abs(r - row) <= 1 for c, r in on_route)
    order = {name: index for index, (_c, _r, name)
             in enumerate(M.METROLINK_STATIONS)}
    assert order['ROCK ROAD'] < order['WELLSTON'] < order['DELMAR LOOP']
    # and it crosses the river on the Eads, which is a named bridge row
    assert M.METROLINK_ROUTE[-1][1] in M.RIVER_BRIDGES


def test_every_metrolink_body_stays_on_non_solid_track_through_turnarounds(game):
    trains = [vehicle for vehicle in game.rail
              if vehicle.kind == 'metrolink']
    assert len(trains) == 2
    reversed_direction = {id(train): False for train in trains}
    previous = {id(train): math.copysign(1, train.speed) for train in trains}

    for _ in range(4200):
        for train in trains:
            train.update()
            assert 0.0 <= train.s <= train.length
            tile = train_tile(train)
            assert not tile['collidable'] and tile.get('rail') == 'metrolink'
            direction = math.copysign(1, train.speed)
            if direction != previous[id(train)]:
                reversed_direction[id(train)] = True
            previous[id(train)] = direction

    assert all(reversed_direction.values())


def test_crossing_is_fully_down_before_train_arrives_then_reopens():
    crossing = M.RailCrossing(sorted(M.ROAD_LINES)[4], M.METROLINK_ROW, 'h')
    train = SimpleNamespace(kind='metrolink', w=108,
                            centerx=crossing.x - M.RAIL_GATE_WARNING_DISTANCE - 60)
    for _ in range(10):
        crossing.update((train,))
    assert crossing.state == 'open'

    reached_crossing = False
    for _ in range(180):
        crossing.update((train,))
        train.centerx += 3.1
        body_distance = max(0.0, abs(train.centerx - crossing.x) - train.w / 2)
        if body_distance == 0:
            reached_crossing = True
            assert crossing.arm >= 0.98
            assert crossing.state == 'closed'
            break
    assert reached_crossing

    train.centerx = crossing.x + M.RAIL_GATE_WARNING_DISTANCE + train.w
    for _ in range(45):
        crossing.update((train,))
    assert crossing.arm == 0.0
    assert crossing.state == 'open'


def test_ambient_traffic_brakes_before_a_closed_gate(game):
    crossing = game.rail_crossings[3]
    for item in game.rail_crossings:
        item.arm = 0.0
        item.warning = False
    crossing.arm = 1.0
    crossing.warning = True
    crossing.state = 'closed'

    car = M.Car(crossing.x - M.traffic_LANE_OFFSET,
                crossing.y - 78, variant='sedan')
    car.angle = math.pi / 2
    car.velocity = 2.5
    car.parked = False
    M.traffic_init_car(car)
    car._traffic_ai['dir'] = 1
    car._traffic_ai['line'] = crossing.col
    assert game.rail_gate_holds(car)

    for _ in range(60):
        M.traffic_drive(car, (car,))

    assert car.rect.bottom < crossing.y - 8
    assert abs(car.velocity) < 0.35


def test_running_the_gate_lets_metrolink_destroy_the_player_car(game):
    game.state = M.STATE_PLAYING
    game.frame += M.FPS * 2
    game.callouts = []
    train = next(vehicle for vehicle in game.rail
                 if vehicle.kind == 'metrolink')
    car = M.Car(train.rect.centerx, train.rect.centery, variant='sedan')
    car.driver = 'player'
    game.driving = car

    game.update_train_collisions()

    assert car.hp == 0
    assert car.burn > 0
    assert getattr(car, 'train_hit_frame') == game.frame
    assert any(callout['text'] == 'TRAIN WINS' for callout in game.callouts)
    game.driving = None


def test_tracks_and_closed_crossing_have_visible_world_pixels(game):
    crossing = game.rail_crossings[3]
    crossing.arm = 1.0
    crossing.warning = True
    game.frame = 14
    game.camera.snap_to(pygame.Rect(crossing.x, crossing.y, 1, 1))
    game.screen.fill((1, 2, 3))

    game.draw_rail_infrastructure()
    game.draw_rail_crossing_gates()

    colors = {game.screen.get_at((x, y))[:3]
              for y in range(M.SCREEN_HEIGHT)
              for x in range(M.SCREEN_WIDTH)}
    assert (178, 184, 180) in colors       # polished rail head
    assert M.hud_HUD_RED in colors         # warning lamp / striped arm
    assert (76, 54, 42) in colors          # timber ties


def test_rail_surface_changes_follow_the_stamped_right_of_way(game):
    """Street-running and crossing track must not receive a gravel carpet."""
    embedded = next((c, r) for c, r, _axis in M.METROLINK_TILES
                    if M.GAME_MAP[r][c].get('rail_embedded'))
    crossing = next((c, r) for c, r, _axis in M.METROLINK_TILES
                    if M.GAME_MAP[r][c].get('rail_crossing'))

    for (col, row), want_rails in ((embedded, True), (crossing, True)):
        game.camera.x = col * M.TILE_SIZE - 128
        game.camera.y = row * M.TILE_SIZE - 128
        game.screen.fill((1, 2, 3))
        game.draw_tile(col, row)
        game.draw_rail_infrastructure()
        crop = pygame.Rect(128, 128, M.TILE_SIZE, M.TILE_SIZE)
        colors = [game.screen.get_at((x, y))[:3]
                  for y in range(crop.top, crop.bottom)
                  for x in range(crop.left, crop.right)]
        assert (66, 62, 58) not in colors, \
            f"ballast covers street-running rail at {col},{row}"
        if want_rails:
            assert (178, 184, 180) in colors, \
                f"railheads disappear at transition {col},{row}"


def test_metrolink_corner_path_is_rounded_instead_of_a_hard_elbow():
    path = M.Game.rounded_rail_path(((0, 0), (100, 0), (100, 100)),
                                    radius=20, steps=6)
    assert (100.0, 0.0) not in path, "hard corner vertex survived smoothing"
    curve = [(x, y) for x, y in path if 80 < x < 100 and 0 < y < 20]
    assert len(curve) >= 4, f"rail bend has too few curve samples: {curve}"
    assert all(0 <= x <= 100 and 0 <= y <= 100 for x, y in path)


def test_embedded_metrolink_has_steel_but_no_sleepers(game):
    """Street-running rail should not grow timber ties at the surface seam."""
    col, row = next((c, r) for c, r, _axis in M.METROLINK_TILES
                    if M.GAME_MAP[r][c].get('rail_embedded')
                    and M.GAME_MAP[r][c]['type'] != M.TILE_RAIL)
    game.camera.x = col * M.TILE_SIZE - 128
    game.camera.y = row * M.TILE_SIZE - 128
    game.screen.fill((1, 2, 3))
    game.draw_tile(col, row)
    game.draw_rail_infrastructure()
    crop = pygame.Rect(128, 128, M.TILE_SIZE, M.TILE_SIZE)
    colors = [game.screen.get_at((x, y))[:3]
              for y in range(crop.top, crop.bottom)
              for x in range(crop.left, crop.right)]
    assert (178, 184, 180) in colors
    assert (76, 54, 42) not in colors, "timber sleepers cross embedded asphalt"

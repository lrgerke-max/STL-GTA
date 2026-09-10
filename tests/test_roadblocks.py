"""Focused deterministic tests for four/five-star police roadblocks."""

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402
import pytest  # noqa: E402
import main as M  # noqa: E402


@pytest.fixture(scope="module")
def game():
    g = M.Game()
    g.cars = []
    g.police = []
    g.foot_police = []
    return g


def reset_high_heat(g, stars=4):
    g.wanted_level = stars
    g.state = M.STATE_PLAYING
    g.frame = 1000
    g.roadblocks = []
    g.roadblock_serial = 0
    g.roadblock_deploy_after = 0
    g.roadblock_target_seen = 0
    g.callouts = []
    g.toasts = []
    car = M.Car(0, 0, variant="sedan")
    car.driver = "player"
    car.angle = 0.0
    car.velocity = 6.0
    car.hp = car.max_hp
    g.driving = car

    # Find a real east-west road with a legal forward containment footprint.
    for row in sorted(M.ROAD_LINES):
        for col in range(8, M.MAP_TILES_W - 24):
            if M.tile_type_at(col, row) != M.TILE_ROAD or col in M.ROAD_LINES:
                continue
            car.rect.center = (col * M.TILE_SIZE + M.TILE_SIZE // 2,
                               row * M.TILE_SIZE + M.TILE_SIZE // 2)
            if g.roadblock_spawn_point(0) is not None:
                g.camera.snap_to(car.rect)
                return car
    raise AssertionError("map has no legal east-west roadblock approach")


def test_four_stars_deploys_one_complete_legal_roadblock(game):
    car = reset_high_heat(game, 4)
    game.update_roadblocks(4)

    assert len(game.roadblocks) == 1
    block = game.roadblocks[0]
    ahead = pygame.Vector2(block["center"]) - pygame.Vector2(car.rect.center)
    assert ahead.dot(game.pursuit_heading()) >= M.ROADBLOCK_AHEAD_MIN
    assert len(block["cars"]) == 2
    assert M.tile_type_at(block["center"][0] // M.TILE_SIZE,
                          block["center"][1] // M.TILE_SIZE) == M.TILE_ROAD
    assert not M.is_blocked(block["strip"])
    assert all(not M.is_blocked(unit.rect) for unit in block["cars"])


def test_five_stars_adds_a_second_distinct_roadblock(game):
    reset_high_heat(game, 4)
    game.update_roadblocks(4)
    game.wanted_level = 5
    game.frame += 1
    game.update_roadblocks(5)

    assert len(game.roadblocks) == 2
    a, b = (pygame.Vector2(block["center"]) for block in game.roadblocks)
    assert a.distance_to(b) >= 210
    assert all(len(block["cars"]) == 2 for block in game.roadblocks)


def test_spikes_cripple_without_instantly_destroying_car(game):
    car = reset_high_heat(game, 4)
    game.update_roadblocks(4)
    block = game.roadblocks[0]
    car.rect.center = block["strip"].center
    car.velocity = 8.0
    car.hp = 5.0

    game.update_roadblock_contacts()
    game.apply_grub_to_car()

    assert car.puncture_steps == M.SPIKE_PUNCTURE_STEPS
    assert car.hp == 1.0 and car.burn == 0
    assert math.isclose(car.velocity, 8.0 * M.SPIKE_ENTRY_SPEED_SCALE)
    assert math.isclose(car.max_speed,
                        car.base_max_speed * M.SPIKE_SPEED_SCALE)
    assert any(callout["text"] == "TIRES SHREDDED" for callout in game.callouts)


def test_passed_roadblock_retires_then_redeploys_ahead(game):
    car = reset_high_heat(game, 4)
    game.update_roadblocks(4)
    old_center = game.roadblocks[0]["center"]
    car.rect.center = (old_center[0] + M.ROADBLOCK_RETIRE_DISTANCE + 80,
                       old_center[1])
    game.frame += 1

    game.update_roadblocks(4)
    assert game.roadblocks == []
    wait_until = game.roadblock_deploy_after
    assert wait_until - game.frame == M.ROADBLOCK_REDEPLOY_BY_STAR[4]

    game.frame = wait_until
    game.update_roadblocks(4)
    assert len(game.roadblocks) == 1
    assert game.roadblocks[0]["center"] != old_center
    rel = pygame.Vector2(game.roadblocks[0]["center"]) - pygame.Vector2(car.rect.center)
    assert rel.dot(game.pursuit_heading()) > 0


def test_roadblock_has_world_and_radar_pixels(game):
    reset_high_heat(game, 4)
    game.update_roadblocks(4)
    block = game.roadblocks[0]
    game.screen.fill((1, 2, 3))
    game.camera.snap_to(block["strip"])
    game.draw_roadblock_strips()
    strip_colour = (224, 186, 54)
    assert any(game.screen.get_at((x, y))[:3] == strip_colour
               for y in range(M.SCREEN_HEIGHT) for x in range(M.SCREEN_WIDTH))

    game.screen.fill((0, 0, 0))
    game.draw_radar(10, 10)
    radar_colour = (246, 194, 52)
    assert any(game.screen.get_at((x, y))[:3] == radar_colour
               for y in range(10, 10 + M.RADAR_SIZE)
               for x in range(10, 10 + M.RADAR_SIZE))


def test_roadblock_cruisers_share_normal_bullet_damage(game):
    reset_high_heat(game, 4)
    game.update_roadblocks(4)
    unit = game.roadblocks[0]["cars"][0]
    game.bullets = [{
        "x": float(unit.rect.centerx - 8), "y": float(unit.rect.centery),
        "vx": 8.0, "vy": 0.0, "life": 10, "damage": 25.0,
        "kind": "pistol",
    }]

    game.update_bullets()

    assert unit.hp == unit.max_hp - 25.0
    assert game.bullets == []


def test_destroying_cruiser_opens_roadblock_and_delays_replacement(game):
    reset_high_heat(game, 4)
    game.update_roadblocks(4)
    unit = game.roadblocks[0]["cars"][0]
    game.roadblock_deploy_after = game.frame

    game.explode(unit)

    assert game.roadblocks == []
    assert game.roadblock_deploy_after == (
        game.frame + M.ROADBLOCK_REDEPLOY_BY_STAR[4])

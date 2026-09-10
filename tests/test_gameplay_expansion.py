"""End-to-end coverage for side missions and integrated throwables."""

import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402
import pytest  # noqa: E402
import main as M  # noqa: E402


@pytest.fixture(scope="module")
def game():
    random.seed(260907)
    return M.Game()


def reset_expansion(game, serial=0):
    if game.driving is not None:
        game.driving.driver = None
        game.driving = None
    game.state = M.STATE_PLAYING
    game.arch_job_unlocked = False
    game.arch_job_completed = False
    game.arch_job_phase = M.ARCH_LOCKED
    game.side_mission = None
    game.side_mission_serial = serial
    game.side_mission_cooldown = 0
    game.side_target_car = None
    game.side_target_pos = None
    game.smash_targets = []
    game.side_missions_done = 0
    game.side_missions_failed = 0
    game.wanted_level = 0
    game.police = []
    game.foot_police = []
    game.roadblocks = []
    game.spotted = False
    game.infraction_at = {}
    game.cash = 200
    game.score = 0
    game.frame = 1000
    game.callouts = []
    game.toasts = []
    game.fx = []
    game.pops = []
    game.decals = []
    game.throwable_system = M.throwable_logic.ThrowableSystem()
    contact, _name = game.side_mission_contact()
    game.player_rect.center = contact
    game.player_fx = float(contact[0])
    game.player_fy = float(contact[1])


def test_marked_vehicle_job_runs_from_contact_to_chop_shop(game):
    reset_expansion(game, 0)
    assert game.try_start_side_mission()
    assert game.side_mission.family == M.mission_logic.VEHICLE_THEFT
    target = game.side_target_car
    payout = game.side_mission.reward

    target.driver = 'player'
    target.parked = False
    game.driving = target
    game.side_mission_event('vehicle_entered', vehicle_id=id(target))
    assert game.side_mission.stage == 'deliver'
    target.rect.center = game.side_target_pos
    game.update_side_mission()

    assert game.side_mission is None
    assert game.side_missions_done == 1
    assert game.cash == 200 + payout


def test_grand_avenue_smash_job_counts_each_physical_target(game):
    reset_expansion(game, 1)
    assert game.try_start_side_mission()
    assert game.side_mission.family == M.mission_logic.SMASH_TARGETS
    targets = list(game.smash_targets)
    assert len(targets) == 6

    for target in targets:
        hit = pygame.Rect(0, 0, 16, 20)
        hit.center = target['pos']
        assert game.damage_smash_target(hit, 100.0)

    assert game.side_mission is None
    assert game.side_missions_done == 1
    assert game.cash == 1700


def test_take_forty_getaway_forces_heat_then_requires_clean_safehouse(game):
    reset_expansion(game, 2)
    assert game.try_start_side_mission()
    assert game.side_mission.family == M.mission_logic.EVADE_HEAT
    assert game.wanted_level == 3

    game.wanted_level = 0
    game.spotted = False
    cool_steps = game.side_mission.cool_steps
    for _ in range(cool_steps):
        game.update_side_mission()
    assert game.side_mission.stage == 'reach_safehouse'
    game.player_rect.center = game.side_target_pos
    game.update_side_mission()

    assert game.side_mission is None
    assert game.side_missions_done == 1
    assert game.cash == 2100


def test_fire_bottle_persists_and_damages_live_foot_cop(game):
    reset_expansion(game, 0)
    start = (10 * M.TILE_SIZE + M.TILE_SIZE // 2,
             M.ROAD_ORIGIN * M.TILE_SIZE + M.TILE_SIZE // 2)
    game.player_rect.center = start
    game.player_aim = 0.0
    cop = M.FootCop(start[0] + 256, start[1])
    game.foot_police = [cop]
    game.throwable_system = M.throwable_logic.ThrowableSystem({
        M.throwable_logic.FIRE_BOTTLE: 1,
    })
    game.weapon = M.throwable_logic.FIRE_BOTTLE
    game.weapon_ammo[game.weapon] = 1
    game.owned_weapons.add(game.weapon)
    game.ammo = 1

    assert game.throw_weapon()
    for _ in range(90):
        game.update_throwables()

    assert game.throwable_system.fire_zones()
    assert cop.hp < M.COP_FOOT_HP or cop not in game.foot_police
    assert any(decal['kind'] == 'scorch' for decal in game.decals)


def test_side_job_contact_and_smash_props_render_world_pixels(game):
    reset_expansion(game, 0)
    game.screen.fill((1, 2, 3))
    contact, _name = game.side_mission_contact()
    game.camera.snap_to(pygame.Rect(contact[0], contact[1], 1, 1))
    game.draw_side_mission_world()
    assert SIDE_COLOR_PRESENT(game.screen)

    reset_expansion(game, 1)
    game.try_start_side_mission()
    game.screen.fill((1, 2, 3))
    game.camera.snap_to(pygame.Rect(*game.smash_targets[0]['pos'], 1, 1))
    game.draw_side_mission_world()
    assert SIDE_COLOR_PRESENT(game.screen)


def SIDE_COLOR_PRESENT(surface):
    color = M.SIDE_MISSION_MARKER_COLORS[0]
    return any(surface.get_at((x, y))[:3] == color
               for y in range(M.SCREEN_HEIGHT)
               for x in range(M.SCREEN_WIDTH))

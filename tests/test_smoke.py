"""Headless behaviour tests for STL-GTA.

Runs with either `python -m pytest tests` or plain `python tests/test_smoke.py`,
so CI works without adding a test dependency the game itself does not need.

Everything here drives the real Game object against the real baked art and the
real map. There are no mocks: the point is to catch the class of bug this
project actually produces - an entity leaving the map, a physics value going
non-finite, the police count disagreeing with the wanted level, a job marker
that spawns inside a building.
"""
import math
import json
import os
import random
import sys
import tempfile
import wave
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402
import main as M  # noqa: E402

_GAME = None


def game():
    """One Game for the whole module - booting bakes every sprite (~1s)."""
    global _GAME
    if _GAME is None:
        random.seed(20250905)
        _GAME = M.Game()
    return reset(_GAME)


def reset(g):
    """Return the shared Game to a known, quiet state between tests."""
    if g.driving:
        g.driving.driver = None
        g.driving.parked = True
        g.driving = None
    g.score = 0
    g.cash = 200
    g.banked = 0
    g.dropped = []
    g.wanted_level = 0
    g.police = []
    g.bust_meter = 0
    g.heat_timer = 0
    g.wanted_decay_timer = 0
    g.infraction_at = {}
    g.streak = 0
    g.jobs_done = 0
    g.jobs_failed = 0
    g.job_cooldown = 0
    g.job = M.Job.generate()
    g.side_mission = None
    g.side_mission_serial = 0
    g.side_mission_cooldown = 0
    g.side_target_car = None
    g.side_target_pos = None
    g.smash_targets = []
    g.side_missions_done = 0
    g.side_missions_failed = 0
    g.arch_job_unlocked = False
    g.arch_job_completed = False
    g.arch_job_phase = M.ARCH_LOCKED
    g.arch_job_timer = 0
    g.arch_job_offer_after = 0
    g.arch_victory_timer = 0
    g.state = M.STATE_PLAYING
    g.busted_flash = 0
    g.wasted_flash = 0
    g.death_timer = 0
    g.death_kind = None
    g.death_stats = None
    g.cop_dispatch = 0
    g.foot_police = []
    g.foot_cop_respawn = 0
    g.crime_pos = None
    g.crime_frame = -10 ** 9
    g.peak_star = 0
    g.chase_steps = 0
    g.longest_chase = 0
    g.spotted = False
    g.was_spotted = False
    g.searching = False
    g.hidden = False
    g.hide_timer = 0
    g.hs_cooldown = 0
    g.chatter_cooldown = 0
    g.speech_bubbles = []
    g.hurt_cd = 0
    g.grub_until = {}
    for _g in g.grub_pickups:
        _g['taken'] = 0
    # new feedback / reactivity / stakes state
    g.multiplier = 1
    g.mult_prog = 0.0
    g.mult_decay = 0
    g.combo = 0
    g.combo_timer = 0
    g.frenzy = None
    g.frenzy_icon = None
    g.frenzy_cooldown = 0
    g.shake = 0.0
    g.freeze = 0
    g.hit_flash = 0
    g.fx = []
    g.pops = []
    g.callouts = []
    g.toasts = []
    g.decals = []
    g.player_hp = M.PLAYER_MAX_HP
    g.player_stamina = M.PLAYER_STAMINA_MAX
    g.sprinting = False
    g.sprint_active = False
    g.sprint_ready = True
    g.weapon = 'fists'
    g.ammo = 0
    g.weapon_ammo = {kind: 0 for kind in M.WEAPON_ORDER}
    g.owned_weapons = {'fists'}
    g.throwable_system = M.throwable_logic.ThrowableSystem()
    g.attack_cd = 0
    g.attack_held = False
    g.punch_timer = 0
    g.bullets = []
    if hasattr(g, 'player_motion'):
        g.player_motion.update(0, 0)
    for w in g.weapon_pickups:
        w['taken'] = 0
    g.sync_player_float()
    for c in g.cars + g.police:
        c.hp = c.max_hp
        c.burn = 0
    for p in g.pedestrians:
        p.mood = 'calm'
        p.down_timer = 0
        p.mood_timer = 0
        p.knock.update(0, 0)
    return g


def teleport(g, pos):
    g.player_rect.center = (int(pos[0]), int(pos[1]))


# ---------------------------------------------------------------------------
# The loop runs at all
# ---------------------------------------------------------------------------

def dispatch_cops(g, star, limit=None):
    """Pump update_police until the star's full quota of cruisers has arrived.

    Cops are dispatched on a delay now (COP_RESPONSE_BY_STAR) rather than
    materialising the same step the star lands, so every police test has to
    wait for the call to go out.
    """
    g.wanted_level = star
    want = M.COP_COUNT_BY_STAR[star]
    limit = limit if limit is not None else M.FPS * 20
    for _ in range(limit):
        if len(g.police) >= want:
            return g.police
        g.update_police()
        g.bust_meter = 0
        if g.state == M.STATE_DEAD:      # cop parked on the spawn point
            g.state = M.STATE_PLAYING
            g.wanted_level = star
    raise AssertionError(
        f"only {len(g.police)}/{want} cruisers arrived for {star} stars")


def test_headless_run_holds_invariants():
    g = game()
    assert g.run_headless(240, seed=3) == 0


def test_invariants_actually_fail_when_broken():
    """A check that can only ever pass is not a check."""
    g = game()
    assert g.check_invariants() is None
    g.wanted_level = 99
    assert g.check_invariants() is not None
    g.wanted_level = 0
    g.police = [M.Car(500, 500)]
    assert "police count" in g.check_invariants()
    g.police = []
    assert g.check_invariants() is None


# ---------------------------------------------------------------------------
# Fixed timestep
# ---------------------------------------------------------------------------

def test_sim_is_frame_rate_independent():
    """One wall-clock second must advance the sim the same amount whether it
    arrives as 60 frames or as 20."""
    g = game()
    g.frame = 0
    g.accumulator = 0.0
    for _ in range(60):
        g.step_sim(M.SIM_DT)
    at_60 = g.frame

    g.frame = 0
    g.accumulator = 0.0
    for _ in range(20):
        g.step_sim(M.SIM_DT * 3)
    at_20 = g.frame

    assert at_60 == 60, at_60
    assert at_20 == 60, at_20


def test_long_stall_does_not_spiral():
    """A ten second hitch must not try to catch up 600 steps in one frame."""
    g = game()
    g.frame = 0
    g.accumulator = 0.0
    steps = g.step_sim(10.0)
    assert steps <= M.MAX_SIM_STEPS, steps
    assert g.accumulator == 0.0


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def test_job_pairs_are_far_apart_and_reachable():
    probe = pygame.Rect(0, 0, M.PLAYER_SIZE, M.PLAYER_SIZE)
    for _ in range(40):
        job = M.Job.generate()
        assert job.pickup[5] != job.dropoff[5]
        assert job.time_limit >= M.JOB_MIN_SECONDS
        for pos in (job.pickup_pos, job.drop_pos):
            probe.center = pos
            assert not M.is_blocked(probe), f"{job.target_name} marker is inside geometry"


def test_job_cards_change_the_route_in_more_than_name_only():
    a, b = M.LANDMARKS[0], M.LANDMARKS[8]
    courier = M.Job(a, b, kind='courier')
    rush = M.Job(a, b, kind='rush')
    hot = M.Job(a, b, kind='hot')
    heavy = M.Job(a, b, kind='heavy')
    assert rush.time_limit < courier.time_limit < heavy.time_limit
    assert rush.base_reward > courier.base_reward
    assert hot.base_reward > courier.base_reward
    assert heavy.base_reward > courier.base_reward
    assert len({j.label for j in (courier, rush, hot, heavy)}) == 4


def test_job_dealer_does_not_repeat_either_recent_card():
    g = game()
    g.recent_job_kinds = []
    dealt = [g.deal_job().kind for _ in range(12)]
    for i, kind in enumerate(dealt):
        assert kind not in dealt[max(0, i - 2):i], dealt


def test_hot_load_starts_a_chase_and_heavy_haul_has_weight():
    g = game()
    a, b = M.LANDMARKS[0], M.LANDMARKS[8]
    g.job = M.Job(a, b, kind='hot')
    teleport(g, g.job.pickup_pos)
    g.update_job()
    assert g.job.collected and g.wanted_level == 2

    g.wanted_level = 0
    g.police = []
    g.job = M.Job(a, b, kind='heavy')
    teleport(g, g.job.pickup_pos)
    g.update_job()
    car = _drive(g)
    baseline = car.base_max_speed
    g.apply_grub_to_car()
    assert car.max_speed < baseline, "the heavy haul does not change handling"
    g.driving = None


def test_full_delivery_pays_out_and_streaks():
    g = game()
    start_cash = g.cash
    for expected in (1, 2):
        teleport(g, g.job.pickup_pos)
        g.update_job()
        assert g.job.collected, "standing on the pickup should accept the run"
        teleport(g, g.job.drop_pos)
        g.update_job()
        assert g.jobs_done == expected
        assert g.streak == expected
        g.job_cooldown = 0
        g.job = M.Job.generate()
    assert g.cash > start_cash, "finishing runs is the only way to earn cash"


def test_job_expires_and_breaks_the_streak():
    g = game()
    g.streak = 4
    teleport(g, g.job.pickup_pos)
    g.update_job()
    assert g.job.collected
    g.job.steps_left = 1
    teleport(g, (M.MAP_WIDTH // 2, M.MAP_HEIGHT // 2))
    g.update_job()
    assert g.job is None
    assert g.jobs_failed == 1
    assert g.streak == 0


def test_dispatcher_refuses_work_while_hot():
    g = game()
    g.wanted_level = M.JOB_HEAT_LIMIT
    teleport(g, g.job.pickup_pos)
    g.update_job()
    assert not g.job.collected, "cops on your tail should block a pickup"


def test_chaos_pays_score_not_cash():
    """These two counters used to be incremented in lockstep everywhere, which
    made one of them meaningless. Running someone over must not fund a run."""
    g = game()
    cash_before = g.cash
    g.score = 0
    car = M.Car(*g.player_rect.center)
    car.driver = 'player'
    car.velocity = 8.0
    car.rect.center = g.player_rect.center
    g.driving = car
    ped = g.pedestrians[0]
    ped.rect.center = car.rect.center
    ped.bump_cooldown = 0
    g.handle_collisions()
    g.driving = None
    assert g.score > 0
    assert g.cash == cash_before


# ---------------------------------------------------------------------------
# Police / wanted level
# ---------------------------------------------------------------------------

def test_wanted_level_is_whole_stars_and_matches_cop_count():
    g = game()
    for _ in range(8):
        g.infraction_at = {}
        g.wanted_bump(1, 'pedestrian')
    assert g.wanted_level == M.WANTED_MAX
    assert float(g.wanted_level).is_integer()
    dispatch_cops(g, M.WANTED_MAX)
    assert len(g.police) == M.COP_COUNT_BY_STAR[M.WANTED_MAX]


def test_cops_spawn_within_reach_of_the_player():
    """They used to all spawn at the downtown station regardless of where the
    player was, so on the far side of the map they never arrived at all."""
    g = game()
    teleport(g, (20 * M.TILE_SIZE, 80 * M.TILE_SIZE))
    dispatch_cops(g, 3)
    assert g.police
    for cop in g.police:
        d = math.hypot(cop.rect.centerx - g.player_rect.centerx,
                       cop.rect.centery - g.player_rect.centery)
        assert d <= M.COP_SPAWN_MAX + M.TILE_SIZE, d


def test_a_cruiser_cannot_handcuff_an_on_foot_player():
    g = game()
    dispatch_cops(g, 2)
    g.police[0].rect.center = g.player_rect.center
    g.update_police()
    assert g.state == M.STATE_PLAYING
    assert g.bust_meter == 0, "cruiser contact counted as an on-foot arrest"


def test_sustained_contact_does_bust_you():
    """In a car, where a cruiser will actually close on you. Below
    COP_RAMMING_STAR a cruiser deliberately brakes short of a player on foot
    and leaves the arrest to the beat cop - see the test below."""
    g = game()
    car = _drive(g)
    dispatch_cops(g, 2)
    g.cash = 1000
    g.peak_star = 2
    for _ in range(M.BUST_CONTACT_STEPS + 4):
        if g.police:
            g.police[0].rect.center = car.rect.center
        g.update_police()
    assert g.state == M.STATE_DEAD, "sustained contact should have taken you"
    assert g.death_kind == 'busted'
    assert g.wanted_level == 0
    assert g.cash == 1000 - M.BAIL_BY_STAR[2]


def test_a_beat_cop_can_actually_arrest_you_on_foot():
    """The arrest fantasy the old build never once delivered: 30 on-foot
    trials produced 23 run over and 0 arrested, because a cruiser deletes
    100 HP long before BUST_CONTACT_STEPS elapses."""
    g = game()
    teleport(g, (40 * M.TILE_SIZE, 40 * M.TILE_SIZE))
    g.wanted_level = 1
    g.cash = 1000
    for _ in range(M.FPS * 25):
        g.update_police()
        if g.state == M.STATE_DEAD:
            break
    assert g.state == M.STATE_DEAD, "a beat cop never took a stationary player"
    assert g.death_kind == 'busted', "he should arrest you, not kill you"


def test_both_ways_of_dying_wake_you_under_the_arch():
    """One respawn anchor teaches the map. Busting used to teleport you to a
    random tile on a 100x100 grid, then to the station; either way you were
    somewhere else every time and never learned where anything was."""
    entry = next(e for e in M.LANDMARKS if e[5] == "Gateway Arch")
    ax = (entry[0] + entry[2] / 2.0) * M.TILE_SIZE
    ay = (entry[1] + entry[3] / 2.0) * M.TILE_SIZE
    for kill in ('busted', 'wasted'):
        g = game()
        teleport(g, (12 * M.TILE_SIZE, 88 * M.TILE_SIZE))
        g.wanted_level = 2
        getattr(g, kill)()
        assert g.state == M.STATE_DEAD, kill
        g.finish_death()
        d = math.hypot(g.player_rect.centerx - ax, g.player_rect.centery - ay)
        assert d < 8 * M.TILE_SIZE, (
            f"{kill} woke up {d / M.TILE_SIZE:.1f} tiles from the Arch")


def test_heat_does_not_decay_while_a_cop_is_on_you():
    """The old timer shed a star every six seconds regardless, so the optimal
    play against the police was to park and wait them out."""
    g = game()
    dispatch_cops(g, 3)
    for _ in range(M.HEAT_GRACE + M.WANTED_DECAY_STEPS + 60):
        for cop in g.police:
            cop.rect.center = g.player_rect.center
        g.update_police()
        g.update_wanted_decay()
        if g.state == M.STATE_DEAD:     # taken; that is a different test
            g.state = M.STATE_PLAYING
            g.wanted_level = 3
            g.bust_meter = 0
    assert g.wanted_level == 3, "stars fell while cops were sitting on the player"


def test_heat_decays_once_you_are_clear():
    g = game()
    g.wanted_level = 2
    g.police = []
    g.heat_timer = 0
    for _ in range(M.HEAT_GRACE + M.WANTED_DECAY_STEPS + 2):
        g.update_wanted_decay()
    assert g.wanted_level == 1


def test_cops_get_out_of_a_dead_end():
    """The old chase_ai drove straight at the player and ground into the first
    wall between them. A cop boxed against geometry must recover."""
    # This test used whatever random state every alphabetically earlier test
    # happened to leave behind, so adding an unrelated Job.generate() could
    # change the cop's initial heading and flip the assertion. Pin the scenario.
    rng_state = random.getstate()
    g = game()
    random.seed(9)
    cop = M.Car(*g.police_station, color=M.POLICE_COLOR, variant='police')
    cop.driver = 'police'
    target = (g.police_station[0], g.police_station[1] - 900)
    start = cop.rect.center
    for _ in range(400):
        cop.chase_ai(target)
    moved = math.hypot(cop.rect.centerx - start[0], cop.rect.centery - start[1])
    assert moved > 4 * M.TILE_SIZE, f"cop only travelled {moved:.0f}px in 400 steps"
    random.setstate(rng_state)


# ---------------------------------------------------------------------------
# Placement / geometry
# ---------------------------------------------------------------------------

def test_free_point_near_never_returns_a_blocked_spot():
    random.seed(11)
    probe = pygame.Rect(0, 0, M.PLAYER_SIZE, M.PLAYER_SIZE)
    checked = 0
    for _ in range(300):
        spot = M.free_point_near(random.randrange(M.MAP_WIDTH),
                                 random.randrange(M.MAP_HEIGHT),
                                 M.PLAYER_SIZE, M.PLAYER_SIZE)
        if spot is None:
            continue
        probe.center = spot
        assert not M.is_blocked(probe)
        checked += 1
    assert checked > 200, "free_point_near gave up far too often"


def test_getting_out_of_a_car_never_puts_you_in_a_wall():
    """Exit used to be centerx - 40 with no collision test at all, which parked
    the player inside buildings and in the Mississippi."""
    g = game()
    probe = pygame.Rect(0, 0, M.PLAYER_SIZE, M.PLAYER_SIZE)
    exits = 0
    for car in g.cars[:25]:
        g.driving = car
        car.driver = 'player'
        if g.exit_vehicle():
            probe.center = g.player_rect.center
            assert not M.is_blocked(probe), f"exited into geometry at {probe.center}"
            exits += 1
        g.driving = None
        car.driver = None
    assert exits > 15, f"only managed to get out of {exits} cars"


def test_pause_freezes_the_simulation():
    g = game()
    g.state = M.STATE_PAUSED
    g.handle_events()
    assert g.player_dir == [0, 0]
    g.state = M.STATE_PLAYING


def test_escape_pauses_and_does_not_quit():
    """ESC and Q both used to hard-quit mid-drive with no confirmation, and Q
    sits one key away from WASD."""
    g = game()
    g.running = True
    g.state = M.STATE_PLAYING
    g.handle_keydown(pygame.K_q)
    assert g.running, "Q must not quit during play"
    g.handle_keydown(pygame.K_ESCAPE)
    assert g.state == M.STATE_PAUSED
    assert g.running
    g.handle_keydown(pygame.K_ESCAPE)
    assert g.state == M.STATE_PLAYING


# ---------------------------------------------------------------------------
# Config coherence
# ---------------------------------------------------------------------------

def test_grid_constants_are_not_duplicated():
    """These were hand-copied literals in three places, so changing the map
    size left props, parking and traffic addressing a different grid."""
    assert M.props_TILE_SIZE == M.TILE_SIZE
    assert M.parking_TILE_SIZE == M.TILE_SIZE
    assert M.parking_MAP_TILES_W == M.MAP_TILES_W
    assert M.traffic_TILE_ROAD == M.TILE_ROAD
    assert M.props_ROAD_ORIGIN == M.ROAD_ORIGIN
    assert M.parking_ROAD_STEP == M.ROAD_STEP


def test_every_hud_string_is_renderable():
    """The HUD font is a hand-authored 5x7 bitmap set. Any glyph it lacks
    draws as a filled box, so cargo names and landmark names have to stay
    inside the charset."""
    ok = set(M.hud_CHARSET)
    # These all appear in live menus/dialogue; a missing glyph is a solid box.
    assert {"+", "(", ")", ">", '"'} <= ok, "live UI punctuation is incomplete"
    strings = list(M.Job.CARGO)
    strings += [lm[5] for lm in M.LANDMARKS]
    strings += [s for pair in M.Game.PAUSE_LINES for s in pair]
    strings += list(M.CALLOUT_STRINGS)
    strings += [s[0] for pool in M.HOOD_SIGNS.values() for s in pool]
    strings += list(M.COMBO_SHOUTS.values())
    strings += [f.replace("{n}", "99") for (f, _t, _b) in M.Frenzy.KINDS.values()]
    strings += ["MULTIPLIER X8", "FRENZY 8  40S", "DAMAGE", "HEALTH",
                "FRENZY DONE +6000", "+250", "+$430"]
    strings += ["PAUSED", "DRIVING", "ON FOOT", "BUSTING", "BUSTED!",
                "DELIVER TO", "PICK UP AT", "STREAK X9", "LOST THEM",
                "JACKED A RIDE!", "NO ROOM TO GET OUT!",
                "TOO HOT - LOSE THE COPS FIRST", "CARGO IMPOUNDED",
                "TOO SLOW - RUN LOST", "PRESS ESC FOR CONTROLS",
                "RUNS 0  LOST 0  BEST X0", "WANTED! LOSE THEM OR GET BUSTED",
                "DELIVERED! $430 (X3 STREAK)", "YIKES! +5"]
    for text in strings:
        missing = set(text.upper()) - ok
        assert not missing, f"{text!r} needs glyphs {sorted(missing)}"


def test_objective_panel_leaves_room_for_the_clock():
    """The countdown is right-aligned on the headline row; a long landmark
    name must not run underneath the digits."""
    g = game()
    longest = max((lm[5] for lm in M.LANDMARKS), key=len)
    head_w = M.hud_text_width(f"DELIVER TO {longest}", 1)
    gutter = M.hud_text_width("000", 1) + 8
    assert head_w + gutter + 16 < M.SCREEN_WIDTH, "objective panel would overflow the screen"
    teleport(g, g.job.pickup_pos)
    g.update_job()
    assert g.job.collected
    g.draw()          # must not raise with a live clock


# ---------------------------------------------------------------------------
# Rendering stability / driving feel / map (post-demo fixes)
# ---------------------------------------------------------------------------

def test_building_lights_do_not_flicker_when_the_camera_pans():
    """The facade window-lit roll was salted on the window's *screen* x, so it
    re-rolled on every camera move and the lights strobed as you walked. A
    one-pixel pan must leave the building band pixel-stable."""
    g = game()
    teleport(g, (36 * M.TILE_SIZE, 20 * M.TILE_SIZE))
    g.driving = None
    g.camera.lead_x = g.camera.lead_y = 0.0
    g.camera.center_on(g.active_rect())
    base_x = g.camera.x
    g.draw()
    a = g.screen.copy()
    g.camera.x = base_x + 1
    g.draw()
    b = g.screen.copy()

    # World content only: skip the HUD's fixed-position corners.
    changed = 0
    for y in range(58, 138):
        for x in range(240, 540):
            if a.get_at((x + 1, y)) != b.get_at((x, y)):
                changed += 1
    assert changed < 250, f"{changed}px moved under a 1px pan - windows are re-rolling"


def test_full_map_toggles_freezes_input_and_renders():
    g = game()
    assert not g.show_map
    g.handle_keydown(pygame.K_m)
    assert g.show_map, "M should open the city map"
    assert not (g.state == M.STATE_PLAYING and not g.show_map), (
        "run()'s step gate must be false while the map is up")

    # held keys are neutralised so nothing rolls behind the map
    g.handle_events()
    assert g.player_dir == [0, 0]

    g.draw()  # plots player / police / job markers - must not raise

    g.handle_keydown(pygame.K_ESCAPE)
    assert not g.show_map, "ESC should close the map, not pause"
    assert g.state == M.STATE_PLAYING

    g.handle_keydown(pygame.K_TAB)
    assert g.show_map, "TAB should also open the map"
    g.handle_keydown(pygame.K_TAB)
    assert not g.show_map


def test_a_car_slides_along_a_wall_instead_of_dead_stopping():
    """Driving into a wall at an angle used to reverse the whole velocity, so
    a narrow street was a pinball table. A blocked diagonal now keeps whichever
    axis is clear."""
    g = game()
    spot = None
    for r in range(7, M.MAP_TILES_H - 7):
        for c in range(7, M.MAP_TILES_W - 7):
            if (M.GAME_MAP[r][c]['collidable'] and M.GAME_MAP[r - 1][c]['collidable']
                    and not M.GAME_MAP[r][c - 1]['collidable']
                    and not M.GAME_MAP[r - 1][c - 1]['collidable']):
                spot = (c, r)
                break
        if spot:
            break
    assert spot, "no wall-with-open-west-face geometry on the map"
    c, r = spot

    # a plain sedan so the collider is the documented 34x18, not a bus
    car = M.Car((c - 1) * M.TILE_SIZE + 40, r * M.TILE_SIZE + 40, variant='sedan')
    car.driver = 'player'
    car.max_speed = M.PLAYER_CAR_MAX_SPEED
    car.angle = -0.6           # mostly east (into the wall), partly north
    car.velocity = 6.0
    x0, y0 = car.rect.centerx, car.rect.centery
    # Keep this inside the wall segment being tested; with eased throttle the
    # later path reaches the perpendicular cap at the end of the facade.
    for _ in range(30):
        car.input_throttle = 1.0
        car.input_steer = 0.0
        car.physics_step()

    # Player throttle now eases in instead of delivering the whole acceleration
    # constant on frame one, so this is intentionally slower than the old 40px.
    assert y0 - car.rect.centery > 20, (
        f"car only crawled {y0 - car.rect.centery}px along the wall")
    # hugging the face is fine; punching a third of a tile through it is not
    assert car.rect.centerx <= x0 + 16, "car slid through the wall it hit"


# ---------------------------------------------------------------------------
# Bring-it-to-life systems: feedback, reactivity, stakes
# ---------------------------------------------------------------------------

def _open_road_point():
    """Centre of a road tile with road either side - somewhere a car can
    actually accelerate without immediately hitting geometry."""
    for row in range(6, M.MAP_TILES_H - 6):
        for col in range(6, M.MAP_TILES_W - 6):
            if all(M.tile_type_at(col + d, row) == M.TILE_ROAD
                   for d in (-1, 0, 1)):
                return (col * M.TILE_SIZE + M.TILE_SIZE // 2,
                        row * M.TILE_SIZE + M.TILE_SIZE // 2)
    raise AssertionError("no open road anywhere on the map")


def _drive(g, variant='sedan'):
    # not appended to g.cars: the driving car is tracked by g.driving, and
    # leaking it into the ambient pool drifts counts across the shared Game.
    car = M.Car(*g.player_rect.center, variant=variant)
    car.rect.center = g.player_rect.center
    car.driver = 'player'
    car.max_speed = M.PLAYER_CAR_MAX_SPEED
    g.driving = car
    return car


def test_chaos_multiplier_climbs_then_wipes_on_death():
    g = game()
    car = _drive(g)
    # bowl a line of pedestrians at splattering speed
    for i in range(12):
        ped = g.pedestrians[0]
        ped.rect.center = (car.rect.centerx + 18, car.rect.centery)
        ped.bump_cooldown = 0
        car.velocity = 8.0
        car.angle = 0.0
        g.handle_collisions()
    assert g.combo >= 8, g.combo
    assert g.multiplier > 1, "chaos should have fed the multiplier"
    high = g.multiplier
    g.busted()
    assert g.multiplier == 1, f"a bust must wipe the multiplier (was {high})"
    assert g.state == M.STATE_DEAD, "a bust must enter the death state"


def test_speed_decides_knocked_down_versus_splattered():
    """Below SPLAT_SPEED they get up again; at or above it they do not."""
    g = game()
    car = _drive(g)
    car.angle = 0.0

    ped = g.pedestrians[0]
    ped.rect.center = (car.rect.centerx + 18, car.rect.centery)
    ped.bump_cooldown = 0
    car.velocity = M.SPLAT_SPEED - 1.5
    g.handle_collisions()
    assert ped in g.pedestrians, "a slow bump must not kill anyone"
    assert ped.down_timer > 0, "a slow bump should knock them down"

    n_before = len(g.pedestrians)
    decals_before = len(g.decals)
    victim = next(p for p in g.pedestrians if p.down_timer <= 0)
    victim.rect.center = (car.rect.centerx + 18, car.rect.centery)
    victim.bump_cooldown = 0
    car.velocity = M.SPLAT_SPEED + 1.0
    g.handle_collisions()
    assert victim not in g.pedestrians, "a fast hit must splatter them"
    assert len(g.pedestrians) == n_before, "the street should be repopulated"
    assert len(g.decals) > decals_before, "a kill leaves a stain on the road"


def test_speeding_car_makes_pedestrians_flee():
    g = game()
    car = _drive(g)
    car.velocity = 7.0
    near = g.pedestrians[0]
    near.rect.center = (car.rect.centerx + 60, car.rect.centery + 8)
    near.mood = 'calm'
    near.down_timer = 0
    near.update(g)
    assert near.mood == 'flee', near.mood
    # a parked car must NOT spook anyone
    g.driving = None
    calm = g.pedestrians[1]
    calm.rect.center = (car.rect.centerx + 30, car.rect.centery)
    calm.mood = 'calm'
    calm.update(g)
    assert calm.mood == 'calm'


def test_a_totalled_car_explodes_and_the_pool_stays_stable():
    g = game()
    g.wanted_level = 0
    victim = next(c for c in g.cars if c.driver is None)
    n_before = len(g.cars)
    score_before = g.score
    victim.damage(9999)
    assert victim.burn > 0, "zero HP should light the fuse"
    for _ in range(int(M.FPS * 2)):
        g.update_wrecks()
        if victim not in g.cars:
            break
    assert victim not in g.cars, "the wreck should have exploded"
    assert len(g.cars) == n_before, "traffic count must be held steady"
    assert g.score > score_before
    assert g.shake > 0 and len(g.fx) > 0, "explosion should throw juice"


def test_exploding_cop_car_keeps_the_police_count_invariant():
    g = game()
    dispatch_cops(g, 3)
    assert len(g.police) == M.COP_COUNT_BY_STAR[3]
    g.police[0].burn = 1
    g.update()                       # update_wrecks then update_police, same step
    assert g.check_invariants() is None, g.check_invariants()
    assert len(g.police) <= M.COP_COUNT_BY_STAR[3]


def test_hitstop_freezes_exactly_one_step():
    g = game()
    car = _drive(g)
    car.rect.center = (40 * M.TILE_SIZE, 40 * M.TILE_SIZE)
    car.velocity = 3.0
    car.angle = 0.0
    g.freeze = 2
    x0 = car.rect.centerx
    f0 = g.frame
    g.update()
    assert g.frame == f0 + 1, "frame still advances during a freeze"
    assert car.rect.centerx == x0, "sim is frozen, nothing moved"
    assert g.freeze == 1


def test_frenzy_icon_is_reachable_and_counts_down():
    g = game()
    g.frenzy = None
    g.frenzy_icon = None
    g.frenzy_cooldown = 0
    g.spawn_frenzy_icon()
    assert g.frenzy_icon is not None
    ix, iy, kind = g.frenzy_icon
    probe = pygame.Rect(0, 0, M.PLAYER_SIZE, M.PLAYER_SIZE)
    probe.center = (ix, iy)
    assert not M.is_blocked(probe), "frenzy icon spawned inside geometry"
    teleport(g, (ix, iy))
    g.update_frenzy()
    assert g.frenzy is not None, "standing on the icon should start the frenzy"
    left = g.frenzy.steps_left
    g.update_frenzy()
    assert g.frenzy.steps_left == left - 1


def test_cop_frenzy_spawns_and_counts_foot_officers_and_cruisers():
    g = game()
    g.frame = 14  # (frame // 7) % 3 selects the cop frenzy.
    g.frenzy_icon = None
    g.spawn_frenzy_icon()
    assert g.frenzy_icon is not None and g.frenzy_icon[2] == 'cop'
    assert M.COP_FOOT_BY_STAR[4] > 0 and M.COP_FOOT_BY_STAR[5] > 0

    g.frenzy = M.Frenzy('cop')
    g.frenzy.remaining = 2
    foot = M.FootCop(g.player_rect.centerx + 40, g.player_rect.centery)
    g.foot_police = [foot]
    g.kill_foot_cop(foot, cause='test')
    assert g.frenzy is not None and g.frenzy.remaining == 1

    cruiser = M.Car(g.player_rect.centerx + 80, g.player_rect.centery,
                    color=M.POLICE_COLOR, variant='police')
    cruiser.driver = 'police'
    g.police = [cruiser]
    g.explode(cruiser)
    assert g.frenzy is None, "destroying a cruiser should complete the cop frenzy"
    assert any('FRENZY DONE' in callout['text'] for callout in g.callouts)


def test_camera_shake_is_zero_at_rest():
    """Shake must not perturb the world when nothing has hit - the camera-pan
    flicker test depends on a still frame being still."""
    g = game()
    g.shake = 0.0
    g.draw()
    assert g.camera.shake_ox == 0.0 and g.camera.shake_oy == 0.0


# ---------------------------------------------------------------------------
# Movement, combat and landmark geometry
# ---------------------------------------------------------------------------

def test_walking_keeps_full_diagonal_speed():
    """int(dx) used to truncate a 2.97px diagonal step to 2, costing a third
    of the player's speed and throwing every fraction away."""
    g = game()
    g.driving = None
    # Forest Park: 22x22 tiles of open ground, room to actually walk 4 tiles
    fp = next(e for e in M.LANDMARKS if e[5] == "Forest Park")
    g.player_rect.center = ((fp[0] + 3) * M.TILE_SIZE, (fp[1] + 3) * M.TILE_SIZE)
    g.sync_player_float()
    assert not M.is_blocked(g.player_rect)
    x0, y0 = g.player_fx, g.player_fy
    g.player_dir = [0.707, 0.707]
    for _ in range(60):
        g.move_player_on_foot()
    travelled = math.hypot(g.player_fx - x0, g.player_fy - y0)
    assert travelled > M.PLAYER_SPEED * 60 * 0.97, travelled


def test_walking_eases_up_to_speed_instead_of_lunging():
    g = game()
    g.driving = None
    g.player_motion.update(0, 0)
    g.player_dir = [1.0, 0.0]
    g.move_player_on_foot()
    assert 0.0 < g.player_motion.x < M.PLAYER_SPEED * 0.6
    for _ in range(12):
        g.move_player_on_foot()
    assert g.player_motion.x > M.PLAYER_SPEED * 0.99


def test_player_car_throttle_and_steering_have_input_ramp():
    g = game()
    car = _drive(g)
    car.rect.center = _open_road_point()
    car.angle = 0.0
    car.velocity = 1.0
    car.input_throttle = 1.0
    car.input_steer = 1.0
    car.physics_step()
    gain = (car.acceleration * M.PLAYER_THROTTLE_RESPONSE
            * (1.0 - M.PLAYER_POWER_FADE * (1.0 / car.max_speed)))
    assert math.isclose(car.velocity, 1.0 + gain, rel_tol=1e-6)
    # Steering is rate-limited toward the lock rather than snapping to it: one
    # step of full input gets you a fraction of the wheel, not all of it. The
    # lock itself is read after the throttle, off this step's new speed.
    lock = car.max_steer * (1.0 - M.PLAYER_LOCK_FADE * (car.velocity / car.max_speed))
    assert 0.0 < car.steer_angle < lock
    assert math.isclose(car.steer_angle, lock * M.PLAYER_STEER_RATE, rel_tol=1e-6)
    assert M.PLAYER_CAR_MAX_SPEED < 9.5
    g.driving = None


def test_the_turning_circle_opens_up_with_speed():
    """A car corners tighter slowly than it does flat out.

    The old model multiplied yaw by (0.45 + 0.55 * speed_frac), so the car
    turned HARDER the faster it went - 288 deg/s and a 103px radius at top
    speed against 43px when crawling. Backwards, and the reason fast driving
    felt like a twitch rather than a car.
    """
    g = game()
    radii = []
    for frac in (0.3, 0.65, 1.0):
        car = _drive(g)
        car.rect.center = _open_road_point()
        car.angle = 0.0
        car.steer_angle = 0.0
        v = car.max_speed * frac
        for settle in range(2):
            a0 = car.angle
            for _ in range(60):
                car.rect.center = _open_road_point()   # pure physics, no geometry
                car.velocity = v
                car.input_throttle = 0.0
                car.input_steer = 1.0
                car.input_handbrake = False
                car.physics_step()
            yaw = abs(car.angle - a0)
        radii.append(v * 60.0 / yaw)
    assert radii[0] < radii[1] < radii[2], f"radius must grow with speed, got {radii}"
    assert radii[0] < 60, f"a slow car should still turn tightly, got {radii[0]:.0f}px"
    assert radii[2] > 140, f"a fast car should sweep wide, got {radii[2]:.0f}px"
    g.driving = None


def test_sub_pixel_travel_is_carried_not_thrown_away():
    """rect.move(int(dx), int(dy)) used to discard the fraction every step.

    A car doing 0.9px/step moved zero pixels forever - which is how ambient
    traffic deadlocked - and a diagonal lost 12% of its speed against a
    cardinal, because the truncation happens per axis.
    """
    g = game()
    car = _drive(g)
    car.driver = None            # ambient traffic: the case that used to freeze
    car.parked = False
    start = _open_road_point()
    car.rect.center = start
    car.angle = 0.0
    for _ in range(120):
        car.velocity = 0.9
        car.input_throttle = 0.0
        car.input_steer = 0.0
        car.input_handbrake = False
        car.physics_step()
    travelled = car.rect.centerx - start[0]
    assert travelled > 100, f"a 0.9px/step car went nowhere in 2s: {travelled}px"

    # ... and a diagonal covers the same ground as a cardinal. Measured a step
    # at a time with the car snapped back to open road, so this is the travel
    # the physics produces and not an argument about where the buildings are.
    def run(angle):
        home = _open_road_point()
        c = M.Car(*home, variant='sedan')
        c.driver = 'player'
        c.angle = angle
        total = 0.0
        for _ in range(240):
            c.rect.center = home
            c.velocity = 3.0
            c.input_throttle = 0.0
            c.input_steer = 0.0
            c.input_handbrake = False
            c.physics_step()
            total += math.hypot(c.rect.centerx - home[0], c.rect.centery - home[1])
        return total
    east = run(0.0)
    diag = run(math.pi / 4)
    assert abs(diag - east) / east < 0.04, f"diagonal {diag:.0f} vs east {east:.0f}"
    g.driving = None


def test_the_camera_never_loses_the_car_it_is_following():
    """At speed the vertical look-ahead used to be 229px on a 180px half-
    viewport, so driving north or south pushed the car off the screen."""
    g = game()
    car = _drive(g)
    worst = 0.0
    for k in range(8):
        ang = k * math.tau / 8.0
        x, y = M.MAP_WIDTH // 2, M.MAP_HEIGHT // 2
        car.angle = ang
        car.velocity = car.max_speed
        for i in range(200):
            car.rect.center = (int(x + math.cos(ang) * car.max_speed * i),
                               int(y + math.sin(ang) * car.max_speed * i))
            if not (60 < car.rect.centerx < M.MAP_WIDTH - 60
                    and 60 < car.rect.centery < M.MAP_HEIGHT - 60):
                break
            g.camera.center_on(car.rect, g._camera_lead())
            sx, sy = g.camera.apply_pos(car.rect.center)
            assert 20 <= sx <= M.SCREEN_WIDTH - 20, f"car off screen in x at {math.degrees(ang):.0f} deg"
            assert 20 <= sy <= M.SCREEN_HEIGHT - 20, f"car off screen in y at {math.degrees(ang):.0f} deg"
            worst = max(worst, abs(sx - M.SCREEN_WIDTH / 2) / (M.SCREEN_WIDTH / 2),
                        abs(sy - M.SCREEN_HEIGHT / 2) / (M.SCREEN_HEIGHT / 2))
    assert worst < 0.6, f"the lead eats {worst:.0%} of the half-viewport"
    g.driving = None


def test_the_police_do_not_simply_outrun_every_car_you_can_steal():
    """Escalation is numbers and aggression, not a speed the player cannot buy.

    Every star used to be faster than the player's own top speed, so a
    straight-line escape did not exist at any wanted level.
    """
    sedan = M.PLAYER_CAR_MAX_SPEED
    assert M.COP_SPEED_BY_STAR[1] < sedan, "one star should be outrunnable in anything"
    assert M.COP_SPEED_BY_STAR[2] < sedan
    fast = M.PLAYER_CAR_MAX_SPEED * M.VEHICLE_TUNING['trans_am']['speed_factor']
    assert M.COP_SPEED_BY_STAR[M.WANTED_MAX] < fast, (
        "the fastest car in the game has to beat the top of the ladder, "
        "or stealing it is decoration")
    assert M.COP_SPEED_BY_STAR[M.WANTED_MAX] > sedan, (
        "five stars in a standard sedan should not be a stroll")


def test_you_cannot_be_arrested_through_the_window_of_a_moving_car():
    g = game()
    car = _drive(g)
    car.rect.center = _open_road_point()
    g.wanted_level = 3
    g.police = []
    cop = M.Car(*car.rect.center, color=M.POLICE_COLOR, variant='police')
    cop.driver = 'police'
    cop.rect.center = car.rect.center
    g.police = [cop]
    g.bust_meter = 0
    car.velocity = M.BUST_MAX_SPEED + 2.0
    for _ in range(M.BUST_CONTACT_STEPS * 2):
        cop.rect.center = car.rect.center
        car.velocity = M.BUST_MAX_SPEED + 2.0
        g.update_police()
    assert g.state != M.STATE_DEAD, "busted while driving flat out"
    assert g.bust_meter == 0

    # Stopped in the same spot, they do take you.
    g.bust_meter = 0
    for _ in range(M.BUST_CONTACT_STEPS + 8):
        cop.rect.center = car.rect.center
        car.velocity = 0.0
        g.update_police()
    assert g.state == M.STATE_DEAD, "a stopped car is an arrest"
    g.state = M.STATE_PLAYING
    g.wanted_level = 0
    g.police = []
    g.bust_meter = 0
    g.driving = None


def test_traffic_pulls_out_around_a_car_parked_in_its_lane():
    """A kerbside car used to stop a lane forever: parking sat at 14-18px off
    the centre line and the driving lane at 15px, so every parked car was an
    immovable obstacle the follow rule braked to a halt behind."""
    assert M.parking_KERB_OFFSET_MIN > M.traffic_LANE_OFFSET, (
        "parked cars must not be parked in the driving lane")
    g = game()
    row = sorted(M.ROAD_LINES)[6]
    lane = M.traffic__lane_coord(0, row)
    # Start mid-block on the longest clear span. The grid is irregular now, so
    # "col 6" is no longer guaranteed to have room to complete a pass before
    # the next junction, and a car that turns first never overtakes anything.
    lines = sorted(M.ROAD_LINES)
    a, b = max(zip(lines, lines[1:]), key=lambda pair: pair[1] - pair[0])
    start_col = a + 1
    mover = M.Car(start_col * M.TILE_SIZE, int(lane), variant='sedan')
    mover.rect.center = (start_col * M.TILE_SIZE, int(lane))
    mover.angle = 0.0
    mover.driver = None
    mover.parked = False
    M.traffic_init_car(mover)
    M.traffic_snap_to_lane(mover)
    blocker = M.Car(mover.rect.centerx + 150, int(lane), variant='sedan')
    blocker.rect.center = (mover.rect.centerx + 150, int(lane))
    blocker.angle = 0.0
    blocker.velocity = 0.0
    blocker.parked = True
    x0 = mover.rect.centerx
    for _ in range(420):
        M.traffic_drive(mover, (mover, blocker))
        if mover.rect.centerx > blocker.rect.centerx + 40:
            break            # it passed; where it goes afterwards is its own business
    assert mover.rect.centerx > blocker.rect.centerx + 40, (
        f"traffic queued behind a parked car instead of passing it: "
        f"moved {mover.rect.centerx - x0}px")


def test_walking_slides_along_a_wall_instead_of_sticking():
    g = game()
    g.driving = None
    spot = None
    for r in range(7, M.MAP_TILES_H - 7):
        for c in range(7, M.MAP_TILES_W - 7):
            if (M.GAME_MAP[r][c]['collidable']
                    and not M.GAME_MAP[r][c - 1]['collidable']
                    and not M.GAME_MAP[r - 1][c - 1]['collidable']):
                spot = (c, r)
                break
        if spot:
            break
    assert spot
    c, r = spot
    g.player_rect.center = ((c - 1) * M.TILE_SIZE + 40, r * M.TILE_SIZE + 40)
    g.sync_player_float()
    y0 = g.player_fy
    g.player_dir = [0.707, -0.707]     # into the wall, and north
    for _ in range(40):
        g.move_player_on_foot()
    assert y0 - g.player_fy > 30, "player stuck on the wall instead of sliding"


def test_punch_drops_a_ped_and_a_second_punch_kills():
    g = game()
    g.driving = None
    g.player_rect.center = M.random_open_spawn()
    g.sync_player_float()
    g.player_aim = 0.0
    ped = g.pedestrians[0]
    ped.rect.center = (g.player_rect.centerx + 20, g.player_rect.centery)
    ped.down_timer = 0
    ped.mood = 'calm'
    g.attack_cd = 0
    g.player_attack()
    assert ped.down_timer > 0, "a punch should put them on the floor"
    assert ped in g.pedestrians

    n_before = len(g.pedestrians)
    ped.rect.center = (g.player_rect.centerx + 20, g.player_rect.centery)
    g.attack_cd = 0
    g.player_attack()
    assert ped not in g.pedestrians, "punching a downed ped should finish them"
    assert len(g.pedestrians) == n_before


def test_pistol_pickup_arms_you_and_bullets_kill():
    g = game()
    g.driving = None
    w = g.weapon_pickups[0]
    w['taken'] = 0
    g.player_rect.center = (int(w['x']), int(w['y']))
    g.sync_player_float()
    g.update_weapon_pickups()
    assert g.weapon == 'pistol' and g.ammo == M.PISTOL_AMMO

    g.player_aim = 0.0
    g.attack_cd = 0
    g.player_attack()
    assert g.ammo == M.PISTOL_AMMO - 1, "firing should spend a round"
    assert g.bullets, "a shot should put a bullet in the air"
    assert g.wanted_level >= 1, "gunfire in public is a crime"

    victim = g.pedestrians[0]
    victim.rect.center = (int(g.bullets[0]['x'] + 14), int(g.bullets[0]['y']))
    n_before = len(g.pedestrians)
    for _ in range(6):
        g.update_bullets()
    assert victim not in g.pedestrians, "the bullet should have killed them"
    assert len(g.pedestrians) == n_before


def _spawn_foot_cop(g):
    g.wanted_level = 1
    g.foot_cop_respawn = 0
    g.update_police()
    assert g.foot_police
    return g.foot_police[0]


def test_foot_cops_can_be_hit_killed_and_stay_gone_for_reinforcement_delay():
    g = game()
    cop = _spawn_foot_cop(g)
    cop.rect.center = (g.player_rect.centerx + 20, g.player_rect.centery)
    cop.fx, cop.fy = map(float, cop.rect.center)
    g.player_aim = 0.0
    g.weapon = 'bat'
    g.owned_weapons.add('bat')
    g.player_attack()
    assert cop not in g.foot_police, "baseball bat left the beat cop invulnerable"
    assert g.foot_cop_respawn == M.COP_FOOT_RESPAWN
    assert g.wanted_level >= 3
    g.update_foot_police(3, g.player_rect, g.player_rect.center)
    assert not g.foot_police, "dead officer was replaced immediately"


def test_pistol_rounds_damage_foot_cops_and_interrupt_an_arrest():
    g = game()
    cop = _spawn_foot_cop(g)
    cop.rect.center = (g.player_rect.centerx + 25, g.player_rect.centery)
    cop.fx, cop.fy = map(float, cop.rect.center)
    g.bust_meter = M.BUST_CONTACT_STEPS // 2
    g.weapon = 'pistol'
    g.owned_weapons.add('pistol')
    g.ammo = 2
    g.weapon_ammo['pistol'] = 2
    g.player_aim = 0.0
    g.player_attack()
    for _ in range(3):
        g.update_bullets()
    assert cop.hp < M.COP_FOOT_HP
    assert cop.down_timer > 0
    assert g.bust_meter < M.BUST_CONTACT_STEPS // 2


def test_a_fast_car_splatters_a_foot_cop():
    g = game()
    cop = _spawn_foot_cop(g)
    car = _drive(g)
    car.velocity = M.SPLAT_SPEED + 1.0
    cop.rect.center = car.rect.center
    cop.fx, cop.fy = map(float, cop.rect.center)
    g.handle_collisions()
    assert cop not in g.foot_police


def test_sprint_is_faster_than_a_beat_cop_but_has_a_stamina_budget():
    g = game()
    road_row = sorted(M.ROAD_LINES)[1]      # row 4 is no longer a street
    teleport(g, (10 * M.TILE_SIZE + 32, road_row * M.TILE_SIZE + 32))
    g.sync_player_float()
    g.player_dir = [1.0, 0.0]
    g.sprinting = True
    start = g.player_rect.centerx
    for _ in range(M.FPS * 2):
        g.move_player_on_foot()
    assert g.player_rect.centerx - start > M.PLAYER_SPEED * M.FPS * 2
    assert g.player_stamina < M.PLAYER_STAMINA_MAX
    assert M.PLAYER_SPRINT_SPEED > M.COP_FOOT_BURST_SPEED
    assert M.COP_FOOT_SEARCH_SPEED < M.PLAYER_SPEED


def test_weapon_pickups_cover_the_full_arsenal_and_shotgun_has_a_spread():
    g = game()
    assert {w['kind'] for w in g.weapon_pickups} == set(M.WEAPON_PICKUP_KINDS)
    g.owned_weapons.update(M.WEAPON_ORDER)
    g.weapon_ammo.update({'pistol': 5, 'shotgun': 3, 'smg': 12})
    g.weapon = 'shotgun'
    g.ammo = 3
    g.player_attack()
    assert len(g.bullets) == M.WEAPON_DEFS['shotgun']['pellets']
    assert g.ammo == 2
    angles = {round(math.atan2(b['vy'], b['vx']), 2) for b in g.bullets}
    assert len(angles) > 1
    g.cycle_weapon()
    assert g.weapon == 'smg'


def test_ramming_a_car_actually_moves_it():
    """Traffic used to absorb a full-speed broadside without twitching."""
    g = game()
    car = _drive(g)
    car.angle = 0.0
    car.velocity = 9.0
    victim = next(c for c in g.cars if c.driver is None)
    victim.velocity = 0.0
    victim.angle = 0.0
    victim.rect.center = (car.rect.centerx + 26, car.rect.centery)
    before = victim.velocity
    g.handle_collisions()
    assert victim.velocity > before + 0.5, (
        f"rammed car barely moved: {before} -> {victim.velocity}")


def test_population_streams_toward_the_player():
    """The viewport is 0.56% of the map, so a population spread over the whole
    city is a population you never see - 40 peds measured 0.0 visible. Anything
    that wanders out of earshot has to come back to just off-screen."""
    g = game()
    g.driving = None
    teleport(g, M.random_open_spawn())
    g.sync_player_float()
    # scatter everyone to the far corners
    for i, ped in enumerate(g.pedestrians):
        ped.rect.center = (200 + (i % 5) * 40, 200 + (i // 5) * 40)
        ped.down_timer = 0
    ax, ay = g.player_rect.center
    far0 = sum(1 for p in g.pedestrians
               if math.hypot(p.rect.centerx - ax, p.rect.centery - ay) > M.POP_KEEP_RADIUS)
    assert far0 > 20, "test setup should have scattered them"

    for _ in range(len(g.pedestrians) * 2):
        g.player_dir = [0, 0]
        g.update_population()
    ax, ay = g.player_rect.center
    far1 = sum(1 for p in g.pedestrians
               if math.hypot(p.rect.centerx - ax, p.rect.centery - ay) > M.POP_KEEP_RADIUS)
    assert far1 < far0 // 4, f"streaming left {far1} of {far0} stragglers behind"
    # and nothing pops into view: recycled entities land outside the viewport
    for ped in g.pedestrians:
        d = math.hypot(ped.rect.centerx - ax, ped.rect.centery - ay)
        assert d < M.POP_KEEP_RADIUS + M.TILE_SIZE or ped.down_timer > 0
    assert M.POP_RESPAWN_MIN > math.hypot(M.SCREEN_WIDTH / 2, M.SCREEN_HEIGHT / 2), \
        "respawn ring must sit outside the viewport corner"


def test_every_live_pedestrian_stays_on_walkable_non_building_ground():
    """Initial, roaming, streamed and replacement walkers share one invariant.

    In particular, an invalid downed pedestrian must not be preserved on a
    building tile merely because population streaming normally leaves bodies
    in place until their fall animation has finished.
    """
    g = game()

    def assert_grounded():
        for ped in g.pedestrians:
            assert M.pedestrian_ground_is_clear(ped.rect), (
                ped.rect.center,
                M.tile_type_at(ped.rect.centerx // M.TILE_SIZE,
                               ped.rect.centery // M.TILE_SIZE))

    assert_grounded()                       # initial population
    for _ in range(240):                    # ordinary and panic roaming
        for ped in g.pedestrians:
            ped.update(g)
    assert_grounded()

    victim = g.pedestrians[0]
    g.splatter_ped(victim, pygame.Vector2(), score=False)
    assert len(g.pedestrians) == M.PEDESTRIAN_COUNT
    assert_grounded()                       # replacement population

    # Force the exact bad state seen in captures: a live actor centred on a
    # roof. Keep it downed so this also covers the streaming early-return.
    roof = next((c, r) for r in range(M.MAP_TILES_H)
                for c in range(M.MAP_TILES_W)
                if M.tile_type_at(c, r) == M.TILE_BUILDING)
    bad = g.pedestrians[0]
    bad.rect.center = (roof[0] * M.TILE_SIZE + M.TILE_SIZE // 2,
                       roof[1] * M.TILE_SIZE + M.TILE_SIZE // 2)
    bad.down_timer = 30
    assert not M.pedestrian_ground_is_clear(bad.rect)
    g.update_population()
    assert_grounded()                       # defensive live-pool repair


def test_population_retypes_to_the_neighborhood_it_streams_into():
    g = game()
    busch = next(lm for lm in M.LANDMARKS if lm[5] == "Busch Stadium")
    bx = (busch[0] + busch[2] // 2) * M.TILE_SIZE
    by = (busch[1] + busch[3] // 2) * M.TILE_SIZE
    ped = M.Pedestrian(6000, 6000, "dog_walker#0")
    old_pedestrians = g.pedestrians
    g.pedestrians = [ped]
    teleport(g, (200, 200))
    g.sync_player_float()
    try:
        with patch.object(M, "ring_spawn_near", return_value=(bx, by)), \
                patch.object(M.random, "random", return_value=0.0), \
                patch.object(M.random, "randrange", return_value=1):
            g.update_population()
        assert ped.kind == "cards_fan#1"
        assert ped.speed == 0.8 * M.peds_gait(ped.kind)
        assert ped.follower is None, "retyping left a dog ghost behind"
    finally:
        g.pedestrians = old_pedestrians


def test_busch_fans_and_south_city_hoosiers_are_local_flavor():
    assert all(lm[5] != "Downtown & Busch Stadium" for lm in M.LANDMARKS)
    busch = next(lm for lm in M.LANDMARKS if lm[5] == "Busch Stadium")
    bx = (busch[0] + busch[2] // 2) * M.TILE_SIZE
    by = (busch[1] + busch[3] // 2) * M.TILE_SIZE
    with patch.object(M.random, "random", return_value=0.0), \
            patch.object(M.random, "randrange", return_value=2):
        assert M.Game._ped_kind_for(bx, by) == "cards_fan#2"
        # St. Louis Hills puts south siders on the street
        assert M.Game._ped_kind_for(10 * M.TILE_SIZE, 90 * M.TILE_SIZE) == "hoosier#2"
        # ... and a neighbourhood with no bias entry still gets the generic mix
        plain = next(c for c, r in ((34, 30), (12, 5), (2, 50))
                     if M.hood_at(c, r) not in M.Game.HOOD_PED_BIAS)
        row = next(r for c, r in ((34, 30), (12, 5), (2, 50)) if c == plain)
        assert M.Game._ped_kind_for(plain * M.TILE_SIZE, row * M.TILE_SIZE) is None
    # every biased hood names a body the archetype table actually has
    for pairs in M.Game.HOOD_PED_BIAS.values():
        for kind, chance in pairs:
            assert kind in M.peds_ARCHETYPES, kind
            assert 0.0 < chance <= 1.0
    assert M.peds_ARCHETYPES["cards_fan"]["w"] == 0
    assert M.peds_ARCHETYPES["hoosier"]["w"] == 0
    assert "mullet" in M.peds__resolve("hoosier#0")["acc"]


def test_the_rare_black_trans_am_has_its_own_art_and_handling():
    g = game()  # ensures the eager sprite cache exists
    assert M.CIVILIAN_WEIGHTED.count("trans_am") == 1
    assert M.PARKED_VARIANTS_WEIGHTED.count("trans_am") == 1
    assert len(M.PARKED_VARIANTS_WEIGHTED) >= 20
    car = M.Car(300, 300, color=M.CAR_COLORS[0], variant="trans_am")
    assert car.color == M.cars_TRANS_AM_BODY
    assert (car.width, car.height) == (M.VEHICLE_DEFAULT_W, M.VEHICLE_DEFAULT_H)
    assert car.max_speed > M.Car(300, 300, variant="sedan").max_speed
    frames, shadows = M.CAR_SPRITES[("trans_am", M.cars_TRANS_AM_BODY)]
    assert len(frames) == len(shadows) == M.cars_ANGLE_STEPS
    colors = {tuple(frames[0].get_at((x, y))[:3])
              for y in range(frames[0].get_height())
              for x in range(frames[0].get_width())}
    assert M.cars_TRANS_AM_BODY in colors
    assert M.cars_TRANS_AM_GOLD in colors


def test_local_showcase_vehicles_are_unique_stealable_destinations():
    g = M.Game(start_fullscreen=False)
    by_name = {entry[5]: entry for entry in M.LANDMARKS}
    assert len(g.cars) == M.PARKED_CAR_COUNT + M.MOVING_CAR_COUNT
    for variant, venue in M.SHOWCASE_VEHICLES:
        found = [car for car in g.cars if car.variant == variant]
        assert len(found) == 1, f"expected one {variant}, got {len(found)}"
        car = found[0]
        assert car.parked and car.driver is None
        assert not M.is_blocked(car.rect)
        target = M.landmark_dropoff_point(by_name[venue])
        assert math.hypot(car.rect.centerx - target[0],
                          car.rect.centery - target[1]) <= M.TILE_SIZE * 4
        for color in M.CAR_COLORS:
            assert (variant, color) in M.CAR_SPRITES
    assert M.VEHICLE_TUNING['mudfoot']['speed_factor'] > 1.0
    assert M.VEHICLE_TUNING['grocery_cart']['speed_factor'] < 0.8


def test_city_service_and_route_70_are_guaranteed_near_the_player():
    for seed in range(4):
        random.seed(seed)
        g = M.Game(start_fullscreen=False)
        moving = [car for car in g.cars if not car.parked]
        for variant in M.GUARANTEED_AMBIENT_VARIANTS:
            found = [car for car in moving if car.variant == variant]
            assert found, (seed, variant, [car.variant for car in moving])
            assert min(math.dist(car.rect.center, g.player_rect.center)
                       for car in found) <= 430


def test_local_legend_rumors_mark_and_discover_the_rare_rides():
    g = M.Game(start_fullscreen=False)
    assert not g.legend_rumors and not g.legend_discovered
    g.frame = M.LOCAL_LEGEND_HINT_FIRST
    g.update_local_legends()
    assert g.legend_rumors == {'mudfoot'}
    fuzzy = g.local_legend_marker('mudfoot')
    truck = g.local_legend_car('mudfoot')
    assert fuzzy != truck.rect.center

    before = g.score
    teleport(g, truck.rect.center)
    g.update_local_legends()
    assert 'mudfoot' in g.legend_discovered
    assert g.local_legend_marker('mudfoot') == truck.rect.center
    assert g.score == before + 500

    g.camera.snap_to(truck.rect)
    g.screen.fill((1, 2, 3))
    g.draw_local_legend_markers()
    colors = {g.screen.get_at((x, y))[:3]
              for y in range(M.SCREEN_HEIGHT)
              for x in range(M.SCREEN_WIDTH)}
    assert M.LOCAL_LEGENDS['mudfoot']['color'] in colors


def test_local_legend_art_reads_before_the_entry_toast():
    mudfoot = M.cars_big_grid('mudfoot')
    cart = M.cars_big_grid('grocery_cart')
    mud_colors = {pixel for row in mudfoot for pixel in row if pixel is not None}
    cart_colors = {pixel for row in cart for pixel in row if pixel is not None}
    assert {M.cars_MUDFOOT_WHITE, M.cars_MUDFOOT_RED} <= mud_colors
    assert {M.cars_CART_PANEL, M.cars_CART_INK} <= cart_colors
    assert set(M.cars_CART_BAG_COLORS) <= cart_colors


def test_rare_rides_unlock_the_garage_and_start_distinct_mastery_runs():
    for variant in ('mudfoot', 'grocery_cart'):
        g = M.Game(start_fullscreen=False)
        car = g.local_legend_car(variant)
        teleport(g, car.rect.center)
        g.toggle_enter_exit()
        assert g.driving is car
        assert variant in g.legend_garage
        assert g.local_challenge['kind'] == variant
        assert g.local_challenge_marker() is not None
        assert g.local_challenge_hud()[0]


def test_each_local_mastery_route_can_be_completed_and_persists():
    # Checkpoint challenges use the actual controlled vehicle/player position.
    for kind, variant in (('grocery_cart', 'grocery_cart'),
                          ('trash_day', 'garbage_truck')):
        g = M.Game(start_fullscreen=False)
        car = (g.local_legend_car(variant) if variant in M.LOCAL_LEGENDS else
               next(c for c in g.cars if c.variant == variant))
        car.driver = 'player'
        car.parked = False
        g.driving = car
        assert g.start_local_challenge(kind)
        points = list(g.local_challenge['points'])
        for point in points:
            car.rect.center = point
            g.update_local_challenge()
        assert kind in g.legend_mastery and g.local_challenge is None

    g = M.Game(start_fullscreen=False)
    first = g.hill_hydrant_positions()[0]
    teleport(g, first)
    g.update_local_legends()
    assert g.local_challenge['kind'] == 'hill_hydrants'
    for point in g.local_challenge['points'][1:]:
        teleport(g, point)
        g.update_local_challenge()
    assert 'hill_hydrants' in g.legend_mastery


def test_mudfoot_crush_targets_are_physical_and_masterable():
    g = M.Game(start_fullscreen=False)
    truck = g.local_legend_car('mudfoot')
    truck.driver = 'player'
    truck.parked = False
    g.driving = truck
    assert g.start_local_challenge('mudfoot')
    targets = list(g.local_challenge['targets'])
    for target in targets:
        truck.rect.center = target['rect'].center
        truck.velocity = 2.5
        g.update_local_challenge()
    assert 'mudfoot' in g.legend_mastery


def test_expired_temp_tags_are_uncommon_but_visible():
    cars = [M.Car(100 + i * 37, 200 + i * 53, variant='sedan') for i in range(500)]
    tagged = [car for car in cars if car.temp_tag]
    assert 20 <= len(tagged) <= 60
    assert not M.Car(100, 100, variant='garbage_truck').temp_tag
    car = tagged[0]
    car.rect.center = (80, 60)
    car.angle = 0.0
    surf = pygame.Surface((160, 120))
    surf.fill((1, 2, 3))
    cam = M.Camera()
    car.draw(surf, cam)
    assert (244, 240, 218) in {surf.get_at((x, y))[:3]
                              for y in range(120) for x in range(160)}


def test_corrected_landmark_plaques_do_not_repeat_false_claims():
    soulard = M.LANDMARK_PLAQUES['Soulard Farmers Market']
    garden = M.LANDMARK_PLAQUES['Missouri Botanical Garden']
    assert 'older than the country' not in soulard.lower()
    assert 'Louisiana Purchase' in soulard
    assert 'never once closed' not in garden.lower()
    assert 'continuously operating' in garden


def test_route_70_metrobus_is_a_moving_fixed_livery():
    game()
    assert M.CIVILIAN_WEIGHTED.count("metrobus_70") == 1
    assert "metrobus_70" not in M.PARKED_VARIANTS_WEIGHTED
    assert M.VEHICLE_TUNING["metrobus_70"]["w"] == M.VEHICLE_TUNING["bus"]["w"]
    for color in M.CAR_COLORS:
        assert ("metrobus_70", color) in M.CAR_SPRITES
    frames, shadows = M.CAR_SPRITES[("metrobus_70", M.CAR_COLORS[0])]
    assert len(frames) == len(shadows) == M.cars_ANGLE_STEPS
    colors = {tuple(frames[0].get_at((x, y))[:3])
              for y in range(frames[0].get_height())
              for x in range(frames[0].get_width())}
    assert {M.cars_METROBUS_BLUE, M.cars_METROBUS_RED,
            M.cars_METROBUS_ROUTE} <= colors


def test_city_refuse_truck_is_orange_and_spells_city_on_both_sides():
    grid = M.cars_big_grid('garbage_truck')
    colors = {pixel for row in grid for pixel in row if pixel is not None}
    assert M.cars_CITY_SERVICE_ORANGE in colors
    assert M.cars_CITY_SERVICE_LETTERING in colors

    glyphs = {
        'C': ("###", "#..", "#..", "#..", "###"),
        'I': ("###", ".#.", ".#.", ".#.", "###"),
        'T': ("###", ".#.", ".#.", ".#.", ".#."),
        'Y': ("#.#", "#.#", ".#.", ".#.", ".#."),
    }
    for y0 in (3, 14):
        for i, letter in enumerate("CITY"):
            for gy, bits in enumerate(glyphs[letter]):
                for gx, bit in enumerate(bits):
                    if bit == '#':
                        assert grid[y0 + gy][7 + i * 4 + gx] == \
                            M.cars_CITY_SERVICE_LETTERING

    frames = M._scale_frames(M.cars_bake_variant('garbage_truck'),
                             M.SPRITE_SCALE_CAR)
    frame_colors = {tuple(frames[0].get_at((x, y))[:3])
                    for y in range(frames[0].get_height())
                    for x in range(frames[0].get_width())}
    assert {M.cars_CITY_SERVICE_ORANGE,
            M.cars_CITY_SERVICE_LETTERING} <= frame_colors


def test_the_streets_are_actually_populated():
    """The whole point, measured the way a player meets it: boot the game and
    look at the screen. A fresh Game, not the shared one, because this is
    about the spawn distribution and earlier tests scatter entities around."""
    random.seed(4242)
    g = M.Game()
    assert len(g.pedestrians) == M.PEDESTRIAN_COUNT
    assert len(g.cars) == M.PARKED_CAR_COUNT + M.MOVING_CAR_COUNT

    seen = []
    for i in range(400):
        g.player_dir = [1, 0] if (i // 60) % 2 == 0 else [0, 1]
        g.step_sim(M.SIM_DT)
        if i % 40 == 0:
            view = pygame.Rect(g.camera.x, g.camera.y,
                               M.SCREEN_WIDTH, M.SCREEN_HEIGHT)
            seen.append(sum(1 for p in g.pedestrians if view.colliderect(p.rect)))
    average = sum(seen) / len(seen)
    assert average >= 5.0, f"only {average:.1f} pedestrians on screen on average"
    assert min(seen) >= 1, f"the street emptied out completely: {seen}"


def test_gamepad_is_optional_and_never_crashes_without_one():
    """CI and most desktops have no pad plugged in; every read must degrade
    to a safe zero rather than raising."""
    g = game()
    g.pad = None
    assert g.pad_axis(M.PAD_AX_LX) == 0.0
    assert g.pad_trigger(M.PAD_AX_RT) == 0.0
    assert g.pad_button(M.PAD_A) is False
    assert g.pad_hat() == (0, 0)
    # the pad only ever overrides input, never invents it
    assert g.apply_pad_driving(0.4, -0.2) == (0.4, -0.2)
    assert g.apply_pad_walking(0.7, 0.7) == (0.7, 0.7)
    g.open_gamepad()          # no device: must be a quiet no-op
    g.drop_gamepad()
    g.handle_pad_button(M.PAD_START)   # routes to ESC -> pause
    assert g.state == M.STATE_PAUSED
    g.handle_pad_button(M.PAD_START)
    assert g.state == M.STATE_PLAYING


def test_gamepad_buttons_map_onto_real_keys():
    keys = {M.pygame.K_e, M.pygame.K_SPACE, M.pygame.K_m,
            M.pygame.K_ESCAPE, M.pygame.K_q}
    assert set(M.PAD_BUTTON_KEYS.values()) <= keys
    for essential in (M.PAD_A, M.PAD_X, M.PAD_START):
        assert essential in M.PAD_BUTTON_KEYS
    # every mapped button index is a plausible XInput button
    assert all(0 <= b <= 10 for b in M.PAD_BUTTON_KEYS)


def test_gamepad_dpad_navigates_title_creator_and_school_picker():
    g = game()
    g.state = M.STATE_TITLE
    g.title_index = 0
    g.handle_pad_hat((0, -1))
    assert g.title_index == 1 % len(g.title_options())

    g.state = M.STATE_CHARACTER
    g.setup_row = 0
    g.handle_pad_hat((0, -1))
    assert g.setup_row == 1
    g.handle_pad_hat((1, 0))
    assert g.school_open
    before = g.school_cursor
    g.handle_pad_hat((0, -1))
    assert g.school_cursor == min(before + 1, len(g.school_matches()) - 1)
    g.handle_pad_button(M.PAD_RB)
    assert g.school_cursor >= min(before + 1, len(g.school_matches()) - 1)
    g.handle_pad_button(M.PAD_B)
    assert not g.school_open


def test_shop_signs_fit_on_a_shopfront():
    """A 64px tile leaves a 60px sign board; anything wider silently vanishes."""
    for hood, pool in M.HOOD_SIGNS.items():
        for name, _bg, _fg in pool:
            w = M.hud_text_width(name, 1)
            assert w <= M.TILE_SIZE - 4, f"{hood}: {name!r} is {w}px, too wide"


def test_neighbourhoods_pick_their_own_character():
    """The Hill should read Italian, the Loop should read Loop - the whole
    point of the hood table is that blocks are not interchangeable."""
    def signs(col, row):
        # Sample across the whole pool. Feeding n a small stride only moves the
        # low bits, and hood_pick_sign shifts them off - so the old version
        # sampled three signs out of eleven and called it a survey.
        return {M.hood_pick_sign(col, row, i << 7)[0] for i in range(64)}

    hill = signs(30, 62)
    loop = signs(12, 17)
    assert hill & {"DELI", "PIZZERIA", "BAKERY", "VOLPI", "GIOIA'S"}, hill
    assert not (hill & {"FOX", "THE GROVE"}), hill
    assert loop & {"TIVOLI", "PAGEANT", "FITZ'S", "RECORDS", "VINTAGE"}, loop
    assert M.hood_at(30, 62) == 'hill'
    assert M.hood_at(70, 45) == 'downtown'
    for style in ('shotgun', 'gable_brick', 'mansard', 'painted_lady', 'flat_front'):
        assert any(style in pool for pool in M.HOOD_HOUSES.values())
    assert M.HOOD_HOUSES['hill'].count('flat_front') >= 2
    assert M.HOOD_HOUSES['bevo'].count('flat_front') >= 2
    hill_frontages = {M.facade_is_storefront('The Hill', kind) for kind in range(1, 10)}
    assert hill_frontages == {False, True}, "The Hill should be mixed-use, not wall-to-wall shops"


def test_south_city_yards_have_local_micro_landmarks_only():
    """Tiny yard jokes belong behind South City buildings, never downtown."""
    expected = {'chainlink', 'above_pool', 'tub_madonna',
                'backyard_bbq', 'clothesline'}
    seen = set()
    yard_hood = sorted(M.props_YARD_HOODS)[0]
    for r in range(M.MAP_TILES_H):
        for c in range(M.MAP_TILES_W):
            items = M.props_props_for_tile(c, r, M.TILE_PLAZA, False, yard_hood)
            seen.update(name for name, _x, _y in items)
            assert not M.props_props_for_tile(c, r, M.TILE_PLAZA, False, 'downtown')
    assert expected <= seen, seen
    # the eligible list must name hoods that actually exist
    assert M.props_YARD_HOODS <= set(M.HOOD_SIGNS), M.props_YARD_HOODS - set(M.HOOD_SIGNS)
    M.props_bake()
    assert set(M.props_PROPS) == set(M.props__BUILDERS) == set(M.props__ANCHORS)
    for name in expected:
        sprite = M.props_get(name)
        assert sprite.get_width() >= 10 and sprite.get_height() >= 10
        assert sprite.get_bounding_rect().width > 0
        assert M.props_get_shadow(name).get_size() == sprite.get_size()

    # More importantly, each joke must occur in the actual generated south
    # side, not just somewhere in a theoretical coordinate scan. Landmark
    # tiles with hand-made art are skipped because draw_props skips them too.
    actual = set()
    for r, row in enumerate(M.GAME_MAP):
        for c, tile in enumerate(row):
            hood = M.hood_at(c, r)
            if hood not in M.props_YARD_HOODS or tile['type'] != M.TILE_PLAZA:
                continue
            owner = tile['landmark']
            if owner is not None and M.lm_has_art(M.landmark_owner(owner)):
                continue
            kerbside = any(M.tile_type_at(c + dc, r + dr) == M.TILE_ROAD
                           for dc, dr in ((-1, 0), (1, 0), (0, -1), (0, 1)))
            if not kerbside:
                actual.update(name for name, _x, _y in
                              M.props_props_for_tile(c, r, tile['type'], False, hood))
    assert expected <= actual, actual


def test_the_fox_is_in_grand_center_and_nowhere_else():
    """Four neighbourhoods meant one 'arts' pool covering the Loop, the CWE
    and Grand Center at once, so the FOX marquee turned up on Delmar - a mile
    and a half and an entirely different city from where the Fox is."""
    for hood, pool in M.HOOD_SIGNS.items():
        names = {t for (t, _bg, _fg) in pool}
        if "FOX" in names:
            assert hood == 'grand', f"the Fox is hanging in {hood}"
        if "THE GROVE" in names:
            assert hood == 'grove', f"the Grove is hanging in {hood}"
    assert M.hood_at(12, 17) == 'loop'
    assert M.hood_at(56, 34) == 'grand'
    assert M.hood_at(80, 12) == 'oldnorth', "north city is not downtown"
    assert M.hood_at(20, 84) == 'sthills', "St Louis Hills is not The Hill"


def test_every_hood_has_signs_and_houses():
    for hood in set(M.HOOD_SIGNS) | set(M.HOOD_HOUSES):
        assert M.HOOD_SIGNS.get(hood), hood
        assert M.HOOD_HOUSES.get(hood), hood
    # and every region hood_at can return is one of them
    seen = {M.hood_at(c, r)
            for r in range(0, M.MAP_TILES_H, 3)
            for c in range(0, M.MAP_TILES_W, 3)}
    for hood in seen:
        assert hood in M.HOOD_SIGNS, f"hood_at returns {hood!r} with no signs"


def test_generated_building_atlas_supplies_every_neighbourhood():
    game()  # Game.__init__ slices the checked-in alpha atlas.
    assert all(os.path.exists(path) for path in M.BUILDING_ATLAS_PATHS)
    seen = {M.hood_at(c, r)
            for r in range(0, M.MAP_TILES_H, 3)
            for c in range(0, M.MAP_TILES_W, 3)}
    for hood in seen:
        sprites = M.NEIGHBORHOOD_BUILDING_SPRITES.get(hood)
        assert sprites, f"generated atlas has no {hood} building"
        assert len(sprites) >= 2, f"{hood} has no alternate generated building"
        for sprite in sprites:
            assert sprite.get_size() == (M.BUILDING_ATLAS_CELL_SIZE,
                                         M.BUILDING_ATLAS_CELL_SIZE)
            assert sprite.get_flags() & pygame.SRCALPHA
            assert sprite.get_bounding_rect(min_alpha=1).width > 8
            colors = {tuple(sprite.get_at((x, y)))
                      for y in range(sprite.get_height())
                      for x in range(sprite.get_width())}
            assert {color[3] for color in colors} <= {0, 255}, "no antialiased alpha"
            assert len(colors) <= 32, "native facade palette became too high-detail"
    assert M.HOOD_BRICKS['cwe'] != M.HOOD_BRICKS['soulard']


def test_ted_drewes_is_its_own_landmark_you_can_walk_up_to():
    entry = next((e for e in M.LANDMARKS if e[5] == "Ted Drewes"), None)
    assert entry is not None, "Ted Drewes should be on the map"
    assert M.lm_has_art("Ted Drewes"), "and it should have its own baked art"
    lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
    # the lot in front is open and reachable; the stand behind it is solid
    lot_row = ly + lh - 1
    assert any(not M.GAME_MAP[lot_row][c]['collidable'] and M.WALK_REACHABLE[lot_row][c]
               for c in range(lx, lx + lw)), "the lot should be walkable"
    assert any(M.GAME_MAP[ly][c]['collidable'] for c in range(lx, lx + lw)), \
        "the stand itself should be solid"
    assert M.is_reachable(*M.landmark_dropoff_point(entry))


def test_every_landmark_is_fully_reachable_from_the_street():
    """A drop marker inside a sealed courtyard is unplayable. Soulard used to
    be a 3x3 maze of blocks with no legible way in."""
    for entry in M.LANDMARKS:
        lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
        name = entry[5]
        for r in range(ly, ly + lh):
            for c in range(lx, lx + lw):
                if M.GAME_MAP[r][c]['collidable']:
                    continue
                assert M.WALK_REACHABLE[r][c], (
                    f"{name}: open tile ({c},{r}) is walled off from the streets")
        drop = M.landmark_dropoff_point(entry)
        assert M.is_reachable(*drop), f"{name}: drop point is unreachable"


def test_the_arch_lets_you_walk_under_the_span():
    """The Arch is a vertical catenary - in plan only the two leg footings are
    solid. There used to be a wall straight down the middle of the span."""
    entry = next(e for e in M.LANDMARKS if e[5] == "Gateway Arch")
    lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
    solid = [(c - lx, r - ly)
             for r in range(ly, ly + lh) for c in range(lx, lx + lw)
             if M.GAME_MAP[r][c]['collidable']]
    assert solid, "the legs should still be solid"
    cols = {sx for sx, _ in solid}
    assert len(cols) == 2, f"expected two leg columns, got {sorted(cols)}"
    mid = lw // 2
    assert mid not in cols, "the span itself must be walkable"
    # a clear walk straight through between the legs
    row = sorted({sy for _, sy in solid})[0]
    for sx in range(min(cols) + 1, max(cols)):
        assert not M.GAME_MAP[ly + row][lx + sx]['collidable']


def test_the_arch_has_a_transparent_actor_occlusion_pass():
    """The collision was open but actors drew over the steel, visually walking
    on top of the Arch.  The foreground pass must contain only sparse steel."""
    arch = next(e for e in M.LANDMARKS if e[5] == "Gateway Arch")
    art = M.lm__bake_arch_foreground(arch[2] * M.TILE_SIZE,
                                      arch[3] * M.TILE_SIZE)
    opaque = sum(1 for y in range(art.get_height()) for x in range(art.get_width())
                 if art.get_at((x, y)).a)
    assert opaque > 100, "the raised steel pass is empty"
    assert opaque < art.get_width() * art.get_height() // 8, (
        "the foreground pass covers the lawn instead of just the Arch")


def test_market_street_and_downtown_cross_streets_fit_a_car():
    """Downtown landmarks must occupy blocks, not erase the street graph."""
    def clear_at(col, row):
        rect = pygame.Rect(0, 0, M.VEHICLE_DEFAULT_W, M.VEHICLE_DEFAULT_H)
        rect.center = (col * M.TILE_SIZE + M.TILE_SIZE // 2,
                       row * M.TILE_SIZE + M.TILE_SIZE // 2)
        return not M.is_blocked(rect)

    for row in (43, 50):
        assert all(clear_at(col, row) for col in range(52, 82)), (
            f"downtown east/west street {row} is not continuous")
    for col in (57, 63, 68, 73, 79):
        assert all(clear_at(col, row) for row in range(42, 58)), (
            f"downtown cross street {col} is blocked")


def test_the_police_station_is_not_inside_a_landmark():
    """It landed inside Union Station's train shed once that went in, which
    walls in anything that spawns there - a cop, or you after a bust."""
    col, row = M.POLICE_STATION_TILE
    assert M.GAME_MAP[row][col]['landmark'] is None, (
        f"the station is inside {M.GAME_MAP[row][col]['landmark']}")
    for entry in M.LANDMARKS:
        r = pygame.Rect(entry[0] - 1, entry[1] - 1, entry[2] + 2, entry[3] + 2)
        assert not r.collidepoint(col, row), f"station abuts {entry[5]}"


def test_every_landmark_style_has_a_baker_a_ground_and_a_label():
    """These four tables have to agree and nothing enforces it: registering a
    style without a baker crashed 91 of 120 tests with a bare KeyError from
    inside the draw path."""
    for name, style in M.lm_LANDMARK_ART.items():
        assert any(e[5] == name for e in M.LANDMARKS), f"{name} is not a landmark"
        assert style in M.lm__BAKERS, f"{name} -> {style} has no baker"
        assert style in M.lm__GROUND, f"{style} has no ground colour"
        assert style in M.lm__LABEL_AT, f"{style} has no label anchor"
    for name in M.LANDMARK_LAYOUT.values():
        assert name in M._LM_SOLID, f"layout {name} has no collision function"


def test_no_two_landmarks_overlap():
    """Landmarks are stamped in list order, so an overlap silently deletes
    whatever was underneath - Busch Stadium was found sitting on top of the
    Gateway Arch's west leg footing, which quietly removed half the Arch."""
    for i, a in enumerate(M.LANDMARKS):
        ra = pygame.Rect(a[0], a[1], a[2], a[3])
        for b in M.LANDMARKS[i + 1:]:
            rb = pygame.Rect(b[0], b[1], b[2], b[3])
            assert not ra.colliderect(rb), f"{a[5]} overlaps {b[5]}"


def test_ted_drewes_is_south_where_chippewa_is():
    """It sat north of both The Hill and Tower Grove Park, about three miles
    from Chippewa. Nobody in this city drives north to get custard."""
    ted = next(e for e in M.LANDMARKS if e[5] == "Ted Drewes")
    hill = next(e for e in M.LANDMARKS if e[5] == "The Hill")
    grove = next(e for e in M.LANDMARKS if e[5] == "Tower Grove Park")
    assert ted[1] > hill[1] + hill[3], "Ted Drewes must be south of The Hill"
    assert ted[1] > grove[1] + grove[3], "and south of Tower Grove Park"
    assert any(e[5] == "Ted Drewes on Grand" for e in M.LANDMARKS), (
        "there are two of them and people will correct you about it")


def test_the_river_is_a_river_and_you_can_cross_it():
    """It used to be three tiles of dead-straight water at the map edge."""
    widths = []
    for row in range(4, M.MAP_TILES_H - 4):
        if row in M.RIVER_BRIDGES:
            continue
        w = sum(1 for c in range(M.MAP_TILES_W)
                if M.GAME_MAP[row][c]['type'] == M.TILE_WATER)
        widths.append(w)
    assert min(widths) >= 4, f"the river narrows to {min(widths)} tiles"
    assert len(set(widths)) > 1, "a river that never bends is a canal"
    for row in M.RIVER_BRIDGES:
        assert all(not M.GAME_MAP[row][c]['collidable']
                   for c in range(M.river_bank(row), M.MAP_TILES_W)), (
            f"the bridge on row {row} does not reach Illinois")


def test_the_stadium_has_exactly_one_way_in():
    """Solid bowl, open field, a single gate - not a maze and not a plaza."""
    entry = next(e for e in M.LANDMARKS if e[5] == "Busch Stadium")
    lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
    cx, cy = int(round(0.355 * lw)), int(round(0.50 * lh))
    field = (lx + cx, ly + cy)
    assert not M.GAME_MAP[field[1]][field[0]]['collidable'], "field must be open"
    assert M.WALK_REACHABLE[field[1]][field[0]], "field must be reachable"
    # the ring is real: walking due north from the centre hits a wall
    hit_wall = any(M.GAME_MAP[ly + cy - k][lx + cx]['collidable']
                   for k in range(1, cy + 1))
    assert hit_wall, "the bowl should be a hard wall to the north"


# ---------------------------------------------------------------------------
# Death ritual: WASTED always ends the round and always ends under the Arch
# ---------------------------------------------------------------------------

def test_wasted_stops_the_game_instead_of_flashing_over_it():
    """The reported bug: the screen said WASTED and you kept driving.

    Dying is a state now. While it holds, input is ignored, the player does
    not move, and the sim cannot hand control back early.
    """
    g = game()
    car = _drive(g)
    car.rect.center = (40 * M.TILE_SIZE, 40 * M.TILE_SIZE)
    g.player_hp = 1.0
    g.wasted("TEST")
    assert g.state == M.STATE_DEAD
    assert g.driving is None, "you do not stay behind the wheel of a wreck"

    where = g.player_rect.center
    g.player_dir = [1.0, 0.0]              # hold right on the stick
    for _ in range(M.FPS):                 # a full second of trying to play
        g.update()
    assert g.state == M.STATE_DEAD, "the card must hold for its full run"
    assert g.player_rect.center == where, "input reached a dead player"


def test_wasted_always_respawns_under_the_arch():
    g = game()
    teleport(g, (12 * M.TILE_SIZE, 88 * M.TILE_SIZE))   # far south-west
    g.player_hp = 1.0
    g.wasted("TEST")
    for _ in range(M.DEATH_HOLD_STEPS + 2):
        g.update()
    assert g.state == M.STATE_PLAYING, "the card should have cleared by now"

    entry = next(e for e in M.LANDMARKS if e[5] == "Gateway Arch")
    ax = (entry[0] + entry[2] / 2.0) * M.TILE_SIZE
    ay = (entry[1] + entry[3] / 2.0) * M.TILE_SIZE
    d = math.hypot(g.player_rect.centerx - ax, g.player_rect.centery - ay)
    assert d < 8 * M.TILE_SIZE, f"woke up {d / M.TILE_SIZE:.1f} tiles from the Arch"
    assert g.player_hp == M.PLAYER_MAX_HP
    assert not M.is_blocked(g.player_rect), "respawned inside a leg footing"


def test_dead_state_advances_in_the_real_time_loop_policy():
    """The render loop once stepped PLAYING only, permanently freezing this timer."""
    g = game()
    g.busted()
    assert g.should_advance_sim(), "the BUSTED timer must be allowed to tick"
    g.accumulator = 0.0
    for _ in range(M.DEATH_HOLD_STEPS + 2):
        g.step_sim(M.SIM_DT)
    assert g.state == M.STATE_PLAYING
    g.state = M.STATE_PAUSED
    assert not g.should_advance_sim()


def test_busted_card_has_a_deliberate_but_skippable_hold():
    g = game()
    g.busted()
    g.handle_keydown(pygame.K_RETURN)
    assert g.state == M.STATE_DEAD, "the result should remain readable for one beat"
    for _ in range(M.DEATH_SKIP_AFTER_STEPS):
        g.update()
    assert g.death_can_skip()
    g.handle_keydown(pygame.K_RETURN)
    assert g.state == M.STATE_PLAYING, "Enter/A should return control after the short hold"


def test_death_wipes_the_heat_and_the_multiplier():
    g = game()
    g.wanted_level = 4
    g.multiplier = 5
    dispatch_cops(g, 4)
    g.wasted("TEST")
    assert g.wanted_level == 0
    assert g.police == []
    assert g.multiplier == 1
    assert g.check_invariants() is None, g.check_invariants()


def test_a_car_cannot_kill_you_in_three_frames():
    """The 'instantly dead on foot' bug: roadkill damage applied every step a
    car overlapped you, so a cruiser resting on you dealt ~44 HP a frame."""
    g = game()
    teleport(g, (40 * M.TILE_SIZE, 40 * M.TILE_SIZE))
    car = M.Car(*g.player_rect.center)
    car.velocity = 9.0
    g.cars.append(car)
    try:
        survived = 0
        for _ in range(M.FPS):             # one full second pinned under it
            car.rect.center = g.player_rect.center
            car.velocity = 9.0
            g.check_roadkill_risk()
            if g.state == M.STATE_DEAD:
                break
            survived += 1
        assert survived > M.HURT_IMMUNE_STEPS - 4, (
            f"only survived {survived} steps under one car")
    finally:
        if car in g.cars:
            g.cars.remove(car)


# ---------------------------------------------------------------------------
# Police senses: line of sight, searching, and hiding
# ---------------------------------------------------------------------------

def test_a_building_blocks_line_of_sight():
    """The whole hiding mechanic rests on this one function."""
    road = next((col, row)
                for row in range(4, M.MAP_TILES_H - 4)
                for col in range(4, M.MAP_TILES_W - 4)
                if M.tile_type_at(col, row) == M.TILE_ROAD
                and M.tile_type_at(col + 1, row) == M.TILE_ROAD)
    ox = road[0] * M.TILE_SIZE + M.TILE_SIZE // 2
    oy = road[1] * M.TILE_SIZE + M.TILE_SIZE // 2
    assert not M.sight_blocked(ox, oy, ox + M.TILE_SIZE, oy), (
        "two points on the same open road must see each other")

    # find any solid tile with open ground either side of it on the same row
    for row in range(4, M.MAP_TILES_H - 4):
        for col in range(4, M.MAP_TILES_W - 4):
            if not M.GAME_MAP[row][col]['collidable']:
                continue
            if M.GAME_MAP[row][col - 2]['collidable']:
                continue
            if M.GAME_MAP[row][col + 2]['collidable']:
                continue
            ax = (col - 2) * M.TILE_SIZE + M.TILE_SIZE // 2
            bx = (col + 2) * M.TILE_SIZE + M.TILE_SIZE // 2
            y = row * M.TILE_SIZE + M.TILE_SIZE // 2
            assert M.sight_blocked(ax, y, bx, y), (
                f"wall at {col},{row} did not block sight")
            return
    raise AssertionError("no wall with open ground either side anywhere on the map")


def test_a_cop_behind_a_wall_cannot_see_you():
    g = game()
    dispatch_cops(g, 3)
    cop = g.police[0]
    # put the cop on the player, then walk it to the far side of a wall
    cop.rect.center = g.player_rect.center
    cop.angle = 0.0
    assert g.cop_can_see(cop, g.player_rect.center), "point blank must be seen"

    for row in range(4, M.MAP_TILES_H - 4):
        for col in range(4, M.MAP_TILES_W - 4):
            if not M.GAME_MAP[row][col]['collidable']:
                continue
            if M.GAME_MAP[row][col - 2]['collidable'] or M.GAME_MAP[row][col + 2]['collidable']:
                continue
            y = row * M.TILE_SIZE + M.TILE_SIZE // 2
            teleport(g, ((col - 2) * M.TILE_SIZE + M.TILE_SIZE // 2, y))
            cop.rect.center = ((col + 2) * M.TILE_SIZE + M.TILE_SIZE // 2, y)
            cop.angle = math.pi                       # looking straight at you
            cop.sight_range = M.COP_SIGHT
            assert not g.cop_can_see(cop, g.player_rect.center), (
                "a cop saw straight through a building")
            return
    raise AssertionError("no suitable wall found")


def test_losing_sight_puts_the_cops_into_a_search():
    g = game()
    dispatch_cops(g, 2)
    for cop in g.police:
        cop.rect.center = g.player_rect.center
    g.update_police()
    assert g.spotted, "a cop on top of you should have you in sight"

    # shove every cruiser to the other end of the map
    for cop in g.police:
        cop.rect.center = (4 * M.TILE_SIZE, 4 * M.TILE_SIZE)
    teleport(g, (90 * M.TILE_SIZE, 90 * M.TILE_SIZE))
    g.bust_meter = 0
    g.update_police()
    assert not g.spotted, "they should have lost you"
    assert g.searching, "losing you should start a search, not end the chase"
    assert all(c.alert == 'search' for c in g.police)


def test_heat_falls_faster_while_you_are_hidden():
    """Standing still in cover, unseen, is the escape hatch a chase needs."""
    g = game()
    spot = None
    for row in range(4, M.MAP_TILES_H - 4):
        for col in range(4, M.MAP_TILES_W - 4):
            x = col * M.TILE_SIZE + M.TILE_SIZE // 2
            y = row * M.TILE_SIZE + M.TILE_SIZE // 2
            if M.in_cover(x, y) and M.WALK_REACHABLE[row][col]:
                spot = (x, y)
                break
        if spot:
            break
    assert spot, "the city has nowhere to hide at all"

    def shed_time(hidden):
        reset(g)
        teleport(g, spot)
        g.wanted_level = 1
        g.police = []
        g.player_dir = [0, 0]
        for step in range(M.FPS * 60):
            g.hidden = hidden
            g.update_wanted_decay()
            if g.wanted_level == 0:
                return step
        return None

    out_in_the_open = shed_time(False)
    in_a_gangway = shed_time(True)
    assert out_in_the_open and in_a_gangway
    assert in_a_gangway < out_in_the_open * 0.6, (
        f"hiding shed a star in {in_a_gangway} steps vs {out_in_the_open} walking")


def test_hiding_needs_cover_and_stillness():
    g = game()
    # middle of a road tile: no cover, so no hiding however still you stand
    road = None
    for row in range(4, M.MAP_TILES_H - 4):
        for col in range(4, M.MAP_TILES_W - 4):
            if M.tile_type_at(col, row) == M.TILE_ROAD:
                road = (col * M.TILE_SIZE + M.TILE_SIZE // 2,
                        row * M.TILE_SIZE + M.TILE_SIZE // 2)
                break
        if road:
            break
    teleport(g, road)
    g.spotted = False
    g.player_dir = [0, 0]
    for _ in range(M.HIDE_ARM_STEPS * 3):
        g.update_hiding()
    assert not g.hidden, "you cannot hide in the middle of Market Street"


def test_one_star_is_a_beat_cop_on_foot_not_a_cruiser():
    """A cruiser cannot arrest a pedestrian - BUST_CONTACT_STEPS wants 42
    steps of contact and a car doing 10px a step runs you over long before
    that. Measured on the old build: 30 on-foot trials, 23 run over, 0
    arrested. One star is a man on foot now."""
    assert M.COP_COUNT_BY_STAR[1] == 0, "one star should field no cruiser"
    assert M.COP_FOOT_BY_STAR[1] == 1, "one star should field a beat cop"
    g = game()
    g.wanted_level = 1
    for _ in range(M.FPS * 8):
        g.update_police()
        if g.foot_police:
            break
    assert g.foot_police, "no beat cop ever turned up for one star"
    assert not g.police, "one star must not put a cruiser on the street"
    assert M.COP_FOOT_SPEED > M.PLAYER_SPEED, "walking should still lose ground"
    assert M.COP_FOOT_SPEED < M.PLAYER_SPRINT_SPEED, "sprinting must open a gap"
    assert M.COP_FOOT_SPEED < M.COP_SPEED_BY_STAR[2], "but not like a car"


def test_a_beat_cop_walks_toward_you_and_can_hold_you():
    g = game()
    teleport(g, (40 * M.TILE_SIZE, 40 * M.TILE_SIZE))
    g.wanted_level = 1
    for _ in range(M.FPS * 8):
        g.update_police()
        if g.foot_police:
            break
    cop = g.foot_police[0]
    start = math.hypot(cop.rect.centerx - g.player_rect.centerx,
                       cop.rect.centery - g.player_rect.centery)
    for _ in range(M.FPS * 6):
        g.update_police()
        if g.state == M.STATE_DEAD:
            break
    if g.foot_police:
        end = math.hypot(g.foot_police[0].rect.centerx - g.player_rect.centerx,
                         g.foot_police[0].rect.centery - g.player_rect.centery)
        closed = start - end
    else:
        closed = start
    assert closed > 60, f"the beat cop only closed {closed:.0f}px in 6s"


def test_a_beat_cop_never_leaves_the_map():
    g = game()
    g.wanted_level = 1
    for _ in range(M.FPS * 30):
        g.update_police()
        for cop in g.foot_police:
            assert 0 <= cop.rect.centerx <= M.MAP_WIDTH, cop.rect.center
            assert 0 <= cop.rect.centery <= M.MAP_HEIGHT, cop.rect.center
            assert not M.is_blocked(cop.rect), "a beat cop walked into a wall"
        if g.state == M.STATE_DEAD:
            g.finish_death()
            g.wanted_level = 1


def test_cops_are_sent_to_the_crime_not_to_wherever_you_got_to():
    """The measured failure of the first LOS pass: a lone unit spawned 400-900
    px out with no idea which way to look and never once found the player in
    10 trials, which turned one star into an inert countdown."""
    g = game()
    teleport(g, (40 * M.TILE_SIZE, 40 * M.TILE_SIZE))
    g.wanted_bump(1, 'pedestrian')
    scene = g.crime_pos
    assert scene is not None, "the offence did not stamp a crime scene"
    # walk a long way off before anyone is dispatched
    teleport(g, (70 * M.TILE_SIZE, 70 * M.TILE_SIZE))
    aim = g.dispatch_target()
    d = math.hypot(aim[0] - scene[0], aim[1] - scene[1])
    assert d < M.TILE_SIZE, "dispatch ignored the crime scene"
    # and it goes stale, so they stop guarding an address you left ten
    # seconds ago
    g.frame = g.crime_frame + M.CRIME_SCENE_STALE + 1
    aim = g.dispatch_target()
    assert math.hypot(aim[0] - scene[0], aim[1] - scene[1]) > M.TILE_SIZE


def test_losing_five_stars_pays_more_than_losing_one():
    def payout(star):
        g = game()
        g.wanted_level = star
        g.peak_star = star
        g.police = []
        g.heat_timer = 10 ** 6
        g.score = 0
        for _ in range(M.FPS * 90):
            g.update_wanted_decay()
            if g.wanted_level == 0:
                return g.score
        raise AssertionError(f"never shed {star} stars")

    one, five = payout(1), payout(5)
    assert five > one * 4, f"five stars paid {five}, one star paid {one}"


def test_bail_scales_with_how_hot_you_were():
    cheap, dear = M.BAIL_BY_STAR[1], M.BAIL_BY_STAR[5]
    assert dear > cheap * 4
    assert max(M.BAIL_BY_STAR) == M.BAIL_MAX_LOSS == 1000
    g = game()
    g.cash = 10000
    g.peak_star = 5
    g.busted()
    assert g.cash == 10000 - M.BAIL_BY_STAR[5]


def test_hiding_in_a_parked_car_counts():
    """The driving layer's own version of ducking into a gangway."""
    g = game()
    car = _drive(g)
    car.velocity = 0.0
    car.input_throttle = 0.0
    g.spotted = False
    for _ in range(M.HIDE_CAR_STEPS + 4):
        g.update_hiding()
    assert g.hidden, "sitting still in a car with the engine off is hiding"
    car.velocity = 5.0
    g.update_hiding()
    assert not g.hidden, "driving away is not hiding"
    g.driving = None


def test_under_the_arch_is_the_best_place_to_hide():
    g = game()
    spot = g.arch_respawn_point()
    teleport(g, spot)
    assert g.hide_scale() > M.HIDE_DECAY_SCALE, (
        "the map's anchor should be mechanically special")


def test_no_cop_sees_you_from_off_the_edge_of_the_screen():
    """Anything over ~300px lets a cop see you from outside the frame, which
    always reads as cheating however true it is."""
    for star in range(1, M.WANTED_MAX + 1):
        assert M.COP_SIGHT_BY_STAR[star] <= 300, star
    assert M.COP_FOOT_SIGHT <= 300


def test_one_star_is_slower_than_five():
    """Escalation: a beat cop should be losable, the full department not."""
    assert M.COP_SPEED_BY_STAR[2] < M.COP_SPEED_BY_STAR[5]
    assert M.COP_SIGHT_BY_STAR[1] < M.COP_SIGHT_BY_STAR[5]
    assert M.COP_RESPONSE_BY_STAR[1] > M.COP_RESPONSE_BY_STAR[5]
    assert M.WANTED_DECAY_BY_STAR[1] < M.WANTED_DECAY_BY_STAR[5], (
        "a one-star scrape should resolve inside a block")
    assert M.COP_SPEED_BY_STAR[2] > M.PLAYER_SPEED, "a cruiser outruns a jogger"


def test_a_fresh_star_does_not_conjure_a_cop_on_top_of_you():
    g = game()
    g.wanted_level = 2
    g.police = []
    g.cop_dispatch = M.COP_RESPONSE_BY_STAR[2]
    g.update_police()
    assert not g.police, "the call has to go out before a cruiser arrives"


# ---------------------------------------------------------------------------
# St. Louis grub: the power-up layer
# ---------------------------------------------------------------------------

def test_pork_steak_and_provel_are_not_shops():
    """The owner's note: neither is a store. Both are food you eat mid-chase."""
    for pool in M.HOOD_SIGNS.values():
        for text, _bg, _fg in pool:
            assert "PORK" not in text, f"{text} is still hanging over a shopfront"
            assert "PROVEL" not in text, f"{text} is still hanging over a shopfront"
    assert 'pork_steak' in M.GRUB_KINDS
    assert 'provel' in M.GRUB_KINDS


def test_every_grub_sign_still_fits_a_shopfront():
    """Replacing the two bad signs must not have broken the 10-char rule."""
    for pool in M.HOOD_SIGNS.values():
        for text, _bg, _fg in pool:
            assert len(text) <= 10, f"{text!r} is {len(text)} chars"
            assert M.hud_text_width(text, 1) <= 62, text


def test_eating_grub_heals_and_starts_a_clock():
    g = game()
    g.player_hp = 20.0
    g.eat_grub('pork_steak', g.player_rect.center)
    assert g.player_hp > 20.0
    assert g.grub_active('pork_steak')
    assert g.grub_seconds_left('pork_steak') > 0
    # and it expires on its own
    g.frame = g.grub_until['pork_steak'] + 1
    assert not g.grub_active('pork_steak')


def test_toasted_ravioli_is_a_straight_heal_with_no_timer():
    g = game()
    g.player_hp = 10.0
    g.eat_grub('toasted_rav', g.player_rect.center)
    assert g.player_hp == 10.0 + M.GRUB_HEAL
    assert not g.grub_active('toasted_rav'), "t-ravs are not a buff, they are dinner"


def test_a_pork_steak_halves_what_a_car_does_to_you():
    g = game()
    teleport(g, (40 * M.TILE_SIZE, 40 * M.TILE_SIZE))

    def hit_once(with_steak):
        reset(g)
        teleport(g, (40 * M.TILE_SIZE, 40 * M.TILE_SIZE))
        car = M.Car(*g.player_rect.center)
        car.velocity = 7.0
        g.cars.append(car)
        try:
            if with_steak:
                g.grub_until['pork_steak'] = g.frame + 600
            g.player_hp = M.PLAYER_MAX_HP
            g.hurt_cd = 0
            car.rect.center = g.player_rect.center
            g.check_roadkill_risk()
            return M.PLAYER_MAX_HP - g.player_hp
        finally:
            if car in g.cars:
                g.cars.remove(car)

    plain = hit_once(False)
    fed = hit_once(True)
    assert plain > 0, "the control hit did nothing"
    assert fed < plain * 0.75, f"steak took {fed:.1f} vs {plain:.1f} plain"


def test_gooey_butter_speeds_you_up_on_foot_and_gives_it_back():
    g = game()
    assert g.grub_speed_scale() == 1.0
    g.grub_until['gooey_butter'] = g.frame + 600
    assert g.grub_speed_scale() == M.GRUB_SPEED_BONUS
    g.frame = g.grub_until['gooey_butter'] + 1
    assert g.grub_speed_scale() == 1.0


def test_gooey_butter_does_not_ratchet_a_car_faster_every_step():
    """max_speed is written every step, so a multiplier applied to the live
    value instead of the baseline would compound into orbit."""
    g = game()
    car = _drive(g)
    base = car.base_max_speed
    g.grub_until['gooey_butter'] = g.frame + 600
    for _ in range(200):
        g.apply_grub_to_car()
    assert abs(car.max_speed - base * M.GRUB_SPEED_BONUS) < 0.01, car.max_speed
    g.grub_until = {}
    g.apply_grub_to_car()
    assert abs(car.max_speed - base) < 0.01, "the ceiling must come back down"
    g.driving = None


def test_provel_makes_the_cops_lose_their_grip():
    g = game()
    dispatch_cops(g, 3)
    g.update_police()
    fast = max(c.max_speed for c in g.police)
    g.grub_until['provel'] = g.frame + 600
    g.bust_meter = 0
    g.update_police()
    slow = max(c.max_speed for c in g.police)
    assert slow < fast, f"cops still doing {slow} on a wheel of provel"


def test_a_concrete_makes_you_hit_harder():
    g = game()
    assert g.grub_ram_scale() == 1.0
    g.grub_until['concrete'] = g.frame + 600
    assert g.grub_ram_scale() == M.GRUB_RAM_BONUS
    assert g.grub_self_ram() < 1.0


def test_a_tallboy_doubles_what_chaos_is_worth():
    g = game()
    g.score = 0
    g.mult_prog = 0.0
    g.add_score(20, g.player_rect.center)
    plain = g.mult_prog
    g.mult_prog = 0.0
    g.grub_until['tallboy'] = g.frame + 600
    g.add_score(20, g.player_rect.center)
    assert g.mult_prog > plain * 1.5, f"{g.mult_prog} vs {plain}"


def test_grub_spawns_somewhere_you_can_actually_walk():
    g = game()
    for item in g.grub_pickups:
        col = int(item['x']) // M.TILE_SIZE
        row = int(item['y']) // M.TILE_SIZE
        assert M.WALK_REACHABLE[row][col], (
            f"{item['kind']} spawned in a sealed pocket at {col},{row}")
        assert item['kind'] in M.GRUB_KINDS


def test_walking_over_grub_takes_it_and_it_comes_back():
    g = game()
    item = g.grub_pickups[0]
    item['taken'] = 0
    item['kind'] = 'toasted_rav'
    teleport(g, (item['x'], item['y']))
    g.player_hp = 20.0
    g.update_grub()
    assert item['taken'], "walked straight over it without eating it"
    healed = g.player_hp
    g.frame = item['taken'] + M.GRUB_RESPAWN + 1
    g.update_grub()
    assert not item['taken'], "grub never came back"
    assert healed > 20.0


# ---------------------------------------------------------------------------
# The bank under the Arch
# ---------------------------------------------------------------------------

def test_cash_banks_under_the_arch_and_nowhere_else():
    g = game()
    teleport(g, (40 * M.TILE_SIZE, 40 * M.TILE_SIZE))
    g.cash = 900
    g.banked = 0
    g.update_bank()
    assert g.cash == 900, "banked from the middle of the map"

    teleport(g, g.arch_center())
    g.update_bank()
    assert g.banked == 900, "the Arch did not take the deposit"
    assert g.cash == 0


def test_fifty_thousand_banked_unlocks_a_real_latched_arch_job():
    g = game()
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        try:
            os.chdir(td)
            g.banked = M.ARCH_JOB_TARGET - 100
            g.cash = 100
            teleport(g, (40 * M.TILE_SIZE, 40 * M.TILE_SIZE))
            g.update_bank()
            assert not g.arch_job_unlocked, "money in your pocket is not banked"
            teleport(g, g.arch_center())
            g.update_bank()
            assert g.arch_job_unlocked
            assert g.arch_job_phase == M.ARCH_READY
            assert g.banked == M.ARCH_JOB_TARGET, "the threshold is not a buy-in"
            assert g.job is None, "an unaccepted courier offer should yield to the finale"
            g.banked = 1
            assert g.arch_job_unlocked, "bail or a respray must never re-lock the finale"
        finally:
            os.chdir(old_cwd)


def test_an_accepted_delivery_finishes_before_the_arch_job_takes_over():
    rng_state = random.getstate()
    g = game()
    try:
        job = M.Job.generate()
        job.collect()
        g.job = job
        g.arch_job_unlocked = True
        g.arch_job_phase = M.ARCH_READY
        g.arch_job_offer_after = 0
        teleport(g, job.drop_pos)
        before = g.jobs_done
        g.update_arch_job()
        assert g.arch_job_phase == M.ARCH_READY
        g.update_job()
        assert g.jobs_done == before + 1
        assert g.job is None
    finally:
        random.setstate(rng_state)


def test_arch_job_runs_city_museum_to_arch_to_hill_and_back_to_jobs():
    rng_state = random.getstate()
    g = game()
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        try:
            os.chdir(td)
            g.arch_job_unlocked = True
            g.arch_job_phase = M.ARCH_READY
            g.arch_job_offer_after = 0
            g.job = None
            g.wanted_level = 0

            teleport(g, g.arch_center())
            g.update_arch_job()
            assert g.arch_job_phase == M.ARCH_CUTTER

            teleport(g, g.landmark_job_point("City Museum"))
            g.update_arch_job()
            assert g.arch_job_phase == M.ARCH_RETURN

            teleport(g, g.arch_center())
            g.update_arch_job()
            assert g.arch_job_phase == M.ARCH_RETURN, "the cutter needs a getaway car"

            car = _drive(g)
            car.rect.center = tuple(map(int, g.arch_center()))
            g.update_arch_job()
            assert g.arch_job_phase == M.ARCH_ESCAPE
            assert g.wanted_level == M.WANTED_MAX
            assert g.arch_job_timer == M.ARCH_JOB_SECONDS * M.FPS

            car.rect.center = tuple(map(int, g.landmark_job_point("The Hill")))
            g.update_arch_job()
            assert g.arch_job_phase == M.ARCH_LAY_LOW
            assert not g.arch_job_completed, "arrival alone is not enough while hot"
            g.wanted_level = 0
            g.police = []
            g.foot_police = []
            score = g.score
            g.update_arch_job()
            assert g.arch_job_completed
            assert g.arch_job_phase == M.ARCH_COMPLETE
            assert g.score == score + M.ARCH_JOB_SCORE
            assert g.arch_victory_timer == M.ARCH_VICTORY_HOLD_STEPS
            assert g.job is None, "a courier offer stepped on the finale card"
            g.draw()
            # The card freezes the city, then ordinary St. Louis keeps going.
            for _ in range(M.ARCH_VICTORY_HOLD_STEPS):
                g.update_arch_victory()
            assert g.arch_victory_timer == 0 and g.job is not None
            g.update_arch_job()
            assert g.score == score + M.ARCH_JOB_SCORE, "completion reward fired twice"
        finally:
            os.chdir(old_cwd)
            random.setstate(rng_state)


def test_arch_job_timeout_death_and_body_shop_cannot_cheese_the_chase():
    rng_state = random.getstate()
    g = game()
    car = _drive(g)
    car.rect.center = tuple(map(int, g.body_shops[0]))
    g.arch_job_unlocked = True
    g.arch_job_phase = M.ARCH_ESCAPE
    g.arch_job_timer = 40
    g.wanted_level = 5
    g.cash = 1000
    g.update_body_shop()
    assert g.cash == 1000 and g.wanted_level == 5

    g.arch_job_timer = 1
    g.update_arch_job()
    assert g.arch_job_phase == M.ARCH_READY
    assert g.arch_job_unlocked and not g.arch_job_completed
    assert g.wanted_level == 5, "timeout should not magically clear the cops"

    g.arch_job_phase = M.ARCH_LAY_LOW
    g.arch_job_timer = 30 * M.FPS
    car.rect.center = tuple(map(int, g.landmark_job_point("The Hill")))
    g.peak_star = 5
    g.busted()
    assert g.state == M.STATE_DEAD
    assert g.arch_job_phase == M.ARCH_READY
    g.update_arch_job()  # wanted was reset by the bust; this must not count as hiding
    assert not g.arch_job_completed
    random.setstate(rng_state)


def test_arch_job_objective_renders_in_every_phase():
    rng_state = random.getstate()
    g = game()
    g.arch_job_unlocked = True
    g.job = None
    for phase in (M.ARCH_READY, M.ARCH_CUTTER, M.ARCH_RETURN,
                  M.ARCH_ESCAPE, M.ARCH_LAY_LOW):
        g.state = M.STATE_PLAYING
        g.arch_job_phase = phase
        g.arch_job_timer = 45 * M.FPS
        if phase == M.ARCH_LAY_LOW:
            teleport(g, (70 * M.TILE_SIZE, 45 * M.TILE_SIZE))
        assert g.arch_job_objective_text() is not None
        g.draw_job_marker()
        g.draw_radar(M.SCREEN_WIDTH - M.RADAR_SIZE - 10, 76)
        g.draw_objective()
        g.draw_map_screen()
    assert not g.draw_arch_cargo(), "cargo appeared without a getaway car"
    _drive(g)
    g.arch_job_phase = M.ARCH_ESCAPE
    assert g.draw_arch_cargo(), "the stolen Arch slice is invisible on the getaway car"
    random.setstate(rng_state)


def test_getting_killed_drops_your_roll_where_you_died():
    g = game()
    teleport(g, (40 * M.TILE_SIZE, 40 * M.TILE_SIZE))
    g.cash = 1200
    g.banked = 4000
    where = g.player_rect.center
    g.wasted("TEST")
    assert g.cash == 0, "you do not keep the roll"
    assert g.banked == 4000, "banked money is safe"
    assert len(g.dropped) == 1
    roll = g.dropped[0]
    assert roll['amount'] == 1200
    assert math.hypot(roll['x'] - where[0], roll['y'] - where[1]) < 4

    # and you can go back for it
    g.finish_death()
    teleport(g, (roll['x'], roll['y']))
    g.update_dropped_cash()
    assert g.cash == 1200, "could not pick the roll back up"
    assert not g.dropped


def test_a_dropped_roll_does_not_wait_forever():
    g = game()
    g.cash = 500
    g.wasted("TEST")
    g.finish_death()
    assert g.dropped
    g.frame += M.DROPPED_CASH_LIFE + 1
    g.update_dropped_cash()
    assert not g.dropped, "the roll should have gone cold"


def test_being_arrested_keeps_your_roll_but_takes_bail():
    """The whole difference between the two deaths: they hand your effects
    back at the desk, so surrendering while holding a big roll is a real
    decision rather than a strictly worse outcome."""
    g = game()
    g.cash = 3000
    g.banked = 0
    g.peak_star = 3
    g.busted()
    assert not g.dropped, "an arrest does not scatter your money on the road"
    assert g.cash == 3000 - M.BAIL_BY_STAR[3]


def test_bail_reaches_into_the_bank_when_your_pockets_are_light():
    g = game()
    g.cash = 40
    g.banked = 5000
    g.peak_star = 5
    g.busted()
    assert g.cash == 0
    assert g.banked == 5000 - (M.BAIL_BY_STAR[5] - 40)


def test_a_nudge_in_a_parking_bay_is_not_a_police_matter():
    """Measured on the old build: a car-on-pedestrian contact raised a wanted
    star at *any* closing speed, 0.0 included, so a pilot that yielded,
    braked and swerved still spent a quarter of its session at 3+ stars."""
    g = game()
    car = _drive(g)
    car.angle = 0.0
    for speed, should_bump in ((0.0, False), (1.0, False), (4.0, True)):
        g.wanted_level = 0
        g.infraction_at = {}
        ped = next(p for p in g.pedestrians if p.down_timer <= 0)
        ped.rect.center = (car.rect.centerx + 18, car.rect.centery)
        ped.bump_cooldown = 0
        car.velocity = speed
        g.handle_collisions()
        if should_bump:
            assert g.wanted_level > 0, f"a {speed} hit should be an offence"
        else:
            assert g.wanted_level == 0, f"a {speed} nudge is not a crime"
    g.driving = None


# ---------------------------------------------------------------------------
# Audio: synthesised at boot, and silent on a machine with no mixer
# ---------------------------------------------------------------------------

def test_the_audio_bank_synthesises_without_numpy():
    """The whole point of the approach: array('h') + Sound(buffer=...), never
    pygame.sndarray, which hard-imports numpy - a 15MB binary dependency on a
    project whose requirements.txt is one line."""
    import array
    samples = [math.sin(i * 0.05) for i in range(400)]
    buf = M.snd__buf(samples, 0.8)
    assert isinstance(buf, array.array)
    assert buf.typecode == 'h'
    assert len(buf) == len(samples) * 2, "stereo interleave"
    assert max(buf) > 0 and min(buf) < 0, "the waveform is not silent"
    assert max(buf) <= 32767 and min(buf) >= -32768, "clipped to 16 bit"


def test_every_engine_loop_is_a_whole_number_of_cycles():
    """Sound.play(loops=-1) repeats the whole buffer, so a loop that is not a
    whole number of cycles clicks once per lap."""
    for period in M.snd_ENGINE_PERIODS:
        n = period * M.snd_ENGINE_CYCLES
        assert n % period == 0
        wave = M.snd__make_engine(period)
        assert len(wave) == n
        assert max(wave) > 0.05, "an engine note that makes no sound"


def test_engine_buckets_climb_with_speed_and_stay_in_range():
    n = len(M.snd_ENGINE_PERIODS)
    assert M.snd_engine_bucket(0.0) == 0
    assert M.snd_engine_bucket(1.0) == n - 1
    assert M.snd_engine_bucket(2.5) == n - 1, "clamped above"
    assert M.snd_engine_bucket(-1.0) == 0, "clamped below"
    prev = -1
    for k in range(0, 11):
        b = M.snd_engine_bucket(k / 10.0)
        assert b >= prev, "buckets must not go down as you speed up"
        prev = b
    # and higher bucket == shorter period == higher note
    assert M.snd_ENGINE_PERIODS[-1] < M.snd_ENGINE_PERIODS[0]


def test_panning_is_equal_power_and_falls_off_with_distance():
    cam = (1000, 1000)
    near = M.snd_pan_volume((1000, 1000), cam, 1.0)
    far = M.snd_pan_volume((1000, 1560), cam, 1.0)
    assert sum(near) > sum(far) > 0, "distance should quieten it"
    assert M.snd_pan_volume((1000, 4000), cam, 1.0) == (0.0, 0.0)
    left_side = M.snd_pan_volume((700, 1000), cam, 1.0)
    right_side = M.snd_pan_volume((1300, 1000), cam, 1.0)
    assert left_side[0] > left_side[1], "a sound to the west is louder left"
    assert right_side[1] > right_side[0], "and to the east, louder right"


def test_sound_calls_are_harmless_with_no_mixer():
    """CI runs on the dummy audio driver. Nothing in the game may care."""
    g = game()
    assert not M.snd__enabled, "the headless test game must be silent"
    g.play_sound('boom', (100, 100))
    g.play_impact((100, 100), 9.0)
    g.update_audio()
    M.snd_duck(10)
    M.snd_loop(M.snd_CH_ENGINE_A, 'engine0', 0.5)
    M.snd_stop(M.snd_CH_ENGINE_A)
    assert g.check_invariants() is None


def test_packaged_soundtrack_is_a_valid_standard_midi():
    assert os.path.isfile(M.GAME_MUSIC_SOURCE_PATH)
    with open(M.GAME_MUSIC_SOURCE_PATH, 'rb') as fh:
        data = fh.read()
    assert data[:4] == b'MThd'
    assert int.from_bytes(data[4:8], 'big') == 6
    assert b'MTrk' in data
    assert len(data) > 1024
    assert 0.0 < M.GAME_MUSIC_VOLUME < 1.0


def test_rendered_chiptune_is_long_streamable_pcm():
    assert os.path.isfile(M.GAME_MUSIC_PATH)
    with wave.open(M.GAME_MUSIC_PATH, 'rb') as soundtrack:
        assert soundtrack.getframerate() == M.snd_SR
        assert soundtrack.getnchannels() == 1
        assert soundtrack.getsampwidth() == 2
        assert soundtrack.getnframes() / soundtrack.getframerate() >= 180.0


def test_rate_limiting_stops_a_wall_scrape_becoming_a_drone():
    M.snd__last_played.clear()
    M.snd_set_frame(0)
    first = M.snd_play('impact0', gap=8)
    M.snd_set_frame(3)
    M.snd_play('impact0', gap=8)
    # with no mixer both return None; what matters is the bookkeeping
    assert M.snd__last_played.get('impact0') == 0, (
        "a rate-limited key must not re-arm inside its gap")
    M.snd_set_frame(20)
    M.snd_play('impact0', gap=8)
    assert M.snd__last_played.get('impact0') == 20
    M.snd__last_played.clear()


# ---------------------------------------------------------------------------
# Handling: grip, the handbrake, and not burying the car in a wall
# ---------------------------------------------------------------------------

def test_a_car_carries_momentum_sideways_through_a_turn():
    """The old model moved the car exactly along its heading every step - no
    slip angle, no lateral momentum. That is a tank, not a car."""
    g = game()
    car = _drive(g)
    car.rect.center = _open_road_point()
    car.angle = 0.0
    car.velocity = 8.0
    car.vlat = 0.0
    car._prev_angle = 0.0
    car.input_steer = 1.0
    car.input_throttle = 1.0
    for _ in range(8):
        car.physics_step()
    assert car.slip > 0.05, "turning hard at speed produced no slide at all"
    g.driving = None


def test_the_handbrake_lets_the_back_come_round():
    def slide(handbrake):
        g = game()
        car = _drive(g)
        car.rect.center = _open_road_point()
        car.angle = 0.0
        car._prev_angle = 0.0
        car.velocity = 9.0
        car.vlat = 0.0
        car.input_steer = 1.0
        car.input_throttle = 1.0
        car.input_handbrake = handbrake
        peak = 0.0
        for _ in range(14):
            car.physics_step()
            peak = max(peak, car.slip)
        g.driving = None
        return peak

    assert slide(True) > slide(False) * 1.15, (
        "the handbrake has to actually loosen the back end")
    assert M.LAT_RETAIN_HANDBRAKE > M.LAT_RETAIN


def test_grip_pulls_the_car_back_into_line():
    """A slide has to end on its own, or the car is a hovercraft."""
    g = game()
    car = _drive(g)
    car.rect.center = _open_road_point()
    car.angle = 0.0
    car._prev_angle = 0.0
    car.velocity = 6.0
    car.vlat = 5.0
    car.input_steer = 0.0
    car.input_throttle = 0.0
    car.input_handbrake = False
    for _ in range(45):
        car.physics_step()
    assert car.vlat == 0.0, f"still sliding sideways at {car.vlat}"
    g.driving = None


def test_traffic_does_not_get_a_handbrake():
    """input_handbrake is only honoured for the player; ambient traffic
    sliding around corners would look like the whole city is drunk."""
    g = game()
    car = next(c for c in g.cars if c.driver is None)
    car.driver = None
    car.input_handbrake = True
    car.angle = 0.0
    car._prev_angle = 0.0
    car.velocity = 6.0
    car.vlat = 4.0
    car.input_steer = 0.0
    car.input_throttle = 0.0
    before = car.vlat
    car.physics_step()
    assert car.vlat < before * M.LAT_RETAIN_HANDBRAKE, (
        "ambient traffic got the handbrake's loose back end")


def test_streamed_traffic_starts_on_a_lane_not_the_center_stripe():
    g = game()
    row = min(M.ROAD_LINES)
    col = next(c for c in range(6, M.MAP_TILES_W - 6)
               if c not in M.ROAD_LINES and M.tile_type_at(c, row) == M.TILE_ROAD)
    center = (col * M.TILE_SIZE + M.TILE_SIZE // 2,
              row * M.TILE_SIZE + M.TILE_SIZE // 2)
    car = M.Car(*center, variant='sedan')
    car.angle = 0.0
    M.traffic_init_car(car)
    assert car.rect.centery == center[1]
    assert M.traffic_snap_to_lane(car)
    lane = M.traffic__lane_clamped(car._traffic_ai['dir'],
                                   car._traffic_ai['line'], col, row)
    assert abs(car.rect.centery - lane) <= 0.5
    assert abs(car.angle) < 1e-9
    assert car.steer_angle == 0.0


def test_a_wedged_car_can_always_get_out():
    """A head-on sets velocity *= -0.18, so a car that ends a step actually
    inside geometry can never drive or reverse out - both just bounce. 265 of
    these were measured in one ten-minute session."""
    g = game()
    wall = None
    for row in range(4, M.MAP_TILES_H - 4):
        for col in range(4, M.MAP_TILES_W - 4):
            if M.GAME_MAP[row][col]['collidable']:
                wall = (col, row)
                break
        if wall:
            break
    car = M.Car(wall[0] * M.TILE_SIZE + M.TILE_SIZE // 2,
                wall[1] * M.TILE_SIZE + M.TILE_SIZE // 2)
    assert M.is_blocked(car.rect), "the test needs the car actually buried"
    car.unwedge()
    assert not M.is_blocked(car.rect), "the car is still stuck in the wall"


def test_which_car_you_steal_actually_matters():
    """Every vehicle used to top out at exactly 9.5 under the player - the
    bus, the refuse truck and the Vespa were the same car."""
    tops = {}
    for variant in ('sedan', 'bus', 'garbage_truck', 'vespa', 'box_truck'):
        tops[variant] = M.Car(2000, 2000, variant=variant).base_max_speed
    assert tops['vespa'] > tops['sedan'] > tops['box_truck'] > tops['bus']
    assert tops['bus'] > tops['garbage_truck']
    assert tops['vespa'] / tops['garbage_truck'] > 1.4, tops


# ---------------------------------------------------------------------------
# St. Louis, specifically
# ---------------------------------------------------------------------------

def test_somebody_asks_where_you_went_to_high_school():
    """The question. You will be asked it by strangers within ninety seconds
    of arriving, and the answer places you more precisely than an address."""
    g = game()
    g.wanted_level = 0
    g.hs_cooldown = 0
    asked = 0
    for _ in range(400):
        ped = g.pedestrians[0]
        ped.mood = 'calm'
        ped.down_timer = 0
        ped.rect.center = g.player_rect.center
        g.hs_cooldown = 0
        before = g.hs_asked
        g.barge_pedestrians()
        if g.hs_asked > before:
            asked += 1
        if asked >= 3:
            break
    assert asked >= 3, "nobody ever asked"
    assert g.hs_asked >= 3
    # every answer and reply has to be renderable in the bitmap font
    for text in M.HS_ANSWERS + M.HS_REPLIES + (M.HS_QUESTION,):
        assert M.hud_text_width(text, 1) > 0, text


def test_ambient_stl_conversations_are_tagged_and_pause_during_chases():
    g = game()
    ped, partner = g.pedestrians[:2]
    ped.rect.center = (20 * M.TILE_SIZE, 84 * M.TILE_SIZE)
    partner.rect.center = (ped.rect.centerx + 20, ped.rect.centery)
    g.chatter_cooldown = 0
    assert g.maybe_start_stl_conversation(ped, partner, forced=True)
    assert len(g.speech_bubbles) >= 2
    assert g.speech_bubbles[0]['speaker'] is ped
    assert g.speech_bubbles[1]['speaker'] is partner
    assert ped.mood == partner.mood == 'gawk'

    g.chatter_cooldown = 0
    g.wanted_level = 1
    before = len(g.speech_bubbles)
    assert not g.maybe_start_stl_conversation(ped, partner, forced=True)
    assert len(g.speech_bubbles) == before


def test_character_creator_has_the_whole_local_school_question():
    names = [name for name, _group in M.STL_HIGH_SCHOOLS]
    assert len(names) >= 150, "the selector is a sample, not the promised metro-area list"
    assert len(names) == len(set(names)), "duplicate high-school choice"
    for expected in ("Vashon High School", "Kirkwood High School",
                     "Christian Brothers College High School",
                     "St. Louis University High School", "MICDS",
                     "Francis Howell North High School", "Seckman Sr. High School",
                     "Washington High School", "Edwardsville High School",
                     "East St. Louis Senior High School", "Waterloo High School",
                     "Gibault Catholic"):
        assert expected in names
    assert {group for _name, group in M.STL_HIGH_SCHOOLS} >= {
        "CITY PUBLIC", "COUNTY PUBLIC", "CHARTER", "TECHNICAL", "PRIVATE"
    }

    g = game()
    assert [row[0] for row in g.school_matches("sluh")] == [
        "St. Louis University High School"
    ]
    assert [row[0] for row in g.school_matches("cbc")] == [
        "Christian Brothers College High School"
    ]
    assert any(row[0] == "Parkway West High School" for row in g.school_matches("park west"))
    assert [row[0] for row in g.school_matches("fzw")] == ["Ft. Zumwalt West High School"]
    assert [row[0] for row in g.school_matches("estl")] == [
        "East St. Louis Senior High School"
    ]


def test_school_combobox_types_filters_and_selects():
    g = game()
    g.state = M.STATE_CHARACTER
    g.setup_row = 1
    g.handle_character_key(pygame.K_RETURN)
    assert g.school_open
    for ch in "sluh":
        g.handle_character_key(pygame.key.key_code(ch), ch)
    assert g.school_query == "SLUH", "W/S/E must type, not navigate, while filtering"
    rows = g.school_matches()
    assert len(rows) == 1
    g.handle_character_key(pygame.K_RETURN)
    assert not g.school_open
    assert g.character_school == "St. Louis University High School"


def test_character_profile_arch_progress_and_arsenal_round_trip_in_v6_save():
    g = game()
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        try:
            os.chdir(td)
            g.character_look = len(M.CHARACTER_LOOKS) - 1
            g.character_school = "Vashon High School"
            g.job_types_done = {'courier', 'hot'}
            g.legend_rumors = {'mudfoot', 'grocery_cart'}
            g.legend_discovered = {'mudfoot'}
            g.legend_garage = {'mudfoot'}
            g.legend_mastery = {'mudfoot', 'hill_hydrants'}
            g.arch_job_unlocked = True
            g.arch_job_completed = False
            g.arch_job_phase = M.ARCH_ESCAPE  # active attempts deliberately do not resume
            g.owned_weapons.update(('bat', 'shotgun', M.throwable_logic.FIRE_BOTTLE))
            g.weapon_ammo['shotgun'] = 7
            g.weapon_ammo[M.throwable_logic.FIRE_BOTTLE] = 2
            g.throwable_system = M.throwable_logic.ThrowableSystem({
                M.throwable_logic.FIRE_BOTTLE: 2,
            })
            g.side_missions_done = 4
            g.side_missions_failed = 1
            g.side_mission_serial = 5
            g.weapon = 'shotgun'
            g.ammo = 7
            g.save_game()
            assert "CONTINUE" in g.title_options()
            with open("savegame.json", "r") as f:
                raw = json.load(f)
            assert raw['version'] == 6
            assert raw['character']['high_school'] == "Vashon High School"
            assert raw['job_types_done'] == ['courier', 'hot']
            assert raw['legend_rumors'] == ['grocery_cart', 'mudfoot']
            assert raw['legend_discovered'] == ['mudfoot']
            assert raw['legend_garage'] == ['mudfoot']
            assert raw['legend_mastery'] == ['hill_hydrants', 'mudfoot']
            g.character_look = 0
            g.character_school = "NOT FROM AROUND HERE"
            g.job_types_done = set()
            g.legend_rumors = set()
            g.legend_discovered = set()
            g.legend_garage = set()
            g.legend_mastery = set()
            g.arch_job_unlocked = False
            g.arch_job_phase = M.ARCH_LOCKED
            g.owned_weapons = {'fists'}
            g.weapon = 'fists'
            g.ammo = 0
            assert g.load_game()
            assert g.character_look == len(M.CHARACTER_LOOKS) - 1
            assert g.character_school == "Vashon High School"
            assert g.job_types_done == {'courier', 'hot'}
            assert g.legend_rumors == {'mudfoot', 'grocery_cart'}
            assert g.legend_discovered == {'mudfoot'}
            assert g.legend_garage == {'mudfoot'}
            assert g.legend_mastery == {'mudfoot', 'hill_hydrants'}
            assert g.arch_job_unlocked and not g.arch_job_completed
            assert g.arch_job_phase == M.ARCH_READY
            assert g.job is None
            assert g.weapon == 'shotgun' and g.ammo == 7
            assert 'bat' in g.owned_weapons
            assert g.throwable_system.inventory(M.throwable_logic.FIRE_BOTTLE) == 2
            assert (g.side_missions_done, g.side_missions_failed,
                    g.side_mission_serial) == (4, 1, 5)
        finally:
            os.chdir(old_cwd)


def test_legacy_save_is_rejected_without_mutating_the_live_game():
    g = game()
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        try:
            os.chdir(td)
            with open("savegame.json", "w") as f:
                json.dump({
                    'version': 2,
                    'player': {'x': 1000, 'y': 1000},
                    'banked': M.ARCH_JOB_TARGET,
                    'cash': 0,
                }, f)
            before = (g.player_rect.center, g.cash, g.banked,
                      g.arch_job_unlocked, g.arch_job_phase)
            assert "CONTINUE" not in g.title_options()
            assert not g.load_game()
            assert (g.player_rect.center, g.cash, g.banked,
                    g.arch_job_unlocked, g.arch_job_phase) == before
        finally:
            os.chdir(old_cwd)


def test_missing_and_malformed_saves_are_safe_on_the_title_screen():
    g = game()
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        try:
            os.chdir(td)
            assert g.title_options() == ("NEW GAME", "QUIT")
            before = (g.player_rect.center, g.cash, g.banked, g.state)
            assert not g.load_game()
            assert (g.player_rect.center, g.cash, g.banked, g.state) == before

            malformed = (
                "{not json",
                "[]",
                json.dumps({'version': M.SAVE_VERSION, 'player': None}),
                json.dumps({
                    'version': M.SAVE_VERSION,
                    'player': {'x': 100, 'y': 100},
                    'score': 0, 'cash': "500", 'banked': 0,
                    'wanted_level': 0, 'discovered': [], 'jobs_done': 0,
                    'jobs_failed': 0, 'side_missions_done': 0,
                    'side_missions_failed': 0, 'side_mission_serial': 0,
                    'best_streak': 0, 'job_types_done': [], 'character': {},
                    'arch_job': {},
                    'weapons': {'selected': 'fists', 'owned': ['fists'],
                                'ammo': {}},
                }),
            )
            for contents in malformed:
                with open("savegame.json", "w") as f:
                    f.write(contents)
                assert "CONTINUE" not in g.title_options()
                assert not g.load_game()
                assert (g.player_rect.center, g.cash, g.banked, g.state) == before
        finally:
            os.chdir(old_cwd)


def test_title_character_and_picker_render_without_assets():
    g = game()
    original_state = g.state
    try:
        g.state = M.STATE_TITLE
        g.draw()
        assert g.screen.get_at((320, 40)) != (0, 0, 0, 255)
        g.state = M.STATE_CHARACTER
        g.character_look = 3
        g.character_school = "Webster Groves High School"
        g.draw()
        g.school_open = True
        g.school_query = "PARKWAY"
        g.school_cursor = 2
        g.draw()
        assert len(g.school_matches()) == 4
    finally:
        g.school_open = False
        g.school_query = ""
        g.state = original_state


def test_every_character_look_is_a_distinct_baked_sprite():
    M.bake_ped_sprites()
    pixels = []
    for key in M.PEDS_PLAYER_KEYS:
        sprite, _shadow = M.ped_sprite(key, 2, False, 0)
        pixels.append(pygame.image.tobytes(sprite, "RGBA"))
    assert len(set(pixels)) == len(M.CHARACTER_LOOKS)


def test_nobody_asks_while_the_police_are_chasing_you():
    g = game()
    g.wanted_level = 3
    g.hs_cooldown = 0
    before = g.hs_asked
    for _ in range(200):
        ped = g.pedestrians[0]
        ped.mood = 'calm'
        ped.down_timer = 0
        ped.rect.center = g.player_rect.center
        g.barge_pedestrians()
    assert g.hs_asked == before, "asked mid-chase, which nobody would"


def test_potholes_are_on_roads_and_there_is_exactly_one_cone():
    g = game()
    assert len(g.potholes) == M.POTHOLE_COUNT
    for hole in g.potholes:
        col = int(hole['x']) // M.TILE_SIZE
        row = int(hole['y']) // M.TILE_SIZE
        assert M.tile_type_at(col, row) == M.TILE_ROAD, (
            f"a pothole in a building at {col},{row}")
    cones = [h for h in g.potholes if h['cone']]
    assert len(cones) == 1, "there is one cone and it never moves"


def test_hitting_a_pothole_costs_you_and_only_once():
    g = game()
    car = _drive(g)
    hole = g.potholes[0]
    car.rect.center = (hole['x'], hole['y'])
    car.velocity = 8.0
    hp0 = car.hp
    g.check_potholes()
    assert car.hp < hp0, "the pothole did nothing"
    hp1 = car.hp
    g.check_potholes()
    assert car.hp == hp1, "the same hole hit twice in consecutive frames"
    g.driving = None


def test_the_clydesdales_are_on_the_street_and_in_the_way():
    g = game()
    wide = max(rv.w for rv in g.rail)
    assert wide >= 100, "the hitch should be as long as a lane is wide"
    slow = min(abs(rv.speed) for rv in g.rail)
    assert slow < 1.0, "eight horses do not hurry"


def test_the_map_names_its_streets():
    """A St. Louis street grid with no names on it is any city's grid."""
    for row, name in M.STREET_ROWS.items():
        assert row % 8 == 4, f"{name} is not on a road line"
        assert len(name) <= 10, name
    for col, name in M.STREET_COLS.items():
        assert col % 8 == 4, f"{name} is not on a road line"
        assert len(name) <= 10, name
    assert "GRAVOIS" in M.STREET_ROWS.values()
    assert "KINGSHWY" in M.STREET_COLS.values()


# ---------------------------------------------------------------------------
# The job loop: chaining, expiry, and somewhere to spend the money
# ---------------------------------------------------------------------------

def test_delivering_puts_the_next_run_straight_on_the_table():
    """A finished delivery used to be followed by two seconds of silence and
    a cooldown. The next run is a decision, not a pause."""
    g = game()
    job = g.job
    teleport(g, job.pickup_pos)
    g.update_job()
    assert job.collected
    teleport(g, job.drop_pos)
    g.update_job()
    assert g.job is not None and g.job is not job, "no next run offered"
    assert g.chain_until > g.frame, "the hot-streak window never opened"


def test_taking_the_next_run_quickly_pays_more():
    """Same run, both ways - two different Job.generate() results would differ
    by distance alone and prove nothing."""
    def deliver(hot):
        g = game()
        # The shared game reset intentionally generates a fresh job. Re-roll
        # from the same seed so this comparison varies only the hot flag, not
        # the randomly selected endpoints and their distance-based payout.
        random.seed(41370)
        g.job = M.Job.generate()
        g.streak = 0
        job = g.job
        teleport(g, job.pickup_pos)
        g.update_job()
        assert job.collected
        job.hot = hot
        before = g.cash
        teleport(g, job.drop_pos)
        g.update_job()
        return g.cash - before

    fast, cold = deliver(True), deliver(False)
    assert fast > cold, f"hot {fast} vs cold {cold}"
    assert fast >= int(cold * (1.0 + M.JOB_CHAIN_BONUS)) - 1


def test_the_chain_window_is_what_marks_a_run_hot():
    g = game()
    job = g.job
    teleport(g, job.pickup_pos)
    g.update_job()
    teleport(g, job.drop_pos)
    g.update_job()
    nxt = g.job
    assert not nxt.hot
    teleport(g, nxt.pickup_pos)
    g.update_job()
    assert nxt.hot, "picked up inside the window and it was not hot"

    g2 = game()
    j2 = g2.job
    teleport(g2, j2.pickup_pos)
    g2.update_job()
    teleport(g2, j2.drop_pos)
    g2.update_job()
    n2 = g2.job
    g2.frame += M.JOB_CHAIN_WINDOW + 10
    teleport(g2, n2.pickup_pos)
    g2.update_job()
    assert not n2.hot, "the window never closed"


def test_a_run_you_never_take_goes_stale():
    """One unwanted job used to sit on the HUD for the whole session -
    verified across three screenshots ninety seconds apart."""
    g = game()
    job = g.job
    teleport(g, (40 * M.TILE_SIZE, 40 * M.TILE_SIZE))
    for _ in range(int(M.JOB_OFFER_SECONDS * M.FPS) + 4):
        g.update_job()
        if g.job is not job:
            break
    assert g.job is not job, "the offer never expired"


def test_you_can_throw_a_run_back_but_not_the_cargo():
    g = game()
    first = g.job
    g.reroll_job()
    assert g.job is not first, "R did not reroll the offer"
    held = g.job
    teleport(g, held.pickup_pos)
    g.update_job()
    assert held.collected
    g.reroll_job()
    assert g.job is held, "cargo in the boot is yours; you cannot hand it back"


def test_the_body_shop_takes_your_money_and_your_wanted_level():
    g = game()
    assert g.body_shops, "there should be a body shop somewhere"
    car = _drive(g)
    car.rect.center = g.body_shops[0]
    g.wanted_level = 4
    g.peak_star = 4
    dispatch_cops(g, 4)
    g.cash = 1000
    g.shop_cooldown = 0
    g.update_body_shop()
    assert g.wanted_level == 0, "drove into the shop hot and came out hot"
    assert g.police == [] and g.foot_police == []
    assert g.cash == 1000 - M.BODY_SHOP_COST
    g.driving = None


def test_the_body_shop_is_not_a_free_button():
    g = game()
    car = _drive(g)
    car.rect.center = g.body_shops[0]
    g.cash = 0
    g.banked = 0
    g.wanted_level = 3
    g.shop_cooldown = 0
    g.update_body_shop()
    assert g.wanted_level == 3, "resprayed for free"
    # and it does nothing at all when you are clean
    g.cash = 1000
    g.wanted_level = 0
    g.update_body_shop()
    assert g.cash == 1000, "charged for a respray nobody needed"
    g.driving = None


def test_the_grand_basin_is_water_you_have_to_go_round():
    """It was paint. You could jog straight across the most photographed
    thing in Forest Park."""
    wet = [(c, r) for r in range(M.MAP_TILES_H) for c in range(M.MAP_TILES_W)
           if M.GAME_MAP[r][c]['landmark'] == "The Grand Basin"]
    assert wet, "the basin is not on the map"
    for c, r in wet:
        assert M.GAME_MAP[r][c]['collidable'], f"{c},{r} is walkable water"
        assert M.GAME_MAP[r][c]['type'] == M.TILE_WATER


def test_forest_park_names_the_places_inside_it():
    named = {M.GAME_MAP[r][c]['landmark']
             for r in range(M.MAP_TILES_H) for c in range(M.MAP_TILES_W)}
    for feature in ("The Grand Basin", "Art Hill", "Saint Louis Art Museum",
                    "The Muny", "Saint Louis Zoo", "The Jewel Box"):
        assert feature in named, f"{feature} claims no tiles"
    assert "Forest Park" in named, "the park itself was completely eaten"


def test_a_feature_never_seals_the_park_off():
    """Making the basin solid must not cut anything off from the streets."""
    for (parent, name, fx, fy, fw, fh, solid) in M.LANDMARK_FEATURES:
        entry = next(e for e in M.LANDMARKS if e[5] == parent)
        lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
        open_tiles = [(c, r)
                      for r in range(ly, ly + lh) for c in range(lx, lx + lw)
                      if M.GAME_MAP[r][c]['landmark'] == name
                      and not M.GAME_MAP[r][c]['collidable']]
        for c, r in open_tiles:
            assert M.WALK_REACHABLE[r][c], f"{name} at {c},{r} is sealed off"


def test_the_hill_paints_its_hydrants():
    assert 'hydrant_hill' in M.props_PROPS
    plain = M.props_get('hydrant')
    painted = M.props_get('hydrant_hill')
    assert painted.get_width() >= plain.get_width() + 4
    assert painted.get_height() >= plain.get_height() + 6
    assert M.props_anchor_offset('hydrant_hill') == (5, 13)
    colors = {tuple(painted.get_at((x, y))[:3])
              for x in range(painted.get_width())
              for y in range(painted.get_height())
              if painted.get_at((x, y))[3]}
    assert {M.props_C_HILL_GREEN, M.props_C_HILL_WHITE,
            M.props_C_HILL_RED} <= colors
    for color in (M.props_C_HILL_GREEN, M.props_C_HILL_WHITE,
                  M.props_C_HILL_RED):
        assert sum(painted.get_at((x, y))[:3] == color
                   for x in range(painted.get_width())
                   for y in range(painted.get_height())) >= 8
    # and they are actually different sprites, not the same one twice
    assert any(plain.get_at((x, y)) != painted.get_at((x, y))
               for x in range(plain.get_width())
               for y in range(plain.get_height()))
    assert len(M.HILL_HYDRANT_TILES) >= 6
    for (col, row), anchor in M.HILL_HYDRANT_TILES.items():
        tile = M.GAME_MAP[row][col]
        props = M.props_props_for_tile(col, row, tile['type'], True)
        assert ('hydrant_hill', *anchor) in props, (col, row, props)
        assert not tile['collidable'], f"Hill hydrant at {col},{row} is inside a wall"


def _run_all():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - this is the reporter
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok   {name}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())

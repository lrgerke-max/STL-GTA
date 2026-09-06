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
import os
import random
import sys

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
    g.state = M.STATE_PLAYING
    g.busted_flash = 0
    g.wasted_flash = 0
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
    g.decals = []
    g.player_hp = M.PLAYER_MAX_HP
    g.weapon = 'fists'
    g.ammo = 0
    g.attack_cd = 0
    g.punch_timer = 0
    g.bullets = []
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
    g.update_police()
    assert len(g.police) == M.COP_COUNT_BY_STAR[M.WANTED_MAX]


def test_cops_spawn_within_reach_of_the_player():
    """They used to all spawn at the downtown station regardless of where the
    player was, so on the far side of the map they never arrived at all."""
    g = game()
    g.wanted_level = 3
    g.police = []
    teleport(g, (20 * M.TILE_SIZE, 80 * M.TILE_SIZE))
    g.update_police()
    assert g.police
    for cop in g.police:
        d = math.hypot(cop.rect.centerx - g.player_rect.centerx,
                       cop.rect.centery - g.player_rect.centery)
        assert d <= M.COP_SPAWN_MAX + M.TILE_SIZE, d


def test_single_frame_of_contact_does_not_bust_you():
    g = game()
    g.wanted_level = 1
    g.police = []
    g.update_police()
    g.police[0].rect.center = g.player_rect.center
    g.update_police()
    assert g.busted_flash == 0, "one touch must not be an instant bust"
    assert g.bust_meter > 0


def test_sustained_contact_does_bust_you():
    g = game()
    g.wanted_level = 1
    g.cash = 1000
    g.police = []
    g.update_police()
    for _ in range(M.BUST_CONTACT_STEPS + 4):
        if g.police:
            g.police[0].rect.center = g.player_rect.center
        g.update_police()
    assert g.busted_flash > 0
    assert g.wanted_level == 0
    assert g.cash == 1000 - M.BAIL_COST


def test_bust_respawn_is_the_station_not_a_random_tile():
    """Busting used to teleport you to a random tile on a 100x100 map, which
    destroyed any sense of where you were."""
    g = game()
    g.wanted_level = 2
    g.busted()
    d = math.hypot(g.player_rect.centerx - g.police_station[0],
                   g.player_rect.centery - g.police_station[1])
    assert d < 10 * M.TILE_SIZE, f"woke up {d:.0f}px from the station"


def test_heat_does_not_decay_while_a_cop_is_on_you():
    """The old timer shed a star every six seconds regardless, so the optimal
    play against the police was to park and wait them out."""
    g = game()
    g.wanted_level = 3
    g.police = []
    g.update_police()
    for _ in range(M.HEAT_GRACE + M.WANTED_DECAY_STEPS + 60):
        for cop in g.police:
            cop.rect.center = g.player_rect.center
        g.update_police()
        g.update_wanted_decay()
        if g.busted_flash:              # taken; that is a different test
            g.busted_flash = 0
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
    g = game()
    cop = M.Car(*g.police_station, color=M.POLICE_COLOR, variant='police')
    cop.driver = 'police'
    target = (g.police_station[0], g.police_station[1] - 900)
    start = cop.rect.center
    for _ in range(400):
        cop.chase_ai(target)
    moved = math.hypot(cop.rect.centerx - start[0], cop.rect.centery - start[1])
    assert moved > 4 * M.TILE_SIZE, f"cop only travelled {moved:.0f}px in 400 steps"


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
    # "+", "(" and ")" were missing and live strings already used them.
    assert {"+", "(", ")"} <= ok, "callout / streak text needs + ( )"
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
    for _ in range(55):
        car.input_throttle = 1.0
        car.input_steer = 0.0
        car.physics_step()

    assert y0 - car.rect.centery > 40, (
        f"car only crawled {y0 - car.rect.centery}px along the wall")
    assert car.velocity > 0, "car reversed off the wall instead of sliding"
    # hugging the face is fine; punching a third of a tile through it is not
    assert car.rect.centerx <= x0 + 16, "car slid through the wall it hit"


# ---------------------------------------------------------------------------
# Bring-it-to-life systems: feedback, reactivity, stakes
# ---------------------------------------------------------------------------

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
    g.wanted_level = 3
    g.police = []
    g.update_police()
    assert len(g.police) == M.COP_COUNT_BY_STAR[3]
    g.police[0].burn = 1
    g.update()                       # update_wrecks then update_police, same step
    assert g.check_invariants() is None, g.check_invariants()
    assert len(g.police) == M.COP_COUNT_BY_STAR[3]


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
    keys = {M.pygame.K_e, M.pygame.K_SPACE, M.pygame.K_m, M.pygame.K_ESCAPE}
    assert set(M.PAD_BUTTON_KEYS.values()) <= keys
    for essential in (M.PAD_A, M.PAD_X, M.PAD_START):
        assert essential in M.PAD_BUTTON_KEYS
    # every mapped button index is a plausible XInput button
    assert all(0 <= b <= 10 for b in M.PAD_BUTTON_KEYS)


def test_shop_signs_fit_on_a_shopfront():
    """A 64px tile leaves a 60px sign board; anything wider silently vanishes."""
    for hood, pool in M.HOOD_SIGNS.items():
        for name, _bg, _fg in pool:
            w = M.hud_text_width(name, 1)
            assert w <= M.TILE_SIZE - 4, f"{hood}: {name!r} is {w}px, too wide"


def test_neighbourhoods_pick_their_own_character():
    """The Hill should read Italian, the Loop should read arts - the whole
    point of the hood table is that blocks are not interchangeable."""
    hill = {M.hood_pick_sign(30, 62, M._noise(30, 62, 71) + i * 7)[0]
            for i in range(24)}
    arts = {M.hood_pick_sign(12, 12, M._noise(12, 12, 71) + i * 7)[0]
            for i in range(24)}
    assert hill & {"DELI", "PIZZERIA", "BAKERY", "IMO'S"}, hill
    assert not (hill & {"FOX", "THE GROVE"}), hill
    assert arts & {"FOX", "THE GROVE", "RECORDS"}, arts
    assert M.hood_at(30, 62) == 'hill'
    assert M.hood_at(70, 45) == 'downtown'
    for style in ('shotgun', 'gable_brick', 'mansard', 'painted_lady'):
        assert any(style in pool for pool in M.HOOD_HOUSES.values())


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


def test_the_stadium_has_exactly_one_way_in():
    """Solid bowl, open field, a single gate - not a maze and not a plaza."""
    entry = next(e for e in M.LANDMARKS if e[5] == "Downtown & Busch Stadium")
    lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
    cx, cy = int(round(0.355 * lw)), int(round(0.50 * lh))
    field = (lx + cx, ly + cy)
    assert not M.GAME_MAP[field[1]][field[0]]['collidable'], "field must be open"
    assert M.WALK_REACHABLE[field[1]][field[0]], "field must be reachable"
    # the ring is real: walking due north from the centre hits a wall
    hit_wall = any(M.GAME_MAP[ly + cy - k][lx + cx]['collidable']
                   for k in range(1, cy + 1))
    assert hit_wall, "the bowl should be a hard wall to the north"


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

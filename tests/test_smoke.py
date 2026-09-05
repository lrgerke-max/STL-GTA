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
    strings = list(M.Job.CARGO)
    strings += [lm[5] for lm in M.LANDMARKS]
    strings += [s for pair in M.Game.PAUSE_LINES for s in pair]
    strings += ["PAUSED", "DRIVING", "ON FOOT", "BUSTING", "BUSTED!",
                "DELIVER TO", "PICK UP AT", "STREAK X9", "LOST THEM",
                "JACKED A RIDE!", "NO ROOM TO GET OUT!",
                "TOO HOT - LOSE THE COPS FIRST", "CARGO IMPOUNDED",
                "TOO SLOW - RUN LOST", "PRESS ESC FOR CONTROLS",
                "RUNS 0  LOST 0  BEST X0", "WANTED! LOSE THEM OR GET BUSTED"]
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

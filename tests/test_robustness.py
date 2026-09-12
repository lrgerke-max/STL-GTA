"""The things that lose somebody's whole run.

A crash on a corrupt save file costs the player everything they did. A weapon
that silently does nothing costs them a fight. Neither shows up in a test that
only exercises the happy path, so this file is deliberately hostile: malformed
saves, saves taken mid-everything, death loops, and every weapon measured
against its own declared numbers.
"""

import json
import math
import os
import random
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402
import main as M  # noqa: E402
import throwables as TL  # noqa: E402


def _clean(game):
    game.state = M.STATE_PLAYING
    game.wanted_level = 0
    game.police = []
    game.foot_police = []
    game.side_mission = None
    game.local_challenge = None
    if game.driving is not None:
        game.driving.driver = None
        game.driving.parked = True
        game.driving = None
    return game


def _arena(game, seed=17):
    """Player on open asphalt with the full armoury."""
    random.seed(seed)
    _clean(game)
    game.pedestrians = []
    game.cars = []
    row = sorted(M.ROAD_LINES)[6]
    game.player_rect.center = (10 * M.TILE_SIZE + M.TILE_SIZE // 2,
                               row * M.TILE_SIZE + M.TILE_SIZE // 2)
    game.sync_player_float()
    game.camera.snap_to(game.player_rect)
    game.owned_weapons = set(M.WEAPON_ORDER)
    for kind in M.WEAPON_ORDER:
        game.weapon_ammo[kind] = 400
    game.attack_cd = 0
    return game


# ------------------------------------------------------------------ saves
def test_a_hostile_save_file_never_crashes_the_game():
    """Every one of these is a file a real player can end up with."""
    tmp = tempfile.mkdtemp(prefix="stlgta-test-save-")
    game = _clean(M.Game())
    game.score, game.cash, game.banked = 1234, 567, 89
    game.discovered = {"Gateway Arch"}
    good_path = os.path.join(tmp, "good.json")
    game.save_game(announce=False, path=good_path)
    good = json.load(open(good_path, encoding="utf-8"))

    cases = {
        "empty": "",
        "not json": "{{{ nope",
        "a list": "[1, 2, 3]",
        "a string": '"hello"',
        "null": "null",
        "truncated": json.dumps(good)[:len(json.dumps(good)) // 2],
        "no version": json.dumps({k: v for k, v in good.items() if k != 'version'}),
        "old version": json.dumps({**good, 'version': 1}),
        "future version": json.dumps({**good, 'version': 9999}),
        "no player": json.dumps({k: v for k, v in good.items() if k != 'player'}),
        "player not a dict": json.dumps({**good, 'player': 42}),
        "player off map": json.dumps({**good, 'player': {'x': 10 ** 9, 'y': -10 ** 9}}),
        "player nan": json.dumps({**good, 'player': {'x': 'NaN', 'y': 'NaN'}}),
        "cash a string": json.dumps({**good, 'cash': "lots"}),
        "cash negative": json.dumps({**good, 'cash': -99999}),
        "wanted 99": json.dumps({**good, 'wanted_level': 99}),
        "wanted negative": json.dumps({**good, 'wanted_level': -5}),
        "discovered a dict": json.dumps({**good, 'discovered': {"a": 1}}),
        "discovered junk": json.dumps({**good, 'discovered': [1, None, {"x": 2}]}),
        "weapons a string": json.dumps({**good, 'weapons': "pistol"}),
        "unknown weapon": json.dumps({**good, 'weapons': {
            'selected': 'raygun', 'owned': ['raygun'], 'ammo': {'raygun': 5}}}),
        "ammo an int": json.dumps({**good, 'weapons': {
            'selected': 'fists', 'owned': ['fists'], 'ammo': 7}}),
        "ammo negative": json.dumps({**good, 'weapons': {
            'selected': 'pistol', 'owned': ['pistol'], 'ammo': {'pistol': -20}}}),
    }
    for label, body in cases.items():
        path = os.path.join(tmp, f"{abs(hash(label))}.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        fresh = _clean(M.Game())
        fresh.load_game(path)                      # must not raise
        for _ in range(30):
            fresh.update()                         # and must stay playable
        assert 0 <= fresh.wanted_level <= M.WANTED_MAX, (
            f"'{label}' left wanted_level at {fresh.wanted_level}")
        assert 0 <= fresh.player_rect.centerx <= M.MAP_WIDTH, label
        assert 0 <= fresh.player_rect.centery <= M.MAP_HEIGHT, label

    missing = _clean(M.Game())
    missing.load_game(os.path.join(tmp, "does-not-exist.json"))
    for _ in range(30):
        missing.update()


def test_a_save_round_trips_everything_it_claims_to_keep():
    tmp = tempfile.mkdtemp(prefix="stlgta-test-rt-")
    path = os.path.join(tmp, "rt.json")
    game = _clean(M.Game())
    game.score, game.cash, game.banked = 123456, 7890, 54321
    game.discovered = {"Gateway Arch", "Ted Drewes"}
    game.owned_weapons = {'fists', 'pistol'}
    game.weapon_ammo['pistol'] = 41
    game.equip_weapon('pistol', False)
    game.jobs_done, game.best_streak = 9, 5
    game.player_rect.center = (40 * M.TILE_SIZE + 32, 37 * M.TILE_SIZE + 32)
    game.sync_player_float()
    game.save_game(announce=False, path=path)

    loaded = _clean(M.Game())
    loaded.load_game(path)
    assert loaded.score == game.score
    assert loaded.cash == game.cash
    assert loaded.banked == game.banked
    assert loaded.discovered == game.discovered
    assert loaded.owned_weapons == game.owned_weapons
    assert loaded.weapon_ammo['pistol'] == 41
    assert loaded.weapon == 'pistol'
    assert loaded.jobs_done == 9
    assert loaded.best_streak == 5
    assert loaded.player_rect.center == game.player_rect.center


def test_saving_mid_anything_survives_a_reload():
    tmp = tempfile.mkdtemp(prefix="stlgta-test-mid-")
    for label in ('driving', 'chase', 'dead', 'side mission', 'challenge', 'map'):
        random.seed(5)
        game = _clean(M.Game())
        if label == 'driving':
            car = M.Car(*game.player_rect.center, variant='sedan')
            car.driver = 'player'
            car.parked = False
            game.cars.append(car)
            game.driving = car
        elif label == 'chase':
            game.wanted_level = 5
            for _ in range(90):
                game.update()
        elif label == 'dead':
            game.state = M.STATE_DEAD
            game.death_timer = 10
        elif label == 'side mission':
            game.side_mission_serial = 1
            contact, _n = game.side_mission_contact()
            game.player_rect.center = (int(contact[0]), int(contact[1]))
            game.sync_player_float()
            game.update()
            game.try_start_side_mission()
        elif label == 'challenge':
            game.start_local_challenge('hill_hydrants')
        else:
            game.handle_keydown(pygame.K_m)

        path = os.path.join(tmp, f"{abs(hash(label))}.json")
        game.save_game(announce=False, path=path)
        back = _clean(M.Game())
        back.load_game(path)
        for _ in range(60):
            back.update()
            back.draw()
        assert back.state == M.STATE_PLAYING, f"saved while {label}, came back {back.state}"


def test_dying_over_and_over_always_respawns_somewhere_legal():
    random.seed(9)
    game = _clean(M.Game())
    for i in range(25):
        game.state = M.STATE_PLAYING
        game.player_hp = 1
        game.wanted_level = i % 6
        game.wasted("TEST")
        for _ in range(300):
            game.update()
            if game.state == M.STATE_PLAYING:
                break
        assert game.state == M.STATE_PLAYING, f"stuck dead on cycle {i}"
        assert not M.is_blocked(game.player_rect), (
            f"cycle {i} respawned inside geometry at {game.player_rect.center}")
        assert M.is_reachable(*game.player_rect.center), (
            f"cycle {i} respawned somewhere cut off")


# ---------------------------------------------------------------- weapons
def test_every_weapon_equips_and_fires_in_every_direction():
    game = M.Game()
    for kind in M.WEAPON_ORDER:
        _arena(game)
        assert game.equip_weapon(kind, False), f"cannot equip {kind}"
        if kind in TL.THROWABLE_ORDER:
            game.throwable_system.add_inventory(kind, 6)
            game.weapon_ammo[kind] = game.throwable_system.inventory(kind)
        for step in range(8):
            game.player_aim = step * math.tau / 8.0
            game.attack_cd = 0
            game.ammo = max(game.ammo, 1)
            game.player_attack()               # must not raise in any heading
            for _ in range(4):
                game.update()


def test_each_weapon_reaches_as_far_as_it_claims_and_no_further():
    """Melee stops at its declared range; a gun carries."""
    game = M.Game()

    def drops_ped(kind, dist):
        _arena(game)
        game.equip_weapon(kind, False)
        px, py = game.player_rect.center
        ped = M.Pedestrian(px + dist, py, "commuter#0")
        game.pedestrians = [ped]
        game.player_aim = 0.0
        for _ in range(80):
            game.attack_cd = 0
            game.ammo = 400
            game.player_attack()
            game.update()
            if ped.down_timer > 0 or ped not in game.pedestrians:
                return True
        return False

    for kind in ('fists', 'bat'):
        reach = M.WEAPON_DEFS[kind]['range']
        assert drops_ped(kind, max(8, reach - 12)), (
            f"{kind} cannot hit inside its own {reach}px range")
        assert not drops_ped(kind, reach + 90), (
            f"{kind} reaches 90px past its declared {reach}px range")

    for kind in ('pistol', 'shotgun', 'smg'):
        assert drops_ped(kind, 40), f"{kind} cannot hit at 40px"
        assert drops_ped(kind, 220), f"{kind} cannot hit at 220px"


def test_a_thrown_bottle_starts_a_fire_that_hurts_people():
    """The fire bottle is the one weapon whose damage is all second-order."""
    game = M.Game()
    _arena(game)
    game.throwable_system.add_inventory(TL.FIRE_BOTTLE, 6)
    game.weapon_ammo[TL.FIRE_BOTTLE] = game.throwable_system.inventory(TL.FIRE_BOTTLE)
    game.equip_weapon(TL.FIRE_BOTTLE, False)
    before = game.ammo
    game.player_aim = 0.0
    game.attack_cd = 0
    game.player_attack()
    assert game.throwable_system.projectiles(), "nothing left the hand"
    assert game.ammo == before - 1, "the throw did not cost a bottle"

    seen_zone = False
    for _ in range(400):
        game.update()
        if game.throwable_system.fire_zones():
            seen_zone = True
    assert seen_zone, "the bottle never started a fire"


def test_you_cannot_shoot_from_inside_a_car():
    game = M.Game()
    _arena(game)
    game.equip_weapon('pistol', False)
    car = M.Car(*game.player_rect.center, variant='sedan')
    car.driver = 'player'
    car.parked = False
    game.cars.append(car)
    game.driving = car
    game.ammo = 40
    game.attack_cd = 0
    game.player_attack()
    assert game.ammo == 40, "fired a pistol from the driver's seat"


def test_cycling_weapons_reaches_every_one_you_own():
    game = M.Game()
    _arena(game)
    seen = set()
    for _ in range(len(M.WEAPON_ORDER) * 3):
        game.handle_keydown(pygame.K_q)
        seen.add(game.weapon)
    assert seen == set(M.WEAPON_ORDER), (
        f"cycling only reaches {sorted(seen)}")


def test_random_input_does_not_crash_the_game():
    """Fuzz. Nothing clever - just never let a key sequence take it down."""
    random.seed(4242)
    game = M.Game()
    _arena(game, seed=4242)
    keys = [pygame.K_e, pygame.K_q, pygame.K_SPACE, pygame.K_m, pygame.K_TAB,
            pygame.K_LSHIFT, pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_h,
            pygame.K_r, pygame.K_ESCAPE]
    rng = random.Random(99)
    for _ in range(3000):
        if rng.random() < 0.12:
            game.handle_keydown(rng.choice(keys))
        if rng.random() < 0.04:
            game.wanted_level = rng.randrange(M.WANTED_MAX + 1)
        for kind in M.WEAPON_ORDER:
            game.weapon_ammo[kind] = max(game.weapon_ammo.get(kind, 0), 20)
        game.player_dir = (rng.choice((-1, 0, 1)), rng.choice((-1, 0, 1)))
        game.player_aim = rng.random() * math.tau
        if game.state == M.STATE_DEAD:
            game.state = M.STATE_PLAYING
            game.death_timer = 0
        game.update()
        game.draw()

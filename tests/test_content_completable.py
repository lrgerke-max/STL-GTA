"""Every piece of content can actually be finished.

A mission you cannot complete is worse than a mission that does not exist,
and it is invisible to every other test in this suite: the state machine is
fine, the map is fine, and the run is simply impossible. So drive each family,
each courier kind and each local challenge to its end.

Objectives are satisfied by teleporting to them. That is deliberate - whether
the city can be driven is probe_roads' job, and this file is about whether the
content's own state machine can be walked from start to finish.

Two things this caught:
  * the vehicle-theft mission drew its target from self.cars without the
    `driver is None` test that toggle_enter_exit enforces, so it could mark a
    vehicle the game would never let you enter
  * three of the five local challenges and one whole family look broken if you
    turn up in the wrong vehicle, because they gate on a specific one. That is
    correct, and worth pinning so nobody "fixes" the gate.
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
import missions as ML  # noqa: E402

#: The vehicle each local challenge demands. None means on foot.
CHALLENGE_VEHICLE = {
    'mudfoot': 'mudfoot',
    'grocery_cart': 'grocery_cart',
    'trash_day': 'garbage_truck',
    'chain_escape': 'vespa',
    'hill_hydrants': None,
}


def _clean(game):
    game.state = M.STATE_PLAYING
    game.side_mission = None
    game.local_challenge = None
    game.job = None
    game.wanted_level = 0
    game.police = []
    game.foot_police = []
    game.legend_mastery = set()
    game.side_mission_cooldown = 0
    return game


def _stand(game, pos):
    """Put the player on foot at `pos`, leaving no car half-occupied."""
    if game.driving is not None:
        game.driving.driver = None
        game.driving.parked = True
        game.driving = None
    game.player_rect.center = (int(pos[0]), int(pos[1]))
    game.sync_player_float()
    game.camera.snap_to(game.player_rect)


def test_every_side_mission_family_can_be_completed():
    random.seed(3)
    game = _clean(M.Game())
    done = {}
    for serial in range(len(ML.MISSION_FAMILIES)):
        _clean(game)
        game.side_mission_serial = serial
        family = ML.MISSION_FAMILIES[serial % len(ML.MISSION_FAMILIES)]
        contact, _name = game.side_mission_contact()
        _stand(game, contact)
        game.update()
        assert game.try_start_side_mission(), f"{family} would not start"
        assert game.side_mission is not None, f"{family} started nothing"
        mission = game.side_mission

        for _ in range(3000):
            if game.side_mission is None:
                break
            if family == ML.VEHICLE_THEFT:
                car = game.side_target_car
                assert car is not None, "the marked ride vanished"
                # The target must be jackable - see the module docstring.
                if game.driving is not car:
                    assert car.driver is None, (
                        "the mission marked a car that already has a driver, "
                        "so toggle_enter_exit will never let you in")
                    car.velocity = 0.0
                    _stand(game, car.rect.center)
                    game.toggle_enter_exit()
                    assert game.driving is car, "could not jack the marked ride"
                else:
                    car.rect.center = (int(game.side_target_pos[0]),
                                       int(game.side_target_pos[1]))
                    game.camera.snap_to(car.rect)
            elif family == ML.SMASH_TARGETS:
                if game.driving is None:
                    car = M.Car(*game.player_rect.center, variant='sedan')
                    car.driver = 'player'
                    car.parked = False
                    M.traffic_take_over(car)
                    game.cars.append(car)
                    game.driving = car
                else:
                    live = [t for t in game.smash_targets if t['hp'] > 0]
                    if live:
                        game.driving.rect.center = live[0]['pos']
                        game.driving.velocity = 3.0
                        game.frame += 20      # clear the per-target cooldown
            else:                              # EVADE_HEAT
                game.wanted_level = 0
                game.police = []
                game.foot_police = []
                game.spotted = False
                if mission.stage == 'reach_safehouse':
                    _stand(game, game.side_target_pos)
            game.update()

        done[family] = mission.status
        assert mission.status == ML.SUCCEEDED, (
            f"{family} ended {mission.status} at stage {mission.stage}")
    assert set(done) == set(ML.MISSION_FAMILIES), done


def test_every_courier_kind_can_be_delivered():
    random.seed(5)
    game = _clean(M.Game())
    delivered = set()
    for kind in M.JOB_KIND_ORDER:
        _clean(game)
        job = None
        for _ in range(60):
            job = game.deal_job()
            if job is not None and job.kind == kind:
                break
        assert job is not None and job.kind == kind, f"never dealt a {kind} run"
        game.job = job
        _stand(game, job.pickup_pos)
        for _ in range(4):
            game.update()
        assert job.collected, f"{kind}: pickup at {job.pickup} did not register"
        _stand(game, job.drop_pos)
        for _ in range(4):
            game.update()
        assert game.job is not job, (
            f"{kind}: drop at {job.dropoff} did not register")
        delivered.add(kind)
    assert delivered == set(M.JOB_KIND_ORDER), delivered


def test_every_local_challenge_can_be_mastered():
    random.seed(7)
    game = _clean(M.Game())
    assert set(CHALLENGE_VEHICLE) == set(M.LOCAL_CHALLENGE_TIMES), (
        "a local challenge was added or removed without updating this test")

    for kind, want in sorted(CHALLENGE_VEHICLE.items()):
        _clean(game)
        if kind == 'chain_escape':
            ride = game.chain_bike
            assert ride is not None, "the fixed chain bike is not on the map"
        elif kind == 'mudfoot':
            ride = game.local_legend_car('mudfoot')
            assert ride is not None, "the mudfoot truck is not on the map"
        elif want is not None:
            ride = M.Car(*game.player_rect.center, variant=want)
            M.traffic_take_over(ride)
            game.cars.append(ride)
        else:
            ride = None
        if ride is not None:
            ride.driver = 'player'
            ride.parked = False
            game.driving = ride
            game.camera.snap_to(ride.rect)
        else:
            game.driving = None

        assert game.start_local_challenge(kind), f"{kind} would not start"
        for _ in range(6000):
            if game.local_challenge is None:
                break
            challenge = game.local_challenge
            # The clock is not what is under test here.
            challenge['steps_left'] = max(challenge['steps_left'], 600)
            if kind == 'mudfoot':
                nxt = next((t for t in challenge['targets'] if not t['hit']), None)
                if nxt is not None:
                    game.driving.rect.center = nxt['rect'].center
                    game.driving.velocity = 3.0
            else:
                marker = game.local_challenge_marker()
                if marker is not None:
                    if game.driving is not None:
                        game.driving.rect.center = (int(marker[0]), int(marker[1]))
                        game.driving.velocity = 2.0
                    else:
                        _stand(game, marker)
            game.update()
        assert kind in game.legend_mastery, f"{kind} never paid out"


def test_a_challenge_refuses_the_wrong_vehicle():
    """The gates are the design. Nobody should 'fix' them away."""
    random.seed(11)
    game = _clean(M.Game())
    game.driving = None
    assert not game.start_local_challenge('chain_escape'), (
        "the Chain of Rocks run should demand the bike")
    _clean(game)
    sedan = M.Car(*game.player_rect.center, variant='sedan')
    sedan.driver = 'player'
    sedan.parked = False
    M.traffic_take_over(sedan)
    game.cars.append(sedan)
    game.driving = sedan
    assert not game.start_local_challenge('chain_escape'), (
        "a sedan is not the chain bike")

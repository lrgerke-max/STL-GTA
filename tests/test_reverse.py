"""Focused regression tests for player-car reversing.

These exercise the real input router and Car physics.  The intent is to keep
"S maps to negative throttle" from being mistaken for "reverse works": the
car must cross zero, travel rearward, steer with reversed yaw, and leave a
wall after a head-on stop.
"""

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402
import main as M  # noqa: E402


def _road_point():
    """Middle of a long east-west street, clear for a reversing run."""
    row = sorted(M.ROAD_LINES)[6]
    return (10 * M.TILE_SIZE + M.TILE_SIZE // 2,
            row * M.TILE_SIZE + M.TILE_SIZE // 2)


def _player_car(position=None):
    car = M.Car(*(position or _road_point()), variant="sedan")
    car.driver = "player"
    car.angle = 0.0
    car.velocity = 0.0
    car.vlat = 0.0
    car.steer_angle = 0.0
    car.sub_x = car.sub_y = 0.0
    return car


def _step(car, throttle, steer=0.0, steps=1):
    hits = 0
    for _ in range(steps):
        car.input_throttle = throttle
        car.input_steer = steer
        car.input_handbrake = False
        hits += bool(car.physics_step())
    return hits


class _Keys:
    def __init__(self, *pressed):
        self.pressed = set(pressed)

    def __getitem__(self, key):
        return key in self.pressed


def _input_shell(car):
    """Smallest Game-shaped object accepted by the driving input branch."""
    g = object.__new__(M.Game)
    g.state = M.STATE_PLAYING
    g.show_map = False
    g.arch_victory_timer = 0
    g.driving = car
    g.pad = None
    g.sprinting = False
    g.attack_held = False
    g.player_dir = [0.0, 0.0]
    return g


def test_s_and_down_route_to_negative_throttle(monkeypatch):
    """Both documented keyboard controls must reach the physics as reverse."""
    car = _player_car()
    g = _input_shell(car)
    monkeypatch.setattr(pygame.event, "get", lambda: [])

    for key in (pygame.K_s, pygame.K_DOWN):
        monkeypatch.setattr(pygame.key, "get_pressed", lambda key=key: _Keys(key))
        M.Game.handle_events(g)
        assert car.input_throttle == -1.0


def test_gamepad_left_trigger_routes_to_negative_throttle(monkeypatch):
    """The analogue left trigger must win over keyboard/default throttle."""
    g = object.__new__(M.Game)
    monkeypatch.setattr(g, "pad_trigger",
                        lambda axis: 1.0 if axis == M.PAD_AX_LT else 0.0)
    monkeypatch.setattr(g, "pad_button", lambda _button: False)
    monkeypatch.setattr(g, "pad_axis", lambda _axis: 0.0)
    monkeypatch.setattr(g, "pad_hat", lambda: (0, 0))
    throttle, steer = M.Game.apply_pad_driving(g, 0.0, 0.0)
    assert throttle == -1.0
    assert steer == 0.0


def test_reverse_from_standstill_moves_rearward_and_selects_reverse_gear():
    car = _player_car()
    start_x = car.rect.centerx

    _step(car, -1.0, steps=M.FPS)

    assert car.velocity < -3.0
    assert car.rect.centerx < start_x - 150
    assert car.drive_gear() == "R"
    assert math.isclose(abs(car.velocity), car.max_speed * M.PLAYER_REVERSE_RATIO,
                        rel_tol=1e-6)


def test_braking_from_forward_motion_crosses_zero_then_reverses():
    car = _player_car()
    car.velocity = car.max_speed
    start_x = car.rect.centerx
    zero_frame = None
    reverse_frame = None

    for frame in range(1, M.FPS * 2 + 1):
        _step(car, -1.0)
        if zero_frame is None and car.velocity <= 0.0:
            zero_frame = frame
        if reverse_frame is None and car.rect.centerx < start_x:
            reverse_frame = frame

    assert zero_frame is not None
    assert reverse_frame is not None
    assert zero_frame < reverse_frame
    assert car.velocity < 0.0
    assert car.drive_gear() == "R"


def test_reverse_steering_has_opposite_yaw_to_forward_steering():
    def yaw(velocity):
        car = _player_car()
        home = car.rect.center
        car.velocity = velocity
        start_angle = car.angle
        for _ in range(20):
            # Reset position so this is a pure yaw test, independent of map
            # geometry; preserve velocity so forward/reverse are symmetric.
            car.rect.center = home
            car.velocity = velocity
            _step(car, 0.0, steer=1.0)
        return car.angle - start_angle

    forward_yaw = yaw(2.0)
    reverse_yaw = yaw(-2.0)
    assert forward_yaw > 0.0
    assert reverse_yaw < 0.0
    assert abs(reverse_yaw) > math.radians(10)


def test_reverse_can_back_away_after_a_head_on_wall_collision():
    wall = None
    for row in range(4, M.MAP_TILES_H - 4):
        for col in range(4, M.MAP_TILES_W - 4):
            if (M.GAME_MAP[row][col]["collidable"]
                    and M.tile_type_at(col - 1, row) == M.TILE_ROAD
                    and M.tile_type_at(col - 2, row) == M.TILE_ROAD):
                wall = (col, row)
                break
        if wall is not None:
            break
    assert wall is not None, "map needs a wall with a clear western approach"

    col, row = wall
    wall_left = col * M.TILE_SIZE
    position = (wall_left - M.VEHICLE_DEFAULT_W // 2 - 1,
                row * M.TILE_SIZE + M.TILE_SIZE // 2)
    car = _player_car(position)
    car.velocity = 2.0

    hits = _step(car, 1.0, steps=20)
    contact_x = car.rect.centerx
    assert hits > 0, "setup never reached the wall"

    _step(car, -1.0, steps=45)
    assert car.rect.centerx < contact_x - 100
    assert car.velocity < 0.0
    assert not M.is_blocked(car.rect)

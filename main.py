import pygame
import sys
import os
import json
import math
import random

# ============================================================
# STL-GTA: a cartoonish, top-down, GTA1-style driving sandbox
# set in a stylized St. Louis.
# ============================================================

# --- Screen / world constants ---
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60

TILE_SIZE = 64
MAP_TILES_W = 100
MAP_TILES_H = 100
MAP_WIDTH = MAP_TILES_W * TILE_SIZE
MAP_HEIGHT = MAP_TILES_H * TILE_SIZE

PLAYER_SIZE = 28
PLAYER_SPEED = 4.2

# --- Tile types ---
TILE_GRASS = 0
TILE_ROAD = 1
TILE_WATER = 2
TILE_BUILDING = 3
TILE_PARK = 4

# --- Cartoon color palette (bright & saturated, GTA1-poster style) ---
COLOR_SKY_BG = (58, 46, 92)          # background behind the map (never normally seen)
COLOR_GRASS = (99, 179, 90)
COLOR_ROAD = (58, 58, 66)
COLOR_ROAD_LINE = (241, 196, 15)
COLOR_WATER = (58, 141, 219)
COLOR_WATER_LINE = (120, 190, 245)
COLOR_PARK = (68, 150, 84)
COLOR_PARK_TREE = (39, 110, 58)
COLOR_OUTLINE = (25, 20, 35)
COLOR_SIDEWALK = (188, 178, 158)

PLAYER_COLOR = (238, 66, 102)
POLICE_COLOR = (40, 70, 200)
CAR_COLORS = [
    (240, 190, 60), (60, 190, 160), (230, 120, 60),
    (170, 100, 210), (250, 130, 170), (110, 200, 90), (250, 90, 90),
]

# --- Landmarks: real St. Louis places, spread across the world grid ---
# (x_tile, y_tile, w_tiles, h_tiles, kind, name, color)
LANDMARKS = [
    (78, 40, 6, 8, "building", "Gateway Arch", (170, 150, 120)),
    (66, 42, 10, 8, "building", "Downtown & Busch Stadium", (150, 110, 150)),
    (66, 54, 9, 7, "building", "Soulard & Anheuser-Busch", (200, 130, 70)),
    (12, 30, 22, 18, "park", "Forest Park", COLOR_PARK),
    (16, 18, 9, 8, "building", "Central West End", (120, 140, 190)),
    (22, 52, 7, 6, "building", "The Hill", (210, 150, 90)),
    (6, 6, 12, 8, "building", "Delmar Loop", (190, 90, 140)),
    (40, 62, 14, 12, "park", "Tower Grove Park", COLOR_PARK),
    (46, 34, 8, 7, "building", "Grand Center Arts District", (140, 90, 190)),
]

POLICE_STATION_TILE = (50, 50)


def build_map():
    """Generate the tile grid: roads on a grid, river along the east edge,
    landmarks stamped on top."""
    game_map = [[None] * MAP_TILES_W for _ in range(MAP_TILES_H)]
    road_lines = set(range(4, MAP_TILES_W, 8))

    for y in range(MAP_TILES_H):
        for x in range(MAP_TILES_W):
            if x in road_lines or y in road_lines:
                tile = {'type': TILE_ROAD, 'collidable': False, 'landmark': None, 'color': COLOR_ROAD}
            elif x >= MAP_TILES_W - 3:
                tile = {'type': TILE_WATER, 'collidable': True, 'landmark': None, 'color': COLOR_WATER}
            else:
                tile = {'type': TILE_GRASS, 'collidable': False, 'landmark': None, 'color': COLOR_GRASS}
            game_map[y][x] = tile

    for (lx, ly, lw, lh, kind, name, color) in LANDMARKS:
        collidable = (kind == "building")
        ttype = TILE_BUILDING if kind == "building" else TILE_PARK
        for y in range(ly, min(ly + lh, MAP_TILES_H)):
            for x in range(lx, min(lx + lw, MAP_TILES_W)):
                game_map[y][x] = {
                    'type': ttype, 'collidable': collidable, 'landmark': name, 'color': color,
                }
    return game_map


GAME_MAP = build_map()


def tile_at(col, row):
    if 0 <= row < MAP_TILES_H and 0 <= col < MAP_TILES_W:
        return GAME_MAP[row][col]
    return None


def is_blocked(rect):
    """True if rect overlaps any collidable tile."""
    start_col = max(0, rect.left // TILE_SIZE - 1)
    end_col = min(MAP_TILES_W - 1, rect.right // TILE_SIZE + 1)
    start_row = max(0, rect.top // TILE_SIZE - 1)
    end_row = min(MAP_TILES_H - 1, rect.bottom // TILE_SIZE + 1)
    for r in range(start_row, end_row + 1):
        for c in range(start_col, end_col + 1):
            tile = GAME_MAP[r][c]
            if tile['collidable']:
                tile_rect = pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                if rect.colliderect(tile_rect):
                    return True
    return False


def landmark_at(rect):
    col = rect.centerx // TILE_SIZE
    row = rect.centery // TILE_SIZE
    tile = tile_at(col, row)
    return tile['landmark'] if tile else None


def random_open_spawn(road_only=False):
    """Find a random walkable/drivable tile far from the map edge."""
    for _ in range(200):
        c = random.randint(5, MAP_TILES_W - 6)
        r = random.randint(5, MAP_TILES_H - 6)
        tile = GAME_MAP[r][c]
        if road_only and tile['type'] != TILE_ROAD:
            continue
        if not road_only and tile['collidable']:
            continue
        return c * TILE_SIZE + TILE_SIZE // 2, r * TILE_SIZE + TILE_SIZE // 2
    return MAP_WIDTH // 2, MAP_HEIGHT // 2


# ============================================================
# Camera
# ============================================================
class Camera:
    def __init__(self):
        self.x = 0
        self.y = 0

    def center_on(self, rect):
        self.x = rect.centerx - SCREEN_WIDTH // 2
        self.y = rect.centery - SCREEN_HEIGHT // 2
        self.x = max(0, min(MAP_WIDTH - SCREEN_WIDTH, self.x))
        self.y = max(0, min(MAP_HEIGHT - SCREEN_HEIGHT, self.y))

    def apply(self, rect):
        return rect.move(-self.x, -self.y)

    def apply_pos(self, pos):
        return (pos[0] - self.x, pos[1] - self.y)

    def visible_tile_range(self):
        start_col = max(0, self.x // TILE_SIZE - 1)
        end_col = min(MAP_TILES_W, (self.x + SCREEN_WIDTH) // TILE_SIZE + 2)
        start_row = max(0, self.y // TILE_SIZE - 1)
        end_row = min(MAP_TILES_H, (self.y + SCREEN_HEIGHT) // TILE_SIZE + 2)
        return start_col, end_col, start_row, end_row


# ============================================================
# Entities
# ============================================================
class Car:
    """A drivable vehicle: physics-driven, steerable, cartoon-rendered."""

    def __init__(self, x, y, color=None):
        self.width, self.height = 34, 18
        self.rect = pygame.Rect(0, 0, self.width, self.height)
        self.rect.center = (x, y)
        self.color = color or random.choice(CAR_COLORS)
        self.angle = random.uniform(0, math.tau)
        self.velocity = 0.0
        self.steer_angle = 0.0
        self.max_speed = 9.5
        self.acceleration = 0.28
        self.brake_force = 0.5
        self.drag = 0.965
        self.max_steer = 0.045
        self.input_throttle = 0.0
        self.input_steer = 0.0
        self.driver = None  # 'player', 'police', or None (parked/wandering)
        self.wander_dir = random.choice([0, 1, 2, 3])

    def move_forward_check(self, dx, dy):
        temp = self.rect.move(int(dx), int(dy))
        if is_blocked(temp) or not (0 <= temp.left and temp.right <= MAP_WIDTH
                                     and 0 <= temp.top and temp.bottom <= MAP_HEIGHT):
            return False
        self.rect.topleft = temp.topleft
        return True

    def physics_step(self):
        if self.input_throttle > 0:
            self.velocity += self.acceleration * self.input_throttle
        elif self.input_throttle < 0:
            self.velocity += self.brake_force * self.input_throttle
        self.velocity = max(-self.max_speed / 2, min(self.max_speed, self.velocity))

        if self.input_throttle == 0:
            self.velocity *= self.drag
            if abs(self.velocity) < 0.02:
                self.velocity = 0.0

        if abs(self.velocity) > 0.15:
            reverse = -1 if self.velocity < 0 else 1
            self.steer_angle += self.input_steer * self.max_steer * reverse
            self.steer_angle = max(-self.max_steer * 2.2, min(self.max_steer * 2.2, self.steer_angle))
            self.angle += self.steer_angle * (abs(self.velocity) / self.max_speed)
        if self.input_steer == 0:
            self.steer_angle *= 0.8

        dx = math.cos(self.angle) * self.velocity
        dy = math.sin(self.angle) * self.velocity
        if not self.move_forward_check(dx, dy):
            self.velocity *= -0.35
            return True  # collided
        return False

    def wander_ai(self):
        """Simple road-following traffic AI: drive straight, turn at intersections/dead ends."""
        self.input_throttle = 0.55
        self.input_steer = 0.0
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        dx, dy = directions[self.wander_dir]
        probe = self.rect.move(int(dx * TILE_SIZE * 0.8), int(dy * TILE_SIZE * 0.8))
        target_angle = math.atan2(dy, dx)
        if is_blocked(probe) or random.random() < 0.003:
            choices = [i for i, (ddx, ddy) in enumerate(directions)
                       if not is_blocked(self.rect.move(int(ddx * TILE_SIZE * 0.8), int(ddy * TILE_SIZE * 0.8)))]
            if choices:
                self.wander_dir = random.choice(choices)
                dx, dy = directions[self.wander_dir]
                target_angle = math.atan2(dy, dx)
        diff = (target_angle - self.angle + math.pi) % math.tau - math.pi
        self.input_steer = max(-1, min(1, diff * 2))
        self.physics_step()

    def chase_ai(self, target_pos):
        tx, ty = target_pos
        dx, dy = tx - self.rect.centerx, ty - self.rect.centery
        target_angle = math.atan2(dy, dx)
        diff = (target_angle - self.angle + math.pi) % math.tau - math.pi
        self.input_steer = max(-1, min(1, diff * 2.2))
        dist = math.hypot(dx, dy)
        self.input_throttle = 1.0 if dist > 40 else 0.0
        self.max_speed = 8.0
        self.physics_step()

    def draw(self, screen, camera):
        screen_pos = camera.apply_pos(self.rect.center)
        if not (-60 < screen_pos[0] < SCREEN_WIDTH + 60 and -60 < screen_pos[1] < SCREEN_HEIGHT + 60):
            return
        body = pygame.Surface((self.width + 4, self.height + 4), pygame.SRCALPHA)
        pygame.draw.rect(body, COLOR_OUTLINE, (0, 0, self.width + 4, self.height + 4), border_radius=7)
        pygame.draw.rect(body, self.color, (2, 2, self.width, self.height), border_radius=6)
        pygame.draw.rect(body, (210, 235, 250), (self.width * 0.55, 3, self.width * 0.35, self.height - 6), border_radius=3)
        rotated = pygame.transform.rotate(body, -math.degrees(self.angle))
        rect = rotated.get_rect(center=screen_pos)
        screen.blit(rotated, rect)
        if self.driver == 'police':
            flash = (255, 40, 40) if (pygame.time.get_ticks() // 200) % 2 == 0 else (60, 90, 255)
            pygame.draw.circle(screen, flash, (int(screen_pos[0]), int(screen_pos[1])), 4)


class Pedestrian:
    def __init__(self, x, y):
        self.rect = pygame.Rect(0, 0, 14, 14)
        self.rect.center = (x, y)
        self.color = random.choice([(250, 220, 130), (140, 200, 240), (240, 150, 200), (180, 230, 150)])
        self.dir = [random.choice([-1, 0, 1]), random.choice([-1, 0, 1])]
        self.speed = 0.8
        self.retarget_timer = 0
        self.bump_cooldown = 0

    def update(self):
        self.retarget_timer -= 1
        if self.retarget_timer <= 0:
            self.dir = [random.choice([-1, 0, 1]), random.choice([-1, 0, 1])]
            self.retarget_timer = random.randint(60, 180)
        if self.bump_cooldown > 0:
            self.bump_cooldown -= 1
        dx, dy = self.dir[0] * self.speed, self.dir[1] * self.speed
        temp = self.rect.move(int(dx), int(dy))
        if is_blocked(temp):
            self.dir = [random.choice([-1, 0, 1]), random.choice([-1, 0, 1])]
        else:
            self.rect.topleft = temp.topleft

    def draw(self, screen, camera):
        pos = camera.apply_pos(self.rect.center)
        if not (-20 < pos[0] < SCREEN_WIDTH + 20 and -20 < pos[1] < SCREEN_HEIGHT + 20):
            return
        pygame.draw.circle(screen, COLOR_OUTLINE, (int(pos[0]), int(pos[1])), 8)
        pygame.draw.circle(screen, self.color, (int(pos[0]), int(pos[1])), 6)
        pygame.draw.circle(screen, (255, 224, 189), (int(pos[0]), int(pos[1] - 6)), 4)


class Toast:
    def __init__(self, text, ms=2400):
        self.text = text
        self.expires = pygame.time.get_ticks() + ms


# ============================================================
# Game
# ============================================================
class Game:
    def __init__(self):
        pygame.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("STL-GTA: St. Louis Sandbox")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont('arial', 18, bold=True)
        self.font_small = pygame.font.SysFont('arial', 13, bold=True)
        self.font_big = pygame.font.SysFont('arial', 26, bold=True)

        self.camera = Camera()
        px, py = random_open_spawn()
        self.player_rect = pygame.Rect(0, 0, PLAYER_SIZE, PLAYER_SIZE)
        self.player_rect.center = (px, py)
        self.player_dir = [0, 0]
        self.driving = None  # Car instance the player is currently driving, or None

        self.cars = []
        for _ in range(16):
            cx, cy = random_open_spawn(road_only=True)
            self.cars.append(Car(cx, cy))

        self.pedestrians = []
        for _ in range(24):
            px2, py2 = random_open_spawn()
            self.pedestrians.append(Pedestrian(px2, py2))

        station_x = POLICE_STATION_TILE[0] * TILE_SIZE
        station_y = POLICE_STATION_TILE[1] * TILE_SIZE
        self.police_station = (station_x, station_y)
        self.police = []

        self.wanted_level = 0
        self.score = 0
        self.discovered = set()
        self.toasts = []
        self.infraction_cooldown = 0
        self.wanted_decay_timer = 0
        self.busted_flash = 0
        self.running = True

    # ---------------- persistence ----------------
    def save_game(self):
        state = {
            'player': {'x': self.player_rect.centerx, 'y': self.player_rect.centery},
            'score': self.score,
            'wanted_level': self.wanted_level,
            'discovered': list(self.discovered),
        }
        try:
            with open("savegame.json", 'w') as f:
                json.dump(state, f)
            self.add_toast("Game saved")
        except OSError as e:
            self.add_toast(f"Save failed: {e}")

    def load_game(self):
        if not os.path.exists("savegame.json"):
            self.add_toast("No save file found")
            return
        try:
            with open("savegame.json", 'r') as f:
                state = json.load(f)
            self.player_rect.center = (state['player']['x'], state['player']['y'])
            self.score = state.get('score', 0)
            self.wanted_level = state.get('wanted_level', 0)
            self.discovered = set(state.get('discovered', []))
            self.add_toast("Game loaded")
        except (OSError, json.JSONDecodeError, KeyError) as e:
            self.add_toast(f"Load failed: {e}")

    # ---------------- helpers ----------------
    def add_toast(self, text):
        self.toasts.append(Toast(text))

    def active_rect(self):
        return self.driving.rect if self.driving else self.player_rect

    # ---------------- input ----------------
    def handle_events(self):
        keys = pygame.key.get_pressed()

        if self.driving:
            throttle = 0.0
            if keys[pygame.K_w] or keys[pygame.K_UP]:
                throttle += 1.0
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:
                throttle -= 1.0
            steer = 0.0
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                steer -= 1.0
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                steer += 1.0
            self.driving.input_throttle = throttle
            self.driving.input_steer = steer
        else:
            dx = dy = 0
            if keys[pygame.K_w] or keys[pygame.K_UP]:
                dy -= 1
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:
                dy += 1
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                dx -= 1
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                dx += 1
            if dx and dy:
                dx *= 0.707
                dy *= 0.707
            self.player_dir = [dx, dy]

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    self.running = False
                elif event.key == pygame.K_e:
                    self.toggle_enter_exit()
                elif event.key == pygame.K_F5:
                    self.save_game()
                elif event.key == pygame.K_F9:
                    self.load_game()

    def toggle_enter_exit(self):
        if self.driving:
            self.driving.driver = None
            exit_pos = (self.driving.rect.centerx - 40, self.driving.rect.centery)
            self.player_rect.center = exit_pos
            self.driving = None
            return
        for car in self.cars:
            if car.driver is None and car.rect.inflate(24, 24).colliderect(self.player_rect):
                car.driver = 'player'
                self.driving = car
                self.add_toast("Jacked a ride!")
                self.score += 20
                return

    # ---------------- update ----------------
    def update(self):
        if self.driving:
            collided = self.driving.physics_step()
            if collided:
                self.wanted_bump(0.15, cooldown_key='wall')
        else:
            dx = self.player_dir[0] * PLAYER_SPEED
            dy = self.player_dir[1] * PLAYER_SPEED
            temp = self.player_rect.move(int(dx), int(dy))
            if not is_blocked(temp):
                self.player_rect.topleft = temp.topleft

        self.camera.center_on(self.active_rect())

        for car in self.cars:
            if car.driver is None:
                car.wander_ai()

        for ped in self.pedestrians:
            ped.update()

        self.handle_collisions()
        self.update_police()
        self.update_wanted_decay()
        self.check_landmark_discovery()
        self.toasts = [t for t in self.toasts if pygame.time.get_ticks() < t.expires]
        if self.busted_flash > 0:
            self.busted_flash -= 1

    def wanted_bump(self, amount, cooldown_key):
        if self.infraction_cooldown <= 0:
            self.wanted_level = min(5, self.wanted_level + amount)
            self.infraction_cooldown = 45

    def handle_collisions(self):
        if self.infraction_cooldown > 0:
            self.infraction_cooldown -= 1
        if not self.driving:
            return
        for ped in self.pedestrians:
            if ped.bump_cooldown <= 0 and self.driving.rect.colliderect(ped.rect.inflate(6, 6)):
                ped.bump_cooldown = 90
                push = pygame.Vector2(ped.rect.centerx - self.driving.rect.centerx,
                                       ped.rect.centery - self.driving.rect.centery)
                if push.length() > 0:
                    push = push.normalize() * 24
                    ped.rect.move_ip(int(push.x), int(push.y))
                self.score += 5
                self.wanted_bump(1, 'pedestrian')
                self.add_toast("Yikes! +5")
        for car in self.cars:
            if car is self.driving or car.driver == 'player':
                continue
            if self.driving.rect.colliderect(car.rect):
                self.wanted_bump(0.5, 'traffic')

    def update_police(self):
        target_count = max(0, int(self.wanted_level))
        while len(self.police) < target_count:
            px, py = self.police_station
            cop = Car(px + random.randint(-40, 40), py + random.randint(-40, 40), color=POLICE_COLOR)
            cop.driver = 'police'
            cop.max_speed = 8.0
            self.police.append(cop)
        while len(self.police) > target_count:
            self.police.pop()

        active = self.active_rect()
        for cop in self.police:
            cop.chase_ai(active.center)
            if cop.rect.colliderect(active) and self.busted_flash <= 0:
                self.busted()

    def busted(self):
        self.add_toast("BUSTED!")
        self.busted_flash = FPS * 2
        self.wanted_level = 0
        self.police = []
        if self.driving:
            self.driving.driver = None
            self.driving = None
        px, py = random_open_spawn()
        self.player_rect.center = (px, py)
        self.score = max(0, self.score - 50)

    def update_wanted_decay(self):
        if self.wanted_level <= 0:
            return
        self.wanted_decay_timer += 1
        if self.wanted_decay_timer > FPS * 6:
            self.wanted_decay_timer = 0
            self.wanted_level = max(0, self.wanted_level - 1)
            if self.wanted_level == 0:
                self.add_toast("Cops gave up chasing you")
                self.score += 100

    def check_landmark_discovery(self):
        name = landmark_at(self.active_rect())
        if name and name not in self.discovered:
            self.discovered.add(name)
            self.score += 150
            self.add_toast(f"Discovered: {name}!")

    # ---------------- drawing ----------------
    def draw_tile(self, c, r):
        tile = GAME_MAP[r][c]
        rect = self.camera.apply(pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE))
        pygame.draw.rect(self.screen, tile['color'], rect)

        if tile['type'] == TILE_ROAD:
            if (c % 8) not in (3, 4, 5):
                pygame.draw.line(self.screen, COLOR_ROAD_LINE, (rect.centerx, rect.top), (rect.centerx, rect.bottom), 2)
            if (r % 8) not in (3, 4, 5):
                pygame.draw.line(self.screen, COLOR_ROAD_LINE, (rect.left, rect.centery), (rect.right, rect.centery), 2)
        elif tile['type'] == TILE_WATER:
            pygame.draw.line(self.screen, COLOR_WATER_LINE, (rect.left, rect.centery), (rect.right, rect.centery), 1)
        elif tile['type'] == TILE_PARK:
            if (c * 7 + r * 13) % 11 == 0:
                pygame.draw.circle(self.screen, COLOR_PARK_TREE, rect.center, TILE_SIZE // 3)
        elif tile['type'] == TILE_BUILDING:
            pygame.draw.rect(self.screen, COLOR_OUTLINE, rect, 1)

    def draw(self):
        self.screen.fill(COLOR_SKY_BG)
        start_col, end_col, start_row, end_row = self.camera.visible_tile_range()
        for r in range(start_row, end_row):
            for c in range(start_col, end_col):
                self.draw_tile(c, r)

        for (lx, ly, lw, lh, kind, name, color) in LANDMARKS:
            cx = (lx + lw / 2) * TILE_SIZE
            cy = (ly + lh / 2) * TILE_SIZE
            sx, sy = self.camera.apply_pos((cx, cy))
            if -50 < sx < SCREEN_WIDTH + 50 and -50 < sy < SCREEN_HEIGHT + 50:
                label = self.font_small.render(name, True, (255, 255, 255))
                shadow = self.font_small.render(name, True, (0, 0, 0))
                r = label.get_rect(center=(sx, sy))
                self.screen.blit(shadow, r.move(1, 1))
                self.screen.blit(label, r)

        for ped in self.pedestrians:
            ped.draw(self.screen, self.camera)
        for car in self.cars:
            if car is not self.driving:
                car.draw(self.screen, self.camera)
        for cop in self.police:
            cop.draw(self.screen, self.camera)

        if self.driving:
            self.driving.draw(self.screen, self.camera)
        else:
            ppos = self.camera.apply_pos(self.player_rect.center)
            pygame.draw.circle(self.screen, COLOR_OUTLINE, (int(ppos[0]), int(ppos[1])), PLAYER_SIZE // 2 + 2)
            pygame.draw.circle(self.screen, PLAYER_COLOR, (int(ppos[0]), int(ppos[1])), PLAYER_SIZE // 2)

        self.draw_hud()
        if self.busted_flash > FPS:
            flash_surf = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            flash_surf.fill((255, 0, 0, 60))
            self.screen.blit(flash_surf, (0, 0))
            text = self.font_big.render("BUSTED!", True, (255, 255, 255))
            self.screen.blit(text, text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)))

        pygame.display.flip()

    def draw_hud(self):
        mode = "DRIVING" if self.driving else "ON FOOT"
        self.screen.blit(self.font.render(f"STL-GTA   Score: {self.score}   [{mode}]", True, (255, 255, 255)), (12, 10))

        stars = "★" * int(self.wanted_level) + "☆" * (5 - int(self.wanted_level))
        star_color = (255, 220, 40) if self.wanted_level > 0 else (200, 200, 200)
        self.screen.blit(self.font.render(stars, True, star_color), (12, 36))

        # Minimap
        mm_size = 160
        mm_x, mm_y = SCREEN_WIDTH - mm_size - 12, 12
        pygame.draw.rect(self.screen, (20, 18, 30), (mm_x, mm_y, mm_size, mm_size))
        scale = mm_size / MAP_WIDTH
        step = max(1, MAP_TILES_W // 40)
        for r in range(0, MAP_TILES_H, step):
            for c in range(0, MAP_TILES_W, step):
                tile = GAME_MAP[r][c]
                mx = mm_x + c * TILE_SIZE * scale
                my = mm_y + r * TILE_SIZE * scale
                size = max(1, step * TILE_SIZE * scale)
                self.screen.fill(tile['color'], (mx, my, size, size))
        active = self.active_rect()
        px = mm_x + active.centerx * scale
        py = mm_y + active.centery * scale
        pygame.draw.circle(self.screen, PLAYER_COLOR, (int(px), int(py)), 3)
        pygame.draw.rect(self.screen, (255, 255, 255), (mm_x, mm_y, mm_size, mm_size), 1)

        # Toasts
        for i, toast in enumerate(reversed(self.toasts[-3:])):
            text = self.font.render(toast.text, True, (255, 255, 255))
            bg = pygame.Surface((text.get_width() + 16, text.get_height() + 8), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 150))
            y = SCREEN_HEIGHT - 50 - i * 34
            self.screen.blit(bg, (12, y))
            self.screen.blit(text, (20, y + 4))

    # ---------------- main loop ----------------
    def run(self):
        print("=" * 60)
        print("  STL-GTA: St. Louis Open-World Sandbox")
        print("=" * 60)
        print("  WASD / Arrows - Move or Drive")
        print("  E             - Enter / Exit Vehicle")
        print("  F5 / F9       - Save / Load")
        print("  ESC / Q       - Quit")
        print(f"  Explore {len(LANDMARKS)} St. Louis landmarks. Reckless driving raises your wanted level!")
        print("=" * 60)

        while self.running:
            self.handle_events()
            if not self.running:
                break
            self.update()
            self.draw()
            self.clock.tick(FPS)

        pygame.quit()


def main():
    Game().run()


if __name__ == "__main__":
    main()

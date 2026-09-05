import pygame
import sys
import os
import pickle
import math

# --- Game Constants & Dimensions ---
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60

# Player dimensions
PLAYER_SIZE = 50
PLAYER_SPEED = 5

# Tile Types
TILE_TYPE_ROAD = 1
TILE_TYPE_WATER = 2
TILE_TYPE_BUILDING = 3
TILE_TYPE_DEFAULT = 0

# Colors
COLOR_ROAD = (150, 150, 80)
COLOR_WATER = (30, 100, 200)
COLOR_BUILDING = (100, 100, 150)
COLOR_DEFAULT = (80, 150, 80)
COLOR_GRASS = (60, 120, 60)

# Map dimensions (in tiles)
MAP_TILES_WIDTH = 100
MAP_TILES_HEIGHT = 100
TILE_SIZE = 64
MAP_WIDTH = MAP_TILES_WIDTH * TILE_SIZE
MAP_HEIGHT = MAP_TILES_HEIGHT * TILE_SIZE

# --- St. Louis Landmark Definitions ---
# Each landmark is (x_tile, y_tile, width_tiles, height_tiles, tile_type, label)
LANDMARKS = [
    # Gateway Arch area (downtown)
    (12, 8, 4, 6, TILE_TYPE_BUILDING, "Gateway Arch District"),
    # Forest Park area
    (30, 15, 15, 10, TILE_TYPE_BUILDING, "Forest Park"),
    # Downtown core
    (10, 6, 8, 4, TILE_TYPE_BUILDING, "Downtown St. Louis"),
    # The Hill (Italian district)
    (20, 12, 5, 3, TILE_TYPE_BUILDING, "The Hill"),
    # Central West End
    (25, 8, 6, 4, TILE_TYPE_BUILDING, "Central West End"),
    # Soulard district
    (15, 18, 7, 4, TILE_TYPE_BUILDING, "Soulard"),
    # University area
    (40, 20, 8, 6, TILE_TYPE_BUILDING, "University Area"),
    # Midtown
    (35, 12, 6, 5, TILE_TYPE_BUILDING, "Midtown"),
]

# --- Initialize the map structure ---
game_map = []
for y in range(MAP_TILES_HEIGHT):
    row = []
    for x in range(MAP_TILES_WIDTH):
        tile_type = TILE_TYPE_DEFAULT
        collidable = False
        
        # Check if this tile is part of a landmark
        is_landmark = False
        for (lx, ly, lw, lh, ltype, label) in LANDMARKS:
            if lx <= x < lx + lw and ly <= y < ly + lh:
                tile_type = ltype
                collidable = True
                is_landmark = True
                break
        
        # Simulate major roads (horizontal and vertical)
        if not is_landmark:
            # Main horizontal roads
            if y in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]:
                tile_type = TILE_TYPE_ROAD
            # Main vertical roads
            elif x in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]:
                tile_type = TILE_TYPE_ROAD
            # Mississippi River (east side)
            elif x >= MAP_TILES_WIDTH - 3:
                tile_type = TILE_TYPE_WATER
                collidable = True
            # Missouri River (north)
            elif y <= 2:
                tile_type = TILE_TYPE_WATER
                collidable = True
            # Parks/grass areas
            elif (x >= 28 and x <= 48 and y >= 13 and y <= 28):
                tile_type = TILE_TYPE_DEFAULT  # Forest Park grass
            else:
                tile_type = TILE_TYPE_DEFAULT
    
        row.append({'type': tile_type, 'collidable': collidable, 'label': ''})
    game_map.append(row)

# --- Vehicle Representation ---
class Vehicle:
    def __init__(self, x, y, width, height):
        self.rect = pygame.Rect(x, y, width, height)
        self.max_speed = 12.0
        self.acceleration = 0.3
        self.brake_force = 0.5
        self.drag_coefficient = 0.97
        self.steer_angle = 0.0
        self.max_steer = 0.04  # radians per frame
        self.current_velocity = 0.0
        self.angle = 0.0  # facing direction in radians
        self.input = {'throttle': 0.0, 'steer': 0.0}
    
    def update(self, dt):
        # Apply throttle/brake
        if self.input['throttle'] > 0:
            self.current_velocity += self.acceleration * self.input['throttle']
        elif self.input['throttle'] < 0:
            self.current_velocity += self.brake_force * self.input['throttle']
        
        # Clamp speed
        self.current_velocity = max(-self.max_speed / 2, min(self.max_speed, self.current_velocity))
        
        # Apply drag when no input
        if self.input['throttle'] == 0:
            self.current_velocity *= self.drag_coefficient
            if abs(self.current_velocity) < 0.01:
                self.current_velocity = 0.0
        
        # Apply steering (only when moving)
        if abs(self.current_velocity) > 0.1:
            reverse = -1 if self.current_velocity < 0 else 1
            self.steer_angle += self.input['steer'] * self.max_steer * reverse
            self.steer_angle = max(-self.max_steer * 2, min(self.max_steer * 2, self.steer_angle))
            self.angle += self.steer_angle * (self.current_velocity / self.max_speed)
        
        # Reset steer when no input
        if self.input['steer'] == 0:
            self.steer_angle *= 0.8
            if abs(self.steer_angle) < 0.001:
                self.steer_angle = 0.0
        
        # Calculate movement vector from angle
        dx = math.cos(self.angle) * self.current_velocity
        dy = math.sin(self.angle) * self.current_velocity
        
        # Check collision
        temp_rect = self.rect.move(int(dx), int(dy))
        if self._check_collision(temp_rect):
            self.current_velocity *= -0.5  # Bounce back
        else:
            self.rect.topleft = (int(temp_rect.left), int(temp_rect.top))
    
    def _check_collision(self, rect):
        x1, y1 = int(rect.left), int(rect.top)
        x2, y2 = int(rect.right), int(rect.bottom)
        
        start_col = max(0, x1 // TILE_SIZE - 1)
        end_col = min(MAP_TILES_WIDTH - 1, x2 // TILE_SIZE + 1)
        start_row = max(0, y1 // TILE_SIZE - 1)
        end_row = min(MAP_TILES_HEIGHT - 1, y2 // TILE_SIZE + 1)
        
        for r in range(start_row, end_row + 1):
            if r >= len(game_map):
                continue
            row = game_map[r]
            for c in range(start_col, end_col + 1):
                if c >= len(row):
                    continue
                tile = row[c]
                if tile.get('collidable', False):
                    tile_rect = pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                    if rect.colliderect(tile_rect):
                        return True
        return False
    
    def draw(self, screen):
        # Draw car rotated
        center = self.rect.center
        rect = pygame.Rect(0, 0, self.rect.width, self.rect.height)
        rect.center = center
        rotated_surface = pygame.transform.rotate(
            pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA),
            math.degrees(-self.angle)
        )
        rotated_surface.fill((0, 100, 200, 200))
        rotated_surface.blit(
            pygame.Surface((self.rect.width, 10), pygame.SRCALPHA),
            (0, self.rect.height // 2 - 5),
            special_flags=pygame.BLEND_RGBA_ADD
        )
        screen.blit(rotated_surface, rotated_surface.get_rect(center=center))
        
        # Draw headlights
        headlight_offset = math.cos(self.angle) * self.rect.width // 2
        headlight_dy = math.sin(self.angle) * self.rect.width // 2
        hl1 = (center[0] + headlight_offset - 10, center[1] + headlight_dy)
        hl2 = (center[0] + headlight_offset + 10, center[1] + headlight_dy)
        pygame.draw.circle(screen, (255, 255, 200), (int(hl1[0]), int(hl1[1])), 3)
        pygame.draw.circle(screen, (255, 255, 200), (int(hl2[0]), int(hl2[1])), 3)


# --- Player Representation ---
class Player:
    def __init__(self, x, y, size):
        self.rect = pygame.Rect(x, y, size, size)
        self.speed = PLAYER_SPEED
        self.direction = [0, 0]
        self.health = 100
        self.wanted_level = 0
    
    def update(self):
        dx = self.direction[0] * self.speed
        dy = self.direction[1] * self.speed
        
        temp_rect = self.rect.move(int(dx), int(dy))
        if self._check_collision(temp_rect):
            return
        self.rect.topleft = (int(temp_rect.left), int(temp_rect.top))
    
    def _check_collision(self, rect):
        x1, y1 = int(rect.left), int(rect.top)
        x2, y2 = int(rect.right), int(rect.bottom)
        
        start_col = max(0, x1 // TILE_SIZE - 1)
        end_col = min(MAP_TILES_WIDTH - 1, x2 // TILE_SIZE + 1)
        start_row = max(0, y1 // TILE_SIZE - 1)
        end_row = min(MAP_TILES_HEIGHT - 1, y2 // TILE_SIZE + 1)
        
        for r in range(start_row, end_row + 1):
            if r >= len(game_map):
                continue
            row = game_map[r]
            for c in range(start_col, end_col + 1):
                if c >= len(row):
                    continue
                tile = row[c]
                if tile.get('collidable', False):
                    tile_rect = pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                    if rect.colliderect(tile_rect):
                        return True
        return False


# --- Global game state ---
player = Player(SCREEN_WIDTH // 2 - PLAYER_SIZE // 2, SCREEN_HEIGHT // 2 - PLAYER_SIZE // 2, PLAYER_SIZE)
vehicle = Vehicle(SCREEN_WIDTH // 2 + 100, SCREEN_HEIGHT // 2, 70, 40)
GAME_STATE_MODE = 'PLAYER'  # 'PLAYER' or 'VEHICLE'
running = True

# Camera
camera = {'x': 0, 'y': 0}

# --- Persistence ---
SAVE_FILE = "savegame.dat"

def save_game():
    state = {
        'player': {'x': player.rect.left, 'y': player.rect.top},
        'vehicle': {'x': vehicle.rect.left, 'y': vehicle.rect.top, 'angle': vehicle.angle},
        'mode': GAME_STATE_MODE,
    }
    try:
        with open(SAVE_FILE, 'wb') as f:
            pickle.dump(state, f)
        print(f"Game saved to {os.path.abspath(SAVE_FILE)}")
    except Exception as e:
        print(f"Error saving: {e}")

def load_game():
    if not os.path.exists(SAVE_FILE):
        print("No save file found!")
        return
    try:
        with open(SAVE_FILE, 'rb') as f:
            state = pickle.load(f)
        player.rect.topleft = (int(state['player']['x']), int(state['player']['y']))
        vehicle.rect.topleft = (int(state['vehicle']['x']), int(state['vehicle']['y']))
        vehicle.angle = state['vehicle']['angle']
        GAME_STATE_MODE = state.get('mode', 'PLAYER')
        print("Game loaded!")
    except Exception as e:
        print(f"Error loading: {e}")


# --- Drawing Functions ---
def draw_tile(screen, c, r):
    """Draw a single tile at grid position (c, r)."""
    tile = game_map[r][c]
    x = c * TILE_SIZE
    y = r * TILE_SIZE
    
    if tile['type'] == TILE_TYPE_WATER:
        color = COLOR_WATER
    elif tile['type'] == TILE_TYPE_BUILDING:
        color = COLOR_BUILDING
    elif tile['type'] == TILE_TYPE_ROAD:
        color = COLOR_ROAD
    else:
        color = COLOR_GRASS
    
    pygame.draw.rect(screen, color, (x, y, TILE_SIZE, TILE_SIZE))
    
    # Grid lines for visual clarity
    pygame.draw.rect(screen, (0, 0, 0, 30), (x, y, TILE_SIZE, TILE_SIZE), 1)


def draw_background(screen):
    """Fill screen with base color."""
    screen.fill((50, 50, 100))


def draw_game(screen):
    """Draw all game elements."""
    draw_background(screen)
    
    # Calculate visible tile range based on camera
    start_col = max(0, camera['x'] // TILE_SIZE - 1)
    end_col = min(MAP_TILES_WIDTH, (camera['x'] + SCREEN_WIDTH) // TILE_SIZE + 2)
    start_row = max(0, camera['y'] // TILE_SIZE - 1)
    end_row = min(MAP_TILES_HEIGHT, (camera['y'] + SCREEN_HEIGHT) // TILE_SIZE + 2)
    
    # Draw visible tiles
    for r in range(start_row, end_row):
        for c in range(start_col, end_col):
            draw_tile(screen, c, r)
    
    # Draw landmark labels
    pygame.font.init()
    font = pygame.font.SysFont('arial', 14, bold=True)
    for (lx, ly, lw, lh, ltype, label) in LANDMARKS:
        center_x = (lx + lw / 2) * TILE_SIZE - camera['x']
        center_y = (ly + lh / 2) * TILE_SIZE - camera['y']
        if 0 < center_x < SCREEN_WIDTH and 0 < center_y < SCREEN_HEIGHT:
            text = font.render(label, True, (255, 255, 255))
            text_rect = text.get_rect(center=(center_x, center_y))
            screen.blit(text, text_rect)
    
    # Draw player or vehicle
    if GAME_STATE_MODE == 'PLAYER':
        pygame.draw.rect(screen, (255, 50, 50), player.rect)
        # Direction indicator
        if player.direction[0] != 0 or player.direction[1] != 0:
            dx = player.direction[0] * 20
            dy = player.direction[1] * 20
            pygame.draw.line(screen, (255, 255, 0), player.rect.center, 
                           (player.rect.center[0] + dx, player.rect.center[1] + dy), 3)
    else:
        vehicle.draw(screen)
    
    # HUD
    pygame.font.init()
    hud_font = pygame.font.SysFont('arial', 18, bold=True)
    
    mode_text = hud_font.render(f"Mode: {GAME_STATE_MODE}", True, (255, 255, 255))
    screen.blit(mode_text, (10, 10))
    
    pos_text = hud_font.render(f"Pos: ({player.rect.centerx}, {player.rect.centery})", True, (200, 200, 200))
    screen.blit(pos_text, (10, 35))
    
    # Minimap
    minimap_size = 150
    minimap_x = SCREEN_WIDTH - minimap_size - 10
    minimap_y = 10
    pygame.draw.rect(screen, (0, 0, 0, 150), (minimap_x, minimap_y, minimap_size, minimap_size))
    
    scale_x = minimap_size / MAP_WIDTH
    scale_y = minimap_size / MAP_HEIGHT
    
    # Draw minimap tiles (simplified)
    step = max(1, MAP_TILES_WIDTH // 30)
    for r in range(0, MAP_TILES_HEIGHT, step):
        for c in range(0, MAP_TILES_WIDTH, step):
            tile = game_map[r][c]
            if tile['type'] == TILE_TYPE_BUILDING:
                color = (100, 100, 150)
            elif tile['type'] == TILE_TYPE_ROAD:
                color = (150, 150, 80)
            elif tile['type'] == TILE_TYPE_WATER:
                color = (30, 100, 200)
            else:
                color = (60, 120, 60)
            mx = minimap_x + c * MAP_TILES_WIDTH * scale_x
            my = minimap_y + r * MAP_TILES_HEIGHT * scale_y
            pygame.draw.rect(screen, color, (mx, my, max(1, step * MAP_TILES_WIDTH * scale_x), max(1, step * MAP_TILES_HEIGHT * scale_y)))
    
    # Player dot on minimap
    px = minimap_x + player.rect.centerx * scale_x
    py = minimap_y + player.rect.centery * scale_y
    pygame.draw.circle(screen, (255, 0, 0), (int(px), int(py)), 3)
    
    pygame.display.flip()


# --- Input Handling ---
def handle_events():
    global running, GAME_STATE_MODE
    
    keys = pygame.key.get_pressed()
    
    # Reset direction
    player.direction = [0, 0]
    
    # Player movement
    if keys[pygame.K_w] or keys[pygame.K_UP]:
        player.direction[1] -= 1
    if keys[pygame.K_s] or keys[pygame.K_DOWN]:
        player.direction[1] += 1
    if keys[pygame.K_a] or keys[pygame.K_LEFT]:
        player.direction[0] -= 1
    if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
        player.direction[0] += 1
    
    # Normalize diagonal movement
    if player.direction[0] != 0 and player.direction[1] != 0:
        player.direction[0] *= 0.707
        player.direction[1] *= 0.707
    
    # Vehicle input
    vehicle.input = {'throttle': 0.0, 'steer': 0.0}
    if keys[pygame.K_w]:
        vehicle.input['throttle'] += 1.0
    if keys[pygame.K_s]:
        vehicle.input['throttle'] -= 1.0
    if keys[pygame.K_a]:
        vehicle.input['steer'] -= 1.0
    if keys[pygame.K_d]:
        vehicle.input['steer'] += 1.0
    
    # State transition
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_e:
                if GAME_STATE_MODE == 'PLAYER':
                    GAME_STATE_MODE = 'VEHICLE'
                    print("Entered vehicle!")
                else:
                    GAME_STATE_MODE = 'PLAYER'
                    print("Exited vehicle!")
            elif event.key == pygame.K_F5:
                save_game()
            elif event.key == pygame.K_F9:
                load_game()


# --- Game Update ---
def update_game():
    if GAME_STATE_MODE == 'PLAYER':
        player.update()
    else:
        vehicle.update(1.0 / FPS)
    
    # Update camera to follow active entity
    if GAME_STATE_MODE == 'PLAYER':
        camera['x'] = player.rect.centerx - SCREEN_WIDTH // 2
        camera['y'] = player.rect.centery - SCREEN_HEIGHT // 2
    else:
        camera['x'] = vehicle.rect.centerx - SCREEN_WIDTH // 2
        camera['y'] = vehicle.rect.centery - SCREEN_HEIGHT // 2
    
    # Clamp camera to map bounds
    camera['x'] = max(0, min(MAP_WIDTH - SCREEN_WIDTH, camera['x']))
    camera['y'] = max(0, min(MAP_HEIGHT - SCREEN_HEIGHT, camera['y']))


# --- Main Game Loop ---
def main():
    global running, screen
    
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("St. Louis GTA Clone")
    clock = pygame.time.Clock()
    
    print("=" * 60)
    print("  STL-GTA: St. Louis Open-World Sandbox")
    print("=" * 60)
    print("  WASD/Arrows - Move")
    print("  E - Enter/Exit Vehicle")
    print("  F5 - Save Game")
    print("  F9 - Load Game")
    print("  ESC/Q - Quit")
    print("=" * 60)
    print()
    
    while running:
        handle_events()
        if not running:
            break
        update_game()
        draw_game(screen)
        clock.tick(FPS)
    
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()

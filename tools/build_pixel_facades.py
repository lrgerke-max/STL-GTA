"""Build the native-resolution St. Louis neighborhood building atlas.

The sheet is intentionally drawn at its final size.  Keep this generator free
of image transforms and antialiased primitives: the game renders at 640x360,
so every pixel in these 64px tiles needs to be deliberate.

``BUILDING_ATLAS_CELLS`` is the public row-major contract for consumers.  The
first item is the hood key used by ``main.py``; the second is a descriptive
variant key for artists and tests.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame


CELL_SIZE = 64
ATLAS_COLUMNS = 6
ATLAS_ROWS = 4
ATLAS_SIZE = (CELL_SIZE * ATLAS_COLUMNS, CELL_SIZE * ATLAS_ROWS)

# Row-major, left-to-right and top-to-bottom.  There are two base variants for
# each of the game's eleven hood keys, followed by a downtown tower and a
# riverfront warehouse (both intentionally routed through ``downtown``).
BUILDING_ATLAS_CELLS = (
    ("soulard", "joined_rowhouses"),
    ("soulard", "corner_tavern"),
    ("hill", "hip_roof_bungalow"),
    ("hill", "shotgun_and_garage"),
    ("cwe", "mansard_townhouse"),
    ("cwe", "limestone_mansion"),
    ("loop", "narrow_shop"),
    ("loop", "barrel_roof_cinema"),
    ("grand", "theater_stagehouse"),
    ("grand", "arts_deco_hall"),
    ("grove", "sawtooth_workshop"),
    ("grove", "nightlife_storefront"),
    ("cherokee", "market_row"),
    ("cherokee", "awning_shops"),
    ("north", "weathered_four_square"),
    ("north", "corner_church"),
    ("south", "two_family_flat"),
    ("south", "porch_bungalow"),
    ("downtown", "brick_warehouse"),
    ("downtown", "parking_garage"),
    ("west", "tudor_house"),
    ("west", "courtyard_apartments"),
    ("downtown", "tower_roof"),
    ("downtown", "riverfront_sawtooth"),
)
BUILDING_ATLAS_HOODS = tuple(hood for hood, _variant in BUILDING_ATLAS_CELLS)

# Compact shared palette, close to main.py's muted brick, roof, glass, and
# outline colors.  Drawing code below uses no colors outside this table.
PALETTE = {
    "clear": (0, 0, 0, 0),
    "ink": (18, 16, 18, 255),
    "shadow": (24, 20, 22, 255),
    "wall": (46, 34, 34, 255),
    "brick": (156, 86, 66, 255),
    "brick_dark": (112, 58, 50, 255),
    "brick_light": (176, 106, 78, 255),
    "buff": (170, 132, 98, 255),
    "limestone": (176, 168, 150, 255),
    "concrete": (118, 112, 102, 255),
    "tar": (58, 58, 62, 255),
    "roof": (78, 74, 72, 255),
    "slate": (58, 60, 68, 255),
    "tile": (124, 88, 68, 255),
    "metal": (148, 150, 148, 255),
    "glass": (42, 54, 66, 255),
    "light": (206, 178, 116, 255),
    "green": (70, 96, 70, 255),
    "blue": (72, 92, 128, 255),
    "red": (150, 66, 58, 255),
    "gold": (170, 132, 70, 255),
    "purple": (110, 78, 120, 255),
}
P = PALETTE


def rect(surface, color, x, y, w, h, width=0):
    """Integer-only rectangle helper that quietly ignores empty geometry."""
    if w > 0 and h > 0:
        pygame.draw.rect(surface, P[color], (int(x), int(y), int(w), int(h)), width)


def poly(surface, color, points, width=0):
    pygame.draw.polygon(surface, P[color], [(int(x), int(y)) for x, y in points], width)


def line(surface, color, start, end, width=1):
    pygame.draw.line(surface, P[color], start, end, width)


def roof_block(surface, x, y, w, h, roof="tar", wall="brick", depth=5):
    """Draw the game's shallow southeast extrusion and return its roof rect."""
    rect(surface, "shadow", x + 4, y + 5, w, h)
    rect(surface, "wall", x + depth, y + depth, w, h)
    rect(surface, wall, x, y, w, h)
    rect(surface, roof, x, y, w - depth, h - depth)
    rect(surface, "ink", x, y, w - depth, h - depth, 1)
    return pygame.Rect(x, y, w - depth, h - depth)


def facade_strip(surface, x, y, w, h, wall="brick", bays=3, shop=False,
                 accent="limestone"):
    """Add the tiny south-facing wall that makes a roof read as a building."""
    rect(surface, wall, x, y, w, h)
    rect(surface, "ink", x, y, w, 1)
    bay_w = max(5, (w - 4) // bays)
    for index in range(bays):
        wx = x + 3 + index * bay_w
        if shop:
            rect(surface, "glass", wx, y + 3, max(3, bay_w - 3), h - 5)
            rect(surface, accent, wx, y + 2, max(3, bay_w - 3), 2)
        else:
            rect(surface, "ink", wx, y + 3, 4, max(3, h - 6))
            rect(surface, "glass" if index % 3 else "light", wx + 1, y + 4,
                 2, max(1, h - 8))


def hvac(surface, x, y, wide=False):
    w = 9 if wide else 6
    rect(surface, "shadow", x + 2, y + 2, w, 5)
    rect(surface, "metal", x, y, w, 5)
    rect(surface, "roof", x + 1, y + 1, w - 2, 1)
    line(surface, "ink", (x + 2, y + 3), (x + w - 2, y + 3))


def vent(surface, x, y):
    rect(surface, "shadow", x + 1, y + 2, 4, 4)
    rect(surface, "metal", x, y, 4, 4)
    rect(surface, "ink", x + 1, y + 1, 2, 2)


def chimney(surface, x, y):
    rect(surface, "shadow", x + 2, y + 2, 5, 6)
    rect(surface, "brick_dark", x, y, 5, 6)
    rect(surface, "limestone", x - 1, y, 7, 2)


def awning(surface, x, y, w, color):
    rect(surface, "ink", x - 1, y - 1, w + 2, 5)
    rect(surface, color, x, y, w, 3)
    for xx in range(x + 2, x + w - 1, 6):
        rect(surface, "limestone", xx, y, 2, 3)


def tree(surface, x, y):
    # Hard-edged circles are okay: pygame.draw.circle does not antialias.
    pygame.draw.circle(surface, P["shadow"], (x + 2, y + 2), 5)
    pygame.draw.circle(surface, P["green"], (x, y), 5)
    rect(surface, "limestone", x - 2, y - 2, 3, 2)


def draw_joined_rowhouses(s):
    for x, w, roof in ((4, 18, "tar"), (22, 18, "roof"), (40, 18, "tar")):
        roof_block(s, x, 11, w, 35, roof, "brick", 4)
        facade_strip(s, x, 42, w, 13, "brick", 2)
        rect(s, "limestone", x + 1, 40, w - 5, 2)
    chimney(s, 16, 12)
    chimney(s, 47, 12)
    rect(s, "green", 5, 56, 52, 3)


def draw_corner_tavern(s):
    roof_block(s, 5, 10, 53, 38, "tar", "brick_dark", 5)
    hvac(s, 16, 18, True)
    vent(s, 42, 29)
    facade_strip(s, 5, 43, 53, 14, "brick", 4, True, "green")
    awning(s, 8, 45, 42, "green")
    rect(s, "gold", 47, 48, 5, 5)


def draw_hip_roof_bungalow(s):
    rect(s, "shadow", 10, 17, 45, 35)
    rect(s, "brick_dark", 8, 15, 45, 35)
    poly(s, "tile", ((8, 23), (18, 10), (45, 10), (53, 23), (47, 43), (14, 43)))
    poly(s, "ink", ((8, 23), (18, 10), (45, 10), (53, 23), (47, 43), (14, 43)), 1)
    line(s, "brick_dark", (18, 10), (30, 28))
    line(s, "brick_dark", (45, 10), (30, 28))
    facade_strip(s, 14, 42, 33, 11, "brick", 2)
    rect(s, "limestone", 11, 52, 40, 4)
    chimney(s, 42, 14)


def draw_shotgun_and_garage(s):
    rect(s, "shadow", 7, 16, 31, 40)
    poly(s, "tile", ((6, 20), (21, 9), (37, 20), (34, 49), (9, 49)))
    poly(s, "ink", ((6, 20), (21, 9), (37, 20), (34, 49), (9, 49)), 1)
    line(s, "brick_dark", (21, 10), (21, 47))
    facade_strip(s, 9, 45, 25, 10, "buff", 2)
    roof_block(s, 41, 29, 17, 23, "roof", "brick", 3)
    rect(s, "metal", 44, 46, 11, 7)
    line(s, "ink", (44, 49), (55, 49))


def draw_mansard_townhouse(s):
    roof_block(s, 7, 12, 50, 34, "slate", "limestone", 5)
    rect(s, "roof", 10, 16, 42, 24)
    for x in (15, 29, 43):
        poly(s, "limestone", ((x, 27), (x + 5, 21), (x + 10, 27)))
        rect(s, "glass", x + 3, 26, 4, 5)
    facade_strip(s, 7, 41, 50, 16, "limestone", 4)
    rect(s, "brick_dark", 29, 47, 7, 10)


def draw_limestone_mansion(s):
    roof_block(s, 8, 13, 48, 36, "slate", "limestone", 5)
    poly(s, "roof", ((11, 29), (21, 16), (42, 16), (53, 29), (49, 43), (15, 43)))
    poly(s, "ink", ((11, 29), (21, 16), (42, 16), (53, 29), (49, 43), (15, 43)), 1)
    rect(s, "limestone", 24, 33, 16, 21)
    rect(s, "glass", 29, 38, 6, 9)
    tree(s, 7, 48)
    tree(s, 57, 48)


def draw_narrow_shop(s):
    roof_block(s, 6, 12, 52, 36, "tar", "brick", 5)
    hvac(s, 13, 20)
    vent(s, 46, 27)
    facade_strip(s, 6, 43, 52, 14, "brick", 4, True, "blue")
    awning(s, 9, 45, 40, "blue")
    rect(s, "purple", 51, 44, 5, 12)


def draw_barrel_roof_cinema(s):
    rect(s, "shadow", 7, 14, 51, 40)
    rect(s, "brick_dark", 5, 12, 51, 40)
    for y, color in ((12, "limestone"), (15, "roof"), (19, "tar"), (23, "roof")):
        rect(s, color, 8 + (y - 12) // 2, y, 45 - (y - 12), 6)
    rect(s, "brick", 8, 29, 45, 24)
    rect(s, "ink", 8, 29, 45, 1)
    rect(s, "red", 12, 39, 37, 7)
    for x in range(14, 48, 6):
        rect(s, "light", x, 40, 2, 2)
    facade_strip(s, 12, 46, 37, 10, "brick_dark", 3, True, "gold")


def draw_theater_stagehouse(s):
    roof_block(s, 7, 9, 50, 42, "tar", "brick_dark", 5)
    roof_block(s, 16, 16, 32, 25, "roof", "brick", 4)
    hvac(s, 22, 21, True)
    vent(s, 40, 32)
    facade_strip(s, 7, 46, 50, 12, "brick", 4, True, "gold")
    rect(s, "gold", 14, 44, 36, 4)
    for x in range(16, 49, 6):
        rect(s, "light", x, 45, 2, 2)


def draw_arts_deco_hall(s):
    roof_block(s, 7, 13, 50, 37, "roof", "limestone", 5)
    rect(s, "tar", 13, 18, 38, 23)
    rect(s, "metal", 22, 22, 20, 3)
    facade_strip(s, 7, 45, 50, 13, "limestone", 5, True, "purple")
    rect(s, "gold", 28, 39, 8, 18)
    rect(s, "ink", 31, 40, 2, 16)


def draw_sawtooth_workshop(s):
    roof_block(s, 4, 12, 56, 40, "tar", "brick_dark", 4)
    for x in range(7, 52, 12):
        poly(s, "metal", ((x, 37), (x + 6, 16), (x + 11, 37)))
        poly(s, "glass", ((x + 3, 34), (x + 6, 21), (x + 9, 34)))
        line(s, "ink", (x, 37), (x + 11, 37))
    facade_strip(s, 4, 47, 56, 11, "brick_dark", 4)
    rect(s, "metal", 8, 50, 15, 8)


def draw_nightlife_storefront(s):
    roof_block(s, 6, 15, 52, 33, "tar", "brick", 5)
    hvac(s, 40, 21)
    facade_strip(s, 6, 43, 52, 14, "brick_dark", 4, True, "purple")
    for x, color in ((10, "red"), (22, "purple"), (34, "blue")):
        awning(s, x, 45, 10, color)
    rect(s, "light", 51, 46, 3, 7)


def draw_market_row(s):
    roof_block(s, 4, 14, 56, 34, "tar", "brick", 4)
    vent(s, 12, 23)
    vent(s, 47, 18)
    facade_strip(s, 4, 43, 56, 14, "brick", 4, True, "green")
    for x, color in ((7, "green"), (20, "red"), (33, "gold"), (46, "blue")):
        awning(s, x, 45, 11, color)


def draw_awning_shops(s):
    roof_block(s, 7, 10, 50, 38, "roof", "buff", 5)
    chimney(s, 45, 12)
    rect(s, "tar", 12, 17, 37, 23)
    facade_strip(s, 7, 43, 50, 14, "buff", 3, True, "red")
    awning(s, 11, 45, 18, "red")
    awning(s, 32, 45, 18, "green")


def draw_weathered_four_square(s):
    rect(s, "shadow", 10, 17, 44, 36)
    poly(s, "roof", ((9, 24), (20, 10), (43, 10), (54, 24), (48, 44), (15, 44)))
    poly(s, "ink", ((9, 24), (20, 10), (43, 10), (54, 24), (48, 44), (15, 44)), 1)
    line(s, "tar", (20, 11), (31, 29))
    line(s, "tar", (43, 11), (31, 29))
    facade_strip(s, 15, 42, 33, 13, "brick_dark", 3)
    rect(s, "concrete", 18, 55, 27, 3)
    chimney(s, 42, 13)


def draw_corner_church(s):
    roof_block(s, 11, 20, 44, 32, "slate", "brick", 4)
    poly(s, "slate", ((14, 24), (31, 9), (51, 24), (48, 45), (17, 45)))
    poly(s, "ink", ((14, 24), (31, 9), (51, 24), (48, 45), (17, 45)), 1)
    rect(s, "brick_dark", 7, 24, 14, 30)
    poly(s, "slate", ((6, 25), (14, 10), (22, 25)))
    rect(s, "limestone", 12, 6, 4, 16)
    line(s, "limestone", (8, 10), (20, 10), 2)
    rect(s, "glass", 11, 34, 6, 10)


def draw_two_family_flat(s):
    roof_block(s, 6, 12, 52, 37, "tar", "brick", 5)
    chimney(s, 13, 14)
    chimney(s, 46, 14)
    rect(s, "limestone", 9, 17, 42, 3)
    facade_strip(s, 6, 44, 52, 13, "brick", 4)
    rect(s, "green", 23, 47, 7, 10)
    rect(s, "red", 32, 47, 7, 10)
    rect(s, "limestone", 20, 55, 22, 4)


def draw_porch_bungalow(s):
    rect(s, "shadow", 8, 17, 48, 35)
    poly(s, "tile", ((7, 24), (20, 11), (43, 11), (56, 24), (49, 44), (14, 44)))
    poly(s, "ink", ((7, 24), (20, 11), (43, 11), (56, 24), (49, 44), (14, 44)), 1)
    facade_strip(s, 14, 42, 35, 12, "buff", 3)
    rect(s, "limestone", 10, 48, 45, 4)
    for x in (13, 51):
        rect(s, "limestone", x, 48, 3, 9)
    rect(s, "concrete", 15, 56, 35, 3)


def draw_brick_warehouse(s):
    roof_block(s, 4, 10, 56, 42, "tar", "brick_dark", 5)
    hvac(s, 11, 17, True)
    hvac(s, 40, 29)
    vent(s, 31, 17)
    facade_strip(s, 4, 47, 56, 11, "brick_dark", 5)
    rect(s, "metal", 8, 50, 13, 8)
    rect(s, "metal", 42, 50, 13, 8)


def draw_parking_garage(s):
    roof_block(s, 5, 9, 54, 43, "concrete", "roof", 5)
    rect(s, "tar", 10, 14, 44, 31)
    for x in (16, 30, 44):
        line(s, "limestone", (x, 16), (x, 42))
    line(s, "gold", (11, 29), (53, 29), 2)
    facade_strip(s, 5, 47, 54, 11, "concrete", 5, True, "roof")
    rect(s, "ink", 47, 20, 5, 5)
    rect(s, "light", 48, 21, 3, 3)


def draw_tudor_house(s):
    rect(s, "shadow", 8, 18, 48, 35)
    poly(s, "slate", ((7, 25), (20, 9), (33, 23), (43, 11), (57, 26), (50, 46), (14, 46)))
    poly(s, "ink", ((7, 25), (20, 9), (33, 23), (43, 11), (57, 26), (50, 46), (14, 46)), 1)
    facade_strip(s, 14, 43, 36, 12, "buff", 3)
    line(s, "brick_dark", (20, 44), (29, 54), 2)
    line(s, "brick_dark", (41, 44), (32, 54), 2)
    tree(s, 7, 51)


def draw_courtyard_apartments(s):
    # U-shaped mass with a visible green court opening toward the street.
    roof_block(s, 5, 10, 17, 44, "slate", "brick", 4)
    roof_block(s, 42, 10, 17, 44, "slate", "brick", 4)
    roof_block(s, 18, 10, 28, 17, "slate", "brick", 4)
    rect(s, "green", 22, 28, 20, 25)
    rect(s, "concrete", 30, 31, 4, 28)
    tree(s, 26, 39)
    tree(s, 39, 47)


def draw_tower_roof(s):
    roof_block(s, 6, 7, 52, 49, "roof", "limestone", 6)
    rect(s, "tar", 11, 12, 41, 38)
    hvac(s, 14, 16, True)
    hvac(s, 37, 37, True)
    rect(s, "glass", 30, 18, 7, 21)
    rect(s, "metal", 31, 19, 5, 2)
    vent(s, 46, 17)
    facade_strip(s, 6, 50, 52, 9, "limestone", 5)


def draw_riverfront_sawtooth(s):
    roof_block(s, 3, 12, 58, 42, "tar", "brick_dark", 4)
    for x in range(6, 55, 10):
        poly(s, "roof", ((x, 43), (x + 5, 15), (x + 10, 43)))
        line(s, "metal", (x + 5, 17), (x + 8, 41), 2)
        line(s, "ink", (x, 43), (x + 10, 43))
    facade_strip(s, 3, 49, 58, 10, "brick_dark", 5)
    rect(s, "green", 7, 52, 15, 7)
    vent(s, 52, 16)


DRAWERS = (
    draw_joined_rowhouses,
    draw_corner_tavern,
    draw_hip_roof_bungalow,
    draw_shotgun_and_garage,
    draw_mansard_townhouse,
    draw_limestone_mansion,
    draw_narrow_shop,
    draw_barrel_roof_cinema,
    draw_theater_stagehouse,
    draw_arts_deco_hall,
    draw_sawtooth_workshop,
    draw_nightlife_storefront,
    draw_market_row,
    draw_awning_shops,
    draw_weathered_four_square,
    draw_corner_church,
    draw_two_family_flat,
    draw_porch_bungalow,
    draw_brick_warehouse,
    draw_parking_garage,
    draw_tudor_house,
    draw_courtyard_apartments,
    draw_tower_roof,
    draw_riverfront_sawtooth,
)


def build_atlas():
    if len(BUILDING_ATLAS_CELLS) != ATLAS_COLUMNS * ATLAS_ROWS:
        raise RuntimeError("atlas mapping must contain exactly 24 cells")
    if len(DRAWERS) != len(BUILDING_ATLAS_CELLS):
        raise RuntimeError("every mapped cell needs exactly one drawing function")

    atlas = pygame.Surface(ATLAS_SIZE, pygame.SRCALPHA, 32)
    atlas.fill(P["clear"])
    for index, draw in enumerate(DRAWERS):
        cell = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA, 32)
        cell.fill(P["clear"])
        draw(cell)
        atlas.blit(cell, ((index % ATLAS_COLUMNS) * CELL_SIZE,
                          (index // ATLAS_COLUMNS) * CELL_SIZE))
    return atlas


def validate_atlas(atlas):
    if atlas.get_size() != ATLAS_SIZE:
        raise RuntimeError(f"expected atlas size {ATLAS_SIZE}, got {atlas.get_size()}")

    allowed = set(P.values())
    alpha_values = set()
    for y in range(atlas.get_height()):
        for x in range(atlas.get_width()):
            color = tuple(atlas.get_at((x, y)))
            alpha_values.add(color[3])
            if color not in allowed:
                raise RuntimeError(f"off-palette pixel {color} at {(x, y)}")
    if alpha_values != {0, 255}:
        raise RuntimeError(f"alpha must be binary, found {sorted(alpha_values)}")

    for index, mapping in enumerate(BUILDING_ATLAS_CELLS):
        cell = atlas.subsurface((index % ATLAS_COLUMNS * CELL_SIZE,
                                 index // ATLAS_COLUMNS * CELL_SIZE,
                                 CELL_SIZE, CELL_SIZE))
        if cell.get_bounding_rect(min_alpha=255).width == 0:
            raise RuntimeError(f"empty atlas cell {index}: {mapping}")


def main():
    pygame.init()
    atlas = build_atlas()
    validate_atlas(atlas)
    output = Path(__file__).resolve().parents[1] / "sprites" / "stlouis-neighborhood-buildings-pixel.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(atlas, str(output))
    print(f"wrote {output} ({atlas.get_width()}x{atlas.get_height()}, {len(DRAWERS)} cells)")
    pygame.quit()


if __name__ == "__main__":
    main()

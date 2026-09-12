"""Render the screenshots the devlog page (docs/index.html) is built from.

    python tools/render_devlog_shots.py

Writes into docs/shots/. The twelve place shots come out at the game's
native 640x360 and the two full-width plates at 2x, and that split
matters: the page shows the places in ~550px columns, and shrinking a
1280px shot into one of those turns pixel art to mush.
"""
import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import pygame  # noqa: E402
import main as M  # noqa: E402

OUT = os.path.join(HERE, "docs", "shots")
os.makedirs(OUT, exist_ok=True)

random.seed(4242)
g = M.Game()
g.state = M.STATE_PLAYING
g.police = []
g.foot_police = []
g.wanted_level = 0


def save(name, scale=2):
    surf = pygame.transform.scale(
        g.screen, (M.SCREEN_WIDTH * scale, M.SCREEN_HEIGHT * scale))
    path = os.path.join(OUT, f"{name}.png")
    pygame.image.save(surf, path)
    print("wrote", path, os.path.getsize(path) // 1024, "KB")


def world(name, col, row, labels=True, scale=2):
    g.player_rect.center = (col * 64 + 32, row * 64 + 32)
    g.player_fx = float(g.player_rect.centerx)
    g.player_fy = float(g.player_rect.centery)
    g.driving = None
    g.camera.x = col * 64 + 32 - M.SCREEN_WIDTH // 2
    g.camera.y = row * 64 + 32 - M.SCREEN_HEIGHT // 2
    g.camera.shake_ox = g.camera.shake_oy = 0.0
    g.screen.fill(M.COLOR_SKY_BG)
    sc, ec, sr, er = g.camera.visible_tile_range()
    for r in range(sr, er):
        for c in range(sc, ec):
            g.draw_tile(c, r)
    g.draw_diagonal_network()
    g.draw_bridge_and_channel()
    g.draw_landmark_art()
    g.draw_landmark_streets(sc, ec, sr, er)
    g.draw_decals()
    for r in range(sr, er):
        for c in range(sc, ec):
            g.draw_props(c, r)
    for r in range(sr, er):
        for c in range(sc, ec):
            g.draw_building_shadow(c, r)
    for r in range(sr, er):
        for c in range(sc, ec):
            g.draw_building_roof(c, r)
    for r in range(sr, er):
        for c in range(sc, ec):
            g.draw_building_facade(c, r)
    g.draw_rail_infrastructure()
    for car in g.cars:
        car.draw(g.screen, g.camera)
    for ped in g.pedestrians:
        ped.draw(g.screen, g.camera)
    g.draw_arch_foreground()
    if labels:
        for (lx, ly, lw, lh, kind, nm, colr) in M.LANDMARKS:
            fr = g.camera.apply(pygame.Rect(lx * 64, ly * 64, lw * 64, lh * 64))
            sx, sy = (M.lm_label_anchor(nm, fr) if M.lm_has_art(nm)
                      else fr.center)
            if -40 < sx < M.SCREEN_WIDTH + 40 and -40 < sy < M.SCREEN_HEIGHT + 40:
                M.hud_text(g.screen, nm.upper(),
                           sx - M.hud_text_width(nm.upper()) // 2, sy)
    save(name, scale)


# the front end, exactly as a player first sees it
g.state = M.STATE_TITLE
g.draw_title_screen()
save("title")
g.state = M.STATE_PLAYING

for name, col, row in (
        ("arch", 86, 46),
        ("stadium", 76, 46),
        ("chain_of_rocks", 95, 3),
        ("brewery", 71, 70),
        ("downtown", 68, 36),
        ("gravois", 38, 86),
        ("garden", 33, 49),
        ("ted_drewes", 8, 79),
        ("forest_park", 20, 34),
        ("the_hill", 27, 59),
        ("des_peres", 40, 95),
        ("delmar", 9, 17),
):
    world(name, col, row, scale=1)


# the whole city, from the map screen
g.state = M.STATE_PLAYING
g.show_map = True
g.screen.fill(M.COLOR_SKY_BG)
g.draw()
save("citymap")

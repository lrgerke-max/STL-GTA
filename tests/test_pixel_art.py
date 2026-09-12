"""It has to keep looking like 1997.

The building facade atlas already had a palette discipline pinned in
test_smoke. The hand-made landmark compositions had none, and they had drifted
in two specific, measurable ways that nothing was watching:

  * the Climatron's dome was a THIRTY-NINE step radial interpolation, a colour
    per two-pixel ring, neighbouring shades 2-3 RGB units apart. A smooth
    airbrushed hemisphere, and the single largest departure from the era look
    in the file. Art Hill was the same mistake at smaller scale - nine
    contours shaded 4.5% at a time.
  * four cast shadows were ALPHA-BLENDED. A translucent shadow invents one new
    intermediate colour for every background colour it crosses, so the Arch's
    catenary ribbon - falling over grass, three greens of tree, gravel, two
    waters and concrete - added an eleven-colour chain of near-identical
    darks all by itself.

Both are now banded or dithered, which is how 8- and 16-bit art did curved
shading and translucency. The numbers: worst chain of invisible colour steps
anywhere went from 38 to 3, the Arch's palette from 44 colours to 25, the
Botanical Garden's from 69 to 35.
"""

import collections
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402
import main as M  # noqa: E402

# convert_alpha() and the art bakers need a display surface. Other modules get
# one by constructing a Game; this one only needs the pixels.
pygame.init()
if pygame.display.get_surface() is None:
    pygame.display.set_mode((320, 180))

#: Two colours closer than this are not two colours - at this render scale the
#: step between them cannot be seen, which is what an airbrush looks like.
INVISIBLE_STEP = 5

#: A gradient is a CHAIN of invisible steps: 39 blues each two units from the
#: next. Two greys that happen to land three units apart are palette
#: redundancy - untidy, invisible, and not a gradient. Four allows for that
#: without leaving room for a ramp.
MAX_CHAIN = 4


def _art(name, lw, lh):
    surf = pygame.Surface((lw * M.TILE_SIZE, lh * M.TILE_SIZE)).convert_alpha()
    surf.fill((0, 0, 0, 0))
    full = pygame.Rect(0, 0, lw * M.TILE_SIZE, lh * M.TILE_SIZE)
    M.lm_draw_landmark(surf, name, full, full)
    return surf


def _colours(surf):
    seen = collections.Counter()
    alphas = set()
    for y in range(surf.get_height()):
        for x in range(surf.get_width()):
            px = surf.get_at((x, y))
            seen[tuple(px)[:3]] += 1
            alphas.add(px[3])
    return seen, alphas


def _longest_invisible_chain(colours):
    """Size of the largest group linked by steps too small to see."""
    parent = {c: c for c in colours}

    def find(c):
        while parent[c] != c:
            parent[c] = parent[parent[c]]
            c = parent[c]
        return c

    cols = list(colours)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            gap = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)
            if gap <= INVISIBLE_STEP ** 2:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb
    groups = collections.Counter(find(c) for c in cols)
    return max(groups.values()) if groups else 0


def _art_landmarks():
    return [(name, lw, lh) for (lx, ly, lw, lh, kind, name, colour)
            in M.LANDMARKS if M.lm_has_art(name)]


def test_no_landmark_composition_contains_a_smooth_gradient():
    """No ramp of steps too small to see. This is the whole discipline."""
    assert _art_landmarks(), "no landmark art to check"
    worst = []
    for name, lw, lh in _art_landmarks():
        seen, _alphas = _colours(_art(name, lw, lh))
        chain = _longest_invisible_chain(list(seen))
        worst.append((chain, name))
        assert chain <= MAX_CHAIN, (
            f"{name} has a {chain}-step ramp of invisible colour steps - "
            f"band it (lm__band) or dither it (lm__alpha_poly) instead")
    worst.sort(reverse=True)
    assert worst[0][0] <= MAX_CHAIN, worst[:3]


def test_landmark_art_has_no_antialiased_alpha():
    """Hard pixel edges. A soft edge is the other way art stops being pixels."""
    for name, lw, lh in _art_landmarks():
        _seen, alphas = _colours(_art(name, lw, lh))
        soft = sorted(a for a in alphas if a not in (0, 255))
        assert not soft, f"{name} has antialiased alpha: {soft[:6]}"


def test_a_cast_shadow_is_dithered_rather_than_blended():
    """lm__alpha_poly must stipple, not blend.

    Checked by construction: paint a shadow over a flat field and assert the
    result contains only the field colour and the shadow colour - no blend of
    the two, and both present, so it really did stipple rather than fill.
    """
    field, shadow = (120, 140, 100), (8, 7, 9)
    surf = pygame.Surface((64, 64))
    surf.fill(field)
    M.lm__alpha_poly(surf, [(4, 4), (60, 4), (60, 60), (4, 60)],
                     shadow + (150,))
    seen = {surf.get_at((x, y))[:3]
            for y in range(8, 56) for x in range(8, 56)}
    assert seen == {field, shadow}, (
        f"a blended shadow invented {sorted(seen - {field, shadow})}")


def test_a_banded_ramp_really_does_band():
    """lm__band must quantise, so a long loop cannot make a long ramp."""
    dark, light = (20, 30, 40), (200, 210, 220)
    steps = {M.lm__band(dark, light, i / 200.0) for i in range(201)}
    assert len(steps) == M.LM_BANDS, (
        f"{len(steps)} shades from a {M.LM_BANDS}-band ramp")
    assert dark in steps and light in steps, "the ramp must reach both ends"
    ordered = sorted(steps)
    gaps = [min(abs(a[i] - b[i]) for i in range(3))
            for a, b in zip(ordered, ordered[1:])]
    assert min(gaps) > INVISIBLE_STEP, (
        f"band steps of {min(gaps)} are still invisible")


def test_the_era_palette_stays_small_per_composition():
    """A whole landmark is a scene, not a sprite, so this is generous - but a
    composition drifting past it is a composition that has stopped choosing
    colours."""
    for name, lw, lh in _art_landmarks():
        seen, _alphas = _colours(_art(name, lw, lh))
        assert len(seen) <= 72, f"{name} uses {len(seen)} colours"


def test_every_baked_sprite_keeps_a_tight_palette():
    """Cars, people, the dog, props, facades - these are what you look at.

    A landmark composition is a whole scene, so 72 colours is reasonable for
    one. A sprite is a sprite: measured, the car sets top out at 14 colours,
    pedestrians at 13, props at 8 and the dog at 3, with no invisible ramp
    longer than two steps anywhere. Nothing here should need more.
    """
    game = M.Game()                      # bakes the atlases
    groups = {}

    cars = []
    for name, frames in M.cars_bake_all().items():
        for i, frame in enumerate(frames[:4]):
            if isinstance(frame, pygame.Surface):
                cars.append((f"{name}[{i}]", frame))
    groups["car"] = cars

    peds = []
    for key in list(M.PED_SPRITES)[:12]:
        for facing in range(4):
            # element 0 is the sprite; element 1 is its drop shadow, which is
            # deliberately translucent - see the next test.
            sprite = M.ped_sprite(key, facing, True, 0)[0]
            peds.append((f"{key}/{facing}", sprite))
    groups["pedestrian"] = peds

    groups["prop"] = [(name, M.props_get(name))
                      for name in sorted(M.props__SPRITES)]
    groups["facade"] = [(f"{hood}[{i}]", sprite)
                        for hood, sprites in M.NEIGHBORHOOD_BUILDING_SPRITES.items()
                        for i, sprite in enumerate(sprites[:2])]

    for label, sprites in groups.items():
        assert sprites, f"no {label} sprites to check"
        for name, sprite in sprites:
            seen, alphas = _colours(sprite)
            opaque = [c for c in seen]
            assert len(opaque) <= 24, (
                f"{label} {name} uses {len(opaque)} colours")
            assert _longest_invisible_chain(opaque) <= 3, (
                f"{label} {name} has an invisible ramp in it")
            soft = sorted(a for a in alphas if a not in (0, 255))
            assert not soft, f"{label} {name} has antialiased alpha: {soft[:4]}"


def test_a_static_light_pool_is_stippled_not_blended():
    """The streetlight's glow used alpha 34 and 52.

    That prop lands on asphalt, sidewalk, grass, park and plaza, so as an
    alpha blend one glow invented five different intermediate colours. It is
    dithered now.

    Actor drop shadows are the deliberate exception and keep their alpha: the
    dither pattern in a BAKED sprite lives in sprite space, so on something
    that moves it swims across the ground as a crawl of noise, while a
    landmark's shadow never moves and bands cleanly.
    """
    M.props_bake()
    light = M.props_get('streetlight')
    alphas = {light.get_at((x, y))[3]
              for y in range(light.get_height())
              for x in range(light.get_width())}
    assert alphas <= {0, 255}, f"the light pool still blends: {sorted(alphas)}"

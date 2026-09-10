"""St. Louis authenticity: the street network, the neighbourhoods, the talk.

Every assertion here exists because the thing it checks was measurably wrong:
one straight MetroLink row through the Compton Hill Water Tower's lawn, a
perfect square street lattice with no named street on it, eleven coarse
neighbourhoods that hung the Fox on Delmar and Bevo Mill signage on a downtown
loft block, a building ring stamped through the middle of Henry Shaw's garden,
and a conversation table so small the city ran out of things to say in about
two minutes of walking.
"""

import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
import main as M  # noqa: E402


# ---------------------------------------------------------------- streets --
def test_the_street_grid_is_irregular_and_every_line_has_a_name():
    lines = sorted(M.ROAD_LINES)
    gaps = {b - a for a, b in zip(lines, lines[1:])}
    assert len(gaps) >= 3, f"the grid is still uniform: gaps {gaps}"
    for line in lines:
        assert M.NS_STREET_NAMES.get(line), f"column {line} has no name"
        assert M.EW_STREET_NAMES.get(line), f"row {line} has no name"
    # the arterials must be real lines, not aspirational ones
    assert M.ARTERIAL_LINES <= M.ROAD_LINES
    assert M.ARTERIAL_NS and M.ARTERIAL_EW


def test_named_streets_land_on_the_landmarks_they_actually_serve():
    named = {v: k for k, v in M.NS_STREET_NAMES.items()}
    # Kingshighway is Forest Park's east wall and the CWE's west wall
    park = next(e for e in M.LANDMARKS if e[5] == "Forest Park")
    cwe = next(e for e in M.LANDMARKS if e[5] == "Central West End")
    kings = named["KINGSHIGHWAY"]
    assert park[0] + park[2] <= kings <= cwe[0]
    # Grand runs through Grand Center
    gc = next(e for e in M.LANDMARKS if e[5] == "Grand Center Arts District")
    assert gc[0] <= named["GRAND BLVD"] <= gc[0] + gc[2]
    # Chippewa carries Ted Drewes
    ew = {v: k for k, v in M.EW_STREET_NAMES.items()}
    ted = next(e for e in M.LANDMARKS if e[5] == "Ted Drewes")
    assert ted[1] <= ew["CHIPPEWA ST"] <= ted[1] + ted[3]
    # both river bridges are on named rows in the grid
    for row in M.RIVER_BRIDGES:
        assert row in M.ROAD_LINES and M.EW_STREET_NAMES.get(row)


def test_grand_boulevard_stays_open_through_grand_center():
    """The district mask must not turn its painted boulevard into a wall."""
    gc = next(e for e in M.LANDMARKS if e[5] == "Grand Center Arts District")
    lx, ly, lw, lh = gc[:4]
    grand = next(line for line, name in M.NS_STREET_NAMES.items()
                 if name == "GRAND BLVD")
    assert lx <= grand < lx + lw

    for row in range(ly, ly + lh):
        tile = M.GAME_MAP[row][grand]
        assert tile['type'] == M.TILE_ROAD, (grand, row, tile['type'])
        assert not tile['collidable'], (grand, row)
        assert tile['landmark'] == "Grand Center Arts District"
        assert M.WALK_REACHABLE[row][grand], (grand, row)


def test_the_diagonals_exist_and_are_drivable_end_to_end():
    """Gravois does not run at a right angle to anything. That is the point."""
    assert {"GRAVOIS AVE", "MANCHESTER AVE", "WEST FLORISSANT AVE"} <= {
        name for name, _pts, _w in M.DIAGONAL_STREETS}

    for name, points, width in M.DIAGONAL_STREETS:
        tiles = M._diagonal_run(points, width)
        assert len(tiles) > 60, f"{name} is barely a driveway"
        solid = [(c, r) for (c, r) in tiles
                 if M.GAME_MAP[r][c]['collidable']
                 and M.GAME_MAP[r][c]['type'] != M.TILE_WATER]
        assert not solid, f"{name} is walled off at {solid[:4]}"
        # and the road surface it does claim is reachable from the street net
        road = [(c, r) for (c, r) in tiles if M.GAME_MAP[r][c].get('diagonal')]
        assert road, f"{name} laid no road at all"
        assert all(M.WALK_REACHABLE[r][c] for (c, r) in road), name

    # a diagonal tile answers with the diagonal's name, not the grid's
    gravois = [t for t, n in M.DIAGONAL_AT.items() if n == "GRAVOIS AVE"]
    assert any(M.street_name(c, r) == "GRAVOIS AVE" for (c, r) in gravois)
    west_florissant = [t for t, n in M.DIAGONAL_AT.items()
                       if n == "WEST FLORISSANT AVE"]
    assert west_florissant
    assert all(M.street_name(c, r) == "WEST FLORISSANT AVE"
               for c, r in west_florissant)
    assert M.EW_STREET_NAMES[9] == "NATURAL BRIDGE"


def test_blocks_are_not_all_the_same_size_any_more():
    spans = M._block_spans(M.MAP_TILES_W)
    sizes = {b - a for a, b in spans}
    assert len(sizes) >= 3, f"every block is still the same shape: {sizes}"


# ------------------------------------------------------------- neighbourhoods
def test_no_neighbourhood_swallows_the_city():
    counts = {}
    for r in range(M.MAP_TILES_H):
        for c in range(M.MAP_TILES_W):
            hood = M.hood_at(c, r)
            counts[hood] = counts.get(hood, 0) + 1
    total = float(sum(counts.values()))
    worst, share = max(counts.items(), key=lambda kv: kv[1])
    # 'south' alone used to be 30.6% of the map with one 11-sign bag
    assert share / total < 0.12, f"{worst} is {share / total:.1%} of the map"
    assert len(counts) >= 20, f"only {len(counts)} neighbourhoods"


def test_every_landmark_sits_in_one_neighbourhood():
    """The Botanical Garden came back 'grove'; City Museum came back 'south'."""
    for (lx, ly, lw, lh, _kind, name, _c) in M.LANDMARKS:
        hoods = {}
        for r in range(ly, ly + lh):
            for c in range(lx, lx + lw):
                hood = M.hood_at(c, r)
                hoods[hood] = hoods.get(hood, 0) + 1
        best, n = max(hoods.items(), key=lambda kv: kv[1])
        assert n / float(lw * lh) >= 0.90, f"{name} is split across {hoods}"

    # the specific misplacements that started this
    garden = next(e for e in M.LANDMARKS if e[5] == "Missouri Botanical Garden")
    assert M.hood_at(garden[0] + 2, garden[1] + 2) == 'shaw'
    museum = next(e for e in M.LANDMARKS if e[5] == "City Museum")
    assert M.hood_at(museum[0] + 2, museum[1] + 2) == 'downtown'
    assert M.hood_at(12, 5) == 'wellsgoodfellow'
    assert M.hood_at(52, 11) == 'fairground'
    assert M.hood_at(82, 11) == 'collegehill'


def test_every_neighbourhood_has_a_complete_kit():
    hoods = {hood for (_a, _b, _c, _d, hood) in M.HOOD_REGIONS}
    hoods.add(M.HOOD_FALLBACK)
    for hood in hoods:
        assert M.HOOD_SIGNS.get(hood), f"{hood} has no shop signs"
        assert M.HOOD_HOUSES.get(hood), f"{hood} has no house styles"
        assert M.HOOD_BRICKS.get(hood), f"{hood} has no masonry"
        assert M.HOOD_NAMES.get(hood), f"{hood} has no name to show the player"
    # and the atlas alias table only points at families the atlas ships
    for hood, source in M.HOOD_ATLAS_ALIAS.items():
        assert hood in hoods, hood
        assert source in M.BUILDING_ATLAS_HOODS, source


SIGN_BELONGS_TO = {
    "FOX": 'grand', "POWELL": 'grand', "SHELDON": 'grand', "BILLIKEN": 'grand',
    "THE GROVE": 'grove', "ATOMIC": 'grove', "URBAN CH": 'grove',
    "CLIMATRON": 'shaw', "SHAW'S": 'shaw', "ORCHIDS": 'shaw',
    "TIVOLI": 'loop', "PAGEANT": 'loop', "BLUEBERRY": 'loop', "CHUCK B": 'loop',
    "MCGURK'S": 'soulard', "MARDI GRAS": 'soulard', "GUS'S": 'soulard',
    "BEVO MILL": 'bevo', "GRBIC": 'bevo', "BUREK": 'bevo',
    "CROWN CNDY": 'oldnorth', "SUMNER": 'ville', "ANNIE M.": 'ville',
    "VIDE POCHE": 'carondelet', "BLUES CITY": 'carondelet',
    "THE RUINS": 'towergrove', "MOKABE'S": 'towergrove',
    "LEMP": 'bentonpark', "CLYDESDALE": 'bentonpark', "VENICE": 'bentonpark',
    "DOGTOWN": 'dogtown', "PARADE": 'dogtown',
    "WATER TWR": 'comptonhts', "LAFAYETTE": 'lafayette',
    "THE MUNY": 'forestpark', "FREE ZOO": 'forestpark',
    "VOLPI": 'hill', "GIOIA'S": 'hill', "MO BAKING": 'hill',
    "BASILICA": 'cwe', "LEFT BANK": 'cwe',
    "LANDING": 'riverfront', "COBBLES": 'riverfront',
    "FRANCIS PK": 'sthills', "CINCO": 'cherokee',
}


def test_a_sign_hangs_in_exactly_the_neighbourhood_it_belongs_to():
    """The Fox on Delmar, McGurk's on Cherokee, Bevo Mill downtown. No."""
    for text, want in SIGN_BELONGS_TO.items():
        found = {hood for hood, pool in M.HOOD_SIGNS.items()
                 if any(t == text for (t, _bg, _fg) in pool)}
        assert found == {want}, f"{text} hangs in {found}, should be {{{want}}}"


def test_shop_signs_still_fit_a_shopfront():
    for hood, pool in M.HOOD_SIGNS.items():
        for text, _bg, _fg in pool:
            assert len(text) <= 10, f"{hood}: {text!r} is {len(text)} chars"


# ------------------------------------------------------------------- talking
def test_every_neighbourhood_has_its_own_things_to_say():
    """`west` had zero local scenes; every hood heard the same fifteen."""
    hoods = {hood for (_a, _b, _c, _d, hood) in M.HOOD_REGIONS} | {M.HOOD_FALLBACK}
    for hood in hoods:
        local = M.STL_LOCAL_BY_HOOD.get(hood, ())
        assert len(local) >= 10, f"{hood} has only {len(local)} local scenes"
        assert M.SOLO_BY_HOOD.get(hood), f"{hood} has no solo barks"
        assert M.STL_PANIC_BY_HOOD.get(hood), f"{hood} has no panic lines"
    assert len(M.STL_CONVERSATIONS) >= 250, len(M.STL_CONVERSATIONS)
    assert len(M.STL_CITYWIDE) >= 40


def test_every_tagged_scene_names_a_real_neighbourhood():
    hoods = {hood for (_a, _b, _c, _d, hood) in M.HOOD_REGIONS} | {M.HOOD_FALLBACK}
    for table in (M.STL_CONVERSATIONS, M.STL_SOLO_BARKS):
        for scene in table:
            if scene[0] is None:
                continue
            for hood in scene[0]:
                assert hood in hoods, f"{hood!r} is not a neighbourhood"
    for hood in M.STL_PANIC_BY_HOOD:
        assert hood in hoods, hood


def test_the_chatter_bag_never_repeats_before_the_deck_runs_out():
    """A bare random.choice over sixteen scenes is why the city sounded like
    it only knew fifteen things."""
    bag = M.ChatterBag()
    rng = random.Random(4242)
    pool = tuple(range(12))
    seen = [bag.deal(('t',), pool, rng) for _ in range(len(pool))]
    assert sorted(seen) == sorted(pool), "the deck dealt a duplicate"
    # across the reshuffle seam, the next card is not the one just heard
    for _ in range(200):
        nxt = bag.deal(('t',), pool, rng)
        assert nxt != seen[-1], "reshuffle repeated the last scene"
        seen.append(nxt)


def test_a_neighbourhood_mostly_hears_itself():
    bag = M.ChatterBag()
    rng = random.Random(99)
    local = 0
    trials = 600
    for _ in range(trials):
        scene = bag.pick('soulard', M.STL_CITYWIDE, M.STL_LOCAL_BY_HOOD, rng)
        if scene[0] is not None and 'soulard' in scene[0]:
            local += 1
    # 83-100% of everything used to come from the citywide bag
    assert local / float(trials) > 0.6, local / float(trials)


def test_the_sirens_go_off_on_the_right_day():
    """The city and county test the outdoor sirens the first MONDAY at 11."""
    text = " ".join(" ".join(scene[1:]) for scene in M.STL_CONVERSATIONS)
    assert "FIRST MONDAY" in text
    assert "FIRST TUESDAY" not in text


# -------------------------------------------------------- the garden and art
def test_the_botanical_garden_is_a_garden_not_a_block_of_flats():
    entry = next(e for e in M.LANDMARKS if e[5] == "Missouri Botanical Garden")
    lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
    assert M.LANDMARK_LAYOUT[entry[5]] == "garden"

    solid = open_tiles = 0
    for r in range(ly, ly + lh):
        for c in range(lx, lx + lw):
            tile = M.GAME_MAP[r][c]
            if tile['collidable']:
                solid += 1
            else:
                open_tiles += 1
                assert M.WALK_REACHABLE[r][c], f"garden sealed at {c},{r}"
    assert open_tiles / float(lw * lh) >= 0.7, "too much masonry in the garden"

    # the default district layout would ring the inside with buildings
    ring = M._LM_SOLID["district"]
    assert any(ring(x, y, lw, lh) != M._LM_SOLID["garden"](x, y, lw, lh)
               for x in range(lw) for y in range(lh))


def test_the_climatron_is_there_and_you_can_find_it():
    named = {name for (parent, name, *_rest) in M.LANDMARK_FEATURES
             if parent == "Missouri Botanical Garden"}
    assert {"The Climatron", "Seiwa-en", "The Linnean House",
            "Tower Grove House"} <= named

    entry = next(e for e in M.LANDMARKS if e[5] == "Missouri Botanical Garden")
    lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
    tagged = {M.GAME_MAP[r][c]['landmark']
              for r in range(ly, ly + lh) for c in range(lx, lx + lw)}
    assert "The Climatron" in tagged
    # Seiwa-en is real water you have to go round
    assert any(M.GAME_MAP[r][c]['type'] == M.TILE_WATER
               for r in range(ly, ly + lh) for c in range(lx, lx + lw))
    assert M.lm_has_art("Missouri Botanical Garden")


def test_a_feature_tile_still_knows_which_landmark_drew_it():
    """_stamp_features renames a tile to the feature that claims it, which
    silently broke the has-art test and drew houses over the Climatron."""
    assert M.landmark_owner("The Climatron") == "Missouri Botanical Garden"
    assert M.landmark_owner("The Muny") == "Forest Park"
    assert M.landmark_owner("Gateway Arch") == "Gateway Arch"


#: landmarks that are deliberately drawn by the generic passes
GENERIC_ON_PURPOSE = {"Downtown", "Soulard Farmers Market", "Cherokee Street"}


def test_no_authored_landmark_art_is_unreachable():
    """lm__bake_cwe, _the_hill, _delmar_loop and _grand_center all existed,
    were registered in three tables, and no landmark name pointed at them."""
    used = set(M.lm_LANDMARK_ART.values())
    orphans = set(M.lm__BAKERS) - used
    assert not orphans, f"art nothing can reach: {sorted(orphans)}"
    for (_x, _y, _w, _h, _k, name, _c) in M.LANDMARKS:
        assert M.lm_has_art(name) or name in GENERIC_ON_PURPOSE, name
    for style in used:
        assert style in M.lm__BAKERS
        assert style in M.lm__GROUND and style in M.lm__LABEL_AT


def test_a_district_with_its_own_art_has_collision_that_matches_it():
    """The four district bakers draw their own street grid; under the old
    'district' layout the picture and the walls disagreed completely."""
    for name in ("Central West End", "The Hill", "Delmar Loop",
                 "Grand Center Arts District"):
        assert M.LANDMARK_LAYOUT[name] == "blocks"
        entry = next(e for e in M.LANDMARKS if e[5] == name)
        lx, ly, lw, lh = entry[0], entry[1], entry[2], entry[3]
        for r in range(ly, ly + lh):
            for c in range(lx, lx + lw):
                if not M.GAME_MAP[r][c]['collidable']:
                    assert M.WALK_REACHABLE[r][c], f"{name} sealed at {c},{r}"


# ----------------------------------------------------------- the courier job
def test_cargo_comes_from_where_you_collected_it():
    """You used to load a BREWERY KEG at Ted Drewes."""
    brewery = M.Job.CARGO_BY_PICKUP["Anheuser-Busch Brewery"]
    custard = M.Job.CARGO_BY_PICKUP["Ted Drewes"]
    assert not set(brewery) & set(custard)
    for _ in range(40):
        assert M.Job.cargo_for("Anheuser-Busch Brewery") in brewery
        assert M.Job.cargo_for("Ted Drewes") in custard
    # anywhere without a list still gets something local
    assert M.Job.cargo_for("Nowhere At All") in M.Job.CARGO
    for name, pool in M.Job.CARGO_BY_PICKUP.items():
        assert any(e[5] == name for e in M.LANDMARKS), name
        assert pool


def test_every_landmark_hands_you_a_fact_when_you_find_it():
    for (_x, _y, _w, _h, _k, name, _c) in M.LANDMARKS:
        assert M.LANDMARK_PLAQUES.get(name), f"{name} has no plaque"
    for (_parent, name, *_rest) in M.LANDMARK_FEATURES:
        assert M.LANDMARK_PLAQUES.get(name), f"{name} has no plaque"
    for name, text in M.LANDMARK_PLAQUES.items():
        assert 20 <= len(text) <= 90, f"{name}: {len(text)} chars"


# ------------------------------------------------------------------ the HUD
@pytest.fixture(scope="module")
def game():
    random.seed(90210)
    return M.Game()


def test_the_game_tells_you_which_neighbourhood_you_are_in(game):
    """Nothing ever named the district you were standing in."""
    soulard = next(e for e in M.LANDMARKS if e[5] == "Soulard Farmers Market")
    game.driving = None
    game.player_rect.center = ((soulard[0] + 1) * M.TILE_SIZE,
                               (soulard[1] + 1) * M.TILE_SIZE)
    game.hood_now = None
    game.update_place_names()
    assert game.hood_now == 'soulard'
    assert M.hood_name('soulard') == "SOULARD"

    # crossing a boundary raises the title
    hill = next(e for e in M.LANDMARKS if e[5] == "The Hill")
    game.player_rect.center = ((hill[0] + 1) * M.TILE_SIZE,
                               (hill[1] + 1) * M.TILE_SIZE)
    game.update_place_names()
    assert game.hood_now == 'hill'
    assert game.hood_banner > 0


def test_the_game_tells_you_which_street_you_are_on(game):
    col = sorted(M.ROAD_LINES)[8]
    row = sorted(M.ROAD_LINES)[3]
    game.driving = None
    game.player_rect.center = (col * M.TILE_SIZE + 32, (row + 1) * M.TILE_SIZE + 32)
    game.street_now = None
    game.update_place_names()
    assert game.street_now == M.NS_STREET_NAMES[col]

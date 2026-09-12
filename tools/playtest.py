"""STL-GTA playtest rig: measures the things that decide whether driving
feels good, so tuning can be judged instead of guessed at.

Every probe prints numbers rather than passing or failing - this is an
instrument, not a test suite. tests/test_smoke.py is the test suite, and it
pins the invariants these numbers established. Run this before and after any
handling, police or traffic change.

    python tools/playtest.py              # every probe
    python tools/playtest.py camera       # just one
    python tools/playtest.py chases       # scripted pursuits at every star

    camera       does the view ever lose the car, across all eight headings
    handling     yaw rate and turning radius against speed
    handbrake    how far the back end comes round in a second
    reverse      launch, brake-to-reverse, reverse yaw, and wall retreat
    corner       a competent driver braking into a 90-degree grid corner
    cornerhb     ... and the same corner taken on the handbrake
    police       whether a flat-out straight-line escape exists, per star
    foot          whether sprinting can open a gap on a one-star beat cop
    cophandling  how hard a five-star cruiser can turn
    drive        can the grid be driven at speed at all (see GridDriver)
    wear         where a chase car's health actually goes
    chasewear    ... split by source, at every star level
    careful      aggressive vs careful driving: whose fault is the damage
    roads        every reachable tile, four headings: can a car drive off it
    traffic      overlapping AI cars, stalled cars, mean traffic speed
    onscreen     how much of the population is actually in frame
    chase/chases a real pursuit: GridDriver flees, the game's own police chase

GridDriver is the point of the rig: a scripted driver good enough that the
numbers describe the game rather than describing a bad autopilot. It holds a
lane, checks a corridor is open before committing to it, brakes into the
corners it means to turn at, refuses to throttle at a wall it can already
see, and backs out when it stops making progress.

It judges a corridor by COLLISION, not by tile type, and that distinction was
worth 2.3 px/step. Asking `traffic__segment_clear` - "is every tile
TILE_ROAD" - is right for ambient traffic, which must follow named lanes and
stay off the lawn. It is wrong for a player: Forest Park's grid lanes are
TILE_PARK, so inside the park all four directions came back blocked and the
driver went blind. It could then neither plan a turn nor re-face during
recovery, so it simply ground whatever was in front of it. Measured before
the fix: 1,144 of 2,400 frames pinned against the Grand Basin, mean speed
2.65 of a 6.40 top speed, and all fifteen `chases` runs finishing ~345px from
a start one tile outside the park. After: 4.68 mean, 2 hits median.

Two lessons worth keeping, both learned the hard way here:

  * `probe_drive` and `probe_chase` start from a FIXED point, so a map change
    re-rolls the route and their numbers move for reasons unrelated to it.
    `probe_roads` is the deterministic one; use it for map work.
  * a probe that says it holds a star level has to pin it, not floor it. The
    scripted driver earns a twelve-kill pedestrian combo, which forces three
    stars on purpose, so every labelled tier used to drift upward.
"""

import collections
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

_G = None


def game():
    global _G
    if _G is None:
        random.seed(4242)
        _G = M.Game()
    g = _G
    g.state = M.STATE_PLAYING
    g.wanted_level = 0
    g.police = []
    g.foot_police = []
    g.foot_cop_respawn = 0
    g.bust_meter = 0
    g.heat_timer = 0
    g.freeze = 0
    g.shake = 0
    g.player_stamina = M.PLAYER_STAMINA_MAX
    g.sprinting = False
    g.sprint_ready = True
    g.grub = {}
    g.frenzy = None
    # Probe cars are appended to g.cars and abandoned as parked when the probe
    # ends. Left alone they accumulate across probes and quietly poison the
    # density and overlap numbers - 50 "parked" cars against a configured 22.
    for c in [c for c in g.cars if getattr(c, '_probe', False)]:
        g.cars.remove(c)
    if g.driving is not None and getattr(g.driving, '_probe', False):
        g.driving = None
    return g


def put_in_car(g, x, y, angle=0.0, variant='sedan'):
    """Hand the player a fresh car of `variant` at (x, y) facing `angle`."""
    # A wrecked probe can be detached from g.driving while remaining in the
    # ambient pool. Remove it before adding its replacement or long probes
    # quietly measure 11, 12, ... cars instead of the configured ten.
    for stale in [c for c in g.cars
                  if getattr(c, '_probe', False) and c is not g.driving]:
        g.cars.remove(stale)
    budget = M.PARKED_CAR_COUNT + M.MOVING_CAR_COUNT
    while len(g.cars) > budget:
        surplus = next((c for c in g.cars
                        if c.driver is None and not c.parked
                        and c.variant not in M.SHOWCASE_VARIANTS
                        and c is not g.chain_bike), None)
        if surplus is None:
            break
        g.cars.remove(surplus)
    if g.driving is not None:
        g.driving.driver = None
        g.driving.parked = True
    car = M.Car(x, y, variant=variant)
    car.angle = angle
    car.velocity = 0.0
    car.vlat = 0.0
    car.steer_angle = 0.0
    car.driver = 'player'
    car.parked = False
    car._probe = True
    M.traffic_take_over(car)
    g.driving = car
    g.cars.append(car)
    g.camera.snap_to(car.rect)
    return car


def straight_road_point():
    """Centre of a long east-west road tile with clear road either side."""
    row = sorted(M.ROAD_LINES)[6]
    col = 10
    return (col * M.TILE_SIZE + M.TILE_SIZE // 2,
            row * M.TILE_SIZE + M.TILE_SIZE // 2)


def open_point():
    """A wide open, non-collidable spot for pure-physics probes."""
    return straight_road_point()


def drive(g, car, throttle=1.0, steer=0.0, handbrake=False, steps=1):
    for _ in range(steps):
        car.input_throttle = throttle
        car.input_steer = steer
        car.input_handbrake = handbrake
        car.physics_step()


# --------------------------------------------------------------------------
# 1. Camera framing
# --------------------------------------------------------------------------
def probe_camera():
    g = game()
    worst = 0.0
    worst_head = None
    offscreen = 0
    rows = []
    for k in range(8):
        ang = k * math.tau / 8.0
        x, y = M.MAP_WIDTH // 2, M.MAP_HEIGHT // 2
        car = put_in_car(g, x, y, ang)
        car.angle = ang
        # ignore geometry: we want pure camera behaviour at speed
        max_off = (0.0, 0.0)
        for i in range(240):
            car.velocity = car.max_speed
            car.rect.center = (int(x + math.cos(ang) * car.max_speed * i),
                               int(y + math.sin(ang) * car.max_speed * i))
            if not (40 < car.rect.centerx < M.MAP_WIDTH - 40
                    and 40 < car.rect.centery < M.MAP_HEIGHT - 40):
                break
            lead = g._camera_lead()
            g.camera.center_on(car.rect, lead)
            sx, sy = g.camera.apply_pos(car.rect.center)
            ox, oy = abs(sx - M.SCREEN_WIDTH / 2), abs(sy - M.SCREEN_HEIGHT / 2)
            max_off = (max(max_off[0], ox), max(max_off[1], oy))
            if not (18 <= sx <= M.SCREEN_WIDTH - 18 and 18 <= sy <= M.SCREEN_HEIGHT - 18):
                offscreen += 1
        # fraction of the half-viewport consumed
        fx = max_off[0] / (M.SCREEN_WIDTH / 2)
        fy = max_off[1] / (M.SCREEN_HEIGHT / 2)
        rows.append((math.degrees(ang), max_off[0], max_off[1], fx, fy))
        worst = max(worst, fx, fy)
        if max(fx, fy) >= worst - 1e-9:
            worst_head = math.degrees(ang)
    print("  heading   off-x   off-y   frac-x  frac-y")
    for d, ox, oy, fx, fy in rows:
        flag = "  <-- OFF SCREEN" if max(fx, fy) >= 1.0 else ""
        print(f"   {d:5.0f}   {ox:5.0f}   {oy:5.0f}    {fx:.2f}    {fy:.2f}{flag}")
    print(f"  worst viewport fraction used: {worst:.2f} (heading {worst_head:.0f})")
    print(f"  frames with the car outside the safe frame: {offscreen}")
    return worst


# --------------------------------------------------------------------------
# 2. Handling: yaw rate and turn radius vs speed
# --------------------------------------------------------------------------
def probe_handling():
    g = game()
    print("  speed  speed%   yaw deg/s   radius px   90deg in px   lat slip")
    out = []
    for frac in (0.25, 0.5, 0.75, 1.0):
        x, y = open_point()
        car = put_in_car(g, x, y, 0.0)
        top = car.max_speed
        v = top * frac
        # settle at speed on an empty plain (no collision interference)
        car.velocity = v
        for _ in range(60):
            car.rect.center = (x, y)
            drive(g, car, throttle=0.0, steer=1.0)
            car.velocity = v
        # measure steady-state yaw
        a0 = car.angle
        for _ in range(60):
            car.rect.center = (x, y)
            drive(g, car, throttle=0.0, steer=1.0)
            car.velocity = v
        yaw = abs(car.angle - a0) / 1.0        # rad per second (60 steps)
        deg = math.degrees(yaw)
        radius = (v * 60.0) / yaw if yaw > 1e-6 else float('inf')
        arc90 = radius * math.pi / 2.0
        out.append((v, frac, deg, radius, arc90, car.slip))
        print(f"  {v:5.2f}   {frac*100:3.0f}%   {deg:8.1f}   {radius:8.0f}   "
              f"{arc90:9.0f}   {car.slip:6.2f}")
    return out


def probe_handbrake():
    g = game()
    x, y = open_point()
    car = put_in_car(g, x, y, 0.0)
    v = car.max_speed
    car.velocity = v
    a0 = car.angle
    peak_slip = 0.0
    for i in range(60):
        car.rect.center = (x, y)
        drive(g, car, throttle=0.35, steer=1.0, handbrake=True)
        car.velocity = max(car.velocity, v * 0.45)
        peak_slip = max(peak_slip, car.slip)
    turned = math.degrees(abs(car.angle - a0))
    print(f"  handbrake: {turned:.0f} deg in 1.0s, peak slip {peak_slip:.2f}, "
          f"exit speed {car.velocity:.2f}/{v:.2f}")
    return turned


def probe_reverse():
    """Measure whether reverse is usable, legible, steerable, and unwedged."""
    g = game()
    x, y = straight_road_point()

    # From rest: when does integer Rect movement first become visible, and how
    # much ground does one second of held reverse produce?
    car = put_in_car(g, x, y, 0.0)
    start_x = car.rect.centerx
    first_move = None
    for frame in range(1, M.FPS + 1):
        drive(g, car, throttle=-1.0)
        if first_move is None and car.rect.centerx < start_x:
            first_move = frame
    print(f"  standstill: first rearward pixel frame {first_move}, "
          f"1.0s speed {car.velocity:.2f}, distance {start_x - car.rect.centerx}px, "
          f"gear {car.drive_gear()}")

    # Full forward speed through braking, neutral, and into reverse.
    car = put_in_car(g, x, y, 0.0)
    car.velocity = car.max_speed
    start_x = car.rect.centerx
    zero_frame = reverse_origin_frame = None
    for frame in range(1, M.FPS * 2 + 1):
        drive(g, car, throttle=-1.0)
        if zero_frame is None and car.velocity <= 0.0:
            zero_frame = frame
        if reverse_origin_frame is None and car.rect.centerx < start_x:
            reverse_origin_frame = frame
    print(f"  transition: velocity crossed zero frame {zero_frame}, "
          f"back past start frame {reverse_origin_frame}, "
          f"2.0s displacement {car.rect.centerx - start_x:+d}px")

    # Positive steering input must yaw in the opposite direction while backing.
    yaws = {}
    for label, velocity in (("forward", 2.0), ("reverse", -2.0)):
        car = put_in_car(g, x, y, 0.0)
        home = car.rect.center
        for _ in range(20):
            car.rect.center = home
            car.velocity = velocity
            drive(g, car, throttle=0.0, steer=1.0)
        yaws[label] = math.degrees(car.angle)
    print(f"  steering: right input forward yaw {yaws['forward']:+.1f} deg, "
          f"reverse yaw {yaws['reverse']:+.1f} deg")

    # Put the bumper against a solid tile, register a head-on, then back away.
    wall = None
    for row in range(4, M.MAP_TILES_H - 4):
        for col in range(4, M.MAP_TILES_W - 4):
            if (M.GAME_MAP[row][col]['collidable']
                    and M.tile_type_at(col - 1, row) == M.TILE_ROAD
                    and M.tile_type_at(col - 2, row) == M.TILE_ROAD):
                wall = (col, row)
                break
        if wall is not None:
            break
    col, row = wall
    wall_left = col * M.TILE_SIZE
    car = put_in_car(g, wall_left - M.VEHICLE_DEFAULT_W // 2 - 1,
                     row * M.TILE_SIZE + M.TILE_SIZE // 2, 0.0)
    car.velocity = 2.0
    hits = 0
    for _ in range(20):
        car.input_throttle = 1.0
        car.input_steer = 0.0
        hits += bool(car.physics_step())
    contact_x = car.rect.centerx
    for _ in range(45):
        drive(g, car, throttle=-1.0)
    print(f"  wall: {hits} head-on contacts, retreated "
          f"{contact_x - car.rect.centerx}px, final speed {car.velocity:.2f}, "
          f"blocked {M.is_blocked(car.rect)}")
    return first_move, zero_frame, yaws, contact_x - car.rect.centerx


def probe_corner(handbrake=False, label="brake-and-turn"):
    """A competent driver taking a real 90 degree grid corner.

    Cruises in at `entry`, brakes to `corner_v` on the approach, turns, then
    powers out - which is what a player actually does. Reports the highest
    cruise speed the corner survives cleanly.
    """
    g = game()
    lines = sorted(M.ROAD_LINES)
    row, col = lines[6], lines[4]
    cx = col * M.TILE_SIZE + M.TILE_SIZE // 2
    cy = row * M.TILE_SIZE + M.TILE_SIZE // 2
    print(f"  [{label}]  cruise   corner v   result                 exit v  hits")
    best = None
    for frac in (0.4, 0.55, 0.7, 0.85, 1.0):
        car = put_in_car(g, cx - 460, cy, 0.0)
        top = car.max_speed
        entry = top * frac
        car.velocity = entry
        corner_v = top * (0.75 if handbrake else 0.42)
        hits = 0
        scrapes = 0
        done = False
        hb_left = 0
        turning = False
        # aim point: down the middle of the street we are turning into
        aim = (cx, cy + 150)
        for i in range(600):
            dx = cx - car.rect.centerx
            hb = False
            if not turning and dx > 130:      # cruise
                steer, thr = 0.0, (1.0 if abs(car.velocity) < entry else 0.0)
            elif not turning and dx > 34:     # brake zone
                steer = 0.0
                thr = -1.0 if abs(car.velocity) > corner_v else 0.0
                if handbrake and abs(car.velocity) <= corner_v and dx < 70:
                    hb_left = 20
            else:                             # turn in and power out
                turning = True
                diff = (math.atan2(aim[1] - car.rect.centery,
                                   aim[0] - car.rect.centerx)
                        - car.angle + math.pi) % math.tau - math.pi
                steer = max(-1.0, min(1.0, diff * 2.4))
                thr = 0.85 if abs(diff) < 0.5 else 0.5
                if hb_left > 0 and abs(diff) > 0.4:
                    hb, hb_left = True, hb_left - 1
            car.input_throttle = thr
            car.input_steer = steer
            car.input_handbrake = hb
            bx, by = car.rect.center
            if car.physics_step():
                hits += 1
            moved = math.hypot(car.rect.centerx - bx, car.rect.centery - by)
            if abs(car.velocity) > 1.0 and moved < abs(car.velocity) * 0.55:
                scrapes += 1
            if car.rect.centery > cy + 190 and abs(car.velocity) > 0.5:
                done = True
                break
        rough = hits + scrapes
        verdict = ("clean" if done and rough == 0 else
                   f"scraped through ({rough})" if done else "failed")
        print(f"            {entry:5.2f}   {corner_v:6.2f}     {verdict:22} "
              f"{car.velocity:5.2f}  {rough:4d}")
        if done and rough == 0:
            best = entry
    if best:
        print(f"            -> corner survives a {best:.2f} px/step cruise "
              f"({best / top * 100:.0f}% of top speed)")
    return best


def probe_corner_hb():
    return probe_corner(handbrake=True, label="handbrake")


# --------------------------------------------------------------------------
# 3. Police balance
# --------------------------------------------------------------------------
def probe_police():
    g = game()
    print("  star  cop top  player top   gap after 10s   verdict")
    for star in range(1, 6):
        x, y = straight_road_point()
        car = put_in_car(g, x, y, 0.0)
        g.wanted_level = star
        g.police = []
        cop = M.Car(x - 300, y, color=M.POLICE_COLOR, variant='police')
        cop.driver = 'police'
        cop.angle = 0.0
        cop.last_seen = car.rect.center
        cop.search_timer = M.COP_SEARCH_STEPS
        g.police = [cop]
        g.cop_dispatch = 10 ** 6         # no reinforcements mid-probe
        start_gap = 300.0
        for i in range(600):
            car.input_throttle = 1.0
            car.input_steer = 0.0
            car.input_handbrake = False
            car.physics_step()
            cop.max_speed = M.COP_SPEED_BY_STAR[star]
            cop.chase_ai(car.rect.center, brake_at=34)
            g.camera.center_on(car.rect, (0, 0))
        gap = math.hypot(cop.rect.centerx - car.rect.centerx,
                         cop.rect.centery - car.rect.centery)
        delta = gap - start_gap
        verdict = ("cop gains" if delta < -20 else
                   "player pulls away" if delta > 20 else "matched")
        print(f"   {star}    {M.COP_SPEED_BY_STAR[star]:5.2f}    {car.max_speed:6.2f}"
              f"      {gap:6.0f} ({delta:+.0f})   {verdict}"
              f"   [v player {car.velocity:.2f} cop {cop.velocity:.2f}]")
    g.wanted_level = 0
    g.police = []


def probe_foot_escape():
    """Ten seconds down an open street, holding sprint whenever it is ready."""
    g = game()
    if g.driving is not None:
        g.driving.driver = None
        g.driving = None
    x, y = straight_road_point()
    g.player_rect.center = (x, y)
    g.sync_player_float()
    g.player_dir = [1.0, 0.0]
    g.sprinting = True
    g.wanted_level = 1
    cop = M.FootCop(x - 120, y)
    cop.angle = 0.0
    cop.alert = 'chase'
    cop.last_seen = g.player_rect.center
    g.foot_police = [cop]
    min_gap = 10 ** 9
    lost_at = None
    for step in range(M.FPS * 10):
        g.move_player_on_foot()
        seen, _touching = g.update_foot_police(
            1, g.player_rect, g.player_rect.center)
        gap = math.hypot(cop.rect.centerx - g.player_rect.centerx,
                         cop.rect.centery - g.player_rect.centery)
        min_gap = min(min_gap, gap)
        if not seen and lost_at is None:
            lost_at = step
    final_gap = math.hypot(cop.rect.centerx - g.player_rect.centerx,
                           cop.rect.centery - g.player_rect.centery)
    lost = f"{lost_at / M.FPS:.1f}s" if lost_at is not None else "never"
    print(f"  start 120px  closest {min_gap:.0f}px  final {final_gap:.0f}px"
          f"  sight broken {lost}  stamina {g.player_stamina:.0f}/{M.PLAYER_STAMINA_MAX:.0f}")
    g.wanted_level = 0
    g.foot_police = []


def probe_cop_handling():
    g = game()
    x, y = open_point()
    cop = M.Car(x, y, color=M.POLICE_COLOR, variant='police')
    cop.driver = 'police'
    cop.max_speed = M.COP_SPEED_BY_STAR[5]
    cop.velocity = cop.max_speed
    a0 = cop.angle = 0.0
    for _ in range(60):
        cop.rect.center = (x, y)
        cop.input_throttle = 0.0
        cop.input_steer = 1.0
        cop.input_handbrake = False
        cop.physics_step()
        cop.velocity = cop.max_speed
    deg = math.degrees(abs(cop.angle - a0))
    print(f"  5-star cruiser at top speed turns {deg:.0f} deg/s "
          f"(player: see handling probe)")


# --------------------------------------------------------------------------
# 4. Traffic health
# --------------------------------------------------------------------------
def probe_traffic(steps=1800):
    g = game()
    x, y = straight_road_point()
    put_in_car(g, x, y, 0.0)
    overlaps = []
    stalled = []
    speeds = []
    worst_pileup = 0
    for i in range(steps):
        if g.driving is None or g.state != M.STATE_PLAYING:
            g.state = M.STATE_PLAYING
            g.wanted_level = 0
            g.police = []
            put_in_car(g, *straight_road_point())
        g.driving.input_throttle = 1.0 if (i // 120) % 2 == 0 else 0.0
        g.driving.input_steer = 0.0
        g.update()
        if i % 15:
            continue
        moving = [c for c in g.cars if c.driver is None and not c.parked]
        n = 0
        for a in range(len(moving)):
            ra = g.traffic_footprint(moving[a])
            for b in range(a + 1, len(moving)):
                if ra.colliderect(g.traffic_footprint(moving[b])):
                    n += 1
        overlaps.append(n)
        worst_pileup = max(worst_pileup, n)
        stalled.append(sum(1 for c in moving if c.stall > 60))
        if moving:
            speeds.append(sum(abs(c.velocity) for c in moving) / len(moving))
    print(f"  moving cars: {len([c for c in g.cars if c.driver is None and not c.parked])}"
          f"  parked: {len([c for c in g.cars if c.parked])}"
          f"  peds: {len(g.pedestrians)}")
    print(f"  overlapping AI-car pairs: mean {sum(overlaps)/len(overlaps):.2f}, "
          f"worst {worst_pileup}")
    print(f"  cars stalled >1s: mean {sum(stalled)/len(stalled):.2f}, "
          f"worst {max(stalled)}")
    print(f"  mean traffic speed: {sum(speeds)/len(speeds):.2f} "
          f"/ {M.traffic_TRAFFIC_MAX_SPEED:.2f} cap")
    return sum(overlaps) / len(overlaps), max(stalled)


def probe_junctions(steps=2000):
    """Where the residual traffic overlaps happen, and whether they are junctions."""
    g = game()
    x, y = straight_road_point()
    put_in_car(g, x, y, 0.0)
    by_tile = {}
    events = junction_events = 0
    for _ in range(steps):
        g.driving.input_throttle = 0.0
        g.driving.input_steer = 0.0
        g.update()
        moving = [c for c in g.cars if c.driver is None and not c.parked]
        for i, a in enumerate(moving):
            for b in moving[i + 1:]:
                if not g.traffic_footprint(a).colliderect(g.traffic_footprint(b)):
                    continue
                over = g.traffic_footprint(a).clip(g.traffic_footprint(b))
                col = over.centerx // M.TILE_SIZE
                row = over.centery // M.TILE_SIZE
                tile = (col, row)
                by_tile[tile] = by_tile.get(tile, 0) + 1
                events += 1
                if M.traffic__is_junction(col, row):
                    junction_events += 1
    pct = 100.0 * junction_events / max(1, events)
    busiest = sorted(by_tile.items(), key=lambda item: (-item[1], item[0]))[:8]
    print(f"  overlap events: {events}; on junctions: {junction_events} ({pct:.1f}%)")
    print("  busiest tiles: " + ", ".join(
        f"{tile}={count}{'*' if M.traffic__is_junction(*tile) else ''}"
        for tile, count in busiest))
    return events, junction_events, by_tile


def probe_visuals():
    """Render the map trouble spots for side-by-side visual inspection."""
    out_dir = os.environ.get(
        'GTASTL_SHOT_DIR', os.path.join(tempfile.gettempdir(), 'gtastl-visuals'))
    os.makedirs(out_dir, exist_ok=True)
    g = game()
    g.driving = None
    views = {
        'arch_eads': (86, 35),
        'grand_center': (57, 35),
        'union_station': (66, 46),
        'downtown_routes': (68, 48),
        'hill_hydrants': (24, 53),
        'manchester': (31, 44),
        'gravois_bevo': (37, 85),
    }
    for name, (col, row) in views.items():
        g.player_fx = col * M.TILE_SIZE + M.TILE_SIZE * 0.5
        g.player_fy = row * M.TILE_SIZE + M.TILE_SIZE * 0.5
        g.player_rect.center = (round(g.player_fx), round(g.player_fy))
        g.camera.snap_to(g.player_rect)
        g.draw()
        path = os.path.join(out_dir, f'{name}.png')
        pygame.image.save(g.screen, path)
        print(f"  wrote {path}")
    overview = g.build_map_overview()
    path = os.path.join(out_dir, 'map_overview.png')
    pygame.image.save(overview, path)
    print(f"  wrote {path}")


def probe_onscreen(steps=900):
    """How much of the population is actually in frame - density that reads."""
    g = game()
    x, y = straight_road_point()
    put_in_car(g, x, y, 0.0)
    seen_cars = []
    seen_parked = []
    seen_peds = []
    for i in range(steps):
        if g.driving is None or g.state != M.STATE_PLAYING:
            g.state = M.STATE_PLAYING
            g.wanted_level = 0
            g.police = []
            put_in_car(g, *straight_road_point())
        g.driving.input_throttle = 1.0
        g.driving.input_steer = 0.0
        g.update()
        if i % 20:
            continue
        cam = g.camera
        def vis(e):
            sx, sy = cam.apply_pos(e.rect.center)
            return -30 < sx < M.SCREEN_WIDTH + 30 and -30 < sy < M.SCREEN_HEIGHT + 30
        seen_cars.append(sum(1 for c in g.cars if vis(c) and not c.parked))
        seen_parked.append(sum(1 for c in g.cars if vis(c) and c.parked))
        seen_peds.append(sum(1 for p in g.pedestrians if vis(p)))
    print(f"  on screen: moving cars {sum(seen_cars)/len(seen_cars):.1f} "
          f"(max {max(seen_cars)}),  parked {sum(seen_parked)/len(seen_parked):.1f} "
          f"(max {max(seen_parked)}),  peds {sum(seen_peds)/len(seen_peds):.1f} "
          f"(max {max(seen_peds)})")


# --------------------------------------------------------------------------
# 5. A scripted driver good enough to judge a chase by
# --------------------------------------------------------------------------
DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))


class GridDriver:
    """Drives the road grid the way a competent player does.

    Holds a lane, brakes into a junction it means to turn at, uses the
    handbrake on tight ones, powers out. Good enough that a chase probe is
    measuring the game rather than measuring a bad autopilot.
    """

    def __init__(self, car, rng, turn_chance=0.35, handbrake=True,
                 careful=False, game=None):
        self.car = car
        self.rng = rng
        self.turn_chance = turn_chance
        self.handbrake = handbrake
        # A careful driver exists to separate "the game did this to me" from
        # "the bot drove into it". It holds a lower cruise, and it lifts off
        # for anything in its lane - traffic, a pedestrian, a spike strip -
        # rather than shouldering through, which is what the default driver
        # does and what makes its damage figures hard to read.
        self.careful = careful
        self.game = game
        self.cruise = car.max_speed * (0.60 if careful else 1.0)
        self.yields = 0
        self.d = int(round(car.angle / (math.pi / 2))) % 4
        self.line = self._line_for(self.d)
        self.next_dir = None
        self.hb_left = 0
        self.wall_hits = 0
        self.speeds = []
        self.junction = None       # latched once we commit to it
        self.stuck = 0
        self.reverse = 0
        self.pinned = 0            # consecutive steps facing a known wall
        self.trail = collections.deque(maxlen=45)
        self.walls = 0             # times it had to re-plan off a wall

    def _hazard_ahead(self):
        """Anything in our lane worth lifting off for, within braking range."""
        if self.game is None:
            return False
        car = self.car
        hx, hy = DIRS[self.d]
        reach = int(52 + abs(car.velocity) * 18)
        if hx:
            box = pygame.Rect(0, 0, reach, car.rect.height + 14)
            box.centery = car.rect.centery
            box.left = car.rect.right if hx > 0 else car.rect.left - reach
        else:
            box = pygame.Rect(0, 0, car.rect.width + 14, reach)
            box.centerx = car.rect.centerx
            box.top = car.rect.bottom if hy > 0 else car.rect.top - reach
        game = self.game
        for other in game.cars:
            if other is not car and box.colliderect(other.rect):
                return True
        for ped in game.pedestrians:
            if box.colliderect(ped.rect):
                return True
        for block in getattr(game, 'roadblocks', ()):
            if box.colliderect(block['strip']):
                return True
        return False

    @staticmethod
    def _corridor_clear(col, row, d, steps=3):
        """Can a car actually drive this way? Asks collision, not tile type.

        `traffic__segment_clear` asks "is every tile TILE_ROAD", which is the
        right question for ambient traffic - that AI follows named lanes and
        must not wander onto a lawn. It is the wrong question for a player,
        and asking it made this driver BLIND: inside Forest Park every grid
        lane is a TILE_PARK, so all four directions came back blocked, and the
        driver could then neither plan a turn nor re-face during recovery. It
        just ground whatever was in front of it.

        Measured with the old test: 1,144 of 2,400 frames spent against the
        Grand Basin's west face, and all fifteen chase runs finishing ~345px
        from where they started after "driving" up to 12.6k px. The probe's
        fixed start is one tile from the park's edge, so every run drove
        straight into that blind spot.
        """
        dx, dy = DIRS[d]
        for step in range(1, steps + 1):
            c, r = col + dx * step, row + dy * step
            if not (0 <= c < M.MAP_TILES_W and 0 <= r < M.MAP_TILES_H):
                return False
            if M.GAME_MAP[r][c]['collidable']:
                return False
        return True

    def _replan(self, avoid=None):
        """Face a direction that is actually open from where we are standing.

        Preference order is turn, turn, reverse of travel, straight on - the
        straight-on option comes last because we only ever call this when the
        way we were going has stopped working.
        """
        col = self.car.rect.centerx // M.TILE_SIZE
        row = self.car.rect.centery // M.TILE_SIZE
        for nd in ((self.d + 1) % 4, (self.d + 3) % 4, (self.d + 2) % 4, self.d):
            if nd == avoid:
                continue
            if self._corridor_clear(col, row, nd, 3):
                self.d = nd
                self.line = self._line_for(nd)
                self.junction = None
                self.next_dir = None
                self.walls += 1
                return True
        return False

    def _line_for(self, d):
        c = self.car.rect.centerx // M.TILE_SIZE
        r = self.car.rect.centery // M.TILE_SIZE
        lines = sorted(M.ROAD_LINES)
        want = r if DIRS[d][1] == 0 else c
        return min(lines, key=lambda L: abs(L - want))

    def _next_junction(self):
        hx, hy = DIRS[self.d]
        lines = sorted(M.ROAD_LINES)
        px, py = self.car.rect.center
        idx = (px if hx else py) // M.TILE_SIZE
        cands = [L for L in lines if (L - idx) * (hx + hy) > 0]
        if not cands:
            return None
        L = min(cands, key=lambda L: abs(L - idx))
        centre = L * M.TILE_SIZE + M.TILE_SIZE // 2
        if hx:
            return (centre, self.line * M.TILE_SIZE + M.TILE_SIZE // 2)
        return (self.line * M.TILE_SIZE + M.TILE_SIZE // 2, centre)

    def step(self):
        car = self.car
        # --- stuck recovery: back out and take the next turn instead ------
        # Speed alone is not enough to notice being stuck. Grinding a wall is
        # a limit cycle - throttle, hit, bounce back at -0.18, throttle again -
        # and the bounce crosses this threshold often enough to keep resetting
        # the counter. Measured: the driver ground the Grand Basin's west face
        # for 1,144 of 2,400 frames and never once triggered recovery. So also
        # ask the only question that matters, which is whether we have
        # actually gone anywhere.
        if abs(car.velocity) < 0.35:
            self.stuck += 1
        else:
            self.stuck = 0
        self.trail.append(car.rect.center)
        if len(self.trail) == self.trail.maxlen:
            first, last = self.trail[0], self.trail[-1]
            if math.hypot(last[0] - first[0], last[1] - first[1]) < 40:
                self.stuck += 3
        if self.stuck > 24 and self.reverse <= 0:
            self.stuck = 0
            self.reverse = 34
        if self.reverse > 0:
            self.reverse -= 1
            car.input_throttle = -1.0
            car.input_steer = self.rng.choice((-1.0, 1.0))
            car.input_handbrake = False
            self.junction = None
            self.next_dir = None
            if self.reverse == 0:
                # face somewhere that is actually open
                c = car.rect.centerx // M.TILE_SIZE
                r = car.rect.centery // M.TILE_SIZE
                for nd in self.rng.sample(range(4), 4):
                    if self._corridor_clear(c, r, nd, 3):
                        self.d = nd
                        self.line = self._line_for(nd)
                        break
            self.speeds.append(abs(car.velocity))
            self.turning_now = False
            return
        hx, hy = DIRS[self.d]
        # --- never drive into a wall we can already see --------------------
        # Forest Park's grid lanes are park tiles, so they have no kerb to
        # hold a car in its lane; drift one tile north of line 37 and the
        # Grand Basin is dead ahead. The old driver detected that the tile in
        # front was blocked and threw throttle at it anyway, which is how half
        # of every low-star chase was spent parked against a lake. Re-plan
        # instead, which is what a player does.
        def blocked_ahead():
            reach = int(M.TILE_SIZE * 0.7)
            probe = car.rect.move(int(DIRS[self.d][0] * reach),
                                  int(DIRS[self.d][1] * reach))
            return M.is_blocked(probe)

        if blocked_ahead():
            self.pinned += 1
            if self.pinned >= 3:
                self.pinned = 0
                if not self._replan(avoid=self.d):
                    self.stuck += 12          # boxed in: let recovery reverse
                hx, hy = DIRS[self.d]
        else:
            self.pinned = 0
        wall_ahead = blocked_ahead()
        px, py = car.rect.center
        # Latch the junction we are working on. Recomputing it every step means
        # that the moment the car's centre crosses the crossing, "the next
        # junction" jumps a whole block ahead and the turn is abandoned
        # half-completed, with the nose pointed at a wall.
        if self.junction is None:
            self.junction = self._next_junction()
            if self.junction is None:
                # No junction ahead: the map edge or the river. Turn around at
                # the last crossing rather than grinding on the boundary.
                self.stuck += 6
        j = self.junction
        dist = 1e9
        if j is not None:
            dist = (j[0] - px) * hx + (j[1] - py) * hy
            if dist < -80:                      # well past it: let it go
                self.junction = None
                self.next_dir = None
                j, dist = None, 1e9

        # commit to an exit while there is still room to slow down. Landmarks
        # are stamped OVER the road grid (the stadium, Forest Park, the Arch
        # grounds), so "it is a road line" does not mean "you can drive down
        # it" - check the corridor before committing, exactly as the traffic
        # AI does, or you will drive into the side of Busch Stadium.
        if self.next_dir is None and dist < 210 and j is not None:
            jc, jr = j[0] // M.TILE_SIZE, j[1] // M.TILE_SIZE
            opts = []
            for nd in (self.d, (self.d + 1) % 4, (self.d + 3) % 4):
                if self._corridor_clear(jc, jr, nd, 9):
                    opts.append(nd)
            if not opts:
                opts = [(self.d + 2) % 4]
            straight = self.d if self.d in opts else None
            turns = [o for o in opts if o != self.d]
            if turns and (straight is None or self.rng.random() < self.turn_chance):
                self.next_dir = self.rng.choice(turns)
            else:
                self.next_dir = straight if straight is not None else opts[0]

        turning = self.next_dir is not None and self.next_dir != self.d
        corner_v = car.max_speed * (0.72 if self.handbrake else 0.42)

        hb = False
        if j is not None and dist < 30 and turning:
            # inside the junction: aim down the street we are turning into
            nd = self.next_dir
            nhx, nhy = DIRS[nd]
            new_line = (j[0] // M.TILE_SIZE) if nhy else (j[1] // M.TILE_SIZE)
            aim_lat = new_line * M.TILE_SIZE + M.TILE_SIZE // 2
            if nhy:
                aim = (aim_lat, j[1] + nhy * 150)
            else:
                aim = (j[0] + nhx * 150, aim_lat)
            if self.hb_left > 0:
                hb, self.hb_left = True, self.hb_left - 1
            if abs((math.atan2(nhy, nhx) - car.angle + math.pi) % math.tau - math.pi) < 0.20:
                self.d = nd
                self.line = new_line
                self.next_dir = None
                self.junction = None
                self.hb_left = 0
        else:
            lat = self.line * M.TILE_SIZE + M.TILE_SIZE // 2
            look = 110
            aim = (px + hx * look, lat) if hy == 0 else (lat, py + hy * look)

        diff = (math.atan2(aim[1] - py, aim[0] - px) - car.angle + math.pi) % math.tau - math.pi
        car.input_steer = max(-1.0, min(1.0, diff * 2.6))

        # brake into a corner, power out of one
        if turning and 30 <= dist < 190 and abs(car.velocity) > corner_v:
            car.input_throttle = -1.0
            if self.handbrake:
                self.hb_left = 16
        elif not turning and j is not None and -20 < dist < 30:
            self.junction = None                # drove straight through
            car.input_throttle = 1.0
        elif abs(diff) > 0.55:
            car.input_throttle = 0.35
        else:
            car.input_throttle = 1.0
        if self.careful:
            if abs(car.velocity) > self.cruise:
                car.input_throttle = min(car.input_throttle, -0.35)
            if self._hazard_ahead():
                car.input_throttle = -1.0
                hb = False
                self.yields += 1
        if wall_ahead and car.input_throttle > 0.0:
            # Still facing something solid after the re-plan (a corner pocket,
            # or a turn we have not rotated into yet). Come off the throttle
            # and let the steering bring the nose round instead of pushing.
            car.input_throttle = -1.0 if car.velocity > 0.35 else 0.0
        car.input_handbrake = hb
        self.turning_now = turning and dist < 190
        self.speeds.append(abs(car.velocity))


def probe_drive(steps=2400, seed=3):
    """Can the grid actually be driven at speed? Distance covered, walls hit."""
    g = game()
    rng = random.Random(seed)
    x, y = straight_road_point()
    car = put_in_car(g, x, y, 0.0)
    d = GridDriver(car, rng)
    p0 = car.rect.center
    hits = 0
    far = 0.0
    in_turn = 0
    spots = []
    for i in range(steps):
        d.step()
        if car.physics_step():
            hits += 1
            if getattr(d, 'turning_now', False):
                in_turn += 1
            elif len(spots) < 8:
                c, r = car.rect.centerx // M.TILE_SIZE, car.rect.centery // M.TILE_SIZE
                spots.append((c, r, M.GAME_MAP[r][c]['type'],
                              M.GAME_MAP[r][c]['landmark'], d.d, d.line))
        far = max(far, math.hypot(car.rect.centerx - p0[0], car.rect.centery - p0[1]))
    mean_v = sum(d.speeds) / len(d.speeds)
    print(f"  of {hits} hits, {in_turn} were mid-corner, {hits - in_turn} on a straight")
    for sp in spots:
        print(f"     straight hit at tile {sp[0]},{sp[1]} type={sp[2]} lm={sp[3]} dir={sp[4]} line={sp[5]}")
    print(f"  {steps/60:.0f}s of grid driving: mean speed {mean_v:.2f}/{car.max_speed:.2f} "
          f"({mean_v/car.max_speed*100:.0f}%), {hits} head-on hits, "
          f"reached {far:.0f}px from the start")
    return mean_v, hits


def probe_chase_all():
    print("  star  seed   outcome                            mean gap  closest  speed  ground covered")
    for star in (1, 2, 3, 4, 5):
        for seed in (7, 11, 23):
            probe_chase(star=star, steps=3600, seed=seed)


def probe_chase(star=3, steps=3600, seed=7):
    """A real pursuit: GridDriver flees, the game's own police chase it."""
    rng = random.Random(seed)
    g = game()
    x, y = straight_road_point()
    car = put_in_car(g, x, y, 0.0)
    g.wanted_level = star
    g.heat_timer = 0
    g.cop_dispatch = 0
    # This probe compares fixed response tiers, so the tier has to actually
    # hold. Locking the offence cooldowns is not enough: at 4.7 px/step the
    # scripted driver racks up a twelve-kill pedestrian combo, and that path
    # (Game.bump_combo -> "YOU MONSTER") forces three stars on purpose,
    # un-cooldowned, because mowing down twelve people should make the police
    # care. Measured before this line existed: a labelled ONE-star run sat at
    # one star for 664 frames and then ran the remaining 1,136 at THREE, so
    # every row of the chases table was fiction and the difficulty curve it
    # printed was noise. Pin the level each frame instead of raising a floor.
    g.infraction_at = {key: 10 ** 9 for key in M.INFRACTION_COOLDOWN}
    g.peak_star = star
    d = GridDriver(car, rng)
    ended = None
    cause = "escaped"
    gaps = []
    p0 = car.rect.center
    ground = 0.0
    prev = p0
    for i in range(steps):
        d.step()
        g.update()
        ground += math.hypot(car.rect.centerx - prev[0], car.rect.centery - prev[1])
        prev = car.rect.center
        if g.state == M.STATE_DEAD:
            ended, cause = i, ("BUSTED " if g.busted_flash else "WASTED ") + (g.death_note or "?")
            break
        if g.driving is None:
            ended, cause = i, f"car gone (hp {car.hp:.0f} burn {car.burn})"
            break
        near = [math.hypot(p.rect.centerx - car.rect.centerx,
                           p.rect.centery - car.rect.centery)
                for p in list(g.police) + list(g.foot_police)]
        if near:
            gaps.append(min(near))
        g.wanted_level = star
    dur = (ended if ended is not None else steps) / 60.0
    mean_v = sum(d.speeds) / max(1, len(d.speeds))
    away = math.hypot(prev[0] - p0[0], prev[1] - p0[1])
    print(f"   {star}    {seed:3d}   {dur:5.1f}s {cause:28} "
          f"{sum(gaps)/max(1,len(gaps)):7.0f}  {min(gaps) if gaps else -1:7.0f}"
          f"  {mean_v:4.2f}  {ground/1000:5.1f}k px driven, {away:5.0f}px from home")
    g.wanted_level = 0
    g.police = []
    g.foot_police = []
    g.state = M.STATE_PLAYING
    return dur


def probe_wear(steps=3600, seed=5, star=0):
    """Where does a chase car's health actually go? Split the damage sources.

    At star=0 this measures ordinary city wear, which is the baseline. Pass a
    star level to measure it under pursuit, which is the number that matters:
    once the scripted driver could actually travel, twelve of fifteen chase
    runs ended WASTED - WRECK TOTALLED rather than busted, at every star
    including one, so it is worth knowing whether that is the police, the
    traffic, or the driver's own kerbs.
    """
    g = game()
    rng = random.Random(seed)
    x, y = straight_road_point()
    car = put_in_car(g, x, y, 0.0)
    g.wanted_level = star
    g.heat_timer = 0
    g.cop_dispatch = 0
    # Lock offence cooldowns: the scripted driver clips traffic, and without
    # this every labelled run silently escalates to a five-star response.
    g.infraction_at = {key: 10 ** 9 for key in M.INFRACTION_COOLDOWN}
    tally = {'wall': 0.0, 'traffic': 0.0, 'shot': 0.0, 'spikes': 0.0}
    # Wrap Car.damage, not Car.crash_damage. crash_damage is only the
    # sustained-contact path; gunfire, potholes, explosions and trains all
    # call damage() directly, so a tally built on crash_damage silently
    # dropped them. Measured: an 18s four-star run lost 99hp and the old
    # tally accounted for 16 of it. Below three stars the two agree, which is
    # exactly why the gap went unnoticed - that is when the police open fire.
    real = M.Car.damage
    src = {'k': 'shot'}

    def spy(self, amount):
        before = self.hp
        real(self, amount)
        if self is g.driving:
            tally[src['k']] += before - self.hp
    M.Car.damage = spy
    real_hc = M.Game.handle_collisions

    def hc(self):
        src['k'] = 'traffic'
        real_hc(self)
        src['k'] = 'shot'
    M.Game.handle_collisions = hc
    real_wall = M.Car.crash_damage

    def wall_spy(self, amount):
        was = src['k']
        if was != 'traffic':
            src['k'] = 'wall'
        real_wall(self, amount)
        src['k'] = was
    M.Car.crash_damage = wall_spy
    # Spike strips write car.hp directly rather than going through damage(),
    # deliberately - max(1.0, ...) is what stops them killing you outright.
    # So they are invisible to the wrapper above, and they are not small: at
    # four stars the scripted driver drives through about ten strips a run,
    # which is 80 of the 100hp it loses.
    real_rb = M.Game.update_roadblock_contacts

    def rb_spy(self):
        before = g.driving.hp if g.driving is not None else 0.0
        real_rb(self)
        if g.driving is not None:
            tally['spikes'] += max(0.0, before - g.driving.hp)
    M.Game.update_roadblock_contacts = rb_spy
    d = GridDriver(car, rng)
    hp0 = car.hp
    try:
        for i in range(steps):
            if g.driving is None or g.state != M.STATE_PLAYING:
                break
            d.step()
            g.update()
            g.wanted_level = star          # hold the tier; see probe_chase
    finally:
        M.Car.damage = real
        M.Car.crash_damage = real_wall
        M.Game.handle_collisions = real_hc
        M.Game.update_roadblock_contacts = real_rb
    label = "solo" if not star else f"{star}-star"
    lost = hp0 - car.hp
    total = sum(tally.values()) or 1.0
    print(f"  {i/60:4.0f}s {label:7} lost {lost:5.0f}/{hp0:.0f}"
          f"   contact {tally['traffic']:5.0f} ({tally['traffic']/total*100:3.0f}%)"
          f"   wall {tally['wall']:5.0f} ({tally['wall']/total*100:3.0f}%)"
          f"   shot {tally['shot']:5.0f} ({tally['shot']/total*100:3.0f}%)"
          f"   spikes {tally['spikes']:5.0f} ({tally['spikes']/total*100:3.0f}%)"
          f"   unaccounted {lost - sum(tally.values()):4.0f}")
    g.wanted_level = 0
    g.police = []
    g.foot_police = []
    g.state = M.STATE_PLAYING
    return tally


def probe_chase_wear():
    """The damage split at every star, which is what decides survivability."""
    for star in (0, 1, 2, 3, 4, 5):
        for seed in (5, 17):
            probe_wear(steps=2400, seed=seed, star=star)


def probe_careful(steps=2400, seeds=(5, 17, 29)):
    """Does a CAREFUL driver still lose the car? Aggressive vs careful.

    The point is to separate "the game did this to me" from "the bot drove
    into it". The default driver holds the throttle down and shoulders
    through traffic, so when a chase ends WRECK TOTALLED it is not obvious
    whether the pursuit was lethal or the driving was. The careful variant
    cruises at 60% and lifts off for anything in its lane, which is what a
    player who wants to keep the car does.
    """
    # "survived" alone hides the trade-off. A careful run that ends early with
    # 90hp in the tank was not wrecked, it was ARRESTED - which is the game
    # working: drive slowly enough to protect the car in a pursuit and the
    # police catch you. Report the cause so the table says that out loud.
    print("  star  driver      alive busted wrecked   secs  hp left"
          "   contact   wall   spikes   yields")
    for star in (0, 1, 2, 3, 4, 5):
        for careful in (False, True):
            alive = busted = wrecked = 0
            hp_left = []
            tallies = collections.Counter()
            yields = 0
            secs = []
            for seed in seeds:
                g = game()
                x, y = straight_road_point()
                car = put_in_car(g, x, y, 0.0)
                g.wanted_level = star
                g.heat_timer = 0
                g.cop_dispatch = 0
                g.infraction_at = {k: 10 ** 9 for k in M.INFRACTION_COOLDOWN}
                d = GridDriver(car, random.Random(seed),
                               careful=careful, game=g)
                before_spike = {'hp': car.hp}
                real_rb = M.Game.update_roadblock_contacts

                def rb_spy(self, _car=car, _t=tallies):
                    was = _car.hp
                    real_rb(self)
                    _t['spikes'] += max(0.0, was - _car.hp)
                M.Game.update_roadblock_contacts = rb_spy
                real_hc = M.Game.handle_collisions
                mark = {'k': 'wall'}

                def hc(self, _m=mark):
                    _m['k'] = 'contact'
                    real_hc(self)
                    _m['k'] = 'wall'
                M.Game.handle_collisions = hc
                real_dmg = M.Car.damage

                def dmg(self, amount, _car=car, _t=tallies, _m=mark):
                    was = self.hp
                    real_dmg(self, amount)
                    if self is _car:
                        _t[_m['k']] += was - self.hp
                M.Car.damage = dmg
                try:
                    i = 0
                    for i in range(steps):
                        if g.driving is None or g.state != M.STATE_PLAYING:
                            break
                        d.step()
                        g.update()
                        g.wanted_level = star
                finally:
                    M.Game.update_roadblock_contacts = real_rb
                    M.Game.handle_collisions = real_hc
                    M.Car.damage = real_dmg
                secs.append(i / 60.0)
                if g.state == M.STATE_PLAYING and g.driving is not None:
                    alive += 1
                elif getattr(g, 'busted_flash', 0):
                    busted += 1
                else:
                    wrecked += 1
                hp_left.append(max(0.0, car.hp))
                yields += d.yields
                g.wanted_level = 0
                g.police = []
                g.foot_police = []
                g.state = M.STATE_PLAYING
            label = "careful" if careful else "aggressive"
            n = float(len(seeds))
            print(f"   {star}    {label:10}  {alive:5d} {busted:6d} "
                  f"{wrecked:7d}  {sum(secs)/n:5.0f}s  {sum(hp_left)/n:6.0f}   "
                  f"{tallies['contact']/n:7.0f}  {tallies['wall']/n:5.0f}  "
                  f"{tallies['spikes']/n:6.0f}   {yields/n:6.0f}")


def probe_roads(steps=45):
    """Is every drivable tile actually drivable OUT of? No RNG, no autopilot.

    probe_drive is a random walk: change the map and the walk goes somewhere
    else, so its numbers move for reasons that have nothing to do with the
    change. This sweep is the opposite - it stands a car on every reachable
    tile at each of four headings, floors it, and reports the tiles it could
    not leave. Same answer every run, and it names the tile instead of the
    route, which is what you need when somebody says "I get blocked here".
    """
    boxed, oneway, tested = [], [], 0
    for r in range(M.MAP_TILES_H):
        for c in range(M.MAP_TILES_W):
            tile = M.GAME_MAP[r][c]
            if tile['collidable'] or not M.WALK_REACHABLE[r][c]:
                continue
            stuck = []
            for hi, ang in enumerate((0.0, math.pi / 2, math.pi, -math.pi / 2)):
                car = M.Car(c * M.TILE_SIZE + M.TILE_SIZE // 2,
                            r * M.TILE_SIZE + M.TILE_SIZE // 2, variant='sedan')
                car.angle = ang
                car.velocity = 0.0
                car.driver = 'player'
                car.parked = False
                if M.is_blocked(car.rect):
                    continue
                tested += 1
                x0, y0 = car.rect.center
                for _ in range(steps):
                    car.input_throttle = 1.0
                    car.input_steer = 0.0
                    car.input_handbrake = False
                    car.physics_step()
                if math.hypot(car.rect.centerx - x0, car.rect.centery - y0) < 40:
                    stuck.append('ESWN'[hi])
            if len(stuck) == 4:
                boxed.append((c, r))
            elif len(stuck) == 3:
                oneway.append((c, r, stuck))
    print(f"  {tested} (tile, heading) placements swept")
    print(f"  tiles a car cannot leave in ANY direction: {len(boxed)}")
    for t in boxed[:12]:
        tile = M.GAME_MAP[t[1]][t[0]]
        print(f"     BOXED IN {t} lm={tile.get('landmark')} "
              f"street={M.street_name(*t)}")
    print(f"  tiles with only one way out: {len(oneway)} "
          f"(map edges and levee cul-de-sacs are expected)")
    return len(boxed), len(oneway)


PROBES = {
    'camera': probe_camera,
    'handling': probe_handling,
    'handbrake': probe_handbrake,
    'reverse': probe_reverse,
    'corner': probe_corner,
    'cornerhb': probe_corner_hb,
    'police': probe_police,
    'foot': probe_foot_escape,
    'cophandling': probe_cop_handling,
    'traffic': probe_traffic,
    'junctions': probe_junctions,
    'visuals': probe_visuals,
    'onscreen': probe_onscreen,
    'chase': probe_chase,
    'chases': probe_chase_all,
    'drive': probe_drive,
    'wear': probe_wear,
    'chasewear': probe_chase_wear,
    'careful': probe_careful,
    'roads': probe_roads,
}


def main():
    global _G
    which = sys.argv[1:] or list(PROBES)
    for name in which:
        # Probes mutate traffic, population, police, and the controlled car.
        # Reusing that state made `traffic onscreen` disagree with `onscreen`
        # by as much as 0.6 visible cars. Every named measurement gets the
        # same deterministic city now, regardless of command order.
        _G = None
        print(f"\n=== {name} ===")
        PROBES[name]()
    print()


if __name__ == '__main__':
    main()

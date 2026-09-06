# STL-GTA: St. Louis Open-World Sandbox

A top-down open-world driving game inspired by the original GTA, set in St. Louis, Missouri.
Everything used at runtime is procedurally baked pixel art — the reference sheets in
`sprites/` are inspiration only and are never loaded by the game.

**The loop:** a dispatcher marks a pickup at one St. Louis landmark and a drop at another.
Get there, grab the cargo, and the clock starts. Deliver on time for cash and a streak
multiplier. Or drive like a lunatic instead — every hit, shunt and wreck feeds a chaos
multiplier and the screen screams the count back at you, until a Kill Frenzy icon or a
police roadblock or your own exploding car ends the run. No dispatcher will hand work to
someone with three cops behind them anyway.

```bash
pip install -r requirements.txt && python main.py
```

## 🎮 Features

- **A real front door**: a procedural title screen leads into a character creator with six
  baked looks and the only profile question St. Louis truly needs: **where'd you go to high
  school?** The searchable picker contains 162 verified schools across the core Missouri
  and Metro East counties (campuses under 100 students are omitted), understands aliases
  such as `SLUH`, `CBC`, `FHN`, `FZW` and `ESTL`, and saves your answer for strangers to judge.

- **A city laid out like St. Louis**: the Gateway Arch on the riverfront with downtown and the ballpark just inland, Soulard and the Anheuser-Busch brewery south along the river, a midtown spine (Grand Center → Central West End) running west to a big Forest Park, the Delmar Loop up in the north-west, and The Hill, **Ted Drewes** and Tower Grove Park down in the south. Compressed and not to scale, but recognisable in the hand — dozens of landmarks and named park features, each discoverable for score.
- **Landmarks with real shapes**: the **Arch** is a vertical catenary, so in plan only the two leg footings are solid and you walk straight under the span. **Busch Stadium** is a hard-walled bowl with one gate corridor into the field. City blocks are two bands of buildings with a service alley, a gate through the middle of every side and a courtyard in the centre — dense to look at, legible to walk. Every open tile in the game is flood-fill verified reachable from the street network, so a drop marker can never land in a sealed pocket.
- **Neighbourhoods that read differently**: shop signs and housing stock are picked per block from the neighbourhood you're in. The Hill gets `DELI`, `PIZZERIA`, `BAKERY`, `IMO'S` over brick shotguns; the Loop and Grand Center get `FOX` (with marquee bulbs), `THE GROVE`, `RECORDS` over Second Empire mansard rowhouses and painted ladies; downtown and Soulard get `OYSTER BAR`, `SLINGERS`, `CROWN`; south city gets `ANTIQUES` and `PORK STEAK`.
- **A real brick city between the roads**: every block is filled with St. Louis masonry — red / brown / buff brick and limestone — rendered in a hybrid view: dark top-down roofs with a lit south **facade**. Four real housing types: the mansard rowhouse with slate dormers, the gabled brick two-flat with its chimney, the painted lady, and the south-city shotgun with a full-width porch. Parks, surface lots and tree-lined sidewalks fill the rest.
- **A St. Louis cast on foot**: commuters, dog walkers (with dogs), shoppers, elders with canes, hi-vis road crews, joggers, plus a jazz **sax busker** in the arts districts, foam-finger crowds around Busch, and South City hoosiers with mullets and tallboys. The streamed population retypes itself by neighborhood as you travel instead of carrying downtown commuters into every district forever.
- **Busy streets, via population streaming**: the viewport sees 0.56% of the map, so a population scattered over the whole city is one you never meet — 40 pedestrians measured **0.0 visible on average**. Raising the raw count can't fix that (you'd need ~1800). Instead the pool stays modest and anything that drifts out of earshot is recycled into a ring hugging the screen edge, biased toward the way you're travelling so traffic arrives in the windscreen rather than the mirror. Measured **~10 pedestrians, ~3.5 moving cars and ~3 parked on screen while driving**, for about 5% of the frame budget. That is deliberately *fewer* cars than it used to carry: at 22 moving cars a 64px street measured **3.7 pairs of cars overlapping each other at any moment (11 at worst)** and traffic averaged 1.26 px/step against its own 3.25 cap — a city permanently jammed solid. 13 cars that are actually moving read as a busier city than 22 stacked in a knot.
- **St. Louis traffic**: ordinary cars and taxis plus a City refuse truck, box truck, school bus,
  blue/red **Route 70 MetroBus**, Hill delivery Vespa, and a rare black Trans Am with a gold
  hood bird and the radio permanently stuck on KSHE — each with its own size and handling.
  Moving traffic spawns directly in its proper lane and uses a measured long-look steering
  line, while wider asphalt aprons keep the two-lane streets from reading like alleys. Ambient
  **MetroLink** trains, a **Loop trolley**, and the Clydesdales run their own lines.
- **The $50,000 Arch Job**: bank enough money and a real multi-stage finale opens under the
  Arch: borrow a cutter from City Museum, bring a getaway car, strap 43 pounds of visible
  stainless steel to it, survive a forced five-star run to The Hill, and lose the cops in
  the gangways. Death, arrest, timeout and body-shop cheese all fail it cleanly; winning gets
  a full-screen victory beat before ordinary St. Louis starts moving again.
- **Courier jobs**: the actual game. Pick up at one landmark, deliver to another before the clock runs out. Payout scales with distance and with the time you had left, and consecutive on-time drops build a streak multiplier. An on-screen marker and an edge-of-screen chevron always point at the objective, so you are never lost on a 100×100-tile map.
- **Cash vs. score**: two separate currencies that mean different things. **Cash** comes from
  finished runs, can be banked safely beneath the Arch, and leaves via bail or a body-shop
  respray. **Score** is the chaos counter. Playing carefully and playing recklessly are genuinely different strategies.
- **Chaos multiplier (x1–x8)**: every reckless act — a hit, a shunt, a wreck — feeds a running multiplier that scales every point of score you earn. Park and it bleeds away; get **busted** or **wasted** and it's gone. The screen shouts each rung.
- **Kill Frenzy**: a pulsing icon drops on the map. Touch it and a clock starts — `MOW DOWN 14 LOCALS`, `WRECK 8 MOTORS` — for a fat score payout and free multiplier rungs. Pure GTA1 "just one more go".
- **Rampage streaks**: bowl a line of pedestrians and the per-hit value stacks, scaled by how
  fast you were going when you did it. The shout ladder runs to fifty (`GOURANGA!`,
  `SLINGER STREAK`, `TOTAL CARNAGE`, `ST LOUIS HATES YOU`, `MOUND CITY MASSACRE`, ...) and the
  window that holds a streak together **grows with the streak**, so a run through three blocks
  of sidewalk stays one run instead of dying in the gap between two crowds. `SPLAT_SPEED` and
  every other impact threshold is now a *fraction* of the top speed rather than a literal
  tuned against a top speed the game no longer has — left alone, the old 5.2 would have put
  splattering at 81% of flat out, i.e. almost never.
- **A reactive crowd**: (`GOURANGA!` at 5). Peds see a speeding car coming and scatter, dive clear, bolt when the stars light up, and knot around a fresh body. Clip one below `SPLAT_SPEED` and they go down and get back up — hit them at speed and they **don't**, leaving a stain on the road that's still there next lap.
- **Combat**: `SPACE` swings your fists — a short arc that drops a pedestrian, and finishes one already on the floor. Find a pistol crate on the street and the same key fires it; bullets kill people, punch holes in cars and cop cruisers, and discharging a firearm in public is very much a crime. Punching a car dents it; enough dents and it goes up.
- **Cars that actually hit each other**: ramming transfers momentum — the struck car gets shoved down the contact normal, yaws away from an off-centre hit, and a parked car knocked at the kerb coasts before it stops. Traffic used to absorb a full-speed broadside without twitching.
- **Impact juice**: wall slams and collisions land — screen shake, a frame of hitstop on the big ones, a spray of sparks / glass / smoke, a white flash. Floating `+N` / `$N` numbers rise off whatever you just did; big moments get a centre-screen ALL-CAPS callout.
- **WASTED / BUSTED**: cars (yours, traffic, cop) have health. Enough hits and one smokes,
  catches fire, then explodes — a blast that scatters the crowd and can chain to the next car.
  Either loss gets a readable result card, then automatically returns you beneath the Arch;
  after its opening beat, `ENTER`, `SPACE`, `E`, or gamepad `A` skips straight back to play.
- **Steal Any Car**: walk up to traffic or a parked car and press `E` to jack it — and it matters which one, because every variant now has its own top speed. The Vespa is 60% faster than the refuse truck.
- **Handbrake turns**: `LSHIFT` (or gamepad `LB`) locks the back wheels. The car carries momentum sideways through a turn now, so you can stab the brake, let the back step out, rotate while keeping your speed, and power out — instead of braking to a quarter of top speed at every single intersection. Slides leave rubber on the road. It is measurably the **fast** line through a 90° grid corner: a scripted driver takes one cleanly at 100% of cruise on the handbrake and exits at 4.7-5.3 px/step, against 85% of cruise and a 1.8-2.7 exit on the brakes alone.
- **Wanted System**: whole-star wanted levels 0–5. Running someone down or shunting traffic at speed earns stars; scraping a kerb does not. Cops spawn *off-screen near you* rather than across the map, chase with whisker-based obstacle avoidance, and have to hold sustained contact (watch the BUSTING bar) before you are taken. Stars only decay once you are genuinely clear of them — parking and waiting no longer works.
- **Chases you can actually win — or lose on purpose**: every star used to be *faster than your
  own top speed* (up to 10.8 against 8.6), so a straight-line escape did not exist at any
  wanted level; a flat-out flee from two stars measured the cruiser closing **274px in ten
  seconds**. Police pace is now pegged to the player's car: a standard sedan outruns one and
  two stars, matches three, and is marginally slower than four and five — which is what makes
  stealing the Trans Am at five stars the right move rather than a cosmetic one. Escalation is
  numbers, aggression and how long they hold the scent. And **you cannot be pulled out of a
  moving car**: below `BUST_MAX_SPEED` a cruiser leaning on you is an arrest in progress, above
  it it is just a ram. One bad corner now costs you your lead, not the run.
- **Control, calling it in**: a cop with no line of sight used to hunt one stale point and give
  up, so a chase died the moment you turned a corner — about one second at speed. A car being
  driven hard down a public street is conspicuous, so units still looking get a periodic radio
  fix on it. Stop, or get off the road and out of sight, and the radio goes quiet: the hiding
  mechanic is untouched, because a hidden player broadcasts nothing. Scripted pursuits went
  from **7-14 seconds** to **25-60 seconds and 4,000-17,000px of driving**, which is a chase
  across the whole city.
- **One scrape is one impact**: the three contact-damage sites (a wall, a rammed car, a cruiser
  leaning on you) each fired *once per simulation step* for as long as the rects overlapped, so
  a half-second graze was thirty separate hits. Every scripted chase died the same way inside
  fifteen seconds — WRECK TOTALLED — with the nearest cruiser still five hundred pixels back.
  Sustained contact is now rate-limited, and the potholes (34 of them, quietly the single
  largest thing eating a chase car at 46 of 100hp per forty seconds) cost you speed and screen
  rather than health.
- **Traffic that goes around things**: kerbside parking used to sit 14-18px off the road's
  centre line while the driving lane sat at 15px off the *same* line — every parked car was
  parked in the middle of the lane. Ambient traffic braked to a dead stop behind each one
  forever, and everything queued up behind it. Parking now hugs the kerb, and traffic **pulls
  out around anything stopped in its lane** — a parked car, a wreck, a car you shunted into the
  gutter — refusing the manoeuvre where there is genuinely no room, such as a bridge deck.
  Overlapping car pairs fell from **3.7 to 0.4**, cars stalled over a second from **1.4 to
  0.2**, and average traffic speed rose from 1.26 to 2.07.
- **Vehicle physics that corner like a car**: the player and the police drive a **bicycle
  model** — yaw is proportional to speed × steering angle, and the steering *lock* fades as
  speed rises, so the turning circle **opens up the faster you go**: a ~30px radius crawling,
  ~190px flat out. The old model did the exact opposite (it scaled yaw by `0.45 + 0.55 ×
  speed_frac`, giving **288°/s and a tightening circle at top speed**), which is what made
  fast driving read as a twitch rather than a car. On top of that sits a **lateral grip
  budget**: ask the tyres for more cornering force than they have and the nose washes wide —
  understeer, not a hidden speed cap. Ambient traffic deliberately keeps the old
  speed-proportional turn, because `traffic_drive()` and its whole lane geometry are tuned
  against it.
- **Sub-pixel travel is carried, not discarded**: `pygame.Rect` holds integers, and
  `rect.move(int(dx), int(dy))` used to throw away the fraction of *every step*. That was the
  engine's largest single bug: a car doing 0.9 px/step moved **zero pixels forever** (the lead
  car of a queue could never leave, so the queue never cleared), a diagonal lost **12% of its
  speed** against a cardinal heading, and 6.10 and 6.40 px/step both truncated to 6 — which is
  why a cruiser 0.3 px/step slower than you never actually fell behind. Remainders are banked
  and spent, so travel is exact over time in every direction for every vehicle.
- **A calmer, longer top end**: 8.6 px/step crossed the whole 640px viewport in 1.2 seconds.
  6.4 still crosses the entire 6400px map in seventeen — a real cross-town chase — while
  leaving you time to read a junction before you are inside it. Power tapers toward the
  ceiling so the last of the top end has to be worked for, and the speedometer is derived from
  the top speed rather than a stale constant (85 mph in a sedan, 95 in the Trans Am, 66 in a
  bus). Walking also ramps into motion instead of jumping to full speed on the first frame.
  Everything runs on a **fixed 60 Hz timestep** so the game plays identically at 30, 60 or
  240 fps.
- **A camera that never loses the car**: it leads in your direction of travel so you can see
  where you're going, but each axis is now capped as a fraction of *its own* half of the
  viewport. The previous version scaled the vertical lead **up** by the aspect ratio, producing
  229px of look-ahead against a 180px half-viewport — driving north or south pushed the car
  clean off the bottom of the screen, measured at **822 frames out of frame in a 1,920-frame
  sweep**. It is now 0.32 of the half-viewport at worst, with a hard clamp in
  `Camera.center_on` as a backstop and a test that sweeps all eight headings. **HUD radar + a full-screen city map** on `M` / `TAB`, across the full 100×100-tile map, with `F5` / `F9` JSON save/load, an in-game pause / controls screen, and an `F3` debug overlay.
- **Chunky 1997-console look**: everything is procedurally baked hard-pixel art at a 640×360 internal buffer, nearest-neighbour upscaled 2×. Optional CRT scanline / vignette pass on `F2`. No image assets.

## 🚀 How to Run (Step by Step)

### Prerequisites

You need **Python 3.10+** installed. If you don't have it:
1. Go to https://www.python.org/downloads/
2. Download and install Python
3. Make sure to check "Add Python to PATH" during installation

### Step 1: Open a Terminal

Press `Windows + R`, type `cmd`, and press Enter.

### Step 2: Navigate to the Game Folder

Type this command and press Enter:
```
cd path/to/GTASTL
```

### Step 3: Install Dependencies

Type this command and press Enter:
```
pip install -r requirements.txt
```

### Step 4: Run the Game

Type this command and press Enter:
```
python main.py
```

It opens **fullscreen** by default (scaled to your display, aspect-correct). Pass
`--windowed` to start in a resizable window instead; `F11` toggles either way at
any time.

### 🎮 Controls

| Key | Action |
|-----|--------|
| `W` / `↑` | Move forward / Accelerate |
| `S` / `↓` | Move backward / Brake |
| `A` / `←` | Move left / Steer left |
| `D` / `→` | Move right / Steer right |
| `LSHIFT` | **Handbrake** — locks the back wheels so the car rotates on its momentum |
| `E` | Enter or exit a vehicle |
| `R` | Reroll the run currently on offer (before pickup only) |
| `SPACE` / `F` | Punch, or fire the pistol if you're carrying one |
| `M` / `TAB` | Full-city map (freezes the sim while it's up) |
| `F11` | Toggle fullscreen / windowed |
| `ESC` / `P` / `F1` | Pause — the full control list lives here |
| `F2` | Cycle CRT post-effects (off → scanlines → scanlines + vignette) |
| `F3` | Debug overlay (fps, sim steps, entity counts, heat) |
| `F5` | Save game |
| `F9` | Load game |
| `Q` | Quit — **only from the pause screen** |

### 🎯 Gamepad

An Xbox 360 / XInput controller is picked up automatically if one is plugged in
(hot-plug works too — no restart needed). Nothing to configure, and the game runs
exactly the same with no pad attached.

| Control | Action |
|---------|--------|
| Right trigger | Accelerate |
| Left trigger | Brake / reverse |
| Left stick | Steer, or walk — **analogue**, so a half-deflected stick is a half-speed walk |
| Right stick | Aim (shoot one way while backing off in another) |
| `A` / `RB` | Enter or exit a vehicle |
| `X` / `B` | Punch or shoot |
| `Y` / `Back` | Full city map |
| `Start` | Pause (and back out of the map) |
| D-pad | Navigate title/character/school menus; steer / walk fallback in play |

Keyboard and pad are live at the same time — the pad only overrides an axis while
you're actually pushing it, so you can swap mid-game.

Nothing quits the game outright during play. `Q` sits one key away from `WASD`, and the
old bindings had both it and `ESC` hard-quitting mid-drive with no confirmation.

## 📈 Playtest rig

`tools/playtest.py` is the instrument the driving tuning is judged against. It prints
numbers rather than passing or failing — turning radius against speed, whether the camera
ever loses the car, whether a straight-line escape exists at each wanted level, how many
AI cars are overlapping each other, how long a scripted pursuit survives and how far it
travels. Run it before and after any handling, police or traffic change.

```bash
python tools/playtest.py            # every probe
python tools/playtest.py chases     # scripted pursuits at every star
python tools/playtest.py camera handling corner
```

The interesting part is `GridDriver`: a scripted driver competent enough that the numbers
describe the *game* and not a bad autopilot. It holds a lane, checks a corridor is
actually open before committing to it (landmarks are stamped over the road grid, so
"it is a road line" does not mean "you can drive down it"), brakes into the corners it
means to turn at, and backs out when it gets stuck. It drives the grid at **82% of top
speed with 8 head-on hits in forty seconds**.

## 🧪 Tests

```bash
python tests/test_smoke.py          # no test dependency needed
python -m pytest tests              # or under pytest, if you have it
python main.py --headless --frames 1800 --shot frame.png
```

`--headless` boots the whole game against the SDL dummy driver — real map, real baked
art, no window — drives it with scripted input, and asserts a set of invariants after
every simulated step (nothing leaves the map, no physics value goes non-finite, the
police count always matches the wanted level, cash never goes negative). It exits
non-zero on the first breach and can dump the final frame as a PNG. Both this and the
behaviour suite run on every push via GitHub Actions.

## 📁 Project Structure

```
GTASTL/
├── main.py               # All game code (single-file prototype — see Known debt)
├── tests/test_smoke.py   # Headless behaviour tests
├── tools/playtest.py     # Handling / police / traffic measurement rig
├── .github/workflows/    # CI: byte-compile, tests, headless play-through
├── requirements.txt      # Python dependencies
├── savegame.json         # Auto-generated save file
└── README.md             # This file
```

## 🔧 Troubleshooting

### "pygame not found" error
Run: `pip install pygame`

### "python: command not found" or "python.exe not found"
Try `py -3 main.py` instead of `python main.py`

### Window opens then immediately closes
Check the console output for error messages. The most common issue is pygame not being installed.

### Game runs but no window appears
Make sure you're running from the repository root (the folder containing `main.py`).

### Fullscreen looks wrong or won't come up
Start with `python main.py --windowed` and press `F11` when you want fullscreen. If a
driver rejects the scaled-fullscreen mode outright, the game falls back to a plain
resizable window on its own.

## 🛠️ Development Notes

- Single-file architecture for simplicity, organized around a `Game` class instead of loose globals
- All art is procedurally **baked** once at startup into hard-pixel surfaces — no image files. The bakers are grouped by a `gfx_*` prefix: `gfx_cars`, `gfx_peds`, `gfx_followers`, `gfx_props`, `gfx_roofs`, `gfx_lm` (landmarks), `gfx_hud`, `gfx_fx`
- The map is a road grid with a deterministic brick-block fabric stamped between the roads (`_fill_city_blocks`), then the real landmark footprints stamped on top (`LANDMARKS`, mirrored into the parking and landmark-size tables)
- **Two handling models in one `physics_step`.** Anything with a `driver` — you or a cruiser —
  gets the bicycle model (`PLAYER_YAW_GAIN`, `PLAYER_LOCK_FADE`, `PLAYER_GRIP`); ambient traffic
  (`driver is None`) keeps the original speed-proportional turn, because `traffic_drive()`'s
  lane geometry is tuned against "radius == max_speed / steer_angle" and rewriting the physics
  under it would put every AI car in the kerb. Per-variant handling via `VEHICLE_TUNING`, plus a
  per-car damage model (`hp` / `burn` fuse → `Game.explode`) with a `crash_damage()` cooldown
  for sustained contact. A blocked move is retried one axis at a time so a car **slides along a
  wall** instead of dead-stopping on every kerb graze (a square-on hit still thunks)
- **`Car.take_subpixel()` banks fractional travel** between steps, so integer `Rect`
  coordinates stop silently eating a per-axis slice of every vehicle's speed. Every impact and
  splatter threshold (`SPLAT_SPEED`, `NUDGE_SPEED`, `IMPACT_*`, `RAM_SPEED`, `HUD_MPH_PER_PX`)
  is derived from `PLAYER_CAR_MAX_SPEED` rather than written out, so retuning the top speed
  cannot leave them behind again
- Feedback layer is one funnel: `Game.add_score()` routes every point through the chaos multiplier, spawns a world-space `+N` pop, and fires a `MULTIPLIER X?` callout on a rung. `add_callout()` / `add_pop()` / `spawn_burst()` / `kick()` are the shared primitives; everything is frame-timed (never `pygame.time.get_ticks()`) so headless capture stays deterministic, and every pool is capped
- Hitstop is a whole-step skip at the top of `Game.update()`; screen shake is a frame-driven offset folded into `Camera.apply()` only (`center_on` never sees it, so the sim and the camera-pan test read a stable `x`/`y`)
- Pedestrians run a small state machine (`calm` / `flee` / `gawk` / `down`) with a decaying knockback vector; `Pedestrian.update(game)` senses the player car, cops and the wanted level
- **On-foot movement keeps a float position** (`player_fx/fy`) and resolves each axis separately, so diagonals keep their full speed (`int()` used to truncate a 2.97px step to 2) and brushing a corner slides instead of stopping dead. `sync_player_float()` re-seats it after anything teleports the player
- **Landmark collision is per-landmark** (`LANDMARK_LAYOUT` → `_LM_SOLID`), and `WALK_REACHABLE` is a one-time flood fill from the road network that `free_point_near()` / `random_open_spawn()` consult, so nothing is ever placed in a sealed pocket. A test asserts every open landmark tile is reachable
- Neighbourhood character is a deterministic lookup (`hood_at` → `HOOD_SIGNS` / `HOOD_HOUSES`) keyed on the tile, never re-rolled per frame
- **Population streaming** (`update_population`) recycles pedestrians and traffic that drift past `POP_KEEP_RADIUS` into the `POP_RESPAWN_MIN..MAX` ring, capped at a few per step so the cost spreads and nothing teleports en masse. The ring's inner edge sits past the screen corner (`hypot(320, 180) = 367`), so nothing ever pops into view. Parked cars recycle onto real kerb bays via `parking_parking_spots`, so there is always a car to steal nearby
- Tile-based collision; `Camera` centers on the active entity (leading it toward its direction of travel) and everything draws through `camera.apply()` / `camera.apply_pos()`
- Real window is `RESIZABLE | SCALED`, opened fullscreen by default; SDL does the aspect-correct letterboxing, so `postfx.present()` just scales the 640×360 buffer into whatever size it is handed. `--windowed` / `F11` for the window
- Road-following wander AI for traffic, whisker-avoidance pursuit AI for police; `RailVehicle` bypasses both and runs a fixed line
- **Fixed-timestep loop.** Every tuning constant in the file is authored *per simulation step*, so `Game.step_sim()` banks real elapsed time and spends it in exact 1/60 s slices, clamped to `MAX_SIM_STEPS` so a long stall (dragging the window, waking from sleep) drops the debt instead of spiralling into catch-up steps
- **Placement goes through `free_point_near()`.** Anywhere the game *puts* something rather than moving it — stepping out of a car, dropping a job marker, respawning after a bust, spawning a cop — spirals outward for a spot the collider actually fits, and returns `None` rather than stuffing an entity inside a wall

## ⚠️ Known debt

`main.py` is ~14,000 lines. The would-be modules are already there in spirit — the
`gfx_*`, `traffic_`, `parking_`, `hud_` and `lm_` prefixes are hand-mangled namespaces
from when these *were* separate files — and splitting them back out is the next
structural job. It is deliberately not bundled with the gameplay work in this pass:
it is a very large, entirely mechanical diff with zero user-visible effect, and it
wants to be its own reviewable change. The one part that was an active hazard — three
sets of hand-copied `TILE_SIZE` / `MAP_TILES_W` / road-grid literals that would have
silently desynced the moment anyone resized the map — has been collapsed onto the
canonical constants, with a test pinning them together.

## 📝 Future Plans

- [x] Mission / job system (GTA1 had phone-booth and special-car missions)
- [ ] Split `main.py` back into modules
- [x] Gamepad support, including front-end navigation
- [x] Bespoke landmark art for the major districts and local businesses
- [x] Rails drawn under the MetroLink / trolley; a proper river bend with a bridge
- [ ] Day/night cycle
- [x] Procedural sound effects and ambient city audio

---

Built with ❤️ and pygame

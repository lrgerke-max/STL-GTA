# STL-GTA: St. Louis Open-World Sandbox

A top-down open-world driving game inspired by the original GTA, set in St. Louis, Missouri.
Most runtime art is procedurally baked pixel art. A native 64px neighborhood atlas in
`sprites/` is sliced into live building tiles at boot and mixed with the procedural city.

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

- **Streets with names, and streets that ignore the grid**: the road network used to be
  `set(range(4, MAP_TILES_W, 8))` in both directions — a perfect square lattice, every block
  the same size, not one street with a name on it. It is now an **irregular** list of
  **31 named streets**: Kingshighway on Forest Park's east wall, Grand straight through Grand
  Center, Chippewa carrying Ted Drewes, Olive approaching the Eads and Arsenal the Poplar
  Street Bridge. County blocks out west are long, downtown blocks are short. And the three
  arteries that make driving here what it is — **Gravois**, **Manchester** and **Natural
  Bridge** — are real diagonals cut across the finished grid after the landmarks are stamped,
  so they ignore whatever is in the way, exactly as they do on the ground. Gravois bends down
  the east side of Tower Grove Park and out to the windmill at Morganford, which is why Bevo
  Mill sits in the fork. Ambient traffic still drives the grid; the diagonals are yours, which
  is what makes "TAKE GRAVOIS, THEY'LL NEVER FOLLOW" a real plan instead of a joke.
  The tiles under a diagonal are a 4-connected staircase because collision and
  reachability are, but the *street* is not: diagonal tiles get their own
  renderer that chamfers the outside corner of every step and runs the grime and
  the centre dashes along the street's real heading. Before that, each 64px step
  was drawn as a square boxed in sidewalk on three sides, and Gravois read as a
  flight of stairs.
- **A city laid out like St. Louis**: the Gateway Arch on the riverfront with downtown and the ballpark just inland, Soulard and the Anheuser-Busch brewery south along the river, a midtown spine (Grand Center → Central West End) running west to a big Forest Park, the Delmar Loop up in the north-west, and The Hill, **Ted Drewes** and Tower Grove Park down in the south. Compressed and not to scale, but recognisable in the hand — dozens of landmarks and named park features, each discoverable for score.
- **What you can see is what you can walk on**: the **Anheuser-Busch Brewery**
  had no layout entry, so its collision was the default hollow ring while its art
  drew 140 red-brick roofs edge to edge across the whole footprint. The middle of
  the brewery was open ground painted to look like rooftops, and crossing it felt
  like walking over the Brew House. Both now come off one mask: brick blocks with
  cobbled yard streets between them, painted centre lines down the lanes, a rail
  spur along the south apron, and the Brew House crenellated on its own block.
- **Cars parked where cars can park**: kerb bays were only tested for being
  *blocked*, and grass is not blocked - so every road-line tile the landmark pass
  turned into lawn, park, rail ballast or open water still handed out parking.
  **136 of 1,636 bays were off the road, 102 of them in the Mississippi**, the
  rest on the Arch grounds and in the parks. Bays now require asphalt under the
  whole car. Ambient traffic no longer comes to rest inside other cars either:
  the unstacking shove is proportional to how deep two cars actually are instead
  of a flat pixel a frame, and parked cars are finally part of it - overlapping
  AI-car pairs went **mean 2.08 / worst 9 -> mean 0.38 / worst 3**, stalls
  **0.49 -> 0.19**, and mean traffic speed **1.93 -> 2.34** of a 3.25 cap.
  Nothing respawns on a spot another vehicle is already sitting on.
- **Landmarks with real shapes**: the **Arch** is a vertical catenary, so in plan only the two leg footings are solid and you walk straight under the span. **Busch Stadium** is a hard-walled bowl with one gate corridor into the field. The **Missouri Botanical Garden** is a garden: it had no layout entry at all, so it fell through to the default district rule and generated a **ring of buildings around a courtyard** — a wall of masonry through the middle of Henry Shaw's garden. It now gets its own composition, and the thing you can pick out from across the map is the **Climatron** — Buckminster Fuller's dome, 1960, the first geodesic structure ever used as a conservatory — drawn as a triangulated net over glass. **Seiwa-en**, the largest Japanese garden in North America, is real water with an island and a drum bridge you have to go round; the **Linnean House** of 1882 and **Tower Grove House** are the only other solid mass, and 44 of the garden's 56 tiles are open ground. All four are separately discoverable. City blocks are two bands of buildings with a service alley, a gate through the middle of every side and a courtyard in the centre — dense to look at, legible to walk. Every open tile in the game is flood-fill verified reachable from the street network, so a drop marker can never land in a sealed pocket.
- **Twenty-four neighbourhoods, and the game says which one you are in**: eleven coarse
  regions were still doing violence to the map. Measured, `south` alone was **30.6% of the
  whole map** — Tower Grove and Shaw and Dutchtown and Bevo and Carondelet and St. Louis Hills
  and Lafayette Square, plus the overflow from Forest Park and Union Station, all drawing shop
  signs from one eleven-item bag. It showed: the Botanical Garden came back `grove`, so
  Manchester Ave nightlife signage hung around Shaw's Garden; City Museum came back `south`,
  so a downtown loft block advertised Ted Drewes and Bevo Mill; half of Cherokee Street came
  back `soulard`, so McGurk's hung on Cherokee. The map is now **24 neighbourhoods**, the
  largest is **9.6%**, **19 of 20 landmarks sit 100% inside one** (the brewery is 94%), and
  unique shop signs went **53 → 116**. Crossing a boundary raises the neighbourhood's real
  name on screen, and the street you are on reads out under the radar — because a player who
  cannot name a district cannot notice it changed.
- **A real brick city between the roads**: every block is filled with neighborhood-weighted
  St. Louis masonry — red / brown / buff brick and limestone — rendered in a hybrid view:
  dark top-down roofs with a lit south **facade**. Native sprites appear at one address in
  three and deterministic procedural storefronts/houses fill the rest, so a block has a family
  resemblance without repeating one stamp. Parks, surface lots and tree-lined sidewalks fill the rest.
- **A St. Louis cast on foot**: commuters, dog walkers (with dogs), shoppers, elders with canes, hi-vis road crews, joggers, plus a jazz **sax busker** in the arts districts, foam-finger crowds around Busch, and South City hoosiers with mullets and tallboys. Street bodies used to be three special-cased landmarks and one 5% hoosier roll in a single giant `south` region; every neighbourhood now names who it puts on the pavement. The streamed population retypes itself by neighborhood as you travel instead of carrying downtown commuters into every district forever.
- **Locals who actually talk, and do not repeat themselves**: the conversation table held
  **29 scenes** — 15 citywide, 14 tagged — spread over 11 neighbourhoods. Measured, that meant
  **83–100% of everything you heard anywhere in the city came out of the same fifteen-item
  bag**, `west` had no local lines at all, and selection was a bare `random.choice` with no
  memory, so it repeated back to back. On a 7-second cooldown a five-minute walk drew about
  forty scenes from a pool of sixteen. It now holds **295 scenes**, **every one of the 24
  neighbourhoods has ten of its own**, and a shuffled-bag dealer will not repeat a scene until
  the deck runs out — with a short memory across the seam so crossing a boundary does not
  replay what you just heard. Local scenes are weighted 72%, so what you hear in Soulard is
  mostly Soulard: the market trading since 1779, beads still in the trees, which corner bar.
  Underneath the surface tier (provel, t-ravs, 40-vs-64) the city now knows the Great Divorce
  of 1876, the earnings tax, Sumner High and who went there, the Climatron being the first
  geodesic conservatory, Vide Poche, the Hodiamont tracks, the drum bridge at Seiwa-en, and
  that the sirens go off the **first Monday** at eleven. Plus **68 solo barks**, **28 reaction
  barks**, **22 cop barks**, and panic lines per neighbourhood instead of five for the whole
  city.
- **A real soundtrack**: the supplied 25.69-second `music/AUD_HO1036.mid` is arranged into
  `music/gloria-8bit.wav`, a 195-second pulse/square/triangle/noise chiptune. It loops once
  play begins, pauses with the game, and sits below the procedural engines, sirens, impacts,
  radio, and neighborhood ambience. `F4` toggles it without muting the rest of the city.
- **Busy streets without the traffic jam**: the viewport sees 0.56% of the map, so population is streamed through a ring just outside the camera instead of smeared across the whole city. The calmer ten-car moving pool now measures **~1.6 moving cars and ~2.6 parked cars on screen** on the irregular network, with overlapping moving-car pairs averaging **0.05**, stalls averaging **0.12**, and traffic averaging **2.27 px/step** against its 3.25 cap. Twenty-two parked cars (including the two local showcase rides) still leave something to steal nearby; the streets breathe instead of becoming a permanent obstacle course.
- **Traffic stays on traffic streets**: ambient routing now admits only true cardinal-road
  tiles, excluding diagonal reservations, landmark plazas, and dedicated MetroLink ballast.
  Cars keep a last-known-good road position and recover within the same simulation frame if
  physics carries them over a kerb. Vehicle overlap checks use the rotated body footprint,
  so north/south traffic no longer mistakes two legal lanes for a collision and shoves both
  cars into Grand Center. A 1,800-frame deterministic run now averages **0.05 real overlaps**,
  **0.12 cars stalled over one second**, and **2.27 px/step** against the 3.25 cap.
- **Road and rail joins read as joins**: diagonal shoulders are clipped at cardinal street
  mouths while their asphalt continues through. Compact four-bar crosswalks replace the old
  oversized blocks. MetroLink keeps asphalt at embedded and grade-crossing track, sleepers
  stay on dedicated ballast, and the steel railheads follow rounded bends instead of hard
  right-angle elbows.
- **St. Louis traffic**: ordinary cars and taxis plus a safety-orange City refuse truck with
  black `CITY` lettering, box truck, school bus,
  blue/red **Route 70 MetroBus**, Hill delivery Vespa, and a rare black Trans Am with a gold
  hood bird and the radio permanently stuck on KSHE — each with its own size and handling.
  Moving traffic spawns directly in its proper lane and uses a measured long-look steering
  line, while wider asphalt aprons keep the two-lane streets from reading like alleys. Ambient
  **MetroLink** runs the Red Line's actual alignment. It used to be one dead-straight row
  across the entire map at row 53 — chosen because row 53 happened to be free of collisions —
  which put it through the Compton Hill Water Tower's lawn and down in south city, where the
  real MetroLink conspicuously does not go. It is a **polyline** now: in from the north-west
  beside Delmar, east along Forest Park's north edge, past the Central West End and Grand,
  south around downtown, and over the Mississippi on the **Eads**, with nine named stops and
  trains that follow the curves. The right-of-way carves where it is dedicated track, keeps
  grade crossings on the streets that cross it, and only insets rails where it rides a road or
  a landmark's own ground, so nothing hand-drawn gets bulldozed. Active warning lights and
  paired arms at every crossing; ambient traffic stops, impatient players can run the gate, and
  the train wins. The **Loop trolley** uses rails embedded in Delmar and goes about two miles
  before turning round, which is both accurate and the entire joke. The
  **Clydesdales** walk a Soulard beat - west along Gravois' grid leg, then south
  down Broadway past the brewery. They used to be handed the full width of the
  map on row 57, which walked the eight-horse hitch through the Farmers Market
  sheds and then straight out across the Mississippi. Two one-off, stealable local spectacles
  wait at destinations instead of clogging traffic: a St. Louis-built monster-truck homage
  inside Busch and the enormous red grocery cart from childhood parades at Soulard Market.
  The monster truck shrugs off potholes; the cart handles exactly like a giant shopping cart should.
- **The Hill's hydrants**: six enlarged, guaranteed curbside hydrants ring the neighborhood
  in broad green, white and red bands. They occupy verified walkable sidewalk tiles rather
  than depending on the generic street-clutter lottery, so the detail is legible and actually
  there every time you visit.
- **The $50,000 Arch Job**: bank enough money and a real multi-stage finale opens under the
  Arch: borrow a cutter from City Museum, bring a getaway car, strap 43 pounds of visible
  stainless steel to it, survive a forced five-star run to The Hill, and lose the cops in
  the gangways. Death, arrest, timeout and body-shop cheese all fail it cleanly; winning gets
  a full-screen victory beat before ordinary St. Louis starts moving again.
- **Four rotating job cards**: ordinary courier work now shares the dispatcher with **Rush**
  runs (short clock, larger payout), **Hot Loads** (the pickup starts a two-star chase), and
  **Heavy Hauls** (more time and money, but the cargo slows the car carrying it). The dealer
  will not repeat either of the last two cards. Mastering each type is saved and pays a first-
  completion bonus, while route distance, time-left reward and the delivery streak keep every
  card pushing a different cross-city line.
- **Courier jobs**: the actual game. Pick up at one landmark, deliver to another before the clock runs out. What you are carrying now depends on **where you collected it** — the old nine-item list was picked at random with no relation to the pickup, so you would load a BREWERY KEG at Ted Drewes and a CRATE OF PROVEL at the Botanical Garden. A keg only comes from Anheuser-Busch; a concrete, upside down, only from either Ted Drewes; hot salami from Gioia's on The Hill; a crate of orchids from the garden; a Crown Candy malt that melts if you are slow. Finding a landmark also hands you **one line of real St. Louis** about it — 630 feet and Saarinen, Dred Scott tried in that courthouse, the market trading since 1779, 1,500 free seats since 1919. Payout scales with distance and with the time you had left, and consecutive on-time drops build a streak multiplier. An on-screen marker and an edge-of-screen chevron always point at the objective, so you are never lost on a 100×100-tile map.
- **Three rotating side jobs**: find the magenta contact and press `E` to take work. Steal a
  marked ride and deliver it intact to a Kingshighway chop shop, tear through six physical
  targets around Grand Center, or survive a forced three-star run before laying low and making
  The Hill. Each has its own timer, failure rules, objective markers, and cash payout.
- **Cash vs. score**: two separate currencies that mean different things. **Cash** comes from
  finished runs, can be banked safely beneath the Arch, and leaves via bail or a body-shop
  respray. Bail is painful but capped at **$1,000**, so one arrest never erases a whole good
  session. **Score** is the chaos counter. Playing carefully and playing recklessly are genuinely different strategies.
- **Defensive saves**: the title screen only offers Continue for a current, structurally valid
  save. Missing, truncated, malformed, out-of-bounds, and incompatible saves fall back safely
  to New Game without partially mutating a live run.
- **Chaos multiplier (x1–x8)**: every reckless act — a hit, a shunt, a wreck — feeds a running multiplier that scales every point of score you earn. Park and it bleeds away; get **busted** or **wasted** and it's gone. The screen shouts each rung.
- **Kill Frenzy**: a pulsing icon drops on the map. Touch it and a clock starts — `MOW DOWN 14 LOCALS`, `WRECK 8 MOTORS`, or the much hotter `DROP 6 COPS` — for a fat score payout and free multiplier rungs. Pure GTA1 "just one more go".
- **Rampage streaks**: bowl a line of pedestrians and the per-hit value stacks, scaled by how
  fast you were going when you did it. The shout ladder runs to fifty (`GOURANGA!`,
  `SLINGER STREAK`, `TOTAL CARNAGE`, `ST LOUIS HATES YOU`, `MOUND CITY MASSACRE`, ...) and the
  window that holds a streak together **grows with the streak**, so a run through three blocks
  of sidewalk stays one run instead of dying in the gap between two crowds. `SPLAT_SPEED` and
  every other impact threshold is now a *fraction* of the top speed rather than a literal
  tuned against a top speed the game no longer has — left alone, the old 5.2 would have put
  splattering at 81% of flat out, i.e. almost never.
- **A reactive crowd**: (`GOURANGA!` at 5). Peds see a speeding car coming and scatter, dive clear, bolt when the stars light up, and knot around a fresh body. Clip one below `SPLAT_SPEED` and they go down and get back up — hit them at speed and they **don't**, leaving a stain on the road that's still there next lap.
- **Combat and arsenal**: `SPACE` / `F` uses your selected weapon. Fists drop people, the
  baseball bat has a wider lethal arc, the pistol is accurate, the shotgun throws a six-pellet
  cone, and the SMG can be held for automatic fire. Satchel charges bounce, tick, and deliver a
  wide radial blast; fire bottles shatter on impact and leave a six-second burning hazard.
  Pickups persist in an inventory, `Q` or the mouse wheel cycles it, and ammo survives saves.
  Every weapon can hurt pedestrians, beat cops, civilian cars, cruisers, and roadblock units.
- **Beat cops are mortal**: officers on foot have health, hit stun, knockdown, and death. A bat,
  bullet, explosion, or fast car can take one out; a slower impact bowls one over. An officer
  kill pays chaos score, jumps the response to at least three stars, panics the crowd, and leaves
  a four-second reinforcement gap instead of replacing the same cop instantly.
- **Cars that actually hit each other**: ramming transfers momentum — the struck car gets shoved down the contact normal, yaws away from an off-centre hit, and a parked car knocked at the kerb coasts before it stops. Traffic used to absorb a full-speed broadside without twitching.
- **Impact juice**: wall slams and collisions land — screen shake, a frame of hitstop on the big ones, a spray of sparks / glass / smoke, a white flash. Floating `+N` / `$N` numbers rise off whatever you just did; big moments get a centre-screen ALL-CAPS callout.
- **WASTED / BUSTED**: cars (yours, traffic, cop) have health. Enough hits and one smokes,
  catches fire, then explodes — a blast that scatters the crowd and can chain to the next car.
  Either loss gets a readable result card, then automatically returns you beneath the Arch;
  after its opening beat, `ENTER`, `SPACE`, `E`, or gamepad `A` skips straight back to play.
- **Steal Any Car**: walk up to traffic or a parked car and press `E` to jack it — and it matters which one, because every variant now has its own top speed. The Vespa is 60% faster than the refuse truck.
- **Handbrake turns**: `LSHIFT` (or gamepad `LB`) locks the back wheels. The car carries momentum sideways through a turn now, so you can stab the brake, let the back step out, rotate while keeping your speed, and power out — instead of braking to a quarter of top speed at every single intersection. Slides leave rubber on the road. It is measurably the **fast** line through a 90° grid corner: a scripted driver takes one cleanly at 100% of cruise on the handbrake and exits at 4.7-5.3 px/step, against 85% of cruise and a 1.8-2.7 exit on the brakes alone.
- **Wanted System**: whole-star wanted levels 0–5. Running someone down or shunting traffic at speed earns stars; scraping a kerb does not. Cops spawn *off-screen near you* rather than across the map, chase with whisker-based obstacle avoidance, and have to hold sustained contact (watch the BUSTING bar) before you are taken. Stars only decay once you are genuinely clear of them — parking and waiting no longer works.
- **On-foot escapes are playable**: hold `LSHIFT` (or gamepad `LB`) for a three-second sprint,
  then recover stamina while walking or hidden. Beat cops walk faster than you but sprint slower,
  search for nine seconds after losing sight, and only build the arrest meter while actively in
  contact. Cruiser contact cannot magically arrest a player standing on the sidewalk, and a
  broken hold drains the meter quickly.
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
  mechanic is untouched, because a hidden player broadcasts nothing. Fixed-tier probes now
  carry low and mid-level pursuits as far as **60 seconds and 14,000px of driving**; four and
  five stars are the sharp escalation, where roadblocks can end a poor line in 10-23 seconds.
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
- **Chunky 1997-console look**: procedural hard-pixel art and a hand-authored 64px facade atlas are rendered at a 640×360 internal buffer, nearest-neighbour upscaled 2×. Optional CRT scanline / vignette pass on `F2`.

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
| `S` / `↓` | Move backward on foot / brake, then engage reverse in a car |
| `A` / `←` | Move left / Steer left |
| `D` / `→` | Move right / Steer right |
| `LSHIFT` | Sprint on foot / **handbrake** in a car |
| `E` | Enter/exit a vehicle or accept a nearby magenta side job |
| `R` | Reroll the run currently on offer (before pickup only) |
| `SPACE` / `F` | Use the selected weapon |
| `Q` / mouse wheel | Cycle weapons during play |
| `M` / `TAB` | Full-city map (freezes the sim while it's up) |
| `F11` | Toggle fullscreen / windowed |
| `ESC` / `P` / `F1` | Pause — the full control list lives here |
| `F2` | Cycle CRT post-effects (off → scanlines → scanlines + vignette) |
| `F3` | Debug overlay (fps, sim steps, entity counts, heat) |
| `F4` | Toggle the soundtrack |
| `F5` | Save game |
| `F9` | Load game |
| `Q` | Quit — **only while paused** |

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
| `A` | Enter or exit a vehicle |
| `LB` | Sprint on foot / handbrake in a car |
| `RB` | Cycle weapons |
| `X` / `B` | Use the selected weapon |
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
python tools/playtest.py foot       # sprint-versus-beat-cop escape measurement
python tools/playtest.py reverse    # standstill, gear transition, steering, wall recovery
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
    missions.py           # Pure side-mission lifecycle and objective logic
    throwables.py         # Pure projectile, blast, and persistent-fire simulation
├── main.py               # All game code (single-file prototype — see Known debt)
├── tests/test_smoke.py   # Headless behaviour tests
├── tools/playtest.py     # Handling / police / traffic measurement rig
├── music/                # Supplied MIDI source and rendered 8-bit soundtrack
├── sprites/              # Native-resolution neighborhood building atlas
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
- Most art is procedurally **baked** once at startup into hard-pixel surfaces. The transparent 6x4 neighborhood atlas in `sprites/` is authored directly at 64x64 per cell by `tools/build_pixel_facades.py`, then sliced without scaling by `bake_neighborhood_building_sprites()`; the other bakers are grouped by a `gfx_*` prefix: `gfx_cars`, `gfx_peds`, `gfx_followers`, `gfx_props`, `gfx_roofs`, `gfx_lm` (landmarks), `gfx_hud`, `gfx_fx`
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
- **On-foot movement keeps a float position** (`player_fx/fy`) and resolves each axis separately, so diagonals keep their full speed (`int()` used to truncate a 2.97px step to 2) and brushing a corner slides instead of stopping dead. `sync_player_float()` re-seats it after anything teleports the player. A three-second stamina sprint opens a real escape gap before dropping back to the walk speed
- **Landmark collision is per-landmark** (`LANDMARK_LAYOUT` → `_LM_SOLID`), and `WALK_REACHABLE` is a one-time flood fill from the road network that `free_point_near()` / `random_open_spawn()` consult, so nothing is ever placed in a sealed pocket. A test asserts every open landmark tile is reachable
- Neighbourhood character is a deterministic lookup (`hood_at` → `HOOD_SIGNS` / `HOOD_HOUSES` / `HOOD_BRICKS` / `BUILDING_ATLAS_HOODS`) keyed on the tile, never re-rolled per frame
- Foot police carry health, stun and knockdown state. Melee, bullets, explosions and sufficiently fast cars all use the same damage path; killing an officer escalates heat and delays the replacement response rather than instantly swapping in an invulnerable copy
- **Population streaming** (`update_population`) recycles pedestrians and traffic that drift past `POP_KEEP_RADIUS` into the `POP_RESPAWN_MIN..MAX` ring, capped at a few per step so the cost spreads and nothing teleports en masse. The ring's inner edge sits past the screen corner (`hypot(320, 180) = 367`), so nothing ever pops into view. Parked cars recycle onto real kerb bays via `parking_parking_spots`, so there is always a car to steal nearby
- Tile-based collision; `Camera` centers on the active entity (leading it toward its direction of travel) and everything draws through `camera.apply()` / `camera.apply_pos()`
- Real window is `RESIZABLE | SCALED`, opened fullscreen by default; SDL does the aspect-correct letterboxing, so `postfx.present()` just scales the 640×360 buffer into whatever size it is handed. `--windowed` / `F11` for the window
- Road-following wander AI for traffic, whisker-avoidance pursuit AI for police; `RailVehicle` bypasses both and follows the MetroLink, Loop trolley, or Clydesdale polyline assigned to it
- **Fixed-timestep loop.** Every tuning constant in the file is authored *per simulation step*, so `Game.step_sim()` banks real elapsed time and spends it in exact 1/60 s slices, clamped to `MAX_SIM_STEPS` so a long stall (dragging the window, waking from sleep) drops the debt instead of spiralling into catch-up steps
- **Placement goes through `free_point_near()`.** Anywhere the game *puts* something rather than moving it — stepping out of a car, dropping a job marker, respawning after a bust, spawning a cop — spirals outward for a spot the collider actually fits, and returns `None` rather than stuffing an entity inside a wall

## ⚠️ Known debt

`main.py` is ~15,000 lines. The would-be modules are already there in spirit — the
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
- [x] Dedicated MetroLink / trolley rails, bounded turnbacks, and active grade crossings
- [ ] Day/night cycle
- [x] Procedural sound effects, ambient city audio, and a 195-second rendered chiptune soundtrack

---

Built with ❤️ and pygame

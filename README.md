# STL-GTA: St. Louis Open-World Sandbox

A top-down open-world driving game inspired by the original GTA, set in St. Louis, Missouri.
Everything you see is procedurally baked pixel art — there are no image assets in this repo.

**The loop:** a dispatcher marks a pickup at one St. Louis landmark and a drop at another.
Get there, grab the cargo, and the clock starts. Deliver on time for cash and a streak
multiplier. Drive like a lunatic on the way and you pick up stars instead — and no
dispatcher will hand a run to someone with three cops behind them.

```bash
pip install -r requirements.txt && python main.py
```

## 🎮 Features

- **A city laid out like St. Louis**: the Gateway Arch on the riverfront with downtown and the ballpark just inland, Soulard and the Anheuser-Busch brewery south along the river, a midtown spine (Grand Center → Central West End) running west to a big Forest Park, the Delmar Loop up in the north-west, and The Hill and Tower Grove Park down in the south. Compressed and not to scale, but recognisable in the hand — 9 landmarks, each discoverable for score.
- **A real brick city between the roads**: every block is filled with St. Louis masonry — red / brown / buff brick and limestone — rendered in a hybrid view: dark top-down roofs with a lit south **facade** showing brick courses, windows, rowhouse stoops and awninged storefronts. Parks, surface lots and tree-lined sidewalks fill the rest.
- **A St. Louis cast on foot**: commuters, dog walkers (with dogs), shoppers, elders with canes, hi-vis road crews, joggers, plus a jazz **sax busker** in the arts districts and a **Cardinals player** by the ballpark. ~40 pedestrians, each a figure with a front / back / profile walk cycle.
- **St. Louis traffic**: ordinary cars and taxis plus a City refuse truck, a box truck, a school bus and a Hill delivery Vespa — each with its own size and handling. Ambient **MetroLink** light-rail trains and a **Loop trolley** run their lines through downtown and the Loop.
- **Courier jobs**: the actual game. Pick up at one landmark, deliver to another before the clock runs out. Payout scales with distance and with the time you had left, and consecutive on-time drops build a streak multiplier. An on-screen marker and an edge-of-screen chevron always point at the objective, so you are never lost on a 100×100-tile map.
- **Cash vs. score**: two separate currencies that mean different things. **Cash** only comes from finished runs and only leaves via bail. **Score** is the chaos counter. Playing carefully and playing recklessly are now genuinely different strategies.
- **Steal Any Car**: walk up to traffic or a parked car and press `E` to jack it.
- **Wanted System**: whole-star wanted levels 0–5. Running someone down or shunting traffic at speed earns stars; scraping a kerb does not. Cops spawn *off-screen near you* rather than across the map, chase with whisker-based obstacle avoidance, and have to hold sustained contact (watch the BUSTING bar) before you are taken. Stars only decay once you are genuinely clear of them — parking and waiting no longer works.
- **Vehicle Physics**: momentum-based acceleration, braking, steering, and drag, run on a **fixed 60 Hz timestep** so the game plays identically at 30, 60 or 240 fps.
- **Scrolling camera + minimap** across the full 100×100-tile map, with `F5` / `F9` JSON save/load, an in-game pause / controls screen, and an `F3` debug overlay.
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

### 🎮 Controls

| Key | Action |
|-----|--------|
| `W` / `↑` | Move forward / Accelerate |
| `S` / `↓` | Move backward / Brake |
| `A` / `←` | Move left / Steer left |
| `D` / `→` | Move right / Steer right |
| `E` | Enter or exit a vehicle |
| `ESC` / `P` / `F1` | Pause — the full control list lives here |
| `F2` | Cycle CRT post-effects (off → scanlines → scanlines + vignette) |
| `F3` | Debug overlay (fps, sim steps, entity counts, heat) |
| `F5` | Save game |
| `F9` | Load game |
| `Q` | Quit — **only from the pause screen** |

Nothing quits the game outright during play. `Q` sits one key away from `WASD`, and the
old bindings had both it and `ESC` hard-quitting mid-drive with no confirmation.

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

## 🛠️ Development Notes

- Single-file architecture for simplicity, organized around a `Game` class instead of loose globals
- All art is procedurally **baked** once at startup into hard-pixel surfaces — no image files. The bakers are grouped by a `gfx_*` prefix: `gfx_cars`, `gfx_peds`, `gfx_followers`, `gfx_props`, `gfx_roofs`, `gfx_lm` (landmarks), `gfx_hud`, `gfx_fx`
- The map is a road grid with a deterministic brick-block fabric stamped between the roads (`_fill_city_blocks`), then the real landmark footprints stamped on top (`LANDMARKS`, mirrored into the parking and landmark-size tables)
- Velocity/momentum physics shared by the player car and traffic/police; per-variant handling via `VEHICLE_TUNING`
- Tile-based collision; `Camera` centers on the active entity and everything draws through `camera.apply()` / `camera.apply_pos()`
- Road-following wander AI for traffic, whisker-avoidance pursuit AI for police; `RailVehicle` bypasses both and runs a fixed line
- **Fixed-timestep loop.** Every tuning constant in the file is authored *per simulation step*, so `Game.step_sim()` banks real elapsed time and spends it in exact 1/60 s slices, clamped to `MAX_SIM_STEPS` so a long stall (dragging the window, waking from sleep) drops the debt instead of spiralling into catch-up steps
- **Placement goes through `free_point_near()`.** Anywhere the game *puts* something rather than moving it — stepping out of a car, dropping a job marker, respawning after a bust, spawning a cop — spirals outward for a spot the collider actually fits, and returns `None` rather than stuffing an entity inside a wall

## ⚠️ Known debt

`main.py` is ~7,300 lines. The would-be modules are already there in spirit — the
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
- [ ] Gamepad support
- [ ] Bespoke landmark art for the remaining districts (Ted Drewes, Imo's, Soulard Market, the Old Courthouse, Fox Theatre, City Museum, the Piasa Bird)
- [ ] Rails drawn under the MetroLink / trolley; a proper river bend with a bridge
- [ ] Day/night cycle
- [ ] Sound effects and music

---

Built with ❤️ and pygame

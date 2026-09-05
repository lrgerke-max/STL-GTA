# STL-GTA: St. Louis Open-World Sandbox

A top-down open-world game inspired by the original GTA games, set in St. Louis, Missouri.

## 🎮 Features

- **A city laid out like St. Louis**: the Gateway Arch on the riverfront with downtown and the ballpark just inland, Soulard and the Anheuser-Busch brewery south along the river, a midtown spine (Grand Center → Central West End) running west to a big Forest Park, the Delmar Loop up in the north-west, and The Hill and Tower Grove Park down in the south. Compressed and not to scale, but recognisable in the hand — 9 landmarks, each discoverable for score.
- **A real brick city between the roads**: every block is filled with St. Louis masonry — red / brown / buff brick and limestone — rendered in a hybrid view: dark top-down roofs with a lit south **facade** showing brick courses, windows, rowhouse stoops and awninged storefronts. Parks, surface lots and tree-lined sidewalks fill the rest.
- **A St. Louis cast on foot**: commuters, dog walkers (with dogs), shoppers, elders with canes, hi-vis road crews, joggers, plus a jazz **sax busker** in the arts districts and a **Cardinals player** by the ballpark. ~40 pedestrians, each a figure with a front / back / profile walk cycle.
- **St. Louis traffic**: ordinary cars and taxis plus a City refuse truck, a box truck, a school bus and a Hill delivery Vespa — each with its own size and handling. Ambient **MetroLink** light-rail trains and a **Loop trolley** run their lines through downtown and the Loop.
- **Steal Any Car**: walk up to traffic or a parked car and press `E` to jack it.
- **Wanted System**: reckless driving (hitting pedestrians, traffic, or walls) raises a GTA1-style wanted level; police cars spawn from the downtown station and chase you until you shake them or get busted.
- **Vehicle Physics**: momentum-based acceleration, braking, steering, and drag.
- **Scrolling camera + minimap** across the full 100×100-tile map, with `F5` / `F9` JSON save/load.
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
cd C:\Users\lrger\Desktop\GTASTL
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
| `F2` | Cycle CRT post-effects (off → scanlines → scanlines + vignette) |
| `F5` | Save game |
| `F9` | Load game |
| `ESC` / `Q` | Quit game |

## 📁 Project Structure

```
GTASTL/
├── main.py          # All game code (single-file prototype)
├── requirements.txt # Python dependencies
├── savegame.json    # Auto-generated save file
└── README.md        # This file
```

## 🔧 Troubleshooting

### "pygame not found" error
Run: `pip install pygame`

### "python: command not found" or "python.exe not found"
Try `py -3 main.py` instead of `python main.py`

### Window opens then immediately closes
Check the console output for error messages. The most common issue is pygame not being installed.

### Game runs but no window appears
Make sure you're running from the correct directory: `C:\Users\lrger\Desktop\GTASTL`

## 🛠️ Development Notes

- Single-file architecture for simplicity, organized around a `Game` class instead of loose globals
- All art is procedurally **baked** once at startup into hard-pixel surfaces — no image files. The bakers are grouped by a `gfx_*` prefix: `gfx_cars`, `gfx_peds`, `gfx_followers`, `gfx_props`, `gfx_roofs`, `gfx_lm` (landmarks), `gfx_hud`, `gfx_fx`
- The map is a road grid with a deterministic brick-block fabric stamped between the roads (`_fill_city_blocks`), then the real landmark footprints stamped on top (`LANDMARKS`, mirrored into the parking and landmark-size tables)
- Velocity/momentum physics shared by the player car and traffic/police; per-variant handling via `VEHICLE_TUNING`
- Tile-based collision; `Camera` centers on the active entity and everything draws through `camera.apply()` / `camera.apply_pos()`
- Road-following wander AI for traffic, chase-the-player AI for police; `RailVehicle` bypasses both and runs a fixed line

## 📝 Future Plans

- [ ] Mission / job system (GTA1 had phone-booth and special-car missions)
- [ ] Bespoke landmark art for the remaining districts (Ted Drewes, Imo's, Soulard Market, the Old Courthouse, Fox Theatre, City Museum, the Piasa Bird)
- [ ] Rails drawn under the MetroLink / trolley; a proper river bend with a bridge
- [ ] Day/night cycle
- [ ] Sound effects and music

---

Built with ❤️ and pygame

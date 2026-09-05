# STL-GTA: St. Louis Open-World Sandbox

A top-down open-world game inspired by the original GTA games, set in St. Louis, Missouri.

## 🎮 Features

- **9 Real St. Louis Landmarks**: Gateway Arch, Downtown & Busch Stadium, Soulard & Anheuser-Busch, Forest Park, Central West End, The Hill, Delmar Loop, Tower Grove Park, and the Grand Center Arts District — each discoverable for score
- **Steal Any Car**: ~16 wandering traffic vehicles patrol the roads; walk up and press `E` to jack one
- **Wanted System**: reckless driving (hitting pedestrians, traffic, or walls) raises a GTA1-style wanted level; police cars spawn from the station and chase you until you shake them or get busted
- **NPC Pedestrians**: 24 wandering pedestrians roam the city on foot
- **Vehicle Physics**: momentum-based acceleration, braking, steering, and drag
- **Scrolling Camera**: follows the player or car smoothly across the full 100×100-tile map (this used to be broken — tiles/sprites were drawn at raw world coordinates instead of camera-relative ones, so the world would vanish as soon as you moved; fixed)
- **Minimap**: top-right corner minimap showing the full city, scaled correctly to its box
- **Save/Load**: `F5` to save, `F9` to load (JSON save file)
- **Cartoonish visual style**: bright, saturated colors and rounded-corner sprites for a GTA1-poster feel

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
- Pygame for rendering and input
- Velocity/momentum-based physics model shared by the player's car and traffic/police cars
- Tile-based collision detection
- `Camera` class centers on the active entity (on-foot player or driven car) and clamps to map bounds; all drawing goes through `camera.apply()` / `camera.apply_pos()` so world, sprites, and minimap all move consistently
- Simple road-following wander AI for traffic; simple chase-the-player AI for police

## 📝 Future Plans

- [ ] Mission / job system (GTA1 had phone-booth and special-car missions)
- [ ] More vehicle types (trucks, buses, sports cars with different handling)
- [ ] More St. Louis landmarks and neighborhoods
- [ ] Day/night cycle
- [ ] Sound effects and music
- [ ] Multiplayer support

---

Built with ❤️ and pygame

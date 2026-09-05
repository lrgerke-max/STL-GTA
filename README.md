# STL-GTA: St. Louis Open-World Sandbox

A top-down open-world game inspired by the original GTA games, set in St. Louis, Missouri.

## 🎮 Features

- **St. Louis Landmarks**: Gateway Arch District, Forest Park, Downtown, The Hill, Soulard, Central West End, and more
- **Vehicle Physics**: Realistic acceleration, braking, steering, and drag
- **Pedestrian Mode**: Walk around the city with WASD/Arrow controls
- **Vehicle Mode**: Enter cars with E key, drive around with physics-based controls
- **Minimap**: Top-right corner minimap showing the full city
- **Save/Load**: Press F5 to save, F9 to load
- **Camera System**: Smooth camera that follows your character

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
├── savegame.dat     # Auto-generated save file
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

- Single-file architecture for simplicity
- Pygame for rendering and input
- Velocity/momentum-based physics model
- Tile-based collision detection
- State machine for player/vehicle mode transitions

## 📝 Future Plans

- [ ] More vehicles (different types)
- [ ] NPC pedestrians and traffic
- [ ] Mission system
- [ ] Wanted level / police chase
- [ ] More St. Louis landmarks and neighborhoods
- [ ] Day/night cycle
- [ ] Sound effects and music
- [ ] Weapon system
- [ ] Multiplayer support

---

Built with ❤️ and pygame

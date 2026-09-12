"""Build a single self-contained STL-GTA.exe for Windows.

    python build_exe.py

Produces `dist/STL-GTA.exe`, which needs no Python, no pygame and no install
on the machine it lands on - double-click and play. Everything the game reads
at runtime is bundled inside it: the facade atlas and the two music files. All
three are found through `main.asset_path`, which knows about PyInstaller's
temporary unpack directory; this is the only reason the exe can find them.

Two things worth knowing about the result:

  * It is large (roughly 40-60MB). That is Python plus pygame plus SDL, and
    one-file builds cannot avoid it.
  * It is unsigned, so Windows SmartScreen will warn the first person who runs
    it ("Windows protected your PC" -> More info -> Run anyway). Signing costs
    real money per year; for sending a build to friends, a warning they click
    past is the normal trade.

Saves never go inside the bundle - they live in %LOCALAPPDATA%\\STL-GTA - so
replacing the exe with a newer build keeps existing progress.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "STL-GTA"

# Read-only assets the game loads at runtime, as (source, destination folder).
# Destinations must match what main.asset_path builds.
DATA = (
    (os.path.join("sprites", "stlouis-neighborhood-buildings-pixel.png"), "sprites"),
    (os.path.join("music", "AUD_HO1036.mid"), "music"),
    (os.path.join("music", "gloria-8bit.wav"), "music"),
)

# Pulled in by `import main` but never used by the game itself. Dropping them
# keeps the download smaller and the build faster.
EXCLUDE = ("numpy", "tkinter", "unittest", "pydoc", "doctest", "pytest",
           "PIL", "setuptools", "pip", "email", "html", "http", "xml")


def main():
    missing = [src for src, _dest in DATA
               if not os.path.isfile(os.path.join(HERE, src))]
    if missing:
        print("missing asset(s), cannot build:")
        for item in missing:
            print("   ", item)
        return 1

    for stale in ("build", "dist", f"{NAME}.spec"):
        path = os.path.join(HERE, stale)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)

    cmd = [sys.executable, "-m", "PyInstaller",
           "--onefile",
           "--noconsole",            # no terminal window behind the game
           "--name", NAME,
           "--distpath", os.path.join(HERE, "dist"),
           "--workpath", os.path.join(HERE, "build"),
           "--specpath", HERE,
           "--noconfirm"]
    for src, dest in DATA:
        cmd += ["--add-data", f"{os.path.join(HERE, src)}{os.pathsep}{dest}"]
    for mod in EXCLUDE:
        cmd += ["--exclude-module", mod]
    icon = os.path.join(HERE, "sprites", "icon.ico")
    if os.path.isfile(icon):
        cmd += ["--icon", icon]
    cmd.append(os.path.join(HERE, "main.py"))

    print("building", NAME + ".exe")
    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        print("\nPyInstaller failed; see the output above.")
        return result.returncode

    exe = os.path.join(HERE, "dist", NAME + ".exe")
    if not os.path.isfile(exe):
        print("\nbuild reported success but produced no exe")
        return 1
    size = os.path.getsize(exe) / (1024 * 1024)
    print(f"\n{exe}  ({size:.0f} MB)")
    print("Send that one file. Nothing needs installing on the other end.")
    print("Unsigned, so the first run shows a SmartScreen warning:")
    print("  More info -> Run anyway")
    return 0


if __name__ == "__main__":
    sys.exit(main())

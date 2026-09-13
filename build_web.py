"""Build the browser version of STL-GTA, so it can be played from a link.

    python build_web.py

Output lands in `docs/play/`, which GitHub Pages serves alongside the devlog:
no install, no Windows warning, and it runs on a Mac or a Chromebook. Compare
`build_exe.py`, which produces the desktop download.

Two things make this different from just pointing pygbag at the repo.

The frame loop had to become async. A desktop game owns its thread; in the
browser the page owns it, and a loop that never yields never paints. That is
`Game.run_async` in main.py, and `sys.platform` picks the entry point.

The music had to shrink. The desktop WAV is 8.6MB of 195-second 22kHz PCM -
39% of the exe, and a browser downloads the whole bundle before the first
frame. It is regenerated here instead, straight from the 7KB MIDI, at four
arranged cycles rather than nine: the renderer varies each cycle on `cycle % 4`
and fades the file's own ends to zero, so four is the shortest cut that plays
every variation and still loops without a seam. Roughly 3.8MB, no resampling,
and the samples are bit-identical to the desktop build for as long as it runs.
"""

import importlib.util
import io
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Nested under build/web/ on purpose: PyInstaller uses build/<name> as its
# own work directory, so staging at build/STL-GTA made the two builders
# delete each other. The leaf must still be the game's name - pygbag names
# the app archive after the directory it is given.
STAGE = os.path.join(HERE, "build", "web", "STL-GTA")
OUT = os.path.join(HERE, "docs", "play")

# One full set of the renderer's four cycle variations. `render` rounds up to
# whole cycles, so anything in (3 x loop, 4 x loop] asks for exactly four.
WEB_MUSIC_SECONDS = 86.0

# Everything the game imports or reads at runtime. The sprites/*.jpg style
# briefs are 1.8MB and the game never opens them, so they stay behind.
SOURCE = ("main.py", "missions.py", "throwables.py")
ASSETS = (os.path.join("sprites", "stlouis-neighborhood-buildings-pixel.png"),)


def load_renderer():
    path = os.path.join(HERE, "tools", "render_chiptune.py")
    spec = importlib.util.spec_from_file_location("render_chiptune", path)
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves its own module out of sys.modules, so register
    # before executing or the decorator raises on a None module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_music(dest):
    """Re-render the soundtrack short enough to download."""
    from pathlib import Path
    rc = load_renderer()
    notes, _src_secs, _fmt, _div = rc.parse_midi(
        Path(os.path.join(HERE, "music", "AUD_HO1036.mid")))
    samples, seconds, cycles = rc.render(notes, WEB_MUSIC_SECONDS)
    rc.write_wave(Path(dest), samples)
    size = os.path.getsize(dest) / (1024 * 1024)
    print(f"  music: {seconds:.0f}s, {cycles} cycles, {size:.1f} MB")


def stage():
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE)                      # parents included
    for name in SOURCE:
        shutil.copy2(os.path.join(HERE, name), os.path.join(STAGE, name))
    for rel in ASSETS:
        dest = os.path.join(STAGE, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(HERE, rel), dest)
    os.makedirs(os.path.join(STAGE, "music"), exist_ok=True)
    build_music(os.path.join(STAGE, "music", "gloria-8bit.wav"))
    total = sum(os.path.getsize(os.path.join(root, f))
                for root, _d, files in os.walk(STAGE) for f in files)
    print(f"  staged {total / (1024 * 1024):.1f} MB of game")


# pygbag's template stretches the canvas with `width/height: 100%` and no
# aspect ratio, and leaves `image-rendering` at its smooth default. Both are
# wrong for a fixed 16:9 pixel-art game: the first squashes the city on any
# window that is not 16:9, the second blurs every hard edge the art is made of.
#
# The fix is to shrink the ELEMENT to 16:9 rather than letterbox the drawing
# inside it, deriving both sides from the viewport so the box is 16:9 by
# construction. `object-fit: contain` looks like the obvious answer and is a trap:
# emscripten turns a click into canvas coordinates by scaling against the
# element's bounding box, so as soon as the drawing stops filling that box,
# every menu click lands somewhere else. Constraining width/height keeps the
# canvas filling its own box - coordinates stay exact - and the page background
# supplies the letterbox. Overriding after the template's own <style> is what
# makes these win the cascade.
PAGE_CSS = """
    <style>
      /* STL-GTA: keep 1280x720 pixel art honest at any window size. */
      html, body { background: #0a0a0c; }
      canvas.emscripten {
        /* !important because pygbag sizes the canvas with an INLINE style,
           which outranks any stylesheet rule without it. Without these the
           canvas keeps whatever square it was given while loading. */
        width: min(100vw, calc(100vh * 16 / 9)) !important;
        height: min(100vh, calc(100vw * 9 / 16)) !important;
        max-width: 100vw !important;
        max-height: 100vh !important;
        inset: 0 !important;
        margin: auto !important;           /* centre in the letterbox */
        image-rendering: pixelated;        /* crisp upscale, not smeared */
      }

      /* A phone can open the link but cannot play a keyboard game, and an
         unexplained letterboxed canvas just looks broken. Say so, but only
         where it is true: `pointer: coarse` is the touch case. Never eat a
         click - the canvas is underneath. */
      #stl-touch-note { display: none; }
      @media (pointer: coarse) {
        #stl-touch-note {
          display: block;
          position: fixed;
          left: 0; right: 0; top: 0;
          z-index: 1000;
          pointer-events: none;
          padding: .7rem .9rem;
          background: #14141a;
          border-bottom: 2px solid #ffc428;
          color: #f2ead6;
          font: 500 15px/1.45 system-ui, -apple-system, sans-serif;
          text-align: center;
        }
        #stl-touch-note b { color: #ffc428; }
      }
    </style>
"""

TOUCH_NOTE = """
    <div id="stl-touch-note">
      <b>STL-GTA needs a keyboard.</b> Open this link on a laptop or desktop
      &mdash; there are no touch controls yet.
    </div>
"""


def polish_page(path):
    """Override the template CSS that would stretch and blur the game."""
    page = io.open(path, encoding="utf-8").read()
    for anchor, addition in (("</head>", PAGE_CSS), ("</body>", TOUCH_NOTE)):
        if anchor not in page:
            raise SystemExit(f"index.html has no {anchor}; pygbag template changed")
        page = page.replace(anchor, addition + anchor, 1)
    io.open(path, "w", encoding="utf-8", newline="").write(page)


def drop_unused_archive(out_dir):
    """pygbag writes the app as both .apk and .tar.gz; the page fetches one.

    Which one varies, so read the page rather than assume, and delete only the
    copy nothing references. That halves what the repo stores and what a
    visitor could be made to download.
    """
    page = io.open(os.path.join(out_dir, "index.html"), encoding="utf-8").read()
    archives = [f for f in os.listdir(out_dir)
                if f.endswith((".apk", ".tar.gz"))]
    used = [f for f in archives if f in page]
    if len(used) != 1:
        print(f"  keeping all archives; page references {len(used)}")
        return
    for name in archives:
        if name not in used:
            os.remove(os.path.join(out_dir, name))
            print(f"  dropped unused {name}")


def main():
    missing = [p for p in SOURCE + ASSETS
               if not os.path.isfile(os.path.join(HERE, p))]
    if missing:
        print("missing file(s), cannot build:", ", ".join(missing))
        return 1

    print("staging web sources")
    stage()

    cmd = [sys.executable, "-m", "pygbag",
           "--build",                    # build only; do not serve
           "--width", "1280", "--height", "720",
           "--app_name", "STL-GTA",
           "--title", "STL-GTA",
           "--can_close", "1",
           "--disable-sound-format-error",
           STAGE]
    print("running pygbag")
    if subprocess.run(cmd, cwd=HERE).returncode != 0:
        print("\npygbag failed; see the output above.")
        return 1

    web = os.path.join(STAGE, "build", "web")
    if not os.path.isfile(os.path.join(web, "index.html")):
        print("\npygbag reported success but produced no index.html")
        return 1
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    shutil.copytree(web, OUT)
    polish_page(os.path.join(OUT, "index.html"))

    drop_unused_archive(OUT)

    total = sum(os.path.getsize(os.path.join(root, f))
                for root, _d, files in os.walk(OUT) for f in files)
    print(f"\n{OUT}  ({total / (1024 * 1024):.1f} MB)")
    print("Commit and push; GitHub Pages serves it at /play/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

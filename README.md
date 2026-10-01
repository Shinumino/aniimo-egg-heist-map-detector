# Aniimo Egg Heist Map Detector

Press **M** in an Operation: Egg Heist Team Mode run, and this tool shows you which map you are on: the whole
map, in the game's own art, with the spawn, the door, the rooms where an egg can be, the keys and the reward
rooms. Your browser shows it, and an overlay can show it on top of the game.

Works with **Aniimo build 3634150** on Windows 10 (2004 or newer) and Windows 11.

## Download and start

1. Download `AniimoEggHeistMapDetector.zip` from [Releases](https://github.com/Shinumino/aniimo-egg-heist-map-detector/releases).
2. Unzip it anywhere.
3. Double-click **Start.bat**.

That's it: Python comes inside the folder, nothing is installed and nothing else is downloaded. The first
start reads the map pictures from your Aniimo install (about 20 seconds); after that it starts in a couple of
seconds. A window stays open while it runs; close it to stop the tool.

The page opens in your browser at http://127.0.0.1:8765. It is only reachable from your own PC.

## How to use it

- **I'm playing:** pick your difficulty (Normal, Hard, Nightmare / Chaos). Some maps look the same at the
  start of a run; knowing the difficulty tells them apart right away.
- **In the run, press M.** About a second later the page shows the map. If two maps still fit, it says so and
  shows both; explore a little and press M again.
- **Overlay:** click *Place overlay*, press **Alt+Tab** to go back to the game, then drag a box where the map
  should go. The *Opacity* slider sets how solid it is, **F8** hides it for a moment, *Off* removes it. The
  overlay shows over the game in borderless or windowed mode, not in exclusive fullscreen.
- **Egg nests:** the marked rooms are where an egg *can* be. The game picks which of them get an egg each run.

## What it reads, what it keeps

- **The game files it reads (never changes):** the build number, the game's tables (inside
  `LuaScripts.xdf`), seven map-art bundles and one icon bundle. It keeps the map pictures it makes from them in
  `%LOCALAPPDATA%\AniimoEggHeistMapDetector`.
- **When you press M** (only while the game is the window in front) it takes a screenshot of the game window,
  the same way a screenshot tool does, and keeps it in the `captures` folder next to `Start.bat`, named with
  the time and the map. Only the newest 10 are kept. A picture you drop into that folder is recognised too
  (and never deleted).
- **It never** opens the game's process, reads its memory or sends anything anywhere. The key is read the way
  any program can ask Windows whether a key is down; it is not hooked or blocked.

The game has an anti-cheat. This tool stays as far from the game as a screenshot tool does, but using any
third-party tool with an online game is at your own risk.

## When the game updates

The tool only runs against the exact game files it was made and tested for. After an update it does nothing
and the page says the game was updated: get the newer version from
[Releases](https://github.com/Shinumino/aniimo-egg-heist-map-detector/releases) when it is out. This way it can
never show you a map that is not right.

## If something goes wrong

- **"Couldn't find Aniimo":** it looks in your Steam libraries. If you installed the game another way, click
  *Choose the Aniimo folder* on the page and pick the folder it is in (or a folder above it). It remembers it.
- **The page doesn't open:** it may already be running; look for the open window, or go to
  http://127.0.0.1:8765.
- **It picked a wrong map:** the screenshot it used is in the `captures` folder. Please open an
  [issue](https://github.com/Shinumino/aniimo-egg-heist-map-detector/issues) with that picture and the map it
  should have been.
- **Chaos:** the game's data has no egg nest spots for Chaos, so none are shown there.

## For developers

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-build.txt
.venv\Scripts\python run.py                         run from source
.venv\Scripts\python -m unittest discover -s tests  tests
.venv\Scripts\python tools\build_portable.py        dist\AniimoEggHeistMapDetector.zip
```

Built and tested with Python 3.14.7. `tests/test_real_game.py` and `tests/smoke_exe.py` need Aniimo installed
and real map screenshots in `tests/fixtures` (not in this repository: they show the game's art). How the maps
work and how a screenshot is matched is written at the top of `src/eggheist.py` and `src/eggheist_match.py`.

## License

MIT, © 2026 Shinumino. You can use, change and share it; keep the license and the copyright line with it.

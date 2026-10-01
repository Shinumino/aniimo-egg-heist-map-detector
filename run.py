"""Aniimo Egg Heist Map Detector: press M in an Egg Heist run, see which map it is.

    AniimoEggHeistMapDetector.exe            (or: python run.py)
    options: --game "X:\\path\\to\\Aniimo"  --port 8765  --no-overlay  --no-capture  --no-browser

Starts a small helper on this PC only (http://127.0.0.1:8765) and opens it in the browser. On the first
start it reads the map pictures from your own Aniimo install (about 20 s) and keeps them in
%LOCALAPPDATA%\\AniimoEggHeistMapDetector. Close this window (or Ctrl+C) to stop it.
"""
import argparse
import json
import os
import sys
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

# The portable download (tools/build_portable.py) ships Tcl/Tk's library unpacked next to its Python, because
# Tcl 9 otherwise looks for zips where the embeddable Python has none. Set before the overlay starts Tk.
_tcl = os.path.join(os.path.dirname(sys.executable), "tcl")
if os.path.isdir(os.path.join(_tcl, "_tcl_data")):
    os.environ.setdefault("TCL_LIBRARY", os.path.join(_tcl, "_tcl_data"))
    os.environ.setdefault("TK_LIBRARY", os.path.join(_tcl, "_tk_data"))

import eggheist  # noqa: E402
import eggheist_capture  # noqa: E402
import eggheist_server  # noqa: E402
import game  # noqa: E402

VERSION = "1.0.0"
# the tool's own folder: next to Start.bat in the portable download (this file is in its app folder), else here
TOOL_DIR = os.path.dirname(HERE) if os.path.isdir(os.path.join(os.path.dirname(HERE), "python")) else HERE
SETTINGS = os.path.join(TOOL_DIR, "settings.json")
CACHE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "AniimoEggHeistMapDetector")
READY = "ready.txt"   # written last: a first start that was interrupted is simply done again


def load(check):
    """The map data for a game that passed the check; the pictures are read from the game once."""
    out = os.path.join(CACHE, check.build)
    heist = eggheist.Heist(check.build, pm_source=check.tables, out=out,
                           tile_bundles=check.tiles, icon_bundles=check.icons)
    if not os.path.exists(os.path.join(out, READY)):
        print("First start: reading the map pictures from your Aniimo install (about 20 seconds)...", flush=True)
        heist.stitch_all()
        heist.extract_icons()
        with open(os.path.join(out, READY), "w") as f:
            f.write(f"{VERSION} {check.build}\n")
    return heist


def load_settings(path=SETTINGS):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)             # never a half-written settings file


def game_folder(explicit=None, settings=None):
    """Where to look for the game: --game first, then the folder chosen on the page, then Steam's libraries."""
    if explicit:
        return game.find_game(explicit)
    chosen = (settings or {}).get("game")
    if chosen and game.is_game(chosen):
        return chosen
    return game.find_game()


def choose(folder, settings_file=SETTINGS, supported=None):
    """The page's "Choose the Aniimo folder": None if the picker was cancelled, else the check of the game found
    at or below `folder`. A folder that passes is remembered for the next starts; one that does not is not."""
    if not folder:
        return None
    found = game.find_game_below(folder)
    if not found:
        return game.Check(folder, blocked=f'There is no Aniimo in "{folder}". Choose the folder Aniimo is installed '
                                          f"in (the one with Aniimo_Data inside, or a folder above it).")
    c = game.check(found, supported)
    if not c.blocked:
        settings = load_settings(settings_file)
        settings["game"] = found
        save_settings(settings_file, settings)
    return c


def on_choose(folder):
    """The page's button, for the helper: None if cancelled, (map data, None) to start, (None, why) to stay put."""
    c = choose(folder)
    if c is None:
        return None
    if c.blocked:
        return None, c.blocked
    return load(c), None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Aniimo Egg Heist Map Detector " + VERSION)
    ap.add_argument("--game", help="the Aniimo folder, if it is not in a Steam library")
    ap.add_argument("--port", type=int, default=eggheist_server.DEFAULT_PORT)
    ap.add_argument("--folder", help="where captures are kept (default: captures, next to Start.bat)")
    ap.add_argument("--no-overlay", action="store_true", help="no on-screen overlay window")
    ap.add_argument("--no-capture", action="store_true", help="do not take a screenshot when M is pressed")
    ap.add_argument("--no-browser", action="store_true", help="do not open the page in the browser")
    a = ap.parse_args(argv)
    print(f"Aniimo Egg Heist Map Detector {VERSION}  (MIT, (c) 2026 Shinumino)", flush=True)
    eggheist_capture.enable_dpi_awareness()
    c = game.check(game_folder(a.game, load_settings()))
    heist = None
    if c.blocked:
        print(c.blocked, flush=True)
    else:
        print(f"Aniimo build {c.build} at {c.game}", flush=True)
        heist = load(c)
    url = f"http://127.0.0.1:{a.port}"
    folder = a.folder or os.path.join(TOOL_DIR, "captures")
    try:
        app = eggheist_server.App(build=c.build, folder=folder, port=a.port, capture=not a.no_capture,
                                  heist=heist, blocked=c.blocked, on_choose=on_choose).start()
    except OSError:
        # the port is taken: almost always the tool is already running; show that one instead
        print(f"Already running? Opening {url}", flush=True)
        if not a.no_browser:
            webbrowser.open(url)
        return
    print(f"Open {url}  (close this window to stop)", flush=True)
    if not a.no_browser:
        webbrowser.open(url)
    eggheist_server.run(app, overlay=not a.no_overlay and not c.blocked)


if __name__ == "__main__":
    main()

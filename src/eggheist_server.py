"""Egg Heist helper: press M in the game and the page shows which map this is.

    .venv/Scripts/python.exe src/eggheist_server.py                 # then open http://127.0.0.1:8765
    .venv/Scripts/python.exe src/eggheist_server.py --folder "X:/some/other/folder" --port 8765

Takes the screenshot itself when M is pressed in the game (src/eggheist_capture.py) and keeps the newest
10 in a `captures` folder next to the tool. Any other image dropped into that folder is matched too. Each one goes through src/eggheist_match.py; it serves
web/eggheist.html plus the map art. Stop it with Ctrl+C; nothing keeps running after that.

It reads image files, the M key's state and the screen inside the game window, like a screenshot tool.
It never opens the game's process or reads its memory: the game ships a kernel anti-cheat
(NEP2 / NEPKernel.sys), see README "Rules" and src/eggheist_capture.py.

Security pass (house rules, 2026-09-30):
- new input: image files that appear in one folder the user chose; decoded with OpenCV, nothing executed.
- new surface: an HTTP server bound to 127.0.0.1 only (not reachable from the network). Routes are an
  allow-list: the page, two JSON feeds, map art by known map id, icons by known name. Everything else 404,
  so no path from a request ever reaches the file system.
- new permission: none. Hostile case: a local program could flood the folder with images; only the newest
  pending file is matched per poll, so the cost is capped at one match (~6 s CPU) at a time.
"""
import argparse
import json
import logging
import logging.handlers
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import eggheist  # noqa: E402
import eggheist_capture  # noqa: E402
import eggheist_match  # noqa: E402
import eggheist_overlay  # noqa: E402

log = logging.getLogger("eggheist")
log.setLevel(logging.INFO)   # info lines (each capture) count, not only warnings
LOG_BYTES = 1_000_000      # log.txt rolls over at this size, one older file kept: at most ~2 MB on disk


def setup_logging(path):
    """The log someone sends when the tool got something wrong (user, 2026-10-01: whether things worked, and
    the name of the picture used). Capped and rolled over so it never piles up. Uncaught errors, also in
    the helper's threads, go in with their traceback instead of only flashing by in the console window."""
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=LOG_BYTES, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(handler)
    sys.excepthook = lambda t, v, tb: log.critical("uncaught error", exc_info=(t, v, tb))
    threading.excepthook = lambda a: log.critical(f"uncaught error in thread {a.thread.name if a.thread else '?'}",
                                                  exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return handler


def describe(res):
    """One line of why: the best map's score and evidence, and the runner-up's score."""
    if not res.candidates:
        return "no candidates"
    b = res.best
    d = b.detail
    nxt = res.candidates[1] if len(res.candidates) > 1 else None
    door = "-" if d.get("door") is None else f"{d['door']:.2f}"
    s = f"best {b.map_id} score {b.score:.2f} (door {door} art {d.get('art', 0):.2f} ncc {d.get('ncc', 0):.2f})"
    return s + (f", next {nxt.map_id} {nxt.score:.2f}" if nxt else "")

DEFAULT_BUILD = "3629693"
DEFAULT_PORT = 8765
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
# in the public tool's .exe (PyInstaller) the page sits next to the unpacked program, not two folders up
PAGE = os.path.join(getattr(sys, "_MEIPASS", ROOT), "web", "eggheist.html")
WEBP_QUALITY = 82


KEEP = 10                  # captures kept; older ones the helper saved are deleted (user: so they do not pile up)
OWN_NAME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{6}( \(\d+\))? .+\.jpg$")   # how _save names its files


def default_folder():
    """`captures` next to the tool. It was Pictures/Egg Heist until the user asked to keep them out of their
    own folders (2026-10-01): the tool's files stay with the tool."""
    return os.path.join(ROOT, "captures")


def read_image(path):
    # cv2.imread cannot open non-ASCII paths on Windows; screenshot names are the user's locale
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


class App:
    def __init__(self, build=DEFAULT_BUILD, folder=None, host="127.0.0.1", port=DEFAULT_PORT, poll=1.0, capture=True,
                 heist=None, blocked=None, pick_folder=None, on_choose=None):
        """`heist`: the map data to use (default: the author's local copy of `build`). `blocked`: a reason not to run at
        all (the public tool's game check failed): then only the page is served, saying why.
        `on_choose(folder)`: what the page's "Choose the Aniimo folder" does with the folder picked by
        `pick_folder()` (default: a Windows folder picker): None (cancelled), or (heist, None) to start with,
        or (None, reason) to stay blocked. Only offered while blocked."""
        self.build, self.folder, self.host, self.port, self.poll = build, folder, host, port, poll
        self._want_capture = capture
        self.capture = capture and not blocked
        self.pick_folder, self.on_choose, self._choosing = pick_folder or pick_folder_dialog, on_choose, False
        self.heist, self.matcher, self.blocked = heist, None, blocked
        self.difficulty = None     # 3 Normal, 4 Hard, 5 Nightmare/Chaos (same maps); None = any. Set by the page.
        # set by the page: where the overlay goes (dragged on screen; None = off), how opaque, and whether a
        # drag is under way
        self._overlay = {"rect": None, "alpha": eggheist_overlay.ALPHA, "placing": False}
        self._own = set()          # files this helper saved itself: never re-matched as "new screenshots"
        self.keep = KEEP
        self.latest = {"match": None, "seq": 0, "status": "starting", "difficulty": None, "blocked": blocked,
                       "can_choose": on_choose is not None,
                       "overlay": {"rect": None, "alpha": eggheist_overlay.ALPHA, "placing": False}}
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # -- data ---------------------------------------------------------------------------------------------
    def prepare(self):
        if self.blocked:   # nothing from the game is read: an empty map list, the page shows the reason
            self.map_ids, self.icons, self.web_dir = set(), {}, None
            self.maps_json = json.dumps({"pools": {}, "levels": {}, "maps": {}, "size": 2048}).encode()
            return
        self.heist = self.heist or eggheist.load(self.build)
        self.matcher = eggheist_match.Matcher(self.heist)
        self.map_ids = set(self.heist.team_maps())
        self.icons = {os.path.splitext(n)[0]: os.path.join(self.heist.out, "icons", n)
                      for n in os.listdir(os.path.join(self.heist.out, "icons")) if n.endswith(".png")}
        self.web_dir = os.path.join(self.heist.out, "web")
        os.makedirs(self.web_dir, exist_ok=True)
        maps = {}
        for sid in sorted(self.map_ids):
            levels = self.heist.levels_of(sid)
            maps[str(sid)] = {
                "levels": levels,
                "markers": {str(lv): [{"kind": m["kind"], "x": round(m["art"][0], 1), "y": round(m["art"][1], 1)}
                                      for m in self.heist.markers(sid, lv)] for lv in levels},
            }
            webp = os.path.join(self.web_dir, f"{sid}.webp")
            if not os.path.exists(webp):
                self.heist.art(sid).save(webp, "WEBP", quality=WEBP_QUALITY)
        self.maps_json = json.dumps({
            "pools": {str(lv): self.heist.pool(lv) for lv in eggheist.TEAM_LEVELS},
            "levels": {str(k): v for k, v in eggheist.LEVEL_NAMES.items()},
            "maps": maps,
            "size": 2048,
        }).encode()

    # -- watching -----------------------------------------------------------------------------------------
    def _images(self):
        try:
            names = os.listdir(self.folder)
        except OSError:
            return {}
        out = {}
        for n in names:
            if n.lower().endswith(IMAGE_EXT):
                try:
                    st = os.stat(os.path.join(self.folder, n))
                    out[n] = (st.st_mtime, st.st_size)
                except OSError:
                    pass
        return out

    def _watch(self):
        seen = self._images()      # what was there before we started is history, not a new screenshot
        pending = {}
        self._set(status=self.watching())
        while not self._stop.wait(self.poll):
            now = self._images()
            for n, (mtime, size) in now.items():
                if (n not in seen or seen[n] != (mtime, size)) and n not in self._own:
                    pending[n] = (mtime, size)
            seen = now
            if not pending:
                continue
            # newest file first; wait until its size stops changing (the snipping tool writes in steps)
            name = max(pending, key=lambda k: pending[k][0])
            if now.get(name) != pending[name] or time.time() - pending[name][0] < self.poll:
                pending[name] = now.get(name, pending[name])
                continue
            pending.clear()
            self._match_file(name)

    def _match_file(self, name):
        path = os.path.join(self.folder, name)
        self._set(status=f"matching {name}")
        img = read_image(path)
        if img is None:
            log.warning(f"picture {name!r}: could not read it")
            self._set(status=f"could not read {name}", error=name)
            return
        res = self._match(img)
        log.info(f"picture {name!r} -> {self._outcome(res)}; {describe(res)}{self._filter()}")
        self._publish(img, name, res)

    @staticmethod
    def _outcome(res):
        if res.looks_like_map:
            return f"map {res.best.map_id} shown"
        if res.has_evidence:
            return "one of " + ", ".join(str(m) for m in res.shortlist)
        return "not the map"

    def _filter(self):
        return f"; playing {eggheist.LEVEL_NAMES.get(self.difficulty, '?')}" if self.difficulty else "; playing any"

    def _match(self, img):
        pool = self.heist.pool(self.difficulty) if self.difficulty else None
        return self.matcher.match(img, maps=pool)

    def set_difficulty(self, level):
        if level != self.difficulty:
            log.info(f"playing: {eggheist.LEVEL_NAMES.get(level, 'any') if level else 'any'}")
        self.difficulty = level
        with self._lock:
            self.latest["difficulty"] = level

    def overlay_settings(self):
        with self._lock:
            return dict(self._overlay)

    def set_overlay(self, **change):
        with self._lock:
            self._overlay.update(change)
            self.latest["overlay"] = dict(self._overlay)

    def start_placing(self):
        self.set_overlay(placing=True)

    def placed(self, rect):
        """The drag finished: its box, or None (cancelled) which keeps the old place."""
        if rect:
            log.info(f"overlay placed at {list(rect)}")
            self.set_overlay(rect=list(rect), placing=False)
        else:
            log.info("overlay placing cancelled")
            self.set_overlay(placing=False)

    def on_capture(self, img):
        """A press of M in the game. Unlike a screenshot the user chose to take, this is often NOT the map
        (M closes it too; M in chat), so it only replaces the shown map when it clearly is one."""
        self._set(status="matching (M key)")
        t0 = time.time()
        res = self._match(img)
        took = time.time() - t0
        if res.looks_like_map:
            name = self._save(img, f"map {res.best.map_id}")
            self._publish(img, "M key", res)
        elif res.has_evidence:     # a map screen, but two or more maps fit it so far: show the shortlist
            name = self._save(img, "maybe " + " or ".join(str(m) for m in res.shortlist))
            self._publish(img, "M key", res)
        else:
            name = self._save(img, "not the map")
        log.info(f"M key: {name!r} -> {self._outcome(res)}; {describe(res)}{self._filter()}; {took:.1f} s")
        if not (res.looks_like_map or res.has_evidence):
            self._set(status=f"M pressed at {time.strftime('%H:%M:%S')}, but that didn't look like the map. "
                             f"{self.watching()}")

    def _save(self, img, what, stamp=None):
        """Each capture is kept, named by time and what it was, so a wrong one can be opened or sent; only the
        newest `keep` of them stay. Files the helper did not name (a picture the user dropped in) are never
        deleted."""
        stamp = stamp or time.strftime("%Y-%m-%d %H%M%S")
        name = f"{stamp} {what}.jpg"
        n = 2
        while os.path.exists(os.path.join(self.folder, name)):
            name = f"{stamp} ({n}) {what}.jpg"
            n += 1
        self._own.add(name)
        try:   # imencode + tofile: cv2.imwrite cannot write non-ASCII paths on Windows
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if ok:
                buf.tofile(os.path.join(self.folder, name))
        except OSError as e:
            log.warning(f"could not save {name}: {e}")
        self._prune()
        return name

    def _prune(self):
        try:
            own = sorted(n for n in os.listdir(self.folder) if OWN_NAME.match(n))   # names sort by time
        except OSError:
            return
        for n in own[:max(0, len(own) - self.keep)]:
            try:
                os.remove(os.path.join(self.folder, n))
            except OSError:
                pass

    def watching(self):
        parts = [f"watching {self.folder}"] + (["press M in the game"] if self.capture else [])
        return "; ".join(parts)

    def _publish(self, img, name, res):
        best = res.best
        match = {
            "file": name,
            "time": time.strftime("%H:%M:%S"),
            "map_id": best.map_id,
            "levels": self.heist.levels_of(best.map_id),
            "confident": res.looks_like_map,
            "shortlist": res.shortlist or [best.map_id],
            "difficulty": self.difficulty,
            "candidates": [{"map_id": c.map_id, "score": round(c.score, 3)} for c in res.candidates[:5]],
            "screen": {"w": img.shape[1], "h": img.shape[0], "scale": best.scale, "shift": list(best.shift)},
        }
        self._set(match=match, status=self.watching(), bump=True)

    def _set(self, match=None, status=None, error=None, bump=False):
        with self._lock:
            if match is not None:
                self.latest["match"] = match
            if status is not None:
                self.latest["status"] = status
            self.latest["error"] = error
            if bump:
                self.latest["seq"] += 1

    # -- serving ------------------------------------------------------------------------------------------
    def handler(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):   # quiet: one line per poll would bury the useful output
                pass

            def send(self, code, ctype, body):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "max-age=3600")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                p = self.path.split("?")[0]
                if p in ("/", "/index.html"):
                    with open(PAGE, "rb") as f:
                        return self.send(200, "text/html; charset=utf-8", f.read())
                if p == "/api/latest":
                    with app._lock:
                        return self.send(200, "application/json", json.dumps(app.latest).encode())
                if p == "/api/maps":
                    return self.send(200, "application/json", app.maps_json)
                m = re.fullmatch(r"/maps/(\d+)\.webp", p)
                if m and int(m.group(1)) in app.map_ids:
                    with open(os.path.join(app.web_dir, f"{m.group(1)}.webp"), "rb") as f:
                        return self.send(200, "image/webp", f.read())
                m = re.fullmatch(r"/icons/(\w+)\.png", p)
                if m and m.group(1) in app.icons:
                    with open(app.icons[m.group(1)], "rb") as f:
                        return self.send(200, "image/png", f.read())
                self.send(404, "text/plain", b"not found")

            def do_POST(self):
                if self.path not in ("/api/difficulty", "/api/overlay", "/api/overlay/place", "/api/game/choose"):
                    return self.send(404, "text/plain", b"not found")
                # JSON only: a browser sends a cross-site text/plain or form post without asking first, but
                # must ask (a CORS preflight, which this server never answers) before a JSON one. So no other
                # website open in the browser can change the settings.
                if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                    return self.send(415, "text/plain", b"JSON only")
                n = int(self.headers.get("Content-Length") or 0)
                if n > 200:
                    return self.send(413, "text/plain", b"too long")
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                    if not isinstance(body, dict):
                        raise ValueError
                except ValueError:
                    return self.send(400, "text/plain", b"bad JSON")
                if self.path == "/api/difficulty":
                    level = body.get("level")
                    if level is not None and (type(level) is not int or level not in (3, 4, 5)):
                        return self.send(400, "text/plain", b"level must be 3, 4, 5 or null")
                    app.set_difficulty(level)
                    return self.send(200, "application/json", json.dumps({"difficulty": level}).encode())
                if self.path == "/api/game/choose":
                    started = app.choose_game()
                    return self.send(202 if started else 409, "application/json", json.dumps({"started": started}).encode())
                if self.path == "/api/overlay/place":
                    app.start_placing()
                    return self.send(200, "application/json", json.dumps(app.overlay_settings()).encode())
                change = {}
                if "rect" in body:
                    r = body["rect"]
                    if r is not None and not _sane_rect(r):
                        return self.send(400, "text/plain", b"rect must be [x, y, w, h] in screen px, or null")
                    change["rect"] = r
                if "alpha" in body:
                    a = body["alpha"]
                    lo, hi = eggheist_overlay.ALPHA_RANGE
                    if type(a) not in (int, float) or not lo <= a <= hi:
                        return self.send(400, "text/plain", b"alpha must be a number from 0.2 to 1")
                    change["alpha"] = float(a)
                app.set_overlay(**change)
                self.send(200, "application/json", json.dumps(app.overlay_settings()).encode())

        return Handler

    def start(self):
        if self.folder is None:
            self.folder = default_folder()
        os.makedirs(self.folder, exist_ok=True)
        self.prepare()
        self.server = ThreadingHTTPServer((self.host, self.port), self.handler())
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        if self.blocked:
            self._set(status="not running: see the message on the page")
            return self
        self._run_watchers()
        return self

    def _run_watchers(self):
        self._watcher = threading.Thread(target=self._watch, daemon=True)
        self._watcher.start()
        if self.capture:
            eggheist_capture.enable_dpi_awareness()
            cap = eggheist_capture.Capture(on_image=self.on_capture)
            threading.Thread(target=cap.run, args=(self._stop,), daemon=True).start()

    # -- choosing the game folder from the page -----------------------------------------------------------------
    def choose_game(self):
        """The page's button: pick a folder, check it, and start for real if it is the game. Runs in its own
        thread (reading the map pictures the first time takes ~20 s); the page follows /api/latest."""
        if self._choosing or not self.blocked or not self.on_choose:
            return False
        self._choosing = True
        threading.Thread(target=self._choose, daemon=True).start()
        return True

    def _choose(self):
        try:
            self._set(status="choose the Aniimo folder in the window that opened")
            folder = self.pick_folder()
            log.info(f"choose the Aniimo folder: {folder!r}" if folder else "choose the Aniimo folder: cancelled")
            if folder:
                self._set(status="checking the folder; the first time it also reads the map pictures (about 20 seconds)")
            outcome = self.on_choose(folder)
            if outcome is None:                                   # cancelled
                self._set(status="not running: see the message on the page")
                return
            heist, reason = outcome
            log.info(f"chosen folder: {'ok, build ' + heist.build if heist else 'refused: ' + reason}")
            if heist is None:
                self.blocked = reason
                with self._lock:
                    self.latest["blocked"] = reason
                self._set(status="not running: see the message on the page")
                return
            self.heist, self.build = heist, heist.build
            self.prepare_unblocked()
        finally:
            self._choosing = False

    def prepare_unblocked(self):
        self.blocked = None
        self.prepare()
        self.capture = self._want_capture
        with self._lock:
            self.latest["blocked"] = None
        self._run_watchers()

    def stop(self):
        self._stop.set()
        self.server.shutdown()
        self.server.server_close()


def _sane_rect(r):
    return (isinstance(r, list) and len(r) == 4 and all(type(v) in (int, float) and abs(v) < 100_000 for v in r)
            and r[2] >= eggheist_overlay.MIN_W and r[3] >= eggheist_overlay.MIN_H)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", default=DEFAULT_BUILD)
    ap.add_argument("--folder", help="where captures are kept and new images are picked up (default: captures next to the tool)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-capture", action="store_true", help="do not take a screenshot when M is pressed in the game")
    ap.add_argument("--no-overlay", action="store_true", help="no on-screen overlay window (the page still works)")
    a = ap.parse_args()
    setup_logging(os.path.join(ROOT, "eggheist.log"))
    app = App(a.build, a.folder, port=a.port, capture=not a.no_capture).start()
    # flush: when stdout is a pipe (tests/smoke_eggheist.py waits for this line) it is block-buffered
    print(f"Egg Heist helper: open http://127.0.0.1:{app.port}  (watching {app.folder}, Ctrl+C to stop)", flush=True)
    run(app, overlay=not a.no_overlay)


def run(app, overlay=True):
    """Keep a started helper running until Ctrl+C: with the overlay window in the main thread, or plain."""
    try:
        if not overlay:
            while True:
                time.sleep(1)
        else:
            while app.blocked:              # until the page's "Choose the Aniimo folder" finds the game, if ever
                time.sleep(0.5)
            # the overlay window needs the main thread (Tk); it stays hidden until a place is picked on the page
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            eggheist_overlay.Overlay(app, root)
            root.after(200, _wake, root)
            root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()


def pick_folder_dialog():
    """The normal Windows folder picker, on top of everything. Only used while the tool is blocked, so no
    other Tk window (the overlay) exists yet; it gets its own short-lived Tk root in this thread."""
    # test seam: tests/smoke_exe.py cannot click inside a Windows dialog, so it names the folder here instead
    if os.environ.get("EGGHEIST_TEST_PICK"):
        return os.environ["EGGHEIST_TEST_PICK"]
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askdirectory(parent=root, title="Choose the folder Aniimo is installed in", mustexist=True) or None
    finally:
        root.destroy()


def _wake(root):
    # Tk's mainloop does not return to Python on its own, so Ctrl+C would wait for the next window event;
    # waking every 200 ms lets the KeyboardInterrupt through right away
    root.after(200, _wake, root)


if __name__ == "__main__":
    main()

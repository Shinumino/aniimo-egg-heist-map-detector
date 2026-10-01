"""Smoke test of the built .exe, the way a user runs it.

    python tests/smoke_exe.py [path/to/AniimoEggHeistMapDetector.exe]
    python tests/smoke_exe.py dist/AniimoEggHeistMapDetector/Start.bat      (the portable download)

1. Starts it against the real game (overlay on, no browser, a temporary capture folder), checks the 21 maps
   load and that a real screenshot dropped into the folder comes back as the right map.
2. Starts it against a fake game folder of another build: it must refuse, point to GitHub, load nothing.
Needs Aniimo installed and the screenshots (EGGHEIST_FIXTURES, see tests/test_real_game.py).
Exits non-zero on any failure.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import game  # noqa: E402

EXE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist", "AniimoEggHeistMapDetector.exe"))
FIX = os.environ.get("EGGHEIST_FIXTURES") or os.path.join(ROOT, "tests", "fixtures")
fails = []
CACHE = tempfile.mkdtemp(prefix="exe-smoke-cache-")


def check(ok, what):
    print(("ok    " if ok else "FAIL  ") + what, flush=True)
    if not ok:
        fails.append(what)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return json.loads(r.read())


def start(args, wait_for="Open http", timeout=180, extra_env=None):
    """Start the exe; return (process, its output so far) once `wait_for` is printed or it exits."""
    cmd = ["cmd", "/c", EXE] if EXE.lower().endswith(".bat") else [EXE]   # the portable download's Start.bat
    # a fresh, empty cache: the first start (which reads the game's bundles with UnityPy) has to really
    # happen. With the author's warm cache it was skipped, and a Smart App Control block went unnoticed.
    env = dict(os.environ, LOCALAPPDATA=CACHE, **(extra_env or {}))
    p = subprocess.Popen(cmd + ["--no-browser"] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env=env)
    lines = []

    def read():
        for line in p.stdout:
            lines.append(line.rstrip())
    threading.Thread(target=read, daemon=True).start()
    end = time.time() + timeout
    while time.time() < end and p.poll() is None and not any(wait_for in x for x in lines):
        time.sleep(0.3)
    return p, lines


def stop(p):
    # a one-file .exe starts a second copy of itself that does the work; killing only the first one left
    # the real one running (found on 2026-10-01), so stop the whole tree
    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    p.wait(10)


def real_game():
    folder = tempfile.mkdtemp(prefix="exe-smoke-")
    port = free_port()
    p, out = start(["--port", str(port), "--no-capture", "--folder", folder])
    try:
        check(p.poll() is None, "starts and keeps running with the overlay on: " + " | ".join(out[-3:]))
        if p.poll() is not None:
            return
        check(len(get(port, "/api/maps")["maps"]) == 21, "the 21 Team Mode maps load")
        shutil.copy(os.path.join(FIX, "nightmare_start.jpg"), os.path.join(folder, "shot.jpg"))
        m, end = None, time.time() + 60
        while time.time() < end and not m:
            m = get(port, "/api/latest")["match"]
            time.sleep(0.5)
        check(bool(m) and m["map_id"] == 20036 and m["confident"], f"a real screenshot is map 20036 ({m and m['map_id']})")
        logfile = os.path.join(os.path.dirname(EXE), "log.txt")
        text = open(logfile, encoding="utf-8").read() if os.path.exists(logfile) else ""
        check("picture 'shot.jpg' -> map 20036 shown" in text, "log.txt names the picture and what was done with it")
    finally:
        stop(p)
        shutil.rmtree(folder, ignore_errors=True)


def other_build():
    fake = tempfile.mkdtemp(prefix="exe-fake-game-")
    lua = os.path.join(fake, "Aniimo_Data", "cvs", "res", "lua")
    os.makedirs(lua)
    with open(os.path.join(lua, "LuaCacheVer.txt"), "w") as f:
        f.write("1.0.9999999,1,0")
    port = free_port()
    p, out = start(["--port", str(port), "--game", fake])
    try:
        latest = get(port, "/api/latest")
        check("9999999" in (latest.get("blocked") or "") and game.RELEASES_URL in latest["blocked"],
              "another build: refuses and points to GitHub")
        check(get(port, "/api/maps")["maps"] == {}, "another build: loads no maps")
    finally:
        stop(p)
        shutil.rmtree(fake, ignore_errors=True)


def choose_folder():
    """Blocked (pointed at an empty folder), then the page's "Choose the Aniimo folder" with the folder ABOVE the
    real install picked: it must find the game inside and start without a restart."""
    empty = tempfile.mkdtemp(prefix="exe-not-a-game-")
    settings = os.path.join(os.path.dirname(EXE), "settings.json")
    before = open(settings, "rb").read() if os.path.exists(settings) else None
    port = free_port()
    p, out = start(["--port", str(port), "--game", empty, "--no-capture"],
                   extra_env={"EGGHEIST_TEST_PICK": os.path.dirname(game.find_game())})
    try:
        latest = get(port, "/api/latest")
        check(bool(latest.get("blocked")) and latest.get("can_choose"), "an empty folder: blocked, with the choose button")
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/game/choose", data=b"{}",
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10).close()
        end = time.time() + 120
        while time.time() < end and get(port, "/api/latest").get("blocked"):
            time.sleep(0.5)
        check(get(port, "/api/latest").get("blocked") is None, "choosing the folder above the game starts the tool")
        check(len(get(port, "/api/maps")["maps"]) == 21, "and its 21 maps load without a restart")
        check(os.path.exists(settings), "the chosen folder is remembered (settings.json)")
    finally:
        stop(p)
        shutil.rmtree(empty, ignore_errors=True)
        if before is None:
            if os.path.exists(settings):
                os.remove(settings)
        else:
            open(settings, "wb").write(before)


def windows_blocks(since):
    """Smart App Control / Code Integrity blocks since `since` (epoch s) of files in the tool's folder."""
    # FilterHashtable + StartTime: a first version filtered the newest 200 entries by a hand-converted time and
    # found nothing even with real blocks in the log (checked against the 18:59 UnityPyBoost blocks)
    ps = ("$t = [DateTimeOffset]::FromUnixTimeSeconds(%d).LocalDateTime; "
          "Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-CodeIntegrity/Operational'; Id=3033,3077; StartTime=$t} "
          "-ErrorAction SilentlyContinue | ForEach-Object { if ($_.Message -match 'attempted to load (.+?) that') { $matches[1] } }"
          % int(since))
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
    name = os.path.basename(os.path.dirname(EXE)).lower()
    return sorted({line.strip() for line in out.splitlines() if name in line.lower()})


if __name__ == "__main__":
    if not os.path.exists(EXE):
        sys.exit(f"no {EXE}: run build.ps1 first")
    began = time.time()
    real_game()
    other_build()
    choose_folder()
    blocked = windows_blocks(began)
    check(not blocked, f"Windows blocked none of the tool's files {blocked}")
    shutil.rmtree(CACHE, ignore_errors=True)
    print(f"\n{len(fails)} failed" if fails else "\nall checks passed")
    sys.exit(1 if fails else 0)

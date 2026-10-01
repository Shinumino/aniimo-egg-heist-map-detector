"""Build the portable download: dist/AniimoEggHeistMapDetector/ (and a .zip of it).

    .venv/Scripts/python.exe tools/build_portable.py

Why this exists next to the .exe: Windows 11 Smart App Control blocks unknown unsigned programs, and a
PyInstaller .exe is always unknown (nobody else has that exact file). It blocked ours on the author's PC
(2026-10-01). This folder holds only files Windows can already vouch for:
- python/: the official embeddable Python from python.org (signed by the Python Software Foundation),
  plus tkinter for the overlay copied from the same Python's official install;
- python/Lib/site-packages: the packages, the standard wheels from PyPI (the same files millions of
  people have), at the exact versions in requirements.txt;
- app/: this tool's own code as plain .py files (scripts are not programs to Smart App Control);
- Start.bat: runs app/run.py with python/python.exe.
The user unzips and double-clicks Start.bat: nothing is installed and nothing else is downloaded.
"""
import glob
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_VERSION = "3.14.7"          # must match the Python the tests and the .exe are built with
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
OUT = os.path.join(ROOT, "dist", "AniimoEggHeistMapDetector")
TK_FILES = ["DLLs/_tkinter.pyd", "DLLs/tcl90.dll", "DLLs/tcl9tk90.dll", "DLLs/zlib1.dll"]
START_BAT = r"""@echo off
rem Aniimo Egg Heist Map Detector: starts the tool with the Python that comes in this folder.
rem Close this window to stop it.
"%~dp0python\python.exe" "%~dp0app\run.py" %*
if errorlevel 1 pause
"""


def step(msg):
    print(f"-- {msg}", flush=True)


SOURCE_ONLY = {"tpk_ar"}   # published only as source on PyPI (a UnityPy dependency): built here, must stay pure Python


def binaries_built_here(sp):
    """Compiled files inside the packages pip had to build from source. Wheels downloaded from PyPI may carry
    binaries (fmod_toolkit ships fmod.dll inside a pure-Python wheel): those are the published files, known
    to Windows. A binary compiled HERE would be an unknown file again, the very thing Smart App Control
    blocks, so any is refused. A first version flagged every .dll not in a platform wheel and caught fmod.dll."""
    out = []
    for rec in glob.glob(os.path.join(sp, "*.dist-info", "RECORD")):
        name = os.path.basename(os.path.dirname(rec)).split("-")[0].lower().replace("-", "_")
        if name not in SOURCE_ONLY:
            continue
        with open(rec, encoding="utf-8") as f:
            out += [line.split(",")[0] for line in f if line.split(",")[0].endswith((".pyd", ".dll", ".exe"))]
    found = {os.path.basename(os.path.dirname(r)).split("-")[0].lower() for r in glob.glob(os.path.join(sp, "*.dist-info", "RECORD"))}
    unexpected = sorted(found & SOURCE_ONLY ^ SOURCE_ONLY)
    if unexpected:
        out.append(f"(expected source-only packages not found: {unexpected}: the dependency tree changed, re-check)")
    return out


def main():
    if sys.version.split()[0] != PY_VERSION:
        sys.exit(f"build with Python {PY_VERSION} (this is {sys.version.split()[0]}): the packages must match it")
    shutil.rmtree(OUT, ignore_errors=True)
    py = os.path.join(OUT, "python")
    os.makedirs(py)

    step(f"official embeddable Python {PY_VERSION}")
    cache = os.path.join(ROOT, "build", f"python-{PY_VERSION}-embed-amd64.zip")
    if not os.path.exists(cache):
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        urllib.request.urlretrieve(EMBED_URL, cache)
    with zipfile.ZipFile(cache) as z:
        z.extractall(py)
    print("   sha256", hashlib.sha256(open(cache, "rb").read()).hexdigest())

    step("tkinter from this Python's official install (the embeddable one has none; the overlay needs it)")
    base = sys.base_prefix
    for f in TK_FILES:
        shutil.copy2(os.path.join(base, f), py)
    shutil.copytree(os.path.join(base, "Lib", "tkinter"), os.path.join(py, "Lib", "tkinter"),
                    ignore=shutil.ignore_patterns("__pycache__", "test*"))
    # Tcl 9 keeps its own library in zips; unpacked next to Python, and run.py points Tcl at them
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "unpack_tcl.py"), os.path.join(py, "tcl")], check=True)

    step("packages: the standard PyPI wheels at the pinned versions")
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-compile", "--prefer-binary",
                    "--target", os.path.join(py, "Lib", "site-packages"), "-r", os.path.join(ROOT, "requirements.txt")],
                   check=True)

    # UnityPyBoost: UnityPy's optional C speed-up. Smart App Control blocked it on the author's PC (a popup
    # on the first start, 2026-10-01) while every other package file passed; UnityPy falls back to plain
    # Python when it is missing (try/except ImportError in UnityPy/helpers), so it is left out.
    for f in glob.glob(os.path.join(py, "Lib", "site-packages", "UnityPy", "UnityPyBoost*.pyd")):
        os.remove(f)
    built = binaries_built_here(os.path.join(py, "Lib", "site-packages"))
    if built:
        sys.exit("compiled here, not published on PyPI: " + ", ".join(built))

    step("search path: stdlib zip, Lib, site-packages, the app")
    pth = glob.glob(os.path.join(py, "python*._pth"))[0]
    with open(pth, "w") as f:
        f.write("python314.zip\n.\nLib\nLib\\site-packages\n..\\app\\src\nimport site\n")

    step("the app")
    app = os.path.join(OUT, "app")
    os.makedirs(app)
    shutil.copy2(os.path.join(ROOT, "run.py"), app)
    for d in ("src", "web"):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(app, d), ignore=shutil.ignore_patterns("__pycache__"))
    for f in ("LICENSE", "README.md", "CHANGELOG.md"):
        if os.path.exists(os.path.join(ROOT, f)):
            shutil.copy2(os.path.join(ROOT, f), OUT)
    with open(os.path.join(OUT, "Start.bat"), "w", newline="\r\n") as f:
        f.write(START_BAT)

    step("zip")
    z = shutil.make_archive(OUT, "zip", os.path.dirname(OUT), os.path.basename(OUT))
    size = sum(os.path.getsize(os.path.join(dp, n)) for dp, _, ns in os.walk(OUT) for n in ns)
    print(f"   {OUT}  ({size / 1e6:.0f} MB)\n   {z}  ({os.path.getsize(z) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()

"""Find the Aniimo install and decide whether this version of the tool may run against it.

The tool only ever READS the game's files, and only these: the build number, the table file inside the
Lua archive, the seven map-art bundles and one icon bundle. It never touches the running game.

It runs only against exactly the files it was made and tested for: the build number, a fingerprint of the
tables, and the exact bundle file names. Anything else (an update, a hotfix that keeps the build number, a
missing file) means it does nothing and says to check GitHub for a newer version. The game updated the
very morning this was written (3629693 -> 3634150) with no notice, so this is not a theoretical case.
"""
import hashlib
import os
import re
import zipfile
from dataclasses import dataclass, field

RELEASES_URL = "https://github.com/Shinumino/aniimo-egg-heist-map-detector/releases"
TABLES_IN_ARCHIVE = "xfs/luascripts/Common/Data/pmdata.bin"
LUA_ARCHIVE = os.path.join("Aniimo_Data", "StreamingAssets", "cvs", "res", "lua", "LuaScripts.xdf")
BUILD_FILE = os.path.join("Aniimo_Data", "cvs", "res", "lua", "LuaCacheVer.txt")
BUNDLES = os.path.join("Aniimo_Data", "StreamingAssets", "cvs", "res", "uab", "win", "DefaultPackage")

# The game files this version was made and tested for. Egg Heist data checked unchanged from build 3629693
# (164 tables compared, 2026-10-01); the map art bundles are the same files as in 3629693.
SUPPORTED = {
    "3634150": {
        "tables_sha256": "14552ae57c7d99279ac3791e732ca74ae5dc8cc6db38c01d0e4e0b0134fc77bb",
        "tiles": [
            "mres_xgui_exall_0_4802707611e9c5f427a3e37eed9f7b75.uab",
            "mres_xgui_exall_1_5872513a083a68228e9a224285e10cdd.uab",
            "mres_xgui_exall_2_04d0b78f6318a83be968ab8ecfda7616.uab",
            "mres_xgui_exall_3_c20353d70b1e5231c63da3e54bdb4930.uab",
            "mres_xgui_exall_4_10d9a0ebeea12109ca0c0a8ee770ee69.uab",
            "mres_xgui_exall_5_e13f209185f8641c0da275b68b638f45.uab",
            "mres_xgui_exall_6_19682ce4c7424954b60fafb274bc0a84.uab",
        ],
        "icons": ["xgui_texture_icon_8d5d52f6017883e1228f39b1eec5d9fc.uab"],
    },
}


@dataclass
class Check:
    game: str | None
    build: str | None = None
    blocked: str | None = None          # why the tool must not run; None = good to go
    tables: bytes | None = field(default=None, repr=False)
    tiles: list = field(default_factory=list)
    icons: list = field(default_factory=list)


# -- finding the game ------------------------------------------------------------------------------------------
def libraries_from_vdf(text):
    """Library folders listed in Steam's steamapps/libraryfolders.vdf."""
    return [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', text)]


def steam_libraries():
    """Every Steam library on this PC, from the registry's Steam path and its libraryfolders.vdf."""
    roots = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            roots.append(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        pass
    roots += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    libs = []
    for r in roots:
        try:
            with open(os.path.join(r, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace") as f:
                libs += libraries_from_vdf(f.read())
        except OSError:
            continue
    seen, out = set(), []
    for p in libs + roots:
        key = os.path.normcase(os.path.normpath(p))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def is_game(folder):
    return bool(folder) and os.path.isfile(os.path.join(folder, BUILD_FILE))


FIND_DEPTH = 3   # how far below a chosen folder to look: Steam's library -> steamapps\common\Aniimo is 3


def find_game_below(folder, depth=FIND_DEPTH):
    """The Aniimo folder at `folder` or up to `depth` levels below it (a launcher's install folder usually holds
    the game a level or two down); None if not there. Kept shallow on purpose: picking a whole drive must not
    turn into a crawl of every folder on it."""
    level = [folder] if folder and os.path.isdir(folder) else []
    for _ in range(depth + 1):
        nxt = []
        for d in level:
            if is_game(d):
                return d
            try:
                nxt += [e.path for e in os.scandir(d) if e.is_dir(follow_symlinks=False)]
            except OSError:
                continue
        level = nxt
    return None


def find_game(explicit=None, libraries=None):
    """The Aniimo folder: the one given (--game), else the first Steam library that has it; None if not found."""
    if explicit:
        return explicit if is_game(explicit) else None
    for lib in steam_libraries() if libraries is None else libraries:
        g = os.path.join(lib, "steamapps", "common", "Aniimo")
        if is_game(g):
            return g
    return None


# -- the check ---------------------------------------------------------------------------------------------------
def read_build(folder):
    with open(os.path.join(folder, BUILD_FILE), encoding="ascii", errors="replace") as f:
        return f.read().split(",")[0].strip().split(".")[-1]


def check(folder, supported=None):
    supported = SUPPORTED if supported is None else supported
    made_for = ", ".join(sorted(supported))
    if not folder:
        return Check(None, blocked="Couldn't find Aniimo in your Steam libraries. If you installed it another way, "
                                   "click Choose the Aniimo folder and pick the folder it is in.")
    build = read_build(folder)
    newer = (f"Check {RELEASES_URL} for a newer version of the tool. It does nothing until then, so it cannot "
             f"show you a wrong map.")
    spec = supported.get(build)
    if spec is None:
        return Check(folder, build, blocked=f"The game is at build {build}, but this version of the tool was made "
                                            f"for build {made_for}. {newer}")
    try:
        with zipfile.ZipFile(os.path.join(folder, LUA_ARCHIVE)) as z:
            tables = z.read(TABLES_IN_ARCHIVE)
    except (OSError, KeyError, zipfile.BadZipFile):
        return Check(folder, build, blocked=f"Couldn't read the game's tables. Verify the game files in Steam. {newer}")
    if hashlib.sha256(tables).hexdigest() != spec["tables_sha256"]:
        return Check(folder, build, blocked=f"The game's tables changed although the build number is still {build}. "
                                            f"{newer}")
    paths = {}
    for kind in ("tiles", "icons"):
        paths[kind] = [os.path.join(folder, BUNDLES, n) for n in spec[kind]]
        missing = [os.path.basename(p) for p in paths[kind] if not os.path.isfile(p)]
        if missing:
            return Check(folder, build, blocked=f"A game file this tool needs is missing ({', '.join(missing)}). "
                                                f"Verify the game files in Steam. {newer}")
    return Check(folder, build, tables=tables, tiles=paths["tiles"], icons=paths["icons"])

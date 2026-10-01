"""Operation: Egg Heist Team Mode maps: which maps each difficulty can roll, where things are, and the game's map art.

    .venv/Scripts/python.exe src/eggheist.py 3629693      # stitch and cache the art of every map (needs UnityPy)

What the game does (build 3603741 and 3629693 identical on all of this, checked 2026-09-30):
- Team Mode is mode 3005. A run's map is one of the scenes in rob_egg_born_data[3005].DungeonList[hardLv]
  (GrabEggSystem.lua:861). hardLv 3 = Normal, 4 = Hard, 5 = Nightmare, 6 = Chaos (dungeon_difficult_level_data).
- The "random" maps are not generated: each of 30 scenes (20031-20060) has a FIXED layout in
  Scene.<id>.scene_room_data (room prefab, position, yaw, type). Room contents come from a shared library,
  Scene.10000.scene_sandbox_data, placed relative to the room (RandomMapBatchUtils.calculateNewPositionV2).
- What IS random per run (RandomMapBatchUtils.filterSandbox): which egg-nest rooms get an egg and where the
  loot chests go. So an "egg" marker here means "an egg can be here at this difficulty", never "is here".
- The map screen shows 64 pre-drawn 256 px tiles per scene (MapRes/Texture/<id>/UI_Img_Map_<id>_<col>_<row>.png,
  row 0 at the top), packed in the mres_xgui_exall_*.uab bundles, not in the xgui_panel_mapres_* ones.
- World -> map pixel: scene_data pairs two map points (MapAPosition/MapBPosition, y counted negative going
  down) with two world points (PointAPositon/PointBPosition, x and z). Linear per axis. Checked pixel-exact
  on 20036 and 20056 by drawing every corridor piece on the art.
"""
import glob
import math
import os
import re
import sys

from pmdata import PmData

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODE = 3005
LIBRARY = 10000   # the scene holding the room library every map instantiates
TEAM_LEVELS = (3, 4, 5, 6)
LEVEL_NAMES = {3: "Normal", 4: "Hard", 5: "Nightmare", 6: "Chaos"}
ROOM_TYPES = {1: "Normal", 2: "Aisle", 3: "Entry", 4: "Entry2", 5: "Reward", 6: "EggNest"}  # RandomMapConst.lua
# key rooms are named per difficulty in the sandbox names; Chaos has no key room of its own in the data,
# its egg nests are the Nightmare ones "migrated" (蛋巢（混沌）迁移), so it uses the Nightmare key room
KEY_ROOM = {3: "普通钥匙房", 4: "困难钥匙房", 5: "噩梦钥匙房", 6: "噩梦钥匙房"}
SPAWN_PORTAL, DOOR_PORTAL = "入口传送门", "地宫传送门"   # map icons Uderground_Front_Door / Uderground_Begin
SANDBOX_EGG_NEST = 4   # sandBoxConfigType of egg nests; sandBoxLevel = hardLv
# map_mark_resource_data ids of the icons the map screen draws (Scene.10000.scene_mark_point_data.markConfigId)
MARK_SPAWN, MARK_DOOR, MARK_EGG = {1009}, {1008}, {1014}   # Uderground_Front_Door, Uderground_Begin, GrabEgg_Lair
MARK_KEY = {1996, 1997, 1998, 1011}                        # blue / purple / gold key room, key door


def _get(table, key):
    return table.get(key, table.get(str(key)))


class Heist:
    def __init__(self, build, pm_source=None, out=None, tile_bundles=None, icon_bundles=None):
        """Defaults (no arguments): the author's local copy of the game data. The public tool passes the table file's bytes
        from the game's own archive, its own cache folder, and the exact bundle files of that build."""
        self.build = build
        if pm_source is None or out is None:
            from extract import paths   # the author's local data folders; the public tool always passes both
            pm_source = pm_source if pm_source is not None else paths(build)[0]
            out = out or os.path.join(paths(build)[2], "eggheist")
        self.pm = PmData(pm_source)
        self.tile_bundles, self.icon_bundles = tile_bundles, icon_bundles
        self.scene = self.pm.module("scene_data")
        self.born = _get(self.pm.module("rob_egg_born_data"), MODE)
        self.sandboxes = self.pm.module(f"Scene.{LIBRARY}.scene_sandbox_data")
        self.out = out
        self._rooms, self._art, self._marks = {}, {}, None

    # -- which maps -------------------------------------------------------------------------------------
    def pool(self, hard_lv):
        """Maps a run at this difficulty can land on, in table order, without the table's repeats."""
        seen = []
        for sid in self.born["DungeonList"][hard_lv - 1]:
            if sid not in seen:
                seen.append(sid)
        return seen

    def team_maps(self):
        return sorted({sid for lv in TEAM_LEVELS for sid in self.pool(lv)})

    def all_maps(self):
        return sorted(int(k) for k in self.scene if 20031 <= int(k) <= 20060)

    def levels_of(self, sid):
        return [lv for lv in TEAM_LEVELS if sid in self.pool(lv)]

    # -- layout -----------------------------------------------------------------------------------------
    def rooms(self, sid):
        if sid not in self._rooms:
            r = self.pm.module(f"Scene.{sid}.scene_room_data")
            self._rooms[sid] = list(r.values()) if isinstance(r, dict) else r
        return self._rooms[sid]

    def world_to_art(self, sid, wx, wz):
        s = _get(self.scene, sid)
        (ax, ay), (bx, by) = s["MapAPosition"], s["MapBPosition"]
        (pax, paz), (pbx, pbz) = s["PointAPositon"], s["PointBPosition"]
        kx, ky = (bx - ax) / (pbx - pax), (by - ay) / (pbz - paz)
        return ax + (wx - pax) * kx, -(ay + (wz - paz) * ky)

    def art_scale(self, sid):
        """Map-art pixels per world unit. Differs per map (20036 6.7, 20056 12.1): each map fills 2048 px."""
        s = _get(self.scene, sid)
        return (s["MapBPosition"][0] - s["MapAPosition"][0]) / (s["PointBPosition"][0] - s["PointAPositon"][0])

    def spawn_room_art(self, sid):
        """Centre of the spawn room in art px. The screenshot matcher anchors on the ROOM, which is the same
        piece on every map; the spawn icon sits ~0.6 units off its centre, enough to skew the fitted scale."""
        entry = next(r for r in self.rooms(sid) if r["roomType"] == 3)
        return self.world_to_art(sid, entry["position"][0], entry["position"][2])

    def _marks_of(self, sb_id):
        """The map marks a library sandbox carries: (markConfigId, room-local position)."""
        if self._marks is None:
            self._marks = {}
            for p in self.pm.module(f"Scene.{LIBRARY}.scene_mark_point_data").values():
                self._marks.setdefault(int(p.get("sandboxId") or 0), []).append((p["markConfigId"], p["markPosition"]))
        return self._marks.get(int(sb_id), [])

    def _at_mark(self, sb_id, kinds, fallback):
        """Where the game draws this sandbox's icon of one of `kinds`; the sandbox origin if it has none.
        The key-room marks sit up to ~20 units from their sandbox origin (a real run's key icon was 89 px
        off before this), portals and nests within ~2."""
        for cid, pos in self._marks_of(sb_id):
            if cid in kinds:
                return pos
        return fallback

    def markers(self, sid, hard_lv):
        """Everything worth pointing at, for one difficulty: spawn, door, egg (possible), key, reward, unique."""
        out = []
        for room in self.rooms(sid):
            found = []
            for sb_id in room.get("sandboxIds", []):
                sb = _get(self.sandboxes, sb_id) or {}
                name, pos = sb.get("name", ""), sb.get("position", [0, 0, 0])
                if SPAWN_PORTAL in name:
                    found.append(("spawn", self._at_mark(sb_id, MARK_SPAWN, pos)))
                elif DOOR_PORTAL in name:
                    found.append(("door", self._at_mark(sb_id, MARK_DOOR, pos)))
                elif sb.get("sandBoxConfigType") == SANDBOX_EGG_NEST and sb.get("sandBoxLevel") == hard_lv:
                    if not any(k == "egg" for k, _ in found):   # one nest per room per difficulty
                        found.append(("egg", self._at_mark(sb_id, MARK_EGG, pos)))
                elif KEY_ROOM[hard_lv] in name:
                    found.append(("key", self._at_mark(sb_id, MARK_KEY, pos)))
            if room["roomType"] == 5:
                found.append(("reward", [0, 0, 0]))
            if "Uniq" in room["resId"]:
                found.append(("unique", [0, 0, 0]))
            for kind, pos in found:
                wx, wz = self._room_to_world(room, pos)
                out.append({"kind": kind, "world": (wx, wz), "art": self.world_to_art(sid, wx, wz),
                            "room": room["id"], "prefab": room["resId"][1:-7]})
        return out

    @staticmethod
    def _room_to_world(room, local):
        # same rotation as RandomMapBatchUtils.calculateNewPositionV2
        a = math.radians(room.get("yaw", 0))
        x, z = local[0], local[2]
        return (x * math.cos(a) + z * math.sin(a) + room["position"][0],
                -x * math.sin(a) + z * math.cos(a) + room["position"][2])

    # -- art --------------------------------------------------------------------------------------------
    def art_path(self, sid):
        return os.path.join(self.out, "maps", f"{sid}.png")

    def art(self, sid):
        """The map screen's own drawing of this scene, 2048x2048 RGBA (transparent where nothing is drawn)."""
        from PIL import Image
        if sid not in self._art:
            if not os.path.exists(self.art_path(sid)):
                self.stitch_all()
            self._art[sid] = Image.open(self.art_path(sid)).convert("RGBA")
        return self._art[sid]

    def stitch_all(self):
        import UnityPy
        from PIL import Image
        bundles = self.tile_bundles or glob.glob(os.path.join(ROOT, "builds", self.build, "raw", "uab", "mres_xgui_exall_*.uab"))
        if not bundles:
            sys.exit(f"no mres_xgui_exall_*.uab in builds/{self.build}/raw/uab: copy them from the game first")
        tiles = {}
        pat = re.compile(r"/MapRes/Texture/(\d+)/UI_Img_Map_\1_(\d+)_(\d+)\.png$")
        for f in bundles:
            for path, obj in UnityPy.load(f).container.items():
                m = pat.search(path)
                if m and obj.type.name == "Texture2D":
                    tiles.setdefault(int(m.group(1)), {})[(int(m.group(2)), int(m.group(3)))] = obj.read().image
        os.makedirs(os.path.join(self.out, "maps"), exist_ok=True)
        for sid in self.all_maps():
            canvas = Image.new("RGBA", (2048, 2048), (0, 0, 0, 0))
            for (col, row), im in tiles.get(sid, {}).items():
                canvas.paste(im.convert("RGBA"), (col * 256, row * 256))
            canvas.save(self.art_path(sid))
        return len(tiles)


    def extract_icons(self):
        """The map screen's own icons for spawn, door, keys and egg nests (xgui_texture_icon_*.uab)."""
        import UnityPy
        pat = re.compile(r"/Map_MarkPoint/(Img_Map_Mark_(?:Uderground_\w+|GrabEgg_Lair))\.png$")
        os.makedirs(os.path.join(self.out, "icons"), exist_ok=True)
        saved = []
        for f in self.icon_bundles or glob.glob(os.path.join(ROOT, "builds", self.build, "raw", "uab", "xgui_texture_icon_*.uab")):
            for path, obj in UnityPy.load(f).container.items():
                m = pat.search(path)
                if m and obj.type.name == "Texture2D":
                    obj.read().image.save(os.path.join(self.out, "icons", m.group(1) + ".png"))
                    saved.append(m.group(1))
        return sorted(set(saved))


def load(build):
    return Heist(build)


if __name__ == "__main__":
    h = load(sys.argv[1] if len(sys.argv) > 1 else "3629693")
    print(f"stitched {h.stitch_all()} maps -> {os.path.join(h.out, 'maps')}")
    print(f"icons: {', '.join(h.extract_icons())}")

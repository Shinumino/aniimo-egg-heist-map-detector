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
- Second floors (2026-10-10): every room of a layout is on one level. Certain room pieces have an upper level,
  marked by a box in Scene.10000.scene_area_data that starts 3.5 to 12 above the room's floor and switches the
  map screen to a second picture of the same scene (the same bundles, MapRes/Texture/<id>_1/2/...): the ground
  floor dimmed, each upper floor drawn in place over its room. Nothing the map marks is on an upper floor.
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
SPAWN_PORTAL, DOOR_PORTAL = "入口传送门", "地宫传送门"   # map icons Uderground_Front_Door / Uderground_Begin
SANDBOX_EGG_NEST = 4   # sandBoxConfigType of egg nests; sandBoxLevel = hardLv
# map_mark_resource_data ids of the icons the map screen draws (Scene.10000.scene_mark_point_data.markConfigId)
MARK_SPAWN, MARK_DOOR, MARK_EGG = {1009}, {1008}, {1014}   # Uderground_Front_Door, Uderground_Begin, GrabEgg_Lair
MARK_KEY = {1996, 1997, 1998, 1011}                        # blue / purple / gold key room, key door
# A locked room is marked wherever the game draws one of those icons, not by the piece's name. Matching names
# (钥匙房, key room, per difficulty) missed the key DOORS (困难/噩梦钥匙门) of room 40_005_Key on Hard and
# Nightmare: six maps showed nothing on a locked room (a player's report, 2026-10-15). In build 3732728 exactly
# nine library pieces carry a key icon, and each of the 31 locked rooms on the team maps lists exactly one.
# Second floors. What an Egg Heist room tells the map screen when you go upstairs (changeMapLayerData's
# arguments), which is also the address of the picture shown then:
# MapRes/Texture/<id>_1/2/UI_Img_Map_Layer_<id>_1_2_0_<col>_<row>.png
UPPER_LAYER = (1, 2, 0)
# In that picture the ground floor is dimmed and the upper floors are not. Measured on four maps (2026-10-10):
# 82% of the drawn pixels are darker than 40, 10% are the 40-80 backdrop of a two-floor room, 6% are upper floor
# at 170-200, and under 1% fall in 80-110.
UPPER_BRIGHT = 110
UPPER_DRAWN = 0.005    # share of a room's box that must be upper floor: the smallest real one (30_006) has 0.021
# How far below the start of a room's upper box something can be and still stand on the upper floor (the box may
# start above the floor boards). Things on a ground floor sit within 0.5 of it, and the lowest box starts 3.5 up.
FLOOR_MARGIN = 1.0


def _get(table, key):
    return table.get(key, table.get(str(key)))


def floor_of(height, starts):
    """1 for the ground floor, 2 for upstairs: `height` above the room's floor, against the heights where the
    room's upper boxes start (none = the room has one floor)."""
    return 2 if any(height >= s - FLOOR_MARGIN for s in starts) else 1


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
        self._rooms, self._art, self._marks, self._spawners = {}, {}, None, None
        self._boxes, self._upstairs = None, {}

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
        return [(cid, pos) for _, cid, pos in self._mark_rows(sb_id)]

    def _mark_rows(self, sb_id):
        """The same, each with the mark's id first, which is the id of the thing it marks (an entity a spawner
        can place)."""
        if self._marks is None:
            self._marks = {}
            for k, p in self.pm.module(f"Scene.{LIBRARY}.scene_mark_point_data").items():
                self._marks.setdefault(int(p.get("sandboxId") or 0), []).append(
                    (int(k), p["markConfigId"], p["markPosition"]))
        return self._marks.get(int(sb_id), [])

    def _nest_chance(self, sb_id):
        """A locked room's own egg nest: (where, the share of runs it is there), or None if it has none.
        The room's spawner places one of its weighted variants each run (spawnGroups, by weight); the nest is
        the entity carrying the egg icon, so its share is the weight of the variants that hold it over all of
        them. Build 3732728: every key piece has one, 16% to 50%, in the same spot in each variant that has it."""
        nests = {mid: pos for mid, cid, pos in self._mark_rows(sb_id) if cid in MARK_EGG}
        if not nests:
            return None
        if self._spawners is None:
            self._spawners = self.pm.module(f"Scene.{LIBRARY}.scene_spawner_data")
        for sp_id in (_get(self.sandboxes, sb_id) or {}).get("spawners") or []:
            groups = (_get(self._spawners, sp_id) or {}).get("spawnGroups") or []
            hit = [g for g in groups if isinstance(g["spawnIds"], list) and nests.keys() & set(g["spawnIds"])]
            total = sum(g["weight"] for g in groups)
            if hit and total:
                where = nests[next(i for i in hit[0]["spawnIds"] if i in nests)]
                return where, sum(g["weight"] for g in hit) / total
        return None

    def _mark_of(self, sb_id, kinds):
        """Where the game draws this sandbox's icon of one of `kinds`; None if it has none."""
        for cid, pos in self._marks_of(sb_id):
            if cid in kinds:
                return pos
        return None

    def _at_mark(self, sb_id, kinds, fallback):
        """Where the game draws this sandbox's icon of one of `kinds`; the sandbox origin if it has none.
        The key-room marks sit up to ~20 units from their sandbox origin (a real run's key icon was 89 px
        off before this), portals and nests within ~2."""
        pos = self._mark_of(sb_id, kinds)
        return fallback if pos is None else pos

    def markers(self, sid, hard_lv):
        """Everything worth pointing at, for one difficulty: spawn, door, egg (possible), key, reward, unique.
        Each says which floor it is on: 1, or 2 when it stands on the room's upper floor. An egg's `chance` is
        None in a nest room (the game picks which nest rooms get an egg, odds unknown) and the share of runs
        its nest is there for a locked room's own nest (_nest_chance)."""
        out = []
        boxes = self._layer_boxes()
        for room in self.rooms(sid):
            starts = [boxes[int(i)][1] for i in room.get("sandboxIds", []) if int(i) in boxes]
            found = []     # (kind, room-local position, chance)
            for sb_id in room.get("sandboxIds", []):
                sb = _get(self.sandboxes, sb_id) or {}
                name, pos = sb.get("name", ""), sb.get("position", [0, 0, 0])
                if SPAWN_PORTAL in name:
                    found.append(("spawn", self._at_mark(sb_id, MARK_SPAWN, pos), None))
                elif DOOR_PORTAL in name:
                    found.append(("door", self._at_mark(sb_id, MARK_DOOR, pos), None))
                elif sb.get("sandBoxConfigType") == SANDBOX_EGG_NEST and sb.get("sandBoxLevel") == hard_lv:
                    if not any(k == "egg" for k, _, _ in found):   # one nest per room per difficulty
                        found.append(("egg", self._at_mark(sb_id, MARK_EGG, pos), None))
                elif (key := self._mark_of(sb_id, MARK_KEY)) is not None:
                    found.append(("key", key, None))
                    if (nest := self._nest_chance(sb_id)) is not None:
                        found.append(("egg", *nest))
            if room["roomType"] == 5:
                found.append(("reward", [0, 0, 0], None))
            if "Uniq" in room["resId"]:
                found.append(("unique", [0, 0, 0], None))
            for kind, pos, chance in found:
                wx, wz = self._room_to_world(room, pos)
                out.append({"kind": kind, "world": (wx, wz), "art": self.world_to_art(sid, wx, wz),
                            "room": room["id"], "prefab": room["resId"][1:-7], "floor": floor_of(pos[1], starts),
                            "chance": chance})
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
        tiles, upper = {}, {}
        pat = re.compile(r"/MapRes/Texture/(\d+)/UI_Img_Map_\1_(\d+)_(\d+)\.png$")
        a, b, c = UPPER_LAYER
        up = re.compile(rf"/MapRes/Texture/(\d+)_{a}/{b}/UI_Img_Map_Layer_\1_{a}_{b}_{c}_(\d+)_(\d+)\.png$")
        for f in bundles:
            for path, obj in UnityPy.load(f).container.items():
                for rx, into in ((pat, tiles), (up, upper)):
                    m = rx.search(path)
                    if m and obj.type.name == "Texture2D":
                        into.setdefault(int(m.group(1)), {})[(int(m.group(2)), int(m.group(3)))] = obj.read().image
        os.makedirs(os.path.join(self.out, "maps"), exist_ok=True)
        for sid in self.all_maps():
            for found, path in ((tiles, self.art_path(sid)), (upper, self.upper_art_path(sid))):
                canvas = Image.new("RGBA", (2048, 2048), (0, 0, 0, 0))
                for (col, row), im in found.get(sid, {}).items():
                    canvas.paste(im.convert("RGBA"), (col * 256, row * 256))
                canvas.save(path)
        return len(tiles)

    # -- second floors ----------------------------------------------------------------------------------
    # In the layouts every room is on one level. A second floor is the upper part of certain room pieces, and
    # each sits directly over its own room: corridor pieces have none, so two second floors never join.
    def _layer_boxes(self):
        """Library sandbox id -> ((min x, min z, max x, max z) in the room's own coordinates, the height above
        the room's floor where it starts): the boxes that tell the map screen which layer to show
        (Scene.10000.scene_area_data, event changeMapLayerData)."""
        if self._boxes is None:
            self._boxes = {}
            areas = self.pm.module(f"Scene.{LIBRARY}.scene_area_data")
            for a in areas.values() if isinstance(areas, dict) else areas:
                events = [e for lg in a.get("logics") or [] for e in lg.get("enterEvents") or []]
                if any(e[0] == "changeMapLayerData" for e in events):
                    self._boxes[int(a["sandboxId"])] = (tuple(a["areaAABB"]), a["position"][1])
        return self._boxes

    def upper_art_path(self, sid):
        return os.path.join(self.out, "maps", f"{sid}-upper.png")

    def upper_art(self, sid):
        """The game's own picture of this scene's upper floors, 2048x2048 RGBA: the ground floor dimmed, every
        second floor drawn in place over its room (what the map screen shows while you are upstairs).
        Read from disk each time: 21 of these held in memory would be 350 MB."""
        from PIL import Image
        if not os.path.exists(self.upper_art_path(sid)):   # a cache made before this picture was read
            self.stitch_all()
        return Image.open(self.upper_art_path(sid)).convert("RGBA")

    def upper_floor_mask(self, sid):
        """Where that picture draws an upper floor: a 2048x2048 array of True / False."""
        import numpy as np
        up = self.upper_art(sid)
        return (np.asarray(up.convert("L")) > UPPER_BRIGHT) & (np.asarray(up.getchannel("A")) > 0)

    def upstairs(self, sid):
        """The rooms of this map that have a second floor, in room order:
        [{"room": id, "rect": (left, top, right, bottom) in art px, "start": height where the upper box begins}].
        Only rooms where the game's own picture draws an upper floor. The small 20_003 piece carries a box too,
        but nothing is drawn in it on any map (2026-10-10), so there would be nothing to show for it; whether
        it has an upstairs in the game is an open question."""
        if sid not in self._upstairs:
            drawn, out = self.upper_floor_mask(sid), []
            for room in self.rooms(sid):
                for sb_id in room.get("sandboxIds", []):
                    box = self._layer_boxes().get(int(sb_id))
                    if not box:
                        continue
                    (x0, z0, x1, z1), start = box
                    pts = [self.world_to_art(sid, *self._room_to_world(room, [x, 0, z])) for x in (x0, x1) for z in (z0, z1)]
                    left, top = max(0, round(min(p[0] for p in pts))), max(0, round(min(p[1] for p in pts)))
                    right, bottom = min(2048, round(max(p[0] for p in pts))), min(2048, round(max(p[1] for p in pts)))
                    if right > left and bottom > top and drawn[top:bottom, left:right].mean() > UPPER_DRAWN:
                        out.append({"room": room["id"], "rect": (left, top, right, bottom), "start": start})
                        break
            self._upstairs[sid] = out
        return self._upstairs[sid]


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

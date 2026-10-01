"""Which Egg Heist map is this? Match a screenshot of the in-game map screen (M) against the game's own map art.

    .venv/Scripts/python.exe src/eggheist_match.py 3629693 "path/to/screenshot.png" [hard_lv]

How it decides, and why this way:
- The explored part of the map screen IS a piece of one map's art (src/eggheist.py), only scaled and
  shifted; the map screen never rotates. So a candidate is (map, scale, shift), scored by how well that
  map's art, placed that way, agrees with the explored pixels of the screenshot.
- Scale and shift come from the SPAWN ROOM, which is on screen from the first second of a run. It is the
  same room piece (Level_Room_30_001) on every map, so one search over zoom levels finds where it is and
  how many screen pixels one world unit takes; every map is then placed from its own spawn point.
  First tried: finding the spawn ICON instead. It failed on 2 of 4 real screenshots: the player arrow and
  the "1P" badge sit on top of it at the start, and its white glyph also matches the door icon. Tried again
  as an extra guess for explored maps (2026-10-01): once visited the game draws it differently (0.40 at
  the true spot), so it is gone again.
- At the start only the spawn room is explored, and it looks the same on every map, so the art cannot
  tell the maps apart yet. The door icon can: the game draws it through the fog from the start. Each map
  says where its door is, so each map is checked for a door icon at ITS spot. A wrong map points at fog.
  (A global "find the door icon" search found the wrong spot on the fully explored Nightmare screenshot.)
- Icons are the game's own images (builds/<build>/out/eggheist/icons, from the xgui_texture_icon bundle),
  not crops of a screenshot, so another screen resolution still works.
- Two maps can be indistinguishable from the start screen: 20060 (Normal) and 20032 (Nightmare) both have
  the door 90 units east of spawn. Knowing the difficulty settles it (`match(img, maps=heist.pool(lv))`);
  without it the answer is `Result.shortlist`, never a confident pick.

Cost (2026-10-01, so it also runs on weaker PCs): it was 5.5 s and ~800 MB per process. Most of it went to
redrawing 2048 px maps 756 times and checking the door icon at 14 sizes for every try. Now: maps kept
as 8-bit at the resolution the screen needs, only the explored part of the screen is compared, the door
icon is looked up in one door map per screenshot at the one icon size, the spawn room is searched on a
half-size copy and refined, and only the best few maps get the fine scale search. tests/test_eggheist.py CostTest holds the budgets.
"""
import math
import os
import sys
from dataclasses import dataclass, field

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = 1400            # long side of the working copy of a screenshot, px; 4K captures are 3840
# Maps are kept at ART_UNIT_PX art px per world unit (the 2048 px art has 6.7-12.1 depending on the map).
# A fixed half size was tried: fine for 20056 (12.1 -> 6), but 20036 (6.7 -> 3.4) then had to be blown up
# 1.45x to meet the screenshot, the comparison fell from 0.78 to 0.42 and a wrong map won Nightmare full.
ART_UNIT_PX = 6.5
DOOR_ICON = "Img_Map_Mark_Uderground_Begin.png"
# map icon sizes tried, px at WORK. The game scales its UI with the screen, so a full-screen capture puts the
# icons at ~60 px whatever the resolution; a snip cropped smaller only makes them bigger. All 10 real
# screenshots measured 58-62. Starting at 16 let tiny templates "win" on floor texture: the size estimate
# came out 16 on the Nightmare screenshot and the door and spawn icon checks were done at the wrong size.
DOOR_SIZES = range(44, 76, 4)
# how far from its predicted spot the door icon may be, px at WORK. 5 was too tight once only the best maps
# get the fine scale search: on the Nightmare start the door is 5.6 room widths out and a 2.5% scale error
# put it 15 px off (score 0.24 instead of ~0.95), so 20036 lost to a map whose door spot hit something
DOOR_REACH = 18
EXPLORED_MIN_PX, EXPLORED_MIN_SHARE = 300, 0.03   # explored pieces smaller than this are UI specks
SPAWN_REF_MAP = 20056  # any map works (same room piece); this one has the most art pixels per unit
SPAWN_HALF = 16        # world units around the spawn point used to find the spawn room (the room is ~26 wide)
UNIT_PX = (4.0, 24.0)  # plausible screen px per world unit, original resolution: 10 real screenshots measured
                       # 8-15; this leaves room for zooming the map in or out (3-30 cost 25% more time)
DOOR_WEIGHT = 1.0      # how much the door icon counts next to the art agreement
SPAWN_GUESSES = 10     # the door room (30_002) and others look like the spawn room: on a fully explored
                       # map the real one ranked 7th in the coarse search, so keep this many guesses
REFINE_MAPS = 4        # maps that get the fine scale search after the first pass
SPAWN_SIZES = 40       # spawn room sizes tried on the half-size copy. 24 was tried: on the fully explored
                       # Nightmare screenshot the real spawn room then fell out of the guesses
MARGIN = 0.08          # best score must beat the runner-up by this much to be called confident
SHORTLIST_GAP = 0.2    # maps within this of the best are "could also be"
DOOR_EVIDENCE, ART_EVIDENCE = 0.8, 0.4   # see Result.looks_like_map
ART_MATCH = 0.8        # see Result.has_evidence
ART_ONLY_LEAD = 0.2    # see Result.looks_like_map: without the door, the best map must lead by this much


@dataclass
class Candidate:
    map_id: int
    hard_lv: int | None
    scale: float          # screenshot px per FULL-SIZE (2048) art px, original screenshot resolution
    shift: tuple          # screenshot px of art (0, 0)
    score: float
    detail: dict = field(default_factory=dict)

    def to_screen(self, art_xy):
        return (art_xy[0] * self.scale + self.shift[0], art_xy[1] * self.scale + self.shift[1])


@dataclass
class Result:
    candidates: list
    icons: dict

    @property
    def best(self):
        return self.candidates[0]

    @property
    def confident(self):
        if len(self.candidates) < 2:
            return bool(self.candidates) and self.candidates[0].score > 0
        return self.candidates[0].score - self.candidates[1].score >= MARGIN

    @property
    def looks_like_map(self):
        """Sure AND with real evidence: the door icon clearly at its spot, or the art clearly agreeing. On the
        real screenshots the right map had door >= 0.95 or art >= 0.45; wrong maps stayed below 0.7 / 0.35.
        A screen that is not the map (M closes it too) can still be "confident" between equally bad guesses."""
        if not (self.confident and self.has_evidence):
            return False
        if (self.best.detail.get("door") or 0) >= DOOR_EVIDENCE:
            return True
        # art alone (the door hidden, e.g. under the player arrow): it must also clearly beat the next map
        return self.candidates[0].score - self.candidates[1].score >= ART_ONLY_LEAD if len(self.candidates) > 1 else True

    @property
    def has_evidence(self):
        """This IS a map screen, whichever map: the best guess has a clear door icon, or art that both covers
        the explored part and matches it closely. A tie between two maps (20060 / 20032 at the start) has
        evidence without being confident.
        The game world can pass for explored map art: the stone hall at the exit, captured when M CLOSED the
        map, scored art 0.61-0.66 (above ART_EVIDENCE) and switched a right map to a wrong one (2026-10-01).
        It matched loosely (ncc 0.71-0.76, the real hidden-door maps 0.84-0.93), hence ART_MATCH."""
        d = self.best.detail if self.candidates else {}
        if (d.get("door") or 0) >= DOOR_EVIDENCE:
            return True
        return d.get("art", 0) >= ART_EVIDENCE and d.get("ncc", 0) >= ART_MATCH

    @property
    def shortlist(self):
        """Maps it could be, best first: the confident pick alone, or everything close to the best."""
        if not self.candidates or self.best.score <= 0:
            return []
        if self.looks_like_map:
            return [self.best.map_id]
        return [c.map_id for c in self.candidates if c.score >= self.best.score - SHORTLIST_GAP][:4]


class Matcher:
    def __init__(self, heist, maps=None):
        self.h = heist
        self.maps = list(maps or heist.team_maps())
        self.door = self._icon_sizes(DOOR_ICON)          # size -> (template, mask), made once
        self._icon_px = {}                                # screenshot shape -> icon size, see icon_size()
        self.art, self.keep = {}, {}
        for sid in set(self.maps) | {SPAWN_REF_MAP}:
            rgba = np.array(heist.art(sid))
            heist._art.pop(sid, None)                    # the full-size PIL copy is not needed any more
            half = self.keep[sid] = min(1.0, ART_UNIT_PX / heist.art_scale(sid))
            size = int(round(2048 * half))
            rgba = cv2.resize(rgba, (size, size), interpolation=cv2.INTER_AREA)
            # one 8-bit picture per map, 0 = nothing drawn there (drawn pixels are bumped to >= 1): a separate
            # alpha layer of the same size was half of the memory
            gray = np.maximum(cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2GRAY), 1)
            gray[rgba[:, :, 3] <= 128] = 0
            lv = heist.levels_of(sid)
            pos = {m["kind"]: (m["art"][0] * half, m["art"][1] * half)
                   for m in heist.markers(sid, lv[0] if lv else 5) if m["kind"] in ("spawn", "door")}
            ax, ay = heist.spawn_room_art(sid)
            pos["anchor"] = (ax * half, ay * half)
            self.art[sid] = (gray, None, pos, heist.art_scale(sid) * half)
        gray, alpha, pos, k = self.art[SPAWN_REF_MAP]
        x, y, r = pos["anchor"][0], pos["anchor"][1], SPAWN_HALF * k
        box = (int(y - r), int(y + r), int(x - r), int(x + r))
        patch = gray[box[0]:box[1], box[2]:box[3]]
        self.spawn_patch = (patch.astype(np.float32), (patch > 0).astype(np.uint8), k)
        if SPAWN_REF_MAP not in self.maps:
            del self.art[SPAWN_REF_MAP]

    def _icon_sizes(self, name):
        icon = cv2.imread(os.path.join(self.h.out, "icons", name), cv2.IMREAD_UNCHANGED)
        if icon is None:
            sys.exit(f"missing {name} in {os.path.join(self.h.out, 'icons')}: run src/eggheist.py <build> first")
        out = {}
        for size in DOOR_SIZES:
            t = cv2.resize(icon[:, :, :3], (size, size), interpolation=cv2.INTER_AREA)
            m = (cv2.resize(icon[:, :, 3], (size, size), interpolation=cv2.INTER_AREA) > 160).astype(np.uint8)
            out[size] = (t, m)
        return out

    def held_bytes(self):
        n = sum(g.nbytes for g, _, _, _ in self.art.values())
        return n + sum(t.nbytes + m.nbytes for t, m in self.door.values()) + self.spawn_patch[0].nbytes

    # -- explored pixels --------------------------------------------------------------------------------
    @staticmethod
    def explored_mask(small):
        """Pixels that look like map art: the fog is blue-grey, icons and the player arrow are saturated.
        Thin things (the "Map" title, the FPS overlay, the zoom slider) are opened away: they are not map,
        and they would stretch the explored area's box over the whole screen."""
        b, _, r = [c.astype(np.int16) for c in cv2.split(small)]
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        fog = (b - r) > 10
        loud = hsv[:, :, 1] > 90
        blank = small.max(axis=2) < 10                  # blacked-out party list, letterbox
        m = (~fog & ~loud & ~blank).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        # loose specks (the zoom slider's dot, a strip at the screen edge) survive the opening and would still
        # stretch the box over the whole screen: keep only pieces of a real size next to the biggest one
        n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        if n > 1:
            areas = stats[1:, cv2.CC_STAT_AREA]
            keep = np.zeros(n, bool)
            keep[1:] = areas >= max(EXPLORED_MIN_PX, EXPLORED_MIN_SHARE * areas.max())
            m = keep[labels]
        return m.astype(bool)

    # -- spawn room -------------------------------------------------------------------------------------
    def _match_patch(self, img, size):
        pg, pa, _ = self.spawn_patch
        t = cv2.resize(pg, (size, size), interpolation=cv2.INTER_AREA)
        m = cv2.resize(pa, (size, size), interpolation=cv2.INTER_NEAREST)
        r = cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED, mask=m)
        r[~np.isfinite(r)] = -1
        return r

    def find_spawn(self, small_gray, f, top=SPAWN_GUESSES):
        """Up to `top` (score, x, y, px_per_unit) guesses for the spawn room centre, in small px, best first.
        Searched on a half-size copy over all sizes, then each guess refined at full size close by."""
        coarse = cv2.resize(small_gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        hits = []
        for u in np.geomspace(UNIT_PX[0] * f, UNIT_PX[1] * f, SPAWN_SIZES):   # small px per world unit
            size = int(round(SPAWN_HALF * u))                          # the patch is 2*SPAWN_HALF*u, halved
            if size < 8 or size >= min(coarse.shape):
                continue
            r = self._match_patch(coarse, size)
            for _ in range(top):
                _, v, _, loc = cv2.minMaxLoc(r)
                hits.append((v, (loc[0] + size / 2) * 2, (loc[1] + size / 2) * 2, u))
                cv2.rectangle(r, (loc[0] - size // 2, loc[1] - size // 2), (loc[0] + size // 2, loc[1] + size // 2), -1, -1)
        hits.sort(reverse=True)
        picked = []
        for v, x, y, u in hits:                                         # distinct places only
            if all(math.dist((x, y), (px, py)) > 10 * u for _, px, py, _ in picked):
                picked.append((v, x, y, u))
            if len(picked) == top:
                break
        return [self._refine_spawn(small_gray, *p) for p in picked]

    def _refine_spawn(self, small_gray, v, x, y, u):
        """The coarse guess at full size: a small window around it, three sizes around its scale."""
        best = None
        h, w = small_gray.shape
        for uu in (u * 0.95, u, u * 1.05):
            size = int(round(2 * SPAWN_HALF * uu))
            pad = size // 2 + 6
            x0, y0 = max(0, int(x) - pad), max(0, int(y) - pad)
            x1, y1 = min(w, int(x) + pad), min(h, int(y) + pad)
            if x1 - x0 <= size or y1 - y0 <= size:
                continue
            r = self._match_patch(small_gray[y0:y1, x0:x1], size)
            _, vv, _, loc = cv2.minMaxLoc(r)
            if best is None or vv > best[0]:
                best = (vv, x0 + loc[0] + size / 2, y0 + loc[1] + size / 2, uu)
        return best or (v, x, y, u)

    # -- scoring ----------------------------------------------------------------------------------------
    def art_score(self, sid, s, t, gray_roi, explored_roi, origin):
        """Agreement of map `sid`'s art placed at scale s / shift t with the explored pixels, compared only
        inside the explored area's box (`origin` = its top-left in small px)."""
        gray = self.art[sid][0]
        h, w = gray_roi.shape
        M = np.float32([[s, 0, t[0] - origin[0]], [0, s, t[1] - origin[1]]])
        a = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        am = a > 0                                      # 0 = no art there (see __init__)
        both = explored_roi & am
        n_e, n_b = int(explored_roi.sum()), int(both.sum())
        if n_b < 200 or n_e == 0:
            return -1.0, 0.0, 0.0
        x, y = a[both].astype(np.float32), gray_roi[both]
        x, y = x - x.mean(), y - y.mean()
        ncc = float((x * y).sum() / (math.sqrt(float((x * x).sum() * (y * y).sum())) + 1e-6))
        coverage = n_b / n_e                            # explored pixels this map has art under
        return ncc * coverage, ncc, coverage

    def icon_size(self, small):
        """Size the map screen draws its icons at in this screenshot, px at WORK. Every map icon (spawn, door,
        keys, nests) has the same size, so the best door-like match anywhere tells it, even when the door
        itself is hidden under the player arrow. It only depends on the screen, so it is remembered per
        screenshot size (every M-key capture has the same one): it was a quarter of each match's time.
        Remembered only after a match that was sure (Result.looks_like_map, see match): learning it from whatever came
        first let a game-world capture (M pressed to close the map) teach a wrong size, and the next real
        start screen scored its door 0.45 instead of 0.96 (2026-10-01, caught by the log)."""
        if small.shape in self._icon_px:
            return self._icon_px[small.shape]
        return self._find_icon_size(small)

    def _find_icon_size(self, small):
        half = cv2.resize(small, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        best = (-2.0, None)
        for size in self.door:
            s2 = size // 2
            if s2 >= min(half.shape[:2]):
                continue
            t, m = self.door[size]
            r = cv2.matchTemplate(half, cv2.resize(t, (s2, s2), interpolation=cv2.INTER_AREA),
                                  cv2.TM_CCOEFF_NORMED, mask=cv2.resize(m, (s2, s2), interpolation=cv2.INTER_NEAREST))
            r[~np.isfinite(r)] = -1
            best = max(best, (float(r.max()), size))
        return best[1]

    def door_map(self, small, size):
        """For every spot of the screenshot, how much it looks like the door icon: about 0 for fog, 0.6-0.98
        for the icon. Made once per screenshot at full size, at the one icon size icon_size() found.
        Tried and dropped: checking each map's door spot separately with all 14 sizes (2.3 of 3 s), and the
        map at half size (fast, but floor texture then scored 0.8-0.93 and a wrong map won Nightmare full).
        TM_CCORR_NORMED was tried first of all: plain fog 0.93 against 0.99 for the icon, no contrast."""
        out = np.full(small.shape[:2], -1, np.float32)
        for s in (size,) if size else self.door:
            if s not in self.door or s >= min(small.shape[:2]):
                continue
            t, m = self.door[s]
            r = cv2.matchTemplate(small, t, cv2.TM_CCOEFF_NORMED, mask=m)
            r[~np.isfinite(r)] = -1
            o = s // 2                                  # result index = template top-left; store at its centre
            region = out[o:o + r.shape[0], o:o + r.shape[1]]
            np.maximum(region, r[:region.shape[0], :region.shape[1]], out=region)
        return out

    @staticmethod
    def door_score(door_map, xy):
        """The best door likeness within DOOR_REACH of `xy` (small px); None if that spot is off screen."""
        h, w = door_map.shape
        x, y = xy
        if not (0 <= x < w and 0 <= y < h):
            return None
        r = DOOR_REACH
        win = door_map[max(0, int(y) - r):int(y) + r + 1, max(0, int(x) - r):int(x) + r + 1]
        return float(win.max()) if win.size else None

    def _try(self, sid, guess, du, ctx):
        door_map, gray_roi, explored_roi, origin = ctx
        _, _, pos, k = self.art[sid]
        v, x, y, u = guess
        s = u * du / k                                  # small px per (stored-size) art px
        t = (x - s * pos["anchor"][0], y - s * pos["anchor"][1])
        art, ncc, cov = self.art_score(sid, s, t, gray_roi, explored_roi, origin)
        door = self.door_score(door_map, (pos["door"][0] * s + t[0], pos["door"][1] * s + t[1]))
        total = art + DOOR_WEIGHT * (door if door is not None else 0.0)
        return total, s, t, {"art": round(art, 3), "ncc": round(ncc, 3), "coverage": round(cov, 3),
                             "door": None if door is None else round(door, 3), "spawn_fit": round(v, 3)}

    # -- the match --------------------------------------------------------------------------------------
    def match(self, img, maps=None):
        """Rank the maps for this screenshot. `maps`: only these (e.g. heist.pool(hard_lv)), default all."""
        maps = [m for m in (maps or self.maps) if m in self.art]
        f = WORK / max(img.shape[:2])
        small = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        small_gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
        explored = self.explored_mask(small)
        ys, xs = np.nonzero(explored)
        if len(xs) < 200:                               # nothing that looks like map art at all
            return Result([Candidate(sid, None, 0.0, (0.0, 0.0), -1.0, {}) for sid in maps], {})
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        icon_px = self.icon_size(small)
        ctx = (self.door_map(small, icon_px), small_gray[y0:y1, x0:x1], explored[y0:y1, x0:x1], (x0, y0))
        spawns = self.find_spawn(small_gray, f)
        first = {}
        for sid in maps:                                # pass 1: every map, every spawn guess, scale as found
            first[sid] = max((self._try(sid, g, 1.0, ctx) + (g,) for g in spawns), key=lambda r: r[0])
        for sid in sorted(first, key=lambda sid: -first[sid][0])[:REFINE_MAPS]:
            g = first[sid][4]                           # pass 2: the best few, scale nudged around their guess
            for du in (0.96, 1.04):
                r = self._try(sid, g, du, ctx) + (g,)
                if r[0] > first[sid][0]:
                    first[sid] = r
        cands = []
        for sid, (total, s, t, det, _) in first.items():
            lv = self.h.levels_of(sid)
            cands.append(Candidate(sid, lv[0] if lv else None, s * self.keep[sid] / f, (t[0] / f, t[1] / f), total, det))
        cands.sort(key=lambda c: -c.score)

        top = cands[0].map_id
        pos, half = self.art[top][2], self.keep[top]
        icons = {k: cands[0].to_screen((pos[k][0] / half, pos[k][1] / half)) for k in ("spawn", "door")}
        res = Result(cands, icons)
        if icon_px and res.looks_like_map:
            self._icon_px[small.shape] = icon_px     # a sure map was read at this size: keep it
        return res


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import eggheist
    h = eggheist.load(sys.argv[1])
    pool = h.pool(int(sys.argv[3])) if len(sys.argv) > 3 else None
    res = Matcher(h).match(cv2.imread(sys.argv[2]), maps=pool)
    print("icons", {k: tuple(round(x) for x in v) for k, v in res.icons.items()})
    for c in res.candidates[:5]:
        print(c.map_id, round(c.score, 3), c.detail, "scale", round(c.scale, 3))
    print("looks like the map" if res.looks_like_map else f"NOT sure; shortlist {res.shortlist}")

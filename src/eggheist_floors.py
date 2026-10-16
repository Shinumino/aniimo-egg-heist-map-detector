"""Both floors of an Egg Heist map in one picture: the ground map as the game draws it, and each room's second
floor pulled out next to that room, joined to it by an arrow.

User, 2026-10-10: "show the first floor and second floor side by side where it connects so it has everything in
one single map", then "connect the first floor with second floor using a arrow".

Why pulled out: in the game a second floor sits directly over its own room, and the game shows it on a second
picture with the ground floor dimmed (src/eggheist.py, "Second floors"). Drawn in place it would hide the room
under it; drawn on a picture of its own it is a handful of loose pieces with nothing saying where they belong.
Beside its room, with an arrow, it says both.

The pieces are the game's own drawing, cut out of its upper picture. Where they go is worked out here:
- never on the map, never on another piece, with a clear gap around each;
- as close to its room as it fits;
- if the arrow to that spot would run over another room, a spot a little farther off with a clear run wins.
"""
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ACCENT = (233, 185, 73, 255)   # the page's accent colour
INK = (17, 17, 17, 255)
PAD = 700        # px of empty room around the 2048 px map for the pulled-out floors: the widest room is ~730 px
GAP = 28         # clear px between a pulled-out floor and anything else that is drawn
CELL = 4         # places are searched on a grid of 4 px cells: 16 times fewer to try, nobody sees 4 px
STRIDE = 3       # ... and every third cell is tried as a corner
TRIED = 4000     # the nearest this-many free places are compared (an area about 750 px across)
SAMPLES = 48     # points checked along an arrow for what it runs over
CROSS = 4.0      # each px of arrow over something drawn costs as much as this many px of distance
OUTLINE = 7      # px, around a two-floor room and around its pulled-out floor
LINE, EDGE, HEAD = 12, 20, 46   # the arrow: its line, the dark edge under it, the length of its head
TAG_W, TAG_H, TAG_FONT = 92, 58, 44
MARGIN = 40      # px kept around everything in the finished picture


def font(px):
    for name in ("segoeuib.ttf", "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name), px)
        except OSError:
            continue
    return ImageFont.load_default()


def connector(room, card):
    """The arrow from a room to its pulled-out floor: from the room's edge to the floor's edge, along the line
    between their centres. Both boxes are (left, top, right, bottom)."""
    ax, ay = (room[0] + room[2]) / 2, (room[1] + room[3]) / 2
    bx, by = (card[0] + card[2]) / 2, (card[1] + card[3]) / 2
    dx, dy = bx - ax, by - ay

    def leave(box):
        hw, hh = (box[2] - box[0]) / 2, (box[3] - box[1]) / 2
        return min(hw / abs(dx) if dx else math.inf, hh / abs(dy) if dy else math.inf)
    ta, tb = leave(room), leave(card)
    if not math.isfinite(ta) or ta + tb >= 1:      # one on top of the other: there is no arrow to draw
        return (ax, ay), (bx, by)
    return (ax + dx * ta, ay + dy * ta), (bx - dx * tb, by - dy * tb)


def place(drawn, rooms, cross=CROSS):
    """Where each room's pulled-out floor goes: for every room in `rooms` (left, top, right, bottom) the top-left
    corner (x, y) of a box of the room's size, or None when nothing is free. `drawn`: True where the map is.
    The biggest room is placed first: it has the fewest places to go."""
    height, width = drawn.shape
    h, w = -(-height // CELL), -(-width // CELL)
    cells = np.zeros((h * CELL, w * CELL), np.uint8)
    cells[:height, :width] = drawn
    solid = cells.reshape(h, CELL, w, CELL).max(axis=(1, 3))      # what an arrow should not run over
    g = -(-GAP // CELL)
    taken = cv2.dilate(solid, np.ones((2 * g + 1, 2 * g + 1), np.uint8))   # where a floor cannot sit
    out = [None] * len(rooms)
    for i in sorted(range(len(rooms)), key=lambda i: -(rooms[i][2] - rooms[i][0]) * (rooms[i][3] - rooms[i][1])):
        left, top, right, bottom = rooms[i]
        cw, ch = -(-(right - left) // CELL), -(-(bottom - top) // CELL)
        if cw >= w or ch >= h:
            continue
        total = cv2.integral(taken)
        inside = total[ch:, cw:] - total[:-ch, cw:] - total[ch:, :-cw] + total[:-ch, :-cw]   # per top-left cell
        free = np.argwhere(inside[::STRIDE, ::STRIDE] == 0) * STRIDE
        if not len(free):
            free = np.argwhere(inside == 0)
        if not len(free):
            continue
        # everything from here on in px, box centres
        cx, cy = (left + right) / 2, (top + bottom) / 2
        bx, by = free[:, 1] * CELL + (right - left) / 2, free[:, 0] * CELL + (bottom - top) / 2
        dist = np.hypot(bx - cx, by - cy)
        near = np.argsort(dist, kind="stable")[:TRIED]
        bx, by, dist = bx[near], by[near], dist[near]
        dx, dy = bx - cx, by - cy
        with np.errstate(divide="ignore", invalid="ignore"):   # the same two boxes: how far along the line each ends
            t = np.minimum(np.where(dx != 0, (right - left) / 2 / np.abs(dx), np.inf),
                           np.where(dy != 0, (bottom - top) / 2 / np.abs(dy), np.inf))
        t = np.clip(t, 0, 0.5)
        steps = (np.arange(1, SAMPLES + 1) / (SAMPLES + 1))[None, :]
        along = t[:, None] + (1 - 2 * t[:, None]) * steps                        # between the two edges only
        px = np.clip(((cx + dx[:, None] * along) / CELL).astype(int), 0, w - 1)
        py = np.clip(((cy + dy[:, None] * along) / CELL).astype(int), 0, h - 1)
        over = solid[py, px].mean(axis=1) * dist * (1 - 2 * t)                   # px of arrow over something drawn
        best = int(np.argmin(dist + cross * over))
        x, y = int(round(bx[best] - (right - left) / 2)), int(round(by[best] - (bottom - top) / 2))
        out[i] = (x, y)
        card = (x, y, x + right - left, y + bottom - top)
        x0, y0, x1, y1 = x // CELL, y // CELL, -(-card[2] // CELL), -(-card[3] // CELL)
        solid[y0:y1, x0:x1] = 1
        taken[max(0, y0 - g):y1 + g, max(0, x0 - g):x1 + g] = 1
        (ax, ay), (qx, qy) = connector(rooms[i], card)
        a, q = (int(ax / CELL), int(ay / CELL)), (int(qx / CELL), int(qy / CELL))
        cv2.line(solid, a, q, 1, thickness=-(-EDGE // CELL))
        cv2.line(taken, a, q, 1, thickness=-(-(EDGE + GAP) // CELL))
    return out


class Picture:
    """`image`: the finished picture (RGBA). `view`: the part of the map's own 2048 px space it shows, as
    (left, top, right, bottom); it starts below 0 or ends past 2048 where a pulled-out floor needed the room.
    `cards`: per two-floor room, {"room", "rect" (the room's box), "at" (corner of its pulled-out floor, or None
    if it found no place), "arrow" ((x, y), (x, y)) or None}, all in that same space."""

    def __init__(self, image, view, cards):
        self.image, self.view, self.cards = image, view, cards

    def spot(self, marker):
        """Where a marker goes in the map's 2048 px space: on the pulled-out floor if it is upstairs."""
        x, y = marker["art"]
        if marker.get("floor") == 2:
            for c in self.cards:
                if c["room"] == marker["room"] and c["at"]:
                    return x + c["at"][0] - c["rect"][0], y + c["at"][1] - c["rect"][1]
        return x, y


def _arrow(d, a, q):
    d.line([a, q], fill=INK, width=EDGE)
    d.line([a, q], fill=ACCENT, width=LINE)
    ang = math.atan2(q[1] - a[1], q[0] - a[0])
    d.polygon([q, (q[0] - HEAD * math.cos(ang - 0.45), q[1] - HEAD * math.sin(ang - 0.45)),
               (q[0] - HEAD * math.cos(ang + 0.45), q[1] - HEAD * math.sin(ang + 0.45))], fill=ACCENT, outline=INK)


def compose(heist, sid):
    """The picture for one map. A map without a second floor comes back as the plain map."""
    base = heist.art(sid)
    ups = heist.upstairs(sid)
    size = 2048 + 2 * PAD
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(base, (PAD, PAD))
    cards = [{"room": u["room"], "rect": tuple(u["rect"]), "at": None, "arrow": None} for u in ups]
    if ups:
        drawn = np.zeros((size, size), bool)
        drawn[PAD:PAD + 2048, PAD:PAD + 2048] = np.asarray(base.getchannel("A")) > 0
        rooms = [tuple(v + PAD for v in u["rect"]) for u in ups]
        spots = place(drawn, rooms)
        upper = heist.upper_art(sid)
        d = ImageDraw.Draw(canvas)
        for c, room, at in zip(cards, rooms, spots):       # the floors first, then every line on top of them
            if at:
                canvas.paste(upper.crop(c["rect"]), at)
        for c, room, at in zip(cards, rooms, spots):
            d.rectangle((room[0] - OUTLINE, room[1] - OUTLINE, room[2] + OUTLINE, room[3] + OUTLINE), outline=ACCENT, width=OUTLINE)
            if not at:
                continue
            card = (at[0], at[1], at[0] + room[2] - room[0], at[1] + room[3] - room[1])
            d.rectangle((card[0] - OUTLINE, card[1] - OUTLINE, card[2] + OUTLINE, card[3] + OUTLINE), outline=ACCENT, width=OUTLINE)
            a, q = connector(room, card)
            _arrow(d, a, q)
            d.rectangle((card[0], card[1], card[0] + TAG_W, card[1] + TAG_H), fill=ACCENT)
            d.text((card[0] + TAG_W / 2, card[1] + TAG_H / 2), "2F", font=font(TAG_FONT), fill=INK, anchor="mm")
            c["at"] = (at[0] - PAD, at[1] - PAD)
            c["arrow"] = ((a[0] - PAD, a[1] - PAD), (q[0] - PAD, q[1] - PAD))
    left, top, right, bottom = canvas.getchannel("A").getbbox() or (PAD, PAD, PAD + 2048, PAD + 2048)
    box = (max(0, left - MARGIN), max(0, top - MARGIN), min(size, right + MARGIN), min(size, bottom + MARGIN))
    return Picture(canvas.crop(box), tuple(v - PAD for v in box), cards)

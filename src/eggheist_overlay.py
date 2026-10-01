"""On-screen overlay for one-monitor players: the matched map, always on top where the user put it.
On the page (web/eggheist.html) "Place overlay" dims the screen like the snipping tool and the user drags
a rectangle: that is the overlay's place and size. A slider sets how see-through it is.
src/eggheist_server.py runs it.

The window is an ordinary separate window, like the ones Discord or OBS draw: nothing is injected into the
game. It is always on top, takes no clicks (they go to the game) and never takes focus. Shown only over a
game in borderless or windowed mode: exclusive fullscreen draws over every other window.

It is left out of screen captures (SetWindowDisplayAffinity, WDA_EXCLUDEFROMCAPTURE, Windows 10 2004+):
otherwise the helper's own M-key capture would photograph the overlay sitting on top of the very map it
is trying to recognise. tests/test_eggheist_overlay.py checks this on the real desktop.
F8 hides and shows it for a moment without going to the page.
"""
import ctypes
import os

from PIL import Image, ImageDraw, ImageFont

import eggheist

MIN_W, MIN_H = 160, 120                       # smallest dragged box that still shows a readable map
TITLE_H = 44                                  # px, the strip above the map
ALPHA = 0.9                                   # default window opacity; the page's slider changes it
ALPHA_RANGE = (0.2, 1.0)
PLACE_WAIT = 30                               # s: after "Place overlay", wait this long for the game to be in front
DIM = 0.35                                    # opacity of the dark layer while dragging
POLL_MS = 250
VK_F8 = 0x77
BG = (20, 23, 29, 255)
ICONS = {"spawn": "Img_Map_Mark_Uderground_Front_Door", "door": "Img_Map_Mark_Uderground_Begin",
         "egg": "Img_Map_Mark_GrabEgg_Lair", "key": "Img_Map_Mark_Uderground_Key_Orange"}
ICON_ART_PX = 110                             # icon size in 2048-px art units, as on the page
DOTS = {"reward": ((199, 155, 255), "R"), "unique": ((201, 201, 201), "U")}


def _font(px):
    for name in ("segoeuib.ttf", "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name), px)
        except OSError:
            continue
    return ImageFont.load_default()


class Cards:
    """Draws the overlay's picture: a title line and the map, cropped to where it is drawn, with markers."""

    def __init__(self, heist):
        self.h = heist
        self._cache, self._crop = {}, {}
        self.icons = {k: Image.open(os.path.join(heist.out, "icons", v + ".png")).convert("RGBA") for k, v in ICONS.items()}

    def title(self, match):
        ids = match.get("shortlist") or [match["map_id"]]
        if match.get("confident") or len(ids) == 1:
            levels = self.h.levels_of(match["map_id"])
            names = " / ".join(eggheist.LEVEL_NAMES[lv] for lv in levels)
            return f"Map {match['map_id']} · {names}"
        return "One of: " + ", ".join(str(i) for i in ids) + " (press M again after exploring)"

    def card(self, match, max_px=None, level=None, markers=True, box=None):
        """The card, at most `max_px` on its long side, or fitted inside `box` (w, h), keeping the map's shape."""
        box = tuple(box) if box else (max_px, max_px)
        sid = match["map_id"]
        levels = self.h.levels_of(sid)
        lv = level if level in levels else (levels[0] if levels else 5)
        key = (sid, tuple(match.get("shortlist") or ()), bool(match.get("confident")), box, lv, markers)
        if key not in self._cache:
            self._cache = {key: self._draw(match, box, lv, markers)}   # one card at a time is all it shows
        return self._cache[key]

    def _draw(self, match, box, lv, markers):
        sid = match["map_id"]
        art = self.h.art(sid)
        if sid not in self._crop:
            self._crop[sid] = art.getchannel("A").getbbox() or (0, 0, 2048, 2048)
        x0, y0, x1, y1 = self._crop[sid]
        pad = 40
        x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(2048, x1 + pad), min(2048, y1 + pad)
        mp = art.crop((x0, y0, x1, y1)).copy()
        if markers:
            self._markers(mp, sid, lv, (x0, y0))
        bw, bh = box
        s = min((bh - TITLE_H) / mp.height, bw / mp.width)
        mp = mp.resize((max(1, int(mp.width * s)), max(1, int(mp.height * s))), Image.LANCZOS)
        out = Image.new("RGBA", (min(bw, max(mp.width, 320)), mp.height + TITLE_H), BG)
        out.alpha_composite(mp, ((out.width - mp.width) // 2, TITLE_H))
        d = ImageDraw.Draw(out)
        d.text((12, TITLE_H // 2), self.title(match), font=_font(20), fill=(232, 230, 225, 255), anchor="lm")
        return out

    def _markers(self, mp, sid, lv, origin):
        d = ImageDraw.Draw(mp)
        marks = self.h.markers(sid, lv)
        for m in sorted(marks, key=lambda m: m["kind"] in self.icons):        # icons on top of dots
            x, y = m["art"][0] - origin[0], m["art"][1] - origin[1]
            if m["kind"] in self.icons:
                ic = self.icons[m["kind"]].resize((ICON_ART_PX, ICON_ART_PX), Image.LANCZOS)
                mp.alpha_composite(ic, (int(x - ICON_ART_PX / 2), int(y - ICON_ART_PX / 2)))
            elif m["kind"] in DOTS:
                color, ch = DOTS[m["kind"]]
                d.ellipse((x - 30, y - 30, x + 30, y + 30), fill=color + (255,), outline=(17, 17, 17, 255), width=5)
                d.text((x, y), ch, font=_font(40), fill=(17, 17, 17, 255), anchor="mm")


# -- the window ------------------------------------------------------------------------------------------------
GWL_EXSTYLE = -20
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x8, 0x20, 0x80
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x80000, 0x8000000
WDA_EXCLUDEFROMCAPTURE = 0x11


class OverlayWindow:
    def __init__(self, root):
        import tkinter
        from PIL import ImageTk
        self._tk = ImageTk
        self.top = tkinter.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.attributes("-alpha", ALPHA)
        self.top.configure(bg="#14171d")
        self.label = tkinter.Label(self.top, bd=0, bg="#14171d")
        self.label.pack()
        self.top.withdraw()
        self._photo, self._styled = None, False

    def hwnd(self):
        return int(self.top.wm_frame(), 16)

    def _style(self):
        u = ctypes.windll.user32
        h = self.hwnd()
        ex = u.GetWindowLongW(h, GWL_EXSTYLE)
        u.SetWindowLongW(h, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
        u.SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE)
        self._styled = True

    def show(self, img, corner):
        """`corner`: the window's top-left in screen px."""
        # master: the overlay's own window. Without it Tk ties the picture to the first Tk root ever made,
        # and once that one is closed (a second root, the tests) showing the picture fails
        self._photo = self._tk.PhotoImage(img, master=self.top)
        self.label.configure(image=self._photo)
        self.top.geometry(f"{img.width}x{img.height}+{int(corner[0])}+{int(corner[1])}")
        self.top.deiconify()
        self.top.update_idletasks()
        if not self._styled:
            self._style()

    def hide(self):
        self.top.withdraw()

    def set_alpha(self, alpha):
        self.top.attributes("-alpha", alpha)

    def visible(self):
        return self.top.state() == "normal"

    def rect(self):
        return self.top.winfo_rootx(), self.top.winfo_rooty(), self.top.winfo_width(), self.top.winfo_height()

    def styles(self):
        ex = ctypes.windll.user32.GetWindowLongW(self.hwnd(), GWL_EXSTYLE)
        return {"click_through": bool(ex & WS_EX_TRANSPARENT), "no_activate": bool(ex & WS_EX_NOACTIVATE),
                "topmost": bool(ex & WS_EX_TOPMOST)}

    def close(self):
        self.top.destroy()


def drag_rect(a, b):
    """The box between two drag points, either direction, as (x, y, w, h); None if too small for a map."""
    x, y = min(a[0], b[0]), min(a[1], b[1])
    w, h = abs(a[0] - b[0]), abs(a[1] - b[1])
    return (int(x), int(y), int(w), int(h)) if w >= MIN_W and h >= MIN_H else None


def virtual_screen():
    """(left, top, width, height) of all monitors together, in real pixels."""
    m = ctypes.windll.user32.GetSystemMetrics
    return m(76), m(77), m(78), m(79)          # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN


class SelectionLayer:
    """Dims every screen like the snipping tool; the user drags a box. Calls on_done((x, y, w, h)) in screen
    px, or on_done(None) for Esc, a right click or a box too small to hold a map."""

    def __init__(self, root, on_done):
        import tkinter
        self.on_done, self._start, self._box = on_done, None, None
        vx, vy, vw, vh = virtual_screen()
        self.origin = (vx, vy)
        self.top = tkinter.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.attributes("-alpha", DIM)
        self.top.geometry(f"{vw}x{vh}+{vx}+{vy}")
        self.canvas = tkinter.Canvas(self.top, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(vw // 2, vh // 2, text="Drag where the map should go.   Esc cancels.",
                                fill="white", font=("Segoe UI", 28, "bold"))
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Escape>", lambda e: self._finish(None))
        self.canvas.bind("<ButtonPress-3>", lambda e: self._finish(None))
        self.top.bind("<Escape>", lambda e: self._finish(None))
        self.top.update_idletasks()
        self.top.focus_force()
        self.canvas.focus_set()

    def _press(self, e):
        self._start = (e.x, e.y)
        if self._box:
            self.canvas.delete(self._box)
        self._box = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#e9b949", width=3, fill="white")

    def _move(self, e):
        if self._start and self._box:
            self.canvas.coords(self._box, *self._start, e.x, e.y)

    def _release(self, e):
        if not self._start:
            return
        r = drag_rect(self._start, (e.x, e.y))
        self._finish((r[0] + self.origin[0], r[1] + self.origin[1], r[2], r[3]) if r else None)

    def _finish(self, rect):
        if self.on_done is None:
            return
        done, self.on_done = self.on_done, None
        self.top.destroy()
        done(rect)


class Overlay:
    """Keeps the window in step with the helper: the latest match, and the place, size and see-through
    level chosen on the page. Opens the drag layer when the page asks for it."""

    def __init__(self, app, root):
        self.app, self.root = app, root
        self.win = OverlayWindow(root)
        self.cards = Cards(app.heist)
        self._f8_down, self._hidden_by_f8 = False, False
        self._layer, self._asked_at, self._alpha, self._shown = None, None, None, None
        self.root.after(POLL_MS, self.tick)

    def tick(self):
        try:
            self._f8()
            self._update()
        finally:
            self.root.after(POLL_MS, self.tick)

    def _f8(self):
        down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_F8) & 0x8000)
        if down and not self._f8_down:
            self._hidden_by_f8 = not self._hidden_by_f8
        self._f8_down = down

    def _update(self):
        settings = self.app.overlay_settings()
        if settings["placing"] or self._layer:
            return self._placing()
        match = self.app.latest.get("match")
        rect = settings.get("rect")
        if not rect or not match or self._hidden_by_f8:
            if self.win.visible():
                self.win.hide()
            return
        if settings["alpha"] != self._alpha:
            self._alpha = settings["alpha"]
            self.win.set_alpha(self._alpha)
        x, y, w, h = rect
        img = self.cards.card(match, box=(w, h), level=self.app.difficulty)
        pos = (x + (w - img.width) // 2, y + (h - img.height) // 2)       # centred in the dragged box
        if self._shown != (id(img), pos) or not self.win.visible():
            self.win.show(img, pos)
            self._shown = (id(img), pos)

    def _placing(self):
        """The page asked to place the overlay: wait (up to PLACE_WAIT s) for the game to come to the front, so
        the user drags over the game and not over the browser they just clicked in, then open the layer."""
        import time
        import eggheist_capture
        if self._layer:
            return
        if self.win.visible():
            self.win.hide()
        self._asked_at = self._asked_at or time.time()
        if eggheist_capture.windows_game_window() or time.time() - self._asked_at > PLACE_WAIT:
            self._layer = SelectionLayer(self.root, self._placed)

    def _placed(self, rect):
        self._layer, self._asked_at, self._shown = None, None, None
        self.app.placed(rect)

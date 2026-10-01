"""Press M in the game and the Egg Heist helper takes the screenshot itself (the user's snipping tool was
unreliable, 2026-09-30). Used by src/eggheist_server.py; on by default, `--no-capture` turns it off.

Chosen to stay as far from the game as a screenshot tool does, because the game ships a kernel anti-cheat
(NEP2 / NEPKernel.sys):
- the key is READ with GetAsyncKeyState, polled ~30 times a second. No keyboard hook, nothing injected,
  and the key still reaches the game (RegisterHotKey would have swallowed M).
- "is the game in front" is the foreground window's title and class ("Aniimo" / "UnityWndClass"). No
  handle to the game's process is ever opened.
- the picture is a copy of the screen inside that window (PIL ImageGrab, GDI), like any screenshot tool.
Pressing M in another window does nothing. M also CLOSES the map and M typed in the game's chat counts too;
the server decides what to do with a capture that is not a map screen (it keeps the last map).
"""
import threading
import time

WINDOW_TITLE, WINDOW_CLASS = "Aniimo", "UnityWndClass"
VK_M = 0x4D
# The map screen fades in from black. A fixed 0.7 s wait gave black or half-dark captures on the first
# real run (2026-09-30), so: wait a little, then grab every STEP until two grabs in a row look the same.
FIRST_WAIT = 0.5       # s after M before the first look
STEP = 0.25            # s between looks
MAX_WAIT = 4.0         # s: the screen never settled (an animation, a moving camera): use what is there
SETTLED = 1.5          # mean brightness change (0-255) between two looks that counts as "stopped changing"
NOT_BLACK = 12         # mean brightness below this is the black first frames, never "settled"
POLL = 0.03            # s between key reads


class Capture:
    def __init__(self, on_image, key_down=None, game_window=None, grab=None, sleep=time.sleep, poll=POLL):
        self.on_image = on_image
        self.key_down = key_down or windows_key_down
        self.game_window = game_window or windows_game_window
        self.grab = grab or windows_grab
        self.sleep, self.poll = sleep, poll
        self._was_down = False

    def step(self):
        down = bool(self.key_down())
        pressed = down and not self._was_down     # the moment M goes down; holding it is one press
        self._was_down = down
        if not pressed or not self.game_window():
            return
        self.sleep(FIRST_WAIT)
        waited, before, img = FIRST_WAIT, None, None
        while True:
            rect = self.game_window()             # read every time: an alt-tab while waiting cancels
            if not rect:
                return
            img = self.grab(rect)
            level = float(img[::8, ::8].mean())
            if before is not None and level >= NOT_BLACK and abs(level - before) < SETTLED:
                break
            if waited >= MAX_WAIT:
                break
            before = level
            self.sleep(STEP)
            waited += STEP
        self.on_image(img)

    def run(self, stop: threading.Event):
        while not stop.is_set():
            try:
                self.step()
            except Exception as e:                # a failed grab must not end the watching
                print(f"capture failed: {e}", flush=True)
            stop.wait(self.poll)


# -- Windows ------------------------------------------------------------------------------------------------
def enable_dpi_awareness():
    """Window rectangles in real screen pixels. Without this, on a 4K screen at 150% scaling the rectangle
    comes back in scaled units and the grab cuts off a third of the game."""
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # per-monitor v2
    except Exception:
        pass


def windows_key_down():
    import ctypes
    return ctypes.windll.user32.GetAsyncKeyState(VK_M) & 0x8000


def windows_game_window():
    """Screen rectangle (left, top, right, bottom) of the game's client area if the game is in front, else None."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    h = u.GetForegroundWindow()
    if not h:
        return None
    title = ctypes.create_unicode_buffer(64)
    cls = ctypes.create_unicode_buffer(64)
    u.GetWindowTextW(h, title, 64)
    u.GetClassNameW(h, cls, 64)
    if title.value != WINDOW_TITLE or cls.value != WINDOW_CLASS:
        return None
    r = wintypes.RECT()
    u.GetClientRect(h, ctypes.byref(r))
    p = wintypes.POINT(0, 0)
    u.ClientToScreen(h, ctypes.byref(p))
    if r.right <= 0 or r.bottom <= 0:
        return None                               # minimised
    return (p.x, p.y, p.x + r.right, p.y + r.bottom)


def windows_grab(rect):
    import cv2
    import numpy as np
    from PIL import ImageGrab
    img = ImageGrab.grab(bbox=rect, all_screens=True)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

"""What the log says about a start: the tool's version, Windows, where the game was looked for and found (or
not), and the build check. The first thing to read when someone sends their log.txt. No game files needed.
"""
import logging
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import eggheist_server  # noqa: E402
import game  # noqa: E402
import run  # noqa: E402
from test_game import fake_game  # noqa: E402


class CacheTest(unittest.TestCase):
    """The map pictures are read from the game once and kept. 1.1.0 keeps one more picture per map (its upper
    floors), so a folder left by 1.0.x is not complete: it is read again, with the same "First start" message,
    instead of the tool starting 15 s late without a word about why."""

    def load(self, cache):
        calls = []

        class FakeHeist:
            def __init__(self, build, pm_source=None, out=None, tile_bundles=None, icon_bundles=None):
                self.build, self.out = build, out

            def stitch_all(self):
                calls.append("pictures")
                os.makedirs(os.path.join(self.out, "maps"), exist_ok=True)

            def extract_icons(self):
                calls.append("icons")

        old = (run.CACHE, run.eggheist.Heist)
        try:
            run.CACHE, run.eggheist.Heist = cache, FakeHeist
            run.load(game.Check("X:/Aniimo", build="1111111", tables=b""))
        finally:
            run.CACHE, run.eggheist.Heist = old
        return calls

    def test_the_first_start_reads_the_pictures_and_the_next_one_does_not(self):
        with tempfile.TemporaryDirectory() as cache:
            self.assertEqual(self.load(cache), ["pictures", "icons"])
            self.assertEqual(self.load(cache), [])

    def test_a_cache_left_by_1_0_is_read_again(self):
        with tempfile.TemporaryDirectory() as cache:
            os.makedirs(os.path.join(cache, "1111111"))
            with open(os.path.join(cache, "1111111", "ready.txt"), "w") as f:     # what 1.0.x wrote when it was done
                f.write("1.0.2 1111111\n")
            self.assertEqual(self.load(cache), ["pictures", "icons"])
            self.assertEqual(self.load(cache), [])


class SourceTest(unittest.TestCase):
    def test_says_where_the_game_came_from(self):
        with tempfile.TemporaryDirectory() as lib:
            g = fake_game(lib)
            self.assertEqual(run.game_source(explicit=g, settings={}), (g, "--game"))
            self.assertEqual(run.game_source(explicit=None, settings={"game": g}), (g, "the chosen folder"))


class StartupLogTest(unittest.TestCase):
    def test_a_blocked_start_explains_itself_in_the_log(self):
        d = tempfile.mkdtemp(prefix="eggheist-startlog-")
        old = (run.LOG_FILE, run.SETTINGS, eggheist_server.run)
        try:
            run.LOG_FILE = os.path.join(d, "log.txt")
            run.SETTINGS = os.path.join(d, "settings.json")
            eggheist_server.run = lambda app, overlay=True: app.stop()     # start, log, stop: no waiting
            g = fake_game(os.path.join(d, "lib"), build="2222222")
            run.main(["--game", g, "--no-browser", "--no-overlay", "--no-capture", "--port", "0",
                      "--folder", os.path.join(d, "captures")])
            for h in list(logging.getLogger("eggheist").handlers):
                h.flush()
            with open(run.LOG_FILE, encoding="utf-8") as f:
                text = f.read()
            self.assertIn(f"Aniimo Egg Heist Map Detector {run.VERSION}", text)
            self.assertIn("Windows", text)
            self.assertIn(f"{g} (via --game)", text)
            self.assertIn("blocked (build 2222222):", text)
            self.assertNotIn("build None", text)
        finally:
            run.LOG_FILE, run.SETTINGS, eggheist_server.run = old
            for h in list(logging.getLogger("eggheist").handlers):
                if getattr(h, "baseFilename", "").startswith(d):
                    logging.getLogger("eggheist").removeHandler(h)
                    h.close()
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

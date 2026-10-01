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
import run  # noqa: E402
from test_game import fake_game  # noqa: E402


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

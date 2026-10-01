"""End to end against a real Aniimo install: find it, pass the check, read the tables and map pictures from
the game itself, and recognise real map screenshots.

Runs only on a PC with the game and the screenshots (they show the game's art, so they are not in this
repository: tests/fixtures is ignored by git). Put them there, or point EGGHEIST_FIXTURES at them. Takes about a minute the first time (it reads ~430 MB of game files).
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import game  # noqa: E402

FIX = os.environ.get("EGGHEIST_FIXTURES") or os.path.join(ROOT, "tests", "fixtures")
GAME = game.find_game()
EXPECTED = {   # screenshot -> (map, difficulty to set or None): the user's own runs, 2026-09-30
    "normal_start": (20056, None), "normal_full": (20056, None), "nightmare_start": (20036, None),
    "nightmare_full": (20036, None), "mkey_20056": (20056, None), "mkey_20060_explored": (20060, None),
    "mkey_20060_start_a": (20060, 3), "mkey_20060_start_b": (20060, 3),
}


@unittest.skipUnless(GAME, "needs Aniimo installed")
@unittest.skipUnless(os.path.isdir(FIX), "needs the map screenshots (EGGHEIST_FIXTURES)")
class RealGameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import cv2
        import run
        import eggheist_match
        cls.cv2 = cv2
        cls.check = game.check(GAME)
        if cls.check.blocked:
            raise unittest.SkipTest(f"installed game is not the supported one: {cls.check.blocked}")
        cls.cache = tempfile.mkdtemp(prefix="eggheist-cache-")
        run.CACHE = cls.cache
        cls.heist = run.load(cls.check)
        cls.matcher = eggheist_match.Matcher(cls.heist)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "cache", ""), ignore_errors=True)

    def test_the_first_start_leaves_a_complete_cache(self):
        out = os.path.join(self.cache, self.check.build)
        self.assertTrue(os.path.exists(os.path.join(out, "ready.txt")))
        self.assertEqual(len([n for n in os.listdir(os.path.join(out, "maps")) if n.endswith(".png")]), 30)
        self.assertIn("Img_Map_Mark_Uderground_Begin.png", os.listdir(os.path.join(out, "icons")))

    def test_the_real_screenshots_give_the_same_maps(self):
        for name, (sid, lv) in EXPECTED.items():
            img = self.cv2.imread(os.path.join(FIX, name + ".jpg"))
            res = self.matcher.match(img, maps=self.heist.pool(lv) if lv else None)
            self.assertEqual(res.best.map_id, sid, name)
            self.assertTrue(res.looks_like_map, name)

    def test_black_and_fading_captures_are_not_maps(self):
        for name in ("mkey_black", "mkey_fading"):
            img = self.cv2.imread(os.path.join(FIX, name + ".jpg"))
            self.assertFalse(self.matcher.match(img).looks_like_map, name)


if __name__ == "__main__":
    unittest.main()

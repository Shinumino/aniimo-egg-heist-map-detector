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
class InstalledGameTest(unittest.TestCase):
    """On a PC that has the game, a blocked check is a failure, not a skip. The screenshot tests below skip
    themselves when the game is not the supported one, so on 2026-10-10 this suite was green while the tool
    refused the installed game (Steam had moved it to build 3668494 the day before). The author's PC is the
    only place that can notice an update before a user does."""

    def test_this_version_runs_on_the_installed_game(self):
        self.assertIsNone(game.check(GAME).blocked)


@unittest.skipUnless(GAME, "needs Aniimo installed")
class RealGameDataTest(unittest.TestCase):
    """What the tool reads from the installed game. Needs only the game, not the screenshots (audit, 2026-10-16:
    these were behind the screenshots' skip and so never ran on a PC with the game but no screenshots)."""

    @classmethod
    def setUpClass(cls):
        import run
        cls.check = game.check(GAME)
        if cls.check.blocked:
            raise unittest.SkipTest(f"installed game is not the supported one: {cls.check.blocked}")
        cls.cache = tempfile.mkdtemp(prefix="eggheist-cache-")
        run.CACHE = cls.cache
        cls.heist = run.load(cls.check)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "cache", ""), ignore_errors=True)

    def test_the_first_start_leaves_a_complete_cache(self):
        import run
        out = os.path.join(self.cache, self.check.build)
        self.assertTrue(os.path.exists(os.path.join(out, run.READY)))
        names = [n for n in os.listdir(os.path.join(out, "maps")) if n.endswith(".png")]
        self.assertEqual(len([n for n in names if not n.endswith("-upper.png")]), 30)     # every map
        self.assertEqual(len([n for n in names if n.endswith("-upper.png")]), 30)         # and its upper floors
        self.assertIn("Img_Map_Mark_Uderground_Begin.png", os.listdir(os.path.join(out, "icons")))

    def test_second_floors_come_out_of_the_real_game(self):
        # the game's own upper pictures and the room data agree: 20056 has one room with an upstairs, and
        # nothing the map marks is upstairs on any map
        self.assertEqual([u["room"] for u in self.heist.upstairs(20056)], [7])
        floors = {m["floor"] for sid in self.heist.team_maps() for lv in self.heist.levels_of(sid)
                  for m in self.heist.markers(sid, lv)}
        self.assertEqual(floors, {1})

    def test_every_locked_room_has_its_key_and_its_egg_chance(self):
        # a player's report (2026-10-15): locked rooms can hold an egg. Every locked room (a *_Key room piece) shows
        # its key on every difficulty, 20045's key door room included (missed by 1.0.x), and one egg nest with
        # the share of runs it is there; a nest room's egg has none
        for sid in self.heist.team_maps():
            locked = sorted(r["id"] for r in self.heist.rooms(sid) if "_Key" in r["resId"])
            for lv in self.heist.levels_of(sid):
                marks = self.heist.markers(sid, lv)
                self.assertEqual(sorted(m["room"] for m in marks if m["kind"] == "key"), locked, (sid, lv))
                chances = [m for m in marks if m["kind"] == "egg" and m["chance"] is not None]
                self.assertEqual(sorted(m["room"] for m in chances), locked, (sid, lv))
        eggs = [m for m in self.heist.markers(20036, 5) if m["kind"] == "egg"]
        self.assertEqual(sorted(m["chance"] for m in eggs if m["chance"] is not None), [0.21, 0.5])


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

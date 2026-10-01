"""Finding the game and deciding whether this version of the tool may run against it (src/game.py).

These need no game files, so they run anywhere (GitHub Actions too): a fake Steam library is built in a
temporary folder. tests/test_real_game.py does the same against the real install, on a PC that has it.
"""
import hashlib
import io
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import game  # noqa: E402

VDF = r'''"libraryfolders"
{
	"0"
	{
		"path"		"D:\\Program Files (x86)\\Steam"
		"apps"
		{
			"228980"		"329701614"
		}
	}
	"1"
	{
		"path"		"J:\\SteamLibrary"
	}
}
'''


def fake_game(root, build="1111111", tables=b"tables", bundles=("a.uab", "b.uab")):
    g = os.path.join(root, "steamapps", "common", "Aniimo")
    lua = os.path.join(g, "Aniimo_Data", "cvs", "res", "lua")
    os.makedirs(lua)
    with open(os.path.join(lua, "LuaCacheVer.txt"), "w") as f:
        f.write(f"1.0.{build},2771573,a8784d33fb7cf605135ddbc22246d146")
    sa = os.path.join(g, "Aniimo_Data", "StreamingAssets", "cvs", "res")
    os.makedirs(os.path.join(sa, "lua"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(game.TABLES_IN_ARCHIVE, tables)
    with open(os.path.join(sa, "lua", "LuaScripts.xdf"), "wb") as f:
        f.write(buf.getvalue())
    pkg = os.path.join(sa, "uab", "win", "DefaultPackage")
    os.makedirs(pkg)
    for b in bundles:
        open(os.path.join(pkg, b), "wb").close()
    return g


def supported(build="1111111", tables=b"tables", tiles=("a.uab",), icons=("b.uab",)):
    return {build: {"tables_sha256": hashlib.sha256(tables).hexdigest(), "tiles": list(tiles), "icons": list(icons)}}


class SteamTest(unittest.TestCase):
    def test_reads_every_library_folder(self):
        self.assertEqual(game.libraries_from_vdf(VDF), [r"D:\Program Files (x86)\Steam", r"J:\SteamLibrary"])

    def test_finds_the_game_in_a_library(self):
        with tempfile.TemporaryDirectory() as lib:
            g = fake_game(lib)
            self.assertEqual(game.find_game(libraries=[r"X:\nothing", lib]), g)

    def test_a_given_folder_wins(self):
        with tempfile.TemporaryDirectory() as lib:
            g = fake_game(lib)
            self.assertEqual(game.find_game(explicit=g, libraries=[]), g)

    def test_no_game_is_none(self):
        self.assertIsNone(game.find_game(libraries=[tempfile.gettempdir()]))


class CheckTest(unittest.TestCase):
    """The tool runs only against exactly the game files it was made and tested for (user, 2026-10-01: after
    an update it must do nothing and point to GitHub). The game updated the morning this was written
    (3629693 -> 3634150) without telling anyone: that is the case these tests are about."""

    def test_the_build_it_was_made_for_runs(self):
        with tempfile.TemporaryDirectory() as lib:
            g = fake_game(lib)
            ok = game.check(g, supported())
            self.assertIsNone(ok.blocked, ok.blocked)
            self.assertEqual(ok.build, "1111111")
            self.assertEqual([os.path.basename(p) for p in ok.tiles], ["a.uab"])

    def test_another_build_is_blocked_and_points_to_github(self):
        with tempfile.TemporaryDirectory() as lib:
            g = fake_game(lib, build="2222222")
            r = game.check(g, supported())
            self.assertIn("2222222", r.blocked)
            self.assertIn("1111111", r.blocked)
            self.assertIn(game.RELEASES_URL, r.blocked)

    def test_same_build_number_but_changed_tables_is_blocked(self):
        with tempfile.TemporaryDirectory() as lib:
            g = fake_game(lib, tables=b"tables, quietly changed")
            r = game.check(g, supported())
            self.assertIn(game.RELEASES_URL, r.blocked)

    def test_a_missing_game_file_is_blocked(self):
        with tempfile.TemporaryDirectory() as lib:
            g = fake_game(lib, bundles=("a.uab",))
            r = game.check(g, supported())
            self.assertIn("b.uab", r.blocked)

    def test_no_game_found_points_to_the_button(self):
        # the page has a "Choose the Aniimo folder" button: nobody should have to type --game
        r = game.check(None, supported())
        self.assertIn("Choose the Aniimo folder", r.blocked)
        self.assertNotIn("--game", r.blocked)

    def test_the_real_list_names_the_current_build(self):
        # guards the release itself: the shipped list must hold exactly one build, fully described
        self.assertEqual(len(game.SUPPORTED), 1)
        (build, spec), = game.SUPPORTED.items()
        self.assertRegex(build, r"^\d{7}$")
        self.assertEqual(len(spec["tables_sha256"]), 64)
        self.assertEqual(len(spec["tiles"]), 7)
        self.assertEqual(len(spec["icons"]), 1)


if __name__ == "__main__":
    unittest.main()

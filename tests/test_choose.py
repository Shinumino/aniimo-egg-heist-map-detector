"""Pointing the tool at a game Steam does not know about (the official launcher installs anywhere): the page's
"Choose the Aniimo folder" button, what it accepts, and how the choice is remembered. No game files needed.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import game  # noqa: E402
import run  # noqa: E402
from test_game import fake_game, supported  # noqa: E402


class FindBelowTest(unittest.TestCase):
    def test_the_game_folder_itself(self):
        with tempfile.TemporaryDirectory() as lib:
            g = fake_game(lib)
            self.assertEqual(game.find_game_below(g), g)

    def test_a_folder_above_it_like_a_launchers_install_folder(self):
        with tempfile.TemporaryDirectory() as lib:
            g = fake_game(lib)                       # lib/steamapps/common/Aniimo: three levels down
            self.assertEqual(game.find_game_below(lib), g)

    def test_too_far_down_or_not_there_is_none(self):
        with tempfile.TemporaryDirectory() as lib:
            deep = os.path.join(lib, "a", "b", "c")
            fake_game(deep)                          # 6 levels down: a search that deep could crawl a whole drive
            self.assertIsNone(game.find_game_below(lib))
            self.assertIsNone(game.find_game_below(os.path.join(lib, "nope")))


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="eggheist-settings-")
        self.file = os.path.join(self.dir, "settings.json")

    def test_a_chosen_folder_is_remembered(self):
        run.save_settings(self.file, {"game": r"X:\Games\Aniimo"})
        self.assertEqual(run.load_settings(self.file), {"game": r"X:\Games\Aniimo"})

    def test_a_missing_or_broken_file_is_no_settings(self):
        self.assertEqual(run.load_settings(self.file), {})
        with open(self.file, "w") as f:
            f.write("{not json")
        self.assertEqual(run.load_settings(self.file), {})

    def test_where_to_look_first(self):
        # --game, then the remembered folder, then Steam's libraries
        with tempfile.TemporaryDirectory() as lib:
            g = fake_game(lib)
            self.assertEqual(run.game_folder(explicit=None, settings={"game": g}), g)
            self.assertEqual(run.game_folder(explicit=g, settings={"game": r"X:\elsewhere"}), g)


class ChooseTest(unittest.TestCase):
    """run.choose(folder): what the page's button does with the folder the user picked."""

    def test_a_good_folder_passes_and_is_remembered(self):
        with tempfile.TemporaryDirectory() as lib, tempfile.TemporaryDirectory() as here:
            g = fake_game(lib)
            settings = os.path.join(here, "settings.json")
            c = run.choose(lib, settings_file=settings, supported=supported())   # picked the folder above
            self.assertIsNone(c.blocked, c.blocked)
            self.assertEqual(c.game, g)
            self.assertEqual(json.load(open(settings))["game"], g)

    def test_a_folder_without_the_game_says_so_and_is_not_remembered(self):
        with tempfile.TemporaryDirectory() as empty, tempfile.TemporaryDirectory() as here:
            settings = os.path.join(here, "settings.json")
            c = run.choose(empty, settings_file=settings, supported=supported())
            self.assertIn("Aniimo", c.blocked)
            self.assertFalse(os.path.exists(settings))

    def test_cancelling_the_picker_changes_nothing(self):
        with tempfile.TemporaryDirectory() as here:
            settings = os.path.join(here, "settings.json")
            self.assertIsNone(run.choose(None, settings_file=settings, supported=supported()))
            self.assertFalse(os.path.exists(settings))


if __name__ == "__main__":
    unittest.main()

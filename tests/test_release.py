"""The release says the same thing everywhere: the version in run.py is the newest in CHANGELOG.md, and the
game build the tool accepts (src/game.py) is the one README.md and the changelog promise. A release that
says "works with build X" while checking for build Y would block everyone, or worse, the other way round.
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import game  # noqa: E402


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class ReleaseTest(unittest.TestCase):
    def test_version_is_the_newest_changelog_entry(self):
        version = re.search(r'^VERSION = "([^"]+)"', read("run.py"), re.M).group(1)
        newest = re.search(r"^## (\S+)", read("CHANGELOG.md"), re.M).group(1)
        self.assertEqual(version, newest)

    def test_the_build_it_checks_for_is_the_build_it_promises(self):
        (build,) = game.SUPPORTED
        self.assertIn(f"build {build}", read("README.md"))
        newest = read("CHANGELOG.md").split("\n## ")[1]
        self.assertIn(f"build {build}", newest)

    def test_license_names_the_author(self):
        self.assertIn("Copyright (c) 2026 Shinumino", read("LICENSE"))

    def test_no_dashes_that_read_as_em_dashes(self):
        # house style for prose: commas, full stops, parentheses
        for name in ("README.md", "CHANGELOG.md"):
            self.assertNotIn("—", read(name), name)


if __name__ == "__main__":
    unittest.main()

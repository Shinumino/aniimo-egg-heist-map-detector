"""Egg Heist rules that need no game files: made-up inputs, so they run anywhere, the public repository's CI
included (the 1.1.0 audit, 2026-10-16: none of the second-floor or locked-room logic ran there, because every
other test needs the game's data or the user's screenshots).

Shipped to the public project by tools/export_detector.py. Needs numpy, OpenCV and Pillow:
    .venv/Scripts/python.exe -m unittest tests.test_eggheist_offline
"""
import os
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import eggheist  # noqa: E402

EGG = next(iter(eggheist.MARK_EGG))


def heist(sandboxes, marks, spawners):
    """A Heist holding only the room library parts _nest_chance reads, without a game behind it."""
    h = eggheist.Heist.__new__(eggheist.Heist)
    h.sandboxes, h._marks, h._spawners = sandboxes, marks, spawners
    return h


def group(weight, *ids):
    return {"weight": weight, "spawnIds": list(ids)}


class FloorOfTest(unittest.TestCase):
    def test_a_room_with_one_floor_is_all_ground(self):
        self.assertEqual(eggheist.floor_of(6.0, []), 1)

    def test_upstairs_starts_a_little_below_the_upper_box(self):
        self.assertEqual(eggheist.floor_of(4.0, [4.0]), 2)
        self.assertEqual(eggheist.floor_of(4.0 - eggheist.FLOOR_MARGIN, [4.0]), 2)
        self.assertEqual(eggheist.floor_of(0.5, [4.0]), 1)


class NestChanceTest(unittest.TestCase):
    """A locked room's own egg nest: the share of runs its spawner places a variant holding it."""

    def test_one_variant_in_four(self):
        h = heist({7: {"spawners": [70]}}, {7: [(71, EGG, [1, 0, 2])]},
                  {70: {"spawnGroups": [group(25, 71), group(25, 72), group(25, 73), group(25, 74)]}})
        self.assertEqual(h._nest_chance(7), [([1, 0, 2], 0.25)])

    def test_two_variants_with_the_nest_in_the_same_spot_add_up(self):
        h = heist({7: {"spawners": [70]}}, {7: [(71, EGG, [1, 0, 2]), (72, EGG, [1, 0, 2])]},
                  {70: {"spawnGroups": [group(22, 71), group(28, 72), group(50, 73)]}})
        self.assertEqual(h._nest_chance(7), [([1, 0, 2], 0.5)])

    def test_nests_in_different_spots_each_keep_their_own_chance(self):
        # Gemini, 2026-10-16: pooled into one marker, spot B had no marker and spot A said 50% for 20%
        h = heist({7: {"spawners": [70]}}, {7: [(71, EGG, [1, 0, 2]), (72, EGG, [9, 0, 9])]},
                  {70: {"spawnGroups": [group(20, 71), group(30, 72), group(50, 73)]}})
        self.assertEqual(sorted(h._nest_chance(7)), [([1, 0, 2], 0.2), ([9, 0, 9], 0.3)])

    def test_a_variant_that_is_never_placed_is_no_nest(self):
        # Gemini, 2026-10-16: a 0% chance came out as a nest room's egg (no number)
        h = heist({7: {"spawners": [70]}}, {7: [(71, EGG, [1, 0, 2])]},
                  {70: {"spawnGroups": [group(0, 71), group(100, 72)]}})
        self.assertEqual(h._nest_chance(7), [])

    def test_an_empty_variant_and_a_second_spawner(self):
        # the game writes an empty spawnIds as {} (seen on spawner 91423788)
        h = heist({7: {"spawners": [60, 70]}}, {7: [(71, EGG, [1, 0, 2])]},
                  {60: {"spawnGroups": [{"weight": 1, "spawnIds": {}}, group(1, 61)]},
                   70: {"spawnGroups": [group(1, 71), {"weight": 3, "spawnIds": {}}]}})
        self.assertEqual(h._nest_chance(7), [([1, 0, 2], 0.25)])

    def test_a_room_with_no_nest_icon_has_none(self):
        h = heist({7: {"spawners": [70]}}, {7: []}, {70: {"spawnGroups": [group(1, 71)]}})
        self.assertEqual(h._nest_chance(7), [])


class ChanceLabelTest(unittest.TestCase):
    """Where the "25%" goes: right of the egg icon, unless that leaves the picture or covers a pulled-out floor
    (ChatGPT, 2026-10-16: on maps 20057 and 20059 it ran past the right edge and was cut)."""

    def setUp(self):
        import eggheist_overlay
        self.O = eggheist_overlay

    def test_right_of_the_icon_when_there_is_room(self):
        (x, y, anchor), box = self.O.label_spot(500, 400, 113, right_edge=2048)
        self.assertEqual(anchor, "lm")
        self.assertGreater(box[0], 500 + self.O.ICON_ART_PX / 2)

    def test_left_of_the_icon_near_the_right_edge(self):
        (x, y, anchor), box = self.O.label_spot(1900, 400, 113, right_edge=2048)
        self.assertEqual(anchor, "rm")
        self.assertLess(box[2], 1900 - self.O.ICON_ART_PX / 2)

    def test_left_of_the_icon_when_something_is_on_the_right(self):
        # a pulled-out floor, another marker or another chance: all boxes to keep off
        (x, y, anchor), box = self.O.label_spot(500, 400, 113, right_edge=2048, avoid=[(600, 380, 900, 700)])
        self.assertEqual(anchor, "rm")

    def test_below_the_icon_when_both_sides_are_taken(self):
        # 20036 at Nightmare: its 50% has a pulled-out floor on each side
        floors = [(600, 380, 900, 700), (100, 380, 400, 700)]
        (x, y, anchor), box = self.O.label_spot(500, 400, 113, right_edge=2048, bottom_edge=2048, avoid=floors)
        self.assertEqual(anchor, "mt")
        self.assertGreater(box[1], 400 + self.O.ICON_ART_PX / 2)


class PictureSaveTest(unittest.TestCase):
    """A map picture is written whole or not at all (ChatGPT, 2026-10-16: closing the tool while it wrote one
    left a broken file that later starts took as done, so Upper showed a broken picture for good)."""

    def test_an_interrupted_write_leaves_nothing_under_the_real_name(self):
        import eggheist_server

        class Breaks:
            def save(self, path, *a, **k):
                with open(path, "wb") as f:
                    f.write(b"RIFF half a picture")
                raise KeyboardInterrupt("the window was closed")

        d = tempfile.mkdtemp(prefix="eggheist-save-")
        path = os.path.join(d, "20036-upper.webp")
        with self.assertRaises(KeyboardInterrupt):
            eggheist_server.save_picture(Breaks(), path)
        self.assertFalse(os.path.exists(path))

    def test_a_finished_write_is_there(self):
        import eggheist_server
        from PIL import Image
        d = tempfile.mkdtemp(prefix="eggheist-save-")
        path = os.path.join(d, "20036.webp")
        eggheist_server.save_picture(Image.new("RGBA", (8, 8), (1, 2, 3, 255)), path)
        self.assertEqual(Image.open(path).size, (8, 8))
        self.assertEqual(os.listdir(d), ["20036.webp"])


class PlaceTest(unittest.TestCase):
    """place(drawn, rooms): where each room's pulled-out floor goes, as its top-left corner (src/eggheist_floors.py).
    Small made-up maps, so each rule can be seen on its own; the real maps are in tests/test_eggheist_floors.py."""

    def setUp(self):
        import eggheist_floors
        self.F = eggheist_floors

    def card(self, room, at):
        return (at[0], at[1], at[0] + room[2] - room[0], at[1] + room[3] - room[1])

    @staticmethod
    def gap_between(a, b):
        dx = max(a[0] - b[2], b[0] - a[2], 0)
        dy = max(a[1] - b[3], b[1] - a[3], 0)
        return (dx * dx + dy * dy) ** 0.5

    def test_a_floor_goes_next_to_its_room_and_not_on_the_map(self):
        drawn = np.zeros((800, 800), bool)
        room = (300, 300, 420, 420)
        drawn[300:420, 300:420] = True                    # the room
        drawn[350:370, 420:700] = True                    # a corridor leaving it to the right
        (at,) = self.F.place(drawn, [room])
        card = self.card(room, at)
        self.assertFalse(drawn[card[1]:card[3], card[0]:card[2]].any(), card)
        self.assertGreaterEqual(self.gap_between(card, room), self.F.GAP)
        self.assertLess(self.gap_between(card, room), 2 * self.F.GAP + self.F.CELL, "it should sit right beside its room")

    def test_two_floors_never_share_a_spot(self):
        drawn = np.zeros((900, 900), bool)
        rooms = [(300, 300, 420, 420), (460, 300, 580, 420)]            # two rooms side by side
        for left, top, right, bottom in rooms:
            drawn[top:bottom, left:right] = True
        a, b = (self.card(r, at) for r, at in zip(rooms, self.F.place(drawn, rooms)))
        self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3], (a, b))
        self.assertGreaterEqual(self.gap_between(a, b), self.F.GAP)

    def arrow_over_the_map(self, drawn, room, at):
        """How many px of the arrow from the room to a floor placed at `at` lie on something drawn."""
        (ax, ay), (bx, by) = self.F.connector(room, self.card(room, at))
        n = int(max(abs(bx - ax), abs(by - ay))) + 2
        xs, ys = np.linspace(ax, bx, n)[1:-1].astype(int), np.linspace(ay, by, n)[1:-1].astype(int)
        return int(drawn[ys, xs].sum())

    def test_the_arrow_does_not_run_over_another_room_when_it_can_be_avoided(self):
        # A room with neighbours right against it on the left, right and below, and two pillars above it with a
        # 40 px lane between them. The nearest free spot is past the left neighbour (248 px away), and its arrow
        # would cross that neighbour for 100 px. Straight up the lane, past the pillars, is farther (368 px) but
        # the arrow runs over nothing.
        drawn = np.zeros((1400, 1400), bool)
        room = (600, 700, 720, 820)
        drawn[700:820, 600:720] = True
        drawn[640:880, 500:600] = True                    # neighbour on the left
        drawn[640:880, 720:1020] = True                   # neighbour on the right
        drawn[820:1120, 500:1020] = True                  # neighbour below
        drawn[480:672, 540:640] = True                    # pillar, up and to the left
        drawn[480:672, 680:780] = True                    # pillar, up and to the right
        (nearest,) = self.F.place(drawn, [room], cross=0)             # distance only: what the rule is there to beat
        self.assertGreater(self.arrow_over_the_map(drawn, room, nearest), 50, "the made-up map does not set the trap")
        (at,) = self.F.place(drawn, [room])
        self.assertEqual(self.arrow_over_the_map(drawn, room, at), 0, self.card(room, at))
        self.assertLess(self.card(room, at)[3], room[1], "it goes up the lane, above the room")

    def test_nowhere_to_put_it_is_none(self):
        drawn = np.ones((300, 300), bool)
        self.assertEqual(self.F.place(drawn, [(100, 100, 200, 200)]), [None])

    def test_the_same_map_gives_the_same_places(self):
        drawn = np.zeros((900, 900), bool)
        rooms = [(300, 300, 420, 420), (460, 300, 580, 420), (300, 460, 380, 540)]
        for left, top, right, bottom in rooms:
            drawn[top:bottom, left:right] = True
        self.assertEqual(self.F.place(drawn, rooms), self.F.place(drawn, rooms))


if __name__ == "__main__":
    unittest.main()

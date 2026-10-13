"""deploy/bin/route_fixes.py: points along the bridge decks of the horse routes (owner 2026-10-13: horses swam under the
Magical Bridge arches north of Camelot and under PKB).

Built on a small PathPoints table with upstream's schema; the shipped file is checked on a real world when
HDC_TEST_WORLD names a clean classic world.
"""
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import route_fixes  # noqa: E402

TEST_WORLD = os.environ.get("HDC_TEST_WORLD")
NOW = "2026-10-13 12:00:00"
# Upstream's PathPoints table, as its worlds have it.
PATH_POINTS = ("CREATE TABLE `PathPoints` (`PathID` VARCHAR(255) NOT NULL DEFAULT '' COLLATE NOCASE, "
               "`Step` INT(11) NOT NULL DEFAULT 0, `X` INT(11) NOT NULL DEFAULT 0, `Y` INT(11) NOT NULL DEFAULT 0, "
               "`Z` INT(11) NOT NULL DEFAULT 0, `MaxSpeed` INT(11) NOT NULL DEFAULT 0, `WaitTime` INT(11) NOT NULL DEFAULT 0, "
               "`LastTimeRowUpdated` DATETIME NOT NULL DEFAULT '2000-01-01 00:00:00', "
               "`PathPoints_ID` VARCHAR(255) NOT NULL DEFAULT '' COLLATE NOCASE, PRIMARY KEY (`PathPoints_ID`))")
ROUTE = [(1, 0, 0, 0, 100), (2, 1000, 0, 0, 200), (3, 2000, 0, 0, 300), (4, 3000, 0, 0, 400), (5, 4000, 0, 0, 500)]
DATA = {
    "why": "Owner 2026-10-13: horses swam under two bridges.",
    "bridges": {"b1": "the first bridge", "b2": "the second bridge"},
    "crossings": [
        {"route": "R1", "bridge": "b1", "from": [1000, 0, 0], "to": [2000, 0, 0],
         "points": [[1300, 0, 50], [1700, 0, 50]], "deck": [[1300, 0, 35], [1700, 0, 35]]},
    ],
}
ONE_LINE = "Route fixes: 1 bridge crossing of 1 horse route given points on the deck: 1 on the first bridge"


def world(route=ROUTE, path_id="R1"):
    conn = sqlite3.connect(":memory:")
    conn.execute(PATH_POINTS)
    conn.executemany("INSERT INTO PathPoints (PathID, Step, X, Y, Z, MaxSpeed, WaitTime, PathPoints_ID) "
                     "VALUES (?, ?, ?, ?, ?, ?, 0, ?)", [(path_id, *row, f"{path_id}-{row[0]}") for row in route])
    return conn


def points(conn, path_id="R1"):
    return conn.execute("SELECT Step, X, Y, Z, MaxSpeed FROM PathPoints WHERE PathID=? ORDER BY Step", (path_id,)).fetchall()


class RouteFixTests(unittest.TestCase):
    def test_points_go_between_the_crossings_two_points_and_the_later_steps_move_up(self):
        conn = world()
        self.assertEqual(route_fixes.apply(conn, NOW, DATA), [ONE_LINE])
        self.assertEqual(points(conn), [(1, 0, 0, 0, 100), (2, 1000, 0, 0, 200), (3, 1300, 0, 50, 300),
                                        (4, 1700, 0, 50, 300), (5, 2000, 0, 0, 300), (6, 3000, 0, 0, 400),
                                        (7, 4000, 0, 0, 500)])

    def test_the_added_points_take_the_segments_speed_no_wait_and_ids_that_name_them(self):
        # A segment takes its speed from its end point (NpcMovementComponent), so the added points keep it.
        conn = world()
        route_fixes.apply(conn, NOW, DATA)
        crossing = DATA["crossings"][0]
        self.assertEqual(conn.execute("SELECT PathPoints_ID, MaxSpeed, WaitTime, LastTimeRowUpdated FROM PathPoints "
                                      "WHERE Step IN (3, 4) ORDER BY Step").fetchall(),
                         [(route_fixes.point_id(crossing, 0), 300, 0, NOW), (route_fixes.point_id(crossing, 1), 300, 0, NOW)])
        self.assertNotEqual(route_fixes.point_id(crossing, 0), route_fixes.point_id(crossing, 1))

    def test_a_second_start_changes_nothing(self):
        conn = world()
        route_fixes.apply(conn, NOW, DATA)
        self.assertEqual(route_fixes.apply(conn, NOW, DATA), [])
        self.assertEqual(len(points(conn)), 7)

    def test_points_from_an_earlier_release_are_replaced_by_the_files_new_ones(self):
        # The heights may be tuned after the first rides: a later release's points replace the rows this fix added
        # (found by their PathPoints_ID), and the route's later steps follow.
        conn = world()
        route_fixes.apply(conn, NOW, DATA)
        retuned = dict(DATA, crossings=[dict(DATA["crossings"][0], points=[[1500, 0, 60]])])
        self.assertEqual(route_fixes.apply(conn, NOW, retuned), [ONE_LINE])
        self.assertEqual(points(conn), [(1, 0, 0, 0, 100), (2, 1000, 0, 0, 200), (3, 1500, 0, 60, 300),
                                        (4, 2000, 0, 0, 300), (5, 3000, 0, 0, 400), (6, 4000, 0, 0, 500)])
        self.assertEqual(conn.execute("SELECT PathPoints_ID FROM PathPoints WHERE Step=3").fetchone(),
                         (route_fixes.point_id(retuned["crossings"][0], 0),))
        self.assertEqual(route_fixes.apply(conn, NOW, retuned), [])

    def test_its_own_points_moved_away_from_the_crossing_are_left_alone(self):
        conn = world()
        route_fixes.apply(conn, NOW, DATA)
        conn.execute("UPDATE PathPoints SET Step=99 WHERE PathPoints_ID=?", (route_fixes.point_id(DATA["crossings"][0], 0),))
        before = points(conn)
        retuned = dict(DATA, crossings=[dict(DATA["crossings"][0], points=[[1500, 0, 60]])])
        self.assertEqual(route_fixes.apply(conn, NOW, retuned),
                         ["Route fixes: 1 left as it is (the route no longer has that segment): R1 (the first bridge)"])
        self.assertEqual(points(conn), before)

    def test_two_crossings_of_one_route_both_get_their_points(self):
        data = dict(DATA, crossings=DATA["crossings"] + [
            {"route": "R1", "bridge": "b2", "from": [3000, 0, 0], "to": [4000, 0, 0], "points": [[3500, 0, 80]],
             "deck": [[3500, 0, 65]]}])
        conn = world()
        self.assertEqual(route_fixes.apply(conn, NOW, data),
                         ["Route fixes: 2 bridge crossings of 1 horse route given points on the deck: "
                          "1 on the first bridge, 1 on the second bridge"])
        self.assertEqual([p[1:4] for p in points(conn)],
                         [(0, 0, 0), (1000, 0, 0), (1300, 0, 50), (1700, 0, 50), (2000, 0, 0), (3000, 0, 0),
                          (3500, 0, 80), (4000, 0, 0)])
        self.assertEqual([p[0] for p in points(conn)], list(range(1, 9)))

    def test_a_crossing_the_owner_changed_is_left_alone_and_named(self):
        for change in ("UPDATE PathPoints SET Z=7 WHERE Step=3", "DELETE FROM PathPoints WHERE Step=3",
                       "UPDATE PathPoints SET Step=9 WHERE Step=2"):
            with self.subTest(change):
                conn = world()
                conn.execute(change)
                before = points(conn)
                self.assertEqual(route_fixes.apply(conn, NOW, DATA),
                                 ["Route fixes: 1 left as it is (the route no longer has that segment): "
                                  "R1 (the first bridge)"])
                self.assertEqual(points(conn), before)

    def test_a_route_not_in_the_world_is_skipped(self):
        conn = world(path_id="Other")
        self.assertEqual(route_fixes.apply(conn, NOW, DATA), [])
        self.assertEqual(len(points(conn, "Other")), 5)

    def test_route_names_compare_without_capitals_as_the_server_reads_them(self):
        conn = world(path_id="r1")
        self.assertEqual(route_fixes.apply(conn, NOW, DATA), [ONE_LINE])
        self.assertEqual(len(points(conn, "r1")), 7)

    def test_a_world_without_routes_is_left_alone(self):
        conn = sqlite3.connect(":memory:")
        self.assertEqual(route_fixes.apply(conn, NOW, DATA), [])

    def test_a_bad_file_rolls_the_step_back_and_says_so(self):
        # A bad crossing after a good one: the file is checked first, so nothing is applied.
        bad = dict(DATA, crossings=DATA["crossings"] + [{"route": "R1", "bridge": "b9", "from": [3000, 0, 0],
                                                         "to": [4000, 0, 0], "points": [[3500, 0, 80]], "deck": []}])
        conn = world()
        line, = route_fixes.apply(conn, NOW, bad)
        self.assertTrue(line.startswith("Route fixes: not applied (crossing 2 (R1): unknown bridge b9)"), line)
        self.assertEqual(points(conn), [(*row,) for row in ROUTE])

    def test_the_file_is_checked(self):
        good = DATA["crossings"][0]
        for change, error in (({"points": []}, "no points"), ({"from": [1, 2]}, "from"),
                              ({"points": [[1700, 0, 50], [1300, 0, 50]]}, "in order"),
                              ({"points": [[1300, 40, 50]]}, "off the line"), ({"route": ""}, "no route"),
                              ({"points": [[1001 + 10 * i, 0, 50] for i in range(65)]}, "more than 64 points")):
            with self.subTest(error):
                with self.assertRaisesRegex(ValueError, error):
                    route_fixes.check(dict(DATA, crossings=[dict(good, **change)]))
        with self.assertRaisesRegex(ValueError, "why"):
            route_fixes.check(dict(DATA, why="no date"))

    def test_the_shipped_file_is_well_formed(self):
        data = route_fixes.load_data()
        route_fixes.check(data)
        self.assertRegex(data["why"], r"\d{4}")
        pairs = [(c["route"].lower(), tuple(c["from"]), tuple(c["to"])) for c in data["crossings"]]
        self.assertEqual(len(pairs), len(set(pairs)))
        # The two reported bridges are in it, on the routes the research named.
        names = " ".join(data["bridges"].values())
        self.assertIn("Magical Bridge", names)
        self.assertIn("Prydwen", names)
        for name in data["bridges"].values():
            self.assertNotIn(",", name)
        self.assertIn("HS_Humberton_SnowdoniaFortress", {c["route"] for c in data["crossings"]})


def line_z(crossing, x, y):
    """The fixed route's height over (x, y): the polyline from, points, to, taken along the crossing."""
    poly = [crossing["from"], *crossing["points"], crossing["to"]]
    (ax, ay, _), (bx, by, _) = crossing["from"], crossing["to"]
    length = math.dist((ax, ay), (bx, by))

    def along(p):
        return ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / length

    s = along((x, y))
    for p, q in zip(poly, poly[1:]):
        sp, sq = along(p), along(q)
        if sp <= s <= sq:
            t = 0 if sq == sp else (s - sp) / (sq - sp)
            return p[2] + t * (q[2] - p[2])
    raise AssertionError(f"({x}, {y}) is not on the crossing")


@unittest.skipUnless(TEST_WORLD, "needs HDC_TEST_WORLD (a clean classic world database)")
class ShippedWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "world.db")
        shutil.copyfile(TEST_WORLD, cls.db)
        cls.data = route_fixes.load_data()
        with sqlite3.connect(cls.db) as conn:
            cls.before = conn.execute("SELECT COUNT(*) FROM PathPoints").fetchone()[0]
            cls.lines = route_fixes.apply(conn, NOW)
        cls.conn = sqlite3.connect(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_every_crossing_gets_its_points_and_nothing_is_left_alone(self):
        crossings = self.data["crossings"]
        routes = {c["route"].lower() for c in crossings}
        self.assertEqual(len(self.lines), 1)
        self.assertTrue(self.lines[0].startswith(f"Route fixes: {len(crossings)} bridge crossings of {len(routes)} "
                                                 "horse routes given points on the deck: "), self.lines[0])
        added = sum(len(c["points"]) for c in crossings)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PathPoints").fetchone()[0], self.before + added)
        for c in crossings:
            with self.subTest(route=c["route"], at=c["from"]):
                coords = [tuple(r) for r in self.conn.execute(
                    "SELECT X, Y, Z FROM PathPoints WHERE PathID=? ORDER BY Step", (c["route"],))]
                want = [tuple(c["from"]), *map(tuple, c["points"]), tuple(c["to"])]
                self.assertTrue(any(coords[i:i + len(want)] == want for i in range(len(coords))))

    def test_every_fixed_route_keeps_one_point_per_step(self):
        for route in sorted({c["route"] for c in self.data["crossings"]}):
            with self.subTest(route):
                steps = [s for (s,) in self.conn.execute("SELECT Step FROM PathPoints WHERE PathID=? ORDER BY Step",
                                                         (route,))]
                self.assertEqual(len(steps), len(set(steps)))

    def test_the_fixed_lines_ride_on_the_deck(self):
        # Never under the walkway, and not more than 35 over it (the points sit 15 over it, within 20).
        for c in self.data["crossings"]:
            for x, y, w in c["deck"]:
                with self.subTest(route=c["route"], at=(x, y)):
                    z = line_z(c, x, y)
                    self.assertGreaterEqual(z, w - 1)
                    self.assertLessEqual(z, w + 35)

    def test_a_second_start_changes_nothing(self):
        self.assertEqual(route_fixes.apply(self.conn, NOW), [])


if __name__ == "__main__":
    unittest.main()

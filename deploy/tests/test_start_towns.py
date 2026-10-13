"""deploy/bin/start_towns.py: the starting locations that were wrong for the period moved to the period's towns
(research start-locations-2026-10-13; owner's decisions 2026-10-13).

Built on a small StartupLocation table with upstream's schema; the shipped file is checked on a real world when
HDC_TEST_WORLD names a clean classic world.
"""
import itertools
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import start_towns  # noqa: E402
import world_fixes as wf  # noqa: E402
from tests.test_world_fixes import SCHEMA as WORLD_FIXES_SCHEMA  # noqa: E402

TEST_WORLD = os.environ.get("HDC_TEST_WORLD")
NOW = "2026-10-13 12:00:00"
OLD = "2000-01-01 00:00:00"
# Upstream's StartupLocation table, as its worlds have it.
STARTUP = ("CREATE TABLE `StartupLocation` (`StartupLoc_ID` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
           "`XPos` INT(11) NOT NULL DEFAULT 0, `YPos` INT(11) NOT NULL DEFAULT 0, `ZPos` INT(11) NOT NULL DEFAULT 0, "
           "`Heading` INT(11) NOT NULL DEFAULT 0, `Region` INT(11) NOT NULL DEFAULT 0, "
           "`MinVersion` INT(11) NOT NULL DEFAULT 0, `RealmID` INT(11) NOT NULL DEFAULT 0, "
           "`RaceID` INT(11) NOT NULL DEFAULT 0, `ClassID` INT(11) NOT NULL DEFAULT 0, "
           "`ClientRegionID` INT(11) NOT NULL DEFAULT 0{stamp})")
STAMP = ", `LastTimeRowUpdated` DATETIME NOT NULL DEFAULT '2000-01-01 00:00:00'"

MAGE = {"race": 1, "class": 18, "name": "Briton Mage", "town": "Adribard's Retreat (Avalon Marsh)",
        "upstream": [1, 559975, 513748, 2619, 4115], "period": [1, 472952, 628137, 2048, 509], "copied_from_row": 12,
        "why": "Mythic's list on Stratics, 2001-09-13."}
# The three Seers: the Norseman's period spot is the Kobold's upstream one (a cycle of towns).
SEERS = [
    {"race": 7, "class": 37, "name": "Dwarf Seer", "town": "Vasudheim (East Svealand)",
     "upstream": [100, 805792, 701507, 4960, 6433], "period": [100, 773771, 755376, 4600, 1363], "copied_from_row": 114,
     "why": "Mythic's list on Stratics, 2001-09-13."},
    {"race": 8, "class": 37, "name": "Kobold Seer", "town": "Haggerfel (Vale of Mularn)",
     "upstream": [100, 748428, 815912, 4408, 4713], "period": [100, 805776, 701532, 4960, 2380], "copied_from_row": 100,
     "why": "Allakhazam, 2003-02-08."},
    {"race": 5, "class": 37, "name": "Norseman Seer", "town": "Fort Atla (Gotar)",
     "upstream": [100, 773735, 755370, 4600, 5520], "period": [100, 748428, 815912, 4408, 4713], "copied_from_row": 506,
     "why": "Mythic's list on Stratics, 2001-09-13."},
]
DATA = {"moves": [MAGE, *SEERS]}
MAGE_LINE = "Start towns: 1 starting location moved to the period's towns: Briton Mage to Adribard's Retreat (Avalon Marsh)"
ALL_LINE = ("Start towns: 4 starting locations moved to the period's towns: Briton Mage to Adribard's Retreat (Avalon "
            "Marsh), Dwarf Seer to Vasudheim (East Svealand), Kobold Seer to Haggerfel (Vale of Mularn), Norseman Seer to "
            "Fort Atla (Gotar)")


def world(rows=(), stamp=True):
    """An in-memory world with a StartupLocation row per (entry, spot): the entry's race and class at the spot."""
    conn = sqlite3.connect(":memory:")
    conn.execute(STARTUP.format(stamp=STAMP if stamp else ""))
    for entry, spot in rows:
        add(conn, entry["race"], entry["class"], spot)
    return conn


def add(conn, race, cls, spot, realm=2):
    return conn.execute("INSERT INTO StartupLocation (Region, XPos, YPos, ZPos, Heading, MinVersion, RealmID, RaceID, "
                        "ClassID, ClientRegionID) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 0)",
                        (*spot, realm, race, cls)).lastrowid


def spot(conn, entry):
    return [list(r) for r in conn.execute("SELECT Region, XPos, YPos, ZPos, Heading FROM StartupLocation "
                                          "WHERE RaceID=? AND ClassID=? ORDER BY StartupLoc_ID",
                                          (entry["race"], entry["class"]))]


def everything(conn):
    return conn.execute("SELECT * FROM StartupLocation ORDER BY StartupLoc_ID").fetchall()


class StartTownTests(unittest.TestCase):
    def test_a_row_at_upstreams_spot_moves_to_the_period_spot(self):
        conn = world([(MAGE, MAGE["upstream"])])
        self.assertEqual(start_towns.apply(conn, NOW, DATA), [MAGE_LINE])
        self.assertEqual(spot(conn, MAGE), [MAGE["period"]])

    def test_only_the_spot_and_the_stamp_change(self):
        # MinVersion, RealmID and ClientRegionID stay; LastTimeRowUpdated says when.
        conn = world()
        conn.execute("INSERT INTO StartupLocation (Region, XPos, YPos, ZPos, Heading, MinVersion, RealmID, RaceID, "
                     "ClassID, ClientRegionID) VALUES (1, 559975, 513748, 2619, 4115, 7, 1, 1, 18, 3)")
        start_towns.apply(conn, NOW, DATA)
        self.assertEqual(everything(conn), [(1, 472952, 628137, 2048, 509, 1, 7, 1, 1, 18, 3, NOW)])

    def test_a_second_start_changes_nothing_and_prints_nothing(self):
        conn = world([(MAGE, MAGE["upstream"])])
        start_towns.apply(conn, NOW, DATA)
        conn.execute("UPDATE StartupLocation SET LastTimeRowUpdated=?", (OLD,))
        before = everything(conn)
        self.assertEqual(start_towns.apply(conn, NOW, DATA), [])
        self.assertEqual(everything(conn), before)

    def test_a_row_already_at_the_period_spot_is_up_to_date(self):
        conn = world([(MAGE, MAGE["period"])])
        self.assertEqual(start_towns.apply(conn, NOW, DATA), [])
        self.assertEqual(everything(conn)[0][-1], OLD)

    def test_the_three_seers_each_land_on_their_own_period_spot_whatever_the_order(self):
        # Each Seer stands where another race's Seer belongs (the Norseman's period spot is the Kobold's upstream one):
        # the spots are the file's, never read from another row, so neither the rows' order nor the file's matters.
        for rows in itertools.permutations(SEERS):
            for moves in itertools.permutations(SEERS):
                with self.subTest(rows=[e["name"] for e in rows], moves=[e["name"] for e in moves]):
                    conn = world([(entry, entry["upstream"]) for entry in rows])
                    line, = start_towns.apply(conn, NOW, {"moves": list(moves)})
                    self.assertTrue(line.startswith("Start towns: 3 starting locations moved to the period's towns: "),
                                    line)
                    for entry in SEERS:
                        self.assertEqual(spot(conn, entry), [entry["period"]], entry["name"])
                    self.assertEqual(start_towns.apply(conn, NOW, {"moves": list(moves)}), [])

    def test_every_entry_moves_in_one_run_and_the_line_names_each_move(self):
        conn = world([(entry, entry["upstream"]) for entry in DATA["moves"]])
        self.assertEqual(start_towns.apply(conn, NOW, DATA), [ALL_LINE])

    def test_a_row_the_owner_moved_is_left_alone_and_named_at_every_start(self):
        conn = world([(entry, entry["upstream"]) for entry in SEERS])
        owners = add(conn, MAGE["race"], MAGE["class"], [1, 1, 2, 3, 4], realm=1)
        kept = f"1 left as it is (at neither upstream's spot nor the period's): Briton Mage (StartupLocation {owners})"
        line, = start_towns.apply(conn, NOW, DATA)
        self.assertEqual(line, "Start towns: 3 starting locations moved to the period's towns: Dwarf Seer to Vasudheim "
                               "(East Svealand), Kobold Seer to Haggerfel (Vale of Mularn), Norseman Seer to Fort Atla "
                               "(Gotar); " + kept)
        self.assertEqual(spot(conn, MAGE), [[1, 1, 2, 3, 4]])
        self.assertEqual(start_towns.apply(conn, NOW, DATA), ["Start towns: " + kept])
        self.assertEqual(spot(conn, MAGE), [[1, 1, 2, 3, 4]])

    def test_a_row_the_owner_only_turned_is_the_owners_too(self):
        # The heading is part of the spot: the fix sets it, so it checks it, and a start the owner turned stays.
        turned = MAGE["upstream"][:4] + [0]
        conn = world([(MAGE, turned)])
        self.assertEqual(start_towns.apply(conn, NOW, DATA),
                         ["Start towns: 1 left as it is (at neither upstream's spot nor the period's): "
                          "Briton Mage (StartupLocation 1)"])
        self.assertEqual(spot(conn, MAGE), [turned])

    def test_every_row_of_the_pair_at_upstreams_spot_moves_and_the_others_are_named(self):
        conn = world([(MAGE, MAGE["upstream"]), (MAGE, MAGE["upstream"]), (MAGE, MAGE["period"]), (MAGE, [1, 9, 9, 9, 9])])
        self.assertEqual(start_towns.apply(conn, NOW, DATA),
                         ["Start towns: 2 starting locations moved to the period's towns: Briton Mage (2 rows) to "
                          "Adribard's Retreat (Avalon Marsh); 1 left as it is (at neither upstream's spot nor the "
                          "period's): Briton Mage (StartupLocation 4)"])
        self.assertEqual(spot(conn, MAGE), [MAGE["period"]] * 3 + [[1, 9, 9, 9, 9]])

    def test_other_races_and_classes_are_left_alone(self):
        # Another race's row at the Briton Mage's upstream spot, and a row for any race or class (0), stay.
        conn = world()
        add(conn, 3, 18, MAGE["upstream"], realm=1)
        add(conn, 0, 18, MAGE["upstream"], realm=1)
        add(conn, 1, 0, MAGE["upstream"], realm=1)
        before = everything(conn)
        self.assertEqual(start_towns.apply(conn, NOW, DATA), [])
        self.assertEqual(everything(conn), before)

    def test_a_pair_with_no_row_is_skipped(self):
        conn = world([(SEERS[0], SEERS[0]["upstream"])])
        self.assertEqual(start_towns.apply(conn, NOW, DATA),
                         ["Start towns: 1 starting location moved to the period's towns: Dwarf Seer to Vasudheim "
                          "(East Svealand)"])

    def test_a_table_without_the_stamp_column_still_moves_the_rows(self):
        conn = world([(MAGE, MAGE["upstream"])], stamp=False)
        self.assertEqual(start_towns.apply(conn, NOW, DATA), [MAGE_LINE])
        self.assertEqual(spot(conn, MAGE), [MAGE["period"]])

    def test_a_world_without_the_table_or_its_columns_is_left_alone(self):
        conn = sqlite3.connect(":memory:")
        self.assertEqual(start_towns.apply(conn, NOW, DATA), [])
        conn.execute("CREATE TABLE StartupLocation (StartupLoc_ID INTEGER PRIMARY KEY, XPos INT, YPos INT, ZPos INT, "
                     "Region INT, RaceID INT, ClassID INT)")  # no Heading
        conn.execute("INSERT INTO StartupLocation VALUES (1, 559975, 513748, 2619, 1, 1, 18)")
        self.assertEqual(start_towns.apply(conn, NOW, DATA), [])
        self.assertEqual(conn.execute("SELECT * FROM StartupLocation").fetchall(), [(1, 559975, 513748, 2619, 1, 1, 18)])

    def test_column_names_compare_without_capitals(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(STARTUP.format(stamp=STAMP).replace("`XPos`", "`xpos`").replace("`Heading`", "`HEADING`"))
        add(conn, MAGE["race"], MAGE["class"], MAGE["upstream"])
        self.assertEqual(start_towns.apply(conn, NOW, DATA), [MAGE_LINE])

    def test_a_failure_rolls_back_this_fix_only_and_says_so(self):
        # The Briton Mage moves first, then the Dwarf Seer's update fails: both stay where they were, and the other
        # fixes' changes in the same transaction are kept.
        conn = world([(MAGE, MAGE["upstream"]), (SEERS[0], SEERS[0]["upstream"])])
        conn.execute("CREATE TABLE other (x)")
        conn.execute("CREATE TRIGGER no_dwarf BEFORE UPDATE ON StartupLocation WHEN OLD.RaceID = 7 "
                     "BEGIN SELECT RAISE(ABORT, 'the Dwarf Seer is locked'); END")
        conn.commit()
        before = everything(conn)
        with conn:
            conn.execute("INSERT INTO other VALUES (1)")  # an earlier fix's change
            lines = start_towns.apply(conn, NOW, DATA)
        self.assertEqual(lines, ["Start towns: not applied (the Dwarf Seer is locked); the starting locations stay "
                                 "where they are"])
        self.assertEqual(everything(conn), before)
        self.assertEqual(conn.execute("SELECT x FROM other").fetchall(), [(1,)])

    def test_a_bad_file_is_not_applied_at_all(self):
        # A bad entry after a good one: the file is checked first, so nothing moves.
        bad = {"moves": [MAGE, dict(SEERS[0], period=[100, 1, 2])]}
        conn = world([(MAGE, MAGE["upstream"])])
        line, = start_towns.apply(conn, NOW, bad)
        self.assertTrue(line.startswith("Start towns: not applied (move 2 (Dwarf Seer): period must be "), line)
        self.assertEqual(spot(conn, MAGE), [MAGE["upstream"]])

    def test_a_missing_data_file_is_a_not_applied_line(self):
        conn = world([(MAGE, MAGE["upstream"])])
        with unittest.mock.patch.object(start_towns, "load_data", side_effect=FileNotFoundError("start_towns.json")):
            line, = start_towns.apply(conn, NOW)
        self.assertTrue(line.startswith("Start towns: not applied (start_towns.json)"), line)

    def test_the_file_is_checked(self):
        for change, error in (({"why": "no date"}, "no why with its date"), ({"name": ""}, "no name"),
                              ({"town": "Here, there"}, "town"), ({"race": 0}, "race"), ({"class": "18"}, "class"),
                              ({"upstream": [1, 2, 3, 4]}, "upstream must be"), ({"period": [1, 2, 3, 4, True]}, "period"),
                              ({"period": MAGE["upstream"]}, "already at"), ({"copied_from_row": None}, "copied_from_row")):
            with self.subTest(error):
                with self.assertRaisesRegex(ValueError, error):
                    start_towns.check({"moves": [dict(MAGE, **change)]})
        with self.assertRaisesRegex(ValueError, "twice"):
            start_towns.check({"moves": [MAGE, dict(MAGE, town="Cotswold Village (Camelot Hills)")]})
        with self.assertRaisesRegex(ValueError, "no moves"):
            start_towns.check({"moves": []})


class WorldFixesTests(unittest.TestCase):
    """world_fixes.apply runs the start towns in its transaction, under their own savepoint."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "world.db")
        with sqlite3.connect(self.db) as c:
            for stmt in WORLD_FIXES_SCHEMA:
                c.execute(stmt)
            c.execute("INSERT INTO ServerProperty (`Key`, Value) VALUES ('disabled_classes', '20;33')")
            add(c, MAGE["race"], MAGE["class"], MAGE["upstream"], realm=1)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_start_towns_run_with_the_other_fixes(self):
        with unittest.mock.patch.object(start_towns, "load_data", return_value=DATA):
            changes = wf.apply(self.db)
        self.assertEqual(changes, ["Disciple (Necromancer's base class) enabled: disabled_classes 20;33 -> 33", MAGE_LINE])
        with sqlite3.connect(self.db) as c:
            self.assertEqual(spot(c, MAGE), [MAGE["period"]])
        with unittest.mock.patch.object(start_towns, "load_data", return_value=DATA):
            self.assertEqual(wf.apply(self.db), [])

    def test_a_bad_data_file_does_not_stop_the_other_fixes(self):
        with unittest.mock.patch.object(start_towns, "load_data", return_value={"moves": [dict(MAGE, why="")]}):
            changes = wf.apply(self.db)
        self.assertEqual(len(changes), 2, changes)
        self.assertEqual(changes[0], "Disciple (Necromancer's base class) enabled: disabled_classes 20;33 -> 33")
        self.assertTrue(changes[1].startswith("Start towns: not applied ("), changes)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT Value FROM ServerProperty WHERE `Key`='disabled_classes'").fetchone(), ("33",))
            self.assertEqual(spot(c, MAGE), [MAGE["upstream"]])


# The shipped file's moves (owner's decisions 2026-10-13): the base-class rows every new character uses, then the
# final-class rows (bots stored with a final class).
SHIPPED = [
    ("Briton", "Mage"), ("Dwarf", "Seer"), ("Kobold", "Seer"), ("Norseman", "Seer"), ("Elf", "Stalker"),
    ("Briton", "Disciple"), ("Troll", "Mystic"), ("Celt", "Forester"), ("Firbolg", "Forester"),
    ("Highlander", "Scout"), ("Elf", "Blademaster"), ("Elf", "Champion"), ("Norseman", "Healer"),
]


class ShippedFileTests(unittest.TestCase):
    def test_the_shipped_file_is_well_formed(self):
        data = start_towns.load_data()
        start_towns.check(data)
        self.assertEqual([tuple(e["name"].split(" ", 1)) for e in data["moves"]], SHIPPED)
        for entry in data["moves"]:
            with self.subTest(entry["name"]):
                self.assertGreater(len(entry["why"]), 40)
                self.assertRegex(entry["why"], r"(19|20)\d\d-\d\d-\d\d")  # its sources are dated

    def test_the_seers_form_the_cycle_and_the_norseman_healer_follows_the_norseman_seer(self):
        moves = {e["name"]: e for e in start_towns.load_data()["moves"]}
        self.assertEqual(moves["Norseman Seer"]["period"], moves["Kobold Seer"]["upstream"])
        self.assertEqual(moves["Norseman Healer"]["period"], moves["Norseman Seer"]["period"])
        self.assertEqual(moves["Norseman Seer"]["town"], "Fort Atla (Gotar)")  # owner 2026-10-13, not Galplen

    def test_the_shrouded_isles_classes_start_in_their_shrouded_isles_city(self):
        moves = {e["name"]: e for e in start_towns.load_data()["moves"]}
        for name, region in (("Briton Disciple", 51), ("Troll Mystic", 151), ("Celt Forester", 181),
                             ("Firbolg Forester", 181)):
            with self.subTest(name):
                self.assertEqual(moves[name]["period"][0], region)


@unittest.skipUnless(TEST_WORLD, "needs HDC_TEST_WORLD (a clean classic world database)")
class ShippedWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "world.db")
        shutil.copyfile(TEST_WORLD, cls.db)
        cls.data = start_towns.load_data()
        with sqlite3.connect(f"file:{TEST_WORLD}?mode=ro", uri=True) as clean:
            cls.clean = {r[0]: r for r in clean.execute("SELECT * FROM StartupLocation")}
        with sqlite3.connect(cls.db) as conn:
            cls.lines = start_towns.apply(conn, NOW)
        cls.conn = sqlite3.connect(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def rows(self, entry):
        return self.conn.execute("SELECT StartupLoc_ID, Region, XPos, YPos, ZPos, Heading FROM StartupLocation "
                                 "WHERE RaceID=? AND ClassID=?", (entry["race"], entry["class"])).fetchall()

    def test_every_row_moves_and_none_is_left_alone(self):
        moves = self.data["moves"]
        self.assertEqual(len(self.lines), 1, self.lines)
        self.assertTrue(self.lines[0].startswith(f"Start towns: {len(moves)} starting locations moved to the period's "
                                                 "towns: Briton Mage to Adribard's Retreat (Avalon Marsh), "), self.lines[0])
        self.assertNotIn("left as", self.lines[0])
        for entry in moves:
            self.assertIn(f"{entry['name']} to {entry['town']}", self.lines[0])

    def test_each_row_was_at_upstreams_spot_and_lands_exactly_on_its_period_spot(self):
        for entry in self.data["moves"]:
            with self.subTest(entry["name"]):
                (row_id, *now), = self.rows(entry)
                self.assertEqual(now, entry["period"])
                # The clean world's row of the pair: upstream's spot, as the file has it (Region, X, Y, Z, Heading).
                clean = self.clean[row_id]
                self.assertEqual([clean[5], *clean[1:5]], entry["upstream"])

    def test_each_period_spot_is_its_source_rows_spot_in_the_clean_world(self):
        # The Norseman Seer and Healer copy the Kobold Seer's row 506 as upstream ships it (before it moves).
        for entry in self.data["moves"]:
            with self.subTest(entry["name"], row=entry["copied_from_row"]):
                source = self.clean[entry["copied_from_row"]]
                self.assertEqual([source[5], *source[1:5]], entry["period"])
                self.assertEqual(source[7], self.clean[self.rows(entry)[0][0]][7])  # the same realm

    def test_only_the_spot_of_those_rows_changes(self):
        moved = {self.rows(e)[0][0] for e in self.data["moves"]}
        for row in self.conn.execute("SELECT * FROM StartupLocation"):
            with self.subTest(row=row[0]):
                if row[0] in moved:
                    self.assertEqual(row[6:11], self.clean[row[0]][6:11])  # MinVersion to ClientRegionID
                    self.assertEqual(row[11], NOW)
                else:
                    self.assertEqual(row, self.clean[row[0]])
        self.assertEqual(len(moved), 13)

    def test_a_second_start_changes_nothing(self):
        self.assertEqual(start_towns.apply(self.conn, NOW), [])


if __name__ == "__main__":
    unittest.main()

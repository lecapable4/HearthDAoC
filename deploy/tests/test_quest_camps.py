"""deploy/bin/quest_camps.py: the quest camps upstream archived as "post-legacy" spawns, copied back once per world.

Built on a small database with the tables the step reads; the camps in deploy/bin/quest_camps.json are checked on a
real world by test_epic_period.py.
"""
import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import quest_camps  # noqa: E402

NOW = "2026-10-12 12:00:00"
DATA = {"camps": [
    {"key": "fire", "name": "Delfina's camp", "names": ["Tylwyth Teg ranger"], "ids": ["r1", "r2"], "why": "period"},
    {"key": "tower", "name": "Lieutenant Grimarth", "names": ["Lieutenant Grimarth"], "ids": ["g1"], "why": "period"},
]}


def world():
    conn = sqlite3.connect(":memory:")
    for table in ("Mob", quest_camps.ARCHIVE):
        extra = ", RemovalReason TEXT" if table == quest_camps.ARCHIVE else ""
        conn.execute(f"CREATE TABLE {table} (Mob_ID TEXT PRIMARY KEY, Name TEXT, Region INT, X INT, Y INT, Z INT{extra})")
    conn.executemany(f"INSERT INTO {quest_camps.ARCHIVE} VALUES (?, ?, 1, ?, 0, 0, 'Post-legacy')",
                     [("r1", "Tylwyth Teg ranger", 1), ("r2", "Tylwyth Teg ranger", 2), ("g1", "Lieutenant Grimarth", 3),
                      ("other", "Tylwyth Teg ranger", 4)])
    return conn


class QuestCampTests(unittest.TestCase):
    def test_copies_each_camps_rows_back_and_keeps_the_archive(self):
        conn = world()
        self.assertEqual(quest_camps.apply(conn, NOW, DATA),
                         ["Quest camps: copied back from upstream's archive: Delfina's camp (2), Lieutenant Grimarth (1)"])
        self.assertEqual(conn.execute("SELECT Mob_ID, Name, X FROM Mob ORDER BY Mob_ID").fetchall(),
                         [("g1", "Lieutenant Grimarth", 3), ("r1", "Tylwyth Teg ranger", 1), ("r2", "Tylwyth Teg ranger", 2)])
        self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {quest_camps.ARCHIVE}").fetchone(), (4,))

    def test_a_camp_is_copied_once_so_rows_the_owner_removes_stay_removed(self):
        conn = world()
        quest_camps.apply(conn, NOW, DATA)
        conn.execute("DELETE FROM Mob WHERE Mob_ID='r1'")
        self.assertEqual(quest_camps.apply(conn, NOW, DATA), [])
        self.assertIsNone(conn.execute("SELECT 1 FROM Mob WHERE Mob_ID='r1'").fetchone())

    def test_a_new_camp_in_the_file_is_copied_on_a_world_that_has_the_others(self):
        conn = world()
        quest_camps.apply(conn, NOW, {"camps": DATA["camps"][:1]})
        self.assertEqual(quest_camps.apply(conn, NOW, DATA),
                         ["Quest camps: copied back from upstream's archive: Lieutenant Grimarth (1)"])

    def test_rows_already_in_the_world_are_left_as_they_are(self):
        conn = world()
        conn.execute("INSERT INTO Mob VALUES ('r1', 'Tylwyth Teg ranger', 1, 99, 0, 0)")
        self.assertEqual(quest_camps.apply(conn, NOW, DATA)[0],
                         "Quest camps: copied back from upstream's archive: Delfina's camp (1), Lieutenant Grimarth (1)")
        self.assertEqual(conn.execute("SELECT X FROM Mob WHERE Mob_ID='r1'").fetchone(), (99,))

    def test_a_row_missing_from_the_archive_or_named_otherwise_is_named_in_the_log(self):
        conn = world()
        data = {"camps": [{"key": "fire", "name": "Delfina's camp", "names": ["Tylwyth Teg ranger"],
                           "ids": ["r1", "gone", "g1"], "why": "period"}]}
        self.assertEqual(quest_camps.apply(conn, NOW, data),
                         ["Quest camps: copied back from upstream's archive: Delfina's camp (1); "
                          "not in the archive as named: Delfina's camp (gone, g1)"])
        self.assertIsNone(conn.execute("SELECT 1 FROM Mob WHERE Mob_ID='g1'").fetchone())

    def test_a_world_without_the_archive_is_left_alone(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Mob (Mob_ID TEXT PRIMARY KEY, Name TEXT)")
        self.assertEqual(quest_camps.apply(conn, NOW, DATA), [])
        self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall(),
                         [("Mob",)])

    def test_a_failure_rolls_the_step_back_and_says_so(self):
        # A good camp first, so rows and a marker are written before the bad entry fails: all of it is undone.
        conn = world()
        bad = {"camps": [DATA["camps"][0], {"key": "bad", "name": "No source", "names": ["x"], "ids": ["g1"]}]}
        line, = quest_camps.apply(conn, NOW, bad)
        self.assertTrue(line.startswith("Quest camps: not applied (camp bad: no why)"), line)
        self.assertIsNone(conn.execute("SELECT 1 FROM Mob").fetchone())
        self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE name=?", (quest_camps.MARKER_TABLE,)).fetchall(), [])
        self.assertEqual(quest_camps.apply(conn, NOW, DATA)[0],
                         "Quest camps: copied back from upstream's archive: Delfina's camp (2), Lieutenant Grimarth (1)")

    def test_rows_hdc_spawns_restored_become_the_camps(self):
        # `hdc spawns restore` at a high level can bring back some of a camp's (lowercase-named) rows and track them in
        # fork_restored_mobs, which a later restore, `hdc spawns undo` and the quest-twin removal delete. Once the camp
        # is copied, its rows are the camp's: they leave that list.
        conn = world()
        conn.execute("CREATE TABLE fork_restored_mobs (Mob_ID TEXT PRIMARY KEY, PatchId TEXT, MaxLevel INT, RestoredUtc TEXT)")
        conn.execute("INSERT INTO Mob VALUES ('r1', 'Tylwyth Teg ranger', 1, 1, 0, 0)")
        conn.executemany("INSERT INTO fork_restored_mobs VALUES (?, 'restore-leveling-spawns-v1', 50, ?)", [("r1", NOW), ("other", NOW)])
        quest_camps.apply(conn, NOW, DATA)
        self.assertEqual(conn.execute("SELECT Mob_ID FROM fork_restored_mobs").fetchall(), [("other",)])

    def test_a_camp_archived_under_other_names_is_named_in_the_log(self):
        conn = world()
        conn.execute(f"UPDATE {quest_camps.ARCHIVE} SET Name='Renamed ranger' WHERE Mob_ID IN ('r1', 'r2')")
        data = {"camps": DATA["camps"][:1]}
        self.assertEqual(quest_camps.apply(conn, NOW, data),
                         ["Quest camps: not in the archive as named: Delfina's camp (r1, r2)"])
        self.assertIsNone(conn.execute("SELECT 1 FROM Mob").fetchone())

    def test_the_shipped_file_is_well_formed(self):
        data = quest_camps.load_data()
        keys = [camp["key"] for camp in data["camps"]]
        self.assertEqual(len(keys), len(set(keys)))
        ids = [i for camp in data["camps"] for i in camp["ids"]]
        self.assertEqual(len(ids), len(set(ids)))
        for camp in data["camps"]:
            with self.subTest(camp["key"]):
                quest_camps.check(camp)


if __name__ == "__main__":
    unittest.main()

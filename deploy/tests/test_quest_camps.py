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

    # "clone": an NPC the period had and the world lacks, made like another row (Lieutenant Cian like Lieutenant Brude).
    CIAN = {"key": "cian", "name": "Lieutenant Cian", "kind": "clone", "like": "b1", "id": "c1",
            "set": {"Name": "Lieutenant Cian", "X": 7}, "why": "period"}

    def test_a_clone_is_added_like_its_row_once(self):
        conn = world()
        conn.execute("INSERT INTO Mob VALUES ('b1', 'Lieutenant Brude', 1, 5, 6, 9200)")
        self.assertEqual(quest_camps.apply(conn, NOW, {"camps": [self.CIAN]}), ["Quest camps: added: Lieutenant Cian"])
        self.assertEqual(conn.execute("SELECT Mob_ID, Name, Region, X, Y, Z FROM Mob ORDER BY Mob_ID").fetchall(),
                         [("b1", "Lieutenant Brude", 1, 5, 6, 9200), ("c1", "Lieutenant Cian", 1, 7, 6, 9200)])
        conn.execute("DELETE FROM Mob WHERE Mob_ID='c1'")  # the owner removed him: he stays removed
        self.assertEqual(quest_camps.apply(conn, NOW, {"camps": [self.CIAN]}), [])
        self.assertIsNone(conn.execute("SELECT 1 FROM Mob WHERE Mob_ID='c1'").fetchone())

    def test_a_clone_whose_row_is_missing_waits_quietly(self):
        # Not this world's (another world, or a test's); a later start tries again.
        conn = world()
        self.assertEqual(quest_camps.apply(conn, NOW, {"camps": [self.CIAN]}), [])
        conn.execute("INSERT INTO Mob VALUES ('b1', 'Lieutenant Brude', 1, 5, 6, 9200)")
        self.assertEqual(quest_camps.apply(conn, NOW, {"camps": [self.CIAN]}), ["Quest camps: added: Lieutenant Cian"])

    def test_a_clone_whose_id_is_taken_is_named_in_the_log(self):
        conn = world()
        conn.execute("INSERT INTO Mob VALUES ('b1', 'Lieutenant Brude', 1, 5, 6, 9200)")
        conn.execute("INSERT INTO Mob VALUES ('c1', 'Someone', 1, 5, 6, 9200)")
        self.assertEqual(quest_camps.apply(conn, NOW, {"camps": [self.CIAN]}),
                         ["Quest camps: not added: Lieutenant Cian (its Mob_ID c1 is taken)"])

    # "archive": a row the period didn't have, kept in fork_removed_mobs (the generated Bline beside Bline Tengit).
    BLINE = {"key": "bline", "name": "the generated Bline", "kind": "archive", "ids": ["x1"], "names": ["Bline"],
             "why": "period"}

    def test_an_archived_row_leaves_the_world_and_is_kept(self):
        conn = world()
        conn.execute("INSERT INTO Mob VALUES ('x1', 'Bline', 1, 5, 6, 7)")
        self.assertEqual(quest_camps.apply(conn, NOW, {"camps": [self.BLINE]}),
                         ["Quest camps: archived in fork_removed_mobs: the generated Bline (1)"])
        self.assertIsNone(conn.execute("SELECT 1 FROM Mob WHERE Mob_ID='x1'").fetchone())
        self.assertEqual(conn.execute("SELECT Mob_ID, Name, FixId FROM fork_removed_mobs").fetchall(),
                         [("x1", "Bline", "quest-camp:bline")])
        self.assertEqual(quest_camps.apply(conn, NOW, {"camps": [self.BLINE]}), [])

    def test_a_row_to_archive_with_another_name_stays(self):
        conn = world()
        conn.execute("INSERT INTO Mob VALUES ('x1', 'Bline Tengit', 1, 5, 6, 7)")
        self.assertEqual(quest_camps.apply(conn, NOW, {"camps": [self.BLINE]}),
                         ["Quest camps: not archived (another name): the generated Bline (x1)"])
        self.assertIsNotNone(conn.execute("SELECT 1 FROM Mob WHERE Mob_ID='x1'").fetchone())

    def test_a_row_to_archive_already_gone_is_quietly_done(self):
        conn = world()
        self.assertEqual(quest_camps.apply(conn, NOW, {"camps": [self.BLINE]}), [])

    def test_the_shipped_file_is_well_formed(self):
        data = quest_camps.load_data()
        keys = [camp["key"] for camp in data["camps"]]
        self.assertEqual(len(keys), len(set(keys)))
        ids = [i for camp in data["camps"] for i in camp.get("ids", []) + [camp.get("id")] if i]  # a clone has "id"
        self.assertEqual(len(ids), len(set(ids)))
        for camp in data["camps"]:
            with self.subTest(camp["key"]):
                quest_camps.check(camp)


if __name__ == "__main__":
    unittest.main()

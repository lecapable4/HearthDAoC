"""deploy/bin/world_update.py: upstream's world update (db-<version>.json of a game patch), applied as upstream's
patcher applies it (OfflineDaoc.Patcher/Program.cs WorldUpdate at v0.37b), but strict like upstream's own check of a
new patch (make_patch.py check_world_update): a row that does not apply leaves the world as it was."""
import copy
import hashlib
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [os.path.join(REPO, "deploy", "bin"), os.path.join(REPO, "tools", "linux"),
                os.path.join(REPO, "tools", "linux", "tests")]

import world_update  # noqa: E402
from odaoc_fetch import FetchError  # noqa: E402

WORLD = """
CREATE TABLE Mob (Mob_ID TEXT PRIMARY KEY, Name TEXT, Level INTEGER, Size INTEGER, Note TEXT, LastTimeRowUpdated TEXT);
INSERT INTO Mob VALUES ('m1', 'pooka', 10, 30, NULL, '2026-01-01');
INSERT INTO Mob VALUES ('m2', 'blackthorn', 20, 40, 'x', '2026-01-01');
INSERT INTO Mob VALUES ('m3', 'falling ice', 5, 10, NULL, '2026-01-01');
CREATE TABLE ItemTemplate (Id_nb TEXT PRIMARY KEY, Model INTEGER, Icon BLOB, Flag INTEGER, Price REAL);
INSERT INTO ItemTemplate VALUES ('sword', 1, X'00ff', 0, 1.5);
"""
MOB = ["Mob_ID", "Name", "Level", "Size", "Note", "LastTimeRowUpdated"]
UPDATE = {
    "Version": "0.37",
    "IgnoreColumns": ["lasttimerowupdated"],  # names compare without case, as in Program.cs
    "NewTables": [{"Table": "offline_world_bot_guild",
                   "Create": "CREATE TABLE offline_world_bot_guild (BotId TEXT PRIMARY KEY, GuildID TEXT)",
                   "Indexes": ["CREATE INDEX idx_bot_guild ON offline_world_bot_guild (GuildID)"]}],
    "NewColumns": [{"Table": "Mob", "Column": "PathID", "Decl": "TEXT"}],
    "Tables": [
        {"Table": "Mob", "Columns": MOB, "Key": ["Mob_ID"], "IgnoreCompare": [],
         "Insert": [["m4", "fenrir shredder", 30, 50, None, "2026-10-01"]],
         # The old LastTimeRowUpdated differs from the world's: an ignored column. Note is NULL: compared with IS.
         "Update": [{"Old": ["m1", "pooka", 10, 30, None, "2025-12-31"], "New": ["m1", "pooka", 11, 35, None, "2026-10-01"]}],
         "Delete": [["m3", "falling ice", 5, 10, None, "2026-01-01"]]},
        {"Table": "ItemTemplate", "Columns": ["Id_nb", "Model", "Icon", "Flag", "Price"], "Key": ["Id_nb"],
         "IgnoreCompare": ["Price"],  # this table's own ignored column
         "Insert": [],
         "Update": [{"Old": ["sword", 1, {"$b64": "AP8="}, False, 9.9], "New": ["sword", 2, {"$b64": "AQI="}, True, 2.5]}],
         "Delete": []},
    ],
}
QUIET = lambda *a, **k: None  # noqa: E731


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def rows(db, sql):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "world.db")
        con = sqlite3.connect(self.db)
        con.executescript(WORLD)
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_adds_the_new_tables_and_columns_and_applies_every_row_with_a_log_row(self):
        logged = []
        self.assertEqual(world_update.apply(self.db, UPDATE, "0.37", log=logged.append),
                         {"added": 1, "changed": 2, "removed": 1})
        self.assertEqual(logged, ["World data updated to 0.37: 1 added, 2 changed, 1 removed."])
        self.assertEqual(rows(self.db, "SELECT Mob_ID, Name, Level, Size, LastTimeRowUpdated, PathID FROM Mob ORDER BY Mob_ID"),
                         [("m1", "pooka", 11, 35, "2026-10-01", None), ("m2", "blackthorn", 20, 40, "2026-01-01", None),
                          ("m4", "fenrir shredder", 30, 50, "2026-10-01", None)])
        self.assertEqual(rows(self.db, "SELECT * FROM ItemTemplate"), [("sword", 2, b"\x01\x02", 1, 2.5)])
        self.assertEqual(rows(self.db, "SELECT name FROM sqlite_master WHERE tbl_name='offline_world_bot_guild' ORDER BY name"),
                         [("idx_bot_guild",), ("offline_world_bot_guild",), ("sqlite_autoindex_offline_world_bot_guild_1",)])
        (version, applied, notes), = rows(self.db, "SELECT Version, AppliedUtc, Notes FROM offline_patch_log")
        self.assertEqual((version, notes), ("0.37", ""))
        self.assertRegex(applied, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{7}Z$")  # .NET's "o" format, as Program.cs writes it

    def test_a_second_run_changes_nothing(self):
        world_update.apply(self.db, UPDATE, "0.37", log=QUIET)
        before = sha(self.db)
        logged = []
        self.assertIsNone(world_update.apply(self.db, UPDATE, "0.37", log=logged.append))
        self.assertEqual(logged, ["World data: already updated to 0.37."])
        self.assertEqual(sha(self.db), before)

    def refused(self, update, pattern):
        before = sha(self.db)
        with self.assertRaisesRegex(world_update.WorldUpdateError, pattern):
            world_update.apply(self.db, update, "0.37", log=QUIET)
        self.assertEqual(sha(self.db), before)  # byte for byte: no new table, column or log row either

    def test_a_row_whose_old_value_is_gone_is_refused_and_the_world_is_left_as_it_was(self):
        con = sqlite3.connect(self.db)
        con.execute("UPDATE Mob SET Level=12 WHERE Mob_ID='m1'")  # the game (or a fix) changed it
        con.commit()
        con.close()
        self.refused(UPDATE, r"^the 0\.37 world update does not fit this world: 1 of its rows did not apply "
                             r"\(Mob update Mob_ID='m1'\); the world is unchanged$")

    def test_an_added_row_that_is_there_already_is_refused(self):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO Mob VALUES ('m4', 'fenrir shredder', 30, 50, NULL, '2026-10-01')")
        con.commit()
        con.close()
        self.refused(UPDATE, r"1 of its rows did not apply \(Mob insert Mob_ID='m4'\)")

    def test_a_removed_row_that_is_gone_already_is_refused(self):
        update = copy.deepcopy(UPDATE)
        update["Tables"][0]["Delete"].append(["m9", "gone", 1, 1, None, "x"])
        update["Tables"][1]["Update"][0]["Old"][1] = 7
        self.refused(update, r"2 of its rows did not apply \(Mob delete Mob_ID='m9', ItemTemplate update Id_nb='sword'\)")

    def test_an_unexpected_value_is_refused(self):
        update = copy.deepcopy(UPDATE)
        update["Tables"][0]["Insert"][0][4] = [1]
        self.refused(update, r"could not be applied \(unexpected value in the world update: \[1\]\)")

    def test_a_table_the_world_lacks_is_refused(self):
        update = copy.deepcopy(UPDATE)
        update["Tables"].append({"Table": "Nope", "Columns": ["a"], "Key": ["a"], "Insert": [[1]], "Update": [], "Delete": []})
        self.refused(update, r"could not be applied \(no such table: Nope\)")

    def test_tables_and_columns_the_world_has_already_are_kept(self):
        con = sqlite3.connect(self.db)
        con.executescript("CREATE TABLE offline_world_bot_guild (BotId TEXT PRIMARY KEY, GuildID TEXT);"
                          "ALTER TABLE Mob ADD COLUMN pathid TEXT;")
        con.close()
        world_update.apply(self.db, UPDATE, "0.37", log=QUIET)
        self.assertEqual([r[1] for r in rows(self.db, "PRAGMA table_info(Mob)")], MOB + ["pathid"])

    def test_numbers_decode_as_the_patcher_reads_them(self):
        self.assertEqual(world_update.value(2 ** 63 - 1), 2 ** 63 - 1)
        self.assertEqual(world_update.value(2 ** 63), float(2 ** 63))  # past int64: a double, as TryGetInt64 fails
        self.assertEqual((world_update.value(True), world_update.value(False)), (1, 0))
        self.assertEqual(world_update.value({"$b64": "AP8="}), b"\x00\xff")
        self.assertIsNone(world_update.value(None))

    def test_a_refusal_is_a_fetch_error(self):
        # init_world and world_admin report it like a failed download: the start or the command stops.
        self.assertTrue(issubclass(world_update.WorldUpdateError, FetchError))


if __name__ == "__main__":
    unittest.main()

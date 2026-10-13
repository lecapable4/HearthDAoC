"""Quest texts in the world data: deploy/bin/quest_dialogue.py and its data file quest_dialogue.json (the Guild of
Shadows chain's dialogue, and the classic quests' period lines, names and class words, without the guides' leftovers).

The synthetic tests use a tiny DataQuest table and data passed in. The tests of the real data file run world_fixes on a
copy of a clean classic world (HDC_TEST_WORLD).
"""
import contextlib
import io
import json
import os
import pathlib
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "bin")
sys.path.insert(0, BIN)

import epic_chains  # noqa: E402
import quest_dialogue as qd  # noqa: E402
import world_fixes as wf  # noqa: E402

TEST_WORLD = os.environ.get("HDC_TEST_WORLD")
SCHEMA = ("CREATE TABLE DataQuest (ID INTEGER PRIMARY KEY, StepType TEXT, AcceptText TEXT, Description TEXT, "
          "SourceText TEXT, StepText TEXT, TargetText TEXT, AdvanceText TEXT, FinishText TEXT, StepItemTemplates TEXT, "
          "CollectItemTemplate TEXT, FinalRewardItemTemplates TEXT, StartName TEXT, TargetName TEXT COLLATE NOCASE, QuestDependency TEXT, "
          "LastTimeRowUpdated DATETIME NOT NULL DEFAULT '2000-01-01 00:00:00')")
CHAINS = {"classes": {"Alpha": 1, "Beta": 2}, "steps": {"7": {"ids": [100, 200]}, "9": {"ids": [None, 300]}}}
OLD = "2000-01-01 00:00:00"
NOW = "2026-10-09 12:00:00"
CLASS_NAMES = ("Infiltrator", "Mercenary", "Cabalist", "Necromancer", "Reaver")


def guard_for(*rows):
    """The digest of a row's values given in sorted column-name order."""
    return qd.digest(list(rows))


class SyntheticTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(SCHEMA)
        self.conn.execute("INSERT INTO DataQuest (ID, StepType, Description, FinishText) VALUES (100, '2|3', 'old A', 'bye')")
        self.conn.execute("INSERT INTO DataQuest (ID, StepType, Description, FinishText) VALUES (200, '2|3', 'old B', 'bye')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def data(self, **overrides):
        entry = {"step": "7",
                 "set": {"Description": {"Alpha": "new A", "Beta": "new B"}, "FinishText": "farewell"},
                 "guard": {"100": [guard_for("old A", "bye")], "200": [guard_for("old B", "bye")]}}
        entry.update(overrides)
        return {"quests": [entry]}

    def run_fix(self, data):
        with self.conn:
            return qd.apply(self.conn, NOW, data, CHAINS)

    def row(self, qid, *columns):
        return self.conn.execute(f"SELECT {', '.join(columns)} FROM DataQuest WHERE ID=?", (qid,)).fetchone()

    def test_a_guarded_row_is_rewritten_for_its_class(self):
        self.assertEqual(self.run_fix(self.data()), ["Quest dialogue: 2 quests rewritten"])
        self.assertEqual(self.row(100, "Description", "FinishText", "LastTimeRowUpdated"), ("new A", "farewell", NOW))
        self.assertEqual(self.row(200, "Description", "FinishText", "LastTimeRowUpdated"), ("new B", "farewell", NOW))

    def test_a_second_run_changes_nothing_and_prints_nothing(self):
        data = self.data()
        self.run_fix(data)
        self.conn.execute("UPDATE DataQuest SET LastTimeRowUpdated=?", (OLD,))
        self.conn.commit()
        before = self.conn.execute("SELECT * FROM DataQuest ORDER BY ID").fetchall()
        self.assertEqual(self.run_fix(data), [])
        self.assertEqual(self.conn.execute("SELECT * FROM DataQuest ORDER BY ID").fetchall(), before)

    def test_a_row_the_owner_edited_is_kept_and_counted(self):
        self.conn.execute("UPDATE DataQuest SET Description='the owner wrote this' WHERE ID=100")
        self.conn.commit()
        self.assertEqual(self.run_fix(self.data()),
                         ["Quest dialogue: 1 quests rewritten; 1 left as they are (their text differs from upstream's and this file's): 100"])
        self.assertEqual(self.row(100, "Description", "LastTimeRowUpdated"), ("the owner wrote this", OLD))
        self.assertEqual(self.row(200, "Description"), ("new B",))

    def test_kept_rows_are_named_at_every_start_even_when_nothing_is_rewritten(self):
        # After an upstream upgrade changes a line, its quest keeps upstream's text: the log must say so.
        self.conn.execute("UPDATE DataQuest SET Description='mine' WHERE ID=100")
        self.conn.execute("UPDATE DataQuest SET Description='mine too' WHERE ID=200")
        self.conn.commit()
        line = ["Quest dialogue: 2 left as they are (their text differs from upstream's and this file's): 100, 200"]
        self.assertEqual(self.run_fix(self.data()), line)
        self.assertEqual(self.run_fix(self.data()), line)
        self.assertEqual(self.row(100, "Description"), ("mine",))

    def test_the_kept_list_is_capped(self):
        self.assertEqual(qd.summary(0, list(range(1, 13))),
                         ["Quest dialogue: 12 left as they are (their text differs from upstream's and this file's): "
                          "1, 2, 3, 4, 5, 6, 7, 8, 9, 10 and 2 more"])
        self.assertEqual(qd.summary(0, []), [])

    def test_a_row_already_at_the_new_text_is_left_alone(self):
        self.conn.execute("UPDATE DataQuest SET Description='new A', FinishText='farewell' WHERE ID=100")
        self.conn.commit()
        data = self.data(guard={})  # no guard at all: the row at the new text is not kept; only 200 is named
        self.assertEqual(self.run_fix(data), ["Quest dialogue: 1 left as they are (their text differs from upstream's and this file's): 200"])
        self.assertEqual(self.row(100, "LastTimeRowUpdated"), (OLD,))

    def test_an_earlier_version_of_the_text_is_rewritten_by_a_later_one(self):
        self.run_fix(self.data())
        later = self.data(set={"Description": {"Alpha": "newer A", "Beta": "newer B"}, "FinishText": "farewell"},
                          guard={"100": [guard_for("new A", "farewell")], "200": [guard_for("new B", "farewell")]})
        self.assertEqual(self.run_fix(later), ["Quest dialogue: 2 quests rewritten"])
        self.assertEqual(self.row(200, "Description"), ("newer B",))

    def test_null_and_empty_text_are_the_same(self):
        self.conn.execute("UPDATE DataQuest SET Description=NULL, FinishText='' WHERE ID=100")
        self.conn.commit()
        data = self.data(guard={"100": [guard_for("", "")], "200": [guard_for("old B", "bye")]})
        self.assertEqual(self.run_fix(data), ["Quest dialogue: 2 quests rewritten"])

    def test_per_stage_lists_and_per_class_objects_resolve(self):
        data = self.data(set={"StepText": ["first", {"Alpha": "second A", "Beta": "second B"}],
                              "TargetText": ["", ""], "AcceptText": "errand"},
                         guard={"100": [guard_for("", "", "")], "200": [guard_for("", "", "")]})
        self.assertEqual(self.run_fix(data), ["Quest dialogue: 2 quests rewritten"])
        self.assertEqual(self.row(100, "AcceptText", "StepText", "TargetText"), ("errand", "first|second A", "|"))
        self.assertEqual(self.row(200, "AcceptText", "StepText", "TargetText"), ("errand", "first|second B", "|"))

    def test_a_null_id_is_skipped(self):
        self.conn.execute("INSERT INTO DataQuest (ID, StepType, Description) VALUES (300, '2', 'old C')")
        self.conn.commit()
        data = {"quests": [{"step": "9", "set": {"Description": "new C"},
                            "guard": {"300": [guard_for("old C")]}}]}
        self.assertEqual(self.run_fix(data), ["Quest dialogue: 1 quests rewritten"])
        self.assertEqual(self.row(300, "Description"), ("new C",))

    def ids_data(self, **overrides):
        entry = {"ids": [100, 200], "set": {"Description": "new", "FinishText": "farewell"},
                 "guard": {"100": [guard_for("old A", "bye")], "200": [guard_for("old B", "bye")]}}
        entry.update(overrides)
        return {"quests": [entry]}

    def test_an_ids_entry_gives_its_quests_one_text(self):
        # The classic quests: plain quest IDs instead of an epic chain step, with the same guards.
        self.assertEqual(self.run_fix(self.ids_data()), ["Quest dialogue: 2 quests rewritten"])
        self.assertEqual(self.row(100, "Description", "FinishText", "LastTimeRowUpdated"), ("new", "farewell", NOW))
        self.assertEqual(self.row(200, "Description", "FinishText", "LastTimeRowUpdated"), ("new", "farewell", NOW))
        self.assertEqual(self.run_fix(self.ids_data()), [])

    def test_an_ids_entry_keeps_a_row_the_owner_edited_and_names_it(self):
        self.conn.execute("UPDATE DataQuest SET Description='the owner wrote this' WHERE ID=200")
        self.conn.commit()
        line = ["Quest dialogue: 1 quests rewritten; 1 left as they are (their text differs from upstream's and this file's): 200"]
        self.assertEqual(self.run_fix(self.ids_data()), line)
        self.assertEqual(self.row(200, "Description", "LastTimeRowUpdated"), ("the owner wrote this", OLD))
        self.assertEqual(self.run_fix(self.ids_data())[0], line[0].replace("1 quests rewritten; ", ""))

    def test_an_ids_entry_with_another_number_of_stages_keeps_the_row(self):
        self.conn.execute("UPDATE DataQuest SET StepType='2|0|3' WHERE ID=200")
        self.conn.commit()
        data = self.ids_data(set={"StepText": ["go", "come back"]}, guard={"100": [guard_for("")], "200": [guard_for("")]})
        self.assertEqual(self.run_fix(data),
                         ["Quest dialogue: 1 quests rewritten; 1 left as they are (their text differs from upstream's and this file's): 200"])
        self.assertEqual(self.row(100, "StepText"), ("go|come back",))
        self.assertEqual(self.row(200, "StepText"), (None,))

    def test_ids_and_step_entries_apply_together(self):
        self.conn.execute("INSERT INTO DataQuest (ID, StepType, Description) VALUES (300, '2', 'old C')")
        self.conn.commit()
        data = {"quests": [{"step": "7", "set": {"FinishText": "farewell"},
                            "guard": {"100": [guard_for("bye")], "200": [guard_for("bye")]}},
                           {"ids": [300], "name": "a classic quest", "set": {"Description": "new C"},
                            "guard": {"300": [guard_for("old C")]}}]}
        self.assertEqual(self.run_fix(data), ["Quest dialogue: 3 quests rewritten"])
        self.assertEqual(self.row(300, "Description"), ("new C",))

    def test_a_per_class_object_in_an_ids_entry_is_refused_by_name(self):
        lines = self.run_fix(self.ids_data(set={"Description": {"100": "a", "200": "b"}}))
        self.assertEqual(lines, ["Quest dialogue: not applied (quests 100, 200: Description has a per-class object, "
                                 "which only a step's entry takes); the quests keep the text they have"])

    def test_a_missing_row_is_skipped(self):
        self.conn.execute("DELETE FROM DataQuest WHERE ID=200")
        self.conn.commit()
        self.assertEqual(self.run_fix(self.data()), ["Quest dialogue: 1 quests rewritten"])

    def test_no_dataquest_table_is_not_an_error(self):
        conn = sqlite3.connect(":memory:")
        self.assertEqual(qd.apply(conn, NOW, self.data(), CHAINS), [])
        conn.close()

    def test_a_list_with_another_number_of_stages_keeps_the_rows_and_is_not_an_error(self):
        before = self.conn.execute("SELECT * FROM DataQuest ORDER BY ID").fetchall()
        self.assertEqual(self.run_fix(self.data(set={"StepText": ["only one"]})), ["Quest dialogue: 2 left as they are (their text differs from upstream's and this file's): 100, 200"])
        self.assertEqual(self.conn.execute("SELECT * FROM DataQuest ORDER BY ID").fetchall(), before)

    def test_one_row_with_another_number_of_stages_is_kept_and_the_other_is_rewritten(self):
        # The owner (or a later world) gave quest 200 a third stage: the file's two-stage text doesn't fit it.
        self.conn.execute("UPDATE DataQuest SET StepType='2|0|3' WHERE ID=200")
        self.conn.commit()
        data = self.data(set={"Description": {"Alpha": "new A", "Beta": "new B"}, "StepText": ["go", "come back"]},
                         guard={"100": [guard_for("old A", "")], "200": [guard_for("old B", "")]})
        self.assertEqual(self.run_fix(data),
                         ["Quest dialogue: 1 quests rewritten; 1 left as they are (their text differs from upstream's and this file's): 200"])
        self.assertEqual(self.row(100, "Description", "StepText"), ("new A", "go|come back"))
        self.assertEqual(self.row(200, "Description", "StepText", "LastTimeRowUpdated"), ("old B", None, OLD))

    def test_step_types_and_collect_items_are_rewritten_stage_by_stage(self):
        # Level 11's rebuild: a delivery becomes a turn-in of two items, and the item handed is another.
        data = self.data(set={"StepType": ["10", {"Alpha": "3", "Beta": "11"}],
                              "CollectItemTemplate": ["cq_stone;2", "cq_gem"], "StepItemTemplates": ["cq_gem", ""]},
                         guard={"100": [guard_for("", "", "2|3")], "200": [guard_for("", "", "2|3")]})
        self.assertEqual(self.run_fix(data), ["Quest dialogue: 2 quests rewritten"])
        self.assertEqual(self.row(100, "StepType", "CollectItemTemplate", "StepItemTemplates"), ("10|3", "cq_stone;2|cq_gem", "cq_gem|"))
        self.assertEqual(self.row(200, "StepType", "CollectItemTemplate", "StepItemTemplates"), ("10|11", "cq_stone;2|cq_gem", "cq_gem|"))
        self.assertEqual(self.run_fix(data), [])

    def test_a_step_type_list_with_another_number_of_stages_keeps_the_rows(self):
        # The fix never changes how many stages a quest has: the rows keep their two.
        before = self.conn.execute("SELECT * FROM DataQuest ORDER BY ID").fetchall()
        data = self.data(set={"StepType": ["10", "0", "3"], "CollectItemTemplate": ["cq_stone;2", "", "cq_gem"]},
                         guard={"100": [guard_for("", "2|3")], "200": [guard_for("", "2|3")]})
        self.assertEqual(self.run_fix(data), ["Quest dialogue: 2 left as they are (their text differs from upstream's and this file's): 100, 200"])
        self.assertEqual(self.conn.execute("SELECT * FROM DataQuest ORDER BY ID").fetchall(), before)

    def test_the_giver_and_the_dependencies_are_single_values(self):
        # The Shrouded Isles 7 and 11: each class's own trainer gives them, and the 11 needs the 7 of its branch.
        # QuestDependency's "|" separates its entries, not stages.
        self.conn.execute("UPDATE DataQuest SET StartName='Carys', QuestDependency='#21500/20478|!#20469'")
        self.conn.commit()
        upstream = guard_for("#21500/20478|!#20469", "Carys")  # sorted: QuestDependency, StartName
        data = self.data(set={"StartName": {"Alpha": "Elaru", "Beta": "Carys"},
                              "QuestDependency": {"Alpha": "#20478|!#20157", "Beta": "#20480|!#20159"}},
                         guard={"100": [upstream], "200": [upstream]})
        self.assertEqual(self.run_fix(data), ["Quest dialogue: 2 quests rewritten"])
        self.assertEqual(self.row(100, "StartName", "QuestDependency"), ("Elaru", "#20478|!#20157"))
        self.assertEqual(self.row(200, "StartName", "QuestDependency"), ("Carys", "#20480|!#20159"))
        self.assertEqual(self.run_fix(data), [])

    def test_a_bad_file_rolls_back_the_fix_and_says_so(self):
        bad = {
            "a list in a column that has no stages": self.data(set={"Description": ["a", "b"]}),
            "a class missing": self.data(set={"Description": {"Alpha": "x"}}),
            "an unknown class": self.data(set={"Description": {"Alpha": "x", "Beta": "y", "Gamma": "z"}}),
            "a | in a value": self.data(set={"Description": "a|b"}),
            "a | in a per-class value": self.data(set={"Description": {"Alpha": "a", "Beta": "b|c"}}),
            "a | in a stage": self.data(set={"StepText": ["a|b", "c"]}),
            "a | in a giver": self.data(set={"StartName": {"Alpha": "Elaru", "Beta": "Elaru|Carys"}}),
            "a list of givers": self.data(set={"StartName": ["Elaru", "Carys"]}),
            "a list of dependencies": self.data(set={"QuestDependency": ["#20478", "!#20157"]}),
            "an unknown column": self.data(set={"Name": "x"}),
            "an unknown step": self.data(step="8"),
            "a step twice": {"quests": self.data()["quests"] * 2},
            "a value that is not text": self.data(set={"Description": 5}),
            "a StepType that is not a list": self.data(set={"StepType": "2"}),
            "a StepType that is not a number": self.data(set={"StepType": ["2", "deliver"]}),
            "a per-class StepType that is not a number": self.data(set={"StepType": ["2", {"Alpha": "3", "Beta": " 3"}]}),
            "a per-class object in an ids entry": self.ids_data(set={"Description": {"Alpha": "x", "Beta": "y"}}),
            "a per-class stage in an ids entry": self.ids_data(set={"StepText": ["a", {"Alpha": "b", "Beta": "c"}]}),
            "a | in an ids entry's value": self.ids_data(set={"Description": "a|b"}),
            "an entry with a step and ids": self.data(ids=[100]),
            "an entry with neither a step nor ids": {"quests": [{"set": {"Description": "x"}}]},
            "ids that are not a list": self.ids_data(ids=100),
            "no ids": self.ids_data(ids=[]),
            "an ID that is not a number": self.ids_data(ids=["100"]),
            "an ID twice": self.ids_data(ids=[100, 100]),
            "a quest in two entries": {"quests": self.data()["quests"] + self.ids_data(ids=[200])["quests"]},
        }
        for what, data in bad.items():
            with self.subTest(what):
                before = self.conn.execute("SELECT * FROM DataQuest ORDER BY ID").fetchall()
                lines = self.run_fix(data)
                self.assertEqual(len(lines), 1, lines)
                self.assertTrue(lines[0].startswith("Quest dialogue: not applied ("), lines[0])
                self.assertEqual(self.conn.execute("SELECT * FROM DataQuest ORDER BY ID").fetchall(), before)

    def test_a_database_error_is_a_not_applied_line(self):
        self.conn.execute("DROP TABLE DataQuest")
        self.conn.execute(SCHEMA.replace("FinishText TEXT,", ""))  # FinishText is gone: reading the row fails
        self.conn.execute("INSERT INTO DataQuest (ID, StepType, Description) VALUES (100, '2|3', 'old A')")
        self.conn.commit()
        lines = self.run_fix(self.data())
        self.assertTrue(lines[0].startswith("Quest dialogue: not applied ("), lines)
        self.assertEqual(self.row(100, "Description"), ("old A",))

    def test_a_missing_data_file_is_a_not_applied_line(self):
        with unittest.mock.patch.object(qd, "load_data", side_effect=FileNotFoundError("quest_dialogue.json")):
            with self.conn:
                lines = qd.apply(self.conn, NOW, None, CHAINS)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("Quest dialogue: not applied ("), lines)

    def test_the_digest_is_the_documented_one(self):
        import hashlib
        self.assertEqual(qd.digest(["a", None, "é"]), hashlib.sha256('["a", "", "é"]'.encode("utf-8")).hexdigest())


class FailureLeavesTheOtherFixesTests(unittest.TestCase):
    """world_fixes.apply: a failing dialogue fix undoes only itself; the fixes before it are saved."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "world.db")
        with sqlite3.connect(self.db) as c:
            c.execute("CREATE TABLE ServerProperty (Category TEXT NOT NULL DEFAULT '', `Key` VARCHAR(255) NOT NULL DEFAULT '', "
                      "Description TEXT NOT NULL DEFAULT '', DefaultValue TEXT NOT NULL DEFAULT '', Value TEXT NOT NULL DEFAULT '', "
                      "LastTimeRowUpdated DATETIME NOT NULL DEFAULT '2000-01-01 00:00:00', ServerProperty_ID VARCHAR(255), "
                      "PRIMARY KEY (`Key`))")
            c.execute("INSERT INTO ServerProperty (`Key`, Value) VALUES ('disabled_classes', '20;33')")
            c.execute("CREATE TABLE StartupLocation (StartupLoc_ID INTEGER PRIMARY KEY AUTOINCREMENT, XPos INT, YPos INT, "
                      "ZPos INT, Heading INT, Region INT, MinVersion INT, RealmID INT, RaceID INT, ClassID INT, "
                      "ClientRegionID INT, LastTimeRowUpdated DATETIME NOT NULL DEFAULT '2000-01-01 00:00:00')")
            c.execute(SCHEMA)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_bad_data_file_does_not_stop_the_other_fixes(self):
        bad = {"quests": [{"step": "7", "set": {"Name": "x"}, "guard": {}}]}
        with unittest.mock.patch.object(qd, "load_data", return_value=bad), \
                unittest.mock.patch.object(epic_chains, "load_data", return_value=CHAINS):
            changes = wf.apply(self.db)
        self.assertEqual(changes[0], "Disciple (Necromancer's base class) enabled: disabled_classes 20;33 -> 33")
        self.assertEqual(len(changes), 2)
        self.assertTrue(changes[1].startswith("Quest dialogue: not applied ("), changes)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT Value FROM ServerProperty WHERE `Key`='disabled_classes'").fetchone(), ("33",))


def real_data():
    return qd.load_data(), epic_chains.load_data()


def quest_ids(data, chains):
    """Every quest the file rewrites: its steps' and its ids entries'."""
    return [qid for entry in data["quests"] for qid in qd._quests(entry, chains)[1].values()]


def chain_ids(data, chains):
    """The Guild of Shadows chain's quests: the step entries'."""
    return [qid for entry in data["quests"] if "step" in entry for qid in qd._quests(entry, chains)[1].values()]


class DataFileTests(unittest.TestCase):
    """The shape of quest_dialogue.json (no world needed). Waits for the data file."""

    def test_every_entry_is_well_formed(self):
        data, chains = real_data()
        self.assertTrue(data["quests"])
        seen, quests = set(), set()
        for entry in data["quests"]:
            with self.subTest(entry=qd.label(entry)):
                if "step" in entry:
                    self.assertIn(entry["step"], chains["steps"])
                    self.assertNotIn(entry["step"], seen)
                    seen.add(entry["step"])
                    ids = {str(qid) for qid in chains["steps"][entry["step"]]["ids"] if qid is not None}
                else:
                    self.assertTrue(entry["name"])  # the quest's name, for the reader
                    ids = {str(qid) for qid in entry["ids"]}
                    self.assertEqual(len(ids), len(entry["ids"]))
                self.assertTrue(ids.isdisjoint(quests))
                quests |= ids
                self.assertTrue(entry["set"])
                self.assertLessEqual(set(entry["set"]), set(qd.COLUMNS))
                self.assertEqual(set(entry["guard"]), ids)
                for digests in entry["guard"].values():
                    self.assertTrue(digests)
                    for d in digests:
                        self.assertRegex(d, r"^[0-9a-f]{64}$")


class SealedTests(unittest.TestCase):
    """The committed text is sealed: no world needed."""

    def test_every_quests_current_text_is_in_its_guard_list(self):
        data, chains = real_data()
        ids = qd.unsealed(data, chains)
        self.assertFalse(ids, f"the text of quests {', '.join(ids)} is not sealed: run python3 deploy/bin/quest_dialogue.py --seal")


@unittest.skipUnless(TEST_WORLD, "needs HDC_TEST_WORLD (a clean classic world database)")
class RealDialogueTests(unittest.TestCase):
    """The real data file on a copy of a clean classic world. These wait for quest_dialogue.json."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "world.db")
        shutil.copyfile(TEST_WORLD, cls.db)
        cls.data, cls.chains = real_data()
        cls.first = wf.apply(cls.db)
        cls.conn = sqlite3.connect(cls.db)
        cls.rows = {qid: cls.conn.execute(
            "SELECT AcceptText, Description, SourceText, StepType, StepText, TargetText, AdvanceText, FinishText "
            "FROM DataQuest WHERE ID=?", (qid,)).fetchone() for qid in quest_ids(cls.data, cls.chains)}

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_every_quest_of_every_entry_is_rewritten_and_none_is_kept(self):
        total = len(quest_ids(self.data, self.chains))
        self.assertIn(f"Quest dialogue: {total} quests rewritten", self.first)

    def test_a_second_run_changes_nothing(self):
        self.assertEqual(wf.apply(self.db), [])

    def test_the_rows_hold_the_resolved_text_of_the_file(self):
        planned = qd._plan(self.conn, self.data, self.chains)
        self.assertEqual(len(planned), len(self.rows))
        for qid, columns, values, _guard in planned:
            with self.subTest(quest=qid):
                held = self.conn.execute(f"SELECT {', '.join(columns)} FROM DataQuest WHERE ID=?", (qid,)).fetchone()
                self.assertEqual([v or "" for v in held], values)

    def test_level_11_has_omis_cut_both_stones_into_the_crediac(self):
        # Frund and Agisthil each drop a stone; Omis takes both (an "id;2" turn-in) and hands the Crediac, which goes
        # back to Captain Dillon. The six stages stay, so upstream's map markers still line up.
        ids = [qid for qid in self.chains["steps"]["11"]["ids"] if qid is not None]
        self.assertEqual(sorted(ids), [20155, 20156, 20157, 20158, 20159])
        for qid in ids:
            with self.subTest(quest=qid):
                self.assertEqual(self.conn.execute(
                    "SELECT StepType, StepItemTemplates, CollectItemTemplate FROM DataQuest WHERE ID=?", (qid,)).fetchone(),
                    ("4|0|0|10|0|3", "|cq_crediac_stone|cq_crediac_stone|cq_crediac||", "|||cq_crediac_stone;2||cq_crediac"))
        self.assertEqual(self.conn.execute(
            "SELECT Id_nb FROM ItemTemplate WHERE Id_nb IN ('cq_crediac_stone', 'cq_crediac') ORDER BY Id_nb").fetchall(),
            [("cq_crediac",), ("cq_crediac_stone",)])

    def test_every_giver_stands_in_its_region_and_the_shrouded_isles_7_and_11_come_from_the_class_trainer(self):
        # Compared without case, as quests match names (QuestNames.Same). Upstream named the Necromancer trainer Carys
        # as every class's giver of the Shrouded Isles 7 and 11 (owner test 2026-10-10).
        classes = list(self.chains["classes"])
        for entry in self.data["quests"]:
            if "step" not in entry:
                continue
            for name, qid in zip(classes, self.chains["steps"][entry["step"]]["ids"]):
                if qid is None:
                    continue
                giver, region = self.conn.execute("SELECT StartName, StartRegionID FROM DataQuest WHERE ID=?", (qid,)).fetchone()
                guilds = [guild for mob, guild in self.conn.execute("SELECT Name, Guild FROM Mob WHERE Region=?", (region,))
                          if mob.lower() == (giver or "").lower()]
                with self.subTest(quest=qid, giver=giver, region=region):
                    self.assertTrue(guilds, "no such mob in the region")
                    if entry["step"] in ("7si", "11si"):
                        self.assertIn(f"{name} Trainer", guilds)

    def test_each_11_needs_the_7_of_its_own_branch_and_both_lead_to_15(self):
        # Period rule (Allakhazam, 2004): who takes the Shrouded Isles 7 finishes the first class quests there, so the
        # Camelot 11 needs the Camelot 7 (either version) and the Shrouded Isles 11 the Shrouded Isles 7. Each closes
        # the other; the 15 is epic-chains-v1's.
        ids = [qid for key in ("11", "11si", "15") for qid in self.chains["steps"][key]["ids"]]
        marks = ", ".join("?" * len(ids))
        self.assertEqual(dict(self.conn.execute(f"SELECT ID, QuestDependency FROM DataQuest WHERE ID IN ({marks})", ids)), {
            20157: "#21500/21324|!#20469", 20155: "#21498/21322|!#20467", 20156: "#21499/21323|!#20468",
            20159: "#20497|!#20471", 20158: "#21501/21325|!#20470",
            20469: "#20478|!#20157", 20467: "#20476|!#20155", 20468: "#20477|!#20156", 20471: "#20480|!#20159",
            20470: "#20479|!#20158",
            20188: "#20157/20469", 20186: "#20155/20467", 20187: "#20156/20468", 20190: "#20159/20471",
            20189: "#20158/20470",
        })

    def test_a_description_that_names_the_accept_text_has_it_in_brackets(self):
        # The chain's own text. A classic quest keeps the period's ("Fort Veldon", then [Veldon] in a Chat reply).
        for qid in chain_ids(self.data, self.chains):
            accept, description, *_rest = self.rows[qid]
            if accept and accept.lower() in (description or "").lower():
                with self.subTest(quest=qid):
                    self.assertIn(f"[{accept}]", description)

    def test_every_quest_can_be_accepted_from_what_its_giver_says(self):
        # The giver's Description offers [keywords]; one is the AcceptText, or leads to it through our Chat replies
        # (level 25: [matter] -> [dispatch] -> [supporting]; level 43: [interested] -> [profitable], the trainers' reply
        # for it keyed "interested@<quest ID>", which ClassicQuests.ChatReply prefers while the player may take it). The
        # classic quests go on through upstream's Chat too: test_quest_reachability.py.
        with open(os.path.join(HERE, "..", "hearthdaoc-quests.json"), encoding="utf-8") as f:
            chat = json.load(f).get("Chat", {})
        for qid in chain_ids(self.data, self.chains):
            accept, description, giver = self.conn.execute(
                "SELECT AcceptText, Description, StartName FROM DataQuest WHERE ID=?", (qid,)).fetchone()
            replies = {k.lower(): v for k, v in chat.get(giver, {}).items()}
            offered, todo = set(), re.findall(r"\[([^\]]+)\]", description or "")
            while todo:
                keyword = todo.pop()
                if keyword not in offered:
                    offered.add(keyword)
                    reply = replies.get(f"{keyword.lower()}@{qid}", replies.get(keyword.lower(), ""))
                    todo.extend(re.findall(r"\[([^\]]+)\]", reply))
            with self.subTest(quest=qid, giver=giver):
                self.assertIn(accept, offered)

    def test_every_whisper_steps_advance_text_can_be_reached_from_its_target_text(self):
        # The whisper keyword is in the target's own text, or reached from it through our Chat replies (level 40:
        # [down to business] -> [Arawnites] -> [speak with Lieutenant Kuebler]).
        with open(os.path.join(HERE, "..", "hearthdaoc-quests.json"), encoding="utf-8") as f:
            chat = json.load(f).get("Chat", {})
        for qid in chain_ids(self.data, self.chains):
            _accept, _desc, _source, step_types, _steps, targets, advances, _finish = self.rows[qid]
            names = (self.conn.execute("SELECT TargetName FROM DataQuest WHERE ID=?", (qid,)).fetchone()[0] or "").split("|")
            types, targets, advances = step_types.split("|"), (targets or "").split("|"), (advances or "").split("|")
            for stage, step_type in enumerate(types):
                if step_type in ("6", "7"):
                    replies = {k.lower(): v for k, v in chat.get(names[stage].split(";")[0], {}).items()}
                    offered, todo = set(), re.findall(r"\[([^\]]+)\]", targets[stage])
                    while todo:
                        keyword = todo.pop()
                        if keyword not in offered:
                            offered.add(keyword)
                            todo.extend(re.findall(r"\[([^\]]+)\]", replies.get(keyword.lower(), "")))
                    with self.subTest(quest=qid, stage=stage + 1):
                        self.assertTrue(advances[stage])
                        self.assertIn(advances[stage], offered)

    def test_no_popup_text_is_longer_than_1000_characters(self):
        # The chain's own text. The classic quests keep upstream's texts, some of them longer (a name is never longer
        # than the <Player> it replaces).
        for qid in chain_ids(self.data, self.chains):
            accept, description, source, _types, steps, targets, _advances, finish = self.rows[qid]
            texts = [description, finish] + (source or "").split("|") + (steps or "").split("|") + (targets or "").split("|")
            for text in texts:
                with self.subTest(quest=qid):
                    self.assertLessEqual(len(text or ""), 1000, (text or "")[:60])


# The classic quests whose Description lost the line that offers their first keyword, and that line (the guides'
# words): level 5's "Cleric Mulgrut" (the owner's report: Hugh Gallen showed only his wares), "Evenings Empty
# Blessing" and "Better Off Buried".
LOST_LINES = {
    20207: "I have a [bit of information] you might be interested in should you wish to hear it.",
    21146: "It seems there is much amiss to the north around Fort Veldon. Kell sent word earlier that he required "
           "[information and assistance].",
    21187: "Welcome back. I have not seen you in a long time. I hope all has been [well] with you.",
}
# The names upstream's generator replaced with <Player> in the classic quests' texts.
PERIOD_NAMES = {"Askheim", "Averrius", "Catla", "Coplin", "Darrius", "Freya", "Gunnar", "Ibicus", "Jango", "Keriann",
                "Morana", "Nisse", "Ove", "Runil", "Thulin"}
# The plain words it took for names (Soul Hunt's "Now", Silver Run's "Well"), and the keyword [name] (Trapper's Pride's
# "What is your [name]?", Amora's Aid's "may I ask your [name]?").
PERIOD_WORDS = {"Now", "Well", "[name]"}
# The fixed stages that still speak to the player, and how many <Player> each keeps: Kaisa's "Come in, come in,
# <Player>" and "Good job <Player>!" ("Solving the Argument"), and Crace's "Well, <Player>, did you get the sporites?"
# and "I hope you find it useful, <Player>!" ("Silver Run").
ADDRESSES_THE_PLAYER = {(21142, "TargetText", 1): 3, (21142, "TargetText", 6): 3}
ADDRESSES_THE_PLAYER.update({(qid, "TargetText", stage): 2 for qid in (20288, 20289, 20290, 20291) for stage in (1, 5)})
# The class the guides' authors were called by, which upstream's generator kept as plain text, so every class of a quest
# open to others read the author's (class-word scan, 2026-10-11), and the guides' placeholders for it ("(class name)").
# The fix is <Class>, which the server replaces with the player's class (female names included). New Crest's accept
# keyword, which DataQuest compares as it is, is each row's own class instead (Runemaster at Etta Greavers,
# Spiritmaster at Palda; Teija's Bonedancer row stays). Each: the quests, the column, its stages, upstream's words, the
# fork's, and the class they name (eCharacterClass; None for a placeholder). Only these words change: a stage keeps
# upstream's <Player>.
CLASS_WORD_FIXES = [
    ((20008,), "TargetText", (1, 3),
     "I see, you're a fighter. Has Mistress Laws", "I see, you're a <Class>. Has Mistress Laws", 14),
    ((20009,), "TargetText", (1,),
     "Greetings young Disciple. What be thy name?", "Greetings young <Class>. What be thy name?", 20),
    ((20100,), "Description", (1,),
     "even more dangerous for a your Viking like you", "even more dangerous for a your <Class> like you", 35),
    ((20100,), "TargetText", (1, 3), "Lo, I see a young Viking before me.", "Lo, I see a young <Class> before me.", 35),
    ((20101,), "TargetText", (1, 3),
     "Mystic, here to do some [exploring]?", "<Class>, here to do some [exploring]?", 36),
    ((20101,), "TargetText", (1, 3),
     "Here you are! Good working with your Mystic.", "Here you are! Good working with your <Class>.", 36),
    ((20104,), "SourceText", (1,), "Ah a brave Mystic you are! Great!", "Ah a brave <Class> you are! Great!", 36),
    ((20192, 20193, 20195), "TargetText", (1, 4),
     "Greetings Friar. I see that your trainer received", "Greetings <Class>. I see that your trainer received", 10),
    ((20349,), "AcceptText", (1,), "Bonedancer", "Runemaster", 30),
    ((20349,), "Description", (1,),
     "Ah, [Bonedancer]. You've aided Karle before", "Ah, [Runemaster]. You've aided Karle before", 30),
    ((20350,), "AcceptText", (1,), "Bonedancer", "Spiritmaster", 30),
    ((20350,), "Description", (1,),
     "Ah, [Bonedancer]. You've aided Karle before", "Ah, [Spiritmaster]. You've aided Karle before", 30),
    ((20373,), "TargetText", (1,),
     "You look like a (your class here) with a purpose", "You look like a <Class> with a purpose", None),
    ((20639,), "TargetText", (2, 13), "Here, take these instructions to aid you. Good luck to thee Theurgist.",
     "Here, take these instructions to aid you. Good luck to thee <Class>.", 5),
    ((20702,), "TargetText", (1, 3, 6),
     "Bring me Caisha like a good little (minstrel)", "Bring me Caisha like a good little <Class>", None),
    ((20811,), "TargetText", (2, 3),
     "What can I do for you, fine Forester?", "What can I do for you, fine <Class>?", 57),
    ((21023, 21025, 21026, 21027), "FinishText", (1,), "I sent word to Elizabeth that a Berserker was helping me",
     "I sent word to Elizabeth that a <Class> was helping me", 31),
    ((21035, 21037), "Description", (1,),
     "Hail Spiritmaster! Many great adventures await you", "Hail <Class>! Many great adventures await you", 27),
    ((21035, 21037), "SourceText", (1,), "Good hourney to you Spiritmaster!", "Good hourney to you <Class>!", 27),
    ((21035, 21037), "TargetText", (4,), "You are indeed a great Spiritmaster! You don't have another do you?",
     "You are indeed a great <Class>! You don't have another do you?", 27),
    ((21096, 21098), "FinishText", (1,),
     "will be restored. Safe journey Spiritmaster.", "will be restored. Safe journey <Class>.", 27),
    ((21096, 21098), "TargetText", (1,), "I can assist you no more Spiritmaster. May the gods guard you",
     "I can assist you no more <Class>. May the gods guard you", 27),
    ((21282,), "Description", (1,),
     "Hello there Shaman. MightI interest you", "Hello there <Class>. MightI interest you", 28),
    ((21354,), "TargetText", (1, 12), "This is great (class name)!", "This is great <Class>!", None),
    ((21354,), "TargetText", (1, 12), "Good luck (class name)!", "Good luck <Class>!", None),
    ((21354,), "TargetText", (1, 12), "I welcome your return (class name).", "I welcome your return <Class>.", None),
]
CLASS_WORDS = {}  # (quest id, column, stage): [(upstream's words, the fork's)]
for _ids, _column, _stages, _old, _new, _class in CLASS_WORD_FIXES:
    for _qid in _ids:
        for _stage in _stages:
            CLASS_WORDS.setdefault((_qid, _column, _stage), []).append((_old, _new))
# The page upstream scraped with Mystemas's last line (Strange Bedfellows): the guide's reward, then the site's footer.
SCRAPED_PAGE = (" Reward: Perfect Life Stone Free account required to post You must log in or create an account to post "
                "messages. Subscribe Privacy Policy Terms of Service Forum Rules Featured Game Sites HEARTHSTONE Top Decks "
                "Database Sites Wowhead EverQuest EverQuest II Addon Sites MMOUI WowInterface ESOUI RiftUI SWTORUI "
                "EQInterface EQ2Interface LOTROInterface CWMods SecretUI Community Sites Wowhead Forums Join the world's "
                "largest MMO gaming network. No account? Sign up now! Connect With Fanbyte \u00a9 2026 Fanbyte LLC")
BILIOUS_NOTE = "Allakhazam spells the monster 'billious goo'; the server's monster is 'bilious goo' (same creature, Dales of Devwy)."
YEARLING_NOTE = "Allakhazam: the yearlings live in the Plains of Gwyddneau (level 42-44)."
# Other leftovers of the period guides that upstream's generator copied into the texts (2026-10-11): the guides'
# placeholders for the player's class ("(character class)") and name ("(your name here)", and Gavon Montgomery's
# whisper keyword "<your name>" in The Lost Stone, which no whisper matched), now <Class> and <Player>; the web page
# scraped after Mystemas's last line, cut (the guide's line ends there, without a stop); and the kill tasks' editors'
# notes on Allakhazam, now a plain hint. Each: the quests, the column, its stages, upstream's words, the fork's.
LEFTOVER_FIXES = [
    ((20071,), "Description", (1,), "Blessings upon you this day, noble (character class).",
     "Blessings upon you this day, noble <Class>."),
    ((20192, 20193, 20194, 20195), "AdvanceText", (1,), "<your name>", "<Player>"),
    ((20192, 20193, 20194, 20195), "SourceText", (1,), "(whisper: <your name>)", "(whisper: <Player>)"),
    ((20192, 20193, 20194, 20195), "StepText", (1,), "(whisper: <your name>)", "(whisper: <Player>)"),
    ((20694,), "SourceText", (1,), BILIOUS_NOTE, "Bilious goo are found in the Dales of Devwy."),
    ((20694,), "StepText", (1,), BILIOUS_NOTE, "Bilious goo are found in the Dales of Devwy."),
    ((20695,), "SourceText", (1,), YEARLING_NOTE, "The yearlings live in Gwyddneau."),
    ((20695,), "StepText", (1,), YEARLING_NOTE, "The yearlings live in Gwyddneau."),
    ((20702,), "TargetText", (1, 3, 6), "ugly (your characters race)?", "ugly <Race>?"),
    ((20702,), "TargetText", (1, 3, 6), SCRAPED_PAGE, ""),
    (tuple(range(20983, 20995)), "Description", (1,), "(your name here), it is time", "<Player>, it is time"),
    ((21397,), "TargetText", (2, 4), "You're a brave (character class), to have", "You're a brave <Class>, to have"),
]
LEFTOVER_WORDS = {}  # (quest id, column, stage): [(upstream's words, the fork's)]
for _ids, _column, _stages, _old, _new in LEFTOVER_FIXES:
    for _qid in _ids:
        for _stage in _stages:
            LEFTOVER_WORDS.setdefault((_qid, _column, _stage), []).append((_old, _new))
# Every listed change but the <Player> slots: the class words first, then the leftovers.
FIXED_WORDS = {key: CLASS_WORDS.get(key, []) + LEFTOVER_WORDS.get(key, []) for key in {*CLASS_WORDS, *LEFTOVER_WORDS}}
TEXT_COLUMNS = ("AcceptText", "Description", "SourceText", "StepText", "TargetText", "AdvanceText", "FinishText")
# The guides' placeholders for the player's class, name and race: no text may hold one (compared without case).
# test_quest_reachability checks the Chat against the same lists.
GUIDE_PLACEHOLDERS = ("(character class)", "(class name)", "(your class here)", "(your name here)", "<your name>",
                      "(player name)", "(your characters race)", "(your character's race)", "(your race)")
# A web page's text, and the site the guides were taken from: no one's words in the world.
SCRAPED_WORDS = ("Free account required", "You must log in", "Fanbyte", "Privacy Policy", "Allakhazam")
BEHAVIOUR_UTILS = os.path.join(HERE, "..", "..", "source", "server", "GameServer", "behaviour", "BehaviourUtils.cs")
DATA_QUEST = os.path.join(HERE, "..", "..", "source", "server", "GameServer", "quests", "QuestsMgr", "DataQuest.cs")


def server_tokens():
    """The tokens BehaviourUtils.GetPersonalizedMessage replaces in what the server sends: <Player>, <Class>, ..."""
    with open(BEHAVIOUR_UTILS, encoding="utf-8-sig") as f:
        return set(re.findall(r'"(<[A-Za-z]+>)"', f.read()))


def with_class_words(text, words):
    """`text` with each (upstream's words, the fork's) pair of `words` replaced; upstream's words are there once."""
    for old, new in words:
        if text.count(old) != 1:
            raise AssertionError(f"{old!r} is in the text {text.count(old)} times, not once")
        text = text.replace(old, new)
    return text


def disabled_classes(conn):
    """The class IDs the world's disabled_classes server property names ("33;34;39;58-62"): no one plays them."""
    value, = conn.execute("SELECT Value FROM ServerProperty WHERE `Key`='disabled_classes'").fetchone()
    out = set()
    for part in (value or "").split(";"):
        first, _, last = part.strip().partition("-")
        if first:
            out |= set(range(int(first), int(last or first) + 1))
    return out


@unittest.skipUnless(TEST_WORLD, "needs HDC_TEST_WORLD (a clean classic world database)")
class ClassicQuestTextTests(unittest.TestCase):
    """The file's ids entries (the classic quests) on a copy of a clean classic world, against upstream's text."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "world.db")
        shutil.copyfile(TEST_WORLD, cls.db)
        wf.apply(cls.db)
        cls.conn = sqlite3.connect(cls.db)
        cls.clean = sqlite3.connect(f"file:{TEST_WORLD}?mode=ro", uri=True)
        cls.changed = {}  # (quest id, column, stage): (upstream's text, the fixed text)
        for entry in qd.load_data()["quests"]:
            for qid in entry.get("ids", []):
                for column in entry["set"]:
                    query = f"SELECT {column} FROM DataQuest WHERE ID=?"
                    before = (cls.clean.execute(query, (qid,)).fetchone()[0] or "").split("|")
                    after = (cls.conn.execute(query, (qid,)).fetchone()[0] or "").split("|")
                    assert len(before) == len(after), (qid, column)
                    for stage, (old, new) in enumerate(zip(before, after), 1):
                        if old != new:
                            cls.changed[(qid, column, stage)] = (old, new)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.clean.close()
        cls.tmp.cleanup()

    def test_the_lost_lines_follow_upstreams_descriptions(self):
        for qid, line in LOST_LINES.items():
            with self.subTest(quest=qid):
                old, new = self.changed[(qid, "Description", 1)]
                self.assertEqual(new, f"{old} {line}")

    def test_every_other_text_is_upstreams_with_period_names_and_words_for_player(self):
        # Only the <Player> slots, the class words and the guides' leftovers change; every other character stays
        # upstream's.
        names = set()
        for (qid, column, stage), (old, new) in self.changed.items():
            if column == "Description" and qid in LOST_LINES:
                continue
            with self.subTest(quest=qid, column=column, stage=stage):
                old = with_class_words(old, FIXED_WORDS.get((qid, column, stage), []))
                slots = "|".join(re.escape(slot) for slot in ["<Player>"] + sorted(PERIOD_NAMES | PERIOD_WORDS))
                match = re.fullmatch(f"({slots})".join(re.escape(part) for part in old.split("<Player>")), new)
                self.assertTrue(match, new)
                names |= set(match.groups())
        self.assertEqual(names - {"<Player>"}, PERIOD_NAMES | PERIOD_WORDS)
        # Names: 37 stages of 21 texts; words: 27 stages of 4 texts (Silver Run's and Amora's Aid's in every class
        # row); class words: 44 stages of 24 rows of 16 quests, none of them among the others; the guides' leftovers:
        # 31 more stages of 20 rows (Strange Bedfellows' 3 are among the class words').
        self.assertEqual(len(self.changed), 37 + 27 + len(LOST_LINES) + 44 + 31)

    def test_no_fixed_text_still_says_player(self):
        # A stage changed for its listed words alone keeps upstream's <Player> (a class said as a title is <Player>
        # there, which the owner left for later: issues #101-#103), plus the guides' placeholders for the player's
        # name, which are <Player> now.
        for (qid, column, stage), (old, new) in self.changed.items():
            with self.subTest(quest=qid, column=column, stage=stage):
                words = FIXED_WORDS.get((qid, column, stage), [])
                if new == with_class_words(old, words):
                    placeholders = sum(fork.count("<Player>") - guide.count("<Player>") for guide, fork in words)
                    self.assertEqual(new.count("<Player>"), old.count("<Player>") + placeholders)
                else:
                    self.assertEqual(new.count("<Player>"), ADDRESSES_THE_PLAYER.get((qid, column, stage), 0))

    def test_the_class_the_guides_authors_were_called_by_is_the_players(self):
        # Gral Bermorn's "Good luck to thee Theurgist." (Weakened Bonds, open to every class), the Mages' and
        # Elementalists' "Greetings young Disciple", the guides' "(class name)" in Fall of an Emperor, ...
        for key in CLASS_WORDS:
            with self.subTest(quest=key[0], column=key[1], stage=key[2]):
                self.assertTrue(key in self.changed, "the fix does not change this stage")
                old, new = self.changed[key]
                self.assertEqual(new, with_class_words(old, FIXED_WORDS[key]))

    def test_no_quest_text_shows_a_class_word_the_fork_fixed_to_another_class(self):
        # The guard, over every quest row of the world: a text that still has the guides' words is offered to their
        # class alone, or to classes no one plays (disabled_classes: Dark Essence's Valkyrie row, Siv's Spirit's
        # Warlock row). The Friar's Lost Stone, Teija's New Crest, the Spiritmaster's Grenlock Clan and Siv's Spirit
        # and the Berserker's Dark Essence keep them. A placeholder is offered to no one. New Crest's accept keyword, a
        # class name alone, is checked by test_quest_reachability.py.
        disabled = disabled_classes(self.conn)
        rows = self.conn.execute(f"SELECT ID, AllowedClasses, {', '.join(TEXT_COLUMNS)} FROM DataQuest").fetchall()
        shown, kept = [], set()
        for _ids, column, _stages, old, _new, cls in CLASS_WORD_FIXES:
            if column == "AcceptText":
                continue
            for qid, allowed, *texts in rows:
                if any(old in (text or "") for text in texts):
                    classes = {int(c) for c in (allowed or "").split("|") if c}
                    if cls is None or not classes or not classes <= {cls} | disabled:
                        shown.append((qid, old))
                    else:
                        kept.add(qid)
        self.assertEqual(shown, [])
        self.assertEqual(sorted(kept), [20194, 20351, 21024, 21028, 21036, 21097, 21099])

    def test_the_guides_leftovers_are_fixed(self):
        for key, words in LEFTOVER_WORDS.items():
            with self.subTest(quest=key[0], column=key[1], stage=key[2]):
                self.assertTrue(key in self.changed, "the fix does not change this stage")
                old, new = self.changed[key]
                self.assertEqual(new, with_class_words(old, FIXED_WORDS[key]))

    def stage(self, qid, column, stage):
        text, = self.conn.execute(f"SELECT {column} FROM DataQuest WHERE ID=?", (qid,)).fetchone()
        return (text or "").split("|")[stage - 1]

    def test_cristin_and_tethra_call_the_player_by_their_class(self):
        # The guides' "(character class)" (Cristin's Supplies, Spicket, Spackit and Spykit; both open to every class).
        self.assertTrue(self.stage(20071, "Description", 1).startswith(
            "Blessings upon you this day, noble <Class>. I have the finest wares in all of Connacht"))
        for stage in (2, 4):
            with self.subTest(stage=stage):
                text = self.stage(21397, "TargetText", stage)
                self.assertIn("I suppose it matters not. You're a brave <Class>, to have defeated this infamous "
                              "spraggon. Have you defeated [many more]?", text)
                self.assertEqual(text.count("<Player>"), 2)

    def test_the_traveler_s_way_trainers_send_the_player_out_by_name(self):
        # The guide's "(your name here)", in every class's row (Midgard).
        for qid in range(20983, 20995):
            with self.subTest(quest=qid):
                self.assertEqual(self.stage(qid, "Description", 1),
                                 "<Player>, it is time to send you out into the lands beyond ours. Explore these other "
                                 "lands and tell them of our house's good will and [aid those we can].")

    def test_gavon_montgomery_is_told_the_players_name(self):
        # The guide: "When he asks, tell him your name." Stage 1 is a whisper step at Gavon Montgomery: the player
        # whispers the name the server puts for <Player> (QuestWhispers.Advances), which the journal shows.
        for qid in (20192, 20193, 20194, 20195):
            with self.subTest(quest=qid):
                self.assertEqual(self.stage(qid, "StepType", 1), "6")
                self.assertEqual(self.stage(qid, "AdvanceText", 1), "<Player>")
                for column in ("SourceText", "StepText"):
                    self.assertEqual(self.stage(qid, column, 1),
                                     "Seek out Gavon Montgomery at Caifelle. (whisper: <Player>)")
                self.assertIn(" What is your name? We have quite a task ahead of us.", self.stage(qid, "TargetText", 1))
        self.assertTrue(self.stage(20194, "TargetText", 1).startswith("Greetings Friar. "))

    def test_mystemas_s_last_line_ends_where_the_guide_s_does(self):
        # The guide's line has no stop after "(minstrel)"; the page around it is no one's words.
        for stage in (1, 3, 6):
            with self.subTest(stage=stage):
                self.assertTrue(self.stage(20702, "TargetText", stage).endswith(
                    "Do you [Understand] me? Good. Now get going before someone sees us talking. Bring me Caisha like a "
                    "good little <Class>"))

    def test_the_kill_tasks_say_where_without_the_editors_notes(self):
        for qid, text in ((20694, "Kill bilious goo and bring Achae Smith the Billious Goo Piece. Bilious goo are found "
                                  "in the Dales of Devwy."),
                          (20695, "Kill cliff yale yearling and bring Wenthian Sy'Lian the Cliff Yale Yearling Essence. "
                                  "The yearlings live in Gwyddneau.")):
            for column in ("SourceText", "StepText"):
                with self.subTest(quest=qid, column=column):
                    self.assertEqual(self.stage(qid, column, 1), text)

    def test_no_quest_text_holds_a_guides_placeholder(self):
        # The guard, over every quest row of the world, whatever classes it is open to.
        rows = self.conn.execute(f"SELECT ID, {', '.join(TEXT_COLUMNS)} FROM DataQuest").fetchall()
        held = [(qid, column, placeholder) for qid, *texts in rows for column, text in zip(TEXT_COLUMNS, texts)
                for placeholder in GUIDE_PLACEHOLDERS if placeholder in (text or "").lower()]
        self.assertEqual(held, [])

    def test_no_quest_text_holds_a_web_page_or_names_its_site(self):
        rows = self.conn.execute(f"SELECT ID, {', '.join(TEXT_COLUMNS)} FROM DataQuest").fetchall()
        held = [(qid, column, words) for qid, *texts in rows for column, text in zip(TEXT_COLUMNS, texts)
                for words in SCRAPED_WORDS if words.lower() in (text or "").lower()]
        self.assertEqual(held, [])

    def test_a_whisper_keyword_holds_no_token_the_server_does_not_replace(self):
        # A whisper step's AdvanceText may hold a token the server replaces (<Player>: the player's name), which
        # DataQuest matches as the player reads it (QuestWhispers.Advances). Any other <...> stays as it is, so no
        # whisper matches it. An accept keyword is compared as it is (CheckOfferedQuestWhisper): no token at all.
        tokens = server_tokens()
        self.assertLessEqual({"<Player>", "<Class>", "<Race>"}, tokens)
        unknown = []
        for qid, step_types, advances, accept in self.conn.execute(
                "SELECT ID, StepType, AdvanceText, AcceptText FROM DataQuest"):
            advances = (advances or "").split("|")
            for stage, step_type in enumerate((step_types or "").split("|"), 1):
                if step_type.strip() in ("6", "7") and stage <= len(advances):
                    unknown += [(qid, stage, token) for token in re.findall(r"<[^<>]*>", advances[stage - 1])
                                if token not in tokens]
            unknown += [(qid, "AcceptText", token) for token in re.findall(r"<[^<>]*>", accept or "")]
        self.assertEqual(unknown, [])


class WhisperKeywordSourceTests(unittest.TestCase):
    """DataQuest matches a whisper step's AdvanceText as the player reads it (source check: a unit test would need a
    live player; the comparison itself is UT_DataQuestWhisper's)."""

    def test_on_player_whisper_personalizes_the_advance_text(self):
        with open(DATA_QUEST, encoding="utf-8-sig") as f:
            source = f.read()
        body = source.split("public virtual void OnPlayerWhisper(GamePlayer p, GameObject obj, string text)", 1)[1]
        body = body.split("\n\t\t}", 1)[0]
        self.assertIn("QuestWhispers.Advances(AdvanceText, BehaviourUtils.GetPersonalizedMessage(AdvanceText, p), text)",
                      body)
        self.assertNotIn("AdvanceText == text", body)


@unittest.skipUnless(TEST_WORLD, "needs HDC_TEST_WORLD (a clean classic world database)")
class DigestCommandTests(unittest.TestCase):
    """--digests on a clean world prints upstream's text's digests, as the guard lists hold them; with --current, the
    digests of the file's own text."""

    def test_the_digests_are_those_of_the_worlds_rows_after_the_epic_chains(self):
        data, chains = real_data()
        out = qd.digests(TEST_WORLD, data, chains)
        self.assertEqual(sorted(out), sorted(qd.label(entry) for entry in data["quests"]))
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "world.db")
            shutil.copyfile(TEST_WORLD, copy)
            conn = sqlite3.connect(copy)
            with conn:
                epic_chains.apply(conn)
            for entry in data["quests"]:
                columns = sorted(entry["set"])
                for qid, d in out[qd.label(entry)].items():
                    row = conn.execute(f"SELECT {', '.join(columns)} FROM DataQuest WHERE ID=?", (int(qid),)).fetchone()
                    self.assertEqual(d, qd.digest(list(row)))
            conn.close()
        self.assertTrue(all(d in entry["guard"][qid] for entry in data["quests"]
                            for qid, d in out[qd.label(entry)].items()))

    def test_current_prints_the_digests_of_the_files_own_text(self):
        data, chains = real_data()
        out = qd.digests(TEST_WORLD, data, chains, current=True)
        printed = {int(qid): d for step in out.values() for qid, d in step.items()}
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "world.db")
            shutil.copyfile(TEST_WORLD, copy)
            conn = sqlite3.connect(copy)
            with conn:
                epic_chains.apply(conn)
            planned = {qid: qd.digest(values) for qid, _columns, values, _guard in qd._plan(conn, data, chains)}
            conn.close()
        self.assertEqual(printed, planned)


class DigestCliTests(unittest.TestCase):
    """The --digests command on a synthetic world, with a data file of its own."""

    def test_it_prints_the_digests_of_the_sets_columns_and_leaves_the_world_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "world.db")
            with sqlite3.connect(db) as c:
                c.execute(SCHEMA)
                c.execute("INSERT INTO DataQuest (ID, StepType, Description, FinishText) VALUES (100, '2|3', 'old A', 'bye')")
                c.execute("INSERT INTO DataQuest (ID, StepType, Description) VALUES (300, '2', NULL)")
            data = {"quests": [{"step": "7", "set": {"FinishText": "x", "Description": "y"}},
                               {"step": "9", "set": {"Description": "z"}}]}
            before = pathlib.Path(db).read_bytes()
            out = qd.digests(db, data, CHAINS)
            self.assertEqual(pathlib.Path(db).read_bytes(), before)
        self.assertEqual(out, {"7": {"100": qd.digest(["old A", "bye"])}, "9": {"300": qd.digest([""])}})

    def test_an_ids_entry_is_printed_under_its_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "world.db")
            with sqlite3.connect(db) as c:
                c.execute(SCHEMA)
                c.execute("INSERT INTO DataQuest (ID, StepType, Description, FinishText) VALUES (100, '2|3', 'old A', 'bye')")
                c.execute("INSERT INTO DataQuest (ID, StepType, Description, FinishText) VALUES (200, '2|3', 'old B', 'bye')")
            out = qd.digests(db, {"quests": [{"ids": [200, 100], "set": {"FinishText": "x"}}]}, CHAINS)
        self.assertEqual(out, {"ids 200, 100": {"200": qd.digest(["bye"]), "100": qd.digest(["bye"])}})


def apply_file(db, data):
    conn = sqlite3.connect(db)
    try:
        with conn:
            return qd.apply(conn, NOW, data, CHAINS)
    finally:
        conn.close()


def held(db):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT ID, Description, FinishText FROM DataQuest ORDER BY ID").fetchall()
    finally:
        conn.close()


class RevisionTests(unittest.TestCase):
    """The documented revision procedure: before changing the text, `--digests <clean world> --current`, and each
    digest appended to its quest's guard list; then the new text. A world at the earlier revision gets the new one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clean = os.path.join(self.tmp.name, "clean.db")
        conn = sqlite3.connect(self.clean)
        with conn:
            conn.execute(SCHEMA)
            conn.execute("INSERT INTO DataQuest (ID, StepType, Description, FinishText) VALUES (100, '2|3', 'old A', 'bye')")
            conn.execute("INSERT INTO DataQuest (ID, StepType, Description, FinishText) VALUES (200, '2|3', 'old B', 'bye')")
        conn.close()
        self.upstream = {"100": [guard_for("old A", "bye")], "200": [guard_for("old B", "bye")]}
        self.revision = {"quests": [{"step": "7", "set": {"Description": {"Alpha": "new A", "Beta": "new B"},
                                                          "FinishText": "farewell"},
                                     "guard": self.upstream}]}
        self.world = os.path.join(self.tmp.name, "world.db")  # a world that had this revision
        shutil.copyfile(self.clean, self.world)
        self.assertEqual(apply_file(self.world, self.revision), ["Quest dialogue: 2 quests rewritten"])

    def tearDown(self):
        self.tmp.cleanup()

    def next_revision(self, added):
        guard = {qid: digests + [added[qid]] for qid, digests in self.upstream.items()}
        return {"quests": [{"step": "7", "set": {"Description": {"Alpha": "newer A", "Beta": "newer B"},
                                                 "FinishText": "farewell"},
                            "guard": guard}]}

    def test_current_prints_the_digests_of_the_files_own_text_and_leaves_the_world_alone(self):
        before = pathlib.Path(self.clean).read_bytes()
        out = qd.digests(self.clean, self.revision, CHAINS, current=True)
        self.assertEqual(pathlib.Path(self.clean).read_bytes(), before)
        self.assertEqual(out, {"7": {"100": guard_for("new A", "farewell"), "200": guard_for("new B", "farewell")}})

    def test_a_revision_guarded_by_the_current_digests_rewrites_every_row(self):
        current = qd.digests(self.clean, self.revision, CHAINS, current=True)["7"]
        self.assertEqual(apply_file(self.world, self.next_revision(current)), ["Quest dialogue: 2 quests rewritten"])
        self.assertEqual(held(self.world), [(100, "newer A", "farewell"), (200, "newer B", "farewell")])

    def test_a_revision_guarded_by_the_clean_worlds_digests_alone_keeps_every_row(self):
        # Without --current, a clean world gives upstream's digests again: the earlier revision's text stays.
        clean = qd.digests(self.clean, self.revision, CHAINS)["7"]
        self.assertEqual(clean, {qid: digests[0] for qid, digests in self.upstream.items()})
        before = held(self.world)
        self.assertEqual(apply_file(self.world, self.next_revision(clean)), ["Quest dialogue: 2 left as they are (their text differs from upstream's and this file's): 100, 200"])
        self.assertEqual(held(self.world), before)

    def test_current_is_an_error_when_a_row_would_keep_another_text(self):
        unguarded = json.loads(json.dumps(self.revision))
        unguarded["quests"][0]["guard"]["200"] = []
        with self.assertRaisesRegex(RuntimeError, "quest 200 does not hold the file's text"):
            qd.digests(self.clean, unguarded, CHAINS, current=True)

    def test_the_command_takes_current(self):
        out = io.StringIO()
        with unittest.mock.patch.object(qd, "load_data", return_value=self.revision), \
                unittest.mock.patch.object(epic_chains, "load_data", return_value=CHAINS), \
                contextlib.redirect_stdout(out):
            self.assertEqual(qd.main(["--digests", self.clean, "--current"]), 0)
        self.assertEqual(json.loads(out.getvalue()),
                         {"7": {"100": guard_for("new A", "farewell"), "200": guard_for("new B", "farewell")}})


class SealTests(unittest.TestCase):
    """--seal on a temp copy of a small synthetic file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "quest_dialogue.json")
        self.clean = os.path.join(self.tmp.name, "clean.db")
        conn = sqlite3.connect(self.clean)
        with conn:
            conn.execute(SCHEMA)
            conn.execute("INSERT INTO DataQuest (ID, StepType, Description, FinishText) VALUES (100, '2|3', 'old A', 'bye')")
            conn.execute("INSERT INTO DataQuest (ID, StepType, Description, FinishText) VALUES (200, '2|3', 'old B', 'bye')")
        conn.close()
        self.upstream = {"100": [guard_for("old A", "bye")], "200": [guard_for("old B", "bye")]}

    def tearDown(self):
        self.tmp.cleanup()

    def dump(self, data):
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")

    def write(self, description):
        self.dump({"_about": "x \u00e9", "quests": [
            {"step": "7", "set": {"Description": description, "FinishText": "farewell"},
             "guard": json.loads(json.dumps(self.upstream))}]})

    def seal(self):
        return qd.seal(self.path, CHAINS)

    def test_it_appends_the_current_digests_once_and_is_byte_identical_the_second_time(self):
        self.write({"Alpha": "new A", "Beta": "new B"})
        self.assertEqual(self.seal(), ["100", "200"])
        sealed = pathlib.Path(self.path).read_bytes()
        guard = json.loads(sealed)["quests"][0]["guard"]
        self.assertEqual(guard["100"], self.upstream["100"] + [guard_for("new A", "farewell")])
        self.assertEqual(guard["200"], self.upstream["200"] + [guard_for("new B", "farewell")])
        self.assertEqual(self.seal(), [])
        self.assertEqual(pathlib.Path(self.path).read_bytes(), sealed)

    def test_unsealed_names_the_quests_until_the_file_is_sealed(self):
        self.write({"Alpha": "new A", "Beta": "new B"})
        self.assertEqual(qd.unsealed(qd.load_data(self.path), CHAINS), ["100", "200"])
        self.seal()
        self.assertEqual(qd.unsealed(qd.load_data(self.path), CHAINS), [])

    def test_a_world_at_revision_n_gets_revision_n_plus_1_after_seal(self):
        self.write({"Alpha": "new A", "Beta": "new B"})
        self.seal()
        world = os.path.join(self.tmp.name, "world.db")
        shutil.copyfile(self.clean, world)
        self.assertEqual(apply_file(world, qd.load_data(self.path)), ["Quest dialogue: 2 quests rewritten"])
        self.assertEqual(held(world), [(100, "new A", "farewell"), (200, "new B", "farewell")])
        data = qd.load_data(self.path)  # revision N+1: edit the text only, then seal
        data["quests"][0]["set"]["Description"] = {"Alpha": "newer A", "Beta": "newer B"}
        self.dump(data)
        self.seal()
        self.assertEqual(apply_file(world, qd.load_data(self.path)), ["Quest dialogue: 2 quests rewritten"])
        self.assertEqual(held(world), [(100, "newer A", "farewell"), (200, "newer B", "farewell")])

    def test_an_ids_entry_is_sealed_for_each_of_its_quests(self):
        self.dump({"quests": [{"ids": [100, 200], "set": {"Description": "new", "FinishText": "farewell"},
                               "guard": json.loads(json.dumps(self.upstream))}]})
        self.assertEqual(qd.unsealed(qd.load_data(self.path), CHAINS), ["100", "200"])
        self.assertEqual(self.seal(), ["100", "200"])
        self.assertEqual(qd.unsealed(qd.load_data(self.path), CHAINS), [])
        guard = qd.load_data(self.path)["quests"][0]["guard"]
        self.assertEqual(guard["200"], self.upstream["200"] + [guard_for("new", "farewell")])
        world = os.path.join(self.tmp.name, "world.db")
        shutil.copyfile(self.clean, world)
        self.assertEqual(apply_file(world, qd.load_data(self.path)), ["Quest dialogue: 2 quests rewritten"])
        self.assertEqual(held(world), [(100, "new", "farewell"), (200, "new", "farewell")])

    def test_the_command_needs_seal_or_digests(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            qd.main([])


if __name__ == "__main__":
    unittest.main()

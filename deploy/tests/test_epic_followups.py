"""The Guild of Shadows epic follow-ups (owner 2026-10-13, after the in-game check of the spots): #121 Captain Rhodri,
Lt. Brude and Lt. Cian on Snowdonia Fortress's north wall and Sir Tilian in Castle Sauvage's north-west corner, with
the map markers on their old spots; #126 the supply run's first step at Bline Tengit; #124 Martley appearing at the
single-tent camp; #119 the linked camps' data.

The world tests run world_fixes on a copy of a clean classic world (HDC_TEST_WORLD) and read upstream's
classic-quests.json (HDC_CLASSIC_QUESTS) merged with the fork's file, as ClassicQuests merges them (the moved markers
included); LinkedCamps' own decisions are unit-tested (Tests/UnitTests/UT_LinkedCamps.cs).
"""
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(DEPLOY, "bin"))

import world_fixes as wf  # noqa: E402
from tests.test_quest_reachability import EXTRA_QUESTS, TEST_WORLD, UPSTREAM_QUESTS  # noqa: E402

RHODRI = "45d3ac8c-b693-4acf-af70-e0f36585e1d4"
BRUDE = "44da6de7-96b4-4a58-b33d-202220d99463"
CIAN = "68b26ff8-6003-5b14-9b56-01a33a205e0a"
TILIAN = "9c99cb1d-193c-495e-9bb6-0720fa9a472e"
TENGIT = "ceafe623-f37f-4b4e-a00b-954d15ca238e"
GENERATED_BLINE = "97c5b723-b48d-50a5-b4a2-d7fe0f0cd73e"
STANDING_MARTLEY = "b94c9ac2-ba75-493e-a90c-65a5c62a839e"
COURIER = "29945a96-6a08-51f5-8df9-f63612026614"
WIZARDESS = "80e60247-caa8-465d-bbba-dcbb22f6cfc1"
OLD = {"rhodri": (1, 528239, 359818, 9088), "tilian": (1, 586282, 476329, 3480), "bline": (1, 508535, 477271, 2284),
       "brude": (1, 528519, 359799, 9088)}
SUPPLY_RUN = [21500, 21498, 21499, 20497, 21501]
SHADES = [20467, 20468, 20469, 20470, 20471, 20472]


def merged_quests(move=True):
    """{quest id: steps}: upstream's file with the fork's entries and (with move) its moved markers, as
    ClassicQuests.Merge builds it."""
    with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
        quests = {int(k): v for k, v in json.load(f)["Quests"].items()}
    with open(EXTRA_QUESTS, encoding="utf-8") as f:
        extra = json.load(f)
    for qid, info in extra["Quests"].items():
        if info.get("Replace") or int(qid) not in quests:
            quests[int(qid)] = info
    for steps in (q.get("Steps") or [] for q in quests.values() if move):
        for step in steps:
            for move in extra.get("MovedMarkers", []):
                if step and step.get("Marker") == move["From"]:
                    step["Marker"] = move["To"]
    return quests, extra


def point(marker):
    return marker["Region"], marker["X"], marker["Y"], marker["Z"]


@unittest.skipUnless(TEST_WORLD and UPSTREAM_QUESTS,
                     "needs HDC_TEST_WORLD (a clean classic world) and upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
class EpicFollowupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "world.db")
        shutil.copyfile(TEST_WORLD, cls.db)
        wf.apply(cls.db)
        cls.conn = sqlite3.connect(cls.db)
        cls.quests, cls.extra = merged_quests()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def mob(self, mob_id, *columns):
        return self.conn.execute(f"SELECT {', '.join(columns)} FROM Mob WHERE Mob_ID=?", (mob_id,)).fetchone()

    def markers(self):
        return [(qid, n, point(step["Marker"])) for qid, info in self.quests.items()
                for n, step in enumerate(info.get("Steps") or []) if step and step.get("Marker")]

    # #121
    def test_rhodri_and_his_lieutenants_stand_on_the_north_wall(self):
        self.assertEqual(self.mob(RHODRI, "Region", "X", "Y", "Z", "Heading"), (1, 528411, 358139, 9200, 0))
        self.assertEqual(self.mob(BRUDE, "Region", "X", "Y", "Z", "Heading"), (1, 528322, 358021, 9200, 0))
        self.assertEqual(self.mob(CIAN, "Name", "Region", "X", "Y", "Z", "Level", "Realm", "NPCTemplateID"),
                         ("Lieutenant Cian", 1, 528649, 357937, 9200, 49, 1, -1))
        self.assertEqual(self.mob(CIAN, "Model", "EquipmentTemplateID"), self.mob(BRUDE, "Model", "EquipmentTemplateID"))

    def test_tilian_stands_in_the_north_west_corner(self):
        self.assertEqual(self.mob(TILIAN, "Region", "X", "Y", "Z"), (1, 583943, 476323, 3480))

    def test_no_marker_is_left_on_a_moved_npcs_old_spot(self):
        spots = [m[2] for m in self.markers()]
        for name, old in OLD.items():
            with self.subTest(name):
                self.assertNotIn(old, spots)
        unmoved, _ = merged_quests(move=False)
        before = [point(step["Marker"]) for info in unmoved.values() for step in info.get("Steps") or [] if step and step.get("Marker")]
        for old, new in ((OLD["rhodri"], (1, 528411, 358139, 9200)), (OLD["tilian"], (1, 583943, 476323, 3480))):
            with self.subTest(old=old):
                self.assertGreater(before.count(old), 50)  # Rhodri's and Tilian's markers, in many quests
                self.assertEqual(spots.count(new), before.count(old) + before.count(new))

    def test_brudes_quests_point_at_him_on_the_wall(self):
        # Lt. Brude gives level 5 "Simple Request" and level 10 "Departed Hero"; both end at him.
        brude = self.mob(BRUDE, "Region", "X", "Y", "Z")
        for qid in (20018, 20025):
            with self.subTest(qid):
                self.assertEqual(point(self.quests[qid]["Steps"][2]["Marker"]), brude)

    # #126
    def test_the_supply_run_starts_at_bline_tengit(self):
        tengit = self.mob(TENGIT, "Region", "X", "Y", "Z")
        for qid in SUPPLY_RUN:
            target, = self.conn.execute("SELECT TargetName FROM DataQuest WHERE ID=?", (qid,)).fetchone()
            with self.subTest(qid):
                self.assertEqual(target.split("|")[0], "Bline Tengit;1")
                self.assertEqual(point(self.quests[qid]["Steps"][1]["Marker"]), tengit)
        source, step = self.conn.execute("SELECT SourceText, StepText FROM DataQuest WHERE ID=21500").fetchone()
        self.assertIn("Bline Tengit", source.split("|")[0])
        self.assertIn("Bline Tengit", step.split("|")[0])

    def test_the_generated_bline_and_the_standing_martley_are_archived(self):
        for mob_id in (GENERATED_BLINE, STANDING_MARTLEY):
            with self.subTest(mob_id):
                self.assertIsNone(self.mob(mob_id, "Name"))
                self.assertIsNotNone(self.conn.execute("SELECT 1 FROM fork_removed_mobs WHERE Mob_ID=?", (mob_id,)).fetchone())

    # #124
    def test_martley_appears_at_the_single_tent_camp(self):
        camp = self.conn.execute("SELECT AVG(X), AVG(Y) FROM Mob WHERE Region=51 AND lower(Name)='drakoran neophyte' "
                                 "AND abs(X-496491) < 3000 AND abs(Y-519855) < 3000").fetchone()
        for qid in SHADES:
            steps = self.quests[qid]["Steps"]
            spawn = steps[2]["Spawn"]
            with self.subTest(qid):
                self.assertEqual((spawn["Name"], spawn["TemplateId"], spawn["Region"]), ("Martley", 700000012, 51))
                self.assertLess(math.dist((spawn["X"], spawn["Y"]), camp), 500)
                self.assertEqual(point(steps[2]["Marker"]), (51, spawn["X"], spawn["Y"], spawn["Z"]))
                self.assertEqual(steps[3]["Issuer"], "Adam Glaze")  # a lost body: the standing Martley is gone

    # #119
    def test_every_linked_camp_member_is_in_the_world_near_its_callers(self):
        groups = {g["Name"]: g for g in self.extra["Links"]}
        self.assertEqual(sorted(groups), ["Delfina's fire", "Sir Dillus's tower", "the Savant and his pet",
                                          "the courier's fire"])
        self.assertEqual(groups["Delfina's fire"]["Callers"], ["b09ebff4-6f36-5f47-bb41-48161840d41c"])
        for name, group in groups.items():
            where = {m: self.mob(m, "Region", "X", "Y") for m in group["Members"]}
            for caller in group.get("Callers") or group["Members"]:
                for member, at in where.items():
                    with self.subTest(name, caller=caller, member=member):
                        self.assertIsNotNone(at)
                        self.assertEqual(at[0], where[caller][0])
                        self.assertLessEqual(math.dist(at[1:], where[caller][1:]), group["Range"])

    def test_the_wizardess_stands_by_the_couriers_fire(self):
        self.assertLessEqual(math.dist(self.mob(WIZARDESS, "X", "Y"), self.mob(COURIER, "X", "Y")), 200)
        self.assertEqual(self.mob(WIZARDESS, "Z"), self.mob(COURIER, "Z"))


if __name__ == "__main__":
    unittest.main()

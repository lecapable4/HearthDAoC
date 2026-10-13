"""The Guild of Shadows epic's monsters, camps, markers and items as the period had them (owner's choices 2026-10-12,
research ~/Games/DAoC/research/dillus-guards-2026-10-12/decisions.md on the owner's machine).

Each fix names its period source where it is made: deploy/bin/mob_fixes.json (rows, templates, quest givers, item
icons), deploy/bin/quest_camps.json (the camps upstream archived as "post-legacy" and the fork copies back) and
deploy/hearthdaoc-quests.json (the quests whose map markers or event spawns move: "Replace" entries). The world tests
run world_fixes on a copy of a clean classic world (HDC_TEST_WORLD) and read upstream's classic-quests.json
(HDC_CLASSIC_QUESTS) merged with the fork's file, as ClassicQuests merges them.
"""
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(DEPLOY, "bin"))

import world_fixes as wf  # noqa: E402
from tests.test_quest_reachability import EXTRA_QUESTS, TEST_WORLD, UPSTREAM_QUESTS, merged_chat, offered  # noqa: E402
from tests.test_quest_rewards import custom_steps  # noqa: E402

CAMPS = os.path.join(DEPLOY, "bin", "quest_camps.json")
CHAINS = os.path.join(DEPLOY, "bin", "epic_chains_data.json")
SIR_DILLUS = "76adce5b-d53f-5618-ada6-76537678ece5"
TOWER = (1, 478515, 397085, 6118)  # upstream's archived Sir Dillus inside the tower, loc 60723, 28445
GRIMARTH = "1e9635f8-d760-4bb3-adfe-7360ef400bd0"
DELFINA = "b09ebff4-6f36-5f47-bb41-48161840d41c"
COURIER = "29945a96-6a08-51f5-8df9-f63612026614"
ARMSMAN = "3bbd91f2-861a-4db9-8c51-58c611379fa3"  # by the isolationists' tent
SEER = "4cb2f5bd-ba84-5372-af34-99c83b60f672"
TWR = "0acf83c7-1577-419d-9b18-fc03bce1f8b3"
BRODIC = "77d83187-b069-57fc-849c-5a6c20dd2732"
REGAL_25 = [21304, 21305, 21306, 21307, 21308, 21309]
REGAL_30 = [21489, 21490, 21491, 21492, 21493, 21494]
STRANGE_BEINGS = [20476, 20477, 20478, 20479, 20480, 20481]
DECEIT_45 = [21295, 21296, 21297, 21298, 21299]
EADIG = "3da67908-4a4c-47d9-90b7-d9cd9c76d5ed"
ICONS = {  # Id_nb: (Model, Color or None)
    "cq_book_of_lore": (500, None), "cq_renegade_diary": (500, None),
    "cq_crediac_stone": (514, None), "cq_cythraul_skull": (540, None),
    "cq_supplies": (488, None), "cq_tepok_s_sack": (488, None),
    "cq_arawnite_orders": (499, None), "cq_delfina_s_reports": (499, None),
    "cq_document_for_scribe_veral": (603, None), "cq_dwarven_dispatch": (603, None),
    "cq_dispatch_for_twr_ap_alsig": (603, None), "cq_isolationist_documents": (603, None),
    "cq_alb_death_dancer": (4, None), "cq_alb_dazzle": (4, None), "cq_alb_glitter": (20, None),
    "cq_alb_lucky_pebble": (115, None),
    "InfiltratorEpicHelm": (62, None), "MercenaryEpicHelm": (63, None), "ReaverEpicHelm": (63, None),
    "CabalistEpicHelm": (822, None), "NecromancerEpicHelm": (822, None),
    "cq_alb_cloak_of_forgotten_curses": (96, None), "cq_alb_cloak_of_murky_secrets": (96, 43),
}


def chain():
    with open(CHAINS, encoding="utf-8") as f:
        data = json.load(f)
    return list(data["classes"]), data["steps"]


def camps():
    with open(CAMPS, encoding="utf-8") as f:
        return json.load(f)["camps"]


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


@unittest.skipUnless(TEST_WORLD and UPSTREAM_QUESTS,
                     "needs HDC_TEST_WORLD (a clean classic world) and upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
class EpicPeriodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "world.db")
        shutil.copyfile(TEST_WORLD, cls.db)
        cls.changes = wf.apply(cls.db)
        cls.conn = sqlite3.connect(cls.db)
        cls.steps = custom_steps()
        cls.classes, cls.chain = chain()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def mob(self, mob_id, *columns):
        return self.conn.execute(f"SELECT {', '.join(columns)} FROM Mob WHERE Mob_ID=?", (mob_id,)).fetchone()

    def near(self, mob_id, radius, names):
        region, x, y = self.mob(mob_id, "Region", "X", "Y")
        marks = ", ".join("?" * len(names))
        return self.conn.execute(
            f"SELECT Mob_ID, X, Y, RoamingRange FROM Mob WHERE Region=? AND lower(Name) IN ({marks}) "
            "AND (X-?)*(X-?) + (Y-?)*(Y-?) <= ?", (region, *names, x, x, y, y, radius * radius)).fetchall()

    def marker(self, qid, step):
        m = self.steps[str(qid)][step]["Marker"]
        return m["Region"], m["X"], m["Y"], m["Z"]

    def template(self, template_id, *columns):
        return self.conn.execute(f"SELECT {', '.join(columns)} FROM NpcTemplate WHERE TemplateId=?", (template_id,)).fetchone()

    # Level 25, Regal Nobility: Sir Dillus "inside the tower that is just at Llyn Barfog entrance. Loc 60600, 28400".
    def test_sir_dillus_stands_in_the_renegade_tower_and_his_marker_with_him(self):
        self.assertEqual(self.mob(SIR_DILLUS, "Region", "X", "Y", "Z"), TOWER)
        for qid in REGAL_25:
            with self.subTest(qid):
                self.assertEqual(self.marker(qid, 1), TOWER)

    def test_sir_dillus_and_lieutenant_grimarth_attack_like_their_guards(self):
        guards = self.template(13028, "AggroLevel", "AggroRange")
        for template in (13031, 13020):
            with self.subTest(template):
                self.assertEqual(self.template(template, "AggroLevel", "AggroRange"), guards)

    def test_lieutenant_grimarth_is_back_by_the_tower(self):
        self.assertEqual(self.mob(GRIMARTH, "Name", "Region", "X", "Y", "Z"), ("Lieutenant Grimarth", 1, 478100, 397136, 5980))

    def test_the_cythraul_marker_points_at_their_camp(self):
        for qid in REGAL_25:
            region, x, y, _ = self.marker(qid, 3)
            with self.subTest(qid):
                self.assertEqual(region, 1)
                cythraul = self.conn.execute("SELECT X, Y FROM Mob WHERE Region=1 AND lower(Name)='cythraul'").fetchall()
                self.assertGreaterEqual(sum(distance((x, y), c) <= 1500 for c in cythraul), 5)

    # Level 43: Delfina, "a camp of Tylwyth Teg elves. There is one among them named Delfina. She carries the reports".
    def test_delfina_is_a_level_45_tylwyth_teg_huntress(self):
        self.assertEqual(self.mob(DELFINA, "Model", "Gender", "Size", "Level", "FactionID"), (348, 2, 60, 45, 62))

    def test_delfina_has_her_camp_and_two_rangers_by_the_fire(self):
        rangers = self.near(DELFINA, 1250, ["tylwyth teg ranger"])
        self.assertEqual(len(rangers), 22)
        guards = [r for r in rangers if distance(r[1:3], self.mob(DELFINA, "X", "Y")) <= 250]
        self.assertEqual(sorted(g[0] for g in guards),
                         ["99755b89-b83f-4f2e-bf3b-84767b709ad6", "a95e6d6f-0f45-4cbd-a527-97467780ea80"])
        self.assertEqual({g[3] for g in guards}, {0})

    # Level 45: the courier "is next to the tent and he is linked to the two by the fire".
    def test_the_isolationist_courier_stands_in_his_camp(self):
        self.assertLessEqual(distance(self.mob(COURIER, "X", "Y"), self.mob(ARMSMAN, "X", "Y")), 300)
        self.assertEqual(self.mob(COURIER, "Z"), self.mob(ARMSMAN, "Z"))
        names = ["isolationist " + kind for kind in
                 ("armsman", "cleric", "mercenary", "paladin", "scout", "sorcerer", "wizardess")]
        self.assertGreaterEqual(len(self.near(COURIER, 6500, names)), 39)

    def test_the_couriers_marker_follows_him_into_his_camp(self):
        courier = self.mob(COURIER, "Region", "X", "Y", "Z")
        for qid in DECEIT_45:
            with self.subTest(qid):
                self.assertEqual(self.marker(qid, 2), courier)

    def test_the_infiltrators_45_ends_at_master_eadigs_marker(self):
        self.assertEqual(self.marker(21297, 7), self.mob(EADIG, "Region", "X", "Y", "Z"))

    # Level 48: the Ellyll Seer in his village.
    def test_the_ellyll_seer_has_his_village(self):
        self.assertEqual(len(self.near(SEER, 1500, ["ellyll guard", "ellyll villager"])), 36)

    def test_every_camp_row_comes_from_upstreams_archive(self):
        clean = sqlite3.connect(f"file:{TEST_WORLD}?mode=ro", uri=True)
        try:
            for camp in camps():
                for mob_id in camp["ids"]:
                    with self.subTest(camp["name"], mob_id=mob_id):
                        row = clean.execute("SELECT lower(Name) FROM offline_classic165_removed_mobs WHERE Mob_ID=?",
                                            (mob_id,)).fetchone()
                        self.assertIsNotNone(row)
                        self.assertIn(row[0], [n.lower() for n in camp["names"]])
                        self.assertIsNone(clean.execute("SELECT 1 FROM Mob WHERE Mob_ID=?", (mob_id,)).fetchone())
                        self.assertIsNotNone(self.mob(mob_id, "Mob_ID"))
        finally:
            clean.close()

    def test_period_levels(self):
        self.assertEqual(self.template(12438, "Level"), ("34",))  # Savant, blue at 40
        self.assertEqual(self.template(12435, "Level"), ("39-43",))  # Overseer Tepok, yellow at 43
        self.assertEqual(self.mob(TWR, "Level"), (18,))  # "Twr ap Alsig 18 - 18"
        for qid in REGAL_30:  # the Arawnite Assassin, yellow at 30
            with self.subTest(qid):
                self.assertEqual(self.steps[str(qid)][2]["Spawn"]["Level"], 30)

    def test_brodic_roams(self):
        self.assertEqual(self.mob(BRODIC, "RoamingRange"), (3000,))

    def test_the_water_elementals_marker_points_at_their_period_spot(self):
        for qid in STRANGE_BEINGS:
            for step in (3, 4):
                with self.subTest(qid, step=step):
                    self.assertEqual(self.marker(qid, step), (51, 547111, 527782, 3080))

    def test_the_infiltrator_chain_comes_from_master_eadig(self):
        n = self.classes.index("Infiltrator")
        ids = [self.chain[step]["ids"][n] for step in ("7", "7closed", "11", "15", "40", "43", "45", "48")]
        for qid in ids:
            with self.subTest(qid):
                self.assertEqual(self.conn.execute("SELECT StartName FROM DataQuest WHERE ID=?", (qid,)).fetchone(),
                                 ("Master Eadig",))
        target, step_text, source = self.conn.execute(
            "SELECT TargetName, StepText, SourceText FROM DataQuest WHERE ID=21297").fetchone()
        self.assertEqual(target.split("|")[-1], "Master Eadig;10")
        self.assertIn("Master Eadig", step_text.split("|")[-1])
        for qid in ids:
            row = self.conn.execute("SELECT * FROM DataQuest WHERE ID=?", (qid,)).fetchone()
            with self.subTest(qid, check="no Edric"):
                self.assertNotIn("Edric", " ".join(str(v) for v in row))
        with open(EXTRA_QUESTS, encoding="utf-8") as f:
            chat = json.load(f)["Chat"]
        self.assertNotIn("Master Edric", chat)
        self.assertIn("interested@20435", chat["Master Eadig"])

    def test_the_cabalist_40_comes_from_magus_agyfen(self):
        accept, giver = self.conn.execute("SELECT AcceptText, StartName FROM DataQuest WHERE ID=20170").fetchone()
        self.assertEqual(giver, "Magus Agyfen")
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            chat = merged_chat(json.load(f).get("Chat"), json.load(open(EXTRA_QUESTS, encoding="utf-8")).get("Chat"))
        description, = self.conn.execute("SELECT Description FROM DataQuest WHERE ID=20170").fetchone()
        self.assertIn(accept, offered([description], chat["magus agyfen"], 20170))
        # And 43 still answers with Agyfen's own 43 line ([profitable]).
        accept43, description43 = self.conn.execute("SELECT AcceptText, Description FROM DataQuest WHERE ID=20434").fetchone()
        self.assertIn(accept43, offered([description43], chat["magus agyfen"], 20434))

    def test_item_icons(self):
        for id_nb, (model, color) in ICONS.items():
            with self.subTest(id_nb):
                row = self.conn.execute("SELECT Model, Color FROM ItemTemplate WHERE Id_nb=?", (id_nb,)).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], model)
                if color is not None:
                    self.assertEqual(row[1], color)

    def test_the_camps_are_copied_back_once(self):
        line = [c for c in self.changes if c.startswith("Quest camps:")]
        self.assertEqual(len(line), 1, self.changes)
        self.assertEqual(wf.apply(self.db), [])


if __name__ == "__main__":
    unittest.main()

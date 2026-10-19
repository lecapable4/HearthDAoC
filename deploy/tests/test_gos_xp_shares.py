"""The Guild of Shadows quest XP as a share of the player's current level (owner decision 1.c, 2026-10-18, #138).

Upstream 0.36 pays a classic quest stage's XP as the larger of the row's RewardXP and a share of the player's current
level (ClassicQuests.ScaleXP: the share times the XP from that level to the next; the shares are classic-quests.json's
XpShares, one per stage, and a stage pays only when its RewardXP is above 0). The owner's 2026-10-09 rule for the
chain, a quarter of a level for 7 and 11 and a tenth from 15 on, is now such a share, at each step's last stage, where
deploy/bin/epic_chains.py pays the chain's XP; its RewardXP, the share at the step's minimum level, stays the floor.
deploy/hearthdaoc-quests.json carries the shares for every class row: inside the Replace entries of the steps the fork
rebuilt (7si, 11, 11si, 25, 30, 45, the Heretic's rows too), and in entries ClassicQuests.Merge lays onto upstream's
(7, the closed Supply Runs, 15, 20, 40, 43, 48; ClassicQuestOverlay). Level 43's also drop upstream's stage-3
greeting, which asks about stage 5's dispatch (R6); level 25's Replace entries leave out upstream's stage-4 greeting,
which is the stage's own text (R21).

The world test runs world_fixes on a copy of a clean classic world (HDC_TEST_WORLD) and merges upstream's
classic-quests.json (HDC_CLASSIC_QUESTS) with the fork's file as ClassicQuests.Merge does (merge_quests).
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(DEPLOY, "bin"))

import epic_chains  # noqa: E402
import quest_dialogue as qd  # noqa: E402
import world_fixes as wf  # noqa: E402
from tests.test_quest_reachability import EXTRA_QUESTS, TEST_WORLD, UPSTREAM_QUESTS, merge_quests  # noqa: E402

# The owner's share of the player's current level for each step of the chain (epic_chains_data.json "steps").
SHARES = {"7": 0.25, "7closed": 0.25, "7si": 0.25, "11": 0.25, "11si": 0.25, "15": 0.1, "20": 0.1, "25": 0.1,
          "30": 0.1, "40": 0.1, "43": 0.1, "45": 0.1, "48": 0.1}
# The Heretic's rows of the steps the fork rebuilt (class 33, which disabled_classes keeps out of play): their Replace
# entries carry the share too, so the data is the same for every row.
HERETIC = {"7si": 20481, "11si": 20472, "25": 21309, "30": 21494}
# The steps whose entries replace upstream's (their markers, items and spawns are the fork's): shares included.
REBUILT = ("7si", "11", "11si", "25", "30", "45")
LEVEL_43_GREET = "Were you able to deliver the dispatch to Twr ap Alsig?"
LEVEL_25_STAGE_4 = "I still seek proof of your deeds. Do you have something for me?"


def chain_rows():
    """{quest ID: step}: every class row of the chain's steps, the Heretic's too (the level-50 quests pay coin only)."""
    rows = {qid: step for step, info in epic_chains.load_data()["steps"].items() if step in SHARES
            for qid in info["ids"] if qid is not None}
    rows.update({qid: step for step, qid in HERETIC.items()})
    return rows


def extra_quests():
    with open(EXTRA_QUESTS, encoding="utf-8") as f:
        return json.load(f)["Quests"]


class ShareDataTests(unittest.TestCase):
    """deploy/hearthdaoc-quests.json (no world needed)."""

    def setUp(self):
        self.rows, self.extra = chain_rows(), extra_quests()

    def test_the_rule_covers_every_step_of_the_chain_but_level_50(self):
        self.assertEqual(sorted(SHARES), sorted(set(epic_chains.load_data()["steps"]) - {"50"}))
        self.assertEqual(len(self.rows), 68)

    def test_every_row_has_the_owners_share_at_its_last_stage(self):
        for qid, step in self.rows.items():
            with self.subTest(quest=qid, step=step):
                shares = self.extra[str(qid)]["XpShares"]
                self.assertGreater(len(shares), 1)
                self.assertEqual(shares, [0.0] * (len(shares) - 1) + [SHARES[step]])

    def test_the_rebuilt_steps_carry_their_shares_in_their_replace_entries(self):
        for qid, step in self.rows.items():
            with self.subTest(quest=qid, step=step):
                entry = self.extra[str(qid)]
                if step in REBUILT:
                    self.assertIs(entry["Replace"], True)
                    self.assertEqual([n for n, s in enumerate(entry["Steps"]) if s and "Greet" in s], [])
                else:  # only what ClassicQuestOverlay lays onto upstream's entry
                    self.assertEqual(set(entry), {"XpShares", "Steps"} if step == "43" else {"XpShares"})

    def test_level_43_drops_upstreams_stage_3_greeting(self):
        # Stage 3 brings Tepok's sack to Captain Rhodri, whose own text asks for it; the dispatch is stage 5's.
        stage_3 = next(e for e in qd.load_data()["quests"] if e.get("step") == "43")["set"]["TargetText"][2]
        self.assertIn("Were you able to retrieve Tepok's precious sack?", stage_3)
        for qid, step in self.rows.items():
            if step == "43":
                with self.subTest(quest=qid):
                    self.assertEqual(self.extra[str(qid)]["Steps"], [None, None, None, {"Greet": ""}])


@unittest.skipUnless(UPSTREAM_QUESTS, "needs upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
class MergedShareTests(unittest.TestCase):
    """Upstream's classic-quests.json merged with the fork's file, as ClassicQuests.Merge merges them."""

    @classmethod
    def setUpClass(cls):
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            cls.upstream = json.load(f)["Quests"]
        cls.extra = extra_quests()
        cls.merged = merge_quests(cls.upstream, cls.extra)
        cls.rows = chain_rows()

    def test_every_row_pays_the_owners_share_with_one_share_per_stage(self):
        for qid in self.rows:
            with self.subTest(quest=qid):
                self.assertEqual(self.merged[str(qid)]["XpShares"], self.extra[str(qid)]["XpShares"])
                self.assertEqual(len(self.merged[str(qid)]["XpShares"]), len(self.upstream[str(qid)]["XpShares"]))

    def test_level_43_keeps_upstreams_steps_but_the_stage_3_greeting(self):
        for qid, step in self.rows.items():
            if step == "43":
                merged, upstream = self.merged[str(qid)]["Steps"], self.upstream[str(qid)]["Steps"]
                with self.subTest(quest=qid):
                    self.assertEqual(upstream[3]["Greet"], LEVEL_43_GREET)
                    self.assertEqual(merged[3], {key: value for key, value in upstream[3].items() if key != "Greet"})
                    self.assertEqual(merged[:3] + merged[4:], upstream[:3] + upstream[4:])

    def test_level_25_says_its_stage_4_line_once(self):
        # Upstream's stage-4 greeting is the stage's TargetText (quest_dialogue.json), which Twr ap Alsig says too.
        stage_4 = next(e for e in qd.load_data()["quests"] if e.get("step") == "25")["set"]["TargetText"][3]
        self.assertEqual(stage_4, LEVEL_25_STAGE_4)
        for qid, step in self.rows.items():
            if step == "25":
                with self.subTest(quest=qid):
                    self.assertEqual(self.upstream[str(qid)]["Steps"][4]["Greet"], LEVEL_25_STAGE_4)
                    self.assertNotIn("Greet", self.merged[str(qid)]["Steps"][4] or {})


@unittest.skipUnless(TEST_WORLD and UPSTREAM_QUESTS, "needs HDC_TEST_WORLD (a clean classic world database) and "
                                                     "upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
class WorldShareTests(unittest.TestCase):
    """The merged shares against the quest rows world_fixes leaves on a copy of a clean classic world."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "world.db")
        shutil.copyfile(TEST_WORLD, cls.db)
        wf.apply(cls.db)
        cls.conn = sqlite3.connect(cls.db)
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            cls.merged = merge_quests(json.load(f)["Quests"], extra_quests())

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_the_stage_with_the_share_pays_xp(self):
        # DataQuest scales a stage's XP only when the stage's RewardXP is above 0: a share elsewhere would pay nothing.
        for qid in chain_rows():
            step_types, reward_xp = self.conn.execute("SELECT StepType, RewardXP FROM DataQuest WHERE ID=?",
                                                      (qid,)).fetchone()
            with self.subTest(quest=qid, RewardXP=reward_xp):
                shares, xp = self.merged[str(qid)]["XpShares"], [int(value) for value in reward_xp.split("|")]
                self.assertEqual(len(shares), len(step_types.split("|")))
                self.assertEqual(len(xp), len(shares))
                self.assertEqual([n for n, share in enumerate(shares, 1) if share > 0 and xp[n - 1] <= 0], [])


if __name__ == "__main__":
    unittest.main()

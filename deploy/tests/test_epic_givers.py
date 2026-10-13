"""The Guild of Shadows epic's level 43 comes from each class's own trainer, and level 40's rewards are seen before
they are chosen (owner 2026-10-12).

Level 43: Allakhazam's "Lord of Deceit (level 43)" (cquest 363, every capture from 2002-09-18) has "Start NPC:
Trainer"; its walkthrough's "Talk to Magus Agyfen in Camelot" was a Cabalist's (Rhodri: "Not to worry Cabalist!").
Upstream gave every class's 43 to Magus Agyfen, a Cabalist trainer. deploy/bin/mob_fixes.json gives it to the
trainer who gives the class's 40 (and 45 and 48): Master Eadig for Infiltrators (owner's choice, 2026-10-12; the period
Infiltrator account of 40 names him); Cabalists keep Agyfen, who also gives their 40, as every period Cabalist source
has him. A trainer offers
both 40 and 43 with the period keyword "[interested]", so deploy/hearthdaoc-quests.json's Chat holds Agyfen's reply
for 43 as "interested@<quest ID>", which ClassicQuests.ChatReply prefers while the player may take that quest.

Level 40: ClassicQuests shows the reward a player names (its examine window) and gives it on "I'll take it"; Rhodri's
lines in deploy/bin/quest_dialogue.json say so. The world tests run world_fixes on a copy of a clean classic world
(HDC_TEST_WORLD).
"""
import json
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

TEST_WORLD = os.environ.get("HDC_TEST_WORLD")
EXTRA_QUESTS = os.path.join(DEPLOY, "hearthdaoc-quests.json")
CHAINS = os.path.join(DEPLOY, "bin", "epic_chains_data.json")
AGYFEN = "Magus Agyfen"


def chain():
    with open(CHAINS, encoding="utf-8") as f:
        data = json.load(f)
    return list(data["classes"]), data["steps"]


def chat():
    with open(EXTRA_QUESTS, encoding="utf-8") as f:
        return json.load(f)["Chat"]


@unittest.skipUnless(TEST_WORLD, "needs HDC_TEST_WORLD (a clean classic world)")
class EpicGiverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "world.db")
        shutil.copyfile(TEST_WORLD, cls.db)
        wf.apply(cls.db)
        cls.conn = sqlite3.connect(cls.db)
        cls.classes, cls.steps = chain()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def row(self, qid, *columns):
        return self.conn.execute(f"SELECT {', '.join(columns)} FROM DataQuest WHERE ID=?", (qid,)).fetchone()

    def test_43_comes_from_the_trainer_who_gives_the_classs_40(self):
        # Every class but the Cabalist has one trainer for 40, 45 and 48; the Cabalist's 40 and 43 are Magus Agyfen's
        # (every period Cabalist source names him), 45 and 48 Magus Isen's.
        for n, cls in enumerate(self.classes):
            with self.subTest(cls):
                giver = {step: self.row(self.steps[step]["ids"][n], "StartName")[0] for step in ("40", "43", "45", "48")}
                self.assertEqual(giver["43"], giver["40"])
                if cls == "Cabalist":
                    self.assertEqual((giver["40"], giver["45"], giver["48"]), (AGYFEN, "Magus Isen", "Magus Isen"))
                else:
                    self.assertEqual(len({giver["40"], giver["45"], giver["48"]}), 1, giver)

    def test_each_43_trainer_says_agyfens_lines_for_43(self):
        lines = chat()
        for n, cls in enumerate(self.classes):
            qid = self.steps["43"]["ids"][n]
            giver, accept = self.row(qid, "StartName", "AcceptText")
            with self.subTest(cls, giver=giver):
                own = lines[giver].get(f"interested@{qid}") if giver != AGYFEN else lines[giver]["interested"]
                self.assertEqual(own, lines[AGYFEN]["interested"])
                self.assertIn(f"[{accept}]", own)
                self.assertIn("[interested]", self.row(qid, "Description")[0])

    def test_a_quests_own_reply_names_a_quest_its_npc_gives(self):
        for npc, replies in chat().items():
            for key in replies:
                if "@" not in key:
                    continue
                qid = int(key.rsplit("@", 1)[1])
                with self.subTest(npc, key=key):
                    self.assertEqual(self.row(qid, "StartName"), (npc,))

    def test_rhodri_shows_the_level_40_rewards_before_one_is_taken(self):
        for n, cls in enumerate(self.classes):
            qid = self.steps["40"]["ids"][n]
            source, step, target = (text.split("|")[-1] for text in self.row(qid, "SourceText", "StepText", "TargetText"))
            offered = re.findall(r"\[([^\]]+)\]", source)
            with self.subTest(cls):
                self.assertTrue(offered)
                self.assertIn("I will show it to you", source)
                self.assertIn("I will show it to you", target)
                self.assertEqual(re.findall(r"\[([^\]]+)\]", target), offered)
                self.assertIn("I'll take it", step)
                for name in offered:
                    self.assertIn(name, step)


if __name__ == "__main__":
    unittest.main()

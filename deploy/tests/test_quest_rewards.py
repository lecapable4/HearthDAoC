"""No classic quest hands its reward twice (owner 2026-10-11: two Belts of Animation from level 5's "Cleric Mulgrut",
two Cloudy Green Stones from level 4's "Zombie Problem", of which only one sold).

DataQuest hands every template in FinalRewardItemTemplates. From the period guides' "You receive X from <monster>!"
upstream's generator made two templates of X, a plain cq_X ("Classic quest reward ((quest item))") and a realm
cq_<realm>_X, and ten quests hand both: both as the final reward, or one on the kill step (StepItemTemplates) or a
trade (classic-quests.json) and the other as the final reward. The period gave one. deploy/bin/mob_fixes.json keeps
one: the realm template, on the kill step where the period's monster dropped it, and a trade's own output.

The world tests run world_fixes on a copy of a clean classic world (HDC_TEST_WORLD). The trades, choices and grants
are in upstream's classic-quests.json (HDC_CLASSIC_QUESTS, as in test_quest_reachability) and the fork's
deploy/hearthdaoc-quests.json, merged as ClassicQuests merges them.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(DEPLOY, "bin"))

import world_fixes as wf  # noqa: E402
from tests.test_quest_reachability import EXTRA_QUESTS, TEST_WORLD, UPSTREAM_QUESTS  # noqa: E402

# DataQuest's eStepType. Kill, Interact, Whisper, Search and Collect hand the step's item when the step is done;
# Deliver and DeliverFinish hand it when the step starts, and its target takes it; the other finishing steps hand
# none (FinishQuest gives only the final rewards).
HANDS_ON_COMPLETION = {0, 4, 6, 8, 10}
DELIVERY = {2, 3}
COLLECT = {10, 11}
# The quests that handed one reward twice on upstream's world.
DOUBLED = {20022, 20116, 20137, 20207, 20208, 20209, 20320, 20510, 20515, 20637}


def custom_steps():
    """{quest ID: [step info]}: upstream's classic-quests.json, with the fork's entries that replace upstream's."""
    with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
        quests = dict(json.load(f)["Quests"])
    with open(EXTRA_QUESTS, encoding="utf-8") as f:
        for qid, info in json.load(f)["Quests"].items():
            if not qid.startswith("_") and (info.get("Replace") or qid not in quests):
                quests[qid] = info
    return {qid: info.get("Steps") or [] for qid, info in quests.items()}


def templates(text):
    """The template IDs of a "|"-separated column, one per stage, without a drop chance (";50")."""
    return [entry.split(";")[0].strip().lower() for entry in (text or "").split("|")]


def doubled(conn, steps_of):
    """[(quest ID, item name, [how each copy is handed])] for every quest that hands the player two items of one name
    and keeps both, one of them as its final reward."""
    names = {template.lower(): name.lower() for template, name in conn.execute("SELECT Id_nb, Name FROM ItemTemplate")}
    found = []
    for qid, types, items, collect, final in conn.execute(
            "SELECT ID, StepType, StepItemTemplates, CollectItemTemplate, FinalRewardItemTemplates FROM DataQuest"):
        types = [int(t) if t.strip().isdigit() else -1 for t in (types or "").split("|")]
        items, collect = templates(items), templates(collect)
        steps = steps_of.get(str(qid), [])

        def custom(n):
            step = steps[n] if n < len(steps) and steps[n] else {}
            return step, step.get("Custom") or {}

        def taken_after(n, item):
            for m in range(n + 1, len(types) + 1):
                if types[m - 1] in DELIVERY and m - 1 < len(items) and items[m - 1] == item:
                    return True
                if types[m - 1] in COLLECT and m - 1 < len(collect) and collect[m - 1] == item:
                    return True
                later = custom(m)[1]
                if item in {k.lower() for k in later.get("Trades") or {}}:
                    return True
                if later.get("Consume") and (later.get("Item") or "").lower() == item:
                    return True
            return False

        kept = []
        for n, step_type in enumerate(types, 1):
            item = items[n - 1] if n - 1 < len(items) else ""
            if item and step_type in HANDS_ON_COMPLETION and not taken_after(n, item):
                kept.append((f"step {n}", item))
            step, extra = custom(n)
            kept += [(f"trade at step {n}", out.lower()) for out in (extra.get("Trades") or {}).values() if out]
            kept += [(f"choice at step {n}", out.lower()) for out in (extra.get("Choices") or {}).values() if out]
            kept += [(f"grant at step {n}", g.lower()) for g in step.get("Grant") or [] if g and not taken_after(n, g.lower())]
        kept += [("final reward", item) for item in templates(final) if item]
        by_name = defaultdict(list)
        for how, item in kept:
            if item in names:  # DataQuest skips a template the world lacks
                by_name[names[item]].append(f"{how}: {item}")
        for name, copies in sorted(by_name.items()):
            if len(copies) > 1 and any(c.startswith("final reward") for c in copies):
                found.append((qid, name, copies))
    return sorted(found)


@unittest.skipUnless(TEST_WORLD and UPSTREAM_QUESTS,
                     "needs HDC_TEST_WORLD (a clean classic world) and upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
class QuestRewardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.steps = custom_steps()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "world.db")
        shutil.copyfile(TEST_WORLD, cls.db)
        wf.apply(cls.db)
        cls.conn = sqlite3.connect(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_upstreams_world_hands_these_ten_rewards_twice(self):
        # The check finds what the owner met: the scan behind the fix, kept so a later upstream world is checked too.
        clean = sqlite3.connect(f"file:{TEST_WORLD}?mode=ro", uri=True)
        try:
            found = doubled(clean, self.steps)
        finally:
            clean.close()
        self.assertEqual({qid for qid, _, _ in found}, DOUBLED, found)
        self.assertIn((20207, "belt of animation", ["final reward: cq_belt_of_animation",
                                                    "final reward: cq_alb_belt_of_animation"]), found)

    def test_no_quest_hands_one_reward_twice(self):
        self.assertEqual(doubled(self.conn, self.steps), [])

    def reward(self, qid):
        return self.conn.execute("SELECT StepItemTemplates, FinalRewardItemTemplates FROM DataQuest WHERE ID=?",
                                 (qid,)).fetchone()

    def test_mulgrut_gives_one_belt(self):
        # "You receive a Belt of Animation from Mulgrut Maggot!" The killing blow finishes the quest (KillFinish).
        self.assertEqual(self.reward(20207)[1], "cq_alb_belt_of_animation")

    def test_wileys_boots_come_from_wiley_and_hurg_pays(self):
        # "Kill him and you get Wiley's Boots." Hurg: "You are rewarded 10 silver and some copper!"
        self.assertEqual(self.reward(20116), ("cq_mid_wiley_s_boots|", ""))
        self.assertEqual(self.conn.execute("SELECT RewardMoney FROM DataQuest WHERE ID=20116").fetchone(), ("0|1000",))

    def test_gronyr_gives_one_stone_for_each_tail(self):
        # "Give the tails back to Gronyr and he will give you a cloudy green stone (worth about 50 copper) for each one."
        self.assertEqual(self.reward(20515)[1], "")
        trades = [step["Custom"]["Trades"] for step in self.steps["20515"] if step and (step.get("Custom") or {}).get("Trades")]
        self.assertEqual(trades, [{"cq_rotting_hog_tail": "cq_cloudy_green_stone"}])

    def test_harwin_makes_the_weapon_of_the_cherts_shape(self):
        self.assertEqual(self.reward(20510)[1], "")


if __name__ == "__main__":
    unittest.main()
